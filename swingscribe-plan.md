# SwingScribe — Development Plan

**Audio in → instrument-separated, swing-aware notation out.**

A pipeline that takes a jazz recording and produces MusicXML you can open in MuseScore,
with swing correctly interpreted rather than mangled.

---

## 1. Scope

### In scope (v1)
- Ingest an audio file (mp3/wav/flac), produce MusicXML + MIDI + a JSON analysis document.
- Source-separate into stems; transcribe the monophonic lead line and the bass line well.
- **Piano solos** where the piano is the foreground instrument (solo piano recordings and
  piano trios). Polyphonic, not just single-note lines — see §5, Stage 3.
- Beat/downbeat tracking with a tempo curve.
- Swing ratio estimation, per-section straight-vs-swung classification, and correct
  rendering as straight eighths under a "Swing" marking.
- A real evaluation harness with tracked regression metrics.
- CLI first, Gradio UI second, Hugging Face Space third.

### Explicitly out of scope (v1)
- Piano **comping** — accompaniment buried under a horn solo in a mixed ensemble. The
  blocker is separation, not polyphony: comping shares the "other" stem with the horns
  and can't be cleanly isolated. (Piano *solos* are in scope — see above.)
- Two-staff piano grand-staff engraving with hand/voice assignment. v1 emits piano
  solos on a single staff; splitting into left and right hand is unsolved territory.
- Drum notation.
- Real-time / streaming operation.
- Mobile, App Store, native desktop installers.
- Anything commercial (MuScriptor weights are CC BY-NC).

### Design principle
**Do the tractable thing excellently before attempting the intractable thing badly.**
A tool that nails bass lines and horn solos with correct swing notation is more useful
than one that half-transcribes everything.

---

## 2. Platform & stack

Python is the right call — every model and MIR library in this space is Python-first,
and there is no serious alternative ecosystem. Nothing else on the table.

| Concern | Choice | Notes |
|---|---|---|
| Python | 3.11 | Best compatibility across torch/demucs/beat_this. Avoid 3.12+ for now. |
| Env/deps | `uv` | Much faster than conda, handles the torch CUDA index cleanly on Windows. |
| DL runtime | PyTorch + CUDA | Check your GPU VRAM early; MuScriptor-large is 1.4B params. |
| Separation | `demucs` (htdemucs_ft) | MIT. Later: swap in a BS-Roformer checkpoint behind the same interface. |
| Beat tracking | `beat_this` (CPJKU) | Run with `dbn=False`. See note below. |
| Monophonic pitch | `basic-pitch` + `pYIN`/CREPE | For horn lines and bass. |
| Piano | `transkun` (or Kong et al. high-res) | Polyphonic, MAESTRO-trained, handles pedal. |
| Multi-instrument | `MuScriptor` | Optional/late stage. CC BY-NC — keep it behind a plugin boundary. |
| Symbolic music | `music21` | Notation assembly, key detection, enharmonic spelling, MusicXML out. |
| MIDI | `pretty_midi` | Intermediate MIDI I/O. |
| DSP | `librosa`, `numpy`, `scipy` | Onset detection, CQT, resampling. |
| Metrics | `mir_eval` | Standard transcription metrics. Do not invent your own. |
| Data contract | `pydantic` v2 | Stage inputs/outputs are validated models. |
| Config | `pydantic-settings` + YAML | One config object threaded through the pipeline. |
| Tests | `pytest`, `pytest-benchmark` | |
| Lint/format | `ruff` | Single tool, fast. |
| UI | `gradio` | Required if you want ZeroGPU on Hugging Face later. |

**Important install note:** `beat_this` only needs `madmom` for DBN post-processing.
We deliberately don't use the DBN (its tempo-continuity prior actively hurts on
expressive jazz), so **skip madmom entirely**. This dodges the single most painful
dependency in the MIR ecosystem — madmom's PyPI build is broken on modern Python.

---

## 3. Architecture

A linear pipeline of **pure, independently testable stages**. Each stage takes a
typed document plus config and returns an updated document. No stage touches global
state; no stage knows about any other stage's internals.

