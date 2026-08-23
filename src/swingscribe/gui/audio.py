"""Span slices of separated stems, optionally time-stretched.

Screen 3 mixes several stems at once, and they must line up *exactly*: stems
from one separation are highly correlated signals, so even ten milliseconds of
drift between them comb-filters into a metallic swish that sounds like bad
separation when the separation is fine. That rules out playing seven <audio>
elements and hoping they stay together.

So the client decodes each span into an AudioBuffer and starts them from a
single scheduled instant — sample-accurate forever, and gapless when looping.
This module cuts those spans.

Speed is handled here too, for the same reason. AudioBufferSourceNode's
playbackRate resamples, which shifts pitch; the browser's pitch-preserving
path only exists on media elements, which are exactly what we just ruled out.
Stretching server-side with torchaudio's phase vocoder keeps every source at
rate 1.0 and therefore still sample-locked — and needs no new dependency
(docs/gui-design.md).

Heavy imports stay inside functions (CLAUDE.md).
"""

import io
import math
from pathlib import Path

# Beyond this, a span is downmixed to mono before being sent. A 2-minute solo
# in stereo is ~21MB per stem, which is fine; a whole 5-minute track across
# several stems is not. Mono costs nothing for the judgement being made here.
STEREO_LIMIT_SECONDS = 180.0

# Phase-vocoder settings. 2048/512 is the usual speech-and-music compromise:
# long enough to resolve a bass note, short enough not to smear a bebop
# eighth into the next one.
STFT_SIZE = 2048
STFT_HOP = 512

MIN_RATE = 0.25
MAX_RATE = 2.0


def slice_wav(
    stem_path: str | Path,
    start: float = 0.0,
    end: float | None = None,
    rate: float = 1.0,
) -> bytes:
    """A 16-bit PCM wav of [start, end) from `stem_path`, at playback `rate`.

    `rate` < 1 slows the audio down without moving its pitch. Returned as
    bytes rather than written to disk: these are transient, the client caches
    the decoded buffers, and nothing downstream wants them.
    """
    import numpy as np
    import soundfile

    rate = max(MIN_RATE, min(float(rate), MAX_RATE))

    with soundfile.SoundFile(str(stem_path)) as f:
        samplerate = f.samplerate
        total = len(f)
        first = max(0, min(int(start * samplerate), total))
        last = total if end is None else max(first, min(int(end * samplerate), total))
        f.seek(first)
        data = f.read(frames=last - first, dtype="float32", always_2d=True)

    span_seconds = (last - first) / samplerate
    if span_seconds > STEREO_LIMIT_SECONDS and data.shape[1] > 1:
        data = data.mean(axis=1, keepdims=True)

    if rate != 1.0 and data.size:
        data = _time_stretch(data, rate)

    buffer = io.BytesIO()
    soundfile.write(buffer, np.clip(data, -1.0, 1.0), samplerate, subtype="PCM_16", format="WAV")
    return buffer.getvalue()


def _time_stretch(data, rate: float):
    """Phase-vocoder time stretch. `rate` 0.5 makes the audio twice as long.

    Operates per channel on one STFT so the channels stay phase-consistent
    with each other — stretching them independently would widen and smear the
    stereo image, which is the opposite of what an isolation check needs.
    """
    import numpy as np
    import torch
    import torchaudio

    waveform = torch.from_numpy(np.ascontiguousarray(data.T))  # (channels, samples)
    window = torch.hann_window(STFT_SIZE)
    spec = torch.stft(waveform, STFT_SIZE, hop_length=STFT_HOP, window=window, return_complex=True)
    phase_advance = torch.linspace(0, math.pi * STFT_HOP, spec.shape[-2])[..., None]
    stretched = torchaudio.functional.phase_vocoder(spec, rate, phase_advance)
    expected = int(math.ceil(waveform.shape[-1] / rate))
    out = torch.istft(stretched, STFT_SIZE, hop_length=STFT_HOP, window=window, length=expected)
    return out.numpy().T  # back to (samples, channels)
