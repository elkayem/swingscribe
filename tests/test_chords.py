"""Chord symbols from a chart the listener types (roadmap O4, chords.py).

All of it is text and arithmetic, so all of it runs in CI: the parser over
the jazz spellings a chart is written in, the refusals that name a bar and a
token, the chart's placement from the form start through a span that begins
mid-chorus, and the <harmony> export -- transposed with the part, as the
notes and key signature are.

No chart here is a real tune's: the changes are made up, like the notes in
every other test.
"""

from fractions import Fraction
from xml.etree import ElementTree

import pytest

from swingscribe import chords
from swingscribe.chords import ChartError, parse_chart, parse_symbol, place
from swingscribe.config import Config
from swingscribe.model import ChordSymbol, NotatedBar, NotatedNote, Notation, NoteEvent
from swingscribe.notation import (
    bar_number_at,
    form_bar_of_page,
    notation_for_span,
    page_downbeat,
)
from swingscribe.stages.export import DIVISIONS, to_musicxml, written_root

# ── one symbol ───────────────────────────────────────────────────────────────


def degrees(symbol: ChordSymbol) -> list[tuple[int, int, str]]:
    return [(d.value, d.alter, d.type) for d in symbol.degrees]


@pytest.mark.parametrize(
    "token, kind, text, expected",
    [
        ("C", "major", "", []),
        ("Cm", "minor", "m", []),
        ("C-", "minor", "-", []),
        ("Cmaj7", "major-seventh", "maj7", []),
        ("CΔ", "major-seventh", "Δ", []),
        ("C∆7", "major-seventh", "∆7", []),  # the Mac's increment sign
        ("C^7", "major-seventh", "^7", []),
        ("CM7", "major-seventh", "M7", []),
        ("CMA7", "major-seventh", "MA7", []),
        ("C7", "dominant", "7", []),
        ("Cm7", "minor-seventh", "m7", []),
        ("C-7", "minor-seventh", "-7", []),
        ("Cmi7", "minor-seventh", "mi7", []),
        ("Cmin7", "minor-seventh", "min7", []),
        ("Cm7b5", "half-diminished", "m7b5", []),
        ("C-7b5", "half-diminished", "-7b5", []),
        ("Cmi7(b5)", "half-diminished", "mi7(b5)", []),
        ("Cø", "half-diminished", "ø", []),
        ("Cø7", "half-diminished", "ø7", []),
        ("Cdim", "diminished", "dim", []),
        ("C°", "diminished", "°", []),
        ("C°7", "diminished-seventh", "°7", []),
        ("Co7", "diminished-seventh", "o7", []),
        ("Cdim7", "diminished-seventh", "dim7", []),
        ("C+", "augmented", "+", []),
        ("Caug", "augmented", "aug", []),
        ("C+7", "augmented-seventh", "+7", []),
        ("C6", "major-sixth", "6", []),
        ("C69", "major-sixth", "69", [(9, 0, "add")]),
        ("C6/9", "major-sixth", "6/9", [(9, 0, "add")]),
        ("Cm6", "minor-sixth", "m6", []),
        ("C9", "dominant-ninth", "9", []),
        ("C11", "dominant-11th", "11", []),
        ("C13", "dominant-13th", "13", []),
        ("Cmaj9", "major-ninth", "maj9", []),
        ("Cm9", "minor-ninth", "m9", []),
        ("Cm11", "minor-11th", "m11", []),
        ("Cm(maj7)", "major-minor", "m(maj7)", []),
        ("CmΔ7", "major-minor", "mΔ7", []),
        ("C-Δ7", "major-minor", "-Δ7", []),
        ("C5", "power", "5", []),
        ("Csus4", "suspended-fourth", "sus4", []),
        ("Csus", "suspended-fourth", "sus", []),
        ("Csus2", "suspended-second", "sus2", []),
        ("Cadd9", "major", "add9", [(9, 0, "add")]),
        ("Cmadd9", "minor", "madd9", [(9, 0, "add")]),
        # Alterations: "add" when the kind lacks the degree, "alter" when it
        # holds it (the flat nine of a C13, every fifth).
        ("C7b9", "dominant", "7b9", [(9, -1, "add")]),
        ("C7#9", "dominant", "7#9", [(9, 1, "add")]),
        ("C7#11", "dominant", "7#11", [(11, 1, "add")]),
        ("C7b5", "dominant", "7b5", [(5, -1, "alter")]),
        ("C7#5", "dominant", "7#5", [(5, 1, "alter")]),
        ("C7+5", "dominant", "7+5", [(5, 1, "alter")]),
        ("C7-9", "dominant", "7-9", [(9, -1, "add")]),
        ("C13b9", "dominant-13th", "13b9", [(9, -1, "alter")]),
        ("C9#11", "dominant-ninth", "9#11", [(11, 1, "add")]),
        ("C7(b9,#11)", "dominant", "7(b9,#11)", [(9, -1, "add"), (11, 1, "add")]),
        ("C7b9#9", "dominant", "7b9#9", [(9, -1, "add"), (9, 1, "add")]),
        ("Cmaj7#11", "major-seventh", "maj7#11", [(11, 1, "add")]),
        ("CΔ#11", "major-seventh", "Δ#11", [(11, 1, "add")]),
        ("C+maj7", "major-seventh", "+maj7", [(5, 1, "alter")]),
        ("Cm9b5", "half-diminished", "m9b5", [(9, 0, "add")]),
        # A suspension of a seventh chord is MuseScore's own encoding of it.
        ("C7sus4", "dominant", "7sus4", [(4, 0, "add"), (3, 0, "subtract")]),
        ("C7sus", "dominant", "7sus", [(4, 0, "add"), (3, 0, "subtract")]),
        ("C9sus4", "dominant-ninth", "9sus4", [(4, 0, "add"), (3, 0, "subtract")]),
        ("C13sus", "dominant-13th", "13sus", [(4, 0, "add"), (3, 0, "subtract")]),
        # The altered dominant names a scale: kind "other", as MuseScore writes it.
        ("C7alt", "other", "7alt", []),
        ("Calt", "other", "alt", []),
    ],
)
def test_the_jazz_spellings(token, kind, text, expected):
    symbol = parse_symbol(token)
    assert (symbol.root_step, symbol.root_alter) == ("C", 0)
    assert symbol.kind == kind
    assert symbol.text == text
    assert degrees(symbol) == expected
    assert symbol.bass_step is None


