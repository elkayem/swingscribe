"""Stage 6 — turning grid positions into something a musician can read.

All pure arithmetic, so the whole stage is exercised here rather than behind
an importorskip: key detection, spelling, note values, ties and rests.
"""

import pytest

from swingscribe.model import MeterSection, NotatedNote, QuantizedNote
from swingscribe.stages import notate
from swingscribe.stages.notate import (
    build,
    detect_key,
    fill_rests,
    is_notatable,
    spell,
    split_for_meter,
    split_points,
    triplet_value,
    tuplet_value,
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


def test_a_fifth_of_a_beat_is_written_as_a_quintuplet():
    """WJazzD annotates beats divided into 5 (and 7): a division this notater
    had no tuplet for used to fall through to a tied chain of binary slivers,
    which is where the tied-32nds bug came from -- see docs on TUPLET_RATIOS."""
    pieces = split_for_meter(0.0, 1.0 / 5.0, 4.0)
    assert len(pieces) == 1
    _start, length, tuplet = pieces[0]
    assert tuplet == (5, 4)
    assert abs(length - 1.0 / 5.0) < 1e-9
    assert abs(tuplet_value(length, (5, 4)) - 0.25) < 1e-9  # written as a 16th


def test_a_full_quintuplet_beat_tiles_the_beat_exactly():
    pieces = []
    for i in range(5):
        pieces += split_for_meter(1.0 + i / 5.0, 1.0 / 5.0, 4.0)
    assert all(t == (5, 4) for _s, _d, t in pieces)
    assert abs(sum(d for _s, d, _t in pieces) - 1.0) < 1e-9


def test_a_seventh_of_a_beat_is_written_as_a_septuplet():
    pieces = split_for_meter(0.0, 1.0 / 7.0, 4.0)
    assert len(pieces) == 1
    _start, length, tuplet = pieces[0]
    assert tuplet == (7, 4)
    assert abs(tuplet_value(length, (7, 4)) - 0.25) < 1e-9  # written as a 16th


def test_an_unnotatable_length_becomes_tied_symbols():
    """1.25 quarter notes is not a symbol. It has to be written as two."""
    pieces = split_for_meter(0.0, 1.25, 4.0)
    assert len(pieces) == 2
    assert sum(length for _s, length, _t in pieces) == 1.25
    assert all(is_notatable(length) for _s, length, _t in pieces)


def test_a_symmetric_syncopation_is_one_symbol():
    """OVERTURNED (D14): this test used to assert the tie. A quarter on any
    "and" is centred on the division it crosses — the jazz syncopation every
    lead sheet writes whole — and the hand transcriptions' tie rate (0.022,
    against our 0.098 with 58% of ties WITHIN the bar) says the listener
    writes it whole too. The conservative tie survives where it earns its
    keep: values NOT centred on what they cross, and triple metre."""
    pieces = split_for_meter(1.5, 1.0, 4.0)
    assert pieces == [(1.5, 1.0, None)]


def test_an_uncentred_crossing_still_ties():
    """A quarter starting on an offbeat sixteenth is not symmetric about
    anything — written whole it genuinely misleads, so it still splits."""
    pieces = split_for_meter(1.75, 1.0, 4.0)
    assert len(pieces) >= 2
    assert sum(length for _s, length, _t in pieces) == 1.0


def test_a_dotted_quarter_on_a_beat_is_one_symbol():
    """The other idiomatic syncopation (D14): a dotted quarter starting on
    its own dot-grid — beat two, or the charleston's and-of-one — is written
    whole on every chart. Off the dot-grid it still ties."""
    assert split_for_meter(1.0, 1.5, 4.0) == [(1.0, 1.5, None)]
    assert len(split_for_meter(0.75, 1.5, 4.0)) >= 2


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


# ── short gaps: the rests that are not rests ────────────────────────────────


class _FlatBars:
    """Every bar four quarters long, so `start_of` is just arithmetic."""

    def start_of(self, bar: int) -> float:
        return (bar - 1) * 4.0


def test_close_short_gaps_fills_a_sub_sixteenth_gap():
    """A note quantized to a sixteenth in a beat whose next onset is a third of
    a beat away leaves a twelfth-of-a-beat hole. That hole is what breaks the
    tuplet group, and no transcriber can hear a rest that short."""
    events = [(1, 0.0, 0.25, 60), (1, 1.0 / 3.0, 1.0 / 3.0, 62)]
    out = notate.close_short_gaps(events, _FlatBars())
    assert out[0][2] == pytest.approx(1.0 / 3.0)
    assert out[1] == events[1]


def test_a_sixteenth_of_silence_is_a_lay_back_not_a_rest():
    """The listener wrote ONE sixteenth rest in 504 across ten transcriptions.
    A player behind the beat leaves a sixteenth of silence before every
    offbeat, and writing that down records the feel as a rhythm."""
    events = [(1, 0.0, 0.25, 60), (1, 0.5, 0.5, 62)]
    out = notate.close_short_gaps(events, _FlatBars())
    assert out[0][2] == pytest.approx(0.5)
    assert out[1] == events[1]


def test_an_eighth_rest_is_a_rest():
    """The rule is bounded by a note value, not by a ratio - that is the whole
    difference from legato_fill."""
    events = [(1, 0.0, 0.5, 60), (1, 1.0, 0.5, 62)]
    assert notate.close_short_gaps(events, _FlatBars()) == events


def test_close_short_gaps_never_shortens():
    """A note already reaching the next onset — or past it, which
    `without_overlap` has usually already trimmed — is not touched."""
    events = [(1, 0.0, 1.0, 60), (1, 1.0, 1.0, 62)]
    assert notate.close_short_gaps(events, _FlatBars()) == events


def test_close_short_gaps_crosses_a_bar_line():
    """The gap is measured in absolute time, so the last note of a bar and the
    first of the next are adjacent like any other pair."""
    events = [(1, 3.0, 0.9, 60), (2, 0.0, 1.0, 62)]
    out = notate.close_short_gaps(events, _FlatBars())
    assert out[0][2] == pytest.approx(1.0)


def test_short_gaps_leave_a_notatable_tuplet_group():
    """The regression this exists for: MuseScore called Yesterdays corrupted
    because seven beats held a plain sixteenth beside a twelfth-of-a-beat
    triplet rest, so the group began off the thirds. Every piece of a beat
    holding a tuplet must land on a sixth of that beat."""
    quantized = [
        _q(bar=1, beat=0.0, duration=0.25, pitch=60),
        _q(bar=1, beat=1.0 / 3.0, duration=1.0 / 3.0, pitch=62),
        _q(bar=1, beat=2.0 / 3.0, duration=1.0 / 3.0, pitch=64),
    ]
    notation = notate.build(quantized, [], swing=True, transpose=0)
    beat_one = [n for n in notation.bars[0].notes if n.beat < 1.0 - 1e-9]
    assert any(n.tuplet for n in beat_one)
    for piece in beat_one:
        for edge in (piece.beat, piece.beat + piece.duration):
            sixths = edge * 6.0
            assert abs(sixths - round(sixths)) < 1e-6, f"{edge} is not a sixth of a beat"


def _q(bar: int, beat: float, duration: float, pitch: int) -> QuantizedNote:
    return QuantizedNote(
        bar=bar, beat=beat, duration_beats=duration, pitch=pitch, timing_residual=0.0
    )


# -- triple metre ---------------------------------------------------------
#
# Halving is right in duple metre and wrong in triple. A 3/4 bar halved goes
# 3 -> 1.5 -> 0.75 and never lands on a beat, which used to leave 12 of the 66
# bars of the benchmark's one 3/4 score short of their time signature, with 14
# notes of duration zero among them.


def test_a_duple_bar_is_halved():
    assert split_points(0.0, 4.0) == [2.0]
    assert split_points(0.0, 1.0) == [0.5]


def test_a_triple_bar_is_cut_at_its_beats_not_at_its_middle():
    assert split_points(0.0, 3.0) == [1.0, 2.0]


def test_a_dotted_beat_divides_in_three():
    """Three eighths under a dotted quarter, not two and a half."""
    assert split_points(0.0, 1.5) == [0.5, 1.0]


def test_an_irregular_bar_peels_off_the_largest_whole_value():
    assert split_points(0.0, 5.0) == [4.0]


def test_split_conserves_duration_in_three_four():
    for start in [i * 0.25 for i in range(12)]:
        for duration in [i * 0.25 for i in range(1, 13)]:
            if start + duration > 3.0:
                continue
            pieces = split_for_meter(start, duration, 3.0)
            assert abs(sum(length for _s, length, _t in pieces) - duration) < 1e-9
            assert abs(pieces[0][0] - start) < 1e-9


def test_no_piece_of_a_three_four_bar_is_an_unwritable_sliver():
    """Every piece must be a real note value (or a legal tuplet). A duration
    that is not is what reached MusicXML as a 32nd carrying the wrong length,
    or as a note of length zero."""
    for start in [i * 0.125 for i in range(24)]:
        for duration in [i * 0.125 for i in range(1, 25)]:
            if start + duration > 3.0:
                continue
            for _s, length, tuplet in split_for_meter(start, duration, 3.0):
                assert length > 0.0
                assert is_notatable(length) or tuplet is not None


def test_a_three_four_bar_fills_to_three_beats():
    notes = [NotatedNote(beat=1.0, duration=0.5, pitch=60, step="C", octave=4)]
    filled = fill_rests(notes, 3.0)
    assert abs(sum(n.duration for n in filled) - 3.0) < 1e-9
    assert all(n.duration > 0.0 for n in filled)


def test_a_note_across_the_second_beat_of_a_waltz_is_cut_there():
    pieces = split_for_meter(0.5, 1.0, 3.0)
    assert [round(s, 6) for s, _l, _t in pieces] == [0.5, 1.0]


# ── written values land on a grid a reader can read ─────────────────────────
# Quantize snaps ONSETS and nothing ever snapped DURATIONS. The legato rule
# hid that for the 90% of notes that run into the next one, because the gap
# they inherit is grid-to-grid; the note before a rest kept its played length
# to the millisecond and was then shattered into tied slivers.


def test_a_played_length_is_written_as_the_nearest_readable_value():
    from swingscribe.stages.notate import snap_value

    assert snap_value(0.476, None) == 0.5
    assert snap_value(0.261, None) == 0.25
    assert snap_value(0.97, None) == 1.0


def test_the_grid_comes_from_the_beat_and_not_from_whichever_is_nearer():
    """A duration has to end on the grid its neighbours START on.

    Offering both grids to every note and taking the nearer one puts a
    triplet-eighth rest in a beat of sixteenths -- the twelfth-of-a-beat
    sliver `close_short_gaps` exists to prevent, arriving from the other side.
    """
    from swingscribe.stages.notate import TERNARY_VALUES, snap_value, ternary_beats

    assert snap_value(0.34, None, TERNARY_VALUES) == pytest.approx(1 / 3)
    assert snap_value(0.66, None, TERNARY_VALUES) == pytest.approx(2 / 3)
    # Beat 0 has onsets on thirds; beat 1 does not.
    assert ternary_beats([0.0, 1 / 3, 2 / 3, 1.0, 1.5]) == {0}


def test_a_tuplet_value_stays_exact_to_the_last_bit():
    """Not a rounding nicety. A candidate rounded to 0.333333 makes two of
    them 0.666666, and MuseScore calls a tuplet group that misses a sixth of a
    beat by 2e-6 a corrupt file."""
    from swingscribe.stages.notate import TERNARY_VALUES, snap_value

    for k in (1, 2, 3, 4):
        assert snap_value(k / 3.0, None, TERNARY_VALUES) * 6.0 == pytest.approx(2 * k, abs=1e-12)


def test_nothing_is_written_shorter_than_a_sixteenth():
    """The same judgement as MIN_REST: the listener gets exact timing from the
    record and wants the page readable."""
    from swingscribe.stages.notate import snap_value

    assert snap_value(0.03, None) == 0.25
    assert snap_value(0.12, None) == 0.25


def test_a_snapped_value_never_runs_past_the_next_onset():
    """`without_overlap` has already run, so rounding up past the next note
    would put two notes sounding at once in a single-line score."""
    from swingscribe.stages.notate import TERNARY_VALUES, snap_value

    assert snap_value(0.48, 0.4) <= 0.4 + 1e-6
    # And it rounds DOWN to a readable value rather than keeping the raw gap.
    assert snap_value(0.48, 0.4) == pytest.approx(0.25)
    assert snap_value(0.48, 0.4, TERNARY_VALUES) == pytest.approx(1 / 3)


def test_a_gap_too_small_for_any_value_keeps_the_gap():
    from swingscribe.stages.notate import snap_value

    assert snap_value(0.5, 0.05) == pytest.approx(0.05)


def test_snapping_leaves_an_already_readable_value_alone():
    from swingscribe.stages.notate import snap_value

    for value in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0):
        assert snap_value(value, None) == pytest.approx(value)


