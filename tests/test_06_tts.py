"""TEST-6 TTS (명세서 §28, §18)."""

from __future__ import annotations

import pytest

from src.errors import ErrorCode, TTSError
from src.media.ffmpeg import FFmpeg
from src.scene.models import Scene, TTSSettings
from src.tts.base import SynthesisRequest
from src.tts.edge_adapter import EdgeTTSAdapter, _rate_string
from src.tts.factory import REGISTRY, create_provider, resolve_settings
from src.tts.local_cli_adapter import SupertonicAdapter
from src.tts.narration import build_narration, synthesize_scenes
from src.tts.offline_adapter import OfflineAdapter, estimate_duration
from tests.conftest import needs_ffmpeg


def make_scenes(count: int = 3, narration: str = "테스트 내레이션입니다.") -> list[Scene]:
    return [
        Scene(
            id=f"SCENE-{i:02d}", order=i, duration_sec=3.0, type="STILL",
            reason="", image_file=f"scene-{i:02d}.png",
            narration=narration, subtitle="자막",
        )
        for i in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# Provider 교체 가능 구조 (명세서 §18)
# ---------------------------------------------------------------------------

def test_every_registered_engine_can_be_instantiated(default_config):
    for engine in sorted(set(REGISTRY)):
        settings = resolve_settings(default_config.tts, engine_override=engine)
        assert create_provider(settings).name


def test_unknown_engine_is_rejected(default_config):
    with pytest.raises(TTSError) as exc_info:
        resolve_settings(default_config.tts, engine_override="없는엔진")
    assert exc_info.value.code == ErrorCode.TTS_FAILED


def test_project_json_overrides_config(default_config):
    settings = resolve_settings(
        default_config.tts,
        TTSSettings(engine="offline", voice="테스트보이스", speed=1.2),
    )
    assert settings.engine == "offline"
    assert settings.voice == "테스트보이스"
    assert settings.speed == 1.2


def test_cli_override_beats_project_json(default_config):
    settings = resolve_settings(
        default_config.tts,
        TTSSettings(engine="edge", voice="A", speed=1.0),
        engine_override="offline",
        voice_override="B",
    )
    assert settings.engine == "offline"
    assert settings.voice == "B"


def test_undecided_voice_falls_back_to_config(default_config):
    """명세서 §11 예시의 'UNDECIDED'는 자리표시자다 (§35-2 미확정).

    기본 엔진과 보이스는 운영자가 바꾸는 값이라 여기에 박아두지 않는다.
    확인할 것은 '자리표시자를 건너뛰고 config 기본값으로 떨어지는가'이다.
    """
    기본값 = resolve_settings(default_config.tts)
    settings = resolve_settings(default_config.tts, TTSSettings(voice="UNDECIDED"))
    assert settings.voice == 기본값.voice
    assert settings.voice, "자리표시자가 보이스 전체를 None으로 만들면 안 된다"


@pytest.mark.parametrize("speed", [0.4, 2.5, 0.0, -1])
def test_out_of_range_speed_is_rejected(default_config, speed):
    with pytest.raises(TTSError):
        resolve_settings(default_config.tts, TTSSettings(speed=speed))


@pytest.mark.parametrize("speed,expected", [(1.0, "+0%"), (1.05, "+5%"), (0.9, "-10%"), (1.25, "+25%")])
def test_edge_rate_string(speed, expected):
    assert _rate_string(speed) == expected


def test_supertonic_without_cli_path_gives_actionable_error():
    """명세서 §35-2 미확정 — 설정 전에는 무엇을 채워야 하는지 알려줘야 한다."""
    with pytest.raises(TTSError) as exc_info:
        SupertonicAdapter({"cliPath": None}).preflight()
    assert "cliPath" in str(exc_info.value)


def test_edge_adapter_reads_proxy_from_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    assert EdgeTTSAdapter({})._proxy() == "http://proxy.example:3128"
    assert EdgeTTSAdapter({"proxy": ""})._proxy() is None
    assert EdgeTTSAdapter({"proxy": "http://x:1"})._proxy() == "http://x:1"


# ---------------------------------------------------------------------------
# TEST-6 WAV 생성, 길이 > 0
# ---------------------------------------------------------------------------

def test_offline_adapter_writes_valid_wav(tmp_path):
    out = OfflineAdapter({}).synthesize(SynthesisRequest("안녕하세요 테스트입니다.", tmp_path / "a", sample_rate=48000))
    assert out.suffix == ".wav"
    assert out.stat().st_size > 0


def test_empty_text_is_rejected(tmp_path):
    with pytest.raises(TTSError):
        OfflineAdapter({}).synthesize(SynthesisRequest("   ", tmp_path / "a"))


def test_estimated_duration_grows_with_text():
    short = estimate_duration("짧다", 7.0, 0.1)
    long = estimate_duration("이것은 훨씬 더 긴 문장이고 글자 수가 많습니다.", 7.0, 0.1)
    assert 0 < short < long


def test_faster_speed_shortens_duration():
    assert estimate_duration("같은 문장입니다", 7.0, 0.1, speed=1.5) < estimate_duration("같은 문장입니다", 7.0, 0.1, speed=1.0)


def test_default_rate_matches_measured_edge_tts():
    """기본 추정치가 실제 edge-tts 길이와 크게 어긋나면 안 된다.

    2026-09-18 에피소드 8씬을 ko-KR-SunHiNeural(speed 1.0)로 합성한 실측값이 41.93초다.
    오프라인 미리보기의 길이 경고가 쓸모 있으려면 추정치가 이 값 근처여야 한다.
    추정 모델을 바꿀 때 이 테스트가 깨지면 DEFAULT_CHARS_PER_SEC를 다시 맞춘다.
    """
    import json
    from pathlib import Path

    from src.tts.offline_adapter import DEFAULT_CHARS_PER_SEC, DEFAULT_MIN_SEC

    plan_path = Path(__file__).resolve().parent.parent / "inputs/2026-09-18/scene-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    estimated = sum(
        estimate_duration(s["narration"], DEFAULT_CHARS_PER_SEC, DEFAULT_MIN_SEC)
        for s in plan["scenes"]
    )

    measured = 41.93
    assert abs(estimated - measured) / measured < 0.10, (
        f"추정 {estimated:.2f}초 vs 실측 {measured}초 — 오차 10%를 넘습니다"
    )


