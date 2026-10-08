# The PDF pages, round two: 44 recordings (2026-10-08)

The listener added 44 recordings to `benchmark/Transcriptions_Other/`, each
paired with a PDF transcription that pdf2musicxml had read into
`musicxml/`. This is what scoring them says, and what it says to do next.
Every number below is from the DEV split: the locked test split (E2) holds
nine of these pages out, and none of them was looked at.

## Placing them

37 were new (three were byte-identical copies of recordings already paired
inside `musicxml/`, three already had sidecars, and the Parker *Ballade* has
no MusicXML). `scripts/locate_scores.py` now also looks for a recording's
score in a `musicxml/` folder beside it, where pdf2musicxml writes. Each was
placed by content on a whole-file Roformer separation:

- **31 placed**, at 77-98% of the score lined up.
- **6 refused.** Parker's *Blue 'n' Boogie* (31%), Lester Young's *Tickle
  Toe* (38%) and *Every Tub* (56%) and Rollins's *I Know That You Know*
  (52%) read as other takes than the pages. Hawkins's *Ballade* (68%) and
  Young's *I Want to Be Happy* (82%) line up but not on one clock: bronze
  scans whose misread bar lengths bend the page's timeline.
- On four placed tracks the beat grid does not carry the score's pulse,
  so the tracker's downbeat stands: *My Ideal*, *Moment's Notice*, *Say It*
  and *The Jive Samba*.
- **No tempo octave errors.** All 21 pages with a printed tempo sit within
  7% of our grid, from 67 to 333 bpm. Oblivion's one-beat-per-bar grid was
  alone.

The scorecard: 28 trusted dev pages (21 silver, 7 bronze) plus Oblivion's
second take; *My Ideal* is below the coverage floor. No existing pin moved.

## What the pages say

### 1. Swing-era recordings are where hearing breaks, and tuning is why

The eight Lester Young, Coleman Hawkins and Ben Webster pages read pitch F1
0.729 against 0.862 for bebop and hard bop, and 98 edits per 100 notes
against 60. We get the pitch wrong on 10.7% of their notes (5.5% on the
others) and write 0.35 extra notes per reference note (0.10).

Measured with CREPE over each solo (circular mean of confident frames),
four of the Young sides are 15-30 cents SHARP of A440 -- 78s transferred a
little fast -- and Mobley's *Smokin'* is 30 cents flat. The modern
recordings sit within 13 cents. Pitch F1 falls with the offset (Young: +10
cents 0.879, +15 0.802, +21 0.790, +28 0.668, +30 0.635), and the semitone
errors lean the way the tuning does: on *Tea for Two* (+30) 9.6% of notes
are a semitone HIGH and 0.3% low; on *Smokin'* (-30) 5.1% low and 0.7% high.
The project ruled tuning out on 2026-09-30 over 175 modern recordings, none
past 30 cents; the swing-era transfers are a different population.

`TranscribeConfig.tuning_correction` (default off, out of every key while
off) takes the recording's own offset out of the frame pitches before
notes are rounded -- only there, so the harmonic-energy onset test still
looks at the true frequency -- when it is 10 cents or more. On the 27
trusted dev horn pages it corrected seven and left the rest alone:

| | before | after |
|---|---|---|
| pitch F1 | 0.782 | 0.848 (7 of 7 up) |
| note F1 | 0.517 | 0.583 (7 of 7 up) |
| rhythm | 0.790 | 0.837 (6 up, 1 down) |
| value | 0.694 | 0.750 (6 up) |
| edits per 100 notes | 83.3 | 65.5 (7 of 7 down) |

*Tea for Two* 0.635 -> 0.803, *Lester Leaps Again* 0.668 -> 0.791,
*Smokin'* 0.807 -> 0.883, Daahoud (+16 cents) 0.894 -> 0.910. The threshold
was set before the run and not tuned on it. The control over every other
set is in the last section.

### 2. Most extra notes are one note split in two

