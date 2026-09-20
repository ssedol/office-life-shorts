"""TEST-9 유료 TTS 어댑터 (명세서 §18 Provider 교체 구조, §26 비밀 값).

ElevenLabs / CLOVA / Typecast는 실제 API로 검증하지 못했다(개발 컨테이너에서
세 도메인 모두 egress 정책에 막혀 있다). 여기서 검증하는 것은 두 가지다.

  1. 우리가 보내는 요청이 의도한 모양인가 — 인증 헤더, 본문 필드, 배속 변환
  2. 서버가 이상한 응답을 줄 때 사람이 고칠 수 있는 오류가 나오는가

실제 엔드포인트 주소와 필드 이름이 문서와 맞는지는 운영자 PC에서
tools/tts_compare.py로 확인해야 한다.
"""

from __future__ import annotations

import pytest

from src.errors import TTSError
from src.tts.base import SynthesisRequest
from src.tts.clova_adapter import ClovaVoiceAdapter, speed_to_clova
from src.tts.elevenlabs_adapter import ElevenLabsAdapter
from src.tts.factory import REGISTRY, resolve_settings
from src.tts.typecast_adapter import TypecastAdapter
from tests.fake_tts_api import FakeTTSAPI


@pytest.fixture
def keys(monkeypatch):
    """세 서비스의 키를 모두 채워 둔다."""
    for name, value in (
        ("ELEVENLABS_API_KEY", "el-key"),
        ("CLOVA_CLIENT_ID", "clova-id"),
        ("CLOVA_CLIENT_SECRET", "clova-secret"),
        ("TYPECAST_API_KEY", "tc-key"),
    ):
        monkeypatch.setenv(name, value)


def request_for(tmp_path, text="안녕하세요", speed=1.0):
    return SynthesisRequest(text=text, out_path=tmp_path / "out", speed=speed)


# ---- 등록 ------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["elevenlabs", "clova", "typecast"])
def test_engines_are_registered(engine):
    assert engine in REGISTRY


def test_schema_engine_list_matches_registry():
    """schema/project.schema.json의 engine 목록은 REGISTRY와 같아야 한다.

    같은 목록이 두 군데 있어서 엔진을 추가할 때 한쪽만 고치기 쉽다.
    실제로 유료 엔진 3종을 추가했을 때 스키마를 빠뜨려, project.json에
    engine을 적으면 검증이 실패하는 상태였다.
    """
    import json
    from pathlib import Path

    schema_path = Path(__file__).resolve().parent.parent / "schema/project.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    listed = set(schema["properties"]["tts"]["properties"]["engine"]["enum"])

    assert listed == set(REGISTRY), (
        f"스키마에만 있음: {sorted(listed - set(REGISTRY))} / "
        f"REGISTRY에만 있음: {sorted(set(REGISTRY) - listed)}"
    )


# ---- ElevenLabs -------------------------------------------------------------


def test_elevenlabs_sends_expected_request(tmp_path, keys):
    with FakeTTSAPI() as server:
        adapter = ElevenLabsAdapter({
            "baseUrl": server.base_url,
            "voice": "VOICE123",
            "model": "eleven_multilingual_v2",
            "stability": 0.45,
        })
        out = adapter.synthesize(request_for(tmp_path, speed=1.1))

        assert out.read_bytes() == server.audio_bytes
        method, path, _, _ = server.requests[-1]
        assert method == "POST"
        assert path.startswith("/v1/text-to-speech/VOICE123")
        assert server.last_headers()["xi-api-key"] == "el-key"

        body = server.last_json()
        assert body["text"] == "안녕하세요"
        assert body["model_id"] == "eleven_multilingual_v2"
        assert body["voice_settings"]["stability"] == 0.45
        assert body["voice_settings"]["speed"] == pytest.approx(1.1)


def test_elevenlabs_clamps_speed_to_supported_range(tmp_path, keys):
    """ElevenLabs는 0.7~1.2만 받는다. 범위를 넘으면 잘라서 보낸다."""
    with FakeTTSAPI() as server:
        adapter = ElevenLabsAdapter({"baseUrl": server.base_url, "voice": "V"})
        adapter.synthesize(request_for(tmp_path, speed=2.0))
        assert server.last_json()["voice_settings"]["speed"] == 1.2

        adapter.synthesize(request_for(tmp_path, speed=0.5))
        assert server.last_json()["voice_settings"]["speed"] == 0.7


