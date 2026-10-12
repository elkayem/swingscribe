# Rhythm-conditioned splits: refuted

2026-10-11. The hypothesis of `docs/error-taxonomy.md` section 4.1: the
segmenter should split a short excursion off a note when the local RHYTHM
predicts a note there, instead of by a constant threshold. Measured on the
cached frame traces of the 68 WJazzD horn solos, with no CREPE. Nothing in
the pipeline changed, no pin moved, no harness cache was written.

**Answer: no. The kill criterion fired.** Fifteen rules were scored, ten on
our own onsets (version 1) and five on the beat grid (version 2), plus two
without any rhythm test as controls. None has a paired interval above zero
or more solos up than down; the best two read −0.0000, level. The reason is in the
candidates, not in the tuning: only 21% of the short pieces the shipped
segmenter drops or swallows are missed reference notes, a note added to the
line has to be right about 43% of the time to raise F1, and no rhythm
feature, from our onsets or from the grid, reaches that. A classifier
fit out-of-fold by solo on every feature below reaches AUC 0.65 and 0.37 in
its best 400 candidates.

## 1. The evidence, measured again

From `.benchmark-taxonomy-table.csv` (2026-10-08), horns only: 6,731 errors
over 68 solos. The three short-miss classes are 1,614 (24%): `squeezed` 830,
`too_short` 535, `absorbed` 249. In 1,013 of them our pitch trace holds 3 or
more frames at the reference pitch (`run_at_ref_frames`); 1,301 are at MEDIUM
UP or UP tempo; the median gap from the previous reference onset is 102 ms
(n = 1,613) and the median reference duration 53 ms. The false-note classes a
looser split feeds: `fragment_neighbour` 648, `split_sustain` 601,
`between_notes` 271. All as the brief stated.

By class, the frames at the reference pitch: `too_short` median 4 (441 of 535
with 3 or more), `squeezed` median 3 (509 of 830), `absorbed` median 0 (63 of
249). So the population a split can reach is `too_short` and `squeezed`;
`absorbed` mostly never reached the pitch.

## 2. Method

**The control.** The shipped horn path over the review cache's trace:
`segment_notes` on the gated, smoothed pitch with the tuning correction taken
out where it applies, `fold_octave_outliers`, `reject_line_outliers` with
loudness read from the stem on disk, the Basic Pitch hole-filler
(`corroborate.fill_gaps` with the `horn_fill_*` gates; Basic Pitch run once
per solo on the whole stem and its notes cached), and `mark_lead_ins`. Every
review was present under the current key (`scripts/wjazz_reviews.py --dry`:
74 of 74). It reproduces the cached notes, lead-in marks included, **exactly
on 30 of 68 horn solos and to within one note's count on 67** (one solo is 3
off). Per-solo note F1 against the pin: within 0.001 on 63 of 68, within
0.002 on 65, at most 0.0027. Every difference traced was the payload's
storage, not the path: the review stores pitch to three decimals, and a frame
stored as exactly k.5 rounds to the even semitone where the true value
(k.4997, say) rounded down, so a pitch cut moves one frame or a sub-persistence
excursion becomes a cut. Section 3 of `docs/error-taxonomy-review.md` had the
same ceiling (33 of 67 exact). Every variant is compared with this control,
not with the pin, so the artifact is on both sides of every delta.

**The candidates.** Every short piece the shipped segmenter loses, of two
kinds, offered to the rule; the rest of the path is unchanged:

- *dropped*: a segment the shipped cuts make but the 60 ms floor removes (3-5
  frames here; the `too_short` geometry). Kept, it skips the floor.
- *excursion*: a run of 3 frames at another rounded pitch inside a kept note,
  under the 40 ms persistence (the `squeezed` geometry). Kept, it is cut out:
  to the note's end if it runs within two frames of it ("end"), else to where
  the pitch returns ("return") or moves on ("other").

There are 7,147 of them over the 68 solos (5,716 dropped, 1,431 excursions).

**Version 1, our own onsets.** For a candidate at t, with p and n the shipped
onsets either side and the local IOI the median of up to three IOIs ending at
p and three starting at n (a gap over 0.4 s ends the context, two IOIs at
least): accept when the IOI is under 0.18 s, |t − p − IOI| and |n − t − IOI|
are both within 0.25 IOI. Variants change one thing each.

**Version 2, the beat grid.** The raw tracker beats from run_eval's grid
cache (`.benchmark-grids.json`), exactly what `document.beats` holds when
transcribe runs. Accept a candidate in a beat of 0.375 s or less (160 bpm
and up) within 0.06 beat of an eighth slot (0, the offbeat at 0.5, 0.58 or
0.67, 1) where no shipped onset sits within 0.15 beat of that slot. Written
down before it was built, the three consequences of reading beats inside
transcribe:

