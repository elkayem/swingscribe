"""Bar-grid derivation. Pure and stdlib-only, so this all runs in CI.

Cases are built from synthetic grids whose right answer is known, including
reproductions of the two failure modes measured on real tracks: a tracker that
drops to half rate for a passage, and a downbeat layer that is noise.
"""

import random

import pytest

from swingscribe.config import Config, MeterConfig
from swingscribe.model import BeatGrid, Document
from swingscribe.stages import meter


def steady(count: int, ibi: float = 0.5, start: float = 0.0) -> list[float]:
    return [round(start + i * ibi, 6) for i in range(count)]


# ── time signatures ─────────────────────────────────────────────────────────


def test_pulses_per_bar_is_not_always_the_numerator():
    """6/8 in 2 has two dotted-quarter pulses, not six. Conflating the two would
    draw bars three times too short."""
    assert meter.resolve_meter(MeterConfig(time_signature="4/4")) == ((4, 4), 4)
    assert meter.resolve_meter(MeterConfig(time_signature="3/4")) == ((3, 4), 3)
    assert meter.resolve_meter(MeterConfig(time_signature="6/8")) == ((6, 8), 2)
    assert meter.resolve_meter(MeterConfig(time_signature="6/4")) == ((6, 4), 6)


def test_pulses_per_bar_can_be_overridden():
    # The same 6/8 counted in 6 rather than in 2.
    signature, pulses = meter.resolve_meter(MeterConfig(time_signature="6/8", pulses_per_bar=6))
    assert (signature, pulses) == ((6, 8), 6)


def test_unlisted_signature_is_parsed_not_refused():
    assert meter.resolve_meter(MeterConfig(time_signature="7/8")) == ((7, 8), 7)


def test_nonsense_signature_raises():
    with pytest.raises(ValueError):
        meter.resolve_meter(MeterConfig(time_signature="banana"))


def test_default_is_four_four():
    assert meter.resolve_meter(MeterConfig()) == ((4, 4), 4)


# ── beat repair ─────────────────────────────────────────────────────────────


def test_steady_grid_needs_no_repair():
    beats = meter.repair_beats(steady(40), MeterConfig())
    assert len(beats) == 40
    assert not any(b.implied for b in beats)


def test_single_dropped_beat_is_restored():
    """One missed beat shifts every later bar line by one beat, so this is
    correctness rather than cosmetics."""
    times = steady(40)
    del times[20]
    beats = meter.repair_beats(times, MeterConfig())
    assert len(beats) == 40
    assert sum(1 for b in beats if b.implied) == 1
    restored = next(b for b in beats if b.implied)
    assert restored.time == pytest.approx(10.0)


def test_half_rate_passage_is_subdivided():
    """The Corner Pocket case: the tracker finds only every other beat for the
    opening, so the local median there is itself the wrong rate. A purely local
    test cannot see this; the reference pulse must be seeded globally."""
    intro = [round(i * 1.0, 6) for i in range(20)]  # every other beat
    body = [round(20.0 + i * 0.5, 6) for i in range(80)]
    beats = meter.repair_beats(intro + body, MeterConfig())

    intro_beats = [b for b in beats if b.time < 19.5]
    gaps = [round(b.time - a.time, 3) for a, b in zip(intro_beats, intro_beats[1:], strict=False)]
    assert set(gaps) == {0.5}  # intro now runs at the true rate
    # 19 gaps inside the intro plus the one at the junction into the body,
    # which the tracker also missed.
    assert sum(1 for b in beats if b.implied) == 20


def test_repair_follows_tempo_drift():
    """Implied beats are placed by subdividing the observed gap, not by
    extrapolating a fixed grid, so a tune that speeds up stays aligned."""
    times = [0.0]
    ibi = 0.60
    for _ in range(60):
        times.append(round(times[-1] + ibi, 6))
        ibi *= 0.995  # gradual accelerando
    dropped = times[:30] + times[31:]
    beats = meter.repair_beats(dropped, MeterConfig())
    restored = next(b for b in beats if b.implied)
    assert restored.time == pytest.approx(times[30], abs=0.02)


def test_a_long_hole_is_not_filled_with_invented_beats():
    """A twenty-second silence is a hole in the tracking, not a run of missed
    beats; inventing forty beats there would be a lie."""
    times = steady(30) + [40.0 + i * 0.5 for i in range(30)]
    beats = meter.repair_beats(times, MeterConfig())
    assert sum(1 for b in beats if b.implied) == 0


def test_repair_can_be_switched_off():
    times = steady(40)
    del times[20]
    beats = meter.repair_beats(times, MeterConfig(repair_beats=False))
    assert len(beats) == 39


def test_single_doubled_beat_is_dropped():
    """The mirror of the dropped beat, and the same harm: Billy Boy's bar 107
    held three tracked beats where two belong, and every bar after it started a
    beat early. Each short interval rounds to one pulse on its own, so the pair
    has to be judged together."""
    times = steady(40)
    times.insert(21, 10.25)  # between 10.0 and 10.5
    beats = meter.repair_beats(times, MeterConfig())
    assert [b.time for b in beats] == steady(40)
    assert not any(b.implied for b in beats)


def test_the_billy_boy_bar_is_repaired_to_four_beats():
    """The measured shape: 0.200, 0.140, 0.140, 0.220 s on a 0.220 s pulse."""
    head = steady(20, ibi=0.22)
    bar_start = head[-1]
    bar = [round(bar_start + t, 6) for t in (0.200, 0.340, 0.480, 0.700)]  # five beats, 0.70 s
    tail = steady(9, ibi=0.22, start=round(bar[-1] + 0.22, 6))
    times = head + bar + tail
    beats = meter.repair_beats(times, MeterConfig())
    intervals = [b.time - a.time for a, b in zip(beats, beats[1:], strict=False)]
    assert len(beats) == len(times) - 1
    assert not any(b.implied for b in beats)
    assert max(intervals) < 0.30 and min(intervals) > 0.19


def test_a_run_tracked_at_double_rate_is_thinned_to_the_pulse():
    """R26: this used to be 'a genuine double-time run is not thinned'. It was
    measured the other way -- Curtis Fuller's Blue Train, both Sidewinders,
    Totem Pole and Cheese Cake are tracked at double rate for a tenth to a
    half of the solo, 33 to 91 beats the annotator does not have, and no run
    of halves anywhere in the three benchmarks was the band's."""
    times = steady(21) + [10.0 + 0.25 * k for k in range(1, 16)] + steady(20, start=14.0)
    beats = meter.repair_beats(times, MeterConfig())
    assert [b.time for b in beats] == steady(48)
    assert not any(b.implied for b in beats)


def test_a_swung_doubled_run_is_thinned():
    """Cheese Cake's shape at 221 bpm: the tracker's extra beat sits on the
    swung offbeat, 0.18 + 0.10 s on a 0.28 s pulse, for bars at a time. The
    two halves are unequal, so neither reads as half a pulse on its own; the
    pair reads as one."""
    head = steady(30, ibi=0.28)
    run = []
    t = head[-1]
    for _ in range(12):
        run += [round(t + 0.18, 6), round(t + 0.28, 6)]
        t = round(t + 0.28, 6)
    tail = steady(30, ibi=0.28, start=round(t + 0.28, 6))
    beats = meter.repair_beats(head + run + tail, MeterConfig())
    intervals = [round(b.time - a.time, 3) for a, b in zip(beats, beats[1:], strict=False)]
    assert set(intervals) == {0.28}
    assert not any(b.implied for b in beats)


