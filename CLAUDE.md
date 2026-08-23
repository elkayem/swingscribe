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
  landed at M1, beat_this at M2 (WITHOUT madmom — we skip the DBN, plan §2),
  the piano model at M7b.
- Heavy ML deps live in the `ml` dependency group, and the GUI's (fastapi,
  uvicorn) in `gui`. Plain `uv sync` — and therefore CI — installs neither;
  dev machines run `uv sync --group ml --group gui`.
- **The GUI frontend has no JS dependencies and no build step** — no Node, no
  npm, no bundler (see docs/gui-design.md for why Gradio and wavesurfer.js
  were both rejected). Keep it that way: `src/swingscribe/gui/static/` is
  plain ES modules served as-is.
- **Stage modules must lazy-import heavy libs inside functions** (torch,
  torchaudio, demucs). pipeline/cli/tests must stay importable without the
  ml group, or CI breaks.
- The original dev machine has NO NVIDIA GPU: torch comes from the CPU wheel
  index (see pyproject). On a CUDA machine, switch the index URL to cu124
  (plan §8) — never take CUDA availability for granted; separate.run logs
  its resolved device.
- **numba is unusable on the dev machine** — Windows Application Control
  blocks its compiled DLLs. That rules out librosa (hard numba dependency),
  so f0 is torchcrepe (CREPE) not pYIN, onsets are hand-rolled numpy
  spectral flux, and torchcrepe is imported through a resampy shim
  (transcribe._import_torchcrepe) with the numba-free weighted_argmax
  decoder. Never add librosa, resampy, or numba-dependent packages.
- MuScriptor weights are CC BY-NC: when it arrives (M10) it goes behind its own
  extras group and module boundary so the NC license never touches core (§11).

## This machine (environment traps that cost real time)

Windows, no NVIDIA GPU, repo under OneDrive, and TLS is intercepted. Every one
of these has broken a tool at least once:

- **TLS interception** breaks anything with a bundled cert store:
  - uv → set `UV_SYSTEM_CERTS=true`
  - winget → add `--source winget` (its msstore source fails cert pinning)
  - Python downloads (huggingface_hub, torch.hub) → set `SSL_CERT_FILE`,
    `REQUESTS_CA_BUNDLE`, and `CURL_CA_BUNDLE` to
    `%USERPROFILE%\.windows-ca-bundle.pem` (exported from the Windows cert
    stores; regenerate from `Cert:\*\Root` if certs rotate)
- **OneDrive** breaks uv's hardlinks (`os error 396`) → set `UV_LINK_MODE=copy`.
  It also intermittently locks `.venv\Lib\site-packages\swingscribe-0.1.0.dist-info`
  mid-install; delete it and re-sync when that happens.
- **ffmpeg** is installed but not on PATH; it lives under
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin`.
- **Application Control blocks numba's DLLs** — see the dependency note above.
- Demucs separation is ~6-13 min per track on CPU. Cache accordingly, and
  prefer `swingscribe audition` (~1s on cached stems) while iterating.

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
  CI runs (ubuntu + windows). Tests needing the ml group use importorskip;
  tests that download model weights are additionally gated behind
  SWINGSCRIBE_HEAVY_TESTS=1 so a routine dev pytest stays fast too.
- Tests that need real audio use the `requires_audio` marker from
  tests/conftest.py and skip unless SWINGSCRIBE_FIXTURES points at a local
  audio directory outside the repo. Checksums are verified against
  tests/fixtures/manifest.yaml before use (catches wrong takes loudly).
- Tier-1 audio is *rendered at test time* from committed generators — never
  stored. Soundfonts are fetched, never committed.
- `uv run ruff check .` and `uv run ruff format --check .` must be clean.

## GUI (plan §13, screens 1-3)

`swingscribe gui [track]` serves the selection/audition app on 127.0.0.1.
`src/swingscribe/gui/` is a **thin adapter over pipeline.run and Config** — the
eventual Hugging Face Space must be able to reuse the core without reusing the
UI, so pipeline logic never goes here. Two rules that are easy to break:

- Stage progress is a side channel (`progress.py`), not a stage argument. The
  stage contract stays (Document, Config) -> Document. Install the sink inside
  the worker thread — ContextVars don't cross threads.
- `gui.*` config is UI state and must never reach a cache key. `stage_config()`
  enforces this via `STAGE_SECTIONS`; changing a port must not throw away a
  separation.

## Current milestone

M3 — monophonic transcription (plan §7): transcribe stage runs CREPE on the
"other" stem with periodicity+energy gating, persistence-based segmentation
(vibrato/scoops never split notes), and octave folding; `swingscribe ab
<file>` writes the §6 stereo ear test (original left, rendered transcription
right) plus the transcribed MIDI. Remaining stages (swing onward) are empty
stubs. Do not implement stage logic until the corresponding milestone.
