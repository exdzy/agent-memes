# AGENTS.md

Notes for AI coding agents working **on** this repository. If you only want to **use** the tool, read
[skills/agent-memes/SKILL.md](skills/agent-memes/SKILL.md).

## Layout

```
src/agent_memes/
  cli.py          argparse CLI, one JSON object per command
  mcp_server.py   dependency-free MCP server (stdio JSON-RPC) and the TOOLS manifest
  kit.py          MemeKit facade, used by the CLI, MCP and Python callers
  providers/      vlipsy.py (official REST API only), local.py (user clip folders)
  media.py        ffprobe/ffmpeg: probe, convert presets, captions, contact sheet, insert
  timeline.py     spec -> OTIO / FCPXML / xmeml / EDL / json
  snippets.py     Remotion, HyperFrames, MoviePy, HTML, ffmpeg snippets
  suggest.py      free text -> mood/keyword queries
  config.py       env > .env > ~/.config/agent-memes/config.toml > defaults
  http.py         urllib client: throttle, retries, key redaction
```

## Rules

- **No runtime dependencies.** Use the stdlib only. Dev tools go in `[dependency-groups].dev`.
- **No secrets.** Never commit API keys, including the example key from the Vlipsy docs. Tests use fake keys
  and `tests/conftest.py::FakeHttp`. `tests/test_no_secrets.py` enforces this.
- **No scraping.** The Vlipsy provider may only call the documented API (`https://docs.vlipsy.com`). Keep
  watermarked downloads as the default, keep attribution in every result, and keep the per-call batch cap.
- **The JSON contract is the API.** Adding fields is fine. Renaming or removing them is a breaking change. New
  failure modes need an `errors.MemeError` code and a `hint`.
- **The CLI, MCP and README stay in sync.** A new capability gets a `MemeKit` method, a CLI subcommand, a
  `TOOLS` entry plus a `_call` branch in `mcp_server.py`, and a README row.
- Tests run offline: `uv run pytest`. Media tests build synthetic clips with ffmpeg's lavfi sources and skip
  when ffmpeg is missing.
- Lint: `uv run ruff check .`.
