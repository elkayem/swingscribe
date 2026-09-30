"""Hearing against writing, on the triples (docs/roadmap.md A1, docs/triples.md).

    uv run python scripts/triples.py --db wjazz/wjazzd.db
    uv run python scripts/triples.py --db wjazz/wjazzd.db --ab --json out.json

A triple is one solo with a recording, WJazzD's human onsets and beats for
it, and a human transcription page of the same take. For each one this
notates three inputs against the SAME reference -- the page cropped to the
bars that hold the annotated solo (`triples.locate_solo`):

  (a) WJazzD's onsets, pitches and durations on WJazzD's own beat grid, the
      annotator's first downbeat as bar 1 -- no hearing, no grid error;
  (b) the same onsets mapped into our timeline (score_wjazz.identify_all's
      offset and rate) on OUR repaired grid, built exactly as run_eval's
      `notate_run` builds the page it scores -- adds grid error;
  (c) our cached transcription over the same window on our grid -- adds
      hearing. This is run_eval's WJazzD notation page.

and scores each with `benchmark.score_against_notation` (rhythm, value,
coverage) and `score_bars.bar_line_agreement` (on the bar). 1 - (a) is
WRITING, (a) - (b) GRID, (b) - (c) HEARING. A fourth row, (f), is WJazzD's
own tatum positions (`wjazz.annotation_notation`) -- Flex-Q's quantisation,
another algorithm's writing of the same onsets (D36), for scale; its values
are ours, so its `value` means nothing.

Then (a)'s disagreements with the page are counted by kind
(`triples.disagreements`), each class with the raw onset phase behind it on
WJazzD's grid -- whether the page's choice can be read from the timing at
all -- and the written symbols of both pages side by side.

`--ab` re-runs everything under each quantizer rule switched the other way
(R27-R33, by environment override, as run_eval's A/B runs are), paired over
the triples with a sign test. Input (a) is the rule measured with no
transcription or grid error in the way; (c) is what it does to a page we
would ship.

No audio is read: the note cache (.benchmark-notes-c0.2-d0.0.json) and the
grid cache (.benchmark-grids.json) that run_eval writes, the WJazzD
database, and the pages. WJazzD is ODbL and the pages are derivatives of
commercial recordings: only aggregate numbers leave this script, and --json
holds per-triple aggregates, never a note.
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
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import run_eval  # noqa: E402
import wjazz_quantize  # noqa: E402
from score_wjazz import candidates, identify_all  # noqa: E402

from swingscribe import mscz, triples  # noqa: E402
from swingscribe.benchmark import notation_notes, score_against_notation  # noqa: E402
from swingscribe.score_bars import bar_line_agreement  # noqa: E402

OMNIBOOK = "Omnibook"
PDF_PAGE = "PDF page"
# (name, WJazzD melid, the WJazzD copy of the recording, the page, its kind).
# The Omnibook sides are the six WJazzD also annotated whose recording is
# under benchmark/wjazzd/ (KC Blues was not on the first list and is checked
# like the others); the PDF pages are the two silver pages whose recording
# was already a WJazzD track (docs/roadmap.md).
TRIPLES = (
    (
        "Blues For Alice",
        53,
        "wjazzd/Charlie_Parker_Blues_For_Alice_solo_53.m4a",
        "Omnibook/Blues_For_Alice.xml",
        OMNIBOOK,
    ),
    (
        "Donna Lee",
        55,
        "wjazzd/Charlie_Parker_Donna_Lee_solo_55.m4a",
        "Omnibook/Donna_Lee.xml",
        OMNIBOOK,
    ),
    (
        "KC Blues",
        58,
        "wjazzd/Charlie_Parker_KC_Blues_solo_58.m4a",
        "Omnibook/KC_Blues.xml",
        OMNIBOOK,
    ),
    (
        "My Little Suede Shoes",
        60,
        "wjazzd/Charlie_Parker_My_Little_Suede_Shoes_solo_60.m4a",
        "Omnibook/My_Little_Suede_Shoes.xml",
        OMNIBOOK,
    ),
    (
        "Ornithology",
        61,
        "wjazzd/Charlie_Parker_Ornithology_solo_61.m4a",
        "Omnibook/Ornithology.xml",
        OMNIBOOK,
    ),
    (
        "Yardbird Suite",
        68,
        "wjazzd/Charlie_Parker_Yardbird_Suite_solo_68.m4a",
        "Omnibook/Yardbird_Suite.xml",
        OMNIBOOK,
    ),
    (
        "Embraceable You",
        56,
        "wjazzd/Charlie_Parker_Embraceable_You_solo_56.m4a",
        "Transcriptions_Other/musicxml/Charlie-Parker-Embraceable-You.musicxml",
        PDF_PAGE,
    ),
    (
        "Cheese Cake",
        121,
        "wjazzd/Dexter_Gordon_Cheese_Cake_solo_121.m4a",
        "Transcriptions_Other/musicxml/Cheese Cake - Dexter Gordon Solo EDITED 2025.musicxml",
        PDF_PAGE,
    ),
)
# Pairings that must FAIL the take check: another Parker take of the tune
# (the 1948 broadcast page against the 1946 Dial solo), another player on
# the tune, and another tune from the same book. The check is only worth
# something if these read as what they are.
CONTROLS = (
    (
        "Ornithology, the 1948 page",
        61,
        "Transcriptions_Other/musicxml/Ornithology (12-11-1948) - Charlie Parker Solo.musicxml",
    ),
    (
        "Donna Lee, Ryan Kisor's solo",
        55,
        "Transcriptions_Other/musicxml/Donna-Lee-Ryan-Kisors-Trumpet-Solo.musicxml",
    ),
    ("Blues For Alice vs Confirmation", 53, "Omnibook/Confirmation.xml"),
    ("Suede Shoes vs Blues For Alice", 60, "Omnibook/Blues_For_Alice.xml"),
    ("Cheese Cake vs Donna Lee", 121, "Omnibook/Donna_Lee.xml"),
)
INPUTS = ("a", "b", "c")
ALL_INPUTS = ("f", *INPUTS)
MEASURES = ("rhythm", "value", "coverage", "on_the_bar")
# Raw-phase buckets for the onsets behind each class, in beats.
PHASE_EDGES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0)

# The quantizer's rules, each switched the OTHER way from what ships
# (config.QuantizeConfig), by environment override: Config ranks the
# environment first, and every Config the stages build reads it.
RULES = (
    ("R33 figure prior off", {"SWINGSCRIBE_QUANTIZE__FIGURE_PRIOR_WEIGHT": "0"}),
    ("R27 sixteenth gate off", {"SWINGSCRIBE_QUANTIZE__MIN_ONSETS_FOR_SIXTEENTH": "1"}),
    ("R29 lag off", {"SWINGSCRIBE_QUANTIZE__LAG_WINDOW_BEATS": "0"}),
    ("R28 tuplet-inside off", {"SWINGSCRIBE_QUANTIZE__TUPLET_NEEDS_ONSETS_INSIDE": "false"}),
    ("R31 ballad grids on", {"SWINGSCRIBE_QUANTIZE__SLOW_BEAT_S": "0.7"}),
    ("sixteenth triplets on", {"SWINGSCRIBE_QUANTIZE__SIXTEENTH_TRIPLETS": "true"}),
    ("offbeat-pair tuplet on", {"SWINGSCRIBE_QUANTIZE__OFFBEAT_PAIR_TUPLET_FIT": "0.05"}),
    ("tuplet gate at 2 onsets", {"SWINGSCRIBE_QUANTIZE__MIN_ONSETS_FOR_TUPLET": "2"}),
    ("legato cap a quarter", {"SWINGSCRIBE_NOTATE__LEGATO_CAP": "1.0"}),
    ("legato fill 0.75", {"SWINGSCRIBE_NOTATE__LEGATO_FILL": "0.75"}),
    ("swing warp off", {"SWINGSCRIBE_QUANTIZE__STRAIGHT_BUR_CEILING": "99"}),
    ("grid slack off", {"SWINGSCRIBE_QUANTIZE__GRID_SLACK_S": "0"}),
    ("literal 16ths (no swing)", {"SWINGSCRIBE_QUANTIZE__TIMING": "literal-16"}),
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
    """The stages narrate every page they build; eight solos of that would
    bury the tables."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# ── the inputs ───────────────────────────────────────────────────────────────


