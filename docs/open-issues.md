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

**It does not help a piano soloist.** Scored against Tommy Flanagan's solo on
Giant Steps (`docs/m3-benchmark.md`), the dedicated `piano` stem is a wash
against `other` of `htdemucs_ft`:

| | pitch F1 | chroma F1 | invented | notes below the notated floor |
|---|---|---|---|---|
| `other` of htdemucs_ft | 0.686 | 0.773 | 69 | 26 (7%) |
| `piano` of htdemucs_6s | 0.682 | 0.765 | 59 | 25 (7%) |

The hypothesis was that Giant Steps' errors — substitutions of −12, −14, −19,
−17, never upward — were bleed a dedicated piano stem would remove. They are
not. They survive isolation intact because they are the pianist's *own left
hand*: separation cannot split one instrument from itself. That makes a piano
soloist an M7b problem (a polyphonic model, or top-line bias in the tracker),
not a separation problem, and it is evidence *against* making 6-stem the
default for its own sake.

## 4. ~~No ground truth or diagnostics~~ — DONE; it surfaced issue #8

Landed: `tests/synthetic/generate.py` (exact ground truth, rendered at test
time), `src/swingscribe/metrics.py` (mir_eval wrappers scoring the three
failure modes separately), 8 pinned baselines, `tools/pin_baselines.py`, and
`transcribe.analyze()` returning per-frame `FrameDiagnostics` for the GUI
overlay.

~~**The gap that remains: the synthetic material is too easy.**~~ Closed by
soundfont rendering: `tests/synthetic/soundfont.py` renders the *same* ground
truth through GeneralUser GS via the FluidSynth CLI (fetched, never committed,
by `scripts/setup_fixtures.py` — plan §12), so a score difference is
attributable to timbre alone. Baselines are pinned separately under
`synthetic_soundfont`; the additive numbers were not touched.

The suite now has dynamic range. Frame pitch accuracy, additive → sampled
tenor sax:

| Case | Additive | Soundfont |
|---|---|---|
| clean_line | 0.990 | 0.919 |
| held_note | 1.000 | 0.993 |
| fast_line | 0.989 | 0.705 |
| vibrato | 0.979 | 0.936 |
| held_note_over_comping (-3dB) | 1.000 | 0.660 |

**The finding worth carrying forward: the open-issue #1 fix is
level-dependent.** A held note under sampled piano comping, note count against
1 in the truth:

| comping level | -3dB | -6dB | -9dB | -12dB | -18dB |
|---|---|---|---|---|---|
| additive | 1 | 1 | — | 1 | — |
| soundfont | 4 | 3 | 2 | 1 | 1 |

Additive comping never shatters the note at any level, so the additive case
could not have shown this. With real instruments, onset corroboration holds
down to about -12dB and fails above it — CREPE loses the sax to the piano
rather than the segmenter mis-splitting (frame pitch accuracy falls with the
note count). The -3dB soundfont case is pinned at onset F1 0.000 as a record
of where we are, not as a floor; `held_note_over_quiet_comping` at -12dB is
the floor that is actually defended.

Whether -3dB comping is a *fair* target is a judgement call nobody has made
yet. It is louder than most real comping, but Demucs bleed puts real
accompaniment closer than -12dB. The honest reading is that the transcriber
needs either better stem isolation or f0 tracking that survives a competing
broadband source.

`fast_line` at 0.705 is the other new signal: 130ms notes segment correctly
(note F1 still 1.000) but a third of the frames are pitched wrong, which
additive synthesis hid completely.

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

## 7. ~~`BeatGrid` doesn't record which source produced it~~ — FIXED

When the quality comparison overrides the initial source choice, the stored Document
doesn't record the winner, so reporting has to re-derive it (and gets it wrong).
Add `BeatGrid.source` at the next natural beats change.