def test_elevenlabs_without_key_explains_how_to_fix(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    adapter = ElevenLabsAdapter({"voice": "V"})

    with pytest.raises(TTSError) as exc:
        adapter.synthesize(request_for(tmp_path))

    assert "ELEVENLABS_API_KEY" in str(exc.value)
    assert any(".env" in d for d in exc.value.details)


def test_elevenlabs_without_voice_id_is_rejected(keys):
    with pytest.raises(TTSError, match="보이스 ID"):
        ElevenLabsAdapter({"voice": None}).preflight()


# ---- CLOVA ------------------------------------------------------------------


def test_clova_sends_expected_form(tmp_path, keys):
    with FakeTTSAPI() as server:
        adapter = ClovaVoiceAdapter({"baseUrl": server.base_url, "voice": "nminyoung"})
        out = adapter.synthesize(request_for(tmp_path))

        assert out.suffix == ".mp3"
        assert out.read_bytes() == server.audio_bytes

        _, path, _, _ = server.requests[-1]
        assert path == "/tts-premium/v1/tts"
        assert server.last_headers()["x-ncp-apigw-api-key-id"] == "clova-id"
        assert server.last_headers()["x-ncp-apigw-api-key"] == "clova-secret"

        form = server.last_form()
        assert form["speaker"] == "nminyoung"
        assert form["text"] == "안녕하세요"
        assert form["format"] == "mp3"
        # emotion을 설정하지 않았으면 아예 보내지 않는다 (지원 화자에서만 동작한다)
        assert "emotion" not in form


def test_clova_sends_emotion_only_when_configured(tmp_path, keys):
    with FakeTTSAPI() as server:
        adapter = ClovaVoiceAdapter({"baseUrl": server.base_url, "voice": "nara", "emotion": 2})
        adapter.synthesize(request_for(tmp_path))

        form = server.last_form()
        assert form["emotion"] == "2"
        assert form["emotion-strength"] == "1"


@pytest.mark.parametrize(("speed", "expected"), [
    (1.0, 0),    # 보통
    (2.0, -5),   # 가장 빠름 (클로바는 음수가 빠르다)
    (0.5, 5),    # 가장 느림
    (1.2, -1),
    (0.8, 2),
    (5.0, -5),   # 범위를 넘으면 자른다
])
def test_clova_speed_conversion(speed, expected):
    """파이프라인의 배속과 클로바의 speed는 방향이 반대다."""
    assert speed_to_clova(speed) == expected


def test_clova_without_keys_explains_how_to_fix(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOVA_CLIENT_ID", raising=False)
    monkeypatch.setenv("CLOVA_CLIENT_SECRET", "x")

    with pytest.raises(TTSError) as exc:
        ClovaVoiceAdapter({}).synthesize(request_for(tmp_path))

    assert "CLOVA_CLIENT_ID" in str(exc.value)


# ---- Typecast ---------------------------------------------------------------


def test_typecast_accepts_direct_audio(tmp_path, keys):
    """오디오를 바로 주는 API면 그대로 저장한다."""
    with FakeTTSAPI() as server:
        adapter = TypecastAdapter({"baseUrl": server.base_url, "voice": "actor-1"})
        out = adapter.synthesize(request_for(tmp_path))

        assert out.read_bytes() == server.audio_bytes
        assert server.last_headers()["authorization"] == "Bearer tc-key"

        body = server.last_json()
        assert body["text"] == "안녕하세요"
        assert body["voice_id"] == "actor-1"
        assert body["language"] == "kor"


def test_typecast_polls_until_job_is_done(tmp_path, keys):
    """작업 ID를 주는 API면 완료될 때까지 조회한 뒤 내려받는다."""
    with FakeTTSAPI(mode="typecast_job") as server:
        adapter = TypecastAdapter({
            "baseUrl": server.base_url, "voice": "actor-1", "pollIntervalSec": 0.01,
        })
        out = adapter.synthesize(request_for(tmp_path))

        assert out.read_bytes() == server.audio_bytes
        paths = [p for method, p, _, _ in server.requests if method == "GET"]
        assert any(p.startswith("/v1/status/") for p in paths), "상태를 조회하지 않았습니다"
        assert any(p.startswith("/v1/audio/") for p in paths), "오디오를 내려받지 않았습니다"


def test_typecast_reports_failed_job(tmp_path, keys):
    with FakeTTSAPI(mode="job_failed") as server:
        adapter = TypecastAdapter({
            "baseUrl": server.base_url, "voice": "actor-1", "pollIntervalSec": 0.01,
        })
        with pytest.raises(TTSError, match="실패"):
            adapter.synthesize(request_for(tmp_path))


def test_typecast_extra_fields_are_merged(tmp_path, keys):
    """문서와 형식이 다를 때 코드를 고치지 않고 설정으로 맞출 수 있어야 한다."""
    with FakeTTSAPI() as server:
        adapter = TypecastAdapter({
            "baseUrl": server.base_url,
            "speakPath": "/v1/text-to-speech",
            "voice": "actor-1",
            "extraFields": {"xapi_hd": True, "actor_id": "legacy-id"},
        })
        adapter.synthesize(request_for(tmp_path))

        body = server.last_json()
        assert body["xapi_hd"] is True
        assert body["actor_id"] == "legacy-id"


def test_typecast_custom_auth_header(tmp_path, keys):
    with FakeTTSAPI() as server:
        adapter = TypecastAdapter({
            "baseUrl": server.base_url, "voice": "a",
            "authHeader": "X-API-KEY", "authScheme": "",
        })
        adapter.synthesize(request_for(tmp_path))

        assert server.last_headers()["x-api-key"] == "tc-key"


# ---- 공통 오류 처리 ----------------------------------------------------------


@pytest.mark.parametrize("make", [
    lambda url: ElevenLabsAdapter({"baseUrl": url, "voice": "V"}),
    lambda url: ClovaVoiceAdapter({"baseUrl": url, "voice": "nara"}),
    lambda url: TypecastAdapter({"baseUrl": url, "voice": "a"}),
])
def test_unauthorized_points_at_the_api_key(tmp_path, keys, make):
    with FakeTTSAPI(mode="unauthorized") as server:
        with pytest.raises(TTSError) as exc:
            make(server.base_url).synthesize(request_for(tmp_path))

        assert "401" in str(exc.value)
        assert any("키" in d for d in exc.value.details), exc.value.details


@pytest.mark.parametrize("make", [
    lambda url: ElevenLabsAdapter({"baseUrl": url, "voice": "V"}),
    lambda url: ClovaVoiceAdapter({"baseUrl": url, "voice": "nara"}),
])
def test_json_instead_of_audio_is_reported(tmp_path, keys, make):
    """200인데 오디오가 아니면 그 본문을 그대로 보여준다."""
    with FakeTTSAPI(mode="json_instead") as server:
        with pytest.raises(TTSError) as exc:
            make(server.base_url).synthesize(request_for(tmp_path))

        assert "quota exceeded" in " ".join(exc.value.details)


def test_empty_response_is_rejected(tmp_path, keys):
    with FakeTTSAPI(mode="empty") as server, pytest.raises(TTSError, match="빈 응답"):
        ClovaVoiceAdapter({"baseUrl": server.base_url}).synthesize(request_for(tmp_path))


def test_empty_text_is_rejected(tmp_path, keys):
    with pytest.raises(TTSError, match="비어 있"):
        ClovaVoiceAdapter({"voice": "nara"}).synthesize(request_for(tmp_path, text="   "))


# ---- 보이스가 엔진을 넘어 새지 않는다 ---------------------------------------


def test_voice_does_not_leak_across_engines(default_config):
    """edge용 보이스 이름이 elevenlabs로 넘어가면 엉뚱한 요청이 나간다.

    config/tts.json의 최상위 voice는 최상위 engine(edge)을 위한 값이다.
    --tts-engine으로 다른 엔진을 고르면 그 값을 물려받으면 안 된다.
    """
    edge = resolve_settings(default_config.tts, engine_override="edge")
    assert edge.voice == "ko-KR-SunHiNeural"

    for engine in ("elevenlabs", "typecast"):
        settings = resolve_settings(default_config.tts, engine_override=engine)
        assert settings.voice != "ko-KR-SunHiNeural", f"{engine}에 edge 보이스가 샜습니다"


def test_engine_block_voice_is_used(default_config):
    """engines.<engine>.voice는 그 엔진의 값이므로 그대로 쓴다."""
    settings = resolve_settings(default_config.tts, engine_override="clova")
    assert settings.voice == "nara"


def test_cli_voice_override_always_wins(default_config):
    settings = resolve_settings(default_config.tts, engine_override="elevenlabs", voice_override="ABC123")
    assert settings.voice == "ABC123"
