"""Where the missing 0.145 of WJazzD note F1 goes: one cause per error.

    .venv\\Scripts\\python.exe scripts/error_taxonomy.py --db wjazz/wjazzd.db
    .venv\\Scripts\\python.exe scripts/error_taxonomy.py --db wjazz/wjazzd.db --pin

Runs over the SAME cached transcriptions `scripts/run_eval.py` scores
(`.benchmark-notes-c0.2-d0.0.json`, never regenerated here), lines each
annotated solo up with `score_wjazz.identify_all` exactly as the scorecard
does, lets mir_eval decide the hits, and hands every non-hit to
`swingscribe.taxonomy` for its one class. Then it prints the Pareto —
overall, per instrument family, per WJazzD tempo class — diffs the per-class
counts against the pinned baseline, and writes three files:

1. **The classified table**, one row per error, at `--table`
   (default `.benchmark-taxonomy-table.csv`, gitignored: it is a note list
   derived from commercial recordings). Schema below.
2. **The spot-check sample** at `--spotcheck` (default
   `benchmark/wjazzd/error-taxonomy-spotcheck.csv`, beside the audio, never
   in git): `--spotcheck-n` rows drawn at random with `--seed`, for a
   listener to verify by ear. A `verdict` column is left blank for them.
3. **The aggregate** at `tests/regression/taxonomy-baseline.json` when
   `--pin` is given; otherwise the run is compared against it and exits
   non-zero if any class count moved, following run_eval.py's pattern.
   `--json` writes the same aggregate elsewhere without pinning.

## Evidence

Frame evidence (CREPE periodicity, the energy gate, the smoothed pitch) is
read from the GUI's review cache under `--cache-dir`, which holds the
identical transcription for every batch solo (verified 2026-09-07: 74 of 74
cache hits with note-for-note identical output). Stem evidence (digital
silence, loudness, harmonic energy in the other stems) is read from the
separated stems under the same cache with soundfile and numpy — no CREPE,
no model. Piano-model evidence comes from `oracle-notes/` in that cache,
where `scripts/line_selection.py` left the polyphonic model's full output
for the pianists. Any evidence that is missing skips the rules that need it.

## The table's schema (`.benchmark-taxonomy-table.csv`)

One row per error. Columns, in order:

    solo            run key (path under benchmark/, forward slashes)
    melid           WJazzD solo id the row is scored against
    performer, instrument, family, tempo, tempoclass
                    from solo_info; family = horn | piano | guitar | other
    population      miss | fp | pair
    class, rule     the class and the rule text that fired (taxonomy.RULES)
    ref_index, est_index
                    positions in the solo's reference / estimate lists
    ref_onset       reference onset in OUR timeline (fit applied), seconds
    ref_pitch, ref_duration
                    WJazzD pitch (MIDI) and performed duration (s, rate-scaled)
    ref_loud_rel    WJazzD loud_max minus the solo's median loud_max (dB-ish)
    ref_f0_mod      WJazzD's f0 modulation label (vibrato, slide, bend, ...)
    ref_prev_gap    seconds since the previous reference onset
    ref_repeat      1 if the previous reference note has the same pitch
    ref_step        this reference pitch minus the previous one (semitones)
    est_onset, est_pitch, est_duration, est_confidence
                    our note
    est_loud_rel_db our note's RMS (dB) minus the median of matched notes
                    within 2 s
    dt              est_onset - ref_onset for pairs (s)
    dpitch          est_pitch - ref_pitch for pairs and fragments
    covered_by_pitch, covering_dpitch, covered_by_matched, covered_by_duration
                    misses: the note of ours covering the onset - its pitch,
                    pitch minus the reference pitch, whether mir_eval matched
                    it to some other reference note, and its duration
    covered_by_onset, coverer_remaining
                    that note's onset, and how much of it is left after the
                    missed onset (>= 0.06 s is `absorbed`, less is `squeezed`)
    align_resid, dt_residual
                    pairs: the fit's local residual (median onset offset of the
                    matched notes within 3 s) and dt with it taken out
    inside_ref_pitch, inside_ref_onset, inside_ref_duration
                    fps: the reference note sounding at our onset
    body_dt         attack_transient pairs: the body note's onset minus the
                    reference onset; transient_ref_index links a body_late
                    row back to its pair
    oracle_heard    piano misses: 1/0 if the polyphonic model had the pitch
    stem_rms        chosen-stem RMS under the reference note
    frames, max_periodicity, energetic_frac, live_frac, f0_at_ref_frac,
    run_at_ref_frames, live_f0_median, live_dpitch
                    the frame trace under the reference note (see
                    taxonomy._frame_facts); live = energetic AND voiced
    est_line_median the median pitch of our notes within 2 s (dropped_*)
    under_ref_line  fps: reference line's local median minus our pitch
    cross_stem_ratio
                    fps: max over other stems of harmonic energy at our
                    pitch, relative to the chosen stem
    ref_gap_s       fps: the reference inter-onset gap our onset falls in

Blank means the evidence was not available or the column does not apply.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swingscribe import taxonomy  # noqa: E402

BASELINE = Path("tests/regression/taxonomy-baseline.json")
TABLE = Path(".benchmark-taxonomy-table.csv")
SPOTCHECK = Path("benchmark/wjazzd/error-taxonomy-spotcheck.csv")
CACHE_DIR = Path("benchmark/.swingscribe-cache")
# The stems a horn's bleed can come from, per separator. Drums are never
# pitched enough to count.
OTHER_STEMS = {
    "htdemucs": ("vocals", "bass"),
    "htdemucs_ft": ("vocals", "bass"),
    "htdemucs_6s": ("vocals", "bass", "guitar", "piano"),
    "bsroformer_sw": ("vocals", "bass", "guitar", "piano"),
}
HARMONICS = 4
HARMONIC_BAND = 0.03  # ±3% of each harmonic ≈ ±50 cents
COLUMNS = [
    "solo",
    "melid",
    "performer",
    "instrument",
    "family",
    "tempo",
    "tempoclass",
    "population",
    "class",
    "rule",
    "ref_index",
    "est_index",
    "ref_onset",
    "ref_pitch",
    "ref_duration",
    "ref_loud_rel",
    "ref_f0_mod",
    "ref_prev_gap",
    "ref_repeat",
    "ref_step",
    "est_onset",
    "est_pitch",
    "est_duration",
    "est_confidence",
    "est_loud_rel_db",
    "dt",
    "dpitch",
    "align_resid",
    "dt_residual",
    "covered_by_pitch",
    "covering_dpitch",
    "covered_by_matched",
    "covered_by_duration",
    "covered_by_onset",
    "coverer_remaining",
    "inside_ref_pitch",
    "inside_ref_onset",
    "inside_ref_duration",
    "body_dt",
    "transient_ref_index",
    "oracle_heard",
    "stem_rms",
    "frames",
    "max_periodicity",
    "energetic_frac",
    "live_frac",
    "f0_at_ref_frac",
    "run_at_ref_frames",
    "live_f0_median",
    "live_dpitch",
    "est_line_median",
    "under_ref_line",
    "cross_stem_ratio",
    "ref_gap_s",
]


# ── evidence from the caches ──────────────────────────────────────────────


class TrackEvidence(taxonomy.Evidence):
    """The review trace, the stems and the piano model's notes for one solo."""

    def __init__(self, diagnostics, chosen, others, rate, lo, oracle):
        self.diagnostics = diagnostics
        self.chosen = chosen  # mono float32 over [lo, hi]
        self.others = others  # name -> mono
        self.rate = rate
        self.lo = lo
        self.oracle = oracle  # sorted (onset, pitch) or None

    def frames(self, t0, t1):
        d = self.diagnostics
        if d is None:
            return None
        hop, start = d["hop_s"], d["start"]
        a = max(0, int(round((t0 - start) / hop)))
        b = min(d["frames"], int(round((t1 - start) / hop)) + 1)
        if b <= a:
            return None
        return taxonomy.FrameWindow(
            hop_s=hop,
            periodicity=[p if p is not None else 0.0 for p in d["periodicity"][a:b]],
            energy_ok=[bool(e) for e in d["energy_ok"][a:b]],
            pitch=list(d["pitch"][a:b]),
            f0=list(d["f0_midi"][a:b]),
        )

    def _slice(self, signal, t0, t1):
        a = max(0, int((t0 - self.lo) * self.rate))
        b = min(len(signal), int((t1 - self.lo) * self.rate))
        return signal[a:b] if b > a else None

    def stem_rms(self, t0, t1):
        import numpy as np

        if self.chosen is None:
            return None
        seg = self._slice(self.chosen, t0, t1)
        return None if seg is None else float(np.sqrt(np.mean(seg**2)))

    def loudness_db(self, t0, t1):
        rms = self.stem_rms(t0, t1)
        return None if rms is None else 20.0 * math.log10(rms + 1e-9)

    def cross_stem_ratio(self, t0, t1, pitch):
        if self.chosen is None or not self.others:
            return None
        own = self._harmonic_energy(self.chosen, t0, t1, pitch)
        if own is None:
            return None
        best = 0.0
        for signal in self.others.values():
            other = self._harmonic_energy(signal, t0, t1, pitch)
            if other is not None:
                best = max(best, other)
        return best / (own + 1e-12)

    def _harmonic_energy(self, signal, t0, t1, pitch):
        import numpy as np

        seg = self._slice(signal, t0, min(t1, t0 + 0.3))
        if seg is None or len(seg) < 64:
            return None
        window = seg * np.hanning(len(seg))
        spectrum = np.abs(np.fft.rfft(window)) ** 2
        freqs = np.fft.rfftfreq(len(seg), 1.0 / self.rate)
        f0 = 440.0 * 2.0 ** ((pitch - 69) / 12.0)
        total = 0.0
        for k in range(1, HARMONICS + 1):
            band = (freqs >= k * f0 * (1 - HARMONIC_BAND)) & (freqs <= k * f0 * (1 + HARMONIC_BAND))
            total += float(spectrum[band].sum())
        return total

    def oracle_has(self, t, pitch):
        if self.oracle is None:
            return None
        return any(
            p == pitch and abs(on - t) <= taxonomy.ORACLE_TOLERANCE_S for on, p in self.oracle
        )


