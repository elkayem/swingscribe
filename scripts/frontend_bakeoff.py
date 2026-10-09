"""Roadmap A2, step 1: a pretrained note-level model against CREPE, on our stems.

    .venv\\Scripts\\python.exe scripts/frontend_bakeoff.py manifest --out DIR
    wsl -- bash -lc '~/bakeoff/.venv/bin/python scripts/bakeoff_basic_pitch_wsl.py infer ...'
    .venv\\Scripts\\python.exe scripts/frontend_bakeoff.py score --db wjazz/wjazzd.db --out DIR

The transcriber's largest remaining errors are the short note (under an
eighth: 27% of the Omnibook's notes and 54% of its outright misses) and the
semitone `neighbour`, and every CREPE gate that could reach them has been
swept and measured out (CLAUDE.md, docs/error-taxonomy.md). The question this
answers is whether a pretrained NOTE-LEVEL model -- Basic Pitch (Spotify,
Apache-2.0) -- hears those notes better on the SAME separated stems. If it
does not, fine-tuning one (A2 step 2) starts from nothing; if it does, the
bake-off says which way of using it is worth building.

## Three steps, two machines

Basic Pitch needs librosa, resampy and numba, which this project may never
import on Windows (Smart App Control, CLAUDE.md). So the model runs in WSL,
in a venv outside the repo, and this script does everything on either side
of it:

1. `manifest` resolves the exact stem wav and region every harness run
   transcribed -- `run_eval.transcribe_all`'s own resolution (the sidecar's
   model and stem, `library.ingested_document` + `library.resolve_stem`, the
   batch cache `benchmark/.swingscribe-cache`) -- and writes
   `{key: {wav, region, ...}}` for the WSL side. Nothing is transcribed.
2. `bakeoff_basic_pitch_wsl.py` (WSL) runs the model once per region, keeps
   its frame and onset posteriorgrams, and decodes them into notes under
   each named parameter set (cheap: no second inference per setting).
3. `score` builds the variants from those notes and CREPE's cached runs and
   scores each with the harness's own code, beside a CREPE card scored by the
   same code in the same run, so the comparison never leans on a pin.

## What is held fixed, and why

- **The fit.** `score_wjazz.identify_all` finds each annotated solo inside a
  track from OUR notes. A polyphonic variant would move that fit (or fail
  it) and the comparison would then measure the fit, not the front end. So
  every variant is scored under CREPE's fit -- same solos, same offset and
  rate -- with `score_wjazz.score`, which is what `run_eval` calls.
- **The stems.** The same wav the CREPE run read, byte for byte.
- **The default take.** A pianist's pinned default is the oracle line
  (`piano_line = "oracle"`); the second take is not scored here.

Every change is reported with `swingscribe.evaluation.paired_change`: the
same tracks before and after, a 95% bootstrap interval resampled by
recording, and a sign test over recordings.

## Declared tuning subset

Parameters (Basic Pitch's thresholds and minimum length, the hybrid's gates)
are chosen on the WJazzD recordings whose SHA-1 of the recording name is 0
mod 3 (`is_tuning`), about a third of them. Everything is also reported on
the other two thirds, and the hand scores, the Omnibook and the PDF pages
are never looked at while tuning.

`score --check` holds CREPE's card here to the pinned per-track numbers (221
of them matched to 0.0000 on 2026-09-30) -- the control that this IS the
harness's scoring; `--notation` also builds and scores the page
(`run_eval.notation_scores`). Results and the verdict:
docs/frontend-bakeoff.md.

Nothing this writes may enter the repo: the notes are derived from
commercial recordings. Everything lands under `--out` (a scratch folder).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
sys.path.insert(0, str(REPO / "scripts"))

import run_eval  # noqa: E402

BATCH_CACHE = REPO / "benchmark" / ".swingscribe-cache"
NOTES_CACHE = Path(".benchmark-notes-c0.2-d0.0.json")

# Reference-duration buckets for WJazzD recall, seconds (the task's, and
# the taxonomy's 60 ms `too_short` boundary is the first edge).
DURATION_EDGES = (0.060, 0.100, 0.150, 0.250)
DURATION_LABELS = ("<60ms", "60-100", "100-150", "150-250", ">250")

# The book's notated values, in quarter notes (docs/error-taxonomy.md 10.5).
# "Under an eighth" is the first three.
VALUE_BANDS = (
    (1 / 6 + 1e-6, "16th-triplet or shorter"),
    (0.25 + 1e-6, "sixteenth"),
    (1 / 3 + 1e-6, "triplet eighth"),
    (0.5 + 1e-6, "eighth"),
    (1.0 + 1e-6, "up to a quarter"),
    (float("inf"), "longer"),
)
SUB_EIGHTH = {"16th-triplet or shorter", "sixteenth", "triplet eighth"}


def is_tuning(recording: str) -> bool:
    """The declared tuning subset: a third of the WJazzD recordings, fixed by
    name so it cannot drift toward whichever tracks a setting happens to
    flatter."""
    return int(hashlib.sha1(recording.encode("utf-8")).hexdigest(), 16) % 3 == 0


def set_of(key: str) -> str:
    if run_eval.is_omnibook(key):
        return "omnibook"
    if run_eval.is_page(key):
        return "pages"
    return "own"


# ── 1. manifest ──────────────────────────────────────────────────────────────


def live_runs(db_path: Path | None, log=print) -> dict:
    """The default-take runs `run_eval` would score today: a sidecar and its
    audio on disk, a cached run under the current fingerprint, and on the
    dev side of the locked split. Nothing is transcribed; a stale run is
    reported and skipped, never recomputed."""
    runs = json.loads(NOTES_CACHE.read_text(encoding="utf-8"))
    live = {}
    stale = []
    # Through run_eval's walk (library.discover): a linked take's audio is
    # its sidecar's, wherever the copy it was keyed by has gone.
    for name, _sidecar_path, _audio, sidecar in run_eval.bench_takes(lambda _message: None):
        run = runs.get(name)
        if run is None:
            continue
        wanted = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
        if run.get("fingerprint") != wanted:
            stale.append(name)
            continue
        live[name] = {**run, "sidecar": sidecar}
    if stale:
        log(f"  {len(stale)} cached run(s) under an old fingerprint, skipped: {stale}")
    return run_eval.split_runs(live, db_path, test=False, log=log)


def manifest(args) -> None:
    from swingscribe.gui import library

    run_eval.CACHE_DIR = BATCH_CACHE
    runs = live_runs(args.db)
    out = {}
    for key, run in sorted(runs.items()):
        sidecar = run["sidecar"]
        settings = run_eval.transcribe_settings(sidecar, 0.2, 0.0)
        base = run_eval.eval_config()
        config = base.model_copy(
            update={
                "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
                "transcribe": settings,
            }
        )
        document = library.ingested_document(library.audio_for_key(run_eval.BENCH, key), config)
        stem = library.resolve_stem(document, config, sidecar["model"], settings.stem)
        if stem is None:
            print(f"  {key}: no {settings.stem!r} stem for {sidecar['model']} -- skipped")
            continue
        out[key] = {
            "wav": str(Path(stem).resolve()),
            "region": run["region"],
            "model": run["model"],
            "stem": run["stem"],
            "ensemble": run.get("ensemble"),
            "set": set_of(key),
            "piano": bool(settings.uses_piano_oracle),
        }
        print(f"  {key}: {Path(stem).parent.name}/{Path(stem).name} {run['region']}")
    path = args.out / "manifest.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    counts = {}
    for entry in out.values():
        counts[entry["set"]] = counts.get(entry["set"], 0) + 1
    print(f"\n{len(out)} runs -> {path}: {counts}")


# ── 2. the fixed references ─────────────────────────────────────────────────


def wjazz_fits(db_path: Path, runs: dict, out: Path, jobs: int) -> dict:
    """CREPE's fit of every annotated solo, computed once and then held fixed
    for every variant (module docstring). The same `identify_all` `run_eval`
    calls, on the same notes; cached under `out` because it is the slowest
    thing here and cannot change while the CREPE runs do not."""
    path = out / "fits.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    names = sorted(k for k in runs if not run_eval.is_located(k) and runs[k]["notes"])
    tasks = [(k, runs[k]["notes"], runs[k]["region"], str(db_path)) for k in names]
    fits = dict(zip(names, run_eval.parallel_map(_fit_one, tasks, jobs), strict=True))
    path.write_text(json.dumps(fits), encoding="utf-8")
    return fits


def _fit_one(task: tuple) -> list:
    key, notes, region, db_path = task
    import sqlite3

    import numpy as np
    from score_wjazz import identify_all

    db = sqlite3.connect(db_path)
    onsets = np.array([n["onset"] for n in notes])
    pitches = np.array([int(n["pitch"]) for n in notes])
    order = np.argsort(onsets)
    found, _why = identify_all(db, run_eval.track_of(key), onsets[order], pitches[order], region)
    out = []
    for solo in found:
        rows = db.execute(
            "select onset, pitch, duration from melody where melid=?", (solo["melid"],)
        ).fetchall()
        if [r[0] for r in rows] != [float(t) for t in solo["ref_on"]]:
            raise RuntimeError(f"melid {solo['melid']}: reference order differs from the fit's")
        out.append(
            {
                "melid": solo["melid"],
                "performer": solo["performer"],
                "instrument": solo["instrument"],
                "offset": float(solo["offset"]),
                "rate": float(solo["rate"]),
                "ref_on": [float(r[0]) for r in rows],
                "ref_p": [int(r[1]) for r in rows],
                "ref_dur": [float(r[2] or 0.0) for r in rows],
                "solos_in_file": len(found),
            }
        )
    return out


def score_paths(runs: dict) -> dict:
    """Run key -> the notated reference `run_eval.mscz_scores` scores it
    against (score_benchmark.TUNES, derived from the sidecars)."""
    import score_benchmark

    by_audio = {audio: mscz_name for audio, mscz_name, *_ in score_benchmark.TUNES.values()}
    return {
        key: str(run_eval.BENCH / by_audio[run_eval.track_of(key)])
        for key in runs
        if run_eval.track_of(key) in by_audio
    }


# ── 3. the variants ──────────────────────────────────────────────────────────


def bp_notes(events: list, shift: float = 0.0, velocity: bool = False) -> list[dict]:
    """Basic Pitch's [onset, offset, pitch, amplitude] as the harness's note
    dicts. `amplitude` (the mean frame activation, 0-1) is the confidence;
    `velocity` also carries it where a consumer ranks on it (`pick_line`
    ranks within the track, so its scale does not matter there -- and it must
    NOT be present for `fill_gaps`, which would read it as MIDI velocity)."""
    out = []
    for onset, offset, pitch, amp in events:
        note = {
            "onset": float(onset) + shift,
            "duration": max(float(offset) - float(onset), 0.0),
            "pitch": int(pitch),
            "confidence": float(amp),
        }
        if velocity:
            note["velocity"] = float(amp)
        out.append(note)
    return sorted(out, key=lambda n: (n["onset"], -n["pitch"]))


def reduce_line(events: list, how: str, shift: float) -> list[dict]:
    """One note per onset cluster (`line_selection.clusters_of`, 50 ms):
    the highest (skyline) or the loudest."""
    from swingscribe.line_selection import clusters_of

    clusters = clusters_of(bp_notes(events, shift))
    if how == "sky":
        return [max(c, key=lambda n: n["pitch"]) for c in clusters]
    if how == "loud":
        return [max(c, key=lambda n: (n["confidence"], n["pitch"])) for c in clusters]
    raise ValueError(how)


def neighbour_vote(crepe: list[dict], bp: list[dict], min_amp: float) -> list[dict]:
    """CREPE's line with one pitch changed where Basic Pitch struck a note a
    semitone or a tone away within the benchmark's 50 ms and struck NOTHING
    at CREPE's pitch there. Exploratory: it asks whether the model reads the
    PITCH of a note better, the `neighbour` class's question."""
    import bisect

    onsets = [n["onset"] for n in bp]
    out = []
    for note in crepe:
        lo = bisect.bisect_left(onsets, note["onset"] - 0.05)
        hi = bisect.bisect_right(onsets, note["onset"] + 0.05)
        near = bp[lo:hi]
        if any(n["pitch"] == note["pitch"] for n in near):
            out.append(note)
            continue
        votes = [
            n
            for n in near
            if abs(n["pitch"] - note["pitch"]) in (1, 2) and n["confidence"] >= min_amp
        ]
        if votes:
            best = max(votes, key=lambda n: n["confidence"])
            out.append({**note, "pitch": best["pitch"]})
        else:
            out.append(note)
    return out


