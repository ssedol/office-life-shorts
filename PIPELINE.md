# 파이프라인

대본 하나를 유튜브에 올라간 영상으로 만드는 전 과정.

```
1 validate  대본 검수              자동
2 prompts   이미지 프롬프트 출력    자동
3 images    이미지 확인            ⏸ 멈춤 — GPT 등에서 직접 생성해 넣는다
4 tts       음성 생성 + 타임라인    자동
5 video     영상 조립              자동
6 review    눈으로 확인            ⏸ 멈춤 — 사람이 본다
7 upload    업로드                 자동
```

## 쓰는 법

```bash
python -m pipeline.run 0001            # 막히는 지점까지 진행
python -m pipeline.run 0001 --status   # 어디까지 됐는지
python -m pipeline.run 0001 --approve  # review 통과 처리
python -m pipeline.run 0001 --dry-run  # 아무것도 만들지 않고 계획만 출력
```

**중단해도 됩니다.** 각 단계 결과가 `build/<id>/state.json` 에 기록되므로
다시 실행하면 끝난 단계는 건너뜁니다.

## ⏸ 3단계 — 이미지 (여기서 멈춥니다)

```
⏸ 이미지 7장이 없습니다.
   build/0001/prompts.txt 의 프롬프트로 생성해서
   assets/scenes/0001/ 에 아래 이름으로 넣어주세요.

     ✗ 1_HOOK.png
     ✗ 4_BODY2.png  🎬영상 씬
     ...
```

- `build/<id>/prompts.txt` — 사람이 복붙할 형태
- `build/<id>/prompts.json` — 코드로 읽을 형태
- 파일명은 **`<씬번호>_<역할>.png`** 로 정확히 맞춰야 합니다
- 🎬 영상 씬은 i2v 로 영상까지 만들었으면 **`.mp4`** 로 넣으세요. 파이프라인이 알아서 씁니다

다 넣고 `python -m pipeline.run 0001` 을 다시 돌리면 이어서 진행됩니다.

## 4단계 — TTS와 타임라인 재계산 (중요)

```bash
python -m pipeline.run 0001 --tts openai      # 또는 elevenlabs, manual
```

**여기서 타임라인을 다시 계산합니다.** 대본의 `start`/`end` 는 글자수로 추정한 계획값입니다.
실제 음성은 길거나 짧습니다. ffprobe 로 실측해서 씬 시간을 덮어씁니다.

**이 단계가 없으면 자막과 음성이 뒤로 갈수록 어긋납니다.** 대부분의 자동 영상 파이프라인이
여기서 깨집니다.

`--tts manual` 은 음성을 직접 녹음해 넣을 때 씁니다.
`build/<id>/audio/<n>_<역할>.mp3` 로 넣으면 나머지는 똑같이 돌아갑니다.
**육성 녹음을 유지하면서 나머지를 자동화하는 방법입니다.**

## 5단계 — 영상 조립

- 씬마다 클립을 만든 뒤 이어 붙입니다
- 정지 이미지에는 `motion` 값대로 켄번즈(zoompan)를 겁니다
- 자막은 ASS 파일로 만들어 구워 넣습니다. **상단 20~35% 구간**에 배치하고
  `config/style.yaml` 의 색 팔레트를 씁니다
- 자막은 말보다 0.15초 먼저 뜹니다
- 씬 사이에 0.15초 간격을 둡니다 (붙이면 말이 뭉쳐 들립니다)

필요: **ffmpeg, ffprobe**

## ⏸ 6단계 — 사람 확인

무인 업로드를 권하지 않습니다. 확인할 것:

- 첫 프레임부터 자막이 떠 있는가
- 캐릭터가 씬마다 같은 사람인가
- 음성과 자막이 어긋나지 않는가
- 하단 25%에 가려지면 안 되는 게 있는가

```bash
python -m pipeline.run 0001 --approve
```

## 7단계 — 업로드

```bash
python -m pipeline.run 0001 --privacy private   # 기본값. 먼저 비공개 권장
```

준비:
1. Google Cloud 프로젝트에서 YouTube Data API v3 활성화
2. OAuth 클라이언트(데스크톱 앱)를 만들어 `client_secret.json` 으로 저장
3. `pip install google-auth-oauthlib google-api-python-client`

업로드 후 제목·설명·태그가 들어가고 고정 댓글이 자동으로 달립니다
(고정 처리는 스튜디오에서 직접 해야 합니다).

⚠️ **AI 고지는 API로 설정되지 않습니다.** TTS·생성 이미지를 쓰므로 업로드 후
스튜디오에서 "변경되거나 합성된 콘텐츠"를 직접 켜세요.

⚠️ **할당량**: `videos.insert` 비용은 자료마다 다릅니다.
[공식 계산기](https://developers.google.com/youtube/v3/determine_quota_cost)로 직접 확인하세요.

## 설치

```bash
pip install -r requirements.txt
# TTS 쓰는 쪽만:        pip install openai      # 또는 elevenlabs
# 업로드 쓸 때:         pip install google-auth-oauthlib google-api-python-client
# ffmpeg 는 별도 설치:  https://ffmpeg.org
```

## 검증 상태

| 부분 | 상태 |
|---|---|
| 단계 진행·상태 기록·정지점 | ✅ 여기서 실행해 확인 |
| 타임라인 재계산 로직 | ✅ 확인 |
| 자막(ASS) 생성 | ✅ 확인 |
| ffmpeg 명령 조립 | ⚠️ 명령 문자열까지만 확인 — **ffmpeg 가 없는 환경이라 실제 인코딩은 미검증** |
| TTS / 업로드 API 호출 | ⚠️ **미검증** — API 키가 없어 `--dry-run` 까지만 |

처음 돌리실 때 `--dry-run` 으로 먼저 확인하시고, 안 되는 부분은 알려주시면 고치겠습니다.
