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

    # 이미 업로드한 영상의 썸네일만 설정/재설정
    python tools/upload.py --input ./inputs/2026-09-18 --thumbnail-only

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
import hashlib
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
        "--thumbnail",
        metavar="FILE",
        help="커스텀 썸네일 파일. 기본은 input 폴더의 thumbnail-final.png 또는 thumbnail.png",
    )
    parser.add_argument(
        "--no-thumbnail",
        action="store_true",
        help="커스텀 썸네일 API 설정을 건너뜁니다",
    )
    parser.add_argument(
        "--comment-only",
        action="store_true",
        help="영상은 올리지 않고 첫 댓글만 답니다 (공개 전환 후에 씁니다)",
    )
    parser.add_argument(
        "--thumbnail-only",
        action="store_true",
        help="영상은 올리지 않고 기존 videoId의 커스텀 썸네일만 설정합니다",
    )
    parser.add_argument(
        "--video-id",
        metavar="ID",
        help="--comment-only/--thumbnail-only에서 쓸 영상 ID. 기본은 upload-result.json에서 읽습니다",
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


def _resolve_thumbnail(args, input_dir: Path) -> Path | None:
    """명시한 파일 또는 회차 폴더의 최종 썸네일을 고른다."""
    if args.no_thumbnail:
        return None
    if args.thumbnail:
        return Path(args.thumbnail)
    for name in ("thumbnail-final.png", "thumbnail.png", "thumbnail-final.jpg", "thumbnail.jpg"):
        candidate = input_dir / name
        if candidate.is_file():
            return candidate
    return None


RESULT_FILE = "upload-result.json"
CHARACTER_QA_FILE = "character-qa.json"
MASTER_CHARACTER_FILES = (
    "ref-01-shocked.png",
    "ref-02-happy-coffee.png",
    "ref-03-talking-blank-bubble.png",
    "ref-04-side-with-back-figure.png",
    "ref-05-desk-whiteboard.png",
)


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_character_qa(
    input_dir: Path, repo_root: Path, thumbnail: Path | None = None
) -> None:
    """마스터 캐릭터 대조 기록이 현재 8개 장면과 정확히 맞는지 확인한다.

    이미지가 바뀐 뒤 예전 검수 기록을 재사용하지 못하도록 장면과 마스터 파일의
    SHA-256을 함께 검증한다. 캐릭터가 같은지에 대한 시각 판단은 생성 직후 사람이
    하며, 이 함수는 그 판단이 빠지거나 실패한 상태로 업로드되는 것을 막는다.
    """
    qa_path = input_dir / CHARACTER_QA_FILE
    try:
        data = json.loads(qa_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise UploadError(
            "마스터 캐릭터 일치 검수 기록이 없습니다",
            details=[
                f"검수 파일: {qa_path}",
                "생성한 scene-01.png~scene-08.png를 assets/character의 마스터 5장과",
                "눈·얼굴형·머리 모양·홍조·옷·사원증·선 굵기 기준으로 대조하세요.",
            ],
        ) from exc

    problems: list[str] = []
    if data.get("approved") is not True:
        problems.append("approved가 true가 아닙니다")
    if not data.get("reviewedAt"):
        problems.append("reviewedAt이 없습니다")

    scene_records = {
        str(item.get("file") or ""): item
        for item in data.get("scenes", [])
        if isinstance(item, dict)
    }
    expected_scenes = [f"scene-{index:02d}.png" for index in range(1, 9)]
    for name in expected_scenes:
        path = input_dir / name
        record = scene_records.get(name)
        if not path.is_file():
            problems.append(f"{name} 파일이 없습니다")
            continue
        if record is None:
            problems.append(f"{name} 검수 기록이 없습니다")
            continue
        if record.get("matchesMaster") is not True:
            problems.append(f"{name}이 마스터 캐릭터와 일치 판정을 받지 못했습니다")
        if not str(record.get("notes") or "").strip():
            problems.append(f"{name}의 시각 검수 메모가 없습니다")
        if str(record.get("sha256") or "").lower() != _sha256(path):
            problems.append(f"{name}이 캐릭터 검수 후 변경됐습니다")

    master_dir = repo_root / "assets" / "character"
    master_records = {
        Path(str(item.get("file") or "")).name: item
        for item in data.get("masterReferences", [])
        if isinstance(item, dict)
    }
    for name in MASTER_CHARACTER_FILES:
        path = master_dir / name
        record = master_records.get(name)
        if not path.is_file():
            problems.append(f"마스터 참조 파일이 없습니다: {path}")
            continue
        if record is None:
            problems.append(f"마스터 참조 기록이 없습니다: {name}")
            continue
        if str(record.get("sha256") or "").lower() != _sha256(path):
            problems.append(f"마스터 참조가 검수 후 변경됐습니다: {name}")

    if thumbnail is not None:
        record = data.get("thumbnail")
        if not thumbnail.is_file():
            problems.append(f"썸네일 파일이 없습니다: {thumbnail}")
        elif not isinstance(record, dict):
            problems.append("썸네일 캐릭터 검수 기록이 없습니다")
        else:
            if Path(str(record.get("file") or "")).name != thumbnail.name:
                problems.append("검수한 썸네일 파일과 실제 업로드 파일이 다릅니다")
            if record.get("matchesMaster") is not True:
                problems.append("썸네일이 마스터 캐릭터와 일치 판정을 받지 못했습니다")
            if not str(record.get("notes") or "").strip():
                problems.append("썸네일의 시각 검수 메모가 없습니다")
            if str(record.get("sha256") or "").lower() != _sha256(thumbnail):
                problems.append("썸네일이 캐릭터 검수 후 변경됐습니다")

    if problems:
        raise UploadError(
            "마스터 캐릭터 일치 검수를 통과하지 못했습니다",
            details=[f"검수 파일: {qa_path}", *problems],
        )


def _record_thumbnail_set(path: Path, thumbnail: Path) -> None:
    """성공 처리 전에 커스텀 썸네일 적용 증거를 결과 파일에 남긴다."""
    _save_result(
        path,
        {
            "thumbnailSet": True,
            "thumbnailMethod": "api",
            "thumbnailFile": str(thumbnail.resolve()),
            "thumbnailSetAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def _assert_thumbnail_recorded(path: Path, thumbnail: Path) -> None:
    """자동화가 썸네일 적용 없이 성공 처리하지 못하게 하는 마지막 게이트."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise UploadError(
            "썸네일 적용 기록을 확인하지 못했습니다",
            details=[f"결과 파일: {path}"],
        ) from exc

    expected = str(thumbnail.resolve())
    actual = str(data.get("thumbnailFile") or "")
    if data.get("thumbnailSet") is not True or actual != expected or not data.get("thumbnailSetAt"):
        raise UploadError(
            "커스텀 썸네일 적용 확인이 끝나지 않았습니다",
            details=[
                f"결과 파일: {path}",
                f"예상 썸네일: {expected}",
                f"기록된 썸네일: {actual or '(없음)'}",
                "thumbnailSet=true, thumbnailFile, thumbnailSetAt이 모두 있어야 성공입니다.",
            ],
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


def _print_plan(meta, video: Path, thumbnail: Path | None) -> None:
    size_mb = video.stat().st_size / (1024 * 1024) if video.exists() else 0
    print()
    print("=" * 60)
    print(f"영상      {video}  ({size_mb:.1f} MB)")
    print(f"썸네일    {thumbnail or '(건너뜀)'}")
    print(f"제목      {meta.title}")
    print(f"공개설정  {meta.privacy_status}")
    print(f"AI 콘텐츠 {'표시' if meta.contains_synthetic_media else '미표시'}")
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


def _force_utf8_output() -> None:
    """콘솔 인코딩 때문에 업로드가 죽지 않게 한다.

    Windows 콘솔 기본값은 cp949라 설명란 머리말의 이모지(🔗, 🎵)를 인코딩하지 못하고
    UnicodeEncodeError로 멈춘다. 그 지점이 실제 업로드 직전이라 영상이 안 올라간다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
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
        thumbnail = _resolve_thumbnail(args, input_dir)
        result_path = _result_path(args, input_dir, cfg)

        # --- 썸네일만 설정 ----------------------------------------------
        if args.thumbnail_only:
            if thumbnail is None:
                raise UploadError(
                    "설정할 썸네일을 찾지 못했습니다",
                    details=["--thumbnail FILE로 지정하거나 회차 폴더에 썸네일을 두세요"],
                )
            video_id = _load_video_id(args, result_path)
            uploader = YouTubeUploader(cfg.upload, root=cfg.repo_root)
            uploader.assert_expected_channel()
            uploader.wait_until_processed(
                video_id,
                timeout_sec=int(cfg.upload.get("timeoutSec") or 600),
            )
            uploader.set_thumbnail(video_id, thumbnail)
            _record_thumbnail_set(result_path, thumbnail)
            _assert_thumbnail_recorded(result_path, thumbnail)
            print(f"커스텀 썸네일 설정 완료: {thumbnail}")
            print(f"  → {STUDIO_URL.format(video_id)}")
            return 0

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

        # 신규 업로드와 dry-run 모두, 현재 이미지에 묶인 캐릭터 시각 검수 기록이
        # 있어야 진행한다. 기존 영상의 댓글/썸네일 보정은 위 분기에서 제외한다.
        _assert_character_qa(input_dir, cfg.repo_root, thumbnail)

        _print_plan(meta, video, thumbnail)

        if args.dry_run:
            print("--dry-run 이므로 업로드하지 않았습니다.")
            return 0

        if not video.exists():
            raise UploadError(
                f"올릴 영상이 없습니다: {video}",
                details=["먼저 렌더하세요:", f"    python main.py --input {input_dir} --mode final"],
            )
        if thumbnail is None and not args.no_thumbnail:
            raise UploadError(
                "업로드할 썸네일을 찾지 못했습니다",
                details=[
                    f"{input_dir}에 thumbnail-final.png 또는 thumbnail.png를 두거나",
                    "--thumbnail FILE로 지정하세요.",
                ],
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
        if meta.contains_synthetic_media:
            print("AI 생성 콘텐츠 표시를 함께 설정했습니다.")

        _save_result(result_path, {
            "videoId": video_id,
            "channelId": channel_id,
            "channelTitle": channel_title,
            "privacyStatus": meta.privacy_status,
            "containsSyntheticMedia": meta.contains_synthetic_media,
            "title": meta.title,
            "uploadedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        })

        thumbnail_error = None
        if thumbnail is not None:
            try:
                print("YouTube 영상 처리가 끝날 때까지 기다린 뒤 썸네일을 설정합니다.")
                uploader.wait_until_processed(
                    video_id,
                    timeout_sec=int(cfg.upload.get("timeoutSec") or 600),
                )
                uploader.set_thumbnail(video_id, thumbnail)
                _record_thumbnail_set(result_path, thumbnail)
                _assert_thumbnail_recorded(result_path, thumbnail)
                print(f"커스텀 썸네일 설정 완료: {thumbnail}")
            except UploadError as exc:
                thumbnail_error = exc
                _save_result(result_path, {
                    "thumbnailSet": False,
                    "thumbnailMethod": "api_failed",
                    "thumbnailFile": str(thumbnail.resolve()),
                    "thumbnailError": str(exc),
                })
                print(f"커스텀 썸네일 API 설정 실패: {exc}", file=sys.stderr)

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
        if comment_pending:
            print(f"  {step}. 공개로 바꾼 뒤 아래를 실행하면 첫 댓글이 달립니다:")
            print(f"       python tools/upload.py --input {input_dir} --comment-only")
            step += 1
        if commented:
            print(f"  {step}. 댓글 고정 (API에 엔드포인트가 없습니다)")
            step += 1
        if thumbnail_error is not None:
            print(f"  {step}. Studio에서 커스텀 썸네일 직접 설정")
            print(f"       파일: {thumbnail}")
            step += 1
        print(f"  → {STUDIO_URL.format(video_id)}")
        return 2 if thumbnail_error is not None else 0

    except PipelineError as exc:
        print(f"\n실패: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
