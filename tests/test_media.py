import pytest
from conftest import needs_ffmpeg

from agent_memes import media
from agent_memes.errors import MemeError

pytestmark = needs_ffmpeg


def test_probe(clips):
    info = media.probe(clips["main"])
    assert (info["width"], info["height"], info["fps"]) == (640, 360, 30.0)
    assert info["has_audio"] and abs(info["duration"] - 6) < 0.1
    assert media.probe(clips["meme"])["fps_rational"] == "24000/1001"
    assert media.probe(clips["silent"])["has_audio"] is False


@pytest.mark.parametrize(
    ("preset", "suffix", "check"),
    [
        ("edit", ".mp4", lambda i: i["video_codec"] == "h264" and i["sample_rate"] == 48000),
        ("webm", ".webm", lambda i: i["video_codec"] == "vp9"),
        ("gif", ".gif", lambda i: i["video_codec"] == "gif" and not i["has_audio"]),
        ("vertical", ".mp4", lambda i: (i["width"], i["height"]) == (1080, 1920)),
        ("square", ".mp4", lambda i: (i["width"], i["height"]) == (1080, 1080)),
        ("audio", ".wav", lambda i: i["audio_codec"] == "pcm_s16le" and not i["has_video"]),
        ("poster", ".jpg", lambda i: i["video_codec"] == "mjpeg"),
    ],
)
def test_convert_presets(clips, tmp_path, preset, suffix, check):
    out = media.convert(clips["meme"], tmp_path / f"x{suffix}", preset=preset)
    assert out["path"].endswith(suffix)
    assert check(out), out


def test_convert_appends_extension_and_trims(clips, tmp_path):
    out = media.convert(clips["main"], tmp_path / "trimmed", start=1, end=3, fps=24)
    assert out["path"].endswith("trimmed.mp4")
    assert abs(out["duration"] - 2) < 0.15 and out["fps"] == 24.0


def test_convert_captions_with_tricky_text(clips, tmp_path):
    font = media.find_font()
    if not font or not media.has_filter("drawtext"):
        pytest.skip("no caption font / drawtext")
    out = media.convert(
        clips["meme"],
        tmp_path / "cap: it's [x].mp4",
        caption_top="100% it's: [fine], ok?",
        caption_bottom="%{pts} \\ ; ' end",
    )
    assert out["width"] == 426


def test_contact_sheet(clips, tmp_path):
    sheet = media.contact_sheet(clips["main"], tmp_path / "sheet.jpg", frames=4, columns=2)
    info = media.probe(sheet["path"])
    assert info["video_codec"] == "mjpeg" and info["width"] > 320


@pytest.mark.parametrize("mode", ["cut", "overlay", "pip"])
def test_insert_modes(clips, tmp_path, mode):
    out = media.insert(clips["main"], clips["meme"], tmp_path / f"{mode}.mp4", at=2, mode=mode)
    main = media.probe(clips["main"])
    meme = media.probe(clips["meme"])
    assert (out["width"], out["height"]) == (640, 360) and out["has_audio"]
    expected = main["duration"] + meme["duration"] if mode == "cut" else main["duration"]
    assert abs(out["duration"] - expected) < 0.15


def test_insert_handles_missing_audio(clips, tmp_path):
    out = media.insert(clips["silent"], clips["meme"], tmp_path / "a.mp4", at=0.5, mode="cut", meme_end=1)
    assert out["has_audio"] and abs(out["duration"] - 2.5) < 0.15
    out = media.insert(clips["main"], clips["silent"], tmp_path / "b.mp4", at=1, mode="pip", position="tl")
    assert out["has_audio"]


def test_insert_rejects_bad_timestamp(clips, tmp_path):
    with pytest.raises(MemeError) as err:
        media.insert(clips["main"], clips["meme"], tmp_path / "x.mp4", at=99)
    assert err.value.code == "invalid_input"
