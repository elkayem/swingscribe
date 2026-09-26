"""Quantize (plan §5 stage 5, M5).

Pure arithmetic like the swing stage, so all of it runs in CI including the
milestone's acceptance criterion: quantize, replay with the swing put back,
and land within 20ms of what was played.

The one thing to be careful about in here is what the round trip actually
asks. `replay_onsets(restore_residual=True)` is exact BY CONSTRUCTION — the
residual is precisely what was subtracted — so a test using it measures
nothing about quantization. The acceptance test replays the NOTATION, residual
discarded, which is the question that matters: does grid position plus feel
reproduce the performance?
"""

import random

import pytest

from swingscribe.config import Config
from swingscribe.model import BeatGrid, Document, MeterSection, NoteEvent, SwingSpan
from swingscribe.stages.quantize import (
    bar_and_beat,
    beat_position,
    choose_grid,
    pooled_phase,
    quantize_notes,
    replay_onsets,
    run,
    snap,
    unwarp_phase,
    warp_phase,
)
from swingscribe.stages.swing import phase_from_bur, swing_spans
from synthetic import generate

BURS = [1.0, 1.3, 1.6, 2.0, 2.5]
TEMPOS = [80, 120, 180, 260]
ACCEPTANCE_MS = 20.0  # plan §5 stage 5


# ── the warp ────────────────────────────────────────────────────────────


def test_warp_sends_the_swung_offbeat_to_the_middle():
    star = phase_from_bur(2.0)
    assert abs(warp_phase(star, star) - 0.5) < 1e-12


def test_warp_fixes_both_beat_boundaries():
    """A note on the downbeat must stay on the downbeat, or every bar drifts."""
    for bur in BURS:
        star = phase_from_bur(bur)
        assert abs(warp_phase(0.0, star)) < 1e-12
        assert abs(warp_phase(1.0, star) - 1.0) < 1e-12


def test_warp_is_monotonic():
    star = phase_from_bur(2.5)
    values = [warp_phase(i / 200.0, star) for i in range(201)]
    assert all(b >= a for a, b in zip(values, values[1:], strict=False))


def test_warp_is_identity_when_straight():
    for phase in (0.0, 0.25, 0.5, 0.75, 0.99):
        assert warp_phase(phase, 0.5) == phase
        assert unwarp_phase(phase, 0.5) == phase


def test_warp_and_unwarp_are_inverses():
    for bur in BURS:
        star = phase_from_bur(bur)
        for i in range(101):
            phase = i / 100.0
            assert abs(unwarp_phase(warp_phase(phase, star), star) - phase) < 1e-12


def test_warp_ignores_a_nonsensical_star():
    for star in (0.0, 1.0, -0.5, 1.5):
        assert warp_phase(0.3, star) == 0.3


# ── positions, snapping, grids ──────────────────────────────────────────


def test_beat_position_is_continuous_beats():
    beats = [0.0, 1.0, 2.0, 3.0]
    assert beat_position(0.0, beats) == 0.0
    assert beat_position(1.5, beats) == 1.5
    assert beat_position(2.25, beats) == 2.25


def test_beat_position_uses_each_beats_own_length():
    """Grids speed up and slow down; phase is relative to the local beat."""
    beats = [0.0, 1.0, 3.0]
    assert beat_position(2.0, beats) == 1.5


def test_beat_position_outside_the_grid():
    beats = [1.0, 2.0, 3.0]
    assert beat_position(0.5, beats) is None
    assert beat_position(3.0, beats) is None
    assert beat_position(1.5, [1.0]) is None


def test_snap_keeps_the_residual():
    snapped, residual = snap(1.30, 4)
    assert snapped == 1.25
    assert abs(residual - 0.05) < 1e-12
    assert abs((snapped + residual) - 1.30) < 1e-12


def test_snap_residual_is_signed():
    assert snap(1.20, 4)[1] < 0  # snapped up to 1.25
    assert snap(1.30, 4)[1] > 0  # snapped down to 1.25


def test_choose_grid_prefers_binary_for_even_eighths():
    assert choose_grid([0.0, 0.5], (4, 3)) == 4


def test_choose_grid_finds_a_triplet_figure():
    """Post-warp a triplet and a swung pair look alike; assuming binary would
    silently rewrite one as the other (plan §5)."""
    assert choose_grid([0.0, 1 / 3, 2 / 3], (4, 3)) == 3


def test_choose_grid_ties_go_to_binary():
    assert choose_grid([0.0], (4, 3)) == 4
    assert choose_grid([], (4, 3)) == 4


# ── pooling, and the refusal to warp on weak evidence ───────────────────


def _spans(bur, confidence, count=6, swung=True):
    return [
        SwingSpan(
            start_beat=i * 16,
            end_beat=(i + 1) * 16,
            bur=bur,
            confidence=confidence,
            is_swung=swung,
        )
        for i in range(count)
    ]


def test_no_spans_means_no_warp():
    assert pooled_phase([], 1.6) == ({}, None)
    assert pooled_phase(_spans(2.0, 0.9, swung=False), 1.6)[0] == {}


def test_a_noisy_latin_reading_is_left_straight():
    """BUR 1.45 at confidence 0.28. Feel-free onsets produce ~1.56 at this
    confidence (docs/wjazzd.md), so this is not evidence of swing and warping
    on it would inject error."""
    assert pooled_phase(_spans(1.45, 0.28), 1.6)[0] == {}


def test_a_confident_shuffle_below_the_floor_is_still_warped():
    """The floor is a statement about evidence, not about music. BUR 1.30 read
    at confidence 0.98 is a real shuffle — notating it straight would be 49ms
    off the performance at 80bpm."""
    assert pooled_phase(_spans(1.30, 0.98), 1.6)[0] != {}


def test_real_solo_readings_are_warped():
    for bur, confidence in [(1.79, 0.32), (2.16, 0.25), (1.90, 0.30)]:
        assert pooled_phase(_spans(bur, confidence), 1.6)[0] != {}, (bur, confidence)


def test_unconfident_spans_shrink_toward_the_track():
    """Per-window BUR is noisy and the aggregate is sound, so a low-confidence
    window should be pulled toward the tune's overall feel rather than trusted
    on its own (docs/m4-swing.md)."""
    spans = [
        SwingSpan(start_beat=0, end_beat=16, bur=2.0, confidence=0.9, is_swung=True),
        SwingSpan(start_beat=16, end_beat=32, bur=2.0, confidence=0.9, is_swung=True),
        SwingSpan(start_beat=32, end_beat=48, bur=4.0, confidence=0.05, is_swung=True),
    ]
    by_beat, track = pooled_phase(spans, 1.6)
    confident, wild = by_beat[0], by_beat[32]
    assert abs(confident - phase_from_bur(2.0)) < 0.02
    # the outlier is dragged most of the way back to the track's feel
    assert abs(wild - track) < abs(wild - phase_from_bur(4.0))


