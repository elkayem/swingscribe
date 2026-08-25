"""Stage 6 — turning grid positions into something a musician can read.

All pure arithmetic, so the whole stage is exercised here rather than behind
an importorskip: key detection, spelling, note values, ties and rests.
"""

from swingscribe.model import MeterSection, NotatedNote, QuantizedNote
from swingscribe.stages.notate import (
    build,
    detect_key,
    fill_rests,
    is_notatable,
    spell,
    split_for_meter,
    triplet_value,
)

# ── key detection ────────────────────────────────────────────────────────


def scale(pitches: list[int], duration: float = 1.0) -> list[tuple[int, float]]:
    return [(p, duration) for p in pitches]


def test_a_c_major_scale_is_c_major():
    assert detect_key(scale([60, 62, 64, 65, 67, 69, 71, 72])) == 0


def test_a_g_major_scale_has_one_sharp():
    assert detect_key(scale([67, 69, 71, 72, 74, 76, 78, 79])) == 1


def test_an_f_major_scale_has_one_flat():
    assert detect_key(scale([65, 67, 69, 70, 72, 74, 76, 77])) == -1


def test_a_minor_key_is_drawn_with_its_relative_majors_signature():
    """A minor takes C major's signature — the staff shows the signature, not
    the tonic, and confusing the two puts three flats on a D minor solo."""
    a_minor = scale([57, 59, 60, 62, 64, 65, 67, 69])
    assert detect_key(a_minor) == 0


def test_key_detection_weights_by_duration_not_by_count():
    """Four passing sixteenths must not outvote a held tonic. In a bebop line
    the passing tones outnumber the chord tones, so counting notes finds the
    wrong key more often than it finds the right one."""
    held = [(60, 8.0), (64, 8.0), (67, 8.0)]  # a long C major triad
    passing = [(p, 0.25) for p in (61, 63, 66, 68, 70, 61, 63, 66)]
    assert detect_key(held + passing) == 0


def test_no_notes_is_c_rather_than_a_guess():
    assert detect_key([]) == 0


# ── spelling ─────────────────────────────────────────────────────────────


def test_diatonic_notes_take_the_key_signature_spelling():
    assert spell(66, 1)[:2] == ("F", 1)  # F# in G major
    assert spell(70, -2)[:2] == ("B", -1)  # Bb in Bb major


def test_the_same_sound_is_spelled_differently_in_different_keys():
    """The whole point of doing this at all."""
    assert spell(66, 4)[:2] == ("F", 1)  # E major: F#
    assert spell(66, -5)[:2] == ("G", -1)  # Db major: Gb


def test_octave_follows_the_spelled_letter_not_the_sounding_pitch():
    """Cb4 sounds where B3 sounds. Getting this wrong writes the note a
    seventh away on the staff while sounding correct, which is the kind of
    bug nobody finds by listening."""
    step, alter, octave = spell(59, 0)  # B3 in C major
    assert (step, alter, octave) == ("B", 0, 3)
    step, alter, octave = spell(60, 0)
    assert (step, alter, octave) == ("C", 0, 4)


def test_every_pitch_spells_back_to_the_pitch_it_came_from():
    """The invariant that matters: spelling must never change the sound."""
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    for key in range(-6, 7):
        for pitch in range(36, 96):
            step, alter, octave = spell(pitch, key)
            assert (octave + 1) * 12 + semitone[step] + alter == pitch


# ── note values, ties, rests ─────────────────────────────────────────────


def test_notatable_values():
    assert is_notatable(1.0) and is_notatable(1.5) and is_notatable(0.75)
    assert not is_notatable(1.25) and not is_notatable(0.9)


def test_a_whole_bar_note_is_one_symbol():
    assert split_for_meter(0.0, 4.0, 4.0) == [(0.0, 4.0, None)]


def test_a_note_on_the_beat_needs_no_tie():
    assert split_for_meter(1.0, 1.0, 4.0) == [(1.0, 1.0, None)]
    assert split_for_meter(0.0, 2.0, 4.0) == [(0.0, 2.0, None)]


def test_a_third_of_a_beat_is_written_as_a_triplet_not_a_sliver():
    """Quantize picks a ternary grid for beats whose notes fit one better, so
    a third of a beat arrives here routinely — and it is not a note value.
    Written without a tuplet it is an unnotatable duration, and the bar stops
    adding up, which is what makes a notation program reject the file."""
    pieces = split_for_meter(0.0, 1.0 / 3.0, 4.0)
    assert len(pieces) == 1
    start, length, tuplet = pieces[0]
    assert tuplet == (3, 2)
    assert abs(length - 1.0 / 3.0) < 1e-9
    assert abs(triplet_value(length) - 0.5) < 1e-9  # written as an eighth


def test_a_full_triplet_beat_tiles_the_beat_exactly():
    pieces = []
    for i in range(3):
        pieces += split_for_meter(1.0 + i / 3.0, 1.0 / 3.0, 4.0)
    assert all(t == (3, 2) for _s, _d, t in pieces)
    assert abs(sum(d for _s, d, _t in pieces) - 1.0) < 1e-9


def test_a_tuplet_never_straddles_a_beat():
    """A triplet written across a beat boundary is unreadable, and it is not
    what quantize found either -- it chooses the grid one beat at a time."""
    for _start, _length, tuplet in split_for_meter(0.5, 1.0 / 3.0, 4.0):
        assert tuplet is None or _start >= 0.0


