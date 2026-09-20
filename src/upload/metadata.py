"""업로드 메타데이터 조립 (제목 / 설명 / 태그 / 첫 댓글).

우선순위는 파이프라인의 다른 설정과 같다: inputs/<날짜>/upload.json > config/upload.json.
제목만은 upload.json에 없으면 project.json의 title을 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import UploadError

#: 유튜브 제한값. 넘으면 API가 400을 주므로 미리 잡는다.
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
TAGS_TOTAL_LIMIT = 500


@dataclass
class UploadMetadata:
    """videos.insert에 실어 보낼 값 + 업로드 후 달 첫 댓글."""

    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    category_id: str = "22"
    privacy_status: str = "private"
    made_for_kids: bool = False
    comment: str | None = None

    def validate(self) -> None:
        """유튜브 제한을 넘는지 미리 확인한다."""
        problems: list[str] = []
        if not self.title.strip():
            problems.append("제목이 비어 있습니다")
        if len(self.title) > TITLE_LIMIT:
            problems.append(f"제목이 {len(self.title)}자입니다 (최대 {TITLE_LIMIT}자)")
        if len(self.description) > DESCRIPTION_LIMIT:
            problems.append(
                f"설명이 {len(self.description)}자입니다 (최대 {DESCRIPTION_LIMIT}자)"
            )
        # 태그는 개수가 아니라 쉼표 포함 총 길이로 제한된다.
        total = sum(len(t) for t in self.tags) + max(len(self.tags) - 1, 0)
        if total > TAGS_TOTAL_LIMIT:
            problems.append(f"태그 총 길이가 {total}자입니다 (최대 {TAGS_TOTAL_LIMIT}자)")
        if "<" in self.title or ">" in self.title:
            problems.append("제목에 < 또는 > 를 쓸 수 없습니다")
        if problems:
            raise UploadError("업로드 메타데이터가 유튜브 제한을 벗어납니다", details=problems)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise UploadError(f"{path.name}을 읽을 수 없습니다: {exc}") from exc


def _render_description(episode: dict, config: dict) -> str:
    """설명란을 조립한다.

    upload.json에 description이 통째로 있으면 그대로 쓴다.
    body만 있으면 config의 템플릿에 해시태그와 함께 끼워 넣는다.
    """
    explicit = episode.get("description")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    body = str(episode.get("body") or "").strip()
    if not body:
        return ""

    hashtags = episode.get("hashtags") or config.get("hashtags") or []
    extra = episode.get("extraHashtags") or []
    template = str(config.get("descriptionTemplate") or "{hashtags}\n\n{body}\n\n{extraHashtags}")
    text = template.format(
        hashtags=" ".join(hashtags),
        body=body,
        extraHashtags=" ".join(extra),
    )
    # 해시태그가 비면 빈 줄만 남으므로 정리한다.
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def load_metadata(
    input_dir: Path,
    config: dict,
    project: dict,
    *,
    privacy_override: str | None = None,
) -> UploadMetadata:
    """inputs/<날짜>/upload.json과 config/upload.json을 합쳐 메타데이터를 만든다."""
    episode = _read_json(input_dir / "upload.json")

    title = str(episode.get("title") or project.get("title") or "").strip()

    tags = episode.get("tags")
    if tags is None:
        tags = config.get("defaultTags") or []
    # 회차 태그를 기본 태그 뒤에 붙이고 싶을 때 쓴다.
    tags = list(tags) + list(episode.get("extraTags") or [])
    # 중복은 조용히 걷어낸다. 순서는 유지한다.
    seen: set[str] = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    privacy = (
        privacy_override
        or episode.get("privacyStatus")
        or config.get("privacyStatus")
        or "private"
    )

    meta = UploadMetadata(
        title=title,
        description=_render_description(episode, config),
        tags=tags,
        category_id=str(episode.get("categoryId") or config.get("categoryId") or "22"),
        privacy_status=str(privacy),
        made_for_kids=bool(
            episode.get("madeForKids", config.get("madeForKids", False))
        ),
        comment=(episode.get("comment") or "").strip() or None,
    )
    meta.validate()
    return meta
