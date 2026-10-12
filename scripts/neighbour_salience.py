"""Is the right pitch in CREPE's output when a short horn note comes out a
semitone or a whole tone off? (docs/neighbour-salience.md)

    .venv\\Scripts\\python.exe scripts/neighbour_salience.py --db wjazz/wjazzd.db

The error taxonomy's `neighbour` class (docs/error-taxonomy.md 4.2) is the
largest single horn error on WJazzD: our note starts within 50 ms of the
annotated one and reads one or two semitones off. Its frame evidence is the
DECODED pitch only -- the review cache keeps f0 after Viterbi -- so whether
the reference pitch was in CREPE's activation at all, a second peak the
decoder passed over, had never been looked at (error-taxonomy-review section
8, item 3). This re-runs CREPE over the solos with the most `neighbour` rows,
keeps the activations OUTSIDE the repo (`--out`: they are derived from
commercial recordings), and asks of every horn `neighbour` pair in them:

1. **Salience.** In the frames under the reference note, is there a local
   maximum of CREPE's activation within `AT_CENTS` of the reference pitch,
   apart from the chosen bin's own peak (`DISTINCT_CENTS`), and how tall is
   it against the bin the shipped decode chose? A pair has a REAL SECONDARY
   PEAK there when, in at least `PEAK_SHARE` of those frames, that peak is
   at least `PEAK_RATIO` of the chosen bin's height and `PEAK_FLOOR`
   absolute (CREPE's bins are independent sigmoids; an empty bin reads
   ~0.001-0.01). Sensitivity to all three is printed, and to the wide
   reading (a +-50-cent window, the chosen bin included), which counts a
   note played BETWEEN the two pitches as being at both.
2. **The decoder.** What `transcribe.viterbi_bins` gives at a lower
   `pitch_step_cost` (0.1, 0.05, 0.02, and 0 = per-frame argmax), both in
   the frames and as NOTES: the whole of `transcribe.analyze` is re-run on
   each decode, so the segmenter, the line floors and Basic Pitch's fill all
   act as shipped. The shipped decode (0.2) must reproduce the harness's
   cached notes -- that is the control that the activations, the stem, the
   span and the settings are the ones the table was made from.
3. **The stem.** WJazzD's own pitch can be wrong, so the chosen stem is
   asked too, over the reference note: harmonic energy at both pitches
   (peak power within 30 cents of harmonics 1-8, under 8 kHz), and where a
   harmonic comb scanned +-2.5 semitones peaks (`comb_peak`), read as AT
   the reference, AT our pitch (within `COMB_BAND`), BETWEEN them, or
   elsewhere.
4. **Bleed.** Whether another stem holds OUR pitch at that moment at least
   as strongly as the chosen stem (`error_taxonomy`'s cross-stem rule).

Both stem instruments are calibrated on short notes we got RIGHT in the
same solos (`control_pairs`): they must side with the played pitch, and a
"secondary peak" must not appear at a pitch nobody played.

Each pair is then filed under one cause, first rule wins:

    decoder-recoverable       a real secondary peak at the reference pitch
    decoded at the reference  the decode already chose it in half the
                              frames (the error is after CREPE)
    bleed                     another stem holds our pitch as strongly
    reference disputed        the stem's comb sits at OUR pitch
    between the two           the stem's comb sits between the pitches
    absent from CREPE         the stem's comb sits at the reference
    stem unclear              neither, or no reading

Kill criterion (the brief): a real secondary peak in fewer than a third of
the pairs means the error is not in the decoder.

Writes the per-pair table to `--out` (never the repo) and prints the
aggregate, which is all that enters docs/.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import json
import math
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Before anything can reach torchcrepe -> librosa -> numba: this runs from a
# background shell, where a refused llvmlite.dll HANGS rather than raising
# (CLAUDE.md). librosa only ever uses numba to optimise.
from swingscribe import numba_guard  # noqa: E402

numba_guard.install_passthrough()
sys.modules.setdefault("llvmlite", None)

TABLE = Path(".benchmark-taxonomy-table.csv")
OUT = Path(r"C:\Users\lkmcg\swingscribe-research\crepe-activations")
STEP_COSTS = (0.2, 0.1, 0.05, 0.02, 0.0)
SHIPPED_STEP = 0.2

PEAK_FLOOR = 0.1
PEAK_RATIO = 0.25
PEAK_SHARE = 0.5
HALF_WINDOW_CENTS = 50.0
AT_CENTS = 30.0
DISTINCT_CENTS = 60.0

HARMONICS = 8
HARMONIC_CEILING_HZ = 8000.0
BAND_CENTS = 30.0
MIN_WINDOW_S = 0.04
MAX_WINDOW_S = 0.3
DISPUTE_DB = 3.0
BLEED_RATIO = 1.0
ONSET_TOLERANCE_S = 0.05

COMB_SPAN = 2.5
# How near a pitch the stem's comb must peak to be AT it: the widest spread
# on 40 short notes we got right (In 'n Out, the trial) was 0.3 semitone.
COMB_BAND = 0.3
CONTROL_MAX_S = 0.2
CONTROL_PER_SOLO = 40

CAUSES = (
    "decoder-recoverable",
    "decoded at the reference",
    "bleed",
    "reference disputed",
    "between the two",
    "absent from CREPE",
    "stem unclear",
)


# ── which pairs ───────────────────────────────────────────────────────────


def neighbour_rows(table: Path) -> list[dict]:
    with table.open(encoding="utf-8") as handle:
        return [
            r for r in csv.DictReader(handle) if r["class"] == "neighbour" and r["family"] == "horn"
        ]


def worst_solos(rows: list[dict], n: int) -> list[str]:
    counts = collections.Counter(r["solo"] for r in rows)
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


# ── the solo: sidecar, fit, stems ─────────────────────────────────────────


def locate(db, runs, name: str, melid: int):
    """(run, sidecar, solo) as error_taxonomy.discover finds them."""
    import numpy as np
    import run_eval
    from score_wjazz import identify_all

    sidecar = next(
        (s for key, _path, _audio, s in run_eval.bench_takes(lambda _m: None) if key == name), None
    )
    if sidecar is None:
        raise RuntimeError(f"{name}: no sidecar in benchmark/")
    run = runs[name]
    onsets = np.array([n["onset"] for n in run["notes"]])
    pitches = np.array([int(n["pitch"]) for n in run["notes"]])
    order = np.argsort(onsets)
    found, why = identify_all(db, name, onsets[order], pitches[order], run["region"])
    solo = next((s for s in found if s["melid"] == melid), None)
    if solo is None:
        raise RuntimeError(f"{name}: melid {melid} not identified ({why})")
    return run, sidecar, solo


def stems_of(name: str, sidecar: dict):
    """(settings, chosen stem path, {other stem: path}, the ingested mix's
    path) as load_evidence reads them."""
    import error_taxonomy
    import run_eval

    from swingscribe.gui import library

    base = run_eval.eval_config()
    settings = run_eval.transcribe_settings(sidecar, SHIPPED_STEP, 0.0)
    config = base.model_copy(
        update={
            "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
            "transcribe": settings,
        }
    )
    document = library.ingested_document(
        library.audio_for_key(run_eval.BENCH, run_eval.track_of(name)), config
    )
    stems = library.available_stems(document, config, sidecar["model"])
    chosen = library.resolve_stem(document, config, sidecar["model"], settings.stem)
    if not chosen:
        raise RuntimeError(f"{name}: no {settings.stem!r} stem on disk")
    others = {
        other: stems[other]
        for other in error_taxonomy.OTHER_STEMS.get(sidecar["model"], ())
        if other in stems and other not in settings.stem.split("+")
    }
    return settings, str(chosen), others, str(document.audio.path)


# ── CREPE, with the activations kept ──────────────────────────────────────


def activations(stem_path: str, tc, path: Path, device: str):
    """(probs (frames, 360) float32, region offset). Computed once, exactly
    as `transcribe._crepe_track`'s Viterbi branch feeds `viterbi_bins`, and
    kept under `path`."""
    import numpy as np

    if path.is_file():
        with np.load(path) as data:
            return data["probs"], float(data["region_offset"])
    import soundfile
    import torch
    import torchaudio

    from swingscribe.stages import transcribe

    data, rate = soundfile.read(stem_path, dtype="float32", always_2d=True)
    mono, region_offset = transcribe.crop_region(data.mean(axis=1), rate, tc.region)
    mono16 = (
        torchaudio.functional.resample(torch.from_numpy(mono), rate, transcribe.CREPE_SAMPLE_RATE)
        .numpy()
        .astype("float32")
    )
    torchcrepe = transcribe._import_torchcrepe()
    audio = torch.from_numpy(mono16)[None]
    chunks = []
    with torch.no_grad():
        for frames in torchcrepe.preprocess(
            audio,
            transcribe.CREPE_SAMPLE_RATE,
            hop_length=transcribe.CREPE_HOP,
            batch_size=256,
            device=device,
        ):
            chunks.append(
                torchcrepe.infer(frames, model=tc.crepe_model, device=device).cpu().numpy()
            )
    probs = np.concatenate(chunks, axis=0).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, probs=probs, region_offset=region_offset)
    return probs, float(region_offset)


def masked_log_probs(probs, tc):
    import numpy as np

    from swingscribe.stages import transcribe

    lo = int(np.floor(transcribe._hz_to_bin(tc.fmin_hz)))
    hi = int(np.ceil(transcribe._hz_to_bin(tc.fmax_hz)))
    log_probs = np.log(np.maximum(probs.astype(np.float64), 1e-12))
    log_probs[:, : max(0, lo)] = transcribe.BIN_FLOOR
    log_probs[:, min(probs.shape[1], hi + 1) :] = transcribe.BIN_FLOOR
    return log_probs


_DECODES: dict = {}


def decode(probs, log_probs, step: float):
    """(bins, f0 Hz, periodicity): `_crepe_track`'s Viterbi branch, from kept
    activations. At step 0 viterbi_bins is the per-frame argmax of the SAME
    masked log-probabilities. Memoised per activation matrix and step."""
    import numpy as np

    from swingscribe.stages import transcribe

    key = (id(probs), step)
    if key not in _DECODES:
        bins = transcribe.viterbi_bins(log_probs, step)
        cents = transcribe.refine_bins(probs, bins)
        f0 = 10.0 * 2.0 ** (cents / 1200.0)
        periodicity = probs[np.arange(len(bins)), bins].astype(np.float64)
        _DECODES[key] = (np.asarray(bins), f0, periodicity)
    return _DECODES[key]


@contextlib.contextmanager
def crepe_from(probs, log_probs, step: float):
    """`transcribe.analyze` with its CREPE pass replaced by a decode of the
    kept activations: everything after it (gates, segmenter, floors, the
    fill) runs as shipped."""
    from swingscribe.stages import transcribe

    original = transcribe._crepe_track
    _bins, f0, periodicity = decode(probs, log_probs, step)

    def replay(mono16, _tc, _device, batch_size=256):
        expected = 1 + len(mono16) // transcribe.CREPE_HOP
        if expected != len(f0):
            raise RuntimeError(f"kept activations hold {len(f0)} frames, the stem {expected}")
        return f0.tolist(), periodicity.tolist()

    transcribe._crepe_track = replay
    try:
        yield
    finally:
        transcribe._crepe_track = original


def notes_at(stem_path, tc, probs, log_probs, step, **update):
    from swingscribe.stages import transcribe

    settings = tc.model_copy(update={"pitch_step_cost": step, **update})
    with crepe_from(probs, log_probs, step), contextlib.redirect_stdout(None):
        notes, _diagnostics = transcribe.analyze(stem_path, settings)
    return sorted(notes, key=lambda n: n.onset)


# ── pitch geometry ────────────────────────────────────────────────────────


def bin_of(midi: float) -> float:
    from swingscribe.stages import transcribe

    hz = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    return transcribe._hz_to_bin(hz)


def window(midi: float, n_bins: int, cents: float) -> tuple[int, int]:
    half = cents / 20.0
    centre = bin_of(midi)
    return max(0, math.ceil(centre - half)), min(n_bins - 1, math.floor(centre + half))


def peak_in(frame, lo: int, hi: int) -> float:
    """The height of a local maximum of the activation inside [lo, hi], or 0."""
    import numpy as np

    j = lo + int(np.argmax(frame[lo : hi + 1]))
    left = frame[j - 1] if j > 0 else -1.0
    right = frame[j + 1] if j + 1 < len(frame) else -1.0
    return float(frame[j]) if frame[j] >= left and frame[j] >= right else 0.0


def spectrum_of(signal, rate: int, t0: float, t1: float, lo_t: float):
    """(power spectrum, freqs) of [t0, t1] of a signal starting at `lo_t`,
    Hann-windowed and zero-padded at least 4x, or None for a sliver."""
    import numpy as np

    a, b = int((t0 - lo_t) * rate), int((t1 - lo_t) * rate)
    seg = signal[max(0, a) : max(0, b)]
    if len(seg) < 64:
        return None
    n_fft = 1 << max(14, math.ceil(math.log2(len(seg))) + 2)
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=n_fft)) ** 2
    return spectrum, np.fft.rfftfreq(n_fft, 1.0 / rate)


def _harmonics(midi: float) -> int:
    f0 = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    top = HARMONIC_CEILING_HZ / (f0 * 2.0 ** (BAND_CENTS / 1200.0))
    return max(1, min(HARMONICS, int(top)))


def harmonic_power(spec, midi: float, harmonics: int | None = None) -> float | None:
    """Sum over harmonics 1-8 (under 8 kHz) of the peak power within
    BAND_CENTS of each."""
    if spec is None:
        return None
    spectrum, freqs = spec
    f0 = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    ratio = 2.0 ** (BAND_CENTS / 1200.0)
    total = 0.0
    for k in range(1, (harmonics or _harmonics(midi)) + 1):
        band = (freqs >= k * f0 / ratio) & (freqs <= k * f0 * ratio)
        if band.any():
            total += float(spectrum[band].max())
    return total


def comb_peak(spec, centre: float) -> float | None:
    """Where the stem's harmonic comb peaks, in semitones from `centre`,
    scanning +-COMB_SPAN in 5-cent steps with the centre's harmonic count:
    a continuous reading of the pitch the stem holds."""
    import numpy as np

    if spec is None:
        return None
    spectrum, freqs = spec
    k = np.arange(1, _harmonics(centre) + 1)
    offsets = np.arange(-COMB_SPAN, COMB_SPAN + 1e-9, 0.05)
    step = freqs[1] - freqs[0]
    scores = []
    for offset in offsets:
        f0 = 440.0 * 2.0 ** ((centre + offset - 69.0) / 12.0)
        idx = np.minimum(np.rint(k * f0 / step).astype(int), len(spectrum) - 1)
        scores.append(float(spectrum[idx].sum()))
    return round(float(offsets[int(np.argmax(scores))]), 2)


# ── one pair ──────────────────────────────────────────────────────────────


def pair_facts(row, reference, trace):
    """Everything the classification reads for one `neighbour` pair."""
    index = int(row["ref_index"])
    ref = reference[index]
    if abs(ref["onset"] - float(row["ref_onset"])) > 0.002 or ref["pitch"] != int(row["ref_pitch"]):
        raise RuntimeError(f"ref_index {index} is not the table's reference note")
    ref_pitch, est_pitch = int(row["ref_pitch"]), int(row["est_pitch"])
    # Where the note sounds in OUR timeline: the fit's local residual (ours
    # minus theirs, read off the matched notes) taken out.
    resid = float(row["align_resid"]) if row["align_resid"] else 0.0
    start = float(row["ref_onset"]) + resid
    duration = max(float(row["ref_duration"] or 0.0), 0.01)
    following = reference[index + 1]["onset"] + resid if index + 1 < len(reference) else start + 1.0
    facts = {
        "solo": row["solo"],
        "instrument": row["instrument"],
        "tempo": float(row["tempo"]) if row["tempo"] else None,
        "ref_onset": round(float(row["ref_onset"]), 3),
        "ref_pitch": ref_pitch,
        "ref_duration": round(duration, 3),
        "est_onset": round(float(row["est_onset"]), 3),
        "est_pitch": est_pitch,
        "dpitch": est_pitch - ref_pitch,
        "adjacent": int(
            any(
                0 <= j < len(reference) and reference[j]["pitch"] == est_pitch
                for j in (index - 1, index + 1)
            )
        ),
    }
    facts.update(measure(start, duration, following, ref_pitch, est_pitch, trace))
    return facts


def measure(start, duration, following, ref_pitch, est_pitch, trace):
    """Salience, decodes, stem and bleed for a note sounding from `start` for
    `duration`, the reference at `ref_pitch` and ours at `est_pitch`. `trace`
    carries the solo's activations and audio; its `tuning` is the recording's
    measured offset from A440 (semitones), which places the pitch windows in
    CREPE's bins and the harmonics in the spectrum, and `rounding` is the part
    of it the stage takes out before rounding (all of it from
    `tuning_min_cents`, else none)."""
    import numpy as np

    from swingscribe.stages import transcribe

    probs, chosen_bins, decodes = trace["probs"], trace["chosen_bins"], trace["decodes"]
    tuning, rounding, region_offset = trace["tuning"], trace["rounding"], trace["region_offset"]
    hop = transcribe.CREPE_HOP / transcribe.CREPE_SAMPLE_RATE
    end = start + duration
    n = len(chosen_bins)
    first = max(0, math.ceil((start - region_offset) / hop))
    last = min(n - 1, math.floor((end - region_offset) / hop))
    frames = list(range(first, last + 1)) or [
        min(n - 1, max(0, round((start + duration / 2 - region_offset) / hop)))
    ]
    # AT the reference: within AT_CENTS of it. A bin 50 cents off is as near
    # our pitch as theirs -- a note played between the two -- so the wide
    # +-50 window is kept only as `wide_share`, for the sensitivity table.
    ref_lo, ref_hi = window(ref_pitch + tuning, probs.shape[1], AT_CENTS)
    wide_lo, wide_hi = window(ref_pitch + tuning, probs.shape[1], HALF_WINDOW_CENTS)
    est_lo, est_hi = window(est_pitch + tuning, probs.shape[1], AT_CENTS)

    chosen_ref = argmax_ref = wide = 0
    ratios = []
    at = dict.fromkeys((0.1, 0.25, 0.5), 0)
    floor_at = dict.fromkeys((0.05, 0.1, 0.2), 0)
    for t in frames:
        frame = probs[t]
        b = int(chosen_bins[t])
        chosen = float(frame[b])
        chosen_ref += ref_lo <= b <= ref_hi
        argmax_ref += ref_lo <= int(np.argmax(frame)) <= ref_hi
        # A SECONDARY peak: a local maximum at the reference that is not the
        # chosen bin's own peak (at least DISTINCT_CENTS from it).
        height = peak_in(frame, ref_lo, ref_hi)
        if height > 0:
            j = ref_lo + int(np.argmax(frame[ref_lo : ref_hi + 1]))
            if abs(j - b) * 20.0 < DISTINCT_CENTS:
                height = 0.0
        ratio = height / chosen if chosen > 0 else 0.0
        ratios.append(ratio)
        for theta in at:
            at[theta] += height >= PEAK_FLOOR and ratio >= theta
        for floor in floor_at:
            floor_at[floor] += height >= floor and ratio >= PEAK_RATIO
        wide_height = peak_in(frame, wide_lo, wide_hi)
        wide += wide_lo <= b <= wide_hi or (
            wide_height >= PEAK_FLOOR and wide_height >= PEAK_RATIO * chosen
        )
    count = len(frames)

    facts = {
        "frames": count,
        "chosen_ref_share": chosen_ref / count,
        "argmax_ref_share": argmax_ref / count,
        "peak_share": at[PEAK_RATIO] / count,
        "peak_share_r10": at[0.1] / count,
        "peak_share_r50": at[0.5] / count,
        "peak_share_f05": floor_at[0.05] / count,
        "peak_share_f20": floor_at[0.2] / count,
        "wide_share": wide / count,
        "ratio_median": statistics.median(ratios),
        "ratio_max": max(ratios),
        "est_chosen_share": sum(est_lo <= chosen_bins[t] <= est_hi for t in frames) / count,
    }
    for step, midi in decodes.items():
        held = sum(
            t < len(midi) and midi[t] is not None and round(midi[t] - rounding) == ref_pitch
            for t in frames
        )
        facts[f"frames_at_ref_c{step}"] = held / count

    # The stem, over the reference note: never past the next reference onset,
    # at least MIN_WINDOW_S where that allows, at most MAX_WINDOW_S.
    t1 = min(max(end, start + MIN_WINDOW_S), following, start + MAX_WINDOW_S)
    t1 = max(t1, start + 0.02)
    signal, rate, lo_t, others = trace["audio"]
    spec = spectrum_of(signal, rate, start, t1, lo_t)
    # One harmonic count for both pitches, so neither is summed over more.
    harmonics = _harmonics(max(ref_pitch, est_pitch) + tuning)
    own_ref = harmonic_power(spec, ref_pitch + tuning, harmonics)
    own_est = harmonic_power(spec, est_pitch + tuning, harmonics)
    facts["stem_ref_db"] = (
        None if not own_ref or not own_est else round(10.0 * math.log10(own_ref / own_est), 2)
    )
    comb = comb_peak(spec, ref_pitch + tuning)
    facts["stem_pitch"] = comb  # semitones from the reference
    facts["stem_at"] = where(comb, est_pitch - ref_pitch)
    # The same comb on the MIX: a verdict the separation could have made up
    # must survive in the recording itself.
    mix_signal, mix_rate = trace["mix"]
    mix_comb = comb_peak(spectrum_of(mix_signal, mix_rate, start, t1, lo_t), ref_pitch + tuning)
    facts["mix_pitch"] = mix_comb
    facts["mix_at"] = where(mix_comb, est_pitch - ref_pitch)
    bleed = None
    if own_est:
        for other in others.values():
            power = harmonic_power(
                spectrum_of(other, rate, start, t1, lo_t), est_pitch + tuning, harmonics
            )
            if power is not None:
                bleed = max(bleed or 0.0, power / own_est)
    facts["bleed_ratio"] = None if bleed is None else round(bleed, 3)
    return facts


def where(comb: float | None, dpitch: int) -> str | None:
    """A comb reading (semitones from the reference) as AT the reference,
    AT our pitch, BETWEEN them, or elsewhere."""
    if comb is None:
        return None
    if abs(comb) <= COMB_BAND:
        return "ref"
    if abs(comb - dpitch) <= COMB_BAND:
        return "ours"
    if 0 < comb / dpitch < 1:
        return "between"
    return "elsewhere"


def real_peak(facts, share=PEAK_SHARE, key="peak_share") -> bool:
    return facts[key] >= share


def cause(facts) -> str:
    """One cause per pair, first rule wins (module docstring)."""
    if real_peak(facts):
        return "decoder-recoverable"
    if facts["chosen_ref_share"] >= PEAK_SHARE:
        return "decoded at the reference"
    if facts["bleed_ratio"] is not None and facts["bleed_ratio"] >= BLEED_RATIO:
        return "bleed"
    return {
        "ours": "reference disputed",
        "between": "between the two",
        "ref": "absent from CREPE",
    }.get(facts["stem_at"], "stem unclear")


def resolved(notes, facts) -> bool:
    """Whether these notes hold the reference note: one at its pitch starting
    within 50 ms of it (mir_eval's tolerance; the residual NOT taken out,
    as the scorecard does not)."""
    return any(
        n.pitch == facts["ref_pitch"] and abs(n.onset - facts["ref_onset"]) <= ONSET_TOLERANCE_S
        for n in notes
    )


# ── the run ───────────────────────────────────────────────────────────────


def smoothed_midi(f0, periodicity, energetic, tc):
    """The gated, median-smoothed pitch `analyze` rounds (before tuning)."""
    from swingscribe.stages import transcribe

    count = min(len(f0), len(energetic))
    pitches = [
        transcribe.hz_to_midi(float(f0[i]))
        if f0[i] > 0 and periodicity[i] >= tc.voicing_threshold and energetic[i]
        else None
        for i in range(count)
    ]
    kernel = max(1, round(tc.median_filter_ms / 1000.0 / 0.01) | 1)
    return transcribe.median_smooth(pitches, kernel)


def control_pairs(name, reference, cached, trace, seed):
    """The instruments' calibration, on notes we got RIGHT: short reference
    notes (<= CONTROL_MAX_S) mir_eval matched at the right pitch, a sample
    of CONTROL_PER_SOLO. Each is measured twice against a neighbour pitch d
    (cycling +1 -1 +1 -1 +1 -1 +2 -2, the neighbour class's own mix):

    - `true`: reference = the played pitch, ours = played + d. How often the
      stem and the comb side with a pitch we KNOW was played.
    - `phantom`: reference = played + d, ours = the played pitch. How often
      a "real peak" shows at a pitch nobody played: the base rate the
      neighbour pairs' real-peak count must clear.
    """
    import random

    import mir_eval
    import numpy as np

    from swingscribe import taxonomy
    from swingscribe.metrics import midi_to_hz

    lo, hi = reference[0]["onset"] - 0.25, reference[-1]["onset"] + 0.25
    ours = [n for n in cached if lo <= n["onset"] <= hi]
    ref_int = np.array([[r["onset"], r["onset"] + 0.1] for r in reference])
    est_int = np.array([[n["onset"], n["onset"] + max(n["duration"], 1e-4)] for n in ours])
    hits = mir_eval.transcription.match_notes(
        ref_int,
        np.array([midi_to_hz(r["pitch"]) for r in reference]),
        est_int,
        np.array([midi_to_hz(n["pitch"]) for n in ours]),
        onset_tolerance=ONSET_TOLERANCE_S,
        pitch_tolerance=50.0,
        offset_ratio=None,
    )
    matched = [(reference[i]["onset"], ours[j]["onset"] - reference[i]["onset"]) for i, j in hits]
    short = [i for i, _j in hits if reference[i]["duration"] <= CONTROL_MAX_S]
    rng = random.Random(seed)
    chosen = sorted(rng.sample(short, min(CONTROL_PER_SOLO, len(short))))
    cycle = (1, -1, 1, -1, 1, -1, 2, -2)
    rows = []
    for k, i in enumerate(chosen):
        r = reference[i]
        resid = taxonomy.alignment_residual(matched, r["onset"])
        start = r["onset"] + resid
        duration = max(r["duration"], 0.01)
        following = reference[i + 1]["onset"] + resid if i + 1 < len(reference) else start + 1.0
        d = cycle[k % len(cycle)]
        for kind, ref_pitch, est_pitch in (
            ("true", r["pitch"], r["pitch"] + d),
            ("phantom", r["pitch"] + d, r["pitch"]),
        ):
            facts = {
                "solo": name,
                "kind": kind,
                "ref_onset": round(r["onset"], 3),
                "ref_duration": round(duration, 3),
                "played": r["pitch"],
                "dpitch": est_pitch - ref_pitch,
            }
            facts.update(measure(start, duration, following, ref_pitch, est_pitch, trace))
            rows.append(facts)
    return rows


def solo_pass(name, rows, db, runs, out: Path, device: str, log=print):
    import error_taxonomy
    import numpy as np
    import run_eval
    import soundfile
    import torch
    import torchaudio
    from score_wjazz import score

    from swingscribe.stages import transcribe

    melid = int(rows[0]["melid"])
    run, sidecar, solo = locate(db, runs, name, melid)
    settings, stem_path, other_paths, mix_path = stems_of(name, sidecar)
    fingerprint_ok = run_eval.transcribe_fingerprint(sidecar, SHIPPED_STEP, 0.0) == run.get(
        "fingerprint"
    )

    started = time.time()
    probs, region_offset = activations(
        stem_path, settings, out / (Path(name).stem + ".npz"), device
    )
    crepe_s = time.time() - started
    log_probs = masked_log_probs(probs, settings)

    # The shipped decode: the control. Its notes must be the harness's.
    shipped = notes_at(stem_path, settings, probs, log_probs, SHIPPED_STEP)
    cached = sorted(run["notes"], key=lambda n: n["onset"])
    control = error_taxonomy.same_transcription(
        cached, [{"onset": n.onset, "pitch": n.pitch} for n in shipped]
    )

    # Frame-level decodes, rounded the way analyze rounds (tuning included).
    data, rate = soundfile.read(stem_path, dtype="float32", always_2d=True)
    mono, _ = transcribe.crop_region(data.mean(axis=1), rate, settings.region)
    mono16 = (
        torchaudio.functional.resample(torch.from_numpy(mono), rate, transcribe.CREPE_SAMPLE_RATE)
        .numpy()
        .astype("float32")
    )
    energetic = transcribe._frame_energy_gate(mono16, settings.silence_floor_db)
    decodes, chosen_bins, tuning = {}, None, 0.0
    for step in STEP_COSTS:
        bins, f0, periodicity = decode(probs, log_probs, step)
        midi = smoothed_midi(f0, periodicity, energetic, settings)
        if step == SHIPPED_STEP:
            chosen_bins = bins
            offset, _concentration = transcribe.tuning_offset(midi)
            tuning = offset
        decodes[step] = midi
    applied = settings.uses_tuning_correction and abs(tuning) * 100.0 >= settings.tuning_min_cents

    # Notes at every step cost, and the shipped decode without the fill: a
    # pair whose note only the fill wrote is not CREPE's to answer for.
    notes = {SHIPPED_STEP: shipped}
    for step in STEP_COSTS:
        if step != SHIPPED_STEP:
            notes[step] = notes_at(stem_path, settings, probs, log_probs, step)
    crepe_only = notes_at(stem_path, settings, probs, log_probs, SHIPPED_STEP, horn_fill_gaps=False)

    lo_t = max(0.0, region_offset - 1.0)
    whole = data.mean(axis=1)[int(lo_t * rate) :]
    others = {}
    for other, path in other_paths.items():
        signal, other_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
        if other_rate == rate:
            others[other] = signal.mean(axis=1)[int(lo_t * rate) :]
    audio = (whole, rate, lo_t, others)
    mix, mix_rate = soundfile.read(mix_path, dtype="float32", always_2d=True)
    mix = (mix.mean(axis=1)[int(lo_t * mix_rate) :], mix_rate)

    trace = {
        "probs": probs,
        "chosen_bins": chosen_bins,
        "decodes": decodes,
        "tuning": tuning,
        "rounding": tuning if applied else 0.0,
        "region_offset": region_offset,
        "audio": audio,
        "mix": mix,
    }
    reference = error_taxonomy.reference_notes(db, solo)
    pairs = []
    for row in rows:
        facts = pair_facts(row, reference, trace)
        facts["fill_note"] = int(
            not any(
                n.pitch == facts["est_pitch"] and abs(n.onset - facts["est_onset"]) <= 0.002
                for n in crepe_only
            )
        )
        facts["in_shipped"] = int(
            any(
                n.pitch == facts["est_pitch"] and abs(n.onset - facts["est_onset"]) <= 0.002
                for n in shipped
            )
        )
        for step in STEP_COSTS:
            facts[f"resolved_c{step}"] = int(resolved(notes[step], facts))
        facts["cause"] = cause(facts)
        pairs.append(facts)

    controls = control_pairs(name, reference, cached, trace, melid)

    est_on = lambda ns: np.array([n.onset for n in ns])  # noqa: E731
    as_dicts = lambda ns: [  # noqa: E731
        {"onset": n.onset, "duration": n.duration, "pitch": n.pitch, "confidence": n.confidence}
        for n in ns
    ]
    f1 = {
        step: round(score(solo, est_on(notes[step]), as_dicts(notes[step]))["note_f1"], 4)
        for step in STEP_COSTS
    }
    summary = {
        "name": name,
        "melid": melid,
        "instrument": rows[0]["instrument"],
        "pairs": len(pairs),
        "frames": int(probs.shape[0]),
        "crepe_s": round(crepe_s, 1),
        "fingerprint_current": fingerprint_ok,
        "control_reproduces_cached_notes": control,
        "tuning_cents": round(tuning * 100.0, 1),
        "tuning_applied": applied,
        "note_f1": f1,
        "pinned_note_f1": None,
    }
    pinned = json.loads(Path("tests/regression/real-audio-baselines.json").read_text("utf-8"))
    summary["pinned_note_f1"] = pinned.get(f"wjazz/{Path(name).stem}/note_f1")
    log(
        f"  {name}: {len(pairs)} pairs, control {'OK' if control else 'DIFFERS'}, "
        f"fingerprint {'current' if fingerprint_ok else 'STALE'}, tuning {tuning * 100:+.1f}c, "
        f"F1 {f1}, pinned {summary['pinned_note_f1']}, CREPE {crepe_s:.0f}s"
    )
    return summary, pairs, controls


# ── the aggregate ─────────────────────────────────────────────────────────


def _plain(value):
    """numpy scalars, for json."""
    return value.item()


def share(count: int, n: int) -> str:
    return f"{count} of {n} ({count / n:.0%})" if n else "0 of 0"


def aggregate(pairs: list[dict], summaries: list[dict]) -> dict:
    n = len(pairs)
    crepe = [p for p in pairs if not p["fill_note"]]
    out = {
        "solos": len(summaries),
        "pairs": n,
        "pairs_from_crepe": len(crepe),
        "pairs_fill_note": n - len(crepe),
        "controls_ok": sum(s["control_reproduces_cached_notes"] for s in summaries),
        "real_peak": sum(real_peak(p) for p in pairs),
        "real_peak_crepe": sum(real_peak(p) for p in crepe),
        "causes": dict(collections.Counter(p["cause"] for p in pairs)),
        "causes_crepe": dict(collections.Counter(p["cause"] for p in crepe)),
        "chosen_ref_half": sum(p["chosen_ref_share"] >= 0.5 for p in pairs),
        "argmax_ref_half": sum(p["argmax_ref_share"] >= 0.5 for p in pairs),
        "any_frame_peak": sum(p["peak_share"] > 0 for p in pairs),
        "ratio_median_of_medians": round(statistics.median(p["ratio_median"] for p in pairs), 4)
        if pairs
        else None,
        "sensitivity": {},
        "stem": {
            "supports_ref": sum(
                p["stem_ref_db"] is not None and p["stem_ref_db"] >= DISPUTE_DB for p in pairs
            ),
            "disputes_ref": sum(
                p["stem_ref_db"] is not None and p["stem_ref_db"] <= -DISPUTE_DB for p in pairs
            ),
            "undecided": sum(
                p["stem_ref_db"] is not None and abs(p["stem_ref_db"]) < DISPUTE_DB for p in pairs
            ),
            "no_reading": sum(p["stem_ref_db"] is None for p in pairs),
            "median_db": round(
                statistics.median(p["stem_ref_db"] for p in pairs if p["stem_ref_db"] is not None),
                2,
            ),
        },
        "bleed": sum(
            p["bleed_ratio"] is not None and p["bleed_ratio"] >= BLEED_RATIO for p in pairs
        ),
        "comb_at": dict(collections.Counter(p["stem_at"] for p in pairs)),
        "mix_at": dict(collections.Counter(p["mix_at"] for p in pairs)),
        "stem_vs_mix": dict(
            collections.Counter(f"{p['stem_at']}/{p['mix_at']}" for p in pairs).most_common()
        ),
        "adjacent": sum(p["adjacent"] for p in pairs),
        "real_peak_adjacent": sum(real_peak(p) for p in pairs if p["adjacent"]),
        "resolved": {str(step): sum(p[f"resolved_c{step}"] for p in pairs) for step in STEP_COSTS},
        "frames_at_ref_half": {
            str(step): sum(p[f"frames_at_ref_c{step}"] >= 0.5 for p in pairs) for step in STEP_COSTS
        },
        "note_f1_mean": {
            str(step): round(statistics.mean(s["note_f1"][step] for s in summaries), 4)
            for step in STEP_COSTS
        },
        "note_f1_up_down": {
            str(step): [
                sum(s["note_f1"][step] > s["note_f1"][SHIPPED_STEP] + 1e-9 for s in summaries),
                sum(s["note_f1"][step] < s["note_f1"][SHIPPED_STEP] - 1e-9 for s in summaries),
            ]
            for step in STEP_COSTS
        },
    }
    for key, label in (
        ("peak_share", f"ratio {PEAK_RATIO}, floor {PEAK_FLOOR}"),
        ("peak_share_r10", f"ratio 0.1, floor {PEAK_FLOOR}"),
        ("peak_share_r50", f"ratio 0.5, floor {PEAK_FLOOR}"),
        ("peak_share_f05", f"ratio {PEAK_RATIO}, floor 0.05"),
        ("peak_share_f20", f"ratio {PEAK_RATIO}, floor 0.2"),
        ("wide_share", "wide: +-50 cents, the chosen bin included"),
    ):
        out["sensitivity"][label] = {
            f"share {s}": sum(real_peak(p, s, key) for p in pairs) for s in (0.25, 0.5, 0.75)
        }
    out["comb_toward_ours"] = toward_quantiles(pairs)
    out["comb_by_bleed"] = {
        str(flag): dict(
            collections.Counter(
                p["stem_at"]
                for p in pairs
                if (p["bleed_ratio"] is not None and p["bleed_ratio"] >= BLEED_RATIO) == flag
            )
        )
        for flag in (True, False)
    }
    out["causes_by_instrument"] = {
        inst: dict(collections.Counter(p["cause"] for p in pairs if p["instrument"] == inst))
        for inst in sorted({p["instrument"] for p in pairs})
    }
    out["causes_by_solo"] = {
        Path(name).stem: dict(collections.Counter(p["cause"] for p in pairs if p["solo"] == name))
        for name in dict.fromkeys(p["solo"] for p in pairs)
    }
    out["by_cause_resolved_c0.0"] = {
        c: sum(p["resolved_c0.0"] for p in pairs if p["cause"] == c) for c in CAUSES
    }
    out["by_dpitch"] = {
        str(d): {
            "n": sum(p["dpitch"] == d for p in pairs),
            "real_peak": sum(real_peak(p) for p in pairs if p["dpitch"] == d),
        }
        for d in (-2, -1, 1, 2)
    }
    return out


def render(agg: dict) -> None:
    n = agg["pairs"]
    print(f"\n== {n} horn `neighbour` pairs over {agg['solos']} solos ==")
    print(f"controls reproducing the cached notes: {agg['controls_ok']} of {agg['solos']}")
    print(f"pairs whose note Basic Pitch's fill wrote: {agg['pairs_fill_note']}")
    print(f"\nreal SECONDARY peak at the reference pitch: {share(agg['real_peak'], n)}")
    print(f"  of the CREPE-written pairs: {share(agg['real_peak_crepe'], agg['pairs_from_crepe'])}")
    print(
        "  the decoder CHOSE the reference pitch in half the frames: "
        + share(agg["chosen_ref_half"], n)
    )
    print(
        "  the per-frame argmax is the reference in half the frames: "
        + share(agg["argmax_ref_half"], n)
    )
    print(f"  any frame with a real peak there: {share(agg['any_frame_peak'], n)}")
    print(
        f"  median (over pairs) of the median peak/chosen ratio: {agg['ratio_median_of_medians']}"
    )
    print("\nsensitivity of the real-peak count:")
    for label, row in agg["sensitivity"].items():
        print(f"  {label}: " + ", ".join(f"{k} -> {v}" for k, v in row.items()))
    print("\nby step:", json.dumps(agg["by_dpitch"]))
    print(f"\ncauses: {json.dumps(agg['causes'])}")
    print(f"causes, CREPE-written only: {json.dumps(agg['causes_crepe'])}")
    print(f"stem: {json.dumps(agg['stem'])}")
    print(f"the stem's harmonic comb peaks at: {json.dumps(agg['comb_at'])}")
    print(f"  as a fraction of the way to our pitch: {json.dumps(agg['comb_toward_ours'])}")
    print(f"the MIX's comb peaks at: {json.dumps(agg['mix_at'])}")
    print(f"  stem/mix: {json.dumps(agg['stem_vs_mix'])}")
    print(f"  by bleed (True = another stem holds our pitch): {json.dumps(agg['comb_by_bleed'])}")
    print(f"causes by instrument: {json.dumps(agg['causes_by_instrument'])}")
    for solo, causes in agg["causes_by_solo"].items():
        print(f"  {solo}: {json.dumps(causes)}")
    print(f"bleed (another stem >= the chosen at our pitch): {share(agg['bleed'], n)}")
    print(
        f"our pitch = an adjacent reference note's: {share(agg['adjacent'], n)}, "
        f"real peak among them {agg['real_peak_adjacent']}"
    )
    print("\nresolved as NOTES at each step cost (a note at the reference pitch within 50 ms):")
    for step, count in agg["resolved"].items():
        print(
            f"  step {step}: {share(count, n)}; frames at ref in half the note "
            f"{agg['frames_at_ref_half'][step]}; mean note F1 {agg['note_f1_mean'][step]} "
            f"(up/down vs 0.2: {agg['note_f1_up_down'][step]})"
        )
    print(f"resolved at argmax, by cause: {json.dumps(agg['by_cause_resolved_c0.0'])}")


def toward_quantiles(rows) -> dict:
    """Where the comb peaks as a fraction of the way from the reference (0)
    to our pitch (1): quantiles over the rows."""
    values = sorted(p["stem_pitch"] / p["dpitch"] for p in rows if p["stem_pitch"] is not None)
    if not values:
        return {}
    return {
        f"p{int(q * 100)}": round(values[int(q * (len(values) - 1))], 2)
        for q in (0.1, 0.25, 0.5, 0.75, 0.9)
    }


def stem_summary(rows) -> dict:
    with_db = [p["stem_ref_db"] for p in rows if p["stem_ref_db"] is not None]
    return {
        "n": len(rows),
        "supports_ref": sum(d >= DISPUTE_DB for d in with_db),
        "disputes_ref": sum(d <= -DISPUTE_DB for d in with_db),
        "undecided": sum(abs(d) < DISPUTE_DB for d in with_db),
        "median_db": round(statistics.median(with_db), 2) if with_db else None,
        "comb_at": dict(collections.Counter(p["stem_at"] for p in rows)),
        "mix_at": dict(collections.Counter(p["mix_at"] for p in rows)),
        "bleed": sum(
            p["bleed_ratio"] is not None and p["bleed_ratio"] >= BLEED_RATIO for p in rows
        ),
    }


def calibrate(controls) -> dict:
    out = {}
    for kind in ("true", "phantom"):
        rows = [c for c in controls if c["kind"] == kind]
        out[kind] = {
            "real_peak": sum(real_peak(c) for c in rows),
            "chosen_ref_half": sum(c["chosen_ref_share"] >= 0.5 for c in rows),
            "comb_toward_ours": toward_quantiles(rows),
            **stem_summary(rows),
        }
    return out


def render_controls(cal: dict) -> None:
    print("\n== calibration on short notes we got RIGHT ==")
    for kind, label in (
        ("true", "reference = the played pitch, ours = a neighbour"),
        ("phantom", "reference = a neighbour nobody played, ours = the played pitch"),
    ):
        c = cal[kind]
        print(
            f"  {label}: n {c['n']}; real peak at the 'reference' "
            f"{share(c['real_peak'], c['n'])}; stem supports the 'reference' "
            f"{c['supports_ref']}, disputes {c['disputes_ref']}, undecided {c['undecided']}, "
            f"median {c['median_db']} dB; comb at {c['comb_at']} "
            f"(toward 'ours' {c['comb_toward_ours']}); mix comb at {c['mix_at']}; "
            f"bleed {c['bleed']}"
        )


# ── can the activation hold a second peak at all? ─────────────────────────


def second_peak(frame, min_bins: int = 3, floor: float = 0.02):
    """(top bin, next local maximum at least `min_bins` from it, its height
    over the top's), or Nones."""
    peaks = [
        j
        for j in range(1, len(frame) - 1)
        if frame[j] >= frame[j - 1] and frame[j] >= frame[j + 1] and frame[j] >= floor
    ]
    if not peaks:
        return None, None, None
    top = max(peaks, key=lambda j: frame[j])
    rest = [j for j in peaks if abs(j - top) >= min_bins]
    if not rest:
        return top, None, None
    other = max(rest, key=lambda j: frame[j])
    return top, other, float(frame[other] / frame[top])


def positive_control(out: Path, device: str) -> None:
    """The secondary-peak test reads zero on the neighbour pairs; is that the
    test or CREPE? Two answers, neither touching the pairs:

    1. every voiced frame (top >= 0.5) of every kept activation: how often a
       second local maximum stands 60-250 cents (a semitone or a tone) from
       the top at >= 0.1/0.25/0.5 of it, and further away;
    2. a harmonic tone at D4 plus a second tone d semitones up at a relative
       level, through CREPE full: the activation at both pitches, and the
       second peak over the top.
    """
    import numpy as np
    import torch

    from swingscribe.stages import transcribe

    print("\n== can CREPE's activation hold a second peak? ==")
    bands = ((60, 250), (250, 1300), (1300, 2500))
    counts = {(band, theta): 0 for band in bands for theta in (0.1, 0.25, 0.5)}
    voiced = 0
    for path in sorted(out.glob("*.npz")):
        with np.load(path) as data:
            probs = data["probs"]
        for frame in probs[probs.max(axis=1) >= 0.5]:
            voiced += 1
            top, other, ratio = second_peak(frame)
            if other is None:
                continue
            cents = abs(other - top) * 20
            for band in bands:
                if band[0] <= cents < band[1]:
                    for theta in (0.1, 0.25, 0.5):
                        counts[band, theta] += ratio >= theta
    print(f"  {voiced} voiced frames over {len(list(out.glob('*.npz')))} solos:")
    for band in bands:
        print(
            f"    second peak {band[0]}-{band[1]} cents from the top: "
            + ", ".join(
                f">= {theta} of it {counts[band, theta]} ({counts[band, theta] / voiced:.2%})"
                for theta in (0.1, 0.25, 0.5)
            )
        )

    torchcrepe = transcribe._import_torchcrepe()
    rate = transcribe.CREPE_SAMPLE_RATE
    t = np.arange(rate // 2) / rate

    def tone(midi):
        f = 440.0 * 2.0 ** ((midi - 69) / 12.0)
        return sum(0.6**k * np.sin(2 * np.pi * f * (k + 1) * t) for k in range(6))

    def activation(signal):
        audio = torch.from_numpy(signal.astype(np.float32))[None]
        with torch.no_grad():
            return np.concatenate(
                [
                    torchcrepe.infer(frames, model="full", device=device).cpu().numpy()
                    for frames in torchcrepe.preprocess(
                        audio, rate, hop_length=transcribe.CREPE_HOP, device=device
                    )
                ]
            )

    base = 62
    print("  synthetic: D4 plus a second harmonic tone d semitones up at a relative level")
    for d in (1, 2, 3, 7):
        for level in (1.0, 0.7, 0.5):
            act = activation(tone(base) + level * tone(base + d))[10:-10]
            b0, b1 = round(bin_of(base)), round(bin_of(base + d))
            at0 = float(np.median(act[:, b0 - 1 : b0 + 2].max(axis=1)))
            at1 = float(np.median(act[:, b1 - 1 : b1 + 2].max(axis=1)))
            seconds = [second_peak(frame) for frame in act]
            ratio = float(np.median([r if r is not None else 0.0 for _t, _o, r in seconds]))
            top = float(np.median([tb for tb, _o, _r in seconds])) - bin_of(base)
            print(
                f"    d {d}, level {level}: activation at D4 {at0:.3f}, at D4+{d} {at1:.3f}; "
                f"second peak {ratio:.2f} of the top; top at D4{top * 0.2:+.2f} semitones"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--solos", type=int, default=10)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--cache-dir", type=Path, default=Path("benchmark/.swingscribe-cache"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--positive-control",
        action="store_true",
        help="only the second-peak checks, over the activations already in --out",
    )
    args = parser.parse_args()
    if args.positive_control:
        positive_control(args.out, args.device)
        return

    import run_eval

    run_eval.CACHE_DIR = args.cache_dir.resolve()
    runs = json.loads(run_eval.notes_cache(SHIPPED_STEP, 0.0).read_text(encoding="utf-8"))
    rows = neighbour_rows(args.table)
    names = worst_solos(rows, args.solos)
    by_solo = collections.defaultdict(list)
    for row in rows:
        by_solo[row["solo"]].append(row)
    print(f"{len(rows)} horn neighbour rows; the {len(names)} solos with the most:")
    db = sqlite3.connect(args.db)
    summaries, pairs, controls = [], [], []
    for name in names:
        summary, facts, calibration = solo_pass(
            name, by_solo[name], db, runs, args.out, args.device
        )
        summaries.append(summary)
        pairs.extend(facts)
        controls.extend(calibration)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "neighbour-pairs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    with (args.out / "neighbour-controls.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(controls[0]))
        writer.writeheader()
        writer.writerows(controls)
    agg = aggregate(pairs, summaries)
    agg["controls"] = calibrate(controls)
    (args.out / "neighbour-aggregate.json").write_text(
        json.dumps({"aggregate": agg, "solos": summaries}, indent=2, default=_plain),
        encoding="utf-8",
    )
    render(agg)
    render_controls(agg["controls"])
    killed = agg["real_peak"] < agg["pairs"] / 3.0
    print(
        "\nKILL CRITERION: real secondary peak in "
        + share(agg["real_peak"], agg["pairs"])
        + " -- "
        + ("fewer than a third: the error is NOT in the decoder." if killed else "passes.")
    )


if __name__ == "__main__":
    main()
