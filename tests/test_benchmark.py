"""The benchmark's reference placement — the part that was wrong for months.

The bug these guard against did not look like a bug. It made the benchmark
report a low note F1 and a normal onset F1, which reads as "the transcriber
gets notes but not rhythm" and sent real work in the wrong direction. So the
tests here are less about arithmetic than about the failure mode: a scorer
that can slip a beat must not be allowed back in.
"""

import statistics

import pytest

from swingscribe.alignment import align
from swingscribe.benchmark import anchor_map, solo_shift, window_shift


def onset_hits(ref: list[float], est: list[float], shift: float, tolerance: float = 0.05) -> int:
    """What the OLD method maximized, kept so a test can show why it failed."""
    return sum(1 for r in ref if any(abs(r + shift - e) <= tolerance for e in est))


def test_window_shift_is_the_median_of_its_anchors():
    assert window_shift([0.10, 0.12, 0.14], fallback=9.0) == 0.12


def test_a_window_without_enough_anchors_falls_back_rather_than_vanishing():
    """A passage we failed to transcribe has no anchors. It must still be
    scored — against the solo's shift — or the benchmark quietly drops our
    worst playing and reports the average of the rest."""
    assert window_shift([], fallback=0.4) == 0.4
    assert window_shift([0.9], fallback=0.4) == 0.4
    assert window_shift([0.9, 0.9], fallback=0.4) == 0.4


def test_one_wild_anchor_does_not_move_the_shift():
    """An octave error can align to the wrong note and produce a nonsense
    delta. The median is chosen so that costs nothing."""
    assert window_shift([0.10, 0.11, 0.12, 0.13, 7.0], fallback=0.0) == 0.12


def test_anchors_ignore_substitutions():
    """A wrong note pairs two notes that are not the same note, so it says
    nothing about where the reference sits."""
    reference = [60, 62, 64]
    estimate = [60, 63, 64]  # middle note wrong
    aligned = align(reference, estimate)
    anchors = anchor_map(aligned.pairs, reference, estimate)
    assert anchors == {0: 0, 2: 2}


def test_a_uniform_eighth_line_defeats_a_hit_maximizing_search():
    """The bug, reproduced.

    A run of evenly spaced notes offers the hit-maximizing search a family of
    equally good shifts, one per note spacing. Onsets carry no identity, so
    the search has no evidence with which to prefer the true shift over one a
    whole eighth note away — and if it takes the slipped one, every pitch is
    then compared against its neighbour.
    """
    spacing = 0.16  # a swung eighth at ~190bpm
    reference = [i * spacing for i in range(16)]
    truth = 0.02
    # The line continues past both ends of the window, as a real solo does and
    # as the harness's margin allows for — so the slip has notes to land on.
    estimate = [i * spacing + truth for i in range(-2, 19)]

    # The tell: a slip of exactly one note spacing scores just as well.
    assert onset_hits(reference, estimate, truth) == onset_hits(
        reference, estimate, truth + spacing
    )

    # The alignment-anchored shift cannot slip, because the anchors say which
    # note is which before timing is consulted at all.
    deltas = [(i * spacing + truth) - reference[i] for i in range(16)]
    assert abs(window_shift(deltas, fallback=0.0) - truth) < 1e-9


def test_a_slipped_window_keeps_its_onset_score_and_loses_its_notes():
    """Why the slip stayed invisible: onset F1 does not notice it.

    This is the whole reason the benchmark read as a rhythm problem. Shifted
    by one note spacing, the onsets still coincide, so an onset-only measure
    is unchanged; it is only when pitch is consulted that the window collapses.
    """
    spacing = 0.16
    reference = [i * spacing for i in range(16)]
    ref_pitch = [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60, 59]
    estimate = [i * spacing + 0.02 for i in range(-2, 19)]

    slipped = 0.02 + spacing
    assert onset_hits(reference, estimate, slipped) >= 15  # onsets: fine
    # ...but each reference note now sits on its neighbour's pitch.
    agreeing = sum(1 for i in range(15) if ref_pitch[i] == ref_pitch[i + 1])
    assert agreeing == 0


def test_solo_shift_is_the_constant_tempo_error():
    deltas = [0.0, 0.1, 0.2, 0.3, 0.4]
    assert solo_shift(deltas) == statistics.median(deltas)
    assert solo_shift([]) == 0.0


# ── scoring the notation itself ──────────────────────────────────────────