def build(variant: str, crepe: list[dict], events: list, piano: bool, args) -> list[dict]:
    """The notes a variant scores for one run.

    `raw`, `sky`, `loud`, `pick` replace the default take everywhere,
    pianists included (they are measured by family). `hybrid:<amp>` and
    `nvote:<amp>` change HORNS only -- a pianist keeps the default take, the
    oracle line, because a horn product change must not cost a pianist
    anything and the pianist already has a note-level model.
    """
    shift = args.shift
    name, _, arg = variant.partition(":")
    if name == "crepe":
        return crepe
    if name == "raw":
        return bp_notes(events, shift)
    if name in ("sky", "loud"):
        return reduce_line(events, name, shift)
    if name == "pick":
        from swingscribe.line_selection import pick_line

        return pick_line(bp_notes(events, 0.0, velocity=True), onset_shift=shift)
    if piano:
        return crepe
    if name == "hybrid":
        # hybrid:<min amp>[:<gap s>[:<cover fraction>]] -- fill_gaps' own
        # defaults (60 ms, half a duration) were measured on the piano.
        from swingscribe.corroborate import COVER_FRACTION, GAP_TOLERANCE, fill_gaps

        amp, gap, cover = [*arg.split(":"), None, None][:3]
        merged, _stats = fill_gaps(
            crepe,
            bp_notes(events, 0.0),
            min_confidence=float(amp),
            gap_tolerance=float(gap) if gap else GAP_TOLERANCE,
            cover_fraction=float(cover) if cover else COVER_FRACTION,
            onset_shift=shift,
        )
        return merged
    if name == "nvote":
        return neighbour_vote(crepe, bp_notes(events, shift), float(arg))
    raise ValueError(variant)