def notate_annotation(solo: dict):
    """(a): WJazzD's onsets on WJazzD's grid, as wjazz_quantize notates them,
    but under a fresh Config (so an override reaches it) and the horn stem
    run_eval uses (the stem only names the note list)."""
    from swingscribe.config import Config
    from swingscribe.model import NoteEvent
    from swingscribe.notation import notation_for_span

    notes = [
        NoteEvent(
            onset=n["onset"],
            duration=n["duration"],
            pitch=n["pitch"],
            confidence=1.0,
            source="wjazz",
        )
        for n in solo["notes"]
    ]
    grid = solo["grid"]
    return quietly(
        notation_for_span,
        "wjazz",
        notes,
        grid,
        (grid[0], grid[-1]),
        stem="other",
        config=Config(),
        anchor=solo["anchor"],
        time_signature=solo["signature"],
        pulses_per_bar=solo["period"],
    )


# The fit is about the recording and the cached notes, never the quantizer,
# so an A/B run reuses it: (track, melid) -> (fit, status).
FITS: dict = {}


def fit_for(db, track: str, run: dict, melid: int) -> tuple[dict | None, str]:
    """The WJazzD solo `melid` as score_wjazz places it in our timeline, and
    whether identify_all ACCEPTED it (the harness scores only those)."""
    if (track, melid) not in FITS:
        FITS[(track, melid)] = _fit(db, track, run, melid)
    return FITS[(track, melid)]