@needs_ffmpeg
def test_synthesize_scenes_produces_wav_per_scene(tmp_path, default_config):
    ffmpeg = FFmpeg()
    settings = resolve_settings(default_config.tts, engine_override="offline")
    scenes = make_scenes(3)

    audios = synthesize_scenes(scenes, create_provider(settings), settings, ffmpeg, tmp_path / "tts")

    assert len(audios) == 3
    for audio in audios:
        assert audio.path is not None and audio.path.is_file()
        assert audio.duration > 0, "TEST-6: 길이 > 0"
        assert ffmpeg.duration(audio.path) == pytest.approx(audio.duration, abs=0.02)


@needs_ffmpeg
def test_empty_narration_becomes_silent_scene(tmp_path, default_config):
    ffmpeg = FFmpeg()
    settings = resolve_settings(default_config.tts, engine_override="offline")
    scenes = make_scenes(3)
    scenes[1].narration = ""

    audios = synthesize_scenes(scenes, create_provider(settings), settings, ffmpeg, tmp_path / "tts")

    assert audios[1].is_silent and audios[1].duration == 0.0
    assert not audios[0].is_silent


@needs_ffmpeg
def test_all_empty_narration_fails(tmp_path, default_config):
    ffmpeg = FFmpeg()
    settings = resolve_settings(default_config.tts, engine_override="offline")
    scenes = make_scenes(3, narration="")

    with pytest.raises(TTSError) as exc_info:
        synthesize_scenes(scenes, create_provider(settings), settings, ffmpeg, tmp_path / "tts")
    assert exc_info.value.code == ErrorCode.TTS_FAILED


@needs_ffmpeg
def test_tts_failure_aborts_with_retries(tmp_path, default_config):
    """명세서 §25 — TTS 실패는 중단. 단 재시도는 한다."""
    from src.tts.base import TTSProvider

    class AlwaysFails(TTSProvider):
        name = "always-fails"
        calls = 0

        def synthesize(self, request):
            AlwaysFails.calls += 1
            raise TTSError("합성 실패")

    settings = resolve_settings(default_config.tts, engine_override="offline")
    settings.base = dict(settings.base, retry={"attempts": 3, "backoffSec": 0.0})

    with pytest.raises(TTSError) as exc_info:
        synthesize_scenes(make_scenes(2), AlwaysFails(), settings, FFmpeg(), tmp_path / "tts")

    assert exc_info.value.code == ErrorCode.TTS_FAILED
    assert AlwaysFails.calls == 3


@needs_ffmpeg
def test_loudnorm_normalization_runs(tmp_path):
    """명세서 §18 음량 정규화. 무음이 아닌 실제 신호로 확인한다."""
    ffmpeg = FFmpeg()
    tone = tmp_path / "tone.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "pcm_s16le", str(tone)])

    out = ffmpeg.to_wav(tone, tmp_path / "norm.wav", normalize={"enabled": True, "targetLufs": -16.0})

    assert out.is_file()
    assert ffmpeg.duration(out) == pytest.approx(2.0, abs=0.2)

    probe = ffmpeg.probe(out)
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert int(audio["sample_rate"]) == 48000
    assert int(audio["channels"]) == 1


# ---------------------------------------------------------------------------
# narration.wav 조립
# ---------------------------------------------------------------------------

@needs_ffmpeg
def test_narration_matches_timeline_length(tmp_path, default_config):
    ffmpeg = FFmpeg()
    settings = resolve_settings(default_config.tts, engine_override="offline")
    audios = synthesize_scenes(make_scenes(4), create_provider(settings), settings, ffmpeg, tmp_path / "tts")

    durations = [5.0, 4.0, 6.0, 5.0]
    out = build_narration(audios, durations, [0.15] * 4, tmp_path / "narration.wav", ffmpeg, settings, tmp_path / "work")

    assert ffmpeg.duration(out) == pytest.approx(sum(durations), abs=0.05)


@needs_ffmpeg
def test_narration_handles_silent_scenes(tmp_path, default_config):
    ffmpeg = FFmpeg()
    settings = resolve_settings(default_config.tts, engine_override="offline")
    scenes = make_scenes(3)
    scenes[0].narration = ""
    audios = synthesize_scenes(scenes, create_provider(settings), settings, ffmpeg, tmp_path / "tts")

    out = build_narration(audios, [3.0, 3.0, 3.0], [0.0, 0.15, 0.15], tmp_path / "n.wav", ffmpeg, settings, tmp_path / "w")
    assert ffmpeg.duration(out) == pytest.approx(9.0, abs=0.05)


@needs_ffmpeg
def test_mismatched_lengths_are_rejected(tmp_path, default_config):
    settings = resolve_settings(default_config.tts, engine_override="offline")
    with pytest.raises(TTSError):
        build_narration([], [1.0], [0.0], tmp_path / "n.wav", FFmpeg(), settings, tmp_path / "w")
