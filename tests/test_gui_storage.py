"""The cache storage view: naming what the cache holds, and letting go of it.
No ml dependencies -- everything here is paths and json."""

import json
from pathlib import Path

import pytest

from swingscribe.config import Config
from swingscribe.gui import library, storage
from swingscribe.stages.separate import SOURCE_MARKER, stems_dir

STEMS = ("drums", "bass", "other", "vocals")


@pytest.fixture
def config(tmp_path):
    return Config(cache_dir=tmp_path / "cache")


def make_track(tmp_path, config, name, source_bytes, wav_bytes, *, remember=True, digest=True):
    """A source file, its ingested wav in the cache, and (optionally) its
    recents entry, with or without the wav digest already learned."""
    source = tmp_path / "music" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(source_bytes)
    track_id = library.file_digest(source)
    wav = Path(config.cache_dir) / "audio" / f"{track_id}-44100.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(wav_bytes)
    wav_digest = library.file_digest(wav)
    if remember:
        library.remember_open(
            config, track_id, source, when=1.0, stem_digest=wav_digest if digest else None
        )
    return {"id": track_id, "source": source, "wav": wav, "digest": wav_digest}


def make_stems(config, digest, model, span=None, size=1000, marker=None):
    out = stems_dir(config.cache_dir, digest, model, span)
    out.mkdir(parents=True)
    for name in STEMS:
        (out / f"{name}.wav").write_bytes(b"x" * size)
    if marker is not None:
        (out / SOURCE_MARKER).write_text(json.dumps(marker), encoding="utf-8")
    return out


def test_inventory_groups_stems_under_their_track(tmp_path, config):
    track = make_track(tmp_path, config, "Oleo.m4a", b"oleo", b"w" * 500)
    whole = make_stems(config, track["digest"], "htdemucs", size=100)
    span = make_stems(config, track["digest"], "htdemucs_6s", span=(1.0, 2.5), size=50)

    listing = storage.inventory(config)

    assert [t["name"] for t in listing["tracks"]] == ["Oleo.m4a"]
    entry = listing["tracks"][0]
    assert entry["id"] == track["id"]
    assert entry["known"] is True
    assert entry["path"] == str(track["source"])
    assert [a["bytes"] for a in entry["audio"]] == [500]
    assert [(s["name"], s["model"], s["span"], s["bytes"]) for s in entry["stems"]] == [
        (whole.name, "htdemucs", None, 400),
        (span.name, "htdemucs_6s", [1.0, 2.5], 200),
    ]
    assert entry["bytes"] == 500 + 400 + 200
    assert listing["orphans"] == []
    assert listing["total_bytes"] >= entry["bytes"]


def test_tracks_are_listed_largest_first(tmp_path, config):
    small = make_track(tmp_path, config, "small.m4a", b"s", b"w" * 10)
    big = make_track(tmp_path, config, "big.m4a", b"b", b"v" * 10)
    make_stems(config, small["digest"], "htdemucs", size=10)
    make_stems(config, big["digest"], "htdemucs", size=1000)
    assert [t["name"] for t in storage.inventory(config)["tracks"]] == ["big.m4a", "small.m4a"]


def test_a_marker_names_a_directory_the_recents_index_never_saw(tmp_path, config):
    """Stems separated from the CLI belong to a track the GUI never opened;
    the marker separate.py writes is what names them anyway."""
    track = make_track(tmp_path, config, "Sandu.m4a", b"sandu", b"w" * 10, remember=False)
    make_stems(
        config,
        track["digest"],
        "bsroformer_sw",
        marker={"track_id": track["id"], "name": "Sandu.m4a", "source": str(track["source"])},
    )

    listing = storage.inventory(config)
    assert len(listing["tracks"]) == 1
    entry = listing["tracks"][0]
    assert entry["name"] == "Sandu.m4a"
    assert entry["known"] is False
    assert entry["path"] == str(track["source"])
    assert [s["model"] for s in entry["stems"]] == ["bsroformer_sw"]


def test_the_wav_digest_is_learned_once_and_remembered(tmp_path, config, monkeypatch):
    """A recents entry from before `stem_digest` existed: the first inventory
    hashes the ingest wav to name the directory, and writes the answer back
    so the second never hashes anything."""
    track = make_track(tmp_path, config, "Old.m4a", b"old", b"w" * 10, digest=False)
    make_stems(config, track["digest"], "htdemucs")
    assert "stem_digest" not in library.recent_index(config)[track["id"]]

    first = storage.inventory(config)
    assert [t["name"] for t in first["tracks"]] == ["Old.m4a"]
    assert first["orphans"] == []
    assert library.recent_index(config)[track["id"]]["stem_digest"] == track["digest"]
    assert library.recent_index(config)[track["id"]]["opened_at"] == 1.0  # untouched

    def explode(_path):
        raise AssertionError("hashed the wav a second time")

    monkeypatch.setattr(storage, "_hash_file", explode)
    second = storage.inventory(config)
    assert [t["name"] for t in second["tracks"]] == ["Old.m4a"]


