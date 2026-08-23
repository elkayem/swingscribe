"""Ear-test click renderer. Naming/matching helpers run in CI; the render
test needs numpy/soundfile from the ml group and skips without them."""

from pathlib import Path

import pytest

from swingscribe.click import default_click_path, is_downbeat
from swingscribe.model import BeatGrid


def test_default_click_path():
    assert default_click_path("takes/koko.mp3") == Path("takes/koko.click.wav")


def test_is_downbeat_tolerance():
    downbeats = [0.0, 2.0, 4.0]
    assert is_downbeat(2.01, downbeats)
    assert not is_downbeat(2.5, downbeats)


def test_render_click_track(tmp_path):
    numpy = pytest.importorskip("numpy", reason="ml dependency group not installed")
    soundfile = pytest.importorskip("soundfile", reason="ml dependency group not installed")

    from swingscribe.click import render_click_track

    rate = 44100
    src = tmp_path / "music.wav"
    silence = numpy.zeros((rate * 2, 2), dtype="float32")
    soundfile.write(str(src), silence, rate)

    grid = BeatGrid(
        beats=[0.0, 0.5, 1.0, 1.5], downbeats=[0.0, 1.0], beats_per_bar=2, local_bpm=[120.0] * 4
    )
    out = render_click_track(src, grid, tmp_path / "music.click.wav")

    data, out_rate = soundfile.read(str(out), always_2d=True)
    assert out_rate == rate
    assert len(data) == rate * 2
    # clicks are audible against the silent source, and downbeats are louder
    beat_peak = abs(data[int(0.5 * rate) : int(0.5 * rate) + 2000]).max()
    downbeat_peak = abs(data[int(1.0 * rate) : int(1.0 * rate) + 2000]).max()
    assert beat_peak > 0.2
    assert downbeat_peak > beat_peak
