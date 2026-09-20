# The quantizer alone, measured on WJazzD (2026-09-20)

`scripts/wjazz_quantize.py`, pinned in `tests/regression/wjazz-quantize-baseline.json`.

## Why

The listener's complaint of 2026-09-19: "even when it gets the notes right,
it chooses timing no human transcriber would ever use" -- Art Pepper's Birks
Works bar 4 as a tied sixteenth into dotted-eighth-sixteenth pairs where the
hand score has quarters and eighths; bar 16 with tied thirty-seconds. Those
are choices of `quantize` and `notate`, and until now the only measure of
them was the notated rhythm of twelve hand scores, which is gap-based,
cannot say which note moved, and rewards writing everything as eighths.

## What the instrument does

Every WJazzD note carries both when it was played (`onset`, seconds) and
where the annotator filed it (`bar`, `beat`, `tatum` out of `division`); every
solo carries the annotator's beat grid in seconds. That is the quantizer's
input and output, 200,000 notes of it, with no audio, no CREPE and no
alignment: the annotator's onsets go through `swing`, `quantize` and `notate`
on the annotator's grid -- `notation.notation_for_span`, the Export button's
path -- and each note is compared with where the annotator filed it. The one
constant not being asked (which of our bars is their bar 1) is the mode of
the differences. 452 solos in one quarter-note metre, 16 seconds to run.

### WJazzD's tatum is more literal than a page, in both directions

This changed the reading of the result twice. The Jazzomat annotation files
each onset at the nearest tatum of a per-beat `division` chosen to fit that
beat's onsets, so it records the performance, not a transcriber's choice:
the offbeat of a two-onset beat sits at 1/2 in 22,577 beats, at 2/3 in
5,102 and at 3/4 in 2,500; a laid-back downbeat is filed at 1/4, a pushed
one at 3/4 of the beat before. A page writes an eighth, a beat and a beat.

So a raw tatum match is the wrong target in both directions. Where the
annotator filed 3/4 and we wrote the eighth, we are right and the tatum is
literal. Where the annotator filed 3/4 and we wrote 3/4 too, we are BOTH
literal, and the page has the dotted eighth plus sixteenth the listener
complained of. The first version of this instrument counted that second
case as a hit; a rule that wrote more of them then read four points better
here while notated rhythm fell on eleven of twelve hand scores and 19 of 22
Omnibook sides. The instrument now reports:

- **tatum hit**: on the annotator's tatum exactly.
- **page hit**: tatum hit, or the *swing convention* -- a two-onset beat's
  offbeat filed at 2/3 or 3/4 and written by us at 1/2 -- with the
  *annotation literal* class (we wrote the beat; the annotator filed the
  note within a sixteenth of it) set aside rather than charged. Our 3/4 in
  such a beat is charged as *late offbeat as dotted* whatever the annotator
  filed.

## The quantizer before and after, 2026-09-20

| tempo band | solos | notes | page hit before | page hit after |
|---|---|---|---|---|
| SLOW | 38 | 17,797 | 45.6% | 46.5% |
| MEDIUM SLOW | 31 | 12,917 | 60.7% | 63.2% |
| MEDIUM | 86 | 36,220 | 61.8% | 66.0% |
| MEDIUM UP | 96 | 34,049 | 68.6% | 73.2% |
| UP | 201 | 98,000 | 79.3% | 85.1% |
| **all** | **452** | **198,983** | **70.7%** | **75.3%** |

The classes, as a share of the ~190,000 matched notes:

| class | before | after | what it is |
|---|---|---|---|
| hit | 61.7% | 63.9% | |
| swing convention | 5.5% | 6.6% | the annotator's 2/3 or 3/4, our eighth |
| annotation literal | 4.8% | 4.8% | we wrote the beat; the tatum is a sixteenth off it |
| late offbeat as dotted | 4.7% | 2.1% | a swung offbeat played at 0.7-0.9, written 3/4: the dotted rhythm of bar 4 |
| early offbeat as 16th | 3.1% | 1.8% | an eighth played at 0.3-0.5, written a sixteenth or thirty-second early |
| laid-back beat after it | 1.6% | 0.8% | a beat played 0.2-0.3 late, written on the "e": the tied pickup of bar 16 |
| pushed beat before it | 0.7% | 0.4% | a beat played early, written in the beat before |
| triplet as binary | 1.6% | 1.6% | thirds written as halves or quarters |
| binary as triplet | 1.9% | 1.9% | the other way |
| below the grid | 9.9% | 9.9% | the annotator's division is 5 or finer; the page has no such value |
| other | 4.4% | 4.7% | |
| dropped | 4.5% | 4.4% of annotated | two onsets in one grid step; one is lost |

