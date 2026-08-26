"""Stage 7 — MusicXML. Pure XML assembly, so all of it runs in CI.

The acceptance criterion (plan §5) is that the file opens in MuseScore without
import warnings, which no test can assert. What tests *can* do is guard the
things that make a reader reject or silently mangle a file, and those are
specific: measures that do not add up, a tie written only half, a transposed
part whose key signature did not move with it.
"""

from xml.etree import ElementTree

from swingscribe.model import NotatedBar, NotatedNote, Notation
from swingscribe.stages.export import (
    DIVISIONS,
    fifths_for_transpose,
    note_type,
    to_musicxml,
    transpose_element,
)


def note(beat, duration, pitch=60, **kw) -> NotatedNote:
    return NotatedNote(beat=beat, duration=duration, pitch=pitch, **kw)


def bar_of(notes, number=1) -> NotatedBar:
    return NotatedBar(number=number, time_signature=(4, 4), notes=notes)


def parse(xml: str):
    return ElementTree.fromstring(xml.split("]>\n")[-1] if "]>" in xml else xml.split(">\n", 2)[-1])


def document(notation: Notation):
    body = to_musicxml(notation)
    start = body.index("<score-partwise")
    return ElementTree.fromstring(body[start:])


# ── the things that make a reader reject a file ──────────────────────────


def test_every_measure_sums_to_its_time_signature():
    """The single most common reason a notation program refuses a file."""
    notation = Notation(
        bars=[bar_of([note(0.0, 1.0), note(1.0, 1.0), note(2.0, 2.0)])],
        key_fifths=0,
    )
    root = document(notation)
    measure = root.find(".//measure")
    total = sum(int(n.findtext("duration")) for n in measure.findall("note"))
    assert total == 4 * DIVISIONS


def test_a_triplet_beat_sums_exactly_with_no_rounding():
    """24 divisions is chosen so a third of a beat is an integer. At 12 or 16
    it is not, and three of them do not add back up to a beat."""
    third = 1.0 / 3.0
    notes = [note(i * third, third, tuplet=(3, 2)) for i in range(3)]
    notes.append(note(1.0, 3.0))
    root = document(Notation(bars=[bar_of(notes)]))
    durations = [int(n.findtext("duration")) for n in root.find(".//measure").findall("note")]
    assert durations[:3] == [8, 8, 8]
    assert sum(durations) == 4 * DIVISIONS


def test_a_triplet_carries_its_time_modification_and_is_written_as_an_eighth():
    third = 1.0 / 3.0
    root = document(
        Notation(bars=[bar_of([note(0.0, third, tuplet=(3, 2)), note(third, 4 - third)])])
    )
    first = root.find(".//measure").find("note")
    assert first.findtext("type") == "eighth"
    modification = first.find("time-modification")
    assert modification.findtext("actual-notes") == "3"
    assert modification.findtext("normal-notes") == "2"


def test_a_tie_is_written_both_as_sound_and_as_notation():
    """MusicXML says a tie twice: <tie> is what sounds, <tied> is what is
    drawn. Readers disagree about which they honour, so a file with only one
    of them either warns or silently loses the tie."""
    notation = Notation(
        bars=[
            bar_of([note(0.0, 4.0, tie_start=True)], number=1),
            bar_of([note(0.0, 4.0, tie_stop=True)], number=2),
        ]
    )
    root = document(notation)
    first, second = root.findall(".//measure")
    assert first.find("note/tie").get("type") == "start"
    assert first.find("note/notations/tied").get("type") == "start"
    assert second.find("note/tie").get("type") == "stop"
    assert second.find("note/notations/tied").get("type") == "stop"


# ── transposition ────────────────────────────────────────────────────────


def test_the_key_signature_moves_with_the_part():
    """A tenor part in concert F is written in G. Transposing the notes but
    not the signature sounds correct and covers the page in accidentals —
    which is the kind of wrong that survives a listening test."""
    concert_f = Notation(bars=[bar_of([note(0.0, 4.0, pitch=65)])], key_fifths=-1, transpose=14)
    root = document(concert_f)
    assert root.find(".//key/fifths").text == "1"  # G major


def test_written_pitch_is_the_transposed_one():
    """Concert A3 (57) on a Bb tenor is written B4 (71)."""
    notation = Notation(bars=[bar_of([note(0.0, 4.0, pitch=57)])], key_fifths=-1, transpose=14)
    pitch = document(notation).find(".//note/pitch")
    assert pitch.findtext("step") == "B"
    assert pitch.findtext("octave") == "4"


