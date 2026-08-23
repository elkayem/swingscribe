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
CACHE_VERSION = 2

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

    # If the grid looks bad, track the other source too and keep the better
    # grid — a second beat_this pass is cheap next to a wrong beat grid.
    duration = document.audio.duration
    quality = grid_quality(beats, duration)
    other = _other_source(source, document)
    if other is not None and grid_is_suspect(quality):
        other_label = "full mix" if other == document.audio.path else "drum stem"
        print(f"beats: suspect grid from {reason} — also trying {other_label}")
        other_beats, other_downbeats = _track(file2beats, other)
        if grid_quality(other_beats, duration) > quality:
            beats, downbeats = other_beats, other_downbeats
            reason = f"{other_label} (better grid than {reason})"
            print(f"beats: kept {other_label} grid ({len(beats)} beats)")

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

    grid = BeatGrid(
        beats=beats,
        downbeats=downbeats,
        beats_per_bar=infer_beats_per_bar(beats, downbeats),
        local_bpm=bpm,
    )
    return document.model_copy(update={"beat_grid": grid})
