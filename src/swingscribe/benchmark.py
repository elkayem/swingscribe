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


# Fraction of the reference's notes that must line up before the rhythm and
# value numbers mean anything. MEASURED, not guessed: scoring every notation
# we can build against every hand transcription on disk gives coverage
# 0.69-0.74 on the two right pairings and 0.16-0.36 on fourteen wrong ones —
# no overlap, and a wide gap to sit in.
#
# Coverage is the discriminator and RHYTHM IS NOT. A wrong pairing still
# scores rhythm 0.077-0.583, and 0.583 is higher than All The Things reads on
# its own correct score (0.618). Both sides are eighth-note bebop lines, so
# most gaps are half a quarter note on both and agree by chance. A rhythm
# number shown without its coverage is a number that cannot tell you it is
# about the wrong tune — which is exactly the failure this project has hit
# twice (docs/benchmark-deficiencies.md R1, R2).
COVERAGE_FLOOR = 0.5

# Prefix sizes for the transposition search, matching gui/ground_truth.py and
# scripts/score_benchmark.py. The offset is constant, so a prefix settles it
# and a full search over ~900 notes each side is minutes of pure Python.
HEAD_REFERENCE = 120
HEAD_ESTIMATE = 160


def bar_starts(bars: list) -> list[float]:
    """Absolute position, in quarter notes, of each bar's first beat."""
    starts = []
    cursor = 0.0
    for bar in bars:
        starts.append(cursor)
        cursor += bar.time_signature[0] * 4.0 / bar.time_signature[1]
    return starts


def notation_notes(notation) -> list[tuple[float, float, int]]:
    """A Notation flattened to (quarter position, duration, pitch), ties merged.

    Rests are dropped: they carry no pitch, so the alignment has nothing to
    match them on, and the gap they occupy is already visible as the interval
    between the notes either side.
    """
    return merge_ties(
        [
            (start + note.beat, note.duration, note.pitch, note.tie_stop)
            for start, bar in zip(bar_starts(notation.bars), notation.bars, strict=True)
            for note in bar.notes
            if not note.is_rest
        ]
    )


def score_against_notation(notation, score) -> dict[str, float]:
    """Our Notation against a parsed `mscz.Score`, as notation.

    This is the measure that answers "would this notate the way a human
    notated it?", and it needs NO TEMPO MAP: both sides are already in quarter
    notes counted from their own bar one, and the single unknown -- which of
    our bars is their bar one -- is one constant that the interval-based
    rhythm measure is immune to by construction (see `score_notation`).

    Transposition is measured, never assumed. A hand transcription may be
    written an octave or more from concert pitch, and our own tracker makes
    octave errors; in a raw comparison those are indistinguishable. Scored
    without detecting it, Confirmation reads 0.121 where the truth is 0.736.

    Scored against `score.melody`, the top note of each chord. Our line is
    monophonic, so scoring it against every chord tone would charge us for
    notes a single-line score cannot hold (`mscz.Score`).
    """
    from swingscribe.alignment import align, best_transposition

    ours = notation_notes(notation)
    theirs = [(n.position, n.duration, n.pitch) for n in score.melody]
    if not ours or not theirs:
        return {"rhythm": 0.0, "value": 0.0, "n_matched": 0.0, "transposition": 0.0}

    their_pitches = [p for _, _, p in theirs]
    our_pitches = [p for _, _, p in ours]
    coarse, _ = best_transposition(their_pitches[:HEAD_REFERENCE], our_pitches[:HEAD_ESTIMATE])
    offset, _ = best_transposition(
        their_pitches[:HEAD_REFERENCE],
        our_pitches[:HEAD_ESTIMATE],
        search=range(coarse - 2, coarse + 3),
    )
    shifted = [(position, duration, pitch + offset) for position, duration, pitch in ours]
    aligned = align(their_pitches, [p for _, _, p in shifted])
    result = score_notation(theirs, shifted, aligned.pairs)
    coverage = result["n_matched"] / len(theirs)
    return {
        **result,
        "transposition": float(offset),
        "reference": float(len(theirs)),
        # How much of their score ours accounted for, and whether that is
        # enough for the rest of these numbers to be about the same music.
        "coverage": coverage,
        "trusted": coverage >= COVERAGE_FLOOR,
    }


