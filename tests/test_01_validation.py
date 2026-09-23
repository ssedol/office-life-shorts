"""TEST-1 입력 검증 / TEST-2 씬 수 (명세서 §28, §14)."""

from __future__ import annotations

import json

import pytest

from src.errors import (
    ErrorCode,
    InputMissingError,
    InvalidSceneTypeError,
    SceneCountError,
    SceneImageMissingError,
)
from src.loader.input_loader import load_input_package
from src.validator.input_validator import validate, validate_or_raise
from tests.conftest import make_package


# ---------------------------------------------------------------------------
# TEST-1 누락 파일 감지
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["project.json", "scene-plan.json", "script.txt"])
def test_missing_required_file_is_detected(tmp_path, missing):
    root = make_package(tmp_path / "in", drop_files=[missing])

    with pytest.raises(InputMissingError) as exc_info:
        load_input_package(root)

    assert exc_info.value.code == ErrorCode.INPUT_MISSING
    assert any(missing in detail for detail in exc_info.value.details)


def test_missing_input_dir_is_detected(tmp_path):
    with pytest.raises(InputMissingError):
        load_input_package(tmp_path / "없는폴더")


def test_broken_json_reports_line_number(tmp_path):
    root = make_package(tmp_path / "in")
    (root / "scene-plan.json").write_text('{"scenes": [ }', encoding="utf-8")

    with pytest.raises(InputMissingError) as exc_info:
        load_input_package(root)
    assert "scene-plan.json" in str(exc_info.value)


def test_missing_scene_image_is_detected(tmp_path, fast_config):
    root = make_package(tmp_path / "in", skip_images=[3])
    package = load_input_package(root)

    with pytest.raises(SceneImageMissingError) as exc_info:
        validate_or_raise(package, fast_config)

    assert exc_info.value.code == ErrorCode.SCENE_IMAGE_MISSING
    assert any("scene-03.png" in detail for detail in exc_info.value.details)


def test_all_eight_images_required(tmp_path, fast_config):
    root = make_package(tmp_path / "in", skip_images=[1, 4, 8])
    report = validate(load_input_package(root), fast_config)

    image_errors = [msg for code, msg in report.errors if code == ErrorCode.SCENE_IMAGE_MISSING]
    assert len(image_errors) == 3


def test_empty_script_is_rejected(tmp_path, fast_config):
    root = make_package(tmp_path / "in")
    (root / "script.txt").write_text("   \n", encoding="utf-8")

    report = validate(load_input_package(root), fast_config)
    assert not report.ok
    assert any("script.txt" in msg for _, msg in report.errors)


def test_valid_package_passes(tmp_path, fast_config):
    report = validate(load_input_package(make_package(tmp_path / "in")), fast_config)
    assert report.ok, report.error_messages()


# ---------------------------------------------------------------------------
# TEST-2 씬 수는 항상 8
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count", [0, 1, 7, 9, 16])
def test_scene_count_must_be_eight(tmp_path, fast_config, count):
    root = make_package(tmp_path / "in", scene_count=count)
    package = load_input_package(root)

    with pytest.raises(SceneCountError) as exc_info:
        validate_or_raise(package, fast_config)

    assert exc_info.value.code == ErrorCode.SCENE_COUNT
    assert any(str(count) in detail for detail in exc_info.value.details)