1. They are the RAW tracker beats. The repair (`drop_doubled_beats`, the
   octave judgement from the downbeat layer, insertion of dropped beats, the
   metronome thinning, `steady_spans`) happens in `meter.bar_grid`, after
   transcribe. A stretch tracked at double rate (Blue Train, 44% of the solo)
   or half rate puts every slot in the wrong place there.
2. The Fast tune speed does not reach transcribe. `BeatsConfig.speed` 0.5 is
   applied only by the grid's readers through `notation.grid_config`; the
   pipeline's beats stage runs at 1.0, so on a tune like Oblivion transcribe
   would see one beat per bar.
3. The GUI's review key hashes the transcribe dump, the source and the stem,
   not the beats (`review.review_key`), and run_eval's fingerprint hashes the
   TranscribeConfig and CACHE_VERSION only. A transcribe that reads beats
   would be served stale whenever the grid changed under an unchanged
   transcribe config, which is exactly the staleness hole the chained keys
   exist to close (CLAUDE.md). Shipping it would mean putting the beats (or
   the beats config and its CACHE_VERSION) into both keys.

**Scoring.** Each variant's notes go through `taxonomy.classify_solo` over the
solo's span with the same evidence (frame trace, stems) for every variant:
note F1 is mir_eval's, the classes are the taxonomy's. Changes are
`evaluation.paired_change` against the control: mean delta, 95% bootstrap
interval resampled by recording, up/down by recording past 0.0005, exact sign
test. n = 68 solos, 68 recordings.

## 3. Results

Control: mean note F1 0.8647, precision 0.860, recall 0.854, 31,027 notes;
short misses (`squeezed` + `too_short` + `absorbed`) 1,614; false classes
(`fragment_neighbour` + `split_sustain` + `between_notes`) 1,523; `neighbour`
833.

| variant | accepted | Δ F1 | 95% interval | up / down | p | P | R | short | false | neighbour |
|---|---|---|---|---|---|---|---|---|---|---|
| every candidate with a context, no test (3+ frames) | 6,824 | −0.0322 | [−0.0364, −0.0278] | 2 / 66 | <0.001 | 0.767 | 0.896 | −1,195 | +3,069 | −9 |
| every candidate with a context, no test (2+ frames) | 10,601 | −0.0688 | [−0.0744, −0.0631] | 1 / 67 | <0.001 | 0.706 | 0.897 | −1,292 | +5,485 | +6 |
| **v1** (as specified) | 214 | −0.0004 | [−0.0008, −0.0000] | 13 / 24 | 0.10 | 0.858 | 0.856 | −87 | +31 | +37 |
| v1, tolerance 0.35 IOI | 399 | −0.0002 | [−0.0008, +0.0003] | 17 / 24 | 0.35 | 0.856 | 0.858 | −169 | +64 | +57 |
| v1, 2-frame pieces too | 253 | −0.0007 | [−0.0011, −0.0002] | 13 / 30 | 0.01 | 0.857 | 0.856 | −105 | +36 | +49 |
| v1, right gap up to 2 IOIs | 236 | −0.0005 | [−0.0009, −0.0001] | 13 / 25 | 0.07 | 0.858 | 0.856 | −95 | +35 | +40 |
| v1, every context IOI within 35% | 52 | −0.0000 | [−0.0003, +0.0002] | 9 / 12 | 0.66 | 0.860 | 0.854 | −18 | +6 | +10 |
| v1, IOI under 0.22 s | 218 | −0.0005 | [−0.0009, −0.0001] | 12 / 25 | 0.05 | 0.858 | 0.856 | −87 | +35 | +37 |
| v1, dropped pieces only | 166 | −0.0000 | [−0.0003, +0.0003] | 13 / 18 | 0.47 | 0.859 | 0.856 | −72 | +10 | +32 |
| v1, excursions only | 48 | −0.0004 | [−0.0007, −0.0002] | 2 / 17 | 0.001 | 0.859 | 0.854 | −18 | +20 | +6 |
| v1, "end" excursions only | 195 | −0.0001 | [−0.0005, +0.0002] | 12 / 21 | 0.16 | 0.858 | 0.856 | −84 | +14 | +38 |
| v1, the hole alone (n − p ≥ 1.25 IOI, fast) | 2,596 | −0.0059 | [−0.0078, −0.0040] | 11 / 52 | <0.001 | 0.827 | 0.877 | −703 | +955 | +23 |
| **v2** (grid, eighth slots) | 1,243 | −0.0025 | [−0.0039, −0.0011] | 10 / 29 | 0.003 | 0.845 | 0.864 | −345 | +394 | +52 |
| v2 + the hole | 929 | −0.0017 | [−0.0028, −0.0007] | 10 / 27 | 0.008 | 0.849 | 0.862 | −279 | +271 | +52 |
| v2, swung offbeat only | 880 | −0.0011 | [−0.0022, −0.0000] | 13 / 22 | 0.18 | 0.850 | 0.862 | −253 | +259 | +34 |
| v2, swung offbeat + the hole | 686 | −0.0009 | [−0.0017, −0.0000] | 13 / 22 | 0.18 | 0.853 | 0.860 | −209 | +186 | +34 |
| v2 + the hole, dropped pieces only | 763 | −0.0005 | [−0.0013, +0.0004] | 12 / 21 | 0.16 | 0.852 | 0.861 | −239 | +197 | +42 |

