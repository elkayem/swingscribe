# Hearing against writing, on the triples

2026-09-30. `scripts/triples.py --db wjazz/wjazzd.db --ab` (docs/roadmap.md
A1), seven minutes, no audio: the harness's note and grid caches, the
WJazzD database and the pages. The package half is `swingscribe/triples.py`
(tested in `tests/test_triples.py` on synthetic lines).

The question the roadmap put: when our page disagrees with a human's, is it
because we HEARD the solo wrong, because our BEAT GRID is wrong, or because
we WROTE a correctly heard performance the way no transcriber would? Every
other measurement in the project mixes the three. D36 took away the one
that claimed to separate the last: WJazzD's tatum layer is Flex-Q's
quantisation, not a transcriber's page.

A **triple** is one solo with three things: the recording, WJazzD's human
annotation of it (onsets in seconds, pitches, a tapped beat grid), and a
human transcription page of the same take. For each, three inputs are
notated through the shipped swing, quantize and notate stages and scored
against the same reference:

- **(a)** WJazzD's onsets, pitches and durations on WJazzD's own beat grid,
  the annotator's first downbeat as bar 1. No hearing, no grid error.
- **(b)** the same onsets mapped into our timeline (`identify_all`'s offset
  and rate) on OUR repaired grid, exactly as `run_eval.notate_run` builds the
  page it scores. Adds grid error.
- **(c)** our cached transcription over the same window on our grid: the
  WJazzD notation page `run_eval` builds. Adds hearing.

`1 - (a)` is WRITING, `(a) - (b)` GRID, `(b) - (c)` HEARING. A fourth row,
**(f)**, is WJazzD's own tatum positions (`wjazz.annotation_notation`):
Flex-Q's writing of the same onsets, for scale (its note values are ours,
so its `value` means nothing).

Scores: `benchmark.score_against_notation` (rhythm, value, coverage) and
`score_bars.bar_line_agreement` (on the bar). Only WJazzD's ONSETS and
BEATS are used for (a)-(c), and those are a human's; its tatum is only row
(f).

## The reference: the page cropped to the solo

An Omnibook page holds the head as well as the solo, and `alignment.align` is
global: handed the whole page against one annotated solo it measures nothing
(R13). `triples.locate_solo` aligns WJazzD's pitches to the page's, lets each
true match vote the page's position minus the annotation's (whole beats),
takes the vote at each end of the solo separately (so a bar the page drops
part-way costs one bar), and crops the page to that window, just under half
a beat either side. The transposition is searched in full (histogram
shortlist, each candidate aligned whole), because a page's opening is the
head and may be written for a transposing horn.

The same numbers are the TAKE CHECK: `same_take` needs the crop's coverage
over `benchmark.COVERAGE_FLOOR` (0.5) and the share of matches on their local
clock over `score_bars.PHASE_SHARE_FLOOR` (0.6), floors measured for their
own questions and reused, not tuned here.

| triple | melid | bpm | page | page bars | page notes | coverage | clock | transp. |
|---|---|---|---|---|---|---|---|---|
| Blues For Alice | 53 | 169 | Omnibook | 12-49 | 278 | 0.892 | 0.964 | 0 |
| Donna Lee | 55 | 226 | Omnibook | 31-96 | 373 | 0.901 | 0.997 | 0 |
| KC Blues | 58 | 118 | Omnibook | 13-38 | 189 | 0.899 | 0.936 | 0 |
| My Little Suede Shoes | 60 | 146 | Omnibook | 33-66 | 257 | 0.930 | 0.992 | 0 |
| Ornithology | 61 | 222 | Omnibook | 33-65 | 200 | 0.855 | 0.971 | 0 |
| Yardbird Suite | 68 | 210 | Omnibook | 32-64 | 196 | 0.893 | 0.938 | 0 |
| Embraceable You | 56 | 72 | PDF, silver | 1-33 | 437 | 0.963 | 0.998 | +9 (alto) |
| Cheese Cake | 121 | 221 | PDF, silver | 1-114 | 587 | 0.917 | 0.974 | +14 (tenor) |

