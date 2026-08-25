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
annotation of the same recording:

| tune | soloist | tempo | note F1 | note recall | beat F1 |
|---|---|---|---|---|---|
| Orbits | Herbie Hancock, piano | 265 | **0.828** | 0.812 | 0.970 |
| Walkin' | Miles Davis, trumpet | 128 | **0.829** | 0.849 | 0.968 |
| Yesterdays | J.J. Johnson, trombone | 125 | **0.835** | 0.849 | 0.962 |
| Oleo | Red Garland, piano | 265 | **0.674** | 0.589 | 0.985 |
| | | **mean** | **0.791** | | **0.971** |

MuseScore — the three hand-transcribed solos:

| tune | pitch F1 | onset F1 | note F1 |
|---|---|---|---|
| Confirmation | 0.762 | 0.596 | 0.514 |
| All The Things | 0.892 | 0.586 | 0.516 |
| Giant Steps | 0.702 | 0.611 | 0.512 |

The gap between the two tables is the point. Against audio the transcriber is
at note F1 0.79; against notation it reads 0.51. Some of that gap is real —
notation idealizes what was played, and that difference is the transcriber's
to explain — but it is not evidence about hearing.

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

### D3 — Octave errors on piano

**11 of Orbits' 18 pitch errors are exactly +12.** Small in absolute terms
(2.4% of the solo) but it is a systematic, nameable error rather than noise,
and it is the one error class a listener notices immediately.

### D4 — Nothing measures the notation itself

Notate and export now exist and produce MusicXML that opens, but no number
on this page scores *notation*. The .mscz benchmark compares pitch sequences
and onset times, not note values, ties, spelling or bar assembly — so a score
could be full of unreadable rhythms and every table above would be unmoved.

The obvious measure is available and not yet built: our MusicXML against the
`.mscz` for the same solo, compared as notated rhythm rather than as time.
`mscz.py` already parses one side of it.

### D5 — The plan's milestone numbering has drifted from CLAUDE.md's

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
