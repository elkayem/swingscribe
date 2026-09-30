"""The ensemble suggestion beside the Ensemble menu (roadmap O2).

`gui/suggestion.py` is an adapter over `routing`: these tests hold it to
passing the routing's answer through UNCHANGED -- never a trio the rule did
not make -- and to refusing a stem set the rule's guards cannot read (a
partial set has no bass or drums to tell a lead from a comp). The first half
runs in CI with the levels stubbed; the route tests at the bottom write real
wavs and need the gui and ml groups.
"""

import json
import os

import pytest

from swingscribe import routing
from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.gui import suggestion as gui_suggestion
from swingscribe.model import AudioRef, Document
from swingscribe.routing import StemLevels
from swingscribe.stages.separate import stems_dir

ROFORMER = "bsroformer_sw"
SIX = ("drums", "bass", "other", "vocals", "guitar", "piano")


@pytest.fixture(autouse=True)
def fresh_memo():
    gui_suggestion.clear_memo()
    yield
    gui_suggestion.clear_memo()


@pytest.fixture
def track(tmp_path):
    """A document whose normalized wav exists (its digest names the stems
    directory) and a function that fills a stem set with placeholder files."""
    normalized = tmp_path / "cache" / "audio" / "normalized.wav"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"pretend this is the normalized wav")
    config = Config(cache_dir=tmp_path / "cache")
    document = Document(
        audio_path=str(tmp_path / "tune.m4a"),
        sample_rate=8000,
        audio=AudioRef(path=str(normalized), sample_rate=8000, channels=2, duration=300.0),
    )

    def separate(model=ROFORMER, names=SIX):
        folder = stems_dir(config.cache_dir, library.stem_digest(document), model)
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / f"{name}.wav").write_bytes(b"placeholder stem")
        return folder

    return {"config": config, "document": document, "separate": separate}


def stub_levels(monkeypatch, levels):
    """Replace the wav reader: every measurement returns `levels`, and the
    list returned records each (stems, span) it was asked about."""
    calls = []

    def measure(stems, region=None, window_s=routing.WINDOW_S):
        calls.append((dict(stems), region))
        return levels

    monkeypatch.setattr(gui_suggestion.routing, "measure", measure)
    return calls


def band(share, piano, other, bass=-26.0, drums=-32.0, active_s=60.0):
    db = {
        "other": other,
        "piano": piano,
        "bass": bass,
        "drums": drums,
        "guitar": -110.0,
        "vocals": -115.0,
    }
    lead = {"other": 1.0 - share, "piano": share, "guitar": 0.0, "vocals": 0.0}
    return StemLevels(db, lead, active_s, active_s)


PIANO_SOLO = band(1.0, piano=-18.0, other=-50.0)
HORN_SOLO = band(0.1, piano=-40.0, other=-16.0)
# Chet Baker, There Will Never Be Another You (solo 75): the horn span
# nearest the piano side on the benchmark's Roformer stems (docs/routing.md).
WORST_HORN = band(0.548, piano=-20.0, other=-20.4)
UNSURE = band(0.75, piano=-20.0, other=-24.0)


def ask(track, model=ROFORMER, span=(10.0, 85.0)):
    return gui_suggestion.suggestion(track["document"], track["config"], model, span)


# --- what reaches the page is the routing's answer, unchanged ---------------


@pytest.mark.parametrize(
    "levels, model",
    [
        (PIANO_SOLO, ROFORMER),
        (HORN_SOLO, ROFORMER),
        (WORST_HORN, ROFORMER),
        (UNSURE, ROFORMER),
        (HORN_SOLO, "htdemucs_6s"),
        (PIANO_SOLO, "htdemucs_6s"),
    ],
)
def test_the_suggestion_is_routing_suggest_verbatim(track, monkeypatch, levels, model):
    track["separate"](model)
    stub_levels(monkeypatch, levels)
    expected = routing.suggest(levels, model)
    got = ask(track, model)
    assert got["measured"] is True
    assert (got["ensemble"], got["stem"], got["reason"]) == (
        expected.ensemble,
        expected.stem,
        expected.reason,
    )
    assert got["confidence"] == pytest.approx(expected.confidence, abs=1e-3)


def test_a_piano_solo_is_offered_trio_on_the_piano_stem(track, monkeypatch):
    track["separate"]()
    stub_levels(monkeypatch, PIANO_SOLO)
    got = ask(track)
    assert (got["ensemble"], got["stem"]) == ("trio", "piano")
    assert "piano model" in got["reason"]


def test_the_worst_horn_span_is_never_offered_a_piano_ensemble(track, monkeypatch):
    """The one error that costs a whole line: a horn sent to the piano model."""
    track["separate"]()
    stub_levels(monkeypatch, WORST_HORN)
    got = ask(track)
    assert got["ensemble"] == "horn-led"
    assert got["stem"] == "other"


