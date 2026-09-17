# office-life-shorts

직장인 대상 유튜브 쇼츠 채널 운영 시스템.
**주제 하나를 입력하면 → 업로드 직전 상태의 쇼츠 대본 + 메타데이터가 나오는 구조**를 목표로 한다.

## 채널 한 줄 정의

> 대한민국 직장인이 "아 맞아 저거"라고 말하게 만드는 40초짜리 공감 + 꿀팁 채널

## 폴더 구조

| 경로 | 역할 |
|---|---|
| `docs/01-channel-strategy.md` | 채널 포지셔닝, 타겟, 콘텐츠 3축, 심리학 채널과의 차이 |
| `docs/02-script-formula.md` | 초 단위 대본 공식 (공감형 / 꿀팁형 / 정보형) |
| `docs/03-hook-library.md` | 0~3초 후킹 문장 라이브러리 + 금지 패턴 |
| `docs/04-topic-bank.md` | 주제 뱅크 (카테고리별 시드 60개) |
| `docs/05-production.md` | 화면·자막·BGM·편집 규칙 |
| `docs/06-upload-meta.md` | 제목 / 설명 / 해시태그 / 고정댓글 규칙 |
| `docs/07-ops-loop.md` | 업로드 주기, 성과 지표, 개선 루프 |
| `templates/topic-brief.md` | 주제 입력 폼 (여기에 주제를 적는다) |
| `templates/script.md` | 대본 산출물 템플릿 |
| `prompts/generate-shorts.md` | 주제 → 완성 대본 변환용 프롬프트 (LLM에 그대로 붙여넣기) |
| `scripts/new.sh` | `./scripts/new.sh "주제"` → `output/`에 대본 뼈대 생성 |
| `output/` | 회차별 완성 대본 (`0001-주제.md`) |

## 작업 흐름

```
주제 선정 (docs/04-topic-bank.md)
  ↓
./scripts/new.sh -c 공감 "월요일 아침 팀장 표정 읽는 법"
  ↓
output/0001-*.md 생성
  ↓
prompts/generate-shorts.md 프롬프트로 대본 채우기
  ↓
docs/02 공식 + docs/03 후킹 기준으로 자가 검수
  ↓
영상 편집 (docs/05-production.md 규칙)
  ↓
업로드 (docs/06-upload-meta.md 메타데이터)
  ↓
48시간 후 지표 확인 (docs/07-ops-loop.md)
```

## 절대 규칙 3가지

1. **0~3초에 자기소개·인사·로고 금지.** 첫 프레임부터 상황이 시작된다.
2. **정보형(법·제도·급여) 콘텐츠는 1차 출처 확인 없이 업로드 금지.** 틀린 노무 정보는 채널 신뢰를 한 번에 태운다.
3. **실존 회사·상사를 특정할 수 있는 디테일 금지.** 모든 사례는 일반화·각색한다.
