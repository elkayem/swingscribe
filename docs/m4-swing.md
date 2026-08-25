# M4 — SwingModel

The stage that makes this project itself rather than a wrapper. Plan §5 stage 4.

Every onset falls somewhere inside a beat, at a phase
φ = (onset − beat_start) / beat_length. Straight eighths put the offbeats at
φ = 0.5; swung eighths put them late, and BUR = φ / (1 − φ). Triplet swing is
φ = 0.667 → BUR 2.0.

Reproduce the synthetic results with `uv run pytest tests/test_swing.py`; the
whole stage is pure arithmetic and runs in CI, acceptance criterion included.

## Acceptance: met

Plan §5 asks for recovery of an injected BUR within ±5%. Over the plan's
matrix — BUR ∈ {1.0, 1.3, 1.6, 2.0, 2.5} × tempo ∈ {80, 120, 180, 260} — the
error on clean onsets is **0.00% in every cell**. Straight eighths are
correctly reported as straight and not classified as swung, at every tempo.

That is the easy half. The rest of this file is what happens when the onsets
are not clean.

## What onset jitter costs

Real onsets are not exact, so the useful question is how much error the
estimator inherits. Measured, per 16-beat window:

| jitter | 80 bpm | 120 bpm | 180 bpm | 260 bpm |
|---|---|---|---|---|
| 0 ms | 0.0% | 0.0% | 0.0% | 0.0% |
| 5 ms | 0.9% | 1.3% | 2.0% | 2.9% |
| 10 ms | 1.8% | 2.6% | 4.3% | 5.6% |
| 20 ms | 3.6% | 4.8% | 7.8% | 12.0% |
| 30 ms | 4.8% | 7.8% | 12.7% | 24.8% |

A fixed timing error is a larger fraction of a shorter beat, so the cost grows
with tempo — at 260 bpm a beat is 231 ms and 10 ms of jitter is 4.3% of it.
**±5% BUR needs onsets good to about 10 ms**, and that is a requirement on the
transcriber, not on this stage.

The estimator is at its sampling limit: measured phase bias is +0.0002 and the
spread matches the standard error of a median, 1.253·σ/√n. There is no
accuracy left to win here. Reaching ±5% at 260 bpm would need ~75 beats per
window — 19 bars, far too long to see a player change feel.

One bug was found and fixed on the way. With ~16 offbeats spread over 0.02
bins, raw histogram counts are 1–3 and ties decide the peak; breaking them by
bin index biased BUR **low by ~2% at every tempo**. Smoothing the histogram
and breaking ties toward the window median removed it (bias −0.010 → +0.0002).
`test_dominant_phase_is_not_biased_by_histogram_ties` guards it, because the
symptom is a small systematic shift rather than a failure.

## On real music

Run over the three benchmark solos, using their own beat grids:

| | Confirmation | All The Things | Giant Steps |
|---|---|---|---|
| soloist | Dexter Gordon, tenor | Hank Mobley, tenor | Tommy Flanagan, piano |
| tempo | 187 bpm | 194 bpm | 249 bpm |
| offbeats in the solo | 432 | 212 | 159 |
| **median offbeat phase** | **0.640** | **0.663** | **0.602** |
| confidence-weighted BUR | **1.79** | **2.16** | **1.55** |
| windows classified swung | 81% | 72% | 73% |
| median per-window confidence | 0.32 | 0.25 | 0.27 |
| phase spread (stdev) | 0.117 | 0.134 | 0.106 |

The aggregate numbers are musically right: both tenor solos land near the
triplet feel, and Giant Steps at 249 bpm is markedly narrower — which is the
tempo/BUR relationship the plan predicts and the literature reports.

## The honest limitation: per-window classification is weak

Per-window confidence is low (0.25–0.32), and that is not pessimism, it is the
measurement. **Our real solos have offbeat phase spread 0.106–0.134 against
uniform random noise's 0.144.** They are only slightly tighter than random.

That has a hard consequence. Deciding "is this window swung, or is there no
eighth-note grid here at all?" needs a statistic that separates real playing
from scatter, and at this window size none does:

| offbeats per window | 14 | 28 | 56 | 112 | 224 |
|---|---|---|---|---|---|
| separable by peak concentration | no | no | no | no | **yes** |
| separable by phase spread | no | no | **yes** | yes | yes |

A 16-beat window holds ~14 offbeats. Concentration needs ~224 (64 bars) and
spread needs ~56 (16 bars) — both too long to track a feel change, which is
the entire reason for windowing.

This killed the classifier the plan specifies. "Peak is well-separated" sounds
decisive but is nearly useless at 14 samples: uniform noise clusters as
tightly (median concentration 0.36) as a real solo does (0.38–0.44), because
small samples clump whatever they are drawn from. `is_swung` is therefore a
**z-test** — is the phase far enough above 0.5, relative to its own standard
error, to be worth warping — which is the question M5 actually needs answered.
Concentration survives only as a weak floor against the worst windows.

What the z-test cannot do is separate swing from noise, because uniform noise
over an offbeat region of 0.35–0.85 has median phase 0.60 and *genuinely is*
above straight. **`confidence` is where that shows up, and it works**:
scattered onsets score 0.22–0.37 against 1.0 for a clean swung line and
0.73–0.80 for a realistically noisy one. M5 should filter on confidence and
treat `is_swung` as a hint.

The binding constraint is upstream. Phase spread of 0.12 comes from real
expressive timing, our own onset error, sixteenth notes leaking in at φ=0.75,
and the ~215 notes per solo that belong to other instruments (open-issue #8).
Tightening any of those tightens this.

## The plan's hypothesis: partially supported

Plan §5 flags a hypothesis worth testing — that the *short* note's absolute
duration stays roughly constant (~100 ms) regardless of tempo, which would
explain the whole tempo/BUR relationship.

| tune | tempo | beat | median φ | short note |
|---|---|---|---|---|
| Confirmation | 187 bpm | 320 ms | 0.640 | **115 ms** |
| All The Things | 194 bpm | 309 ms | 0.663 | **104 ms** |
| Giant Steps | 249 bpm | 241 ms | 0.602 | **96 ms** |

Suggestive, and weaker than it looks. The two competing predictions for Giant
Steps are 87 ms (if φ were constant at Confirmation's 0.640) and 115 ms (if
the short note were constant in milliseconds). Observed is 96 ms — **between
them, and closer to constant-φ**. So the short note does shrink less than
proportionally with tempo, which is the direction the hypothesis predicts, but
it is not constant.

Three tunes, one take each, with per-window BUR noise of ±15% at these tempos.
This is a direction to test properly against a real corpus (WJazzD, plan §6
layer 2), not a result.
