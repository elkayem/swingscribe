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

### 4. Transcribe & review — BUILT
Piano roll over the waveform, the A/B ear-test render, and a diagnostic overlay
(f0, periodicity, gate decisions) so a suspicious note traces to a cause.

**A piano roll alone is a picture; wired to the frame trace it is a
diagnostic.** Clicking a note surfaces the frames that produced it — how many,
their mean periodicity against the voicing threshold, how many failed the energy
gate, the raw f0 spread across the note, and whether a detected onset sits at
its start. Two lanes beneath the roll carry the same evidence continuously: raw
CREPE f0 (dim) against the gated-and-smoothed pitch (bright), so the gaps
between them *are* the frames gating removed; and periodicity against its
threshold with energy-gate failures shaded.

Notes are drawn over the bar grid from screen 2, because a wrong downbeat is
invisible in a note list and obvious the moment notes sit against bar lines.
Note opacity tracks confidence, so an uncertain note looks uncertain.

**Fragmentation is reported at span level**, not just per note: the summary
counts consecutive same-pitch notes butted together ("6 split same-pitch
pairs"), which is the first thing that says whether the transcription is
breaking held notes. Clicking one says *which mechanism* split it — a detected
onset (open issue #1: the onset detector fires on the whole stem, so comping or
drum bleed breaks a note the soloist is holding) or a gate dropout in the gap
(periodicity or energy). Reporting "fragmented" without saying which would leave
the actual question unanswered. Measured on a 30s piano-stem span of Gerry's
Blues: 87 notes, 6 fragment pairs, and every one of them was a periodicity
dropout rather than an onset split.

Implementation notes:

- **`transcribe.analyze()`, not `pipeline.run`.** analyze() returns the
  FrameDiagnostics the pipeline discards. The result is cached under
  `gui/reviews/`, keyed by the stem digest + model + the whole transcribe
  config — *not* written into the pipeline's chained-key stage cache. The GUI
  must never construct a pipeline cache key: getting it subtly wrong poisons the
  cache with results the config does not describe. The cost is that a later
  `swingscribe ab` re-runs CREPE (~30s); that is the safe trade.
- **Span bounds are rounded server-side** (`SPAN_PRECISION`) before they reach a
  key. The job POST sends raw floats and the review GET sends `toFixed(3)`, so
  without one shared rounding point those are different spans and the GET never
  finds the job's work — which is exactly the bug that showed up first.
- **The A/B render is just another source** in the sample-locked engine, so
  original-vs-transcription switches mid-phrase carry the same guarantee as the
  audition mixer. Verified byte-identical in length at 1x and 0.5x. Synthesis is
  the core's `abmix.notes_to_midi`; slowing it shifts note times rather than
  resampling, so the pitch is exact.
- Transcription is a `kind="transcribe"` job on the existing background-job
  machinery, keyed by a `variant` so two spans never dedupe onto each other.
  ~30s for a span, since separation is cached.

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
- **The beat grid is drawn over the waveform** — downbeats as dots with a faint
  bar line (and bar numbers when zoomed), other beats as ticks — so "did it hear
  the bars right?" is answerable before transcription runs; a wrong meter (see
  open-issues #5) is visible at a glance instead of surfacing as mangled
  notation later. The grid is whole-file and chained from the selected model's
  drum stem, so it loads free on any track+model the pipeline has already
  processed; otherwise the Beats chip runs a kind="beats" job (the GET endpoint
  never computes — `pipeline.cached_document` peeks at the cache chain without
  executing anything). Snap mode places A/B on the nearest beat during drags and
  taps; nudges deliberately never snap, since ±0.1s is how you correct the
  grid's own small errors. Density-guarded: at zooms where beats would be
  sub-pixel, they don't draw.
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
