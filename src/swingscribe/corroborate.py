"""Two detectors, one question: did that note actually happen?

The monophonic path (CREPE f0 + spectral-flux onsets) and a polyphonic piano
model are independent — different features, different architectures, different
failure modes. A note both of them report is very unlikely to be a
hallucination of either, and a note only one reports deserves suspicion.

That distinction matters here more than it looks, because "a note the hand
transcription does not contain" covers two completely different things:

- **we invented it.** On Orbits, CREPE follows the upright bass through the
  `other` stem's bleed: the notes the listener deleted sit a median of 17
  semitones below the melody and the piano model reports 0% of them, because
  a piano model correctly declines to call a double bass a piano.
- **it is real and out of scope.** The hand transcriptions notate the right
  hand only. On the Peterson, the deleted notes are 90% corroborated — they
  happened, they are just the left hand, which nobody asked for.

Only the first is a transcription error. Scoring them together is what makes
a working transcriber look broken, and telling them apart needs no ground
truth at all — just the second opinion.

Everything here is pure numpy over plain note dicts, so it runs in CI. The
model that produces the second opinion lives in `piano.py`.
"""

from typing import Any

import numpy as np

# How far apart two detectors may place the same note and still be talking
# about it. Generous on purpose: they segment onsets by different means, and
# 0.05s measured tighter precision at a real cost in recall while 0.20s let
# unrelated neighbours vouch for each other. 0.10 was the best of the three on
# both piano solos with hand transcriptions (docs/m7b-piano.md).
ONSET_TOLERANCE = 0.10


def _arrays(notes: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    if not notes:
        return np.zeros(0), np.zeros(0, dtype=int)
    return (
        np.array([float(n["onset"]) for n in notes]),
        np.array([int(n["pitch"]) for n in notes]),
    )


def corroborate(
    notes: list[dict[str, Any]],
    oracle: list[dict[str, Any]],
    onset_tolerance: float = ONSET_TOLERANCE,
) -> np.ndarray:
    """For each note, did the oracle independently report the same pitch there?

    Exact pitch, not pitch class: an octave disagreement is a real
    disagreement, and `snap_octaves` is where that case is handled rather than
    waved through.
    """
    onsets, pitches = _arrays(notes)
    o_onsets, o_pitches = _arrays(oracle)
    found = np.zeros(len(notes), dtype=bool)
    if not len(notes) or not len(oracle):
        return found
    for index in range(len(notes)):
        near = np.abs(o_onsets - onsets[index]) <= onset_tolerance
        found[index] = bool(np.any(near & (o_pitches == pitches[index])))
    return found


def snap_octaves(
    notes: list[dict[str, Any]],
    oracle: list[dict[str, Any]],
    onset_tolerance: float = ONSET_TOLERANCE,
) -> list[dict[str, Any]]:
    """Move a note to the oracle's octave where the two agree on pitch CLASS.

    23% of our pitch errors on piano are exact octaves (docs/benchmark-
    deficiencies.md D4). CREPE infers the octave from a harmonic stack and can
    take the wrong rung of it; a polyphonic model decides per key and does not
    fail that way. So where the two name the same note and disagree only about
    where it lives, the oracle wins.

    Notes the oracle says nothing about are returned untouched — this only
    corrects, it never rejects. Rejecting is `corroborate`'s job, and keeping
    them separate is what lets the measurement attribute the gain: snapping
    raises RECALL (a note at the right octave now matches), corroboration
    raises PRECISION.
    """
    o_onsets, o_pitches = _arrays(oracle)
    if not len(oracle):
        return list(notes)
    out: list[dict[str, Any]] = []
    for note in notes:
        near = np.abs(o_onsets - float(note["onset"])) <= onset_tolerance
        pitch = int(note["pitch"])
        if np.any(near & (o_pitches == pitch)):
            out.append(note)  # already agreed on; nothing to correct
            continue
        same_class = near & (((o_pitches - pitch) % 12) == 0)
        if np.any(same_class):
            candidates = o_pitches[same_class]
            nearest = int(candidates[np.argmin(np.abs(candidates - pitch))])
            out.append({**note, "pitch": nearest})
        else:
            out.append(note)
    return out


def apply(
    notes: list[dict[str, Any]],
    oracle: list[dict[str, Any]],
    onset_tolerance: float = ONSET_TOLERANCE,
    snap: bool = True,
    reject: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Correct octaves, then drop what the oracle will not vouch for.

    Order matters: snapping first gives a note at the wrong octave the chance
    to be corrected rather than thrown away, which is worth more than it costs
    — measured over both piano solos, snapping then rejecting beat rejecting
    alone on precision AND recall.
    """
    before = [int(n["pitch"]) for n in notes]
    working = snap_octaves(notes, oracle, onset_tolerance) if snap else list(notes)
    moved = sum(1 for a, n in zip(before, working, strict=True) if a != int(n["pitch"]))
    found = corroborate(working, oracle, onset_tolerance)
    kept = [n for n, ok in zip(working, found, strict=True) if ok] if reject else working
    return kept, {
        "input": len(notes),
        "octaves_snapped": moved,
        "uncorroborated": int((~found).sum()),
        "kept": len(kept),
    }
