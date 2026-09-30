"""Propose where the solos are, from the stems' envelopes and the bar grid.

A new listener's first job is to find a solo's A and B on a waveform
(docs/roadmap.md, O3). This proposes them from what the app holds before
anything is transcribed: the whole-file stems (the quick htdemucs_6s set
the batch locates with) and the repaired bar grid. docs/solo-spans.md has
the measurements, and scripts/solo_spans_survey.py reproduces them against
the 77 WJazzD solos annotated on the 49 recordings in benchmark/wjazzd/:

- a span edge lands within two bars of 71% of solo starts and 73% of
  ends (81% and 78% within 4 s), at 7.5 boundaries a recording, 0.46 a
  minute of them inside the annotated solos where they are wrong for sure.
  The same number of boundaries dropped on bar lines at random finds 0.12;
- 35 of the 77 solos have both edges within two bars, 21 of those as ONE
  proposed span -- a single click;
- a found start sits a median 0.4 bar BEFORE the first note, a found end
  a median third of a bar after the last: the side a span should err on,
  since a pickup belongs to the solo;
- the span's lead label is the stem whose chroma follows WJazzD's
  annotated line on 64 of the 69 located horn solos (htdemucs_6s), and is
  clearly another stem on 3 (`lead_stem`).

Only the penalty is cross-validated; every other choice here was made on
the same 77 solos (docs/solo-spans.md says which, and what a joint
cross-validation of the three discrete knobs reads held out).

Two cues, because they fail in different places:

- **Who is playing and how it sounds** (`bar_features`): each stem's level
  and the melodic stems' spectral shape (cepstra of their summed band
  power, over the frames where anything melodic sounds), pooled per bar.
  A handover from trumpet to tenor, or from the horns to the piano,
  changes both. The track is cut where the change is largest by optimal
  partitioning (`segment`): every cut must pay a penalty, so a cut is made
  only where the bars either side are different enough to earn it.
- **The head** (`find_head`): a soloist who also plays the melody -- every
  quartet, and Parker on his own heads -- sounds the same on both sides of
  the head's last bar, and no timbre cue can see that boundary. But the
  head is played again at the end and a solo is not: the horn stems' bar
  chroma repeats as one long diagonal stripe at a lag of most of the
  track. The head-in's last bar is a boundary where no timbre cut is near.
  Measured per recording against timbre alone: +0.049 of edges within two
  bars (interval +0.014 to +0.092; 6 recordings up, none down, sign test
  p = 0.031) and +0.053 within 4 s (+0.017 to +0.095; 7 up, none down).

What cannot work this way is in docs/solo-spans.md: a soloist who follows
his own head unchanged when the head is not repeated the same way at the
end, two soloists on one instrument (which the reference cannot test: it
holds no such handover), and anything inside an open vamp.

Pure numpy and the standard library's `wave`: no torch, no librosa, no
decoding beyond the PCM stems separation already wrote. The six stems are
read one at a time, averaged down to 22 kHz mono, and kept only as a
tenth-of-a-second envelope; proposing on those takes 0.05 s for the
longest track (647 bars). Only `match_boundaries`, the scoring control,
imports mir_eval, and lazily: it lives in the `ml` group, which CI lacks.
"""

from __future__ import annotations

import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ── reading the stems ────────────────────────────────────────────────────────

# Envelope resolution. A bar at 300 bpm is 0.8 s, so ten frames a second
# still gives eight per bar at the fastest tempo in WJazzD.
HOP_S = 0.1
# The stems are read at half the ingest rate: nothing a band energy needs
# lives above 11 kHz, and it halves the memory of a ten-minute stem.
READ_RATE = 22050
N_FFT = 2048
# Quarter-octave bands from 100 Hz (a horn's lowest fundamentals) to the
# read rate's Nyquist, plus one band under them for the bass and kick.
BAND_LOW_HZ = 100.0
BANDS_PER_OCTAVE = 4
# Pitch classes are read where a melody's fundamentals and first harmonics
# are, with a window long enough to resolve a semitone at 50 Hz's second
# harmonic.
CHROMA_N_FFT = 8192
CHROMA_LOW_HZ = 50.0
CHROMA_HIGH_HZ = 1000.0

# ── what the proposer reads ─────────────────────────────────────────────────

