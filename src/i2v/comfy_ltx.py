"""LTX 2.5 I2V — ComfyUI 커넥터 (명세서 §16, §17).

명세서 §17의 핵심 요구사항:
    "사용자가 별도로 안정화한 ComfyUI LTX 2.5 I2V workflow JSON을
     그대로 재사용할 수 있게 구현한다."

그래서 이 커넥터는 워크플로우의 노드 구조를 전혀 가정하지 않는다.
config/i2v.json의 inject 매핑이 "어느 노드의 어느 입력에 무엇을 넣을지"를 선언하고,
커넥터는 그 자리에만 값을 꽂아 ComfyUI에 그대로 제출한다.

주입 가능한 값(명세서 §17):
    imagePath / positivePrompt / negativePrompt / seed /
    width / height / frameCount / durationSec / fps / outputPrefix
"""

from __future__ import annotations

import contextlib
import json
import logging
import mimetypes
import random
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from ..errors import I2VError
from .base import I2VProvider, I2VRequest, I2VResult

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif", ".webp")

#: 이미지 전달 방식
IMAGE_MODE_UPLOAD = "upload"   # ComfyUI /upload/image API 사용 (기본)
IMAGE_MODE_COPY = "copy"       # comfyui.inputDir로 파일 복사
IMAGE_MODE_PATH = "path"       # 절대 경로를 그대로 주입 (LoadImageFromPath 계열 노드용)


