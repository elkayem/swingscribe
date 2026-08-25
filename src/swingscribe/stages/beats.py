"""Stage 2 — BeatTrack: beat_this on the drum stem → BeatGrid (plan §5, M2).

The drum stem is the preferred source — the ride cymbal is the cleanest beat
reference in jazz and separation already isolated it. Falls back to the full
mix when the drum stem is missing or near-silent. Runs with dbn=False
deliberately: the DBN's tempo-continuity prior hurts on expressive jazz, and
skipping it means madmom is never needed (plan §2).

Emits a tempo curve (local BPM per beat), never a single global tempo, and
flags octave-error outliers (half/double tempo) — the known failure mode.

Heavy imports (torch, beat_this, soundfile) stay inside functions: this
module must stay importable without the ml dependency group.
"""

import math
import statistics
from collections.abc import Callable
from pathlib import Path

from swingscribe.config import Config
from swingscribe.device import resolve_device
from swingscribe.model import BeatGrid, Document

# Bump when this stage's behavior changes without a config change — it feeds
# the cache key (see pipeline._cache_name). v2: grid-quality source comparison.
# v3: per-passage coverage and splicing (open-issue #9).
# v4: per-passage rate repair (open-issue #9, second half).
CACHE_VERSION = 4

# |log2(bpm / median)| at or beyond this counts as an octave-error outlier;
# 0.5 flags anything past ~1.41x off the median, halfway to a doubling.
OCTAVE_OUTLIER_THRESHOLD = 0.5

# Below this median BPM a grid is nonsense for jazz, and a track should hold
# at least half that many beats over its duration; otherwise the tracker
# found phantoms (e.g. a near-empty drum stem) and deserves a full-mix retry.
MIN_PLAUSIBLE_BPM = 40.0

# tempo_hint corrects an octave error when tracked/hinted tempo differ by
# roughly a factor of two (either way).
OCTAVE_RATIO_RANGE = (1.7, 2.3)

# A grid with more than this fraction of octave outliers is suspect enough to
# try the other audio source and compare.
MAX_OUTLIER_FRACTION = 0.25


def local_bpm_curve(beats: list[float]) -> list[float]:
    """Local BPM per beat from inter-beat intervals; the last beat repeats
    its predecessor's value so the curve has one entry per beat."""
    if len(beats) < 2:
        return [0.0] * len(beats)
    bpm = [60.0 / (b1 - b0) for b0, b1 in zip(beats, beats[1:], strict=False)]
    return [*bpm, bpm[-1]]


def octave_outliers(local_bpm: list[float]) -> list[int]:
    """Indices whose local BPM is suspiciously far (~an octave) off the median."""
    positive = [b for b in local_bpm if b > 0]
    if len(positive) < 3:
        return []
    median = statistics.median(positive)
    return [
        i
        for i, bpm in enumerate(local_bpm)
        if bpm > 0 and abs(math.log2(bpm / median)) >= OCTAVE_OUTLIER_THRESHOLD
    ]


def infer_beats_per_bar(beats: list[float], downbeats: list[float]) -> int:
    """Median number of beats between consecutive downbeats; 4 when unknown."""
    if len(downbeats) < 2:
        return 4
    counts = []
    for d0, d1 in zip(downbeats, downbeats[1:], strict=False):
        counts.append(sum(1 for b in beats if d0 <= b < d1))
    counts = [c for c in counts if c > 0]
    return round(statistics.median(counts)) if counts else 4


def select_source(
    stems: dict[str, str],
    fallback_path: str,
    use_drum_stem: bool,
    min_mix_ratio: float,
    rms_of: Callable[[str], float],
) -> tuple[str, str]:
    """Pick the audio the tracker listens to. Returns (path, reason).

    The drum-stem gate is relative to the mix: a brushes ballad leaves a
    technically-nonsilent drum stem that is still useless for tracking."""
    if not use_drum_stem:
        return fallback_path, "full mix (use_drum_stem=false)"
    drums = stems.get("drums")
    if drums is None or not Path(drums).is_file():
        return fallback_path, "full mix (no drum stem)"
    mix_rms = rms_of(fallback_path)
    if mix_rms > 0 and rms_of(drums) / mix_rms < min_mix_ratio:
        return fallback_path, "full mix (drum stem near-silent relative to mix)"
    return drums, "drum stem"