def test_the_note_before_a_rest_stops_being_a_sliver():
    """The whole defect, end to end.

    An eighth-note line where one note was tongued short: before snapping its
    0.31 of a beat is split into tied fragments and leaves an unwritable rest.
    """
    from swingscribe.model import QuantizedNote
    from swingscribe.stages.notate import build

    notes = [
        QuantizedNote(bar=1, beat=0.0, duration_beats=0.5, pitch=60, timing_residual=0.0),
        QuantizedNote(bar=1, beat=0.5, duration_beats=0.31, pitch=62, timing_residual=0.0),
        QuantizedNote(bar=1, beat=2.0, duration_beats=0.5, pitch=64, timing_residual=0.0),
    ]
    notation = build(notes, [], swing=False, transpose=0)
    written = [n for bar in notation.bars for n in bar.notes if not n.is_rest]
    assert all(n.duration >= 0.25 - 1e-6 for n in written), [n.duration for n in written]
    rests = [n for bar in notation.bars for n in bar.notes if n.is_rest]
    assert all(r.duration >= 0.25 - 1e-6 for r in rests), [r.duration for r in rests]


# ── the legato CAP: a lead sheet does not write articulation ───────────────
# `legato_fill` asks whether the PLAYER held the note, which is articulation.
# That is the right question where a duration is the gated extent of a CREPE
# pitch and tends to overrun. It is the wrong one where the duration is a
# careful human's note-off -- WJazzD's is -- and the player tongues short.


