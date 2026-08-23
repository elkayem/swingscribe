"""Ingest stage. Needs the ml dependency group; skips cleanly in CI."""

import math
import struct
import wave
from pathlib import Path

import pytest

pytest.importorskip("torchaudio", reason="ml dependency group not installed")

from swingscribe.config import Config
from swingscribe.model import Document
from swingscribe.stages import ingest


def write_sine_wav(path, rate=22050, seconds=1.0, freq=440.0, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            sample = struct.pack("<h", int(20000 * math.sin(2 * math.pi * freq * i / rate)))
            frames += sample * channels
        w.writeframes(bytes(frames))


def test_ingest_resamples_and_widens_to_stereo(tmp_path):
    src = tmp_path / "tone.wav"
    write_sine_wav(src, rate=22050, channels=1)
    config = Config(cache_dir=tmp_path / "cache")
    document = Document(audio_path=str(src), sample_rate=0)

    out = ingest.run(document, config)

    assert out.audio is not None
    assert out.audio.sample_rate == 44100
    assert out.audio.channels == 2
    assert abs(out.audio.duration - 1.0) < 0.01
    assert Path(out.audio.path).is_file()
    assert out.sample_rate == 44100


def test_ingest_is_deterministic(tmp_path):
    src = tmp_path / "tone.wav"
    write_sine_wav(src)
    config = Config(cache_dir=tmp_path / "cache")
    document = Document(audio_path=str(src), sample_rate=0)

    first = ingest.run(document, config)
    second = ingest.run(document, config)
    assert first.audio.path == second.audio.path  # same content → same normalized file


def test_ingest_missing_file_raises(tmp_path):
    config = Config(cache_dir=tmp_path / "cache")
    document = Document(audio_path=str(tmp_path / "nope.wav"), sample_rate=0)
    with pytest.raises(FileNotFoundError):
        ingest.run(document, config)