def test_the_floor_is_applied_once_not_per_span():
    """Testing each span separately puts a hard threshold on a noisy estimate,
    so neighbouring windows on identical material get opposite treatment. That
    measurably broke the round trip (25.6ms at BUR 1.6 against 0.0ms either
    side of it)."""
    spans = [
        SwingSpan(start_beat=0, end_beat=16, bur=1.62, confidence=0.95, is_swung=True),
        SwingSpan(start_beat=16, end_beat=32, bur=1.58, confidence=0.95, is_swung=True),
    ]
    by_beat, _ = pooled_phase(spans, 1.6)
    assert set(range(0, 32)) <= set(by_beat)  # every beat treated the same way


# ── bars ────────────────────────────────────────────────────────────────


def _section(beats, pulses=4):
    return MeterSection(
        start=beats[0],
        end=beats[-1],
        pulses_per_bar=pulses,
        time_signature=(4, 4),
        anchor=beats[0],
        first_bar=1,
    )


def test_bar_and_beat_counts_from_the_anchor():
    beats = [i * 0.5 for i in range(33)]
    section = _section(beats)
    assert bar_and_beat(0.0, beats, [section]) == (1, 0.0)
    assert bar_and_beat(3.0, beats, [section]) == (1, 3.0)
    assert bar_and_beat(4.0, beats, [section]) == (2, 0.0)
    assert bar_and_beat(9.5, beats, [section]) == (3, 1.5)


def test_bar_and_beat_outside_any_section_reports_bar_zero():
    """A pickup or a rubato intro must not be forced into a bar."""
    beats = [i * 0.5 for i in range(33)]
    section = MeterSection(start=4.0, end=16.0, pulses_per_bar=4, time_signature=(4, 4), anchor=4.0)
    assert bar_and_beat(1.0, beats, [section]) == (0, 1.0)
    assert bar_and_beat(2.0, beats, []) == (0, 2.0)


# ── the acceptance criterion ────────────────────────────────────────────


def _round_trip_error_ms(bpm, bur, jitter=0.0, seed=0, **kwargs):
    rng = random.Random(seed)
    notes, beats = generate.swung_phrase([60, 62] * 48, bpm=bpm, bur=bur)
    onsets = [n.onset + rng.gauss(0.0, jitter) for n in notes]
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets,
        [n.duration for n in notes],
        [n.pitch for n in notes],
        beats,
        spans,
        [],
        **kwargs,
    )
    replayed = replay_onsets(quantized, positions, beats, spans)
    return sorted(
        abs(a - b) * 1000.0 for a, b in zip(onsets[: len(replayed)], replayed, strict=False)
    )


@pytest.mark.parametrize("bur", BURS)
@pytest.mark.parametrize("bpm", TEMPOS)
def test_round_trip_lands_within_20ms(bur, bpm):
    """Plan §5 stage 5: quantize, re-render with swing applied, and the onsets
    must land within 20ms of the original. Residual NOT restored — this is
    replaying the notation, which is the only version of the question that
    tests anything."""
    errors = _round_trip_error_ms(bpm, bur)
    assert errors
    assert max(errors) < ACCEPTANCE_MS


def test_restoring_the_residual_is_exact():
    """The invariant behind the residual: nothing is thrown away. Exact by
    construction, which is why it is NOT the acceptance test above."""
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=2.0)
    onsets = [n.onset for n in notes]
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets, [n.duration for n in notes], [n.pitch for n in notes], beats, spans, []
    )
    replayed = replay_onsets(quantized, positions, beats, spans, restore_residual=True)
    assert max(abs(a - b) for a, b in zip(onsets, replayed, strict=False)) < 1e-9


@pytest.mark.parametrize("bpm", TEMPOS)
def test_round_trip_degrades_gracefully_with_tracker_jitter(bpm):
    """With 10ms of onset error the median stays well inside tolerance; the
    worst note can cross a grid boundary and snap to the wrong sixteenth,
    which is quantization working as specified rather than failing."""
    errors = _round_trip_error_ms(bpm, 2.0, jitter=0.010, seed=3)
    median = errors[len(errors) // 2]
    assert median < ACCEPTANCE_MS


def test_straight_material_is_not_warped_at_all():
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=1.0)
    onsets = [n.onset for n in notes]
    spans = swing_spans(onsets, beats)
    quantized, _ = quantize_notes(
        onsets, [n.duration for n in notes], [n.pitch for n in notes], beats, spans, []
    )
    assert quantized
    assert max(abs(n.timing_residual) for n in quantized) < 1e-9


def test_quantize_notes_degenerate_inputs():
    assert quantize_notes([], [], [], [], [], []) == ([], [])
    assert quantize_notes([1.0], [0.1], [60], [0.0], [], []) == ([], [])


# ── the stage ───────────────────────────────────────────────────────────


def _document(onsets, durations, pitches, beats, spans, stem="other"):
    return Document(
        audio_path="x.wav",
        sample_rate=16000,
        beat_grid=BeatGrid(beats=beats, downbeats=[], beats_per_bar=4),
        notes={
            stem: [
                NoteEvent(onset=o, duration=d, pitch=p, confidence=0.9, source="t")
                for o, d, p in zip(onsets, durations, pitches, strict=True)
            ]
        },
        swing=spans,
    )


def test_run_populates_the_document():
    notes, beats = generate.swung_phrase([60, 62] * 32, bpm=180.0, bur=2.0)
    onsets = [n.onset for n in notes]
    spans = swing_spans(onsets, beats)
    document = _document(
        onsets, [n.duration for n in notes], [n.pitch for n in notes], beats, spans
    )
    result = run(document, Config())
    assert result.quantized["other"]
    assert len(result.quantized["other"]) == len(onsets)


def test_run_requires_beats():
    with pytest.raises(ValueError, match="beats to have run first"):
        run(Document(audio_path="x.wav", sample_rate=16000), Config())


def test_run_names_the_missing_stem():
    document = Document(
        audio_path="x.wav",
        sample_rate=16000,
        beat_grid=BeatGrid(beats=[0.0, 0.5, 1.0], downbeats=[], beats_per_bar=4),
        notes={"vocals": []},
    )
    with pytest.raises(ValueError, match="needs notes for the 'other' stem"):
        run(document, Config())


