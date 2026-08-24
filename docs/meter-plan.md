# Meter, downbeats, and bar lines — proposal

Status: **implemented.** Covers the GUI changes requested (bar lines, downbeat
colour, estimated beats, user-chosen downbeat, time signature menu, no bars
during rubato) and how the result reaches the rest of the pipeline.

Two corrections landed during implementation, both from real data:

1. **Corner Pocket's opening is not half-time.** It is 4/4 at ~135 throughout;
   the tracker simply misses every other beat for the first 23 seconds. So the
   passage must be *repaired*, not treated as its own section — and a repair
   test based on a local median cannot see it, because the local median there
   is itself the wrong rate. `reference_pulse` is seeded from the global mode
   and only then smoothed, which catches it.
2. **Repair can disguise rubato.** Subdividing irregular gaps produces evenly
   spaced beats that look perfectly steady precisely because they were
   manufactured. Three rules keep fabrication from voting for its own
   metricality: stability is judged against the reference pulse rather than a
   post-repair local median; a span must begin and end on a *detected* beat;
   and `min_span_beats` counts detected beats only.

## What the data says

Measured on the two tracks with cached grids, comparing each inter-beat
interval (IBI) against a *local* median (window ±4 beats):

| | Gerry's Blues (ft) | Corner Pocket (6s) |
|---|---|---|
| beats / downbeats | 704 / 266 | 602 / 231 |
| IBI deviation vs local median | median 0.00%, 90th pct 4.8% | median 0.00%, 90th pct 4.8% |
| beats off local median by >15% | — | 23 of 601 |
| beats between consecutive downbeats | `{2: 131, 4: 99, 1: 30, 3: 5}` | `{4: 81, 2: 67, 1: 58, 3: 19, 5: 3, 6: 2}` |

Two conclusions, and they drive everything below:

1. **The pulse layer is excellent.** Better than 95% of beats sit within 5% of
   their local neighbours. This is a reliable ruler.
2. **The downbeat layer is noise.** If bars were real, the beats-between-downbeats
   histogram would be a single spike. Instead it is spread across 1–6.
   `infer_beats_per_bar` takes the median of that, which is how both tunes ended
   up claiming 2 beats per bar — open-issue #5, now quantified.

So: **stop drawing detected downbeats. Derive bar lines by counting beats.**
That is also exactly what makes "click a dot to move the downbeat" a
one-parameter change rather than a re-analysis.

One more finding that shapes the rubato work: Corner Pocket's first 29 beats
run at 0.82 s IBI and the rest at 0.44 s — the tracker is in half-time for the
first 23 seconds, then switches. Any stability test must use a **local**
median, never a global one, or the entire intro reads as an error.

## The model

A bar grid is three numbers, not a list:

- **beats** — the detected pulse (trusted, unchanged)
- **pulses_per_bar** — how many tracked beats make a bar
- **anchor** — a time in seconds identifying a beat that is beat 1

Bar lines are then every *n*-th beat counted outward from the anchor. Tempo
drift is handled for free, because bar lines land on real detected beats whose
spacing already drifts. Nothing needs to model *rall.* explicitly.

### Time signature is not pulses-per-bar

Worth separating now, because 6/8 breaks the naive equivalence. beat_this
tracks a *pulse*; the notated meter is a separate fact:

| Time signature | pulses_per_bar | each pulse is |
|---|---|---|
| 4/4 | 4 | quarter |
| 3/4 | 3 | quarter |
| 6/8 (in 2) | 2 | dotted quarter |
| 6/8 (in 6) | 6 | eighth |

So the menu picks a time signature *and* a pulse interpretation. Defaults per
entry, with `pulses_per_bar` separately overridable for the ambiguous ones.
Storing both means notation at M6 gets the real signature rather than
back-inferring it.

### Designing now for meter changes and rubato

This is the "good idea" worth adopting up front: make the meter a **list of
sections**, and expose exactly one in the v1 UI.