def test_a_ghost_beat_before_a_real_one_is_dropped_even_in_a_run():
    """My Favorite Things' shape: a beat 80 ms before a real one, 0.26 + 0.08
    on a 0.34 s pulse, again and again. The long half is over 0.75 of the
    pulse, so it is not a short pair; the pair is one pulse."""
    times = steady(20, ibi=0.34)
    t = times[-1]
    for _ in range(6):
        times += [round(t + 0.26, 6), round(t + 0.34, 6), round(t + 0.68, 6)]
        t = round(t + 0.68, 6)
    beats = meter.repair_beats(times, MeterConfig())
    intervals = [round(b.time - a.time, 3) for a, b in zip(beats, beats[1:], strict=False)]
    assert set(intervals) == {0.34}


def test_a_passage_at_another_tempo_is_not_thinned():
    """Twenty intervals at 0.6 of the pulse are a tempo, not doubled beats: no
    pair of them makes one pulse, and no pair is isolated."""
    times = steady(21) + [round(10.0 + 0.3 * k, 6) for k in range(1, 21)] + steady(20, start=16.5)
    beats = meter.repair_beats(times, MeterConfig())
    assert len(beats) == len(times)


def test_a_short_pair_in_a_ragged_passage_is_left_alone():
    """Without ordinary intervals on both sides, and with no pair making one
    pulse, there is no pulse to say a short interval is wrong; a rubato
    passage must not be edited into steadiness."""
    times = [0.0, 0.5, 1.0, 1.4, 1.7, 2.15, 2.9, 3.4, 3.9]
    beats = meter.repair_beats(times, MeterConfig())
    assert 1.7 in [b.time for b in beats]
    assert 2.15 in [b.time for b in beats]


def shade_of_jade(head: list[float] | None = None) -> tuple[list[float], float]:
    """The measured shape, R34 (113.76-114.72 s on A Shade of Jade): a
    0.227 s pulse, and one bar run 6% slow whose third beat the tracker found
    twice, 80 ms apart -- 0.20, 0.22, 0.08, 0.24, 0.22 s, no pair of which
    reads as one pulse. (times, the ghost)"""
    head = head or steady(24, ibi=0.227)
    t = head[-1]
    bar = [round(t + x, 6) for x in (0.20, 0.42, 0.50, 0.74, 0.96)]
    tail = steady(24, ibi=0.227, start=round(bar[-1] + 0.227, 6))
    return head + bar + tail, bar[1]


def test_a_ghost_the_pair_test_cannot_see_is_dropped_by_the_metronome():
    """Twice in five bars on A Shade of Jade, and the page sat half a bar off
    for the rest of the solo. The pair test keeps both crowded beats (either
    one dropped leaves 1.4 pulses); the count across two bars either side
    says the bar holds four beats, not five. Of the pair, the one farther
    from an even beat between its neighbours goes."""
    times, ghost = shade_of_jade()
    assert meter.drop_doubled_beats(times, 0.15) == times  # the hole this closes
    beats = meter.repair_beats(times, MeterConfig())
    assert [b.time for b in beats] == [t for t in times if t != ghost]
    assert not any(b.implied for b in beats)


def test_the_metronome_reads_a_ghost_as_one_beat_too_many():
    times = steady(40, ibi=0.25)
    assert meter.metronome_jump(times, 19, 20) == pytest.approx(0.0, abs=1e-9)
    ghosted = times[:21] + [round(times[20] + 0.08, 6)] + times[21:]
    assert meter.metronome_jump(ghosted, 19, 22) == pytest.approx(1.0, abs=0.05)
    dropped = times[:20] + times[21:]
    assert meter.metronome_jump(dropped, 19, 20) == pytest.approx(-1.0, abs=0.05)


def test_two_real_beats_tracked_close_together_are_both_kept():
    """0.69 + 0.12 + 0.69 s on a 0.5 s pulse: the time holds three intervals
    and the grid has three, so the pair is two displaced beats, not a ghost.
    Dropping one would lose a beat."""
    times = [*steady(20), 10.19, 10.31, *steady(20, start=11.0)]
    beats = meter.repair_beats(times, MeterConfig())
    assert len(beats) == len(times)


def test_a_ghost_in_a_ragged_passage_is_left_alone():
    """No metronome to read: a side whose own intervals wander past a third of
    its pulse is not steady, and a rubato passage must not be counted."""
    rng = random.Random(7)
    ragged = [0.0]
    for _ in range(24):
        ragged.append(round(ragged[-1] + 0.227 * rng.choice((0.6, 1.0, 1.45)), 6))
    times, ghost = shade_of_jade(head=ragged)
    k = times.index(ghost)
    assert meter.metronome_jump(times, k - 1, k + 2) is None
    beats = meter.repair_beats(times, MeterConfig())
    assert ghost in [b.time for b in beats]


def test_a_ghost_at_a_change_of_tempo_is_left_alone():
    """Two sides at different tempi are not one metronome."""
    left = steady(20, ibi=0.5)
    right = steady(20, ibi=0.35, start=11.0)
    times = [*left, 10.42, 10.5, *right]
    assert meter.metronome_jump(times, 19, 22) is None
    assert 10.42 in [b.time for b in meter.repair_beats(times, MeterConfig())]


def test_a_steady_grid_and_a_mended_ghost_raise_no_doubt():
    assert meter.grid_doubts(meter.repair_beats(steady(60), MeterConfig())) == []
    times, _ghost = shade_of_jade()
    assert meter.grid_doubts(meter.repair_beats(times, MeterConfig())) == []


def test_a_ghost_the_metronome_cannot_read_is_a_doubt():
    """R34's tracking half: a slip the repair leaves is reported where it is,
    with the metronome's silence (None) rather than a guess."""
    rng = random.Random(7)
    ragged = [0.0]
    for _ in range(24):
        ragged.append(round(ragged[-1] + 0.227 * rng.choice((0.6, 1.0, 1.45)), 6))
    times, ghost = shade_of_jade(head=ragged)
    doubts = meter.grid_doubts(meter.repair_beats(times, MeterConfig()))
    assert any(d.start <= ghost <= d.end and d.jump is None for d in doubts)


def test_jitter_is_not_a_doubt():
    """0.18 + 0.28 s pairs on a 0.227 s pulse: the tracker's 20 ms frames,
    not a count."""
    times = [0.0]
    for k in range(60):
        step = (0.18 if k % 2 else 0.28) if 20 <= k < 30 else 0.23
        times.append(round(times[-1] + step, 6))
    assert meter.grid_doubts(meter.repair_beats(times, MeterConfig())) == []


def test_a_stretch_tracked_one_beat_long_is_a_doubt_the_metronome_sizes():
    """Four beats heard as five over a bar, with steady bars either side: the
    metronome reads one beat too many."""
    head = steady(20, ibi=0.5)
    bar = [round(head[-1] + 0.4 * k, 6) for k in range(1, 6)]  # 5 intervals in 2.0 s
    tail = steady(20, ibi=0.5, start=round(bar[-1] + 0.5, 6))
    beats = [meter.Beat(t) for t in head + bar + tail]  # as the repair would leave it
    doubts = meter.grid_doubts(beats)
    assert len(doubts) == 1
    assert doubts[0].kept - doubts[0].held == pytest.approx(1.0, abs=0.35)
    assert doubts[0].jump == pytest.approx(1.0, abs=0.1)


