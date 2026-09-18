#!/usr/bin/env python3
"""캐릭터 시트를 격자대로 잘라 레퍼런스 컷으로 저장한다.

  ./scripts/crop_sheet.py sheet2.png --grid 2x3 \
      --names desk docs count123 bed leaving sofa \
      --prefix main --out assets/ref/poses

  --margin 0.04   칸 경계의 격자선을 피해 4%씩 안쪽으로 잘라낸다 (기본값)
  --dry-run       자를 위치만 확인

Pillow 필요: pip install Pillow
"""
import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--grid", required=True, help="행x열, 예: 3x3 또는 2x3")
    ap.add_argument("--names", nargs="+", required=True, help="왼→오, 위→아래 순서")
    ap.add_argument("--prefix", required=True, help="main / boss / peer")
    ap.add_argument("--out", default="assets/ref/poses")
    ap.add_argument("--margin", type=float, default=0.04)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows, cols = (int(x) for x in a.grid.lower().split("x"))
    if len(a.names) != rows * cols:
        print(f"이름 {len(a.names)}개인데 칸은 {rows*cols}개입니다.", file=sys.stderr)
        return 1

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.dry_run:
        for i, name in enumerate(a.names):
            print(f"  {i//cols+1}행 {i%cols+1}열 → {out}/{a.prefix}_{name}.png")
        return 0

    try:
        from PIL import Image
    except ImportError:
        print("Pillow 가 필요합니다: pip install Pillow", file=sys.stderr)
        return 1

    img = Image.open(a.sheet)
    cw, ch = img.width / cols, img.height / rows
    mx, my = cw * a.margin, ch * a.margin

    for i, name in enumerate(a.names):
        r, c = divmod(i, cols)
        box = (int(c * cw + mx), int(r * ch + my),
               int((c + 1) * cw - mx), int((r + 1) * ch - my))
        dst = out / f"{a.prefix}_{name}.png"
        img.crop(box).save(dst)
        print(f"  ✓ {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
