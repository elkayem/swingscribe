"""BeatTrack stage. Pure helpers run everywhere (CI included); the end-to-end
test downloads beat_this weights and is opt-in via SWINGSCRIBE_HEAVY_TESTS=1."""

import pytest

from conftest import requires_heavy
from swingscribe.stages.beats import (
    infer_beats_per_bar,
    local_bpm_curve,
    octave_outliers,
    select_source,
)


def test_local_bpm_curve_steady():
    beats = [i * 0.5 for i in range(9)]  # 120 bpm
    bpm = local_bpm_curve(beats)
    assert len(bpm) == 9  # one entry per beat — a curve, not a global number
    assert all(abs(b - 120.0) < 1e-6 for b in bpm)


def test_local_bpm_curve_tracks_tempo_changes():
    beats = [0.0, 0.5, 1.0, 1.75, 2.5]  # 120 bpm slowing to 80 bpm
    bpm = local_bpm_curve(beats)
    assert abs(bpm[0] - 120.0) < 1e-6
    assert abs(bpm[3] - 80.0) < 1e-6


def test_local_bpm_curve_degenerate():
    assert local_bpm_curve([]) == []
    assert local_bpm_curve([1.0]) == [0.0]


def test_octave_outliers_flags_half_tempo():
    # steady 120 bpm with one missed beat → a 60 bpm gap, the classic octave error
    beats = [0.0, 0.5, 1.0, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
    outliers = octave_outliers(local_bpm_curve(beats))
    assert outliers == [2]


def test_octave_outliers_clean_curve():
    beats = [i * 0.5 for i in range(16)]
    assert octave_outliers(local_bpm_curve(beats)) == []


def test_infer_beats_per_bar_four_four():
    beats = [i * 0.5 for i in range(16)]
    downbeats = [0.0, 2.0, 4.0, 6.0]
    assert infer_beats_per_bar(beats, downbeats) == 4


def test_infer_beats_per_bar_waltz():
    beats = [i * 0.5 for i in range(12)]
    downbeats = [0.0, 1.5, 3.0, 4.5]
    assert infer_beats_per_bar(beats, downbeats) == 3


def test_infer_beats_per_bar_defaults_to_four():
    assert infer_beats_per_bar([0.0, 0.5], []) == 4


def rms_table(values):
    return lambda path: values[path]


def test_select_source_prefers_drum_stem(tmp_path):
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"x")
    rms = rms_table({str(drums): 0.02, "mix.wav": 0.1})  # 20% of mix
    path, reason = select_source({"drums": str(drums)}, "mix.wav", True, 0.05, rms_of=rms)
    assert path == str(drums)
    assert reason == "drum stem"


def test_select_source_falls_back_on_relative_silence(tmp_path):
    # the They Say It's Spring case: drum stem nonsilent in absolute terms
    # but carrying ~4% of the mix's energy (brushes ballad)
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"x")
    rms = rms_table({str(drums): 0.0032, "mix.wav": 0.083})
    path, reason = select_source({"drums": str(drums)}, "mix.wav", True, 0.05, rms_of=rms)
    assert path == "mix.wav"
    assert "near-silent relative to mix" in reason


def test_select_source_falls_back_when_missing():
    path, reason = select_source({}, "mix.wav", True, 0.05, rms_of=lambda p: 0.1)
    assert path == "mix.wav"
    assert "no drum stem" in reason


def test_select_source_respects_config_off():
    path, reason = select_source(
        {"drums": "drums.wav"}, "mix.wav", False, 0.05, rms_of=lambda p: 0.1
    )
    assert path == "mix.wav"
    assert "use_drum_stem=false" in reason


def test_grid_is_plausible_normal():
    from swingscribe.stages.beats import grid_is_plausible

    beats = [i * 0.5 for i in range(240)]  # 120s at 120 bpm
    assert grid_is_plausible(beats, duration=120.0)


def test_grid_is_plausible_rejects_phantom_grid():
    from swingscribe.stages.beats import grid_is_plausible

    # the Spring failure: 41 beats at ~22 bpm over a 328s track
    beats = [i * 2.64 for i in range(41)]
    assert not grid_is_plausible(beats, duration=328.0)


