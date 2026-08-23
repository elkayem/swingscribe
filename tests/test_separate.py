"""Separate stage. Pure helpers run everywhere (CI included); the end-to-end
test downloads model weights and runs the real separator, so it is opt-in via
SWINGSCRIBE_HEAVY_TESTS=1."""

import os
from pathlib import Path

import pytest

from swingscribe.stages.separate import resolve_device, stems_dir

requires_heavy = pytest.mark.skipif(
    not os.environ.get("SWINGSCRIBE_HEAVY_TESTS"),
    reason="Set SWINGSCRIBE_HEAVY_TESTS=1 to run tests that download model weights",
)


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