def test_downbeat_marks_that_keep_their_phase_settle_a_doubt():
    """The tracker's marks every four beats on both sides of a doubted stretch
    whose count is right: settled. The same marks a beat apart on the far
    side -- the grid slipped -- leave it reported. Nothing moves either way."""
    head = steady(24)
    t = head[-1]
    times = [*head, round(t + 0.667, 6), round(t + 1.333, 6), *steady(24, start=round(t + 2.0, 6))]
    beats = [meter.Beat(x) for x in times]  # three intervals where four belong
    assert meter.grid_doubts(beats)
    on_count = [beats[i].time for i in range(0, len(beats), 4)]
    slipped = [b for b in on_count if b < t] + [beats[i].time for i in range(26, len(beats), 4)]
    kept = [b for b in on_count if b < t] + [beats[i].time for i in range(28, len(beats), 4)]
    assert meter.grid_doubts(beats, downbeats=kept) == []
    assert meter.grid_doubts(beats, downbeats=slipped)
    assert meter.grid_doubts(beats, downbeats=kept[:2]) == meter.grid_doubts(beats)


def test_a_ragged_stretch_two_beats_long_is_thinned_by_the_metronome():
    """Totem Pole's shape (R34): seven pulses tracked as nine ragged
    intervals between steady bars, no pair of which reads as one pulse or as
    a ghost. Two bars either side say the stretch holds two beats too many,
    so it is re-laid at seven, keeping the tracker's beats that sit on the
    new subdivision."""
    head = steady(24, ibi=0.44)
    t = head[-1]
    ragged = [round(t + x, 6) for x in (0.30, 0.62, 1.00, 1.30, 1.66, 2.00, 2.40, 2.72)]
    end = round(t + 7 * 0.44, 6)
    tail = steady(24, ibi=0.44, start=end)
    beats = meter.repair_beats(head + ragged + tail, MeterConfig())
    inside = [b.time for b in beats if t < b.time < end]
    assert len(inside) == 6  # seven intervals
    assert meter.grid_doubts(beats) == []
    assert not any(b.relaid for b in beats)


def test_thinning_never_adds_a_beat():
    """A stretch one beat SHORT (four pulses tracked as three intervals) is
    left to the doubt list: the metronome only ever takes beats out."""
    head = steady(24, ibi=0.5)
    t = head[-1]
    times = [*head, round(t + 0.667, 6), round(t + 1.333, 6), *steady(24, start=round(t + 2.0, 6))]
    beats = meter.repair_beats(times, MeterConfig())
    assert len(beats) == len(times)
    assert any(d.jump is not None and d.jump < -0.5 for d in meter.grid_doubts(beats))


def test_reference_pulse_holds_through_a_double_rate_stretch():
    """The reference the pair test needs: a rolling median that followed the
    halves called every one of them a beat."""
    intervals = [0.5] * 20 + [0.25] * 30 + [0.5] * 20
    reference = meter.reference_pulse(intervals)
    assert all(abs(r - 0.5) < 1e-9 for r in reference)
    # and it still follows a half-rate stretch down to the true pulse
    intervals = [0.5] * 20 + [1.0] * 30 + [0.5] * 20
    reference = meter.reference_pulse(intervals)
    assert all(abs(r - 0.5) < 1e-9 for r in reference)
    # and it still follows a genuine change of tempo, as it always did
    intervals = [0.5] * 20 + [0.65] * 30
    assert meter.reference_pulse(intervals)[-1] == pytest.approx(0.65)


def _half_rate_grid(fine_runs: int = 3) -> tuple[list[float], list[float]]:
    """Brother Hubbard's shape: a 0.4 s pulse tracked at 0.8 s for most of the
    track, the true pulse surfacing in runs. The tracker's downbeat layer
    marks every second grid beat in the coarse stretches (a 4/4 bar at half
    rate) and every fourth in the fine ones. Returns (beats, downbeats)."""
    beats: list[float] = []
    downbeats: list[float] = []
    t = 0.0
    for run in range(fine_runs * 2 + 1):
        if run % 2 == 0:  # coarse stretch: 40 beats at 0.8 s
            for k in range(40):
                beats.append(round(t, 6))
                if k % 2 == 0:
                    downbeats.append(round(t, 6))
                t += 0.8
        else:  # fine stretch: 40 beats at 0.4 s
            for k in range(40):
                beats.append(round(t, 6))
                if k % 4 == 0:
                    downbeats.append(round(t, 6))
                t += 0.4
    return beats, downbeats


def test_a_grid_at_half_rate_with_the_pulse_surfacing_is_subdivided_to_it():
    """R32: the seed is the tracker's octave, and on Brother Hubbard, Adam's
    Apple and Nothing Personal it was the wrong one -- R26's thinning then
    took out the true pulse wherever it surfaced (Brother Hubbard 100 beats
    short of the annotator's over the solo). The downbeat layer says which
    octave is the bar: marks every second grid beat where the grid is coarse."""
    beats, downbeats = _half_rate_grid()
    assert meter.pulse_octave(beats, downbeats) == pytest.approx(0.4)
    repaired = meter.repair_beats(beats, MeterConfig(), downbeats)
    intervals = [round(b.time - a.time, 3) for a, b in zip(repaired, repaired[1:], strict=False)]
    assert set(intervals) == {0.4}
    # the surfaced beats are the tracker's; only the coarse gaps were filled
    assert sum(b.implied for b in repaired) == 4 * 39 + 3
    assert all(not b.implied for b in repaired if b.time in set(beats))


def test_a_double_rate_stretch_under_downbeats_in_fours_is_still_thinned():
    """Blue Train's shape with its downbeat layer: the marks come every four
    coarse beats, so the coarse pulse is the bar's and the halves are the
    tracker's, exactly as R26 measured."""
    times = steady(21) + [10.0 + 0.25 * k for k in range(1, 16)] + steady(20, start=14.0)
    downbeats = [t for i, t in enumerate(steady(24)) if i % 4 == 0]
    assert meter.pulse_octave(times, downbeats) is None
    beats = meter.repair_beats(times, MeterConfig(), downbeats)
    assert [b.time for b in beats] == steady(48)


def test_marks_in_twos_alone_do_not_double_a_grid():
    """Embraceable You at 70 bpm: the downbeat layer marks every second beat
    (0.56 of its pairs) and no run of halves exists anywhere in the grid.
    A ballad is not doubled on the downbeat layer's word alone."""
    times = steady(120, ibi=0.86)
    downbeats = times[::2]
    assert meter.pulse_octave(times, downbeats) is None
    beats = meter.repair_beats(times, MeterConfig(), downbeats)
    assert [b.time for b in beats] == times


def test_the_octave_needs_enough_marks_to_be_believed():
    beats, downbeats = _half_rate_grid()
    assert meter.pulse_octave(beats, downbeats[:8]) is None
    assert meter.pulse_octave(beats, []) is None