Three readings of the "before" column:

1. **The dotted rhythm of bar 4 was the quantizer's own, and the largest
   class it owned.** Half of the 8,880 came from beats the swing reading
   never reached (a window with too few offbeats, or a span read straight
   inside a swinging solo) so no warp applied and 0.7 fell to the sixteenth
   grid; the other half were offbeats played at 0.8-0.9, which even the
   warp only brings to 0.75. Either way the beat held one or two onsets.
2. **The early offbeat was the swing warp's doing**: a phase of 0.4 or 0.5
   (an eighth played straight or ahead) is mapped to 0.33-0.42 by a warp
   built to bring 0.65 to 0.5, and the sixteenth or thirty-second grid then
   fits it better. The laid-back beat was the coarsest-within-slack rule
   with one onset to judge by.
3. **Ballads are a different problem.** At SLOW, 43% of notes are below
   our finest grid and 20% are dropped for want of one: the tempo-blind
   candidate set (nothing finer than a sixteenth unless a beat cannot keep
   its onsets apart) that D11 already names. Nothing here touches it.

## What shipped

Two rules in `quantize`, both measured on this instrument first and then on
the hand scores and the Omnibook through `run_eval` (`CACHE_VERSION` 3):

- **A sparse beat cannot demonstrate a sixteenth**
  (`QuantizeConfig.min_onsets_for_sixteenth`, 3). A beat holding one or
  two onsets is offered the eighth grid and the ternary one only, the same
  reasoning as the three-onset gate on tuplets, one grid coarser. Two
  escapes keep it from ever losing a note: the eighth grid must keep the
  onsets apart, and its reading must not land an onset on the neighbouring
  beat's own note (`_collides_on_eighths`, which looks both ways -- a late
  note pushed onto the next beat's first onset, or an early first note
  pulled onto the beat the previous beat's late note is being pushed to;
  the one-way guard lost 1,456 notes). This is what moves the table above.
- **Each binary grid is scored under both timing readings, the raw phase
  and the warped one** (`choose_reading`), the coarsest grid within slack
  of the best pair wins, and the note is snapped and replayed under that
  reading. The straight reading is offered only to a beat whose onsets all
  sit at or before the span's swung offbeat: past it, a raw 0.75 is a
  perfect sixteenth, and the ungated version wrote the dotted rhythm back
  (that was the four-points-better-and-every-page-worse result). Gated, it
  is worth 0.3 of a point here and takes the early-offbeat class from 3.1%
  to 2.5% on its own.

Through `run_eval`, with our own notes on our own grid:

| measure | before | after |
|---|---|---|
| Omnibook notated rhythm, over 22 | 0.730 | 0.758 (21 of 22 up) |
| Omnibook notated value | 0.656 | 0.689 |
| hand-score rhythm, 12 scores | | up on 9, down on 3 (Melody for C -0.015, Soul Station -0.018, Giant Steps -0.005) |
| Birks Works rhythm / value | 0.704 / 0.650 | 0.748 / 0.708 |
| pianist rhythm, over 7 | 0.818 | 0.828 |
| readability, over 85 pages | 0.9908 | 0.9945 |
| placement (mscz / Omnibook / WJazzD) | 0.908 / 0.856 / 0.835 | 0.895 / 0.848 / 0.825 |

The placement dip is the one cost, and it is named: a lone late offbeat in
a beat the swing reading did not reach snaps to the NEXT beat on the eighth
grid (0.8 with no warp is nearer 1.0 than 0.5), where the annotator has it
as the "and" of the beat before. Nothing changed in `wjazz_on_the_bar` (70
of 73). The fix is a prior on the "and" for a lone late offbeat, and it is
the next thing on this instrument.

## Measured and not shipped