All eight are the same take; the WJazzD fit is accepted by the harness's own
rule on all eight (match rate 0.78-0.90). The six Omnibook sides are every
side WJazzD also annotated whose recording is under `benchmark/wjazzd/`, KC
Blues included; the two PDF pages are the silver ones whose recording was
already a WJazzD track. Every one is a dev track.

The check is only worth something if wrong pairings fail it. Five that must:

| control | coverage | clock | verdict |
|---|---|---|---|
| Ornithology, WJazzD's 1946 solo against the 1948 broadcast page | 0.266 | 0.195 | refused |
| Donna Lee, Parker's solo against Ryan Kisor's page | 0.298 | 0.236 | refused |
| Blues For Alice against the Omnibook's Confirmation | 0.252 | 0.178 | refused |
| My Little Suede Shoes against Blues For Alice | 0.360 | 0.239 | refused |
| Cheese Cake against Donna Lee | 0.312 | 0.215 | refused |

Right pairings read coverage 0.855-0.963 and clock 0.936-0.998; wrong ones
0.252-0.360 and 0.178-0.239. The same take of the same tune, by another
transcriber, would sit with the first group; another take of it sits with
the second (Ornithology 1948).

## The scores

Rhythm, per triple:

| triple | (f) Flex-Q | (a) | (b) | (c) |
|---|---|---|---|---|
| Blues For Alice | 0.701 | 0.769 | 0.761 | 0.693 |
| Donna Lee | 0.685 | 0.882 | 0.837 | 0.841 |
| KC Blues | 0.659 | 0.681 | 0.664 | 0.646 |
| My Little Suede Shoes | 0.770 | 0.867 | 0.896 | 0.861 |
| Ornithology | 0.580 | 0.787 | 0.786 | 0.730 |
| Yardbird Suite | 0.588 | 0.859 | 0.801 | 0.756 |
| Embraceable You | 0.912 | 0.879 | 0.876 | 0.849 |
| Cheese Cake | 0.621 | 0.792 | 0.844 | 0.817 |
| **mean** | **0.690** | **0.815** | **0.808** | **0.774** |

Means of the other three, over the same eight:

| measure | (f) | (a) | (b) | (c) |
|---|---|---|---|---|
| value | 0.646 | 0.782 | 0.782 | 0.729 |
| coverage | 0.906 | 0.894 | 0.896 | 0.851 |
| on the bar | 0.853 | 0.873 | 0.852 | 0.834 |

Row (c) is the page we ship, and it sits where the Omnibook set already
reads (rhythm 0.780 over 22 sides): the triples are not unusual pages.

## Where the distance from the page goes

Mean over the eight, `1 - (c)` split three ways:

| measure | writing | grid | hearing | total |
|---|---|---|---|---|
| rhythm | **0.185** | 0.006 | 0.034 | 0.226 |
| value | **0.218** | 0.000 | 0.052 | 0.271 |
| coverage | 0.106 | -0.002 | 0.044 | 0.149 |
| on the bar | 0.127 | 0.021 | 0.017 | 0.166 |

Paired over the eight (95% interval resampled by triple, exact sign test):

| step | rhythm | value | coverage | on the bar |
|---|---|---|---|---|
| grid, (a) to (b) | -0.006 [-0.029, +0.017], 2 up 5 down | -0.000, 4/4 | +0.002, 4/1 | -0.021 [-0.071, +0.019], 3/5 |
| hearing, (b) to (c) | -0.034 [-0.048, -0.019], 1/7, p=0.07 | -0.052 [-0.078, -0.028], 1/7 | -0.044, 1/7 | -0.017, 0/8, p=0.01 |
| Flex-Q to ours, (f) to (a) | +0.125 [+0.058, +0.189], 7/1, p=0.07 | +0.136, 7/1 | -0.012, 0/7 | +0.019, 6/2 |

