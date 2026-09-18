"""04.5 TTS — 씬별 음성을 만들고 실제 길이를 잰다.

  python -m pipeline.tts 0001 --provider openai
  python -m pipeline.tts 0001 --provider manual   # 직접 넣은 파일을 쓰기만 함

결과: build/<id>/audio/<n>_<role>.mp3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import (BUILD, have, load_script, mark, probe_duration, retime,
                     save_script, work)


def tts_openai(text: str, style: str, speed: float, dst: Path) -> None:
    from openai import OpenAI
    client = OpenAI()
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts", voice="onyx", input=text,
        instructions=style, speed=speed, response_format="mp3",
    ) as r:
        r.stream_to_file(dst)


def tts_elevenlabs(text: str, style: str, speed: float, dst: Path) -> None:
    from elevenlabs.client import ElevenLabs
    import os
    client = ElevenLabs()
    voice_id = os.environ.get("ELEVEN_VOICE_ID")
    if not voice_id:
        raise RuntimeError("ELEVEN_VOICE_ID 환경변수를 설정하세요")
    audio = client.text_to_speech.convert(
        voice_id=voice_id, text=text,
        model_id="eleven_multilingual_v2", output_format="mp3_44100_128")
    with dst.open("wb") as fh:
        for chunk in audio:
            fh.write(chunk)


def tts_manual(text: str, style: str, speed: float, dst: Path) -> None:
    raise FileNotFoundError(
        f"수동 모드입니다. {dst.name} 파일을 직접 넣어주세요.\n      낭독할 문장: {text}")


PROVIDERS = {"openai": tts_openai, "elevenlabs": tts_elevenlabs, "manual": tts_manual}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="openai")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    d = load_script(a.script_id)
    adir = work(a.script_id) / "audio"
    adir.mkdir(exist_ok=True)
    voice = d.get("voice", {})
    made = failed = 0

    print(f"[{d['id']}] TTS · {a.provider}")
    for sc in d["scenes"]:
        dst = adir / f"{sc['n']}_{sc['role']}.mp3"
        if a.dry_run:
            print(f"  + {sc['n']} {sc['role']:6s} → {dst.name}   \"{sc['tts'][:34]}…\"")
            made += 1
            continue
        if dst.exists() and not a.force:
            print(f"  - {sc['n']} {sc['role']:6s} 이미 있음")
            continue
        try:
            PROVIDERS[a.provider](sc["tts"], voice.get("style", ""),
                                  voice.get("speed", 1.0), dst)
            print(f"  ✓ {sc['n']} {sc['role']:6s} → {dst.name}")
            made += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {sc['n']} {sc['role']:6s} {e}")
            failed += 1

    if a.dry_run:
        return 0
    if failed:
        mark(a.script_id, "tts", ok=False)
        return 1

    # 실측 길이로 타임라인을 다시 계산한다. 이 단계가 없으면 자막이 어긋난다.
    if not have("ffprobe"):
        print("\n  ffprobe 가 없어 길이를 재지 못했습니다. 타임라인은 계획값 그대로입니다.")
        mark(a.script_id, "tts", ok=True, retimed=False)
        return 0

    durs = {sc["n"]: probe_duration(adir / f"{sc['n']}_{sc['role']}.mp3")
            for sc in d["scenes"]}
    d = retime(d, durs)
    save_script(d)
    print(f"\n  타임라인 재계산 완료 · 총 {d['total_sec']}초")
    for sc in d["scenes"]:
        print(f"    {sc['n']} {sc['role']:6s} {sc['start']:6.2f}–{sc['end']:6.2f}")
    mark(a.script_id, "tts", ok=True, retimed=True, total_sec=d["total_sec"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