# ── 4. scoring, with the harness's own functions ────────────────────────────


def bucket(value: float, edges) -> int:
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


def _wjazz_one(task: tuple) -> dict:
    """`score_wjazz.score` under a FIXED fit, plus what the score hides:
    recall by the reference note's performed duration (mir_eval's hits,
    `taxonomy.match`) and the taxonomy's classes for the paired errors
    (`taxonomy.pair_unmatched` + `classify_pair`, no frame evidence)."""
    key, solos, notes = task
    import numpy as np
    from score_wjazz import score

    from swingscribe import taxonomy

    ordered = sorted(notes, key=lambda n: n["onset"])
    onsets = np.array([n["onset"] for n in ordered])
    out = {}
    for solo in solos:
        s = {**solo, "ref_on": np.array(solo["ref_on"]), "ref_p": np.array(solo["ref_p"])}
        result = score(s, onsets, ordered)
        placed = s["ref_on"] * s["rate"] + s["offset"]
        lo, hi = float(placed[0]) - 0.25, float(placed[-1]) + 0.25
        est = [
            {"onset": n["onset"], "duration": n["duration"], "pitch": int(n["pitch"])}
            for n in ordered
            if lo <= n["onset"] <= hi
        ]
        ref = [
            {"onset": float(t), "duration": d * s["rate"], "pitch": int(p)}
            for t, p, d in zip(placed, solo["ref_p"], solo["ref_dur"], strict=True)
        ]
        matched = taxonomy.match(ref, est)
        hit = {i for i, _ in matched}
        est_hit = {j for _, j in matched}
        buckets_n = [0] * (len(DURATION_EDGES) + 1)
        buckets_hit = [0] * (len(DURATION_EDGES) + 1)
        for i, r in enumerate(ref):
            b = bucket(r["duration"], DURATION_EDGES)
            buckets_n[b] += 1
            buckets_hit[b] += i in hit
        ref_free = [i for i in range(len(ref)) if i not in hit]
        est_free = [j for j in range(len(est)) if j not in est_hit]
        pairs = taxonomy.pair_unmatched(ref, est, ref_free, est_free)
        classes: dict[str, int] = {}
        neighbour_ref = []
        for i, j in pairs:
            cls = taxonomy.classify_pair(ref[i], est[j], est).cls
            classes[cls] = classes.get(cls, 0) + 1
            if cls == "neighbour":
                neighbour_ref.append(i)
        classes["miss"] = len(ref_free) - len(pairs)
        classes["fp"] = len(est_free) - len(pairs)
        # Timing of the hits, for the onset-lead calibration.
        lead = [est[j]["onset"] - ref[i]["onset"] for i, j in matched]
        row = key if solo["solos_in_file"] == 1 else f"{key} [{solo['performer']}]"
        out[row] = {
            "note_f1": result["note_f1"],
            "note_precision": result["note_precision"],
            "note_recall": result["note_recall"],
            "n_ref": len(ref),
            "n_est": len(est),
            "hits": len(matched),
            "bucket_n": buckets_n,
            "bucket_hit": buckets_hit,
            "classes": classes,
            "lead_median": float(np.median(lead)) if lead else None,
            "instrument": solo["instrument"],
            # Which reference notes, so two cards can be put together: the
            # union of two detectors' hits is the recall a perfect selector
            # between them could reach.
            "hit_idx": sorted(hit),
            "neighbour_ref": sorted(neighbour_ref),
            "bucket_of": [bucket(r["duration"], DURATION_EDGES) for r in ref],
        }
        if abs(len(matched) / max(len(ref), 1) - result["note_recall"]) > 1e-9:
            raise RuntimeError(f"{row}: taxonomy.match disagrees with score_wjazz.score")
    return out