**On these eight solos, 82% of the rhythm distance and 80% of the value
distance from a human page is there with a human's onsets on a human's beat
grid.** Hearing is 15% of the rhythm distance and grid 3%, and the grid step
cannot be told from zero. Hearing is real and consistent -- down on 7 of 8
for rhythm, value and coverage, 8 of 8 on the bar -- but it is the smaller
part. The grid's one visible cost is Cheese Cake on the bar (0.877 on
WJazzD's grid, 0.703 on ours), the slip at bar 84 docs/roadmap.md already
traced to our grid by two references.

What "writing" holds, and why it is an upper bound on what the quantizer
owes: (1) our choices where the timing pointed at the page's place; (2)
conventions the page applies that the raw timing does not carry (next
section) -- still the quantizer's to learn; (3) the page's own errors --
two are OMR readings, and the Omnibook is an edited book; (4) two humans
disagreeing about which notes exist (the annotation covers 0.855-0.963 of
the page before anything is notated, which is most of (a)'s coverage
loss). Only (3) and (4) are not ours to fix, and no second human page of
any of these takes exists, so there is no human-against-human ceiling to
quote.

By set: the six Omnibook sides read writing 0.192 / grid 0.017 / hearing
0.037 on rhythm, the two PDF pages 0.165 / -0.025 / 0.027.

**Flex-Q is further from a human page than our quantizer**, on the same
onsets: rhythm 0.690 against 0.815, ours higher on 7 of 8. Its commonest
disagreement is a swung pair filed at 2/3 (binary read as a triplet: 11.8%
of its matched notes, 11.1% of all intervals wrong on that alone). That is
D36 measured: the layer is a literal quantisation, not a page. The one page
where Flex-Q wins is the ballad (Embraceable You, 0.912 against 0.879, and
coverage 0.963 against 0.904), below.

## What (a) disagrees with, by kind

Every matched note of (a) against the page, in one class
(`triples.position_class`), after reconciling the two bar-1s locally. Pooled
over the eight: 2,263 matched notes, 1,950 intervals of which 345 are wrong
(pooled rhythm 0.823). "Charged" is the share of ALL intervals that are
wrong because of that class (each wrong gap charged to the end that moved).
The raw columns are the annotated onset behind each note, on WJazzD's grid
-- the grid (a) was notated on, so it is the same clock: its phase in the
beat, how many onsets its beat holds, and whether the onset sounded nearer
the page's place or ours.

| class | notes | charged | raw phase q1 / median / q3 | onsets in beat 1/2/3/4+ (%) | nearer page / ours (%) |
|---|---|---|---|---|---|
| hit | 63.1% | - | | 16/55/16/14 | |
| **offbeat written on a beat** | 3.1% | **3.5%** | 0.10 / 0.42 / 0.92 | 32/49/14/4 | 7 / 90 |
| **triplet read binary** | 7.0% | **3.3%** | 0.40 / 0.57 / 0.73 | 4/23/27/46 | 32 / 63 |
| page sixteenth written on an eighth | 4.5% | 2.3% | 0.28 / 0.53 / 0.94 | 5/21/31/44 | 11 / 87 |
| downbeat written on an and | 2.2% | 2.2% | 0.42 / 0.55 / 0.74 | 39/43/10/8 | 16 / 78 |
| downbeat written on the e | 3.2% | 2.1% | 0.20 / 0.25 / 0.30 | 8/35/33/24 | 0 / 100 |
| offbeat written late (dotted figure) | 1.8% | 1.1% | 0.74 / 0.81 / 0.85 | 5/32/37/27 | 0 / 98 |
| binary read as triplet | 1.8% | 1.0% | 0.46 / 0.61 / 0.75 | 0/0/95/5 | 12 / 85 |
| a beat or more apart | 0.5% | 0.5% | | | |
| a 32nd apart | 7.4% | 0.4% | | 1/2/12/85 | 8 / 84 |
| downbeat written on the a before | 0.5% | 0.3% | 0.77 / 0.85 / 0.87 | | 0 / 67 |
| offbeat written early (sixteenth) | 0.7% | 0.3% | 0.28 / 0.35 / 0.46 | | 33 / 60 |
| everything else | 4.2% | 0.7% | | | |

The same notes by where they SOUNDED -- each note's raw phase to the nearest
eighth of a beat, and where each side wrote it relative to the sound (beats,
rounded to an eighth):

