"""Measure quantize + notate ALONE, with the transcriber out of the loop.

    uv run python scripts/wjazz_quantize.py --db wjazz/wjazzd.db
    uv run python scripts/wjazz_quantize.py --db wjazz/wjazzd.db --melid 186 --show 40
    uv run python scripts/wjazz_quantize.py --db wjazz/wjazzd.db --pin

## The question

Every WJazzD note carries both when it was PLAYED (`onset`, seconds) and
where the annotator FILED it (`bar`, `beat`, `tatum` out of `division`), and
every solo carries the annotator's beat grid in seconds (`beats`). That is
exactly the quantizer's input and its output, 200,000 notes of it, with no
audio, no CREPE and no alignment step: feed the human's onsets on the human's
grid through `swing`, `quantize` and `notate` -- the same three stages the
Export button runs (`notation.notation_for_span`) -- and ask, note by note,
whether we wrote each one where the annotator did.

The listener's complaint that started this (2026-09-19): "even when it gets
the notes right, it chooses timing no human transcriber would use" -- a
swung pair written as a dotted eighth and a sixteenth, a pushed pickup as a
tied thirty-second. Those are quantizer choices, and the twelve hand scores
are too few to see the shape of them. This instrument sees it over 452
solos and names the CLASS of each choice, by tempo.

## What WJazzD's tatum is, and is not

It is not a lead sheet. The Jazzomat annotation files each onset at the
nearest tatum of a per-beat `division` chosen to fit that beat's onsets, so
it is more LITERAL than a transcriber's page: a swung offbeat played at
0.75 of the beat is filed at tatum 4 of 4, a laid-back downbeat at tatum 2
of 4, a pushed one at tatum 4 of the beat before. Counted over the
database, the offbeat of a two-onset beat sits at 1/2 in 22,577 beats, at
2/3 in 5,102 and at 3/4 in 2,500 (2026-09-20). A page writes all three as
an eighth, and so does our quantizer where the swing warp is applied. So a
raw position match undercounts us, and the classes below say WHICH side is
the literal one.

## The classes

Per matched note, from the annotator's position, ours, the raw onset phase
within the beat and how many annotated onsets share the beat:

- **hit**: the same position, to a 24th of a quarter.
- **swing convention**: the offbeat of a beat with at most two onsets,
  filed at 2/3 or 3/4 by the annotator and written at 1/2 by us. A page
  writes an eighth; counted WITH the hits as `page_hit`. The other way
  round is not a convention: OUR 3/4 in such a beat is the dotted eighth
  plus sixteenth of the complaint even where the annotator filed 3/4 too,
  and is charged as `late offbeat as dotted` (the first version of this
  instrument counted it as a hit, and a rule that wrote more of them read
  4 points better here while every hand score got worse, 2026-09-20).
- **annotation literal**: we wrote a beat and the annotator filed the note
  within a sixteenth of it (a laid-back or pushed beat, tatum'd). The page
  writes the beat; not charged to us, reported apart.
- **early offbeat as 16th**: the annotator filed an eighth, we wrote a
  sixteenth or thirty-second BEFORE it (the note was played early, around
  0.3-0.45 of the beat; the swing warp moves it earlier still).
- **late offbeat as dotted**: the annotator filed an eighth (1/2 or 2/3),
  we wrote 3/4 or finer after it: the dotted eighth plus sixteenth of the
  complaint. Happens where the warp was NOT applied to a late offbeat.
- **laid-back beat after it**: the annotator filed the beat, we wrote a
  sixteenth or thirty-second after it (the tied pickup of the complaint).
- **pushed beat before it**: the annotator filed the beat, we wrote it a
  sixteenth or thirty-second early (in the beat before).
- **triplet as binary** / **binary as triplet**: thirds against halves
  and quarters, in beats with three or more annotated onsets.
- **below the grid**: the annotator's division is 5 or finer, or the note
  is otherwise off both grids; the page has no such value.
- **other**: everything else.
- **dropped**: an annotated note our page does not have: two onsets fell
  inside the finest grid step and quantize kept one.

The number is the quantizer's, not the transcriber's: the notes are a
human's, so every class above is a choice of grid or value. Its counterpart
with OUR notes is `run_eval`'s `wjazz-notation/*/rhythm`, which is gap-based
and cannot say which note moved.

## What it is not

WJazzD's durations are a human's note-off, not a written value, so no
value is scored -- the same limit as `score_against_wjazz_notation`. Only
solos in one metre whose beat is a quarter note are used, the same rule as
`wjazz.notated_beats`. ODbL: aggregates only leave this script; `--json`
holds per-solo counts, never a note list.
"""

