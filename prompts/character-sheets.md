# 캐릭터 시트 — 캐릭터를 고정하는 방법

## 왜 시트인가

씬마다 한 장씩 따로 생성하면 **생성 횟수만큼 다른 캐릭터**가 나온다.
모델은 매번 새로 그리기 때문에 머리 모양, 넥타이 폭, 사원증 줄 색이 조금씩 달라진다.

> **한 번의 생성 안에 들어간 그림들은 서로 같다.**

이게 유일하게 확실한 방법이다. 아래 시트 4장만 뽑으면, 그 안의 모든 포즈가 서로 동일한 캐릭터다.
이후 씬 이미지를 만들 때 **해당 포즈 컷을 레퍼런스로 넣으면** 흔들림이 크게 줄어든다.

## 만드는 순서

```
1. 아래 시트 프롬프트 4개를 각각 생성   ← 캐릭터를 만드셨던 그 도구에서 (스타일이 같아야 함)
2. 각 칸을 잘라서 assets/ref/poses/ 에 지정된 이름으로 저장
3. ./scripts/genimg.py 실행 — 씬마다 알맞은 포즈 컷이 자동으로 레퍼런스에 들어간다
```

**반드시 기존 프로필 이미지(`assets/ref/main.webp`)를 참조로 함께 넣고 생성하세요.**
그래야 시트 속 캐릭터가 기존 캐릭터와 같아집니다.

---

## 시트 1 — 주인공 표정 (3×3, 9칸)

> 저장: `assets/ref/expr/main_<이름>.png`
> 순서(왼→오, 위→아래): tired, nervous, annoyed, shocked, resigned, relieved, excited, panicked, determined

```
A 3x3 character expression sheet of the SAME single character in every cell,
evenly spaced grid on a plain white background, thin gray grid lines,
bust shot (head and shoulders) facing the viewer in every cell.

Character: a chibi Korean male office worker in his late 20s, big head small body,
messy black hair with one stray ahoge strand, round blush cheeks,
white dress shirt, navy necktie, blue lanyard with a white ID card badge.

Nine expressions, left to right, top to bottom:
1. exhausted with dead hollow eyes and slumped shoulders
2. nervous side-eye glance with a single sweat drop and a stiff forced smile
3. annoyed with puffed cheeks, furrowed brows and a small anger cross mark
4. shocked with huge round eyes, dropped jaw and both hands raised
5. resigned with a flat straight line mouth and half lidded eyes
6. relieved with closed eyes, a small soft smile and a visible exhale puff
7. excited with sparkling star eyes and a wide open happy mouth
8. panicked with wide eyes, flailing hands and spiral motion lines
9. determined with a confident smirk and one clenched fist

cute Korean webtoon chibi illustration, thick bold navy outlines,
clean flat shading, consistent character design across all nine cells, no text
```

## 시트 2 — 주인공 전신 포즈 (2×3, 6칸)

> 저장: `assets/ref/poses/main_<이름>.png`
> 순서: desk, docs, count123, bed, leaving, sofa

```
A 2x3 character pose sheet of the SAME single character in every cell,
evenly spaced grid on a plain white background, thin gray grid lines,
full body in every cell, no background objects except what is named.

Character: a chibi Korean male office worker in his late 20s, big head small body,
messy black hair with one stray ahoge strand, round blush cheeks,
white dress shirt, navy necktie, blue lanyard with a white ID card badge.

Six poses, left to right, top to bottom:
1. sitting at an office desk facing a monitor, seen from a three quarter angle
2. standing and holding a stack of documents with both hands
3. facing the viewer holding up one, two and three fingers, cheerful
4. lying flat on his back with arms spread, tie loosened, exhausted
5. walking away with a shoulder bag, seen from behind, tiptoeing quietly
6. slouched sitting on a sofa, vacant stare, one arm hanging down

cute Korean webtoon chibi illustration, thick bold navy outlines,
clean flat shading, consistent character design across all six cells, no text
```

## 시트 3 — 팀장 (2×3, 6칸)

> 저장: `assets/ref/poses/boss_<이름>.png`
> 순서: sigh, mouse, drop, glare, rush, scolded

```
A 2x3 character pose sheet of the SAME single character in every cell,
evenly spaced grid on a plain white background, thin gray grid lines, full body.

Character: a chibi Korean male team leader in his 40s, big head small body,
short slicked black hair with graying sides, thick square glasses,
light gray dress shirt with a loosened dark tie, slightly round belly.

Six poses, left to right, top to bottom:
1. sitting at a desk facing a monitor, letting out a heavy sigh with a breath puff
2. slamming a computer mouse down onto a desk, sharp impact burst
3. dropping a heavy stack of documents onto a desk
4. adjusting his glasses while glaring sideways, stern
5. hurrying past with a phone to his ear and files under his arm, motion lines
6. standing small and scolded, shoulders hunched, looking down

cute Korean webtoon chibi illustration, thick bold navy outlines,
clean flat shading, consistent character design across all six cells, no text
```

## 시트 4 — 동료 (1×3, 3칸)

> 저장: `assets/ref/poses/peer_<이름>.png`
> 순서: wave, desk, chat

```
A 1x3 character pose sheet of the SAME single character in every cell,
evenly spaced row on a plain white background, thin gray grid lines, full body.

Character: a chibi Korean female office worker in her late 20s, big head small body,
shoulder length dark brown bob hair, beige blouse,
blue lanyard with a white ID card badge.

Three poses, left to right:
1. cheerfully waving with one hand as if calling someone to lunch
2. sitting at an office desk working, seen from a three quarter angle
3. leaning in and chatting with a hand near her mouth

cute Korean webtoon chibi illustration, thick bold navy outlines,
clean flat shading, consistent character design across all three cells, no text
```

---

## 자르기

시트를 격자대로 균등 분할하면 됩니다. 로컬에서:

```bash
./scripts/crop_sheet.py sheet2.png --grid 2x3 \
    --names desk docs count123 bed leaving sofa \
    --prefix main --out assets/ref/poses
```

## 그다음 — 롤링 레퍼런스 (선택)

시트만으로도 대부분 잡히지만, 더 빡빡하게 가려면
**1번 씬 결과물을 2번 씬의 추가 레퍼런스로** 넣는 식으로 이어갑니다.
`genimg.py --chain` 옵션이 그 동작입니다.
