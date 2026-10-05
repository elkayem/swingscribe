"""Find the solos in the GUI (roadmap O3): `gui/solos.py` and its routes.

The first half is the record logic -- what the listener did with a proposed
span, matched back by content -- and runs in CI with nothing installed. The
middle writes real (tiny, synthetic) stem wavs and needs numpy for the
envelopes. The routes at the bottom need the gui group as well. Nothing here
runs a separation or a beat tracker: the job's separation is stubbed with a
function that writes stems, and the beat grid is a cache hit faked the way
the export tests fake it.
"""

import json
import threading
import time
import wave

import pytest

from swingscribe.config import Config
from swingscribe.gui import jobs, storage
from swingscribe.gui import solos as gui_solos
from swingscribe.gui.solos import ACCEPTED, ADJUSTED, IGNORED, decide, match, merge

MODEL = "htdemucs_6s"
SIX = ("drums", "bass", "other", "vocals", "guitar", "piano")

HORN = {"start": 10.0, "end": 42.0, "lead": "other", "kind": "section"}
PIANO = {"start": 42.0, "end": 74.0, "lead": "piano", "kind": "section"}
HEAD = {"start": 0.0, "end": 10.0, "lead": "other", "kind": "head"}
SPANS = [HEAD, HORN, PIANO]


def _decide(selection, origin=None, records=(), spans=SPANS):
    return decide(spans, selection, origin, list(records), MODEL, "default", now=1000.0)


# ── what a selection says about the proposals (CI) ───────────────────────────


def test_a_clicked_span_kept_as_it_is_was_accepted():
    record = _decide((10.0, 42.0), origin=HORN)
    assert record["action"] == ACCEPTED
    assert record["clicked"] is True
    assert (record["start"], record["end"], record["lead"], record["kind"]) == (
        10.0,
        42.0,
        "other",
        "section",
    )
    assert record["moved"] == [0.0, 0.0]
    assert record["model"] == MODEL and record["level"] == "default"


def test_a_clicked_span_with_a_moved_edge_says_by_how_much():
    """Selection minus proposal: A a bar earlier is negative, B later positive."""
    record = _decide((8.0, 42.5), origin=HORN)
    assert record["action"] == ADJUSTED
    assert record["moved"] == [-2.0, 0.5]
    assert record["selection"] == [8.0, 42.5]


def test_a_selection_drawn_over_an_unclicked_span_ignored_it():
    record = _decide((12.5, 40.0))
    assert record["action"] == IGNORED
    assert record["clicked"] is False
    assert (record["start"], record["end"]) == (10.0, 42.0)
    assert record["moved"] == [2.5, -2.0]


def test_a_selection_over_two_bands_is_about_the_one_it_overlaps_most():
    """Both bands lie wholly inside it; the larger share of the union wins."""
    spans = [
        {"start": 0.0, "end": 20.0, "lead": "other", "kind": "section"},
        {"start": 20.0, "end": 60.0, "lead": "other", "kind": "section"},
    ]
    record = _decide((0.0, 60.0), spans=spans)
    assert (record["start"], record["end"]) == (20.0, 60.0)
    assert record["overlap"] == pytest.approx(40 / 60, abs=1e-3)


def test_a_selection_about_no_proposal_records_nothing():
    """A few seconds straddling a boundary lies mostly inside neither span."""
    assert _decide((41.0, 43.0), spans=[HORN, PIANO]) is not None  # half in each: one wins
    assert _decide((100.0, 120.0)) is None
    # Mostly outside every span: 2 s of a 30 s selection overlap the head.
    assert decide([HEAD], (8.0, 38.0), None, [], MODEL, "default") is None


def test_a_click_is_remembered_so_a_later_drag_over_it_is_an_adjustment():
    """The origin lives in the page and is lost on a reload; the record's
    `clicked` is what keeps "I took this band and then moved it" from being
    written back as "ignored"."""
    first = _decide((10.0, 42.0), origin=HORN)
    later = _decide((9.5, 42.0), origin=None, records=[first])
    assert later["action"] == ADJUSTED and later["clicked"] is True
    back = _decide((10.0, 42.0), origin=None, records=[later])
    assert back["action"] == ACCEPTED


