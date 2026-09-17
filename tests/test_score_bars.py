"""A located score's bar lines, read off the tracked beat grid.

The defect these guard against was invisible to every number the harness
pins: eleven of twenty-two Omnibook pages sat one to two beats off the
book's bar lines, because the downbeat was taken from a straight line
through a performance whose tempo breathes (2026-09-17).
"""

import random

from swingscribe.model import NotatedBar, NotatedNote, Notation
from swingscribe.score_bars import (
    PHASE_SHARE_FLOOR,
    bar_line_agreement,
    bars_on_grid,
    beat_coordinate,
    clock_anchors,
    wjazz_bar_line_agreement,
)


class _Note:
    def __init__(self, position, pitch):
        self.position, self.duration, self.pitch = position, 0.5, pitch


class _Score:
    def __init__(self, melody, bars):
        self.melody, self.bars, self.beats_per_bar = melody, bars, 4.0


def _grid(first: float, pulse: float, count: int, drift: float = 0.0) -> list[float]:
    """Beat times whose pulse lengthens by `drift` of itself over the grid."""
    beats, when = [], first
    for index in range(count):
        beats.append(when)
        when += pulse * (1.0 + drift * index / count)
    return beats


def _played(beats: list[float], origin: int, positions: list[float], late: float = 0.0):
    """Onsets for score positions, on a grid whose beat `origin` is quarter 0.
    Offbeats are laid back by `late` of a beat, the way a swung eighth is."""
    anchors = []
    for position in positions:
        whole = int(position)
        fraction = position - whole + (late if position % 1 else 0.0)
        lo, hi = beats[origin + whole], beats[origin + whole + 1]
        anchors.append((position, lo + fraction * (hi - lo)))
    return anchors


def test_beat_coordinate_reads_between_the_beats_and_refuses_the_edges():
    beats = [1.0, 1.5, 2.0]
    assert beat_coordinate(beats, 1.25) == 0.5
    assert beat_coordinate(beats, 1.5) == 1.0
    assert beat_coordinate(beats, 0.5) is None
    assert beat_coordinate(beats, 2.0) is None


def test_bar_one_is_the_beat_the_notes_vote_for_not_the_lines_intercept():
    """A tempo that drifts 6% puts a straight line's intercept a beat or more
    from bar 1; the grid carries the drift, so the vote does not care."""
    beats = _grid(0.4, 0.27, 400, drift=0.06)
    positions = [i * 0.5 for i in range(32 * 8)]
    found = bars_on_grid(_played(beats, 5, positions, late=0.15), beats, quarters=128)
    assert found["trusted"] is True
    assert found["phase"] == 1
    assert found["bar_one"] == beats[5]
    assert found["anchor"] == beats[5]
    assert found["end"] == beats[5 + 128]
    assert found["share"] > 0.95


def test_a_score_that_begins_before_the_file_still_names_a_bar_line_on_the_grid():
    beats = _grid(0.2, 0.3, 200)
    positions = [4.0 + i * 0.5 for i in range(200)]  # bar 1 was cut off the transfer
    anchors = [(q, t) for q, t in _played(beats, 0, positions)]
    shifted = [(q + 2.0, t) for q, t in anchors]  # quarter zero is two beats before the grid
    found = bars_on_grid(shifted, beats, quarters=110)
    assert found["bar_one"] is None
    assert found["phase"] == 2
    assert found["anchor"] == beats[2]


def test_a_slipped_beat_part_way_through_does_not_move_bar_one():
    """One beat the tracker doubled and the repair missed: everything after
    it votes for the next phase. The majority names the phase and the opening
    names bar 1."""
    beats = _grid(1.0, 0.3, 300)
    early = _played(beats, 8, [i * 0.5 for i in range(0, 200)])
    late = _played(beats, 9, [100.0 + i * 0.5 for i in range(0, 60)])
    found = bars_on_grid(early + late, beats, quarters=132)
    assert found["phase"] == 0
    assert found["bar_one"] == beats[8]
    assert found["share"] < 1.0
    assert found["trusted"] is True


def test_a_grid_at_half_the_scores_pulse_is_not_trusted():
    beats = _grid(1.0, 0.6, 200)  # the tracker halved a fast tempo
    onsets = [(i * 0.5, 1.0 + i * 0.15) for i in range(400)]  # quarters at 0.3 s
    found = bars_on_grid(onsets, beats, quarters=200)
    assert found["share"] < PHASE_SHARE_FLOOR
    assert found["trusted"] is False


