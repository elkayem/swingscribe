# Writing, round 2: rules for the classes the triples expose

2026-09-30. `scripts/writing_ab.py --db wjazz/wjazzd.db --a1b --rules all`
(docs/roadmap.md A1, the follow-up docs/triples.md asked for), no audio:
the WJazzD database, the pages under `benchmark/`, and SNAPSHOTS of the
harness's note and grid caches taken before the horn hole-filler (A2)
re-transcribed the horns -- the CREPE-only notes the committed pins were
made from.

docs/triples.md found that 82% of the rhythm distance between our page and
a human's is there with PERFECT onsets on a perfect grid: the (a) row,
WJazzD's onsets notated on WJazzD's grid, is transcriber convention, and it
named the classes. This round asks two things of them: whether the largest
class, the half-beat displacement, is ours at all (A1b), and whether the
smallest rule that could plausibly fix each of the others survives the
pages.

**The answer is no rule.** Four new rules, one per class a rule could
reach, each behind a field that is OFF and dumps nothing at its default (so
no cache key and no pin moved): `QuantizeConfig.late_downbeat_max_onsets`,
`isolated_lag_max_onsets`, `tuplet_pushed_last` and
`NotateConfig.hold_to_beat`. `legato_cap` and R31's ballad grids were read on
the same instrument. Every rule shrinks its own class on the (a) row; not
one is decided up on the hand scores or the Omnibook, the late downbeat and
the hold (at either setting) are decided DOWN there, the pushed triplet is
decided down on (a)'s placement, and the isolated lag is level at two
onsets and drops a note at three. The half-beat class is not the pages'
OMR (5% of it sits where a page bar could have lost time) and not readable
from timing (8% of on-beat notes are anticipated). What is left on
the page is how a transcriber READS a phrase. The hold fails on human onsets
too, because the condition it needs is a fact about the page's next note,
not our line's. The late-downbeat rule is right 29 to 4 on the Omnibook
where the page writes the note on the beat or the "e", and moves nearly as
many notes again that the page writes somewhere else -- mostly in beats the
page fills with more notes than we heard.

## The criterion and the three sets

A rule is RECOMMENDED only if it is decided up on the pages (the hand
scores or the Omnibook, 95% interval excluding zero), is not decided down
on any of the three sets, and drops no note. Each rule is switched on by
environment override, which every `Config` the stages build reads and every
worker inherits, against the shipped defaults in the same run:

1. **The triples**, paired over the eight of docs/triples.md, through
   `scripts/triples.py`'s own builders: (a) WJazzD's onsets on its grid (no
   hearing, no grid error) and (c) our notes on our grid.
2. **The pages**: the twelve hand scores (paired by recording) and the 22
   Omnibook sides (located pages trusted on both sides), through `run_eval`'s
   own notation path (`notate_run`, `score_notation_page`), default takes
   only, with `evaluation.paired_change`.
3. **The WJazzD quantizer instrument** (`scripts/wjazz_quantize.py`, 452
   solos, 198,983 annotated notes, 4,203 dropped at baseline), for
   COLLATERAL only: the notes a rule drops. D36: it judges nothing else.

Cells below are the mean change [95% interval] and recordings up/down
(level within 0.002); `*` marks a decided change. `edit_cost` is edits per
100 reference notes, so UP is worse.

## Summary