| sounded at | n | same place | the page writes it | we write it |
|---|---|---|---|---|
| the beat (0.94-0.06) | 358 | 70% | on it 71%, a 16th early 12%, an eighth early 6% | on it 99% |
| 0.06-0.19 | 352 | 79% | on the beat 87% | on the beat 87%, as played 10% |
| **0.19-0.31** | 232 | **53%** | **on the beat 69%**, on the "e" 11% | on the beat 50%, **on the "e" 44%** |
| 0.31-0.44 | 165 | 33% | the "e" 33%, the beat 24%, the "and" 15% | the "e" 40%, as played 24%, the "and" 20% |
| 0.44-0.56 | 209 | 49% | the "and" 52%, a 16th early 19% | the "and" 74% |
| 0.56-0.69 | 385 | 73% | the "and" 80% | the "and" 83% |
| 0.69-0.81 | 329 | 65% | the "and" 68%, the "a" 13% | the "and" 66%, the "a" 20% |
| **0.81-0.94** | 233 | **52%** | next beat 37%, **the "and" 27%**, the "a" 24% | next beat 40%, the "a" 31%, as played 15% |

Two things follow.

**The page's departures are mostly conventions, not finer timing.** Of the
834 matched notes (a) did not place where the page did, the onset sounded
nearer the PAGE's place for 102 (12%): those a better snap could find. For
692 (83%) it sounded nearer ours, and the page applied a reading the raw
timing does not carry: the swung "and" for an offbeat played at 0.81 (the
dotted class, 98% nearer ours), the beat for a downbeat played a sixteenth
late (the "e" class, 100%), an anticipation for a note played ON the beat
(12% + 6% of the notes that sounded there, where we write the beat 99% of
the time). These are the quantizer's rules' territory -- the warp, the lag,
the sparse-beat gate -- and they are where the page is won or lost.