def test_two_notes_in_a_beat_are_never_a_triplet():
    """The largest single disagreement with the hand transcriptions.

    Warping is imperfect — the phase estimate is shrunk toward the track mean
    and real playing scatters around it — so a warped offbeat routinely lands
    near 0.58 rather than 0.5. On pure snap error ternary then beats binary,
    and an even eighth pair gets notated as a triplet. Measured against the
    hand scores that was happening on a third of all intervals.

    A tuplet has to be visible in the notes: three of them, at least.
    """
    from swingscribe.stages.quantize import choose_grid

    swung_pair = [0.0, 0.62]  # a warped offbeat that did not quite reach 0.5
    assert choose_grid(swung_pair, (4, 3), min_onsets_for_tuplet=3) == 4
    # ...and on pure arithmetic it would have gone the other way:
    assert choose_grid(swung_pair, (4, 3), min_onsets_for_tuplet=1) == 3


def test_three_notes_that_really_are_a_triplet_still_are():
    """The other half. Suppressing tuplets entirely would be a worse error
    than allowing them too freely — a bebop line is full of real triplets."""
    from swingscribe.stages.quantize import choose_grid

    triplet = [0.0, 1 / 3, 2 / 3]
    assert choose_grid(triplet, (4, 3), min_onsets_for_tuplet=3) == 3


def test_a_beat_of_four_sixteenths_stays_binary():
    from swingscribe.stages.quantize import choose_grid

    assert choose_grid([0.0, 0.25, 0.5, 0.75], (4, 3), min_onsets_for_tuplet=3) == 4


def test_the_tuplet_floor_cannot_leave_a_beat_with_no_grid():
    """If every candidate were ternary, requiring three onsets must still
    return something rather than falling off the end."""
    from swingscribe.stages.quantize import choose_grid

    assert choose_grid([0.0, 0.5], (3,), min_onsets_for_tuplet=3) == 3


def test_a_grid_that_merges_two_onsets_is_too_coarse_whatever_its_error():
    """Two notes on one grid position are ONE note in a single-line score --
    the other is simply lost. So separation is a hard constraint, not a
    preference: before this rule, buying notated rhythm by coarsening the grid
    quietly deleted 4.8% of All The Things."""
    from swingscribe.stages.quantize import choose_grid

    # Two onsets a sixteenth apart: an eighth grid puts them in one place.
    close_pair = [0.0, 0.25]
    assert choose_grid(close_pair, (2, 4), min_onsets_for_tuplet=3, slack=1.0) == 4


def test_parsimony_still_applies_when_the_grid_can_separate_the_notes():
    from swingscribe.stages.quantize import choose_grid

    # An eighth pair: both grids separate it, so the coarser one wins.
    assert choose_grid([0.0, 0.52], (2, 4), min_onsets_for_tuplet=3, slack=0.05) == 2


def test_zero_slack_restores_least_snap_error():
    from swingscribe.stages.quantize import choose_grid

    assert choose_grid([0.0, 0.52], (2, 4), min_onsets_for_tuplet=3, slack=0.0) == 2
    assert choose_grid([0.0, 0.74], (2, 4), min_onsets_for_tuplet=3, slack=0.0) == 4


def test_a_32nd_run_is_not_merged_off_the_page():
    """The listener's ballad rule, half one: when a soloist genuinely plays
    a run of 32nds — five or more onsets in one beat, which no sixteenth
    grid can keep apart — they are written as 32nds, not silently merged.
    Don't Blame Me was losing 186 of 513 heard notes to exactly this."""
    period = 60.0 / 64.0  # a ballad beat
    beats = [i * period for i in range(6)]
    onsets = [beats[2] + k * period / 8 for k in range(8)]  # eight 32nds
    quantized, _ = quantize_notes(onsets, [0.05] * 8, list(range(60, 68)), beats, [], [])
    assert len(quantized) == 8
    fractions = sorted(q.beat - int(q.beat) for q in quantized)
    assert fractions == pytest.approx([k / 8 for k in range(8)])
    assert len(set(fractions)) == 8  # every note keeps its own place


def test_a_laggy_sixteenth_line_is_never_promoted_to_32nds():
    """Half two: a soloist playing sixteenths BEHIND the beat must stay on
    the sixteenth grid — four onsets keep apart there, so the 32nd grid is
    never even offered, however well it would fit the lag."""
    period = 60.0 / 64.0
    beats = [i * period for i in range(6)]
    lag = 0.06 * period  # noticeably behind, close to a 32nd position
    onsets = [beats[2] + (k / 4 + 0.0) * period + lag for k in range(4)]
    quantized, _ = quantize_notes(onsets, [0.05] * 4, [60, 62, 64, 65], beats, [], [])
    fractions = sorted(q.beat - int(q.beat) for q in quantized)
    assert fractions == pytest.approx([0.0, 0.25, 0.5, 0.75])


def test_a_real_triplet_survives_the_swing_warp():
    """D12's mechanism: the swing warp is a hypothesis about BINARY beats,
    and applying it to a genuine triplet drags the thirds off-lattice before
    choose_grid votes — {0, 1/3, 2/3} warped at BUR 2.5 reads {0, .23, .47},
    which sixteenths fit almost perfectly. Scored in raw time, where a
    performed triplet actually sits at thirds, ternary wins — and the
    notated positions are true thirds, not thirds of warped space."""
    period = 0.4  # 150 bpm
    beats = [i * period for i in range(9)]
    spans = [SwingSpan(start_beat=0, end_beat=8, bur=2.5, confidence=0.95, is_swung=True)]
    onsets = [beats[2] + f * period for f in (0.0, 1 / 3, 2 / 3)]
    quantized, positions = quantize_notes(onsets, [0.05] * 3, [60, 62, 64], beats, spans, [])
    fractions = [q.beat - int(q.beat) for q in quantized]
    assert fractions == pytest.approx([0.0, 1 / 3, 2 / 3])
    # And the round trip replays them AT the thirds — the warp does not
    # reapply to a beat notated ternary.
    replayed = replay_onsets(quantized, positions, beats, spans)
    assert replayed == pytest.approx(onsets, abs=1e-9)