| rule (setting) | (a) rhythm | (a) value | hand rhythm | hand value | Omnibook rhythm | Omnibook value | on the bar, hand / Omnibook | Flex-Q dropped | verdict |
|---|---|---|---|---|---|---|---|---|---|
| late downbeat, 2 onsets | +0.0002, 1/1 | +0.0004, 2/1 | **-0.0012 [-0.0024, -0.0002]\*, 0/4** | -0.0006, 0/2 | -0.0005, 3/6 | +0.0003, 6/5 | **-0.0010\* / -0.0012\*** | 0 | down |
| late downbeat, 3 onsets | +0.0042, 3/2 | +0.0028, 4/2 | **-0.0014 [-0.0028, -0.0000]\*, 1/5** | -0.0005, 1/3 | -0.0015, 4/7 | +0.0007, 8/7 | **-0.0012\* / -0.0018\* (0/9)** | 0 | down |
| isolated lag, 2 onsets | +0.0015, 2/0 | +0.0010, 1/0 | -0.0004, 0/2 | -0.0002, 0/1 | +0.0005 [+0.0000, +0.0012], 2/0 | +0.0002, 2/0 | +0.0002 / +0.0004 | 0 | level |
| isolated lag, 3 onsets | **+0.0026 [+0.0005, +0.0054]\*, 3/0** | **+0.0025\*, 2/0** | -0.0007, 0/3 | -0.0002, 0/1 | -0.0004, 3/4 | -0.0005, 2/4 | -0.0004 / -0.0006 | **+1** | drops a note |
| tuplet, pushed last | +0.0003, 2/2 | +0.0017, 2/1 | -0.0002, 2/1 | -0.0001, 1/1 | -0.0002, 3/2 | +0.0001, 4/2 | -0.0005 / +0.0003; (a) **-0.0030\*, 0/4** | -1 | down on (a) |
| hold to beat, 1 | 0 | **-0.0081 [-0.0127, -0.0040]\*, 0/6** | 0 | -0.0067 [-0.0152, +0.0027], 2/9 | 0 | **-0.0262 [-0.0330, -0.0196]\*, 0/21** | 0 / 0 | 0 | down |
| hold to beat, 2 | 0 | **-0.0079\*, 0/6** | 0 | -0.0093 [-0.0204, +0.0021], 3/8 | 0 | **-0.0272\*, 0/21** | 0 / 0 | 0 | down |
| legato cap, a quarter | 0 | **-0.0159 [-0.0272, -0.0079]\*, 0/8** | 0 | **-0.0240 [-0.0381, -0.0100]\*, 1/11** | 0 | **-0.0319 [-0.0401, -0.0243]\*, 0/22** | 0 / 0 | 0 | down |
| R31 ballad grids (0.7 s) | +0.0008, 1/0 | +0.0014, 1/0 | 0 | 0 | 0 | 0 | 0 / 0 | -1,495 | no page to judge |

The (c) row -- our notes on the triples -- is in each section below; it
decided nothing on any rule except the two holds and the cap (value down,
0/7 each).

## A1b: the half-beat displacements are not the page's OMR

120 matched notes of (a) are an offbeat written on a beat (71) or a
downbeat written on an "and" (49) -- 5.7% of all intervals, the largest
charge. Each was placed by the bar it sits in on the page
(`evaluation.reader_bars`, `fills`, and the time a page had gained or lost
by that bar, `overrun`):

| where the displaced note sits | notes | share |
|---|---|---|
| in a page bar that does not fill its signature | 1 | 0.8% |
| next to one | 1 | 0.8% |
| on a page running about half a beat off (standing overrun) | 4 | 3.3% |
| bars fill; beside a note only one side has | 60 | 50.0% |
| bars fill; both neighbours matched | 54 | 45.0% |

