"""Would the routing suggestion have got the benchmark's sidecars right?

Every `*.swingscribe.json` under `benchmark/` carries a listener's (or the
batch's) `ensemble` and `stem` for a span. This reads the stems ALREADY ON
DISK for that span -- through `pipeline.cached_document` (which never runs
ingest) and `library.available_stems`, the resolver the GUI uses -- measures
them with `routing.window_power` / `routing.summarize` and asks
`routing.suggest`, then tabulates:

- the confusion table, truth (horn-led / trio) against the suggestion;
- the separating margin: the worst horn span and the worst trio span on each
  of the two piano tests, and where the thresholds sit between them;
- a leave-one-out check of a threshold DERIVED from the data (the midpoint
  of the gap without the held-out span), because the shipped thresholds were
  chosen after looking at these same eleven trio spans;
- sub-windows inside every labelled span at 1 s steps (a listener's
  selection is rarely the sidecar's exact span), with "no suggestion" split
  into too short and judged-but-unsure;
- the floor sweep that places `MIN_ACTIVE_S`: every window of 10-40, 45, 50
  and 60 s at 1 s steps, judged under several floors, reporting the worst
  horn window on EACH piano test alone and jointly;
- probes that CONTAIN a horn and must never be called trio: the whole file of
  every horn track with a whole-file stem set, and, where one file holds both
  a horn solo and a piano solo (Dolores, Orbits, Gingerbread Boy), the span
  from the horn solo through the piano solo;
- edge probes: the piano solo with 0-30 s of the neighbouring horn solo
  taken in at its edge, which is what a slightly wide selection looks like;
- the lead-stem agreement, sidecar stem against suggested stem.

`ensemble: null` is scored as horn-led: it behaves like it (CLAUDE.md), and
all five such sidecars are horn solos with `stem: other`.

Usage:
    uv run python scripts/routing_survey.py [--model htdemucs_6s] [--json out.json]

Reads wavs only: no separation, no CREPE, no ingest (a sidecar whose ingest
or stems are not cached is reported and skipped). 152 s over the 111
sidecars on the Roformer, 180 s with --model htdemucs_6s (2026-09-30). Only
levels and counts leave this script.

`routing.suggest` refuses every separator but bsroformer_sw, but it computes
its evidence first, so a run with --model still reports how close that
separator's horns came to a piano call -- which is how it is judged for
`routing.SUGGEST_MODELS`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

from swingscribe import pipeline, routing
from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.stages import ingest

BENCH = Path("benchmark")
CACHES = (BENCH / ".swingscribe-cache", Path(".swingscribe-cache"))
WINDOW_LENGTHS_S = (10, 12, 15, 20, 30, 60)
WINDOW_STEP_S = 1
# The floor sweep: every window length here, at 1 s steps, judged under each
# floor. 40 s and past, the worst horn window only falls (0.73 at 30 s).
SWEEP_LENGTHS_S = (*range(10, 41), 45, 50, 60)
SWEEP_FLOORS_S = (10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 18.0, 20.0)
# Seconds of the neighbouring horn solo taken in at the piano solo's edge.
EDGE_S = (0, 2, 5, 8, 10, 12, 15, 20, 30)
PIANO = ("trio", "solo-piano")


def truth_of(ensemble: str | None) -> str:
    """The class a sidecar is scored as: piano-led or not."""
    return "trio" if ensemble in PIANO else "horn-led"


def called(suggestion: routing.Suggestion) -> str:
    """The suggestion as a table column: a piano call, horn-led, or none."""
    if suggestion.ensemble in PIANO:
        return "trio"
    return suggestion.ensemble or "none"


def judged(suggestion: routing.Suggestion) -> bool:
    """Whether the rule got as far as the piano tests (a whole stem set and
    enough melody); a "none" that was not judged is a refusal, not doubt."""
    return "piano_share" in suggestion.evidence


@contextmanager
def floor_of(seconds: float):
    """`routing.MIN_ACTIVE_S` set to `seconds` for the sweep, restored after."""
    saved = routing.MIN_ACTIVE_S
    routing.MIN_ACTIVE_S = seconds
    try:
        yield
    finally:
        routing.MIN_ACTIVE_S = saved


def resolve(audio: Path, model: str, region):
    """(stems, cache) for this sidecar's span, or None. Read-only."""
    for cache in CACHES:
        base = Config(cache_dir=cache)
        config = base.model_copy(
            update={"separate": base.separate.model_copy(update={"model": model})}
        )
        document = pipeline.cached_document(audio, config, [("ingest", ingest.run)])
        if document is None or document.audio is None:
            continue
        if not Path(document.audio.path).is_file():
            continue
        span = None if region is None else tuple(region)
        stems = library.available_stems(document, config, model, span=span)
        # A summed stem (library.COMBINED_STEMS) is not a source; routing
        # would drop it anyway, but it need not be read.
        stems = {name: path for name, path in stems.items() if name in routing.SEPARATED_STEMS}
        if stems:
            return stems, cache
    return None