def test_project_scene_count_mismatch_is_detected(tmp_path, fast_config):
    root = make_package(tmp_path / "in")
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    data["sceneCount"] = 6
    (root / "project.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    report = validate(load_input_package(root), fast_config)
    assert any(code == ErrorCode.SCENE_COUNT for code, _ in report.errors)


def test_duplicate_order_is_detected(tmp_path, fast_config):
    root = make_package(tmp_path / "in", scene_overrides={3: {"order": 2}})
    report = validate(load_input_package(root), fast_config)
    assert any("order" in msg and "중복" in msg for _, msg in report.errors)


# ---------------------------------------------------------------------------
# type / videoPrompt / durationSec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_type", ["ANIMATE", "still_", "", "VIDEO", "i2 v"])
def test_invalid_scene_type_is_rejected(tmp_path, fast_config, bad_type):
    root = make_package(tmp_path / "in", scene_overrides={4: {"type": bad_type}})
    package = load_input_package(root)

    with pytest.raises(InvalidSceneTypeError) as exc_info:
        validate_or_raise(package, fast_config)
    assert exc_info.value.code == ErrorCode.INVALID_SCENE_TYPE


def test_lowercase_type_is_accepted(tmp_path, fast_config):
    """type은 대소문자를 구분하지 않고 정규화한다."""
    root = make_package(tmp_path / "in", scene_overrides={4: {"type": "still"}})
    report = validate(load_input_package(root), fast_config)
    assert report.ok, report.error_messages()


def test_i2v_without_video_prompt_is_rejected(tmp_path, fast_config):
    root = make_package(tmp_path / "in", scene_overrides={2: {"videoPrompt": ""}})
    report = validate(load_input_package(root), fast_config)

    assert not report.ok
    assert any("videoPrompt" in msg for _, msg in report.errors)


def test_still_scene_does_not_need_video_prompt(tmp_path, fast_config):
    root = make_package(tmp_path / "in")
    report = validate(load_input_package(root), fast_config)
    assert report.ok, report.error_messages()


@pytest.mark.parametrize("duration", [0, -1, -0.5])
def test_non_positive_duration_is_rejected(tmp_path, fast_config, duration):
    root = make_package(tmp_path / "in", scene_overrides={5: {"durationSec": duration}})
    report = validate(load_input_package(root), fast_config)

    assert not report.ok
    assert any("durationSec" in msg for _, msg in report.errors)


def test_unknown_motion_is_rejected(tmp_path, fast_config):
    root = make_package(tmp_path / "in", scene_overrides={3: {"motion": "spin"}})
    report = validate(load_input_package(root), fast_config)
    assert any(code == ErrorCode.INVALID_SCENE_TYPE for code, _ in report.errors)


def test_all_errors_are_reported_at_once(tmp_path, fast_config):
    """명세서 §14 — 누락/오류 항목을 명확히 출력한다. 첫 오류에서 멈추지 않는다."""
    root = make_package(
        tmp_path / "in",
        skip_images=[7],
        scene_overrides={2: {"videoPrompt": ""}, 4: {"type": "NOPE"}, 5: {"durationSec": 0}},
    )
    report = validate(load_input_package(root), fast_config)

    codes = {code for code, _ in report.errors}
    assert ErrorCode.SCENE_IMAGE_MISSING in codes
    assert ErrorCode.INVALID_SCENE_TYPE in codes
    assert ErrorCode.INPUT_MISSING in codes
    assert len(report.errors) >= 4


def test_i2v_ratio_outside_recommendation_only_warns(tmp_path, fast_config):
    """명세서 §9.3 권장 비율(2~3씬)은 경고일 뿐 실패가 아니다."""
    root = make_package(
        tmp_path / "in",
        scene_overrides={
            order: {"type": "I2V", "videoPrompt": "subtle blink"} for order in (1, 2, 3, 4, 5)
        },
    )
    report = validate(load_input_package(root), fast_config)

    assert report.ok, report.error_messages()
    assert any("§9.3" in w or "권장" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# 댓글 유도 문구 (config/app.json cta)
# ---------------------------------------------------------------------------

def _cta_warnings(report, scene_id: str) -> list[str]:
    return [w for w in report.warnings if w.startswith(f"{scene_id}:") and "댓글 유도" in w]


def test_missing_cta_warns_for_last_scene_and_early_range(tmp_path, fast_config):
    """마지막 씬은 반드시, 앞쪽은 '범위 안 어딘가'로 본다 (2026-09-21 개정).

    예전에는 1번 씬을 콕 집어 요구했는데, 사건을 꺼내기도 전에 공감을 물으면
    가리킬 대상이 없는 빈 질문이 된다. 그래서 앞쪽은 범위로만 확인한다.
    """
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "오늘 얘기할 건요.", "subtitle": "시작"},
        8: {"narration": "오늘은 여기까지입니다.", "subtitle": "끝"},
    })
    report = validate(load_input_package(root), fast_config)

    assert report.ok, "댓글 유도는 권고지 필수가 아니다"
    assert _cta_warnings(report, "SCENE-08")
    assert any("앞쪽" in w for w in report.warnings)
    assert not _cta_warnings(report, "SCENE-01"), "1번 씬을 콕 집어 요구하지 않는다"