def test_grid_quality_prefers_steady_plausible_grid():
    from swingscribe.stages.beats import grid_is_suspect, grid_quality

    steady = [i * 0.54 for i in range(400)]  # ~111 bpm, clean — the Born To Blue drum grid
    # messy half-tempo grid with jitter — the Born To Blue full-mix grid
    import random

    rng = random.Random(1)
    messy = []
    t = 0.0
    for _ in range(360):
        t += rng.choice([0.5, 1.0, 1.0, 1.0, 2.0])
        messy.append(t)

    duration = 328.0
    assert grid_quality(steady, duration) > grid_quality(messy, duration)
    assert not grid_is_suspect(grid_quality(steady, duration))
    assert grid_is_suspect(grid_quality(messy, duration))


def test_grid_quality_plausibility_dominates():
    from swingscribe.stages.beats import grid_quality

    phantom = [i * 2.64 for i in range(41)]  # 22 bpm phantoms (Spring drum stem)
    coherent = [i * 0.84 for i in range(390)]  # 71 bpm half-time (Spring full mix)
    assert grid_quality(coherent, 328.0) > grid_quality(phantom, 328.0)


def test_grid_is_plausible_rejects_sparse_coverage():
    from swingscribe.stages.beats import grid_is_plausible

    beats = [i * 0.5 for i in range(20)]  # plausible tempo, but only 10s of a 328s track
    assert not grid_is_plausible(beats, duration=328.0)


def test_correct_octave_subdivides_half_tempo():
    from swingscribe.stages.beats import correct_octave

    beats = [i * (60.0 / 71.4) for i in range(50)]  # tracked at 71.4, truth ~140
    downbeats = beats[0::4]
    new_beats, new_downbeats, action = correct_octave(beats, downbeats, 140.0)
    assert action is not None and "subdivided" in action
    assert len(new_beats) == 2 * len(beats) - 1
    bpm = local_bpm_curve(new_beats)
    import statistics

    assert abs(statistics.median(bpm) - 142.8) < 1.0
    assert new_downbeats == downbeats  # bar starts unchanged


def test_correct_octave_halves_double_tempo():
    from swingscribe.stages.beats import correct_octave

    beats = [i * 0.25 for i in range(80)]  # tracked at 240, truth ~120
    downbeats = beats[0::8]  # true bar starts land on even indices
    new_beats, new_downbeats, action = correct_octave(beats, downbeats, 120.0)
    assert action is not None and "halved" in action
    assert new_beats == beats[0::2]  # kept the parity holding the downbeats
    assert new_downbeats == downbeats
    import statistics

    assert abs(statistics.median(local_bpm_curve(new_beats)) - 120.0) < 1.0


def test_correct_octave_leaves_good_grid_alone():
    from swingscribe.stages.beats import correct_octave

    beats = [i * 0.5 for i in range(50)]  # 120 bpm, hint 120
    new_beats, new_downbeats, action = correct_octave(beats, beats[0::4], 120.0)
    assert action is None
    assert new_beats == beats


@requires_heavy
def test_beats_end_to_end_recovers_tempo(tmp_path):
    pytest.importorskip("beat_this")
    import math
    import struct
    import wave

    from swingscribe.config import Config
    from swingscribe.model import Document
    from swingscribe.stages import beats, ingest

    # 8s of sharp percussive pulses at exactly 120 bpm
    rate = 44100
    src = tmp_path / "pulses.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(rate * 8):
            phase = i % (rate // 2)  # every 0.5s
            sample = (
                int(28000 * math.exp(-phase / 400.0) * math.sin(0.4 * phase)) if phase < 3000 else 0
            )
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))

    config = Config(cache_dir=tmp_path / "cache")
    document = ingest.run(Document(audio_path=str(src), sample_rate=0), config)
    out = beats.run(document, config)  # no stems → full-mix fallback

    grid = out.beat_grid
    assert grid is not None and len(grid.beats) > 8
    assert len(grid.local_bpm) == len(grid.beats)
    import statistics

    median = statistics.median(b for b in grid.local_bpm if b > 0)
    assert abs(median - 120.0) / 120.0 < 0.06  # within ~5% (octave errors would be 100% off)


