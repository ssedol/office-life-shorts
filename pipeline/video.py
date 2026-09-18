"""05 영상 조립 — 이미지/영상 + 켄번즈 + 자막 + 음성 → mp4.

  python -m pipeline.video 0001 --dry-run    # ffmpeg 명령만 출력
  python -m pipeline.video 0001

씬별 소스 우선순위:
  1) assets/scenes/<id>/<n>_<role>.mp4  ← i2v 로 만든 영상이 있으면 그걸 쓴다
  2) assets/scenes/<id>/<n>_<role>.png  ← 없으면 정지 이미지 + 켄번즈
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import (ROOT, SCENES, SCENE_GAP, have, load_cfg, load_script,
                     mark, run, work)

W, H, FPS = 1080, 1920, 30


def ass_color(hex_rgb: str) -> str:
    """#RRGGBB → ASS 의 &HAABBGGRR."""
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ass_time(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(d: dict, dst: Path) -> None:
    """자막 파일. 상단 20~35% 구간에 배치한다 (하단은 유튜브 UI가 덮는다)."""
    pal = load_cfg("style")["palette"]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Pretendard,86,{ass_color(pal['white'])},&H000000FF,{ass_color(pal['navy'])},&H64000000,-1,0,0,0,100,100,0,0,1,9,4,8,70,70,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for sc in d["scenes"]:
        text = sc["caption"].replace("\n", "\\N")
        # 자막은 말보다 0.15초 먼저 뜬다. 늦게 뜨면 느리게 느껴진다.
        start = max(sc["start"] - 0.15, 0)
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(sc['end'])},"
                     f"Main,,0,0,0,,{text}")
    dst.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def kenburns(motion: str, frames: int) -> str:
    """정지 이미지에 줄 움직임. zoompan 필터 식."""
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    match motion:
        case "zoom_in":
            z, pos = "'min(zoom+0.0009,1.18)'", center
        case "zoom_out":
            z, pos = "'if(lte(zoom,1.0),1.18,max(1.001,zoom-0.0009))'", center
        case "pan_right":
            z, pos = "1.12", f"x='(iw-iw/zoom)*on/{max(frames-1,1)}':y='ih/2-(ih/zoom/2)'"
        case "pan_left":
            z, pos = "1.12", f"x='(iw-iw/zoom)*(1-on/{max(frames-1,1)})':y='ih/2-(ih/zoom/2)'"
        case _:
            z, pos = "1.04", center
    return (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
            f"crop={W*2}:{H*2},"
            f"zoompan=z={z}:{pos}:d={frames}:s={W}x{H}:fps={FPS},"
            f"format=yuv420p")


def scene_clip(d: dict, sc: dict, wdir: Path, dry: bool) -> Path | None:
    """씬 하나를 mp4 클립으로 만든다. 길이는 음성 + 씬 간격."""
    base = SCENES / d["id"] / f"{sc['n']}_{sc['role']}"
    dur = round(sc.get("audio_sec", sc["end"] - sc["start"]) + SCENE_GAP, 3)
    dst = wdir / "clips" / f"{sc['n']}.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)

    mp4, png = base.with_suffix(".mp4"), base.with_suffix(".png")
    if mp4.exists():
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(mp4), "-t", str(dur),
               "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                      f"crop={W}:{H},fps={FPS},format=yuv420p",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(dst)]
    elif png.exists() or dry:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-t", str(dur),
               "-vf", kenburns(sc.get("motion", "static"), int(dur * FPS)),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", str(dst)]
    else:
        print(f"  ✗ {sc['n']} {sc['role']}: 이미지도 영상도 없습니다 ({png.name})")
        return None

    src = "🎬영상" if mp4.exists() else "🖼이미지"
    print(f"  · {sc['n']} {sc['role']:6s} {src} {dur:5.2f}초")
    run(cmd, dry)
    return dst


def scene_audio(d: dict, sc: dict, wdir: Path, dry: bool) -> Path | None:
    """음성 뒤에 씬 간격만큼 무음을 붙여 영상 길이와 맞춘다."""
    src = wdir / "audio" / f"{sc['n']}_{sc['role']}.mp3"
    if not src.exists() and not dry:
        print(f"  ✗ {sc['n']} {sc['role']}: 음성 파일이 없습니다. tts 단계를 먼저 돌리세요")
        return None
    dur = round(sc.get("audio_sec", sc["end"] - sc["start"]) + SCENE_GAP, 3)
    dst = wdir / "clips" / f"{sc['n']}.wav"
    run(["ffmpeg", "-y", "-i", str(src), "-af", f"apad=whole_dur={dur}",
         "-t", str(dur), "-ar", "48000", "-ac", "2", str(dst)], dry)
    return dst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if not a.dry_run and not have("ffmpeg"):
        print("ffmpeg 가 필요합니다. https://ffmpeg.org 에서 설치하세요.", file=sys.stderr)
        return 1

    d = load_script(a.script_id)
    wdir = work(a.script_id)
    print(f"[{d['id']}] 영상 조립 · {d['total_sec']}초")

    clips, audios = [], []
    for sc in d["scenes"]:
        c = scene_clip(d, sc, wdir, a.dry_run)
        s = scene_audio(d, sc, wdir, a.dry_run)
        if c is None or s is None:
            mark(a.script_id, "video", ok=False)
            return 1
        clips.append(c)
        audios.append(s)

    vlist = wdir / "clips" / "video.txt"
    alist = wdir / "clips" / "audio.txt"
    vlist.write_text("".join(f"file '{p.name}'\n" for p in clips), encoding="utf-8")
    alist.write_text("".join(f"file '{p.name}'\n" for p in audios), encoding="utf-8")

    ass = wdir / "subtitles.ass"
    build_ass(d, ass)
    print(f"  · 자막 {ass.name} ({len(d['scenes'])}줄)")

    final = wdir / "final.mp4"
    print("  · 합치기")
    run(["ffmpeg", "-y",
         "-f", "concat", "-safe", "0", "-i", str(vlist),
         "-f", "concat", "-safe", "0", "-i", str(alist),
         "-vf", f"ass={ass}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-r", str(FPS), "-shortest", "-movflags", "+faststart", str(final)], a.dry_run)

    print(f"\n  → {final.relative_to(ROOT)}")
    mark(a.script_id, "video", ok=True, path=str(final.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
