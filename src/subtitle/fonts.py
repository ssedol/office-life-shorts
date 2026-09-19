"""자막 폰트 해석 (명세서 §19, §35-3).

명세서 §35-3의 "자막 폰트"는 확정 항목이 아니므로, 특정 경로에 고정하지 않고
fontFile → fontCandidates → 시스템 폰트 순으로 찾는다.

중요한 점: ASS 파일의 Style에 적히는 폰트 **이름**과 실제로 찾은 폰트 **파일**이
가리키는 게 같아야 libass가 폰트를 찾는다. 설정의 fontName을 그대로 쓰면
운영체제마다 어긋난다 — 예를 들어 Linux에서 NanumGothic으로 맞춰 둔 설정을
Windows에서 돌리면 맑은 고딕(Malgun Gothic) 파일이 잡히는데 이름은 NanumGothic이라
libass가 못 찾고 한글이 깨진다. 그래서 찾은 파일에서 family 이름을 직접 읽는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

try:  # Pillow는 선택 의존성이다. 없으면 설정의 fontName을 그대로 쓴다.
    from PIL import ImageFont  # type: ignore
except Exception:  # pragma: no cover - 환경에 따라 다름
    ImageFont = None  # type: ignore


@dataclass
class ResolvedFont:
    """ASS에 쓸 폰트 이름과 libass에 넘길 폰트 폴더."""

    family: str
    #: libass의 fontsdir로 넘길 폴더. 시스템 폰트에 맡길 때는 None.
    directory: Path | None = None
    #: 실제로 찾은 폰트 파일. 못 찾았으면 None.
    path: Path | None = None

    @property
    def found(self) -> bool:
        return self.path is not None


def read_family_name(path: Path) -> str | None:
    """폰트 파일에서 family 이름을 읽는다. 실패하면 None."""
    if ImageFont is None:
        return None
    try:
        family, _style = ImageFont.truetype(str(path), 20).getname()
    except Exception as exc:  # 손상된 폰트, 지원하지 않는 형식 등
        log.debug("폰트 이름을 읽지 못했습니다: %s (%s)", path, exc)
        return None
    return family or None


def resolve_font(subtitle_cfg: dict) -> ResolvedFont:
    """설정에서 실제로 쓸 폰트를 정한다.

    fontFile → fontCandidates 순으로 첫 번째로 존재하는 파일을 쓰고,
    그 파일에서 읽은 family 이름을 ASS Style에 적는다.
    아무것도 못 찾으면 설정의 fontName으로 시스템 폰트에 맡긴다.
    """
    configured_name = str(subtitle_cfg.get("fontName") or "sans-serif")

    candidates: list[str] = []
    explicit = subtitle_cfg.get("fontFile")
    if explicit:
        candidates.append(str(explicit))
    candidates += [str(c) for c in (subtitle_cfg.get("fontCandidates") or [])]

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_file():
            continue

        family = read_family_name(path) or configured_name
        if family != configured_name:
            log.info(
                "자막 폰트: %s (설정의 '%s' 대신 실제 파일의 이름을 씁니다)",
                family, configured_name,
            )
        else:
            log.debug("자막 폰트: %s (%s)", family, path)
        return ResolvedFont(family=family, directory=path.parent, path=path)

    if explicit:
        log.warning("config/subtitle.json fontFile을 찾을 수 없습니다: %s", explicit)

    log.warning(
        "자막 폰트 파일을 찾지 못했습니다. 시스템에 설치된 '%s'에 맡깁니다. "
        "한글이 깨지면 config/subtitle.json의 fontFile에 한글 폰트 경로를 지정하세요",
        configured_name,
    )
    return ResolvedFont(family=configured_name)


def resolve_font_dir(subtitle_cfg: dict) -> Path | None:
    """libass에 넘길 fontsdir만 필요할 때 쓰는 단축 함수."""
    return resolve_font(subtitle_cfg).directory
