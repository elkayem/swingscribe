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


def _require_ffmpeg() -> str:
    # Uses find_ffmpeg(), not shutil.which() directly: on this machine winget
    # installs ffmpeg but never puts it on PATH (CLAUDE.md), so a plain
    # shutil.which() check here would silently skip these tests in exactly
    # the environment — a fresh shell — where they matter most.
    found = ingest.find_ffmpeg()
    if found is None:
        pytest.skip("ffmpeg not found (not on PATH, and no winget install located)")
    return found


def test_find_ffmpeg_prefers_path(monkeypatch):
    monkeypatch.setattr(ingest.shutil, "which", lambda name: r"C:\on\path\ffmpeg.exe")
    assert ingest.find_ffmpeg() == r"C:\on\path\ffmpeg.exe"


def test_find_ffmpeg_falls_back_to_winget_location(monkeypatch, tmp_path):
    # The exact bug this regression-tests: shutil.which() finds nothing (a
    # fresh shell, PATH never touched) but ffmpeg is still on disk where
    # winget put it.
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)
    fake_home = tmp_path
    ffmpeg_dir = fake_home / "AppData/Local/Microsoft/WinGet/Packages"
    ffmpeg_dir /= "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-7.1-full_build/bin"
    ffmpeg_dir.mkdir(parents=True)
    exe = ffmpeg_dir / "ffmpeg.exe"
    exe.write_bytes(b"not a real binary, just needs to exist")
    monkeypatch.setattr(ingest.Path, "home", classmethod(lambda cls: fake_home))

    found = ingest.find_ffmpeg()
    assert found is not None
    assert Path(found) == exe


def test_find_ffmpeg_returns_none_when_truly_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)
    monkeypatch.setattr(ingest.Path, "home", classmethod(lambda cls: tmp_path))
    assert ingest.find_ffmpeg() is None


def test_ingest_decodes_m4a_even_when_ffmpeg_is_off_path(tmp_path, monkeypatch):
    """The actual bug report: a plain shell has ffmpeg installed but not on
    PATH, and every m4a failed with 'ffmpeg is not on PATH' even though
    ffmpeg was right there in the winget install directory."""
    import subprocess

    real_ffmpeg = _require_ffmpeg()
    src_wav = tmp_path / "tone.wav"
    write_sine_wav(src_wav, rate=44100, channels=2)
    src_m4a = tmp_path / "tone.m4a"
    subprocess.run(
        [real_ffmpeg, "-y", "-loglevel", "error", "-i", str(src_wav), str(src_m4a)], check=True
    )

    # Simulate the real-world failure: shutil.which() finds nothing, as it
    # would in a fresh shell, but the real winget install is still on disk —
    # find_ffmpeg()'s glob fallback should still locate it via the real home.
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None)

    config = Config(cache_dir=tmp_path / "cache")
    out = ingest.run(Document(audio_path=str(src_m4a), sample_rate=0), config)
    assert out.audio is not None
    assert Path(out.audio.path).is_file()


def test_ingest_m4a_via_ffmpeg_fallback(tmp_path):
    import subprocess

    ffmpeg = _require_ffmpeg()
    src_wav = tmp_path / "tone.wav"
    write_sine_wav(src_wav, rate=44100, channels=2)
    src_m4a = tmp_path / "tone.m4a"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(src_wav), str(src_m4a)], check=True
    )

    config = Config(cache_dir=tmp_path / "cache")
    out = ingest.run(Document(audio_path=str(src_m4a), sample_rate=0), config)

    assert out.audio is not None
    assert out.audio.sample_rate == 44100
    assert out.audio.channels == 2
    # aac adds encoder padding; duration should still be within ~100ms
    assert abs(out.audio.duration - 1.0) < 0.1
    assert Path(out.audio.path).is_file()


def test_ingest_undecodable_file_fails_clearly(tmp_path):
    _require_ffmpeg()
    garbage = tmp_path / "not-audio.m4a"
    garbage.write_bytes(b"this is definitely not audio")

    config = Config(cache_dir=tmp_path / "cache")
    with pytest.raises(ingest.AudioDecodeError) as excinfo:
        ingest.run(Document(audio_path=str(garbage), sample_rate=0), config)
    message = str(excinfo.value)
    assert "not-audio.m4a" in message  # names the file
    assert "ffmpeg" in message  # names the decoder that rejected it
