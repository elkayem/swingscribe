# Issue #8 — melodic-line selection: the sequence view works

2026-09-01. The experiment the M7b handoff pointed at, run over cached data
while the listener was away. Instrument: `scripts/line_selection.py`.

## The question

Piano's error class is following the wrong voice: wrong-pitch dominates
(Soul Station: 66 wrong against 125 matched), and M7b measured that the
oracle's top-2-per-cluster CONTAINS the human's note 93–96% of the time.
Every prior attempt picked per cluster in isolation (highest, loudest).
Nobody had treated the line as a SEQUENCE.

## Method

The piano oracle's full polyphonic output (onset, pitch, velocity) for all
ten piano spans — six hand-scored, four WJazzD — extracted once (~8 min;
`--extract`). Notes cluster at 50 ms onset gaps. A strategy picks at most
one note per cluster; every strategy is scored the same way the green bar
scores the shipped line (pitch-sequence alignment, raw notes, D20).

The winning strategy is a small Viterbi:

- **emission** = the note's velocity as a WITHIN-TRACK PERCENTILE RANK;
- **transition** = a register-continuity cost per semitone from the last
  emitted note, capped at an octave (phrase-start leaps are legitimate);
- **skip**: emitting must beat skipping by a margin, so a quiet left-hand
  comp between phrases emits nothing.

## Results (F1 against the reference melody, per track)

| track | shipped | loudest | dp (w=.02, m=.10) | top-2 ceiling recall |
|---|---|---|---|---|
| Carl Perkins – For Minors Only | 0.788 | 0.848 | 0.846 | 0.953 |
| Hancock – Dolores | 0.865 | 0.866 | **0.948** | 0.972 |
| Hancock – Gingerbread Boy | 0.830 | 0.848 | **0.940** | 0.949 |
| Hancock – Orbits | 0.946 | **0.978** | 0.926 | 0.987 |
| Peterson – Lover Come Back | 0.756 | 0.704 | **0.795** | 0.945 |
| Red Garland – Oleo | 0.790 | 0.870 | 0.865 | 0.932 |
| Sonny Clark – Melody For C | 0.806 | 0.796 | **0.867** | 0.955 |
| Sonny Clark – There Will Never | 0.884 | 0.797 | **0.910** | 0.969 |
| Flanagan – Giant Steps | 0.794 | 0.865 | **0.921** | 0.964 |
| Wynton Kelly – Soul Station | 0.559 | 0.533 | **0.637** | 0.915 |
| **mean** | **0.8017** | 0.8104 | **0.8655** | — |

Wrong-pitch totals: shipped 344 → dp 199. The dp line beats or matches the
shipped line on 9 of 10 tracks (Orbits −0.020 is the one dip) and lifts the
WORST track (+0.078; neighbouring grid points lift the minimum further, to
0.699 at m=.35, trading mean for floor).

## The three findings that made it work, in order of importance

1. **Per-track velocity normalization.** Absolute MIDI velocities do not
   transfer between recordings — the model's loudness scale rides the mix —
   so a fixed skip margin over-skips one track and under-skips another.
   Percentile-rank velocities unified the grid: after normalization EVERY
   dp variant beat the shipped mean.
2. **The skip state.** A forced one-note-per-cluster line gets dragged
   through comping. Skipping must be a first-class outcome.