def test_a_wav_the_gui_never_opened_still_claims_its_stems(tmp_path, config, monkeypatch):
    """The eval harness ingests tracks the recents index never sees. Their
    stems are joined to their wav by hashing it -- once, then remembered in
    the memo -- so the group is at least coherent, if unnamed."""
    track = make_track(tmp_path, config, "Batch.m4a", b"batch", b"w" * 10, remember=False)
    stems = make_stems(config, track["digest"], "htdemucs_6s", size=10)

    first = storage.inventory(config)
    assert first["orphans"] == []
    [entry] = first["tracks"]
    assert entry["id"] == track["id"]
    assert entry["name"] == track["id"]  # nothing names it, so the id is shown
    assert entry["known"] is False and entry["path"] is None
    assert [s["name"] for s in entry["stems"]] == [stems.name]
    assert track["id"] not in library.recent_index(config)  # not invented as "recent"

    def explode(_path):
        raise AssertionError("hashed the wav a second time")

    monkeypatch.setattr(storage, "_hash_file", explode)
    assert [t["id"] for t in storage.inventory(config)["tracks"]] == [track["id"]]

    # The memo is keyed by size and mtime: a rewritten wav is hashed afresh.
    track["wav"].write_bytes(b"different" * 3)
    monkeypatch.setattr(storage, "_hash_file", lambda _path: "0000000000000000")
    assert storage.inventory(config)["orphans"][0]["name"] == stems.name


def test_a_directory_nobody_can_name_is_an_orphan(tmp_path, config):
    make_track(tmp_path, config, "Known.m4a", b"k", b"w" * 10)
    stray = make_stems(config, "feedfacefeedface", "htdemucs", size=10)
    stems_root = Path(config.cache_dir) / "stems"
    (stems_root / "notes").mkdir()  # not a stems directory: not ours to list or delete
    (stems_root / "README.txt").write_text("x", encoding="utf-8")

    listing = storage.inventory(config)
    assert [o["name"] for o in listing["orphans"]] == [stray.name]
    assert listing["orphan_bytes"] == 40
    assert listing["orphans"][0]["digest"] == "feedfacefeedface"


def test_busy_targets_reads_job_snapshots(tmp_path):
    source = tmp_path / "a.m4a"
    jobs = [
        {"path": str(source), "model": "htdemucs", "kind": "separate", "state": "running"},
        {"path": str(source), "model": "htdemucs_6s", "kind": "separate", "state": "queued"},
        {"path": str(source), "model": "htdemucs_ft", "kind": "separate", "state": "done"},
        {"path": str(source), "model": "bsroformer_sw", "kind": "transcribe", "state": "running"},
    ]
    assert storage.busy_targets(jobs) == {
        (str(source.resolve()), "htdemucs"),
        (str(source.resolve()), "htdemucs_6s"),
    }


def test_delete_stems_refuses_anything_but_a_stems_directory(tmp_path, config):
    track = make_track(tmp_path, config, "T.m4a", b"t", b"w" * 10)
    make_stems(config, track["digest"], "htdemucs")
    for bad in ("..", "../audio", "gui", "stems", f"{track['digest']}-htdemucs/../../audio"):
        with pytest.raises(ValueError):
            storage.delete_stems(config, bad)
    with pytest.raises(FileNotFoundError):
        storage.delete_stems(config, f"{track['digest']}-htdemucs_ft")
    assert (Path(config.cache_dir) / "audio").is_dir()  # nothing escaped


def test_delete_stems_removes_the_directory_and_reports_its_size(tmp_path, config):
    track = make_track(tmp_path, config, "T.m4a", b"t", b"w" * 10)
    keep = make_stems(config, track["digest"], "htdemucs", size=10)
    gone = make_stems(config, track["digest"], "htdemucs_6s", size=25)

    assert storage.delete_stems(config, gone.name) == 100
    assert not gone.exists()
    assert keep.is_dir()
    assert [s["model"] for s in storage.inventory(config)["tracks"][0]["stems"]] == ["htdemucs"]


