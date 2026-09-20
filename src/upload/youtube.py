"""YouTube Data API v3 업로드 어댑터.

인증은 설치형 앱(Desktop) OAuth다. 최초 1회만 브라우저가 열리고, 이후에는
token.json의 refresh token으로 갱신한다. client_secret.json과 token.json은
.gitignore에 있어 커밋되지 않는다 (명세서 §26).

다른 어댑터(src/tts, src/i2v)는 의존성을 늘리지 않으려고 urllib을 쓰지만,
여기는 OAuth 갱신과 재개 가능 업로드를 직접 구현할 이유가 없어 공식 클라이언트를 쓴다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..errors import DependencyMissingError, UploadError

log = logging.getLogger(__name__)

#: 업로드와 댓글 작성에 필요한 최소 범위.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

#: 한 번에 올리는 덩어리. 재개 가능 업로드라 중간에 끊겨도 이어서 간다.
CHUNK_SIZE = 4 * 1024 * 1024


def _import_google():
    """구글 클라이언트를 늦게 불러온다.

    업로드를 안 쓰는 사람에게까지 설치를 강제하지 않으려는 것이다.
    렌더 파이프라인은 이 모듈을 import하지 않는다.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise DependencyMissingError(
            "YouTube 업로드에 필요한 패키지가 없습니다",
            details=[
                "다음을 실행하세요:",
                "    pip install google-api-python-client google-auth-oauthlib",
                f"원인: {exc}",
            ],
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload


class YouTubeUploader:
    """영상 1편을 올리고 첫 댓글까지 단다."""

    def __init__(self, config: dict, *, root: Path):
        self.config = config
        self.root = root
        self._service = None

    # --- 인증 ---------------------------------------------------------

    def _credentials(self):
        Request, Credentials, InstalledAppFlow, _, _, _ = _import_google()

        token_path = self.root / str(self.config.get("tokenFile") or "token.json")
        secret_path = self.root / str(
            self.config.get("clientSecretFile") or "client_secret.json"
        )

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                return creds
            except Exception as exc:  # 만료·취소된 토큰은 다시 로그인시킨다
                log.warning("토큰 갱신 실패, 다시 로그인합니다: %s", exc)
                creds = None

        if not secret_path.exists():
            raise UploadError(
                f"{secret_path.name}이 없습니다",
                details=[
                    "Google Cloud 콘솔에서 'OAuth 클라이언트 ID / 데스크톱 앱'을 만들어",
                    f"JSON을 내려받아 {secret_path}에 두세요.",
                    "https://console.cloud.google.com/apis/credentials",
                    "이 파일은 .gitignore에 있어 커밋되지 않습니다 (명세서 §26)",
                ],
            )

        log.info("브라우저에서 Google 로그인을 진행하세요 (최초 1회)")
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        log.info("인증 완료. 다음부터는 %s를 재사용합니다", token_path.name)
        return creds

    def _client(self):
        if self._service is None:
            _, _, _, build, _, _ = _import_google()
            self._service = build("youtube", "v3", credentials=self._credentials())
        return self._service

    # --- 업로드 -------------------------------------------------------

    def upload(self, video_path: Path, metadata) -> str:
        """영상을 올리고 videoId를 돌려준다."""
        _, _, _, _, HttpError, MediaFileUpload = _import_google()

        if not video_path.exists():
            raise UploadError(f"업로드할 영상이 없습니다: {video_path}")

        body = {
            "snippet": {
                "title": metadata.title,
                "description": metadata.description,
                "tags": metadata.tags,
                "categoryId": metadata.category_id,
            },
            "status": {
                "privacyStatus": metadata.privacy_status,
                "selfDeclaredMadeForKids": metadata.made_for_kids,
            },
        }

        media = MediaFileUpload(
            str(video_path), chunksize=CHUNK_SIZE, resumable=True, mimetype="video/mp4"
        )
        request = self._client().videos().insert(
            part="snippet,status", body=body, media_body=media
        )

        size_mb = video_path.stat().st_size / (1024 * 1024)
        log.info("업로드 시작: %s (%.1f MB)", video_path.name, size_mb)

        response = None
        last_percent = -10
        try:
            while response is None:
                status, response = request.next_chunk()
                if status:
                    percent = int(status.progress() * 100)
                    if percent - last_percent >= 10:
                        log.info("  업로드 %d%%", percent)
                        last_percent = percent
        except HttpError as exc:
            raise UploadError(
                "업로드에 실패했습니다",
                details=_http_error_details(exc),
            ) from exc

        video_id = response.get("id")
        if not video_id:
            raise UploadError("업로드 응답에 videoId가 없습니다", details=[str(response)[:500]])
        return video_id

    # --- 첫 댓글 ------------------------------------------------------

    def comment(self, video_id: str, text: str) -> str | None:
        """영상에 최상위 댓글을 단다.

        '고정'은 YouTube Data API에 엔드포인트가 없어 여기서 못 한다.
        업로드 후 유튜브 앱이나 스튜디오에서 직접 눌러야 한다.
        """
        _, _, _, _, HttpError, _ = _import_google()
        body = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}},
            }
        }
        try:
            response = (
                self._client().commentThreads().insert(part="snippet", body=body).execute()
            )
        except HttpError as exc:
            # 댓글 실패로 업로드까지 되돌릴 이유는 없다. 경고만 남긴다.
            log.warning("첫 댓글을 달지 못했습니다: %s", "; ".join(_http_error_details(exc)))
            return None
        return response.get("id")


def _http_error_details(exc) -> list[str]:
    """HttpError에서 사람이 읽을 만한 부분만 뽑는다."""
    details: list[str] = []
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status:
        details.append(f"HTTP {status}")
    try:
        content = exc.content.decode("utf-8", "replace")
    except Exception:
        content = str(exc)
    details.append(content[:500])
    if status == 403 and "quota" in content.lower():
        details.append("할당량을 다 썼습니다. 업로드 1건이 1600 유닛이고 하루 10000 유닛입니다.")
    if status == 401:
        details.append("토큰이 만료됐습니다. token.json을 지우고 다시 실행하면 재인증합니다.")
    return details
