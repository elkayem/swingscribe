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


def test_browse_defaults_to_library_dir(tmp_path, config):
    music = tmp_path / "music"
    make_audio(music / "solo.m4a")
    (music / "subdir").mkdir()

    result = library.browse(None, config)
    assert result["path"] == str(music.resolve())
    assert [d["name"] for d in result["dirs"]] == ["subdir"]
    assert [f["name"] for f in result["files"]] == ["solo.m4a"]


def test_browse_navigates_to_an_explicit_path(tmp_path, config):
    other = tmp_path / "elsewhere"
    make_audio(other / "take.wav")
    result = library.browse(str(other), config)
    assert result["path"] == str(other.resolve())
    assert [f["name"] for f in result["files"]] == ["take.wav"]


def test_browse_reports_parent_for_navigation_up(tmp_path, config):
    child = tmp_path / "a" / "b"
    child.mkdir(parents=True)
    result = library.browse(str(child), config)
    assert result["parent"] == str(child.parent)


def test_browse_drive_root_has_no_parent():
    drives = library.list_drives()
    result = library.browse(drives[0], Config())
    assert result["parent"] is None


def test_browse_excludes_our_own_derived_output(tmp_path, config):
    music = tmp_path / "music"
    make_audio(music / "Blues.m4a")
    make_audio(music / "Blues.ab.wav")

    result = library.browse(str(music), config)
    assert [f["name"] for f in result["files"]] == ["Blues.m4a"]


def test_browse_skips_hidden_entries(tmp_path, config):
    music = tmp_path / "music"
    make_audio(music / "solo.m4a")
    (music / ".git").mkdir(parents=True)

    result = library.browse(str(music), config)
    assert result["dirs"] == []


def test_browse_rejects_a_file_path(tmp_path, config):
    audio = make_audio(tmp_path / "music" / "solo.m4a")
    with pytest.raises(NotADirectoryError):
        library.browse(str(audio), config)


def test_browse_rejects_a_missing_path(tmp_path, config):
    with pytest.raises(NotADirectoryError):
        library.browse(str(tmp_path / "does-not-exist"), config)


def test_browse_lists_are_sorted_case_insensitively(tmp_path, config):
    music = tmp_path / "music"
    make_audio(music / "banana.wav")
    make_audio(music / "Apple.wav")
    make_audio(music / "cherry.wav")

    names = [f["name"] for f in library.browse(str(music), config)["files"]]
    assert names == ["Apple.wav", "banana.wav", "cherry.wav"]


def test_browse_reports_available_drives():
    drives = library.list_drives()
    assert all(d.endswith(":\\") for d in drives)
    assert len(drives) >= 1  # the drive this repo lives on, at minimum


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


def _stem_document(config, tmp_path, names, model="htdemucs_6s", levels=None, rate=8000):
    """A Document whose stems dir holds wavs named `names`.

    `levels` writes real audio at those constant amplitudes (needs the ml
    group's soundfile); without it the stems are opaque bytes, which is all
    the name-level tests read.
    """
    from swingscribe.stages.separate import stems_dir

    wav = make_audio(tmp_path / "cache" / "audio" / "norm.wav", b"normalized")
    document = Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=12.0),
    )
    out = stems_dir(config.cache_dir, library.file_digest(wav), model)
    out.mkdir(parents=True)
    for i, name in enumerate(names):
        if levels is None:
            (out / f"{name}.wav").write_bytes(b"stem")
            continue
        import numpy as np
        import soundfile

        soundfile.write(
            out / f"{name}.wav",
            np.full((rate, 2), levels[i], "float32"),
            rate,
            subtype="FLOAT",
        )
    return document, out


def test_selectable_stems_offers_a_sum_the_separator_never_wrote(config, tmp_path):
    """Demucs switches an instrument it cannot place BETWEEN stems rather than
    attenuating it across them, so the stem you picked can go bit-zero mid-solo
    (Miles' Oleo: 29.8% of the span). The menu therefore offers the sum."""
    document, _ = _stem_document(config, tmp_path, ("drums", "bass", "other", "vocals"))

    assert "other+vocals" in library.selectable_stems(document, config, "htdemucs_6s")
    # Offered, never separated — it must not pretend to be one of demucs' own.
    assert "other+vocals" not in library.available_stems(document, config, "htdemucs_6s")


def test_selectable_stems_withholds_a_sum_missing_a_part(config, tmp_path):
    document, _ = _stem_document(config, tmp_path, ("drums", "bass", "other"))

    assert library.selectable_stems(document, config, "htdemucs_6s") == [
        "bass",
        "drums",
        "other",
    ]
    assert library.resolve_stem(document, config, "htdemucs_6s", "other+vocals") is None


def test_resolve_stem_leaves_a_separated_stem_alone(config, tmp_path):
    """A separated stem must resolve to the SAME path `available_stems` gives,
    or every review key already computed against it silently changes."""
    document, _ = _stem_document(config, tmp_path, ("other", "vocals"))
    stems = library.available_stems(document, config, "htdemucs_6s")

    assert library.resolve_stem(document, config, "htdemucs_6s", "other") == stems["other"]


