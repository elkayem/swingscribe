# How SwingScribe writes a solo, beside how the humans write one

2026-09-20. `scripts/notation_survey.py --db wjazz/wjazzd.db`, over every
page the harness can build under the current quantizer (R28), and the same
tallies of the references over the same tracks. No audio; the note cache
and the grid cache, eleven minutes (the WJazzD alignment is the wait).

The question the listener asked: the pages still do not look like a page a
human would write, even where the notes are right. The rhythm and value
scores say how often we agree with a human about a position or a length;
they do not say what we write INSTEAD. This survey does. It is a
vocabulary count, not a score: what symbols each corpus uses and where in
the beat its onsets sit.

Four corpora, three kinds of reference:

- **The listener's twelve hand scores** (`benchmark/*.mscz`): read from
  the MuseScore XML itself (`durationType`, dots, `Tuplet`, `Tie`), grace
  notes skipped because they take no time.
- **The Omnibook, 22 sides** (LORIA's MusicXML): `type`, dots,
  `time-modification`, `tie`. A different transcriber and a different
  house style, which is why it is worth having.
- **WJazzD, the 77 located solos** and separately all 448: bar, beat,
  tatum and division. Positions only. WJazzD has no page, and a score
  built from it (`wjazz.annotation_notation`) carries OUR values on the
  annotator's positions, so its value columns would measure nothing.
- **Ours**, notated from the cached notes exactly as `run_eval` builds the
  page it scores: the repaired grid, the sidecar's downbeat, the default
  take.

Ties are merged before positions are counted, so a note is one onset in
every corpus. Both halves of a tied note are counted as written symbols.

## The tables

Shares of notes (or rests, or onsets) in percent. Cells under 0.05% are
left blank; "-" means the corpus cannot show it.

### Note values

| written value | ours (hand-score set) | hand scores | ours (Omnibook set) | Omnibook |
|---|---|---|---|---|
| eighth | 69.2 | 67.7 | 63.6 | 65.3 |
| sixteenth | 12.2 | 8.6 | 14.6 | 11.8 |
| quarter | 5.6 | 9.4 | 7.3 | 6.4 |
| triplet eighth | 5.7 | 9.0 | 5.3 | 8.7 |
| sixteenth triplet (16th[3:2]) | 0 | 1.0 | 0 | 4.9 |
| quarter-note triplet | 0 | 1.2 | 0 | 0.2 |
| quintuplet / sextuplet 16ths | 0 | 0 | 0 | 0.5 |
| **dotted eighth** | **2.6** | 0.1 | **3.0** | 0.1 |
| **32nd** | **2.1** | 0.2 | **2.0** | 0.3 |
| **dotted sixteenth** | **0.8** | 0 | **0.9** | 0 |
| dotted quarter | 1.4 | 1.5 | 2.5 | 0.8 |
| half | 0.4 | 1.1 | 0.7 | 0.8 |
| notes | 4747 | 4332 | 9469 | 9974 |
| tuplet share | 5.7 | 11.2 | 5.3 | 14.4 |
| tie rate | 0.049 | 0.023 | 0.053 | 0.045 |

### Rests

| written rest | ours (hand-score set) | hand scores | ours (Omnibook set) | Omnibook |
|---|---|---|---|---|
| eighth | 58.1 | 42.3 | 55.9 | 43.8 |
| quarter | 18.9 | 30.1 | 14.5 | 34.5 |
| half | 7.1 | 17.5 | 10.2 | 17.5 |
| whole bar | 0.6 | 4.0 | 2.5 | 2.9 |
| **dotted quarter** | **9.9** | 1.8 | **11.1** | 0 |
| dotted half | 1.8 | 2.2 | 1.7 | 0 |
| dotted eighth | 1.8 | 0 | 1.8 | 0.2 |
| sixteenth | 1.4 | 0.1 | 1.4 | 1.1 |
| rests | 856 | 674 | 1266 | 1278 |
| rests per note | 0.18 | 0.16 | 0.13 | 0.13 |

### Where in the beat the onsets sit

| position | ours (hand set) | hand scores | ours (Omnibook set) | Omnibook | ours (WJazzD set) | WJazzD located | WJazzD all 448 |
|---|---|---|---|---|---|---|---|
| on the beat | 43.1 | 47.4 | 42.4 | 40.8 | 41.8 | 34.6 | 32.0 |
| the "and" | 40.6 | 39.8 | 39.5 | 41.9 | 36.0 | 27.3 | 25.2 |
| **the "e"** | **6.2** | 1.8 | **6.6** | 2.5 | 8.2 | 7.2 | 7.7 |
| the "a" | 3.7 | 2.8 | 5.0 | 3.9 | 6.2 | 10.4 | 11.2 |
| thirds (1/3, 2/3) | 4.0 | 7.1 | 3.8 | 8.0 | 2.6 | 13.1 | 13.1 |
| sixths (1/6, 5/6) | 0 | 0.4 | 0 | 1.8 | 0 | 3.1 | 4.0 |
| **odd 32nds** (1/8, 3/8...) | **2.5** | 0.1 | **2.8** | 0.2 | **5.1** | 1.5 | 2.4 |
| other (fifths, sevenths...) | 0 | 0.6 | 0 | 1.0 | 0 | 2.7 | 4.6 |
| onsets | 4747 | 4291 | 9469 | 21593 | 36718 | 35997 | 197017 |

WJazzD's thirds are not all triplets: its tatum is literal, and it files a
swung pair at 2/3 or 3/4 as often as at 1/2 (docs/wjazz-quantize.md). Read
that column as "where the annotator heard it", not "what a page writes".

### Gap to the next onset

The written length of a note in a single line, whatever symbol carries
it. Available in every corpus, WJazzD included.

| next onset after | ours (hand set) | hand scores | ours (Omnibook set) | Omnibook | ours (WJazzD set) | WJazzD located |
|---|---|---|---|---|---|---|
| an eighth | 56.7 | 60.1 | 57.1 | 59.5 | 47.4 | 35.0 |
| a sixteenth | 10.1 | 8.5 | 13.5 | 12.2 | 17.8 | 15.0 |
| a triplet eighth | 5.5 | 8.9 | 5.1 | 9.1 | 3.5 | 11.2 |
| two triplet eighths | 0 | 1.1 | 0 | 0.3 | 0 | 4.0 |
| a sixteenth triplet | 0 | 1.0 | 0 | 5.3 | 0 | 4.9 |
| a quarter | 12.2 | 9.0 | 9.7 | 4.8 | 11.7 | 7.1 |
| a dotted eighth | 3.3 | 0.2 | 3.2 | 0.2 | 2.8 | 4.0 |
| a 32nd | 1.5 | 0.2 | 1.4 | 0.3 | 4.2 | 2.3 |
| a dotted sixteenth | 0.8 | 0 | 0.8 | 0 | 1.4 | 0.2 |
| other | 1.8 | 1.7 | 1.8 | 0.5 | 2.0 | 8.4 |

## What the tables say

Five differences, in the order they cost the page. Each is a thing we
write that no human corpus writes at a tenth of the rate, or a thing every
human corpus writes that we cannot.

### 1. The laid-back downbeat is written on the "e", and the note before it becomes a dotted eighth

We put 6.2% of onsets on the "e" against the listener's 1.8% and the
Omnibook's 2.5%; 2.5-2.8% on odd 32nd positions against 0.1-0.2%; 2.6-3.0%
of notes are dotted eighths against 0.1%. These are one phenomenon. Of our
394 dotted eighths on the hand-score set, 169 start on the "and" and 120 on
the "e": the note on the "and" runs to the next beat's "e" because the
next note was played late, and the note on the "e" IS that late note.

The line sits behind the tracked beat. Over 108 tracks (the twelve, the
Omnibook, the located WJazzD), the median per-track offset of the
near-beat onsets is +0.033 beats (quartiles +0.016 and +0.050, range
-0.050 to +0.095), and 44 tracks have more than a fifth of their near-beat
onsets over 0.18 beats late. Birks Works is +0.088 with 23%: in bar 4
Pepper plays the downbeat at 0.234, the "and" at 0.709, and every note of
the bar 0.22-0.33 beats behind the grid, and the listener writes the bar
on the beat. Under a sixteenth grid 0.234 is the "e" and 0.709 the "and",
and that is the tied sixteenth of the listener's first complaint
(2026-09-19). R27 took the dotted eighth out of the SPARSE beat; a beat of
three laid-back notes still reads on sixteenths, faithfully.

A human hears the line's own beat, not the drummer's. The quantizer
estimates the offbeat phase (the swing model's phi) and warps it to 1/2,
but it takes the downbeat at 0. The rule to measure is a second phase: the
median of the near-beat onsets over the swing window, subtracted before
the snap, bounded so that a genuine sixteenth (a run of four) is untouched.
This is the "laid-back beat after it" class of the quantizer instrument
and, unlike the counted rule that failed to transfer (D34.1), it is a
window statistic rather than a threshold at one beat line, so it should
survive the tracker's frame and CREPE's scatter. Measure it on the
instrument first, then through `run_eval`, as the transfer lesson requires.

### 2. There is no sixteenth-triplet grid

The Omnibook writes 4.9% of its notes as sixteenth triplets (six to the
beat) and puts 1.8% of its onsets on sixths; the listener 1.0% and 0.4%;
WJazzD 4.9% of gaps. We write none: the candidate grids are 2, 3, 4 and,
on evidence of collision, 8 per beat. A beat of six goes to sixteenths or
32nds, and that is most of our 32nds and dotted sixteenths (2.0-2.1% and
0.8-0.9%, against 0.2-0.3% and 0). Birks Works bar 16 is the case: the
listener writes C B Bb as a sixteenth triplet in the second half of beat 2
and we write a dotted sixteenth, a sixteenth and a dotted sixteenth, which
MuseScore shows as tied 32nds. Bar 16 also carries the line-phase problem
above, 0.17-0.33 beats late from the middle of beat 2 on.

A 6-per-beat candidate belongs in `choose_reading` under the same
evidence rule as the 32nd grid: admitted only where the sixteenth grid
cannot keep the onsets apart, and preferred to 32nds where the thirds
fit. Also a notate change (a 6:4 tuplet over half a beat, or 3:2 over a
sixteenth pair). The Omnibook's quintuplets and sextuplets (0.5%) are
Parker on a ballad and stay out of scope.

### 3. Rests are written to show the beat, and ours are not

The listener's rests are 90% eighth, quarter and half, and the Omnibook's
96%. Ours are 58% eighth rests and 10-11% DOTTED QUARTER rests, which the
listener writes 1.8% of the time and the Omnibook never. On the hand-score
set 135 of our dotted quarter rests start on the "and": a human writes an
eighth rest to the beat line and a quarter rest after it, two symbols that
show where the beat is. We also write 117 quarter rests starting on the
"and", across a beat line, where a human writes two eighths. This is
notate's rest splitting, not quantize: `split_points` halves a metrical
unit for notes and the same rule should apply to rests, with a rest that
starts off the beat closed at the next beat line first. It is pure
readability: no onset moves, so `rhythm` and `value` cannot see it, and
neither can `readability`, which counts sub-eighth rests only.

We also write a third more rests than the listener (0.18 per note against
0.16) and fewer quarter notes (5.6% against 9.4%): where we hear an eighth
and a gap we write an eighth and an eighth rest; the listener writes a
quarter. On the Omnibook set the counts match (0.13 per note both), so
this is partly the listener's own style, and `legato_cap` (off; measured
on WJazzD's durations, docs/m6-notate.md) is the knob already built for
it. Not a priority.

### 4. We under-write triplets

Triplet eighths: 5.7% against the listener's 9.0%, 5.3% against the
Omnibook's 8.7%; thirds 4.0% of our onsets against 7-8% of theirs. Part of
this is R28's trade (a triplet needs every onset inside the beat, which
put laid-back sixteenths back on the binary grid and lost some real
triplets); part is the quarter-note triplet (1.2% of the listener's notes,
D28, no onset rule reads it); part is the two-onset beat at (0.35, 0.75)
whose rule did not transfer. The instrument's "thirds written binary" class
(2.4%) is the count to move, and the WJazzD column above says why it is
hard: the annotator puts 13% of onsets on thirds, half of them swung pairs
we deliberately write as eighths.

### 5. Ties: twice the listener's, level with the Omnibook

Tie rate 0.049 against the listener's 0.023, but the Omnibook ties at
0.045 and we read 0.053 beside it. A tie is mostly a note across a beat
line or a bar line, and the Omnibook's transcriber writes those as we do.
The listener's complaint about ties is really the two above: a tied
sixteenth that should be an eighth on the beat (1), and tied 32nds that
should be a sixteenth triplet (2). Ties are a symptom here, not a lever;
D14 is closed by this survey rather than by a rule.

## After the lag rule (R29, the same evening)

Difference 1 shipped as `quantize.line_lag` (docs/wjazz-quantize.md has
the four versions and the instrument's verdict). The survey re-run under
it, same tracks:

| | ours before | ours after | hand scores | | ours before | ours after | Omnibook |
|---|---|---|---|---|---|---|---|
| onsets on the "e" | 6.2 | **3.3** | 1.8 | | 6.6 | **4.7** | 2.5 |
| odd 32nd positions | 2.5 | 2.0 | 0.1 | | 2.8 | 2.2 | 0.2 |
| dotted eighths | 2.6 | **1.1** | 0.1 | | 3.0 | **1.7** | 0.1 |
| triplet eighths | 5.7 | **8.4** | 9.0 | | 5.3 | **7.6** | 8.7 |
| sixteenths | 12.2 | 8.0 | 8.6 | | 14.6 | 11.3 | 11.8 |
| 32nds | 2.1 | 1.6 | 0.2 | | 2.0 | 1.6 | 0.3 |
| on the beat | 43.1 | 46.5 | 47.4 | | 42.4 | 44.9 | 40.8 |
| tie rate | 0.049 | **0.032** | 0.023 | | 0.053 | **0.042** | 0.045 |
| notes | 4747 | 4664 | 4332 | | 9469 | 9347 | 9974 |

The "e" halves, the dotted eighth falls by more than half, and two
things the rule was not written for moved with them: the triplet deficit
closed by half (a laid-back triplet had been read as sixteenths, and the
sixteenth share is now the human's), and the tie rate fell to within a
hundredth of the listener's. The cost is 1.3-1.7% fewer notes on the page
(the instrument's dropped count 7,079 -> 7,155): a beat shifted onto a
line a pushed note already holds still loses one where the guard does not
see it. Rests did not move, as expected: difference 3 is notate's.

What is left of difference 1 is the residue between our 3.3% and the
listener's 1.8%: beats lagging past the cap, beats the floor leaves
alone, and the genuine "e".

## After the rest rule (R30, the next morning)

Difference 3 shipped in notate: at the beat level and above a rest is
written only when it fills its metrical unit, and is otherwise divided at
the unit's own points, so a rest never straddles a beat line. Inside a
beat the ordinary rule stands (a dotted eighth rest stays one symbol; the
sixteenth rest a split would make is what readability counts, and the fix
for those is upstream). No note moves, so rhythm and value cannot move,
and did not: 0 up, 0 down on every page.

| rest | ours before | ours after | hand scores | Omnibook |
|---|---|---|---|---|
| eighth | 58.1 | 69.0 | 42.3 | 43.8 |
| quarter | 18.9 | 21.2 | 30.1 | 34.5 |
| half | 7.1 | 7.0 | 17.5 | 17.5 |
| dotted quarter | 9.9 | **0** | 1.8 | 0 |
| dotted half | 1.8 | 0.4 | 2.2 | 0 |
| dotted eighth | 1.8 | 1.1 | 0 | 0.2 |
| rests, hand-score set | 856 | 1006 | 674 | |

The dotted quarter rest is gone and the page shows its beats. We now
write more eighth rests than a human, not fewer, because every dotted
quarter became an eighth and a quarter; the remaining gap to the human is
the rest we write at all where the human writes a longer note value
(difference 3's second half, `legato_cap`, not a priority).

## After the ballad grids and the octave repair (R31, R32, 2026-09-21)

Re-run under both. The hand-score and Omnibook columns did not move (the
harness said the same: no page in either set changed). The WJazzD column
did, on the four grids that were tracked at half the pulse and are read
on the right octave now (R32), and on the ballads offered the finer grids
(R31); this column's "before" is the main table's, so it also carries
R29 and R30.

| ours on the WJazzD set (77 solos) | before | after | WJazzD located |
|---|---|---|---|
| on the beat | 41.8 | 44.7 | 34.6 |
| the "and" | 36.0 | 37.0 | 27.3 |
| the "e" | 8.2 | 6.0 | 7.2 |
| the "a" | 6.2 | 4.2 | 10.4 |
| thirds | 2.6 | 3.6 | 13.1 |
| sixths | 0 | 0.2 | 3.1 |
| odd 32nds | 5.1 | 4.0 | 1.5 |
| next onset an eighth | 47.4 | 50.3 | 35.0 |
| next onset a sixteenth | 17.8 | 14.5 | 15.0 |
| next onset a triplet eighth | 3.5 | 4.7 | 11.2 |
| next onset a sixteenth triplet | 0 | 0.4 | 4.9 |
| next onset a dotted eighth | 2.8 | 1.6 | 4.0 |
| next onset a 32nd | 4.2 | 3.1 | 2.3 |
| tie rate | | 0.064 | |
| notes | 36718 | 36619 | 35997 |

Read the WJazzD column as the annotator's tatum, not a page: it files a
swung pair at 3/4 and a laid-back beat at 1/4 (docs/wjazz-quantize.md),
so our "e" and "a" are BELOW it now and should be. The sixths and the
sixteenth triplet appear for the first time, from the ballads.

### What is left of difference 1 is isolated, not a phrase

The residue of the "e" (3.1% of the 3,783 matched notes on the twelve
hand scores, 118 notes) was paired note by note with what the human
wrote there (scratchpad `position_confusion.py`, same pairing as
`value_confusion.py`): 48 are on the beat in the score, 21 on a triplet
third, 17 on the "and", and 28 ARE on the "e" -- a quarter of them are
right. 103 of the 118 are not the first onset of their beat; 93 follow
our previous note by exactly a sixteenth, so the shape is a two-note
figure (0, 1/4) in a beat of two to four onsets where the human has (and,
beat) or a triplet -- the line's late "and" arriving on the beat line and
the beat's own note a quarter after it, which is a lag of a quarter beat
on the SECOND note only, past `lag_cap` and not what a window median can
see.

Wider than the "e": every matched note whose position class differs
from the human's, taken as a shift modulo the beat and grouped into runs
of consecutive shifted notes. Of 547 shifted notes, 463 are ISOLATED (a
single note between agreeing neighbours) and 84 sit in runs of three or
more; the longest runs are Peterson's bars 22-40 and Mobley's bars 51-53
at +0.75 (we are a sixteenth early, mostly our "and" against the
human's 2/3 or "a": the swing convention, not a defect). A phrase-level
rule -- a lag, a grid octave, a candidate set -- has nothing left to
move here; what remains is one note at a time, a sixteenth or an eighth
from where the human put it, and is the quantizer's per-beat decision
on an ambiguous onset or a note the aligner paired with its neighbour.
That is the reading the hand-score rhythm of 0.845 should be given.

## The value score: what we write instead (2026-09-21)

`value` reads 0.777 over the twelve hand scores: 842 of 3,783 matched
notes carry a different written length from the human's.
`scripts/value_confusion.py` tallies what we wrote and what they wrote,
with the one context that decides most of it -- whether a rest follows
our note, and whether one follows theirs.

| ours | theirs | rest after ours | rest after theirs | count | share |
|---|---|---|---|---|---|
| eighth | 16th | no | no | 73 | 8.7% |
| eighth | quarter | **yes** | **no** | 68 | 8.1% |
| eighth | quarter | no | no | 65 | 7.7% |
| eighth | triplet eighth | no | no | 59 | 7.0% |
| 16th | eighth | no | no | 56 | 6.7% |
| triplet eighth | eighth | no | no | 49 | 5.8% |
| eighth | quarter | yes | yes | 39 | 4.6% |
| quarter | eighth | no | yes | 31 | 3.7% |
| eighth | quarter-note triplet | no | no | 23 | 2.7% |

By context over all 842: no rest on either side 61.5%, a rest on both
14.6%, a rest after ours only 14.1%, a rest after theirs only 9.7%.

Three fifths of the value errors have no rest anywhere near them, so
they are rhythm differences wearing a value: an extra or missing note
beside the matched one, a triplet read binary or the reverse, the
quarter-note triplet (D28). Those move with the quantizer, not with any
duration rule. The one phrasing class is the second row: an eighth we
followed with a rest where the human wrote the note through as a
quarter, 68 notes. Two knobs already built for it were measured on the
pages:

- `NotateConfig.legato_cap` (a gap to the next onset short enough to be a
  note value is written into the note): at an eighth it changes nothing,
  because a gap that short never holds a rest; at a quarter it turns
  every eighth-plus-eighth-rest into a quarter, the 68 right ones and the
  many the human also writes as eighth and rest -- value 0.777 -> 0.752,
  Omnibook 0.714 -> 0.681.
- `NotateConfig.legato_fill` (the player held at least this share of the
  gap): at 0.75 and at 0.6 value is flat (+0.0002) and the tie rate rises;
  the probe behind it says why -- the notes the human wrote as quarters
  were held a median 0.42 of the gap and the ones written eighth-and-rest
  0.36. The player's hold does not tell the two apart; the human's choice
  is phrasing.

Both stay off. The value score's next movement comes from the rhythm
side, and the page is the judge of the remaining 68.

## What it means for the plan

The line phase (1) shipped the same day as R29, above; it was the largest
single difference in every table and it is what the listener's bar 4
showed. The sixteenth-triplet grid (2) was built and measured the same
night and is OFF: +2.1 on the instrument and worse on every Omnibook side
it touched (docs/wjazz-quantize.md), because on our onsets the figure is
not three notes at sixths. It stays a candidate-set change and
is a candidate-set change like the ballad work. The rest splitting (3) is
a notate change that costs an afternoon and moves no score, only the page.
The triplet deficit (4) is known and partly deliberate. Ties (5) are not a
lever.

Run this survey after any quantize or notate change. It is the one
measurement that says what we wrote instead, and the numbers above are
its baseline.
