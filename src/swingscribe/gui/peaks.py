"""Waveform peak envelopes for the two-tier display.

The browser never decodes audio to draw a waveform. Decoding a five-minute
m4a in JS costs seconds and a few hundred megabytes; reading peaks off the
already-normalized wav costs milliseconds. So the server sends numbers and the
client draws them.

Format is dictated by wavesurfer.js: `peaks` is one array per channel, and its
line renderer draws channel 0 upward and channel 1 downward, taking the
absolute value of each. So a true min/max envelope is sent as
[maxima, minima] — two "channels" that are really the top and bottom of one.

Heavy imports stay inside functions (CLAUDE.md).
"""

import json
from pathlib import Path

OVERVIEW_BUCKETS = 4000  # whole track; comfortably more than any screen is wide
DETAIL_BUCKETS = 2000  # one zoomed window
MAX_BUCKETS = 16000  # guard: a client asking for a million buckets gets a no


def envelope(
    wav_path: str | Path,
    buckets: int,
    start: float = 0.0,
    end: float | None = None,
) -> dict:
    """Min/max envelope of [start, end) as {duration, start, end, peaks}.

    `peaks` is [maxima, minima] per the wavesurfer contract above. Channels are
    summed to mono first: this is a navigation aid, and a stereo pair drawn as
    two half-height traces reads worse at a glance than one full-height one.
    """
    import numpy as np
    import soundfile

    buckets = max(1, min(int(buckets), MAX_BUCKETS))
    with soundfile.SoundFile(str(wav_path)) as f:
        rate = f.samplerate
        total = len(f)
        duration = total / rate
        first = max(0, min(int(start * rate), total))
        last = total if end is None else max(first, min(int(end * rate), total))
        f.seek(first)
        data = f.read(frames=last - first, dtype="float32", always_2d=True)

    mono = data.mean(axis=1) if data.size else np.zeros(0, dtype="float32")
    if mono.size == 0:
        return {
            "duration": duration,
            "start": first / rate,
            "end": last / rate,
            "peaks": [[0.0] * buckets, [0.0] * buckets],
        }

    buckets = min(buckets, mono.size)
    # reduceat over computed edges handles the ragged last bucket without a pad.
    edges = (np.arange(buckets) * (mono.size / buckets)).astype(np.int64)
    edges = np.unique(edges)
    maxima = np.maximum.reduceat(mono, edges)
    minima = np.minimum.reduceat(mono, edges)

    return {
        "duration": duration,
        "start": first / rate,
        "end": last / rate,
        # Clip rather than normalize: a waveform drawn at true amplitude tells
        # you a quiet passage is quiet, which matters when judging isolation.
        "peaks": [
            np.clip(maxima, 0.0, 1.0).round(4).tolist(),
            np.clip(minima, -1.0, 0.0).round(4).tolist(),
        ],
    }


def overview(wav_path: str | Path, cache_dir: str | Path, digest: str) -> dict:
    """Whole-track envelope, memoized on disk.

    The overview is requested every time a track is opened and never changes,
    so it is worth the few kilobytes. Detail windows are not cached — they are
    cheap, and there are unboundedly many of them.
    """
    path = Path(cache_dir) / "gui" / "peaks" / f"{digest}-{OVERVIEW_BUCKETS}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        pass
    data = envelope(wav_path, OVERVIEW_BUCKETS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data