def test_a_short_played_note_still_fills_a_short_gap_under_the_cap():
    """Dexter Gordon's Cheese Cake, bar 2: he plays 0.52 of a one-beat gap.
    The ratio test fails at 0.75 and writes an eighth plus an eighth rest;
    the Jazzomat lead sheet writes a quarter."""
    from swingscribe.stages.notate import build

    notes = [
        _q(1, 0.0, 0.52, 60),
        _q(1, 1.0, 0.52, 62),
        _q(1, 2.0, 1.0, 64),
    ]
    ratio_only = build(notes, [], swing=False, transpose=0, legato_fill=0.75)
    capped = build(notes, [], swing=False, transpose=0, legato_fill=0.75, legato_cap=2.0)
    assert any(n.is_rest and n.beat < 2.0 for n in ratio_only.bars[0].notes)
    assert not any(n.is_rest and n.beat < 2.0 for n in capped.bars[0].notes)
    assert capped.bars[0].notes[0].duration == pytest.approx(1.0)


def test_the_cap_leaves_a_phrase_break_as_a_real_rest():
    """The failure the other route has. Dropping the ratio toward zero fills
    every gap, which ties a phrase-ending note across four beats of silence
    into the next phrase. A cap asks about the GAP, so it cannot do that."""
    from swingscribe.stages.notate import build

    notes = [_q(1, 0.0, 0.5, 60), _q(2, 1.0, 0.5, 62)]
    capped = build(notes, [], swing=False, transpose=0, legato_fill=0.75, legato_cap=2.0)
    assert capped.bars[0].notes[0].duration == pytest.approx(0.5)
    assert any(n.is_rest for n in capped.bars[0].notes)


def test_the_cap_is_off_by_default_so_the_pipeline_is_unchanged():
    from swingscribe.stages.notate import build

    notes = [_q(1, 0.0, 0.52, 60), _q(1, 1.0, 1.0, 62)]
    assert build(notes, [], swing=False, transpose=0, legato_fill=0.75).bars[0].notes[
        0
    ].duration == pytest.approx(0.5)
