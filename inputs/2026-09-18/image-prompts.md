# 씬 이미지 생성 프롬프트 — 2026-09-18

주제: 회사에서 이 말, 먼저 꺼내면 손해 봅니다

이 파일은 `scene-plan.json`의 8씬과 1:1로 대응한다.
ChatGPT에 **한 대화 안에서 순서대로** 넣어야 캐릭터 일관성이 유지된다 (명세서 §31 RISK-1).

---

## 0. 먼저 이것부터 (스타일 고정)

새 대화를 열고 아래를 **가장 먼저** 붙여넣는다. 이미지를 요청하지 말고 규칙만 인식시킨다.

```
You will generate 8 vertical illustrations for a Korean YouTube Shorts channel.
I will give them to you one at a time. Before that, lock in this style and keep it
IDENTICAL across all 8 images. Never change the character design between images.

STYLE LOCK — apply to every image:
- Friendly Korean webtoon / chibi character illustration, flat colors, minimal shading
- Bold navy outlines, consistent line weight throughout
- Bright warm yellow office atmosphere as the dominant background tone
- Clean, uncluttered background. Few props. No visual noise.

MAIN CHARACTER — identical in every image:
- Young male office worker, early 30s, chibi proportions (large head, small body)
- Dark brown / near-black slightly messy hair
- White dress shirt, navy necktie
- Blue employee ID badge hanging on a lanyard
- Simple friendly face, expressive eyes and eyebrows

COMPOSITION RULES — every image:
- Vertical 9:16 aspect ratio (1080 x 1920). If 9:16 is unavailable, use the tallest
  portrait ratio available and keep the character horizontally centered with generous
  space on the left and right, because the sides will be cropped.
- Keep the character in the upper-middle of the frame.
- The bottom 30% of the frame must stay visually EMPTY — it is reserved for burned-in
  subtitles. No characters, no props, no important detail down there.
- Keep a 15% margin from all edges free of important detail (the video applies a slow
  zoom and pan, so edges get cropped).
- ABSOLUTELY NO text, letters, numbers, signs, or writing anywhere in the image.
  Speech bubbles and thought clouds are allowed only if they are completely EMPTY.

Reply "ready" and wait for scene 1.
```

---

## SCENE-01 — Hook (STILL, slow_zoom_in)

내레이션: "회사에서 이 말, 먼저 꺼내면 괜히 손해 봅니다."

```
Scene 1 of 8. Same style lock, same character.

The office worker faces the viewer directly, at desk height in a simple bright yellow
office. His expression is a knowing, slightly awkward half-smile — the face of someone
about to warn you about something. One hand is raised to chest height in a small
"hold on" gesture, palm forward, fingers relaxed and simple.

Background: a plain yellow office wall with one simple window shape far behind him.
Nothing else.

Framing: waist-up, character centered in the upper-middle. Bottom 30% empty.
```

---

## SCENE-02 — 상황 (I2V, LTX 2.5 입력)

내레이션: "팀장님이 갑자기 일을 하나 넘깁니다."

> I2V 대상이라 **포즈와 손동작을 최대한 단순하게** (명세서 §13).
> 서류를 "건네는 중"이 아니라 **이미 건네진 직후** 상태로 그린다.

```
Scene 2 of 8. Same style lock, same main character.

Two characters, side by side, facing slightly toward each other.

LEFT: a new character — the team leader. Middle-aged Korean man, chibi proportions,
same art style. Short neat grey-black hair, light grey dress shirt, no tie, simple
rectangular glasses. Calm, matter-of-fact expression. He holds a small stack of plain
papers forward with one hand, arm already extended, elbow slightly bent. Simple hand,
no finger detail.

RIGHT: the main office worker (unchanged design). He has just been handed the papers.
His eyebrows are raised, mouth slightly open — mildly surprised and awkward. Both his
arms hang naturally at his sides; he has NOT taken the papers yet. Keep his hands
simple and relaxed, no gripping, no complex finger poses.

Background: plain bright yellow office, one simple desk edge at the bottom.

Framing: both characters waist-up, centered as a pair. Bottom 30% empty.
```

---

## SCENE-03 — 공감 (STILL, static)

내레이션: "머릿속에 바로 떠오르는 말이 있죠. 이건 제 일이 아닌데요."

```
Scene 3 of 8. Same style lock, same character.

The main office worker alone, facing the viewer. His lips are pressed flat in a tight
closed-mouth line and his eyes look slightly off to the side — visibly holding
something back. Shoulders slightly raised.

Above and to the right of his head, draw a COMPLETELY EMPTY thought cloud — a rounded
cartoon thought bubble with two small trailing circles, outlined in navy, filled with
plain white. The bubble must contain NO text and NO symbols at all. Keep the bubble in
the upper third of the frame.

Background: plain bright yellow, nothing else.

Framing: chest-up, character centered slightly left so the thought cloud fits on the
right. Bottom 30% empty.
```

---

## SCENE-04 — 문제 설명 (STILL, slow_zoom_in)

내레이션: "그런데 이 말은 내용보다 태도로 먼저 전달됩니다."

