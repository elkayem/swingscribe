"""The ground-truth overlay: transposition, placement, and the four classes.

Scores are written here as XML rather than committed: the real benchmark
transcriptions are derivative works of commercial recordings and must never
enter git (plan §12). Hand-built ones also let placement be asserted exactly,
which a real solo never could.
"""

import pytest

from swingscribe.config import Config

pytest.importorskip("fastapi", reason="gui dependency group not installed")

from swingscribe.gui import ground_truth  # noqa: E402

# The synthetic solo: two 4/4 bars, eight quarter notes, written an octave
# above the concert pitch we produce — the benchmark's tenor case.
CONCERT = [72, 74, 76, 77, 79, 77, 76, 74]
WRITTEN = [p + 12 for p in CONCERT]

# Onsets that are deliberately NOT at a constant tempo: they run ahead of the
# grid and then fall behind it, which is what real playing does and what makes
# constant-tempo placement wrong.
ONSETS = [10.0, 10.6, 11.2, 11.7, 12.1, 12.5, 12.9, 13.3]
SPAN = (10.0, 14.0)  # 8 quarter notes over 4s -> 120 bpm implied


def chord(pitch: int, duration: str = "quarter") -> str:
    return (
        f"<Chord><durationType>{duration}</durationType><Note><pitch>{pitch}</pitch></Note></Chord>"
    )


def write_score(tmp_path, pitches, name="solo.mscx", per_bar=4) -> str:
    """A score of quarter notes, `per_bar` to a bar."""
    bars = []
    for start in range(0, len(pitches), per_bar):
        body = "".join(chord(p) for p in pitches[start : start + per_bar])
        head = "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>" if not bars else ""
        bars.append(f"<Measure><voice>{head}{body}</voice></Measure>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<museScore version="4.70"><Score>'
        '<metaTag name="workTitle">Synthetic</metaTag>'
        f"<Staff>{''.join(bars)}</Staff>"
        "</Score></museScore>"
    )
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return str(path)


def notes_from(pitches, onsets, duration=0.3):
    return [
        {"onset": t, "duration": duration, "pitch": p, "confidence": 0.9}
        for p, t in zip(pitches, onsets, strict=True)
    ]


# ── transposition (trap 1) ──────────────────────────────────────────────────


def test_transposition_is_measured_not_assumed(tmp_path):
    """A score written an octave up must not read as eight wrong notes."""
    overlay = ground_truth.overlay(
        write_score(tmp_path, WRITTEN), notes_from(CONCERT, ONSETS), *SPAN
    )
    assert overlay["score"]["transposition"] == 12
    assert overlay["counts"]["matched"] == len(CONCERT)
    assert overlay["counts"]["wrong"] == 0
    assert overlay["pitch_f1"] == 1.0


def test_reference_notes_are_reported_at_concert_pitch(tmp_path):
    """Both lanes share one pitch axis, so the score comes down to ours."""
    overlay = ground_truth.overlay(
        write_score(tmp_path, WRITTEN), notes_from(CONCERT, ONSETS), *SPAN
    )
    assert [n["pitch"] for n in overlay["reference_notes"]] == CONCERT
    assert [n["written"] for n in overlay["reference_notes"]] == WRITTEN


def test_no_transposition_when_the_score_is_at_concert_pitch(tmp_path):
    overlay = ground_truth.overlay(
        write_score(tmp_path, CONCERT), notes_from(CONCERT, ONSETS), *SPAN
    )
    assert overlay["score"]["transposition"] == 0


# ── horizontal placement (trap 2) ───────────────────────────────────────────


def test_aligned_notes_take_our_timestamps_exactly(tmp_path):
    """The whole point: an aligned notated note needs no tempo at all, because
    we know which of our notes it is and that note has a real onset."""
    overlay = ground_truth.overlay(
        write_score(tmp_path, WRITTEN), notes_from(CONCERT, ONSETS), *SPAN
    )
    assert [n["x"] for n in overlay["reference_notes"]] == ONSETS
    assert overlay["score"]["anchors"] == len(ONSETS)