```python
class MeterSection(BaseModel):
    start: float  # seconds, inclusive
    end: float  # seconds, exclusive
    pulses_per_bar: int
    beat_unit: int  # denominator: 4 = quarter, 8 = eighth
    time_signature: tuple[int, int]
    anchor: float  # seconds; a beat that is beat 1
    bar_number: int = 1  # bar number at `anchor`
    origin: str  # "detected" | "user" | "default"
```

`Document.meter: list[MeterSection]`. Then:

- **v1** emits one section spanning the metrical part of the tune.
- **Rubato is the absence of a section.** No special "is_rubato" flag, no second
  concept — time not covered by any section simply has no bars. That falls out
  of the list for free.
- **Meter changes later** are additional sections. No schema change, no cache
  migration, no rework of the drawing code, which already iterates sections.

That is the whole reason to build the container now even though the UI only
ever shows one section.

## Algorithms

Three pure functions in a new `stages/meter.py`, each independently testable
against synthetic grids:

**1. `repair_beats(beats) -> list[Beat]`** — insert beats the tracker dropped.
For each gap, `n = round(gap / local_ibi)`; if `n >= 2`, insert `n-1` evenly
spaced beats flagged `implied=True`. This matters for correctness, not
cosmetics: one missed beat shifts every bar line after it by one beat. Gerry's
Blues needs exactly one such repair; Corner Pocket's apparent 41 "gaps" are the
half-time intro and must *not* be repaired, which the local-IBI test handles
correctly. The inverse case (a spurious extra beat at ~0.5× local IBI) is
detectable the same way; propose flagging but not auto-removing in v1.

**2. `metrical_spans(beats) -> list[(start_idx, end_idx)]`** — maximal runs of
at least `MIN_SPAN_BEATS` (~8) consecutive beats whose IBI is within `TOL`
(~15%) of the local median. On the measured data this flags 23 of 601 beats on
Corner Pocket and cleanly isolates the half-time intro as its own span.
Deliberately conservative: wrongly hiding bars the user wants is worse than
drawing bars through a slightly ragged passage.

**3. `derive_sections(beats, spans, config) -> list[MeterSection]`** — apply
`pulses_per_bar` and `anchor` to produce sections. The anchor's own span is
authoritative. For a span disjoint from the anchor's, the bar count is
continued across the gap only when the gap can be filled with a whole number of
implied beats; otherwise that span restarts at bar 1 and is marked lower
confidence. (Rubato is usually intro/outro, so this is low-stakes — but it
should be explicit rather than accidental.)

Default anchor when the user has not chosen one: the beat, within the first
`pulses_per_bar` beats of the longest span, that maximises agreement with the
detected downbeat list. The downbeat layer is noise, but it is *biased* noise,
so it is a better-than-random first guess — and the user can move it in one
click.

## Where the overrides live

This is the part that must not be got wrong, because it decides whether
changing the downbeat costs a click or thirteen minutes.

New `MeterConfig` section in `Config`, added to `STAGE_SECTIONS`:

```yaml
meter:
  time_signature: null      # [4, 4] etc; null = infer
  pulses_per_bar: null      # null = from time signature, or infer
  anchor: null              # seconds; null = auto-detect
  min_span_beats: 8
  stability_tolerance: 0.15
```

New `meter` stage registered **after `transcribe`**, not next to `beats`:

```
ingest → separate → beats → transcribe → meter → swing → quantize → notate
```

The placement is deliberate and is the whole cache argument. Chained keys mean
a stage's config invalidates everything downstream of it. Meter sits below
transcription because transcription does not use it — so moving the downbeat
re-runs only swing/quantize/notate (milliseconds), never CREPE (minutes) and
never separation. Putting `meter` next to `beats`, where it conceptually
belongs, would make every downbeat click cost a full re-transcription.

