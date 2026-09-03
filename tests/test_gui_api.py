"""The GUI's HTTP surface, driven through FastAPI's TestClient.

Everything here avoids running a real stage: ingest is stubbed so the API's own
behaviour is what's under test, not torchaudio's.
"""

import json
import pathlib
import time

import pytest

from swingscribe.config import Config
from swingscribe.model import AudioRef, Document, NoteEvent

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


def test_browse_defaults_to_library_dir(world):
    payload = world["client"].get("/api/browse").json()
    assert [f["name"] for f in payload["files"]] == ["Some Tune.m4a"]
    assert payload["parent"] is not None  # not a drive root


def test_browse_can_navigate_to_a_subfolder(world, tmp_path):
    sub = pathlib.Path(world["config"].gui.library_dir) / "solos"
    sub.mkdir()
    (sub / "take.wav").write_bytes(b"pretend audio")

    payload = world["client"].get("/api/browse", params={"path": str(sub)}).json()
    assert payload["path"] == str(sub.resolve())
    assert [f["name"] for f in payload["files"]] == ["take.wav"]
    assert payload["parent"] == str(sub.parent)


def test_browse_rejects_a_nonexistent_path(world, tmp_path):
    response = world["client"].get("/api/browse", params={"path": str(tmp_path / "nope")})
    assert response.status_code == 400


def test_browse_a_folder_then_open_a_file_found_there(world):
    """The realistic path: navigate somewhere new, then open what you found —
    matches the actual bug report (a file in an unlisted folder)."""
    payload = (
        world["client"].get("/api/browse", params={"path": str(world["source"].parent)}).json()
    )
    found = next(f for f in payload["files"] if f["name"] == "Some Tune.m4a")
    response = world["client"].post("/api/tracks/open", json={"path": found["path"]})
    assert response.status_code == 200, response.text


def test_open_returns_duration_and_model_readiness(world):
    track = open_track(world)
    assert track["duration"] == pytest.approx(6.0)
    assert track["name"] == "Some Tune.m4a"
    ready = {entry["model"]: entry["ready"] for entry in track["models"]}
    # Every offered model is reported, and only the one with stems on disk is
    # ready. Keyed off the config rather than a literal so that changing which
    # models are offered is a config decision, not a test rewrite.
    assert set(ready) == set(world["config"].gui.models)
    assert ready["htdemucs_ft"] is True
    assert all(v is False for k, v in ready.items() if k != "htdemucs_ft")


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
    # No separation in the chain. The grid is tracked from the mix, so asking
    # for it must never be a question that can only be answered by minutes of
    # demucs — and the answer no longer depends on `model` at all.
    assert seen["stages"] == ["ingest", "beats"]


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


def _seed_review(world, monkeypatch, *, stem="other", start=1.0, end=3.0, pitches=(64,)):
    """Populate the review cache for a span without running CREPE."""
    from dataclasses import dataclass

    from swingscribe.gui import library, review

    @dataclass
    class Diag:
        hop_s: float = 0.01
        start: float = 0.0
        f0_midi: list = None
        periodicity: list = None
        energy_ok: list = None
        pitch: list = None
        onsets: list = None

        @property
        def voiced_fraction(self):
            return 1.0

    from swingscribe.model import NoteEvent

    notes = [
        NoteEvent(
            onset=round(start + 0.1 + 0.5 * index, 3),
            duration=0.2,
            pitch=pitch,
            confidence=0.8,
            source=stem,
        )
        for index, pitch in enumerate(pitches)
    ]
    diag = Diag(
        start=start,
        f0_midi=[64.0, 64.0],
        periodicity=[0.9, 0.9],
        energy_ok=[True, True],
        pitch=[64.0, 64.0],
        onsets=[note.onset for note in notes],
    )
    monkeypatch.setattr("swingscribe.stages.transcribe.analyze", lambda sp, tc: (notes, diag))

    track = open_track(world)
    config = world["config"].model_copy(
        update={
            "transcribe": world["config"].transcribe.model_copy(
                update={"stem": stem, "region": (start, end)}
            )
        }
    )
    document = library.ingested_document(world["source"], config)
    review.analyze_and_cache(document, config, "htdemucs_ft")
    return track


