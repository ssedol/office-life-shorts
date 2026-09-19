"""ElevenLabs 어댑터 (명세서 §18 — Provider 교체 가능 구조).

글로벌 품질 최상위로 평가받는 유료 TTS다. 한국어도 지원하지만 주력 언어는 아니라
실제로 들어보고 판단해야 한다(tools/tts_compare.py 참고).

가격(2026-09 기준, 종량제):
    eleven_multilingual_v2 / eleven_v3   $0.10 / 1,000자
    eleven_flash_v2_5 / eleven_turbo_v2_5 $0.05 / 1,000자

이 채널은 한 편이 260자 정도라 매일 올려도 월 1달러 미만이다.

보이스 ID는 이름이 아니라 20자 내외의 해시 문자열이다.
https://elevenlabs.io/app/voice-library 에서 보이스를 고르면 ID를 볼 수 있다.

주의: 이 어댑터는 이 저장소에서 실제 API로 검증한 적이 없다(개발 컨테이너에서
api.elevenlabs.io가 막혀 있다). HTTP 프로토콜은 가짜 서버로 검증했다.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import TTSError
from .base import SynthesisRequest, TTSProvider
from .http_common import json_encoded, post_for_audio, require_env

DEFAULT_BASE_URL = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
API_KEY_ENV = "ELEVENLABS_API_KEY"


class ElevenLabsAdapter(TTSProvider):
    name = "elevenlabs"
    output_suffix = ".mp3"

    def preflight(self) -> None:
        require_env(
            API_KEY_ENV,
            engine="ElevenLabs",
            signup_hint="https://elevenlabs.io/app/settings/api-keys 에서 발급합니다",
        )
        if not self._voice_id():
            raise TTSError(
                "ElevenLabs: 보이스 ID가 없습니다",
                details=[
                    "config/tts.json의 engines.elevenlabs.voice에 보이스 ID를 넣으세요",
                    "이름이 아니라 ID입니다 (예: 21m00Tcm4TlvDq8ikWAM)",
                    "https://elevenlabs.io/app/voice-library 에서 확인합니다",
                ],
            )

    def _voice_id(self) -> str | None:
        value = self.options.get("voice")
        text = str(value).strip() if value else ""
        return text or None

    def synthesize(self, request: SynthesisRequest) -> Path:
        self.preflight()
        api_key = require_env(API_KEY_ENV, engine="ElevenLabs", signup_hint="")

        text = request.text.strip()
        if not text:
            raise TTSError("합성할 텍스트가 비어 있습니다")

        voice_id = request.voice or self._voice_id()
        base_url = str(self.options.get("baseUrl") or DEFAULT_BASE_URL).rstrip("/")
        model = str(self.options.get("model") or DEFAULT_MODEL)
        output_format = str(self.options.get("outputFormat") or DEFAULT_OUTPUT_FORMAT)

        # ElevenLabs의 speed는 0.7~1.2만 받는다. 파이프라인의 배속을 그 범위로 자른다.
        speed = min(max(float(request.speed), 0.7), 1.2)

        voice_settings = {
            "stability": float(self.options.get("stability", 0.5)),
            "similarity_boost": float(self.options.get("similarityBoost", 0.75)),
            "style": float(self.options.get("style", 0.0)),
            "use_speaker_boost": bool(self.options.get("speakerBoost", True)),
            "speed": speed,
        }
        payload = {"text": text, "model_id": model, "voice_settings": voice_settings}

        language = self.options.get("languageCode")
        if language:
            payload["language_code"] = str(language)

        url = f"{base_url}/v1/text-to-speech/{voice_id}?output_format={output_format}"
        out_path = request.out_path.with_suffix(self.output_suffix)

        return post_for_audio(
            url,
            engine="ElevenLabs",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            body=json_encoded(payload),
            out_path=out_path,
            timeout=float(self.options.get("timeoutSec", 60)),
        )

    def describe(self) -> str:
        return f"ElevenLabs ({self.options.get('model') or DEFAULT_MODEL}, voice={self._voice_id() or '미지정'})"