@pytest.mark.parametrize(
    "token, root, alter",
    [
        ("Bb7", "B", -1),
        ("B♭7", "B", -1),
        ("F#m7b5", "F", 1),
        ("F♯m7♭5", "F", 1),
        ("Ebmaj7", "E", -1),
    ],
)
def test_flats_and_sharps_on_the_root(token, root, alter):
    symbol = parse_symbol(token)
    assert (symbol.root_step, symbol.root_alter) == (root, alter)


def test_a_flat_root_before_a_nine_is_the_root_not_an_alteration():
    """B-flat nine is written "Bb9", never B with a flat nine: the root takes its
    accidental first, the way every reader of a chart reads it."""
    symbol = parse_symbol("Bb9")
    assert (symbol.root_step, symbol.root_alter, symbol.kind) == ("B", -1, "dominant-ninth")


def test_a_slash_chord_has_its_bass():
    symbol = parse_symbol("C7/E")
    assert (symbol.kind, symbol.text, symbol.bass_step, symbol.bass_alter) == (
        "dominant",
        "7",
        "E",
        0,
    )
    flat = parse_symbol("Abmaj7/Bb")
    assert (flat.root_step, flat.root_alter, flat.bass_step, flat.bass_alter) == ("A", -1, "B", -1)
    # 6/9 is a quality, not a bass: 9 is not a note name.
    assert parse_symbol("C6/9").bass_step is None
    assert parse_symbol("C6/9/G").bass_step == "G"


def test_no_chord():
    for token in ("N.C.", "NC"):
        symbol = parse_symbol(token)
        assert (symbol.kind, symbol.text) == ("none", "N.C.")


@pytest.mark.parametrize(
    "token", ["Cx", "Cmaj7#", "c7", "H7", "C2", "Cm7sus4", "Cmalt", "C9alt", "Cdim9", "C7/"]
)
def test_an_unknown_quality_is_refused_never_guessed(token):
    with pytest.raises(ChartError):
        parse_symbol(token)


