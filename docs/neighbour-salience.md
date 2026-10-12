# The `neighbour` class: is the right pitch in CREPE's output?

2026-10-11. The last open item of the error taxonomy's list
(docs/error-taxonomy-review.md section 8, item 3). Instrument:
`scripts/neighbour_salience.py`. Nothing in the pipeline changed, no pin
moved, and no harness cache was written. The activations (CREPE full, 10 ms
hop, 360 bins per frame) and the per-pair table live OUTSIDE the repo, in
`C:\Users\lkmcg\swingscribe-research\crepe-activations`, because both are
derived from commercial recordings. Only the aggregates below are here.

**Answer: no. The kill criterion fired; step 2 (a decoder change) was not
built.** Under 0 of 318 semitone-off notes does CREPE's activation hold the
reference pitch as a second peak. Lowering the Viterbi step cost recovers 4
of 318 notes at most. In half the pairs the recording itself, both the stem
and the unseparated mix, puts the note BETWEEN the two semitones. In a
third, the recording sits on OUR pitch and disputes the annotation.

## The question

`neighbour` is the largest single horn error class on WJazzD: 834 of 6,731
horn errors over 68 solos (12.4%; `.benchmark-taxonomy-table.csv`,
2026-10-08). Our note starts within 50 ms of the annotated one and reads one
or two semitones off. Everything already known about it:

- The reference notes are short (median 78 ms) and in stepwise lines.
- CREPE's decoded f0 sat at the reference pitch in only 17% of the note's
  frames at the median (error-taxonomy.md 4.2).
- A 30 ms median filter does nothing (error-taxonomy-review.md section 3b.1).
  Basic Pitch has the right pitch on only 3-15% of these notes, and a pitch
  vote costs F1 (frontend-bakeoff.md).

What was never looked at: the review cache keeps the pitch AFTER Viterbi, so
nobody knew whether the reference pitch was in CREPE's activation as a
second peak the decoder passed over. If it were, a lower step cost or a
bleed-aware prior could take it.

**Kill criterion, fixed before the run:** if the reference pitch is a real
secondary peak in fewer than a third of the pairs, the error is not in the
decoder.

## The sample

The 10 horn solos with the most `neighbour` rows: 318 of the 834 pairs
(38%). CREPE was re-run over each solo's span on the GPU through
`transcribe._crepe_track`'s own Viterbi path, with the activations kept.

| solo | instrument | pairs | note F1, shipped decode | pinned |
|---|---|---|---|---|
| Joe Henderson, In 'n Out (198) | ts | 52 | 0.8630 | 0.863 |
| Wynton Marsalis, Cherokee II | tp | 41 | 0.7760 | 0.776 |
| J.J. Johnson, Blues In The Closet | tb | 31 | 0.7886 | 0.7886 |
| Freddie Hubbard, Maiden Voyage | tp | 30 | 0.7691 | 0.7691 |
| John Coltrane, Giant Steps | ts | 30 | 0.9146 | 0.9146 |
| Wynton Marsalis, Cherokee | tp | 30 | 0.8571 | 0.8571 |
| Joe Henderson, In 'n Out (199) | ts | 29 | 0.8478 | 0.8478 |
| Cannonball Adderley, This Here | as | 27 | 0.7770 | 0.777 |
| Joe Henderson, The Sidewinder | ts | 24 | 0.8511 | 0.8511 |
| Miles Davis, Dolores | tp | 24 | 0.8667 | 0.8667 |

Four tenors, four trumpets, a trombone and an alto. The median tempo of the
318 pairs is 277 bpm, so this is the class at its fast end, where it is
densest.

## The controls

