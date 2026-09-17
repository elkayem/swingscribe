"""Which beat is beat 1? A truth table for the automatic downbeat, from references.

    uv run python scripts/downbeat_truth.py --card <run_eval --json output>

A track the listener has not given a downbeat gets one from
`meter._auto_anchor`: the phase the tracker's downbeat layer agrees with most
often, over the WHOLE track. Until the references were read for bar lines
(score_bars.py, D32) nobody could say how often that is right. Now every
track scored against a reference knows its true phase: the matched notes
vote on the repaired beat grid (`score_bars.bars_on_grid`), exactly as the
Omnibook's bar 1 is placed.

Reads what `run_eval` already cached -- its notes, its beat grids, and the
card it wrote with `--json` (for the WJazzD solos' melids and windows) -- so
it costs no audio and no model. Prints one row per track: the truth and its
share, and each candidate rule's answer. Nothing here is pinned; it is the
instrument for changing the rule, and aggregate numbers only leave it.
"""

import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import run_eval  # noqa: E402

SOLO_MARGIN_S = run_eval.SOLO_MARGIN_S


def repaired_grid(grid: dict, sidecar: dict, config):
    """(beat times, Beat objects, pulses per bar) -- the grid the page uses."""
    from swingscribe.notation import meter_from_settings
    from swingscribe.stages import meter

    overrides = {
        key: sidecar[key]
        for key in ("time_signature", "pulses_per_bar")
        if sidecar.get(key) is not None
    }
    meter_config = config.meter.model_copy(update=overrides)
    duration = grid.get("duration") or grid["beats"][-1]
    repaired, _ = meter.bar_grid(grid["beats"], grid.get("downbeats", []), meter_config, duration)
    _signature, pulses = meter_from_settings(
        sidecar.get("time_signature"), sidecar.get("pulses_per_bar"), config
    )
    return [beat.time for beat in repaired], repaired, pulses


def anchors_for(theirs: list[tuple[float, int]], notes: list[dict]) -> list[tuple[float, float]]:
    """(reference position, heard onset) for every true pitch match."""
    from swingscribe.alignment import measured_transposition

    ours = [(float(n["onset"]), int(n["pitch"])) for n in notes]
    offset, aligned = measured_transposition([p for _, p in theirs], [p for _, p in ours])
    return [
        (theirs[ri][0], ours[ei][0])
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and theirs[ri][1] == ours[ei][1] + offset
    ]


def marked_beats(times: list[float], downbeats: list[float]) -> list[int]:
    """Indices of grid beats the tracker's downbeat layer marks (within 50 ms)."""
    import bisect

    marked = []
    for downbeat in downbeats:
        index = bisect.bisect_left(times, downbeat)
        near = [i for i in (index - 1, index) if 0 <= i < len(times)]
        if not near:
            continue
        best = min(near, key=lambda i: abs(times[i] - downbeat))
        if abs(times[best] - downbeat) <= 0.05:
            marked.append(best)
    return marked


