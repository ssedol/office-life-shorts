# 오늘도출근 Shorts Factory

직장인 공감형 YouTube Shorts 채널 **오늘도출근**의 반자동 제작 시스템입니다.
ChatGPT가 만든 이미지 8장과 씬 구성을 폴더에 넣으면, 나머지 공정을 자동으로 처리합니다.

SSOT는 `TODAY_TO_WORK_PROJECT_SPEC.md` (명세서 v1.0)이고, 이 저장소는 그 구현입니다.

> 저장소 이름은 `office-life-shorts`이지만, 명세서 §1.1의 권장 이름은 `today-to-work-shorts`입니다.
> 코드 동작에는 영향이 없습니다.

---

## 역할 분담

| 단계 | 담당 | 결과물 |
|---|---|---|
| 주제 / 제목 / 대본 / 8씬 구성 | 외부 AI | `script.txt`, 씬 구성 |
| 씬 이미지 8장 + STILL/I2V 판단 | **ChatGPT** | `scene-01~08.png`, `scene-plan.json` |
| I2V / TTS / 자막 / 타임라인 / 렌더 | **이 저장소** | `preview.mp4`, `final.mp4` |
| 검수 및 업로드 | 사람 | — |

로컬 시스템은 **이미지를 생성하지 않고, STILL/I2V를 재판단하지 않습니다** (명세서 §33-1, §33-2).

---

## 설치

```bash
# 1. 시스템 의존성
sudo apt-get install ffmpeg fonts-nanum      # Ubuntu/Debian
# brew install ffmpeg                         # macOS (한글 폰트는 기본 내장)

# 2. 파이썬 패키지
pip install -r requirements.txt

# 3. 설치 확인
python main.py --input ./inputs/2026-09-18 --validate-only
```

Python 3.10 이상이 필요합니다.

---

## 빠른 시작

저장소에는 바로 돌려볼 수 있는 샘플 입력(`inputs/2026-09-18/`)이 들어 있습니다.

```bash
# Preview 렌더 (LTX 2.5 없이 먼저 확인)
python main.py --input ./inputs/2026-09-18 --skip-i2v

# 검수 후 Final 렌더
python main.py --input ./inputs/2026-09-18 --mode final
```

결과는 `outputs/2026-09-18/` 에 생깁니다.

> 샘플 이미지는 `inputs/2026-09-18/image-prompts.md`의 프롬프트로 만든 실제 생성본입니다.
> 도형만 있는 자리표시자가 필요하면 `python tools/make_sample_images.py <폴더>` 로 만들 수 있습니다.

---

## 처리 흐름

```text
inputs/YYYY-MM-DD/
        │
        ▼
  ① 입력 검증        8씬 / 이미지 8장 / type / videoPrompt / durationSec
        │
        ▼
  ② TTS              씬별 한국어 내레이션 합성 + 실제 길이 측정
        │
        ▼
  ③ 타임라인 구성     씬 길이 = leadIn + TTS길이 + tailPad (말이 끝나면 다음 씬)
        │
        ▼
  ④ STILL / I2V 분기  I2V 씬만 LTX 2.5 호출, 실패하면 STILL fallback
        │
        ▼
  ⑤ 내레이션 합치기   씬 길이에 맞춰 패딩 → narration.wav
        │
        ▼
  ⑥ 자막             subtitles.srt / subtitles.ass / subtitle-timeline.json
        │
        ▼
  ⑦ Preview 렌더  →  사람 검수  →  Final 렌더
```

③에서 씬 길이는 **실제 내레이션 길이**로 정해집니다 (`timeline.fitToNarration`, 기본 켜짐).
`scene-plan.json`의 `durationSec`을 하한으로 쓰면 말이 끝난 뒤 정지 화면이 남아 영상이 늘어집니다.
실측에서 40초 영상의 22%(9초)가 그런 빈 시간이었습니다. `false`로 두면 종전 동작입니다.

**명세서 §3.1과 순서가 한 군데 다릅니다.** 명세서는 I2V → TTS 순이지만,
씬 길이가 실제 TTS 길이에 의존하기 때문에(명세서 §31 RISK-3) TTS를 먼저 돌리고
확정된 길이를 I2V에 넘깁니다. 입력이 같으면 결과도 같으므로 논리적 순서는 그대로입니다.

---

## 입력 패키지 (명세서 §10)

```text
inputs/2026-09-18/
├─ project.json          채널/날짜/제목/해상도/TTS 설정
├─ script.txt            전체 대본 (사람이 읽는 원본)
├─ scene-plan.json       8씬 구성 + STILL/I2V 판단 + 내레이션/자막
└─ scene-01.png ~ scene-08.png
```