def test_a_swung_pair_still_cannot_vote_a_tuplet():
    """The convention gate survives raw-space scoring: a swung offbeat in raw
    time lands near 2/3 — that is what swing IS — so on arithmetic alone a
    pair would read ternary. The page writes swung pairs as eighths."""
    period = 0.4
    beats = [i * period for i in range(9)]
    spans = [SwingSpan(start_beat=0, end_beat=8, bur=2.0, confidence=0.95, is_swung=True)]
    onsets = [beats[2], beats[2] + 0.66 * period]
    quantized, _ = quantize_notes(onsets, [0.05] * 2, [60, 62], beats, spans, [])
    fractions = [q.beat - int(q.beat) for q in quantized]
    assert fractions == pytest.approx([0.0, 0.5])


def test_the_same_figure_is_written_finer_on_a_slow_beat():
    """D11: the slack is a time budget, so the SAME beat-fraction figure gets
    a finer grid on a long beat than a short one — the direction of WJazzD's
    tempo staircase (16ths under 120 bpm, eighths over 160, across 456 solos,
    while the interval in SECONDS stays put).

    The figure: three onsets at 0, 0.5 and 0.8 of the beat. On a ballad
    beat (60 bpm, 1s) the third is 200ms past the eighth position and 50ms
    from the sixteenth -- a real dotted rhythm, written to the sixteenth
    grid. On a burner's beat (200 bpm, 300ms) the same fraction is 60ms of
    earliness on the next beat -- a pushed downbeat, written as one. A
    constant slack in beats cannot say both. (Three onsets, because since
    2026-09-20 a beat of one or two is read on eighths at every tempo:
    docs/wjazz-quantize.md.)
    """

    def third_note_beat(bpm):
        period = 60.0 / bpm
        beats = [i * period for i in range(6)]
        onsets = [beats[1], beats[1] + 0.5 * period, beats[1] + 0.8 * period]
        quantized, _ = quantize_notes(onsets, [0.05] * 3, [60, 62, 64], beats, [], [])
        assert len(quantized) == 3
        return quantized[2].beat

    assert third_note_beat(60.0) == pytest.approx(1.75)  # sixteenth grid: dotted figure
    assert third_note_beat(200.0) == pytest.approx(2.0)  # eighth grid: the next beat


def test_a_chord_rides_through_quantize_on_its_head_note():
    """quantize_notes never derives a chord; it carries the one it is handed
    and hands it back on the same note, so notate can write it."""
    from swingscribe.stages.quantize import quantize_notes

    beats = [float(i) * 0.5 for i in range(40)]
    onsets = [beats[4], beats[6], beats[8]]
    quantized, _ = quantize_notes(
        onsets, [0.2, 0.2, 0.2], [60, 64, 67], beats, [], [], chords=[[], [72, 76], []]
    )
    assert [n.chord for n in quantized] == [[], [72, 76], []]
    plain, _ = quantize_notes(onsets, [0.2, 0.2, 0.2], [60, 64, 67], beats, [], [])
    assert [n.chord for n in plain] == [[], [], []]


# -- the quarter-note triplet, read over a beat pair (D28) -------------------


def _pair_figure(beats, first: int, period: float, extra=()):
    """Three onsets at 0, 2/3 and 4/3 of the pair starting at beat `first`,
    plus the next downbeat, plus any extras (in beats from `first`)."""
    fractions = [0.0, 2 / 3, 4 / 3, 2.0, *extra]
    return sorted(beats[first] + f * period for f in fractions)


def test_a_quarter_note_triplet_is_read_over_the_beat_pair():
    """Beat by beat the figure is invisible: two onsets in the first beat
    (which cannot vote a tuplet) and one at a third in the second. Read as a
    pair against the 0, 2/3, 4/3 lattice it is what a human writes -- 48 of
    the hand scores' ternary notes in under-three-onset beats are this."""
    period = 0.4
    beats = [i * period for i in range(9)]
    spans = [SwingSpan(start_beat=0, end_beat=8, bur=2.0, confidence=0.95, is_swung=True)]
    onsets = _pair_figure(beats, 2, period)
    quantized, _ = quantize_notes(
        onsets, [0.05] * 4, [60, 62, 64, 65], beats, spans, [], quarter_triplets=True
    )
    assert [q.beat for q in quantized] == pytest.approx([2.0, 2 + 2 / 3, 3 + 1 / 3, 4.0])


def test_a_swung_pair_and_a_downbeat_are_not_a_quarter_note_triplet():
    """The same three onsets a beat apart: a swung eighth pair on the first
    beat (its offbeat at 2/3, which IS swing) and the second beat's downbeat.
    The downbeat sits a third from any lattice point, so the pair reading
    loses and the page writes eighths."""
    period = 0.4
    beats = [i * period for i in range(9)]
    spans = [SwingSpan(start_beat=0, end_beat=8, bur=2.0, confidence=0.95, is_swung=True)]
    onsets = sorted(beats[2] + f * period for f in (0.0, 0.66, 1.0, 1.66, 2.0))
    quantized, _ = quantize_notes(
        onsets, [0.05] * 5, [60] * 5, beats, spans, [], quarter_triplets=True
    )
    assert [q.beat for q in quantized] == pytest.approx([2.0, 2.5, 3.0, 3.5, 4.0])


def test_the_pair_must_start_on_a_half_note_unit():
    """Beats 2 and 3 of a bar (0-based 1 and 2) are not a unit notate can
    bracket -- the bar halves at beat 3 -- so the figure there keeps its
    beat-level reading, an eighth after the second beat's downbeat (a lone
    onset is read on eighths, docs/wjazz-quantize.md)."""
    period = 0.4
    beats = [i * period for i in range(9)]
    spans = [SwingSpan(start_beat=0, end_beat=8, bur=2.0, confidence=0.95, is_swung=True)]
    onsets = _pair_figure(beats, 1, period)
    quantized, _ = quantize_notes(
        onsets, [0.05] * 4, [60, 62, 64, 65], beats, spans, [], quarter_triplets=True
    )
    assert [q.beat for q in quantized] == pytest.approx([1.0, 1.5, 2.5, 3.0])


def test_a_three_four_bar_has_no_half_note_unit():
    period = 0.4
    beats = [i * period for i in range(13)]
    section = MeterSection(
        start=0.0,
        end=beats[-1],
        pulses_per_bar=3,
        time_signature=(3, 4),
        anchor=0.0,
        first_bar=1,
        origin="user",
    )
    spans = [SwingSpan(start_beat=0, end_beat=12, bur=2.0, confidence=0.95, is_swung=True)]
    onsets = _pair_figure(beats, 3, period)  # beats 1-2 of bar 2, in 3/4
    quantized, _ = quantize_notes(
        onsets, [0.05] * 4, [60] * 4, beats, spans, [section], quarter_triplets=True
    )
    fractions = [q.beat - int(q.beat) for q in quantized]
    assert fractions == pytest.approx([0.0, 0.5, 0.5, 0.0])


