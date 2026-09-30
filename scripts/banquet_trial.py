"""Banquet, query-by-audio separation, as a routing-free soloist stem: a trial.

    .venv\\Scripts\\python.exe scripts/banquet_trial.py manifest --db wjazz/wjazzd.db --out DIR
    .venv\\Scripts\\python.exe scripts/banquet_trial.py probes --out DIR --ids m61,m70  # optional
    wsl -- bash -lc '~/banquet/.venv/bin/python scripts/banquet_wsl.py infer ...'
    .venv\\Scripts\\python.exe scripts/banquet_trial.py score --db wjazz/wjazzd.db --out DIR
    .venv\\Scripts\\python.exe scripts/banquet_trial.py probes --out DIR --ids ... --report

The 2026-09-30 run and its verdict (not worth a full evaluation: note F1
0.853 -> 0.562 over 16 spans, every one down) are in docs/banquet-trial.md.

docs/separation-research.md (2026-09-01) ranked Banquet (Watcharasupat and
Lerch, ISMIR 2024: a band-split separator with ONE decoder, conditioned on a
PaSST embedding of a query clip, trained on MoisesDB, whose taxonomy has reed,
brass and wind stems) "the strongest lead" and never ran it. The idea: a few
seconds of the soloist as the QUERY returns that instrument's stem, which
could retire stem routing (D23) and the soloist-leaves-the-stem failure (R16,
Oleo's muted trumpet in `vocals`). This asks whether it is worth a full
evaluation, against the stem that ships: BS-Roformer-SW's `other`.

## Three steps, two machines

Banquet imports librosa (numba) and pytorch_lightning, so it runs in WSL, in
a venv of its own (`scripts/banquet_wsl.py`, whose docstring has the setup).
This script does both ends:

1. `manifest` takes the trial set (below), resolves each span's ingest wav
   and Roformer `other` stem the way `run_eval` does (the sidecar's model,
   `library.ingested_document` + `library.resolve_stem`, the batch cache),
   writes a crop of the ingest wav over the span plus the separate stage's
   3 s margin (`SeparateConfig.span_margin_s`, the Roformer's own crop), and
   cuts each query clip. Nothing is transcribed.
2. `banquet_wsl.py infer` separates each crop with each query.
3. `score` pads each Banquet stem back to the track's time base (zeros
   outside the crop, `separate._pad_stem_to_track`, exactly as a span-scoped
   Roformer set is written), transcribes it with the harness's own CREPE path
   (`transcribe.analyze` under `run_eval.transcribe_settings`), and scores it
   against WJazzD with `score_wjazz.score` beside the Roformer run.

## The query, chosen without the answer

`self`: the 6 s of the span in which the ROFORMER `other` stem is loudest --
the window with the highest MEDIAN frame level (50 ms frames, 0.25 s steps,
the span's outer second on each side excluded), so a held, sustained
stretch wins over one loud attack. It reads our own audio only, never the
annotation. It is also what the product could do: the listener's selection
and a separation already on disk. The model was trained on 10 s queries;
`banquet_wsl.py` tiles a 6 s clip to 10 s exactly as the authors'
`inference_byoq` does.

`cross`: the `self` clip of ANOTHER trial recording with the same WJazzD
instrument code (a different performer where one exists, else the same
player on another tune; lowest melid breaks ties). It asks whether an
instrument LIBRARY -- the listener names "tenor", the app supplies a tenor
clip -- would do, which is the version of Banquet that needs no separator
at all before it.

## What is held fixed

- **The fit.** Every stem is scored under the Roformer run's own
  `identify_all` fit (frontend_bakeoff's rule and code), so the same solo,
  offset and rate are scored on both sides.
- **The transcriber.** The Roformer side is the harness's cached run when
  its fingerprint (`run_eval.transcribe_fingerprint`, the whole resolved
  TranscribeConfig plus `transcribe.CACHE_VERSION`) matches what this
  process would compute; otherwise it is re-transcribed here, so both sides
  always come from the same code. `--notes` points at a SNAPSHOT of the
  harness cache: another workflow may be rewriting the live one. While the
  working tree's transcriber is mid-change, put a `git archive` of a commit
  on PYTHONPATH (`card.json` records which `swingscribe` was imported); the
  2026-09-30 run used 0049aee, whose fingerprints match all 74 WJazzD runs
  of the pre-hybrid snapshot.
- **The set.** Dev split only (every WJazzD track in `benchmark/` is dev).

The trial set is named here, not chosen from scores: the routing-trouble
solos of docs/separation-research.md and D23, and the first six of that
doc's fixed separator-judging subset (`--ordinary` takes more of it).

Every change is `swingscribe.evaluation.paired_change`: paired by track, a
95% bootstrap interval resampled by recording (the ingest wav's digest, so
two solos cut from one file are one draw), and up/down counts and a sign
test over recordings at the harness's tolerance (`run_eval.TOLERANCE`).
`stem_dropout` (R16's check: the share of 1 s bins that are digital
silence), a quiet share (bins 40 dB under the stem's in-span 95th
percentile) and the stem's in-span level beside the mix's are reported for
every stem: a mask-based separator that finds nothing to extract comes back
nearly silent, which only the level shows for what it is.

Nothing this writes may enter the repo: the audio and notes are derived from
commercial recordings. Everything lands under `--out` (a scratch folder).
"""

