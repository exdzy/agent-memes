"""High-level facade used by the CLI, the MCP server and Python callers."""

from __future__ import annotations

import datetime as _dt
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__, media, snippets, suggest
from . import timeline as tlmod
from .config import Config, load_config, mask
from .errors import MemeError, invalid
from .http import HttpClient
from .models import Meme
from .providers import LocalProvider, Page, VlipsyProvider, parse_vlipsy_id

MAX_BATCH = 25  # keep downloads per call small: this is a picker, not a mirroring tool
SOURCES = ("auto", "vlipsy", "local", "all")
QUALITIES = ("hd", "sd")
WATERMARK_NOTE = (
    "Unwatermarked file requested. Only use it if your Vlipsy plan or API agreement allows it "
    "(see https://vlipsy.com/terms)."
)


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


class MemeKit:
    def __init__(self, config: Config | None = None, *, http: HttpClient | None = None) -> None:
        self.config = config or load_config()
        self.http = http or HttpClient(
            self.config.user_agent, min_interval=self.config.request_interval, timeout=self.config.timeout
        )
        self.vlipsy = VlipsyProvider(self.config, self.http)
        self.local = LocalProvider(self.config.local_dirs)

    # ------------------------------------------------------------------ helpers
    @property
    def cache_dir(self) -> Path:
        return self.config.cache_dir

    def _vlipsy_dir(self, vid: str) -> Path:
        return self.cache_dir / "vlipsy" / vid

    def _sources(self, source: str) -> list[str]:
        if source not in SOURCES:
            raise invalid(f"Unknown source {source!r}.", f"Choose one of: {', '.join(SOURCES)}")
        if source == "auto":
            if self.config.vlipsy_api_key:
                return ["vlipsy"]
            if self.config.local_dirs:
                return ["local"]
            self.vlipsy._key()  # raises missing_api_key with the full hint
        if source == "all":
            out = ["local"] if self.config.local_dirs else []
            return out + (["vlipsy"] if self.config.vlipsy_api_key else [])
        return [source]

    def _safesearch(self, level: str | None) -> str:
        level = (level or self.config.safesearch).lower()
        if level not in ("high", "medium", "low", "off"):
            raise invalid(
                f"Unknown safesearch level {level!r}.", "Use high (G), medium (G/PG), low (≤PG-13) or off."
            )
        return level

    # ------------------------------------------------------------------ discovery
    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        safesearch: str | None = None,
        source: str = "auto",
    ) -> dict:
        level = self._safesearch(safesearch)
        merged = Page(items=[], offset=offset, total=0)
        for name in self._sources(source):
            provider = self.vlipsy if name == "vlipsy" else self.local
            page = provider.search(query, limit=limit, offset=offset, safesearch=level)
            merged.items += page.items
            merged.total = (merged.total or 0) + (page.total or len(page.items))
        merged.items = merged.items[: max(1, limit)] if source != "all" else merged.items
        out = merged.to_dict()
        out.update(query=query, safesearch=level)
        return out

    def trending(self, *, limit: int = 10, offset: int = 0, safesearch: str | None = None) -> dict:
        level = self._safesearch(safesearch)
        out = self.vlipsy.trending(limit=limit, offset=offset, safesearch=level).to_dict()
        out["safesearch"] = level
        return out

    def playlists(self, *, limit: int = 25, offset: int = 0) -> dict:
        return self.vlipsy.playlists(limit=limit, offset=offset)

    def playlist(
        self, playlist_id: str, *, limit: int = 25, offset: int = 0, safesearch: str | None = None
    ) -> dict:
        level = self._safesearch(safesearch)
        out = self.vlipsy.playlist(playlist_id, limit=limit, offset=offset, safesearch=level).to_dict()
        out.update(playlist=playlist_id, safesearch=level)
        return out

    def suggest(
        self,
        context: str,
        *,
        limit: int = 5,
        safesearch: str | None = None,
        source: str = "auto",
        max_queries: int = 3,
    ) -> dict:
        """Run a few mood/keyword searches for a free-text moment and rank the merged results."""
        if not context.strip():
            raise invalid("Describe the moment, e.g. 'when the build finally passes after 3 hours'.")
        queries = suggest.candidate_queries(context, max_queries=max(1, min(max_queries, 5)))
        pages: list[list[dict]] = []
        for q in queries:
            try:
                pages.append(self.search(q, limit=8, safesearch=safesearch, source=source)["results"])
            except MemeError as exc:
                if exc.code in ("missing_api_key", "auth_failed"):
                    raise
                pages.append([])
        # round-robin across queries (most specific first) so the list stays diverse
        seen: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for rank in range(max((len(p) for p in pages), default=0)):
            for page in pages:
                if rank < len(page):
                    item = page[rank]
                    if item["ref"] not in seen:
                        seen[item["ref"]] = {"item": item, "queries": []}
                        order.append(item["ref"])
        for q, page in zip(queries, pages, strict=True):
            for item in page:
                seen[item["ref"]]["queries"].append(q)
        ranked = [seen[ref] for ref in order]
        results = [{**e["item"], "matched_queries": e["queries"]} for e in ranked[: max(1, limit)]]
        return {"context": context, "queries": queries, "results": results}

    def info(self, ref: str, *, refresh: bool = False) -> dict:
        return self._meme(ref, refresh=refresh).full()

    def _meme(self, ref: str, *, refresh: bool = False) -> Meme:
        ref = ref.strip()
        if ref.startswith("local:") or Path(ref).expanduser().is_file():
            return self.local.get(ref)
        vid = parse_vlipsy_id(ref)
        if not vid:
            raise invalid(
                f"{ref!r} is neither an existing file nor a meme ref.",
                "Use a ref from search results (e.g. 'vlipsy:V1iupR0X'), a vlipsy.com/vlip/... URL, or a file path.",
            )
        meta = self._vlipsy_dir(vid) / "meta.json"
        if meta.is_file() and not refresh:
            try:
                return Meme.from_full(json.loads(meta.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                pass
        meme = self.vlipsy.get(vid)
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps(meme.full(), indent=2), encoding="utf-8")
        return meme

    # ------------------------------------------------------------------ fetching
    def fetch(
        self,
        ref: str,
        *,
        out_dir: str | Path | None = None,
        quality: str = "hd",
        watermark: bool | None = None,
        refresh: bool = False,
    ) -> dict:
        if quality not in QUALITIES:
            raise invalid(f"Unknown quality {quality!r}.", "Use 'hd' (480p) or 'sd' (360p).")
        meme = self._meme(ref, refresh=refresh)
        watermark = self.config.watermark if watermark is None else watermark
        notes: list[str] = []

        if meme.provider == "local":
            path, cached, watermarked, nbytes = (
                Path(meme.local_path),
                True,
                None,
                Path(meme.local_path).stat().st_size,
            )
        else:
            variant = meme.variants.get(quality) or meme.variants.get("sd") or meme.variants.get("hd")
            if not variant:
                raise MemeError(f"{meme.ref} has no downloadable video.", code="not_found")
            url = variant.watermark_url if watermark else variant.url
            watermarked = bool(watermark)
            if not url:  # fall back to whatever rendition exists
                url = variant.url or variant.watermark_url
                watermarked = url == variant.watermark_url
            if not watermarked:
                notes.append(WATERMARK_NOTE)
            used_quality = quality if meme.variants.get(quality) else next(iter(meme.variants))
            path = self._vlipsy_dir(meme.id) / f"{used_quality}{'-wm' if watermarked else ''}.mp4"
            cached = path.is_file() and path.stat().st_size > 0 and not refresh
            nbytes = path.stat().st_size if cached else self.http.download(url, path)

        probe = None
        try:
            probe = media.probe(path)
        except MemeError as exc:
            if exc.code != "ffmpeg_missing":
                raise
            notes.append(
                "ffprobe not found: install ffmpeg to get duration/fps/size info and editing features."
            )

        final, sidecar = path, None
        if out_dir:
            out = Path(out_dir).expanduser()
            out.mkdir(parents=True, exist_ok=True)
            final = out / f"{meme.safe_name}{path.suffix}"
            if final.resolve() != path.resolve():
                shutil.copy2(path, final)
            sidecar = out / f"{meme.safe_name}.meme.json"
            sidecar.write_text(
                json.dumps(
                    {
                        "tool": f"agent-memes {__version__}",
                        "fetched_at": _now(),
                        "file": final.name,
                        "watermarked": watermarked,
                        "attribution": meme.attribution,
                        "meme": meme.full(),
                        "probe": probe,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        result = {
            "ref": meme.ref,
            "title": meme.title,
            "from": meme.source,
            "path": str(final.resolve()),
            "cache_path": str(path.resolve()),
            "sidecar": str(sidecar.resolve()) if sidecar else None,
            "cached": cached,
            "watermarked": watermarked,
            "bytes": nbytes,
            "attribution": meme.attribution,
            "page_url": meme.page_url,
            "media": probe,
        }
        if notes:
            result["notes"] = notes
        return result

    def fetch_many(self, refs: list[str], **kwargs) -> dict:
        if len(refs) > MAX_BATCH:
            raise invalid(
                f"At most {MAX_BATCH} clips per call.",
                "Pick the clips you need; bulk mirroring is not supported.",
            )
        results, errors = [], []
        for ref in refs:
            try:
                results.append(self.fetch(ref, **kwargs))
            except MemeError as exc:
                if exc.code in ("missing_api_key", "auth_failed"):
                    raise
                errors.append({"ref": ref, **exc.to_dict()})
        return {"results": results, "errors": errors}

    def resolve_media(self, src: str) -> tuple[str, dict, str | None, str | None]:
        """File path or meme ref -> (absolute path, probe, ref, attribution). Fetches refs on demand."""
        path = Path(src).expanduser()
        if path.is_file():
            ref, attribution = None, None
            sidecar = path.with_suffix(".meme.json")
            if sidecar.is_file():
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                    ref, attribution = data.get("meme", {}).get("ref"), data.get("attribution")
                except (OSError, ValueError):
                    pass
            return str(path.resolve()), media.probe(path), ref, attribution
        fetched = self.fetch(src)
        info = fetched["media"] or media.probe(fetched["path"])
        return fetched["path"], info, fetched["ref"], fetched["attribution"]

    # ------------------------------------------------------------------ previews
    def preview(self, ref: str, *, frames: int = 6, columns: int = 3, out: str | Path | None = None) -> dict:
        """Contact sheet (one JPEG with N frames) so a multimodal agent can *see* a clip before using it."""
        path, info, mref, attribution = self.resolve_media(ref)
        if out is None:
            base = (
                self._vlipsy_dir(mref.split(":", 1)[1])
                if mref and mref.startswith("vlipsy:")
                else Path(path).parent
            )
            out = base / f"{Path(path).stem}.contact-{frames}.jpg"
        sheet = media.contact_sheet(path, out, frames=frames, columns=columns)
        return {
            "ref": mref,
            "video": path,
            "contact_sheet": sheet["path"],
            "frames": sheet["frames"],
            "duration": info.get("duration"),
            "attribution": attribution,
        }

    # ------------------------------------------------------------------ editing
    def convert(self, src: str, *, preset: str = "edit", out: str | Path | None = None, **opts) -> dict:
        path, _info, ref, attribution = self.resolve_media(src)
        if preset not in media.PRESETS:
            raise invalid(f"Unknown preset {preset!r}.", f"Choose one of: {', '.join(media.PRESETS)}")
        if opts.get("font") is None:
            opts["font"] = self.config.font
        # friendly output names for memes; files keep their own stem (and never trigger an API call)
        stem = self._meme(ref).safe_name if ref and not Path(src).expanduser().is_file() else None
        result = media.convert(path, out, preset=preset, stem=stem, **opts)
        result.update(source=path, ref=ref, attribution=attribution)
        return result

    def insert(
        self, into: str, meme: str, *, at: float, mode: str = "cut", out: str | Path | None = None, **opts
    ) -> dict:
        main_path = Path(into).expanduser()
        if not main_path.is_file():
            raise MemeError(f"Main video not found: {into}", code="not_found")
        meme_path, _info, ref, attribution = self.resolve_media(meme)
        if out is None:
            out = main_path.with_name(f"{main_path.stem}.with-meme{main_path.suffix or '.mp4'}")
        result = media.insert(main_path, meme_path, out, at=at, mode=mode, **opts)
        result.update(main=str(main_path.resolve()), meme=meme_path, ref=ref, attribution=attribution)
        return result

    def timeline(
        self,
        spec: dict,
        *,
        formats: list[str] | None = None,
        out_dir: str | Path = ".",
        name: str | None = None,
        media_dir: str | Path | None = None,
        conform: bool = False,
    ) -> dict:
        """Write NLE timelines. Meme refs are copied into ``media_dir`` (default ``<out_dir>/media``)
        so the exported project does not point into the cache. ``conform`` re-encodes meme clips to the
        timeline's frame rate and frame size (letterboxed) so they drop in without NLE conforming."""
        formats = formats or ["otio", "fcpxml", "xmeml", "edl"]
        bad = [f for f in formats if f not in tlmod.FORMATS]
        if bad:
            raise invalid(f"Unknown format(s): {', '.join(bad)}", f"Choose from: {', '.join(tlmod.FORMATS)}")
        out = Path(out_dir).expanduser()
        media_root = Path(media_dir).expanduser() if media_dir else out / "media"

        def resolve(src: str):
            if Path(src).expanduser().is_file():
                return self.resolve_media(src)
            fetched = self.fetch(src, out_dir=media_root)
            return (
                fetched["path"],
                fetched["media"] or media.probe(fetched["path"]),
                fetched["ref"],
                fetched["attribution"],
            )

        tl = tlmod.build_timeline(spec, resolve)
        if conform:
            self._conform(tl, media_root)
        out.mkdir(parents=True, exist_ok=True)
        stem = (
            name
            or "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in tl.name).strip("-")
            or "timeline"
        )
        files = {}
        for fmt in formats:
            writer, ext = tlmod.WRITERS[fmt]
            target = out / f"{stem}{ext}"
            target.write_text(writer(tl), encoding="utf-8")
            files[fmt] = str(target.resolve())
        credits = sorted({c.attribution for t in tl.tracks for c in t.clips if c.attribution})
        return {
            "files": files,
            "timeline": tl.to_dict(),
            "credits": credits,
            "import_hints": {
                "otio": "DaVinci Resolve: File > Import > Timeline. Or convert with `otioconvert` to anything else.",
                "fcpxml": "Final Cut Pro: File > Import > XML. DaVinci Resolve also imports .fcpxml.",
                "xmeml": "Premiere Pro: File > Import (Final Cut Pro XML). Also Resolve / Kdenlive / Shotcut.",
                "edl": "Any NLE: import CMX3600 EDL (first track only), then relink media by clip name.",
            },
        }

    def _conform(self, tl: tlmod.Timeline, media_root: Path) -> None:
        rate = f"{tl.rate.numerator}/{tl.rate.denominator}"
        done: dict[str, dict] = {}
        for track in tl.tracks:
            for c in track.clips:
                if not c.ref or not c.has_video:
                    continue
                if (
                    c.fps
                    and abs(c.fps - float(tl.rate)) < 0.01
                    and (c.width, c.height) == (tl.width, tl.height)
                ):
                    continue
                if c.path not in done:
                    target = media_root / f"{Path(c.path).stem}.{tl.width}x{tl.height}@{float(tl.rate):g}.mp4"
                    done[c.path] = media.convert(
                        c.path, target, preset="edit", width=tl.width, height=tl.height, fps=rate
                    )
                info = done[c.path]
                c.path, c.fps, c.width, c.height = info["path"], info["fps"], info["width"], info["height"]
                c.sample_rate = info.get("sample_rate")
                c.media_frames = max(1, tl.frames(info["duration"] or 0))
                c.dur = min(c.dur, c.media_frames - c.src_in)

    def snippet(
        self,
        src: str,
        *,
        target: str,
        at: float = 0.0,
        asset_dir: str | Path | None = None,
        project_root: str | Path | None = None,
    ) -> dict:
        if target not in snippets.TARGETS:
            raise invalid(f"Unknown target {target!r}.", f"Choose one of: {', '.join(snippets.TARGETS)}")
        if asset_dir:
            fetched = self.fetch(src, out_dir=asset_dir) if not Path(src).expanduser().is_file() else None
            if fetched:
                path, info, attribution, name = (
                    fetched["path"],
                    fetched["media"] or {},
                    fetched["attribution"],
                    Path(fetched["path"]).stem,
                )
            else:
                dest = Path(asset_dir).expanduser()
                dest.mkdir(parents=True, exist_ok=True)
                target_file = dest / Path(src).name
                if Path(src).resolve() != target_file.resolve():
                    shutil.copy2(src, target_file)
                path, info, _ref, attribution = self.resolve_media(str(target_file))
                name = Path(path).stem
        else:
            path, info, _ref, attribution = self.resolve_media(src)
            name = Path(path).stem
        root = project_root or (Path.cwd() if asset_dir else None)
        rel = snippets.relative(path, str(root) if root else None)
        code = snippets.render(
            target,
            path=path,
            rel_path=rel,
            duration=info.get("duration"),
            at=at,
            attribution=attribution,
            has_audio=bool(info.get("has_audio")),
            name=name,
        )
        return {
            "target": target,
            "path": path,
            "relative_path": rel,
            "code": code,
            "attribution": attribution,
        }

    # ------------------------------------------------------------------ credits / housekeeping
    def credits(self, paths: list[str] | None = None, *, write: str | Path | None = None) -> dict:
        roots = [Path(p).expanduser() for p in (paths or ["."])]
        items, seen = [], set()
        for root in roots:
            files = [root] if root.is_file() else sorted(root.rglob("*.meme.json")) if root.is_dir() else []
            for f in files:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                meme = data.get("meme") or {}
                key = meme.get("ref") or str(f)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "ref": meme.get("ref"),
                        "title": meme.get("title"),
                        "from": meme.get("from"),
                        "page_url": meme.get("page_url"),
                        "attribution": data.get("attribution"),
                        "file": str(f.with_name(data.get("file") or f.name)),
                    }
                )
        text = "\n".join(["Meme clips used:"] + [f"- {i['attribution']}" for i in items]) if items else ""
        if write and text:
            Path(write).write_text(text + "\n", encoding="utf-8")
        return {
            "count": len(items),
            "items": items,
            "text": text,
            "written": str(write) if write and text else None,
        }

    def cache_info(self) -> dict:
        root = self.cache_dir
        files = [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else []
        return {"cache_dir": str(root), "files": len(files), "bytes": sum(p.stat().st_size for p in files)}

    def cache_clear(self) -> dict:
        info = self.cache_info()
        if self.cache_dir.is_dir():
            shutil.rmtree(self.cache_dir)
        return {"cleared": True, **info}

    def doctor(self, *, online: bool = False) -> dict:
        checks: dict[str, Any] = {
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        }
        for name, finder in (("ffmpeg", media.ffmpeg_bin), ("ffprobe", media.ffprobe_bin)):
            try:
                binary = finder()
                first = subprocess.run(
                    [binary, "-version"], capture_output=True, text=True, timeout=20
                ).stdout.splitlines()
                checks[name] = {"ok": True, "path": binary, "version": first[0] if first else None}
            except (MemeError, OSError, subprocess.TimeoutExpired) as exc:
                checks[name] = {"ok": False, "hint": getattr(exc, "hint", None) or media.FFMPEG_HINT}
        checks["captions"] = {
            "drawtext_filter": media.has_filter("drawtext") if checks["ffmpeg"]["ok"] else False,
            "font": media.find_font(self.config.font),
        }
        checks["vlipsy"] = {
            "api_key": mask(self.config.vlipsy_api_key),
            "source": self.config.api_key_source,
            "api_base": self.config.api_base,
        }
        if not self.config.vlipsy_api_key:
            checks["vlipsy"]["hint"] = (
                "No key: Vlipsy search is disabled. Set VLIPSY_API_KEY or use local dirs."
            )
        elif online:
            try:
                self.vlipsy.trending(limit=1)
                checks["vlipsy"]["reachable"] = True
            except MemeError as exc:
                checks["vlipsy"]["reachable"] = False
                checks["vlipsy"]["error"] = exc.to_dict()
        checks["local_dirs"] = [{"path": str(p), "exists": p.is_dir()} for p in self.config.local_dirs]
        checks["cache"] = self.cache_info()
        checks["config"] = self.config.to_public_dict()
        checks["ok"] = bool(
            checks["ffmpeg"]["ok"]
            and checks["ffprobe"]["ok"]
            and (self.config.vlipsy_api_key or self.config.local_dirs)
        )
        return checks