Landed with #9 below, which was that change. `BeatGrid.source` holds the
human-readable outcome ("drum stem + full mix over 5 span(s)") and
`BeatGrid.spliced` holds the spans taken from the other source, so a caller
can tell which beats are worth trusting less. Both default to empty, so
previously cached grids still deserialize.

## 8. CREPE loses the soloist to loud comping (surfaced by #4)

Split out of #4 so it survives that entry being closed. With realistic timbres, a
held sax note under piano comping at -3dB is tracked as 4 notes with frame pitch
accuracy 0.66; the same case is perfect at -12dB and perfect at every level under
additive synthesis. The onset-corroboration fix from #1 is intact — the failure is
upstream of it, in f0 tracking, and the note count is a symptom.

Regression-guarded both ways in `tests/test_synthetic.py`: `held_note_over_comping`
pins the failure, `held_note_over_quiet_comping` defends the level where it works.
Directions: better stem isolation (6-stem, see #3), a periodicity/energy gate that
notices it has switched sources mid-note, or CREPE's ensemble/`full` model.

**Confirmed on real music — but see the correction below for how much of the
error it actually accounts for.** Scoring against the hand transcriptions
(`docs/m3-benchmark.md`), Confirmation produced 253 notes that are not in the
score, and only 13 of them repeat a neighbour's pitch, so they are not #1's
fragmentation coming back. Recall is fine (0.86); precision is what this costs
us (0.64).

Note that #3's dedicated stems did *not* fix the equivalent on Giant Steps, so
"better isolation" is not automatically the answer — see #3.

### Partly addressed: Viterbi f0 decoding (`transcribe.pitch_step_cost`)

The mechanism was that CREPE was decoded **per frame**, by weighted argmax,
with nothing connecting frame t to frame t-1 — so the instant another
instrument out-shouted the soloist the reported pitch jumped to it and back.
`viterbi_bins` charges for movement between frames, which makes an excursion
that leaves the soloist and returns pay twice while a real interval pays once.
Default `pitch_step_cost` 0.2. Measured on the benchmark:

| | cost 0.0 | 0.1 | 0.2 | 0.4 |
|---|---|---|---|---|
| Confirmation | 0.747 | 0.753 | 0.762 | 0.764 |
| All The Things | 0.893 | 0.893 | 0.892 | 0.892 |
| Giant Steps | 0.688 | 0.687 | 0.702 | 0.709 |

0.4 scores higher still but starts dropping real notes (Giant Steps' missed
notes go 28 -> 44, and the additive `clean_line` case loses a note outright),
so 0.2 is where the trade stops being free. Invented notes on Confirmation
fall 242 -> 215 and on Giant Steps 69 -> 47.

**This does not close the issue.** Confirmation still invents 215 notes; the
gain is real but partial, and the largest error source is still other
instruments in the stem.

### CORRECTION: on the horns, most of the rest is not other instruments

An earlier version of this entry read "only 13 of 253 repeat a neighbour's
pitch, so the other 240 sit at unrelated pitches: they are other instruments."
The first half is measured; the second half was an inference, and it is wrong.
"Not the same pitch as its neighbour" is not "unrelated to its neighbour".

Measured properly — each invented note against the nearest real notes on
either side of it in time, after Viterbi decoding:

| | Confirmation | All The Things | Giant Steps |
|---|---|---|---|
| invented notes | 215 | 39 | 47 |
| within 2 semitones of a real neighbour | **74%** | **94%** | 24% |
| sitting *between* its neighbours in pitch | 49% | 77% | 15% |
| more than 4 semitones from both | 16% | 0% | **70%** |
| outside the soloist's own register | 7% | 5% | **55%** |
| within 0.5s of a real note | 85% | 85% | 96% |
| median duration vs matched | 0.110 / 0.150s | 0.110 / 0.160s | 0.120 / 0.130s |

The two horn solos and the piano solo have different remaining failure modes,
and only one of them is this issue:

- **On the tenors, the remaining invented notes are the soloist's own
  articulation.** They are one or two semitones from a real note (commonest
  intervals -1, -2, +1, +2), half of them sit between their neighbours, none
  are out of register, and they are short. Those are scoops, bends, grace
  notes and passing tones — sound the player really made and the transcriber
  chose not to notate. Not other instruments, and not something isolation can
  reach.
- **On Giant Steps it really is a second source**: 70% more than 4 semitones
  from both neighbours, 55% below the soloist's register, commonest intervals
  -10, -17, -9, -12, -20. The pianist's left hand, as #3 concluded.

So this issue is real but it is now mostly a *piano-soloist* issue, and the
horn precision gap belongs to a new problem: deciding which pitch inflections
deserve to be notated as separate notes. `pitch_persist_ms` currently applies
one flat 60ms threshold regardless of interval size, which cannot distinguish
a bend from a melodic step.

### Measured and rejected: interval-aware note splitting

The obvious follow-up to the correction above was to make `_pitch_change_points`
interval-aware — require a small excursion to persist much longer than a large
one before it earns its own note, on the theory that small excursions are bends
and large ones are melody. **It does not work, and the reason is worth keeping
so nobody tries it again.**

Every local feature the segmenter can see, scored over the 253 invented and 966
matched notes of the two tenor solos:

| rule | invented caught | matched wrongly caught |
|---|---|---|
| interval <= 2 semitones | 52% | **61%** |
| returns to the previous pitch | 16% | 10% |
| no corroborated onset | 60% / 37% | 35% / 50% |
| <= 2 semitones AND returns | 9% | 7% |
| <= 2 semitones AND no onset | 33% | 24% |

The first row is the whole story: a matched note is *more* likely to be a small
interval than an invented one. Bebop is overwhelmingly stepwise, so "small
interval" describes the melody at least as well as it describes the ornaments.
The onset feature has real signal on Confirmation (60% vs 35%) and inverts on
All The Things (37% vs 50%) — the second number pair above — because a
slurred saxophone line produces real notes with no fresh attack.

Searching all combinations of interval, duration, return and onset for the best
achievable trade, every winner turns out to be **duration alone**; adding an
interval constraint makes each one worse:

| rule | invented cut | matched lost |
|---|---|---|
| duration < 0.25 beats, no onset | 22% | 3% |
| duration < 0.25 beats | 33% | 6% |
| interval <= 2, duration < 0.25 beats, no onset | 11% | 2% |

And the best of those is the beat-relative duration floor already known to be
marginal: applied per tune it moves Confirmation 0.762 -> 0.769 and All The
Things 0.892 -> **0.875**. Net zero.

**Conclusion: the remaining precision gap on horn solos is not reachable from
local per-note features.** Whether a passing tone or a scoop deserves to be
notated depends on the phrase, the harmony and the transcriber's convention —
context the segmenter does not have and cannot be given by a threshold. It is
a modelling problem, not a heuristic one. It is also partly a matter of taste:
some fraction of those "invented" notes are sounds the player really made, and
a different transcriber would have written some of them down.

### Two things the synthetic case got wrong about this

Worth recording, because the -3dB soundfont case was chosen as the cheap proxy
for this issue and it misled in both directions.

1. **It showed no improvement at all, for the wrong reason.** Viterbi fixes its
   pitch track — frames on the true sax bin go 54% -> 71%, and the
   octave-below excursions go 16.8% -> 0% — but the score does not move,
   because at the frames CREPE gets wrong its confidence in the sax is 0.07,
   far under the 0.5 `voicing_threshold`. Those frames are gated out as
   unvoiced whichever bin the decoder picks. **That case is a voicing failure,
   not a decoding failure**, and it cannot measure a decoder. Drop the gate to
   0.05 and continuity takes it from frame accuracy 0.727 to 0.913 and onset
   F1 0.286 to 0.500.
2. **So it suggested lowering the voicing gate, which is wrong on real audio.**
   Swept over the benchmark, every reduction below 0.5 costs accuracy (mean
   pitch F1 0.788 at 0.5, 0.776 at 0.1): a lower gate admits bleed, and on
   real music there is much more of it than one synthetic piano. The gate
   stays at 0.5.

## 9. ~~The drum-stem gate is global, but drum presence is local~~ — FIXED

Confirmation draws no bars for its first ~20s. Not a drawing bug and not a
meter bug — the beat *tracker* found almost nothing there, and the meter stage
correctly declined to invent bars over it.

Measured (htdemucs_6s, RMS per 4s window against a whole-mix RMS of 0.130):

| window | mix | drums | bass | piano |
|---|---|---|---|---|
| 0–4s | 0.112 | **0.00005** | 0.00008 | 0.002 |
| 4–8s | 0.115 | 0.005 | 0.035 | 0.012 |
| 8–12s | 0.126 | 0.012 | 0.053 | 0.017 |
| 28–32s | 0.138 | 0.024 | 0.076 | 0.022 |

The intro has no drums at all — the drum stem is ~68dB below the mix for the
first four seconds, and the kit only arrives gradually. Beats stage runs on
the drum stem by design (plan §5: the ride is the cleanest reference), so it
had nothing to track. The result:

- no beats at all before 11.28s
- three sparse beats 11.28–13.82, then a 6.06s hole
- from 19.88s a steady grid, but at 0.62s spacing — **half** the true rate
- whole-track median 187.5 bpm, and the transcription implies 187.3 bpm, so
  the tracker is exactly right once the drums are playing

`min_drum_mix_ratio` (open-issue #3's relative gate) correctly keeps the drum
stem here, because *across the whole track* drums are well above the 5%
threshold. The gate cannot see that one passage has none. A drumless intro —
a piano intro, a rubato head, a horn pickup — is common in jazz, so this will
recur.

### Measured: which source would have found the intro?

beat_this run on each source for Confirmation, truth 187.3 bpm from the hand
transcription:

| source | intro coverage 0-30s | first beat | intro gaps | whole stdev | octave outliers |
|---|---|---|---|---|---|
| drums (current) | 20/94 = 21% | 11.28s | 1.28, 6.06, 0.62... | **22.0** | 2% |
| bass | 36/94 = 38% | 9.62s | 0.64, 0.66, 0.64... | 45.9 | **30%** |
| full mix | **95/94 = 101%** | **0.24s** | **0.32, 0.34, 0.32** | 64.5 | 2% |

Bass beats drums in the intro but finds beats at HALF the true rate — the
bassist is playing a 2-feel in the head and only walks in 4 for the solos, so
the bass reports its own rhythm rather than the pulse. That is why its
whole-track octave-outlier rate is 30%. Bass is not the answer.

The full mix is: 101% intro coverage at exactly the right rate. In a drumless
intro the pulse is carried by the *ensemble*, and separation destroys that by
isolating one instrument. But the full mix is three times less steady than the
drum stem over the body of the track, so it is not the answer everywhere
either.

### The deeper bug

The M2 grid-quality comparison already tries the other source when a grid is
suspect. **It never fired here**, because the drum grid is excellent by every
whole-track measure — 187.5 bpm median, 2% outliers, the steadiest of the
three. A grid can be superb across 95% of a track and have a 20-second hole
at the front, and nothing in `grid_is_suspect` notices.

So source selection AND quality assessment are both global, and the failure is
local. That is the same shape as the drum-gate problem above, one level up.

**Fix direction:** evaluate coverage and steadiness per passage and splice —
full mix for the intro, drum stem for the body. A coverage test (are there
long stretches with no beats where the audio is not silent?) would catch this
class of failure that steadiness alone cannot see.

The half-rate opening is also the Corner Pocket pattern from
docs/meter-plan.md; repair seeded from the global mode should reach it, but
cannot here because the surviving early beats are too few to form a span
(`min_span_beats`).

Low urgency for the benchmark work: Confirmation's `form_start` is 51.4s, well
clear of the damage. It matters when a solo *starts* near a drumless passage.

### The fix: measure coverage separately, and splice rather than swap

`coverage_gaps` finds stretches with no beats lasting more than three expected
beat intervals — **including before the first beat and after the last**, which
is where this failure lives; a grid that simply starts late looks perfect to
every steadiness measure. `audible_spans` discards gaps where the mix is not
playing, so a silent lead-in is not mistaken for a tracker failure.
`splice_beats` then fills each gap from the other source, all-or-nothing, and
only where the filler's beat rate there agrees with the base grid's to within
25%. That rate test is what rejects the bass: it covers the intro better than
the drums but reports a 2-feel at half the true pulse.

Confirmation, against 187.3 bpm from the hand transcription:

| | before | wholesale swap | splice (shipped) |
|---|---|---|---|
| source | drum stem | full mix | drum stem + full mix, 5 spans |
| first beat | 11.28s | 0.24s | **0.24s** |
| intro 0-30s coverage | 21% | 101% | **84%** |
| whole-track stdev | 22.0 | 64.5 | **35.7** |
| octave outliers | 2% | 2% | 2% |

The middle column is worth keeping. A first attempt let the existing
whole-track comparison decide, and it *did* fix the coverage — by swapping to
the full mix, whose grid is three times less steady over the body of the tune.
That is precisely the trade this entry warned against. **Coverage gaps are a
local failure and must get a local repair**, so the wholesale swap now
requires a genuinely suspect grid (v2's job, unchanged) and a merely gappy
grid keeps its source and borrows only what it is missing. The spliced spans
land exactly on the damage described above: 0.24-10.98, 11.62-12.26,
12.88-13.52, 14.14-19.58, plus an outro.

### Second half: repairing a locally wrong RATE

Splicing left intro coverage at 84%, because the drum stem's own beats from
19.88s are *present* — at 0.62s spacing, exactly half the tune's 0.32s pulse.
Present beats are not a gap, so no coverage test can see them.

`repair_local_rate` subdivides any run of intervals sitting at a whole
multiple (2x-4x) of the grid's own median interval. This is `correct_octave`'s
repair applied per passage and seeded from the grid itself rather than from a
user-supplied `tempo_hint` — the grid's median is the better reference in
every case where most of the track is tracked correctly, and it needs no
input. The safety property is the run length: a single doubled interval is a
dropped beat, a fermata or a rubato moment, so only a *persistent* wrong rate
counts as evidence. It is deliberately one-directional; a passage tracked too
FAST would need beats removed, and choosing which to remove is a much less
safe decision that `correct_octave` still only makes with a user's tempo.

| | Confirmation | All The Things | Giant Steps |
|---|---|---|---|
| intro 0-30s, originally | 21% | 98% | 51% |
| after splicing | 84% | 98% | 51% |
| **after rate repair** | **101%** | 98% | **100%** |
| octave outliers before | 2% | 3% | 16% |
| **octave outliers after** | **1%** | 3% | **5%** |
| whole-track stdev | 22.0 -> 33.8 | 30.1 | 69.9 -> **54.6** |
| repaired spans | 19.9-30.0s, 437.1-439.0s | none | 0.3-29.7s, 297.6-336.5s |

Confirmation's repaired span lands exactly on the half-rate stretch described
above. **Giant Steps was the surprise**: 68 seconds of half-rate tracking that
nothing had diagnosed, and repairing it cut its octave outliers from 16% to
5%. Its median stays 250.0 bpm against a truth of 249, so this is a real
repair and not a doubling error. That was assumed to be issue #6's territory;
some of #6 may be the same bug.

Confirmation's whole-track stdev is 33.8 against the original drum stem's
22.0. That is not a regression — the original was steady precisely *because*
it was ignoring a third of the track. Steadiness measured over more of the
music is a harder number to score well on.

**What is left.** Giant Steps still has audible coverage gaps in its last 30
seconds (340.9s onward) that nothing filled, and All The Things reports 187.5
bpm against a hand-transcription truth of 194. Neither is this issue.
