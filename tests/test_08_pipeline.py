"""TEST-8 Render / TEST-9 Sync / TEST-10 Repeatability (명세서 §28).

렌더 시간을 줄이려고 대부분 작은 해상도(fast_config)로 돌린다.
1080×1920 요구사항 자체를 확인하는 테스트만 저장소 기본 config를 쓴다.
"""

from __future__ import annotations

import json

import pytest

from src.errors import ErrorCode, RenderError
from src.media.ffmpeg import FFmpeg
from src.pipeline import RunOptions, run
from tests.conftest import make_config, make_package, needs_ffmpeg
from tests.fake_comfyui import FakeComfyUI, make_test_video

pytestmark = needs_ffmpeg


def run_pipeline(cfg, input_dir, out_dir, **kwargs):
    options = RunOptions(
        input_dir=input_dir,
        output_dir=out_dir,
        tts_engine=kwargs.pop("tts_engine", "offline"),
        skip_i2v=kwargs.pop("skip_i2v", True),
        force=kwargs.pop("force", True),
        **kwargs,
    )
    return run(cfg, options)


# ---------------------------------------------------------------------------
# TEST-8 1080×1920 MP4 생성
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_render_produces_1080x1920_h264_mp4(tmp_path, default_config):
    """명세서 §20 — 1080×1920 / 30fps / H.264 MP4."""
    package = make_package(tmp_path / "in", duration_sec=1.0, image_size=(1080, 1920))
    config_dir = make_config(tmp_path, {"render": {"profiles": {"preview": {"preset": "ultrafast", "crf": 34, "superSample": 1.0}}}})

    from src.config import load_config
    cfg = load_config(config_dir, repo_root=default_config.repo_root)

    result = run_pipeline(cfg, package, tmp_path / "out")

    assert result.output_path is not None and result.output_path.is_file()
    ffmpeg = FFmpeg()
    info = ffmpeg.probe(result.output_path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")

    assert (int(video["width"]), int(video["height"])) == (1080, 1920)
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert video["r_frame_rate"] == "30/1"
    assert audio["codec_name"] == "aac"


def test_preview_and_final_are_separate_files(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"

    preview = run_pipeline(fast_config, package, out_dir, mode="preview")
    final = run_pipeline(fast_config, package, out_dir, mode="final")

    assert preview.output_path.name == "preview.mp4"
    assert final.output_path.name == "final.mp4"
    assert preview.output_path.is_file() and final.output_path.is_file()


def test_final_requires_preview_first(tmp_path, fast_config):
    """명세서 §21 / §33-6 — MVP에서 Preview 검수 단계를 생략하지 않는다."""
    package = make_package(tmp_path / "in", duration_sec=1.0)

    with pytest.raises(RenderError) as exc_info:
        run_pipeline(fast_config, package, tmp_path / "out", mode="final", force=False)

    assert "preview.mp4" in str(exc_info.value)


def test_existing_output_is_not_overwritten_without_force(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir, mode="preview")

    with pytest.raises(RenderError) as exc_info:
        run_pipeline(fast_config, package, out_dir, mode="preview", force=False)
    assert "--force" in str(exc_info.value)


def test_all_expected_outputs_are_written(tmp_path, fast_config):
    """명세서 §23 outputs/YYYY-MM-DD/ 구성."""
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    for name in ("preview.mp4", "narration.wav", "subtitles.srt", "subtitles.ass",
                 "subtitle-timeline.json", "render-log.json"):
        assert (out_dir / name).is_file(), f"{name}이 없습니다"

    scenes = sorted((out_dir / "scenes").glob("*.mp4"))
    assert len(scenes) == 8, "씬 클립 8개가 있어야 합니다"


def test_work_dir_is_cleaned_up(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)
    assert not (out_dir / ".work").exists()


def test_keep_work_preserves_intermediates(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir, keep_work=True)
    assert (out_dir / ".work").is_dir()


def test_validate_only_skips_rendering(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"

    result = run_pipeline(fast_config, package, out_dir, validate_only=True)

    assert result.output_path is None
    assert not (out_dir / "preview.mp4").exists()
    assert (out_dir / "render-log.json").is_file()


# ---------------------------------------------------------------------------
# TEST-9 음성 / 씬 / 자막 싱크
# ---------------------------------------------------------------------------

def test_video_audio_and_timeline_lengths_agree(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=2.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    ffmpeg = FFmpeg()
    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    timeline_total = log["details"]["timeline"]["totalDurationSec"]

    video_dur = ffmpeg.duration(out_dir / "preview.mp4")
    audio_dur = ffmpeg.duration(out_dir / "narration.wav")

    assert video_dur == pytest.approx(timeline_total, abs=0.1)
    assert audio_dur == pytest.approx(timeline_total, abs=0.1)


def test_scene_clips_have_the_lengths_the_timeline_says(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=2.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    ffmpeg = FFmpeg()
    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))

    for scene in log["scenes"]:
        clip = out_dir / "scenes" / scene["clip"]
        assert ffmpeg.duration(clip) == pytest.approx(scene["durationSec"], abs=0.05), scene["id"]


def test_subtitle_cues_stay_inside_their_scenes(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=2.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    cues = {c["sceneId"]: c for c in json.loads((out_dir / "subtitle-timeline.json").read_text(encoding="utf-8"))["cues"]}

    for scene in log["scenes"]:
        cue = cues.get(scene["id"])
        if cue is None:
            continue
        start = scene["startSec"]
        end = start + scene["durationSec"]
        assert start - 1e-6 <= cue["startSec"] < cue["endSec"] <= end + 1e-6, scene["id"]


def test_scene_extends_when_narration_is_longer_than_planned(tmp_path, fast_config):
    """명세서 §31 RISK-3 — TTS 길이 기준으로 타임라인을 조정한다."""
    package = make_package(
        tmp_path / "in",
        duration_sec=1.0,
        scene_overrides={3: {"narration": "이 문장은 아주 길어서 계획된 1초 안에는 절대로 들어갈 수 없는 분량입니다. " * 2}},
    )
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    scene = next(s for s in log["scenes"] if s["id"] == "SCENE-03")

    assert scene["durationSec"] > scene["plannedDurationSec"]
    assert scene["durationSec"] >= scene["audioDurationSec"]
    assert any("SCENE-03" in w for w in log["warnings"])


def test_scene_start_times_are_contiguous(tmp_path, fast_config):
    package = make_package(tmp_path / "in", duration_sec=1.5)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    scenes = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))["scenes"]
    # render-log.json은 초를 소수점 3자리로 반올림해 적는다. 그 값을 더해 나가면
    # 씬마다 최대 0.0005초씩 오차가 쌓이므로, 허용 오차를 씬 수에 비례해 잡는다.
    tolerance = 0.001 * len(scenes)
    cursor = 0.0
    for scene in scenes:
        assert scene["startSec"] == pytest.approx(cursor, abs=tolerance), scene["id"]
        cursor += scene["durationSec"]


# ---------------------------------------------------------------------------
# I2V 통합 (fallback이 렌더까지 이어지는지)
# ---------------------------------------------------------------------------

def test_i2v_success_is_used_in_the_final_video(tmp_path, fast_config):
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=3.0, width=270, height=480)
    package = make_package(tmp_path / "in", duration_sec=3.0)
    out_dir = tmp_path / "out"

    with FakeComfyUI(video_bytes) as server:
        from src.config import deep_merge
        fast_config.i2v = deep_merge(fast_config.i2v, {"comfyui": {"baseUrl": server.base_url}})
        run_pipeline(fast_config, package, out_dir, skip_i2v=False)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    assert log["i2v"] == {"SCENE-02": "success", "SCENE-05": "success"}
    assert [s["processedAs"] for s in log["scenes"] if s["id"] in ("SCENE-02", "SCENE-05")] == ["i2v", "i2v"]
    assert ffmpeg.duration(out_dir / "preview.mp4") > 0


def test_i2v_failure_still_produces_a_complete_video(tmp_path, fast_config):
    """US-3 — I2V가 실패해도 전체 제작이 중단되지 않는다."""
    from src.config import deep_merge
    fast_config.i2v = deep_merge(fast_config.i2v, {"comfyui": {"baseUrl": "http://127.0.0.1:1"}})

    package = make_package(tmp_path / "in", duration_sec=1.5)
    out_dir = tmp_path / "out"
    result = run_pipeline(fast_config, package, out_dir, skip_i2v=False)

    assert result.output_path.is_file()
    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    assert log["i2v"] == {"SCENE-02": "fallback_still", "SCENE-05": "fallback_still"}
    assert log["render"] == "success"
    assert len(list((out_dir / "scenes").glob("*.mp4"))) == 8


def test_i2v_clip_shorter_than_scene_is_padded(tmp_path, fast_config):
    """명세서 §16 — I2V는 3~5초. 씬이 더 길면 마지막 프레임으로 채운다.

    씬이 I2V 클립보다 길어야 의미가 있는 테스트이므로, 내레이션 길이에 맞추지 않고
    scene-plan.json의 durationSec을 그대로 쓰도록 fitToNarration을 끈다.
    """
    from src.config import deep_merge

    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=3.0, width=270, height=480)
    package = make_package(tmp_path / "in", duration_sec=8.0)
    out_dir = tmp_path / "out"
    fast_config.app = deep_merge(fast_config.app, {"timeline": {"fitToNarration": False, "maxSceneSec": 0}})

    with FakeComfyUI(video_bytes) as server:
        fast_config.i2v = deep_merge(fast_config.i2v, {"comfyui": {"baseUrl": server.base_url}})
        run_pipeline(fast_config, package, out_dir, skip_i2v=False)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    scene = next(s for s in log["scenes"] if s["id"] == "SCENE-02")
    assert scene["durationSec"] == pytest.approx(8.0, abs=0.05), "durationSec이 그대로 쓰여야 한다"

    clip = out_dir / "scenes" / "scene-02.mp4"
    assert ffmpeg.duration(clip) == pytest.approx(8.0, abs=0.05)


