# A second reading of the error taxonomy

2026-09-07. An independent analysis of `docs/error-taxonomy.md` from its raw
per-note table (`.benchmark-taxonomy-table.csv`, 7,707 rows) and from two
measurements the first analysis did not make: the alignment residual under
the timing classes, and the onset detector's ticks under every class. Both
reuse the first analysis's own loaders (`scripts/error_taxonomy.py`), so the
population, the fit and the evidence are identical; nothing here re-scores.
The pairing reading used throughout is the table's own (same-pitch partner
preferred), open question 5 of the first document.

Nothing in the transcriber was changed. Section 3 holds the one experiment
that runs the segmenter over cached frame traces; its output was scored, not
shipped.

## 1. What reproduces

Every count in the first document was recomputed from the table and agrees:
7,707 errors as 3,384 misses, 1,936 false positives and 2,387 pairs; 7,291
horn, 335 piano, 81 guitar rows; the class Pareto to the row; the piano
oracle heard 196 of the 249 piano `absorbed` misses. The pinned aggregate's
per-class F1 costs sum to 0.1451 against a mean note F1 of 0.8549 over 73;
pooled precision is 0.867 and recall 0.829 (28,062 hits over 33,833 reference
and 32,385 estimated notes). The 62 taxonomy tests pass. The bootstrap sd of
`absorbed` (263) agrees with a plain standard error of its per-solo counts
(sd 31.5 per solo, 269 for the total).

The main conclusions stand: `absorbed` is the largest class in every family
and tempo band; it is a note-length phenomenon (median reference duration
58 ms against 60 ms split thresholds); the gates and the stems are not where
the recall goes; the pianists' misses are in the polyphonic model's output.

## 2. Two measurements the first analysis did not make

### 2.1 The timing classes are not alignment residual

A worry a second analyst has to check: `timing_late` and `timing_early`
(657 pairs) could be the affine fit's residual, not the transcriber's. Ten of
the 65 solos with ten or more pairs have a per-solo median pair offset over
20 ms, and Wayne Shorter's Footprints reads 23 late against 3 early.

Measured from the MATCHED notes (the fit's own residual, which the table
does not carry): the per-solo median of `est - ref` onset is 3.5 ms at the
median across solos and 20.6 ms at the worst (Chet Baker, I Fall In Love Too
Easily); only 3 of 73 solos exceed 15 ms. Subtracting each pair's local
residual (median matched offset within ±3 s) brings **160 of 657 timing pairs
(24%) inside the 50 ms tolerance**, and the residual points the same way as
the error by more than 10 ms in 187 of 657. So about a quarter of the class
is fit, three quarters is placement, and the first document's reading (a
cliff at the tolerance on notes placed 60-70 ms off) holds for the majority.
The matched notes' own spread is what makes the cliff: their onset offsets
have an inter-quartile range of 21 ms and **10.3% of hits sit more than 30 ms
off** (2,902 of 28,062), so the 50 ms edge cuts through the tail of the
same distribution.

One detail worth keeping: for the timing pairs a corroborated onset tick lies
within 30 ms of OUR onset in 262 of 657 and of THEIR onset in 95. The
detector agrees with where the segmenter put the note, not with where the
annotator did. For `timing_early` that is 6 of 284 at the annotated onset:
the pitch trace arrives before the perceived attack, which is what a slurred
entry sounds like, and the segmenter cuts where the pitch changes.

### 2.2 What the onset detector saw under each class

`FrameDiagnostics.onsets` holds the corroborated onset ticks — the ones
`segment_notes` may cut on. Two calibration numbers first, over the 72 solos
with a trace:

| | hits | n | rate |
|---|---|---|---|
| tick within 30 ms of a MATCHED reference onset (ceiling) | 13,383 | 27,067 | 0.494 |
| tick within 30 ms of a point 75% through a matched note ≥ 300 ms (false rate) | 105 | 2,001 | 0.052 |

**The corroborated onset detector marks half of the real onsets.** That is a
fact about the stage worth its own deficiency entry: at 2.5 ticks per second
it is not noisy, it is quiet. Against that ceiling, the tick rate per class
(horns):

