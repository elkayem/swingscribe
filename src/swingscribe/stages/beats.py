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

# |log2(bpm / median)| at or beyond this counts as an octave-error outlier;
# 0.5 flags anything past ~1.41x off the median, halfway to a doubling.
OCTAVE_OUTLIER_THRESHOLD = 0.5


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
    min_rms: float,
    rms_of: Callable[[str], float],
) -> tuple[str, str]:
    """Pick the audio the tracker listens to. Returns (path, reason)."""
    if not use_drum_stem:
        return fallback_path, "full mix (use_drum_stem=false)"
    drums = stems.get("drums")
    if drums is None or not Path(drums).is_file():
        return fallback_path, "full mix (no drum stem)"
    if rms_of(drums) < min_rms:
        return fallback_path, "full mix (drum stem near-silent)"
    return drums, "drum stem"


def _rms(path: str) -> float:
    import soundfile

    data, _rate = soundfile.read(path, dtype="float32", always_2d=True)
    return float((data**2).mean() ** 0.5)


def run(document: Document, config: Config) -> Document:
    import torch
    from beat_this.inference import File2Beats

    if document.audio is None:
        raise ValueError("beats requires ingest to have run first (document.audio is None)")

    source, reason = select_source(
        document.stems,
        document.audio.path,
        config.beats.use_drum_stem,
        config.beats.min_drum_rms,
        _rms,
    )
    device = resolve_device(config.beats.device, torch.cuda.is_available())
    print(f"beats: source={reason} device={device} dbn={config.beats.dbn}")

    file2beats = File2Beats(
        checkpoint_path=config.beats.checkpoint, device=device, dbn=config.beats.dbn
    )
    raw_beats, raw_downbeats = file2beats(source)
    beats = [float(b) for b in raw_beats]
    downbeats = [float(d) for d in raw_downbeats]

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
