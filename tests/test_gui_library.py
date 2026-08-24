"""Track identity, discovery and remembered state. No ml dependencies."""

import json
import pathlib

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


def test_settings_live_beside_the_audio_not_in_the_cache(config, tmp_path):
    """The cache holds derived data that must stay safely deletable; a span and
    a downbeat are judgements that took listening to reach. Clearing gigabytes
    of stems must not cost you those."""
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    library.save_settings(audio, {"region": [10.0, 20.0], "stem": "other"}, config)

    beside = tmp_path / "music" / "tune.m4a.swingscribe.json"
    assert beside.is_file()
    assert not (config.cache_dir / "gui" / "tune.json").exists()

    # And it survives the cache being thrown away entirely.
    import shutil

    shutil.rmtree(config.cache_dir, ignore_errors=True)
    assert library.load_settings(audio, config, "any-id")["stem"] == "other"


def test_settings_merge_rather_than_replace(config, tmp_path):
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    library.save_settings(audio, {"region": [10.0, 20.0], "stem": "other"}, config)
    library.save_settings(audio, {"stem": "guitar"}, config)
    settings = library.load_settings(audio, config, "id")
    assert settings["region"] == [10.0, 20.0]
    assert settings["stem"] == "guitar"


def test_settings_name_their_own_track(config, tmp_path):
    """The file sits in the user's music folder, so it should be identifiable
    without opening it against a directory listing."""
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    library.save_settings(audio, {"stem": "other"}, config)
    assert library.load_settings(audio, config, "id")["file"] == "tune.m4a"


def test_old_cache_sidecars_are_migrated_forward(config, tmp_path):
    """Settings written before the move must not be silently lost."""
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    track_id = library.file_digest(audio)
    legacy = config.cache_dir / "gui" / f"{track_id}.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps({"region": [5.0, 9.0], "stem": "piano", "path": str(audio)}),
        encoding="utf-8",
    )

    settings = library.load_settings(audio, config, track_id)
    assert settings["region"] == [5.0, 9.0]
    assert settings["stem"] == "piano"
    assert library.settings_path(audio).is_file()  # brought forward on read
    assert "path" not in settings  # bookkeeping stays in the recents index


def test_settings_fall_back_to_the_cache_when_the_folder_is_read_only(
    config, tmp_path, monkeypatch
):
    """A read-only music library or a mounted share must not lose the work."""
    audio = make_audio(tmp_path / "music" / "tune.m4a")

    real_write = pathlib.Path.write_text

    def refuse(self, *args, **kwargs):
        if self.name.endswith(library.SETTINGS_SUFFIX):
            raise OSError("read-only")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", refuse)
    written = library.save_settings(audio, {"stem": "bass"}, config)
    assert config.cache_dir in written.parents


def test_load_settings_tolerates_a_corrupt_file(config, tmp_path):
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    library.settings_path(audio).write_text("{not json", encoding="utf-8")
    # Settings are a convenience: a damaged file means "forget where I was",
    # never a failure to open the track.
    assert library.load_settings(audio, config, "id") == {}


def test_every_setting_the_gui_persists_survives_a_restart(config, tmp_path):
    """Closing the app and reopening must bring back where you were. Written
    over the real payload so a newly persisted setting that nothing restores
    shows up here."""
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    settings = {
        "region": [85.07, 208.03],
        "stem": "guitar",
        "model": "htdemucs_6s",
        "beats_shown": True,
        "snap_mode": "bar",
        "time_signature": "3/4",
        "anchor": 6.68,
        "bars_per_chorus": 16,
        "form_start": 1.76,
    }
    library.save_settings(audio, settings, config)
    library.remember_open(config, "trackid", audio)

    restored = library.load_settings(audio, config, "trackid")
    assert {key: restored[key] for key in settings} == settings

    recent = library.recent_tracks(config)
    assert [entry["name"] for entry in recent] == ["tune.m4a"]
    assert recent[0]["region"] == [85.07, 208.03]
    assert recent[0]["stem"] == "guitar"


def test_recent_tracks_drops_entries_whose_audio_has_gone(config, tmp_path):
    present = make_audio(tmp_path / "music" / "here.wav")
    library.remember_open(config, "aaa", present)
    library.remember_open(config, "bbb", tmp_path / "gone.wav")
    assert [e["name"] for e in library.recent_tracks(config)] == ["here.wav"]


def test_recent_tracks_is_newest_first(config, tmp_path):
    older = make_audio(tmp_path / "music" / "older.wav", b"a")
    newer = make_audio(tmp_path / "music" / "newer.wav", b"b")
    # Explicit timestamps: two real calls can land in the same clock tick.
    library.remember_open(config, "aaa", older, when=1.0)
    library.remember_open(config, "bbb", newer, when=9.0)
    assert [e["name"] for e in library.recent_tracks(config)] == ["newer.wav", "older.wav"]


def test_recent_tracks_order_is_stable_when_timestamps_tie(config, tmp_path):
    first = make_audio(tmp_path / "music" / "alpha.wav", b"a")
    second = make_audio(tmp_path / "music" / "beta.wav", b"b")
    library.remember_open(config, "aaa", first, when=5.0)
    library.remember_open(config, "bbb", second, when=5.0)
    assert [e["name"] for e in library.recent_tracks(config)] == ["alpha.wav", "beta.wav"]


def test_losing_the_recents_index_does_not_lose_settings(config, tmp_path):
    """The index is disposable by design; the settings are not."""
    audio = make_audio(tmp_path / "music" / "tune.m4a")
    library.save_settings(audio, {"stem": "guitar"}, config)
    library.remember_open(config, "aaa", audio)
    (config.cache_dir / "gui" / "recents.json").unlink()

    assert library.recent_tracks(config) == []
    assert library.load_settings(audio, config, "aaa")["stem"] == "guitar"


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
