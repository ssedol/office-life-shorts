"""TEST-7 자막 (명세서 §28, §19, §27)."""

from __future__ import annotations

import json
import re

import pytest

from src.errors import SubtitleError
from src.scene.models import Scene
from src.scene.timeline import Timeline, TimelineScene
from src.subtitle.builder import build_cues, build_subtitles, format_srt_time, hex_to_ass_color
from src.subtitle.wrap import display_width, layout_text, parse_emphasis

SRT_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})$")


def make_timeline(subtitles: list[str], duration: float = 4.0, audio: float = 2.5) -> Timeline:
    items = []
    cursor = 0.0
    for index, text in enumerate(subtitles):
        scene = Scene(
            id=f"SCENE-{index + 1:02d}", order=index + 1, duration_sec=duration, type="STILL",
            reason="", image_file=f"scene-{index + 1:02d}.png", narration="내레이션", subtitle=text,
        )
        items.append(TimelineScene(
            scene=scene, index=index, start=cursor, duration=duration,
            lead_in=0.15, audio_duration=audio, source="still",
        ))
        cursor += duration
    return Timeline(scenes=items, fps=30)


# ---------------------------------------------------------------------------
# 강조 마크업 파싱
# ---------------------------------------------------------------------------

def test_emphasis_markup_is_stripped_from_plain_text():
    plain, spans = parse_emphasis("먼저 꺼내면 **손해** 보는 말")
    assert plain == "먼저 꺼내면 손해 보는 말"
    assert [plain[s:e] for s, e in spans] == ["손해"]


def test_multiple_emphasis_spans():
    plain, spans = parse_emphasis("**이것**과 **저것**")
    assert plain == "이것과 저것"
    assert [plain[s:e] for s, e in spans] == ["이것", "저것"]


def test_text_without_markup_has_no_emphasis():
    plain, spans = parse_emphasis("강조 없는 문장")
    assert plain == "강조 없는 문장"
    assert spans == []


def test_emphasis_keywords_work_without_markup():
    layout = layout_text("판단은 상대에게", max_width=20, keywords=["판단"])
    segments = [seg for line in layout.lines for seg in line.segments]
    assert any(seg.emphasis and "판단" in seg.text for seg in segments)


# ---------------------------------------------------------------------------
# 줄바꿈 — 최대 2줄 (명세서 §19, §27)
# ---------------------------------------------------------------------------

def test_short_text_stays_on_one_line():
    layout = layout_text("짧은 자막", max_width=15)
    assert len(layout.lines) == 1
    assert not layout.overflow


def test_long_text_wraps_to_two_lines():
    layout = layout_text("이 문장은 한 줄에 다 들어가지 않습니다", max_width=12)
    assert len(layout.lines) == 2
    assert not layout.overflow
    assert all(line.width <= 12 for line in layout.lines)


def test_text_too_long_for_max_lines_is_flagged_not_truncated():
    text = "이 문장은 한 줄에 다 들어가지 않을 만큼 충분히 깁니다"
    layout = layout_text(text, max_width=12, max_lines=2)

    assert layout.overflow
    assert layout.plain.replace("\n", " ") == text, "넘쳐도 글자를 버리지는 않는다"


def test_two_lines_are_balanced():
    layout = layout_text("앞부분은 짧고 뒷부분은 조금 더 깁니다 정말로", max_width=14)
    assert len(layout.lines) == 2
    widths = [line.width for line in layout.lines]
    assert abs(widths[0] - widths[1]) < max(widths) * 0.7


def test_overflow_is_flagged():
    layout = layout_text("아주 " * 30, max_width=10, max_lines=2)
    assert layout.overflow


def test_single_long_word_is_hard_broken():
    layout = layout_text("가나다라마바사아자차카타파하가나다라마바사", max_width=8)
    assert len(layout.lines) >= 2
    assert all(line.width <= 8.01 for line in layout.lines)


def test_emphasis_survives_line_break():
    layout = layout_text("앞쪽 문장이 길어서 줄이 넘어가고 여기 **강조** 단어", max_width=12)
    segments = [seg for line in layout.lines for seg in line.segments]
    assert any(seg.emphasis and seg.text == "강조" for seg in segments)
    assert "**" not in layout.plain


