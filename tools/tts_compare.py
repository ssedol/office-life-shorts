#!/usr/bin/env python3
"""같은 대본을 여러 TTS 엔진으로 뽑아 나란히 들어보는 도구.

어느 엔진이 자연스러운지는 들어봐야 안다. 매번 config를 고쳐가며 전체 파이프라인을
돌리는 대신, 음성만 뽑아 한곳에 모은다.

    # 기본: 지금 대본을 edge로만
    python tools/tts_compare.py

    # 엔진 비교
    python tools/tts_compare.py --engines edge,clova,typecast,elevenlabs

    # 대본 문체까지 같이 비교 (2x2 = 4가지)
    python tools/tts_compare.py --engines edge,clova --scripts original,spoken

    # 보이스 후보 고르기 — Voice Library에서 복사한 ID를 그대로 늘어놓는다
    python tools/tts_compare.py --engines elevenlabs \
        --voices EXAVITQu4vr4xnSDxMaL,onwK4e9ZLuTAKqWW03F9,pNInz6obpgDQGcFmaJgB

결과:

    outputs/tts-compare/
      original-edge/    scene-01.wav ... scene-08.wav, 합본.wav
      original-clova/   ...
      spoken-edge/      ...
      결과.md           길이 비교표

'합본.wav'를 들으면 전체 흐름을 한 번에 판단할 수 있다.

유료 엔진은 .env에 키가 있어야 한다(.env.example 참고).
키가 없거나 API가 실패해도 나머지 엔진은 계속 진행한다 — 하나 막혔다고
전부 다시 돌릴 이유가 없다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config  # noqa: E402
from src.errors import PipelineError  # noqa: E402
from src.media.ffmpeg import FFmpeg  # noqa: E402
from src.tts.base import SynthesisRequest  # noqa: E402
from src.tts.factory import PAID_ENGINES, REGISTRY, create_provider, resolve_settings  # noqa: E402

log = logging.getLogger("tts_compare")

#: ElevenLabs 종량제 단가 (2026-09 기준, USD per 1,000자)
_USD_PER_1K = {
    "eleven_multilingual_v2": 0.10,
    "eleven_v3": 0.10,
    "eleven_flash_v2_5": 0.05,
    "eleven_turbo_v2_5": 0.05,
}


@dataclass
class Outcome:
    script: str
    engine: str
    voice: str | None
    out_dir: Path
    durations: dict[str, float] = field(default_factory=dict)
    combined: Path | None = None
    error: str | None = None

    @property
    def total(self) -> float:
        return sum(self.durations.values())

    @property
    def ok(self) -> bool:
        return self.error is None


def _safe_name(value: str) -> str:
    """보이스 ID를 폴더 이름에 쓸 수 있게 다듬는다."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
    return cleaned[:24] or "voice"


def load_scripts(input_dir: Path, names: list[str]) -> dict[str, dict[str, str]]:
    """대본 버전별로 {씬 ID: 내레이션} 맵을 만든다."""
    plan = json.loads((input_dir / "scene-plan.json").read_text(encoding="utf-8"))
    original = {s["id"]: s["narration"] for s in plan["scenes"]}

    scripts: dict[str, dict[str, str]] = {}
    for name in names:
        if name == "original":
            scripts[name] = original
            continue
        override_path = input_dir / f"narration-{name}.json"
        if not override_path.is_file():
            raise SystemExit(
                f"대본 파일이 없습니다: {override_path}\n"
                f"사용 가능: original, " + ", ".join(
                    p.stem.removeprefix("narration-") for p in sorted(input_dir.glob("narration-*.json"))
                )
            )
        override = json.loads(override_path.read_text(encoding="utf-8")).get("narration", {})
        missing = [sid for sid in original if sid not in override]
        if missing:
            raise SystemExit(f"{override_path.name}에 빠진 씬이 있습니다: {', '.join(missing)}")
        scripts[name] = {sid: override[sid] for sid in original}
    return scripts


def synthesize_one(
    cfg,
    ffmpeg: FFmpeg,
    script_name: str,
    narrations: dict[str, str],
    engine: str,
    out_root: Path,
    voice: str | None = None,
) -> Outcome:
    """엔진 하나 × 대본 하나 × 보이스 하나를 뽑는다. 실패해도 예외를 밖으로 던지지 않는다."""
    settings = resolve_settings(cfg.tts, engine_override=engine, voice_override=voice)
    # 보이스를 여러 개 비교할 때 폴더가 겹치지 않게 이름에 보이스를 넣는다.
    suffix = f"-{_safe_name(voice)}" if voice else ""
    out_dir = out_root / f"{script_name}-{engine}{suffix}"
    outcome = Outcome(script_name, engine, settings.voice, out_dir)

    try:
        provider = create_provider(settings)
        provider.preflight()
        out_dir.mkdir(parents=True, exist_ok=True)

        normalize = settings.normalize
        if not getattr(provider, "supports_normalize", True):
            normalize = {"enabled": False}

        parts: list[Path] = []
        for index, (scene_id, text) in enumerate(narrations.items(), start=1):
            raw = provider.synthesize(SynthesisRequest(
                text=text.strip(),
                out_path=out_dir / f"raw-{index:02d}",
                voice=settings.voice,
                speed=settings.speed,
                sample_rate=settings.sample_rate,
            ))
            wav = out_dir / f"scene-{index:02d}.wav"
            ffmpeg.to_wav(raw, wav, sample_rate=settings.sample_rate,
                          channels=settings.channels, normalize=normalize)
            raw.unlink(missing_ok=True)
            outcome.durations[scene_id] = ffmpeg.duration(wav)
            parts.append(wav)
            log.info("  %s %s %.2f초", engine, scene_id, outcome.durations[scene_id])

        outcome.combined = ffmpeg.concat_audio(
            parts, out_dir / "합본.wav",
            sample_rate=settings.sample_rate, channels=settings.channels,
        )
    except PipelineError as exc:
        # 표에는 한 줄 요약만 넣고, 해결 방법은 로그로 자세히 남긴다.
        outcome.error = exc.message
        log.warning("%s (%s) 실패: %s", engine, script_name, exc.message)
        for detail in exc.details:
            log.warning("    %s", detail)
    except Exception as exc:  # 예상 못 한 오류도 다른 엔진 진행을 막지 않는다
        outcome.error = f"{type(exc).__name__}: {exc}"
        log.warning("%s (%s) 실패: %s", engine, script_name, outcome.error)
    return outcome


