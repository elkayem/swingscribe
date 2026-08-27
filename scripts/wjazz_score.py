"""Write a WJazzD solo out as a score, to use as ground truth in the GUI.

    uv run python scripts/wjazz_score.py --db wjazz/wjazzd.db --out ../wjazz-scores
    uv run python scripts/wjazz_score.py --db wjazz/wjazzd.db --match "Sidewinder"

## What this is

WJazzD annotates every note's place in the bar -- `bar`, `beat`, and `tatum`
out of that beat's own `division` -- as well as its onset in seconds. The
metrical half is a complete notation: in a single line the written value of a
note is the distance to the next one, less any rest. So a score can be
rendered from it, which is how the Jazzomat project's own PDF lead sheets are
made.

What comes out is a `.musicxml`, which MuseScore opens and which the GUI's
"Ground truth..." button now accepts alongside `.mscz`/`.mscx`.

## What it is evidence about

The POSITIONS and the PITCHES are a human's, and are independent.

The RESTS and NOTE VALUES are ours -- `notate.notated_durations`,
`notate.snap_values`, `notate.MIN_REST` and the tuplet grouping, applied to a
human's grid. Comparing our note values against these would be comparing our
conventions with themselves. Use it for what was played and where it sits in
the bar; `run_eval.py` still scores WJazzD notation on rhythm alone.

## Licence

WJazzD is ODbL, which is share-alike. A file written from it is a derivative
of the database, so `--out` defaults OUTSIDE this repository and these files
must never be committed (CLAUDE.md, plan section 12).
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from swingscribe.benchmark import readability  # noqa: E402
from swingscribe.stages.export import to_musicxml  # noqa: E402
from swingscribe.wjazz import annotation_notation  # noqa: E402

DEFAULT_OUT = Path("..") / "wjazz-scores"


def safe_name(text: str) -> str:
    """A filename the GUI's soloist/tune matcher can still read."""
    cleaned = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"[\s]+", "_", cleaned) or "untitled"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, required=True, help="wjazzd.db")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"where to write (default {DEFAULT_OUT} -- ODbL, keep it out of the repo)",
    )
    parser.add_argument("--match", default="", help="only solos whose performer or title matches")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many")
    args = parser.parse_args()

    if args.out.resolve().is_relative_to(Path(__file__).resolve().parent.parent):
        parser.error(
            f"{args.out} is inside the repository. WJazzD is ODbL share-alike and a score "
            "written from it is a derivative of the database; write it somewhere else."
        )

    db = sqlite3.connect(args.db)
    rows = db.execute(
        "select melid, performer, title, instrument from solo_info order by performer, title"
    ).fetchall()
    needle = args.match.lower()
    rows = [r for r in rows if not needle or needle in f"{r[1]} {r[2]}".lower()]
    if args.limit:
        rows = rows[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for melid, performer, title, instrument in rows:
        notation = annotation_notation(db, melid)
        if notation is None or not notation.bars:
            print(f"  (skipped) {performer} - {title}: no metrical annotation")
            continue
        name = f"{safe_name(performer)}_{safe_name(title)}.musicxml"
        path = args.out / name
        path.write_text(to_musicxml(notation, part_name=instrument or "Solo"), encoding="utf-8")
        score = readability(notation)
        written += 1
        print(f"  {name:<58s} {len(notation.bars):4d} bars  readability {score['readability']:.3f}")
    print(f"\nWrote {written} score(s) to {args.out.resolve()}.")
    print("ODbL: these are derivatives of WJazzD. Do not commit them.")


if __name__ == "__main__":
    main()