def _notated_one(task: tuple) -> dict:
    """Pitch F1 against a notated reference exactly as
    `score_benchmark.score_tune` computes it (`measured_transposition` over
    the whole line), and recall by the book's notated value from the same
    alignment's true matches (`benchmark.anchor_map`) -- the hits the error
    taxonomy's Omnibook block counts."""
    key, score_path, notes = task
    from swingscribe import mscz
    from swingscribe.alignment import measured_transposition
    from swingscribe.benchmark import anchor_map

    score = mscz.parse_any(score_path)
    ref_pitches = score.pitches
    est_pitches = [int(n["pitch"]) for n in notes]
    offset, pitch = measured_transposition(ref_pitches, est_pitches)
    anchored = anchor_map(pitch.pairs, ref_pitches, [p + offset for p in est_pitches])
    bands_n = [0] * len(VALUE_BANDS)
    bands_hit = [0] * len(VALUE_BANDS)
    for i, note in enumerate(score.melody):
        b = next(k for k, (edge, _label) in enumerate(VALUE_BANDS) if note.duration < edge)
        bands_n[b] += 1
        bands_hit[b] += i in anchored
    return {
        key: {
            "pitch_f1": pitch.f1,
            "pitch_precision": pitch.precision,
            "pitch_recall": pitch.recall,
            "n_ref": len(ref_pitches),
            "n_est": len(est_pitches),
            "band_n": bands_n,
            "band_hit": bands_hit,
            "band_of": [
                next(k for k, (edge, _label) in enumerate(VALUE_BANDS) if n.duration < edge)
                for n in score.melody
            ],
            "hit_idx": sorted(anchored),
        }
    }


