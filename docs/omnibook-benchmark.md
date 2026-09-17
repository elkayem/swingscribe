# The Omnibook set: Parker's recordings against LORIA's MusicXML of the book

A third benchmark set, added 2026-09-17 beside the listener's own
transcriptions (`benchmark/*.mscz`) and the Weimar Jazz Database
(`benchmark/wjazzd/`). `benchmark/Omnibook/` holds the fifty scores of the
Charlie Parker Omnibook as MusicXML from LORIA, and the twenty-two of the
fifty recordings the listener could find, named like their scores. Nothing
in that folder is committed: the scores are a derivative of a copyrighted
book and the recordings are commercial (plan §12); only the aggregate
numbers here are.

Reproduce all of it with:

```bash
uv run python scripts/locate_scores.py --folder Omnibook       # sidecars, once
uv run python scripts/benchmark_batch.py --folder Omnibook     # the sheet
uv run python scripts/run_eval.py --db wjazz/wjazzd.db --cache-dir benchmark/.swingscribe-cache
```

The sheet is `benchmark/Omnibook/omnibook_test.xlsx`, one row per recording
with the same columns as `benchmark/benchmark_test.xlsx`; the harness pins
the set under `omnibook/` and `omnibook-notation/` in
`tests/regression/real-audio-baselines.json`, with means of its own
(`summary/omnibook_*`).

## What the Omnibook is evidence about

The plan (§6, layer 3) had this right before any of it was measured: the
Omnibook is useful for the *notation* layer, it is written in straight
eighths with the swing implied, and it carries two traps -- take-matching
(most Parker sides were issued in several takes) and editorial
interpretation (ghost notes dropped, enharmonics normalised). So it is
scored exactly as the listener's own transcriptions are, by the same two
functions, and it answers the same two questions:

- **pitch F1** (time-free, `alignment.align`): did we hear the right notes,
  in order?
- **rhythm / value** (`benchmark.score_against_notation`): are the notes we
  got *written* the way the book writes them? Never read without its
  coverage -- a located span can be the wrong take.

And **note F1**, the onset-and-pitch score placed at a constant tempo per
four-bar window, is reported for parity with the MuseScore set and reads
low for the same reason it does there: it charges the gap between performed
and notated timing to the transcriber.

What it is NOT: evidence about swing, or about the head. Bird's heads are
unison with a trumpet on most of these sides (Davis, Gillespie, Dorham,
Rodney), and the Roformer files both horns under `other`, so the head bars
are a two-horn line transcribed as one. The solo choruses are the
measurement.

## Locating the score: by content, never by hand

A listener's transcription covers exactly the span they drew, so bar 1 of
the score is the span's start by construction. The book's score covers the
head and Parker's choruses of a whole side, from wherever on the record they
start -- after a drum intro on Bloomdido, after a 32-bar intro the book
does not print on Ko Ko, and from a piano intro on Now's The Time. Nobody
drew a span, and drawing twenty-two by ear would have put a human judgement
under every number.

`scripts/locate_scores.py` finds it instead. The whole file is transcribed
(a whole-file Roformer separation, then the `other` stem end to end), and
`benchmark.locate_score` aligns the score's pitch sequence to what we heard
with the same time-free aligner every score here uses. Every true match is
an anchor (notated position, heard onset), and a Theil-Sen line through the
anchors -- the median of the pairwise slopes, immune to a minority of wild
points -- is the score's clock: seconds per quarter note, and where quarter
zero falls. That line places the score; its bar lines come from the beat
grid ("Bar 1 is a beat of the grid", below), and from then on the track is
an ordinary benchmark tune.

Two things were learned building it, both recorded in `benchmark.py`:

- **A whole file offers the aligner enough chance matches that the wrong
  octave can out-match the right one.** Choosing the transposition on a
  prefix, as the span-scoped scores do, put Ornithology at +12 with 195 of
  373 notes "matched" and 13 of them on any clock; at 0 it matches 213 with
  187 on one line. Raw coverage at a wrong offset reached 47-52% on three
  sides, above the 0.5 floor the span-scoped scores trust. So the
  transposition is chosen over the whole sequences by anchors *on the
  clock*, and the gate is the share of matches on the line (right sides
  70-88%, wrong offsets 6-39%) together with the share of the score the
  line accounts for (so a wrong take of the same tune, whose head lines up
  and whose solo does not, is not placed on its head alone).
- **The anchors are monotone by construction**, because the aligner walks
  both sequences in order -- so in uniformly dense music even chance
  matches sit near a line. The on-line share alone is not a control; the
  share of the score placed is what refuses an unrelated recording.

### The placements

All twenty-two placed, every one at transposition 0 (the LORIA scores are
at concert pitch), with the fitted tempo within a few percent of the score's
own marking except where the marking is plainly the wrong pulse (Now's The
Time 1 is marked 132 and plays at 202; Now's The Time 2 is marked 220 and
plays at 129). The clock is tight: the median anchor sits within 0.03-0.28 s
of the line on every side.

| side | bars | fitted bpm | marked | placed at | score lined up |
|---|---|---|---|---|---|
| Au Privave 1 | 61 | 202 | 220 | 0.3-72.8 s | 82% |
| Bloomdido | 73 | 227 | 240 | 9.2-86.7 s | 83% |
| Blues For Alice | 49 | 168 | 165 | 6.1-76.1 s | 76% |
| Card Board | 66 | 202 | 210 | 0.0-76.6 s | 56% |
| Chasing The Bird | 65 | 190 | 210 | 0.3-82.2 s | 84% |
| Confirmation | 97 | 203 | 208 | 5.6-120.1 s | 80% |
| Dewey Square | 65 | 179 | 184 | 11.4-98.6 s | 86% |
| Donna Lee | 97 | 226 | 230 | 0.2-103.1 s | 87% |
| KC Blues | 38 | 118 | 126 | 6.5-84.3 s | 83% |
| Kim 2 | 97 | 320 | 320 | 6.6-79.5 s | 79% |
| Ko Ko | 129 | 301 | 308 | 25.2-128.4 s | 82% |
| Laird Baird | 50 | 155 | 162 | 10.7-88.8 s | 85% |
| Moose The Mooche | 65 | 209 | 224 | 0.2-74.7 s | 55% |
| My Little Suede Shoes | 66 | 146 | 148 | 11.6-120.4 s | 86% |
| Now's The Time 1 | 62 | 202 | 132 | 34.0-107.8 s | 79% |
| Now's The Time 2 | 50 | 129 | 220 | 12.7-104.8 s | 85% |
| Ornithology | 66 | 220 | 236 | 3.3-75.3 s | 57% |
| Red Cross | 66 | 208 | 210 | 3.7-79.5 s | 72% |
| Scrapple From The Apple | 64 | 198 | 200 | 10.5-88.4 s | 86% |
| Segment | 97 | 245 | 260 | 4.4-99.8 s | 83% |
| Shawnuff | 66 | 282 | 326 | 19.2-75.6 s | 67% |
| Yardbird Suite | 65 | 210 | 224 | 9.5-84.1 s | 76% |

"Score lined up" is the raw share of the book's notes the whole-file
alignment matched, before any span was cut; the span-scoped coverage the
sheet reports is the number to read. The bar counts cross-check the
placements the way `docs/m3-benchmark.md` did for the first three tunes: a
12-bar blues head plus four choruses is 60 and a pickup (Au Privave, 61); a
32-bar head plus two choruses is 96 and a pickup (Confirmation, Donna Lee,
Kim, Segment, 97); Ko Ko's 129 is Parker's two 64-bar choruses, the book's
own intro being absent from the LORIA file.

