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


def test_the_same_figure_is_written_finer_on_a_slow_beat():
    """D11: the slack is a time budget, so the SAME beat-fraction figure gets
    a finer grid on a long beat than a short one — the direction of WJazzD's
    tempo staircase (16ths under 120 bpm, eighths over 160, across 456 solos,
    while the interval in SECONDS stays put).

    The figure: an offbeat landing at 0.68 of its beat. On a ballad beat
    (60 bpm, 1s) that placement is ~180ms from the eighth position — a real
    dotted rhythm, written to the sixteenth grid. On a burner's beat
    (200 bpm, 300ms) the same fraction is ~54ms of lateness — a played
    eighth pair, written as one. A constant slack in beats cannot say both.
    """

    def second_note_beat(bpm):
        period = 60.0 / bpm
        beats = [i * period for i in range(6)]
        onsets = [beats[1], beats[1] + 0.68 * period]
        quantized, _ = quantize_notes(onsets, [0.05, 0.05], [60, 62], beats, [], [])
        assert len(quantized) == 2
        return quantized[1].beat - int(quantized[1].beat)

    assert second_note_beat(60.0) == pytest.approx(0.75)  # sixteenth grid: dotted figure
    assert second_note_beat(200.0) == pytest.approx(0.5)  # eighth grid: an eighth pair
