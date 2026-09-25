"""Pitches read exactly off a notation-program PDF's own drawing.

A PDF exported by Sibelius or Finale draws its staff lines as thin paths
and sets every notehead, accidental and clef as a glyph of a music font,
at a position. Those are not pixels to recognise: the staff lines say
where the lines are, a notehead's height above the bottom line IS its
staff step, and the glyph to its left IS its accidental. So for the
written pitch of every note on such a page there is no need to trust an
OMR engine at all -- the engine's reading is kept for what the text layer
cannot say (durations, rests, ties, tuplets), and its pitches are
corrected to the printed ones by aligning the two note sequences.

The rules of notation applied here: a step is a half-space from the bottom
line (treble: E4, bass: G2); an accidental holds for its letter and octave
until the bar line; the key signature's accidentals hold everywhere else;
a tied-into note keeps its pitch. Nothing here reads durations.

Three more things the page prints as glyphs, read the same way: the tuplet
NUMBER (a lone digit in the staff's band, centred on its group of
noteheads -- the engines miss two fifths of the corpus's triplets and
write three plain eighths), the TIME SIGNATURE (two music-font digits
stacked at the first staff's start, or a common/cut-time glyph), and the
TEMPO (a music-text beat glyph, "=", a number, and the words before them).
"""

from __future__ import annotations

import difflib
import math
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from pdf2musicxml.pdfpages import is_music_font, music_family

STEPS = "CDEFGAB"
ACCIDENTALS = {"b": -1, "#": 1, "n": 0, "": -1, "": 1, "": 0}
CLEFS = {"&": "treble", "?": "bass", "": "treble", "": "bass"}

# Metronome-mark beat glyphs in the Sibelius and Finale TEXT fonts (Opus
# Text, Inkpen2 Text, Reprise Text, Engraver Text, Jazz Text).
BEAT_GLYPHS = {"w": "whole", "h": "half", "q": "quarter", "e": "eighth", "x": "16th"}
BEAT_QUARTERS = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}
# A tuplet digit and the count it plays in the time of.
TUPLET_NORMAL = {3: 2, 5: 4, 6: 4, 7: 4}
# Rest glyphs share their codes across Opus, Inkpen2 and Maestro (measured
# 2026-09-24); the box is the check that a code means what it should.
# Flag glyphs in Opus, Inkpen2 and Maestro: one flag (an eighth), two (a sixteenth).
FLAG_CODES = {"j": 1, "J": 1, "k": 2, "K": 2}
REST_CODES = {
    "‰": "eighth",
    "Œ": "quarter",
    "≈": "16th",
    "Ó": "half",
    "∑": "whole",
}
REST_BOXES = {  # height range, width range, in staff spaces
    "eighth": ((1.4, 2.3), (0.7, 1.8)),
    "quarter": ((2.6, 3.6), (0.7, 1.8)),
    "16th": ((2.5, 3.4), (0.9, 2.0)),
    "half": ((0.3, 0.8), (0.9, 2.2)),
    "whole": ((0.3, 0.9), (0.9, 2.3)),
}


def rest_value(char: str, width: float, height: float, spacing: float, step: int) -> str | None:
    """The rest a music glyph is, by its code and its box; None when it is not one."""
    value = REST_CODES.get(char)
    if value is None or spacing <= 0 or not -2 <= step <= 10:
        return None
    (low_h, high_h), (low_w, high_w) = REST_BOXES[value]
    if low_h <= height / spacing <= high_h and low_w <= width / spacing <= high_w:
        return value
    return None


def is_notehead_box(width: float, height: float, spacing: float) -> str | None:
    """ "head", "grace" or None, from a music glyph's box in staff spaces.

    Codes differ by font and encoding (a Finale PDF puts its half head at
    U+02D9, Sibelius its quarter REST at U+0152), but a notehead is always
    about a space tall and a little wider than tall: black, half, cross
    and diamond heads alike. Accidentals and rests are two to four spaces
    tall, a half or whole rest half a space tall and twice as wide,
    augmentation and staccato dots under half a space. A grace head is the
    same shape at two thirds the size.
    """
    if spacing <= 0 or height <= 0:
        return None
    h, w = height / spacing, width / spacing
    if not 0.5 <= h <= 1.6 or not 0.8 <= w / h <= 1.7:
        return None
    return "grace" if h < 0.8 else "head"


# The bottom line's letter index (C=0) and octave, by clef.
CLEF_BOTTOM = {"treble": (2, 4), "bass": (4, 2)}


@dataclass(frozen=True)
class Staff:
    bottom: float  # y of the bottom line, page points (y grows upward)
    spacing: float  # between lines
    left: float
    right: float

    @property
    def top(self) -> float:
        return self.bottom + 4 * self.spacing

    def step_of(self, y: float) -> int:
        return round((y - self.bottom) / (self.spacing / 2))

    def holds(self, y: float, ledger_spaces: float = 6.0) -> bool:
        margin = ledger_spaces * self.spacing
        return self.bottom - margin <= y <= self.top + margin


@dataclass
class Printed:
    """One notehead on the page, with what stood beside it."""

    x: float
    y: float
    staff: int
    step: int
    kind: str  # head
    grace: bool
    char: str = ""
    alter: int | None = None  # an explicit accidental, if one stood before it
    letter: str = ""
    octave: int = 0
    sounding_alter: int = 0  # once the bar and key rules are applied
    page: int = 0  # index within the transcription's pages, once collected
    bar: int = 0  # bar lines passed on its staff, by the page's paths
    key_alter: int = 0  # the key signature's alter for its letter
    value: str = ""  # a rest's written value ("eighth"); heads carry none


