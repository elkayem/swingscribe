# SwingScribe GUI — design notes

Detail behind plan §13. Written while M3 was still being debugged, so treat the
core-integration notes as requirements and the UI specifics as a starting point.

## The premise

Anytune Pro+ (iPad) is the reference. It is a **transcribe-by-ear** tool: it helps a
musician find a passage, slow it down, loop it, and work the notes out by hand.
SwingScribe transcribes *for* you. So the overlap is not the whole app — it is
precisely the front half:

> **finding, isolating, and auditioning the passage you care about.**

That front half is exactly what our pipeline currently lacks and what makes it
frustrating to use: you point it at a five-minute tune and wait ten minutes for a
whole-track result when you wanted ninety seconds of one solo.

## What to take from Anytune

| Anytune feature | Take it? | Why |
|---|---|---|
| **Two-tier waveform** (overview + zoomed detail) | **Yes — core** | Selecting a solo boundary to ±0.1s inside a 5-minute track is impossible on a single full-width waveform. Overview for navigation, detail for the edit. |
| **A/B loop points set on the fly** | **Yes — core** | Tap A when the solo starts, B when it ends, while listening. Far better than typing timestamps. |
| **Loop playback of the selection** | **Yes — core** | The audition step *is* looped listening. |
| **Named marks with comments** | **Yes** | "Milt's solo", "head out" — matches how you actually navigate a tune, and gives the export something to label spans with. |
| **AutoLoop** (A/B snap to marks around playhead) | **Yes, later** | Cheap once marks exist; makes jumping between solos one gesture. |
| **Tempo change without pitch change** | **Yes** | Half-speed playback is how you verify a dense bebop line by ear — for auditioning isolation *and* for checking our output. torchaudio has a phase vocoder; no new heavy dep. |
| **ReFrame** (vocal/instrument isolate) | **Superseded** | Their version is EQ/mid-side trickery. We have real source separation — 6-stem Demucs is strictly better. This is our audition step. |
| **FineTouch EQ** | **No** | Solved better by separation for our purposes. |
| **Pitch shift ±24 semitones** | **Maybe, low priority** | Useful for transposing-instrument work at M5, not for auditioning. |
| Step-it-up, interval trainer, LiveMix | **No** | Practice-tool features. Not our product. |

**Where we beat the reference:** their isolation is a filter; ours is a trained
separation model, and we can offer per-stem solo/mute of a real six-way split.
Nothing in Anytune outputs notation.

## Screens

### 1. Load & navigate
Waveform overview of the whole track, transport, playhead. Marks rail beneath.

### 2. Select the span
Two-tier waveform: overview with the selection shaded, detail view around the
playhead for precise edits. A/B set by button while playing, then draggable, with
nudge controls (±0.1s) — solo entries never land on tidy seconds. Loop the selection.

### 3. Isolate & audition ★ *the gate*
Pick separation model and lead stem (`other`/`guitar`/`piano`/`vocals`/`bass`).
Play the isolated stem looped over the selected span, at adjustable speed, ideally
A/B against the original mix.

**This screen decides everything downstream.** If the soloist is not clearly
dominant here, no threshold tuning later will rescue the transcription — the user
should change stem or model, or accept the passage is not separable. Getting this
judgement to happen in 20 seconds of listening rather than 10 minutes of compute is
the single biggest workflow win available to us.

### 4. Transcribe & review
Piano roll over the waveform, the A/B ear-test render, and a diagnostic overlay
(f0, periodicity, gate decisions) so a suspicious note traces to a cause.

### 5. Notate & export
Notation, swing marking, transposition, MusicXML/MIDI out.

## What the core must provide (build before/with the GUI)

These are pipeline changes, not UI work, and the GUI is unusable without them:

1. **`region: [start, end] | null` in the ingest config.** A span must be a
   first-class job parameter so it participates in the cache key. Then transcribing a
   second solo from the same tune reuses separation and re-runs only what changed.
2. **`transcribe.stem` config** replacing the hardcoded `"other"`.
3. **Separation stays whole-file** even when transcription is span-limited — Demucs
   degrades on short crops, and whole-file stems cache once and serve every span.
4. **Per-stage progress callbacks.** Multi-minute CPU stages cannot present as a
   frozen tab.
5. **A stem-audition entry point** that returns (or writes) the isolated stem for a
   span without running transcription at all — the thing screen 3 plays.

## Framework question

Gradio is the plan's §2 choice, chosen for Hugging Face ZeroGPU compatibility at M9.
Its stock audio widget does **not** do precise draggable region selection or two-tier
waveforms, so screen 2 likely needs a custom component (Gradio supports these, at
some cost) or a different stack (e.g. a small FastAPI + wavesurfer.js frontend) with
Gradio kept only for the eventual public Space. **Resolve this before building
screen 2** — it is the highest-risk unknown in the GUI work.

## Deliberately out of scope for v1 of the GUI

Hand-editing transcribed notes; batch queues; notation editing beyond export.
MuseScore already does the last one.

## Sources

- https://apps.apple.com/us/app/anytune-pro-music-practice/id478293637
- https://anytune.zendesk.com/hc/en-us/articles/360025901972-Looping
- https://www.anytune.app/
