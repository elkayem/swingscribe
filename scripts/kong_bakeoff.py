"""Roadmap A2 and A4: two note-only Kong checkpoints against what ships.

    python scripts/kong_bakeoff.py infer    --out DIR --model filosax --which horn --device cuda
    python scripts/kong_bakeoff.py crepe    --out DIR --snapshot SNAP [--source crepe]
    python scripts/kong_bakeoff.py decode   --out DIR --model filosax --onset 0.5
    python scripts/kong_bakeoff.py pianists --out DIR --db wjazz/wjazzd.db --snapshot SNAP
    python scripts/kong_bakeoff.py horns    --out DIR --db wjazz/wjazzd.db --snapshot SNAP \\
        --fs DIR/filosax/notes-default.json --bp BP.json --fs-shift 0.006 \\
        --variants saxbph/stack:s:0.7:0.04   (the declared composite; docs/kong-bakeoff.md)

(run it as `.venv\\Scripts\\python.exe`, PYTHONIOENCODING=utf-8). Both models
are Kong et al.'s high-resolution CRNN retrained by others, and both load
through `piano.load_note_model`, the second loader, which never reaches
upstream's download-over-small-files check and keeps the activations:

- **Edwards et al.** (Zenodo 10610212, CC BY 4.0): the piano model
  retrained with augmentation for robustness. Swapped in for the pipeline's
  checkpoint wherever a PIANIST's line reads the piano model -- the oracle
  line (`line_selection.pick_line`, the default take) and CREPE's line
  corrected by it (`corroborate.apply` + `fill_gaps`, the second take).
  Pianists only (roadmap A4).
- **Riley & Dixon's FiloSax saxophone CRNN** (Hugging Face
  xavriley/midi-transcription-models, `filosax_25k.pth`): tenor saxophone
  only, never trumpet or trombone. HORNS only (roadmap A2), three ways: as
  the line, as a hole-filler exactly like the Basic Pitch hybrid, and as a
  selector between CREPE's line and its own -- each on every horn or routed
  to the saxophones (`ROUTES`), against CREPE and the hybrid.

The pianists' second take needs CREPE's line before the oracle. `crepe`
rebuilds it from the GUI's cached review payloads by default, with no CREPE
pass (`line_from_frames`); a take the control cannot rebuild is reported
apart (`CONTROL_FLOOR`).

## What is held fixed

Everything `frontend_bakeoff.py` holds fixed, through its own functions:
the stems and regions each harness run transcribed (its `manifest.json`,
copied from the Basic Pitch bake-off's scratch), CREPE's fit of every WJazzD
solo (its `fits.json`), the declared tuning subset (`frontend_bakeoff.
is_tuning`), and the scorers (`score_variant`: `score_wjazz.score` under the
fixed fit, the time-free notated pitch F1, `run_eval.notation_scores`).
The harness caches are read ONLY through a snapshot (`--snapshot`): another
workflow rewrites them while this runs, and the fingerprints the live
harness checks move with its in-flight config.

## The controls

- The pipeline's own checkpoint (`kong`), run through the second loader,
  must reproduce the cached pianist runs, both takes (`pianists` prints the
  share of notes reproduced) -- the check that the swap changes the WEIGHTS
  and nothing else.
- CREPE's card, scored here, against the pinned numbers (`--check`), and
  the Basic Pitch hybrid rebuilt from round one's notes against round one's
  numbers.
- A float16 re-decode of the stored rolls against the float32 decode made at
  inference, both ways (`infer --check16`).

Every change is `evaluation.paired_change`: the same tracks before and
after, a 95% bootstrap interval resampled by recording, and a sign test.

## Where things land

The activations (four rolls at 100 frames/s, float16) go OUTSIDE the repo
and outside AppData, under `~/swingscribe-research/kong-activations/`, so
roadmap A6 can find them; notes, cards and summaries under `--out`. None of
it may enter the repo: all of it is derived from commercial recordings.
Results and the verdict: docs/kong-bakeoff.md.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import frontend_bakeoff as fb  # noqa: E402  (chdirs to the repo, imports run_eval)
import run_eval  # noqa: E402

RESEARCH = Path.home() / "swingscribe-research"
ACTIVATIONS = RESEARCH / "kong-activations"

# The card is shared with other long jobs: take it only with this much free,
# or run on the CPU and say so. The first Kong inference of this bake-off
# started on a card another job held at 5.9 of 6 GB.
GPU_FREE_FLOOR = 3 * 2**30


def usable_device(requested: str) -> str:
    """`requested`, unless it names a GPU that is missing or has less than
    `GPU_FREE_FLOOR` bytes free; then the CPU, with a line saying why."""
    if not requested.startswith("cuda"):
        return requested
    import torch

    if not torch.cuda.is_available():
        print(f"{requested}: no CUDA device; running on the CPU", flush=True)
        return "cpu"
    free, total = torch.cuda.mem_get_info(torch.device(requested))
    if free < GPU_FREE_FLOOR:
        print(
            f"{requested}: {free / 2**30:.1f} of {total / 2**30:.1f} GB free, under "
            f"the {GPU_FREE_FLOOR / 2**30:.0f} GB floor; running on the CPU",
            flush=True,
        )
        return "cpu"
    return requested


def checkpoint(model: str) -> Path:
    """Where each model's weights are. `kong` is the pipeline's own
    Note_pedal release, whose note head the second loader runs."""
    from swingscribe import piano

    return {
        "kong": piano.checkpoint_path(),
        "edwards": RESEARCH / "edwards-piano" / "high_resolution_MAESTRO_augmentations.pth",
        "filosax": RESEARCH / "filosax-sax-crnn" / "filosax_25k.pth",
    }[model]


def use_snapshot(snapshot: Path) -> None:
    """Point every harness cache this reads at the snapshot copies."""
    fb.NOTES_CACHE = snapshot / ".benchmark-notes-c0.2-d0.0.json"
    run_eval.GRIDS_CACHE = snapshot / ".benchmark-grids.json"
    run_eval.BASELINES = snapshot / "real-audio-baselines.json"
    run_eval.CACHE_DIR = fb.BATCH_CACHE


def load_manifest(out: Path) -> dict:
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def select(manifest: dict, which: str) -> list[str]:
    keys = sorted(manifest)
    if which == "piano":
        return [k for k in keys if manifest[k]["piano"]]
    if which == "horn":
        return [k for k in keys if not manifest[k]["piano"]]
    return keys


def sidecar_of(key: str) -> dict:
    path = run_eval.BENCH / f"{run_eval.track_of(key)}.swingscribe.json"
    return json.loads(path.read_text(encoding="utf-8"))


def activation_file(model: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return ACTIVATIONS / model / f"{digest}.npz"


def load_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(tmp, path)


# ── 1. inference: rolls and default notes ───────────────────────────────────


def same_notes(a: list[dict], b: list[dict], tolerance: float = 0.002) -> float:
    """The share of `a` with a note in `b` at the same pitch within
    `tolerance` seconds of its onset, one-to-one."""
    if not a:
        return 1.0 if not b else 0.0
    free: dict[int, list[float]] = {}
    for note in b:
        free.setdefault(int(note["pitch"]), []).append(float(note["onset"]))
    for onsets in free.values():
        onsets.sort()
    hits = 0
    for note in a:
        onsets = free.get(int(note["pitch"]), [])
        i = bisect.bisect_left(onsets, float(note["onset"]) - tolerance)
        if i < len(onsets) and abs(onsets[i] - float(note["onset"])) <= tolerance:
            onsets.pop(i)
            hits += 1
    return hits / len(a)


def infer(args) -> None:
    """Run one checkpoint over the manifest's regions, cropped exactly as the
    pipeline crops them; keep the rolls (float16) and the notes decoded at
    upstream's thresholds from the float32 rolls."""
    import numpy as np
    import soundfile
    import torch

    from swingscribe import piano
    from swingscribe.stages.transcribe import crop_region

    manifest = load_manifest(args.out)
    keys = select(manifest, args.which)
    # The CPU's share either way: resampling runs there even when the model
    # is on the GPU, and this machine is shared with other long jobs.
    torch.set_num_threads(args.threads)
    device = usable_device(args.device)
    model = piano.load_note_model(checkpoint(args.model), device)
    print(f"{args.model}: {model.path.name}, iteration {model.iteration}, on {device}")
    notes_path = args.out / args.model / "notes-default.json"
    index_path = ACTIVATIONS / args.model / "index.json"
    notes = load_json(notes_path, {})
    index = load_json(index_path, {})
    started, seconds, checked = time.time(), 0.0, 0
    for key in keys:
        if key in notes and activation_file(args.model, key).is_file():
            continue
        entry = manifest[key]
        tick = time.time()
        data, rate = soundfile.read(entry["wav"], dtype="float32", always_2d=True)
        mono, offset = crop_region(data.mean(axis=1), rate, tuple(entry["region"]))
        del data
        mono16 = piano.to_model_rate(mono, rate)
        rolls = piano.note_activations(model, mono16, args.batch)
        found = piano.decode_notes(rolls, offset)
        half = {k: v.astype(np.float16) for k, v in rolls.items()}
        # How much float16 storage moves a decode, for every later sweep
        # (checked on the first few regions: a decode is most of the time).
        # Both ways: a one-sided share missed float16's zero-length copies.
        agree = None
        if checked < args.check16:
            again = piano.decode_notes(half, offset)
            agree = min(same_notes(found, again), same_notes(again, found))
            checked += 1
        path = activation_file(args.model, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **half)
        notes[key] = found
        index[key] = {
            "file": path.name,
            "offset": offset,
            "region": entry["region"],
            "wav": entry["wav"],
            "audio_frames": int(np.ceil(len(mono16) / (piano.MODEL_SAMPLE_RATE // 100))) + 1,
            "checkpoint": model.path.name,
        }
        save_json(notes_path, notes)
        save_json(index_path, index)
        seconds += len(mono) / rate
        print(
            f"  {key}: {len(found)} notes, {len(mono) / rate:.0f}s audio in "
            f"{time.time() - tick:.1f}s"
            + ("" if agree is None else f"; float16 decode agrees on {agree:.4f}"),
            flush=True,
        )
    elapsed = time.time() - started
    print(f"{seconds:.0f}s of audio in {elapsed:.0f}s ({seconds / max(elapsed, 1e-9):.0f}x)")


REVIEW_ROOTS = (
    REPO / "benchmark" / ".swingscribe-cache" / "gui" / "reviews",
    REPO / ".swingscribe-cache" / "gui" / "reviews",
)


def line_from_frames(diagnostics: dict, tc) -> list:
    """CREPE's line before the oracle, rebuilt from a review payload's frame
    trace by `analyze`'s own steps after the CREPE pass: `segment_notes` over
    the gated, smoothed pitch and the corroborated onsets, then
    `fold_octave_outliers`, then whole-track time. The payload rounds to a
    millisecond and a thousandth of a semitone; the control in `pianists`
    measures what that costs (nothing, where it was measured)."""
    from swingscribe.stages import transcribe

    hop, start = float(diagnostics["hop_s"]), float(diagnostics["start"])
    onset_frames = {round((float(t) - start) / hop) for t in diagnostics["onsets"]}
    notes = transcribe.segment_notes(
        diagnostics["pitch"],
        [float(p) for p in diagnostics["periodicity"]],
        onset_frames,
        hop_s=hop,
        min_note_s=tc.min_note_ms / 1000.0,
        persist_frames=max(1, round(tc.pitch_persist_ms / 1000.0 / hop)),
        max_gap_frames=max(1, round(tc.silence_gap_ms / 1000.0 / hop)),
        source=f"{tc.stem}:crepe",
    )
    return transcribe.offset_notes(transcribe.fold_octave_outliers(notes), start)


def crepe(args) -> None:
    """The pianists' CREPE line BEFORE the piano model touches it -- what
    `_consult_piano_oracle` receives -- so the second take can be rebuilt
    around either checkpoint.

    `--source reviews` (the default) runs NO CREPE: it finds, among the GUI's
    cached review payloads, the one whose frame trace belongs to each
    pianist -- matched by content, its diagnostics starting at the run's
    region and its notes reproducing one of the run's two cached takes -- and
    rebuilds the line from it (`line_from_frames`). A pianist nobody has
    reviewed gets no second take here. `--source crepe` runs one CREPE pass
    per pianist through `transcribe.analyze` itself with the oracle step
    intercepted."""
    use_snapshot(args.snapshot)
    manifest = load_manifest(args.out)
    path = args.out / "crepe-pre-oracle.json"
    done = load_json(path, {})
    keys = [k for k in select(manifest, "piano") if k not in done]
    if args.source == "crepe":
        done.update(_crepe_pass(args, manifest, keys))
    else:
        done.update(_from_reviews(keys))
    save_json(path, done)
    for key in select(manifest, "piano"):
        entry = done.get(key)
        print(
            f"  {key}: "
            + (
                "no frame trace"
                if entry is None
                else f"{len(entry['notes'])} CREPE notes ({entry['source']})"
            )
        )


def _from_reviews(keys: list[str]) -> dict:
    snapshot = json.loads(fb.NOTES_CACHE.read_text(encoding="utf-8"))
    targets = {
        (key, take): snapshot[k]
        for key in keys
        for take, k in (("default", key), ("crepe", run_eval.second_key(key)))
        if k in snapshot
    }
    best: dict[str, tuple] = {}
    for root in REVIEW_ROOTS:
        for path in sorted(root.rglob("*.bin")):
            try:
                payload = json.loads(path.read_bytes())
                start = float(payload["diagnostics"]["start"])
            except (ValueError, KeyError, TypeError):
                continue
            for (key, take), run in targets.items():
                if abs(float(run["region"][0]) - start) > 0.002:
                    continue
                share = min(
                    same_notes(run["notes"], payload["notes"]),
                    same_notes(payload["notes"], run["notes"]),
                )
                # A match on CREPE's own take vouches for the frames directly.
                rank = (share >= 0.999 and take == "crepe", share)
                if share >= 0.95 and rank > best.get(key, ((False, 0.0),))[0]:
                    best[key] = (rank, path, take, share)
    out = {}
    for key, (_rank, path, take, share) in best.items():
        payload = json.loads(path.read_bytes())
        tc = run_eval.transcribe_settings(sidecar_of(key), 0.2, 0.0, run_eval.SECOND_LINE)
        notes = line_from_frames(payload["diagnostics"], tc)
        out[key] = {
            "notes": [n.model_dump(mode="json") for n in notes],
            "source": f"review {path.parent.name}{path.stem[:10]} ({take} take {share:.4f})",
        }
    return out


def _crepe_pass(args, manifest: dict, keys: list[str]) -> dict:
    from swingscribe.stages import transcribe

    captured: dict = {}

    def intercept(_mono, _rate, _tc, _offset, notes, *, log=False):
        captured["notes"] = list(notes)
        return notes, [], []

    transcribe._consult_piano_oracle = intercept
    device = usable_device(args.device)
    out = {}
    for key in keys:
        settings = run_eval.transcribe_settings(sidecar_of(key), 0.2, 0.0, run_eval.SECOND_LINE)
        settings = settings.model_copy(update={"device": device})
        transcribe.analyze(manifest[key]["wav"], settings)
        out[key] = {
            "notes": [n.model_dump(mode="json") for n in captured.pop("notes")],
            "source": "crepe",
        }
    return out


# ── 2. decoding at other thresholds, from the stored rolls ──────────────────


def _decode_one(task: tuple) -> tuple[str, list[dict]]:
    key, npz, offset, thresholds = task
    import numpy as np

    from swingscribe import piano

    with np.load(npz) as rolls:
        return key, piano.decode_notes({k: rolls[k] for k in piano.ROLLS}, offset, **thresholds)


def decoded_path(out: Path, model: str, onset: float, frame: float) -> Path:
    return out / model / f"notes-o{onset:g}-f{frame:g}.json"


def decode(args) -> None:
    index = load_json(ACTIVATIONS / args.model / "index.json", {})
    thresholds = {"onset_threshold": args.onset, "frame_threshold": args.frame}
    tasks = [
        (k, str(ACTIVATIONS / args.model / e["file"]), e["offset"], thresholds)
        for k, e in sorted(index.items())
    ]
    started = time.time()
    notes = dict(run_eval.parallel_map(_decode_one, tasks, args.jobs))
    path = decoded_path(args.out, args.model, args.onset, args.frame)
    save_json(path, notes)
    total = sum(len(v) for v in notes.values())
    print(f"{len(notes)} regions, {total} notes -> {path} ({time.time() - started:.0f}s)")


# ── 3. the shared runs and fits ─────────────────────────────────────────────


def load_runs(manifest: dict) -> dict:
    """The snapshot's runs for the manifest's keys, and each pianist's second
    take under its own key. The manifest (not the fingerprint) says which
    runs count: the live fingerprint moves with another workflow's config."""
    cache = json.loads(fb.NOTES_CACHE.read_text(encoding="utf-8"))
    runs = {}
    for key in manifest:
        runs[key] = cache[key]
        second = run_eval.second_key(key)
        if manifest[key]["piano"] and second in cache:
            runs[second] = cache[second]
    return runs


def crepe_notes(run: dict) -> list[dict]:
    return [{k: n[k] for k in ("onset", "duration", "pitch", "confidence")} for n in run["notes"]]


def fixed_references(args, runs: dict, keys: list[str]) -> tuple[dict, dict]:
    fits = fb.wjazz_fits(args.db, {k: runs[k] for k in keys}, args.out, args.jobs)
    scores = fb.score_paths({k: runs[k] for k in keys})
    return fits, scores


# ── 4. pianists: Edwards against the pipeline's checkpoint ──────────────────


ORACLE_KEYS = ("onset", "duration", "pitch", "velocity")
# The share of a cached take the control must rebuild, both ways, before that
# take is compared at all.
CONTROL_FLOOR = 0.99


def oracle_takes(events: list[dict], pre_oracle: list, sidecar: dict) -> tuple[list, list]:
    """Both pianist takes, built by the pipeline's own code around `events`:
    `_consult_piano_oracle` with the piano model's answer supplied, then --
    for CREPE's take only -- `reject_line_outliers`, exactly as `analyze`
    runs them."""
    from swingscribe import piano
    from swingscribe.stages import transcribe

    heard = [{k: e[k] for k in ORACLE_KEYS} for e in events]
    default_tc = run_eval.transcribe_settings(sidecar, 0.2, 0.0)
    crepe_tc = run_eval.transcribe_settings(sidecar, 0.2, 0.0, run_eval.SECOND_LINE)
    saved = piano.transcribe
    piano.transcribe = lambda *_a, **_k: [dict(e) for e in heard]
    try:
        line, _, _ = transcribe._consult_piano_oracle(None, 0, default_tc, 0.0, pre_oracle)
        second, _, _ = transcribe._consult_piano_oracle(None, 0, crepe_tc, 0.0, pre_oracle)
    finally:
        piano.transcribe = saved
    second = transcribe.reject_line_outliers(
        second,
        None,
        crepe_tc.line_window_s,
        crepe_tc.line_register_floor,
        crepe_tc.line_loudness_floor_db,
    )

    def as_dicts(notes):
        return [
            {"onset": n.onset, "duration": n.duration, "pitch": n.pitch, "confidence": n.confidence}
            for n in notes
        ]

    return as_dicts(line), as_dicts(second)


PIANIST_PAGE = ("rhythm", "value", "readability", "on_the_bar", "tie_rate", "edit_cost")


def pianists(args) -> None:
    from swingscribe.model import NoteEvent

    use_snapshot(args.snapshot)
    manifest = load_manifest(args.out)
    keys = select(manifest, "piano")
    runs = load_runs(manifest)
    fits, scores = fixed_references(args, runs, sorted(manifest))
    pre = load_json(args.out / "crepe-pre-oracle.json", {})
    # CREPE's take exists only where CREPE's own line does (`crepe`).
    crepe_keys = [k for k in keys if k in pre]
    by_model = {m: load_json(args.out / m / "notes-default.json", {}) for m in ("kong", "edwards")}
    notes_of: dict[str, dict[str, list]] = {}
    for model, events in by_model.items():
        for key in keys:
            pre_oracle = [NoteEvent(**n) for n in pre[key]["notes"]] if key in pre else []
            line, second = oracle_takes(events[key], pre_oracle, sidecar_of(key))
            notes_of.setdefault(f"{model}-oracle", {})[key] = line
            if key in pre:
                notes_of.setdefault(f"{model}-crepe", {})[key] = second
    # The control: the pipeline's checkpoint, through the second loader and
    # the pipeline's own take-building, against the cached runs.
    print("control: the pipeline's checkpoint through the second loader, against the cache")
    control = {}
    for key in keys:
        cached_line = runs[key]["notes"]
        ours_line = notes_of["kong-oracle"][key]
        row = {
            "oracle": [
                len(ours_line),
                len(cached_line),
                same_notes(cached_line, ours_line),
                same_notes(ours_line, cached_line),
            ],
        }
        text = (
            f"  {key}: oracle line {len(ours_line)}/{len(cached_line)} notes, "
            f"{row['oracle'][2]:.4f}/{row['oracle'][3]:.4f} reproduced"
        )
        if key in pre:
            cached_second = runs[run_eval.second_key(key)]["notes"]
            ours_second = notes_of["kong-crepe"][key]
            row["crepe"] = [
                len(ours_second),
                len(cached_second),
                same_notes(cached_second, ours_second),
                same_notes(ours_second, cached_second),
            ]
            text += (
                f"; CREPE take {len(ours_second)}/{len(cached_second)}, "
                f"{row['crepe'][2]:.4f}/{row['crepe'][3]:.4f}"
            )
        control[key] = row
        print(text)
    # CREPE's take is compared only where the control rebuilt the cached take:
    # a review's frame trace can come from an older CREPE config or stem set,
    # and then the take is not the pipeline's. The rest are reported apart.
    valid = [k for k in crepe_keys if min(control[k]["crepe"][2:]) >= CONTROL_FLOOR]
    stale = [k for k in crepe_keys if k not in valid]
    for model in by_model:
        takes = notes_of.get(f"{model}-crepe", {})
        notes_of[f"{model}-crepe-stale"] = {k: takes.pop(k) for k in stale}
    if stale:
        print(f"CREPE take rebuilt from a stale frame trace (under {CONTROL_FLOOR}): {stale}")
    args.wjazz_only = False
    args.notation = True
    cached = {
        "cache-oracle": {k: crepe_notes(runs[k]) for k in keys},
        "cache-crepe": {k: crepe_notes(runs[run_eval.second_key(k)]) for k in valid},
        "cache-crepe-stale": {k: crepe_notes(runs[run_eval.second_key(k)]) for k in stale},
    }
    notes_of = {name: notes for name, notes in notes_of.items() if notes}
    cached = {name: notes for name, notes in cached.items() if notes}
    cards = {}
    for name, notes in {**cached, **notes_of}.items():
        cards[name] = fb.score_variant(f"pianist-{name}", notes, fits, scores, args, runs)
        cards[name]["mscz"] = run_eval.mscz_scores(
            {k: {**runs[k], "notes": notes[k]} for k in notes}, args.jobs
        )
    summary: dict = {"control": control}
    for take, ks in (("oracle", keys), ("crepe", valid), ("crepe-stale", stale)):
        if not ks:
            continue
        before, after = cards[f"kong-{take}"], cards[f"edwards-{take}"]
        summary[take] = pianist_rows(before, after, ks)
        summary[f"{take}-control"] = pianist_rows(cards[f"cache-{take}"], before, ks)
    summary["per_track"] = {
        name: {
            k: {
                "wjazz_note_f1": _wjazz_of(card, k),
                "pitch_f1": card["notated"].get(k, {}).get("pitch_f1"),
                "note_f1": card["mscz"].get(k, {}).get("note_f1"),
                "rhythm": card["notation"].get(k, {}).get("rhythm"),
            }
            for k in keys
        }
        for name, card in cards.items()
    }
    save_json(args.out / "pianists-summary.json", fb.jsonable(summary))
    for label, rows in summary.items():
        if label in ("control", "per_track"):
            continue
        print(
            f"\n=== pianists, {label} take: "
            + ("cache -> kong" if "control" in label else "kong -> edwards")
        )
        for row in rows:
            print(
                f"  {row['measure']:<28s} n={row['n']:2d}  {row['before']:.4f} -> "
                f"{row['after']:.4f}  {fb.fmt_change(row['change'])}"
            )


def _wjazz_of(card: dict, key: str):
    rows = [v["note_f1"] for k, v in card["wjazz"].items() if run_eval.track_of(k) == key]
    return statistics.fmean(rows) if rows else None


def pianist_rows(before: dict, after: dict, keys: list[str]) -> list[dict]:
    """One row per measure: WJazzD note F1 (the four WJazzD pianists, under
    the fixed fit), hand-score pitch F1 (time-free) and note F1 (audio against
    notation), and the page (rhythm, value, readability, placement, ties,
    edit cost; `run_eval.notation_scores`)."""
    from swingscribe.evaluation import paired_change

    rows = []

    def add(label, b, a, field):
        ks = [k for k in keys if k in b and k in a and field in b[k] and field in a[k]]
        if not ks:
            return
        rows.append(
            {
                "measure": label,
                "n": len(ks),
                "before": statistics.fmean(b[k][field] for k in ks),
                "after": statistics.fmean(a[k][field] for k in ks),
                "change": paired_change(
                    [b[k][field] for k in ks],
                    [a[k][field] for k in ks],
                    [run_eval.track_of(k) for k in ks],
                    tolerance=run_eval.TOLERANCE,
                ),
            }
        )

    wjazz_b = {run_eval.track_of(k): v for k, v in before["wjazz"].items()}
    wjazz_a = {run_eval.track_of(k): v for k, v in after["wjazz"].items()}
    for field in ("note_f1", "note_precision", "note_recall"):
        add(f"WJazzD {field}", wjazz_b, wjazz_a, field)
    for field in ("pitch_f1", "pitch_precision", "pitch_recall"):
        add(f"hand {field}", before["notated"], after["notated"], field)
    for field in ("note_f1", "onset_f1"):
        add(f"hand mscz {field}", before["mscz"], after["mscz"], field)
    for field in PIANIST_PAGE:
        add(f"page {field}", before["notation"], after["notation"], field)
    return rows


# ── 5. horns: the FiloSax model three ways ──────────────────────────────────


def fs_notes(events: list[dict], shift: float, conf: str) -> list[dict]:
    """The model's notes as the harness's dicts. `conf` picks what a gate
    reads as confidence: `s` the onset roll's peak, `v` the velocity head
    (normalised). No `velocity` key, so `fill_gaps` reads `confidence`."""
    out = []
    for e in events:
        confidence = e["onset_strength"] if conf == "s" else e["velocity"] / 127.0
        out.append(
            {
                "onset": float(e["onset"]) + shift,
                "duration": max(float(e["duration"]), 0.0),
                "pitch": int(e["pitch"]),
                "confidence": float(confidence),
            }
        )
    return sorted(out, key=lambda n: (n["onset"], -n["pitch"]))


def bp_hybrid(crepe: list[dict], bp_events: list) -> list[dict]:
    """The Basic Pitch hybrid as docs/frontend-bakeoff.md chose it: onset
    0.8 decode, amplitude 0.3, a 40 ms hole, onsets 4 ms late."""
    from swingscribe.corroborate import fill_gaps

    merged, _ = fill_gaps(
        crepe,
        fb.bp_notes(bp_events, 0.0),
        min_confidence=0.3,
        gap_tolerance=0.04,
        onset_shift=0.004,
    )
    return merged


def select_line(
    crepe: list[dict], fs: list[dict], replace: float, crepe_max: float, drop: float
) -> list[dict]:
    """A selector between CREPE's line and the model's, note by note, where
    the two meet (within 50 ms):

    - they agree on the pitch: CREPE's note stands;
    - they disagree: the model's pitch replaces CREPE's when its onset
      strength is at least `replace` AND CREPE's confidence is at most
      `crepe_max` (CREPE's onset and length are kept);
    - the model has nothing within 80 ms at CREPE's pitch and CREPE's
      confidence is under `drop`: CREPE's note is dropped (a horn model's
      corroboration -- which a PIANO model may never do to a horn).

    Holes are then filled by `fill_gaps` separately (the `fssel` variant)."""
    onsets = [n["onset"] for n in fs]
    out = []
    for note in crepe:
        lo = bisect.bisect_left(onsets, note["onset"] - 0.08)
        hi = bisect.bisect_right(onsets, note["onset"] + 0.08)
        near = fs[lo:hi]
        agree = [n for n in near if n["pitch"] == note["pitch"]]
        if agree:
            out.append(note)
            continue
        if note["confidence"] < drop:
            continue
        close = [
            n
            for n in near
            if abs(n["onset"] - note["onset"]) <= 0.05 and n["confidence"] >= replace
        ]
        if close and note["confidence"] <= crepe_max:
            best = max(close, key=lambda n: n["confidence"])
            out.append({**note, "pitch": best["pitch"]})
        else:
            out.append(note)
    return out


def horn_variant(variant: str, crepe: list[dict], fs_events: list, bp_events) -> list[dict]:
    """The notes a horn variant scores. Grammar (colon-separated):

    - `crepe`, `bph` (the Basic Pitch hybrid);
    - `fsraw:<conf>`, `fsloud:<conf>`, `fssky:<conf>`, `fspick:<conf>`: the
      model as the LINE (`conf` is `s`, the onset peak, or `v`, velocity);
    - `fsh:<conf>:<min>:<gap>`: CREPE plus the model in its holes;
    - `stack:<conf>:<min>:<gap>`: the Basic Pitch hybrid plus the model's
      notes in the holes it still has;
    - `fssel:<conf>:<replace>:<crepe max>:<drop>[:<min>:<gap>]`: the selector,
      then (with the last two) the holes filled;
    - `fsbp:<conf>`: the model as the line, with Basic Pitch's notes in ITS
      holes exactly as the hybrid fills CREPE's.
    """
    from swingscribe.corroborate import fill_gaps
    from swingscribe.line_selection import clusters_of, pick_line

    shift = ARGS.fs_shift
    name, *parts = variant.split(":")
    if name == "crepe":
        return crepe
    if name == "bph":
        return bp_hybrid(crepe, bp_events)
    conf = parts[0] if parts else "s"
    fs = fs_notes(fs_events, shift, conf)
    if name == "fsraw":
        return fs
    if name == "fsbp":
        return bp_hybrid(fs, bp_events)
    if name in ("fsloud", "fssky"):
        clusters = clusters_of(fs)
        if name == "fssky":
            return [max(c, key=lambda n: n["pitch"]) for c in clusters]
        return [max(c, key=lambda n: (n["confidence"], n["pitch"])) for c in clusters]
    if name == "fspick":
        with_velocity = [{**n, "velocity": n["confidence"]} for n in fs_notes(fs_events, 0.0, conf)]
        return pick_line(with_velocity, onset_shift=shift)
    if name in ("fsh", "stack"):
        minimum, gap = float(parts[1]), float(parts[2])
        base = crepe if name == "fsh" else bp_hybrid(crepe, bp_events)
        merged, _ = fill_gaps(
            base,
            fs_notes(fs_events, 0.0, conf),
            min_confidence=minimum,
            gap_tolerance=gap,
            onset_shift=shift,
        )
        return merged
    if name == "fssel":
        replace, crepe_max, drop = (float(p) for p in parts[1:4])
        line = select_line(crepe, fs, replace, crepe_max, drop)
        if len(parts) > 4:
            minimum, gap = float(parts[4]), float(parts[5])
            line, _ = fill_gaps(
                line,
                fs_notes(fs_events, 0.0, conf),
                min_confidence=minimum,
                gap_tolerance=gap,
                onset_shift=shift,
            )
        return line
    raise ValueError(variant)


ARGS = argparse.Namespace(fs_shift=0.0)

# Which horns a routed variant applies to (`<route>/<variant>`, `horns`):
# every saxophone, or alto and tenor only -- the soprano read worse on the
# tuning subset (2 solos, -0.059) and the paper says the model struggles in
# the altissimo. A route ending in "bph" gives every other horn the Basic
# Pitch hybrid; otherwise they keep CREPE's line.
ROUTES = {
    "sax": frozenset({"as", "ts", "ss", "bs"}),
    "at": frozenset({"as", "ts"}),
}


def plays(key: str, fits: dict, instruments: frozenset) -> bool:
    """Whether a horn run is played on one of `instruments`. WJazzD says
    which horn (its fit's `instrument`; a guitar solo is not a horn at all);
    every other horn in the benchmark is an alto or a tenor -- Art Pepper and
    Charlie Parker on alto, Dexter Gordon, Hank Mobley and Wayne Shorter on
    tenor."""
    if run_eval.track_of(key).startswith("wjazzd/"):
        solos = fits.get(key) or []
        return bool(solos) and all(s["instrument"] in instruments for s in solos)
    return True


def instrument_rows(card: dict, base: dict, keys: list[str]) -> list[dict]:
    """WJazzD note F1 and recall by the soloist's instrument, paired."""
    from swingscribe.evaluation import paired_change

    w, bw = card["wjazz"], base["wjazz"]
    groups: dict[str, list[str]] = {}
    for k in keys:
        if k in w and k in bw:
            groups.setdefault(bw[k]["instrument"], []).append(k)
    rows = []
    for instrument, ks in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        row = {"instrument": instrument, "n": len(ks)}
        for field in ("note_f1", "note_recall", "note_precision"):
            row[field] = statistics.fmean(w[k][field] for k in ks)
            row[f"{field}_base"] = statistics.fmean(bw[k][field] for k in ks)
        row["change"] = paired_change(
            [bw[k]["note_f1"] for k in ks],
            [w[k]["note_f1"] for k in ks],
            [run_eval.track_of(k) for k in ks],
            tolerance=run_eval.TOLERANCE,
        )
        rows.append(row)
    return rows


def horns(args) -> None:
    use_snapshot(args.snapshot)
    ARGS.fs_shift = args.fs_shift
    manifest = load_manifest(args.out)
    runs = load_runs(manifest)
    keys = sorted(manifest)
    fits, scores = fixed_references(args, runs, keys)
    meta = {k: ("piano" if manifest[k]["piano"] else "horn") for k in keys}
    if args.subset == "tuning":
        keys = [
            k for k in keys if not run_eval.is_located(k) and fb.is_tuning(run_eval.track_of(k))
        ]
        args.wjazz_only = True
    crepe_of = {k: crepe_notes(runs[k]) for k in keys}
    base = fb.score_variant("crepe", crepe_of, fits, scores, args, runs)
    if args.check:
        fb.check_against_pins(base)
    fs = load_json(Path(args.fs), {}) if args.fs else {}
    bp = load_json(Path(args.bp), {}).get("notes", {}) if args.bp else {}
    against = {"crepe": base}
    if bp:
        notes = {
            k: crepe_of[k] if manifest[k]["piano"] else bp_hybrid(crepe_of[k], bp.get(k, []))
            for k in keys
        }
        against["bph"] = fb.score_variant("bph@round1", notes, fits, scores, args, runs)
    results = []
    tag = Path(args.fs).stem if args.fs else "none"
    for variant in [v for v in args.variants.split(",") if v]:
        # A pianist keeps the default take in every variant: a saxophone
        # model vouches for nothing on a piano, and a horn change must not
        # cost a pianist anything. `sax/<variant>` applies the variant to
        # saxophones only and keeps CREPE's line on every other horn;
        # `saxbph/<variant>` gives the other horns the Basic Pitch hybrid;
        # `at` and `atbph` the same for alto and tenor (ROUTES).
        route, _, inner = variant.rpartition("/")
        fallback_bph = route.endswith("bph")
        instruments = ROUTES[route.removesuffix("bph")] if route else None
        notes = {}
        for k in keys:
            if manifest[k]["piano"]:
                notes[k] = crepe_of[k]
            elif instruments is not None and not plays(k, fits, instruments):
                notes[k] = bp_hybrid(crepe_of[k], bp[k]) if fallback_bph else crepe_of[k]
            else:
                notes[k] = horn_variant(inner, crepe_of[k], fs.get(k, []), bp.get(k, []))
        label = f"{variant}@{tag}~shift{args.fs_shift:+.3f}"
        card = fb.score_variant(label, notes, fits, scores, args, runs)
        for name, reference in against.items():
            summary = fb.summarise(f"{label} vs {name}", card, reference, meta)
            summary["instruments"] = instrument_rows(card, reference, sorted(reference["wjazz"]))
            fb.print_summary(summary)
            print("  by instrument (F1 variant/base, R variant/base):")
            for row in summary["instruments"]:
                print(
                    f"    {row['instrument']:<6s} n={row['n']:2d}  F1 {row['note_f1']:.4f}/"
                    f"{row['note_f1_base']:.4f}  R {row['note_recall']:.3f}/"
                    f"{row['note_recall_base']:.3f}  {fb.fmt_change(row['change'])}"
                )
            results.append(summary)
    if args.summary:
        existing = load_json(args.summary, [])
        done = {s["variant"] for s in results}
        merged = [s for s in existing if s["variant"] not in done] + fb.jsonable(results)
        save_json(args.summary, merged)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    i = sub.add_parser("infer", help="run a checkpoint over the manifest's regions")
    i.add_argument("--model", choices=("kong", "edwards", "filosax"), required=True)
    i.add_argument("--which", choices=("piano", "horn", "all"), required=True)
    i.add_argument("--device", default="cpu")
    i.add_argument("--threads", type=int, default=4)
    i.add_argument("--batch", type=int, default=1)
    i.add_argument("--check16", type=int, default=3, help="regions to check float16 on")
    c = sub.add_parser("crepe", help="the pianists' CREPE line before the oracle")
    c.add_argument("--device", default="cpu")
    c.add_argument("--source", choices=("reviews", "crepe"), default="reviews")
    c.add_argument("--snapshot", type=Path, required=True)
    d = sub.add_parser("decode", help="decode stored rolls at other thresholds")
    d.add_argument("--model", required=True)
    d.add_argument("--onset", type=float, default=0.3)
    d.add_argument("--frame", type=float, default=0.1)
    d.add_argument("--jobs", type=int, default=3)
    p = sub.add_parser("pianists", help="Edwards against the pipeline's checkpoint")
    h = sub.add_parser("horns", help="the FiloSax model against CREPE and the hybrid")
    for s in (p, h):
        s.add_argument("--db", type=Path, default=Path("wjazz/wjazzd.db"))
        s.add_argument("--snapshot", type=Path, required=True)
        s.add_argument("--jobs", type=int, default=3)
    h.add_argument("--fs", default=None, help="decoded FiloSax notes (decode's output)")
    h.add_argument("--bp", default=None, help="round one's Basic Pitch notes, for the hybrid")
    h.add_argument("--fs-shift", type=float, default=0.0, help="seconds added to model onsets")
    h.add_argument("--variants", default="")
    h.add_argument("--subset", choices=("all", "tuning"), default="all")
    h.add_argument("--wjazz-only", action="store_true")
    h.add_argument("--notation", action="store_true")
    h.add_argument("--check", action="store_true")
    h.add_argument("--summary", type=Path, default=None)
    for s in (i, c, d, p, h):
        s.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    {"infer": infer, "crepe": crepe, "decode": decode, "pianists": pianists, "horns": horns}[
        args.command
    ](args)
    print(f"({time.time() - started:.0f}s)")


if __name__ == "__main__":
    main()