def test_cta_in_hook_only_still_warns_for_the_last_scene(tmp_path, fast_config):
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "여러분도 해보셨죠?"},
        8: {"narration": "오늘은 여기까지입니다.", "subtitle": "끝"},
    })
    report = validate(load_input_package(root), fast_config)

    assert not _cta_warnings(report, "SCENE-01")
    assert _cta_warnings(report, "SCENE-08")


def test_cta_in_both_places_passes_clean(tmp_path, fast_config):
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "이 말 해보셨죠?"},
        8: {"narration": "여러분은 어떻게 말하세요?"},
    })
    report = validate(load_input_package(root), fast_config)

    assert not [w for w in report.warnings if "댓글 유도" in w]


@pytest.mark.parametrize("narration,subtitle", [
    ("여러분은 이럴 때 어떻게 말하세요?", "끝"),
    ("오늘은 여기까지입니다.", "**여러분은** 어떠세요?"),
    ("비슷한 경험 있나요?", "끝"),
    ("저만 그런가요?", "끝"),
    ("댓글로 알려주세요.", "끝"),
    ("이 말 해보셨죠?", "끝"),
])
def test_cta_is_detected_in_narration_or_subtitle(tmp_path, fast_config, narration, subtitle):
    root = make_package(tmp_path / "in", scene_overrides={8: {"narration": narration, "subtitle": subtitle}})
    report = validate(load_input_package(root), fast_config)

    assert not _cta_warnings(report, "SCENE-08"), f"{narration!r} / {subtitle!r}"


def test_middle_scene_cta_satisfies_the_early_requirement(tmp_path, fast_config):
    """중간 씬의 질문이 앞쪽 요구를 채운다 (2026-09-21 개정).

    예전에는 중간 씬을 무시하고 1번 씬만 인정했다. 3편에서 사건이 끝나는
    6번 씬에 댓글 유도를 넣는 게 자연스럽다는 게 확인돼 범위 방식으로 바꿨다.
    """
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "시작합니다.", "subtitle": "시작"},
        4: {"narration": "여러분은 어떻게 하세요?"},
        8: {"narration": "오늘은 여기까지입니다.", "subtitle": "끝"},
    })
    report = validate(load_input_package(root), fast_config)

    assert not any("앞쪽" in w for w in report.warnings), "4번 씬이 앞쪽 요구를 채운다"
    assert _cta_warnings(report, "SCENE-08"), "마지막 씬은 여전히 필요하다"


def test_cta_scenes_can_target_the_last_scene_only(tmp_path, fast_config):
    from src.config import deep_merge

    # earlyWithin까지 꺼야 마지막 씬만 보는 설정이 된다.
    fast_config.app = deep_merge(
        fast_config.app, {"cta": {"scenes": ["last"], "earlyWithin": 0}}
    )
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "시작합니다.", "subtitle": "시작"},
        8: {"narration": "여러분은 어떻게 하세요?"},
    })
    report = validate(load_input_package(root), fast_config)

    assert not [w for w in report.warnings if "댓글 유도" in w]


def test_cta_check_can_be_disabled(tmp_path, fast_config):
    from src.config import deep_merge

    fast_config.app = deep_merge(fast_config.app, {"cta": {"required": False}})
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "시작.", "subtitle": "시작"},
        8: {"narration": "끝.", "subtitle": "끝"},
    })
    report = validate(load_input_package(root), fast_config)

    assert not [w for w in report.warnings if "댓글 유도" in w]


def test_early_cta_hint_mentions_keeping_the_subtitle(tmp_path, fast_config):
    """앞쪽 경고는 '자막은 그대로 두라'는 조언을 담아야 한다.

    훅에 댓글 유도를 넣을 때 자막까지 질문으로 바꾸면 훅이 약해진다.
    예전에는 1번 씬 경고가 이 조언을 달았는데, 범위 방식으로 바뀌면서 옮겼다.
    """
    root = make_package(tmp_path / "in", scene_overrides={
        i: {"narration": "그냥 진행합니다.", "subtitle": "진행"} for i in range(1, 7)
    })
    report = validate(load_input_package(root), fast_config)

    early = [w for w in report.warnings if "앞쪽" in w]
    assert early, "앞쪽 6개 씬에 댓글 유도가 없으면 경고해야 한다"
    assert any("자막은 그대로" in w for w in early)