| class | tick at the onset | rate | reading |
|---|---|---|---|
| split_sustain | 301 / 449 | 0.670 | **above the ceiling**: these are cuts the detector MADE |
| too_short | 57 / 107 | 0.533 | attacked notes, dropped for length |
| dropped | 22 / 44 | 0.500 | attacked notes, never emitted |
| neighbour | 398 / 914 | 0.435 | attacked notes, pitch misread |
| between_notes / between_phrases | 87 / 246, 40 / 102 | 0.35, 0.39 | real attacks in the gaps |
| timing_late | 87 / 325 | 0.268 | |
| absorbed | 404 / 2,124 | 0.190 | |
| fragment_other | 33 / 182 | 0.181 | |
| fragment_neighbour | 61 / 564 | 0.108 | pitch-change cuts, not onset cuts |
| body_late | 13 / 183 | 0.071 | pitch-change cuts |
| merged | 33 / 646 | 0.051 | **at the false rate**: no attack was detected |
| timing_early | 6 / 284 | 0.021 | |

Two things follow.

**`split_sustain` and `fragment_neighbour` are different mechanisms and the
first document groups them as one** ("a held note re-attacked", 1,250 rows).
Two thirds of split_sustain cuts sit on a corroborated tick: the detector
found an attack inside a note the annotator wrote as one, so the fix is in
`corroborate_onsets` (the dip test, D2) or in the annotation convention, and
it competes with `merged`. Nine tenths of fragment_neighbour cuts sit on NO
tick: they are `_pitch_change_points` firing on a 60 ms excursion during
vibrato or decay, and the fix is in the persistence rule, where it competes
with `absorbed`. Reporting them under one mechanism hides that a fix for one
is a risk for the other.

**`merged` is invisible to the detector.** 673 re-articulations at the same
pitch with a tick under 5% of them, the control's rate. The segmenter can
split a same-pitch repeat only on an onset tick, so this class is bounded by
the detector's recall, not by any threshold; the ceiling row says the
detector misses half of all onsets, and these are the half.

### 2.3 The geometry of `absorbed`

The first document describes absorbed as "one note of ours running straight
through the next one or two of theirs". The table's own columns give the
missed onset's position in the covering note: 119 ms in at the median, into
a coverer 170 ms long, so the coverer has **44 ms left after the missed onset
at the median (p25 6 ms, p75 78 ms)**. Split by that remainder (2,461):

| where the missed onset falls | n | share |
|---|---|---|
| AFTER our note-off, in the 50 ms cover slack | 496 | 20.2% |
| 0-30 ms before our note-off | 469 | 19.1% |
| 30-60 ms before it | 548 | 22.3% |
| 60 ms or more before it (run through) | 948 | 38.5% |

So in a fifth of the class our note had already ended when the missed note
began, and in three fifths the missed note sits under the last 60 ms of ours
or just past it. The picture is less "tracked through" than "no boundary of
its own": a 53-67 ms note between two notes we matched, whose neighbours' onsets
set our boundaries. The reference duration is 53 ms in the first three rows
and 67 ms in the last. The 496 in the slack are misses the frame rules were
written for (too_short, dropped, tracked_*) and never reached, because the
cover rule fires first; `merged` has the same slack in 42 of 673.

This does not change the mechanism the document names (under-segmentation of
notes at the split threshold), but it changes what a fix has to do: for
1,513 of the 2,461 a later note-off or a split inside the last 60 ms is the
requirement, not a cut in the middle of a long note.

## 3. Open question 1, measured: re-segmenting the cached traces

The first document's open question 1 asks whether `absorbed`'s short-run
bucket is recoverable at all, and names the experiment: re-segment the cached
frame traces with other split thresholds and score the result through the
taxonomy. That is done here for the horns, with no CREPE: `segment_notes`,
`fold_octave_outliers` and `reject_line_outliers` (with the loudness read
from the stem on disk) are run over the review cache's gated, smoothed pitch
and corroborated onsets, exactly the inputs the stage gives them.

