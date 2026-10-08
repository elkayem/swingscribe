# Scoops and re-attacks: heard as notes, written as one (2026-10-08)

docs/pages-round2.md found that most of our extra notes on the PDF pages
are one note split in two, and the commonest shape is a short note a
semitone UNDER the note after it, touching it: a scoop into the note, cut
by the segmenter at the semitone it passed through. This is what deciding
where that note belongs found.

## The two references disagree, by convention

Every touching pair of our segmented notes a step apart, labelled against
each reference (scratch instruments `scoop_capture.py`, `scoop_features.py`,
`scoop_pages.py`; the frames are the stage's own, the tuning correction on):

- **WJazzD** (44 solos, human onsets in seconds): of the pairs a semitone
  apart with the lower note first, the annotator heard ONE note at the
  upper pitch from the lower note's onset 117 times, and two notes 1,303
  times. Its annotators mark a scoop as a note of its own.
- **The pages** (the hand scores, the Omnibook, the PDF pages): over the
  same shape the page writes only the upper note 328 times on the PDF pages
  against 768 pairs it writes as two (30%), and 179 against 520 on the
  Omnibook.

So the same pair is two notes to one reference and one to the other. Both
are right about what they are: WJazzD says what was played, the page says
how a transcriber writes it. A rule in the transcriber would trade one for
the other; the scoop belongs to WRITING.

## What tells a scoop from an approach note

A chromatic approach note also sits a semitone under its target. What
differs is the frames: a scoop slides through its semitone, an approach
note settles on it. Over WJazzD's pairs a semitone apart, lower first:

| | scoop (one note) | two notes |
|---|---|---|
| the lower note's length, median | 80 ms | 110 ms |
| its frames within a quarter-tone of its own semitone | **0.33** | **0.86** |
| a corroborated onset where the upper note begins | 5% | 34% |

On the pages, at a settled share of at most 0.5, at most 100 ms, and no
onset at the boundary: 125 pairs the page writes as one note against 64 it
writes as two (PDF pages), 79 against 48 (Omnibook), 16 against 11 (hand
scores). The page puts that one note where the SCOOP began three times in
four (92 of 125, 66 of 78, 12 of 16). Where the pair sits in the beat helps
only a little: a scoop a sixteenth before the beat is right 21 times in 25,
one on the "and" before a beat 54 against 43.

The fall-off the other way (a short note a step UNDER the one before it)
was read the same way and is not a rule: the Omnibook writes it as two
notes as often as one.

## Measured as a merge first

Applied to the cached notes (the scoop folded into its note at the scoop's
onset), scored by the harness's own functions (`scoop_ab.py`, paired by
recording, 95% intervals):

| setting | WJazzD note F1 | hand scores edits / rhythm / value | Omnibook edits | PDF pages edits |
|---|---|---|---|---|
| settled <= 0.34, <= 80 ms | -0.0022 (18 / 39) | -1.76 / +0.0040 / +0.0060 (4 / 0) | -0.24, level | -0.81 [-1.20, -0.44] (20 / 3) |
| **settled <= 0.5, <= 100 ms** | -0.0064 (14 / 51) | **-3.13 / +0.0075 / +0.0099 (5 / 0)** | -0.59, level | **-1.96 [-2.78, -1.17] (22 / 4)** |
| no settling test, <= 80 ms | -0.0176 (7 / 59) | -2.94 / +0.0044 / +0.0064 | -0.14, level | -2.20 |

(edits per 100 reference notes, lower is better; up / down by recording.)
The settling test is the rule: without it WJazzD pays three times as much
and the pages gain nothing more. And as a merge the WJazzD cost is real --
the transcription would stop holding notes a listener hears.

## So it ships as a grace note

`TranscribeConfig.glide_max_ms` 100 and `glide_max_stable` 0.5 MARK the
scoop (`NoteEvent.lead_in`, `transcribe.mark_lead_ins`); the line keeps it, so
the roll, the erase tool and every hearing measure see exactly what they
saw. Quantize (`QuantizeConfig.absorb_lead_ins`, swing timing only) folds a
marked scoop onto its note: the note starts where the scoop did and lasts
both, and the scoop's pitch rides along as its grace
(`QuantizedNote.grace`, `NotatedNote.grace`, written `<grace slash="yes"/>`
ahead of it). No heard note leaves the page: it is written the way a
transcriber writes a scoop.