def score_against_wjazz_notation(notation, positions: list[tuple[float, int]]) -> dict[str, float]:
    """Our Notation against WJazzD's METRICAL annotation, as notation.

    WJazzD gives every note a `bar`, a `beat`, and a `tatum` out of `division`
    subdivisions of that beat, so it carries a human's notation as well as a
    human's onsets — and it writes a swung pair as two eighths, which is
    exactly the convention we target. `wjazz.notated_positions` turns that into
    quarter notes from the solo's own bar one.

    Why this matters more than one more hand transcription: the MuseScore
    scores are ten solos, all bebop, all eighth-note lines, so a grid rule
    tuned on them can be rewarded for simply writing everything as eighths.
    WJazzD is 456 solos annotated by different people, and `division` runs 1
    through 10 across the database. It is the control that set cannot be.

    **Only `rhythm` is reported, and that is a property of the source.** WJazzD
    stores a note's metrical POSITION but not its notated VALUE — its
    `duration` column is performed seconds, not a note value — so there is
    nothing to compare a dotted eighth against. Returning a `value` here would
    be inventing one. `rhythm` is the interval question, and the interval
    question is the whole of "did we write the swing straight?"
    """
    from swingscribe.alignment import align, best_transposition

    ours = notation_notes(notation)
    if not ours or not positions:
        return {"rhythm": 0.0, "n_matched": 0.0, "transposition": 0.0, "coverage": 0.0}

    # A duration of zero on the reference side: `score_notation` reads it only
    # for `value`, which is not reported, and never for `rhythm`.
    theirs = [(position, 0.0, pitch) for position, pitch in positions]
    their_pitches = [p for _, p in positions]
    our_pitches = [p for _, _, p in ours]
    coarse, _ = best_transposition(their_pitches[:HEAD_REFERENCE], our_pitches[:HEAD_ESTIMATE])
    offset, _ = best_transposition(
        their_pitches[:HEAD_REFERENCE],
        our_pitches[:HEAD_ESTIMATE],
        search=range(coarse - 2, coarse + 3),
    )
    shifted = [(position, duration, pitch + offset) for position, duration, pitch in ours]
    aligned = align(their_pitches, [p for _, _, p in shifted])
    result = score_notation(theirs, shifted, aligned.pairs)
    coverage = result["n_matched"] / len(theirs)
    return {
        "rhythm": result["rhythm"],
        "n_matched": result["n_matched"],
        "transposition": float(offset),
        "reference": float(len(theirs)),
        "coverage": coverage,
        "trusted": coverage >= COVERAGE_FLOOR,
    }


# What a human actually writes. Counted over the ten hand transcriptions in
# benchmark/ -- 3646 notes and 487 rests, read straight out of the .mscz XML
# before ties are merged, so these are SYMBOLS ON A PAGE and not durations:
#
#   rests shorter than an eighth        6 of  487   1.2%
#   note values below a sixteenth      13 of 3646   0.4%
#   notes tied into the next          82 of 3646   2.2%
#   eighth notes                     2406 of 3646  66.0%
#
# The listener's complaint -- a sixteenth rest before a note played behind the
# beat, and "dotted 1/32 notes with strange ties" -- is exactly the first two
# rows, and NOTHING in `score_notation` could see it. `rhythm` asks whether the
# gap to the next note matches and `value` whether the note value matches; a
# page can be unreadable and move neither. Worse, `value` actively FIGHTS the
# repair: absorbing an unwritable rest into the note before it turns an eighth
# into a dotted eighth, which `value` scores as wrong (and by the count above
# a dotted eighth is genuinely rare -- 6 in 3646). That regression was real and
# was reported as the price of the fix, with no number on the other side of the
# ledger. This is that number.
#
# It needs no reference, so it runs over EVERY notation the harness can build
# -- the thirty-odd WJazzD solos as well as the ten hand-scored ones -- which
# is the widest measurement in this project.
WRITABLE_REST = 0.5  # an eighth; see notate.MIN_REST for the same threshold
WRITABLE_VALUE = 0.25  # a sixteenth


def _written_value(note) -> float:
    """The note value as a reader sees it, undoing any tuplet compression.

    A triplet eighth is stored as a third of a beat but READ as an eighth, and
    counting it as 0.333 would call ordinary swing notation unwritable.
    """
    if note.tuplet:
        actual, normal = note.tuplet
        return note.duration * actual / normal if normal else note.duration
    return note.duration


def readability(notation) -> dict[str, float]:
    """How much of a Notation is written the way a human writes it.

    Deliberately NOT a comparison. Every other number in this module asks
    whether we agree with a particular human about a particular recording;
    this one asks whether the page is *writable at all*, which is a property
    of the page alone.

    - **short_rests** -- rests below an eighth, per 100 events. The listener
      wrote 6 in 487. A gap this short is a player laying back, not a rest.
    - **short_values** -- notes written shorter than a sixteenth, per 100
      notes. These are the "dotted 1/32 notes with strange ties".
    - **tie_rate** -- notes tied into the next, as a fraction. A value that
      does not fit one symbol becomes several, so this rises with the two
      above; the human sits at 0.022.
    - **readability** -- the fraction of events that are neither. One number
      to move, anchored at the human's 0.995.

    Rates rather than counts, because a chorus and a whole solo would
    otherwise not be comparable.
    """
    notes = [n for bar in notation.bars for n in bar.notes if not n.is_rest]
    rests = [n for bar in notation.bars for n in bar.notes if n.is_rest]
    events = len(notes) + len(rests)
    if not events:
        return {
            "short_rests": 0.0,
            "short_values": 0.0,
            "tie_rate": 0.0,
            "readability": 0.0,
            "events": 0.0,
        }
    short_rests = sum(1 for r in rests if _written_value(r) < WRITABLE_REST - 1e-6)
    short_values = sum(1 for n in notes if _written_value(n) < WRITABLE_VALUE - 1e-6)
    tied = sum(1 for n in notes if n.tie_start)
    return {
        "short_rests": round(100.0 * short_rests / events, 3),
        "short_values": round(100.0 * short_values / len(notes), 3) if notes else 0.0,
        "tie_rate": round(tied / len(notes), 4) if notes else 0.0,
        "readability": round(1.0 - (short_rests + short_values) / events, 4),
        "events": float(events),
    }
