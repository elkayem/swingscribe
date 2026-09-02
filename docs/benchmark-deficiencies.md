# Deficiencies relative to the benchmark

A running, ordered list of what stands between the current pipeline and a
transcription worth handing to a musician. Ordered by measured impact, not by
how interesting the problem is. Every entry has to name a number that would
move; anything that cannot is an opinion and belongs somewhere else.

Reproduce all of it with one command:

```bash
uv run python scripts/run_eval.py --db wjazz/wjazzd.db
```

## Two benchmarks, measuring different things

This distinction turned out to matter, and confusing them cost real time.

**WJazzD (`score_wjazz.py`) — audio against audio.** Per-note onsets in
seconds, annotated from the recording by a human. Asks: *did we hear what was
played?* Nothing stands between our timestamps and theirs but where the track
starts. This is the right measure of `transcribe`.

**MuseScore (`score_benchmark.py`) — audio against notation.** A notated
score has no timestamps, so scoring it in time needs a tempo map and a swing
model. Asks: *would this notate the way a human notated it?* It necessarily
charges the gap between performed timing and notated rhythm to the
transcriber, so it reads lower and always will. This is the right measure of
the notation path, and a pessimistic one for `transcribe`.

Scoring against notation and reading the result as a transcription failure is
what sent months of attention toward timing. Do not repeat it.

## Current state

WJazzD — note F1 is onset within 50 ms **and** exact pitch, against a human
annotation of the same recording. One audio file can hold several annotated
solos and each is scored separately:

| tune | soloist | tempo | note F1 | note recall | beat F1 |
|---|---|---|---|---|---|
| Orbits | Herbie Hancock, piano ★ | 265 | **0.895** | 0.832 | 0.970 |
| Nothing Personal | Pat Metheny, guitar | 242 | **0.873** | 0.882 | 0.832 |
| Yesterdays | J.J. Johnson, trombone | 125 | **0.835** | 0.849 | 0.977 |
| Walkin' | Miles Davis, trumpet | 128 | **0.829** | 0.849 | 0.934 |
| Nothing Personal | Michael Brecker, tenor | 244 | **0.817** | 0.808 | 0.728 |
| Dolores | Miles Davis, trumpet | 275 | **0.755** | 0.765 | 0.987 |
| Don't Blame Me | Charlie Parker, alto | 64 | **0.754** | 0.777 | 0.948 |
| Dolores | Herbie Hancock, piano | 282 | **0.749** | 0.731 | 0.905 |
| Gingerbread Boy | Herbie Hancock, piano ★ | 286 | **0.715** | 0.623 | 0.976 |
| Oleo | Red Garland, piano ★ | 265 | **0.710** | 0.600 | 0.985 |
| Dolores | Wayne Shorter, tenor | 277 | **0.676** | 0.660 | 0.976 |
| | | **mean** | **0.782** | | **0.929** |

★ routed to the piano oracle (`ensemble: trio` in the sidecar). Those three
were 0.828, 0.641 and 0.674 before it — see R10. Dolores is deliberately not
routed: its span holds a trumpet and a tenor as well as Hancock's piano.

Eleven solos, seven instruments, 64 to 286 bpm, four of them by pianists.
Four tracks are correctly *not* scored, because WJazzD's versions are by
different players: Confirmation, Giant Steps and All The Things land at
1.9-9.3%, which is what note density predicts for the wrong take, and Star
Eyes at 4.5% is most likely a different issue of the same tune.

Notation — of the notes we get right, how many are *written* the way the
human wrote them:

| tune | bars | matched | rhythm | note value |
|---|---|---|---|---|
| Giant Steps ★ | 67 | 250 | **0.777** | **0.692** |
| Confirmation | 134 | 581 | **0.744** | **0.668** |
| Lover Come Back ★ | 64 | 314 | **0.671** | **0.627** |
| All The Things | 74 | 380 | **0.618** | **0.682** |

MuseScore — audio against notated rhythm, the pessimistic measure:

| tune | pitch F1 | onset F1 | note F1 |
|---|---|---|---|
| All The Things | 0.892 | 0.586 | 0.516 |
| Giant Steps ★ | 0.761 | 0.633 | 0.554 |
| Confirmation | 0.762 | 0.596 | 0.514 |
| Lover Come Back ★ | 0.710 | 0.428 | 0.266 |

The gap between the first and last tables is the point. Against audio the
transcriber is at note F1 0.76; against notation it reads 0.51. Some of that
gap is real — notation idealizes what was played, and that difference is the
transcriber's to explain — but it is not evidence about hearing.

## Open deficiencies

### D1 — Fast piano is the weakest case, and it is a clean pattern

The four lowest scores are not scattered. Every pianist above 260 bpm is at
the bottom of the table:

| soloist | tempo | note F1 | precision | recall |
|---|---|---|---|---|
| Herbie Hancock, Orbits | 265 | 0.828 | 0.845 | 0.812 |
| Herbie Hancock, Dolores | 282 | 0.749 | 0.768 | 0.731 |
| Red Garland, Oleo | 265 | 0.674 | 0.786 | 0.590 |
| Herbie Hancock, Gingerbread Boy | 286 | 0.641 | 0.676 | 0.610 |

**It is recall, not precision** — we hear fewer notes than they played, which
is the opposite of the Giant Steps complaint (too many notes, left-hand
comping). Block-chord piano at a burning tempo moves its top voice inside a
sustained texture, so there is no attack for an onset detector to find, and a
monophonic tracker has to pick one voice out of a chord.

This is what M7b (the piano path) exists for and it should not be chased
inside `transcribe`. Orbits at 0.828 shows the ceiling is not low; the other
three show what a chordal left hand costs.

### D2 — Long sustained notes are transcribed as several notes

**37% of All The Things' invented notes.** An 11-beat held note near the end
of that solo comes out as four, three of which are then scored as inventions.
Found from the user's report and confirmed by inspection.

Same-pitch fragments as a share of invented notes: All The Things 37%,
Confirmation 14%, Giant Steps 12%. Costs precision now, and would notate as
four tied fragments.

**One fix tried and rejected on measurement.** The onset corroboration test
asks only for a *rise* in the note's own harmonics, and vibrato swells a held
note by several dB unaided — which is exactly what cut that note into five.
Requiring the energy to *dip* below the sustain first, where the pitch is the
same note either side, does fix the case: at 2 dB the held note comes back as
one 3.20 s note.

It loses overall. Genuine repeated notes are suppressed faster than
fragments are saved:

| `onset_dip_db` | Orbits | Walkin' | Oleo | Yesterdays | mean |
|---|---|---|---|---|---|
| 0 (ships) | 0.828 | 0.829 | 0.674 | 0.835 | **0.791** |
| 2 | 0.827 | 0.812 | 0.666 | 0.805 | 0.775 |
| 3 | 0.826 | 0.800 | 0.663 | 0.806 | 0.774 |

Down on every tune. The knob stays, defaulted off, because the mechanism is
sound and a better rise/dip discriminator may yet win — but it must not be
turned on without re-running `run_eval.py`.

### D3 — For a piano soloist, `htdemucs_6s` is the wrong model

**Measured: 6-stem separation of a piano solo produces a quarter to a
twentieth of the notes.** The 6-stem model routes piano into its own `piano`
stem, so `other` — which is what every sidecar asks for — comes back nearly
empty when the soloist *is* the pianist. The 4-stem `htdemucs_ft` has no
piano stem, so its `other` keeps the piano and works.

| tune, piano soloist | `htdemucs_ft` / other | `htdemucs_6s` / other | `htdemucs_6s` / piano |
|---|---|---|---|
| Oleo (Red Garland) | 285 notes, F1 0.674 | 71 notes | 149 notes, no match |
| Gingerbread Boy (Hancock) | **1633 notes, F1 0.641** | 485 notes, no match | — |

Confirmed by controlled comparison: same audio, same span, same transcriber
settings, only the separation model changed — 485 notes and no match at all,
against 1633 notes and note F1 0.641.

Not a defect in the pipeline so much as a trap in choosing the stem, but it
cost a whole tune off the benchmark and it will do so again. **A piano
soloist wants `htdemucs_ft`.** Horn soloists are unaffected: Walkin' and
Yesterdays are both 6-stem and score 0.83.

### D4 — Octave errors on piano

**11 of Orbits' 18 pitch errors are exactly +12.** Small in absolute terms
(2.4% of the solo) but it is a systematic, nameable error rather than noise,
and it is the one error class a listener notices immediately.

### D5 — Notation: All The Things lags the other two on rhythm

Rhythm is 0.78 on two tunes and **0.620** on All The Things; note value sits
at 0.67-0.69 across all three. Both numbers roughly doubled once the two grid
bugs below were fixed, so what remains is no longer dominated by one cause.

Worth knowing before digging: at a SIXTEENTH-note tolerance rather than a
thirty-second, rhythm was already 0.92-0.94 before any of this work. The
disagreements are all one small unit — nobody is writing unreadable rhythm.

All The Things is also the tune whose beat grid the tracker warned about (58
octave-error outliers, stdev 30.1 bpm), which is the first thing to check.

