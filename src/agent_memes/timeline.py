"""Timeline spec -> NLE interchange files (OTIO, FCPXML, Premiere/FCP7 XML, CMX3600 EDL).

Spec (JSON)::

    {
      "name": "Reaction edit",
      "fps": 30,                       # optional: defaults to the first video clip's rate
      "width": 1920, "height": 1080,   # optional: defaults to the first video clip's size
      "tracks": [
        {"name": "V1", "clips": [
          {"src": "./main.mp4", "in": 0, "out": 12.5},
          {"src": "vlipsy:V1iupR0X"},                  # placed right after the previous clip
          {"src": "./main.mp4", "in": 12.5}
        ]},
        {"name": "V2", "clips": [{"src": "vlipsy:8WTyZTC5", "at": 30, "duration": 3}]}
      ]
    }

All times are seconds. ``src`` may be a file path or any meme ref (fetched automatically).
"""

from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .errors import invalid

FORMATS = ("otio", "fcpxml", "xmeml", "edl", "json")
_NTSC = {
    23.976: Fraction(24000, 1001),
    29.97: Fraction(30000, 1001),
    47.952: Fraction(48000, 1001),
    59.94: Fraction(60000, 1001),
    119.88: Fraction(120000, 1001),
}


def parse_rate(value) -> Fraction:
    if value is None:
        return Fraction(30)
    if isinstance(value, str) and "/" in value:
        rate = Fraction(value)
    else:
        f = float(value)
        rate = next((r for k, r in _NTSC.items() if abs(f - k) < 0.01), None) or Fraction(round(f))
    if rate <= 0 or rate > 240:
        raise invalid(f"Unsupported frame rate {value!r}.")
    return rate


@dataclass
class TLClip:
    name: str
    path: str
    ref: str | None
    start: int  # timeline start (frames)
    src_in: int  # source in (frames)
    dur: int  # frames
    media_frames: int
    width: int | None
    height: int | None
    fps: float | None
    has_video: bool
    has_audio: bool
    attribution: str | None = None
    sample_rate: int | None = None

    @property
    def end(self) -> int:
        return self.start + self.dur


@dataclass
class TLTrack:
    name: str
    clips: list[TLClip] = field(default_factory=list)


@dataclass
class Timeline:
    name: str
    rate: Fraction
    width: int
    height: int
    tracks: list[TLTrack]

    @property
    def duration(self) -> int:
        return max((c.end for t in self.tracks for c in t.clips), default=0)

    def frames(self, seconds: float) -> int:
        return int(round(Fraction(seconds).limit_denominator(100000) * self.rate))

    def to_dict(self) -> dict:
        sec = lambda f: round(float(Fraction(f) / self.rate), 4)  # noqa: E731
        return {
            "name": self.name,
            "fps": float(self.rate),
            "fps_rational": f"{self.rate.numerator}/{self.rate.denominator}",
            "width": self.width,
            "height": self.height,
            "duration": sec(self.duration),
            "tracks": [
                {
                    "name": t.name,
                    "clips": [
                        {
                            "name": c.name,
                            "ref": c.ref,
                            "path": c.path,
                            "at": sec(c.start),
                            "in": sec(c.src_in),
                            "duration": sec(c.dur),
                            "has_audio": c.has_audio,
                            "attribution": c.attribution,
                        }
                        for c in t.clips
                    ],
                }
                for t in self.tracks
            ],
        }


Resolver = Callable[[str], tuple[str, dict, str | None, str | None]]
"""src -> (absolute path, probe dict, meme ref or None, attribution or None)"""


