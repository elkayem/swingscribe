"""Lining a WJazzD solo up with our transcription of the same recording.

WJazzD annotates note onsets in seconds against its own copy of a recording.
Ours come from the user's copy. Two CD issues of one master can differ in
where the track starts and in playback speed — usually by tenths of a
percent, but a mastering fault can reach a few percent (Kind of Blue's side
1 is the famous one, and it is in this benchmark) — so before anything can
be scored the two have to be put on one clock.

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
from collections import Counter

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
# Real speed faults exceed a few tenths of a percent: the benchmark's So What
# runs 2.26% slower than the copy WJazzD annotated (the Kind of Blue side-1
# fault), and a clamp of ±0.6% held the fit at its ceiling and reported three
# right transcriptions as "wrong file/take" at 10% matched. The control that
# says widening does not manufacture agreement: with the rate freed, six
# known-wrong pairings stay at chance (1.5-6.9%), so MIN_MATCH_RATE keeps
# doing the gatekeeping (docs/benchmark-deficiencies.md D19).
RATE_LOW, RATE_HIGH, RATE_STEP = 0.97, 1.03, 0.0005


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
    seed guess, so nothing to get wrong. A short window degrades gracefully
    under rate error rather than failing: the notes near whatever instant the
    offset happens to pin still hit the 50ms criterion, and there are enough
    of them in 15 seconds of playing to beat chance (measured at the +2.26%
    So What fault: both anchors landed and the derived rate was within 0.05%
    of the truth). Two located ends give the rate by subtraction, and a joint
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
    and rate within about a tolerance of the truth matches the same notes, so
    the search returns an arbitrary member of that set -- an offset ~30ms
    early in practice, and a rate a step or two wide on a long solo, where a
    rate error spends the tolerance at the ends first. That is a third of the
    50ms criterion given away for nothing, and it also makes any per-note
    timing residual read as bias that is really the fit's.

    So the matched pairs get the last word on BOTH parameters: a least-squares
    line through their own times, the same "let the inliers refine the fit"
    move as the .mscz benchmark's centring (src/swingscribe/benchmark.py),
    kept only while it does not lose matches. Matches are pitch-verified and
    within the tolerance by construction, so the residuals are bounded and
    plain least squares is safe.
    """
    import numpy as np

    for _ in range(3):
        t = ref_on * rate + offset
        index = np.clip(np.searchsorted(est_on, t), 0, len(est_on) - 1)
        ref_t, est_t = [], []
        for step in (-1, 0, 1):
            j = np.clip(index + step, 0, len(est_on) - 1)
            ok = (np.abs(est_on[j] - t) <= ONSET_TOLERANCE_S) & (est_p[j] == ref_p)
            ref_t.extend(ref_on[ok].tolist())
            est_t.extend(est_on[j][ok].tolist())
        if len(ref_t) < 10:
            break
        slope, intercept = np.polyfit(np.asarray(ref_t), np.asarray(est_t), 1)
        slope = min(RATE_HIGH, max(RATE_LOW, float(slope)))
        n = int(_matches(ref_on, ref_p, est_on, est_p, float(intercept), slope).sum())
        if n < hits:
            break
        offset, rate, hits = float(intercept), slope, n
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


# A gap this long or shorter becomes the note's written value; anything
# longer is a note followed by a real rest. Two beats, because a lead sheet
# does not write articulation and WJazzD's `duration` is a human's note-off:
# see `notate.notated_durations`, which measured it on this database.
LEGATO_CAP = 2.0


def annotation_notation(db, melid: int, legato_fill: float = 0.75, legato_cap: float = LEGATO_CAP):
    """One WJazzD solo as a `Notation` -- a score, not a list of onsets.

    ## Why this is possible, having once been said not to be

    An earlier reading of this database said a notated score could not be built
    from it, because `melody.duration` is performed seconds and there is no
    column holding a note VALUE. The first half is true and the second half is
    the wrong conclusion. In a single line the written value of a note is the
    metrical distance to the next one, less any rest -- and the metrical
    positions are all here, exactly: `bar`, `beat`, and `tatum` out of that
    beat's own `division`. Nothing is missing. The Jazzomat project's own PDF
    lead sheets are rendered from these same columns.

    ## What it therefore is, and is not

    The POSITIONS and the PITCHES are a human's, and are independent evidence.
    The rests and note values are OURS: the gap-to-value rule
    (`notate.notated_durations`), the rest floor (`notate.MIN_REST`) and the
    tuplet grouping are the ones this project ships, applied to a human's grid.

    So this is a proper ground truth for *what was played and where it sits in
    the bar*, and it is NOT independent evidence about note values -- scoring
    our `value` against it would be scoring our conventions against themselves.
    That is the honest version of the earlier objection, and it is why
    `score_against_wjazz_notation` still reports rhythm only.

    ## Bar numbers are WJazzD's own

    Not renumbered from 1. The whole point of the file is to be laid beside
    the Jazzomat lead sheet for the same solo, and a score whose bar 3 is
    their bar 5 cannot be. WJazzD numbers a pickup 0 or -1 and this keeps
    that, so bar N here is bar N there.

    ODbL: WJazzD is share-alike, so a file written from this is a derivative
    of the database and must stay out of this repository (CLAUDE.md, plan §12).
    """
    from swingscribe.model import MeterSection, QuantizedNote
    from swingscribe.stages import notate

    rows = list(
        db.execute(
            "select bar, beat, tatum, division, num, denom, beatdur, duration, pitch "
            "from melody where melid=? order by eventid",
            (melid,),
        )
    )
    rows = [r for r in rows if r[0] is not None]
    if not rows:
        return None

    # The time signature the annotator used. Taken as the majority rather than
    # from the first row: a pickup bar can be annotated in a different metre,
    # and one odd row must not set the signature for the whole solo.
    signatures = Counter((int(r[4] or 4), int(r[5] or 4)) for r in rows)
    num, denom = signatures.most_common(1)[0][0]
    quarters_per_beat = 4.0 / denom

    first_bar = min(int(r[0]) for r in rows)
    quantized = []
    for bar, beat, tatum, division, _num, _denom, beatdur, duration, pitch in rows:
        division = max(1, int(division or 1))
        position = ((int(beat) - 1) + (int(tatum) - 1) / division) * quarters_per_beat
        # Performed seconds -> beats, using the annotator's own local beat
        # length. `build` will mostly overwrite this via the legato rule, but
        # the note genuinely followed by a rest is told apart by how much of
        # the gap it filled, so a real length has to go in.
        played = float(duration or 0.0) / float(beatdur) if beatdur else quarters_per_beat
        quantized.append(
            QuantizedNote(
                bar=int(bar),
                beat=position,
                duration_beats=max(played * quarters_per_beat, 1e-3),
                pitch=int(round(float(pitch))),
                timing_residual=0.0,
            )
        )

    performer, title = db.execute(
        "select performer, title from solo_info where melid=?", (melid,)
    ).fetchone() or ("", "")
    # Seconds are meaningless here -- there is no audio in this path and
    # `build` reads only `time_signature` and `first_bar` off a section.
    section = MeterSection(
        start=0.0,
        end=0.0,
        pulses_per_bar=num,
        time_signature=(num, denom),
        anchor=0.0,
        first_bar=first_bar,
        origin="user",
    )
    return notate.build(
        quantized,
        [section],
        swing=True,
        transpose=0,
        title=f"{performer} - {title}".strip(" -"),
        legato_fill=legato_fill,
        legato_cap=legato_cap,
    )
