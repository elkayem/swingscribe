# M7b — the piano path

Plan §5 stage 3 routes piano through a dedicated polyphonic model rather than
the monophonic f0 path, and says so bluntly: *"Do not use the monophonic path
for piano."* This is the measurement that says why, taken before any model was
added, so the improvement has something to be measured against.

## The finding: it is not polyphony, it is the left hand

Oscar Peterson's *Lover Come Back To Me* was added to the benchmark as the
first solo here that is genuinely polyphonic — 52 of its 507 notated notes are
chord tones (10%), mostly thirds under the melody rather than octave doubling:

| interval below the melody note | m3 | M3 | P4 | TT | P5 | M6 | 8ve+ |
|---|---|---|---|---|---|---|---|
| count | 19 | 9 | 4 | 6 | 6 | 2 | 5 |

The obvious hypothesis is that those 52 notes are what a monophonic path
cannot reach. They are — but they are not what is costing us. Aligning our
notation against each hand transcription's melody line:

| tune | soloist | melody recall | precision | exact-octave errors | errors a 5th or more BELOW |
|---|---|---|---|---|---|
| All The Things | Hank Mobley, tenor | **0.905** | 0.878 | 0% | 6% |
| Confirmation | Dexter Gordon, tenor | **0.861** | 0.692 | 2% | 15% |
| Giant Steps | Tommy Flanagan, piano | **0.715** | 0.695 | **25%** | **80%** |
| Lover Come Back | Oscar Peterson, piano | **0.670** | 0.628 | **23%** | **77%** |

**About 78% of our pitch errors on piano are notes a fifth or more below the
melody, and roughly a quarter are exact octaves. On horns the same figures are
6–15% and 0–2%.** The failure is not that we cannot hear two notes at once. It
is that in a piano trio the `other` stem carries both of the pianist's hands,
and a monophonic tracker follows whichever voice is loudest frame to frame —
which is the left one more often than it should be.

That also bounds what polyphony alone could buy. A perfect monophonic
transcriber on the Peterson solo reaches 455 of 507 notes, so note recall
caps at 0.897 and note F1 at 0.946. We are at melody recall 0.670. **The
chord tones are not the binding constraint and will not be for some time.**

## Baseline to beat

Everything below is the monophonic path, `htdemucs_ft` "other" stem, scored
the same way the other three tunes are (`scripts/run_eval.py`).

| | Lover Come Back To Me |
|---|---|
| MuseScore note F1 | **0.230** |
| MuseScore onset F1 | 0.414 |
| MuseScore pitch F1 | 0.649 |
| MuseScore chroma F1 | 0.745 |
| notated rhythm | 0.665 |
| notated note value | 0.629 |
| bars | 64, against the score's 64 |

The other three tunes sit at note F1 0.512–0.516, so this solo reads roughly
half as good as the horn material. Chroma F1 0.745 against pitch F1 0.649 is
the same finding from another angle: we usually have the right pitch class and
the wrong octave.

WJazzD has no take of this recording (best candidate 8.2%, which is what note
density predicts for the wrong take), so this tune is scored against notation
only. Bar count landing exactly on 64 says the beat grid and the form are
right and the loss is genuinely in the notes.

## What the ground truth had to learn first

`mscz.parse` kept only the top note of every chord. That is correct for a
single line and wrong for this solo, and it would have made a polyphonic
transcriber score *identically* to the monophonic one it replaced — the
benchmark could not have seen the improvement it exists to measure.

`Score` now carries two views: `melody` (top note of each chord — what the
time-free pitch aligner needs, since two notes at one position have no order)
and `notes` (everything). Every measure through M6 uses `melody`, so nothing
pinned moved; the four monophonic scores parse bit-identically.

## Chosen model

`piano_transcription_inference` (Kong et al., MIT), over the plan's named
`transkun` (also MIT). Both work; the decision was the dependency footprint on
this machine:

- **10 packages against 25.** transkun resolves tensorboard, matplotlib,
  seaborn, pandas, grpcio, protobuf and sox — a training stack in an inference
  path.
