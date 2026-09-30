# Proposing the solo spans (roadmap O3, 2026-09-30)

`src/swingscribe/solo_spans.py`, measured by `scripts/solo_spans_survey.py`.
Nothing is pinned and nothing calls it yet: the pipeline, the GUI and every
cache key are untouched. This is the research half of O3; the GUI half is
sketched at the end.

## Why

A new listener's first job is to find a solo's A and B on a waveform they
have never seen. Two things the app holds before any transcription could do
it for them: the whole-file stems (the quick htdemucs_6s set the batch
already locates with) say who is playing, and the repaired bar grid says
where a boundary may fall. The question was how far those two go, and where
they cannot.

## The reference: 77 solos, 154 edges

WJazzD annotates 77 solos on the 49 distinct recordings under
`benchmark/wjazzd/` (74 files; So What, Blue Train, Oleo, Dolores, Orbits,
In 'n Out and others are byte-identical copies of one track, one file per
annotated soloist). An edge is a solo's first annotated onset or its last
note-off; 154 in all.

- **74 solos are placed by content**: the batch fitted each annotation to
  our audio and wrote the span to the sidecar (`region`: first and last
  onset, one second either side). Against WJazzD's own `solostart_sec`
  those starts agree to a median +0.02 s, within a second on 88% of them;
  the rest are transfers at another speed (So What's three solos drift
  +2.3, +4.2, +6.3 s, a 1.8% rate) and one wrong database entry (George
  Coleman's Maiden Voyage, melid 171, carries Hubbard's `solostart_sec` and
  is 64.9 s off).
- **3 are placed from the original-track time** (Miles's second Oleo solo,
  Charlie Shavers on Limehouse Blues, J.J. Johnson on My Funny Valentine):
  annotated on a track we hold with no copy of their own, so WJazzD's start
  is corrected by the offset of their located siblings -- a line through
  three on Oleo, a constant from one on the other two. The My Funny
  Valentine sibling reads -1.7 s, so that solo is placed to about a second,
  not a bar.