def test_the_origin_is_let_go_once_the_selection_is_elsewhere():
    """Clicked the horn band, then drew a selection over the piano band: that
    is about the piano band, which the listener did not click."""
    record = _decide((44.0, 72.0), origin=HORN)
    assert (record["start"], record["end"]) == (42.0, 74.0)
    assert record["action"] == IGNORED


def test_the_origin_need_not_be_among_the_spans_on_screen():
    """A band clicked at one level stays the selection's origin after the
    level changes and it is no longer drawn."""
    record = _decide((10.0, 42.0), origin={**HORN, "level": "more"}, spans=[PIANO])
    assert record["action"] == ACCEPTED
    assert record["level"] == "more"


def test_merge_replaces_the_record_for_the_same_proposal_and_nothing_else():
    old = _decide((12.0, 40.0))
    other = _decide((44.0, 72.0))
    foreign = {"start": 10.0, "end": 42.0, "model": "bsroformer_sw", "action": IGNORED}
    junk = {"note": "hand-edited, unreadable"}
    records = [old, other, foreign, junk]
    new = _decide((10.0, 42.0), origin=HORN, records=records)
    merged = merge(records, new)
    assert merged[0] == new  # same proposal, same stem set: replaced in place
    assert merged[1:] == [other, foreign, junk]  # never dropped, never reordered
    assert merge([], new) == [new]


def test_records_are_matched_back_by_content_not_by_index():
    record = _decide((10.0, 42.0), origin=HORN)
    # A re-proposal at another level: the spans are renumbered, and the horn
    # band's edges agree to the millisecond.
    renumbered = [
        {"start": 0.0, "end": 10.0},
        {"start": 10.0, "end": 26.0},
        {"start": 26.0, "end": 42.0},
        {"start": 10.0004, "end": 41.9996},
    ]
    assert match([record], renumbered, MODEL) == {3: 0}
    # A downbeat moved a beat: the proposal is a different one now.
    assert match([record], [{"start": 10.4, "end": 42.4}], MODEL) == {}
    # And the same edges from another separation are another proposal.
    assert match([record], [HORN], "bsroformer_sw") == {}


def test_annotate_puts_each_record_on_its_span_and_counts_the_rest():
    taken = _decide((10.0, 42.0), origin=HORN)
    elsewhere = {**_decide((44.0, 72.0)), "start": 300.0, "end": 330.0}
    payload = {"model": MODEL, "spans": [dict(s) for s in SPANS]}
    out = gui_solos.annotate(payload, [taken, elsewhere, {"junk": True}])
    assert [s["record"] and s["record"]["action"] for s in out["spans"]] == [None, ACCEPTED, None]
    assert out["carried"] == 1  # the unmatched record is kept, and said so


def test_records_of_reads_only_well_formed_records():
    settings = {gui_solos.SIDECAR_KEY: [{"start": 1, "end": 2, "model": MODEL}, {"start": "x"}, 7]}
    assert gui_solos.records_of(settings) == [{"start": 1, "end": 2, "model": MODEL}]
    assert gui_solos.records_of({}) == []
    assert gui_solos.records_of({gui_solos.SIDECAR_KEY: "nonsense"}) == []


def test_levels_are_named_and_refuse_a_stranger():
    assert list(gui_solos.LEVELS) == ["fewer", "default", "more"]
    assert gui_solos.LEVELS["fewer"] > gui_solos.LEVELS["default"] > gui_solos.LEVELS["more"]
    with pytest.raises(ValueError):
        gui_solos.level_penalty("most")


# ── the job and the cache panel (CI) ─────────────────────────────────────────


def test_both_solos_stage_tables_sum_to_one():
    assert sum(share for _n, share in jobs.JOB_STAGES["solos"]) == pytest.approx(1.0)
    assert sum(share for _n, share in jobs.SOLOS_CACHED_STAGES) == pytest.approx(1.0)


