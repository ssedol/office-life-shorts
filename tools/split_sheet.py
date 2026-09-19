#!/usr/bin/env python3
"""여러 씬이 한 장에 붙어 있는 합본 이미지를 씬별 파일로 쪼갠다.

ChatGPT에 8장을 한 번에 요청하면 2열×4행 같은 격자 한 장으로 주는 경우가 있다.
그대로는 쓸 수 없으므로 칸 단위로 잘라 scene-01.png ~ scene-08.png로 저장한다.

    python tools/split_sheet.py 합본.png inputs/2026-09-18 --cols 2 --rows 4

칸 비율이 9:16이 아닐 때 맞추는 방법(--fit):

    extend  (기본) 좌우는 그대로 두고 위아래를 가장자리 색으로 늘린다.
            배경(창문/시계/바인더)이 보존되고 확대 배율도 낮아 화질 손실이 적다.
            배경이 단색에 가까운 이 채널 스타일에 맞다.
    cover   좌우를 잘라 9:16을 만든다. 배경이 크게 잘리고 확대 배율이 커진다.
    pad     위아래를 단색으로 채운다. --pad-color로 색을 지정한다.

주의: 합본에서 잘라낸 이미지는 개별 생성본보다 해상도가 낮다.
      흐름 확인용으로는 충분하지만, 최종 업로드용으로는 개별 생성을 권한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

TARGET_W, TARGET_H = 1080, 1920
TARGET_RATIO = TARGET_W / TARGET_H

FIT_EXTEND = "extend"
FIT_COVER = "cover"
FIT_PAD = "pad"


def background_color(img: Image.Image) -> tuple[int, int, int]:
    """칸에서 가장 넓은 면적을 차지하는 색.

    이 채널은 배경이 단색 노란 벽이라 최빈색이 곧 배경색이다.
    가장자리 한 줄의 평균을 쓰면 거기 걸친 머리카락이나 소품에 끌려가므로 쓰지 않는다.
    """
    small = img.convert("RGB").resize((64, 64), Image.BOX)
    # 비슷한 색을 한 덩어리로 묶으려고 채널당 8단계로 양자화한다.
    quantized = small.point(lambda value: (value // 32) * 32 + 16)
    colors = quantized.getcolors(64 * 64) or [(1, (251, 216, 46))]
    return max(colors)[1]


def to_target(panel: Image.Image, fit: str, pad_color: str | None, top_ratio: float = 0.85) -> Image.Image:
    """칸 하나를 1080×1920으로 만든다.

    top_ratio: extend/pad에서 늘려야 할 높이 중 위쪽에 배분할 비율.
        이 채널은 캐릭터 위쪽이 단색 노란 벽이라 위로 늘리면 티가 안 나지만,
        아래쪽은 몸통이나 책상이라 늘리면 줄무늬가 생긴다. 그래서 위쪽에 몰아준다.
    """
    ratio = panel.width / panel.height

    if abs(ratio - TARGET_RATIO) < 0.01:
        return panel.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    if fit == FIT_COVER:
        if ratio > TARGET_RATIO:  # 너무 넓다 → 좌우를 자른다
            new_w = int(round(panel.height * TARGET_RATIO))
            left = (panel.width - new_w) // 2
            panel = panel.crop((left, 0, left + new_w, panel.height))
        else:  # 너무 좁다 → 위아래를 자른다
            new_h = int(round(panel.width / TARGET_RATIO))
            top = (panel.height - new_h) // 2
            panel = panel.crop((0, top, panel.width, top + new_h))
        return panel.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    # extend / pad — 폭은 그대로 두고 높이를 채운다.
    need_h = int(round(panel.width / TARGET_RATIO))
    if need_h <= panel.height:
        # 이미 충분히 길면 위아래를 잘라낸다.
        top = (panel.height - need_h) // 2
        panel = panel.crop((0, top, panel.width, top + need_h))
        return panel.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    extra = need_h - panel.height
    top_h = int(round(extra * max(0.0, min(1.0, top_ratio))))
    bottom_h = extra - top_h

    canvas = Image.new("RGB", (panel.width, need_h))
    if fit == FIT_PAD:
        # 색을 지정하지 않으면 칸의 배경색을 그대로 이어 쓴다.
        color = pad_color if pad_color else background_color(panel)
        canvas.paste(Image.new("RGB", (panel.width, need_h), color), (0, 0))
    else:  # extend — 가장자리 한 줄을 늘려 배경을 이어붙인다.
        if top_h:
            strip = panel.crop((0, 0, panel.width, 1)).resize((panel.width, top_h), Image.NEAREST)
            canvas.paste(strip, (0, 0))
        if bottom_h:
            strip = panel.crop((0, panel.height - 1, panel.width, panel.height))
            canvas.paste(strip.resize((panel.width, bottom_h), Image.NEAREST), (0, top_h + panel.height))

    canvas.paste(panel, (0, top_h))
    return canvas.resize((TARGET_W, TARGET_H), Image.LANCZOS)


def split(
    sheet_path: Path,
    out_dir: Path,
    *,
    cols: int,
    rows: int,
    fit: str,
    pad_color: str | None,
    gutter: int,
    prefix: str,
    top_ratio: float = 0.85,
) -> list[Path]:
    with Image.open(sheet_path) as source:
        sheet = source.convert("RGB")

    cell_w = sheet.width // cols
    cell_h = sheet.height // rows
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    index = 0
    for row in range(rows):
        for col in range(cols):
            index += 1
            box = (
                col * cell_w + gutter,
                row * cell_h + gutter,
                (col + 1) * cell_w - gutter,
                (row + 1) * cell_h - gutter,
            )
            panel = to_target(sheet.crop(box), fit, pad_color, top_ratio)
            path = out_dir / f"{prefix}{index:02d}.png"
            panel.save(path, optimize=True)
            written.append(path)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="합본 이미지를 씬별 1080×1920 파일로 쪼갭니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("sheet", help="합본 이미지 경로")
    parser.add_argument("out_dir", help="저장할 폴더 (예: inputs/2026-09-18)")
    parser.add_argument("--cols", type=int, default=2, help="가로 칸 수 (기본 2)")
    parser.add_argument("--rows", type=int, default=4, help="세로 칸 수 (기본 4)")
    parser.add_argument("--fit", choices=[FIT_EXTEND, FIT_COVER, FIT_PAD], default=FIT_EXTEND,
                        help="9:16으로 맞추는 방법 (기본 extend)")
    parser.add_argument("--pad-color", default=None, help="--fit pad 일 때 채울 색 (기본 #FBD82E)")
    parser.add_argument("--gutter", type=int, default=2,
                        help="칸 경계선을 피하려고 각 변에서 잘라낼 픽셀 (기본 2)")
    parser.add_argument("--extend-top", type=float, default=0.85, metavar="RATIO",
                        help="extend/pad에서 늘릴 높이 중 위쪽 비중 (0~1, 기본 0.85). "
                             "위는 단색 벽이라 늘려도 티가 안 나고, 아래는 몸통이라 줄무늬가 생긴다")
    parser.add_argument("--prefix", default="scene-", help="파일명 접두사 (기본 scene-)")
    args = parser.parse_args(argv)

    sheet_path = Path(args.sheet)
    if not sheet_path.is_file():
        print(f"합본 이미지를 찾을 수 없습니다: {sheet_path}", file=sys.stderr)
        return 1

    with Image.open(sheet_path) as im:
        cell_w, cell_h = im.width // args.cols, im.height // args.rows

    written = split(
        sheet_path,
        Path(args.out_dir),
        cols=args.cols,
        rows=args.rows,
        fit=args.fit,
        pad_color=args.pad_color,
        gutter=args.gutter,
        prefix=args.prefix,
        top_ratio=args.extend_top,
    )

    print(f"합본: {sheet_path.name}  칸 1개: {cell_w}×{cell_h} (비율 {cell_w / cell_h:.3f})")
    print(f"맞춤 방식: {args.fit}  →  1080×1920 (확대 {TARGET_W / cell_w:.2f}배)")
    for path in written:
        print(f"  {path}")

    if TARGET_W / cell_w > 2.0:
        print(
            f"\n경고: 확대 배율이 {TARGET_W / cell_w:.1f}배입니다. 선이 뭉개집니다.\n"
            "      흐름 확인용으로는 쓸 만하지만, 업로드용은 씬별로 따로 생성하세요.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