- **21 handovers**: an annotated solo that starts at most 8 s after another
  ends, or up to 1 s before (Red Garland's first note on Oleo sounds 0.04 s
  before Coltrane's last one ends). They run -0.04 to +3.7 s; the next gap
  is 15 s. Every one is between two instruments.

**The ceiling.** A solo does not start on its chorus line. Over the 62
solos with two or more annotated choruses, the first onset is within one
bar of WJazzD's first chorus line on 61% and within two on 85%; the last
note is within one/two bars of a chorus line on 74%/85%. A proposer that
cut perfectly on chorus lines would read those numbers against the note
edges, so **two bars** is the tolerance that measures the proposer rather
than the pickup; one bar and 4 s are printed beside it.

**What cannot be judged.** WJazzD annotates some soloists, not the head,
the piano or bass solos, the fours or the ending. A proposed boundary more
than two bars inside an annotated solo is wrong for certain: **wrong-inside**.
One outside every annotated solo that matches no edge is **unjudged**; most
are real boundaries the reference does not mark, and the survey never
counts them either way. The first and last bar lines are span edges too
(a solo can open the track), but never proposals.

## How it is scored, and why that is not mir_eval's matching

`score_boundaries` is hand-rolled, and it is the project's second
exception to "mir_eval is the source of truth", beside `alignment.py`'s
time-free note comparison. Three things about this reference make
mir_eval's precision/recall the wrong question:

- **A handover is one boundary.** The proposal is a run of contiguous
  spans, so each boundary ends one span and starts the next; at a handover
  the same boundary is the end of one annotated solo and the start of the
  next, and `score_boundaries` credits it to both. `mir_eval.util.match_events`
  matches it once, and under one-to-one matching a handover all but cannot
  be found whole: `MIN_BARS` keeps timbre cuts eight bars apart and a head
  edge within four bars of a cut is merged into it, so its second edge is a
  miss by construction. With 21 handovers, one-to-one recall is held to
  about 133 of 154 edges (0.86) whatever the proposer hears.
- **The tolerance is in bars** at the local tempo, a different number of
  seconds at every edge.
- **The reference is partial**, so a proposal matching no annotated edge is
  not a false positive (above), and mir_eval's precision would count every
  one as such. Wrong-inside replaces precision.

The survey prints mir_eval's one-to-one count beside the shipped one, over
the same proposals at the default (`match_boundaries`: `match_events`, with
the bar tolerance through its `distance` hook), so the difference is on the
record rather than hidden in it:

| edges within 1 bar / 2 bars / 4 s | starts | ends | all 154 edges |
|---|---|---|---|
| shipped, many-to-one | 0.57 / 0.71 / 0.81 | 0.55 / 0.73 / 0.78 | 0.56 / 0.72 / 0.79 |
| mir_eval, one-to-one | 0.47 / 0.53 / 0.58 | 0.55 / 0.73 / 0.78 | 0.51 / 0.63 / 0.68 |

One-to-one loses 14 edges within two bars and 17 within 4 s, and **every
one of them is one edge of a handover**. (Which of the two edges it keeps is
the matcher's tie-break; here the end, so only starts move.) The
difference is exactly the handovers found whole, and nothing else.

## What the proposer does

1. **Envelopes.** Each stem is read once as 16-bit PCM, averaged to 22 kHz
   mono, and reduced to quarter-octave band power ten times a second, with
   pitch-class power for the horn stems (`other`, `vocals`, `guitar`).
   Nine seconds and 124 MB peak for the six stems of an 824 s track; the
   survey's cached envelopes (with bass and piano chroma besides) are
   0.8-7.2 MB compressed, median 1.8.
2. **Bar features** (`bar_features`, 30 a bar): each stem's level against
   its own 95th percentile, floored at -40 dB; and twelve cepstra of the
   summed melodic stems' band shape over the frames within 25 dB of their
   loud level, as a mean and a spread per bar. Standardised over the track.
3. **Optimal partitioning** (`segment`): the exact minimum of within-segment
   squared deviation plus 4.0 per feature per segment, segments of at least
   8 bars. 0.05 s for the longest track, 647 bars.
4. **The head** (`find_head`): the horn stems' bar chroma correlated bar
   against bar; the strongest diagonal stripe at a lag of at least a third
   of the track whose first half starts in the track's first 30% and whose
   second half ends in its last 30%, believed from a correlation of 0.85
   (38 of the 49 recordings). The stripe is found on a 4-bar smoothing of
   the diagonal and its edges are then placed on the raw diagonal
   (`_refine`, below). **The head-in's last bar** is a boundary where no
   timbre cut lies within four bars; where one does, the cut places the
   boundary (`combine`). The head-out's first bar is not a boundary by
   default (below).
5. **Spans** between consecutive boundaries, each labelled with the melodic
   stem holding the most energy, "rhythm" when the melodic stems sit 20 dB
   under their loud level, and "head" when most of the span is in the
   stripe.

## Results (htdemucs_6s, default meter, 77 solos on 49 recordings)

Share of edges with a span edge within one bar / two bars / 4 s:

| penalty | starts | ends | both edges | boundaries | wrong-inside | F1 | F2 |
|---|---|---|---|---|---|---|---|
| 2 | 0.58 / 0.73 / 0.84 | 0.61 / 0.77 / 0.86 | 0.29 / 0.55 / 0.73 | 777 | 241 | 0.451 | 0.592 |
| 3 | 0.60 / 0.71 / 0.83 | 0.62 / 0.78 / 0.87 | 0.31 / 0.55 / 0.73 | 504 | 112 | 0.604 | 0.682 |
| **4** | **0.57 / 0.71 / 0.81** | **0.55 / 0.73 / 0.78** | **0.26 / 0.46 / 0.60** | **367** | **59** | 0.685 | **0.706** |
| 5 | 0.52 / 0.65 / 0.74 | 0.52 / 0.68 / 0.75 | 0.21 / 0.39 / 0.53 | 309 | 43 | 0.682 | 0.670 |
| 6 | 0.48 / 0.60 / 0.69 | 0.51 / 0.65 / 0.73 | 0.21 / 0.38 / 0.48 | 265 | 24 | 0.701 | 0.652 |
| 8 | 0.44 / 0.58 / 0.68 | 0.47 / 0.58 / 0.64 | 0.20 / 0.33 / 0.42 | 214 | 13 | 0.700 | 0.626 |

F counts edges found within two bars against the wrong-inside proposals
only. **The penalty is chosen on F2**, which weighs a missed edge four times
a false one, and that was decided before a fold was scored: a false
boundary inside a solo costs the listener one drag across it, a missed edge
costs finding it by ear. F1 would choose 6-8.

At the default: 367 boundaries, 7.5 a recording, 59 of them inside the 128
annotated solo-minutes (0.46 a minute). **35 of the 77 solos have both
edges within two bars, and 21 of those come out as one span with nothing
inside -- one click.**

### What is cross-validated, and what is not

**Only the penalty.** Two-fold cross-validation by recording (alternate
recordings, F2 on the training fold) chose 4.0 on both folds, so for the
penalty the bold row is also the held-out reading. **Every other choice was
made on these same 77 solos**: the 8-bar minimum segment, the head
thresholds (swept, below), the head-edge merge rule and the head-out
decision (both changed after looking, below), the edge refinement's effect
on real heads, the 25 dB gate, the feature set and the lead rule. The
numbers above are in-sample for all of them.

A joint two-fold cross-validation of the three discrete knobs the survey
can sweep cheaply -- penalty (2-8) x minimum segment (4, 8, 12) x head
edges (none, in, in+out), 54 settings -- chose (4, 8, in) on one fold and
(3, 12, in) on the other. Held out: starts 0.58 / 0.70 / 0.78, ends
0.57 / 0.75 / 0.81, both 0.29 / 0.49 / 0.62, 80 wrong-inside, **F2 0.693
against the in-sample 0.706**. The head thresholds, the gate and the
features are not in that grid.

### Against chance

The same number of boundaries per recording, placed without listening, 200
draws each:

| edges within 1 bar / 2 bars / 4 s | starts | ends | wrong-inside |
|---|---|---|---|
| uniformly on interior bar lines | 0.07 / 0.12 / 0.17 | 0.07 / 0.12 / 0.17 | 150 |
| evenly spaced, random phase | 0.08 / 0.13 / 0.21 | 0.07 / 0.13 / 0.19 | 167 |
| the proposer | 0.57 / 0.71 / 0.81 | 0.55 / 0.73 / 0.78 | 59 |

The best of 200 uniform draws finds 0.20 of the edges within two bars (95th
percentile 0.16); the proposer finds 0.72 with about 40% of chance's
wrong-inside. The track's first and last bar lines, which are span edges
for everyone, account for one start and one end.

### Where the found edges fall

Of the starts found within four bars (n = 63), proposal minus first onset
is -1.64 / -0.99 / **-0.41** / +0.10 / +0.51 bars at the
10th/25th/50th/75th/90th percentiles; of the ends (n = 61), -0.29 / -0.00 /
**+0.33** / +1.03 / +1.62. A proposal sits on the bar line before a pickup
and after the last note's bar: the side a span should err on.

**By what is across the edge** (within two bars):

- a handover between two annotated soloists on different instruments:
  0.74 of 42;
- a start whose other side WJazzD does not annotate (a head, an intro, a
  piano solo): 0.71 of 56; an end likewise: 0.71 of 56;
- the reference holds **no handover between two players of one
  instrument**, so that case is untested here (below).

### The head cue

Against timbre alone at the default penalty: starts within two bars 0.64
-> 0.71, within 4 s 0.71 -> 0.81; ends unchanged; 22 more boundaries, 2
more wrong-inside, F2 0.675 -> 0.706. Six starts are found that no timbre
cut sees (Donna Lee, Yardbird Suite, Sandu, Orbits, St. Thomas, Footprints)
and none is lost. Per recording, edges within two bars +0.049 [+0.014,
+0.092] (6 up, none down, sign test p = 0.031); within 4 s +0.053 [+0.017,
+0.095] (7 up, none down, p = 0.016).

**How near the head's end is to a solo's start, counted without selecting
on the answer.** On the 38 recordings with a believed head, 44 starts have
no annotated solo before them. For the first of them on each recording
(38), the head-in edge is within two bars on 13, within eight on 21, and a
median 4.6 bars away. The stripe ends where the head-out stops repeating
the head-in bar for bar, which is often a few bars before the solo: an
intro, a break, a pickup, or a head-out embellished at the end.

**How it merges was changed after the first survey**: letting the head edge
overrule a timbre cut within four bars loses starts the cut had right (So
What, where the stripe stops 6 s before Miles comes in; Totem Pole 5 s;
Oleo 3 s). With the cut placing the boundary: starts within two bars 0.66
-> 0.71, F2 0.684 -> 0.706 at today's defaults. One decision, made on a
diagnosed mechanism rather than a sweep, but made on these 77.

**The head thresholds**, swept on the same 77 at the shipped defaults: gap
2-8 reads alike and gap 0 loses two starts (0.71 -> 0.69 within two bars);
similarity 0.80 believes 41 heads for the same recall, 0.90 only 25 for
0.68; the floor never binds between 0.45 and 0.55, because every believed
peak is 0.85 or more and `peak - 0.3` sets it. F2 0.686-0.707 over the
whole grid, 0.706 at the shipped point.

### The lead label

For the span over each annotated solo's middle, on htdemucs_6s: the 72 horn
solos read `other` 58, `guitar` 11, `vocals` 3; the four piano solos
`piano` 2 and `guitar` 2 (htdemucs_6s files a piano under guitar);
Metheny's guitar solo `guitar`. Never `piano` or `rhythm` for a horn -- but
a horn stem is not the same thing as the right stem, so the label is
checked against something it does not read: **the stem whose chroma
follows WJazzD's annotated line** over the solo (the annotated notes
carried into our timeline, as a pitch-class target on half-second frames,
correlated with each stem's log chroma).

- **htdemucs_6s, the 69 located horn solos: the label is that stem on 64.**
  It is clearly another on 3 (0.1 or more under the line's stem): `guitar`
  on both of Coltrane's My Favorite Things solos (line correlation `other`
  0.68 and 0.52 against `guitar` 0.24 and 0.29) and on J.J. Johnson's Crazy
  Rhythm (`other` 0.45, `guitar` 0.10). On 2 the line is shared between
  stems (Dolores: `vocals` 0.43, `other` 0.42, label `guitar` 0.36;
  Coltrane's Oleo: `vocals` 0.55, label `other` 0.48). The line itself is in
  `other` 59 times, `guitar` 6, `vocals` 4, and on the 10 where it is not in
  `other` the label names its stem 8 times. Against always choosing `other`
  for a horn (right on 59 of 69), the label is right on 64.
- **The Roformer, the 32 located horn solos on the 22 recordings with a
  whole-file set: the label is the line's stem on 31.** The line is in
  `other` on all 32 -- the Roformer files every horn there -- and the label
  says `piano` once (Chet Baker's There Will Never Be Another You: `other`
  0.73, `piano` 0.12). On the same 32 solos htdemucs_6s reads 28 of 32.

So **the label names a stem of the separation it was read from.** On
htdemucs_6s it follows a horn into `guitar` or `vocals` most of the time
it goes there (8 of 10) and wrongly sends it there 3 times in 69; on the
Roformer, the default separator, a horn is always in `other` and the label
adds nothing but one wrong `piano`. An htdemucs_6s label carried to a
Roformer set names the wrong stem whenever it is not `other`. It is a
suggestion, never a routing rule -- and never a reason to set `ensemble`: a
horn span labelled `piano` would send a horn to the piano oracle, which
CLAUDE.md forbids.

### The separator

On the 22 recordings (36 solos) with a whole-file set of both: htdemucs_6s
F2 0.699, BS-Roformer-SW 0.679 (starts 0.69 against 0.67, ends 0.72 against
0.69 within two bars; wrong-inside 26 against 24). The Roformer's better
horn routing buys no boundaries; the quick separation is the right input,
and the one a new track can have in minutes.

### The Omnibook

The Omnibook gives one edge a side, the end of Parker's solo (its located
regions hold the head and Parker's choruses). On whatever whole-file stems
exist (16 Roformer, 6 htdemucs_6s): found within one bar / two bars / 4 s
on 0.50 / 0.77 / 0.77 of 22 sides, 0.62 / 0.81 / 0.81 of the 16 not also in
WJazzD. Nothing was tuned on it.

## Changed after review (2026-09-30)

An adversarial review of the first version found two defects in the head
cue and several claims the survey did not support. Fixed, each on a stated
mechanism, then the survey re-run; every number in this file is the re-run.

- **The stripe's start was a bar or two late.** `find_head` thresholded a
  4-bar boxcar of the diagonal, and np.convolve's "same" mode sits an even
  kernel half a bar off centre (bars k-2..k+1); the floor then erodes the
  edge. On 200 planted heads the smoothed edges were exact on 5: the start
  was 1-2 bars late on 193, the end a bar early on 52. `_refine` moves each
  edge by at most two bars to where the RAW diagonal crosses the floor:
  exact on 199 of 200 (the other runs a bar long because a random bar
  correlated above the floor). On the 38 real heads it moved the start on
  27 (earlier by 1-3 bars, as the bias predicts) and the end on 20 (13 a
  bar later, 6 a bar earlier, 1 three earlier); the same 38 are believed.
  That the end moved on real music is the refinement's doing, not its aim,
  and it is measured on these 77: two more starts within two bars
  (Yardbird Suite, St. Thomas), none lost.
- **The head-out edge is off** (`HEAD_EDGES = "in"`). Its start lands
  within two bars of an annotated solo end on 1 of the 38 head recordings
  (0 before the refinement), so the reference almost never says it is
  right, and it costs 16 boundaries and 2 wrong-inside (F2 0.704 against
  0.706). `head_edges="in+out"` still offers it; the head-out is labelled
  "head" either way.
- At the default, from the first version to this one: starts within two
  bars 0.69 -> 0.71 (ends 0.73 both), boundaries 385 -> 367, wrong-inside
  61 -> 59, F2 0.693 -> 0.706, one-click solos 20 -> 21. The head cue per
  recording, within two bars +0.034 (p = 0.13) -> +0.049 (p = 0.031); within
  4 s +0.063 (p = 0.008) -> +0.053 (p = 0.016).
- Withdrawn claims: "the 11 starts that follow a detected head: all 11"
  selected those starts by the head edge's own hit condition (the honest
  count is the 13 of 38 above); "a horn stem every time" counted any
  non-piano label a success (the line check above replaces it); "the
  cross-validated numbers are the bold row" held for the penalty alone.
- Added: the one-to-one control, the chance control, the joint
  cross-validation, and a handover rule that admits Oleo's 0.04 s overlap
  (20 -> 21 handovers).

## What did not work

Development runs on the same 77 solos and htdemucs_6s, from scratch scripts
that pooled frames by truncation rather than rounding, scored without
the track's end bar lines, and ran with the head-out edge on and the
stripe's smoothed edges; the survey read within about 0.03 of them. Every
comparison below is at matched settings within those runs.

- **Novelty peaks on a wide window.** A 16-bar contrast of the same
  features ranks above 99% of in-solo bars at 65% of starts and 77% of
  ends: the cue is there. Peak-picking places it badly -- starts within one
  bar 0.36-0.38 at 427 boundaries against the partition's 0.52 at 340 --
  even when each peak is placed by a 4-bar contrast. Filtering the
  partition's cuts by the wide contrast did no better (0.36 at 409).
- **Cutting only on chorus lines.** WJazzD's own chorus length, laid on our
  default-meter grid from the first annotated chorus, puts 174 of 297
  annotated chorus starts on the lattice (59%): our bar count drifts over a
  track. The partition restricted to it read starts 0.40 within one bar at
  275 boundaries.
- **Snapping to a four-bar phase.** Chorus lines sit on their track's modal
  four-bar phase 73% of the time (226 of 308). Snapping the boundaries to
  it -- with the phase taken from the ANSWER -- lowers starts within one
  bar 0.51 -> 0.34 and within two 0.64 -> 0.53. The phase voted by the cuts
  or read off the head does the same.
- **Scaling features by their bar-to-bar noise** instead of their spread
  over the track (which contains the very changes sought): worse at every
  penalty, e.g. starts within two bars 0.61 at 592 boundaries against 0.64
  at 485.
- **Repetition as a per-bar feature** of the partition instead of the
  stripe's edges: the same start recall (0.69 within two bars) with 81
  wrong-inside against 51.
- **Cepstra per stem** (horn stems and piano apart): 124 wrong-inside
  against 51 at the same penalty, recall no better. **PCA to ten
  dimensions**: starts up (0.73 within two bars), ends down (0.65), 91
  wrong-inside. **Gating at 15 or 35 dB** instead of 25: within 0.04
  everywhere. **Weighting** the level block 0.5-2x or the spread 0-0.5x:
  best F2 0.650 against equal weights' 0.660.
- **The lead label by level against each stem's own peak**: horn solos
  named `vocals` 28 times and `piano` 4, because a stem of bleed has a low
  peak to be loud against. By energy, the line check above.
- **Form length from the bass stem's chroma** (the lag whose self-similarity
  most stands out, 12-64 bars): right on 22 of 42 tunes with a closed form,
  a multiple or divisor on 10 more. Not good enough to fill the sidecar's
  `bars_per_chorus`; it stays in the survey (section 9).

## What cannot work this way

- **A soloist who follows his own head.** Nothing in the envelopes changes
  at the head's last bar when the same horn plays both. The repetition cue
  finds it only when the head-out repeats the head-in closely, and 6 of the
  records below have no believed head at all. **16 of the 56 starts with no
  annotated solo before them are missed, and 15 of those 16 are the first
  annotated solo on the record, by its leader or co-leader**: Parker on
  Don't Blame Me, KC Blues and My Little Suede Shoes; Baker on Let's Get
  Lost and Long Ago and Far Away; Marsalis on April in Paris and Cherokee;
  J.J. Johnson on Crazy Rhythm and My Funny Valentine (co-leading with
  Getz); Adderley on This Here, Brown on Joy Spring, Gordon on Cheese Cake,
  Miles on Dolores, Bechet on Limehouse Blues, Shorter on Adam's Apple. The
  16th is Hancock's piano after the head on Gingerbread Boy. That the
  leader's horn carried the head is an inference from the credits: WJazzD
  does not say who played it.
- **Two soloists on one instrument** -- two tenors trading, a trumpet solo
  after a trumpet solo. The reference cannot test it (all 21 handovers are
  between different instruments), and the nearest case is a warning:
  Coltrane's tenor handing to Adderley's alto on So What (317 s) is found at
  penalties 2 and 3 but not at the default, because the two differ by a
  fourth in register and in little the band shape sees at one bar's
  resolution. The synthetic test holds that a register shift inside one
  stem is found when it is clean; on real music, same instrument and same
  register is harder than this and untested. A register cue from the
  transcribed pitch is the next thing to try, and it needs CREPE over the
  whole file, which this proposer exists to come before.
- **An open vamp.** My Favorite Things gets 14 boundaries, 4 of them inside
  Coltrane's two solos, where McCoy Tyner's comping changes texture and the
  soloist does not.
- **The grid's resolution.** Boundaries land on the default meter's bar
  lines; a grid at half the true pulse puts them on every other true bar,
  and the tolerances here are counted in our bars.

## For the GUI (not built)

The module takes a `StemEnvelopes` and the bar lines `/beats` already
draws, and returns `Proposal.spans`. What the Overview would need:

- whole-file stems. A new track has none; the quick htdemucs_6s separation
  (about 2.7 minutes per 10 minutes of audio on CPU) is the input measured
  here, and any whole-file set works (the Roformer read a little worse);
- the envelopes cached beside the stems, so opening the track again costs a
  twentieth of a second;
- the spans drawn as bands on the Overview, labelled "head" where they are;
  a click sets A and B to the span's edges; the penalty as a "fewer / more"
  control (6 / 4 / 3);
- **the lead label shown, not applied.** It names a stem of the set it was
  read from, so the boundaries can come from htdemucs_6s while the Stem
  menu's default comes from the set the listener transcribes from (the
  Roformer by default, where a horn is in `other` 32 times of 32). Never
  let it set `ensemble`.

## Reproducing

    uv run python scripts/solo_spans_survey.py --db wjazz/wjazzd.db

Reads the stage cache's whole-file stem sets once (87 of them: 48
htdemucs_6s and one Roformer for the WJazzD recordings, 22 Roformer for the
comparison, 16 for the Omnibook), caches their envelopes in
`benchmark/.solo-spans/` (gitignored, 206 MB, safe to delete), and prints
sections 1-9 in about 30 seconds after that. The beat grids are
`.benchmark-grids.json`'s, repaired with `meter.bar_grid` under the default
meter: no sidecar time signature or downbeat, since a new listener has set
neither. `match_boundaries` needs mir_eval (the `ml` group). Only
aggregates leave the script.
