"""Melodic-line selection experiments over the piano oracle (issue #8).

    uv run python scripts/line_selection.py --extract   # ~8 min, once
    uv run python scripts/line_selection.py             # score strategies

Results and the method's writeup: docs/issue8-line-selection.md. This is a
MEASUREMENT instrument. The picker it measured now ships as
`swingscribe.line_selection` behind `TranscribeConfig.piano_line = "oracle"`,
offered in the GUI as a second take beside the CREPE line; this script
imports it from there so the two cannot drift apart.

The oracle's full polyphonic output per piano span is extracted once into
`benchmark/.swingscribe-cache/oracle-notes/` (derived data, safely
deletable like everything else in the cache) and every strategy iteration
is then arithmetic. Strategies pick at most one note per 50 ms onset
cluster and are scored exactly as the green bar scores the shipped line:
pitch-sequence alignment against the reference melody, raw notes (D20).

The winner so far is a small Viterbi — velocity as a WITHIN-TRACK
percentile rank for the emission, a leap-capped register-continuity
transition, and a first-class skip state so comping between phrases emits
nothing. Mean F1 0.8655 against the shipped line's 0.8017, better or equal
on 9 of 10 tracks; the oracle's top-2 ceiling is 0.915+ recall on every
track, so selection remains the entire gap.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmark"
ORACLE_DIR = BENCH_DIR / ".swingscribe-cache" / "oracle-notes"

sys.path.insert(0, str(REPO_ROOT / "src"))

HEAD = 220  # transposition search head, mirroring gui/ground_truth


# The piano spans with references: the six hand-scored tracks and the four
# WJazzD pianos. Derived from sidecars at run time — a track qualifies when
# its sidecar routes to the piano oracle and names a score.
def piano_tracks() -> list[Path]:
    from swingscribe.config import Config

    out = []
    for sidecar_path in sorted(BENCH_DIR.rglob("*.swingscribe.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        audio = sidecar_path.with_name(sidecar_path.name.removesuffix(".swingscribe.json"))
        if not audio.is_file() or not sidecar.get("score"):
            continue
        ensemble = sidecar.get("ensemble")
        config = Config()
        routed = config.transcribe.model_copy(update={"ensemble": ensemble or "horn-led"})
        if routed.uses_piano_oracle:
            out.append(audio)
    return out


def extract(tracks: list[Path]) -> None:
    """One slow oracle pass per track; JSONs land in the cache."""
    import soundfile

    from swingscribe import piano, pipeline
    from swingscribe.config import Config
    from swingscribe.gui import library
    from swingscribe.stages import ingest, separate
    from swingscribe.stages.transcribe import crop_region

    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    for audio in tracks:
        out_path = ORACLE_DIR / (audio.stem + ".oracle.json")
        if out_path.exists():
            print(f"cached: {out_path.name}")
            continue
        sidecar = json.loads((audio.parent / f"{audio.name}.swingscribe.json").read_text("utf-8"))
        model = sidecar["model"]
        base = Config.from_yaml()
        base = base.model_copy(
            update={"separate": base.separate.model_copy(update={"model": model})}
        )
        document = pipeline.run(
            str(audio.relative_to(BENCH_DIR)),
            base,
            stages=[("ingest", ingest.run), ("separate", separate.run)],
        )
        stem_path = library.resolve_stem(document, base, model, sidecar["stem"])
        if stem_path is None:
            print(f"no {sidecar['stem']!r} stem for {audio.name} — separate it first; skipped")
            continue
        data, rate = soundfile.read(stem_path, dtype="float32", always_2d=True)
        mono, offset = crop_region(data.mean(axis=1), rate, tuple(sidecar["region"]))
        started = time.time()
        notes = piano.transcribe(mono, rate, offset=offset)
        out_path.write_text(
            json.dumps({"track": str(audio.relative_to(BENCH_DIR)), "notes": notes})
        )
        print(f"{audio.stem}: {len(notes)} oracle notes in {time.time() - started:.0f}s")


# The picker itself lives in the package now (`swingscribe.line_selection`),
# so the shipped code and this instrument cannot drift apart; the names are
# re-exported here so the strategies below read as they did when measured.
from swingscribe.line_selection import (  # noqa: E402
    clusters_of,
    normalize_velocities,
    pick_from_clusters,
)


def pick_dp(clusters, w_continuity=0.02, skip_margin=0.10, beam=8):
    return pick_from_clusters(clusters, w_continuity, skip_margin, beam)


def score_line(reference: list[int], candidate: list[dict]) -> dict:
    from swingscribe.alignment import align, best_transposition

    est = [int(n["pitch"]) for n in sorted(candidate, key=lambda n: n["onset"])]
    if not est:
        return {"f1": 0.0, "matched": 0, "wrong": 0, "invented": 0, "missed": len(reference)}
    coarse, _ = best_transposition(reference[:HEAD], est[:HEAD])
    offset, _ = best_transposition(
        reference[:HEAD], est[:HEAD], search=range(coarse - 2, coarse + 3)
    )
    aligned = align(reference, [p + offset for p in est])
    return {
        "f1": round(aligned.f1, 4),
        "matched": aligned.matches,
        "wrong": aligned.substitutions,
        "invented": aligned.insertions,
        "missed": aligned.deletions,
    }


def shipped_line(audio: Path, sidecar: dict) -> list[dict]:
    from swingscribe.config import Config
    from swingscribe.gui import library, review

    config = Config.from_yaml()
    document = library.ingested_document(audio, config)
    run_config = review.span_config(
        config, sidecar["stem"], sidecar["region"][0], sidecar["region"][1], sidecar.get("ensemble")
    )
    payload = review.cached_review(document, run_config, sidecar["model"])
    if payload is None:
        raise SystemExit(f"no cached review for {audio.name} — run the batch first")
    return payload["notes"]


def score(tracks: list[Path]) -> None:
    from swingscribe import mscz

    rows = []
    for audio in tracks:
        oracle_path = ORACLE_DIR / (audio.stem + ".oracle.json")
        if not oracle_path.exists():
            print(f"no oracle notes for {audio.name} — run --extract first; skipped")
            continue
        sidecar = json.loads((audio.parent / f"{audio.name}.swingscribe.json").read_text("utf-8"))
        reference = [n.pitch for n in mscz.parse_any(sidecar["score"]).melody]
        notes = normalize_velocities(json.loads(oracle_path.read_text())["notes"])
        clusters = clusters_of(notes)
        row = {
            "track": audio.stem,
            "shipped": score_line(reference, shipped_line(audio, sidecar)),
            "loudest": score_line(
                reference, [max(c, key=lambda n: (n["velocity"], n["pitch"])) for c in clusters]
            ),
            "dp": score_line(reference, pick_dp(clusters)),
            "ceiling_top2": score_line(
                reference,
                [n for c in clusters for n in sorted(c, key=lambda x: -x["velocity"])[:2]],
            ),
        }
        rows.append(row)
        print(
            f"{audio.stem[:36]:<36} shipped={row['shipped']['f1']:.3f}  "
            f"loudest={row['loudest']['f1']:.3f}  dp={row['dp']['f1']:.3f}"
        )
    if not rows:
        return
    for label in ("shipped", "loudest", "dp"):
        f1s = [r[label]["f1"] for r in rows]
        wrong = sum(r[label]["wrong"] for r in rows)
        print(f"{label:<10} mean F1 {sum(f1s) / len(f1s):.4f}  min {min(f1s):.3f}  wrong {wrong}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extract", action="store_true", help="run the oracle over piano spans")
    args = parser.parse_args()
    os.chdir(BENCH_DIR)
    tracks = piano_tracks()
    print(f"{len(tracks)} piano track(s) with references")
    if args.extract:
        extract(tracks)
    else:
        score(tracks)


if __name__ == "__main__":
    main()
