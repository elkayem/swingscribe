"""Stage 3 — Transcribe, monophonic path (plan §5, M3).

CREPE f0 tracking (torchcrepe) + spectral-flux onset detection on the
"other" stem (where the horn lives after separation), segmented into
NoteEvents. CREPE rather than pYIN: librosa's pYIN hard-requires numba,
whose compiled DLLs Windows Application Control blocks on the dev machine;
torchcrepe runs on plain torch (with a shim for its unused resampy import).
Onset detection is hand-rolled numpy spectral flux for the same reason.

The three known hazards are handled explicitly:

- **Silence between phrases**: frames are gated on CREPE's periodicity
  (config voicing_threshold) AND on frame energy relative to the stem's
  loud reference (silence_floor_db). Both are needed: pitch trackers emit
  confident garbage over rests, and the bleed in a stem is *pitched*
  (piano/bass), so quiet-but-periodic frames must be gated by energy.
- **Octave errors**: constrained [fmin, fmax] search range first; then
  notes sitting ~12 semitones off their neighborhood median get folded
  back (fold_octave_outliers) — same shape as the tempo-octave problem.
- **Vibrato / inflection**: a median filter over the f0 track smooths
  vibrato wobble, and a note only splits on a pitch change when the new
  rounded pitch PERSISTS (pitch_persist_ms) — scoops, falls, and bends
  pass through as transitions inside one note instead of becoming notes.

Heavy imports (torch, torchcrepe, numpy, soundfile) stay inside functions:
this module must stay importable without the ml dependency group.

Only the horn-led ensemble is implemented; trio/solo-piano arrive at M7b.
"""

import math
import statistics
import sys
import types

from swingscribe.config import Config
from swingscribe.device import resolve_device
from swingscribe.model import Document, NoteEvent

CREPE_SAMPLE_RATE = 16000
CREPE_HOP = 160  # 10ms frames

# Bump when this stage's behavior changes without a config change (see
# pipeline._cache_name).
CACHE_VERSION = 1


def hz_to_midi(hz: float) -> float:
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def median_smooth(pitches: list[float | None], kernel: int) -> list[float | None]:
    """NaN/None-aware median filter over the f0 track (vibrato smoothing)."""
    if kernel <= 1:
        return list(pitches)
    half = kernel // 2
    out: list[float | None] = []
    for i, value in enumerate(pitches):
        if value is None:
            out.append(None)
            continue
        window = [w for w in pitches[max(0, i - half) : i + half + 1] if w is not None]
        out.append(statistics.median(window))
    return out


def fill_short_gaps(pitches: list[float | None], max_gap: int) -> list[float | None]:
    """Bridge brief unvoiced dropouts inside a phrase by holding the last
    pitch, so a breathy legato line doesn't shatter into fragments."""
    out = list(pitches)
    i, n = 0, len(out)
    while i < n:
        if out[i] is None:
            j = i
            while j < n and out[j] is None:
                j += 1
            if i > 0 and j < n and (j - i) <= max_gap:
                for k in range(i, j):
                    out[k] = out[i - 1]
            i = j
        else:
            i += 1
    return out


def _voiced_runs(pitches: list[float | None]) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, p in enumerate(pitches):
        if p is not None and start is None:
            start = i
        elif p is None and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(pitches)))
    return runs


def _pitch_change_points(rounded: list[int], persist: int) -> list[int]:
    """Indices (relative) where a NEW rounded pitch takes over and persists.
    Shorter excursions are vibrato/inflection and never split a note."""
    points = []
    if not rounded:
        return points
    current = rounded[0]
    i = 1
    while i < len(rounded):
        if rounded[i] == current:
            i += 1
            continue
        j = i
        while j < len(rounded) and rounded[j] == rounded[i]:
            j += 1
        if j - i >= persist:
            points.append(i)
            current = rounded[i]
        i = j
    return points


