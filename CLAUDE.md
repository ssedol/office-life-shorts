# 오늘도출근 Shorts Factory — 작업 지침

## 브랜치

**작업과 푸시는 `main`에서 한다.** 운영자가 정한 규칙이다 (2026-09-19).

세션 시작 시 `claude/...` 같은 작업 브랜치가 지정되더라도, **최종 결과물은 `main`에 올린다.**
작업 브랜치에서 작업했다면 끝에 `main`으로 합쳐 푸시한다.

```bash
git checkout main
git merge --ff-only <작업브랜치>   # 또는 애초에 main에서 작업
git push origin main
```

별도 요청이 없으면 PR은 만들지 않는다.

## 이 저장소가 하는 일

직장인 공감형 YouTube Shorts 채널 **오늘도출근**의 반자동 제작 시스템.
`TODAY_TO_WORK_PROJECT_SPEC.md`(명세서 v1.0)가 SSOT다. 구조를 바꿀 땐 먼저 명세서를 확인한다.

대본과 `scene-plan.json`은 이쪽에서 쓰고, 그에 맞춘 이미지 8장만 ChatGPT에서 받는다.
이미지를 `inputs/<날짜>/`에 넣으면 I2V / TTS / 자막 / 타임라인 / 렌더를 자동 처리한다.

## 자주 쓰는 명령

```bash
python main.py --input ./inputs/YYYY-MM-DD --validate-only   # 입력 검증만
python main.py --input ./inputs/YYYY-MM-DD --skip-i2v        # LTX 없이 preview
python main.py --input ./inputs/YYYY-MM-DD --mode final      # 검수 후 final
python main.py --input ./inputs/YYYY-MM-DD --tts-engine offline  # 네트워크 없을 때(무음)

python tools/tts_compare.py --engines edge,clova,typecast,elevenlabs --scripts original,spoken
                                         # 같은 대본을 엔진별로 뽑아 비교 (합본.wav를 듣는다)

python tools/upload.py --input ./inputs/YYYY-MM-DD --dry-run
                                         # 무엇이 올라갈지만 확인 (네트워크 안 씀)
python tools/upload.py --input ./inputs/YYYY-MM-DD
                                         # 실제 업로드 (기본 공개 발행)

pytest                                   # 전체 (약 2분)
pytest -m "not slow" -q                  # 1080×1920 실렌더 제외
ruff check --select F,E9,B,UP,SIM .      # lint
```

## 바꾸면 안 되는 전제 (명세서 §33)

1. 로컬에서 이미지를 생성하지 않는다 — **이미지 생성만** ChatGPT 담당.
   주제·제목·대본·8씬 구성·`scene-plan.json`·`script.txt`·`upload.json`은 **전부 이쪽에서 만든다.**
   명세서 §1에 "주제/대본/8씬 구성은 외부 AI가 담당한다"고 적혀 있으나 **그 문장은 현재 운영 방식과 다르다.**
   ChatGPT에 기획을 넘기는 게 아니라, 이미지를 만들지 못해서 그 부분만 맡기는 것이다.
   ChatGPT에는 `image-prompts.md`만 넘긴다.
2. STILL/I2V를 로컬에서 재판단하지 않는다 — `scene-plan.json`을 그대로 따른다.
3. 씬 수는 **항상 8개**.
4. I2V 실패는 전체 실패가 아니다 — 원본 이미지 + `slow_zoom_in`으로 대체하고 로그에 남긴다.
5. Preview → 사람 검수 → Final 순서를 유지한다.
6. ~~자동 YouTube 업로드는 MVP 범위 밖.~~ **2026-09-21 운영자 결정으로 범위에 들어왔다** (DEC-017).
   ~~감사를 통과하지 않아 유튜브가 비공개로 잠근다.~~
   **2026-09-23에 감사를 통과한 것이 확인됐다** — 5편을 `--privacy public`으로 올리고
   `videos.list`로 다시 읽어 `public`이 유지되는 것을 확인했다. 첫 댓글도 자동으로 달렸다.
   그래서 같은 날 `config/upload.json`의 기본값도 `public`으로 바꿨다(운영자 결정) —
   비공개로 오래 두면 구독자 유입에 손해다. **이제 `tools/upload.py`를 그냥 실행하면
   바로 공개 발행된다.** 올리기 전에 `--dry-run`으로 먼저 확인한다.
   특정 회차만 숨기려면 `--privacy private`를 준다.

## 판단이 갈렸던 지점

