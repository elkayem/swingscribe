"""Where a located score's bar lines fall on the tracked beat grid.

`benchmark.locate_score` says where a score sits in a recording as ONE
straight clock -- a start and a tempo. That is enough to draw a span and not
enough to name a downbeat: over a three-minute side the tempo breathes, the
line's intercept lands up to two beats from the music's bar 1 (Segment,
2026-09-17), and a sidecar anchor written from it put eleven of the
twenty-two Omnibook pages one to two beats off the book's bar lines -- every
note right, every bar line wrong, and the span's own first beat cut off with
it.

The beat tracker already holds the local clock. Every true match of the
alignment is a (score position, heard onset) pair; read the onset's place on
the beat grid as a fractional beat index and subtract the position, and what
is left is the index of the beat that IS the score's quarter zero. One pair
says little (a laid-back eighth sits a sixth of a beat late); hundreds vote,
and on the Omnibook sides 86-98% of them name one beat in the bar.

Pure arithmetic over plain lists, like `alignment.py`: no audio, no model.
"""

from __future__ import annotations

import bisect
from collections import Counter

# Votes needed before a phase is believed, and the share of them the winning
# beat must hold. A right grid reads 0.86-0.98 on the twenty-two Omnibook
# sides; a grid at half or double the score's pulse spreads its votes over
# every beat of the bar and cannot reach this.
MIN_VOTES = 20
PHASE_SHARE_FLOOR = 0.6
# Bar 1 and the last bar are each read from this share of the score's notes,
# from its two ends: a slipped beat or a chorus the book leaves out moves the
# index part-way through, and the span's edges should follow the music
# nearest them.
EDGE_SHARE = 0.25


def clock_anchors(score, notes: list[tuple[float, int]], found: dict) -> list[tuple[float, float]]:
    """(score position, heard onset) for the matches on a located clock.

    `found` is `benchmark.locate_score`'s answer for the same score and
    notes. One alignment at the transposition it settled on, keeping the true
    pitch matches within its own tolerance of its own line -- the anchors it
    counted, which it reports only as a number.
    """
    from swingscribe.alignment import align
    from swingscribe.benchmark import LOCATE_RESIDUAL_S

    offset = int(found["transposition"])
    start, slope = found["start"], found["seconds_per_quarter"]
    theirs = [n.pitch for n in score.melody]
    aligned = align(theirs, [pitch + offset for _, pitch in notes])
    return [
        (score.melody[ri].position, notes[ei][0])
        for ri, ei in aligned.pairs
        if ri is not None
        and ei is not None
        and theirs[ri] == notes[ei][1] + offset
        and abs(notes[ei][0] - (start + slope * score.melody[ri].position)) <= LOCATE_RESIDUAL_S
    ]


def beat_coordinate(beats: list[float], when: float) -> float | None:
    """`when` as a fractional index into `beats`; None outside the grid."""
    index = bisect.bisect_right(beats, when) - 1
    if index < 0 or index + 1 >= len(beats):
        return None
    return index + (when - beats[index]) / (beats[index + 1] - beats[index])


def _mode(values: list[int]) -> int | None:
    return Counter(values).most_common(1)[0][0] if values else None


