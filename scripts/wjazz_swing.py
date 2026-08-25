"""Measure swing timing against the Weimar Jazz Database (plan §6 layer 2).

    uv run python scripts/wjazz_swing.py --db path/to/wjazzd.db

WJazzD annotates 456 jazz solos with per-note onsets AND human-tapped beat
positions, both in seconds. That makes it possible to run our own swing
estimator with our transcriber taken completely out of the loop — **no audio
is needed for any of this**, which is why it is worth doing long before the
audio-aligned regression set the plan schedules for M6.

It answers three questions that three benchmark tunes could not:

1. Is the offbeat phase spread we measure real jazz, or our own onset error?
2. Does BUR track the human `rhythmfeel` label?
3. Does the short note's absolute duration stay constant across tempo, as
   plan §5 hypothesises?

NOTHING this reads may be committed. The notes are transcriptions of
commercial recordings (plan §12), and WJazzD is ODbL — share-alike on the
database and any substantial derivative. Only the aggregate numbers it prints
may go in the repo; `docs/wjazzd.md` holds the last run's.

Get the database from https://jazzomat.hfm-weimar.de/download/download.html
(42.5 MB, ODbL). Keep it outside the repo.
"""

import argparse
import random
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from swingscribe.stages.swing import bur_from_phase, dominant_phase, offbeat_phases

BIN_WIDTH = 0.02
CLUSTER_WIDTH = 0.06
OFFBEAT_RANGE = (0.35, 0.85)
MIN_BEATS = 40
MIN_NOTES = 100
MIN_OFFBEATS = 30
TEMPO_BANDS = [(100, 140), (140, 180), (180, 220), (220, 280), (280, 999)]


def load(db_path: Path):
    db = sqlite3.connect(db_path)
    solos = {
        r[0]: {"tempo": r[1], "feel": r[2], "instrument": r[3], "style": r[4]}
        for r in db.execute("select melid, avgtempo, rhythmfeel, instrument, style from solo_info")
    }
    onsets: dict[int, list[float]] = defaultdict(list)
    beats: dict[int, list[float]] = defaultdict(list)
    for melid, onset in db.execute("select melid, onset from melody order by melid, onset"):
        onsets[melid].append(onset)
    for melid, onset in db.execute("select melid, onset from beats order by melid, onset"):
        beats[melid].append(onset)
    return solos, onsets, beats


def measure(onsets: list[float], beats: list[float]) -> dict | None:
    """Offbeat phase statistics for one solo, or None if too little evidence."""
    if len(beats) < MIN_BEATS or len(onsets) < MIN_NOTES:
        return None
    phases = [p for _, p in offbeat_phases(onsets, beats, *OFFBEAT_RANGE)]
    if len(phases) < MIN_OFFBEATS:
        return None
    found = dominant_phase(phases, BIN_WIDTH, CLUSTER_WIDTH)
    if found is None:
        return None
    phase, concentration, _ = found
    return {
        "phase": phase,
        "bur": bur_from_phase(phase),
        "spread": statistics.pstdev(phases),
        "concentration": concentration,
        "n_offbeats": len(phases),
    }


