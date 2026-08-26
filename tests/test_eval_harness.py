"""The eval harness's track discovery.

Not alignment code, but the same class of harm: a benchmark that scores a
SUBSET without saying so reports a number about less music than it claims.
That has now happened twice — once when a stale grids file made
`wjazz_beat_f1` a mean over 4 beside a note F1 over 11 (R8), and once when
`benchmark/` grew subfolders and two of the three sidecar globs were made
recursive while the third was not, costing every track under
`benchmark/wjazzd/` its beat score and its notation score.

Pure path logic, so it runs in CI with no audio and no ml group.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

run_eval = pytest.importorskip("run_eval")
score_benchmark = pytest.importorskip("score_benchmark")


def write_sidecar(folder: Path, audio: str, **extra) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / audio).write_bytes(b"not really audio")
    payload = {"file": audio, "region": [0.0, 10.0], "model": "htdemucs", "stem": "other"}
    payload.update(extra)
    path = folder / f"{audio}.swingscribe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_track_in_the_root_keeps_its_bare_name(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path, "Solo.m4a")
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert run_eval.sidecar_name(path, sidecar) == "Solo.m4a"


def test_a_track_in_a_subfolder_is_keyed_by_its_path(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path / "wjazzd", "Solo.m4a")
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    # Forward slashes, so a key pinned on Windows matches one pinned anywhere.
    assert run_eval.sidecar_name(path, sidecar) == "wjazzd/Solo.m4a"


def test_two_tracks_of_the_same_name_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    a = write_sidecar(tmp_path, "Solo.m4a")
    b = write_sidecar(tmp_path / "wjazzd", "Solo.m4a")
    names = {run_eval.sidecar_name(p, json.loads(p.read_text(encoding="utf-8"))) for p in (a, b)}
    assert len(names) == 2


def test_discover_tunes_finds_a_score_in_a_subfolder(tmp_path):
    (tmp_path / "Hand.mscz").write_bytes(b"pretend")
    write_sidecar(
        tmp_path / "wjazzd",
        "Solo.m4a",
        score=str(tmp_path / "Hand.mscz"),
        ensemble="trio",
    )
    found = score_benchmark.discover_tunes(tmp_path)
    assert len(found) == 1
    audio, mscz_name, _title, instrument = next(iter(found.values()))
    assert audio == "wjazzd/Solo.m4a"
    assert mscz_name == "Hand.mscz"
    assert instrument == "piano"


def test_a_sidecar_without_a_score_is_not_a_benchmark_tune(tmp_path):
    write_sidecar(tmp_path, "Solo.m4a")
    assert score_benchmark.discover_tunes(tmp_path) == {}


def test_every_sidecar_walk_in_the_harness_is_recursive():
    """A structural guard, because the failure it prevents is silent: the run
    still succeeds, it just quietly covers less music than its header claims."""
    for path in (SCRIPTS / "run_eval.py", SCRIPTS / "score_benchmark.py"):
        source = path.read_text(encoding="utf-8")
        assert '.glob("*.swingscribe.json")' not in source, (
            f"{path.name} walks sidecars with a flat glob; tracks in "
            f"benchmark/ subfolders would be skipped without a word"
        )
        assert '.rglob("*.swingscribe.json")' in source
