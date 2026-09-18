"""FEAT-4 내레이션 생성 (명세서 §18).

2단계로 나뉜다.

1) synthesize_scenes()  — 씬별로 합성해 표준 WAV로 만들고 실제 길이를 잰다.
   이 길이가 타임라인의 기준이 된다(명세서 §31 RISK-3 대응).
2) build_narration()    — 타임라인이 확정된 뒤 씬 오디오를 패딩해 narration.wav로 합친다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ..errors import TTSError
from ..media.ffmpeg import FFmpeg
from ..scene.models import Scene
from .base import SynthesisRequest, TTSProvider
from .factory import ResolvedTTSSettings

log = logging.getLogger(__name__)


@dataclass
class SceneAudio:
    scene_id: str
    index: int
    path: Path | None
    duration: float

    @property
    def is_silent(self) -> bool:
        return self.path is None


def synthesize_scenes(
    scenes: list[Scene],
    provider: TTSProvider,
    settings: ResolvedTTSSettings,
    ffmpeg: FFmpeg,
    work_dir: Path,
) -> list[SceneAudio]:
    """씬별 내레이션을 합성한다. 하나라도 실패하면 TTSError로 중단한다(명세서 §25)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    provider.preflight()

    normalize = settings.normalize
    if not getattr(provider, "supports_normalize", True):
        normalize = {"enabled": False}

    results: list[SceneAudio] = []
    for index, scene in enumerate(scenes):
        text = scene.narration.strip()
        if not text:
            log.warning("%s: narration이 비어 있어 무음으로 처리합니다", scene.id)
            results.append(SceneAudio(scene.id, index, None, 0.0))
            continue

        raw_path = work_dir / f"{index + 1:02d}-raw"
        wav_path = work_dir / f"{index + 1:02d}-narration.wav"

        produced = _synthesize_with_retry(
            provider,
            SynthesisRequest(
                text=text,
                out_path=raw_path,
                voice=settings.voice,
                speed=settings.speed,
                sample_rate=settings.sample_rate,
            ),
            attempts=settings.retry_attempts,
            backoff=settings.retry_backoff,
            label=scene.id,
        )

        ffmpeg.to_wav(
            produced,
            wav_path,
            sample_rate=settings.sample_rate,
            channels=settings.channels,
            normalize=normalize,
        )
        duration = ffmpeg.duration(wav_path)
        if duration <= 0:
            raise TTSError(
                f"{scene.id}: 생성된 음성 길이가 0입니다",
                details=[str(wav_path), f"엔진: {provider.describe()}"],
            )

        log.info("%s TTS %.2f초 (%s)", scene.id, duration, provider.name)
        results.append(SceneAudio(scene.id, index, wav_path, duration))

    if all(item.is_silent for item in results):
        raise TTSError(
            "모든 씬의 narration이 비어 있어 음성을 만들 수 없습니다",
            details=["scene-plan.json의 narration 필드를 확인하세요"],
        )
    return results


def _synthesize_with_retry(
    provider: TTSProvider,
    request: SynthesisRequest,
    *,
    attempts: int,
    backoff: float,
    label: str,
) -> Path:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return provider.synthesize(request)
        except TTSError as exc:
            last = exc
            if attempt < attempts:
                wait = backoff * (2 ** (attempt - 1))
                log.warning("%s TTS 실패 (%d/%d). %.1f초 후 재시도합니다", label, attempt, attempts, wait)
                time.sleep(wait)
    assert last is not None
    raise TTSError(
        f"{label}: TTS 합성을 {attempts}회 시도했지만 실패했습니다",
        details=[str(last)],
    )


def build_narration(
    scene_audios: list[SceneAudio],
    durations: list[float],
    lead_ins: list[float],
    out_path: Path,
    ffmpeg: FFmpeg,
    settings: ResolvedTTSSettings,
    work_dir: Path,
) -> Path:
    """씬별 오디오를 씬 길이에 맞춰 패딩하고 하나로 이어 narration.wav를 만든다."""
    if not (len(scene_audios) == len(durations) == len(lead_ins)):
        raise TTSError("오디오/길이/리드인 개수가 일치하지 않습니다")

    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    parts: list[Path] = []
    for audio, duration, lead_in in zip(scene_audios, durations, lead_ins, strict=True):
        part = work_dir / f"{audio.index + 1:02d}-padded.wav"
        if audio.is_silent:
            ffmpeg.silence(
                part,
                duration,
                sample_rate=settings.sample_rate,
                channels=settings.channels,
            )
        else:
            ffmpeg.pad_to_duration(
                audio.path,
                part,
                total_seconds=duration,
                lead_in=lead_in,
                sample_rate=settings.sample_rate,
                channels=settings.channels,
            )
        parts.append(part)

    ffmpeg.concat_audio(parts, out_path, sample_rate=settings.sample_rate, channels=settings.channels)

    total = ffmpeg.duration(out_path)
    if total <= 0:
        raise TTSError(f"narration.wav 길이가 0입니다: {out_path}")
    log.info("narration.wav 생성 완료 (%.2f초)", total)
    return out_path