def test_too_few_votes_are_not_trusted_and_none_at_all_is_empty():
    beats = _grid(0.0, 0.5, 40)
    assert bars_on_grid(_played(beats, 4, [0.0, 1.0, 2.0]), beats, quarters=16)["trusted"] is False
    empty = bars_on_grid([], beats, quarters=16)
    assert empty["votes"] == 0 and empty["anchor"] is None


def test_clock_anchors_keeps_the_matches_on_the_located_line():
    rng = random.Random(11)
    scale = [60, 62, 63, 65, 67, 69, 70, 72]
    score = _Score([_Note(i * 0.5, rng.choice(scale)) for i in range(160)], bars=20)
    start, spq = 10.0, 0.3
    heard = [(start + n.position * spq, n.pitch) for n in score.melody]
    elsewhere = [(100.0 + i * 0.2, rng.choice(scale)) for i in range(200)]
    found = {"transposition": 0.0, "start": start, "seconds_per_quarter": spq}
    anchors = clock_anchors(score, sorted(heard + elsewhere), found)
    assert len(anchors) >= 120  # the unrelated playing takes some matches for itself
    assert all(abs(onset - (start + position * spq)) <= 1.0 for position, onset in anchors)


def _page(score, shift: float) -> Notation:
    """The score's own notes as our Notation, every bar line `shift` beats early."""
    bars: dict[int, list[NotatedNote]] = {}
    for n in score.melody:
        index, beat = divmod(n.position + shift, 4.0)
        bars.setdefault(int(index), []).append(
            NotatedNote(beat=beat, duration=0.5, pitch=n.pitch, is_rest=False)
        )
    return Notation(
        bars=[
            NotatedBar(number=i + 1, time_signature=(4, 4), notes=bars.get(i, []))
            for i in range(max(bars) + 1)
        ]
    )


def test_a_page_on_the_books_bar_lines_reads_zero_and_a_beat_late_reads_three():
    """The rhythm measure scores these two pages the same; this one does not."""
    rng = random.Random(7)
    scale = [60, 62, 63, 65, 67, 69, 70, 72]
    score = _Score([_Note(i * 0.5, rng.choice(scale)) for i in range(96)], bars=12)
    right = bar_line_agreement(_page(score, 0.0), score)
    assert right["beat_offset"] == 0.0 and right["on_the_bar"] == 1.0
    # Au Privave, 2026-09-17: the book's beat 2 printed on our beat 1.
    late = bar_line_agreement(_page(score, 3.0), score)
    assert late["beat_offset"] == 3.0
    assert late["beat_share"] == 1.0 and late["on_the_bar"] == 0.0
    assert late["beat_n"] == 96.0


def test_bar_line_agreement_of_nothing_is_empty():
    score = _Score([_Note(0.0, 60)], bars=1)
    assert bar_line_agreement(Notation(), score)["beat_n"] == 0.0


def test_a_wjazz_solo_that_starts_on_the_wrong_beat_loses_nearly_all_of_on_the_bar():
    """The listener saw WJazzD pages begin on the wrong beat; WJazzD's own
    bar/beat/tatum is the reference that says so. The annotation's solo
    starts mid-bar, as they do -- only the beat in the bar is compared."""
    rng = random.Random(9)
    scale = [60, 62, 63, 65, 67, 69, 70, 72]
    score = _Score([_Note(i * 0.5, rng.choice(scale)) for i in range(96)], bars=12)
    theirs = [((n.position + 2.0) % 4.0, n.pitch) for n in score.melody]  # solo enters on beat 3
    right = wjazz_bar_line_agreement(_page(score, 2.0), theirs, 4.0)
    assert right["beat_offset"] == 0.0 and right["on_the_bar"] == 1.0
    wrong = wjazz_bar_line_agreement(_page(score, 1.0), theirs, 4.0)
    assert wrong["beat_offset"] == 3.0
    assert wrong["on_the_bar"] == 0.0


def test_a_page_in_another_metre_is_not_judged():
    score = _Score([_Note(i * 0.5, 60 + i % 5) for i in range(48)], bars=6)
    theirs = [(n.position % 3.0, n.pitch) for n in score.melody]
    assert wjazz_bar_line_agreement(_page(score, 0.0), theirs, 3.0)["beat_n"] == 0.0
    assert wjazz_bar_line_agreement(_page(score, 0.0), [], 4.0)["beat_n"] == 0.0
