# 오늘도출근 Shorts Factory — 개발 명세서 v1.0

> 이 문서는 직장인 공감형 YouTube Shorts 채널 **오늘도출근**의 반자동 제작 시스템을 구현하기 위한 SSOT(Single Source of Truth)다.
>
> 핵심 전제:
> - 주제/대본/8씬 구성은 외부 AI가 담당한다.
> - **씬 이미지 8장 생성은 ChatGPT가 담당한다.**
> - **씬별 STILL / I2V 판단도 ChatGPT가 담당한다.**
> - 로컬 프로젝트는 이미지 이후 공정만 처리한다.
> - I2V는 **LTX 2.5 I2V**를 사용한다.
> - TTS는 초기에는 무료 한국어 TTS를 사용한다.
> - 기본 출력은 **8씬 / 35~45초 / 9:16 / 1080×1920**이다.

---

# 1. 프로젝트 개요

## 1.1 프로젝트명

**오늘도출근 Shorts Factory**

권장 로컬 저장소명:

```text
today-to-work-shorts
```

## 1.2 채널 정의

채널명:

```text
오늘도출근
```

채널 주제:

- 직장생활
- 회사 인간관계
- 직장인 공감
- 사회생활 꿀팁
- 회사에서의 말하기/처세
- 가벼운 직장인 공감썰

콘텐츠 톤:

- 가볍고 재밌는 공감형
- 과도한 자기계발/훈계조 금지
- “회사 다녀본 사람은 바로 알아듣는” 느낌
- 역할극보다 **1인 내레이션 중심**
- 짧고 바로 써먹을 수 있는 팁 중심

---

# 2. 문제 정의

현재 수작업 제작에는 다음 문제가 있다.

1. 매일 주제와 대본을 만들고 씬을 나눠야 한다.
2. 각 씬을 정지 이미지로 쓸지 영상화할지 매번 판단해야 한다.
3. 캐릭터/채널 비주얼 일관성을 유지해야 한다.
4. 이미지, 영상, TTS, 자막, 렌더를 각각 수동 관리해야 한다.
5. 이미지 생성까지 로컬 자동화에 넣으면 초기 개발 범위가 과도하게 커진다.
6. 초기 단계에서는 완전 자동화보다 품질 검수 가능한 반자동 구조가 더 현실적이다.

---

# 3. 목표

## 3.1 MVP 목표

외부 AI와 ChatGPT가 만든 입력 패키지를 로컬 프로젝트에 넣으면 다음을 자동 수행한다.

```text
입력 검증
↓
STILL / I2V 분기
↓
I2V 대상 씬 → LTX 2.5
↓
TTS 생성
↓
자막 생성
↓
타임라인 구성
↓
Preview 렌더
↓
사람 검수
↓
Final 렌더
```

## 3.2 운영 목표

- 하루 1편 수준의 반복 제작 가능
- 이미지 생성 이후 작업 최소화
- 캐릭터/채널 스타일 일관성 유지
- 실패한 I2V 씬은 정지 이미지로 자동 대체
- 향후 TTS/BGM/렌더러 교체 가능
- 향후 Web UI나 스케줄러 확장 가능

---

# 4. 비목표(Non-Goals)

MVP에서 하지 않는다.

- 로컬 T2I/I2I 이미지 생성
- 완전 무인 주제 선정
- 완전 자동 YouTube 업로드
- 멀티보이스 역할극
- 자동 성과 분석
- 여러 채널 동시 운영
- AI가 로컬에서 STILL/I2V를 재판단하는 기능

---

# 5. 페르소나

## Persona-1. 채널 운영자

- 1인 쇼츠 채널 운영자
- 반복 작업을 최대한 줄이고 싶음
- 로컬 PC에서 ComfyUI/LTX 2.5 사용 가능
- 결과물은 반드시 사람 검수 후 업로드

## Persona-2. 구현 개발자/다른 AI

- 본 문서 기반으로 로컬 자동화 구현
- 이미지 생성은 외부 입력으로 간주
- I2V/TTS/자막/렌더 파이프라인 구현에 집중

---

# 6. 사용자 스토리

## US-1

채널 운영자로서, 나는 오늘의 주제와 씬 구성이 준비되면 ChatGPT가 만든 이미지 8장을 로컬 프로젝트에 넣고 자동으로 Preview 영상을 만들고 싶다.

## US-2

개발자로서, 나는 이미지 생성 기능 없이도 입력 규격만 맞으면 동일한 영상 제작 공정을 반복 실행할 수 있어야 한다.