# Bumped whenever a card's CONTENTS change for the same notes, so an older
# card is never served (1: hit indices and neighbour references added).
CARD_VERSION = 1


def score_variant(name: str, notes_of: dict, fits: dict, scores: dict, args, runs=None) -> dict:
    """A card for one variant, cached under --out/cards. The notes a card was
    built from, CARD_VERSION and which sections were asked for are hashed
    into its file name, so a changed variant is never served a stale card."""
    wanted = {"wjazz_only": args.wjazz_only, "notation": args.notation, "v": CARD_VERSION}
    payload = json.dumps([notes_of, wanted], sort_keys=True).encode("utf-8")
    digest = hashlib.sha1(payload).hexdigest()[:12]
    path = args.out / "cards" / f"{name.replace(':', '_')}-{digest}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    started = time.time()
    w_tasks = [(k, fits[k], notes_of[k]) for k in sorted(notes_of) if fits.get(k)]
    card = {"wjazz": {}, "notated": {}, "notation": {}}
    for part in run_eval.parallel_map(_wjazz_one, w_tasks, args.jobs):
        card["wjazz"].update(part)
    if not args.wjazz_only:
        n_tasks = [(k, scores[k], notes_of[k]) for k in sorted(notes_of) if k in scores]
        for part in run_eval.parallel_map(_notated_one, n_tasks, args.jobs):
            card["notated"].update(part)
    if args.notation and runs is not None:
        # The page: run_eval's own notation scorer (swing, quantize, notate
        # through swingscribe.notation, then score_against_notation), on the
        # variant's notes with the run's stem and region, over the grids the
        # harness cached. Read-only: nothing here writes a harness cache.
        grids = json.loads(run_eval.GRIDS_CACHE.read_text(encoding="utf-8"))
        variant_runs = {
            k: {**runs[k], "notes": notes_of[k]} for k in sorted(notes_of) if k in scores
        }
        card["notation"] = run_eval.notation_scores(variant_runs, grids, args.jobs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card), encoding="utf-8")
    print(f"  scored {name} in {time.time() - started:.0f}s", flush=True)
    return card


# ── 5. the report ────────────────────────────────────────────────────────────


def paired(before: dict, after: dict, field: str, keys: list[str]):
    from swingscribe.evaluation import paired_change

    keys = [k for k in keys if k in before and k in after]
    if not keys:
        return None
    return paired_change(
        [before[k][field] for k in keys],
        [after[k][field] for k in keys],
        [run_eval.track_of(k) for k in keys],
        tolerance=run_eval.TOLERANCE,
    )


def fmt_change(c) -> str:
    if c is None:
        return "-"
    mark = "*" if c.decided else " "
    return f"{c.mean:+.4f} [{c.low:+.4f},{c.high:+.4f}]{mark} {c.up}/{c.down}/{c.level} p={c.p:.3f}"


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else float("nan")


def pooled(section: dict, keys, n_field: str, hit_field: str) -> list[float]:
    keys = [k for k in keys if k in section]
    if not keys:
        return []
    width = len(section[keys[0]][n_field])
    n = [sum(section[k][n_field][b] for k in keys) for b in range(width)]
    h = [sum(section[k][hit_field][b] for k in keys) for b in range(width)]
    return [(hh / nn if nn else float("nan"), nn) for hh, nn in zip(h, n, strict=True)]