def build_timeline(spec: dict, resolve: Resolver) -> Timeline:
    if not isinstance(spec, dict) or not isinstance(spec.get("tracks"), list) or not spec["tracks"]:
        raise invalid(
            "Timeline spec needs a non-empty 'tracks' list.", "See `agent-memes timeline --example`."
        )

    resolved: list[list[tuple[dict, tuple]]] = []
    first_video = None
    for t_index, track in enumerate(spec["tracks"]):
        clips = track.get("clips") if isinstance(track, dict) else None
        if not isinstance(clips, list):
            raise invalid(f"Track {t_index} needs a 'clips' list.")
        row = []
        for c in clips:
            if not isinstance(c, dict) or not c.get("src"):
                raise invalid(f"Every clip needs a 'src' (track {t_index}).")
            r = resolve(str(c["src"]))
            if first_video is None and r[1].get("has_video"):
                first_video = r[1]
            row.append((c, r))
        resolved.append(row)

    rate = parse_rate(spec.get("fps") or (first_video or {}).get("fps"))
    width = int(spec.get("width") or (first_video or {}).get("width") or 1920)
    height = int(spec.get("height") or (first_video or {}).get("height") or 1080)
    tl = Timeline(
        name=str(spec.get("name") or "agent-memes timeline"), rate=rate, width=width, height=height, tracks=[]
    )

    for t_index, (track, row) in enumerate(zip(spec["tracks"], resolved, strict=True)):
        out = TLTrack(name=str(track.get("name") or f"V{t_index + 1}"))
        cursor = 0
        for c, (path, info, ref, attribution) in row:
            media_dur = info.get("duration") or 0
            media_frames = max(1, tl.frames(media_dur))
            src_in = tl.frames(float(c.get("in") or 0))
            if "out" in c and c["out"] is not None:
                dur = tl.frames(float(c["out"])) - src_in
            elif c.get("duration") is not None:
                dur = tl.frames(float(c["duration"]))
            else:
                dur = media_frames - src_in
            dur = min(dur, media_frames - src_in)
            if dur <= 0:
                raise invalid(f"Clip {c['src']!r} has an empty in/out range.")
            start = tl.frames(float(c["at"])) if c.get("at") is not None else cursor
            if start < cursor:
                raise invalid(
                    f"Clip {c['src']!r} overlaps the previous clip on track {out.name}.",
                    "Move it with 'at' or put it on another track.",
                )
            out.clips.append(
                TLClip(
                    name=str(c.get("name") or Path(path).name),
                    path=path,
                    ref=ref,
                    start=start,
                    src_in=src_in,
                    dur=dur,
                    media_frames=media_frames,
                    width=info.get("width"),
                    height=info.get("height"),
                    fps=info.get("fps"),
                    has_video=bool(info.get("has_video", True)),
                    has_audio=bool(info.get("has_audio")),
                    attribution=attribution,
                    sample_rate=info.get("sample_rate"),
                )
            )
            cursor = start + dur
        tl.tracks.append(out)
    return tl


# --------------------------------------------------------------------------- OTIO
def _rt(frames: int, rate: Fraction) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(rate), "value": float(frames)}


def _tr(start: int, dur: int, rate: Fraction) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "duration": _rt(dur, rate), "start_time": _rt(start, rate)}


def to_otio(tl: Timeline) -> str:
    def gap(frames: int) -> dict:
        return {
            "OTIO_SCHEMA": "Gap.1",
            "effects": [],
            "markers": [],
            "metadata": {},
            "name": "",
            "source_range": _tr(0, frames, tl.rate),
        }

    def clip(c: TLClip) -> dict:
        return {
            "OTIO_SCHEMA": "Clip.1",
            "effects": [],
            "markers": [],
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "available_range": _tr(0, c.media_frames, tl.rate),
                "metadata": {},
                "name": Path(c.path).name,
                "target_url": Path(c.path).as_uri(),
            },
            "metadata": {"agent_memes": {"ref": c.ref, "attribution": c.attribution}},
            "name": c.name,
            "source_range": _tr(c.src_in, c.dur, tl.rate),
        }

    def track(name: str, kind: str, clips: list[TLClip]) -> dict:
        children, cursor = [], 0
        for c in clips:
            if c.start > cursor:
                children.append(gap(c.start - cursor))
            children.append(clip(c))
            cursor = c.end
        return {
            "OTIO_SCHEMA": "Track.1",
            "children": children,
            "effects": [],
            "kind": kind,
            "markers": [],
            "metadata": {},
            "name": name,
            "source_range": None,
        }

    video = [track(t.name, "Video", [c for c in t.clips if c.has_video]) for t in tl.tracks]
    audio = [
        track(f"A{i + 1}", "Audio", [c for c in t.clips if c.has_audio])
        for i, t in enumerate(tl.tracks)
        if any(c.has_audio for c in t.clips)
    ]
    doc = {
        "OTIO_SCHEMA": "Timeline.1",
        "global_start_time": None,
        "metadata": {"agent_memes": {"width": tl.width, "height": tl.height, "generator": "agent-memes"}},
        "name": tl.name,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "children": video + audio,
            "effects": [],
            "markers": [],
            "metadata": {},
            "name": "tracks",
            "source_range": None,
        },
    }
    return json.dumps(doc, indent=2)


# --------------------------------------------------------------------------- FCPXML (Final Cut Pro, Resolve)
def _t(frames: int, rate: Fraction) -> str:
    value = Fraction(frames) / rate
    return f"{value.numerator}s" if value.denominator == 1 else f"{value.numerator}/{value.denominator}s"


