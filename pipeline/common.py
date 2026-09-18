"""파이프라인 공통 — 경로, 설정 로딩, 상태 파일, 시간 계산."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
BUILD = ROOT / "build"
SCENES = ROOT / "assets" / "scenes"

_NOT_SPOKEN = re.compile(r"[\s,.?!…·~\"'“”‘’()\[\]]")

# 씬 사이에 두는 숨 쉴 틈. 붙여버리면 말이 뭉쳐 들린다.
SCENE_GAP = 0.15


def n_chars(text: str) -> int:
    return len(_NOT_SPOKEN.sub("", text))


def load_cfg(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8"))


def load_script(sid: str) -> dict:
    return json.loads((OUTPUT / f"{sid}.json").read_text(encoding="utf-8"))


def save_script(d: dict) -> None:
    (OUTPUT / f"{d['id']}.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def work(sid: str) -> Path:
    p = BUILD / sid
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── 상태 ────────────────────────────────────────────────────────────────
def state_path(sid: str) -> Path:
    return work(sid) / "state.json"


def read_state(sid: str) -> dict:
    p = state_path(sid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def mark(sid: str, stage: str, ok: bool = True, **extra) -> None:
    s = read_state(sid)
    s[stage] = {"ok": ok, **extra}
    state_path(sid).write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")


# ── 외부 도구 ───────────────────────────────────────────────────────────
def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], dry: bool = False) -> int:
    if dry:
        print("    $", " ".join(str(c) for c in cmd)[:400])
        return 0
    return subprocess.run(cmd, check=False).returncode


def probe_duration(path: Path) -> float:
    """오디오/영상 실제 길이(초). ffprobe 필요."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


# ── 타임라인 ────────────────────────────────────────────────────────────
def retime(d: dict, durations: dict[int, float]) -> dict:
    """TTS 실제 길이로 씬 타임라인을 다시 계산한다.

    대본의 start/end 는 글자수로 추정한 계획값이다. 실제 음성은 길거나 짧으므로
    영상을 만들기 전에 반드시 실측값으로 덮어써야 한다. 이걸 안 하면
    자막과 음성이 갈수록 어긋난다.
    """
    t = 0.0
    for sc in d["scenes"]:
        dur = durations.get(sc["n"], sc["end"] - sc["start"])
        sc["start"] = round(t, 3)
        sc["end"] = round(t + dur, 3)
        sc["audio_sec"] = round(dur, 3)
        t += dur + SCENE_GAP
    d["total_sec"] = round(t - SCENE_GAP, 3)
    return d
