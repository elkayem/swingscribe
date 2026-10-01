"""Judge A6's re-ranker on human data only, paired against the shipped rule.

    python scripts/reranker_eval.py --db wjazz/wjazzd.db --model open=<weights.json> \
        --notes <snapshot of the notes cache> --grids <snapshot of the grids cache> \
        --json out.json

docs/reranker.md. Each `--model label=path` is switched on by environment
override (QuantizeConfig.reranker; every Config the stages build reads it,
every worker is handed it) against the shipped defaults in the same run, on
exactly the instruments docs/writing-round2.md used for the hand rules,
through their own code (scripts/writing_ab.py, scripts/beat_signature.py):

1. the triples (scripts/triples.py builders): (a) WJazzD's human onsets on
   WJazzD's human beats -- the quantizer alone -- and (c) our notes on our
   grid, paired over the trusted triples: rhythm, value, coverage, on the
   bar, and the notes written;
2. the listener's twelve hand scores (paired by recording) and the located
   Omnibook sides, through run_eval's own notation path;
3. the Rhythm Perceiver's beat-signature accuracy (scripts/beat_signature.py)
   on the triples' (a) and (c) rows, the hand scores and the Omnibook, per
   page and pooled;
4. collateral: the WJazzD quantizer instrument's dropped notes
   (scripts/wjazz_quantize.py; D36: it judges nothing else).

Plus three views of (a) no page score has, each by `--sets`:

- `beats`: every beat where the quantizer had a choice, matched note by note
  to the page through the triples' alignment, scored as the training data is
  scored -- does the chosen reading write every note where the page does --
  for the rule, the model and the best candidate offered (the oracle);
- `oracle`: the page-level ceiling of ANY per-beat re-ranker over the gated
  and the open readings -- an oracle that picks the reading writing the page
  wherever one is offered, scored as (a) is scored;
- `split`: where a model's page-level change comes from -- its picks kept
  only on labelled beats, only on the rest, only where they write the page,
  or everywhere but where it trades one wrong reading for another.

No audio is read and nothing is written to the harness caches; only
aggregates leave the script.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import run_eval  # noqa: E402
import writing_ab  # noqa: E402

KEY = "SWINGSCRIBE_QUANTIZE__RERANKER"


def env_for(path: str | None) -> dict:
    return {KEY: path} if path else {}


@contextlib.contextmanager
def switched(path: str | None):
    saved = os.environ.get(KEY)
    if path:
        os.environ[KEY] = path
    else:
        os.environ.pop(KEY, None)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = saved


def quietly(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# ── workers (spawned: the env travels in the task) ──────────────────────────


def _set_env(path: str | None) -> None:
    if path:
        os.environ[KEY] = path
    else:
        os.environ.pop(KEY, None)


def _page_worker(task: tuple) -> dict | None:
    *inner, path = task
    _set_env(path)
    return writing_ab._page_one((*inner, {}))


def _beatsig_worker(task: tuple) -> dict | None:
    *inner, path = task
    _set_env(path)
    import beat_signature

    return beat_signature._page_one(tuple(inner))


# ── the sets ────────────────────────────────────────────────────────────────


def pages(tasks, path: str | None, jobs: int) -> dict:
    results = run_eval.parallel_map(_page_worker, [(*t, path) for _s, _k, t in tasks], jobs)
    return {
        key: {**entry, "set": which}
        for (which, key, _t), entry in zip(tasks, results, strict=True)
        if entry
    }


def beatsig_pages(runs, grids, inventory, path: str | None, jobs: int, db_path) -> dict:
    import beat_signature

    chosen = [
        p
        for p in beat_signature.select_pages(
            quietly(run_eval.split_runs, runs, db_path, test=False)
        )
        if run_eval.track_of(p[1]) in grids
    ]
    tasks = [
        (
            key,
            runs[key],
            grids[run_eval.track_of(key)],
            str(score),
            sorted(inventory),
            str(run_eval.CACHE_DIR),
            path,
        )
        for _set, key, score in chosen
    ]
    results = run_eval.parallel_map(_beatsig_worker, tasks, jobs)
    return {
        key: {**r, "set": which}
        for (which, key, _score), r in zip(chosen, results, strict=True)
        if r is not None
    }


def beatsig_change(before: dict, after: dict) -> dict:
    from swingscribe.evaluation import paired_change

    out = {}
    for which in ("omnibook", "hand"):
        keys = sorted(k for k in before if before[k]["set"] == which and k in after)
        for view in ("classes", "onsets"):
            b = [before[k]["local"][view]["accuracy"] for k in keys]
            a = [after[k]["local"][view]["accuracy"] for k in keys]
            c = paired_change(
                b, a, [run_eval.recording_of(run_eval.pin_name(k)) for k in keys], tolerance=0.002
            )
            pooled_b = sum(before[k]["local"][view]["correct"] for k in keys) / max(
                1, sum(before[k]["local"][view]["beats"] for k in keys)
            )
            pooled_a = sum(after[k]["local"][view]["correct"] for k in keys) / max(
                1, sum(after[k]["local"][view]["beats"] for k in keys)
            )
            out[f"{which} {view}"] = {
                **_cell(c),
                "pooled_before": round(pooled_b, 4),
                "pooled_after": round(pooled_a, 4),
            }
    return out


def _cell(c) -> dict:
    return {
        "n": c.n,
        "mean": round(c.mean, 4),
        "low": round(c.low, 4),
        "high": round(c.high, 4),
        "up": c.up,
        "down": c.down,
        "p": round(c.p, 3),
        "decided": c.decided,
    }


def beatsig_triples(db, runs, grids, inventory) -> dict:
    import beat_signature

    rows = quietly(beat_signature.triple_rows, db, runs, grids, inventory, log=lambda *_: None)
    return {r["name"]: r for r in rows if r["trusted"]}


def beatsig_triples_change(before: dict, after: dict) -> dict:
    from swingscribe.evaluation import paired_change

    out = {}
    names = sorted(set(before) & set(after))
    for key in ("a", "c"):
        have = [n for n in names if key in before[n]["inputs"] and key in after[n]["inputs"]]
        for view in ("classes", "onsets"):
            c = paired_change(
                [before[n]["inputs"][key]["local"][view]["accuracy"] for n in have],
                [after[n]["inputs"][key]["local"][view]["accuracy"] for n in have],
                tolerance=0.002,
            )
            out[f"({key}) {view}"] = {
                **_cell(c),
                "pooled_before": round(
                    sum(before[n]["inputs"][key]["local"][view]["correct"] for n in have)
                    / max(1, sum(before[n]["inputs"][key]["local"][view]["beats"] for n in have)),
                    4,
                ),
                "pooled_after": round(
                    sum(after[n]["inputs"][key]["local"][view]["correct"] for n in have)
                    / max(1, sum(after[n]["inputs"][key]["local"][view]["beats"] for n in have)),
                    4,
                ),
            }
    return out


# ── the per-beat view on (a) ────────────────────────────────────────────────


class BeatProbe:
    """Records every beat the hook is asked about and, when a model is given,
    answers as the model would. The beat's notes are found by time."""

    def __init__(self, model=None, open_: bool = True):
        self.model = model
        self.open = model.open if model is not None else open_
        self.beats: list[tuple[dict, list[dict], int | None]] = []

    def choose(self, context, candidates):
        pick = self.model.choose(context, candidates) if self.model is not None else None
        self.beats.append((dict(context), [dict(c) for c in candidates], pick))
        return pick