from __future__ import annotations

import argparse
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
STEP_COST, DIP_DB = 0.2, 0.0  # the harness's default decode (its cache name)

# The routing-trouble solos: every horn the 2026-09-01 batch mis-routed on
# htdemucs_6s (D23: under `guitar` or `vocals`, or switched between stems
# mid-solo), R16's Oleo, and the two docs/separation-research.md adds.
ROUTING = (61, 399, 320, 446, 447, 427, 434, 228, 397, 375)
# docs/separation-research.md "How every candidate gets judged": the fixed
# subset every separator has been scored on, in that doc's order.
FIXED_SUBSET = (54, 70, 56, 58, 168, 218, 60, 74, 385, 121, 226, 231)

QUERY_SECONDS = 6.0
QUERY_STEP_S = 0.25
FRAME_S, HOP_S = 0.05, 0.025
EDGE_S = 1.0  # the span's outer second either side is never a query
QUIET_DB = 40.0  # a 1 s bin this far under the stem's in-span 95th pct is "quiet"
CONDITIONS = ("self", "cross")


def trial_melids(ordinary: int) -> list[tuple[int, str]]:
    return [(m, "routing") for m in ROUTING] + [(m, "ordinary") for m in FIXED_SUBSET[:ordinary]]


def sidecars_by_melid() -> dict[int, tuple[str, dict]]:
    out = {}
    for path in sorted(run_eval.BENCH.rglob("*.swingscribe.json")):
        sidecar = json.loads(path.read_text(encoding="utf-8"))
        melids = sidecar.get("melids") or ([sidecar["melid"]] if sidecar.get("melid") else [])
        if len(melids) == 1:
            out[int(melids[0])] = (run_eval.sidecar_name(path, sidecar), sidecar)
    return out


def config_for(sidecar: dict):
    settings = run_eval.transcribe_settings(sidecar, STEP_COST, DIP_DB)
    base = run_eval.eval_config()
    return base.model_copy(
        update={
            "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
            "transcribe": settings,
        }
    ), settings


# ── 1. manifest ──────────────────────────────────────────────────────────────


