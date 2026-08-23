"""Track identity, discovery and remembered state. No ml dependencies."""

import json

import pytest

from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.model import AudioRef, Document


@pytest.fixture
def config(tmp_path):
    return Config(cache_dir=tmp_path / "cache", gui={"library_dir": str(tmp_path / "music")})


def make_audio(path, payload=b"RIFF-ish bytes"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_file_digest_follows_content_not_name(tmp_path):
    a = make_audio(tmp_path / "one.wav", b"same")
    b = make_audio(tmp_path / "two.wav", b"same")
    c = make_audio(tmp_path / "three.wav", b"different")
    # Two rips of the same file are one track; the GUI and the cache agree.
    assert library.file_digest(a) == library.file_digest(b)
    assert library.file_digest(a) != library.file_digest(c)
    assert len(library.file_digest(a)) == library.DIGEST_CHARS


def test_list_tracks_filters_by_suffix(tmp_path, config):
    music = tmp_path / "music"
    make_audio(music / "solo.m4a")
    make_audio(music / "take.wav")
    make_audio(music / "notes.txt")
    (music / "subdir").mkdir()
    make_audio(music / "subdir" / "buried.wav")

    names = {entry["name"] for entry in library.list_tracks(config)}
    assert names == {"solo.m4a", "take.wav"}  # no text file, and not recursive


def test_list_tracks_hides_our_own_output(tmp_path, config):
    """`audition` and `ab` write next to the source, so the working folder fills
    with derived wavs. Offering to transcribe an A/B mix is never the intent."""
    music = tmp_path / "music"
    make_audio(music / "Gerry's Blues.m4a")
    make_audio(music / "Gerry's Blues.ab.wav")
    make_audio(music / "Gerry's Blues.other.wav")
    make_audio(music / "Gerry's Blues.click.wav")
    make_audio(music / "Gerry's Blues.6s.ab.wav")
    make_audio(music / "a real take.wav")

    names = {entry["name"] for entry in library.list_tracks(config)}
    assert names == {"Gerry's Blues.m4a", "a real take.wav"}


def test_list_tracks_survives_a_missing_directory(config):
    assert library.list_tracks(config) == []


def test_state_round_trips_and_merges(config):
    library.save_state(config, "abc123", {"region": [10.0, 20.0], "stem": "other"})
    library.save_state(config, "abc123", {"stem": "guitar"})
    state = library.load_state(config, "abc123")
    # A partial save updates one key without dropping the rest.
    assert state == {"region": [10.0, 20.0], "stem": "guitar"}


def test_load_state_tolerates_a_corrupt_sidecar(config, tmp_path):
    path = tmp_path / "cache" / "gui" / "bad.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    # UI state is disposable: a damaged sidecar means "forget where I was",
    # never a failure to open the track.
    assert library.load_state(config, "bad") == {}


def test_recent_tracks_drops_entries_whose_audio_has_gone(config, tmp_path):
    present = make_audio(tmp_path / "music" / "here.wav")
    library.save_state(config, "aaa", {"path": str(present), "opened_at": 1.0})
    library.save_state(config, "bbb", {"path": str(tmp_path / "gone.wav"), "opened_at": 2.0})

    recent = library.recent_tracks(config)
    assert [entry["name"] for entry in recent] == ["here.wav"]


def test_recent_tracks_is_newest_first(config, tmp_path):
    older = make_audio(tmp_path / "music" / "older.wav", b"a")
    newer = make_audio(tmp_path / "music" / "newer.wav", b"b")
    library.save_state(config, "aaa", {"path": str(older), "opened_at": 1.0})
    library.save_state(config, "bbb", {"path": str(newer), "opened_at": 9.0})
    assert [entry["name"] for entry in library.recent_tracks(config)] == [
        "newer.wav",
        "older.wav",
    ]


def test_available_stems_reads_the_separate_stage_layout(config, tmp_path):
    """The GUI must find stems the CLI wrote, so it derives the directory from
    stages.separate rather than duplicating the naming rule."""
    wav = make_audio(tmp_path / "cache" / "audio" / "norm.wav", b"normalized")
    document = Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=12.0),
    )
    from swingscribe.stages.separate import stems_dir

    out = stems_dir(config.cache_dir, library.file_digest(wav), "htdemucs_6s")
    out.mkdir(parents=True)
    for name in ("drums", "bass", "other", "guitar"):
        (out / f"{name}.wav").write_bytes(b"stem")

    assert library.available_stems(document, config, "htdemucs_6s").keys() == {
        "drums",
        "bass",
        "other",
        "guitar",
    }
    assert library.available_stems(document, config, "htdemucs_ft") == {}


def test_model_status_reports_readiness_in_config_order(config, tmp_path):
    wav = make_audio(tmp_path / "cache" / "audio" / "norm.wav", b"normalized")
    document = Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=12.0),
    )
    from swingscribe.stages.separate import stems_dir

    out = stems_dir(config.cache_dir, library.file_digest(wav), "htdemucs_ft")
    out.mkdir(parents=True)
    (out / "other.wav").write_bytes(b"stem")

    status = library.model_status(document, config)
    assert [entry["model"] for entry in status] == config.gui.models
    assert [entry["ready"] for entry in status] == [True, False]


def test_gui_config_never_reaches_a_cache_key(config):
    """gui.* is UI state. If it ever fed a stage key, changing a port would
    throw away a thirteen-minute separation."""
    with pytest.raises(KeyError):
        config.stage_config("gui")
    baseline = json.dumps(config.stage_config("separate"), sort_keys=True)
    moved = config.model_copy(update={"gui": config.gui.model_copy(update={"port": 9999})})
    assert json.dumps(moved.stage_config("separate"), sort_keys=True) == baseline
