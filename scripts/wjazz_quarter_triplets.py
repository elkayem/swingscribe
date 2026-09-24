"""Quarter-note triplet truth from WJazzD's tatum, on the annotator's own onsets.

    uv run python scripts/wjazz_quarter_triplets.py --db wjazz/wjazzd.db

D28 asked whether a timing rule can read the figure -- three equal notes
over a half note, at 0, 2/3 and 4/3 of a beat pair. The hand scores hold
17 of them; WJazzD files every note at a tatum, so it labels the figure at
scale. For every 4/4 solo this takes each half-note unit (beats 1-2, 3-4)
holding exactly three onsets before 1.8 of the unit as a CANDIDATE, with
the raw phases of its onsets on the annotator's grid, the notes' held
lengths, the next onset's position and the solo's own swung "and"; it is
TRUE when the annotator filed the three at 0, 2/3, 4/3. It also counts the
true figures the candidate shape cannot see, and scores the shipped
interval rule (`quantize.quarter_triplet_pairs`) and lattice variants for
precision and recall, by tempo band.

Measured 2026-09-23: 116 figures in 197,000 notes; 8 in the candidate
shape among 12,737 units; every rule reads precision 0.00-0.02 on the
annotator's own onsets, because the real figures sit at 0.15, 0.80, 1.43
of the unit, inside the spread of "one, and, and-of-two". Aggregates only
leave this script (plan section 12).
"""

from __future__ import annotations

import argparse
import bisect
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import wjazz_quantize as wq  # noqa: E402

FIGURE_END = 1.8  # of the unit; an onset from here on is the next beat, early


def candidates(db) -> tuple[list[dict], Counter, int]:
    """(candidate units, true figures outside the candidate shape, true total)."""
    rows: list[dict] = []
    hidden: Counter = Counter()
    true_total = 0
    for (melid,) in db.execute("select melid from solo_info order by melid"):
        solo = wq.load_solo(db, melid)
        if solo is None or solo["period"] != 4:
            continue
        grid = solo["grid"]
        if len(grid) < 8:
            continue
        notes = solo["notes"]
        bpm = 60.0 / statistics.median(b - a for a, b in zip(grid, grid[1:], strict=False))
        by_beat: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
        for n in notes:
            i = bisect.bisect_right(grid, n["onset"]) - 1
            if i < 0 or i + 1 >= len(grid):
                continue
            length = grid[i + 1] - grid[i]
            by_beat[i].append(
                ((n["onset"] - grid[i]) / length, n["duration"] / length, n["position"])
            )
        ands = [
            b[1][0] for b in by_beat.values() if len(b) == 2 and b[0][0] < 0.15 and b[1][0] > 0.4
        ]
        swing_and = statistics.median(ands) if len(ands) >= 10 else None
        anchor_i = bisect.bisect_left(grid, solo["anchor"]) if solo["anchor"] is not None else 0

        truths: set[int] = set()
        for k in range(len(notes) - 2):
            p0, p1, p2 = (notes[k + j]["position"] for j in range(3))
            if (
                abs(p1 - p0 - 2 / 3) < 0.01
                and abs(p2 - p1 - 2 / 3) < 0.01
                and abs(p0 - round(p0)) < 0.01
            ):
                true_total += 1
                truths.add(int(round(p0)))
                if int(round(p0)) % 2:
                    hidden["starts on beat two or four"] += 1

        for i in range(anchor_i, len(grid) - 2, 2):
            unit = sorted(
                list(by_beat.get(i, []))
                + [(1 + ph, dur, pos) for ph, dur, pos in by_beat.get(i + 1, [])]
            )
            figure = [u for u in unit if u[0] < FIGURE_END]
            following = [u[0] for u in unit if u[0] >= FIGURE_END]
            nxt = by_beat.get(i + 2, [])
            next_phase = following[0] if following else (2 + nxt[0][0] if nxt else None)
            if not figure:
                continue
            unit_pos = int(round(figure[0][2]))
            if len(figure) != 3:
                if unit_pos in truths:
                    hidden[f"unit holds {len(figure)} onsets before {FIGURE_END}"] += 1
                continue
            rel = [u[2] - unit_pos for u in figure]
            rows.append(
                {
                    "bpm": bpm,
                    "f": [u[0] for u in figure],
                    "dur": [u[1] for u in figure],
                    "next": next_phase,
                    "swing_and": swing_and,
                    "rel": tuple(round(x * 12) / 12 for x in rel),
                    "true": abs(rel[0]) < 0.01
                    and abs(rel[1] - 2 / 3) < 0.01
                    and abs(rel[2] - 4 / 3) < 0.01,
                }
            )
    return rows, hidden, true_total


