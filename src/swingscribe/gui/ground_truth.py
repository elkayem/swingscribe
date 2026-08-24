"""A hand transcription drawn against ours, note by note.

The benchmark harness scores three solos against MuseScore transcriptions and
prints numbers. Numbers say *how much* is wrong; they cannot say *what kind*.
A spurious note one semitone from a real one is the soloist's own scoop; one
fifteen semitones below is a different instrument playing. Those need
completely different fixes, they are nearly impossible to tell apart in a
table, and they are obvious on a piano roll. This module produces what the
roll draws.

Everything here is presentation over `mscz` and `alignment`; no scoring is
reimplemented (CLAUDE.md — `alignment.py` is the source of truth for the
time-free comparison, `metrics.py` for anything in time).

## Two things this gets right on purpose

**The transposition is measured, never assumed.** A hand transcription may be
written an octave or more from concert pitch for readability — both benchmark
tenor solos are +12 — and our own tracker makes octave errors. In a raw score
those look identical. Scored without detecting it, Confirmation reads 0.121
instead of 0.736, so this is not a refinement; it decides whether anything
displayed means anything. The detected offset is reported so it can be seen.

**A notated score has no timestamps, so we never invent them.** Bar 1 is the
start of the span and the tempo follows from bars/span, but that constant-
tempo assumption drifts — up to 1.9s over one solo, which is six beats. So
horizontal position comes from the ALIGNMENT instead: every notated note that
aligned to one of ours inherits that note's real onset, needing no tempo at
all, and unaligned notes are interpolated between their neighbouring anchors.
Constant tempo survives only as the fallback outside the outermost anchors.

The consequence is worth stating plainly, and the UI states it too: an aligned
pair sits at the same x BY CONSTRUCTION. This view cannot be read as evidence
about timing. Onset timing has its own measurement in
`scripts/score_benchmark.py`; this one answers pitch and identity. `drift_s`
reports how far the alignment-derived placement had to move the score away
from constant tempo, which is the honest statement of what a naive placement
would have got wrong.

Nothing read here may be committed — these scores are derivative works of
commercial recordings (plan §12).
"""

import bisect
import hashlib
import re
from pathlib import Path
from typing import Any

from swingscribe import mscz
from swingscribe.alignment import align, best_transposition
from swingscribe.cache import StageCache
from swingscribe.config import Config

SCORE_SUFFIXES = frozenset({".mscz", ".mscx"})

# Prefix sizes for narrowing the transposition search. A full 49-candidate
# search over ~900 notes each side is minutes of pure Python; the offset is
# constant, so a prefix settles it. Matches scripts/score_benchmark.py.
HEAD_REFERENCE = 120
HEAD_ESTIMATE = 160

_WORD = re.compile(r"[a-z0-9]+")
# Words that appear in nearly every filename and so carry no evidence about
# which score belongs to which track.
_STOPWORDS = frozenset(
    {"solo", "on", "the", "a", "an", "of", "transcription", "take", "mscz", "mscx"}
)


def is_score(path: Path) -> bool:
    return path.suffix.lower() in SCORE_SUFFIXES


def _tokens(name: str) -> set[str]:
    return {w for w in _WORD.findall(name.lower()) if w not in _STOPWORDS and not w.isdigit()}


def nearby_scores(audio_path: str | Path) -> list[dict[str, Any]]:
    """Score files beside the track, best name match first.

    Name matching is a ranking, never a decision: the benchmark's scores are
    named after the soloist ("Dexter_Gordon_solo_on_Confirmation.mscz") and the
    audio after the album track ("02 Confirmation.m4a"), so a stem-equality
    test would find nothing while shared-word overlap ranks it first. A folder
    holding several tunes is the normal case, so the user picks; this only
    decides what to offer first, and `matched` marks the ones with real
    evidence behind them.
    """
    source = Path(audio_path)
    folder = source.parent
    if not folder.is_dir():
        return []
    wanted = _tokens(source.stem)
    found = []
    for candidate in folder.iterdir():
        try:
            if not candidate.is_file() or not is_score(candidate):
                continue
        except OSError:
            continue
        shared = wanted & _tokens(candidate.stem)
        found.append(
            {
                "name": candidate.name,
                "path": str(candidate),
                "shared": sorted(shared),
                "matched": bool(shared),
            }
        )
    found.sort(key=lambda c: (-len(c["shared"]), c["name"].lower()))
    return found