def noise_floor(solos, onsets, beats, seed: int = 0) -> float:
    """The BUR that onsets with NO feel at all produce.

    Each solo's notes are re-scattered uniformly inside their own beats, which
    destroys the feel while keeping note density and the real beat grid. Any
    measured BUR at or below the result is "no swing detected" rather than a
    reading of a subtle one — without this, a Latin solo appears to swing at
    1.43 purely because the offbeat region (0.35–0.85) is asymmetric about 0.5.
    """
    rng = random.Random(seed)
    floors = []
    for melid in solos:
        grid = beats[melid]
        if len(grid) < MIN_BEATS or len(onsets[melid]) < MIN_NOTES:
            continue
        scattered = [
            grid[i] + rng.uniform(0.0, 1.0) * (grid[i + 1] - grid[i])
            for i in range(len(grid) - 1)
            for _ in range(2)
        ]
        found = measure(scattered, grid)
        if found:
            floors.append(found["bur"])
    return statistics.median(floors) if floors else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure swing timing against the Weimar Jazz Database."
    )
    parser.add_argument("--db", type=Path, required=True, help="path to wjazzd.db")
    args = parser.parse_args()

    solos, onsets, beats = load(args.db)
    rows = []
    for melid, info in solos.items():
        found = measure(onsets[melid], beats[melid])
        if found:
            rows.append({**info, **found})
    print(f"{len(solos)} solos in the database, {len(rows)} with enough evidence to measure\n")

    swing = [r for r in rows if (r["feel"] or "").startswith("SWING")]

    print("=" * 70)
    print("1. How tightly does real jazz place its offbeats?")
    print("=" * 70)
    spreads = sorted(r["spread"] for r in swing)
    q = statistics.quantiles(spreads, n=10)
    print(f"  {len(swing)} SWING solos, human onsets and human beats:")
    print(
        f"    phase spread  median {statistics.median(spreads):.3f}  "
        f"10th {q[0]:.3f}  90th {q[8]:.3f}"
    )
    print("    our benchmark solos, from audio: 0.106 - 0.134")
    print("    uniform random noise:            0.144")

    print()
    print("=" * 70)
    print("2. Does BUR follow the human rhythmfeel label?")
    print("=" * 70)
    floor = noise_floor(solos, onsets, beats)
    print(f"  no-feel floor (randomised onsets): BUR {floor:.2f}\n")
    by_feel: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_feel[(row["feel"] or "?").split("_")[0]].append(row)
    print(f"  {'feel':10s} {'n':>4s} {'BUR':>6s} {'spread':>8s}   verdict")
    for feel, group in sorted(by_feel.items(), key=lambda kv: -len(kv[1])):
        if len(group) < 5:
            continue
        bur = statistics.median([g["bur"] for g in group])
        print(
            f"  {feel:10s} {len(group):4d} {bur:6.2f} "
            f"{statistics.median([g['spread'] for g in group]):8.3f}   "
            f"{'swung' if bur > floor else 'at/below the floor'}"
        )

    print()
    print("=" * 70)
    print("3. Plan section 5's hypothesis: is the SHORT note constant across tempo?")
    print("=" * 70)
    print(f"  {'tempo':>12s} {'n':>4s} {'BUR':>6s} {'short note':>14s}")
    for low, high in TEMPO_BANDS:
        group = [r for r in swing if r["tempo"] and low <= r["tempo"] < high]
        if len(group) < 5:
            continue
        shorts = sorted((1 - r["phase"]) * 60000.0 / r["tempo"] for r in group)
        quart = statistics.quantiles(shorts, n=4)
        print(
            f"  {low:5d}-{high:<6d} {len(group):4d} "
            f"{statistics.median([g['bur'] for g in group]):6.2f} "
            f"{statistics.median(shorts):8.0f} ms ({quart[0]:.0f}-{quart[2]:.0f})"
        )

    mid = [r for r in swing if r["tempo"] and 140 <= r["tempo"] < 280]
    shorts = sorted((1 - r["phase"]) * 60000.0 / r["tempo"] for r in mid)
    burs = sorted(r["bur"] for r in mid)
    print(f"\n  140-280 bpm, n={len(mid)}:")
    print(
        f"    BUR        median {statistics.median(burs):.2f}  "
        f"10th-90th {statistics.quantiles(burs, n=10)[0]:.2f}-"
        f"{statistics.quantiles(burs, n=10)[8]:.2f}"
    )
    print(
        f"    short note median {statistics.median(shorts):.0f} ms  "
        f"10th-90th {statistics.quantiles(shorts, n=10)[0]:.0f}-"
        f"{statistics.quantiles(shorts, n=10)[8]:.0f} ms"
    )


if __name__ == "__main__":
    main()
