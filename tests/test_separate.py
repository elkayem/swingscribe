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


def test_a_span_names_its_own_stems_dir_in_milliseconds(tmp_path):
    from swingscribe.stages.separate import span_of_dir

    whole = stems_dir(tmp_path, "d1", "htdemucs")
    part = stems_dir(tmp_path, "d1", "htdemucs", (38.4, 75.1))
    assert part != whole
    assert part.name == "d1-htdemucs@38400-75100"
    assert span_of_dir(part) == (38.4, 75.1)
    assert span_of_dir(whole) is None


def test_covering_dirs_prefers_the_whole_file_then_any_containing_span(tmp_path):
    from swingscribe.stages.separate import covering_dirs

    whole = stems_dir(tmp_path, "d1", "m")
    wide = stems_dir(tmp_path, "d1", "m", (30.0, 80.0))
    narrow = stems_dir(tmp_path, "d1", "m", (40.0, 50.0))
    elsewhere = stems_dir(tmp_path, "d1", "m", (100.0, 120.0))
    for d in (wide, narrow, elsewhere):
        d.mkdir(parents=True)
    found = covering_dirs(tmp_path, "d1", "m", (38.4, 75.1))
    assert found[0] == whole  # first even though it does not exist yet
    assert wide in found
    assert narrow not in found and elsewhere not in found
    assert covering_dirs(tmp_path, "d1", "m", None) == [whole]  # no span: whole file only


def test_a_span_separation_writes_full_length_stems_silent_outside(tmp_path, monkeypatch):
    """The model sees only the span (plus margin); the stems it produces are
    padded back to the track's length so every consumer keeps the track's
    time base. Exercised through the Roformer path with a fake backend."""
    import hashlib

    np = pytest.importorskip("numpy")
    soundfile = pytest.importorskip("soundfile")
    from swingscribe.config import Config
    from swingscribe.model import AudioRef, Document
    from swingscribe.stages import separate

    rate = 1000
    track = tmp_path / "norm.wav"
    signal = np.ones((10 * rate, 2), dtype="float32") * 0.5  # a 10 s track
    soundfile.write(str(track), signal, rate, subtype="PCM_16")
    document = Document(
        audio_path="orig.m4a",
        sample_rate=rate,
        audio=AudioRef(path=str(track), sample_rate=rate, channels=2, duration=10.0),
    )
    config = Config(cache_dir=tmp_path / "cache")
    config = config.model_copy(
        update={
            "separate": config.separate.model_copy(
                update={"model": "bsroformer_sw", "span": (4.0, 6.0), "span_margin_s": 1.0}
            )
        }
    )
    seen = {}

    def fake_backend(audio_path, _checkpoint, out_dir):
        data, r = soundfile.read(str(audio_path), dtype="float32", always_2d=True)
        seen["frames"] = len(data)
        out_dir.mkdir(parents=True, exist_ok=True)
        stems = {}
        for name in ("drums", "bass", "other", "vocals", "guitar", "piano"):
            p = out_dir / f"{name}.wav"
            soundfile.write(str(p), data, r, subtype="PCM_16")
            stems[name] = str(p)
        return stems

    monkeypatch.setattr(separate, "_roformer_separate", fake_backend)
    result = separate.run(document, config)

    assert seen["frames"] == 4 * rate  # 3-7 s: the span plus a second either side
    other, r = soundfile.read(result.stems["other"], dtype="float32", always_2d=True)
    assert len(other) == 10 * rate  # padded back to the whole track
    assert abs(other[: 3 * rate]).max() == 0.0 and abs(other[7 * rate :]).max() == 0.0
    assert abs(other[4 * rate : 6 * rate]).min() > 0.4
    digest = hashlib.sha256(track.read_bytes()).hexdigest()[:16]
    assert Path(result.stems["other"]).parent == stems_dir(
        config.cache_dir, digest, "bsroformer_sw", (4.0, 6.0)
    )
    assert not (Path(result.stems["other"]).parent / "_span_input.wav").exists()

    # A second run over a NARROWER span is served by the set already on disk.
    monkeypatch.setattr(
        separate,
        "_roformer_separate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-separated")),
    )
    narrower = config.model_copy(
        update={"separate": config.separate.model_copy(update={"span": (4.5, 5.5)})}
    )
    assert separate.run(document, narrower).stems == result.stems


def test_roformer_output_names_map_onto_pipeline_stems():
    from swingscribe.stages.separate import roformer_stem_name

    assert roformer_stem_name("track_(Other)_BS-Roformer-SW.wav") == "other"
    assert roformer_stem_name("track_(Vocals)_BS-Roformer-SW.wav") == "vocals"
    assert roformer_stem_name("track_(Piano)_BS-Roformer-SW.wav") == "piano"
    assert roformer_stem_name("track_(Instrumental)_x.wav") is None  # not a stem we keep
    assert roformer_stem_name("track.wav") is None


