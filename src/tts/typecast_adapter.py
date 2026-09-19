"""타입캐스트(Typecast) 어댑터 (명세서 §18).

한국 회사이고, 지원 언어 35개 중 한국어를 포함한 6개를 "네이티브 수준"으로
지원한다고 밝히고 있다. 감정·연기 톤 조절이 되어 국내 쇼츠 제작에 많이 쓰인다.

    .env
        TYPECAST_API_KEY=...

⚠️ 확실하지 않은 부분 — 반드시 읽으세요.

이 어댑터는 실제 API로 검증하지 못했다. 개발 컨테이너에서 typecast.ai가
네트워크 정책에 막혀 공식 문서를 열 수 없었다. 그래서 요청 형식은
"이럴 것이다"라는 추측이 섞여 있다.

대신 두 가지로 위험을 줄였다.

1. 응답이 오디오든 작업 ID든 모두 처리한다. 타입캐스트가 바로 오디오를 주면
   그대로 저장하고, 작업 ID를 주면 완료될 때까지 조회한다.
2. 엔드포인트 경로와 필드 이름을 config/tts.json에서 바꿀 수 있게 했다.
   실제 문서와 다르면 코드를 고치지 않고 설정만 고치면 된다.

https://typecast.ai/developers/api/ 문서와 대조해 보시고, 다르면 알려주세요.
바로 맞추겠습니다.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..errors import TTSError
from .base import SynthesisRequest, TTSProvider
from .http_common import (
    find_first,
    get_json,
    get_to_file,
    json_encoded,
    post_audio_or_json,
    require_env,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.typecast.ai"
DEFAULT_SPEAK_PATH = "/v1/text-to-speech"
API_KEY_ENV = "TYPECAST_API_KEY"
SIGNUP_HINT = "https://typecast.ai/developers/api/ 에서 API 키를 발급합니다"

#: 작업 결과 JSON에서 오디오 주소가 담길 만한 키 이름들
_AUDIO_URL_KEYS = ("audio_download_url", "audio_url", "download_url", "speak_url", "url")
#: 작업 상태 조회 주소가 담길 만한 키 이름들
_STATUS_URL_KEYS = ("speak_v2_url", "status_url", "result_url", "self")
_DONE_STATES = {"done", "completed", "success", "succeeded"}
_FAILED_STATES = {"failed", "error", "canceled", "cancelled"}


class TypecastAdapter(TTSProvider):
    name = "typecast"
    output_suffix = ".mp3"

    def preflight(self) -> None:
        require_env(API_KEY_ENV, engine="Typecast", signup_hint=SIGNUP_HINT)
        if not self.options.get("voice"):
            raise TTSError(
                "Typecast: 보이스(actor) 이름이 없습니다",
                details=[
                    "config/tts.json의 engines.typecast.voice에 값을 넣으세요",
                    "타입캐스트 콘솔에서 쓸 보이스의 ID를 확인합니다",
                ],
            )

    def _headers(self, api_key: str) -> dict[str, str]:
        scheme = str(self.options.get("authScheme", "Bearer")).strip()
        header_name = str(self.options.get("authHeader", "Authorization")).strip()
        value = f"{scheme} {api_key}".strip() if scheme else api_key
        return {header_name: value, "Content-Type": "application/json"}

    def synthesize(self, request: SynthesisRequest) -> Path:
        self.preflight()
        api_key = require_env(API_KEY_ENV, engine="Typecast", signup_hint=SIGNUP_HINT)

        text = request.text.strip()
        if not text:
            raise TTSError("합성할 텍스트가 비어 있습니다")

        base_url = str(self.options.get("baseUrl") or DEFAULT_BASE_URL).rstrip("/")
        speak_path = str(self.options.get("speakPath") or DEFAULT_SPEAK_PATH)
        voice = request.voice or str(self.options["voice"])
        out_path = request.out_path.with_suffix(self.output_suffix)

        payload: dict[str, object] = {
            "text": text,
            "voice_id": voice,
            "model": str(self.options.get("model") or "ssfm-v21"),
            "language": str(self.options.get("language") or "kor"),
            "output": {
                "volume": int(self.options.get("volume", 100)),
                "audio_pitch": int(self.options.get("pitch", 0)),
                "audio_tempo": float(request.speed),
                "audio_format": "mp3",
            },
        }
        emotion = self.options.get("emotion")
        if emotion:
            payload["prompt"] = {"emotion_preset": str(emotion),
                                 "emotion_intensity": float(self.options.get("emotionIntensity", 1.0))}
        payload.update(dict(self.options.get("extraFields") or {}))

        timeout = float(self.options.get("timeoutSec", 60))
        audio, job = post_audio_or_json(
            f"{base_url}{speak_path}",
            engine="Typecast",
            headers=self._headers(api_key),
            body=json_encoded(payload),
            out_path=out_path,
            timeout=timeout,
        )
        if audio is not None:
            return audio

        assert job is not None
        return self._await_job(job, api_key, out_path, base_url, timeout)

    def _await_job(self, job: dict, api_key: str, out_path: Path, base_url: str, timeout: float) -> Path:
        """작업 ID를 받았을 때 완료될 때까지 기다렸다 오디오를 내려받는다."""
        audio_url = find_first(job, _AUDIO_URL_KEYS)
        if audio_url:
            return get_to_file(audio_url, engine="Typecast", out_path=out_path,
                               headers=self._headers(api_key), timeout=timeout)

        status_url = find_first(job, _STATUS_URL_KEYS)
        if not status_url:
            raise TTSError(
                "Typecast 응답에서 오디오 주소를 찾지 못했습니다",
                details=[
                    f"받은 키: {', '.join(sorted(job)) or '(없음)'}",
                    "config/tts.json engines.typecast의 baseUrl/speakPath를 확인하세요",
                    "실제 API 문서와 형식이 다르면 알려주세요",
                ],
            )
        if status_url.startswith("/"):
            status_url = f"{base_url}{status_url}"

        interval = float(self.options.get("pollIntervalSec", 1.0))
        deadline = time.monotonic() + float(self.options.get("pollTimeoutSec", 120))
        while time.monotonic() < deadline:
            state = get_json(status_url, engine="Typecast", headers=self._headers(api_key), timeout=timeout)
            status = str(find_first(state, ("status", "state")) or "").lower()
            if status in _FAILED_STATES:
                raise TTSError("Typecast 합성 작업이 실패했습니다", details=[str(state)[:500]])
            audio_url = find_first(state, _AUDIO_URL_KEYS)
            if audio_url and (not status or status in _DONE_STATES):
                return get_to_file(audio_url, engine="Typecast", out_path=out_path,
                                   headers=self._headers(api_key), timeout=timeout)
            time.sleep(interval)

        raise TTSError("Typecast 합성 작업이 제한 시간 안에 끝나지 않았습니다", details=[status_url])

    def describe(self) -> str:
        return f"Typecast ({self.options.get('voice') or '미지정'})"
