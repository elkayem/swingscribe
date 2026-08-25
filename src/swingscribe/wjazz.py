"""Lining a WJazzD solo up with our transcription of the same recording.

WJazzD annotates note onsets in seconds against its own copy of a recording.
Ours come from the user's copy. Two CD issues of one master can differ in
where the track starts and, by a few tenths of a percent, in playback speed,
so before anything can be scored the two have to be put on one clock.

That is two parameters -- offset and rate -- for a whole solo, and it has
been got wrong twice, which is why it lives here with tests instead of inside
the script. Both failures were the same shape: an offset search anchored
somewhere the true answer was not, reporting a confident wrong alignment that
looked like a transcription failure. The second one made a 0.84 solo read as
0.51.

The control that says the fit is not manufacturing agreement is in the
scoring script: run against the WRONG take, these same two parameters achieve
under 10% (docs/benchmark-deficiencies.md).

numpy is imported inside functions, as everywhere else in this project, so
importing this module costs nothing in CI (CLAUDE.md).
"""

import re

ONSET_TOLERANCE_S = 0.05
# Below this share of the reference matched, we have not found the take. A
# wrong candidate lands at 2-7% from note density alone; a right one at 20%+.
MIN_MATCH_RATE = 0.15
# ...and the runner-up must be this far behind, or the identification is not
# safe enough to score against.
MIN_MARGIN = 2.5
# Above this, a candidate is certainly present in the audio and the margin
# rule does not apply to it. A wrong take reaches 10% on note density alone,
# so 40% is not a near miss -- it is a solo we transcribed.
#
# This exists because a span can hold more than one annotated solo. The user's
# Dolores covers Herbie Hancock, Miles Davis and Wayne Shorter in turn; two of
# them matched at 77% and 73%, and the margin rule threw away BOTH on the
# grounds that they could not be told apart. They could: they are both there.
CONFIDENT_MATCH_RATE = 0.40
STOPWORDS = frozenset({"the", "a", "an", "of", "on", "solo", "and"})
RATE_LOW, RATE_HIGH, RATE_STEP = 0.994, 1.006, 0.0005


def title_tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in STOPWORDS and len(w) > 2}


def _matches(ref_on, ref_p, est_on, est_p, offset, rate):
    """Boolean per reference note: does one of ours sit on it, same pitch?"""
    import numpy as np

    t = ref_on * rate + offset
    index = np.searchsorted(est_on, t)
    hit = np.zeros(len(t), dtype=bool)
    for step in (-1, 0, 1):
        j = np.clip(index + step, 0, len(est_on) - 1)
        hit |= (np.abs(est_on[j] - t) <= ONSET_TOLERANCE_S) & (est_p[j] == ref_p)
    return hit


ANCHOR_NOTES = 60  # reference notes per end-anchor; ~15s of playing


def _best_offset(ref_on, ref_p, est_on, est_p, low, high, step):
    import numpy as np

    best = (0.0, -1)
    for offset in np.arange(low, high, step):
        n = int(_matches(ref_on, ref_p, est_on, est_p, offset, 1.0).sum())
        if n > best[1]:
            best = (float(offset), n)
    return best