def test_resolve_stem_sums_the_parts_sample_for_sample(config, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")

    document, out = _stem_document(config, tmp_path, ("other", "vocals"), levels=(0.6, 0.7))

    path = library.resolve_stem(document, config, "htdemucs_6s", "other+vocals")
    assert path is not None
    data, rate = soundfile.read(path, dtype="float32", always_2d=True)
    assert rate == 8000
    # 0.6 + 0.7, sample for sample — addition, not an averaging mix-down, so
    # neither source is attenuated by being summed with the other. And it is
    # held in float: 1.3 would clip to 1.0 in the default 16-bit PCM, taking
    # the peaks the soloist is loudest in with it.
    assert np.allclose(data, 1.3)
    # Written beside the stems it is made of, so clearing the cache clears it.
    assert pathlib.Path(path).parent == out
    assert not list(out.glob("*.partial.wav"))


def test_resolve_stem_reuses_a_sum_it_already_wrote(config, tmp_path):
    pytest.importorskip("soundfile")

    document, _ = _stem_document(config, tmp_path, ("other", "vocals"), levels=(0.1, 0.2))

    first = library.resolve_stem(document, config, "htdemucs_6s", "other+vocals")
    stamp = pathlib.Path(first).stat().st_mtime_ns
    second = library.resolve_stem(document, config, "htdemucs_6s", "other+vocals")

    assert first == second
    assert pathlib.Path(second).stat().st_mtime_ns == stamp


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
    for name in ("drums", "bass", "other", "vocals"):
        (out / f"{name}.wav").write_bytes(b"stem")

    status = library.model_status(document, config)
    assert [entry["model"] for entry in status] == config.gui.models
    ready = {entry["model"]: entry["ready"] for entry in status}
    assert ready["htdemucs_ft"] is True  # the only one with its stems on disk
    assert all(v is False for k, v in ready.items() if k != "htdemucs_ft")


def test_a_partial_stem_folder_is_not_ready_and_says_what_is_missing(config, tmp_path):
    """One stem copied across from another cache (CLAUDE.md's own advice)
    used to read as "Separated", which hid the Separate button and left a
    stem menu of one -- Crazy Rhythm's tenor was in `guitar` and unreachable."""
    wav = make_audio(tmp_path / "cache" / "audio" / "norm.wav", b"normalized")
    document = Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=12.0),
    )
    from swingscribe.stages.separate import stems_dir

    out = stems_dir(config.cache_dir, library.file_digest(wav), "htdemucs_6s")
    out.mkdir(parents=True)
    (out / "other.wav").write_bytes(b"stem")

    entry = {e["model"]: e for e in library.model_status(document, config)}["htdemucs_6s"]
    assert entry["ready"] is False
    assert entry["stems"] == ["other"]  # still listed: resolve_stem may use it
    assert entry["missing"] == ["drums", "bass", "vocals", "guitar", "piano"]


def test_gui_config_never_reaches_a_cache_key(config):
    """gui.* is UI state. If it ever fed a stage key, changing a port would
    throw away a thirteen-minute separation."""
    with pytest.raises(KeyError):
        config.stage_config("gui")
    baseline = json.dumps(config.stage_config("separate"), sort_keys=True)
    moved = config.model_copy(update={"gui": config.gui.model_copy(update={"port": 9999})})
    assert json.dumps(moved.stage_config("separate"), sort_keys=True) == baseline


def test_stem_dropout_measures_digital_silence_over_the_span(config, tmp_path):
    """The diagnostic that found R16, and it needs no reference at all: demucs
    writes true zero where it has moved a source to another stem."""
    soundfile = pytest.importorskip("soundfile")
    np = pytest.importorskip("numpy")

    rate = 8000
    audio = np.full((10 * rate, 2), 0.2, "float32")
    audio[3 * rate : 6 * rate] = 0.0  # three seconds the source left
    path = tmp_path / "other.wav"
    soundfile.write(path, audio, rate, subtype="FLOAT")

    assert library.stem_dropout(path) == pytest.approx(0.3, abs=0.05)
    # ...and only over the span asked about: the silence is outside this one.
    assert library.stem_dropout(path, (6.0, 10.0)) == 0.0


def test_choose_stem_reaches_for_the_sum_only_when_the_stem_drops_out(config, tmp_path):
    """`other` going quiet is not a soft horn — it is a horn in another file.
    But a clean stem must be left alone: the sum carries the partner's bleed."""
    pytest.importorskip("soundfile")
    import numpy as np
    import soundfile

    from swingscribe.stages.separate import stems_dir

    rate = 8000
    wav = make_audio(tmp_path / "cache" / "audio" / "norm.wav", b"normalized")
    document = Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=10.0),
    )
    out = stems_dir(config.cache_dir, library.file_digest(wav), "htdemucs_6s")
    out.mkdir(parents=True)

    def write(name, holes):
        data = np.full((10 * rate, 2), 0.2, "float32")
        for lo, hi in holes:
            data[lo * rate : hi * rate] = 0.0
        soundfile.write(out / f"{name}.wav", data, rate, subtype="FLOAT")

    write("other", [(2, 6)])  # 40% gone — the soloist has left
    write("vocals", [(0, 2), (6, 10)])  # and is here instead
    stem, report = library.choose_stem(document, config, "htdemucs_6s", (0.0, 10.0))
    assert stem == "other+vocals"
    assert report["other"] > library.DROPOUT_LIMIT
    assert report["other+vocals"] == 0.0

    # A clean `other` is never traded for the sum.
    write("other", [])
    stem, report = library.choose_stem(document, config, "htdemucs_6s", (0.0, 10.0))
    assert stem == "other"
    assert "other+vocals" not in report  # not even built — no reason to look
