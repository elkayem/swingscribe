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


def test_select_source_prefers_drum_stem(tmp_path):
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"x")
    path, reason = select_source(
        {"drums": str(drums)}, "mix.wav", True, 0.001, rms_of=lambda p: 0.1
    )
    assert path == str(drums)
    assert reason == "drum stem"


def test_select_source_falls_back_when_silent(tmp_path):
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"x")
    path, reason = select_source(
        {"drums": str(drums)}, "mix.wav", True, 0.001, rms_of=lambda p: 1e-6
    )
    assert path == "mix.wav"
    assert "near-silent" in reason


def test_select_source_falls_back_when_missing():
    path, reason = select_source({}, "mix.wav", True, 0.001, rms_of=lambda p: 0.1)
    assert path == "mix.wav"
    assert "no drum stem" in reason


def test_select_source_respects_config_off():
    path, reason = select_source(
        {"drums": "drums.wav"}, "mix.wav", False, 0.001, rms_of=lambda p: 0.1
    )
    assert path == "mix.wav"
    assert "use_drum_stem=false" in reason


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