def bars_on_grid(
    anchors: list[tuple[float, float]],
    beats: list[float],
    quarters: float,
    pulses_per_bar: int = 4,
) -> dict[str, float | int | bool | None]:
    """The score's bar 1, last bar line and downbeat phase, on `beats`.

    `anchors` are (score position in quarters, heard onset in seconds) for
    the matches that sit on the located clock, in score order; `beats` the
    repaired, extended grid the page is built on (`meter.bar_grid`), one
    pulse per quarter; `quarters` the score's length.

    `phase` is the beat index, modulo the bar, that carries a bar line.
    `bar_one` and `end` are beat times -- None when that beat is off the
    grid's edge, a score that starts before the file does. `anchor` is always
    a beat on the grid that carries a bar line, the one nearest bar 1: what a
    sidecar stores. Nothing here is trusted below the two floors above.
    """
    result: dict[str, float | int | bool | None] = {
        "votes": 0,
        "phase": None,
        "share": 0.0,
        "bar_one": None,
        "end": None,
        "anchor": None,
        "trusted": False,
    }
    origins = [
        round(coordinate - position)
        for position, onset in anchors
        if (coordinate := beat_coordinate(beats, onset)) is not None
    ]
    if not origins:
        return result
    phase, count = Counter(origin % pulses_per_bar for origin in origins).most_common(1)[0]
    share = count / len(origins)
    on_phase = [origin for origin in origins if origin % pulses_per_bar == phase]
    edge = max(1, round(len(origins) * EDGE_SHARE))
    first = _mode([o for o in origins[:edge] if o % pulses_per_bar == phase])
    last = _mode([o for o in origins[-edge:] if o % pulses_per_bar == phase])
    first = _mode(on_phase) if first is None else first
    last = _mode(on_phase) if last is None else last
    closing = last + round(quarters)

    def beat_time(index: int) -> float | None:
        return beats[index] if 0 <= index < len(beats) else None

    # The nearest bar line to bar 1 that the grid actually holds.
    held = first
    while held < 0:
        held += pulses_per_bar
    while held >= len(beats):
        held -= pulses_per_bar
    result.update(
        votes=len(origins),
        phase=phase,
        share=share,
        bar_one=beat_time(first),
        end=beat_time(closing),
        anchor=beat_time(held),
        trusted=len(origins) >= MIN_VOTES and share >= PHASE_SHARE_FLOOR,
    )
    return result


EMPTY_AGREEMENT = {"beat_offset": 0.0, "beat_share": 0.0, "on_the_bar": 0.0, "beat_n": 0.0}


def beat_agreement(
    ours: list[tuple[float, int]], theirs: list[tuple[float, int]], bar: float
) -> dict[str, float]:
    """Our beat-in-bar against a reference's, over the true pitch matches.

    `ours` are (position in quarters from OUR bar 1, pitch), `theirs` the
    same from THEIR bar 1 (or already the beat in the bar: only the position
    modulo the bar is read), `bar` the bar's length in quarters -- one metre
    throughout, both sides.

    The notated rhythm measure compares the GAPS between matched notes, so a
    page whose every bar line sits a beat early scores exactly what the right
    page scores -- it is phase-immune on purpose (`benchmark.score_notation`),
    and that is how eleven Omnibook pages went out a beat or two off the book
    with nothing in the scorecard to say so. This asks the other question.

    `on_the_bar` is the SCORE: the share of matched notes we wrote on the
    beat the reference wrote them on (to the nearest half beat). A page on
    its bar lines reads 0.8-0.95 -- what is left is syncopation we resolved
    differently -- and a page a beat off reads under 0.1, so a wrong
    downbeat costs nearly the whole of it. `beat_offset` says which way: the
    commonest difference (ours minus theirs, modulo the bar), 0.0 for a page
    on the reference's bar lines, 3.0 for one whose notes all sit a beat
    early. `beat_share` is the share of matches at that difference -- quote
    the offset with it, it is a mode.
    """
    from swingscribe.alignment import measured_transposition

    result = dict(EMPTY_AGREEMENT)
    if not ours or not theirs or bar <= 0:
        return result
    offset, aligned = measured_transposition([p for _, p in theirs], [p for _, p in ours])
    deltas: Counter = Counter()
    for ri, ei in aligned.pairs:
        if ri is None or ei is None or theirs[ri][1] != ours[ei][1] + offset:
            continue
        delta = round(((ours[ei][0] - theirs[ri][0]) % bar) * 2) / 2
        deltas[0.0 if delta >= bar else delta] += 1
    total = sum(deltas.values())
    if not total:
        return result
    mode, count = deltas.most_common(1)[0]
    result.update(
        beat_offset=mode,
        beat_share=count / total,
        on_the_bar=deltas[0.0] / total,
        beat_n=float(total),
    )
    return result


