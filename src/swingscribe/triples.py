"""Hearing against writing: one solo, three inputs, one human page.

A TRIPLE is a solo for which three things exist: the recording, WJazzD's
per-note annotation of it (onsets in seconds, pitches, and a tapped beat
grid, all a human's), and a human transcription PAGE of the same take --
LORIA's Omnibook, or a PDF read by `pdf2musicxml`. Nothing else in the
benchmark holds all three, and together they split the distance between our
page and the human's into three parts that no other measurement can
separate (docs/roadmap.md A1, docs/triples.md):

- **(a)** WJazzD's onsets on WJazzD's OWN beat grid, through swing, quantize
  and notate. No hearing and no grid error: every difference from the page
  is a WRITING choice (or a disagreement between two humans about which
  notes were played, which `coverage` sees).
- **(b)** the same onsets mapped into our timeline, on OUR repaired beat
  grid. What (b) loses against (a) is GRID error.
- **(c)** our own transcription over the same window on our grid -- the page
  the Export button would write. What (c) loses against (b) is HEARING.

D36 took the quantizer's old instrument away: WJazzD's tatum layer is
Flex-Q's quantisation, not a transcriber's. This uses only WJazzD's ONSETS
and BEATS, which are a human's, and judges the result against a human page.

Everything here is pure arithmetic over plain lists and a parsed `mscz.Score`,
like `alignment.py` and `score_bars.py`, so it runs in CI. The I/O -- the
database, the caches, the notating -- is `scripts/triples.py`.
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from swingscribe.alignment import TRANSPOSE_SEARCH, align
from swingscribe.benchmark import COVERAGE_FLOOR, NOTATION_TOLERANCE
from swingscribe.mscz import Score
from swingscribe.score_bars import EDGE_SHARE, PHASE_SHARE_FLOOR

# ── placing the annotated solo on the page ──────────────────────────────────
#
# An Omnibook page holds the head and the solo, and `alignment.align` is
# GLOBAL: handed the whole page against one annotated solo it matches the
# head too, and every number after that is about the wrong music (CLAUDE.md,
# R13). So the page is cropped to the stretch that holds the solo first, by
# content: WJazzD's pitches aligned to the page's, and each true match a vote
# for how far the page's quarter-note clock sits from the annotation's.

# How many transposition candidates the pitch histogram offers the full
# alignment. The page may be written for a transposing horn (a tenor page is
# +14) and its opening is the head, not the solo, so the prefix search
# `measured_transposition` uses would be settling on the wrong music.
HISTOGRAM_CANDIDATES = 5
# The window either side of the solo's first and last note, in quarters:
# just under half a beat. A first note the page writes a sixteenth from
# where the annotation files it is still the solo's; the head's last eighth,
# half a beat before it, is not.
CROP_MARGIN = 0.5 - 1.0 / 48.0


def _histogram_shifts(reference: list[int], estimate: list[int], top: int) -> list[int]:
    """The `top` transpositions under which the two pitch histograms overlap
    most -- a shortlist for the full alignment, never the answer."""
    ref, est = Counter(reference), Counter(estimate)
    overlap = {
        shift: sum(count * ref.get(pitch + shift, 0) for pitch, count in est.items())
        for shift in TRANSPOSE_SEARCH
    }
    return sorted(overlap, key=lambda s: (-overlap[s], abs(s)))[:top]


def best_offset(reference: list[int], estimate: list[int]) -> tuple[int, list]:
    """(semitones to add to `estimate`, the true (ri, ei) matches at it).

    Candidates are the histogram's shortlist and the octaves either side of
    each, every one aligned IN FULL; the most true matches wins.
    """
    if not reference or not estimate:
        return 0, []
    candidates = set()
    for shift in _histogram_shifts(reference, estimate, HISTOGRAM_CANDIDATES):
        candidates.update(s for s in (shift - 12, shift, shift + 12) if s in TRANSPOSE_SEARCH)
    best: tuple[int, list] = (0, [])
    for shift in sorted(candidates, key=abs):
        pairs = true_matches(reference, [p + shift for p in estimate])
        if len(pairs) > len(best[1]):
            best = (shift, pairs)
    return best


def true_matches(reference: list[int], estimate: list[int]) -> list[tuple[int, int]]:
    """(reference index, estimate index) for aligned pairs of EQUAL pitch.

    A substitution pairs two different notes and says nothing about where
    either sits, so it never votes (benchmark.anchor_map, same rule).
    """
    aligned = align(reference, estimate)
    return [
        (ri, ei)
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and reference[ri] == estimate[ei]
    ]


def _mode(values: list[int]) -> int | None:
    return Counter(values).most_common(1)[0][0] if values else None


def locate_solo(page: Score, solo: list[tuple[float, int]]) -> dict:
    """Where on `page` the annotated `solo` sits, and whether it is the same take.

    `solo` is (position in quarters from the annotation's own bar 1, pitch)
    per annotated note, in order. Each true match of the pitch alignment
    votes the page's position minus the annotation's, rounded to a whole
    beat; the mode over the first and the last quarter of the matches
    (score_bars.EDGE_SHARE) places the two ends separately, so a bar the
    page omits or doubles part-way costs only that bar.

    Returned: `lo`/`hi`, the page window in quarters (CROP_MARGIN either
    side); `transposition` (page = solo + this); `clock_share`, the share of
    matches whose shift is the one commonest AROUND them (`local_shifts`:
    a bar the page omits is a step, not a scatter); `coverage`, the share
    of the page's notes in the window the solo matches, and `recall`, the
    share of the solo's notes. `same_take` needs coverage over
    benchmark.COVERAGE_FLOOR AND clock share over score_bars.
    PHASE_SHARE_FLOOR -- floors measured for their own questions, reused
    rather than tuned here: another take of a bebop head is still two
    eighth-note lines in one key, and matches scattered at chance cannot
    hold one clock.
    """
    empty = {
        "lo": 0.0,
        "hi": 0.0,
        "transposition": 0,
        "matched": 0,
        "clock_share": 0.0,
        "coverage": 0.0,
        "recall": 0.0,
        "page_notes": 0,
        "first_bar": 0,
        "last_bar": 0,
        "same_take": False,
    }
    theirs = [n.pitch for n in page.melody]
    ours = [pitch for _, pitch in solo]
    shift, pairs = best_offset(theirs, ours)
    if not pairs:
        return empty
    deltas = [round(page.melody[ri].position - solo[ei][0]) for ri, ei in pairs]
    local = local_shifts([float(d) for d in deltas])
    clock_share = sum(1 for d, s in zip(deltas, local, strict=True) if d == s) / len(deltas)
    edge = max(1, round(len(deltas) * EDGE_SHARE))
    first_shift = _mode(deltas[:edge])
    last_shift = _mode(deltas[-edge:])
    lo = solo[0][0] + first_shift - CROP_MARGIN
    hi = solo[-1][0] + last_shift + CROP_MARGIN
    cropped = crop(page, lo, hi)
    kept = [n.pitch for n in cropped.melody]
    matched = len(true_matches(kept, [p + shift for p in ours]))
    coverage = matched / len(kept) if kept else 0.0
    return {
        "lo": lo,
        "hi": hi,
        "transposition": shift,
        "matched": matched,
        "clock_share": clock_share,
        "coverage": coverage,
        "recall": matched / len(ours),
        "page_notes": len(kept),
        "first_bar": cropped.melody[0].bar if kept else 0,
        "last_bar": cropped.melody[-1].bar if kept else 0,
        "same_take": coverage >= COVERAGE_FLOOR and clock_share >= PHASE_SHARE_FLOOR,
    }


def crop(page: Score, lo: float, hi: float) -> Score:
    """`page` with only the notes whose position is in [lo, hi].

    Positions are NOT re-origined: `score_bars.bar_line_agreement` reads a
    note's beat as its position modulo the bar, and the parser pads every
    short bar to its signature, so the page's own origin is what keeps its
    bar lines where it drew them.
    """
    melody = [n for n in page.melody if lo <= n.position <= hi]
    notes = [n for n in page.notes if lo <= n.position <= hi]
    return Score(
        title=page.title,
        notes=notes,
        melody=melody,
        bars=len({n.bar for n in melody}),
        beats_per_bar=page.beats_per_bar,
        key_fifths=page.key_fifths,
        graces=page.graces,
    )


# ── what the disagreements are ──────────────────────────────────────────────
#
# `benchmark.score_notation` says how often a gap or a value agrees; this says
# what we wrote INSTEAD, per matched note, so a rhythm deficit can be charged
# to a kind of choice. Positions are compared after the page's bar 1 and ours
# are reconciled LOCALLY -- the whole-beat shift commonest among the matches
# around each one -- so a bar one side omits reads as one slip, not as every
# note after it misplaced (the idea of score_bars.difference_trace).

# Two positions closer than this are the same place: half a 24th of a
# quarter, the finest lattice either side writes (a 32nd is 3/24, a triplet
# sixteenth 4/24).
POSITION_TOLERANCE = 1.0 / 48.0
# Matches either side whose shift votes a note's local shift.
LOCAL_WINDOW = 15
# A gap longer than this, in quarters, after a note's written end is a rest.
REST_GAP = 0.02

POSITION_CLASSES = (
    "hit",
    "downbeat written on the e",
    "downbeat written on the a before",
    "offbeat written late (dotted figure)",
    "offbeat written early (sixteenth)",
    "offbeat written on a beat",
    "downbeat written on an and",
    "page sixteenth written on an eighth",
    "sixteenth moved",
    "triplet read binary",
    "binary read as triplet",
    "triplet moved",
    "a 32nd apart",
    "page finer than our lattice",
    "a beat or more apart",
    "other",
)
# Names for written lengths, in quarters (a tuplet member by its sounding
# length: a triplet eighth is a third of a beat).
VALUE_NAMES = (
    (4.0, "whole"),
    (3.0, "half."),
    (2.0, "half"),
    (1.5, "quarter."),
    (1.0, "quarter"),
    (0.75, "eighth."),
    (2 / 3, "quarter-triplet"),
    (0.5, "eighth"),
    (0.375, "16th."),
    (1 / 3, "triplet-8th"),
    (0.25, "16th"),
    (1 / 6, "16th-triplet"),
    (0.125, "32nd"),
)
# Names for places in the beat, for the cross-tab of what the page wrote
# against what we wrote.
PLACE_NAMES = {
    0: "beat",
    3: "32nd after",
    4: "1/6",
    6: "e",
    8: "1/3",
    9: "32nd before and",
    12: "and",
    15: "32nd after and",
    16: "2/3",
    18: "a",
    20: "5/6",
    21: "32nd before beat",
}
VALUE_CLASSES = (
    "we rest where the page holds",
    "we hold where the page rests",
    "both rest, different lengths",
    "beside a note or position that differs",
    "last note",
    "other",
)


def _on_lattice(frac: float, division: int) -> bool:
    return abs(frac * division - round(frac * division)) < 1e-6 * division + 1e-9


def _frac(position: float) -> float:
    """The place within its beat, on the 24th lattice where it is on it."""
    value = position - math.floor(position)
    snapped = round(value * 24) / 24
    return (snapped % 1.0) if abs(value - snapped) < 1e-6 else value


def _binary(frac: float) -> bool:
    return _on_lattice(frac, 8)


def _ternary(frac: float) -> bool:
    return _on_lattice(frac, 12) and not _binary(frac)


def value_name(length: float) -> str:
    """A written length, named; "longer" past a whole, "other" off the table."""
    for value, name in VALUE_NAMES:
        if abs(length - value) < 0.02:
            return name
    return "longer" if length > 4.0 else "other"


def place_name(position: float) -> str:
    """A position's place in its beat, named: "beat", "e", "and", "a",
    "1/3", "2/3", a 32nd, or "k/24" for anything else on the lattice."""
    frac = _frac(position)
    if not _on_lattice(frac, 24):
        return "off the lattice"
    step = round(frac * 24) % 24
    return PLACE_NAMES.get(step, f"{step}/24")


def position_class(theirs: float, ours: float) -> str:
    """One class for one matched note: `theirs` is the page's position,
    `ours` our position already moved onto the page's clock.

    Named for what a reader sees. "downbeat written on the e" is the R29
    complaint (a line behind the beat written a sixteenth late), "offbeat
    written late (dotted figure)" the R27 one (a swung eighth written as a
    dotted eighth and a sixteenth); "a 32nd apart" is any binary place a
    32nd from the page's, which a reader barely notices and `rhythm`'s
    tolerance forgives.
    """
    residual = ours - theirs
    if abs(residual) <= POSITION_TOLERANCE:
        return "hit"
    if abs(residual) >= 1.0 - POSITION_TOLERANCE:
        return "a beat or more apart"
    h, o = _frac(theirs), _frac(ours)
    if not _on_lattice(h, 24):
        return "page finer than our lattice"
    if _ternary(h):
        return "triplet read binary" if _binary(o) else "triplet moved"
    if _ternary(o):
        return "binary read as triplet"
    if not _binary(o) or not _binary(h):
        return "other"
    if abs(abs(residual) - 0.125) <= POSITION_TOLERANCE:
        return "a 32nd apart"
    if h == 0.0:
        if residual > 0 and abs(o - 0.25) < 1e-9:
            return "downbeat written on the e"
        if residual < 0 and abs(o - 0.75) < 1e-9:
            return "downbeat written on the a before"
        if abs(o - 0.5) < 1e-9:
            return "downbeat written on an and"
        return "other"
    if abs(h - 0.5) < 1e-9:
        if abs(o - 0.75) < 1e-9:
            return "offbeat written late (dotted figure)"
        if abs(o - 0.25) < 1e-9:
            return "offbeat written early (sixteenth)"
        if o == 0.0:
            return "offbeat written on a beat"
        return "other"
    if _on_lattice(h, 4):  # the "e" or the "a"
        return "page sixteenth written on an eighth" if _on_lattice(o, 2) else "sixteenth moved"
    return "other"


def local_shifts(deltas: list[float], window: int = LOCAL_WINDOW) -> list[int]:
    """Per match, the whole-beat shift commonest among the `window` matches
    either side (ties to the whole run's commonest)."""
    rounded = [round(d) for d in deltas]
    overall = _mode(rounded)
    out = []
    for i in range(len(rounded)):
        counts = Counter(rounded[max(0, i - window) : i + window + 1]).most_common()
        top = counts[0][1]
        tied = {value for value, count in counts if count == top}
        out.append(overall if overall in tied else counts[0][0])
    return out


def disagreements(
    ours: list[tuple[float, float, int]], theirs: list[tuple[float, float, int]]
) -> dict:
    """Our notes against the page's, note by note, as KINDS of difference.

    Both are (position in quarters, written length, pitch), ties merged, in
    order (`benchmark.notation_notes` and `mscz.Score.melody`). Pairing is
    `alignment.align` at the offset the whole line settles, exactly as
    `benchmark.score_against_notation` pairs them -- so `rhythm` and `value`
    here are that scorer's numbers, and a test holds them equal.

    What comes back, beside those two:

    - `positions`: every true match in one of POSITION_CLASSES;
    - `rhythm_blame`: every WRONG interval (the ones `rhythm` counts against
      us) charged to the class of the end that moved -- half to each when
      both did, to "a beat or more apart" when the local shift changes
      between them;
    - `values`: every wrong value in one of VALUE_CLASSES. A value that is
      wrong beside a note or a position that differs is "rhythm wearing a
      value" (docs/notation-survey.md); only where both notes and both
      positions agree is the difference a choice of length or rest;
    - `missing` (page notes with no true match), `extra` (ours with none),
      `substituted` (aligned pairs of different pitch, counted in both);
    - `crosstab`: (the page's place in the beat, ours) for every matched
      note that is not a hit; `value_pairs`: (our written length, the
      page's) for every wrong value; and `per_note`: (page index, our index,
      class, the page's position, ours moved onto the page's clock) per
      match, for a caller that can say more about a note (the raw onset
      behind it). `per_note` is not aggregate: keep it out of a file.
    """
    from swingscribe.alignment import measured_transposition

    result = {
        "matched": 0,
        "page_notes": len(theirs),
        "our_notes": len(ours),
        "missing": len(theirs),
        "extra": len(ours),
        "substituted": 0,
        "intervals": 0,
        "intervals_wrong": 0,
        "rhythm": 0.0,
        "value": 0.0,
        "positions": Counter(),
        "rhythm_blame": Counter(),
        "values": Counter(),
        "crosstab": Counter(),
        "value_pairs": Counter(),
        "per_note": [],
        "transposition": 0,
    }
    if not ours or not theirs:
        return result
    offset, aligned = measured_transposition([p for *_, p in theirs], [p for *_, p in ours])
    matched = [
        (ri, ei)
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and theirs[ri][2] == ours[ei][2] + offset
    ]
    result["transposition"] = offset
    result["substituted"] = sum(
        1
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and theirs[ri][2] != ours[ei][2] + offset
    )
    if not matched:
        return result
    result["matched"] = len(matched)
    result["missing"] = len(theirs) - len(matched)
    result["extra"] = len(ours) - len(matched)

    deltas = [ours[ei][0] - theirs[ri][0] for ri, ei in matched]
    shifts = local_shifts(deltas)
    classes = [
        position_class(theirs[ri][0], ours[ei][0] - shift)
        for (ri, ei), shift in zip(matched, shifts, strict=True)
    ]
    result["positions"] = Counter(classes)
    result["per_note"] = [
        (ri, ei, cls, theirs[ri][0], ours[ei][0] - shift)
        for (ri, ei), shift, cls in zip(matched, shifts, classes, strict=True)
    ]
    result["crosstab"] = Counter(
        (place_name(theirs[ri][0]), place_name(ours[ei][0] - shift))
        for (ri, ei), shift, cls in zip(matched, shifts, classes, strict=True)
        if cls != "hit"
    )
    index_of = {pair: i for i, pair in enumerate(matched)}

    intervals = wrong = 0
    for i, ((ri, ei), (nri, nei)) in enumerate(zip(matched, matched[1:], strict=False)):
        if nri != ri + 1 or nei != ei + 1:
            continue
        intervals += 1
        gap_theirs = theirs[nri][0] - theirs[ri][0]
        gap_ours = ours[nei][0] - ours[ei][0]
        if abs(gap_ours - gap_theirs) <= NOTATION_TOLERANCE:
            continue
        wrong += 1
        here, there = classes[i], classes[i + 1]
        if shifts[i] != shifts[i + 1]:
            result["rhythm_blame"]["a beat or more apart"] += 1.0
        elif here == "hit" or there == "hit":
            result["rhythm_blame"][there if here == "hit" else here] += 1.0
        else:
            result["rhythm_blame"][here] += 0.5
            result["rhythm_blame"][there] += 0.5
    result["intervals"] = intervals
    result["intervals_wrong"] = wrong
    result["rhythm"] = (intervals - wrong) / intervals if intervals else 0.0

    valued = 0
    for i, (ri, ei) in enumerate(matched):
        written, page_value = ours[ei][1], theirs[ri][1]
        if abs(written - page_value) <= NOTATION_TOLERANCE:
            valued += 1
            continue
        result["value_pairs"][(value_name(written), value_name(page_value))] += 1
        if ri + 1 >= len(theirs) or ei + 1 >= len(ours):
            result["values"]["last note"] += 1
            continue
        following = index_of.get((ri + 1, ei + 1))
        if (
            classes[i] != "hit"
            or following is None
            or classes[following] != "hit"
            or shifts[following] != shifts[i]
        ):
            result["values"]["beside a note or position that differs"] += 1
            continue
        rest_ours = ours[ei + 1][0] - (ours[ei][0] + written) > REST_GAP
        rest_theirs = theirs[ri + 1][0] - (theirs[ri][0] + page_value) > REST_GAP
        if rest_ours and not rest_theirs:
            result["values"]["we rest where the page holds"] += 1
        elif rest_theirs and not rest_ours:
            result["values"]["we hold where the page rests"] += 1
        elif rest_ours and rest_theirs:
            result["values"]["both rest, different lengths"] += 1
        else:
            result["values"]["other"] += 1
    result["value"] = valued / len(matched)
    return result


# ── the written symbols ─────────────────────────────────────────────────────
#
# Positions and lengths are what the quantizer chooses; the SYMBOLS are what
# a reader sees -- a tie, a tuplet bracket, a dot, a rest of an odd length.
# Counted over the bars that hold the solo, on each side.

# Written lengths (quarters, tuplet ratio undone) that carry a dot.
DOTTED = (3.0, 1.5, 0.75, 0.375, 0.1875)
REST_NAMES = (
    (4.0, "whole"),
    (3.0, "dotted half"),
    (2.0, "half"),
    (1.5, "dotted quarter"),
    (1.0, "quarter"),
    (0.75, "dotted eighth"),
    (0.5, "eighth"),
    (0.375, "dotted 16th"),
    (0.25, "16th"),
    (0.125, "32nd"),
)
TYPE_QUARTERS = {
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
}


def _rest_name(written: float) -> str:
    for value, name in REST_NAMES:
        if abs(written - value) < 1e-3:
            return name
    return "other"


def _empty_symbols() -> dict:
    return {
        "notes": 0,
        "rests": 0,
        "tie_starts": 0,
        "tuplet_notes": 0,
        "dotted_notes": 0,
        "sub_eighth_rests": 0,
        "rest_kinds": Counter(),
    }


def _count(symbols: dict, written: float, is_rest: bool, tied: bool, tuplet: bool) -> None:
    if is_rest:
        symbols["rests"] += 1
        symbols["rest_kinds"][_rest_name(written)] += 1
        symbols["sub_eighth_rests"] += written < 0.5 - 1e-6
        return
    symbols["notes"] += 1
    symbols["tie_starts"] += tied
    symbols["tuplet_notes"] += tuplet
    symbols["dotted_notes"] += any(abs(written - d) < 1e-3 for d in DOTTED)


def notation_symbols(notation) -> dict:
    """The written symbols of our page, over the bars from the one holding
    its first note to the one holding its last (voice 1)."""
    symbols = _empty_symbols()
    sounding = [i for i, bar in enumerate(notation.bars) if any(not n.is_rest for n in bar.notes)]
    if not sounding:
        return symbols
    for bar in notation.bars[sounding[0] : sounding[-1] + 1]:
        for note in bar.notes:
            if note.voice != 1:
                continue
            written = note.duration * (note.tuplet[0] / note.tuplet[1] if note.tuplet else 1.0)
            _count(symbols, written, note.is_rest, note.tie_start, note.tuplet is not None)
    return symbols


def page_symbols(path: str | Path, first_bar: int, last_bar: int) -> dict:
    """The same count off a MusicXML page, over measures `first_bar` to
    `last_bar` (1-based, in file order: `mscz.ScoreNote.bar`), the first
    voice, grace notes and chord tones left out."""
    symbols = _empty_symbols()
    root = ElementTree.parse(Path(path)).getroot()
    part = root.find("part")
    if part is None:
        return symbols
    for number, measure in enumerate(part.findall("measure"), start=1):
        if not first_bar <= number <= last_bar:
            continue
        for note in measure.findall("note"):
            if note.find("chord") is not None or note.find("grace") is not None:
                continue
            if (note.findtext("voice") or "1").strip() != "1":
                continue
            kind = note.findtext("type")
            is_rest = note.find("rest") is not None
            if kind is None:
                # A whole-bar rest is often written with no type at all.
                if is_rest:
                    symbols["rests"] += 1
                    symbols["rest_kinds"]["whole bar"] += 1
                continue
            written = TYPE_QUARTERS.get(kind, 0.0) * (2.0 - 0.5 ** len(note.findall("dot")))
            _count(
                symbols,
                written,
                is_rest,
                any(t.get("type") == "start" for t in note.findall("tie")),
                note.find("time-modification") is not None,
            )
    return symbols


# ── the decomposition ───────────────────────────────────────────────────────

DECOMPOSED = ("rhythm", "value", "coverage", "on_the_bar")


def decompose(a: dict, b: dict, c: dict, fields: tuple[str, ...] = DECOMPOSED) -> dict:
    """1 - (a) is WRITING, (a) - (b) is GRID, (b) - (c) is HEARING, per field.

    The three add up to 1 - (c), the whole distance from the human page. A
    negative part is a finding, not an error: our grid can happen to write a
    figure nearer the page than the annotator's taps do.
    """
    out = {}
    for field in fields:
        if field not in a or field not in b or field not in c:
            continue
        out[field] = {
            "writing": 1.0 - a[field],
            "grid": a[field] - b[field],
            "hearing": b[field] - c[field],
            "total": 1.0 - c[field],
        }
    return out


def mapped(onset: float, offset: float, rate: float) -> float:
    """An annotated onset in OUR timeline: `score_wjazz.fit_affine`'s
    their_time * rate + offset, the whole fit (two numbers about the
    recording's transfer, none about the playing)."""
    return onset * rate + offset
