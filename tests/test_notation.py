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


# ── double time ─────────────────────────────────────────────────────────────


def test_double_time_doubles_the_bars_and_the_values():
    """The listener's checkbox: the notated pulse is twice the tracked one,
    so a performed bar becomes two notated bars and a note on every beat —
    quarters at true meter — is written in halves' worth of doubled units
    (i.e., the same notes carry twice the notated value). The flag rides on
    the Notation so export can say 'Notated in double time' and the scorers
    can halve positions back to true meter."""
    beats = grid(count=48, start=0.0)
    region = (0.0, 32 * BEAT)
    normal = notation_for_span("t.wav", line(beats), beats, region, stem="other")
    doubled = notation_for_span("t.wav", line(beats), beats, region, stem="other", double_time=True)
    assert normal is not None and doubled is not None
    assert not normal.double_time
    assert doubled.double_time
    played_bars = sum(1 for bar in normal.bars if any(not n.is_rest for n in bar.notes))
    doubled_bars = sum(1 for bar in doubled.bars if any(not n.is_rest for n in bar.notes))
    assert doubled_bars == 2 * played_bars


def test_scoring_halves_a_double_time_page_back_to_true_meter():
    """A double-timed page scored against a true-meter reference must read
    the same as the normal page — the scorer, not the reader, undoes the
    doubling (benchmark.notation_notes)."""
    from swingscribe.benchmark import notation_notes

    beats = grid(count=48, start=0.0)
    region = (0.0, 32 * BEAT)
    normal = notation_for_span("t.wav", line(beats), beats, region, stem="other")
    doubled = notation_for_span("t.wav", line(beats), beats, region, stem="other", double_time=True)
    flat_normal = notation_notes(normal)
    flat_doubled = notation_notes(doubled)
    assert [p for p, _d, _pi in flat_doubled] == pytest.approx([p for p, _d, _pi in flat_normal])
    assert [d for _p, d, _pi in flat_doubled] == pytest.approx([d for _p, d, _pi in flat_normal])


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


def test_the_second_voice_is_notated_separately_and_merged_as_voice_2():
    """Two simultaneous notes in ONE list are not a chord to notate -- they are
    a grid too coarse, and one of them gets dropped. So the overlay is notated
    on its own and folded in afterwards."""
    from swingscribe.notation import notation_for_span

    beats = [i * 0.5 for i in range(40)]
    line = [
        NoteEvent(onset=t, duration=0.45, pitch=72, confidence=0.9, source="other")
        for t in (0.0, 0.5, 1.0, 1.5, 2.0)
    ]
    under = [
        NoteEvent(onset=t, duration=0.45, pitch=60, confidence=0.9, source="other")
        for t in (0.0, 0.5, 1.0, 1.5, 2.0)
    ]
    notation = notation_for_span(
        "x.wav", line, beats, (0.0, 20.0), stem="other", second_voice=under
    )
    assert notation is not None
    pitched = [n for bar in notation.bars for n in bar.notes if not n.is_rest]
    assert 72 in [n.pitch for n in pitched if n.voice == 1]
    assert 60 in [n.pitch for n in pitched if n.voice == 2]
    # Neither voice ate the other.
    assert len([n for n in pitched if n.voice == 1 and n.pitch == 72]) >= 4
    assert len([n for n in pitched if n.voice == 2 and n.pitch == 60]) >= 4


def test_without_a_second_voice_everything_stays_voice_1():
    from swingscribe.notation import notation_for_span

    beats = [i * 0.5 for i in range(40)]
    line = [
        NoteEvent(onset=t, duration=0.45, pitch=72, confidence=0.9, source="other")
        for t in (0.0, 0.5, 1.0, 1.5, 2.0)
    ]
    notation = notation_for_span("x.wav", line, beats, (0.0, 20.0), stem="other")
    assert notation is not None
    assert {n.voice for bar in notation.bars for n in bar.notes} == {1}


def test_merge_is_a_no_op_when_the_overlay_could_not_be_notated():
    from swingscribe.model import Notation as N
    from swingscribe.notation import merge_second_voice

    notation = N(title="t", bars=[])
    assert merge_second_voice(notation, None) is notation


def test_both_voices_share_one_swing_reading():
    """Swing is estimated from onsets, and the overlay is a different sample of
    the same playing — run on its own it reads a different BUR and warps a
    different set of beats, so the two voices drift apart on the page."""
    from swingscribe.notation import notation_for_span
    from swingscribe.stages import swing as swing_stage

    beats = [i * 0.5 for i in range(40)]
    line = [
        NoteEvent(onset=t, duration=0.2, pitch=72, confidence=0.9, source="other")
        for t in (0.0, 0.35, 0.5, 0.85, 1.0, 1.35, 1.5, 1.85)
    ]
    calls = []
    real = swing_stage.run

    def counting(document, config):
        calls.append(1)
        return real(document, config)

    swing_stage.run = counting
    try:
        notation_for_span("x.wav", line, beats, (0.0, 20.0), stem="other", second_voice=list(line))
    finally:
        swing_stage.run = real
    # Once, for the line. The overlay inherits that reading rather than
    # estimating its own.
    assert sum(calls) == 1


def test_the_overlay_inherits_the_line_s_swing_spans():
    from swingscribe.model import BeatGrid, Document, SwingSpan
    from swingscribe.notation import _notate_only

    captured = {}
    from swingscribe.stages import quantize as quantize_stage

    real = quantize_stage.run

    def capture(document, config):
        captured["swing"] = list(document.swing)
        return real(document, config)

    quantize_stage.run = capture
    try:
        parent = Document(
            audio_path="x.wav",
            sample_rate=44100,
            beat_grid=BeatGrid(beats=[i * 0.5 for i in range(20)], downbeats=[], beats_per_bar=4),
            swing=[SwingSpan(start_beat=0, end_beat=16, bur=1.8, confidence=0.9, is_swung=True)],
            notes={"other": []},
        )
        # The real caller forces the stem onto every stage; a bare Config
        # would file the notes under "" and quantize would not find them.
        run_config = Config().model_copy(
            update={
                "quantize": Config().quantize.model_copy(update={"stem": "other"}),
                "notate": Config().notate.model_copy(update={"stem": "other"}),
            }
        )
        _notate_only([], parent, run_config)
    finally:
        quantize_stage.run = real
    assert [s.bur for s in captured["swing"]] == [1.8]