def summarise(name: str, card: dict, base: dict, meta: dict) -> dict:
    """Every number the doc reports for one variant, beside CREPE's."""
    w, bw = card["wjazz"], base["wjazz"]
    keys = sorted(bw)
    out = {"variant": name}
    groups = {
        "all": keys,
        "tuning": [k for k in keys if is_tuning(run_eval.track_of(k))],
        "heldout": [k for k in keys if not is_tuning(run_eval.track_of(k))],
        "horn": [k for k in keys if meta[run_eval.track_of(k)] == "horn"],
        "piano": [k for k in keys if meta[run_eval.track_of(k)] == "piano"],
    }
    for group, ks in groups.items():
        ks = [k for k in ks if k in w]
        out[f"wjazz_{group}_n"] = len(ks)
        for field in ("note_f1", "note_precision", "note_recall"):
            out[f"wjazz_{group}_{field}"] = mean(w[k][field] for k in ks)
            out[f"wjazz_{group}_{field}_crepe"] = mean(bw[k][field] for k in ks)
        out[f"wjazz_{group}_f1_change"] = paired(bw, w, "note_f1", ks)
    out["wjazz_buckets"] = pooled(w, keys, "bucket_n", "bucket_hit")
    out["wjazz_buckets_crepe"] = pooled(bw, keys, "bucket_n", "bucket_hit")
    classes: dict[str, int] = {}
    crepe_classes: dict[str, int] = {}
    for k in keys:
        for c, v in w.get(k, {}).get("classes", {}).items():
            classes[c] = classes.get(c, 0) + v
        for c, v in bw[k]["classes"].items():
            crepe_classes[c] = crepe_classes.get(c, 0) + v
    out["wjazz_classes"], out["wjazz_classes_crepe"] = classes, crepe_classes
    leads = [w[k]["lead_median"] for k in keys if k in w and w[k]["lead_median"] is not None]
    out["lead_median_of_medians"] = statistics.median(leads) if leads else None

    n, bn = card["notated"], base["notated"]
    for section in ("own", "omnibook", "pages"):
        ks = sorted(k for k in bn if set_of(k) == section and k in n)
        out[f"{section}_n"] = len(ks)
        for field in ("pitch_f1", "pitch_precision", "pitch_recall"):
            out[f"{section}_{field}"] = mean(n[k][field] for k in ks)
            out[f"{section}_{field}_crepe"] = mean(bn[k][field] for k in ks)
        out[f"{section}_f1_change"] = paired(bn, n, "pitch_f1", ks)
        out[f"{section}_bands"] = pooled(n, ks, "band_n", "band_hit")
        out[f"{section}_bands_crepe"] = pooled(bn, ks, "band_n", "band_hit")
        pianists = [k for k in ks if meta[run_eval.track_of(k)] == "piano"]
        if pianists:
            out[f"{section}_piano_n"] = len(pianists)
            out[f"{section}_piano_precision"] = mean(n[k]["pitch_precision"] for k in pianists)
            out[f"{section}_piano_precision_crepe"] = mean(
                bn[k]["pitch_precision"] for k in pianists
            )
            out[f"{section}_piano_precision_change"] = paired(bn, n, "pitch_precision", pianists)
    sub = [i for i, (_e, label) in enumerate(VALUE_BANDS) if label in SUB_EIGHTH]
    for which, bands in (
        ("", out.get("omnibook_bands")),
        ("_crepe", out.get("omnibook_bands_crepe")),
    ):
        if bands:
            hits = sum(bands[i][0] * bands[i][1] for i in sub)
            total = sum(bands[i][1] for i in sub)
            out[f"omnibook_sub_eighth_recall{which}"] = hits / total if total else float("nan")
            out["omnibook_sub_eighth_n"] = total
    # Sub-eighth recall per side, paired, so the kill criterion has an interval.
    ks = sorted(k for k in bn if set_of(k) == "omnibook" and k in n)
    if ks:
        from swingscribe.evaluation import paired_change

        def sub_recall(entry):
            total = sum(entry["band_n"][i] for i in sub)
            return sum(entry["band_hit"][i] for i in sub) / total if total else 0.0

        out["omnibook_sub_eighth_change"] = paired_change(
            [sub_recall(bn[k]) for k in ks], [sub_recall(n[k]) for k in ks], ks, tolerance=0.002
        )
    out.update(ceilings(card, base, keys))
    out.update(page_measures(card, base))
    return out


def ceilings(card: dict, base: dict, keys: list[str]) -> dict:
    """What a PERFECT selector between CREPE and this variant could reach:
    a reference note counts if either detector hit it (each under its own
    one-to-one mir_eval matching). And, of CREPE's `neighbour` pairs, how
    many reference notes the variant hit at the right pitch -- the most a
    pitch vote could ever repair."""
    w, bw = card["wjazz"], base["wjazz"]
    if not all("hit_idx" in bw.get(k, {}) and "hit_idx" in w.get(k, {}) for k in keys):
        return {}
    width = len(DURATION_EDGES) + 1
    union, total = [0] * width, [0] * width
    fixable = neighbours = 0
    for k in keys:
        either = set(bw[k]["hit_idx"]) | set(w[k]["hit_idx"])
        for i, b in enumerate(bw[k]["bucket_of"]):
            total[b] += 1
            union[b] += i in either
        theirs = set(w[k]["hit_idx"])
        neighbours += len(bw[k]["neighbour_ref"])
        fixable += sum(1 for i in bw[k]["neighbour_ref"] if i in theirs)
    out = {
        "wjazz_union_buckets": [
            u / t if t else float("nan") for u, t in zip(union, total, strict=True)
        ],
        "wjazz_union_recall": sum(union) / sum(total),
        "crepe_neighbour_refs": neighbours,
        "crepe_neighbour_refs_hit_by_variant": fixable,
    }
    n, bn = card["notated"], base["notated"]
    omni = sorted(k for k in bn if set_of(k) == "omnibook" and k in n and "hit_idx" in n[k])
    if omni:
        sub = {i for i, (_e, label) in enumerate(VALUE_BANDS) if label in SUB_EIGHTH}
        hits = count = 0
        for k in omni:
            either = set(bn[k]["hit_idx"]) | set(n[k]["hit_idx"])
            for i, b in enumerate(bn[k]["band_of"]):
                if b in sub:
                    count += 1
                    hits += i in either
        out["omnibook_union_sub_eighth_recall"] = hits / count if count else float("nan")
    return out


PAGE_FIELDS = ("rhythm", "value", "readability", "on_the_bar", "tie_rate")