작업하다 마주칠 수 있는, 이미 결론이 난 사안들이다.

- **씬 길이**는 `durationSec`이 아니라 **실제 내레이션 길이**로 정해진다
  (`config/app.json`의 `timeline.fitToNarration`, 기본 켜짐).
  `durationSec`을 하한으로 쓰면 말이 끝난 뒤 정지 화면이 남아 영상이 늘어진다.
  실측에서 40초 영상의 22%가 그런 빈 시간이었다.
- **실행 순서**는 명세서 §3.1과 한 군데 다르다. 씬 길이가 TTS 길이에 의존하므로
  TTS → 타임라인 → I2V 순으로 돈다. 입력이 같으면 결과도 같다.
- **자막은 `.ass`로 번인**한다. `.srt`는 외곽선 색·강조색·안전영역을 표현할 수 없어서
  명세서가 요구한 `.srt`는 그대로 내보내되 렌더에는 `.ass`를 쓴다.
- **댓글 유도**는 훅과 마무리 두 군데에 넣는다. 검증이 없으면 경고한다.
  훅에서는 자막을 건드리지 않고 내레이션에만 붙인다 — 훅이 약해진다.
- **`workflows/ltx25_i2v.json`은 자리표시자**다. 운영자가 ComfyUI에서
  `Export (API)`로 저장한 실제 워크플로우로 교체해야 I2V가 동작한다.
- **TTS 설정 우선순위는 CLI > `project.json` > `config/tts.json`이다.**
  `project.json`의 `tts.engine`을 적어 두면 채널 기본값을 바꿔도 안 먹힌다.
  그래서 에피소드 입력에서는 engine/voice를 비워 두고 speed만 둔다.
  엔진 목록은 `schema/project.schema.json`에도 있어 어긋나기 쉽다 —
  `test_schema_engine_list_matches_registry`가 막아 준다.
- **보이스 이름은 엔진 사이에서 물려받지 않는다.** 형식이 서로 다르기 때문이다
  (edge `ko-KR-SunHiNeural` / clova `nara` / elevenlabs는 이름이 아닌 ID).
  최상위 `voice`는 최상위 `engine`의 값으로만 쓰고, `--tts-voice`로 준 값만 항상 이긴다.
- **오프라인 TTS의 `charsPerSec`는 실측 보정값**이다(초당 5.2자, edge-tts ko-KR-SunHiNeural).
  추정 모델을 바꾸면 `test_default_rate_matches_measured_edge_tts`가 깨진다. 값을 다시 맞춘다.