def grid_is_plausible(
    beats: list[float], duration: float, min_bpm: float = MIN_PLAUSIBLE_BPM
) -> bool:
    """A sane grid has a jazz-plausible median tempo and covers the track."""
    if len(beats) < 4:
        return False
    positive = [b for b in local_bpm_curve(beats) if b > 0]
    if not positive or statistics.median(positive) < min_bpm:
        return False
    min_expected = duration * (min_bpm / 60.0) * 0.5  # half coverage tolerates intros/fades
    return len(beats) >= min_expected


def grid_quality(beats: list[float], duration: float) -> tuple[bool, float]:
    """Orderable quality score: (plausible, -octave_outlier_fraction).
    Tuple comparison prefers a plausible grid, then the steadier one."""
    if not beats:
        return (False, -1.0)
    fraction = len(octave_outliers(local_bpm_curve(beats))) / len(beats)
    return (grid_is_plausible(beats, duration), -fraction)


def grid_is_suspect(quality: tuple[bool, float]) -> bool:
    plausible, neg_fraction = quality
    return not plausible or -neg_fraction > MAX_OUTLIER_FRACTION


def correct_octave(
    beats: list[float], downbeats: list[float], hint_bpm: float
) -> tuple[list[float], list[float], str | None]:
    """Fix a half/double-tempo grid against a known tempo. Returns
    (beats, downbeats, action) with action None when the grid is left alone."""
    positive = [b for b in local_bpm_curve(beats) if b > 0]
    if not positive:
        return beats, downbeats, None
    median = statistics.median(positive)
    low, high = OCTAVE_RATIO_RANGE

    ratio = hint_bpm / median
    if low <= ratio <= high:
        # tracked an octave low → subdivide each interval at its midpoint
        doubled = []
        for b0, b1 in zip(beats, beats[1:], strict=False):
            doubled += [b0, (b0 + b1) / 2.0]
        doubled.append(beats[-1])
        return doubled, downbeats, f"subdivided {median:.1f} → {median * 2:.1f} bpm"

    inverse = median / hint_bpm
    if low <= inverse <= high:
        # tracked an octave high → keep the alternate beats that retain the
        # most downbeats, and drop downbeats that no longer sit on a beat
        best_kept, best_score = beats[0::2], -1
        for offset in (0, 1):
            kept = beats[offset::2]
            score = sum(1 for d in downbeats if any(abs(d - b) <= 0.02 for b in kept))
            if score > best_score:
                best_kept, best_score = kept, score
        kept_downbeats = [d for d in downbeats if any(abs(d - b) <= 0.02 for b in best_kept)]
        return best_kept, kept_downbeats, f"halved {median:.1f} → {median / 2:.1f} bpm"

    return beats, downbeats, None


# ── Local coverage (open-issue #9) ───────────────────────────────────────
#
# Source selection and the grid-quality comparison above are both whole-track
# judgements. Drum presence is not: Confirmation opens with ~20 seconds of
# piano and bass and no kit at all, so the drum stem — correctly chosen, since
# across the whole track the drums are far above min_drum_mix_ratio — had
# nothing to track there. The resulting grid is the steadiest of the three
# sources by every global measure and still has a 20-second hole at the front,
# which is exactly what `grid_is_suspect` cannot see.
#
# So coverage is measured separately from steadiness, and the repair is a
# splice rather than a swap: in a drumless intro the pulse is carried by the
# whole ensemble, and the full mix tracks it well there while being three
# times less steady over the body of the tune. Neither source is right
# everywhere.

# A stretch with no beat lasting longer than this many expected beat
# intervals is a coverage gap.
MAX_GAP_BEATS = 3.0

# A gap only counts as a tracker failure if the mix is actually playing
# there — silent lead-in and run-out are not.
GAP_AUDIBLE_RATIO = 0.1
GAP_WINDOW_S = 0.5