**Half-beat displacements are the largest single charge**: an offbeat
written on a beat and a downbeat written on an "and", 5.7% of all
intervals, a third of (a)'s rhythm deficit. The raw onsets side with us
(90% and 78%): these notes sounded where we wrote them and the page puts
them half a beat away. In the first, 59 of the 71 notes sounded within a
fifth of a beat of a beat line, either side of it, and the page writes
them on the "and" before -- an anticipation where we write the beat (for
the ones just before the line, R29's "an onset at 0.88 or later is the next
downbeat, early" is the rule in play). The second is its mirror: notes that
sounded on the "and" (median 0.55) written on a beat. Together they look
like phrases displaced by an eighth, and they concentrate on two pages --
Cheese Cake's OMR reading (9.6% of its matched notes in these two classes)
and KC Blues, the slow blues (10.7%), against 3.0% on Donna Lee -- so part
of this is page error, and none of it is readable from onset timing
alone.

**Triplets are the second.** The page writes 13.2% of its notes as tuplets
(the Omnibook sides 16.9%); (a) writes 4.1% (5.0%). "Triplet read binary"
is 7.0% of matched notes and 3.3% of intervals; a third of those onsets
sound nearer the page's third than our binary place. Their beats hold four
or more annotated onsets 46% of the time -- a triplet on the page where the
annotator heard more notes (grace notes, ghosted notes the page leaves out)
-- three onsets 27%, two 23%. Loosening the gate does not reach them (below).

**The laid-back downbeat is still written on the "e".** 3.2% of matched
notes, every one played 0.20-0.30 of a beat late; the page writes the beat.
Of all notes that sounded a sixteenth late, the page writes the beat 69% of
the time and we write the "e" 44%. R29's lag takes out a line that SITS
behind (without it these grow from 72 to 90 notes); what is left are late
downbeats inside a line that does not, which a window median cannot see.

**The ballad writes finer than we do.** "Page sixteenth written on an
eighth" is 15.2% of Embraceable You's matched notes and "a 32nd apart" 28.9%
(0.0-7.1% and 0.3-8.9% on every other side): at 72 bpm the page writes
sixteenths and 32nds where we write eighths and sixteenths.

### Values and rests

(a)'s value is 0.782 (mean of eight); pooled, 20.9% of its matched notes
carry the wrong length. **17.9 of those points sit beside a note or a
position that differs** -- rhythm wearing a value, as `value_confusion.py`
found on our own notes (61% of wrong lengths on the hand scores had no rest
on either side) -- and 2.8 are a choice of length with both notes and both
positions agreeing: we rest where the page holds (1.6), both rest but
differently (1.1), we hold where the page rests (0.1). The
commonest wrong pairs: our eighth where the page has a sixteenth (3.1% of
matched notes) and the reverse (2.7%), our eighth where the page holds a
quarter (2.5%), our eighth where the page has a triplet eighth (2.0%).

Written symbols over the bars that hold the solo:

| | page | (f) | (a) | (b) | (c) |
|---|---|---|---|---|---|
| notes | 2643 | 2803 | 2580 | 2580 | 2613 |
| rests per note | 0.12 | 0.10 | **0.18** | 0.18 | 0.14 |
| tuplet notes | 13.2% | 28.8% | **4.1%** | 5.3% | 6.8% |
| dotted notes | 1.5% | 7.5% | **5.7%** | 4.9% | 5.2% |
| tie starts | 4.6% | 9.9% | 3.8% | 3.5% | 4.0% |
| rests: eighth | 34.8% | 27.2% | **61.0%** | 60.3% | 60.2% |
| rests: quarter | 33.0% | 30.1% | 19.8% | 21.3% | 20.3% |
| rests: half | 15.8% | 15.8% | 10.4% | 10.2% | 9.3% |
| rests: 16th | 11.2% | 11.4% | 2.6% | 3.5% | 3.3% |
| rests: dotted quarter | 0 | 0 | 0 | 0 | 0 |

The six Omnibook sides alone write dotted notes 0.4% of the time against our
5.7%, and 0.12 rests per note against 0.18; the page's sixteenth rests are
the two PDF pages' (23.9% of their rests, 2.6% of the Omnibook's). With the
annotator's note-offs, which are earlier than CREPE's gated extents, (a)
writes MORE rests than our own page (c) does: the rest excess is a notate
convention (a human holds a note to the next one unless the gap is real),
not a hearing artefact. Filling gaps by rule is not the fix (next section).

## The rules, switched the other way

Each rule the other way from what ships (`config.QuantizeConfig`,
`NotateConfig`), by environment override, all three inputs re-notated,
paired over the eight. Rows are (a) unless marked; mean change, 95%
interval, triples up / down (level within 0.002), sign test.

| rule, switched | rhythm | value | on the bar | notes written |
|---|---|---|---|---|
| R27 sixteenth gate off | -0.009 [-0.016, -0.002], 1/6, p=0.12 | **-0.011 [-0.020, -0.004], 0/6, p=0.03** | -0.002 | 0 |
| R28 tuplet-inside off | +0.003, 3/2 | +0.008 [+0.003, +0.013], 5/0, p=0.06 | **-0.004, 0/7, p=0.02** | 0 |
| R29 lag off | -0.011 [-0.022, +0.000], 3/5 | -0.008, 3/5 | -0.002 | +4 |
| R31 ballad grids on (Embraceable You only) | +0.006 | +0.011 | +0.010 | **+18** |
| R31, on our own notes (c) | +0.021 | +0.021 | -0.012 | +25 |
| R33 figure prior off | -0.001, 3/3 | -0.010 [-0.018, -0.001], 1/7, p=0.07 | +0.005, 6/1, p=0.12 | -27 |
| tuplet gate at 2 onsets | -0.010 [-0.020, -0.002], 1/7, p=0.07 | -0.008, 1/6 | **-0.007, 0/6, p=0.03** | 0 |
| sixteenth triplets on | -0.006 [-0.012, -0.001], 0/4, p=0.12 | -0.006, 0/4 | -0.000 | 0 |
| offbeat-pair tuplet on | -0.003, 2/2 | -0.003, 2/2 | -0.001 | 0 |
| grid slack off | -0.002, 1/4 | **-0.004 [-0.007, -0.002], 0/6, p=0.03** | +0.002, 3/0 | 0 |
| legato cap a quarter | 0 | **-0.016 [-0.027, -0.008], 0/8, p=0.01** | 0 | 0 |
| legato fill 0.75 | 0 | -0.000, 1/1 | 0 | 0 |
| swing warp off | -0.011, 3/5 | -0.007, 4/4 | -0.005, 3/5 | +5 |
| swing warp off, on our grid (b) | -0.027, 1/7, p=0.07 | -0.020, 1/6 | **-0.018, 0/8, p=0.01** | -4 |
| literal 16ths (no swing reading at all) | **-0.152 [-0.231, -0.068]**, 2/6 | -0.146, 1/7, p=0.07 | -0.007 | +43 |