def test_a_job_with_its_own_stage_weights_maps_progress_onto_them():
    from swingscribe.progress import ProgressEvent

    job = jobs.Job(id="x", path="a.wav", model=MODEL, kind="solos")
    job.stages = jobs.SOLOS_CACHED_STAGES
    runner = jobs.JobRunner()
    runner._on_progress(job, ProgressEvent("beats", 1.0))
    assert job.fraction == pytest.approx(0.40)
    runner._on_progress(job, ProgressEvent("envelopes", 0.5))
    assert job.fraction == pytest.approx(0.70)


def test_a_solos_job_that_need_not_separate_does_not_queue_behind_a_separation(tmp_path):
    runner = jobs.JobRunner()
    release = threading.Event()
    ran = threading.Event()
    runner._run_separation = lambda job, config, model: release.wait(5)
    runner._run_solos = lambda job, config, model: ran.set()
    try:
        runner.submit("a.wav", Config(cache_dir=tmp_path), "htdemucs", "separate")
        light = runner.submit("b.wav", Config(cache_dir=tmp_path), MODEL, "solos", heavy=False)
        assert ran.wait(3), "a cheap solos job waited on the separation"
        deadline = time.time() + 3
        while light.state != "done" and time.time() < deadline:
            time.sleep(0.02)
        assert light.state == "done"
    finally:
        release.set()


def test_a_solos_job_that_separates_takes_the_heavy_lane(tmp_path):
    runner = jobs.JobRunner()
    release = threading.Event()
    ran = threading.Event()
    runner._run_separation = lambda job, config, model: release.wait(5)
    runner._run_solos = lambda job, config, model: ran.set()
    try:
        runner.submit("a.wav", Config(cache_dir=tmp_path), "htdemucs", "separate")
        queued = runner.submit("b.wav", Config(cache_dir=tmp_path), MODEL, "solos", heavy=True)
        assert not ran.wait(0.3)
        assert queued.state == "queued"
    finally:
        release.set()
    assert ran.wait(5)


def test_the_cache_panel_will_not_delete_what_a_solos_job_is_writing():
    snapshots = [
        {"kind": "solos", "state": "running", "path": "C:/music/a.m4a", "model": MODEL},
        {"kind": "solos", "state": "done", "path": "C:/music/b.m4a", "model": MODEL},
        {"kind": "beats", "state": "running", "path": "C:/music/c.m4a", "model": MODEL},
    ]
    busy = storage.busy_targets(snapshots)
    assert len(busy) == 1
    assert next(iter(busy))[1] == MODEL


# ── stems and envelopes (numpy) ──────────────────────────────────────────────


RATE = 11025
BAR_S = 2.0  # 120 bpm in 4/4
BARS = 32