def test_merge_ties_makes_one_note_of_a_tied_pair():
    """A tie is one note wearing two noteheads. The reference side merges them
    when parsing, so ours must too — otherwise every tie reads as an extra
    note the reference does not have, and a correct score loses precision for
    being correctly notated."""
    from swingscribe.benchmark import merge_ties

    # a whole note tied across a bar line, then a separate note
    notes = [(0.0, 4.0, 60, False), (4.0, 2.0, 60, True), (6.0, 2.0, 62, False)]
    assert merge_ties(notes) == [(0.0, 6.0, 60), (6.0, 2.0, 62)]


def test_merge_ties_does_not_join_a_repeated_note():
    """Two of the same pitch in a row are two notes unless a tie says so."""
    from swingscribe.benchmark import merge_ties

    notes = [(0.0, 1.0, 60, False), (1.0, 1.0, 60, False)]
    assert len(merge_ties(notes)) == 2


def test_notation_scoring_survives_a_different_bar_one():
    """Our bar numbering starts wherever the span did, theirs at their bar 1.
    Measuring intervals rather than absolute positions makes that unaskable."""
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    reference = [(float(i), 1.0, 60 + i) for i in range(8)]
    estimate = [(float(i) + 16.0, 1.0, 60 + i) for i in range(8)]  # 4 bars later
    aligned = align([p for _, _, p in reference], [p for _, _, p in estimate])
    result = score_notation(reference, estimate, aligned.pairs)
    assert result["rhythm"] == 1.0
    assert result["value"] == 1.0


def test_notation_scoring_survives_a_disagreement_about_the_bar_count():
    """The reason this measures intervals at all.

    Confirmation notates 130 bars where the hand transcription has 129. Scored
    on absolute position that difference drifts and swamps everything -- the
    same notation read 0.34 that way and 0.79 as intervals. A benchmark that
    cannot tell a rhythm error from a bar-count disagreement is not measuring
    rhythm.
    """
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    reference = [(float(i), 1.0, 60 + i % 12) for i in range(60)]
    estimate = [(float(i) * 1.02 + 9.0, 1.0, 60 + i % 12) for i in range(60)]
    aligned = align([p for _, _, p in reference], [p for _, _, p in estimate])
    assert score_notation(reference, estimate, aligned.pairs)["rhythm"] == 1.0


def test_a_score_against_itself_is_perfect():
    """The check any comparison measure has to pass before it is believed."""
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    score = [(0.0, 1.0, 60), (1.0, 0.5, 62), (1.5, 0.5, 64), (2.0, 2.0, 65)]
    aligned = align([p for _, _, p in score], [p for _, _, p in score])
    result = score_notation(score, score, aligned.pairs)
    assert result["rhythm"] == 1.0
    assert result["value"] == 1.0


def test_a_wrong_note_value_is_right_in_rhythm_and_wrong_in_value():
    """The two numbers are kept apart because they fail independently, and
    because the fix for each is in a different place."""
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    reference = [(0.0, 0.75, 60), (1.0, 1.0, 62), (2.0, 1.0, 64)]
    estimate = [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64)]
    aligned = align([p for _, _, p in reference], [p for _, _, p in estimate])
    result = score_notation(reference, estimate, aligned.pairs)
    assert result["rhythm"] == 1.0
    assert abs(result["value"] - 2 / 3) < 1e-9


def test_a_note_written_on_the_wrong_beat_fails_rhythm():
    from swingscribe.benchmark import score_notation

    reference = [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)]
    estimate = [(0.0, 1.0, 60), (1.5, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)]
    # two intervals ruined by moving one note: the one into it and the one out
    assert score_notation(reference, estimate, aligned_pairs(reference, estimate))["rhythm"] < 0.5


def aligned_pairs(reference, estimate):
    from swingscribe.alignment import align

    return align([p for _, _, p in reference], [p for _, _, p in estimate]).pairs


def test_nothing_matched_scores_zero_rather_than_dividing_by_it():
    from swingscribe.benchmark import score_notation

    assert score_notation([(0.0, 1.0, 60)], [(0.0, 1.0, 72)], [(0, 0)])["rhythm"] == 0.0


# ── a whole Notation against a whole Score ──────────────────────────────────
# The GUI's Score button and the eval harness both go through this, so what is
# under test is that they cannot drift apart -- and that the transposition is
# found rather than assumed.


def _bar(notes, signature=(4, 4)):
    from swingscribe.model import NotatedBar

    return NotatedBar(number=1, time_signature=signature, notes=notes)


