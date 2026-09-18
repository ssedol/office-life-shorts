"""TEST-4 I2V 호출 / TEST-5 I2V Fallback (명세서 §28, §16, §17)."""

from __future__ import annotations

import json

import pytest

from src.config import deep_merge
from src.errors import ErrorCode, I2VError
from src.i2v.base import I2VRequest
from src.i2v.comfy_ltx import ComfyUILTXProvider
from src.i2v.runner import STATUS_FALLBACK, STATUS_SKIPPED, STATUS_SUCCESS, run_i2v
from src.media.ffmpeg import FFmpeg
from src.scene.models import Scene
from src.scene.timeline import SOURCE_I2V, SOURCE_I2V_FALLBACK, Timeline, TimelineScene
from tests.conftest import make_image, needs_ffmpeg
from tests.fake_comfyui import FakeComfyUI, make_test_video


def make_timeline(tmp_path, count: int = 3, i2v_orders=(2,)) -> Timeline:
    items = []
    cursor = 0.0
    for order in range(1, count + 1):
        is_i2v = order in i2v_orders
        image = make_image(tmp_path / f"scene-{order:02d}.png", 270, 480)
        scene = Scene(
            id=f"SCENE-{order:02d}",
            order=order,
            duration_sec=4.0,
            type="I2V" if is_i2v else "STILL",
            reason="테스트",
            image_file=image.name,
            narration="내레이션",
            subtitle="자막",
            video_prompt="Subtle blinking, very slow camera push-in." if is_i2v else None,
        )
        scene.image_path = image
        items.append(
            TimelineScene(
                scene=scene, index=order - 1, start=cursor, duration=4.0,
                lead_in=0.15, audio_duration=3.0,
                source=SOURCE_I2V if is_i2v else "still",
            )
        )
        cursor += 4.0
    return Timeline(scenes=items, fps=30)


def configure(cfg, server: FakeComfyUI | None = None, **overrides):
    """cfg.i2v를 테스트 서버에 맞춘다."""
    patch = {
        "comfyui": {"pollIntervalSec": 0.02, "connectTimeoutSec": 5, "timeoutSec": 15},
        "retry": {"attempts": 1, "backoffSec": 0.0},
    }
    if server is not None:
        patch["comfyui"]["baseUrl"] = server.base_url
    cfg.i2v = deep_merge(cfg.i2v, deep_merge(patch, overrides))
    return cfg


# ---------------------------------------------------------------------------
# 워크플로우 주입 (명세서 §17)
# ---------------------------------------------------------------------------

def test_workflow_injection_fills_every_mapped_slot(fast_config):
    provider = ComfyUILTXProvider(fast_config.i2v, fast_config.repo_root)
    workflow = provider.load_workflow()

    injected = provider.inject(workflow, {
        "imagePath": "scene-02.png",
        "positivePrompt": "subtle blink",
        "negativePrompt": "walking",
        "seed": 12345,
        "width": 1080,
        "height": 1920,
        "frameCount": 121,
        "fps": 30,
        "outputPrefix": "today-to-work/SCENE-02",
    })

    mapping = fast_config.i2v["inject"]
    assert injected[mapping["imagePath"]["node"]]["inputs"]["image"] == "scene-02.png"
    assert injected[mapping["positivePrompt"]["node"]]["inputs"]["text"] == "subtle blink"
    assert injected[mapping["seed"]["node"]]["inputs"]["seed"] == 12345
    assert injected[mapping["frameCount"]["node"]]["inputs"]["length"] == 121
    assert injected[mapping["fps"]["node"]]["inputs"]["frame_rate"] == 30


def test_injection_reports_missing_node(fast_config):
    cfg = configure(fast_config, inject={"seed": {"node": "9999", "field": "seed"}})
    provider = ComfyUILTXProvider(cfg.i2v, cfg.repo_root)

    with pytest.raises(I2VError) as exc_info:
        provider.inject(provider.load_workflow(), {"seed": 1})

    assert "9999" in str(exc_info.value)
    assert exc_info.value.code == ErrorCode.I2V_FAILED


def test_injection_reports_missing_field(fast_config):
    cfg = configure(fast_config, inject={"seed": {"node": "3", "field": "없는입력"}})
    provider = ComfyUILTXProvider(cfg.i2v, cfg.repo_root)

    with pytest.raises(I2VError) as exc_info:
        provider.inject(provider.load_workflow(), {"seed": 1})
    assert "없는입력" in str(exc_info.value)


