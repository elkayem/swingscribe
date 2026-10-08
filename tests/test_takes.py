"""Linked sidecars ("takes"): a sidecar IS a track (gui/library.py).

Pure file arithmetic, so all of it runs in CI: no fastapi, no audio decode.
"""

import json

import pytest

from swingscribe.config import Config
from swingscribe.gui import library, storage


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def folder(tmp_path):
    music = tmp_path / "Multi-Horn"
    music.mkdir()
    audio = music / "Open_Sesame.m4a"
    audio.write_bytes(b"pretend this is an m4a")
    return music, audio


def test_an_audio_s_own_sidecar_is_the_track_it_always_was(folder):
    music, audio = folder
    own = write(library.settings_path(audio), {"region": [0, 10], "file": audio.name})
    assert library.take_key(own) == "Open_Sesame.m4a"
    assert library.audio_of(own) == audio
    assert not library.is_linked(own, audio)
    assert library.track_id_for(audio, own) == library.file_digest(audio)
    assert library.track_id_for(audio) == library.file_digest(audio)


def test_a_linked_take_names_its_audio_and_has_an_id_of_its_own(folder):
    music, audio = folder
    take = write(music / "Open_Sesame_Melody.swingscribe.json", {"audio": "Open_Sesame.m4a"})
    assert library.audio_of(take) == audio
    assert library.is_linked(take, audio)
    track_id = library.track_id_for(audio, take)
    assert track_id.startswith(library.file_digest(audio) + "-")
    assert library.audio_digest_of(track_id) == library.file_digest(audio)
    other = write(music / "Open_Sesame_Hubbard.swingscribe.json", {"audio": "Open_Sesame.m4a"})
    assert library.track_id_for(audio, other) != track_id


def test_a_take_may_live_in_another_folder(tmp_path, folder):
    music, audio = folder
    elsewhere = tmp_path / "Transcriptions_Other"
    elsewhere.mkdir()
    take = write(elsewhere / "Head.swingscribe.json", {"audio": "../Multi-Horn/Open_Sesame.m4a"})
    assert library.audio_of(take) == audio


def test_settings_go_through_the_take_s_own_sidecar(folder):
    music, audio = folder
    config = Config(cache_dir=music / "cache")
    own = write(library.settings_path(audio), {"region": [0, 10], "ensemble": "horn-led"})
    take = write(music / "Open_Sesame_Melody.swingscribe.json", {"audio": audio.name})
    track_id = library.track_id_for(audio, take)
    library.save_settings(audio, {"ensemble": "multi-horn"}, config, take)
    assert library.load_settings(audio, config, track_id, take)["ensemble"] == "multi-horn"
    # The audio's own sidecar is untouched.
    assert json.loads(own.read_text())["ensemble"] == "horn-led"
    saved = json.loads(take.read_text())
    assert saved["audio"] == "Open_Sesame.m4a"
    assert saved["file"] == "Open_Sesame.m4a"
    # And the own sidecar still saves as it always did, with no `audio`.
    library.save_settings(audio, {"stem": "other"}, config)
    assert "audio" not in json.loads(own.read_text())


def test_update_settings_reads_and_writes_the_take(folder):
    music, audio = folder
    config = Config(cache_dir=music / "cache")
    take = write(music / "T.swingscribe.json", {"audio": audio.name, "count": 1})
    library.update_settings(audio, config, lambda s: {"count": s["count"] + 1}, sidecar=take)
    assert json.loads(take.read_text())["count"] == 2


def test_a_new_take_copies_the_recording_and_not_the_span(folder):
    music, audio = folder
    write(
        library.settings_path(audio),
        {
            "anchor": 8.46,
            "form_start": 8.46,
            "model": "bsroformer_sw",
            "bars_per_chorus": 32,
            "changes": "| Bb6 |",
            "region": [0, 67.3],
            "ensemble": "multi-horn",
            "erasures": [{"onset": 1.0, "pitch": 60}],
            "score": "x.mscz",
        },
    )
    take = library.new_take(audio, "Open_Sesame_Freddie_Hubbard_solo")
    assert take == music / "Open_Sesame_Freddie_Hubbard_solo.swingscribe.json"
    data = json.loads(take.read_text())
    assert data["anchor"] == 8.46 and data["model"] == "bsroformer_sw"
    assert data["changes"] == "| Bb6 |" and data["bars_per_chorus"] == 32
    for fresh in ("region", "ensemble", "erasures", "score"):
        assert fresh not in data
    assert data["audio"] == "Open_Sesame.m4a"
    with pytest.raises(FileExistsError):
        library.new_take(audio, "Open_Sesame_Freddie_Hubbard_solo")


def test_a_new_take_can_go_in_another_folder(tmp_path, folder):
    music, audio = folder
    elsewhere = tmp_path / "heads"
    take = library.new_take(audio, "Head", folder=elsewhere)
    assert take.parent == elsewhere
    assert library.audio_of(take) == audio


