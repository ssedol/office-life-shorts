"""FFmpeg 렌더러 (명세서 §20, §21).

2단계로 렌더한다.

1) 씬별 클립  — outputs/YYYY-MM-DD/scenes/scene-XX.mp4
   STILL/fallback은 모션 필터로, I2V는 생성된 영상을 1080×1920/30fps로 정규화한다.
   모든 클립을 동일 규격으로 맞춰야 concat 시 재인코딩 없이 이어붙일 수 있다.
2) 최종 합성 — 클립 concat + narration.wav 먹싱 + 자막 번인 → preview.mp4 / final.mp4

최종 출력: 1080×1920 / 30fps / H.264 MP4 (명세서 §20)
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import REPO_ROOT
from ..errors import PipelineError, RenderError
from ..media.ffmpeg import FFmpeg
from ..scene.still import build_fit_chain, build_still_filter
from ..scene.timeline import SOURCE_I2V, TimelineScene, frames_for
from ..subtitle.fonts import resolve_font
from .base import RenderJob, Renderer, RenderResult

log = logging.getLogger(__name__)


class FFmpegRenderer(Renderer):
    name = "ffmpeg"

    def __init__(self, ffmpeg: FFmpeg):
        self.ffmpeg = ffmpeg

    # ---- 진입점 -------------------------------------------------------------
    def render(self, job: RenderJob) -> RenderResult:
        self.ffmpeg.require()

        cfg = job.render_cfg
        width = int(cfg["resolution"]["width"])
        height = int(cfg["resolution"]["height"])
        fps = int(cfg["fps"])

        job.scenes_dir.mkdir(parents=True, exist_ok=True)
        job.work_dir.mkdir(parents=True, exist_ok=True)
        job.out_path.parent.mkdir(parents=True, exist_ok=True)

        clips: list[Path] = []
        for item in job.timeline.scenes:
            try:
                clip = self._render_scene(item, job, width, height, fps)
            except PipelineError as exc:
                raise RenderError(f"{item.scene.id} 클립 렌더 실패", details=[str(exc)]) from exc
            item.clip_path = clip
            clips.append(clip)

        try:
            self._compose(clips, job, width, height, fps)
        except PipelineError as exc:
            raise RenderError("최종 합성 실패", details=[str(exc)]) from exc

        duration = self.ffmpeg.duration(job.out_path)
        size = self.ffmpeg.video_size(job.out_path)
        if size != (width, height):
            raise RenderError(
                f"출력 해상도가 {size}입니다 (기대값 {width}x{height})",
                details=[str(job.out_path)],
            )

        log.info("%s 렌더 완료: %s (%.2f초)", job.mode, job.out_path, duration)
        return RenderResult(
            path=job.out_path,
            mode=job.mode,
            width=width,
            height=height,
            fps=fps,
            duration_sec=duration,
            scene_clips=clips,
        )

    # ---- 씬 클립 ------------------------------------------------------------
    def _render_scene(self, item: TimelineScene, job: RenderJob, width: int, height: int, fps: int) -> Path:
        out_path = job.scenes_dir / f"{item.scene.id.lower()}.mp4"
        if item.source == SOURCE_I2V and item.i2v_raw_path is not None:
            return self._render_i2v_clip(item, job, out_path, width, height, fps)
        return self._render_still_clip(item, job, out_path, width, height, fps)

    def _render_still_clip(
        self, item: TimelineScene, job: RenderJob, out_path: Path, width: int, height: int, fps: int
    ) -> Path:
        cfg = job.render_cfg
        image = item.scene.image_path
        if image is None or not image.is_file():
            raise RenderError(f"{item.scene.id}: 이미지 파일이 없습니다: {item.scene.image_file}")

        total_frames = frames_for(item.duration, fps)
        still_cfg = cfg.get("still", {})
        chain = build_still_filter(
            item.scene.effective_motion,
            width,
            height,
            fps,
            total_frames,
            fit=str(cfg.get("fitMode", "cover")),
            background=cfg.get("backgroundColor"),
            super_sample=float(cfg.get("superSample", 2.0)),
            zoom_amount=float(still_cfg.get("zoomAmount", 0.12)),
            pan_amount=float(still_cfg.get("panAmount", 0.12)),
        )

        self.ffmpeg.run([
            "-framerate", str(fps),
            "-loop", "1",
            "-i", str(image),
            "-frames:v", str(total_frames),
            "-vf", chain,
            *self._video_encode_args(cfg, fps),
            "-an",
            str(out_path),
        ])
        return out_path

    def _render_i2v_clip(
        self, item: TimelineScene, job: RenderJob, out_path: Path, width: int, height: int, fps: int
    ) -> Path:
        cfg = job.render_cfg
        source = item.i2v_raw_path
        assert source is not None

        raw_duration = self.ffmpeg.duration(source)
        total_frames = frames_for(item.duration, fps)

        chain = [
            build_fit_chain(width, height, fit=str(cfg.get("fitMode", "cover")), background=cfg.get("backgroundColor")),
            f"fps={fps}",
        ]
        # 생성 영상이 씬보다 짧으면(명세서 §16: I2V는 3~5초) 마지막 프레임을 늘려 채운다.
        shortfall = item.duration - raw_duration
        if shortfall > 1.0 / fps:
            chain.append(f"tpad=stop_mode=clone:stop_duration={shortfall + 0.5:.3f}")
            item.notes.append(f"I2V 영상 {raw_duration:.2f}초 → 씬 {item.duration:.2f}초, 마지막 프레임으로 채움")
        chain += ["format=yuv420p", "setsar=1"]

        self.ffmpeg.run([
            "-i", str(source),
            "-frames:v", str(total_frames),
            "-vf", ",".join(chain),
            *self._video_encode_args(cfg, fps),
            "-an",
            str(out_path),
        ])
        return out_path

    # ---- 최종 합성 ----------------------------------------------------------
    def _compose(self, clips: list[Path], job: RenderJob, width: int, height: int, fps: int) -> None:
        cfg = job.render_cfg

        list_path = job.work_dir / "concat.txt"
        list_path.write_text(
            "".join(f"file '{clip.resolve().as_posix()}'\n" for clip in clips),
            encoding="utf-8",
        )

        # ffmpeg 필터에 경로를 직접 넣으면 Windows에서 깨진다. 필터그래프 파서는
        # ':'를 옵션 구분자로, '\\'를 이스케이프로 읽기 때문에 C:\경로\파일 같은 값이
        # 여러 단계 이스케이프를 거치며 망가진다. 그래서 자막과 폰트를 작업 폴더로
        # 복사하고 그 폴더를 cwd로 삼아 파일 이름만 넘긴다. 이스케이프가 아예 필요 없어진다.
        subtitle_filter = self._prepare_subtitle_filter(job)
        audio_cfg = cfg.get("audio", {})

        args = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-i", str(job.narration_path),
        ]

        filter_complex = f"[0:v]{subtitle_filter}[v]"
        audio_label = "1:a"

        bgm_cfg = cfg.get("bgm", {})
        bgm_path = self._bgm_path(bgm_cfg)
        if bgm_path is not None:
            args += ["-stream_loop", "-1", "-i", str(bgm_path)]
            gain = float(bgm_cfg.get("gainDb", -22))
            filter_complex += (
                f";[2:a]volume={gain}dB,aresample={audio_cfg.get('sampleRate', 48000)}[bgm]"
                f";[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            )
            audio_label = "[a]"

        args += [
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", audio_label,
            *self._video_encode_args(cfg, fps),
            "-c:a", str(audio_cfg.get("codec", "aac")),
            "-b:a", str(audio_cfg.get("bitrate", "192k")),
            "-ar", str(audio_cfg.get("sampleRate", 48000)),
            "-ac", str(audio_cfg.get("channels", 1)),
            "-movflags", "+faststart",
            "-shortest",
            str(job.out_path),
        ]
        # 입력과 출력은 모두 절대 경로라 cwd를 바꿔도 안전하다.
        self.ffmpeg.run(args, cwd=job.work_dir)

    def _prepare_subtitle_filter(self, job: RenderJob) -> str:
        """자막과 폰트를 작업 폴더에 모으고, 파일 이름만 쓰는 필터 문자열을 만든다.

        ffmpeg 필터에 절대 경로를 넣으면 Windows에서 필터그래프 파싱이 깨진다.
        작업 폴더를 cwd로 실행할 것이므로 여기서는 이름만 쓴다.
        """
        if not job.subtitle_path.is_file():
            raise RenderError(f"자막 파일이 없습니다: {job.subtitle_path}")

        job.work_dir.mkdir(parents=True, exist_ok=True)

        local_subtitle = job.work_dir / job.subtitle_path.name
        if local_subtitle.resolve() != job.subtitle_path.resolve():
            shutil.copy2(job.subtitle_path, local_subtitle)

        options = [f"filename={local_subtitle.name}"]

        font = resolve_font(job.subtitle_cfg)
        if font.path is not None:
            fonts_dir = job.work_dir / "fonts"
            fonts_dir.mkdir(exist_ok=True)
            local_font = fonts_dir / font.path.name
            if not local_font.exists():
                shutil.copy2(font.path, local_font)
            options.append("fontsdir=fonts")

        return "ass=" + ":".join(options)

    def _bgm_path(self, bgm_cfg: dict) -> Path | None:
        """BGM은 명세서 §35-4에 따라 MVP 기본 비활성이다. 파일을 넣고 enabled=true로 켠다."""
        if not bgm_cfg.get("enabled"):
            return None
        raw = bgm_cfg.get("file")
        if not raw:
            log.warning("bgm.enabled=true 이지만 file이 비어 있어 BGM을 건너뜁니다")
            return None
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            # ffmpeg는 job.work_dir을 cwd로 실행되므로, 저장소 루트 기준 상대 경로를 직접 붙인다.
            path = REPO_ROOT / path
        if not path.is_file():
            log.warning("BGM 파일을 찾을 수 없어 건너뜁니다: %s", path)
            return None
        return path

    # ---- 인코딩 옵션 --------------------------------------------------------
    @staticmethod
    def _video_encode_args(cfg: dict, fps: int) -> list[str]:
        return [
            "-c:v", "libx264",
            "-preset", str(cfg.get("preset", "medium")),
            "-crf", str(cfg.get("crf", 20)),
            "-profile:v", str(cfg.get("h264Profile", "high")),
            "-level", str(cfg.get("h264Level", "4.1")),
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-g", str(fps * 2),
        ]

    def describe(self) -> str:
        return f"FFmpegRenderer ({self.ffmpeg.ffmpeg_bin})"