def _fit(db, track: str, run: dict, melid: int) -> tuple[dict | None, str]:
    import numpy as np

    onsets = np.array([n["onset"] for n in run["notes"]])
    pitches = np.array([int(n["pitch"]) for n in run["notes"]])
    order = np.argsort(onsets)
    onsets, pitches = onsets[order], pitches[order]
    found, why = identify_all(db, track, onsets, pitches, run["region"])
    for solo in found:
        if solo["melid"] == melid:
            return solo, "accepted"
    for solo in candidates(db, track, onsets, pitches, run["region"]):
        if solo["melid"] == melid:
            return solo, f"NOT accepted ({why or 'another solo won'})"
    return None, why or "no candidate"


def notate_mapped(track: str, run: dict, grid: dict, solo: dict, fit: dict, window):
    """(b): the annotator's onsets mapped by the fit, on our grid."""
    rate, offset = fit["rate"], fit["offset"]
    mapped = {
        **run,
        "notes": [
            {
                "onset": triples.mapped(n["onset"], offset, rate),
                "duration": n["duration"] * rate,
                "pitch": n["pitch"],
                "confidence": 1.0,
            }
            for n in solo["notes"]
        ],
    }
    return quietly(run_eval.notate_run, track, mapped, grid, region=window)


def score(notation, crop) -> dict:
    if notation is None or not notation.bars:
        return {}
    scored = score_against_notation(notation, crop)
    agreement = bar_line_agreement(notation, crop)
    ours = notation_notes(notation)
    theirs = [(n.position, n.duration, n.pitch) for n in crop.melody]
    kinds = triples.disagreements(ours, theirs)
    return {
        "rhythm": scored["rhythm"],
        "value": scored["value"],
        "coverage": scored["coverage"],
        "on_the_bar": agreement["on_the_bar"],
        "beat_offset": agreement["beat_offset"],
        "n_matched": scored["n_matched"],
        "written": len(ours),
        "kinds": kinds,
        "symbols": triples.notation_symbols(notation),
    }


# How much nearer, in beats, one place must be before the raw onset is said
# to side with it: about the annotator's and the tapper's own scatter.
SIDE_MARGIN = 0.03


def signed(offset: float) -> float:
    """An offset within a beat, folded into [-0.5, 0.5)."""
    return (offset + 0.5) % 1.0 - 0.5


def raw_phases(solo: dict, notation, kinds: dict) -> tuple[dict, list]:
    """What the annotated onsets behind (a)'s matched notes say, on WJazzD's
    grid -- the grid (a) was notated on, so our positions and the raw
    phases share one clock.

    Per class, (raw phase, onsets in that beat, which place the onset is
    nearer): "page" means the timing itself points at the page's place, so
    a quantizer could have found it; "ours" that the onset sounded nearer
    where we wrote it, and the page applied a CONVENTION the timing does not
    carry (the swing "and", the laid-back beat) or a reading it cannot (an
    anticipation of a note played on the beat).

    And per note, (raw phase, page offset from the sound, ours), in beats:
    where each side wrote the note relative to where it was played.

    Our notes are the annotator's minus any quantize dropped, paired back by
    pitch in order (wjazz_quantize.align: a skip is a drop)."""
    ours = notation_notes(notation)
    pairs, _ = wjazz_quantize.align(solo["notes"], ours)
    source = {j: k for k, j in pairs}
    grid = solo["grid"]
    beat_of = [bisect.bisect_right(grid, n["onset"]) - 1 for n in solo["notes"]]
    per_beat = Counter(beat_of)
    out: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
    offsets: list[tuple[float, float, float]] = []
    for _ri, ei, cls, page_position, our_position in kinds["per_note"]:
        k = source.get(ei)
        if k is None:
            continue
        i = beat_of[k]
        if not 0 <= i < len(grid) - 1:
            continue
        phase = (solo["notes"][k]["onset"] - grid[i]) / (grid[i + 1] - grid[i])
        # Where it sounded, on the page's clock: our position moved back by
        # the (sub-beat) distance the quantizer moved it.
        sounded = our_position + signed(phase - our_position % 1.0)
        page_off, our_off = page_position - sounded, our_position - sounded
        offsets.append((phase, page_off, our_off))
        to_page, to_ours = abs(page_off), abs(our_off)
        side = (
            "page"
            if to_page < to_ours - SIDE_MARGIN
            else "ours"
            if to_ours < to_page - SIDE_MARGIN
            else "neither"
        )
        out[cls].append((phase, per_beat[i], side))
    return out, offsets


