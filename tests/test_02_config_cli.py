"""설정 로딩과 CLI (명세서 §23, §24, §25)."""

from __future__ import annotations

import json

import pytest

from src.config import deep_merge, load_config
from src.errors import ConfigError, ErrorCode
from src.media.ffmpeg import FFmpeg, escape_filter_path
from tests.conftest import make_config, make_package


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_repo_config_loads(default_config):
    assert default_config.scene_count == 8
    assert (default_config.width, default_config.height) == (1080, 1920)
    assert default_config.fps == 30


def test_missing_config_file_is_reported(tmp_path):
    config_dir = make_config(tmp_path)
    (config_dir / "tts.json").unlink()

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_dir)
    assert exc_info.value.code == ErrorCode.CONFIG_INVALID


def test_broken_config_json_is_reported(tmp_path):
    config_dir = make_config(tmp_path)
    (config_dir / "render.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_dir)
    assert "render.json" in str(exc_info.value)


def test_missing_required_key_is_reported(tmp_path):
    config_dir = make_config(tmp_path)
    data = json.loads((config_dir / "app.json").read_text(encoding="utf-8"))
    del data["sceneCount"]
    (config_dir / "app.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_dir)
    assert any("sceneCount" in detail for detail in exc_info.value.details)


@pytest.mark.parametrize("mode,crf,preset", [("preview", 26, "veryfast"), ("final", 18, "slow")])
def test_render_profiles(default_config, mode, crf, preset):
    profile = default_config.render_profile(mode)
    assert profile["crf"] == crf
    assert profile["preset"] == preset
    assert profile["mode"] == mode
    assert "profiles" not in profile


def test_unknown_render_mode_is_rejected(default_config):
    with pytest.raises(ConfigError):
        default_config.render_profile("draft")


def test_deep_merge_ignores_none():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    assert deep_merge(base, {"a": None, "nested": {"y": 9}}) == {"a": 1, "nested": {"x": 1, "y": 9}}


def test_deep_merge_does_not_mutate_base():
    base = {"nested": {"x": 1}}
    deep_merge(base, {"nested": {"x": 2}})
    assert base == {"nested": {"x": 1}}


def test_relative_paths_resolve_against_repo_root(default_config):
    resolved = default_config.resolve("workflows/ltx25_i2v.json")
    assert resolved.is_absolute()
    assert resolved.is_file()


def test_absolute_paths_are_left_alone(default_config, tmp_path):
    assert default_config.resolve(str(tmp_path / "x.json")) == tmp_path / "x.json"


def test_none_path_resolves_to_none(default_config):
    assert default_config.resolve(None) is None


# ---------------------------------------------------------------------------
# ffmpeg 래퍼
# ---------------------------------------------------------------------------

def test_missing_ffmpeg_is_reported_with_install_hint():
    from src.errors import DependencyMissingError

    with pytest.raises(DependencyMissingError) as exc_info:
        FFmpeg("ffmpeg-없음", "ffprobe-없음").require()

    assert exc_info.value.code == ErrorCode.DEPENDENCY_MISSING
    assert any("apt-get" in detail for detail in exc_info.value.details)


@pytest.mark.parametrize("raw,expected", [
    ("/a/b.ass", "/a/b.ass"),
    ("C:/x/y.ass", "C\\:/x/y.ass"),
    ("/a/it's.ass", "/a/it\\'s.ass"),
    ("C:\\x\\y.ass", "C\\:\\\\x\\\\y.ass"),
])
def test_filter_path_escaping(raw, expected):
    assert escape_filter_path(raw) == expected


# ---------------------------------------------------------------------------
# CLI (명세서 §24)
# ---------------------------------------------------------------------------

def test_cli_parses_all_documented_options():
    from main import build_parser

    args = build_parser().parse_args([
        "--input", "./inputs/2026-09-18",
        "--mode", "final",
        "--skip-i2v",
        "--force",
    ])
    assert args.input == "./inputs/2026-09-18"
    assert args.mode == "final"
    assert args.skip_i2v is True
    assert args.force is True


def test_cli_defaults_to_preview():
    from main import build_parser

    args = build_parser().parse_args(["--input", "x"])
    assert args.mode == "preview"
    assert args.skip_i2v is False
    assert args.force is False


def test_cli_rejects_unknown_mode():
    from main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--input", "x", "--mode", "draft"])


def test_cli_requires_input():
    from main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_cli_returns_nonzero_on_pipeline_error(tmp_path, capsys):
    from main import main

    code = main(["--input", str(tmp_path / "없는폴더"), "--validate-only", "--quiet"])

    assert code == 1
    assert "ERR_INPUT_MISSING" in capsys.readouterr().err


def test_cli_validate_only_succeeds_on_sample(tmp_path, capsys):
    from main import main

    package = make_package(tmp_path / "in")
    code = main(["--input", str(package), "--validate-only", "--quiet"])

    assert code == 0
    assert "입력 검증 통과" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 저장소에 들어 있는 샘플 입력 (명세서 §10)
# ---------------------------------------------------------------------------

def test_bundled_sample_package_is_valid(repo_root, default_config):
    from src.loader.input_loader import load_input_package
    from src.validator.input_validator import validate

    package = load_input_package(repo_root / "inputs" / "2026-09-18")
    report = validate(package, default_config)

    assert report.ok, report.error_messages()
    assert len(package.scenes) == 8
    assert sum(1 for s in package.scenes if s.is_i2v) == 2  # 명세서 §9.3


def test_bundled_schemas_match_the_sample(repo_root):
    jsonschema = pytest.importorskip("jsonschema")

    sample = repo_root / "inputs" / "2026-09-18"
    for data_file, schema_file in (("project.json", "project.schema.json"),
                                   ("scene-plan.json", "scene-plan.schema.json")):
        data = json.loads((sample / data_file).read_text(encoding="utf-8"))
        schema = json.loads((repo_root / "schema" / schema_file).read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)


def test_bundled_workflow_is_api_format(repo_root, default_config):
    from src.i2v.comfy_ltx import ComfyUILTXProvider

    workflow = ComfyUILTXProvider(default_config.i2v, repo_root).load_workflow()
    assert all("class_type" in node for node in workflow.values())


def test_bundled_inject_mapping_matches_bundled_workflow(repo_root, default_config):
    """config/i2v.json의 매핑이 workflows/ltx25_i2v.json과 어긋나지 않아야 한다."""
    from src.i2v.comfy_ltx import ComfyUILTXProvider

    provider = ComfyUILTXProvider(default_config.i2v, repo_root)
    provider.inject(provider.load_workflow(), {
        "imagePath": "scene-01.png",
        "positivePrompt": "p",
        "negativePrompt": "n",
        "seed": 1,
        "width": 1080,
        "height": 1920,
        "frameCount": 121,
        "durationSec": 4.0,
        "fps": 30,
        "outputPrefix": "x",
    })


# ---------------------------------------------------------------------------
# .env / 환경 변수 (명세서 §26)
# ---------------------------------------------------------------------------

def test_dotenv_is_parsed(tmp_path, monkeypatch):
    from src.config import load_dotenv

    monkeypatch.delenv("SHORTS_TEST_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 주석\n\nSHORTS_TEST_KEY=hello\nexport SHORTS_QUOTED=\"world\"\n잘못된줄\n",
        encoding="utf-8",
    )

    loaded = load_dotenv(env_file)

    assert loaded["SHORTS_TEST_KEY"] == "hello"
    assert loaded["SHORTS_QUOTED"] == "world"
    assert "잘못된줄" not in loaded


def test_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    from src.config import load_dotenv

    monkeypatch.setenv("SHORTS_TEST_KEY", "이미있음")
    (tmp_path / ".env").write_text("SHORTS_TEST_KEY=덮어쓰기\n", encoding="utf-8")

    load_dotenv(tmp_path / ".env")
    import os
    assert os.environ["SHORTS_TEST_KEY"] == "이미있음"


def test_missing_dotenv_is_fine(tmp_path):
    from src.config import load_dotenv

    assert load_dotenv(tmp_path / ".env") == {}


def test_comfyui_base_url_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://gpu-box:9000")
    cfg = load_config(make_config(tmp_path))
    assert cfg.i2v["comfyui"]["baseUrl"] == "http://gpu-box:9000"