def test_the_pair_reading_needs_the_whole_figure():
    """Two of the three (a downbeat and the note at 2/3) are a swung pair by
    the convention; the figure has to show three equally spaced onsets."""
    from swingscribe.stages.quantize import quarter_triplet_pairs

    beats = [i * 0.4 for i in range(9)]
    assert quarter_triplet_pairs({2: [0.0, 2 / 3], 3: []}, beats, []) == []
    assert quarter_triplet_pairs({2: [0.0, 2 / 3], 3: [1 / 3]}, beats, []) == [2]


def test_the_pair_reading_wants_equal_spacing_not_the_lattice():
    """Measured against the hand scores, the human's quarter-note triplets sit
    in our onsets at gaps of 0.58-0.78 of a beat starting late, none on 0,
    2/3, 4/3 -- and a swung "one, and, and" has gaps of 2/3 then 1."""
    from swingscribe.stages.quantize import quarter_triplet_pairs

    beats = [i * 0.4 for i in range(9)]
    late_but_even = {2: [0.09, 0.865], 3: [0.643]}  # gaps 0.775, 0.778
    assert quarter_triplet_pairs(late_but_even, beats, []) == [2]
    one_and_and = {2: [0.0, 0.667], 3: [0.667]}  # gaps 0.667, 1.0
    assert quarter_triplet_pairs(one_and_and, beats, []) == []
    with_a_fourth = {2: [0.0, 0.5, 0.667], 3: [0.333]}
    assert quarter_triplet_pairs(with_a_fourth, beats, []) == []
    early_downbeat_after = {2: [0.0, 0.667], 3: [0.333, 0.9]}  # 1.9: the next downbeat, early
    assert quarter_triplet_pairs(early_downbeat_after, beats, []) == [2]


def test_the_reading_is_off_unless_asked_for():
    """The flag ships off (config.py says why): the same figure is written
    beat by beat -- an eighth pair and an eighth after the downbeat."""
    period = 0.4
    beats = [i * period for i in range(9)]
    spans = [SwingSpan(start_beat=0, end_beat=8, bur=2.0, confidence=0.95, is_swung=True)]
    onsets = _pair_figure(beats, 2, period)
    quantized, _ = quantize_notes(onsets, [0.05] * 4, [60, 62, 64, 65], beats, spans, [])
    assert [q.beat for q in quantized] == pytest.approx([2.0, 2.5, 3.5, 4.0])
    assert Config().quantize.quarter_triplets is False


# ── each beat read straight or swung (docs/wjazz-quantize.md) ───────────────


def test_a_beat_played_straight_is_read_straight_inside_a_swinging_solo():
    """An offbeat at 0.5 with a span reading φ* = 0.65 warps to 0.38, which
    the sixteenth grid fits better than the eighth: the swung-pair convention
    turned a straight eighth into a sixteenth on 3.1% of WJazzD's notes. Read
    under the raw phase it is an eighth with no error; a swung pair is still
    read under the warp."""
    from swingscribe.stages.quantize import choose_reading

    star = 0.65
    straight = [0.0, 0.5]
    warped = [warp_phase(p, star) for p in straight]
    assert choose_reading(warped, (2, 4, 3), 3, 0.05, raw_offsets=straight) == (2, "raw")
    swung = [0.0, 0.65]
    warped = [warp_phase(p, star) for p in swung]
    assert choose_reading(warped, (2, 4, 3), 3, 0.05, raw_offsets=swung) == (2, "warped")
    # An offbeat PAST the swing point is not straight: read raw, 0.75 is a
    # perfect sixteenth and the page would get the dotted eighth back.
    late = [0.0, 0.75]
    warped = [warp_phase(p, star) for p in late]
    assert choose_reading(warped, (2, 4, 3), 3, 0.05, raw_offsets=late, star=star) == (
        2,
        "warped",
    )
    assert choose_reading(warped, (2, 4, 3), 3, 0.05, raw_offsets=late) == (4, "raw")
    # Without the raw phases there is only the warped reading, as before.
    assert choose_reading([0.0, 0.5], (4, 3)) == (4, "warped")


def test_the_straight_reading_is_notated_and_replayed_where_it_was_played():
    """One straight offbeat inside a swinging line: on the page it is the
    same eighth as its swung neighbours (not the sixteenth it warped to),
    and the round trip puts it back at 0.5, not at the span's φ*."""
    beat = 0.4  # 150 bpm
    beats = [i * beat for i in range(24)]
    onsets = []
    for i in range(2, 20):
        onsets.append(beats[i])
        onsets.append(beats[i] + (0.5 if i == 10 else 0.66) * beat)
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets, [0.1] * len(onsets), [60] * len(onsets), beats, spans, []
    )
    by_position = dict(zip(positions, quantized, strict=True))
    notated = sorted(round(q.beat, 3) for p, q in by_position.items() if 10 <= p < 11)
    assert notated == [10.0, 10.5]
    replayed = replay_onsets(quantized, positions, beats, spans)
    played = {round(o, 6) for o in onsets}
    straight = beats[10] + 0.5 * beat
    assert any(abs(r - straight) < 1e-6 for r in replayed)
    swung = beats[11] + 0.66 * beat
    assert min(abs(r - swung) for r in replayed) < 0.02 * beat
    assert played  # the line was swung everywhere else and replays as such


# ── a sparse beat cannot demonstrate a sixteenth (docs/wjazz-quantize.md) ────


def _sparse_line(offbeat: float, count: int = 12, beat: float = 0.4):
    """A swung line with one beat whose lone offbeat sits at `offbeat`."""
    beats = [i * beat for i in range(count + 4)]
    onsets = []
    for i in range(2, count + 2):
        if i == 8:
            onsets.append(beats[i] + offbeat * beat)
            continue
        onsets.append(beats[i])
        onsets.append(beats[i] + 0.66 * beat)
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets, [0.1] * len(onsets), [60] * len(onsets), beats, spans, []
    )
    return [round(q.beat, 3) for q, p in zip(quantized, positions, strict=True) if 8 <= p < 9]


def test_a_lone_late_offbeat_is_an_eighth_not_a_dotted_figure():
    """Played at 0.82 of the beat, alone in it, a swung "and" warps to about
    0.75 and the sixteenth grid fits it exactly: the dotted eighth plus
    sixteenth of the listener's complaint, 4.7% of WJazzD's notes. One
    onset cannot demonstrate a sixteenth, so the beat is read on eighths."""
    assert _sparse_line(0.82) == [8.5]