def test_a_free_intro_whose_gaps_subdivide_neatly_still_gets_no_bars():
    """So What's rubato intro: the tracker's few beats there sit 1.6, 2.7
    and 3.7 pulses apart, and an even subdivision of any of those gaps is
    within a fraction of the pulse of itself. The gap has to be a whole
    number of pulses before the beats invented inside it can count."""
    rubato = [0.0, 0.8, 1.35, 2.15, 2.5, 3.85, 4.15, 4.45, 6.3]
    times = rubato + [round(9.0 + i * 0.5, 6) for i in range(60)]
    beats = meter.repair_beats(times, MeterConfig())
    spans = meter.metrical_spans(beats, MeterConfig())
    assert len(spans) == 1
    assert beats[spans[0][0]].time >= 6.3


def test_a_half_rate_intro_keeps_its_bars_under_the_whole_gap_test():
    """The Corner Pocket case again, through metrical_spans: every other beat
    found, every gap exactly two pulses, so the subdivided intro is a span."""
    intro = [round(i * 1.0, 6) for i in range(20)]
    body = [round(20.0 + i * 0.5, 6) for i in range(80)]
    beats = meter.repair_beats(intro + body, MeterConfig())
    spans = meter.metrical_spans(beats, MeterConfig())
    assert len(spans) == 1
    assert beats[spans[0][0]].time == pytest.approx(0.0)


# ── metrical spans ──────────────────────────────────────────────────────────


def test_steady_grid_is_one_span():
    beats = meter.repair_beats(steady(60), MeterConfig())
    assert meter.metrical_spans(beats, MeterConfig()) == [(0, 60)]


def test_free_passage_breaks_the_span():
    """Rubato is the absence of a span — there is no is_rubato flag anywhere."""
    rubato = [0.0, 0.9, 1.3, 2.6, 2.9, 4.4, 4.7, 5.0, 7.2]
    times = rubato + [round(9.0 + i * 0.5, 6) for i in range(60)]
    beats = meter.repair_beats(times, MeterConfig())
    spans = meter.metrical_spans(beats, MeterConfig())
    assert len(spans) == 1
    # Bars start only where the pulse does. The free opening gets none, and the
    # span begins on a beat the tracker actually found, not a manufactured one.
    assert beats[spans[0][0]].time >= 7.0
    assert not beats[spans[0][0]].implied


def test_single_wobble_does_not_split_the_grid():
    """One stumble should not punch a hole in the bar grid for the rest of the
    tune — measured on Gerry's Blues, which had two such 0.4s hiccups."""
    times = steady(80)
    times[40] += 0.12
    beats = meter.repair_beats(times, MeterConfig())
    assert len(meter.metrical_spans(beats, MeterConfig())) == 1


def test_a_real_hole_still_splits_even_though_beats_are_adjacent():
    """Where the tracker found nothing, the beats bracketing the hole are
    index-adjacent, so a bridge rule that only counted indices would merge
    straight across the passage that has no pulse."""
    times = steady(40) + [round(40.0 + i * 0.5, 6) for i in range(40)]
    beats = meter.repair_beats(times, MeterConfig())
    spans = meter.metrical_spans(beats, MeterConfig())
    assert len(spans) == 2


def test_fabricated_beats_cannot_vote_for_their_own_metricality():
    """Repair subdivides a wide gap into evenly spaced beats that look steady
    because they were manufactured that way. A span made mostly of those is not
    evidence of a pulse, so the length test counts detected beats only."""
    # Six real beats, wildly irregular, then a long steady passage.
    ragged = [0.0, 0.9, 1.3, 2.6, 2.9, 4.4]
    times = ragged + [round(20.0 + i * 0.5, 6) for i in range(60)]
    beats = meter.repair_beats(times, MeterConfig())
    spans = meter.metrical_spans(beats, MeterConfig())
    assert all(beats[a].time >= 20.0 for a, _b in spans)


def test_short_runs_get_no_bars():
    beats = meter.repair_beats([0.0, 0.5, 1.0, 1.5], MeterConfig())
    assert meter.metrical_spans(beats, MeterConfig(min_span_beats=8)) == []


# ── extending to the track edges ────────────────────────────────────────────


def test_grid_extends_into_a_head_with_no_detected_beats():
    """The Corner Pocket case: the audio is at full level from 0.0s but the
    tracker emits nothing until 5.86s, so without this the first bars are simply
    missing. The head is in tempo; the tracking starts late."""
    beats = meter.repair_beats(steady(60, start=6.0), MeterConfig())
    extended = meter.extend_beats(beats, MeterConfig(), 0.0, 40.0)
    assert extended[0].time < 0.6
    assert extended[0].extrapolated
    assert all(b.implied for b in extended if b.extrapolated)


def test_extension_is_capped_so_a_free_intro_stays_bare():
    beats = meter.repair_beats(steady(60, start=90.0), MeterConfig())
    extended = meter.extend_beats(beats, MeterConfig(max_extend_seconds=5.0), 0.0, 200.0)
    assert extended[0].time == pytest.approx(85.0, abs=0.6)


def test_extension_refuses_an_unsteady_edge():
    """Only a pulse already shown to be steady may be continued outward."""
    ragged = [10.0, 10.9, 11.3, 12.6, 12.9] + [round(14.0 + i * 0.5, 6) for i in range(50)]
    beats = meter.repair_beats(ragged, MeterConfig())
    extended = meter.extend_beats(beats, MeterConfig(), 0.0, 60.0)
    assert extended[0].time == beats[0].time  # nothing prepended


def test_extension_can_be_switched_off():
    beats = meter.repair_beats(steady(60, start=6.0), MeterConfig())
    same = meter.extend_beats(beats, MeterConfig(extend_to_edges=False), 0.0, 40.0)
    assert same[0].time == beats[0].time


def test_extrapolated_beats_may_bound_a_span_but_interpolated_ones_may_not():
    """Extrapolation deliberately continues a proven pulse, so it can anchor the
    grid; interpolation across a ragged gap is manufactured and cannot."""
    beats = meter.repair_beats(steady(60, start=6.0), MeterConfig())
    extended = meter.extend_beats(beats, MeterConfig(), 0.0, 40.0)
    spans = meter.metrical_spans(extended, MeterConfig())
    assert spans and extended[spans[0][0]].time < 0.6


# ── the form start ──────────────────────────────────────────────────────────


def test_form_start_makes_that_bar_number_one():
    """An intro is not part of the song structure, so bar 1 belongs where the
    tune starts, not where the audio does."""
    beats = meter.repair_beats(steady(40), MeterConfig())
    sections = meter.derive_sections(beats, [], MeterConfig(anchor=0.0))
    lines = meter.bar_lines(beats, sections, form_start=4.0)
    numbered = dict(lines)
    assert numbered[4.0] == 1
    assert numbered[2.0] == 0  # the intro bar before it
    assert numbered[6.0] == 2


def test_without_a_form_start_bar_one_is_the_first_bar_line():
    beats = meter.repair_beats(steady(40), MeterConfig())
    sections = meter.derive_sections(beats, [], MeterConfig(anchor=0.0))
    assert meter.bar_lines(beats, sections)[0][1] == 1


