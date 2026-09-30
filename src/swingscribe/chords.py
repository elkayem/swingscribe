"""Chord symbols on the page, from changes the listener types (roadmap O4).

Every human transcription service and every lead-sheet program delivers the
changes over the solo; until this module we delivered none (docs/landscape.md
section 6). This first version does not listen. The LISTENER types one chorus
of the tune's changes, the way a chart is written, and this module reads it
and lays it over the page's bars.

Recognition is deliberately not here. A chord symbol over a solo is read as a
claim about the harmony, a wrong one is worse than none, and no recogniser has
been measured on this music. When one is, the ground truth is WJazzD's chord
annotation: the `beats` table's `chord` column names the chord at each
CHANGE (30,548 of 132,329 annotated beats over 456 solos) and it holds until
the next. Score a recogniser there by the share of beats whose root and
quality class agree with the chord in effect, on the same repaired grid the
page uses, before a single recognised symbol reaches a page. Those labels
are Jazzomat's spelling, not a chart's: this parser reads 246 of the 419
distinct labels, 82.3% of the changes (2026-09-30), and refuses the rest --
`j7` for a major seventh (3,052 changes), accidentals AFTER the degree
(`79b`, `7911#`), `sus7` for 7sus4. Read them with a converter written for
that syntax beside `wjazz.py`; loosening this grammar to accept `79b` would
make it guess at what a listener meant.

## The chart

    | Dm7 | G7 | Cmaj7 | % |
    | Em7b5 . A7b9 . | Dm7 / G7 / | C6 | / |

- `|` separates bars. Line breaks, and a `|` at either end of a line, are
  layout only, so a bar with nothing new in it must say so: `%` (the bar
  before, again) or `/` (the chord goes on).
- Chords in a bar are separated by spaces (or commas outside parentheses)
  and share the bar EVENLY: two in 4/4 fall on beats 1 and 3. A `.` or `/`
  holds the chord before it for one share, so `C . F G` is C for two beats,
  then F, then G. The shares must divide the bar's beats: three chords in a
  4/4 bar are refused, never guessed at.
- `%` alone in a bar repeats the bar before it, symbols and all.
- `N.C.` (or `NC`) is no chord.
- Repeat signs are refused: the chart is one chorus, written out.

## Spellings

Read by grammar, not from a list of whole symbols: a root (A-G, one flat or
sharp), a family (m mi min -, maj M Δ ^, dim o °, aug +, ø), an extension
(5, 6, 69 or 6/9, 7, 9, 11, 13), then any number of modifiers -- sus, sus2,
sus4, alt, add9, no3, and the alterations b5 #5 b9 #9 #11 b13 (+ and - for
# and b), bare or in parentheses -- and a slash bass. Anything else is
refused with its bar and token named: a spelling this module does not know
is the listener's to fix, never ours to guess.

Each symbol keeps the listener's spelling as the text a reader prints (`-7`
stays `-7`, `Δ` stays `Δ`), beside a MusicXML <kind> and <degree>s that say
what it MEANS, so a reader that respells chords in its own house style still
gets the right chord.

## Placement

The chart is one chorus, repeated from the form start through the span, so a
span that begins in the middle of the third chorus gets the third chorus's
bar under its bar 1. Which bar of the form page bar 1 is comes from
`notation.form_bar_of_page`, counted on the same repaired grid the page and
the roll are built from; `place` is the arithmetic after that.
"""

import math
import re
from dataclasses import dataclass
from fractions import Fraction

from swingscribe.model import ChordDegree, ChordSymbol, Notation

# A share of the bar that holds the chord before it.
HOLDS = frozenset({".", "/"})
REPEAT = "%"


class ChartError(ValueError):
    """A chart that cannot be read. `bar` is 1-based, `token` as typed."""

    def __init__(self, message: str, bar: int | None = None, token: str | None = None):
        super().__init__(message)
        self.bar = bar
        self.token = token


@dataclass(frozen=True)
class ChartBar:
    slots: int  # shares of the bar, chords and holds together
    chords: tuple[tuple[int, ChordSymbol], ...]  # (share index, symbol), in order
    text: str  # the bar as typed


@dataclass(frozen=True)
class Chart:
    bars: tuple[ChartBar, ...]

    @property
    def chord_count(self) -> int:
        return sum(len(bar.chords) for bar in self.bars)