- **It avoids numba by construction.** Its one real dependency,
  `torchlibrosa`, is a pure-PyTorch reimplementation of librosa's spectrogram
  ops. Windows Application Control blocks numba's DLLs here (CLAUDE.md), which
  is why librosa, resampy and pYIN are all already banned.
- **Explicit sustain-pedal handling**, which plan §5 flags as a thing to deal
  with rather than discover.

`basic-pitch` was ruled out before it was considered on quality: it pulls
`resampy` (numba) and TensorFlow 2.15, and downgrades numpy.

## First measurement with the model in place

`piano_transcription_inference` runs at **0.36x realtime on CPU** (41s for a
115s span) and its checkpoint is 172 MB. Two things it does not do for itself
on this machine, both handled in the stage that will wrap it:

- it fetches its checkpoint with `os.system('wget ...')`, which does not exist
  on Windows, and ignores the exit code — the failure surfaces much later as a
  `FileNotFoundError` inside `torch.load`;
- it wants 16 kHz mono, and its own loader goes through librosa.

It transcribes **everything it hears**: 1582 notes on the Peterson span
against the hand transcription's 507, because the `other` stem carries both of
the pianist's hands plus bass bleed. So a melody-selection step is not
optional — it is the whole difference between the model's output and a solo
transcription.