A grace enters the scored line by the REFERENCE reader's rule
(`benchmark.grace_line`, `mscz.Score.graces`): a MusicXML page lets a grace
compete for the top of its position, so a scoop from below leaves the line
as it would a human's; the .mscz reader keeps a grace as a note of no
length, so on a hand score our grace is an insertion where the human wrote
none, as the separate note was. WJazzD's notation instrument keeps it.

## Re-attacks: the same convention at the same pitch

The other half of the roadmap item. Two of our notes at ONE pitch that
touch were cut by a corroborated onset (the segmenter cannot cut a held
pitch otherwise). Labelled the same way:

| the pair | pages: one note / two | WJazzD: one note / two |
|---|---|---|
| the first is 100 ms or less | hand 13 / 0, Omnibook 47 / 4, PDF 55 / 15 | 126 / 114 |
| the second is 100 ms or less | hand 9 / 0, Omnibook 28 / 21, PDF 50 / 20 | 88 / 128 |
| both longer | hand 17 / 31, Omnibook 29 / 91, PDF 83 / 220 | 193 / 736 |

A short HEAD -- the note re-attacked just after it began -- is one note on
the page 115 times in 134, and WJazzD's annotators split about evenly: the
same convention gap as the scoop, so the same split between hearing and
writing. Merged at the head's onset (scratch `reattack_ab.py`): hand scores
edits -1.33 [-2.54, -0.27], value +0.0025; Omnibook edits -0.91 [-1.63,
-0.29], rhythm +0.0041; PDF pages edits -1.19 [-1.93, -0.59], value +0.0034,
rhythm +0.0033. A short TAIL reads the other way on the PDF pages (rhythm
-0.0032 [-0.0061, -0.0006], 8 up / 16 down) and is not marked.

So the mark generalised: `NoteEvent.lead_in` is "this note leads into the
next one", a scoop or a re-attack head (`TranscribeConfig.reattack_max_ms`
100), and quantize's `absorb_lead_ins` writes the pair as one note -- a
scoop with its grace, a re-attack with none (the pitch is the note's own).

## Result

The whole harness with both kinds marked and folded, against the tuning-on
card (81faf95), paired by recording. Every hearing measure is unchanged by
construction -- WJazzD note F1 and every set's pitch F1 read the same
notes, and the error taxonomy reads all 148 counts unchanged.

| set / measure | change [95% interval] | better / worse |
|---|---|---|
| PDF pages, edits per 100 notes | **-2.97 [-4.19, -1.91]** | 25 / 2 |
| PDF pages, value / rhythm | **+0.0044** / +0.0029 | 15 / 6, 14 / 10 |
| hand scores, edits per 100 | **-1.05 [-2.10, -0.27]** | 5 / 0 |
| hand scores, rhythm / value | **+0.0032** / **+0.0032** | 5 / 0, 4 / 0 |
| Omnibook, edits per 100 | **-1.49 [-2.59, -0.41]** | 15 / 7 |
| Omnibook, rhythm / value | +0.0013 / -0.0012, level | 11 / 11, 7 / 14 |
| WJazzD notation (Flex-Q, collateral) | rhythm -0.0110, on the bar -0.0042 | |

Silver pages' edits per 100 go 60.2 -> 57.4 and their rhythm 0.824 ->
0.828, value 0.759 -> 0.764; bronze 78.5 -> 75.2; Omnibook 64.7 -> 63.3;
hand scores 55.2 -> 54.2. The scoops alone (the first run) read PDF pages
-1.88, hand scores -0.38, Omnibook -0.62 and level, with the Omnibook's
trade near even (insertions -1.03 per 100, deletions +0.69: some of what
reads as a scoop is a Parker approach note the book writes). Nothing is
decided down on a page set, and no heard pitch leaves the page (a scoop is
printed as a grace; a re-attack is its own note's pitch), so both ship ON
by the criterion of docs/writing-round2.md.

Flex-Q reads lower, and it is not a page measure (D36): its tatum layer
writes the scoop as a note and the main note where it SOUNDED, a sixteenth
after, and we now write the main note where the scoop began, as the pages
do three times in four. Three bar-line step counts each moved by one; the
traces show half-beat excursions over two bars that appear on How Deep and
Caravan and disappear on Punjab and Moment's Notice as different notes
match -- the grid did not change.

Pages carry 3-14 grace notes each (five checked); all five open in
MuseScore 4 (exit 0). A grace from below is spelled as its note's lower
neighbour (`export.grace_spelling`): F sharp into G, never G flat.
