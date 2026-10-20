"""Configuration: environment variables > ./.env > config file > defaults.

API keys are never stored in the project. They come from the ``VLIPSY_API_KEY``
environment variable, a git-ignored ``.env`` file in the working directory, or the
user-level config file written by ``agent-memes auth set`` (mode 0600).
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

SAFESEARCH_LEVELS = ("high", "medium", "low", "off")
DEFAULT_API_BASE = "https://apiv2.vlipsy.com"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else Path.home() / fallback


def config_path() -> Path:
    override = os.environ.get("AGENT_MEMES_CONFIG")
    if override:
        return Path(override).expanduser()
    return _xdg("XDG_CONFIG_HOME", ".config") / "agent-memes" / "config.toml"


def default_cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "agent-memes"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _read_config_file(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    vlipsy_api_key: str | None = None
    api_key_source: str | None = None
    api_base: str = DEFAULT_API_BASE
    cache_dir: Path = field(default_factory=default_cache_dir)
    safesearch: str = "medium"
    watermark: bool = True
    local_dirs: list[Path] = field(default_factory=list)
    font: str | None = None
    request_interval: float = 0.35
    timeout: float = 30.0
    user_agent: str = f"agent-memes/{__version__} (+https://github.com/exdzy/agent-memes)"

    def to_public_dict(self) -> dict:
        """Config as JSON, with the API key masked."""
        return {
            "vlipsy_api_key": mask(self.vlipsy_api_key),
            "api_key_source": self.api_key_source,
            "api_base": self.api_base,
            "cache_dir": str(self.cache_dir),
            "safesearch": self.safesearch,
            "watermark": self.watermark,
            "local_dirs": [str(p) for p in self.local_dirs],
            "font": self.font,
            "config_file": str(config_path()),
        }


def mask(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 6:
        return "***"
    return f"{key[:3]}…{key[-2:]}"


def load_config(**overrides) -> Config:
    file_cfg = _read_config_file(config_path())
    dotenv = _read_dotenv(Path.cwd() / ".env")
    env = os.environ

    cfg = Config()

    if env.get("VLIPSY_API_KEY"):
        cfg.vlipsy_api_key, cfg.api_key_source = env["VLIPSY_API_KEY"].strip(), "env:VLIPSY_API_KEY"
    elif dotenv.get("VLIPSY_API_KEY"):
        cfg.vlipsy_api_key, cfg.api_key_source = dotenv["VLIPSY_API_KEY"], ".env"
    elif file_cfg.get("vlipsy_api_key"):
        cfg.vlipsy_api_key, cfg.api_key_source = str(file_cfg["vlipsy_api_key"]), "config_file"

    cfg.api_base = (env.get("VLIPSY_API_BASE") or file_cfg.get("api_base") or DEFAULT_API_BASE).rstrip("/")

    cache = env.get("AGENT_MEMES_CACHE_DIR") or file_cfg.get("cache_dir")
    if cache:
        cfg.cache_dir = Path(cache).expanduser()

    safesearch = (env.get("AGENT_MEMES_SAFESEARCH") or file_cfg.get("safesearch") or cfg.safesearch).lower()
    if safesearch in SAFESEARCH_LEVELS:
        cfg.safesearch = safesearch

    cfg.watermark = _bool(env.get("AGENT_MEMES_WATERMARK", file_cfg.get("watermark")), True)

    local = env.get("AGENT_MEMES_LOCAL_DIRS")
    if local:
        cfg.local_dirs = [Path(p).expanduser() for p in local.split(os.pathsep) if p]
    elif isinstance(file_cfg.get("local_dirs"), list):
        cfg.local_dirs = [Path(str(p)).expanduser() for p in file_cfg["local_dirs"]]

    cfg.font = env.get("AGENT_MEMES_FONT") or file_cfg.get("font")

    for key, value in overrides.items():
        if value is not None:
            setattr(cfg, key, value)
    return cfg


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value))


def update_config_file(**values) -> Path:
    """Merge ``values`` into the user config file (``None`` removes a key). File mode is 0600."""
    path = config_path()
    data = _read_config_file(path)
    for key, value in values.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k} = {_toml_value(v)}\n" for k, v in sorted(data.items()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("# agent-memes user config. Keep this file out of version control.\n" + body)
    os.chmod(path, 0o600)
    return path