def slice_levels(power, start, stop):
    return routing.summarize({s: v[start:stop] for s, v in power.items()})


def gap_midpoint_rule(rows, held_out):
    """Thresholds re-derived from every span but `held_out`: the midpoint of
    the gap between the worst horn and the worst trio on each piano test."""
    horn = [r for r in rows if r is not held_out and r["truth"] == "horn-led"]
    trio = [r for r in rows if r is not held_out and r["truth"] == "trio"]
    share = (max(r["piano_share"] for r in horn) + min(r["piano_share"] for r in trio)) / 2
    margin = (max(r["margin"] for r in horn) + min(r["margin"] for r in trio)) / 2
    return share, margin


class FloorStats:
    """What one floor does to every window: the worst horn on each piano test
    alone and jointly, and how many trio windows it still calls."""

    def __init__(self):
        self.counts = Counter()
        self.horn_share = None  # (share, margin, name, start, length)
        self.horn_margin = None
        self.horn_joint = None  # the loudest horn window that passes the SHARE test
        self.horn_pass_share = 0
        self.horn_pass_margin = 0
        self.trio_min_share = None
        self.trio_min_margin = None
        self.trio_max_under = None

    def add(self, truth, suggestion, name, start, length):
        call = called(suggestion)
        verdict = call if call != "none" else ("none" if judged(suggestion) else "short")
        self.counts[(truth, verdict)] += 1
        if not judged(suggestion):
            return
        share = suggestion.evidence["piano_share"]
        margin = suggestion.evidence["piano_margin_db"]
        where = (share, margin, name, start, length)
        if truth == "horn-led":
            if self.horn_share is None or (share, margin) > self.horn_share[:2]:
                self.horn_share = where
            if self.horn_margin is None or margin > self.horn_margin[1]:
                self.horn_margin = where
            if share >= routing.PIANO_SHARE_MIN:
                self.horn_pass_share += 1
                if self.horn_joint is None or margin > self.horn_joint[1]:
                    self.horn_joint = where
            self.horn_pass_margin += margin >= routing.PIANO_MARGIN_DB
        else:
            if self.trio_min_share is None or share < self.trio_min_share:
                self.trio_min_share = share
            if self.trio_min_margin is None or margin < self.trio_min_margin:
                self.trio_min_margin = margin
            under = suggestion.evidence["piano_under_loudest_db"]
            if self.trio_max_under is None or under > self.trio_max_under:
                self.trio_max_under = under

    def as_dict(self):
        return {
            "counts": {f"{t} -> {c}": k for (t, c), k in sorted(self.counts.items())},
            "horn_max_share": self.horn_share,
            "horn_max_margin": self.horn_margin,
            "horn_passing_share": self.horn_pass_share,
            "horn_passing_margin": self.horn_pass_margin,
            "horn_joint_worst": self.horn_joint,
            "trio_min_share": self.trio_min_share,
            "trio_min_margin_db": self.trio_min_margin,
            "trio_max_under_loudest_db": self.trio_max_under,
        }