Scored exactly like the baseline (notated, then time-free pitch alignment
against the hand transcription's melody line):

| | notes | P | R | **F1** |
|---|---|---|---|---|
| **Giant Steps** — CREPE monophonic | 347 | 0.695 | 0.715 | **0.705** |
| piano model, top-of-cluster | 379 | 0.807 | 0.908 | **0.855** |
| piano model, + register gate −9 st | 341 | 0.874 | 0.884 | **0.879** |
| **Lover Come Back** — CREPE monophonic | 486 | 0.628 | 0.670 | **0.648** |
| piano model [other], top-of-cluster | 539 | 0.508 | 0.602 | 0.551 |
| piano model [mix], top-of-cluster | 512 | 0.568 | 0.640 | 0.602 |
| piano model [mix], + register gate −15 st | 480 | 0.610 | 0.644 | **0.627** |

**Giant Steps improves by +0.174, and recall by +0.169.** That is the M7b
promise arriving: Tommy Flanagan plays a mostly single-line bebop piano and
the model simply hears more of it than CREPE does.

**The Peterson does not improve** — 0.627 against the monophonic 0.648, after
the best gate. Nothing is wrong with the note detection; the problem is
choosing which of the notes is the tune. Peterson's left hand is active
between his right-hand phrases, so "the highest note in this onset cluster" is
a left-hand note whenever the right hand is not playing, and precision falls to
0.51–0.61. Flanagan's sparser left hand never poses that question.

So the binding constraint has moved, exactly one step: it was *hearing* the
notes, and it is now **melodic-line selection** — open-issue #8, which the
erasure labels in the GUI sidecars were being collected for. A register gate
taken from the line's own median is a crude stand-in and is worth roughly
+0.02; it is in the measurement to size the problem, not to ship.

One incidental finding worth keeping: on the Peterson, feeding the model the
**raw mix beats feeding it the separated stem** (0.627 against 0.570). The
separation is removing or smearing piano the model would otherwise get. That
is what plan §5's `solo-piano` routing already predicts — "piano path on the
raw audio, separation skipped entirely" — and it now has a number behind it
for the trio case too.

## The second opinion: what shipped

The line-selection problem above is still open. But measuring it turned up
something that needed no new data and no selector at all.

### "Not in the score" covers two different things

The hand transcriptions notate the **right hand only** — the left hand is
deliberately not transcribed. So a note of ours that is absent from the score
may be either of:

- **a transcription error.** We invented it, or heard the wrong instrument.
- **correct, and out of scope.** It happened; nobody asked for it.

Charging both to precision is what makes a working transcriber look broken.
Telling them apart needs no ground truth — only a second detector. CREPE
(monophonic f0 over a harmonic stack) and a polyphonic piano model are
independent in features, architecture and failure mode, so a note both report
is very unlikely to be either one's hallucination.

The listener's own erasures are the held-out test, and they split cleanly:

| solo | erased notes corroborated | median pitch vs kept | reading |
|---|---|---|---|
| Orbits | **0%** | −17 semitones | CREPE is tracking the **bass** through stem bleed |
| Oleo | 10% | −0.5 | invented |
| Giant Steps | 65% | −10 | mixed |
| Lover Come Back | **90%** | −4.5 | real notes, **left hand** |

Orbits is the clearest case and it is not what was expected. The notes the
listener deleted sit a median of seventeen semitones below the melody and the
piano model reports **none** of them — because a piano model correctly
declines to call a double bass a piano. That is an independent confirmation
that those deletions were right, arrived at without a hand transcription.

### It also fixes them

Two operations, measured separately because they do different things:

- **`snap_octaves`** moves a note to the oracle's octave where the two agree
  on pitch class. Raises **recall** — a note at the right octave now matches.
  Aimed at D4, where 23% of piano pitch errors are exact octaves.
- **`corroborate`** drops what the oracle will not vouch for. Raises
  **precision**.

Snapping runs first, so a note at the wrong octave gets corrected rather than
thrown away. Scored through the real harness, all four piano solos improve on
**both** benchmarks, in precision **and** recall:

| solo | measure | baseline | + oracle | |
|---|---|---|---|---|
| Orbits | WJazzD note F1 | 0.828 | **0.895** | +0.067 |
| Oleo | WJazzD note F1 | 0.674 | **0.710** | +0.037 |
| Giant Steps | notated melody F1 | 0.705 | **0.765** | +0.060 |
| Lover Come Back | notated melody F1 | 0.648 | **0.698** | +0.050 |
| | ⤷ precision | 0.628 | 0.706 | +0.078 |
| | ⤷ recall | 0.670 | 0.690 | +0.020 |

Orbits and Oleo are WJazzD — a human's onsets on the *same recording*, not a
notation comparison — so this is not an artefact of the notation path.

### Routing, and the one way it can go badly wrong

`TranscribeConfig.uses_piano_oracle` is true for `ensemble` in `trio` or
`solo-piano`, which is the routing plan §5 stage 3 specifies. **A horn-led
span must never get it**: a piano model asked about a saxophone vouches for
nothing, and rejection would then delete the entire line.

That is not hypothetical. Dolores' span holds Miles Davis, Wayne Shorter AND
Herbie Hancock, so it stays horn-led even though a third of it is piano.
`ensemble` therefore lives per track in the sidecar beside the audio, with the
span and the downbeat — it is a judgement about the recording, not a global
setting.

An oracle that cannot be reached — no `ml` group, no checkpoint, a download
that failed — is reported and ignored. The oracle improves a line that
already exists, and must never be the reason there is no line.

### Confirmation from the app, on labels that were never used to tune it

The 33 erasures on Orbits were made by ear against a CREPE-only transcription,
long before the oracle existed. Running the same span through the GUI with
`ensemble: trio` — the first end-to-end use of the oracle in the app —
produced 399 notes from 488 the oracle heard: 18 octaves snapped, 51
uncorroborated notes dropped.

Of the 33 erasures, **26 no longer match any note at all**: the transcriber
has stopped emitting them. Seven have a note at that instant but at another
pitch. Not one still matches exactly.

Sampling the unmatched ones by name — G2 at 2:43, G2 at 2:47, F♯2 at 2:49 —
says what they were. G2 is 17 semitones under the melody; corroboration
dropped them because a piano model, correctly, will not vouch for a double
bass bleeding through the stem.

So the tool now does automatically what the listener was doing by hand, on
labels that played no part in choosing the thresholds. That is the strongest
form the earlier measurement could take, and it arrived as a side effect of
wiring the GUI rather than from a scoring run.

It also exposed an interface bug: the review screen reported all 33 as
"erasures no longer match this transcription", in a warning colour, beside a
Discard button. `erasures.resolve` now separates `moved` from vanished, and
only the former is a warning.

## Line selection, reframed by the listener (2026-08-25)

The plan and issue #8 both treat "which note is the melody" as something the
software must decide. The listener's actual workflow does not:

> At this point, I'm not too worried about whether the left hand gets captured
> or not... Most of the time, with piano music I'll use the top one or two
> notes (what the right hand plays) so it would be good to at least see it.

That changes the target from *precision* to *recall*. A note that is on the
screen can be deleted in one keystroke; a note that is missing has to be found
by ear. So the question is not "can we pick the line?" but "is the right note
present at all?"

**It is, and by a wide margin.** Clustering the oracle's polyphonic output by
onset (50 ms) and keeping the top N pitches of each cluster, scored against the
hand transcriptions — which notate the right hand only, so they are exactly the
target this asks about:

| | Giant Steps recall | Lover Come Back recall |
|---|---|---|
| our pipeline (ships today) | 0.742 | 0.734 |
| oracle top-1 | 0.917 | 0.701 |
| **oracle top-2** | **0.958** | **0.925** |
| oracle top-3 | 0.961 | 0.967 |

Soul Station, added later and the worst tune in the benchmark (D8), makes the
same case more sharply — 0.538 recall today against 0.835 for top-2, and 0.288
against 0.596 over the block-chord ending where we currently track an inner
voice an octave under the line.

Top-2 is the knee. Precision is 0.60 / 0.41 / 0.30, so between half and two
thirds of what is shown would be deleted — which is the trade the listener
asked for, and the reason this is a *review* feature and not a new default.

### Velocity is an unused melody cue

The oracle reports a velocity per note and nothing reads it. Taking the
*loudest* note of each cluster rather than the highest:

| | Giant Steps F1 | Lover Come Back F1 |
|---|---|---|
| oracle top-1 (highest) | 0.858 | 0.583 |
| oracle loudest of cluster | 0.864 | **0.715** |
| top-2, nearest CREPE's contour | 0.825 | 0.702 |
| our pipeline (ships today) | 0.761 | 0.730 |

On Soul Station it is better still: recall 0.538 → **0.722** at an F1 that
matches what ships (0.537 vs 0.536). Strictly more of the line on screen for
the same amount of deleting, which is the shape of win this workflow wants.

On the Peterson — the hard case, locked hands and octave doubling — loudness
recovers most of what "highest" throws away (0.583 → 0.715). It still does not
beat the current pipeline there, so this is not a drop-in replacement; it is
evidence that the selector should weigh loudness, and that a register floor
should not be trusted (`>= 55` helped Giant Steps and hurt Lover).

### What the erasure labels say, which is not what register predicts

302 hand-made "not the solo" labels now exist across 11 tracks. The intuition
that they are mostly low left-hand material is **wrong**: median pitch is 60,
and only 24% sit below G3.

Against the notes that were kept:

| property | erased (median) | kept (median) | separates? |
|---|---|---|---|
| duration | 0.130 s | 0.150 s | **no** |
| confidence | 0.708 | 0.851 | yes — AUC **0.830** |

A duration floor is a trap: at 0.12 s it removes 41% of erased notes and 28%
of kept ones, which is barely better than deleting at random. Nobody should
"tidy up" with one.

Confidence is genuinely informative. At a 0.65 floor it removes 30% of what
the listener deleted and only 7% of what they kept. That is **not** an
argument for auto-deleting — losing 7% of good notes to save a third of the
clicks is the wrong trade when recall is the point. It is an argument for
*shading* low-confidence notes in the review UI so the eye goes to them first.

## What shipped: the second voice as a review overlay

Built to the listener's own spec — *"second voice on the same staff; if it
isn't correct, I'll delete it."*

- `corroborate.second_voice` clusters the oracle's output by onset (50 ms),
  keeps the top two of each simultaneity, and drops whatever the line already
  shows. Taken from the oracle's own clustering rather than relative to our
  note, because the case that most needs it is the one where our note is
  **wrong**: over Soul Station's block-chord ending we track an inner voice an
  octave under the melody, so the note worth offering is the one *above* ours.
- It never enters the scored note list. It rides on `FrameDiagnostics` — the
  overlay nothing downstream consumes — and `piano_second_voice` is off in the
  plain `Config`. The GUI turns it on for review only. The Score button does
  not see it either: that measure compares our line against a single notated
  melody, and a second voice on the page would score as a page full of notes
  the human never wrote.
- `notation.py` notates it **separately** and merges it as voice 2. It cannot
  simply join `notes`: quantize picks one grid per beat and notate writes one
  note per grid position, so two simultaneous notes in one list are not a
  chord to it — they are a grid that is too coarse, and one of them would be
  silently dropped (M6).
- Both voices share **one** swing reading. Estimated on its own the overlay
  reads BUR 2.21 against the line's 1.51 on Giant Steps and warps 144 beats
  against 224 — two voices of one performance, warped differently, drift apart
  on the page. The line's reading wins: a melodic stream of onsets is what the
  swing estimator is built for.
- Rests are kept in voice 2. A voice whose durations do not fill the bar does
  not add up, and a bar that does not add up is the one thing every MusicXML
  reader complains about. They can be hidden in the notation editor; an
  unreadable file cannot be fixed there.

Verified end to end on Giant Steps: 320 line notes plus 235 offered, 67 bars,
**all 67 measures add up in both voices**.

In the app it is a `2nd voice` chip in the edit bar (key `V`), shown only when
there is an overlay to show, drawn outlined rather than filled and underneath
the line — it must never be mistaken for a note we are claiming was played.
Deleting an overlay note in the GUI is not wired yet; the erasure index space
is keyed to `notes`. Export it and delete in the notation editor for now.


## The overlay was the wrong shape. Gap-filling is the right one.

The listener's verdict on the second voice, after using it:

> I am finding the polyphonic piano transcriptions less useful. They're too
> messy and it is difficult visually to see what to keep. [...] stick to a
> monophonic melody, recording only the top note.

That is not a rejection of the oracle. It is a rejection of *showing* the
oracle. The evidence for that is one bar.

### One bar, traced to the frame

Bar 4 of Sonny Clark's solo on *There Will Never Be Another You* is eight
straight eighths at 200 bpm, and the listener counted five in ours where they
had written eight. The frame trace says where each one went:

| the note | in raw CREPE f0? | why it was lost |
|---|---|---|
| Bb4 | yes, 6 frames, periodicity up to 0.83 | survived gating for 4 frames = 40 ms, under `min_note_ms` 60 |
| Eb4 | yes, 10 frames, pitch rock-steady | periodicity never cleared 0.53 against a threshold of 0.5 |
| B3 | yes, 5 frames | same, plus the duration floor |

All three are notes CREPE *found* and the segmenter threw away, because on a
piano the previous note is still ringing when the next is struck and the
tracker's confidence collapses at every transition.

### Loosening the gates does not work, and the sweep says so

The GUI had already cached raw f0, periodicity and energy for six spans, all
six with hand transcriptions, so every gating rule could be re-run at zero
CREPE cost and scored with the time-free pitch aligner. Baseline P 0.715 /
R 0.762 / F1 0.735. Every knob, one at a time:

| change | precision | recall | F1 |
|---|---|---|---|
| `voicing_threshold` 0.5 -> 0.2 | 0.715 -> 0.663 | 0.762 -> 0.786 | 0.735 -> 0.717 |
| `min_note_ms` 60 -> 25 | 0.715 -> 0.627 | 0.762 -> 0.788 | 0.735 -> 0.694 |
| `pitch_persist_ms` 60 -> 20 | 0.713 | 0.761 | 0.733 |
| a stability rescue at a lower floor | 0.664-0.711 | 0.768-0.783 | 0.716-0.736 |
| a confidence-weighted short-note floor | 0.659-0.708 | 0.767-0.778 | 0.708-0.733 |

**Nothing beats the current settings, and every route to more recall costs
about two false notes per true one.** The thresholds are not mistuned. Short
true notes and short false notes are not separable by anything the monophonic
path can see — including confidence, which was the obvious candidate and does
not work here either.

### The oracle already heard all three

Every one of the three missing notes is in the polyphonic model's output for
that bar — Bb4 at 79.518, Eb4 at 79.937, B3 at 80.354 — sitting in the second
voice, next to D3, F3, C3, C#3 and G3, which are Clark's left hand. **The
overlay was unreadable for exactly the reason it was useful: it shows the top
two of every simultaneity, and most simultaneities are left hand.**

So the filter should not be "top two of each cluster". It should be "**where
is the line missing something?**" — `corroborate.fill_gaps`:

- **a hole, not a disagreement.** If the line already has a note within 60 ms
  we keep ours. Correcting a wrong pitch is `snap_octaves`' job; doing it here
  would put two notes on one grid position in a single-line score.
- **the line's own register**, +/- an octave of the median pitch within a
  second. Without this the left hand walks straight back in.
- **the oracle's velocity**, above 0.45 normalised. Its quietest reports are
  pedal ring and sympathetic resonance; the melody is rarely the softest thing
  sounding. (Same cue as the melody-selection finding above, used again.)
- **half a claimed duration counts as covering.** Our durations are the gated
  extent of a pitch, not the played length, so a note's frames run past where
  the next one starts. At face value they close the hole immediately after
  every note.

Measured on four piano spans, line alone against line plus gap-fill:

| span | F1 | recall | notes added |
|---|---|---|---|
| Sonny Clark / There Will Never Be Another You | 0.811 -> **0.827** | 0.842 -> **0.907** | +38 |
| Carl Perkins / For Minors Only | 0.697 -> **0.724** | 0.645 -> **0.710** | +12 |
| Sonny Clark / Melody For C | 0.707 -> **0.750** | 0.697 -> **0.780** | +70 |
| Wynton Kelly / Soul Station | 0.490 -> **0.503** | 0.538 -> **0.580** | +24 |
| **mean** | **0.676 -> 0.701** | **0.680 -> 0.744** | |

All four improve on recall *and* F1. Precision costs 0.011 for 0.064 of
recall — a 6:1 trade in the direction the listener asked for, against the
roughly 1:2 that every gate change offered. The parameter surface is flat: F1
sits between 0.698 and 0.703 across the whole range swept, so this is not a
knife-edge fit. Lowering the velocity floor to 0.35 buys recall 0.783 at
precision 0.639 if more is wanted; it is a dial, not a constant.

Three things follow:

- `piano_fill_gaps` is **on by default** for piano, and `uses_piano_oracle`
  still gates it, so a horn never sees it. The reason a horn must never is
  unchanged and now has a second edge: a piano model asked about a saxophone
  vouches for nothing, so *every* hole would look unfillable and the register
  test would be measuring noise.
- `piano_second_voice` is **off everywhere**, GUI included. The recall it
  existed for now arrives inside one line.
- **The missing-note problem is a piano problem.** On the same sweep the two
  horn spans read recall 0.917 (Art Pepper) and 0.936 (Hank Mobley), against
  0.538-0.697 for the four pianos. Nothing here applies to a horn because
  nothing here is wrong on a horn.

### The routing trap, seen once more

The solo that prompted all of this was transcribed with `ensemble: horn-led`
because that is what produced a readable monophonic line. It is a piano solo.
`horn-led` on a pianist skips the oracle entirely — the octave snapping, the
corroboration, and now the gap-filling. The setting that gives the listener
what they want is `trio`, and it always was; the overlay was what made `trio`
unpleasant to use. Check the routing before believing a piano number
(CLAUDE.md) now cuts both ways.
