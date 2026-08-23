# SwingScribe

**Audio in → instrument-separated, swing-aware notation out.**

SwingScribe takes a jazz recording and produces MusicXML you can open in
MuseScore, with swing correctly interpreted rather than mangled: swing ratio
is estimated per section and rendered as straight eighths under a "Swing"
marking, with the expressive microtiming preserved as data instead of
discarded.

## Status

**M1 — ingest + separation.** `swingscribe run <file>` takes an mp3/wav/flac
and produces four separated stems (drums/bass/other/vocals) via Demucs, with
stage outputs cached so a re-run is instant. No beat tracking, transcription,
or notation yet. See `swingscribe-plan.md` for the plan and milestones.

Separation needs the ML dependency group (`uv sync --group ml`) and downloads
model weights (~300 MB) on first run. Without a CUDA GPU it runs on CPU —
expect minutes, not seconds, for a full track.

## Running the tests

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11.

```
uv sync
uv run pytest
uv run ruff check .
```

Audio never lives in this repository (plan §12). Tests that need real
recordings skip unless `SWINGSCRIBE_FIXTURES` points at a local audio
directory, and files are checksum-verified against
`tests/fixtures/manifest.yaml`.

## License

MIT — see `LICENSE`.
