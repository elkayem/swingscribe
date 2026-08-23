"""The ear test (plan §6): render detected beats as clicks over the music.

Beat-tracking bugs are instantly audible and nearly invisible in the numbers,
so this mixes the original (attenuated) with short click bursts at every
detected beat — downbeats get a higher, louder click than other beats.
"""

from pathlib import Path

from swingscribe.model import BeatGrid

DOWNBEAT_FREQ = 1760.0  # A6
BEAT_FREQ = 1175.0  # D6
CLICK_SECONDS = 0.03
MUSIC_GAIN = 0.5
DOWNBEAT_GAIN = 0.9
BEAT_GAIN = 0.55
DOWNBEAT_TOLERANCE = 0.02  # seconds; beat/downbeat lists come from the same tracker


def default_click_path(audio_path: str | Path) -> Path:
    p = Path(audio_path)
    return p.with_name(p.stem + ".click.wav")


def is_downbeat(t: float, downbeats: list[float], tolerance: float = DOWNBEAT_TOLERANCE) -> bool:
    return any(abs(t - d) <= tolerance for d in downbeats)


def render_click_track(audio_path: str | Path, grid: BeatGrid, out_path: str | Path) -> Path:
    import numpy as np
    import soundfile

    data, rate = soundfile.read(str(audio_path), dtype="float32", always_2d=True)
    mix = data * MUSIC_GAIN
    total = len(mix)

    click_len = int(rate * CLICK_SECONDS)
    t = np.arange(click_len) / rate
    envelope = np.exp(-t * 90.0)

    for beat in grid.beats:
        start = int(round(beat * rate))
        if start >= total:
            continue
        down = is_downbeat(beat, grid.downbeats)
        freq = DOWNBEAT_FREQ if down else BEAT_FREQ
        gain = DOWNBEAT_GAIN if down else BEAT_GAIN
        burst = (np.sin(2 * np.pi * freq * t) * envelope * gain).astype(np.float32)
        end = min(total, start + click_len)
        mix[start:end] += burst[: end - start, None]

    np.clip(mix, -1.0, 1.0, out=mix)
    out = Path(out_path)
    soundfile.write(str(out), mix, rate)
    return out
