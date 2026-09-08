# Where the 0.145 goes: an error taxonomy for the WJazzD benchmark

2026-09-07. The WJazzD benchmark reads mean note F1 **0.8549 over 73 solos**
(`scripts/run_eval.py`, pinned). This document is the instrument that says
where the other 0.1451 goes, and what it said the first time it was run.
Nothing in the transcriber was changed to produce it.

**Second reading, same day.** `docs/error-taxonomy-review.md` is an
independent analysis of this document's raw table. Three of its findings
changed the instrument and the baseline was re-pinned (2026-09-07, later):
a missed onset past our note-off is no longer "covered" (the frame rules
read the gap), an other-pitch coverer that ends within 60 ms of the missed
onset is `squeezed` rather than `absorbed`, and every pair carries the
alignment's local residual. Mean F1, the error count and the deficit are
unchanged; what moved is how the 2,461 old `absorbed` rows are named, and
every number below is the re-pinned one.

**Third pin, the overnight run (2026-09-07, later still).** The transcriber
DID change after that: `pitch_persist_ms` 60 → 40 and the piano model's
onset shift in `fill_gaps`, one CACHE_VERSION bump. Mean F1 0.8549 →
0.8583 over the same 73, errors 7,707 → 7,583, `absorbed` 948 → 333 and
`too_short` 345 → 765. The tables below are the SECOND pin's — the one
this analysis was written against — and the third pin's paired deltas, the
page-side cost and what leads the Pareto now are in
`docs/error-taxonomy-review.md`, section 7. Re-running this instrument
after any transcribe change now needs `scripts/wjazz_reviews.py` first
(D26), or the frame-evidence classes vanish into `unclassified`.

Reproduce:

    .venv\Scripts\python.exe scripts/error_taxonomy.py --db wjazz/wjazzd.db
    .venv\Scripts\python.exe scripts/error_taxonomy_page.py --out pareto.html

The first command classifies, prints the Pareto, writes the per-note table
(`.benchmark-taxonomy-table.csv`, gitignored) and the listener's spot-check
sample (`benchmark/wjazzd/error-taxonomy-spotcheck.csv`), and diffs every
class count against `tests/regression/taxonomy-baseline.json`; `--pin`
rewrites that file. The second renders the committed aggregate as a page.

## 1. Method

**Population.** The same cached transcriptions the scorecard scores
(`.benchmark-notes-c0.2-d0.0.json`, 2026-09-02 Roformer stems and line
floors), located inside their recordings by `score_wjazz.identify_all`
exactly as `run_eval.py` does — same fit, same 15% floor, same span
(placed first reference onset − 0.25 s to placed last + 0.25 s). 73 solos:
68 horns (26 trumpet, 21 tenor, 13 alto, 5 trombone, 3 soprano), 4 pianists,
1 guitarist. 33,833 reference notes, 32,385 of ours.

**Hits.** `mir_eval.transcription.match_notes` with the benchmark's own
tolerances (50 ms onset, 50 cents, offsets ignored). The classifier never
re-scores: the note F1 read off its hits equals the pinned value on every
one of the 73 solos (the script checks each against
`tests/regression/real-audio-baselines.json` and prints `DISAGREES` if any
differ by more than 0.002; none do), and the per-class F1 costs sum to
0.1451, the whole deficit, by construction (`taxonomy.f1_deficit`).

**Three populations.** Before classifying, the unmatched notes on the two
sides are paired one-to-one within 150 ms (`taxonomy.pair_unmatched`,
minimum-cost assignment on onset distance, a same-pitch partner preferred by
50 ms). A pair is one error, counted once but costing both a miss and a
false positive — its weight in the F1 decomposition is 2/(R+E). What is not
paired is a pure miss (theirs, nothing of ours near it) or a pure false
positive (ours, nothing of theirs near it).

| population | n | share of errors |
|---|---|---|
| miss | 3,384 | 43.9% |
| false positive | 1,936 | 25.1% |
| pair | 2,387 | 31.0% |

**Both readings of the pairing.** Without the same-pitch preference 103 of
the 2,387 pairs (4.3%) would have a different partner. The table carries
the raw `dt` and `dpitch` of every pair so either reading can be re-cut.

**Evidence.** Every rule that needs more than the two note lists asks an
`Evidence` object and is skipped, never guessed, when the answer is None:

- *frames* — CREPE periodicity, the energy gate and the gated, smoothed
  pitch under each reference note, read from the GUI review cache under
  `benchmark/.swingscribe-cache`, which holds the note-for-note identical
  transcription for all 74 batch solos (verified by comparing every onset
  and pitch; a payload that differs is refused);