def test_delete_stems_refuses_a_separation_in_progress(tmp_path, config):
    track = make_track(tmp_path, config, "T.m4a", b"t", b"w" * 10)
    running = make_stems(config, track["digest"], "htdemucs")
    idle = make_stems(config, track["digest"], "htdemucs_6s")
    busy = {(str(track["source"].resolve()), "htdemucs")}

    listing = storage.inventory(config, busy)
    assert [s["busy"] for s in listing["tracks"][0]["stems"]] == [True, False]
    with pytest.raises(storage.InUseError):
        storage.delete_stems(config, running.name, busy)
    assert running.is_dir()
    storage.delete_stems(config, idle.name, busy)
    assert not idle.exists()

    with pytest.raises(storage.InUseError):
        storage.delete_track(config, track["id"], busy)
    assert running.is_dir() and track["wav"].is_file()


def test_delete_track_keeps_the_sidecar_and_the_recents_entry(tmp_path, config):
    """Reclaiming disk must not cost a span or a downbeat, and the track must
    still be findable afterwards: only derived data goes."""
    track = make_track(tmp_path, config, "T.m4a", b"t", b"w" * 10)
    other = make_track(tmp_path, config, "Other.m4a", b"o", b"v" * 10)
    a = make_stems(config, track["digest"], "htdemucs", size=10)
    b = make_stems(config, track["digest"], "htdemucs_6s", span=(0.0, 4.0), size=10)
    theirs = make_stems(config, other["digest"], "htdemucs", size=10)
    peaks = Path(config.cache_dir) / "gui" / "peaks" / f"{track['id']}-1200.json"
    peaks.parent.mkdir(parents=True)
    peaks.write_text("[]", encoding="utf-8")
    sidecar = library.save_settings(track["source"], {"region": [1.0, 2.0]}, config)

    result = storage.delete_track(config, track["id"])

    assert result["freed"] == 10 + 40 + 40 + 2
    assert set(result["removed"]) == {a.name, b.name, track["wav"].name, peaks.name}
    assert not a.exists() and not b.exists() and not track["wav"].exists()
    assert not peaks.exists()
    assert theirs.is_dir() and other["wav"].is_file()  # another track's data
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["region"] == [1.0, 2.0]
    assert track["id"] in library.recent_index(config)
    assert [t["name"] for t in storage.inventory(config)["tracks"]] == ["Other.m4a"]


def test_delete_survives_onedrive_holding_the_emptied_directory(tmp_path, config, monkeypatch):
    """On this machine rmtree deletes every file and then fails on the
    directory itself (WinError 5: OneDrive still holds it). The bytes are
    gone, which is what the listener asked for; an empty directory is not
    an error, and the inventory hides and sweeps it."""
    track = make_track(tmp_path, config, "T.m4a", b"t", b"w" * 10)
    stems = make_stems(config, track["digest"], "htdemucs", size=10)
    calls = []

    def onedrive_rmtree(path):
        calls.append(path)
        for child in Path(path).iterdir():
            child.unlink()
        raise PermissionError(5, "Access is denied", str(path))

    monkeypatch.setattr(storage.shutil, "rmtree", onedrive_rmtree)
    monkeypatch.setattr(storage.time, "sleep", lambda _s: None)
    assert storage.delete_stems(config, stems.name) == 40
    assert len(calls) == 5  # retried, then accepted the empty directory
    assert stems.is_dir() and not any(stems.iterdir())

    listing = storage.inventory(config)
    assert listing["tracks"][0]["stems"] == []  # hidden ...
    assert not stems.exists()  # ... and swept once the lock let go


def test_delete_still_fails_when_files_remain(tmp_path, config, monkeypatch):
    track = make_track(tmp_path, config, "T.m4a", b"t", b"w" * 10)
    stems = make_stems(config, track["digest"], "htdemucs", size=10)

    def stuck(path):
        raise PermissionError(5, "Access is denied", str(path))

    monkeypatch.setattr(storage.shutil, "rmtree", stuck)
    monkeypatch.setattr(storage.time, "sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        storage.delete_stems(config, stems.name)
    assert len(list(stems.glob("*.wav"))) == 4


def test_a_track_whose_audio_moved_is_flagged(tmp_path, config):
    track = make_track(tmp_path, config, "Was Here.m4a", b"t", b"w" * 10)
    make_stems(config, track["digest"], "htdemucs", size=10)
    track["source"].unlink()

    [entry] = storage.inventory(config)["tracks"]
    assert entry["name"] == "Was Here.m4a"  # still named, from the index
    assert entry["known"] is True
    assert entry["source_exists"] is False


def test_delete_track_validates_the_id(config):
    with pytest.raises(ValueError):
        storage.delete_track(config, "../gui")
    with pytest.raises(FileNotFoundError):
        storage.delete_track(config, "0123456789abcdef")
