# Deficiencies relative to the benchmark

A running, ordered list of what stands between the current pipeline and a
transcription worth handing to a musician. Ordered by measured impact, not by
how interesting the problem is. Every entry has to name a number that would
move; anything that cannot is an opinion and belongs somewhere else.

Reproduce all of it with one command:

```bash
uv run python scripts/run_eval.py --db ../wjazz/wjazzd.db
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
| Yesterdays | J.J. Johnson, trombone | 125 | **0.835** | 0.849 | 0.962 |
| Walkin' | Miles Davis, trumpet | 128 | **0.829** | 0.849 | 0.968 |
| Orbits | Herbie Hancock, piano | 265 | **0.828** | 0.812 | 0.970 |
| Dolores | Miles Davis, trumpet | 275 | **0.755** | 0.765 | — |
| Dolores | Herbie Hancock, piano | 282 | **0.749** | 0.731 | — |
| Dolores | Wayne Shorter, tenor | 277 | **0.676** | 0.660 | — |
| Oleo | Red Garland, piano | 265 | **0.674** | 0.590 | 0.985 |
| | | **mean** | **0.764** | | **0.972** |

Notation — of the notes we get right, how many are *written* the way the
human wrote them:

| tune | bars | matched | rhythm | note value |
|---|---|---|---|---|
| Giant Steps | 67 | 241 | **0.785** | **0.693** |
| Confirmation | 130 | 581 | **0.779** | **0.673** |
| All The Things | 74 | 376 | **0.620** | **0.683** |

MuseScore — audio against notated rhythm, the pessimistic measure:

| tune | pitch F1 | onset F1 | note F1 |
|---|---|---|---|
| Confirmation | 0.762 | 0.596 | 0.514 |
| All The Things | 0.892 | 0.586 | 0.516 |
| Giant Steps | 0.702 | 0.611 | 0.512 |

The gap between the first and last tables is the point. Against audio the
transcriber is at note F1 0.76; against notation it reads 0.51. Some of that
gap is real — notation idealizes what was played, and that difference is the
transcriber's to explain — but it is not evidence about hearing.

## Open deficiencies

### D1 — Oleo: we hear fewer notes than Red Garland played

**Note F1 0.674 against 0.83 for the other three, and it is recall
(0.589) not precision (0.786).** The only tune where we under-detect. 24.5%
of his notes have something of ours nearby that is wrong, and 5.0% have
nothing at all. Block-chord piano at 265 bpm: the top voice moves inside a
sustained texture, so there is no attack for an onset detector to find.

Note this is the *opposite* failure from Giant Steps, where the complaint was
too many notes (left-hand comping). Both are polyphonic-piano problems and
they may share a cause; they need different fixes.

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
| Gingerbread Boy (Hancock) | to be measured | 485 notes over 316 s, no match | — |

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

## Resolved

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
