"""How SwingScribe writes a solo, beside how the humans write one.

Four corpora, one vocabulary. For every page the harness can build (the
twelve hand-scored tracks, the twenty-two Omnibook sides, the located WJazzD
solos) this notates the cached notes under the CURRENT quantizer, exactly as
`run_eval` does, and tallies what it wrote: note values, rests, ties,
tuplets, where in the beat the onsets sit and how far apart they are. The
same tallies are made of the references -- the listener's `.mscz`, LORIA's
Omnibook MusicXML, WJazzD's bar/beat/tatum -- over the SAME tracks, so a
difference is a difference of writing, not of repertoire.

Two kinds of tally, because the references carry different evidence:

- **written vocabulary** (note types, dots, tuplet ratios, rests, ties) is
  read from the page itself -- ours, the `.mscz` XML, the Omnibook XML.
  WJazzD has no page: its values would be ours (wjazz.annotation_notation).
- **positions** (where in the beat an onset sits; how far to the next one)
  are exact in every corpus, WJazzD included, and are what the quantizer
  actually chooses. Ties are merged first, so a note is one onset.

Usage:
    uv run python scripts/notation_survey.py --db wjazz/wjazzd.db [--json out.json]

Nothing here needs audio; it reads the harness's note cache and grid cache.
Only aggregates may leave this script (plan section 12).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import sqlite3
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval  # noqa: E402

from swingscribe import mscz  # noqa: E402
from swingscribe.mscz import read_mscx_xml  # noqa: E402

TOL = 0.02

# Written value of a duration in quarter notes. Tuplet members are named by
# their written symbol (a triplet eighth is 1/3 of a beat, written "eighth").
VALUES = [
    (4.0, "whole"),
    (3.0, "half."),
    (2.0, "half"),
    (1.5, "quarter."),
    (1.0, "quarter"),
    (0.75, "eighth."),
    (0.5, "eighth"),
    (0.375, "16th."),
    (0.25, "16th"),
    (0.1875, "32nd."),
    (0.125, "32nd"),
]

POSITIONS = [
    (Fraction(0), "beat"),
    (Fraction(1, 2), "and"),
    (Fraction(1, 4), "e"),
    (Fraction(3, 4), "a"),
    (Fraction(1, 3), "1/3"),
    (Fraction(2, 3), "2/3"),
    (Fraction(1, 6), "1/6"),
    (Fraction(5, 6), "5/6"),
    (Fraction(1, 8), "odd 32nd"),
    (Fraction(3, 8), "odd 32nd"),
    (Fraction(5, 8), "odd 32nd"),
    (Fraction(7, 8), "odd 32nd"),
]

GAPS = [
    (2.0, "half+"),
    (1.5, "dotted quarter"),
    (1.0, "quarter"),
    (0.75, "dotted eighth"),
    (2 / 3, "two triplet eighths"),
    (0.5, "eighth"),
    (0.375, "dotted 16th"),
    (1 / 3, "triplet eighth"),
    (0.25, "16th"),
    (1 / 6, "16th triplet"),
    (0.125, "32nd"),
]


def nearest(value: float, table, tol: float = TOL, floor: str | None = None) -> str:
    for target, name in table:
        if abs(value - float(target)) < tol:
            return name
    if floor is not None and value >= float(table[0][0]):
        return floor
    return "other"


class Tally:
    """One corpus's counts. `add_written` takes the page; `add_onsets` the line."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.notes: Counter = Counter()
        self.rests: Counter = Counter()
        self.positions: Counter = Counter()
        self.gaps: Counter = Counter()
        self.n_notes = 0
        self.n_rests = 0
        self.tied = 0
        self.tuplet = 0
        self.n_onsets = 0
        self.tracks = 0

    def add_written(self, kind: str, is_rest: bool, tied: bool, in_tuplet: bool) -> None:
        if is_rest:
            self.rests[kind] += 1
            self.n_rests += 1
            return
        self.notes[kind] += 1
        self.n_notes += 1
        self.tied += tied
        self.tuplet += in_tuplet

    def add_onsets(self, positions: list[float]) -> None:
        """Onsets in beats (quarter notes) from the start; ties already merged."""
        for a, b in zip(positions, positions[1:], strict=False):
            self.positions[nearest(a % 1.0, POSITIONS)] += 1
            self.gaps[nearest(b - a, GAPS, floor="half+")] += 1
        if positions:
            self.positions[nearest(positions[-1] % 1.0, POSITIONS)] += 1
        self.n_onsets += len(positions)

    def as_dict(self) -> dict:
        def pct(counter: Counter, total: int) -> dict[str, float]:
            if not total:
                return {}
            return {k: round(100.0 * v / total, 2) for k, v in counter.most_common()}

        return {
            "tracks": self.tracks,
            "notes": self.n_notes,
            "rests": self.n_rests,
            "onsets": self.n_onsets,
            "tie_rate": round(self.tied / self.n_notes, 4) if self.n_notes else None,
            "tuplet_share": round(self.tuplet / self.n_notes, 4) if self.n_notes else None,
            "note_values_pct": pct(self.notes, self.n_notes),
            "rest_values_pct": pct(self.rests, self.n_rests),
            "onset_positions_pct": pct(self.positions, self.n_onsets),
            "gap_to_next_pct": pct(self.gaps, sum(self.gaps.values())),
        }


