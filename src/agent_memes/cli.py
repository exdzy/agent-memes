"""`agent-memes` CLI. Every command prints exactly one JSON object on stdout.

Success: ``{"ok": true, "data": {...}}`` (exit 0)
Failure: ``{"ok": false, "error": {"code", "message", "hint"}}`` (exit != 0, see errors.EXIT_CODES)
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from . import __version__
from .errors import MemeError, invalid

EPILOG = """\
examples:
  agent-memes search "this is fine" --limit 5
  agent-memes suggest "when the deploy fails on friday"
  agent-memes fetch vlipsy:V1iupR0X --out ./assets/memes
  agent-memes preview vlipsy:V1iupR0X                 # contact sheet JPEG for vision models
  agent-memes convert vlipsy:V1iupR0X --preset vertical --caption-bottom "me in prod"
  agent-memes insert --into talk.mp4 --meme vlipsy:V1iupR0X --at 12.5 --mode cut
  agent-memes timeline edit.json --format otio fcpxml xmeml --out ./export
  agent-memes snippet vlipsy:V1iupR0X --for remotion --asset-dir public/memes
  agent-memes mcp                                      # MCP server on stdio

All output is JSON. Docs: https://github.com/exdzy/agent-memes
"""


def _emit(payload: dict, pretty: bool) -> None:
    sys.stdout.write(json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _kit():
    from .kit import MemeKit

    return MemeKit()


def _load_spec(value: str) -> dict:
    if value == "-":
        text = sys.stdin.read()
    elif value.lstrip().startswith("{"):
        text = value
    else:
        path = Path(value).expanduser()
        if not path.is_file():
            raise MemeError(f"Spec file not found: {value}", code="not_found")
        text = path.read_text(encoding="utf-8")
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        raise invalid(f"Timeline spec is not valid JSON: {exc}") from None
    if not isinstance(spec, dict):
        raise invalid("Timeline spec must be a JSON object.")
    if not value.lstrip().startswith("{") and value != "-":
        # relative clip paths are relative to the spec file
        base = Path(value).expanduser().resolve().parent
        for track in spec.get("tracks") or []:
            for clip in (track or {}).get("clips") or []:
                src = clip.get("src") if isinstance(clip, dict) else None
                if isinstance(src, str) and (src.startswith("./") or src.startswith("../")):
                    clip["src"] = str((base / src).resolve())
    return spec


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-memes",
        description="Meme video clips for AI agents: search, fetch, convert and drop into any editing workflow.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"agent-memes {__version__}")
    p.add_argument("--pretty", action="store_true", help="indent JSON output")
    sub = p.add_subparsers(dest="command", metavar="command")

    def add(name: str, help_: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS, help="indent JSON output")
        return sp

    safe = {"choices": ["high", "medium", "low", "off"], "help": "rating filter (default: medium = G/PG)"}

    sp = add("search", "Search meme clips.")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--offset", type=int, default=0)
    sp.add_argument("--safesearch", **safe)
    sp.add_argument("--source", choices=["auto", "vlipsy", "local", "all"], default="auto")

    sp = add("suggest", "Describe a moment in plain words; get ranked meme candidates.")
    sp.add_argument("context")
    sp.add_argument("--limit", type=int, default=5)
    sp.add_argument("--safesearch", **safe)
    sp.add_argument("--source", choices=["auto", "vlipsy", "local", "all"], default="auto")

    sp = add("trending", "Trending clips on Vlipsy.")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--offset", type=int, default=0)
    sp.add_argument("--safesearch", **safe)

    sp = add("playlists", "List Vlipsy playlists (curated collections like 'Hello', 'Lol').")
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--offset", type=int, default=0)

    sp = add("playlist", "Clips in one playlist.")
    sp.add_argument("id")
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--offset", type=int, default=0)
    sp.add_argument("--safesearch", **safe)

    sp = add("info", "Full metadata for one clip (ref, Vlipsy URL, or local path).")
    sp.add_argument("ref")
    sp.add_argument("--refresh", action="store_true", help="ignore cached metadata")

    sp = add(
        "fetch",
        "Download clip(s) to the cache, optionally copying into a project folder with a credit sidecar.",
    )
    sp.add_argument("refs", nargs="+")
    sp.add_argument("--out", help="copy into this folder (e.g. ./assets/memes)")
    sp.add_argument("--quality", choices=["hd", "sd"], default="hd")
    sp.add_argument(
        "--no-watermark",
        action="store_true",
        help="request the unwatermarked file (only if your Vlipsy plan/agreement allows it)",
    )
    sp.add_argument("--refresh", action="store_true")

    sp = add("preview", "Contact-sheet JPEG of a clip so a vision model can see it.")
    sp.add_argument("ref")
    sp.add_argument("--frames", type=int, default=6)
    sp.add_argument("--columns", type=int, default=3)
    sp.add_argument("--out")

    sp = add(
        "convert",
        "Transcode with an editing preset (edit, prores, webm, gif, vertical, square, audio, poster).",
    )
    sp.add_argument("src", help="meme ref or file path")
    sp.add_argument("--preset", default="edit")
    sp.add_argument("--out")
    sp.add_argument("--start", type=float)
    sp.add_argument("--end", type=float)
    sp.add_argument("--width", type=int)
    sp.add_argument("--height", type=int)
    sp.add_argument("--fps", type=float)
    sp.add_argument("--speed", type=float, help="0.25-4.0")
    sp.add_argument("--mute", action="store_true")
    sp.add_argument("--normalize-audio", action="store_true", help="EBU R128 loudness to -16 LUFS")
    sp.add_argument("--caption-top")
    sp.add_argument("--caption-bottom")
    sp.add_argument("--font", help="TTF/OTF for captions (default: Impact or a bold system font)")

    sp = add("insert", "Splice a meme into a video: cut (cutaway), overlay (full-frame), or pip (corner).")
    sp.add_argument("--into", required=True, help="main video file")
    sp.add_argument("--meme", required=True, help="meme ref or file path")
    sp.add_argument("--at", type=float, required=True, help="seconds into the main video")
    sp.add_argument("--mode", choices=["cut", "overlay", "pip"], default="cut")
    sp.add_argument("--out")
    sp.add_argument("--meme-start", type=float)
    sp.add_argument("--meme-end", type=float)
    sp.add_argument("--position", choices=["tl", "tr", "bl", "br", "center", "top", "bottom"], default="br")
    sp.add_argument("--scale", type=float, default=0.38, help="pip width as a fraction of the frame")
    sp.add_argument(
        "--duck", type=float, default=0.25, help="main audio volume while the meme plays (overlay/pip)"
    )
    sp.add_argument("--meme-volume", type=float, default=1.0)

    sp = add("timeline", "Build NLE timelines (OTIO, FCPXML, Premiere XML, EDL) from a JSON spec.")
    sp.add_argument("spec", nargs="?", help="spec file, inline JSON, or - for stdin")
    sp.add_argument(
        "--format",
        nargs="+",
        default=["otio", "fcpxml", "xmeml", "edl"],
        choices=["otio", "fcpxml", "xmeml", "edl", "json"],
    )
    sp.add_argument("--out", default=".")
    sp.add_argument("--name", help="output file stem")
    sp.add_argument("--media-dir", help="where meme refs are copied (default: <out>/media)")
    sp.add_argument("--conform", action="store_true", help="re-encode memes to the timeline fps/size")
    sp.add_argument("--example", action="store_true", help="print an example spec")

    sp = add("snippet", "Paste-ready code: ffmpeg, remotion, hyperframes, html, moviepy, markdown.")
    sp.add_argument("src")
    sp.add_argument(
        "--for",
        dest="target",
        required=True,
        choices=["ffmpeg", "remotion", "hyperframes", "html", "moviepy", "markdown"],
    )
    sp.add_argument("--at", type=float, default=0.0)
    sp.add_argument("--asset-dir", help="copy the clip here first (e.g. public/memes, assets/memes)")
    sp.add_argument("--project-root", help="paths in the snippet are relative to this (default: cwd)")

    sp = add("credits", "Collect attributions from *.meme.json sidecars (for video descriptions).")
    sp.add_argument("paths", nargs="*")
    sp.add_argument("--write", help="also write the credit text to this file")

    sp = add("doctor", "Check ffmpeg, fonts, API key and cache.")
    sp.add_argument("--online", action="store_true", help="also make one API request to verify the key")

    sp = add("auth", "Manage the Vlipsy API key in your user config (never in the project).")
    sp.add_argument("action", choices=["set", "status", "clear"])
    sp.add_argument("--key", help="API key (prefer the interactive prompt or VLIPSY_API_KEY)")

    sp = add("cache", "Inspect or clear the local cache.")
    sp.add_argument("action", choices=["info", "clear"])

    add("tools", "Print the MCP tool manifest (JSON Schemas) for agent frameworks.")
    sub.add_parser("mcp", help="Run the MCP server on stdio.")
    return p


def run(args: argparse.Namespace) -> dict:
    cmd = args.command
    if cmd == "tools":
        from .mcp_server import TOOLS

        return {"tools": TOOLS}
    if cmd == "auth":
        from .config import config_path, load_config, mask, update_config_file

        if args.action == "set":
            key = args.key or (
                getpass.getpass("Vlipsy API key: ") if sys.stdin.isatty() else sys.stdin.readline()
            )
            key = (key or "").strip()
            if not key:
                raise invalid("No key given.")
            path = update_config_file(vlipsy_api_key=key)
            return {"saved": True, "config_file": str(path), "api_key": mask(key)}
        if args.action == "clear":
            path = update_config_file(vlipsy_api_key=None)
            return {"cleared": True, "config_file": str(path)}
        cfg = load_config()
        return {
            "api_key": mask(cfg.vlipsy_api_key),
            "source": cfg.api_key_source,
            "config_file": str(config_path()),
        }
    if cmd == "timeline" and args.example:
        from .timeline import EXAMPLE_SPEC

        return {"example": EXAMPLE_SPEC}

    kit = _kit()
    if cmd == "search":
        return kit.search(
            args.query, limit=args.limit, offset=args.offset, safesearch=args.safesearch, source=args.source
        )
    if cmd == "suggest":
        return kit.suggest(args.context, limit=args.limit, safesearch=args.safesearch, source=args.source)
    if cmd == "trending":
        return kit.trending(limit=args.limit, offset=args.offset, safesearch=args.safesearch)
    if cmd == "playlists":
        return kit.playlists(limit=args.limit, offset=args.offset)
    if cmd == "playlist":
        return kit.playlist(args.id, limit=args.limit, offset=args.offset, safesearch=args.safesearch)
    if cmd == "info":
        return kit.info(args.ref, refresh=args.refresh)
    if cmd == "fetch":
        opts = {
            "out_dir": args.out,
            "quality": args.quality,
            "watermark": False if args.no_watermark else None,
            "refresh": args.refresh,
        }
        if len(args.refs) == 1:
            return kit.fetch(args.refs[0], **opts)
        return kit.fetch_many(args.refs, **opts)
    if cmd == "preview":
        return kit.preview(args.ref, frames=args.frames, columns=args.columns, out=args.out)
    if cmd == "convert":
        return kit.convert(
            args.src,
            preset=args.preset,
            out=args.out,
            start=args.start,
            end=args.end,
            width=args.width,
            height=args.height,
            fps=args.fps,
            speed=args.speed,
            mute=args.mute,
            normalize_audio=args.normalize_audio,
            caption_top=args.caption_top,
            caption_bottom=args.caption_bottom,
            font=args.font,
        )
    if cmd == "insert":
        return kit.insert(
            args.into,
            args.meme,
            at=args.at,
            mode=args.mode,
            out=args.out,
            meme_start=args.meme_start,
            meme_end=args.meme_end,
            position=args.position,
            scale=args.scale,
            duck=args.duck,
            meme_volume=args.meme_volume,
        )
    if cmd == "timeline":
        if not args.spec:
            raise invalid(
                "Pass a spec file, inline JSON, or - for stdin.", "See `agent-memes timeline --example`."
            )
        return kit.timeline(
            _load_spec(args.spec),
            formats=args.format,
            out_dir=args.out,
            name=args.name,
            media_dir=args.media_dir,
            conform=args.conform,
        )
    if cmd == "snippet":
        return kit.snippet(
            args.src, target=args.target, at=args.at, asset_dir=args.asset_dir, project_root=args.project_root
        )
    if cmd == "credits":
        return kit.credits(args.paths or None, write=args.write)
    if cmd == "doctor":
        return kit.doctor(online=args.online)
    if cmd == "cache":
        return kit.cache_info() if args.action == "info" else kit.cache_clear()
    raise invalid(f"Unknown command {cmd!r}.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pretty = getattr(args, "pretty", False)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "mcp":
        from .mcp_server import serve

        return serve()
    try:
        data = run(args)
    except MemeError as exc:
        _emit({"ok": False, "error": exc.to_dict()}, pretty)
        return exc.exit_code
    except KeyboardInterrupt:
        _emit({"ok": False, "error": {"code": "interrupted", "message": "Interrupted."}}, pretty)
        return 130
    except Exception as exc:  # last resort: agents still get JSON, never a bare traceback
        from .http import redact

        _emit(
            {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": redact(f"{type(exc).__name__}: {exc}"),
                    "hint": "Please report this at https://github.com/exdzy/agent-memes/issues",
                },
            },
            pretty,
        )
        return 1
    _emit({"ok": True, "data": data}, pretty)
    return 0