# An alternate source may fill a gap only if its beat rate there agrees with
# the base grid's within this fraction. This is what rejects the bass, which
# covers Confirmation's intro better than the drums but reports a 2-feel —
# its own rhythm, at half the true pulse rate.
SPLICE_RATE_TOLERANCE = 0.25


def median_interval(beats: list[float]) -> float:
    """Median seconds between consecutive beats; 0.0 when undefined."""
    if len(beats) < 2:
        return 0.0
    return statistics.median(b1 - b0 for b0, b1 in zip(beats, beats[1:], strict=False))


def coverage_gaps(
    beats: list[float],
    duration: float,
    max_gap_beats: float = MAX_GAP_BEATS,
    interval: float | None = None,
) -> list[tuple[float, float]]:
    """Spans where the tracker found no beats for longer than it should have.

    The head (before the first beat) and tail (after the last) count, which is
    where this failure actually appears — a grid that simply starts late looks
    perfect to every steadiness measure.
    """
    if duration <= 0:
        return []
    if len(beats) < 2:
        return [(0.0, duration)]
    interval = interval if interval is not None else median_interval(beats)
    if interval <= 0:
        return []
    limit = max_gap_beats * interval
    edges = [0.0, *beats, duration]
    return [(a, b) for a, b in zip(edges, edges[1:], strict=False) if b - a > limit]


def audible_spans(
    spans: list[tuple[float, float]],
    window_rms: list[float],
    window_s: float,
    ratio: float = GAP_AUDIBLE_RATIO,
) -> list[tuple[float, float]]:
    """Keep only the spans where the mix is playing.

    Relative to the track's own loud reference (95th-percentile window), for
    the same reason the drum gate is relative: an absolute threshold cannot
    tell a quiet recording from a silent passage.
    """
    if not window_rms or window_s <= 0:
        return list(spans)
    ordered = sorted(window_rms)
    reference = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    floor = reference * ratio
    kept = []
    for lo, hi in spans:
        chunk = window_rms[int(lo / window_s) : math.ceil(hi / window_s)]
        if chunk and max(chunk) >= floor:
            kept.append((lo, hi))
    return kept


def splice_beats(
    base: list[float],
    filler: list[float],
    gaps: list[tuple[float, float]],
    interval: float,
    tolerance: float = SPLICE_RATE_TOLERANCE,
) -> tuple[list[float], list[tuple[float, float]]]:
    """Fill each gap in `base` with `filler`'s beats, where the rate agrees.

    Returns (beats, filled_spans). A gap is filled all-or-nothing: partial
    agreement is not evidence, and half a gap of beats at the wrong rate is
    worse than none. Candidates landing within half a beat of an existing beat
    are dropped so a splice never doubles the pulse at a seam.
    """
    if interval <= 0 or not gaps or not filler:
        return list(base), []
    added: list[float] = []
    filled: list[tuple[float, float]] = []
    for lo, hi in gaps:
        inner = [
            b for b in filler if lo <= b <= hi and all(abs(b - p) > 0.5 * interval for p in base)
        ]
        if len(inner) < 2:
            continue
        rate = median_interval(inner)
        if rate <= 0 or abs(rate / interval - 1.0) > tolerance:
            continue
        added.extend(inner)
        filled.append((min(inner), max(inner)))
    if not added:
        return list(base), []
    return sorted(base + added), filled


# ── Local rate repair (open-issue #9, second half) ───────────────────────
#
# Splicing fixes a passage with NO beats. It cannot fix a passage with the
# wrong beats: Confirmation's drum grid resumes at 19.88s at 0.62s spacing,
# exactly half the tune's 0.32s pulse, and those beats are present, so no
# coverage test sees them.
#
# `correct_octave` already does this repair, but globally and only when the
# user supplies a tempo_hint. The grid's own median interval is a better
# reference than a hint in every case where most of the track is tracked
# correctly, and it needs no input — so this is that correction, applied per
# passage and seeded from the grid itself.
#
# The safety property is the run length. A single doubled interval is a
# dropped beat, a fermata or a rubato moment; only a PERSISTENT wrong rate is
# evidence of a passage the tracker took at the wrong subdivision.

