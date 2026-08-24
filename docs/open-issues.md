# Open issues — carry these forward

Findings that are diagnosed but not yet fixed, recorded so they survive a session
change. Delete entries as they land.

## 1. ~~Sustained notes split by other instruments' onsets~~ — FIXED

Fixed by onset corroboration: a split inside a voiced run now requires the
tracked pitch's OWN harmonics to re-attack by `transcribe.onset_rise_db`
(default 3.0 dB). Measured on the original case (Moment's Notice 1.5–4.5s):
the held pitch-70 note went from 6 fragments to 1 note of 1.22s; notes in the
window 15 → 8. Regression-guarded in the synthetic suite
(`held_note_over_comping`: onset F1 0.40 with corroboration off, 1.000 on).
Set `onset_rise_db: 0` to restore the old behaviour.

Original report follows.


`stages/transcribe.py` splits a note at any detected onset, so a re-articulated
same-pitch note becomes two notes. But onsets come from `_spectral_flux_onsets`,
which is broadband flux over the **whole** stem — so piano comping and drum bleed
split notes the soloist is holding.

Evidence (Moment's Notice, 4-stem, Coltrane holding one pitch):

| Transcribed note | Detected onset |
|---|---|
| 2.65s pitch 70 | 2.65s |
| 2.87s pitch 70 | 2.87s |
| 3.24s pitch 70 | 3.24s |
| 3.47s pitch 70 | 3.47s |

Pitch constant, stem RMS flat at ~0.11 across the span — no real re-articulation.

**Fix direction:** require corroboration near the tracked f0 before splitting —
a genuine re-articulation dips then re-rises the harmonic energy *at the note's own
pitch*. Band-limit the onset detector around the tracked f0 and its harmonics, or
gate candidate splits on a local minimum in that band. Isolation (6-stem) reduces
but does not eliminate this.

## 2. ~~`transcribe.stem` is hardcoded~~ — FIXED

With `htdemucs_6s` giving `drums/bass/other/vocals/guitar/piano`, the transcriber
should be pointable at any stem — a guitar solo lives in `guitar`, a piano solo in
`piano`. Needs to be config (and is a prerequisite for the GUI audition screen).

## 3. 6-stem separation is better for this material but not the default

Measured (see git history for the run):

| Track | Notes | Mean confidence | Pitch range |
|---|---|---|---|
| Gerry's Blues 4-stem | 1259 | 0.75 | 35–90 |
| Gerry's Blues 6-stem | 762 | 0.78 | 37–90 |
| Moment's Notice 4-stem | 3032 | 0.73 | 33–90 |
| Moment's Notice 6-stem | 2461 | 0.81 | 33–82 |

Fewer notes with *higher* confidence = phantom notes removed. Confirmed better by
ear on Gerry's Blues. Decide whether `htdemucs_6s` becomes the default (note: its
piano/guitar sources are experimental per Demucs' authors, and 4-stem may still be
right for genuinely horn-only material).

Side effect: the 6-stem drum track gave Gerry's Blues a much cleaner beat grid
(tempo stdev 20.4 → 8.3, octave outliers 10 → 3) but moved the median 136.4 →
142.9 bpm. Needs a re-listen to decide which grid is right.

## 4. ~~No ground truth or diagnostics~~ — LARGELY DONE, one real gap

Landed: `tests/synthetic/generate.py` (exact ground truth, rendered at test
time), `src/swingscribe/metrics.py` (mir_eval wrappers scoring the three
failure modes separately), 8 pinned baselines, `tools/pin_baselines.py`, and
`transcribe.analyze()` returning per-frame `FrameDiagnostics` for the GUI
overlay.

**The gap that remains: the synthetic material is too easy.** Every case
scores ≥0.98, so the suite is a regression guard, not a quality measure — it
will catch a change that breaks something, but it cannot tell us whether the
transcriber is *good*. Additive synthesis with clean harmonics is far easier
to track than a real horn. Plan §6 specifies FluidSynth soundfont rendering
for exactly this reason; that is the next step, along with plan §12's
`scripts/setup_fixtures.py` to fetch a permissively-licensed soundfont.

Also still open from the original entry: nothing scores real audio. That is
Layer 2 (WJazzD, M6).

## 5. Footprints downbeat inference is wrong in 6/4 — ROUTED AROUND, not fixed

**Update:** measurement shows the problem is general, not 6/4-specific. The
beats-between-consecutive-downbeats histogram is `{2: 131, 4: 99, 1: 30, 3: 5}`
on Gerry's Blues and similar on Corner Pocket — if bars were real this would be
a single spike. `infer_beats_per_bar` takes the median of that, which is why
both 4/4 tunes reported 2 beats per bar. The *pulse* layer is fine (>95% of
beats within 5% of their local neighbours); only the downbeat layer is noise.

`stages/meter.py` no longer trusts it: bar lines are derived by counting beats
from a user-settable anchor, and the detected downbeats survive only as a weak
hint for the initial anchor guess. The underlying beat_this behaviour is
unchanged, so this entry stays open — but nothing downstream depends on it now.

Original report:

1005 beats against 435 downbeats = a downbeat every ~2.3 beats on a 6/4 tune. The
beat layer looks right (136 bpm quarter); the downbeat layer is not. Every track in
the M2 listening pass was in 4, so non-four meters are untested.

## 6. Moment's Notice beat grid is unstable

Tempo stdev 110.6 against a 250 bpm median, 420 octave outliers (17% of beats). The
grid-quality comparison rejected the drum stem in favour of the full mix, which is
backwards for fast bebop with a clear ride pattern.

## 7. `BeatGrid` doesn't record which source produced it

When the quality comparison overrides the initial source choice, the stored Document
doesn't record the winner, so reporting has to re-derive it (and gets it wrong).
Add `BeatGrid.source` at the next natural beats change.