def test_null_mapping_is_skipped(fast_config):
    """durationSec는 기본 매핑이 null이라 주입하지 않는다."""
    provider = ComfyUILTXProvider(fast_config.i2v, fast_config.repo_root)
    before = json.dumps(provider.load_workflow(), sort_keys=True)
    after = json.dumps(provider.inject(provider.load_workflow(), {"durationSec": 4.0}), sort_keys=True)
    assert before == after


def test_ui_format_workflow_is_rejected(tmp_path, fast_config):
    ui_workflow = tmp_path / "ui.json"
    ui_workflow.write_text(json.dumps({"nodes": [{"id": 1}], "links": []}), encoding="utf-8")
    cfg = configure(fast_config, workflowFile=str(ui_workflow))

    with pytest.raises(I2VError) as exc_info:
        ComfyUILTXProvider(cfg.i2v, cfg.repo_root).load_workflow()
    assert "API 형식" in str(exc_info.value)


def test_missing_workflow_file_is_reported(tmp_path, fast_config):
    cfg = configure(fast_config, workflowFile=str(tmp_path / "없는파일.json"))
    with pytest.raises(I2VError) as exc_info:
        ComfyUILTXProvider(cfg.i2v, cfg.repo_root).preflight()
    assert "workflow JSON이 없습니다" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TEST-4 LTX 2.5 호출 후 MP4 생성
# ---------------------------------------------------------------------------

@needs_ffmpeg
def test_i2v_produces_mp4(tmp_path, fast_config):
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=3.0)

    with FakeComfyUI(video_bytes) as server:
        cfg = configure(fast_config, server)
        provider = ComfyUILTXProvider(cfg.i2v, cfg.repo_root)
        image = make_image(tmp_path / "scene-02.png", 270, 480)
        out = tmp_path / "out.mp4"

        result = provider.generate(I2VRequest(
            scene_id="SCENE-02", image_path=image,
            video_prompt="Subtle blinking, very slow camera push-in.",
            out_path=out, width=270, height=480, fps=30, duration_sec=3.0, seed=777,
        ))

    assert out.is_file() and out.stat().st_size > 0
    assert result.seed == 777
    assert ffmpeg.video_size(out) == (270, 480)
    assert ffmpeg.duration(out) > 0

    workflow = server.submitted_workflows[0]
    assert workflow["6"]["inputs"]["text"] == "Subtle blinking, very slow camera push-in."
    assert workflow["3"]["inputs"]["seed"] == 777
    assert workflow["70"]["inputs"]["length"] == 90  # 3초 × 30fps
    assert server.uploaded_images == ["scene-02.png"]


@needs_ffmpeg
def test_runner_marks_success_and_sets_source(tmp_path, fast_config):
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=3.0)
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))

    with FakeComfyUI(video_bytes) as server:
        report = run_i2v(timeline, configure(fast_config, server), tmp_path / "work")

    assert report.as_log_map() == {"SCENE-02": STATUS_SUCCESS}
    assert report.success_count == 1
    item = timeline.scenes[1]
    assert item.source == SOURCE_I2V
    assert item.i2v_raw_path is not None and item.i2v_raw_path.is_file()


@needs_ffmpeg
@pytest.mark.parametrize("output_key", ["gifs", "videos", "images"])
def test_video_output_is_found_under_any_node_key(tmp_path, fast_config, output_key):
    """노드마다 결과 키가 달라서(gifs/videos/images) 전부 훑어야 한다."""
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=2.0)

    with FakeComfyUI(video_bytes, output_key=output_key) as server:
        cfg = configure(fast_config, server)
        provider = ComfyUILTXProvider(cfg.i2v, cfg.repo_root)
        out = tmp_path / f"{output_key}.mp4"
        provider.generate(I2VRequest(
            scene_id="SCENE-02", image_path=make_image(tmp_path / "s.png", 270, 480),
            video_prompt="x", out_path=out, width=270, height=480, fps=30, duration_sec=2.0,
        ))

    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# TEST-5 실패 시 STILL 전환 (명세서 §16 Fallback)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["prompt_error", "exec_error", "no_video", "empty_file"])
