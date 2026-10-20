"""ffmpeg / ffprobe helpers: probe, convert presets, captions, contact sheets and splicing."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from fractions import Fraction
from pathlib import Path

from .errors import MemeError, invalid

FFMPEG_HINT = "Install ffmpeg (macOS: `brew install ffmpeg`, Debian/Ubuntu: `apt install ffmpeg`, Windows: `winget install ffmpeg`)."

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/TTF/impact.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

POSITIONS = {"tl", "tr", "bl", "br", "center", "top", "bottom"}
INSERT_MODES = ("cut", "overlay", "pip")


# --------------------------------------------------------------------------- binaries
def ffmpeg_bin() -> str:
    path = os.environ.get("AGENT_MEMES_FFMPEG") or shutil.which("ffmpeg")
    if not path:
        raise MemeError("ffmpeg not found on PATH.", code="ffmpeg_missing", hint=FFMPEG_HINT)
    return path


def ffprobe_bin() -> str:
    path = os.environ.get("AGENT_MEMES_FFPROBE") or shutil.which("ffprobe")
    if not path:
        raise MemeError("ffprobe not found on PATH.", code="ffmpeg_missing", hint=FFMPEG_HINT)
    return path


def run_ffmpeg(args: list[str], *, timeout: float = 900) -> None:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MemeError("ffmpeg timed out.", code="ffmpeg_failed") from None
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise MemeError(
            "ffmpeg failed.",
            code="ffmpeg_failed",
            hint="See details.stderr. Re-run with simpler options to isolate the problem.",
            details={"stderr": tail},
        )


def has_filter(name: str) -> bool:
    try:
        out = subprocess.run(
            [ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
        )
    except (MemeError, OSError, subprocess.TimeoutExpired):
        return False
    return re.search(rf"^\s*\S+\s+{re.escape(name)}\s", out.stdout, re.MULTILINE) is not None


# --------------------------------------------------------------------------- probing
def _rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "0"):
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise MemeError(f"File not found: {path}", code="not_found")
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise MemeError(
            f"ffprobe could not read {path.name}.",
            code="ffmpeg_failed",
            details={"stderr": proc.stderr[-800:]},
        )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    duration = None
    for candidate in (fmt.get("duration"), (video or {}).get("duration"), (audio or {}).get("duration")):
        try:
            if candidate is not None:
                duration = float(candidate)
                break
        except ValueError:
            continue
    rational = None
    for key in ("r_frame_rate", "avg_frame_rate"):
        candidate = (video or {}).get(key)
        value = _rate(candidate)
        if value and value <= 120:
            rational = candidate
            break
    fps = _rate(rational)
    return {
        "path": str(path.resolve()),
        "duration": round(duration, 4) if duration else None,
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "fps": round(fps, 3) if fps else None,
        "fps_rational": rational,
        "video_codec": (video or {}).get("codec_name"),
        "pix_fmt": (video or {}).get("pix_fmt"),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name"),
        "sample_rate": int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        "channels": (audio or {}).get("channels"),
        "size_bytes": path.stat().st_size,
    }


# --------------------------------------------------------------------------- filter escaping
def _esc_value(text: str) -> str:
    """Escape a filter option value (level 1) and the filtergraph (level 2)."""
    level1 = re.sub(r"([\\':])", r"\\\1", text)
    return re.sub(r"([\\'\[\],;])", r"\\\1", level1)


def find_font(preferred: str | None = None) -> str | None:
    if preferred:
        return preferred if Path(preferred).is_file() else None
    return next((f for f in FONT_CANDIDATES if Path(f).is_file()), None)


def caption_filters(
    text: str,
    *,
    position: str,
    width: int,
    height: int,
    font: str,
    tmpdir: Path,
    uppercase: bool = True,
    size_ratio: float = 0.085,
) -> list[str]:
    """Classic meme captions: one drawtext per wrapped line so every line is centered."""
    text = text.upper() if uppercase else text
    fontsize = max(14, int(min(height * size_ratio, width * 0.1)))
    max_chars = max(8, int(width / (fontsize * 0.52)))
    lines = textwrap.wrap(text, width=max_chars) or [text]
    line_h = int(fontsize * 1.15)
    margin = int(height * 0.04)
    border = max(2, fontsize // 14)
    filters = []
    for i, line in enumerate(lines):
        textfile = tmpdir / f"cap-{position}-{i}.txt"
        textfile.write_text(line, encoding="utf-8")
        if position == "top":
            y = f"{margin + i * line_h}"
        else:
            y = f"h-{margin + (len(lines) - i) * line_h}"
        filters.append(
            "drawtext="
            f"fontfile={_esc_value(font)}:textfile={_esc_value(str(textfile))}:expansion=none:"
            f"fontsize={fontsize}:fontcolor=white:borderw={border}:bordercolor=black:"
            f"x=(w-text_w)/2:y={y}"
        )
    return filters


# --------------------------------------------------------------------------- convert presets
PRESET_EXTS = {
    "edit": {".mp4", ".mov", ".m4v", ".mkv"},
    "vertical": {".mp4", ".mov", ".m4v", ".mkv"},
    "square": {".mp4", ".mov", ".m4v", ".mkv"},
    "prores": {".mov"},
    "webm": {".webm"},
    "gif": {".gif"},
    "audio": {".wav"},
    "poster": {".jpg", ".jpeg", ".png"},
}

PRESETS = {
    "edit": {
        "ext": ".mp4",
        "desc": "H.264/AAC MP4, constant frame rate, 48 kHz audio. Imports cleanly into every NLE.",
    },
    "prores": {
        "ext": ".mov",
        "desc": "ProRes 422 HQ + PCM in .mov for Final Cut / Premiere / Resolve intermediates.",
    },
    "webm": {"ext": ".webm", "desc": "VP9/Opus WebM for the web, Remotion, HyperFrames."},
    "gif": {"ext": ".gif", "desc": "Palette-optimised GIF (no audio)."},
    "vertical": {"ext": ".mp4", "desc": "1080x1920 9:16 with blurred fill. TikTok / Reels / Shorts."},
    "square": {"ext": ".mp4", "desc": "1080x1080 1:1 with blurred fill."},
    "audio": {"ext": ".wav", "desc": "48 kHz stereo WAV: use the meme as a sound effect."},
    "poster": {"ext": ".jpg", "desc": "Single JPEG frame (thumbnail / poster)."},
}


def output_path(out: str | Path | None, src: Path, preset: str, stem: str | None = None) -> Path:
    """Directory -> default name inside it; missing/foreign extension -> preset extension appended."""
    ext = PRESETS[preset]["ext"]
    default_name = f"{stem or src.stem}.{preset}{ext}"
    if out is None:
        return Path.cwd() / default_name
    out = Path(out).expanduser()
    if out.is_dir() or str(out).endswith(("/", os.sep)):
        return out / default_name
    if out.suffix.lower() not in PRESET_EXTS[preset]:
        return out.with_name(out.name + ext)
    return out


def _even(n: float) -> int:
    n = int(round(n))
    return n - (n % 2)


def _fit_pad(w: int, h: int) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )


def _blur_fill(w: int, h: int) -> str:
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=24,eq=brightness=-0.08[bgb];"
        f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


def convert(
    src: str | Path,
    out: str | Path | None,
    *,
    preset: str = "edit",
    start: float | None = None,
    end: float | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: float | str | None = None,
    mute: bool = False,
    normalize_audio: bool = False,
    caption_top: str | None = None,
    caption_bottom: str | None = None,
    font: str | None = None,
    speed: float | None = None,
    stem: str | None = None,
) -> dict:
    if preset not in PRESETS:
        raise invalid(f"Unknown preset {preset!r}.", f"Choose one of: {', '.join(PRESETS)}")
    src = Path(src)
    info = probe(src)
    out = output_path(out, src, preset, stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    if start is not None and end is not None and end <= start:
        raise invalid("end must be greater than start.")
    if speed is not None and not 0.25 <= speed <= 4:
        raise invalid("speed must be between 0.25 and 4.")

    src_w, src_h = info["width"] or 854, info["height"] or 480
    if preset == "vertical":
        tw, th = width or 1080, height or 1920
    elif preset == "square":
        tw, th = width or 1080, height or 1080
    elif width and height:
        tw, th = width, height
    elif width:
        tw, th = width, src_h * width / src_w
    elif height:
        tw, th = src_w * height / src_h, height
    elif preset == "gif":
        tw, th = min(480, src_w), min(480, src_w) * src_h / src_w
    else:
        tw, th = src_w, src_h
    tw, th = _even(tw), _even(th)

    args: list[str] = []
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-i", str(src)]

    tmpdir = Path(tempfile.mkdtemp(prefix="agent-memes-"))
    try:
        chain: list[str] = []
        if preset in ("vertical", "square"):
            graph_head = _blur_fill(tw, th)
        elif width and height:
            graph_head = _fit_pad(tw, th)
        elif (tw, th) != (src_w, src_h) or src_w % 2 or src_h % 2:
            graph_head = f"scale={tw}:{th}:flags=lanczos,setsar=1"
        else:
            graph_head = "setsar=1"
        if speed:
            chain.append(f"setpts=PTS/{speed}")
        target_fps = fps or (15 if preset == "gif" else None) or info.get("fps_rational")
        if target_fps and preset != "poster":
            chain.append(f"fps={target_fps}")  # constant frame rate keeps NLEs in sync
        caption_font = None
        if caption_top or caption_bottom:
            caption_font = find_font(font)
            if not caption_font:
                raise MemeError(
                    "No font found for captions.",
                    code="invalid_input",
                    hint="Pass --font /path/to/font.ttf or set AGENT_MEMES_FONT.",
                )
            if caption_top:
                chain += caption_filters(
                    caption_top, position="top", width=tw, height=th, font=caption_font, tmpdir=tmpdir
                )
            if caption_bottom:
                chain += caption_filters(
                    caption_bottom, position="bottom", width=tw, height=th, font=caption_font, tmpdir=tmpdir
                )

        vgraph = "[0:v]" + graph_head + ("," + ",".join(chain) if chain else "")

        audio_filters: list[str] = []
        if speed:
            audio_filters += _atempo_chain(speed)
        if normalize_audio:
            audio_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        want_audio = info["has_audio"] and not mute and preset not in ("gif", "poster")

        if preset == "gif":
            graph = f"{vgraph},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4[v]"
            args += ["-filter_complex", graph, "-map", "[v]", "-loop", "0"]
        elif preset == "poster":
            args += [
                "-filter_complex",
                vgraph + "[v]",
                "-map",
                "[v]",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-update",
                "1",
            ]
        elif preset == "audio":
            if not info["has_audio"]:
                raise invalid("This clip has no audio track.")
            af = ",".join(audio_filters + ["aresample=48000"])
            args += ["-vn", "-af", af, "-ac", "2", "-c:a", "pcm_s16le"]
        else:
            args += ["-filter_complex", vgraph + "[v]", "-map", "[v]"]
            if want_audio:
                args += ["-map", "0:a:0"]
                af = ",".join(audio_filters + ["aresample=48000"])
                args += ["-af", af, "-ar", "48000", "-ac", "2"]
            if preset == "prores":
                args += ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]
                args += ["-c:a", "pcm_s16le"] if want_audio else ["-an"]
            elif preset == "webm":
                args += [
                    "-c:v",
                    "libvpx-vp9",
                    "-crf",
                    "32",
                    "-b:v",
                    "0",
                    "-row-mt",
                    "1",
                    "-pix_fmt",
                    "yuv420p",
                ]
                args += ["-c:a", "libopus", "-b:a", "128k"] if want_audio else ["-an"]
            else:
                args += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
                args += ["-movflags", "+faststart"]
                args += ["-c:a", "aac", "-b:a", "192k"] if want_audio else ["-an"]
        args.append(str(out))
        run_ffmpeg(args)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    result = probe(out)
    result["preset"] = preset
    return result


def _atempo_chain(speed: float) -> list[str]:
    chain = []
    while speed > 2.0:
        chain.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        chain.append("atempo=0.5")
        speed /= 0.5
    chain.append(f"atempo={speed:.4f}")
    return chain


# --------------------------------------------------------------------------- preview
def contact_sheet(
    src: str | Path, out: str | Path, *, frames: int = 6, columns: int = 3, tile_width: int = 320
) -> dict:
    info = probe(src)
    frames = max(1, min(frames, 16))
    columns = max(1, min(columns, frames))
    rows = -(-frames // columns)
    duration = info["duration"] or 1.0
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # sample frames evenly, skipping the very first/last instant
    rate = frames / max(duration, 0.1)
    graph = f"fps={rate:.5f},scale={tile_width}:-2,tile={columns}x{rows}:padding=4:margin=4:color=black"
    run_ffmpeg(["-i", str(src), "-vf", graph, "-frames:v", "1", "-q:v", "3", "-update", "1", str(out)])
    return {
        "path": str(out.resolve()),
        "frames": frames,
        "columns": columns,
        "rows": rows,
        "source_duration": duration,
    }


# --------------------------------------------------------------------------- insert / splice
def _position_xy(position: str, margin: int) -> tuple[str, str]:
    return {
        "tl": (f"{margin}", f"{margin}"),
        "tr": (f"W-w-{margin}", f"{margin}"),
        "bl": (f"{margin}", f"H-h-{margin}"),
        "br": (f"W-w-{margin}", f"H-h-{margin}"),
        "center": ("(W-w)/2", "(H-h)/2"),
        "top": ("(W-w)/2", f"{margin}"),
        "bottom": ("(W-w)/2", f"H-h-{margin}"),
    }[position]


def insert(
    main: str | Path,
    meme: str | Path,
    out: str | Path,
    *,
    at: float,
    mode: str = "cut",
    meme_start: float | None = None,
    meme_end: float | None = None,
    position: str = "br",
    scale: float = 0.38,
    duck: float = 0.25,
    meme_volume: float = 1.0,
) -> dict:
    """Splice a meme into ``main``.

    * ``cut``     – cutaway: main pauses at ``at``, meme plays full-frame, main resumes.
    * ``overlay`` – meme replaces the picture for its duration while main keeps running (audio ducked).
    * ``pip``     – meme plays picture-in-picture in a corner (audio ducked).
    """
    if mode not in INSERT_MODES:
        raise invalid(f"Unknown mode {mode!r}.", f"Choose one of: {', '.join(INSERT_MODES)}")
    if position not in POSITIONS:
        raise invalid(f"Unknown position {position!r}.", f"Choose one of: {', '.join(sorted(POSITIONS))}")
    m = probe(main)
    k = probe(meme)
    if not m["has_video"] or not k["has_video"]:
        raise invalid("Both inputs need a video stream.")
    main_dur = m["duration"] or 0
    if at < 0 or at > main_dur:
        raise invalid(f"--at {at} is outside the main video (0..{main_dur:.2f}s).")

    ms = max(0.0, meme_start or 0.0)
    me = min(meme_end, k["duration"]) if meme_end else k["duration"]
    if not me or me <= ms:
        raise invalid("Meme trim range is empty.")
    seg = me - ms

    W, H = _even(m["width"]), _even(m["height"])
    fps = m.get("fps_rational") or m["fps"] or 30
    fmt = f"fps={fps},format=yuv420p,setsar=1"

    args = ["-i", str(main), "-i", str(meme)]
    idx = 2
    main_a = "0:a"
    meme_a = "1:a"
    if not m["has_audio"]:
        args += ["-f", "lavfi", "-t", f"{main_dur + seg + 1:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        main_a, idx = f"{idx}:a", idx + 1
    if not k["has_audio"]:
        args += ["-f", "lavfi", "-t", f"{seg + 1:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        meme_a, idx = f"{idx}:a", idx + 1

    anorm = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    meme_v = f"[1:v]trim=start={ms:.3f}:end={me:.3f},setpts=PTS-STARTPTS"
    meme_au = f"[{meme_a}]atrim=start={ms:.3f}:end={me:.3f},asetpts=PTS-STARTPTS,{anorm},volume={meme_volume}"

    if mode == "cut":
        main_a_trim = (
            f"[{main_a}]{anorm}" if m["has_audio"] else f"[{main_a}]atrim=end={main_dur:.3f},{anorm}"
        )
        graph = ";".join(
            [
                f"[0:v]scale={W}:{H},{fmt},split=2[mv1][mv2]",
                f"[mv1]trim=end={at:.3f},setpts=PTS-STARTPTS[v0]",
                f"[mv2]trim=start={at:.3f},setpts=PTS-STARTPTS[v2]",
                f"{meme_v},{_fit_pad(W, H)},{fmt}[v1]",
                f"{main_a_trim},asplit=2[ma1][ma2]",
                f"[ma1]atrim=end={at:.3f},asetpts=PTS-STARTPTS[a0]",
                f"[ma2]atrim=start={at:.3f},asetpts=PTS-STARTPTS[a2]",
                f"{meme_au}[a1]",
                "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]",
            ]
        )
    else:
        end_t = at + seg
        if mode == "overlay":
            fg = f"{meme_v},{_fit_pad(W, H)},{fmt},setpts=PTS+{at:.3f}/TB[fg]"
            ox, oy = "0", "0"
        else:
            pw = _even(W * max(0.1, min(scale, 1.0)))
            fg = f"{meme_v},scale={pw}:-2,{fmt},pad=iw+8:ih+8:4:4:color=white,setpts=PTS+{at:.3f}/TB[fg]"
            ox, oy = _position_xy(position, int(min(W, H) * 0.04))
        enable = f"between(t,{at:.3f},{end_t:.3f})"
        graph = ";".join(
            [
                f"[0:v]scale={W}:{H},{fmt}[base]",
                fg,
                f"[base][fg]overlay=x={ox}:y={oy}:eof_action=pass:enable='{enable}'[v]",
                f"[{main_a}]{anorm},atrim=end={main_dur:.3f},volume=volume={duck}:enable='{enable}'[ma]",
                f"{meme_au},adelay={int(at * 1000)}:all=1[mm]",
                "[ma][mm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            ]
        )

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    args += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart"]
    if mode != "cut":
        args += ["-t", f"{main_dur:.3f}"]
    args.append(str(out))
    run_ffmpeg(args)
    result = probe(out)
    result.update({"mode": mode, "at": at, "meme_duration": round(seg, 3), "meme_end_at": round(at + seg, 3)})
    return result
