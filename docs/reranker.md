# A6: a learned per-beat re-ranker, trained on synthetic performances

2026-09-30. `swingscribe/reranker.py` (the model and its features),
`stages/quantize.py` (one opt-in hook in `choose_reading`),
`QuantizeConfig.reranker` (default `""`, off, dumps nothing),
`scripts/reranker_data.py` (performance model and training data),
`scripts/reranker_train.py`, `scripts/reranker_eval.py`,
`tests/test_reranker.py`. No audio: the WJazzD database, the pages under
`benchmark/`, and SNAPSHOTS of the harness's note and grid caches
(byte-identical to the caches at HEAD 4e96179 when copied). docs/roadmap.md
A6.

The page's remaining distance is writing, not hearing (docs/triples.md: 82%
of the rhythm distance survives perfect onsets), and every hand rule tried
since R33 is level or worse on the pages (docs/writing-round2.md). A6 asks
whether a LEARNED reading does better: a model that picks, beat by beat,
among the readings `choose_grid` already enumerates. Pairs of (performed
onsets, human page) are what the project lacks -- the eight triples are the
evaluation -- so it is trained on human pages PLAYED by a performance model
fitted to WJazzD.

**The answer is no, and the reason is not the model.** Fourteen models were
trained (three performance models, four training targets, two candidate
sets), twelve were judged on the pages, and none is recommended:

- **Offered only what the rule may write ("gated")**, no model moves the
  pages reliably. There is almost nothing to choose: an ORACLE that knows
  the page and picks the reading writing it wherever one is offered moves
  the triples' (a) rhythm by +0.0023 [+0.0000, +0.0046], 3/0, not decided.
  Of six gated models, four are level everywhere, one is decided down on
  the hand scores' value (-0.0020, 0/4), and one was decided up on the
  Omnibook (+0.0012 [+0.0001, +0.0026], 4/1, sign test p = 0.38) -- the
  tenth model judged, which did not replicate on an independent rendering
  (+0.0004 [-0.0006, +0.0015], 3/2).
