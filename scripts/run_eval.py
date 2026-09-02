"""One command, one scorecard: everything the pipeline is measured by.

    uv run python scripts/run_eval.py --db wjazz/wjazzd.db
    uv run python scripts/run_eval.py --db wjazz/wjazzd.db --pin

Plan section 7 asks M6 for an eval harness that "prints a scorecard", with
pinned baselines so a change that moves a number has to say so. This is it.

It runs both benchmarks over everything in `benchmark/` that has a sidecar,
transcribes what it must (cached per decode setting, because CREPE on CPU is
a minute a tune), and prints one table. Then it diffs against the pinned
baselines and exits non-zero if anything moved by more than noise.

## Why there are two benchmarks and both are kept

They ask different questions and neither subsumes the other; the full
argument is in `docs/benchmark-deficiencies.md`. Briefly: WJazzD scores our
timestamps against a human's timestamps for the same recording, which is what
`transcribe` should be judged on. MuseScore scores our audio against notated
rhythm, which is what `notate` should be judged on and which necessarily
reads lower, because notation idealizes what was played.

Reporting only the second one is what made the transcriber look worse than it
is for months.

## What "pinned" means here

Real-audio baselines cannot run in CI -- they need the audio, which is never
committed (plan section 12). So this is a pre-merge command, not a test. The
baselines live in `tests/regression/real-audio-baselines.json`, separately
from the synthetic ones in `baselines.json`, which stay sacred and untouched
(CLAUDE.md).

Nothing this reads or writes may be committed except the aggregate numbers.
"""

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

BENCH = Path("benchmark")
BASELINES = Path("tests/regression/real-audio-baselines.json")
# Which stage cache the stems and ingests are read from. The default is the
# repo-root cache the GUI shares when launched from here; `--cache-dir
# benchmark/.swingscribe-cache` reads the batch's, where a span-scoped
# Roformer separation lands (stages/separate.py). Copying 28 GB of stems
# between the two so this could keep one default was the alternative.
CACHE_DIR = Path(".swingscribe-cache")


def eval_config():
    from swingscribe.config import Config

    return Config(cache_dir=CACHE_DIR)


# How far a score may move before it is called a change rather than noise.
# Transcription is deterministic, so this is tight on purpose; it exists for
# floating-point drift across platforms, not for genuine variation.
TOLERANCE = 0.002


def notes_cache(step_cost: float, dip_db: float) -> Path:
    """One cache per decode setting -- they are not interchangeable results."""
    return Path(f".benchmark-notes-c{step_cost}-d{dip_db}.json")


def sidecar_name(sidecar_path: Path, sidecar: dict) -> str:
    """The track's key: its path relative to benchmark/, with forward slashes.

    `sidecar["file"]` is a bare filename, because the sidecar lives beside its
    audio and does not need to say where that is. Once benchmark/ has
    subfolders (benchmark/wjazzd/, added when the library outgrew one flat
    directory) the bare name no longer locates the file, and two tracks in
    different folders could collide on it. Forward slashes so a key pinned on
    Windows matches one pinned anywhere else.
    """
    folder = sidecar_path.parent.relative_to(BENCH)
    name = sidecar.get("file") or sidecar_path.name.removesuffix(".swingscribe.json")
    return name if folder == Path(".") else f"{folder.as_posix()}/{name}"


def transcribe_settings(sidecar: dict, step_cost: float, dip_db: float):
    """The exact TranscribeConfig this sidecar asks for. One definition, used
    both to fingerprint a cached run and to compute a fresh one, so the two can
    never drift apart."""
    from swingscribe.config import Config

    base = Config()
    low, high = sidecar["region"]
    # A null `stem` means the listener never chose one, not that there is no
    # stem: it falls back to the default exactly as `ensemble` does. Without
    # this it reached the filesystem as "None.wav" and the track was skipped -
    # which went unnoticed for as long as a cached run kept answering for it.
    return base.transcribe.model_copy(
        update={
            "stem": sidecar.get("stem") or base.transcribe.stem,
            "region": (low, high),
            "pitch_step_cost": step_cost,
            "onset_dip_db": dip_db,
            "ensemble": sidecar.get("ensemble") or base.transcribe.ensemble,
        }
    )


