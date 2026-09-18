"""TEST-3 STILL 모션 효과 (명세서 §28, §15)."""

from __future__ import annotations

import pytest

from src.media.ffmpeg import FFmpeg
from src.scene.models import MOTIONS
from src.scene.still import build_fit_chain, build_still_filter
from tests.conftest import make_image, needs_ffmpeg


# ---------------------------------------------------------------------------
# 필터 체인 구성
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("motion", MOTIONS)
def test_every_documented_motion_builds_a_chain(motion):
    chain = build_still_filter(motion, 1080, 1920, 30, 120)
    assert "format=yuv420p" in chain
    assert "setsar=1" in chain


def test_static_has_no_zoompan():
    assert "zoompan" not in build_still_filter("static", 1080, 1920, 30, 120)


@pytest.mark.parametrize("motion", ["slow_zoom_in", "slow_zoom_out", "slow_pan_left", "slow_pan_right"])
def test_moving_motions_use_zoompan(motion):
    assert "zoompan=" in build_still_filter(motion, 1080, 1920, 30, 120)


def test_unknown_motion_falls_back_to_static():
    assert build_still_filter("스핀", 1080, 1920, 30, 120) == build_still_filter("static", 1080, 1920, 30, 120)


def test_motion_amount_is_bounded():
    """명세서 §15 — 확대/팬 과도 금지. 기본 이동량은 12%."""
    chain = build_still_filter("slow_zoom_in", 1080, 1920, 30, 120, zoom_amount=0.12)
    assert "0.120000" in chain
    assert "min(on,119)/119" in chain


def test_zoom_out_starts_zoomed_in():
    chain = build_still_filter("slow_zoom_out", 1080, 1920, 30, 120, zoom_amount=0.12)
    assert "1.120000-0.120000" in chain


def test_pan_left_and_right_are_mirrored():
    left = build_still_filter("slow_pan_left", 1080, 1920, 30, 120)
    right = build_still_filter("slow_pan_right", 1080, 1920, 30, 120)
    assert "(1-min(on,119)/119)" in left
    assert "(1-min(on,119)/119)" not in right


def test_single_frame_scene_does_not_divide_by_zero():
    chain = build_still_filter("slow_zoom_in", 1080, 1920, 30, 1)
    assert "/1" in chain  # span이 1로 보정된다


def test_cover_crops_and_never_stretches():
    """명세서 §15 — 입력 이미지 종횡비 유지."""
    chain = build_fit_chain(1080, 1920, fit="cover")
    assert "force_original_aspect_ratio=increase" in chain
    assert "crop=1080:1920" in chain


def test_contain_letterboxes_and_never_stretches():
    chain = build_fit_chain(1080, 1920, fit="contain", background="#101828")
    assert "force_original_aspect_ratio=decrease" in chain
    assert "pad=1080:1920" in chain
    assert "0x101828" in chain


def test_super_sample_raises_working_resolution():
    chain = build_still_filter("slow_zoom_in", 1080, 1920, 30, 120, super_sample=2.0)
    assert "scale=2160:3840" in chain
    assert "s=1080x1920" in chain


def test_working_resolution_is_even():
    """H.264 yuv420p는 짝수 해상도를 요구한다."""
    chain = build_still_filter("slow_zoom_in", 271, 481, 30, 60, super_sample=1.5)
    scale_part = chain.split(":force_original_aspect_ratio")[0]
    width, height = scale_part.removeprefix("scale=").split(":")
    assert int(width) % 2 == 0 and int(height) % 2 == 0


# ---------------------------------------------------------------------------
# 실제 렌더 결과
# ---------------------------------------------------------------------------

@needs_ffmpeg
@pytest.mark.parametrize("motion", MOTIONS)
def test_motion_renders_exact_frame_count(tmp_path, motion):
    ffmpeg = FFmpeg()
    image = make_image(tmp_path / "scene.png", 270, 480)
    out = tmp_path / f"{motion}.mp4"
    frames = 45  # 1.5초 @ 30fps

    chain = build_still_filter(motion, 270, 480, 30, frames, super_sample=1.5)
    ffmpeg.run([
        "-framerate", "30", "-loop", "1", "-i", str(image),
        "-frames:v", str(frames), "-vf", chain,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-pix_fmt", "yuv420p", "-r", "30",
        "-an", str(out),
    ])

    assert out.is_file()
    assert ffmpeg.video_size(out) == (270, 480)
    assert abs(ffmpeg.duration(out) - frames / 30) < 0.05


@needs_ffmpeg
def test_zoom_in_actually_zooms(tmp_path):
    """첫 프레임과 마지막 프레임이 실제로 달라야 모션이 걸린 것이다."""
    from PIL import Image, ImageChops

    ffmpeg = FFmpeg()
    image = make_image(tmp_path / "scene.png", 270, 480)
    frames = 30

    def render(motion: str):
        out = tmp_path / f"{motion}.mp4"
        ffmpeg.run([
            "-framerate", "30", "-loop", "1", "-i", str(image),
            "-frames:v", str(frames),
            "-vf", build_still_filter(motion, 270, 480, 30, frames, super_sample=2.0),
            "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p", "-an", str(out),
        ])
        first, last = tmp_path / f"{motion}-0.png", tmp_path / f"{motion}-1.png"
        ffmpeg.run(["-i", str(out), "-vf", "select=eq(n\\,0)", "-vframes", "1", str(first)])
        ffmpeg.run(["-i", str(out), "-vf", f"select=eq(n\\,{frames - 1})", "-vframes", "1", str(last)])
        return first, last

    def mean_diff(a, b):
        with Image.open(a) as ia, Image.open(b) as ib:
            hist = ImageChops.difference(ia.convert("L"), ib.convert("L")).histogram()
        return sum(i * c for i, c in enumerate(hist)) / sum(hist)

    moving_first, moving_last = render("slow_zoom_in")
    static_first, static_last = render("static")

    assert mean_diff(moving_first, moving_last) > 1.0, "slow_zoom_in인데 화면이 그대로입니다"
    assert mean_diff(static_first, static_last) < 0.5, "static인데 화면이 움직였습니다"
