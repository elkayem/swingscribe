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


# ── The second loader: note-only Kong checkpoints (docs/kong-bakeoff.md) ─────


def test_note_weights_reads_every_layout_in_circulation():
    weights = {"frame_fc.weight": 1}
    assert piano.note_weights({"iteration": 5, "model": weights}) is weights
    pedal_release = {"model": {"note_model": weights, "pedal_model": {"x": 2}}}
    assert piano.note_weights(pedal_release) is weights
    assert piano.note_weights(weights) is weights  # bare weights
    with pytest.raises(ValueError):
        piano.note_weights({"model": {}})


def _tiny_network():
    """A stand-in for the 25M-parameter CRNN with the same constructor and the
    same four outputs: one frame per 160-sample hop plus the extra one a
    centred STFT gives, and each frame reads the sample it sits on, so the
    test can see where every frame of the deframed roll came from."""
    torch = pytest.importorskip("torch", reason="ml dependency group not installed")

    class TinyNet(torch.nn.Module):
        def __init__(self, frames_per_second, classes_num):
            super().__init__()
            self.scale = torch.nn.Parameter(torch.ones(1))
            self.hop = piano.MODEL_SAMPLE_RATE // frames_per_second
            self.classes = classes_num

        def forward(self, audio):
            frames = torch.nn.functional.pad(audio[:, :: self.hop], (0, 1))
            roll = frames[..., None].expand(-1, -1, self.classes) * self.scale
            return dict.fromkeys(piano.ROLLS, roll)

    return torch, TinyNet


def _no_downloads(monkeypatch):
    """Upstream's constructor would `wget` over a small file; this path must
    never fetch anything, whatever the file's size."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("the note-model loader tried to download")

    monkeypatch.setattr(piano.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(piano.os, "system", refuse)


def test_load_note_model_takes_a_small_file_strictly_and_downloads_nothing(monkeypatch, tmp_path):
    torch, tiny = _tiny_network()
    import numpy as np

    monkeypatch.setattr(piano, "_note_network_class", lambda: tiny)
    _no_downloads(monkeypatch)
    weights = tiny(piano.FRAMES_PER_SECOND, piano.CLASSES_NUM).state_dict()
    weights["scale"] = torch.full((1,), 2.0)
    path = tmp_path / "note_only.pth"
    # The real files carry the training sampler's numpy RNG state beside the
    # weights, which weights-only loading refuses unless allowlisted.
    sampler = {"rng": np.random.RandomState(0).get_state()}
    torch.save({"iteration": 25000, "model": weights, "sampler": sampler}, path)
    assert path.stat().st_size < piano.MIN_CHECKPOINT_BYTES

    model = piano.load_note_model(path)
    assert model.iteration == 25000
    assert float(model.network.scale.detach()) == 2.0  # the file's weights, not the init
    assert not model.network.training

    # The Note_pedal release's layout loads its note head.
    nested = tmp_path / "note_pedal.pth"
    torch.save({"model": {"note_model": weights, "pedal_model": {}}}, nested)
    assert float(piano.load_note_model(nested).network.scale.detach()) == 2.0

    # Keys that do not fit the network raise: upstream's strict=False would
    # have run the random initial weights without a word.
    wrong = tmp_path / "wrong.pth"
    torch.save({"model": {"frame_fc.weight": torch.ones(2)}}, wrong)
    with pytest.raises(RuntimeError):
        piano.load_note_model(wrong)
    with pytest.raises(FileNotFoundError):
        piano.load_note_model(tmp_path / "absent.pth")


def test_note_activations_deframe_like_upstream(monkeypatch, tmp_path):
    torch, tiny = _tiny_network()
    import numpy as np

    monkeypatch.setattr(piano, "_note_network_class", lambda: tiny)
    path = tmp_path / "tiny.pth"
    torch.save({"model": tiny(100, 88).state_dict()}, path)
    model = piano.load_note_model(path)

    # 25 s pads to 30 s: five half-overlapping 10 s segments, deframed to
    # 750 + 3 x 500 + 750 frames -- every one of them the sample it sits on.
    seconds = 25
    audio = (np.arange(seconds * piano.MODEL_SAMPLE_RATE) / 1e6).astype(np.float32)
    rolls = piano.note_activations(model, audio, batch_size=2)
    assert set(rolls) == set(piano.ROLLS)
    frames = rolls["frame_output"]
    assert frames.shape == (3000, piano.CLASSES_NUM)
    padded = np.concatenate([audio, np.zeros(5 * piano.MODEL_SAMPLE_RATE, np.float32)])
    np.testing.assert_allclose(frames[:, 7], padded[::160][:3000])

    # One segment is returned whole, the centred STFT's extra frame included.
    short = piano.note_activations(model, audio[: piano.MODEL_SAMPLE_RATE])
    assert short["reg_onset_output"].shape == (1001, piano.CLASSES_NUM)


def test_decode_notes_reads_one_note_off_synthetic_rolls():
    pytest.importorskip("torch", reason="ml dependency group not installed")
    pytest.importorskip("piano_transcription_inference", reason="ml group not installed")
    import numpy as np

    frames, pitch = 300, 60
    column = pitch - piano.BEGIN_NOTE
    rolls = {key: np.zeros((frames, piano.CLASSES_NUM), np.float32) for key in piano.ROLLS}
    rolls["reg_onset_output"][98:103, column] = [0.2, 0.6, 1.0, 0.6, 0.2]
    rolls["reg_offset_output"][148:153, column] = [0.2, 0.6, 1.0, 0.6, 0.2]
    rolls["frame_output"][100:150, column] = 0.9
    rolls["velocity_output"][95:155, column] = 0.5

    notes = piano.decode_notes(rolls, offset=2.0)
    assert len(notes) == 1
    note = notes[0]
    assert note["pitch"] == pitch
    assert note["onset"] == pytest.approx(3.0, abs=0.011)  # frame 100, plus the offset
    assert note["duration"] == pytest.approx(0.5, abs=0.02)
    assert note["velocity"] == 64
    assert note["onset_strength"] == pytest.approx(1.0)
    # Nothing clears a higher onset threshold.
    assert piano.decode_notes(rolls, onset_threshold=1.01) == []


def test_decode_notes_drops_the_copy_a_plateau_makes():
    """Upstream's peak test is non-strict, so two EQUAL onset frames are two
    onsets, and the second decodes to a copy of the note that ends before it
    begins. float16 rolls make such plateaus (329 of 47,143 notes on the
    horn regions); a note of no length is dropped."""
    pytest.importorskip("torch", reason="ml dependency group not installed")
    pytest.importorskip("piano_transcription_inference", reason="ml group not installed")
    import numpy as np

    frames, pitch = 300, 60
    column = pitch - piano.BEGIN_NOTE
    rolls = {key: np.zeros((frames, piano.CLASSES_NUM), np.float32) for key in piano.ROLLS}
    rolls["reg_onset_output"][98:104, column] = [0.2, 0.6, 1.0, 1.0, 0.6, 0.2]
    rolls["reg_offset_output"][148:153, column] = [0.2, 0.6, 1.0, 0.6, 0.2]
    rolls["frame_output"][100:150, column] = 0.9
    rolls["velocity_output"][95:155, column] = 0.5

    notes = piano.decode_notes(rolls)
    assert len(notes) == 1
    assert notes[0]["duration"] == pytest.approx(0.5, abs=0.02)
