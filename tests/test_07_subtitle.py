"""TEST-7 자막 (명세서 §28, §19, §27)."""

from __future__ import annotations

import json
import re
from pathlib import Path

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


def _usable_px(subtitle_cfg: dict, width: int = 1080) -> float:
    safe = subtitle_cfg["safeArea"]
    return width - safe["marginLeft"] - safe["marginRight"]


def _korean_text_of_width(target_width: float) -> str:
    """지정한 표시 폭에 최대한 가까운 한국어 문장을 만든다.

    폰트 크기 설정이 바뀌어도 테스트가 그대로 유효하도록, 문장을 하드코딩하지 않고
    config에서 역산한 폭에 맞춰 생성한다.
    """
    pool = ["회사에서", "이런", "말을", "먼저", "꺼내면", "생각보다",
            "크게", "손해를", "보게", "됩니다", "정말", "자주", "다들", "그렇게"]
    words: list[str] = []
    for index in range(60):
        candidate = words + [pool[index % len(pool)]]
        if display_width(" ".join(candidate)) > target_width:
            break
        words = candidate
    return " ".join(words)


def test_long_subtitle_shrinks_font_instead_of_adding_a_third_line(tmp_path, default_config):
    """명세서 §19 최대 2줄. 글자가 많으면 폰트를 줄여서라도 2줄에 맞춘다."""
    base = default_config.subtitle
    usable = _usable_px(base)
    max_lines = base["maxLines"]

    # 기본 폰트로는 2줄에 안 들어가지만, 최소 폰트로는 들어가는 길이를 고른다.
    at_base = max_lines * usable / base["fontSize"]
    at_min = max_lines * usable / base["minFontSize"]
    long_text = _korean_text_of_width((at_base + at_min) / 2)

    assert layout_text(long_text, max_width=usable / base["fontSize"], max_lines=max_lines).overflow, (
        "기본 폰트에서 이미 2줄에 들어가면 이 테스트가 의미를 잃는다"
    )

    cues, warnings = build_cues(make_timeline([long_text], duration=8.0, audio=7.0), base, 1080)

    assert len(cues[0].layout.lines) == max_lines
    assert cues[0].shrunk
    assert base["minFontSize"] <= cues[0].font_size < base["fontSize"]
    assert not warnings


def test_subtitle_too_long_even_at_min_font_warns_but_keeps_text(tmp_path, default_config):
    """최소 폰트로도 2줄을 못 맞추면 글자를 버리지 않고 경고로 알린다."""
    base = default_config.subtitle
    # 최소 폰트에서의 2줄 수용량보다 확실히 긴 문장.
    too_long = _korean_text_of_width(base["maxLines"] * _usable_px(base) / base["minFontSize"] * 1.5)

    cues, warnings = build_cues(make_timeline([too_long], duration=10.0, audio=9.0), base, 1080)

    assert cues[0].font_size == base["minFontSize"]
    assert cues[0].layout.plain.replace("\n", " ") == too_long, "넘쳐도 글자를 버리지 않는다"
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


# ---------------------------------------------------------------------------
# 폰트 해석 — ASS의 폰트 이름과 실제 파일이 같은 것을 가리켜야 한다
# ---------------------------------------------------------------------------

def test_ass_font_name_comes_from_the_actual_file(tmp_path, default_config):
    """설정의 fontName이 실제 파일과 달라도 ASS에는 파일의 이름이 들어가야 한다.

    Windows에서 흔한 상황이다. 설정은 NanumGothic인데 잡히는 파일은 맑은 고딕이라,
    설정값을 그대로 쓰면 libass가 폰트를 못 찾아 한글이 깨진다.
    """
    from src.subtitle.fonts import read_family_name, resolve_font

    cfg = dict(default_config.subtitle)
    real_path = next(p for p in cfg["fontCandidates"] if Path(p).is_file())
    real_family = read_family_name(Path(real_path))
    assert real_family, "테스트 환경에 읽을 수 있는 폰트가 있어야 한다"

    # 설정에는 일부러 엉뚱한 이름을 넣는다.
    cfg["fontName"] = "없는폰트이름"
    cfg["fontFile"] = real_path

    assert resolve_font(cfg).family == real_family

    result = build_subtitles(make_timeline(["자막 확인"]), tmp_path, cfg, width=1080, height=1920, fps=30)
    style = next(line for line in result.ass_path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("Style: Main,"))

    assert style.split(",")[1] == real_family
    assert "없는폰트이름" not in style


