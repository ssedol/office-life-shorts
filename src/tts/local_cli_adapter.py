"""로컬 TTS CLI 브리지 어댑터 (명세서 §18 SupertonicAdapter 자리).

명세서 §35-2에 따라 최종 엔진/보이스가 아직 확정되지 않았으므로,
특정 라이브러리 API에 코드를 고정하지 않고 "로컬 CLI를 호출하는" 일반 어댑터로 만들었다.
config/tts.json에서 실행 파일과 인자 템플릿만 지정하면 어떤 로컬 엔진이든 붙는다.

config/tts.json 예시:

    "engines": {
      "supertonic": {
        "cliPath": "/opt/supertonic/bin/supertonic-tts",
        "args": ["--text", "{text}", "--voice", "{voice}", "--speed", "{speed}", "--out", "{out}"],
        "voice": "ko-female-01",
        "outputSuffix": ".wav",
        "cwd": null,
        "timeoutSec": 120
      }
    }

치환 가능한 자리표시자: {text} {voice} {speed} {out} {sampleRate}
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..errors import TTSError
from .base import SynthesisRequest, TTSProvider


class LocalCliAdapter(TTSProvider):
    name = "cli"

    def __init__(self, options: dict | None = None, *, engine_name: str | None = None):
        super().__init__(options)
        if engine_name:
            self.name = engine_name
        self.output_suffix = str(self.options.get("outputSuffix") or ".wav")

    # ---- 내부 --------------------------------------------------------------
    def _cli_path(self) -> str:
        cli = self.options.get("cliPath")
        if not cli:
            raise TTSError(
                f"'{self.name}' 엔진의 cliPath가 설정되지 않았습니다",
                details=[
                    f"config/tts.json → engines.{self.name}.cliPath 에 실행 파일 경로를 넣으세요",
                    f"인자 형식은 engines.{self.name}.args 에서 지정합니다",
                    "당장 확인만 하려면 engine을 'edge'(온라인) 또는 'offline'으로 바꾸세요",
                ],
            )
        return str(cli)

    def preflight(self) -> None:
        cli = self._cli_path()
        if shutil.which(cli) is None and not Path(cli).expanduser().is_file():
            raise TTSError(
                f"'{self.name}' 실행 파일을 찾을 수 없습니다: {cli}",
                details=[f"config/tts.json → engines.{self.name}.cliPath 를 확인하세요"],
            )

    def _build_args(self, request: SynthesisRequest, out_path: Path, voice: str) -> list[str]:
        template = self.options.get("args")
        if not isinstance(template, list) or not template:
            raise TTSError(
                f"'{self.name}' 엔진의 args 템플릿이 없습니다",
                details=[
                    f"config/tts.json → engines.{self.name}.args 를 리스트로 지정하세요",
                    '예: ["--text", "{text}", "--out", "{out}"]',
                ],
            )
        mapping = {
            "text": request.text,
            "voice": voice,
            "speed": f"{request.speed:g}",
            "out": str(out_path),
            "sampleRate": str(request.sample_rate),
        }
        args: list[str] = []
        for item in template:
            value = str(item)
            for key, replacement in mapping.items():
                value = value.replace("{" + key + "}", replacement)
            args.append(value)
        return args

    # ---- 인터페이스 ---------------------------------------------------------
    def synthesize(self, request: SynthesisRequest) -> Path:
        self.preflight()

        text = request.text.strip()
        if not text:
            raise TTSError("합성할 텍스트가 비어 있습니다")

        out_path = request.out_path.with_suffix(self.output_suffix)
        voice = request.voice or str(self.options.get("voice") or "")
        cmd = [self._cli_path(), *self._build_args(request, out_path, voice)]
        cwd = self.options.get("cwd")
        timeout = float(self.options.get("timeoutSec", 120))

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise TTSError(f"'{self.name}' 합성이 {timeout}초 안에 끝나지 않았습니다") from exc
        except OSError as exc:
            raise TTSError(f"'{self.name}' 실행 실패: {exc}") from exc

        if proc.returncode != 0:
            raise TTSError(
                f"'{self.name}' 합성 실패 (exit {proc.returncode})",
                details=[" ".join(cmd), (proc.stderr or "").strip()[-1500:]],
            )
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise TTSError(f"'{self.name}'가 출력 파일을 만들지 않았습니다: {out_path}")
        return out_path

    def describe(self) -> str:
        return f"{self.name} CLI ({self.options.get('cliPath') or '미설정'})"


class SupertonicAdapter(LocalCliAdapter):
    """명세서 §18이 지목한 Supertonic 계열 자리.

    실제 보이스/모델이 확정되면 config/tts.json의 engines.supertonic만 채우면 된다.
    """

    def __init__(self, options: dict | None = None):
        super().__init__(options, engine_name="supertonic")