def test_bundled_sample_has_cta_in_both_places(repo_root, default_config):
    """저장소 샘플은 훅과 마무리 양쪽에 댓글 유도를 갖춰야 한다."""
    package = load_input_package(repo_root / "inputs" / "2026-09-18")
    report = validate(package, default_config)

    assert not [w for w in report.warnings if "댓글 유도" in w], report.warnings


# ---------------------------------------------------------------------------
# 어미 반복 (config/app.json script.maxSameEndingScenes / maxPlainPoliteScenes)
# ---------------------------------------------------------------------------

def _ending_warnings(report) -> list[str]:
    return [w for w in report.warnings if "어미가 반복" in w or "평서문이" in w]


def test_same_ending_in_every_scene_warns(tmp_path, fast_config):
    """5편 초안이 8개 씬 전부 '~어요'로 끝나 단조롭다는 지적을 받았다 (2026-09-23).

    문어체 어미 검사는 '~습니다'만 보기 때문에 이런 대본이 그대로 통과했다.
    """
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "팀장님 흉을 보냈어요."},
        2: {"narration": "삭제 버튼을 눌렀어요."},
        3: {"narration": "이미 읽고 난 뒤였어요."},
        4: {"narration": "카톡이 하나 왔어요."},
        5: {"narration": "한마디로 답장했어요."},
        6: {"narration": "여러분도 식은땀 흘려보셨죠?"},
        7: {"narration": "급하면 아직도 그냥 눌러요."},
        8: {"narration": "여러분은 어떠세요? 댓글로 알려주세요."},
    })
    report = validate(load_input_package(root), fast_config)

    assert report.ok, "문체는 권고지 필수가 아니다"
    repeated = [w for w in report.warnings if "'~어요'로 끝나는" in w]
    assert repeated, report.warnings
    assert "SCENE-01" in repeated[0] and "SCENE-05" in repeated[0]


def test_mixed_endings_pass_clean(tmp_path, fast_config):
    """명사 종결·'~거든요'·'~죠'를 섞으면 경고하지 않는다."""
    root = make_package(tmp_path / "in", scene_overrides={
        1: {"narration": "팀장님 흉을 보냈거든요. 근데 보낸 데가 팀 전체 단톡방."},
        2: {"narration": '"아 취소, 취소!" 손이 먼저 나갔어요. 삭제 누르고 또 누르고.'},
        3: {"narration": "근데 이미 읽음 표시. 팀장님이 제일 먼저 보신 거예요."},
        4: {"narration": "5분 뒤에 카톡이 왔는데, 딱 한 글자. 물음표."},
        5: {"narration": '그래서 저도 한 글자로 답했죠. "넵!"'},
        6: {"narration": "여러분도 있으시죠? 단톡방 잘못 보내서 식은땀 난 적."},
        7: {"narration": "요즘은 방 이름부터 봐요. 급하면? 그냥 누르죠 뭐."},
        8: {"narration": "여러분은 무슨 사고 쳐보셨어요? 댓글 좀 풀어주세요."},
    })
    report = validate(load_input_package(root), fast_config)

    assert not _ending_warnings(report), report.warnings


def test_plain_polite_declaratives_are_counted_without_questions(tmp_path, fast_config):
    """'~요?'로 되묻는 문장은 평서문으로 세지 않는다."""
    root = make_package(tmp_path / "in", scene_overrides={
        i: {"narration": f"{i}번은 이렇게 물어요?"} for i in range(1, 9)
    })
    report = validate(load_input_package(root), fast_config)

    assert not [w for w in report.warnings if "평서문이" in w], report.warnings


def test_ending_variety_check_can_be_disabled(tmp_path, fast_config):
    from src.config import deep_merge

    fast_config.app = deep_merge(
        fast_config.app,
        {"script": {"maxSameEndingScenes": 0, "maxPlainPoliteScenes": 0}},
    )
    root = make_package(tmp_path / "in", scene_overrides={
        i: {"narration": f"{i}번째 씬을 진행했어요."} for i in range(1, 9)
    })
    report = validate(load_input_package(root), fast_config)

    assert not _ending_warnings(report), report.warnings


def test_episode_five_script_passes_the_ending_check(repo_root, default_config):
    """운영자 지적으로 다시 쓴 5편 대본이 기준을 지키는지 본다."""
    package = load_input_package(repo_root / "inputs" / "2026-09-24")
    report = validate(package, default_config)

    assert not _ending_warnings(report), report.warnings