def test_a_lone_laid_back_downbeat_is_on_the_beat():
    """Played 0.2 late and alone in its beat, the note was on the "e" (1.6%
    of WJazzD's notes). On the eighth grid it is the beat."""
    assert _sparse_line(0.2) == [8.0]


def test_the_sparse_rule_never_costs_a_note():
    """A lone onset at 0.85 of beat 8 reads as beat 9 on the eighth grid --
    where beat 9's own first note sits. The collision guard keeps the finer
    grid, and both notes reach the page. (At 75 bpm, where the slack is
    small enough that the shipped reading was the sixteenth; at 150 the
    coarsest-within-slack rule already read it as the next beat, D29.)"""
    beat = 0.8
    beats = [i * beat for i in range(20)]
    onsets = [beats[i] for i in range(2, 16) if i != 8] + [beats[8] + 0.85 * beat]
    onsets.sort()
    quantized, positions = quantize_notes(
        onsets, [0.1] * len(onsets), [60] * len(onsets), beats, [], []
    )
    assert len(quantized) == len(onsets)
    near = sorted(
        round(q.beat, 3) for q, p in zip(quantized, positions, strict=True) if 8 <= p <= 9
    )
    assert near == [8.75, 9.0]


def test_min_onsets_for_sixteenth_of_one_restores_the_old_reading():
    from swingscribe.stages.quantize import choose_reading  # noqa: F401 - documents the knob

    beat = 0.4
    beats = [i * beat for i in range(20)]
    onsets = [beats[8] + 0.2 * beat]
    quantized, _ = quantize_notes(onsets, [0.1], [60], beats, [], [], min_onsets_for_sixteenth=1)
    assert round(quantized[0].beat, 3) == 8.25


# ── the tuplet gate, two refinements (docs/wjazz-quantize.md) ────────────────


def test_a_pair_starting_off_the_beat_that_fits_thirds_may_vote_a_tuplet():
    """The second and third of a triplet after a rest: (0.35, 0.75). The
    swung-pair convention is about {0, 2/3}; this figure starts at 1/3."""
    from swingscribe.stages.quantize import choose_reading

    pair = [0.35, 0.7]
    assert choose_reading(pair, (2, 4, 3), 3, 0.05, raw_offsets=pair, offbeat_pair_fit=0.05) == (
        3,
        "raw",
    )
    # Off by default, and the swung pair is still an eighth pair.
    assert choose_reading(pair, (2, 4, 3), 3, 0.05, raw_offsets=pair)[0] != 3
    swung = [0.0, 0.66]
    assert (
        choose_reading(swung, (2, 4, 3), 3, 0.05, raw_offsets=swung, offbeat_pair_fit=0.05)[0] != 3
    )


def test_laid_back_sixteenths_are_not_a_triplet_when_the_last_lands_on_the_next_beat():
    """(0.3, 0.55, 0.85): the thirds grid sends 0.85 to 1.0, which is the
    next beat's note early, not the third of a triplet. Four onsets never
    are one."""
    from swingscribe.stages.quantize import choose_reading

    late = [0.3, 0.55, 0.85]
    assert choose_reading(late, (2, 4, 3), 3, 0.05, raw_offsets=late)[0] == 3
    assert choose_reading(late, (2, 4, 3), 3, 0.05, raw_offsets=late, inside=True)[0] == 4
    four = [0.1, 0.35, 0.6, 0.85]
    assert choose_reading(four, (2, 4, 3), 3, 0.05, raw_offsets=four, inside=True)[0] == 4
    # A real triplet, all three inside, is still a triplet.
    real = [0.0, 1 / 3, 2 / 3]
    assert choose_reading(real, (2, 4, 3), 3, 0.05, raw_offsets=real, inside=True) == (3, "raw")


def test_the_inside_rule_is_on_and_the_pair_rule_is_off_by_default():
    """Both measured on the instrument and then on the pages: the inside
    rule lifts every page-side measure a little, the pair rule lowers them
    all (docs/wjazz-quantize.md)."""
    assert Config().quantize.offbeat_pair_tuplet_fit == 0.0
    assert Config().quantize.tuplet_needs_onsets_inside is True


# ── the line's lag behind the beat is taken out first (docs/notation-survey.md) ──


def _laid_back_line(lag: float, window: int = 4, count: int = 12, beat: float = 0.38):
    """A straight sixteenth-ish line played `lag` beats behind the grid:
    every beat holds onsets at lag, lag + 0.25 and lag + 0.5, except beat 8,
    which holds the same three on time. Returns the notated positions of
    beats 6 and 8 and everything needed to replay."""
    beats = [i * beat for i in range(count + 4)]
    onsets = []
    for i in range(2, count + 2):
        late = 0.0 if i == 8 else lag
        onsets.extend(beats[i] + (late + k) * beat for k in (0.0, 0.25, 0.5))
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets,
        [0.05] * len(onsets),
        [60] * len(onsets),
        beats,
        spans,
        [],
        lag_window_beats=window,
    )
    by_beat = {}
    for q, p in zip(quantized, positions, strict=True):
        by_beat.setdefault(int(p), []).append(round(q.beat, 3))
    return by_beat, (onsets, beats, spans, quantized, positions)


def test_a_line_played_behind_the_beat_is_written_on_the_beat():
    """Played 0.2 of a beat late throughout, the sixteenth grid faithfully
    wrote every downbeat on the "e" (6.2% of our onsets, against a human's
    1.8-2.5%). With the lag taken out, beat 6 is 0, 0.25, 0.5 -- and beat
    8, the one beat played on time, keeps its own first onset where it was."""
    by_beat, _ = _laid_back_line(0.2)
    assert by_beat[6] == [6.0, 6.25, 6.5]
    assert by_beat[8] == [8.0, 8.25, 8.5]
    without, _ = _laid_back_line(0.2, window=0)
    assert without[6] == [6.25, 6.5, 6.75]


def test_the_lag_replays_as_feel_and_the_round_trip_stays_exact():
    """The notation replays with its lag put back (it is feel, like swing),
    and with the residual restored the performance comes back exactly."""
    _, (onsets, beats, spans, quantized, positions) = _laid_back_line(0.2)
    exact = replay_onsets(quantized, positions, beats, spans, restore_residual=True)
    assert max(abs(a - b) for a, b in zip(exact, onsets, strict=True)) < 1e-9
    notation = replay_onsets(quantized, positions, beats, spans)
    beat = beats[1] - beats[0]
    # Beat 6's downbeat is notated ON the beat and replays 0.2 late. (The
    # replay positions carry the lag, so the note is found by its notation.)
    played = [
        r
        for r, p, q in zip(notation, positions, quantized, strict=True)
        if int(p) == 6 and abs(q.beat - 6.0) < 1e-9
    ]
    assert len(played) == 1
    assert abs(played[0] - (beats[6] + 0.2 * beat)) < 1e-6


