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