def test_form_start_snaps_to_the_nearest_bar_line():
    beats = meter.repair_beats(steady(40), MeterConfig())
    sections = meter.derive_sections(beats, [], MeterConfig(anchor=0.0))
    # 4.3s is nearest the bar line at 4.0, not the beat at 4.5.
    assert dict(meter.bar_lines(beats, sections, form_start=4.3))[4.0] == 1


# ── sections and bar lines ──────────────────────────────────────────────────


def test_bar_lines_land_every_pulses_per_bar_beats():
    beats = meter.repair_beats(steady(64), MeterConfig())
    config = MeterConfig(anchor=0.0)
    lines = meter.bar_lines(beats, meter.derive_sections(beats, [], config))
    assert [t for t, _n in lines][:4] == pytest.approx([0.0, 2.0, 4.0, 6.0])
    assert [n for _t, n in lines][:4] == [1, 2, 3, 4]


def test_moving_the_anchor_shifts_every_bar_line():
    """The whole point of the design: the downbeat is one parameter, so a click
    re-phases the entire tune rather than triggering re-analysis."""
    beats = meter.repair_beats(steady(64), MeterConfig())
    first = meter.bar_lines(beats, meter.derive_sections(beats, [], MeterConfig(anchor=0.0)))
    moved = meter.bar_lines(beats, meter.derive_sections(beats, [], MeterConfig(anchor=0.5)))
    assert [t for t, _ in moved][:3] == pytest.approx([0.5, 2.5, 4.5])
    assert len(first) == len(moved)


def test_three_four_gives_three_beat_bars():
    beats = meter.repair_beats(steady(60), MeterConfig())
    config = MeterConfig(time_signature="3/4", anchor=0.0)
    lines = meter.bar_lines(beats, meter.derive_sections(beats, [], config))
    assert [t for t, _ in lines][:3] == pytest.approx([0.0, 1.5, 3.0])


def test_anchor_snaps_to_the_nearest_beat():
    """Anchors are stored as times so they survive a re-tracked grid; a time
    that falls between beats must land on one, not offset the whole grid."""
    beats = meter.repair_beats(steady(40), MeterConfig())
    lines = meter.bar_lines(beats, meter.derive_sections(beats, [], MeterConfig(anchor=1.04)))
    assert [t for t, _ in lines][0] == pytest.approx(1.0)


def test_auto_anchor_uses_the_downbeat_layer_as_a_weak_hint():
    """The detected layer is noise, but biased noise — a better first guess than
    a coin flip, and one click fixes it."""
    beats = meter.repair_beats(steady(64), MeterConfig())
    # Mostly phase 1, with the spread of wrong answers the real layer shows.
    downbeats = [0.5, 2.5, 4.5, 6.5, 8.5, 10.5, 1.0, 7.0]
    sections = meter.derive_sections(beats, downbeats, MeterConfig())
    assert sections[0].anchor == pytest.approx(0.5)


def _slipped_track():
    """A 4/4 tune the tracker lost one beat of at 80 s: real downbeats fall on
    index phase 0 before the slip and phase 3 after it. The first part is the
    longer, so the whole-track vote is phase 0."""
    beats = meter.repair_beats(steady(240), MeterConfig())  # 120 s at 0.5 s a beat
    times = [b.time for b in beats]
    before = [times[i] for i in range(0, 160, 4)]
    after = [times[i] for i in range(163, 240, 4)]
    return beats, before + after


def test_the_automatic_downbeat_is_voted_around_the_span_not_over_the_track():
    """D32: one slipped beat anywhere shifts the phase of everything after it,
    and the whole-track majority describes the longer side -- which need not
    be the side the solo is on (53 of 63 WJazzD solos right, against 62)."""
    beats, downbeats = _slipped_track()
    whole = meter.derive_sections(beats, downbeats, MeterConfig())
    assert whole[0].anchor == pytest.approx(0.0)  # phase 0: the longer side's
    late_solo = meter.derive_sections(beats, downbeats, MeterConfig(), near=(95.0, 115.0))
    assert late_solo[0].anchor == pytest.approx(1.5)  # phase 3: the solo's own side
    early_solo = meter.derive_sections(beats, downbeats, MeterConfig(), near=(5.0, 25.0))
    assert early_solo[0].anchor == pytest.approx(0.0)


def test_a_span_with_too_few_marks_falls_back_to_the_whole_track():
    beats, downbeats = _slipped_track()
    sparse = [d for d in downbeats if d < 80.0] + [d for d in downbeats if d > 110.0][:2]
    sections = meter.derive_sections(beats, sparse, MeterConfig(), near=(100.0, 105.0))
    assert sections[0].anchor == pytest.approx(0.0)


def test_a_placed_downbeat_is_never_outvoted_and_bar_grid_passes_the_span_through():
    beats, downbeats = _slipped_track()
    placed = meter.derive_sections(beats, downbeats, MeterConfig(anchor=1.0), near=(90.0, 115.0))
    assert placed[0].anchor == pytest.approx(1.0)
    raw = [b.time for b in beats]
    _grid, sections = meter.bar_grid(raw, downbeats, MeterConfig(), 120.0, near=(90.0, 115.0))
    assert sections[0].anchor == pytest.approx(1.5)


def test_sections_carry_the_notated_signature_not_just_the_pulse():
    beats = meter.repair_beats(steady(64), MeterConfig())
    sections = meter.derive_sections(beats, [], MeterConfig(time_signature="6/8", anchor=0.0))
    assert sections[0].time_signature == (6, 8)
    assert sections[0].pulses_per_bar == 2


def test_no_beats_means_no_sections():
    assert meter.derive_sections([], [], MeterConfig()) == []


# ── the stage ───────────────────────────────────────────────────────────────


def test_stage_populates_document_meter(tmp_path):
    config = Config(cache_dir=tmp_path)
    document = Document(
        audio_path="x.wav",
        sample_rate=44100,
        beat_grid=BeatGrid(beats=steady(64), downbeats=[0.0, 2.0], beats_per_bar=4),
    )
    result = meter.run(document, config)
    assert len(result.meter) == 1
    assert result.meter[0].pulses_per_bar == 4


def test_stage_without_a_beat_grid_is_a_noop(tmp_path):
    document = Document(audio_path="x.wav", sample_rate=44100)
    assert meter.run(document, Config(cache_dir=tmp_path)).meter == []


def test_meter_is_a_cache_keyed_stage(tmp_path):
    """The overrides must reach the cache key — that is how a downbeat change
    reaches transcription instead of living in a UI side channel."""
    config = Config(cache_dir=tmp_path)
    assert "anchor" in config.stage_config("meter")
    moved = config.model_copy(update={"meter": config.meter.model_copy(update={"anchor": 3.0})})
    assert moved.stage_config("meter") != config.stage_config("meter")


def test_document_without_meter_still_deserializes():
    """Documents cached before this field existed must still load, or the
    introduction of meter would silently discard every separation."""
    old = '{"audio_path": "x.wav", "sample_rate": 44100}'
    assert Document.model_validate_json(old).meter == []