# Every stem a lead line can be filed under. htdemucs_6s files a horn under
# `guitar` or `vocals` on a fifth of the WJazzD tracks (CLAUDE.md), so the
# timbre cue sums them rather than trusting `other`.
MELODIC_STEMS = ("other", "vocals", "guitar", "piano")
# The head's melody, for the repetition cue. Not the piano: its comping
# repeats the chord changes every chorus of every solo, which is exactly
# the repetition the head has to stand out from.
HEAD_STEMS = ("other", "vocals", "guitar")
CHROMA_STEMS = HEAD_STEMS
# Cepstra are taken over 100 Hz - 8 kHz, and only over frames where the
# melodic stems are within GATE_DB of their loud level: between phrases a
# stem holds bleed, and bleed has the timbre of whoever else is playing.
CEPSTRUM_LOW_HZ = 100.0
CEPSTRUM_HIGH_HZ = 8000.0
N_CEPSTRA = 12
GATE_DB = 25.0
# A stem's level is read against its own 95th percentile over the track and
# floored, so a stem that is silent for a minute reads as silent rather than
# as a spike of -90 dB.
LEVEL_REFERENCE_PERCENTILE = 95.0
LEVEL_FLOOR_DB = -40.0

# Optimal partitioning. A cut must reduce the within-segment squared
# deviation by PENALTY per feature (the features are standardised over the
# track), and no segment is shorter than MIN_BARS unless it touches an end
# of the track. PENALTY is what two-fold cross-validation by recording chose
# on both folds (F2 over the WJazzD survey, docs/solo-spans.md). MIN_BARS
# at 4 or 12 reads F2 0.700 or 0.712 against 8's 0.706 on the same 77
# solos, and a joint cross-validation chose 8 on one fold and 12 (at
# penalty 3) on the other; 8 stays because it keeps an 8-bar trade whole,
# which the reference cannot test and a 12-bar floor would forbid.
PENALTY = 4.0
MIN_BARS = 8

# The head stripe. Chroma similarity is smoothed over HEAD_SMOOTH_BARS
# along each diagonal; the stripe runs while it stays above
# max(HEAD_FLOOR, peak - HEAD_DROP), across gaps of up to HEAD_GAP_BARS;
# its head-in half must start in the first HEAD_EDGE of the track and its
# head-out half end in the last; and the peak must reach
# HEAD_MIN_SIMILARITY before the stripe is believed (38 of the 49 WJazzD
# recordings). A track under HEAD_MIN_BARS cannot hold a head, a solo and
# the head again. Swept on the same 77 solos, at the shipped defaults:
# gap 2-8 reads alike and gap 0 loses two starts (0.71 -> 0.69 within two
# bars); similarity 0.8 believes 41 heads for the same recall, 0.9 only 25
# for 0.68; the floor never binds between 0.45 and 0.55, because every
# believed peak is 0.85 or more and peak - HEAD_DROP sets it. F2 0.686 to
# 0.707 over the whole grid, 0.706 here.
HEAD_SMOOTH_BARS = 4
HEAD_FLOOR = 0.55
HEAD_DROP = 0.3
HEAD_EDGE = 0.3
HEAD_MIN_SIMILARITY = 0.85
HEAD_MIN_BARS = 24
HEAD_GAP_BARS = 4
# A timbre cut this close to a head edge is the same boundary (`combine`).
MERGE_BARS = 4
# Which of the stripe's inner edges become boundaries. The head-in's end
# only: the head-out's start lands within two bars of an annotated solo's
# end on none of the recordings with a believed head, so the reference
# never once says it is right, and it adds boundaries (docs/solo-spans.md).
HEAD_EDGES = "in"
# A span whose melodic stems sit this far under their loud level is the
# rhythm section's (a bass or drum solo, fours with the drums).
QUIET_DB = -20.0


def band_edges(rate: int = READ_RATE) -> np.ndarray:
    """Band edges in Hz: [20, 100, 100*2^(1/4), ..., nyquist]."""
    top = rate / 2
    count = int(np.floor(np.log2(top / BAND_LOW_HZ) * BANDS_PER_OCTAVE))
    upper = BAND_LOW_HZ * 2.0 ** (np.arange(count + 1) / BANDS_PER_OCTAVE)
    return np.concatenate([[20.0], upper[upper < top], [top]])