def vote(marked: list[int], pulses: int) -> tuple[int | None, float]:
    """(winning phase, its share) of the marked beats; (None, 0) with none."""
    if not marked:
        return None, 0.0
    counts = Counter(index % pulses for index in marked)
    phase, count = counts.most_common(1)[0]
    return phase, count / len(marked)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--card", type=Path, required=True, help="run_eval's --json output")
    parser.add_argument("--db", type=Path, default=Path("wjazz/wjazzd.db"))
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    parser.add_argument("--margin", type=float, default=20.0, help="seconds around the span")
    args = parser.parse_args()

    import score_benchmark

    from swingscribe import mscz
    from swingscribe.score_bars import bars_on_grid
    from swingscribe.stages import meter
    from swingscribe.wjazz import notated_beats

    card = json.loads(args.card.read_text(encoding="utf-8"))
    runs = json.loads(run_eval.notes_cache(args.step_cost, args.dip_db).read_text("utf-8"))
    grids = json.loads(run_eval.GRIDS_CACHE.read_text(encoding="utf-8"))
    config = run_eval.eval_config()
    db = sqlite3.connect(args.db) if args.db.is_file() else None

    # (label, set, run name, reference positions, bar, window or None)
    jobs = []
    by_audio = {audio: score for audio, score, *_ in score_benchmark.TUNES.values()}
    for name in sorted(runs):
        if run_eval.take_of(name) is not None or name not in by_audio:
            continue
        score = mscz.parse_any(run_eval.BENCH / by_audio[name])
        which = "omnibook" if run_eval.is_omnibook(name) else "mscz"
        theirs = [(n.position, n.pitch) for n in score.melody]
        jobs.append((Path(name).stem, which, name, theirs, float(score.beats_per_bar), None))
    for key, entry in sorted(card.get("wjazz", {}).items()):
        if db is None or "melid" not in entry or run_eval.take_of(key) is not None:
            continue
        name = entry.get("run") or key.split(" [")[0]
        theirs, bar = notated_beats(db, entry["melid"])
        if not theirs or name not in runs:
            continue
        window = (entry["solo_start"] - SOLO_MARGIN_S, entry["solo_end"] + SOLO_MARGIN_S)
        jobs.append((Path(key).stem, "wjazz", name, theirs, bar, window))

    rows = []
    for label, which, name, theirs, bar, window in jobs:
        track = run_eval.track_of(name)
        if track not in grids:
            continue
        sidecar_path = run_eval.BENCH / f"{track}.swingscribe.json"
        sidecar = json.loads(sidecar_path.read_text("utf-8")) if sidecar_path.is_file() else {}
        times, _repaired, pulses = repaired_grid(grids[track], sidecar, config)
        if pulses != round(bar):
            continue
        notes = runs[name]["notes"]
        if window is not None:
            notes = [n for n in notes if window[0] <= n["onset"] <= window[1]]
        if not notes:
            continue
        anchors = anchors_for(theirs, notes)
        quarters = max(p for p, _ in theirs) - min(p for p, _ in theirs)
        # Reference positions need not start at a bar line's zero (WJazzD's
        # pickup bars are negative); only the phase is read here.
        truth = bars_on_grid(anchors, times, quarters, pulses)
        if not truth["trusted"]:
            rows.append((which, label, None, truth["share"], {}, len(anchors)))
            continue
        span = (min(n["onset"] for n in notes), max(n["onset"] for n in notes))
        marked = marked_beats(times, grids[track].get("downbeats", []))

        def inside(lo, hi, marked=marked, times=times):
            return [i for i in marked if lo <= times[i] <= hi]

        shipped = meter.bar_grid(
            grids[track]["beats"],
            grids[track].get("downbeats", []),
            config.meter.model_copy(
                update={
                    key: sidecar[key]
                    for key in ("time_signature", "pulses_per_bar")
                    if sidecar.get(key) is not None
                }
            ),
            grids[track].get("duration") or grids[track]["beats"][-1],
            near=span,
        )[1]
        shipped_phase = (
            min(range(len(times)), key=lambda i: abs(times[i] - shipped[0].anchor)) % pulses
            if shipped
            else None
        )
        candidates = {
            "shipped": (shipped_phase, 1.0),
            "global": vote(marked, pulses),
            "span": vote(inside(*span), pulses),
            "span+m": vote(inside(span[0] - args.margin, span[1] + args.margin), pulses),
        }
        stored = sidecar.get("anchor")
        if stored is not None:
            nearest = min(range(len(times)), key=lambda i: abs(times[i] - stored))
            candidates["stored"] = (nearest % pulses, 1.0)
        rows.append((which, label, truth["phase"], truth["share"], candidates, len(anchors)))

    names = ["shipped", "global", "span", "span+m", "stored"]
    print(
        f"{'set':9s}{'track':40s}{'truth':>6s}{'share':>7s}  " + "".join(f"{n:>14s}" for n in names)
    )
    tally = {which: {n: [0, 0] for n in names} for which in ("mscz", "omnibook", "wjazz")}
    for which, label, truth, share, candidates, _n in rows:
        if truth is None:
            print(
                f"{which:9s}{label[:39]:40s}{'-':>6s}{share:7.2f}  (grid does not carry the pulse)"
            )
            continue
        cells = []
        for n in names:
            if n not in candidates or candidates[n][0] is None:
                cells.append(f"{'-':>14s}")
                continue
            phase, confidence = candidates[n]
            right = phase == truth
            tally[which][n][0] += right
            tally[which][n][1] += 1
            mark = "" if right else f" ({(phase - truth) % 4:+d})"
            cells.append(f"{phase}@{confidence:.2f}{mark:>6s}".rjust(14))
        print(f"{which:9s}{label[:39]:40s}{truth:6d}{share:7.2f}  " + "".join(cells))
    print()
    for which, by_name in tally.items():
        line = ", ".join(f"{n} {r}/{t}" for n, (r, t) in by_name.items() if t)
        print(f"{which}: {line}")
    shares = [share for _w, _l, truth, share, _c, _n in rows if truth is not None]
    if shares:
        untrusted = sum(1 for row in rows if row[2] is None)
        print(
            f"\ntruth share median {statistics.median(shares):.2f}; {untrusted} track(s) with no "
            "trustworthy truth (the grid, not the downbeat)"
        )


if __name__ == "__main__":
    main()
