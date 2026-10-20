"""Paste-ready integration snippets for programmatic editors."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

TARGETS = ("ffmpeg", "remotion", "hyperframes", "html", "moviepy", "markdown")


def _sec(x: float | None) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") if x is not None else "0"


def render(
    target: str,
    *,
    path: str,
    rel_path: str,
    duration: float | None,
    at: float = 0.0,
    attribution: str | None,
    has_audio: bool,
    name: str,
) -> str:
    credit = attribution or name
    dur = _sec(duration)
    if target == "ffmpeg":
        q = shlex.quote
        return "\n".join(
            [
                f"# Cut-in the meme at {_sec(at)}s (main pauses, meme plays full-frame, main resumes):",
                f"agent-memes insert --into main.mp4 --meme {q(path)} --at {_sec(at)} --mode cut --out edit.mp4",
                "# Picture-in-picture instead:",
                f"agent-memes insert --into main.mp4 --meme {q(path)} --at {_sec(at)} --mode pip --position br --out edit.mp4",
                f"# Credit: {credit}",
            ]
        )
    if target == "remotion":
        var = "".join(p.capitalize() for p in name.replace("-", " ").replace("_", " ").split()[:4]) or "Meme"
        return "\n".join(
            [
                "import {OffthreadVideo, Sequence, staticFile, useVideoConfig} from 'remotion';",
                "",
                f"// Credit: {credit}",
                f"export const {var}Meme: React.FC<{{at?: number}}> = ({{at = {_sec(at)}}}) => {{",
                "  const {fps} = useVideoConfig();",
                "  return (",
                f"    <Sequence from={{Math.round(at * fps)}} durationInFrames={{Math.round({dur} * fps)}}>",
                f"      <OffthreadVideo src={{staticFile({json.dumps(rel_path.removeprefix('public/'))})}} />",
                "    </Sequence>",
                "  );",
                "};",
            ]
        )
    if target == "hyperframes":
        audio_attr = 'data-has-audio="true"' if has_audio else "muted"
        return "\n".join(
            [
                f"<!-- Credit: {credit} -->",
                "<video",
                f'  id="meme-{name[:40]}"',
                '  class="clip"',
                f'  src="{rel_path}"',
                "  playsinline",
                f"  {audio_attr}",
                f'  data-start="{_sec(at)}"',
                f'  data-duration="{dur}"',
                '  data-track-index="2"',
                '  data-volume="1"',
                "></video>",
            ]
        )
    if target == "html":
        return "\n".join(
            [
                '<figure class="meme">',
                f'  <video src="{rel_path}" autoplay loop muted playsinline></video>',
                f"  <figcaption>{credit}</figcaption>",
                "</figure>",
            ]
        )
    if target == "moviepy":
        return "\n".join(
            [
                "from moviepy import VideoFileClip, CompositeVideoClip  # moviepy >= 2",
                "",
                'main = VideoFileClip("main.mp4")',
                f"meme = VideoFileClip({json.dumps(path)}).with_start({_sec(at)})",
                "meme = meme.resized(height=main.h)",
                "edit = CompositeVideoClip([main, meme.with_position('center')])",
                'edit.write_videofile("edit.mp4", audio_codec="aac")',
                f"# Credit: {credit}",
            ]
        )
    if target == "markdown":
        return f"- {credit}"
    raise ValueError(target)


def relative(path: str, base: str | None) -> str:
    if not base:
        return Path(path).name
    try:
        return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()
