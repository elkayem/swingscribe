"""How long a separation will take — an estimate the listener can act on.

A separator's cost is close to linear in the audio it is given, so one
number per model (seconds of compute per second of audio) plus a fixed
model-load cost predicts a run well enough to decide "wait" or "pick the
faster model". The seeds are what was measured on the original dev machine
(CPU, no GPU: docs/separation-research.md); every completed separation
then teaches the estimate this machine's own speed, kept in the cache as
`gui/timings.json` — derived data, safely deletable, and the seeds return.
"""

import json
import statistics
from pathlib import Path

# Seconds of compute per second of audio, and a fixed cost per run, measured
# 2026-09-02 on the dev CPU. htdemucs_ft is a bag of four models (4x);
# BS-Roformer-SW is ~9x htdemucs and spends about a minute loading.
SEED_SPEED: dict[str, float] = {
    "htdemucs": 0.28,
    "htdemucs_6s": 0.28,
    "htdemucs_ft": 1.1,
    "bsroformer_sw": 2.5,
}
SEED_LOAD_S: dict[str, float] = {"bsroformer_sw": 60.0}
DEFAULT_SPEED = 1.0
KEEP_SAMPLES = 12  # the most recent runs per model; a laptop's speed drifts

TIMINGS_FILE = "timings.json"


def _path(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / "gui" / TIMINGS_FILE


def load(cache_dir: str | Path) -> dict[str, list[list[float]]]:
    """{model: [[audio_seconds, elapsed_seconds], ...]}, newest last."""
    path = _path(cache_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(cache_dir: str | Path, model: str, audio_seconds: float, elapsed_seconds: float) -> None:
    """Remember one completed separation. Runs that reused stems on disk must
    NOT be recorded — a two-second "separation" would teach a nonsense speed."""
    if audio_seconds <= 0 or elapsed_seconds <= 0:
        return
    data = load(cache_dir)
    samples = data.setdefault(model, [])
    samples.append([round(audio_seconds, 2), round(elapsed_seconds, 2)])
    del samples[:-KEEP_SAMPLES]
    path = _path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def speed(cache_dir: str | Path, model: str) -> tuple[float, float]:
    """(seconds per audio second, fixed seconds) for `model` on this machine:
    learned from recorded runs when there are at least two, else the seed."""
    samples = load(cache_dir).get(model, [])
    load_s = SEED_LOAD_S.get(model, 0.0)
    if len(samples) >= 2:
        # Take the fixed cost off before measuring the per-second rate, so a
        # short span does not read as a slow model.
        rates = [max(0.0, elapsed - load_s) / audio for audio, elapsed in samples if audio > 0]
        return statistics.median(rates), load_s
    return SEED_SPEED.get(model, DEFAULT_SPEED), load_s


def estimate(cache_dir: str | Path, model: str, audio_seconds: float) -> float:
    """Predicted wall-clock seconds to separate `audio_seconds` with `model`."""
    per_second, load_s = speed(cache_dir, model)
    return load_s + per_second * max(0.0, audio_seconds)
