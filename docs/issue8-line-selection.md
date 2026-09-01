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

## Not integrated — the listener decides the shape

Options, not yet chosen: (a) dp line replaces the CREPE line for
`uses_piano_oracle` ensembles, with CREPE demoted to the corroborating
second opinion (the exact inverse of today's roles); (b) dp line offered in
the GUI as an alternative take beside the CREPE line; (c) keep shipping
CREPE and use the dp line only to SHADE review-screen confidence. M7b's
history says the oracle-as-primary failed on PICKING, and picking is what
just improved — but (a) changes every piano default and the erasure-label
covenant (302 labels were judged against CREPE lines) needs an explicit
migration story first.