"""Local coverage and splicing (open-issue #9). All pure — no numpy, no
beat_this — so they run in CI, which is where this logic most needs guarding:
the bug they exist to prevent was invisible to every whole-track measure."""


def test_median_interval():
    from swingscribe.stages.beats import median_interval

    assert abs(median_interval([0.0, 0.5, 1.0, 1.5]) - 0.5) < 1e-9
    assert median_interval([1.0]) == 0.0
    assert median_interval([]) == 0.0


def test_coverage_gaps_finds_a_late_start():
    """Confirmation's actual failure: the grid is perfectly steady and simply
    does not begin until 11.3s, which no steadiness measure can see."""
    from swingscribe.stages.beats import coverage_gaps

    beats = [11.28 + i * 0.32 for i in range(200)]
    gaps = coverage_gaps(beats, duration=beats[-1] + 0.32)
    assert len(gaps) == 1
    assert gaps[0][0] == 0.0
    assert abs(gaps[0][1] - 11.28) < 1e-9


def test_coverage_gaps_finds_a_hole_in_the_middle():
    from swingscribe.stages.beats import coverage_gaps

    beats = [i * 0.32 for i in range(20)] + [12.0 + i * 0.32 for i in range(20)]
    gaps = coverage_gaps(beats, duration=beats[-1] + 0.32)
    assert len(gaps) == 1
    assert abs(gaps[0][0] - beats[19]) < 1e-9
    assert abs(gaps[0][1] - 12.0) < 1e-9


def test_coverage_gaps_clean_grid_has_none():
    from swingscribe.stages.beats import coverage_gaps

    beats = [i * 0.32 for i in range(300)]
    assert coverage_gaps(beats, duration=beats[-1] + 0.32) == []


def test_coverage_gaps_counts_the_tail():
    from swingscribe.stages.beats import coverage_gaps

    beats = [i * 0.5 for i in range(20)]  # stops at 9.5s
    gaps = coverage_gaps(beats, duration=30.0)
    assert len(gaps) == 1
    assert abs(gaps[0][1] - 30.0) < 1e-9


def test_audible_spans_drops_a_silent_lead_in():
    """A silent intro is not a tracker failure and must not trigger a splice."""
    from swingscribe.stages.beats import audible_spans

    window_s = 0.5
    windows = [0.0] * 20 + [0.2] * 100  # silent for the first 10s
    assert audible_spans([(0.0, 10.0)], windows, window_s) == []
    assert audible_spans([(20.0, 30.0)], windows, window_s) == [(20.0, 30.0)]


def test_audible_spans_keeps_a_playing_gap():
    from swingscribe.stages.beats import audible_spans

    windows = [0.15] * 40  # quiet intro, but playing
    assert audible_spans([(0.0, 11.0)], windows, 0.5) == [(0.0, 11.0)]


def test_splice_fills_a_gap_at_the_matching_rate():
    from swingscribe.stages.beats import splice_beats

    base = [11.28 + i * 0.32 for i in range(100)]
    filler = [0.24 + i * 0.32 for i in range(200)]  # full mix, same rate
    beats, filled = splice_beats(base, filler, [(0.0, 11.28)], interval=0.32)
    assert len(filled) == 1
    assert len(beats) > len(base)
    assert beats == sorted(beats)
    assert beats[0] < 1.0  # the intro is now covered


def test_splice_rejects_a_half_rate_filler():
    """The bass covers Confirmation's intro better than the drums do, but
    plays a 2-feel — its beats are at half the true pulse. Filling from it
    would be worse than leaving the hole."""
    from swingscribe.stages.beats import splice_beats

    base = [11.28 + i * 0.32 for i in range(100)]
    filler = [0.3 + i * 0.64 for i in range(20)]  # half rate
    beats, filled = splice_beats(base, filler, [(0.0, 11.28)], interval=0.32)
    assert filled == []
    assert beats == base