- **ffmpeg 필터에는 경로를 넣지 않는다.** 필터그래프 파서가 `:`와 `\`를 특수문자로 읽어
  Windows 절대 경로에서 깨진다. 자막·폰트는 작업 폴더로 복사하고 파일 이름만 넘긴다.
- **지난 회차 대본을 틀로 삼지 않는다.** 5편을 4편에서 줄 단위로 베껴 쓴 적이 있다
  (2026-09-23). 7번 씬 뒷문장은 글자까지 같았고, 6·8번 댓글 유도도 같은 틀에 명사만
  바꿔 끼운 상태였다. 그 결과 8개 씬이 전부 `~어요`로 끝나 "왜 이런 게 반복되냐"는
  지적을 받았다. 구성(훅 → 사건 → 정점 → 댓글 유도 → 마무리)은 채널 포맷이라 유지하되,
  **문장과 어미는 매 회차 새로 쓴다.** 명사로 끊기, `~거든요`, `~더라고요`, `~죠 뭐`,
  연결어미로 끊기를 섞어야 사람이 말하는 것처럼 들린다.
  `config/app.json`의 `script.maxSameEndingScenes` / `maxPlainPoliteScenes`가
  같은 어미 반복을 경고로 잡아 준다 — 이 검사는 4편도 걸러낸다.
- **ElevenLabs `eleven_v3`는 짧은 감탄사를 과장되게 늘여 읽는다.** 5편 정점 대사
  `"넵!"`이 0.8초 넘게 늘어지며 억양이 꺾여 "겨죠?"처럼 들리는 문제가 있었다(2026-09-23).
  같은 줄을 stability 0.8까지 올리고 따옴표를 빼고 여러 번 다시 뽑아도 매번 재현됐다 —
  파라미터 문제가 아니라 v3가 짧고 독립된 대사를 "감정 표현"으로 해석해 늘이는 것으로 보인다.
  `eleven_multilingual_v2`로는 같은 텍스트가 0.1~0.2초짜리 자연스러운 발화로 나왔다
  (음성인식으로 대조 확인). 이 채널은 4편 "힘내세요"처럼 정점에 짧은 감탄사를 자주 쓰는
  포맷이라 `config/tts.json`의 `elevenlabs.model`을 `eleven_multilingual_v2`로 되돌렸다.
  v3를 다시 쓰려면 이 문제부터 재현 여부를 확인한다.

## 업로드 자동화에서 확인된 사실

- **감사를 통과해서 이제 공개 발행까지 자동이다 (2026-09-23 확인).**
  2020-07-28 이후 만든 API 프로젝트는 감사 전까지 `videos.insert`로 올린 영상이
  비공개로 잠기는데, 5편(`9yCnV69HY6g`)을 `--privacy public`으로 올린 뒤
  `videos.list`로 다시 읽으니 `public` / `processed`였다. 잠기지 않았다.
- **첫 댓글도 자동으로 달린다.** 공개 영상일 때만 가능하다 —
  `tools/upload.py`는 비공개면 요청을 아예 보내지 않고(실패할 요청으로 할당량을
  쓰지 않으려고) 나중에 `--comment-only`로 달 수 있게 남겨 둔다.
  5편에서 업로드와 동시에 고정 댓글 문구가 실제로 달린 것을 확인했다.
- **댓글 고정은 API에 없다.** `commentThreads.insert`로 댓글은 달리지만
  고정 엔드포인트가 없어 유튜브 앱이나 스튜디오에서 직접 눌러야 한다.
- **업로드 도구는 UTF-8로 출력해야 한다.** Windows 콘솔 기본값이 cp949라
  설명란 머리말의 이모지(🔗, 🎵)에서 `UnicodeEncodeError`로 죽는다. 그 지점이
  업로드 직전이라 영상이 아예 안 올라간다. `tools/upload.py`가 시작할 때
  stdout/stderr를 UTF-8로 재설정한다.
- **할당량은 하루 10,000 유닛, 업로드 1건이 1,600 유닛**이라 하루 6편이 상한이다.
  실패한 시도도 깎이므로 `--dry-run`으로 먼저 확인한다.
- **손으로 올린 영상은 이 API 프로젝트로 태그를 읽을 수도 고칠 수도 없다.**
  `videos.list`가 태그를 0개로 돌려주고, `videos.update`로 태그를 보내도 에러 없이 무시된다.
  API로 올린 영상은 태그가 정상으로 읽힌다. 2026-09-22에 4편(손 업로드)을 "태그 없음"으로
  잘못 판단한 적이 있다 — 실제로는 태그가 다 들어가 있었다. 손 업로드 영상의 태그는
  스튜디오 화면으로 확인한다.
- **AI 공시를 API로 설정할 수 있는지는 미확인.** 지금은 사람이 체크해야 한다고 보고
  업로드가 끝나면 안내만 출력한다.

## 검증되지 않은 부분

- **edge-tts 실제 음성** — 개발 컨테이너에서 `speech.platform.bing.com`이
  egress 정책으로 막혀 있다. 어댑터 코드는 있지만 실제 한국어 음성 출력은 미검증.
  운영자 PC에서 확인해야 한다.
- **LTX 2.5 실제 생성** — 커넥터는 가짜 ComfyUI 서버로 HTTP 프로토콜 전 구간을
  검증했지만, 실제 LTX 워크플로우로는 돌려본 적이 없다.
- **elevenlabs는 2026-09-23에 운영자 PC에서 실제 API로 검증됐다.** 5편 렌더에서
  실제 음성이 나왔고, 그 과정에서 v3의 짧은 감탄사 문제를 찾아 v2로 바꿨다
  (판단이 갈렸던 지점 참고). clova / typecast 두 종은 아직 미검증 —
  개발 컨테이너의 egress 정책에 막혀 가짜 서버(`tests/fake_tts_api.py`)로
  요청 형식과 오류 처리만 검증했다. **특히 typecast는 공식 문서조차 열지 못해
  요청 형식에 추측이 섞여 있다** — 그래서 엔드포인트와 필드를 `config/tts.json`에서
  고칠 수 있게 했다(`baseUrl` / `speakPath` / `extraFields` / `authHeader`).
  응답이 오디오든 작업 ID든 모두 처리하므로 둘 중 어느 쪽이어도 동작한다.

## 문서 쓸 때

설명과 주석은 한국어로 쓴다. 커밋 메시지도 한국어다.
