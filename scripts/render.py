#!/usr/bin/env python3
"""output/NNNN.json → 사람이 읽는 마크다운. JSON이 원본, 마크다운은 사본이다.

  ./scripts/render.py output/0001.json       # 화면에 출력
  ./scripts/render.py output/*.json -w       # 파일로 저장
"""
import json
import re
import sys
from pathlib import Path

_NOT_SPOKEN = re.compile(r"[\s,.?!…·~\"'“”‘’()\[\]]")


def n(t: str) -> int:
    return len(_NOT_SPOKEN.sub("", t))


def render(d: dict) -> str:
    yt = d["youtube"]
    L = [f"# {d['id']} · {d['topic']}", "",
         f"`{d['axis']}축` · {d.get('category','')} · {d['total_sec']}초 · "
         f"총 {sum(n(s['tts']) for s in d['scenes'])}자",
         "", "> JSON에서 생성된 파일입니다. 고칠 때는 `output/{}.json` 을 고치세요.".format(d["id"]), "",
         "## 씬", "", "| # | 구간 | 초 | 종류 | 나레이션(TTS) | 자막 | 움직임 |",
         "|---|---|---|---|---|---|---|"]
    for s in d["scenes"]:
        kind = "🎬 영상" if s.get("asset_type") == "video" else "🖼 이미지"
        L.append(f"| {s['n']} | {s['role']} | {s['start']}–{s['end']} | {kind} | {s['tts']} "
                 f"| {s['caption']} | {s['motion']} |")
    L += ["", "## 이미지 프롬프트", ""]
    for s in d["scenes"]:
        kind = "🎬 영상용 첫 프레임" if s.get("asset_type") == "video" else "🖼 정지 이미지"
        L.append(f"**{s['n']}. {s['role']} · {kind}**  \n`{s['image_prompt']}`")
        if s.get("video_motion"):
            L.append(f"  \n▶ 영상 모션: `{s['video_motion']}`")
        L.append("")
    L += [f"**공통 스타일**  \n`{d['image_style']}`", "",
          f"**네거티브**  \n`{d.get('image_negative','')}`", "",
          f"**캐릭터 레퍼런스** `{d.get('character_ref','')}` — 매 생성에 함께 넣을 것", "",
          "## 유튜브 업로드", "",
          f"- **제목:** {yt['title']}",
          f"- **태그:** {' '.join(yt['tags'])}",
          f"- **고정 댓글:** {yt['pinned_comment']}",
          f"- **썸네일 문구:** {yt.get('thumbnail_text','')}",
          f"- **아동용:** 아니오 / **AI 고지:** {'필요' if yt.get('ai_disclosure') else '불필요'}",
          "", "설명란:", "", "```", yt["description"], "```", ""]
    return "\n".join(L)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 2
    for a in args:
        src = Path(a)
        d = json.loads(src.read_text(encoding="utf-8"))
        md = render(d)
        if "-w" in sys.argv:
            slug = re.sub(r"[?!,.:\"']", "", re.sub(r"[ /]", "-", d["topic"]))
            dst = src.parent / f"{d['id']}-{slug}.md"
            dst.write_text(md + "\n", encoding="utf-8")
            print(f"생성됨: {dst}")
        else:
            print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
