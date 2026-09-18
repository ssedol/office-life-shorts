"""FEAT-5 자막 생성 (명세서 §19, §27).

출력:
    subtitles.srt           — 명세서가 요구하는 표준 자막 파일(업로드/검수용)
    subtitles.ass           — 실제 번인 렌더용. 외곽선·강조색·안전영역을 표현하려면 ASS가 필요하다
    subtitle-timeline.json  — 명세서가 요구하는 타임라인 JSON

스타일(명세서 §19):
    굵은 고딕 / 흰 글자 / 짙은 네이비 외곽선 / 중요 단어 노란색 / 최대 2줄 / 가운데 정렬 / 안전영역 유지
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import SubtitleError
from ..scene.timeline import Timeline
from .wrap import Layout, layout_text

log = logging.getLogger(__name__)


@dataclass
class Cue:
    index: int
    scene_id: str
    start: float
    end: float
    layout: Layout
    font_size: int
    shrunk: bool = False

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    @property
    def plain_lines(self) -> list[str]:
        return [line.text for line in self.layout.lines]


@dataclass
class SubtitleResult:
    srt_path: Path
    ass_path: Path
    timeline_path: Path
    cues: list[Cue]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 색 변환
# ---------------------------------------------------------------------------

def hex_to_ass_color(value: str, alpha: int = 0) -> str:
    """#RRGGBB → ASS의 &HAABBGGRR 형식."""
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise SubtitleError(f"색상 형식이 올바르지 않습니다: {value} (#RRGGBB 형식이어야 합니다)")
    try:
        r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError as exc:
        raise SubtitleError(f"색상 형식이 올바르지 않습니다: {value}") from exc
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def format_srt_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    centis = int(round(seconds * 100))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


# ---------------------------------------------------------------------------
# 큐 생성
# ---------------------------------------------------------------------------

def _largest_fitting_font(
    text: str,
    *,
    usable_px: float,
    min_size: int,
    max_size: int,
    max_lines: int,
    markup: str,
    keywords: list[str],
) -> tuple[int, Layout]:
    """max_lines 안에 들어가는 가장 큰 폰트 크기와 그때의 레이아웃을 찾는다.

    최소 크기로도 안 들어가면 최소 크기의 레이아웃을 그대로 돌려준다(글자를 버리지 않는다).
    """
    def attempt(size: int) -> Layout:
        return layout_text(
            text, max_width=usable_px / size, max_lines=max_lines, markup=markup, keywords=keywords
        )

    lo, hi = min_size, max_size
    best: tuple[int, Layout] | None = None

    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = attempt(mid)
        if candidate.overflow:
            hi = mid - 1
        else:
            best = (mid, candidate)
            lo = mid + 1

    if best is not None:
        return best
    return min_size, attempt(min_size)


