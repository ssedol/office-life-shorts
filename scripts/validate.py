#!/usr/bin/env python3
"""대본 검수 게이트.

사람이 쓰든 LLM이 쓰든, 이 스크립트를 통과하지 못하면 제작 단계로 넘어가지 않는다.
자동화 파이프라인에서는 03_script → 04_validate 단계가 이 파일이다.

  ./scripts/validate.py output/0001.json
  ./scripts/validate.py output/*.json

종료 코드: 0 = 통과, 1 = FAIL 있음
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CH = yaml.safe_load((ROOT / "config" / "channel.yaml").read_text(encoding="utf-8"))
AX = yaml.safe_load((ROOT / "config" / "axes.yaml").read_text(encoding="utf-8"))

C = CH["constraints"]
BLOCK_IDS = [b["id"] for b in AX["structure"]]


# 구두점은 발음되지 않으므로 길이 계산에서 제외한다.
_NOT_SPOKEN = re.compile(r"[\s,.?!…·~\"'“”‘’()\[\]]")


def n_chars(text: str) -> int:
    """발음되는 글자수. 공백과 구두점을 뺀 값이 나레이션 길이의 기준."""
    return len(_NOT_SPOKEN.sub("", text))


def check(script: dict) -> list[tuple[str, str, str]]:
    """(level, code, message) 목록을 돌려준다. level: FAIL | WARN"""
    out: list[tuple[str, str, str]] = []
    fail = lambda c, m: out.append(("FAIL", c, m))
    warn = lambda c, m: out.append(("WARN", c, m))

    blocks = {b["id"]: b for b in script.get("blocks", [])}
    narration = " ".join(b.get("narration", "") for b in script.get("blocks", []))

    # 1. 축이 활성 상태인가
    axis = script.get("axis")
    if not AX["axes"].get(axis, {}).get("active"):
        fail("axis.inactive", f"축 {axis} 는 현재 비활성이다 (config/axes.yaml)")

    # 2. 블록 구조
    missing = [b for b in BLOCK_IDS if b not in blocks]
    if missing:
        fail("blocks.missing", f"빠진 블록: {', '.join(missing)}")
    order = [b["id"] for b in script.get("blocks", [])]
    if order and order != BLOCK_IDS:
        fail("blocks.order", f"블록 순서가 다르다: {order}")

    # 3. 분량
    n = n_chars(narration)
    lo, hi = C["narration_chars"]["min"], C["narration_chars"]["max"]
    if n < lo:
        fail("length.short", f"{n}자 — {lo}자 미만. BODY 디테일을 늘려라")
    elif n > hi:
        fail("length.long", f"{n}자 — {hi}자 초과. SETUP부터 깎아라")
    est = round(n / C["chars_per_sec"], 1)
    if not (C["duration_sec"]["min"] <= est <= C["duration_sec"]["max"]):
        warn("length.duration", f"예상 {est}초 — 목표 구간 밖")

    # 4. 금지어
    for p in CH["banned_phrases"]:
        if p in narration:
            fail("banned.phrase", f"금지어 '{p}' 가 나레이션에 있다")

    # 5. HOOK 검사
    hook = blocks.get("HOOK", {}).get("narration", "")
    if hook:
        hn = n_chars(hook)
        if hn > C["hook_max_chars"]:
            fail("hook.long", f"HOOK {hn}자 — 최대 {C['hook_max_chars']}자. 3초를 넘긴다")
        markers = CH["hook_concreteness_markers"]
        hit = [k for k, vals in markers.items() if any(v in hook for v in vals)]
        if not hit:
            fail("hook.abstract",
                 "HOOK에 구체적 시간/직급/장소가 없다. 추상어를 구체어로 바꿔라")
        for bad in yaml.safe_load((ROOT / "config" / "hooks.yaml").read_text(encoding="utf-8"))["forbidden_openings"]:
            if isinstance(bad, str) and hook.startswith(bad):
                fail("hook.forbidden", f"금지된 도입: '{bad}'")

    # 6. 후킹 후보
    cands = script.get("hook_candidates", [])
    if len(cands) < C["hook_candidates_min"]:
        fail("hook.candidates", f"후보 {len(cands)}개 — {C['hook_candidates_min']}개 이상 필요")
    ci = script.get("hook_chosen", -1)
    if not (0 <= ci < len(cands)):
        fail("hook.chosen", f"hook_chosen 인덱스가 범위 밖: {ci}")
    elif cands[ci]["text"].strip() != hook.strip():
        warn("hook.mismatch", "채택한 후보와 HOOK 나레이션이 다르다")

    # 7. CTA — 질문으로 끝나야 한다
    cta = blocks.get("CTA", {}).get("narration", "")
    if cta and "?" not in cta:
        fail("cta.not_question", "CTA가 질문이 아니다. 댓글 전환이 안 된다")

    # 8. 업로드 메타
    meta = script.get("meta", {})
    title = meta.get("title", "")
    if len(title) > C["title_max_chars"]:
        fail("meta.title_long", f"제목 {len(title)}자 — {C['title_max_chars']}자 초과 시 잘린다")
    tags = meta.get("hashtags", [])
    h = C["hashtags"]
    if not (h["min"] <= len(tags) <= h["max"]):
        fail("meta.hashtags", f"해시태그 {len(tags)}개 — {h['min']}~{h['max']}개여야 한다")
    for req in h["required"]:
        if req not in tags:
            fail("meta.hashtag_required", f"{req} 누락")
    tt = meta.get("thumbnail_text", "")
    t = C["thumbnail_text_chars"]
    if tt and not (t["min"] <= len(tt.replace(" ", "")) <= t["max"]):
        warn("meta.thumbnail", f"썸네일 텍스트 {len(tt)}자 — 그리드에서 안 읽힌다")

    # 9. 안전 — 자동화에서 가장 중요한 게이트
    prod = script.get("production", {})
    if CH["safety"]["require_ai_disclosure_if_synthetic"]:
        if (prod.get("synthetic_voice") or prod.get("synthetic_visual")) \
           and not meta.get("ai_disclosure"):
            fail("safety.ai_disclosure",
                 "합성 음성/영상을 쓰면서 AI 고지 설정이 없다")
    if not prod.get("human_elements"):
        warn("safety.templated",
             "human_elements 가 비었다 — 사람 고유 요소 없는 템플릿 영상은 "
             "YouTube 'inauthentic content' 판정 위험")

    return out


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    worst = 0
    for p in paths:
        try:
            script = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"✗ {p.name}: 읽기 실패 — {e}")
            worst = 1
            continue
        results = check(script)
        fails = [r for r in results if r[0] == "FAIL"]
        mark = "✗" if fails else "✓"
        print(f"{mark} {p.name}  ({script.get('axis','?')}축 / {script.get('topic','')})")
        for level, code, msg in results:
            print(f"    [{level}] {code}: {msg}")
        if fails:
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv))
