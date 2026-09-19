"""파이프라인 오케스트레이션 (명세서 §3.1).

    입력 검증 → STILL/I2V 분기 → I2V 대상 씬 LTX 2.5 → TTS → 자막
    → 타임라인 구성 → Preview 렌더 → 사람 검수 → Final 렌더

실제 실행 순서는 위 흐름과 한 군데 다르다. 타임라인이 TTS 실제 길이에 의존하므로
(명세서 §31 RISK-3) TTS를 먼저 돌리고 타임라인을 확정한 뒤 I2V에 길이를 넘긴다.
입력이 같으면 결과도 같으므로 명세서의 논리적 순서와 어긋나지 않는다.

오류 정책(명세서 §25):
    I2V 실패      → fallback 후 계속
    TTS 실패      → 중단
    자막 실패     → 중단
    최종 렌더 실패 → 중단
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig, deep_merge
from .errors import PipelineError, RenderError
from .i2v.runner import run_i2v
from .loader.input_loader import load_input_package
from .logger.render_log import STATUS_FAILED, STATUS_SUCCESS, RenderLog
from .media.ffmpeg import FFmpeg
from .render.base import MODE_FINAL, MODE_PREVIEW, RenderJob
from .render.ffmpeg_renderer import FFmpegRenderer
from .scene.models import InputPackage
from .scene.timeline import build_timeline
from .subtitle.builder import build_subtitles
from .tts.factory import create_provider, resolve_settings
from .tts.narration import build_narration, synthesize_scenes
from .validator.input_validator import validate, validate_or_raise

log = logging.getLogger(__name__)


@dataclass
class RunOptions:
    input_dir: Path
    mode: str = MODE_PREVIEW
    skip_i2v: bool = False
    force: bool = False
    validate_only: bool = False
    tts_engine: str | None = None
    tts_voice: str | None = None
    output_dir: Path | None = None
    keep_work: bool = False


@dataclass
class RunResult:
    output_path: Path | None
    log_path: Path
    out_dir: Path
    package: InputPackage | None = None
    warnings: list[str] = field(default_factory=list)


def _apply_project_overrides(cfg: AppConfig, package: InputPackage) -> AppConfig:
    """project.json의 resolution/fps를 config 위에 덮어쓴다."""
    override: dict = {}
    if package.project.resolution:
        override["resolution"] = {
            "width": package.project.resolution.width,
            "height": package.project.resolution.height,
        }
    if package.project.fps:
        override["fps"] = package.project.fps
    if override:
        cfg.render = deep_merge(cfg.render, override)
    return cfg


def _resolve_out_dir(cfg: AppConfig, package: InputPackage, options: RunOptions) -> Path:
    if options.output_dir:
        return Path(options.output_dir).expanduser().resolve()
    base = cfg.resolve(cfg.app.get("paths", {}).get("outputsDir", "outputs"))
    assert base is not None
    return (base / package.date).resolve()


def run(cfg: AppConfig, options: RunOptions) -> RunResult:
    """입력 폴더 하나를 받아 영상 1편을 만든다."""
    ffmpeg = FFmpeg(cfg.ffmpeg_bin, cfg.ffprobe_bin, str(cfg.app.get("ffmpeg", {}).get("logLevel", "error")))

    # ---- 1. 로딩 + 검증 (FEAT-1) -------------------------------------------
    package = load_input_package(options.input_dir)
    cfg = _apply_project_overrides(cfg, package)
    out_dir = _resolve_out_dir(cfg, package, options)
    out_dir.mkdir(parents=True, exist_ok=True)

    render_log = RenderLog(path=out_dir / "render-log.json", input_dir=str(package.root), mode=options.mode)
    render_log.project = {
        "channel": package.project.channel,
        "date": package.project.date,
        "topic": package.project.topic,
        "title": package.project.title,
    }

    try:
        report = validate(package, cfg)
        render_log.validation = {
            "status": STATUS_SUCCESS if report.ok else STATUS_FAILED,
            "errors": report.error_messages(),
            "warnings": report.warnings,
        }
        render_log.add_warnings(report.warnings)
        for message in report.warnings:
            log.warning("%s", message)

        validate_or_raise(package, cfg)
        log.info("입력 검증 통과: %d개 씬", len(package.scenes))

        if options.validate_only:
            render_log.set_stage("render", "skipped")
            return RunResult(None, render_log.save(), out_dir, package, report.warnings)

        ffmpeg.require()
        _check_existing_output(out_dir, options)

        work_dir = out_dir / ".work"
        work_dir.mkdir(parents=True, exist_ok=True)

        # ---- 2. TTS (FEAT-4) -----------------------------------------------
        tts_settings = resolve_settings(
            cfg.tts,
            package.project.tts,
            engine_override=options.tts_engine,
            voice_override=options.tts_voice,
        )
        provider = create_provider(tts_settings)
        log.info("TTS 엔진: %s", provider.describe())

        scene_audios = synthesize_scenes(package.scenes, provider, tts_settings, ffmpeg, work_dir / "tts")
        render_log.set_stage(
            "tts",
            STATUS_SUCCESS,
            engine=tts_settings.engine,
            voice=tts_settings.voice,
            speed=tts_settings.speed,
            sceneDurations={a.scene_id: round(a.duration, 3) for a in scene_audios},
        )

        # ---- 3. 타임라인 ----------------------------------------------------
        timeline = build_timeline(package.scenes, scene_audios, cfg)
        render_log.add_warnings(timeline.warnings)
        for message in timeline.warnings:
            log.warning("%s", message)
        log.info("타임라인 구성 완료: 총 %.2f초", timeline.total_duration)

        # ---- 4. I2V (FEAT-3) ------------------------------------------------
        i2v_report = run_i2v(timeline, cfg, work_dir / "i2v", skip=options.skip_i2v)
        render_log.i2v = i2v_report.as_log_map()
        if i2v_report.outcomes:
            log.info("I2V: 성공 %d / fallback %d", i2v_report.success_count, i2v_report.fallback_count)
        for outcome in i2v_report.outcomes:
            if outcome.status != "success" and outcome.message:
                render_log.add_warning(f"{outcome.scene_id}: {outcome.message}")

        # ---- 5. 내레이션 합치기 ---------------------------------------------
        narration_path = build_narration(
            scene_audios,
            timeline.durations,
            timeline.lead_ins,
            out_dir / "narration.wav",
            ffmpeg,
            tts_settings,
            work_dir / "tts",
        )

        # ---- 6. 자막 (FEAT-5) ------------------------------------------------
        subtitle_result = build_subtitles(
            timeline,
            out_dir,
            cfg.subtitle,
            width=cfg.width,
            height=cfg.height,
            fps=cfg.fps,
        )
        render_log.set_stage("subtitle", STATUS_SUCCESS, cues=len(subtitle_result.cues))
        render_log.add_warnings(subtitle_result.warnings)

        # ---- 7. 렌더 (FEAT-6) ------------------------------------------------
        render_cfg = cfg.render_profile(options.mode)
        renderer = FFmpegRenderer(ffmpeg)
        job = RenderJob(
            timeline=timeline,
            narration_path=narration_path,
            subtitle_path=subtitle_result.ass_path,
            out_path=out_dir / f"{options.mode}.mp4",
            scenes_dir=out_dir / "scenes",
            work_dir=work_dir / "render",
            mode=options.mode,
            render_cfg=render_cfg,
            # 자막 생성 단계에서 폰트가 확정된 설정을 쓴다. 그래야 ASS의 폰트 이름과
            # libass에 넘기는 fontsdir가 같은 파일을 가리킨다.
            subtitle_cfg=subtitle_result.resolved_cfg or cfg.subtitle,
        )
        result = renderer.render(job)

        render_log.set_scenes(timeline)
        render_log.set_stage(
            "render",
            STATUS_SUCCESS,
            renderer=renderer.name,
            durationSec=round(result.duration_sec, 3),
            resolution=f"{result.width}x{result.height}",
            fps=result.fps,
            crf=render_cfg.get("crf"),
            preset=render_cfg.get("preset"),
        )
        render_log.outputs = {
            options.mode: str(result.path),
            "narration": str(narration_path),
            "subtitlesSrt": str(subtitle_result.srt_path),
            "subtitlesAss": str(subtitle_result.ass_path),
            "subtitleTimeline": str(subtitle_result.timeline_path),
        }
        render_log.details["timeline"] = timeline.to_dict()

        if not options.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)

        return RunResult(result.path, render_log.save(), out_dir, package, render_log.warnings)

    except PipelineError as exc:
        render_log.add_error(exc.code, exc.message)
        for stage in ("tts", "subtitle", "render"):
            if getattr(render_log, stage) == "pending":
                setattr(render_log, stage, STATUS_FAILED if stage == _stage_for(exc) else "not_reached")
        render_log.save()
        raise
    except Exception as exc:  # 예상 못 한 오류도 로그에 남긴다.
        render_log.add_error("ERR_RENDER_FAILED", f"{type(exc).__name__}: {exc}")
        render_log.save()
        raise


def _stage_for(exc: PipelineError) -> str:
    return {
        "ERR_TTS_FAILED": "tts",
        "ERR_SUBTITLE_FAILED": "subtitle",
        "ERR_RENDER_FAILED": "render",
    }.get(exc.code, "")


def _check_existing_output(out_dir: Path, options: RunOptions) -> None:
    """--force 없이 기존 결과물을 덮어쓰지 않도록 막는다."""
    if options.force:
        return
    target = out_dir / f"{options.mode}.mp4"
    if target.exists():
        raise RenderError(
            f"이미 결과물이 있습니다: {target}",
            details=["덮어쓰려면 --force 옵션을 쓰세요"],
        )
    if options.mode == MODE_FINAL and not (out_dir / f"{MODE_PREVIEW}.mp4").exists():
        # 명세서 §21: MVP에서 Preview 단계를 생략하지 않는다.
        raise RenderError(
            f"preview.mp4가 없습니다: {out_dir}",
            details=[
                "명세서 §21에 따라 Final은 Preview 검수 이후에 만듭니다",
                "먼저 --mode preview로 실행해 결과를 확인하세요",
                "검수 절차를 건너뛰려면 --force를 쓰세요",
            ],
        )