class Filtered:
    """A model whose picks are kept only where `keep(time, candidates, pick)`
    says so (the rule's reading elsewhere): the split diagnostic."""

    def __init__(self, model, keep):
        self.model = model
        self.keep = keep
        self.open = model.open

    def choose(self, context, candidates):
        pick = self.model.choose(context, candidates)
        if pick is None or not self.keep(round(context["time"], 6), candidates, pick):
            return None
        return pick


class OracleChooser:
    """Picks, at each beat it has a label for, the offered reading that
    writes every note where the page does (the rule's pick when none does).
    Labels are page positions relative to the beat line, keyed by its time."""

    def __init__(self, labels: dict, open_: bool):
        self.labels = labels
        self.open = open_

    def choose(self, context, candidates):
        rel = self.labels.get(round(context["time"], 6))
        if rel is None:
            return None
        for i, c in enumerate(candidates):
            if _writes(c, rel):
                return None if c["baseline"] else i
        return None


def _writes(candidate: dict, rel: list[float]) -> bool:
    """Does this reading write every note of the beat where the page does?"""
    return len(candidate["snapped"]) == len(rel) and all(
        abs(s - r) < 1e-6 for s, r in zip(candidate["snapped"], rel, strict=True)
    )


def _base(candidates: list[dict]) -> int | None:
    return next((i for i, c in enumerate(candidates) if c["baseline"]), None)