def beat_lengths(grid: list[float]) -> list[float]:
    return [b - a for a, b in zip(grid, grid[1:], strict=False)]


def build(db, runs: dict, grids: dict, entry: tuple, located_cache: dict) -> dict:
    """Everything for one triple under the current environment."""
    from swingscribe.wjazz import annotation_notation

    name, melid, track, page_rel, kind = entry
    solo = wjazz_quantize.load_solo(db, melid)
    if solo is None:
        return {"name": name, "skipped": "WJazzD solo not in one quarter-note metre"}
    page_path = run_eval.BENCH / page_rel
    page = mscz.parse_any(page_path)
    if name not in located_cache:
        located_cache[name] = triples.locate_solo(
            page, [(n["position"], n["pitch"]) for n in solo["notes"]]
        )
    located = located_cache[name]
    crop = triples.crop(page, located["lo"], located["hi"])
    run, grid = runs.get(track), grids.get(track)
    fit, fit_status = fit_for(db, track, run, melid) if run else (None, "no cached run")
    out = {
        "name": name,
        "kind": kind,
        "melid": melid,
        "track": track,
        "page": page_rel,
        "tempo_bpm": round(60.0 / statistics.median(beat_lengths(solo["grid"])), 1),
        "located": located,
        "fit": {
            "status": fit_status,
            "match_rate": fit["match_rate"] if fit else None,
            "offset": fit["offset"] if fit else None,
            "rate": fit["rate"] if fit else None,
        },
        "annotated_notes": len(solo["notes"]),
        "inputs": {},
    }
    notations = {
        "f": quietly(annotation_notation, db, melid),
        "a": notate_annotation(solo),
    }
    if fit is not None and grid is not None:
        placed = [triples.mapped(t, fit["offset"], fit["rate"]) for t in fit["ref_on"]]
        window = (placed[0] - run_eval.SOLO_MARGIN_S, placed[-1] + run_eval.SOLO_MARGIN_S)
        out["window"] = window
        notations["b"] = notate_mapped(track, run, grid, solo, fit, window)
        notations["c"] = quietly(run_eval.notate_run, track, run, grid, region=window)
        out["c_input_notes"] = sum(1 for n in run["notes"] if window[0] <= n["onset"] <= window[1])
    for key, notation in notations.items():
        out["inputs"][key] = score(notation, crop)
    if out["inputs"].get("a"):
        out["phases"], out["offsets"] = raw_phases(
            solo, notations["a"], out["inputs"]["a"]["kinds"]
        )
    out["page_symbols"] = triples.page_symbols(page_path, located["first_bar"], located["last_bar"])
    return out


def controls(db) -> list[dict]:
    """`locate_solo` on pairings that are NOT triples (CONTROLS)."""
    out = []
    for name, melid, page_rel in CONTROLS:
        path = run_eval.BENCH / page_rel
        solo = wjazz_quantize.load_solo(db, melid)
        if solo is None or not path.is_file():
            continue
        located = triples.locate_solo(
            mscz.parse_any(path), [(n["position"], n["pitch"]) for n in solo["notes"]]
        )
        out.append({"name": name, "melid": melid, "page": page_rel, "located": located})
    return out


def print_controls(rows: list[dict]) -> None:
    print("\n== Controls: pairings that must fail the take check ==")
    for r in rows:
        loc = r["located"]
        print(
            f"  {r['name']:32} cover {loc['coverage']:.3f} recall {loc['recall']:.3f} "
            f"clock {loc['clock_share']:.3f} transp {loc['transposition']:+d}  "
            f"{'SAME TAKE (wrong!)' if loc['same_take'] else 'refused'}"
        )


def run_all(db, runs, grids, located_cache) -> list[dict]:
    return [build(db, runs, grids, entry, located_cache) for entry in TRIPLES]


# ── reporting ────────────────────────────────────────────────────────────────


def trusted(results: list[dict]) -> list[dict]:
    """The triples that passed both checks: the WJazzD fit accepted by the
    harness's own rule, and the page the same take (`locate_solo`)."""
    return [
        r
        for r in results
        if "skipped" not in r
        and r["located"]["same_take"]
        and r["fit"]["status"] == "accepted"
        and all(r["inputs"].get(k) for k in INPUTS)
    ]


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else float("nan")


