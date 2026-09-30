"""Our page and a reference score in MV2H's text format (swingscribe.mv2h,
docs/mv2h.md).

The Java tool is a download and never runs in CI; what runs here is
everything that decides what MV2H is handed. The expected lines are the ones
MV2H's own MIDI converter printed for the same scores (2026-09-30, MV2H at
79155847, compared line for line on a 4/4 and a 3/4 score, both pinned
below), so a change that breaks the correspondence fails here rather than
in a number.
"""

import pytest

from swingscribe.evaluation import PageBar
from swingscribe.model import NotatedBar, NotatedNote, Notation
from swingscribe.mscz import Score, ScoreNote
from swingscribe.mv2h import (
    Bar,
    Side,
    earliest,
    grid_shift,
    hierarchy,
    lines,
    notation_side,
    parse_output,
    score_side,
    signature_of,
    with_keys_agreed,
)


def _note(beat, duration, pitch, **flags):
    return NotatedNote(beat=beat, duration=duration, pitch=pitch, **flags)


def _rest(beat, duration):
    return NotatedNote(beat=beat, duration=duration, is_rest=True)


def test_time_signatures_are_read_the_way_mv2h_reads_them():
    # (beats per bar, sub-beats per beat, quarters per sub-beat), from MV2H's
    # tools/midi/TimeSignature: compound only above three and by threes.
    assert hierarchy(4, 4) == (4, 2, 0.5)
    assert hierarchy(3, 4) == (3, 2, 0.5)
    assert hierarchy(2, 2) == (2, 2, 1.0)
    assert hierarchy(6, 8) == (2, 3, 0.5)
    assert hierarchy(12, 8) == (4, 3, 0.5)
    assert hierarchy(3, 8) == (3, 2, 0.25)


def test_a_bar_known_only_by_its_length_gets_a_signature():
    assert signature_of(4.0) == (4, 4)
    assert signature_of(3.0) == (3, 4)
    assert signature_of(2.5) == (5, 8)


def test_a_four_four_score_is_written_as_mv2hs_converter_writes_it():
    """The 4/4 check score -- B-flat, eighths, a triplet, sixteenths and two
    rests over three bars -- line for line as MV2H's MIDI converter printed
    it for the same notes at 120 bpm."""
    third = 1.0 / 3.0
    side = Side(
        notes=[
            (0.0, 0.5, 70),
            (0.5, 0.5, 72),
            (1.0, third, 74),
            (1.0 + third, third, 75),
            (1.0 + 2 * third, third, 77),
            (2.0, 1.5, 79),
            (3.5, 0.5, 77),
            (4.0, 0.25, 75),
            (4.25, 0.25, 74),
            (4.5, 1.0, 72),  # an eighth rest follows
            (6.0, 2.0, 70),
            (8.0, 3.0, 65),  # a quarter rest closes the last bar
        ],
        bars=[Bar(0.0, 4.0, 4, 4), Bar(4.0, 4.0, 4, 4), Bar(8.0, 4.0, 4, 4)],
        key_tonic=(7 * -2) % 12,
    )
    expected = {
        "Hierarchy 4,2 1 a=0 0",
        "Key 10 Maj 0",
        "Note 70 0 0 250 0",
        "Note 72 250 250 500 0",
        "Note 74 500 500 667 0",
        "Note 75 667 667 833 0",
        "Note 77 833 833 1000 0",
        "Note 79 1000 1000 1750 0",
        "Note 77 1750 1750 2000 0",
        "Note 75 2000 2000 2125 0",
        "Note 74 2125 2125 2250 0",
        "Note 72 2250 2250 2750 0",
        "Note 70 3000 3000 4000 0",
        "Note 65 4000 4000 5500 0",
        *(f"Tatum {t}" for t in range(0, 6001, 250)),
    }
    out = lines(side)
    assert set(out) == expected
    assert len(out) == len(expected)


def test_a_three_four_score_is_written_as_mv2hs_converter_writes_it():
    """The 3/4 check score, line for line as MV2H's MIDI converter printed
    it for the same notes at 120 bpm (G major)."""
    side = Side(
        notes=[(0.0, 1.0, 67), (1.0, 0.5, 69), (1.5, 0.5, 71), (2.0, 1.0, 72), (3.0, 3.0, 74)],
        bars=[Bar(0.0, 3.0, 3, 4), Bar(3.0, 3.0, 3, 4)],
        key_tonic=7,
    )
    expected = {
        "Hierarchy 3,2 1 a=0 0",
        "Key 7 Maj 0",
        "Note 67 0 0 500 0",
        "Note 69 500 500 750 0",
        "Note 71 750 750 1000 0",
        "Note 72 1000 1000 1500 0",
        "Note 74 1500 1500 3000 0",
        *(f"Tatum {t}" for t in range(0, 3001, 250)),
    }
    out = lines(side)
    assert set(out) == expected
    assert len(out) == len(expected)  # no tatum written twice