def test_transpose_element_matches_the_real_instruments():
    """Written-to-sounding, reduced into an octave plus an octave count, which
    is what MusicXML wants and is not the same as the raw semitone count."""
    assert transpose_element(0) == (0, 0, 0)  # concert
    assert transpose_element(2) == (-1, -2, 0)  # Bb trumpet
    assert transpose_element(9) == (-5, -9, 0)  # Eb alto
    assert transpose_element(14) == (-1, -2, -1)  # Bb tenor: a major NINTH


def test_a_concert_part_has_no_transpose_element():
    root = document(Notation(bars=[bar_of([note(0.0, 4.0)])], transpose=0))
    assert root.find(".//transpose") is None


def test_fifths_shift_for_each_instrument():
    assert fifths_for_transpose(0) == 0
    assert fifths_for_transpose(2) == 2  # a major second is two fifths
    assert fifths_for_transpose(9) == 3  # a major sixth is three


# ── the rest ─────────────────────────────────────────────────────────────


def test_swing_is_marked_once_at_the_top():
    notation = Notation(bars=[bar_of([note(0.0, 4.0)], number=n) for n in (1, 2, 3)], swing=True)
    root = document(notation)
    words = root.findall(".//words")
    assert len(words) == 1
    assert words[0].text == "Swing"


def test_a_straight_score_is_not_marked_swing():
    root = document(Notation(bars=[bar_of([note(0.0, 4.0)])], swing=False))
    assert root.findall(".//words") == []


def test_rests_are_rests_and_carry_no_pitch():
    root = document(Notation(bars=[bar_of([note(0.0, 2.0), note(2.0, 2.0, is_rest=True)])]))
    notes = root.find(".//measure").findall("note")
    assert notes[1].find("rest") is not None
    assert notes[1].find("pitch") is None


def test_note_types():
    assert note_type(4.0) == ("whole", 0)
    assert note_type(1.5) == ("quarter", 1)
    assert note_type(0.5) == ("eighth", 0)
    assert note_type(0.125) == ("32nd", 0)


def test_an_empty_score_is_still_a_valid_document():
    root = document(Notation())
    assert root.tag == "score-partwise"
    assert root.find("part") is not None


def test_the_document_declares_itself_musicxml():
    xml = to_musicxml(Notation(bars=[bar_of([note(0.0, 4.0)])]))
    assert xml.startswith("<?xml version=")
    assert "score-partwise" in xml.split("\n")[1]  # the DOCTYPE


def test_a_single_voice_bar_writes_no_backup():
    """The common path must be byte-for-byte what it always was."""
    notation = Notation(
        title="One voice",
        bars=[
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[NotatedNote(beat=0.0, duration=4.0, pitch=60, step="C", octave=4)],
            )
        ],
    )
    xml = to_musicxml(notation)
    assert "<backup>" not in xml
    assert "<voice>1</voice>" in xml


def test_a_second_voice_is_rewound_to_the_barline():
    """MusicXML has no interleaved form: voice 2 must undo voice 1's advance
    with a <backup>, or it lands in the next bar."""
    notation = Notation(
        title="Two voices",
        bars=[
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[
                    NotatedNote(beat=0.0, duration=2.0, pitch=72, step="C", octave=5),
                    NotatedNote(beat=2.0, duration=2.0, pitch=74, step="D", octave=5),
                    NotatedNote(beat=0.0, duration=4.0, pitch=60, step="C", octave=4, voice=2),
                ],
            )
        ],
    )
    xml = to_musicxml(notation)
    assert "<voice>2</voice>" in xml
    # Rewound by the whole bar: two half notes at 24 divisions per quarter.
    assert "<backup>" in xml
    assert f"<duration>{4 * DIVISIONS}</duration>" in xml.split("<backup>")[1]
    # And voice 1 is written before voice 2.
    assert xml.index("<voice>1</voice>") < xml.index("<backup>") < xml.index("<voice>2</voice>")


def test_voices_are_grouped_not_interleaved():
    from swingscribe.stages.export import voices_of

    bar = NotatedBar(
        number=1,
        time_signature=(4, 4),
        notes=[
            NotatedNote(beat=0.0, duration=1.0, pitch=72, voice=1),
            NotatedNote(beat=0.0, duration=1.0, pitch=60, voice=2),
            NotatedNote(beat=1.0, duration=1.0, pitch=74, voice=1),
        ],
    )
    numbers = [n for n, _notes in voices_of(bar)]
    assert numbers == [1, 2]
    assert [n.pitch for n in voices_of(bar)[0][1]] == [72, 74]
    assert [n.pitch for n in voices_of(bar)[1][1]] == [60]