def print_pairing(results: list[dict]) -> None:
    print("\n== The pairings ==")
    print(
        f"  {'triple':22} {'melid':>5} {'bpm':>5} {'fit':>9} {'match':>6} {'page bars':>11} "
        f"{'notes':>6} {'cover':>6} {'recall':>6} {'clock':>6} {'transp':>6}  same take"
    )
    for r in results:
        if "skipped" in r:
            print(f"  {r['name']:22} skipped: {r['skipped']}")
            continue
        loc, fit = r["located"], r["fit"]
        rate = f"{fit['match_rate']:.2f}" if fit["match_rate"] is not None else "-"
        print(
            f"  {r['name']:22} {r['melid']:5d} {r['tempo_bpm']:5.0f} {fit['status'][:9]:>9} "
            f"{rate:>6} {loc['first_bar']:>4}-{loc['last_bar']:<6} {loc['page_notes']:6d} "
            f"{loc['coverage']:6.3f} {loc['recall']:6.3f} {loc['clock_share']:6.3f} "
            f"{loc['transposition']:+6d}  {'yes' if loc['same_take'] else 'NO'}"
        )


def print_scores(rows: list[dict]) -> None:
    print(f"\n== Scores against the cropped page, {len(rows)} triples ==")
    for field in MEASURES:
        print(f"  {field}:")
        print(f"    {'triple':22}" + "".join(f" {k:>7}" for k in ALL_INPUTS))
        for r in rows:
            cells = "".join(
                f" {r['inputs'][k][field]:7.3f}" if r["inputs"].get(k) else "       -"
                for k in ALL_INPUTS
            )
            print(f"    {r['name']:22}{cells}")
        cells = "".join(
            f" {mean(r['inputs'][k][field] for r in rows if r['inputs'].get(k)):7.3f}"
            for k in ALL_INPUTS
        )
        print(f"    {'mean':22}{cells}")
    print("  notes the page shows / annotated / written by (a) / dropped by (a):")
    for r in rows:
        written = r["inputs"]["a"]["written"]
        print(
            f"    {r['name']:22} {r['located']['page_notes']:5d} {r['annotated_notes']:5d} "
            f"{written:5d} {r['annotated_notes'] - written:4d}"
        )


def decompositions(rows: list[dict]) -> dict:
    per = {
        r["name"]: triples.decompose(r["inputs"]["a"], r["inputs"]["b"], r["inputs"]["c"])
        for r in rows
    }
    means = {
        field: {
            part: mean(per[n][field][part] for n in per if field in per[n])
            for part in ("writing", "grid", "hearing", "total")
        }
        for field in triples.DECOMPOSED
    }
    return {"per_triple": per, "mean": means}


def print_decomposition(dec: dict, rows: list[dict]) -> dict:
    from swingscribe.evaluation import paired_change

    print(f"\n== Where the distance from the page goes, mean over {len(rows)} ==")
    print(f"  {'measure':11} {'writing':>8} {'grid':>8} {'hearing':>8} {'total':>8}")
    for field, parts in dec["mean"].items():
        print(
            f"  {field:11} {parts['writing']:8.3f} {parts['grid']:8.3f} "
            f"{parts['hearing']:8.3f} {parts['total']:8.3f}"
        )
    print("  paired steps (95% interval by triple, sign test):")
    steps = {}
    for field in MEASURES:
        for before, after, label in (
            ("a", "b", "grid"),
            ("b", "c", "hearing"),
            ("f", "a", "ours vs Flex-Q"),
        ):
            change = paired_change(
                [r["inputs"][before][field] for r in rows],
                [r["inputs"][after][field] for r in rows],
                tolerance=0.002,
            )
            steps[f"{field}/{label}"] = change.__dict__
            print(
                f"    {field:11} {label:15} {change.mean:+.3f} "
                f"[{change.low:+.3f}, {change.high:+.3f}] "
                f"{change.up} up {change.down} down, p={change.p:.2f}"
            )
    return steps


def pooled_kinds(rows: list[dict], key: str) -> dict:
    counters = ("positions", "rhythm_blame", "values", "crosstab", "value_pairs")
    numbers = (
        "matched",
        "intervals",
        "intervals_wrong",
        "missing",
        "extra",
        "substituted",
        "page_notes",
        "our_notes",
    )
    total = {**{f: Counter() for f in counters}, **dict.fromkeys(numbers, 0)}
    for r in rows:
        kinds = r["inputs"][key]["kinds"]
        for field in counters:
            total[field].update(kinds[field])
        for field in numbers:
            total[field] += kinds[field]
    return total


