"""입력 패키지 로더 (명세서 §10, §11, §12).

파일 존재/파싱만 담당한다. 내용 검증은 src/validator가 맡는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import InputMissingError
from ..scene.models import InputPackage, Project, Scene

PROJECT_FILE = "project.json"
SCENE_PLAN_FILE = "scene-plan.json"
SCRIPT_FILE = "script.txt"
REQUIRED_FILES = (PROJECT_FILE, SCENE_PLAN_FILE, SCRIPT_FILE)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        raise InputMissingError(
            f"{label} JSON 파싱 실패: {path.name}",
            details=[f"{exc.msg} (line {exc.lineno}, column {exc.colno})"],
        ) from exc
    if not isinstance(data, dict):
        raise InputMissingError(f"{label}의 최상위는 객체여야 합니다: {path.name}")
    return data


def load_input_package(input_dir: Path) -> InputPackage:
    """입력 폴더를 읽어 InputPackage를 만든다.

    필수 파일이 없으면 ERR_INPUT_MISSING으로 중단한다(명세서 §14).
    """
    root = Path(input_dir).expanduser().resolve()
    if not root.exists():
        raise InputMissingError(f"입력 폴더가 없습니다: {root}")
    if not root.is_dir():
        raise InputMissingError(f"입력 경로가 폴더가 아닙니다: {root}")

    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise InputMissingError(
            f"입력 폴더에 필수 파일이 없습니다: {root}",
            details=[f"누락: {name}" for name in missing],
        )

    project_raw = _read_json(root / PROJECT_FILE, "project.json")
    scene_plan_raw = _read_json(root / SCENE_PLAN_FILE, "scene-plan.json")

    scenes_raw = scene_plan_raw.get("scenes")
    if not isinstance(scenes_raw, list):
        raise InputMissingError("scene-plan.json에 'scenes' 배열이 없습니다")

    scenes: list[Scene] = []
    for index, item in enumerate(scenes_raw):
        if not isinstance(item, dict):
            raise InputMissingError(f"scene-plan.json scenes[{index}]가 객체가 아닙니다")
        scene = Scene.from_dict(item)
        if scene.image_file:
            scene.image_path = root / scene.image_file
        scenes.append(scene)

    # order 기준 정렬. order가 비정상이어도 검증 단계에서 잡히도록 원본 순서를 보조 키로 쓴다.
    scenes = [s for _, s in sorted(enumerate(scenes), key=lambda pair: (pair[1].order, pair[0]))]

    script = (root / SCRIPT_FILE).read_text(encoding="utf-8")

    return InputPackage(
        root=root,
        project=Project.from_dict(project_raw),
        scenes=scenes,
        script=script,
        project_raw=project_raw,
        scene_plan_raw=scene_plan_raw,
    )