Placed against the page, our extra notes are NOT the band in the
soloist's stem: 75% (swing era) and 62% (hard bop) sit inside the
soloist's phrases, not in the page's rests. They touch a neighbour of ours
and are a semitone from it (51% / 55%) or the same pitch (30% / 18%). On
hard bop, 52% of the semitone ones come just BEFORE their neighbour and a
semitone BELOW it: a scoop into the note, split off. The WJazzD taxonomy
already names this (`attack_transient`, `body_late`: a 90 ms note a step
under, then the body) and the held note re-attacked (`split_sustain`,
`fragment_neighbour`), mid-table there; on the pages they are the commonest
extra note, and each one also shortens the note it was cut from -- a large
share of the value errors (we write an eighth where the page holds a
quarter: 288 notes on hard bop, 3.9% of matched notes on the triples).
A scoop is told from a chromatic approach note by its length and its
missing attack, not its interval: both sit a half step below.

### 3. On modern recordings the page is mostly writing

Bebop and hard bop: 60 edits per 100 notes, of which value 21.4 and
position 16.2. The triples -- a page, its recording and WJazzD's human
onsets for the same solo -- grow from eight to eleven with Daahoud, Speak
No Evil and Punjab (the new Joy Spring page is a different take from
WJazzD's, and the take check refuses it). Over the eleven the rhythm
distance is writing 0.180, grid -0.001, hearing 0.028. On the human onsets
the largest writing classes are a page triplet read binary (6.6% of
matched notes, 3.2% of intervals), an offbeat written on a beat (3.4% of
intervals), a downbeat written on an "and" (2.3%), and the page's quarter
written as our eighth.

### 4. What we miss is fast and low

Hard bop: 6% of eighths missed, 13% of sixteenths, 18% of 32nds, 24% of
sixteenth-triplets, 20% of quintuplets; 15% of notes more than a fifth
under the solo's median pitch. The Omnibook taxonomy found the same
(notes under an eighth: 27% of the book, 54% of its misses).

### 5. Placement problems are mostly the page's

Mean on-the-bar is 0.776 on silver pages and 0.482 on bronze. The harness
attributes 30 of 47 bar-line steps to the PAGE (an OMR bar holding 4.5, 5
or 6 beats); Punjab reads 0.30 on the bar even on WJazzD's own onsets and
beats, so its page is off, not our grid. What is the grid's:

- up-tempo slips: *Moment's Notice* (250-270 bpm, 8 steps, 4 doubted
  counts), *Spontaneous Combustion* (whole-beat steps);
- straight-eighth and latin feels: *The Jive Samba* half a beat off its
  page throughout, *Caravan* half a beat off for a few bars at a time;
- ballads: *Say It* (68 bpm) steps half a beat four times; *My Ideal*'s
  page advances 0.74 quarters per page quarter.

Five swing-era and hard-bop pages with no step at all put only 70-83% of
matched notes on the page's beat: writing (a line far behind the beat),
not the grid.

## Next, in order

1. **Switch the tuning correction on** -- done 2026-10-08 (the control and
   the shipped numbers are below).
2. **Merge scoops and re-attacks into the note they belong to.** A short
   note touching its neighbour a semitone below and before it, with no
   attack of its own, is the neighbour's scoop; a same-pitch fragment with
   no attack is the held note. Judge it on WJazzD's onsets (audio against
   audio, `attack_transient`/`split_sustain` counts) and on the pages'
   insertions and value errors together -- precision gained must not cost
   real chromatic approach notes.
3. **Writing**: triplets read binary and the quarter written as an eighth
   (which item 2 will partly fix) lead the triples' list. Hand rules are
   exhausted (docs/writing-round2.md); the paired pages here are A6's
   training data.
4. **Fast-note and low-register recall** for horns, still the hearing
   lever after tuning.
5. **Grid**: up-tempo slips, straight-eighth and latin tunes (the downbeat
   layer and the lag rule both assume swing), rubato ballads.
