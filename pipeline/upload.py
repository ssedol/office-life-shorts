"""07 업로드 — YouTube Data API v3.

  python -m pipeline.upload 0001 --dry-run
  python -m pipeline.upload 0001 --privacy private   # 먼저 비공개로 올려 확인 권장

준비:
  1) Google Cloud 프로젝트에서 YouTube Data API v3 활성화
  2) OAuth 클라이언트(데스크톱 앱) 만들어 client_secret.json 로 저장
  3) pip install google-auth-oauthlib google-api-python-client
  첫 실행 때 브라우저 인증 후 token.json 이 저장된다.

⚠️ videos.insert 의 할당량 비용은 자료마다 다르다. 반드시 공식 계산기로 확인할 것:
   https://developers.google.com/youtube/v3/determine_quota_cost
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import ROOT, load_script, mark, work

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token, secret = ROOT / "token.json", ROOT / "client_secret.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secret.exists():
                raise FileNotFoundError("client_secret.json 이 없습니다. 위 준비 단계를 보세요.")
            creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES) \
                .run_local_server(port=0)
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id")
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"],
                    default="private")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    d = load_script(a.script_id)
    yt = d["youtube"]
    video = work(a.script_id) / "final.mp4"

    body = {
        "snippet": {
            "title": yt["title"],
            "description": yt["description"],
            "tags": [t.lstrip("#") for t in yt["tags"]],
            "categoryId": "22",           # People & Blogs
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": a.privacy,
            "selfDeclaredMadeForKids": yt.get("made_for_kids", False),
        },
    }

    print(f"[{d['id']}] 업로드 · {a.privacy}")
    print(f"  제목: {yt['title']}")
    print(f"  태그: {' '.join(yt['tags'])}")
    print(f"  파일: {video.relative_to(ROOT) if video.exists() else '(없음) ' + str(video.name)}")
    if yt.get("ai_disclosure"):
        print("  ⚠️ AI 고지 필요 — API 로는 설정되지 않습니다.")
        print("     업로드 후 스튜디오에서 '변경되거나 합성된 콘텐츠'를 직접 켜세요.")
    print(f"  고정 댓글: {yt['pinned_comment']}")

    if a.dry_run:
        print("\n  (모의 실행 — 실제로 올리지 않았습니다)")
        return 0
    if not video.exists():
        print("  ✗ final.mp4 가 없습니다. video 단계를 먼저 돌리세요.", file=sys.stderr)
        return 1

    from googleapiclient.http import MediaFileUpload
    svc = get_service()
    req = svc.videos().insert(part="snippet,status", body=body,
                              media_body=MediaFileUpload(str(video),
                                                         chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"    {int(status.progress() * 100)}%")
    vid = resp["id"]
    url = f"https://youtube.com/shorts/{vid}"
    print(f"  ✓ {url}")

    # 고정 댓글: 댓글창 최상단이 비어 있으면 첫 댓글이 안 달린다
    try:
        svc.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": vid,
            "topLevelComment": {"snippet": {"textOriginal": yt["pinned_comment"]}}}}).execute()
        print("  ✓ 고정 댓글 작성 (고정 처리는 스튜디오에서 직접)")
    except Exception as e:  # noqa: BLE001
        print(f"  ! 댓글 실패: {e}")

    d["youtube"]["video_id"] = vid
    d["youtube"]["url"] = url
    d["status"] = "published"
    from .common import save_script
    save_script(d)
    mark(a.script_id, "upload", ok=True, url=url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
