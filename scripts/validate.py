#!/usr/bin/env python3
"""대본 검수. 통과해야 로컬 영상 제작으로 넘긴다.

  ./scripts/validate.py output/0001.json
  ./scripts/validate.py output/*.json

종료 코드 0 = 통과, 1 = FAIL 있음
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CH = yaml.safe_load((ROOT / "config" / "channel.yaml").read_text(encoding="utf-8"))
HK = yaml.safe_load((ROOT / "config" / "hooks.yaml").read_text(encoding="utf-8"))
C = CH["constraints"]
ROLES = ["HOOK", "SETUP", "BODY1", "BODY2", "BODY3", "PAYOFF", "CTA"]

# 구두점은 발음되지 않으므로 길이 계산에서 뺀다.
_NOT_SPOKEN = re.compile(r"[\s,.?!…·~\"'“”‘’()\[\]]")


def n_chars(text: str) -> int:
    return len(_NOT_SPOKEN.sub("", text))


def check(s: dict) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    fail = lambda c, m: out.append(("FAIL", c, m))
    warn = lambda c, m: out.append(("WARN", c, m))

    scenes = s.get("scenes", [])
    by_role = {sc.get("role"): sc for sc in scenes}
    tts_all = " ".join(sc.get("tts", "") for sc in scenes)

    # 씬 구조
    order = [sc.get("role") for sc in scenes]
    if order != ROLES:
        fail("scenes.order", f"씬 구성이 다르다. 필요: {ROLES} / 현재: {order}")

    # 전체 분량
    n = n_chars(tts_all)
    lo, hi = C["narration_chars"]["min"], C["narration_chars"]["max"]
    if n < lo:
        fail("length.short", f"{n}자 — {lo}자 미만. 본문을 늘려라")
    elif n > hi:
        fail("length.long", f"{n}자 — {hi}자 초과. 앞부분부터 깎아라")

    # 씬별 시간 대비 글자수
    for sc in scenes:
        dur = sc.get("end", 0) - sc.get("start", 0)
        cn = n_chars(sc.get("tts", ""))
        if dur > 0 and cn > dur * C["chars_per_sec"]:
            warn("scene.tight",
                 f"{sc.get('role')}: {cn}자 / {dur}초 — 상한 {int(dur*C['chars_per_sec'])}자. 말이 빨라진다")
        if not sc.get("image_prompt"):
            fail("scene.no_image", f"{sc.get('role')}: image_prompt 가 비었다")
        cap = sc.get("caption", "")
        if len(cap.replace(" ", "")) > 14:
            warn("scene.caption_long", f"{sc.get('role')}: 자막 {len(cap)}자 — 못 읽고 넘어간다")

    # 연속 static 금지 (정지 화면이 이어지면 이탈한다)
    motions = [sc.get("motion", "static") for sc in scenes]
    for i in range(len(motions) - 1):
        if motions[i] == "static" and motions[i + 1] == "static":
            warn("scene.static_run", f"{i+1}, {i+2}번 씬이 연속 static 이다")

    # 금지어
    for p in CH["banned_phrases"]:
        if p in tts_all:
            fail("banned.phrase", f"금지어 '{p}' 가 나레이션에 있다")

    # HOOK
    hook = by_role.get("HOOK", {}).get("tts", "")
    if hook:
        hn = n_chars(hook)
        if hn > C["hook_max_chars"]:
            fail("hook.long", f"HOOK {hn}자 — 최대 {C['hook_max_chars']}자. 3초를 넘긴다")
        markers = CH["hook_concreteness_markers"]
        if not any(v in hook for vals in markers.values() for v in vals):
            fail("hook.abstract", "HOOK에 구체적 시간/직급/장소가 없다")
        for bad in HK["forbidden_openings"]:
            if isinstance(bad, str) and hook.startswith(bad):
                fail("hook.forbidden", f"금지된 도입: '{bad}'")

    cands = s.get("hook_candidates", [])
    if len(cands) < C["hook_candidates_min"]:
        fail("hook.candidates", f"후보 {len(cands)}개 — {C['hook_candidates_min']}개 이상 필요")

    # CTA
    cta = by_role.get("CTA", {}).get("tts", "")
    if cta and "?" not in cta:
        fail("cta.not_question", "CTA가 질문이 아니다. 댓글이 안 달린다")

    # 유튜브 메타
    yt = s.get("youtube", {})
    if len(yt.get("title", "")) > C["title_max_chars"]:
        fail("yt.title_long", f"제목 {len(yt.get('title',''))}자 — {C['title_max_chars']}자 초과 시 잘린다")
    tags = yt.get("tags", [])
    h = C["hashtags"]
    if not (h["min"] <= len(tags) <= h["max"]):
        fail("yt.tags", f"해시태그 {len(tags)}개 — {h['min']}~{h['max']}개여야 한다")
    for req in h["required"]:
        if req not in tags:
            fail("yt.tag_required", f"{req} 누락")
    if yt.get("made_for_kids") is not False:
        fail("yt.kids", "made_for_kids 는 false 여야 한다")
    if not yt.get("ai_disclosure"):
        warn("yt.ai_disclosure", "TTS/생성 이미지를 쓴다면 ai_disclosure 를 true 로 두고 업로드 시 고지할 것")

    return out


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    worst = 0
    for p in paths:
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"✗ {p.name}: 읽기 실패 — {e}")
            worst = 1
            continue
        res = check(s)
        fails = [r for r in res if r[0] == "FAIL"]
        total = n_chars(" ".join(sc.get("tts", "") for sc in s.get("scenes", [])))
        print(f"{'✗' if fails else '✓'} {p.name}  [{s.get('axis','?')}축] {s.get('topic','')}  ({total}자)")
        for level, code, msg in res:
            print(f"    [{level}] {code}: {msg}")
        if fails:
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
