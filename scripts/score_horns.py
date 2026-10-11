"""Score two-horn head pages against a human's two-voice page.

    .venv\\Scripts\\python.exe scripts\\score_horns.py REFERENCE.mscz PAGE.musicxml [PAGE ...]

Each PAGE is our Export's MusicXML of a head (scripts/multi_horn_page.py or
the GUI). Prints, per page, the whole-beat shift that lines it up with the
reference, then per voice (upper, lower, both pooled): WRITTEN F1 (the same
spot and pitch), HEARD F1 (the right pitch within an eighth), how many exact
matches also have the reference's length, and the staccato and tuplet marks'
agreement; then the bars where either voice misses most. Two pages of the
same melody (a head in and a head out) scored against one reference are the
overfitting check: rules tuned on one should not read much better than the
other. swingscribe.horn_score does the reading and matching (mir_eval).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("pages", type=Path, nargs="+")
    parser.add_argument("--shift", type=float, default=None, help="beats; default: searched")
    parser.add_argument("--bars", type=int, default=12, help="worst bars to list")
    args = parser.parse_args(argv)
    from swingscribe import horn_score

    reference = horn_score.read_page(args.reference)
    print(
        f"reference {args.reference.name}: {reference.bars} bars, "
        f"{len(reference.upper)} upper + {len(reference.lower)} lower notes, "
        f"{reference.graces} graces"
    )
    for page in args.pages:
        ours = horn_score.read_page(page)
        result = horn_score.compare(reference, ours, args.shift)
        shift = result["shift_beats"]
        print(
            f"\n{page.name}: {len(ours.upper)} upper + {len(ours.lower)} lower notes, "
            f"shifted {shift:+.0f} beats"
        )
        print(
            "  voice   written P/R/F1          heard P/R/F1            value  "
            "stacc(both/ref/ours)  tuplet(both/ref/ours)"
        )
        for voice in ("upper", "lower", "both"):
            r = result[voice]
            w, h = r["written"], r["heard"]
            s, t = r["staccato"], r["tuplet"]
            print(
                f"  {voice:6s}  {w['precision']:.3f} {w['recall']:.3f} {w['f1']:.3f}"
                f"     {h['precision']:.3f} {h['recall']:.3f} {h['f1']:.3f}"
                f"     {r['value']:.3f}  "
                f"{s['both']:3d}/{s['reference_only']:3d}/{s['ours_only']:3d}"
                f"            {t['both']:3d}/{t['reference_only']:3d}/{t['ours_only']:3d}"
            )
        misses: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        for row in horn_score.bar_report(reference, ours, shift):
            k = 0 if row["voice"] == "upper" else 2
            misses[row["bar"]][k] += 1
            misses[row["bar"]][k + 1] += 0 if row["hit"] else 1
        worst = sorted(misses.items(), key=lambda kv: -(kv[1][1] + kv[1][3]))[: args.bars]
        print(
            "  worst bars (reference bar: upper missed/of, lower missed/of): "
            + ", ".join(f"{b}: {m[1]}/{m[0]} {m[3]}/{m[2]}" for b, m in sorted(worst))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
