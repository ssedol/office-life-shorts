"""Renderer 인터페이스 (명세서 §20 — 렌더러 교체 가능 구조).

    Renderer
    └─ FFmpegRenderer   (현재 구현. 명세서 §35-1에서 FFmpeg로 확정)

Remotion 등 다른 렌더러를 붙이려면 이 인터페이스만 구현하면 된다.
타임라인/자막/내레이션은 렌더러와 무관하게 이미 만들어져 있으므로,
새 렌더러는 "RenderJob → mp4 한 개"만 책임지면 된다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path

from ..scene.timeline import Timeline

MODE_PREVIEW = "preview"
MODE_FINAL = "final"
MODES = (MODE_PREVIEW, MODE_FINAL)


@dataclass
class RenderJob:
    timeline: Timeline
    narration_path: Path
    subtitle_path: Path
    out_path: Path
    scenes_dir: Path
    work_dir: Path
    mode: str
    render_cfg: dict
    subtitle_cfg: dict


@dataclass
class RenderResult:
    path: Path
    mode: str
    width: int
    height: int
    fps: int
    duration_sec: float
    scene_clips: list[Path] = field(default_factory=list)


class Renderer(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def render(self, job: RenderJob) -> RenderResult:
        """타임라인을 최종 mp4로 렌더한다. 실패하면 src.errors.RenderError를 던진다."""

    def describe(self) -> str:
        return self.name
