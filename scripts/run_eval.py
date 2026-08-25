"""One command, one scorecard: everything the pipeline is measured by.

    uv run python scripts/run_eval.py --db ../wjazz/wjazzd.db
    uv run python scripts/run_eval.py --db ../wjazz/wjazzd.db --pin

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
import json
import statistics
import sys
import time
from pathlib import Path

BENCH = Path("benchmark")
BASELINES = Path("tests/regression/real-audio-baselines.json")
# How far a score may move before it is called a change rather than noise.
# Transcription is deterministic, so this is tight on purpose; it exists for
# floating-point drift across platforms, not for genuine variation.
TOLERANCE = 0.002


def notes_cache(step_cost: float, dip_db: float) -> Path:
    """One cache per decode setting -- they are not interchangeable results."""
    return Path(f".benchmark-notes-c{step_cost}-d{dip_db}.json")


def transcribe_all(cache: Path, step_cost: float, dip_db: float, log=print) -> dict:
    """Transcribe every sidecar'd span in benchmark/, reusing what is cached."""
    from swingscribe.config import Config
    from swingscribe.gui import library
    from swingscribe.stages import transcribe
    from swingscribe.stages.separate import stems_dir

    runs = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    for sidecar_path in sorted(BENCH.glob("*.swingscribe.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        name = sidecar["file"]
        if name in runs or not (BENCH / name).is_file():
            continue
        base = Config()
        config = base.model_copy(
            update={"separate": base.separate.model_copy(update={"model": sidecar["model"]})}
        )
        document = library.ingested_document(BENCH / name, config)
        low, high = sidecar["region"]
        stem = (
            stems_dir(config.cache_dir, library.file_digest(document.audio.path), sidecar["model"])
            / f"{sidecar['stem']}.wav"
        )
        if not stem.is_file():
            log(f"  {name}: no {sidecar['stem']!r} stem for {sidecar['model']} â€” skipped")
            continue
        settings = base.transcribe.model_copy(
            update={
                "stem": sidecar["stem"],
                "region": (low, high),
                "pitch_step_cost": step_cost,
                "onset_dip_db": dip_db,
            }
        )
        started = time.time()
        notes, diagnostics = transcribe.analyze(str(stem), settings)
        log(f"  {name}: {len(notes)} notes in {time.time() - started:.0f}s")
        runs[name] = {
            "model": sidecar["model"],
            "stem": sidecar["stem"],
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
    return runs


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


def notate_run(name: str, run: dict, grid: dict):
    """Everything from cached notes to a Notation: swing, quantize, notate.

    The stages below transcribe are all pure arithmetic, so this is a second
    or two per tune and needs no audio -- only the notes and the beat grid.
    The assembly itself lives in the package (swingscribe.notation), because
    the GUI's Export button needs exactly the same thing and a second copy of
    it here is how the scoring harness has gone wrong before (CLAUDE.md).
    """
    import json as _json

    from swingscribe.config import Config
    from swingscribe.model import NoteEvent
    from swingscribe.notation import notation_for_span

    sidecar_path = BENCH / f"{name}.swingscribe.json"
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
        ],
        grid["beats"],
        tuple(run["region"]),
        stem=run["stem"],
        config=Config(),
        anchor=sidecar.get("anchor"),
    )


def notation_scores(runs: dict, grids: dict) -> dict:
    """Our notation against the hand transcription's, as notation.

    Needs no tempo map: both sides are already in quarter notes from their own
    bar one, and the single unknown -- which of our bars is their bar one --
    is one constant that the median absorbs.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import score_benchmark

    from swingscribe import mscz
    from swingscribe.alignment import align, best_transposition
    from swingscribe.benchmark import merge_ties, score_notation

    by_audio = {audio: mscz_name for audio, mscz_name, *_ in score_benchmark.TUNES.values()}
    out = {}
    for name, run in sorted(runs.items()):
        if name not in by_audio or name not in grids:
            continue
        notation = notate_run(name, run, grids[name])
        if notation is None or not notation.bars:
            continue
        ours = merge_ties(
            [
                (bar_start + note.beat, note.duration, note.pitch, note.tie_stop)
                for bar_start, bar in _with_starts(notation.bars)
                for note in bar.notes
                if not note.is_rest
            ]
        )
        score = mscz.parse(BENCH / by_audio[name])
        theirs = [(n.position, n.duration, n.pitch) for n in score.notes]
        if not ours or not theirs:
            continue
        their_pitches = [p for _, _, p in theirs]
        our_pitches = [p for _, _, p in ours]
        coarse, _ = best_transposition(their_pitches[:120], our_pitches[:160])
        offset, _ = best_transposition(
            their_pitches[:120], our_pitches[:160], search=range(coarse - 2, coarse + 3)
        )
        shifted = [(pos, dur, pitch + offset) for pos, dur, pitch in ours]
        aligned = align(their_pitches, [p for _, _, p in shifted])
        result = score_notation(theirs, shifted, aligned.pairs)
        out[name] = {
            "rhythm": round(result["rhythm"], 4),
            "value": round(result["value"], 4),
            "n_matched": result["n_matched"],
            "bars": float(len(notation.bars)),
            "key_fifths": float(notation.key_fifths),
        }
    return out


def _with_starts(bars):
    """(absolute quarter position of the bar, bar) for each bar in order."""
    cursor = 0.0
    for bar in bars:
        yield cursor, bar
        cursor += bar.time_signature[0] * 4.0 / bar.time_signature[1]


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
        print(f"\n  mean note F1 {card['summary']['wjazz_note_f1']:.3f}   ", end="")
        print(f"mean beat F1 {card['summary']['wjazz_beat_f1']:.3f}   over {len(wjazz)} solos")
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
    parser.add_argument("--grids", type=Path, default=None, help="cached beat grids, optional")
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    parser.add_argument("--pin", action="store_true", help="rewrite the baselines from this run")
    parser.add_argument("--json", type=Path, default=None, help="also write the scorecard here")
    args = parser.parse_args()

    cache = notes_cache(args.step_cost, args.dip_db)
    print(f"== Transcribing (step cost {args.step_cost}, dip {args.dip_db} dB), cache {cache} ==")
    runs = transcribe_all(cache, args.step_cost, args.dip_db)
    grids = json.loads(args.grids.read_text(encoding="utf-8")) if args.grids else {}

    card = {
        "settings": {"step_cost": args.step_cost, "dip_db": args.dip_db},
        "wjazz": wjazz_scores(args.db, runs, grids) if args.db else {},
        "mscz": mscz_scores(runs),
        "notation": notation_scores(runs, grids) if grids else {},
        "summary": {},
    }
    scored = [e for e in card["wjazz"].values() if "skipped" not in e]
    if scored:
        card["summary"]["wjazz_note_f1"] = round(statistics.fmean(e["note_f1"] for e in scored), 4)
        beats = [e["beat_f1"] for e in scored if "beat_f1" in e]
        if beats:
            card["summary"]["wjazz_beat_f1"] = round(statistics.fmean(beats), 4)
    if card["mscz"]:
        card["summary"]["mscz_note_f1"] = round(
            statistics.fmean(e["note_f1"] for e in card["mscz"].values()), 4
        )

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