def score_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _monotone(anchors: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Anchors made strictly increasing in notated position.

    The alignment walks both sequences in order, so anchors arrive ordered
    already. Equal positions are still possible (a chord, or a second voice),
    and they would make an interpolation slope divide by zero, so the later of
    such a pair is dropped rather than special-cased at every use.
    """
    kept: list[tuple[float, float]] = []
    for position, time in anchors:
        if kept and position <= kept[-1][0]:
            continue
        kept.append((position, time))
    return kept


def _place(
    position: float,
    positions: list[float],
    times: list[float],
    fallback_rate: float,
    fallback_origin: float,
) -> tuple[float, float]:
    """Notated position (quarter notes) -> (seconds, local seconds-per-quarter).

    Piecewise-linear through the anchors, extrapolating off the outermost pair
    beyond them. This is a tempo map derived from the alignment: exact at every
    anchor, and it cannot accumulate drift because each anchor resets it.
    """
    n = len(positions)
    if n == 0:
        return fallback_origin + position * fallback_rate, fallback_rate
    if n == 1:
        return times[0] + (position - positions[0]) * fallback_rate, fallback_rate

    index = bisect.bisect_left(positions, position)
    if index <= 0:
        lo, hi = 0, 1  # before the first anchor — extrapolate off the opening pair
    elif index >= n:
        lo, hi = n - 2, n - 1  # past the last — extrapolate off the closing pair
    else:
        lo, hi = index - 1, index
    step = positions[hi] - positions[lo]
    rate = (times[hi] - times[lo]) / step if step > 0 else fallback_rate
    if rate <= 0:
        rate = fallback_rate  # a non-advancing pair says nothing about tempo
    return times[lo] + (position - positions[lo]) * rate, rate


def overlay(
    score_path: str | Path, notes: list[dict[str, Any]], start: float, end: float
) -> dict[str, Any]:
    """Align a notated score to transcribed notes and place both on one axis.

    `notes` are the review payload's notes (dicts with onset/duration/pitch) in
    whole-track seconds; [start, end] is the span they were transcribed from,
    which is also the span the score covers — bar 1 of the score is `start`.
    """
    score = mscz.parse(score_path)
    reference = score.pitches
    estimate = [int(n["pitch"]) for n in notes]
    span = max(1e-6, end - start)

    # Average tempo from the notation itself. Only ever a fallback for
    # placement (see the module docstring), but it is also the cross-check that
    # the span is the one the score was written against: a solo whose implied
    # tempo comes out at 90 or 400 bpm is a span mismatch, not a slow tune.
    quarters = max(1e-6, score.bars * score.beats_per_bar)
    seconds_per_quarter = span / quarters
    implied_bpm = 60.0 / seconds_per_quarter

    offset = 0
    if reference and estimate:
        coarse, _ = best_transposition(reference[:HEAD_REFERENCE], estimate[:HEAD_ESTIMATE])
        offset, _ = best_transposition(
            reference[:HEAD_REFERENCE],
            estimate[:HEAD_ESTIMATE],
            search=range(coarse - 2, coarse + 3),
        )
    aligned = align(reference, [p + offset for p in estimate])

    # ── classify ──────────────────────────────────────────────────────────
    # The four classes fall straight out of the alignment path: a pair is
    # matched or a wrong note, a lone estimate is invented, a lone reference
    # was missed.
    ref_class: list[str] = ["missed"] * len(reference)
    ref_partner: list[int | None] = [None] * len(reference)
    est_class: list[str] = ["invented"] * len(estimate)
    est_partner: list[int | None] = [None] * len(estimate)
    anchors: list[tuple[float, float]] = []
    for ri, ei in aligned.pairs:
        if ri is None or ei is None:
            continue
        kind = "matched" if reference[ri] == estimate[ei] + offset else "wrong"
        ref_class[ri], est_class[ei] = kind, kind
        ref_partner[ri], est_partner[ei] = ei, ri
        anchors.append((score.notes[ri].position, float(notes[ei]["onset"])))

    anchors = _monotone(anchors)
    positions = [p for p, _ in anchors]
    times = [t for _, t in anchors]

    # ── place the score horizontally ──────────────────────────────────────
    reference_notes = []
    drifts = []
    for index, note in enumerate(score.notes):
        x, rate = _place(note.position, positions, times, seconds_per_quarter, start)
        drifts.append(x - (start + note.position * seconds_per_quarter))
        reference_notes.append(
            {
                "x": round(x, 3),
                "duration": round(note.duration * rate, 3),
                "pitch": note.pitch - offset,  # concert, to share our pitch axis
                "written": note.pitch,
                "bar": note.bar,
                "cls": ref_class[index],
                "partner": ref_partner[index],
            }
        )

    return {
        "score": {
            "name": Path(score_path).name,
            "path": str(score_path),
            "title": score.title,
            "bars": score.bars,
            "beats_per_bar": score.beats_per_bar,
            "implied_bpm": round(implied_bpm, 1),
            "transposition": offset,
            "anchors": len(anchors),
            # How far the alignment had to move the score away from constant
            # tempo — i.e. what a naive placement would have got wrong.
            "drift_s": round(max(drifts) - min(drifts), 2) if drifts else 0.0,
        },
        "counts": {
            "matched": aligned.matches,
            "wrong": aligned.substitutions,
            "invented": aligned.insertions,
            "missed": aligned.deletions,
            "reference": len(reference),
            "estimate": len(estimate),
        },
        "pitch_f1": round(aligned.f1, 3),
        "precision": round(aligned.precision, 3),
        "recall": round(aligned.recall, 3),
        "reference_notes": reference_notes,
        "estimate_class": est_class,
        "estimate_partner": est_partner,
    }


def _cache(config: Config) -> StageCache:
    return StageCache(Path(config.cache_dir) / "gui" / "overlays")


def overlay_key(review_key: str, score_path: str | Path) -> str:
    """One overlay per (transcription, score file). Both sides are content-
    keyed, so re-notating a bar and re-transcribing the span both miss."""
    raw = f"{review_key}\x00{score_digest(score_path)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cached_overlay(
    config: Config,
    review_key: str,
    score_path: str | Path,
    notes: list[dict[str, Any]],
    start: float,
    end: float,
) -> dict[str, Any]:
    """The overlay for this transcription and score, computing it on a miss.

    Needleman-Wunsch over two ~900-note sequences is a few seconds of pure
    Python — fine once, tiresome on every toggle of a class, hence the cache.
    """
    cache = _cache(config)
    key = overlay_key(review_key, score_path)
    stored = cache.get_json(key)
    if stored is not None:
        return stored
    computed = overlay(score_path, notes, start, end)
    cache.put_json(key, computed)
    return computed