LOCAL_RATE_TOLERANCE = 0.15  # how close to an exact multiple an interval must sit
MIN_RATE_RUN = 3  # consecutive intervals at that multiple before we believe it
MAX_RATE_FACTOR = 4


def repair_local_rate(
    beats: list[float],
    tolerance: float = LOCAL_RATE_TOLERANCE,
    min_run: int = MIN_RATE_RUN,
    max_factor: int = MAX_RATE_FACTOR,
) -> tuple[list[float], list[tuple[float, float]]]:
    """Subdivide passages tracked at a whole fraction of the grid's own rate.

    Returns (beats, repaired_spans). The reference is the whole-grid median
    interval, so this only works while most of the track is right — which is
    the case it exists for. Deliberately one-directional: a passage tracked
    too FAST would need beats removed, and choosing which to remove is a
    different and much less safe decision (see `correct_octave`, which only
    does it with a user-supplied tempo).
    """
    if len(beats) < 4:
        return list(beats), []
    intervals = [b1 - b0 for b0, b1 in zip(beats, beats[1:], strict=False)]
    reference = statistics.median(intervals)
    if reference <= 0:
        return list(beats), []

    factors = []
    for gap in intervals:
        k = round(gap / reference)
        exact = 2 <= k <= max_factor and abs(gap / (k * reference) - 1.0) <= tolerance
        factors.append(k if exact else 1)

    out = [beats[0]]
    spans: list[tuple[float, float]] = []
    i = 0
    while i < len(intervals):
        k = factors[i]
        if k == 1:
            out.append(beats[i + 1])
            i += 1
            continue
        j = i
        while j < len(intervals) and factors[j] == k:
            j += 1
        if j - i >= min_run:
            for m in range(i, j):
                step = intervals[m] / k
                out.extend(beats[m] + n * step for n in range(1, k))
                out.append(beats[m + 1])
            spans.append((beats[i], beats[j]))
        else:
            out.extend(beats[m + 1] for m in range(i, j))
        i = j
    return out, spans


def _rms_windows(path: str, window_s: float = GAP_WINDOW_S) -> list[float]:
    import soundfile

    data, rate = soundfile.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    size = max(1, int(window_s * rate))
    return [float((mono[i : i + size] ** 2).mean() ** 0.5) for i in range(0, len(mono), size)]


def _rms(path: str) -> float:
    import soundfile

    data, _rate = soundfile.read(path, dtype="float32", always_2d=True)
    return float((data**2).mean() ** 0.5)


def _track(file2beats, source: str) -> tuple[list[float], list[float]]:
    raw_beats, raw_downbeats = file2beats(source)
    return [float(b) for b in raw_beats], [float(d) for d in raw_downbeats]


def _other_source(source: str, document: Document) -> str | None:
    """The alternative audio to try when the tracked grid is suspect."""
    drums = document.stems.get("drums")
    if source == document.audio.path:
        return drums if drums and Path(drums).is_file() else None
    return document.audio.path


