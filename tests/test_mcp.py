import json
import subprocess
import sys

from conftest import needs_ffmpeg

from agent_memes.mcp_server import TOOLS, Server


def test_tool_schemas_are_well_formed():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names))
    for tool in TOOLS:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        for req in schema.get("required", []):
            assert req in schema["properties"], (tool["name"], req)
        assert tool["description"] and "annotations" in tool


def test_initialize_negotiates_version():
    s = Server()
    r = s.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}
    )
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["capabilities"] == {"tools": {"listChanged": False}}
    r = s.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}
    )
    assert r["result"]["protocolVersion"] == "2025-11-25"
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"] == -32601


def test_tool_errors_are_reported_in_band():
    s = Server()
    r = s.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "meme_search", "arguments": {"query": "hello"}},
        }
    )
    assert r["result"]["isError"] is True
    assert json.loads(r["result"]["content"][0]["text"])["error"]["code"] == "missing_api_key"


@needs_ffmpeg
def test_stdio_roundtrip_with_local_library(clips, tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "mind_blown.mp4").write_bytes(clips["meme"].read_bytes())
    monkeypatch.setenv("AGENT_MEMES_LOCAL_DIRS", str(lib))
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "meme_search", "arguments": {"query": "mind blown"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "meme_preview",
                "arguments": {"ref": str(lib / "mind_blown.mp4"), "frames": 2},
            },
        },
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "agent_memes", "mcp"],
        input="\n".join(json.dumps(m) for m in msgs),
        capture_output=True,
        text=True,
        timeout=120,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    search = replies[1]["result"]
    assert search["isError"] is False
    assert search["structuredContent"]["results"][0]["title"] == "mind blown"
    preview = replies[2]["result"]["content"]
    assert preview[1]["type"] == "image" and preview[1]["mimeType"] == "image/jpeg"
