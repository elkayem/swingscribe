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

## One performer, one title, several solos

456 solos share only 421 performer/title pairs. Joe Henderson takes two on
In 'n Out, Sonny Rollins three on Blue Seven, and Coltrane's Body and Soul
exists as a master and an alternate take. Naming a file after the performer
and the tune therefore OVERWRITES, silently, and what survives is whichever
solo the query reached last -- so the file called `Joe_Henderson_In_n_Out`
held his SECOND solo while the audio and the Jazzomat page both showed his
first.

The melid goes in every filename for that reason, and it is also the number
in the synopsis URL (melid 198 is `.../synopsis/solo198.html`), so a file can
be laid beside the page it was rendered from. It is written `_solo_198` and
not `_solo198` so the GUI's name matcher splits it into a stopword and a
digit and ignores both (`gui/ground_truth.py`).

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
    cleaned = re.sub(r"[^\w\s-]", "", text or "").strip()
    return re.sub(r"[\s]+", "_", cleaned)


def score_name(performer: str, title: str, titleaddon: str, melid: int) -> str:
    """A filename that identifies ONE solo -- see the module docstring.

    `titleaddon` carries what distinguishes two recordings of the same tune
    ("Alternate Take", "1961") and is worth reading; `melid` is what makes the
    name unique, and what ties it to the synopsis page.
    """
    parts = [safe_name(performer), safe_name(title), safe_name(titleaddon)]
    stem = "_".join(part for part in parts if part) or "untitled"
    return f"{stem}_solo_{melid}.musicxml"


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
        "select melid, performer, title, titleaddon, solopart, instrument from solo_info "
        "order by performer, title, solopart, melid"
    ).fetchall()
    needle = args.match.lower()
    rows = [r for r in rows if not needle or needle in f"{r[1]} {r[2]} {r[3] or ''}".lower()]
    if args.limit:
        rows = rows[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for melid, performer, title, titleaddon, solopart, instrument in rows:
        notation = annotation_notation(db, melid)
        if notation is None or not notation.bars:
            print(f"  (skipped) {performer} - {title}: no metrical annotation")
            continue
        name = score_name(performer, title, titleaddon or "", melid)
        # One name, one solo. The melid guarantees it; this says so out loud,
        # because the naming without it lost 35 of 456 solos and said nothing.
        if name in written:
            parser.error(f"{name} would be written twice (melid {written[name]} and {melid})")
        path = args.out / name
        path.write_text(to_musicxml(notation, part_name=instrument or "Solo"), encoding="utf-8")
        score = readability(notation)
        written[name] = melid
        part = f"solo {solopart}" if solopart else ""
        print(
            f"  {name:<62s} {len(notation.bars):4d} bars  "
            f"readability {score['readability']:.3f}  {part}"
        )
    print(f"\nWrote {len(written)} score(s) to {args.out.resolve()}.")
    print("ODbL: these are derivatives of WJazzD. Do not commit them.")


if __name__ == "__main__":
    main()