def test_transcribe_job_requires_a_stem(world):
    response = world["client"].post(
        "/api/jobs",
        json={"path": str(world["source"]), "model": "htdemucs_ft", "kind": "transcribe"},
    )
    assert response.status_code == 400


def test_review_reports_not_ready_without_transcribing(world):
    track = open_track(world)
    payload = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/review",
            params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
        )
        .json()
    )
    assert payload == {"ready": False}


def test_review_serves_notes_and_frame_diagnostics(world, monkeypatch):
    track = _seed_review(world, monkeypatch)
    payload = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/review",
            params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
        )
        .json()
    )
    assert payload["ready"] is True
    assert payload["notes"][0]["pitch"] == 64
    diag = payload["diagnostics"]
    assert diag["frames"] == 2
    assert diag["energy_ok"] == [True, True]
    assert "onsets" in diag


def test_review_span_is_part_of_the_key(world, monkeypatch):
    """A review of 1-3s must not answer a request for 5-7s."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    other = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/review",
            params={"model": "htdemucs_ft", "stem": "other", "start": 5.0, "end": 7.0},
        )
        .json()
    )
    assert other == {"ready": False}


def test_transcription_wav_matches_the_span(world, monkeypatch):
    import io
    import wave

    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/transcription",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content)) as clip:
        assert clip.getnframes() / clip.getframerate() == pytest.approx(2.0, abs=0.05)


def test_transcription_of_an_untranscribed_span_is_404(world):
    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/transcription",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 404


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
    # The four demucs wrote, plus the sum the listener can ask for when the
    # separator has switched the soloist between two of them (library.py).
    assert payload["stems"] == ["bass", "drums", "other", "other+vocals", "vocals"]


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


def test_transcribe_job_and_review_agree_on_the_span(world, monkeypatch):
    """The end-to-end version of the precision bug: submit a job with unrounded
    float bounds, then fetch the review the way the client does."""
    from dataclasses import dataclass

    from swingscribe.model import NoteEvent

    @dataclass
    class Diag:
        hop_s: float = 0.01
        start: float = 1.0637
        f0_midi: list = None
        periodicity: list = None
        energy_ok: list = None
        pitch: list = None
        onsets: list = None

        @property
        def voiced_fraction(self):
            return 1.0

    notes = [NoteEvent(onset=1.2, duration=0.2, pitch=64, confidence=0.8, source="other")]
    diag = Diag(f0_midi=[64.0], periodicity=[0.9], energy_ok=[True], pitch=[64.0], onsets=[1.2])
    monkeypatch.setattr("swingscribe.stages.transcribe.analyze", lambda sp, tc: (notes, diag))

    track = open_track(world)
    # Job posted with full float precision, as the browser does.
    response = world["client"].post(
        "/api/jobs",
        json={
            "path": str(world["source"]),
            "model": "htdemucs_ft",
            "kind": "transcribe",
            "stem": "other",
            "start": 1.0637000000001,
            "end": 3.0912999999998,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["id"]
    for _ in range(200):
        state = world["client"].get(f"/api/jobs/{job_id}").json()
        if state["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert state["state"] == "done", state.get("error")

    # Review fetched the way the client builds params: rounded to 3 dp.
    payload = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/review",
            params={"model": "htdemucs_ft", "stem": "other", "start": "1.064", "end": "3.091"},
        )
        .json()
    )
    assert payload["ready"] is True
    assert payload["notes"][0]["pitch"] == 64


def test_the_sidecar_ensemble_reaches_the_transcribe_config(world, monkeypatch):
    """A GUI transcription of a piano solo must consult the same oracle the
    benchmark does, or the score you review is not the score that was
    measured. It rides in the sidecar because it is a judgement about the
    recording, like the span (M7b)."""
    from swingscribe.gui import review

    track = open_track(world)
    world["client"].post(f"/api/tracks/{track['id']}/state", json={"state": {"ensemble": "trio"}})

    seen = {}

    def capture(document, config, model):
        seen["ensemble"] = config.transcribe.ensemble
        return None

    monkeypatch.setattr(review, "cached_review", capture)
    world["client"].get(
        f"/api/tracks/{track['id']}/review",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert seen["ensemble"] == "trio"


def test_an_unknown_ensemble_in_the_sidecar_is_ignored(world, monkeypatch):
    """The sidecar is hand-editable. A typo there must fall back to the
    configured default rather than reaching pydantic as an invalid literal."""
    from swingscribe.gui import review

    track = open_track(world)
    world["client"].post(
        f"/api/tracks/{track['id']}/state", json={"state": {"ensemble": "banjo-led"}}
    )
    seen = {}

    def capture(document, config, model):
        seen["ensemble"] = config.transcribe.ensemble
        return None

    monkeypatch.setattr(review, "cached_review", capture)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/review", params={"model": "htdemucs_ft", "stem": "other"}
    )
    assert response.status_code == 200
    assert seen["ensemble"] == world["config"].transcribe.ensemble


# ── export ──────────────────────────────────────────────────────────────────


def _seed_beats(monkeypatch, world, step: float = 0.5, count: int = 13):
    """A cached beat grid, without running beat_this.

    The export endpoint never tracks beats itself — that is the Beats button's
    job — so what it needs is a cache hit, which is what this fakes.
    """
    from swingscribe.model import BeatGrid, Document

    def cached(path, config, stages):
        return Document(
            audio_path=str(path),
            sample_rate=world["rate"],
            beat_grid=BeatGrid(
                beats=[round(i * step, 6) for i in range(count)], downbeats=[], beats_per_bar=4
            ),
        )

    monkeypatch.setattr("swingscribe.pipeline.cached_document", cached)


def test_export_needs_a_transcription_first(world, monkeypatch):
    """409 with the fix in the message, not 500: the button is telling you
    which earlier button you still owe it."""
    _seed_beats(monkeypatch, world)
    track = open_track(world)
    response = world["client"].post(
        f"/api/tracks/{track['id']}/export",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 409
    assert "transcribe" in response.json()["detail"].lower()


def test_export_needs_a_beat_grid_first(world, monkeypatch):
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    monkeypatch.setattr("swingscribe.pipeline.cached_document", lambda p, c, stages: None)
    response = world["client"].post(
        f"/api/tracks/{track['id']}/export",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 409
    assert "beats" in response.json()["detail"].lower()


def test_export_writes_musicxml_beside_the_audio(world, monkeypatch):
    """Beside the audio, never in the cache: the cache is deletable derived
    data, and a score you have to dig out of it is a score you will not open."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    response = world["client"].post(
        f"/api/tracks/{track['id']}/export",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    written = pathlib.Path(payload["path"])
    assert written.parent == world["source"].parent
    assert written.suffix == ".musicxml"
    assert payload["bars"] >= 1
    assert "<score-partwise" in written.read_text(encoding="utf-8")