def print_kinds(rows: list[dict], keys=ALL_INPUTS) -> dict:
    pooled = {k: pooled_kinds(rows, k) for k in keys}
    print(f"\n== What the page disagrees with, by kind, pooled over {len(rows)} ==")
    print("  positions of matched notes (share of matched):")
    print(f"    {'class':40}" + "".join(f" {k:>7}" for k in keys))
    for cls in triples.POSITION_CLASSES:
        cells = "".join(
            f" {pooled[k]['positions'][cls] / max(1, pooled[k]['matched']):7.1%}" for k in keys
        )
        print(f"    {cls:40}{cells}")
    print("  wrong intervals charged by class (share of ALL intervals):")
    for cls in triples.POSITION_CLASSES[1:]:
        cells = "".join(
            f" {pooled[k]['rhythm_blame'][cls] / max(1, pooled[k]['intervals']):7.1%}" for k in keys
        )
        print(f"    {cls:40}{cells}")
    print("  wrong values by context (share of matched):")
    for cls in triples.VALUE_CLASSES:
        cells = "".join(
            f" {pooled[k]['values'][cls] / max(1, pooled[k]['matched']):7.1%}" for k in keys
        )
        print(f"    {cls:40}{cells}")
    print("  notes:")
    for field in ("page_notes", "our_notes", "matched", "missing", "extra", "substituted"):
        print(f"    {field:40}" + "".join(f" {pooled[k][field]:7d}" for k in keys))
    print("  page's place -> ours, the commonest misplacements (share of matched), (a) and (c):")
    top = pooled["a"]["crosstab"].most_common(16)
    for (theirs, ours), n in top:
        c_share = pooled["c"]["crosstab"][(theirs, ours)] / max(1, pooled["c"]["matched"])
        print(f"    {theirs:>16} -> {ours:16} {n / pooled['a']['matched']:7.1%} {c_share:7.1%}")
    print(
        "  our written length -> the page's, commonest wrong values (share of matched), (a), (c):"
    )
    for (ours, theirs), n in pooled["a"]["value_pairs"].most_common(14):
        c_share = pooled["c"]["value_pairs"][(ours, theirs)] / max(1, pooled["c"]["matched"])
        print(f"    {ours:>16} -> {theirs:16} {n / pooled['a']['matched']:7.1%} {c_share:7.1%}")
    return pooled


def pooled_phases(rows: list[dict]) -> dict:
    by_class: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
    for r in rows:
        for cls, values in r.get("phases", {}).items():
            by_class[cls].extend(values)
    out = {}
    for cls in triples.POSITION_CLASSES:
        values = by_class.get(cls, [])
        if not values:
            continue
        phases = sorted(p for p, _n, _s in values)
        q = statistics.quantiles(phases, n=4) if len(phases) >= 4 else [phases[0]] * 3
        onsets = Counter(min(n, 4) for _p, n, _s in values)
        sides = Counter(side for _p, _n, side in values)
        histogram = Counter(
            next(
                (
                    f"{lo:.2f}-{hi:.2f}"
                    for lo, hi in zip(PHASE_EDGES, PHASE_EDGES[1:], strict=False)
                    if lo <= p < hi
                ),
                "1.00",
            )
            for p in phases
        )
        out[cls] = {
            "n": len(values),
            "phase_q1": round(q[0], 3),
            "phase_median": round(q[1], 3),
            "phase_q3": round(q[2], 3),
            "onsets_in_beat": {str(k): onsets[k] for k in sorted(onsets)},
            "nearer": dict(sides),
            "phase_histogram": dict(histogram),
        }
    return out


def print_phases(phases: dict) -> None:
    print("\n== The annotated onsets behind (a)'s classes (raw phase on WJazzD's grid) ==")
    print(
        f"    {'class':40} {'n':>5} {'q1':>6} {'median':>6} {'q3':>6}  "
        "onsets in the beat 1/2/3/4+   nearer page/ours/neither"
    )
    for cls, block in phases.items():
        counts = block["onsets_in_beat"]
        total = max(1, block["n"])
        shares = "/".join(f"{100 * counts.get(str(k), 0) / total:.0f}" for k in (1, 2, 3, 4))
        sides = "/".join(
            f"{100 * block['nearer'].get(side, 0) / total:.0f}"
            for side in ("page", "ours", "neither")
        )
        print(
            f"    {cls:40} {block['n']:5d} {block['phase_q1']:6.2f} {block['phase_median']:6.2f} "
            f"{block['phase_q3']:6.2f}  {shares:>27}   {sides}"
        )