```
                 ┌──────────────────────────────────────────────┐
   audio file →  │ 0. Ingest      → AudioRef                    │
                 │ 1. Separate    → Stems (drums/bass/other/voc)│
                 │ 2. BeatTrack   → BeatGrid (beats, downbeats) │
                 │ 3. Transcribe  → NoteEvents (per stem)       │
                 │ 4. SwingModel  → SwingProfile (BUR per span) │
                 │ 5. Quantize    → QuantizedNotes (grid-snapped)│
                 │ 6. Notate      → Score (music21)             │
                 │ 7. Export      → .musicxml / .mid / .json    │
                 └──────────────────────────────────────────────┘
```

### The data contract

Everything hangs off one document. This is the most important design decision in the
project — get it right and Claude Code can work on any single stage in isolation.

```python
# swingscribe/model.py
from pydantic import BaseModel


class NoteEvent(BaseModel):
    onset: float  # seconds, as performed
    duration: float  # seconds, as performed
    pitch: int  # MIDI note number
    confidence: float
    source: str  # which stem/model produced it


class BeatGrid(BaseModel):
    beats: list[float]  # seconds
    downbeats: list[float]  # subset of beats
    beats_per_bar: int


class SwingSpan(BaseModel):
    start_beat: int
    end_beat: int
    bur: float  # beat-upbeat ratio; 1.0 = straight, 2.0 = triplet swing
    confidence: float
    is_swung: bool


class QuantizedNote(BaseModel):
    bar: int
    beat: float  # position within bar, in straight-eighth grid units
    duration_beats: float
    pitch: int
    timing_residual: float  # microtiming AFTER swing removal — the expressive layer


class Document(BaseModel):
    audio_path: str
    sample_rate: int
    stems: dict[str, str] = {}  # stem name → wav path
    beat_grid: BeatGrid | None = None
    notes: dict[str, list[NoteEvent]] = {}
    swing: list[SwingSpan] = []
    quantized: dict[str, list[QuantizedNote]] = {}
```

Note `timing_residual` — that's the expressive-timing layer, preserved rather than
discarded. It's the interesting research output and costs nothing to keep.

### Caching

Separation and transcription are slow. Cache every stage output on disk, keyed by a
**chained** content hash:

```
root_key  = sha256(audio_bytes)
stage_key = sha256(upstream_key + stage_name + canonical_json(stage_config))
```

Each stage's key folds in the key of the stage that produced its input, so the key
transitively encodes the audio and every upstream stage's config. A flat scheme —
`sha256(audio_bytes + stage_name + stage_config)` — has a staleness hole: change the
*separation* config and the *transcribe* key doesn't change, so transcription silently
returns a hit computed from the old stems. Chaining makes any upstream change
invalidate everything downstream, while a downstream-only tweak still reuses upstream
work: re-running the pipeline after tweaking only the quantizer must not re-run Demucs.

`canonical_json` means deterministic serialization (sorted keys, fixed separators) —
dict ordering must never change a key.

Implement this in M0, not later — retrofitting caching is miserable and you'll be
running this loop thousands of times.

---

## 4. Repo layout

```
swingscribe/
├── pyproject.toml
├── CLAUDE.md                    # working notes for Claude Code (see §9)
├── README.md
├── config/
│   └── default.yaml
├── src/swingscribe/
│   ├── model.py                 # pydantic document + stage types
│   ├── config.py
│   ├── cache.py
│   ├── cli.py
│   ├── pipeline.py              # orchestration only, no logic
│   └── stages/
│       ├── ingest.py
│       ├── separate.py
│       ├── beats.py
│       ├── transcribe.py
│       ├── swing.py             # ← the interesting one
│       ├── quantize.py
│       ├── notate.py
│       └── export.py
├── tests/
│   ├── synthetic/               # generator scripts — audio is RENDERED, never stored
│   ├── regression/
│   │   └── baselines.json       # ← pinned metrics only, diffed per commit
│   └── fixtures/
│       └── manifest.yaml        # names + checksums. NO AUDIO, EVER. See §12.
├── eval/
│   ├── wjazzd.py                # dataset loader
│   ├── run_eval.py
│   └── report.py
└── ui/
    └── app.py                   # gradio
```