- *stem* — RMS and harmonic energy read from the separated stems with
  soundfile and numpy: digital silence (`SILENT_RMS`), each note's loudness
  against its matched neighbours, and the harmonic energy at a false
  positive's pitch in the other melodic stems (vocals, bass, guitar, piano;
  harmonics 1-4, ±3%) relative to the chosen stem;
- *the piano model* — `oracle-notes/` in the same cache, the polyphonic
  model's full output for the four pianists, consulted for piano misses
  only.

**Families and tempo.** `taxonomy.family_of` maps WJazzD's instrument code
to horn / piano / guitar / other; tempo bands are WJazzD's own `tempoclass`
(SLOW < 80 bpm, MEDIUM SLOW, MEDIUM 112-140, MEDIUM UP 140-180, UP ≥ 180).

## 2. The rule table, in decision order

The first rule that fires wins (`swingscribe.taxonomy.RULES`, one test per
rule in `tests/test_taxonomy.py`). "Covers" means the onset falls inside a
note's span, more than 50 ms after its onset; for a false positive the span
extends 50 ms past the reference note-off (a release), for a miss it ends
at OUR note-off — an onset past it sits in a gap the frame rules can read.

| population | class | fires when |
|---|---|---|
| pair | timing_late | same pitch, ours 50-150 ms after theirs |
| pair | timing_early | same pitch, ours 50-150 ms before theirs |
| pair | attack_transient | pitch differs and a note of ours at the reference pitch begins later inside the reference note |
| pair | octave | onsets within 50 ms, pitch 12 or 24 off |
| pair | neighbour | onsets within 50 ms, pitch 1 or 2 off |
| pair | other_pitch | onsets within 50 ms, any other pitch |
| pair | loose | pitch differs and onsets 50-150 ms apart |
| miss | merged | a note of ours at the same pitch covers the onset |
| miss | absorbed | a note of ours at another pitch covers the onset and runs on ≥ 60 ms past it |
| miss | squeezed | a note of ours at another pitch covers the onset and ends within 60 ms of it |
| miss | not_picked | pianist; the polyphonic model has this pitch within 100 ms |
| miss | left_stem | chosen stem digitally silent under the note (R16) |
| miss | gated | no frame under the note is both energetic and voiced |
| miss | unvoiced | energetic frames, periodicity never reaches 0.5 |
| miss | too_short | gated pitch at the reference pitch for 1-5 frames (under min_note_ms) |
| miss | dropped_register | a ≥ 60 ms run at the reference pitch, more than 12 semitones under our line's local median (D22 floor) |
| miss | dropped | a ≥ 60 ms run at the reference pitch and no note emitted |
| miss | tracked_octave | live frames an octave from the reference pitch |
| miss | tracked_other | live frames at some other pitch |
| miss | unclassified | none fired, or no evidence |
| fp | split_sustain | inside a same-pitch reference note (D2) |
| fp | body_late | the body behind an attack_transient (relabelled from split_sustain) |
| fp | bleed_register | more than 12 semitones under the reference line's local median (2 s window) |
| fp | bleed_cross_stem | another stem holds at least as much harmonic energy at this pitch |
| fp | fragment_octave / fragment_neighbour / fragment_other | inside a reference note at another pitch: 12/24, 1/2, or any other semitones off |
| fp | between_phrases | no reference note sounding, in a gap of ≥ 1 s |
| fp | between_notes | no reference note sounding, in a shorter rest |
| fp | unclassified | none fired |

Why this order: a note of ours whose span covers the missed onset explains
the miss better than any frame reading about the same instant, so the
covering rules go first; the piano model's opinion goes before the stem and
frame rules because it is the question the piano path actually asks; digital
silence goes before the gates because a gate reading over silence is not
evidence; and for false positives, "inside a reference note at the same
pitch" is unambiguous, so it goes before the bleed tests that a fragment
could also trip. Every miss carries its frame facts and (for a pianist) the
model's opinion whatever rule fired, so the pre-empted readings can be
re-cut from the table.

`unclassified` after the final run: **0 of 7,707** (the
threshold is 10%).

## 3. The Pareto

All 73 solos, 7,707 errors. `F1 cost` is the class's share of the mean
(1 − note F1), and the column sums to 0.1451. `sd` is the bootstrap spread
of the count over 1,000 resamples of the 73 solos (section 6).