def test_resolved_cfg_points_at_the_font_that_was_found(tmp_path, default_config):
    """렌더러가 쓸 설정에도 확정된 폰트 이름과 경로가 담겨야 한다."""
    cfg = dict(default_config.subtitle)
    cfg["fontName"] = "없는폰트이름"

    result = build_subtitles(make_timeline(["자막 확인"]), tmp_path, cfg, width=1080, height=1920, fps=30)

    from src.subtitle.fonts import resolve_font

    assert result.resolved_cfg["fontName"] != "없는폰트이름"
    assert Path(result.resolved_cfg["fontFile"]).is_file()

    # 렌더러는 resolved_cfg로 fontsdir를 구한다. 그때 나오는 폰트가
    # ASS Style에 적힌 이름과 같은 파일이어야 libass가 찾을 수 있다.
    refetched = resolve_font(result.resolved_cfg)
    assert refetched.family == result.resolved_cfg["fontName"]
    assert refetched.path == Path(result.resolved_cfg["fontFile"])
    assert refetched.directory == Path(result.resolved_cfg["fontFile"]).parent


def test_font_falls_back_to_configured_name_when_nothing_is_found(tmp_path):
    """폰트 파일을 하나도 못 찾으면 설정의 이름으로 시스템에 맡긴다."""
    from src.subtitle.fonts import resolve_font

    font = resolve_font({"fontName": "Malgun Gothic", "fontFile": None, "fontCandidates": ["/없는/경로.ttf"]})

    assert font.family == "Malgun Gothic"
    assert font.directory is None
    assert not font.found


def test_windows_font_candidates_are_listed(default_config):
    """Windows에서 쓸 맑은 고딕 경로가 후보에 있어야 한다."""
    candidates = [str(c).lower() for c in default_config.subtitle["fontCandidates"]]

    assert any("malgun" in c for c in candidates), "Windows용 한글 폰트 후보가 없습니다"


# ---- 자막 필터 경로 (Windows 회귀) -----------------------------------------


def _subtitle_job(tmp_path: Path, subtitle_cfg: dict):
    """_prepare_subtitle_filter만 시험하기 위한 최소 RenderJob."""
    from src.render.base import MODE_PREVIEW, RenderJob

    ass_path = tmp_path / "subtitles.ass"
    ass_path.write_text("[Script Info]\n", encoding="utf-8")
    return RenderJob(
        timeline=make_timeline(["자막"]),
        narration_path=tmp_path / "narration.wav",
        subtitle_path=ass_path,
        out_path=tmp_path / "preview.mp4",
        scenes_dir=tmp_path / "scenes",
        work_dir=tmp_path / "work",
        mode=MODE_PREVIEW,
        render_cfg={},
        subtitle_cfg=subtitle_cfg,
    )


def test_subtitle_filter_carries_no_path(tmp_path, default_config):
    """ass 필터에는 경로가 아니라 파일 이름만 들어가야 한다.

    필터그래프 파서는 ':'를 옵션 구분자로, '\\'를 이스케이프로 읽는다.
    Windows 절대 경로(C:\\...)를 그대로 넣으면 필터체인 파싱이 통째로 깨진다
    (ERR_RENDER_FAILED). 그래서 파일을 작업 폴더로 복사하고 이름만 쓴다.
    """
    from src.media.ffmpeg import FFmpeg
    from src.render.ffmpeg_renderer import FFmpegRenderer

    job = _subtitle_job(tmp_path, default_config.subtitle)

    filter_str = FFmpegRenderer(FFmpeg())._prepare_subtitle_filter(job)

    assert filter_str.startswith("ass=filename=subtitles.ass")
    assert "\\" not in filter_str
    assert "/" not in filter_str
    # 드라이브 문자의 ':'가 남으면 안 된다. 옵션 구분용 ':'만 허용한다.
    for option in filter_str.removeprefix("ass=").split(":"):
        assert "=" in option, f"옵션이 아닌 조각이 있습니다: {option}"

    # 필터가 가리키는 파일이 작업 폴더에 실제로 있어야 한다.
    assert (job.work_dir / "subtitles.ass").is_file()
    if "fontsdir=fonts" in filter_str:
        assert any((job.work_dir / "fonts").iterdir())


def test_subtitle_filter_omits_fontsdir_when_font_is_missing(tmp_path):
    """폰트 파일을 못 찾으면 fontsdir 없이 시스템 폰트에 맡긴다."""
    from src.media.ffmpeg import FFmpeg
    from src.render.ffmpeg_renderer import FFmpegRenderer

    job = _subtitle_job(tmp_path, {"fontName": "Malgun Gothic", "fontFile": None, "fontCandidates": []})

    filter_str = FFmpegRenderer(FFmpeg())._prepare_subtitle_filter(job)

    assert filter_str == "ass=filename=subtitles.ass"
    assert not (job.work_dir / "fonts").exists()