def load_evidence(name, run, sidecar, lo, hi, cache_dir, log=print):
    """Everything the classifier may ask about this solo, or as much of it
    as the caches hold."""
    import run_eval

    from swingscribe.gui import library, review

    base = run_eval.eval_config()
    settings = run_eval.transcribe_settings(sidecar, 0.2, 0.0)
    config = base.model_copy(
        update={
            "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
            "transcribe": settings,
        }
    )
    document = library.ingested_document(run_eval.BENCH / name, config)
    diagnostics = None
    try:
        cfg = review.span_config(
            config, settings.stem, settings.region[0], settings.region[1], settings.ensemble
        )
        # Read the stored payload by its key directly rather than through
        # `cached_review`, whose contract is the GUI's ("is this review
        # complete enough to SHOW?") and can decline a payload that is still
        # perfectly good frame evidence — a pianist's review from before the
        # candidate pool existed, for one. The notes are verified below either
        # way, so a payload from a different transcription is never used.
        key = review.review_key(document, cfg, sidecar["model"])
        payload = review._cache(cfg).get_json(key)
        if payload is not None:
            ours = [(round(n["onset"], 3), n["pitch"]) for n in run["notes"]]
            theirs = [(n["onset"], n["pitch"]) for n in payload["notes"]]
            if ours == theirs:
                diagnostics = payload["diagnostics"]
            else:
                log(f"  {name}: review cache holds a DIFFERENT transcription; no frame evidence")
    except Exception as error:  # noqa: BLE001 - evidence is optional
        log(f"  {name}: no review ({error})")

    chosen = others = None
    rate = 0
    stems = library.available_stems(document, config, sidecar["model"])
    stem_path = library.resolve_stem(document, config, sidecar["model"], settings.stem)
    if stem_path:
        chosen, rate = _read(stem_path, lo, hi)
        others = {}
        for other in OTHER_STEMS.get(sidecar["model"], ()):
            if other in stems and other not in settings.stem.split("+"):
                others[other], _ = _read(stems[other], lo, hi)
    else:
        log(f"  {name}: no {settings.stem!r} stem on disk; no stem evidence")

    oracle = None
    oracle_path = cache_dir / "oracle-notes" / (Path(name).stem + ".oracle.json")
    if oracle_path.is_file():
        notes = json.loads(oracle_path.read_text(encoding="utf-8"))["notes"]
        oracle = sorted((float(n["onset"]), int(n["pitch"])) for n in notes)
    return TrackEvidence(diagnostics, chosen, others, rate, lo, oracle)