| class | n | share | cumulative | F1 cost | of the deficit | sd |
|---|---|---|---|---|---|---|
| squeezed | 1,018 | 13.2% | 13.2% | 0.0143 | 9.8% | 104 |
| neighbour | 964 | 12.5% | 25.7% | 0.0272 | 18.7% | 98 |
| absorbed | 948 | 12.3% | 38.0% | 0.0133 | 9.1% | 115 |
| merged | 631 | 8.2% | 46.2% | 0.0091 | 6.3% | 64 |
| fragment_neighbour | 585 | 7.6% | 53.8% | 0.0094 | 6.5% | 56 |
| split_sustain | 453 | 5.9% | 59.7% | 0.0075 | 5.1% | 58 |
| timing_late | 357 | 4.6% | 64.3% | 0.0110 | 7.6% | 46 |
| too_short | 345 | 4.5% | 68.8% | 0.0047 | 3.2% | 72 |
| timing_early | 300 | 3.9% | 72.7% | 0.0094 | 6.5% | 40 |
| between_notes | 266 | 3.5% | 76.1% | 0.0036 | 2.5% | 50 |
| attack_transient | 224 | 2.9% | 79.0% | 0.0064 | 4.4% | 46 |
| loose | 207 | 2.7% | 81.7% | 0.0062 | 4.3% | 22 |
| fragment_other | 194 | 2.5% | 84.2% | 0.0024 | 1.6% | 46 |
| other_pitch | 194 | 2.5% | 86.8% | 0.0052 | 3.6% | 29 |
| tracked_other | 189 | 2.5% | 89.2% | 0.0027 | 1.8% | 27 |
| body_late | 186 | 2.4% | 91.6% | 0.0027 | 1.9% | 42 |
| dropped | 160 | 2.1% | 93.7% | 0.0026 | 1.8% | 17 |
| octave | 141 | 1.8% | 95.5% | 0.0031 | 2.1% | 45 |
| between_phrases | 105 | 1.4% | 96.9% | 0.0013 | 0.9% | 31 |
| bleed_cross_stem | 102 | 1.3% | 98.2% | 0.0015 | 1.0% | 17 |
| dropped_register | 43 | 0.6% | 98.8% | 0.0005 | 0.4% | 10 |
| bleed_register | 27 | 0.4% | 99.1% | 0.0002 | 0.1% | 13 |
| not_picked | 22 | 0.3% | 99.4% | 0.0003 | 0.2% | 13 |
| fragment_octave | 18 | 0.2% | 99.6% | 0.0002 | 0.1% | 9 |
| tracked_octave | 17 | 0.2% | 99.9% | 0.0003 | 0.2% | 8 |
| unvoiced | 8 | 0.1% | 100.0% | 0.0001 | 0.1% | 4 |
| gated | 3 | | | 0.0001 | | 2 |
| left_stem | 0 | | | | | |

These are the re-pinned counts (`tests/regression/taxonomy-baseline.json`,
2026-09-07, after the second reading). Against the first pin the old
`absorbed` (2,461) became `absorbed` 948 + `squeezed` 1,018, and its 496
slack cases — plus 42 of `merged`'s — went where the frame rules put them:
`too_short` 112 → 345, `tracked_other` 52 → 189, `dropped` 45 → 160,
`not_picked` 4 → 22, `dropped_register` 26 → 43, `tracked_octave` 3 → 17,
`unvoiced` 5 → 8. `tracked_other` is 171 horn, 11 piano and 7 guitar rows.

Grouped by mechanism, which is how the fixes divide:

| mechanism | classes | n | share | F1 cost | of the deficit |
|---|---|---|---|---|---|
| under-segmentation: a fast note run straight through | absorbed | 948 | 12.3% | 0.0133 | 9.1% |
| under-segmentation: a fast note with no boundary of its own | squeezed | 1,018 | 13.2% | 0.0143 | 9.8% |
| a same-pitch repeat heard as one note | merged | 631 | 8.2% | 0.0091 | 6.3% |
| wrong pitch on a short note | neighbour, other_pitch, loose | 1,365 | 17.7% | 0.0386 | 26.6% |
| onset just outside tolerance | timing_late, timing_early | 657 | 8.5% | 0.0204 | 14.1% |
| a held note cut on a DETECTED ONSET | split_sustain | 453 | 5.9% | 0.0075 | 5.1% |
| a held note cut on a PITCH EXCURSION | fragment_neighbour, fragment_other, fragment_octave | 797 | 10.3% | 0.0120 | 8.2% |
| an attack split off at its own pitch | attack_transient, body_late | 410 | 5.3% | 0.0091 | 6.3% |
| extra notes outside the line | between_*, bleed_* | 500 | 6.5% | 0.0066 | 4.5% |
| the gap between two of our notes (gates and tracking) | too_short, dropped*, unvoiced, gated, tracked_*, left_stem, not_picked | 787 | 10.2% | 0.0112 | 7.7% |
| octave | octave | 141 | 1.8% | 0.0031 | 2.1% |

