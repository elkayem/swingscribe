"""The piano oracle's weights: where they live (plan §13, the portable build)."""

from pathlib import Path

import pytest

pytest.importorskip("numpy", reason="ml dependency group not installed")

from swingscribe import piano  # noqa: E402


def test_checkpoint_lives_under_home_by_default(monkeypatch):
    monkeypatch.delenv("SWINGSCRIBE_MODELS_DIR", raising=False)
    path = piano.checkpoint_path()
    assert path.parent == Path.home() / "piano_transcription_inference_data"
    assert path.name == piano.CHECKPOINT_NAME


def test_models_dir_override_moves_it(monkeypatch, tmp_path):
    """The portable build points every model download at one per-user
    folder: TORCH_HOME for demucs and beat_this, AUDIO_SEPARATOR_MODEL_DIR
    for the Roformer, and this for the piano checkpoint."""
    monkeypatch.setenv("SWINGSCRIBE_MODELS_DIR", str(tmp_path / "models"))
    assert piano.checkpoint_path() == tmp_path / "models" / piano.CHECKPOINT_NAME


def test_ensure_checkpoint_is_a_no_op_when_the_file_is_whole(monkeypatch, tmp_path):
    monkeypatch.setattr(piano, "MIN_CHECKPOINT_BYTES", 4)
    target = tmp_path / piano.CHECKPOINT_NAME
    target.write_bytes(b"weights!")
    logged = []
    assert piano.ensure_checkpoint(target, log=logged.append) == target
    assert logged == []  # nothing fetched, nothing announced