@dataclass(frozen=True)
class Glyph:
    """One character of the text layer with its font and box (page points, y up)."""

    char: str
    font: str
    left: float
    bottom: float
    right: float
    top: float

    @property
    def x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def y(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom


@dataclass
class TupletMark:
    """A tuplet number printed over or under a group of noteheads."""

    x: float
    y: float
    staff: int
    count: int  # the digit: 3 for a triplet
    spacing: float  # the staff's, for tolerances
    page: int = 0


@dataclass
class TimeMark:
    staff: int
    x: float
    beats: int
    beat_type: int
    symbol: str | None = None  # "common" or "cut" when printed as a glyph
    page: int = 0
    bar: int = 0  # bar lines passed on its staff: the bar it begins

    @property
    def text(self) -> str:
        return f"{self.beats}/{self.beat_type}"


@dataclass
class MultiRest:
    """A multi-bar rest: a thick bar on the middle line with its count over it."""

    staff: int
    x: float  # the bar's centre
    count: int
    page: int = 0
    bar: int = 0


@dataclass(frozen=True)
class Tempo:
    unit: str  # "quarter", "half", ...
    dots: int
    per_minute: int
    words: str = ""  # "Medium Swing", when printed before the mark

    @property
    def quarters_per_minute(self) -> float:
        return self.per_minute * BEAT_QUARTERS[self.unit] * (2 - 0.5**self.dots)

    @property
    def text(self) -> str:
        mark = f"{self.unit}{'.' * self.dots} = {self.per_minute}"
        return f"{self.words} {mark}".strip()


@dataclass
class PagePrint:
    staves: list[Staff]
    notes: list[Printed]  # reading order: staff by staff, left to right
    clefs: list[str]  # per staff
    keys: list[dict[str, int]]  # per staff: letter -> alter
    barlines: list[list[float]]  # per staff: x of each bar line
    tuplets: list[TupletMark] = field(default_factory=list)
    times: list[TimeMark] = field(default_factory=list)  # in reading order
    tempo: Tempo | None = None
    rests: list[Printed] = field(default_factory=list)  # kind "rest", value set
    flags: list[tuple[int, float, float, int]] = field(default_factory=list)  # staff, x, y, n
    beams: list[tuple[int, float, float, float, float]] = field(default_factory=list)
    multirests: list[MultiRest] = field(default_factory=list)


# ---------------------------------------------------------------- geometry


def find_staves(page) -> list[Staff]:
    """Staves from the thin, wide paths: five equally spaced lines, top of the page first."""
    import pypdfium2.raw as raw

    width, _height = page.get_size()
    lines = []
    for obj in page.get_objects(max_depth=4):
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        left, bottom, right, top = obj.get_bounds()
        if top - bottom < 2.0 and right - left > 0.3 * width:
            lines.append(((bottom + top) / 2, left, right))
    lines.sort()
    staves: list[Staff] = []
    i = 0
    while i + 4 < len(lines):
        ys = [lines[i + k][0] for k in range(5)]
        gaps = [ys[k + 1] - ys[k] for k in range(4)]
        if 3.0 < gaps[0] < 14.0 and max(gaps) - min(gaps) < 0.15 * gaps[0]:
            staves.append(
                Staff(
                    bottom=ys[0],
                    spacing=sum(gaps) / 4,
                    left=min(lines[i + k][1] for k in range(5)),
                    right=max(lines[i + k][2] for k in range(5)),
                )
            )
            i += 5
        else:
            i += 1
    return sorted(staves, key=lambda s: -s.bottom)


def find_barlines(page, staves: list[Staff]) -> list[list[float]]:
    """Per staff, the x of every bar line: a thin vertical path overshooting BOTH outer lines alike.

    A stem is a thin vertical path too, and a beamed stem can span the
    staff almost exactly, so height alone took every stem for a bar line
    (Whisper Not read 116 on a 33-bar page, 2026-09-24): the pitch reader
    reset its accidentals at each one and a tuplet number's group
    "straddled a bar line". What tells them apart, measured on Opus,
    Inkpen2 and Maestro pages: a bar line runs 0.15-0.35 of a space past
    the bottom line and the same past the top line, while a stem ends ON
    a notehead at one end (a line or a space) and at a beam or flag at
    the other. Sibelius also draws bar lines wider than stems (3.2 against
    2.0 points in Inkpen2); Finale draws them alike, so width is only a
    floor here, never the test.
    """
    import pypdfium2.raw as raw

    candidates: list[tuple[float, float, float, float]] = []
    widths: list[float] = []
    for obj in page.get_objects(max_depth=4):
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        left, bottom, right, top = obj.get_bounds()
        # Up to 8 points wide: a double bar line is one path in some exports.
        if right - left > 8.0 or top - bottom < 8.0 or top - bottom > 400.0:
            continue
        candidates.append((left, bottom, right, top))
        widths.append(right - left)
    widths.sort()
    stem_width = widths[len(widths) // 2] if widths else 0.0
    result: list[list[float]] = [[] for _ in staves]
    for left, bottom, right, top in candidates:
        if right - left < 0.9 * stem_width:
            continue
        for index, staff in enumerate(staves):
            below = (staff.bottom - bottom) / staff.spacing
            above = (top - staff.top) / staff.spacing
            # 0.05: an older Finale export overshoots by 0.07 of a space.
            if 0.05 <= below <= 0.7 and 0.05 <= above <= 0.7 and abs(below - above) <= 0.12:
                result[index].append((left + right) / 2)
    # A double bar line is two paths a point or two apart: one bar line.
    merged: list[list[float]] = []
    for xs, staff in zip(result, staves, strict=True):
        clusters: list[list[float]] = []
        for x in sorted(xs):
            if clusters and x - clusters[-1][-1] <= 1.0 * staff.spacing:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        merged.append([sum(c) / len(c) for c in clusters])
    return merged


def bar_index(bars: list[float], x: float, spacing: float) -> int:
    """Bar lines passed on a staff before x: the bar a mark or notehead at x sits in."""
    bar = 0
    while bar < len(bars) and x > bars[bar] + 0.5 * spacing:
        bar += 1
    return bar


def multi_rests(
    paths: list[tuple[float, float, float, float]],
    glyphs: list[Glyph],
    staves: list[Staff],
    barlines: list[list[float]],
    heads: list[Printed],
) -> list[MultiRest]:
    """The multi-bar rests on the page: a thick bar on the middle line with its count over it.

    Sibelius and Finale both draw the H-bar as one filled path four
    spaces or wider and about three quarters of a space thick, centred
    on the middle line (No Room For Squares: 21-30 spaces wide, 0.69
    thick; Artie Shaw's Interlude: 9.9 wide, 1.0 thick), and set the
    count in the music font above the staff over the bar (Opus 2.1
    spaces tall, Maestro 2.0). A beam can lie on the middle line too,
    so the bar must hold no notehead and the count must stand over it.
    """
    out: list[MultiRest] = []
    digits = [
        g
        for g in glyphs
        if g.char.isdigit()
        and is_music_font(g.font)
        and "chord" not in g.font.lower()
        and "text" not in g.font.lower()
    ]
    for staff_index, staff in enumerate(staves):
        spacing = staff.spacing
        bars = barlines[staff_index] if staff_index < len(barlines) else []
        for left, bottom, right, top in paths:
            width, thick = right - left, top - bottom
            if width < 4 * spacing or not 0.4 * spacing <= thick <= 1.3 * spacing:
                continue
            if staff.step_of((bottom + top) / 2) != 4 or left < staff.left or right > staff.right:
                continue
            over = sorted(
                (
                    g
                    for g in digits
                    if left <= g.x <= right
                    and 1.6 * spacing <= g.height <= 2.6 * spacing
                    and 8 <= staff.step_of(g.y) <= 18
                ),
                key=lambda g: g.x,
            )
            if not over:
                continue
            count = int("".join(g.char for g in over))
            if count < 2:
                continue
            centre = (left + right) / 2
            bar = bar_index(bars, centre, spacing)
            span_left = bars[bar - 1] if bar > 0 else staff.left
            span_right = bars[bar] if bar < len(bars) else staff.right
            if any(h.staff == staff_index and span_left < h.x < span_right for h in heads):
                continue
            out.append(MultiRest(staff_index, centre, count))
    return out


def find_beams(page, staves: list[Staff]) -> list[tuple[int, float, float, float, float]]:
    """Every path that could be a beam, as (staff, left, bottom, right, top).

    A beam is a filled path under two spaces wide or more (a tight pair), half a
    space thick (up to a space and a half with its slope), within eight
    spaces of a staff; every beam of a group is its own path (two paths
    over a run of sixteenths). Ties, slurs, tuplet brackets and text
    lines pass this sieve too; `_beams_over` tells them apart by where
    they end and how far from the heads they sit.
    """
    import pypdfium2.raw as raw

    out: list[tuple[int, float, float, float, float]] = []
    for obj in page.get_objects(max_depth=4):
        if obj.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        left, bottom, right, top = obj.get_bounds()
        width, height = right - left, top - bottom
        for index, staff in enumerate(staves):
            spacing = staff.spacing
            if not 1.8 * spacing <= width <= 0.5 * (staff.right - staff.left):
                continue
            if not 0.3 * spacing <= height <= 1.6 * spacing:
                continue
            if top < staff.bottom - 8 * spacing or bottom > staff.top + 8 * spacing:
                continue
            out.append((index, left, bottom, right, top))
    return out


# ---------------------------------------------------------------- reading a page


def read_page(pdf: Path, index: int) -> PagePrint | None:
    """Every notehead on the page with its staff step and explicit accidental; None if no staves."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument(str(pdf))
    page = doc[index]
    staves = find_staves(page)
    if not staves:
        return None
    barlines = find_barlines(page, staves)
    glyphs = _glyphs(page.get_textpage(), raw)
    heads: list[Printed] = []
    rests: list[Printed] = []
    flags: list[tuple[int, float, float, int]] = []  # staff, x, y, flags
    accidentals: list[tuple[float, float, int, int]] = []  # x, y, staff, alter
    clef_marks: list[tuple[int, float, str]] = []  # staff, x, clef
    for glyph in glyphs:
        char, font = glyph.char, glyph.font
        lowered = font.lower()
        if not is_music_font(font) or "chord" in lowered or "text" in lowered:
            continue
        left, bottom, right, top = glyph.left, glyph.bottom, glyph.right, glyph.top
        x, y = glyph.x, glyph.y
        candidates = [k for k, staff in enumerate(staves) if staff.holds(y)]
        if not candidates:
            continue
        staff_index = min(candidates, key=lambda k: abs((staves[k].bottom + staves[k].top) / 2 - y))
        staff = staves[staff_index]
        shape = is_notehead_box(right - left, top - bottom, staff.spacing)
        if char in ACCIDENTALS and top - bottom >= 2.0 * staff.spacing:
            # A sharp or natural is drawn about its line; a flat's bowl sits
            # at the bottom of a tall glyph, 30% of the height up (measured
            # on Opus and Inkpen2: 0.30 and 0.33).
            reference = bottom + 0.3 * (top - bottom) if ACCIDENTALS[char] == -1 else y
            accidentals.append((x, reference, staff_index, ACCIDENTALS[char]))
        elif char in CLEFS and top - bottom >= 4.0 * staff.spacing:
            clef_marks.append((staff_index, x, CLEFS[char]))
        elif shape is not None:
            heads.append(
                Printed(
                    x=x,
                    y=y,
                    staff=staff_index,
                    step=staff.step_of(y),
                    kind="head",
                    grace=shape == "grace",
                    char=char,
                )
            )
        elif char in FLAG_CODES and 2.0 * staff.spacing <= top - bottom <= 3.6 * staff.spacing:
            flags.append((staff_index, x, y, FLAG_CODES[char]))
        else:
            value = rest_value(char, right - left, top - bottom, staff.spacing, staff.step_of(y))
            if value is not None:
                rests.append(
                    Printed(
                        x=x,
                        y=y,
                        staff=staff_index,
                        step=staff.step_of(y),
                        kind="rest",
                        grace=False,
                        char=char,
                        value=value,
                    )
                )
    heads = drop_articulations(heads, staves)
    rests.sort(key=lambda r: (r.staff, r.x))
    paths = [
        tuple(float(v) for v in obj.get_bounds())
        for obj in page.get_objects(max_depth=4)
        if obj.type == raw.FPDF_PAGEOBJ_PATH
    ]

    heads.sort(key=lambda h: (h.staff, round(h.x, 1), -h.y))
    # Each accidental belongs to the nearest notehead to its right on the same
    # step, within two spaces; the rest (before the first note of a staff,
    # after the clef) are the key signature.
    keys: list[dict[str, int]] = [{} for _ in staves]
    clefs = ["treble"] * len(staves)
    for staff_index, _x, clef in sorted(clef_marks):
        clefs[staff_index] = clef
    first_x = {}
    for head in heads:
        first_x.setdefault(head.staff, head.x)
    signature: list[list[tuple[float, str, int]]] = [[] for _ in staves]
    for x, y, staff_index, alter in sorted(accidentals):
        staff = staves[staff_index]
        step = staff.step_of(y)
        owner = None
        for head in heads:
            if (
                head.staff == staff_index
                and head.step == step
                and 0 < head.x - x <= 2.5 * staff.spacing
                and (owner is None or head.x < owner.x)
            ):
                owner = head
        if x < first_x.get(staff_index, float("inf")) - 0.5 * staff.spacing:
            letter_index, _octave = CLEF_BOTTOM[clefs[staff_index]]
            signature[staff_index].append((x, STEPS[(letter_index + step) % 7], alter))
        elif owner is not None:
            owner.alter = alter
    for staff_index, marks in enumerate(signature):
        keys[staff_index], leftover = key_signature(marks)
        # What a valid signature cannot hold is a courtesy accidental on
        # the staff's first note.
        for _x, letter, alter in leftover:
            for head in heads:
                if head.staff == staff_index and head.x == first_x.get(staff_index):
                    letter_index, _octave = CLEF_BOTTOM[clefs[staff_index]]
                    if STEPS[(letter_index + head.step) % 7] == letter:
                        head.alter = alter
    # A staff without a key signature of its own carries the previous one.
    for k in range(1, len(staves)):
        if not keys[k] and not signature[k]:
            keys[k] = dict(keys[k - 1])
    return PagePrint(
        staves,
        heads,
        clefs,
        keys,
        barlines,
        tuplets=tuplet_marks(glyphs, staves, heads),
        times=time_signatures(glyphs, staves, _object_boxes(page)),
        tempo=tempo_mark(glyphs),
        rests=rests,
        beams=find_beams(page, staves),
        flags=flags,
        multirests=multi_rests(paths, glyphs, staves, barlines, heads),
    )


def _glyphs(textpage, raw) -> list[Glyph]:
    """Every non-blank character of the page's text layer, with its font and box."""
    out: list[Glyph] = []
    for i in range(textpage.count_chars()):
        char = textpage.get_text_range(i, 1)
        if not char.strip():
            continue
        name_buffer = (raw.c_char * 128)()
        raw.FPDFText_GetFontInfo(textpage, i, name_buffer, 128, raw.c_int())
        font = name_buffer.value.decode("latin-1", "replace").split("+", 1)[-1]
        left, bottom, right, top = textpage.get_charbox(i)
        out.append(Glyph(char, font, left, bottom, right, top))
    return out


def _object_boxes(page) -> list[tuple[float, float, float, float]]:
    """The boxes of the page's text objects, which the text layer may not all list."""
    boxes = []
    for obj in page.get_objects(max_depth=4):
        if obj.type != 1:  # FPDF_PAGEOBJ_TEXT
            continue
        bounds = obj.get_bounds() if hasattr(obj, "get_bounds") else obj.get_pos()
        boxes.append(tuple(float(v) for v in bounds))
    return boxes


def _staff_of(staves: list[Staff], y: float, ledger_spaces: float) -> int | None:
    holders = [k for k, staff in enumerate(staves) if staff.holds(y, ledger_spaces)]
    if not holders:
        return None
    return min(holders, key=lambda k: abs((staves[k].bottom + staves[k].top) / 2 - y))


def tuplet_marks(
    glyphs: list[Glyph], staves: list[Staff], heads: list[Printed]
) -> list[TupletMark]:
    """The tuplet numbers on the page: lone digits in a staff's band, among its notes.

    Sibelius sets them in the family's Text face, Finale in Times Bold
    Italic; either way a digit about a space and a half tall, on its own
    (a chord symbol's "7" or "13" and a bar number's digits have a
    neighbour on their baseline), below the staff or above it within the
    reach of a beam, and between the staff's first and last notehead (bar
    numbers sit at the left edge, before the first note).
    """
    first_x: dict[int, float] = {}
    last_x: dict[int, float] = {}
    for head in heads:
        first_x[head.staff] = min(first_x.get(head.staff, float("inf")), head.x)
        last_x[head.staff] = max(last_x.get(head.staff, float("-inf")), head.x)
    marks: list[TupletMark] = []
    for glyph in glyphs:
        if not glyph.char.isdigit() or int(glyph.char) not in TUPLET_NORMAL:
            continue
        if "chord" in glyph.font.lower():
            continue
        staff_index = _staff_of(staves, glyph.y, 9.0)
        if staff_index is None or staff_index not in first_x:
            continue
        staff = staves[staff_index]
        if not 0.9 * staff.spacing <= glyph.height <= 2.2 * staff.spacing:
            continue
        if not -10 <= staff.step_of(glyph.y) <= 18:
            continue
        if (
            not first_x[staff_index] - staff.spacing
            <= glyph.x
            <= last_x[staff_index] + staff.spacing
        ):
            continue
        reach = 0.8 * glyph.width
        lone = not any(
            other is not glyph
            and abs(other.y - glyph.y) < glyph.height
            and other.left < glyph.right + reach
            and other.right > glyph.left - reach
            for other in glyphs
        )
        if lone:
            marks.append(TupletMark(glyph.x, glyph.y, staff_index, int(glyph.char), staff.spacing))
    return marks


def time_signatures(
    glyphs: list[Glyph],
    staves: list[Staff],
    object_boxes: list[tuple[float, float, float, float]] = (),
) -> list[TimeMark]:
    """The time signatures printed on the page, in reading order.

    Two music-font digits about two spaces tall, one on the upper half
    of the staff and one on the lower at the same x, or a common/cut time
    glyph on the middle line. pdfium's text layer drops the second of two
    identical characters whose boxes overlap, so a 4/4 or 2/2 arrives as
    a lone numerator; the page's text OBJECTS still hold both, and a text
    object directly under a lone numerator makes it N/N.
    """
    marks: list[TimeMark] = []
    for staff_index, staff in enumerate(staves):
        digits: list[Glyph] = []
        symbols: list[Glyph] = []
        for glyph in glyphs:
            lowered = glyph.font.lower()
            if not is_music_font(glyph.font) or "chord" in lowered or "text" in lowered:
                continue
            if not staff.holds(glyph.y, 1.0):
                continue
            step = staff.step_of(glyph.y)
            if glyph.char.isdigit() and 1.6 * staff.spacing <= glyph.height <= 2.6 * staff.spacing:
                digits.append(glyph)
            elif (
                glyph.char in "cC"
                and 1.5 * staff.spacing <= glyph.height <= 3.0 * staff.spacing
                and abs(step - 4) <= 1
            ):
                symbols.append(glyph)
        for symbol in sorted(symbols, key=lambda g: g.x):
            if symbol.char == "c":
                marks.append(TimeMark(staff_index, symbol.x, 4, 4, "common"))
            else:
                marks.append(TimeMark(staff_index, symbol.x, 2, 2, "cut"))
        # Digits within a space of each other horizontally form one signature.
        digits.sort(key=lambda g: g.x)
        groups: list[list[Glyph]] = []
        for glyph in digits:
            if groups and glyph.x - groups[-1][-1].x < 1.5 * staff.spacing:
                groups[-1].append(glyph)
            else:
                groups.append([glyph])
        for group in groups:
            upper = sorted((g for g in group if staff.step_of(g.y) >= 5), key=lambda g: g.x)
            lower = sorted((g for g in group if staff.step_of(g.y) <= 3), key=lambda g: g.x)
            if not upper:
                continue
            beats = int("".join(g.char for g in upper))
            if lower:
                beat_type = int("".join(g.char for g in lower))
            else:
                top_glyph = upper[0]
                under = any(
                    abs(left - top_glyph.left) < 1.5
                    and abs(right - top_glyph.right) < 1.5
                    and top_glyph.bottom - 2.0 <= top <= top_glyph.bottom + 2.0
                    for left, bottom, right, top in object_boxes
                )
                if not under:
                    continue
                beat_type = beats
            if beats and beat_type in (1, 2, 4, 8, 16):
                marks.append(TimeMark(staff_index, group[0].x, beats, beat_type))
    marks.sort(key=lambda m: (m.staff, m.x))
    return marks


def tempo_mark(glyphs: list[Glyph]) -> Tempo | None:
    """The metronome mark on the page, with the words before it, if printed.

    A beat glyph of a notation family's text face ("q" in Opus Text is a
    quarter note), an "=", and a number to its right on the same line;
    an augmentation dot glyph after the beat makes it dotted. The words
    are the text-font glyphs on that baseline to the left, "Medium Swing".
    """
    for equals in glyphs:
        if equals.char != "=":
            continue
        line_height = max(equals.height, 4.0)
        beat = None
        for glyph in glyphs:
            if (
                glyph.char in BEAT_GLYPHS
                and music_family(glyph.font)
                and not is_music_font(glyph.font)
                and glyph.right <= equals.left + 1.0
                and equals.left - glyph.right < 4 * glyph.height
                and abs(glyph.y - equals.y) < glyph.height
            ):
                beat = glyph
        if beat is None:
            continue
        dots = sum(
            1
            for glyph in glyphs
            if glyph.char == "."
            and beat.right - 1.0 <= glyph.left <= equals.left
            and abs(glyph.y - equals.y) < beat.height
        )
        number = ""
        for glyph in sorted(glyphs, key=lambda g: g.left):
            if glyph.left < equals.right - 1.0 or glyph.left - equals.right > 8 * line_height:
                continue
            if abs(glyph.y - equals.y) > 1.5 * max(glyph.height, line_height):
                continue
            if glyph.char.isdigit():
                number += glyph.char
            elif number:
                break
        if not number or not 20 <= int(number) <= 400:
            continue
        words = _words_before(glyphs, beat)
        return Tempo(BEAT_GLYPHS[beat.char], min(dots, 1), int(number), words)
    return None


def _words_before(glyphs: list[Glyph], beat: Glyph) -> str:
    """The text-font glyphs on the beat glyph's baseline to its left, as words."""
    same_line = [
        g
        for g in glyphs
        if g is not beat
        and not is_music_font(g.font)
        and not (music_family(g.font) and "text" in g.font.lower())  # the beat's own face
        and g.right <= beat.left + 1.0
        and abs(g.bottom - beat.bottom) < 0.6 * beat.height
        and g.height >= 0.3 * beat.height
    ]
    same_line.sort(key=lambda g: g.left)
    text = ""
    previous: Glyph | None = None
    for glyph in reversed(same_line):
        gap = previous.left - glyph.right if previous is not None else beat.left - glyph.right
        if gap > 2.5 * glyph.height:
            break
        space = " " if gap > 0.2 * glyph.height and text else ""
        text = glyph.char + space + text
        previous = glyph
    return " ".join(text.split()).strip(" (")


SHARPS = "FCGDAEB"
FLATS = "BEADGCF"


def key_signature(marks: list[tuple[float, str, int]]) -> tuple[dict[str, int], list]:
    """The longest valid signature the marks (in x order) begin with, and the marks left over.

    A signature is a prefix of the circle of fifths in one direction --
    F C G D A E B in sharps, B E A D G C F in flats -- and nothing else.
    """
    marks = sorted(marks)
    if not marks:
        return {}, []
    order = SHARPS if marks[0][2] == 1 else FLATS
    alter = marks[0][2]
    if alter == 0:
        return {}, marks
    taken = 0
    for (_x, letter, mark_alter), expected in zip(marks, order, strict=False):
        if mark_alter != alter or letter != expected:
            break
        taken += 1
    return {letter: alter for _x, letter, _a in marks[:taken]}, marks[taken:]


# ---------------------------------------------------------------- pitches


BLACK_HEAD = "\u0153"


def drop_articulations(heads: list[Printed], staves: list[Staff]) -> list[Printed]:
    """Drop the head-shaped glyphs that are accents, marcatos and tenutos, not notes.

    An accent is a notehead's size and shape and sits straight above or
    below its note, one to four spaces away; a second note of a chord sits
    there too, but these are single-line pages and the black head itself
    (U+0153 in every Sibelius and Finale family) is never dropped.
    """
    black = [h for h in heads if h.char == BLACK_HEAD]
    kept = []
    for head in heads:
        if head.char != BLACK_HEAD:
            spacing = staves[head.staff].spacing
            stacked = any(
                b.staff == head.staff
                and abs(b.x - head.x) < 0.5 * spacing
                and 1.2 * spacing <= abs(b.y - head.y) <= 4.0 * spacing
                for b in black
            )
            if stacked:
                continue
        kept.append(head)
    return kept


def printed_noteheads(pdf: Path, index: int) -> int:
    """How many noteheads the page prints, by glyph shape; 0 for a scan or a page with no staves."""
    page = read_page(pdf, index)
    return len(page.notes) if page else 0


def resolve_pitches(pages: list[PagePrint]) -> list[Printed]:
    """The pages' noteheads in reading order with letter, octave and sounding alter filled in."""
    out: list[Printed] = []
    for page_index, page in enumerate(pages):
        for staff_index, staff in enumerate(page.staves):
            letter_index, base_octave = CLEF_BOTTOM[page.clefs[staff_index]]
            key = page.keys[staff_index]
            bars = page.barlines[staff_index]
            for head in [h for h in page.notes if h.staff == staff_index]:
                diatonic = letter_index + head.step
                head.page = page_index
                head.bar = bar_index(bars, head.x, staff.spacing)
                head.letter = STEPS[diatonic % 7]
                head.octave = base_octave + diatonic // 7
                head.key_alter = key.get(head.letter, 0)
                out.append(head)
    sounding_alters(out, [(h.page, h.staff, h.bar) for h in out])
    return out


def sounding_alters(heads: list[Printed], bar_keys: list[tuple]) -> int:
    """Set each head's sounding alter from the accidentals before it in its bar; how many changed.

    An explicit accidental holds for its letter and octave until the bar
    key changes; the key signature's alter holds elsewhere. The keys are
    the caller's notion of a bar: the page's bar lines alone, or those and
    the reading's measures together (`correct_pitches`).
    """
    state: dict[tuple[str, int], int] = {}
    previous: tuple | None = None
    changed = 0
    for head, bar_key in zip(heads, bar_keys, strict=True):
        if bar_key != previous:
            state = {}
            previous = bar_key
        if head.alter is not None:
            state[(head.letter, head.octave)] = head.alter
        alter = state.get((head.letter, head.octave), head.key_alter)
        if alter != head.sounding_alter:
            changed += 1
        head.sounding_alter = alter
    return changed


@dataclass
class Correction:
    printed: int = 0
    read: int = 0
    aligned: int = 0
    changed: int = 0  # pitches corrected
    unread: int = 0  # printed heads the reading has no note for
    unprinted: int = 0  # read notes the page has no head for
    alters_from_engine_bars: int = 0  # sounding alters the reading's bar ends decided
    changes: list[str] = field(default_factory=list)


def _align(read_seq: list[int], print_seq: list[int]) -> tuple[list[tuple[int, int]], int, int]:
    """Index pairs the two sequences agree on, plus the counts left over on each side."""
    matcher = difflib.SequenceMatcher(a=read_seq, b=print_seq, autojunk=False)
    pairs: list[tuple[int, int]] = []
    unprinted = unread = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend(zip(range(i1, i2), range(j1, j2), strict=True))
        elif tag == "replace":
            # A short stretch of misread positions pairs up note for note; a
            # long one is as likely a dropped note beside an invented one,
            # and is reported, not corrected.
            span = min(i2 - i1, j2 - j1)
            if (i2 - i1) == (j2 - j1) and span <= 4:
                pairs.extend(zip(range(i1, i1 + span), range(j1, j1 + span), strict=True))
            else:
                unprinted += i2 - i1
                unread += j2 - j1
        elif tag == "delete":
            unprinted += i2 - i1
        elif tag == "insert":
            unread += j2 - j1
    return pairs, unprinted, unread


def correct_pitches(part: ET.Element, printed: list[Printed]) -> Correction:
    """Set every aligned note's pitch to the printed one.

    The reading's notes (rests aside) and the printed heads are aligned on
    their diatonic positions, so an engine's accidental slips still align
    and get corrected, while a dropped or invented note shows up as an
    unmatched stretch and is counted, not guessed at. A tied-into note
    keeps the pitch of the note it is tied from.
    """
    notes = [n for n in part.iter("note") if n.find("rest") is None and n.find("pitch") is not None]
    result = Correction(printed=len(printed), read=len(notes))
    if not printed or not notes:
        return result
    aligned = align_notes(notes, printed)
    if aligned is None:
        # Two sequences that will not line up are not one line (a piano
        # score, a page the reader misread): correcting would guess.
        result.unread, result.unprinted = len(printed), len(notes)
        return result
    pairs, unprinted, unread = aligned
    result.unprinted, result.unread = unprinted, unread
    result.aligned = len(pairs)
    # A bar line the page's paths did not give (an older Finale export
    # hides some) is taken from the reading: an accidental stops holding
    # where EITHER the page or the reading ends the bar.
    measure_index: dict[int, int] = {}
    for number, measure in enumerate(part.findall("measure")):
        for note in measure.findall("note"):
            measure_index[id(note)] = number
    engine_bar = {j: measure_index.get(id(notes[i]), -1) for i, j in pairs}
    bar_keys = []
    last = -1
    for j, head in enumerate(printed):
        last = engine_bar.get(j, last)
        bar_keys.append((head.page, head.staff, head.bar, last))
    result.alters_from_engine_bars = sounding_alters(printed, bar_keys)
    tied_from: dict[int, tuple[str, int, int]] = {}
    for i, j in pairs:
        note, head = notes[i], printed[j]
        pitch = note.find("pitch")
        old = (
            pitch.findtext("step", "C"),
            int(pitch.findtext("octave", "4")),
            int(float(pitch.findtext("alter", "0") or 0)),
        )
        if note.find('tie[@type="stop"]') is not None and i - 1 in tied_from:
            new = tied_from[i - 1]
        else:
            new = (head.letter, head.octave, head.sounding_alter)
        if note.find('tie[@type="start"]') is not None:
            tied_from[i] = new
        if old != new:
            pitch.find("step").text = new[0]
            pitch.find("octave").text = str(new[1])
            alter = pitch.find("alter")
            if new[2] == 0:
                if alter is not None:
                    pitch.remove(alter)
            else:
                if alter is None:
                    alter = ET.Element("alter")
                    pitch.insert(1, alter)
                alter.text = str(new[2])
            shown = note.find("accidental")
            if shown is not None:
                note.remove(shown)
            result.changed += 1
            if len(result.changes) < 200:
                result.changes.append(
                    f"{old[0]}{old[2]:+d}/{old[1]} -> {new[0]}{new[2]:+d}/{new[1]}"
                )
    return result


def align_notes(
    notes: list[ET.Element], printed: list[Printed]
) -> tuple[list[tuple[int, int]], int, int] | None:
    """Pair the reading's pitched notes with the printed heads by diatonic position.

    Returns (pairs of note index and head index, read notes unprinted,
    printed heads unread), or None when the two will not line up: under
    70% paired on full position, then on the letter alone (an engine that
    read a passage an octave off still aligns on letters).
    """

    def diatonic_of(note: ET.Element) -> int:
        pitch = note.find("pitch")
        return int(pitch.findtext("octave", "4")) * 7 + STEPS.index(pitch.findtext("step", "C"))

    read_seq = [diatonic_of(n) for n in notes]
    print_seq = [h.octave * 7 + STEPS.index(h.letter) for h in printed]
    floor = 0.7 * min(len(read_seq), len(print_seq))
    pairs, unprinted, unread = _align(read_seq, print_seq)
    if len(pairs) < floor:
        pairs, unprinted, unread = _align([d % 7 for d in read_seq], [d % 7 for d in print_seq])
    if len(pairs) < floor:
        return None
    return pairs, unprinted, unread


# ---------------------------------------------------------------- a transcription's pages


@dataclass
class PrintedPages:
    """Everything the text layer says about one transcription's pages, in reading order."""

    heads: list[Printed]
    marks: list[TupletMark]
    barlines: dict[tuple[int, int], list[float]]  # (page, staff) -> x of each bar line
    time: TimeMark | None  # the first time signature printed
    tempo: Tempo | None
    rests: list[Printed] = field(default_factory=list)  # reading order, page set
    beams: dict[tuple[int, int], list[tuple[float, float, float, float]]] = field(
        default_factory=dict
    )  # (page, staff) -> beam-like paths (left, bottom, right, top)
    flags: dict[tuple[int, int], list[tuple[float, float, int]]] = field(default_factory=dict)
    times: list[TimeMark] = field(default_factory=list)  # every signature printed, page set
    multirests: list[MultiRest] = field(default_factory=list)

    @property
    def barline_count(self) -> int:
        """How many bar lines the pages' paths gave; about one per bar when the finder works."""
        return sum(len(xs) for xs in self.barlines.values())


def collect(pages: list[PagePrint]) -> PrintedPages:
    heads = resolve_pitches(pages)
    marks: list[TupletMark] = []
    rests: list[Printed] = []
    barlines: dict[tuple[int, int], list[float]] = {}
    beams: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    flags: dict[tuple[int, int], list[tuple[float, float, int]]] = {}
    times: list[TimeMark] = []
    multirests: list[MultiRest] = []
    for page_index, page in enumerate(pages):
        for mark in page.tuplets:
            mark.page = page_index
            marks.append(mark)
        for rest in page.rests:
            rest.page = page_index
            staff = page.staves[rest.staff]
            rest.bar = bar_index(page.barlines[rest.staff], rest.x, staff.spacing)
            rests.append(rest)
        for time_mark in page.times:
            time_mark.page = page_index
            staff = page.staves[time_mark.staff]
            time_mark.bar = bar_index(page.barlines[time_mark.staff], time_mark.x, staff.spacing)
            times.append(time_mark)
        for multirest in page.multirests:
            multirest.page = page_index
            staff = page.staves[multirest.staff]
            multirest.bar = bar_index(page.barlines[multirest.staff], multirest.x, staff.spacing)
            multirests.append(multirest)
        for staff_index, bars in enumerate(page.barlines):
            barlines[(page_index, staff_index)] = list(bars)
        for staff_index, left, bottom, right, top in page.beams:
            beams.setdefault((page_index, staff_index), []).append((left, bottom, right, top))
        for staff_index, x, y, n in page.flags:
            flags.setdefault((page_index, staff_index), []).append((x, y, n))
    time = next((t for page in pages for t in page.times), None)
    tempo = next((page.tempo for page in pages if page.tempo is not None), None)
    return PrintedPages(heads, marks, barlines, time, tempo, rests, beams, flags, times, multirests)


# ---------------------------------------------------------------- tuplets


@dataclass
class TupletCorrection:
    marks: int = 0  # tuplet numbers printed
    applied: int = 0  # groups the reading had plain and now has as tuplets
    already: int = 0  # groups the reading had as tuplets
    unplaced: int = 0  # numbers no run of that many noteheads sits under (a rest inside)
    unaligned: int = 0  # a head of the group has no read note
    uneven: int = 0  # the read notes differ in value, or a rest or another note sits between
    unprinted: int = 0  # the reading's tuplet groups no printed number claims
    revalued: int = 0  # groups whose value the page's beams set against the reading's
    changes: list[str] = field(default_factory=list)  # what was done and what could not be

    def note(self, text: str) -> None:
        if len(self.changes) < 300:
            self.changes.append(text)


Slot = tuple[float, float, "ET.Element | None", bool, str, str]  # x, y, element, grace, kind, value


def _onsets(slots: list[Slot], spacing: float) -> list[tuple[float, list[tuple]]]:
    """Runs of slots at one x (a chord of heads), left to right; grace heads take no place.

    A slot is (x, y, the read element it paired with or None, grace, "head" or "rest");
    each onset is (x, [(element, kind, y), ...]).
    """
    out: list[tuple[float, list[tuple]]] = []
    for x, y, element, grace, what, value in sorted(slots, key=lambda s: s[0]):
        if grace:
            continue
        chord = what == "head" and out and out[-1][1][-1][1] == "head"
        if chord and x - out[-1][0] < 0.3 * spacing:
            out[-1][1].append((element, what, y, value))
        else:
            out.append((x, [(element, what, y, value)]))
    return out


BEAM_VALUES = {1: "eighth", 2: "16th", 3: "32nd"}


def _beams_over(
    paths: list[tuple[float, float, float, float]],
    head_xs: list[float],
    head_ys: list[float],
    spacing: float,
    mark_x: float,
) -> int:
    """How many beams run over a group of noteheads: paths from its first stem to its last.

    A beam reaches from the first note's stem to the last note's, within a
    space or two, and the tuplet number sits under its span; a tie or slur
    hugs the heads, a tuplet bracket is broken at its number and so never
    spans it, a text line runs far past the group, and the next staff's
    beams lie seven spaces off where a stem reaches three or four.
    Measured on Inkpen2: beams 0.5 of a space thick, 1.5 with their slope.
    """
    if len(head_xs) < 2:
        return 0
    first_x, last_x = min(head_xs), max(head_xs)
    centres: list[float] = []
    for left, bottom, right, top in paths:
        if not left <= mark_x <= right:
            continue
        if not first_x - 2.0 * spacing <= left <= first_x + 1.2 * spacing:
            continue
        if not last_x - 1.2 * spacing <= right <= last_x + 2.0 * spacing:
            continue
        centre = (bottom + top) / 2
        distance = min(abs(centre - y) for y in head_ys)
        # A stem's length away: nearer is a tie, farther the next staff's beams.
        if not 1.8 * spacing <= distance <= 6.5 * spacing:
            continue
        centres.append(centre)
    if not centres:
        return 0
    # The beams of one group are stacked within a space or so of each other.
    nearest = min(centres, key=lambda c: min(abs(c - y) for y in head_ys))
    return sum(1 for c in centres if abs(c - nearest) <= 1.6 * spacing)


def _pair_rests(
    part: ET.Element,
    printed: PrintedPages,
    notes: list[ET.Element],
    note_of_head: dict[int, int],
) -> dict[int, ET.Element]:
    """Each printed rest's read rest, by position: between the same two aligned notes, as many.

    A printed rest lies between two aligned heads; the reading's rests
    between those heads' notes correspond to the page's in order when
    there are as many. More or fewer (a quarter rest read as two eighths)
    pairs none of them.
    """
    all_notes = list(part.iter("note"))
    position = {id(n): k for k, n in enumerate(all_notes)}
    head_keys = [(h.page, h.staff, h.x) for h in printed.heads]
    aligned = [j for j in range(len(printed.heads)) if j in note_of_head]
    aligned_keys = [head_keys[j] for j in aligned]
    groups: dict[tuple[int | None, int | None], list[int]] = {}
    for index, rest in enumerate(printed.rests):
        k = bisect_right(aligned_keys, (rest.page, rest.staff, rest.x))
        before = aligned[k - 1] if k > 0 else None
        after = aligned[k] if k < len(aligned) else None
        groups.setdefault((before, after), []).append(index)
    paired: dict[int, ET.Element] = {}
    for (before, after), indices in groups.items():
        # Before the first aligned head or after the last, the run reaches the line's end.
        low = -1 if before is None else position[id(notes[note_of_head[before]])]
        high = len(all_notes) if after is None else position[id(notes[note_of_head[after]])]
        read_rests = [n for n in all_notes[low + 1 : high] if n.find("rest") is not None]
        if len(read_rests) == len(indices):
            for index, element in zip(indices, read_rests, strict=True):
                paired[index] = element
    return paired


def _scale_divisions(part: ET.Element, factor: int) -> None:
    """Multiply the part's divisions and every duration by `factor`."""
    for measure in part.findall("measure"):
        for element in measure.iter():
            if element.tag in ("divisions", "duration") and element.text:
                element.text = str(int(float(element.text)) * factor)


def _bracket_extent(
    paths: list[tuple[float, float, float, float]], mark: TupletMark
) -> tuple[float, float] | None:
    """Where the tuplet bracket drawn with a number begins and ends, if one is drawn.

    A bracket is a thin path at the number's height, broken at the number
    (Sibelius, Finale) or running under it whole; its ends are the
    group's ends. Only the nearest segment on each side belongs to the
    number: three brackets in a row put the neighbour's segment a few
    spaces off, and the gap for the number is two.
    """
    spacing = mark.spacing
    left_segment = right_segment = None
    for left, bottom, right, top in paths:
        if top - bottom > 1.0 * spacing or abs((bottom + top) / 2 - mark.y) > 1.2 * spacing:
            continue
        if left <= mark.x <= right:
            return (left, right)
        near_left = mark.x - 2.0 * spacing <= right <= mark.x + 0.5 * spacing
        if near_left and (left_segment is None or right > left_segment[1]):
            left_segment = (left, right)
        near_right = mark.x - 0.5 * spacing <= left <= mark.x + 2.0 * spacing
        if near_right and (right_segment is None or left < right_segment[0]):
            right_segment = (left, right)
    if left_segment is None and right_segment is None:
        return None
    return (
        left_segment[0] if left_segment is not None else mark.x,
        right_segment[1] if right_segment is not None else mark.x,
    )


def _page_value(
    x: float,
    y: float,
    what: str,
    rest_value: str,
    element: ET.Element,
    paths: list[tuple[float, float, float, float]],
    flags: list[tuple[float, float, int]],
    mark: TupletMark,
    group: tuple[float, float],
) -> tuple[Fraction | None, bool]:
    """A member's written value as the page shows it, in quarters, and whether the page said so.

    A rest prints its value in its glyph; a note's is its beams (paths
    over its stem, a stem's length away, not the bracket at the number's
    height, and not running more than four spaces past the group's ends
    -- a text line over the bar does), else its flag glyphs, else a
    quarter, or the longer value the reading gives an unbeamed,
    unflagged head.
    """
    from pdf2musicxml.musicxml import NOMINAL_QUARTERS

    spacing = mark.spacing
    if what == "rest":
        if rest_value in NOMINAL_QUARTERS:
            return Fraction(NOMINAL_QUARTERS[rest_value]), True
        return None, False
    centres = []
    for left, bottom, right, top in paths:
        if not left <= x + 0.8 * spacing or not right >= x - 0.8 * spacing:
            continue
        if left < group[0] - 4.0 * spacing or right > group[1] + 4.0 * spacing:
            continue
        centre = (bottom + top) / 2
        if abs(centre - mark.y) <= 1.2 * spacing and top - bottom <= 1.0 * spacing:
            continue  # the bracket
        if 1.8 * spacing <= abs(centre - y) <= 6.5 * spacing:
            centres.append(centre)
    if centres:
        nearest = min(centres, key=lambda c: abs(c - y))
        beams = sum(1 for c in centres if abs(c - nearest) <= 1.6 * spacing)
        return Fraction(NOMINAL_QUARTERS[BEAM_VALUES.get(beams, "32nd")]), True
    flagged = [
        n
        for fx, fy, n in flags
        if abs(fx - x) <= 1.2 * spacing and 1.5 * spacing <= abs(fy - y) <= 5.5 * spacing
    ]
    if flagged:
        return Fraction(NOMINAL_QUARTERS["eighth" if max(flagged) == 1 else "16th"]), True
    kind = element.findtext("type")
    if kind in ("half", "whole", "breve", "long"):
        return Fraction(NOMINAL_QUARTERS[kind]), False
    return Fraction(1), False


def apply_printed_tuplets(part: ET.Element, printed: PrintedPages) -> TupletCorrection:
    """Make the reading's notes under each printed tuplet number a tuplet of that count.

    A "3" claims the three consecutive onsets on its staff it is centred
    on -- noteheads and rests alike, no bar line between them; their read
    notes must be consecutive in one bar, and become one value in a 3:2
    (5:4, 6:4, 7:4), so the bar that held one eighth too many now adds
    up. The value is the one `normal` of which make the group's read
    total (an engine that split a triplet eighth into two sixteenths kept
    the sounding total), else `count` of which make it (plain notes),
    else the majority -- unless the page's beams over the group say
    (one beam is eighths, two sixteenths), which outranks the reading.
    A group the engine already read as a
    tuplet is left alone; the engine's tuplets no number claims are
    counted for the report, not stripped.
    """
    from pdf2musicxml.musicxml import NOMINAL_QUARTERS, _child_index, _notations
    from pdf2musicxml.musicxml import divisions_of as measure_divisions

    result = TupletCorrection(marks=len(printed.marks))
    notes = [n for n in part.iter("note") if n.find("rest") is None and n.find("pitch") is not None]
    if not printed.marks or not notes or not printed.heads:
        return result
    aligned = align_notes(notes, printed.heads)
    if aligned is None:
        result.unplaced = len(printed.marks)
        return result
    note_of_head = {j: i for i, j in aligned[0]}
    rest_element = _pair_rests(part, printed, notes, note_of_head)
    measure_of: dict[int, ET.Element] = {}
    divisions_of: dict[int, int] = {}
    position: dict[int, int] = {}
    current = 1
    for measure in part.findall("measure"):
        current = measure_divisions(measure, current)
        divisions_of[id(measure)] = current
        for note in measure.findall("note"):
            measure_of[id(note)] = measure
            position[id(note)] = len(position)
    by_staff: dict[tuple[int, int], list[Slot]] = {}
    for j, head in enumerate(printed.heads):
        element = notes[note_of_head[j]] if j in note_of_head else None
        by_staff.setdefault((head.page, head.staff), []).append(
            (head.x, head.y, element, head.grace, "head", "")
        )
    for r, rest in enumerate(printed.rests):
        by_staff.setdefault((rest.page, rest.staff), []).append(
            (rest.x, rest.y, rest_element.get(r), False, "rest", rest.value)
        )
    claimed: set[int] = set()
    for mark in printed.marks:
        count = mark.count
        onsets = _onsets(by_staff.get((mark.page, mark.staff), []), mark.spacing)
        bars = printed.barlines.get((mark.page, mark.staff), [])
        paths = printed.beams.get((mark.page, mark.staff), [])
        flags = printed.flags.get((mark.page, mark.staff), [])
        # The bracket's own extent, when one is drawn, says which onsets it
        # holds: a "3" over quarter, quarter, eighth, eighth holds four.
        window = None
        extent = _bracket_extent(paths, mark)
        if extent is not None:
            inside = [
                o
                for o in onsets
                if extent[0] - 0.5 * mark.spacing <= o[0] <= extent[1] + 0.5 * mark.spacing
            ]
            if 2 <= len(inside) <= 2 * count and not any(
                inside[0][0] < bar < inside[-1][0] for bar in bars
            ):
                window = inside
        best: tuple[float, list] | None = None
        for start in range(len(onsets) - count + 1):
            run = onsets[start : start + count]
            first_x, last_x = run[0][0], run[-1][0]
            gap = (last_x - first_x) / (count - 1)
            if gap <= 0:
                continue
            if not first_x - 0.5 * gap <= mark.x <= last_x + 0.5 * gap:
                continue
            if any(first_x < bar < last_x for bar in bars):
                continue
            distance = abs(mark.x - (first_x + last_x) / 2)
            if best is None or distance < best[0]:
                best = (distance, run)
        where = f"page {mark.page + 1} staff {mark.staff + 1} x {mark.x:.0f}"
        if window is None and best is None:
            result.unplaced += 1
            result.note(f"{where}: {count} printed, no run of {count} notes or rests under it")
            continue
        if window is None:
            window = best[1]
        slots = [(x, slot) for x, group in window for slot in group]
        if any(element is None for _x, (element, _what, _y, _v) in slots):
            result.unaligned += 1
            missing = next(what for _x, (element, what, _y, _v) in slots if element is None)
            result.note(f"{where}: {count} printed, a {missing} of the group was not read")
            continue
        members = sorted(
            (element for _x, (element, _w, _y, _v) in slots), key=lambda e: position[id(e)]
        )
        measure = measure_of[id(members[0])]
        where = f"bar {measure.get('number')}"
        if any(m.find("grace") is not None or m.find("duration") is None for m in members):
            result.uneven += 1
            result.note(f"{where}: {count} printed, a grace note among the read notes")
            continue
        if measure.find("backup") is not None or measure.find("forward") is not None:
            # Several voices: shortening one voice's notes sends a later
            # <backup> past the start of the bar, which MuseScore refuses.
            result.uneven += 1
            result.note(f"{where}: {count} printed, the bar has several voices")
            continue
        if any(measure_of[id(m)] is not measure for m in members):
            result.uneven += 1
            result.note(f"{where}: {count} printed, the read notes straddle a bar line")
            continue
        kids = measure.findall("note")
        between = kids[kids.index(members[0]) : kids.index(members[-1]) + 1]
        member_ids = {id(m) for m in members}
        if any(id(k) not in member_ids for k in between):
            result.uneven += 1
            result.note(f"{where}: {count} printed, another note or rest read between them")
            continue
        if any(m.find("time-modification") is not None for m in members):
            result.already += 1
            claimed.update(member_ids)
            continue
        normal = TUPLET_NORMAL[count]
        divisions = divisions_of[id(measure)]
        heads_only = [m for m in members if m.find("chord") is None]
        # Each member's written value as the page shows it; when they sum
        # to `count` of one unit the group is that tuplet, values and all.
        page_values: list[Fraction | None] = []
        evidence = False
        for x, (element, what, y, value) in slots:
            if element.find("chord") is None:
                page_value, said = _page_value(
                    x, y, what, value, element, paths, flags, mark, (window[0][0], window[-1][0])
                )
                page_values.append(page_value)
                evidence = evidence or said
        unit = sum(v for v in page_values if v is not None) / count if page_values else None
        unit_name = next(
            (k for k, q in NOMINAL_QUARTERS.items() if unit is not None and Fraction(q) == unit),
            None,
        )
        names = {Fraction(q): k for k, q in NOMINAL_QUARTERS.items()}
        if (
            evidence
            and unit_name is not None
            and None not in page_values
            and all(v in names for v in page_values)
            and len(page_values) == len(heads_only)
        ):
            per_unit = Fraction(divisions) * normal / count
            factor = math.lcm(*(int((v * per_unit).denominator) for v in page_values))
            if factor != 1:
                _scale_divisions(part, factor)
                for key in divisions_of:
                    divisions_of[key] *= factor
                divisions *= factor
                per_unit *= factor
            ordered = sorted(slots, key=lambda s: position[id(s[1][0])])
            value_of = {
                id(element): v
                for (_x, (element, _w, _y, _v)), v in zip(ordered, page_values, strict=False)
            }
            old_kinds = [m.findtext("type") or "?" for m in heads_only]
            for member in members:
                value = value_of.get(id(member), page_values[0])
                member.find("duration").text = str(int(value * per_unit))
                kind_element = member.find("type")
                if kind_element is None:
                    kind_element = ET.Element("type")
                    member.insert(_child_index(member, "type"), kind_element)
                kind_element.text = names[value]
                for dot in member.findall("dot"):
                    member.remove(dot)
                modification = ET.Element("time-modification")
                ET.SubElement(modification, "actual-notes").text = str(count)
                ET.SubElement(modification, "normal-notes").text = str(normal)
                ET.SubElement(modification, "normal-type").text = unit_name
                member.insert(_child_index(member, "time-modification"), modification)
            _notations(members[0]).append(ET.Element("tuplet", {"type": "start"}))
            _notations(members[-1]).append(ET.Element("tuplet", {"type": "stop"}))
            claimed.update(member_ids)
            result.applied += 1
            new_kinds = [names[v] for v in page_values]
            if new_kinds != old_kinds:
                result.revalued += 1
            rests_in = sum(1 for m in members if m.find("rest") is not None)
            result.note(
                f"{where}: {count}:{normal} of {unit_name}s over {', '.join(new_kinds)}"
                + (f" ({rests_in} rests)" if rests_in else "")
                + (f" (the reading had {', '.join(old_kinds)})" if new_kinds != old_kinds else "")
            )
            continue
        held = sum(int(m.findtext("duration") or 0) for m in heads_only)
        total = Fraction(held, divisions)
        kinds = [m.findtext("type") or "?" for m in heads_only]
        if len(heads_only) != count:
            # A bracket holding more or fewer than its number, with no page
            # value for its members: only `count` equal notes make a tuplet.
            result.uneven += 1
            result.note(f"{where}: {count} printed over {len(heads_only)} onsets, values unknown")
            continue
        kind = None
        for divisor in (normal, count):
            nominal = total / divisor
            kind = next((k for k, q in NOMINAL_QUARTERS.items() if Fraction(q) == nominal), None)
            if kind is not None:
                break
        if kind is None:
            commonest, votes = Counter(kinds).most_common(1)[0]
            if votes * 2 > len(kinds) and commonest in NOMINAL_QUARTERS:
                kind = commonest
        if kind is None:
            result.uneven += 1
            result.note(f"{where}: {count} printed over {', '.join(kinds)}, no one value fits")
            continue
        # The page's beams say the value outright: one beam over the
        # group's heads is eighths, two sixteenths (an engine that read a
        # beamed triplet of eighths as sixteenths left the bar short).
        chosen = kind
        beams = _beams_over(
            paths,
            [x for x, group in window if any(what == "head" for _e, what, _y, _v in group)],
            [y for _x, group in window for _e, what, y, _v in group if what == "head"],
            mark.spacing,
            mark.x,
        )
        if beams in BEAM_VALUES:
            chosen = BEAM_VALUES[beams]
        units = Fraction(NOMINAL_QUARTERS[chosen]) * divisions * normal / count
        if units.denominator != 1:
            # A quintuplet of sixteenths under 12 divisions: 3 x 4/5. Finer
            # divisions for the whole part, and every duration with them.
            factor = units.denominator
            _scale_divisions(part, factor)
            for key in divisions_of:
                divisions_of[key] *= factor
            units *= factor
        equalised = any(k != kind for k in kinds) or any(m.find("dot") is not None for m in members)
        for member in members:
            member.find("duration").text = str(int(units))
            kind_element = member.find("type")
            if kind_element is None:
                kind_element = ET.Element("type")
                member.insert(_child_index(member, "type"), kind_element)
            kind_element.text = chosen
            for dot in member.findall("dot"):
                member.remove(dot)
            modification = ET.Element("time-modification")
            ET.SubElement(modification, "actual-notes").text = str(count)
            ET.SubElement(modification, "normal-notes").text = str(normal)
            member.insert(_child_index(member, "time-modification"), modification)
        _notations(members[0]).append(ET.Element("tuplet", {"type": "start"}))
        _notations(members[-1]).append(ET.Element("tuplet", {"type": "stop"}))
        claimed.update(member_ids)
        result.applied += 1
        if chosen != kind:
            result.revalued += 1
        rests_in = sum(1 for m in members if m.find("rest") is not None)
        result.note(
            f"{where}: {count} {chosen}s made a {count}:{normal} from the page"
            + (f" ({rests_in} rests)" if rests_in else "")
            + (" (values equalised)" if equalised else "")
            + (f" (the reading had {kind}s; the beams say {chosen}s)" if chosen != kind else "")
        )
    for note in notes:
        if note.find('notations/tuplet[@type="start"]') is not None and id(note) not in claimed:
            result.unprinted += 1
    return result


# ---------------------------------------------------------------- bars


@dataclass
class BarFix:
    merged: int = 0  # read measures joined because the page has one bar there
    split: int = 0  # read measures divided because the page has two bars there
    changes: list[str] = field(default_factory=list)


def align_bars(part: ET.Element, printed: PrintedPages) -> BarFix:
    """Make the reading's measures the page's bars where the page's bar lines say otherwise.

    Every aligned note knows its printed bar (page, staff, bar lines
    passed). Two consecutive read measures whose notes all sit in one
    printed bar, and whose lengths together make under a bar and a half,
    are joined (an
    engine that took a double bar line for two bars and a repeat, Whisper
    Not bar 9); a read measure whose notes sit in two consecutive printed
    bars, and which is at least a bar and a half long, is divided where
    the second bar's first note begins. Bars of several voices, measures
    with no aligned note, and readings the length test does not back are
    left as read. A bar line or repeat mark inside a joined bar was the
    engine's, never the page's, and goes.
    """
    from pdf2musicxml.musicxml import _measure_length
    from pdf2musicxml.musicxml import bars as measure_bars
    from pdf2musicxml.musicxml import divisions_of as measure_divisions

    result = BarFix()
    notes = [n for n in part.iter("note") if n.find("rest") is None and n.find("pitch") is not None]
    if not notes or not printed.heads:
        return result
    aligned = align_notes(notes, printed.heads)
    if aligned is None:
        return result
    bar_ids: dict[tuple[int, int, int], int] = {}
    for head in printed.heads:
        bar_ids.setdefault((head.page, head.staff, head.bar), len(bar_ids))
    printed_bar: dict[int, int] = {}
    for i, j in aligned[0]:
        head = printed.heads[j]
        printed_bar[id(notes[i])] = bar_ids[(head.page, head.staff, head.bar)]

    def bars_of(measure: ET.Element) -> list[int]:
        """The printed bars the measure's aligned notes sit in, in order of appearance."""
        seen: list[int] = []
        for note in measure.findall("note"):
            bar = printed_bar.get(id(note))
            if bar is not None and (not seen or seen[-1] != bar):
                seen.append(bar)
        return seen

    def one_voice(measure: ET.Element) -> bool:
        return measure.find("backup") is None and measure.find("forward") is None

    def lengths() -> dict[int, tuple[Fraction, Fraction | None]]:
        out = {}
        current = 1
        for measure, bar in zip(part.findall("measure"), measure_bars(part), strict=True):
            current = measure_divisions(measure, current)
            out[id(measure)] = (_measure_length(measure, current), bar.expected)
        return out

    # Join: two read measures on one printed bar, together one bar long.
    measures = part.findall("measure")
    known = lengths()
    k = 0
    while k + 1 < len(measures):
        first, second = measures[k], measures[k + 1]
        a, b = bars_of(first), bars_of(second)
        together = known[id(first)][0] + known[id(second)][0]
        expected = known[id(first)][1]
        # Two real bars behind a bar line the finder missed would make two
        # bars' worth; an engine's split bar, even read long, does not.
        fits = expected is None or together <= Fraction(3, 2) * expected
        if a and b and len(a) == 1 and a == b and fits and one_voice(first) and one_voice(second):
            for barline in first.findall("barline"):
                first.remove(barline)
            for child in list(second):
                if child.tag not in ("attributes", "barline", "print"):
                    first.append(child)
            part.remove(second)
            result.merged += 1
            numbers = f"{first.get('number')} and {second.get('number')}"
            result.changes.append(f"bars {numbers} read as two: one on the page")
            measures = part.findall("measure")
            known = lengths()
            continue
        k += 1
    # Divide: one read measure on two printed bars, a bar and a half or longer.
    for measure in part.findall("measure"):
        sequence = bars_of(measure)
        length, expected = known[id(measure)]
        if len(sequence) != 2 or sequence[1] != sequence[0] + 1 or not one_voice(measure):
            continue
        if expected is not None and length < Fraction(3, 2) * expected:
            continue
        children = list(measure)
        cut = next(
            (
                index
                for index, child in enumerate(children)
                if child.tag == "note" and printed_bar.get(id(child)) == sequence[1]
            ),
            None,
        )
        if cut is None:
            continue
        in_order = all(
            printed_bar.get(id(child)) in (None, sequence[0] if index < cut else sequence[1])
            for index, child in enumerate(children)
            if child.tag == "note"
        )
        if not in_order:
            continue
        new = ET.Element("measure", {"number": f"{measure.get('number', '')}a"})
        for child in children[cut:]:
            measure.remove(child)
            new.append(child)
        part.insert(list(part).index(measure) + 1, new)
        result.split += 1
        result.changes.append(f"bar {measure.get('number')} read as one: two on the page")
    if result.merged or result.split:
        measures = part.findall("measure")
        try:
            start = int(measures[0].get("number", "1"))
        except ValueError:
            start = 1
        for offset, measure in enumerate(measures):
            measure.set("number", str(start + offset))
    return result


def printed_bar_per_measure(
    part: ET.Element, printed: PrintedPages
) -> list[tuple[int, int, int] | None]:
    """The printed bar (page, staff, bar) each read measure's aligned notes sit in.

    None where a measure holds notes of two printed bars, or none.
    """
    keys = _printed_bar_of_notes(part, printed)
    if keys is None:
        return [None] * len(part.findall("measure"))
    return [ks[0] if len(ks) == 1 else None for ks in _measure_keys(part, keys)]


def printed_count_per_measure(part: ET.Element, printed: PrintedPages) -> list[int | None]:
    """How many noteheads the page prints in each of the reading's measures, by the notes' bars.

    Each aligned note knows its printed bar; a measure whose aligned notes
    all sit in one printed bar gets that bar's count, any other None. By
    the notes, not the index, so a bar the reading joined or split does
    not shift every count after it.
    """
    measures = part.findall("measure")
    notes = [n for n in part.iter("note") if n.find("rest") is None and n.find("pitch") is not None]
    if not notes or not printed.heads:
        return [None] * len(measures)
    aligned = align_notes(notes, printed.heads)
    if aligned is None:
        return [None] * len(measures)
    counts: dict[tuple[int, int, int], int] = {}
    for head in printed.heads:
        key = (head.page, head.staff, head.bar)
        counts[key] = counts.get(key, 0) + 1
    bar_of_note: dict[int, tuple[int, int, int]] = {}
    for i, j in aligned[0]:
        head = printed.heads[j]
        bar_of_note[id(notes[i])] = (head.page, head.staff, head.bar)
    out: list[int | None] = []
    for measure in measures:
        bars = {bar_of_note[id(n)] for n in measure.findall("note") if id(n) in bar_of_note}
        out.append(counts[bars.pop()] if len(bars) == 1 else None)
    return out


# ---------------------------------------------------------------- time changes and rest bars


def _printed_bar_of_notes(
    part: ET.Element, printed: PrintedPages
) -> dict[int, tuple[int, int, int]] | None:
    """Each read note's printed bar (page, staff, bar), by the pitch alignment; None if none."""
    notes = [n for n in part.iter("note") if n.find("rest") is None and n.find("pitch") is not None]
    if not notes or not printed.heads:
        return None
    aligned = align_notes(notes, printed.heads)
    if aligned is None:
        return None
    keys: dict[int, tuple[int, int, int]] = {}
    for i, j in aligned[0]:
        head = printed.heads[j]
        keys[id(notes[i])] = (head.page, head.staff, head.bar)
    return keys


def _measure_keys(
    part: ET.Element, keys: dict[int, tuple[int, int, int]]
) -> list[list[tuple[int, int, int]]]:
    """Per read measure, the printed bars of its aligned notes, sorted."""
    return [
        sorted({keys[id(n)] for n in measure.findall("note") if id(n) in keys})
        for measure in part.findall("measure")
    ]


def _renumber(part: ET.Element) -> None:
    measures = part.findall("measure")
    try:
        start = max(1, int(measures[0].get("number", "1")))
    except (ValueError, IndexError):
        start = 1
    for offset, measure in enumerate(measures):
        measure.set("number", str(start + offset))


@dataclass
class TimeChange:
    placed: int = 0  # changes of signature written where the page prints one
    dropped: int = 0  # the reading's own changes no printed signature backs
    changes: list[str] = field(default_factory=list)


def apply_printed_times(part: ET.Element, printed: PrintedPages) -> TimeChange:
    """Carry the page's changes of time signature into the reading.

    Each printed signature knows the bar it begins; the read measure
    whose first aligned note sits in that bar, or the first after it,
    declares it (Artie Shaw's Interlude: 4/4 to 2/4 at letter C and
    back; The First Circle: 12/8 and 8/8 turn about). A signature no
    printed one backs -- an engine's, kept because the bars after it
    happened to fill it -- goes. A signature whose bar the reading
    joined to the one before is left unplaced and named.
    """
    from pdf2musicxml.musicxml import _time_length, set_measure_time

    result = TimeChange()
    if not printed.times:
        return result
    keys = _printed_bar_of_notes(part, printed)
    if keys is None:
        return result
    measures = part.findall("measure")
    per_measure = _measure_keys(part, keys)
    placed: dict[int, TimeMark] = {}
    for mark in sorted(printed.times, key=lambda m: (m.page, m.staff, m.bar, m.x)):
        key = (mark.page, mark.staff, mark.bar)
        target = next(
            (i for i, ks in enumerate(per_measure) if ks and ks[0] >= key),
            None,
        )
        if target is None:
            result.changes.append(f"{mark.text} on page {mark.page + 1}: no read note after it")
            continue
        if target > 0 and per_measure[target - 1] and per_measure[target - 1][-1] >= key:
            result.changes.append(
                f"{mark.text} on page {mark.page + 1}: its bar is joined to the one before"
            )
            continue
        placed[target] = mark
    in_force = _time_length(measures[0].find("attributes"))
    for index, measure in enumerate(measures):
        mark = placed.get(index)
        if mark is not None:
            length = Fraction(mark.beats * 4, mark.beat_type)
            if length != in_force or index == 0:
                if index > 0 or _time_length(measure.find("attributes")) != length:
                    set_measure_time(measure, mark.beats, mark.beat_type)
                    if index > 0:
                        result.placed += 1
                        result.changes.append(f"bar {measure.get('number')}: {mark.text}")
                in_force = length
            continue
        attributes = measure.find("attributes")
        if index > 0 and attributes is not None and attributes.find("time") is not None:
            attributes.remove(attributes.find("time"))
            if len(list(attributes)) == 0:
                measure.remove(attributes)
            result.dropped += 1
    return result


@dataclass
class RestFix:
    bars: int = 0  # bars of rest the page prints between two read notes
    replaced: int = 0  # read measures those bars replaced
    changes: list[str] = field(default_factory=list)


def expand_multirests(part: ET.Element, printed: PrintedPages) -> RestFix:
    """Give the page's multi-bar rests their bars in the reading.

    A stretch of the page between two read notes that holds a multi-bar
    rest is worth the rest's count plus one bar for each printed bar of
    plain rests beside it; whatever the reading wrote for that stretch
    (nothing, one empty bar, three) is replaced by that many
    whole-measure rests in the signature in force. A stretch the
    reading joined into a noted bar, or wrote a pitched note into, is
    left alone and named.
    """
    from pdf2musicxml.musicxml import bars as measure_bars
    from pdf2musicxml.musicxml import divisions_of as measure_divisions
    from pdf2musicxml.musicxml import measure_rest, scale_divisions, set_measure_time

    result = RestFix()
    if not printed.multirests:
        return result
    keys = _printed_bar_of_notes(part, printed)
    if keys is None:
        return result
    measures = part.findall("measure")
    per_measure = _measure_keys(part, keys)
    head_keys = {(h.page, h.staff, h.bar) for h in printed.heads}
    rest_keys = {(r.page, r.staff, r.bar) for r in printed.rests} - head_keys
    stretches: dict[tuple[int, int], list[MultiRest]] = {}
    for multirest in printed.multirests:
        key = (multirest.page, multirest.staff, multirest.bar)
        before = [i for i, ks in enumerate(per_measure) if ks and ks[0] < key]
        after = [i for i, ks in enumerate(per_measure) if ks and ks[-1] > key]
        prev = before[-1] if before else -1
        nxt = after[0] if after else len(measures)
        if prev >= nxt:
            result.changes.append(
                f"{multirest.count} bars of rest on page {multirest.page + 1}: "
                "the reading joined them to a noted bar"
            )
            continue
        stretches.setdefault((prev, nxt), []).append(multirest)
    all_bars = measure_bars(part)
    divisions_at: list[int] = []
    current = 1
    for measure in measures:
        current = measure_divisions(measure, current)
        divisions_at.append(current)
    factor = 1
    for prev, _nxt in stretches:
        index = min(prev + 1, len(measures) - 1)
        lengths = [all_bars[index].expected if all_bars else None]
        lengths += [Fraction(m.beats * 4, m.beat_type) for m in printed.times]
        for expected in lengths:
            if expected is not None:
                factor = math.lcm(factor, (expected * divisions_at[index]).denominator)
    if factor > 1:
        scale_divisions(part, factor)
        divisions_at = [d * factor for d in divisions_at]
    for (prev, nxt), group in sorted(stretches.items(), reverse=True):
        between = measures[prev + 1 : nxt]
        low = per_measure[prev][-1] if prev >= 0 else (-1, -1, -1)
        high = per_measure[nxt][0] if nxt < len(measures) else (10**6, 0, 0)
        # A signature printed at the rest (Artie Shaw's letter C: 2/4 over
        # a 7-bar rest) is the rest bars' own, declared on the first.
        marks = sorted(
            (m for m in printed.times if low < (m.page, m.staff, m.bar) < high),
            key=lambda m: (m.page, m.staff, m.bar, m.x),
        )
        mark = marks[-1] if marks else None
        # The page prints no notehead between the two aligned notes, so a
        # pitched note the reading has there is the engine's (Artie Shaw's
        # Interlude: a quarter read off the H-bar of a 7-bar rest).
        if any(low < k < high for k in head_keys):
            result.changes.append(
                f"{sum(m.count for m in group)} bars of rest on page {group[0].page + 1}: "
                "the page prints notes between the read notes around it"
            )
            continue
        invented = sum(len(m.findall("note/pitch")) for m in between)
        plain = sum(1 for k in rest_keys if low < k < high)
        total = sum(m.count for m in group) + plain
        index = min(prev + 1, len(measures) - 1)
        expected = all_bars[index].expected if all_bars else None
        if mark is not None:
            expected = Fraction(mark.beats * 4, mark.beat_type)
        if expected is None:
            continue
        duration = int(expected * divisions_at[index])
        attributes = next(
            (m.find("attributes") for m in between if m.find("attributes") is not None), None
        )
        new_measures = []
        for _ in range(total):
            new = ET.Element("measure", {"number": "1"})
            new.append(measure_rest(duration))
            new_measures.append(new)
        if attributes is not None and new_measures:
            new_measures[0].insert(0, attributes)
        if mark is not None and new_measures:
            set_measure_time(new_measures[0], mark.beats, mark.beat_type)
        position = (
            list(part).index(between[0])
            if between
            else list(part).index(measures[prev]) + 1
            if prev >= 0
            else 0
        )
        for measure in between:
            part.remove(measure)
        for offset, new in enumerate(new_measures):
            part.insert(position + offset, new)
        result.bars += total
        result.replaced += len(between)
        result.changes.append(
            f"after bar {measures[prev].get('number') if prev >= 0 else 0}: {total} bars of rest "
            f"({sum(m.count for m in group)} under a multi-bar rest) for {len(between)} read"
            + (f", {invented} read notes dropped" if invented else "")
        )
    if result.bars:
        _renumber(part)
    return result