def test_name_spells_a_symbol_back():
    assert chords.name(parse_symbol("F#m7b5")) == "F#m7b5"
    assert chords.name(parse_symbol("Bb7/D")) == "Bb7/D"
    assert chords.name(parse_symbol("N.C.")) == "N.C."


# ── the chart ────────────────────────────────────────────────────────────────


def slots(chart) -> list[list[tuple[int, str]]]:
    return [[(slot, chords.name(symbol)) for slot, symbol in bar.chords] for bar in chart.bars]


def test_bars_shares_and_holds():
    chart = parse_chart("| Dm7 G7 | Cmaj7 | Em7b5 . A7b9 . | C . F G |", beats_per_bar=4)
    assert [bar.slots for bar in chart.bars] == [2, 1, 4, 4]
    assert slots(chart) == [
        [(0, "Dm7"), (1, "G7")],
        [(0, "Cmaj7")],
        [(0, "Em7b5"), (2, "A7b9")],
        [(0, "C"), (2, "F"), (3, "G")],
    ]
    assert chart.chord_count == 8


def test_line_breaks_and_outer_bar_lines_are_layout():
    """A chart typed four bars to a line has a bar line at both ends of
    every line; that must not make empty bars."""
    chart = parse_chart("| C7 | F7 | C7 | / |\n| F7 | / | C7 | % |\n")
    assert len(chart.bars) == 8
    assert parse_chart("C7 F7").bars[0].slots == 2  # no bar lines: one bar


def test_a_repeat_copies_the_bar_before_and_a_hold_writes_nothing():
    chart = parse_chart("| C7 F7 | % | / |")
    assert slots(chart) == [[(0, "C7"), (1, "F7")], [(0, "C7"), (1, "F7")], []]


def test_commas_separate_chords_except_inside_parentheses():
    chart = parse_chart("| Dm7, G7 | C7(b9, #11) |")
    # The listener's spelling is kept whole, space and all: it is what prints.
    assert slots(chart) == [[(0, "Dm7"), (1, "G7")], [(0, "C7(b9, #11)")]]
    assert degrees(chart.bars[1].chords[0][1]) == [(9, -1, "add"), (11, 1, "add")]


def test_an_empty_chart_is_no_changes():
    assert parse_chart("").bars == ()
    assert parse_chart("  |  \n | ").bars == ()


def test_a_parse_error_names_the_bar_and_the_token():
    with pytest.raises(ChartError) as caught:
        parse_chart("| C7 | F7 | C7 | Cxx7 |")
    assert caught.value.bar == 4
    assert caught.value.token == "Cxx7"
    assert "bar 4" in str(caught.value) and "Cxx7" in str(caught.value)


def test_shares_that_do_not_divide_the_bar_are_refused():
    """Three chords in a 4/4 bar have no even split on the beats; which of
    them gets two beats is the listener's to say, with a hold."""
    with pytest.raises(ChartError) as caught:
        parse_chart("| C7 | C F G |", beats_per_bar=4)
    assert caught.value.bar == 2 and "'.'" in str(caught.value)
    assert parse_chart("| C F G |", beats_per_bar=3).bars[0].slots == 3  # 3/4: one each
    assert parse_chart("| C F G |").bars[0].slots == 3  # no meter given: not checked


@pytest.mark.parametrize(
    "text, bar",
    [
        ("|: C7 | F7 :|", 1),  # a repeat sign
        ("| C7 | % F7 |", 2),  # '%' shares its bar
        ("| % | C7 |", 1),  # nothing to repeat
        ("| C7 | , |", 2),  # nothing at all
    ],
)
def test_malformed_bars_are_refused(text, bar):
    with pytest.raises(ChartError) as caught:
        parse_chart(text)
    assert caught.value.bar == bar


def test_a_chart_of_holds_alone_is_refused():
    with pytest.raises(ChartError):
        parse_chart("| / | % |")


# ── placement ────────────────────────────────────────────────────────────────


def page(bars: int, first: int = 1, signature=(4, 4)) -> Notation:
    length = signature[0] * 4.0 / signature[1]
    return Notation(
        bars=[
            NotatedBar(
                number=number,
                time_signature=signature,
                notes=[NotatedNote(beat=0.0, duration=length, is_rest=True)],
            )
            for number in range(first, first + bars)
        ]
    )