# ── one symbol ───────────────────────────────────────────────────────────────

# The chord tones each MusicXML kind already holds. An alteration of one of
# these is <degree-type>alter</degree-type> (the flat nine of a C13); of any
# other it is "add" (the flat nine of a C7).
_TONES: dict[str, frozenset[int]] = {
    kind: frozenset(tones)
    for kinds, tones in (
        (("major", "minor", "augmented", "diminished"), (1, 3, 5)),
        (
            (
                "dominant",
                "major-seventh",
                "minor-seventh",
                "diminished-seventh",
                "augmented-seventh",
                "half-diminished",
                "major-minor",
            ),
            (1, 3, 5, 7),
        ),
        (("major-sixth", "minor-sixth"), (1, 3, 5, 6)),
        (("dominant-ninth", "major-ninth", "minor-ninth"), (1, 3, 5, 7, 9)),
        (("dominant-11th", "major-11th", "minor-11th"), (1, 3, 5, 7, 9, 11)),
        (("dominant-13th", "major-13th", "minor-13th"), (1, 3, 5, 7, 9, 11, 13)),
        (("suspended-second",), (1, 2, 5)),
        (("suspended-fourth",), (1, 4, 5)),
        (("power",), (1, 5)),
        (("none", "other"), ()),
    )
    for kind in kinds
}

# The family a quality opens with, tried in this order: minor-major before
# major before minor, because "maj" and "mmaj" both begin with "m". "ma" is
# major only before a digit ("Cma7"), or "Cmadd9" would read as major.
_FAMILIES: tuple[tuple[str, re.Pattern], ...] = (
    ("minor-major", re.compile(r"(?:min|mi|m|-)(?:maj|Maj|MAJ|ma|MA|M|Δ)")),
    ("major", re.compile(r"maj|Maj|MAJ|MA(?=\d)|ma(?=\d)|M|Δ")),
    ("minor", re.compile(r"min|mi|m|-")),
    ("half-diminished", re.compile(r"ø")),
    ("diminished", re.compile(r"dim|o")),
    ("augmented", re.compile(r"aug|\+")),
)
_EXTENSION = re.compile(r"13|11|69|9|7|6|5")

# (family, extension) -> (kind, degrees the extension adds beyond the kind).
_KINDS: dict[tuple[str, str | None], tuple[str, tuple[tuple[int, int, str], ...]]] = {
    ("", None): ("major", ()),
    ("", "5"): ("power", ()),
    ("", "6"): ("major-sixth", ()),
    ("", "69"): ("major-sixth", ((9, 0, "add"),)),
    ("", "7"): ("dominant", ()),
    ("", "9"): ("dominant-ninth", ()),
    ("", "11"): ("dominant-11th", ()),
    ("", "13"): ("dominant-13th", ()),
    ("major", None): ("major", ()),
    ("major", "6"): ("major-sixth", ()),
    ("major", "69"): ("major-sixth", ((9, 0, "add"),)),
    ("major", "7"): ("major-seventh", ()),
    ("major", "9"): ("major-ninth", ()),
    ("major", "11"): ("major-11th", ()),
    ("major", "13"): ("major-13th", ()),
    ("minor", None): ("minor", ()),
    ("minor", "6"): ("minor-sixth", ()),
    ("minor", "69"): ("minor-sixth", ((9, 0, "add"),)),
    ("minor", "7"): ("minor-seventh", ()),
    ("minor", "9"): ("minor-ninth", ()),
    ("minor", "11"): ("minor-11th", ()),
    ("minor", "13"): ("minor-13th", ()),
    ("minor-major", "7"): ("major-minor", ()),
    ("minor-major", "9"): ("major-minor", ((9, 0, "add"),)),
    ("half-diminished", None): ("half-diminished", ()),
    ("half-diminished", "7"): ("half-diminished", ()),
    ("half-diminished", "9"): ("half-diminished", ((9, 0, "add"),)),
    ("half-diminished", "11"): ("half-diminished", ((9, 0, "add"), (11, 0, "add"))),
    ("diminished", None): ("diminished", ()),
    ("diminished", "7"): ("diminished-seventh", ()),
    ("augmented", None): ("augmented", ()),
    ("augmented", "7"): ("augmented-seventh", ()),
    ("augmented", "9"): ("dominant-ninth", ((5, 1, "alter"),)),
    ("augmented-major", "7"): ("major-seventh", ((5, 1, "alter"),)),
    ("augmented-major", "9"): ("major-ninth", ((5, 1, "alter"),)),
}