def test_unaligned_notes_are_interpolated_between_their_anchors(tmp_path):
    """A missed note has no timestamp of its own, so it lands proportionally
    between the anchors that surround it — not on the constant-tempo grid."""
    # Drop the 4th note (index 3) from what we produced: it becomes `missed`.
    kept = [i for i in range(len(CONCERT)) if i != 3]
    notes = notes_from([CONCERT[i] for i in kept], [ONSETS[i] for i in kept])
    overlay = ground_truth.overlay(write_score(tmp_path, WRITTEN), notes, *SPAN)

    assert overlay["counts"]["missed"] == 1
    placed = overlay["reference_notes"]
    assert placed[3]["cls"] == "missed"
    # Position 3 quarters sits midway between the anchors at 2 and 4 quarters.
    assert placed[3]["x"] == pytest.approx((ONSETS[2] + ONSETS[4]) / 2, abs=1e-6)
    # Its neighbours are still exact.
    assert placed[2]["x"] == ONSETS[2]
    assert placed[4]["x"] == ONSETS[4]


def test_placement_stays_ordered(tmp_path):
    kept = [i for i in range(len(CONCERT)) if i not in (0, 3, 7)]
    notes = notes_from([CONCERT[i] for i in kept], [ONSETS[i] for i in kept])
    overlay = ground_truth.overlay(write_score(tmp_path, WRITTEN), notes, *SPAN)
    xs = [n["x"] for n in overlay["reference_notes"]]
    assert xs == sorted(xs)


def test_drift_reports_what_constant_tempo_would_have_cost(tmp_path):
    """The honest statement of trap 2: how far the alignment had to move the
    score away from the constant tempo the notation implies."""
    overlay = ground_truth.overlay(
        write_score(tmp_path, WRITTEN), notes_from(CONCERT, ONSETS), *SPAN
    )
    # ONSETS run 0.2s ahead of the 0.5s/quarter grid and 0.2s behind it.
    assert overlay["score"]["drift_s"] == pytest.approx(0.4, abs=0.01)
    assert overlay["score"]["implied_bpm"] == pytest.approx(120.0, abs=0.1)


def test_constant_tempo_is_the_fallback_when_nothing_anchors(tmp_path):
    """With no anchors there is no map to derive, so placement falls back to
    bars/span rather than refusing to draw."""
    overlay = ground_truth.overlay(write_score(tmp_path, WRITTEN), [], *SPAN)
    assert overlay["score"]["anchors"] == 0
    xs = [n["x"] for n in overlay["reference_notes"]]
    assert xs == [pytest.approx(10.0 + i * 0.5) for i in range(len(WRITTEN))]
    assert overlay["score"]["drift_s"] == 0.0


# Distinct pitches, so the aligner cannot anchor them ambiguously.
DISTINCT = [60, 62, 64, 65, 67, 69, 71, 72]


def test_notes_placed_outside_the_span_are_pinned_into_it(tmp_path):
    """A missed note drawn outside the span is drawn NOWHERE, and an invisible
    note is indistinguishable from one the score does not contain.

    This is R16's second failure: with half our line gone the alignment
    anchored only the tail, and extrapolating off that pair put the opening
    bars BEFORE the span started. Twenty 'missed' notes silently vanished and
    the passage read as empty.
    """
    # Only the last three notes survive, and they anchor early in the span —
    # so extrapolating back off them lands the opening well before `start`.
    notes = notes_from(DISTINCT[5:], [10.1, 10.6, 11.1])
    overlay = ground_truth.overlay(write_score(tmp_path, DISTINCT), notes, *SPAN)

    placed = overlay["reference_notes"]
    assert len(placed) == len(DISTINCT)  # every notated note is still reported
    # Nothing may be drawn off the edge of the view it is drawn on.
    assert all(SPAN[0] <= n["x"] <= SPAN[1] for n in placed)

    pinned = [n for n in placed if n["pinned"]]
    assert overlay["score"]["off_span"] == len(pinned) == 5
    assert all(n["cls"] == "missed" for n in pinned)
    assert all(n["x"] == SPAN[0] for n in pinned)  # pinned to the edge they left by
    # The anchored tail is untouched and still exact.
    assert [n["x"] for n in placed[5:]] == [10.1, 10.6, 11.1]


def test_a_healthy_alignment_pins_nothing(tmp_path):
    """The pin is a repair for a failed alignment, not a thing that happens."""
    overlay = ground_truth.overlay(
        write_score(tmp_path, WRITTEN), notes_from(CONCERT, ONSETS), *SPAN
    )
    assert overlay["score"]["off_span"] == 0
    assert not any(n["pinned"] for n in overlay["reference_notes"])