def test_bar_grid_is_the_repaired_extended_grid_and_its_sections():
    """`/beats` and the Export button both count bars from this one function,
    so it has to be exactly repair + extend + derive -- a grid the roll draws
    but export does not count on is the bug it exists to prevent."""
    tracked = steady(20, start=1.0)
    downbeats = [1.5, 3.5, 5.5]  # phase 1
    config = MeterConfig()
    beats, sections = meter.bar_grid(tracked, downbeats, config, 12.0)
    repaired = meter.extend_beats(meter.repair_beats(tracked, config), config, 0.0, 12.0)
    assert [b.time for b in beats] == [b.time for b in repaired]
    assert sections == meter.derive_sections(repaired, downbeats, config)
    assert sections and sections[0].anchor == 1.5


# ── beats the listener pinned (roadmap O5) ──────────────────────────────────

# Cheese Cake's slip, as the tracker gave it (160.28, 160.48, 160.60, 160.84 s
# on a 0.26 s pulse): a doubled beat whose pair is 0.32 s, a millisecond past
# the one-pulse test, so the repair keeps both and every bar after it is a
# beat off. The true beats are the two ends and one between them.
SLIP_PULSE = 0.26


def slipped(count_before: int = 40, count_after: int = 40) -> tuple[list[float], list[float]]:
    """(the tracker's beats, the true beats) around one doubled beat."""
    head = [round(i * SLIP_PULSE, 6) for i in range(count_before)]
    t = head[-1]
    tail = [round(t + 0.56 + i * SLIP_PULSE, 6) for i in range(count_after)]
    tracked = head + [round(t + 0.20, 6), round(t + 0.32, 6)] + tail
    return tracked, head + [round(t + 0.28, 6)] + tail


def times(beats: list[meter.Beat]) -> list[float]:
    return [b.time for b in beats]


def test_no_pins_change_nothing():
    tracked = steady(40)
    repaired = meter.repair_beats(tracked, MeterConfig())
    assert meter.apply_pins(repaired, [], MeterConfig()) == repaired
    assert meter.apply_pins(repaired, None, MeterConfig()) == repaired
    assert meter.bar_grid(tracked, [], MeterConfig(), 20.0, pins=[]) == meter.bar_grid(
        tracked, [], MeterConfig(), 20.0
    )


@pytest.fixture
def metronome_off(monkeypatch):
    """The repair as it was before the metronome test (R34), which mends
    Cheese Cake's slip on its own now. A pin is for the slip the metronome
    cannot read -- in a ragged stretch, beside a change of tempo -- and its
    arithmetic is the same whichever slip it mends, so the pin tests keep
    this one steady fixture and switch the metronome off rather than build a
    ragged neighbourhood the pin's own steadiness tests would then refuse."""
    monkeypatch.setattr(meter, "drop_ghost_beats", lambda beats, tolerance, seed=None: list(beats))
    monkeypatch.setattr(meter, "thin_by_metronome", lambda beats, tolerance: list(beats))


def test_the_metronome_mends_cheese_cakes_doubled_beat_without_a_pin():
    """R34: the pair is 0.32 s, a millisecond past the one-pulse test, and two
    bars either side say the time holds one beat between the pair's
    neighbours, not two."""
    tracked, truth = slipped()
    assert meter.drop_doubled_beats(tracked, 0.15) == tracked
    assert times(meter.repair_beats(tracked, MeterConfig())) == pytest.approx(
        [t for t in tracked if t != round(truth[39] + 0.20, 6)]
    )


def test_the_repair_without_the_metronome_misses_cheese_cakes_doubled_beat(metronome_off):
    """The precondition the pin exists for: without one the grid is a beat long."""
    tracked, truth = slipped()
    repaired = meter.repair_beats(tracked, MeterConfig())
    assert len(repaired) == len(truth) + 1


@pytest.mark.usefixtures("metronome_off")
def test_a_pin_at_a_doubled_beat_takes_the_extra_one_out():
    tracked, truth = slipped()
    t = truth[39]
    repaired = meter.repair_beats(tracked, MeterConfig())
    pinned = meter.apply_pins(repaired, [t + 0.27], MeterConfig())
    assert len(pinned) == len(truth)
    assert t + 0.27 in times(pinned)
    assert [b for b in pinned if b.pinned] == [meter.Beat(t + 0.27, pinned=True)]
    # Away from the slip nothing moved: the pin is a local fix.
    assert times(pinned)[:39] == truth[:39]
    assert times(pinned)[42:] == truth[42:]


@pytest.mark.usefixtures("metronome_off")
def test_a_pin_anywhere_on_the_slip_mends_it_whichever_beat_it_lands_on():
    """The listener drags one of the two crowded beat lines onto the other,
    or onto where the beat really is: all three are the same fix."""
    tracked, truth = slipped()
    t = truth[39]
    repaired = meter.repair_beats(tracked, MeterConfig())
    for pin in (t + 0.20, t + 0.27, t + 0.32):
        assert len(meter.apply_pins(repaired, [pin], MeterConfig())) == len(truth), pin


@pytest.mark.usefixtures("metronome_off")
@pytest.mark.parametrize("form_start", [None, 2.0])
def test_a_pin_anywhere_on_the_slip_keeps_one_bar_grid_numbered_like_the_truth(form_start):
    """The review's finding: a pin on one of the crowded beats (t+0.20) or
    beside the slip left an interval each side of it outside the tolerance,
    the grid split there, a bar line went missing and every bar after it was
    numbered one lower -- the beat COUNT was right all along. Every 20 ms
    from 0.3 s before the slip to 0.68 s into it, the pinned grid is one
    section, and its bar lines are the true grid's: the same numbers, and
    after the slip the same times."""
    tracked, truth = slipped()
    t = truth[39]
    config = MeterConfig(anchor=0.0, form_start=form_start)
    true_beats, true_sections = meter.bar_grid(truth, [], config, 30.0)
    true_lines = meter.bar_lines(true_beats, true_sections, form_start)
    for k in range(-30, 70, 2):
        pin = round(t + k / 100, 4)
        beats, sections = meter.bar_grid(tracked, [], config, 30.0, pins=[pin])
        lines = meter.bar_lines(beats, sections, form_start)
        assert len(sections) == 1, pin
        assert [n for _, n in lines] == [n for _, n in true_lines], pin
        after = [(a, c) for (a, _), (c, _) in zip(lines, true_lines, strict=True) if c > t + 1.0]
        assert after and all(a == pytest.approx(c) for a, c in after), pin


@pytest.mark.usefixtures("metronome_off")
def test_a_pinned_slip_puts_the_bar_lines_after_it_back_and_leaves_those_before():
    """What the downbeat cannot do: right on BOTH sides of the slip."""
    tracked, truth = slipped()
    config = MeterConfig(anchor=0.0)
    pin = truth[40]  # the true beat inside the slip
    true_lines = meter.bar_lines(*meter.bar_grid(truth, [], config, 30.0))
    off_lines = meter.bar_lines(*meter.bar_grid(tracked, [], config, 30.0))
    pinned_lines = meter.bar_lines(*meter.bar_grid(tracked, [], config, 30.0, pins=[pin]))
    after = [t for t, _ in true_lines if t > pin + 0.1]
    assert [t for t, _ in off_lines if t > pin + 0.1][:5] != pytest.approx(after[:5])
    assert [t for t, _ in pinned_lines if t > pin + 0.1] == pytest.approx(after)
    assert [t for t, _ in pinned_lines if t < pin - 0.1] == pytest.approx(
        [t for t, _ in true_lines if t < pin - 0.1]
    )
    assert [n for _, n in pinned_lines] == [n for _, n in true_lines]


