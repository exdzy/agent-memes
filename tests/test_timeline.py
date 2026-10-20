import json
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest

from agent_memes import timeline as tl
from agent_memes.errors import MemeError


def fake_resolver(durations):
    def resolve(src):
        dur, fps, audio = durations[src]
        return (
            f"/media/{src}",
            {
                "duration": dur,
                "fps": fps,
                "width": 1920,
                "height": 1080,
                "has_video": True,
                "has_audio": audio,
                "sample_rate": 48000,
            },
            f"vlipsy:{src[:8]}",
            f"credit {src}",
        )

    return resolve


SPEC = {
    "name": "Test edit",
    "tracks": [
        {
            "name": "V1",
            "clips": [
                {"src": "main.mp4", "in": 0, "out": 5},
                {"src": "meme.mp4"},
                {"src": "main.mp4", "in": 5},
            ],
        },
        {"name": "V2", "clips": [{"src": "meme.mp4", "at": 11, "duration": 1}]},
    ],
}
MEDIA = {"main.mp4": (10.0, 30.0, True), "meme.mp4": (2.0, 23.976, False)}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (30, Fraction(30)),
        (29.97, Fraction(30000, 1001)),
        ("24000/1001", Fraction(24000, 1001)),
        (25.0, Fraction(25)),
    ],
)
def test_parse_rate(value, expected):
    assert tl.parse_rate(value) == expected


def test_build_places_clips_sequentially():
    t = tl.build_timeline(SPEC, fake_resolver(MEDIA))
    v1 = t.tracks[0].clips
    assert [(c.start, c.dur) for c in v1] == [(0, 150), (150, 60), (210, 150)]
    assert t.tracks[1].clips[0].start == 330
    assert t.duration == 360


def test_overlap_is_rejected():
    spec = {"tracks": [{"clips": [{"src": "main.mp4"}, {"src": "meme.mp4", "at": 1}]}]}
    with pytest.raises(MemeError):
        tl.build_timeline(spec, fake_resolver(MEDIA))


def test_otio_structure():
    t = tl.build_timeline(SPEC, fake_resolver(MEDIA))
    doc = json.loads(tl.to_otio(t))
    assert doc["OTIO_SCHEMA"] == "Timeline.1"
    tracks = doc["tracks"]["children"]
    assert [tr["kind"] for tr in tracks] == ["Video", "Video", "Audio"]
    v2 = tracks[1]["children"]
    assert v2[0]["OTIO_SCHEMA"] == "Gap.1" and v2[0]["source_range"]["duration"]["value"] == 330
    audio = tracks[2]["children"]  # meme has no audio -> gap where it sits
    assert [c["OTIO_SCHEMA"] for c in audio] == ["Clip.1", "Gap.1", "Clip.1"]


def test_fcpxml_connected_clip_offsets():
    t = tl.build_timeline(SPEC, fake_resolver(MEDIA))
    xml = tl.to_fcpxml(t)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>')
    root = ET.fromstring(xml.split("\n", 2)[2])
    spine = root.find("./library/event/project/sequence/spine")
    clips = list(spine)
    assert [c.get("offset") for c in clips] == ["0s", "5s", "7s"]
    lane = clips[2].find("asset-clip")
    # connected clip at 11s inside a parent whose source starts at 5s and that sits at 7s -> 5 + (11 - 7)
    assert lane.get("lane") == "1" and lane.get("offset") == "9s"


def test_xmeml_and_edl():
    t = tl.build_timeline(SPEC, fake_resolver(MEDIA))
    root = ET.fromstring(tl.to_xmeml(t).split("\n", 2)[2])
    items = root.findall(".//video/track/clipitem")
    assert [(i.findtext("start"), i.findtext("end")) for i in items] == [
        ("0", "150"),
        ("150", "210"),
        ("210", "360"),
        ("330", "360"),
    ]
    assert root.find(".//clipitem/file/pathurl").text == "file://localhost/media/main.mp4"
    edl = tl.to_edl(t)
    assert "001  AX       V     C        00:00:00:00 00:00:05:00 00:00:00:00 00:00:05:00" in edl
    assert "* FROM CLIP NAME: meme.mp4" in edl
