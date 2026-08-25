"""Placing a notated score in time so it can be scored against our notes.

A hand transcription has bars and beats, not seconds. To score onset timing
against one, its notes have to be given timestamps, and every way of doing
that embeds an assumption. This module holds the assumption, alone, where it
can be tested — because the previous version of it lived inside
`scripts/score_benchmark.py`, was never tested, and was wrong for months.

## The failure it exists to prevent

Place the score at a constant tempo and let each window slide to fit. The
obvious way to choose the slide is to search for the shift that maximizes
onset hits. That is wrong, and it fails silently.

Onsets carry no identity. In a bebop line of near-uniform eighth notes, a
shift of a whole eighth note lines almost as many onsets up as the truth
does. Measured on the three benchmark solos, that search slipped 12/32, 9/18
and 6/16 windows, and the slips clustered on INTEGER numbers of eighth notes
(-1, -3, -4, -5, -8) rather than spreading over a continuum — which is how
you tell a beat slip from real tempo drift.

A slipped window is the worst kind of wrong. It still scores full onset F1,
because the onsets do line up; but every note in it is compared against the
wrong notated note, so its note F1 goes to nearly zero. That produced the
benchmark's long-standing signature of note F1 ~0.33 against onset F1 ~0.60,
which was read as a transcription failure and was really a scoring bug.

## What it does instead

The correspondence comes from `alignment.align`, which matches our pitch
sequence to the notated one using no timing whatsoever. Each aligned pair
contributes one (ours - notated) delta, and a window's shift is the median of
its deltas: a robust location estimate over an independently-derived
correspondence, not a search over the number being reported. It cannot slip a
beat, because the pitches pin which note is which, and it cannot inflate the
score, because nothing is optimized against the score.

Pure Python, no numpy, so CI exercises it (CLAUDE.md).
"""

import statistics

# Aligned pairs a window needs before its own shift beats the whole solo's.
# Two points make a median that is really just a midpoint of noise.
MIN_ANCHORS_PER_WINDOW = 3


def anchor_map(
    pairs: list[tuple[int | None, int | None]],
    reference: list[int],
    estimate: list[int],
) -> dict[int, int]:
    """Reference index -> estimate index, for true matches only.

    A substitution pairs two notes that are *not* the same note, so it says
    nothing about where the reference sits in time and must not anchor it.
    `estimate` is expected already transposed into the reference's key.
    """
    return {
        ri: ei
        for ri, ei in pairs
        if ri is not None and ei is not None and reference[ri] == estimate[ei]
    }


def window_shift(deltas: list[float], fallback: float) -> float:
    """Where a window really sits, from its aligned pairs.

    A window with too few anchors falls back to the solo-wide shift rather
    than being dropped. That matters for honesty: a window we failed to
    transcribe has no anchors, and dropping it would remove our worst
    passages from the average instead of scoring them.
    """
    if len(deltas) < MIN_ANCHORS_PER_WINDOW:
        return fallback
    return statistics.median(deltas)


def solo_shift(deltas: list[float]) -> float:
    """The whole solo's shift — the fallback, and the constant-tempo error."""
    return statistics.median(deltas) if deltas else 0.0


# ── scoring the notation itself ──────────────────────────────────────────
#
# Everything above places a notated score in time so its ONSETS can be
# scored. That leaves the notation unmeasured: note values, where a note sits
# in its bar, whether a rhythm was written as a triplet or as two sixteenths.
# A score could be full of unreadable rhythm and move none of those numbers.
#
# This compares the two as notation, which needs no tempo map at all — both
# sides are already in quarter notes from their own bar one. The only unknown
# is where our bar one is relative to theirs, and that is one constant.

# How far apart two notated positions may be and still count as the same
# place. A thirty-second note: anything smaller is not a distinction a reader
# would draw, and anything larger would forgive a wrong note value.
NOTATION_TOLERANCE = 0.125


def merge_ties(notes: list) -> list[tuple[float, float, int]]:
    """Notated notes → (position, duration, pitch), tied groups merged.

    A tie is one note wearing two noteheads. The reference side merges them
    when parsing (`mscz.parse`), so ours has to as well or every tie reads as
    an extra note that the reference does not have.
    """
    merged: list[list] = []
    for position, duration, pitch, tie_stop in notes:
        if merged and tie_stop and merged[-1][2] == pitch:
            merged[-1][1] += duration
            continue
        merged.append([position, duration, pitch])
    return [(p, d, int(n)) for p, d, n in merged]


def score_notation(
    reference: list[tuple[float, float, int]],
    estimate: list[tuple[float, float, int]],
    pairs: list[tuple[int | None, int | None]],
) -> dict[str, float]:
    """How much of the notation we got right, given a pitch-level alignment.

    `pairs` comes from `alignment.align` on the two pitch sequences, so which
    note is which was decided without consulting rhythm at all — the same
    separation the onset benchmark relies on, and for the same reason.

    Two numbers, deliberately apart:

    - **rhythm** — is the gap to the next note the same? Written as an
      interval rather than as an absolute position, and that choice matters.
      Absolute positions need our bar one to be their bar one, and any
      disagreement about the total bar count then drifts and swamps the
      measurement: Confirmation notates 130 bars where the score has 129, and
      scoring absolute positions read 0.34 against 0.79 for the same notation
      measured as intervals. An interval is translation-invariant and cannot
      accumulate, so it measures the rhythm and not the alignment.
    - **value** — is it the same note value? A quarter written where a dotted
      eighth belongs has the right rhythm and the wrong value here.

    Note what neither number can see: a note the alignment did not match at
    all. This measures the notation of the notes we got, and says nothing
    about the notes we missed — `note_f1` is where that lives.
    """
    matched = [
        (ri, ei)
        for ri, ei in pairs
        if ri is not None and ei is not None and reference[ri][2] == estimate[ei][2]
    ]
    if not matched:
        return {"rhythm": 0.0, "value": 0.0, "n_matched": 0.0}

    # Consecutive matched pairs only: a gap that steps over a note one side
    # has and the other does not is not evidence about rhythm.
    intervals = 0
    correct = 0
    for (ri, ei), (next_ri, next_ei) in zip(matched, matched[1:], strict=False):
        if next_ri != ri + 1 or next_ei != ei + 1:
            continue
        intervals += 1
        theirs = reference[next_ri][0] - reference[ri][0]
        ours = estimate[next_ei][0] - estimate[ei][0]
        if abs(ours - theirs) <= NOTATION_TOLERANCE:
            correct += 1
    valued = sum(
        1 for ri, ei in matched if abs(estimate[ei][1] - reference[ri][1]) <= NOTATION_TOLERANCE
    )
    return {
        "rhythm": correct / intervals if intervals else 0.0,
        "value": valued / len(matched),
        "n_matched": float(len(matched)),
    }