def test_a_pin_in_a_dropped_beat_puts_it_back():
    """Three tracked intervals of 1.33 pulses over four: each rounds to one,
    so the repair inserts nothing and the grid is a beat short. A pin on the
    true beat in the middle re-derives the stretch from time."""
    tracked = steady(9) + [4.667, 5.333] + steady(29, start=6.0)
    repaired = meter.repair_beats(tracked, MeterConfig())
    assert len(repaired) == 40  # the precondition: one short
    pinned = meter.apply_pins(repaired, [5.0], MeterConfig())
    assert times(pinned) == pytest.approx(steady(41))
    assert [b.time for b in pinned if b.pinned] == [5.0]
    # The beats re-derived beside the pin are the software's, and say so.
    assert [b.time for b in pinned if b.implied] == pytest.approx([4.5, 5.5])


def test_pins_at_both_ends_of_a_ragged_stretch_make_the_count_between_them_whole():
    """Between two pins the count is theirs: as many beats as the time holds
    at the local pulse, each the tracker's own where one is near its place."""
    ragged = [4.3, 5.1, 5.6, 6.9, 7.3]
    beats = [meter.Beat(t) for t in sorted(steady(9) + ragged + steady(25, start=8.0))]
    pinned = meter.apply_pins(beats, [4.0, 8.0], MeterConfig())
    inside = [t for t in times(pinned) if 4.0 <= t <= 8.0]
    assert len(inside) == 9  # 4.0, eight half-second beats to 8.0
    assert inside[0] == 4.0 and inside[-1] == 8.0
    # 5.1, 5.6 and 6.9 sit within a quarter of a step of their places and
    # keep their own times; 4.3 and 7.3 do not, and give way.
    assert inside == pytest.approx([4.0, 4.5, 5.1, 5.6, 6.0, 6.5, 6.9, 7.5, 8.0])
    assert times(pinned)[:8] == steady(8)
    assert times(pinned)[-24:] == steady(24, start=8.5)


@pytest.mark.parametrize("every", [1, 4, 24])
@pytest.mark.parametrize("length", [8, 16, 24])
def test_pins_in_a_long_ragged_stretch_keep_the_count(length, every):
    """Pins at TRUE beats inside a jittered stretch (count kept, every beat
    within a fifth of a pulse of its place) leave the count and the bar
    numbers after it as a clean grid has them. The window's pulse used to be
    read off the rolling reference, which drifts with the jitter (0.519 s on
    0.5 s over 24 beats) and counted a 13.5 s window one beat short; and a
    jittered beat that passes the steadiness test by chance ended a window
    with no steady interval near it."""
    truth = [1.0 + 0.5 * i for i in range(120)]
    pattern = [0.2, -0.15, 0.1, -0.2, 0.18, -0.05, -0.2, 0.15]
    tracked = list(truth)
    for k, i in enumerate(range(40, 40 + length)):
        tracked[i] = truth[i] + pattern[k % len(pattern)] * 0.5
    stretch = list(range(40, 40 + length))
    pins = [truth[i] for i in stretch[::every]] + [truth[stretch[-1]]]
    config = MeterConfig(anchor=truth[4])
    duration = truth[-1] + 1.0
    clean, clean_sections = meter.bar_grid(truth, [], config, duration)
    pinned, sections = meter.bar_grid(tracked, [], config, duration, pins=pins)
    assert len(sections) == 1
    assert len(times(pinned)) == len(times(clean))
    for t in times(pinned):
        assert min(abs(t - x) for x in truth) <= 0.2 * 0.5 + 1e-6 or not truth[0] <= t <= truth[-1]
    assert meter.bar_lines(pinned, sections)[-5:] == pytest.approx(
        meter.bar_lines(clean, clean_sections)[-5:]
    )


def test_a_pin_half_a_beat_off_the_tracker_moves_beats_and_adds_none():
    """The listener and the tracker disagree about the phase. The grid goes
    through the pin, nothing else sits within half a pulse of it, the count
    across the window is the count its ends hold, and outside the window
    every beat is the tracker's."""
    beats = [meter.Beat(t) for t in steady(41)]
    pinned = meter.apply_pins(beats, [5.25], MeterConfig())
    assert len(pinned) == len(beats)
    assert 5.25 in times(pinned)
    assert all(abs(t - 5.25) > 0.25 for t in times(pinned) if t != 5.25)
    assert [t for t in times(pinned) if t <= 4.5] == steady(10)
    assert [t for t in times(pinned) if t >= 6.0] == steady(29, start=6.0)


@pytest.mark.parametrize("form_start", [None, 2.0])
@pytest.mark.parametrize("pin", [20.2, 20.25, 20.3])
def test_a_pin_half_a_beat_off_keeps_one_bar_grid_and_its_numbers(pin, form_start):
    """The window around a half-beat pin is uneven by construction (0.375,
    0.375, 0.75 s at 20.25 on a 0.5 s pulse): judged on the tolerance it
    split the grid at the pin and numbered every bar after it one lower.
    The window is the listener's, so the grid is one section and every bar
    line away from the pin keeps its time and its number."""
    config = MeterConfig(anchor=0.0, form_start=form_start)
    tracked = steady(80)
    plain_beats, plain_sections = meter.bar_grid(tracked, [], config, 40.0)
    beats, sections = meter.bar_grid(tracked, [], config, 40.0, pins=[pin])
    assert len(sections) == 1 == len(plain_sections)
    plain = meter.bar_lines(plain_beats, plain_sections, form_start)
    lines = meter.bar_lines(beats, sections, form_start)
    assert [n for _, n in lines] == [n for _, n in plain]
    away = [(a, c) for (a, _), (c, _) in zip(lines, plain, strict=True) if abs(c - pin) > 1.5]
    assert all(a == c for a, c in away)


def jittered(seed: int, count: int = 120, pulse: float = 0.5, jitter: float = 0.02) -> list[float]:
    rnd = random.Random(seed)
    return [round(i * pulse + rnd.uniform(-jitter, jitter), 4) for i in range(count)]


@pytest.mark.parametrize("form_start", [None, 2.0])
def test_a_tap_off_a_beat_never_splits_the_grid_or_renumbers_a_bar(form_start):
    """A pin 0.1-0.5 of a pulse off a beat the grid already has right -- a
    tap error, or a listener who hears the beat elsewhere -- on a grid
    jittered by 20 ms. Before the window vouched for itself, 38 of 130 such
    pins split the grid and renumbered the bars after it; on Cheese Cake, 34
    of 210 pins 50 ms off a steady beat did."""
    config = MeterConfig(anchor=0.0, form_start=form_start)
    for seed in range(5):
        tracked = jittered(seed)
        plain_beats, plain_sections = meter.bar_grid(tracked, [], config, 60.0)
        plain = meter.bar_lines(plain_beats, plain_sections, form_start)
        for frac in (-0.5, -0.4, -0.3, -0.2, -0.1, 0.1, 0.2, 0.3, 0.4, 0.5):
            pin = tracked[40] + frac * 0.5
            beats, sections = meter.bar_grid(tracked, [], config, 60.0, pins=[pin])
            lines = meter.bar_lines(beats, sections, form_start)
            assert len(sections) == len(plain_sections) == 1, (seed, frac)
            assert [n for _, n in lines] == [n for _, n in plain], (seed, frac)
            far = [
                (a, c) for (a, _), (c, _) in zip(lines, plain, strict=True) if abs(c - pin) > 1.5
            ]
            assert all(a == c for a, c in far), (seed, frac)


