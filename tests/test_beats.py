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
