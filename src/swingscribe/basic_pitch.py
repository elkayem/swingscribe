"""Basic Pitch -- a note-level second opinion that fills the holes in a horn's line.

Basic Pitch (Spotify; Bittner et al., "A Lightweight Instrument-Agnostic
Model for Polyphonic Note Transcription and Multipitch Estimation", ICASSP
2022) is a small note/onset network trained on many instruments. The
roadmap's A2 bake-off (docs/frontend-bakeoff.md) ran it on the harness's
own stems: useless as a horn's LINE (its weak onsets on a horn stem are the
comping), but CREPE's line plus Basic Pitch's notes where the line has a
HOLE -- `corroborate.fill_gaps` -- read WJazzD note F1 0.8580 -> 0.8650 over
73 solos (49 up, 1 down) and the Omnibook's sub-eighth recall 0.660 ->
0.703. CREPE's segmentation drops the short note; this model hears 60% of
WJazzD's notes under 60 ms where CREPE hears 49%.

This is NOT a stage and has no opinion about Documents, for the same reason
`piano.py` is not one. `stages/transcribe.py` consults it for a horn.

## A port, not the package

The `basic-pitch` package imports librosa and resampy at module import (and
through them numba), which Smart App Control refuses on the dev machine and
CLAUDE.md forbids; on Linux it also pulls full TensorFlow. The bake-off ran
it in WSL for that reason. Everything the product needs is the ONNX graph
and about a hundred lines of numpy around it, ported here from basic-pitch
0.4.0 (https://github.com/spotify/basic-pitch), Copyright 2022 Spotify AB,
licensed under the Apache License, Version 2.0:

- `inference.run_inference` / `window_audio_file` / `unwrap_output`: the
  2-second windows with a 30-frame overlap, half of it as leading zeros, and
  the overlap trimmed back off -> `posteriorgrams`;
- `note_creation.get_infered_onsets` -> `inferred_onsets`;
- `note_creation.output_to_notes_polyphonic` -> `output_to_notes`, WITHOUT
  the melodia trick (notes grown from leftover frame energy with no onset:
  worse in every hybrid the bake-off tried, because on a stem those are the
  bleed) and without the frequency limits (unused);
- `note_creation.model_frames_to_time` -> `frame_times`, verbatim, magic
  0.0018 s included: the bake-off's 4 ms onset shift was measured against
  exactly this arithmetic.

`scipy.signal.argrelmax` is replaced by its numpy equivalent
(`local_maxima`), and the decoder keeps the upstream's dtypes -- float64
energy, float32 amplitudes -- so a threshold compares the same number here as
there, whatever numpy's promotion rules. The model graph
`basic-pitch-nmp.onnx` is the package's `saved_models/icassp_2022/nmp.onnx`
byte for byte (`MODEL_SHA256`); the Apache-2.0 text ships beside it
(`basic-pitch-LICENSE.txt`) and its NOTICE is in packaging/NOTICES.md.

## One deliberate difference: the resampler

librosa resamples to 22,050 Hz with soxr; this uses torchaudio, like the
rest of the project (soxr is librosa's dependency, not ours). The fidelity
check against the WSL run is in docs/frontend-bakeoff.md, "Shipped".

Heavy imports (numpy, torch, torchaudio, onnxruntime) stay inside functions:
this module must import without the ml group, which CI never installs.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).resolve().with_name("basic-pitch-nmp.onnx")
# SHA-256 of basic-pitch 0.4.0's saved_models/icassp_2022/nmp.onnx, the graph
# the bake-off measured. A test holds the vendored file to it.
MODEL_SHA256 = "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec"

# basic_pitch.constants
SAMPLE_RATE = 22050
FFT_HOP = 256
ANNOTATIONS_FPS = SAMPLE_RATE // FFT_HOP  # 86 (integer, as upstream)
ANNOT_N_FRAMES = ANNOTATIONS_FPS * 2  # 172 frames in a 2 s training window
AUDIO_N_SAMPLES = SAMPLE_RATE * 2 - FFT_HOP  # 43,844 samples per window
N_OVERLAPPING_FRAMES = 30
OVERLAP_LEN = N_OVERLAPPING_FRAMES * FFT_HOP  # 7,680
HOP_SIZE = AUDIO_N_SAMPLES - OVERLAP_LEN  # 36,164
MIDI_OFFSET = 21  # the model's 88 bins are the piano's keys, A0 up
MAX_FREQ_IDX = 87
ENERGY_TOL = 11  # frames under the frame threshold that end a note

# The graph's tensor names (basic_pitch.inference.Model.predict).
INPUT_NAME = "serving_default_input_2:0"
NOTE_OUTPUT = "StatefulPartitionedCall:1"
ONSET_OUTPUT = "StatefulPartitionedCall:2"

# Audio either side of the region, so a note at its edge has context. The
# bake-off loaded exactly this much (scripts/bakeoff_basic_pitch_wsl.py).
MARGIN_S = 1.0


def min_note_frames(min_note_ms: float) -> int:
    """A minimum length in ms as the decoder's frame count, the way the
    bake-off converted it (at the FLOAT frame rate 86.13, not the integer 86).
    The decoder keeps a note only if it is LONGER than this many frames, so
    23 ms (2 frames) means at least three, 35 ms."""
    return int(round(min_note_ms / 1000.0 * (SAMPLE_RATE / FFT_HOP)))


def region_audio(mono, rate: int, region: tuple[float, float | None] | None):
    """The signal Basic Pitch hears for a region: the region plus `MARGIN_S`
    either side, sliced the way librosa.load(offset=, duration=) slices it
    (first sample int(start * rate), length int(duration * rate)). Returns
    (segment, start): `start` is the whole-track time of its first sample."""
    if region is None:
        return mono, 0.0
    low, high = region
    start = max(0.0, float(low) - MARGIN_S)
    first = int(start * rate)
    if high is None:
        return mono[first:], start
    count = int((float(high) + MARGIN_S - start) * rate)
    return mono[first : first + count], start


def resample(mono, rate: int):
    """Mono float32 at the model's 22,050 Hz, through torchaudio."""
    import numpy as np

    signal = np.ascontiguousarray(mono, dtype=np.float32)
    if rate == SAMPLE_RATE:
        return signal
    import torch
    import torchaudio

    return (
        torchaudio.functional.resample(torch.from_numpy(signal), rate, SAMPLE_RATE)
        .numpy()
        .astype(np.float32)
    )


