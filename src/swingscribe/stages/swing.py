"""Stage 4 — SwingModel: onsets → SwingSpans (per-window BUR). Plan §5 stage 4.

The heart of the project. Everything upstream wraps somebody else's model;
this is the part that has to know what jazz is.

The measurement is simple. Every onset falls somewhere inside a beat, at a
phase φ = (onset − beat_start) / beat_length. In straight eighths the offbeats
land at φ = 0.5; in swung eighths they land late, and the beat-upbeat ratio is
BUR = φ / (1 − φ). Triplet swing is φ = 0.667 → BUR 2.0.

Four things this stage is careful about:

- **BUR is not a constant.** It widens at slow tempos and narrows toward 1.0
  in fast bebop, and players change it within a tune. So it is estimated per
  window and emitted as a sequence of spans, never as one number for a track.
- **Straight passages are detected, not assumed.** Plenty of Shorter is even
  eighths, and reporting BUR 1.0 with high confidence is a real result that
  quantization needs.
- **A histogram alone is not accurate enough.** BUR = φ/(1−φ) has slope
  1/(1−φ)² — at triplet swing that is 9, so a 0.02-wide bin is 0.18 of BUR,
  well outside the ±5% the milestone asks for. The histogram only *locates*
  the peak; the estimate is the median of the phases clustered around it.
- **A window with too few offbeats gets no span at all.** Inventing a BUR over
  a rest or a passage of whole notes would be worse than admitting the gap.
  M5 can interpolate or fall back, but only if it can see where the evidence
  actually was.

Pure arithmetic, no heavy imports — the whole stage runs in CI.
"""

import bisect
import statistics

from swingscribe.config import Config
from swingscribe.model import Document, SwingSpan

# Bump when this stage's behavior changes without a config change (see
# pipeline._cache_name).
CACHE_VERSION = 1


def beat_phase(onset: float, beats: list[float]) -> tuple[int, float] | None:
    """(index of the enclosing beat, position within it as a 0-1 fraction).

    None when the onset falls outside the grid — before the first beat or
    after the last. Those are common (a pickup, a run-out) and not errors.
    """
    if len(beats) < 2 or onset < beats[0] or onset >= beats[-1]:
        return None
    index = bisect.bisect_right(beats, onset) - 1
    length = beats[index + 1] - beats[index]
    if length <= 0:
        return None
    return index, (onset - beats[index]) / length


def offbeat_phases(
    onsets: list[float], beats: list[float], low: float, high: float
) -> list[tuple[int, float]]:
    """(beat index, phase) for onsets in the offbeat region.

    The region excludes phases near 0, which are downbeat attacks and carry no
    swing information. Note the upper bound still lets sixteenth-note offbeats
    at φ=0.75 through: in a sixteenth-heavy passage the estimate is polluted,
    and onset positions alone cannot tell the two cases apart.
    """
    found = []
    for onset in onsets:
        placed = beat_phase(onset, beats)
        if placed is not None and low < placed[1] < high:
            found.append(placed)
    return found


def dominant_phase(
    phases: list[float], bin_width: float, cluster_width: float
) -> tuple[float, float, float] | None:
    """The dominant offbeat phase, how concentrated it is, and how precise.

    Histogram to locate the peak, then take the median of everything within
    `cluster_width` of it — see the module docstring on why the histogram's
    own resolution is not enough. Two re-centring passes, because the peak
    bin's centre is up to half a bin from where the notes actually are.

    Returns (phase, concentration, standard_error). Concentration is the
    fraction of the window's offbeats sitting in the cluster — a
    well-separated peak is what distinguishes a real swing feel from onsets
    scattered across the beat. The standard error is how well those offbeats
    pin the phase down, and it is not the same question: sixteen offbeats can
    agree that the feel is swung while leaving BUR uncertain by 10%, which is
    exactly what happens at fast tempos. Measured, this estimator sits at the
    sampling limit — the phase bias is +0.0002 and the spread matches
    1.253·σ/√n — so there is no accuracy left to win here, only precision to
    report honestly.
    """
    if not phases or bin_width <= 0:
        return None
    counts: dict[int, int] = {}
    for phase in phases:
        index = int(phase / bin_width)
        counts[index] = counts.get(index, 0) + 1

    # Smooth before picking the peak. A 16-beat window holds ~16 offbeats
    # spread over 0.02-wide bins, so raw counts are 1-3 and ties are constant;
    # picking a raw peak made the estimate depend on which of several equal
    # bins won, which biased BUR low by ~2% at every tempo. Weighting each bin
    # by its neighbours makes the peak depend on where the mass is.
    def mass(index: int) -> int:
        return counts.get(index - 1, 0) + 2 * counts[index] + counts.get(index + 1, 0)

    # Remaining ties break toward the window's own median rather than toward
    # the low bin, which is what made the old bias one-directional.
    middle = statistics.median(phases) / bin_width
    peak = max(counts, key=lambda b: (mass(b), -abs(b - middle)))
    centre = (peak + 0.5) * bin_width
    near: list[float] = []
    for _ in range(2):
        near = [p for p in phases if abs(p - centre) <= cluster_width]
        if not near:
            return None
        centre = statistics.median(near)
    spread = statistics.pstdev(near) if len(near) > 1 else 0.0
    return centre, len(near) / len(phases), spread / (len(near) ** 0.5)