JSON 형식은 `schema/project.schema.json`, `schema/scene-plan.schema.json` 에 정의돼 있습니다.
편집기에 스키마를 연결하면 필드 누락을 바로 잡을 수 있습니다.

### scene-plan.json 씬 1개

```json
{
  "id": "SCENE-02",
  "order": 2,
  "durationSec": 4,
  "type": "I2V",
  "reason": "상사와 주인공 상호작용이 핵심",
  "imageFile": "scene-02.png",
  "narration": "팀장님이 갑자기 일을 하나 넘깁니다.",
  "subtitle": "팀장님이 일을 넘길 때",
  "videoPrompt": "A young office worker looks slightly surprised ..."
}
```

- `type`이 `I2V`면 `videoPrompt`가 **필수**입니다.
- `type`이 `STILL`이면 `motion`을 선택적으로 넣습니다 (`static` / `slow_zoom_in` / `slow_zoom_out` / `slow_pan_left` / `slow_pan_right`). 생략하면 `slow_zoom_in`.
- `seed`를 넣으면 I2V 결과를 재현할 수 있습니다.

### 자막 강조

명세서 §19의 "중요 단어 노란색"을 위해 `subtitle` 값 안에서 `**`로 감쌉니다.

```json
"subtitle": "먼저 꺼내면 **손해** 보는 말"
```

마크업이 없으면 전부 흰색으로 나오므로, 기존 입력과도 호환됩니다.
항상 강조할 단어는 `config/subtitle.json`의 `emphasisKeywords`에 넣어두면 됩니다.

### 댓글 유도는 훅과 마무리 두 군데

쇼츠에서 댓글은 노출에 직접 영향을 주는데, 대본을 쓰다 보면 가장 빠뜨리기 쉽습니다.
**SCENE-01(훅)과 SCENE-08(마무리)** 양쪽에 시청자에게 던지는 질문을 넣으세요.
끝까지 본 사람과 중간에 이탈한 사람, 양쪽에서 댓글이 나옵니다.
없으면 검증 단계에서 경고합니다 (실패는 아닙니다).

**훅에서는 자막을 건드리지 마세요.** 자막은 훅 문구 그대로 두고 내레이션에만
질문을 붙여야 훅이 약해지지 않습니다.

```json
// SCENE-01 — 자막은 훅 그대로, 내레이션 끝에만 질문
"narration": "회사에서 이 말, 먼저 꺼내면 괜히 손해 봅니다. 여러분도 해보셨죠?",
"subtitle": "먼저 꺼내면 **손해** 보는 말"

// SCENE-08 — 자막까지 질문형으로
"narration": "내 일이 아니라는 말, 순서 질문으로 바꿔보세요. 여러분은 이럴 때 어떻게 말하세요?",
"subtitle": "여러분은 **어떻게** 말하세요?"
```

명세서 §1.2의 "가볍고 재밌는 공감형" 톤에 맞춰, 딱딱한 "구독 좋아요"보다
질문형이 이 채널에 맞습니다.

| 위치 | 문구 예시 |
|---|---|
| 훅 | "여러분도 해보셨죠?" / "혹시 오늘도 하셨어요?" / "저만 그런가요?" |
| 마무리 | "여러분은 이럴 때 어떻게 말하세요?" / "여러분 회사에도 이런 분 있나요?" / "다들 어떻게 넘기시는지 궁금하네요." |

확인할 위치는 `config/app.json`의 `cta.scenes`(`["first", "last"]`),
인식 기준은 `cta.patterns`에서 조정하고, `cta.required`를 `false`로 두면 검사를 끕니다.

---

## CLI (명세서 §24)

```bash
python main.py --input ./inputs/2026-09-18 [옵션]
```

| 옵션 | 설명 |
|---|---|
| `--mode preview\|final` | 렌더 모드. 기본 `preview` |
| `--skip-i2v` | LTX 2.5 호출을 건너뛰고 I2V 씬도 정지 이미지로 렌더 |
| `--force` | 기존 결과물 덮어쓰기 + Preview 없이 Final 허용 |
| `--validate-only` | 입력 검증만 수행 |
| `--tts-engine NAME` | `config/tts.json`의 engine을 덮어씀 (`edge` / `supertonic` / `cli` / `offline`) |
| `--tts-voice VOICE` | 보이스를 덮어씀 |
| `--output DIR` | 출력 폴더 직접 지정 |
| `--config DIR` | config 폴더 경로 |
| `--keep-work` | 중간 파일(`.work`)을 남김 |
| `-v` / `-q` | 상세 로그 / 경고 이상만 |

