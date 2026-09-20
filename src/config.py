"""config/*.json 로딩과 병합.

config 디렉터리의 JSON 4종(+i2v)을 읽어 하나의 AppConfig로 묶는다.
project.json이 일부 값(해상도/fps/tts)을 덮어쓸 수 있고,
CLI 옵션이 그보다 더 우선한다.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

CONFIG_FILES = {
    "app": "app.json",
    "render": "render.json",
    "tts": "tts.json",
    "subtitle": "subtitle.json",
    "i2v": "i2v.json",
    "upload": "upload.json",
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """override를 base 위에 재귀적으로 덮어쓴 새 dict를 반환한다.

    override의 값이 None이면 무시한다(= "지정 안 함").
    """
    out = copy.deepcopy(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    try:
        with path.open(encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"설정 파일 JSON 파싱 실패: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"설정 파일 최상위는 객체여야 합니다: {path}")
    return data


@dataclass
class AppConfig:
    """실행에 필요한 모든 설정 묶음."""

    app: dict[str, Any] = field(default_factory=dict)
    render: dict[str, Any] = field(default_factory=dict)
    tts: dict[str, Any] = field(default_factory=dict)
    subtitle: dict[str, Any] = field(default_factory=dict)
    i2v: dict[str, Any] = field(default_factory=dict)
    # 업로드는 렌더 파이프라인이 쓰지 않는다. 파일이 없어도 빈 dict로 둔다.
    upload: dict[str, Any] = field(default_factory=dict)
    repo_root: Path = REPO_ROOT

    # ---- 자주 쓰는 값 접근자 -------------------------------------------------
    @property
    def width(self) -> int:
        return int(self.render["resolution"]["width"])

    @property
    def height(self) -> int:
        return int(self.render["resolution"]["height"])

    @property
    def fps(self) -> int:
        return int(self.render["fps"])

    @property
    def scene_count(self) -> int:
        return int(self.app["sceneCount"])

    @property
    def ffmpeg_bin(self) -> str:
        return str(self.app["ffmpeg"]["bin"])

    @property
    def ffprobe_bin(self) -> str:
        return str(self.app["ffmpeg"]["probeBin"])

    def resolve(self, value: str | os.PathLike[str] | None) -> Path | None:
        """저장소 루트 기준 상대 경로를 절대 경로로 바꾼다."""
        if value in (None, ""):
            return None
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = self.repo_root / path
        return path

    def render_profile(self, mode: str) -> dict[str, Any]:
        """preview/final 프로파일이 적용된 render 설정을 반환한다."""
        profiles = self.render.get("profiles", {})
        if mode not in profiles:
            raise ConfigError(
                f"알 수 없는 렌더 모드입니다: {mode}",
                details=[f"config/render.json profiles 키: {sorted(profiles)}"],
            )
        merged = deep_merge(self.render, profiles[mode])
        merged.pop("profiles", None)
        merged["mode"] = mode
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "render": self.render,
            "tts": self.tts,
            "subtitle": self.subtitle,
            "i2v": self.i2v,
        }


def load_dotenv(path: Path) -> dict[str, str]:
    """.env를 읽어 os.environ에 없는 키만 채운다 (명세서 §26).

    의존성을 늘리지 않으려고 직접 파싱한다. `KEY=value` 형식만 지원하고
    `#`으로 시작하는 줄과 빈 줄은 건너뛴다.
    """
    if not path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def _apply_env_overrides(cfg: AppConfig) -> None:
    """환경 변수로 덮어쓸 수 있는 값을 반영한다."""
    comfy_url = os.environ.get("COMFYUI_BASE_URL")
    if comfy_url:
        cfg.i2v = deep_merge(cfg.i2v, {"comfyui": {"baseUrl": comfy_url}})


def load_config(config_dir: Path | None = None, *, repo_root: Path | None = None) -> AppConfig:
    """config 디렉터리에서 설정을 읽는다."""
    root = Path(repo_root) if repo_root else REPO_ROOT
    directory = Path(config_dir) if config_dir else root / "config"
    load_dotenv(root / ".env")
    loaded = {name: _read_json(directory / filename) for name, filename in CONFIG_FILES.items()}
    cfg = AppConfig(repo_root=root, **loaded)
    _validate(cfg)
    _apply_env_overrides(cfg)
    return cfg


def _validate(cfg: AppConfig) -> None:
    """설정에 최소한의 형식 검증을 건다."""
    problems: list[str] = []

    for key in ("sceneCount", "durationRange", "timeline", "ffmpeg"):
        if key not in cfg.app:
            problems.append(f"config/app.json에 '{key}'가 없습니다")
    for key in ("resolution", "fps", "profiles", "audio"):
        if key not in cfg.render:
            problems.append(f"config/render.json에 '{key}'가 없습니다")
    for key in ("engine", "engines"):
        if key not in cfg.tts:
            problems.append(f"config/tts.json에 '{key}'가 없습니다")
    for key in ("fontSize", "maxLines", "safeArea"):
        if key not in cfg.subtitle:
            problems.append(f"config/subtitle.json에 '{key}'가 없습니다")
    for key in ("workflowFile", "inject", "comfyui"):
        if key not in cfg.i2v:
            problems.append(f"config/i2v.json에 '{key}'가 없습니다")

    if problems:
        raise ConfigError("설정 파일이 올바르지 않습니다", details=problems)

    if cfg.render["resolution"].get("width", 0) <= 0 or cfg.render["resolution"].get("height", 0) <= 0:
        raise ConfigError("config/render.json resolution은 양수여야 합니다")
    if int(cfg.render.get("fps", 0)) <= 0:
        raise ConfigError("config/render.json fps는 양수여야 합니다")
