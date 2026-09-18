"""render-log.json 기록 (명세서 §22).

기록 항목:
    시작/종료 시간, 씬별 처리 상태, I2V fallback 여부,
    TTS 성공/실패, 자막 성공/실패, 렌더 성공/실패, 전체 소요 시간

실패했을 때도 어디까지 진행됐는지 남아야 하므로, 파이프라인은 예외 발생 시에도
반드시 save()를 호출한다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_PENDING = "pending"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class RenderLog:
    path: Path
    input_dir: str = ""
    mode: str = "preview"
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None
    _monotonic_start: float = field(default_factory=time.monotonic, repr=False)

    project: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=lambda: {"status": STATUS_PENDING})
    i2v: dict[str, str] = field(default_factory=dict)
    tts: str = STATUS_PENDING
    subtitle: str = STATUS_PENDING
    render: str = STATUS_PENDING

    scenes: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    # ---- 기록 ---------------------------------------------------------------
    def set_stage(self, stage: str, status: str, **extra: Any) -> None:
        if stage in ("tts", "subtitle", "render"):
            setattr(self, stage, status)
        else:
            self.details.setdefault(stage, {})["status"] = status
        if extra:
            self.details.setdefault(stage, {}).update(extra)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def add_warnings(self, messages: list[str]) -> None:
        for message in messages:
            self.add_warning(message)

    def add_error(self, code: str, message: str) -> None:
        self.errors.append({"code": code, "message": message})

    def set_scenes(self, timeline) -> None:
        """타임라인 상태를 씬별 로그로 옮긴다."""
        self.scenes = [
            {
                "id": item.scene.id,
                "order": item.scene.order,
                "plannedType": item.scene.type,
                "processedAs": item.source,
                "fallback": item.is_fallback,
                "motion": item.scene.effective_motion if item.source != "i2v" else None,
                "startSec": round(item.start, 3),
                "durationSec": round(item.duration, 3),
                "plannedDurationSec": round(item.scene.duration_sec, 3),
                "audioDurationSec": round(item.audio_duration, 3),
                "clip": item.clip_path.name if item.clip_path else None,
                "notes": list(item.notes),
            }
            for item in timeline.scenes
        ]

    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self._monotonic_start

    # ---- 출력 ---------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.project.get("channel"),
            "date": self.project.get("date"),
            "title": self.project.get("title"),
            "inputDir": self.input_dir,
            "mode": self.mode,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at or _now_iso(),
            "elapsedSec": round(self.elapsed_sec, 2),
            "validation": self.validation,
            "i2v": self.i2v,
            "tts": self.tts,
            "subtitle": self.subtitle,
            "render": self.render,
            "scenes": self.scenes,
            "outputs": self.outputs,
            "warnings": self.warnings,
            "errors": self.errors,
            "details": self.details,
        }

    def save(self) -> Path:
        self.finished_at = _now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log.debug("render-log.json 저장: %s", self.path)
        return self.path