**Control.** The shipped settings (60 ms persistence, 60 ms minimum note)
through this path reproduce the cached notes exactly on 33 of 67 horns and
within ONE note on the other 34; per-solo note F1 is within 0.0031 of the
pinned value everywhere and within 0.001 on 64 of 67. Giant Steps (Coltrane)
has no review payload matching its cached notes and is out of this
measurement; n is 67. Classification here uses frame evidence only, for
every configuration alike (section 6).

| configuration (persist / min note) | mean F1 | Δ vs shipped | solos up / down | paired t | P | R | absorbed | merged | neighbour | too_short | fragment_nb | split_sustain | between_notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A shipped 60 / 60 | 0.8514 | | | | 0.857 | 0.825 | 2,122 | 646 | 913 | 107 | 598 | 449 | 277 |
| B 40 / 60 | 0.8541 | +0.0027 | 41 / 25 | +2.5 | 0.858 | 0.833 | 1,975 | 503 | 793 | 234 | 641 | 568 | 275 |
| C 50 / 50 | 0.8549 | +0.0035 | 35 / 32 | +2.0 | 0.836 | 0.855 | 1,370 | 531 | 872 | 67 | 990 | 594 | 464 |
| D 40 / 40 | 0.8470 | −0.0044 | 25 / 42 | | 0.802 | 0.880 | 769 | 429 | 861 | 19 | 1,637 | 804 | 840 |
| E 30 / 30 | 0.8241 | −0.0272 | 9 / 58 | | 0.753 | 0.894 | 442 | 379 | 789 | 10 | 2,611 | 1,138 | 1,423 |
| F tempo: 0.8 × sixteenth, clamped 30-60 | 0.8532 | +0.0018 | 16 / 6 | +2.2 | 0.849 | 0.838 | 1,791 | 577 | 919 | 97 | 746 | 499 | 352 |
| G tempo: 0.6 × sixteenth, clamped 30-60 | 0.8509 | −0.0005 | 14 / 18 | | 0.832 | 0.849 | 1,510 | 520 | 898 | 96 | 1,047 | 593 | 512 |

(F and G bite on 24 solos, those over about 207 bpm; the rest keep 60 ms.)

**What it says.**

- **`absorbed` is reducible and F1 barely moves.** At 50/50 the class falls
  by 752 (35%) in 66 of 67 solos, and recall rises 0.825 → 0.855 — but
  `fragment_neighbour` rises 392, `between_notes` 187, `split_sustain` 145,
  and precision falls 0.857 → 0.836. Mean F1 +0.0035 with 35 solos up and
  32 down is not a result. At 40/40 and 30/30 the trade runs the wrong way.
  This is CLAUDE.md's "two false notes per true one", now with the classes
  the false notes go into named: they are the same short excursions, cut
  loose instead of swallowed. **A threshold cannot separate the two
  populations because they are one population** — the 3-5-frame excursion
  during a held note and the 3-5-frame excursion that is a note look alike
  to the persistence rule. The discriminating cue has to be something
  else, and section 2.2 says the corroborated onset detector is not it
  (a tick under 19% of absorbed).
- **Persistence and the minimum note are not the same knob.** B moves the
  persistence to 40 ms and leaves the floor at 60: +0.0027 mean F1, 41 up
  against 25 down, paired t 2.5, precision unchanged. `merged` (−143) and
  `neighbour` (−120) fall along with `absorbed` (−147): a shorter
  persistence moves the SPLIT earlier, so the following note's onset lands
  inside tolerance, while the floor still drops the loose specks
  (`too_short` +127 is misses changing class, not new false notes). Its
  cost is `split_sustain` +119. It is the one configuration in this table
  that is not a precision/recall trade, and it is small.
- **Tempo scaling helps where it bites and is not worth more than that.**
  F improves 16 of the 24 fast solos and hurts 6, +0.0055 at the median
  among them, +0.0018 on the mean of 67; G, scaled harder, loses it again.
  The same reading as D11 one stage earlier: the constant does not know
  the tempo, but knowing the tempo buys a few thousandths.
- **The realistic ceiling is far below the document's 0.021.** 1,501
  recoverable misses were named; the best configuration here recovers a
  net 0.0035 of F1 over the horns, and half of that is not paired-robust.
  Under-segmentation stays the largest class; it is not the cheapest.