def loudest_window(
    path: str, region: tuple[float, float], seconds: float = QUERY_SECONDS
) -> tuple[float, float, float]:
    """(start, end, median dB) of the `seconds` window of `region` in which
    the stem's median 50 ms frame level is highest (module docstring)."""
    import numpy as np
    import soundfile

    info = soundfile.info(path)
    rate = info.samplerate
    lo, hi = region[0] + EDGE_S, region[1] - EDGE_S
    data, _ = soundfile.read(
        path, dtype="float32", always_2d=True, start=int(lo * rate), stop=int(hi * rate)
    )
    mono = data.mean(axis=1)
    frame, hop = int(FRAME_S * rate), int(HOP_S * rate)
    frames = np.lib.stride_tricks.sliding_window_view(mono, frame)[::hop]
    level = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    width = int(round(seconds / HOP_S))
    step = int(round(QUERY_STEP_S / HOP_S))
    if len(level) < width:
        raise ValueError(f"{path}: region {region} is shorter than a query")
    medians = np.median(np.lib.stride_tricks.sliding_window_view(level, width)[::step], axis=1)
    best = int(np.argmax(medians))
    start = lo + best * step * HOP_S
    return start, start + seconds, float(medians[best])


def write_clip(path: str, start: float, end: float, out: Path) -> tuple[int, int]:
    """[start, end] of `path` as 16-bit PCM (the separate stage's crop format).
    Returns (offset_samples, total_samples) for padding a result back."""
    import soundfile

    info = soundfile.info(path)
    rate = info.samplerate
    a = max(0, int(start * rate))
    b = min(info.frames, int(end * rate))
    data, _ = soundfile.read(path, dtype="float32", always_2d=True, start=a, stop=b)
    out.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(str(out), data, rate, subtype="PCM_16")
    return a, info.frames


def cross_source(entry: dict, entries: dict) -> str | None:
    """The trial recording whose self query stands in for an instrument
    library: same instrument code, another tune, a different performer where
    one exists, lowest melid breaking ties (module docstring)."""
    others = [
        e
        for e in entries.values()
        if e["instrument"] == entry["instrument"]
        and e["title"] != entry["title"]
        and e["digest"] != entry["digest"]
    ]
    if not others:
        return None
    others.sort(key=lambda e: (e["performer"] == entry["performer"], e["melid"]))
    return others[0]["key"]


def manifest(args) -> None:
    import sqlite3

    from swingscribe.gui import library

    run_eval.CACHE_DIR = BATCH_CACHE
    from swingscribe.config import Config

    margin = Config().separate.span_margin_s
    db = sqlite3.connect(args.db)
    runs = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    by_melid = sidecars_by_melid()
    out = args.out
    entries: dict[str, dict] = {}
    for melid, group in trial_melids(args.ordinary):
        if melid not in by_melid:
            print(f"  melid {melid}: no sidecar in benchmark/ -- skipped")
            continue
        key, sidecar = by_melid[melid]
        if key not in runs:
            print(f"  {key}: no cached run in {args.notes} -- skipped")
            continue
        config, settings = config_for(sidecar)
        if settings.uses_piano_oracle:
            print(f"  {key}: routed to the piano oracle, not a horn -- skipped")
            continue
        document = library.ingested_document(run_eval.BENCH / key, config)
        stem = library.resolve_stem(document, config, sidecar["model"], settings.stem)
        if stem is None:
            print(f"  {key}: no {settings.stem!r} stem for {sidecar['model']} -- skipped")
            continue
        performer, title, instrument = db.execute(
            "select performer, title, instrument from solo_info where melid=?", (melid,)
        ).fetchone()
        region = tuple(runs[key]["region"])
        ident = f"m{melid}"
        mix = out / "mix" / f"{ident}.wav"
        offset, total = write_clip(document.audio.path, region[0] - margin, region[1] + margin, mix)
        q0, q1, q_db = loudest_window(stem, region)
        query = out / "queries" / f"{ident}.wav"
        write_clip(stem, q0, q1, query)
        entries[key] = {
            "id": ident,
            "key": key,
            "melid": melid,
            "group": group,
            "performer": performer,
            "title": title,
            "instrument": instrument,
            "digest": library.stem_digest(document),
            "region": list(region),
            "mix": str(mix.resolve()),
            "mix_offset": offset,
            "track_frames": total,
            "roformer": str(Path(stem).resolve()),
            "query_window": [round(q0, 3), round(q1, 3)],
            "query_median_db": round(q_db, 1),
            "queries": {"self": str(query.resolve())},
        }
        print(
            f"  {key}: {group} {instrument} span {region[0]:.1f}-{region[1]:.1f}s, "
            f"query {q0:.1f}-{q1:.1f}s ({q_db:.1f} dB)"
        )
    for entry in entries.values():
        source = cross_source(entry, entries)
        entry["cross_from"] = source
        entry["queries"]["cross"] = entries[source]["queries"]["self"] if source else None
    write_manifests(out, entries)
    groups = [e["group"] for e in entries.values()]
    print(
        f"\n{len(entries)} spans ({groups.count('routing')} routing, "
        f"{groups.count('ordinary')} ordinary) -> {out / 'manifest.json'}"
    )