def test_overlay_cache_version_separates_placements(tmp_path):
    """The overlay key hashes both sides' CONTENT, which cannot see a change to
    placement itself — so a stored overlay would outlive the code that made it."""
    score = write_score(tmp_path, WRITTEN)
    key = ground_truth.overlay_key("review-abc", score)
    ground_truth.CACHE_VERSION += 1
    try:
        assert ground_truth.overlay_key("review-abc", score) != key
    finally:
        ground_truth.CACHE_VERSION -= 1


def test_place_handles_the_thin_anchor_cases():
    """Zero and one anchor have no slope to interpolate along."""
    assert ground_truth._place(4.0, [], [], 0.5, 10.0) == (12.0, 0.5)
    # One anchor pins the offset; the rate still has to come from the notation.
    assert ground_truth._place(4.0, [2.0], [11.0], 0.5, 10.0) == (12.0, 0.5)
    # A pair that does not advance in time says nothing about tempo.
    x, rate = ground_truth._place(4.0, [2.0, 3.0], [11.0, 11.0], 0.5, 10.0)
    assert rate == 0.5


# ── the four classes ────────────────────────────────────────────────────────


def test_classes_cover_every_note_on_both_sides(tmp_path):
    """matched / wrong / invented / missed, straight off the alignment path."""
    pitches = list(CONCERT)
    pitches[5] = pitches[5] - 1  # a wrong note, one semitone off
    onsets = list(ONSETS)
    pitches.insert(2, 60)  # an invented note nothing was notated for
    onsets.insert(2, 11.05)
    overlay = ground_truth.overlay(
        write_score(tmp_path, WRITTEN), notes_from(pitches, onsets), *SPAN
    )

    counts = overlay["counts"]
    assert counts["invented"] == 1
    assert counts["wrong"] == 1
    assert counts["matched"] == len(CONCERT) - 1
    assert counts["missed"] == 0

    assert len(overlay["estimate_class"]) == len(pitches)
    assert overlay["estimate_class"][2] == "invented"
    assert overlay["estimate_partner"][2] is None
    assert set(overlay["estimate_class"]) == {"matched", "wrong", "invented"}

    # Partners point both ways, which is what draws the stalk between a wrong
    # note and what was written.
    for index, kind in enumerate(overlay["estimate_class"]):
        partner = overlay["estimate_partner"][index]
        if kind == "invented":
            assert partner is None
        else:
            assert overlay["reference_notes"][partner]["partner"] == index


def test_empty_transcription_is_all_missed(tmp_path):
    overlay = ground_truth.overlay(write_score(tmp_path, WRITTEN), [], *SPAN)
    assert overlay["counts"]["missed"] == len(WRITTEN)
    assert overlay["counts"]["matched"] == 0
    assert all(n["cls"] == "missed" for n in overlay["reference_notes"])


# ── finding a score ─────────────────────────────────────────────────────────


def test_nearby_scores_rank_by_shared_words_not_by_stem(tmp_path):
    """The benchmark names scores after the soloist and audio after the album
    track, so an exact-stem match would find nothing."""
    audio = tmp_path / "02 Confirmation.m4a"
    audio.write_bytes(b"audio")
    write_score(tmp_path, WRITTEN, "Dexter_Gordon_solo_on_Confirmation.mscx")
    write_score(tmp_path, WRITTEN, "Tommy Flanagan Solo on Giant Steps.mscx")

    found = ground_truth.nearby_scores(audio)
    assert [c["name"] for c in found][0] == "Dexter_Gordon_solo_on_Confirmation.mscx"
    assert found[0]["shared"] == ["confirmation"]
    assert found[0]["matched"] is True
    # The other tune is still offered — ranking is a suggestion, not a filter.
    assert len(found) == 2
    assert found[1]["matched"] is False


def test_nearby_scores_ignores_non_scores(tmp_path):
    audio = tmp_path / "tune.m4a"
    audio.write_bytes(b"audio")
    (tmp_path / "tune.mid").write_bytes(b"midi")
    (tmp_path / "notes.txt").write_text("nope", encoding="utf-8")
    assert ground_truth.nearby_scores(audio) == []


# ── caching ─────────────────────────────────────────────────────────────────


