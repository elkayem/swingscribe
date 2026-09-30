# E4-E6: edit cost, confidence against the errors, stratified means

2026-09-30. The three planned measures of `docs/roadmap.md` section 2, and
the OMR step check the first three PDF pages asked for, built into
`scripts/run_eval.py` before the new pages are scored, so the pages judge the
next change instead of being spent on tuning it.

Every number below is from

    run_eval.py --db wjazz/wjazzd.db --cache-dir benchmark/.swingscribe-cache --jobs 2

with every note and grid cached (no transcription, no separation), run four
times: twice for the first reading and once after each of two reviews. Not
one of the 2,832 committed pins moved (largest drift 0.000000) and none
vanished in any run, and the last run reproduced every one of the 714 keys
the earlier runs added, exactly. 796 new keys are pinned; the erasure rows
and the strata are printed and written with `--json`, never pinned (see E5
and E6 for why). A third review found the OMR step check wrong on Embraceable
You; it was rewritten (below) and the run repeated a fifth time: one pin
moved, that page's `page_steps` 0 -> 3, and it was re-pinned alone. No other
of the 3,628 pins moved (largest drift 0.000000) and none vanished. A fourth
review refuted that rewrite's rule -- it judged the rounded half-beat labels
and gave every half-beat step to the page -- and the check was rewritten
again to judge the unrounded offsets (below). A sixth run moved no pin at
all: `page_steps` reads 3, 1 and 0 on Embraceable You, Gingerbread Boy and
Cheese Cake as before, all 3,628 pins held (largest drift 0.000000), none
vanished, none appeared, and nothing was re-pinned. Only the trace lines,
which are strings and never pinned, changed.

## E4. Edit cost per 100 reference notes

**What it asks.** How much would a reader have to fix to turn our page into
the human's? Rhythm, value, pitch F1 and placement are four answers to four
questions, each with its coverage caveat; none of them is the one a user asks
first. `benchmark.edit_cost` counts it from the SAME time-free alignment
`score_notation` reads (no second aligner), per 100 of the reference's notes:

| component | one edit is | test |
|---|---|---|
| insertions | a note of ours the page does not have: delete it | alignment gap |
| deletions | a page note we do not have: write it in | alignment gap |
| pitch | an aligned pair at the wrong pitch: change it | alignment substitution |
| position | a matched note off the page's rhythm: move it, or shift everything after | rhythm's gap test, `NOTATION_TOLERANCE`, between consecutive KEPT notes -- across a hearing edit too, which rhythm skips, so a page of rhythm 1.0 can still carry position edits, every one of them beside a hearing edit |
| value | a matched note of the wrong length: change it | value's test, `NOTATION_TOLERANCE` |
| bar | the page starts on the wrong beat: move bar 1 | `score_bars` placement says off (`beat_offset != 0`) and the cheapest edit set opens off the bar |

Insertions, deletions and pitch are HEARING edits; position and value are
written, but not all of them are notation's (below).

**Why position is not "the gaps rhythm failed".** Rhythm's gap test fails
both the gap into a misplaced note and the gap out of it, where a reader moves
the note once; and a beat the grid dropped fails one gap and would, counted
per note, charge every note after it. So `frame_edits` minimises:
each matched note is kept or moved (one edit), and between two CONSECUTIVE
kept notes whose gap fails rhythm's test everything after is shifted (one
edit). The first kept note sets the frame -- a page a beat off throughout is
the `bar` edit, which rhythm cannot see. The test is between
consecutive kept notes, so a frame drifting under the tolerance at every
step (0.1 of a beat a note over twenty notes, two beats in all) costs
nothing, as it costs rhythm nothing; a test holds that on the record. It is
NOT rhythm's set of gaps: rhythm tests only consecutive matches with no note
between on either side, and this tests the gap across an insertion, a
deletion or a pitch substitution too. So a page that scores rhythm 1.0 can
still cost position edits, and every one of them falls in the part beside a
hearing edit (below): the gap it fails holds a hearing edit and has one
beside each end, and the split takes the fewest clean edits. Value tests
every matched note, as value does, so value 1.0 does cost nothing. Exact dynamic programme, checked against brute force over every kept
subset on 2,000 random cases (and 300 more in CI); 0.16 s on a 1,500-note
page. A pitch substitution is charged its pitch and nothing more: its timing
is not checked, as rhythm does not check it.