# The kinds a suspension may replace the third of. A triad becomes MusicXML's
# suspended-fourth (or -second); anything larger keeps its kind and gains
# "add 4, subtract 3" -- the encoding MuseScore itself writes for its 7sus4,
# 9sus4 and 13sus4 and prints back under those names, where
# suspended-fourth plus a flat seven comes back "Csus4♭7" (probed with
# MuseScore 4's command line, 2026-09-30).
_SUSPENDABLE = frozenset(
    {
        "major",
        "dominant",
        "dominant-ninth",
        "dominant-11th",
        "dominant-13th",
        "major-sixth",
        "major-seventh",
        "major-ninth",
    }
)

_ALTER_SIGN = {"b": -1, "-": -1, "#": 1, "+": 1}
_ACCIDENTAL = {"": 0, "b": -1, "♭": -1, "#": 1, "♯": 1}
_NOTE = re.compile(r"([A-G])(b|#|♭|♯)?")
_SLASH_BASS = re.compile(r"(.+)/([A-G](?:b|#|♭|♯)?)")
_NO_CHORD = frozenset({"N.C.", "N.C", "NC", "n.c.", "N/C"})

# Unicode a chart pasted from a lead sheet or typed on a Mac arrives in:
# the triangle three ways, the degree sign, the slashed O, the real flat,
# sharp and minus signs.
_NORMAL = str.maketrans(
    {
        "♭": "b",
        "♯": "#",
        "−": "-",
        "–": "-",
        "∆": "Δ",
        "△": "Δ",
        "^": "Δ",
        "°": "o",
        "º": "o",
        "Ø": "ø",
        "∅": "ø",
    }
)


def _degree(value: int, alter: int, kind: str, present: set[int]) -> ChordDegree:
    """An alteration: "alter" if the chord already holds the degree, "add"
    if not. The fifth is in every chord this module writes."""
    held = value == 5 or value in _TONES.get(kind, frozenset()) or value in present
    return ChordDegree(value=value, alter=alter, type="alter" if held else "add")


