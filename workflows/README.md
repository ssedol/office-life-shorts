# workflows/

## ltx25_i2v.json 은 자리표시자입니다

현재 들어 있는 `ltx25_i2v.json` 은 **실제로 검증된 워크플로우가 아닙니다.**
`config/i2v.json` 의 `inject` 매핑이 어떤 구조를 기대하는지 보여주는 예시일 뿐이고,
체크포인트 파일명(`ltx-2.5-i2v.safetensors` 등)도 임의로 적은 값입니다.
이 상태로 ComfyUI에 제출하면 실패하고, 명세서 §16 Fallback 규칙에 따라
해당 씬은 정지 이미지(`slow_zoom_in`)로 대체됩니다.

## 내 워크플로우로 교체하기

1. ComfyUI에서 LTX 2.5 I2V 워크플로우를 돌려 결과가 만족스러운 상태까지 안정화합니다.
2. **Workflow → Export (API)** 로 저장합니다.
   - 그냥 `Save` 하면 UI 전용 형식(`{"nodes": [...]}`)이라 `/prompt` 에 제출할 수 없습니다.
   - 커넥터가 이 경우를 감지해 "API 형식이 아닙니다" 오류를 냅니다.
3. 저장한 파일을 이 폴더의 `ltx25_i2v.json` 으로 덮어씁니다.
4. `config/i2v.json` 의 `inject` 에 적힌 `node` 값을 실제 노드 ID로 맞춥니다.
   - 노드 ID는 ComfyUI 노드 우측 상단에 표시되는 번호이고, API JSON의 최상위 키와 같습니다.
   - 쓰지 않을 항목은 `null` 로 두면 주입을 건너뜁니다.

## inject 매핑 항목 (명세서 §17)

| 키 | 넣는 값 | 보통 붙는 노드 |
|---|---|---|
| `imagePath` | 씬 이미지 | `LoadImage` 의 `image` |
| `positivePrompt` | scene-plan.json 의 `videoPrompt` | positive `CLIPTextEncode` 의 `text` |
| `negativePrompt` | `config/i2v.json` 의 `defaults.negativePrompt` | negative `CLIPTextEncode` 의 `text` |
| `seed` | 씬의 `seed` 또는 난수 | `KSampler` 의 `seed` |
| `width` / `height` | 1080 / 1920 | `LTXVImgToVideo` 등 |
| `frameCount` | `duration × fps` | `LTXVImgToVideo` 의 `length` |
| `durationSec` | 초 단위 길이 | frameCount 대신 길이를 받는 노드용 (기본 `null`) |
| `fps` | 30 | `VHS_VideoCombine` 의 `frame_rate` |
| `outputPrefix` | `today-to-work/SCENE-XX` | `VHS_VideoCombine` 의 `filename_prefix` |

매핑이 실제 워크플로우와 맞지 않으면, 어떤 노드/입력을 찾을 수 없는지
오류 메시지에 그대로 나옵니다. 그때 해당 항목만 고치면 됩니다.

## 이미지 전달 방식

`config/i2v.json` 의 `comfyui.imageMode`:

- `upload` (기본) — ComfyUI `/upload/image` API로 올립니다. 원격 ComfyUI에서도 동작합니다.
- `copy` — `comfyui.inputDir` 로 파일을 복사합니다. 같은 PC에서 쓸 때.
- `path` — 절대 경로를 그대로 주입합니다. `LoadImageFromPath` 계열 커스텀 노드용.

## 결과 영상 회수

커넥터는 `/history/{prompt_id}` 의 `outputs` 를 전부 훑어
영상 확장자(`.mp4`, `.webm`, `.mov`, `.mkv`, `.gif`, `.webp`)를 가진 항목을 찾습니다.
`VHS_VideoCombine` 은 `gifs` 키에, 다른 저장 노드는 `videos` / `images` 키에 넣는 등
노드마다 다르기 때문입니다. `.mp4` 가 있으면 우선합니다.

ComfyUI가 같은 PC에 있다면 `comfyui.outputDir` 를 지정해 두는 편이 빠릅니다.
HTTP 다운로드 대신 파일을 직접 복사합니다.