**The bar edit is minimised with the positions** (`benchmark.frame_edits`,
after the second review). The placement verdict is a MODE over the page, so
a page on its bar lines until a slipped beat and off them after it, with
more notes after, reads off the bar -- and the first version charged it a
shift for the slip AND a moved bar 1, two edits for the reader's one. Now a
frame opened at a note off the reference's bar lines (the difference modulo
the bar, to the nearest half beat: `beat_agreement`'s own test, one note at
a time, `frame_off_the_bar`) costs the bar edit inside the same dynamic
programme, and only on a page the verdict calls off: a page off from its
first note pays it, one that slipped off pays the shift alone, and one off
from the start that slips again pays both. Checked against brute force over
every kept subset on 300 more random cases. No number moved: the verdict is
"on the bar" on all 44 notation rows, so the bar edit is never offered.

**Not all of position and value is notation's.** A matched note's written
value is inherited from the gap to the next onset (`without_overlap`
truncates there), so an extra note of ours or a missed note of theirs right
after a match turns into a value edit on the match; and an extra onset in a
beat changes the grid the quantizer picks for it, which moves its
neighbours. The first reading of this document filed all of position and
value under notation and concluded that the reader's effort was "mostly
notation, not hearing"; the review measured that 466 of the 846 value edits
on the twelve hand scores touch a hearing edit, and the conclusion does not
survive it. So each position and value edit is now also counted BESIDE a
hearing edit when one touches it -- the alignment pair right before or after
the note, or for a shift anywhere inside the gap it crosses
(`edit_position_beside`, `edit_value_beside`, parts of the components, not
additions to the cost) -- and `edit_beside_share` is the share of matched
notes a hearing edit touches. Where several minimal edit sets exist the
split takes the one with the most edits beside a hearing edit, so "notation
alone" is a floor, never a tie broken in its favour.

**Readings** (default take, trusted pairings; per 100 reference notes):

| set | n | edit cost | insert | delete | pitch | position (beside) | value (beside) | bar | range |
|---|---|---|---|---|---|---|---|---|---|
| hand scores | 12 | **55.3** | 11.4 | 5.7 | 5.6 | 12.9 (8.3) | 19.6 (10.8) | 0.0 | 33.4-71.7 |
| Omnibook | 22 | **68.1** | 7.0 | 11.2 | 11.5 | 16.3 (11.7) | 22.2 (14.2) | 0.0 | 45.8-93.6 |
| PDF pages, silver | 3 | **56.3** | 7.2 | 10.6 | 4.5 | 13.9 (9.0) | 20.0 (11.5) | 0.0 | 52.5-63.3 |

The same means in three blocks:

| set | n | hearing | notation beside a hearing edit | notation alone | matched notes a hearing edit touches |
|---|---|---|---|---|---|
| hand scores | 12 | 22.8 (41%) | 19.1 (35%) | 13.4 (24%) | 31% |
| Omnibook | 22 | 29.7 (44%) | 25.8 (38%) | 12.6 (19%) | 42% |
| PDF pages, silver | 3 | 22.3 (40%) | 20.5 (36%) | 13.4 (24%) | 36% |

What they say:

- **Hearing is the largest of the three blocks on every set; notation
  alone is at least 19-24%; the 35-38% between them is not assigned to
  either.** Position and value are 59% of the edits on the hand scores, 56%
  on the Omnibook and 60% on the pages -- but 59-67% of them touch a hearing
  edit. What only quantize and notate can fix is at least 12.6-13.4 edits
  per 100 notes. "At least" because where several minimal edit sets exist
  the split takes the most beside a hearing edit; breaking those ties the
  other way (the second review's re-run, reproduced) moves 354 -> 340 of the
  551 position edits beside a hearing edit on the hand scores and 1,071 ->
  1,010 of 1,507 on the Omnibook. Value edits have no tie to break.
- **The notes beside a hearing edit go wrong far more often than the rest**,
  pooled over each set's notes: on the hand scores a matched note a hearing
  edit touches carries a value edit 41% of the time against 14% for one
  nothing touches (1,135 and 2,671 notes), and a position edit 31% against
  7%; on the Omnibook 44% against 17% and 36% against 10% (2,996 and 4,413);
  on the pages 40% against 15% and 31% against 9% (507 and 919). That is an
  association, not yet a cause: the passages where we mishear may also be
  the hard ones to notate. It is not the tie-break's doing: broken the other
  way, the position rates read 30.0% against 7.9% on the hand scores and
  33.7% against 11.3% on the Omnibook. If the whole excess were the hearing
  edit's, a perfect ear would take 13.4 more edits per 100 with it on the hand scores
  (16.7 on the Omnibook, 14.0 on the pages) beyond the hearing edits
  themselves. The mechanical case alone -- an insertion or a deletion as the
  very next pair of a wrongly-valued note, whose written value is the gap to
  an onset only one side has -- is 238 of the 846 value edits on the hand
  scores (169 before one of our extra notes, 69 before one of theirs we
  missed). CLAUDE.md's value confusion of 2026-09-21 (61% of wrong lengths
  have an extra or missing note beside the match) was the same finding from
  the other side.
