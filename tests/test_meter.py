"""Bar-grid derivation. Pure and stdlib-only, so this all runs in CI.

Cases are built from synthetic grids whose right answer is known, including
reproductions of the two failure modes measured on real tracks: a tracker that
drops to half rate for a passage, and a downbeat layer that is noise.
"""

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
