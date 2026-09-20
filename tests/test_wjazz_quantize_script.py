"""The quantizer instrument's pure parts: how a note is classed and how our
page is paired with the annotator's list. No database, no audio."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

wq = pytest.importorskip("wjazz_quantize")


def test_a_note_on_the_annotators_tatum_is_a_hit():
    assert wq.classify(4.5, 4.5, 2, 2) == "hit"
    assert wq.classify(4.5, 4.5 + 1e-9, 2, 2) == "hit"


def test_the_swung_offbeat_is_one_eighth_however_it_is_filed():
    """WJazzD files a two-onset beat's offbeat at 1/2, 2/3 or 3/4; a page
    writes an eighth for all three, so no pairing of them is charged."""
    assert wq.classify(4 + 2 / 3, 4.5, 3, 2) == "swing convention"
    assert wq.classify(4.75, 4.5, 4, 2) == "swing convention"
    # Our 3/4 is the dotted rhythm of the complaint, whatever the annotator filed.
    assert wq.classify(4.5, 4.75, 2, 1) == "late offbeat as dotted"
    assert wq.classify(4.75, 4.75, 4, 2) == "late offbeat as dotted"
    # With three onsets in the beat the thirds are a triplet, not a swing.
    assert wq.classify(4 + 2 / 3, 4.5, 3, 3) == "triplet as binary"


def test_a_tatum_within_a_sixteenth_of_our_beat_is_the_annotations_literalness():
    assert wq.classify(4.25, 4.0, 4, 2) == "annotation literal"  # laid back, tatum'd
    assert wq.classify(4.75, 5.0, 4, 2) == "annotation literal"  # pushed, tatum'd


def test_the_complaints_two_classes_are_named():
    assert wq.classify(4.5, 4.25, 2, 1) == "early offbeat as 16th"
    assert wq.classify(4.5, 4.375, 2, 1) == "early offbeat as 16th"
    assert wq.classify(4.5, 4.75, 2, 3) == "late offbeat as dotted"
    assert wq.classify(4.0, 4.25, 1, 1) == "laid-back beat after it"
    assert wq.classify(4.0, 3.875, 1, 1) == "pushed beat before it"


def test_a_division_the_page_cannot_write_is_below_the_grid():
    assert wq.classify(4.2, 4.25, 5, 5) == "below the grid"
    assert wq.classify(4 + 1 / 3, 4 + 1 / 4, 6, 6) == "below the grid"


def test_binary_and_ternary_readings_are_kept_apart():
    assert wq.classify(4 + 1 / 3, 4.25, 3, 3) == "triplet as binary"
    assert wq.classify(4.5, 4 + 1 / 3, 2, 3) == "binary as triplet"


def test_ours_is_paired_with_theirs_in_order_and_a_dropped_note_is_a_skip():
    theirs = [{"pitch": p} for p in (60, 62, 64, 65, 67)]
    ours = [(0.0, 0.5, 60), (0.5, 0.5, 62), (1.5, 0.5, 65), (2.0, 0.5, 67)]  # 64 dropped
    pairs, skipped = wq.align(theirs, ours)
    assert pairs == [(0, 0), (1, 1), (3, 2), (4, 3)]
    assert skipped == 1


def test_a_note_ours_has_that_theirs_cannot_supply_is_left_unpaired():
    theirs = [{"pitch": p} for p in (60, 62)]
    ours = [(0.0, 0.5, 60), (0.25, 0.5, 71), (0.5, 0.5, 62)]
    pairs, skipped = wq.align(theirs, ours)
    assert pairs == [(0, 0), (1, 2)]
    assert skipped == 0


def test_positions_are_classed_on_a_24th_grid():
    assert wq.frac_of(3.5) == wq.Fraction(1, 2)
    assert wq.frac_of(3 + 2 / 3) == wq.Fraction(2, 3)
    assert wq.frac_of(3.125) == wq.Fraction(1, 8)
    assert wq.frac_of(3.0 + 1e-9) == 0
