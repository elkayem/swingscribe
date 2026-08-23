# SwingScribe

**Audio in → instrument-separated, swing-aware notation out.**

SwingScribe takes a jazz recording and produces MusicXML you can open in
MuseScore, with swing correctly interpreted rather than mangled: swing ratio
is estimated per section and rendered as straight eighths under a "Swing"
marking, with the expressive microtiming preserved as data instead of
discarded.

## Status

**M0 — skeleton only. Nothing works yet.** The document model, config, stage
cache, and CI are in place; every pipeline stage is an empty stub. See
`swingscribe-plan.md` for the plan and milestones.

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
