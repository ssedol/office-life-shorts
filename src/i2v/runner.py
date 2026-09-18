"""I2V 실행과 fallback (명세서 §16).

    I2V 실패
    → 원본 이미지를 STILL로 사용
    → slow_zoom_in 기본 적용
    → render-log.json에 기록

I2V 실패는 전체 실패가 아니다(명세서 §33-5). 예외를 밖으로 던지지 않고
타임라인의 source를 i2v_fallback_still로 바꾸고 계속 진행한다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import AppConfig
from ..errors import I2VError
from ..scene.timeline import SOURCE_I2V, SOURCE_I2V_FALLBACK, Timeline
from .base import I2VProvider, I2VRequest
from .comfy_ltx import ComfyUILTXProvider

log = logging.getLogger(__name__)

PROVIDERS: dict[str, type[I2VProvider]] = {
    "comfyui": ComfyUILTXProvider,
    "comfyui-ltx25": ComfyUILTXProvider,
}

STATUS_SUCCESS = "success"
STATUS_FALLBACK = "fallback_still"
STATUS_SKIPPED = "skipped"


@dataclass
class I2VOutcome:
    scene_id: str
    status: str
    message: str = ""
    seed: int | None = None
    path: Path | None = None


@dataclass
class I2VReport:
    outcomes: list[I2VOutcome] = field(default_factory=list)

    def as_log_map(self) -> dict[str, str]:
        """명세서 §22 render-log.json의 i2v 블록 형식."""
        return {item.scene_id: item.status for item in self.outcomes}

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.outcomes if item.status == STATUS_SUCCESS)

    @property
    def fallback_count(self) -> int:
        return sum(1 for item in self.outcomes if item.status == STATUS_FALLBACK)


def create_provider(cfg: AppConfig) -> I2VProvider:
    name = str(cfg.i2v.get("provider", "comfyui")).lower()
    if name not in PROVIDERS:
        raise I2VError(
            f"알 수 없는 I2V provider입니다: {name}",
            details=[f"사용 가능: {', '.join(sorted(set(PROVIDERS)))}"],
        )
    return PROVIDERS[name](cfg.i2v, cfg.repo_root)


def run_i2v(
    timeline: Timeline,
    cfg: AppConfig,
    work_dir: Path,
    *,
    skip: bool = False,
    provider: I2VProvider | None = None,
) -> I2VReport:
    """타임라인의 I2V 씬을 처리한다. 실패한 씬은 STILL fallback으로 표시한다."""
    report = I2VReport()
    i2v_items = [item for item in timeline.scenes if item.scene.is_i2v]
    if not i2v_items:
        return report

    fallback_cfg = cfg.i2v.get("fallback", {})
    fallback_motion = str(fallback_cfg.get("motion", "slow_zoom_in"))
    fallback_enabled = bool(fallback_cfg.get("enabled", True))

    def to_fallback(item, message: str) -> None:
        if not fallback_enabled:
            raise I2VError(f"{item.scene.id}: I2V 실패 (fallback 비활성화)", details=[message])
        item.source = SOURCE_I2V_FALLBACK
        item.scene.motion = fallback_motion
        item.notes.append(f"I2V fallback: {message}")
        report.outcomes.append(I2VOutcome(item.scene.id, STATUS_FALLBACK, message))
        log.warning("%s: I2V 실패 → STILL(%s)로 대체합니다. %s", item.scene.id, fallback_motion, message)

    if skip or not cfg.i2v.get("enabled", True):
        reason = "--skip-i2v 옵션" if skip else "config/i2v.json enabled=false"
        for item in i2v_items:
            item.source = SOURCE_I2V_FALLBACK
            item.scene.motion = fallback_motion
            item.notes.append(f"I2V 건너뜀: {reason}")
            report.outcomes.append(I2VOutcome(item.scene.id, STATUS_SKIPPED, reason))
        log.info("I2V %d개 씬을 건너뜁니다 (%s)", len(i2v_items), reason)
        return report

    try:
        provider = provider or create_provider(cfg)
        provider.preflight()
    except I2VError as exc:
        for item in i2v_items:
            to_fallback(item, str(exc))
        return report

    work_dir.mkdir(parents=True, exist_ok=True)
    defaults = cfg.i2v.get("defaults", {})
    min_sec = float(defaults.get("minSec", 3.0))
    max_sec = float(defaults.get("maxSec", 5.0))
    attempts = max(1, int(cfg.i2v.get("retry", {}).get("attempts", 1)))
    backoff = float(cfg.i2v.get("retry", {}).get("backoffSec", 3.0))

    for item in i2v_items:
        scene = item.scene
        # 명세서 §16: 생성 길이는 3~5초. 씬이 더 길면 렌더 단계에서 마지막 프레임을 늘려 채운다.
        duration = min(max(item.duration, min_sec), max_sec)

        request = I2VRequest(
            scene_id=scene.id,
            image_path=scene.image_path,
            video_prompt=scene.video_prompt or "",
            out_path=work_dir / f"{scene.id.lower().replace('scene-', 'scene-')}.mp4",
            width=cfg.width,
            height=cfg.height,
            fps=timeline.fps,
            duration_sec=duration,
            seed=scene.seed,
            negative_prompt=str(defaults.get("negativePrompt", "")),
        )

        error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = provider.generate(request)
                item.source = SOURCE_I2V
                item.i2v_raw_path = result.path
                report.outcomes.append(
                    I2VOutcome(scene.id, STATUS_SUCCESS, seed=result.seed, path=result.path)
                )
                log.info("%s: I2V 생성 성공 (%s)", scene.id, result.path.name)
                error = None
                break
            except I2VError as exc:
                error = exc
                if attempt < attempts:
                    wait = backoff * attempt
                    log.warning("%s: I2V 실패 (%d/%d). %.1f초 후 재시도합니다", scene.id, attempt, attempts, wait)
                    time.sleep(wait)

        if error is not None:
            to_fallback(item, str(error))

    return report