def edge_probe(pair_power, lo, piano, horn_first, model):
    """The piano solo with k seconds of the neighbouring horn solo at its edge."""
    start, end = piano["region"]
    n = min(len(v) for v in pair_power.values())
    out = []
    for k in EDGE_S:
        a, b = (start - k, end) if horn_first else (start, end + k)
        i0, i1 = max(0, round(a - lo)), min(n, round(b - lo))
        s = routing.suggest(slice_levels(pair_power, i0, i1), model)
        out.append(
            {
                "horn_s": k,
                "called": called(s),
                "piano_share": s.evidence.get("piano_share"),
                "margin": s.evidence.get("piano_margin_db"),
                "confidence": s.confidence,
            }
        )
    return out


def survey(model_override: str | None) -> dict:
    rows = []
    skipped = []
    powers = {}
    by_dir = defaultdict(list)
    for side in sorted(BENCH.rglob("*.swingscribe.json")):
        sidecar = json.loads(side.read_text(encoding="utf-8"))
        audio = side.with_name(side.name[: -len(".swingscribe.json")])
        name = audio.relative_to(BENCH).as_posix()
        model = model_override or sidecar.get("model") or "bsroformer_sw"
        region = sidecar.get("region")
        found = resolve(audio, model, region) if region else None
        if found is None:
            skipped.append(name)
            continue
        stems, _ = found
        power = routing.window_power(stems, tuple(region))
        levels = routing.summarize(power)
        suggestion = routing.suggest(levels, model)
        row = {
            "name": name,
            "ensemble": sidecar.get("ensemble"),
            "truth": truth_of(sidecar.get("ensemble")),
            "model": model,
            "sidecar_stem": sidecar.get("stem"),
            "region": region,
            "span_s": levels.span_s,
            "active_s": levels.active_s,
            "piano_share": suggestion.evidence.get("piano_share", float("nan")),
            "margin": suggestion.evidence.get("piano_margin_db", float("nan")),
            "under_loudest": suggestion.evidence.get("piano_under_loudest_db", float("nan")),
            "called": called(suggestion),
            "suggested": suggestion.ensemble,
            "stem": suggestion.stem,
            "confidence": suggestion.confidence,
            "reason": suggestion.reason,
            "stems_dir": Path(next(iter(stems.values()))).parent.name,
            "level_db": levels.level_db,
        }
        rows.append(row)
        powers[name] = power
        by_dir[row["stems_dir"]].append(row)
        print(
            f"{row['truth']:8} -> {row['called']:8} share {row['piano_share']:.3f} "
            f"margin {row['margin']:+7.1f} conf {row['confidence']:.2f} "
            f"active {row['active_s']:5.0f} s  stem {row['sidecar_stem']}->{row['stem']}  {name}",
            flush=True,
        )

    confusion = Counter((r["truth"], r["called"]) for r in rows)
    horn = [r for r in rows if r["truth"] == "horn-led"]
    trio = [r for r in rows if r["truth"] == "trio"]
    separation = {}
    if horn and trio:
        separation = {
            "horn_max_piano_share": max(r["piano_share"] for r in horn),
            "trio_min_piano_share": min(r["piano_share"] for r in trio),
            "horn_max_margin_db": max(r["margin"] for r in horn),
            "trio_min_margin_db": min(r["margin"] for r in trio),
            "trio_max_margin_db": max(r["margin"] for r in trio),
            "trio_max_under_loudest_db": max(r["under_loudest"] for r in trio),
            "min_active_s": min(r["active_s"] for r in rows),
            "horn_max_share_track": max(horn, key=lambda r: r["piano_share"])["name"],
            "horn_max_margin_track": max(horn, key=lambda r: r["margin"])["name"],
            "trio_min_share_track": min(trio, key=lambda r: r["piano_share"])["name"],
            "trio_min_margin_track": min(trio, key=lambda r: r["margin"])["name"],
            "min_active_track": min(rows, key=lambda r: r["active_s"])["name"],
        }

    # Leave-one-out of a data-derived rule (the leak check).
    loo_right = 0
    for r in rows if horn and trio else []:
        share_t, margin_t = gap_midpoint_rule(rows, r)
        piano = r["piano_share"] >= share_t and r["margin"] >= margin_t
        loo_right += piano == (r["truth"] == "trio")

    # Sub-windows inside every labelled span, 1 s steps: the shipped rule per
    # length, and the floor sweep. One summary per window serves both.
    windows = {length: FloorStats() for length in WINDOW_LENGTHS_S}
    floors = {f: FloorStats() for f in SWEEP_FLOORS_S}
    lengths = sorted(set(SWEEP_LENGTHS_S) | set(WINDOW_LENGTHS_S))
    for r in rows:
        power = powers[r["name"]]
        n = min(len(v) for v in power.values())
        for length in lengths:
            for start in range(0, n - length + 1, WINDOW_STEP_S):
                levels = slice_levels(power, start, start + length)
                if length in windows:
                    s = routing.suggest(levels, r["model"])
                    windows[length].add(r["truth"], s, r["name"], start, length)
                if length in SWEEP_LENGTHS_S:
                    for f, stats in floors.items():
                        with floor_of(f):
                            s = routing.suggest(levels, r["model"])
                        stats.add(r["truth"], s, r["name"], start, length)

    # Probes that contain a horn: whole files, and horn-through-piano spans.
    probes = []
    edges = []
    seen_files = set()
    for r in horn:
        if r["stems_dir"] in seen_files or "@" in r["stems_dir"]:
            continue  # a span-scoped set is digital zero outside its span
        seen_files.add(r["stems_dir"])
        found = resolve(BENCH / r["name"], r["model"], None)
        if found is None:
            continue
        s = routing.suggest(routing.measure(found[0], None), r["model"])
        probes.append(
            {
                "probe": "whole file",
                "name": r["name"],
                "called": called(s),
                "piano_share": s.evidence.get("piano_share"),
                "margin": s.evidence.get("piano_margin_db"),
                "reason": s.reason,
            }
        )
    for group in by_dir.values():
        pianists = [r for r in group if r["truth"] == "trio"]
        horns = [r for r in group if r["truth"] == "horn-led"]
        for p in pianists:
            for h in horns:
                lo = min(p["region"][0], h["region"][0])
                hi = max(p["region"][1], h["region"][1])
                inside = [x for x in group if lo < x["region"][0] < hi and x not in (p, h)]
                if inside:
                    continue  # only adjacent solos: horn straight into piano
                stems = resolve(BENCH / h["name"], h["model"], (lo, hi))
                if stems is None:
                    continue
                pair_power = routing.window_power(stems[0], (lo, hi))
                s = routing.suggest(routing.summarize(pair_power), h["model"])
                piano_part = (p["region"][1] - p["region"][0]) / (hi - lo)
                probes.append(
                    {
                        "probe": f"horn+piano ({piano_part:.0%} piano)",
                        "name": f"{h['name']} + {p['name']}",
                        "called": called(s),
                        "piano_share": s.evidence.get("piano_share"),
                        "margin": s.evidence.get("piano_margin_db"),
                        "reason": s.reason,
                    }
                )
                horn_first = h["region"][0] < p["region"][0]
                first, second = (h, p) if horn_first else (p, h)
                gap = second["region"][0] - first["region"][1]
                edges.append(
                    {
                        "piano": p["name"],
                        "horn": h["name"],
                        "horn_first": horn_first,
                        "gap_s": gap,
                        "steps": edge_probe(pair_power, lo, p, horn_first, h["model"]),
                    }
                )
    # Unscored: the whole file of a piano track that no horn sidecar shares.
    # A trio record may be piano throughout or not; nothing here says which,
    # so these are printed for the reader and never counted.
    horn_dirs = {r["stems_dir"] for r in horn}
    for r in trio:
        if r["stems_dir"] in horn_dirs or r["stems_dir"] in seen_files or "@" in r["stems_dir"]:
            continue
        seen_files.add(r["stems_dir"])
        found = resolve(BENCH / r["name"], r["model"], None)
        if found is None:
            continue
        s = routing.suggest(routing.measure(found[0], None), r["model"])
        probes.append(
            {
                "probe": "whole file, piano track (unscored)",
                "name": r["name"],
                "called": called(s),
                "piano_share": s.evidence.get("piano_share"),
                "margin": s.evidence.get("piano_margin_db"),
                "reason": s.reason,
            }
        )
    for p in probes:
        share = p["piano_share"]
        margin = p["margin"]
        print(
            f"probe {p['probe']:34} -> {p['called']:8} "
            f"share {share if share is None else round(share, 3)} "
            f"margin {margin if margin is None else round(margin, 1)}  {p['name']}",
            flush=True,
        )

    stem_agree = Counter()
    for r in rows:
        if r["stem"] is None:
            stem_agree["no suggestion"] += 1
        elif r["stem"] == r["sidecar_stem"]:
            stem_agree["agree"] += 1
        else:
            stem_agree[f"{r['sidecar_stem']} -> {r['stem']}"] += 1

    return {
        "model": model_override or "sidecar",
        "min_active_s": routing.MIN_ACTIVE_S,
        "n": len(rows),
        "skipped": skipped,
        "confusion": {f"{t} -> {c}": k for (t, c), k in sorted(confusion.items())},
        "separation": separation,
        "loo_midpoint_rule_right": loo_right,
        "windows": {str(length): stats.as_dict() for length, stats in windows.items()},
        "floor_sweep": {str(f): stats.as_dict() for f, stats in floors.items()},
        "probes": probes,
        "edges": edges,
        "stem_agreement": dict(stem_agree),
        "rows": rows,
    }