def test_the_horn_call_follows_the_separator(track, monkeypatch):
    """htdemucs_6s files piano solos under `guitar`, so a quiet piano stem
    there proves nothing: the model must reach the rule."""
    track["separate"]("htdemucs_6s")
    stub_levels(monkeypatch, HORN_SOLO)
    got = ask(track, "htdemucs_6s")
    assert got["measured"] is True
    assert got["ensemble"] is None
    assert "bsroformer_sw" in got["reason"]


def test_a_four_stem_separation_says_it_has_no_piano_stem(track, monkeypatch):
    """htdemucs writes four stems and no `piano`: the set is whole for its
    model, so it is read, and the rule itself says why it cannot judge --
    never a horn-led call made by a set that cannot hold a piano solo."""
    four = ("drums", "bass", "other", "vocals")
    track["separate"]("htdemucs", names=four)
    levels = StemLevels(
        {"drums": -30.0, "bass": -25.0, "other": -16.0, "vocals": -40.0},
        {"other": 0.9, "vocals": 0.1},
        60.0,
        60.0,
    )
    calls = stub_levels(monkeypatch, levels)
    got = ask(track, "htdemucs")
    assert got["measured"] is True
    assert set(calls[0][0]) == set(four)
    assert got["ensemble"] is None and got["stem"] is None
    assert "no piano stem" in got["reason"]


def test_unsure_is_no_suggestion_with_a_reason(track, monkeypatch):
    track["separate"]()
    stub_levels(monkeypatch, UNSURE)
    got = ask(track)
    assert got["ensemble"] is None and got["stem"] is None
    assert got["reason"].startswith("No suggestion")


# --- what is refused before anything is read --------------------------------


def test_no_stems_is_not_measured(track, monkeypatch):
    calls = stub_levels(monkeypatch, PIANO_SOLO)
    got = ask(track)
    assert got["measured"] is False
    assert got["ensemble"] is None
    assert "Separate" in got["reason"]
    assert calls == []


def test_a_partial_set_is_refused_even_when_the_piano_would_pass(track, monkeypatch):
    """A lone copied stem is a legitimate cache state (CLAUDE.md), but with
    no bass or drums the lead guard reads nothing: a piano comping under a
    bass solo would be the loudest stem present."""
    track["separate"](names=("piano", "other"))
    calls = stub_levels(monkeypatch, PIANO_SOLO)
    got = ask(track)
    assert got["measured"] is False
    assert got["ensemble"] is None
    for name in ("drums", "bass", "vocals", "guitar"):
        assert name in got["reason"]
    assert calls == []


def test_an_unknown_model_must_hold_every_stem_the_rule_reads(track, monkeypatch):
    """`separate.missing_stems` calls an unknown model's set complete; the
    suggestion does not."""
    track["separate"]("some_new_model", names=("piano", "other"))
    calls = stub_levels(monkeypatch, PIANO_SOLO)
    got = ask(track, "some_new_model")
    assert got["measured"] is False
    assert calls == []


def test_a_summed_stem_on_disk_is_handed_over_and_left_to_the_rule(track, monkeypatch):
    """`other+vocals.wav` is written beside the stems it sums. The adapter
    passes everything; `routing.measure` is what drops the sum."""
    folder = track["separate"]()
    (folder / "other+vocals.wav").write_bytes(b"placeholder sum")
    calls = stub_levels(monkeypatch, PIANO_SOLO)
    ask(track)
    assert set(calls[0][0]) == {*SIX, "other+vocals"}


# --- the memo -----------------------------------------------------------------