```
Scene 4 of 8. Same style lock, same character.

The main office worker in three-quarter view, mouth open mid-sentence, speaking.

Next to his mouth, draw a single EMPTY speech bubble — but make its shape spiky and
angular, with sharp jagged edges instead of a soft rounded outline, and give it a cool
pale blue-grey fill instead of white. This is a visual metaphor for a cold tone of
voice. The bubble must be completely empty: no text, no symbols, no punctuation.

His own expression stays neutral and unaware — he does not realize how it sounds.

Background: plain bright yellow, one simple window shape far behind.

Framing: chest-up, centered. Bottom 30% empty.
```

---

## SCENE-05 — 반응 / 오해 (I2V, LTX 2.5 입력)

내레이션: "듣는 사람은 거절이 아니라 선긋기로 받아들여요."

> I2V 대상. 두 인물 모두 **정적인 상반신 포즈**로, 표정과 시선만 의미를 갖게 한다.

```
Scene 5 of 8. Same style lock, same main character.

Two characters facing each other in profile-ish three-quarter view.

RIGHT: the main office worker (unchanged design), mouth closed, expression flat and
slightly defensive. Arms relaxed at his sides.

LEFT: the same team leader character from scene 2 (grey-black hair, light grey shirt,
rectangular glasses, no tie). His expression has cooled — eyebrows lowered flat, mouth
a small straight line, and his eyes are turned AWAY from the office worker, looking off
to the left. Shoulders very slightly dropped. No papers in his hands this time; arms
relaxed at his sides.

Leave a noticeable empty gap between the two characters to suggest distance.

Background: plain bright yellow office, very simple.

Framing: both characters chest-up. Bottom 30% empty.
```

---

## SCENE-06 — 해결법 (STILL, slow_pan_right)

내레이션: "대신 이렇게 바꿔보세요. 지금 이것부터 하고 있는데, 순서를 어떻게 할까요."

> `slow_pan_right` 이라 **가로로 넓게 퍼진 구도**가 좋다.

```
Scene 6 of 8. Same style lock, same character.

The main office worker stands on the LEFT side of the frame, turned toward the right.
His expression is bright and cooperative — light smile, eyebrows relaxed, one hand
raised in a small open-palm "asking" gesture. Simple hand, no finger detail.

On the RIGHT side of the frame, at the same height as his head and shoulders, draw a
simple navy-outlined whiteboard or task board in flat white. On it, draw exactly three
short horizontal lines stacked vertically, each with a small empty square checkbox at
its left end. The lines represent text but must be PLAIN LINES — no letters, no words,
no numbers anywhere.

Spread the composition horizontally: character on the left, board on the right, with
clear yellow space between them.

Background: plain bright yellow office.

Framing: waist-up. Bottom 30% empty.
```

---

## SCENE-07 — 적용 예시 (STILL, slow_zoom_out)

내레이션: "거절은 똑같이 하는데, 판단은 상대에게 넘어갑니다."

> `slow_zoom_out` — 시작이 확대 상태이므로 **중앙에 두 인물을 모아** 배치.

```
Scene 7 of 8. Same style lock, same main character.

Two characters facing each other, centered together in the middle of the frame with
generous yellow space around them.

LEFT: the main office worker (unchanged design), calm and relaxed, a small polite
smile, hands at his sides. He is done speaking.

RIGHT: the same team leader character (grey-black hair, light grey shirt, rectangular
glasses). Now HE is the one thinking — one hand raised to his chin, head tilted
slightly, eyes looking upward, eyebrows raised in consideration. The decision has moved
to him.

Above the team leader's head, a small COMPLETELY EMPTY thought cloud, navy outline,
white fill, no text or symbols.

Background: plain bright yellow office, one simple desk edge.

Framing: both characters waist-up, grouped in the center. Bottom 30% empty.
```

---

## SCENE-08 — 마무리 (STILL, slow_zoom_in)

내레이션: "내 일이 아니라는 말, 순서 질문으로 바꿔보세요."

```
Scene 8 of 8. Same style lock, same character.

The main office worker alone, facing the viewer straight on, relaxed and confident.
Warm genuine smile, eyes slightly curved, shoulders down and easy. One hand gives a
small, simple thumbs-up at chest height — keep the hand chunky and simple, chibi style.

Background: the simplest of all eight — plain bright warm yellow, no window, no desk,
no props. Just the character.

Framing: chest-up, character centered, with MORE empty space below him than in the
other scenes. Bottom 35% empty.
```

---

## 저장 규칙

| 씬 | 파일명 |
|---|---|
| SCENE-01 | `scene-01.png` |
| SCENE-02 | `scene-02.png` |
| SCENE-03 | `scene-03.png` |
| SCENE-04 | `scene-04.png` |
| SCENE-05 | `scene-05.png` |
| SCENE-06 | `scene-06.png` |
| SCENE-07 | `scene-07.png` |
| SCENE-08 | `scene-08.png` |

- **PNG**로 저장, 파일명은 위와 정확히 일치해야 한다 (`scene-plan.json`의 `imageFile`과 매칭).
- 이 폴더(`inputs/2026-09-18/`)의 기존 자리표시자 이미지를 덮어쓴다.
- 비율이 9:16이 아니어도 동작한다. `config/render.json`의 `fitMode: "cover"`가
  가운데를 기준으로 좌우를 잘라내고, 검증 단계에서 경고를 띄운다.

## 검증

```bash
python main.py --input ./inputs/2026-09-18 --validate-only
```

## 렌더 (음성은 나중에)

```bash
python main.py --input ./inputs/2026-09-18 --skip-i2v --tts-engine offline --force
```