def _worst(where):
    if where is None:
        return "none"
    share, margin, name, start, length = where
    return f"{share:.3f} / {margin:+.2f} dB ({length} s @{start} s, {name})"


def _trio(stats):
    if stats["trio_min_share"] is None:
        return "none judged"
    return (
        f"min share {stats['trio_min_share']:.3f}, "
        f"min margin {stats['trio_min_margin_db']:+.2f} dB, "
        f"most under the loudest stem {stats['trio_max_under_loudest_db']:.2f} dB"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", help="measure this separator's stems instead of the sidecar's")
    parser.add_argument("--json", type=Path, help="write the aggregate here")
    args = parser.parse_args(argv)
    result = survey(args.model)
    print()
    print(f"n = {result['n']} spans ({len(result['skipped'])} skipped: no cached stems)")
    print("confusion (truth -> suggestion):")
    for key, count in result["confusion"].items():
        print(f"  {key:22} {count}")
    for key, value in result["separation"].items():
        print(f"  {key:28} {value if isinstance(value, str) else round(value, 3)}")
    print(f"leave-one-out, gap-midpoint rule: {result['loo_midpoint_rule_right']} of {result['n']}")
    print(f"\nwindows at {WINDOW_STEP_S} s steps, floor {result['min_active_s']:.0f} s:")
    for length, stats in result["windows"].items():
        print(f"{length:>3} s: {stats['counts']}")
        print(f"      horn max share   {_worst(stats['horn_max_share'])}")
        print(f"      horn max margin  {_worst(stats['horn_max_margin'])}")
        print(f"      horn joint worst {_worst(stats['horn_joint_worst'])}")
        print("      trio " + _trio(stats))
    print(f"\nfloor sweep, windows of {SWEEP_LENGTHS_S[0]}-{SWEEP_LENGTHS_S[-1]} s:")
    for f, stats in result["floor_sweep"].items():
        print(
            f"floor {float(f):4.0f} s: {stats['counts']}; horn passing share "
            f"{stats['horn_passing_share']}, passing margin {stats['horn_passing_margin']}"
        )
        print(f"      horn max share   {_worst(stats['horn_max_share'])}")
        print(f"      horn max margin  {_worst(stats['horn_max_margin'])}")
        print(f"      horn joint worst {_worst(stats['horn_joint_worst'])}")
        print("      trio " + _trio(stats))
    scored = [p for p in result["probes"] if "unscored" not in p["probe"]]
    print(
        f"\nprobes containing a horn (n={len(scored)}):",
        dict(Counter(p["called"] for p in scored)),
    )
    for edge in result["edges"]:
        side = "before" if edge["horn_first"] else "after"
        steps = ", ".join(
            f"{s['horn_s']}s {s['called']}"
            + ("" if s["piano_share"] is None else f" ({s['piano_share']:.2f}/{s['margin']:+.1f})")
            for s in edge["steps"]
        )
        print(f"edge: horn {side} {edge['piano']} (gap {edge['gap_s']:.1f} s): {steps}")
    print("lead stem:", result["stem_agreement"])
    if args.json:
        args.json.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