def segment_notes(
    pitches: list[float | None],
    confidences: list[float],
    onset_frames: set[int],
    hop_s: float,
    min_note_s: float,
    persist_frames: int,
    max_gap_frames: int,
    source: str,
) -> list[NoteEvent]:
    """Gated, smoothed frame pitches → NoteEvents.

    Splits happen at: unvoiced gaps longer than max_gap_frames, detected
    onsets (repeated same-pitch notes), and persistent pitch changes.
    """
    bridged = fill_short_gaps(pitches, max_gap_frames)
    notes = []
    for run_start, run_end in _voiced_runs(bridged):
        run = [bridged[i] for i in range(run_start, run_end)]
        rounded = [round(p) for p in run]
        pitch_cuts = set(_pitch_change_points(rounded, persist_frames))
        onset_cuts = {o - run_start for o in onset_frames if run_start < o < run_end}
        # A run-initial transition shorter than the persistence window is a
        # scoop into the first stable note — merge it instead of emitting a
        # grace-note artifact (unless an onset genuinely separates them).
        if pitch_cuts:
            first_cut = min(pitch_cuts)
            if first_cut < persist_frames and not any(o <= first_cut for o in onset_cuts):
                pitch_cuts.discard(first_cut)
        cuts = pitch_cuts | onset_cuts
        bounds = [0, *sorted(cuts), run_end - run_start]
        for b0, b1 in zip(bounds, bounds[1:], strict=False):
            if b1 <= b0:
                continue
            duration = (b1 - b0) * hop_s
            if duration < min_note_s:
                continue
            segment = run[b0:b1]
            conf = [confidences[run_start + k] for k in range(b0, b1)]
            notes.append(
                NoteEvent(
                    onset=(run_start + b0) * hop_s,
                    duration=duration,
                    pitch=round(statistics.median(segment)),
                    confidence=statistics.fmean(conf) if conf else 0.0,
                    source=source,
                )
            )
    return notes


def crop_region(mono, rate: int, region: tuple[float, float | None] | None):
    """Slice a mono signal to [start, end] seconds; a None end means "to the
    end". Returns (signal, offset) where offset is the start time to add back
    so note onsets stay in whole-track time."""
    if region is None:
        return mono, 0.0
    duration = len(mono) / rate
    start, end = region
    end = duration if end is None else end
    if end <= start:
        raise ValueError(f"region end must be after start, got {region}")
    start = max(0.0, min(start, duration))
    end = max(start, min(end, duration))
    return mono[int(start * rate) : int(end * rate)], start


def offset_notes(notes: list[NoteEvent], offset: float) -> list[NoteEvent]:
    if not offset:
        return notes
    return [n.model_copy(update={"onset": n.onset + offset}) for n in notes]


def pick_peaks(strength: list[float], min_separation: int, window: int, delta: float) -> list[int]:
    """Local maxima of an onset-strength curve that stand `delta` above the
    local mean, at least `min_separation` frames apart."""
    peaks: list[int] = []
    last = -min_separation
    for i in range(1, len(strength) - 1):
        if not (strength[i] >= strength[i - 1] and strength[i] > strength[i + 1]):
            continue
        local = strength[max(0, i - window) : i + window + 1]
        if strength[i] >= (sum(local) / len(local)) + delta and i - last >= min_separation:
            peaks.append(i)
            last = i
    return peaks


def fold_octave_outliers(notes: list[NoteEvent], context: int = 2) -> list[NoteEvent]:
    """Fold notes sitting ~an octave off their neighborhood back into it."""
    out = []
    for i, note in enumerate(notes):
        neighbors = [n.pitch for n in notes[max(0, i - context) : i]] + [
            n.pitch for n in notes[i + 1 : i + 1 + context]
        ]
        if neighbors:
            offset = note.pitch - statistics.median(neighbors)
            if 11 <= abs(offset) <= 13:
                shift = -12 if offset > 0 else 12
                note = note.model_copy(update={"pitch": note.pitch + shift})
        out.append(note)
    return out


def _import_torchcrepe():
    """Import torchcrepe with a stub for its unused resampy dependency —
    resampy needs numba, which Application Control blocks on some machines.
    We resample with torchaudio, so resampy is never actually called."""
    try:
        import resampy  # noqa: F401
    except ImportError:
        stub = types.ModuleType("resampy")

        def _blocked(*_args, **_kwargs):
            raise RuntimeError("resampy is unavailable here; resample with torchaudio instead")

        stub.resample = _blocked
        sys.modules["resampy"] = stub
    import torchcrepe

    return torchcrepe


def _frame_energy_gate(mono16, floor_db: float) -> list[bool]:
    """Per-frame keep/drop by RMS relative to the stem's loud reference
    (95th-percentile frame RMS), so quiet pitched bleed between phrases is
    gated even when its periodicity is high."""
    import numpy as np

    n_frames = 1 + (len(mono16) - 1) // CREPE_HOP
    padded = np.pad(mono16, (0, n_frames * CREPE_HOP + CREPE_HOP - len(mono16)))
    frames = padded[: n_frames * CREPE_HOP].reshape(n_frames, CREPE_HOP)
    rms = np.sqrt((frames**2).mean(axis=1))
    reference = np.percentile(rms, 95)
    floor = reference * (10.0 ** (floor_db / 20.0))
    return [bool(v) for v in rms >= floor]