def _our_positions(notation) -> list[tuple[float, int]]:
    from swingscribe.benchmark import notation_notes

    return [(position, pitch) for position, _duration, pitch in notation_notes(notation)]


def _our_bar(notation) -> float:
    """The length in TRUE quarters of our page's bar, 0.0 if it changes metre.
    A double-time page is written in doubled units (`notation_notes` halves
    its positions), so its written bar is half as long as it looks."""
    lengths = {bar.time_signature[0] * 4.0 / bar.time_signature[1] for bar in notation.bars}
    if len(lengths) != 1:
        return 0.0
    return lengths.pop() * (0.5 if getattr(notation, "double_time", False) else 1.0)


def bar_line_agreement(notation, score) -> dict[str, float]:
    """`beat_agreement` against a parsed `mscz.Score` (both readers pad a
    short bar to its time signature, so position modulo the bar is the beat)."""
    bar = float(score.beats_per_bar)
    theirs = [(n.position, n.pitch) for n in score.melody]
    return beat_agreement(_our_positions(notation), theirs, bar)


def _comparable(notation, bar: float) -> bool:
    """Our page's bar must divide theirs: a 4/4 page against a 3/4 annotation
    has no common bar line to be on, and the mode of noise is not a finding."""
    ours_bar = _our_bar(notation)
    return bar > 0 and ours_bar > 0 and not (bar / ours_bar) % 1


def wjazz_bar_line_agreement(
    notation, positions: list[tuple[float, int]], bar: float
) -> dict[str, float]:
    """`beat_agreement` against WJazzD's own bar/beat/tatum annotation
    (`wjazz.notated_beats`). Refused -- every field zero -- when the page's
    metre is not the annotation's."""
    if not positions or not _comparable(notation, bar):
        return dict(EMPTY_AGREEMENT)
    return beat_agreement(_our_positions(notation), positions, bar)


# ── where a page leaves its bar lines ───────────────────────────────────────
#
# `on_the_bar` says a page is off; it cannot say WHERE. On a sound page the
# difference between our position and the reference's is one constant from
# the first matched note to the last. Every way a beat grid fails writes its
# own signature into that difference: a beat the tracker dropped or doubled
# is a STEP of one beat at the bar where it happened (and every bar line
# after it is off), a chorus the reference omits is a step of whole bars, a
# grid at half or double the pulse is a SLOPE, and a wrong downbeat is no
# step at all -- one constant that is not a multiple of the bar.

# The label of a match is the commonest difference among this many matches
# around it: wide enough that a syncopation we resolved differently (half a
# beat, a note or two at a time) never reads as a step.
TRACE_WINDOW = 15
# A run of labels shorter than this is folded into the run before it.
TRACE_MIN_RUN = 10
# Our positions should advance one quarter per reference quarter. Outside
# this the grid is not at the reference's pulse, and steps mean nothing.
TRACE_SLOPE_TOLERANCE = 0.1


def _matched_differences(
    ours: list[tuple[float, int]], theirs: list[tuple[float, int]]
) -> list[tuple[float, float]]:
    """(our position, ours minus theirs) for every true pitch match, in order."""
    from swingscribe.alignment import measured_transposition

    offset, aligned = measured_transposition([p for _, p in theirs], [p for _, p in ours])
    return [
        (ours[ei][0], ours[ei][0] - theirs[ri][0])
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and theirs[ri][1] == ours[ei][1] + offset
    ]


