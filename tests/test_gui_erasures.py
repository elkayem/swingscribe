"""Silenced notes: matching them back after a re-transcription, and the
guarantee that a label is never lost on the way.

The matching is the whole risk here. Note indices are renumbered by any
config change, so an erasure stored as "note #417" would later silence a
different note — silently. Everything below is about that.
"""

import pytest

from swingscribe.config import Config

pytest.importorskip("fastapi", reason="gui dependency group not installed")

from swingscribe.gui import erasures  # noqa: E402


def note(onset: float, pitch: int, duration: float = 0.2, confidence: float = 0.8) -> dict:
    return {"onset": onset, "pitch": pitch, "duration": duration, "confidence": confidence}


NOTES = [note(10.0, 60), note(10.5, 62), note(11.0, 64), note(11.5, 62), note(12.0, 67)]
SPAN = (9.0, 13.0)


# ── the record ──────────────────────────────────────────────────────────────


def test_record_snapshots_what_the_note_was(tmp_path):
    """Duration and confidence are stored, not looked up later: the label has
    to survive a transcription that can no longer be reproduced."""
    made = erasures.record(note(51.2344, 55, 0.14, 0.617), "other", "htdemucs_ft")
    assert made == {
        "onset": 51.234,
        "pitch": 55,
        "duration": 0.14,
        "confidence": 0.617,
        "reason": "not-solo",
        "stem": "other",
        "model": "htdemucs_ft",
    }


# ── matching ────────────────────────────────────────────────────────────────


def test_exact_notes_match(tmp_path):
    stored = [erasures.record(NOTES[1], "other", "m"), erasures.record(NOTES[3], "other", "m")]
    resolved = erasures.resolve(stored, NOTES, SPAN)
    assert resolved["silenced"] == [1, 3]
    assert resolved["unmatched"] == []


def test_a_note_that_moved_slightly_still_matches():
    """A threshold change nudges onsets by a frame or two; that is the same
    note and must stay silenced."""
    stored = [erasures.record(note(11.0, 64), "other", "m")]
    moved = [note(10.0, 60), note(11.02, 64)]
    assert erasures.resolve(stored, moved, SPAN)["silenced"] == [1]


def test_a_note_that_moved_too_far_does_not_match():
    stored = [erasures.record(note(11.0, 64), "other", "m")]
    moved = [note(11.4, 64)]
    resolved = erasures.resolve(stored, moved, SPAN)
    assert resolved["silenced"] == []
    assert len(resolved["unmatched"]) == 1


def test_pitch_must_be_exact():
    """An octave folded differently is a different note. Failing to match and
    saying so beats silencing something in the wrong register."""
    stored = [erasures.record(note(11.0, 64), "other", "m")]
    folded = [note(11.0, 52)]
    resolved = erasures.resolve(stored, folded, SPAN)
    assert resolved["silenced"] == []
    assert resolved["unmatched"][0]["pitch"] == 64


def test_the_nearest_of_two_candidates_wins():
    """Fragmentation leaves two notes of the same pitch milliseconds apart, so
    a first-match scan would claim whichever happened to come first."""
    stored = [erasures.record(note(11.02, 64), "other", "m")]
    fragmented = [note(11.0, 64), note(11.025, 64)]
    assert erasures.resolve(stored, fragmented, SPAN)["silenced"] == [1]


def test_one_note_per_erasure_and_one_erasure_per_note():
    """Two erasures inside one tolerance window must not both claim the same
    note, and must not leave the second silently matched to nothing."""
    stored = [
        erasures.record(note(11.00, 64), "other", "m"),
        erasures.record(note(11.02, 64), "other", "m"),
    ]
    single = [note(11.01, 64)]
    resolved = erasures.resolve(stored, single, SPAN)
    assert resolved["silenced"] == [0]
    assert len(resolved["unmatched"]) == 1


def test_assignment_is_deterministic():
    stored = [erasures.record(n, "other", "m") for n in NOTES]
    first = erasures.resolve(stored, NOTES, SPAN)
    second = erasures.resolve(list(reversed(stored)), NOTES, SPAN)
    assert first["silenced"] == second["silenced"] == [0, 1, 2, 3, 4]


# ── what happens when one no longer matches ─────────────────────────────────


def test_unmatched_erasures_are_carried_never_dropped():
    """The label still describes a note somebody judged. Losing it on a reload
    would destroy exactly the data this feature exists to collect."""
    stored = [erasures.record(note(11.0, 64), "other", "m")]
    resolved = erasures.resolve(stored, [note(10.0, 60)], SPAN)
    assert resolved["carried"] == stored
    assert resolved["stored"] == 1


def test_erasures_outside_the_span_are_carried_but_not_reported():
    """Moving the span is routine; those erasures are out of view, not lost,
    and reporting them would cry wolf on every span change."""
    stored = [
        erasures.record(note(11.0, 64), "other", "m"),  # in span, matches
        erasures.record(note(200.0, 70), "other", "m"),  # another solo entirely
    ]
    resolved = erasures.resolve(stored, NOTES, SPAN)
    assert resolved["silenced"] == [2]
    assert resolved["unmatched"] == []
    assert resolved["carried"] == [stored[1]]


def test_no_span_reports_everything():
    stored = [erasures.record(note(200.0, 70), "other", "m")]
    assert len(erasures.resolve(stored, NOTES, None)["unmatched"]) == 1