## 3b. The next experiments, measured (later the same day)

Section 5 named three experiments. All three were run from the caches, no
CREPE, after the instrument changes in section 4 landed; every configuration
is classified with frame evidence only, against the re-pinned classes.

### 3b.1 The segmenter's other knobs (68 horns)

The same re-segmentation path as section 3, now with the median filter
re-applied to the gated raw f0 the cache holds, and the onset corroboration
recomputed from the stem (raw spectral flux and harmonic energy exactly as
`analyze` does). Control: the recomputed corroborated onset set equals the
cached one on 63 of 68 solos, the notes on 27 (the rest differ by a note or
by sub-2 ms onsets), and the control's mean F1 is 0.8522 against the pinned
horn 0.8521. Corroboration keeps 16,850 of 29,699 raw ticks.

| configuration | mean F1 | Δ | se | up / down | P | R | absorbed | squeezed | merged | neighbour | too_short | fragment_nb | split_sustain | between_notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A control (60 / 60, median 50, dip 0) | 0.8522 | | | | 0.860 | 0.827 | 798 | 932 | 616 | 949 | 339 | 604 | 452 | 280 |
| B persistence 40, floor 60 | 0.8549 | +0.0028 | 0.0011 | 42 / 25 | 0.861 | 0.835 | 252 | 1,010 | 465 | 820 | 778 | 645 | 576 | 278 |
| H median filter 30 | 0.8504 | −0.0018 | 0.0005 | 14 / 41 | 0.860 | 0.824 | 867 | 938 | 624 | 957 | 331 | 575 | 458 | 272 |
| I median 30 + persistence 40 | 0.8542 | +0.0020 | 0.0012 | 39 / 29 | 0.861 | 0.833 | 268 | 1,019 | 473 | 812 | 768 | 629 | 579 | 271 |
| J onset dip 3 dB | 0.8459 | −0.0063 | 0.0011 | 18 / 48 | 0.863 | 0.813 | 830 | 920 | 1,085 | 934 | 330 | 593 | 307 | 255 |
| K onset dip 6 dB | 0.8424 | −0.0097 | 0.0014 | 14 / 52 | 0.863 | 0.806 | 840 | 917 | 1,290 | 926 | 331 | 588 | 285 | 252 |
| L persistence 40 + dip 3 | 0.8488 | −0.0034 | 0.0017 | 28 / 40 | 0.863 | 0.821 | 271 | 1,003 | 918 | 807 | 769 | 635 | 445 | 253 |

- **Persistence 40 with the floor kept holds up on a second, independent
  path**: +0.0028 (paired t 2.5), 42 solos up against 25. `absorbed` proper
  falls from 798 to 252 — the run-through IS the persistence rule — while
  `squeezed` barely moves (932 → 1,010): a note with no room is not helped
  by splitting sooner. `too_short` more than doubles (339 → 778) because
  the freed excursions are shorter than the floor and are dropped, which is
  misses changing class, not false notes; `split_sustain` +124 is the cost.
- **The 30 ms median filter is refuted** as a fix for `neighbour`: 949 →
  957, mean F1 −0.0018, 14 solos up and 41 down. Section 4.2 of the first
  document proposed it; it should not be tried again.
- **The onset dip test is refuted in taxonomy terms, three to one.** Dip 3 dB
  saves 145 `split_sustain` and costs 469 `merged`; dip 6 dB saves 167 and
  costs 674. Recall falls 0.827 → 0.813. D2 said this about one held note in
  All The Things; this says it over 68 solos. The two classes are the two
  sides of one threshold, and the threshold is on the right side.

### 3b.2 The pianists through the line picker (n = 4)

`line_selection.pick_line` over the cached piano-model output, scored and
classified like the shipped line:

| solo | shipped line F1 | picker F1 | picker, matched median dt | picker shifted by its median |
|---|---|---|---|---|
| Hancock, Dolores | 0.9301 | 0.9319 | −21 ms | 0.9468 |
| Hancock, Gingerbread Boy | 0.9139 | 0.9087 | −16 ms | 0.9321 |
| Hancock, Orbits | 0.9412 | 0.8654 | −24 ms | 0.9234 |
| Garland, Oleo | 0.7942 | 0.7332 | −23 ms | 0.8098 |
| mean | 0.8948 | 0.8598 | | 0.9030 |

As it stands the picker LOSES to the shipped line on WJazzD (0.860 against
0.895) — and the classes say why: `timing_early` 12 → 100, `absorbed` +
`squeezed` 222 → 27. The picker has the notes; **the piano model's onsets
lead the annotator's by 16-24 ms on every solo** (IQR 15-23 ms), against
−9 to 0 ms for CREPE's line, and a 50 ms tolerance turns that lead into a
hundred timing errors. `docs/issue8-line-selection.md` measured the picker
with a time-free pitch alignment, which cannot see this. A CONSTANT
correction, not fitted per solo:

| shift added to the picker's onsets | 0 | +10 ms | +15 ms | +20 ms | +25 ms | +30 ms |
|---|---|---|---|---|---|---|
| mean F1 (4) | 0.8598 | 0.8863 | 0.8966 | 0.9002 | 0.9049 | 0.9032 |
| solos above the shipped line | 1 | 2 | 2 | 3 | 3 | 3 |

At +20 to +30 ms the picker beats the shipped line's 0.8948 on the mean and
on three of the four solos (Orbits stays under, 0.923 against 0.941). Four
solos of fast trio piano; but the lead is the same sign and size on all
four, and it is a property of the model's onset regression, so it will hold
wherever the picker is used. The shipped default path also inherits it:
`corroborate.fill_gaps` copies oracle notes with their onsets into the line.

## 4. Where the first analysis should change — applied

Every item below was applied the same day; the classifier, the script, the
tests (71) and `tests/regression/taxonomy-baseline.json` were re-pinned.
**The baseline moved by redefinition, not by any change to the
transcriber**: mean F1 0.8549, 7,707 errors and the 0.1451 deficit are
unchanged; the old `absorbed` 2,461 is now `absorbed` 948 + `squeezed`
1,018, and its 496 slack cases (plus 42 of `merged`'s) went to the frame
classes (`too_short` 112 → 345, `tracked_other` 52 → 189, `dropped` 45 →
160, `not_picked` 4 → 22, `dropped_register` 26 → 43, `tracked_octave` 3 →
17, `unvoiced` 5 → 8). `docs/error-taxonomy.md` carries the re-pinned
tables. D25 records the onset detector's recall.

1. **Split the "held note re-attacked" mechanism** into onset-cut
   (`split_sustain`, 67% on a tick) and pitch-cut (`fragment_*`, ≤ 18%)
   rows in section 3's mechanism table, with the different fix and the
   different class at risk for each (2.2).
2. **Sub-split `absorbed`** by the coverer's remainder, or at least report
   the split: `absorbed` proper (≥ 60 ms of our note after the missed
   onset, 948) and a boundary class (the rest, 1,513, of which 496 are in
   the slack after our note-off and belong with the frame rules). The
   `covering_dpitch`/`covered_by_duration` columns already carry it; the
   table needs the coverer's onset as well.
3. **Add the timing residual to the timing rows.** Carry `matched_resid`
   (local median offset of matched notes) in the table and report the
   fraction of timing pairs that the residual explains (24%) beside the
   class; the guard should see it move if the fit changes.
4. **Record the onset detector's recall** (49% of matched reference onsets,
   5% false rate) as a deficiency entry. It bounds `merged` (673) directly
   and shapes `split_sustain`; no existing D-entry states it.
5. **The regression guard's noise scale is the wrong test.** `count_sd` is
   the spread of a class across resamples of the SOLOS: it says how big the
   class would be on a different benchmark, not whether a change moved it.
   A fix that removed 10% of `absorbed` in every solo (246 notes) would be
   marked inside noise (2 sd = 526), while as a paired change it is about
   six standard errors of the per-solo mean. Pin per-solo class counts
   (aggregate numbers, not note lists, so they can ship) and judge a mover
   by a paired bootstrap of the per-solo deltas, or by the count of solos
   that moved each way. Keep `count_sd` for what it measures: the sample.