class ComfyUILTXProvider(I2VProvider):
    name = "comfyui-ltx25"

    # ---- 설정 --------------------------------------------------------------
    @property
    def _comfy(self) -> dict:
        return self.config.get("comfyui", {})

    @property
    def base_url(self) -> str:
        return str(self._comfy.get("baseUrl", "http://127.0.0.1:8188")).rstrip("/")

    @property
    def _timeout(self) -> float:
        return float(self._comfy.get("timeoutSec", 900))

    @property
    def _poll_interval(self) -> float:
        return float(self._comfy.get("pollIntervalSec", 2.0))

    @property
    def _connect_timeout(self) -> float:
        return float(self._comfy.get("connectTimeoutSec", 10))

    def workflow_path(self) -> Path:
        raw = self.config.get("workflowFile")
        if not raw:
            raise I2VError("config/i2v.json에 workflowFile이 없습니다")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.repo_root / path
        return path

    # ---- 사전 점검 ----------------------------------------------------------
    def preflight(self) -> None:
        path = self.workflow_path()
        if not path.is_file():
            raise I2VError(
                f"LTX 2.5 workflow JSON이 없습니다: {path}",
                details=[
                    "ComfyUI에서 'Workflow → Export (API)'로 저장한 JSON을 넣으세요",
                    "노드 ID가 다르면 config/i2v.json의 inject 매핑을 맞춰야 합니다",
                ],
            )
        self.load_workflow()  # 파싱 가능 여부만 확인

    def load_workflow(self) -> dict[str, Any]:
        path = self.workflow_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise I2VError(f"workflow JSON 파싱 실패: {path} ({exc})") from exc

        # ComfyUI 웹 UI 저장 형식(nodes 배열)은 API 형식이 아니다.
        if isinstance(data, dict) and "nodes" in data and "prompt" not in data:
            raise I2VError(
                f"workflow JSON이 API 형식이 아닙니다: {path}",
                details=[
                    "ComfyUI에서 'Workflow → Export (API)'로 다시 저장하세요",
                    "일반 Save는 UI 전용 형식이라 /prompt에 제출할 수 없습니다",
                ],
            )
        if isinstance(data, dict) and "prompt" in data and isinstance(data["prompt"], dict):
            data = data["prompt"]
        if not isinstance(data, dict):
            raise I2VError(f"workflow JSON 최상위는 객체여야 합니다: {path}")
        return data

    # ---- 값 주입 ------------------------------------------------------------
    def inject(self, workflow: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        """config/i2v.json의 inject 매핑에 따라 워크플로우에 값을 꽂는다."""
        mapping = self.config.get("inject", {})
        if not isinstance(mapping, dict):
            raise I2VError("config/i2v.json의 inject는 객체여야 합니다")

        problems: list[str] = []

        for key, target in mapping.items():
            if key.startswith("$"):
                continue  # 설정 파일 주석 키
            if target is None:
                continue  # 명시적으로 "주입 안 함"
            if key not in values or values[key] is None:
                continue
            if not isinstance(target, dict):
                problems.append(f"inject.{key}는 객체여야 합니다 (예: {{\"node\": \"10\", \"field\": \"image\"}})")
                continue

            node_id = str(target.get("node", ""))
            field = target.get("field")
            optional = bool(target.get("optional", False))

            if not node_id or not field:
                problems.append(f"inject.{key}에 node/field가 필요합니다")
                continue

            node = workflow.get(node_id)
            if node is None:
                if not optional:
                    problems.append(
                        f"inject.{key}: 워크플로우에 노드 '{node_id}'가 없습니다 "
                        f"(있는 노드: {', '.join(sorted(workflow)[:12])}…)"
                    )
                continue

            inputs = node.setdefault("inputs", {})
            if field not in inputs and not optional and not target.get("create", False):
                problems.append(
                    f"inject.{key}: 노드 '{node_id}'({node.get('class_type', '?')})에 입력 '{field}'가 없습니다 "
                    f"(있는 입력: {', '.join(sorted(inputs))})"
                )
                continue

            inputs[field] = values[key]

        if problems:
            raise I2VError(
                "workflow 주입 매핑이 실제 워크플로우와 맞지 않습니다",
                details=[*problems, "config/i2v.json의 inject 항목을 워크플로우 노드 ID에 맞추세요"],
            )
        return workflow

    # ---- HTTP --------------------------------------------------------------
    def _request(self, path: str, *, data: bytes | None = None, headers: dict | None = None, timeout: float | None = None) -> bytes:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self._connect_timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = ""
            with contextlib.suppress(Exception):  # 오류 본문은 부가 정보일 뿐이다
                body = exc.read().decode("utf-8", "replace")[:1500]
            raise I2VError(
                f"ComfyUI 요청 실패: {path} (HTTP {exc.code})",
                details=[url, body] if body else [url],
            ) from exc
        except urllib.error.URLError as exc:
            raise I2VError(
                f"ComfyUI에 연결할 수 없습니다: {self.base_url}",
                details=[
                    f"{exc.reason}",
                    "ComfyUI가 실행 중인지, config/i2v.json의 baseUrl이 맞는지 확인하세요",
                ],
            ) from exc
        except TimeoutError as exc:
            raise I2VError(f"ComfyUI 응답 시간 초과: {path}") from exc

    def _post_json(self, path: str, payload: dict) -> dict:
        raw = self._request(
            path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=max(self._connect_timeout, 30),
        )
        return json.loads(raw.decode("utf-8") or "{}")

    def _get_json(self, path: str) -> dict:
        raw = self._request(path)
        return json.loads(raw.decode("utf-8") or "{}")

    def _upload_image(self, image_path: Path) -> str:
        """POST /upload/image 로 이미지를 올리고 ComfyUI 내부 파일명을 돌려준다."""
        boundary = f"----shorts{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        payload = image_path.read_bytes()

        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            payload,
            f"\r\n--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
            f"--{boundary}--\r\n".encode(),
        ])

        raw = self._request(
            "/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=max(self._connect_timeout, 60),
        )
        info = json.loads(raw.decode("utf-8") or "{}")
        name = info.get("name") or image_path.name
        subfolder = info.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else name

    def _prepare_image(self, image_path: Path) -> str:
        mode = str(self._comfy.get("imageMode", IMAGE_MODE_UPLOAD)).lower()

        if mode == IMAGE_MODE_PATH:
            return str(image_path.resolve())

        if mode == IMAGE_MODE_COPY:
            input_dir = self._comfy.get("inputDir")
            if not input_dir:
                raise I2VError(
                    "imageMode=copy 인데 comfyui.inputDir가 없습니다",
                    details=["config/i2v.json의 comfyui.inputDir에 ComfyUI input 폴더 경로를 넣으세요"],
                )
            target_dir = Path(input_dir).expanduser()
            if not target_dir.is_dir():
                raise I2VError(f"ComfyUI input 폴더가 없습니다: {target_dir}")
            target = target_dir / image_path.name
            shutil.copy2(image_path, target)
            return image_path.name

        return self._upload_image(image_path)

    # ---- 결과 회수 ----------------------------------------------------------
    def _poll_history(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            history = self._get_json(f"/history/{urllib.parse.quote(prompt_id)}")
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise I2VError(
                        "ComfyUI 실행이 오류로 끝났습니다",
                        details=[json.dumps(status.get("messages") or [], ensure_ascii=False)[:1500]],
                    )
                if entry.get("outputs"):
                    return entry
            time.sleep(self._poll_interval)

        raise I2VError(
            f"ComfyUI 작업이 {self._timeout:.0f}초 안에 끝나지 않았습니다 (prompt_id={prompt_id})",
            details=["config/i2v.json의 comfyui.timeoutSec를 늘리거나 프레임 수를 줄이세요"],
        )

    @staticmethod
    def _find_video_output(entry: dict) -> dict:
        """history 항목에서 영상 파일 정보를 찾는다.

        VHS_VideoCombine은 'gifs', SaveVideo 계열은 'videos'/'images'에 넣는 등
        노드마다 키가 달라서 전부 훑는다.
        """
        candidates: list[dict] = []
        for node_output in (entry.get("outputs") or {}).values():
            if not isinstance(node_output, dict):
                continue
            for items in node_output.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict) and str(item.get("filename", "")).lower().endswith(VIDEO_SUFFIXES):
                        candidates.append(item)
        if not candidates:
            raise I2VError(
                "ComfyUI 결과에서 영상 파일을 찾지 못했습니다",
                details=[
                    "워크플로우에 VHS_VideoCombine 또는 영상 저장 노드가 있는지 확인하세요",
                    f"받은 출력 키: {list((entry.get('outputs') or {}).keys())}",
                ],
            )
        # mp4를 우선한다.
        candidates.sort(key=lambda item: 0 if str(item["filename"]).lower().endswith(".mp4") else 1)
        return candidates[0]

    def _download(self, item: dict, out_path: Path) -> Path:
        output_dir = self._comfy.get("outputDir")
        if output_dir:
            local = Path(output_dir).expanduser() / (item.get("subfolder") or "") / item["filename"]
            if local.is_file():
                out_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local, out_path)
                return out_path

        query = urllib.parse.urlencode({
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        raw = self._request(f"/view?{query}", timeout=max(self._connect_timeout, 120))
        if not raw:
            raise I2VError(f"ComfyUI에서 빈 파일을 받았습니다: {item['filename']}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        return out_path

    # ---- 인터페이스 ---------------------------------------------------------
    def generate(self, request: I2VRequest) -> I2VResult:
        workflow = self.load_workflow()

        defaults = self.config.get("defaults", {})
        seed = request.seed
        if seed is None:
            seed = defaults.get("seed")
        if seed is None:
            seed = random.randint(0, 2**31 - 1)

        image_ref = self._prepare_image(request.image_path)

        values = {
            "imagePath": image_ref,
            "positivePrompt": request.video_prompt,
            "negativePrompt": request.negative_prompt or defaults.get("negativePrompt", ""),
            "seed": int(seed),
            "width": request.width,
            "height": request.height,
            "frameCount": request.frame_count,
            "durationSec": round(request.duration_sec, 3),
            "fps": request.fps,
            "outputPrefix": f"today-to-work/{request.scene_id}",
        }
        workflow = self.inject(workflow, values)

        client_id = str(self._comfy.get("clientId") or "today-to-work-shorts")
        response = self._post_json("/prompt", {"prompt": workflow, "client_id": client_id})

        if response.get("error"):
            raise I2VError(
                "ComfyUI가 워크플로우를 거부했습니다",
                details=[json.dumps(response, ensure_ascii=False)[:1500]],
            )
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise I2VError("ComfyUI 응답에 prompt_id가 없습니다", details=[json.dumps(response)[:800]])

        log.info("%s: ComfyUI 제출 (prompt_id=%s, %d프레임, seed=%s)",
                 request.scene_id, prompt_id, request.frame_count, seed)

        entry = self._poll_history(str(prompt_id))
        item = self._find_video_output(entry)
        path = self._download(item, request.out_path)

        if path.stat().st_size == 0:
            raise I2VError(f"{request.scene_id}: 받은 영상 파일이 비어 있습니다")

        return I2VResult(
            scene_id=request.scene_id,
            path=path,
            duration_sec=request.duration_sec,
            seed=int(seed),
            provider=self.name,
        )

    def describe(self) -> str:
        return f"ComfyUI LTX 2.5 I2V ({self.base_url})"