def fit_affine(ref_on, ref_p, est_on, est_p, region):
    """(offset, rate, matches) lining their solo up with our notes.

    The rate is *derived*, not searched. Searching offset and rate jointly
    needs an anchor for the offset window, and every cheap anchor is wrong in
    the case that matters: when two issues really do differ in speed, no
    single offset fits the whole solo, so the rate-1.0 fit anchors the search
    in the wrong place. That cost 162 matches on Yesterdays.

    Instead each end of the solo is located on its own, over the full range of
    offsets that would put the reference anywhere inside our span at all — no
    seed guess, so nothing to get wrong. A short window is immune to rate
    error (0.6% over 15 seconds is 90ms, and these anchor on a 50ms
    criterion), and two located ends give the rate by subtraction. A joint
    refinement then cleans up.

    Pitch is part of the criterion throughout: an onset-only fit on a jazz
    line can lock onto a whole eighth-note slip, which is the bug that made
    the other benchmark wrong for months (src/swingscribe/benchmark.py).
    """
    import numpy as np

    # Every offset for which their solo overlaps our span by any amount.
    low = region[0] - float(ref_on[-1])
    high = region[1] - float(ref_on[0])

    head = slice(0, min(ANCHOR_NOTES, len(ref_on) // 3))
    tail = slice(max(0, len(ref_on) - ANCHOR_NOTES), len(ref_on))
    head_offset, _ = _best_offset(ref_on[head], ref_p[head], est_on, est_p, low, high, 0.01)
    tail_offset, _ = _best_offset(ref_on[tail], ref_p[tail], est_on, est_p, low, high, 0.01)
    t_head = float(np.mean(ref_on[head]))
    t_tail = float(np.mean(ref_on[tail]))

    rate = 1.0
    if t_tail - t_head > 10.0:
        drift = (tail_offset - head_offset) / (t_tail - t_head)
        rate = min(RATE_HIGH, max(RATE_LOW, 1.0 + drift))
    offset = head_offset - (rate - 1.0) * t_head

    best = (offset, rate, int(_matches(ref_on, ref_p, est_on, est_p, offset, rate).sum()))
    for trial_rate in np.arange(rate - 4 * RATE_STEP, rate + 4.5 * RATE_STEP, RATE_STEP):
        centre = head_offset - (trial_rate - 1.0) * t_head
        for trial in np.arange(centre - 0.15, centre + 0.15, 0.002):
            n = int(_matches(ref_on, ref_p, est_on, est_p, trial, trial_rate).sum())
            if n > best[2]:
                best = (float(trial), float(trial_rate), n)
    return _centre(ref_on, ref_p, est_on, est_p, *best)


def _centre(ref_on, ref_p, est_on, est_p, offset, rate, hits):
    """Move the fit to the middle of the plateau it is sitting on.

    Maximizing a count under a hard tolerance is flat-topped: every offset
    within about a tolerance of the truth matches the same notes, so the
    search returns an arbitrary member of that set -- in practice the lowest,
    which lands ~30ms early. That is a third of the 50ms criterion given away
    for nothing, and it also makes any per-note timing residual read as bias
    that is really the fit's.

    So the matched pairs get the last word: shift by the median residual, the
    same robust centring the .mscz benchmark uses (src/swingscribe/benchmark.py),
    and keep it only if it does not lose matches.
    """
    import numpy as np

    for _ in range(2):
        t = ref_on * rate + offset
        index = np.clip(np.searchsorted(est_on, t), 0, len(est_on) - 1)
        residuals = []
        for step in (-1, 0, 1):
            j = np.clip(index + step, 0, len(est_on) - 1)
            ok = (np.abs(est_on[j] - t) <= ONSET_TOLERANCE_S) & (est_p[j] == ref_p)
            residuals.extend((est_on[j] - t)[ok].tolist())
        if len(residuals) < 10:
            break
        moved = offset + float(np.median(residuals))
        n = int(_matches(ref_on, ref_p, est_on, est_p, moved, rate).sum())
        if n < hits:
            break
        offset, hits = moved, n
    return offset, rate, hits


def notated_positions(db, melid: int) -> list[tuple[float, int]]:
    """(metrical position in quarter notes, pitch) for one WJazzD solo.

    WJazzD annotates every note's place in the bar, not just its time:
    `bar`, `beat`, and `tatum` out of `division` subdivisions of that beat.
    So it carries a human's NOTATION as well as a human's onsets, and the
    notation half is what tells whether we wrote a swung pair as two eighths
    or as a dotted eighth.

    That matters as a control rather than as more of the same. The three
    MuseScore solos are all bebop and all eighth-note lines, so a grid rule
    tuned on them can be rewarded for simply writing everything as eighths.
    These solos were annotated by different people from different recordings,
    and `division` runs 1 through 10 across the database.

    Position is returned relative to the solo's own first bar, since which of
    our bars is their bar one is not knowable and is not being asked.
    """
    rows = db.execute(
        "select bar, beat, tatum, division, period, pitch from melody "
        "where melid=? order by eventid",
        (melid,),
    )
    out = []
    for bar, beat, tatum, division, period, pitch in rows:
        if not period or bar is None:
            continue
        position = (bar - 1) * period + (beat - 1) + (tatum - 1) / max(1, division or 1)
        out.append((float(position), int(pitch)))
    if not out:
        return []
    origin = out[0][0]
    return [(position - origin, pitch) for position, pitch in out]