The re-attacked held note is two rows because the second reading found two
mechanisms under one name: 67% of `split_sustain` cuts sit on a corroborated
onset tick (the detector made them; the fix is `corroborate_onsets`, and it
competes with `merged`), while 89% of `fragment_neighbour` cuts sit on none
(`_pitch_change_points` made them; the fix is the persistence rule, and it
competes with `absorbed`). Under-segmentation is two rows for the same
reason: the geometry is different (4.1), even if the threshold is the same.

### 3.1 By family

**Horns (68 solos, 7,291 errors, mean note F1 0.8521; pooled precision
0.860, recall 0.827).** The overall table is the horn table: neighbour 949
(13.0%), squeezed 935 (12.8%), absorbed 798 (10.9%), merged 616 (8.4%),
fragment_neighbour 570 (7.8%), split_sustain 452 (6.2%), too_short 339,
timing_late 326, timing_early 286, between_notes 248, attack_transient 221,
loose 204, other_pitch 191, fragment_other 186, body_late 184, tracked_other
171, dropped 159, octave 141, between_phrases 103, bleed_cross_stem 100,
dropped_register 41, bleed_register 27, fragment_octave 17, tracked_octave
15, unvoiced 4, gated 2. Under-segmentation (absorbed + squeezed) is 17.6%
of the horn deficit, wrong pitch on a short note 27.5%, timing 13.8%, the
two held-note mechanisms 5.4% and 8.6%, the gap classes 7.4%.

**Pianists (4 solos, 335 errors, mean note F1 0.8948; pooled precision
0.963, recall 0.853).** `absorbed` 148 and `squeezed` 74 are 222 of 335 (66%) and
54.5% of the piano deficit; timing 42 (12.5%, 22.0% of the deficit);
`not_picked` 22 (the slack cases the model heard); everything else is
single digits. Only 16 of the 335 are false positives — the second
opinion (M7b) has bought the precision it was built for, and what is left
is recall. **n is 4** (Hancock ×3 at 265-286 bpm, Garland at 265), all
transcribed from the Roformer's `piano` stem with the oracle consulted, and
the brief's "pianos sit at recall 0.54-0.70" is the hand-scored set's
number, not this one; this set's pianists read better than its horns.
Nothing here generalises beyond fast trio piano.

**Guitar (1 solo, Metheny, 81 errors, note F1 0.8857).** absorbed 20,
between_notes 14, fragment_neighbour 11. One solo; reported for
completeness, not read.

### 3.2 By tempo class

| tempo class | solos | mean F1 | errors | three largest |
|---|---|---|---|---|
| SLOW (< 80) | 3 | 0.9047 | 187 | squeezed 26, timing_early 24, split_sustain 20 |
| MEDIUM (112-140) | 17 | 0.8387 | 1,723 | neighbour 216, fragment_neighbour 163, squeezed 152 |
| MEDIUM UP (140-180) | 22 | 0.8441 | 2,409 | squeezed 365, absorbed 277, neighbour 250 |
| UP (≥ 180) | 31 | 0.8668 | 3,388 | absorbed 538, neighbour 488, squeezed 475 |

Under-segmentation (absorbed + squeezed together) leads in every band, and
`absorbed` proper — the run-through — grows with tempo while `squeezed`
holds its share. At MEDIUM the held-note classes
(fragment_neighbour, split_sustain, timing) take a larger share — longer
notes, more chance to cut one — and at UP the short-note classes dominate.
No MEDIUM SLOW solo is in the set.

## 4. The three largest classes, what a fix would move, and what it puts at risk

### 4.1 `absorbed` + `squeezed` — 1,966 (25.5%, 0.0276 of F1, 18.9% of the deficit)

Written first about the single class `absorbed` (2,461 at the first pin);
the numbers in this subsection's "What it is" and "What the frames say" are
that population's, and the split that followed is at the end.

**What it is.** A reference note whose onset falls inside a note of ours at
another pitch. The reference notes are short and fast: median duration
**58 ms** (p25 43, p75 78), median gap from the previous reference onset
**104 ms** (p25 74, p75 146). The covering note is at the *previous*
reference note's pitch in 1,912 of 2,461 cases (78%), was itself matched to
that previous note in 2,099 (85%), and is 170 ms long at the median — so
the picture is one note of ours running straight through the next one or
two of theirs. Adjacent pitches: |covering dpitch| ≤ 2 in 1,310 (53%),
≤ 5 in 2,220 (90%).

**What the frames say (horns, 2,192).** The gated, smoothed pitch
`segment_notes` saw:

| bucket | n | share |
|---|---|---|
| reached the reference pitch, but for 10-50 ms only (under the 60 ms `pitch_persist_ms` / `min_note_ms`) | 1,362 | 62% |
| reached it for ≥ 60 ms and still did not split | 225 | 10% |
| raw f0 touched it, the 50 ms median filter removed it | 139 | 6% |
| never at the reference pitch: the tracker stayed on the other note | 466 | 21% |

So in two thirds of the cases the note was *heard* — the pitch trace has
it — and the segmenter merged it because the excursion was shorter than the
persistence it demands. For scale, 11.1% of all 33,833 reference notes are
under 60 ms and 28.0% start under 100 ms after the previous one: the
transcriber's split thresholds sit at the length of the music's own notes.

**Concentration.** absorbed is 64% and 42% of the errors on Coltrane's two
My Favorite Things solos, 49% on Blue Train, 78% on Hancock's Gingerbread
Boy, 36-44% on the Cherokees, In 'n Out and Maiden Voyage. Its bootstrap sd
(263, 11% of the count) is the largest of any class for this reason; a fix
should be measured per solo, not on the mean.

**The split (second reading).** How much of our note is left after the
missed onset: in 496 of 2,461 (20%) our note had already ENDED (the onset
sat in the 50 ms cover slack — not covered at all now, and filed by the
frame rules); in 1,017 (41%) fewer than 60 ms of ours remained
(`squeezed`); in 948 (39%) our note ran on for 60 ms or more (`absorbed`
proper). The reference note is 53 ms long in the first two groups and 67 ms
in the third. Three fifths of the old class is therefore a boundary that
landed late on a note with no room, not a note tracked through.

**What a fix would move.** The document first named 1,501 misses (the
short-run and filter buckets) as the target, 0.021 of F1. The second reading
measured it (`docs/error-taxonomy-review.md`, section 3): re-segmenting the
cached traces over 67 horns, a 50 ms persistence and floor cut the old class
by a third in 66 of 67 solos and moved mean F1 by +0.0035 with 35 solos up
and 32 down — the freed excursions land in `fragment_neighbour` and
`between_notes` almost one for one. A threshold cannot separate the two
populations because they are one population. The one configuration that is
not a precision/recall trade is persistence 40 ms with the 60 ms floor kept
(+0.0027, 41 up / 25 down, paired t 2.5), and it is small. The reachable set
is also smaller than 1,501: 214 of the short-run cases are one or two frames,
at the trace's resolution. The candidate change is a
split threshold that scales with the local inter-onset interval — the same
"the constant does not know the tempo" finding as D11, one stage earlier —
rather than a lower constant: CLAUDE.md records that lowering
`min_note_ms`, `pitch_persist_ms` and `median_filter_ms` as constants over
six cached spans bought about two false notes per true one, and this
taxonomy says exactly which classes those false notes go into.

**At risk.** `fragment_neighbour` (585) and `split_sustain` (453): a
segmenter that splits on shorter excursions splits more held notes at
their vibrato and decay, which is precisely what the sweep saw. `too_short`
(112) is where the recovered notes go if `pitch_persist_ms` moves without
`min_note_ms`. `between_notes` (266) grows if shorter specks between
phrases survive. The guard reports all four beside `absorbed`.

### 4.2 `neighbour` — 964 (12.5%, 0.0272 of F1, 18.7% of the deficit)

**What it is.** Our note starts within 50 ms of theirs (median |dt| 12 ms)
and reads 1 or 2 semitones off: +1 in 475, −1 in 333, −2 in 84, +2 in 72.
The reference notes are again short (median 78 ms) in stepwise lines
(|step from the previous reference pitch| is 1-3 in 658 of 931), and our
note is 100 ms long at the median. CREPE's raw f0 sat at the reference
pitch in only 17% of the note's frames at the median (p75 35%); the gated
pitch held it for 1 frame at the median. Nothing about the direction
supports a lag reading: the error points toward the previous note in 463
cases and away from it in 468.

**Both readings.** In 252 of 964 (26%) our pitch equals the *next* or
*previous* reference note's pitch, so a second analyst may prefer to read
those as that adjacent note heard early or late, with this one absorbed —
the same mechanism as 4.1, filed under a different name because the
pairing chose the nearer onset. The other 712 (74%) are a genuine
wrong-pitch reading of a short note.

**What a fix would move.** The 712 genuine cases: 0.020 of F1. The
mechanism is inside the f0 decode on 60-100 ms notes — the 0.2/bin Viterbi
step cost, the 50 ms median filter, CREPE's own frame resolution — and the
cached reviews hold post-decode f0 only, so a step-cost sweep needs CREPE
while a median-filter sweep does not. A first experiment: re-segment the
cached f0 with `median_filter_ms` 30 and count what moves out of
`neighbour` and into `fragment_neighbour`.