# ---------------------------------------------------------------------------
# TEST-10 다른 날짜 폴더로 동일 실행
# ---------------------------------------------------------------------------

def test_different_date_folders_run_independently(tmp_path, fast_config):
    dates = ["2026-09-18", "2026-09-19", "2026-10-01"]
    results = []

    for date in dates:
        package = make_package(tmp_path / "inputs" / date, date=date, duration_sec=1.0)
        results.append(run_pipeline(fast_config, package, tmp_path / "outputs" / date))

    for date, result in zip(dates, results, strict=True):
        assert result.output_path.is_file()
        log = json.loads((result.log_path).read_text(encoding="utf-8"))
        assert log["date"] == date
        assert log["render"] == "success"

    # 출력이 서로 섞이지 않는다.
    assert len({str(r.output_path) for r in results}) == 3


def test_same_input_produces_same_timeline(tmp_path, fast_config):
    """같은 입력이면 타임라인도 같아야 재실행이 안전하다."""
    package = make_package(tmp_path / "in", duration_sec=1.0)

    logs = []
    for index in range(2):
        out_dir = tmp_path / f"out{index}"
        run_pipeline(fast_config, package, out_dir)
        logs.append(json.loads((out_dir / "render-log.json").read_text(encoding="utf-8")))

    assert logs[0]["details"]["timeline"] == logs[1]["details"]["timeline"]


