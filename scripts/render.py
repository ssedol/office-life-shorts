#!/usr/bin/env python3
"""output/NNNN.json → 사람이 읽는 마크다운.

JSON이 단일 진실이다. 마크다운은 파생물이므로 직접 고치지 않는다.

  ./scripts/render.py output/0001.json          # stdout
  ./scripts/render.py output/0001.json -w       # output/NNNN-<주제>.md 로 저장
"""
import json
import re
import sys
from pathlib import Path

_NOT_SPOKEN = re.compile(r"[\s,.?!…·~\"'“”‘’()\[\]]")


def n_chars(t: str) -> int:
    return len(_NOT_SPOKEN.sub("", t))


def render(d: dict) -> str:
    L = [f"# {d['id']} · {d['topic']}", ""]
    L += [f"> `{d['axis']}축` · {d.get('category','')} · 상태 `{d.get('status','draft')}`",
          "> 이 파일은 `output/{}.json` 에서 생성됩니다. 직접 수정하지 마세요.".format(d["id"]), ""]

    b = d.get("brief", {})
    if b:
        L += ["## 브리핑", "", "| 항목 | 내용 |", "|---|---|",
              f"| 타겟 상황 | {b.get('situation','')} |",
              f"| 감정 (전 → 후) | {b.get('emotion_before','')} → {b.get('emotion_after','')} |",
              f"| 핵심 한 문장 | {b.get('core_line','')} |",
              f"| CTA 질문 | {b.get('cta_question','')} |", ""]

    L += ["## 후킹 후보", ""]
    for i, c in enumerate(d["hook_candidates"]):
        mark = " ← **채택**" if i == d["hook_chosen"] else ""
        L.append(f"{i+1}. `{c['pattern']}` {c['text']}{mark}")
    if d.get("hook_reason"):
        L += ["", f"**채택 이유:** {d['hook_reason']}"]
    L.append("")

    L += ["## 대본", "", "| 구간 | 자 | 나레이션 | 화면·자막 |", "|---|---|---|---|"]
    total = 0
    for blk in d["blocks"]:
        n = n_chars(blk["narration"])
        total += n
        cap = blk.get("caption", "")
        vis = blk["visual"] + (f" / 「{cap}」" if cap else "")
        L.append(f"| {blk['id']} | {n} | {blk['narration']} | {vis} |")
    L += ["", f"**합계 {total}자** (발음 기준) · 예상 {round(total/5, 1)}초", ""]

    m = d["meta"]
    L += ["## 업로드 메타", "",
          f"- **제목({len(m['title'])}자):** {m['title']}",
          f"- **해시태그:** {' '.join(m['hashtags'])}",
          f"- **설명:** {m.get('description','')}",
          f"- **고정 댓글:** {m['pinned_comment']}",
          f"- **썸네일:** {m['thumbnail_text']}",
          f"- **AI 고지:** {'필요' if m.get('ai_disclosure') else '해당 없음'}", ""]

    p = d.get("production", {})
    L += ["## 제작", "",
          f"- 합성 음성: {p.get('synthetic_voice', False)} / 합성 영상: {p.get('synthetic_visual', False)}",
          f"- 사람 고유 요소: {', '.join(p.get('human_elements', [])) or '**없음 — 양산형 판정 위험**'}", ""]

    if d.get("metrics"):
        L += ["## 성과", "", "| 지표 | 값 |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in d["metrics"].items()]
        L.append("")
    return "\n".join(L)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    write = "-w" in sys.argv
    if not args:
        print(__doc__)
        return 2
    for a in args:
        src = Path(a)
        d = json.loads(src.read_text(encoding="utf-8"))
        md = render(d)
        if write:
            slug = re.sub(r"[ /]", "-", d["topic"])
            slug = re.sub(r"[?!,.:\"']", "", slug)
            dst = src.parent / f"{d['id']}-{slug}.md"
            dst.write_text(md + "\n", encoding="utf-8")
            print(f"생성됨: {dst}")
        else:
            print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