6. **Benchmark hygiene**: the six refused pairs (four are probably other
   takes -- worth a listen); bronze pages' overfull bars, which are most of
   the placement charge; and scanned pages whose OCR'd title is noise
   ("Hon Om rue Ocean") and is their split group, so a better OCR reading
   could move a track between dev and test.

## The control

`run_eval` over every set with `SWINGSCRIBE_TRANSCRIBE__TUNING_CORRECTION=
true` (threshold 10 cents), `--against` the day's card. Paired by
recording, 95% intervals:

- **Omnibook** (Parker's 1940s sides, the other old transfers): pitch F1
  +0.015 [+0.004, +0.032], 8 up 0 down, sign p 0.008; edits per 100 -2.8
  [-5.7, -0.5]; rhythm +0.011, value +0.009.
- **WJazzD**, audio against audio over 73 solos: note F1 +0.0027
  [+0.0006, +0.0052], 11 up 2 down.
- **Hand scores**: pitch F1 +0.004, 3 up 0 down -- but Art Pepper's *For
  Minors Only* rhythm -0.067 and value -0.063 on a near-level note F1.
- **PDF pages**: edits per 100 -4.6 [-9.2, -1.0], value +0.015, rhythm
  +0.012.

Every loss was a SMALL correction. Measured per corrected track (50 of
190 changed):

| offset | tracks | hearing change | up / down | page edits per 100 |
|---|---|---|---|---|
| 10-15 cents | 20 | -0.011 | 14 / 3 | -0.3 |
| 15-20 cents | 10 | +0.028 | 10 / 0 | -4.7 |
| 20-25 cents | 5 | +0.043 | 3 / 0 | -13.2 |
| 25+ cents | 4 | +0.132 | 4 / 0 | -30.2 |

The 10-15 band holds every loss -- Hawkins's *My Ideal* (untrusted, -0.31
pitch F1), Coltrane's *So What* (-0.023), Fuller's *Blue Train* (-0.014),
*For Minors Only*'s page -- and at that size a "tuning" is as likely a
player leaning sharp as a transfer running fast. So `tuning_min_cents` is
**15**: every one of the 19 tracks from there up heard better and none
worse, and a track under 15 keeps today's notes exactly, so this table IS
the threshold's effect. Chosen on dev data with the test split held out.

**On by default since 2026-10-08**, the listener's call on this table. It
acts only on CREPE's line (`TranscribeConfig.uses_tuning_correction`): a
pianist on the piano model's line keys exactly as before, so only horns and
the pianists' CREPE takes re-transcribed. The harness at 15 cents, paired
by recording against the card it replaced: 31 of 194 runs changed and the
other 163 are note for note what they were.

| set / measure | change [95% interval] | up / down |
|---|---|---|
| pages pitch F1 | +0.0157 [+0.0032, +0.0317] | 6 / 0 |
| pages edits per 100 notes | -4.33 [-8.81, -0.89] | 6 better / 0 |
| pages rhythm / value | +0.0118 / +0.0142 | 5 / 1, 6 / 0 |
| Omnibook pitch F1 | +0.0144 [+0.0026, +0.0311] | 5 / 0 |
| Omnibook rhythm / value | +0.0112 / +0.0082 | 5 / 1 |
| WJazzD note F1 | +0.0018 [+0.0003, +0.0038] | 4 / 0 |
| hand scores pitch F1 | +0.0025 | 1 / 0 (Confirmation) |

Silver pages' mean pitch F1 0.850 -> 0.867, edits per 100 64.4 -> 60.2;
bronze 0.773 -> 0.787. What reads down is small and explained: My Little
Suede Shoes (Omnibook, +15.6 cents, the smallest correction) rhythm -0.011;
Daahoud rhythm -0.004 with value +0.016; and two WJazzD solos' beat F1
(Blues For Alice -0.007, Cherokee -0.015), whose GRID did not change -- the
beat score places WJazzD's beats by a fit made from our notes, and that fit
moved by about 20 ms as their note F1 rose (+0.053, +0.027). Cherokee's page
also matches 21 more notes, which expose a half-beat excursion over bars
80-82 (WJazzD bar-line steps 45 -> 47).