**Preview → 검수 → Final 순서는 강제됩니다** (명세서 §21, §33-6).
`preview.mp4` 없이 `--mode final`을 실행하면 중단되고, 정말 건너뛰려면 `--force`가 필요합니다.

---

## 출력 (명세서 §23)

```text
outputs/2026-09-18/
├─ preview.mp4              검수용
├─ final.mp4                최종본
├─ narration.wav            내레이션 (전체 길이에 맞춰 패딩됨)
├─ subtitles.srt            표준 자막 (업로드/검수용)
├─ subtitles.ass            번인 렌더용 (외곽선/강조색/안전영역 포함)
├─ subtitle-timeline.json   자막 타임라인
├─ render-log.json          실행 기록
└─ scenes/                  씬별 클립 8개
```

---

## 설정 (`config/`)

| 파일 | 내용 |
|---|---|
| `app.json` | 씬 수, 길이 범위, 타임라인(`fitToNarration`), 댓글 유도 검사, ffmpeg 경로 |
| `render.json` | 해상도/fps, 모션 강도, preview·final 프로파일, BGM |
| `tts.json` | 엔진 선택, 보이스, 속도, 음량 정규화, 재시도 |
| `subtitle.json` | 폰트, 색상, 줄 수, 안전영역, 강조 마크업 |
| `i2v.json` | ComfyUI 주소, workflow 파일, **주입 매핑**, fallback |

우선순위는 **CLI 옵션 > `project.json` > `config/*.json`** 입니다.
`resolution` / `fps` / `tts`는 `project.json`에서 영상별로 덮어쓸 수 있습니다.

각 JSON 안의 `$comment` 필드에 해당 설정의 의미와 관련 명세서 절이 적혀 있습니다.

---

## LTX 2.5 I2V 연동

**`workflows/ltx25_i2v.json`은 자리표시자입니다.** 실제 워크플로우로 교체해야 I2V가 동작합니다.
교체 방법과 주입 매핑 설명은 [`workflows/README.md`](workflows/README.md)를 보세요.

요약하면:

1. ComfyUI에서 **Workflow → Export (API)** 로 저장
2. `workflows/ltx25_i2v.json` 으로 덮어쓰기
3. `config/i2v.json`의 `inject` 에 적힌 `node` 값을 실제 노드 ID로 수정

커넥터는 워크플로우 구조를 전혀 가정하지 않습니다. 매핑이 틀리면
어떤 노드/입력을 못 찾았는지 오류 메시지에 그대로 나옵니다 (명세서 §17).

### I2V 실패 시 (명세서 §16)

ComfyUI가 꺼져 있든, 매핑이 틀렸든, 생성이 실패하든 **전체 제작은 중단되지 않습니다.**
해당 씬은 원본 이미지 + `slow_zoom_in`으로 대체되고 `render-log.json`에 기록됩니다.

```json
"i2v": { "SCENE-02": "success", "SCENE-05": "fallback_still" }
```

---

## TTS

기본 엔진은 **edge-tts**입니다. 무료이고 한국어 뉴럴 보이스 품질이 좋지만 **인터넷 연결이 필요합니다.**

```bash
# 사용 가능한 한국어 보이스 확인
python -m edge_tts --list-voices | grep ko-KR
```

`config/tts.json`의 `engine`만 바꾸면 다른 어댑터로 교체됩니다.

| engine | 설명 |
|---|---|
| `edge` | 기본. 무료 한국어 뉴럴 보이스. 인터넷 필요 |
| `supertonic` | 명세서 §18이 지목한 로컬 엔진 자리. `cliPath`와 `args`를 채우면 동작 |
| `cli` | 임의의 로컬 TTS 실행 파일 브리지 |
| `offline` | **무음 자리표시자.** 네트워크 없는 환경에서 파이프라인 점검용. 실제 제작에는 쓰지 않음 |

새 엔진을 붙이려면 `src/tts/base.py`의 `TTSProvider`를 구현하고
`src/tts/factory.py`의 `REGISTRY`에 등록하면 됩니다.
WAV 변환·음량 정규화·길이 패딩은 공통 코드가 처리하므로 다시 구현할 필요가 없습니다.

---

## 렌더러 교체

현재 구현은 `FFmpegRenderer` 하나입니다 (명세서 §35-1에서 FFmpeg로 확정).
Remotion 등으로 바꾸려면 `src/render/base.py`의 `Renderer` 인터페이스만 구현하면 됩니다.
타임라인·자막·내레이션은 렌더러와 무관하게 이미 만들어져 있으므로,
새 렌더러는 `RenderJob → mp4 한 개`만 책임지면 됩니다.