def _write_wav(path, samples, rate=RATE):
    np = pytest.importorskip("numpy")
    data = np.clip(samples, -1, 1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((data * 32767).astype("<i2").tobytes())


def _stems(folder, seed=0):
    """Sixteen bars of a horn in `other`, then sixteen of piano, over a
    steady bass and kit: the handover the proposer is built to hear. Each
    bar's melody note is drawn at random, so nothing repeats like a head."""
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(seed)
    n = int(RATE * BAR_S * BARS)
    t = np.arange(n) / RATE
    half = t < BAR_S * BARS / 2
    bar = np.minimum((t / BAR_S).astype(int), BARS - 1)
    pitch = 440.0 * 2.0 ** (rng.integers(-5, 8, size=BARS) / 12)
    phase = 2 * np.pi * np.cumsum(pitch[bar]) / RATE
    signals = {
        "bass": 0.3 * np.sin(2 * np.pi * 82 * t),
        "drums": 0.2 * rng.standard_normal(n) * (np.sin(2 * np.pi * 2 * t) > 0.9),
        "other": np.where(half, 0.5, 0.0) * np.sin(phase),
        "piano": np.where(half, 0.0, 0.4) * (np.sin(phase / 2) + 0.5 * np.sin(1.5 * phase)),
        "guitar": 0.001 * rng.standard_normal(n),
        "vocals": 0.001 * rng.standard_normal(n),
    }
    folder.mkdir(parents=True, exist_ok=True)
    for name, samples in signals.items():
        _write_wav(folder / f"{name}.wav", samples)
    return {name: str(folder / f"{name}.wav") for name in signals}


@pytest.fixture
def track(tmp_path):
    from swingscribe.model import AudioRef, Document
    from swingscribe.stages.separate import stems_dir

    pytest.importorskip("numpy", reason="ml dependency group not installed")
    gui_solos.clear_memo()
    normalized = tmp_path / "cache" / "audio" / "normalized.wav"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"pretend this is the normalized wav")
    config = Config(cache_dir=tmp_path / "cache")
    document = Document(
        audio_path=str(tmp_path / "tune.m4a"),
        sample_rate=RATE,
        audio=AudioRef(path=str(normalized), sample_rate=RATE, channels=1, duration=BAR_S * BARS),
    )
    from swingscribe.gui import library

    def folder(model=MODEL, span=None):
        return stems_dir(config.cache_dir, library.stem_digest(document), model, span)

    yield {"config": config, "document": document, "folder": folder}
    gui_solos.clear_memo()


def test_whole_file_set_prefers_the_quick_six_stem_set(track):
    config, document = track["config"], track["document"]
    assert gui_solos.whole_file_set(document, config) is None
    # A span set is silent outside its span: the proposer would find its edges.
    for name in SIX:
        path = track["folder"](MODEL, (10.0, 20.0))
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.wav").write_bytes(b"stem")
    assert gui_solos.whole_file_set(document, config) is None
    # A whole-file set missing its drums is not a set.
    partial = track["folder"]("bsroformer_sw")
    partial.mkdir(parents=True)
    (partial / "other.wav").write_bytes(b"stem")
    assert gui_solos.whole_file_set(document, config) is None
    for name in SIX:
        (partial / f"{name}.wav").write_bytes(b"stem")
    assert gui_solos.whole_file_set(document, config)[0] == "bsroformer_sw"
    six = track["folder"](MODEL)
    six.mkdir(parents=True)
    for name in SIX:
        (six / f"{name}.wav").write_bytes(b"stem")
    model, stems = gui_solos.whole_file_set(document, config)
    assert model == MODEL and sorted(stems) == sorted(SIX)


def test_envelopes_are_cached_beside_the_stems_and_miss_when_a_stem_changes(track):
    np = pytest.importorskip("numpy")
    stems = _stems(track["folder"]())
    seen = []
    env = gui_solos.build_envelopes(stems, report=lambda f, m: seen.append((f, m)))
    cache = gui_solos.envelope_path(stems)
    assert cache.parent == track["folder"]() and cache.name.startswith("_")
    assert seen[0][0] == 0.0 and seen[-1] == (1.0, "envelopes ready")
    back = gui_solos.cached_envelopes(stems)
    assert sorted(back.power) == sorted(SIX)
    assert sorted(back.chroma) == ["guitar", "other", "vocals"]
    for name in SIX:
        assert np.array_equal(back.power[name], env.power[name])
    # The stem listing the Stem menu reads is untouched by the cache file.
    from swingscribe.gui import library

    assert sorted(library.available_stems(track["document"], track["config"], MODEL)) == sorted(SIX)
    # A re-separation rewrites a stem: the fingerprint misses by itself.
    _write_wav(track["folder"]() / "piano.wav", np.zeros(RATE))
    gui_solos.clear_memo()
    assert gui_solos.cached_envelopes(stems) is None


def test_building_envelopes_stops_between_stems_when_cancelled(track):
    pytest.importorskip("numpy")
    stems = _stems(track["folder"]())
    with pytest.raises(jobs.JobCancelled):
        gui_solos.build_envelopes(stems, cancelled=lambda: True)
    assert not gui_solos.envelope_path(stems).exists()