import argparse
import bisect
import contextlib
import io
import json
import sqlite3
import statistics
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from error_taxonomy import tempo_band  # noqa: E402

BASELINE = REPO_ROOT / "tests/regression/wjazz-quantize-baseline.json"
BANDS = ("SLOW", "MEDIUM SLOW", "MEDIUM", "MEDIUM UP", "UP")
# Positions are compared on a 24th-of-a-quarter grid: the finest thing
# either side writes (a thirty-second is 3/24, a triplet sixteenth 4/24).
GRID = 24
# How many human notes the aligner may skip to find ours again. Quantize
# drops a note only when a grid merges two onsets, one at a time.
MAX_SKIP = 3
EPS = 1.0 / (2 * GRID)
OFFBEAT = {Fraction(1, 2), Fraction(2, 3), Fraction(3, 4)}
THIRDS = {Fraction(1, 3), Fraction(2, 3)}
BINARY = {Fraction(0), Fraction(1, 2), Fraction(1, 4), Fraction(3, 4)}
CLASSES = (
    "hit",
    "swing convention",
    "annotation literal",
    "early offbeat as 16th",
    "late offbeat as dotted",
    "laid-back beat after it",
    "pushed beat before it",
    "triplet as binary",
    "binary as triplet",
    "below the grid",
    "other",
)
PAGE_HITS = ("hit", "swing convention")
NOT_OURS = ("annotation literal",)


def frac_of(position: float) -> Fraction:
    """The position within its beat, on the 24th grid."""
    return Fraction(round(position * GRID) % GRID, GRID)


def load_solo(db, melid: int):
    """The annotator's notes, grid and metre for one solo, or None if the
    metre is not a single quarter-note-beat signature."""
    rows = list(
        db.execute(
            "select onset, duration, pitch, bar, beat, tatum, division, period, num, denom "
            "from melody where melid=? order by onset",
            (melid,),
        )
    )
    rows = [r for r in rows if r[7] and r[3] is not None and r[4] is not None]
    if not rows or len({(r[7], r[9]) for r in rows}) != 1 or rows[0][9] != 4:
        return None
    period = int(rows[0][7])
    notes = [
        {
            "onset": float(onset),
            "duration": float(duration),
            "pitch": int(pitch),
            "position": (bar - 1) * period + (beat - 1) + (tatum - 1) / max(1, division or 1),
            "division": int(division or 1),
        }
        for onset, duration, pitch, bar, beat, tatum, division, _p, _n, _d in rows
    ]
    beats = list(
        db.execute("select onset, bar, beat from beats where melid=? order by onset", (melid,))
    )
    grid = sorted({float(onset) for onset, _bar, _beat in beats})
    downbeats = [float(onset) for onset, _bar, beat in beats if beat == 1]
    return {
        "notes": notes,
        "grid": grid,
        "anchor": downbeats[0] if downbeats else None,
        "period": period,
        "signature": (int(rows[0][8]), 4),
    }


def our_notation(solo):
    """The annotator's onsets through swing, quantize and notate on the
    annotator's grid."""
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
    # The stages report on stdout; 452 solos of that would bury the table.
    with contextlib.redirect_stdout(io.StringIO()):
        return notation_for_span(
            "wjazz",
            notes,
            grid,
            (grid[0], grid[-1]),
            stem="wjazz",
            anchor=solo["anchor"],
            time_signature=solo["signature"],
            pulses_per_bar=solo["period"],
        )


def align(theirs, ours):
    """Pair our notes with the annotator's, in order, by pitch: (i_theirs,
    i_ours) pairs and the annotated notes skipped. Ours is the annotator's
    list with a few notes possibly dropped, so a skip is a drop, never a
    substitution."""
    pairs, skipped = [], 0
    i = 0
    for j, (_pos, _dur, pitch) in enumerate(ours):
        k = i
        while k < len(theirs) and k - i <= MAX_SKIP and theirs[k]["pitch"] != pitch:
            k += 1
        if k >= len(theirs) or k - i > MAX_SKIP:
            continue  # ours has a note the annotator's list cannot supply
        skipped += k - i
        pairs.append((k, j))
        i = k + 1
    skipped += len(theirs) - i
    return pairs, skipped