def _read(path, lo, hi):
    import soundfile

    info = soundfile.info(str(path))
    start = max(0, int(lo * info.samplerate))
    stop = min(info.frames, int(hi * info.samplerate))
    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True, start=start, stop=stop)
    return data.mean(axis=1), rate


# ── the solos ─────────────────────────────────────────────────────────────


def reference_notes(db, solo):
    """WJazzD's notes for this solo placed on our clock, with the columns
    the table reports. Order must be the one `fit_affine` saw."""
    rows = db.execute(
        "select onset, pitch, duration, loud_max, f0_mod from melody where melid=?",
        (solo["melid"],),
    ).fetchall()
    if [r[0] for r in rows] != [float(t) for t in solo["ref_on"]]:
        raise RuntimeError(f"melid {solo['melid']}: reference order differs from the fit's")
    louds = [r[3] for r in rows if r[3] is not None]
    median_loud = statistics.median(louds) if louds else 0.0
    out = []
    previous = None
    for onset, pitch, duration, loud, mod in rows:
        placed = float(onset) * solo["rate"] + solo["offset"]
        out.append(
            {
                "onset": placed,
                "duration": float(duration or 0.0) * solo["rate"],
                "pitch": int(pitch),
                "loud_rel": None if loud is None else round(float(loud) - median_loud, 2),
                "f0_mod": mod or "",
                "prev_gap": None if previous is None else round(placed - previous["onset"], 3),
                "repeat": int(previous is not None and previous["pitch"] == int(pitch)),
                "step": None if previous is None else int(pitch) - previous["pitch"],
            }
        )
        previous = out[-1]
    return out