@functools.lru_cache(maxsize=1)
def session():
    """One onnxruntime session per process; the graph is 230 KB and CPU-only
    (78x real time in the bake-off), so there is no device to choose."""
    import onnxruntime

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Basic Pitch model missing from the package: {MODEL_PATH}")
    options = onnxruntime.SessionOptions()
    options.log_severity_level = 3  # the graph's unused-initializer warnings are noise
    return onnxruntime.InferenceSession(
        str(MODEL_PATH), options, providers=["CPUExecutionProvider"]
    )


def unwrap(output, original_length: int):
    """basic_pitch.inference.unwrap_output: drop half the overlap from each
    end of every window, join them, and trim to the audio's length."""
    import numpy as np

    n_olap = int(0.5 * N_OVERLAPPING_FRAMES)
    if n_olap > 0:
        output = output[:, n_olap:-n_olap, :]
    n_frames = int(np.floor(original_length * (ANNOTATIONS_FPS / SAMPLE_RATE)))
    return output.reshape(output.shape[0] * output.shape[1], output.shape[2])[:n_frames, :]


def posteriorgrams(audio, model=None, batch: int = 16):
    """The frame ("note") and onset posteriorgrams for 22,050 Hz mono audio,
    each (n_frames, 88). basic_pitch.inference.run_inference on an array: the
    same leading half-overlap of zeros, the same 2 s windows every
    `HOP_SIZE` samples (the last zero-padded), windows sent in batches."""
    import numpy as np

    model = model or session()
    original_length = len(audio)
    padded = np.concatenate([np.zeros(OVERLAP_LEN // 2, dtype=np.float32), audio])
    starts = list(range(0, padded.shape[0], HOP_SIZE))
    notes, onsets = [], []
    for first in range(0, len(starts), batch):
        windows = []
        for i in starts[first : first + batch]:
            window = padded[i : i + AUDIO_N_SAMPLES]
            if len(window) < AUDIO_N_SAMPLES:
                window = np.pad(window, (0, AUDIO_N_SAMPLES - len(window)))
            windows.append(window)
        x = np.stack(windows)[:, :, None].astype(np.float32)
        note, onset = model.run([NOTE_OUTPUT, ONSET_OUTPUT], {INPUT_NAME: x})
        notes.append(note)
        onsets.append(onset)
    return (
        unwrap(np.concatenate(notes), original_length),
        unwrap(np.concatenate(onsets), original_length),
    )


def frame_times(n_frames: int):
    """basic_pitch.note_creation.model_frames_to_time, verbatim: each frame's
    time, less upstream's per-window correction for the windows' overlap
    arithmetic (the 0.0018 is upstream's own "magic number")."""
    import numpy as np

    frames = np.arange(n_frames)
    original_times = frames * FFT_HOP / float(SAMPLE_RATE)
    window_numbers = np.floor(frames / ANNOT_N_FRAMES)
    window_offset = (FFT_HOP / SAMPLE_RATE) * (
        ANNOT_N_FRAMES - (AUDIO_N_SAMPLES / FFT_HOP)
    ) + 0.0018
    return original_times - (window_offset * window_numbers)


def inferred_onsets(onsets, frames, n_diff: int = 2):
    """basic_pitch.note_creation.get_infered_onsets: onsets also where the
    frame activation jumps, rescaled to the onset map's maximum. Upstream
    divides by the jump's maximum unguarded; a map with no jump at all (only
    silence) keeps its onsets here instead of turning into NaN."""
    import numpy as np

    diffs = []
    for n in range(1, n_diff + 1):
        frames_appended = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(frames_appended[n:, :] - frames_appended[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    peak = np.max(frame_diff)
    if peak > 0:
        frame_diff = np.max(onsets) * frame_diff / peak
    return np.max([onsets, frame_diff], axis=0)


def local_maxima(values):
    """scipy.signal.argrelmax(values, axis=0) as a boolean mask: strictly
    greater than both neighbours in time. Its default `clip` mode compares
    the first and last frames with themselves, so neither is ever a peak."""
    import numpy as np

    mask = np.zeros(values.shape, dtype=bool)
    if values.shape[0] >= 3:
        middle = values[1:-1]
        mask[1:-1] = (middle > values[:-2]) & (middle > values[2:])
    return mask


def output_to_notes(
    frames,
    onsets,
    onset_threshold: float,
    frame_threshold: float,
    min_note_len: int,
    infer_onsets: bool = True,
    energy_tol: int = ENERGY_TOL,
) -> list[tuple[int, int, int, float]]:
    """basic_pitch.note_creation.output_to_notes_polyphonic, melodia trick
    off: [(start frame, end frame, MIDI pitch, amplitude)], amplitude being
    the mean frame activation over the note (0-1).

    Onsets are peaks of the onset map (in time) at or over
    `onset_threshold`, taken LATEST FIRST, as upstream does: each note claims
    its frames and its two neighbouring pitch bins, so the order decides which
    of two overlapping notes survives. A note runs until the frame
    activation has stayed under `frame_threshold` for `energy_tol` frames,
    and is kept only if it is longer than `min_note_len` frames."""
    import numpy as np

    n_frames = frames.shape[0]
    if n_frames == 0:
        return []
    if infer_onsets:
        onsets = inferred_onsets(onsets, frames)

    peak_thresh_mat = np.zeros(onsets.shape)
    peaks = local_maxima(onsets)
    peak_thresh_mat[peaks] = onsets[peaks]

    onset_idx = np.where(peak_thresh_mat >= onset_threshold)
    onset_time_idx = onset_idx[0][::-1]  # backwards in time
    onset_freq_idx = onset_idx[1][::-1]

    remaining_energy = np.zeros(frames.shape)
    remaining_energy[:, :] = frames[:, :]

    note_events: list[tuple[int, int, int, float]] = []
    for note_start_idx, freq_idx in zip(onset_time_idx, onset_freq_idx, strict=True):
        if note_start_idx >= n_frames - 1:
            continue
        i = note_start_idx + 1
        k = 0  # frames since the energy dropped under the threshold
        while i < n_frames - 1 and k < energy_tol:
            if remaining_energy[i, freq_idx] < frame_threshold:
                k += 1
            else:
                k = 0
            i += 1
        i -= k  # back to the last frame over the threshold
        if i - note_start_idx <= min_note_len:
            continue
        remaining_energy[note_start_idx:i, freq_idx] = 0
        if freq_idx < MAX_FREQ_IDX:
            remaining_energy[note_start_idx:i, freq_idx + 1] = 0
        if freq_idx > 0:
            remaining_energy[note_start_idx:i, freq_idx - 1] = 0
        amplitude = np.mean(frames[note_start_idx:i, freq_idx])
        note_events.append(
            (int(note_start_idx), int(i), int(freq_idx) + MIDI_OFFSET, float(amplitude))
        )
    return note_events


def transcribe(
    mono,
    rate: int,
    region: tuple[float, float | None] | None,
    *,
    onset_threshold: float,
    frame_threshold: float,
    min_note_ms: float,
    model=None,
) -> list[dict[str, Any]]:
    """Every note Basic Pitch hears with an onset inside `region`, as the
    note dicts `corroborate.fill_gaps` reads: whole-track `onset` and
    `duration` in seconds, `pitch`, and `confidence` = the amplitude. No
    `velocity` key, deliberately: fill_gaps would read one as MIDI velocity
    out of 127, and the amplitude is already 0-1.

    `mono` is the WHOLE track at `rate`; the region plus a second either
    side is what the model hears (`region_audio`). Onsets are reported
    unshifted -- fill_gaps applies the measured onset shift."""
    segment, start = region_audio(mono, rate, region)
    note, onset = posteriorgrams(resample(segment, rate), model)
    events = output_to_notes(
        note.astype("float32"),
        onset.astype("float32"),
        onset_threshold,
        frame_threshold,
        min_note_frames(min_note_ms),
    )
    times = frame_times(note.shape[0])
    low, high = (None, None) if region is None else region
    out = []
    for first, last, pitch, amplitude in events:
        begin = float(times[first]) + start
        if low is not None and begin < low:
            continue
        if high is not None and begin > high:
            continue
        out.append(
            {
                "onset": begin,
                "duration": max(float(times[last]) + start - begin, 0.0),
                "pitch": pitch,
                "confidence": amplitude,
            }
        )
    return sorted(out, key=lambda n: (n["onset"], -n["pitch"]))
