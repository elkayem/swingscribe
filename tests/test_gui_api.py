"""The GUI's HTTP surface, driven through FastAPI's TestClient.

Everything here avoids running a real stage: ingest is stubbed so the API's own
behaviour is what's under test, not torchaudio's.
"""

import json
import pathlib

import pytest

from swingscribe.config import Config
from swingscribe.model import AudioRef, Document

pytest.importorskip("fastapi", reason="gui dependency group not installed")
soundfile = pytest.importorskip("soundfile", reason="ml dependency group not installed")
np = pytest.importorskip("numpy", reason="ml dependency group not installed")

from fastapi.testclient import TestClient  # noqa: E402

from swingscribe.gui import app as gui_app  # noqa: E402
from swingscribe.gui import library  # noqa: E402
from swingscribe.stages.separate import stems_dir  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A track that looks ingested and separated, without running either."""
    music = tmp_path / "music"
    music.mkdir()
    source = music / "Some Tune.m4a"
    source.write_bytes(b"pretend this is an m4a")

    rate = 8000
    tone = (0.4 * np.sin(2 * np.pi * 220 * np.arange(rate * 6) / rate)).astype("float32")
    normalized = tmp_path / "cache" / "audio" / "normalized.wav"
    normalized.parent.mkdir(parents=True)
    soundfile.write(str(normalized), np.stack([tone, tone], axis=1), rate)

    config = Config(cache_dir=tmp_path / "cache", gui={"library_dir": str(music)})
    document = Document(
        audio_path=str(source),
        sample_rate=rate,
        audio=AudioRef(path=str(normalized), sample_rate=rate, channels=2, duration=6.0),
    )
    monkeypatch.setattr(library, "ingested_document", lambda path, cfg: document)

    stem_dir = stems_dir(config.cache_dir, library.file_digest(normalized), "htdemucs_ft")
    stem_dir.mkdir(parents=True)
    for name in ("drums", "bass", "other", "vocals"):
        soundfile.write(str(stem_dir / f"{name}.wav"), np.stack([tone, tone], axis=1), rate)

    client = TestClient(gui_app.create_app(config))
    return {"client": client, "source": source, "config": config, "rate": rate}


def open_track(world):
    response = world["client"].post("/api/tracks/open", json={"path": str(world["source"])})
    assert response.status_code == 200, response.text
    return response.json()


def test_index_and_static_are_served(world):
    client = world["client"]
    assert "SwingScribe" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_stylesheet_makes_the_hidden_attribute_win(world):
    """The UI shows and hides panels with the `hidden` attribute, but the
    browser's `[hidden] { display: none }` is a user-agent rule that any author
    `display` overrides. Several containers here set display: flex/grid, so
    without an explicit override the track picker stays on screen forever while
    element.hidden cheerfully reports true."""
    import re

    # Comments are stripped first: the rule is explained in a comment that
    # itself quotes "[hidden] { display: none }", which a naive search matches.
    css = re.sub(r"/\*.*?\*/", "", world["client"].get("/static/style.css").text, flags=re.S)
    match = re.search(r"\[hidden\]\s*\{([^}]*)\}", css)
    assert match, "style.css must override the user-agent [hidden] rule"
    assert "display: none !important" in match.group(1)

    html = world["client"].get("/").text
    assert " hidden" in html  # the pattern this rule exists to support


def test_config_endpoint_reports_the_model_menu(world):
    payload = world["client"].get("/api/config").json()
    assert payload["models"] == world["config"].gui.models
    assert payload["library_dir"].endswith("music")


def test_tracks_lists_the_library(world):
    payload = world["client"].get("/api/tracks").json()
    assert [entry["name"] for entry in payload["library"]] == ["Some Tune.m4a"]
    assert payload["recent"] == []


def test_open_returns_duration_and_model_readiness(world):
    track = open_track(world)
    assert track["duration"] == pytest.approx(6.0)
    assert track["name"] == "Some Tune.m4a"
    ready = {entry["model"]: entry["ready"] for entry in track["models"]}
    assert ready == {"htdemucs_ft": True, "htdemucs_6s": False}


def test_open_rejects_a_missing_file(world):
    response = world["client"].post("/api/tracks/open", json={"path": "nope.wav"})
    assert response.status_code == 404


def test_open_rejects_a_non_audio_file(world, tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("not audio", encoding="utf-8")
    response = world["client"].post("/api/tracks/open", json={"path": str(text)})
    assert response.status_code == 400


def test_opening_a_track_makes_it_recent(world):
    open_track(world)
    recent = world["client"].get("/api/tracks").json()["recent"]
    assert [entry["name"] for entry in recent] == ["Some Tune.m4a"]


def test_overview_peaks_cover_the_whole_track(world):
    track = open_track(world)
    data = world["client"].get(f"/api/tracks/{track['id']}/peaks").json()
    assert data["duration"] == pytest.approx(6.0)
    assert len(data["peaks"]) == 2
    assert len(data["peaks"][0]) > 100


def test_window_peaks_report_the_range_they_cover(world):
    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/peaks", params={"start": 1.0, "end": 3.0, "buckets": 200}
    )
    data = response.json()
    assert (data["start"], data["end"]) == (pytest.approx(1.0), pytest.approx(3.0))
    assert len(data["peaks"][0]) == 200


def test_stem_peaks_need_a_separated_stem(world):
    track = open_track(world)
    ok = world["client"].get(
        f"/api/tracks/{track['id']}/peaks",
        params={"start": 0, "end": 2, "stem": "other", "model": "htdemucs_ft"},
    )
    assert ok.status_code == 200
    missing = world["client"].get(
        f"/api/tracks/{track['id']}/peaks",
        params={"start": 0, "end": 2, "stem": "guitar", "model": "htdemucs_ft"},
    )
    assert missing.status_code == 404


def test_audio_endpoint_supports_range_requests(world):
    """Seeking in a five-minute file depends on this; without it the browser
    refetches the whole wav on every click."""
    track = open_track(world)
    url = f"/api/tracks/{track['id']}/audio"
    assert world["client"].get(url).headers["accept-ranges"] == "bytes"
    partial = world["client"].get(url, headers={"Range": "bytes=0-1023"})
    assert partial.status_code == 206
    assert len(partial.content) == 1024


def test_stem_slice_returns_the_requested_span(world):
    import io

    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/stem",
        params={"stem": "other", "model": "htdemucs_ft", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data, rate = soundfile.read(io.BytesIO(response.content), always_2d=True)
    assert data.shape[0] == pytest.approx(2.0 * world["rate"], abs=2)


def test_mix_is_sliced_by_the_same_endpoint(world):
    """The A/B reference goes through the identical code path as the stems, so
    it is guaranteed to line up with them sample for sample."""
    import io

    track = open_track(world)
    stem, mix = (
        world["client"].get(
            f"/api/tracks/{track['id']}/stem",
            params={"stem": name, "model": "htdemucs_ft", "start": 0.5, "end": 2.5},
        )
        for name in ("other", "mix")
    )
    lengths = {
        soundfile.read(io.BytesIO(response.content), always_2d=True)[0].shape[0]
        for response in (stem, mix)
    }
    assert len(lengths) == 1


def test_stem_slice_names_what_is_available_when_it_is_not(world):
    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/stem",
        params={"stem": "piano", "model": "htdemucs_ft", "start": 0, "end": 1},
    )
    assert response.status_code == 404
    assert "other" in response.json()["detail"]  # tells you what you can pick


def test_download_sets_a_filename(world):
    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/stem",
        params={
            "stem": "other",
            "model": "htdemucs_ft",
            "start": 1.0,
            "end": 2.0,
            "download": True,
        },
    )
    assert "attachment" in response.headers["content-disposition"]
    assert "Some Tune.other" in response.headers["content-disposition"]


def test_state_is_remembered_across_opens(world):
    track = open_track(world)
    world["client"].post(
        f"/api/tracks/{track['id']}/state",
        json={"state": {"region": [12.5, 44.25], "stem": "other", "model": "htdemucs_ft"}},
    )
    reopened = open_track(world)
    assert reopened["state"]["region"] == [12.5, 44.25]
    assert reopened["state"]["stem"] == "other"


def test_unknown_track_is_recovered_from_its_sidecar(world):
    """A page reload after the server restarts must not dead-end."""
    track = open_track(world)
    fresh = TestClient(gui_app.create_app(world["config"]))  # empty in-memory registry
    assert fresh.get(f"/api/tracks/{track['id']}/peaks").status_code == 200


def test_unknown_track_with_no_sidecar_is_a_404(world):
    assert world["client"].get("/api/tracks/deadbeefdeadbeef/peaks").status_code == 404


def test_beats_endpoint_reports_not_ready_without_computing(world):
    """No cached grid exists in this fixture; the endpoint must say so rather
    than block the request on minutes of beat tracking."""
    track = open_track(world)
    payload = world["client"].get(f"/api/tracks/{track['id']}/beats").json()
    assert payload == {"ready": False}


def test_beats_endpoint_derives_bars_from_a_cached_grid(world, monkeypatch):
    """Bar lines come from counting beats, not from the tracker's downbeat
    layer — which is why a deliberately misleading downbeat list still yields a
    clean grid."""
    from swingscribe import pipeline
    from swingscribe.model import BeatGrid

    track = open_track(world)
    beats = [round(i * 0.5, 3) for i in range(64)]
    grid = BeatGrid(beats=beats, downbeats=[0.5, 1.5, 2.0], beats_per_bar=2)
    document = Document(audio_path="x", sample_rate=8000, beat_grid=grid)
    seen = {}

    def fake_cached(path, config, stages):
        seen["model"] = config.separate.model
        seen["stages"] = [name for name, _stage in stages]
        return document

    monkeypatch.setattr(pipeline, "cached_document", fake_cached)
    payload = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/beats",
            params={"model": "htdemucs_6s", "time_signature": "4/4", "anchor": 0.0},
        )
        .json()
    )

    assert payload["ready"] is True
    assert payload["time_signature"] == "4/4"
    assert payload["pulses_per_bar"] == 4
    assert payload["bpm"] == pytest.approx(120.0)
    # A bar every four beats, numbered from one.
    assert [t for t, _n in payload["bars"]][:3] == pytest.approx([0.0, 2.0, 4.0])
    assert [n for _t, n in payload["bars"]][:3] == [1, 2, 3]
    assert seen["model"] == "htdemucs_6s"
    assert seen["stages"] == ["ingest", "separate", "beats"]


def test_beats_endpoint_rephases_on_a_new_anchor(world, monkeypatch):
    """The downbeat click must be a redraw, not a re-analysis: same request,
    one parameter different, every bar line moved."""
    from swingscribe import pipeline
    from swingscribe.model import BeatGrid

    track = open_track(world)
    grid = BeatGrid(beats=[round(i * 0.5, 3) for i in range(64)], downbeats=[], beats_per_bar=4)
    monkeypatch.setattr(
        pipeline,
        "cached_document",
        lambda path, config, stages: Document(audio_path="x", sample_rate=8000, beat_grid=grid),
    )
    url = f"/api/tracks/{track['id']}/beats"
    first = world["client"].get(url, params={"anchor": 0.0}).json()
    moved = world["client"].get(url, params={"anchor": 0.5}).json()
    assert [t for t, _ in moved["bars"]][:3] == pytest.approx([0.5, 2.5, 4.5])
    assert len(first["bars"]) == len(moved["bars"])


def test_beats_endpoint_marks_beats_it_had_to_invent(world, monkeypatch):
    """Implied beats are flagged so the UI can draw them as guesses rather than
    letting the software's inference pass for detection."""
    from swingscribe import pipeline
    from swingscribe.model import BeatGrid

    track = open_track(world)
    times = [round(i * 0.5, 3) for i in range(64)]
    del times[30]
    grid = BeatGrid(beats=times, downbeats=[], beats_per_bar=4)
    monkeypatch.setattr(
        pipeline,
        "cached_document",
        lambda path, config, stages: Document(audio_path="x", sample_rate=8000, beat_grid=grid),
    )
    payload = world["client"].get(f"/api/tracks/{track['id']}/beats").json()
    assert sum(1 for flag in payload["implied"] if flag) == 1
    assert len(payload["implied"]) == len(payload["beats"]) == 64


