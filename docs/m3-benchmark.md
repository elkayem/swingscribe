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

How that per-window offset is chosen turned out to matter more than anything
else on this page — see "The onset numbers were wrong" below.

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
| onset F1 (windowed) | 0.585 | 0.580 | 0.622 |
| note F1 (onset+pitch) | **0.489** | **0.501** | **0.500** |
| drift the fit absorbed | 0.94 s | 0.30 s | 0.22 s |

The onset and note rows were **0.604/0.325, 0.650/0.341, 0.645/0.360** until
the scoring bug below was found. The pitch rows are unaffected: they never
used timing at all.

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

**So the invented notes are at some other pitch** — 240 of Confirmation's 253.
This section originally continued "they are other instruments", attributing
them to open-issue #8. That inference was wrong and is corrected in the
follow-up below: measured against their neighbours rather than just counted as
different, 74% of them are within two semitones of a real note. On the horns
they are the soloist's own scoops and passing tones. Only Giant Steps' are a
second instrument.

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

## The onset numbers were wrong, and wrong in a way that misled us

Note F1 sat at 0.33 against an onset F1 of 0.60 for months. Read plainly that
says "it finds the notes and puts them in the wrong place", and it sent
attention toward timing. It was a bug in the scorer.

The per-window offset was chosen by searching for the shift that maximized
**onset hits**. Onsets carry no identity. In a bebop line of near-uniform
eighths, a shift of a whole eighth note lines up almost exactly as many
onsets as the truth does, and the search has no evidence with which to
prefer the truth. Measured, it slipped **12 of 32 windows on Confirmation, 9
of 18 on All The Things, and 6 of 16 on Giant Steps** — and the slips landed
on *integer numbers of eighth notes* (−1, −3, −4, −5, −6, −7, −8), not on a
continuum, which is how a beat slip is told apart from real tempo drift.

A slipped window is the worst kind of wrong, because it hides:

- its **onsets still coincide**, so onset F1 is unharmed — even flattered;
- every note in it is compared against its *neighbour's* pitch, so note F1
  goes to nearly zero.

Which is precisely the signature the table showed. The "drift the fit
absorbed" column was the visible symptom all along: 1.94 s of drift across
one solo is six beats, and no rhythm section drifts six beats.

**The fix.** The shift now comes from the pitch-sequence alignment, which
establishes which of our notes is which notated note using no timing at all.
Each aligned pair gives one (ours − notated) delta, and the window's shift is
their median — a robust location estimate over an independently derived
correspondence, rather than a search over the number being reported. It
cannot slip a beat, because pitch pins the correspondence first.

Two things worth stating about the result:

- **This is not the metric being gamed.** An independent method — fitting the
  shift by maximizing onset *and pitch* hits together — lands within 0.03 of
  it on all three solos (0.558 / 0.582 / 0.576 against 0.574 / 0.571 / 0.607
  before the harness's honesty adjustment below). Two methods that share no
  machinery agree.
- **Windows with too few anchors are scored, not dropped.** A passage we
  failed to transcribe has no aligned pairs; it falls back to the solo-wide
  shift and scores badly. Dropping it would have removed our worst playing
  from the average, and would have read about 0.08 higher.

Onset F1 went *down* slightly (0.604 → 0.585, 0.650 → 0.580, 0.645 → 0.622).
That is the correction working: some of the old onset matches were the
spurious ones a slipped window produces.

The logic now lives in `src/swingscribe/benchmark.py` with tests in
`tests/test_benchmark.py`, rather than untested inside the script — which is
the reason it survived this long. One of those tests reproduces the slip.

## Follow-up: Viterbi f0 decoding

The first fix these numbers motivated, measured the same way. CREPE was being
decoded per frame with nothing connecting frame t to frame t-1, so a louder
instrument captured the pitch for as long as it was louder. `transcribe.
pitch_step_cost` charges for movement between frames; 0.2 is the default.

| | before | after | invented notes |
|---|---|---|---|
| Confirmation | 0.747 | **0.762** | 242 -> 215 |
| All The Things | 0.893 | 0.892 | 38 -> 39 |
| Giant Steps | 0.688 | **0.702** | 69 -> 47 |

Two caveats on reading that table:

- The "before" column is **not** the results table above. It is the new code
  path with the transition cost set to zero, which already scores higher than
  what M3 shipped (0.736 / 0.883 / 0.686) because torchcrepe's
  `weighted_argmax` sigmoids an activation that is already a probability and
  then dithers the result. Of the total gain, roughly 0.008 mean F1 is that
  fix and 0.009 is continuity. They are separated here so neither gets credit
  for the other.
- All The Things was already at 0.89 and does not move. The gain is
  concentrated exactly where the error was.

Raising the cost to 0.4 scores higher again (0.764 / 0.892 / 0.709) but starts
refusing real intervals — Giant Steps' missed notes go 28 -> 44 — so 0.2 is
where the trade stops being free.

### Where the remaining invented notes actually are

Viterbi does not close open-issue #8 — Confirmation still invents 215 notes —
but measuring *what they are* changed which problem is next. Each invented note
against the nearest real note on either side of it in time:

| | Confirmation | All The Things | Giant Steps |
|---|---|---|---|
| invented notes | 215 | 39 | 47 |
| within 2 semitones of a real neighbour | **74%** | **94%** | 24% |
| sitting *between* its neighbours in pitch | 49% | 77% | 15% |
| more than 4 semitones from both | 16% | 0% | **70%** |
| outside the soloist's register | 7% | 5% | **55%** |
| within 0.5s of a real note | 85% | 85% | 96% |
| median duration vs matched | 0.110 / 0.150s | 0.110 / 0.160s | 0.120 / 0.130s |

They are not in the rests, and on the horns they are not other instruments.
They are inside the phrases, in the soloist's register, one or two semitones
from a real note, and short: scoops, bends, grace notes, passing tones — sound
the player made that the transcriber chose not to write down. Giant Steps is
the opposite on every row, and stays a second-source problem.

That splits the remaining precision gap into two unrelated problems, and puts
the horn one somewhere new: `pitch_persist_ms` applies one flat 60ms threshold
however large the interval is, so it cannot tell a bend from a melodic step.

## What this suggests next

1. **For the horns, isolation is the bottleneck.** The largest single lever is
   keeping other instruments out of the stem the tracker sees (issue #8).
   Tuning CREPE's gates will not touch 240 spurious notes. But the Giant Steps
   result above is a warning that "isolate harder" is not a general answer —
   it did nothing there. *Partly acted on:* Viterbi decoding removed 27 of
   Confirmation's and 22 of Giant Steps' invented notes without touching
   isolation at all — see the follow-up section. The rest still stand.
2. **For a piano or guitar soloist, the ceiling is monophony itself.** This is
   the two-or-three-note path already wanted for solos that are not single
   lines, and it is what M7b exists for.
3. **A minimum-duration floor should be beat-relative — but it is worth very
   little.** An 80 ms floor removes 25% / 43% of invented notes for 5% / 3% of
   matched ones on the tenors. On Giant Steps it removes 10% for 11%, a loss,
   because at 249 bpm real notes *are* that short: 80 ms is 0.25 beats at
   187 bpm but 0.33 beats at 249, so `min_note_ms` is the wrong unit. Working
   the counts through, though, an absolute floor moves pitch F1 by +0.006 /
   +0.007 / −0.045, and making it beat-relative only rescues the third case to
   about neutral. This is a footnote, not a lever — an earlier draft of this
   file oversold it as "a clear win".
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
