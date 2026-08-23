# SwingScribe

Jazz audio → swing-aware MusicXML. Python 3.11, uv, PyTorch (from M1).
`swingscribe-plan.md` is the source of truth; this file is the working summary.

## Architecture

Linear pipeline of pure stages in src/swingscribe/stages/. Each takes
(Document, Config) → Document. Stages never import each other. All shared types
live in model.py. pipeline.py is orchestration/wiring only — stage logic never
goes there.

## Caching (plan §3)

Stage outputs are cached on disk under **chained** content-hash keys:

    root_key  = sha256(audio_bytes)
    stage_key = sha256(upstream_key + stage_name + canonical_json(stage_config))

Chaining exists to close a staleness hole: with flat keys, changing an upstream
stage's config would not invalidate downstream entries, which would then serve
results computed from outdated inputs. Do not "simplify" the scheme back to a
flat hash. canonical_json = sorted keys, fixed separators — dict order must
never change a key.

## Dependencies

- Deps are added at the milestone that needs them, not up front: torch/demucs
  land at M1, beat_this at M2 (WITHOUT madmom — we skip the DBN, plan §2),
  the piano model at M7b.
- MuScriptor weights are CC BY-NC: when it arrives (M10) it goes behind its own
  extras group and module boundary so the NC license never touches core (§11).
- torch must come from the CUDA index, not PyPI default (plan §8).

## Rules

- Never add a dependency without asking.
- Never modify model.py without flagging the migration impact on cached artifacts.
- Every stage change requires a corresponding test in tests/.
- Do not run the full pipeline to test one stage — use cached fixtures.
- mir_eval is the source of truth for metrics. Don't hand-roll scoring.
- Baselines in tests/regression/baselines.json are sacred. If a change moves
  them, say so explicitly and explain why.
- **No audio in git, ever** (plan §12) — not committed-then-deleted, not in a
  private repo. Same for MIDI/MusicXML/note lists derived from commercial
  recordings; only aggregate metrics may be committed.

## Testing (plan §6, §12)

- `uv run pytest` — runs lint-fast tier-1 (synthetic/unit) tests; this is all
  CI runs (ubuntu + windows).
- Tests that need real audio use the `requires_audio` marker from
  tests/conftest.py and skip unless SWINGSCRIBE_FIXTURES points at a local
  audio directory outside the repo. Checksums are verified against
  tests/fixtures/manifest.yaml before use (catches wrong takes loudly).
- Tier-1 audio is *rendered at test time* from committed generators — never
  stored. Soundfonts are fetched, never committed.
- `uv run ruff check .` and `uv run ruff format --check .` must be clean.

## Current milestone

M0 — skeleton: repo, config, document model, cache layer, CI (plan §7).
Stages in src/swingscribe/stages/ are empty stubs. Do not implement stage
logic until the corresponding milestone.