def _note(beat, duration, pitch, tie_stop=False, rest=False):
    from swingscribe.model import NotatedNote

    return NotatedNote(
        beat=beat,
        duration=duration,
        pitch=pitch,
        step="C",
        alter=0,
        octave=4,
        is_rest=rest,
        tie_stop=tie_stop,
    )


def _notation(bars):
    from swingscribe.model import Notation

    return Notation(bars=bars)


class _Score:
    """The two fields `score_against_notation` reads off an mscz.Score."""

    def __init__(self, melody, bars=2):
        self.melody = melody
        self.bars = bars


class _ScoreNote:
    def __init__(self, position, duration, pitch):
        self.position, self.duration, self.pitch = position, duration, pitch


def test_bar_starts_accumulate_the_time_signature():
    from swingscribe.benchmark import bar_starts

    bars = [_bar([], (4, 4)), _bar([], (3, 4)), _bar([], (4, 4))]
    assert bar_starts(bars) == [0.0, 4.0, 7.0]


def test_notation_notes_are_absolute_and_drop_rests():
    from swingscribe.benchmark import notation_notes

    notation = _notation(
        [
            _bar([_note(0.0, 1.0, 60), _note(1.0, 1.0, 0, rest=True), _note(2.0, 2.0, 62)]),
            _bar([_note(0.0, 4.0, 64)]),
        ]
    )
    assert notation_notes(notation) == [(0.0, 1.0, 60), (2.0, 2.0, 62), (4.0, 4.0, 64)]


def test_notation_notes_merges_a_tie_across_a_barline():
    from swingscribe.benchmark import notation_notes

    notation = _notation(
        [
            _bar([_note(0.0, 4.0, 60)]),
            _bar([_note(0.0, 2.0, 60, tie_stop=True), _note(2.0, 2.0, 62)]),
        ]
    )
    assert notation_notes(notation) == [(0.0, 6.0, 60), (6.0, 2.0, 62)]


def test_a_notation_scored_against_its_own_notes_is_perfect():
    from swingscribe.benchmark import notation_notes, score_against_notation

    notation = _notation(
        [
            _bar([_note(0.0, 1.0, 60), _note(1.0, 1.0, 62), _note(2.0, 2.0, 64)]),
            _bar([_note(0.0, 1.0, 65), _note(1.0, 1.0, 67), _note(2.0, 2.0, 69)]),
        ]
    )
    melody = [_ScoreNote(p, d, n) for p, d, n in notation_notes(notation)]
    result = score_against_notation(notation, _Score(melody))
    assert result["rhythm"] == 1.0
    assert result["value"] == 1.0
    assert result["n_matched"] == 6.0
    assert result["transposition"] == 0.0


def test_the_transposition_is_measured_not_assumed():
    """A hand transcription written an octave up must not read as six wrong
    notes. Undetected, Confirmation scores 0.121 where the truth is 0.736."""
    from swingscribe.benchmark import notation_notes, score_against_notation

    notation = _notation(
        [
            _bar([_note(0.0, 1.0, 60), _note(1.0, 1.0, 62), _note(2.0, 2.0, 64)]),
            _bar([_note(0.0, 1.0, 65), _note(1.0, 1.0, 67), _note(2.0, 2.0, 69)]),
        ]
    )
    melody = [_ScoreNote(p, d, n + 12) for p, d, n in notation_notes(notation)]
    result = score_against_notation(notation, _Score(melody))
    assert result["transposition"] == 12.0
    assert result["rhythm"] == 1.0
    assert result["n_matched"] == 6.0


def test_an_empty_side_scores_zero_rather_than_raising():
    from swingscribe.benchmark import score_against_notation

    notation = _notation([_bar([_note(0.0, 4.0, 0, rest=True)])])
    assert score_against_notation(notation, _Score([]))["n_matched"] == 0.0


def test_the_wrong_score_does_not_manufacture_agreement():
    """The control this project relies on: run a fit against the WRONG take
    and it must collapse. A fit that still reads high there is measuring its
    own search, not the music -- that mistake has been made twice here.

    COVERAGE is the number that collapses, and rhythm is emphatically not.
    See `test_coverage_is_the_discriminator_and_rhythm_is_not`.
    """
    import random

    from swingscribe.benchmark import COVERAGE_FLOOR, notation_notes, score_against_notation

    rng = random.Random(7)
    scale = [60, 62, 64, 65, 67, 69, 71, 72]
    notation = _notation(
        [
            _bar(
                [_note(float(beat), 1.0, scale[(bar * 4 + beat) % len(scale)]) for beat in range(4)]
            )
            for bar in range(8)
        ]
    )
    right = [_ScoreNote(p, d, n) for p, d, n in notation_notes(notation)]
    good = score_against_notation(notation, _Score(right, bars=8))
    assert good["rhythm"] == 1.0
    assert good["coverage"] == 1.0
    assert good["trusted"] is True

    # Same note count, unrelated pitches at unrelated positions.
    wrong = [
        _ScoreNote(i * rng.choice([0.5, 1.0, 1.5]), 1.0, rng.randint(40, 84)) for i in range(32)
    ]
    bad = score_against_notation(notation, _Score(wrong, bars=8))
    assert bad["coverage"] < COVERAGE_FLOOR
    assert bad["trusted"] is False


