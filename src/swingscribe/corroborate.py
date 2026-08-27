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


# How close two oracle notes must be to count as struck together. Tighter than
# ONSET_TOLERANCE on purpose: this groups one detector's own output, where a
# chord really is simultaneous, rather than reconciling two detectors that
# segment differently.
CLUSTER_TOLERANCE = 0.05


def second_voice(
    notes: list[dict[str, Any]],
    oracle: list[dict[str, Any]],
    onset_tolerance: float = ONSET_TOLERANCE,
    cluster_tolerance: float = CLUSTER_TOLERANCE,
) -> list[dict[str, Any]]:
    """The rest of the top TWO notes the oracle heard — a review aid, not a line.

    The listener's workflow for piano is not "pick the melody for me", it is
    "show me the top one or two notes and I will delete the rest". That makes
    RECALL the target, and recall is where the oracle is strong: the top two of
    each simultaneity hold the note a human notated 84-96% of the time, against
    0.54-0.74 for the monophonic line alone (docs/m7b-piano.md).

    It is deliberately taken from the oracle's own clustering rather than
    relative to our note, because the case that most needs it is the one where
    our note is WRONG: over Soul Station's block-chord ending we track an inner
    voice an octave under the melody (D8), so the note worth showing is the one
    ABOVE ours, not below.

    Whatever is already in `notes` is left out, so this is only what the review
    screen is not showing yet.

    NOT part of the transcription. It never enters the scored note list — it
    rides on FrameDiagnostics, which nothing downstream consumes — because
    doubling the note count would halve precision on every benchmark while
    describing the same playing.
    """
    if not oracle:
        return []
    ordered = sorted(oracle, key=lambda n: (float(n["onset"]), -int(n["pitch"])))
    top_two: list[dict[str, Any]] = []
    cluster: list[dict[str, Any]] = []
    for note in ordered:
        if cluster and float(note["onset"]) - float(cluster[0]["onset"]) > cluster_tolerance:
            top_two += sorted(cluster, key=lambda n: -int(n["pitch"]))[:2]
            cluster = []
        cluster.append(note)
    top_two += sorted(cluster, key=lambda n: -int(n["pitch"]))[:2]

    if not notes:
        return top_two
    onsets, pitches = _arrays(notes)
    out = []
    for note in top_two:
        near = np.abs(onsets - float(note["onset"])) <= onset_tolerance
        if not np.any(near & (pitches == int(note["pitch"]))):
            out.append(note)
    return out


# A note the oracle heard counts as "already ours" if the line has anything at
# all within this of it. Onset-only, deliberately: the point is to fill HOLES
# in the line, and a hole is a stretch of time with nothing in it, whatever
# pitch we would have put there.
GAP_TOLERANCE = 0.06

# How far from the line's local register an oracle note may sit and still be
# plausibly the same voice. An octave is loose enough to catch a leap and
# tight enough to leave the left hand where it is.
REGISTER_SEMITONES = 12

# Half a second either side is roughly a bar at bebop tempo — enough context to
# know what register the line is in without averaging across a phrase that
# moved.
REGISTER_WINDOW = 1.0

# The oracle's velocity, normalised, as a confidence. Below this its notes are
# as likely to be pedal ring or a neighbour's overtone as a struck note.
FILL_CONFIDENCE = 0.45

# Our note durations are the GATED extent of a pitch, not the played length:
# CREPE's periodicity collapses at each transition, so a note's frames run
# past where the next note starts. Taking half the claimed duration is what
# stops a line note from covering the hole immediately after it.
COVER_FRACTION = 0.5


def _velocity_confidence(note: dict[str, Any]) -> float:
    """The oracle reports velocity, the line reports confidence. One scale."""
    if "velocity" in note:
        return float(note["velocity"]) / 127.0
    return float(note.get("confidence", 0.0))


def fill_gaps(
    notes: list[dict[str, Any]],
    oracle: list[dict[str, Any]],
    gap_tolerance: float = GAP_TOLERANCE,
    register: int = REGISTER_SEMITONES,
    window: float = REGISTER_WINDOW,
    min_confidence: float = FILL_CONFIDENCE,
    cover_fraction: float = COVER_FRACTION,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Notes the oracle heard where our line has a HOLE, merged into the line.

    This is the second opinion used the way the listener asked for it: one
    monophonic line, as complete as we can make it, rather than a second voice
    to read past. `second_voice` shows the top two of every simultaneity, which
    is most of the left hand; this shows only what fills a silence in the line
    we already have, at the register the line is already in.

    Measured over four piano solos with hand transcriptions, against the
    monophonic line alone: recall 0.680 -> 0.744 for precision 0.677 -> 0.666.
    Every one of the four improved on recall AND F1 (docs/m7b-piano.md). That
    ratio is the point — the listener deletes what does not belong far more
    cheaply than they can hear a note that was never written.

    Three tests, and each earns its place:

    - a HOLE, not a disagreement. If the line already has a note here we keep
      ours; correcting a wrong pitch is `snap_octaves`' job, and doing it here
      would put two notes on one beat in a single-line score.
    - the line's REGISTER. Without it the left hand walks straight in — this
      is the same rule that keeps a bass line out of the melody, applied to
      the same signal.
    - the oracle's VELOCITY. Its quietest reports are pedal ring and sympathetic
      resonance; the melody is rarely the softest thing sounding.

    HORNS MUST NEVER REACH THIS. A piano model asked about a saxophone vouches
    for nothing, so every hole would be filled with nothing, and the register
    test would then be measuring noise. `TranscribeConfig.uses_piano_oracle`
    is the gate — see `stages/transcribe.py`.
    """
    if not oracle or not notes:
        return list(notes), {"input": len(notes), "filled": 0, "kept": len(notes)}

    onsets, pitches = _arrays(notes)
    order = np.argsort(onsets)
    onsets, pitches = onsets[order], pitches[order]
    ends = onsets + np.array([float(notes[i].get("duration", 0.0)) for i in order]) * cover_fraction

    filled: list[dict[str, Any]] = []
    for note in second_voice(notes, oracle):
        if _velocity_confidence(note) < min_confidence:
            continue
        onset = float(note["onset"])
        if np.min(np.abs(onsets - onset)) < gap_tolerance:
            continue
        if np.any((onsets <= onset) & (onset < ends)):
            continue
        near = (onsets >= onset - window) & (onsets <= onset + window)
        if not np.any(near):
            continue
        if abs(int(note["pitch"]) - float(np.median(pitches[near]))) > register:
            continue
        filled.append(
            {
                "onset": onset,
                "duration": float(note["duration"]),
                "pitch": int(note["pitch"]),
                "confidence": _velocity_confidence(note),
            }
        )
    merged = sorted([*notes, *filled], key=lambda n: float(n["onset"]))
    return merged, {"input": len(notes), "filled": len(filled), "kept": len(merged)}
