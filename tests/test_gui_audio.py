"""Peak envelopes and stem span slicing.

Needs soundfile/numpy (the ml group), so it skips on CI. The time-stretch tests
additionally need torch.
"""

import math

import pytest

from swingscribe.gui import audio as gui_audio
from swingscribe.gui import peaks

soundfile = pytest.importorskip("soundfile", reason="ml dependency group not installed")
np = pytest.importorskip("numpy", reason="ml dependency group not installed")


def write_wav(path, seconds=4.0, rate=22050, freq=220.0, channels=2, amplitude=0.5):
    t = np.arange(int(seconds * rate)) / rate
    tone = (amplitude * np.sin(2 * math.pi * freq * t)).astype("float32")
    data = np.stack([tone] * channels, axis=1)
    soundfile.write(str(path), data, rate)
    return path


# ── peaks ───────────────────────────────────────────────────────────────────


def test_envelope_shape_and_range(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=4.0, amplitude=0.5)
    data = peaks.envelope(wav, buckets=500)

    maxima, minima = data["peaks"]
    assert len(maxima) == len(minima) == 500
    assert data["duration"] == pytest.approx(4.0, abs=0.01)
    # A steady tone at 0.5 fills every bucket to roughly ±0.5.
    assert max(maxima) == pytest.approx(0.5, abs=0.02)
    assert min(minima) == pytest.approx(-0.5, abs=0.02)
    assert all(value >= 0 for value in maxima)
    assert all(value <= 0 for value in minima)


def test_envelope_honours_a_time_window(tmp_path):
    """The detail tier asks for one window; it must get that window's audio and
    be told which range it actually covers."""
    rate = 22050
    loud = 0.8 * np.sin(2 * math.pi * 220 * np.arange(rate * 2) / rate)
    quiet = 0.05 * np.sin(2 * math.pi * 220 * np.arange(rate * 2) / rate)
    data = np.concatenate([loud, quiet]).astype("float32")
    wav = tmp_path / "halves.wav"
    soundfile.write(str(wav), data, rate)

    first = peaks.envelope(wav, buckets=100, start=0.0, end=2.0)
    second = peaks.envelope(wav, buckets=100, start=2.0, end=4.0)

    assert first["start"] == pytest.approx(0.0)
    assert second["start"] == pytest.approx(2.0)
    assert max(first["peaks"][0]) > 0.7
    assert max(second["peaks"][0]) < 0.1


def test_envelope_clamps_a_window_past_the_end(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=2.0)
    data = peaks.envelope(wav, buckets=50, start=1.0, end=99.0)
    assert data["end"] == pytest.approx(2.0, abs=0.01)


def test_envelope_caps_absurd_bucket_counts(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=1.0)
    data = peaks.envelope(wav, buckets=10_000_000)
    assert len(data["peaks"][0]) <= peaks.MAX_BUCKETS


def test_overview_is_memoized(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=2.0)
    cache = tmp_path / "cache"
    first = peaks.overview(wav, cache, "digest0")
    cached_file = cache / "gui" / "peaks" / f"digest0-{peaks.OVERVIEW_BUCKETS}.json"
    assert cached_file.is_file()

    wav.unlink()  # a second call must not need to read the audio again
    assert peaks.overview(wav, cache, "digest0") == first


# ── span slices ─────────────────────────────────────────────────────────────


def test_slice_wav_cuts_the_requested_span(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=6.0, rate=22050)
    payload = gui_audio.slice_wav(wav, start=1.0, end=3.0)

    import io

    data, rate = soundfile.read(io.BytesIO(payload), dtype="float32", always_2d=True)
    assert rate == 22050
    assert data.shape[0] == pytest.approx(2.0 * rate, abs=2)
    assert data.shape[1] == 2  # short span keeps its stereo image


def test_slice_wav_to_the_end_when_end_is_none(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=3.0, rate=8000)
    import io

    data, _ = soundfile.read(
        io.BytesIO(gui_audio.slice_wav(wav, start=1.0, end=None)), always_2d=True
    )
    assert data.shape[0] == pytest.approx(2.0 * 8000, abs=2)


def test_slice_wav_downmixes_a_long_span(tmp_path):
    """Whole-track spans across several stems would otherwise cost hundreds of
    megabytes of AudioBuffer in the browser."""
    seconds = gui_audio.STEREO_LIMIT_SECONDS + 5
    wav = write_wav(tmp_path / "long.wav", seconds=seconds, rate=4000)
    import io

    data, _ = soundfile.read(io.BytesIO(gui_audio.slice_wav(wav)), always_2d=True)
    assert data.shape[1] == 1


def test_every_stem_of_one_span_gets_the_same_length(tmp_path):
    """Screen 3 loops several buffers against each other; a one-sample
    difference in length would drift them apart over a long practice loop."""
    import io

    a = write_wav(tmp_path / "a.wav", seconds=5.0, rate=16000, freq=200)
    b = write_wav(tmp_path / "b.wav", seconds=5.0, rate=16000, freq=700)
    lengths = set()
    for source in (a, b):
        data, _ = soundfile.read(io.BytesIO(gui_audio.slice_wav(source, 1.0, 3.5)), always_2d=True)
        lengths.add(data.shape[0])
    assert len(lengths) == 1


def test_slice_wav_clamps_the_rate():
    assert gui_audio.MIN_RATE < 1.0 < gui_audio.MAX_RATE


def test_time_stretch_lengthens_without_moving_pitch(tmp_path):
    pytest.importorskip("torch", reason="ml dependency group not installed")
    import io

    rate = 16000
    wav = write_wav(tmp_path / "tone.wav", seconds=3.0, rate=rate, freq=440.0, channels=1)
    payload = gui_audio.slice_wav(wav, start=0.0, end=2.0, rate=0.5)
    data, out_rate = soundfile.read(io.BytesIO(payload), dtype="float32", always_2d=True)

    # Half speed: twice as long, same sample rate.
    assert out_rate == rate
    assert data.shape[0] / rate == pytest.approx(4.0, abs=0.1)

    # And still a 440 Hz tone — resampling instead would have put it at 220.
    mono = data[:, 0]
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    peak_hz = np.fft.rfftfreq(len(mono), 1 / rate)[int(np.argmax(spectrum))]
    assert peak_hz == pytest.approx(440.0, abs=8.0)