def run(document: Document, config: Config) -> Document:
    import torch
    from beat_this.inference import File2Beats

    if document.audio is None:
        raise ValueError("beats requires ingest to have run first (document.audio is None)")

    source, reason = select_source(
        document.stems,
        document.audio.path,
        config.beats.use_drum_stem,
        config.beats.min_drum_mix_ratio,
        _rms,
    )
    device = resolve_device(config.beats.device, torch.cuda.is_available())
    print(f"beats: source={reason} device={device} dbn={config.beats.dbn}")

    file2beats = File2Beats(
        checkpoint_path=config.beats.checkpoint, device=device, dbn=config.beats.dbn
    )
    beats, downbeats = _track(file2beats, source)

    # Two independent reasons to try the other source: the grid is unsteady
    # (v2), or it has holes where the music is playing (v3, open-issue #9).
    # A grid can be the steadiest of its alternatives and still miss the first
    # twenty seconds, so steadiness alone cannot decide this.
    duration = document.audio.duration
    windows = _rms_windows(document.audio.path)
    quality = grid_quality(beats, duration)
    gaps = audible_spans(coverage_gaps(beats, duration), windows, GAP_WINDOW_S)
    other = _other_source(source, document)
    spliced: list[tuple[float, float]] = []

    if other is not None and (grid_is_suspect(quality) or gaps):
        other_label = "full mix" if other == document.audio.path else "drum stem"
        why = "suspect grid" if grid_is_suspect(quality) else f"{len(gaps)} coverage gap(s)"
        print(f"beats: {why} from {reason} — also trying {other_label}")
        other_beats, other_downbeats = _track(file2beats, other)

        # Swap wholesale ONLY when the whole grid is bad (v2's job). A grid
        # whose only fault is a hole gets a local repair, because that is the
        # entire finding of open-issue #9: the drum stem is the right source
        # for the body of a tune even when it is the wrong one for the intro.
        # Letting the global comparison decide a near-tie here would trade a
        # 20-second hole for a three-times-less-steady grid everywhere.
        if grid_is_suspect(quality) and grid_quality(other_beats, duration) > quality:
            beats, downbeats, filler = other_beats, other_downbeats, beats
            reason = f"{other_label} (better grid than {reason})"
            print(f"beats: kept {other_label} grid ({len(beats)} beats)")
        else:
            filler = other_beats

        interval = median_interval(beats)
        gaps = audible_spans(
            coverage_gaps(beats, duration, interval=interval), windows, GAP_WINDOW_S
        )
        if gaps:
            beats, spliced = splice_beats(beats, filler, gaps, interval)
        if spliced:
            covered = sum(hi - lo for lo, hi in spliced)
            reason = f"{reason} + {other_label} over {len(spliced)} span(s)"
            print(
                f"beats: spliced {len(spliced)} span(s), {covered:.1f}s, from "
                f"{other_label} where {reason.split(' + ')[0]} had no beats"
            )
        elif gaps:
            # Worth saying out loud: the hole is real and nothing could fill
            # it at the right rate, so downstream bar lines will stop there.
            unfilled = ", ".join(f"{lo:.1f}-{hi:.1f}s" for lo, hi in gaps[:4])
            print(f"beats: WARNING {len(gaps)} coverage gap(s) left unfilled: {unfilled}")

    # After splicing, because a spliced-in passage can itself be at the wrong
    # rate, and because the reference interval is only trustworthy once the
    # grid covers the track.
    beats, repaired = repair_local_rate(beats)
    if repaired:
        covered = sum(hi - lo for lo, hi in repaired)
        where = ", ".join(f"{lo:.1f}-{hi:.1f}s" for lo, hi in repaired[:4])
        more = "" if len(repaired) <= 4 else f" (+{len(repaired) - 4} more)"
        print(
            f"beats: subdivided {len(repaired)} passage(s), {covered:.1f}s, "
            f"tracked at a fraction of the grid's own rate: {where}{more}"
        )

    if config.beats.tempo_hint:
        beats, downbeats, action = correct_octave(beats, downbeats, config.beats.tempo_hint)
        if action:
            print(f"beats: tempo hint {config.beats.tempo_hint:g} bpm → {action}")

    bpm = local_bpm_curve(beats)
    outliers = octave_outliers(bpm)
    positive = [b for b in bpm if b > 0]
    if positive:
        median = statistics.median(positive)
        stdev = statistics.pstdev(positive)
        print(
            f"beats: {len(beats)} beats, {len(downbeats)} downbeats, "
            f"median {median:.1f} bpm, stdev {stdev:.1f}"
        )
    if outliers:
        times = ", ".join(f"{beats[i]:.2f}s" for i in outliers[:8])
        more = "" if len(outliers) <= 8 else f" (+{len(outliers) - 8} more)"
        print(f"beats: WARNING {len(outliers)} octave-error outlier(s) at {times}{more}")

    # Downbeats are deliberately NOT spliced. The detected downbeat layer is
    # noise (open-issue #5) and nothing downstream trusts it — meter.py counts
    # beats from a user-set anchor instead — so inventing more of it would add
    # confidence without adding information.
    grid = BeatGrid(
        beats=beats,
        downbeats=downbeats,
        beats_per_bar=infer_beats_per_bar(beats, downbeats),
        local_bpm=bpm,
        source=reason,
        spliced=spliced,
        repaired=repaired,
    )
    return document.model_copy(update={"beat_grid": grid})
