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

## The tuplet's onsets sit inside the beat (R28, the same day)

The two triplet classes after R27 were 1.6% thirds written binary and 1.9%
binary written as thirds. Behind the second: laid-back sixteenths such as
(0.3, 0.55, 0.85) and (0.1, 0.35, 0.6, 0.85), which the annotator files at
division 4. The thirds grid sends 0.85 to 1.0 -- the next beat -- and still
counted it as the third onset a tuplet needs, and parsimony then preferred
thirds to sixteenths; 597 of those 1,910 beats held FOUR onsets, which no
triplet can. Behind the first: 1,129 two-onset beats at (0.35, 0.75), the
second and third of a triplet after a rest, which the tuplet gate refuses
because two onsets cannot vote one.

Two rules were written and measured, on the instrument and then on the
pages, together and each alone:

| setting | instrument page hit | page hit counting drops | dropped | hand-score rhythm | Omnibook rhythm | placement (mscz / Omnibook) |
|---|---|---|---|---|---|---|
| R27 | 75.3% | 71.8% | 4.4% | | 0.758 | 0.895 / 0.848 |
| inside only (`tuplet_needs_onsets_inside`) | 74.4% | 71.6% | 3.6% | 5 up, 2 down | 0.761 (10 up, 6 down) | 0.898 / 0.856 |
| pair only (`offbeat_pair_tuplet_fit` 0.05) | 76.4% | | 4.4% | 0 up, 8 down | 0.748 (3 up, 14 down) | 0.890 / 0.843 |
| both | 75.5% | | 3.6% | 4 up, 5 down | 0.752 (5 up, 15 down) | 0.892 / 0.853 |
| pair 0.08, no inside | 76.5% | | 4.3% | 1 up, 8 down | 0.738 | 0.885 / 0.834 |

**The inside rule ships** (`QuantizeConfig.tuplet_needs_onsets_inside`,
`CACHE_VERSION` 4): a ternary reading needs every onset of the beat to
land inside it on thirds. On the instrument it trades one triplet class for
the other (binary-as-triplet 1.9% -> 0.7%, triplet-as-binary 1.6% -> 2.4%)
and loses a point of `page_hit`, but it puts 1,700 more notes on the page
(a ternary reading with an onset at 1.0 collided with the next beat's note
and one was dropped), and every page-side measure agrees: Omnibook rhythm
0.758 -> 0.761 and value 0.689 -> 0.693, pianist rhythm 0.828 -> 0.830,
placement up on both sets. `page_hit_all`, which counts a dropped note as
a miss, was added to the instrument for exactly this: 71.8% -> 71.6% is
the honest instrument reading of a rule the pages like.

**The pair rule does not ship** (off at 0.0, measured at 0.05): +1.1 on the
instrument, and on our own notes hand-score rhythm down on 8 of 12,
Omnibook on 14 of 17 that moved, placement down on both sets. The pairs it
admits on our onsets are not the annotator's triplets. Same lesson as the
counted rule below: a threshold on raw phase does not transfer from a
human's onsets to ours.

## The line's lag behind the beat (R29, the same evening)

The notation survey (docs/notation-survey.md) put a number on the
listener's bar 4: 6.2% of our onsets on the "e" against a human's
1.8-2.5%, and 2.6-3.0% of our notes dotted eighths against 0.1%, because
the line sits behind the tracked beat and a sixteenth grid writes that
faithfully. `quantize.line_lag` reads the lag as a window median of
downbeat offsets and the beat's onsets are shifted by it before the warp
and the snap. Four versions were measured here before one shipped, and
the instrument's verdict on the rule itself is the interesting part.

| version | page hit | page hit counting drops | dropped | laid-back beat | late offbeat as dotted | early offbeat as 16th | pushed beat | binary as triplet |
|---|---|---|---|---|---|---|---|---|
| R28 (none) | 74.4% | 71.6% | 7,079 | 1,554 | 4,268 | 3,752 | 884 | 1,250 |
| one-sided estimate, shift | 67.7% | 65.4% | 6,050 | 708 | 2,477 | 7,182 | 3,275 | 4,877 |
| symmetric, stretch onto [0, 1] | 74.6% | 71.1% | 8,528 | 649 | 4,656 | 4,260 | 646 | 2,218 |
| symmetric, shift, no push guard | 74.6% | 70.9% | 9,075 | 661 | 2,596 | 5,035 | 558 | 2,611 |
| symmetric, shift, guard, push 0.85 | 75.1% | 72.2% | 7,304 | 821 | 2,760 | 4,680 | 657 | 2,173 |
| **shipped: push 0.88** | **74.8%** | **71.9%** | **7,155** | **693** | **2,510** | **4,983** | **644** | **2,637** |