def classify(h_pos: float, o_pos: float, division: int, onsets_in_beat: int) -> str:
    """One class for one matched note (module docstring)."""
    delta = round((o_pos - h_pos) * GRID) / GRID
    h, o = frac_of(h_pos), frac_of(o_pos)
    same_beat = int(h_pos // 1) == int(o_pos // 1)
    # Our 3/4 in a beat of at most two onsets is the dotted eighth plus
    # sixteenth of the complaint, whatever the annotator filed: a page writes
    # that offbeat as an eighth (the annotator's 3/4 is the tatum's
    # literalness, and is a convention when WE wrote the eighth).
    if same_beat and onsets_in_beat <= 2 and h in OFFBEAT and o == Fraction(3, 4):
        return "late offbeat as dotted"
    if abs(delta) < EPS:
        return "hit"
    if same_beat and onsets_in_beat <= 2 and h in OFFBEAT and o == Fraction(1, 2):
        return "swing convention"
    if o == 0 and abs(delta) <= 0.25 + EPS:
        return "annotation literal"
    if division >= 5 or h not in BINARY | THIRDS | {
        Fraction(1, 8),
        Fraction(3, 8),
        Fraction(5, 8),
        Fraction(7, 8),
        Fraction(1, 6),
        Fraction(5, 6),
    }:
        return "below the grid"
    # A beat of three or more annotated onsets at thirds is a triplet figure;
    # its 2/3 is not an offbeat eighth, whatever we wrote for it.
    if h in THIRDS and o in BINARY and onsets_in_beat >= 3:
        return "triplet as binary"
    if h in BINARY and o in THIRDS:
        return "binary as triplet"
    if h in (Fraction(1, 2), Fraction(2, 3)) and same_beat and o < h:
        return "early offbeat as 16th"
    if h in (Fraction(1, 2), Fraction(2, 3)) and same_beat and o > h and o not in THIRDS:
        return "late offbeat as dotted"
    if h == 0 and delta > 0 and delta <= 0.25 + EPS:
        return "laid-back beat after it"
    if h == 0 and delta < 0 and -delta <= 0.25 + EPS:
        return "pushed beat before it"
    return "other"


def measure(solo, notation):
    """Per-note classes for one solo: counts, and the note rows (kept in
    memory for --show, never written)."""
    from swingscribe.benchmark import notation_notes

    theirs = solo["notes"]
    ours = notation_notes(notation)
    pairs, dropped = align(theirs, ours)
    if len(pairs) < 20:
        return None
    diffs = [ours[j][0] - theirs[k]["position"] for k, j in pairs]
    # The one constant not being asked: which of our bars is their bar 1.
    offset = statistics.mode(round(d * GRID) for d in diffs) / GRID
    per_beat = Counter(int(n["position"] // 1) for n in theirs)
    grid = solo["grid"]
    counts = Counter()
    rows = []
    for k, j in pairs:
        note = theirs[k]
        h_pos = note["position"]
        o_pos = ours[j][0] - offset
        cls = classify(h_pos, o_pos, note["division"], per_beat[int(h_pos // 1)])
        counts[cls] += 1
        i = bisect.bisect_right(grid, note["onset"]) - 1
        phase = (
            (note["onset"] - grid[i]) / (grid[i + 1] - grid[i]) if 0 <= i < len(grid) - 1 else None
        )
        rows.append((note, h_pos, o_pos, phase, cls))
    counts["matched"] = len(pairs)
    counts["dropped"] = dropped
    counts["theirs"] = len(theirs)
    return {"counts": counts, "rows": rows, "offset": offset}


def aggregate(results):
    """Aggregates over solos: totals, the page hit rate, class shares."""
    total = Counter()
    for r in results.values():
        total.update(r["counts"])
    matched = total["matched"] or 1
    charged = matched - sum(total[c] for c in NOT_OURS)
    return {
        "n_solos": len(results),
        "n_notes": total["theirs"],
        "matched": total["matched"],
        "dropped": total["dropped"],
        "hit": round(total["hit"] / matched, 4),
        "page_hit": round(sum(total[c] for c in PAGE_HITS) / max(1, charged), 4),
        # The same over every annotated note we are charged for: a dropped
        # note is a miss here, not an absence. A rule that keeps notes on the
        # page at the cost of a few positions reads better on this one and
        # worse on `page_hit`, and the pages agree with this one (R28).
        "page_hit_all": round(
            sum(total[c] for c in PAGE_HITS) / max(1, charged + total["dropped"]), 4
        ),
        "classes": {c: total[c] for c in CLASSES},
    }


def render(by_band, overall):
    print("\n== Quantize alone on WJazzD: the annotator's onsets on the annotator's grid ==")
    print(
        f"  {overall['n_solos']} solos, {overall['n_notes']} notes; {overall['matched']} matched, "
        f"{overall['dropped']} dropped by our page"
    )
    print(
        f"  on the annotator's tatum: {overall['hit']:.1%}; on the page's position "
        f"(swing convention allowed, literal tatums set aside): {overall['page_hit']:.1%}; "
        f"counting a dropped note as a miss: {overall['page_hit_all']:.1%}"
    )
    print(
        f"\n  {'tempo band':12} {'solos':>5} {'notes':>7} {'tatum':>7} {'page':>7} "
        f"{'page+drop':>9} {'dropped':>8}"
    )
    for band, agg in by_band.items():
        print(
            f"  {band:12} {agg['n_solos']:5d} {agg['n_notes']:7d} {agg['hit']:7.1%} "
            f"{agg['page_hit']:7.1%} {agg['page_hit_all']:9.1%} {agg['dropped']:8d}"
        )
    print(f"\n  {'class':26} {'all':>7} {'share':>6}  " + " ".join(f"{b[:6]:>7}" for b in by_band))
    matched = overall["matched"]
    for cls in CLASSES:
        n = overall["classes"][cls]
        per_band = " ".join(
            f"{a['classes'][cls] / max(1, a['matched']):7.1%}" for a in by_band.values()
        )
        print(f"  {cls:26} {n:7d} {n / matched:6.1%}  {per_band}")
    n = overall["dropped"]
    per_band = " ".join(f"{a['dropped'] / max(1, a['n_notes']):7.1%}" for a in by_band.values())
    print(f"  {'dropped (of annotated)':26} {n:7d} {n / overall['n_notes']:6.1%}  {per_band}")


def show_rows(name, result, limit):
    print(f"\n  {name}: offset {result['offset']:+.2f} quarters")
    print(f"  {'onset':>8} {'pitch':>5} {'theirs':>8} {'ours':>8} {'phase':>6}  class")
    for note, h_pos, o_pos, phase, cls in result["rows"][:limit]:
        flag = "" if cls in PAGE_HITS else "  <--"
        shown = f"{phase:6.2f}" if phase is not None else "     -"
        print(
            f"  {note['onset']:8.3f} {note['pitch']:5d} {h_pos:8.3f} {o_pos:8.3f} {shown}  "
            f"{cls}{flag}"
        )


def compare(current: dict, pinned: dict) -> int:
    moved = 0
    for band in sorted(set(current) | set(pinned)):
        a, b = pinned.get(band, {}), current.get(band, {})
        for field in ("hit", "page_hit", "page_hit_all", "n_solos", "dropped"):
            if a.get(field) != b.get(field):
                print(f"  {band}/{field}: {a.get(field)} -> {b.get(field)}")
                moved += 1
        for cls in CLASSES:
            x, y = a.get("classes", {}).get(cls), b.get("classes", {}).get(cls)
            if x != y:
                print(f"  {band}/{cls}: {x} -> {y}")
                moved += 1
    print("  unchanged" if not moved else f"  {moved} number(s) moved; --pin if intended")
    return 1 if moved else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "wjazz/wjazzd.db")
    parser.add_argument("--melid", type=int, action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--show", type=int, default=0, help="print the first N notes per solo")
    parser.add_argument("--json", type=Path, default=None, help="per-solo counts (no notes)")
    parser.add_argument("--pin", action="store_true")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    solos = list(
        db.execute("select melid, performer, title, avgtempo from solo_info order by melid")
    )
    if args.melid:
        solos = [s for s in solos if s[0] in set(args.melid)]
    if args.limit:
        solos = solos[: args.limit]

    results, bands = {}, {}
    for melid, performer, title, tempo in solos:
        solo = load_solo(db, melid)
        if solo is None or len(solo["grid"]) < 16:
            continue
        notation = our_notation(solo)
        if notation is None:
            continue
        result = measure(solo, notation)
        if result is None:
            continue
        name = f"{performer} - {title} (solo {melid})"
        results[name] = result
        bands[name] = tempo_band(tempo or 0.0)
        if args.show:
            show_rows(name, result, args.show)

    by_band = {}
    for band in BANDS:
        subset = {n: r for n, r in results.items() if bands[n] == band}
        if subset:
            by_band[band] = aggregate(subset)
    overall = aggregate(results)
    render(by_band, overall)

    card = {"overall": overall, "band": by_band}
    if args.json:
        card["solos"] = {
            n: {"band": bands[n], "counts": dict(r["counts"]), "offset": r["offset"]}
            for n, r in results.items()
        }
        args.json.write_text(json.dumps(card, indent=2), encoding="utf-8")
    if args.pin:
        BASELINE.write_text(
            json.dumps({"overall": overall, "band": by_band}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nPinned to {BASELINE}.")
        return
    if BASELINE.is_file():
        old = json.loads(BASELINE.read_text(encoding="utf-8"))
        print("\n== Against the pin ==")
        raise SystemExit(
            compare({"overall": overall, **by_band}, {"overall": old["overall"], **old["band"]})
        )


if __name__ == "__main__":
    main()
