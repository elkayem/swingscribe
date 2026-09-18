"""How many beats does our grid gain or lose on the reference's, and where?

    uv run python scripts/grid_drift.py --card <run_eval --json output>
    uv run python scripts/grid_drift.py --card ... --only Cheese Totem

For every WJazzD solo with a reference, the annotator's positions are laid
on our RAW tracker beats and on the REPAIRED grid through the same true
pitch matches `downbeat_truth.py` votes with, and (our beat coordinate -
their position) is followed along the solo. Its drift from the first notes
to the last is the number of beats our grid gained (+) or lost (-) on the
annotator's; a step in it is where. A right grid drifts ~0 with no steps.

This is the instrument that found R26 (docs/benchmark-deficiencies.md):
the tracker at double rate for a stretch, invisible to a repair that judged
one pair at a time. It costs no audio: it reads what `run_eval` cached.
Without `--quiet`, every step on the repaired grid is printed with the raw
intervals around it, what the repair kept, and the annotation's own beats
there -- the raw intervals are what a new repair rule is written against.
Aggregate numbers only leave it.
"""

import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import downbeat_truth  # noqa: E402
import run_eval  # noqa: E402

# Rolling-median window over the matched notes, and the change in it that
# counts as a step (in beats).
WINDOW = 9
STEP = 0.75
MIN_ANCHORS = 20


def rolling(values: list[float], window: int = WINDOW) -> list[float]:
    half = window // 2
    return [statistics.median(values[max(0, i - half) : i + half + 1]) for i in range(len(values))]


def steps_of(
    times: list[float], diffs: list[float]
) -> tuple[list[tuple[float, float]], list[float]]:
    """(steps as (time, change), the smoothed difference)."""
    smooth = rolling(diffs)
    raw = [
        (times[i], smooth[i] - smooth[i - 1])
        for i in range(1, len(smooth))
        if abs(smooth[i] - smooth[i - 1]) >= STEP
    ]
    merged: list[tuple[float, float]] = []
    for time, change in raw:  # steps within a second are one step
        if merged and time - merged[-1][0] < 1.0:
            merged[-1] = (merged[-1][0], merged[-1][1] + change)
        else:
            merged.append((time, change))
    return [(t, c) for t, c in merged if abs(c) >= STEP], smooth


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--card", type=Path, required=True, help="run_eval's --json output")
    parser.add_argument("--db", type=Path, default=Path("wjazz/wjazzd.db"))
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    parser.add_argument("--only", nargs="*", default=[], help="substrings of solo names")
    parser.add_argument("--quiet", action="store_true", help="one line per solo")
    args = parser.parse_args()

    from swingscribe.score_bars import beat_coordinate
    from swingscribe.wjazz import notated_beats

    card = json.loads(args.card.read_text("utf-8"))
    runs = json.loads(run_eval.notes_cache(args.step_cost, args.dip_db).read_text("utf-8"))
    grids = json.loads(run_eval.GRIDS_CACHE.read_text("utf-8"))
    config = run_eval.eval_config()
    db = sqlite3.connect(args.db)
    notation = card.get("wjazz_notation", {})

    solos = 0
    counts = {"raw": 0, "repaired": 0}
    drifts: dict[str, list[float]] = {"raw": [], "repaired": []}
    for key, entry in sorted(card.get("wjazz", {}).items()):
        if "melid" not in entry or run_eval.take_of(key) is not None:
            continue
        if args.only and not any(s.lower() in key.lower() for s in args.only):
            continue
        page = notation.get(key, {})
        name = entry.get("run") or key.split(" [")[0]
        track = run_eval.track_of(name)
        if name not in runs or track not in grids:
            continue
        theirs, _bar = notated_beats(db, entry["melid"])
        if not theirs:
            continue
        window = (
            entry["solo_start"] - run_eval.SOLO_MARGIN_S,
            entry["solo_end"] + run_eval.SOLO_MARGIN_S,
        )
        notes = [n for n in runs[name]["notes"] if window[0] <= n["onset"] <= window[1]]
        anchors = sorted(downbeat_truth.anchors_for(theirs, notes), key=lambda a: a[1])
        if len(anchors) < MIN_ANCHORS:
            continue
        sidecar_path = run_eval.BENCH / f"{track}.swingscribe.json"
        sidecar = json.loads(sidecar_path.read_text("utf-8")) if sidecar_path.is_file() else {}
        raw = grids[track]["beats"]
        repaired_times, repaired, _pulses = downbeat_truth.repaired_grid(
            grids[track], sidecar, config
        )
        rows = []
        for position, onset in anchors:
            on_raw = beat_coordinate(raw, onset)
            on_repaired = beat_coordinate(repaired_times, onset)
            if on_raw is not None and on_repaired is not None:
                rows.append((onset, on_raw - position, on_repaired - position))
        if len(rows) < MIN_ANCHORS:
            continue
        times = [r[0] for r in rows]
        raw_steps, raw_smooth = steps_of(times, [r[1] for r in rows])
        repaired_steps, repaired_smooth = steps_of(times, [r[2] for r in rows])
        result = {
            "raw": (raw_smooth[-1] - raw_smooth[0], raw_steps),
            "repaired": (repaired_smooth[-1] - repaired_smooth[0], repaired_steps),
        }
        solos += 1
        for which, (drift, steps) in result.items():
            counts[which] += len(steps)
            drifts[which].append(abs(drift))
        print(
            f"\n== {key}  tempo {entry.get('tempo')}  matched {len(rows)}  "
            f"trace steps {page.get('beat_steps')} slope {page.get('beat_slope')}"
        )
        print(
            f"   drift over solo: raw {result['raw'][0]:+.1f} beats ({len(raw_steps)} steps), "
            f"repaired {result['repaired'][0]:+.1f} beats ({len(repaired_steps)} steps)"
        )
        if args.quiet:
            continue
        for time, change in repaired_steps:
            nearby = [round(c, 1) for t, c in raw_steps if abs(t - time) < 2.0]
            print(f"   step {change:+.1f} at {time:.2f}s (raw: {nearby or 'none'})")
            lo, hi = time - 3.0, time + 2.5
            raw_here = [b for b in raw if lo <= b <= hi]
            if len(raw_here) > 1:
                gaps = " ".join(
                    f"{b - a:.3f}" for a, b in zip(raw_here, raw_here[1:], strict=False)
                )
                print(f"      raw beats {raw_here[0]:.2f}..: {gaps}")
            kept = [b for b in repaired if lo <= b.time <= hi]
            if len(kept) > 1:
                gaps = " ".join(
                    f"{b.time - a.time:.3f}{'i' if b.implied else ''}"
                    for a, b in zip(kept, kept[1:], strict=False)
                )
                print(f"      repaired  {kept[0].time:.2f}..: {gaps}")
            near = " ".join(f"{o:.2f}@{p:g}" for p, o in anchors if lo <= o <= hi)
            print(f"      annotated (onset@quarter): {near}")
    if not solos:
        print("no solo with enough matched notes")
        return
    print(
        f"\n{solos} solos: raw steps {counts['raw']}, repaired steps {counts['repaired']}; "
        f"mean |drift| raw {statistics.mean(drifts['raw']):.2f}, "
        f"repaired {statistics.mean(drifts['repaired']):.2f}; "
        f"within a beat raw {sum(1 for d in drifts['raw'] if d < 1)}, "
        f"repaired {sum(1 for d in drifts['repaired'] if d < 1)}"
    )


if __name__ == "__main__":
    main()