- **The two references disagree about what we hear.** On the listener's
  pages we write more than they do (insertions 11.4 against deletions 5.7);
  on the Omnibook it reverses (7.0 against 11.2) and pitch edits double (11.5
  against 5.6). The book's worst pages are the unison-head sides (D30: Card
  Board 83.2, Moose The Mooche 82.7, Shawnuff 72.4, with hearing 43-55 per
  100) and KC Blues (93.6, the most notation-alone edits of any page, 20.8).
- **The bar component is zero everywhere**: all 37 pages sit on their
  reference's bar lines (12 of 12, 22 of 22, 3 of 3). It exists for the page
  that does not, where it is the cheapest edit on the page; no real page has
  exercised it, only the unit tests.
- **It is not rhythm or value renamed.** Across pages it correlates with
  rhythm at -0.75 (hand scores) and -0.78 (Omnibook), with value at -0.73 and
  -0.84: related, and far from redundant.
- **The pianists' default line is cheaper to fix**: 52.0 edits per 100 on
  the oracle line against 60.1 on the CREPE line, over the same 7 pages;
  paired change -8.1, 95% interval [-12.4, -3.4] resampled by recording,
  6 of 7 down, sign test p = 0.125 (seven pages cannot reach 0.05 with one
  dissent). The oracle line inserts more (+3.6) and deletes (-4.4) and
  mis-pitches (-3.9) less. Its value edits fall 2.5, all of it beside a
  hearing edit (-2.7 there, +0.2 clean), and its position edits 0.9 (-1.4
  beside, +0.5 clean). The line's gain is a hearing gain, carried into the
  notation around it. The one number that folds all of this agrees
  with the 2026-09-18 decision to make it the default.
- **It is hard, not impossible, to win by dropping notes.** Dropping a note
  the page also has costs a deletion, so it pays only where that note
  carried two edits of its own (a move and a value); dropping one the page
  lacks saves an insertion, which is what dropping it is for.
- **A page-made step is still charged to us.** Gingerbread Boy's two-beat
  step at bar 102 is the page's (below), and the edit cost counts it as one
  of our position shifts: 0.15 per 100 of its 670 notes, left in.

Not done: the roadmap names MV2H (McLeod and Steedman, 2018) as the outside
cross-check. It is a Java tool and was not run; adding it is a dependency
decision for the listener.

## OMR step check

A bar-line step on a PDF page can be the page's: an OMR engine that read six
beats into a bar of 4/4 puts every later note two beats later on the page,
and the trace reads a step no grid caused. `evaluation.page_steps` places the
page's measures where the score reader places them (`evaluation.reader_bars`:
the reader advances through a bar to where its LAST voice ends, padded to the
signature -- so a bar whose first voice overruns and whose last fits moves
nothing, and a test holds the walker to `mscz.parse_musicxml` on a page of
two voices).

Three things move our position minus the page's. A beat GRID adds or drops
whole beats. The page's READER moves every note after an overfull bar later
by that bar's overrun, any fraction. And OUR LINE sits a fraction of a beat
off the page wherever it was written differently -- a phrase a sixteenth
later -- which moves from passage to passage and is neither. The trace's
labels cannot tell them apart: each run is labelled with its offset rounded
to the half beat, so an offset near a quarter flips between two labels, and a
grid's whole beat under a fractional offset can read as a label change of
half a beat.

So each step is judged on UNROUNDED offsets. The check reads every matched
note's ours-minus-page difference, the numbers the trace's labels were
rounded from (`run_eval.page_differences`: the trace's own
`score_bars._matched_differences` on the same notes, asked for again). A
run's offset is the median of its notes'; a step's change is the after run's
median less the before run's; the page's overrun across the step is summed
over the overfull bars the reader leaves between the BULK of the run before
and the bulk of the run after (the middle of each run's page positions: the
median, like the label, follows the majority of a run's notes, and an
overfull bar inside a run moves only the notes after it); and the residual is
the change with that overrun taken out. Then:

