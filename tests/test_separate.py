"""Separate stage. Pure helpers run everywhere (CI included); the end-to-end
test downloads model weights and runs the real separator, so it is opt-in via
SWINGSCRIBE_HEAVY_TESTS=1."""

from pathlib import Path

import pytest

from conftest import requires_heavy
from swingscribe.device import resolve_device
from swingscribe.stages.separate import existing_stems, stems_dir


def test_resolve_device_auto():
    assert resolve_device("auto", cuda_available=True) == "cuda"
    assert resolve_device("auto", cuda_available=False) == "cpu"


def test_resolve_device_explicit_passthrough():
    assert resolve_device("cpu", cuda_available=True) == "cpu"
    assert resolve_device("cuda", cuda_available=False) == "cuda"


def test_stems_dir_encodes_audio_and_model(tmp_path):
    a = stems_dir(tmp_path, "digest1", "htdemucs_ft")
    b = stems_dir(tmp_path, "digest2", "htdemucs_ft")
    c = stems_dir(tmp_path, "digest1", "bs_roformer")
    assert a != b != c
    assert a == stems_dir(tmp_path, "digest1", "htdemucs_ft")  # deterministic


@requires_heavy
def test_separate_end_to_end(tmp_path):
    pytest.importorskip("demucs", reason="ml dependency group not installed")
    from swingscribe.config import Config
    from swingscribe.model import Document
    from swingscribe.stages import ingest, separate
    from test_ingest import write_sine_wav

    src = tmp_path / "tone.wav"
    write_sine_wav(src, seconds=2.0)
    config = Config(cache_dir=tmp_path / "cache")
    document = ingest.run(Document(audio_path=str(src), sample_rate=0), config)

    out = separate.run(document, config)

    assert set(out.stems) == {"drums", "bass", "other", "vocals"}
    for path in out.stems.values():
        assert Path(path).is_file()


def test_existing_stems_returns_the_full_set(tmp_path):
    out = tmp_path / "digest-htdemucs"
    out.mkdir()
    for name in ("drums", "bass", "other", "vocals"):
        (out / f"{name}.wav").write_bytes(b"RIFF....")
    found = existing_stems(out, ["drums", "bass", "other", "vocals"])
    assert found is not None
    assert sorted(found) == ["bass", "drums", "other", "vocals"]
    assert found["other"].endswith("other.wav")


def test_existing_stems_rejects_a_partial_separation(tmp_path):
    """A directory holding three of four wavs is a separation that died
    partway through. Reusing it would make the stage silently return less than
    it promises — and the missing stem is exactly the one nobody notices until
    a downstream stage asks for it."""
    out = tmp_path / "digest-htdemucs"
    out.mkdir()
    for name in ("drums", "bass", "other"):
        (out / f"{name}.wav").write_bytes(b"RIFF....")
    assert existing_stems(out, ["drums", "bass", "other", "vocals"]) is None


def test_existing_stems_rejects_empty_files(tmp_path):
    """An interrupted write leaves the file created and empty."""
    out = tmp_path / "digest-htdemucs"
    out.mkdir()
    (out / "drums.wav").write_bytes(b"RIFF....")
    (out / "other.wav").write_bytes(b"")
    assert existing_stems(out, ["drums", "other"]) is None


def test_existing_stems_on_a_missing_directory(tmp_path):
    assert existing_stems(tmp_path / "nothing-here", ["drums"]) is None


def test_existing_stems_of_a_model_with_more_sources(tmp_path):
    """The 4-stem set is not a complete htdemucs_6s separation, even though it
    sits in a directory of its own and every file in it is valid."""
    out = tmp_path / "digest-htdemucs_6s"
    out.mkdir()
    for name in ("drums", "bass", "other", "vocals"):
        (out / f"{name}.wav").write_bytes(b"RIFF....")
    six = ["drums", "bass", "other", "vocals", "guitar", "piano"]
    assert existing_stems(out, six) is None
