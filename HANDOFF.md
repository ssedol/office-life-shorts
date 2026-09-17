# JSON 형식 설명

로컬 파이프라인이 읽을 파일 형식입니다. **`output/0001.json` 을 열어놓고 보시면 빠릅니다.**

## 전체 모양

```json
{
  "id": "0001",
  "topic": "팀장이 한숨 쉴 때 하면 안 되는 것",
  "axis": "A",
  "total_sec": 45.0,

  "voice":       { "lang": "ko-KR", "style": "...", "speed": 1.05 },
  "image_style": "모든 씬에 공통으로 붙일 스타일 문자열",

  "scenes":  [ ... 7개 ... ],
  "youtube": { ... 업로드 정보 ... }
}
```

## scenes — 씬 7개

영상은 **항상 씬 7개**입니다. 순서대로 돌면서 만들면 됩니다.

```json
{
  "n": 1,
  "role": "HOOK",
  "start": 0.0,
  "end": 4.0,
  "tts": "월요일 아침, 팀장이 한숨 쉬면 하면 안 되는 게 있어요.",
  "caption": "월요일 아침 팀장 한숨",
  "image_prompt": "over the shoulder view of a person's back sitting at an office desk...",
  "motion": "zoom_in"
}
```

| 필드 | 뭘 하면 되나 |
|---|---|
| `tts` | **이 문장을 TTS에 넣으세요.** 이것만 소리로 나갑니다 |
| `caption` | 화면에 띄울 자막. `tts` 와 다릅니다 (짧게 축약된 강조 문구) |
| `image_prompt` | 이미지 생성 모델에 넣을 영문 프롬프트. **뒤에 `image_style` 을 붙여서** 넣으세요 |
| `motion` | 만들어진 정지 이미지에 줄 움직임 |
| `start` / `end` | 이 씬이 화면에 떠 있는 구간 (초) |

### motion 값

`zoom_in` · `zoom_out` · `pan_left` · `pan_right` · `static`

정지 이미지에 켄번즈 효과를 주는 용도입니다. 쇼츠는 화면이 멈추면 바로 이탈하기 때문에
`static` 이 연속으로 오지 않게 대본 단계에서 이미 배치해 뒀습니다.

### 씬 7개의 시간 배분

| 씬 | 역할 | 구간 | 글자 상한 |
|---|---|---|---|
| HOOK | 이탈 저지 | 0–4초 | 22자 |
| SETUP | 상황 세우기 | 4–9초 | 27자 |
| BODY1 | 1단계 | 9–16초 | 38자 |
| BODY2 | 2단계 | 16–23초 | 38자 |
| BODY3 | 3단계 | 23–31초 | 44자 |
| PAYOFF | 반전 한 줄 | 31–40초 | 49자 |
| CTA | 댓글 유도 질문 | 40–45초 | 27자 |

글자 상한은 **초당 5.5자**(공백·구두점 제외) 기준입니다. TTS 속도를 바꾸면 이 값도 달라집니다.
`voice.speed` 를 조정하셨다면 알려주세요, 대본 길이를 거기 맞춰 쓰겠습니다.

## voice — TTS 설정

```json
{ "lang": "ko-KR", "style": "30대 직장인, 담담하고 약간 지친 톤. 과장 없이 툭 던지듯", "speed": 1.05 }
```

`style` 은 톤 지시문입니다. 쓰시는 TTS 엔진이 이걸 못 받으면 무시하고 목소리만 고르시면 됩니다.
**어떤 엔진 쓰시는지 알려주시면 그 엔진이 받는 형식으로 맞춰 드리겠습니다.**

## image_style — 채널 톤 통일

```
photorealistic, modern Korean office interior, muted desaturated color grade,
soft window light, shallow depth of field, no visible faces, no text,
vertical 9:16 composition, cinematic
```

**얼굴을 넣지 않는 스타일로 잡았습니다.** 이유 두 가지:
- AI 생성 얼굴은 어색하게 나오는 경우가 많고, 같은 인물을 매 씬 일관되게 유지하기 어렵습니다
- 실존 인물처럼 보이는 얼굴은 초상권 문제가 생길 수 있습니다

바꾸고 싶으시면 말씀해 주세요. **이 문자열 하나만 고치면 채널 전체 톤이 바뀝니다.**

## youtube — 업로드 정보

```json
{
  "title": "팀장 한숨 3단계 구분법",
  "description": "...(해시태그와 면책 문구 포함된 완성 텍스트)...",
  "tags": ["#shorts", "#직장생활", "#팀장", "#직장인공감", "#직장인생존기"],
  "pinned_comment": "우리 팀장은 2단계에서 커피 타러 나가요. 그쪽은 몇 단계?",
  "thumbnail_text": "팀장 한숨 3단계",
  "made_for_kids": false,
  "ai_disclosure": true
}
```

| 필드 | 주의 |
|---|---|
| `title` | 25자 이내로 맞춰져 있습니다. 쇼츠는 제목이 잘립니다 |
| `description` | **그대로 넣으면 됩니다.** 해시태그·면책 문구까지 다 들어 있습니다 |
| `pinned_comment` | 업로드 직후 **댓글을 달고 고정**하세요. 첫 댓글이 비어 있으면 댓글이 안 달립니다 |
| `thumbnail_text` | 썸네일에 얹을 문구. 이미지는 로컬에서 만드세요 |
| `made_for_kids` | **항상 false.** 아동용으로 잡히면 댓글이 막힙니다 |
| `ai_disclosure` | **true면 업로드 시 "변경되거나 합성된 콘텐츠" 고지를 켜세요.** TTS·생성 이미지를 쓰므로 해당됩니다 |

## 영상 만들 때 꼭 지킬 것

`docs/05-production.md` 에 자세히 있지만, 코드에 박아야 할 건 이 세 가지입니다.

1. **해상도 1080×1920 (9:16)**
2. **자막 안전 영역** — 하단 25%, 우측 15%에 자막을 두지 마세요. 유튜브 UI가 덮습니다
3. **첫 프레임부터 자막이 떠 있어야 합니다.** 검은 화면으로 시작하면 바로 이탈합니다

## 업로드 자동화 붙이기 전에

⚠️ `docs/08-automation.md` 를 먼저 읽어주세요. 요약하면:

- YouTube Data API `videos.insert` 의 **할당량 수치가 자료마다 다릅니다.**
  [공식 계산기](https://developers.google.com/youtube/v3/determine_quota_cost)로 직접 확인하세요.
- **완전 무인 업로드는 권하지 않습니다.** 업로드 직전에 사람이 한 번 보는 단계를 두세요.
  무인으로 아끼는 건 하루 10분이고, 잃을 수 있는 건 채널 전체입니다.
