"""The eval harness's track discovery.

Not alignment code, but the same class of harm: a benchmark that scores a
SUBSET without saying so reports a number about less music than it claims.
That has now happened three times — once when a stale grids file made
`wjazz_beat_f1` a mean over 4 beside a note F1 over 11 (R8), and once when
`benchmark/` grew subfolders and two of the three sidecar globs were made
recursive while the third was not, costing every track under
`benchmark/wjazzd/` its beat score and its notation score. The third was
the same harm with the sign flipped: the notes cache is keyed by track name
and only ever added to, so renaming eight tracks left eight orphan entries
behind and every one of them was scored a second time under its old name.

Pure path logic, so it runs in CI with no audio and no ml group.
"""

import contextlib
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


# -- the notes cache must not outlive its tracks ---------------------------


def _cached(sidecar_path: Path, names: list[str]) -> dict:
    """Cache entries that are genuine hits, so transcribe_all never reaches the
    audio -- these tests are about which keys survive, not about decoding."""
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    fingerprint = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
    return {name: {"fingerprint": fingerprint, "notes": []} for name in names}


def test_a_cached_run_whose_track_is_gone_is_not_scored(tmp_path, monkeypatch):
    """Renaming a track leaves its old entry in the notes cache. Everything
    downstream iterates those keys, so the orphan gets scored a second time
    under its old name and the mean is over more tracks than exist."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path / "wjazzd", "New_Name.m4a")
    cache = tmp_path / "notes.json"
    cache.write_text(
        json.dumps(_cached(path, ["wjazzd/Old_Name.m4a", "wjazzd/New_Name.m4a"])), encoding="utf-8"
    )
    runs = run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=lambda *_a: None)
    assert set(runs) == {"wjazzd/New_Name.m4a"}


def test_the_orphan_stays_in_the_cache_file(tmp_path, monkeypatch):
    """It cost minutes of CREPE and comes straight back if the rename is
    reverted. It is dropped from what gets SCORED, not from the file."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    path = write_sidecar(tmp_path / "wjazzd", "New_Name.m4a")
    cache = tmp_path / "notes.json"
    cache.write_text(
        json.dumps(_cached(path, ["wjazzd/Old_Name.m4a", "wjazzd/New_Name.m4a"])), encoding="utf-8"
    )
    run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=lambda *_a: None)
    assert "wjazzd/Old_Name.m4a" in json.loads(cache.read_text(encoding="utf-8"))


# -- the notes cache must encode the transcriber, not just its filename ----


def test_the_fingerprint_moves_when_the_routing_moves(tmp_path):
    """`ensemble` routes the piano oracle. Two sidecars that differ only there
    describe different transcriptions and may not share a cached run."""
    horn = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "horn-led"}
    piano = {**horn, "ensemble": "trio"}
    assert run_eval.transcribe_fingerprint(horn, 0.2, 0.0) != run_eval.transcribe_fingerprint(
        piano, 0.2, 0.0
    )


def test_the_fingerprint_moves_when_the_span_moves(tmp_path):
    a = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "horn-led"}
    b = {**a, "region": [0.0, 20.0]}
    assert run_eval.transcribe_fingerprint(a, 0.2, 0.0) != run_eval.transcribe_fingerprint(
        b, 0.2, 0.0
    )


def test_the_fingerprint_moves_when_the_stage_changes_behaviour(monkeypatch):
    """A new step in transcribe with no config change -- the piano gap-fill was
    exactly this -- must still invalidate. The stage's CACHE_VERSION is what
    says so, the same way pipeline._cache_name reads it."""
    from swingscribe.stages import transcribe

    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "trio"}
    before = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
    monkeypatch.setattr(transcribe, "CACHE_VERSION", 99, raising=False)
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0) != before


def test_the_fingerprint_is_stable_for_the_same_settings():
    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "trio"}
    assert run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0) == run_eval.transcribe_fingerprint(
        dict(sidecar), 0.2, 0.0
    )


def test_a_run_cached_before_fingerprints_existed_is_recomputed(tmp_path, monkeypatch):
    """No fingerprint means the entry predates this check and there is no way
    to know what produced it. Serving it is the staleness hole."""
    monkeypatch.setattr(run_eval, "BENCH", tmp_path)
    write_sidecar(tmp_path, "Solo.m4a", ensemble="horn-led")
    cache = tmp_path / "notes.json"
    cache.write_text(json.dumps({"Solo.m4a": {"ensemble": "horn-led", "notes": []}}), "utf-8")
    said = []
    # The decision is what is under test. Everything after it needs real audio,
    # so let it fail there -- a cache HIT would have returned before logging
    # anything at all, which is the behaviour being ruled out.
    with contextlib.suppress(Exception):
        run_eval.transcribe_all(cache, step_cost=0.2, dip_db=0.0, log=said.append)
    assert any("re-transcribing" in line for line in said)


def test_a_null_stem_falls_back_to_the_default():
    """A sidecar can carry `stem: null` - the listener never chose one. That is
    not "there is no stem": untreated it reached the filesystem as "None.wav"
    and the track was silently skipped, which nobody saw because a cached run
    kept answering for it (R15)."""
    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": None, "ensemble": "horn-led"}
    assert run_eval.transcribe_settings(sidecar, 0.2, 0.0).stem == "other"


def test_resolving_a_null_stem_does_not_disturb_a_chosen_one():
    """The fallback must not move the fingerprint of every other track, or
    every cached transcription is thrown away to fix one sidecar."""
    sidecar = {"region": [0.0, 10.0], "model": "htdemucs", "stem": "other", "ensemble": "trio"}
    settings = run_eval.transcribe_settings(sidecar, 0.2, 0.0)
    assert settings.stem == "other"