def write_manifests(out: Path, entries: dict) -> None:
    """manifest.json, and the same with /mnt/c paths for the WSL half."""
    wsl = {
        k: {
            **e,
            "mix": wsl_path(e["mix"]),
            "queries": {q: wsl_path(p) if p else None for q, p in e["queries"].items()},
        }
        for k, e in entries.items()
    }
    (out / "manifest.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    (out / "manifest-wsl.json").write_text(json.dumps(wsl, indent=1), encoding="utf-8")


def wsl_path(path: str) -> str:
    """C:\\Users\\... -> /mnt/c/Users/..."""
    if len(path) > 2 and path[1] == ":":
        return "/mnt/" + path[0].lower() + path[2:].replace("\\", "/")
    return path


# ── the sanity probe ─────────────────────────────────────────────────────────


def probes(args) -> None:
    """Is the MACHINERY right, whatever the horn result? Ask the same model
    for sources it was certainly trained on -- drums and bass, MoisesDB's
    commonest stems -- with a query cut the self query's way from the
    Roformer's OWN drums/bass stem of the same span, and measure the answer
    against that Roformer stem (scale-invariant SDR over the span; the
    Roformer is a pseudo-reference, so this says "found the same source",
    not "separated it well"). A run that returns the drums at the drums'
    level while returning the horn 60 dB down has a model problem, not a
    plumbing one. `--report` prints the table from what the WSL half wrote.

    `--stems other --seconds 10 --name self10` cuts the answer to the other
    objection -- "you tiled a 6 s query; the model was trained on 10 s" -- as
    a condition of its own, scored like `self` by `score --conditions`.
    """
    entries = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))
    chosen = [k for k, e in entries.items() if e["id"] in args.ids.split(",")]
    stems = args.stems.split(",")
    if args.report:
        probe_report(args, entries, chosen)
        return
    for key in chosen:
        entry = entries[key]
        for stem in stems:
            source = Path(entry["roformer"]).with_name(f"{stem}.wav")
            if not source.is_file():
                print(f"  {key}: no Roformer {stem} stem")
                continue
            name = args.name or f"probe-{stem}"
            q0, q1, q_db = loudest_window(str(source), tuple(entry["region"]), args.seconds)
            clip = args.out / "queries" / f"{entry['id']}-{name}.wav"
            write_clip(str(source), q0, q1, clip)
            entry["queries"][name] = str(clip.resolve())
            entry.setdefault("probe_windows", {})[name] = [round(q0, 3), round(q1, 3)]
            print(f"  {key}: {name} query from {stem}, {q0:.1f}-{q1:.1f}s ({q_db:.1f} dB)")
    write_manifests(args.out, entries)


def reference_stem(condition: str) -> str:
    """The Roformer stem a condition's answer is measured against: the probe's
    own stem, else `other` (every horn query asks for the soloist)."""
    return condition.removeprefix("probe-") if condition.startswith("probe-") else "other"


def si_sdr(estimate, reference) -> float:
    """Scale-invariant SDR (dB) of mono `estimate` against mono `reference`."""
    import numpy as np

    reference = reference - reference.mean()
    estimate = estimate - estimate.mean()
    alpha = (estimate @ reference) / max(reference @ reference, 1e-20)
    target = alpha * reference
    noise = estimate - target
    return float(10 * np.log10(max(target @ target, 1e-20) / max(noise @ noise, 1e-20)))


