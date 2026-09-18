"""테스트 공통 픽스처.

실제 ffmpeg를 쓰는 테스트는 렌더 시간을 줄이려고 작은 해상도 config를 쓴다.
1080×1920 요구사항 자체를 확인하는 TEST-8만 기본 config를 그대로 쓴다.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import deep_merge, load_config  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe가 필요합니다")

MOTIONS_BY_ORDER = [
    "slow_zoom_in",
    None,  # SCENE-02 = I2V
    "static",
    "slow_zoom_out",
    None,  # SCENE-05 = I2V
    "slow_pan_left",
    "slow_pan_right",
    "slow_zoom_in",
]

I2V_ORDERS = (2, 5)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def make_image(path: Path, width: int = 270, height: int = 480, label: str = "") -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), (253, 224, 122))
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, width - 10, height - 10), outline=(21, 32, 70), width=4)
    if label:
        draw.text((20, 20), label, fill=(21, 32, 70))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def make_package(
    root: Path,
    *,
    date: str = "2026-09-18",
    scene_count: int = 8,
    duration_sec: float = 1.0,
    image_size: tuple[int, int] = (270, 480),
    skip_images: list[int] | None = None,
    drop_files: list[str] | None = None,
    scene_overrides: dict[int, dict] | None = None,
) -> Path:
    """테스트용 입력 패키지를 만든다. order는 1부터 scene_count까지."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    skip_images = skip_images or []
    drop_files = drop_files or []
    scene_overrides = scene_overrides or {}

    scenes = []
    for order in range(1, scene_count + 1):
        is_i2v = order in I2V_ORDERS
        scene: dict = {
            "id": f"SCENE-{order:02d}",
            "order": order,
            "durationSec": duration_sec,
            "type": "I2V" if is_i2v else "STILL",
            "reason": "테스트용 씬",
            "imageFile": f"scene-{order:02d}.png",
            "narration": f"{order}번째 씬 내레이션입니다.",
            "subtitle": f"{order}번 **자막**",
        }
        if is_i2v:
            scene["videoPrompt"] = "Subtle blinking and a very slow camera push-in. Keep the character unchanged."
        else:
            motion = MOTIONS_BY_ORDER[(order - 1) % len(MOTIONS_BY_ORDER)]
            if motion:
                scene["motion"] = motion
        scene.update(scene_overrides.get(order, {}))
        scenes.append(scene)

        if order not in skip_images and scene.get("imageFile"):
            make_image(root / scene["imageFile"], *image_size, label=scene["id"])

    project = {
        "channel": "오늘도출근",
        "date": date,
        "topic": "테스트 주제",
        "title": "테스트 제목",
        "durationTargetSec": 40,
        "sceneCount": 8,
        "resolution": {"width": image_size[0], "height": image_size[1]},
        "fps": 30,
        "tts": {"engine": "offline", "voice": "UNDECIDED", "speed": 1.0},
        "renderMode": "preview",
    }

    if "project.json" not in drop_files:
        (root / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    if "scene-plan.json" not in drop_files:
        (root / "scene-plan.json").write_text(
            json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if "script.txt" not in drop_files:
        (root / "script.txt").write_text("테스트 대본\n" + "\n".join(s["narration"] for s in scenes), encoding="utf-8")

    return root


def make_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    """저장소 config를 복사하고 일부 값을 덮어쓴 config 폴더를 만든다."""
    target = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", target)

    for name, override in (overrides or {}).items():
        path = target / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(deep_merge(data, override), ensure_ascii=False, indent=2), encoding="utf-8")

    return target


@pytest.fixture
def fast_config(tmp_path: Path):
    """작은 해상도 + 오프라인 TTS + I2V 비활성 기본값."""
    config_dir = make_config(
        tmp_path,
        {
            "render": {
                "resolution": {"width": 270, "height": 480},
                "profiles": {"preview": {"preset": "ultrafast", "crf": 34, "superSample": 1.0}},
            },
            "tts": {"engine": "offline"},
            "subtitle": {"fontSize": 22, "minFontSize": 14, "safeArea": {"marginLeft": 20, "marginRight": 20, "marginBottom": 90}},
            "i2v": {"comfyui": {"connectTimeoutSec": 2, "pollIntervalSec": 0.05, "timeoutSec": 20}, "retry": {"attempts": 1, "backoffSec": 0.0}},
        },
    )
    return load_config(config_dir, repo_root=REPO_ROOT)


@pytest.fixture
def default_config():
    """저장소 기본 config (1080×1920)."""
    return load_config(REPO_ROOT / "config", repo_root=REPO_ROOT)


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    return make_package(tmp_path / "inputs" / "2026-09-18")
