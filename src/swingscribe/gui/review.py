"""Transcription for the review screen: notes plus the per-frame trace.

This is what Screen 4 draws. It calls the core's `transcribe.analyze()`
directly — not `pipeline.run` — for two deliberate reasons:

- analyze() returns the FrameDiagnostics the pipeline discards, which is the
  whole point of the review screen: a note traces to a cause.
- The result is cached HERE, under gui/, not in the pipeline's chained-key
  stage cache. The GUI must never construct a pipeline cache key itself — get
  it subtly wrong and it poisons the cache with results the config does not
  describe. The cost is that a later `swingscribe ab` re-runs CREPE (~30s);
  that is the safe trade.

The gui review cache is keyed by the ingested-stem digest + model + the full
transcribe config (which already carries the span and stem). So reopening a
span you reviewed is instant, and changing the span, the stem, or any gate
threshold is a different key — never a stale hit.

Everything is in whole-track seconds, matching FrameDiagnostics.

Heavy imports stay inside functions (CLAUDE.md).
"""

import hashlib
from pathlib import Path
from typing import Any

from swingscribe.cache import StageCache, canonical_json
from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.model import Document, NoteEvent

# Diagnostics are ~100 frames/second; a two-minute span is ~12k frames across
# several arrays. That is fine to send over localhost once, but pointless to
# send at full float precision — three decimals is well under a MIDI cent.
_ROUND = 3


def review_key(document: Document, config: Config, model: str) -> str:
    """Content key for a transcription review: the stem's identity, the model
    that produced it, and every transcribe setting that would change a note."""
    stem_digest = library.stem_digest(document)
    tc = canonical_json(config.transcribe.model_dump(mode="json"))
    raw = f"{stem_digest}\x00{model}\x00{tc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache(config: Config) -> StageCache:
    return StageCache(Path(config.cache_dir) / "gui" / "reviews")


def cached_review(document: Document, config: Config, model: str) -> dict[str, Any] | None:
    """The stored review for this exact stem+model+config, or None."""
    return _cache(config).get_json(review_key(document, config, model))


def _payload(notes: list[NoteEvent], diagnostics: Any) -> dict[str, Any]:
    """Serialize notes + frame trace for the wire.

    Frame arrays are parallel and equal length; the client indexes them by
    frame number, and turns a click on a note into a frame range via `hop_s`
    and `start`. `None` (a gated-out or unpitched frame) is preserved as null,
    because "no pitch here" is itself diagnostic.
    """
    frames = len(diagnostics.periodicity)

    def r(value: float | None) -> float | None:
        return None if value is None else round(value, _ROUND)

    return {
        "notes": [
            {
                "onset": round(n.onset, _ROUND),
                "duration": round(n.duration, _ROUND),
                "pitch": n.pitch,
                "confidence": round(n.confidence, _ROUND),
            }
            for n in notes
        ],
        "diagnostics": {
            "hop_s": diagnostics.hop_s,
            "start": round(diagnostics.start, _ROUND),
            "frames": frames,
            "f0_midi": [r(v) for v in diagnostics.f0_midi],
            "periodicity": [r(v) for v in diagnostics.periodicity],
            "energy_ok": list(diagnostics.energy_ok),
            "pitch": [r(v) for v in diagnostics.pitch],
            "onsets": [round(t, _ROUND) for t in diagnostics.onsets],
            "voiced_fraction": round(diagnostics.voiced_fraction, _ROUND),
        },
    }


def analyze_and_cache(document: Document, config: Config, model: str) -> dict[str, Any]:
    """Transcribe the configured span and cache the notes + diagnostics.

    Runs on the job worker; the stage emits progress.report() around the CREPE
    pass, so the existing job machinery reports it unchanged. The stem must
    already be separated (it is — the user has been auditioning it).
    """
    from swingscribe.stages import transcribe

    stem = config.transcribe.stem
    stem_path = library.available_stems(document, config, model).get(stem)
    if stem_path is None:
        available = ", ".join(sorted(library.available_stems(document, config, model)))
        raise ValueError(f"no {stem!r} stem for {model}; available: {available or 'none'}")

    notes, diagnostics = transcribe.analyze(stem_path, config.transcribe)
    payload = _payload(notes, diagnostics)
    _cache(config).put_json(review_key(document, config, model), payload)
    return payload