---

## 테스트

```bash
pytest                    # 전체
pytest -m "not slow"      # 1080×1920 실제 렌더 테스트 제외
pytest tests/test_04_i2v.py -v
```

명세서 §28의 TEST-1 ~ TEST-10을 파일 단위로 대응시켰습니다.

| 파일 | 대응 |
|---|---|
| `test_01_validation.py` | TEST-1 입력 검증 / TEST-2 씬 수 |
| `test_02_config_cli.py` | 설정 로딩, CLI 옵션, 번들 샘플·스키마 정합성 |
| `test_03_still.py` | TEST-3 STILL 모션 |
| `test_04_i2v.py` | TEST-4 I2V 호출 / TEST-5 fallback |
| `test_06_tts.py` | TEST-6 TTS |
| `test_07_subtitle.py` | TEST-7 자막 |
| `test_08_pipeline.py` | TEST-8 렌더 / TEST-9 싱크 / TEST-10 반복 실행 |

I2V 테스트는 `tests/fake_comfyui.py`의 가짜 ComfyUI 서버를 띄워
실제 HTTP 프로토콜(업로드 → 제출 → 폴링 → 다운로드)을 그대로 검증합니다.
ComfyUI 설치 없이 돌아갑니다.

---

## 오류 코드 (명세서 §25)

| 코드 | 정책 |
|---|---|
| `ERR_INPUT_MISSING` | 중단 |
| `ERR_SCENE_COUNT` | 중단 |
| `ERR_SCENE_IMAGE_MISSING` | 중단 |
| `ERR_INVALID_SCENE_TYPE` | 중단 |
| `ERR_I2V_FAILED` | **fallback 후 계속** |
| `ERR_TTS_FAILED` | 중단 |
| `ERR_SUBTITLE_FAILED` | 중단 |
| `ERR_RENDER_FAILED` | 중단 |
| `ERR_CONFIG_INVALID` | 중단 (명세서 목록 외 추가) |
| `ERR_DEPENDENCY_MISSING` | 중단 (명세서 목록 외 추가) |

검증 오류는 첫 항목에서 멈추지 않고 **전부 모아서** 출력합니다 (명세서 §14).

---

## 폴더 구조

```text
.
├─ main.py                 CLI 진입점
├─ config/                 설정 5종
├─ schema/                 project / scene-plan JSON Schema
├─ workflows/              LTX 2.5 ComfyUI workflow (교체 필요)
├─ inputs/YYYY-MM-DD/      입력 패키지
├─ outputs/YYYY-MM-DD/     결과물
├─ tools/                  샘플 이미지 생성기
├─ tests/                  TEST-1 ~ TEST-10
└─ src/
   ├─ config.py            설정 병합 + .env
   ├─ errors.py            오류 코드
   ├─ pipeline.py          오케스트레이션
   ├─ loader/              입력 패키지 로딩
   ├─ validator/           FEAT-1 입력 검증
   ├─ scene/               모델, 타임라인, FEAT-2 STILL 모션
   ├─ i2v/                 FEAT-3 LTX 2.5 커넥터 + fallback
   ├─ tts/                 FEAT-4 Provider 인터페이스 + 어댑터
   ├─ subtitle/            FEAT-5 자막 생성
   ├─ render/              FEAT-6 렌더러 인터페이스 + FFmpeg 구현
   ├─ media/               ffmpeg / ffprobe 래퍼
   └─ logger/              render-log.json
```

---

## 보안 (명세서 §26)

- API Key는 `.env`에 두고, `.env`는 커밋하지 않습니다 (`.gitignore`에 포함).
- 계정 비밀번호·결제정보는 저장하지 않습니다.
- 개인정보를 수집하지 않고, 로컬 영상 제작 데이터만 저장합니다.

`.env.example`을 복사해 쓰세요. MVP는 유료 API를 쓰지 않으므로 값은 전부 선택 사항입니다.

---

## 확정된 결정 (명세서 §35)

| 항목 | 결정 |
|---|---|
| 렌더러 | **FFmpeg** (Renderer 인터페이스로 교체 가능) |
| TTS | **edge-tts** 기본, Provider 교체 가능 |
| 자막 폰트 | `fontFile` → `fontCandidates` → 시스템 폰트 순으로 자동 탐색 (Linux는 NanumGothic Bold) |
| BGM/SFX | **MVP 제외.** `config/render.json`의 `bgm`에 파일을 넣고 켜면 동작 |
| LTX workflow | 주입 매핑 구조. 사용자가 안정화한 workflow JSON을 그대로 재사용 |