def page_measures(card: dict, base: dict) -> dict:
    """The page, where `--notation` built one: means over the tracks both
    cards notated, and the paired change. A located page's rhythm, value and
    placement count only where BOTH sides are trusted (coverage over the
    floor), exactly as `run_eval.paired_changes` reads them."""
    from swingscribe.evaluation import paired_change

    p, bp = card.get("notation", {}), base.get("notation", {})
    out = {}
    for section in ("own", "omnibook", "pages"):
        for field in PAGE_FIELDS:
            ks = sorted(k for k in bp if set_of(k) == section and k in p)
            ks = [k for k in ks if field in bp[k] and field in p[k]]
            if field in run_eval.TRUSTED_FIELDS:
                ks = [k for k in ks if bp[k].get("trusted", 1.0) == 1.0 == p[k].get("trusted", 1.0)]
            if not ks:
                continue
            out[f"page_{section}_{field}_n"] = len(ks)
            out[f"page_{section}_{field}"] = mean(p[k][field] for k in ks)
            out[f"page_{section}_{field}_crepe"] = mean(bp[k][field] for k in ks)
            out[f"page_{section}_{field}_change"] = paired_change(
                [bp[k][field] for k in ks],
                [p[k][field] for k in ks],
                ks,
                tolerance=run_eval.TOLERANCE,
            )
    return out


def print_summary(s: dict) -> None:
    def pair(field: str, digits: int = 3) -> str:
        return f"{s[field]:.{digits}f}/{s[field + '_crepe']:.{digits}f}"

    print(f"\n=== {s['variant']} ===  (each pair is variant/CREPE)")
    for group in ("all", "tuning", "heldout", "horn", "piano"):
        g = f"wjazz_{group}"
        if not s.get(f"{g}_n"):
            continue
        print(
            f"  WJazzD {group:<8s} n={s[f'{g}_n']:3d}  F1 {pair(f'{g}_note_f1', 4)}  "
            f"P {pair(f'{g}_note_precision')}  R {pair(f'{g}_note_recall')}  "
            f"{fmt_change(s[f'{g}_f1_change'])}"
        )
    print(
        "  WJazzD recall by duration: "
        + "  ".join(
            f"{label} {v:.3f}/{c:.3f} (n={n})"
            for label, (v, n), (c, _n) in zip(
                DURATION_LABELS, s["wjazz_buckets"], s["wjazz_buckets_crepe"], strict=True
            )
        )
    )
    cls, base = s["wjazz_classes"], s["wjazz_classes_crepe"]
    shown = ("miss", "fp", "neighbour", "octave", "other_pitch", "attack_transient", "loose")
    print("  WJazzD errors: " + ", ".join(f"{c} {cls.get(c, 0)}/{base.get(c, 0)}" for c in shown))
    if s.get("lead_median_of_medians") is not None:
        lead = 1000 * s["lead_median_of_medians"]
        print(f"  onset lead (median over solos of the median hit dt): {lead:+.1f} ms")
    for section in ("own", "omnibook", "pages"):
        if not s.get(f"{section}_n"):
            continue
        print(
            f"  {section:<8s} n={s[f'{section}_n']:3d}  pitch F1 {pair(f'{section}_pitch_f1', 4)}  "
            f"P {pair(f'{section}_pitch_precision')}  R {pair(f'{section}_pitch_recall')}  "
            f"{fmt_change(s[f'{section}_f1_change'])}"
        )
        if s.get(f"{section}_piano_n"):
            print(
                f"           pianists n={s[f'{section}_piano_n']}  precision "
                f"{pair(f'{section}_piano_precision')}  "
                f"{fmt_change(s[f'{section}_piano_precision_change'])}"
            )
    if s.get("omnibook_bands"):
        print(
            "  Omnibook recall by value: "
            + "  ".join(
                f"{label} {v:.3f}/{c:.3f} (n={n})"
                for (_e, label), (v, n), (c, _n) in zip(
                    VALUE_BANDS, s["omnibook_bands"], s["omnibook_bands_crepe"], strict=True
                )
            )
        )
        print(
            f"  Omnibook sub-eighth recall {pair('omnibook_sub_eighth_recall', 4)} "
            f"(n={s['omnibook_sub_eighth_n']})  {fmt_change(s['omnibook_sub_eighth_change'])}"
        )
    if "wjazz_union_recall" in s:
        book = s.get("omnibook_union_sub_eighth_recall", float("nan"))
        print(
            f"  CREPE-or-variant ceiling: WJazzD recall {s['wjazz_union_recall']:.3f} ("
            + "  ".join(
                f"{label} {v:.3f}"
                for label, v in zip(DURATION_LABELS, s["wjazz_union_buckets"], strict=True)
            )
            + f"); Omnibook sub-eighth {book:.3f}"
            f"; CREPE neighbour refs the variant hit: {s['crepe_neighbour_refs_hit_by_variant']}"
            f" of {s['crepe_neighbour_refs']}"
        )
    for section in ("own", "omnibook", "pages"):
        for field in PAGE_FIELDS:
            key = f"page_{section}_{field}"
            if key in s:
                print(
                    f"  page {section:<8s} {field:<11s} n={s[key + '_n']:2d} {pair(key, 4)}  "
                    f"{fmt_change(s[key + '_change'])}"
                )