def test_splice_never_doubles_the_pulse_at_a_seam():
    from swingscribe.stages.beats import splice_beats

    base = [10.0 + i * 0.5 for i in range(20)]
    filler = [i * 0.5 for i in range(40)]  # overlaps the base exactly
    beats, _ = splice_beats(base, filler, [(0.0, 10.0)], interval=0.5)
    intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    assert min(intervals) > 0.25  # no beat lands within half a beat of another


def test_splice_leaves_a_grid_with_no_gaps_alone():
    from swingscribe.stages.beats import splice_beats

    base = [i * 0.5 for i in range(40)]
    beats, filled = splice_beats(base, [i * 0.5 + 0.1 for i in range(40)], [], interval=0.5)
    assert beats == base
    assert filled == []


def test_beat_grid_records_its_source():
    """open-issue #7 — the stored grid must say where it came from."""
    from swingscribe.model import BeatGrid

    grid = BeatGrid(beats=[0.0, 0.5], downbeats=[0.0], beats_per_bar=4)
    assert grid.source == ""  # old cached artifacts still load
    assert grid.spliced == []
    grid = BeatGrid(
        beats=[0.0, 0.5],
        downbeats=[0.0],
        beats_per_bar=4,
        source="drum stem + full mix over 1 span(s)",
        spliced=[(0.0, 11.3)],
    )
    assert grid.spliced == [(0.0, 11.3)]


def test_repair_local_rate_subdivides_a_half_rate_passage():
    """Confirmation's residue: the grid resumes at exactly half the tune's
    pulse. Those beats are PRESENT, so no coverage test can see them."""
    from swingscribe.stages.beats import median_interval, repair_local_rate

    good = [i * 0.32 for i in range(100)]
    half = [good[-1] + (i + 1) * 0.64 for i in range(15)]
    repaired, spans = repair_local_rate(good + half)
    assert len(spans) == 1
    assert abs(median_interval(repaired) - 0.32) < 0.01
    assert repaired == sorted(repaired)
    intervals = [b - a for a, b in zip(repaired, repaired[1:], strict=False)]
    assert max(intervals) < 0.45  # nothing at the old half rate survives


def test_repair_local_rate_ignores_an_isolated_long_interval():
    """One doubled interval is a dropped beat, a fermata or a rubato moment.
    Only a persistent wrong rate is evidence of a mis-tracked passage."""
    from swingscribe.stages.beats import repair_local_rate

    beats = [i * 0.5 for i in range(40)]
    beats = beats[:20] + [b + 0.5 for b in beats[20:]]  # one 1.0s hole
    repaired, spans = repair_local_rate(beats)
    assert spans == []
    assert repaired == beats


def test_repair_local_rate_leaves_a_steady_grid_alone():
    from swingscribe.stages.beats import repair_local_rate

    beats = [i * 0.32 for i in range(200)]
    repaired, spans = repair_local_rate(beats)
    assert spans == []
    assert repaired == beats


def test_repair_local_rate_handles_a_quarter_rate_passage():
    from swingscribe.stages.beats import repair_local_rate

    good = [i * 0.5 for i in range(60)]
    quarter = [good[-1] + (i + 1) * 2.0 for i in range(10)]
    repaired, spans = repair_local_rate(good + quarter)
    assert len(spans) == 1
    intervals = [b - a for a, b in zip(repaired, repaired[1:], strict=False)]
    assert max(intervals) < 0.7


def test_repair_local_rate_does_not_touch_a_faster_passage():
    """One-directional on purpose: removing beats means choosing WHICH to
    remove, which correct_octave only does with a user-supplied tempo."""
    from swingscribe.stages.beats import repair_local_rate

    beats = [i * 0.5 for i in range(60)] + [29.5 + (i + 1) * 0.25 for i in range(20)]
    repaired, spans = repair_local_rate(beats)
    assert spans == []
    assert repaired == beats


def test_repair_local_rate_degenerate():
    from swingscribe.stages.beats import repair_local_rate

    assert repair_local_rate([]) == ([], [])
    assert repair_local_rate([1.0, 2.0]) == ([1.0, 2.0], [])