def test_a_triplet_rounds_to_the_millisecond_as_the_converter_does():
    third = 1.0 / 3.0
    side = Side([(1.0, third, 74), (1.0 + third, third, 75)], [Bar(0.0, 4.0, 4, 4)], None)
    notes = [line for line in lines(side) if line.startswith("Note")]
    assert notes == ["Note 74 500 500 667 0", "Note 75 667 667 833 0"]


def test_shift_and_tempo_move_every_time_together():
    side = Side([(0.5, 0.5, 60)], [Bar(0.0, 4.0, 4, 4)], 0)
    out = lines(side, shift=4.0, ms_per_quarter=250)
    assert "Note 60 1125 1125 1250 0" in out
    assert "Hierarchy 4,2 1 a=0 1000" in out
    assert "Key 0 Maj 1000" in out
    assert out[-2:] == ["Tatum 2000", "Key 0 Maj 1000"]


def test_a_negative_time_is_refused():
    """MV2H's grouping code uses -1 for "not started"."""
    side = Side([(0.0, 1.0, 60)], [Bar(0.0, 4.0, 4, 4)], 0)
    with pytest.raises(ValueError):
        lines(side, shift=-1.0)
    assert earliest(side) == 0.0


def test_an_irregular_bar_restarts_the_count_on_both_sides_of_it():
    """An overfull OMR bar: MV2H's format restarts the bar count at every
    Hierarchy, so one is written where the bar starts and one after it."""
    side = Side([], [Bar(0.0, 4.0, 4, 4), Bar(4.0, 4.5, 4, 4), Bar(8.5, 4.0, 4, 4)], None)
    hierarchies = [line for line in lines(side) if line.startswith("Hierarchy")]
    assert hierarchies == [
        "Hierarchy 4,2 1 a=0 0",
        "Hierarchy 4,2 1 a=0 2000",
        "Hierarchy 4,2 1 a=0 4250",
    ]


def test_a_signature_change_writes_a_new_hierarchy():
    side = Side([], [Bar(0.0, 4.0, 4, 4), Bar(4.0, 3.0, 3, 4), Bar(7.0, 3.0, 3, 4)], None)
    hierarchies = [line for line in lines(side) if line.startswith("Hierarchy")]
    assert hierarchies == ["Hierarchy 4,2 1 a=0 0", "Hierarchy 3,2 1 a=0 2000"]


def test_our_page_is_the_notes_every_page_measure_reads_transposed_with_its_key():
    """Ties merged, rests dropped (`benchmark.notation_notes`), the measured
    transposition applied to the pitches AND to the key signature."""
    notation = Notation(
        key_fifths=-2,  # B-flat major
        bars=[
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[_note(0.0, 1.0, 70), _rest(1.0, 1.0), _note(2.0, 2.0, 72, tie_start=True)],
            ),
            NotatedBar(
                number=2,
                time_signature=(4, 4),
                notes=[_note(0.0, 1.0, 72, tie_stop=True), _note(1.0, 3.0, 74)],
            ),
        ],
    )
    side = notation_side(notation, transpose=12)
    assert side.notes == [(0.0, 1.0, 82), (2.0, 3.0, 84), (5.0, 3.0, 86)]
    assert side.bars == [Bar(0.0, 4.0, 4, 4), Bar(4.0, 4.0, 4, 4)]
    assert side.key_tonic == 10  # an octave moves no key
    assert notation_side(notation, transpose=2).key_tonic == 0  # up a tone: C


def test_a_double_time_page_is_read_at_true_meter():
    notation = Notation(
        double_time=True,
        bars=[
            NotatedBar(
                number=1, time_signature=(4, 4), notes=[_note(0.0, 2.0, 60), _note(2.0, 2.0, 62)]
            )
        ],
    )
    side = notation_side(notation)
    assert side.notes == [(0.0, 1.0, 60), (1.0, 1.0, 62)]
    assert side.bars == [Bar(0.0, 2.0, 4, 8)]
    beats, sub_beats, sub_length = hierarchy(4, 8)
    assert beats * sub_beats * sub_length == 2.0


def _score(melody, bars, beats_per_bar=4.0, key_fifths=0):
    notes = [ScoreNote(position=p, duration=d, pitch=n, bar=1) for p, d, n in melody]
    return Score("t", notes, notes, bars, beats_per_bar, key_fifths)


