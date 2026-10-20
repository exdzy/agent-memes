# Security

## API keys

agent-memes reads keys only from the `VLIPSY_API_KEY` environment variable, a git-ignored `.env` in the working
directory, or `~/.config/agent-memes/config.toml` (written with mode 600 by `agent-memes auth set`). Keys are
removed from URLs and error messages before output. `doctor` and `auth status` show them masked.

The repository contains no keys, and CI (gitleaks plus `tests/test_no_secrets.py`) keeps it that way.

## Reporting a vulnerability

Please open a [private security advisory](https://github.com/exdzy/agent-memes/security/advisories/new) rather
than a public issue. If you accidentally published a key, revoke it with the provider right away.
