"""The benchmark's reference placement — the part that was wrong for months.

The bug these guard against did not look like a bug. It made the benchmark
report a low note F1 and a normal onset F1, which reads as "the transcriber
gets notes but not rhythm" and sent real work in the wrong direction. So the
tests here are less about arithmetic than about the failure mode: a scorer
that can slip a beat must not be allowed back in.
"""

import statistics

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


def test_notation_scoring_is_blind_to_which_bar_is_bar_one():
    """Our bar numbering starts wherever the span did, theirs at their bar 1.
    That single constant is the one thing the comparison must forgive, and
    everything else must survive it."""
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    reference = [(float(i), 1.0, 60 + i) for i in range(8)]
    estimate = [(float(i) + 16.0, 1.0, 60 + i) for i in range(8)]  # 4 bars later
    aligned = align([p for _, _, p in reference], [p for _, _, p in estimate])
    result = score_notation(reference, estimate, aligned.pairs)
    assert result["placement"] == 1.0
    assert result["value"] == 1.0
    assert result["offset"] == 16.0


def test_a_wrong_note_value_is_right_in_placement_and_wrong_in_value():
    """The two numbers are kept apart because they fail independently: a
    quarter written where a dotted eighth belongs sits in the right place."""
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    reference = [(0.0, 0.75, 60), (1.0, 1.0, 62), (2.0, 1.0, 64)]
    estimate = [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64)]
    aligned = align([p for _, _, p in reference], [p for _, _, p in estimate])
    result = score_notation(reference, estimate, aligned.pairs)
    assert result["placement"] == 1.0
    assert abs(result["value"] - 2 / 3) < 1e-9


def test_a_note_written_on_the_wrong_beat_fails_placement():
    from swingscribe.alignment import align
    from swingscribe.benchmark import score_notation

    reference = [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)]
    estimate = [(0.0, 1.0, 60), (1.5, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)]
    aligned = align([p for _, _, p in reference], [p for _, _, p in estimate])
    assert score_notation(reference, estimate, aligned.pairs)["placement"] == 0.75


def test_nothing_matched_scores_zero_rather_than_dividing_by_it():
    from swingscribe.benchmark import score_notation

    assert score_notation([(0.0, 1.0, 60)], [(0.0, 1.0, 72)], [(0, 0)])["placement"] == 0.0