def test_coverage_is_the_discriminator_and_rhythm_is_not():
    """Why `trusted` exists at all, and why it keys on coverage.

    Measured over every notation the benchmark can build against every hand
    score on disk: coverage runs 0.69-0.74 on the two RIGHT pairings and
    0.16-0.36 on fourteen WRONG ones, with no overlap. Rhythm over the same
    wrong pairings reaches 0.583 -- higher than All The Things reads against
    its OWN correct score (0.618). Two eighth-note bebop lines agree about
    most gaps by chance, so a rhythm number cannot tell you it is describing
    the wrong tune. The floor therefore sits in coverage's gap, and this test
    is what stops someone "tidying" it to a rounder number outside it.
    """
    from swingscribe.benchmark import COVERAGE_FLOOR

    assert 0.36 < COVERAGE_FLOOR < 0.69


def test_coverage_counts_their_notes_not_ours():
    """Half their score matched is half their score matched, however many
    notes we invented on top of it."""
    from swingscribe.benchmark import notation_notes, score_against_notation

    notation = _notation([_bar([_note(float(b), 1.0, 60 + b) for b in range(4)]) for _ in range(2)])
    ours = notation_notes(notation)
    melody = [_ScoreNote(p, d, n) for p, d, n in ours]
    result = score_against_notation(notation, _Score(melody, bars=2))
    assert result["reference"] == float(len(melody))
    assert result["coverage"] == result["n_matched"] / result["reference"]