def test_line_lag_is_a_capped_window_median_that_never_moves_a_note_before_its_beat():
    from swingscribe.stages.quantize import line_lag

    raw = {i: [0.2, 0.45, 0.7] for i in range(10)}
    raw[4] = [0.05, 0.3]  # one beat nearly on time
    raw[5] = [0.6]  # no downbeat candidate at all
    lags = line_lag(raw, window=4, cap=0.2)
    assert abs(lags[2] - 0.2) < 1e-9
    assert abs(lags[4] - 0.05) < 1e-9  # never more than the beat's own first onset
    assert abs(lags[5] - 0.2) < 1e-9  # a beat without a downbeat still lags with its line
    # A beat whose downbeat was pushed -- played at the end of the beat
    # before -- is not shifted onto it.
    pushed = {i: [0.2, 0.45, 0.7] for i in range(10)}
    pushed[6] = [0.2, 0.9]
    assert 7 not in line_lag(pushed, window=4, cap=0.2)
    assert abs(line_lag(pushed, window=4, cap=0.2)[8] - 0.2) < 1e-9
    # The cap.
    assert abs(line_lag({i: [0.3] for i in range(10)}, 4, 0.2)[3] - 0.2) < 1e-9
    # One "e" among on-time beats moves nothing, and nothing goes negative.
    on_time = {i: [0.0, 0.5] for i in range(10)}
    on_time[5] = [0.25, 0.5]
    assert line_lag(on_time, 4, 0.2) == {}
    # A line that scatters both ways is not late: the downbeat played early
    # sits at the END of the previous beat and counts against the lag.
    scatter = {i: [0.06, 0.5, 0.94] for i in range(10)}
    assert line_lag(scatter, 4, 0.2) == {}
    # Under the floor it is scatter.
    slight = {i: [0.05, 0.55] for i in range(10)}
    assert abs(line_lag(slight, 4, 0.2)[4] - 0.05) < 1e-9
    assert line_lag(slight, 4, 0.2, floor=0.08) == {}
    # Too few candidates is no evidence; a window of 0 is off.
    assert line_lag({0: [0.2], 1: [0.2]}, 4, 0.2) == {}
    assert line_lag(raw, 0, 0.2) == {}


def test_the_lag_is_on_by_default_in_the_config():
    from swingscribe.config import QuantizeConfig

    assert QuantizeConfig().lag_window_beats == 4
    assert QuantizeConfig().lag_cap == 0.2
    assert QuantizeConfig().lag_floor == 0.08


# ── the sixteenth triplet: six to the beat (docs/notation-survey.md, D35.2) ──


def test_three_notes_in_half_a_beat_are_read_on_sixths():
    """A sixteenth triplet at (0.5, 2/3, 5/6) after a note on the beat: the
    sixteenth grid cannot keep the last two apart, so the finer grids are
    offered, and sixths fit exactly where 32nds would write 0.625 and 0.875."""
    from swingscribe.stages.quantize import choose_reading

    figure = [0.0, 0.5, 2 / 3, 5 / 6]
    assert choose_reading(figure, (2, 4, 3, 6, 8), 3, 0.02, raw_offsets=figure, inside=True) == (
        6,
        "raw",
    )
    # Without the six-per-beat grid on offer, it is a 32nd figure.
    assert choose_reading(figure, (2, 4, 3, 8), 3, 0.02, raw_offsets=figure, inside=True)[0] == 8
    # Inside is judged on sixths: 5/6 is inside on the six grid although the
    # thirds grid would send it to the next beat.
    assert choose_reading(figure, (2, 4, 3, 6), 3, 0.02, raw_offsets=figure, inside=True)[0] == 6


def test_the_six_grid_is_offered_only_where_sixteenths_cannot_keep_the_beat_apart():
    beat = 0.4
    beats = [i * beat for i in range(16)]
    onsets = []
    for i in range(2, 14):
        if i == 8:
            onsets.extend(beats[i] + f * beat for f in (0.0, 0.5, 2 / 3, 5 / 6))
        else:
            onsets.extend(beats[i] + f * beat for f in (0.0, 0.5))
    spans = swing_spans(onsets, beats)
    on, positions = quantize_notes(
        onsets,
        [0.05] * len(onsets),
        [60] * len(onsets),
        beats,
        spans,
        [],
        tuplet_needs_onsets_inside=True,
        sixteenth_triplets=True,
    )
    read = sorted(round(q.beat, 3) for q, p in zip(on, positions, strict=True) if 8 <= p < 9)
    assert read == [8.0, 8.5, 8.667, 8.833]
    off, positions = quantize_notes(
        onsets,
        [0.05] * len(onsets),
        [60] * len(onsets),
        beats,
        spans,
        [],
        tuplet_needs_onsets_inside=True,
        sixteenth_triplets=False,
    )
    read = sorted(round(q.beat, 3) for q, p in zip(off, positions, strict=True) if 8 <= p < 9)
    assert read == [8.0, 8.5, 8.625, 8.875]
    # The swung pairs around it are untouched either way.
    assert sorted(round(q.beat, 3) for q, p in zip(on, positions, strict=True) if 6 <= p < 7) == [
        6.0,
        6.5,
    ]


def test_sixteenth_triplets_are_off_by_default_in_the_config():
    """Measured and rejected on the pages (docs/wjazz-quantize.md): the
    reading exists for when a figure deserves it."""
    from swingscribe.config import QuantizeConfig

    assert QuantizeConfig().sixteenth_triplets is False


# ── a ballad beat is offered the finer grids outright (docs/wjazz-quantize.md) ──


def _ballad_beat(slow_beat_s: float, grids=(6, 8, 12)):
    """A 64 bpm line: swung pairs, and beat 8 holding six even notes."""
    beat = 0.94
    beats = [i * beat for i in range(16)]
    onsets = []
    for i in range(2, 14):
        if i == 8:
            onsets.extend(beats[i] + k / 6 * beat for k in range(6))
        else:
            onsets.extend(beats[i] + f * beat for f in (0.0, 0.5))
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets,
        [0.05] * len(onsets),
        [60] * len(onsets),
        beats,
        spans,
        [],
        tuplet_needs_onsets_inside=True,
        slow_beat_s=slow_beat_s,
        slow_beat_grids=grids,
    )
    return sorted(round(q.beat, 3) for q, p in zip(quantized, positions, strict=True) if 8 <= p < 9)