What each row taught:

- **The evidence must be symmetric.** Taking the lag as the median of
  first-onset offsets alone reads every line's scatter as lag (an on-time
  downbeat is 0 to 0.1 late, never early, because an early one lands at
  the end of the beat before), and shifting a line by its scatter wrote
  every pushed note a sixteenth early. A last onset from the push
  threshold on now counts as the next downbeat played early, negative, and
  a line played dead on the beat reads no lag at all.
- **Shift, never stretch.** Mapping [lag, 1] onto [0, 1] keeps the next
  beat line fixed, which looked principled, and turned a sixteenth's 0.25
  into a third's 0.31: binary-as-triplet doubled.
- **A beat whose downbeat was pushed has no late downbeat to pull back.**
  Shifted, its first onset landed on the beat line the pushed note snaps
  to and one of the two was dropped: +2,600 drops.
- **The push threshold is where the instrument and the pages disagree.**
  The instrument prefers 0.85; every page measure prefers 0.88 (Omnibook
  rhythm 0.780 against 0.787, pianists 0.858 against 0.866), because a
  laid-back beat's own "a" sits at 0.86 -- Birks Works bar 4's last
  sixteenth -- and at 0.85 it was pushed onto the next beat line.

**The instrument cannot judge this rule, only its collateral.** WJazzD's
annotators write the "e" themselves: 7.2% of their onsets, against 1.8%
in the listener's scores and 2.5% in the Omnibook, so every laid-back
downbeat we now write on the beat is charged as "annotation literal"
(11,475 -> 13,443) and the instrument reads +0.4 for a rule the pages
read as the largest gain since the notation was first scored: hand-score
rhythm 0.794 -> 0.845 (17 up, 1 down over 18 rows), value 0.735 ->
0.777, tie rate 0.050 -> 0.033; Omnibook rhythm 0.761 -> 0.787 (20 up, 1
down), value 0.693 -> 0.714; pianists 0.830 -> 0.866; placement up on
both sets, WJazzD's own placement -0.008 (the literal annotator again).
Birks Works rhythm 0.762 -> 0.835, and bar 4 is the listener's note for
note. The rows above are what the instrument is for here: the first
three versions would each have shipped a defect the pages might have
averaged away.

Settings: `QuantizeConfig.lag_window_beats` 4 (2 and 8 measured within
0.2 of it), `lag_cap` 0.2 (0.3 the same), `lag_floor` 0.08 (0 reads +0.3
better on the instrument and the pages were not run on it), `LAG_PUSH_MIN`
0.88.

## Ballads: the candidate set follows the tempo (R31, 2026-09-21)

The SLOW band -- 38 solos at 37-79 bpm, 17,797 notes -- was the
instrument's worst by far: page hit 45.3%, 35.8% counting drops, a fifth
of the annotated notes dropped and 43.7% "below the grid". A probe of what
those solos hold: the annotator files 20% of the notes at sixths of the
beat, 18% at eighths, 11% at tenths and 6% at twelfths; beats hold four
to eight onsets; and of the notes our page LOSES, 61% sit a sixteenth or
an eighth of a beat from the note before (60-100 ms at this tempo), at
divisions 8, 10, 12 and 6. Our candidate set stopped at the sixteenth,
and offered 32nds only where sixteenths could not keep the onsets apart,
which at 64 bpm is a beat of 32nd-triplets, already merging.

`QuantizeConfig.slow_beat_s` (0.7 s, 86 bpm and under) and
`slow_beat_grids` ((6, 8, 12)): a solo whose median beat is that long
has every beat offered those grids outright, under the tuplet gate and
the slack, which in beats is small at this tempo. Notate writes twelfths
as 32nds under a 3:2 in the sixteenth.

| grids on offer | SLOW page hit | counting drops | dropped | below the grid | binary as triplet |
|---|---|---|---|---|---|
| none (R30) | 45.3% | 35.8% | 3,545 | 6,227 | 53 |
| 6, 8 | 47.5% | 37.9% | 3,459 | 5,443 | 269 |
| **6, 8, 12** | 46.6% | **40.6%** | **2,227** | 6,164 | 238 |
| 6, 8, 10, 12 | 45.4% | 40.9% | 1,697 | 6,435 | 191 |
| 8, 12 | 42.7% | 37.3% | 2,186 | 6,786 | 77 |

