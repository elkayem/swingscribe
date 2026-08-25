"""Notes the listener has marked as "heard correctly, but not the solo".

The obvious use is cleanup: a pianist comps with the left hand behind their own
right-hand solo, the transcriber picks those notes up correctly, and they are
not wanted in the transcription. That is a difference of *scope*, not a
transcription error — today the benchmark scores it as our mistake and it is
not one.

The valuable use is that every erasure is a labelled example: heard correctly,
not part of the solo, carrying its pitch, duration, confidence and — through
its neighbours — its register within the phrase. That is training signal for
melodic-line selection, the biggest open problem in the project (open-issue #8,
docs/m3-benchmark.md). So the file format matters as much as the interaction,
and nothing here ever silently throws a label away.

## Where they live

In the track's sidecar, `<track>.swingscribe.json`, beside the audio — never in
the cache. The cache is derived data that must stay safely deletable; an
erasure is a human judgement (CLAUDE.md). They key on absolute track time, so
one list serves the whole track and changing the span does not orphan them.

## Why they are not stored as note indices

Re-running transcribe with any config change renumbers every note, so an
erasure stored as "note #417" would later silence a *different* note — silently,
which is the worst kind of wrong. Each erasure therefore records what the note
*was* (onset, pitch, and a snapshot of duration and confidence so the label
survives even a transcription that can no longer be reproduced), and is matched
back by content.

Matching is done HERE and only here: the review screen and the A/B render both
resolve through this module, because two implementations would eventually
disagree about which note is silenced and the place that would show up is the
audio.
"""

from typing import Any

# How far a note may have moved and still be the same note. Ten milliseconds is
# the transcriber's frame hop, so a note that survives a config change usually
# lands within one or two frames; 30ms allows that without reaching the next
# note in a fast bebop line.
TOLERANCE_S = 0.03

# Every erasure means the same thing today. Recorded anyway so that a later
# kind — an obvious octave error, say — cannot be confused with this one when
# the set is read back as training data.
REASON = "not-solo"


def record(note: dict[str, Any], stem: str, model: str) -> dict[str, Any]:
    """One erasure, self-contained.

    Duration and confidence are snapshotted rather than looked up later: the
    transcription that produced them may not be reproducible once a threshold
    moves, and a label that cannot describe its own example is worth much less.
    """
    return {
        "onset": round(float(note["onset"]), 3),
        "pitch": int(note["pitch"]),
        "duration": round(float(note.get("duration", 0.0)), 3),
        "confidence": round(float(note.get("confidence", 0.0)), 3),
        "reason": REASON,
        "stem": stem,
        "model": model,
    }


def _in_span(erasure: dict[str, Any], span: tuple[float, float] | None) -> bool:
    """Is this erasure inside the span currently transcribed?

    Erasures outside it are not missing, just out of view — moving the span is
    routine, and reporting those as unmatched would cry wolf constantly.
    """
    if span is None:
        return True
    lo, hi = span
    return lo - TOLERANCE_S <= erasure.get("onset", -1.0) <= hi + TOLERANCE_S


def resolve(
    erasures: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    span: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Match stored erasures onto the current notes.

    Pitch must be exact and onset within TOLERANCE_S. Exact pitch is
    deliberate: if a re-transcription folds an octave differently, that should
    fail to match and be reported, not quietly silence a note in the wrong
    register.

    Candidate pairs are assigned greedily by ascending onset distance, one
    note per erasure and one erasure per note. That matters more than it
    looks — fragmentation routinely leaves two notes of the same pitch 60ms
    apart, and a first-match scan would claim whichever came first in the list
    rather than the nearer one.

    Returns the note indices to silence, and the erasures inside the span that
    matched nothing. Unmatched erasures are *reported*, never dropped.
    """
    candidates = []
    for ei, erasure in enumerate(erasures):
        pitch = erasure.get("pitch")
        onset = erasure.get("onset")
        if pitch is None or onset is None:
            continue
        for ni, note in enumerate(notes):
            if note["pitch"] != pitch:
                continue
            distance = abs(note["onset"] - onset)
            if distance <= TOLERANCE_S:
                candidates.append((distance, ei, ni))
    # (distance, erasure, note) sorts nearest-first and ties break on index, so
    # the same inputs always produce the same assignment.
    candidates.sort()

    claimed_notes: set[int] = set()
    claimed_erasures: set[int] = set()
    for _, ei, ni in candidates:
        if ei in claimed_erasures or ni in claimed_notes:
            continue
        claimed_erasures.add(ei)
        claimed_notes.add(ni)

    carried = [erasure for index, erasure in enumerate(erasures) if index not in claimed_erasures]
    return {
        "silenced": sorted(claimed_notes),
        # Everything that found no note, so the client can write the list back
        # without losing labels for spans it is not looking at. An erasure is
        # never dropped as a side effect of anything.
        "carried": carried,
        # The subset worth telling the user about: inside the span they are
        # looking at, and therefore genuinely missing rather than out of view.
        "unmatched": [e for e in carried if _in_span(e, span)],
        "stored": len(erasures),
    }


def audible(notes: list[dict[str, Any]], silenced: list[int] | set[int]) -> list[dict[str, Any]]:
    """The notes that should sound. Silenced notes stay visible on the roll —
    you have to be able to see what you cut — but they never reach a render."""
    drop = set(silenced)
    return [note for index, note in enumerate(notes) if index not in drop]