(`short` and `false` are changes in the class sums named above.)

**On the 48 MEDIUM UP and UP solos alone**, where the hypothesis should be
strongest, the order is the same: v1 −0.0005 [−0.0010, −0.0001], 8 / 17; v1
at 0.35 IOI −0.0002 [−0.0009, +0.0005], 12 / 17; v2 −0.0036 [−0.0055,
−0.0018], 8 / 29; the best grid variant −0.0008 [−0.0019, +0.0004], 11 / 21.

**The class test passes and F1 still does not move**, which is worth reading.
Version 1 takes 87 notes out of the short-miss classes for 31 into the false
ones, as the brief asked, but its recovered misses do not all become hits:

| | notes added | new matches | per added note | pure misses removed | became pairs |
|---|---|---|---|---|---|
| v1 | 148 | 49 | 0.33 | 103 | 54 |
| v1, tolerance 0.35 | 287 | 115 | 0.40 | 199 | 84 |
| v2 | 940 | 314 | 0.33 | 419 | 105 |
| v2 + the hole, dropped only | 543 | 217 | 0.40 | 285 | 68 |
| every candidate (3+ frames) | 5,458 | 1,304 | 0.24 | 1,483 | 179 |

An added note raises F1 only when it brings a new match more often than F1/2
of the time (dF1 ∝ ΔM − (F1/2)·ΔE): 0.43 here. Every row is under it.
Between a quarter and a half of the misses a variant removes come back as a
`neighbour` or timing pair — a note at the right moment with the wrong pitch,
or at the right pitch 50-150 ms off — which keeps the miss and adds a false
positive.

## 4. Why: what the candidates are

Every candidate of the no-test variant (3+ frames), labelled against the
control's reference notes within 50 ms of its onset (n = 6,824 with a rhythm
context):

| label | n | share |
|---|---|---|
| a reference onset at ANOTHER pitch (a real attack, the wrong pitch) | 2,437 | 0.36 |
| NEW: a reference note the control missed, at its pitch | 1,413 | 0.21 |
| a reference note the control already matched, at its pitch (a duplicate) | 1,097 | 0.16 |
| inside a sounding reference note (a fragment) | 962 | 0.14 |
| no reference sounding (between notes) | 915 | 0.13 |

Of the wrong-pitch group (2,553 counted without the context filter), 1,809
are one or two semitones from the reference note they sit on and 1,688 sit on
a reference note the control already matched: the pitch passing through a
neighbour on the way into a note our line already has. That is the largest
population, and it sits where the rhythm says a note is, because it IS at a
note's onset. A rhythm test cannot reject it; only its pitch can.

Candidates are not late: same-pitch candidates sit a median 10 ms after the
missed onset (deciles −16 to +47 ms). The generator covers 1,417 of the
control's 4,558 missed reference notes within 50 ms.

How the rhythm features sort the candidates (share NEW):

- **Local IOI**: 0.33 under 80 ms, 0.28 at 80-100, 0.25 at 100-120, 0.16-0.17
  at 140-220, 0.09 past 300 ms. Fast helps, never past a third.
- **The slot, as specified**: the right gap ≈ one IOI is NOT where the real
  notes are. 4,571 of 6,824 candidates have the next onset within half an IOI
  (the piece sits at the END of its slot, just before the next cut), and the
  NEW share peaks at right/IOI 0.5-0.9 (0.30-0.33), not at 1.0 (0.26). The
  left gap does not separate (median left/IOI 1.07 NEW against 1.04 not).
- **Both sides within 0.25 IOI, fast**: 0.32 (68 of 214).
- **The hole** (n − p) on fast runs: 0.29-0.31 at 1.25-2.25 IOIs against 0.18
  where n − p is one IOI. A missing note does leave a hole; so do the
  fragments.