def placed(notation: Notation) -> dict[int, list[tuple[float, str]]]:
    return {
        bar.number: [(symbol.beat, chords.name(symbol)) for symbol in bar.harmony]
        for bar in notation.bars
    }


CHART = parse_chart("| C7 | F7 | C7 G7 | Dm7 . G7 . |", 4)


def test_the_chart_repeats_every_chorus():
    result = placed(place(CHART, page(6), form_bar=1))
    assert result[1] == [(0.0, "C7")]
    assert result[3] == [(0.0, "C7"), (2.0, "G7")]
    assert result[4] == [(0.0, "Dm7"), (2.0, "G7")]
    assert result[5] == [(0.0, "C7")]  # chorus 2
    assert result[6] == [(0.0, "F7")]


def test_a_span_that_starts_mid_chorus_gets_its_bar_of_the_chart():
    """Page bar 1 is form bar 7: the third bar of the second chorus of a
    four-bar chart."""
    result = placed(place(CHART, page(3), form_bar=7))
    assert result[1] == [(0.0, "C7"), (2.0, "G7")]
    assert result[2] == [(0.0, "Dm7"), (2.0, "G7")]
    assert result[3] == [(0.0, "C7")]


def test_nothing_is_written_before_the_form_starts():
    """An intro, or a pickup before bar 1 of the form: no chart bar is
    there to write."""
    result = placed(place(CHART, page(4, first=0), form_bar=-1))
    assert result[0] == [] and result[1] == [] and result[2] == []
    assert result[3] == [(0.0, "C7")]


def test_the_first_bar_opens_with_the_chord_in_effect():
    """A chart bar that holds its chord leaves the page's first bar with no
    symbol of its own; a reader starting there must still know it."""
    chart = parse_chart("| C7 | / F7 | Bb7 |", 4)
    result = placed(place(chart, page(3), form_bar=2))
    assert result[1] == [(0.0, "C7"), (2.0, "F7")]
    assert result[2] == [(0.0, "Bb7")]
    # ...and a chorus round, when the chart's first bar is the hold.
    held = parse_chart("| / | C7 | F7 |", 4)
    assert placed(place(held, page(1), form_bar=1))[1] == [(0.0, "F7")]
    # Later bars that hold write nothing: the page shows what the chart does.
    assert placed(place(chart, page(3), form_bar=1))[2] == [(2.0, "F7")]


def test_a_double_time_page_spreads_a_chart_bar_over_two():
    """Double time writes a played bar as two page bars, so a chart bar's
    beat 3 is the next page bar's beat 1."""
    result = placed(place(CHART, page(4), form_bar=3, bars_per_chart_bar=2))
    assert result[1] == [(0.0, "C7")]
    assert result[2] == [(0.0, "G7")]
    assert result[3] == [(0.0, "Dm7")]
    assert result[4] == [(0.0, "G7")]


def test_a_three_four_chart_falls_on_its_beats():
    chart = parse_chart("| C7 F7 Bb7 |", 3)
    result = placed(place(chart, page(1, signature=(3, 4)), form_bar=1))
    assert result[1] == [(0.0, "C7"), (1.0, "F7"), (2.0, "Bb7")]


def test_placement_copies_and_leaves_the_notes_alone():
    original = page(2)
    result = place(CHART, original, form_bar=1)
    assert all(not bar.harmony for bar in original.bars)
    assert [bar.notes for bar in result.bars] == [bar.notes for bar in original.bars]


def test_in_effect_looks_back_a_chorus_round():
    chart = parse_chart("| C7 F7 | / |", 4)
    assert chords.name(chords.in_effect(chart, 1, Fraction(0))) == "F7"
    assert chords.name(chords.in_effect(chart, 0, Fraction(0))) == "C7"


# ── which bar of the form page bar 1 is ──────────────────────────────────────


def grid(count: int, step: float = 0.5, start: float = 0.0) -> list[float]:
    return [round(start + i * step, 6) for i in range(count)]


def test_page_bar_one_is_counted_from_the_form_start():
    """Beats every half second, bar lines every 2 s from 0; the form starts
    at 2 s, so the page for a span starting at 10 s opens on form bar 5."""
    beats = grid(81)  # 0 .. 40 s
    settings = {"anchor": 0.0, "form_start": 2.0}
    assert form_bar_of_page(beats, [], settings, Config(), 40.0, (10.0, 20.0)) == 5
    # A chorus of four bars: that is the first bar of the second chorus, and
    # a span two seconds later opens on its second bar.
    assert form_bar_of_page(beats, [], settings, Config(), 40.0, (12.0, 22.0)) == 6
    # Without a form start the roll numbers from its first bar line.
    assert form_bar_of_page(beats, [], {"anchor": 0.0}, Config(), 40.0, (10.0, 20.0)) == 6