def probe_report(args, entries: dict, chosen: list[str]) -> None:
    import numpy as np
    import soundfile

    def span(path: str, entry: dict, cropped: bool):
        info = soundfile.info(path)
        rate = info.samplerate
        shift = entry["mix_offset"] / rate if cropped else 0.0
        a, b = (int((t - shift) * rate) for t in entry["region"])
        data, _ = soundfile.read(path, dtype="float64", always_2d=True, start=a, stop=b)
        return data

    def db(x) -> float:
        """Over every channel, as `span_level` measures it for the scorecard."""
        return float(20 * np.log10(np.sqrt((x**2).mean()) + 1e-12))

    conditions = sorted(p.name for p in (args.out / "banquet").iterdir() if p.is_dir())
    report = {}
    print(
        f"{'id':6} {'condition':12} {'vs stem':7} {'Banquet dB':>10} {'Roformer dB':>11} "
        f"{'SI-SDR vs Roformer':>19}"
    )
    for key in chosen:
        entry = entries[key]
        mix = span(entry["mix"], entry, True)
        print(f"{entry['id']:6} {'(the mix)':12} {'':7} {db(mix):10.1f}")
        report[key] = {"mix_db": db(mix)}
        for condition in conditions:
            stem = reference_stem(condition)
            est_path = args.out / "banquet" / condition / f"{entry['id']}.wav"
            if not est_path.is_file():
                continue
            est = span(str(est_path), entry, True)
            ref = span(str(Path(entry["roformer"]).with_name(f"{stem}.wav")), entry, False)
            n = min(len(est), len(ref))
            row = {"stem": stem, "banquet_db": db(est), "roformer_db": db(ref)}
            row["si_sdr"] = si_sdr(est[:n].mean(axis=1), ref[:n].mean(axis=1))
            report[key][condition] = row
            print(
                f"{entry['id']:6} {condition:12} {stem:7} {row['banquet_db']:10.1f} "
                f"{row['roformer_db']:11.1f} {row['si_sdr']:19.1f}"
            )
    (args.out / "probes.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


# ── 2. transcription ────────────────────────────────────────────────────────


def padded(entry: dict, estimate: Path, out: Path) -> Path:
    """The Banquet crop as a full-length 16-bit wav in the track's time base:
    zeros, then the crop at its offset -- the separate stage's own padding."""
    import shutil

    from swingscribe.stages.separate import _pad_stem_to_track

    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(estimate, out)
    _pad_stem_to_track(out, entry["mix_offset"], entry["track_frames"])
    return out


def transcribe_stem(path: str, sidecar: dict, device: str | None) -> dict:
    from swingscribe.stages import transcribe

    settings = run_eval.transcribe_settings(sidecar, STEP_COST, DIP_DB)
    if device:
        settings = settings.model_copy(update={"device": device})
    started = time.time()
    notes, diagnostics = transcribe.analyze(path, settings)
    return {
        "seconds": round(time.time() - started, 1),
        "voiced_fraction": diagnostics.voiced_fraction,
        "notes": [
            {"onset": n.onset, "duration": n.duration, "pitch": n.pitch, "confidence": n.confidence}
            for n in notes
        ],
    }


def soundfile_rate(path: str) -> int:
    import soundfile

    return soundfile.info(path).samplerate


def quiet_share(path: str, region: tuple[float, float]) -> float:
    """Share of the region's 1 s bins QUIET_DB or more under the stem's own
    95th-percentile bin: the near-silence a mask-based separator leaves where
    `stem_dropout`'s bit-zero test sees none."""
    import numpy as np
    import soundfile

    info = soundfile.info(path)
    rate = info.samplerate
    data, _ = soundfile.read(
        path,
        dtype="float32",
        always_2d=True,
        start=int(region[0] * rate),
        stop=int(min(region[1], info.duration) * rate),
    )
    mono = data.mean(axis=1)
    bins = len(mono) // rate
    if bins < 1:
        return 0.0
    rms = np.sqrt((mono[: bins * rate].reshape(bins, rate) ** 2).mean(axis=1))
    level = 20 * np.log10(rms + 1e-9)
    return float((level < np.percentile(level, 95) - QUIET_DB).mean())


def span_level(path: str, region: tuple[float, float], shift_s: float = 0.0) -> float:
    """RMS level of `path` over `region` (seconds of the TRACK; `shift_s` is
    where the file starts in the track), dBFS. A mask-based separator that
    finds nothing to extract returns the mixture scaled almost to zero, which
    this shows as a level 60-80 dB under the mix where `stem_dropout` only
    says "silent"."""
    import numpy as np
    import soundfile

    info = soundfile.info(path)
    rate = info.samplerate
    start = max(0, int((region[0] - shift_s) * rate))
    stop = min(info.frames, int((region[1] - shift_s) * rate))
    data, _ = soundfile.read(path, dtype="float64", always_2d=True, start=start, stop=stop)
    return float(20 * np.log10(np.sqrt((data**2).mean()) + 1e-12))


def notes_for(args, entries: dict, sidecars: dict) -> dict[str, dict[str, list]]:
    """variant -> key -> notes. Cached under --out per variant; a Banquet
    variant's cache entry carries the fingerprint of the code that made it."""
    from swingscribe.gui import library

    snapshot = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    variants: dict[str, dict[str, list]] = {"roformer": {}}
    extra: dict[str, dict] = {}
    for condition in args.conditions:
        cache_path = args.out / f"notes-{condition}.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
        variants[condition] = {}
        for key, entry in sorted(entries.items()):
            estimate = args.out / "banquet" / condition / f"{entry['id']}.wav"
            if not estimate.is_file():
                continue
            wanted = run_eval.transcribe_fingerprint(sidecars[key], STEP_COST, DIP_DB)
            # A re-separated estimate is new input: its size and mtime key it.
            stat = estimate.stat()
            made = [stat.st_size, int(stat.st_mtime)]
            cached = cache.get(key)
            if (
                cached is None
                or cached.get("fingerprint") != wanted
                or cached.get("estimate") != made
            ):
                full = padded(
                    entry, estimate, args.out / "padded" / condition / f"{entry['id']}.wav"
                )
                run = transcribe_stem(str(full), sidecars[key], args.device)
                region = tuple(entry["region"])
                run.update(
                    fingerprint=wanted,
                    estimate=made,
                    dropout=library.stem_dropout(full, region),
                    quiet=quiet_share(str(full), region),
                )
                full.unlink()
                cache[key] = run
                cache_path.write_text(json.dumps(cache), encoding="utf-8")
                print(f"  {condition} {key}: {len(run['notes'])} notes in {run['seconds']:.0f}s")
            variants[condition][key] = cache[key]["notes"]
            rate = soundfile_rate(entry["mix"])
            extra.setdefault(key, {})[condition] = {
                **{k: cache[key][k] for k in ("dropout", "quiet", "voiced_fraction")},
                "level_db": span_level(
                    str(estimate), tuple(entry["region"]), entry["mix_offset"] / rate
                ),
            }
    # The Roformer side: the snapshot's run where the fingerprint says it is
    # what this code would compute, else transcribed here (module docstring).
    cache_path = args.out / "notes-roformer.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    for key, entry in sorted(entries.items()):
        wanted = run_eval.transcribe_fingerprint(sidecars[key], STEP_COST, DIP_DB)
        region = tuple(entry["region"])
        snap = snapshot.get(key)
        if snap is not None and snap.get("fingerprint") == wanted and not args.retranscribe:
            notes, source = snap["notes"], "snapshot"
        else:
            cached = cache.get(key)
            if cached is None or cached.get("fingerprint") != wanted:
                cached = transcribe_stem(entry["roformer"], sidecars[key], args.device)
                cached["fingerprint"] = wanted
                cache[key] = cached
                cache_path.write_text(json.dumps(cache), encoding="utf-8")
                print(f"  roformer {key}: re-transcribed, {len(cached['notes'])} notes")
            notes, source = cached["notes"], "here"
        variants["roformer"][key] = notes
        extra.setdefault(key, {})["roformer"] = {
            "dropout": library.stem_dropout(entry["roformer"], region),
            "quiet": quiet_share(entry["roformer"], region),
            "level_db": span_level(entry["roformer"], region),
            "source": source,
        }
        extra[key]["mix_db"] = span_level(
            entry["mix"], region, entry["mix_offset"] / soundfile_rate(entry["mix"])
        )
    args.extra = extra
    return variants


# ── 3. scoring ───────────────────────────────────────────────────────────────


def score(args) -> None:
    import frontend_bakeoff

    from swingscribe.evaluation import paired_change

    run_eval.CACHE_DIR = BATCH_CACHE
    entries = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))
    by_melid = sidecars_by_melid()
    sidecars = {key: by_melid[e["melid"]][1] for key, e in entries.items()}
    if args.device == "cpu":
        import torch

        torch.set_num_threads(args.threads)
    variants = notes_for(args, entries, sidecars)

    # CREPE-on-Roformer's fit of each annotated solo, held fixed for every
    # variant (frontend_bakeoff's rule and function).
    fits_path = args.out / "fits.json"
    fits = json.loads(fits_path.read_text(encoding="utf-8")) if fits_path.is_file() else {}
    missing = [k for k in sorted(entries) if k not in fits]
    if missing:
        tasks = [(k, variants["roformer"][k], entries[k]["region"], str(args.db)) for k in missing]
        for key, found in zip(
            missing, run_eval.parallel_map(frontend_bakeoff._fit_one, tasks, args.jobs), strict=True
        ):
            fits[key] = found
        fits_path.write_text(json.dumps(fits), encoding="utf-8")

    card: dict[str, dict] = {}
    for name, notes_of in variants.items():
        tasks = [(k, fits[k], notes_of[k]) for k in sorted(notes_of) if fits.get(k)]
        card[name] = {}
        for part in run_eval.parallel_map(frontend_bakeoff._wjazz_one, tasks, args.jobs):
            for row, result in part.items():
                card[name][row] = {
                    k: result[k]
                    for k in ("note_f1", "note_precision", "note_recall", "n_ref", "n_est")
                }

    pins = json.loads(Path(args.pins).read_text(encoding="utf-8")) if args.pins else {}
    rows = []
    for key, entry in sorted(entries.items(), key=lambda kv: (kv[1]["group"], kv[1]["melid"])):
        if not fits.get(key):
            print(f"  {key}: the Roformer run found no annotated solo -- not scored")
            continue
        pin = pins.get(f"wjazz/{run_eval.pin_name(key)}/note_f1")
        rows.append((key, entry, pin))
    print_table(rows, card, args.extra, args.conditions)
    # The control: the Roformer side must reproduce the pinned note F1.
    pinned = [(card["roformer"][k]["note_f1"], p) for k, _, p in rows if p is not None]
    if pinned:
        worst = max(abs(a - b) for a, b in pinned)
        print(f"\ncontrol: Roformer note F1 vs the pins, {len(pinned)} rows, worst |d| {worst:.4f}")

    import swingscribe

    report = {
        "card": card,
        "extra": args.extra,
        "changes": {},
        # Which transcriber made the notes: a checkout of a commit on
        # PYTHONPATH pins it while the working tree moves (docs/banquet-trial.md).
        "code": {"swingscribe": swingscribe.__file__, "run_eval": run_eval.__file__},
    }
    for group in ("routing", "ordinary", "all"):
        chosen = [(k, e) for k, e, _ in rows if group == "all" or e["group"] == group]
        for condition in args.conditions:
            paired = [(k, e) for k, e in chosen if k in card[condition]]
            if not paired:
                continue
            for field in ("note_f1", "note_precision", "note_recall"):
                before = [card["roformer"][k][field] for k, _ in paired]
                after = [card[condition][k][field] for k, _ in paired]
                change = paired_change(
                    before,
                    after,
                    [e["digest"] for _, e in paired],
                    tolerance=run_eval.TOLERANCE,
                )
                report["changes"][f"{group}/{condition}/{field}"] = {
                    "before": statistics.fmean(before),
                    "after": statistics.fmean(after),
                    **change.__dict__,
                }
                print(
                    f"{group:8s} {condition:6s} {field:15s} n={change.n:2d} "
                    f"{statistics.fmean(before):.3f} -> {statistics.fmean(after):.3f}  "
                    f"{change.mean:+.4f} [{change.low:+.4f}, {change.high:+.4f}]  "
                    f"up {change.up} / down {change.down}  p={change.p:.3f}"
                )
    (args.out / "card.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n-> {args.out / 'card.json'}")