The twelfth is what puts notes back on the page: 1,300 fewer drops for
a point of page hit. The tenth takes 500 more but reads a point lower on
page hit and, on the three located WJazzD ballads, 0.864 against 0.870;
left out. Overall the instrument reads 74.8 -> 74.6% page hit and 71.9 ->
72.3% counting drops, 7,155 -> 5,770 dropped.

Judged per BEAT the rule reached the wrong solos: Soul Station at 100 bpm
has a third of its beats past 0.6 s and read 0.820 -> 0.812, and two
half-rate grids (Brother Hubbard, Adam's Apple; R21) read worse still.
Judged on the solo's MEDIAN beat it reaches the ballads: the three
located WJazzD ballads (Don't Blame Me, Embraceable You, I Fall In Love
Too Easily) 0.847 -> 0.870 on page rhythm, 3 of 3 up, with 28, 29 and 2
more notes matched; no hand-scored or Omnibook page moves, and Soul
Station and Adam's Apple are untouched. The one thing it still reaches
that it should not is Brother Hubbard's two takes, whose tracked grid was
at HALF rate (R21) and whose median beat therefore looked like a ballad's:
0.276 -> 0.210 and 0.260 on a page that was already off its pulse. That
was R21's to fix, and a rule cannot see it from the grid it is given; R32
fixed the grid the same day (its median beat is 0.40 s now, and its
page rhythm 0.67 and 0.59). Beat threshold 0.6 and 0.75 were measured too and read the same
on the SLOW band; 0.7 sits between Soul Station's 0.60 and the slowest
real ballad's 0.84.

## Measured and not shipped

### The six-per-beat grid (D35.2), measured and off

The Omnibook writes 4.9% of its notes as sixteenth triplets and we had no
grid for them (docs/notation-survey.md), so `QuantizeConfig.sixteenth_triplets`
offers six to the beat wherever the 32nd grid is offered -- where
sixteenths cannot keep the onsets apart -- under the tuplet gate, tried
before 32nds because it is coarser. Notate writes the figure as sixteenths
under a 3:2 in the half-beat unit.

| version | instrument page hit | below the grid | binary as triplet | Omnibook rhythm | Omnibook pages | hand-score pages |
|---|---|---|---|---|---|---|
| off (R29) | 74.8% | 20,036 | 2,637 | 0.787 | | |
| wherever sixteenths merge | 77.0% | 16,394 | 3,908 | 0.779 | 0 up, 15 down | 4 up, 4 down |
| 3-4 onsets, count alone | 76.1% | 17,997 | 3,897 | 0.779 | 0 up, 15 down | 4 up, 4 down |
| 3-4 onsets, fit within 0.03 | 75.2% | 19,319 | 2,997 | 0.786 | 0 up, 6 down | 2 up, 1 down |

The largest instrument gain of the week -- the SLOW band alone 45 -> 51 --
and a loss on every Omnibook side it touches, the book that writes the
figure most. On the annotator's onsets a sixteenth triplet sits at sixths;
on ours the figure the Omnibook writes that way is not three notes at
sixths (CREPE's onsets scatter, and the fast Parker sides are where the
book writes them), and what sixths fit instead is a scattered sixteenth
or 32nd run, which then reads a third late. The flag is off. It is the
first GRID-CHOICE rule that did not transfer, so the transfer lesson is
sharper than it was: the instrument sees a human's onsets, and a grid
finer than a sixteenth is exactly where ours stop being a human's.

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
  The counted rule is above, measured and reverted; R29's lag takes a
  share of these (late offbeat as dotted 4,268 -> 2,510) where the line
  lags as a whole. What is left must be judged on our onsets.
- **The triplet confusions**: 2.4% thirds written binary after R28
  (1,129 of them the (0.35, 0.75) pair, whose rule did not transfer) and
  0.7% the other way.
- **Ballads**, after R31: 2,227 notes still dropped and 6,164 below the
  grid in the SLOW band (47% between them, from 60%). What is left is
  the annotator's tenths (the quintuplet 32nd, writable and measured
  above) and divisions past twelve, and the ballad's own scatter, which
  no grid fits.
- **"other"**, 4.7%: the largest cell is the annotator's 1/3 in a
  two-onset beat written by us at 1/4 (2,338), which a page would write as
  an eighth or a triplet, never a sixteenth.

## What it is not

WJazzD's `duration` is a note-off, not a value, so nothing here scores
values; `notate`'s rests and ties are measured by `benchmark.readability`.
Only aggregates leave the script (ODbL); `--json` holds per-solo counts.
