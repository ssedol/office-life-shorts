"""FEAT-2 STILL 씬 처리 (명세서 §15).

지원 모션: static / slow_zoom_in / slow_zoom_out / slow_pan_left / slow_pan_right

원칙(명세서 §15):
    - 씬당 효과 1개
    - 확대/팬 과도 금지 → 기본 이동량은 12%로 제한
    - 입력 이미지 종횡비 유지 → 늘리지 않고 크롭(cover) 또는 레터박스(contain)만 한다

이 모듈은 ffmpeg 필터 문자열만 만든다. 실제 인코딩은 src/render가 맡으므로
렌더러를 교체해도 모션 정의는 그대로 검증할 수 있다.
"""

from __future__ import annotations

from .models import MOTIONS

FIT_COVER = "cover"
FIT_CONTAIN = "contain"


def _even(value: float) -> int:
    """H.264(yuv420p)는 짝수 해상도를 요구한다."""
    number = int(round(value))
    return number if number % 2 == 0 else number + 1


def _hex_to_ffmpeg_color(value: str | None, fallback: str = "black") -> str:
    if not value:
        return fallback
    text = str(value).strip()
    if text.startswith("#"):
        return "0x" + text[1:]
    return text


def build_fit_chain(
    width: int,
    height: int,
    *,
    fit: str = FIT_COVER,
    background: str | None = None,
) -> str:
    """이미지를 늘리지 않고 width×height에 맞추는 필터 체인."""
    if fit == FIT_CONTAIN:
        color = _hex_to_ffmpeg_color(background, "black")
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={color}"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height}"
    )


def build_still_filter(
    motion: str,
    width: int,
    height: int,
    fps: int,
    total_frames: int,
    *,
    fit: str = FIT_COVER,
    background: str | None = None,
    super_sample: float = 2.0,
    zoom_amount: float = 0.12,
    pan_amount: float = 0.12,
) -> str:
    """정지 이미지 → 모션 클립용 ffmpeg 필터 체인을 만든다.

    Args:
        motion: MOTIONS 중 하나. 모르는 값이면 static으로 떨어뜨린다.
        total_frames: 이 씬이 출력할 총 프레임 수.
        super_sample: zoompan의 정수 좌표 계단 현상을 줄이기 위한 내부 배율.
    """
    if motion not in MOTIONS:
        motion = "static"

    # zoompan은 입력 해상도 격자 위에서 크롭하므로, 목표 해상도보다 크게 잡을수록 움직임이 매끄럽다.
    scale = max(1.0, float(super_sample)) if motion != "static" else 1.0
    work_w = _even(width * scale)
    work_h = _even(height * scale)

    chain = [build_fit_chain(work_w, work_h, fit=fit, background=background)]

    if motion == "static":
        chain.append(f"fps={fps}")
    else:
        # on(출력 프레임 번호)이 0..span 동안 진행도 0→1이 되게 한다.
        span = max(1, int(total_frames) - 1)
        progress = f"min(on,{span})/{span}"
        zoom_peak = 1.0 + float(zoom_amount)
        pan_zoom = 1.0 + float(pan_amount)

        if motion == "slow_zoom_in":
            z = f"1+{zoom_amount:.6f}*{progress}"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif motion == "slow_zoom_out":
            z = f"{zoom_peak:.6f}-{zoom_amount:.6f}*{progress}"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif motion == "slow_pan_right":
            # 화면이 오른쪽으로 이동 = 잘라내는 창이 왼쪽에서 오른쪽으로 간다.
            z = f"{pan_zoom:.6f}"
            x = f"(iw-iw/zoom)*{progress}"
            y = "ih/2-(ih/zoom/2)"
        else:  # slow_pan_left
            z = f"{pan_zoom:.6f}"
            x = f"(iw-iw/zoom)*(1-{progress})"
            y = "ih/2-(ih/zoom/2)"

        chain.append(
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"
        )

    if motion == "static" and (work_w != width or work_h != height):
        chain.append(f"scale={width}:{height}:flags=lanczos")

    chain.append("format=yuv420p")
    chain.append("setsar=1")
    return ",".join(chain)