def _notation_of(events, duration=0.5):
    """A 4/4 Notation holding notes at the given (quarter position, pitch)."""
    from swingscribe.model import NotatedBar, NotatedNote, Notation

    last = max((position for position, _p in events), default=0.0)
    count = int(last // 4) + 1
    bars = [NotatedBar(number=i + 1, time_signature=(4, 4), notes=[]) for i in range(count)]
    for position, pitch in events:
        index = int(position // 4)
        bars[index].notes.append(
            NotatedNote(beat=position - index * 4, duration=duration, pitch=pitch)
        )
    return Notation(title="t", bars=bars)


def _straight_eighths(pitches, start=0.0):
    """A line of straight eighths as (position_in_quarters, pitch)."""
    return [(start + i * 0.5, p) for i, p in enumerate(pitches)]


def test_wjazz_notation_scores_rhythm_and_reports_no_value():
    """WJazzD stores a note's metrical POSITION but not its notated VALUE, so
    a `value` number here would be invented."""
    from swingscribe.benchmark import score_against_wjazz_notation

    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    notation = _notation_of(_straight_eighths(pitches))
    result = score_against_wjazz_notation(notation, _straight_eighths(pitches))
    assert result["rhythm"] == 1.0
    assert "value" not in result
    assert result["coverage"] == 1.0
    assert result["trusted"] is True


def test_wjazz_notation_penalises_a_rhythm_written_wrong():
    from swingscribe.benchmark import score_against_wjazz_notation

    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    # We wrote every gap as a quarter where the annotation says an eighth.
    ours = _notation_of([(i * 1.0, p) for i, p in enumerate(pitches)])
    result = score_against_wjazz_notation(ours, _straight_eighths(pitches))
    assert result["coverage"] == 1.0  # the notes are all there
    assert result["rhythm"] < 0.2  # the rhythm is not


def test_wjazz_notation_measures_the_transposition():
    """The solo may be annotated at concert pitch and ours written elsewhere."""
    from swingscribe.benchmark import score_against_wjazz_notation

    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    ours = _notation_of([(i * 0.5, p + 12) for i, p in enumerate(pitches)])
    result = score_against_wjazz_notation(ours, _straight_eighths(pitches))
    assert result["transposition"] == -12.0
    assert result["rhythm"] == 1.0


def test_wjazz_notation_is_empty_without_an_annotation():
    from swingscribe.benchmark import score_against_wjazz_notation

    notation = _notation_of(_straight_eighths([60, 62]))
    assert score_against_wjazz_notation(notation, [])["n_matched"] == 0.0


# ── readability: is the page writable at all? ───────────────────────────────
# The one measure here that needs no reference. It exists because the listener
# could name two defects -- a sixteenth rest before a note played behind the
# beat, and "dotted 1/32 notes with strange ties" -- that NOTHING in
# `score_notation` could see, and because the repair for the first of them
# shows up in `value` as a regression with nothing on the other side.


def _tied(beat, duration, pitch, tuplet=None):
    from swingscribe.model import NotatedNote

    return NotatedNote(beat=beat, duration=duration, pitch=pitch, tie_start=True, tuplet=tuplet)


def test_a_page_of_eighths_and_eighth_rests_is_perfectly_readable():
    from swingscribe.benchmark import readability

    notation = _notation(
        [_bar([_note(0.0, 0.5, 60), _note(0.5, 0.5, 62), _note(1.0, 0.5, 0, rest=True)])]
    )
    result = readability(notation)
    assert result["readability"] == 1.0
    assert result["short_rests"] == 0.0
    assert result["short_values"] == 0.0
    assert result["events"] == 3.0


def test_a_sixteenth_rest_costs_readability():
    from swingscribe.benchmark import readability

    notation = _notation(
        [_bar([_note(0.0, 0.5, 60), _note(0.5, 0.25, 0, rest=True), _note(0.75, 0.5, 62)])]
    )
    result = readability(notation)
    assert result["short_rests"] == pytest.approx(100.0 / 3.0, abs=0.01)
    assert result["readability"] == pytest.approx(2.0 / 3.0, abs=0.001)


def test_a_thirty_second_note_costs_readability():
    from swingscribe.benchmark import readability

    notation = _notation([_bar([_note(0.0, 0.125, 60), _note(0.125, 0.5, 62)])])
    result = readability(notation)
    assert result["short_values"] == 50.0
    assert result["readability"] == 0.5


def test_a_triplet_eighth_is_read_as_an_eighth_and_costs_nothing():
    """The one rule that stops ordinary swing notation scoring as unwritable.

    A triplet eighth is STORED as a third of a beat, which is below a
    sixteenth; it is READ as an eighth with a 3 over it. Counting the stored
    duration would call 10% of every hand transcription unreadable.
    """
    from swingscribe.benchmark import readability

    third = 1.0 / 3.0
    notation = _notation(
        [
            _bar(
                [
                    _note(0.0, third, 60),
                    _note(third, third, 62),
                    _note(2 * third, third, 64),
                ]
            )
        ]
    )
    for note in notation.bars[0].notes:
        note.tuplet = (3, 2)
    assert readability(notation)["readability"] == 1.0


def test_a_triplet_rest_is_read_as_an_eighth_rest_too():
    from swingscribe.benchmark import readability

    third = 1.0 / 3.0
    notation = _notation([_bar([_note(0.0, third, 0, rest=True), _note(third, 2 * third, 60)])])
    notation.bars[0].notes[0].tuplet = (3, 2)
    notation.bars[0].notes[1].tuplet = (3, 2)
    assert readability(notation)["short_rests"] == 0.0


def test_ties_are_reported_and_do_not_move_the_score():
    """Reported next to it, not folded into it.

    A tie is how a legitimately long value crosses a barline. It rises with
    the two real defects, which makes it a useful witness, but a page is not
    unreadable for having one.
    """
    from swingscribe.benchmark import readability

    notation = _notation([_bar([_tied(0.0, 0.5, 60), _note(0.5, 0.5, 60, tie_stop=True)])])
    result = readability(notation)
    assert result["tie_rate"] == 0.5
    assert result["readability"] == 1.0


def test_readability_is_a_rate_so_a_chorus_and_a_solo_compare():
    from swingscribe.benchmark import readability

    short = _notation([_bar([_note(0.0, 0.125, 60), _note(0.5, 0.5, 62)])])
    long = _notation([_bar([_note(0.0, 0.125, 60), _note(0.5, 0.5, 62)]) for _ in range(8)])
    assert readability(short)["readability"] == readability(long)["readability"]
    assert readability(long)["events"] == 16.0


def test_an_empty_notation_scores_zero_rather_than_dividing_by_it():
    from swingscribe.benchmark import readability

    assert readability(_notation([]))["events"] == 0.0
    assert readability(_notation([_bar([])]))["readability"] == 0.0
