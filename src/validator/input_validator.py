"""FEAT-1 입력 검증 (명세서 §14).

검증 항목:
    - project.json / scene-plan.json / script.txt 존재      (loader에서 이미 확인)
    - 씬 개수 정확히 8
    - 이미지 8장 존재
    - type 값이 STILL 또는 I2V
    - I2V 씬에 videoPrompt 존재
    - durationSec > 0

오류가 하나라도 있으면 렌더를 시작하지 않고, 누락/오류 항목을 모두 모아서 출력한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import AppConfig
from ..errors import (
    InputMissingError,
    InvalidSceneTypeError,
    SceneCountError,
    SceneImageMissingError,
)
from ..scene.models import MOTIONS, SCENE_TYPES, InputPackage

try:  # Pillow는 선택 의존성이다. 없으면 이미지 크기 검사만 건너뛴다.
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - 환경에 따라 다름
    Image = None  # type: ignore


@dataclass
class ValidationReport:
    errors: list[tuple[str, str]] = field(default_factory=list)  # (오류코드, 메시지)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, message: str) -> None:
        self.errors.append((code, message))

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error_messages(self) -> list[str]:
        return [f"{code}: {message}" for code, message in self.errors]


def validate(package: InputPackage, cfg: AppConfig, *, strict: bool = False) -> ValidationReport:
    """입력 패키지를 검증하고 보고서를 돌려준다. 예외는 던지지 않는다."""
    report = ValidationReport()
    expected_count = cfg.scene_count

    _check_project(package, cfg, report)
    _check_scene_count(package, expected_count, report)
    _check_scenes(package, cfg, report)
    _check_script(package, report)

    if strict and report.warnings:
        for message in report.warnings:
            report.error("ERR_INPUT_MISSING", f"(strict) {message}")
        report.warnings = []

    return report


def validate_or_raise(package: InputPackage, cfg: AppConfig, *, strict: bool = False) -> ValidationReport:
    """검증 실패 시 대표 오류 코드로 예외를 던진다."""
    report = validate(package, cfg, strict=strict)
    if report.ok:
        return report

    first_code = report.errors[0][0]
    exc_by_code = {
        "ERR_SCENE_COUNT": SceneCountError,
        "ERR_SCENE_IMAGE_MISSING": SceneImageMissingError,
        "ERR_INVALID_SCENE_TYPE": InvalidSceneTypeError,
        "ERR_INPUT_MISSING": InputMissingError,
    }
    exc_cls = exc_by_code.get(first_code, InputMissingError)
    raise exc_cls(
        f"입력 검증 실패: {package.root}",
        details=report.error_messages(),
    )


# ---------------------------------------------------------------------------


def _check_project(package: InputPackage, cfg: AppConfig, report: ValidationReport) -> None:
    project = package.project

    for field_name, value in (
        ("channel", project.channel),
        ("date", project.date),
        ("title", project.title),
    ):
        if not str(value).strip():
            report.error("ERR_INPUT_MISSING", f"project.json '{field_name}' 값이 비어 있습니다")

    if project.duration_target_sec <= 0:
        report.error("ERR_INPUT_MISSING", "project.json durationTargetSec는 0보다 커야 합니다")

    duration_range = cfg.app.get("durationRange", {})
    lo = float(duration_range.get("minSec", 35))
    hi = float(duration_range.get("maxSec", 45))
    if not (lo <= project.duration_target_sec <= hi):
        report.warn(
            f"project.json durationTargetSec={project.duration_target_sec}초가 "
            f"권장 범위({lo}~{hi}초)를 벗어납니다"
        )

    if project.scene_count != cfg.scene_count:
        report.error(
            "ERR_SCENE_COUNT",
            f"project.json sceneCount={project.scene_count} (기대값 {cfg.scene_count})",
        )

    if project.resolution and (project.resolution.width <= 0 or project.resolution.height <= 0):
        report.error("ERR_INPUT_MISSING", "project.json resolution은 양수여야 합니다")

    if project.fps is not None and project.fps <= 0:
        report.error("ERR_INPUT_MISSING", "project.json fps는 0보다 커야 합니다")

    if project.render_mode and project.render_mode not in ("preview", "final"):
        report.warn(f"project.json renderMode='{project.render_mode}'는 preview/final이 아닙니다")


def _check_scene_count(package: InputPackage, expected: int, report: ValidationReport) -> None:
    actual = len(package.scenes)
    if actual != expected:
        report.error(
            "ERR_SCENE_COUNT",
            f"scene-plan.json 씬 개수가 {actual}개입니다 (명세서 §8.2에 따라 항상 {expected}개)",
        )


def _check_scenes(package: InputPackage, cfg: AppConfig, report: ValidationReport) -> None:
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    i2v_count = 0

    for index, scene in enumerate(package.scenes):
        label = scene.id or f"scenes[{index}]"

        if not scene.id:
            report.error("ERR_INPUT_MISSING", f"scenes[{index}] 'id'가 없습니다")
        elif scene.id in seen_ids:
            report.error("ERR_INPUT_MISSING", f"씬 id가 중복됩니다: {scene.id}")
        else:
            seen_ids.add(scene.id)

        if scene.order <= 0:
            report.error("ERR_INPUT_MISSING", f"{label} 'order'는 1 이상이어야 합니다 (현재 {scene.order})")
        elif scene.order in seen_orders:
            report.error("ERR_INPUT_MISSING", f"{label} 'order'가 중복됩니다: {scene.order}")
        else:
            seen_orders.add(scene.order)

        if scene.duration_sec <= 0:
            report.error("ERR_INPUT_MISSING", f"{label} 'durationSec'는 0보다 커야 합니다 (현재 {scene.duration_sec})")

        if scene.type not in SCENE_TYPES:
            report.error(
                "ERR_INVALID_SCENE_TYPE",
                f"{label} 'type'이 '{scene.type or '(없음)'}'입니다. {' 또는 '.join(SCENE_TYPES)}만 허용됩니다",
            )

        if not str(scene.reason).strip():
            report.warn(f"{label} 'reason'이 비어 있습니다")

        if not str(scene.narration).strip():
            report.warn(f"{label} 'narration'이 비어 있습니다 (해당 씬은 무음으로 처리됩니다)")

        if not str(scene.subtitle).strip():
            report.warn(f"{label} 'subtitle'이 비어 있습니다 (해당 씬은 자막 없이 렌더됩니다)")

        _check_scene_image(scene, label, report)

        if scene.is_i2v:
            i2v_count += 1
            if not str(scene.video_prompt or "").strip():
                report.error(
                    "ERR_INPUT_MISSING",
                    f"{label} type=I2V인데 'videoPrompt'가 없습니다 (명세서 §12)",
                )
        elif scene.motion is not None and scene.motion not in MOTIONS:
            report.error(
                "ERR_INVALID_SCENE_TYPE",
                f"{label} 'motion'이 '{scene.motion}'입니다. 허용: {', '.join(MOTIONS)}",
            )

    # 명세서 §9.3 권장 비율. 강제는 아니므로 경고로만 알린다.
    if package.scenes and not (2 <= i2v_count <= 3):
        report.warn(f"I2V 씬이 {i2v_count}개입니다 (명세서 §9.3 권장: 2~3개)")


def _check_scene_image(scene, label: str, report: ValidationReport) -> None:
    if not scene.image_file:
        report.error("ERR_SCENE_IMAGE_MISSING", f"{label} 'imageFile'이 없습니다")
        return

    path: Path | None = scene.image_path
    if path is None or not path.is_file():
        report.error(
            "ERR_SCENE_IMAGE_MISSING",
            f"{label} 이미지 파일이 없습니다: {scene.image_file}",
        )
        return

    if path.stat().st_size == 0:
        report.error("ERR_SCENE_IMAGE_MISSING", f"{label} 이미지 파일이 비어 있습니다: {scene.image_file}")
        return

    if Image is None:
        return

    try:
        with Image.open(path) as img:
            width, height = img.size
    except Exception as exc:  # 손상된 이미지
        report.error("ERR_SCENE_IMAGE_MISSING", f"{label} 이미지를 열 수 없습니다: {scene.image_file} ({exc})")
        return

    if width <= 0 or height <= 0:
        report.error("ERR_SCENE_IMAGE_MISSING", f"{label} 이미지 크기가 비정상입니다: {width}x{height}")
        return

    # 명세서 §13: 기본 비율 9:16
    ratio = width / height
    target = 9 / 16
    if abs(ratio - target) > 0.02:
        report.warn(
            f"{label} 이미지 비율이 {width}x{height} (≈{ratio:.3f})로 9:16({target:.3f})과 다릅니다. "
            "config/render.json fitMode 설정에 따라 크롭 또는 레터박스 처리됩니다"
        )


def _check_script(package: InputPackage, report: ValidationReport) -> None:
    if not package.script.strip():
        report.error("ERR_INPUT_MISSING", "script.txt가 비어 있습니다")