**At risk.** `fragment_neighbour` (585, same short excursions cut loose),
`too_short` (112), and `absorbed` itself if a decode that moves faster also
tracks the comping between notes.

### 4.3 `timing_late` + `timing_early` — 657 (8.5%, 0.0204 of F1, 14.1% of the deficit)

**What it is.** Same pitch, onset outside the 50 ms tolerance but inside
150 ms. Late: median 66 ms, p75 78 ms, p90 99 ms, on notes 169 ms long at
the median. Early: median −62 ms, p25 −74 ms, on notes 118 ms long. Three
quarters of both sit within 80 ms; the class is a cliff at the tolerance,
not a tail of badly placed onsets. **167 of the 657 (25%) sit inside the
tolerance once the fit's local residual is taken out** (`align_resid`, the
median offset of the matched notes within 3 s): that quarter is the
alignment's, the rest is placement. The matched notes' own offsets have an
inter-quartile range of 21 ms and 10.3% of them sit more than 30 ms off, so
the 50 ms edge cuts through the tail of the same distribution. Late notes are the longer ones — a soft
attack whose harmonic rise `corroborate_onsets` accepts a frame or two in —
and early notes shorter.

**What a fix would move.** 0.020 of F1 if every one landed inside 50 ms;
about 0.015 for the three quarters inside 80 ms. Onset placement is
`onset_rise_db` / `onset_window_ms` and the position of the split inside a
pitch change; both are cheap sweeps over the cached reviews (frame trace
included, no CREPE).

**At risk.** `merged` (673): an onset pushed earlier lands inside the
previous note's tail and a re-articulation is lost as one note; `attack_transient`
(224) and `body_late` (186), because pulling an onset earlier onto a scoop
moves the split into the transient. `split_sustain` if the rise threshold
drops.

### 4.4 The next three, briefly

- **A held note re-attacked** (split_sustain 453, fragment_neighbour 585,
  fragment_other 194, fragment_octave 18): our note begins at 75% of the
  way through theirs at the median (p25 59-62%), 3-5 dB quieter than the
  matched notes around it, on reference notes 220-480 ms long — the decay
  and vibrato of a held note read as a new one, and `fragment_other` at
  position 1.06 is the release after note-off. **Two mechanisms** (second
  reading, 2.2): `split_sustain` sits on a corroborated onset tick in 301 of
  449 — the detector cut it — while `fragment_neighbour` does in 61 of 564
  and `body_late` in 13 of 183 — the persistence rule cut those. D2's
  finding stands for the first: the dip test that fixes it costs `merged`
  more than it saves, and D25 records the detector's 49% recall that bounds
  `merged` (33 of 646 sit on a tick, the control's rate).
- **Attack transients** (224 + 186): a 90 ms note a step *under* the
  reference (−1 in 114, −2 in 45, +1 in 38, −12 in 9) followed 105 ms later
  by the body at the right pitch. A scoop, split off. One mechanism, two
  rows, counted with both names so the guard sees them move together.
- **Extra notes outside the line** (500): 7-12 dB under the matched notes
  around them and, at the median, carrying a hundredth of the harmonic
  energy the other stems do — they are in *our* stem. `bleed_register` is
  27 and `left_stem` is 0: D22's floors and the Roformer have taken the
  bleed that a rule can see, and what remains reads as ghost notes and key
  noise, which D20 already accepts as a ceiling.

### 4.5 The pianists

`absorbed` + `squeezed` are 222 of the 4 pianists' 335 errors (148 + 74;
249 under the first pin's single class), and the polyphonic model **heard
204 of the 264 piano misses (77%)** at the exact pitch within 100 ms — 196
of the old 249, and the 22 now filed `not_picked` are the slack cases. The
line did not take them because a note of ours was already sounding there:
`corroborate.fill_gaps` fills *holes*, by design, and these are not holes.
That is D24 / issue #8 from the miss side — the recall the picker is
measured to have is sitting in the oracle's output under our own previous
note. What would move: up to 196 misses over 4 solos (0.06 of the piano
mean). At risk: the 16 false positives, which is the whole of piano
precision; a fill that splits our note at the oracle's onset must be
measured on both halves, as M7b was.

**What the pianists' frames say (249 `absorbed`).** The gated pitch
reached the reference pitch for 10-50 ms in 92 (37%) and for ≥ 60 ms in 12
(5%); raw f0 touched it in 30 more (12%); in **115 (46%) CREPE never
reached it** — it was tracking the other voice, which is the piano
problem CLAUDE.md describes (the line is not polyphony, it is voice
choice). Of those 115, the polyphonic model heard the note anyway in the
large majority (oracle_heard is true for 196 of all 249). So for a pianist
the recall is in the model's output, not in CREPE's trace, and the fix is
the picker, not the segmenter: the two families share a class name and
not a mechanism. Reference notes here are 86 ms long at the median, 122 ms
apart.

## 5. Negative results, on the record

- **Nothing leaves the stem any more.** `left_stem` fired 0 times over
  33,833 reference notes on the Roformer stems (R16 was an htdemucs
  finding); `gated` fired 3 times and `unvoiced` 5. The gates are not where
  the recall goes, which agrees with the gate sweeps CLAUDE.md records.
- **Bleed a rule can see is gone.** `bleed_register` 27 and
  `bleed_cross_stem` 102 (1.7% together); D22's floors were the last cheap
  win of that kind.
- **The octave class is 1.8%** (141; 119 of them an octave *low*), not the
  headline it is on the hand-scored pianos (D4), because
  `fold_octave_outliers` and `snap_octaves` already handle it here.
- **`not_picked` is 22** (4 at the first pin), not because the model
  rarely hears what we miss (it hears 77% of the piano misses) but because
  those misses are covered by a note of ours and `absorbed`/`squeezed` fire
  first. Both readings are in the table (`oracle_heard` on every piano
  miss).
- **Confidence does not separate the false positives.** Median
  `est_confidence` is 0.849 over the 1,936 false positives and 0.850 over
  the 2,387 pairs. CLAUDE.md's AUC 0.830 was measured on the listener's
  erasures, which are bleed; here the false positives are the line's own
  fragments and specks, and the cue does not see them.
- **The corroborated onset detector marks half of the real onsets** (D25):
  a tick within 30 ms of 13,383 of 27,067 matched reference onsets, at a
  5.2% false rate. `merged` is bounded by that recall; `split_sustain` is
  its other side.
- **The largest class is not a gate, a threshold or a stem: it is note
  length.** The shipped split thresholds (60 ms) sit at the length of 11%
  of the reference notes, and the measured "loosening the gates buys two
  false notes per true one" is what a constant does when the music's note
  length is the constant.

## 6. The regression guard, and what "noise" means here

`error_taxonomy.py` without `--pin` flattens every class count — overall,
per family, per population — and diffs it against the pinned JSON, printing
every count that moved and exiting non-zero if any did, following
`run_eval.py`'s pattern (`compare`, tested in
`tests/test_error_taxonomy_script.py`). It was run once more after the
pin, unchanged code, and reported all counts unchanged.

