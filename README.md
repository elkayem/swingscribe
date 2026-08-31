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

## The GUI

```
uv run swingscribe gui
```

Opens the selection and audition app on `127.0.0.1:8420` (plan §13, screens 1-3):
load a track, drag out the span of one solo on a two-tier waveform, pick the stem
carrying it, and listen to the isolated instrument looped over that span before
spending anything on transcription. It shows which separation models are already
cached and runs the missing one as a background job with real progress. The
audition screen mixes every stem sample-locked, so switching between the isolated
stem and the original mix mid-phrase compares the same instant.

It also draws the bar grid over the waveform — bar lines, bar numbers, chorus
markers, and snap-to-bar for placing loop points — so you can see whether the
grid the transcription will quantize against actually matches the tune before
running anything. Bars are derived by counting beats from a downbeat you can
move with one click (or `D`), the time signature is a menu, beats the tracker
missed are drawn as hollow stubs, and passages with no steady pulse get no bars
at all. Press `F` (or shift-click a bar line) to say where the tune's *form* starts, so
an intro isn't counted: that bar becomes bar 1, the chorus count starts there,
and the bars before it are drawn faint and unnumbered. Your choices travel into the pipeline as `--time-signature`,
`--downbeat` and `--bars-per-chorus`.

Turn on **Click** to hear a metronome on the bar grid while you audition — a bar
line one beat out is unmistakable by ear and easy to miss on screen.

Your settings for a track (span, stem, model, time signature, downbeat, form
start) are saved beside the audio as `<track>.swingscribe.json`, not in the
cache: clearing derived data should never cost you a judgement you had to listen
for. Reopening the track restores where you were.

It hands off to the CLI: the exact `swingscribe ab …` command for the span and
stem you settled on, plus a download of the isolated span. Needs the `gui`
dependency group (`uv sync --group ml --group gui`).

The two ear tests (plan §6): `swingscribe click <file>` writes the music with
clicks at the detected beats, and `swingscribe ab <file>` writes a stereo wav
— original left, rendered transcription right — plus the transcribed MIDI. Stage outputs are cached, so re-runs are instant. No
transcription or notation yet. See `swingscribe-plan.md` for the milestones.

Separation needs the ML dependency group (`uv sync --group ml`) and downloads
model weights (~300 MB) on first run. Without a CUDA GPU it runs on CPU —
expect minutes, not seconds, for a full track.

## Batch-scoring the WJazzD solos

`scripts/wjazz_batch.py` runs the whole GUI workflow over the audio in
`benchmark/wjazzd/` without a browser — locate the solo, separate, track
beats, transcribe, export MusicXML, score against the hand transcript — and
records every result in `benchmark/wjazzd/wjazzd_benchmark_test.xlsx`.

```
uv sync --group ml --group gui --group batch
uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db --all
```

Run it from the repository root. Pick what to process with `--all`,
`--limit N` (first N by filename), `--random N`, or `--file NAME` (repeatable).
Start with one tune — a solo that has never been separated costs minutes of
CPU, and everything after that is cached.

**Close the spreadsheet in Excel before running.** Excel takes an exclusive
lock; the script writes after every tune so an interruption never loses
finished work.

It only touches rows for the solos in *this* run. Every other row is left
exactly as it was, so you can re-run one tune without disturbing the rest.
Nothing here may be committed — WJazzD is ODbL and `benchmark/` is gitignored
in full.

### What the columns mean

The sheet has one row per WJazzD solo (all 456, most blank because there is no
audio for them here). Beyond the identifying columns and the settings actually
used (`separation_model`, `ensemble`, the located `solo_start`/`solo_end`),
there are **two different measures**, and confusing them is the single most
expensive mistake this project has made:

| column | meaning |
|---|---|
| `notes` | how many notes **we** transcribed |
| `notation_reference` | how many notes are in the **hand transcript** |
| `pitch_f1`, `pitch_matched`, `pitch_wrong`, `pitch_invented`, `pitch_missed` | the GUI's green ground-truth bar |
| `notation_rhythm`, `notation_value`, `notation_coverage`, `notation_matched` | the GUI's **Score it** button |

**`pitch_*` asks: did we hear the right notes?** It is time-free and
pitch-only. Every note we emitted is `matched` (right pitch), `wrong` (a note
there, wrong pitch) or `invented` (nothing there at all); every note of theirs
we had nothing for is `missed`. The counts add up both ways —
`matched + wrong + missed` is their note count, `matched + wrong + invented`
is ours — which is the check that nothing is being miscounted.

**`notation_*` asks a harder question: are those notes *written* the way a
human wrote them?** It charges the gap between performed timing and notated
rhythm, so it matches fewer notes and reads lower than `pitch_f1` — always.
That is expected, not a regression.

Two warnings about reading these:

- **Never read `notation_rhythm` without `notation_coverage` beside it.**
  Coverage is how much of the hand transcript ours accounted for (the GUI's
  "60% lined up"). Below ~0.5 the pairing is not trustworthy: two eighth-note
  bebop lines agree about most gaps by chance, so a *wrong* pairing can still
  read 0.58 on rhythm. The `status` column says so when coverage is low.
- **`notation_value` is the one number to read sceptically.** The hand
  transcripts here are rendered from WJazzD's metrical annotation, and while
  the positions and pitches are a human's, the note *values* are our own
  conventions applied to that human's grid — so it partly scores us against
  ourselves. `scripts/run_eval.py` omits it deliberately; it is carried here
  only so a row matches the GUI line exactly.

The numbers are the GUI's own, not a second opinion about them: the script
calls the same functions the Transcribe, Export and Score buttons call, and
leaves its transcription in the GUI's cache. Open a scored track afterwards
and the notes are already there — no Transcribe click, no second CREPE pass —
and **Score it** reports what is in the spreadsheet.

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

The tier-1 synthetic suite renders its own audio, so it needs no fixtures —
but its *realistic* half renders through a soundfont, which is fetched rather
than committed:

```
uv run python scripts/setup_fixtures.py
$env:SWINGSCRIBE_HEAVY_TESTS = "1"
uv run pytest tests/test_synthetic.py
```

That downloads GeneralUser GS and the FluidSynth CLI to a directory outside
the repo and prints where. Without them the soundfont cases skip; the
additive ones still run.

## Troubleshooting

**Windows Application Control blocks `swingscribe.exe`:** if `uv run
swingscribe <command>` fails with

```
error: Failed to spawn: `swingscribe`
  Caused by: An Application Control policy has blocked this file. (os error 4551)
```

your machine's Application Control policy is blocking the generated
`.venv\Scripts\swingscribe.exe` console-script shim, not the code itself.
Run the module directly instead — `python.exe` isn't blocked, only the stub:

```
uv run python -m swingscribe.cli gui
```

Works for every subcommand (`run`, `click`, `audition`, `ab`, `gui`) — just
swap `gui` for the one you need.

## License

MIT — see `LICENSE`.
