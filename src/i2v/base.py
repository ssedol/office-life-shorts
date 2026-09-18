"""I2V Provider 인터페이스 (명세서 §16, §17).

로컬 시스템은 STILL/I2V를 재판단하지 않는다(명세서 §33-2).
여기서는 "이미 I2V로 정해진 씬"을 영상으로 만드는 일만 한다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path


@dataclass
class I2VRequest:
    scene_id: str
    image_path: Path
    video_prompt: str
    out_path: Path
    width: int
    height: int
    fps: int
    duration_sec: float
    seed: int | None = None
    negative_prompt: str = ""

    @property
    def frame_count(self) -> int:
        return max(1, int(round(self.duration_sec * self.fps)))


@dataclass
class I2VResult:
    scene_id: str
    path: Path
    duration_sec: float
    seed: int | None
    provider: str


class I2VProvider(abc.ABC):
    """모든 I2V 백엔드가 구현해야 하는 인터페이스."""

    name = "base"

    def __init__(self, config: dict, repo_root: Path):
        self.config = config
        self.repo_root = repo_root

    @abc.abstractmethod
    def generate(self, request: I2VRequest) -> I2VResult:
        """이미지 + 프롬프트 → 영상 파일. 실패하면 src.errors.I2VError를 던진다."""

    def preflight(self) -> None:
        return None

    def describe(self) -> str:
        return self.name