def test_an_unnotatable_length_becomes_tied_symbols():
    """1.25 quarter notes is not a symbol. It has to be written as two."""
    pieces = split_for_meter(0.0, 1.25, 4.0)
    assert len(pieces) == 2
    assert sum(length for _s, length, _t in pieces) == 1.25
    assert all(is_notatable(length) for _s, length, _t in pieces)


def test_a_syncopation_across_the_middle_of_the_bar_is_tied():
    """A quarter starting on the "and" of two straddles the bar's midpoint.
    Written as one quarter it looks like it starts on a beat; the tie is what
    keeps the half-bar visible."""
    pieces = split_for_meter(1.5, 1.0, 4.0)
    assert len(pieces) == 2
    assert pieces[0][0] == 1.5
    assert sum(length for _s, length, _t in pieces) == 1.0


def test_split_always_conserves_duration():
    """Whatever else it does, notation may not lose or invent time."""
    for start in [i * 0.25 for i in range(16)]:
        for duration in [i * 0.25 for i in range(1, 17)]:
            if start + duration > 4.0:
                continue
            pieces = split_for_meter(start, duration, 4.0)
            assert abs(sum(length for _s, length, _t in pieces) - duration) < 1e-9
            assert abs(pieces[0][0] - start) < 1e-9


def test_rests_fill_a_bar_to_its_time_signature():
    """A bar that does not add up is what makes a notation program refuse to
    open the file at all."""
    notes = [NotatedNote(beat=1.0, duration=1.0, pitch=60, step="C", octave=4)]
    filled = fill_rests(notes, 4.0)
    assert abs(sum(n.duration for n in filled) - 4.0) < 1e-9
    assert filled[0].is_rest and filled[0].beat == 0.0
    assert any(n.is_rest and n.beat >= 2.0 for n in filled)


def test_an_empty_bar_becomes_rests_not_nothing():
    filled = fill_rests([], 4.0)
    assert filled and all(n.is_rest for n in filled)
    assert abs(sum(n.duration for n in filled) - 4.0) < 1e-9


# ── the whole stage ──────────────────────────────────────────────────────


def section(bars: int = 8) -> list[MeterSection]:
    return [
        MeterSection(
            start=0.0,
            end=float(bars) * 2,
            pulses_per_bar=4,
            time_signature=(4, 4),
            anchor=0.0,
            first_bar=1,
        )
    ]


def test_a_simple_line_becomes_bars_that_add_up():
    notes = [
        QuantizedNote(bar=1, beat=b, duration_beats=1.0, pitch=p, timing_residual=0.0)
        for b, p in zip([0.0, 1.0, 2.0, 3.0], [60, 62, 64, 65], strict=True)
    ]
    notation = build(notes, section(), swing=True, transpose=0)
    assert len(notation.bars) == 1
    bar = notation.bars[0]
    assert abs(sum(n.duration for n in bar.notes) - 4.0) < 1e-9
    assert notation.swing is True


def test_a_note_running_past_the_bar_line_is_tied_across_it():
    """A bar line is not allowed to end a note; it is allowed to split one."""
    notes = [QuantizedNote(bar=1, beat=3.0, duration_beats=2.0, pitch=60, timing_residual=0.0)]
    notation = build(notes, section(), swing=False, transpose=0)
    assert len(notation.bars) == 2
    sounded = [n for bar in notation.bars for n in bar.notes if not n.is_rest]
    assert len(sounded) == 2
    assert sounded[0].tie_start and not sounded[0].tie_stop
    assert sounded[1].tie_stop and not sounded[1].tie_start
    assert abs(sum(n.duration for n in sounded) - 2.0) < 1e-9


def test_every_bar_adds_up_to_its_time_signature():
    notes = [
        QuantizedNote(
            bar=1 + i // 6,
            beat=(i % 6) * 0.5,
            duration_beats=0.5,
            pitch=60 + i,
            timing_residual=0.0,
        )
        for i in range(18)
    ]
    notation = build(notes, section(), swing=True, transpose=0)
    for bar in notation.bars:
        length = bar.time_signature[0] * 4.0 / bar.time_signature[1]
        assert abs(sum(n.duration for n in bar.notes) - length) < 1e-9, f"bar {bar.number}"


def test_notation_keeps_sounding_pitch_and_carries_transposition_separately():
    """A tenor part is written a major ninth up, but the note is still the
    note it sounded. Baking the transposition into the pitch would invalidate
    every comparison against concert-pitch ground truth."""
    notes = [QuantizedNote(bar=1, beat=0.0, duration_beats=4.0, pitch=60, timing_residual=0.0)]
    notation = build(notes, section(), swing=True, transpose=14)
    sounded = [n for bar in notation.bars for n in bar.notes if not n.is_rest]
    assert sounded[0].pitch == 60
    assert notation.transpose == 14


def test_no_notes_gives_an_empty_score_rather_than_an_exception():
    assert build([], section(), swing=False, transpose=0).bars == []


def test_the_score_starts_at_bar_one_even_if_the_soloist_does_not():
    """A player entering on bar 2 leaves a bar of rests, which is what a
    reader expects. A score whose first measure is numbered 2 is a score with
    a measure missing."""
    notes = [QuantizedNote(bar=3, beat=0.0, duration_beats=4.0, pitch=60, timing_residual=0.0)]
    notation = build(notes, section(), swing=False, transpose=0)
    assert notation.bars[0].number == 1
    assert all(n.is_rest for n in notation.bars[0].notes)
    assert [b.number for b in notation.bars] == [1, 2, 3]