3. **The ceiling is high EVERYWHERE — Soul Station included** (top-2 recall
   0.915, ONE reference note absent from the oracle's clusters). Selection
   is the entire piano problem; the oracle's hearing is not the limit even
   on the set's worst track.

## Caveats, on the record

- Ten tracks, a 9-point grid: some overfit risk. Mitigation: the surface is
  smooth (0.83–0.87 across w ≤ 0.05), the win is broad (9/10), and the two
  weights have physical readings (a semitone of leap costs ~2 percentile
  points of loudness; a note must beat silence by 10 points).
- This measures the pitch question only. Rhythm/notation impact of swapping
  the line source is unmeasured, as is behaviour against WJazzD's
  audio-vs-audio measure.
- The oracle notes' DURATIONS are the model's own; the shipped line's
  duration conventions (without_overlap etc.) would still apply downstream.

## Integrated as a second take (2026-09-02)

The picker ships as `swingscribe.line_selection` behind
`TranscribeConfig.piano_line`: `"crepe"` (the default, unchanged) or
`"oracle"`, the line above. The GUI's review screen offers the choice as a
**Line** picker for pianist ensembles only, so the listener can transcribe
the same span both ways and compare them by ear, with every downstream
control — erasures, the green bar, the Score button, export — working on
whichever take is on screen. That is shape (b); shape (a) is the same code
with the default flipped, and it waits on what the comparison finds and on
the two unmeasured questions: notation scores and WJazzD's audio measure.

What the `"oracle"` take applies: `pick_line` alone. CREPE's notes are set
aside rather than demoted to a second opinion, and the register floor
(`reject_line_outliers`) is skipped, because neither combination was
measured — the 0.8655 is the picker by itself. `scripts/line_selection.py`
imports the shipped picker, so the instrument and the product cannot drift.

The default keys exactly as it did before the field existed
(`TranscribeConfig`'s serializer leaves the line fields out of the dump for
`"crepe"`), so no cached review or batch note-cache became a miss for a
change that alters no note. The oracle take keys differently, as it must.

An erasure now records which line it was judged on (`line` in the sidecar
record). Erasures made on the CREPE line will mostly fail to match the
oracle take — the onsets are the model's own — and are reported as
unmatched, never dropped (gui/erasures.py).

Shape (c), shading review confidence, was not built: the picked note's
confidence IS its loudness rank, so the shading comes for free on the
oracle take.

## The onset lead (2026-09-07)

The second reading of the error taxonomy (`docs/error-taxonomy-review.md`,
3b.2) scored the picker against WJazzD's onsets rather than the time-free
pitch alignment above, and it LOST to the shipped line on all four pianists
(mean note F1 0.860 against 0.895) — not on pitch but on time. The model's
matched onsets sit 16-24 ms early on every solo (median per solo; CREPE's
line on the same stems reads 0 to -9 ms), and the benchmark's 50 ms
tolerance turned that lead into a hundred timing errors.

`pick_line` now moves every picked onset late by `ONSET_SHIFT_S` (20 ms, the
measured median lead; `TranscribeConfig.piano_line_onset_shift_ms`). With a
constant +20 ms the picker reads 0.900 on the four and beats the shipped
line on three of them; +25 ms reads 0.905 and was not taken, being tuned on
four solos. The field dumps only for the oracle take, like the other line
fields, so no default-path key moved; the oracle take keys differently and
a cached oracle review is recomputed once. `corroborate.fill_gaps` copies
oracle onsets into the DEFAULT piano line unshifted; that is the part left
for the next bundled re-transcription, because it would re-fingerprint the
note cache.

The default piano line carries the same shift since the 2026-09-07 overnight
run: `corroborate.fill_gaps` moves every oracle note it copies late by
`ONSET_SHIFT_S`, under `transcribe.CACHE_VERSION` 2. Paired over the four
WJazzD pianists it read note F1 0.8949 → 0.9042, all four up (with
`pitch_persist_ms` 40 landing in the same run; the horns moved +0.0030), and
`absorbed` + `squeezed` on the pianists went 222 → 187. See
docs/error-taxonomy-review.md section 7.

## The notation side, measured (2026-09-10)

The reason the oracle take stayed a second take was that only the pitch
question had been measured. The harness now transcribes every pianist on
BOTH lines (`run_eval.py`: the oracle take is keyed `<track> [line=oracle]`,
pinned per track, and summarised paired over the same tracks), so the
notation question is measured too — against the hand scores as notation,
with the matched count beside every rhythm number. Seven pianists with hand
scores (Red Garland's Billy Boy joined the same day), all on the Roformer's
`piano` stem, the default take's keys untouched:

| pianist | pitch F1 crepe / oracle | note F1 crepe / oracle | rhythm crepe / oracle (matched) |
|---|---|---|---|
| Carl Perkins, For Minors Only | 0.816 / 0.854 | 0.397 / 0.330 | 0.741 / 0.762 (79 / 86) |
| Oscar Peterson, Lover Come Back | 0.791 / 0.845 | 0.370 / 0.399 | 0.722 / 0.808 (363 / 392) |
| Red Garland, Billy Boy | 0.730 / 0.768 | 0.569 / 0.605 | 0.818 / 0.852 (329 / 394) |
| Sonny Clark, Melody for C | 0.831 / 0.876 | 0.527 / 0.562 | 0.755 / 0.774 (516 / 548) |
| Sonny Clark, There Will Never Be | 0.932 / 0.922 | 0.664 / 0.700 | 0.785 / 0.897 (303 / 299) |
| Tommy Flanagan, Giant Steps | 0.816 / 0.895 | 0.614 / 0.679 | 0.848 / 0.859 (268 / 298) |
| Wynton Kelly, Soul Station | 0.599 / 0.707 | 0.263 / 0.333 | 0.795 / 0.818 (125 / 157) |
| **mean over 7** | **0.788 / 0.838** | **0.486 / 0.515** | **0.780 / 0.824** |

The oracle take wins pitch on six of seven (the exception is the one
Sonny Clark solo already at 0.93), note F1 on six (Carl Perkins' 17-second
span is the exception), and notated rhythm on all seven, with more notes
lined up on every one but that same Sonny Clark. Audio against audio it is
level: WJazzD note F1 0.904 → 0.898 over the four WJazzD pianists, which is
the onset lead of the section above, corrected. Soul Station is the
clearest case of what the picker fixes: a third of its matched positions
were at the wrong pitch on the CREPE line (the left hand), and the oracle
take moves its pitch F1 0.599 → 0.707.

**What this decides.** Every question that was open when the picker shipped
as a second take is now measured, and it wins or ties on each. Making
`piano_line = "oracle"` the pianist default is a pipeline default change:
it re-fingerprints every piano transcription (the oracle take's keys
already exist in both caches, so the cost is the sidecars' and the
baselines', not CREPE's), moves the pinned piano numbers, and changes what
the Transcribe button produces for a trio. It is not taken here; it is the
listener's call, on this table.
