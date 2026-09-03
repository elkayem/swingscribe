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

# Decimal places span bounds are rounded to before they reach a cache key.
# Milliseconds are finer than any boundary a person places by ear.
SPAN_PRECISION = 3


def span_config(
    config: Config,
    stem: str,
    start: float | None,
    end: float | None,
    ensemble: str | None = None,
    line: str | None = None,
) -> Config:
    """The exact transcribe config a review of this span is computed under.

    THE definition, used by the GUI's endpoints and by any batch tool that
    wants to produce the same numbers the GUI shows. It lives here rather
    than inside `create_app` because a second copy of this rounding is not a
    cosmetic difference: a span rounded to the millisecond crops the audio a
    couple of hundred samples away from where an unrounded one does, which
    moves CREPE's 10ms frame lattice against the music and flips notes across
    quantizer grid boundaries. Measured on Maiden Voyage, the identical 489
    notes scored notated rhythm 0.686 unrounded against 0.630 rounded -- so a
    caller that skipped this produced a genuinely different page from the one
    the GUI draws, with nothing on either side saying why.
    """
    region = (
        None
        if start is None and end is None
        else (
            round(start or 0.0, SPAN_PRECISION),
            None if end is None else round(end, SPAN_PRECISION),
        )
    )
    updates: dict[str, Any] = {
        "stem": stem,
        "region": region,
        # The second-voice overlay is OFF; see the GUI's review_config.
        "piano_second_voice": False,
    }
    if ensemble is not None:
        updates["ensemble"] = ensemble
    # Which detector supplies a pianist's line (issue #8). Part of the key
    # because it changes every note; a horn's review ignores it, and the
    # default leaves the key exactly as it was (TranscribeConfig's serializer).
    if line is not None:
        updates["piano_line"] = line
    return config.model_copy(update={"transcribe": config.transcribe.model_copy(update=updates)})


# One content hash per stem file per process. `review_key` is called on
# endpoints documented as cheap to poll, and these files are ~80MB.
_STEM_DIGESTS: dict[tuple[str, int, int], str] = {}


def stem_file_digest(path: str | Path) -> str:
    """sha256 of a separated stem's CONTENT, memoized on (path, size, mtime).

    Content rather than (size, mtime) themselves, because CLAUDE.md's own
    advice is to COPY a stem between cache directories rather than re-separate
    it: a copy changes mtime while the audio is identical, and keying on mtime
    would throw away a perfectly good review — and a minute of CREPE — for it.
    A copy costs one re-hash and yields the same key; a genuine
    re-separation yields a different one, which is the case that matters.
    """
    file = Path(path)
    stat = file.stat()
    memo = (str(file), stat.st_size, stat.st_mtime_ns)
    digest = _STEM_DIGESTS.get(memo)
    if digest is None:
        hasher = hashlib.sha256()
        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()[:16]
        _STEM_DIGESTS[memo] = digest
    return digest


def review_key(document: Document, config: Config, model: str) -> str:
    """Content key for a transcription review: the stem's identity, the model
    that produced it, every transcribe setting that would change a note, and
    the STEM FILE's own content.

    That last part is load-bearing, not defensive. Confirmed 2026-08-29:
    htdemucs_6s separation is NOT bit-reproducible across independent runs of
    the identical audio on this machine -- two runs produced `other.wav`s
    that differed from their first sample, same length, different SHA256.
    transcribe.analyze() itself IS perfectly deterministic given a fixed
    stem (also confirmed), so once a stem file exists, everyone reading it
    gets the same notes forever -- but `stem_digest` only hashes the SOURCE
    audio, never the stem `separate.run` actually produced from it. If that
    stem is ever regenerated under an unchanged config (a cleared cache, a
    debugging session pointing separate at a different cache_dir and back),
    every review key computed against the old bytes still matches, and a
    stale review keeps being served indistinguishably from a fresh one.
    Hashing the stem makes a changed stem a cache MISS instead.
    """
    source_digest = library.stem_digest(document)
    tc = canonical_json(config.transcribe.model_dump(mode="json"))
    stem_path = library.resolve_stem(document, config, model, config.transcribe.stem)
    stem_signature = stem_file_digest(stem_path) if stem_path else "unseparated"
    raw = f"{source_digest}\x00{model}\x00{tc}\x00{stem_signature}"
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
        # The piano review overlay: the rest of the top two notes the oracle
        # heard (M7b). A SEPARATE key, not more entries in "notes", because
        # everything that scores, exports or erases treats "notes" as the
        # transcription — mixing them would put a review aid into every
        # measurement.
        "second_voice": [
            {
                "onset": round(float(n["onset"]), _ROUND),
                "duration": round(float(n["duration"]), _ROUND),
                "pitch": int(n["pitch"]),
                "confidence": round(float(n.get("velocity", 0)) / 127.0, _ROUND),
            }
            for n in getattr(diagnostics, "second_voice", []) or []
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
    stem_path = library.resolve_stem(document, config, model, stem)
    if stem_path is None:
        available = ", ".join(library.selectable_stems(document, config, model))
        raise ValueError(f"no {stem!r} stem for {model}; available: {available or 'none'}")

    notes, diagnostics = transcribe.analyze(stem_path, config.transcribe)
    payload = _payload(notes, diagnostics)
    _cache(config).put_json(review_key(document, config, model), payload)
    return payload