def bur_from_phase(phase: float) -> float:
    """φ → beat-upbeat ratio. 0.5 → 1.0 (straight), 0.667 → 2.0 (triplet)."""
    return phase / (1.0 - phase) if phase < 1.0 else float("inf")


def phase_from_bur(bur: float) -> float:
    """The inverse. Used to generate test material, and by M5's warp."""
    return bur / (1.0 + bur)


def swing_spans(
    onsets: list[float],
    beats: list[float],
    window_beats: int = 16,
    offbeat_range: tuple[float, float] = (0.35, 0.85),
    min_onsets: int = 4,
    swung_phase: float = 0.55,
    min_peak_ratio: float = 1.2,
    min_z: float = 2.0,
    bin_width: float = 0.02,
    cluster_width: float = 0.06,
    target_precision: float = 0.10,
) -> list[SwingSpan]:
    """Per-window BUR over a beat grid.

    Windows tile the grid rather than sliding across it: every onset then
    contributes to exactly one estimate and the spans join into the contiguous
    sequence M5 wants. A sliding window would smear a genuine straight-to-swung
    transition across N beats of overlap.

    `is_swung` is decided by a z-test — is the phase far enough above 0.5,
    relative to its own standard error, to be worth warping — and not by peak
    concentration alone. Measured, concentration is nearly useless at this
    window size: 14 offbeats of *uniform random noise* cluster about as tightly
    (median 0.36) as a real solo does (0.38-0.44), because small samples clump
    whatever they are drawn from, and the two do not separate until ~224
    offbeats, which is 64 bars. It survives only as a weak floor against the
    most obviously scattered windows.
    """
    if len(beats) < 2 or window_beats < 1:
        return []
    by_beat: dict[int, list[float]] = {}
    for index, phase in offbeat_phases(onsets, beats, *offbeat_range):
        by_beat.setdefault(index, []).append(phase)

    spans = []
    last = len(beats) - 1  # beat i spans beats[i]..beats[i+1]
    for start in range(0, last, window_beats):
        end = min(start + window_beats, last)
        window = [p for i in range(start, end) for p in by_beat.get(i, [])]
        if len(window) < min_onsets:
            continue
        found = dominant_phase(window, bin_width, cluster_width)
        if found is None:
            continue
        phase, concentration, standard_error = found
        # Relative uncertainty in BUR, propagated from the phase estimate:
        # d(ln BUR)/dφ = 1/(φ(1−φ)), which is why the same timing error costs
        # far more at fast tempos and at extreme ratios.
        denominator = phase * (1.0 - phase)
        relative_error = standard_error / denominator if denominator > 0 else 1.0
        # How many standard errors the phase sits above straight. This is the
        # question M5 actually needs answered — "is this far enough from
        # straight to be worth warping?" — and unlike concentration it uses
        # the spread of the evidence rather than just its clumpiness.
        low, high = offbeat_range
        floor = 2.0 * cluster_width / max(1e-9, high - low)  # concentration of pure noise
        z = (phase - 0.5) / standard_error if standard_error > 0 else float("inf")
        spans.append(
            SwingSpan(
                start_beat=start,
                end_beat=end,
                bur=bur_from_phase(phase),
                # Three independent ways an estimate can be weak, and all
                # three matter: a tight cluster of three onsets is not yet
                # evidence, twenty scattered ones are not either, and twenty
                # agreeing ones can still leave BUR loose at 260bpm.
                confidence=(
                    concentration
                    * min(1.0, len(window) / (2.0 * min_onsets))
                    * (1.0 / (1.0 + relative_error / target_precision))
                ),
                is_swung=(
                    phase > swung_phase and z > min_z and concentration > floor * min_peak_ratio
                ),
            )
        )
    return spans


def run(document: Document, config: Config) -> Document:
    if document.beat_grid is None:
        raise ValueError("swing requires beats to have run first (document.beat_grid is None)")
    sc = config.swing
    stem = sc.stem or config.transcribe.stem
    notes = document.notes.get(stem)
    if notes is None:
        available = ", ".join(sorted(document.notes)) or "none (run transcribe first)"
        raise ValueError(f"swing needs notes for the {stem!r} stem; available: {available}")

    spans = swing_spans(
        [n.onset for n in notes],
        document.beat_grid.beats,
        window_beats=sc.window_beats,
        offbeat_range=(sc.offbeat_low, sc.offbeat_high),
        min_onsets=sc.min_onsets,
        swung_phase=sc.swung_phase_threshold,
        min_peak_ratio=sc.min_peak_ratio,
        min_z=sc.min_z,
        bin_width=sc.bin_width,
        cluster_width=sc.cluster_width,
        target_precision=sc.target_precision,
    )

    beats_total = len(document.beat_grid.beats) - 1
    if spans:
        covered = sum(s.end_beat - s.start_beat for s in spans)
        swung = [s for s in spans if s.is_swung]
        print(f"swing: {len(spans)} span(s) over {covered}/{beats_total} beats, {len(swung)} swung")
        if swung:
            burs = [s.bur for s in swung]
            print(
                f"swing: BUR median {statistics.median(burs):.2f}, "
                f"range {min(burs):.2f}-{max(burs):.2f}, mean confidence "
                f"{statistics.fmean(s.confidence for s in swung):.2f}"
            )
        else:
            print("swing: no window met the swung threshold - reads as straight eighths")
    else:
        print("swing: no window had enough offbeats to estimate BUR")

    return document.model_copy(update={"swing": spans})
