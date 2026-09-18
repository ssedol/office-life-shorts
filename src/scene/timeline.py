"""타임라인 구성 (명세서 §3.1, §31 RISK-3).

씬 길이는 scene-plan.json의 durationSec를 하한으로 삼되,
실제 TTS 길이가 그보다 길면 TTS 쪽에 맞춘다. 그래야 음성이 잘리지 않고
씬/자막/음성 싱크가 어긋나지 않는다.

    scene_duration = max(durationSec, leadIn + ttsLength + tailPad, minSceneSec)

계산된 길이는 항상 프레임 경계로 올림해서 concat 시 드리프트가 생기지 않게 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from ..config import AppConfig
from ..tts.narration import SceneAudio
from .models import Scene

SOURCE_STILL = "still"
SOURCE_I2V = "i2v"
SOURCE_I2V_FALLBACK = "i2v_fallback_still"


@dataclass
class TimelineScene:
    scene: Scene
    index: int
    start: float
    duration: float
    lead_in: float
    audio_duration: float
    source: str
    #: I2V 성공 시 생성된 원본 mp4
    i2v_raw_path: Path | None = None
    #: 렌더러가 만든 정규화 클립
    clip_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def subtitle_start(self) -> float:
        return self.start + self.lead_in

    @property
    def subtitle_end(self) -> float:
        if self.audio_duration > 0:
            return min(self.start + self.lead_in + self.audio_duration, self.end)
        return self.end

    @property
    def is_fallback(self) -> bool:
        return self.source == SOURCE_I2V_FALLBACK


@dataclass
class Timeline:
    scenes: list[TimelineScene]
    fps: int
    warnings: list[str] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(s.duration for s in self.scenes)

    @property
    def durations(self) -> list[float]:
        return [s.duration for s in self.scenes]

    @property
    def lead_ins(self) -> list[float]:
        return [s.lead_in for s in self.scenes]

    def to_dict(self) -> dict:
        return {
            "fps": self.fps,
            "totalDurationSec": round(self.total_duration, 3),
            "scenes": [
                {
                    "id": s.scene.id,
                    "order": s.scene.order,
                    "type": s.scene.type,
                    "source": s.source,
                    "startSec": round(s.start, 3),
                    "endSec": round(s.end, 3),
                    "durationSec": round(s.duration, 3),
                    "plannedDurationSec": round(s.scene.duration_sec, 3),
                    "audioDurationSec": round(s.audio_duration, 3),
                }
                for s in self.scenes
            ],
        }


def quantize(seconds: float, fps: int) -> float:
    """프레임 경계로 올림한다."""
    frames = max(1, math.ceil(seconds * fps - 1e-6))
    return frames / fps


def frames_for(seconds: float, fps: int) -> int:
    return max(1, int(round(seconds * fps)))


def build_timeline(
    scenes: list[Scene],
    scene_audios: list[SceneAudio],
    cfg: AppConfig,
    *,
    fps: int | None = None,
) -> Timeline:
    """씬 목록과 TTS 길이로 타임라인을 만든다."""
    if len(scenes) != len(scene_audios):
        raise ValueError("씬 개수와 오디오 개수가 일치하지 않습니다")

    timeline_cfg = cfg.app.get("timeline", {})
    lead_in_cfg = float(timeline_cfg.get("leadInSec", 0.15))
    tail_pad = float(timeline_cfg.get("tailPadSec", 0.35))
    min_scene = float(timeline_cfg.get("minSceneSec", 1.0))
    effective_fps = int(fps or cfg.fps)

    items: list[TimelineScene] = []
    warnings: list[str] = []
    cursor = 0.0

    for index, (scene, audio) in enumerate(zip(scenes, scene_audios, strict=True)):
        lead_in = lead_in_cfg if audio.duration > 0 else 0.0
        needed = lead_in + audio.duration + tail_pad if audio.duration > 0 else min_scene
        duration = quantize(max(scene.duration_sec, needed, min_scene), effective_fps)

        item = TimelineScene(
            scene=scene,
            index=index,
            start=cursor,
            duration=duration,
            lead_in=lead_in,
            audio_duration=audio.duration,
            source=SOURCE_I2V if scene.is_i2v else SOURCE_STILL,
        )

        if duration > scene.duration_sec + 1e-3:
            note = (
                f"{scene.id}: 계획 {scene.duration_sec:.2f}초 → 실제 {duration:.2f}초 "
                f"(TTS {audio.duration:.2f}초에 맞춰 확장)"
            )
            item.notes.append(note)
            warnings.append(note)

        items.append(item)
        cursor += duration

    total = cursor
    duration_range = cfg.app.get("durationRange", {})
    lo = float(duration_range.get("minSec", 35))
    hi = float(duration_range.get("maxSec", 45))
    if total < lo or total > hi:
        warnings.append(
            f"전체 길이 {total:.2f}초가 권장 범위({lo}~{hi}초)를 벗어납니다. "
            "scene-plan.json의 durationSec 또는 narration 분량을 조정하세요"
        )

    return Timeline(scenes=items, fps=effective_fps, warnings=warnings)