def test_default_output_dir_follows_project_date(tmp_path, fast_config, monkeypatch):
    """명세서 §23 — outputs/YYYY-MM-DD/"""
    package = make_package(tmp_path / "in", date="2027-01-05", duration_sec=1.0)
    fast_config.app = dict(fast_config.app, paths={**fast_config.app["paths"], "outputsDir": str(tmp_path / "outputs")})

    result = run(fast_config, RunOptions(input_dir=package, tts_engine="offline", skip_i2v=True, force=True))

    assert result.out_dir.name == "2027-01-05"
    assert result.output_path.parent == result.out_dir


# ---------------------------------------------------------------------------
# 오류 정책 (명세서 §25)
# ---------------------------------------------------------------------------

def test_validation_failure_stops_before_rendering(tmp_path, fast_config):
    """명세서 §14 — 오류 시 렌더 시작 금지."""
    package = make_package(tmp_path / "in", skip_images=[4], duration_sec=1.0)
    out_dir = tmp_path / "out"

    from src.errors import SceneImageMissingError
    with pytest.raises(SceneImageMissingError):
        run_pipeline(fast_config, package, out_dir)

    assert not (out_dir / "preview.mp4").exists()
    assert not (out_dir / "scenes").exists()


def test_log_is_written_even_when_the_run_fails(tmp_path, fast_config):
    """명세서 §22 — 어디까지 진행됐는지 남아야 한다."""
    package = make_package(tmp_path / "in", scene_count=7, duration_sec=1.0)
    out_dir = tmp_path / "out"

    from src.errors import SceneCountError
    with pytest.raises(SceneCountError):
        run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    assert log["validation"]["status"] == "failed"
    assert log["render"] != "success"
    assert any(e["code"] == ErrorCode.SCENE_COUNT for e in log["errors"])