def test_the_proposal_hears_the_handover_and_labels_both_sides(track):
    pytest.importorskip("numpy")
    from swingscribe.model import BeatGrid

    stems = _stems(track["folder"]())
    env = gui_solos.build_envelopes(stems)
    grid = BeatGrid(beats=[i * 0.5 for i in range(BARS * 4)], downbeats=[], beats_per_bar=4)
    lines = gui_solos.bar_line_times(grid, track["config"], BAR_S * BARS, {"anchor": 0.0})
    payload = gui_solos.propose(env, lines, MODEL, "default")
    assert payload["model"] == MODEL and payload["penalty"] == 4.0
    leads = [span["lead"] for span in payload["spans"]]
    assert leads[0] == "other" and leads[-1] == "piano"
    assert [b["time"] for b in payload["boundaries"]] == [pytest.approx(32.0)]
    assert sum(span["bars"] for span in payload["spans"]) == len(lines) - 1


def test_the_default_level_is_the_proposers_own_penalty():
    pytest.importorskip("numpy")
    from swingscribe import solo_spans

    assert gui_solos.LEVELS[gui_solos.DEFAULT_LEVEL] == solo_spans.PENALTY


def test_the_job_separates_only_when_no_whole_file_set_exists_then_reads(track, monkeypatch):
    pytest.importorskip("numpy")
    from swingscribe import pipeline
    from swingscribe.gui import library

    monkeypatch.setattr(pipeline, "run", lambda *a, **k: None)
    monkeypatch.setattr(library, "ingested_document", lambda path, cfg: track["document"])
    runner = jobs.JobRunner()
    separations = []

    def separate(job, config, model, started_at=None):
        separations.append((model, config.separate.span))
        _stems(track["folder"](model))

    runner._run_separation = separate
    job = runner.submit("tune.m4a", track["config"], MODEL, "solos", heavy=True)
    deadline = time.time() + 30
    while job.state in ("queued", "running") and time.time() < deadline:
        time.sleep(0.05)
    assert job.state == "done", job.error
    assert separations == [(MODEL, None)]  # the whole track, never a span
    assert job.result == {"model": MODEL}
    assert gui_solos.envelope_path(
        gui_solos.whole_file_set(track["document"], track["config"])[1]
    ).exists()

    again = runner.submit("tune.m4a", track["config"], MODEL, "solos", heavy=False)
    deadline = time.time() + 30
    while again.state in ("queued", "running") and time.time() < deadline:
        time.sleep(0.05)
    assert again.state == "done" and len(separations) == 1


# ── the routes (gui + numpy) ─────────────────────────────────────────────────


@pytest.fixture
def world(track, tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="gui dependency group not installed")
    from fastapi.testclient import TestClient

    from swingscribe import pipeline
    from swingscribe.gui import app as gui_app
    from swingscribe.gui import library
    from swingscribe.model import BeatGrid, Document

    music = tmp_path / "music"
    music.mkdir()
    source = music / "Some Tune.m4a"
    source.write_bytes(b"pretend this is an m4a")
    monkeypatch.setattr(library, "ingested_document", lambda path, cfg: track["document"])
    grid = {"value": None}

    def cached(path, config, stages):
        if grid["value"] is None:
            return None
        return Document(audio_path=str(path), sample_rate=RATE, beat_grid=grid["value"])

    monkeypatch.setattr(pipeline, "cached_document", cached)
    config = track["config"].model_copy(
        update={"gui": track["config"].gui.model_copy(update={"library_dir": str(music)})}
    )
    client = TestClient(gui_app.create_app(config))
    opened = client.post("/api/tracks/open", json={"path": str(source)}).json()

    def track_grid():
        grid["value"] = BeatGrid(
            beats=[i * 0.5 for i in range(BARS * 4)], downbeats=[], beats_per_bar=4
        )

    return {
        "client": client,
        "id": opened["id"],
        "source": source,
        "grid": track_grid,
        "stems": lambda: _stems(track["folder"]()),
    }