def read_mono(path: str | Path, rate: int = READ_RATE) -> tuple[np.ndarray, int]:
    """A 16-bit PCM wav as mono float32 at `rate` (an integer divisor of its own).

    Read in blocks and averaged down, so a ten-minute 44.1 kHz stereo stem
    never exists in memory at full size. The boxcar average is a poor
    anti-alias filter and does not need to be better: what folds down is the
    octave above 11 kHz, where a separated horn stem holds almost nothing.
    """
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        native = handle.getframerate()
        frames = handle.getnframes()
        if width != 2:
            raise ValueError(f"{path}: expected 16-bit PCM, got {8 * width}-bit")
        factor = max(1, native // rate)
        out = np.empty(frames // factor, dtype=np.float32)
        block = factor << 18
        filled = 0
        while filled < out.size:
            raw = handle.readframes(block)
            if not raw:
                break
            data = np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)
            mono = data.mean(axis=1, dtype=np.float32) / 32768.0
            usable = (mono.size // factor) * factor
            chunk = mono[:usable].reshape(-1, factor).mean(axis=1)
            take = min(chunk.size, out.size - filled)
            out[filled : filled + take] = chunk[:take]
            filled += take
    return out[:filled], native // factor


def _frame_projection(
    samples: np.ndarray, rate: int, n_fft: int, hop_s: float, projection: np.ndarray
) -> np.ndarray:
    """(frames, k): each frame's power spectrum times `projection` (bins, k).

    One Hann window per hop, centred on the hop (frame i is time i * hop_s),
    not an overlapped STFT: this is an envelope read at bar resolution, and
    one window per tenth of a second is plenty to know how loud a stem is
    and where its energy sits.
    """
    hop = int(round(hop_s * rate))
    count = int(np.ceil(samples.size / hop)) if samples.size else 0
    half = n_fft // 2
    window = np.hanning(n_fft).astype(np.float32)
    out = np.zeros((count, projection.shape[1]), dtype=np.float32)
    offsets = np.arange(n_fft)
    step = max(1, (1 << 20) // n_fft)  # a million samples of frames at a time
    for start in range(0, count, step):
        stop = min(count, start + step)
        # The chunk's own stretch of signal, zero-padded where it runs off
        # either end -- never a padded copy of the whole stem.
        lo = start * hop - half
        hi = (stop - 1) * hop - half + n_fft
        piece = np.zeros(hi - lo, dtype=np.float32)
        a, b = max(lo, 0), min(hi, samples.size)
        if b > a:
            piece[a - lo : b - lo] = samples[a:b]
        index = ((np.arange(start, stop) - start) * hop)[:, None] + offsets[None, :]
        spectrum = np.fft.rfft(piece[index] * window, axis=1)
        power = (spectrum.real**2 + spectrum.imag**2).astype(np.float32)
        out[start:stop] = power @ projection
    return out


def band_power(samples: np.ndarray, rate: int, hop_s: float = HOP_S) -> np.ndarray:
    """(frames, bands) summed power per quarter-octave band (`band_edges`)."""
    edges = band_edges(rate)
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / rate)
    index = np.searchsorted(edges, freqs, side="right") - 1
    bands = len(edges) - 1
    member = np.zeros((freqs.size, bands), dtype=np.float32)
    inside = (index >= 0) & (index < bands)
    member[np.flatnonzero(inside), index[inside]] = 1.0
    return _frame_projection(samples, rate, N_FFT, hop_s, member)


def chroma_power(samples: np.ndarray, rate: int, hop_s: float = HOP_S) -> np.ndarray:
    """(frames, 12) power per pitch class, C first, from CHROMA_LOW_HZ to
    CHROMA_HIGH_HZ.

    A window four times the bands' (0.37 s), because semitones at 50-100 Hz
    sit 3-6 Hz apart; low notes are named by their second and third
    harmonics where the fundamental cannot be resolved.
    """
    freqs = np.fft.rfftfreq(CHROMA_N_FFT, 1.0 / rate)
    keep = (freqs >= CHROMA_LOW_HZ) & (freqs <= CHROMA_HIGH_HZ)
    classes = np.round(12 * np.log2(freqs[keep] / 440.0) + 69).astype(int) % 12
    member = np.zeros((freqs.size, 12), dtype=np.float32)
    member[np.flatnonzero(keep), classes] = 1.0
    return _frame_projection(samples, rate, CHROMA_N_FFT, hop_s, member)


@dataclass(frozen=True)
class StemEnvelopes:
    """Per-stem band power, and chroma for some stems, on one frame clock."""

    hop_s: float
    edges_hz: np.ndarray
    power: dict[str, np.ndarray]  # stem -> (frames, bands), linear
    chroma: dict[str, np.ndarray] = field(default_factory=dict)  # stem -> (frames, 12)

    @property
    def frames(self) -> int:
        return min(p.shape[0] for p in self.power.values()) if self.power else 0


def stem_envelopes(
    paths: dict[str, str | Path],
    hop_s: float = HOP_S,
    chroma_stems: Sequence[str] = CHROMA_STEMS,
) -> StemEnvelopes:
    """Read every stem once and keep only its envelopes.

    One stem's samples at a time: 73 MB for a 14-minute stem, 124 MB traced
    at the peak for all six of My Favorite Things (824 s, 9 s of CPU), which
    read 161 MB while the previous stem was still held during the next read.
    """
    power, chroma = {}, {}
    rate = READ_RATE
    for name, path in sorted(paths.items()):
        samples, rate = read_mono(path)
        power[name] = band_power(samples, rate, hop_s)
        if name in chroma_stems:
            chroma[name] = chroma_power(samples, rate, hop_s)
        del samples  # before the next stem is read, not after
    return StemEnvelopes(hop_s=hop_s, edges_hz=band_edges(rate), power=power, chroma=chroma)


# ── per-bar features ─────────────────────────────────────────────────────────


def bar_frames(bar_lines: Sequence[float], hop_s: float, frames: int) -> np.ndarray:
    """(bars, 2) frame ranges [start, stop) of each bar, never empty."""
    index = np.clip(np.round(np.asarray(bar_lines, dtype=float) / hop_s).astype(int), 0, frames)
    starts = np.minimum(index[:-1], max(frames - 1, 0))
    stops = np.clip(np.maximum(index[1:], starts + 1), 1, max(frames, 1))
    return np.stack([starts, stops], axis=1)


def pool_bars(
    values: np.ndarray,
    ranges: np.ndarray,
    active: np.ndarray | None = None,
    spread: bool = False,
    min_frames: int = 3,
) -> np.ndarray:
    """Mean (and, with `spread`, standard deviation) of per-frame values per bar.

    With `active`, only active frames count; a bar with fewer than
    `min_frames` of them repeats the bar before it (a rest is not a change
    of soloist), and bars before the first such bar take the first one's.
    """
    width = values.shape[1] * (2 if spread else 1)
    rows = np.zeros((len(ranges), width), dtype=float)
    have = np.zeros(len(ranges), dtype=bool)
    for k, (a, b) in enumerate(ranges):
        segment = values[a:b]
        if active is not None:
            segment = segment[active[a:b]]
        if len(segment) < (min_frames if active is not None else 1):
            continue
        mean = segment.mean(axis=0)
        rows[k] = np.concatenate([mean, segment.std(axis=0)]) if spread else mean
        have[k] = True
    if have.any():
        filled = np.maximum.accumulate(np.where(have, np.arange(len(ranges)), -1))
        first = int(np.argmax(have))
        filled[filled < 0] = first
        rows = rows[filled]
    return rows


def stem_levels(env: StemEnvelopes) -> tuple[list[str], np.ndarray]:
    """(stems, (frames, stems)) level in dB against each stem's own loud
    level, floored at LEVEL_FLOOR_DB."""
    stems = sorted(env.power)
    n = env.frames
    columns = []
    for stem in stems:
        level = 10 * np.log10(env.power[stem][:n].sum(axis=1) + 1e-10)
        level = level - np.percentile(level, LEVEL_REFERENCE_PERCENTILE)
        columns.append(np.maximum(level, LEVEL_FLOOR_DB))
    return stems, np.stack(columns, axis=1) if columns else np.zeros((n, 0))


def _dct_basis(size: int, count: int) -> np.ndarray:
    i = np.arange(size)
    return np.stack([np.cos(np.pi * q * (2 * i + 1) / (2 * size)) for q in range(count)], axis=1)


def melodic_cepstra(
    env: StemEnvelopes, stems: Sequence[str] = MELODIC_STEMS
) -> tuple[np.ndarray, np.ndarray]:
    """(frames, N_CEPSTRA) spectral shape of the summed melodic stems, and
    the frames where they sound (within GATE_DB of their loud level).

    The zeroth coefficient -- overall level -- is dropped: loudness is the
    level features' job, and a soloist playing softer is not a new soloist.
    """
    n = env.frames
    present = [s for s in stems if s in env.power]
    if not present:
        return np.zeros((n, N_CEPSTRA)), np.zeros(n, dtype=bool)
    edges = env.edges_hz
    keep = (edges[:-1] >= CEPSTRUM_LOW_HZ) & (edges[1:] <= CEPSTRUM_HIGH_HZ)
    total = sum(env.power[s][:n] for s in present)
    shape = np.log10(total[:, keep] + 1e-10) @ _dct_basis(int(keep.sum()), N_CEPSTRA + 1)
    loud = 10 * np.log10(total.sum(axis=1) + 1e-10)
    active = loud > np.percentile(loud, LEVEL_REFERENCE_PERCENTILE) - GATE_DB
    return shape[:, 1:], active


def standardize(x: np.ndarray) -> np.ndarray:
    """Zero mean, unit spread per column over the track."""
    return (x - x.mean(axis=0)) / (x.std(axis=0) + 1e-6)


def bar_features(env: StemEnvelopes, bar_lines: Sequence[float]) -> np.ndarray:
    """(bars, features): stem levels, and the melodic cepstra's mean and
    spread over the bar's sounding frames, each standardised over the track
    -- 6 + 24 = 30 features for a six-stem separation.

    Bar i runs from bar_lines[i] to bar_lines[i + 1]. Weighting the level
    block 0.5-2x against the cepstra, or dropping the spread, did not beat
    equal weights at any penalty on the survey.
    """
    ranges = bar_frames(bar_lines, env.hop_s, env.frames)
    _stems, levels = stem_levels(env)
    shape, active = melodic_cepstra(env)
    return np.concatenate(
        [
            standardize(pool_bars(levels, ranges)),
            standardize(pool_bars(shape, ranges, active, spread=True)),
        ],
        axis=1,
    )


def bar_chroma(
    env: StemEnvelopes, bar_lines: Sequence[float], stems: Sequence[str] = HEAD_STEMS
) -> np.ndarray:
    """(bars, 12) the stems' summed pitch-class profile per bar, log-compressed,
    centred and unit length, so a dot product is a correlation."""
    ranges = bar_frames(bar_lines, env.hop_s, env.frames)
    present = [s for s in stems if s in env.chroma]
    if not present:
        return np.zeros((len(ranges), 12))
    total = sum(env.chroma[s][: env.frames] for s in present)
    x = pool_bars(total, ranges)
    x = np.log1p(x / (np.median(x) + 1e-12))
    x = x - x.mean(axis=1, keepdims=True)
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)


# ── segmentation ─────────────────────────────────────────────────────────────


def segment(features: np.ndarray, penalty: float, min_bars: int = MIN_BARS) -> list[int]:
    """Cut indices (bar i starts a new segment) by optimal partitioning.

    Minimises the within-segment squared deviation from each segment's mean
    plus `penalty` per segment, exactly, in O(bars^2): a whole track is a
    few hundred bars. Segments are at least `min_bars` long except the
    first and last, which may be cut short by the track itself.
    """
    n = len(features)
    if n == 0:
        return []
    x = np.asarray(features, dtype=float).reshape(n, -1)
    sums = np.concatenate([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    squares = np.concatenate([[0.0], np.cumsum((x**2).sum(axis=1))])
    best = np.full(n + 1, np.inf)
    best[0] = 0.0
    back = np.zeros(n + 1, dtype=int)
    for j in range(1, n + 1):
        i = np.arange(j)
        allowed = (j - i >= min_bars) | (i == 0) | (j == n)
        i = i[allowed & np.isfinite(best[:j])]
        if i.size == 0:
            continue
        length = j - i
        partial = sums[j] - sums[i]
        cost = (squares[j] - squares[i]) - (partial**2).sum(axis=1) / length
        total = best[i] + cost + penalty
        k = int(np.argmin(total))
        best[j] = total[k]
        back[j] = i[k]
    cuts = []
    j = n
    while j > 0:
        j = int(back[j])
        if j > 0:
            cuts.append(j)
    return sorted(cuts)


@dataclass(frozen=True)
class Head:
    """The head-in and head-out as bar ranges [start, end), and how alike
    they are (mean chroma correlation at the stripe's peak)."""

    in_start: int
    in_end: int
    out_start: int
    out_end: int
    similarity: float


def _run(above: np.ndarray, peak: int, gap: int) -> tuple[int, int]:
    """[start, end) of the run of True around `peak`, bridging gaps of up to
    `gap` False entries (a bar the head-out embellishes, a bridge played
    differently, is still the head)."""
    true = np.flatnonzero(above)
    a = b = peak
    while True:
        before = true[(true < a) & (true >= a - gap - 1)]
        if before.size == 0:
            break
        a = int(before.min())
    while True:
        after = true[(true > b) & (true <= b + gap + 1)]
        if after.size == 0:
            break
        b = int(after.max())
    return a, b + 1


def _refine(raw: np.ndarray, a: int, b: int, floor: float, reach: int) -> tuple[int, int]:
    """Move a run's edges from the smoothed diagonal onto the raw one.

    A boxcar thresholded at `floor` erodes a stripe's edges, and
    np.convolve's "same" mode sits an even kernel half a bar off centre
    (HEAD_SMOOTH_BARS = 4 averages bars k-2..k+1): on planted heads the
    smoothed run began one or two bars late (in_start 5 for 4, 9-10 for 8)
    while its end was exact, so the head-out's start, which is the head-in's
    start plus the lag, was late too. Each edge moves by at most `reach`
    bars to where the raw diagonal itself crosses the floor -- outward while
    the bar beyond it is above, else inward while the edge bar is below.
    """
    lo = a
    while lo > max(0, a - reach) and raw[lo - 1] >= floor:
        lo -= 1
    if lo == a:
        while lo < min(b - 1, a + reach) and raw[lo] < floor:
            lo += 1
    hi = b
    while hi < min(len(raw), b + reach) and raw[hi] >= floor:
        hi += 1
    if hi == b:
        while hi > max(lo + 1, b - reach) and raw[hi - 1] < floor:
            hi -= 1
    return lo, hi


def find_head(chroma: np.ndarray) -> Head | None:
    """The longest-lag melodic repetition that opens and closes the track.

    For every lag of at least a third of the track, the diagonal of the
    bars' chroma correlation is smoothed and its strongest runs taken, their
    edges then placed on the raw diagonal (`_refine`); a run is a head if
    its first half starts in the track's first HEAD_EDGE and its second half
    ends in the last. The strongest such run wins, and None unless it
    reaches HEAD_MIN_SIMILARITY. A solo over the same changes correlates
    too, just less: in the development runs the strongest stripes that were
    not the head peaked at 0.4-0.77, the heads at 0.82-0.99.
    """
    n = len(chroma)
    if n < HEAD_MIN_BARS:
        return None
    similarity = chroma @ chroma.T
    kernel = np.ones(HEAD_SMOOTH_BARS) / HEAD_SMOOTH_BARS
    best = None
    for lag in range(max(16, n // 3), n - HEAD_SMOOTH_BARS):
        raw = np.diag(similarity, lag)
        diagonal = np.convolve(raw, kernel, mode="same")
        for i in np.argsort(-diagonal)[:5]:
            peak = float(diagonal[i])
            floor = max(HEAD_FLOOR, peak - HEAD_DROP)
            a, b = _run(diagonal >= floor, int(i), HEAD_GAP_BARS)
            a, b = _refine(raw, a, b, floor, HEAD_SMOOTH_BARS // 2)
            if a > HEAD_EDGE * n or b + lag < (1 - HEAD_EDGE) * n:
                continue
            if best is None or peak > best.similarity:
                best = Head(a, b, a + lag, min(n, b + lag), peak)
            break
    if best is None or best.similarity < HEAD_MIN_SIMILARITY:
        return None
    return best


# ── the proposal ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Boundary:
    time: float
    bar: int  # index into the bar lines
    source: str  # "timbre", "head", or "both" (the two cues agree)


@dataclass(frozen=True)
class Span:
    """A stretch between two proposed boundaries, and who leads it."""

    start: float
    end: float
    # The melodic stem holding the most energy, or "rhythm": a stem of the
    # separation the envelopes were read from, so never carried to another.
    lead: str
    kind: str  # "head" or "section"


@dataclass(frozen=True)
class Proposal:
    boundaries: list[Boundary]
    spans: list[Span]
    head: Head | None


def lead_stem(env: StemEnvelopes, start: float, end: float, quiet_db: float = QUIET_DB) -> str:
    """The melodic stem holding the most energy over [start, end), or
    "rhythm" when the melodic stems together sit `quiet_db` or more under
    their own loud level there (a bass or drum solo, drums trading).

    Energy, not level against each stem's own peak: measured on the 77
    annotated WJazzD solos, the relative rule called 4 horn solos piano and
    named `vocals` for 28, because a stem that is mostly bleed has a low
    peak to be loud against.

    What the label is worth, checked against something it does not read:
    the stem whose chroma follows WJazzD's annotated line over the solo
    (scripts/solo_spans_survey.py section 6). On htdemucs_6s the label is
    that stem for 64 of the 69 located horn solos; it is clearly another
    on 3 -- `guitar` on both My Favorite Things solos and on Crazy Rhythm,
    where the line is in `other` -- and the line is shared between two
    stems on 2 (Dolores, Coltrane's Oleo). On the Roformer, over the 32 of
    them it has a whole-file set for, 31 of 32: it files every horn line
    under `other`, and named `piano` once. So the label names a stem OF
    THE SEPARATION IT WAS READ FROM: htdemucs_6s's `guitar` is the
    Roformer's `other`, and a label carried from one set to the other
    names the wrong stem. It is a suggestion for the Stem menu, not a
    routing rule.
    """
    a = int(max(0, np.floor(start / env.hop_s)))
    b = int(min(env.frames, max(a + 1, np.ceil(end / env.hop_s))))
    present = [s for s in MELODIC_STEMS if s in env.power]
    if not present or b <= a:
        return "rhythm"
    energy = {s: float(env.power[s][a:b].sum()) for s in present}
    total = sum(env.power[s][: env.frames] for s in present).sum(axis=1)
    loud = 10 * np.log10(total + 1e-10)
    here = 10 * np.log10(total[a:b].mean() + 1e-10)
    if here < np.percentile(loud, LEVEL_REFERENCE_PERCENTILE) + quiet_db:
        return "rhythm"
    return max(energy, key=energy.get)


def combine(
    cuts: Sequence[int], head: Head | None, bars: int, head_edges: str = HEAD_EDGES
) -> dict[int, str]:
    """Boundary bar -> source: "timbre", "head", or "both".

    A head edge with a timbre cut within MERGE_BARS of it is one boundary,
    and the timbre cut places it: the stripe ends where the melody stops
    repeating bar for bar, which an embellished head-out ends early -- So
    What's stripe stops 6 s before Miles comes in (Totem Pole's 5 s, Oleo's
    3 s), and letting it overrule the cut at his entry lost those starts.
    A head edge with no cut near it is a boundary of its own; that is where
    the cue earns its place (Donna Lee, Yardbird Suite, Sandu, Orbits, St.
    Thomas, Footprints: a start no timbre cut sees). Head-wins reads starts
    0.66 within two bars against 0.71 for this rule, F2 0.684 against
    0.706 -- a rule changed after the first survey, on these 77 solos.

    `head_edges` is "in" (the head-in's end, the default: HEAD_EDGES),
    "in+out" (the head-out's start as well), or "none".
    """
    chosen = {int(k): "timbre" for k in cuts}
    if head is None or head_edges == "none":
        return chosen
    wanted = (head.in_end, head.out_start) if head_edges == "in+out" else (head.in_end,)
    for edge in wanted:
        if not 0 < edge < bars:
            continue
        near = [
            k for k, source in chosen.items() if source != "head" and abs(k - edge) <= MERGE_BARS
        ]
        if near:
            for k in near:
                chosen[k] = "both"
        else:
            chosen[edge] = "head"
    return chosen


def propose(
    env: StemEnvelopes,
    bar_lines: Sequence[float],
    penalty: float = PENALTY,
    min_bars: int = MIN_BARS,
    head_edges: str = HEAD_EDGES,
) -> Proposal:
    """Solo boundaries and spans for one track.

    `bar_lines` is the repaired grid's bar lines over the whole track
    (`meter.bar_lines`); boundaries land on them. `penalty` is per feature,
    so it means the same whatever the feature count, and it is the one
    knob: 3 finds a few more edges (starts 0.71, ends 0.78 within two bars
    against 0.71/0.73) at twice the false ones inside solos (112 against
    59), 6 fewer than half as many (24) for 0.60/0.65. `head_edges` is
    `combine`'s. The head is looked for only when `env` holds chroma.

    Spans run between consecutive boundaries from the first bar line to the
    last, each labelled with `lead_stem`, and "head" when more than half of
    it lies in the head stripe -- the head-in or the head-out, whether or
    not that edge is a boundary.
    """
    lines = np.asarray(bar_lines, dtype=float)
    if len(lines) < 3 or env.frames == 0:
        return Proposal([], [], None)
    features = bar_features(env, lines)
    cuts = segment(features, penalty * features.shape[1], min_bars)
    head = find_head(bar_chroma(env, lines)) if env.chroma else None
    chosen = combine(cuts, head, len(features), head_edges)
    boundaries = [Boundary(float(lines[k]), k, chosen[k]) for k in sorted(chosen)]
    edges = [float(lines[0])] + [b.time for b in boundaries] + [float(lines[-1])]
    heads = []
    if head is not None:
        last = len(lines) - 1
        heads = [
            (lines[head.in_start], lines[min(head.in_end, last)]),
            (lines[head.out_start], lines[min(head.out_end, last)]),
        ]
    spans = []
    for start, end in zip(edges[:-1], edges[1:], strict=False):
        overlap = sum(max(0.0, min(end, b) - max(start, a)) for a, b in heads)
        kind = "head" if overlap > 0.5 * (end - start) else "section"
        spans.append(Span(start, end, lead_stem(env, start, end), kind))
    return Proposal(boundaries, spans, head)


# ── scoring against a reference ──────────────────────────────────────────────


@dataclass(frozen=True)
class BoundaryScore:
    """Did a proposed boundary land near each reference solo edge?

    `hits[k]` is, for reference edge k, whether some proposed boundary lies
    within each tolerance (one bar, two bars, `seconds`). `inside` counts
    proposals strictly inside a reference solo (more than two bars from both
    its edges): those are wrong for certain. `outside` counts the rest that
    match no edge -- heads, piano and bass solos, trading and endings have
    boundaries too, and a reference that annotates only some soloists cannot
    say whether those are wrong.
    """

    hits: list[tuple[bool, bool, bool]]
    inside: int
    outside: int


def _edges(
    solos: Sequence[tuple[float, float]], bar_seconds: Callable[[float], float]
) -> tuple[np.ndarray, np.ndarray]:
    """Reference edge times, start, end, start, end... in the order of
    `solos`, and the bar length at each."""
    times = np.array([t for solo in solos for t in solo], dtype=float)
    return times, np.array([bar_seconds(float(t)) for t in times], dtype=float)


def score_boundaries(
    proposed: Sequence[float],
    solos: Sequence[tuple[float, float]],
    bar_seconds: Callable[[float], float],
    seconds: float = 4.0,
    track: tuple[float, float] | None = None,
) -> BoundaryScore:
    """Score proposed boundary times against reference solos (start, end).

    `bar_seconds(t)` is the length of the bar at time t, so one bar means
    one bar at the tempo there. Edges are listed start, end, start, end...
    in the order of `solos`. `track` is the first and last bar line: the
    outer edges of the first and last span, so a solo that opens the track
    is found there, though neither is a proposal to count as wrong.

    This is NOT mir_eval's matching, and the difference is deliberate --
    the second exception to "mir_eval is the source of truth", beside
    alignment.py's. Three things about this reference make its
    precision/recall the wrong question:

    - **A handover is one boundary.** The proposal is a run of contiguous
      spans, so each boundary is the end of one span and the start of the
      next, and where one soloist hands to another within a bar or two the
      same boundary is both solos' edge. `hits` credits it to both;
      `mir_eval.util.match_events` matches it once. Under one-to-one
      matching a handover all but cannot be found whole: MIN_BARS keeps the
      timbre cuts eight bars apart and a head edge within MERGE_BARS of a
      cut is merged into it, so the handover's second edge is a miss by
      construction, whatever the proposer heard. The survey counts which
      edges the one-to-one matching loses (docs/solo-spans.md).
    - **The tolerance is in bars at the local tempo**, a different number
      of seconds at every edge. `match_boundaries` gets that through
      match_events' `distance` hook; mir_eval's segmentation measures take
      one window in seconds.
    - **The reference is partial.** WJazzD annotates some soloists, never
      the head, the piano or bass solos, the fours or the ending, so a
      proposal matching no annotated edge is not a false positive, and
      mir_eval's precision would count every one as such. `inside` counts
      only proposals that are wrong for certain.

    The survey prints `match_boundaries`' one-to-one recall beside this, so
    the gap between the two is on the record rather than hidden in it.
    """
    times = np.sort(np.asarray(proposed, dtype=float))
    reach = np.sort(np.concatenate([times, np.asarray(track or (), dtype=float)]))
    edge_times, edge_bars = _edges(solos, bar_seconds)
    hits = []
    for t, bar in zip(edge_times.tolist(), edge_bars.tolist(), strict=True):
        gap = float(np.min(np.abs(reach - t))) if reach.size else np.inf
        hits.append((gap <= bar + 1e-9, gap <= 2 * bar + 1e-9, gap <= seconds + 1e-9))
    inside = outside = 0
    for t in times:
        if np.any(np.abs(t - edge_times) <= 2 * edge_bars):
            continue
        within = any(
            start + 2 * bar_seconds(start) < t < end - 2 * bar_seconds(end) for start, end in solos
        )
        inside += within
        outside += not within
    return BoundaryScore(hits, inside, outside)


def match_boundaries(
    proposed: Sequence[float],
    solos: Sequence[tuple[float, float]],
    bar_seconds: Callable[[float], float],
    seconds: float = 4.0,
    track: tuple[float, float] | None = None,
) -> list[tuple[bool, bool, bool]]:
    """`score_boundaries`' hits under mir_eval's ONE-TO-ONE matching.

    Each reference edge and each proposal (the track's first and last bar
    lines included, as there) is matched at most once, by
    `mir_eval.util.match_events` -- in bars through its `distance` hook for
    the first two tolerances, in seconds for the third. The control on the
    many-to-one count, not a replacement for it: see `score_boundaries` for
    why a handover's one boundary should count for both its edges.
    """
    import mir_eval

    edge_times, edge_bars = _edges(solos, bar_seconds)
    est = np.sort(
        np.concatenate([np.asarray(proposed, dtype=float), np.asarray(track or (), dtype=float)])
    )
    columns = []
    for window, in_bars in ((1.0, True), (2.0, True), (seconds, False)):
        scale = edge_bars if in_bars else np.ones_like(edge_times)

        def distance(ref, est, scale=scale):
            return np.abs(np.subtract.outer(ref, est)) / scale[:, None]

        matched = np.zeros(edge_times.size, dtype=bool)
        if edge_times.size and est.size:
            pairs = mir_eval.util.match_events(edge_times, est, window + 1e-9, distance)
            matched[[i for i, _ in pairs]] = True
        columns.append(matched)
    return [tuple(bool(c[k]) for c in columns) for k in range(edge_times.size)]