def test_overlay_is_cached_per_transcription_and_score(tmp_path):
    config = Config(cache_dir=tmp_path / "cache")
    score = write_score(tmp_path, WRITTEN)
    notes = notes_from(CONCERT, ONSETS)

    first = ground_truth.cached_overlay(config, "review-key", score, notes, *SPAN)
    # A hit must not re-read the score, so removing it changes nothing.
    second = ground_truth.cached_overlay(config, "review-key", score, notes, *SPAN)
    assert first == second

    # A different transcription is a different overlay.
    assert ground_truth.overlay_key("review-key", score) != ground_truth.overlay_key(
        "other-key", score
    )
    # And so is a re-notated score, because the key is over its bytes.
    edited = write_score(tmp_path, WRITTEN[:-1], "edited.mscx")
    assert ground_truth.overlay_key("review-key", edited) != ground_truth.overlay_key(
        "review-key", score
    )


# ── the endpoints ───────────────────────────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402

from swingscribe.gui import app as gui_app  # noqa: E402
from swingscribe.gui import library, review  # noqa: E402
from swingscribe.model import AudioRef, Document  # noqa: E402
from swingscribe.stages.separate import stems_dir  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A track with a transcribed span and a score beside it, no stages run."""
    music = tmp_path / "music"
    music.mkdir()
    source = music / "02 Confirmation.m4a"
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

    score = write_score(music, WRITTEN, "Dexter_Gordon_solo_on_Confirmation.mscx")
    client = TestClient(gui_app.create_app(config))
    track = client.post("/api/tracks/open", json={"path": str(source)}).json()
    return {
        "client": client,
        "config": config,
        "document": document,
        "track": track,
        "score": score,
        "source": source,
        "music": music,
    }


def transcribe_the_span(world, monkeypatch, pitches=CONCERT, onsets=ONSETS):
    """Fill the review cache the way a transcribe job would."""
    from swingscribe.model import NoteEvent

    class Diagnostics:
        hop_s = 0.01
        start = SPAN[0]
        f0_midi = [60.0]
        periodicity = [0.9]
        energy_ok = [True]
        pitch = [60.0]
        onsets = [SPAN[0]]
        voiced_fraction = 1.0

    notes = [
        NoteEvent(onset=t, duration=0.3, pitch=p, confidence=0.9, source="other")
        for p, t in zip(pitches, onsets, strict=True)
    ]
    monkeypatch.setattr(
        "swingscribe.stages.transcribe.analyze", lambda path, tc: (notes, Diagnostics())
    )
    config = world["config"]
    run = config.model_copy(
        update={
            "transcribe": config.transcribe.model_copy(update={"stem": "other", "region": SPAN})
        }
    )
    review.analyze_and_cache(world["document"], run, "htdemucs_ft")


def ground_truth_url(world, score=None, start=SPAN[0], end=SPAN[1]) -> str:
    return (
        f"/api/tracks/{world['track']['id']}/ground-truth"
        f"?model=htdemucs_ft&stem=other&start={start}&end={end}"
        f"&score={score or world['score']}"
    )


def test_browse_lists_scores_alongside_audio(world):
    data = world["client"].get(f"/api/browse?path={world['music']}").json()
    assert [f["name"] for f in data["files"]] == ["02 Confirmation.m4a"]
    assert [s["name"] for s in data["scores"]] == ["Dexter_Gordon_solo_on_Confirmation.mscx"]


def test_scores_endpoint_suggests_what_sits_beside_the_track(world):
    found = world["client"].get(f"/api/tracks/{world['track']['id']}/scores").json()
    assert found["scores"][0]["name"] == "Dexter_Gordon_solo_on_Confirmation.mscx"
    assert found["scores"][0]["matched"] is True


def test_overlay_needs_the_transcription_first(world):
    """The alignment is *to* our notes and their onsets place the score, so
    there is nothing to draw until the span has been transcribed."""
    response = world["client"].get(ground_truth_url(world))
    assert response.status_code == 404
    assert "transcribe" in response.json()["detail"]


def test_overlay_is_served_once_the_span_is_transcribed(world, monkeypatch):
    transcribe_the_span(world, monkeypatch)
    payload = world["client"].get(ground_truth_url(world)).json()
    assert payload["score"]["transposition"] == 12
    assert payload["counts"]["matched"] == len(CONCERT)
    assert payload["estimate_class"] == ["matched"] * len(CONCERT)
    assert [n["x"] for n in payload["reference_notes"]] == ONSETS


def test_a_missing_or_wrong_file_is_a_clear_error(world, monkeypatch):
    transcribe_the_span(world, monkeypatch)
    client = world["client"]
    assert (
        client.get(ground_truth_url(world, score=str(world["music"] / "nope.mscz"))).status_code
        == 404
    )
    assert client.get(ground_truth_url(world, score=str(world["source"]))).status_code == 400