def test_the_span_is_in_the_filename(world, monkeypatch):
    """Exporting a second chorus must not overwrite the first."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    payload = (
        world["client"]
        .post(
            f"/api/tracks/{track['id']}/export",
            params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
        )
        .json()
    )
    assert "1-3s" in pathlib.Path(payload["path"]).name


def test_a_silenced_note_does_not_come_back_on_the_page(world, monkeypatch):
    """The score must hold exactly the notes the A/B render plays. An erasure
    that survives into the export is a note nobody asked for, in print."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0, pitches=(64, 67, 71))
    _seed_beats(monkeypatch, world)
    params = {"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0}
    before = world["client"].post(f"/api/tracks/{track['id']}/export", params=params).json()

    world["client"].post(
        f"/api/tracks/{track['id']}/state",
        json={"state": {"erasures": [{"onset": 1.6, "pitch": 67, "reason": "not-solo"}]}},
    )
    after = world["client"].post(f"/api/tracks/{track['id']}/export", params=params).json()
    assert after["notes"] == before["notes"] - 1
    # The erased note is gone from the page too, not merely from the count:
    # a G4 written where nobody asked for one is the whole failure mode.
    xml = pathlib.Path(after["path"]).read_text(encoding="utf-8")
    assert "<step>G</step>" not in xml


def test_export_says_so_when_every_note_is_silenced(world, monkeypatch):
    """Rather than writing an empty score and calling it a success."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    world["client"].post(
        f"/api/tracks/{track['id']}/state",
        json={"state": {"erasures": [{"onset": 1.1, "pitch": 64, "reason": "not-solo"}]}},
    )
    response = world["client"].post(
        f"/api/tracks/{track['id']}/export",
        params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
    )
    assert response.status_code == 409
    assert "silenced" in response.json()["detail"]


def test_transposition_comes_from_the_sidecar(world, monkeypatch):
    """Nothing in the audio says which horn it was, so it can only come from
    the listener — and the key signature has to move with it."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    world["client"].post(
        f"/api/tracks/{track['id']}/state", json={"state": {"transposition": "Bb-tenor"}}
    )
    payload = (
        world["client"]
        .post(
            f"/api/tracks/{track['id']}/export",
            params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
        )
        .json()
    )
    assert payload["transpose"] == 14
    xml = pathlib.Path(payload["path"]).read_text(encoding="utf-8")
    assert "<transpose>" in xml