def test_a_ballad_beat_of_six_is_written_on_sixths():
    assert _ballad_beat(0.6) == [8.0, 8.167, 8.333, 8.5, 8.667, 8.833]
    # Off, the sixteenth grid merges pairs, the 32nd grid is admitted on that
    # evidence, and the six notes land on 32nds a sliver off.
    assert _ballad_beat(0.0) == [8.0, 8.125, 8.375, 8.5, 8.625, 8.875]
    # A beat shorter than the threshold is not a ballad beat.
    assert _ballad_beat(1.5) == [8.0, 8.125, 8.375, 8.5, 8.625, 8.875]


def test_the_ballad_grids_ship_off():
    """R31 shipped on at 86 bpm and under, judged only against WJazzD's
    tatum layer -- Flex-Q's quantisation of the onsets, not a transcriber's
    page (D36, 2026-09-23). Off until a human ballad page says otherwise;
    the mechanism and its grids stay for that measurement."""
    from swingscribe.config import QuantizeConfig

    assert QuantizeConfig().slow_beat_s == 0.0
    assert QuantizeConfig().slow_beat_grids == (6, 8, 12)


def test_a_ballad_is_a_tempo_not_a_long_beat():
    """One stretched beat inside a fast line does not make a ballad: the
    median beat decides, so a slipped or half-rate stretch is not offered
    the ballad grids."""
    beat = 0.4
    beats = [i * beat for i in range(16)]
    beats[9:] = [beats[8] + 0.94 + (i - 9) * beat for i in range(9, 16)]  # beat 8 is 0.94 s
    onsets = []
    for i in range(2, 14):
        if i == 8:
            onsets.extend(beats[i] + k / 6 * (beats[9] - beats[8]) for k in range(6))
        else:
            onsets.extend(beats[i] + f * beat for f in (0.0, 0.5))
    spans = swing_spans(onsets, beats)
    quantized, positions = quantize_notes(
        onsets,
        [0.05] * len(onsets),
        [60] * len(onsets),
        beats,
        spans,
        [],
        tuplet_needs_onsets_inside=True,
        slow_beat_s=0.7,
    )
    read = sorted(round(q.beat, 3) for q, p in zip(quantized, positions, strict=True) if 8 <= p < 9)
    assert read == [8.0, 8.125, 8.375, 8.5, 8.625, 8.875]


# ── the figure prior ────────────────────────────────────────────────────


def _prior_figure_beat(weight: float, next_beat_downbeat: bool = False) -> list[float]:
    """Sixteen beats at 120 bpm of straight eighth pairs (no swing span, lag
    off), except beat 8, which holds onsets at 0, 0.5 and 0.8 of the beat,
    and beat 9, which holds a lone note on its "and" -- or, with
    `next_beat_downbeat`, on its beat line. On snap error alone beat 8's
    sixteenth grid wins by a hair: 0.0167 beats of mean error against the
    eighth grid's 0.0667, with 0.04 beats of slack (0.02 s at 0.5 s a beat).
    The figure it writes, `0 1/2 3/4`, is 1.2% of a human's beats; the
    eighth grid's `0 1/2` is 55%, with the late note pushed to beat 9's line."""
    from swingscribe.stages.quantize import figure_prior

    figure_prior.cache_clear()
    beats = [i * 0.5 for i in range(17)]
    onsets: list[float] = []
    for index, b in enumerate(beats[:-1]):
        if index == 8:
            fractions = (0.0, 0.5, 0.8)
        elif index == 9:
            fractions = (0.0,) if next_beat_downbeat else (0.5,)
        else:
            fractions = (0.0, 0.5)
        onsets.extend(b + f * 0.5 for f in fractions)
    first = 8 * 2  # beats 0-7 hold two onsets each
    quantized, _positions = quantize_notes(
        onsets,
        [0.05] * len(onsets),
        [60] * len(onsets),
        beats,
        [],
        [],
        grid_slack_s=0.02,
        figure_prior_weight=weight,
    )
    assert len(quantized) == len(onsets)
    return [round(q.beat, 3) for q in quantized[first : first + 3]]


def test_the_figure_prior_writes_a_rare_figure_on_the_coarser_grid():
    """A beat whose snap error prefers the sixteenth grid by a hair and whose
    figure the table calls rare is written on the eighth grid with the
    weight on, and unchanged with it at zero. No meter section, so `beat`
    is the absolute position: beat 8 of the grid."""
    assert _prior_figure_beat(0.0) == [8.0, 8.5, 8.75]  # the dotted figure, on snap error
    assert _prior_figure_beat(0.01) == [8.0, 8.5, 9.0]  # the pair; the late note is beat 9's


def test_the_figure_prior_never_pushes_a_note_onto_an_occupied_beat_line():
    """The same beat when beat 9 has its own note on the line: the eighth
    reading would write two notes on one position across the bar line, so
    it is refused as a merging grid is, and the sixteenth stays."""
    assert _prior_figure_beat(0.0, next_beat_downbeat=True) == [8.0, 8.5, 8.75]
    assert _prior_figure_beat(0.01, next_beat_downbeat=True) == [8.0, 8.5, 8.75]


def test_the_figure_prior_table_ships_and_reads():
    from swingscribe.stages.quantize import figure_of, figure_prior, figure_surprisal

    table, unseen = figure_prior()
    assert table["0 1/2"] < table["0"] < table["0 1/3 2/3"] < table["0 3/4"] < unseen
    assert all(s > 0 for s in table.values())
    assert figure_of([0.0, 0.52], 2) == "0 1/2"
    assert figure_of([0.1, 0.34, 0.65], 3) == "0 1/3 2/3"
    assert figure_of([0.9], 2) == "-"  # pushed onto the next beat: nothing left here
    assert figure_of([0.0, 0.0], 4) == "0"  # one figure, however many onsets share it
    assert figure_surprisal("0 1/2", (table, unseen)) == table["0 1/2"]
    assert figure_surprisal("0 1/8 1/3 5/7", (table, unseen)) == unseen


def test_the_figure_prior_ships_on_and_off_costs_nothing():
    config = Config()
    assert config.quantize.figure_prior_weight == 0.015  # R33
    assert _prior_figure_beat(0.0) == _prior_figure_beat(-1.0)