def print_table(rows, card, extra, conditions) -> None:
    """One row per span: note F1 (P/R) per variant, then R16's dropout, the
    quiet share and the in-span level (dB) of each stem, the Roformer first."""
    variants = ["roformer", *conditions]
    print(
        f"\n{'melid':>5} {'grp':4} {'ins':3} "
        + " ".join(f"{v + ' F1 (P/R)':>20}" for v in variants)
        + f"   dropout, quiet, level dB ({' / '.join(variants)}; mix level)   pin"
    )

    def cell(name: str, key: str) -> str:
        r = card.get(name, {}).get(key)
        if r is None:
            return f"{'-':>20}"
        return f"{r['note_f1']:.3f} ({r['note_precision']:.2f}/{r['note_recall']:.2f})".rjust(20)

    def share(key: str, field: str, fmt: str = ".2f", blank: str = "  - ") -> str:
        return "/".join(
            format(extra[key][v][field], fmt) if v in extra.get(key, {}) else blank
            for v in variants
        )

    for key, entry, pin in rows:
        mix = extra.get(key, {}).get("mix_db")
        mix = "  -  " if mix is None else f"{mix:5.1f}"
        levels = share(key, "level_db", "5.1f", "  -  ")
        print(
            f"{entry['melid']:>5} {entry['group'][:4]:4} {entry['instrument']:3} "
            + " ".join(cell(v, key) for v in variants)
            + f"   {share(key, 'dropout')}  {share(key, 'quiet')}  {levels}; {mix}"
            + f"   {'' if pin is None else f'{pin:.3f}'}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--db", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument(
        "--notes", type=Path, default=NOTES_CACHE, help="a SNAPSHOT of the harness cache"
    )
    m.add_argument("--ordinary", type=int, default=6, help="how many of the fixed subset")
    s = sub.add_parser("score")
    s.add_argument("--db", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument(
        "--notes", type=Path, default=NOTES_CACHE, help="a SNAPSHOT of the harness cache"
    )
    s.add_argument("--pins", type=Path, default=None, help="real-audio-baselines.json, a control")
    s.add_argument("--device", default=None, help="CREPE's device: cuda | cpu (default: auto)")
    s.add_argument("--threads", type=int, default=4, help="torch threads on cpu")
    s.add_argument("--jobs", type=int, default=4)
    s.add_argument(
        "--retranscribe", action="store_true", help="re-run CREPE on the Roformer stem too"
    )
    s.add_argument(
        "--conditions",
        default=",".join(CONDITIONS),
        help="the Banquet runs to transcribe and score, e.g. self,cross,self10",
    )
    p = sub.add_parser("probes")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ids", required=True, help="comma-separated manifest ids, e.g. m61,m375")
    p.add_argument("--stems", default="drums,bass", help="Roformer stems to query with")
    p.add_argument("--seconds", type=float, default=QUERY_SECONDS, help="query length")
    p.add_argument("--name", default=None, help="the condition's name (default probe-<stem>)")
    p.add_argument("--report", action="store_true", help="print the table instead")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "score":
        args.conditions = [c for c in args.conditions.split(",") if c]
    if args.command == "manifest":
        manifest(args)
    elif args.command == "probes":
        probes(args)
    else:
        score(args)


if __name__ == "__main__":
    main()