---

## 5. Stage specifications

### Stage 1 — Separate
- `htdemucs_ft` via the `demucs` Python API (not subprocess).
- Output 4 stems to the cache dir as 44.1kHz wav.
- Config flag for model name so BS-Roformer can be swapped in later.
- **Acceptance:** stems audibly correct on a test track; bass and drums clean.

### Stage 2 — BeatTrack
- Run `beat_this` on the **drum stem**, not the full mix. The ride cymbal is the
  cleanest beat reference in jazz, and you already have it isolated.
- Fall back to full mix if the drum stem is empty/quiet.
- Emit a tempo curve (local BPM per beat), not a single global tempo.
- **Sanity check to build early:** render a click track at the detected beats, mix it
  against the original at low level, and listen. Beat-tracking bugs are instantly
  audible and nearly invisible in the numbers.
- **Known failure modes to guard against:** octave errors (half/double tempo) and
  continuity drift. Log the tempo curve's variance and flag outliers.
- **Acceptance:** click track lines up by ear on 10 test tracks across tempos.

### Stage 3 — Transcribe
Three paths behind one interface, selected by an `--ensemble` config flag:

| `--ensemble` | Routing | Expected quality |
|---|---|---|
| `horn-led` | Monophonic path on the lead stem | Good |
| `trio` | Piano path on the "other" stem (bass/drums removed cleanly) | Very good |
| `solo-piano` | Piano path on the raw audio, separation skipped entirely | Best |

- **Monophonic** (horns, bass): pYIN or CREPE for f0, onset detection from the stem,
  note segmentation. Accurate, cheap, well understood.
- **Piano**: a dedicated polyphonic piano model (`transkun`). Do **not** use the
  monophonic path for piano — these models handle full polyphony by design, and solo
  piano is the single most-solved task in the field (F1 above 0.97 on MAESTRO).
  Block chords and dense voicings are fine. Two things to handle explicitly:
  - **Sustain pedal** blurs note offsets. Durations will run long. Use a model with
    explicit pedal handling and expect to post-process offsets.
  - **Out-of-distribution decay.** MAESTRO is pristine Disklavier recordings. A 1957
    session on a mediocre upright in mono will land well below the headline numbers.
    Don't quote benchmark figures to users; measure on your own regression set.
- **Multi-instrument** (optional): MuScriptor on the mix. Keep it behind a plugin
  boundary with its own extras group (`pip install swingscribe[muscriptor]`) so the
  NC license never contaminates the core package.
- **Acceptance:** ≥0.75 onset F1 on WJazzD sax solos, ≥0.90 on solo piano
  (mir_eval, 50ms tolerance).

### Stage 4 — SwingModel ★ the heart of the project
```
for each onset:
    b = index of enclosing beat
    φ = (onset - beats[b]) / (beats[b+1] - beats[b])

collect φ for onsets in the offbeat region (0.35 < φ < 0.85)
over a sliding window of N beats (start with N=16):
    histogram φ, find the dominant peak φ*
    BUR = φ* / (1 - φ*)
    classify: is_swung = (φ* > 0.55) and (peak is well-separated)
```
- BUR is **not** constant. It widens at slow tempos and narrows toward 1.0 in fast
  bebop. Estimate per-window and emit a `SwingSpan` sequence, not one number.
- **Hypothesis worth testing:** the short note's *absolute* duration stays roughly
  constant (~100ms) regardless of tempo, which would explain the whole tempo/BUR
  relationship. You can test this directly against your own collection — and it's a
  publishable-quality result if it holds.
- Straight sections must be detected, not assumed. Plenty of Shorter is even-eighths.
- **Acceptance:** on synthetic audio with injected BUR, recover it within ±5%.