def estimate_notes(run, lo, hi):
    notes = sorted(run["notes"], key=lambda n: n["onset"])
    return [
        {
            "onset": float(n["onset"]),
            "duration": float(n["duration"]),
            "pitch": int(n["pitch"]),
            "confidence": float(n.get("confidence", 0.0)),
        }
        for n in notes
        if lo <= n["onset"] <= hi
    ]


def solo_info(db, melid):
    row = db.execute(
        "select performer, instrument, avgtempo, tempoclass from solo_info where melid=?",
        (melid,),
    ).fetchone()
    return {
        "performer": row[0],
        "instrument": row[1],
        "tempo": row[2],
        "tempoclass": row[3] or "",
    }


def discover(db, runs, log=print):
    """(name, run, sidecar, solo) for every identified solo, as run_eval
    would score it."""
    import numpy as np
    import run_eval
    from score_wjazz import identify_all

    out = []
    for sidecar_path in sorted(run_eval.BENCH.rglob("*.swingscribe.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        name = run_eval.sidecar_name(sidecar_path, sidecar)
        if name not in runs or not (run_eval.BENCH / name).is_file():
            continue
        run = runs[name]
        onsets = np.array([n["onset"] for n in run["notes"]])
        pitches = np.array([int(n["pitch"]) for n in run["notes"]])
        order = np.argsort(onsets)
        found, why = identify_all(db, name, onsets[order], pitches[order], run["region"])
        if not found:
            log(f"  {name}: skipped - {why}")
            continue
        for solo in found:
            if sidecar.get("melid") not in (None, solo["melid"]):
                log(
                    f"  {name}: sidecar names melid {sidecar['melid']} but the fit found "
                    f"{solo['melid']} ({solo['performer']})"
                )
            out.append((name, run, sidecar, solo))
    return out


def classify_all(db, runs, cache_dir, with_audio=True, limit=None, log=print):
    solos = discover(db, runs, log)
    if limit:
        solos = solos[:limit]
    real = Path("tests/regression/real-audio-baselines.json")
    pinned_f1 = json.loads(real.read_text(encoding="utf-8")) if real.is_file() else {}
    disagreements = []
    results = []
    for name, run, sidecar, solo in solos:
        started = time.time()
        reference = reference_notes(db, solo)
        lo, hi = reference[0]["onset"] - 0.25, reference[-1]["onset"] + 0.25
        estimate = estimate_notes(run, lo, hi)
        info = solo_info(db, solo["melid"])
        family = taxonomy.family_of(info["instrument"])
        if with_audio:
            evidence = load_evidence(name, run, sidecar, lo - 0.5, hi + 0.5, cache_dir, log)
        else:
            evidence = taxonomy.Evidence()
        errors = taxonomy.classify_solo(reference, estimate, evidence, family)
        rows = table_rows(name, solo, info, family, reference, estimate, errors, evidence)
        results.append(
            {
                "name": name,
                "melid": solo["melid"],
                "info": info,
                "family": family,
                "fit": {
                    "offset": round(solo["offset"], 3),
                    "rate": round(solo["rate"], 5),
                    "match_rate": round(solo["match_rate"], 3),
                },
                "errors": errors,
                "rows": rows,
            }
        )
        counts = taxonomy.class_counts(errors.rows)
        top = ", ".join(f"{c} {n}" for c, n in sorted(counts.items(), key=lambda kv: -kv[1])[:4])
        # The control that this matching IS the scorecard's: the F1 read off
        # mir_eval's hits here must equal the one run_eval pinned.
        pinned = pinned_f1.get(f"wjazz/{Path(name).stem}/note_f1")
        agreement = "" if pinned is None else f", pinned {pinned:.4f}"
        if pinned is not None and abs(pinned - errors.note_f1) > 0.002:
            agreement += " DISAGREES"
            disagreements.append(name)
        log(
            f"  {name}: F1 {errors.note_f1:.4f}{agreement} ({family}), {len(errors.rows)} errors "
            f"[{top}] in {time.time() - started:.0f}s"
        )
    if disagreements:
        log(f"  WARNING: {len(disagreements)} solo(s) disagree with the pinned note F1")
    return results


def table_rows(name, solo, info, family, reference, estimate, errors, evidence):
    """The classified table's rows for one solo."""
    matched_est = {j for _, j in errors.matched}
    loud = {}
    if evidence.chosen is not None if isinstance(evidence, TrackEvidence) else False:
        for j, note in enumerate(estimate):
            t0, t1 = taxonomy._est_window(note)
            loud[j] = evidence.loudness_db(t0, t1)

    def loud_rel(j):
        if j not in loud or loud[j] is None:
            return None
        t = estimate[j]["onset"]
        near = [
            loud[k]
            for k in matched_est
            if k in loud and loud[k] is not None and abs(estimate[k]["onset"] - t) <= 2.0
        ]
        return None if len(near) < 3 else round(loud[j] - statistics.median(near), 1)

    out = []
    for row in errors.rows:
        ref = reference[row.ref_index] if row.ref_index is not None else None
        est = estimate[row.est_index] if row.est_index is not None else None
        e = row.evidence
        record = {
            "solo": name,
            "melid": solo["melid"],
            "performer": info["performer"],
            "instrument": info["instrument"],
            "family": family,
            "tempo": info["tempo"],
            "tempoclass": info["tempoclass"],
            "population": row.population,
            "class": row.cls,
            "rule": row.rule,
            "ref_index": row.ref_index,
            "est_index": row.est_index,
            "ref_onset": None if ref is None else round(ref["onset"], 3),
            "ref_pitch": None if ref is None else ref["pitch"],
            "ref_duration": None if ref is None else round(ref["duration"], 3),
            "ref_loud_rel": None if ref is None else ref["loud_rel"],
            "ref_f0_mod": None if ref is None else ref["f0_mod"],
            "ref_prev_gap": None if ref is None else ref["prev_gap"],
            "ref_repeat": None if ref is None else ref["repeat"],
            "ref_step": None if ref is None else ref["step"],
            "est_onset": None if est is None else round(est["onset"], 3),
            "est_pitch": None if est is None else est["pitch"],
            "est_duration": None if est is None else round(est["duration"], 3),
            "est_confidence": None if est is None else round(est["confidence"], 3),
            "est_loud_rel_db": None if est is None else loud_rel(row.est_index),
        }
        for column in COLUMNS:
            if column not in record:
                value = e.get(column)
                if isinstance(value, bool):
                    value = int(value)
                if isinstance(value, float):
                    value = round(value, 4)
                record[column] = value
        out.append(record)
    return out


# ── aggregation, printing, pinning ────────────────────────────────────────


def timing_residual_of(results):
    """Of the timing pairs, how many the alignment's own local residual
    explains: dt inside the tolerance once `align_resid` is taken out."""
    timing = [
        row
        for r in results
        for row in r["errors"].rows
        if row.cls in ("timing_late", "timing_early")
    ]
    explained = sum(
        1
        for row in timing
        if abs(row.evidence.get("dt_residual", 1.0)) <= taxonomy.ONSET_TOLERANCE_S
    )
    return {"pairs": len(timing), "explained_by_residual": explained}


def aggregate(results, resamples=1000, seed=0):
    def counts_of(subset):
        merged = {}
        for r in subset:
            for cls, n in taxonomy.class_counts(r["errors"].rows).items():
                merged[cls] = merged.get(cls, 0) + n
        return dict(sorted(merged.items(), key=lambda kv: (-kv[1], kv[0])))

    def populations_of(subset):
        pops = {"miss": 0, "fp": 0, "pair": 0}
        for r in subset:
            for row in r["errors"].rows:
                pops[row.population] += 1
        return pops

    def deficit_of(subset):
        shares = {}
        for r in subset:
            for cls, share in taxonomy.f1_deficit(r["errors"]).items():
                shares[cls] = shares.get(cls, 0.0) + share / len(subset)
        return dict(sorted(((c, round(s, 5)) for c, s in shares.items()), key=lambda kv: -kv[1]))

    def block(subset):
        return {
            "n_solos": len(subset),
            "n_reference": sum(r["errors"].n_reference for r in subset),
            "n_estimate": sum(r["errors"].n_estimate for r in subset),
            "n_matched": sum(len(r["errors"].matched) for r in subset),
            "n_errors": sum(len(r["errors"].rows) for r in subset),
            "mean_note_f1": round(statistics.fmean(r["errors"].note_f1 for r in subset), 4),
            "populations": populations_of(subset),
            "counts": counts_of(subset),
            "f1_deficit": deficit_of(subset),
        }

    families = sorted({r["family"] for r in results})
    tempos = sorted({r["info"]["tempoclass"] for r in results})
    per_solo = [taxonomy.class_counts(r["errors"].rows) for r in results]
    out = {
        "overall": block(results),
        "family": {f: block([r for r in results if r["family"] == f]) for f in families},
        "tempo": {t: block([r for r in results if r["info"]["tempoclass"] == t]) for t in tempos},
        "noise": {
            cls: {k: round(v, 3) for k, v in sd.items()}
            for cls, sd in taxonomy.bootstrap_noise(per_solo, resamples, seed).items()
        },
        "pairs_alternative_differ": sum(r["errors"].pairs_alternative_differ for r in results),
        "timing_residual": timing_residual_of(results),
        "solos": {
            r["name"]: {
                "melid": r["melid"],
                "family": r["family"],
                "tempoclass": r["info"]["tempoclass"],
                "note_f1": round(r["errors"].note_f1, 4),
                "n_reference": r["errors"].n_reference,
                "n_estimate": r["errors"].n_estimate,
                "fit": r["fit"],
                "counts": taxonomy.class_counts(r["errors"].rows),
            }
            for r in results
        },
    }
    for family in families:
        subset = [taxonomy.class_counts(r["errors"].rows) for r in results if r["family"] == family]
        if len(subset) >= 4:
            out["family"][family]["noise"] = {
                cls: {k: round(v, 3) for k, v in sd.items()}
                for cls, sd in taxonomy.bootstrap_noise(subset, resamples, seed).items()
            }
    return out


def render(agg):
    def pareto(title, block, noise=None):
        total = block["n_errors"] or 1
        print(f"\n== {title}: {block['n_solos']} solos, {block['n_errors']} errors, ", end="")
        print(
            f"mean note F1 {block['mean_note_f1']:.4f}; "
            f"populations miss {block['populations']['miss']} / fp {block['populations']['fp']} "
            f"/ pair {block['populations']['pair']} =="
        )
        print(f"  {'class':<20s} {'n':>6s} {'share':>7s} {'cum':>6s} {'F1 cost':>8s} {'sd':>6s}")
        cum = 0.0
        for cls, n in block["counts"].items():
            cum += n / total
            cost = block["f1_deficit"].get(cls, 0.0)
            sd = f"{noise[cls]['count_sd']:6.1f}" if noise and cls in noise else "      "
            print(f"  {cls:<20s} {n:6d} {n / total:7.1%} {cum:6.1%} {cost:8.4f} {sd}")
        total_cost = sum(block["f1_deficit"].values())
        print(f"  {'sum of F1 costs':<20s} {'':6s} {'':7s} {'':6s} {total_cost:8.4f}")

    pareto("ALL", agg["overall"], agg["noise"])
    for family, block in agg["family"].items():
        pareto(f"family {family}", block, block.get("noise"))
    for tempoclass, block in agg["tempo"].items():
        pareto(f"tempo {tempoclass}", block)
    print(
        f"\nPairing: {agg['pairs_alternative_differ']} pairs would differ without the "
        f"same-pitch preference (of {agg['overall']['populations']['pair']})."
    )
    unclassified = agg["overall"]["counts"].get("unclassified", 0)
    print(f"Unclassified: {unclassified} of {agg['overall']['n_errors']} errors.")
    tr = agg.get("timing_residual")
    if tr and tr["pairs"]:
        print(
            f"Timing: {tr['explained_by_residual']} of {tr['pairs']} timing pairs sit inside the "
            f"tolerance once the fit's local residual is taken out (alignment, not placement)."
        )


def flatten(agg):
    flat = {}
    for cls, n in agg["overall"]["counts"].items():
        flat[f"count/{cls}"] = n
    for family, block in agg["family"].items():
        for cls, n in block["counts"].items():
            flat[f"family/{family}/{cls}"] = n
    for pop, n in agg["overall"]["populations"].items():
        flat[f"population/{pop}"] = n
    flat["n_solos"] = agg["overall"]["n_solos"]
    flat["n_errors"] = agg["overall"]["n_errors"]
    return flat


def paired_by_family(pinned_solos, current_solos):
    """`taxonomy.paired_delta_noise` over all solos and per family, from the
    per-solo counts both the pin and this run carry; {} when either lacks them."""
    if not pinned_solos or not current_solos:
        return {}
    before = {name: s["counts"] for name, s in pinned_solos.items()}
    after = {name: s["counts"] for name, s in current_solos.items()}
    out = {"all": taxonomy.paired_delta_noise(before, after)}
    families = {s.get("family") for s in current_solos.values()} - {None}
    for family in families:
        names = {n for n, s in current_solos.items() if s.get("family") == family}
        out[family] = taxonomy.paired_delta_noise(
            {n: c for n, c in before.items() if n in names},
            {n: c for n, c in after.items() if n in names},
        )
    return out


def compare(agg):
    """Diff the per-class counts against the pin. Returns an exit code.

    Every moved count is printed. Classification is deterministic, so any
    movement after a transcriber change is real; the ±sd column is the
    bootstrap spread of that class over resamples of the solos, the scale a
    change must beat before it says something about the transcriber rather
    than about which solos are in the set. Movers beyond 2 sd are marked.
    """
    if not BASELINE.is_file():
        print(f"\nNo taxonomy baseline pinned yet. Run with --pin to create {BASELINE}.")
        return 0
    pinned = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = flatten(agg)
    noise = pinned.get("noise", agg["noise"])
    moved = [
        (key, pinned["flat"].get(key, 0), value)
        for key, value in sorted(current.items())
        if pinned["flat"].get(key, 0) != value
    ]
    vanished = sorted(set(pinned["flat"]) - set(current))
    if not moved and not vanished:
        print(f"\n== Taxonomy baseline: all {len(current)} counts unchanged ==")
        return 0
    print("\n== Taxonomy baseline: CHANGED ==")
    # The paired reading: per-solo deltas over the solos both runs hold.
    # `count_sd` says how big a class would be on another set of solos; the
    # paired se says whether THIS change moved it (docs/error-taxonomy-review.md).
    paired = paired_by_family(pinned.get("solos"), agg.get("solos"))
    for key, was, now in moved:
        cls = key.rsplit("/", 1)[-1]
        sd = noise.get(cls, {}).get("count_sd", 0.0)
        flag = "  beyond 2 sd" if abs(now - was) > 2 * sd else ""
        scope = (
            "all"
            if key.startswith("count/")
            else key.split("/")[1]
            if key.startswith("family/")
            else None
        )
        stats = paired.get(scope, {}).get(cls) if scope else None
        if stats:
            verdict = "beyond 2 se" if abs(stats["delta"]) > 2 * stats["se"] else "inside noise"
            up, down, n = stats["up"], stats["down"], stats["n_solos"]
            flag += f"  paired: {verdict} (se {stats['se']:.1f}, up {up} / down {down} of {n})"
        print(f"  {key:<40s} {was:6d} -> {now:6d}  ({now - was:+d}, sd {sd:.1f}){flag}")
    for key in vanished:
        print(f"  {key:<40s} {pinned['flat'][key]:6d} -> gone")
    print("\nIf this is intended, say so explicitly and re-pin with --pin (CLAUDE.md).")
    return 1


def write_table(results, path):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for r in results:
            for record in r["rows"]:
                writer.writerow({k: ("" if v is None else v) for k, v in record.items()})


def write_spotcheck(results, path, n, seed):
    """`n` errors drawn at random, not chosen, for a listener to verify."""
    rows = [record for r in results for record in r["rows"]]
    sample = random.Random(seed).sample(rows, min(n, len(rows)))
    sample.sort(key=lambda r: (r["solo"], r["ref_onset"] or r["est_onset"]))
    columns = [
        "solo",
        "performer",
        "time",
        "population",
        "class",
        "rule",
        "ref_pitch",
        "est_pitch",
        "dt",
        "ref_duration",
        "est_duration",
        "note",
        "verdict",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for r in sample:
            t = r["ref_onset"] if r["ref_onset"] is not None else r["est_onset"]
            evidence = {
                k: r[k]
                for k in (
                    "covered_by_pitch",
                    "coverer_remaining",
                    "align_resid",
                    "inside_ref_pitch",
                    "max_periodicity",
                    "energetic_frac",
                    "run_at_ref_frames",
                    "under_ref_line",
                    "cross_stem_ratio",
                    "ref_gap_s",
                    "oracle_heard",
                )
                if r.get(k) not in (None, "")
            }
            writer.writerow(
                {
                    "solo": r["solo"],
                    "performer": r["performer"],
                    "time": f"{int(t // 60)}:{t % 60:06.3f}",
                    "population": r["population"],
                    "class": r["class"],
                    "rule": r["rule"],
                    "ref_pitch": r["ref_pitch"] if r["ref_pitch"] is not None else "",
                    "est_pitch": r["est_pitch"] if r["est_pitch"] is not None else "",
                    "dt": r["dt"] if r["dt"] is not None else "",
                    "ref_duration": r["ref_duration"] if r["ref_duration"] is not None else "",
                    "est_duration": r["est_duration"] if r["est_duration"] is not None else "",
                    "note": "; ".join(f"{k}={v}" for k, v in evidence.items()),
                    "verdict": "",
                }
            )


def main():
    global CACHE_DIR
    parser = argparse.ArgumentParser(description="Classify every WJazzD transcription error.")
    parser.add_argument("--db", type=Path, required=True, help="wjazz/wjazzd.db")
    parser.add_argument("--notes", type=Path, default=None, help="run_eval's notes cache")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--spotcheck", type=Path, default=SPOTCHECK)
    parser.add_argument("--spotcheck-n", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--no-audio", action="store_true", help="skip stem and frame evidence")
    parser.add_argument("--limit", type=int, default=None, help="first N solos only (dev)")
    parser.add_argument("--json", type=Path, default=None, help="also write the aggregate here")
    parser.add_argument("--pin", action="store_true", help="rewrite the baseline from this run")
    args = parser.parse_args()

    import run_eval

    CACHE_DIR = args.cache_dir.resolve()
    run_eval.CACHE_DIR = CACHE_DIR
    notes = args.notes or run_eval.notes_cache(0.2, 0.0)
    runs = json.loads(notes.read_text(encoding="utf-8"))
    print(f"== Classifying {notes} against {args.db}, evidence from {CACHE_DIR} ==")
    db = sqlite3.connect(args.db)
    results = classify_all(db, runs, CACHE_DIR, not args.no_audio, args.limit)
    if not results:
        print("nothing to classify")
        return

    agg = aggregate(results, args.resamples, args.seed)
    render(agg)
    write_table(results, args.table)
    print(f"\nWrote {sum(len(r['rows']) for r in results)} rows to {args.table}")
    write_spotcheck(results, args.spotcheck, args.spotcheck_n, args.seed)
    print(f"Wrote a {args.spotcheck_n}-row spot-check sample to {args.spotcheck}")

    if args.json:
        args.json.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    if args.pin or args.limit:
        if args.limit:
            print("\n--limit set: not comparing against the baseline")
            return
        payload = {
            "overall": agg["overall"],
            "family": {
                f: {k: v for k, v in b.items() if k != "noise"} for f, b in agg["family"].items()
            },
            "tempo": agg["tempo"],
            "noise": agg["noise"],
            "pairs_alternative_differ": agg["pairs_alternative_differ"],
            "timing_residual": agg.get("timing_residual"),
            # Per-solo CLASS COUNTS, not notes: aggregates, so they can ship.
            # They are what the paired test in `compare` reads.
            "solos": {
                name: {"family": s["family"], "note_f1": s["note_f1"], "counts": s["counts"]}
                for name, s in agg["solos"].items()
            },
            "flat": flatten(agg),
        }
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nPinned {len(payload['flat'])} counts to {BASELINE}.")
        return
    raise SystemExit(compare(agg))


if __name__ == "__main__":
    main()