**`beats.py` is not touched at all**, so the expensive cached beat grids stay
valid. (If we ever do bump that stage, fold in open-issue #7's `BeatGrid.source`
at the same time.)

**The GUI does not run the pipeline to preview meter.** `derive_sections` is a
pure function over an already-cached `BeatGrid`, so the GUI calls it directly
and every meter/anchor change redraws instantly with no job and no cache write —
the same pattern as `pipeline.cached_document`. The stage exists so the *pipeline*
gets the same answer, not so the GUI can ask the question.

**Reaching the rest of the software**, three linked paths:

1. `Document.meter` is the single producer for swing/quantize/notate at M4+.
2. CLI flags `--time-signature 4/4` and `--downbeat 12.34` fold into
   `MeterConfig` via the existing `apply_overrides`, so they participate in
   cache keys honestly.
3. The GUI's handoff command emits those flags alongside `--stem`/`--start`/
   `--end`, and the per-track sidecar remembers the choice for the GUI itself.

So the answer to "how does the downbeat reach transcription" is: it is config,
it is in the cache key, and the handoff command carries it. No hidden channel.

## UI changes (screen 2)

- **Bar lines only at bar starts.** Full-height line plus a filled dot in the
  downbeat colour. Every other beat keeps its small baseline tick. This is the
  direct fix for the current mess, where a full line is drawn at each of 266
  bogus detected downbeats.
- **Implied beats** (inserted by `repair_beats`) draw as a hollow dot — visibly
  the software's guess, not a detection.
- **Click a dot to set the downbeat.** Hit-test the bottom ~14 px strip within
  ~6 px of a beat marker; cursor and hover highlight make it discoverable, and
  clicks elsewhere still seek. Also `D` = "make the beat nearest the playhead
  the downbeat", which is the better gesture while the music is playing.
  Re-derives instantly; all bar lines shift together.
- **Time signature menu**: 4/4, 3/4, 6/8, 5/4, 2/4, Custom… (free numerator/
  denominator plus pulses-per-bar). Applies to the whole tune, per the stated
  assumption.
- **Rubato regions** draw with no bar lines and a faint dimmed band labelled
  "no steady pulse", so their absence reads as a decision rather than a bug.
- **Bar numbers count from the anchor**, so the number under a bar line is the
  bar you would call it.

## Suggested additions

Three, in the order I would rank them. All are small once bars exist, and all
serve the actual goal of isolating a solo.

1. **Chorus lines.** A `bars_per_chorus` setting (12, 16, 32, custom) drawing a
   heavier line every N bars, and snap-to-chorus for A/B. Jazz solos are whole
   choruses; this turns "select the tenor solo" into two clicks and makes an
   off-by-one boundary obvious. Highest value per line of code of anything here.
2. **Click track in the audition.** A checkbox mixing a click at the bar lines
   into the isolated-stem playback, reusing `click.py`. Ears verify a grid far
   better than eyes do — a bar line one beat off is instantly audible and easy
   to miss visually. This makes the meter genuinely checkable at the gate.
3. **Snap-to-bar** as a third snap mode (off / beat / bar). Solos start on
   downbeats, so bar snapping is usually what is wanted; beat snapping is the
   finer fallback.

Two I would **not** build: automatic time-signature detection (the downbeat
layer is demonstrably too weak to trust, and a wrong automatic answer is worse
than a menu), and automatic rubato *classification* beyond the conservative
stability test above.

## Migration impact

Per CLAUDE.md, spelled out:

- `model.py`: adds `MeterSection` and `Document.meter: list[...] = []`. A new
  optional field with a default, so **existing cached Documents still
  deserialize** — no separation or beat grid is invalidated.
- `config.py`: adds `MeterConfig` and `"meter"` to `STAGE_SECTIONS`. Existing
  stage keys are unchanged, because `stage_config` only reads the named section.
- `pipeline.py`: registers `meter` after `transcribe`. Every stage downstream of
  it is unimplemented today, so nothing cached is invalidated.
