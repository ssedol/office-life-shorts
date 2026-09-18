#!/usr/bin/env python3
"""대본 JSON을 읽어 씬 이미지를 생성한다. 로컬에서 돌린다.

  ./scripts/genimg.py output/0001.json --dry-run          # 뭘 만들지 확인만
  ./scripts/genimg.py output/0001.json --provider openai
  ./scripts/genimg.py output/*.json    --provider gemini --only video

  --only image   정지 이미지 씬만
  --only video   영상으로 만들 씬의 첫 프레임만
  --force        이미 있는 파일도 다시 생성

결과: assets/scenes/<대본ID>/<씬번호>_<역할>.png

캐릭터 일관성을 위해 매 호출에 assets/ref/main.webp 를 참조 이미지로 넣는다.
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "scenes"


def build_prompt(d: dict, sc: dict) -> str:
    return f"{sc['image_prompt']}, {d.get('image_style','')}"


# ── 제공자별 구현 ────────────────────────────────────────────────────────
# 주의: 각 API의 정확한 파라미터는 버전에 따라 바뀐다.
# 동작하지 않으면 해당 제공자의 현재 문서를 확인하고 이 함수만 고치면 된다.

def gen_openai(prompt: str, negative: str, refs: list[Path], dst: Path) -> None:
    """OpenAI gpt-image-1. 9:16 에 가장 가까운 크기는 1024x1536 (2:3)."""
    from openai import OpenAI
    client = OpenAI()
    # gpt-image-1 에는 별도 negative 파라미터가 없어 프롬프트에 붙인다.
    full = f"{prompt}. Avoid: {negative}" if negative else prompt
    if refs:
        full = ("Keep the characters exactly as in the reference images "
                "(same hair, face, clothes, colors). ") + full
        handles = [r.open("rb") for r in refs]
        try:
            r = client.images.edit(model="gpt-image-1", image=handles,
                                   prompt=full, size="1024x1536")
        finally:
            for h in handles:
                h.close()
    else:
        r = client.images.generate(model="gpt-image-1", prompt=full, size="1024x1536")
    dst.write_bytes(base64.b64decode(r.data[0].b64_json))


MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def gen_gemini(prompt: str, negative: str, refs: list[Path], dst: Path) -> None:
    """Google Gemini 이미지 모델."""
    from google import genai
    from google.genai import types
    client = genai.Client()
    full = f"{prompt}. Do not include: {negative}" if negative else prompt
    if refs:
        full = ("Keep the characters exactly as in the reference images "
                "(same hair, face, clothes, colors). ") + full
    parts: list = [full]
    for ref in refs:
        parts.insert(0, types.Part.from_bytes(
            data=ref.read_bytes(), mime_type=MIME.get(ref.suffix.lower(), "image/png")))
    r = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=parts,
        config=types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio="9:16")),
    )
    for part in r.candidates[0].content.parts:
        if getattr(part, "inline_data", None):
            dst.write_bytes(part.inline_data.data)
            return
    raise RuntimeError("응답에 이미지가 없습니다")


PROVIDERS = {"openai": gen_openai, "gemini": gen_gemini}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="openai")
    ap.add_argument("--only", choices=["image", "video"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chain", action="store_true",
                    help="앞 씬 결과물을 다음 씬의 추가 레퍼런스로 넣는다 (일관성 ↑, 속도 ↓)")
    ap.add_argument("--check-refs", action="store_true",
                    help="필요한 레퍼런스 컷이 다 있는지만 확인하고 끝낸다")
    a = ap.parse_args()

    if a.check_refs:
        missing = []
        for path in a.files:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            for sc in d["scenes"]:
                for r in sc.get("ref_pose", []):
                    if not (ROOT / r).exists():
                        missing.append(r)
        missing = sorted(set(missing))
        if missing:
            print(f"레퍼런스 컷 {len(missing)}개가 없습니다. "
                  f"prompts/character-sheets.md 로 시트를 먼저 만드세요.\n")
            for m in missing:
                print("  ✗", m)
            return 1
        print("필요한 레퍼런스 컷이 모두 있습니다.")
        return 0

    made = skipped = failed = 0
    for path in a.files:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        base = ROOT / d["character_ref"] if d.get("character_ref") else None
        dest_dir = OUT / d["id"]
        prev: Path | None = None
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n[{d['id']}] {d['topic']}")

        for sc in d["scenes"]:
            kind = sc.get("asset_type", "image")
            if a.only and kind != a.only:
                continue
            dst = dest_dir / f"{sc['n']}_{sc['role']}.png"
            label = "🎬첫프레임" if kind == "video" else "🖼이미지"
            if dst.exists() and not a.force:
                print(f"  - {sc['n']} {sc['role']:6s} {label}  이미 있음 (건너뜀)")
                skipped += 1
                continue
            if a.dry_run:
                print(f"  + {sc['n']} {sc['role']:6s} {label}  → {dst.relative_to(ROOT)}")
                print(f"      {build_prompt(d, sc)[:110]}...")
                pose = sc.get("ref_pose", [])
                have = [r for r in pose if (ROOT / r).exists()]
                print(f"      레퍼런스: {', '.join(Path(r).name for r in pose) or '없음'}"
                      f"  ({len(have)}/{len(pose)} 준비됨)")
                if kind == "video":
                    print(f"      영상 모션: {sc.get('video_motion','')}")
                made += 1
                continue
            refs = [p for p in ([base] if base else []) +
                    [ROOT / r for r in sc.get("ref_pose", [])] +
                    ([prev] if a.chain and prev else []) if p and p.exists()]
            try:
                PROVIDERS[a.provider](build_prompt(d, sc),
                                      d.get("image_negative", ""), refs, dst)
                print(f"  ✓ {sc['n']} {sc['role']:6s} {label}  → {dst.relative_to(ROOT)} "
                      f"(레퍼런스 {len(refs)}장)")
                prev = dst
                made += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ {sc['n']} {sc['role']:6s} 실패: {e}")
                failed += 1

    verb = "생성 예정" if a.dry_run else "생성"
    print(f"\n{verb} {made} · 건너뜀 {skipped} · 실패 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
