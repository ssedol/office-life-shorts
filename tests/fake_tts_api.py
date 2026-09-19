"""테스트용 가짜 TTS API 서버.

ElevenLabs / CLOVA / Typecast 실제 서버 없이 어댑터의 HTTP 동작을 확인한다.
개발 컨테이너에서 세 서비스 모두 네트워크 정책에 막혀 있어, 실제 API로는
한 번도 돌려보지 못했다. 최소한 우리가 보내는 요청이 의도한 모양인지,
오류 응답을 제대로 해석하는지는 여기서 검증한다.

    POST /v1/text-to-speech/{voice_id}   ElevenLabs
    POST /tts-premium/v1/tts             CLOVA Voice
    POST /v1/text-to-speech              Typecast (오디오 직접 또는 작업 ID)
    GET  /v1/status/{job}                Typecast 작업 상태
    GET  /v1/audio/{job}                 Typecast 오디오 내려받기
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeTTSAPI:
    """with 문으로 띄우고 내리는 가짜 TTS 서버.

    받은 요청을 requests에 기록해 두므로, 테스트에서 "무엇을 보냈는지"를
    그대로 확인할 수 있다.
    """

    def __init__(self, audio_bytes: bytes = b"ID3\x04\x00fake-mp3-payload", *, mode: str = "success"):
        """
        Args:
            mode: success       — 바로 오디오를 돌려준다
                  typecast_job  — Typecast가 작업 ID를 돌려주고 두 번 조회 후 완료
                  unauthorized  — 401
                  json_instead  — 200인데 오디오 대신 JSON
                  empty         — 200인데 본문이 비어 있음
                  job_failed    — Typecast 작업이 실패 상태로 끝남
        """
        self.audio_bytes = audio_bytes
        self.mode = mode
        #: [(method, path, headers, body)] — 보낸 요청 전부
        self.requests: list[tuple[str, str, dict, bytes]] = []
        self._polls = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def last_json(self) -> dict:
        """마지막 요청 본문을 JSON으로 읽는다."""
        return json.loads(self.requests[-1][3].decode("utf-8"))

    def last_form(self) -> dict[str, str]:
        """마지막 요청 본문을 form 형식으로 읽는다."""
        raw = self.requests[-1][3].decode("utf-8")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def last_headers(self) -> dict[str, str]:
        """마지막 요청 헤더. HTTP 헤더 이름은 대소문자를 구분하지 않고,
        urllib이 'xi-api-key'를 'Xi-Api-Key'로 바꿔 보내므로 소문자로 맞춰 돌려준다."""
        return {k.lower(): v for k, v in self.requests[-1][2].items()}

    def __enter__(self) -> FakeTTSAPI:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # 테스트 출력을 더럽히지 않는다
                pass

            def _send(self, status: int, body: bytes, content_type: str):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, status: int, payload: dict):
                self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

            def _send_audio(self):
                self._send(200, outer.audio_bytes, "audio/mpeg")

            def _record(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, dict(self.headers), body))
                return body

            def do_POST(self):
                self._record()

                if outer.mode == "unauthorized":
                    return self._send_json(401, {"detail": "invalid api key"})
                if outer.mode == "json_instead":
                    return self._send_json(200, {"detail": "quota exceeded"})
                if outer.mode == "empty":
                    return self._send(200, b"", "audio/mpeg")
                if outer.mode in ("typecast_job", "job_failed"):
                    return self._send_json(200, {"result": {"speak_v2_url": f"{outer.base_url}/v1/status/job-1"}})
                return self._send_audio()

            def do_GET(self):
                outer.requests.append((self.command, self.path, dict(self.headers), b""))

                if self.path.startswith("/v1/status/"):
                    if outer.mode == "job_failed":
                        return self._send_json(200, {"result": {"status": "failed", "error": "합성 실패"}})
                    outer._polls += 1
                    if outer._polls < 2:
                        return self._send_json(200, {"result": {"status": "progress"}})
                    return self._send_json(200, {"result": {
                        "status": "done",
                        "audio_download_url": f"{outer.base_url}/v1/audio/job-1",
                    }})
                if self.path.startswith("/v1/audio/"):
                    return self._send_audio()
                return self._send_json(404, {"detail": "not found"})

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
