# SwingScribe

**Audio in → instrument-separated, swing-aware notation out.**

SwingScribe takes a jazz recording and produces MusicXML you can open in
MuseScore, with swing correctly interpreted rather than mangled: swing ratio
is estimated per section and rendered as straight eighths under a "Swing"
marking, with the expressive microtiming preserved as data instead of
discarded.

## Status

**M2 — separation + beat tracking.** `swingscribe run <file>` takes an audio
file — wav/flac natively, plus anything ffmpeg can decode (mp3, m4a/aac,
ogg, opus, wma, aiff, ...) — and produces four separated stems
(drums/bass/other/vocals) via
Demucs, then tracks beats and downbeats with beat_this on the drum stem,
emitting a per-beat tempo curve. `swingscribe click <file>` writes an
ear-test wav — the music with clicks at the detected beats (downbeats
higher-pitched). If the tracker lands an octave off (half/double tempo),
pass `--tempo-hint <bpm>` with the known tempo to correct the grid. Stage outputs are cached, so re-runs are instant. No
transcription or notation yet. See `swingscribe-plan.md` for the milestones.

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