def test_tts_failure_aborts_the_run(tmp_path, fast_config):
    """명세서 §25 — TTS 실패는 중단."""
    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"

    from src.errors import TTSError
    with pytest.raises(TTSError):
        run_pipeline(fast_config, package, out_dir, tts_engine="supertonic")

    assert not (out_dir / "preview.mp4").exists()
    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    assert log["tts"] == "failed"


# ---------------------------------------------------------------------------
# BGM (명세서 §35-4 — MVP 제외이지만 켜면 동작해야 한다)
# ---------------------------------------------------------------------------

def test_bgm_is_off_by_default(fast_config):
    assert fast_config.render["bgm"]["enabled"] is False


def test_bgm_mixes_in_when_enabled(tmp_path, fast_config):
    from src.config import deep_merge

    ffmpeg = FFmpeg()
    bgm = tmp_path / "bgm.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-c:a", "pcm_s16le", str(bgm)])

    fast_config.render = deep_merge(fast_config.render, {"bgm": {"enabled": True, "file": str(bgm), "gainDb": -22}})

    package = make_package(tmp_path / "in", duration_sec=1.0)
    out_dir = tmp_path / "out"
    result = run_pipeline(fast_config, package, out_dir)

    assert result.output_path.is_file()
    assert ffmpeg.has_audio(result.output_path)
    # BGM 길이(3초)가 아니라 영상 길이에 맞춰 루프/컷된다.
    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    assert ffmpeg.duration(result.output_path) == pytest.approx(log["details"]["timeline"]["totalDurationSec"], abs=0.15)


def test_missing_bgm_file_is_skipped_not_fatal(tmp_path, fast_config):
    from src.config import deep_merge

    fast_config.render = deep_merge(fast_config.render, {"bgm": {"enabled": True, "file": str(tmp_path / "없는파일.mp3")}})

    package = make_package(tmp_path / "in", duration_sec=1.0)
    result = run_pipeline(fast_config, package, tmp_path / "out")
    assert result.output_path.is_file()


# ---------------------------------------------------------------------------
# fitToNarration — 내레이션이 끝나면 바로 다음 씬 (늘어짐 방지)
# ---------------------------------------------------------------------------

def test_fit_to_narration_leaves_no_idle_time(tmp_path, fast_config):
    """말이 끝난 뒤 정지 화면이 남지 않아야 한다."""

    timeline_cfg = fast_config.app["timeline"]
    lead, tail = timeline_cfg["leadInSec"], timeline_cfg["tailPadSec"]

    # durationSec을 일부러 크게 잡아도 내레이션 길이에 맞춰 줄어들어야 한다.
    package = make_package(tmp_path / "in", duration_sec=8.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    for scene in log["scenes"]:
        speaking = lead + scene["audioDurationSec"] + tail
        idle = scene["durationSec"] - speaking
        assert idle < 1 / 30 + 1e-6, f"{scene['id']}: 빈 시간 {idle:.2f}초"
        assert scene["durationSec"] < scene["plannedDurationSec"], scene["id"]


def test_fit_to_narration_still_never_cuts_audio(tmp_path, fast_config):
    """씬을 줄이더라도 음성이 잘리면 안 된다."""
    package = make_package(tmp_path / "in", duration_sec=0.5)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    lead = fast_config.app["timeline"]["leadInSec"]
    for scene in log["scenes"]:
        assert scene["durationSec"] >= lead + scene["audioDurationSec"], scene["id"]


def test_max_scene_sec_caps_silent_scenes(tmp_path, fast_config):
    """내레이션이 없는 씬이 durationSec만 믿고 길어지지 않는다."""
    from src.config import deep_merge

    fast_config.app = deep_merge(fast_config.app, {"timeline": {"fitToNarration": False, "maxSceneSec": 3.0}})
    package = make_package(tmp_path / "in", duration_sec=10.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    for scene in log["scenes"]:
        assert scene["durationSec"] <= 3.0 + 1 / 30, scene["id"]


def test_fit_disabled_respects_planned_duration(tmp_path, fast_config):
    """fitToNarration=false면 기존처럼 durationSec을 하한으로 존중한다."""
    from src.config import deep_merge

    fast_config.app = deep_merge(fast_config.app, {"timeline": {"fitToNarration": False, "maxSceneSec": 0}})
    package = make_package(tmp_path / "in", duration_sec=5.0)
    out_dir = tmp_path / "out"
    run_pipeline(fast_config, package, out_dir)

    log = json.loads((out_dir / "render-log.json").read_text(encoding="utf-8"))
    for scene in log["scenes"]:
        assert scene["durationSec"] >= 5.0 - 1e-6, scene["id"]
