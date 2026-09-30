"""Our pages on the Rhythm Perceiver's per-beat measure (docs/roadmap.md A6).

    python scripts/beat_signature.py --db wjazz/wjazzd.db
    python scripts/beat_signature.py --db wjazz/wjazzd.db --json out.json
    python scripts/beat_signature.py --notes <copy of the notes cache> --grids <copy>

Shanin, Riley and Dixon (ICASSP 2026) report "rhythm accuracy" -- the share
of beats whose 12-bin beat signature is the reference's -- of 0.53 on the
Charlie Parker Omnibook, over the 60% of tracks whose automatic beats held,
and 0.87 on Filosax. `swingscribe.beat_signature` is that measure; this
script scores three sets with it:

- the 22 located Omnibook sides against LORIA's MusicXML (the paper's
  reference too), on ALL 22 and on two analogues of the paper's "easy"
  subset: the sides whose bar lines HELD (the harness's own placement:
  on the reference's beat, and a difference trace with one steady run and
  no step), and the 60% SLOWEST sides (the paper names fast tempo first
  among what made a track hard);
- the listener's 12 hand scores (default take);
- the triples (scripts/triples.py): (a) WJazzD's human onsets on WJazzD's
  human beats through our quantizer -- the quantizer alone, the closest we
  come to the paper's ground-truth beats -- beside (c) our transcription
  on our grid and (f) Flex-Q's positions, against the same cropped page.

Each page is built exactly as `run_eval` builds it (`run_eval.notate_run`,
from the cached notes and grids). The classes are the 42 commonest
signatures of the human transcription corpus under
benchmark/Transcriptions_Other (the paper counted its 42 on Filosax,
which is not here), minus the test split and every page whose recording is
benchmarked, exactly as the figure prior is counted.

No audio is read. Only aggregates leave this script: per-page accuracies
and pooled counts of twelve-letter rhythm strings, never a note.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import run_eval  # noqa: E402

from swingscribe import beat_signature as bs  # noqa: E402

# The paper's numbers (Tables 1 and 2), for the report's margin.
PAPER = {
    "Rhythm Perceiver, Omnibook easy 60%": 0.53,
    "Perceiver without rhythm supervision, same": 0.48,
    "CRNN + qparse, same": 0.18,
    "Rhythm Perceiver, Filosax test": 0.87,
}
PAPER_OMNIBOOK = 0.53
# Share of the Omnibook the paper's easy subset kept (section 4).
EASY_SHARE = 0.6
# A page "held" its bar lines when the harness's own placement says so:
# the commonest beat difference is none, and the difference trace is one
# steady run (score_bars.difference_trace) -- no dropped or doubled beat.
HELD_OFFSET = 0.0
SETS = ("omnibook", "hand")
VIEWS = bs.VIEWS
TOP = 15


def quietly(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# ── the class inventory ─────────────────────────────────────────────────────


def corpus_counts(folder: Path, split_path: Path, log=print) -> tuple[Counter, dict]:
    """Beat signatures over the human transcription corpus, counted as the
    figure prior counts figures (scripts/figure_prior.py): bars that fill
    their signature, not doubted by the converter, quarter-note beats, one
    voice, no two onsets at one position; the recordings under benchmark/
    and the test split left out."""
    import figure_prior

    corpus = figure_prior.load_corpus(folder, log=lambda *_: None)
    corpus = figure_prior.without_test_pages(corpus, split_path, log=lambda *_: None)
    counts: Counter = Counter()
    for t in corpus:
        for bar in t.bars:
            if bar.voices != 1 or not figure_prior.bar_included(t, bar, strict=False):
                continue
            events = bs.bar_events(
                float(bar.length),
                [float(o) for o in bar.onsets],
                [(float(p), float(d)) for p, d in bar.rests],
            )
            starts = [onset for onset, _ in events]
            for beat in range(int(bar.length)):
                if beat in bar.duplicate_beats:
                    continue
                counts[bs.beat_signature(events, beat, starts=starts)] += 1
    total = sum(counts.values())
    stats = {"pages": len(corpus), "beats": total, "signatures": len(counts)}
    log(f"  corpus: {stats['pages']} pages, {total} beats, {len(counts)} distinct signatures")
    return counts, stats


def inventory_stats(counts: Counter, inventory: frozenset[str]) -> dict:
    total = sum(counts.values()) or 1
    return {
        "classes": len(inventory),
        "covered": sum(counts[s] for s in inventory) / total,
        "unsupported": counts[bs.UNSUPPORTED] / total,
        "at_least_30": sum(
            1 for s, n in counts.items() if s != bs.UNSUPPORTED and n >= bs.RARE_BELOW
        ),
        "top": [(s, bs.describe(s), n / total) for s, n in counts.most_common(TOP)],
    }


# ── one page ────────────────────────────────────────────────────────────────


def views(result: dict) -> dict:
    out = {
        v: {
            "accuracy": result[v]["accuracy"],
            "correct": result[v]["correct"],
            "beats": result[v]["beats"],
        }
        for v in VIEWS
    }
    out["onset_f1"] = dict(result["onset_f1"])
    return out


def score_page(notation, reference, inventory) -> dict:
    """Every number for one page against one parsed reference."""
    from swingscribe.score_bars import bar_line_agreement, bar_line_trace

    local = bs.against_score(notation, reference, inventory, local=True)
    strict = bs.against_score(notation, reference, inventory, local=False)
    agreement = bar_line_agreement(notation, reference)
    trace = bar_line_trace(notation, reference)
    held = (
        bool(agreement["beat_n"])
        and agreement["beat_offset"] == HELD_OFFSET
        and trace["steady"]
        and not trace["steps"]
    )
    rare = sum(
        n
        for (theirs, _ours), n in local["exact"]["confusion"].items()
        if bs.signature_class(theirs, inventory) == bs.RARE
    )
    return {
        "local": views(local),
        "global": views(strict),
        "matches": local["matches"],
        "clock_share": local["clock_share"],
        "on_the_bar": agreement["on_the_bar"],
        "beat_offset": agreement["beat_offset"],
        "steady": bool(trace["steady"]),
        "steps": len(trace["steps"]),
        "held": held,
        "unsupported_theirs": local["exact"]["unsupported"]["theirs"],
        "unsupported_ours": local["exact"]["unsupported"]["ours"],
        # ...of which an ONSET is off the twelve bins (a 32nd), not only an end
        "unsupported_ours_onsets": local["onsets"]["unsupported"]["ours"],
        "unsupported_theirs_onsets": local["onsets"]["unsupported"]["theirs"],
        "rare_theirs": rare,
        "confusion": dict(local["exact"]["confusion"]),
    }


def _page_one(task: tuple) -> dict | None:
    name, run, grid, score_path, inventory, cache_dir = task
    run_eval._worker_setup(cache_dir)
    from swingscribe import mscz

    notation = quietly(run_eval.notate_run, name, run, grid)
    if notation is None or not notation.bars:
        return None
    reference = mscz.parse_any(score_path)
    out = score_page(notation, reference, frozenset(inventory))
    track = run_eval.track_of(name)
    out["bpm"] = run_eval.span_bpm(run_eval.page_grid(track, grid)[1], tuple(run["region"]))
    return out


def select_pages(runs: dict) -> list[tuple[str, str, Path]]:
    """(set, run key, score path) for the default take of every Omnibook side
    and every hand score (a .mscz beside its recording in benchmark/)."""
    import score_benchmark

    by_audio = {audio: score for audio, score, *_ in score_benchmark.TUNES.values()}
    out = []
    for key in sorted(runs):
        track = run_eval.track_of(key)
        if run_eval.take_of(key) is not None or track not in by_audio:
            continue
        score = run_eval.BENCH / by_audio[track]
        if run_eval.is_omnibook(key):
            out.append(("omnibook", key, score))
        elif "/" not in track and score.suffix.lower() == ".mscz":
            out.append(("hand", key, score))
    return out


# ── the triples ─────────────────────────────────────────────────────────────


def triple_rows(db, runs: dict, grids: dict, inventory: frozenset[str], log=print) -> list[dict]:
    """(a), (b), (c) and (f) of every triple against its cropped page, built
    the way scripts/triples.py builds them."""
    import triples as triples_script

    from swingscribe import mscz, triples
    from swingscribe.wjazz import annotation_notation

    out = []
    for name, melid, track, page_rel, kind in triples_script.TRIPLES:
        import wjazz_quantize

        solo = wjazz_quantize.load_solo(db, melid)
        if solo is None:
            continue
        page = mscz.parse_any(run_eval.BENCH / page_rel)
        located = triples.locate_solo(page, [(n["position"], n["pitch"]) for n in solo["notes"]])
        crop = triples.crop(page, located["lo"], located["hi"])
        run, grid = runs.get(track), grids.get(track)
        fit, status = (
            quietly(triples_script.fit_for, db, track, run, melid) if run else (None, "no run")
        )
        notations = {
            "a": triples_script.notate_annotation(solo),
            "f": quietly(annotation_notation, db, melid),
        }
        if fit is not None and grid is not None:
            placed = [triples.mapped(t, fit["offset"], fit["rate"]) for t in fit["ref_on"]]
            window = (placed[0] - run_eval.SOLO_MARGIN_S, placed[-1] + run_eval.SOLO_MARGIN_S)
            notations["b"] = triples_script.notate_mapped(track, run, grid, solo, fit, window)
            notations["c"] = quietly(run_eval.notate_run, track, run, grid, region=window)
        row = {
            "name": name,
            "kind": kind,
            "trusted": bool(located["same_take"]) and status == "accepted",
            "tempo_bpm": round(
                60.0 / statistics.median(triples_script.beat_lengths(solo["grid"])), 1
            ),
            "inputs": {},
        }
        for key, notation in notations.items():
            if notation is None or not notation.bars:
                continue
            row["inputs"][key] = score_page(notation, crop, inventory)
        log(
            f"  {name:24} "
            + "  ".join(
                f"({k}) {row['inputs'][k]['local']['classes']['accuracy']:.3f}"
                for k in ("a", "b", "c", "f")
                if k in row["inputs"]
            )
        )
        out.append(row)
    return out


# ── summaries ───────────────────────────────────────────────────────────────


def pooled_interval(correct: list[int], beats: list[int], resamples: int = 10_000, seed: int = 0):
    """Pooled accuracy over pages, with a bootstrap interval that resamples
    PAGES (beats of one page are not independent draws)."""
    import numpy as np

    c, n = np.asarray(correct, dtype=float), np.asarray(beats, dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(c), size=(resamples, len(c)))
    pooled = c[draws].sum(axis=1) / n[draws].sum(axis=1)
    low, high = np.quantile(pooled, [0.025, 0.975])
    return float(c.sum() / n.sum()), float(low), float(high)


def mean_interval(values: list[float], labels: list[str]):
    """Mean over pages with `evaluation.paired_change`'s bootstrap (against
    zero, so its delta IS the mean), and how many pages sit above the paper's
    0.53 (its sign test against that constant)."""
    from swingscribe.evaluation import paired_change

    zero = paired_change([0.0] * len(values), values, labels)
    above = paired_change([PAPER_OMNIBOOK] * len(values), values, labels)
    return {
        "mean": zero.mean,
        "low": zero.low,
        "high": zero.high,
        "above": above.up,
        "below": above.down,
        "p_vs_paper": above.p,
    }


def summarize(rows: list[dict], pairing: str = "local") -> dict:
    """Per view: pooled accuracy with its interval and the per-page mean."""
    out = {"n": len(rows)}
    if not rows:
        return out
    labels = [r["name"] for r in rows]
    for view in VIEWS:
        cells = [r[pairing][view] for r in rows]
        pooled, low, high = pooled_interval(
            [c["correct"] for c in cells], [c["beats"] for c in cells]
        )
        out[view] = {
            "pooled": pooled,
            "pooled_low": low,
            "pooled_high": high,
            "beats": sum(c["beats"] for c in cells),
            **mean_interval([c["accuracy"] for c in cells], labels),
        }
    counts = [r[pairing]["onset_f1"] for r in rows]
    tp = sum(c["tp"] for c in counts)
    ours = sum(c["ours"] for c in counts)
    theirs = sum(c["theirs"] for c in counts)
    precision, recall = tp / ours if ours else 0.0, tp / theirs if theirs else 0.0
    out["onset_f1"] = {
        "pooled": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "precision": precision,
        "recall": recall,
        "mean": statistics.fmean(c["f1"] for c in counts),
    }
    return out


def confusion_tables(rows: list[dict], top: int = TOP) -> dict:
    """Pooled over pages: per reference signature, how often we wrote it and
    what instead; the commonest wrong pairs; and the share of wrong beats
    whose ONSETS were right (a length or a rest only)."""
    pooled: Counter = Counter()
    for r in rows:
        pooled.update(r["confusion"])
    by_theirs: dict[str, Counter] = {}
    for (theirs, ours), n in pooled.items():
        by_theirs.setdefault(theirs, Counter())[ours] += n
    total = sum(pooled.values()) or 1
    figures = []
    for theirs, row in sorted(by_theirs.items(), key=lambda item: -sum(item[1].values()))[:top]:
        n = sum(row.values())
        instead = [(o, bs.describe(o), c / n) for o, c in row.most_common() if o != theirs][:3]
        figures.append(
            {
                "signature": theirs,
                "figure": bs.describe(theirs),
                "share": n / total,
                "beats": n,
                "right": row[theirs] / n,
                "instead": instead,
            }
        )
    wrong = [(pair, n) for pair, n in pooled.items() if pair[0] != pair[1]]
    wrong_total = sum(n for _, n in wrong) or 1
    onsets_right = sum(
        n
        for (t, o), n in wrong
        if bs.UNSUPPORTED not in (t, o) and bs.onset_pattern(t) == bs.onset_pattern(o)
    )
    unsupported = sum(n for (t, o), n in wrong if bs.UNSUPPORTED in (t, o))
    pairs = [
        (t, bs.describe(t), o, bs.describe(o), n / wrong_total)
        for (t, o), n in sorted(wrong, key=lambda item: -item[1])[:top]
    ]
    return {
        "beats": total,
        "wrong": wrong_total,
        "wrong_onsets_right": onsets_right / wrong_total,
        "wrong_unsupported": unsupported / wrong_total,
        "figures": figures,
        "pairs": pairs,
    }


# ── printing ────────────────────────────────────────────────────────────────


def print_pages(rows: list[dict], title: str) -> None:
    print(f"\n== {title}: per page (local pairing; classes / exact / onsets; global classes) ==")
    print(
        f"  {'page':44} {'bpm':>5} {'beats':>5} {'class':>6} {'exact':>6} {'onset':>6} "
        f"{'global':>6} {'clock':>6} {'otb':>6} {'steps':>5} held"
    )
    for r in sorted(rows, key=lambda r: r["name"]):
        loc = r["local"]
        bpm = f"{r['bpm']:5.0f}" if r.get("bpm") else "    -"
        print(
            f"  {r['name'][:44]:44} {bpm} {loc['classes']['beats']:5d} "
            f"{loc['classes']['accuracy']:6.3f} {loc['exact']['accuracy']:6.3f} "
            f"{loc['onsets']['accuracy']:6.3f} {r['global']['classes']['accuracy']:6.3f} "
            f"{r['clock_share']:6.3f} {r['on_the_bar']:6.3f} {r['steps']:5d} "
            f"{'yes' if r['held'] else 'NO'}"
        )


def print_summary(label: str, s: dict) -> None:
    if s.get("n", 0) == 0:
        print(f"  {label:40} n=0")
        return
    for view in VIEWS:
        v = s[view]
        print(
            f"  {label:40} {view:8} pooled {v['pooled']:.3f} [{v['pooled_low']:.3f}, "
            f"{v['pooled_high']:.3f}]  page mean {v['mean']:.3f} [{v['low']:.3f}, {v['high']:.3f}]"
            f"  n={s['n']} pages, {v['beats']} beats; above 0.53: {v['above']}/{s['n']}"
        )
    o = s["onset_f1"]
    print(
        f"  {label:40} onset F1 (zero tolerance) pooled {o['pooled']:.3f} (P {o['precision']:.3f}"
        f" R {o['recall']:.3f}), page mean {o['mean']:.3f}"
    )


def unsupported_line(label: str, rows: list[dict]) -> dict:
    """How many beats each side wrote off the twelve bins, and how many of
    those have an ONSET off them (the rest end a note off them)."""
    beats = sum(r["local"]["exact"]["beats"] for r in rows) or 1
    out = {
        "beats": beats,
        **{
            k: sum(r[k] for r in rows)
            for k in (
                "unsupported_theirs",
                "unsupported_theirs_onsets",
                "unsupported_ours",
                "unsupported_ours_onsets",
                "rare_theirs",
            )
        },
    }
    print(
        f"  {label:28} unsupported beats: reference {out['unsupported_theirs'] / beats:.3f} "
        f"({out['unsupported_theirs_onsets'] / beats:.3f} with an onset off the bins), ours "
        f"{out['unsupported_ours'] / beats:.3f} ({out['unsupported_ours_onsets'] / beats:.3f}); "
        f"reference beats outside the 42 classes {out['rare_theirs'] / beats:.3f}"
    )
    return out


def print_confusion(title: str, table: dict) -> None:
    print(f"\n== {title}: what the reference wrote, and what we wrote instead (exact view) ==")
    print(
        f"  {table['beats']} beats, {table['wrong']} wrong; of the wrong, onsets right "
        f"(a length or rest only) {table['wrong_onsets_right']:.3f}, unsupported on either "
        f"side {table['wrong_unsupported']:.3f}"
    )
    for f in table["figures"]:
        instead = "; ".join(f"{d} {share:.2f}" for _s, d, share in f["instead"])
        print(
            f"  {f['signature']:12} {f['figure']:16} {f['share']:6.3f} of beats, "
            f"right {f['right']:.3f}; instead: {instead}"
        )
    print("  commonest wrong pairs (share of wrong beats):")
    for t, td, o, od, share in table["pairs"]:
        print(f"    {td:16} -> {od:16} {share:.3f}   ({t} -> {o})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--notes", type=Path, default=run_eval.notes_cache(0.2, 0.0))
    parser.add_argument("--grids", type=Path, default=run_eval.GRIDS_CACHE)
    parser.add_argument("--db", type=Path, default=None, help="WJazzD, for the triples")
    parser.add_argument(
        "--corpus", type=Path, default=run_eval.BENCH / "Transcriptions_Other" / "musicxml"
    )
    parser.add_argument("--split", type=Path, default=run_eval.SPLIT_FILE)
    parser.add_argument("--classes", type=int, default=bs.PAPER_CLASSES)
    parser.add_argument("--jobs", type=int, default=run_eval.default_jobs())
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    started = time.time()
    counts, corpus = corpus_counts(args.corpus, args.split)
    inventory = bs.build_inventory(counts, args.classes)
    inv = inventory_stats(counts, inventory)
    print(
        f"  inventory: the {inv['classes']} commonest signatures cover {inv['covered']:.3f} of "
        f"corpus beats; {inv['at_least_30']} reach {bs.RARE_BELOW} beats; unsupported "
        f"{inv['unsupported']:.3f}"
    )

    runs = json.loads(args.notes.read_text(encoding="utf-8"))
    grids = json.loads(args.grids.read_text(encoding="utf-8"))
    runs = run_eval.split_runs(runs, args.db, test=False)
    chosen = [p for p in select_pages(runs) if run_eval.track_of(p[1]) in grids]
    tasks = [
        (
            key,
            runs[key],
            grids[run_eval.track_of(key)],
            str(score),
            sorted(inventory),
            str(run_eval.CACHE_DIR),
        )
        for _set, key, score in chosen
    ]
    results = run_eval.parallel_map(_page_one, tasks, args.jobs)
    rows: dict[str, list[dict]] = {s: [] for s in SETS}
    for (which, key, _score), result in zip(chosen, results, strict=True):
        if result is None:
            print(f"  {key}: no page")
            continue
        result["name"] = Path(run_eval.track_of(key)).stem
        rows[which].append(result)

    report: dict = {"paper": PAPER, "corpus": corpus, "inventory": inv, "sets": {}}
    omnibook = rows["omnibook"]
    held = [r for r in omnibook if r["held"]]
    by_tempo = sorted((r for r in omnibook if r.get("bpm")), key=lambda r: r["bpm"])
    slow = by_tempo[: round(EASY_SHARE * len(by_tempo))]
    subsets = {
        "omnibook, all": omnibook,
        "omnibook, bar lines held": held,
        f"omnibook, slowest {EASY_SHARE:.0%}": slow,
        "hand scores": rows["hand"],
    }
    print_pages(omnibook, f"Omnibook, {len(omnibook)} sides")
    print_pages(rows["hand"], f"Hand scores, {len(rows['hand'])}")
    print("\n== Summary (paper: 0.53 on the Omnibook's easy 60%, 0.87 on Filosax) ==")
    for label, subset in subsets.items():
        for pairing in ("local", "global"):
            s = summarize(subset, pairing)
            report["sets"][f"{label} [{pairing}]"] = s
            print_summary(f"{label} [{pairing}]", s)
    if slow:
        print(f"  (slowest {EASY_SHARE:.0%}: {slow[0]['bpm']:.0f}-{slow[-1]['bpm']:.0f} bpm)")
    report["unsupported"] = {
        "omnibook": unsupported_line("omnibook", omnibook),
        "hand": unsupported_line("hand scores", rows["hand"]),
    }
    report["pages"] = {
        which: [{k: v for k, v in r.items() if k != "confusion"} for r in rows[which]]
        for which in SETS
    }
    report["confusion"] = {
        "omnibook": confusion_tables(omnibook),
        "hand": confusion_tables(rows["hand"]),
    }
    print_confusion("Omnibook", report["confusion"]["omnibook"])
    print_confusion("Hand scores", report["confusion"]["hand"])

    if args.db is not None:
        print(
            "\n== Triples: (a) WJazzD onsets on WJazzD beats, (b) on our beats, (c) ours, "
            "(f) Flex-Q =="
        )
        db = sqlite3.connect(args.db)
        triples = triple_rows(db, runs, grids, inventory)
        trusted = [t for t in triples if t["trusted"]]
        report["triples"] = []
        for t in triples:
            report["triples"].append(
                {
                    "name": t["name"],
                    "kind": t["kind"],
                    "trusted": t["trusted"],
                    "tempo_bpm": t["tempo_bpm"],
                    "inputs": {
                        k: {kk: vv for kk, vv in v.items() if kk != "confusion"}
                        for k, v in t["inputs"].items()
                    },
                }
            )
        print(f"  trusted: {len(trusted)} of {len(triples)}")
        for key in ("a", "b", "c", "f"):
            have = [{**t["inputs"][key], "name": t["name"]} for t in trusted if key in t["inputs"]]
            s = summarize(have)
            report["sets"][f"triples ({key}) [local]"] = s
            print_summary(f"triples ({key}) [local]", s)
        from swingscribe.evaluation import paired_change

        # (b) - (a) is the grid's share, (c) - (b) hearing's, (c) - (a) both,
        # and (a) - (f) our quantizer against Flex-Q on the same onsets.
        for after, before in (("b", "a"), ("c", "b"), ("c", "a"), ("a", "f")):
            both = [t for t in trusted if before in t["inputs"] and after in t["inputs"]]
            if not both:
                continue
            for view in VIEWS:
                change = paired_change(
                    [t["inputs"][before]["local"][view]["accuracy"] for t in both],
                    [t["inputs"][after]["local"][view]["accuracy"] for t in both],
                )
                report["sets"][f"triples ({after}) - ({before}) {view}"] = change.__dict__
                print(
                    f"  ({after}) - ({before}) {view:8} {change.mean:+.3f} [{change.low:+.3f}, "
                    f"{change.high:+.3f}]  {change.up} up / {change.down} down, "
                    f"p = {change.p:.3f}, n = {change.n}"
                )
        a_rows = [{**t["inputs"]["a"], "name": t["name"]} for t in trusted if "a" in t["inputs"]]
        c_rows = [{**t["inputs"]["c"], "name": t["name"]} for t in trusted if "c" in t["inputs"]]
        report["unsupported"]["triples_a"] = unsupported_line("triples (a)", a_rows)
        report["unsupported"]["triples_c"] = unsupported_line("triples (c)", c_rows)
        report["confusion"]["triples_a"] = confusion_tables(a_rows)
        print_confusion("Triples (a), the quantizer alone", report["confusion"]["triples_a"])

    print(f"\n  {time.time() - started:.0f} s")
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=1, default=list), encoding="utf-8")
        print(f"  wrote {args.json}")


if __name__ == "__main__":
    main()
