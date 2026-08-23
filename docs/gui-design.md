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

1. ~~**`region` in the ingest config.**~~ **DONE, but on `transcribe`, not `ingest`.**
   An earlier draft of this doc put `region` on ingest; that was wrong. With chained
   cache keys, a region on ingest changes every downstream key, so picking a new solo
   would re-run *separation* — the opposite of what we want. `transcribe.region:
   [start, end] | null` (null end = "to the end") keeps ingest/separate/beats
   whole-file and cached, so switching solos re-runs only transcription. Note onsets
   stay in whole-track time.
2. **`transcribe.stem` config** replacing the hardcoded `"other"`. **DONE.**
3. **Separation stays whole-file** even when transcription is span-limited — Demucs
   degrades on short crops, and whole-file stems cache once and serve every span.
   **DONE** (falls out of requirement 1).
4. **Per-stage progress callbacks.** Multi-minute CPU stages cannot present as a
   frozen tab. *Still to do.*
5. **A stem-audition entry point** that returns (or writes) the isolated stem for a
   span without running transcription at all — the thing screen 3 plays.
   **DONE:** `swingscribe audition <file> --stem guitar --start 90 --end 210`, which
   runs ingest + separate only.

## Framework question — RESOLVED: FastAPI + a hand-written frontend

Decided before building screens 1-3. This **overrides plan §2's Gradio choice for
the local tool**; Gradio stays the plan for the public Space at M9.

**Why not Gradio.** The two blocking features are not coming. The request for
time-aligned editable regions on `gr.Audio` (gradio#9740) was closed *as not
planned*, labelled "users can implement themselves"; `waveform_options` offers
`trim_region_color` and nothing resembling a draggable A/B loop or a two-tier view.
So the real comparison was never "Gradio's widget vs. a waveform library" — it was
"write the waveform inside a Svelte custom component, or write it on a plain page".
The frontend cost is identical; only the framework constraint differs.

On this machine the custom-component path also costs more than the docs suggest:
`gradio cc` needs Node 20+/npm 9+, neither of which is installed, and adding them
means another `NODE_EXTRA_CA_CERTS` fight with the intercepted TLS plus a
`node_modules` tree under OneDrive — the same class of trap as the uv hardlink
failures in CLAUDE.md.

**Why FastAPI.** Every interaction that must feel immediate is local: nudging a
loop point ±0.1s, tapping A while the music plays, soloing a stem, switching
isolated-against-original mid-phrase. Gradio round-trips each of those through the
server. Here the server does only what the browser cannot — list files, read peaks,
cut a span out of a stem, run Demucs — and everything else is client-side.

**What it costs.** ZeroGPU is Gradio-SDK-only, so this forecloses running *these
screens* on ZeroGPU. That is judged acceptable: a public demo is "upload a file,
pick a stem, get MusicXML", which is a small Gradio app; the precise-selection
workflow is inherently the local tool, working against a warm separation cache. The
discipline this demands is that `gui/` stays a thin adapter over `pipeline.run` and
`Config` — never a second brain — so the Space reuses the core rather than the UI.

**No waveform library either.** wavesurfer.js was the intended renderer and was
dropped during implementation. Both tiers need things it makes awkward: the detail
tier renders an arbitrary time *window*, so its local time frame is offset from the
track's, and the audition tier draws the isolated stem *over* the original mix.
Reduced to painting an envelope from peaks the server already computes, it earned
nothing. The canvas renderer in `static/waveform.js` is ~330 lines and the frontend
has **no JS dependencies and no build step** — no Node, no npm, no bundler.

## How screens 1-3 are built

- `swingscribe gui [track]` serves on 127.0.0.1 and opens a browser.
- **Peaks, not audio, cross the wire for drawing.** The server sends a min/max
  envelope (`gui/peaks.py`); the browser never decodes a five-minute file to draw it.
  The whole-track overview is memoized under the cache dir.
- **Two playback engines**, because the two halves want different things:
  - *Screens 1-2*: one `<audio>` element on the whole mix. Range requests make
    seeking instant, memory cost is nil, and `preservesPitch` gives tempo change free.
  - *Screen 3*: WebAudio `AudioBufferSourceNode`s, one per stem, all scheduled from
    a single instant. Stems from one separation are highly correlated, so even ~10ms
    of drift comb-filters into a swish that sounds exactly like bad separation —
    media elements cannot guarantee better. Sample-locked, and gapless when looping.
- **Speed on screen 3 is server-side** (`gui/audio.py`, torchaudio phase vocoder).
  `AudioBufferSourceNode.playbackRate` resamples and therefore transposes; the
  browser's pitch-preserving path exists only on media elements, which the sync
  requirement rules out. Stretching server-side keeps every source at rate 1.0 and
  therefore still locked. Measured ~0.9s for a 71s stereo span at half speed, and
  every stem of a span comes back byte-identical in length.
- **Separation runs as a background job** with real progress from demucs' callback
  (`model_idx_in_bag` + `segment_offset/audio_length`), polled once a second.
  Screens 1-2 stay usable throughout, since they need only ingest.
- **Per-track UI state** (span, stem, model) is a sidecar under the cache dir. It is
  UI state only: `Config.stage_config()` now rejects any section that is not a
  pipeline stage, so `gui.*` can never reach a cache key and discard a separation.

## Deliberately out of scope for v1 of the GUI

Hand-editing transcribed notes; batch queues; notation editing beyond export.
MuseScore already does the last one.

## Sources

- https://apps.apple.com/us/app/anytune-pro-music-practice/id478293637
- https://anytune.zendesk.com/hc/en-us/articles/360025901972-Looping
- https://www.anytune.app/