- a residual within a quarter beat of a whole number other than zero is the
  **grid's** -- it added or dropped that many beats, whatever the page did
  beside it;
- a residual within a quarter beat of zero is the **page's** only if the page
  MADE the step, which is a counterfactual: add back to each run's median the
  page's overrun standing at that run's bulk, label both the way the trace
  does, and the step is the page's when the labels then agree -- without the
  page's overruns the trace would not have stepped there;
- anything else is **undecided**: a residual the trace would label a half
  beat, or a step that stands without the page (the trace rounding an offset
  that is our line's). The trace line names every undecided step after the
  decided ones, with its residual, and `page_steps` never counts one.

The counterfactual replaced a rule about the overrun's size (the page's when
an overfull bar sat between the runs or the page ran "a fraction of a half
beat late"), which a third review broke through the real trace (2026-09-30):
a page running an eighth late while our line moved a sixteenth was called the
page's though the trace steps there without it, and a page running a half
beat late -- which the old rule ignored as unable to cross a label's edge --
does push an exact-quarter tie across one, because Python rounds a tie to the
even count of half beats. The counterfactual gets both right and leaves every
real reading as it was: 3 / 1 / 0 on the three pages.

The quarter is the trace's own label arithmetic, not a number fitted to a
page. The trace labels an offset `round(2 * offset) / 2`, so it cannot tell
apart two offsets within a quarter beat of one half-beat value: a quarter is
half its resolution. Python rounds a tie to the even count of half beats,
which is always a whole beat, so the trace labels an offset exactly a quarter
from a whole number with that whole number; the check reads a residual the
same way, so the bound is inclusive. A short bar is padded by the reader,
cannot move a note after it, and is named when it sits within a bar of a
step, never counted.

**The first version got Embraceable You wrong.** It looked one bar either
side of a step and never summed: it named page bar 28 (4.125 of 4) at the
-0.5 step at bar 30 and called it "not this step", and it never saw page bar
26 (4.25 of 4) two bars further back. Between them the reader places every
note after bar 28 0.375 of a beat late, and the unrounded offset per matched
note says so: median +0.12 over bars 18-25 and -0.33 over bars 28-34 (means
+0.10 and -0.27), a fall of 0.37-0.45 of a beat. That lands the offset near
-0.25, the very point where rounding to the half beat changes its mind, and
our line wobbles a sixteenth either side of it: the four runs' medians are
0.000, -0.375, -0.125 and -0.375, which the trace labels 0, -0.5, 0, -0.5 --
the three steps of -0.5, +0.5 and -0.5 at bars 30, 31 and 32. None of them is
a grid's, and the first version counted none of them as the page's.

**The second version gave the page steps that were not its own.** It summed
the overrun between the runs' bulks, as the check still does, but judged the
half-beat LABELS: a step was the page's if its label change plus the overrun
was within half a beat of zero, and a tie went to the page, because "no grid
makes half a beat". A review refuted both halves of that. On a page that
already runs a fractional offset, a grid's dropped beat can read as a label
change of half a beat. A synthetic copy of Embraceable You's page run
through the real trace (`test_a_grid_beat_under_a_fractional_page_offset_is_the_grids`),
with a beat dropped at bar 36 where our line sits a 32nd later, reads -0.5 ->
-1.0, and the tie gave it to the page; unrounded, those runs moved -0.875
with nothing on the page between them: the grid's. And half-beat steps are
not the page's by construction: WJazzD's annotation, which no OMR reader
touched, traces them too. Hancock's Gingerbread Boy reads "+0.5 at bar 6" against it, runs at
-12.5 and -12.0 unrounded, a residual of +0.50 with no page at all:
undecided. Over every WJazzD trace on the card (the default takes: 62 steps
on 16 solos, read with a scratch script over the cached notes -- the harness
runs no OMR check on a WJazzD row, which has no page), 39 steps are label
changes of exactly half a beat, and the second version's arithmetic would
have called all 39 the page's. This one calls none of the 62 the page's, as
no page overruns there. Of the 42 label changes that end in a half (those
39 and three of a beat and a half), it reads 4 as the grid's -- a residual
within a quarter of a whole beat: Joe Henderson's In 'n Out, solo 199, "-0.5
at bar 64" is -0.75 unrounded -- and leaves 38 undecided, 6 of them with
nothing the trace resolves moved across them (our own line on a label's
edge). Of the 20 whole-beat label changes, 19 leave a whole beat and 1 is
undecided (In 'n Out, solo 198, "+2.0 at bar 187" is +1.50).

On the three pages: **4 of 5 steps are the page's, as before, now on
unrounded offsets; none is undecided.** Gingerbread Boy's -2.0 at bar 102:
runs at 0.000 and -2.000, page bar 102 holding 6 of 4 beats between them,
residual 0.00 ("-2.0 at bar 102: page bar 102 holds 6 of 4 beats -- the
page's step (residual +0.00)"). Embraceable You's three: the first is where
the page's 0.375 crosses between the runs, change -0.375, residual 0.00
("-0.5 at bar 30: page bar 26 holds 4.25 of 4 beats, page bar 28 holds 4.125
of 4 beats -- the page's step (residual +0.00)"); the other two are our line's
sixteenth either side of the label's edge on a page that runs 0.375 late,
residuals +0.25 and -0.25 ("+0.5 at bar 31: nothing the trace resolves moved
across it (residual +0.25); the page runs 0.375 of a beat late since page
bars 26, 28, which the trace rounds to half beats -- the page's step").
Cheese Cake's +1.0 at our bar 83 -- the trace's number: our page opens with a
pickup bar 0, and the page built on WJazzD's annotation of the same solo,
which numbers that opening bar 1, calls the same bar 84 and steps there too
-- has runs whose medians are a whole beat apart (+4.000 and +5.000; a
whole bar of offset is still on the bar) and no overfull page bar behind
it: residual +1.00, a whole beat, ours. The trace line carries each verdict
and the row pins `page_steps`.

Where it is thin. Embraceable You's two flicker steps sit exactly on the
tolerance: residuals of a quarter, read as zero by the same tie rule the
trace labels with. A strict quarter would leave them undecided and that
page's `page_steps` at 1, not 3. The medians are coarse because the offsets
are: our page and theirs are both written on a grid, so a run's median sits
on an eighth or a twelfth of a beat and moves in those steps. And the count
is still a description, not a validation: the rule has now been rewritten
twice on the three pages it reports on, and the next page with a step is its
first test. A whole-bar step with no overfull bar behind it (a bar the engine
dropped or added) reads as the grid's, unchecked.

## E5. Does confidence point at the errors

**WJazzD, against mir_eval's false positives.** Every note of ours in a
scored solo is a hit or a false positive under exactly the match
`score_wjazz.score` scores (`evaluation.note_hits` asks mir_eval's
`match_notes` for the pairs; the harness stops if the flags do not reproduce
the note precision beside them, and a test now holds it to stopping).
Ranked by confidence, over 73 solos, two ways -- and the first reading
quoted the first as if it were the second:

- **per solo, each solo counted once** (`wjazz_conf_auc`, `wjazz_fp_low10`,
  `wjazz_fp_low20`): AUC 0.646 (median 0.641, range 0.448-0.878; above 0.5
  on 67 of 73) -- the chance a false positive is less confident than a
  hit -- and the least-confident 10% / 20% of a solo's notes hold 27% / 41%
  of its false positives (chance 10% / 20%);
- **pooled, each false positive counted once** (`wjazz_pooled_*`, weighted
  by each solo's `fp_n`): **AUC 0.637; of all 4,320 false positives, 25%
  sit among their own solo's least-confident 10% of notes and 39% among
  its least-confident 20%**. That is the sentence to quote about "the
  false positives"; the per-solo figure answers how well a typical solo
  ranks. A solo with few false positives ranks them a little better, which
  is all the gap is.

Per-solo means by line: the pianists' oracle line 0.669 (n = 4; its confidence is the piano
model's, about fifty distinct values, and ties across the cut are counted in
proportion), CREPE on everyone else 0.644 (n = 69). By tempo class: UP 0.693
(31), MEDIUM UP 0.613 (22), MEDIUM 0.606 (17), SLOW 0.618 (3). It correlates
with note precision at only +0.25.

So confidence points at the errors, weakly: a review that starts from the
bottom fifth of the confidence order finds 39% of the false positives.
That is the curve a better confidence has to beat -- the roadmap's point that
review gets cheaper even when F1 does not move.

**The listener's erasures.** 376 erasures on 10 sidecars fall inside their
spans (all on the melody line; none made on the All-notes view). Matched onto
the notes this run transcribed by content (`erasures.resolve`: exact pitch,
30 ms), **133 match a note of the default take, 120 of them on Billy Boy**.
Every record names the separation and line it was made on, and that, not
the transcriber, decides whether it still matches:

| made on | erasures | match the default take |
|---|---|---|
| today's stems (BS-Roformer-SW; `piano` for a pianist, `other` for a horn) | 141 on 5 tracks | **132** |
| Demucs stems (`htdemucs`, `htdemucs_6s`, `htdemucs_ft`) | 235 on 9 tracks | **1** |

The 141 are Billy Boy's 124 (made on the oracle line, 120 match), four on
All The Things You Are, seven on Giant Steps (the three made on the oracle
line match; the four made on the CREPE line match only the CREPE take),
three each on Confirmation and Soul Station. The 235 are the horns' 123
(Confirmation's 85 and Someday's 37 on htdemucs_6s, one on All The Things
You Are) and the pianists' 112: 107 made on Demucs's `other` stem, from when
pianists were read from it, and Sonny Clark's five on htdemucs_6s `piano`.
So the first reading's explanations were wrong in two places. The pianists'
labels were not "mostly made on the CREPE line, and do not match the oracle
line": Billy Boy's, half of them, were made on the oracle line and match it.
And Confirmation's were not shown to have vanished because the line floors
(D22) removed that bleed: 85 of its 88 were made on htdemucs_6s, only 4 sit
an octave or more under today's line (the register floor's reach), and the
loudness floor cannot be checked from the records, which carry no loudness.
The new separation and the floors both arrived after the labels, and this
does not separate them. What it does show is that where a label was made
predicts whether it matches, on every track; the card now shows it (`stems`
column: made on this run's separation, and matched).

Weighted so every matched erasure counts once (a track holds 1 to 120 of
them): **AUC 0.746, the least-confident 10% hold 15% of the erasures, 20%
hold 36%**, over 133 erasures on 6 tracks -- in effect Billy Boy's reading
(0.781, 15%, 37%) on the oracle line. The weighting hides the three horns,
and their 7 matched erasures are too few to read either way: Confirmation
0.188 (2 matched) and All The Things You Are 0.213 (4) have the erased notes
MORE confident than the kept ones, and Hank Mobley's Someday My Prince Will
Come 0.989 (1) has its one erased note among the least confident. Seven
notes cannot say whether confidence misleads on a horn's bleed; they say not
to read 0.746 as more than one pianist. CLAUDE.md's AUC 0.830 against 302
labels was the labels' own snapshot confidence when they were made -- a
different population from today's 133 -- and is neither confirmed nor
refuted here.

What was NOT tried: matching the Demucs-era labels against the piano
model's full output (the review's `candidates` pool) rather than against the
line, which is what line selection (issue #8) would train on. The records
carry onset, pitch, duration and their snapshot confidence, so they may yet
be usable as their own population; "the training data is one track" is true
only of matching against the line this run emits.

The erasure rows are printed and in `--json`, never pinned: their inputs
are the listener's live labels, not code, and the first note erased in a GUI
session would otherwise fail the next run with no code change.

## E6. Stratified means

Printed and in `--json` (`card["strata"]`), never pinned: they are the pinned
numbers cut another way, and a stratum of two would pin noise. WJazzD by
`solo_info`; every notation set by the tempo of the repaired grid its page is
built on, in WJazzD's own tempo classes (`evaluation.tempo_class`: SLOW under
80 bpm, MEDIUM SLOW 80-112, MEDIUM 112-140, MEDIUM UP 140-180, UP from 180).

**WJazzD, note F1 / beat F1 (n):**

| tempo class | note F1 | beat F1 | n |
|---|---|---|---|
| SLOW | 0.906 | 0.858 | 3 |
| MEDIUM SLOW | - | - | 0 |
| MEDIUM | 0.842 | 0.948 | 17 |
| MEDIUM UP | 0.848 | 0.927 | 22 |
| UP | 0.869 | 0.958 | 31 |

| style | note F1 | beat F1 | n |
|---|---|---|---|
| BEBOP | 0.870 | 0.967 | 12 |
| COOL | 0.886 | 0.960 | 9 |
| HARDBOP | 0.853 | 0.957 | 20 |
| POSTBOP | 0.853 | 0.932 | 29 |
| FUSION | 0.784 | 0.702 | 2 |
| TRADITIONAL | 0.863 | 0.973 | 1 |

| instrument | note F1 | beat F1 | n |
|---|---|---|---|
| tp | 0.867 | 0.949 | 26 |
| ts | 0.865 | 0.947 | 21 |
| as | 0.840 | 0.924 | 13 |
| tb | 0.826 | 0.953 | 5 |
| p | 0.898 | 0.951 | 4 |
| ss | 0.801 | 0.940 | 3 |
| g | 0.887 | 0.832 | 1 |

**Notation, rhythm / value / edits per 100 (n), default takes, trusted:**

| set | tempo class | rhythm | value | edits | n |
|---|---|---|---|---|---|
| hand scores | MEDIUM SLOW | 0.838 | 0.745 | 71.7 | 1 |
| | MEDIUM | 0.856 | 0.746 | 55.6 | 1 |
| | MEDIUM UP | 0.844 | 0.792 | 49.9 | 3 |
| | UP | 0.846 | 0.783 | 55.2 | 7 |
| Omnibook | MEDIUM | 0.707 | 0.668 | 78.6 | 2 |
| | MEDIUM UP | 0.749 | 0.716 | 69.4 | 4 |
| | UP | 0.796 | 0.716 | 66.5 | 16 |
| PDF pages, silver | SLOW | 0.837 | 0.812 | 53.1 | 1 |
| | UP | 0.813 | 0.737 | 57.9 | 2 |

The PDF pages are stratified per tier, as every other PDF number is (E3):
a bronze page is a different kind of reference, and one "PDF pages" row
would have mixed them the day the first bronze page was scored. Today all
three are silver.

What they say:

- **The ballad gap is one line now.** 3 of the benchmark's 73 scored WJazzD
  solos are SLOW and none MEDIUM SLOW (Parker's Don't Blame Me and
  Embraceable You, Chet Baker's I Fall In Love Too Easily), and their beat
  F1 is 0.858 against 0.927-0.958 everywhere else. The database itself holds
  39 SLOW and 31 MEDIUM SLOW of its 456 solos: the gap is in what we have
  audio for, not in what exists. Across all 37 notation pages the only SLOW
  page is Embraceable You's PDF, and the only MEDIUM SLOW one is Soul
  Station. D16 stayed invisible inside a mean; this table cannot hide it.
- **The Omnibook's rhythm rises with tempo**: 0.707 (MEDIUM, 2 sides) to
  0.749 (MEDIUM UP, 4) to 0.796 (UP, 16), edit cost 78.6 to 66.5. The hand
  scores are flat (0.838-0.856), with 7 of 12 pages UP.
- **The two FUSION solos are both Kenny Garrett's Brother Hubbard** (beat F1
  0.733 and 0.672), one recording and one of the four half-rate grids R32
  read on the right octave. Read the row as that recording, not as the style.
- **Soprano (0.801, n = 3: two My Favorite Things, one Limehouse Blues),
  trombone (0.826, 5) and alto (0.840, 13)** read under trumpet and tenor
  (0.867, 0.865). Every stratum under five is a pointer, not a finding.
- Flex-Q's rhythm (collateral, D36) is printed by tempo class too: SLOW 0.848
  (3) against 0.650-0.664 -- dropped and merged notes, not page quality.

## What the first readings say about the product

1. **Neither lever is shown to be the larger yet, and the edit cost is how
   to find out.** Hearing edits are 40-44% of a reader's effort on every
   set, notation alone at least 19-24%, and the 35-38% between them --
   position and value edits a hearing edit touches -- is an association,
   not a cause. Only part of it is the hearing's by construction: 238 of the
   846 value edits on the hand scores sit right before an insertion or a
   deletion, whose written value is the gap to an onset only one side has.
   Credit the hearing with the whole block and it is the larger lever (41.9
   against 13.4 per 100 on the hand scores); credit it with the mechanical
   part alone and the two are about even (about 28 against 27 -- the pooled
   238 of 846 applied to the mean value edits, an estimate). What decides it
   is an ORACLE ABLATION, cheap because every note and grid is cached: take
   our aligned insertions out of the cached notes, re-notate, re-score, and
   count the notation edits that leave with them. It is the next
   measurement, not done here. Until then judge either kind of change by
   the edit cost, which charges a hearing change for the notation damage
   around it and a notation change for any note it loses. On the listener's
   pages the largest hearing component is our extra notes (11.4 per 100); on
   the Omnibook the missed notes and wrong pitches (11.2 and 11.5, led by
   the unison heads); the largest notation-alone component is value
   everywhere.
2. **An erase in the GUI can fix more than one edit.** Export and Score
   rebuild the page from the notes the listener keeps, so erasing one of our
   extra notes re-notates the note before it too -- and 169 of the 846 value
   edits on the hand scores sit right before one of our extra notes. (Whether
   the re-notated value is then the human's depends on the note's own length
   and the gap rules; that is not measured here.) That makes finding the
   extra notes the cheapest review there is,
   and confidence is how the review finds them -- at a pooled AUC of 0.64 it
   finds 39% of WJazzD's 4,320 false positives in the bottom fifth of each
   solo's notes. A better
   per-note confidence (the piano model's corroboration, the neighbour
   salience cue in the error taxonomy, the pitch trace's stability) makes the
   review cheaper with no transcription change; the E5 curve is its
   acceptance test.
3. **Labels are tied to the stems they were made on.** 132 of the 141
   erasures made on today's separation still match; 1 of 235 made on
   Demucs's does. Before a separation change ships, the labels made on the
   old one need re-matching or re-review, or the training data for line
   selection quietly shrinks; the card's `stems` column now shows it.
4. **Ballads remain the blind spot.** 3 SLOW and 0 MEDIUM SLOW of the 73
   scored WJazzD solos (the database has 70 such solos), 1 SLOW notation page
   in 37. Pairing slow audio with the ballad PDFs is what lets A3 and R31 be
   judged at all.

## Where it lives

- `src/swingscribe/benchmark.py`: `edit_cost`, `frame_edits` (the dynamic
  programme: position, beside, bar), `frame_off_the_bar`,
  `position_edit_split`, `position_edits`, `EDIT_FIELDS`, `EDIT_SPLIT`;
  `score_against_notation(..., off_the_bar=)` returns the `edit_*` fields
  off its own alignment, testing the frame against the score's own bar
  length.
- `src/swingscribe/evaluation.py`: `confidence_ranking`, `share_in_lowest`,
  `note_hits` (mir_eval, lazy); `tempo_class`, `strata`; `PageBar`,
  `page_bars`, `reader_bars`, `PageBar.overrun`, `page_overrun`,
  `STEP_MATCH` (a quarter beat), `page_steps` (each step's unrounded
  residual and its verdict: page, grid or undecided), `describe_page_steps`.
- `scripts/run_eval.py`: `score_notation_page` (the placement verdict read
  first and handed to the edit cost), the `edit_*` columns and means
  (`edit_blocks` prints the three blocks), `conf_auc` / `fp_low10` /
  `fp_low20` / `fp_n` on WJazzD rows and `wjazz_confidence_summary` (per
  solo and pooled, each line saying which), the `erasures` section and
  `erasure_means` (unpinned), `page_steps` on PDF rows (the page's steps
  only: an undecided one is named in the trace line and never counted) off
  `page_differences` (the trace's matched notes, unrounded), `card["strata"]`
  (PDF pages per tier); `edit_cost` is a trusted headline field of the
  paired table (E1), marked "(v)" there because lower is better. Every new
  renderer runs in CI on a small card (`test_the_scorecard_renders_every_new_section`).

New pins (additions only, 796 over the committed 2,832; the diff is 796
insertions and no deletion): `edit_*`, `edit_position_beside`,
`edit_value_beside`, `edit_beside_share` on every notation, Omnibook and
page row; `page_steps` on page rows; `conf_auc`, `fp_low10`, `fp_low20`,
`fp_n` on WJazzD rows; the summary means
`{mscz,omnibook,pages_silver}_edit_*` (the split included),
`pianist_edit_cost*`, `wjazz_conf_auc`, `wjazz_fp_low10/20`, `wjazz_conf_n`
(per solo) and `wjazz_pooled_conf_auc`, `wjazz_pooled_fp_low10/20`,
`wjazz_pooled_conf_n`, `wjazz_pooled_fp_n` (pooled). No `erasures/`,
`summary/erasure_*` or strata key is pinned. `tests/regression/test-baselines.json`
(the release `--test` pins) is untouched and lacks the new keys, so the
next `--test` run reports them as new.