On (c), our own notes, the same switches move less and less consistently
(R27 off: rhythm level 2/2, value -0.003; R29 off: -0.004; R33 off: +0.002
rhythm, -0.003 value): the hearing noise the (a) row is free of is what the
page-level scorecard sees.

## What it says about R27-R33

Eight solos, seven of them Parker and six from one book: every verdict
below is a direction, not a settlement. `p` is the two-sided sign test over
the eight.

- **R27, the sixteenth needs three onsets: supported.** Off, value falls on
  6 of 6 that move (p=0.03) and rhythm on 6 of 7; the dotted figure grows
  from 41 notes to 50, the "a before" from 12 to 26, the "e" from 72 to 80.
  On our own notes (c) it is level on these eight (2 up, 2 down); it
  shipped on the Omnibook's 22 sides (0.730 -> 0.758, 21 up), a set eight
  solos of hearing noise cannot stand in for.
- **R28, a triplet needs its onsets inside: mixed, keep.** Off buys value
  (+0.008, 5 up, none down) and costs placement (on the bar down on 7 of 7
  that move, p=0.02). The trade is on the record; nothing here says flip it.
- **R29, the lag: supported, and not finished.** Off, rhythm -0.011 (3 up,
  5 down, interval touching zero), notes on the "e" 72 -> 90, dotted
  figures 41 -> 65. What it leaves is the isolated late downbeat: 72 notes
  played 0.20-0.30 late inside a line that does not lag.
