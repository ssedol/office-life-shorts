"""테스트용 가짜 ComfyUI 서버.

실제 ComfyUI 없이 커넥터(src/i2v/comfy_ltx.py)의 동작을 확인한다.
지원하는 엔드포인트는 커넥터가 쓰는 것과 같다.

    POST /upload/image   → 업로드된 파일명 반환
    POST /prompt         → prompt_id 반환 (제출된 워크플로우를 기록해 둔다)
    GET  /history/{id}   → 실행 결과
    GET  /view?...       → 결과 영상 바이트
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FakeComfyUI:
    """with 문으로 띄우고 내리는 가짜 서버."""

    def __init__(self, video_bytes: bytes, *, mode: str = "success", output_key: str = "gifs", filename: str = "scene_00001.mp4"):
        """
        Args:
            mode: success        — 정상 처리
                  prompt_error   — /prompt가 에러를 돌려줌
                  exec_error     — 실행 중 오류 (history status_str=error)
                  no_video       — 결과에 영상이 없음
                  empty_file     — 0바이트 파일 반환
        """
        self.video_bytes = video_bytes
        self.mode = mode
        self.output_key = output_key
        self.filename = filename

        self.submitted_workflows: list[dict] = []
        self.uploaded_images: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> FakeComfyUI:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # 테스트 출력 정리
                pass

            def _send(self, status: int, body: bytes, content_type: str = "application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, status: int, payload: dict):
                self._send(status, json.dumps(payload).encode("utf-8"))

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)

                if self.path == "/upload/image":
                    name = "uploaded.png"
                    for part in raw.split(b"\r\n"):
                        if b'filename="' in part:
                            name = part.split(b'filename="')[1].split(b'"')[0].decode()
                            break
                    outer.uploaded_images.append(name)
                    self._send_json(200, {"name": name, "subfolder": "", "type": "input"})
                    return

                if self.path == "/prompt":
                    payload = json.loads(raw.decode("utf-8"))
                    outer.submitted_workflows.append(payload.get("prompt", {}))
                    if outer.mode == "prompt_error":
                        self._send_json(200, {"error": {"type": "prompt_outputs_failed_validation",
                                                        "message": "Prompt has no properly connected outputs"}})
                        return
                    self._send_json(200, {"prompt_id": "test-prompt-1", "number": 1, "node_errors": {}})
                    return

                self._send_json(404, {"error": "not found"})

            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)

                if parsed.path.startswith("/history/"):
                    prompt_id = parsed.path.rsplit("/", 1)[-1]

                    if outer.mode == "exec_error":
                        self._send_json(200, {prompt_id: {
                            "status": {"status_str": "error", "completed": False,
                                       "messages": [["execution_error", {"exception_message": "CUDA out of memory"}]]},
                            "outputs": {},
                        }})
                        return

                    outputs: dict = {}
                    if outer.mode == "no_video":
                        outputs = {"9": {"images": [{"filename": "preview.png", "subfolder": "", "type": "output"}]}}
                    else:
                        outputs = {"9": {outer.output_key: [
                            {"filename": outer.filename, "subfolder": "", "type": "output", "format": "video/h264-mp4"}
                        ]}}

                    self._send_json(200, {prompt_id: {
                        "status": {"status_str": "success", "completed": True, "messages": []},
                        "outputs": outputs,
                    }})
                    return

                if parsed.path == "/view":
                    body = b"" if outer.mode == "empty_file" else outer.video_bytes
                    self._send(200, body, "video/mp4")
                    return

                self._send_json(404, {"error": "not found"})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def make_test_video(ffmpeg, path: Path, *, seconds: float = 3.0, width: int = 270, height: int = 480, fps: int = 30) -> bytes:
    """LTX 결과물 대역으로 쓸 진짜 mp4를 만든다."""
    ffmpeg.run([
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "34", "-pix_fmt", "yuv420p",
        "-an", str(path),
    ])
    return path.read_bytes()
