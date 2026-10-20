import json
import os
import stat

from conftest import needs_ffmpeg

from agent_memes.cli import main
from agent_memes.config import config_path, load_config


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_missing_key_json_error(capsys):
    code, out = run(capsys, "search", "hello")
    assert code == 3
    assert out == {"ok": False, "error": out["error"]} and out["error"]["code"] == "missing_api_key"


def test_tools_manifest(capsys):
    code, out = run(capsys, "tools")
    assert code == 0 and any(t["name"] == "meme_insert" for t in out["data"]["tools"])


def test_timeline_example(capsys):
    code, out = run(capsys, "timeline", "--example")
    assert code == 0 and out["data"]["example"]["tracks"]


def test_auth_set_writes_private_file_outside_project(capsys, isolated_env):
    code, out = run(capsys, "auth", "set", "--key", "dummy-key-for-tests")  # fake value, gitleaks:allow
    assert code == 0 and out["data"]["api_key"] == "dum…ts"  # fake value, gitleaks:allow
    path = config_path()
    assert not str(path).startswith(str(isolated_env))
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    cfg = load_config()
    assert cfg.vlipsy_api_key == "dummy-key-for-tests" and cfg.api_key_source == "config_file"  # fake value, gitleaks:allow
    code, out = run(capsys, "auth", "status")
    assert "dummy-key-for-tests" not in json.dumps(out)
    run(capsys, "auth", "clear")
    assert load_config().vlipsy_api_key is None


def test_env_beats_dotenv_beats_config(isolated_env, monkeypatch):
    (isolated_env / ".env").write_text("VLIPSY_API_KEY=from-dotenv\n")
    assert load_config().api_key_source == ".env"
    monkeypatch.setenv("VLIPSY_API_KEY", "from-env")
    cfg = load_config()
    assert cfg.vlipsy_api_key == "from-env" and cfg.api_key_source == "env:VLIPSY_API_KEY"  # fake value, gitleaks:allow


@needs_ffmpeg
def test_convert_and_insert_via_cli(capsys, clips, tmp_path):
    code, out = run(capsys, "convert", str(clips["meme"]), "--preset", "square", "--out", str(tmp_path) + "/")
    assert code == 0 and out["data"]["width"] == 1080
    code, out = run(
        capsys,
        "insert",
        "--into",
        str(clips["main"]),
        "--meme",
        str(clips["meme"]),
        "--at",
        "1",
        "--mode",
        "pip",
        "--out",
        str(tmp_path / "pip.mp4"),
    )
    assert code == 0 and out["data"]["mode"] == "pip"


@needs_ffmpeg
def test_timeline_cli_relative_paths(capsys, clips, tmp_path):
    spec = tmp_path / "edit.json"
    (tmp_path / "main.mp4").write_bytes(clips["main"].read_bytes())
    spec.write_text(
        json.dumps({"tracks": [{"clips": [{"src": "./main.mp4", "out": 2}, {"src": "./main.mp4", "in": 4}]}]})
    )
    code, out = run(
        capsys, "timeline", str(spec), "--format", "otio", "edl", "--out", str(tmp_path / "export")
    )
    assert code == 0, out
    assert set(out["data"]["files"]) == {"otio", "edl"}
    assert out["data"]["timeline"]["duration"] == 4.0