def difference_trace(
    ours: list[tuple[float, int]],
    theirs: list[tuple[float, int]],
    bar: float,
    first_bar: int = 1,
) -> dict:
    """How (ours - theirs) moves along a page: its runs, its steps, its slope.

    `segments` are runs of one difference -- `from`/`to` in OUR quarters from
    our first bar line, `offset` the difference to the nearest half beat,
    `beat_offset` that modulo the bar (0.0 is a run on the reference's bar
    lines), `matches` how many notes say so. `steps` are the changes between
    consecutive runs: `at` (our quarters), `bar` (our bar as PRINTED, counted
    from `first_bar` -- 0 when the page opens with a pickup), `change` in
    beats. `slope` is our quarters per reference quarter, a Theil-Sen line,
    and `steady` whether it is near enough to 1 for the steps to mean
    anything.
    """
    from swingscribe.benchmark import robust_line

    result = {
        "segments": [],
        "steps": [],
        "slope": 0.0,
        "steady": False,
        "matches": 0,
        "first_bar": first_bar,
    }
    pairs = _matched_differences(ours, theirs)
    if len(pairs) < TRACE_MIN_RUN or bar <= 0:
        return result
    slope, _ = robust_line([(position - difference, position) for position, difference in pairs])
    steady = abs(slope - 1.0) <= TRACE_SLOPE_TOLERANCE
    result.update(slope=slope, steady=steady, matches=len(pairs))
    if not steady:
        return result

    half = TRACE_WINDOW // 2
    rounded = [round(difference * 2) / 2 for _, difference in pairs]
    labels = [
        Counter(rounded[max(0, i - half) : i + half + 1]).most_common(1)[0][0]
        for i in range(len(rounded))
    ]
    runs: list[list] = []  # [label, first index, last index]
    for index, label in enumerate(labels):
        if runs and runs[-1][0] == label:
            runs[-1][2] = index
        else:
            runs.append([label, index, index])
    merged: list[list] = []
    for run in runs:
        short = run[2] - run[1] + 1 < TRACE_MIN_RUN
        if merged and (short or merged[-1][0] == run[0]):
            merged[-1][2] = run[2]
        else:
            merged.append(run)
    if len(merged) > 1 and merged[0][2] - merged[0][1] + 1 < TRACE_MIN_RUN:
        merged[1][1] = merged[0][1]  # a short opening run belongs to what follows
        merged = merged[1:]

    for label, first, last in merged:
        agree = sum(1 for value in rounded[first : last + 1] if value == label)
        result["segments"].append(
            {
                "from": pairs[first][0],
                "to": pairs[last][0],
                "offset": label,
                "beat_offset": label % bar,
                "matches": last - first + 1,
                "share": agree / (last - first + 1),
            }
        )
    for before, after in zip(result["segments"], result["segments"][1:], strict=False):
        result["steps"].append(
            {
                "at": after["from"],
                "bar": int(after["from"] // bar) + first_bar,
                "change": after["offset"] - before["offset"],
            }
        )
    return result


def _first_bar(notation) -> int:
    return int(notation.bars[0].number) if notation.bars else 1


def bar_line_trace(notation, score) -> dict:
    """`difference_trace` against a parsed `mscz.Score`."""
    theirs = [(n.position, n.pitch) for n in score.melody]
    return difference_trace(
        _our_positions(notation), theirs, float(score.beats_per_bar), _first_bar(notation)
    )


def wjazz_bar_line_trace(notation, positions: list[tuple[float, int]], bar: float) -> dict:
    """`difference_trace` against `wjazz.notated_beats`; empty when the
    page's metre is not the annotation's."""
    if not positions or not _comparable(notation, bar):
        return difference_trace([], [], 0.0)
    return difference_trace(_our_positions(notation), positions, bar, _first_bar(notation))


def describe_trace(trace: dict, bar: float) -> str:
    """One line a person can act on."""
    if not trace["matches"]:
        return "nothing to trace"
    if not trace["steady"]:
        return (
            f"our page advances {trace['slope']:.2f} quarters per reference quarter -- "
            "the beat grid is not at the reference's pulse"
        )
    parts = []
    for segment in trace["segments"]:
        first = int(segment["from"] // bar) + trace["first_bar"]
        last = int(segment["to"] // bar) + trace["first_bar"]
        where = "on the bar" if segment["beat_offset"] == 0.0 else f"{segment['beat_offset']:+.1f}"
        parts.append(f"bars {first}-{last} {where}")
    steps = ", ".join(f"{step['change']:+.1f} at bar {step['bar']}" for step in trace["steps"])
    return "; ".join(parts) + (f"  [steps: {steps}]" if steps else "")
