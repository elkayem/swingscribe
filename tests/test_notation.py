"""Notes + a beat grid -> a Notation, without audio or cache.

Two callers share this (the eval harness and the GUI's Export button), which
is the whole reason it is in the package rather than copied into both. So the
tests here are about the contract they both rely on: the span is trimmed, bar 1
is the span's first bar, and the anchor sets the phase.
"""

import pytest

from swingscribe.config import Config
from swingscribe.model import NoteEvent
from swingscribe.notation import (
    MIN_BEATS,
    meter_from_settings,
    notation_for_span,
    section_for,
    span_beats,
)

BEAT = 0.5  # 120 bpm


def grid(count: int = 48, start: float = 10.0, step: float = BEAT) -> list[float]:
    return [round(start + i * step, 6) for i in range(count)]


def line(beats: list[float], pitches: list[int] | None = None) -> list[NoteEvent]:
    """One note on each beat, so every bar is full and nothing is ambiguous."""
    pitches = pitches or [60, 62, 64, 65]
    return [
        NoteEvent(
            onset=t,
            duration=BEAT * 0.9,
            pitch=pitches[i % len(pitches)],
            confidence=0.9,
            source="other",
        )
        for i, t in enumerate(beats)
    ]


# ── trimming ────────────────────────────────────────────────────────────────


def test_span_beats_keeps_only_the_span_plus_margin():
    beats = grid(count=100, start=0.0)
    kept = span_beats(beats, (20.0, 30.0))
    assert kept[0] >= 18.0 and kept[-1] <= 32.0
    assert 25.0 in kept


def test_span_beats_runs_to_the_end_when_the_span_has_no_end():
    beats = grid(count=40, start=0.0)
    assert span_beats(beats, (5.0, None))[-1] == beats[-1]


def test_a_span_too_short_to_bar_out_returns_none():
    beats = grid(count=60, start=0.0)
    notes = line(beats)
    # A window narrower than MIN_BEATS beats cannot carry a bar grid.
    short = (0.0, BEAT * (MIN_BEATS - 6))
    assert notation_for_span("t.wav", notes, beats, short, stem="other") is None


# ── bar numbering ───────────────────────────────────────────────────────────


def test_bar_one_is_the_first_bar_of_the_span_not_of_the_track():
    """A solo starting six minutes in must not export 700 empty bars first."""
    beats = grid(count=64, start=360.0)
    notation = notation_for_span(
        "t.wav", line(beats), beats, (360.0, 360.0 + 32 * BEAT), stem="other"
    )
    assert notation is not None
    assert notation.bars[0].number == 1


def test_section_anchors_on_the_first_beat_when_none_is_given():
    beats = grid()
    section = section_for(beats, None, (4, 4), 4)
    assert section.anchor == beats[0]
    assert section.first_bar == 1
    assert section.origin == "user"


def test_the_anchor_moves_the_bar_lines_not_the_notes():
    """Shifting the downbeat by one beat must re-phrase the same notes, not
    drop or add any."""
    beats = grid(count=40)
    notes = line(beats)
    region = (beats[0], beats[-1])
    on_one = notation_for_span("t.wav", notes, beats, region, stem="other", anchor=beats[0])
    on_two = notation_for_span("t.wav", notes, beats, region, stem="other", anchor=beats[1])
    assert on_one is not None and on_two is not None

    def sounded(notation):
        return [n.pitch for bar in notation.bars for n in bar.notes if not n.is_rest]

    assert sounded(on_one) == sounded(on_two)
    # ... but the first bar's contents differ, because bar 1 now starts a beat later.
    assert on_one.bars[0].notes != on_two.bars[0].notes


# ── meter ───────────────────────────────────────────────────────────────────


def test_meter_from_settings_defaults_to_the_configs_own_meter():
    assert meter_from_settings(None, None, Config()) == ((4, 4), 4)


def test_six_eight_is_counted_in_two():
    """Pulses are not the numerator: 6/8 in two has two dotted-quarter beats."""
    assert meter_from_settings("6/8", None, Config()) == ((6, 8), 2)


def test_an_explicit_pulse_count_wins():
    assert meter_from_settings("6/8", 6, Config()) == ((6, 8), 6)


def test_an_unparseable_signature_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        meter_from_settings("swing", None, Config())


def test_the_time_signature_reaches_the_page():
    beats = grid(count=40)
    notation = notation_for_span(
        "t.wav",
        line(beats),
        beats,
        (beats[0], beats[-1]),
        stem="other",
        time_signature=(3, 4),
        pulses_per_bar=3,
    )
    assert notation is not None
    assert notation.bars[0].time_signature == (3, 4)


# ── config ──────────────────────────────────────────────────────────────────


def test_the_stem_is_forced_onto_every_stage():
    """A caller that sets the stem in one place and not another would get an
    empty score rather than an error, so notation_for_span sets all three."""
    beats = grid(count=40)
    notes = [n.model_copy(update={"source": "piano"}) for n in line(beats)]
    notation = notation_for_span("t.wav", notes, beats, (beats[0], beats[-1]), stem="piano")
    assert notation is not None
    assert any(not n.is_rest for bar in notation.bars for n in bar.notes)


def test_transposition_travels_from_config_to_the_notation():
    beats = grid(count=40)
    base = Config()
    config = base.model_copy(
        update={"notate": base.notate.model_copy(update={"transposition": "Bb-tenor"})}
    )
    notation = notation_for_span(
        "t.wav", line(beats), beats, (beats[0], beats[-1]), stem="other", config=config
    )
    assert notation is not None
    assert notation.transpose == 14