Classification is deterministic, so any movement after a transcriber
change is real. The question the guard also has to answer is whether a
movement is *about the transcriber* or about which solos happen to be in
the set, and for that each class carries a **bootstrap sd**: its count
over 1,000 resamples of the 73 solos with replacement (seed 0,
`taxonomy.bootstrap_noise`). A mover whose |Δ| exceeds **2 sd** is marked
`beyond 2 sd`. The threshold is chosen because 2 sd of the resample
distribution is roughly the 95% band of "this class's size if the
benchmark had been drawn differently"; a change that moves a class less
than that would not be expected to hold on another set of solos.

**The paired test (second reading).** `count_sd` answers "how big would
this class be on a different set of solos", not "did this change move it":
a fix that trimmed `absorbed` by a tenth in every solo (about 95 notes now,
246 at the first pin) would sit inside 2 sd while being many standard
errors of the per-solo mean. So the pin also carries every solo's class
counts (aggregates, so they ship), and `compare` judges each mover twice:
against `count_sd`, and against the bootstrap standard error of the sum of
per-solo deltas over the solos both runs hold (`taxonomy.paired_delta_noise`),
printing `paired: beyond 2 se` or `inside noise` with the count of solos up
and down. A class that moved in one solo only reads as inside paired noise
however far it moved; a class that moved the same way in every solo reads
as beyond it however small the total.

The scale it sets is not uniform: `absorbed`'s sd is 263 (11% of its
count) because it concentrates in a few fast solos, `neighbour`'s 98
(10%), while `dropped` (45) has sd 7 and `unvoiced` (5) sd 3. A fix that
"empties" a class of 45 by 20 is beyond noise; one that moves `absorbed` by
200 is inside it and needs the per-solo view. Families with at least four
solos get their own sd (horn, piano); the guitar's single solo does not.

## 7. The spot-check sample