def test_solos_says_what_is_missing_and_what_separating_would_cost(world):
    answer = world["client"].get(f"/api/tracks/{world['id']}/solos").json()
    assert answer["ready"] is False
    assert answer["needs"] == ["beats", "separate", "envelopes"]
    assert answer["model"] == MODEL
    assert answer["audio_seconds"] == BAR_S * BARS
    assert answer["estimate_s"] > 0

    world["grid"]()
    world["stems"]()
    answer = world["client"].get(f"/api/tracks/{world['id']}/solos").json()
    # Stems on disk, envelopes not read yet: no separation, so no estimate.
    assert answer == {"ready": False, "needs": ["envelopes"], "model": MODEL, "level": "default"}


def test_solos_refuses_a_level_it_does_not_know(world):
    response = world["client"].get(f"/api/tracks/{world['id']}/solos", params={"level": "most"})
    assert response.status_code == 400


def _ready(world):
    world["grid"]()
    gui_solos.build_envelopes(world["stems"]())
    answer = world["client"].get(f"/api/tracks/{world['id']}/solos", params={"anchor": 0.0}).json()
    assert answer["ready"] is True, answer
    return answer


def test_solos_proposes_spans_and_never_writes_the_sidecar(world):
    sidecar = world["source"].with_name(world["source"].name + ".swingscribe.json")
    before = sidecar.read_text(encoding="utf-8") if sidecar.exists() else None
    answer = _ready(world)
    assert answer["model"] == MODEL and answer["level"] == "default"
    assert [s["lead"] for s in answer["spans"]][-1] == "piano"
    assert all(s["record"] is None for s in answer["spans"])
    assert answer["carried"] == 0
    after = sidecar.read_text(encoding="utf-8") if sidecar.exists() else None
    assert after == before
    # The fewer/more control only re-runs the arithmetic.
    fewer = (
        world["client"]
        .get(f"/api/tracks/{world['id']}/solos", params={"level": "fewer", "anchor": 0.0})
        .json()
    )
    assert fewer["ready"] is True and fewer["penalty"] == 6.0


def test_a_choice_is_recorded_in_the_sidecar_and_comes_back_on_its_span(world):
    answer = _ready(world)
    client, track_id = world["client"], world["id"]
    client.post(f"/api/tracks/{track_id}/state", json={"state": {"region": [1.0, 2.0]}})
    horn = answer["spans"][0]
    body = {
        "model": answer["model"],
        "level": answer["level"],
        "spans": [{k: s[k] for k in ("start", "end", "lead", "kind")} for s in answer["spans"]],
        "selection": [horn["start"], horn["end"] + 1.0],
        "origin": {k: horn[k] for k in ("start", "end", "lead", "kind")},
    }
    made = client.post(f"/api/tracks/{track_id}/solos/choice", json=body).json()["record"]
    assert made["action"] == ADJUSTED and made["moved"] == [0.0, 1.0]

    sidecar = world["source"].with_name(world["source"].name + ".swingscribe.json")
    stored = json.loads(sidecar.read_text(encoding="utf-8"))
    assert stored["region"] == [1.0, 2.0]  # the page's own keys are untouched
    assert stored[gui_solos.SIDECAR_KEY] == [made]
    # ... and the page's next state write leaves the record alone.
    client.post(f"/api/tracks/{track_id}/state", json={"state": {"region": [3.0, 4.0]}})
    stored = json.loads(sidecar.read_text(encoding="utf-8"))
    assert stored[gui_solos.SIDECAR_KEY] == [made]

    again = client.get(f"/api/tracks/{track_id}/solos", params={"anchor": 0.0}).json()
    assert again["spans"][0]["record"]["action"] == ADJUSTED
    assert all(s["record"] is None for s in again["spans"][1:])


