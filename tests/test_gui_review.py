"""The review module: keying, payload shape, and the endpoints Screen 4 reads.

analyze() itself is heavy (CREPE), so it is monkeypatched here — what is under
test is the GUI's keying and serialization, not the transcriber.
"""

from dataclasses import dataclass

import pytest

from swingscribe.config import Config
from swingscribe.model import AudioRef, Document, NoteEvent

pytest.importorskip("fastapi", reason="gui dependency group not installed")

from swingscribe.gui import library, review  # noqa: E402
from swingscribe.stages.separate import stems_dir  # noqa: E402


@dataclass
class FakeDiagnostics:
    hop_s: float = 0.01
    start: float = 30.0
    f0_midi: list = None
    periodicity: list = None
    energy_ok: list = None
    pitch: list = None
    onsets: list = None

    @property
    def voiced_fraction(self) -> float:
        return sum(1 for p in self.pitch if p is not None) / max(1, len(self.pitch))


def a_document(tmp_path) -> Document:
    wav = tmp_path / "cache" / "audio" / "norm.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(b"normalized")
    return Document(
        audio_path="orig.m4a",
        sample_rate=44100,
        audio=AudioRef(path=str(wav), sample_rate=44100, channels=2, duration=200.0),
    )


def a_config(tmp_path, **transcribe) -> Config:
    config = Config(cache_dir=tmp_path / "cache")
    if transcribe:
        config = config.model_copy(
            update={"transcribe": config.transcribe.model_copy(update=transcribe)}
        )
    return config


# ── keying ──────────────────────────────────────────────────────────────────


def test_key_is_stable_for_the_same_inputs(tmp_path):
    document = a_document(tmp_path)
    config = a_config(tmp_path, region=(30.0, 45.0), stem="other")
    assert review.review_key(document, config, "htdemucs_ft") == review.review_key(
        document, config, "htdemucs_ft"
    )


def test_key_changes_with_span_stem_model_and_threshold(tmp_path):
    document = a_document(tmp_path)
    base = a_config(tmp_path, region=(30.0, 45.0), stem="other")
    key = review.review_key(document, base, "htdemucs_ft")

    span = a_config(tmp_path, region=(30.0, 60.0), stem="other")
    stem = a_config(tmp_path, region=(30.0, 45.0), stem="guitar")
    thresh = a_config(tmp_path, region=(30.0, 45.0), stem="other", voicing_threshold=0.7)

    assert review.review_key(document, span, "htdemucs_ft") != key
    assert review.review_key(document, stem, "htdemucs_ft") != key
    assert review.review_key(document, base, "htdemucs_6s") != key
    assert review.review_key(document, thresh, "htdemucs_ft") != key


# ── payload ───────────────────────────────────────────────────────────────


def test_payload_preserves_nulls_and_frame_alignment():
    notes = [NoteEvent(onset=30.0, duration=0.5, pitch=64, confidence=0.8, source="other")]
    diag = FakeDiagnostics(
        f0_midi=[64.123456, None, 64.2],
        periodicity=[0.9, 0.1, 0.8],
        energy_ok=[True, False, True],
        pitch=[64.12, None, 64.2],
        onsets=[30.0, 30.5],
    )
    payload = review._payload(notes, diag)

    d = payload["diagnostics"]
    assert d["frames"] == 3
    assert len(d["f0_midi"]) == len(d["periodicity"]) == len(d["pitch"]) == 3
    # A gated-out / unpitched frame stays null — "no pitch here" is diagnostic.
    assert d["f0_midi"][1] is None
    assert d["pitch"][1] is None
    assert d["energy_ok"] == [True, False, True]
    assert d["voiced_fraction"] == pytest.approx(2 / 3, abs=0.01)
    assert payload["notes"][0]["pitch"] == 64


def test_analyze_and_cache_round_trips(tmp_path, monkeypatch):
    document = a_document(tmp_path)
    config = a_config(tmp_path, region=(30.0, 45.0), stem="other")

    stem_dir = stems_dir(config.cache_dir, library.stem_digest(document), "htdemucs_ft")
    stem_dir.mkdir(parents=True)
    (stem_dir / "other.wav").write_bytes(b"stem")

    notes = [NoteEvent(onset=31.0, duration=0.3, pitch=60, confidence=0.9, source="other")]
    diag = FakeDiagnostics(
        f0_midi=[60.0, 60.0],
        periodicity=[0.9, 0.9],
        energy_ok=[True, True],
        pitch=[60.0, 60.0],
        onsets=[31.0],
    )
    seen = {}

    def fake_analyze(stem_path, tc):
        seen["stem_path"] = stem_path
        seen["region"] = tc.region
        return notes, diag

    monkeypatch.setattr("swingscribe.stages.transcribe.analyze", fake_analyze)

    produced = review.analyze_and_cache(document, config, "htdemucs_ft")
    assert seen["stem_path"].endswith("other.wav")
    assert seen["region"] == (30.0, 45.0)
    assert len(produced["notes"]) == 1

    # Now a cache hit, without touching analyze again.
    monkeypatch.setattr(
        "swingscribe.stages.transcribe.analyze",
        lambda *a: (_ for _ in ()).throw(AssertionError("should not re-run")),
    )
    cached = review.cached_review(document, config, "htdemucs_ft")
    assert cached == produced


def test_missing_stem_is_a_clear_error(tmp_path):
    document = a_document(tmp_path)
    config = a_config(tmp_path, region=(30.0, 45.0), stem="guitar")
    with pytest.raises(ValueError, match="guitar"):
        review.analyze_and_cache(document, config, "htdemucs_ft")


def test_span_precision_is_canonicalised_server_side(tmp_path):
    """The job POST sends raw floats and the review GET sends toFixed(3). The
    key is a hash of the config, so without rounding in one shared place those
    are different spans and the GET never finds the job's work."""
    document = a_document(tmp_path)
    raw = a_config(tmp_path, region=(round(60.063700000001, 3), 90.09), stem="other")
    rounded = a_config(tmp_path, region=(60.064, 90.09), stem="other")
    assert review.review_key(document, raw, "htdemucs_ft") == review.review_key(
        document, rounded, "htdemucs_ft"
    )