def trusted_triples(db):
    """(name, solo, crop) for every triple whose page holds this take."""
    import triples as triples_script
    import wjazz_quantize

    from swingscribe import mscz
    from swingscribe import triples as tri

    for name, melid, _track, page_rel, _kind in triples_script.TRIPLES:
        solo = wjazz_quantize.load_solo(db, melid)
        page = mscz.parse_any(run_eval.BENCH / page_rel)
        located = tri.locate_solo(page, [(n["position"], n["pitch"]) for n in solo["notes"]])
        if located["same_take"]:
            yield name, solo, tri.crop(page, located["lo"], located["hi"])


def notate_with(solo: dict, chooser):
    """(a)'s notation -- the annotator's onsets on the annotator's beats,
    scripts/triples.py's builder -- with `chooser` in the reranker hook."""
    import triples as triples_script

    from swingscribe import reranker

    original = reranker.load_model
    reranker.load_model = lambda _spec: chooser
    try:
        with switched("probe"):
            return triples_script.notate_annotation(solo)
    finally:
        reranker.load_model = original


def page_positions(solo: dict, crop, notation, beats: list, written_by) -> list:
    """Per beat the hook was asked about, (category, rel): `rel` is the
    page's position of each of the beat's notes relative to the beat line,
    from the triples' note pairing (`tri.disagreements`) and our written
    position less the written offset of the reading `written_by(candidates,
    pick)` names. A beat is "labelled" when every one of its notes is paired
    and the page writes all of them in the beat or on the next line."""
    import bisect

    import wjazz_quantize

    from swingscribe import triples as tri
    from swingscribe.benchmark import notation_notes

    ours = notation_notes(notation)
    theirs = [(n.position, n.duration, n.pitch) for n in crop.melody]
    page_of = {e: (p, o) for _r, e, _c, p, o in tri.disagreements(ours, theirs)["per_note"]}
    ours_of = dict(wjazz_quantize.align(solo["notes"], ours)[0])
    onsets = [n["onset"] for n in solo["notes"]]
    out = []
    for context, candidates, pick in beats:
        written = written_by(candidates, pick)
        if written is None:
            out.append(("the rule merges", None))
            continue
        first = bisect.bisect_left(onsets, context["time"] - 1e-9)
        rel: list[float] | None = []
        for j, k in enumerate(range(first, first + len(context["raw"]))):
            e = ours_of.get(k)
            if e is None or e not in page_of:
                rel = None
                break
            ppos, opos = page_of[e]
            rel.append(ppos - (opos - candidates[written]["snapped"][j]))
        if rel is None:
            out.append(("a note only one side has", None))
        elif not all(-1e-6 <= r <= 1 + 1e-6 for r in rel):
            out.append(("written in another beat", None))
        else:
            out.append(("labelled", rel))
    return out


def _rule_written(candidates, _pick):
    return _base(candidates)


def _chosen_written(candidates, pick):
    base = _base(candidates)
    return None if base is None else (pick if pick is not None else base)


