"""Recompute the GUI review payloads for every WJazzD solo under run_eval's
CURRENT transcribe config, so the error taxonomy has frame evidence again.

    uv run python scripts/wjazz_reviews.py                 # compute what is missing
    uv run python scripts/wjazz_reviews.py --dry           # only say what is missing

`scripts/error_taxonomy.py` reads its frame evidence (CREPE periodicity, the
energy gate, the smoothed pitch) from the GUI's review cache BY KEY, and that
key carries every transcribe setting that can change a note. So any change to
`TranscribeConfig`'s defaults or to `transcribe.CACHE_VERSION` leaves every
solo without evidence until a review is recomputed under the new key -- and
the taxonomy then reports the frame-evidence classes (`too_short`,
`tracked_other`, `dropped`, ...) as gone and their misses as `unclassified`.
That is an instrument gap, not a transcription change: on 2026-09-07 the
first pass after the persistence change read 1,265 `unclassified` where the
pin had 0, until this was run.

This is pass 2 of `wjazz_batch.py` alone: the sidecar's located span, stem,
model and ensemble through `review.analyze_and_cache`, the same computation
the Score button reports. It does NOT run the whole-file locate pass, which
under a changed transcribe config would be a full CREPE pass over every
whole file rather than every solo (about six times the work). One CREPE pass
per solo, ~1 minute each on this CPU; 74 solos took 71 minutes.

Every recomputed payload is checked note-for-note against run_eval's notes
cache, exactly as `error_taxonomy.load_evidence` will check it, so a payload
this writes is one the taxonomy will read.
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import run_eval  # noqa: E402

DEFAULT_CACHE_DIR = Path("benchmark/.swingscribe-cache")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--dry", action="store_true", help="say what is missing, compute nothing")
    parser.add_argument("--limit", type=int, default=None, help="compute at most N (dev)")
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    args = parser.parse_args()

    run_eval.CACHE_DIR = args.cache_dir.resolve()
    from swingscribe.gui import library, review

    notes_path = run_eval.notes_cache(args.step_cost, args.dip_db)
    runs = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}

    computed = present = 0
    for sidecar_path in sorted(run_eval.BENCH.rglob("*.swingscribe.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        name = run_eval.sidecar_name(sidecar_path, sidecar)
        if not name.startswith("wjazzd/") or not (run_eval.BENCH / name).is_file():
            continue
        # The same config, document and span config `error_taxonomy.load_evidence`
        # builds, so the key this writes under is the key it reads from.
        base = run_eval.eval_config()
        settings = run_eval.transcribe_settings(sidecar, args.step_cost, args.dip_db)
        config = base.model_copy(
            update={
                "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
                "transcribe": settings,
            }
        )
        document = library.ingested_document(run_eval.BENCH / name, config)
        cfg = review.span_config(
            config, settings.stem, settings.region[0], settings.region[1], settings.ensemble
        )
        key = review.review_key(document, cfg, sidecar["model"])
        if review._cache(cfg).get_json(key) is not None:
            present += 1
            continue
        if args.dry:
            print(f"  {name}: missing ({key[:12]})", flush=True)
            continue
        started = time.time()
        payload = review.analyze_and_cache(document, cfg, sidecar["model"])
        verdict = ""
        if name in runs:
            ours = [(round(n["onset"], 3), n["pitch"]) for n in runs[name]["notes"]]
            theirs = [(n["onset"], n["pitch"]) for n in payload["notes"]]
            verdict = "matches run_eval" if ours == theirs else "DIFFERS from run_eval"
        print(
            f"  {name}: {len(payload['notes'])} notes in {time.time() - started:.0f}s {verdict}",
            flush=True,
        )
        computed += 1
        if args.limit and computed >= args.limit:
            break
    print(f"{computed} computed, {present} already present")


if __name__ == "__main__":
    main()
