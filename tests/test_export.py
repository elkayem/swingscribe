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
    tuplet_groups,
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
    """DIVISIONS is chosen so a third of a beat is an integer. At 12 or 16 it
    is not, and three of them do not add back up to a beat."""
    third = 1.0 / 3.0
    notes = [note(i * third, third, tuplet=(3, 2)) for i in range(3)]
    notes.append(note(1.0, 3.0))
    root = document(Notation(bars=[bar_of(notes)]))
    durations = [int(n.findtext("duration")) for n in root.find(".//measure").findall("note")]
    assert durations[:3] == [DIVISIONS // 3] * 3
    assert sum(durations) == 4 * DIVISIONS


def test_a_quintuplet_beat_sums_exactly_with_no_rounding():
    """DIVISIONS must also be divisible by 5: WJazzD annotates beats divided
    into 5 (and 7), and a quintuplet whose five pieces do not sum back to a
    whole beat is the same corrupt-file failure the triplet case guards."""
    fifth = 1.0 / 5.0
    notes = [note(i * fifth, fifth, tuplet=(5, 4)) for i in range(5)]
    notes.append(note(1.0, 3.0))
    root = document(Notation(bars=[bar_of(notes)]))
    durations = [int(n.findtext("duration")) for n in root.find(".//measure").findall("note")]
    assert durations[:5] == [DIVISIONS // 5] * 5
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


def test_a_quintuplet_carries_its_time_modification_and_is_written_as_a_16th():
    fifth = 1.0 / 5.0
    root = document(
        Notation(bars=[bar_of([note(0.0, fifth, tuplet=(5, 4)), note(fifth, 4 - fifth)])])
    )
    first = root.find(".//measure").find("note")
    assert first.findtext("type") == "16th"
    modification = first.find("time-modification")
    assert modification.findtext("actual-notes") == "5"
    assert modification.findtext("normal-notes") == "4"


def test_tuplet_groups_split_on_a_change_of_ratio():
    """A triplet followed directly by a quintuplet in the same beat must be two
    brackets, not one claiming a ratio that fits neither run."""
    third = 1.0 / 3.0
    fifth = 1.0 / 5.0
    notes = [
        note(0.0, third, tuplet=(3, 2)),
        note(third, third, tuplet=(3, 2)),
        note(2 * third, third, tuplet=(3, 2)),
        note(1.0, fifth, tuplet=(5, 4)),
        note(1.0 + fifth, fifth, tuplet=(5, 4)),
        note(1.0 + 2 * fifth, fifth, tuplet=(5, 4)),
        note(1.0 + 3 * fifth, fifth, tuplet=(5, 4)),
        note(1.0 + 4 * fifth, fifth, tuplet=(5, 4)),
    ]
    marks = tuplet_groups(notes)
    assert marks == {0: "start", 2: "stop", 3: "start", 7: "stop"}


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


# ── chords ──────────────────────────────────────────────────────────────────


def test_a_chord_is_the_head_note_followed_by_chord_marked_notes():
    """MusicXML's chord is positional: the head advances the cursor, each
    following <chord/> note repeats its duration and advances nothing. The
    measure must still sum to its signature counting only the heads."""
    notation = Notation(
        bars=[bar_of([note(0.0, 1.0, 78, chord=[84, 82]), note(1.0, 3.0, 75)])],
        key_fifths=0,
    )
    measure = document(notation).find(".//measure")
    notes = measure.findall("note")
    assert [n.find("chord") is not None for n in notes] == [False, True, True, False]
    # Steps only; the alters (F#, Bb, Eb) are checked by the spelling tests.
    assert [n.findtext("pitch/step") + n.findtext("pitch/octave") for n in notes] == [
        "F5",
        "B5",
        "C6",
        "E5",
    ]
    assert [int(n.findtext("duration")) for n in notes] == [DIVISIONS] * 3 + [3 * DIVISIONS]
    heads = [n for n in notes if n.find("chord") is None]
    assert sum(int(n.findtext("duration")) for n in heads) == 4 * DIVISIONS


def test_chord_members_repeat_the_heads_type_tie_and_tuplet_but_not_its_bracket():
    tied = note(0.0, 1.0, 78, chord=[84], tie_start=True, tuplet=(3, 2))
    notation = Notation(bars=[bar_of([tied, note(1.0, 3.0, 75)])])
    notes = document(notation).find(".//measure").findall("note")
    head, member = notes[0], notes[1]
    assert member.findtext("type") == head.findtext("type")
    assert member.find("tie").get("type") == "start"
    assert member.findtext("time-modification/actual-notes") == "3"
    assert head.find("notations/tuplet") is not None
    assert member.find("notations/tuplet") is None


def test_our_chord_reads_back_through_the_musicxml_reader(tmp_path):
    """mscz.parse_musicxml already understands <chord/>: the member lands at
    the head's position, and the melody view keeps the top note."""
    from swingscribe import mscz

    notation = Notation(bars=[bar_of([note(0.0, 1.0, 78, chord=[84]), note(1.0, 3.0, 75)])])
    path = tmp_path / "chord.musicxml"
    path.write_text(to_musicxml(notation), encoding="utf-8")
    score = mscz.parse_musicxml(path)
    assert sorted((n.position, n.pitch) for n in score.notes) == [(0.0, 78), (0.0, 84), (1.0, 75)]
    assert [n.pitch for n in score.melody] == [84, 75]


def test_a_quarter_note_triplet_is_one_bracket_over_two_beats():
    """The group passes the beat line at four thirds; its own length, not
    the beat line, closes it. The beat-level triplet after it is its own."""
    two_thirds = 2.0 / 3.0
    third = 1.0 / 3.0
    notes = [
        note(0.0, two_thirds, tuplet=(3, 2)),
        note(two_thirds, two_thirds, tuplet=(3, 2)),
        note(2 * two_thirds, two_thirds, tuplet=(3, 2)),
        note(2.0, third, tuplet=(3, 2)),
        note(2.0 + third, third, tuplet=(3, 2)),
        note(2.0 + 2 * third, third, tuplet=(3, 2)),
    ]
    assert tuplet_groups(notes) == {0: "start", 2: "stop", 3: "start", 5: "stop"}


def test_two_triplet_beats_are_still_two_brackets():
    third = 1.0 / 3.0
    notes = [note(k * third, third, tuplet=(3, 2)) for k in range(6)]
    assert tuplet_groups(notes) == {0: "start", 2: "stop", 3: "start", 5: "stop"}