def test_take_names_must_be_file_names(folder):
    _music, audio = folder
    for bad in ("", "  ", "a/b", "a\\b", "what?", "..", "x."):
        with pytest.raises(ValueError):
            library.new_take(audio, bad)


def test_renaming_the_own_sidecar_makes_it_a_linked_take(folder):
    music, audio = folder
    own = write(library.settings_path(audio), {"region": [1, 2], "anchor": 3.0})
    renamed = library.rename_take(own, audio, "Open_Sesame_Melody")
    assert not own.exists()
    data = json.loads(renamed.read_text())
    assert data["region"] == [1, 2] and data["anchor"] == 3.0
    assert data["audio"] == "Open_Sesame.m4a"
    assert library.audio_of(renamed) == audio
    with pytest.raises(FileExistsError):
        write(music / "Other.swingscribe.json", {"audio": audio.name})
        library.rename_take(renamed, audio, "Other")


def test_discover_keys_own_sidecars_by_their_audio_and_takes_by_name(tmp_path, folder):
    music, audio = folder
    root = tmp_path
    write(library.settings_path(audio), {})
    write(music / "Open_Sesame_Melody.swingscribe.json", {"audio": audio.name})
    write(music / "Gone.swingscribe.json", {"audio": "Gone.m4a"})
    write(root / "Flat.mp3.swingscribe.json", {})
    found = {key: (sidecar.name, audio_path) for key, sidecar, audio_path in library.discover(root)}
    assert found["Multi-Horn/Open_Sesame.m4a"][1] == audio
    assert found["Multi-Horn/Open_Sesame_Melody"][1] == audio
    assert found["Flat.mp3"][1] == root / "Flat.mp3"
    # A missing audio is still discovered; the caller decides.
    assert not found["Multi-Horn/Gone"][1].is_file()


def test_the_browser_groups_takes_under_their_audio(tmp_path, folder):
    music, audio = folder
    config = Config(cache_dir=tmp_path / "cache")
    (music / "Lonely.m4a").write_bytes(b"x")
    write(library.settings_path(audio), {})
    write(music / "Open_Sesame_Melody.swingscribe.json", {"audio": audio.name})
    elsewhere = tmp_path / "Transcriptions_Other"
    elsewhere.mkdir()
    (elsewhere / "copy.m4a").write_bytes(b"y")
    write(music / "Head.swingscribe.json", {"audio": "../Transcriptions_Other/copy.m4a"})
    write(music / "Missing.swingscribe.json", {"audio": "nowhere.m4a"})

    listing = library.browse(music, config)
    files = {f["name"]: f for f in listing["files"]}
    assert files["Lonely.m4a"]["takes"] == []
    assert [t["name"] for t in files["Open_Sesame.m4a"]["takes"]] == [
        "Open_Sesame.m4a",
        "Open_Sesame_Melody",
    ]
    assert [t["linked"] for t in files["Open_Sesame.m4a"]["takes"]] == [False, True]
    away = {t["name"]: t for t in listing["takes"]}
    assert away["Head"]["relative"] == "../Transcriptions_Other/copy.m4a"
    assert not away["Head"]["missing"]
    assert away["Missing"]["missing"]


def test_recents_name_a_linked_take_and_forget_a_renamed_one(tmp_path, folder):
    music, audio = folder
    config = Config(cache_dir=tmp_path / "cache")
    take = write(music / "Melody.swingscribe.json", {"audio": audio.name, "region": [1, 2]})
    track_id = library.track_id_for(audio, take)
    library.remember_open(config, track_id, audio, sidecar=take)
    library.remember_open(config, library.file_digest(audio), audio)
    names = {r["id"]: r["name"] for r in library.recent_tracks(config)}
    assert names[track_id] == "Melody"
    assert names[library.file_digest(audio)] == "Open_Sesame.m4a"
    assert library.remembered_sidecar(config, track_id) == str(take)
    library.rename_take(take, audio, "Melody2")
    assert track_id not in {r["id"] for r in library.recent_tracks(config)}


def test_the_cache_panel_says_which_takes_share_a_recording(tmp_path, folder):
    music, audio = folder
    config = Config(cache_dir=tmp_path / "cache")
    digest = library.file_digest(audio)
    wav = tmp_path / "cache" / "audio" / f"{digest}-44100.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"wav")
    take = write(music / "Melody.swingscribe.json", {"audio": audio.name})
    library.remember_open(config, digest, audio, stem_digest="a" * 16)
    library.remember_open(
        config, library.track_id_for(audio, take), audio, stem_digest="a" * 16, sidecar=take
    )
    listing = storage.inventory(config)
    (track,) = listing["tracks"]
    assert track["id"] == digest
    assert [t["name"] for t in track["takes"]] == ["Open_Sesame.m4a", "Melody"]