`benchmark/wjazzd/error-taxonomy-spotcheck.csv`: 40 rows drawn by
`random.Random(0).sample` from all 7,707, sorted by track and time. Columns:
`solo`, `performer`, `time` (m:ss.mmm in the track's own timeline, so the
GUI's cursor lands on it), `population`, `class`, `rule`, `ref_pitch`,
`est_pitch`, `dt`, `ref_duration`, `est_duration`, `note` (the evidence the
rule read), and an empty `verdict` for the listener. The draw is random,
not chosen; a rule the listener finds wrong should be reported by class and
rule text, and re-drawing with another `--seed` gives a fresh sample.

## 8. Open questions

1. **Is `absorbed`'s 10-50 ms bucket recoverable at all?** ANSWERED by the
   second reading (`docs/error-taxonomy-review.md`, section 3): mostly not
   by a threshold. Re-segmenting the cached traces over 67 horns, every
   shorter constant trades the class for `fragment_neighbour` and
   `between_notes` about one for one; persistence 40 ms with the 60 ms
   floor kept is the one non-trade at +0.0027 mean F1. What remains open is
   a cue that separates a short excursion that is a note from one that is
   vibrato — the corroborated onset detector is not it (a tick under 19% of
   the old class).
2. **Is `neighbour` a decode problem or a CREPE resolution problem?** The
   raw f0 was at the reference pitch 17% of the time. The median-filter
   half is ANSWERED (`docs/error-taxonomy-review.md`, 3b.1): a 30 ms filter
   leaves `neighbour` at 957 against 949 and costs 0.0018 of F1 over 68
   horns. What remains is the step-cost half, which needs CREPE.
3. **The 466 `absorbed` cases where the tracker never reached the pitch**
   and the 52 `tracked_other`: are these the comping (a piano voice under
   the horn's note) or the horn itself? The cross-stem energy test only ran
   on false positives; running it on misses is a one-line change.
4. **Timing at 50 ms.** Three quarters of the timing pairs are within 80
   ms. Whether the notater cares about 30 ms is a quantize question (grid
   slack is 20 ms); the benchmark's tolerance is plan §6's and stays.
5. **The pairing's pitch preference** changes 103 pairs. Neither reading is
   wrong; the table carries both. The second analysis used the same-pitch
   reading throughout and did not re-cut the 103.
6. **Piano n = 4.** Nothing in section 4.5 should be acted on without the
   hand-scored pianos in the same instrument, which need the MuseScore
   references placed in time — a different harness, deliberately not
   touched here.

## 9. Assumptions on the record

1. **The population is `run_eval`'s.** Solos are located by
   `identify_all` with its 15% floor and 40% confident rate; the sidecar's
   own `melid` agreed with the fit's choice on every solo (the script
   prints any disagreement). No fit sat at the rate clamp (0.97/1.03); the
   lowest match rate accepted was 0.637.
2. **A pair is one error weighing two.** The F1 decomposition needs the
   weight; the Pareto counts it once.
3. **Pairing window 150 ms, same-pitch preference 50 ms.** Three times the
   match tolerance; the alternative is reported (103 pairs).
4. **"Covers" allows 50 ms after a REFERENCE note-off for a false positive
   (a release), and nothing after OUR note-off for a miss.** The first pin
   allowed the slack for misses too, on the argument that our durations
   overrun; the second reading found 496 misses sitting in it — a gap
   between two of our notes, which the frame rules describe better — and
   the rule was changed and re-pinned.
5. **Frame evidence is the review cache's, read by key.** Another session
   changed `review.cached_review` on 2026-09-07 to refuse a pianist's
   payload that lacks a candidate pool; this script reads the payload by
   its key directly and verifies the notes, so the four pianists keep
   their frame evidence. If a review is ever regenerated under a new key
   the rule that needs frames is skipped and the miss lands in
   `unclassified`, which the 10% threshold would then show.
6. **The piano model's notes are `scripts/line_selection.py`'s cache**,
   computed from the `other` stem of an earlier separation over the same
   region, not from the Roformer's `piano` stem the line was transcribed
   from. Their onsets are in track time and were checked against the
   sidecar regions. "The model heard it" is therefore evidence about the
   recording, not about this run's stem.
7. **Cross-stem harmonic energy** is an FFT over the note's first 300 ms,
   harmonics 1-4 at ±3%, in the melodic stems only (never drums). A ratio
   of 1.0 is the threshold; nothing was tuned.
8. **`bleed_register` is judged against the reference line**, not our own
   line as D22 does, because the question here is cause, not detection.
9. **WJazzD's `loud_max` is reported relative to each solo's median**, in
   the database's own units, as a column only; no rule uses it.
10. **The transcriptions are the 2026-09-02 pin's.** Any change to
    transcribe invalidates `.benchmark-notes-c0.2-d0.0.json` through its
    fingerprint, and this instrument then classifies the new notes.