**Reproduction.** The shipped decode (step cost 0.2), run from the kept
activations through the whole of `transcribe.analyze` (gates, segmenter,
line floors, Basic Pitch's fill), reproduces the harness's cached notes on
10 of 10 solos: the same count, the same pitches, onsets within 2 ms. Its
note F1 equals the pinned value on all ten, and all 318 table rows are notes
the shipped run writes. Basic Pitch's fill, not CREPE's line, wrote 16 of
the 318; every result below holds with those excluded.

**Calibration on notes we got RIGHT.** For each solo, 40 short reference
notes (≤ 0.2 s, median 90 ms) that mir_eval matched at the right pitch, 400
in all. Each was measured twice against a neighbour pitch d (+1 −1 +1 −1 +1
−1 +2 −2, the class's own mix):

| instrument | played pitch as "reference" (n = 400) | unplayed neighbour as "reference" (n = 400) |
|---|---|---|
| CREPE's decode chose it, half the frames | 339 | 0 |
| a secondary peak there | 0 (it is the top, not a second) | **0** |
| stem harmonic energy favours it by ≥ 3 dB | 382 (median +15.9 dB) | 1 |
| stem's comb peaks AT it (± 0.3 semitone) | 360 | 1 |
| mix's comb peaks AT it | 349 | 3 |

The secondary-peak test never fires at a pitch nobody played. The stem and
mix readings side with the played pitch nine times in ten.

**Positive control: can CREPE's activation hold a second peak at all?** Yes,
but only for a competitor as loud as the winner.

- **Real frames.** Over 115,505 voiced frames of the ten solos (top bin
  ≥ 0.5), a second local maximum 60-250 cents from the top stands at ≥ 0.25
  of it in 891 frames (0.77%), and at ≥ 0.1 in 2,002 (1.73%). So the test
  can fire.
- **Synthetic.** A harmonic tone at D4 plus a second tone d semitones up:

| second tone | activation at D4 | at the second pitch | second peak / top | where the top lands |
|---|---|---|---|---|
| +1, equal level | 0.76 | 0.36 | none | D4 **+0.46** |
| +1, 3 dB down (0.7) | 0.88 | 0.07 | none | D4 +0.06 |
| +1, 6 dB down (0.5) | 0.94 | 0.02 | none | D4 +0.06 |
| +2, equal level | 0.64 | 0.56 | 0.85 | D4 +0.06 |
| +2, 3 dB down | 0.90 | 0.06 | 0.07 | D4 +0.06 |
| +3, equal level | 0.75 | 0.25 | 0.34 | D4 +0.06 |
| +7, equal level | 0.77 | 0.09 | 0.49 | D4 +0.06 |

CREPE is close to winner-take-all. A second tone 3 dB under the first
vanishes from the activation at a semitone or a tone. Two equal tones a
semitone apart give ONE peak halfway between them, not two. Whatever is
quieter than the line under a short note is not in CREPE's output for any
decoder to find.

## 1. Salience: is the reference a secondary peak?

The frames are those whose centre lies inside the reference note, with the
fit's local residual taken out (`align_resid`). A secondary peak is a local
maximum within 30 cents of the reference pitch, at least 60 cents from the
chosen bin, at least 0.1 absolute and 0.25 of the chosen bin's height, in at
least half of those frames.

| reading (n = 318) | pairs |
|---|---|
| **real secondary peak at the reference** | **0 (0%)** |
| ... in a quarter of the frames instead of half | 4 |
| ... at a ratio of 0.1 or 0.5, or a floor of 0.05 or 0.2 | 0 at half the frames (3-4 at a quarter) |
| a secondary peak in ANY frame | 16 (5%) |
| the decode already chose the reference (within 30 cents) in half the frames | 11 (3%) |
| the per-frame argmax is the reference in half the frames | 11 (3%) |
| WIDE: anything within ±50 cents of the reference, the chosen bin included | 61 (19%) at half the frames, 118 at a quarter |

The wide reading is the most generous one possible. It counts a note
played BETWEEN the two pitches as being at both, and it still stays under a
third. By step direction the count is 0 for every one: +1 (n = 150), −1
(128), +2 (17), −2 (23). Our pitch equals an adjacent reference note's in
77 of 318 (24%), and none of those has a secondary peak either. The decoded
path sits within 30 cents of OUR pitch in a median third of the frames under
the reference note; the rest of the frames lie between.

## 2. The decoder: a lower step cost

Each decode is run as notes through the whole stage, and the solo is scored
as the scorecard scores it.

| step cost | pairs resolved (a note at the reference within 50 ms), n = 318 | mean note F1, 10 solos | solos up / down |
|---|---|---|---|
| 0.2 (shipped) | 0 | 0.8311 | |
| 0.1 | 3 | 0.8315 | 5 / 3 |
| 0.05 | 3 | 0.8313 | 4 / 3 |
| 0.02 | 3 | 0.8311 | 5 / 3 |
| 0 (per-frame argmax) | 4 | 0.8317 | 6 / 3 |

The largest move is +0.0006 over ten solos, inside the noise that 5-6 up
against 3 down describes. That agrees with the 5 ms hop measurement
(error-taxonomy-review section 10: "the step cost makes no difference at
either resolution"). There is nothing in the activation for continuity to
be standing in front of.

## 3. The recording: stem and mix

WJazzD's pitch is a human's reading of the audio, so the audio was asked
directly. Over the reference note's own span (never past the next reference
onset; median 74 ms), two readings were taken. The first is the harmonic
energy at both pitches in the chosen stem. The second is where a harmonic
comb scanned ±2.5 semitones peaks, in the stem and in the unseparated mix.

| where the comb peaks, n = 318 | stem | mix |
|---|---|---|
| at the reference (± 0.3) | 16 | 32 |
| at OUR pitch (± 0.3) | 116 | 90 |
| between the two | 165 | 151 |
| elsewhere | 21 | 45 |

- **Stem and mix agree on 263 of 318:** between/between 145, ours/ours 83,
  elsewhere/elsewhere 19, ref/ref 16. Separation did not make this up.
- **As a fraction of the way from the reference (0) to our pitch (1),** the
  stem's comb sits at p10 0.35, p25 0.50, median **0.65**, p75 0.90, p90
  1.05. Nearer our pitch than theirs in 212 of 318 (the mix: 185).
- **Harmonic energy:** the stem favours the reference by 3 dB in 32 pairs
  and our pitch in 160, with 126 undecided (median −3.0 dB). On notes we got
  right it favoured the played pitch in 382 of 400.
- **Not a short-window artefact.** Duration-matched against the
  calibration, notes we got right read "between" in 5 of 92 at 60-80 ms; the
  neighbour pairs read it in 59 of 102.

## 4. Bleed

Another stem (vocals, bass, guitar, piano) holds our pitch at least as
strongly as the chosen stem in 21 of 318 (7%). When the horn really plays a
pitch, this happens 4 times in 400 (the unplayed-neighbour control above,
where "ours" is the played pitch). So bleed is real here but small: 15 of
the 21 have the stem's comb at our pitch, 5 between.

## The causes

One per pair, first rule wins (`neighbour_salience.cause`). On the brief's
four classes: decoder-recoverable 0, absent from CREPE 9, the reference
disputed 101, and bleed 20. Another 157 are a disputed pitch of a second
kind: the recording sits between the two semitones.

| cause | rule | pairs (n = 318) | CREPE-written only (n = 302) |
|---|---|---|---|
| decoder-recoverable | a real secondary peak at the reference | **0** | 0 |
| decoded at the reference | the decode chose it in half the frames; the error is after CREPE | 11 (3%) | 9 |
| bleed | another stem holds our pitch as strongly | 20 (6%) | 20 |
| reference disputed | the stem's comb sits AT our pitch | 101 (32%) | 95 |
| between the two | the stem's comb sits between the pitches | 157 (49%) | 151 |
| absent from CREPE | the stem's comb sits AT the reference | 9 (3%) | 9 |
| stem unclear | elsewhere | 20 (6%) | 18 |

- **The disputed pairs.** On these, the stem favours our pitch by a median
  9.1 dB.
- **The between pairs.** These sit at 0.4 / 0.45 / 0.55 / 0.6 / 0.7 of the
  way to our pitch (p10-p90). That is a coin flip by pitch alone, and 26 of
  157 sit exactly halfway. 42 of the 157 are next to a reference note at our
  pitch: a window shared with the next or previous note reads halfway, as
  the synthetic +1 at equal level does. In the other 115 the note itself
  sounds between: a bend, a scoop or an off-centre passing tone. This
  instrument cannot say which.
- **By instrument.** Between leads on the trumpets (77 of 125) and the
  trombone (23 of 31). Disputed leads on the tenors (55 of 135) and the alto
  (13 of 27).
- **By solo.** No solo has a secondary peak. Dolores is 21 of 24 between.
  Maiden Voyage is 16 of 30 disputed.

## What it means

1. **The `neighbour` class is not in the decoder, and no decoder change
   should be built for it.** CREPE's activation does not keep a quieter
   competitor a semitone or a tone away, and under these notes it holds no
   second peak at the reference. A lower step cost moves 4 notes of 318.
2. **Half the class is a pitch BETWEEN two semitones in the recording
   itself**, read the same way in the stem and in the mix. The annotator
   chose one side; CREPE's rounding, and Basic Pitch, chose the other. The
   signal cannot decide those notes (median 0.55 of the way across). A fix
   there would have to come from musical context, such as the key, the
   chord, or the line's direction, and that is a different instrument from
   anything measured here.
3. **A third of the class is the recording at OUR pitch**, on the stem
   (median 9 dB over the reference) and on the mix. Basic Pitch has the
   reference pitch on only 3-15% of this class (frontend-bakeoff.md), so
   three readers built on different principles stand against one
   annotation. These pairs should not be chased as transcription errors.
   The 0.0272 of F1 the taxonomy charges to `neighbour` overstates what a
   transcriber can win back, by at least this third.
4. **What is left for a transcriber is small:** absent from CREPE 9 and
   decoded at the reference 11, 6% of the sample. The second of these is
   after CREPE (smoothing and rounding of a note held within 30 cents of the
   reference), not in it.

## Reproducing

    .venv\Scripts\python.exe scripts/neighbour_salience.py --db wjazz/wjazzd.db
    .venv\Scripts\python.exe scripts/neighbour_salience.py --db wjazz/wjazzd.db --positive-control

The first command takes about five minutes on the RTX 3050: CREPE is
10-20 s per solo, and the rest is six `analyze` passes per solo (five step
costs, and the fill switched off) with Basic Pitch inside each. Activations
are reused from `--out` once computed. The script reads the taxonomy table
(`scripts/error_taxonomy.py`) and the harness's notes cache. A solo whose
shipped decode does not reproduce the cached notes says so on its line.
