"""YouTube 업로드 메타데이터 조립과 오류 처리 테스트 (명세서 §35-5, DEC-012).

실제 업로드는 하지 않는다. 구글 클라이언트를 가짜로 바꿔 끼워
videos.insert에 실려 나가는 본문이 맞는지만 확인한다.
"""

from __future__ import annotations

import json

import pytest

from src.errors import UploadError
from src.upload.metadata import (
    DESCRIPTION_LIMIT,
    TAGS_TOTAL_LIMIT,
    TITLE_LIMIT,
    UploadMetadata,
    load_metadata,
)

CONFIG = {
    "privacyStatus": "private",
    "categoryId": "22",
    "defaultTags": ["직장생활", "오늘도출근"],
    "hashtags": ["#직장생활", "#직장인공감"],
    "descriptionTemplate": "{hashtags}\n\n{body}\n\n{extraHashtags}",
}


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_제목은_upload_json이_project_json을_이긴다(tmp_path):
    _write(tmp_path, "upload.json", {"title": "회차 제목"})
    meta = load_metadata(tmp_path, CONFIG, {"title": "프로젝트 제목"})
    assert meta.title == "회차 제목"


def test_제목이_없으면_project_json에서_가져온다(tmp_path):
    meta = load_metadata(tmp_path, CONFIG, {"title": "프로젝트 제목"})
    assert meta.title == "프로젝트 제목"


def test_body만_있으면_템플릿으로_조립한다(tmp_path):
    _write(tmp_path, "upload.json", {"title": "t", "body": "본문", "extraHashtags": ["#a"]})
    meta = load_metadata(tmp_path, CONFIG, {})
    assert meta.description == "#직장생활 #직장인공감\n\n본문\n\n#a"


def test_description이_있으면_템플릿을_무시한다(tmp_path):
    _write(tmp_path, "upload.json", {"title": "t", "body": "무시됨", "description": "그대로"})
    meta = load_metadata(tmp_path, CONFIG, {})
    assert meta.description == "그대로"


def test_extraTags가_기본태그_뒤에_붙고_중복은_사라진다(tmp_path):
    _write(tmp_path, "upload.json", {"title": "t", "extraTags": ["오늘도출근", "신규"]})
    meta = load_metadata(tmp_path, CONFIG, {})
    assert meta.tags == ["직장생활", "오늘도출근", "신규"]


def test_공개설정_우선순위는_CLI가_가장_높다(tmp_path):
    _write(tmp_path, "upload.json", {"title": "t", "privacyStatus": "unlisted"})
    assert load_metadata(tmp_path, CONFIG, {}).privacy_status == "unlisted"
    meta = load_metadata(tmp_path, CONFIG, {}, privacy_override="public")
    assert meta.privacy_status == "public"


def test_기본_공개설정은_비공개다(tmp_path):
    """감사 전에는 유튜브가 어차피 비공개로 잠근다. 기본값이 그 사실과 맞아야 한다."""
    _write(tmp_path, "upload.json", {"title": "t"})
    assert load_metadata(tmp_path, CONFIG, {}).privacy_status == "private"


@pytest.mark.parametrize(
    "meta, 걸리는_말",
    [
        (UploadMetadata(title="", description=""), "제목이 비어"),
        (UploadMetadata(title="가" * (TITLE_LIMIT + 1), description=""), "제목이"),
        (UploadMetadata(title="t", description="가" * (DESCRIPTION_LIMIT + 1)), "설명이"),
        (UploadMetadata(title="t<b>", description=""), "< 또는 >"),
        (
            UploadMetadata(title="t", description="", tags=["가" * (TAGS_TOTAL_LIMIT + 1)]),
            "태그 총 길이",
        ),
    ],
)
def test_유튜브_제한을_넘으면_업로드_전에_막는다(meta, 걸리는_말):
    with pytest.raises(UploadError) as exc:
        meta.validate()
    assert 걸리는_말 in str(exc.value)


def test_태그_길이는_개수가_아니라_총_글자수로_잰다():
    """유튜브 제한은 쉼표를 포함한 총 길이다. 짧은 태그는 많아도 통과해야 한다."""
    UploadMetadata(title="t", description="", tags=["가나"] * 100).validate()


def test_잘못된_json은_읽는_시점에_안내와_함께_실패한다(tmp_path):
    (tmp_path / "upload.json").write_text("{깨진", encoding="utf-8")
    with pytest.raises(UploadError) as exc:
        load_metadata(tmp_path, CONFIG, {})
    assert "upload.json" in str(exc.value)


def test_upload_json이_없어도_동작한다(tmp_path):
    """회차 파일은 선택이다. 없으면 config와 project.json만으로 굴러가야 한다."""
    meta = load_metadata(tmp_path, CONFIG, {"title": "제목만"})
    assert meta.title == "제목만"
    assert meta.tags == ["직장생활", "오늘도출근"]
    assert meta.comment is None