def per_beat_a(db, model_path: str | None, open_: bool) -> dict:
    """(a)'s beats with a choice, scored note by note against the page."""
    from swingscribe import reranker

    model = reranker.load_model(model_path) if model_path else None
    totals = Counter()
    confusions = Counter()
    for _name, solo, crop in trusted_triples(db):
        probe = BeatProbe(model, open_)
        notation = notate_with(solo, probe)
        positions = page_positions(solo, crop, notation, probe.beats, _chosen_written)
        for (_context, candidates, pick), (category, rel) in zip(
            probe.beats, positions, strict=True
        ):
            if category == "the rule merges":
                continue
            base = _base(candidates)
            chosen = pick if pick is not None else base
            totals["beats"] += 1
            if rel is None:
                totals["unmatched"] += 1
                continue
            right = [_writes(c, rel) for c in candidates]
            gated = [i for i, c in enumerate(candidates) if c.get("gated", True)]
            totals["labelled"] += 1
            totals["baseline"] += right[base]
            totals["model"] += right[chosen]
            totals["oracle_open"] += any(right)
            totals["oracle_gated"] += any(right[i] for i in gated)
            moved = candidates[chosen]["snapped"] != candidates[base]["snapped"]
            totals["changed"] += moved
            if moved:
                verdict = (
                    "fixed"
                    if right[chosen] and not right[base]
                    else "broke"
                    if right[base] and not right[chosen]
                    else "both wrong"
                )
                totals[f"changed_{verdict}"] += 1
                key = (
                    " ".join(_frac(r) for r in rel),
                    " ".join(_frac(s) for s in candidates[base]["snapped"]),
                    " ".join(_frac(s) for s in candidates[chosen]["snapped"]),
                    verdict,
                )
                confusions[key] += 1
    n = max(1, totals["labelled"])
    out = {k: totals[k] for k in totals}
    for k in ("baseline", "model", "oracle_open", "oracle_gated"):
        out[f"{k}_rate"] = round(totals[k] / n, 4)
    out["changes"] = [[*k, v] for k, v in confusions.most_common(25)]
    return out


def _rule_labels(db, open_: bool):
    """Pass 1 for the oracle and the split: each trusted triple notated by
    the rule, with every consulted beat's category and page positions.

    The hook is in place and defers, so this is the rule's page only for a
    gated chooser. An OPEN one is also offered readings the gates refuse,
    and where the rule's own reading merges two notes it writes the
    admitted reading of least snap error -- the notes kept, as the
    always-deferring open model keeps them -- so an open oracle or split is
    measured against that page, not the shipped one (docs/reranker.md has
    both)."""
    for name, solo, crop in trusted_triples(db):
        probe = BeatProbe(None, open_)
        notation = notate_with(solo, probe)
        positions = page_positions(solo, crop, notation, probe.beats, _rule_written)
        yield name, solo, crop, notation, probe.beats, positions


def _paired_cells(before: dict, after: dict, fields) -> dict:
    from swingscribe.evaluation import paired_change

    names = sorted(before)
    out = {}
    for field in fields:
        c = paired_change(
            [before[n][field] for n in names], [after[n][field] for n in names], tolerance=0.002
        )
        out[field] = {
            **_cell(c),
            "before": round(sum(before[n][field] for n in names) / len(names), 4),
        }
    return out


def oracle_a(db, open_: bool, inventory=None) -> dict:
    """The (a) row's ceiling for ANY per-beat re-ranker over these readings:
    a first pass notates with the rule and labels each beat with the page's
    positions (as `per_beat_a` does); a second lets an oracle pick the
    right reading wherever one is offered. Scored as scripts/triples.py
    scores (a), paired over the trusted triples."""
    import triples as triples_script

    before, after = {}, {}
    for name, solo, crop, notation, beats, positions in _rule_labels(db, open_):
        labels = {
            round(context["time"], 6): rel
            for (context, _c, _p), (category, rel) in zip(beats, positions, strict=True)
            if category == "labelled"
        }
        best = notate_with(solo, OracleChooser(labels, open_))
        before[name] = triples_script.score(notation, crop)
        after[name] = triples_script.score(best, crop)
        if inventory is not None:
            import beat_signature

            for row, n in ((before[name], notation), (after[name], best)):
                row["beatsig"] = beat_signature.score_page(n, crop, inventory)["local"]
    out = {"n": len(before)}
    out.update(
        _paired_cells(before, after, ("rhythm", "value", "coverage", "on_the_bar", "written"))
    )
    if inventory is not None:
        from swingscribe.evaluation import paired_change

        names = sorted(before)
        for view in ("classes", "onsets"):
            c = paired_change(
                [before[n]["beatsig"][view]["accuracy"] for n in names],
                [after[n]["beatsig"][view]["accuracy"] for n in names],
                tolerance=0.002,
            )
            out[f"beatsig {view}"] = _cell(c)
    return out


SPLITS = ("all", "labelled", "unlabelled", "fixes", "no both-wrong")


