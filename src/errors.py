"""오류 코드와 예외 정의 (명세서 §25).

정책:
    I2V 실패      → fallback 후 계속
    TTS 실패      → 중단
    자막 실패     → 중단
    최종 렌더 실패 → 중단
"""

from __future__ import annotations


class ErrorCode:
    """명세서 §25 오류 코드."""

    INPUT_MISSING = "ERR_INPUT_MISSING"
    SCENE_COUNT = "ERR_SCENE_COUNT"
    SCENE_IMAGE_MISSING = "ERR_SCENE_IMAGE_MISSING"
    INVALID_SCENE_TYPE = "ERR_INVALID_SCENE_TYPE"
    I2V_FAILED = "ERR_I2V_FAILED"
    TTS_FAILED = "ERR_TTS_FAILED"
    SUBTITLE_FAILED = "ERR_SUBTITLE_FAILED"
    RENDER_FAILED = "ERR_RENDER_FAILED"

    # 명세서 §25의 목록은 "예:"로 제시된 대표 코드다.
    # 아래 두 개는 위 코드로 표현할 수 없는 상황을 위해 추가했다.
    CONFIG_INVALID = "ERR_CONFIG_INVALID"
    DEPENDENCY_MISSING = "ERR_DEPENDENCY_MISSING"


class PipelineError(Exception):
    """파이프라인 공통 예외. 항상 오류 코드를 동반한다."""

    code = ErrorCode.INPUT_MISSING

    def __init__(self, message: str, *, code: str | None = None, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or []

    def __str__(self) -> str:  # pragma: no cover - 표현용
        if self.details:
            body = "\n".join(f"  - {d}" for d in self.details)
            return f"[{self.code}] {self.message}\n{body}"
        return f"[{self.code}] {self.message}"


class InputMissingError(PipelineError):
    code = ErrorCode.INPUT_MISSING


class SceneCountError(PipelineError):
    code = ErrorCode.SCENE_COUNT


class SceneImageMissingError(PipelineError):
    code = ErrorCode.SCENE_IMAGE_MISSING


class InvalidSceneTypeError(PipelineError):
    code = ErrorCode.INVALID_SCENE_TYPE


class I2VError(PipelineError):
    """I2V 실패. 파이프라인은 이 예외를 잡아 STILL fallback으로 계속 진행한다."""

    code = ErrorCode.I2V_FAILED


class TTSError(PipelineError):
    code = ErrorCode.TTS_FAILED


class SubtitleError(PipelineError):
    code = ErrorCode.SUBTITLE_FAILED


class RenderError(PipelineError):
    code = ErrorCode.RENDER_FAILED


class ConfigError(PipelineError):
    code = ErrorCode.CONFIG_INVALID


class DependencyMissingError(PipelineError):
    code = ErrorCode.DEPENDENCY_MISSING
