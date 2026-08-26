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
  `ingest.find_ffmpeg()` locates it there when `shutil.which` finds nothing,
  so the app itself doesn't need PATH fixed — but a shell running the tools
  by hand (this file's other commands, ad hoc scripts) still does.
- **numba now works here again** (checked 2026-08-25: numba 0.67 / llvmlite
  0.49 JIT-compile in 0.4s, and librosa 0.11's stft and resample both run).
  The Application Control block that shaped several decisions has lifted, and
  librosa has in fact been installed all along as a torchcrepe dependency.
  This does NOT mean go and add librosa: the numba-free replacements
  (hand-rolled spectral flux, torchaudio resampling, the weighted_argmax
  decoder) are measured and working, and `transcribe._import_torchcrepe`'s
  resampy stub is already a no-op when the real thing imports. It means a new
  dependency that needs numba is no longer disqualified on sight — verify it
  on the machine rather than assuming either way.
- Demucs separation on CPU: **`htdemucs` ~2.8 min** per 10-minute track,
  `htdemucs_6s` ~2.7, **`htdemucs_ft` ~11** — the last is a bag of FOUR models
  and that is the whole 4x. It buys nothing measurable (mean note F1 0.759 vs
  0.752 over the 9 benchmark solos that used it), so `htdemucs` is the
  default. `jobs>0` does not help; torch already uses every core.
  `separate.run` reuses a complete set of stems already on disk, so a config
  change upstream no longer costs a re-separation. Prefer
  `swingscribe audition` (~1s on cached stems) while iterating.

## Rules

- Never add a dependency without asking.
- Never modify model.py without flagging the migration impact on cached artifacts.
- Every stage change requires a corresponding test in tests/.
- Do not run the full pipeline to test one stage — use cached fixtures.
- mir_eval is the source of truth for metrics. Don't hand-roll scoring. The
  one exception is `alignment.py`'s time-free note-sequence comparison, which
  exists because mir_eval has no such measure and because scoring a notated
  score in time would need a tempo map from our own beat tracker — see its
  module docstring. Everything time-based still goes through `metrics.py`.
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
- `scripts/score_benchmark.py` scores the pipeline against the hand
  transcriptions in `benchmark/` (results: `docs/m3-benchmark.md`). Run it
  after any transcribe change — it is the only measurement against real
  music, and it is cheap once the stems are cached (`--reuse` skips CREPE).
  Its note cache and everything else it touches stay out of git.

## GUI (plan §13, screens 1-3)

`swingscribe gui [track]` serves the selection/audition app on 127.0.0.1.
`src/swingscribe/gui/` is a **thin adapter over pipeline.run and Config** — the
eventual Hugging Face Space must be able to reuse the core without reusing the
UI, so pipeline logic never goes here. Two rules that are easy to break:

- Stage progress is a side channel (`progress.py`), not a stage argument. The
  stage contract stays (Document, Config) -> Document. Install the sink inside
  the worker thread — ContextVars don't cross threads.
- **`meter` runs AFTER `transcribe`, not next to `beats`.** It belongs with
  beats conceptually, but chained keys mean anything above transcribe
  invalidates it — so moving a downbeat would re-run CREPE. Don't "tidy" the
  stage order (docs/meter-plan.md).
- **`beats` runs BEFORE `separate`, and tracks the MIX, not the drum stem.**
  The plan says drum stem; measured over 11 WJazzD solos the mix wins 0.929
  to 0.816 beat F1, because an isolated kit at 275 bpm is a two-feel and the
  tracker halves the pulse. It is also the difference between a Beats button
  that costs ~5 seconds and one that costs a separation (~11 min). Ordering
  is what keeps a change of separation model from throwing away the grid and
  the downbeat anchor with it (docs/benchmark-deficiencies.md R7).
- **Per-track GUI settings live beside the audio** (`<track>.swingscribe.json`),
  never in the cache dir. The cache is derived data that must stay safely
  deletable; a span and a downbeat are human judgements. Only the disposable
  recents index stays under the cache.
- **Erasures ("not the solo") are matched by content, never by index.** Any
  config change renumbers every note, so a stored index would silently silence
  a different one. `gui/erasures.py` matches on (onset, pitch) with exact pitch
  — a re-decoding that follows another voice must fail to match and be
  reported, not erase a note nobody judged. They are training data for
  melodic-line selection (issue #8): never drop one as a side effect.
- Bar lines are derived by counting beats from an anchor. The beat tracker's
  detected downbeat layer is noise (open-issue #5) and must not be drawn or
  trusted; only its pulse layer is reliable.
- `gui.*` config is UI state and must never reach a cache key. `stage_config()`
  enforces this via `STAGE_SECTIONS`; changing a port must not throw away a
  separation.
- **Export builds its score through `swingscribe/notation.py`, not its own
  Document.** The eval harness needs exactly the same "notes + a beat grid ->
  a Notation" assembly, and a second copy of it is the shape of duplication
  that has already cost this harness twice. The GUI cannot use `pipeline.run`
  for it: the notes on screen carry the listener's ERASURES, which the pipeline
  knows nothing about and must not. Everything below transcribe is arithmetic,
  so export is a plain request, not a job.
- **`notation_for_span` trims the beat grid to the span first, so bar 1 is the
  span's first bar** — the way a solo transcription is numbered, and the way
  the files in `benchmark/` already are. It deliberately does not call
  `stages/meter.py`: over a span the user selected by ear, with a downbeat they
  placed by hand, meter derivation has nothing left to decide. The score lands
  beside the audio like `ab`/`audition`/`click`, never in the cache, with the
  span in the filename so a second chorus does not overwrite the first.
- **`ensemble` and `transposition` are per-track sidecar fields with menus
  built from `config.ENSEMBLES`/`TRANSPOSITIONS`.** Neither is inferable from
  the signal — one says who is playing, the other which horn — so both can only
  come from the listener. Build the menus from those constants, never from a
  hand-copied list, or the UI drifts from what the validator accepts.
- **The Score button and the F1 on the ground-truth bar are DIFFERENT
  QUESTIONS**, and this is the project's most expensive confusion appearing in
  the UI. The bar's F1 is time-free and pitch-only (`gui/ground_truth.py`):
  did we hear the right notes? The Score button asks whether the notes we got
  are WRITTEN the way a human wrote them, through
  `benchmark.score_against_notation` — shared with `run_eval.py`, never
  reimplemented. It reads lower and always will.
- **Never show that rhythm number without its coverage.** Measured over every
  notation the benchmark can build against every hand score on disk, coverage
  is 0.69-0.74 on a right pairing and 0.16-0.36 on fourteen wrong ones — but
  rhythm on a WRONG pairing reads up to 0.583, higher than All The Things
  scores against its own correct score (0.618). Two eighth-note bebop lines
  agree about most gaps by chance, so rhythm cannot tell you it is describing
  the wrong tune. `COVERAGE_FLOOR = 0.5` sits in coverage's gap and is what
  `trusted` keys on; below it the numbers are withheld, not shown.
- **An unmatched erasure is not automatically a problem.** `erasures.resolve`
  splits them: `moved` (a note still sounds there, at another pitch — worth a
  look) against the rest, which simply vanished because the transcriber no
  longer emits them. Reporting both as "no longer matches", next to a Discard
  button, put a warning colour on good news — 26 of Orbits' 33 hand-erased
  left-hand notes stopped matching because corroboration had already dropped
  exactly those (M7b).

## M7b — the piano path (current)

The plan routes piano through a polyphonic model, and the measurement says why
in a way the plan did not anticipate. `docs/m7b-piano.md` has it all; the two
things not to re-derive:

- **Piano's problem is not polyphony, it is the left hand.** ~78% of our pitch
  errors on the two piano solos with hand transcriptions are notes a fifth or
  more BELOW the melody, and a quarter are exact octaves; on horns that is
  6-15% and 0-2%. Chord tones are only 10% of the Peterson's notes, so a
  perfect monophonic transcriber still caps at note F1 0.946 there — and we
  are nowhere near that cap, so polyphony is not yet what is costing us.
- **The model chosen is `piano_transcription_inference`, not the plan's
  `transkun`** — 10 dependencies against 25, and its `torchlibrosa` is
  numba-free. Deviation recorded in docs/m7b-piano.md.
- Using the model as the PRIMARY line: Giant Steps 0.705 -> 0.879, but the
  Peterson does **not** improve (0.648 -> 0.627). It detects the notes; we
  pick the wrong ones. That is **melodic-line selection** (open-issue #8),
  still open, and it is why the model is not the primary line today.
- **What ships instead is the model as a SECOND OPINION**
  (`corroborate.py`). `snap_octaves` moves a note to the oracle's octave when
  they agree on pitch class (raises recall, fixes D4); `corroborate` drops
  what the oracle will not vouch for (raises precision). Every piano solo
  improved on both benchmarks and both halves of F1 — Orbits 0.828 -> 0.895,
  Gingerbread Boy 0.641 -> 0.715, Oleo 0.674 -> 0.710, Giant Steps 0.705 ->
  0.765, Lover 0.648 -> 0.698. Mean WJazzD note F1 0.766 -> 0.782.
- **NEVER route a horn to the piano oracle.** A piano model asked about a
  saxophone vouches for nothing, and rejection then deletes the whole line.
  `ensemble` lives per track in the sidecar for this reason, and Dolores stays
  horn-led even though a third of its span is Hancock's piano.
- **A note we emit that is not in the hand transcription is not automatically
  an error.** The hand transcriptions notate the RIGHT HAND ONLY. Corroboration
  is what separates "we invented it" from "it happened, nobody asked for it" —
  on Orbits the listener's erasures are 0% corroborated (CREPE was tracking the
  bass through stem bleed), on the Peterson they are 90% (his left hand).
- **The listener does not want us to pick the line — they want to SEE the top
  one or two notes and delete the rest.** That flips the target from precision
  to recall, and recall is where the oracle is strong: top-2 of each onset
  cluster contains the note the human notated 93-96% of the time, against 0.74
  recall for what ships. Precision is ~0.5, which is the trade they asked for.
- **The oracle's `velocity` is an unused melody cue.** Loudest-of-cluster beats
  highest-of-cluster on the hard case (Peterson 0.583 -> 0.715 F1). A register
  floor does NOT generalise — `>= 55` helped Giant Steps and hurt Lover.
- **Never filter notes by duration.** Measured against 302 erasure labels, a
  0.12s floor removes 41% of erased notes and 28% of KEPT ones — barely better
  than random. Confidence does separate them (AUC 0.830), but at a 0.65 floor
  it still costs 7% of kept notes to remove 30% of erased ones, so it is a
  cue for SHADING the review UI, not for deleting.
- `mscz.Score` now has two views. `melody` (top note per chord) is what every
  measure through M6 uses and what the time-free aligner needs; `notes` is
  everything. Scoring polyphony against `melody` would report a polyphonic
  transcriber as no better than the monophonic one it replaced.

## Current milestone

M4 — SwingModel (plan §5 stage 4). The swing stage turns onsets + the beat
grid into per-window `SwingSpan`s: offbeat phase φ, BUR = φ/(1−φ), and a
confidence. Pure arithmetic, no heavy imports, so the whole stage and its
acceptance criterion run in CI. Results and limits: `docs/m4-swing.md`.

Two things about it that are easy to get wrong:

- **`confidence` is the load-bearing number, not `is_swung`.** No statistic
  separates "swung" from "no grid at all" at a 16-beat window, and that is
  *inherent*: across 359 hand-annotated WJazzD solos real jazz scatters at
  phase spread 0.135 against uniform noise's 0.144. `is_swung` is a z-test
  against straight — the warp-or-not question M5 needs — and confidence says
  whether to believe it. Filter on confidence.
- **BUR ≈ 1.56 is the noise floor, not "slightly swung."** The offbeat region
  is asymmetric about 0.5, so feel-free onsets still average late. Never warp
  on a reading near 1.5.
- **BUR precision is set upstream.** ±5% needs onsets good to ~10ms; the
  estimator itself is already at its sampling limit (phase bias +0.0002).
- Swing timing is validated against WJazzD without any audio
  (`scripts/wjazz_swing.py`, `docs/wjazzd.md`). The database is ODbL — only
  aggregate numbers may enter this repo, and it lives outside it.

M5 — Quantize (plan §5 stage 5) landed with it: swing-warp, then grid-snap,
`timing_residual` preserved. Also pure arithmetic, also fully CI-tested.
Results and limits: `docs/m5-quantize.md`.

- **Never warp on a BUR near 1.5 unless confidence is high.** The no-swing
  floor is 1.56 and it scales with confidence — it is a claim about evidence,
  not about music. Applied ONCE to the pooled track reading; per-span
  thresholding put a 25.6ms spike in the round trip at exactly the threshold.
- **`replay_onsets(restore_residual=True)` is exact by construction.** Only
  the default (replaying the notation) measures anything.

M6 — Notate + Export + the eval harness. All three landed together; the plan
and this file had drifted apart on what M6 even was (plan §7's table says M6
is the eval harness, this file said Notate), so both readings were satisfied.
Results and limits: `docs/m6-notate.md`.

- **Notate does NOT use music21, which the plan names for it.** Everything the
  stage needs is arithmetic, and keeping it arithmetic means key detection and
  spelling run in CI like every other stage. This is a plan deviation on the
  record in `docs/benchmark-deficiencies.md` — confirm or overturn it.
- **Everything is concert pitch until export.** The benchmark's ground truth is
  concert pitch; a stage that silently transposed would invalidate every
  comparison. Written pitch is applied once, at export — and the key signature
  moves with it, or the part sounds right and is covered in accidentals.
- **A tuplet is allowed inside one beat and no wider.** Quantize chooses its
  grid one beat at a time, and a third of a beat is not a note value: without
  `NotatedNote.tuplet`, 57 of Confirmation's 129 bars did not add up.
- **24 divisions per quarter** in MusicXML — the smallest divisible by 8 (a
  thirty-second) and 3 (a triplet).
- **Never read more resolution out of a beat than its notes demonstrate.**
  This one cost the most and was invisible until the notation was scored as
  notation. A warped offbeat lands near 0.6, not 0.5, so on pure snap error a
  swung eighth pair wins a TRIPLET grid — and once tuplets were restricted it
  won a dotted-eighth instead. `choose_grid` now needs three onsets before a
  tuplet is allowed, offers an eighth-note grid at all, and takes the
  coarsest grid within `grid_slack` of the best. Rhythm 0.54 → 0.73.
- **A grid that merges two onsets is too coarse, whatever its snap error.**
  Two notes on one grid position are one note in a single-line score. Without
  this, coarsening bought notated rhythm by silently deleting 4.8% of the
  notes.
- **`grid_slack` must NOT be tuned on the notation score.** That score rises
  monotonically to "write everything as eighth notes", which three bebop
  solos reward and real sixteenth-note material would not. It is set by
  quantize's own 20 ms round-trip acceptance instead — the measure of what
  coarsening costs the performance rather than what it buys the page.

## Measuring: two benchmarks, and they answer different questions

Confusing them cost months. `docs/benchmark-deficiencies.md` is the running
list of what is actually wrong; run everything with one command:

    uv run python scripts/run_eval.py --db wjazz/wjazzd.db

- **WJazzD (`score_wjazz.py`) is audio against audio** — a human's per-note
  onsets in seconds for the same recording. Asks "did we hear what was
  played?" and is the right measure of `transcribe`. Currently **mean note F1
  0.782 and mean beat F1 0.929, both over the same 11 solos**. Quote the `n`
  with the mean: beat F1 was once reported as 0.97 because it was silently a
  mean over 4 (R8). `run_eval.py` now pins and prints each mean's own count.
- **MuseScore (`score_benchmark.py`) is audio against notation.** Asks "would
  this notate the way a human notated it?" It charges the gap between
  performed timing and notated rhythm to the transcriber, so it reads lower
  and always will. Currently mean note F1 0.51.

Reading the second as a transcription failure is exactly the mistake that was
made. Both are kept; neither subsumes the other.

- **`.mscz` stores the WRITTEN pitch under an 8va/8vb**, with the octave in a
  separate `<Spanner type="Ottava">`; `mscz.parse` applies it. Ignoring it was
  a ground-truth bug worth an octave on 58 notes across 5 of the 10 hand
  scores. Writing a passage 8va to keep it on the staff is ordinary notation,
  not an error on the transcriber's side — do not "correct" it back.
- **`score_benchmark.TUNES` is DERIVED from the sidecars, never hand-listed.**
  A hand-maintained table is why seven hand transcriptions sat unmeasured
  while the benchmark reported a mean over four. A score picked in the GUI is
  benchmarked because it was picked.
- **`ensemble: null` is not `horn-led`, but it behaves like it.** Three of the
  four new piano solos silently skipped the piano oracle that way. Check the
  routing before believing a piano number.
- **The GUI and the harness use DIFFERENT cache directories** —
  `benchmark/.swingscribe-cache` (relative to the track) versus
  `./.swingscribe-cache` (relative to the cwd run_eval is invoked from). The
  same track gets separated twice. Copy the one stem across rather than
  re-separating; do not "fix" it by repointing the harness, which orphans
  every separation already in the root cache.

**Two fitting bugs have now been found in this harness, both of which reported
a measurement failure as a transcription failure.** Any code that aligns our
notes to a reference belongs in the package with tests, never in a script:
`src/swingscribe/benchmark.py` and `src/swingscribe/wjazz.py`.

- A per-window offset chosen by maximizing ONSET hits slips whole eighth
  notes on a line of near-uniform eighths — it cost note F1 ~0.17 on every
  tune. Correspondence must come from pitch first.
- An offset search seeded from the span's start missed a solo that began 26 s
  into the span, and reported 0.51 where the truth was 0.84.

The control that says a fit is not manufacturing agreement: run it against the
WRONG take. It scores under 10% there against 79-84% on a right one.