def to_fcpxml(tl: Timeline) -> str:
    rate = tl.rate
    frame_dur = f"{rate.denominator}/{rate.numerator}s"
    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name="agent-memes-sequence",
        frameDuration=frame_dur,
        width=str(tl.width),
        height=str(tl.height),
    )
    ids = iter(f"r{i}" for i in range(2, 100000))
    formats: dict[tuple, str] = {}
    assets: dict[str, str] = {}
    for t in tl.tracks:
        for c in t.clips:
            if c.path in assets:
                continue
            fmt_key = (c.width, c.height, c.fps)
            if fmt_key not in formats:
                fid = next(ids)
                formats[fmt_key] = fid
                attrs = {"id": fid, "name": f"agent-memes-{c.width}x{c.height}"}
                if c.fps:
                    clip_rate = parse_rate(c.fps)
                    attrs["frameDuration"] = f"{clip_rate.denominator}/{clip_rate.numerator}s"
                if c.width and c.height:
                    attrs.update(width=str(c.width), height=str(c.height))
                ET.SubElement(resources, "format", **attrs)
            aid = next(ids)
            assets[c.path] = aid
            attrs = {
                "id": aid,
                "name": Path(c.path).stem,
                "start": "0s",
                "duration": _t(c.media_frames, rate),
                "hasVideo": "1" if c.has_video else "0",
                "format": formats[fmt_key],
            }
            if c.has_audio:
                attrs.update(
                    hasAudio="1", audioSources="1", audioChannels="2", audioRate=str(c.sample_rate or 48000)
                )
            asset = ET.SubElement(resources, "asset", **attrs)
            ET.SubElement(asset, "media-rep", kind="original-media", src=Path(c.path).as_uri())

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="agent-memes")
    project = ET.SubElement(event, "project", name=tl.name)
    total = tl.duration
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=_t(total, rate),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")

    def clip_el(parent, c: TLClip, offset: int, lane: int | None = None):
        attrs = {
            "ref": assets[c.path],
            "offset": _t(offset, rate),
            "name": c.name,
            "start": _t(c.src_in, rate),
            "duration": _t(c.dur, rate),
            "tcFormat": "NDF",
        }
        if lane:
            attrs["lane"] = str(lane)
        if c.has_audio:
            attrs["audioRole"] = "dialogue"
        return ET.SubElement(parent, "asset-clip", **attrs)

    # primary storyline = first track; gaps fill the holes and host connected clips
    spine_items: list[tuple[ET.Element, int, int, int]] = []  # (element, offset, duration, local start)
    cursor = 0
    for c in tl.tracks[0].clips:
        if c.start > cursor:
            g = ET.SubElement(
                spine,
                "gap",
                name="Gap",
                offset=_t(cursor, rate),
                start="0s",
                duration=_t(c.start - cursor, rate),
            )
            spine_items.append((g, cursor, c.start - cursor, 0))
        spine_items.append((clip_el(spine, c, c.start), c.start, c.dur, c.src_in))
        cursor = c.end
    if cursor < total:
        g = ET.SubElement(
            spine, "gap", name="Gap", offset=_t(cursor, rate), start="0s", duration=_t(total - cursor, rate)
        )
        spine_items.append((g, cursor, total - cursor, 0))

    for lane, t in enumerate(tl.tracks[1:], start=1):
        for c in t.clips:
            parent = next((it for it in spine_items if it[1] <= c.start < it[1] + it[2]), spine_items[-1])
            el, p_offset, _p_dur, p_start = parent
            clip_el(el, c, p_start + (c.start - p_offset), lane=lane)

    ET.indent(root, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


# --------------------------------------------------------------------------- xmeml (Premiere Pro, FCP7, Resolve)
def _rate_el(parent, rate: Fraction):
    r = ET.SubElement(parent, "rate")
    ET.SubElement(r, "timebase").text = str(round(float(rate)))
    ET.SubElement(r, "ntsc").text = "TRUE" if rate.denominator == 1001 else "FALSE"
    return r


def to_xmeml(tl: Timeline) -> str:
    root = ET.Element("xmeml", version="4")
    seq = ET.SubElement(root, "sequence", id="sequence-1")
    ET.SubElement(seq, "name").text = tl.name
    ET.SubElement(seq, "duration").text = str(tl.duration)
    _rate_el(seq, tl.rate)
    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    fmt = ET.SubElement(video, "format")
    sc = ET.SubElement(fmt, "samplecharacteristics")
    _rate_el(sc, tl.rate)
    ET.SubElement(sc, "width").text = str(tl.width)
    ET.SubElement(sc, "height").text = str(tl.height)
    ET.SubElement(sc, "pixelaspectratio").text = "square"
    audio = ET.SubElement(media, "audio")
    ET.SubElement(audio, "numOutputChannels").text = "2"

    file_ids: dict[str, str] = {}
    counter = iter(range(1, 1000000))

    def file_el(parent, c: TLClip):
        if c.path in file_ids:
            ET.SubElement(parent, "file", id=file_ids[c.path])
            return
        fid = f"file-{len(file_ids) + 1}"
        file_ids[c.path] = fid
        f = ET.SubElement(parent, "file", id=fid)
        ET.SubElement(f, "name").text = Path(c.path).name
        ET.SubElement(f, "pathurl").text = "file://localhost" + urllib.parse.quote(Path(c.path).as_posix())
        _rate_el(f, tl.rate)
        ET.SubElement(f, "duration").text = str(c.media_frames)
        m = ET.SubElement(f, "media")
        if c.has_video:
            v = ET.SubElement(ET.SubElement(m, "video"), "samplecharacteristics")
            ET.SubElement(v, "width").text = str(c.width or tl.width)
            ET.SubElement(v, "height").text = str(c.height or tl.height)
        if c.has_audio:
            a = ET.SubElement(m, "audio")
            asc = ET.SubElement(a, "samplecharacteristics")
            ET.SubElement(asc, "depth").text = "16"
            ET.SubElement(asc, "samplerate").text = str(c.sample_rate or 48000)
            ET.SubElement(a, "channelcount").text = "2"

    def clipitem(track_el, c: TLClip, kind: str):
        item = ET.SubElement(track_el, "clipitem", id=f"clipitem-{next(counter)}")
        ET.SubElement(item, "name").text = c.name
        ET.SubElement(item, "enabled").text = "TRUE"
        ET.SubElement(item, "duration").text = str(c.media_frames)
        _rate_el(item, tl.rate)
        ET.SubElement(item, "start").text = str(c.start)
        ET.SubElement(item, "end").text = str(c.end)
        ET.SubElement(item, "in").text = str(c.src_in)
        ET.SubElement(item, "out").text = str(c.src_in + c.dur)
        file_el(item, c)
        if kind == "audio":
            st = ET.SubElement(item, "sourcetrack")
            ET.SubElement(st, "mediatype").text = "audio"
            ET.SubElement(st, "trackindex").text = "1"

    for t in tl.tracks:
        vt = ET.SubElement(video, "track")
        for c in t.clips:
            if c.has_video:
                clipitem(vt, c, "video")
    for t in tl.tracks:
        if any(c.has_audio for c in t.clips):
            at = ET.SubElement(audio, "track")
            for c in t.clips:
                if c.has_audio:
                    clipitem(at, c, "audio")

    ET.indent(root, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


# --------------------------------------------------------------------------- CMX3600 EDL
def _tc(frames: int, base: int) -> str:
    ff = frames % base
    s = frames // base
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{ff:02d}"


def to_edl(tl: Timeline) -> str:
    base = round(float(tl.rate))
    lines = [f"TITLE: {tl.name[:60]}", "FCM: NON-DROP FRAME", ""]
    for n, c in enumerate(tl.tracks[0].clips, start=1):
        lines.append(
            f"{n:03d}  AX       V     C        "
            f"{_tc(c.src_in, base)} {_tc(c.src_in + c.dur, base)} {_tc(c.start, base)} {_tc(c.end, base)}"
        )
        lines.append(f"* FROM CLIP NAME: {Path(c.path).name}")
        lines.append(f"* SOURCE FILE: {c.path}")
        lines.append("")
    if len(tl.tracks) > 1:
        lines.append("* NOTE: EDL holds a single video track; only the first track was exported.")
    return "\n".join(lines) + "\n"


WRITERS = {
    "otio": (to_otio, ".otio"),
    "fcpxml": (to_fcpxml, ".fcpxml"),
    "xmeml": (to_xmeml, ".xml"),
    "edl": (to_edl, ".edl"),
    "json": (lambda tl: json.dumps(tl.to_dict(), indent=2), ".timeline.json"),
}

EXAMPLE_SPEC = {
    "name": "Reaction edit",
    "tracks": [
        {
            "name": "V1",
            "clips": [
                {"src": "./main.mp4", "in": 0, "out": 12.5},
                {"src": "vlipsy:V1iupR0X"},
                {"src": "./main.mp4", "in": 12.5},
            ],
        },
        {"name": "V2", "clips": [{"src": "vlipsy:8WTyZTC5", "at": 30, "duration": 3}]},
    ],
}
