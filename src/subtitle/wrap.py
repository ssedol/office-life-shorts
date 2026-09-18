"""자막 줄바꿈과 강조 마크업 파싱 (명세서 §19, §27).

명세서 §19는 자막을 "최대 2줄, 가운데 정렬, 중요 단어는 노란색"으로 규정한다.
scene-plan.json에는 강조 단어를 담을 필드가 없으므로, subtitle 문자열 안에
config/subtitle.json의 emphasisMarkup(기본 "**")으로 감싸는 방식을 쓴다.

    "subtitle": "이 말 먼저 하면 **손해**"

마크업이 없으면 전부 기본색(흰색)이 되므로, 기존 입력과도 호환된다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: 한글/한자/가나 등 전각 문자는 1.0, 그 외는 0.55로 폭을 센다.
NARROW_WIDTH = 0.55


@dataclass
class Segment:
    """한 줄 안에서 색이 같은 연속 구간."""

    text: str
    emphasis: bool


@dataclass
class Line:
    segments: list[Segment]

    @property
    def text(self) -> str:
        return "".join(seg.text for seg in self.segments)

    @property
    def width(self) -> float:
        return display_width(self.text)


@dataclass
class Layout:
    lines: list[Line]
    overflow: bool
    """maxLines를 넘겼는지 여부. 넘쳤으면 호출 측이 폰트를 줄여 다시 시도한다."""

    @property
    def plain(self) -> str:
        return "\n".join(line.text for line in self.lines)


def char_width(ch: str) -> float:
    """한 글자의 표시 폭(전각=1.0 기준)."""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    return NARROW_WIDTH


def display_width(text: str) -> float:
    return sum(char_width(ch) for ch in text)


def parse_emphasis(text: str, markup: str = "**") -> tuple[str, list[tuple[int, int]]]:
    """마크업을 제거한 평문과, 평문 기준 강조 구간 [start, end) 목록을 돌려준다."""
    if not markup:
        return text, []

    token = re.escape(markup)
    pattern = re.compile(f"{token}(.+?){token}", re.DOTALL)

    plain_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    length = 0

    for match in pattern.finditer(text):
        before = text[cursor:match.start()]
        plain_parts.append(before)
        length += len(before)

        inner = match.group(1)
        spans.append((length, length + len(inner)))
        plain_parts.append(inner)
        length += len(inner)
        cursor = match.end()

    plain_parts.append(text[cursor:])
    return "".join(plain_parts), spans


def _is_emphasized(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in spans)


def _segments_for(plain: str, spans: list[tuple[int, int]], start: int, end: int) -> list[Segment]:
    """평문의 [start, end) 구간을 강조 여부가 같은 덩어리로 쪼갠다."""
    segments: list[Segment] = []
    for index in range(start, end):
        emph = _is_emphasized(index, spans)
        if segments and segments[-1].emphasis == emph:
            segments[-1].text += plain[index]
        else:
            segments.append(Segment(plain[index], emph))
    return segments


def _tokenize(plain: str) -> list[tuple[int, int]]:
    """공백을 기준으로 단어 구간 [start, end)를 뽑는다(공백 제외)."""
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", plain)]


def _greedy_breaks(plain: str, max_width: float) -> list[tuple[int, int]]:
    """탐욕적으로 줄을 채운다. 반환값은 줄 구간 [start, end) 목록."""
    tokens = _tokenize(plain)
    if not tokens:
        return []

    lines: list[tuple[int, int]] = []
    line_start = tokens[0][0]
    line_end = tokens[0][1]

    for start, end in tokens[1:]:
        candidate_width = display_width(plain[line_start:end])
        if candidate_width <= max_width:
            line_end = end
        else:
            lines.append((line_start, line_end))
            line_start, line_end = start, end
    lines.append((line_start, line_end))

    # 한 단어가 통째로 max_width를 넘으면 강제로 쪼갠다.
    result: list[tuple[int, int]] = []
    for start, end in lines:
        if display_width(plain[start:end]) <= max_width:
            result.append((start, end))
            continue
        cursor = start
        while cursor < end:
            width = 0.0
            cut = cursor
            while cut < end:
                width += char_width(plain[cut])
                if width > max_width and cut > cursor:
                    break
                cut += 1
            result.append((cursor, cut))
            cursor = cut
    return result


def _rebalance_two(plain: str, max_width: float) -> list[tuple[int, int]] | None:
    """2줄일 때 두 줄 길이가 비슷해지는 분할점을 찾는다."""
    tokens = _tokenize(plain)
    if len(tokens) < 2:
        return None

    text_start, text_end = tokens[0][0], tokens[-1][1]
    best: tuple[float, list[tuple[int, int]]] | None = None

    for index in range(1, len(tokens)):
        first = (text_start, tokens[index - 1][1])
        second = (tokens[index][0], text_end)
        w1 = display_width(plain[first[0]:first[1]])
        w2 = display_width(plain[second[0]:second[1]])
        if w1 > max_width or w2 > max_width:
            continue
        score = abs(w1 - w2)
        if best is None or score < best[0]:
            best = (score, [first, second])

    return best[1] if best else None


def layout_text(
    text: str,
    *,
    max_width: float,
    max_lines: int = 2,
    markup: str = "**",
    keywords: list[str] | None = None,
) -> Layout:
    """자막 한 개를 줄 단위 레이아웃으로 만든다."""
    plain, spans = parse_emphasis(text, markup)
    plain = re.sub(r"[ \t]+", " ", plain.replace("\n", " ")).strip()

    if not plain:
        return Layout(lines=[], overflow=False)

    # 마크업 대신 키워드 목록으로도 강조할 수 있게 한다.
    for keyword in keywords or []:
        if not keyword:
            continue
        for match in re.finditer(re.escape(keyword), plain):
            spans.append((match.start(), match.end()))

    breaks = _greedy_breaks(plain, max_width)

    if len(breaks) == 2:
        balanced = _rebalance_two(plain, max_width)
        if balanced:
            breaks = balanced
    elif len(breaks) == 1 and max_lines >= 2:
        pass  # 한 줄에 들어가면 그대로 둔다.

    lines = [Line(_segments_for(plain, spans, start, end)) for start, end in breaks]
    return Layout(lines=lines, overflow=len(lines) > max_lines)
