"""Linked sidecars through the GUI's HTTP surface: opening a take, keeping
two takes of one recording apart, New take and Rename take."""

import json

import pytest

from swingscribe.config import Config
from swingscribe.model import AudioRef, Document

pytest.importorskip("fastapi", reason="gui dependency group not installed")
try:
    from fastapi.testclient import TestClient
except RuntimeError as exc:  # starlette's test client wants its http library
    pytest.skip(f"no test client: {exc}", allow_module_level=True)

from swingscribe.gui import app as gui_app  # noqa: E402
from swingscribe.gui import library  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    music = tmp_path / "Multi-Horn"
    music.mkdir()
    audio = music / "Open_Sesame.m4a"
    audio.write_bytes(b"pretend this is an m4a")
    copy = tmp_path / "Transcriptions_Other" / "Open-Sesame-copy.m4a"
    copy.parent.mkdir()
    copy.write_bytes(b"pretend this is an m4a")  # byte-identical
    wav = tmp_path / "cache" / "audio" / "normalized.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"wav")
    config = Config(cache_dir=tmp_path / "cache", gui={"library_dir": str(music)})

    def ingested(path, cfg):
        return Document(
            audio_path=str(path),
            sample_rate=44100,
            audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=60.0),
        )

    monkeypatch.setattr(library, "ingested_document", ingested)
    client = TestClient(gui_app.create_app(config))
    return {"client": client, "audio": audio, "copy": copy, "music": music}


def open_path(world, path, sidecar=None):
    body = {"path": str(path)} | ({"sidecar": str(sidecar)} if sidecar else {})
    response = world["client"].post("/api/tracks/open", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def save(world, track_id, state):
    response = world["client"].post(f"/api/tracks/{track_id}/state", json={"state": state})
    assert response.status_code == 200, response.text
    return response.json()


def test_byte_identical_copies_with_their_own_sidecars_are_two_tracks(world):
    first = open_path(world, world["audio"])
    second = open_path(world, world["copy"])
    # The same bytes are one recording -- one digest, one cache -- but each
    # copy has its own sidecar: the first keeps the plain digest, the other
    # is named for its sidecar (library.claim_track_id).
    digest = library.file_digest(world["audio"])
    assert first["id"] == digest
    assert second["id"] != digest and second["id"].startswith(digest + "-")
    save(world, first["id"], {"region": [1, 2]})
    save(world, second["id"], {"region": [3, 4]})
    assert json.loads(library.settings_path(world["audio"]).read_text())["region"] == [1, 2]
    assert json.loads(library.settings_path(world["copy"]).read_text())["region"] == [3, 4]


def test_opening_a_take_reads_and_writes_its_own_sidecar(world):
    own = open_path(world, world["audio"])
    save(world, own["id"], {"region": [0, 67.308], "anchor": 8.46})
    take_path = world["music"] / "Open_Sesame_Melody.swingscribe.json"
    take_path.write_text(json.dumps({"audio": "Open_Sesame.m4a", "ensemble": "multi-horn"}))
    take = open_path(world, take_path)
    assert take["id"] != own["id"]
    assert take["name"] == "Open_Sesame_Melody"
    assert take["linked"] is True
    assert take["sidecar"] == str(take_path)
    assert take["state"]["ensemble"] == "multi-horn"
    save(world, take["id"], {"region": [10, 20]})
    assert json.loads(take_path.read_text())["region"] == [10, 20]
    # The tab still open on the own sidecar reads its own region, untouched.
    response = world["client"].post(f"/api/tracks/{own['id']}/state", json={"state": {}})
    assert response.json()["settings"]["region"] == [0, 67.308]


def test_new_take_starts_from_the_recording_judgements(world):
    own = open_path(world, world["audio"])
    save(world, own["id"], {"region": [0, 67.3], "anchor": 8.46, "ensemble": "multi-horn"})
    response = world["client"].post(
        f"/api/tracks/{own['id']}/takes", json={"name": "Open_Sesame_Freddie_Hubbard_solo"}
    )
    assert response.status_code == 200, response.text
    take = response.json()
    assert take["name"] == "Open_Sesame_Freddie_Hubbard_solo"
    assert take["state"]["anchor"] == 8.46
    assert "region" not in take["state"] and "ensemble" not in take["state"]
    again = world["client"].post(
        f"/api/tracks/{own['id']}/takes", json={"name": "Open_Sesame_Freddie_Hubbard_solo"}
    )
    assert again.status_code == 409
    bad = world["client"].post(f"/api/tracks/{own['id']}/takes", json={"name": "a/b"})
    assert bad.status_code == 400


def test_rename_turns_the_own_sidecar_into_a_linked_take(world):
    own = open_path(world, world["audio"])
    save(world, own["id"], {"region": [5, 6]})
    response = world["client"].post(
        f"/api/tracks/{own['id']}/rename", json={"name": "Open_Sesame_Melody"}
    )
    assert response.status_code == 200, response.text
    renamed = response.json()
    assert renamed["linked"] and renamed["name"] == "Open_Sesame_Melody"
    assert renamed["state"]["region"] == [5, 6]
    assert not library.settings_path(world["audio"]).exists()
    assert renamed["id"] != own["id"]


def test_the_browser_lists_takes(world):
    open_path(world, world["audio"])
    (world["music"] / "Head.swingscribe.json").write_text(json.dumps({"audio": "Open_Sesame.m4a"}))
    listing = world["client"].get("/api/browse", params={"path": str(world["music"])}).json()
    (audio,) = listing["files"]
    assert [t["name"] for t in audio["takes"]] == ["Head"]


def test_a_copy_keeps_its_id_across_a_restart(world):
    first = open_path(world, world["audio"])
    second = open_path(world, world["copy"])
    world["client"].app.state.tracks.clear()  # the server restarted
    state = save(world, second["id"], {"region": [7, 8]})
    assert state["settings_path"] == str(library.settings_path(world["copy"]))
    assert first["id"] != second["id"]
