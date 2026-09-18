# 오늘도 출근

직장인 **공감 + 꿀팁** 쇼츠 채널. (`office-life-shorts`)

## 역할 분담

| 누가 | 뭘 하나 | 결과물 |
|---|---|---|
| **클로드** | 주제 고르기 + 대본 쓰기 | `output/NNNN.json` 파일 1개 |
| **로컬 PC** | 그 파일 읽어서 TTS · 이미지 · 영상 · 업로드 | 유튜브 영상 |

**주고받는 건 JSON 파일 하나뿐입니다.** 형식은 `HANDOFF.md` 에 있습니다.

## 지금 바로 쓸 수 있는 것

`output/` 에 **검수를 통과한 대본 5편**이 있습니다. 로컬에서 그대로 돌리면 됩니다.

| 파일 | 축 | 주제 |
|---|---|---|
| `output/0001.json` | 공감 | 팀장이 한숨 쉴 때 하면 안 되는 것 |
| `output/0002.json` | 꿀팁 | 보고서 첫 줄에 이것만 넣으면 반려가 줄어든다 |
| `output/0003.json` | 공감 | 퇴근하고 아무것도 못 하는 건 게으른 게 아니다 |
| `output/0004.json` | 꿀팁 | 관계 안 깨지고 거절하는 문장 3개 |
| `output/0005.json` | 공감 | 점심 혼자 먹고 싶은 날 쓰는 핑계 순위 |

같은 이름의 `.md` 파일은 사람이 읽기 편하게 만든 사본입니다. 내용은 같습니다.

## 대본이 더 필요할 때

저한테 이렇게 말씀하시면 됩니다.

> "공감 3개, 꿀팁 2개 더 만들어줘"
> "연차 주제로 꿀팁 하나"

주제를 직접 고르고 싶으면 `data/topics.yaml` 에 49개가 대기 중입니다.

## 이미지 프롬프트 뽑기

씬별 완성 프롬프트를 복붙 가능한 형태로 냅니다.

```bash
./scripts/prompts.py output/0001.json           # 눈으로 보기
./scripts/prompts.py output/0001.json --json    # 코드에서 읽기
```

⚠️ **`assets/ref/main.webp` 를 매 생성에 캐릭터 레퍼런스로 함께 넣으세요.**
프롬프트만으로는 35장에 걸쳐 같은 캐릭터가 유지되지 않습니다.

## 이미지 만들기 — 시트부터

**씬마다 따로 생성하면 캐릭터가 흔들립니다.** 한 번의 생성 안에 들어간 그림만 서로 같습니다.

```
1. prompts/character-sheets.md 의 시트 프롬프트 4개를 생성   → 레퍼런스 컷 21개
2. ./scripts/crop_sheet.py 로 격자대로 자르기
3. ./scripts/genimg.py output/*.json --check-refs            → 준비 확인
4. ./scripts/genimg.py output/0001.json                      → 씬 이미지 생성
```

## 이미지 생성 (로컬)

```bash
pip install -r requirements.txt openai      # 또는 google-genai
export OPENAI_API_KEY=...

./scripts/genimg.py output/0001.json --dry-run      # 확인
./scripts/genimg.py output/0001.json                # 생성
```

씬마다 `asset_type` 이 `image`(정지) 또는 `video`(첫 프레임 + 모션)로 표시돼 있습니다.
영상 씬은 이미지까지만 만들고, 움직이는 건 `video_motion` 을 i2v 모델에 넣으시면 됩니다.

## 검수 (선택)

대본이 채널 규칙을 지키는지 확인합니다. 제가 만들 때 이미 돌리지만, 로컬에서도 됩니다.

```bash
pip install PyYAML
./scripts/validate.py output/0001.json
```

금지어, 대본 길이, 후킹 구체성, 자막 길이, 제목 25자, 해시태그 개수 등을 검사하고
문제가 있으면 종료 코드 1을 냅니다. **파이프라인 앞단에 걸어두면 불량 대본이 안 넘어갑니다.**

## 나머지 파일들

당장 안 봐도 됩니다. 채널 규칙이 어디 적혀 있는지만 알아두세요.

| 경로 | 뭐가 들었나 |
|---|---|
| `HANDOFF.md` | **JSON 형식 설명 — 로컬 코드 짤 때 이거 보세요** |
| `config/style.yaml` | **비주얼 규칙** — 캐릭터 3명, 표정 사전, 색 팔레트, 구도 |
| `assets/ref/main.webp` | **캐릭터 레퍼런스** — 이미지 생성마다 함께 넣을 것 |
| `assets/scenes/` | 생성된 씬 이미지가 쌓이는 곳 |
| `config/channel.yaml` | 금지어, 대본 길이, 목소리 톤 |
| `config/axes.yaml` | 씬 7개의 시간 배분 |
| `config/hooks.yaml` | 첫 4초 후킹 패턴 8종 |
| `data/topics.yaml` | 주제 49개 대기열 |
| `docs/` | 전략·대본공식·제작·업로드 해설 (사람용) |
| `docs/08-automation.md` | **자동화 전 꼭 읽을 것** — 유튜브 정책 리스크 |
