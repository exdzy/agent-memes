# Contributing

Thanks for helping. Issues and pull requests are welcome.

```bash
uv sync
uv run pytest          # offline; needs ffmpeg for the media tests (they skip without it)
uv run ruff check .
```

## Ground rules

1. **Never commit secrets.** That includes API keys (also the example key from the Vlipsy docs), tokens and
   `.env` files. Tests use fake keys and the `FakeHttp` fixture. `tests/test_no_secrets.py` and gitleaks in CI
   catch mistakes. If you leak a key anyway, revoke it first, then rewrite history.
2. **Official APIs only.** Providers must use documented APIs within the provider's terms. No scraping, no
   removing watermarks, no bulk mirroring.
3. **Zero runtime dependencies.** Use the stdlib plus the ffmpeg binary.
4. **Keep the agent contract.** One JSON object per CLI command, stable error codes with hints, and absolute
   paths in results. New features land in `MemeKit`, the CLI and the MCP `TOOLS` together, with a test.

## Adding a provider

Implement `search(query, *, limit, offset, safesearch) -> Page` and `get(id) -> Meme` (see
`providers/local.py`). Give refs a unique prefix (`name:id`), and give every `Meme` the fields needed for
attribution (`title`, `source`, `page_url` or `credit`).