def estimate_cost(engine: str, model: str | None, chars: int) -> str:
    """대략적인 비용을 알려준다. 단가를 아는 엔진만."""
    rate = _USD_PER_1K.get(str(model or ""))
    if engine != "elevenlabs" or rate is None:
        return "—"
    return f"${chars / 1000 * rate:.4f}"


def write_report(outcomes: list[Outcome], scripts: dict[str, dict[str, str]],
                 cfg, out_root: Path) -> Path:
    """결과를 마크다운 표로 남긴다."""
    lines = [
        "# TTS 엔진 비교",
        "",
        "각 폴더의 `합본.wav`를 들어보고 고르세요. 씬별 파일도 같이 있습니다.",
        "",
        "## 길이",
        "",
        "| 대본 | 엔진 | 보이스 | 음성 길이 | 영상 길이(추정) | 글자수 | 1편 비용 | 상태 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    timeline = cfg.app.get("timeline", {})
    overhead = (float(timeline.get("leadInSec", 0.12)) + float(timeline.get("tailPadSec", 0.25))) * 8

    for item in outcomes:
        chars = sum(len(t) for t in scripts[item.script].values())
        model = cfg.tts.get("engines", {}).get(item.engine, {}).get("model")
        if item.ok:
            status = "OK"
            speech = f"{item.total:.2f}초"
            video = f"{item.total + overhead:.2f}초"
        else:
            status = item.error or "실패"
            speech = video = "—"
        lines.append(
            f"| {item.script} | {item.engine} | {item.voice or '기본'} | {speech} | {video} | "
            f"{chars} | {estimate_cost(item.engine, model, chars)} | {status} |"
        )

    lines += [
        "",
        f"권장 길이는 {cfg.app.get('durationRange', {}).get('minSec', 35)}~"
        f"{cfg.app.get('durationRange', {}).get('maxSec', 45)}초입니다.",
        "",
        "## 대본",
        "",
    ]
    for name, narrations in scripts.items():
        lines += [f"### {name}", ""]
        lines += [f"- **{sid}** {text}" for sid, text in narrations.items()]
        lines.append("")

    report = out_root / "결과.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="같은 대본을 여러 TTS 엔진으로 뽑아 비교한다",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", default="inputs/2026-09-18", help="입력 폴더 (scene-plan.json이 있는 곳)")
    parser.add_argument("--engines", default="edge",
                        help=f"쉼표로 구분. 사용 가능: {', '.join(sorted(set(REGISTRY)))}")
    parser.add_argument("--scripts", default="original",
                        help="쉼표로 구분. original 또는 narration-<이름>.json의 <이름>")
    parser.add_argument("--voices", default="",
                        help="쉼표로 구분한 보이스 ID/이름. 주면 보이스마다 한 벌씩 뽑는다")
    parser.add_argument("--out", default="outputs/tts-compare", help="결과 폴더")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    input_dir = (REPO_ROOT / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input)
    if not (input_dir / "scene-plan.json").is_file():
        print(f"scene-plan.json이 없습니다: {input_dir}", file=sys.stderr)
        return 2

    engines = [e.strip().lower() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in engines if e not in REGISTRY]
    if unknown:
        print(f"모르는 엔진입니다: {', '.join(unknown)}\n"
              f"사용 가능: {', '.join(sorted(set(REGISTRY)))}", file=sys.stderr)
        return 2

    script_names = [s.strip() for s in args.scripts.split(",") if s.strip()]
    scripts = load_scripts(input_dir, script_names)

    cfg = load_config()
    ffmpeg = FFmpeg(cfg.ffmpeg_bin, cfg.ffprobe_bin)
    ffmpeg.require()

    out_root = (REPO_ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    paid = [e for e in engines if e in PAID_ENGINES]
    if paid:
        chars = sum(len(t) for m in scripts.values() for t in m.values())
        log.info("유료 엔진 %s — 이번 실행에서 %d자를 합성합니다", ", ".join(paid), chars * len(paid) // len(engines))

    # --voices를 주면 보이스마다 한 벌씩 뽑는다. 안 주면 설정대로 한 벌.
    voices: list[str | None] = [v.strip() for v in args.voices.split(",") if v.strip()] or [None]

    outcomes: list[Outcome] = []
    for script_name, narrations in scripts.items():
        for engine in engines:
            for voice in voices:
                log.info("=== %s / %s%s ===", script_name, engine, f" / {voice}" if voice else "")
                outcomes.append(
                    synthesize_one(cfg, ffmpeg, script_name, narrations, engine, out_root, voice=voice)
                )

    report = write_report(outcomes, scripts, cfg, out_root)

    print()
    ok = [o for o in outcomes if o.ok]
    for item in ok:
        print(f"  {item.out_dir.name}: {item.total:.2f}초 → {item.combined}")
    for item in (o for o in outcomes if not o.ok):
        print(f"  {item.out_dir.name}: 실패 — {item.error}")
    print(f"\n비교표: {report}")
    if ok:
        print("각 폴더의 '합본.wav'를 들어보고 고르세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