def test_a_reference_has_a_bar_every_signature_from_its_start():
    score = _score([(0.0, 1.0, 60), (7.0, 2.0, 62)], bars=2, beats_per_bar=4.0, key_fifths=1)
    side = score_side(score)
    assert side.notes == [(0.0, 1.0, 60), (7.0, 2.0, 62)]
    # A note held past the last bar line still gets a bar under it.
    assert side.bars == [Bar(0.0, 4.0, 4, 4), Bar(4.0, 4.0, 4, 4), Bar(8.0, 4.0, 4, 4)]
    assert side.key_tonic == 7


def test_a_pages_bars_are_where_the_score_reader_put_them():
    score = _score([(0.0, 1.0, 60)], bars=2)
    bars = [PageBar("1", 0.0, 4.5, 4.0), PageBar("2", 4.5, 4.0, 4.0)]
    side = score_side(score, bars)
    assert side.bars == [Bar(0.0, 4.5, 4, 4), Bar(4.5, 4.0, 4, 4)]


def test_the_grid_shift_is_a_vote_of_the_matched_notes():
    ours = [(0.0, 0.5, 60), (0.5, 0.5, 62), (1.0, 0.5, 64), (2.0, 0.5, 65), (3.0, 1.0, 67)]
    # The reference is our page sixteen beats later, with one note written an
    # eighth late, one wrong pitch, and one note we did not play.
    theirs = [
        (16.0, 0.5, 60),
        (16.5, 0.5, 62),
        (17.5, 0.5, 64),
        (18.0, 0.5, 66),
        (19.0, 1.0, 67),
        (20.0, 1.0, 69),
    ]
    pairs = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, None)]
    shift, share = grid_shift(ours, theirs, pairs)
    assert shift == 16.0
    assert share == pytest.approx(3 / 4)  # the late note is off; the wrong pitch never voted


def test_a_tied_vote_takes_the_smaller_shift_and_nothing_matched_is_zero():
    ours = [(0.0, 1.0, 60), (1.0, 1.0, 62)]
    theirs = [(4.0, 1.0, 60), (-3.0, 1.0, 62)]
    assert grid_shift(ours, theirs, [(0, 0), (1, 1)])[0] == -4.0
    assert grid_shift(ours, theirs, [(0, None), (None, 1)]) == (0.0, 0.0)


MAIN_A_OUTPUT = (
    "Evaluating alignment 1 / 80\rEvaluating alignment 2 / 80\r\n"
    "Multi-pitch: 0.9457364341085273\n"
    "Voice: 1.0\n"
    "Meter: 0.7564102564102565\n"
    "Value: 0.912590163934426\n"
    "Harmony: 1.0\n"
    "MV2H: 0.922947370890642\n"
)


def test_mv2hs_own_output_is_read_with_its_alignment_count():
    out = parse_output(MAIN_A_OUTPUT)
    assert out["mv2h"] == pytest.approx(0.922947370890642)
    assert out["meter"] == pytest.approx(0.7564102564102565)
    assert out["alignments"] == 80.0


def test_the_drivers_extra_lines_are_read_too():
    text = (
        "Most matches: 246\nWith most matches: 491520\nAlignments: 1228800\n"
        "Evaluated: 2500 sampled\nBest from: most-matches\nWorst: 0.76\n"
        + MAIN_A_OUTPUT.split("\r\n", 1)[1]
    )
    out = parse_output(text)
    assert out["how"] == "sampled"
    assert out["evaluated"] == 2500.0
    assert out["alignments"] == 1228800.0
    assert out["with_most_matches"] == 491520.0
    assert out["best_from"] == "most-matches"
    assert out["worst"] == 0.76


def test_a_reading_against_one_shared_ground_truth_says_so():
    """`--shared-truth` reproduces MV2H's own -a, whose meter is consumed by
    the first alignment it scores: the output must carry the mark."""
    text = "Alignments: 48\nEvaluated: 48 all-shared\nBest from: all\nWorst: 0.7\n"
    out = parse_output(text + MAIN_A_OUTPUT.split("\r\n", 1)[1])
    assert out["how"] == "all-shared"
    assert out["best_from"] == "all"


def test_agreeing_the_key_replaces_harmony_alone():
    """Harmony is the key signature here and no other component reads it,
    so MV2H with the reference's key is the other four plus a one."""
    out = parse_output(MAIN_A_OUTPUT)
    out["harmony"] = 0.0
    expected = (0.9457364341085273 + 1.0 + 0.7564102564102565 + 0.912590163934426 + 1.0) / 5
    assert with_keys_agreed(out) == pytest.approx(expected)
    # Where the keys already agree it is MV2H's own number.
    assert with_keys_agreed(parse_output(MAIN_A_OUTPUT)) == pytest.approx(0.922947370890642)


def test_an_answer_missing_a_component_is_refused():
    with pytest.raises(ValueError):
        parse_output("Multi-pitch: 0.5\nMV2H: 0.5\n")
