"""TTSProvider 인터페이스 (명세서 §18).

    TTSProvider
    ├─ EdgeTTSAdapter        (기본, 무료 한국어)
    ├─ SupertonicAdapter     (명세서 §18 초기 후보 — 로컬 엔진)
    └─ OfflineAdapter        (네트워크 없는 환경/테스트용 무음 생성)

Provider는 "텍스트 → 오디오 파일 1개"만 책임진다.
WAV 변환·음량 정규화·길이 패딩은 narration.py가 공통으로 처리하므로
새 Provider를 추가할 때 중복 구현할 필요가 없다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SynthesisRequest:
    text: str
    out_path: Path
    """Provider가 써야 할 출력 경로(확장자 포함). Provider는 다른 확장자를 쓰면 실제 경로를 반환한다."""
    voice: str | None = None
    speed: float = 1.0
    sample_rate: int = 48000


class TTSProvider(abc.ABC):
    """모든 TTS 엔진이 구현해야 하는 인터페이스."""

    name = "base"
    #: Provider가 내놓는 파일 확장자 (narration.py가 WAV로 변환한다)
    output_suffix = ".wav"

    def __init__(self, options: dict | None = None):
        self.options = options or {}

    @abc.abstractmethod
    def synthesize(self, request: SynthesisRequest) -> Path:
        """텍스트를 합성해 오디오 파일을 만들고 실제 경로를 돌려준다.

        실패하면 src.errors.TTSError를 던진다.
        """

    def preflight(self) -> None:
        """실행 전 사용 가능 여부를 확인한다. 기본은 아무것도 하지 않는다."""
        return None

    def describe(self) -> str:
        return self.name