# ── ours: the harness's pages ────────────────────────────────────────────────


def written_kind(duration: float, tuplet: tuple[int, int] | None) -> str:
    written = duration * tuplet[0] / tuplet[1] if tuplet else duration
    name = nearest(written, VALUES, tol=1e-3)
    return f"{name}[{tuplet[0]}:{tuplet[1]}]" if tuplet else name


def add_notation(tally: Tally, notation) -> None:
    onsets: list[float] = []
    origin = 0.0
    for bar in notation.bars:
        num, den = bar.time_signature
        for note in bar.notes:
            if note.voice != 1:
                continue
            tally.add_written(
                written_kind(note.duration, note.tuplet),
                note.is_rest,
                note.tie_start,
                note.tuplet is not None,
            )
            if not note.is_rest and not note.tie_stop:
                onsets.append(origin + note.beat)
        origin += num * 4.0 / den
    tally.add_onsets(onsets)
    tally.tracks += 1


# ── the references ───────────────────────────────────────────────────────────


def add_musicxml(tally: Tally, path: Path) -> None:
    """LORIA's Omnibook: `type`, dots, `time-modification`, `tie`."""
    root = ElementTree.parse(path).getroot()
    part = root.find("part")
    if part is None:
        return
    for note in part.iter("note"):
        if note.find("chord") is not None:
            continue
        kind = (note.findtext("type") or "measure") + "." * len(note.findall("dot"))
        tm = note.find("time-modification")
        if tm is not None:
            kind += f"[{tm.findtext('actual-notes')}:{tm.findtext('normal-notes')}]"
        tally.add_written(
            kind,
            note.find("rest") is not None,
            any(t.get("type") == "start" for t in note.findall("tie")),
            tm is not None,
        )
    tally.tracks += 1


GRACE = ("acciaccatura", "appoggiatura", "grace4", "grace8", "grace16", "grace32", "grace8after")


def add_mscz(tally: Tally, path: Path) -> None:
    """The listener's MuseScore file: `durationType`, `dots`, `Tuplet`, `Tie`."""
    root = ElementTree.fromstring(read_mscx_xml(path))
    score = root.find("Score")
    staff = score.find("Staff") if score is not None else None
    if staff is None:
        return
    ratio = ""
    for measure in staff.findall("Measure"):
        for voice in measure.findall("voice"):
            for element in voice:
                if element.tag == "Tuplet":
                    ratio = f"[{element.findtext('actualNotes')}:{element.findtext('normalNotes')}]"
                elif element.tag == "endTuplet":
                    ratio = ""
                elif element.tag in ("Chord", "Rest"):
                    if element.tag == "Chord" and any(element.find(g) is not None for g in GRACE):
                        continue  # takes no time; mscz.parse keeps its pitch
                    dots = int(element.findtext("dots", "0") or 0)
                    kind = element.findtext("durationType", "?") + "." * dots + ratio
                    tied = (
                        element.find("Note/Spanner[@type='Tie']/next") is not None
                        or element.find("Note/Tie") is not None
                    )
                    tally.add_written(kind, element.tag == "Rest", tied, bool(ratio))
    tally.tracks += 1


def add_score_onsets(tally: Tally, path: Path) -> None:
    score = mscz.parse_any(path)
    tally.add_onsets([n.position for n in score.melody])


def add_wjazz_onsets(tally: Tally, db: sqlite3.Connection, melid: int) -> bool:
    row = db.execute("SELECT signature FROM solo_info WHERE melid=?", (melid,)).fetchone()
    signature = row[0] if row else None
    if not signature or "/" not in signature or ";" in signature:
        return False
    period = int(signature.split("/")[0])
    rows = db.execute(
        "SELECT bar, beat, tatum, division FROM melody WHERE melid=? ORDER BY onset", (melid,)
    ).fetchall()
    tally.add_onsets(
        [bar * period + (beat - 1) + (tatum - 1) / division for bar, beat, tatum, division in rows]
    )
    tally.tracks += 1
    return True


