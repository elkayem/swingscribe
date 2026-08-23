# SwingScribe

**Audio in → instrument-separated, swing-aware notation out.**

A pipeline that takes a jazz recording and produces MusicXML you can open in
MuseScore, with swing correctly interpreted rather than mangled: swing ratio is
estimated per section and rendered as straight eighths under a "Swing" marking,
with the expressive microtiming preserved as data instead of discarded.

**Status: M0 (skeleton).** The pipeline stages are stubs; the document model,
config, disk cache, and CI are in place. See `swingscribe-plan.md` for the full
plan and milestones.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11.

```
uv sync            # core + dev deps (no ML stack yet — that lands at M1)
uv run pytest      # tier-1 tests; audio-dependent tests skip without SWINGSCRIBE_FIXTURES
uv run ruff check .
```

Test audio never lives in this repository (see plan §12). Point
`SWINGSCRIBE_FIXTURES` at a local directory to enable the audio-dependent
tests; files are checksum-verified against `tests/fixtures/manifest.yaml`.
