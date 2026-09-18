"""전체 파이프라인 오케스트레이터.

  python -m pipeline.run 0001                 # 막히는 지점까지 진행
  python -m pipeline.run 0001 --status        # 현재 어디까지 됐는지
  python -m pipeline.run 0001 --from tts      # 특정 단계부터
  python -m pipeline.run 0001 --dry-run

단계:
  1 validate  대본 검수            자동
  2 prompts   이미지 프롬프트 출력  자동
  3 images    이미지 확인          ⏸ 멈춤 — GPT 등에서 직접 생성
  4 tts       음성 생성 + 타임라인  자동
  5 video     영상 조립            자동
  6 review    눈으로 확인          ⏸ 멈춤 — 사람이 봐야 한다
  7 upload    업로드               자동
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .common import ROOT, SCENES, load_script, mark, read_state, work

STAGES = ["validate", "prompts", "images", "tts", "video", "review", "upload"]
GATES = {"images", "review"}


def sh(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def st_validate(sid: str, a) -> bool:
    return sh([sys.executable, "scripts/validate.py", f"output/{sid}.json"]) == 0


def st_prompts(sid: str, a) -> bool:
    d = load_script(sid)
    w = work(sid)
    out = subprocess.run([sys.executable, "scripts/prompts.py", f"output/{sid}.json"],
                         cwd=ROOT, capture_output=True, text=True, check=False)
    (w / "prompts.txt").write_text(out.stdout, encoding="utf-8")
    items = subprocess.run([sys.executable, "scripts/prompts.py",
                            f"output/{sid}.json", "--json"],
                           cwd=ROOT, capture_output=True, text=True, check=False)
    (w / "prompts.json").write_text(items.stdout, encoding="utf-8")
    print(f"  → build/{sid}/prompts.txt  (복붙용)")
    print(f"  → build/{sid}/prompts.json (코드용)")
    mark(sid, "prompts", ok=True)
    return True


def st_images(sid: str, a) -> bool:
    d = load_script(sid)
    missing = []
    for sc in d["scenes"]:
        base = SCENES / sid / f"{sc['n']}_{sc['role']}"
        if not (base.with_suffix(".png").exists() or base.with_suffix(".mp4").exists()):
            missing.append(f"{sc['n']}_{sc['role']}.png"
                           + ("  🎬영상 씬" if sc.get("asset_type") == "video" else ""))
    if missing:
        print(f"\n  ⏸ 이미지 {len(missing)}장이 없습니다.")
        print(f"     build/{sid}/prompts.txt 의 프롬프트로 생성해서")
        print(f"     assets/scenes/{sid}/ 에 아래 이름으로 넣어주세요.\n")
        for m in missing:
            print("       ✗", m)
        print(f"\n     🎬 표시된 씬은 i2v 로 영상까지 만들면 .mp4 로 넣으세요.")
        print(f"     다 넣으신 뒤:  python -m pipeline.run {sid}")
        mark(sid, "images", ok=False, missing=len(missing))
        return False
    print(f"  ✓ 이미지 {len(d['scenes'])}개 모두 준비됨")
    mark(sid, "images", ok=True)
    return True


def st_tts(sid: str, a) -> bool:
    cmd = [sys.executable, "-m", "pipeline.tts", sid, "--provider", a.tts]
    if a.dry_run:
        cmd.append("--dry-run")
    return sh(cmd) == 0


def st_video(sid: str, a) -> bool:
    cmd = [sys.executable, "-m", "pipeline.video", sid]
    if a.dry_run:
        cmd.append("--dry-run")
    return sh(cmd) == 0


def st_review(sid: str, a) -> bool:
    if read_state(sid).get("review", {}).get("ok"):
        print("  ✓ 확인 완료")
        return True
    final = work(sid) / "final.mp4"
    print(f"\n  ⏸ 사람이 볼 차례입니다.")
    print(f"     {final.relative_to(ROOT)} 를 열어 확인하세요.\n")
    print("       · 첫 프레임부터 자막이 떠 있는가")
    print("       · 캐릭터가 씬마다 같은 사람인가")
    print("       · 음성과 자막이 어긋나지 않는가")
    print("       · 하단 25% 에 가려지면 안 되는 게 있는가\n")
    print(f"     통과하면:  python -m pipeline.run {sid} --approve")
    return False


def st_upload(sid: str, a) -> bool:
    cmd = [sys.executable, "-m", "pipeline.upload", sid, "--privacy", a.privacy]
    if a.dry_run:
        cmd.append("--dry-run")
    return sh(cmd) == 0


RUNNERS = {"validate": st_validate, "prompts": st_prompts, "images": st_images,
           "tts": st_tts, "video": st_video, "review": st_review, "upload": st_upload}


def show_status(sid: str) -> int:
    s = read_state(sid)
    d = load_script(sid)
    print(f"\n[{sid}] {d['topic']}\n")
    for i, st in enumerate(STAGES, 1):
        got = s.get(st)
        icon = "✓" if got and got.get("ok") else ("⏸" if st in GATES else "·")
        note = ""
        if st == "images" and got and not got.get("ok"):
            note = f"  ({got.get('missing')}장 부족)"
        if st == "upload" and got and got.get("ok"):
            note = f"  {got.get('url','')}"
        print(f"  {icon} {i}. {st:9s}{note}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id")
    ap.add_argument("--from", dest="start", choices=STAGES)
    ap.add_argument("--only", choices=STAGES)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--approve", action="store_true", help="review 단계를 통과 처리")
    ap.add_argument("--tts", default="openai")
    ap.add_argument("--privacy", default="private",
                    choices=["private", "unlisted", "public"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sid = a.script_id

    if a.status:
        return show_status(sid)
    if a.approve:
        mark(sid, "review", ok=True)
        print(f"  ✓ 확인 완료 처리했습니다. 이어서:  python -m pipeline.run {sid}")
        return 0

    stages = [a.only] if a.only else STAGES[STAGES.index(a.start):] if a.start else STAGES
    done = read_state(sid)

    for st in stages:
        if not a.only and st not in GATES and done.get(st, {}).get("ok") and st != "upload":
            print(f"✓ {st} (이미 완료)")
            continue
        print(f"\n━━ {st} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if RUNNERS[st](sid, a):
            # 단계 스스로 기록하지 않았으면 여기서 기록한다
            if not read_state(sid).get(st, {}).get("ok"):
                mark(sid, st, ok=True)
        else:
            if st in GATES:
                return 0          # 정지점은 실패가 아니다
            print(f"\n✗ {st} 단계에서 멈췄습니다.")
            return 1
    print("\n완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
