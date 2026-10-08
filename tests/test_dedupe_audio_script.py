"""scripts/dedupe_audio.py: byte-identical copies become linked takes of one
file -- planned in a dry run, applied only when asked."""

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dedupe_audio  # noqa: E402

from swingscribe.gui import library  # noqa: E402


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
    dedupe_audio.main([str(tmp_path), "--keep-in", "Multi-Horn", "--apply"])
    assert not copy.exists() and keep.is_file()
    data = json.loads(own.read_text())
    assert data["region"] == [0, 67.3]
    assert library.audio_of(own) == keep
    # Its key -- the sidecar's own path -- did not move.
    keys = {key for key, *_ in library.discover(tmp_path)}
    assert "Transcriptions_Other/Open-Sesame-copy.m4a" in keys
