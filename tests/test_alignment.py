"""Time-free note-sequence alignment (src/swingscribe/alignment.py).

Pure logic, no numpy — these must run in CI, where the ml group is absent.
"""

from swingscribe.alignment import align, best_transposition, measured_transposition, to_chroma


def test_identical_sequences_align_perfectly():
    seq = [60, 62, 64, 65, 67]
    result = align(seq, seq)
    assert result.matches == 5
    assert (result.substitutions, result.insertions, result.deletions) == (0, 0, 0)
    assert result.f1 == 1.0


def test_a_wrong_note_is_a_substitution_not_an_insert_plus_delete():
    # Substituting costs the same as one gap but saves a second gap, so the
    # alignment should prefer it. Otherwise every wrong note would be
    # double-counted against both precision and recall.
    result = align([60, 62, 64], [60, 63, 64])
    assert result.substitutions == 1
    assert (result.insertions, result.deletions) == (0, 0)
    assert result.matches == 2


def test_an_extra_note_is_an_insertion():
    result = align([60, 62, 64], [60, 61, 62, 64])
    assert result.matches == 3
    assert result.insertions == 1
    assert result.deletions == 0
    assert result.recall == 1.0
    assert result.precision == 0.75


def test_a_missed_note_is_a_deletion():
    result = align([60, 62, 64], [60, 64])
    assert result.matches == 2
    assert result.deletions == 1
    assert result.insertions == 0
    assert result.precision == 1.0


def test_empty_estimate_scores_zero_without_dividing_by_zero():
    result = align([60, 62], [])
    assert result.deletions == 2
    assert result.precision == 0.0
    assert result.f1 == 0.0


def test_both_empty_is_not_an_error():
    result = align([], [])
    assert result.f1 == 0.0
    assert result.pairs == []


def test_pairs_reconstruct_the_whole_path_in_order():
    result = align([60, 62, 64], [60, 64])
    assert result.pairs == [(0, 0), (1, None), (2, 1)]


def test_fragmentation_costs_precision_but_not_recall():
    # One held note heard as three repeats — open-issue #1's failure mode.
    result = align([60, 67], [60, 60, 60, 67])
    assert result.recall == 1.0
    assert result.precision == 0.5


def test_best_transposition_finds_an_octave_error():
    reference = [60, 62, 64, 65, 67, 69]
    estimate = [p - 12 for p in reference]
    offset, result = best_transposition(reference, estimate)
    assert offset == 12
    assert result.matches == len(reference)


def test_best_transposition_finds_a_transposing_instrument_offset():
    # A Bb tenor part written in treble clef sounds 14 semitones lower.
    reference = [74, 76, 78, 79]
    estimate = [p - 14 for p in reference]
    offset, _ = best_transposition(reference, estimate)
    assert offset == 14


def test_best_transposition_leaves_a_matching_pair_alone():
    seq = [60, 62, 64, 65]
    offset, result = best_transposition(seq, seq)
    assert offset == 0
    assert result.matches == 4


def test_chroma_forgives_octaves_but_not_wrong_notes():
    reference = [60, 62, 64]
    octave_off = [72, 50, 64]
    assert align(to_chroma(reference), to_chroma(octave_off)).matches == 3
    wrong_note = [60, 63, 64]
    assert align(to_chroma(reference), to_chroma(wrong_note)).matches == 2


# ── the transposition is settled over the whole line ────────────────────────


def _line(seed: int, n: int) -> list[int]:
    import random

    rng = random.Random(seed)
    return [rng.choice([60, 62, 63, 65, 67, 69, 70, 72]) for _ in range(n)]


def test_measured_transposition_is_not_decided_by_the_opening():
    """A head heard an octave under the book, then a solo heard right: the
    prefix says +12, the whole line says 0. Three Omnibook sides did exactly
    this and lost two thirds of their pitch F1 to it."""
    reference = _line(1, 400)
    estimate = [p - 12 for p in reference[:100]] + reference[100:]
    prefix, _ = best_transposition(reference[:120], estimate[:160])
    assert prefix == 12
    offset, aligned = measured_transposition(reference, estimate)
    assert offset == 0
    assert aligned.matches >= 300  # the solo, plus whatever the head yields by chance


def test_measured_transposition_agrees_with_the_prefix_when_the_prefix_is_right():
    """Where the opening IS the line, the answer and the alignment are exactly
    what the prefix search gave, so no pinned number moves."""
    reference = _line(2, 300)
    estimate = [p + 12 for p in reference]
    offset, aligned = measured_transposition(reference, estimate)
    assert offset == -12
    assert aligned.matches >= 300  # the solo, plus whatever the head yields by chance
    assert aligned.pairs == align(reference, [p + offset for p in estimate]).pairs


def test_measured_transposition_on_an_empty_side_is_zero():
    offset, aligned = measured_transposition([], [60, 62])
    assert offset == 0
    assert aligned.matches == 0