def test_a_span_before_the_form_start_is_counted_negative():
    beats = grid(81)
    settings = {"anchor": 0.0, "form_start": 20.0}
    assert form_bar_of_page(beats, [], settings, Config(), 40.0, (10.0, 30.0)) == -4


def test_the_form_bar_follows_the_page_downbeat_the_notes_are_counted_from():
    """The chart and the page must count bar 1 from the same beat: the one
    `notation_for_span` puts its first downbeat on."""
    beats = grid(121)  # 0 .. 60 s
    span = (20.8, 31.0)  # bar lines at 20 and 22 with the anchor at 0: 20 is nearer
    downbeat = page_downbeat(beats, span, 0.0, 4)
    assert downbeat == 20.0
    notes = [
        NoteEvent(onset=t, duration=0.4, pitch=60 + i % 12, confidence=0.9, source="other")
        for i, t in enumerate(beats)
        if span[0] <= t <= span[1]
    ]
    notation = notation_for_span("t.wav", notes, beats, span, stem="other", anchor=0.0)
    first = next(bar for bar in notation.bars if bar.number == 1)
    # The note at 21.0 s is on beat 3 of bar 1 (bar 1 began at 20.0 s).
    assert [n.beat for n in first.notes if not n.is_rest][0] == 2.0
    assert form_bar_of_page(beats, [], {"anchor": 0.0}, Config(), 60.0, span) == 11


def test_the_bar_number_is_counted_in_beats_across_free_time():
    """The roll draws no bar lines through free time; the page's downbeat
    past it still gets the number the beats count to."""
    beats = grid(40)  # 0 .. 19.5
    lines = [(0.0, 1), (2.0, 2)]  # the roll stops drawing after bar 2
    assert bar_number_at(beats, lines, 12.0, 4) == 7
    assert bar_number_at(beats, [], 12.0, 4) is None


# ── export ───────────────────────────────────────────────────────────────────


def document(notation: Notation):
    body = to_musicxml(notation)
    return ElementTree.fromstring(body[body.index("<score-partwise") :])


def note(beat: float, duration: float, pitch: int = 65, **kw) -> NotatedNote:
    return NotatedNote(beat=beat, duration=duration, pitch=pitch, step="F", octave=4, **kw)


def chart_page(text: str, bars: list[list[NotatedNote]], transpose: int = 0, **kw) -> Notation:
    notation = Notation(
        bars=[NotatedBar(number=i, time_signature=(4, 4), notes=n) for i, n in enumerate(bars, 1)],
        transpose=transpose,
        **kw,
    )
    return place(parse_chart(text, 4), notation, form_bar=1)


def harmonies(root) -> list[dict]:
    found = []
    for measure in root.iter("measure"):
        for element in measure.findall("harmony"):
            found.append(
                {
                    "bar": int(measure.get("number")),
                    "root": (
                        element.findtext("root/root-step"),
                        element.findtext("root/root-alter"),
                    ),
                    "kind": element.findtext("kind"),
                    "text": element.find("kind").get("text"),
                    "bass": (
                        element.findtext("bass/bass-step"),
                        element.findtext("bass/bass-alter"),
                    ),
                    "offset": element.findtext("offset"),
                    "degrees": [
                        (
                            d.findtext("degree-value"),
                            d.findtext("degree-alter"),
                            d.findtext("degree-type"),
                            d.get("print-object"),
                        )
                        for d in element.findall("degree")
                    ],
                    "children": [child.tag for child in element],
                }
            )
    return found


def test_the_harmony_element_in_the_schemas_order():
    notation = chart_page("| Bb7b9/D |", [[note(0.0, 4.0)]])
    [harmony] = harmonies(document(notation))
    assert harmony["children"] == ["root", "kind", "bass", "degree"]
    assert harmony["root"] == ("B", "-1")
    assert (harmony["kind"], harmony["text"]) == ("dominant", "7b9")
    assert harmony["bass"] == ("D", None)
    # The text spells the flat nine already; the degree is there for a
    # reader that respells chords, and marked so none prints it twice.
    assert harmony["degrees"] == [("9", "-1", "add", "no")]
    assert harmony["offset"] is None