def parse_quality(suffix: str) -> tuple[str, list[ChordDegree]]:
    """The part of a symbol after its root (and before a slash bass) as a
    MusicXML kind and degrees. Raises ChartError on anything it does not
    know."""
    text = suffix.translate(_NORMAL)
    text = re.sub(r"[()\s,]", "", text).replace("6/9", "69")
    rest = text
    family = ""
    delta = False
    for name, pattern in _FAMILIES:
        match = pattern.match(rest)
        if match:
            family, delta = name, match.group(0).endswith("Δ")
            rest = rest[match.end() :]
            break
    if family == "augmented":
        # "+maj7", "augΔ": an augmented triad under a major seventh.
        major = _FAMILIES[1][1].match(rest)
        if major:
            family, delta = "augmented-major", major.group(0) == "Δ"
            rest = rest[major.end() :]
    extension = None
    match = _EXTENSION.match(rest)
    if match:
        extension = match.group(0)
        rest = rest[match.end() :]
    elif delta or family == "augmented-major":
        # A triangle alone is a major seventh, the way every chart uses it.
        extension = "7"
    key = (family, extension)
    if key not in _KINDS:
        raise ChartError(
            f"unknown chord quality {suffix!r} (no {family or 'major'} chord is written "
            f"with {extension or 'nothing after it'})"
        )
    kind, extra = _KINDS[key]
    degrees = [ChordDegree(value=v, alter=a, type=t) for v, a, t in extra]

    sus: str | None = None
    alt = False
    altered: list[tuple[int, int]] = []
    while rest:
        if match := re.match(r"sus([24])?", rest):
            sus = match.group(1) or "4"
        elif match := re.match(r"alt", rest):
            alt = True
        elif match := re.match(r"add([b#+-]?)(2|4|9|11|13)", rest):
            alter = _ALTER_SIGN.get(match.group(1), 0)
            degrees.append(ChordDegree(value=int(match.group(2)), alter=alter, type="add"))
        elif match := re.match(r"(?:no|omit)([35])", rest):
            degrees.append(ChordDegree(value=int(match.group(1)), alter=0, type="subtract"))
        elif match := re.match(r"([b#+-])(5|9|11|13)", rest):
            altered.append((int(match.group(2)), _ALTER_SIGN[match.group(1)]))
        elif match := re.fullmatch(r"\+", rest):
            # "C7+": the augmented fifth, the older way of writing it.
            altered.append((5, 1))
        else:
            raise ChartError(f"unknown chord quality {suffix!r} (cannot read {rest!r})")
        rest = rest[match.end() :]

    # A minor seventh with a flat five is the half-diminished chord, however
    # it is spelled: m7b5, -7b5, mi7(b5).
    if kind in ("minor-seventh", "minor-ninth", "minor-11th") and (5, -1) in altered:
        altered.remove((5, -1))
        if kind != "minor-seventh":
            degrees.insert(0, ChordDegree(value=9, alter=0, type="add"))
        if kind == "minor-11th":
            degrees.insert(1, ChordDegree(value=11, alter=0, type="add"))
        kind = "half-diminished"
    if alt:
        # The altered dominant names a scale, not a set of tones: no kind or
        # degree set means it, so it is written as MuseScore writes its own
        # "7alt" -- kind "other", the spelling as the text -- which MuseScore
        # reads back as that chord and every reader prints as typed. The
        # tensions spelled out as degrees came back "C7♭9♯9♯11♭13".
        if kind not in ("major", "dominant") or (kind == "major" and family):
            raise ChartError(f"unknown chord quality {suffix!r} (alt is a dominant seventh)")
        kind = "other"
    if sus is not None:
        if kind not in _SUSPENDABLE:
            raise ChartError(
                f"unknown chord quality {suffix!r} (sus replaces the third of a major or "
                "dominant chord)"
            )
        if kind == "major":
            kind = "suspended-second" if sus == "2" else "suspended-fourth"
        else:
            degrees = [
                ChordDegree(value=int(sus), alter=0, type="add"),
                ChordDegree(value=3, alter=0, type="subtract"),
                *degrees,
            ]
    present = {d.value for d in degrees if d.type != "subtract"}
    degrees.extend(_degree(value, alter, kind, present) for value, alter in altered)
    return kind, degrees


def parse_symbol(token: str) -> ChordSymbol:
    """One chord symbol, e.g. "Bb7#11", "F#m7b5", "C7/E", "N.C."."""
    if token in _NO_CHORD:
        return ChordSymbol(kind="none", text="N.C.")
    body, bass = token, None
    slash = _SLASH_BASS.fullmatch(token)
    if slash:
        body, bass = slash.group(1), slash.group(2)
    root = _NOTE.match(body)
    if root is None:
        raise ChartError("a chord starts with its root, a capital A to G")
    suffix = body[root.end() :]
    kind, degrees = parse_quality(suffix)
    symbol = ChordSymbol(
        root_step=root.group(1),
        root_alter=_ACCIDENTAL[root.group(2) or ""],
        kind=kind,
        text=suffix,
        degrees=degrees,
    )
    if bass is not None:
        note = _NOTE.fullmatch(bass)
        assert note is not None  # the slash pattern only matches a note
        symbol.bass_step = note.group(1)
        symbol.bass_alter = _ACCIDENTAL[note.group(2) or ""]
    return symbol


def name(symbol: ChordSymbol) -> str:
    """The symbol as a chart spells it: root, the listener's suffix, bass."""
    if symbol.kind == "none":
        return "N.C."
    signs = {-1: "b", 0: "", 1: "#"}
    text = f"{symbol.root_step}{signs[symbol.root_alter]}{symbol.text}"
    if symbol.bass_step is not None:
        text += f"/{symbol.bass_step}{signs[symbol.bass_alter]}"
    return text


# ── the chart ────────────────────────────────────────────────────────────────


