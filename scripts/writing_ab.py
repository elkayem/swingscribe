"""Writing research, round 2: rules for the classes the triples expose.

    uv run python scripts/writing_ab.py --db wjazz/wjazzd.db --a1b
    uv run python scripts/writing_ab.py --db wjazz/wjazzd.db --rules all --json out.json
    uv run python scripts/writing_ab.py --db wjazz/wjazzd.db --rules "late downbeat 3" \
        --notes snapshot-notes.json --grids snapshot-grids.json

docs/triples.md (A1) found that 82% of the rhythm distance between our page
and a human's is there with PERFECT onsets on a perfect grid: transcriber
convention. It named the classes. This script asks two things of them
(docs/writing-round2.md):

- **A1b** (`--a1b`): are the half-beat displacements -- an offbeat written
  on a beat, a downbeat written on an "and", the largest class -- the page's
  OMR losing time (the displaced notes sit in or after a page bar that does
  not fill its signature, `evaluation.reader_bars`), or a transcriber's
  reading? It also asks whether they come as phrases or single notes,
  whether a note only one side has sits beside them, and whether any
  feature of the timing predicts the page's anticipation.
- **The rules** (`--rules`): each candidate switched ON by environment
  override (every Config the stages build reads it, and every worker
  inherits it), against the shipped defaults, on three sets:

  1. the triples' (a) row -- WJazzD's onsets on WJazzD's grid, no hearing
     and no grid error -- and (c), our own notes, through
     `scripts/triples.py`'s own builders, paired over the eight triples;
  2. the twelve hand scores and the Omnibook sides, through `run_eval`'s
     own notation path (`notate_run`, `score_notation_page`), paired by
     recording with `evaluation.paired_change`, located pages trusted on
     both sides (`run_eval.TRUSTED_FIELDS`), default takes only;
  3. the WJazzD quantizer instrument (`scripts/wjazz_quantize.py`), for
     COLLATERAL only -- the notes a rule drops (D36: it judges nothing
     else).

  Plus the notes each set's pages WRITE: a rule that wins a score by losing
  heard notes is not a win (D37).
- **Why a rule does not transfer** (`--moved`, with `--rules`): for every
  matched page note the rule moves, whether the page writes it where the
  rule put it, where it was, or neither, and whether the page's beat holds
  more notes than ours (a note we did not hear). Counts only.

No audio is read and nothing is written to the harness caches: pass
SNAPSHOT copies of `.benchmark-notes-c0.2-d0.0.json` and
`.benchmark-grids.json` with --notes/--grids when run_eval may be rewriting
them. WJazzD is ODbL and the pages are derivatives of commercial
recordings: only aggregate numbers leave this script.
"""

from __future__ import annotations

import argparse
import bisect
import contextlib
import io
import json
import logging
import os
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import run_eval  # noqa: E402
import triples as triples_script  # noqa: E402
import wjazz_quantize  # noqa: E402

from swingscribe.triples import VALUE_CLASSES  # noqa: E402

# Each candidate rule, switched ON (docs/writing-round2.md), by environment
# override. Several settings of one rule are separate rows.
RULES = {
    "late downbeat 2": {"SWINGSCRIBE_QUANTIZE__LATE_DOWNBEAT_MAX_ONSETS": "2"},
    "late downbeat 3": {"SWINGSCRIBE_QUANTIZE__LATE_DOWNBEAT_MAX_ONSETS": "3"},
    "isolated lag 2": {"SWINGSCRIBE_QUANTIZE__ISOLATED_LAG_MAX_ONSETS": "2"},
    "isolated lag 3": {"SWINGSCRIBE_QUANTIZE__ISOLATED_LAG_MAX_ONSETS": "3"},
    "tuplet pushed last": {"SWINGSCRIBE_QUANTIZE__TUPLET_PUSHED_LAST": "true"},
    "hold to beat 1": {"SWINGSCRIBE_NOTATE__HOLD_TO_BEAT": "1"},
    "hold to beat 2": {"SWINGSCRIBE_NOTATE__HOLD_TO_BEAT": "2"},
    "legato cap a quarter": {"SWINGSCRIBE_NOTATE__LEGATO_CAP": "1.0"},
    # Not new: R31's ballad grids at the value they shipped with, for the
    # "page sixteenth written on an eighth" class (docs/triples.md puts it
    # on the one ballad), read on the same three sets as the new rules.
    "ballad grids (R31)": {"SWINGSCRIBE_QUANTIZE__SLOW_BEAT_S": "0.7"},
}
PAGE_MEASURES = ("rhythm", "value", "on_the_bar", "edit_cost")
TRIPLE_MEASURES = ("rhythm", "value", "coverage", "on_the_bar")
TOLERANCE = 0.002
HALF_BEAT = ("offbeat written on a beat", "downbeat written on an and")
# Classes whose counts on (a) each rule is read against (docs/triples.md).
WATCHED = (
    "hit",
    "downbeat written on the e",
    "offbeat written late (dotted figure)",
    "triplet read binary",
    "binary read as triplet",
    "offbeat written on a beat",
    "downbeat written on an and",
    "page sixteenth written on an eighth",
    "a 32nd apart",
    "a beat or more apart",
)


