# Developing SwingScribe

The README is the front door and the [user guide](../src/swingscribe/gui/guide/user-guide.md)
is for people using the app. This page is for people working on it: setting
up, running the tests, and scoring the pipeline against the benchmarks.
`CLAUDE.md` holds the working notes on the architecture and the decisions
behind it; `swingscribe-plan.md` is the plan.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11.

```
uv sync --group ml --group gui --group batch --group roformer
```

Name every group every time: `uv sync` uninstalls whatever the named groups
do not require. The heavy machine-learning dependencies live in `ml`, the
web app's in `gui`, the WJazzD batch tooling's in `batch`, and the
BS-RoFormer separator's in `roformer`. Plain `uv sync` — what CI runs —
installs none of them, which is why every stage module imports its heavy
libraries lazily.

Separation and transcription download model weights (about 300 MB) on
first use. Without a CUDA GPU they run on the CPU: expect minutes, not
seconds, for a whole track.

## Running the tests

```
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`uv run pytest` runs the tier-1 tests: synthetic audio and unit tests, all
of which run in CI on Ubuntu and Windows. Tests that need the `ml` group
skip without it; tests that download model weights are gated behind
`SWINGSCRIBE_HEAVY_TESTS=1` so a routine run stays fast.

Audio never lives in this repository. Tests that need real recordings skip
unless `SWINGSCRIBE_FIXTURES` points at a local audio directory, and the
files are checksum-verified against `tests/fixtures/manifest.yaml` so a
wrong take fails loudly rather than quietly.

The tier-1 synthetic suite renders its own audio, so it needs no fixtures —
but its *realistic* half renders through a soundfont, which is fetched
rather than committed:

```
uv run python scripts/setup_fixtures.py
$env:SWINGSCRIBE_HEAVY_TESTS = "1"
uv run pytest tests/test_synthetic.py
```

That downloads GeneralUser GS and the FluidSynth CLI to a directory outside
the repo and prints where. Without them the soundfont cases skip; the
additive ones still run.

## Measuring: two benchmarks, two questions

There are two benchmarks, and they answer different questions. Confusing
them is the most expensive mistake this project has made; the full story is
in `docs/benchmark-deficiencies.md`. One command runs everything:

```
uv run python scripts/run_eval.py --db wjazz/wjazzd.db
```

- **WJazzD** (`scripts/score_wjazz.py`) is audio against audio: a human's
  per-note onsets in seconds for the same recording. It asks *did we hear
  what was played?* and is the right measure of transcription.
- **MuseScore** (`scripts/score_benchmark.py`) is audio against notation:
  the hand transcriptions in `benchmark/`. It asks *would this notate the
  way a human notated it?* It charges the gap between performed timing and
  notated rhythm to the transcriber, so it reads lower and always will.

The Weimar Jazz Database is ODbL and lives outside the repo (see
`docs/wjazzd.md`); only aggregate numbers may be committed.

## Batch-scoring the WJazzD solos

`scripts/wjazz_batch.py` runs the whole GUI workflow over the audio in
`benchmark/wjazzd/` without a browser — locate the solo, separate, track
beats, transcribe, export MusicXML, score against the hand transcript — and
records every result in `benchmark/wjazzd/wjazzd_benchmark_test.xlsx`.

```
uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db --all
```

Run it from the repository root. Pick what to process with `--all`,
`--limit N` (first N by filename), `--random N`, or `--file NAME`
(repeatable). Start with one tune — a solo that has never been separated
costs minutes of CPU, and everything after that is cached.

**Close the spreadsheet in Excel before running.** Excel takes an exclusive
lock; the script writes after every tune so an interruption never loses
finished work. It only touches rows for the solos in *this* run; every other
row is left exactly as it was. Nothing here may be committed — `benchmark/`
is gitignored in full.

### What the columns mean

The sheet has one row per WJazzD solo (all 456, most blank because there is
no audio for them here). Beyond the identifying columns and the settings
actually used (`separation_model`, `ensemble`, the located
`solo_start`/`solo_end`), there are **two different measures**:

| column | meaning |
|---|---|
| `notes` | how many notes **we** transcribed |
| `notation_reference` | how many notes are in the **hand transcript** |
| `pitch_f1`, `pitch_matched`, `pitch_wrong`, `pitch_invented`, `pitch_missed` | the GUI's ground-truth bar |
| `notation_rhythm`, `notation_value`, `notation_coverage`, `notation_matched` | the GUI's **Score it** button |

**`pitch_*` asks: did we hear the right notes?** It is time-free and
pitch-only. Every note we emitted is `matched` (right pitch), `wrong` (a
note there, wrong pitch) or `invented` (nothing there at all); every note of
theirs we had nothing for is `missed`. The counts add up both ways —
`matched + wrong + missed` is their note count, `matched + wrong + invented`
is ours — which is the check that nothing is being miscounted.

**`notation_*` asks a harder question: are those notes *written* the way a
human wrote them?** It charges the gap between performed timing and notated
rhythm, so it matches fewer notes and reads lower than `pitch_f1` — always.
That is expected, not a regression.

Two warnings about reading these:

- **Never read `notation_rhythm` without `notation_coverage` beside it.**
  Coverage is how much of the hand transcript ours accounted for. Below
  about 0.5 the pairing is not trustworthy: two eighth-note bebop lines
  agree about most gaps by chance, so a *wrong* pairing can still read 0.58
  on rhythm. The `status` column says so when coverage is low.
- **`notation_value` is the one number to read sceptically.** The hand
  transcripts here are rendered from WJazzD's metrical annotation, and while
  the positions and pitches are a human's, the note *values* are our own
  conventions applied to that human's grid — so it partly scores us against
  ourselves. `scripts/run_eval.py` omits it deliberately.

The numbers are the GUI's own: the script calls the same functions the
Transcribe, Export and Score buttons call, and leaves its transcription in
the GUI's cache. Open a scored track afterwards and the notes are already
there, and **Score it** reports what is in the spreadsheet.

## Windows notes

Windows Smart App Control refuses the `swingscribe.exe` console-script stub
that pip generates at install time (`os error 4551`). Run the module
instead — `uv run python -m swingscribe <command>` or the `.\swingscribe`
shim beside `pyproject.toml`. The user guide's troubleshooting section has
the details, and `CLAUDE.md` has the rest of this machine's traps: TLS
interception, OneDrive and uv, and the numba block that rules out librosa.