### D6 — The plan's milestone numbering has drifted from CLAUDE.md's

The plan's table has M5 = "Quantize + Notate + Export" and M6 = "WJazzD eval
harness + pinned baselines"; CLAUDE.md has M5 = Quantize and M6 = Notate.
Both readings are now satisfied — quantize, notate, export and the eval
harness all exist — but the numbering should be reconciled before it is used
to decide what comes next.

### D7 — The notation score is not self-validating, and rhythm looks fine on the wrong tune

Measured 2026-08-25, building every notation the benchmark can from cached
notes and scoring it against every hand transcription on disk (16 pairings,
2 of them correct):

| pairing | coverage | rhythm |
|---|---|---|
| right (n=2) | 0.69 – 0.74 | 0.671 – 0.777 |
| wrong (n=14) | 0.16 – 0.36 | 0.077 – 0.583 |

**Coverage separates the two cleanly and rhythm does not.** A wrong pairing
scoring rhythm 0.583 is higher than All The Things scores against its own
correct score (0.618), because both sides are eighth-note bebop lines and
most gaps are half a quarter note on both. Anything reporting rhythm without
coverage can therefore be describing the wrong tune and look plausible — the
same class of failure as R1 and R2, caught this time before it cost anything.

`benchmark.COVERAGE_FLOOR = 0.5` sits in the gap; below it the GUI withholds
the numbers rather than showing them. What would move: more right pairings.
Two is thin, and the floor should be re-derived once there are more hand
transcriptions to check it against.

### D8 — Block-chord piano: we track an inner voice, an octave under the line

