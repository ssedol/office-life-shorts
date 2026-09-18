"""자막 폰트 해석 (명세서 §19, §35-3).

명세서 §35-3의 "자막 폰트"는 아직 확정 항목이 아니므로, 특정 경로에 고정하지 않고
config/subtitle.json의 fontFile → fontCandidates → 시스템 fontconfig 순으로 찾는다.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def resolve_font_dir(subtitle_cfg: dict) -> Path | None:
    """libass에 넘길 fontsdir를 정한다. 못 찾으면 None(시스템 폰트에 맡김)."""
    explicit = subtitle_cfg.get("fontFile")
    if explicit:
        path = Path(str(explicit)).expanduser()
        if path.is_file():
            return path.parent
        log.warning("config/subtitle.json fontFile을 찾을 수 없습니다: %s", path)

    for candidate in subtitle_cfg.get("fontCandidates") or []:
        path = Path(str(candidate)).expanduser()
        if path.is_file():
            log.debug("자막 폰트: %s", path)
            return path.parent

    log.warning(
        "자막 폰트 파일을 찾지 못했습니다. 시스템에 설치된 '%s'를 사용합니다. "
        "글자가 깨지면 config/subtitle.json의 fontFile에 한글 폰트 경로를 지정하세요",
        subtitle_cfg.get("fontName", "(미지정)"),
    )
    return None