- **The beat phase** at fast tempos: 0.29-0.31 on the swung offbeat (7-8
  twelfths of the beat), 0.14-0.18 at 4-5 twelfths, 0.21-0.26 elsewhere.
  Distance to the nearest eighth slot: 0.24 within 0.05 beat, 0.19-0.22
  beyond. At beats of 0.375 s or more, distance to a sixteenth slot: flat
  (0.17-0.20).

**The ceiling.** A gradient-boosted classifier (scikit-learn, scratch only),
fit out-of-fold over five folds grouped by solo, on all of these at once:

| features | AUC | NEW share in its top 100 / 400 / 1,600 | largest prefix at ≥ 0.45 |
|---|---|---|---|
| v1: IOI, both gaps, the hole, context size, kind, length | 0.649 | 0.30 / 0.37 / 0.32 | 2 |
| v1 + v2: + beat length, phase, slot distances | 0.641 | 0.45 / 0.36 / 0.32 | 102 |
| v1 + v2 + pitch steps + onset tick | 0.688 | 0.29 / 0.40 / 0.35 | 11 |
| pitch steps + onset tick, no rhythm | 0.657 | 0.42 / 0.40 / 0.33 | 68 |

No subset larger than about a hundred candidates reaches the 0.43 an added
note needs, with rhythm or without; the grid's best hundred would net a
couple of notes over 68 solos. The pitch features alone separate as well as
the rhythm ones, which is the wrong-pitch row above seen from the other side.

## 5. What this closes

The segmenter's short-note line is closed from a third direction. Sections 3,
3b, 8, 9 and 10 of `docs/error-taxonomy-review.md` measured every constant
(persistence, the floor plain and conditional, the median kernel, the onset
dip, the detectors, a 5 ms hop) and found the shipped point at the best of
each. This measured the conditional the brief proposed: the excursion's
place in the local rhythm, from our own onsets and from the beat grid. The
short pieces the shipped segmenter loses are one population in time as well
as in length. The real notes among them sit in the same slots as the
pitch transitions into the next note, the duplicates and the fragments,
because all of them are produced at note boundaries, and the boundaries are
what the rhythm describes.

Two numbers for whoever comes next:

- **The recoverable set inside the trace is small.** 1,417 of 4,558 missed
  reference notes have a candidate at their pitch within 50 ms; the 1,458
  candidates that are new come with 5,689 that are not. Whatever separates
  them has to overcome about 4:1 against, from evidence the trace and the
  onsets do not hold.
- **The largest competitor is pitch, not time.** 36% of candidates are real
  attacks at a pitch one or two semitones off, which is the `neighbour`
  mechanism. A front end that hears the pitch of a 50 ms note correctly would
  help both classes; `docs/neighbour-salience.md` (the same day, a separate
  measurement) finds that CREPE's activation does not hold the reference pitch
  as a second peak under those notes.

Nothing to implement: the brief's step 2 (a TranscribeConfig field, a test,
a harness A/B) was conditional on a variant passing, and none did.

## 6. Assumptions on the record

- The traces are the review payloads under the current key; the control is
  exact on 30 of 68 and the remainder differ by the three-decimal rounding in
  section 2. Deltas are against this control, never against the pin.
- Basic Pitch's notes were computed once per solo on the stem and reused, so
  every variant's hole-filler saw the same model output; a kept candidate can
  block a fill the control made, and that is counted in the deltas.
- "New match" in section 4 is a label against the control's matches (a missed
  reference note at the candidate's pitch within mir_eval's 50 ms); the
  end-to-end rows in section 3 are mir_eval's own matching of each variant.
- The IOI context is our shipped onsets after the floor, before
  `reject_line_outliers` and the fill. The beat grid is the harness's cached
  raw grid at speed 1.0 for all 68 solos (none has Fast tune).
- Tempo bands are WJazzD's `tempoclass`.
- The instrument (`common.py`, `rhythm.py`, `variants.py`, `report.py`,
  `features.py`, `features2.py`, `grid_features.py`, `ceiling.py`,
  `accounting.py`) is kept OUTSIDE the repo, in
  `C:\Users\lkmcg\swingscribe-research\rhythm-splits`, with the per-solo
  results and the cached Basic Pitch notes, because its tables are derived
  from commercial recordings and WJazzD; only these aggregates are here.
  `variants.py OUT.pkl --jobs 3` re-runs every rule in about two minutes
  once `solos.pkl` and `bp/` exist; `report.py OUT.pkl` prints section 3.