def test_levels_are_read_once_per_span_and_stem_set(track, monkeypatch):
    folder = track["separate"]()
    calls = stub_levels(monkeypatch, PIANO_SOLO)
    ask(track, span=(10.0, 85.0))
    ask(track, span=(10.0004, 84.9996))  # the same span to the millisecond
    assert len(calls) == 1
    assert calls[0][1] == (10.0, 85.0)
    ask(track, span=(12.0, 85.0))
    assert len(calls) == 2
    # A re-separated stem is a new file: the memo must not answer for it.
    piano = folder / "piano.wav"
    piano.write_bytes(b"a different, longer placeholder stem")
    stat = piano.stat()
    os.utime(piano, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    ask(track, span=(12.0, 85.0))
    assert len(calls) == 3


# --- JSON ---------------------------------------------------------------------


def test_the_payload_is_strict_json():
    """A margin over no rival stem is infinite; JSON has no infinity, and
    Starlette refuses to encode one."""
    hint = routing.Suggestion(
        None,
        None,
        0.0,
        "because",
        {"piano_margin_db": float("inf"), "piano_share": 0.5, "x": float("nan")},
    )
    payload = gui_suggestion._payload(ROFORMER, (1.0, 2.0), hint, measured=True)
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["evidence"] == {"piano_margin_db": None, "piano_share": 0.5, "x": None}


# --- the route, on real wavs ----------------------------------------------------


@pytest.fixture
def served(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="gui dependency group not installed")
    np = pytest.importorskip("numpy", reason="ml dependency group not installed")
    soundfile = pytest.importorskip("soundfile", reason="ml dependency group not installed")
    from fastapi.testclient import TestClient

    from swingscribe.gui import app as gui_app

    music = tmp_path / "music"
    music.mkdir()
    source = music / "Some Tune.m4a"
    source.write_bytes(b"pretend this is an m4a")
    rate = 8000
    seconds = 16
    t = np.arange(rate * seconds) / rate
    normalized = tmp_path / "cache" / "audio" / "normalized.wav"
    normalized.parent.mkdir(parents=True)
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")
    soundfile.write(str(normalized), np.stack([tone, tone], axis=1), rate)
    config = Config(cache_dir=tmp_path / "cache", gui={"library_dir": str(music)})
    document = Document(
        audio_path=str(source),
        sample_rate=rate,
        audio=AudioRef(path=str(normalized), sample_rate=rate, channels=2, duration=seconds),
    )
    monkeypatch.setattr(library, "ingested_document", lambda path, cfg: document)

    def separate(amplitudes, model=ROFORMER):
        folder = stems_dir(config.cache_dir, library.stem_digest(document), model)
        folder.mkdir(parents=True, exist_ok=True)
        for index, (name, amplitude) in enumerate(amplitudes.items()):
            wave = (amplitude * np.sin(2 * np.pi * (110 + 55 * index) * t)).astype("float32")
            soundfile.write(str(folder / f"{name}.wav"), np.stack([wave, wave], axis=1), rate)

    client = TestClient(gui_app.create_app(config))
    opened = client.post("/api/tracks/open", json={"path": str(source)})
    assert opened.status_code == 200, opened.text
    return {"client": client, "id": opened.json()["id"], "separate": separate, "source": source}


# Stem amplitudes of a piano solo over a trio: the piano on top, the other
# melodic stems 40-50 dB down, the bass 10 dB and the drums 16 dB down.
PIANO_WAVS = {
    "piano": 0.3,
    "other": 0.003,
    "bass": 0.1,
    "drums": 0.05,
    "guitar": 0.001,
    "vocals": 0.001,
}


def get(served, **params):
    params = {"model": ROFORMER, "start": 0.0, "end": 16.0} | params
    return served["client"].get(f"/api/tracks/{served['id']}/suggestion", params=params)


def test_the_route_suggests_trio_over_a_piano_solo(served):
    served["separate"](PIANO_WAVS)
    response = get(served)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["measured"] is True
    assert (body["ensemble"], body["stem"]) == ("trio", "piano")
    assert body["evidence"]["piano_share"] == 1.0
    assert body["span"] == [0.0, 16.0]


def test_the_route_suggests_horn_led_over_a_horn_solo(served):
    served["separate"](
        {"piano": 0.01, "other": 0.3, "bass": 0.1, "drums": 0.05, "guitar": 0.001, "vocals": 0.001}
    )
    body = get(served).json()
    assert (body["ensemble"], body["stem"]) == ("horn-led", "other")


def test_the_route_says_nothing_under_the_floor_of_melody(served):
    """Under `routing.MIN_ACTIVE_S` (15 s since the floor sweep) a piano solo
    as clear as this one is still no suggestion: at 10 s nine horn windows
    passed the share test (docs/routing.md)."""
    served["separate"](PIANO_WAVS)
    body = get(served, start=2.0, end=14.0).json()
    assert body["measured"] is True
    assert body["ensemble"] is None
    assert f"at least {routing.MIN_ACTIVE_S:.0f} s" in body["reason"]


def test_the_route_offers_nothing_off_the_roformer(served):
    """The same piano solo on htdemucs_6s stems: measured, and no call. That
    separator filed three of five benchmark piano solos under `guitar` and
    read Coltrane's soprano 0.9 dB from a trio call (docs/routing.md)."""
    served["separate"](PIANO_WAVS, model="htdemucs_6s")
    body = get(served, model="htdemucs_6s").json()
    assert body["measured"] is True
    assert (body["ensemble"], body["stem"]) == (None, None)
    assert "bsroformer_sw" in body["reason"]
    # The evidence still says what the stems read; only the call is withheld.
    assert body["evidence"]["piano_share"] == 1.0


def test_the_route_writes_nothing(served):
    """A suggestion is a read: the sidecar beside the audio is the listener's."""
    served["separate"](PIANO_WAVS)
    sidecar = library.settings_path(served["source"])
    before = sidecar.read_bytes() if sidecar.exists() else None
    assert get(served).status_code == 200
    after = sidecar.read_bytes() if sidecar.exists() else None
    assert after == before


def test_the_route_refuses_a_model_off_the_menu_and_a_backwards_span(served):
    assert get(served, model="../../elsewhere").status_code == 400
    assert get(served, start=9.0, end=3.0).status_code == 400


def test_the_page_has_the_suggestion_strip(served):
    """The markup the script fills: the strip, its Apply and its Keep."""
    html = served["client"].get("/").text
    for element in ('id="ensemble-suggestion"', 'id="suggestion-apply"', 'id="suggestion-keep"'):
        assert element in html
