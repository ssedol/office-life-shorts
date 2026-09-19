"""ffmpeg / ffprobe 호출 래퍼.

이 모듈은 렌더러 구현체(FFmpegRenderer)와 TTS 후처리가 공유한다.
렌더러를 교체해도(명세서 §20) 여기 있는 오디오 유틸은 그대로 재사용할 수 있다.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import DependencyMissingError, PipelineError

log = logging.getLogger(__name__)


@dataclass
class FFmpegResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class FFmpeg:
    """ffmpeg / ffprobe 실행기."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe", loglevel: str = "error"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.loglevel = loglevel

    # ---- 가용성 -------------------------------------------------------------
    def available(self) -> bool:
        return shutil.which(self.ffmpeg_bin) is not None and shutil.which(self.ffprobe_bin) is not None

    def require(self) -> None:
        missing = [b for b in (self.ffmpeg_bin, self.ffprobe_bin) if shutil.which(b) is None]
        if missing:
            raise DependencyMissingError(
                "ffmpeg/ffprobe를 찾을 수 없습니다",
                details=[
                    f"PATH에 없음: {', '.join(missing)}",
                    "Ubuntu/Debian: sudo apt-get install ffmpeg",
                    "macOS: brew install ffmpeg",
                    "Windows: https://www.gyan.dev/ffmpeg/builds/ 에서 받아 PATH에 추가",
                ],
            )

    # ---- 실행 ---------------------------------------------------------------
    def run(self, args: list[str], *, cwd: Path | None = None, check: bool = True) -> FFmpegResult:
        """ffmpeg 실행. args는 ffmpeg 바이너리 뒤에 오는 인자만 넘긴다."""
        cmd = [self.ffmpeg_bin, "-hide_banner", "-loglevel", self.loglevel, "-nostdin", "-y", *args]
        log.debug("ffmpeg: %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        result = FFmpegResult(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")
        if check and proc.returncode != 0:
            raise PipelineError(
                "ffmpeg 실행 실패",
                details=[
                    " ".join(cmd),
                    (result.stderr or "(stderr 없음)").strip()[-2000:],
                ],
            )
        return result

    def probe(self, path: Path) -> dict:
        """ffprobe -show_format -show_streams 결과를 dict로 돌려준다."""
        cmd = [
            self.ffprobe_bin,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise PipelineError(
                f"ffprobe 실패: {path}",
                details=[(proc.stderr or "").strip()[-1000:]],
            )
        return json.loads(proc.stdout or "{}")

    def duration(self, path: Path) -> float:
        """미디어 길이(초). 알 수 없으면 0.0."""
        info = self.probe(path)
        fmt_dur = info.get("format", {}).get("duration")
        if fmt_dur not in (None, "N/A"):
            try:
                return float(fmt_dur)
            except (TypeError, ValueError):
                pass
        for stream in info.get("streams", []):
            value = stream.get("duration")
            if value not in (None, "N/A"):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return 0.0

    def video_size(self, path: Path) -> tuple[int, int] | None:
        for stream in self.probe(path).get("streams", []):
            if stream.get("codec_type") == "video":
                return int(stream["width"]), int(stream["height"])
        return None

    def has_audio(self, path: Path) -> bool:
        return any(s.get("codec_type") == "audio" for s in self.probe(path).get("streams", []))

    # ---- 오디오 유틸 --------------------------------------------------------
    def silence(self, out_path: Path, seconds: float, *, sample_rate: int = 48000, channels: int = 1) -> Path:
        """지정 길이의 무음 WAV를 만든다."""
        layout = "mono" if channels == 1 else "stereo"
        self.run([
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl={layout}",
            "-t", f"{max(seconds, 0.0):.6f}",
            "-c:a", "pcm_s16le",
            str(out_path),
        ])
        return out_path

    def to_wav(
        self,
        src: Path,
        out_path: Path,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
        normalize: dict | None = None,
    ) -> Path:
        """임의 오디오를 파이프라인 표준 WAV(PCM 16bit)로 변환한다.

        normalize가 주어지면 EBU R128 loudnorm으로 음량을 정규화한다(명세서 §18).
        """
        filters: list[str] = []
        if normalize and normalize.get("enabled", True):
            target = float(normalize.get("targetLufs", -16.0))
            tp = float(normalize.get("truePeakDb", -1.5))
            lra = float(normalize.get("lra", 11.0))
            filters.append(f"loudnorm=I={target}:TP={tp}:LRA={lra}")
        filters.append(f"aresample={sample_rate}")

        self.run([
            "-i", str(src),
            "-af", ",".join(filters),
            "-ac", str(channels),
            "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            str(out_path),
        ])
        return out_path

    def pad_to_duration(
        self,
        src: Path,
        out_path: Path,
        *,
        total_seconds: float,
        lead_in: float = 0.0,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> Path:
        """오디오 앞에 lead_in 무음을 붙이고 total_seconds 길이로 정확히 맞춘다."""
        delay_ms = int(round(max(lead_in, 0.0) * 1000))
        chain = []
        if delay_ms > 0:
            chain.append(f"adelay={delay_ms}:all=1")
        chain.append("apad")
        chain.append(f"atrim=0:{total_seconds:.6f}")
        chain.append("asetpts=N/SR/TB")
        self.run([
            "-i", str(src),
            "-af", ",".join(chain),
            "-ac", str(channels),
            "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            str(out_path),
        ])
        return out_path

    def concat_audio(
        self,
        parts: list[Path],
        out_path: Path,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
    ) -> Path:
        """여러 WAV를 순서대로 이어붙인다."""
        if not parts:
            raise PipelineError("이어붙일 오디오가 없습니다")
        if len(parts) == 1:
            self.run(["-i", str(parts[0]), "-c:a", "pcm_s16le", "-ar", str(sample_rate), "-ac", str(channels), str(out_path)])
            return out_path

        args: list[str] = []
        for part in parts:
            args += ["-i", str(part)]
        inputs = "".join(f"[{i}:a]" for i in range(len(parts)))
        filtergraph = f"{inputs}concat=n={len(parts)}:v=0:a=1[out]"
        args += [
            "-filter_complex", filtergraph,
            "-map", "[out]",
            "-ac", str(channels),
            "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            str(out_path),
        ]
        self.run(args)
        return out_path


def escape_filter_path(path: str) -> str:
    """ffmpeg 필터 인자에 파일 경로를 넣을 때 필요한 이스케이프.

    Windows 경로의 백슬래시는 필터그래프 파서가 이스케이프 문자로 읽어서,
    이스케이프를 겹쳐 봐야 값이 망가진다. ffmpeg은 Windows에서도 슬래시 경로를
    받으므로 먼저 슬래시로 바꾼 뒤 ':'와 작은따옴표만 처리한다.

    그래도 드라이브 문자의 ':'는 남으므로 완전히 안전하지는 않다.
    자막처럼 확실해야 하는 경로는 파일을 작업 폴더로 옮기고 이름만 쓰는 편이 낫다
    (src/render/ffmpeg_renderer.py의 _prepare_subtitle_filter 참고).
    """
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