def split_a(db, model_path: str) -> dict:
    """Where a model's page-level change on (a) comes from: its picks kept
    everywhere, only on labelled beats, only on the rest, only where it
    writes the page (`fixes`), and everywhere but the labelled beats where
    it trades one wrong reading for another (`no both-wrong`); with the
    consulted beats' categories and the model's moves among them."""
    import triples as triples_script

    from swingscribe import reranker

    model = reranker.load_model(model_path)
    categories, moves = Counter(), Counter()
    scores: dict[str, dict] = {key: {} for key in ("rule", *SPLITS)}
    for name, solo, crop, notation, beats, positions in _rule_labels(db, model.open):
        labels = {}
        for (context, candidates, _p), (category, rel) in zip(beats, positions, strict=True):
            categories[category] += 1
            if category == "labelled":
                labels[round(context["time"], 6)] = rel
            base = _base(candidates)
            pick = model.choose(context, candidates)
            if base is None or pick is None:
                continue
            if candidates[pick]["snapped"] == candidates[base]["snapped"]:
                continue
            if category != "labelled":
                moves[category] += 1
                continue
            mine, rule = _writes(candidates[pick], rel), _writes(candidates[base], rel)
            moves[
                "labelled, fixed"
                if mine and not rule
                else "labelled, broke"
                if rule and not mine
                else "labelled, both wrong"
            ] += 1

        def writes_page(t, candidates, pick, labels=labels):
            return t in labels and _writes(candidates[pick], labels[t])

        keeps = {
            "all": lambda t, c, p: True,
            "labelled": lambda t, c, p, labels=labels: t in labels,
            "unlabelled": lambda t, c, p, labels=labels: t not in labels,
            "fixes": writes_page,
            "no both-wrong": lambda t, c, p, labels=labels: (
                t not in labels or writes_page(t, c, p) or _writes(c[_base(c)], labels[t])
            ),
        }
        scores["rule"][name] = triples_script.score(notation, crop)
        for key, keep in keeps.items():
            scores[key][name] = triples_script.score(notate_with(solo, Filtered(model, keep)), crop)
    out = {"categories": dict(categories), "moves": dict(moves), "n": len(scores["rule"])}
    for key in SPLITS:
        out[key] = _paired_cells(scores["rule"], scores[key], ("rhythm", "value", "on_the_bar"))
    return out


def _frac(x: float) -> str:
    from fractions import Fraction

    return str(Fraction(x).limit_denominator(48))


# ── the run ─────────────────────────────────────────────────────────────────