def test_malformed_records_are_ignored_not_fatal():
    """The sidecar is a file a person can edit."""
    stored = [{"pitch": 64}, {"onset": 11.0}, erasures.record(NOTES[0], "other", "m")]
    assert erasures.resolve(stored, NOTES, SPAN)["silenced"] == [0]


# ── what sounds ─────────────────────────────────────────────────────────────


def test_audible_drops_only_the_silenced():
    kept = erasures.audible(NOTES, [1, 3])
    assert [n["pitch"] for n in kept] == [60, 64, 67]
    assert len(NOTES) == 5  # the input is untouched


def test_audible_with_nothing_silenced_is_everything():
    assert erasures.audible(NOTES, []) == NOTES


# ── the endpoints ───────────────────────────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402

from swingscribe.gui import app as gui_app  # noqa: E402
from swingscribe.gui import library, review  # noqa: E402
from swingscribe.model import AudioRef, Document, NoteEvent  # noqa: E402
from swingscribe.stages.separate import stems_dir  # noqa: E402


class Diagnostics:
    hop_s = 0.01
    start = SPAN[0]
    f0_midi = [60.0]
    periodicity = [0.9]
    energy_ok = [True]
    pitch = [60.0]
    onsets = [SPAN[0]]
    voiced_fraction = 1.0


@pytest.fixture
def world(tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    source = music / "Tune.m4a"
    source.write_bytes(b"pretend this is an m4a")
    normalized = tmp_path / "cache" / "audio" / "normalized.wav"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"pretend this is a wav")

    config = Config(cache_dir=tmp_path / "cache", gui={"library_dir": str(music)})
    document = Document(
        audio_path=str(source),
        sample_rate=8000,
        audio=AudioRef(path=str(normalized), sample_rate=8000, channels=2, duration=60.0),
    )
    monkeypatch.setattr(library, "ingested_document", lambda path, cfg: document)
    stem_dir = stems_dir(config.cache_dir, library.stem_digest(document), "htdemucs_ft")
    stem_dir.mkdir(parents=True)
    (stem_dir / "other.wav").write_bytes(b"stem")

    events = [
        NoteEvent(
            onset=n["onset"],
            duration=n["duration"],
            pitch=n["pitch"],
            confidence=n["confidence"],
            source="other",
        )
        for n in NOTES
    ]
    monkeypatch.setattr(
        "swingscribe.stages.transcribe.analyze", lambda path, tc: (events, Diagnostics())
    )
    run = config.model_copy(
        update={
            "transcribe": config.transcribe.model_copy(update={"stem": "other", "region": SPAN})
        }
    )
    review.analyze_and_cache(document, run, "htdemucs_ft")

    client = TestClient(gui_app.create_app(config))
    track = client.post("/api/tracks/open", json={"path": str(source)}).json()
    return {"client": client, "track": track, "source": source, "config": config}


def review_url(world) -> str:
    return (
        f"/api/tracks/{world['track']['id']}/review"
        f"?model=htdemucs_ft&stem=other&start={SPAN[0]}&end={SPAN[1]}"
    )


def save_erasures(world, records) -> None:
    response = world["client"].post(
        f"/api/tracks/{world['track']['id']}/state", json={"state": {"erasures": records}}
    )
    assert response.status_code == 200, response.text


def test_review_resolves_the_sidecars_erasures(world):
    save_erasures(world, [erasures.record(NOTES[1], "other", "htdemucs_ft")])
    payload = world["client"].get(review_url(world)).json()
    assert payload["erasures"]["silenced"] == [1]
    assert payload["erasures"]["unmatched"] == []


def test_erasures_are_not_part_of_the_review_cache_key(world):
    """Silencing a note is a judgement about the music, not a different
    transcription of it — it must not invalidate a 30-second CREPE run."""
    before = world["client"].get(review_url(world)).json()
    save_erasures(world, [erasures.record(NOTES[0], "other", "htdemucs_ft")])
    after = world["client"].get(review_url(world)).json()
    assert before["notes"] == after["notes"]
    assert before["erasures"]["silenced"] == []
    assert after["erasures"]["silenced"] == [0]


def test_erasures_live_beside_the_audio_not_in_the_cache(world, tmp_path):
    """CLAUDE.md: the cache is derived data that must stay safely deletable."""
    save_erasures(world, [erasures.record(NOTES[0], "other", "htdemucs_ft")])
    sidecar = library.settings_path(world["source"])
    assert sidecar.is_file()
    assert "erasures" in sidecar.read_text(encoding="utf-8")
    assert not list((tmp_path / "cache").rglob("*erasure*"))


def test_silenced_notes_do_not_reach_the_render(world, monkeypatch):
    """The ear test has to stop playing what you cut, or the A/B stops
    describing the transcription you are keeping."""
    seen = {}

    def fake_render(notes, start, end, sample_rate, rate):
        seen["pitches"] = [n.pitch for n in notes]
        return b"RIFF"

    monkeypatch.setattr("swingscribe.gui.audio.render_transcription", fake_render)
    url = (
        f"/api/tracks/{world['track']['id']}/transcription"
        f"?model=htdemucs_ft&stem=other&start={SPAN[0]}&end={SPAN[1]}"
    )

    assert world["client"].get(url).status_code == 200
    assert seen["pitches"] == [60, 62, 64, 62, 67]

    save_erasures(
        world,
        [
            erasures.record(NOTES[1], "other", "htdemucs_ft"),
            erasures.record(NOTES[3], "other", "htdemucs_ft"),
        ],
    )
    assert world["client"].get(url).status_code == 200
    assert seen["pitches"] == [60, 64, 67]
