"""Dependency-free MCP server (JSON-RPC 2.0 over stdio, newline-delimited).

Run with ``agent-memes mcp``. Implements initialize, ping, tools/list and tools/call.
"""

from __future__ import annotations

import base64
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from . import __version__
from .errors import MemeError
from .http import redact

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]

INSTRUCTIONS = """\
agent-memes finds meme / reaction video clips and drops them into editing workflows.
Typical flow: meme_suggest (describe the moment) or meme_search -> meme_preview (look at the contact
sheet before choosing) -> meme_fetch (out_dir = the project's asset folder) -> meme_insert / meme_convert
for a rendered result, or meme_timeline / meme_snippet for an NLE or code-based editor.
Refs look like 'vlipsy:V1iupR0X' or 'local:/abs/path.mp4'; file paths work anywhere a ref does.
Always keep the returned 'attribution' and put meme_credits output in the video description.
Downloads are watermarked by default. All paths returned are absolute."""

SAFE = {
    "type": "string",
    "enum": ["high", "medium", "low", "off"],
    "description": "Rating filter. high=G, medium=G/PG (default), low=up to PG-13, off=everything.",
}
SOURCE = {
    "type": "string",
    "enum": ["auto", "vlipsy", "local", "all"],
    "default": "auto",
    "description": "Where to search. auto = Vlipsy if a key is configured, else local folders.",
}
REF = {
    "type": "string",
    "description": "Meme ref ('vlipsy:ID', 'local:/path'), a vlipsy.com/vlip/... URL, or a file path.",
}

RO = {"readOnlyHint": True, "openWorldHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
LOCAL_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}


def _tool(
    name: str, description: str, props: dict, required: list[str] | None = None, annotations=None
) -> dict:
    schema: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "inputSchema": schema, "annotations": annotations or RO}


