"""오프라인/테스트용 어댑터.

네트워크도 로컬 TTS 엔진도 없는 환경에서 파이프라인 전체(타임라인 → 자막 → 렌더)를
끝까지 돌려보기 위한 것이다. 글자 수로 길이만 추정해 같은 길이의 무음 WAV를 만든다.

실제 영상 제작에는 쓰지 않는다. config/tts.json engine을 'edge' 등으로 바꿔야 한다.
ffmpeg에 의존하지 않도록 표준 라이브러리 wave 모듈만 쓴다.
"""

from __future__ import annotations

import re
import wave
from pathlib import Path

from ..errors import TTSError
from .base import SynthesisRequest, TTSProvider

#: 실측 보정값. ko-KR-SunHiNeural(speed 1.0)로 2026-09-18 에피소드 8씬을 합성한 결과,
#: 공백 제외 204자가 41.93초였다. 부호당 0.18초 숨을 빼면 초당 5.2자다.
#: 처음 쓰던 7.0은 34% 빠른 값이라 오프라인 미리보기가 실제보다 11초 짧게 나왔다.
DEFAULT_CHARS_PER_SEC = 5.2
DEFAULT_MIN_SEC = 0.8


def estimate_duration(text: str, chars_per_sec: float, min_sec: float, speed: float = 1.0) -> float:
    """한국어 내레이션 길이를 글자 수로 대충 추정한다.

    오프라인 미리보기의 씬 길이가 실제 음성과 비슷해야 길이 경고가 쓸모 있다.
    기본값은 edge-tts 실측으로 맞춰 두었다(DEFAULT_CHARS_PER_SEC 주석 참고).
    다른 보이스나 speed를 쓰면 config/tts.json의 engines.offline.charsPerSec를 조정한다.
    """
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        return 0.0
    seconds = len(stripped) / max(chars_per_sec, 0.1) / max(speed, 0.1)
    # 문장 부호마다 짧은 숨을 더한다.
    seconds += 0.18 * len(re.findall(r"[.,!?…]", text))
    return max(seconds, min_sec)


class OfflineAdapter(TTSProvider):
    name = "offline"
    output_suffix = ".wav"
    supports_normalize = False  # 무음에 loudnorm을 걸면 의미가 없다

    def synthesize(self, request: SynthesisRequest) -> Path:
        text = request.text.strip()
        if not text:
            raise TTSError("합성할 텍스트가 비어 있습니다")

        seconds = estimate_duration(
            text,
            float(self.options.get("charsPerSec", DEFAULT_CHARS_PER_SEC)),
            float(self.options.get("minSec", DEFAULT_MIN_SEC)),
            request.speed,
        )
        out_path = request.out_path.with_suffix(self.output_suffix)
        frames = int(round(seconds * request.sample_rate))

        with wave.open(str(out_path), "wb") as fp:
            fp.setnchannels(1)
            fp.setsampwidth(2)
            fp.setframerate(request.sample_rate)
            fp.writeframes(b"\x00\x00" * frames)

        return out_path

    def describe(self) -> str:
        return "offline (무음 자리표시자 — 실제 음성 아님)"