**Soul Station (Wynton Kelly) is the worst tune in the benchmark** — note F1
0.182, pitch F1 0.536 — and it is not a tempo problem (100 bpm) nor an
alignment one (grid 100.0 bpm against the score's implied 101.4).

The failure is **localised**, which is what distinguishes it from D1. Matches
by decile of the solo:

    0.81  0.86  0.71  0.38  0.91  0.76  0.19  0.05  0.24  0.45

Bar by bar, the cause is plain:

| bars | score melody | score chord tones | ours | score range | our range |
|---|---|---|---|---|---|
| 1-8 | 58 | 0 | 59 | 54-78 | 38-78 |
| 21-24 | 32 | 14 | 33 | 72-93 | 54-84 |
| **25-28** | **24** | **20** | **13** | **71-83** | **55-72** |
| 29-32 | 28 | 8 | 26 | 60-84 | 44-84 |

Kelly ends the solo in block chords. Where the texture thickens we produce
half the notes **an octave below the melody** — not missing the line, tracking
a different voice of the same chord. This score is 21% chord tones against the
Peterson's 10%, so it is the benchmark's first genuinely chordal piano solo.

It is also the clearest case for the top-N reading (docs/m7b-piano.md):

| | whole solo recall | bars 25-32 recall |
|---|---|---|
| our pipeline | 0.538 | 0.288 |
| oracle top-1 | 0.637 | 0.519 |
| oracle top-2 | 0.835 | 0.596 |
| oracle loudest-of-cluster | **0.722** (F1 0.537, ours 0.536) | — |

Loudest-of-cluster is the striking one: same F1 as what ships, with recall
0.538 → 0.722. Strictly more of the line on screen for the same amount of
deleting.

### D7 update — the coverage floor now has ten right pairings, not two

D7 set `COVERAGE_FLOOR = 0.5` from two correct pairings reading 0.69-0.74
against fourteen wrong ones at 0.16-0.36, and flagged two as thin evidence.
With ten:

| tune | coverage |
|---|---|
| Someday My Prince Will Come | 0.932 |
| For Minors Only (Art Pepper) | 0.917 |
| All The Things You Are | 0.912 |
| Confirmation | 0.865 |
| There Will Never Be Another You | 0.851 |
| Giant Steps | 0.742 |
| Lover Come Back To Me | 0.734 |
| Melody For C | 0.703 |
| For Minors Only (Carl Perkins) | 0.664 |
| **Soul Station** | **0.538** |

The floor survives — every correct pairing clears it — but the margin is far
thinner than two samples suggested. Soul Station is a *correct* pairing at
0.538, against wrong pairings reaching 0.36. Do not raise the floor on the
strength of the old two-sample range; there is now about 0.18 of daylight, and
it is the hardest tune that sits closest to the edge.

### D11 - The notater has no idea what tempo it is writing at

Over 456 WJazzD solos the median notated interval stays between 96 and 166 ms
at every tempo, while the note value it is written as steps sixteenth (under
120 bpm) to triplet eighth (120-160) to eighth (over 160). Regressing
log(interval in quarters) on log(tempo): slope 0.705, r = 0.690.

`choose_grid` and `grid_slack` know nothing about this. `grid_slack` is a
constant set by quantize's round-trip acceptance, and the M6 rule that it must
not be tuned on the notation score still stands - but a constant cannot be
right from 63 bpm to 340 bpm, and this is the table that says what it should
vary with. It predicts the observed failure directly: the only benchmark score
that produced thirty-second notes is at a tempo where WJazzD says the running
value is a sixteenth.

**First cut applied 2026-08-31: the slack is a time budget now.**
`grid_slack` (0.05 beats) became `grid_slack_s` (0.02 SECONDS), converted
per beat at that beat's own length — equal to the old value at 150 bpm, the
benchmark's centre of mass, and equal to plan §5's 20ms round-trip criterion
by construction. Measured over the fixed 12-solo subset (64-266 bpm),
against the trued-up sheet:

- notated rhythm up at BOTH ends: ballads +0.084 (Don't Blame Me, which
  also crossed BACK over the coverage floor, 0.475 → 0.550), +0.048, +0.003;
  fast bebop +0.010 to +0.032 (St Thomas, Oleo, Mr PC). Same-11-tracks mean
  0.633 → 0.645; one dip, Cheese Cake −0.004.
- tie rate DOWN precisely where D14's tempo trend predicted: Cheese Cake
  0.177 → 0.155, Mr PC 0.126 → 0.113, Oleo 0.124 → 0.105. The excess ties
  at speed really were too-fine grids splitting values.
- readability flat (0.9934 → 0.9925 mean), pitch F1 identical to 4 decimals
  (the control: quantize cannot touch hearing).
- real-audio round trip (replaying the notation, cached reviews): ballads
  IMPROVE (median 73 → 57ms — the finer grid captures more of what was
  played), burners pay ≤1ms median / ≤7ms p90. Synthetic acceptance sweep
  unchanged at 0.00ms.

Still open in D11: the candidate set itself is tempo-blind — `resolution`
caps the finest grid at a sixteenth, while under 100 bpm humans put 43.6%
of values BELOW the sixteenth. A ballad may want a 32nd-capable grid
(divisions 8) offered at all. Not yet tried.

### D12 - We write triplets at a quarter of the human rate — MOSTLY RESOLVED, and the frame was wrong

**Re-measured 2026-08-31, after D11.** The 0.9% was pre-D11: the current
exports carry **12.0%** tuplet notes over 66 wjazzd solos (r=0.579 against
each solo's own annotated ternary rate — the triplets land on the right
tunes). And the 23.9% target was never ours to hit: splitting WJazzD's
50,639 ternary-division notes by beat pattern, only **59.8% sit in
3+-onset beats** (real triplet figures); 20.2% are two onsets at tatums
{1,3}-of-3 — a swung pair annotated at triplet positions, which OUR
convention (and the listener's, and the Jazzomat lead sheets') writes as
two eighths — and the rest are 2-onset/1-onset beats no notation writes as
a tuplet. Convention-adjusted target ≈ 0.148; we write 0.120. A 1.2x gap,
not 4x.

**The warp-suppression mechanism was real and is fixed, with a neutral
outcome.** The swing warp is a hypothesis about BINARY beats; applied to a
genuine triplet it dragged the thirds off-lattice ({0,1/3,2/3} at BUR 2.5
reads {0,.23,.47} warped — near-perfect sixteenths). `choose_grid` now
scores the ternary candidate on RAW offsets, notates true thirds, and
stores the replay position as warp(k/3) so replay recovers the raw thirds
exactly and the residual-restore invariant is untouched (two new tests).
Measured on the subset: rhythm +0.002, tuplet rate flat, pitch identical —
because D11's larger fast-tempo slack was ALREADY letting ternary win
within-slack despite the distortion. Kept for correctness, reported as
neutral.

**What remains points the other way: the BALLADS over-write ternary.**
Don't Blame Me writes 41.6% tuplets against the annotator's 31%,
Embraceable You 44.3% against 19% — while the listener's own scores sit at
4.1% overall. At slow tempo the value set floors at a sixteenth (D11's
open half), so the triplet grid is the only fine option a busy beat has.
Offering a finer binary grid (divisions 8) where the beat is long is one
change that plausibly fixes ballad triplet over-writing, D11's remaining
readability gap, AND the under-100bpm coverage collapse together.

The original suspect — `choose_grid`'s rule that three onsets must be
present before a tuplet is allowed — was re-measured by implication and
STANDS: it is precisely what keeps the 40% of WJazzD's ternary notes that
are swing-pair annotation from flooding the page. Added in M6 for a good
reason (a warped offbeat lands near 0.6 and wins a triplet grid
on snap error alone) and now load-bearing for the convention
underneath it.

One structural fact that survives and constrains any fix: of 97,499 annotated
WJazzD beats, **zero** mix binary and ternary notes inside a single beat. The
per-beat exclusive grid choice is right, and the 2026-08-31 re-measurement
says the threshold is too.

### D13 - Two tracks hold three annotated solos, and the filenames say one

Content identification on the benchmark's own cached notes finds three
soloists inside `Miles_Davis_Dolores` (Miles 76.9%, Herbie Hancock 73.7%,
Wayne Shorter 64.6%) and two inside `Pat_Metheny_Nothing_Personal` (Metheny
88.7%, Michael Brecker 81.2%). The listener reports the same of The Sidewinder
(Lee Morgan and Joe Henderson).

`identify_all` handles this correctly and scores each solo over its own span,
and title-token matching means a filename naming one soloist does not hide the
others. But the filename is now the only human-readable record of what is in
the file, and it is wrong for at least three tracks. Nothing is mis-measured
today; this is a trap laid for the next person reading a scorecard.

### D14 - Our tie rate is 2-8x the human's, and nobody has looked

The readability measure reports it now, over thirty notations. Ours runs
**0.030 to 0.180** notes tied into the next; the ten hand transcriptions sit
at **0.022** (82 tie starts in 3646 notes, counted off the .mscz XML).

Some of that is legitimate -- a long note crossing a barline has to be tied.
Some of it is `split_for_meter`'s recursion fragmenting a value that should
have been one symbol, which is what the listener meant by "strange ties".

**Separated 2026-08-31, and the split is 58/42.** Classifying all 3,496 ties
across 66 wjazzd exports: 57.8% are WITHIN the bar (the suspect class),
42.2% cross barlines (mostly obligatory). Two supporting facts: the tie
rate rises monotonically with tempo (0.049 under 100 bpm to 0.160 over
280 — too-fine grids split values, and D11 already moved it 0.110 → 0.104),
and the biggest within-bar source was `_subdivide`'s rule that any value
crossing a division ties unless flush.

**First fix applied: the symmetric-syncopation allowance.** A plain binary
value that starts an odd multiple of half its own length into a HALVING
unit is centred on the division it crosses — a quarter on any "and" — and
every lead sheet writes it as one symbol. `_symmetric_syncopation` allows
exactly that; an uncentred crossing (a quarter off an offbeat sixteenth)
still ties, and triple metre is gated out (a unit dividing in three has no
symmetric middle; the waltz test still passes). Measured: subset tie rate
0.0945 → 0.0882 with rhythm, value, readability and pitch unchanged to 3-4
decimals; against the hand scores, Giant Steps ties 0.095 → 0.077 with
value +0.003, Confirmation 0.095 → 0.082 with value +0.004, All The Things
0.117 → 0.106 with rhythm +0.007. The 3/4 tune is untouched by design.

**Second fix applied: the dotted allowance.** A dotted binary value
starting on a multiple of its own dot-unit — the dotted quarter on beat
two; the charleston was already whole by flush — is the other figure every
chart writes untied. Subset ties 0.0882 → 0.0779, all other numbers
unchanged to four decimals; All The Things reads 0.106 → 0.073 against the
hand score.

**The barline class was then audited and its fix measured and REJECTED.**
The hand scores' own 82 ties split 57.3% barline / 42.7% within-bar — the
same shape as ours at a fifth the rate (their barline rate 0.0125, ours
0.041). Absorbing a sub-eighth tail that dribbles over a barline into
silence moved subset ties only 0.078 → 0.077 while readability and one
hand-score value dipped: the followed-by-silence guard rarely fires
(gap-filled durations run most barline ties straight into the next onset),
and a trim that does fire can mint the sub-eighth rest it meant to
prevent. The surviving barline ties are legato-into-the-next-note, where
cutting invents a rest the ear never heard. Reverted; the reasoning lives
beside `close_short_gaps` in notate.build.

Still open: triple metre (Someday holds at 0.178 — the 3/4 gate is
correct for the symmetric rule, so this needs its own convention), and
whatever remains of the within-bar class. Human target 0.022; we stand at
**0.077** (from 0.110 at the start of 2026-08-31).

Not folded into the readability composite on purpose: a page is not unreadable
for having a tie, so it is reported beside the score rather than inside it.

### D15 - `choose_grid` does not know that a beat is binary OR ternary, never both

**Zero of WJazzD's 97,499 annotated beats mix binary and ternary
subdivisions.** Every beat in 456 human-annotated solos commits to one grid.

`choose_grid` chooses per beat with no reference to its neighbours and no such
constraint, which is a strong free prior being thrown away. Likely related to
D12 (we under-write triplets 4x): a lone ternary onset in a run of ternary
beats currently has to clear the three-onset gate by itself.

### D16 - The benchmark cannot see the slow-tempo failure mode

Notating all 456 WJazzD solos from the annotators' own metrical positions, and
scoring the page for readability, gives a **monotone** relation with tempo:

        bpm      n   readability   rest<8th   note<16th    ties
       <100     59       0.5689       2.95      43.60%    0.248
    100-140     97       0.8518       2.71      13.78%    0.175
    140-200    138       0.9275       1.91       6.07%    0.151
    200-280    121       0.9728       1.58       1.34%    0.124
      >=280     41       0.9863       1.24       0.15%    0.109

At a slow tempo a human divides the beat far more finely -- `division` 8, 12
and up -- and 43.6% of the resulting values fall below the sixteenth that
`notate.WRITABLE_VALUES` floors at. A constant value floor is simply the wrong
shape across this range, which is D11 arriving from a third direction.

**But our own numbers show no tempo trend at all**: mean notated rhythm reads
0.615 below 145 bpm (n=7) and 0.565 at or above it (n=13). That is not evidence
that we are fine at slow tempos. It is evidence that we cannot tell, because
**exactly one of the twenty benchmarked solos is under 100 bpm** (Charlie
Parker's Don't Blame Me, 64 bpm) -- and its WJazzD-derived score is the worst
readability of everything generated, 0.331, while our own notation of it reads
1.000. A page can be perfectly writable and still be the wrong page.

The benchmark is bebop at 125-286 bpm. That is exactly the regime a fixed grid
handles well. Adding two or three ballads is the cheapest way to make the
existing measures able to fail.

### D10 — So What: right recording, right places, wrong notes

The only one of the nine new WJazzD tracks that did not score. `identify_all`
withheld it at a best candidate of **14.0%** against the 15% floor, so the
guard did its job — but the diagnosis is worth keeping, because it is NOT the
take-matching failure that floor exists to catch.

All three annotated soloists lock on at musically correct, correctly ordered
offsets, and our note density inside each located window matches theirs almost
exactly:

| soloist | window | theirs | ours |
|---|---|---|---|
| Miles Davis | 91.7-204.4s | 221 (2.0/s) | 255 (2.3/s) |
| John Coltrane | 207.1-315.0s | 479 (4.4/s) | 478 (4.4/s) |
| Cannonball Adderley | 317.6-422.9s | 445 (4.2/s) | 464 (4.4/s) |

So it is the right recording, and we are producing the right *number* of notes
in the right *places*. Only 10-14% of them are the right note.

Ruled out: a wrong issue (the measured rate is 1.004-1.008, and rate is fitted
anyway) and a tuning offset (+0 semitones beats every shift from -4 to +4;
+1 halves the match rate). What is left is the transcription itself. So What is
the hardest texture in the set — a modal tune at a quiet dynamic, 1959 Columbia
balance, Miles muted and distant, and Bill Evans comping continuously under
everything. A monophonic tracker in that texture produces a plausible stream of
the wrong voice, which is exactly what these numbers look like.

Untried: a different stem, and whether the `other` stem of `htdemucs_6s` is
actually holding the horns alone here.

**Overturned by D19.** The "measured rate of 1.004-1.008" that ruled out a
wrong issue was itself pinned at `fit_affine`'s clamp ceiling; the true rate
is +2.26% and the notes were right all along, read against a drifting clock.

### D9 — Metheny's guitar line notates worst of anything measured

`Nothing Personal` (Pat Metheny, 242 bpm) is heard well — WJazzD note F1
**0.873**, third best of twenty — and notated worse than anything else:
**rhythm 0.254** against WJazzD's metrical annotation, at coverage 0.744 so
the pairing is sound. Every other trusted solo is 0.44 to 0.72.

Hearing the notes and writing them are separate failures, and this is the
cleanest example yet of the second without the first. It is also the only
guitar in the set. Unexamined.

### D17 - `fit_affine` can lose to a brute-force offset scan by 10x

Found while diagnosing R16. On Miles' Oleo transcribed from `htdemucs`'s
`other` stem — a deliberately bad input, the trumpet buried under the piano
that the 4-source model has nowhere else to put — a plain scan of offsets at
rate 1.0 finds **81 of 224** reference notes at offset 26.895, and
`fit_affine` returns offset **71.426** with **8**. `htdemucs_ft`'s `other`
does the same thing. Both are then rejected by `identify_all` as "wrong take
or wrong issue" at 3.6%.

The head/tail anchors each search the full overlap range independently
(`wjazz.py:99-106`), so a noisy estimate lets one of them win at a spurious
offset; the derived rate is then nonsense and the joint refinement only
searches ±0.15s around it. It never recovers.

This did not corrupt any shipped number — the affected pairings are *rejected*
rather than mis-scored, which is the identifier working. But it is the third
fitting bug in this harness and the failure is silent in the direction that
matters: a configuration that transcribes BETTER can be reported as
unidentifiable. A cheap guard would be to keep the rate-1.0 scan's best as a
floor and take it whenever the anchored fit scores worse.

### D18 - Twelve groups of benchmark tracks are byte-identical, and identity is content

`benchmark/wjazzd/` holds **12 groups of files that are the same bytes under
different names**, because one recording carries several annotated solos and
each gets its own sidecar. Oleo is a group of three:

```
1f42971d638d5685  John_Coltrane_Oleo_solo_231.m4a
                  Miles_Davis_Oleo_solo_320.m4a
                  Red_Garland_Oleo_solo_365.m4a
```

The others are pairs: Maiden Voyage, Speak No Evil, Orbits, Blues In The
Closet, Crazy Rhythm, Walkin', In 'n Out, The Sidewinder, Totem Pole, Blue
Train, Dolores. This is D13 from the other side — there the filename
under-reports what is inside one file, here several filenames *are* one file.

Everything keyed by content therefore collides, by design and correctly: one
separation and one beat grid serve all three Oleos, which is the caching
scheme working. What collides *incorrectly* is anything that means "which
track is this":

- **`Document.audio_path` used to come back from the cache**, naming whichever
  file those bytes were first ingested under. Fixed in `pipeline._for_path`;
  the symptom is written up below.
- **`library.file_digest` is `sha256(bytes)[:16]`, so all three Oleos share one
  track id.** `recents.json` holds a single entry for `1f42971d638d5685`, and
  `resolve()` returns whichever was opened last. Open Coltrane's Oleo and a
  still-open Miles page resolves to Coltrane's document. **Not fixed** — it
  needs the path folded into the identity, or a recents index keyed on both.
  Per-track judgements are safe: `load_settings` prefers the path-based
  sidecar and all three have one on disk.

The trap is that the loud failure and the silent one look nothing alike. The
two caches on this machine held both at once for the same audio:

| cache | cached `audio_path` | result |
|---|---|---|
| `.swingscribe-cache` | `04 Oleo.m4a` (renamed away) | `FileNotFoundError` |
| `benchmark/.swingscribe-cache` | `John_Coltrane_Oleo_solo_231.m4a` | proceeds as the wrong soloist |

Prefer the loud one. A benchmark number attributed to the wrong soloist is
exactly the class of error this document exists to catch.

### D19 - `fit_affine`'s rate clamp (±0.6%) is narrower than a real speed fault

Found 2026-08-31, diagnosing why the batch reported Cannonball's So What
(melid 48) as "wrong file/take" at 10% matched while the GUI's Score It
lined up 358 of 445 notes on the same audio. The disagreement is the usual
one in a new place: Score It aligns time-free (pitch sequence, no clock),
`fit_affine` is a clock fit — and only the clock fit broke.

The copy of So What in `benchmark/wjazzd/` plays **2.26% slower** than the
copy WJazzD annotated — the well-known *Kind of Blue* side-1 speed fault
(ours is the in-tune copy; theirs runs ~39 cents sharp). `fit_affine`'s
two-anchor machinery derives a rate of 1.02305, within 0.05% of the truth —
and `wjazz.py:113` clamps it into `[RATE_LOW, RATE_HIGH] = [0.994, 1.006]`.
Held at +0.6% against a true +2.26%, the reference drifts ~1.7 s across the
solo, only chance hits survive, and 10% falls under `MIN_MATCH_RATE = 0.15`.

Measured, all on cached transcriptions:

| fit | rate | matched |
|---|---|---|
| shipped `fit_affine` (clamped) | 1.0060 (the clamp ceiling) | 46/445 = **10%** |
| same code, clamp lifted | 1.0224 | 363/445 = **82%** |
| 2-D scan over the listener's hand-drawn span | 1.02260 | 372/445 = **84%** |

84% is the top of the range this project sees, and the located span
(317.5-424.8 s) lands within a second of the hand-drawn one (316.6-426.2 s).

**The control is already done.** The same free-rate fit over the sheet's six
other "wrong file/take" rows (Ornithology 61, Crazy Rhythm 399, Dolores 427,
Orbits 434, Cherokee 446/447) stays at chance — 1.5-6.9% — so freeing the
rate does not manufacture agreement; `MIN_MATCH_RATE` keeps doing the actual
gatekeeping. (The two Cherokees also look badly under-transcribed — 377 and
280 notes against 679 and 655 reference — which is its own thread.)

This overturns D10 (noted there): all three So What soloists were right
notes against a drifting clock, not wrong notes — and the same bytes carry
Miles' and Coltrane's solos (D18), so one speed fault took out three rows.

**The silent half, unmeasured:** a pairing whose true rate sits outside the
clamp but which still clears the 15% floor gets *scored*, with a drifting
reference depressing `pitch_*` and misplacing the located span, and no error
anywhere. Any row whose fitted rate sits AT 0.994 or 1.006 is suspect — the
clamp boundary is a confession. The sheet does not currently record the
fitted rate; a `fit_rate` column would make this auditable at a glance.

**Applied 2026-08-30**: `RATE_LOW`/`RATE_HIGH` widened to 0.97/1.03, and
`_centre` now refines BOTH parameters by least squares over the matched
pairs — at ±3% the plateau is wide enough in rate that offset-only centring
left the fit a step or two wide, 33ms of placement error at the ends of a
60s solo (caught by the new `test_recovers_a_mastering_speed_fault`).

Re-measured on the real audio: So What (48) fits rate 1.02244, 82% matched,
and scores pitch F1 **0.861** / notation rhythm **0.638 at coverage 0.829**
where the sheet said "wrong file/take". The batch records `fit_rate` per row
now, written before the match-rate gate so rejected rows show the rate they
were rejected at.

**The silent half existed but was benign — measured, not assumed.** An
audit over every cached pass-1 transcription (free-rate fit, no CREPE)
found six scored rows outside the old clamp: Donna Lee 55 at 0.9929,
Embraceable You 56 at 1.0076, Long Ago and Far Away 73 at **0.9887**, Sandu
94 at 1.0070, JJ's Walkin' 196 at 0.9935, St Thomas 385 at **0.9915**. All
six re-run with the free rate moved at noise level, in both directions
(mean rhythm over the six 0.669 → 0.664; pitch F1 within ±0.010). The
paragraph above predicted depressed `pitch_*`, and that was wrong: both
scoring measures are TIME-FREE aligners, so the fit's clock only places the
span — a sub-1% drift moves the span edges by well under the 1s margin.
The clamp does real damage only when drift pushes the match below the 15%
floor and the row is not scored at all, which is exactly So What.

Every known-wrong pairing stays below the 15% floor with the clamp wide
(1.2-4.6%), confirming the control on the full set. Wrong-take fits now
wander toward the new clamp edges (Cherokee II lands AT 0.97), which is
expected — a failed fit buys the most chance agreement at maximum drift —
and harmless, because the floor is what gatekeeps.

**`run_eval` after the change (2026-08-30, full folder trued up):** the
only summary movements are n going 20 → 21 (So What joins) and the means
riding it — wjazz note F1 0.8095 → 0.8175, beat F1 0.940 → 0.956. The
MuseScore means did not move (note F1 0.447 = the pinned 0.4472). No
same-key per-track value moved at all; the ~670 remaining diff lines are
rename churn — the pins predate the `_solo_NNN` renaming (last pinned
e9968c9, 2026-08-27), so every old key reads "gone" and every current key
"new". Rename-aware, the 13 tracks present under both names moved -0.020
to +0.024 (mean +0.003): located-span jitter, not a regression. Not
re-pinned yet — the pin should happen once, under the new names, with the
listener told n changed and why.

### D20 - The two GUI measures disagree about which notes exist — RESOLVED: both are right, and it is now policy

**The listener ruled 2026-08-31: `pitch_*` scores the RAW transcription,
erasures deliberately NOT applied.** "I should always get the same score
regardless if a human came in later and silenced some of the invented
notes — the transcription included a note that shouldn't have been
included, and that is a shortcoming in the transcriber." So the
`/ground-truth` endpoint's behaviour is the criterion, not a bug, and the
disagreement between the two measures is a DISTINCTION: `pitch_*` judges
the transcriber's raw output; `notation_*` judges the exported page, which
applies erasures because the page the listener keeps applies them.
Anything that "fixes" either endpoint to match the other is reverting a
decision.

**And a ceiling is on the record.** The listener, on the ghost-note
finding: any two transcribers write these lines differently — one adds a
ghost note, one a scoop, one omits it — and the same transcriber differs
across days; a perfect score against a single reference is not attainable,
and the penalty for a real-but-unnotated note is accepted. The reference
itself can also simply be wrong: transcribers make mistakes, so some
penalties are charged to the software for being right. Both effects bound
every reference-based number in this project from above, which is one more
reason the reference-free readability measure exists.

Found 2026-08-31 by classifying Confirmation's invented notes: a direct
`ground_truth.overlay` over the AUDIBLE notes read invented=156 where the
sheet said 214, and the difference is exactly the listener's erasures.
`/api/tracks/{id}/notation-score` resolves erasures before scoring (the
exported page does, so its score must); `/api/tracks/{id}/ground-truth`
aligns the RAW review notes, so the green bar — and the batch's `pitch_*`
columns — charge notes the listener already silenced as invented or wrong.
On Confirmation (60 silenced) that costs ~0.03 of reported pitch F1
(0.759 shown vs 0.790 audible-only).

The question was put to the listener and answered above: raw for
`pitch_*`, audible for `notation_*`, both on purpose. The batch scripts'
column documentation says so, per next-session-prompt's rule that the
sheet always reports the criteria in force.

Separately, the classification itself: Confirmation's invented notes are
NOT junk — median confidence 0.781 (matched: 0.853, wrong: 0.701), median
100ms, interleaved between matched notes (median 150ms to the nearest),
and only 17 of 156 are unisons/octaves of a neighbour. They read as ghost
notes and passing tones a human deliberately leaves off the page, which is
a notation-philosophy gap, not a detector fault — and the measured floors
(duration near-random, confidence 0.65 costing 7% of kept notes) already
say no threshold removes them cleanly.

### D21 - A sibling-solo copy can name a solo the excerpt does not hold

The 2026-08-31 sibling copies assumed that a second melid on the same
trackid lives inside the same excerpt. Two do not, and their rows are the
sheet's two strangest numbers:

- **Kenny Garrett 257** annotates 103s of playing where 256 annotates 85s
  — the listener's excerpt covers part of 257's window, and the partial
  overlap scores rhythm 0.277 at coverage 0.602 (the sheet's worst trusted
  rhythm by 0.13).
- **John Coltrane 228** is My Favorite Things' SECOND solo section, 723
  notes against 227's 743. This entry first claimed the excerpt held only
  the first; **that was wrong**. The file is the whole 13.7-minute track,
  and on 2026-09-01 the batch's locate placed 228 at offset +596.5 s with
  45% of its notes matched in time and pitch — a wrong pairing scores
  under 10%. What is true is that it scores badly there: pitch F1 0.601 at
  coverage 0.472 (rhythm untrusted). `other` cleared the locate gate so
  `guitar` was never tried, and the whole-file energies (guitar 1.6x
  `other`) say the soprano is split between them — the composite-stem
  case (docs/separation-research.md item 0), not a copy error.

The Garrett row stays as described; the general lesson for future copies
stands: check the sibling's annotated DURATION against the excerpt before
assuming containment — `select max(onset) from melody` is one line — and
then let the LOCATE say where it is before concluding it is not there.

### D22 - Bleed inside the lead stem, rejected by the line's own register and loudness

2026-09-01. Ornithology, transcribed from the `guitar` stem htdemucs_6s put
Bird in, read pitch F1 0.802 with 34 invented notes. They were piano
comping — but INSIDE the same stem: at those pitches and times the piano,
bass and `other` stems held nothing (harmonic-energy ratio 0.000 at the
median), so no cross-stem test could see them, and the piano oracle used
as a chord witness separated nothing either (drop-when-≥3-sounding removes
8 of 34 invented against 26 of 150 matched). What did separate them was
the line itself: the invented notes sit a median 8.5 semitones below the
line's local median pitch (p25: 12 below; matched notes' p10 is 7 below)
and a median 4.5 dB under its local loudness (p25: 9.7 dB; matched p10 is
4.4 dB). Confidence separates them worse than either.