### Stage 5 — Quantize
- Warp φ through a piecewise-linear map sending φ* → 0.5, then snap to the straight
  grid (16th-note resolution).
- Store the pre-snap deviation as `timing_residual`.
- Handle triplets explicitly — post-warp, a genuine triplet figure and a swung eighth
  pair are dangerously similar. Use duration context to disambiguate.
- **Acceptance:** round-trip test — quantize → re-render with swing applied → onsets
  land within 20ms of the original.

### Stage 6 — Notate
- Key detection (Krumhansl or music21's analyzer), then enharmonic spelling. Jazz
  spelling conventions matter: a bebop line will look wrong with naive spelling.
- Bar/measure assembly from downbeats; pickup bar handling.
- Add "Swing" tempo text; write eighths straight.
- Transposing instruments: alto sax is in E♭, tenor/trumpet in B♭. Config-driven.
- **Acceptance:** output opens cleanly in MuseScore with no import warnings.

---

## 6. Test strategy

Three layers. Layer 1 runs on every commit; layer 2 nightly or pre-merge; layer 3 by hand.

### Layer 1 — Synthetic (fast, exact ground truth)
Generate MIDI with a **known** injected swing ratio, render through a soundfont
(FluidSynth), run the pipeline, assert recovery. This is the only place you get exact
answers, so it carries the unit-test load.

Parametrize over: BUR ∈ {1.0, 1.3, 1.6, 2.0, 2.5}, tempo ∈ {80, 120, 180, 260},
instrument, and added noise/reverb. Roughly 200 cases, seconds to run.

### Layer 2 — WJazzD regression set
The Weimar Jazz Database: 456 solo transcriptions from 340 tracks, manually annotated,
**time-aligned to the original audio**, with beat positions included. They publish
unquantized MIDI — the microtiming is preserved, which is exactly what you need and
exactly what the Omnibook lacks.

- Pick ~20 solos spanning eras, tempos, and instruments. Include at least 4 piano
  solos — WJazzD covers pianists, and the piano path has different failure modes
  (offset smear from pedaling) that horn fixtures won't surface.
- Score with `mir_eval`: onset F1 (50ms), pitch accuracy (50 cents), plus your own
  BUR error.
- **Pin the numbers in `tests/regression/baselines.json` and diff per commit.** Tuning
  MIR pipelines is whack-a-mole; without a tracked number you will not notice the mole.

### Layer 3 — Omnibook acceptance (manual)
Useful for the *notation* layer only. The Omnibook is written in straight eighths with
swing implied — it is the **target output** of your warping step, not ground truth for
timing. It cannot validate the swing estimator; the answer has already been erased.

Two traps: **take-matching** (multiple issued takes exist for most Parker sides — the
wrong take makes your eval pure noise) and **editorial interpretation** (ghost notes
dropped, enharmonics normalized — disagreement isn't automatically your bug). It's
under copyright, so keep fixtures local and out of the public repo.

### The ear test (build this in M2, use it forever)
Render the transcription back to audio, then produce a stereo file with the **original
on the left channel and your transcription on the right**. Thirty seconds of listening
reveals more than a page of metrics. Make it a CLI subcommand.

---

## 7. Milestones

Each milestone ends with something that visibly works. Resist the urge to build the
whole pipeline before running any of it.

| # | Deliverable | Acceptance |
|---|---|---|
| **M0** | Skeleton: repo, config, document model, cache layer, CI, ruff | `pytest` green on an empty suite; cache hit/miss works |
| **M1** | Ingest + Separate | CLI produces 4 stems from an mp3 |
| **M2** | BeatTrack + click-track renderer + ear-test command | Click lines up by ear on 10 tracks |
| **M3** | Monophonic transcription of one horn → MIDI | MIDI opens and sounds like the solo |
| **M4** | **SwingModel + Layer-1 synthetic suite** | Recovers injected BUR within ±5% |
| **M5** | Quantize + Notate + Export | MusicXML opens in MuseScore, swing marking present |
| **M6** | WJazzD eval harness + pinned baselines | `python -m eval.run_eval` prints a scorecard |
| **M7** | Bass line path | Walking bass transcribed at ≥0.8 onset F1 |
| **M7b** | Piano path + `--ensemble` routing | Solo piano ≥0.90 onset F1; trio piano usable |
| **M8** | Gradio UI (local) | Drag audio in, get MusicXML out, in a browser |
| **M9** | Hugging Face Space | Public URL, ZeroGPU, someone else uses it |
| M10 | *(optional)* MuScriptor multi-instrument path | Behind an extras flag |

M4 is the milestone that makes this project yours rather than a wrapper around other
people's models. Don't let it slip behind polish work.

---

## 8. Windows setup notes

```powershell
# 1. Install uv
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Project init
uv init swingscribe && cd swingscribe
uv python pin 3.11

# 3. Torch with CUDA — must come from the CUDA index, not PyPI default
uv add torch torchaudio --index https://download.pytorch.org/whl/cu124

# 4. Core deps
uv add demucs librosa pretty_midi music21 mir_eval pydantic pydantic-settings gradio
uv add --dev pytest ruff

# 5. beat_this (no madmom — we don't use the DBN)
uv add git+https://github.com/CPJKU/beat_this
```

Gotchas:
- **ffmpeg must be on PATH** or mp3 decoding fails cryptically. `winget install ffmpeg`.
- Model weights are multi-GB and cache to `%USERPROFILE%\.cache`. Point `HF_HOME` and
  `TORCH_HOME` at a drive with room.
- Windows' 260-char path limit bites with deep cache dirs — enable long paths.
- Verify `torch.cuda.is_available()` before anything else. Silent CPU fallback turns a
  20-second job into 15 minutes and you won't notice until you're debugging the wrong thing.

---

## 9. CLAUDE.md starter

Put this at the repo root so every Claude Code session starts oriented:

```markdown
# SwingScribe

Jazz audio → swing-aware MusicXML. Python 3.11, uv, PyTorch.

## Architecture
Linear pipeline of pure stages in src/swingscribe/stages/. Each takes
(Document, Config) → Document. Stages never import each other. All shared types
live in model.py.

## Rules
- Never add a dependency without asking.
- Never modify model.py without flagging the migration impact on cached artifacts.
- Every stage change requires a corresponding test in tests/.
- Do not run the full pipeline to test one stage — use cached fixtures.
- mir_eval is the source of truth for metrics. Don't hand-roll scoring.
- Baselines in tests/regression/baselines.json are sacred. If a change moves them,
  say so explicitly and explain why.

## Current milestone
M0 — see swingscribe-plan.md §7.
```

**How to drive Claude Code on this:** work one stage at a time, in milestone order,
and make it write the test before the implementation. The pipeline is deliberately
structured so a single stage fits comfortably in context. Asking it to build the whole
thing at once will produce something that runs and is wrong in ways the tests won't catch.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Beat tracker fails on rubato intros / ballads | Detect low confidence, allow manual tempo hint via CLI |
| Separation smears horns together (they share the "other" stem) | v1 targets *one* lead line; use `--lead-instrument` hint, and try BS-Roformer |
| Notation output is technically correct but ugly | Budget real time for music21 spelling and beaming rules; test in MuseScore constantly |
| Scope creep into piano *comping* | Solos are in, comping is out. The line is whether the piano is foreground. |
| Piano output is a single-staff wall of notes | Accept it for v1. Grand-staff splitting is its own project. |
| Piano model trained on clean recordings underperforms on 1950s sessions | Measure on your own set; don't trust MAESTRO numbers |
| MuScriptor NC license leaks into the core package | Separate extras group, separate module, documented |
| Motivation dip at M6 (eval harness isn't fun) | Do M5 first so you have pretty output to look at while grinding through metrics |

---

## 11. Licensing

- Your code: MIT.
- Demucs: MIT — fine.
- beat_this, librosa, music21, mir_eval: permissive — fine.
- **MuScriptor weights: CC BY-NC 4.0** — non-commercial only. Isolated in an optional
  extras group. Keeps the core package clean and monetizable later if you ever change
  your mind.
- WJazzD: cite Pfleiderer et al. 2017 in the README.
- Parker Omnibook: copyrighted. Local fixtures only, never committed.

---

## 12. Test fixtures & audio handling

**Rule zero: no copyrighted audio in the repository. Not once. Not in a private repo.**

Git history is permanent. A file committed today and deleted tomorrow is still in the
history and trivially recoverable — and if the repo ever goes public, so does it.
`.gitignore` the fixtures path in your *first* commit, before any audio exists on disk
near the working tree.

### The three fixture tiers

| Tier | Source | Lives where | Runs in CI |
|---|---|---|---|
| 1. Synthetic | Generated at test time from MIDI + soundfont | Generator committed, audio never stored | Yes |
| 2. WJazzD | Public annotations + your own copies of the recordings | Manifest committed, audio local | No |
| 3. Personal library | Your mp3 collection | Manifest committed, audio local | No |

**Tier 1 is generated, not stored.** Commit `tests/synthetic/generate.py` and a fixed
seed; the suite renders its own audio at run time. Fixtures stay in sync with the
generator by construction, and there's nothing to license. Don't commit the soundfont
either — they run into the hundreds of MB. Fetch it in `scripts/setup_fixtures.py`,
and pick a permissively licensed one.

**Tier 2 needs the manifest pattern regardless of your library.** WJazzD ships
transcriptions, *not* audio — the annotations are time-aligned to commercial recordings
users are expected to own separately. So even the public dataset requires a
bring-your-own-audio mechanism.

### The mechanism

```yaml
# tests/fixtures/manifest.yaml — committed
fixtures:
  - id: parker_koko_1945
    filename: "koko.mp3"
    sha256: "a3f1..."          # verify the right take
    tier: 3
    ensemble: horn-led
    expected_tempo_bpm: 300
```

```python
# tests/conftest.py
FIXTURE_DIR = os.environ.get("SWINGSCRIBE_FIXTURES")

requires_audio = pytest.mark.skipif(
    not FIXTURE_DIR,
    reason="Set SWINGSCRIBE_FIXTURES to a local audio directory (see §12)",
)
```

- Audio lives in a directory **outside the repo tree**, pointed at by
  `SWINGSCRIBE_FIXTURES`.
- Tests verify the SHA-256 against the manifest before running. This catches the
  take-matching problem from §6 — the wrong take of a Parker side silently turns your
  eval into noise, and a checksum turns that into a loud failure.
- CI runs tier 1 only. A fresh clone runs the full synthetic suite immediately and opts
  into the rest by supplying audio.

### What derived artifacts may be committed

A complete note-level MIDI transcription of a copyrighted recording is plausibly a
derivative work. Keep the line here:

- **Commit:** aggregate metrics — onset F1, pitch accuracy, BUR error, tempo estimates.
  These are facts about your software's behavior.
- **Don't commit:** note lists, MIDI, or MusicXML derived from commercial recordings.
  Those are closer to a copy of the performance.

`baselines.json` holds scores, never note data.

### Public-domain audio for the demo and CI

Under the Music Modernization Act, US sound recordings from 1925 entered the public
domain on 1 January 2026 — including the first Louis Armstrong Hot Five sessions and
Bessie Smith's "St. Louis Blues" with Armstrong. The line advances one year every
1 January (1926 recordings in 2027, and so on).

This gives you real jazz you can commit outright: good for the README demo, the
Hugging Face Space landing example, and a CI smoke test that exercises the full
pipeline on genuine audio.

Two caveats. These are noisy 1925 electrical recordings, and rhythmically they're
closer to two-beat than to bebop swing — so they're demo material, not a serious
regression benchmark for the swing model. And none of this is legal advice; verify
the status of anything you plan to redistribute.

**Source:** the Library of Congress National Jukebox and the Discography of American
Historical Recordings (UCSB) both host digitized public-domain recordings.
