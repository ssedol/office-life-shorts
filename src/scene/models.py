"""입력 패키지 데이터 모델 (명세서 §11, §12).

여기 정의된 값은 ChatGPT가 만든 scene-plan.json을 그대로 옮긴 것이다.
명세서 §33-2/§33-4에 따라 로컬에서 STILL/I2V를 재판단하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCENE_TYPE_STILL = "STILL"
SCENE_TYPE_I2V = "I2V"
SCENE_TYPES = (SCENE_TYPE_STILL, SCENE_TYPE_I2V)

# 명세서 §15 지원 모션
MOTIONS = ("static", "slow_zoom_in", "slow_zoom_out", "slow_pan_left", "slow_pan_right")
DEFAULT_MOTION = "slow_zoom_in"


@dataclass
class Resolution:
    width: int
    height: int

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Resolution | None:
        if not data:
            return None
        return cls(width=int(data["width"]), height=int(data["height"]))


@dataclass
class TTSSettings:
    engine: str | None = None
    voice: str | None = None
    speed: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TTSSettings:
        data = data or {}
        voice = data.get("voice")
        # 명세서 §11 예시의 자리표시자. 값이 확정되기 전까지는 config 기본값을 쓴다.
        if isinstance(voice, str) and voice.strip().upper() == "UNDECIDED":
            voice = None
        speed = data.get("speed")
        return cls(
            engine=data.get("engine") or None,
            voice=voice,
            speed=float(speed) if speed is not None else None,
        )


@dataclass
class Project:
    """project.json (명세서 §11)."""

    channel: str
    date: str
    topic: str
    title: str
    duration_target_sec: float
    scene_count: int
    resolution: Resolution | None
    fps: int | None
    tts: TTSSettings
    render_mode: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        return cls(
            channel=str(data.get("channel", "")),
            date=str(data.get("date", "")),
            topic=str(data.get("topic", "")),
            title=str(data.get("title", "")),
            duration_target_sec=float(data.get("durationTargetSec", 40)),
            scene_count=int(data.get("sceneCount", 8)),
            resolution=Resolution.from_dict(data.get("resolution")),
            fps=int(data["fps"]) if data.get("fps") is not None else None,
            tts=TTSSettings.from_dict(data.get("tts")),
            render_mode=data.get("renderMode"),
            raw=data,
        )


@dataclass
class Scene:
    """scene-plan.json의 씬 1개 (명세서 §12)."""

    id: str
    order: int
    duration_sec: float
    type: str
    reason: str
    image_file: str
    narration: str
    subtitle: str
    motion: str | None = None
    video_prompt: str | None = None
    seed: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # 로더가 채워주는 절대 경로
    image_path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scene:
        return cls(
            id=str(data.get("id", "")),
            order=int(data.get("order", 0)),
            duration_sec=float(data.get("durationSec", 0)),
            type=str(data.get("type", "")).strip().upper(),
            reason=str(data.get("reason", "")),
            image_file=str(data.get("imageFile", "")),
            narration=str(data.get("narration", "")),
            subtitle=str(data.get("subtitle", "")),
            motion=data.get("motion"),
            video_prompt=data.get("videoPrompt"),
            seed=int(data["seed"]) if data.get("seed") is not None else None,
            raw=data,
        )

    @property
    def is_i2v(self) -> bool:
        return self.type == SCENE_TYPE_I2V

    @property
    def effective_motion(self) -> str:
        """STILL 렌더에 실제로 적용할 모션. 미지정이면 기본값."""
        if self.motion and self.motion in MOTIONS:
            return self.motion
        return DEFAULT_MOTION


@dataclass
class InputPackage:
    """inputs/YYYY-MM-DD/ 한 벌 (명세서 §10)."""

    root: Path
    project: Project
    scenes: list[Scene]
    script: str
    project_raw: dict[str, Any]
    scene_plan_raw: dict[str, Any]

    @property
    def date(self) -> str:
        return self.project.date or self.root.name