def _spectral_flux_onsets(mono, rate: int, hop_s: float, min_sep_s: float = 0.05) -> set[int]:
    """Half-wave-rectified spectral flux + peak picking → onset frame
    indices in CREPE hop units."""
    import numpy as np

    hop = 512
    frame = 1024
    window = np.hanning(frame)
    n = 1 + max(0, (len(mono) - frame)) // hop
    mags = []
    for i in range(n):
        chunk = mono[i * hop : i * hop + frame]
        if len(chunk) < frame:
            chunk = np.pad(chunk, (0, frame - len(chunk)))
        mags.append(np.abs(np.fft.rfft(chunk * window)))
    flux = [0.0]
    for prev, cur in zip(mags, mags[1:], strict=False):
        flux.append(float(np.maximum(cur - prev, 0.0).sum()))
    peak = max(flux) or 1.0
    flux = [f / peak for f in flux]
    flux_hop_s = hop / rate
    peaks = pick_peaks(
        flux,
        min_separation=max(1, round(min_sep_s / flux_hop_s)),
        window=max(2, round(0.5 / flux_hop_s)),
        delta=0.05,
    )
    return {round(p * flux_hop_s / hop_s) for p in peaks}


def run(document: Document, config: Config) -> Document:
    import soundfile
    import torch
    import torchaudio

    torchcrepe = _import_torchcrepe()

    if document.audio is None:
        raise ValueError("transcribe requires ingest to have run first (document.audio is None)")
    tc = config.transcribe
    if tc.ensemble != "horn-led":
        raise NotImplementedError(
            f"ensemble {tc.ensemble!r} is not implemented yet — the piano path arrives at M7b"
        )
    stem_path = document.stems.get(tc.stem)
    if stem_path is None:
        available = ", ".join(sorted(document.stems)) or "none (run separation first)"
        raise ValueError(f"transcribe needs the {tc.stem!r} stem; available: {available}")

    data, rate = soundfile.read(stem_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    mono, region_offset = crop_region(mono, rate, tc.region)
    if tc.region:
        print(f"transcribe: region {tc.region[0]:.1f}-{tc.region[1]:.1f}s of {tc.stem} stem")
    mono16 = (
        torchaudio.functional.resample(torch.from_numpy(mono), rate, CREPE_SAMPLE_RATE)
        .numpy()
        .astype("float32")
    )
    hop_s = CREPE_HOP / CREPE_SAMPLE_RATE

    device = resolve_device(tc.device, torch.cuda.is_available())
    print(
        f"transcribe: crepe model={tc.crepe_model} device={device} "
        f"ensemble={tc.ensemble} stem={tc.stem}"
    )
    f0, periodicity = torchcrepe.predict(
        torch.from_numpy(mono16)[None],
        CREPE_SAMPLE_RATE,
        hop_length=CREPE_HOP,
        fmin=tc.fmin_hz,
        fmax=tc.fmax_hz,
        model=tc.crepe_model,
        decoder=torchcrepe.decode.weighted_argmax,  # viterbi needs numba-blocked librosa
        return_periodicity=True,
        batch_size=256,
        device=device,
    )
    f0 = f0[0].tolist()
    periodicity = periodicity[0].tolist()

    # Gate on periodicity AND frame energy — silence between phrases must
    # not transcribe (see module docstring for the thresholds' rationale).
    energetic = _frame_energy_gate(mono16, tc.silence_floor_db)
    count = min(len(f0), len(energetic))
    pitches: list[float | None] = [
        hz_to_midi(float(f0[i]))
        if periodicity[i] >= tc.voicing_threshold and energetic[i]
        else None
        for i in range(count)
    ]
    kernel = max(1, round(tc.median_filter_ms / 1000.0 / hop_s) | 1)
    pitches = median_smooth(pitches, kernel)

    onset_frames = _spectral_flux_onsets(mono, rate, hop_s)

    notes = segment_notes(
        pitches,
        [float(p) for p in periodicity[:count]],
        onset_frames,
        hop_s=hop_s,
        min_note_s=tc.min_note_ms / 1000.0,
        persist_frames=max(1, round(tc.pitch_persist_ms / 1000.0 / hop_s)),
        max_gap_frames=max(1, round(tc.silence_gap_ms / 1000.0 / hop_s)),
        source=f"{tc.stem}:crepe",
    )
    notes = fold_octave_outliers(notes)
    notes = offset_notes(notes, region_offset)  # back to whole-track time

    voiced_fraction = sum(1 for p in pitches if p is not None) / max(1, len(pitches))
    if notes:
        low = min(n.pitch for n in notes)
        high = max(n.pitch for n in notes)
        conf = statistics.fmean(n.confidence for n in notes)
        print(
            f"transcribe: {len(notes)} notes, pitch {low}–{high} (MIDI), "
            f"mean confidence {conf:.2f}, voiced {voiced_fraction:.0%} of frames"
        )
    else:
        print("transcribe: no notes found")

    return document.model_copy(update={"notes": {**document.notes, tc.stem: notes}})
