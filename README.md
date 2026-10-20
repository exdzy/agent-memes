# agent-memes

**Meme video clips for AI agents: search a reaction clip, look at it, and drop it into any editing workflow.**

[![CI](https://github.com/exdzy/agent-memes/actions/workflows/ci.yml/badge.svg)](https://github.com/exdzy/agent-memes/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)

`agent-memes` is a CLI, an MCP server and a Python library in one package. It finds meme and reaction clips
through the [Vlipsy API](https://docs.vlipsy.com) (or in your own clip folders), shows them to vision models as
contact sheets, and gets them into a real edit:

- **Render with ffmpeg**: cut a meme into a video, overlay it, or play it picture-in-picture; convert to
  ProRes, WebM, GIF, 9:16 vertical, square or WAV; add classic top/bottom meme captions.
- **Export NLE timelines**: OpenTimelineIO (`.otio`), Final Cut Pro / Resolve (`.fcpxml`),
  Premiere Pro (`.xml`) and CMX3600 EDL. The edit opens in the editor with the media linked.
- **Paste-ready code**: snippets for Remotion, HyperFrames, MoviePy, HTML and ffmpeg.
- **Credits**: every download gets a `.meme.json` sidecar, and `credits` turns those into a list for the
  video description.

It is built for agents. Every command prints one JSON object, errors have stable codes and hints, the paths
it returns are absolute, and it needs nothing installed except Python and ffmpeg.

```console
$ agent-memes suggest "when the deploy fails on friday" --limit 2
{"ok": true, "data": {"context": "when the deploy fails on friday",
  "queries": ["this is fine", "fail", "deploy fails"],
  "results": [{"ref": "vlipsy:V1iupR0X", "title": "This is fine", "from": "The IT Crowd", "duration": 9.2, ...},
              {"ref": "vlipsy:LfhzegVd", "title": "The reason this species is a failure", ...}]}}

$ agent-memes insert --into talk.mp4 --meme vlipsy:V1iupR0X --at 12.5 --mode cut
{"ok": true, "data": {"path": "/abs/talk.with-meme.mp4", "duration": 71.43, "mode": "cut", ...}}
```

---

## Before you start: the Vlipsy API and its terms

agent-memes uses **only Vlipsy's official REST API**. It never scrapes vlipsy.com. Under the
[Vlipsy Terms of Service](https://vlipsy.com/terms), API use needs explicit permission, and apps that use it must
credit Vlipsy. In practice:

- **Bring your own API key.** Request one from Vlipsy (see [docs.vlipsy.com](https://docs.vlipsy.com) and the
  API section of the terms; at the time of writing new API access goes through an early-access form). This repo
  ships **no key**: not a real one, not the documentation's example key.
- **Watermarked by default.** Downloads use Vlipsy's watermarked files. Only use `--no-watermark` if your plan or
  agreement allows it.
- **Credit is built in.** Each fetch records an attribution line. Run `agent-memes credits` for your
  description.
- **It picks clips; it doesn't mirror the library.** Requests are rate limited and capped at 25 clips per call.
- **Fair use is your responsibility.** The clips come from films, TV and the internet, and the rights belong
  to their owners. Vlipsy's terms allow fair-use purposes such as commentary and memes.

No key yet? Point `AGENT_MEMES_LOCAL_DIRS` at your own folders of clips and every feature works offline.

*agent-memes is an independent open-source project. It is not affiliated with or endorsed by Vlipsy or Tunic Labs, Inc.*

---

## Install

Requires **Python 3.11+** and **ffmpeg** (`brew install ffmpeg`, `apt install ffmpeg`, `winget install ffmpeg`).

```bash
uv tool install git+https://github.com/exdzy/agent-memes
```

Or with pipx: `pipx install git+https://github.com/exdzy/agent-memes`. To run it without installing:

```bash
uvx --from git+https://github.com/exdzy/agent-memes agent-memes doctor
```

Set your key in one of these ways (they are checked in this order):

```bash
export VLIPSY_API_KEY=...          # 1. environment variable
echo "VLIPSY_API_KEY=..." > .env   # 2. a git-ignored .env in the working directory
agent-memes auth set               # 3. prompts, then stores it in ~/.config/agent-memes/config.toml (mode 600)
```

Then check the setup:

```bash
agent-memes doctor --online
```

## Use it from an agent (MCP)

The MCP server speaks JSON-RPC over stdio and has no dependencies.

**Claude Code**

```bash
claude mcp add agent-memes -e VLIPSY_API_KEY=$VLIPSY_API_KEY -- \
  uvx --from git+https://github.com/exdzy/agent-memes agent-memes mcp
```

Or install it as a plugin, which bundles the MCP server and the `agent-memes` skill:

```text
/plugin marketplace add exdzy/agent-memes
/plugin install agent-memes@agent-memes
```

**Claude Desktop, Cursor, Windsurf, and any client that takes an `mcpServers` JSON block**

```json
{
  "mcpServers": {
    "agent-memes": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/exdzy/agent-memes", "agent-memes", "mcp"],
      "env": { "VLIPSY_API_KEY": "your-key-here" }
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`)

```toml
[mcp_servers.agent-memes]
command = "uvx"
args = ["--from", "git+https://github.com/exdzy/agent-memes", "agent-memes", "mcp"]
env = { VLIPSY_API_KEY = "your-key-here" }
```

These configs live on your machine. Keep real keys out of any config file you commit.

### Tools

| Tool | What it does |
| --- | --- |
| `meme_suggest` | Takes a moment in plain words, runs a few mood and keyword searches, returns ranked candidates |
| `meme_search` | Phrase search with a rating filter (`high`=G, `medium`=G/PG default, `low`, `off`) |
| `meme_trending`, `meme_playlists`, `meme_playlist` | Browse |
| `meme_info` | Full metadata, renditions and attribution |
| `meme_preview` | Contact-sheet JPEG returned **as an image**, so the model can look at the clip first |
| `meme_fetch` | Download (cached), optionally into the project with a `.meme.json` credit sidecar |
| `meme_convert` | Presets `edit`, `prores`, `webm`, `gif`, `vertical`, `square`, `audio`, `poster`; trim, resize, fps, speed, mute, loudness, captions |
| `meme_insert` | Render a meme into a video: `cut`, `overlay` or `pip` |
| `meme_timeline` | Write `.otio`, `.fcpxml`, Premiere `.xml`, `.edl` and a resolved `.timeline.json` |
| `meme_snippet` | Code for Remotion, HyperFrames, MoviePy, HTML, ffmpeg, or a markdown credit line |
| `meme_credits` | Collect attributions from the sidecars |
| `meme_doctor` | Check ffmpeg, the caption font, the key (masked) and the cache |

`agent-memes tools` prints the same manifest (JSON Schemas) for agent frameworks that don't use MCP.

## CLI

```bash
agent-memes search "mind blown" --limit 5 --safesearch high
agent-memes suggest "awkward silence after a bad joke"
agent-memes trending
agent-memes info https://vlipsy.com/vlip/the-it-crowd-this-is-fine-V1iupR0X

agent-memes fetch vlipsy:V1iupR0X --out ./assets/memes          # + the-it-crowd-this-is-fine-V1iupR0X.meme.json
agent-memes preview vlipsy:V1iupR0X --frames 6                  # contact sheet for vision models

agent-memes convert vlipsy:V1iupR0X --preset vertical --caption-top "me watching prod" --caption-bottom "this is fine"
agent-memes convert vlipsy:V1iupR0X --preset prores --start 1.5 --end 6
agent-memes convert vlipsy:V1iupR0X --preset audio --normalize-audio     # meme as a sound effect

agent-memes insert --into vlog.mp4 --meme vlipsy:V1iupR0X --at 42 --mode cut
agent-memes insert --into vlog.mp4 --meme vlipsy:V1iupR0X --at 42 --mode pip --position tr --scale 0.33
agent-memes insert --into vlog.mp4 --meme ./my-clip.mp4 --at 42 --mode overlay --duck 0.2

agent-memes timeline edit.json --format otio fcpxml xmeml edl --out ./export --conform
agent-memes snippet vlipsy:V1iupR0X --for remotion --asset-dir public/memes --at 3.5
agent-memes credits ./assets --write CREDITS.md
```

Anywhere a ref is accepted, you can pass `vlipsy:ID`, a bare Vlipsy ID, a `vlipsy.com/vlip/...` or `vlp.to/...`
URL, `local:/path`, or a plain file path.

### Output contract

```json
{"ok": true,  "data": { ... }}
{"ok": false, "error": {"code": "missing_api_key", "message": "...", "hint": "...", "details": {...}}}
```

| Exit | `error.code` |
| --- | --- |
| 0 | success |
| 2 | `invalid_input` |
| 3 | `missing_api_key`, `auth_failed` |
| 4 | `not_found` |
| 5 | `ffmpeg_missing`, `ffmpeg_failed` (`details.stderr` holds the ffmpeg error) |
| 6 | `rate_limited` |
| 7 | `network_error`, `upstream_error` |

API keys are removed from every URL and error message before it is printed.

## Editing workflows

### Insert modes

| Mode | Result |
| --- | --- |
| `cut` | The main video pauses at `--at`, the meme plays full frame, then the main video resumes. Output gets longer by the meme's duration. |
| `overlay` | The meme covers the picture for its duration while the main audio keeps going, ducked. Output length doesn't change. |
| `pip` | The meme plays in a corner with a thin border. `--position tl\|tr\|bl\|br\|center\|top\|bottom`, `--scale 0.38`. |

The output always matches the main video's resolution, frame rate and 48 kHz audio. Inputs without an audio
track get silence, so the result never loses sync. Use `--meme-start` and `--meme-end` to trim the meme.

### NLE timelines

Write a small JSON spec. Times are in seconds, and `src` can be a file or a meme ref:

```json
{
  "name": "Reaction edit",
  "tracks": [
    {"name": "V1", "clips": [
      {"src": "./main.mp4", "in": 0, "out": 12.5},
      {"src": "vlipsy:V1iupR0X"},
      {"src": "./main.mp4", "in": 12.5}
    ]},
    {"name": "V2", "clips": [{"src": "vlipsy:8WTyZTC5", "at": 30, "duration": 3}]}
  ]
}
```

A clip without `at` starts where the previous clip on its track ends. `fps`, `width` and `height` default to the
first video clip's values. Meme clips are copied into `<out>/media/` so the project doesn't depend on the cache.
`--conform` re-encodes them to the sequence's frame rate and size.

| File | Open in |
| --- | --- |
| `.otio` | DaVinci Resolve (File > Import > Timeline), or [`otioconvert`](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) to any other format |
| `.fcpxml` | Final Cut Pro (File > Import > XML), DaVinci Resolve |
| `.xml` (FCP7 xmeml) | Premiere Pro (File > Import), Resolve, Kdenlive, Shotcut |
| `.edl` | Any NLE (first track only; relink by clip name) |

Track 1 becomes the primary storyline (FCPXML) or V1. Higher tracks become connected clips on lanes or V2, V3
and so on, and clips with sound get matching audio tracks. [examples/edit.json](examples/edit.json) has a
complete spec.

### Code-based editors

```bash
agent-memes snippet vlipsy:V1iupR0X --for remotion    --asset-dir public/memes   # <Sequence><OffthreadVideo/>
agent-memes snippet vlipsy:V1iupR0X --for hyperframes --asset-dir assets/memes   # <video class="clip" data-start ...>
agent-memes snippet vlipsy:V1iupR0X --for moviepy                                # VideoFileClip(...).with_start()
agent-memes snippet vlipsy:V1iupR0X --for html                                   # <figure><video> + caption
```

## Python

```python
from agent_memes import MemeKit

kit = MemeKit()  # reads VLIPSY_API_KEY / .env / user config
hits = kit.suggest("when the coffee machine breaks")["results"]
clip = kit.fetch(hits[0]["ref"], out_dir="assets/memes")
kit.insert("vlog.mp4", clip["path"], at=42.0, mode="pip", position="tr")
kit.timeline(
    {"tracks": [{"clips": [{"src": "vlog.mp4", "out": 42}, {"src": hits[0]["ref"]}]}]},
    out_dir="export",
    formats=["otio", "fcpxml"],
)
print(kit.credits(["assets"])["text"])
```

## Your own clip library

```bash
export AGENT_MEMES_LOCAL_DIRS=~/Clips/memes:~/Clips/reactions
agent-memes search "deal with it" --source local
```

Filenames are searchable. To add titles and tags, put a sidecar next to the clip (`clip.json` or `clip.meme.json`):

```json
{"title": "Deal with it", "tags": ["cool", "sunglasses"], "from": "My stream", "credit": "Clip by @me"}
```

`--source auto` (the default) uses Vlipsy when a key is set and local folders otherwise. `--source all` searches both.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `VLIPSY_API_KEY` | none | Your key (or `.env`, or `agent-memes auth set`) |
| `AGENT_MEMES_SAFESEARCH` | `medium` | `high` (G), `medium` (G/PG), `low` (≤PG-13), `off` |
| `AGENT_MEMES_WATERMARK` | `true` | Default watermark choice for downloads |
| `AGENT_MEMES_LOCAL_DIRS` | none | Clip folders, separated by `:` (`;` on Windows) |
| `AGENT_MEMES_CACHE_DIR` | `~/.cache/agent-memes` | Downloads and metadata |
| `AGENT_MEMES_FONT` | Impact or a bold system font | Caption font file |
| `AGENT_MEMES_CONFIG` | `~/.config/agent-memes/config.toml` | User config file |

## Development

```bash
git clone https://github.com/exdzy/agent-memes && cd agent-memes
uv sync
uv run pytest            # offline: uses fixtures and synthetic ffmpeg clips, never a real key
uv run ruff check .
```

`tests/test_no_secrets.py` fails the build if anything that looks like an API key or token is committed, and CI
also runs [gitleaks](https://github.com/gitleaks/gitleaks). Details are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) for the code. Clips belong to their respective rights holders and are subject to the terms of
the source you fetch them from.
