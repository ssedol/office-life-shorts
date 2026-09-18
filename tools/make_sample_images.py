#!/usr/bin/env python3
"""샘플 입력용 자리표시자 이미지 생성기.

실제 제작에서 씬 이미지는 ChatGPT가 만든다(명세서 §7.2-A, DEC-008).
이 스크립트는 파이프라인을 처음부터 끝까지 돌려보기 위한 자리표시자만 만든다.
채널 비주얼(노란 오피스 톤 / 굵은 네이비 외곽선)을 흉내 낸 단순 도형이며,
캐릭터 일관성 검수용으로 쓸 수 있는 물건이 아니다.

    python tools/make_sample_images.py inputs/2026-09-18
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920

BG = (253, 224, 122)        # 밝은 노란색 오피스 분위기
NAVY = (21, 32, 70)         # 굵은 네이비 외곽선
SHIRT = (255, 255, 255)
TIE = (36, 62, 138)
BADGE = (59, 130, 246)
SKIN = (253, 216, 185)
HAIR = (54, 38, 32)
DESK = (225, 183, 96)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]

SCENE_LABELS = [
    "01 Hook",
    "02 상황",
    "03 공감",
    "04 문제 설명",
    "05 반응 / 오해",
    "06 해결법",
    "07 적용 예시",
    "08 마무리",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def draw_character(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    """chibi 직장인 실루엣 (자리표시자 수준)."""
    w = int(240 * scale)
    outline = max(6, int(10 * scale))

    # 몸통(흰 셔츠)
    body = (cx - w // 2, cy, cx + w // 2, cy + int(300 * scale))
    draw.rounded_rectangle(body, radius=int(40 * scale), fill=SHIRT, outline=NAVY, width=outline)

    # 네이비 넥타이
    draw.polygon(
        [
            (cx, cy + int(20 * scale)),
            (cx - int(26 * scale), cy + int(70 * scale)),
            (cx, cy + int(210 * scale)),
            (cx + int(26 * scale), cy + int(70 * scale)),
        ],
        fill=TIE, outline=NAVY,
    )

    # 파란 사원증
    badge = (cx + int(45 * scale), cy + int(150 * scale), cx + int(105 * scale), cy + int(235 * scale))
    draw.rounded_rectangle(badge, radius=int(10 * scale), fill=BADGE, outline=NAVY, width=max(4, outline // 2))

    # 머리
    head_r = int(130 * scale)
    draw.ellipse((cx - head_r, cy - head_r * 2 + int(20 * scale), cx + head_r, cy + int(20 * scale)),
                 fill=SKIN, outline=NAVY, width=outline)
    # 약간 헝클어진 짙은 머리
    draw.chord((cx - head_r, cy - head_r * 2 + int(20 * scale), cx + head_r, cy + int(20 * scale)),
               180, 360, fill=HAIR, outline=NAVY, width=outline)
    # 눈
    eye_y = cy - head_r + int(10 * scale)
    for dx in (-int(48 * scale), int(48 * scale)):
        draw.ellipse((cx + dx - int(13 * scale), eye_y - int(13 * scale),
                      cx + dx + int(13 * scale), eye_y + int(13 * scale)), fill=NAVY)


def make_scene(index: int, out_path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # 책상
    draw.rectangle((0, 1380, WIDTH, 1440), fill=DESK, outline=NAVY, width=8)
    # 배경 창문
    draw.rounded_rectangle((90, 300, 400, 620), radius=24, outline=NAVY, width=10)
    draw.rounded_rectangle((680, 300, 990, 620), radius=24, outline=NAVY, width=10)

    draw_character(draw, WIDTH // 2, 980, scale=1.0)

    label_font = load_font(74)
    note_font = load_font(40)
    small_font = load_font(34)

    label = f"SCENE-{index:02d}"
    draw.text((WIDTH // 2, 150), label, font=label_font, fill=NAVY, anchor="mm")
    draw.text((WIDTH // 2, 232), SCENE_LABELS[index - 1], font=note_font, fill=NAVY, anchor="mm")

    # 자막 안전영역 표시 (config/subtitle.json safeArea와 같은 값)
    draw.rectangle((80, HEIGHT - 520, WIDTH - 80, HEIGHT - 300), outline=(180, 150, 60), width=4)
    draw.text((WIDTH // 2, HEIGHT - 560), "↓ 자막 안전영역", font=small_font, fill=(140, 115, 40), anchor="mm")

    draw.text((WIDTH // 2, HEIGHT - 120), "자리표시자 이미지 — 실제 제작에서는 ChatGPT 생성본으로 교체",
              font=small_font, fill=(150, 125, 50), anchor="mm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("inputs/sample")
    for index in range(1, 9):
        path = target / f"scene-{index:02d}.png"
        make_scene(index, path)
        print(f"  {path}")
    print(f"\n자리표시자 이미지 8장을 만들었습니다: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