@needs_ffmpeg
def test_every_failure_mode_falls_back_to_still(tmp_path, fast_config, mode):
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=2.0)
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))

    with FakeComfyUI(video_bytes, mode=mode) as server:
        report = run_i2v(timeline, configure(fast_config, server), tmp_path / "work")

    assert report.as_log_map() == {"SCENE-02": STATUS_FALLBACK}
    item = timeline.scenes[1]
    assert item.source == SOURCE_I2V_FALLBACK
    assert item.scene.effective_motion == "slow_zoom_in"  # 명세서 §16
    assert any("fallback" in note for note in item.notes)


def test_unreachable_server_falls_back(tmp_path, fast_config):
    """ComfyUI가 꺼져 있어도 전체 제작이 중단되면 안 된다 (US-3)."""
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))
    cfg = configure(fast_config, baseUrl="http://127.0.0.1:1")  # 닫힌 포트

    report = run_i2v(timeline, cfg, tmp_path / "work")

    assert report.as_log_map() == {"SCENE-02": STATUS_FALLBACK}
    assert timeline.scenes[1].source == SOURCE_I2V_FALLBACK


def test_bad_injection_mapping_falls_back_without_crashing(tmp_path, fast_config):
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))
    cfg = configure(fast_config, inject={"seed": {"node": "9999", "field": "seed"}})

    report = run_i2v(timeline, cfg, tmp_path / "work")
    assert report.fallback_count == 1


def test_multiple_i2v_scenes_fail_independently(tmp_path, fast_config):
    timeline = make_timeline(tmp_path, count=5, i2v_orders=(2, 5))
    cfg = configure(fast_config, baseUrl="http://127.0.0.1:1")

    report = run_i2v(timeline, cfg, tmp_path / "work")

    assert report.as_log_map() == {"SCENE-02": STATUS_FALLBACK, "SCENE-05": STATUS_FALLBACK}
    assert all(item.source == SOURCE_I2V_FALLBACK for item in timeline.scenes if item.scene.is_i2v)
    assert all(item.source == "still" for item in timeline.scenes if not item.scene.is_i2v)


def test_fallback_disabled_raises(tmp_path, fast_config):
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))
    cfg = configure(fast_config, baseUrl="http://127.0.0.1:1", fallback={"enabled": False})

    with pytest.raises(I2VError):
        run_i2v(timeline, cfg, tmp_path / "work")


def test_skip_i2v_marks_scenes_skipped(tmp_path, fast_config):
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))
    report = run_i2v(timeline, fast_config, tmp_path / "work", skip=True)

    assert report.as_log_map() == {"SCENE-02": STATUS_SKIPPED}
    assert timeline.scenes[1].source == SOURCE_I2V_FALLBACK


def test_no_i2v_scenes_is_a_noop(tmp_path, fast_config):
    timeline = make_timeline(tmp_path, count=3, i2v_orders=())
    report = run_i2v(timeline, fast_config, tmp_path / "work")
    assert report.outcomes == []


@needs_ffmpeg
def test_retry_then_success(tmp_path, fast_config):
    """첫 시도가 실패해도 재시도로 살아나면 fallback이 아니다."""
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=2.0)
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))

    with FakeComfyUI(video_bytes) as server:
        cfg = configure(fast_config, server, retry={"attempts": 2, "backoffSec": 0.0})
        server.mode = "exec_error"

        class FlakyProvider(ComfyUILTXProvider):
            calls = 0

            def generate(self, request):
                FlakyProvider.calls += 1
                if FlakyProvider.calls == 1:
                    raise I2VError("일시적 오류")
                server.mode = "success"
                return super().generate(request)

        provider = FlakyProvider(cfg.i2v, cfg.repo_root)
        report = run_i2v(timeline, cfg, tmp_path / "work", provider=provider)

    assert report.as_log_map() == {"SCENE-02": STATUS_SUCCESS}
    assert FlakyProvider.calls == 2


@needs_ffmpeg
def test_generated_duration_is_clamped_to_spec_range(tmp_path, fast_config):
    """명세서 §16 — I2V는 3~5초."""
    ffmpeg = FFmpeg()
    video_bytes = make_test_video(ffmpeg, tmp_path / "ltx.mp4", seconds=2.0)
    timeline = make_timeline(tmp_path, count=3, i2v_orders=(2,))
    timeline.scenes[1].duration = 12.0  # 씬이 아주 길어도

    with FakeComfyUI(video_bytes) as server:
        run_i2v(timeline, configure(fast_config, server), tmp_path / "work")

    length = server.submitted_workflows[0]["70"]["inputs"]["length"]
    assert length == 150, "5초(=150프레임)로 제한되어야 합니다"