def test_a_typo_in_the_sidecar_transposition_falls_back_to_concert(world, monkeypatch):
    """The sidecar is hand-editable; a bad value there must not break the
    button or reach pydantic as an invalid literal."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    world["client"].post(
        f"/api/tracks/{track['id']}/state", json={"state": {"transposition": "F-horn"}}
    )
    payload = (
        world["client"]
        .post(
            f"/api/tracks/{track['id']}/export",
            params={"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0},
        )
        .json()
    )
    assert payload["transpose"] == 0


def test_the_exported_score_can_be_downloaded_back(world, monkeypatch):
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    params = {"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0}
    missing = world["client"].get(f"/api/tracks/{track['id']}/export", params=params)
    assert missing.status_code == 404
    world["client"].post(f"/api/tracks/{track['id']}/export", params=params)
    response = world["client"].get(f"/api/tracks/{track['id']}/export", params=params)
    assert response.status_code == 200
    assert "<score-partwise" in response.text
    assert ".musicxml" in response.headers["content-disposition"]


def test_config_offers_exactly_what_the_validator_accepts(world):
    """The menus are built from this, so a hand-copied list here would drift
    and start offering values the server rejects."""
    from swingscribe.config import ENSEMBLES, TRANSPOSITIONS

    payload = world["client"].get("/api/config").json()
    assert payload["ensembles"] == list(ENSEMBLES)
    assert payload["transpositions"] == list(TRANSPOSITIONS)
    assert payload["default_ensemble"] in ENSEMBLES
    assert payload["default_transposition"] in TRANSPOSITIONS


def test_config_says_which_ensembles_consult_the_piano_model(world):
    """The routing, asked of the config rather than listed twice.

    The consequence of this choice is invisible on screen and expensive: a
    piano solo left on horn-led gets no second opinion, and the listener hit
    exactly that on a Sonny Clark solo. The UI shows it, so it has to be told
    -- and told by the same property `transcribe` branches on, or the label
    will go on saying "consulted" after the routing has moved.
    """
    from swingscribe.config import ENSEMBLES, TranscribeConfig

    payload = world["client"].get("/api/config").json()
    routed = payload["piano_oracle_ensembles"]
    assert set(routed) <= set(ENSEMBLES)
    for name in ENSEMBLES:
        expected = TranscribeConfig(ensemble=name).uses_piano_oracle
        assert (name in routed) is expected, name
    # The one that must never be in it, whatever else changes.
    assert "horn-led" not in routed


# ── scoring the notation against a hand transcription ───────────────────────


def _hand_transcription(tmp_path, pitches=(64, 67, 71)) -> pathlib.Path:
    """A one-bar .mscx holding these pitches as quarter notes.

    Written here rather than committed: the real benchmark scores are
    derivative works of commercial recordings and must never enter git.
    """
    chords = "".join(
        f"<Chord><durationType>quarter</durationType><Note><pitch>{p}</pitch></Note></Chord>"
        for p in pitches
    )
    path = tmp_path / "Hand Transcription.mscx"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<museScore version="4.70"><Score><Division>480</Division>'
        '<metaTag name="workTitle">Hand</metaTag><Staff><Measure><voice>'
        "<KeySig><concertKey>0</concertKey></KeySig>"
        "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
        f"{chords}</voice></Measure></Staff></Score></museScore>",
        encoding="utf-8",
    )
    return path


def test_notation_score_needs_a_transcription_first(world, monkeypatch, tmp_path):
    _seed_beats(monkeypatch, world)
    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/notation-score",
        params={
            "model": "htdemucs_ft",
            "stem": "other",
            "score": str(_hand_transcription(tmp_path)),
            "start": 1.0,
            "end": 3.0,
        },
    )
    assert response.status_code == 409


def test_notation_score_rejects_something_that_is_not_a_score(world, monkeypatch, tmp_path):
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0)
    _seed_beats(monkeypatch, world)
    not_a_score = tmp_path / "notes.txt"
    not_a_score.write_text("64 67 71", encoding="utf-8")
    response = world["client"].get(
        f"/api/tracks/{track['id']}/notation-score",
        params={
            "model": "htdemucs_ft",
            "stem": "other",
            "score": str(not_a_score),
            "start": 1.0,
            "end": 3.0,
        },
    )
    assert response.status_code == 400


def test_notation_score_reports_rhythm_and_value(world, monkeypatch, tmp_path):
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0, pitches=(64, 67, 71))
    _seed_beats(monkeypatch, world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/notation-score",
        params={
            "model": "htdemucs_ft",
            "stem": "other",
            "score": str(_hand_transcription(tmp_path)),
            "start": 1.0,
            "end": 3.0,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert 0.0 <= payload["rhythm"] <= 1.0
    assert 0.0 <= payload["value"] <= 1.0
    assert payload["matched"] == 3
    assert payload["reference"] == 3
    assert payload["coverage"] == 1.0
    assert payload["trusted"] is True
    assert payload["score"] == "Hand Transcription.mscx"


def test_a_score_that_barely_lines_up_is_marked_untrusted(world, monkeypatch, tmp_path):
    """Rhythm against the wrong tune reads as high as 0.58, so the number must
    never travel without what it rests on (benchmark.COVERAGE_FLOOR)."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0, pitches=(64, 67, 71))
    _seed_beats(monkeypatch, world)
    # Twenty notated notes against our three: most of their score is unaccounted for.
    wrong = _hand_transcription(tmp_path, pitches=tuple(40 + (i * 5) % 30 for i in range(20)))
    payload = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/notation-score",
            params={
                "model": "htdemucs_ft",
                "stem": "other",
                "score": str(wrong),
                "start": 1.0,
                "end": 3.0,
            },
        )
        .json()
    )
    assert payload["trusted"] is False
    assert payload["coverage"] < 0.5