**At most 6 of 120 (5%) could be OMR losing time**, all six on the two PDF
pages (the half-beat-off four are Embraceable You's). The Omnibook sides
hold 64 of the 120 and none of them sits near a bar that does not fill. And
they are NOT displaced phrases -- an OMR bar that loses an eighth moves every
note after it to the next bar line: runs of consecutive displaced notes are
83 single notes, 14 pairs and 3 of three. **The page writes the note
EARLIER than we do in 96 of 120 (80%)**: anticipation, a transcriber's
reading. Half of them sit beside a note only one side has -- the annotation
and the page disagree about a neighbouring note, and the missing neighbour
may itself be what displaced the match -- and 54 are clean.

So the class is ours, but is it readable from timing? Every matched note
that SOUNDED within 0.15 of a beat line and that we wrote on the beat, by
where the page puts it:

| notes | n | the page writes the beat | the "and" before | elsewhere |
|---|---|---|---|---|
| all | 687 | 531 (77%) | 54 (8%) | 102 (15%) |
| played a beat or more | 47 | 24 | 20 | 3 |
| ... and sounded before the line | 24 | 10 | 12 | 2 |
| ... and the note before matched | 34 | 21 | 10 | 3 |
| played a beat and a half or more | 17 | 6 | 9 | 2 |
| played two beats or more | 6 | 1 | 5 | 0 |

No condition with 20 notes or more gives the anticipation a majority; the
long notes lean that way on counts too small to act on (17 and 6 notes, out
of 2,263). **No rule was built.** A phrase a transcriber writes anticipated
is a reading of the phrase -- the tie across the bar line into a long note
-- and the evidence for it is not in the onset.

## The late downbeat on the "e" (2.1%), and the dotted figure (1.1%)

The class: a downbeat played 0.20-0.30 of a beat late inside a line that
does not lag, which R29's window median cannot see, written on the "e".
Among (a)'s notes whose first onset in the beat sounded 0.12-0.36 late and
which we wrote on the "e" (66), the page writes the beat 64% and the "e"
17%; by the beat's onset count, 2 onsets 76% the beat, 3 onsets 67%, 4
onsets 31% (the "e" 54% -- a run of sixteenths starting late is a run). The
dotted class is largely the same thing: in 8 of its 11 two-onset beats the
downbeat sounds about a quarter of a beat late and carries its swung
offbeat with it (to 0.75-0.9), which the page writes (0, 0.5) and we write
(0.25, 0.75). Two rules, for beats of at most 2 or 3 onsets:

- **`late_downbeat_max_onsets`** (`quantize.late_downbeats`): after the grid
  is chosen, a beat whose earliest note is written on the "e", with nothing
  on its line and nothing pushed there by the beat before, has that note
  written on the beat. One note moves, the rest stay.
- **`isolated_lag_max_onsets`** (`quantize.isolated_lags`): the same beat read
  as R29 reads a lagging line -- shifted by its own first onset (0.15-0.35,
  capped at `lag_cap`) before the grid is chosen, for a beat R29's window
  gave no lag. Two guards were forced by the collateral instrument: the beat
  before must hold nothing from 0.75 on (its note may be written on this
  beat's line; 18 notes dropped without it, at 2 onsets), and the beat's own
  last onset must sit before `LAG_PUSH_MIN` (unwarped by the lag, the "a"
  becomes the next beat's line and its note; 5 more). With both, 2 onsets
  drops none and 3 onsets one.

On (a) both do what the class says: late downbeat 3 moves 11 notes off the
"e" and 10 onto a hit; isolated lag 3 is decided up on rhythm and value.
On (c) they lean up and decide nothing (late downbeat 3: rhythm +0.0035,
4/2; isolated lag 3: -0.0004, 2/1). **On the pages the late-downbeat rule is
decided down on the hand scores' rhythm (2 onsets 0/4, 3 onsets 1/5) and on
the bar on both sets** (Omnibook 0 up / 9 down at 3 onsets); the isolated
lag reaches four matched page notes a set at 2 onsets and reads level.

Why the pages disagree with (a), measured on the notes the rule MOVES
(`writing_ab.py --moved`: every matched page note whose place against the
page changed):

| rule | set | moved | page = where we moved it | page = where it was | neither |
|---|---|---|---|---|---|
| late downbeat 3 | Omnibook | 60 | 29 | 4 | 27 (16 in a beat the page fills fuller than we do) |
| late downbeat 3 | hand | 13 | 2 | 3 | 8 (5 fuller) |
| late downbeat 2 | Omnibook | 41 | 23 | 1 | 17 |
| isolated lag 3 | Omnibook | 28 | 9 | 9 | 10 |
| isolated lag 3 | hand | 10 | 3 | 5 | 2 |

Where the page writes the note at the beat or the "e", the rule is right
29 to 4 on the Omnibook. But almost half the notes it moves are written
NEITHER place -- 21 of those 27 LATER on the page (by a sixth to a half of
a beat, all but one), and 16 of the 27 in a beat that holds more notes on
the page than in our line -- and moving those a sixteenth earlier moves
them away from the page, which the gap-based rhythm and the half-beat
`on_the_bar` both charge. The rule's precondition, "a beat of at most three
onsets", is a claim about the performance; on our notes it is a claim
about what we HEARD, and a beat we
heard two notes of is often a triplet or a run on the page. That is a
hypothesis about the mechanism with the counts above behind it, not a
measurement of hearing; the horn hole-filler (A2) changes exactly which
beats are sparse, so these two rules are worth one re-run after it lands.

## Triplets read binary (3.3%)

docs/triples.md suggested a triplet reading that absorbs a grace or ghost
onset, because 46% of these notes sit in beats with four or more annotated
onsets. Classified by the beat's shape (158 notes of (a) in 94 page beats):

| the annotated beat | notes | share |
|---|---|---|
| 3 onsets | 42 | 26.6% |
| 2 onsets, the page holds notes the annotation lacks | 31 | 19.6% |
| 4 onsets, the page writes a sixteenth-triplet turn (0, 1/6, 1/3, 1/2) | 30 | 19.0% |
| 4 onsets, the last at 0.88 or later, the page writes thirds and the next beat's note | 23 | 14.6% |
| 5 or more onsets | 20 | 12.7% |
| 1 or 2 onsets, the rest | 12 | 7.6% |
| 4 onsets, the page writes thirds and leaves one out (a ghost absorbed) | **0** | 0 |

**No ghost is absorbed anywhere**: the four-onset share is a turn figure or
the next downbeat played early. The turn is barely readable from timing:
over every fully matched four-onset beat of (a), those whose onsets all sit
inside the first three quarters with the first before 0.15 are written as
the turn 9 times in 14 -- 4 of the 8 evenly spaced, 5 of the 6 uneven -- and
fourteen beats in 2,263 notes is no basis for a grid the Omnibook already
refused in its general form (`sixteenth_triplets`: 0 up / 15 down on the
Omnibook). A laid-back triplet is not readable either: of 35 three-onset beats
whose first onset sounded 0.12-0.45 late, all matched, the page writes a
triplet from the beat 6 times, a binary figure from the beat 19, a late
binary figure 10. Neither was built.

The one subclass timing names is the pushed-in downbeat, which R28
(`tuplet_needs_onsets_inside`) refuses because thirds send the fourth onset
to 1.0. **`tuplet_pushed_last`** lets a ternary reading send exactly one
onset to the next line when it is the last, sits from `LAG_PUSH_MIN` (0.88)
on, the figure starts on the beat, the others alone pass the tuplet gate,
and the next beat has nothing of its own at the line. On (a) it removes 14
"triplet read binary" notes and adds 12 "binary read as triplet" (hits +7
net) -- half right, as the shape predicts: of (a)'s fully matched four-onset
beats with the first onset before 0.15 and the last from 0.88, the page
writes thirds in 5 of 18 and sixteenths in 11 -- and it costs on the bar
(-0.0030 [-0.0060, -0.0006]\*, 0 up / 4 down). (c) is level (rhythm -0.0017,
2/2) and so are both page sets. It keeps one note Flex-Q's default drops.

## A ballad's sixteenths written as eighths (2.3%)

R31's territory, re-read at the value it shipped with (`slow_beat_s` 0.7):
Embraceable You gains on (a) and (c) (the only triple under 86 bpm: rhythm
+0.006 and +0.021 on its own, value +0.011 and +0.021), 18 and 25 more notes
written, 1,495 fewer notes dropped on the WJazzD instrument, and NO hand
score or Omnibook side moves, because none is under 86 bpm. Unchanged from
docs/triples.md: not decidable here, and A3's ballad pages are what can
decide it.

## Rests: why `legato_cap` fails, and why holding to the beat does too

We write 0.18 rests per note on (a) against the page's 0.12. The human
pages, gap by gap between consecutive melody notes, over every file of
each set:

| the note starts on | the next note | Omnibook (50 files) held | hand scores (12) held |
|---|---|---|---|
| the beat | a beat later | 92% of 347 | 92% of 249 |
| the "and" | a beat later | 78% of 742 | 29% of 129 |
| the beat | a beat and a half later | 31% of 348 | 42% of 69 |

From the beat to the next beat the two corpora agree, so
**`hold_to_beat`** fills exactly that gap: a note ON a beat line whose next
onset is a whole number of beats later, up to the setting. It is decided
down on value wherever it is read, like the cap. The reason is in which
gaps it reaches. On (a), the notes on a beat line whose next note of OURS
is a beat later (101, the first note matched), against the page:

| the page, after the same note | n | page holds |
|---|---|---|
| its next note is ours too, a beat later | 35 | 31 |
| a note only the page has, inside our gap | 24 | 22 |
| its next note is ours, half a beat EARLIER (anticipated) | 22 | 22 |
| its next note is ours, a beat and a half later | 12 | 10 |
| other | 8 | |

**The gap the rule sees is our gap; the convention answers the page's.** In
two of three of our beat-long gaps the page's own gap is not a beat, and in
half of all of them (51 of 101) it is shorter -- a note we do not have, or
the next note anticipated -- where the page's note IS an eighth, which our
eighth-and-rest had right by accident. Held, it becomes a wrong quarter: on
(a) hold-to-beat fixes 27 values and breaks 48 (4 were wrong both ways),
and the cap fixes 28 and breaks 73. Counted by context
(`triples.VALUE_CLASSES`), "we rest where the page holds" falls
(-26 on (a), -55 on the hand scores) and "beside a note or position that
differs" rises more (+45, +65; +198 on the Omnibook). The discriminating
condition -- does the page's next note come a beat later -- is a fact about
the page. The rest excess is, to that extent, the anticipation class and
the missing-note class wearing a value, and there is no length rule for it.
On our own notes the direction is not even the same: against the Omnibook
we already HOLD where the page rests (81) more than we rest where it holds
(12).

## What else was measured and not built

- **An anticipation rule** (a long note on the beat written on the "and"
  before): no timing condition with 20 notes gives it a majority (A1b).
- **Grace absorption for a four-onset triplet**: nothing to absorb (0 of 158).
- **A turn-figure grid** for four even onsets: written both ways equally.
- **A late-triplet reading** (three even onsets from 0.12-0.45): a triplet on
  the page 6 times in 35.

## Reproducing

    uv run python scripts/writing_ab.py --db wjazz/wjazzd.db --a1b
    uv run python scripts/writing_ab.py --db wjazz/wjazzd.db --rules all \
        --notes <snapshot of .benchmark-notes-c0.2-d0.0.json> \
        --grids <snapshot of .benchmark-grids.json> --json out.json
    uv run python scripts/writing_ab.py --db wjazz/wjazzd.db --moved \
        --rules "late downbeat 3,isolated lag 3" --notes ... --grids ...

Four minutes a rule with four workers (the triples, 34 pages and 452 WJazzD
solos, each twice); `--sets` narrows it. It never writes the harness caches,
and `--json` holds aggregates only, never a note (WJazzD is ODbL and the
pages derive from commercial recordings). The per-note diagnostics above
that are not flags of the script (the value context by gap, the page
corpora's rests, the beat shapes) were scratch scripts over the same
builders; their counts are what is recorded here. `--moved` reproduces the
transfer table. This run was cut by a Windows resource error at the
seventh rule and finished in a second run with two workers; each run takes
its own baseline, so every row is paired against a baseline built in the
same process.

## Caveats

- **Eight triples, seven by Parker, six from one book**; every (a) and (c)
  interval has eight draws. The pages are twelve and 22.
- **The notes are CREPE-only.** The horn hole-filler (A2) adds short notes
  to every horn; a rule whose failure is a sparse beat on our side -- the
  late downbeat, above -- should be re-read on its notes.
- `on_the_bar` rounds to the nearest half beat, so a note moved a sixteenth
  flips it only where the page writes the note half a beat or more from the
  new place. The rhythm measure is the primary, and the two agree in sign
  on every decided row but the pushed triplet's placement on (a), where
  rhythm reads +0.0003.
- The working tree held other tasks' edits on the scoring path
  (`notation.py`, `model.py`, `config.py`); the last of them was saved at
  07:56, and these runs began at 09:18, so nothing moved under them. Every
  comparison is paired against a baseline built in the same run.
