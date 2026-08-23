# SwingScribe

**Audio in → instrument-separated, swing-aware notation out.**

SwingScribe takes a jazz recording and produces MusicXML you can open in
MuseScore, with swing correctly interpreted rather than mangled: swing ratio
is estimated per section and rendered as straight eighths under a "Swing"
marking, with the expressive microtiming preserved as data instead of
discarded.

## Status

**M3 — separation, beat tracking, monophonic transcription.**
`swingscribe run <file>` takes an audio file — wav/flac natively, plus
anything ffmpeg can decode (mp3, m4a/aac, ogg, opus, wma, aiff, ...) — and
produces four separated stems via Demucs, tracks beats/downbeats with
beat_this on the drum stem (per-beat tempo curve, `--tempo-hint <bpm>` to
fix octave errors), and transcribes the lead line from the "other" stem
with CREPE. No swing analysis or notation yet.

Transcription can be limited to one solo and one instrument, which is both
the point and a large speed win — separation and beat tracking stay
whole-file and cached, so only transcription re-runs when you pick a
different span:

```
uv run swingscribe audition track.m4a --stem guitar --start 90 --end 210
uv run swingscribe ab track.m4a --stem guitar --start 90 --end 210
```

`audition` writes just the isolated stem so you can hear whether the soloist
is cleanly separated *before* spending minutes on analysis. Set
`separate.model: htdemucs_6s` in the config to split guitar and piano into
their own stems instead of leaving them mixed into `other`.

The two ear tests (plan §6): `swingscribe click <file>` writes the music with
clicks at the detected beats, and `swingscribe ab <file>` writes a stereo wav
— original left, rendered transcription right — plus the transcribed MIDI. Stage outputs are cached, so re-runs are instant. No
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