def band(bpm: float) -> str:
    return "slow<120" if bpm < 120 else "mid120-200" if bpm < 200 else "fast>=200"


def shipped(r: dict) -> bool:
    f = r["f"]
    gaps = [f[1] - f[0], f[2] - f[1]]
    return f[0] <= 0.25 and all(0.58 <= g <= 0.80 for g in gaps) and max(gaps) / min(gaps) <= 1.25


def lattice(tol: float, next_min: float | None = None):
    def rule(r: dict) -> bool:
        f = r["f"]
        ok = abs(f[0]) <= tol and abs(f[1] - 2 / 3) <= tol and abs(f[2] - 4 / 3) <= tol
        if ok and next_min is not None:
            ok = r["next"] is None or r["next"] >= next_min
        return ok

    return rule


def summarize(name: str, rule, rows: list[dict]) -> None:
    tp = fp = fn = 0
    by: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        hit = rule(r)
        if hit and r["true"]:
            tp += 1
            by[band(r["bpm"])][0] += 1
        elif hit:
            fp += 1
            by[band(r["bpm"])][1] += 1
        elif r["true"]:
            fn += 1
    print(
        f"  {name:36s} adopted {tp + fp:5d}  true {tp:3d}  precision {tp / max(1, tp + fp):.2f}  "
        f"recall {tp / max(1, tp + fn):.2f}  "
        + "  ".join(f"{k}: {v[0]}/{v[0] + v[1]}" for k, v in sorted(by.items()))
    )


def spread(label: str, subset: list[dict]) -> None:
    for k in range(3):
        vals = sorted(r["f"][k] for r in subset)
        if vals:
            n = len(vals)
            print(
                f"  {label:5s} onset {k}: median {vals[n // 2]:.3f}  "
                f"10th {vals[n // 10]:.3f}  90th {vals[9 * n // 10]:.3f}  n={n}"
            )
    if subset:
        held = statistics.median(statistics.mean(r["dur"]) for r in subset)
        print(f"  {label:5s} held length, mean of the three: median {held:.2f} beats")
        nxt = [r["next"] for r in subset if r["next"] is not None]
        if nxt:
            print(f"  {label:5s} next onset after the unit: median {statistics.median(nxt):.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    args = parser.parse_args()
    db = sqlite3.connect(str(args.db))
    rows, hidden, true_total = candidates(db)
    true_rows = [r for r in rows if r["true"]]
    print(
        f"annotated quarter-note triplets: {true_total}; candidate units: {len(rows)}; "
        f"true among candidates: {len(true_rows)}"
    )
    print(f"true figures outside the candidate shape: {dict(hidden)}")
    print("rules on the candidate units:")
    summarize("shipped interval rule", shipped, rows)
    for tol in (0.06, 0.08, 0.10, 0.12):
        summarize(f"lattice tol {tol}", lattice(tol), rows)
    for tol in (0.08, 0.10):
        summarize(f"lattice tol {tol}, next onset >= 1.9", lattice(tol, next_min=1.9), rows)
    print("phase of the three onsets, true against false candidates:")
    spread("true", true_rows)
    spread("false", [r for r in rows if not r["true"]])
    print("what the annotator filed where lattice 0.10 adopts a false one (twelfths of a beat):")
    filed = Counter(r["rel"] for r in rows if not r["true"] and lattice(0.10)(r))
    for rel, n in filed.most_common(8):
        print(f"  {n:4d}  {tuple(round(x, 3) for x in rel)}")
    for label, subset in (
        ("true figures", true_rows),
        ("false lattice adoptions", [r for r in rows if not r["true"] and lattice(0.10)(r)]),
    ):
        sw = [r["swing_and"] for r in subset if r["swing_and"] is not None]
        if sw:
            print(f"  swung 'and' of the solos holding {label}: median {statistics.median(sw):.3f}")


if __name__ == "__main__":
    main()