def jsonable(value):
    from swingscribe.evaluation import PairedChange

    if isinstance(value, PairedChange):
        return {**value.__dict__, "decided": value.decided}
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def score(args) -> None:
    run_eval.CACHE_DIR = BATCH_CACHE
    manifest = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))
    runs = live_runs(args.db, log=lambda *_a: None)
    keys = sorted(k for k in runs if k in manifest)
    fits = wjazz_fits(args.db, {k: runs[k] for k in keys}, args.out, args.jobs)
    scores = score_paths({k: runs[k] for k in keys})
    meta = {k: ("piano" if manifest[k]["piano"] else "horn") for k in keys}
    if args.subset == "tuning":
        keys = [k for k in keys if not run_eval.is_located(k) and is_tuning(run_eval.track_of(k))]
        if not args.wjazz_only:
            raise SystemExit("--subset tuning scores WJazzD only; pass --wjazz-only")
    crepe = {
        k: [
            {kk: n[kk] for kk in ("onset", "duration", "pitch", "confidence")}
            for n in runs[k]["notes"]
        ]
        for k in keys
    }
    base = score_variant("crepe", crepe, fits, scores, args, runs)
    if args.check:
        check_against_pins(base)
    bp = json.loads(Path(args.bp).read_text(encoding="utf-8")) if args.bp else None
    results = []
    for variant in args.variants.split(",") if args.variants else []:
        notes_of = {
            k: build(variant, crepe[k], bp["notes"].get(k, []), manifest[k]["piano"], args)
            for k in keys
        }
        label = f"{variant}@{Path(args.bp).stem}~shift{args.shift:+.3f}"
        card = score_variant(label, notes_of, fits, scores, args, runs)
        summary = summarise(label, card, base, meta)
        summary["params"] = bp["params"]
        print_summary(summary)
        results.append(summary)
    if args.summary:
        existing = []
        if args.summary.is_file():
            existing = json.loads(args.summary.read_text(encoding="utf-8"))
        done = {s["variant"] for s in results}
        merged = [s for s in existing if s["variant"] not in done] + jsonable(results)
        args.summary.write_text(json.dumps(merged, indent=1), encoding="utf-8")


def check_against_pins(base: dict) -> None:
    """The control that this script's scoring IS the harness's: CREPE's card
    here must reproduce the pinned per-track numbers."""
    pins = json.loads(run_eval.BASELINES.read_text(encoding="utf-8"))
    worst = []
    for key, entry in base["wjazz"].items():
        pin = pins.get(f"wjazz/{run_eval.pin_name(key)}/note_f1")
        if pin is not None:
            worst.append((abs(pin - entry["note_f1"]), f"wjazz/{key}"))
    for key, entry in base["notated"].items():
        section = {"own": "mscz", "omnibook": "omnibook", "pages": "pages"}[set_of(key)]
        pin = pins.get(f"{section}/{run_eval.pin_name(key)}/pitch_f1")
        if pin is not None:
            worst.append((abs(pin - entry["pitch_f1"]), f"{section}/{key}"))
    for key, entry in base.get("notation", {}).items():
        section = {"own": "notation", "omnibook": "omnibook-notation", "pages": "pages-notation"}
        for field in ("rhythm", "value", "readability"):
            pin = pins.get(f"{section[set_of(key)]}/{run_eval.pin_name(key)}/{field}")
            if pin is not None and field in entry:
                worst.append((abs(pin - entry[field]), f"{section[set_of(key)]}/{key}/{field}"))
    worst.sort(reverse=True)
    print(
        f"  CREPE card against the pins: {len(worst)} numbers, worst |diff| "
        f"{worst[0][0]:.4f} ({worst[0][1]}); {sum(1 for d, _ in worst if d > 0.002)} over 0.002"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest", help="the stem and region of every scored run")
    m.add_argument("--db", type=Path, default=Path("wjazz/wjazzd.db"))
    m.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score", help="score variants against CREPE")
    s.add_argument("--db", type=Path, default=Path("wjazz/wjazzd.db"))
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--bp", type=Path, default=None, help="notes decoded by the WSL half")
    s.add_argument(
        "--variants",
        default="",
        help="comma list of raw, sky, loud, pick, hybrid:<min amp>[:<gap s>[:<cover>]], "
        "nvote:<min amp>",
    )
    s.add_argument("--shift", type=float, default=0.0, help="seconds added to every BP onset")
    s.add_argument("--subset", choices=("all", "tuning"), default="all")
    s.add_argument("--wjazz-only", action="store_true")
    s.add_argument("--check", action="store_true", help="CREPE's card against the pins")
    s.add_argument("--summary", type=Path, default=None, help="append summaries to this JSON")
    s.add_argument("--notation", action="store_true", help="also build and score the page")
    s.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    {"manifest": manifest, "score": score}[args.command](args)
    print(f"({time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