@contextlib.contextmanager
def environment(overrides: dict[str, str]):
    saved = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def quietly(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def change_cells(before: list[float], after: list[float], recordings=None) -> dict:
    from swingscribe.evaluation import paired_change

    c = paired_change(before, after, recordings, tolerance=TOLERANCE)
    return {
        "n": c.n,
        "mean": round(c.mean, 4),
        "low": round(c.low, 4),
        "high": round(c.high, 4),
        "up": c.up,
        "down": c.down,
        "level": c.level,
        "p": round(c.p, 3),
        "decided": c.decided,
    }


def cell_text(cell: dict) -> str:
    mark = "*" if cell["decided"] else " "
    return (
        f"{cell['mean']:+.4f} [{cell['low']:+.4f}, {cell['high']:+.4f}]{mark} "
        f"{cell['up']}/{cell['down']} p={cell['p']:.2f}"
    )


# ── A1b: the half-beat displacements ───────────────────────────────────────


def a1b(db) -> dict:
    """Where the (a) row's half-beat displacements come from: the page's
    OMR (bars that do not fill), a note only one side has, or neither.
    Aggregates only."""
    from swingscribe import mscz
    from swingscribe import triples as tri
    from swingscribe.benchmark import notation_notes
    from swingscribe.evaluation import reader_bars

    totals: Counter = Counter()
    runs_by_length: Counter = Counter()
    near_beat: Counter = Counter()
    per_triple = {}
    for name, melid, _track, page_rel, kind in triples_script.TRIPLES:
        solo = wjazz_quantize.load_solo(db, melid)
        page_path = run_eval.BENCH / page_rel
        page = mscz.parse_any(page_path)
        located = tri.locate_solo(page, [(n["position"], n["pitch"]) for n in solo["notes"]])
        crop = tri.crop(page, located["lo"], located["hi"])
        notation = triples_script.notate_annotation(solo)
        ours = notation_notes(notation)
        theirs = [(n.position, n.duration, n.pitch) for n in crop.melody]
        kinds = tri.disagreements(ours, theirs)
        bars = reader_bars(page_path)
        fills = [bar.fills for bar in bars]
        overrun = [bar.overrun for bar in bars]
        first_bar = located["first_bar"]
        rows = {ri: (ei, cls, ppos, opos) for ri, ei, cls, ppos, opos in kinds["per_note"]}
        matched_ours = {ei for ei, *_ in rows.values()}
        pairs, _ = wjazz_quantize.align(solo["notes"], ours)
        source = {j: k for k, j in pairs}
        grid = solo["grid"]
        counts: Counter = Counter()
        displaced = [ri for ri in sorted(rows) if rows[ri][1] in HALF_BEAT]
        for ri in displaced:
            if ri - 1 not in displaced:  # a run starts here: how long is it?
                length = 1
                while ri + length in displaced:
                    length += 1
                runs_by_length[min(length, 4)] += 1
        for ri in displaced:
            ei, cls, ppos, opos = rows[ri]
            bar = crop.melody[ri].bar
            standing = sum(overrun[first_bar - 1 : bar - 1]) % 1.0
            near = any(0 < b <= len(fills) and not fills[b - 1] for b in (bar - 1, bar, bar + 1))
            beside = not (
                (ri - 1) in rows
                and (ri + 1) in rows
                and (ei - 1) in matched_ours
                and (ei + 1) in matched_ours
            )
            if not fills[bar - 1]:
                where = "own page bar does not fill"
            elif abs(standing - 0.5) < 0.2:
                where = "page running about half a beat off"
            elif near:
                where = "next to a page bar that does not fill"
            elif beside:
                where = "bars fill; beside a note only one side has"
            else:
                where = "bars fill; both neighbours matched"
            counts[where] += 1
            counts["page earlier" if opos - ppos > 0 else "page later"] += 1
            totals[(kind, where)] += 1
            totals[where] += 1
            totals["notes"] += 1
            totals["page earlier" if opos - ppos > 0 else "page later"] += 1
        # Anticipation as a reading of timing: every matched note that
        # SOUNDED within 0.15 of a beat line and that we wrote on the beat.
        for _ri, (ei, _cls, ppos, opos) in rows.items():
            k = source.get(ei)
            if k is None:
                continue
            i = bisect.bisect_right(grid, solo["notes"][k]["onset"]) - 1
            if not 0 <= i < len(grid) - 1:
                continue
            length = grid[i + 1] - grid[i]
            phase = (solo["notes"][k]["onset"] - grid[i]) / length
            if 0.15 <= phase < 0.85 or abs(opos - round(opos)) > 1e-6:
                continue
            delta = opos - ppos
            page = (
                "beat"
                if abs(delta) < 1 / 48
                else "and before"
                if abs(delta - 0.5) < 1 / 48
                else "elsewhere"
            )
            played = solo["notes"][k]["duration"] / length
            neighbour = (ei - 1) in matched_ours
            near_beat[("all", page)] += 1
            if played >= 1.0:
                near_beat[("played a beat or more", page)] += 1
                if neighbour:
                    near_beat[("played a beat or more, note before matched", page)] += 1
        per_triple[name] = dict(counts)
    out = {
        "notes": totals["notes"],
        "by_cause": {k: v for k, v in totals.items() if isinstance(k, str) and k not in ("notes",)},
        "by_set": {f"{k[0]}: {k[1]}": v for k, v in totals.items() if isinstance(k, tuple)},
        "runs_by_length": {
            ("4+" if k == 4 else str(k)): v for k, v in sorted(runs_by_length.items())
        },
        "per_triple": per_triple,
        "near_beat": {f"{k[0]} -> page {k[1]}": v for k, v in sorted(near_beat.items())},
    }
    print(f"\n== A1b: the half-beat displacements on (a), {out['notes']} notes ==")
    for key, value in sorted(out["by_cause"].items(), key=lambda kv: -kv[1]):
        print(f"  {key:45} {value:4d}  {value / max(1, out['notes']):6.1%}")
    print("  by set:")
    for key, value in sorted(out["by_set"].items()):
        print(f"    {key:55} {value:4d}")
    print(f"  runs of consecutive displaced notes by length: {out['runs_by_length']}")
    print("  notes that sounded within 0.15 of a beat line, written on it by us:")
    for key, value in out["near_beat"].items():
        print(f"    {key:70} {value:4d}")
    return out


# ── the triples ─────────────────────────────────────────────────────────────


def triple_rows(db, runs, grids, located) -> dict:
    results = triples_script.run_all(db, runs, grids, located)
    return {r["name"]: r for r in triples_script.trusted(results)}


def triples_change(before: dict, after: dict) -> dict:
    names = sorted(set(before) & set(after))
    out = {}
    for key in ("a", "c"):
        block = {}
        for field in TRIPLE_MEASURES:
            block[field] = change_cells(
                [before[n]["inputs"][key][field] for n in names],
                [after[n]["inputs"][key][field] for n in names],
            )
        block["written"] = sum(after[n]["inputs"][key]["written"] for n in names) - sum(
            before[n]["inputs"][key]["written"] for n in names
        )
        block["classes"] = {
            cls: sum(after[n]["inputs"][key]["kinds"]["positions"][cls] for n in names)
            - sum(before[n]["inputs"][key]["kinds"]["positions"][cls] for n in names)
            for cls in WATCHED
        }
        block["rests_per_note"] = rests_per_note(after, names, key) - rests_per_note(
            before, names, key
        )
        block["values"] = {
            cls: sum(after[n]["inputs"][key]["kinds"]["values"][cls] for n in names)
            - sum(before[n]["inputs"][key]["kinds"]["values"][cls] for n in names)
            for cls in VALUE_CLASSES
        }
        out[key] = block
    return out


def rests_per_note(rows: dict, names: list[str], key: str) -> float:
    rests = sum(rows[n]["inputs"][key]["symbols"]["rests"] for n in names)
    notes = sum(rows[n]["inputs"][key]["symbols"]["notes"] for n in names)
    return rests / max(1, notes)


# ── the hand scores and the Omnibook ────────────────────────────────────────


def _page_one(task: tuple) -> dict | None:
    name, run, grid, score_path, cache_dir, env = task
    os.environ.update(env)
    run_eval._worker_setup(cache_dir)
    from swingscribe import mscz
    from swingscribe.benchmark import notation_notes, readability

    notation = quietly(run_eval.notate_run, name, run, grid)
    if notation is None or not notation.bars:
        return None
    from swingscribe.triples import disagreements

    reference = mscz.parse_any(score_path)
    agreement, result = run_eval.score_notation_page(notation, reference)
    if not result["n_matched"]:
        return None
    ours = notation_notes(notation)
    kinds = disagreements(ours, [(n.position, n.duration, n.pitch) for n in reference.melody])
    return {
        "rhythm": result["rhythm"],
        "value": result["value"],
        "on_the_bar": agreement["on_the_bar"],
        "edit_cost": result["edit_cost"],
        "coverage": result["coverage"],
        "trusted": bool(result["trusted"]),
        "written": len(ours),
        "readability": readability(notation)["readability"],
        # Wrong values by context (triples.VALUE_CLASSES): only where both
        # notes and both positions agree is a wrong length a choice of
        # length; beside a displaced note it is rhythm wearing a value.
        "values": dict(kinds["values"]),
    }


def page_tasks(runs: dict, grids: dict, db_path: Path | None) -> list[tuple[str, str, tuple]]:
    """(set, key, task) for every default-take hand score and Omnibook side."""
    import score_benchmark

    by_audio = {audio: mscz_name for audio, mscz_name, *_ in score_benchmark.TUNES.values()}
    wanted = {
        k: v
        for k, v in runs.items()
        if run_eval.take_of(k) is None
        and not run_eval.is_page(k)
        and run_eval.track_of(k) in by_audio
        and run_eval.track_of(k) in grids
    }
    wanted = quietly(run_eval.split_runs, wanted, db_path, test=False)
    out = []
    for key, run in sorted(wanted.items()):
        track = run_eval.track_of(key)
        which = "omnibook" if run_eval.is_omnibook(key) else "hand"
        out.append(
            (
                which,
                key,
                (
                    key,
                    run,
                    grids[track],
                    str(run_eval.BENCH / by_audio[track]),
                    str(run_eval.CACHE_DIR),
                ),
            )
        )
    return out


def page_scores(tasks, env: dict, jobs: int) -> dict:
    results = run_eval.parallel_map(_page_one, [(*t, env) for _s, _k, t in tasks], jobs)
    return {
        key: {**entry, "set": which}
        for (which, key, _t), entry in zip(tasks, results, strict=True)
        if entry
    }


def pages_change(before: dict, after: dict) -> dict:
    out = {}
    for which in ("hand", "omnibook"):
        keys = sorted(k for k in before if before[k]["set"] == which and k in after)
        block = {}
        for field in PAGE_MEASURES:
            rows = [
                k for k in keys if which == "hand" or (before[k]["trusted"] and after[k]["trusted"])
            ]
            block[field] = change_cells(
                [before[k][field] for k in rows],
                [after[k][field] for k in rows],
                [run_eval.recording_of(run_eval.pin_name(k)) for k in rows],
            )
        block["written"] = sum(after[k]["written"] for k in keys) - sum(
            before[k]["written"] for k in keys
        )
        block["written_down"] = sum(1 for k in keys if after[k]["written"] < before[k]["written"])
        block["readability"] = round(
            statistics.fmean(after[k]["readability"] for k in keys)
            - statistics.fmean(before[k]["readability"] for k in keys),
            4,
        )
        block["values"] = {
            cls: sum(after[k]["values"].get(cls, 0) for k in keys)
            - sum(before[k]["values"].get(cls, 0) for k in keys)
            for cls in VALUE_CLASSES
        }
        out[which] = block
    return out


# ── the notes a rule moves on the pages ─────────────────────────────────────


def page_rows(tasks, env: dict) -> dict:
    """Every page's notes, the reference's, and `triples.disagreements`'
    per-note rows, under `env` (in this process: seconds a page)."""
    from swingscribe import mscz
    from swingscribe.benchmark import notation_notes
    from swingscribe.triples import disagreements

    out = {}
    with environment(env):
        for which, key, (name, run, grid, score_path, cache_dir) in tasks:
            run_eval._worker_setup(cache_dir)
            notation = quietly(run_eval.notate_run, name, run, grid)
            if notation is None or not notation.bars:
                continue
            reference = mscz.parse_any(score_path)
            ours = notation_notes(notation)
            theirs = [(n.position, n.duration, n.pitch) for n in reference.melody]
            out[key] = (which, ours, theirs, disagreements(ours, theirs)["per_note"])
    return out


def moved_notes(tasks, env: dict) -> dict:
    """For every matched page note a rule MOVES (its place against the page's
    changed): does the page write it where the rule put it, where it was, or
    neither -- and, for neither, is the page's beat fuller than ours (a note
    we did not hear)? docs/writing-round2.md: on human onsets the late
    downbeat is right; this is what it meets on ours. Counts only."""
    before, after = page_rows(tasks, {}), page_rows(tasks, env)
    tally: Counter = Counter()
    for key, (which, _ours, theirs, rows) in before.items():
        if key not in after:
            continue
        _w, ours_after, _t, rows_after = after[key]
        now = {ri: (pp, op) for ri, _ei, _cls, pp, op in rows_after}
        for ri, _ei, _cls, pp, op in rows:
            if ri not in now:
                continue
            pp2, op2 = now[ri]
            if abs((op2 - pp2) - (op - pp)) < 1e-6:
                continue
            tally[(which, "moved")] += 1
            if abs(op2 - pp2) < 1e-6:
                tally[(which, "page = where it was moved")] += 1
            elif abs(op - pp) < 1e-6:
                tally[(which, "page = where it was")] += 1
            else:
                tally[(which, "neither")] += 1
                later = op2 - pp2 < 0
                tally[(which, "neither, page later" if later else "neither, page earlier")] += 1
                page_beat, our_beat = int(pp2 // 1 + 1e-9), int(op2 // 1 + 1e-9)
                n_page = sum(1 for p in theirs if page_beat <= p[0] < page_beat + 1 - 1e-9)
                n_ours = sum(1 for o in ours_after if our_beat <= o[0] < our_beat + 1 - 1e-9)
                if n_page > n_ours:
                    tally[(which, "neither, the page's beat fuller than ours")] += 1
    out = {f"{k[0]}: {k[1]}": v for k, v in sorted(tally.items()) if v}
    for key, value in out.items():
        print(f"    {key:60} {value:4d}")
    return out


# ── the Flex-Q instrument: collateral only ──────────────────────────────────


def flexq(db) -> dict:
    solos = list(db.execute("select melid from solo_info order by melid"))
    results = {}
    for (melid,) in solos:
        solo = wjazz_quantize.load_solo(db, melid)
        if solo is None or len(solo["grid"]) < 16:
            continue
        notation = wjazz_quantize.our_notation(solo)
        if notation is None:
            continue
        result = wjazz_quantize.measure(solo, notation)
        if result is not None:
            results[melid] = result
    overall = wjazz_quantize.aggregate(results)
    return {k: overall[k] for k in ("n_solos", "n_notes", "matched", "dropped", "page_hit_all")}


# ── the run ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    parser.add_argument("--notes", type=Path, default=run_eval.notes_cache(0.2, 0.0))
    parser.add_argument("--grids", type=Path, default=run_eval.GRIDS_CACHE)
    parser.add_argument("--a1b", action="store_true", help="the half-beat split")
    parser.add_argument(
        "--rules", default="", help="comma-separated RULES labels, or 'all'; empty for none"
    )
    parser.add_argument(
        "--sets", default="triples,pages,flexq", help="which of triples,pages,flexq to run"
    )
    parser.add_argument("--jobs", type=int, default=run_eval.default_jobs())
    parser.add_argument("--json", type=Path, default=None, help="aggregates only")
    parser.add_argument(
        "--moved",
        action="store_true",
        help="instead of scoring, count what the pages write for the notes each rule moves",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)

    db = sqlite3.connect(args.db)
    card: dict = {}
    if args.a1b:
        card["a1b"] = a1b(db)
    labels = list(RULES) if args.rules == "all" else [r for r in args.rules.split(",") if r]
    sets = set(args.sets.split(","))
    if labels and args.moved:
        runs = json.loads(args.notes.read_text(encoding="utf-8"))
        grids = json.loads(args.grids.read_text(encoding="utf-8"))
        tasks = page_tasks(runs, grids, args.db)
        card["moved"] = {}
        for label in labels:
            print(f"\n== notes moved by {label} ({RULES[label]}) ==")
            card["moved"][label] = moved_notes(tasks, RULES[label])
        labels = []
    if labels:
        runs = json.loads(args.notes.read_text(encoding="utf-8"))
        grids = json.loads(args.grids.read_text(encoding="utf-8"))
        located: dict = {}
        base_triples = triple_rows(db, runs, grids, located) if "triples" in sets else {}
        tasks = page_tasks(runs, grids, args.db) if "pages" in sets else []
        base_pages = page_scores(tasks, {}, args.jobs) if tasks else {}
        base_flexq = flexq(db) if "flexq" in sets else {}
        card["baseline"] = {
            "pages_n": {
                s: sum(1 for e in base_pages.values() if e["set"] == s)
                for s in ("hand", "omnibook")
            },
            "flexq": base_flexq,
            "triples_values": {
                key: {
                    "matched": sum(
                        r["inputs"][key]["kinds"]["matched"] for r in base_triples.values()
                    ),
                    **{
                        cls: sum(
                            r["inputs"][key]["kinds"]["values"][cls] for r in base_triples.values()
                        )
                        for cls in VALUE_CLASSES
                    },
                }
                for key in ("a", "c")
                if base_triples
            },
            "pages_values": {
                s: {
                    cls: sum(e["values"].get(cls, 0) for e in base_pages.values() if e["set"] == s)
                    for cls in VALUE_CLASSES
                }
                for s in ("hand", "omnibook")
            },
        }
        print(f"baseline: pages {card['baseline']['pages_n']}, flexq {base_flexq}")
        print(f"  wrong values by context, triples: {card['baseline']['triples_values']}")
        print(f"  wrong values by context, pages: {card['baseline']['pages_values']}")
        card["rules"] = {}
        for label in labels:
            env = RULES[label]
            block: dict = {"env": env}
            with environment(env):
                if base_triples:
                    block["triples"] = triples_change(
                        base_triples, triple_rows(db, runs, grids, located)
                    )
                if tasks:
                    block["pages"] = pages_change(base_pages, page_scores(tasks, env, args.jobs))
                if base_flexq:
                    now = flexq(db)
                    block["flexq"] = {
                        "dropped": now["dropped"] - base_flexq["dropped"],
                        "page_hit_all": round(now["page_hit_all"] - base_flexq["page_hit_all"], 4),
                    }
            card["rules"][label] = block
            report(label, block)
            if args.json:  # after every rule: a run killed part-way keeps what it measured
                args.json.write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
            sys.stdout.flush()
    if args.json:
        args.json.write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")


def nonzero(counts: dict) -> dict:
    return {k: v for k, v in counts.items() if v}


def report(label: str, block: dict) -> None:
    print(f"\n== {label} ({block['env']}) ==")
    for key, rows in block.get("triples", {}).items():
        print(f"  triples ({key}), paired over 8, written {rows['written']:+d}:")
        for field in TRIPLE_MEASURES:
            print(f"    {field:11} {cell_text(rows[field])}")
        moved = {c: v for c, v in rows["classes"].items() if v}
        print(f"    classes {moved}  rests/note {rows['rests_per_note']:+.4f}")
        print(f"    wrong values by context {nonzero(rows['values'])}")
    for which, rows in block.get("pages", {}).items():
        print(
            f"  {which}: written {rows['written']:+d} ({rows['written_down']} pages fewer), "
            f"readability {rows['readability']:+.4f}"
        )
        for field in PAGE_MEASURES:
            print(f"    {field:11} n={rows[field]['n']:2d} {cell_text(rows[field])}")
        print(f"    wrong values by context {nonzero(rows['values'])}")
    if "flexq" in block:
        print(f"  Flex-Q collateral: {block['flexq']}")


if __name__ == "__main__":
    main()