TOOLS = [
    _tool(
        "meme_search",
        "Search meme/reaction video clips by words or phrase (e.g. 'this is fine', 'mind blown'). "
        "Returns compact results with 'ref', title, source show/movie, duration, tags and a preview image URL.",
        {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "safesearch": SAFE,
            "source": SOURCE,
        },
        ["query"],
    ),
    _tool(
        "meme_suggest",
        "Describe a moment in plain language ('when the build finally passes', 'awkward silence "
        "after a bad joke'); runs a few mood/keyword searches and returns ranked candidates.",
        {
            "context": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "safesearch": SAFE,
            "source": SOURCE,
        },
        ["context"],
    ),
    _tool(
        "meme_trending",
        "Currently trending clips on Vlipsy.",
        {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "safesearch": SAFE,
        },
    ),
    _tool(
        "meme_playlists",
        "List curated Vlipsy playlists (e.g. 'Hello', 'Lol').",
        {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
        },
    ),
    _tool(
        "meme_playlist",
        "Clips in one Vlipsy playlist.",
        {
            "id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "safesearch": SAFE,
        },
        ["id"],
    ),
    _tool(
        "meme_info",
        "Full metadata for one clip: title, source, tags, rating, duration, renditions, attribution.",
        {"ref": REF},
        ["ref"],
    ),
    _tool(
        "meme_preview",
        "Render a contact sheet (one JPEG with N evenly spaced frames) and return it as an image "
        "so you can SEE the clip before using it. Fetches the clip if needed.",
        {
            "ref": REF,
            "frames": {"type": "integer", "minimum": 1, "maximum": 16, "default": 6},
            "columns": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3},
        },
        ["ref"],
        WRITE,
    ),
    _tool(
        "meme_fetch",
        "Download a clip (cached). With out_dir, copies it into that folder plus a "
        "<name>.meme.json credit sidecar. Returns the absolute path and probe info (duration, fps, size, audio).",
        {
            "ref": REF,
            "out_dir": {"type": "string", "description": "e.g. the project's assets/memes folder"},
            "quality": {"type": "string", "enum": ["hd", "sd"], "default": "hd"},
            "watermark": {
                "type": "boolean",
                "default": True,
                "description": "false only if the user's Vlipsy plan/agreement allows unwatermarked use",
            },
        },
        ["ref"],
        WRITE,
    ),
    _tool(
        "meme_convert",
        "Transcode a clip with an editing preset: edit (H.264 CFR MP4 for any NLE), prores (.mov), "
        "webm, gif, vertical (9:16 blurred fill), square, audio (WAV sound effect), poster (JPEG). Optional trim, "
        "resize, fps, speed, mute, loudness normalisation and classic top/bottom meme captions.",
        {
            "src": REF,
            "preset": {
                "type": "string",
                "enum": ["edit", "prores", "webm", "gif", "vertical", "square", "audio", "poster"],
                "default": "edit",
            },
            "out": {"type": "string", "description": "output file path"},
            "start": {"type": "number"},
            "end": {"type": "number"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "fps": {"type": "number"},
            "speed": {"type": "number"},
            "mute": {"type": "boolean"},
            "normalize_audio": {"type": "boolean"},
            "caption_top": {"type": "string"},
            "caption_bottom": {"type": "string"},
            "font": {"type": "string"},
        },
        ["src"],
        LOCAL_WRITE,
    ),
    _tool(
        "meme_insert",
        "Render a new video with a meme spliced into a main video at a timestamp. mode=cut: main "
        "pauses, meme plays full-frame, main resumes. mode=overlay: meme covers the picture while main audio "
        "continues ducked. mode=pip: meme in a corner. Output matches the main video's size and fps.",
        {
            "into": {"type": "string", "description": "main video file"},
            "meme": REF,
            "at": {"type": "number", "description": "seconds into the main video"},
            "mode": {"type": "string", "enum": ["cut", "overlay", "pip"], "default": "cut"},
            "out": {"type": "string"},
            "meme_start": {"type": "number"},
            "meme_end": {"type": "number"},
            "position": {
                "type": "string",
                "enum": ["tl", "tr", "bl", "br", "center", "top", "bottom"],
                "default": "br",
            },
            "scale": {"type": "number", "default": 0.38},
            "duck": {"type": "number", "default": 0.25},
            "meme_volume": {"type": "number", "default": 1.0},
        },
        ["into", "meme", "at"],
        LOCAL_WRITE,
    ),
    _tool(
        "meme_timeline",
        "Write NLE timeline files from a spec so a human can finish the edit in their editor: "
        "otio (OpenTimelineIO / Resolve), fcpxml (Final Cut Pro / Resolve), xmeml (Premiere Pro), edl, json. "
        "Spec: {name?, fps?, width?, height?, tracks:[{name?, clips:[{src, in?, out?, duration?, at?}]}]} (seconds). "
        "Clips without 'at' follow the previous clip on their track.",
        {
            "spec": {"type": "object"},
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["otio", "fcpxml", "xmeml", "edl", "json"]},
            },
            "out_dir": {"type": "string", "default": "."},
            "name": {"type": "string"},
            "media_dir": {
                "type": "string",
                "description": "where meme refs are copied (default <out_dir>/media)",
            },
            "conform": {
                "type": "boolean",
                "default": False,
                "description": "re-encode meme clips to the timeline fps/size so they drop in cleanly",
            },
        },
        ["spec"],
        LOCAL_WRITE,
    ),
    _tool(
        "meme_snippet",
        "Paste-ready integration code for a clip: ffmpeg, remotion, hyperframes, html, moviepy or a "
        "markdown credit line. With asset_dir the clip is copied there and the snippet uses a relative path.",
        {
            "src": REF,
            "target": {
                "type": "string",
                "enum": ["ffmpeg", "remotion", "hyperframes", "html", "moviepy", "markdown"],
            },
            "at": {"type": "number", "default": 0},
            "asset_dir": {"type": "string"},
            "project_root": {"type": "string"},
        },
        ["src", "target"],
        LOCAL_WRITE,
    ),
    _tool(
        "meme_credits",
        "Collect attribution lines from *.meme.json sidecars under the given folders "
        "(default: current directory) for the video description.",
        {"paths": {"type": "array", "items": {"type": "string"}}, "write": {"type": "string"}},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    ),
    _tool(
        "meme_doctor",
        "Diagnose setup: ffmpeg/ffprobe, caption font, API key presence (masked), cache.",
        {"online": {"type": "boolean", "default": False}},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    ),
]