def _tokens(segment: str) -> list[str]:
    """A bar's tokens: split on spaces and on commas outside parentheses, so
    "Dm7, G7" is two chords and "C7(b9, #11)" is one."""
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    for char in segment:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (char.isspace() or char == ","):
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def parse_chart(text: str, beats_per_bar: int | None = None) -> Chart:
    """One chorus of changes. `beats_per_bar` (the time signature's
    numerator) is what a bar's shares must divide; None checks nothing.

    An empty chart is a chart with no bars, not an error: the listener has
    typed no changes. A chart with bars and not one chord is refused.
    """
    bars: list[ChartBar] = []
    segments = [segment.strip() for segment in text.split("|")]
    for segment in segments:
        if not segment:
            continue
        number = len(bars) + 1
        if segment.startswith(":") or segment.endswith(":"):
            raise ChartError(
                f"bar {number}: repeat signs are not read - write the chorus out bar by bar",
                number,
                segment,
            )
        tokens = _tokens(segment)
        if not tokens:
            raise ChartError(f"bar {number}: no chord and no hold in {segment!r}", number, segment)
        if REPEAT in tokens:
            if tokens != [REPEAT]:
                raise ChartError(f"bar {number}: '%' stands alone in its bar", number, REPEAT)
            if not bars:
                raise ChartError(
                    f"bar {number}: '%' repeats the bar before, and there is none", number, REPEAT
                )
            bars.append(ChartBar(bars[-1].slots, bars[-1].chords, segment))
            continue
        chords: list[tuple[int, ChordSymbol]] = []
        for slot, token in enumerate(tokens):
            if token in HOLDS:
                continue
            try:
                chords.append((slot, parse_symbol(token)))
            except ChartError as exc:
                raise ChartError(f"bar {number}, {token!r}: {exc}", number, token) from exc
        if beats_per_bar and beats_per_bar % len(tokens):
            raise ChartError(
                f"bar {number}: {len(tokens)} chords cannot share a bar of {beats_per_bar} "
                "beats evenly - hold a chord with '.', as in 'C . F G'",
                number,
                segment,
            )
        bars.append(ChartBar(len(tokens), tuple(chords), segment))
    chart = Chart(bars=tuple(bars))
    if bars and not chart.chord_count:
        raise ChartError("the chart holds no chord, only holds and repeats")
    return chart


# ── placement ────────────────────────────────────────────────────────────────


def in_effect(chart: Chart, index: int, at: Fraction) -> ChordSymbol | None:
    """The chord sounding at `at` (a fraction of the bar) in chart bar
    `index`, looking back through the chart, a chorus round if need be."""
    count = len(chart.bars)
    for back in range(count + 1):
        bar = chart.bars[(index - back) % count]
        sounding = [
            symbol for slot, symbol in bar.chords if back > 0 or Fraction(slot, bar.slots) <= at
        ]
        if sounding:
            return sounding[-1]
    return None


def place(
    chart: Chart,
    notation: Notation,
    form_bar: int,
    bars_per_chart_bar: int = 1,
) -> Notation:
    """The chart laid over the page's bars, as a copy; the notes untouched.

    `form_bar` is the bar of the form page bar 1 falls on: 1 is the chart's
    first bar, 33 the first bar of a 32-bar tune's second chorus, and 0 or
    less a bar before the form starts, where nothing is written. The chart
    repeats every `len(chart.bars)` bars. `bars_per_chart_bar` is 2 on a
    double-time page, whose bar is half a played one.

    The first bar of the page inside the form always opens with a symbol: a
    chart bar that holds (`/`) its chord would otherwise leave the page's
    first bar with none, and a reader starting there has to know the
    harmony.
    """
    if not chart.bars:
        return notation
    count = len(chart.bars)
    scale = max(1, bars_per_chart_bar)
    bars = []
    opened = False
    for bar in notation.bars:
        played, half = divmod(bar.number - 1, scale)
        form = form_bar + played
        if form < 1:
            bars.append(bar.model_copy(update={"harmony": []}))
            continue
        index = (form - 1) % count
        source = chart.bars[index]
        length = Fraction(bar.time_signature[0] * 4, bar.time_signature[1])
        symbols = []
        for slot, symbol in source.chords:
            share = Fraction(slot, source.slots) * scale
            if math.floor(share) != half:
                continue
            symbols.append(symbol.model_copy(update={"beat": float((share - half) * length)}))
        if not opened:
            opened = True
            if not symbols or symbols[0].beat > 0:
                held = in_effect(chart, index, Fraction(half, scale))
                if held is not None:
                    symbols.insert(0, held.model_copy(update={"beat": 0.0}))
        bars.append(bar.model_copy(update={"harmony": symbols}))
    return notation.model_copy(update={"bars": bars})
