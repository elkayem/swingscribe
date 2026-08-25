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

A fourth hazard was added after M3 was scored against real transcriptions:
**following the wrong instrument**. f0 is decoded with a Viterbi path through
CREPE's per-frame pitch bins (pitch_step_cost), so leaving the line the
soloist is on has to be paid for. See `viterbi_bins` for why that matters and
what it does not fix.

Heavy imports (torch, torchcrepe, numpy, soundfile) stay inside functions:
this module must stay importable without the ml dependency group.

Only the horn-led ensemble is implemented; trio/solo-piano arrive at M7b.
"""

import math
import statistics
import sys
import types
from dataclasses import dataclass

from swingscribe import progress
from swingscribe.config import Config, TranscribeConfig
from swingscribe.device import resolve_device
from swingscribe.model import Document, NoteEvent

CREPE_SAMPLE_RATE = 16000
CREPE_HOP = 160  # 10ms frames
PITCH_BINS = 360  # CREPE's output resolution
CENTS_PER_BIN = 20.0
CENTS_ORIGIN = 1997.3794084376191  # cents of bin 0, from torchcrepe.convert

# Bump when this stage's behavior changes without a config change (see
# pipeline._cache_name).
CACHE_VERSION = 1


def hz_to_midi(hz: float) -> float:
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def _hz_to_bin(hz: float) -> float:
    """Frequency to CREPE pitch-bin index (fractional)."""
    return (1200.0 * math.log2(hz / 10.0) - CENTS_ORIGIN) / CENTS_PER_BIN


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


def harmonic_energy(
    mono,
    rate: int,
    pitch_midi: list[float | None],
    hop: int,
    n_harmonics: int = 4,
    frame_size: int = 1024,
) -> list[float]:
    """Per-frame energy in narrow bands around the *tracked pitch's* harmonics.

    This is the evidence that distinguishes a re-articulation from a neighbour
    instrument's transient: tonguing a held note puts fresh energy into that
    note's own harmonics, while a piano comp chord underneath it does not
    (open-issue #1). Frames with no tracked pitch score 0.0 — there is no
    "own pitch" to measure.
    """
    import numpy as np

    window = np.hanning(frame_size)
    half = frame_size // 2
    nyquist = rate / 2
    out: list[float] = []
    for i, midi in enumerate(pitch_midi):
        if midi is None:
            out.append(0.0)
            continue
        centre = i * hop
        lo = centre - half
        chunk = mono[max(0, lo) : lo + frame_size]
        if len(chunk) < frame_size:
            pad_left = max(0, -lo)
            chunk = np.pad(chunk, (pad_left, frame_size - len(chunk) - pad_left))
        spectrum = np.abs(np.fft.rfft(chunk * window))
        f0 = 440.0 * 2 ** ((midi - 69) / 12)
        total = 0.0
        for k in range(1, n_harmonics + 1):
            freq = f0 * k
            if freq >= nyquist:
                break
            bin_centre = int(round(freq * frame_size / rate))
            total += float(spectrum[max(0, bin_centre - 1) : bin_centre + 2].sum())
        out.append(total)
    return out


def corroborate_onsets(
    candidates: set[int],
    energy: list[float],
    pitch_midi: list[float | None],
    rise_db: float,
    window: int,
    dip_db: float = 0.0,
) -> set[int]:
    """Drop onsets that show no fresh attack in the tracked pitch's harmonics.

    An onset landing where no pitch is tracked is kept untouched — it falls
    outside a voiced run and the segmenter ignores it anyway. Inside a run, a
    split is allowed only when harmonic energy rises by `rise_db` across the
    candidate frame, which is what re-articulating the note actually does and
    what a neighbouring instrument's transient does not.

    `dip_db` adds the other half of that argument. A rise alone is weak
    evidence on a held note, because vibrato swells the harmonics several dB
    all by itself — measured, an 11-beat held note in All The Things was cut
    into five by exactly this. Re-articulating a note means interrupting it:
    the tongue stops the tone before the new attack, so the energy must fall
    below the sustain it is interrupting *and then* rise. A swell only rises.

    The dip is required only where it means something — where the pitch on
    both sides is the same note. A split between two different pitches is a
    slur, and a slurred pair has no dip at all.
    """
    import statistics as _stats

    if rise_db <= 0:
        return set(candidates)
    rise_ratio = 10.0 ** (rise_db / 20.0)
    dip_ratio = 10.0 ** (-dip_db / 20.0) if dip_db > 0 else None
    kept: set[int] = set()
    for i in candidates:
        if not (0 <= i < len(pitch_midi)) or pitch_midi[i] is None:
            kept.add(i)
            continue
        before = [e for e in energy[max(0, i - window) : i] if e > 0]
        after = energy[i : i + window]
        if not before or not after:
            kept.add(i)
            continue
        if max(after) < _stats.median(before) * rise_ratio:
            continue
        if dip_ratio is not None and _same_note_across(pitch_midi, i, window):
            trough = min(energy[max(0, i - 2) : i + 3] or [0.0])
            if trough > _stats.median(before) * dip_ratio:
                continue  # a swell, not a re-articulation
        kept.add(i)
    return kept


def _same_note_across(pitch_midi: list[float | None], i: int, window: int) -> bool:
    """Is the tracked pitch the same note either side of frame `i`?"""
    before = [p for p in pitch_midi[max(0, i - window) : i] if p is not None]
    after = [p for p in pitch_midi[i : i + window] if p is not None]
    if not before or not after:
        return False
    return round(statistics.median(before)) == round(statistics.median(after))


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


# ── Viterbi f0 decoding (open-issue #8) ──────────────────────────────────
#
# CREPE emits an independent probability for each of 360 pitch bins per 10ms
# frame. Decoding each frame by itself — torchcrepe's `weighted_argmax`, what
# we shipped through M3 — means nothing connects frame t to frame t-1, so the
# instant a comping piano out-shouts the soloist the reported pitch jumps to
# the piano and back. That is the mechanism behind open-issue #8, and the
# benchmark's 240 invented notes at unrelated pitches is its signature.
#
# torchcrepe ships a Viterbi decoder but routes it through
# librosa.sequence.viterbi, and librosa hard-requires numba, whose DLLs
# Application Control blocks here. So this is our own, in numpy.
#
# Two deliberate differences from torchcrepe's:
#
# 1. **A soft transition cost, not a hard band.** theirs forbids moving more
#    than 11 bins (2.2 semitones) per frame outright, so an octave leap has to
#    slide through every bin between, taking ~60ms — a quarter of a note at
#    bebop tempo. Ours charges `step_cost` per bin of distance and lets the
#    evidence decide. A leap is affordable when the evidence is strong; an
#    excursion that jumps away AND returns pays the cost twice, which is
#    exactly the asymmetry that separates a real interval from following the
#    piano for a moment.
#
# 2. **log(p), not log(softmax(p)).** `torchcrepe.infer` already returns
#    per-bin sigmoid probabilities (its variable is misleadingly named
#    `logits`), so theirs softmaxes an activation that is already a
#    probability. CREPE is trained with per-bin binary cross-entropy against a
#    blurred one-hot target, so the bins are independent probabilities and
#    log(p) is the observation likelihood the model was actually fit to.

BIN_FLOOR = -1e9  # stands in for -inf on out-of-range bins (keeps arithmetic finite)


def viterbi_bins(log_probs, step_cost: float):
    """Best pitch-bin path through a (frames, bins) log-probability matrix.

    Maximises  sum_t log_probs[t, b_t] - step_cost * |b_t - b_{t-1}|.

    The naive recurrence is O(bins^2) per frame. Because the transition
    penalty is linear in |i - j|, the inner maximisation is a max-plus
    distance transform and separates into a forward and a backward running
    maximum, each O(bins) and each vectorised:

        max_i (prev[i] - c|i-j|)
          = max( max_{i<=j}(prev[i] + c*i) - c*j ,
                 max_{i>=j}(prev[i] - c*i) + c*j )

    which is what turns a 360x360 matrix per frame into two accumulates.
    """
    import numpy as np

    log_probs = np.asarray(log_probs, dtype=np.float64)
    n_frames, n_bins = log_probs.shape
    if n_frames == 0:
        return []
    if step_cost <= 0:  # no continuity constraint — plain per-frame argmax
        return [int(b) for b in log_probs.argmax(axis=1)]

    idx = np.arange(n_bins, dtype=np.float64)
    ramp = step_cost * idx
    back = np.empty((n_frames, n_bins), dtype=np.int16)
    back[0] = idx
    score = log_probs[0].copy()

    for t in range(1, n_frames):
        # forward sweep: best predecessor at or below each bin
        g = score + ramp
        run_f = np.maximum.accumulate(g)
        arg_f = np.maximum.accumulate(np.where(g >= run_f, idx, -1.0))
        best_f = run_f - ramp

        # backward sweep: best predecessor at or above each bin
        h = (score - ramp)[::-1]
        run_b = np.maximum.accumulate(h)
        arg_b = (n_bins - 1) - np.maximum.accumulate(np.where(h >= run_b, idx, -1.0))
        best_b = run_b[::-1] + ramp
        arg_b = arg_b[::-1]

        take_f = best_f >= best_b
        back[t] = np.where(take_f, arg_f, arg_b).astype(np.int16)
        score = np.where(take_f, best_f, best_b) + log_probs[t]

    path = [0] * n_frames
    b = int(score.argmax())
    for t in range(n_frames - 1, -1, -1):
        path[t] = b
        b = int(back[t][b])
    return path


def refine_bins(probs, bins, window: int = 4):
    """Sub-bin pitch, in cents, by weighting probabilities around each bin.

    Viterbi picks a bin, and bins are 20 cents wide — coarse enough to matter
    for a median filter running over the result. This is torchcrepe's
    `weighted_argmax` refinement applied *around the path* instead of around
    the per-frame argmax: continuity chooses the region, the local weighted
    mean places the pitch inside it.
    """
    import numpy as np

    probs = np.asarray(probs, dtype=np.float64)
    n_frames, n_bins = probs.shape
    centres = CENTS_PER_BIN * np.arange(n_bins) + CENTS_ORIGIN
    out = np.empty(n_frames, dtype=np.float64)
    for t, b in enumerate(bins):
        lo, hi = max(0, b - window), min(n_bins, b + window + 1)
        weights = probs[t, lo:hi]
        total = weights.sum()
        out[t] = centres[lo:hi] @ weights / total if total > 0 else centres[b]
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


def _crepe_track(mono16, tc: TranscribeConfig, device: str, batch_size: int = 256):
    """CREPE f0 + periodicity for one mono 16kHz signal.

    Returns (f0_hz, periodicity) as plain lists. With `pitch_step_cost` at 0
    this delegates to `torchcrepe.predict` and is bit-identical to what M3
    shipped; above 0 it runs the whole excerpt through `viterbi_bins`.

    The Viterbi path deliberately does NOT go through torchcrepe's `decoder`
    hook: `predict` calls the decoder once per batch of frames, which would
    restart the path — and hand back a free jump — every 2.56s. Continuity is
    the entire point, so we drive `preprocess`/`infer` ourselves and decode
    the excerpt as one sequence.
    """
    import numpy as np
    import torch

    torchcrepe = _import_torchcrepe()
    audio = torch.from_numpy(mono16)[None]

    if tc.pitch_step_cost <= 0:
        f0, periodicity = torchcrepe.predict(
            audio,
            CREPE_SAMPLE_RATE,
            hop_length=CREPE_HOP,
            fmin=tc.fmin_hz,
            fmax=tc.fmax_hz,
            model=tc.crepe_model,
            decoder=torchcrepe.decode.weighted_argmax,
            return_periodicity=True,
            batch_size=batch_size,
            device=device,
        )
        return f0[0].tolist(), periodicity[0].tolist()

    chunks = []
    with torch.no_grad():
        for frames in torchcrepe.preprocess(
            audio,
            CREPE_SAMPLE_RATE,
            hop_length=CREPE_HOP,
            batch_size=batch_size,
            device=device,
        ):
            # (frames, 360) per-bin probabilities — sigmoid is already applied
            # inside the model, despite `infer`'s docstring calling them logits.
            chunks.append(torchcrepe.infer(frames, model=tc.crepe_model).cpu().numpy())
    probs = np.concatenate(chunks, axis=0).astype(np.float64)

    lo = int(np.floor(_hz_to_bin(tc.fmin_hz)))
    hi = int(np.ceil(_hz_to_bin(tc.fmax_hz)))
    log_probs = np.log(np.maximum(probs, 1e-12))
    log_probs[:, : max(0, lo)] = BIN_FLOOR
    log_probs[:, min(probs.shape[1], hi + 1) :] = BIN_FLOOR

    bins = viterbi_bins(log_probs, tc.pitch_step_cost)
    cents = refine_bins(probs, bins)
    f0 = 10.0 * 2.0 ** (cents / 1200.0)
    # Periodicity is the network's probability at the bin we CHOSE, matching
    # torchcrepe. Note the consequence: where continuity holds the path on the
    # soloist against a louder competitor, this reads low and the voicing gate
    # drops the frame — a spurious note becomes a rest rather than a right note.
    periodicity = probs[np.arange(len(bins)), bins]
    return f0.tolist(), periodicity.tolist()


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


@dataclass(frozen=True)
class FrameDiagnostics:
    """Per-frame trace of how the transcription decision was reached.

    Exists so a suspicious note can be traced to a *cause* — was the pitch
    wrong, was the frame gated out, did an onset split it — rather than
    guessed at. Deliberately NOT part of Document: it is an order of magnitude
    more data than the notes, nothing downstream consumes it, and putting it
    in the cached document would bloat every stage artifact for the sake of an
    opt-in overlay.

    All times are whole-track seconds. Lists are frame-aligned and equal
    length except `onsets`.
    """

    hop_s: float
    start: float  # whole-track time of frame 0
    f0_midi: list[float | None]  # raw CREPE pitch, BEFORE any gating
    periodicity: list[float]  # CREPE's own confidence
    energy_ok: list[bool]  # passed the silence-floor gate
    pitch: list[float | None]  # after both gates and median smoothing
    onsets: list[float]  # detected onset times (note-split candidates)

    @property
    def times(self) -> list[float]:
        return [self.start + i * self.hop_s for i in range(len(self.periodicity))]

    @property
    def voiced_fraction(self) -> float:
        return sum(1 for p in self.pitch if p is not None) / max(1, len(self.pitch))


def analyze(
    stem_path: str, tc: TranscribeConfig, *, log: bool = False
) -> tuple[list[NoteEvent], FrameDiagnostics]:
    """Transcribe one stem, returning the notes AND the per-frame trace.

    `run()` is a thin wrapper that keeps only the notes. Callers wanting the
    diagnostic overlay (the GUI's review screen) call this directly — which
    keeps transcription logic in the stage rather than duplicated in the UI.
    """
    import soundfile
    import torch
    import torchaudio

    data, rate = soundfile.read(stem_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    mono, region_offset = crop_region(mono, rate, tc.region)
    if log and tc.region:
        print(f"transcribe: region {tc.region[0]:.1f}-{tc.region[1]:.1f}s of {tc.stem} stem")

    mono16 = (
        torchaudio.functional.resample(torch.from_numpy(mono), rate, CREPE_SAMPLE_RATE)
        .numpy()
        .astype("float32")
    )
    hop_s = CREPE_HOP / CREPE_SAMPLE_RATE

    device = resolve_device(tc.device, torch.cuda.is_available())
    decoding = (
        f"viterbi (step cost {tc.pitch_step_cost})"
        if tc.pitch_step_cost > 0
        else "weighted argmax (per-frame)"
    )
    if log:
        print(
            f"transcribe: crepe model={tc.crepe_model} device={device} "
            f"ensemble={tc.ensemble} stem={tc.stem} decode={decoding}"
        )
    progress.report("transcribe", 0.05, f"running CREPE ({tc.crepe_model}) on {device}")
    f0, periodicity = _crepe_track(mono16, tc, device)

    # Gate on periodicity AND frame energy — silence between phrases must
    # not transcribe (see module docstring for the thresholds' rationale).
    progress.report("transcribe", 0.75, "gating and segmenting")
    energetic = _frame_energy_gate(mono16, tc.silence_floor_db)
    count = min(len(f0), len(energetic))
    raw_midi: list[float | None] = [
        hz_to_midi(float(f0[i])) if f0[i] and f0[i] > 0 else None for i in range(count)
    ]
    pitches: list[float | None] = [
        raw_midi[i] if periodicity[i] >= tc.voicing_threshold and energetic[i] else None
        for i in range(count)
    ]
    kernel = max(1, round(tc.median_filter_ms / 1000.0 / hop_s) | 1)
    pitches = median_smooth(pitches, kernel)

    # Broadband flux finds every transient in the stem, including the ones
    # belonging to other instruments. Keep only those corroborated by a fresh
    # attack in the tracked pitch's own harmonics (open-issue #1).
    raw_onsets = _spectral_flux_onsets(mono, rate, hop_s)
    h_energy = harmonic_energy(mono16, CREPE_SAMPLE_RATE, pitches, CREPE_HOP)
    onset_frames = corroborate_onsets(
        raw_onsets,
        h_energy,
        pitches,
        rise_db=tc.onset_rise_db,
        window=max(1, round(tc.onset_window_ms / 1000.0 / hop_s)),
        dip_db=tc.onset_dip_db,
    )
    if log and raw_onsets:
        print(
            f"transcribe: {len(onset_frames)}/{len(raw_onsets)} onsets corroborated "
            f"by harmonic attack (rest were other instruments)"
        )

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

    diagnostics = FrameDiagnostics(
        hop_s=hop_s,
        start=region_offset,
        f0_midi=raw_midi,
        periodicity=[float(p) for p in periodicity[:count]],
        energy_ok=list(energetic[:count]),
        pitch=pitches,
        onsets=sorted(region_offset + f * hop_s for f in onset_frames),
    )
    progress.report("transcribe", 1.0, f"{len(notes)} notes")
    return notes, diagnostics


def run(document: Document, config: Config) -> Document:
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

    notes, diagnostics = analyze(stem_path, tc, log=True)

    voiced_fraction = diagnostics.voiced_fraction
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
