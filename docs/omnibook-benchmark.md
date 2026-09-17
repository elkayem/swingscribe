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
zero falls. The sidecar gets that extent as its region and its start as the
bar-1 anchor, and from then on the track is an ordinary benchmark tune.

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
| Au Privave 1 | 61 | 202 | 220 | 0.6-73.0 s | 82% |
| Bloomdido | 73 | 227 | 240 | 9.3-86.6 s | 83% |
| Blues For Alice | 49 | 168 | 165 | 6.4-76.3 s | 76% |
| Card Board | 66 | 202 | 210 | 0.0-77.5 s | 56% |
| Chasing The Bird | 65 | 190 | 210 | 0.3-82.3 s | 84% |
| Confirmation | 97 | 203 | 208 | 6.5-120.9 s | 80% |
| Dewey Square | 65 | 179 | 184 | 11.4-98.7 s | 86% |
| Donna Lee | 97 | 226 | 230 | 0.5-103.5 s | 87% |
| KC Blues | 38 | 118 | 126 | 7.1-84.6 s | 83% |
| Kim 2 | 97 | 320 | 320 | 6.8-79.6 s | 79% |
| Ko Ko | 129 | 301 | 308 | 25.3-128.2 s | 82% |
| Laird Baird | 50 | 155 | 162 | 10.6-88.2 s | 85% |
| Moose The Mooche | 65 | 209 | 224 | 0.0-74.8 s | 55% |
| My Little Suede Shoes | 66 | 146 | 148 | 11.7-120.4 s | 86% |
| Now's The Time 1 | 62 | 202 | 132 | 34.5-108.1 s | 79% |
| Now's The Time 2 | 50 | 129 | 220 | 11.5-104.4 s | 85% |
| Ornithology | 66 | 220 | 236 | 3.5-75.3 s | 57% |
| Red Cross | 66 | 208 | 210 | 3.4-79.7 s | 72% |
| Scrapple From The Apple | 64 | 198 | 200 | 10.7-88.3 s | 86% |
| Segment | 97 | 245 | 260 | 5.1-100.3 s | 83% |
| Shawnuff | 66 | 282 | 326 | 19.3-75.5 s | 67% |
| Yardbird Suite | 65 | 210 | 224 | 9.8-84.1 s | 76% |

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

## Results

Pinned 2026-09-17 (`tests/regression/real-audio-baselines.json`,
`summary/omnibook_*`), all 22 sides, every one above the coverage floor:

| side | pitch F1 | chroma | onset F1 | note F1 | coverage | rhythm | value | readability |
|---|---|---|---|---|---|---|---|---|
| Donna Lee | 0.881 | 0.885 | 0.734 | 0.684 | 0.86 | 0.785 | 0.748 | 0.9955 |
| Scrapple From The Apple | 0.878 | 0.885 | 0.734 | 0.674 | 0.84 | 0.863 | 0.776 | 0.9912 |
| Ko Ko | 0.872 | 0.877 | 0.750 | 0.678 | 0.82 | 0.778 | 0.711 | 0.9963 |
| My Little Suede Shoes | 0.861 | 0.861 | 0.613 | 0.551 | 0.85 | 0.674 | 0.692 | 0.9941 |
| Now's The Time 2 | 0.860 | 0.866 | 0.592 | 0.448 | 0.83 | 0.775 | 0.735 | 0.9837 |
| Bloomdido | 0.859 | 0.870 | 0.695 | 0.619 | 0.82 | 0.803 | 0.695 | 0.9981 |
| Laird Baird | 0.853 | 0.856 | 0.630 | 0.513 | 0.81 | 0.741 | 0.692 | 0.9856 |
| Kim 2 | 0.850 | 0.852 | 0.712 | 0.638 | 0.78 | 0.777 | 0.711 | 0.9966 |
| Dewey Square | 0.841 | 0.845 | 0.674 | 0.581 | 0.83 | 0.736 | 0.672 | 0.9939 |
| Confirmation | 0.838 | 0.841 | 0.614 | 0.509 | 0.79 | 0.710 | 0.629 | 0.9958 |
| Segment | 0.838 | 0.847 | 0.700 | 0.603 | 0.82 | 0.851 | 0.714 | 0.9905 |
| Au Privave 1 | 0.836 | 0.839 | 0.641 | 0.562 | 0.81 | 0.764 | 0.624 | 0.9975 |
| Now's The Time 1 | 0.828 | 0.836 | 0.648 | 0.541 | 0.78 | 0.699 | 0.618 | 0.9954 |
| Chasing The Bird | 0.820 | 0.825 | 0.663 | 0.571 | 0.83 | 0.721 | 0.652 | 0.9979 |
| KC Blues | 0.817 | 0.817 | 0.549 | 0.416 | 0.83 | 0.586 | 0.548 | 0.9818 |
| Red Cross | 0.793 | 0.816 | 0.645 | 0.553 | 0.72 | 0.645 | 0.524 | 0.9951 |
| Blues For Alice | 0.778 | 0.778 | 0.627 | 0.482 | 0.76 | 0.647 | 0.613 | 0.9950 |
| Yardbird Suite | 0.754 | 0.881 | 0.665 | 0.557 | 0.75 | 0.644 | 0.592 | 0.9976 |
| Shawnuff | 0.646 | 0.659 | 0.646 | 0.417 | 0.60 | 0.767 | 0.683 | 0.9838 |
| Ornithology | 0.585 | 0.857 | 0.624 | 0.409 | 0.56 | 0.664 | 0.612 | 0.9977 |
| Card Board | 0.557 | 0.794 | 0.633 | 0.367 | 0.55 | 0.739 | 0.646 | 0.9961 |
| Moose The Mooche | 0.546 | 0.827 | 0.636 | 0.406 | 0.53 | 0.667 | 0.558 | 0.9930 |
| **mean** | **0.790** | 0.837 | 0.656 | **0.535** | 0.76 | **0.729** | **0.657** | **0.9933** |

Every mean is over the same 22 sides; the tie rate beside readability is
0.068. For scale, the listener's own twelve tracks read mean note F1
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
  up at the right octave. Without them the mean pitch F1 is 0.826 over 19.
  Until the transposition was settled over the whole line rather than the
  opening (R23), those sides read 0.30-0.36 -- the prefix chose the head's
  octave and charged the entire solo for it.
- **Notation: rhythm 0.729 and value 0.657 at 0.76 coverage**, in
  the range the listener's own scores read (0.62-0.78 rhythm on the hand
  scores in docs/benchmark-deficiencies.md). The lowest rhythm is KC Blues
  (0.586), the slowest side at 118 bpm, where the book writes sixteenths --
  the quantizer's candidate set is tempo-blind (D11) and under 120 bpm a
  human puts 43.6% of values below a sixteenth; the highest are Scrapple
  (0.863) and Segment (0.851), medium-up eighth-note lines, which is where
  the grid rule was measured. Not yet taken apart note by note.
- **Readability 0.9933** against the human's 0.995: the page is
  writable everywhere, with 0.66 sub-eighth rests and 0.02 sub-sixteenth
  values per hundred events.
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
leave-one-out error). 2,752 errors, 6 unclassified. The short note leads, as
on WJazzD — notes under an eighth are 27% of the book and 54% of the
outright misses — then the semitone-off pair, then the head an octave low
(D30: 209 of 248 octave pairs on four sides' first chorus, Yardbird Suite
being the fourth). Re-articulation classes are nearly empty here, which is
the book's editorial convention and not the transcriber.