- `beats.py`: untouched, no `CACHE_VERSION` bump, grids preserved.

Net: **no existing cache entry is discarded.**

## Phasing

| Phase | Content | Verifiable by |
|---|---|---|
| 1 | `stages/meter.py` pure functions + `MeterSection` + config + stage registration | unit tests on synthetic and real grids |
| 2 | Drawing: bar lines, downbeat colour, implied dots, rubato bands, bar numbers | the two cached tracks |
| 3 | Interaction: click-to-anchor, `D` key, time signature menu, snap-to-bar | manual + DOM assertions |
| 4 | Handoff: CLI flags, sidecar persistence, GUI command emission | round-trip test |
| 5 (opt) | Chorus lines, click track | by ear |

Phases 1–2 are the ones that answer "did it hear the bars right?", which is the
question you actually asked. 3–4 make the answer stick.

## Decisions taken

1. **Anchor is stored in seconds**, not as a beat index, so it survives a grid
   re-tracked with a different separation model or tempo hint; it re-snaps to
   the nearest beat on load.
2. **Corner Pocket's opening is repaired, not sectioned off** — it is in tempo,
   and the missing beats are restored (45 implied beats across the track).
3. **The meter menu is remembered per track** in the GUI sidecar; the config
   default stays `null`. The choice travels to the pipeline through the handoff
   command's `--time-signature` / `--downbeat` flags, which are ordinary config
   overrides and therefore participate in the cache key.

## Measured result

| | Gerry's Blues | Corner Pocket |
|---|---|---|
| beats detected → repaired | 704 → 705 | 602 → 647 |
| metrical sections | 1 | 2 |
| bar lines | 176 | 160 |
| bar duration within a section | 1.58–1.78s | 1.38–1.82s |
| free time excluded | — | 20.2s outro |

Both now read 4/4 rather than the 2/bar the detected downbeat layer claimed.

## Round two: edges, the form, and moving around

Three questions from use, and what they turned into.

**"Why do the measures start at 6.6s?"** Because beat_this emitted no beat at all
before 5.86s — while the audio is at full level from 0.0s (measured RMS ~0.06
per half-second right from the start). The head is in tempo; the *tracking*
starts late. `extend_beats` now continues a steady edge pulse out to the ends of
the track, so Corner Pocket's first beat is 0.12s and it gains five bars at the
front. Guarded two ways: the edge pulse must be steady, and the reach is capped
(`max_extend_seconds`, default 12s) so a genuinely free intro stays bare.

The guard needed care. Judging edge steadiness on the *repaired* beats is
circular — repair makes a ragged head evenly spaced, so it always looks steady
enough to extrapolate from. The pulse value comes from the repaired spacing
(right even where the tracker ran at half rate), but steadiness is judged on
detected beats alone.

**"Why does it say 'free time'?"** Because the label fired whenever more than one
section existed, which reads as a claim about the whole tune. It now names the
amount and the place: `≈136 bpm · 4/4 · 37s unmetered`, with the exact ranges in
the tooltip.

**"Can I choose the first bar of the chorus?"** Yes — `form_start`, set by
shift-clicking any bar line. An intro is not part of the song structure, so bar 1
lands where the tune starts; bars before it number zero and negative and are
drawn without labels, and the chorus count starts there too.

**Getting around.** The overview's window box is now a scrubber — grab it and
slide to move the detail view. Shift+wheel and horizontal trackpad scroll pan;
plain wheel still zooms. And `⇤ A` (or Enter) restarts playback at the start of
the selection, since the transport otherwise plays from the playhead.

## Still deferred

- **Meter changes mid-tune** — the section list supports it; the UI exposes one
  section. Adding a second is a UI affordance, not a schema change.
- **Manually marking a rubato passage**, for when the conservative automatic
  test disagrees with the player.
- **A click track over the audition**, which would let the ear check the grid;
  eyes miss a bar line that is one beat out.