def test_a_selection_about_no_proposal_writes_nothing(world):
    answer = _ready(world)
    body = {
        "model": answer["model"],
        "spans": [{"start": 10.0, "end": 20.0}],
        "selection": [40.0, 60.0],
    }
    made = world["client"].post(f"/api/tracks/{world['id']}/solos/choice", json=body).json()
    assert made == {"record": None}
    sidecar = world["source"].with_name(world["source"].name + ".swingscribe.json")
    stored = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    assert gui_solos.SIDECAR_KEY not in stored


def test_a_choice_refuses_an_empty_selection(world):
    body = {"model": MODEL, "spans": [], "selection": [5.0, 5.0]}
    response = world["client"].post(f"/api/tracks/{world['id']}/solos/choice", json=body)
    assert response.status_code == 400


def test_a_solos_job_names_the_set_it_will_read_and_what_it_will_cost(world):
    runner = world["client"].app.state.runner
    runner._run_solos = lambda job, config, model: None
    job = (
        world["client"]
        .post(
            "/api/jobs", json={"path": str(world["source"]), "model": "whatever", "kind": "solos"}
        )
        .json()
    )
    assert job["kind"] == "solos" and job["model"] == MODEL
    assert job["estimate"] > 0  # a whole-track separation is part of it

    world["stems"]()
    time.sleep(0.2)  # let the first (stubbed) job finish, or it dedupes
    job = (
        world["client"]
        .post("/api/jobs", json={"path": str(world["source"]), "model": MODEL, "kind": "solos"})
        .json()
    )
    assert job["estimate"] is None  # stems on disk: nothing to separate


def test_the_config_offers_the_levels_the_server_accepts(world):
    config = world["client"].get("/api/config").json()
    assert config["solo_levels"] == list(gui_solos.LEVELS)
    assert config["default_solo_level"] in config["solo_levels"]
    assert config["solo_separation_model"] == gui_solos.SEPARATION_MODEL


def test_the_bands_sit_on_the_steady_grid_like_the_roll():
    """A stretch the listener marked steady is the roll's grid too
    (meter.apply_steady), so the Overview's bands count bars on it."""
    from swingscribe.model import BeatGrid

    head = [round(i * 0.5, 6) for i in range(40)]
    t = head[-1]
    lock = [round(t + 0.1 + 0.75 * k, 6) for k in range(12)]  # a mark every 1.5 beats
    tail = [round(t + 9.0 + i * 0.5, 6) for i in range(40)]
    truth = head + [round(t + 0.5 * k, 6) for k in range(1, 18)] + tail
    config = Config()

    def lines(beats, steady=None):
        grid = BeatGrid(beats=beats, downbeats=[], beats_per_bar=4)
        return gui_solos.bar_line_times(grid, config, 50.0, {"anchor": 0.0}, None, steady)

    assert lines(head + lock + tail, [(t + 0.2, t + 8.8)]) == pytest.approx(lines(truth))
    assert lines(head + lock + tail) != pytest.approx(lines(truth))


def test_the_bands_sit_on_the_pinned_grid_like_the_roll():
    """Find the solos counts bars on the grid the roll draws, pins and all
    (meter.apply_pins): a slip the listener mended must not come back on the
    Overview's bands."""
    from swingscribe.model import BeatGrid

    truth = [round(i * 0.5, 6) for i in range(64)]
    slipped = [0.0, 0.667, 1.333] + truth[4:]  # four pulses tracked as three
    config = Config()
    lines = gui_solos.bar_line_times(
        BeatGrid(beats=slipped, downbeats=[], beats_per_bar=4), config, 32.0, {"anchor": 0.0}, [1.0]
    )
    right = gui_solos.bar_line_times(
        BeatGrid(beats=truth, downbeats=[], beats_per_bar=4), config, 32.0, {"anchor": 0.0}
    )
    unpinned = gui_solos.bar_line_times(
        BeatGrid(beats=slipped, downbeats=[], beats_per_bar=4), config, 32.0, {"anchor": 0.0}
    )
    assert lines == pytest.approx(right)
    assert unpinned != pytest.approx(right)
