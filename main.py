#!/usr/bin/env python3
"""오늘도출근 Shorts Factory — CLI 진입점 (명세서 §24).

사용 예:

    python main.py --input ./inputs/2026-09-18
    python main.py --input ./inputs/2026-09-18 --mode final
    python main.py --input ./inputs/2026-09-18 --skip-i2v
    python main.py --input ./inputs/2026-09-18 --mode preview --force
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config import load_config
from src.errors import PipelineError
from src.pipeline import RunOptions, run
from src.render.base import MODE_PREVIEW, MODES

REPO_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="today-to-work-shorts",
        description="오늘도출근 Shorts Factory — 입력 패키지 1개를 쇼츠 영상 1편으로 만듭니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i", required=True, metavar="DIR",
        help="입력 폴더 (예: ./inputs/2026-09-18)",
    )
    parser.add_argument(
        "--mode", "-m", choices=MODES, default=MODE_PREVIEW,
        help=f"렌더 모드 (기본: {MODE_PREVIEW}). final은 preview 검수 이후에 씁니다",
    )
    parser.add_argument(
        "--skip-i2v", action="store_true",
        help="LTX 2.5 호출을 건너뛰고 I2V 씬도 정지 이미지로 렌더합니다",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="기존 결과물을 덮어쓰고, preview 없이 final을 만드는 것도 허용합니다",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="입력 검증만 하고 렌더는 하지 않습니다 (명세서 §14)",
    )
    parser.add_argument("--tts-engine", metavar="NAME", help="config/tts.json의 engine을 덮어씁니다 (edge/supertonic/offline)")
    parser.add_argument("--tts-voice", metavar="VOICE", help="TTS 보이스를 덮어씁니다")
    parser.add_argument("--output", "-o", metavar="DIR", help="출력 폴더를 직접 지정합니다 (기본: outputs/YYYY-MM-DD)")
    parser.add_argument("--config", metavar="DIR", help="config 폴더 경로 (기본: ./config)")
    parser.add_argument("--keep-work", action="store_true", help="중간 파일(.work)을 지우지 않습니다")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그를 출력합니다")
    parser.add_argument("--quiet", "-q", action="store_true", help="경고 이상만 출력합니다")
    return parser


def setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)-7s %(message)s", stream=sys.stderr)
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.quiet)

    try:
        cfg = load_config(Path(args.config) if args.config else None, repo_root=REPO_ROOT)
        result = run(
            cfg,
            RunOptions(
                input_dir=Path(args.input),
                mode=args.mode,
                skip_i2v=args.skip_i2v,
                force=args.force,
                validate_only=args.validate_only,
                tts_engine=args.tts_engine,
                tts_voice=args.tts_voice,
                output_dir=Path(args.output) if args.output else None,
                keep_work=args.keep_work,
            ),
        )
    except PipelineError as exc:
        print(f"\n실패: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130

    _print_summary(args, result)
    return 0


def _print_summary(args, result) -> None:
    print()
    if args.validate_only:
        print("입력 검증 통과")
    else:
        print(f"완료: {result.output_path}")
    print(f"로그: {result.log_path}")

    if result.warnings:
        print(f"\n경고 {len(result.warnings)}건:")
        for message in result.warnings:
            print(f"  - {message}")

    if not args.validate_only and args.mode == MODE_PREVIEW:
        print(
            "\n다음 단계 (명세서 §21):"
            "\n  1. preview.mp4로 I2V 왜곡 / TTS 발음 / 자막 타이밍 / 씬 길이 / 캐릭터 일관성 / 전체 흐름을 검수"
            f"\n  2. 문제 없으면: python main.py --input {args.input} --mode final"
        )


if __name__ == "__main__":
    raise SystemExit(main())