- **Offered every reading the note-keeping guards allow ("open")**, every
  model is decided DOWN on the Omnibook (rhythm -0.0036 to -0.0191, 0-4 of
  22 pages up), all six judged. The ceiling there is real (the oracle:
  +0.0142 [+0.0066, +0.0238], 7/0 on (a)) and the models do find some of it
  (15 beats fixed against 3 broken on (a)'s labelled beats), but they also
  trade one WRONG reading for another on beats no offered reading writes
  right (50 of 68 moves, 49 of them unreachable), and those trades are what
  cost the page: against the same hook deferring, the model reads -0.0120
  on (a), +0.0019 with the trades refused, and +0.0046 with only its fixes
  kept.
- Training only to move toward a reading that writes the page (`stay`)
  removes most of the trades, and with them most of the gain: level on (a),
  still decided down on the Omnibook (-0.0036, 3/13; replicated at -0.0038,
  4/13).

The ceiling is the finding. On (a) -- human onsets on human beats -- the
rule writes 59.7% of the 1,019 beats where an open model would be asked
exactly as the page does, and only 3.3% more are writable by ANY of the
readings it enumerates (0.9% by readings its own gates admit). The rest of the distance
is outside the candidate set: notes only one side has (16.1%), beats no
reading reaches (9.8%), notes the page writes in another beat (5.6%), and
beats a per-beat lag shift would reach (5.1%). A re-ranker cannot touch
those. The hook, the model and the scripts stay, off, for the day paired
human data exists; no weights ship.

## The criterion and the sets

As docs/writing-round2.md: RECOMMENDED only if decided up on the pages (the
hand scores or the Omnibook, 95% interval excluding zero), not decided down
on any set, and dropping no note. Each model is switched on by environment
override (`SWINGSCRIBE_QUANTIZE__RERANKER=<weights.json>`, which every
`Config` the stages build reads and every worker inherits) against the
shipped defaults in the same run, through each instrument's own code:

1. **The triples** (scripts/triples.py builders, the eight trusted): (a)
   WJazzD's human onsets on WJazzD's human beats -- the quantizer alone --
   and (c) our notes on our grid.
2. **The pages**: the twelve hand scores (paired by recording) and the 22
   located Omnibook sides, through run_eval's own notation path.
3. **The beat-signature accuracy** (scripts/beat_signature.py, the Rhythm
   Perceiver's per-beat measure, docs/beat-signature.md) on the triples' (a)
   and (c) rows, the hand scores and the Omnibook.
4. **Collateral**: scripts/wjazz_quantize.py's dropped notes over 452 WJazzD
   solos (4,203 dropped of 198,983 at baseline). D36: it judges nothing else.

And three views of (a) no page score has (`reranker_eval.py --sets`):
`beats` scores each beat where the quantizer had a choice as the training
data is scored (does the written reading put every note where the page
does); `oracle` is the page-level ceiling of any per-beat re-ranker; `split`
says which of a model's moves its page-level change comes from.

Cells are the mean change [95% interval] and recordings up/down (level
within 0.002); `*` and bold mark a decided change. `edit_cost` is edits per
100 reference notes, so UP is worse.

## Summary

| model | (a) rhythm | (a) on the bar | (c) rhythm | hand rhythm | hand value | Omnibook rhythm | Omnibook value | Omnibook edit cost | notes written, hand / Omnibook | Flex-Q dropped |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 open | -0.0118, 3/5 | **-0.0101 [-0.0138, -0.0060]\*, 0/6** | **-0.0167 [-0.0328, -0.0007]\*, 2/6** | -0.0057, 5/6 | +0.0000, 6/5 | **-0.0191 [-0.0245, -0.0140]\*, 0/21** | **-0.0090 [-0.0134, -0.0049]\*, 2/15** | **+1.9124 [+1.3494, +2.5170]\*, 21/1** | +4 / +19 | -345 |
| v1 gated | +0.0002, 1/1 | -0.0007, 0/1 | +0.0018, 3/3 | +0.0002, 1/0 | +0.0009, 3/1 | +0.0017, 6/4 | +0.0010, 5/4 | -0.1901, 5/8 | 0 / 0 | 0 |
| v2 open | **-0.0225 [-0.0350, -0.0098]\*, 1/7** | **-0.0121 [-0.0176, -0.0070]\*, 0/7** | **-0.0144 [-0.0289, -0.0011]\*, 2/6** | -0.0055, 5/6 | -0.0066, 4/7 | **-0.0145 [-0.0206, -0.0088]\*, 3/17** | **-0.0123 [-0.0175, -0.0073]\*, 2/16** | **+1.9220 [+1.2303, +2.6723]\*, 17/1** | +4 / +19 | -345 |
| v2 gated | +0.0000, 1/2 | +0.0001, 2/2 | +0.0035, 3/1 | -0.0022, 1/3 | **-0.0020 [-0.0044, -0.0003]\*, 0/4** | +0.0002, 7/5 | -0.0006, 3/7 | -0.0619, 6/8 | 0 / 0 | 0 |
| v3 open, exact | **-0.0141 [-0.0250, -0.0030]\*, 2/6** | **-0.0107 [-0.0149, -0.0063]\*, 0/7** | **-0.0147 [-0.0303, -0.0007]\*, 2/6** | -0.0052, 4/6 | -0.0035, 4/6 | **-0.0138 [-0.0185, -0.0092]\*, 2/19** | **-0.0112 [-0.0152, -0.0072]\*, 2/17** | **+1.8113 [+1.2027, +2.4604]\*, 18/2** | +4 / +19 | -345 |
| v3 gated, exact | +0.0006, 1/1 | +0.0007, 1/0 | +0.0022, 2/1 | -0.0047, 1/2 | -0.0033, 1/2 | +0.0004, 7/5 | -0.0001, 2/5 | -0.0587, 5/6 | 0 / 0 | 0 |
| v3 open, hits | -0.0097, 2/6 | **-0.0068 [-0.0121, -0.0016]\*, 1/4** | -0.0109, 2/5 | -0.0053, 4/6 | -0.0051, 3/6 | **-0.0102 [-0.0139, -0.0065]\*, 2/18** | **-0.0094 [-0.0128, -0.0060]\*, 2/16** | **+1.4438 [+0.8843, +2.0221]\*, 17/2** | +4 / +19 | -345 |
| v3 gated, hits | +0.0009, 1/0 | +0.0009, 1/0 | +0.0028, 3/1 | -0.0074, 1/3 | -0.0050, 0/3 | -0.0001, 5/6 | -0.0007, 3/8 | +0.0150, 8/5 | 0 / 0 | 0 |
| v3 open, stay | -0.0035, 2/4 | -0.0017, 2/4 | -0.0066, 2/4 | -0.0003, 2/3 | +0.0010, 4/3 | **-0.0036 [-0.0063, -0.0009]\*, 3/13** | -0.0019, 4/10 | **+0.6035 [+0.2243, +1.0178]\*, 14/3** | +4 / +19 | -345 |
| v3 gated, stay | +0.0009, 1/0 | +0.0005, 1/0 | **+0.0034 [+0.0004, +0.0083]\*, 3/0** | -0.0012, 1/1 | -0.0009, 0/1 | **+0.0012 [+0.0001, +0.0026]\*, 4/1** | +0.0006, 2/0 | **-0.1303 [-0.2978, -0.0123]\*, 0/4** | 0 / 0 | 0 |
| v3 open, stay, seed 1 | -0.0052, 2/4 | -0.0002, 2/3 | -0.0076, 2/5 | -0.0012, 2/5 | +0.0000, 4/5 | **-0.0038 [-0.0064, -0.0014]\*, 4/13** | **-0.0022 [-0.0045, -0.0000]\*, 3/10** | **+0.6445 [+0.3049, +1.0245]\*, 16/2** | +4 / +19 | -345 |
| v3 gated, stay, seed 1 | +0.0013, 2/0 | +0.0005, 1/0 | +0.0030, 2/0 | +0.0003, 1/0 | +0.0002, 0/0 | +0.0004, 3/2 | -0.0000, 2/2 | -0.0489, 1/4 | 0 / 0 | 0 |
| open, always defers | -0.0021, 0/2 | **+0.0006 [+0.0000, +0.0015]\*, 1/0** | -0.0034, 1/4 | -0.0001, 1/2 | +0.0002, 1/2 | -0.0008, 3/6 | +0.0005, 4/4 | **+0.2812 [+0.1108, +0.4855]\*, 9/0** | +4 / +19 | -345 |
| gated, always defers | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 |

`v1`-`v3` are the performance models (below); `exact`, `hits`, `stay` the
training targets (v1 and v2 trained to `exact`; `dist` was read per beat
only); "always defers" is a model with no weights, the ablation that
separates the hook from the learning. The (a) and (c) rows wrote +5 and
+8 notes under every open model, the hand scores +4 and the Omnibook +19
(the notes the rule merges, kept; see "Where the open models' loss comes
from"), and nothing dropped a note anywhere.

| model | beat signature (a) | (c) | hand | Omnibook | on the bar, hand | Omnibook | hand edit cost |
|---|---|---|---|---|---|---|---|
| v1 open | +0.0074, 5/2 | +0.0014, 3/4 | +0.0026, 6/3 | **-0.0041 [-0.0079, -0.0003]\*, 7/13** | -0.0035, 2/5 | **-0.0133 [-0.0180, -0.0080]\*, 3/19** | +0.4061, 5/7 |
| v1 gated | -0.0023, 1/1 | -0.0018, 0/2 | +0.0020, 3/0 | +0.0002, 4/1 | -0.0004, 0/1 | +0.0007, 7/2 | -0.1603, 1/4 |
| v2 open | +0.0001, 2/2 | -0.0006, 3/3 | +0.0035, 5/3 | +0.0014, 10/7 | -0.0006, 4/5 | **-0.0091 [-0.0128, -0.0054]\*, 2/19** | +1.0354, 7/5 |
| v2 gated | **-0.0067 [-0.0122, -0.0026]\*, 0/6** | -0.0004, 1/1 | -0.0007, 1/2 | -0.0008, 2/5 | +0.0012, 3/0 | +0.0004, 5/3 | +0.1542, 3/2 |
| v3 open, exact | **+0.0098 [+0.0026, +0.0170]\*, 6/1** | +0.0030, 4/3 | +0.0040, 6/3 | **+0.0030 [+0.0000, +0.0062]\*, 11/6** | -0.0016, 3/6 | **-0.0093 [-0.0132, -0.0053]\*, 3/18** | +0.6440, 6/5 |
| v3 gated, exact | -0.0032, 0/2 | -0.0004, 1/1 | -0.0043, 1/3 | -0.0002, 2/3 | +0.0011, 2/0 | +0.0002, 5/3 | +0.3888, 2/2 |
| v3 open, hits | **+0.0067 [+0.0017, +0.0114]\*, 6/1** | -0.0001, 2/3 | +0.0010, 5/3 | +0.0012, 8/5 | -0.0005, 3/5 | **-0.0073 [-0.0105, -0.0040]\*, 2/16** | +0.7525, 6/3 |
| v3 gated, hits | -0.0012, 0/2 | -0.0004, 1/1 | -0.0069, 1/4 | -0.0004, 2/4 | +0.0009, 2/1 | +0.0001, 5/3 | +0.6425, 3/1 |
| v3 open, stay | **+0.0056 [+0.0015, +0.0101]\*, 5/0** | +0.0022, 4/3 | +0.0025, 4/1 | +0.0012, 9/5 | +0.0008, 3/2 | -0.0017, 3/8 | +0.0777, 4/3 |
| v3 gated, stay | +0.0000, 0/0 | +0.0006, 1/0 | -0.0013, 1/2 | +0.0001, 2/1 | +0.0004, 1/0 | -0.0000, 1/1 | +0.1312, 1/1 |
| v3 open, stay, seed 1 | **+0.0046 [+0.0015, +0.0083]\*, 5/0** | +0.0013, 3/3 | +0.0020, 4/2 | +0.0023, 12/5 | +0.0012, 3/1 | -0.0020, 4/10 | +0.1187, 5/4 |
| v3 gated, stay, seed 1 | -0.0003, 0/1 | +0.0006, 1/0 | -0.0000, 1/1 | +0.0001, 2/1 | +0.0004, 1/0 | -0.0001, 2/2 | -0.0260, 0/1 |
| open, always defers | -0.0017, 0/2 | -0.0013, 1/3 | -0.0008, 0/2 | -0.0010, 2/6 | +0.0006, 1/0 | -0.0007, 1/5 | +0.0551, 3/1 |

Beat signature is the "classes" accuracy per page (the "onsets" view moves
with it everywhere); pooled at baseline 0.6127 on (a), 0.5682 on (c), 0.5944
on the hand scores and 0.5749 on the Omnibook (docs/beat-signature.md). The
open models raise it on (a) -- they do write more of (a)'s beats in the
page's figure -- while the gap-based rhythm on the same eight pages falls:
a wrong-for-wrong trade costs the beat-signature nothing and the gaps a
great deal.

## 1. The pages

The OMR corpus (`benchmark/Transcriptions_Other/musicxml`, read with
`scripts/figure_prior.py`'s reader and filters): 275 files; 7 dropped as
`figure_prior.OVERLAP` (their recordings are benchmarked -- the three silver
pages with audio among them); 79 held out as test split
(`tests/regression/split.json`, `figure_prior.without_test_pages`); **189 dev
pages**, of which **177** hold at least 16 notes on quarter-note beats.
Training labels come only from bars `figure_prior.bar_included` accepts,
single-voice, in x/4, outside duplicated beats: **49,084 labelled beats**.
72 pages carry a tempo marking (at or above `figure_prior.MIN_TEMPO`); 105
do not.

## 2. The performance model

Fitted by `reranker_data.py fit` to WJazzD's PERFORMED onsets against its
annotated BEATS, never the tatum layer (D36), leaving out the eight
triples' solos (melids 53, 55, 56, 58, 60, 61, 68, 121): 429 solos with 32+
beats and 40+ beat lines with an onset near them. Every parameter and its
source:

| parameter | value: median over solos (q10-q90) | source |
|---|---|---|
| tempo | the page's marking; else the reference solo's | page / WJazzD beats |
| reference solo | drawn from solos within 20% of the page's tempo (any, if unmarked); the pool is the 305 solos with 15+ eighth pairs and 20+ line downbeats, 127-288 bpm (q10-q90) | WJazzD |
| a written downbeat sounds at | +0.120 beats (0.045-0.200) | the middle of three onsets whose outer two are offbeats (0.5-0.88) of consecutive beats, -0.3..+0.45 of the line: 23,954 such downbeats in 319 solos, about 13% of them EARLY |
| its scatter | 49 residual quantiles per solo, rmad 0.100 beats (0.067-0.157) | same |
| a busy beat starts earlier | 3 onsets -0.049, 4 onsets -0.068 beats (1 onset -0.006) | median first onset by onset count (10,875 / 28,211 / 9,312 / 6,061 beats) against a pair's |
| an eighth pair's offbeat sounds at | 0.696 (0.631-0.764) | beats of exactly two onsets, first before 0.42, second 0.42-0.9, the beat before not pushed (24,658 pairs in 335 solos) |
| implied long:short | 1.25:1 (0.99-1.61) | offbeat less the pair's downbeat (0.555 of a beat); M4's ~1.3:1 |
| its scatter | 49 residual quantiles about a running median (pairs within 8 beats), rmad 0.079 (0.052-0.125) | same |
| drift of the line along the solo | AR(1), rho 0.924 per beat, sd 0.043 beats | autocorrelation of the pair downbeats at lags 1-32 |
| sixteenths | played straight: written spacing plus the beat's lateness, the drift, and each note's own draw from the downbeat scatter | four-onset beats: the third onset sits 0.476 of a beat after the first (2,682 beats) |
| triplets | at thirds, likewise | no WJazzD parameter (an assumption) |
| anticipation (a held "and" played on the next beat) | q = 0 | the estimate from docs/writing-round2.md's ratio (54 anticipated per 531 on-beat notes on (a)) is q = 0.78; the fidelity check rejects it (below) |
| two onsets never closer than | 15 ms | an assumption |

R29's median lag of +0.033 beats is a different estimator (a window median
of downbeat offsets against our TRACKED grid); against WJazzD's tapped beats
a downbeat inside a line sounds +0.12 late.

**Fidelity** (`reranker_data.py fidelity`): one rendering of every page
beside WJazzD's real beats, on what a re-ranker sees.

| | beats of 1 / 2 / 3 / 4 / 5+ onsets | pair: first onset q25/50/75 | pair: second | pair first from 0.25 | lone onset in 0-.15 / .15-.3 / .3-.45 / .45-.6 / .6-.75 / .75-.9 / .9-1 | last onset from 0.88 |
|---|---|---|---|---|---|---|
| WJazzD | .344 / .423 / .131 / .065 / .037 | .094 .198 .378 | .644 .753 .871 | .411 | .197 .119 .083 .167 .186 .144 .104 | .260 |
| v3, q = 0.78 | .357 / .453 / .123 / .046 / .022 | .085 .165 .279 | .638 .718 .815 | .303 | .329 .222 .074 .065 .156 .093 .061 | .198 |
| v3, q = 0.25 | .331 / .476 / .124 / .046 / .022 | .085 .165 .279 | .637 .715 .809 | .303 | .262 .174 .059 .091 .225 .128 .062 | .194 |
| v3, q = 0 | .324 / .485 / .123 / .047 / .022 | .083 .162 .280 | .637 .714 .804 | .301 | .219 .151 .061 .107 .253 .147 .062 | .189 |

The estimated anticipation rate puts a third of the lone onsets on the beat
where WJazzD has a fifth; q = 0 is nearest, so the models were trained at
q = 0 -- the synthetic performances carry NO anticipation. The remaining
gap is raggedness: real pairs start late (from 0.25) 41% of the time to the
model's 30%, and a real beat ends on the next line 26% to 19%. And the
model plays every written note and nothing else: no extra, missing or
merged notes, which is the largest class on the real (a) row (16.1%).

Two earlier performance models, kept in the script for the record: **v1**
took the line's lag as the NEAREST onset to each beat line, which pulls in
the previous beat's last notes and read the downbeat at +0.015 beats, ten
times too close (v2's pair measure: +0.133), and swung the offbeat to the
pair spacing; **v2** took the downbeat from the eighth pair itself, which
cannot see an early downbeat (a pair's first onset is inside its beat by
construction). Both were trained at q = 0.78.

## 3. The model

**Candidates.** `choose_reading` enumerates (grid, reading) pairs -- the
binary grids under the warped or the raw phase, the ternary grid under the
raw -- and the shipped rule keeps the coarsest within slack of the best
after the figure prior (R33). The hook hands a model every ADMITTED
reading: each keeps the beat's onsets apart, sends no onset to the next
beat line when that beat has its own note, and puts none on the beat line
when the beat before pushed onto it -- the note-keeping guards, applied
whether or not the prior is on. The rule's pick is marked `baseline`; the
model returns the one to write, or None to keep the rule's. It is never
asked when the rule's pick is the only admitted reading.

- **gated**: only readings the convention gates also allow (the tuplet and
  sixteenth gates, R27's sparse-beat trim, R28's inside rule, the straight
  reading's swing-point gate). With the shipped gates and the prior on, the
  rule's pick is always admitted when anything is, so a deferring gated
  model writes the shipped page exactly: measured, zero change on all 34
  pages, the 8 triples (both rows) and the 452 WJazzD solos.
- **open**: every reading of every grid the beat was offered before the
  sparse-beat trim, gates lifted, guards kept. Where the rule's own reading
  merges two onsets and an open reading keeps them apart, that reading is
  written even when the model defers (the admitted reading of least snap
  error): 345 fewer dropped notes over the WJazzD solos, +19 on the
  Omnibook.

**Features** (`reranker.featurize`, `FEATURE_SET = "v1"`): of the beat --
onset count (to 5), tempo band (beat length cut at 0.22/0.30/0.40/0.55 s),
neighbour density (onsets in the two beats either side), busy neighbours
(4+ onsets), ternary-looking neighbours (three onsets within 0.04 of
thirds), the beat's swing point past straight (bands at 0.02/0.08), whether
a lag was taken out, where its first and last raw onsets sound (bands),
whether the beat before ends late and the next is empty; of the candidate
-- grid and reading, snap error (in beats and in units of the 20 ms slack),
its excess over the beat's best, the figure-prior surprisal and its excess
over the beat's least, the figure (22 named, the rest "other"), the written
first and last positions by name, whether it pushes a note to the next
line, whether it is the rule's pick, whether it is ungated; and the
crossings of these (grid x count/tempo/density/neighbours/swing/lag, figure
x tempo/density for the twelve commonest figures, and so on). Sparse
names, one weight each.

**Training** (`reranker_train.py`): a conditional logit -- one linear score
per candidate, softmax over the beat's candidates -- fitted by L-BFGS to the
negative log of the softmax mass on the target candidates, plus L2 (1e-4;
1e-3 and 1e-2 read the same within 0.003 in cross-validation). Features
seen on fewer than 20 candidates are dropped: 453-455 weights open,
315-319 gated, a 9-13 KB JSON. Targets: `exact`, the candidates writing
every note of the beat where the page does (beats with none are left out of
the loss); `hits`, those writing the most notes right; `dist`, those
nearest in summed position; `stay`, exact, and where no candidate is right
the rule's own pick. Cross-validation holds out whole PAGES (5 folds, every
rendering of a page in one).

## 4. On the synthetic data

Three renderings of every page; a beat counts when the rule had a choice
and the page labels it. Cross-validated accuracy (does the written reading
put every note where the page does), held-out pages:

| performance model, q | candidates | labelled beats | rule | model | oracle |
|---|---|---|---|---|---|
| v1, 0.78 | open | 95,520 | 0.8329 | 0.8634 | 0.8851 |
| v1, 0.78 | gated | 42,990 | 0.9337 | 0.9357 | 0.9428 |
| v2, 0.78 | open | 93,275 | 0.8718 | 0.8909 | 0.9075 |
| v2, 0.78 | gated | 56,454 | 0.9270 | 0.9332 | 0.9393 |
| v3, 0 (exact) | open | 97,972 | 0.8523 | 0.8700 | 0.8867 |
| v3, 0 (exact) | gated | 53,313 | 0.9171 | 0.9230 | 0.9286 |
| v3, 0 (hits / dist / stay) | open | 97,972 | 0.8523 | 0.8668 / 0.8627 / 0.8621 | 0.8867 |
| v3, 0 (hits / dist / stay) | gated | 53,313 | 0.9171 | 0.9226 / 0.9220 / 0.9222 | 0.9286 |
| v3, 0, seed 1 (stay, trained on all) | open | 98,155 | 0.8554 | 0.8667 | 0.8904 |

On its own data the model recovers half the open headroom and half the
gated -- and the gated headroom is already only 1.2 points: on synthetic
performances the rule writes 92% of its gated beats right.

## 5. On human data

### The ceiling

On (a) the hook is consulted on 1,019 beats (open) or 433 (gated) across
the eight triples. Each is labelled from the triples' note pairing
(`triples.disagreements`): the page's position of each of the beat's notes
relative to the beat line.

| (a)'s beats where the open hook is consulted | beats | share |
|---|---|---|
| the rule's reading writes the page | 608 | 59.7% |
| a note only one side has (we heard it and the page did not write it, or the reverse) | 164 | 16.1% |
| no offered reading writes the page | 100 | 9.8% |
| the page writes a note in another beat (anticipation and its kin) | 57 | 5.6% |
| unreachable, but reached by shifting the beat so its first onset is on the line | 52 | 5.1% |
| an UNGATED reading writes the page | 25 | 2.5% |
| another gated reading writes the page | 9 | 0.9% |
| the rule's reading merges two notes | 4 | 0.4% |

The shifted figures are the laid-back downbeat again ("0 1/2" 22, "0" 15,
"0 1/4 1/2" 6, "0 1/4 1/2 3/4" 5): what R29's window lag leaves behind
beat by beat. So per labelled beat (794): the rule 0.7657, the best gated
reading 0.7771, the best open reading 0.8086.

The oracle (`--sets oracle`) picks the page's reading wherever one is
offered and is scored as (a) is scored:

| oracle over | rhythm | value | on the bar | beat signature |
|---|---|---|---|---|
| gated readings | +0.0023 [+0.0000, +0.0046], 3/0, p = 0.25 | +0.0010, 2/0 | +0.0007, 1/0 | **+0.0028 [+0.0008, +0.0055]\*, 3/0** |
| open readings | **+0.0142 [+0.0066, +0.0238]\*, 7/0, p = 0.02** | **+0.0082\*, 6/0** | **+0.0036\*, 3/0** | **+0.0111 [+0.0060, +0.0176]\*, 7/0** |

against (a)'s baseline rhythm 0.8146, value 0.7818. The open oracle is
measured against the open hook deferring everywhere (which keeps the notes
the rule merges; that page reads (a) rhythm -0.0021 against the shipped
one, level), so against the shipped page it is about +0.012. **A perfect
gated re-ranker is not decided on (a).** Whatever a gated model learns, the
pages cannot show it.

### Per beat on (a)

| model | changed (fixed / broke / both wrong) | written right per labelled beat |
|---|---|---|
| (rule) | -- | 0.7657 of 794 (gated: 0.8319 of 339) |
| v1 open | 67 (17 / 6 / 44) | 0.7796 |
| v2 open | 75 (15 / 11 / 49) | 0.7708 |
| v3 open, exact | 68 (15 / 3 / 50) | 0.7809 |
| v3 open, hits | 52 (11 / 4 / 37) | 0.7746 |
| v3 open, dist | 67 (11 / 14 / 42) | 0.7620 |
| v3 open, stay | 11 (4 / 0 / 7) | 0.7708 |
| v3 open, stay, seed 1 | 13 (4 / 1 / 8) | 0.7695 |
| v1 gated | 10 (3 / 2 / 5) | 0.8348 |
| v2 gated | 8 (4 / 2 / 2) | 0.8378 |
| v3 gated, exact / hits | 6 (4 / 1 / 1) | 0.8407 |
| v3 gated, dist | 7 (3 / 1 / 3) | 0.8378 |
| v3 gated, stay (both seeds) | 3 (3 / 0 / 0) | 0.8407 |

Every learned model is right more often than the rule per beat but one, and
the commonest move of the open `exact` and `hits` models is the same: a
beat the page writes as a plain eighth pair "0 1/2", played laid back,
which the rule writes "1/4 1/2" or "1/4 3/4" and the model "1/3 2/3" --
wrong either way.

### Where the open models' loss comes from

`--sets split` keeps a model's picks on some beats and the rule's on the
rest (paired over the eight, against the open hook deferring):

| v3 open, exact: picks kept on | rhythm | value | on the bar |
|---|---|---|---|
| every beat | **-0.0120 [-0.0224, -0.0019]\*, 2/6** | **-0.0100\*, 2/6** | **-0.0113\*, 0/7** |
| labelled beats only (68 moves: 15 fixed, 3 broke, 50 both wrong) | **-0.0099 [-0.0184, -0.0020]\*, 1/5** | **-0.0100\*, 1/6** | **-0.0058\*, 2/5** |
| the other beats only (45 moves) | -0.0013, 3/4 | +0.0008, 3/3 | **-0.0055\*, 1/6** |
| only where the pick writes the page | **+0.0046 [+0.0016, +0.0082]\*, 5/0** | +0.0031, 4/1 | +0.0011, 2/0 |
| everywhere but the both-wrong trades | +0.0019, 4/3 | +0.0028, 4/4 | -0.0044, 2/5 |

| v3 open, stay: picks kept on | rhythm | value | on the bar |
|---|---|---|---|
| every beat (24 moves: 4 fixed, 7 both wrong, 13 on unlabelled beats) | -0.0014, 2/3 | -0.0005, 3/3 | -0.0023, 2/4 |
| only where the pick writes the page | +0.0014, 2/0 | +0.0012, 2/0 | +0.0007, 1/0 |

The model's right answers are worth something (+0.0046, 5/0); its
wrong-for-wrong trades cost more than that (refusing them alone takes (a)
from -0.0120 to +0.0019). 49 of the 50 are on beats no offered reading
writes, and the training data cannot teach it to leave those alone: on
synthetic performances such beats are rarer (11% of labelled beats against
19% on (a)) and the `exact` loss leaves them out. `stay` teaches it to
leave them, and leaves almost nothing to gain. The keep-the-notes fallback alone ("open,
always defers") is level on rhythm everywhere and costs Omnibook edit cost
+0.28, 9/0: D37's finding again -- the transcribers do not write most of the
notes the rule merges.

### The one gated result that crossed the line

v3 gated `stay` is decided up on the Omnibook (rhythm +0.0012 [+0.0001,
+0.0026], 4/1, p = 0.38; edit cost -0.13, 0/4) and on (c) (+0.0034, 3/0),
and down nowhere. It was the tenth model judged on the pages, its target
was designed after the split above was read on the evaluation triples, and
it moves 3 beats of (a). Retrained on an independent rendering
(seed 1) it reads Omnibook rhythm +0.0004 [-0.0006, +0.0015], 3/2, and
nothing decided anywhere. Not a result.

### Collateral

The quantizer instrument's dropped notes never rose: unchanged under every
gated model, -345 (of 4,203) under every open one, the keep-the-notes
fallback. No page lost a note; readability moved by -0.0002 to +0.0008.

## 6. Negative results, for the record

- A learned re-ranker over the gated readings: six judged, none reliably
  off level (one decided down on hand value, one decided up on the
  Omnibook and not replicated); the oracle over them is not decided on (a).
- Over the open readings: decided down on the Omnibook in all six judged
  (rhythm -0.0036 to -0.0191, value down in five), and on (a)'s on-the-bar
  in four.
- Performance model v1 (nearest-onset lag) and v2 (pair downbeat): the
  first misplaces the downbeat tenfold; both trained at the estimated
  anticipation rate, which the fidelity check rejects.
- Targets `hits` and `dist` (teach the least-wrong reading where none is
  right): fewer moves than `exact`, the same direction on the pages; `dist`
  breaks more beats than it fixes on (a) (11 / 14).
- Target `stay`: removes the trades and the gain together.
- Regularisation (L2 1e-4 to 1e-2): within 0.003 in cross-validation.
- The beat-signature accuracy disagrees with rhythm on the open models (up
  on (a), level to up on the Omnibook, while rhythm falls): it charges
  nothing for a wrong-for-wrong trade.

## 7. What more data would buy

The synthetic route has a hard limit and a soft one. The hard one is the
candidate set: with human onsets on human beats, a perfect choice among the
gated readings buys +0.002 of rhythm on (a) and among all readings +0.014.
No training data moves that. The soft one is what synthetic performances
cannot show: notes one side has and the other does not (16% of (a)'s
beats), anticipations (6%), and the beats no reading writes (10%), where a
model trained on clean renderings makes its costly trades.

- **Paired tier-A pages** (performed onsets beside a human page: WJazzD
  solos with a transcription PDF, or the listener's recordings with their
  pages). Each is a set of real labelled beats -- (a) has 1,019 consulted
  beats in eight solos, a hundredth of one synthetic training set, so a
  model trained on them needs dozens of pages before it can be trusted, and
  the eight triples must stay the evaluation. What they would teach that
  synthesis cannot: when to leave an unwritable beat alone, and the
  anticipation and omission classes.
- **New candidate readings**, judged with that data: a per-beat lag shift
  (the beat moved so its first onset is on the line: 52 of (a)'s beats,
  5.1%, become writable, 22 of them a plain eighth pair), and an
  anticipation reading that moves a note across the beat line. Both were
  tried as RULES (docs/writing-round2.md: the late downbeat, decided down;
  anticipation is not readable from timing) -- a learned choice among them
  is the version that has not been tried, and it needs real pairs.
- **The listener's corrections in the Page view** would be the cheapest
  paired data of all: each corrected beat is (our onsets, the human figure)
  for exactly the beats we get wrong.

## Reproduce

    python scripts/reranker_data.py fit --db wjazz/wjazzd.db --out perf.json
    python scripts/reranker_data.py fidelity --perf perf.json
    python scripts/reranker_data.py render --perf perf.json --q 0 --seed 0 --out beats.pkl
    python scripts/reranker_train.py --beats beats.pkl --mode gated --target stay --cv 5 --l2 1e-4
    python scripts/reranker_train.py --beats beats.pkl --mode gated --target stay --l2 1e-4 --out w.json
    python scripts/reranker_eval.py --db wjazz/wjazzd.db --notes <notes snapshot> \
        --grids <grids snapshot> --model gated=w.json --sets oracle,beats,split,triples,pages,beatsig,flexq

`fit` 5 s, `render` (three renderings) under a minute, training 30 s, a
cross-validation 90 s; the evaluation six minutes for two models on the
triples, pages, beat signature and Flex-Q with `--jobs 4`, and four more for
`oracle`, `beats` and `split`. The fitted model, the renderings and the weights stay in
scratch: per-solo WJazzD statistics are ODbL derivatives and the beats are
derived from the pages.