def build_cues(timeline: Timeline, subtitle_cfg: dict, width: int) -> tuple[list[Cue], list[str]]:
    """타임라인에서 자막 큐를 만든다. 2줄을 넘으면 폰트를 줄여 다시 시도한다."""
    warnings: list[str] = []

    base_size = int(subtitle_cfg.get("fontSize", 66))
    min_size = int(subtitle_cfg.get("minFontSize", max(24, base_size // 2)))
    max_lines = int(subtitle_cfg.get("maxLines", 2))
    markup = str(subtitle_cfg.get("emphasisMarkup", "**"))
    keywords = list(subtitle_cfg.get("emphasisKeywords") or [])

    safe = subtitle_cfg.get("safeArea", {})
    margin_l = int(safe.get("marginLeft", 80))
    margin_r = int(safe.get("marginRight", 80))
    usable_px = max(1, width - margin_l - margin_r)

    #: 설정값 maxCharsPerLine은 "기본 폰트 크기에서의 전각 글자 수" 상한이다.
    configured_max = subtitle_cfg.get("maxCharsPerLine")
    px_limit = usable_px / base_size
    base_max_width = min(float(configured_max), px_limit) if configured_max else px_limit

    cues: list[Cue] = []
    for item in timeline.scenes:
        text = item.scene.subtitle.strip()
        if not text:
            continue

        start = item.subtitle_start
        end = item.subtitle_end
        if end <= start:
            warnings.append(f"{item.scene.id}: 자막 표시 시간이 0이라 건너뜁니다")
            continue

        font_size = base_size
        layout = layout_text(text, max_width=base_max_width, max_lines=max_lines, markup=markup, keywords=keywords)
        shrunk = False

        if layout.overflow:
            # maxLines 안에 들어가는 가장 큰 폰트를 찾는다.
            # 줄 수는 폰트가 작아질수록 단조 감소하므로 이분 탐색이 성립한다.
            # 평균 폭으로 한 번에 계산하면 단어 경계 때문에 한 줄이 더 생기는 경우가 있다.
            font_size, layout = _largest_fitting_font(
                text,
                usable_px=usable_px,
                min_size=min_size,
                max_size=base_size,
                max_lines=max_lines,
                markup=markup,
                keywords=keywords,
            )
            shrunk = font_size < base_size

            if layout.overflow:
                warnings.append(
                    f"{item.scene.id}: 자막이 최소 폰트({min_size}px)에서도 {len(layout.lines)}줄입니다 "
                    f"(명세서 §19 최대 {max_lines}줄). subtitle 문구를 줄이세요: \"{text}\""
                )

        cues.append(
            Cue(
                index=len(cues) + 1,
                scene_id=item.scene.id,
                start=start,
                end=end,
                layout=layout,
                font_size=font_size,
                shrunk=shrunk,
            )
        )

    if not cues:
        raise SubtitleError(
            "표시할 자막이 하나도 없습니다",
            details=["scene-plan.json의 subtitle 필드를 확인하세요 (명세서 §27: 자막 필수)"],
        )

    # 겹침 방지
    for previous, current in zip(cues, cues[1:], strict=False):
        if current.start < previous.end:
            previous.end = current.start

    return cues, warnings


# ---------------------------------------------------------------------------
# 파일 출력
# ---------------------------------------------------------------------------

def write_srt(cues: list[Cue], path: Path) -> Path:
    blocks = []
    for cue in cues:
        body = "\n".join(cue.plain_lines)
        blocks.append(
            f"{cue.index}\n{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n{body}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def write_ass(cues: list[Cue], path: Path, subtitle_cfg: dict, width: int, height: int) -> Path:
    base_size = int(subtitle_cfg.get("fontSize", 66))
    font_name = str(subtitle_cfg.get("fontName", "NanumGothic"))
    bold = -1 if subtitle_cfg.get("bold", True) else 0
    primary = hex_to_ass_color(subtitle_cfg.get("primaryColor", "#FFFFFF"))
    emphasis = hex_to_ass_color(subtitle_cfg.get("emphasisColor", "#FFD400"))
    outline_color = hex_to_ass_color(subtitle_cfg.get("outlineColor", "#152046"))
    back_color = hex_to_ass_color(subtitle_cfg.get("outlineColor", "#152046"), alpha=0x50)
    outline_w = float(subtitle_cfg.get("outlineWidth", 5))
    shadow = float(subtitle_cfg.get("shadow", 1))

    safe = subtitle_cfg.get("safeArea", {})
    margin_l = int(safe.get("marginLeft", 80))
    margin_r = int(safe.get("marginRight", 80))
    margin_v = int(safe.get("marginBottom", 360))

    alignment = 2 if str(subtitle_cfg.get("alignment", "bottom_center")).startswith("bottom") else 5

    header = f"""[Script Info]
; 오늘도출근 Shorts Factory — 자동 생성 (명세서 §19)
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font_name},{base_size},{primary},{primary},{outline_color},{back_color},{bold},0,0,0,100,100,0,0,1,{outline_w:g},{shadow:g},{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for cue in cues:
        parts: list[str] = []
        if cue.font_size != base_size:
            parts.append(f"{{\\fs{cue.font_size}}}")
        for line_index, line in enumerate(cue.layout.lines):
            if line_index:
                parts.append("\\N")
            for segment in line.segments:
                if segment.emphasis:
                    # 인라인 색 지정 태그는 &H...& 처럼 끝에도 &를 붙이는 것이 ASS 표준 표기다.
                    parts.append(
                        f"{{\\c{emphasis}&}}{_escape_ass_text(segment.text)}{{\\c{primary}&}}"
                    )
                else:
                    parts.append(_escape_ass_text(segment.text))
        body = "".join(parts)
        lines.append(
            f"Dialogue: 0,{format_ass_time(cue.start)},{format_ass_time(cue.end)},Main,,0,0,0,,{body}\n"
        )

    path.write_text("".join(lines), encoding="utf-8")
    return path


def write_timeline_json(cues: list[Cue], path: Path, subtitle_cfg: dict, width: int, height: int, fps: int) -> Path:
    payload = {
        "resolution": {"width": width, "height": height},
        "fps": fps,
        "style": {
            "fontName": subtitle_cfg.get("fontName"),
            "fontSize": subtitle_cfg.get("fontSize"),
            "primaryColor": subtitle_cfg.get("primaryColor"),
            "emphasisColor": subtitle_cfg.get("emphasisColor"),
            "outlineColor": subtitle_cfg.get("outlineColor"),
            "maxLines": subtitle_cfg.get("maxLines"),
            "safeArea": subtitle_cfg.get("safeArea"),
        },
        "cues": [
            {
                "index": cue.index,
                "sceneId": cue.scene_id,
                "startSec": round(cue.start, 3),
                "endSec": round(cue.end, 3),
                "durationSec": round(cue.duration, 3),
                "fontSize": cue.font_size,
                "lines": [
                    [{"text": seg.text, "emphasis": seg.emphasis} for seg in line.segments]
                    for line in cue.layout.lines
                ],
                "text": " ".join(cue.plain_lines),
            }
            for cue in cues
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_subtitles(
    timeline: Timeline,
    out_dir: Path,
    subtitle_cfg: dict,
    *,
    width: int,
    height: int,
    fps: int,
) -> SubtitleResult:
    """자막 3종 파일을 만든다. 실패하면 SubtitleError로 중단한다(명세서 §25)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cues, warnings = build_cues(timeline, subtitle_cfg, width)

    srt_path = write_srt(cues, out_dir / "subtitles.srt")
    ass_path = write_ass(cues, out_dir / "subtitles.ass", subtitle_cfg, width, height)
    timeline_path = write_timeline_json(cues, out_dir / "subtitle-timeline.json", subtitle_cfg, width, height, fps)

    for warning in warnings:
        log.warning("%s", warning)
    log.info("자막 %d개 생성 (%s)", len(cues), srt_path.name)

    return SubtitleResult(srt_path, ass_path, timeline_path, cues, warnings)
