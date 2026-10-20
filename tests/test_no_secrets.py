"""Guard rail: no API keys or tokens may ever be committed to this repository."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "vlipsy key": re.compile(r"\bvl_[A-Za-z0-9]{8,}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "openai/anthropic key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "key in url": re.compile(r"[?&]key=(?!REDACTED|\$|\{|<|\.\.\.)[A-Za-z0-9_-]{8,}"),
}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}


def repo_files():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        files = [ROOT / f for f in out]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]
    return [
        f for f in files if f.is_file() and f.suffix not in {".mp4", ".jpg", ".png", ".gif", ".mov", ".webm"}
    ]


def test_no_secrets_in_repo():
    hits = []
    for path in repo_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                hits.append(f"{path.relative_to(ROOT)}: {name}: {m.group(0)[:12]}…")
    assert not hits, "Possible secrets committed:\n" + "\n".join(hits)


def test_env_files_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".env" in gitignore