def report_cells(title: str, cells: dict) -> None:
    print(f"  {title}")
    for key, c in cells.items():
        mark = "*" if c.get("decided") else " "
        extra = ""
        if "pooled_before" in c:
            extra = f"  pooled {c['pooled_before']:.4f} -> {c['pooled_after']:.4f}"
        interval = f"[{c['low']:+.4f}, {c['high']:+.4f}]{mark}"
        print(
            f"    {key:20} n={c['n']:2d} {c['mean']:+.4f} {interval} "
            f"{c['up']}/{c['down']} p={c['p']:.2f}{extra}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    parser.add_argument("--notes", type=Path, default=run_eval.notes_cache(0.2, 0.0))
    parser.add_argument("--grids", type=Path, default=run_eval.GRIDS_CACHE)
    parser.add_argument("--model", action="append", default=[], help="label=weights.json")
    parser.add_argument("--sets", default="beats,triples,pages,beatsig,flexq")
    parser.add_argument("--jobs", type=int, default=run_eval.default_jobs())
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    os.environ.pop(KEY, None)

    models = dict(m.split("=", 1) for m in args.model)
    sets = set(args.sets.split(","))
    db = sqlite3.connect(args.db)
    runs = json.loads(args.notes.read_text(encoding="utf-8"))
    grids = json.loads(args.grids.read_text(encoding="utf-8"))
    card: dict = {"models": models, "baseline": {}, "changes": {}}
    started = time.time()

    if "oracle" in sets:
        import beat_signature

        from swingscribe import beat_signature as bs

        counts, _corpus = quietly(
            beat_signature.corpus_counts,
            run_eval.BENCH / "Transcriptions_Other" / "musicxml",
            run_eval.SPLIT_FILE,
        )
        oracle_inventory = bs.build_inventory(counts, bs.PAPER_CLASSES)
        print("== the ceiling: an oracle re-ranker on (a) ==")
        for label, open_ in (("gated", False), ("open", True)):
            card.setdefault("oracle", {})[label] = oracle_a(db, open_, oracle_inventory)
            print(f"  oracle over the {label} readings:")
            report_cells("", {k: v for k, v in card["oracle"][label].items() if k != "n"})
        sys.stdout.flush()

    if "split" in sets:
        print("== where each model's change on (a) comes from ==")
        for label, path in models.items():
            card.setdefault("split", {})[label] = split = split_a(db, path)
            print(f"  {label}: beats {split['categories']}; moves {split['moves']}")
            for key in SPLITS:
                report_cells(f"picks kept on: {key}", split[key])
        sys.stdout.flush()

    if "beats" in sets:
        print("== per-beat view on (a) ==")
        for label, path in {"baseline": None, **models}.items():
            from swingscribe import reranker

            open_ = reranker.load_model(path).open if path else True
            card.setdefault("beats", {})[label] = per_beat_a(db, path, open_)
            b = card["beats"][label]
            print(
                f"  {label}: {b['labelled']} labelled beats of {b['beats']}; rule "
                f"{b['baseline_rate']:.4f} model {b['model_rate']:.4f} oracle gated "
                f"{b['oracle_gated_rate']:.4f} open {b['oracle_open_rate']:.4f}; changed "
                f"{b.get('changed', 0)} (fixed {b.get('changed_fixed', 0)}, broke "
                f"{b.get('changed_broke', 0)})"
            )
            for row in b["changes"][:12]:
                print(f"      {row}")
        sys.stdout.flush()

    base_triples = base_pages = base_flexq = base_bs_pages = base_bs_triples = None
    inventory = None
    if "triples" in sets:
        located: dict = {}
        with switched(None):
            base_triples = writing_ab.triple_rows(db, runs, grids, located)
    tasks = writing_ab.page_tasks(runs, grids, args.db) if "pages" in sets else []
    if tasks:
        base_pages = pages(tasks, None, args.jobs)
        card["baseline"]["pages_n"] = Counter(e["set"] for e in base_pages.values())
    if "beatsig" in sets:
        import beat_signature

        from swingscribe import beat_signature as bs

        counts, _corpus = quietly(
            beat_signature.corpus_counts,
            run_eval.BENCH / "Transcriptions_Other" / "musicxml",
            run_eval.SPLIT_FILE,
        )
        inventory = bs.build_inventory(counts, bs.PAPER_CLASSES)
        base_bs_pages = beatsig_pages(runs, grids, inventory, None, args.jobs, args.db)
        with switched(None):
            base_bs_triples = beatsig_triples(db, runs, grids, inventory)
    if "flexq" in sets:
        with switched(None):
            base_flexq = writing_ab.flexq(db)
        card["baseline"]["flexq"] = base_flexq
    print(f"baselines built ({time.time() - started:.0f} s): {card['baseline']}")

    for label, path in models.items():
        block: dict = {}
        print(f"\n== {label} ({path}) ==")
        if base_triples is not None:
            with switched(path):
                after = writing_ab.triple_rows(db, runs, grids, located)
            block["triples"] = writing_ab.triples_change(base_triples, after)
        if base_pages is not None:
            block["pages"] = writing_ab.pages_change(base_pages, pages(tasks, path, args.jobs))
        if base_bs_pages is not None:
            block["beatsig_pages"] = beatsig_change(
                base_bs_pages, beatsig_pages(runs, grids, inventory, path, args.jobs, args.db)
            )
            with switched(path):
                after_bs = beatsig_triples(db, runs, grids, inventory)
            block["beatsig_triples"] = beatsig_triples_change(base_bs_triples, after_bs)
        if base_flexq is not None:
            with switched(path):
                now = writing_ab.flexq(db)
            block["flexq"] = {
                "dropped": now["dropped"] - base_flexq["dropped"],
                "page_hit_all": round(now["page_hit_all"] - base_flexq["page_hit_all"], 4),
            }
        card["changes"][label] = block
        writing_ab.report(label, {"env": env_for(path), **block})
        if "beatsig_pages" in block:
            report_cells("beat signature, pages", block["beatsig_pages"])
            report_cells("beat signature, triples", block["beatsig_triples"])
        if args.json:
            args.json.write_text(json.dumps(card, indent=1, default=str), encoding="utf-8")
        sys.stdout.flush()
    print(f"\n{time.time() - started:.0f} s")
    if args.json:
        args.json.write_text(json.dumps(card, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