def test_korean_counts_as_full_width():
    assert display_width("가나다") == 3.0
    assert display_width("abc") < 3.0


def test_empty_subtitle_produces_no_lines():
    assert layout_text("   ", max_width=15).lines == []


# ---------------------------------------------------------------------------
# 색상 변환
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("#FFFFFF", "&H00FFFFFF"),
    ("#000000", "&H00000000"),
    ("#FFD400", "&H0000D4FF"),   # ASS는 BGR 순서
    ("#152046", "&H00462015"),
    ("FFD400", "&H0000D4FF"),
    ("#FFF", "&H00FFFFFF"),
])
def test_hex_to_ass_color(value, expected):
    assert hex_to_ass_color(value) == expected


@pytest.mark.parametrize("value", ["#GGGGGG", "#12345", "빨강"])
def test_invalid_color_is_rejected(value):
    with pytest.raises(SubtitleError):
        hex_to_ass_color(value)


# ---------------------------------------------------------------------------
# TEST-7 SRT 생성, 타임코드 유효
# ---------------------------------------------------------------------------

def test_srt_timecodes_are_valid(tmp_path, default_config):
    timeline = make_timeline(["첫 **자막**", "두 번째 자막", "세 번째 자막"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)

    lines = result.srt_path.read_text(encoding="utf-8").splitlines()
    timecodes = [line for line in lines if "-->" in line]

    assert len(timecodes) == 3
    for timecode in timecodes:
        assert SRT_TIME.match(timecode), f"잘못된 타임코드: {timecode}"


def test_srt_indices_are_sequential(tmp_path, default_config):
    timeline = make_timeline(["A", "B", "C", "D"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)

    blocks = [b for b in result.srt_path.read_text(encoding="utf-8").split("\n\n") if b.strip()]
    assert [int(b.strip().splitlines()[0]) for b in blocks] == [1, 2, 3, 4]


def test_srt_has_no_markup(tmp_path, default_config):
    timeline = make_timeline(["여기 **강조** 있음"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)
    assert "**" not in result.srt_path.read_text(encoding="utf-8")


def test_cues_never_overlap(tmp_path, default_config):
    timeline = make_timeline(["A", "B", "C"], duration=3.0, audio=5.0)  # 오디오가 씬보다 길어도
    cues, _ = build_cues(timeline, default_config.subtitle, 1080)

    for previous, current in zip(cues, cues[1:], strict=False):
        assert previous.end <= current.start


def test_cue_stays_inside_its_scene(tmp_path, default_config):
    timeline = make_timeline(["A", "B"], duration=4.0, audio=10.0)
    cues, _ = build_cues(timeline, default_config.subtitle, 1080)

    for cue, item in zip(cues, timeline.scenes, strict=True):
        assert cue.start >= item.start - 1e-6
        assert cue.end <= item.end + 1e-6


@pytest.mark.parametrize("seconds,expected", [
    (0, "00:00:00,000"),
    (1.5, "00:00:01,500"),
    (61.25, "00:01:01,250"),
    (3661.007, "01:01:01,007"),
])
def test_srt_time_format(seconds, expected):
    assert format_srt_time(seconds) == expected


# ---------------------------------------------------------------------------
# ASS 스타일 (명세서 §19)
# ---------------------------------------------------------------------------

def test_ass_style_matches_spec(tmp_path, default_config):
    timeline = make_timeline(["먼저 꺼내면 **손해** 보는 말"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)
    ass = result.ass_path.read_text(encoding="utf-8")

    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    style = next(line for line in ass.splitlines() if line.startswith("Style: Main,"))
    fields = style.removeprefix("Style: ").split(",")

    assert fields[3] == "&H00FFFFFF", "기본 글자는 흰색"
    assert fields[5] == "&H00462015", "외곽선은 짙은 네이비"
    assert fields[7] == "-1", "굵은 고딕"
    assert fields[18] == "2", "가운데 하단 정렬"
    assert int(fields[-2]) == 360, "안전영역 하단 여백"


def test_ass_emphasis_uses_yellow(tmp_path, default_config):
    timeline = make_timeline(["여기 **강조** 있음"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)
    ass = result.ass_path.read_text(encoding="utf-8")

    assert "{\\c&H0000D4FF&}강조{\\c&H00FFFFFF&}" in ass


def test_ass_uses_two_lines_for_long_subtitle(tmp_path, default_config):
    timeline = make_timeline(["이 자막은 길어서 반드시 두 줄로 나뉘어야 정상입니다"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)

    dialogue = next(line for line in result.ass_path.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue:"))
    assert dialogue.count("\\N") == 1


def test_long_subtitle_shrinks_font_instead_of_adding_a_third_line(tmp_path, default_config):
    """명세서 §19 최대 2줄. 글자가 많으면 폰트를 줄여서라도 2줄에 맞춘다."""
    long_text = "회사에서 이런 말을 먼저 꺼내면 생각보다 정말 크게 손해를 봅니다"
    timeline = make_timeline([long_text], duration=8.0, audio=7.0)

    # 기본 폰트 크기에서는 3줄이 필요한 문장이어야 이 테스트가 의미가 있다.
    base = default_config.subtitle
    usable = 1080 - base["safeArea"]["marginLeft"] - base["safeArea"]["marginRight"]
    assert layout_text(long_text, max_width=usable / base["fontSize"], max_lines=2).overflow

    cues, warnings = build_cues(timeline, base, 1080)

    assert len(cues[0].layout.lines) == 2
    assert cues[0].shrunk
    assert base["minFontSize"] <= cues[0].font_size < base["fontSize"]
    assert not warnings


def test_subtitle_too_long_even_at_min_font_warns_but_keeps_text(tmp_path, default_config):
    """최소 폰트로도 2줄을 못 맞추면 글자를 버리지 않고 경고로 알린다."""
    too_long = "회사에서 이런 말을 먼저 꺼내면 생각보다 훨씬 더 크게 손해를 보게 되는 진짜 이유가 따로 있습니다"
    timeline = make_timeline([too_long], duration=10.0, audio=9.0)

    cues, warnings = build_cues(timeline, default_config.subtitle, 1080)

    assert cues[0].font_size == default_config.subtitle["minFontSize"]
    assert cues[0].layout.plain.replace("\n", " ") == too_long
    assert any("최대 2줄" in w or "줄입니다" in w for w in warnings)


# ---------------------------------------------------------------------------
# subtitle-timeline.json
# ---------------------------------------------------------------------------

def test_timeline_json_structure(tmp_path, default_config):
    timeline = make_timeline(["첫 **자막**", "둘째 자막"])
    result = build_subtitles(timeline, tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)

    data = json.loads(result.timeline_path.read_text(encoding="utf-8"))
    assert data["resolution"] == {"width": 1080, "height": 1920}
    assert data["fps"] == 30
    assert len(data["cues"]) == 2

    first = data["cues"][0]
    assert first["sceneId"] == "SCENE-01"
    assert first["endSec"] > first["startSec"]
    assert any(seg["emphasis"] for line in first["lines"] for seg in line)


def test_all_three_files_are_written(tmp_path, default_config):
    result = build_subtitles(make_timeline(["A"]), tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)
    assert result.srt_path.name == "subtitles.srt"
    assert result.ass_path.name == "subtitles.ass"
    assert result.timeline_path.name == "subtitle-timeline.json"
    assert all(p.is_file() for p in (result.srt_path, result.ass_path, result.timeline_path))


def test_no_subtitles_at_all_is_an_error(tmp_path, default_config):
    """명세서 §27 — 자막은 필수."""
    with pytest.raises(SubtitleError):
        build_subtitles(make_timeline(["", "  ", ""]), tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)


def test_scene_without_subtitle_is_skipped_not_fatal(tmp_path, default_config):
    result = build_subtitles(make_timeline(["A", "", "C"]), tmp_path, default_config.subtitle, width=1080, height=1920, fps=30)
    assert [cue.scene_id for cue in result.cues] == ["SCENE-01", "SCENE-03"]
