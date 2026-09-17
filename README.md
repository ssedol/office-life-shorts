# office-life-shorts

직장인 대상 유튜브 쇼츠 채널 운영 시스템.
**주제 → 대본 → 검수 → 제작 → 업로드**를 단계로 쪼개고, 각 단계의 규칙을 기계가 읽을 수 있는
형태로 고정했다. 지금은 사람이 돌리고, 순서대로 코드로 대체한다.

## 채널 한 줄 정의

> 대한민국 직장인이 "아 맞아 저거"라고 말하게 만드는 40초짜리 **공감 + 꿀팁** 채널

**활성 축: A(공감) 50% / B(꿀팁) 50%.** C(정보)는 보류 — `docs/01` 참고.

## 설계 원칙: 규칙은 데이터, 문서는 해설

| 종류 | 위치 | 읽는 주체 |
|---|---|---|
| **규칙** | `config/*.yaml`, `data/topics.yaml` | 사람 + 스크립트 + LLM |
| **산출물** | `output/NNNN.json` (`schema/script.schema.json` 준수) | 스크립트 |
| **해설** | `docs/*.md` | 사람만 |

**같은 사실을 두 곳에 쓰지 않는다.** 금지어를 바꾸려면 `config/channel.yaml` 한 곳만 고친다.
`output/*.md` 는 JSON에서 생성되는 파생물이므로 직접 수정하지 않는다.

## 빠른 시작

```bash
pip install -r requirements.txt

# 1. 주제 고르기 (data/topics.yaml 에서 status: idea 인 것)
# 2. 대본 뼈대 생성
./scripts/new.sh -c A -k 상사 -t T002 "'편하게 말해봐'에 진짜 편하게 말하면 생기는 일"

# 3. prompts/generate-shorts.md 로 대본 채우기 (LLM)
# 4. 검수 게이트 — 통과해야 제작으로 넘어간다
./scripts/validate.py output/0002.json

# 5. 사람이 읽을 마크다운 생성
./scripts/render.py output/0002.json -w
```

## 파이프라인

```
01_collect  주제 수집    → data/topics.yaml        [수동]
02_select   주제 선별    → status: idea → queued   [수동]
03_script   대본 생성    → output/NNNN.json        [수동 + 프롬프트]
04_validate 검수 게이트  → scripts/validate.py     [자동 ✅]
05_produce  영상 생성    → TTS/녹음 + 자막 + 렌더  [미착수]
06_approve  사람 승인    →                         [의도적으로 사람]
07_upload   업로드       → YouTube Data API        [미착수]
08_measure  지표 수집    → 01로 되먹임             [미착수]
```

설계와 리스크는 **`docs/08-automation.md`** 에 있다. 자동화를 시작하기 전에 반드시 읽을 것.

## 파일 지도

| 경로 | 역할 |
|---|---|
| `config/channel.yaml` | 페르소나, 분량 기준, 금지어, 안전 규칙 |
| `config/axes.yaml` | 축 정의·비중(`active_mix`), 초 단위 구조 |
| `config/hooks.yaml` | 후킹 패턴 8종, 금지 도입부 |
| `data/topics.yaml` | 주제 뱅크 (단일 진실) |
| `schema/script.schema.json` | 대본 JSON 스키마 |
| `scripts/new.sh` | 대본 뼈대 생성 |
| `scripts/validate.py` | **검수 게이트** — 통과 못 하면 제작 금지 |
| `scripts/render.py` | JSON → 마크다운 |
| `docs/01`~`07` | 전략·대본공식·후킹·주제·제작·업로드·운영 해설 |
| `docs/08-automation.md` | 자동화 설계, 정책 리스크, API 제약 |
| `output/0001.*` | 검수를 통과한 샘플 대본 |

## 절대 규칙 4가지

1. **0~3초에 자기소개·인사·로고 금지.** 첫 프레임부터 상황이 시작된다.
2. **`scripts/validate.py` 를 통과하지 못한 대본은 제작하지 않는다.**
3. **실존 회사·상사를 특정할 수 있는 디테일 금지.** 모든 사례는 일반화·각색한다.
4. **모든 영상에 사람 고유 요소가 최소 1개 있어야 한다.**
   템플릿만 갈아끼운 대량 생산물은 YouTube `inauthentic content` 정책 대상이다 (`docs/08` §0).
