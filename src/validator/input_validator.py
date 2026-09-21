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
    _check_cta(package, cfg, report)
    _check_script_style(package, cfg, report)

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


#: cta.scenes가 가리키는 위치별 안내 문구
_CTA_HINTS = {
    "first": (
        "훅에 시청자에게 던지는 질문을 넣으면, 끝까지 보지 않은 사람도 댓글을 답니다 "
        '(예: "여러분도 해보셨죠?"). 자막은 훅 그대로 두고 내레이션에만 붙이면 훅이 약해지지 않습니다'
    ),
    "last": (
        "마지막 씬에 시청자에게 던지는 질문을 넣으면 댓글이 붙습니다 "
        '(예: "여러분은 어떻게 하세요?")'
    ),
}


def _resolve_cta_scenes(package: InputPackage, targets: list) -> list[tuple[str, object]]:
    """cta.scenes 설정을 (위치이름, 씬) 목록으로 바꾼다.

    'first' / 'last' 또는 1부터 시작하는 씬 번호를 받는다.
    """
    resolved: list[tuple[str, object]] = []
    for target in targets:
        if target == "first":
            resolved.append(("first", package.scenes[0]))
        elif target == "last":
            resolved.append(("last", package.scenes[-1]))
        elif isinstance(target, int) and 1 <= target <= len(package.scenes):
            resolved.append(("last", package.scenes[target - 1]))
    return resolved


def _check_script_style(package: InputPackage, cfg: AppConfig, report: ValidationReport) -> None:
    """내레이션이 '말'인지 '설명문'인지 살펴 경고한다 (2026-09-21 추가).

    1편과 2편을 만들고 나서 '귀에 안 들어온다'는 문제가 나왔다. 세어 보니 두 대본 모두
    실제 대사가 0/8씬이었고, 주어가 거의 전부 생략돼 있었으며, 지시어가 가리키는 대상이
    나오기 전에 먼저 쓰였다. 글로 읽으면 넘어가는 것들이 TTS로 들으면 잡히지 않는다.

    대본은 사람이 쓰는 것이라 강제하지 않는다. cta 검사와 같이 경고로만 알린다.
    """
    style = cfg.app.get("script", {})
    if not style.get("required", False) or not package.scenes:
        return

    scenes = package.scenes

    # 1) 실제 대사가 있는가
    marks = [str(m) for m in style.get("quoteMarks", []) if str(m)]
    min_quoted = int(style.get("minQuotedScenes", 0))
    if marks and min_quoted:
        quoted = sum(1 for sc in scenes if any(m in sc.narration for m in marks))
        if quoted < min_quoted:
            report.warn(
                f"대본에 실제 대사가 {quoted}개 씬에만 있습니다 (권장 {min_quoted}개 이상). "
                f"해설만 이어지면 장면이 보이지 않아 귀에 남지 않습니다. "
                f'예: 상대가 한 말을 "..." 안에 그대로 넣기'
            )

    # 2) 지시어가 가리키는 대상보다 먼저 나오지 않는가
    words = [str(w) for w in style.get("demonstratives", []) if str(w)]
    max_scenes = int(style.get("maxDemonstrativeScenes", len(scenes)))
    if words:
        hit_scenes = [sc for sc in scenes if any(w in sc.narration for w in words)]
        if len(hit_scenes) > max_scenes:
            ids = ", ".join(sc.id for sc in hit_scenes)
            report.warn(
                f"지시어('이 말', '이것' 등)가 {len(hit_scenes)}개 씬에 있습니다 "
                f"(권장 {max_scenes}개 이하): {ids}. "
                f"음성은 되돌려 들을 수 없어, 가리키는 대상을 그때그때 말해 주는 편이 낫습니다"
            )

    # 3) 낭독체 어미를 쓰지 않는가
    endings = [str(e) for e in style.get("writtenEndings", []) if str(e)]
    for sc in scenes:
        found = [e for e in endings if e in sc.narration]
        if found:
            report.warn(
                f"{sc.id}: 문어체 표현이 있습니다 ({', '.join(found)}). "
                f"TTS가 그대로 읽으면 낭독하는 느낌이 납니다"
            )

    # 4) 한 씬이 너무 길지 않은가
    limit = int(style.get("maxNarrationChars", 0))
    if limit:
        for sc in scenes:
            length = len(sc.narration.strip())
            if length > limit:
                report.warn(
                    f"{sc.id}: 내레이션이 {length}자입니다 (권장 {limit}자 이하). "
                    f"한 씬이 길면 자막이 넘치고 화면이 정체됩니다"
                )


def _check_cta(package: InputPackage, cfg: AppConfig, report: ValidationReport) -> None:
    """댓글 유도 문구가 있는지 확인한다 (기본: 훅과 마지막 씬 두 군데).

    쇼츠에서 댓글은 노출에 직접 영향을 주는데, 대본을 쓰다 보면 가장 빠뜨리기 쉬운 항목이다.
    훅과 마무리 두 군데에 심으면, 끝까지 본 사람과 중간에 이탈한 사람 양쪽에서 댓글이 나온다.
    강제하면 콘텐츠에 개입하는 셈이라 경고로만 알린다(명세서 §33-4: scene-plan 우선).
    """
    cta_cfg = cfg.app.get("cta", {})
    if not cta_cfg.get("required", False) or not package.scenes:
        return

    patterns = [str(p) for p in cta_cfg.get("patterns", []) if str(p).strip()]
    if not patterns:
        return

    def _has_cta(scene) -> bool:
        haystack = f"{scene.narration} {scene.subtitle}"
        return any(pattern in haystack for pattern in patterns)

    for position, scene in _resolve_cta_scenes(package, list(cta_cfg.get("scenes", ["last"]))):
        if _has_cta(scene):
            continue
        report.warn(
            f"{scene.id}: 댓글 유도 문구가 없습니다. {_CTA_HINTS[position]}. "
            f"config/app.json의 cta.patterns에서 인식 기준을 조정할 수 있습니다"
        )

    # 앞쪽에도 하나 더 있어야 중간 이탈자에게서 댓글이 나온다.
    # 다만 '1번 씬에 반드시'로 못 박으면, 사건을 꺼내기도 전에 공감을 묻는
    # 빈 질문이 된다(3편 초안이 그랬다). 그래서 범위로만 확인한다.
    early_within = int(cta_cfg.get("earlyWithin", 0))
    if early_within > 0:
        head = package.scenes[:early_within]
        if head and not any(_has_cta(sc) for sc in head):
            report.warn(
                f"앞쪽 {early_within}개 씬에 댓글 유도 문구가 없습니다. "
                f"끝까지 보지 않는 사람에게서도 댓글이 나오려면 중간에 한 번 물어야 합니다 "
                f'(예: "여러분도 해보셨죠?"). '
                f"사건을 다 보여준 뒤에 물어야 가리킬 대상이 생깁니다 — "
                f"1번 씬에서 물으면 무슨 얘긴지 모르는 채로 공감을 요구하게 됩니다. "
                f"자막은 그대로 두고 내레이션에만 붙이면 화면이 약해지지 않습니다"
            )