6. **Confidence does not separate false positives here.** Median
   `est_confidence` is 0.849 for the 1,936 false positives and 0.850 for
   the 2,387 pairs. CLAUDE.md's AUC 0.830 was measured on the listener's
   erasures, which are bleed; on WJazzD the false positives are the line's
   own fragments and specks, and the confidence cue does not see them.
   Worth one sentence in section 5 so nobody proposes it.
7. **Say which `absorbed` bucket a horn fix targets.** The 3-5-frame runs
   are 1,104 of the 1,362 "10-50 ms" cases; the 1-2-frame runs (214) are
   at the frame resolution and not recoverable by a threshold. The
   document's 1,501 target overstates the reachable set by about 200.

## 5. What the measurements leave to decide

The three experiments named here at first writing are done (3b). Two
changes to the transcriber are now measured well enough to ship, and both
carry the same cost: any change to `transcribe`'s behaviour re-fingerprints
`run_eval`'s note cache and re-runs CREPE over every solo it touches (hours
on this machine, CLAUDE.md). Neither has been shipped; that is the
listener's call.

1. **`pitch_persist_ms` 60 → 40, `min_note_ms` kept at 60.** Horns +0.0027
   to +0.0028 mean note F1 on two independent re-segmentation paths (41-42
   solos up, 25 down, paired t 2.5), precision unchanged. Cost:
   `split_sustain` +119 to +124 and a `too_short` class that doubles (misses
   renamed, not new errors). Not measured on the pianists or on the
   MuseScore notation scores, which a re-pin would show. Small, real, cheap
   to write — a one-line default with the CACHE_VERSION bump — and
   expensive to re-measure.
2. **A constant +20 to +25 ms on the piano model's onsets.** The model leads
   WJazzD's annotators by 16-24 ms on all four pianists. Applied in
   `line_selection.pick_line` alone it costs nothing in the harness (the
   oracle take is not what `run_eval` caches) and lifts the picker from
   0.860 to 0.900-0.905 on the four, above the shipped line's 0.895 on
   three of them; applied where the default path copies oracle notes
   (`corroborate.fill_gaps`) it touches the default pianist output and
   re-transcribes. The hand-scored pianos in the MuseScore set are the
   control that n = 4 needs, and their measure is time-free, so the
   correction has to be judged on WJazzD.
3. **Do not try again**: a 30 ms median filter (`neighbour` unmoved, F1
   −0.0018) and the onset dip test at 3 or 6 dB (three `merged` for every
   `split_sustain` saved).
4. **Still open**: a cue that separates a 30-50 ms pitch excursion that is a
   note from one that is vibrato — the largest class needs it and no
   threshold supplies it; and whether the raw spectral-flux set holds the
   half of the onsets the corroborated one misses (D25).
5. Nothing on the timing classes until the notater needs it: three quarters
   are placement, but at 60-70 ms on a 50 ms tolerance the benchmark is
   measuring the tail of a 21 ms IQR, and quantize's grid slack is 20 ms.

## 6. Assumptions on the record

- The pairing is the table's (same-pitch preferred). The 103 alternative
  pairs were not re-cut here.
- The onset ticks are the CORROBORATED set (`FrameDiagnostics.onsets`), the
  only one the cache holds. The raw spectral-flux set is not available
  without re-running the stage.
- "Within 30 ms" for a tick is a choice; the ceiling and false-rate rows
  use the same window, so the per-class rates are comparable to them.
- The re-segmentation (section 3) classifies with frame evidence only, for
  every configuration alike, so `bleed_cross_stem` folds into the fragment
  and between classes there; the shipped configuration is run through the
  same path and reproduces the cached notes to within one note per solo,
  which is the control. Its n is 67 horns, not 68: Giant Steps has no
  review payload matching its cached notes.
- The sweep varies the two segmenter thresholds only. `median_filter_ms`,
  `silence_gap_ms` and the onset corroboration were held at their shipped
  values; the tempo used for F and G is WJazzD's `avgtempo` for the solo.