- **R30, rests show the beat: supported.** Not one dotted-quarter rest on
  either side over the eight (0 of 454 ours, 0 of 330 the pages').
- **R31, ballad grids: the first human ballad page says ON.** Embraceable
  You (72 bpm, a silver OMR page) is the first page under 86 bpm the
  benchmark has had. With the rule on, (a) gains on all four measures
  (rhythm +0.006, value +0.011, coverage +0.037, on the bar +0.010) and
  keeps 18 of the 31 notes it otherwise drops; our own page (c) gains
  rhythm +0.021, value +0.021, coverage +0.041 for on the bar -0.012. And
  the page is written LITERALLY: Flex-Q's fine divisions score 0.912 against
  our 0.879 there, and plain nearest-sixteenth writing beats our swing
  reading on it (+0.033 on (a), +0.058 on (c)) -- the opposite of D36's
  reason for switching R31 off ("the literal reading a transcriber
  simplifies most at exactly that tempo"). One page, one transcriber, read
  by OMR: evidence for re-opening R31 with the ~24 ballad pages of A3, not
  yet for flipping it.
- **R32, the pulse octave: not exercised.** No half-rate grid among the
  eight.
- **R33, the figure prior: weakly supported.** Off, value -0.010 (7 of 8
  down, p=0.07), rhythm level (3/3), on the bar +0.005 (6 up, p=0.12), and
  27 notes the guards keep are dropped (coverage down on 7 of 7). On human
  onsets the prior helps value a little and costs placement a little.
- **The rest of the grid choice holds.** The three-onset tuplet gate (at
  two: rhythm 7 of 8 down, on the bar 6 of 6 down, p=0.03), sixteenth
  triplets off (on: 4 of 4 down), the coarsest-within-slack rule (off:
  value 6 of 6 down, p=0.03). The offbeat-pair tuplet is level (2/2):
  no evidence either way. `legato_cap` stays off (a quarter: value down on
  all 8, p=0.01) and `legato_fill` is inert on these notes.
- **The swing reading is worth 0.15 of rhythm** (literal sixteenths:
  -0.152 on (a), down on 6 of 8; the two up are the two slowest, the ballad
  at 72 and KC Blues at 118). The warp alone is worth more on OUR grid
  than on the annotator's (off: -0.027 and on the bar 0 of 8 on (b),
  -0.011 on (a)).

## What the quantizer should work on

In the order the (a) row charges them, with no hearing or grid error in the
way:

1. **Half-beat displacements** (5.7% of intervals). Not in the onset timing;
   part page error. The instrument to build first is a page-side check --
   does the displaced phrase sit in a bar that does not fill its signature,
   the question `evaluation.page_steps` asks of a bar-line step (an OMR bar
   that loses an eighth rest moves every note after it by an eighth) --
   then the anticipation reading: a note on or just before the beat that a
   transcriber writes on the "and" before it.
2. **Triplets** (3.3%). The page writes three times our tuplet share. A third
   are timing-readable; most sit in beats where the annotator heard more
   notes than the page writes, so the gate is not the lever (loosening it
   loses). A reading that lets a triplet absorb a grace note is.
3. **The page's sixteenths written as eighths** (2.3%), mostly the ballad:
   R31's territory.
4. **The laid-back downbeat on the "e"** (2.1%): the isolated late downbeat
   R29's window cannot see.
5. **Values are rhythm**: 17.9 of the 20.9 wrong-value points (pooled)
   follow a position. The rest-per-note excess (0.18 against 0.12) is the one value
   question of its own, and filling gaps by a cap is measured wrong.

The larger conclusion, for the roadmap: on these eight the page is lost in
WRITING, four to five times more than in hearing (value 4.2x, rhythm 5.4x),
and most of what is lost is a transcriber's convention rather than timing a
finer grid would recover: only one misplaced note in eight sounded nearer
the page's place than ours, and the literal readings (Flex-Q, 0.125 lower;
plain sixteenths, 0.152 lower) are further from the page than the rules
are. What remains is how a human READS a performance -- which can be
learned from exactly this material, onsets paired with pages, and the PDF
corpus with its audio is where more of it comes from.

## Caveats

- **Eight solos, seven by Parker, six from one book.** The Omnibook is an
  edited transcription of 1940s sides; the two PDF pages are OMR readings
  (silver). Tempo 72-226 bpm, one ballad, one Latin feel. Every mean here
  is over eight and every sign test has eight draws.
- **Writing includes the page's errors and the two humans' disagreements**,
  and there is no human-against-human ceiling for rhythm on any of these
  takes.
- **(b)'s downbeat is a human's.** The WJazzD tracks' sidecar anchors were
  voted from WJazzD's own bars (`wjazz.bar_anchors`), so the grid step here
  is the beat times and the repair, not the downbeat phase (which D32 puts
  right on 95 of 96 tracks anyway).
- **D36**: WJazzD's tatum is Flex-Q's and enters only row (f). The onsets,
  pitches, durations and beats used for (a)-(c) are the annotator's.
- A grace note on a MusicXML page has no duration, so the parser puts it at
  its main note's position and `melody` keeps the higher of the two: a
  page's grace note is at worst a substitution or a missing note here, never
  a rhythm error. The written-symbol counts leave grace notes out.

## Reproducing

    uv run python scripts/triples.py --db wjazz/wjazzd.db
    uv run python scripts/triples.py --db wjazz/wjazzd.db --ab --json out.json

It reads `.benchmark-notes-c0.2-d0.0.json` and `.benchmark-grids.json` (what
`run_eval` writes), the database, and the pages under `benchmark/`; a
minute and a half without `--ab`, seven minutes with. `--json` holds
per-triple aggregates and the pooled tables, never a note. A new triple is a row in `TRIPLES`: the
WJazzD melid, the WJazzD copy of the recording under `benchmark/wjazzd/`
(its cached run and grid), and the page; the take check decides whether it
is scored.