def test_export_and_score_notate_the_same_thing(world, monkeypatch, tmp_path):
    """Scoring a different Notation from the one written to disk would be a
    number about nothing, so both go through build_notation."""
    track = _seed_review(world, monkeypatch, start=1.0, end=3.0, pitches=(64, 67, 71))
    _seed_beats(monkeypatch, world)
    params = {"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0}
    exported = world["client"].post(f"/api/tracks/{track['id']}/export", params=params).json()
    scored = (
        world["client"]
        .get(
            f"/api/tracks/{track['id']}/notation-score",
            params={**params, "score": str(_hand_transcription(tmp_path))},
        )
        .json()
    )
    assert scored["bars"] == exported["bars"]


def test_the_review_payload_carries_the_second_voice_separately(tmp_path, monkeypatch):
    """It must never arrive as extra entries in `notes`: everything that
    scores, exports or erases treats `notes` as the transcription."""
    from swingscribe.gui import review

    class Diag:
        hop_s = 0.01
        start = 0.0
        f0_midi = [60.0]
        periodicity = [0.9]
        energy_ok = [True]
        pitch = [60.0]
        onsets = [0.0]
        second_voice = [{"onset": 1.0, "duration": 0.2, "pitch": 64, "velocity": 80}]
        voiced_fraction = 1.0

    notes = [NoteEvent(onset=1.0, duration=0.2, pitch=72, confidence=0.9, source="other")]
    payload = review._payload(notes, Diag())
    assert [n["pitch"] for n in payload["notes"]] == [72]
    assert [n["pitch"] for n in payload["second_voice"]] == [64]


def test_a_payload_without_a_second_voice_still_has_the_key(tmp_path):
    """The client reads it unconditionally; a missing key would be a crash on
    every horn track."""
    from swingscribe.gui import review

    class Diag:
        hop_s = 0.01
        start = 0.0
        f0_midi = [60.0]
        periodicity = [0.9]
        energy_ok = [True]
        pitch = [60.0]
        onsets = [0.0]
        voiced_fraction = 1.0

    payload = review._payload([], Diag())
    assert payload["second_voice"] == []


def test_the_line_choice_reaches_the_transcribe_config_and_its_key(world, monkeypatch):
    """`line=oracle` asks for the line picked from the piano model (issue
    #8). It changes every note, so it must reach the config the review is
    keyed on — and the default must key exactly as it did before the choice
    existed, or every open review becomes a miss."""
    from swingscribe.gui import review

    track = open_track(world)
    world["client"].post(f"/api/tracks/{track['id']}/state", json={"state": {"ensemble": "trio"}})
    seen = []

    def capture(document, config, model):
        seen.append((config.transcribe.piano_line, review.review_key(document, config, model)))
        return None

    monkeypatch.setattr(review, "cached_review", capture)
    base = {"model": "htdemucs_ft", "stem": "other", "start": 1.0, "end": 3.0}
    world["client"].get(f"/api/tracks/{track['id']}/review", params=base)
    world["client"].get(f"/api/tracks/{track['id']}/review", params={**base, "line": "crepe"})
    world["client"].get(f"/api/tracks/{track['id']}/review", params={**base, "line": "oracle"})

    assert [line for line, _ in seen] == ["crepe", "crepe", "oracle"]
    assert seen[0][1] == seen[1][1]  # naming the default is the default
    assert seen[2][1] != seen[0][1]  # the other take is another review


def test_an_unknown_line_is_refused(world):
    track = open_track(world)
    response = world["client"].get(
        f"/api/tracks/{track['id']}/review",
        params={"model": "htdemucs_ft", "stem": "other", "line": "theremin"},
    )
    assert response.status_code == 400
    assert "crepe" in response.json()["detail"]


def test_the_config_offers_the_line_choices(world):
    from swingscribe.config import LINES

    payload = world["client"].get("/api/config").json()
    assert payload["lines"] == list(LINES)
    assert payload["default_line"] == "crepe"


def test_a_transcribe_job_carries_the_line_choice(world, monkeypatch):
    """The job and the review GET must agree on the key, or the job's work
    is never found: a job run for the oracle line answers a review asked
    for the oracle line, and not the one asked for CREPE's."""
    from dataclasses import dataclass

    from swingscribe.model import NoteEvent

    @dataclass
    class Diag:
        hop_s: float = 0.01
        start: float = 1.0
        f0_midi: list = None
        periodicity: list = None
        energy_ok: list = None
        pitch: list = None
        onsets: list = None

        @property
        def voiced_fraction(self):
            return 1.0

    seen = {}

    def analyze(stem_path, tc):
        seen["line"] = tc.piano_line
        notes = [NoteEvent(onset=1.2, duration=0.2, pitch=64, confidence=0.8, source="other")]
        return notes, Diag(
            f0_midi=[64.0], periodicity=[0.9], energy_ok=[True], pitch=[64.0], onsets=[]
        )

    monkeypatch.setattr("swingscribe.stages.transcribe.analyze", analyze)
    track = open_track(world)
    world["client"].post(f"/api/tracks/{track['id']}/state", json={"state": {"ensemble": "trio"}})
    response = world["client"].post(
        "/api/jobs",
        json={
            "path": str(world["source"]),
            "model": "htdemucs_ft",
            "kind": "transcribe",
            "stem": "other",
            "start": 1.0,
            "end": 3.0,
            "line": "oracle",
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    for _ in range(200):
        state = world["client"].get(f"/api/jobs/{job_id}").json()
        if state["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert state["state"] == "done", state.get("error")
    assert seen["line"] == "oracle"

    base = {"model": "htdemucs_ft", "stem": "other", "start": "1.000", "end": "3.000"}
    asked = world["client"].get(
        f"/api/tracks/{track['id']}/review", params={**base, "line": "oracle"}
    )
    other = world["client"].get(f"/api/tracks/{track['id']}/review", params=base)
    assert asked.json()["ready"] is True
    assert other.json()["ready"] is False