def test_a_change_under_a_held_note_is_offset_into_it():
    """Beat 3 falls inside a half note from beat 2: the symbol goes before
    that note, a quarter into it, rather than moving to the next note."""
    notation = chart_page("| Dm7 G7 |", [[note(0.0, 1.0), note(1.0, 2.0), note(3.0, 1.0)]])
    measure = document(notation).find(".//measure")
    order = [child.tag for child in measure if child.tag in ("harmony", "note")]
    assert order == ["harmony", "note", "harmony", "note", "note"]
    offsets = [h["offset"] for h in harmonies(document(notation))]
    assert offsets == [None, str(DIVISIONS)]


def test_chord_symbols_add_no_time_to_a_bar():
    notation = chart_page("| C7 . F7 . |", [[note(0.0, 1.0), note(1.0, 1.0), note(2.0, 2.0)]])
    measure = document(notation).find(".//measure")
    assert sum(int(n.findtext("duration")) for n in measure.findall("note")) == 4 * DIVISIONS


def test_a_page_without_changes_writes_no_harmony():
    notation = Notation(bars=[NotatedBar(number=1, time_signature=(4, 4), notes=[note(0.0, 4.0)])])
    assert "<harmony" not in to_musicxml(notation)


@pytest.mark.parametrize(
    "concert, semitones, written",
    [
        # B-flat tenor (+14) and trumpet (+2): up a major second.
        (("B", -1), 14, ("C", 0)),
        (("E", -1), 14, ("F", 0)),
        (("F", 1), 14, ("G", 1)),
        (("G", -1), 2, ("A", -1)),  # by interval, whatever the key says
        (("E", 0), 2, ("F", 1)),
        # E-flat alto (+9): up a major sixth.
        (("B", -1), 9, ("G", 0)),
        (("D", -1), 9, ("B", -1)),
        (("A", 1), 9, ("G", 0)),  # F## respelled: no symbol wants a double sharp
        (("C", 0), 0, ("C", 0)),
    ],
)
def test_roots_move_by_the_parts_interval(concert, semitones, written):
    assert written_root(*concert, semitones) == written


def test_a_b_flat_tenor_part_writes_its_chords_up_a_ninth():
    """Everything is concert until export: the notes, the key signature and
    the chord symbols all move with the part, in the same place."""
    notation = chart_page(
        "| Bb7 | F#m7b5 . C7/E . |",
        [[note(0.0, 4.0, 70)], [note(0.0, 4.0, 66)]],
        transpose=14,
        key_fifths=-2,
    )
    root = document(notation)
    found = [(h["root"], h["text"], h["bass"]) for h in harmonies(root)]
    assert found == [
        (("C", None), "7", (None, None)),
        (("G", "1"), "m7b5", (None, None)),
        (("D", None), "7", ("F", "1")),
    ]
    assert root.findtext(".//key/fifths") == "0"  # concert B-flat major, written C
    assert root.findtext(".//note/pitch/step") == "C"  # the concert B-flat, written C


def test_no_chord_hides_its_root():
    notation = chart_page("| N.C. |", [[note(0.0, 4.0)]])
    element = document(notation).find(".//harmony")
    assert element.find("root/root-step").get("text") == ""
    assert (element.findtext("kind"), element.find("kind").get("text")) == ("none", "N.C.")


def test_on_a_grand_staff_the_chords_sit_over_the_treble_only():
    bars = [[note(0.0, 4.0, 72), note(0.0, 4.0, 48, staff=2)]]
    notation = chart_page("| C7 F7 |", bars, staves=2)
    measure = document(notation).find(".//measure")
    tags = [child.tag for child in measure]
    # Both symbols come before the rewind to the bass staff, each on staff 1.
    assert tags.index("backup") > max(i for i, tag in enumerate(tags) if tag == "harmony")
    assert [h.findtext("staff") for h in measure.findall("harmony")] == ["1", "1"]
    assert [h.findtext("offset") for h in measure.findall("harmony")] == [None, str(2 * DIVISIONS)]