# ── assembly ─────────────────────────────────────────────────────────────────


def sidecar_of(key: str) -> dict:
    path = run_eval.BENCH / f"{run_eval.track_of(key)}.swingscribe.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def survey(db_path: Path | None, step_cost: float, dip_db: float, grids_path: Path) -> dict:
    quiet = lambda *_: None  # noqa: E731
    cache = run_eval.notes_cache(step_cost, dip_db)
    runs = run_eval.transcribe_all(cache, step_cost, dip_db, log=quiet)
    grids = run_eval.beat_grids(grids_path, log=quiet)
    tallies: dict[str, Tally] = {}

    def tally(name: str) -> Tally:
        return tallies.setdefault(name, Tally(name))

    # The hand-scored tracks and the Omnibook: our page over the sidecar's
    # span, the reference from the sidecar's score. Default take only.
    for key, run in sorted(runs.items()):
        if run_eval.take_of(key) is not None:
            continue
        sidecar = sidecar_of(key)
        score_path = sidecar.get("score")
        if not score_path or not Path(score_path).is_file():
            continue
        track = run_eval.track_of(key)
        if track not in grids:
            continue
        book = run_eval.is_omnibook(key)
        score = Path(score_path)
        # A score generated from WJazzD (scripts/wjazz_score.py) carries OUR
        # values on the annotator's positions; it is surveyed as WJazzD below.
        if not book and score.suffix.lower() not in (".mscz", ".mscx"):
            continue
        notation = run_eval.notate_run(key, run, grids[track])
        if notation is None or not notation.bars:
            continue
        ours = tally("ours vs Omnibook" if book else "ours vs hand scores")
        theirs = tally("Omnibook (LORIA)" if book else "hand scores (.mscz)")
        add_notation(ours, notation)
        if book:
            add_musicxml(theirs, score)
        else:
            add_mscz(theirs, score)
        add_score_onsets(theirs, score)

    if db_path is not None:
        db = sqlite3.connect(db_path)
        located = run_eval.wjazz_scores(db_path, runs, grids, run_eval.default_jobs())
        ours = tally("ours vs WJazzD")
        theirs = tally("WJazzD (annotation, located)")
        for key, entry in sorted(located.items()):
            if "melid" not in entry:
                continue
            name = entry.get("run") or key.split(" [")[0]
            track = run_eval.track_of(name)
            if name not in runs or track not in grids:
                continue
            window = (
                entry["solo_start"] - run_eval.SOLO_MARGIN_S,
                entry["solo_end"] + run_eval.SOLO_MARGIN_S,
            )
            notation = run_eval.notate_run(name, runs[name], grids[track], region=window)
            if notation is None or not notation.bars:
                continue
            if add_wjazz_onsets(theirs, db, entry["melid"]):
                add_notation(ours, notation)
        whole = tally("WJazzD (annotation, all solos)")
        for (melid,) in db.execute("SELECT melid FROM solo_info ORDER BY melid"):
            add_wjazz_onsets(whole, db, melid)

    return {name: t.as_dict() for name, t in tallies.items()}


def render(result: dict) -> None:
    def line(title: str, values: dict, top: int = 12) -> None:
        cells = ", ".join(f"{k} {v:.1f}%" for k, v in list(values.items())[:top])
        print(f"  {title}: {cells}")

    for name, block in result.items():
        head = f"== {name}: {block['tracks']} tracks"
        if block["notes"]:
            head += (
                f", {block['notes']} notes, {block['rests']} rests,"
                f" tie rate {block['tie_rate']:.3f},"
                f" tuplets {100 * block['tuplet_share']:.1f}%"
            )
        else:
            head += f", {block['onsets']} onsets"
        print(head)
        if block["note_values_pct"]:
            line("note values", block["note_values_pct"])
            line("rest values", block["rest_values_pct"], top=8)
        line("onset in beat", block["onset_positions_pct"])
        line("gap to next", block["gap_to_next_pct"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=None, help="wjazzd.db; skips WJazzD if absent")
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    parser.add_argument("--grids", type=Path, default=run_eval.GRIDS_CACHE)
    parser.add_argument("--json", type=Path, default=None, help="write the tallies here")
    args = parser.parse_args()
    # The stages narrate every page they build (swing spans, notes placed);
    # a survey over a hundred pages wants only the tallies.
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()):
        result = survey(args.db, args.step_cost, args.dip_db, args.grids)
    render(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