def sounded_table(rows: list[dict]) -> dict:
    """By where in the beat a note SOUNDED (raw phase, to the nearest
    eighth of a beat), where the page wrote it and where we did, as offsets
    from the sound rounded to an eighth of a beat."""
    out = {}
    buckets: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        for phase, page_off, our_off in r.get("offsets", []):
            buckets[(round(phase * 8) % 8) / 8].append((page_off, our_off))
    for bucket in sorted(buckets):
        pairs = buckets[bucket]
        n = len(pairs)
        page = Counter(round(p * 8) / 8 for p, _o in pairs)
        ours = Counter(round(o * 8) / 8 for _p, o in pairs)
        agree = sum(1 for p, o in pairs if abs(p - o) <= 1 / 48)
        out[f"{bucket:.3f}"] = {
            "n": n,
            "agree": round(agree / n, 4),
            "page": {f"{k:+.3f}": round(v / n, 4) for k, v in page.most_common(5)},
            "ours": {f"{k:+.3f}": round(v / n, 4) for k, v in ours.most_common(5)},
        }
    return out


def print_sounded(table: dict) -> None:
    print("\n== Where each side writes a note, by where it sounded (a); offsets in beats ==")
    print(f"    {'sounded at':>10} {'n':>5} {'agree':>6}  page writes it / we write it")
    for bucket, block in table.items():
        page = ", ".join(f"{k} {v:.0%}" for k, v in list(block["page"].items())[:4])
        ours = ", ".join(f"{k} {v:.0%}" for k, v in list(block["ours"].items())[:3])
        print(f"    {bucket:>10} {block['n']:5d} {block['agree']:6.0%}  {page}  /  {ours}")


def pooled_symbols(rows: list[dict]) -> dict:
    def add(total: dict, symbols: dict) -> None:
        for field, value in symbols.items():
            if field == "rest_kinds":
                total[field].update(value)
            else:
                total[field] = total.get(field, 0) + value

    out = {}
    for group in (None, OMNIBOOK, PDF_PAGE):
        subset = [r for r in rows if group is None or r["kind"] == group]
        blocks = {}
        for label in ("page", *ALL_INPUTS):
            total = {"rest_kinds": Counter()}
            for r in subset:
                add(total, r["page_symbols"] if label == "page" else r["inputs"][label]["symbols"])
            blocks[label] = total
        out[group or "all"] = {"n": len(subset), "symbols": blocks}
    return out


def print_symbols(pooled: dict) -> None:
    labels = ("page", *ALL_INPUTS)
    for group, block in pooled.items():
        symbols = block["symbols"]
        print(f"\n== Written symbols over the bars that hold the solo: {group}, {block['n']} ==")
        print(f"    {'':26}" + "".join(f" {k:>7}" for k in labels))
        for field in ("notes", "rests"):
            print(f"    {field:26}" + "".join(f" {symbols[k].get(field, 0):7d}" for k in labels))
        for field in ("tie_starts", "tuplet_notes", "dotted_notes"):
            print(
                f"    {field + ' / note':26}"
                + "".join(
                    f" {symbols[k].get(field, 0) / max(1, symbols[k].get('notes', 0)):7.1%}"
                    for k in labels
                )
            )
        sub_eighth = [
            symbols[k].get("sub_eighth_rests", 0) / max(1, symbols[k].get("rests", 0))
            for k in labels
        ]
        print(f"    {'sub-eighth rests / rest':26}" + "".join(f" {x:7.1%}" for x in sub_eighth))
        print(
            f"    {'rests / note':26}"
            + "".join(
                f" {symbols[k].get('rests', 0) / max(1, symbols[k].get('notes', 0)):7.2f}"
                for k in labels
            )
        )
        kinds = sorted({kind for k in labels for kind in symbols[k]["rest_kinds"]})
        for kind in kinds:
            print(
                f"    {'rest: ' + kind:26}"
                + "".join(
                    f" {symbols[k]['rest_kinds'][kind] / max(1, symbols[k].get('rests', 0)):7.1%}"
                    for k in labels
                )
            )


def summary(rows: list[dict]) -> dict:
    return {
        k: {m: round(mean(r["inputs"][k][m] for r in rows), 4) for m in MEASURES}
        for k in ALL_INPUTS
    }


