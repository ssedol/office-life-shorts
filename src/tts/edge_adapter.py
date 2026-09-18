"""edge-tts 어댑터 — 기본 무료 한국어 TTS (명세서 §18).

무가입/무료이고 한국어 뉴럴 보이스 품질이 현재 무료 옵션 중 가장 좋다.
단 인터넷 연결이 필요하다. 오프라인 환경에서는 config/tts.json의
engine을 "offline" 또는 "supertonic"으로 바꾼다.

보이스 목록은 `python -m edge_tts --list-voices | grep ko-KR` 로 확인한다.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..errors import TTSError
from .base import SynthesisRequest, TTSProvider

DEFAULT_VOICE = "ko-KR-SunHiNeural"


def _rate_string(speed: float) -> str:
    """1.05 → '+5%' 형태의 edge-tts rate 문자열."""
    percent = int(round((float(speed) - 1.0) * 100))
    return f"{percent:+d}%"


def _pitch_string(hz: float) -> str:
    return f"{int(round(float(hz))):+d}Hz"


class EdgeTTSAdapter(TTSProvider):
    name = "edge"
    output_suffix = ".mp3"  # edge-tts는 mp3(audio-24khz-48kbitrate-mono-mp3)를 반환한다

    def _proxy(self) -> str | None:
        """사내망 등 프록시 환경 지원.

        config/tts.json engines.edge.proxy 가 우선하고, 없으면 HTTPS_PROXY 환경변수를 쓴다.
        proxy를 빈 문자열("")로 두면 환경변수를 무시하고 직접 연결한다.
        """
        configured = self.options.get("proxy")
        if configured is not None:
            return str(configured) or None
        return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None

    def preflight(self) -> None:
        try:
            import edge_tts  # noqa: F401
        except ImportError as exc:
            raise TTSError(
                "edge-tts 패키지를 찾을 수 없습니다",
                details=[
                    "pip install edge-tts",
                    "오프라인 환경이라면 config/tts.json의 engine을 'offline'으로 바꾸세요",
                ],
            ) from exc

    def synthesize(self, request: SynthesisRequest) -> Path:
        self.preflight()
        import edge_tts

        text = request.text.strip()
        if not text:
            raise TTSError("합성할 텍스트가 비어 있습니다")

        voice = request.voice or self.options.get("voice") or DEFAULT_VOICE
        rate = _rate_string(request.speed)
        pitch = _pitch_string(self.options.get("pitchHz", 0))
        proxy = self._proxy()
        out_path = request.out_path.with_suffix(self.output_suffix)

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, proxy=proxy)
            await communicate.save(str(out_path))

        try:
            asyncio.run(_run())
        except Exception as exc:
            raise TTSError(
                f"edge-tts 합성 실패 (voice={voice})",
                details=[
                    f"{type(exc).__name__}: {exc}",
                    "인터넷 연결 또는 보이스 이름을 확인하세요",
                    "오프라인이면 config/tts.json engine을 'offline'으로 바꿀 수 있습니다",
                ],
            ) from exc

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise TTSError(f"edge-tts가 빈 파일을 만들었습니다: {out_path.name}")
        return out_path

    def describe(self) -> str:
        return f"edge-tts ({self.options.get('voice') or DEFAULT_VOICE})"