| variant | page hit | dotted | laid-back | dropped |
|---|---|---|---|---|
| one-sided warp (phases at or before 0.5 untouched, [0.5, φ*] collapsed onto 0.5) | 77.5%* | | 3.1% | 5.4% |
| two readings, ungated | 79.6%* | | 2.2% | 4.4% |
| sparse = 1 (a lone onset only) | 73.8% | 3.5% | 1.1% | 4.4% |

\* under the first version of the instrument, which counted our 3/4 as a hit.
The one-sided warp's flat region merges onsets (1,800 more beats lose a
note); the ungated straight reading writes the dotted rhythm for every
offbeat past the swing point; sparse = 1 is strictly less than sparse = 2 on
every class with the same drops.

### The counted rule for the sparse beat (D34.1), measured and not shipped

The truth table behind it, over 452 solos -- for a sparse beat whose last
onset sits at 0.65-0.95 of the beat, where the annotator filed that note:

| beat | next beat's downbeat | raw phase | n | annotator: the "and" / the next beat | ours (R27): and / next / dotted |
|---|---|---|---|---|---|
| unwarped | free | 0.65-0.75 | 827 | 100% / 0% | 58% / 0% / 42% |
| unwarped | free | 0.75-0.85 | 2,634 | 98% / 2% | 0% / 90% / 10% |
| unwarped | free | 0.85-0.95 | 4,634 | 27% / 73% | 0% / 99% / 1% |
| unwarped | taken | 0.75-0.85 | 805 | 100% / 0% | 0% / 4% / 96% |
| unwarped | taken | 0.85-0.95 | 190 | 79% / 21% | 0% / 84% / 16% |
| warped | free | 0.75-0.85 | 5,609 | 99% / 1% | 75% / 5% / 20% |
| warped | free | 0.85-0.95 | 4,670 | 36% / 64% | 4% / 76% / 20% |
| warped | taken | 0.85-0.95 | 570 | 85% / 15% | 8% / 9% / 83% |

So a rule was written from it: in a sparse beat, an onset before 0.25 is the
beat, up to 0.85 the "and", from 0.85 the next beat unless the next beat
already holds a note before 0.25 of itself, in which case the "and"; stored
in warped space so the swing replays. On the instrument: page hit 75.3% ->
76.7%, the dotted class 2.1% -> 1.7%, the laid-back beat 0.8% -> 0.3%, the
early offbeat 1.8% -> 1.4%, drops 8,787 -> 8,657; 0.80 and 0.90 as the
boundary read 76.3% and 75.9%.

Through `run_eval`, on OUR notes on OUR grid, it read worse on every
page-side measure: hand-score rhythm down on six of the ten pages that
moved (Birks Works 0.748 -> 0.716, All The Things 0.716 -> 0.681), Omnibook
rhythm down on 13 of 20, placement 0.895 -> 0.886 (mscz), 0.848 -> 0.840
(Omnibook), 0.825 -> 0.822 (WJazzD). Reverted.

The lesson is about the instrument, not the rule. R27's two rules change
which GRID a beat is read on, and a human's onsets and ours agree about
that. The counted rule moves notes ACROSS beat boundaries by a raw-phase
threshold, and there a human's onsets on a human's grid are not ours on
ours: the tracker's beats sit on a 20 ms frame and CREPE's onsets carry
their own scatter, so a note at 0.85 of an annotated beat is anywhere from
0.75 to 0.95 of ours, and a boundary calibrated on the clean side sends
the wrong notes over. Any rule that decides by a phase threshold near a
beat line has to be measured on our onsets before it is believed.

## What is left, for this instrument to measure next

- **The lone late offbeat in an unswung beat** (the placement dip above).
  The counted rule is above, measured and reverted: whatever replaces it
  must be judged on our onsets, and the next candidate is a threshold that
  moves with the grid's own jitter (a beat's neighbours, not a constant).
- **The triplet confusions**, 3.5% both ways, untouched by either rule.
- **Ballads**: below the grid and dropped, 60% of SLOW notes between them;
  a tempo-aware candidate set or the double-time reading.
- **"other"**, 4.7%: the largest cell is the annotator's 1/3 in a
  two-onset beat written by us at 1/4 (2,338), which a page would write as
  an eighth or a triplet, never a sixteenth.

## What it is not

WJazzD's `duration` is a note-off, not a value, so nothing here scores
values; `notate`'s rests and ties are measured by `benchmark.readability`.
Only aggregates leave the script (ODbL); `--json` holds per-solo counts.