def test_beats_endpoint_rejects_a_nonsense_time_signature(world, monkeypatch):
    from swingscribe import pipeline
    from swingscribe.model import BeatGrid

    track = open_track(world)
    monkeypatch.setattr(
        pipeline,
        "cached_document",
        lambda path, config, stages: Document(
            audio_path="x",
            sample_rate=8000,
            beat_grid=BeatGrid(beats=[0.0, 0.5], downbeats=[], beats_per_bar=4),
        ),
    )
    response = world["client"].get(
        f"/api/tracks/{track['id']}/beats", params={"time_signature": "banana"}
    )
    assert response.status_code == 400


def test_job_rejects_an_unknown_kind(world):
    response = world["client"].post(
        "/api/jobs",
        json={"path": str(world["source"]), "model": "htdemucs_ft", "kind": "transmogrify"},
    )
    assert response.status_code == 400


def test_job_rejects_a_model_outside_the_menu(world):
    response = world["client"].post(
        "/api/jobs", json={"path": str(world["source"]), "model": "not_a_model"}
    )
    assert response.status_code == 400


def test_stems_endpoint_lists_one_model(world):
    track = open_track(world)
    payload = (
        world["client"]
        .get(f"/api/tracks/{track['id']}/stems", params={"model": "htdemucs_ft"})
        .json()
    )
    assert payload["stems"] == ["bass", "drums", "other", "vocals"]


def test_settings_are_written_beside_the_audio(world):
    """Not under the cache: clearing derived data must never cost the user a
    span, a stem choice or a downbeat they had to listen to find."""
    track = open_track(world)
    response = world["client"].post(
        f"/api/tracks/{track['id']}/state",
        json={"state": {"region": [1.0, 2.0], "stem": "other"}},
    )
    assert response.status_code == 200
    written = pathlib.Path(response.json()["settings_path"])
    assert written == world["source"].with_name(world["source"].name + ".swingscribe.json")
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["stem"] == "other"


def test_open_reports_where_settings_live(world):
    track = open_track(world)
    assert track["settings_path"].endswith(".swingscribe.json")