def transcribe_fingerprint(sidecar: dict, step_cost: float, dip_db: float) -> str:
    """A cached run is reusable only if the transcriber would read the same
    settings AND is the same transcriber. Mirrors pipeline._cache_name: the
    stage's CACHE_VERSION is folded in, so a behaviour change with no config
    change still invalidates."""
    from swingscribe.cache import canonical_json
    from swingscribe.stages import transcribe

    settings = transcribe_settings(sidecar, step_cost, dip_db)
    payload = {
        "version": getattr(transcribe, "CACHE_VERSION", 1),
        "model": sidecar["model"],
        "transcribe": settings.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]


def transcribe_all(cache: Path, step_cost: float, dip_db: float, log=print) -> dict:
    """Transcribe every sidecar'd span in benchmark/, reusing what is cached."""
    from swingscribe.gui import library
    from swingscribe.stages import transcribe

    runs = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    live: set[str] = set()
    for sidecar_path in sorted(BENCH.rglob("*.swingscribe.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        name = sidecar_name(sidecar_path, sidecar)
        if not (BENCH / name).is_file():
            continue
        live.add(name)
        # Re-transcribe when ANYTHING the transcriber reads has changed. The
        # cache filename carries only the two decode settings the sweep varies,
        # so for a long time a change to the stage itself -- a new default, a
        # new step like the piano gap-fill -- silently kept serving notes
        # computed by the old code. That is exactly the staleness hole the
        # pipeline's chained keys exist to close (CLAUDE.md), reintroduced in
        # the harness because this cache is keyed by filename.
        #
        # So the fingerprint is the whole resolved TranscribeConfig plus the
        # stage's CACHE_VERSION, canonicalised the same way the real cache
        # keys are. An entry without one is pre-fingerprint and re-runs once.
        cached_run = runs.get(name)
        wanted = transcribe_fingerprint(sidecar, step_cost, dip_db)
        if cached_run is not None:
            if cached_run.get("fingerprint") == wanted:
                continue
            why = "settings" if cached_run.get("fingerprint") else "no fingerprint"
            log(f"  {name}: {why} differs from cache -- re-transcribing")
            runs.pop(name)
        base = eval_config()
        low, high = sidecar["region"]
        settings = transcribe_settings(sidecar, step_cost, dip_db)
        # The region rides in the config too, so a span-scoped stem set that
        # covers this solo resolves (library.span_for) — a whole-file set
        # still answers first.
        config = base.model_copy(
            update={
                "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
                "transcribe": settings,
            }
        )
        document = library.ingested_document(BENCH / name, config)
        # Through library.resolve_stem, the same resolver the GUI uses: a
        # composite like "other+vocals" (Oleo's fix, R16) is summed on demand
        # beside its parts. Building the path by hand skipped every track the
        # listener had routed to a composite stem.
        stem = library.resolve_stem(document, config, sidecar["model"], settings.stem)
        if stem is None:
            log(f"  {name}: no {settings.stem!r} stem for {sidecar['model']} — skipped")
            continue
        # `ensemble` is a per-track human judgement about the recording, so it
        # lives in the sidecar beside the audio like the span does. It routes
        # the piano oracle (M7b): a span with a horn anywhere in it must stay
        # horn-led, because a piano model asked about a saxophone vouches for
        # nothing and rejection would delete the line.
        ensemble = settings.ensemble
        started = time.time()
        notes, diagnostics = transcribe.analyze(str(stem), settings)
        log(f"  {name}: {len(notes)} notes in {time.time() - started:.0f}s")
        runs[name] = {
            "model": sidecar["model"],
            "stem": settings.stem,
            "ensemble": ensemble,
            "fingerprint": transcribe_fingerprint(sidecar, step_cost, dip_db),
            "region": [low, high],
            "voiced_fraction": diagnostics.voiced_fraction,
            "notes": [
                {
                    "onset": n.onset,
                    "duration": n.duration,
                    "pitch": n.pitch,
                    "confidence": n.confidence,
                }
                for n in notes
            ],
        }
        cache.write_text(json.dumps(runs), encoding="utf-8")
    # Only what is on disk NOW. The cache is keyed by track name and is only
    # ever added to, so a renamed or deleted track leaves its old entry behind
    # -- and everything downstream iterates these keys rather than the
    # sidecars. Renaming eight tracks scored all eight TWICE, once under each
    # name, and the WJazzD mean was quietly a mean over 32 where the truth was
    # 21. A deleted track would have gone on being scored forever.
    #
    # The stale entries stay in the FILE: they cost minutes of CREPE each and
    # come straight back if a rename is reverted. They just do not get scored.
    stale = sorted(set(runs) - live)
    if stale:
        log(f"  ignoring {len(stale)} cached run(s) with no track on disk: {', '.join(stale)}")
    return {name: run for name, run in runs.items() if name in live}


GRIDS_CACHE = Path(".benchmark-grids.json")


def beat_grids(cache: Path = GRIDS_CACHE, log=print) -> dict:
    """A beat grid for every sidecar'd track in benchmark/, reusing the cache.

    This used to be an external file passed with --grids, and the file went
    stale: it held 7 of the 12 tracks, so `summary/wjazz_beat_f1` was a mean
    over 4 solos while the note score next to it was a mean over 11. A
    benchmark that silently scores a subset is the same class of mistake as a
    fit that silently manufactures agreement, so the harness computes its own
    now -- affordable only because the grid no longer chains from a
    separation (stages/beats.py) and costs seconds.
    """
    from swingscribe.gui import library
    from swingscribe.stages import beats

    grids = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    for sidecar_path in sorted(BENCH.rglob("*.swingscribe.json")):
        # rglob and the subfolder-qualified key, matching transcribe_all. With
        # the flat glob this silently skipped every track under benchmark/
        # wjazzd/, which cost them their beat score AND their notation score --
        # the exact "scores a subset without saying so" failure this docstring
        # is about, reintroduced by making two of three globs recursive.
        name = sidecar_name(sidecar_path, json.loads(sidecar_path.read_text(encoding="utf-8")))
        if name in grids or not (BENCH / name).is_file():
            continue
        config = eval_config()
        document = library.ingested_document(BENCH / name, config)
        started = time.time()
        # No stems on the document: the mix is the source, and handing this
        # stage a drum stem would measure a grid the pipeline does not build.
        grid = beats.run(document, config).beat_grid
        log(f"  {name}: {len(grid.beats)} beats in {time.time() - started:.0f}s")
        grids[name] = {"beats": [round(float(b), 4) for b in grid.beats], "source": grid.source}
        cache.write_text(json.dumps(grids), encoding="utf-8")
    return grids


def wjazz_scores(db_path: Path, runs: dict, grids: dict) -> dict:
    """Note and beat scores against WJazzD, for every take we can identify."""
    import sqlite3

    import numpy as np

    sys.path.insert(0, str(Path(__file__).parent))
    from score_wjazz import identify_all, score, score_beats

    db = sqlite3.connect(db_path)
    out = {}
    for name, run in sorted(runs.items()):
        onsets = np.array([n["onset"] for n in run["notes"]])
        pitches = np.array([int(n["pitch"]) for n in run["notes"]])
        order = np.argsort(onsets)
        onsets, pitches = onsets[order], pitches[order]
        ordered = [run["notes"][i] for i in order]

        found, why = identify_all(db, name, onsets, pitches, run["region"])
        if not found:
            out[name] = {"skipped": why}
            continue
        for solo in found:
            result = score(solo, onsets, ordered)
            entry = {
                "performer": solo["performer"],
                "instrument": solo["instrument"],
                "tempo": solo["tempo"],
                "melid": solo["melid"],
                # Where the annotated solo actually sits in OUR timeline. The
                # notation scorer needs it: a whole-track region notates the
                # head and every other soloist too, and a global aligner given
                # 450 reference notes against 1500 of ours is not measuring
                # notation any more.
                "solo_start": round(float(solo["ref_on"][0]) * solo["rate"] + solo["offset"], 3),
                "solo_end": round(float(solo["ref_on"][-1]) * solo["rate"] + solo["offset"], 3),
                "note_f1": round(result["note_f1"], 4),
                "note_precision": round(result["note_precision"], 4),
                "note_recall": round(result["note_recall"], 4),
                "onset_f1": round(result["onset_f1"], 4),
            }
            if name in grids:
                beats = score_beats(
                    db, solo["melid"], grids[name]["beats"], solo["offset"], solo["rate"]
                )
                if beats:
                    entry["beat_f1"] = round(beats["f_measure"], 4)
            # One audio file can hold several annotated solos, so the row is
            # keyed by the solo, not by the file.
            key = name if len(found) == 1 else f"{name} [{solo['performer']}]"
            out[key] = entry
    return out


def mscz_scores(runs: dict) -> dict:
    """Pitch, onset and note scores against the hand transcriptions."""
    sys.path.insert(0, str(Path(__file__).parent))
    import score_benchmark

    by_audio = {audio: key for key, (audio, *_rest) in score_benchmark.TUNES.items()}
    out = {}
    for name, run in sorted(runs.items()):
        key = by_audio.get(name)
        if key is None:
            continue
        scored = score_benchmark.score_tune(key, run)
        out[name] = {
            "pitch_f1": round(scored["pitch_f1"], 4),
            "chroma_f1": round(scored["chroma_f1"], 4),
            "onset_f1": round(scored["onset_f1"], 4),
            "note_f1": round(scored["note_f1"], 4),
        }
    return out


# How far either side of the located solo to notate. Enough that a bar is not
# clipped mid-phrase, small enough that the neighbouring soloist stays out.
SOLO_MARGIN_S = 1.0


def notate_run(name: str, run: dict, grid: dict, region: tuple[float, float] | None = None):
    """Everything from cached notes to a Notation: swing, quantize, notate.

    The stages below transcribe are all pure arithmetic, so this is a second
    or two per tune and needs no audio -- only the notes and the beat grid.
    The assembly itself lives in the package (swingscribe.notation), because
    the GUI's Export button needs exactly the same thing and a second copy of
    it here is how the scoring harness has gone wrong before (CLAUDE.md).
    """
    import json as _json

    from swingscribe.model import NoteEvent
    from swingscribe.notation import notation_for_span

    sidecar_path = BENCH / f"{name}.swingscribe.json"  # name carries any subfolder
    sidecar = {}
    if sidecar_path.is_file():
        sidecar = _json.loads(sidecar_path.read_text(encoding="utf-8"))

    return notation_for_span(
        str(BENCH / name),
        [
            NoteEvent(
                onset=n["onset"],
                duration=n["duration"],
                pitch=n["pitch"],
                confidence=n["confidence"],
                source="crepe",
            )
            for n in run["notes"]
            # A region override means the run covers more music than we are
            # notating (a whole track against one annotated solo), so the
            # notes have to be cut to it as well as the beat grid.
            if region is None or region[0] <= n["onset"] <= region[1]
        ],
        grid["beats"],
        region or tuple(run["region"]),
        stem=run["stem"],
        config=eval_config(),
        anchor=sidecar.get("anchor"),
    )


def notation_scores(runs: dict, grids: dict) -> dict:
    """Our notation against the hand transcription's, as notation.

    The comparison itself lives in `swingscribe.benchmark` -- anything that
    aligns our notes to a reference belongs in the package with tests, never
    in a script (CLAUDE.md), and the GUI's Score button needs the same numbers.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import score_benchmark

    from swingscribe import mscz
    from swingscribe.benchmark import readability, score_against_notation

    by_audio = {audio: mscz_name for audio, mscz_name, *_ in score_benchmark.TUNES.values()}
    out = {}
    for name, run in sorted(runs.items()):
        if name not in by_audio or name not in grids:
            continue
        notation = notate_run(name, run, grids[name])
        if notation is None or not notation.bars:
            continue
        result = score_against_notation(notation, mscz.parse(BENCH / by_audio[name]))
        if not result["n_matched"]:
            continue
        out[name] = {
            "rhythm": round(result["rhythm"], 4),
            "value": round(result["value"], 4),
            "n_matched": result["n_matched"],
            "bars": float(len(notation.bars)),
            "key_fifths": float(notation.key_fifths),
            # Whether the page is writable at all -- a question no comparison
            # against a reference can see. Folded in here rather than measured
            # in a pass of its own because the notation is already built.
            **readability(notation),
        }
    return out


def wjazz_notation_scores(db_path: Path, card_wjazz: dict, runs: dict, grids: dict) -> dict:
    """Our notation against WJazzD's metrical annotation, per identified solo.

    This is the notation benchmark the MuseScore set cannot be on its own: ten
    hand transcriptions, all bebop eighth-note lines, can reward a grid rule
    for writing everything as eighths. WJazzD is hundreds of solos annotated by
    different people, with `division` running 1 through 10 — and it writes a
    swung pair as two eighths, which is the convention we target.

    Only `rhythm`: WJazzD stores metrical position, not notated value.
    """
    import sqlite3

    from swingscribe.benchmark import readability, score_against_wjazz_notation
    from swingscribe.wjazz import notated_positions

    db = sqlite3.connect(db_path)
    out = {}
    for key, entry in sorted(card_wjazz.items()):
        if "melid" not in entry:
            continue
        # The row may be keyed "file [performer]" when one file holds several
        # annotated solos; the notes and grid are the file's.
        name = key.split(" [")[0]
        if name not in runs or name not in grids:
            continue
        # Notate ONLY the located solo, not the whole track. The alignment
        # underneath is global on purpose (both sides are meant to cover the
        # same music), so handing it a five-minute notation against a
        # one-chorus annotation measures nothing about notation.
        window = (entry["solo_start"] - SOLO_MARGIN_S, entry["solo_end"] + SOLO_MARGIN_S)
        notation = notate_run(name, runs[name], grids[name], region=window)
        if notation is None or not notation.bars:
            continue
        # Readability is a property of OUR page and needs no reference, so it
        # is recorded even for a solo the alignment could not line up. That is
        # the point of having it: it is the one number every notation the
        # harness can build contributes to.
        out[key] = dict(readability(notation))
        result = score_against_wjazz_notation(notation, notated_positions(db, entry["melid"]))
        if not result["n_matched"]:
            continue
        out[key].update(
            {
                "rhythm": round(result["rhythm"], 4),
                "n_matched": result["n_matched"],
                "coverage": round(result["coverage"], 4),
                "trusted": float(bool(result["trusted"])),
            }
        )
    return out


def readable_pages(card: dict) -> dict:
    """Every notation this run built, keyed uniquely, for the readability mean.

    Both notation sections contribute. WJazzD keys carry a performer suffix
    when one file holds several annotated solos and the hand-scored keys are
    bare filenames, so nothing collides -- but the two sections DO notate some
    of the same audio over different regions, which is why this reads them as
    separate pages rather than deduplicating by track.
    """
    pages = {}
    for section, prefix in (("notation", ""), ("wjazz_notation", "wjazz:")):
        for name, entry in card.get(section, {}).items():
            if "readability" in entry:
                pages[prefix + name] = entry
    return pages


def render(card: dict) -> None:
    wjazz = {k: v for k, v in card["wjazz"].items() if "skipped" not in v}
    skipped = {k: v for k, v in card["wjazz"].items() if "skipped" in v}

    print("\n== WJazzD: our timestamps against a human's, same recording ==")
    if wjazz:
        header = (
            f"  {'tune':<26s} {'soloist':<20s} {'inst':>4s} {'bpm':>5s}  "
            f"{'note':>6s} {'P':>6s} {'R':>6s} {'beat':>6s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name, e in sorted(wjazz.items(), key=lambda kv: -kv[1]["note_f1"]):
            beat = f"{e['beat_f1']:.3f}" if "beat_f1" in e else "  -  "
            print(
                f"  {Path(name).stem[:26]:<26s} {e['performer'][:20]:<20s} {e['instrument']:>4s} "
                f"{e['tempo'] or 0:5.0f}  {e['note_f1']:6.3f} {e['note_precision']:6.3f} "
                f"{e['note_recall']:6.3f} {beat:>6s}"
            )
        # Each mean states its own n. They are not always the same n -- a solo
        # can be note-scored with no beat grid -- and printing one count for
        # both is how the two came to be read as the same population.
        note_n = int(card["summary"]["wjazz_note_n"])
        beat_n = int(card["summary"].get("wjazz_beat_n", 0))
        note_f1 = card["summary"]["wjazz_note_f1"]
        beat_f1 = card["summary"]["wjazz_beat_f1"]
        print(f"\n  mean note F1 {note_f1:.3f} over {note_n} solos", end="")
        print(f"   mean beat F1 {beat_f1:.3f} over {beat_n} solos")
    for name, e in sorted(skipped.items()):
        print(f"  (not scored) {Path(name).stem[:30]:<30s} {e['skipped']}")

    if card.get("notation"):
        print("\n== Notation: our score against the hand transcription, as notation ==")
        header = f"  {'tune':<30s} {'bars':>5s} {'matched':>8s} {'rhythm':>8s} {'value':>7s}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name, entry in sorted(card["notation"].items()):
            print(
                f"  {Path(name).stem[:30]:<30s} {int(entry['bars']):5d} "
                f"{int(entry['n_matched']):8d} {entry['rhythm']:8.3f} {entry['value']:7.3f}"
            )

    if card.get("wjazz_notation"):
        print("\n== Notation: our score against WJazzD's metrical annotation ==")
        print("  (rhythm only — WJazzD stores metrical position, not notated value)")
        header = f"  {'solo':<34s} {'matched':>8s} {'cover':>7s} {'rhythm':>8s}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        rows = sorted(card["wjazz_notation"].items())
        for name, entry in rows:
            if "rhythm" not in entry:
                print(f"  {Path(name).stem[:34]:<34s} {'-':>8s}   (nothing lined up)")
                continue
            flag = "" if entry["trusted"] else "   (untrusted — too little lined up)"
            print(
                f"  {Path(name).stem[:34]:<34s} {int(entry['n_matched']):8d} "
                f"{entry['coverage']:7.3f} {entry['rhythm']:8.3f}{flag}"
            )
        trusted = [e for _n, e in rows if e.get("trusted")]
        if trusted:
            print(
                f"\n  mean rhythm {statistics.fmean(e['rhythm'] for e in trusted):.3f} "
                f"over {len(trusted)} solo(s)"
            )

    pages = readable_pages(card)
    if pages:
        print("\n== Readability: is the page writable at all? (no reference needed) ==")
        header = (
            f"  {'notation':<34s} {'events':>7s} {'rest<8th':>9s} "
            f"{'note<16th':>10s} {'ties':>6s} {'score':>7s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name, e in sorted(pages.items(), key=lambda kv: kv[1]["readability"]):
            print(
                f"  {Path(name).stem[:34]:<34s} {int(e['events']):7d} "
                f"{e['short_rests']:9.2f} {e['short_values']:10.2f} "
                f"{e['tie_rate']:6.3f} {e['readability']:7.4f}"
            )
        print(
            f"\n  mean readability {card['summary']['readability']:.4f} "
            f"over {int(card['summary']['readability_n'])} notation(s)"
        )
        # The target, counted off the ten hand transcriptions in benchmark/:
        # 6 sub-eighth rests in 487 rests, 13 sub-sixteenth notes in 3646.
        print("  a human writes 0.995 (benchmark/*.mscz: 6 short rests, 13 short values)")

    print("\n== MuseScore: our audio against notated rhythm ==")
    header = f"  {'tune':<30s} {'pitch':>7s} {'chroma':>7s} {'onset':>7s} {'note':>7s}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, e in sorted(card["mscz"].items()):
        print(
            f"  {Path(name).stem[:30]:<30s} {e['pitch_f1']:7.3f} {e['chroma_f1']:7.3f} "
            f"{e['onset_f1']:7.3f} {e['note_f1']:7.3f}"
        )
    if card["mscz"]:
        print(f"\n  mean note F1 {card['summary']['mscz_note_f1']:.3f}")


def flatten(card: dict) -> dict[str, float]:
    """Every number the baselines pin, as one flat name -> value mapping."""
    flat = {}
    for name, entry in card["wjazz"].items():
        for field, value in entry.items():
            if isinstance(value, (int, float)):
                flat[f"wjazz/{Path(name).stem}/{field}"] = float(value)
    for name, entry in card["mscz"].items():
        for field, value in entry.items():
            flat[f"mscz/{Path(name).stem}/{field}"] = float(value)
    for name, entry in card.get("notation", {}).items():
        for field, value in entry.items():
            if isinstance(value, (int, float)):
                flat[f"notation/{Path(name).stem}/{field}"] = float(value)
    for name, entry in card.get("wjazz_notation", {}).items():
        for field, value in entry.items():
            if isinstance(value, (int, float)):
                flat[f"wjazz-notation/{Path(name).stem}/{field}"] = float(value)
    for field, value in card["summary"].items():
        flat[f"summary/{field}"] = float(value)
    return flat


def compare(card: dict) -> int:
    """Diff against the pinned baselines. Returns a process exit code."""
    if not BASELINES.is_file():
        print(f"\nNo baselines pinned yet. Run with --pin to create {BASELINES}.")
        return 0
    pinned = json.loads(BASELINES.read_text(encoding="utf-8"))
    current = flatten(card)
    moved, appeared, vanished = [], [], []
    for key, value in sorted(current.items()):
        if key not in pinned:
            appeared.append(key)
        elif abs(value - pinned[key]) > TOLERANCE:
            moved.append((key, pinned[key], value))
    vanished = sorted(set(pinned) - set(current))

    if not (moved or appeared or vanished):
        print(f"\n== Baselines: all {len(current)} numbers unchanged ==")
        return 0
    print("\n== Baselines: CHANGED ==")
    for key, was, now in moved:
        print(f"  {key:<48s} {was:7.4f} -> {now:7.4f}  ({now - was:+.4f})")
    for key in appeared:
        print(f"  {key:<48s}      new -> {current[key]:7.4f}")
    for key in vanished:
        print(f"  {key:<48s} {pinned[key]:7.4f} -> gone")
    print("\nIf this is intended, say so explicitly and re-pin with --pin (CLAUDE.md).")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Score everything and print one scorecard.")
    parser.add_argument("--db", type=Path, default=None, help="wjazzd.db; skips WJazzD if absent")
    parser.add_argument(
        "--grids", type=Path, default=GRIDS_CACHE, help=f"beat-grid cache (default {GRIDS_CACHE})"
    )
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    parser.add_argument("--pin", action="store_true", help="rewrite the baselines from this run")
    parser.add_argument("--json", type=Path, default=None, help="also write the scorecard here")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"stage cache to read stems from (default {CACHE_DIR}; the batch's is "
        "benchmark/.swingscribe-cache)",
    )
    args = parser.parse_args()
    if args.cache_dir is not None:
        global CACHE_DIR
        CACHE_DIR = args.cache_dir.resolve()

    cache = notes_cache(args.step_cost, args.dip_db)
    print(f"== Transcribing (step cost {args.step_cost}, dip {args.dip_db} dB), cache {cache} ==")
    runs = transcribe_all(cache, args.step_cost, args.dip_db)
    print(f"== Beat grids, cache {args.grids} ==")
    grids = beat_grids(args.grids)

    wjazz = wjazz_scores(args.db, runs, grids) if args.db else {}
    card = {
        "settings": {"step_cost": args.step_cost, "dip_db": args.dip_db},
        "wjazz": wjazz,
        "mscz": mscz_scores(runs),
        "notation": notation_scores(runs, grids) if grids else {},
        # WJazzD carries a human's NOTATION as well as their onsets, so the
        # same solos answer both questions.
        "wjazz_notation": (
            wjazz_notation_scores(args.db, wjazz, runs, grids) if args.db and grids else {}
        ),
        "summary": {},
    }
    scored = [e for e in card["wjazz"].values() if "skipped" not in e]
    if scored:
        card["summary"]["wjazz_note_f1"] = round(statistics.fmean(e["note_f1"] for e in scored), 4)
        card["summary"]["wjazz_note_n"] = float(len(scored))
        beats = [e["beat_f1"] for e in scored if "beat_f1" in e]
        if beats:
            card["summary"]["wjazz_beat_f1"] = round(statistics.fmean(beats), 4)
            # Pinned so the denominator can never change silently. It already
            # did once: beat F1 was a mean over the 4 solos that happened to
            # have a cached grid, printed beside a note F1 over 11, and the
            # gap read as agreement between two numbers that were measuring
            # different populations.
            card["summary"]["wjazz_beat_n"] = float(len(beats))
    pages = readable_pages(card)
    if pages:
        card["summary"]["readability"] = round(
            statistics.fmean(e["readability"] for e in pages.values()), 4
        )
        card["summary"]["readability_n"] = float(len(pages))
    if card["mscz"]:
        card["summary"]["mscz_note_f1"] = round(
            statistics.fmean(e["note_f1"] for e in card["mscz"].values()), 4
        )
        card["summary"]["mscz_note_n"] = float(len(card["mscz"]))

    render(card)
    if args.json:
        args.json.write_text(json.dumps(card, indent=2), encoding="utf-8")

    if args.pin:
        BASELINES.parent.mkdir(parents=True, exist_ok=True)
        BASELINES.write_text(json.dumps(flatten(card), indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nPinned {len(flatten(card))} numbers to {BASELINES}.")
        return
    raise SystemExit(compare(card))


if __name__ == "__main__":
    main()
