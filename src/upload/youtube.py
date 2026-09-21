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

    # --- 채널 확인 ----------------------------------------------------

    def current_channel(self) -> tuple[str, str]:
        """지금 토큰이 붙은 채널의 (id, 제목)을 돌려준다."""
        _, _, _, _, HttpError, _ = _import_google()
        try:
            response = self._client().channels().list(part="snippet", mine=True).execute()
        except HttpError as exc:
            raise UploadError("채널 정보를 읽지 못했습니다", details=_http_error_details(exc)) from exc
        items = response.get("items") or []
        if not items:
            raise UploadError(
                "이 계정에 연결된 YouTube 채널이 없습니다",
                details=["로그인한 Google 계정에 채널이 있는지 확인하세요"],
            )
        return items[0]["id"], items[0]["snippet"]["title"]

    def assert_expected_channel(self) -> tuple[str, str]:
        """config의 expectedChannelId와 다르면 업로드 전에 멈춘다.

        Google 계정에 채널이 여러 개면 OAuth 동의 때 고른 채널로 업로드된다.
        로그인 화면에서 채널을 잘못 고르면 엉뚱한 채널에 올라가는데,
        올라간 뒤에는 옮길 방법이 없어 지우고 다시 올리는 수밖에 없다.
        2026-09-21에 실제로 그 일이 있었다.
        """
        channel_id, title = self.current_channel()
        expected = str(self.config.get("expectedChannelId") or "").strip()
        if not expected:
            log.warning(
                "업로드 대상 채널: %s (%s) — config의 expectedChannelId가 비어 있어 확인만 합니다",
                title, channel_id,
            )
            return channel_id, title
        if channel_id != expected:
            raise UploadError(
                "로그인한 채널이 설정과 다릅니다. 업로드를 중단했습니다",
                details=[
                    f"지금 토큰의 채널: {title} ({channel_id})",
                    f"config/upload.json의 expectedChannelId: {expected}",
                    "token.json을 지우고 다시 실행한 뒤,",
                    "Google 로그인 화면에서 올바른 채널을 고르세요.",
                ],
            )
        log.info("업로드 대상 채널 확인: %s (%s)", title, channel_id)
        return channel_id, title

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

    def comment(self, video_id: str, text: str, *, raise_on_error: bool = False) -> str | None:
        """영상에 최상위 댓글을 단다.

        '고정'은 YouTube Data API에 엔드포인트가 없어 여기서 못 한다.
        업로드 후 유튜브 앱이나 스튜디오에서 직접 눌러야 한다.

        비공개 영상은 댓글이 막혀 있어 항상 실패한다(commentsDisabled).
        업로드 직후에는 경고만 남기고, --comment-only로 따로 부를 때는
        raise_on_error=True로 실패를 드러낸다.
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
            details = _http_error_details(exc)
            if raise_on_error:
                raise UploadError("첫 댓글을 달지 못했습니다", details=details) from exc
            # 업로드 자체는 끝났다. 댓글 실패로 되돌릴 이유는 없다.
            log.warning("첫 댓글을 달지 못했습니다: %s", "; ".join(details))
            return None
        return response.get("id")

    def privacy_status(self, video_id: str) -> str | None:
        """영상의 현재 공개 상태를 읽는다. 못 읽으면 None."""
        _, _, _, _, HttpError, _ = _import_google()
        try:
            response = self._client().videos().list(part="status", id=video_id).execute()
        except HttpError:
            return None
        items = response.get("items") or []
        if not items:
            return None
        return items[0].get("status", {}).get("privacyStatus")


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
    if "commentsDisabled" in content:
        details.append("비공개 영상은 댓글을 달 수 없습니다.")
        details.append("스튜디오에서 공개로 바꾼 뒤 --comment-only로 다시 실행하세요.")
    return details
