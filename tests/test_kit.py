import json
from pathlib import Path

import pytest
from conftest import needs_ffmpeg

from agent_memes import suggest
from agent_memes.errors import MemeError


@needs_ffmpeg
def test_fetch_defaults_to_watermark_and_writes_sidecar(make_kit, clips, tmp_path):
    kit, http = make_kit(media_file=clips["meme"])
    out = kit.fetch("vlipsy:V1iupR0X", out_dir=tmp_path / "assets")
    assert http.downloads == ["https://media.vlipsy.com/vlips/V1iupR0X/480p-watermark.mp4"]
    assert out["watermarked"] is True and out["cached"] is False
    assert Path(out["path"]).name == "the-it-crowd-this-is-fine-V1iupR0X.mp4"
    assert out["media"]["has_audio"] is True and out["media"]["duration"] > 1
    sidecar = json.loads(Path(out["sidecar"]).read_text())
    assert sidecar["meme"]["ref"] == "vlipsy:V1iupR0X"
    assert "via Vlipsy" in sidecar["attribution"]

    again = kit.fetch("https://vlipsy.com/vlip/the-it-crowd-this-is-fine-V1iupR0X")
    assert again["cached"] is True and len(http.downloads) == 1
    # metadata is cached too: only the first fetch hit the API
    assert sum(1 for url, _ in http.calls if url.endswith("/V1iupR0X")) == 1


@needs_ffmpeg
def test_fetch_unwatermarked_adds_note(make_kit, clips):
    kit, http = make_kit(media_file=clips["meme"])
    out = kit.fetch("V1iupR0X", watermark=False, quality="sd")
    assert http.downloads[-1].endswith("/360p.mp4")
    assert out["watermarked"] is False
    assert any("Vlipsy" in n for n in out["notes"])


def test_fetch_many_is_capped(make_kit):
    kit, _ = make_kit()
    with pytest.raises(MemeError) as err:
        kit.fetch_many([f"vlipsy:AAAAAAA{i % 10}" for i in range(30)])
    assert err.value.code == "invalid_input"


@needs_ffmpeg
def test_credits_collects_sidecars(make_kit, clips, tmp_path):
    kit, _ = make_kit(media_file=clips["meme"])
    kit.fetch("vlipsy:V1iupR0X", out_dir=tmp_path / "a")
    kit.fetch("vlipsy:8WTyZTC5", out_dir=tmp_path / "a")
    credits = kit.credits([str(tmp_path)], write=tmp_path / "CREDITS.md")
    assert credits["count"] == 2
    assert "The IT Crowd" in (tmp_path / "CREDITS.md").read_text()


@needs_ffmpeg
def test_local_provider_search_and_auto_source(make_kit, clips, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "deal_with_it.mp4").write_bytes(clips["meme"].read_bytes())
    (lib / "deal_with_it.json").write_text(
        json.dumps({"title": "Deal with it", "tags": ["cool", "sunglasses"]})
    )
    (lib / "facepalm.mp4").write_bytes(clips["silent"].read_bytes())
    kit, http = make_kit(vlipsy_api_key=None, local_dirs=[lib])
    kit.config.vlipsy_api_key = None
    res = kit.search("sunglasses")
    assert res["results"][0]["title"] == "Deal with it"
    assert res["results"][0]["ref"].startswith("local:")
    assert http.calls == []  # never touched the network
    info = kit.fetch(res["results"][0]["ref"])
    assert info["path"].endswith("deal_with_it.mp4")


def test_suggest_queries():
    qs = suggest.candidate_queries("when the deploy fails on friday")
    assert qs[0] == "this is fine"
    assert "fail" in qs
    assert suggest.candidate_queries("mind blown")[0] == "mind blown"


def test_suggest_round_robin(make_kit):
    kit, http = make_kit()
    out = kit.suggest("this is fine", limit=2)
    assert out["queries"][0] == "this is fine"
    assert [r["ref"] for r in out["results"]] == ["vlipsy:V1iupR0X", "vlipsy:8WTyZTC5"]


def test_unknown_ref_is_invalid(make_kit):
    kit, _ = make_kit()
    with pytest.raises(MemeError) as err:
        kit.info("definitely not a ref!")
    assert err.value.code == "invalid_input"


@needs_ffmpeg
def test_convert_file_with_foreign_sidecar_needs_no_api(make_kit, clips, tmp_path):
    clip = tmp_path / "x.mp4"
    clip.write_bytes(clips["meme"].read_bytes())
    (tmp_path / "x.meme.json").write_text(
        json.dumps({"meme": {"ref": "vlipsy:ZZZZZZZZ"}, "attribution": "credit"})
    )
    kit, http = make_kit()
    out = kit.convert(str(clip), preset="poster", out=str(tmp_path) + "/")
    assert out["path"].endswith("x.poster.jpg") and out["attribution"] == "credit"
    assert http.calls == []


@needs_ffmpeg
def test_local_fetch_into_project_keeps_file_stem(make_kit, clips, tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "facepalm.mp4").write_bytes(clips["silent"].read_bytes())
    kit, _ = make_kit(local_dirs=[lib])
    out = kit.fetch(f"local:{lib / 'facepalm.mp4'}", out_dir=tmp_path / "assets")
    assert Path(out["path"]).name == "facepalm.mp4"