def _document_for(tmp_path):
    from swingscribe.model import AudioRef, Document

    wav = tmp_path / "norm.wav"
    wav.write_bytes(b"RIFF....")
    return Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=1.0),
    )


def test_a_roformer_model_reuses_its_stems_without_loading_anything(tmp_path, monkeypatch):
    """The reuse check for a Roformer model comes from KNOWN_SOURCES, so a
    complete set on disk is served with no audio-separator (or torch)
    import at all -- CI has neither."""
    import hashlib

    from swingscribe.config import Config
    from swingscribe.stages import separate

    document = _document_for(tmp_path)
    config = Config(cache_dir=tmp_path / "cache")
    config = config.model_copy(
        update={"separate": config.separate.model_copy(update={"model": "bsroformer_sw"})}
    )
    digest = hashlib.sha256(Path(document.audio.path).read_bytes()).hexdigest()[:16]
    out = stems_dir(config.cache_dir, digest, "bsroformer_sw")
    out.mkdir(parents=True)
    for name in ("drums", "bass", "other", "vocals", "guitar", "piano"):
        (out / f"{name}.wav").write_bytes(b"RIFF....")

    def explode(*_args, **_kwargs):
        raise AssertionError("a complete set must not be re-separated")

    monkeypatch.setattr(separate, "_roformer_separate", explode)
    result = separate.run(document, config)
    assert sorted(result.stems) == ["bass", "drums", "guitar", "other", "piano", "vocals"]


def test_a_roformer_model_that_drops_a_stem_is_an_error(tmp_path, monkeypatch):
    from swingscribe.config import Config
    from swingscribe.stages import separate

    document = _document_for(tmp_path)
    config = Config(cache_dir=tmp_path / "cache")
    config = config.model_copy(
        update={"separate": config.separate.model_copy(update={"model": "bsroformer_sw"})}
    )

    def five_only(_audio, _checkpoint, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        return {
            n: str(out_dir / f"{n}.wav") for n in ("drums", "bass", "other", "vocals", "guitar")
        }

    monkeypatch.setattr(separate, "_roformer_separate", five_only)
    with pytest.raises(RuntimeError, match="piano"):
        separate.run(document, config)


def test_write_source_marker_names_the_track(tmp_path):
    """A stems directory is named by the wav digest, which nothing can turn
    back into a title; the marker beside the stems says which track they
    are, in the id the GUI uses (the SOURCE file's digest)."""
    import hashlib
    import json

    from swingscribe.model import AudioRef, Document
    from swingscribe.stages.separate import SOURCE_MARKER, write_source_marker

    source = tmp_path / "Take 3.m4a"
    source.write_bytes(b"source bytes")
    document = Document(
        audio_path=str(source),
        sample_rate=1000,
        audio=AudioRef(path=str(tmp_path / "norm.wav"), sample_rate=1000, channels=2, duration=1),
    )
    out = tmp_path / "stems" / "0123456789abcdef-htdemucs@4000-6000"
    write_source_marker(out, document, "htdemucs", (4.0, 6.0))

    record = json.loads((out / SOURCE_MARKER).read_text(encoding="utf-8"))
    assert record["track_id"] == hashlib.sha256(b"source bytes").hexdigest()[:16]
    assert record["name"] == "Take 3.m4a"
    assert record["source"] == str(source)
    assert record["model"] == "htdemucs"
    assert record["span"] == [4.0, 6.0]


def test_reusing_an_older_set_backfills_its_marker(tmp_path, monkeypatch):
    """Directories separated before the marker existed get one the first
    time they are reused, so the cache names itself without re-separating."""
    import hashlib

    from swingscribe.config import Config
    from swingscribe.stages import separate
    from swingscribe.stages.separate import SOURCE_MARKER

    document = _document_for(tmp_path)
    config = Config(cache_dir=tmp_path / "cache")
    config = config.model_copy(
        update={"separate": config.separate.model_copy(update={"model": "bsroformer_sw"})}
    )
    digest = hashlib.sha256(Path(document.audio.path).read_bytes()).hexdigest()[:16]
    out = stems_dir(config.cache_dir, digest, "bsroformer_sw")
    out.mkdir(parents=True)
    for name in ("drums", "bass", "other", "vocals", "guitar", "piano"):
        (out / f"{name}.wav").write_bytes(b"RIFF....")

    def explode(*_args, **_kwargs):
        raise AssertionError("a complete set must not be re-separated")

    monkeypatch.setattr(separate, "_roformer_separate", explode)
    assert not (out / SOURCE_MARKER).exists()
    separate.run(document, config)
    assert (out / SOURCE_MARKER).is_file()
