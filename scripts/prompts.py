#!/usr/bin/env python3
"""씬별 이미지 프롬프트를 '그대로 복붙할 수 있는' 완성 형태로 뽑는다.

  ./scripts/prompts.py output/0001.json          # 화면에 출력
  ./scripts/prompts.py output/0001.json --json    # 로컬 코드에서 쓸 JSON 배열

완성 프롬프트 = scene.image_prompt + image_style
네거티브   = image_negative
캐릭터 일관성을 위해 character_ref 이미지를 함께 넣어야 한다.
"""
import json
import sys
from pathlib import Path


def build(d: dict) -> list[dict]:
    style = d.get("image_style", "")
    neg = d.get("image_negative", "")
    return [{
        "n": s["n"],
        "role": s["role"],
        "prompt": f"{s['image_prompt']}, {style}",
        "negative": neg,
        "reference_image": d.get("character_ref"),
        "aspect_ratio": "9:16",
    } for s in d["scenes"]]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    for a in args:
        d = json.loads(Path(a).read_text(encoding="utf-8"))
        items = build(d)
        if "--json" in sys.argv:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            continue
        print(f"\n{'='*70}\n{d['id']} · {d['topic']}")
        print(f"레퍼런스 이미지: {d.get('character_ref')}  (매 생성에 함께 넣을 것)")
        print(f"비율: 9:16\n{'='*70}")
        for it in items:
            print(f"\n──[ {it['n']}. {it['role']} ]{'─'*45}")
            print(it["prompt"])
        print(f"\n──[ NEGATIVE (전 씬 공통) ]{'─'*38}\n{items[0]['negative']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
