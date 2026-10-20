---
name: agent-memes
description: Find meme / reaction video clips and put them into a video edit. Use when the user wants a meme, reaction clip, "this is fine" moment or funny cutaway in a video, asks to search Vlipsy, wants to cut / overlay / picture-in-picture a clip into footage, or needs the clip in Premiere, DaVinci Resolve, Final Cut, OpenTimelineIO, Remotion, HyperFrames or MoviePy. Also for converting a clip to vertical/ProRes/GIF/WebM, adding top/bottom meme captions, or collecting meme credits for a video description.
---

# agent-memes

Use the `meme_*` MCP tools when they are available. Otherwise use the `agent-memes` CLI: every command prints
one JSON object (`{"ok": true, "data": ...}` or `{"ok": false, "error": {"code", "message", "hint"}}`). If the
CLI is not installed, prefix commands with `uvx --from git+https://github.com/exdzy/agent-memes`.

## Workflow

1. **Find candidates.** Use `suggest "<the moment in plain words>"` when you know the moment but not the meme,
   and `search "<phrase>"` when you know the meme ("this is fine", "mind blown"). The default safesearch,
   `medium`, allows G and PG. Pass `--safesearch high` for kids' or brand content.
2. **Look before you pick.** Run `preview <ref>` and read the contact-sheet JPEG it returns. Titles and tags can
   mislead, so check the clip shows what the user meant.
3. **Fetch into the project.** `fetch <ref> --out <project>/assets/memes` writes the clip and a `.meme.json`
   credit sidecar, then returns an absolute `path` plus `media` (duration, fps, size, has_audio).
4. **Integrate.** Pick the route that matches what the user is working in:
   - A finished video file: `insert --into main.mp4 --meme <ref> --at <sec> --mode cut|overlay|pip`.
     `cut` pauses the main video, `overlay` covers it while its audio continues ducked, and `pip` is the corner
     variant.
   - A reformatted clip: `convert <ref> --preset edit|prores|webm|gif|vertical|square|audio|poster`, with
     optional `--start/--end`, `--caption-top/--caption-bottom`, `--normalize-audio`, `--speed`.
   - A human finishing the edit in an NLE: write a timeline spec and run
     `timeline spec.json --format otio fcpxml xmeml edl --out export --conform`.
   - A code-based editor: `snippet <ref> --for remotion|hyperframes|moviepy|html --asset-dir <dir> --at <sec>`.
5. **Credit.** Run `credits <assets dir>` and add its `text` to the video description, or show it to the user.

## Rules

- Never put an API key in project files, commits, snippets or chat. Keys come from `VLIPSY_API_KEY`, a
  git-ignored `.env`, or `agent-memes auth set`. If the result is `missing_api_key`, tell the user how to get
  and set a key (the `hint` explains), or offer local clip folders via `AGENT_MEMES_LOCAL_DIRS`.
- Keep downloads watermarked unless the user says their Vlipsy plan allows otherwise (`--no-watermark`).
- Fetch only the clips you will use. This tool picks clips; it does not bulk-download the library.
- Use absolute paths for outputs. When an ffmpeg step fails, read `error.details.stderr`.
- Timestamps are seconds (floats). Check `--at` against the main video's duration first, using `info` or the
  `media` that `fetch` returns.

## Timeline spec

```json
{"name": "Edit", "fps": 30, "width": 1920, "height": 1080,
 "tracks": [
   {"name": "V1", "clips": [{"src": "/abs/main.mp4", "out": 12.5}, {"src": "vlipsy:V1iupR0X"},
                            {"src": "/abs/main.mp4", "in": 12.5}]},
   {"name": "V2", "clips": [{"src": "vlipsy:8WTyZTC5", "at": 30, "duration": 3}]}
 ]}
```

`fps`, `width` and `height` are optional. A clip without `at` follows the previous clip on its track. Fields per
clip: `src`, `in`, `out` or `duration`, `at`, `name`.