def ab(db, runs, grids, located_cache, baseline: list[dict]) -> dict:
    """Each rule switched the other way, paired over the trusted triples."""
    from swingscribe.evaluation import paired_change

    names = [r["name"] for r in trusted(baseline)]
    before = {r["name"]: r for r in baseline}
    out = {}
    print(f"\n== Rules switched the other way, paired over {len(names)} triples ==")
    print(
        f"  {'rule':26} {'in':3} "
        + " ".join(f"{m:>27}" for m in ("rhythm", "value", "on the bar"))
        + "  written"
    )
    for label, overrides in RULES:
        with environment(overrides):
            after = {r["name"]: r for r in run_all(db, runs, grids, located_cache)}
        out[label] = {}
        for key in INPUTS:
            cells = []
            out[label][key] = {}
            for field in MEASURES:
                change = paired_change(
                    [before[n]["inputs"][key][field] for n in names],
                    [after[n]["inputs"][key][field] for n in names],
                    tolerance=0.002,
                )
                out[label][key][field] = {
                    "mean": round(change.mean, 4),
                    "low": round(change.low, 4),
                    "high": round(change.high, 4),
                    "up": change.up,
                    "down": change.down,
                    "p": round(change.p, 3),
                    "after": round(mean(after[n]["inputs"][key][field] for n in names), 4),
                    "per_triple": {
                        n: round(
                            after[n]["inputs"][key][field] - before[n]["inputs"][key][field], 4
                        )
                        for n in names
                    },
                }
                if field != "coverage":
                    cells.append(
                        f"{change.mean:+.3f} {change.up}up/{change.down}dn p={change.p:.2f}"
                    )
            written = sum(after[n]["inputs"][key]["written"] for n in names) - sum(
                before[n]["inputs"][key]["written"] for n in names
            )
            out[label][key]["written_delta"] = written
            out[label][key]["written_per_triple"] = {
                n: after[n]["inputs"][key]["written"] - before[n]["inputs"][key]["written"]
                for n in names
            }
            if key == "a":
                out[label][key]["positions"] = {
                    cls: sum(after[n]["inputs"][key]["kinds"]["positions"][cls] for n in names)
                    for cls in triples.POSITION_CLASSES
                }
            print(
                f"  {label:26} {key:3} " + " ".join(f"{c:>27}" for c in cells) + f"  {written:+5d}"
            )
    return out


def aggregate_only(result: dict) -> dict:
    """A result with nothing but aggregate numbers in it (the --json file):
    no per-note list, counters as plain dicts, cross-tab keys as text."""

    def plain(value):
        if isinstance(value, Counter):
            return {(" -> ".join(k) if isinstance(k, tuple) else k): v for k, v in value.items()}
        return value

    out = {
        k: v for k, v in result.items() if k not in ("inputs", "phases", "offsets", "page_symbols")
    }
    out["inputs"] = {
        key: {
            **{m: round(v[m], 4) for m in (*MEASURES, "beat_offset", "n_matched", "written")},
            "kinds": {f: plain(x) for f, x in v["kinds"].items() if f != "per_note"},
            "symbols": {f: plain(x) for f, x in v["symbols"].items()},
        }
        for key, v in result.get("inputs", {}).items()
        if v
    }
    if "page_symbols" in result:
        out["page_symbols"] = {f: plain(x) for f, x in result["page_symbols"].items()}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    parser.add_argument("--notes", type=Path, default=run_eval.notes_cache(0.2, 0.0))
    parser.add_argument("--grids", type=Path, default=run_eval.GRIDS_CACHE)
    parser.add_argument("--ab", action="store_true", help="switch each rule the other way")
    parser.add_argument("--json", type=Path, default=None, help="aggregates only")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)

    db = sqlite3.connect(args.db)
    runs = json.loads(args.notes.read_text(encoding="utf-8"))
    grids = json.loads(args.grids.read_text(encoding="utf-8"))
    located_cache: dict = {}
    results = run_all(db, runs, grids, located_cache)
    print_pairing(results)
    control_rows = controls(db)
    print_controls(control_rows)
    rows = trusted(results)
    left_out = [r["name"] for r in results if r not in rows]
    if left_out:
        print(f"  left out: {', '.join(left_out)}")
    print_scores(rows)
    dec = decompositions(rows)
    steps = print_decomposition(dec, rows)
    pooled = print_kinds(rows)
    phases = pooled_phases(rows)
    print_phases(phases)
    sounded = sounded_table(rows)
    print_sounded(sounded)
    symbols = pooled_symbols(rows)
    print_symbols(symbols)
    card = {
        "triples": [aggregate_only(r) for r in results],
        "trusted": [r["name"] for r in rows],
        "controls": control_rows,
        "summary": summary(rows),
        "decomposition": dec,
        "steps": steps,
        "kinds": {
            k: {
                f: (
                    {" -> ".join(x) if isinstance(x, tuple) else x: n for x, n in v.items()}
                    if isinstance(v, Counter)
                    else v
                )
                for f, v in pooled[k].items()
            }
            for k in pooled
        },
        "phases": phases,
        "sounded": sounded,
        "symbols": {
            group: {
                "n": block["n"],
                "symbols": {
                    k: {f: (dict(v) if isinstance(v, Counter) else v) for f, v in s.items()}
                    for k, s in block["symbols"].items()
                },
            }
            for group, block in symbols.items()
        },
    }
    if args.ab:
        card["ab"] = ab(db, runs, grids, located_cache, results)
    if args.json:
        args.json.write_text(json.dumps(card, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
