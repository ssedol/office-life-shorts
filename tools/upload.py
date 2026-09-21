#!/usr/bin/env python3
"""렌더가 끝난 영상을 YouTube에 올린다 (명세서 §35-5, DEC-017).

    # 무엇이 올라갈지 먼저 확인 (네트워크를 쓰지 않는다)
    python tools/upload.py --input ./inputs/2026-09-18 --dry-run

    # 실제 업로드 (기본: 비공개)
    python tools/upload.py --input ./inputs/2026-09-18

    # 감사를 통과한 뒤 공개로 바로 발행
    python tools/upload.py --input ./inputs/2026-09-18 --privacy public

    # 공개로 바꾼 뒤 첫 댓글만 따로 달기 (영상은 다시 올리지 않는다)
    python tools/upload.py --input ./inputs/2026-09-18 --comment-only

제목·설명·태그·첫 댓글은 inputs/<날짜>/upload.json에 쓴다.
없는 값은 config/upload.json의 기본값을 쓰고, 제목은 project.json의 title로 넘어간다.

기본이 비공개인 이유:
    감사를 통과하지 않은 API 프로젝트에서 올린 영상은 유튜브가 어차피 비공개로 잠근다.
    공개로 지정해 봐야 잠기므로, 그럴 바에는 의도를 설정에 명시해 둔다.
    https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits

댓글 '고정'은 API에 엔드포인트가 없다. 댓글은 자동으로 달리지만
고정은 유튜브 앱이나 스튜디오에서 직접 눌러야 한다.

비공개 영상은 댓글 자체가 막혀 있다. 그래서 업로드가 private로 끝나면
댓글을 시도하지 않고 건너뛴다. 스튜디오에서 공개로 바꾼 뒤
--comment-only로 다시 부르면 그때 댓글을 단다.

업로드 결과(videoId)는 outputs/<날짜>/upload-result.json에 남는다.
--comment-only는 그 파일에서 videoId를 읽으므로 따로 붙여넣지 않아도 된다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config  # noqa: E402
from src.errors import PipelineError, UploadError  # noqa: E402
from src.upload import YouTubeUploader, load_metadata  # noqa: E402

log = logging.getLogger("upload")


def setup_logging(verbose: bool) -> None:
    """main.py와 같은 형식으로 맞춘다."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
        stream=sys.stderr,
    )
    if not verbose:
        # 구글 클라이언트가 청크마다 남기는 로그를 줄인다.
        for noisy in ("googleapiclient", "google_auth_httplib2", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

WATCH_URL = "https://www.youtube.com/watch?v={}"
STUDIO_URL = "https://studio.youtube.com/video/{}/edit"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upload",
        description="렌더 결과물을 YouTube에 올립니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, metavar="DIR", help="입력 폴더")
    parser.add_argument(
        "--video",
        metavar="FILE",
        help="올릴 영상 파일. 기본은 outputs/<날짜>/final.mp4",
    )
    parser.add_argument(
        "--output", "-o", metavar="DIR", help="렌더 결과 폴더 (기본: outputs/<날짜>)"
    )
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        help="공개 설정을 덮어씁니다 (기본: config/upload.json의 privacyStatus)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="무엇이 올라갈지만 출력하고 업로드하지 않습니다",
    )
    parser.add_argument("--no-comment", action="store_true", help="첫 댓글을 달지 않습니다")
    parser.add_argument(
        "--comment-only",
        action="store_true",
        help="영상은 올리지 않고 첫 댓글만 답니다 (공개 전환 후에 씁니다)",
    )
    parser.add_argument(
        "--video-id",
        metavar="ID",
        help="--comment-only에서 쓸 영상 ID. 기본은 upload-result.json에서 읽습니다",
    )
    parser.add_argument("--config", metavar="DIR", help="config 폴더 경로")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그")
    return parser


def _resolve_video(args, input_dir: Path, cfg) -> Path:
    if args.video:
        return Path(args.video)
    if args.output:
        return Path(args.output) / "final.mp4"
    return cfg.repo_root / "outputs" / input_dir.name / "final.mp4"


RESULT_FILE = "upload-result.json"


def _result_path(args, input_dir: Path, cfg) -> Path:
    """업로드 결과(videoId 등)를 남길 위치. 렌더 결과 폴더 옆에 둔다."""
    if args.output:
        return Path(args.output) / RESULT_FILE
    return cfg.repo_root / "outputs" / input_dir.name / RESULT_FILE


def _save_result(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing.update(data)
    path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )


def _load_video_id(args, path: Path) -> str:
    """--comment-only가 쓸 영상 ID를 찾는다."""
    if args.video_id:
        return args.video_id.strip()
    if not path.exists():
        raise UploadError(
            "어느 영상에 댓글을 달지 알 수 없습니다",
            details=[
                f"{path}가 없습니다.",
                "이 폴더를 먼저 업로드했거나, --video-id로 직접 지정해야 합니다.",
            ],
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UploadError(f"{path.name}을 읽을 수 없습니다: {exc}") from exc
    video_id = str(data.get("videoId") or "").strip()
    if not video_id:
        raise UploadError(f"{path.name}에 videoId가 없습니다")
    return video_id


def _print_plan(meta, video: Path) -> None:
    size_mb = video.stat().st_size / (1024 * 1024) if video.exists() else 0
    print()
    print("=" * 60)
    print(f"영상      {video}  ({size_mb:.1f} MB)")
    print(f"제목      {meta.title}")
    print(f"공개설정  {meta.privacy_status}")
    print(f"카테고리  {meta.category_id}")
    print(f"태그      {len(meta.tags)}개 / {sum(len(t) for t in meta.tags)}자")
    print("-" * 60)
    print(meta.description or "(설명 없음)")
    print("-" * 60)
    if meta.comment:
        print("첫 댓글:")
        print(meta.comment)
    else:
        print("첫 댓글: (없음)")
    print("=" * 60)
    print()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    try:
        cfg = load_config(Path(args.config) if args.config else None)
        input_dir = Path(args.input)
        if not input_dir.is_dir():
            raise UploadError(f"입력 폴더가 없습니다: {input_dir}")

        project_path = input_dir / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8")) if project_path.exists() else {}

        meta = load_metadata(
            input_dir, cfg.upload, project, privacy_override=args.privacy
        )
        video = _resolve_video(args, input_dir, cfg)
        result_path = _result_path(args, input_dir, cfg)

        # --- 댓글만 달기 --------------------------------------------------
        if args.comment_only:
            if not meta.comment:
                raise UploadError(
                    "달 댓글이 없습니다",
                    details=[f"{input_dir / 'upload.json'}의 comment를 채우세요"],
                )
            video_id = _load_video_id(args, result_path)
            uploader = YouTubeUploader(cfg.upload, root=cfg.repo_root)
            uploader.assert_expected_channel()

            status = uploader.privacy_status(video_id)
            if status and status != "public":
                print()
                print(f"이 영상은 아직 {status} 상태입니다.")
                print("비공개·미등록 영상은 댓글이 막혀 있습니다.")
                print(f"먼저 공개로 바꾸세요 → {STUDIO_URL.format(video_id)}")
                return 1

            print()
            print(f"영상: {WATCH_URL.format(video_id)}")
            print("첫 댓글:")
            print(meta.comment)
            comment_id = uploader.comment(video_id, meta.comment, raise_on_error=True)
            _save_result(result_path, {"commentId": comment_id})
            print()
            print("첫 댓글을 달았습니다.")
            print("댓글 고정은 API에 엔드포인트가 없어 직접 눌러야 합니다.")
            print(f"  → {WATCH_URL.format(video_id)}")
            return 0

        _print_plan(meta, video)

        if args.dry_run:
            print("--dry-run 이므로 업로드하지 않았습니다.")
            return 0

        if not video.exists():
            raise UploadError(
                f"올릴 영상이 없습니다: {video}",
                details=["먼저 렌더하세요:", f"    python main.py --input {input_dir} --mode final"],
            )

        uploader = YouTubeUploader(cfg.upload, root=cfg.repo_root)

        # 업로드 전에 어느 채널인지 확인한다. 잘못 올라가면 옮길 방법이 없다.
        channel_id, channel_title = uploader.assert_expected_channel()
        print(f"업로드 채널  {channel_title} ({channel_id})")
        if not str(cfg.upload.get("expectedChannelId") or "").strip():
            print("  ↑ config/upload.json의 expectedChannelId가 비어 있습니다.")
            print("    이 채널이 맞으면 그 값에 위 채널ID를 적어두세요. 다음부터 자동으로 막아 줍니다.")

        video_id = uploader.upload(video, meta)

        print()
        print(f"업로드 완료: {WATCH_URL.format(video_id)}")

        _save_result(result_path, {
            "videoId": video_id,
            "channelId": channel_id,
            "channelTitle": channel_title,
            "privacyStatus": meta.privacy_status,
            "title": meta.title,
            "uploadedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        })

        # 비공개 영상은 댓글이 막혀 있다. 실패할 요청을 보내 할당량을 쓰지 않는다.
        commented = False
        comment_pending = False
        if meta.comment and not args.no_comment:
            if meta.privacy_status == "public":
                if uploader.comment(video_id, meta.comment):
                    commented = True
                    print("첫 댓글을 달았습니다.")
            else:
                comment_pending = True
                print(f"첫 댓글은 건너뛰었습니다 — {meta.privacy_status} 영상은 댓글이 막혀 있습니다.")

        print()
        print("남은 것:")
        step = 1
        if meta.privacy_status != "public":
            print(f"  {step}. 공개 전환 (감사 전에는 유튜브가 비공개로 잠급니다)")
            step += 1
        print(f"  {step}. 'AI 생성 콘텐츠' 공시 체크")
        step += 1
        if comment_pending:
            print(f"  {step}. 공개로 바꾼 뒤 아래를 실행하면 첫 댓글이 달립니다:")
            print(f"       python tools/upload.py --input {input_dir} --comment-only")
            step += 1
        if commented:
            print(f"  {step}. 댓글 고정 (API에 엔드포인트가 없습니다)")
            step += 1
        print(f"  → {STUDIO_URL.format(video_id)}")
        return 0

    except PipelineError as exc:
        print(f"\n실패: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