Measured before anything shipped, over a per-note table of the 12-solo
subset, Ornithology, and all ten hand scores (23 tracks, labels from a
50 ms time+pitch match through `fit_affine` for WJazzD and from the
aligner's path for the hand scores), scored with the green bar's own
aligner:

| rule | WJazzD ΔF1 (13) | hand ΔF1 (10) | worst track | tracks hurt |
|---|---|---|---|---|
| loudness < local median − 12 dB | +0.024 | +0.009 | −0.012 (Carl Perkins, piano) | 1 |
| pitch < local median − 12 | +0.003 | +0.014 | −0.002 | 0 |
| either | **+0.026** | **+0.021** | −0.002 | 0 |

The register floor lifts every PIANO solo (+0.019 to +0.033: it removes
left-hand notes) and the loudness floor hurts one pianist (soft notes are
notes), so the loudness test is horn-only. The surface is flat over
windows of 1.5-3 s and floors of 10-16 on both axes
(`TranscribeConfig.line_*`, `transcribe.reject_line_outliers`).

**Measured at 12 dB / 12 semitones** — through the batch, fresh CREPE,
against the trued-up sheet. The fixed subset (n=12): mean pitch F1
**0.854 → 0.880**, every track up (+0.007 Mr PC to +0.055 There Will
Never Be Another You); trusted rhythm **0.694 → 0.701** over the same
12, up on 10; trusted count 12 → 12. The ten hand scores: mean pitch F1
**0.793 → 0.815**, every track up (+0.010 to +0.038); trusted rhythm
**0.746 → 0.732**, down on 8 of 10, with coverage down on six (Art Pepper
0.924 → 0.889 the largest); trusted count 10 → 10.

That rhythm/coverage cost is real notes going with the bleed. Art
Pepper's 15 removed notes were 7 invented, 1 wrong and **7 matched** —
in-register, so the LOUDNESS floor took them: ghosted notes inside a
phrase that the hand transcriber wrote. Over all 18 horn tracks the
loudness floor's take is 391 bleed against 91 real at 12 dB, 333/61 at
14, 280/42 at 16, 195/15 at 20; an isolation gate (only reject quiet
notes with a gap on both sides) does not change the ratio, because bleed
sits as close to other notes as a ghost note does. **14 dB ships**: nearly
all of the pitch gain (table: WJazzD +0.024 against +0.026), no track's
F1 down on the table, a third fewer real notes lost. Re-measured through
the batch at that setting: **shipped numbers, 14 dB / 12 semitones** —
subset (n=12) mean pitch F1 **0.854 → 0.878**, trusted rhythm **0.694 →
0.696** (n=12, up on 8), trusted 12 → 12, coverage held within 0.01 on
ten; hand scores (n=10) mean pitch F1 **0.793 → 0.814**, every track up,
trusted rhythm **0.746 → 0.733** (n=10), trusted 10 → 10. Art Pepper is
the one page that lost coverage (0.924 → 0.896).

The rhythm dip on the hand scores is NOT mostly lost notes, and the
pianos prove it: they get the register floor only, their coverage is
unchanged to the third decimal (Melody for C 0.802, Soul Station 0.585,
Giant Steps 0.810), and their rhythm still drops 0.004-0.015. Same
matched notes, different positions on the page — removing a left-hand or
comping note from a beat leaves `choose_grid` fewer onsets and it picks a
coarser grid, moving the notes that remain. The bleed had been propping
up the grid choice. That is a quantize question (D11's territory: the
grid chooser is coarsest-within-slack), not a reason to keep bleed, and
it is on the record here so nobody reads the rhythm dip as the floors
removing real notes. Costs either way: every review key changes (a CREPE
pass per track on the next true-up), and the real-audio baselines move
and need re-pinning.

### D23 - The batch's "wrong take" verdict was a stem-routing verdict

2026-09-01. The listener ear-checked Ornithology (melid 61), which the
batch had flagged as `best fit only matched 5% — wrong file/take?`, and
found it 100% the right tune; transcribed by hand in the GUI from the
`guitar` stem it lines up 152 of 194 notes. It is the right TAKE too: the
same fit against that review lands at offset +37.12 s, rate 1.0008, 78%
matched, with the rate clamp opened to ±20% changing nothing.

The batch never looked there. Its locate pass was hard-wired to `other`,
and htdemucs_6s had filed Bird under `guitar`: in-span RMS 0.123 against
`other`'s 0.004, with `other` digitally silent for 30.7% of the solo. R16
described exactly this switching for Oleo's muted trumpet (`vocals`), and
the fix there — `library.choose_stem` — runs AFTER the solo is located, so
it could not help a locate that had already failed on the wrong stem.

Whole-file stem energies for every other flagged row say the same thing
is likely: Marsalis' two Cherokees (446, 447) have `vocals` at 1.6x and 8x
`other`; Getz's Crazy Rhythm (399) and Coltrane's My Favorite Things (228)
have `guitar` at 2x and 1.6x; Shorter's Dolores and Orbits (427, 434) have
`other` a third digital silence whole-file. None of those numbers proves a
solo is THERE — energy cannot tell quiet bleed from a soloist — which is
why the locate itself is what has to look.

**Applied**: pass 1 now tries `LOCATE_STEM_ORDER` (`other`, `guitar`,
`vocals`, `piano`) in that fixed order and takes the FIRST stem in which
the solo clears `MIN_MATCH_RATE`; pass 2 then prefers that stem. This is
the one place a reference steers a stem choice, and it is a found/not-found
gate, never a best-of-N: a later stem matching more cannot displace an
earlier one that cleared the floor, so no sheet number is the best of
several tries. The rows above are queued for a re-run; whatever still
fails after it is a wrong take in the sense the status claims.

## Resolved

### R18 - A cached Document named a file that had been renamed away

The GUI's Score button on Miles' Oleo failed with

```
could not score against Miles_Davis_Oleo_solo_320.musicxml:
[Errno 2] No such file or directory: '...\benchmark\04 Oleo.m4a'
```

and the message named the one file that was fine. `04 Oleo.m4a` was this audio
before it was refiled under WJazzD naming; the ingest entry keyed by its
content still carried the old path, because a cache key is content plus config
and the cached payload is a whole `Document` with `audio_path` inside it. A
hit restored the name along with the data.

`beat_times` then re-derived a cache key from `document.audio_path` rather than
the path it had been handed (`gui/musicxml.py`), and read a file that no longer
existed. Export was broken the same way; `stages/export.py` takes its part name
from the same field, so a pipeline export would have titled the part `04 Oleo`.

**This bug had already been found once and fixed in one caller.**
`scripts/wjazz_batch.py` carried a `run_pipeline` wrapper whose docstring
diagnosed it precisely — naming `beat_times` and the byte-identical Dolores
pair — while the GUI, which had the same bug, had no such wrapper. The fix
belongs where the invariant is: `pipeline._for_path` stamps the caller's path
onto every Document loaded from cache, and the wrapper is gone. Stamping
invalidates nothing, because the path reaches no key — no separation and no
CREPE was recomputed, and stale entries heal on next read.

The misleading message is fixed too: an unreadable audio path now returns 404
naming the audio, instead of a 422 blaming the score.

### R16 - Demucs switched a soloist between stems, and half a solo went missing

**The `other` stem was bit-zero for 29.8% of Miles Davis' Oleo (melid 320),
and the GUI drew an empty piano roll over it.** Reported as "no notes at all,
transcribed or ground truth, from 1.3 to 6.5 seconds".

Demucs assigns each moment to exactly ONE source, so an instrument it cannot
place consistently is not attenuated across the stems — it is *switched*
between them, leaving digital silence behind. On this recording the muted
trumpet is routed to `vocals` for 17 of the solo's 58 seconds. The energy gate
correctly dropped those frames (RMS 0.000026 against a 0.000971 floor), CREPE's
confident garbage over the silence was correctly discarded, and the result was
106 notes where WJazzD annotates 224.

Every layer behaved as designed, which is why nothing reported an error. The
ground-truth overlay then appeared broken as a *consequence*: with the notes
gone there was nothing under that region to align a score against.

Measured across every horn track in `benchmark/`, Oleo is alone — every other
reads <=3.8% silence in-span and a vocals/other energy ratio <=0.18, against
Oleo's 29.8% and 0.81. So this is one recording's separation failure, not a
systemic one.

`library.resolve_stem` now materialises the SUM of two stems on demand
(`other+vocals`), written beside them under the same content digest and offered
by the stem menu. On this solo:

     stem                    notes   note F1   P       R
     6s/other (was)            106     0.497   0.774   0.366
     6s/vocals                 174     0.638   0.730   0.567
     ft/vocals                 177     0.708   0.802   0.634
     6s/other+vocals (now)     237     0.824   0.802   0.848

Ground truth: 197 of 224 matched, 14 missed, pitch F1 0.855.

**It is offered, not selected.** The sum carries the other stem's bleed with
it, so it costs precision wherever the separation was already clean — which is
everywhere else in the benchmark. A separated stem still resolves to exactly
the path `available_stems` gives, so no review key already computed moved.

### R17 - A `missed` note placed outside the span was drawn nowhere

Found by asking the right follow-up question about R16: *why did the notated
score not show those notes as `missed`?* It should have — and the payload did
contain all 224 of them. They were placed off the edge of the view.

Score position is derived from the alignment, extrapolating off the outermost
anchor pair beyond them (`ground_truth._place`). With half the line missing the
aligner anchored nothing in the opening, so bars 1-7 were extrapolated backwards
and landed at **x = 24.2-27.9s against a span starting at 29.717** — outside the
region the roll draws. 24 reference notes were affected. Nothing reported it.

An invisible note is indistinguishable from one the score does not contain, and
`missed` is the single most important class on this view: it is the one the
transcriber owes an explanation for. So the failure was in the worst possible
direction — it hid exactly the evidence that would have pointed at R16.

A note landing outside the span is now pinned to the edge it left by and
counted (`score.off_span`), and the GUI says so beside the drift figure. A
pinned x is not a claim about time — nothing on this view is — it is a claim
that the score holds a note the alignment could not place. On the two Oleo
transcriptions:

     stem                 our notes   off_span   missed   pitch F1
     other (was)                106         24      127      0.527
     other+vocals (now)         237          0       14      0.855

`overlay_key` gained a `CACHE_VERSION`, because it hashes both sides' CONTENT
and neither can see a change to placement itself — a stored overlay would
otherwise outlive the code that made it.

### R15 - The notes cache did not know which transcriber wrote it

`run_eval`'s note cache is keyed by track name, in a file whose name carries
the two decode settings the sweep varies (`step_cost`, `dip_db`). Nothing else
about the transcriber entered the key. A cached entry was reused whenever the
sidecar's `ensemble` still matched.

So a change to the STAGE was invisible to it. The piano gap-fill (M7b) added a
step that changes the note list with no config change the cache could see, and
the first run after it re-transcribed exactly ONE track of the nine piano
solos - the one whose `ensemble` the listener had just edited. The other eight
were scored with notes computed before the feature existed, and the scorecard
gave no sign.

This is precisely the staleness hole the pipeline's chained keys exist to
close (CLAUDE.md section 3), reintroduced in the harness because this cache is
keyed by filename rather than by content. The fix mirrors
`pipeline._cache_name`: `transcribe_fingerprint` hashes the whole resolved
`TranscribeConfig` plus the stage's `CACHE_VERSION`, canonicalised the same
way, and an entry without a fingerprint is treated as unknown provenance and
recomputed once.

`transcribe_settings` is now the single definition of what the transcriber is
asked for, used both to fingerprint a cached run and to compute a fresh one,
so the two cannot drift apart - which is how the `ensemble` check that
preceded it managed to cover one field and miss the rest.

### R14 - Renaming eight tracks scored all eight twice

The notes cache is keyed by track name and only ever added to; nothing pruned
an entry whose track was gone. Everything downstream iterates those keys
rather than the sidecars, so after the listener's tracks were renamed, each
one was scored under BOTH names with identical numbers, and
`summary/wjazz_note_f1` was reported as a mean over 32 where the truth was a
mean over 20. `1-17 Star Eyes.m4a` had no audio at all and had been scored
from a cache entry for an unknown length of time.

Same family as R8 (a mean over 4 printed beside a mean over 11) and R11b (two
of three globs made recursive), with the sign flipped: a silent SUPERSET
rather than a silent subset. `transcribe_all` now returns only runs whose
track is on disk, and says how many it ignored. The orphans stay in the cache
FILE - they cost minutes of CREPE each and come straight back if a rename is
reverted - they simply are not scored.

Both of these are now pinned by `tests/test_eval_harness.py`, which is the
third time that file has grown a guard for this class of bug. The lesson it
keeps teaching: **a harness that decides what to score deserves the same tests
as the code it scores.**

### R13 — The WJazzD notation scores were measuring the aligner, not the notation

First run of the new WJazzD notation benchmark read mean rhythm 0.533 with
nine of twenty pairings below the coverage floor — including Clifford Brown's
George's Dilemma at coverage 0.517 while its note F1 was 0.914. Hearing 91% of
the notes and lining up 52% of the notation is not a coherent pair of numbers,
and the incoherence was the tell.

The cause: a WJazzD track's sidecar covers the WHOLE TRACK, because the solo's
position is not known in advance (that is what `identify_all` is for). So we
notated five minutes — head, every other soloist — and handed a **global**
aligner 450 reference notes against ~1500 of ours. `alignment.align` is global
on purpose, because both sides are meant to cover the same span of music; here
they did not.

Fixed by notating only the located solo: `identify_all` already returns the
offset and rate that place the annotation in our timeline, so the window is
free. Notes are cut to it as well as the beat grid.

| | before | after |
|---|---|---|
| George's Dilemma | 0.517 / 0.318 | **0.895 / 0.718** |
| Joy Spring | 0.426 / 0.359 | **0.877 / 0.717** |
| Sandu | 0.627 / 0.522 | **0.886 / 0.651** |
| Gingerbread Boy | 0.137 / 0.417 | **0.645 / 0.546** |
| trusted pairings | 11 of 20 | **19 of 20** |
| mean rhythm | 0.533 | **0.581** |

Fourth bug of this shape (R1, R2, R12): a measurement failure that reads as a
transcription failure. The control that caught it was the same one as always —
a number that disagreed with another number about the same music.

### R11b — A silent subset, again: two of three sidecar globs

`benchmark/` grew subfolders and `transcribe_all` and `discover_tunes` were
made recursive. `beat_grids` was not. Every track under `benchmark/wjazzd/`
therefore got no beat grid, which silently cost them **both** their beat score
and their notation score — `wjazz_beat_f1` stayed a mean over 11 beside a note
F1 over 20, which is precisely the R8 failure the function's own docstring
warns about, reintroduced three lines above it.

`tests/test_eval_harness.py` now guards discovery, including a structural check
that no sidecar walk in either script uses a flat glob. The scripts had no
tests at all before this.



### R12 — 8va/8vb in the hand transcriptions was read as an octave error

**MuseScore 4 stores the WRITTEN pitch under an ottava**, and carries the
octave in a separate `<Spanner type="Ottava">`. `mscz.parse` ignored the
spanner, so every note under an 8va or 8vb came out an octave from what the
score says — a ground-truth bug, charging the transcriber for an octave the
score never claimed. It is the third bug of this shape (see R1, R2): a
measurement failure reported as a transcription failure.

Writing a high passage 8va to keep it on the staff is ordinary notation. The
listener flagged it as expected behaviour on their side, which it is; the
defect was entirely in the reader.

**Measured, not assumed.** Two cheap heuristics disagreed and both were
inconclusive — boundary melodic intervals said "sounding", the mid-staff
pitch range of every ottava'd passage said "written". The recording settled
it. Aligning the Peterson solo against our transcription of the same audio:

| reading | notes under the 8vb that match |
|---|---|
| as stored | 1 / 11 |
| +12 | 0 / 11 |
| **-12 (the 8vb applied)** | **10 / 11** |

Lover Come Back To Me `pitch_f1` 0.7104 → 0.7301 from this alone.

The span is half-open: MuseScore's own declared length (`measures=1,
fractions=-3/4` = one quarter) covers two eighths, not three, so a note at
the end marker's tick is already outside.

Affects 58 notes across 5 of the 10 hand transcriptions — ~10% of the line on
the Wynton Kelly and Carl Perkins solos, 3.3% overall.

**Where the evidence is thinner.** The decisive test is the Peterson 8vb, and
it was re-run against the polyphonic piano model rather than our own
transcription after noticing that the first test was nearly circular: CREPE's
octave errors are the very failure being adjudicated, so agreeing with CREPE
could have meant agreeing with our own mistake. Independently, the oracle
matches the shifted pitches 100% and the written ones 55%.

Soul Station's three 8va spans do **not** replicate that cleanly (oracle
agreement 50/62/70% written against 50/50/80% shifted). They are 20 notes in
bars 20-23, inside the stretch where that solo fails for an unrelated reason
(D8), so they are a poor test bed rather than counter-evidence. The reading is
kept because the file format cannot store 8va and 8vb by different rules, the
Peterson case is unambiguous, and the musical argument only points one way: an
ottava exists to bring notes that are off the staff back onto it, so a stored
pitch sitting mid-staff under an 8va must be the written one.

### R11 — Seven hand transcriptions sat unmeasured behind a hand-maintained table

`score_benchmark.TUNES` was a literal dict pairing audio to `.mscz`. The GUI
already records the chosen score in the sidecar beside the audio, so the table
was duplicating information the app writes — and duplication of exactly the
kind CLAUDE.md warns about, because the failure is silent: seven scores were
added to `benchmark/` and the benchmark went on reporting a mean over four.

`TUNES` is now derived from the sidecars. A score the listener picks in the
app is benchmarked by virtue of having been picked. The benchmark went from
4 tunes (2 piano) to 10 (6 piano) with no new pairing code.

Related routing bug found at the same time: three of the four new piano solos
had `ensemble: null`, so they defaulted to horn-led and never consulted the
piano oracle — the M7b work worth +0.05 to +0.07 note F1 on piano. Unset is
not the same as chosen, and nothing was warning about it.


### R10 — Piano precision was being charged for notes that are not errors

The hand transcriptions notate the **right hand only**. So one of our notes
being absent from the score means either "we invented it" or "it happened and
nobody asked for it", and D1/D4 were reading both as the first.

Telling them apart needs no ground truth, only a second detector. CREPE and a
polyphonic piano model are independent in features, architecture and failure
mode. Validated against the listener's own erasures, which split cleanly:

| solo | erased notes the piano model also heard | median pitch vs kept |
|---|---|---|
| Orbits | **0%** | −17 semitones |
| Oleo | 10% | −0.5 |
| Giant Steps | 65% | −10 |
| Lover Come Back | **90%** | −4.5 |

Orbits is the surprise and the clearest case: the deleted notes sit seventeen
semitones below the melody and the piano model reports **none** of them,
because CREPE is tracking the **double bass** through the `other` stem's
bleed and a piano model correctly declines to call that a piano. The listener
deleted them by ear; an independent detector agrees, with no score involved.

Lover Come Back is the opposite and equally clear: 90% corroborated. Those are
Peterson's left hand — real, and out of scope.

Fixed by `src/swingscribe/corroborate.py`, two operations kept separate
because they do different things: `snap_octaves` moves a note to the oracle's
octave where the two agree on pitch class (raises RECALL, and is the direct
fix for D4), then `corroborate` drops what the oracle will not vouch for
(raises PRECISION). Every piano solo improved on **both** benchmarks and on
**both** halves of F1:

| solo | | before | after |
|---|---|---|---|
| Orbits | WJazzD note F1 | 0.828 | **0.895** |
| Gingerbread Boy | WJazzD note F1 | 0.641 | **0.715** |
| Oleo | WJazzD note F1 | 0.674 | **0.710** |
| Giant Steps | notated melody F1 | 0.705 | **0.765** |
| Lover Come Back | notated melody F1 | 0.648 | **0.698** |

Mean WJazzD note F1 over all 11 solos: **0.766 -> 0.782**. Gingerbread Boy was
the worst tune in the benchmark and is no longer in the bottom two.

**The one way this goes badly wrong** is routing a horn to it: a piano model
asked about a saxophone vouches for nothing, and rejection would then delete
the whole line. `ensemble` therefore lives per track in the sidecar, and
Dolores stays horn-led even though a third of its span is Hancock's piano.

### R7 — The beat grid was tracked from the drum stem, and it cost both ways

Symptom the user reported: the GUI's Beats button takes minutes. It did,
because a beats job ran a full demucs separation first, purely to get a drum
stem to track — the plan's reasoning being that the ride cymbal is the
cleanest pulse in jazz.

Measured, over all 11 WJazzD-matched solos, tracking the **full mix** instead:

| tune | soloist | tempo | mix | drum stem |
|---|---|---|---|---|
| Gingerbread Boy | Herbie Hancock | 286 | **0.976** | 0.602 |
| Dolores | Wayne Shorter | 277 | **0.976** | 0.653 |
| Dolores | Miles Davis | 275 | **0.987** | 0.676 |
| Dolores | Herbie Hancock | 282 | **0.905** | 0.644 |
| Nothing Personal | Pat Metheny | 242 | **0.832** | 0.773 |
| Yesterdays | J.J. Johnson | 125 | **0.977** | 0.962 |
| Orbits | Herbie Hancock | 265 | 0.970 | 0.970 |
| Oleo | Red Garland | 265 | 0.985 | 0.985 |
| Don't Blame Me | Charlie Parker | 64 | 0.948 | 0.948 |
| Walkin' | Miles Davis | 128 | 0.934 | **0.968** |
| Nothing Personal | Michael Brecker | 244 | 0.728 | **0.795** |
| | | **mean** | **0.929** | 0.816 |

The mechanism is visible in the beat counts: on Dolores the stem grid has 938
beats where the mix has 1690, and on Gingerbread Boy 955 against 2085. An
isolated drum kit at 275 bpm is a two-feel with nothing to contradict it, so
the tracker locks to half the pulse — and half-rate scores ≈0.67 by
construction, which is exactly what those rows show. The mix carries the
comping and the melody, which fix the rate.

So the drum stem was buying nothing on 3 tunes, losing badly on 4, winning on
2 (by 0.03 and 0.07), and charging a separation for all of them.

Fixed: `use_drum_stem` defaults off, and **`beats` now runs before `separate`
in the pipeline**. Ordering is the invalidation rule under chained keys, so
this is also what stops a change of separation model from throwing away a
beat grid and the downbeat anchor derived from it. The Beats button went from
~11 minutes to ~5 seconds. The stem path and its splice/fallback machinery
are kept behind the flag, not deleted — the reasoning that chose it is sound
for a tune the mix mistracks, and Walkin' is one.

Two things this cost, both reported rather than buried:

- **Confirmation's notated rhythm fell 0.779 → 0.744**, and its bar count
  went 130 → 134 against the human's 129. Confirmation is open-issue #9's
  motivating case: a 20-second drumless intro that the stem path handled by
  splicing. The mix grid needs no splice there and is slightly less accurate
  anyway. One tune, one number, against +0.11 mean beat F1 and the workflow.
- **Walkin' beat F1 fell 0.968 → 0.934**, the only real loss in the table.

### R8 — Beat F1 was a mean over 4 solos printed beside a note F1 over 11

`summary/wjazz_beat_f1` read 0.9715 and was quoted as the beat accuracy of
the benchmark. It was the mean over the four solos that happened to have a
grid in a hand-built `--grids` file, which had gone stale at 7 of 12 tracks
while the note score moved on to 11 solos. Nothing was wrong with the
number; it was answering a question about a different population than the one
next to it.

This is the third measurement bug in this harness and the same shape as the
first two: a *measurement* artefact that reads as a statement about the
transcriber. Fixed twice over — `run_eval.py` computes its own grids for
every sidecar'd track (affordable now that a grid costs seconds, R7), and
every mean now pins and prints its own `n`, so a denominator cannot change
silently again.

The honest like-for-like: on the four solos that were being scored, the new
mix grid is a wash (−0.035, +0.015, 0.000, 0.000). All of R7's gain is on the
seven solos that were never being scored at all.

### R9 — `separate` re-ran demucs over stems already on disk

Stems are written to a directory named for the audio digest and model, so
they are content-addressed and always correct for that pair. The stage never
looked: any config change upstream invalidated its cache entry, and the
honest answer to "you nudged a beats setting" was another eleven minutes of
demucs producing bytes that were already there.

`separate.run` now checks for a complete set against the model's own source
list before separating — all-or-nothing, because a directory holding three of
four wavs is a separation that died partway through.

### R1 — The .mscz benchmark's window offset fit slipped whole eighth notes

**Was costing note F1 about 0.17 on every tune.** Fixed in d91a26f; full
account in `docs/m3-benchmark.md`. Note F1 0.325/0.341/0.360 →
0.489/0.501/0.500, and onset F1 correctly went *down*, because some of the
old onset matches were the spurious ones a slipped window produces.

### R2 — The WJazzD fit mis-aligned Yesterdays, and it looked like a bad solo

**Reported note F1 0.509 where the truth is 0.835, and beat F1 0.623 where
the truth is 0.962.** The offset search was seeded from the start of the
user's span, but J.J. Johnson does not start playing until 26 s into it, so
the true offset lay outside the search window and the fit settled on a
confident wrong alignment 37 ms out.

Two things this cost, worth remembering because both were nearly acted on:

- It produced a plausible *story* — "trombone attacks are soft, so our onsets
  are late" — which was wrong, and which would have sent a night's work into
  the onset detector.
- It made the beat tracker look broken on that track, because the beat
  comparison inherits the same alignment.

The rate is now derived from two independently located ends of the solo
rather than searched from a seed, and the fit is centred on the median
residual of its matched pairs instead of being left wherever the count
plateau ended. `src/swingscribe/wjazz.py`, tested in `tests/test_wjazz.py`.

### R3 — Two solos looked only partly covered by their spans

Investigated and **false**. I had compared the raw fitted offset against the
span rather than the placed first onset; the user's spans cover every
annotated solo to within 0.4 s.

### R4 — Note values are not being written from played durations

Tested and **the hypothesis was right about humans and wrong about us**. 90
to 93% of the notes in the hand transcriptions fill the gap to the next note
exactly and none exceed it; but 93-96% of ours already do too, because
`notate.without_overlap` truncates every note at the next onset. Adding an
explicit legato rule moved the mean note-value agreement from 0.4628 to
0.4665. `notate.legato_fill` ships off.


### R5 — A swung eighth pair was being notated as it was played

**The largest single disagreement with the hand transcriptions**, and only
visible once the notation was scored as notation. Their even eighth (0.500 of
a quarter) came out as ours 0.667, 0.333, 0.750 or 0.250 — a triplet or a
dotted-eighth pair. That is exactly the failure the swing warp exists to
prevent.

Both halves were `choose_grid` reading more resolution out of a beat than its
notes can demonstrate. Warping is imperfect — the phase estimate is shrunk
toward the track mean and real playing scatters — so a warped offbeat
routinely lands near 0.6 rather than 0.5. On pure snap error, ternary beats
binary there; and once tuplets were restricted, the sixteenth grid took it
instead.

Fixed in 49f5f79 and 26a3402: a tuplet needs three onsets to be visible, an
eighth-note grid became a candidate at all, and the coarsest grid within
`grid_slack` of the best wins — with the hard constraint that a grid which
merges two onsets is too coarse whatever its error.

  rhythm 0.539 → 0.728      value 0.463 → 0.683

The stopping rule matters as much as the fix. The notation score rises
monotonically all the way to "write everything as eighth notes", which three
bebop solos would reward and any music with real sixteenths would not, so
`grid_slack` is **not** set from it. It is set by quantize's own acceptance
criterion — plan §5's 20 ms round trip, which measures what coarsening costs
the *performance*. 0.05 is the largest value that stays inside it.


**And then the overfitting worry was tested rather than argued about.**
WJazzD annotates metrical position — bar, beat, and which tatum of how many
subdivisions — so the notation can be scored against four *different* solos,
annotated by other people from other recordings, where `division` runs 1
through 10 rather than being all eighths:

| setting | MuseScore rhythm (3 bebop solos) | **WJazzD rhythm (4 other solos)** |
|---|---|---|
| as it was | 0.539 | **0.530** |
| tuplets need 3 onsets | 0.591 | **0.572** |
| + grid_slack 0.03 | 0.685 | **0.601** |
| **+ grid_slack 0.05 (ships)** | **0.728** | **0.619** |
| + grid_slack 0.08 | 0.762 | **0.626** |
| + grid_slack 0.12 | 0.779 | **0.616** ← turns over |

The control behaves as a control should: it agrees about the direction (+0.09
from the two fixes) and **it turns over**, where the tuning set does not. Its
optimum is near 0.08; we ship 0.05, on the conservative side of it, chosen by
a criterion that never saw either notation score.

### R6 — Is the CREPE voicing gate set too high?

Swept against WJazzD, mean note F1 over the four solos with beat grids:

| `voicing_threshold` | 0.30 | 0.40 | **0.50** (ships) | 0.60 | 0.70 | 0.80 |
|---|---|---|---|---|---|---|
| mean note F1 | 0.787 | 0.789 | **0.791** | 0.794 | 0.788 | 0.765 |

There is a real peak and it is at 0.60, but it beats the shipping 0.50 by
**0.002** — an order of magnitude less than the spread between tunes at any
one setting, and measured on four solos. The per-tune picture is mixed
(Orbits 0.828 → 0.810, Yesterdays 0.835 → 0.842). Moving a shipping default
on that evidence would be fitting the noise, so **0.50 stays**.

Worth keeping: the curve is flat from 0.30 to 0.70 and only collapses at
0.80, so the gate is not a lever on overall accuracy. It *is* a lever on the
precision/recall balance — Oleo's recall runs 0.624 at 0.30 down to 0.471 at
0.80 — so it is the right knob if recall on a specific tune ever matters more
than the mean.

## Assumptions on the record

Recorded so they can be overturned, in the order they were made.

1. **The shipping decode setting is `pitch_step_cost = 0.2`**, the config
   default. `scripts/score_benchmark.py` had been defaulting to 0.0, the
   legacy pre-Viterbi path, so the two disagreed about what was measured.
   Every number here is 0.2.
2. **A WJazzD solo is only scored when it wins its title by 2.5x and clears
   15% matched.** The three rejected tracks land at 1.9-9.3%, which is what
   note density predicts for the wrong take, so the threshold has daylight on
   both sides.
3. **An affine (offset, rate) fit is legitimate.** A rate term corrects a
   playback-speed difference between CD issues, which shows up as *monotone*
   drift across the solo — Walkin' needs 0.9942, Yesterdays 0.9965. Its
   capacity to manufacture agreement is bounded by what it achieves on a
   wrong take: under 10%, against the 79-84% it reports on a right one.
4. **The user's erasures are not applied** to any number above. They mark
   notes as "not the solo" and would raise precision, but they are ground
   truth about a problem (melodic-line selection, issue #8) rather than a
   licence to delete the evidence.
5. **Beat F1 is scored against WJazzD's human taps at mir_eval's default
   70 ms window.** No allowance is made for the taps themselves being human.
6. **Notate does not use music21**, which the plan names for it. music21 is
   not a dependency of this project and "never add a dependency without
   asking" is explicit (CLAUDE.md), so the stage is pure arithmetic instead.
   The upside is real — key detection and spelling run in CI like everything
   else — but this is a plan deviation and should be confirmed or overturned.
   `model.py`'s notation types carry everything a music21 `Score` would need,
   so wrapping rather than rewriting is the way back.
7. **Sidecars were created for two tunes that had none** (Dolores,
   Gingerbread Boy), with spans covering *every* WJazzD solo on that title,
   because which soloist was ripped is not knowable without listening —
   `identify` decides that afterwards from the audio and reports who it
   found. They are ordinary GUI sidecars and can be edited or deleted.
