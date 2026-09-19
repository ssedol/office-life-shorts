"""네이버 클로바 보이스(CLOVA Voice Premium) 어댑터 (명세서 §18).

한국어 발음 정밀도와 억양 안정성이 높다고 평가받는 국내 서비스다.
NAVER Cloud Platform에 가입해 CLOVA Voice를 신청하면 키 두 개가 나온다.

    .env
        CLOVA_CLIENT_ID=...       (X-NCP-APIGW-API-KEY-ID)
        CLOVA_CLIENT_SECRET=...   (X-NCP-APIGW-API-KEY)

화자(speaker) 이름 예시 — 목록은 콘솔에서 확인한다.
    nara      밝은 여성 (기본값으로 둔다)
    nminyoung 차분한 여성
    nyejin    성숙한 여성
    njinho    차분한 남성
    nsinu     친근한 남성

주의: 이 어댑터는 이 저장소에서 실제 API로 검증한 적이 없다(개발 컨테이너에서
naveropenapi.apigw.ntruss.com이 막혀 있다). HTTP 프로토콜은 가짜 서버로 검증했다.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import TTSError
from .base import SynthesisRequest, TTSProvider
from .http_common import form_encoded, post_for_audio, require_env

DEFAULT_BASE_URL = "https://naveropenapi.apigw.ntruss.com"
DEFAULT_SPEAKER = "nara"
CLIENT_ID_ENV = "CLOVA_CLIENT_ID"
CLIENT_SECRET_ENV = "CLOVA_CLIENT_SECRET"
SIGNUP_HINT = "https://www.ncloud.com/product/aiService/clovaVoice 에서 신청합니다"


def speed_to_clova(speed: float) -> int:
    """파이프라인의 배속(1.0 = 보통)을 클로바의 speed 값으로 바꾼다.

    클로바는 -5(가장 빠름) ~ 5(가장 느림)로, 방향이 반대이고 정수다.
    1.0배를 0으로 두고, 2배까지를 -5, 0.5배까지를 +5에 대응시킨다.
    """
    # 빠르게(1.0→0, 2.0→-5) / 느리게(1.0→0, 0.5→+5)는 기울기가 달라 따로 잡는다.
    value = -round((speed - 1.0) * 5.0) if speed >= 1.0 else round((1.0 - speed) * 10.0)
    return int(min(max(value, -5), 5))


class ClovaVoiceAdapter(TTSProvider):
    name = "clova"
    output_suffix = ".mp3"

    def preflight(self) -> None:
        require_env(CLIENT_ID_ENV, engine="CLOVA Voice", signup_hint=SIGNUP_HINT)
        require_env(CLIENT_SECRET_ENV, engine="CLOVA Voice", signup_hint=SIGNUP_HINT)

    def synthesize(self, request: SynthesisRequest) -> Path:
        self.preflight()
        client_id = require_env(CLIENT_ID_ENV, engine="CLOVA Voice", signup_hint=SIGNUP_HINT)
        client_secret = require_env(CLIENT_SECRET_ENV, engine="CLOVA Voice", signup_hint=SIGNUP_HINT)

        text = request.text.strip()
        if not text:
            raise TTSError("합성할 텍스트가 비어 있습니다")

        speaker = request.voice or str(self.options.get("voice") or DEFAULT_SPEAKER)
        base_url = str(self.options.get("baseUrl") or DEFAULT_BASE_URL).rstrip("/")
        audio_format = str(self.options.get("format") or "mp3")

        fields: dict[str, object] = {
            "speaker": speaker,
            "text": text,
            "format": audio_format,
            "speed": speed_to_clova(request.speed),
            "volume": int(self.options.get("volume", 0)),
            "pitch": int(self.options.get("pitch", 0)),
            "alpha": int(self.options.get("alpha", 0)),
        }
        # emotion은 지원 화자에서만 받는다. 설정에 없으면 아예 보내지 않는다.
        if self.options.get("emotion") is not None:
            fields["emotion"] = int(self.options["emotion"])
            fields["emotion-strength"] = int(self.options.get("emotionStrength", 1))

        out_path = request.out_path.with_suffix(f".{audio_format}")

        return post_for_audio(
            f"{base_url}/tts-premium/v1/tts",
            engine="CLOVA Voice",
            headers={
                "X-NCP-APIGW-API-KEY-ID": client_id,
                "X-NCP-APIGW-API-KEY": client_secret,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=form_encoded(fields),
            out_path=out_path,
            timeout=float(self.options.get("timeoutSec", 60)),
        )

    def describe(self) -> str:
        return f"CLOVA Voice ({self.options.get('voice') or DEFAULT_SPEAKER})"
