# M3 scored against real transcriptions

First measurement of the pipeline against real music. Everything before this
was either ear judgement or synthetic ground truth, and synthetic ground
truth had stopped being informative — the additive cases all scored ≥0.98.

Reproduce with:

```bash
uv run python scripts/score_benchmark.py
```

Nothing derived from `benchmark/` is committed. This file holds the aggregate
numbers, which is all plan §12 allows.

## What is being measured

Three solos, hand-transcribed in MuseScore, with the span/stem/model chosen
in the GUI and saved to each track's sidecar. The sidecar span *is* the
transcribed span — bar 1 of each score is its start. That cross-checks
independently: the bar counts (129 ≈ 4×32, 73 ≈ 2×36+1, 65 ≈ 4×16+1) and the
implied tempos (187, 194, 249 bpm) are all musically right for these tunes,
and Confirmation's saved downbeat lands on bar 33 to within 0.16 bars.

Two measures, kept apart on purpose:

**Pitch sequence, time-free.** A notated score has no timestamps. Scoring it
in time needs a tempo map, and the only one we have is our own beat tracker —
which would charge beat-tracking error to the transcriber and vice versa,
exactly the confound that made the Confirmation intro investigation
(open-issue #9) so slow. Ignoring time removes it. Needleman-Wunsch on the
pitch sequences; matches, substitutions, insertions and deletions.

**Onset timing, per 4-bar window.** mir_eval, with a constant tempo derived
from bars/span and a per-window constant offset to absorb drift. Rhythm
*within* a window is genuinely tested; rhythm across the solo is not, and
cannot be until M5 gives us a real tempo map. Treat this as a floor.

## Results

| | Confirmation | All The Things | Giant Steps |
|---|---|---|---|
| soloist | Dexter Gordon, tenor | Hank Mobley, tenor | Tommy Flanagan, piano |
| stem | `other` of 6s | `other` of 6s | `other` of ft |
| implied tempo | 187 bpm | 194 bpm | 249 bpm |
| notes produced | 899 (133%) | 445 (106%) | 377 (112%) |
| **pitch F1** | **0.736** | **0.883** | **0.686** |
| precision / recall | 0.64 / 0.86 | 0.86 / 0.91 | 0.65 / 0.73 |
| chroma F1 | 0.741 | 0.883 | 0.773 |
| matched / wrong / invented / missed | 579 / 67 / 253 / 29 | 382 / 17 / 46 / 21 | 245 / 63 / 69 / 29 |
| onset F1 (windowed) | 0.604 | 0.650 | 0.645 |
| note F1 (onset+pitch) | 0.325 | 0.341 | 0.360 |
| drift the fit absorbed | 1.94 s | 0.78 s | 1.56 s |

## What the numbers say

**We are not making a systematic octave error.** The transposition is
measured, not assumed, and it came out **+12 for both tenor solos and 0 for
the piano solo**. That is the control working: the hand transcriptions of the
tenors are written an octave above concert for readability, the piano one is
at true pitch, and our output is at concert pitch throughout. Worth stating
how much this mattered — scored without detecting it, Confirmation would have
read 0.121 instead of 0.736, and every conclusion drawn from it would have
been wrong.

**Recall beats precision everywhere.** We find the notes (0.73–0.91 recall);
we also emit a lot that are not there. Only 29, 21 and 29 notated notes were
missed outright across the three solos. The problem is over-production, not
deafness — and over-production is the easier problem.

**Open-issue #1 held up on real music.** Of the invented notes, the ones
repeating a neighbour's pitch — one held note heard as several, the failure
the harmonic-attack corroboration was built to kill — number **13 of 253, 5
of 46, and 3 of 69**. Fragmentation is essentially gone outside the synthetic
suite too.

**So the invented notes are other instruments.** 240 of Confirmation's 253
are at some unrelated pitch. That is open-issue #8 (CREPE follows the loudest
broadband source, not the soloist) showing up on real audio, and it is now
the single largest error source in the whole pipeline.

**Giant Steps' errors all point downward — and separation cannot fix them.**
Its commonest substitutions are −12 (×18), −14, −19, −17, never upward. Its
detected range runs down to MIDI 43, fifteen semitones below the notated floor
of 58. Chroma scoring gains +0.087 there versus +0.005 and +0.000 on the
tenors, so a real share of that error *is* octave confusion, unlike on the
horns.

The obvious hypothesis was bleed: the run used `htdemucs_ft`, which folds piano
in with everything else. It was wrong. Re-separating with `htdemucs_6s` and
transcribing its dedicated `piano` stem changes nothing:

| | pitch F1 | chroma F1 | invented | below the notated floor |
|---|---|---|---|---|
| `other` of htdemucs_ft | 0.686 | 0.773 | 69 | 26 (7%) |
| `piano` of htdemucs_6s | 0.682 | 0.765 | 59 | 25 (7%) |

The downward errors survive isolation intact because they are the pianist's
*own left hand*. Separation splits instruments from each other; it cannot split
one instrument from itself, and a monophonic tracker pointed at a pianist will
sometimes follow the lower voice. Giant Steps is therefore an M7b problem — a
polyphonic model, or a top-line bias in the tracker — not an M3 one, and this
is evidence against adopting 6-stem as the default for its own sake
(open-issue #3).

**Note durations are already right.** Median duration ours vs notated: 0.140
vs 0.160 s, 0.160 vs 0.155 s, 0.130 vs 0.120 s. Segmentation lengths are not
the problem.

**Timing is the weak axis, as expected at M3.** Onset F1 ~0.60–0.65 at a 50 ms
tolerance, and note F1 drops to ~0.33 because it needs onset *and* pitch on
the same note. Quantization is M5's job and there is no tempo map yet — the
per-window fit had to absorb up to 1.94 s of drift, which is 6 beats at
Confirmation's tempo. Do not read these as a verdict on M3.

## What this suggests next

1. **For the horns, isolation is the bottleneck.** The largest single lever is
   keeping other instruments out of the stem the tracker sees (issue #8).
   Tuning CREPE's gates will not touch 240 spurious notes. But the Giant Steps
   result above is a warning that "isolate harder" is not a general answer —
   it did nothing there.
2. **For a piano or guitar soloist, the ceiling is monophony itself.** This is
   the two-or-three-note path already wanted for solos that are not single
   lines, and it is what M7b exists for.
3. **A minimum-duration floor should be beat-relative, not absolute.** An 80 ms
   floor removes 25% / 43% of invented notes for 5% / 3% of matched ones on the
   tenors — a clear win. On Giant Steps the same floor removes 10% for 11%, a
   loss, because at 249 bpm real notes *are* that short. 80 ms is 0.25 beats at
   187 bpm but 0.33 beats at 249. `min_note_ms` is the wrong unit.
4. **The three failure modes are now separable and cheap to re-measure**, which
   is what this harness is for. Re-run it after any transcribe change.

## Caveats

- One take per tune, three tunes, one transcriber's ear as truth. These are
  benchmarks to move, not absolute accuracy.
- The hand transcriptions are themselves interpretations; a "wrong note" of ±1
  semitone (the commonest substitution on both tenors, 15 and 5 occurrences)
  may be a ghost note or a scoop either of us could defend.
- The onset numbers depend on a constant-tempo assumption that the drift
  figures show is strained. They are a floor, not an estimate.
