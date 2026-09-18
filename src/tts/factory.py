"""TTS Provider 팩토리 (명세서 §18 — Provider 교체 가능 구조)."""

from __future__ import annotations

from ..errors import TTSError
from ..scene.models import TTSSettings
from .base import TTSProvider
from .edge_adapter import EdgeTTSAdapter
from .local_cli_adapter import LocalCliAdapter, SupertonicAdapter
from .offline_adapter import OfflineAdapter

#: engine 이름 → Provider 클래스
REGISTRY: dict[str, type[TTSProvider]] = {
    "edge": EdgeTTSAdapter,
    "edge-tts": EdgeTTSAdapter,
    "supertonic": SupertonicAdapter,
    "cli": LocalCliAdapter,
    "offline": OfflineAdapter,
}


class ResolvedTTSSettings:
    """config/tts.json + project.json + CLI를 합친 최종 TTS 설정."""

    def __init__(self, engine: str, voice: str | None, speed: float, options: dict, base: dict):
        self.engine = engine
        self.voice = voice
        self.speed = speed
        self.options = options
        self.base = base

    @property
    def sample_rate(self) -> int:
        return int(self.base.get("sampleRate", 48000))

    @property
    def channels(self) -> int:
        return int(self.base.get("channels", 1))

    @property
    def normalize(self) -> dict:
        return dict(self.base.get("normalize", {"enabled": True}))

    @property
    def retry_attempts(self) -> int:
        return max(1, int(self.base.get("retry", {}).get("attempts", 1)))

    @property
    def retry_backoff(self) -> float:
        return float(self.base.get("retry", {}).get("backoffSec", 2.0))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TTS engine={self.engine} voice={self.voice} speed={self.speed}>"


def resolve_settings(
    tts_config: dict,
    project_tts: TTSSettings | None = None,
    *,
    engine_override: str | None = None,
    voice_override: str | None = None,
) -> ResolvedTTSSettings:
    """우선순위: CLI > project.json > config/tts.json."""
    project_tts = project_tts or TTSSettings()

    engine = (engine_override or project_tts.engine or tts_config.get("engine") or "edge").strip().lower()
    if engine not in REGISTRY:
        raise TTSError(
            f"알 수 없는 TTS 엔진입니다: {engine}",
            details=[f"사용 가능: {', '.join(sorted(set(REGISTRY)))}"],
        )

    options = dict(tts_config.get("engines", {}).get(engine, {}))
    # 'UNDECIDED'는 명세서 §11 예시의 자리표시자다(§35-2 미확정). 해당 출처만 건너뛰고
    # 다음 우선순위로 넘어가야지, 전체 체인을 None으로 만들면 안 된다.
    voice = _first_voice(voice_override, project_tts.voice, options.get("voice"), tts_config.get("voice"))

    speed = project_tts.speed if project_tts.speed is not None else tts_config.get("speed", 1.0)
    speed = float(speed)
    if not (0.5 <= speed <= 2.0):
        raise TTSError(f"tts.speed는 0.5~2.0 범위여야 합니다 (현재 {speed})")

    return ResolvedTTSSettings(engine, voice, speed, options, tts_config)


def _first_voice(*candidates: str | None) -> str | None:
    """우선순위대로 훑어 실제로 쓸 수 있는 보이스 이름을 고른다."""
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate).strip()
        if not text or text.upper() == "UNDECIDED":
            continue
        return text
    return None


def create_provider(settings: ResolvedTTSSettings) -> TTSProvider:
    return REGISTRY[settings.engine](settings.options)
