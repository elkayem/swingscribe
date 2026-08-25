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

## Resolved

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