def test_a_pin_decides_nothing_outside_its_window():
    """A pin is local. Its new intervals moved the rolling reference pulse a
    few milliseconds, and a whole-gap test that FAILED on the unpinned grid
    -- the free stretch at the head, 0.478 to 1.538 s -- passed: the grid
    gained a bar at 0.0 s and every bar line after it, 20 s of them, was
    renumbered. Outside the window the unpinned grid's answers stand
    (`meter.Judgement`)."""
    rnd = random.Random(22)
    t, tracked = 0.0, []
    for _ in range(48):
        tracked.append(round(t, 3))
        t += 0.5 * (2.0 if rnd.random() < 0.08 else 1.0) * rnd.uniform(0.94, 1.06)
    config = MeterConfig(anchor=0.0)
    duration = tracked[-1] + 0.5
    plain_beats, plain_sections = meter.bar_grid(tracked, [], config, duration)
    plain = meter.bar_lines(plain_beats, plain_sections)
    pin = round(tracked[8] + 0.2 * (tracked[9] - tracked[8]), 3)
    assert pin == 4.626
    beats, sections = meter.bar_grid(tracked, [], config, duration, pins=[pin])
    assert meter.bar_lines(beats, sections) == plain
    assert [(s.start, s.first_bar) for s in sections] == [
        (s.start, s.first_bar) for s in plain_sections
    ]
    # The precondition: judged afresh, the head is drawn and renumbers all.
    afresh = meter.bar_lines(beats, meter.derive_sections(beats, [], config))
    assert afresh[0][0] < plain[0][0]
    assert [n for t, n in afresh if t > 10.0] != [n for t, n in plain if t > 10.0]


def test_steady_intervals_vouches_for_a_window_and_keeps_the_unpinned_judgement():
    beats = [meter.Beat(t) for t in steady(20)]
    moved = beats[:10] + [meter.Beat(5.12, pinned=True)] + beats[11:]  # 0.24 of a pulse
    plain = meter.steady_intervals(moved, MeterConfig())
    assert all(plain)  # the two intervals beside the pin, 0.62 and 0.38 s, too
    unpinned = [*beats[:10], meter.Beat(5.12), *beats[11:]]
    assert not all(meter.steady_intervals(unpinned, MeterConfig()))
    # A judgement on an interval the pin left alone is kept, even False.
    judged = meter.Judgement(steady={(beats[2].time, beats[3].time): False}, bridge_pulse=0.5)
    flags = meter.steady_intervals(moved, MeterConfig(), judged)
    assert flags[2] is False and flags[9] and flags[10]


def test_the_bridge_is_measured_against_the_unpinned_grids_pulse():
    """On a tracker's 20 ms frame grid a hole of exactly two pulses sits ON
    the bridge threshold, and a pin elsewhere moved the median interval by
    2e-15 s -- enough to split Ko Ko in four places 47 s from the pin. The
    pinned grid bridges against the unpinned grid's pulse."""
    times_ = steady(20) + [9.62, 10.0] + steady(20, start=10.5)  # 0.12 + 0.38 s
    beats = [meter.Beat(t) for t in times_]
    assert len(meter.metrical_spans(beats, MeterConfig())) == 1  # bridged
    judged = meter.judge(beats, MeterConfig())
    assert meter.metrical_spans(beats, MeterConfig(), judged) == meter.metrical_spans(
        beats, MeterConfig()
    )
    narrow = meter.Judgement(steady=judged.steady, bridge_pulse=0.2)
    assert len(meter.metrical_spans(beats, MeterConfig(), narrow)) == 2


def test_a_pin_near_the_end_does_not_stop_the_extension():
    """Judged on the tracker's gaps, a pin's uneven pair near the last beat
    made the edge look unsteady: on Cheese Cake a pin 50 ms off the beat at
    380.88 s took the extension, and the last nine bar lines, away."""
    tracked = steady(40)  # 0 .. 19.5
    plain, _ = meter.bar_grid(tracked, [], MeterConfig(), 30.0)
    pinned, _ = meter.bar_grid(tracked, [], MeterConfig(), 30.0, pins=[18.1])
    assert plain[-1].time == pytest.approx(30.0)
    assert pinned[-1].time == pytest.approx(30.0)
    assert len(pinned) == len(plain)


def test_two_pins_within_half_a_beat_are_one():
    """Kept both, they made a beat of 50-200 ms and threw the count. The GUI
    replaces the nearer pin; a hand-edited sidecar's later one is dropped."""
    beats = [meter.Beat(t) for t in steady(41)]
    pinned = meter.apply_pins(beats, [5.0, 5.2], MeterConfig())
    assert [b.time for b in pinned if b.pinned] == [5.0]
    assert len(pinned) == len(beats)
    both = meter.apply_pins(beats, [5.0, 5.3], MeterConfig())
    assert [b.time for b in both if b.pinned] == [5.0, 5.3]


def test_a_pin_on_a_beat_moves_only_that_beat():
    beats = [meter.Beat(t) for t in steady(41)]
    pinned = meter.apply_pins(beats, [5.05], MeterConfig())
    expected = steady(41)
    expected[10] = 5.05
    assert times(pinned) == pytest.approx(expected)


def test_a_pin_beyond_the_tracked_beats_carries_the_grid_out_to_it():
    """A tracker that starts late or stops early: a pin out there is a beat,
    and the beats between it and the grid are filled at the pulse."""
    beats = [meter.Beat(t) for t in steady(20, start=1.0)]  # 1.0 .. 10.5
    pinned = meter.apply_pins(beats, [0.0, 12.0], MeterConfig())
    assert times(pinned) == pytest.approx(steady(25))
    assert pinned[0].pinned and pinned[-1].pinned
    assert pinned[1].implied and pinned[-2].implied and pinned[-3].implied


@pytest.mark.usefixtures("metronome_off")
def test_a_pinned_grid_stays_one_metrical_span():
    """Pinned beats are found beats: the pin must not cut the bar grid at
    the slip it mends."""
    tracked, truth = slipped()
    pins = [truth[39] + 0.27]
    beats, sections = meter.bar_grid(tracked, [], MeterConfig(anchor=0.0), 30.0, pins=pins)
    assert len(sections) == 1
    assert sections[0].start == 0.0 and sections[0].end == beats[-1].time


def test_clean_pins_keeps_seconds_and_drops_everything_else():
    """A hand-edited sidecar must not be able to break the grid."""
    junk = [3.0, "4.0", None, float("nan"), float("inf"), -1.0, True, 1.0, 1.02, 2.0]
    assert meter.clean_pins(junk) == [1.0, 2.0, 3.0]
    assert meter.clean_pins(None) == []
    assert meter.clean_pins([]) == []


def test_bar_grid_ignores_a_pin_past_the_end_of_the_track():
    tracked = steady(20)
    assert meter.bar_grid(tracked, [], MeterConfig(), 10.0, pins=[25.0]) == meter.bar_grid(
        tracked, [], MeterConfig(), 10.0
    )
