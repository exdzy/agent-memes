from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_memes.errors import MemeError

FIXTURES = Path(__file__).parent / "fixtures"
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never touch the real user config, cache, API key or a .env in the repo."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AGENT_MEMES_CONFIG", str(home / "config.toml"))
    monkeypatch.setenv("AGENT_MEMES_CACHE_DIR", str(home / "cache"))
    for var in (
        "VLIPSY_API_KEY",
        "AGENT_MEMES_LOCAL_DIRS",
        "AGENT_MEMES_SAFESEARCH",
        "AGENT_MEMES_WATERMARK",
        "VLIPSY_API_BASE",
        "AGENT_MEMES_FONT",
    ):
        monkeypatch.delenv(var, raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> dict[str, Path]:
    """Synthetic test clips: main (720p30 + audio), meme (480p23.976 + audio), silent (360p25, no audio)."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    d = tmp_path_factory.mktemp("clips")
    main, meme, silent = d / "main.mp4", d / "meme.mp4", d / "silent.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:sample_rate=48000",
        "-t",
        "6",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(main),
    )
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=426x240:rate=24000/1001",
        "-f",
        "lavfi",
        "-i",
        "sine=f=880:sample_rate=44100",
        "-t",
        "2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(meme),
    )
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "smptebars=size=320x180:rate=25",
        "-t",
        "1.5",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(silent),
    )
    return {"main": main, "meme": meme, "silent": silent}


class FakeHttp:
    """Stands in for HttpClient: serves fixture JSON and 'downloads' a local file."""

    def __init__(self, routes: dict[str, dict], media_file: Path | None = None) -> None:
        self.routes = routes
        self.media_file = media_file
        self.calls: list[tuple[str, dict]] = []
        self.downloads: list[str] = []

    def get_json(self, url: str, params: dict | None = None):
        self.calls.append((url, dict(params or {})))
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                return payload
        raise MemeError("Not found.", code="not_found")

    def download(self, url: str, dest: Path, **_kw) -> int:
        self.downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.media_file:
            shutil.copy(self.media_file, dest)
        else:
            dest.write_bytes(b"\x00" * 16)
        return dest.stat().st_size


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def vlipsy_routes() -> dict[str, dict]:
    search = load_fixture("vlipsy_search.json")
    return {
        "/v1/vlips/search": search,
        "/v1/vlips/trending": search,
        "/v1/vlips/V1iupR0X": {"data": search["data"][0]},
        "/v1/vlips/8WTyZTC5": {"data": search["data"][1]},
        "/v1/playlists": {
            "data": [{"id": "5N8mJ4Ub", "title": "Hello", "vlip_count": 209}],
            "pagination": {"offset": 0, "count": 1, "total_count": 1},
        },
        "/v1/playlists/5N8mJ4Ub/vlips": search,
    }


@pytest.fixture
def make_kit(vlipsy_routes):
    """Build a MemeKit with a fake key and fake HTTP (no network)."""
    from agent_memes.config import load_config
    from agent_memes.kit import MemeKit

    def factory(media_file: Path | None = None, **config_overrides):
        overrides = {"vlipsy_api_key": "test-key-not-real", "api_key_source": "test"}  # fake value, gitleaks:allow
        overrides.update(config_overrides)
        http = FakeHttp(vlipsy_routes, media_file)
        kit = MemeKit(load_config(**overrides), http=http)
        return kit, http

    return factory
