"""scripts/dedupe_audio.py: byte-identical copies become linked takes of one
file -- planned in a dry run, applied only when asked."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dedupe_audio  # noqa: E402

from swingscribe.gui import library  # noqa: E402


def trash(tmp_path):
    """Where --apply keeps the copies here: there is no Recycle Bin on Linux."""
    return ["--trash", str(tmp_path / ".dedupe" / "trash")]


def setup(tmp_path):
    keep = tmp_path / "Multi-Horn" / "Open_Sesame.m4a"
    copy = tmp_path / "Transcriptions_Other" / "Open-Sesame-copy.m4a"
    for path in (keep, copy):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"the same bytes")
    (tmp_path / "Multi-Horn" / "Other.m4a").write_bytes(b"different bytes")
    own = library.settings_path(copy)
    own.write_text(json.dumps({"region": [0, 67.3], "file": copy.name}))
    return keep, copy, own


def test_a_dry_run_changes_nothing(tmp_path, capsys):
    keep, copy, own = setup(tmp_path)
    assert dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn"]) == 0
    printed = capsys.readouterr().out
    assert "DELETE Transcriptions_Other/Open-Sesame-copy.m4a" in printed
    assert "dry run" in printed
    assert copy.is_file() and "audio" not in json.loads(own.read_text())


def test_apply_links_the_copy_s_sidecar_to_the_kept_file(tmp_path):
    keep, copy, own = setup(tmp_path)
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply", *trash(tmp_path)])
    assert not copy.exists() and keep.is_file()
    data = json.loads(own.read_text())
    assert data["region"] == [0, 67.3]
    assert library.audio_of(own) == keep
    # Its key -- the sidecar's own path -- did not move.
    keys = {key for key, *_ in library.discover(tmp_path)}
    assert "Transcriptions_Other/Open-Sesame-copy.m4a" in keys


def test_the_original_is_kept_by_default(tmp_path, monkeypatch, capsys):
    """The listener copied INTO Multi-Horn: the file created first stays."""
    keep, copy, own = setup(tmp_path)
    times = {keep: 2.0, copy: 1.0}
    monkeypatch.setattr(dedupe_audio, "created", lambda path: times.get(path, 0.0))
    dedupe_audio.main([str(tmp_path)])
    printed = capsys.readouterr().out
    assert "KEEP Transcriptions_Other/Open-Sesame-copy.m4a" in printed
    assert "DELETE Multi-Horn/Open_Sesame.m4a" in printed


def test_one_file_under_two_players_names_is_left_alone(tmp_path, capsys):
    folder = tmp_path / "Transcriptions_Other"
    folder.mkdir()
    parker = folder / "Charlie-Parker-Ballade.m4a"
    hawkins = folder / "Coleman-Hawkins-Ballade.m4a"
    for path in (parker, hawkins):
        path.write_bytes(b"one download, two labels")
    dedupe_audio.main([str(tmp_path), "--apply", *trash(tmp_path)])
    printed = capsys.readouterr().out
    assert "LEAVE" in printed and "another recording" in printed
    assert "DELETE" not in printed
    assert parker.is_file() and hawkins.is_file()


def test_a_linked_take_naming_the_deleted_copy_is_repointed(tmp_path, capsys):
    keep, copy, own = setup(tmp_path)
    take = tmp_path / "Multi-Horn" / "Open_Sesame_Melody.swingscribe.json"
    take.write_text(
        json.dumps({"audio": "../Transcriptions_Other/Open-Sesame-copy.m4a", "anchor": 8.46})
    )
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn"])
    printed = capsys.readouterr().out
    assert "REPOINT Multi-Horn/Open_Sesame_Melody.swingscribe.json -> audio Open_Sesame.m4a" in (
        printed
    )
    assert "LINK Transcriptions_Other/Open-Sesame-copy.m4a.swingscribe.json" in printed
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply", *trash(tmp_path)])
    assert library.audio_of(take) == keep
    assert json.loads(take.read_text())["anchor"] == 8.46
    keys = {key for key, *_ in library.discover(tmp_path)}
    assert "Multi-Horn/Open_Sesame_Melody" in keys


def test_two_solos_of_one_recording_are_linked_whatever_their_names(tmp_path, capsys):
    """Local task A2: the name rule left every WJazzD multi-solo recording
    and every Parker copy. A sidecar carries a solo's identity, so a copy
    with one is linked however differently it is named."""
    folder = tmp_path / "wjazzd"
    folder.mkdir()
    fuller = folder / "Curtis_Fuller_Blue_Train.wav"
    morgan = folder / "Lee_Morgan_Blue_Train.wav"
    for path, region in ((fuller, [100, 160]), (morgan, [40, 100])):
        path.write_bytes(b"one side, three solos")
        library.settings_path(path).write_text(json.dumps({"region": region}))
    dedupe_audio.main([str(tmp_path), "--apply", *trash(tmp_path)])
    printed = capsys.readouterr().out
    assert "LEAVE" not in printed
    assert "DELETE wjazzd/Lee_Morgan_Blue_Train.wav" in printed
    own = library.settings_path(morgan)
    assert library.audio_of(own) == fuller
    assert json.loads(own.read_text())["region"] == [40, 100]


def test_a_copy_with_no_sidecar_paired_with_a_page_by_name_is_left(tmp_path, capsys):
    kept = tmp_path / "wjazzd" / "CharlieParker_EmbraceableYou.wav"
    copy = tmp_path / "Transcriptions_Other" / "CharlieParker-EmbraceableYou-take.wav"
    for path in (kept, copy):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"the same take")
    (copy.parent / "musicxml").mkdir()
    (copy.parent / "musicxml" / f"{copy.stem}.musicxml").write_text("<score-partwise/>")
    dedupe_audio.main([str(tmp_path), "--keep-in", "wjazzd", "--apply"])
    printed = capsys.readouterr().out
    assert "LEAVE Transcriptions_Other/CharlieParker-EmbraceableYou-take.wav" in printed
    assert "paired with it by name" in printed
    assert copy.is_file()


# ── --apply never deletes, and --undo puts it back ──────────────────────────


def manifest_of(tmp_path):
    (found,) = (tmp_path / ".dedupe").glob("manifest-*.json")
    return found


def test_apply_moves_the_copy_to_the_trash_and_writes_a_manifest(tmp_path):
    keep, copy, own = setup(tmp_path)
    before = own.read_text()
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply", *trash(tmp_path)])
    assert not copy.exists()
    moved = tmp_path / ".dedupe" / "trash" / "Transcriptions_Other" / "Open-Sesame-copy.m4a"
    assert moved.read_bytes() == b"the same bytes"
    manifest = json.loads(manifest_of(tmp_path).read_text())
    (step,) = manifest["steps"]
    assert step["status"] == "done" and step["went_to"] == str(moved)
    (sidecar,) = step["sidecars"]
    assert sidecar["verb"] == "LINK" and sidecar["before"] == before


def test_undo_restores_the_audio_and_every_sidecar(tmp_path, capsys):
    keep, copy, own = setup(tmp_path)
    take = tmp_path / "Multi-Horn" / "Open_Sesame_Melody.swingscribe.json"
    take.write_text(json.dumps({"audio": "../Transcriptions_Other/Open-Sesame-copy.m4a"}))
    own_before, take_before = own.read_text(), take.read_text()
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply", *trash(tmp_path)])
    assert not copy.exists() and library.audio_of(take) == keep
    assert dedupe_audio.main(["--undo", str(manifest_of(tmp_path))]) == 0
    assert copy.read_bytes() == b"the same bytes"
    assert own.read_text() == own_before and take.read_text() == take_before
    assert json.loads(manifest_of(tmp_path).read_text())["steps"][0]["status"] == "undone"
    assert "undone" in capsys.readouterr().out


def test_undo_leaves_a_sidecar_edited_since_and_says_so(tmp_path, capsys):
    keep, copy, own = setup(tmp_path)
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply", *trash(tmp_path)])
    edited = json.loads(own.read_text()) | {"anchor": 1.5}
    own.write_text(json.dumps(edited))
    assert dedupe_audio.main(["--undo", str(manifest_of(tmp_path))]) == 1
    assert copy.is_file()  # the audio still comes back
    assert json.loads(own.read_text())["anchor"] == 1.5
    assert "edited since" in capsys.readouterr().out


def test_apply_without_a_recycle_bin_needs_a_trash(tmp_path, monkeypatch):
    keep, copy, own = setup(tmp_path)
    monkeypatch.setattr(dedupe_audio.sys, "platform", "linux")
    with pytest.raises(SystemExit, match="--trash"):
        dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply"])
    assert copy.is_file() and "audio" not in json.loads(own.read_text())


def test_a_trash_the_walk_would_read_is_refused(tmp_path):
    keep, copy, own = setup(tmp_path)
    with pytest.raises(SystemExit, match="hidden"):
        dedupe_audio.main(
            [str(tmp_path), "--keep-in", "Multi-Horn", "--apply", "--trash", str(tmp_path / "t")]
        )
    assert copy.is_file()