def _call(kit, name: str, a: dict) -> tuple[Any, list[dict]]:
    """Returns (json result, extra MCP content blocks)."""
    if name == "meme_search":
        return kit.search(
            a["query"],
            limit=a.get("limit", 10),
            offset=a.get("offset", 0),
            safesearch=a.get("safesearch"),
            source=a.get("source", "auto"),
        ), []
    if name == "meme_suggest":
        return kit.suggest(
            a["context"],
            limit=a.get("limit", 5),
            safesearch=a.get("safesearch"),
            source=a.get("source", "auto"),
        ), []
    if name == "meme_trending":
        return kit.trending(
            limit=a.get("limit", 10), offset=a.get("offset", 0), safesearch=a.get("safesearch")
        ), []
    if name == "meme_playlists":
        return kit.playlists(limit=a.get("limit", 25), offset=a.get("offset", 0)), []
    if name == "meme_playlist":
        return kit.playlist(
            a["id"], limit=a.get("limit", 25), offset=a.get("offset", 0), safesearch=a.get("safesearch")
        ), []
    if name == "meme_info":
        return kit.info(a["ref"]), []
    if name == "meme_preview":
        result = kit.preview(a["ref"], frames=a.get("frames", 6), columns=a.get("columns", 3))
        data = base64.b64encode(Path(result["contact_sheet"]).read_bytes()).decode("ascii")
        return result, [{"type": "image", "data": data, "mimeType": "image/jpeg"}]
    if name == "meme_fetch":
        return kit.fetch(
            a["ref"], out_dir=a.get("out_dir"), quality=a.get("quality", "hd"), watermark=a.get("watermark")
        ), []
    if name == "meme_convert":
        opts = {
            k: a.get(k)
            for k in (
                "start",
                "end",
                "width",
                "height",
                "fps",
                "speed",
                "caption_top",
                "caption_bottom",
                "font",
            )
        }
        opts.update(mute=bool(a.get("mute")), normalize_audio=bool(a.get("normalize_audio")))
        return kit.convert(a["src"], preset=a.get("preset", "edit"), out=a.get("out"), **opts), []
    if name == "meme_insert":
        opts = {
            k: a[k] for k in ("meme_start", "meme_end", "position", "scale", "duck", "meme_volume") if k in a
        }
        return kit.insert(
            a["into"], a["meme"], at=float(a["at"]), mode=a.get("mode", "cut"), out=a.get("out"), **opts
        ), []
    if name == "meme_timeline":
        return kit.timeline(
            a["spec"],
            formats=a.get("formats"),
            out_dir=a.get("out_dir", "."),
            name=a.get("name"),
            media_dir=a.get("media_dir"),
            conform=bool(a.get("conform")),
        ), []
    if name == "meme_snippet":
        return kit.snippet(
            a["src"],
            target=a["target"],
            at=a.get("at", 0.0),
            asset_dir=a.get("asset_dir"),
            project_root=a.get("project_root"),
        ), []
    if name == "meme_credits":
        return kit.credits(a.get("paths"), write=a.get("write")), []
    if name == "meme_doctor":
        return kit.doctor(online=bool(a.get("online"))), []
    raise KeyError(name)


class Server:
    def __init__(self) -> None:
        self._kit = None
        self.protocol = SUPPORTED_VERSIONS[0]

    @property
    def kit(self):
        if self._kit is None:
            from .kit import MemeKit

            self._kit = MemeKit()
        return self._kit

    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method")
        mid = msg.get("id")
        is_request = "id" in msg
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                self.protocol = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
                result = {
                    "protocolVersion": self.protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "agent-memes", "title": "agent-memes", "version": __version__},
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self.call_tool(params.get("name"), params.get("arguments") or {})
            elif method and method.startswith("notifications/"):
                return None
            else:
                if not is_request:
                    return None
                return {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
        except Exception as exc:  # protocol-level failure
            traceback.print_exc(file=sys.stderr)
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": redact(str(exc))}}
        return {"jsonrpc": "2.0", "id": mid, "result": result} if is_request else None

    def call_tool(self, name: str | None, arguments: dict) -> dict:
        if name not in {t["name"] for t in TOOLS}:
            return self._tool_error({"code": "unknown_tool", "message": f"Unknown tool: {name}"})
        try:
            data, extra = _call(self.kit, name, arguments)
        except MemeError as exc:
            return self._tool_error(exc.to_dict())
        except KeyError as exc:
            return self._tool_error({"code": "invalid_input", "message": f"Missing argument: {exc}"})
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return self._tool_error(
                {"code": "internal_error", "message": redact(f"{type(exc).__name__}: {exc}")}
            )
        result: dict[str, Any] = {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}, *extra],
            "isError": False,
        }
        if self.protocol >= "2025-06-18" and isinstance(data, dict):
            result["structuredContent"] = data
        return result

    @staticmethod
    def _tool_error(error: dict) -> dict:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": error}, ensure_ascii=False)}],
            "isError": True,
        }


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    server = Server()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply: Any = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if isinstance(msg, list):
                replies = [r for r in (server.handle(m) for m in msg if isinstance(m, dict)) if r]
                reply = replies or None
            elif isinstance(msg, dict):
                reply = server.handle(msg)
            else:
                reply = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