## US-3

채널 운영자로서, I2V가 실패해도 전체 제작이 중단되지 않고 해당 씬이 정지 이미지로 대체되길 원한다.

---

# 7. 역할 분담

## 7.1 외부 AI / 기획 AI

담당:

- 오늘 주제 선정
- 제목/훅
- 35~45초 대본
- 8씬 구성
- 씬별 상황 설명
- 씬별 핵심 대사

## 7.2 ChatGPT

담당:

### A. 이미지 생성
- `scene-01.png` ~ `scene-08.png`
- 오늘도출근 캐릭터 스타일 유지
- 씬 상황에 맞게 표정/구도/배경/소품 조정
- 세로 9:16 기준

### B. STILL / I2V 판단
각 씬마다:

- `STILL` 또는 `I2V`
- 추천 이유
- I2V일 경우 LTX 2.5용 `videoPrompt`

### C. 캐릭터 스타일 관리

고정 요소:

- 젊은 남성 직장인 chibi 캐릭터
- 검은색/짙은 갈색의 약간 헝클어진 머리
- 흰 셔츠
- 네이비 넥타이
- 파란 사원증
- 밝은 노란색 오피스 분위기
- 굵은 네이비 외곽선
- 친근한 한국 웹툰/캐릭터 일러스트 느낌

## 7.3 로컬 자동화 시스템

담당:

- 입력 검증
- STILL 씬 처리
- I2V 씬 LTX 2.5 실행
- TTS 생성
- 자막 생성
- 타임라인 구성
- Preview 렌더
- Final 렌더
- 로그 기록

---

# 8. 콘텐츠 포맷

## 8.1 길이

```text
최소: 35초
권장: 40초
최대: 45초
```

## 8.2 씬 수

```text
항상 8씬
```

## 8.3 권장 구조

```text
SCENE-01 Hook
SCENE-02 상황
SCENE-03 공감
SCENE-04 문제 설명
SCENE-05 반응/오해
SCENE-06 해결법
SCENE-07 적용 예시
SCENE-08 마무리
```

구체적인 의미는 영상별로 조정 가능하나 **씬 수는 8개 유지**.

---

# 9. STILL / I2V 판단 기준

판단 주체는 **ChatGPT**다.

로컬 시스템은 이를 재판단하지 않는다.

## 9.1 I2V 우선 조건

- 사람 간 상호작용이 중요
- 표정 변화가 의미를 가짐
- 시선 이동이 중요
- 어색한 분위기/반응이 핵심
- 바쁜 사무실 분위기처럼 움직임 자체가 의미 있음
- 엔딩에 움직임이 있으면 완성도가 크게 좋아짐

## 9.2 STILL 우선 조건

- 정보 전달 중심
- 큰 자막/문구 중심
- 생각/고민 장면
- 체크리스트/보드/설명 장면
- 줌/팬으로 충분
- 영상화해도 전달력이 크게 증가하지 않음

## 9.3 권장 비율

```text
STILL: 5~6씬
I2V: 2~3씬
```

---

# 10. 입력 패키지

예시:

```text
inputs/2026-09-18/
```

필수 파일:

```text
project.json
script.txt
scene-plan.json
scene-01.png
scene-02.png
scene-03.png
scene-04.png
scene-05.png
scene-06.png
scene-07.png
scene-08.png
```

---

# 11. project.json

예시:

```json
{
  "channel": "오늘도출근",
  "date": "2026-09-18",
  "topic": "회사에서 이 말 먼저 하면 손해 봅니다",
  "title": "회사에서 이 말, 먼저 꺼내면 손해 봅니다",
  "durationTargetSec": 40,
  "sceneCount": 8,
  "resolution": {
    "width": 1080,
    "height": 1920
  },
  "fps": 30,
  "tts": {
    "engine": "supertonic",
    "voice": "UNDECIDED",
    "speed": 1.05
  },
  "renderMode": "preview"
}
```

---

# 12. scene-plan.json

예시:

```json
{
  "scenes": [
    {
      "id": "SCENE-01",
      "order": 1,
      "durationSec": 4,
      "type": "STILL",
      "reason": "훅 자막과 표정 전달이 핵심",
      "imageFile": "scene-01.png",
      "narration": "회사에서 이 말, 먼저 꺼내면 괜히 손해 봅니다.",
      "subtitle": "회사에서 이 말 먼저 하면 손해",
      "motion": "slow_zoom_in"
    },
    {
      "id": "SCENE-02",
      "order": 2,
      "durationSec": 4,
      "type": "I2V",
      "reason": "상사와 주인공 상호작용이 핵심",
      "imageFile": "scene-02.png",
      "narration": "이건 제 일이 아닌데요?",
      "subtitle": "이건 제 일이 아닌데요?",
      "videoPrompt": "A young office worker looks slightly surprised and awkward as a manager hands over documents. Keep the original character design and office layout unchanged. Add subtle blinking, slight head movement, small hand hesitation, and a very slow camera push-in."
    }
  ]
}
```

필수 필드:

```text
id
order
durationSec
type
reason
imageFile
narration
subtitle
```

STILL일 때 선택 필드:

```text
motion
```

I2V일 때 필수 필드:

```text
videoPrompt
```

---

# 13. 이미지 규격

파일명:

```text
scene-01.png ~ scene-08.png
```

기본 비율:

```text
9:16
```

원칙:

- 캐릭터가 핵심
- 자막 공간 확보
- 배경 과밀 금지
- 이미지 내부 긴 텍스트 금지
- I2V 대상 이미지는 복잡한 손동작/포즈를 피함
- 같은 영상 내 캐릭터 외형을 최대한 통일

---

# 14. FEAT-1 입력 검증

실행 전 필수 검증:

- project.json 존재
- scene-plan.json 존재
- script.txt 존재
- 씬 개수 정확히 8
- 이미지 8장 존재
- `type` 값이 `STILL` 또는 `I2V`
- I2V 씬에 videoPrompt 존재
- durationSec > 0

오류 시:

- 렌더 시작 금지
- 누락/오류 항목을 명확히 출력

---

# 15. FEAT-2 STILL 처리

지원 모션:

```text
static
slow_zoom_in
slow_zoom_out
slow_pan_left
slow_pan_right
```

원칙:

- 씬당 1개 효과
- 확대/팬 과도 금지
- 자막 방해 금지
- 입력 이미지 종횡비 유지

---

# 16. FEAT-3 LTX 2.5 I2V

사용 모델:

```text
LTX 2.5 I2V
```

입력:

- scene 이미지
- videoPrompt
- LTX 2.5 workflow JSON
- 실행 config

출력:

```text
scene-XX.mp4
```

기본 원칙:

- 3~5초
- 작은 움직임
- 눈 깜빡임
- 약한 고개 움직임
- 작은 손동작
- 시선 변화
- 느린 camera push-in

피해야 할 것:

- 걷기/달리기
- 큰 자세 변화
- 복잡한 군중
- 과도한 카메라 이동
- 새 객체 생성
- 복잡한 손동작
- 장면 전체 변형

## Fallback

```text
I2V 실패
→ 원본 이미지를 STILL로 사용
→ slow_zoom_in 기본 적용
→ render-log.json에 기록
```

---

# 17. LTX 2.5 Workflow 연동

워크플로우 파일:

```text
workflows/ltx25_i2v.json
```

로컬 자동화에서 다음 값을 주입 가능해야 한다.

- 입력 이미지 경로
- positive prompt
- seed
- width
- height
- frame count 또는 duration
- fps
- output path

중요:
사용자가 별도로 안정화한 ComfyUI LTX 2.5 I2V workflow JSON을 그대로 재사용할 수 있게 구현한다.

---

# 18. FEAT-4 TTS

방향:

- 한국어
- 1인 내레이션
- 무료 솔루션 우선
- 친근한 직장 동료 느낌
- 뉴스/아나운서 톤 지양

초기 후보:

```text
Supertonic 계열
```

단, 보이스는 아직 최종 확정하지 않음.

TTS 구조는 Provider 교체 가능하게 만든다.

예:

```text
TTSProvider
├─ SupertonicAdapter
├─ ClovaAdapter
└─ FutureProvider
```

출력:

```text
narration.wav
```

필수:

- 속도 조절
- WAV 출력
- 음량 정규화
- 오류 반환

---

# 19. FEAT-5 자막

기본 스타일:

- 굵은 고딕 계열
- 기본 글자: 흰색
- 외곽선: 짙은 네이비
- 중요 단어: 노란색 강조
- 최대 2줄
- 가운데 정렬
- 모바일 안전영역 고려

출력:

```text
subtitles.srt
subtitle-timeline.json
```

---

# 20. FEAT-6 렌더링

권장 렌더러:

```text
Remotion
```

대안:

```text
FFmpeg
```

구조는 렌더러 교체 가능하게 구현.

최종 출력:

```text
1080×1920
30fps
H.264 MP4
```

---

# 21. Preview / Final

## Preview

출력:

```text
preview.mp4
```

검수 항목:

- I2V 왜곡
- TTS 발음
- 자막 타이밍
- 씬 길이
- 캐릭터 일관성
- 전체 흐름

## Final

Preview 승인 후 생성:

```text
final.mp4
```

MVP에서 Preview 단계를 생략하지 않는다.

---

# 22. 로그

출력:

```text
render-log.json
```

예:

```json
{
  "i2v": {
    "SCENE-02": "success",
    "SCENE-05": "fallback_still"
  },
  "tts": "success",
  "subtitle": "success",
  "render": "success"
}
```

로그 항목:

- 시작/종료 시간
- 씬별 처리 상태
- I2V fallback 여부
- TTS 성공/실패
- 자막 성공/실패
- 렌더 성공/실패
- 전체 소요 시간

---

# 23. 권장 폴더 구조

```text
today-to-work-shorts/
│
├─ inputs/
│  └─ YYYY-MM-DD/
│     ├─ project.json
│     ├─ script.txt
│     ├─ scene-plan.json
│     ├─ scene-01.png
│     ├─ scene-02.png
│     ├─ scene-03.png
│     ├─ scene-04.png
│     ├─ scene-05.png
│     ├─ scene-06.png
│     ├─ scene-07.png
│     └─ scene-08.png
│
├─ workflows/
│  └─ ltx25_i2v.json
│
├─ config/
│  ├─ app.json
│  ├─ render.json
│  ├─ tts.json
│  └─ subtitle.json
│
├─ src/
│  ├─ loader/
│  ├─ validator/
│  ├─ scene/
│  ├─ i2v/
│  ├─ tts/
│  ├─ subtitle/
│  ├─ render/
│  └─ logger/
│
├─ outputs/
│  └─ YYYY-MM-DD/
│     ├─ preview.mp4
│     ├─ final.mp4
│     ├─ narration.wav
│     ├─ subtitles.srt
│     ├─ render-log.json
│     └─ scenes/
│
└─ README.md
```

---

# 24. CLI 요구사항

예:

```bash
npm run build-short -- --input ./inputs/2026-09-18
```

또는:

```bash
python main.py --input ./inputs/2026-09-18
```

권장 옵션:

```text
--mode preview
--mode final
--skip-i2v
--force
```

---

# 25. 오류 코드

예:

```text
ERR_INPUT_MISSING
ERR_SCENE_COUNT
ERR_SCENE_IMAGE_MISSING
ERR_INVALID_SCENE_TYPE
ERR_I2V_FAILED
ERR_TTS_FAILED
ERR_SUBTITLE_FAILED
ERR_RENDER_FAILED
```

정책:

- I2V 실패: fallback 후 계속
- TTS 실패: 중단
- 자막 실패: 중단
- 최종 렌더 실패: 중단

---

# 26. 권한/보안

- API Key는 `.env`
- `.env` Git 커밋 금지
- 계정 비밀번호 저장 금지
- 결제정보 저장 금지
- 개인정보 수집 불필요
- 로컬 영상 제작 데이터만 저장

---

# 27. 접근성

- 자막 필수
- 한 화면 최대 2줄
- 모바일에서도 읽히는 크기
- 색상만으로 정보 전달 금지
- 자막 안전영역 유지
- 빠른 전환으로 가독성 저하 금지

---

# 28. 테스트 전략

## TEST-1 입력 검증
누락 파일 감지.

## TEST-2 씬 수
항상 8씬인지 확인.

## TEST-3 STILL
모션 효과 정상 적용.

## TEST-4 I2V
LTX 2.5 호출 후 MP4 생성.

## TEST-5 I2V Fallback
실패 시 STILL 전환.

## TEST-6 TTS
WAV 생성, 길이 > 0.

## TEST-7 Subtitle
SRT 생성, 타임코드 유효.

## TEST-8 Render
1080×1920 MP4 생성.

## TEST-9 Sync
음성/씬/자막 싱크 확인.

## TEST-10 Repeatability
다른 날짜 입력 폴더로 동일 실행 가능.

---

# 29. Definition of Done

MVP 완료 조건:

- [ ] 입력 폴더만 지정해 실행 가능
- [ ] 8씬 입력 검증
- [ ] STILL/I2V 분기 정상
- [ ] LTX 2.5 I2V 최소 1씬 생성 성공
- [ ] I2V 실패 fallback 정상
- [ ] 한국어 TTS 생성
- [ ] 자막 자동 생성
- [ ] Preview MP4 생성
- [ ] Final MP4 생성
- [ ] 1080×1920 출력
- [ ] 로그 파일 생성
- [ ] 다음 영상에도 동일 구조 재사용 가능

---

# 30. TASKS

## M0 — 초기화
- [ ] 저장소 생성
- [ ] 폴더 구조
- [ ] README
- [ ] config
- [ ] JSON Schema

## M1 — 입력/검증
- [ ] project.json loader
- [ ] scene-plan.json loader
- [ ] image validator
- [ ] error codes

## M2 — 씬 처리
- [ ] STILL processor
- [ ] I2V branch
- [ ] LTX 2.5 connector
- [ ] fallback

## M3 — TTS / Subtitle
- [ ] TTS Provider interface
- [ ] 무료 한국어 TTS 1종
- [ ] narration.wav
- [ ] SRT 생성
- [ ] subtitle style

## M4 — Render
- [ ] scene timeline
- [ ] preview render
- [ ] final render
- [ ] output 정리

## M5 — 안정화
- [ ] logging
- [ ] retry 정책
- [ ] 샘플 프로젝트 테스트
- [ ] README 완성
- [ ] 반복 제작 테스트

---

# 31. Top 5 리스크

## RISK-1 I2V 왜곡
대응:
- I2V 2~3씬 제한
- 작은 움직임
- 실패 시 STILL fallback

## RISK-2 TTS 품질
대응:
- Provider 추상화
- 교체 가능 구조

## RISK-3 씬/오디오 싱크
대응:
- TTS 길이 기준 timeline 조정
- Preview 검수

## RISK-4 입력 누락
대응:
- 실행 전 validator

## RISK-5 개발 범위 과다
대응:
- 이미지 생성 제외
- 업로드 자동화 제외
- MVP 후 확장

---

# 32. Decision Log

- **DEC-001** 채널명은 `오늘도출근`.
- **DEC-002** 주제는 직장생활/인간관계/공감/꿀팁.
- **DEC-003** 콘텐츠는 가볍고 재밌는 공감형.
- **DEC-004** 역할극보다 1인 내레이션.
- **DEC-005** 기본 영상 길이 35~45초.
- **DEC-006** 기본 씬 수 8개.
- **DEC-007** 9:16 / 1080×1920.
- **DEC-008** 이미지 8장은 ChatGPT 생성.
- **DEC-009** STILL/I2V 추천도 ChatGPT 담당.
- **DEC-010** 로컬은 이미지 이후 공정만 담당.
- **DEC-011** I2V는 LTX 2.5.
- **DEC-012** I2V는 기본 2~3씬.
- **DEC-013** TTS는 무료 한국어 음성부터.
- **DEC-014** Preview → 검수 → Final 유지.
- **DEC-015** 로컬 I2I는 MVP에서 제외.

---

# 33. 구현 시 바꾸면 안 되는 전제

1. 이미지 생성 기능을 로컬에 임의 추가하지 않는다.
2. STILL/I2V를 로컬에서 재판단하지 않는다.
3. 씬 수는 8개로 유지한다.
4. ChatGPT가 제공한 scene-plan을 우선한다.
5. I2V 실패 시 전체 실패가 아니라 STILL fallback.
6. Preview 검수 단계를 유지한다.
7. MVP에서 자동 YouTube 업로드까지 확장하지 않는다.

---

# 34. MVP 요약

```text
외부 AI
주제 / 제목 / 대본 / 8씬
        ↓
ChatGPT
이미지 8장 + STILL/I2V 추천
        ↓
로컬
STILL / LTX 2.5 I2V
        ↓
TTS
        ↓
자막
        ↓
Preview
        ↓
사람 검수
        ↓
Final
```

이 구조가 v1.0의 SSOT다.

---

# 35. 개발 시작 시 확인할 미확정 항목

개발자는 임의 결정하지 말고 사용자와 확인할 것:

1. 최종 렌더러: Remotion 또는 FFmpeg
2. 무료 한국어 TTS 최종 엔진/보이스
3. 자막 폰트 및 정확한 위치
4. BGM/SFX를 MVP에 포함할지
5. LTX 2.5 최종 ComfyUI Workflow JSON

