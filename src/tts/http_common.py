"""유료 TTS API 어댑터가 공유하는 HTTP 유틸 (명세서 §18, §26).

ElevenLabs / CLOVA / Typecast는 모두 "텍스트를 POST하면 오디오 바이트가 온다"는
같은 모양이다. 인증 헤더와 본문 형식만 다르다. 그 공통부를 여기 모은다.

의존성을 늘리지 않으려고 requests 대신 표준 라이브러리 urllib을 쓴다.
src/i2v/comfy_ltx.py도 같은 방식이다.

API 키는 코드나 config에 적지 않고 반드시 환경변수(.env)에서 읽는다(명세서 §26).
.env는 .gitignore에 있어 커밋되지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..errors import TTSError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0

#: 오디오로 보기 어려운 응답을 오류 메시지에 실을 때 자르는 길이
_ERROR_BODY_LIMIT = 500


def require_env(var_name: str, *, engine: str, signup_hint: str) -> str:
    """환경변수에서 API 키를 읽는다. 없으면 안내와 함께 실패한다."""
    value = (os.environ.get(var_name) or "").strip()
    if not value:
        raise TTSError(
            f"{engine}: 환경변수 {var_name}이(가) 없습니다",
            details=[
                ".env 파일에 다음 줄을 추가하세요:",
                f"    {var_name}=발급받은_키",
                signup_hint,
                ".env는 커밋되지 않습니다 (명세서 §26)",
            ],
        )
    return value


def post_for_audio(
    url: str,
    *,
    engine: str,
    headers: dict[str, str],
    body: bytes,
    out_path: Path,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """POST해서 받은 응답 본문을 그대로 오디오 파일로 저장한다.

    응답이 오디오가 아니라 JSON 오류면 그 내용을 그대로 보여준다.
    키가 틀렸는지, 글자 수를 초과했는지, 보이스 이름이 없는지를
    바로 알 수 있어야 하기 때문이다.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise TTSError(
            f"{engine} 합성 실패 (HTTP {exc.code})",
            details=[_describe_error_body(exc.read()), *_hint_for_status(exc.code, engine)],
        ) from exc
    except urllib.error.URLError as exc:
        raise TTSError(
            f"{engine} 서버에 연결하지 못했습니다",
            details=[f"{type(exc).__name__}: {exc.reason}", "인터넷 연결과 방화벽을 확인하세요", url],
        ) from exc

    if not payload:
        raise TTSError(f"{engine}이(가) 빈 응답을 보냈습니다")

    # 200인데 JSON이 오는 경우가 있다(비동기 작업 큐, 부분 실패 등).
    if "json" in content_type or "text" in content_type:
        raise TTSError(
            f"{engine}이(가) 오디오 대신 {content_type}을(를) 보냈습니다",
            details=[_describe_error_body(payload)],
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    return out_path


def post_audio_or_json(
    url: str,
    *,
    engine: str,
    headers: dict[str, str],
    body: bytes,
    out_path: Path,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Path | None, dict | None]:
    """오디오를 바로 주는 API와 작업 ID를 주는 API를 모두 받는다.

    서비스마다 응답 방식이 다르고 버전에 따라 바뀌기도 한다.
    Content-Type을 보고 갈라서, 오디오면 저장하고 JSON이면 파싱해 돌려준다.
    둘 중 하나는 반드시 None이다.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise TTSError(
            f"{engine} 합성 실패 (HTTP {exc.code})",
            details=[_describe_error_body(exc.read()), *_hint_for_status(exc.code, engine)],
        ) from exc
    except urllib.error.URLError as exc:
        raise TTSError(
            f"{engine} 서버에 연결하지 못했습니다",
            details=[f"{type(exc).__name__}: {exc.reason}", url],
        ) from exc

    if not payload:
        raise TTSError(f"{engine}이(가) 빈 응답을 보냈습니다")

    if "audio" in content_type or "octet-stream" in content_type:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        return out_path, None

    try:
        return None, json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSError(
            f"{engine} 응답을 오디오로도 JSON으로도 읽지 못했습니다",
            details=[f"Content-Type: {content_type or '(없음)'}", _describe_error_body(payload)],
        ) from exc


def post_for_json(
    url: str,
    *,
    engine: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """POST해서 JSON 응답을 받는다. 2단계(작업 생성 → 결과 조회) API용."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise TTSError(
            f"{engine} 요청 실패 (HTTP {exc.code})",
            details=[_describe_error_body(exc.read()), *_hint_for_status(exc.code, engine)],
        ) from exc
    except urllib.error.URLError as exc:
        raise TTSError(
            f"{engine} 서버에 연결하지 못했습니다",
            details=[f"{type(exc).__name__}: {exc.reason}", url],
        ) from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSError(
            f"{engine} 응답을 JSON으로 읽지 못했습니다",
            details=[_describe_error_body(payload)],
        ) from exc