Card Board's score begins a second before the recording does (the transfer
is cut into the pickup), so its region is clamped at zero and its implied
tempo is a shade high. Card Board, Moose The Mooche and Ornithology line up
markedly less of their score than the rest; whether that is the head (a
two-horn unison the Roformer leaves in `other`) or a different take than
the book's is what their span-scoped coverage below says.

### Bar 1 is a beat of the grid, not the line's intercept

The listener opened the first exports beside the book and found Au Privave
a beat early: the book's beat 2 printed on our beat 1, and its first two
notes missing. Measured over all twenty-two (the pages' true pitch matches,
our beat-in-bar less the book's): **eleven pages sat off the book's bar
lines** -- seven with every note a beat early, three a beat late, Segment by
two -- each by ONE constant from its first bar to its last (69-91% of
matches at the modal offset). The beat grid was sound; only the downbeat was wrong.

The cause was the placement, not the tracker. The sidecar's bar-1 anchor
was the Theil-Sen line's intercept, and a straight line through a side
whose tempo breathes puts quarter zero up to two beats from the music's
(Segment: the line's 245 bpm against a grid at 254). A stored anchor
overrides the tracker's own downbeat phase -- and that phase, the best
phase of the downbeat layer (`meter._auto_anchor`), **named the right beat
on all 22 sides**, and agrees with the listener's hand-placed downbeat on
the three of their own tracks that carry one. Writing our own made eleven
worse. The same intercept was the span's start, so on ten sides the span
opened after the book's bar 1 and the opening notes were never transcribed
(four of them on Confirmation).

`swingscribe.score_bars.bars_on_grid` reads the bar lines off the grid the
page is built on instead. Every on-clock match is a (score position, heard
onset) pair; the onset's fractional index on the repaired beat grid, less
the position, is the index of the beat that is quarter zero. One pair is
worth little -- a laid-back eighth sits a sixth of a beat late -- but
**86-98% of 139-568 votes per side name one beat of the bar**. The phase is
the majority's; bar 1 and the last bar line are read from the first and
last quarter of the score's notes, so a slipped beat or a chorus the book
omits moves only the end it is near. The span now opens a quarter-beat
(never under 80 ms) before that beat. Half a beat was tried first and let
a stray sound on the and-of-four into three spans, each written as a
one-note pickup bar; two such bars remain and are real (a scoop into Blues
For Alice's first note, the last note of the piano intro on Now's The Time
1, both inside 80 ms of the bar line). A grid that does not carry the
score's pulse (half or double time) spreads its votes over the bar, fails
the 0.6 share floor, and gets NO anchor written: the tracker's stands.
`locate_scores.py --bars-only` re-votes a downbeat without moving a stored
span, for a span someone has since corrected by hand.

**What moved when the spans did** (22 re-transcribed, re-pinned): mean
pitch F1 0.7904 -> 0.7905, note F1 0.5355 -> 0.5368, rhythm 0.7290 ->
0.7303, value 0.6567 -> 0.6559, readability 0.9933 -> 0.9949. The largest
single moves: Au Privave pitch +0.012 and note -0.026, Blues For Alice
rhythm +0.053 and value +0.040, KC Blues readability +0.012. Nothing on the
listener's set or WJazzD moved. The reason the defect went out at all is
that nothing pinned could see it: notated rhythm compares the gaps between
matched notes and is immune to a constant shift by construction.
`bar_line_agreement` is the measure that can, and the harness now pins it
for every hand-scored page -- 22 of 22 Omnibook pages at offset 0, and all
twelve of the listener's own (weakest Dexter Gordon's Confirmation, where
only 49% of matches sit at the modal offset; not yet looked at).

## Results

Pinned 2026-09-17 (`tests/regression/real-audio-baselines.json`,
`summary/omnibook_*`), all 22 sides, every one above the coverage floor --
re-pinned the same day once bar 1 came off the beat grid ("Bar 1 is a beat
of the grid", above; what moved is listed there). `bar line` is
`score_bars.bar_line_agreement`: how many beats our bar lines sit from the
book's, and the share of matched notes that say so.

| side | pitch F1 | chroma | onset F1 | note F1 | coverage | rhythm | value | readability | bar line |
|---|---|---|---|---|---|---|---|---|---|
| Scrapple From The Apple | 0.886 | 0.890 | 0.739 | 0.663 | 0.85 | 0.833 | 0.756 | 1.0000 | +0.0 (94%) |
| Donna Lee | 0.884 | 0.888 | 0.729 | 0.682 | 0.86 | 0.772 | 0.732 | 0.9970 | +0.0 (91%) |
| Ko Ko | 0.869 | 0.873 | 0.750 | 0.684 | 0.82 | 0.783 | 0.711 | 0.9988 | +0.0 (89%) |
| My Little Suede Shoes | 0.862 | 0.862 | 0.607 | 0.529 | 0.85 | 0.674 | 0.680 | 0.9881 | +0.0 (81%) |
| Bloomdido | 0.858 | 0.867 | 0.698 | 0.623 | 0.81 | 0.817 | 0.701 | 1.0000 | +0.0 (93%) |
| Laird Baird | 0.855 | 0.858 | 0.628 | 0.514 | 0.81 | 0.749 | 0.696 | 0.9879 | +0.0 (84%) |
| Now's The Time 2 | 0.851 | 0.858 | 0.592 | 0.439 | 0.82 | 0.767 | 0.724 | 0.9894 | +0.0 (85%) |
| Au Privave 1 | 0.848 | 0.851 | 0.633 | 0.536 | 0.82 | 0.783 | 0.648 | 0.9974 | +0.0 (88%) |
| Kim 2 | 0.848 | 0.851 | 0.712 | 0.639 | 0.78 | 0.765 | 0.697 | 0.9967 | +0.0 (87%) |
| Dewey Square | 0.846 | 0.851 | 0.688 | 0.592 | 0.84 | 0.735 | 0.668 | 0.9920 | +0.0 (88%) |
| Confirmation | 0.845 | 0.848 | 0.619 | 0.509 | 0.80 | 0.704 | 0.616 | 0.9930 | +0.0 (88%) |
| Segment | 0.836 | 0.845 | 0.691 | 0.598 | 0.81 | 0.812 | 0.688 | 0.9968 | +0.0 (92%) |
| Chasing The Bird | 0.826 | 0.826 | 0.678 | 0.588 | 0.84 | 0.722 | 0.674 | 0.9979 | +0.0 (86%) |
| Now's The Time 1 | 0.822 | 0.830 | 0.636 | 0.532 | 0.78 | 0.705 | 0.595 | 0.9953 | +0.0 (83%) |
| KC Blues | 0.812 | 0.812 | 0.565 | 0.406 | 0.83 | 0.595 | 0.552 | 0.9940 | +0.0 (77%) |
| Red Cross | 0.782 | 0.805 | 0.642 | 0.550 | 0.72 | 0.623 | 0.517 | 0.9950 | +0.0 (83%) |
| Blues For Alice | 0.780 | 0.780 | 0.643 | 0.506 | 0.76 | 0.700 | 0.653 | 0.9926 | +0.0 (77%) |
| Yardbird Suite | 0.750 | 0.874 | 0.675 | 0.564 | 0.74 | 0.645 | 0.585 | 0.9952 | +0.0 (82%) |
| Shawnuff | 0.647 | 0.660 | 0.659 | 0.436 | 0.60 | 0.787 | 0.654 | 0.9908 | +0.0 (83%) |
| Ornithology | 0.581 | 0.863 | 0.629 | 0.408 | 0.55 | 0.655 | 0.641 | 0.9953 | +0.0 (79%) |
| Card Board | 0.558 | 0.795 | 0.638 | 0.392 | 0.55 | 0.739 | 0.646 | 0.9961 | +0.0 (86%) |
| Moose The Mooche | 0.546 | 0.830 | 0.645 | 0.418 | 0.53 | 0.700 | 0.596 | 0.9976 | +0.0 (86%) |
| **mean** | **0.790** | 0.837 | 0.659 | **0.537** | 0.76 | **0.730** | **0.656** | **0.9949** | 22 of 22 at 0 |

Every mean is over the same 22 sides; the tie rate beside readability is
0.069. For scale, the listener's own twelve tracks read mean note F1
0.517 on the same measure, and WJazzD's seventy-three solos
0.858 on the audio-against-audio one that this set cannot
answer.

## What the numbers say

- **On nineteen of the twenty-two sides the transcriber reads pitch F1
  0.75-0.88** -- the same band as the listener's horn tracks, on mono 78-era
  transfers separated by a model trained on modern mixes. The book's
  editorial hand (ghost notes dropped, a run written straight) is in the
  `wrong`/`missed` columns of the sheet and is not the transcriber's to
  explain.
- **Three sides are held down by the head, not the solo** (D30 in
  docs/benchmark-deficiencies.md). Ornithology, Card Board and Moose The
  Mooche open with a head played in unison with a trumpet, and on those
  three we hear it an octave under the book; the solo that follows lines
  up at the right octave. Without them the mean pitch F1 is 0.827 over 19.
  Until the transposition was settled over the whole line rather than the
  opening (R23), those sides read 0.30-0.36 -- the prefix chose the head's
  octave and charged the entire solo for it.
- **Notation: rhythm 0.730 and value 0.656 at 0.76 coverage**, in
  the range the listener's own scores read (0.62-0.78 rhythm on the hand
  scores in docs/benchmark-deficiencies.md). The lowest rhythm is KC Blues
  (0.595), the slowest side at 118 bpm, where the book writes sixteenths --
  the quantizer's candidate set is tempo-blind (D11) and under 120 bpm a
  human puts 43.6% of values below a sixteenth; the highest are Scrapple
  (0.833), Bloomdido (0.817) and Segment (0.812), medium-up eighth-note lines, which is where
  the grid rule was measured. Not yet taken apart note by note.
- **Readability 0.9949** against the human's 0.995: the page is
  writable everywhere.
- **Take-matching, the plan's first trap, did not bite** on the twenty-two
  the listener found: every side placed by content at the book's bar
  count, at the right octave, and every span-scoped coverage clears the
  floor. The three low-coverage sides are the head, not another take.

## What moved elsewhere

Nothing on the listener's set or WJazzD moved for the Omnibook's sake: the
new sections and means are additions, and the whole-line transposition
returns the prefix's answer wherever the prefix was right. Red Garland's
Billy Boy moved on its own account (pitch F1 0.730 -> 0.722 default take,
0.768 -> 0.778 oracle take, and the pianist means with it): its sidecar
had lost its `stem` in an edit on 2026-09-13, the harness fell back to
`other` and heard nothing, and the stem was put back to `piano` -- the one
every addition and erasure on the sidecar names -- before pinning.

## Where the missing 0.21 goes

The error taxonomy reads this set too, as a block of its own
(`scripts/error_taxonomy.py`, docs/error-taxonomy.md section 10; pinned
under `omnibook` in `tests/regression/taxonomy-baseline.json`). Its hits
are this document's pitch-F1 matches, reproduced on all 22 sides, and each
book note is placed in time from the matched notes around it (19 ms median
leave-one-out error). 2,743 errors, none unclassified (the second pin, after
R24 moved the spans; 2,752 and 6 on the first). The short note leads, as
on WJazzD — notes under an eighth are 27% of the book and 54% of the
outright misses — then the semitone-off pair, then the head an octave low
(D30: 209 of 248 octave pairs on four sides' first chorus, Yardbird Suite
being the fourth). Re-articulation classes are nearly empty here, which is
the book's editorial convention and not the transcriber.