def get_json(url: str, *, engine: str, headers: dict[str, str] | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> dict:
    """GET해서 JSON을 받는다. 작업 상태 조회용."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise TTSError(
            f"{engine} 상태 조회 실패 (HTTP {exc.code})",
            details=[_describe_error_body(exc.read()), *_hint_for_status(exc.code, engine)],
        ) from exc
    except urllib.error.URLError as exc:
        raise TTSError(f"{engine} 상태 조회 실패", details=[str(exc.reason), url]) from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSError(f"{engine} 상태 응답을 읽지 못했습니다", details=[_describe_error_body(payload)]) from exc


def get_to_file(url: str, *, engine: str, out_path: Path, headers: dict[str, str] | None = None,
                timeout: float = DEFAULT_TIMEOUT) -> Path:
    """URL에서 오디오를 내려받아 저장한다. 2단계 API의 마지막 단계용."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise TTSError(f"{engine} 오디오 내려받기 실패", details=[str(exc), url]) from exc

    if not payload:
        raise TTSError(f"{engine}: 내려받은 오디오가 비어 있습니다", details=[url])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    return out_path


def find_first(payload: object, keys: tuple[str, ...]) -> str | None:
    """중첩된 JSON에서 주어진 키 중 처음 찾은 문자열 값을 돌려준다.

    서비스마다 결과 URL을 result.audio_download_url, data.url 등 다른 자리에 담는다.
    구조를 추측해 하드코딩하는 대신 키 이름으로 훑는다.
    """
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = find_first(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_first(item, keys)
            if found:
                return found
    return None


def form_encoded(fields: dict[str, object]) -> bytes:
    """application/x-www-form-urlencoded 본문을 만든다. None 값은 뺀다."""
    pairs = {k: str(v) for k, v in fields.items() if v is not None}
    return urllib.parse.urlencode(pairs, encoding="utf-8").encode("utf-8")


def json_encoded(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _describe_error_body(raw: bytes) -> str:
    """오류 응답 본문을 사람이 읽을 수 있게 줄인다."""
    try:
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:  # pragma: no cover - decode(errors=replace)는 사실상 안 터진다
        return "(응답을 읽지 못했습니다)"
    if not text:
        return "(응답 본문 없음)"
    return text[:_ERROR_BODY_LIMIT]


def _hint_for_status(status: int, engine: str) -> list[str]:
    """HTTP 상태코드별로 가장 흔한 원인을 짚어준다."""
    if status in (401, 403):
        return [f"{engine} API 키가 없거나 틀렸습니다. .env를 확인하세요"]
    if status == 404:
        return ["보이스/화자 이름이나 엔드포인트 주소가 틀렸을 수 있습니다"]
    if status == 422:
        return ["요청 본문 형식이 맞지 않습니다. 보이스 ID와 모델 이름을 확인하세요"]
    if status == 429:
        return ["요청이 너무 잦거나 이번 달 사용량을 초과했습니다"]
    if status >= 500:
        return ["서버 쪽 오류입니다. 잠시 후 다시 시도하세요"]
    return []
