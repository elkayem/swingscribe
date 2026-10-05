"""Stage — Meter: bar lines derived by counting beats (docs/meter-plan.md).

Measured against real tracks, beat_this's two output layers are of very
different quality. The *pulse* is excellent — better than 95% of beats sit
within 5% of their local neighbours. The *downbeat* layer is noise: if bars
were real, the histogram of beats-between-consecutive-downbeats would be one
spike, and instead Gerry's Blues gives {2: 131, 4: 99, 1: 30, 3: 5}. Taking the
median of that is how both test tracks ended up claiming two beats per bar
(open-issue #5).

So this stage ignores the detected downbeats as a source of truth and derives
bar lines by counting beats outward from an anchor. Three numbers describe a
bar grid — beats, pulses_per_bar, anchor — which is also what makes "click a
dot to move the downbeat" a one-parameter change rather than a re-analysis.
Gradual tempo drift needs no special handling: bar lines land on real detected
beats, whose spacing already drifts.

Everything here is pure and cheap. The GUI calls these functions directly on a
cached BeatGrid to redraw instantly; the stage exists so the pipeline reaches
the same answer through the cache key, not so the GUI can ask the question.

No heavy imports at all — this module is stdlib-only and always importable.
"""

import bisect
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace

from swingscribe.config import Config, MeterConfig
from swingscribe.model import Document, MeterSection

# name -> (numerator, denominator, tracked pulses per bar)
#
# The third number is not always the numerator. beat_this tracks a pulse; 6/8
# at a jazz tempo is felt in 2, so it has two dotted-quarter pulses per bar
# even though it notates as six eighths. Keeping both means notation at M6 gets
# the real signature instead of back-inferring it from a pulse count.
TIME_SIGNATURES: dict[str, tuple[int, int, int]] = {
    "2/4": (2, 4, 2),
    "3/4": (3, 4, 3),
    "4/4": (4, 4, 4),
    "5/4": (5, 4, 5),
    "6/4": (6, 4, 6),
    "7/4": (7, 4, 7),
    "3/8": (3, 8, 1),
    "6/8": (6, 8, 2),
    "9/8": (9, 8, 3),
    "12/8": (12, 8, 4),
}

DEFAULT_TIME_SIGNATURE = "4/4"

# Rolling window (in beats, either side) for the local pulse reference.
REFERENCE_WINDOW = 8

# Two spans separated by no more than this many beats are one span. Without it a
# single wobbly interval — a fill, a stumble — punches a hole in the bar grid
# for the rest of the tune, which reads as a bug rather than as caution.
#
# The time check is not redundant with the index check: where the tracker found
# nothing at all (Corner Pocket's 19.8s free outro), the beats bracketing the
# hole are index-adjacent, so an index-only test would bridge straight across
# the very passage that has no pulse to draw.
BRIDGE_BEATS = 1

# 2: with no anchor set, the downbeat is voted around the transcribe region
# rather than over the whole track (`_auto_anchor`, D32).
# 3: a stretch tracked at double rate is thinned to the pulse (R26).
# 4: the pulse's OCTAVE is judged from the downbeat layer before the repair
# (`pulse_octave`, R32): a grid at half rate with the true pulse surfacing
# is subdivided to it instead of thinned to the half.
# 5: a ghost beat crowding a real one is thinned by the metronome test
# (`drop_ghost_beats`, R34), and so is a ragged stretch it reads as whole
# beats too many (`thin_by_metronome`).
# 6: doubts too close for the metronome to read alone are read as one, a
# whole bar too many is thinned, and a re-lay keeps only FOUND beats (R35).
# 7: a section's first_bar counts the bars of free time before it (R35).
CACHE_VERSION = 7


@dataclass(frozen=True)
class Beat:
    """One beat of the repaired grid."""

    time: float
    implied: bool = False  # inserted here, not found by the tracker
    # Implied *beyond* the tracker's range rather than between two of its beats.
    # Interpolation is bounded by evidence on both sides; extrapolation is not,
    # so the two are allowed to do different things (see metrical_spans).
    extrapolated: bool = False
    # Placed by the listener (`apply_pins`). Found, not implied: a pin is
    # evidence of a beat, like the tracker's, and better than it.
    pinned: bool = False
    # Laid out again in a pin's window (`apply_pins`), the tracker's own beat
    # or an implied one. The intervals beside it follow from the listener's
    # pin, not from the tracker, and `metrical_spans` takes them as steady.
    relaid: bool = False


def resolve_meter(config: MeterConfig) -> tuple[tuple[int, int], int]:
    """(time signature, pulses per bar), honouring explicit overrides."""
    name = config.time_signature or DEFAULT_TIME_SIGNATURE
    if name in TIME_SIGNATURES:
        numerator, denominator, pulses = TIME_SIGNATURES[name]
    else:
        # "7/8" and friends: parse it rather than refuse. Pulses default to the
        # numerator, which the user can override when they feel it differently.
        try:
            numerator, denominator = (int(part) for part in name.split("/", 1))
        except ValueError as exc:
            raise ValueError(f"unparseable time signature {name!r}") from exc
        pulses = numerator
    return (numerator, denominator), max(1, config.pulses_per_bar or pulses)


def _rolling_median(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    out = []
    for i in range(len(values)):
        lo = max(0, i - window)
        hi = min(len(values), i + window + 1)
        out.append(statistics.median(values[lo:hi]))
    return out


# An interval under three quarters of the seed says something about the
# pulse only when it is HALF of it, within this fraction: a tracker at double
# rate emits halves, while a swung offbeat or a ghost beat emits neither.
# Anything else that short is left out of the reference. Longer intervals
# enter as the whole multiple they round to, as they always did, so the
# reference still follows a genuine change of tempo.
REFERENCE_HALF_FIT = 0.15
# Fitting intervals wanted in a window before the local median is believed;
# with fewer, the seed stands.
REFERENCE_MIN_FIT = 3


def modal_interval(intervals: list[float]) -> float:
    """The grid's own seed pulse: the mode at 10 ms resolution, which is robust
    to a minority of intervals sitting at a multiple of the true pulse.
    Falls back to the median when the mode is degenerate."""
    counts: dict[float, int] = {}
    for value in intervals:
        bucket = round(value, 2)
        counts[bucket] = counts.get(bucket, 0) + 1
    seed = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0] if counts else 0.0
    if seed <= 0 and intervals:
        seed = statistics.median(intervals)
    return seed


def reference_pulse(intervals: list[float], seed: float | None = None) -> list[float]:
    """The pulse rate the tune is *actually* running at, per interval.

    `seed` overrides the grid's own modal interval: the octave the mode
    picks is the tracker's, and on a grid tracked at half rate for most of
    a tune it is the wrong one (`pulse_octave`).

    Cannot be a plain local median. Corner Pocket's first 23 seconds are tracked
    at half rate, so the local median there is itself the wrong answer and no
    amount of local smoothing notices. Instead: seed from the global mode, use
    that to guess how many pulses each interval spans, divide it out, and smooth
    the *implied* pulse. Half-rate regions contribute their halved value, so the
    reference stays on the true rate while still following genuine tempo drift.

    A stretch tracked at DOUBLE rate must not pull the reference down with it
    (2026-09-18, R26): Curtis Fuller's Blue Train solo is tracked at half the
    pulse for 44% of its length, and a rolling median that followed those
    intervals called every one of them a beat -- 66 extra beats on the page.
    So an interval under three quarters of the seed enters the median only
    as half a pulse, and only when it is one within `REFERENCE_HALF_FIT`. A
    swung offbeat (0.64 + 0.36 of a pulse), a ghost 80 ms from a real beat,
    a rubato interval say nothing and are left out; where too few remain in
    a window, the seed stands. Longer intervals enter as the whole multiple
    they round to, as before, so a passage at another tempo still moves the
    reference with it.
    """
    if not intervals:
        return []
    if seed is None or seed <= 0:
        seed = modal_interval(intervals)
    if seed <= 0:
        return list(intervals)

    implied: list[float | None] = []
    for value in intervals:
        ratio = value / seed
        if ratio >= 0.75:
            implied.append(value / round(ratio))
        elif abs(ratio / 0.5 - 1.0) <= REFERENCE_HALF_FIT:
            implied.append(value * 2.0)
        else:
            implied.append(None)
    out = []
    for i in range(len(intervals)):
        lo, hi = max(0, i - REFERENCE_WINDOW), i + REFERENCE_WINDOW + 1
        window = [value for value in implied[lo:hi] if value is not None]
        out.append(statistics.median(window) if len(window) >= REFERENCE_MIN_FIT else seed)
    return out


# The pulse's octave (2026-09-21, R32). A tracker at half rate for most of a
# tune -- Kenny Garrett's Brother Hubbard at 0.82 s on a 148 bpm tune, Adam's
# Apple, Nothing Personal -- puts the seed on the wrong octave, and R26's
# thinning then removes the true pulse wherever it surfaces. Its own
# activation says nothing about it: read at the midpoints of its beats the
# model hears 0.05-0.14 on those grids and 0.6-0.8 on the 300 bpm tunes,
# where the grid is right. What does say it is the DOWNBEAT layer, on the
# grids that hold both octaves: in the half-rate stretches it marks every
# SECOND grid beat (0.64-0.80 of consecutive marks, the bar of a 4/4 tune
# at half rate), against 0.08-0.14 on Blue Train's, Totem Pole's and the
# Sidewinders' coarse stretches, whose coarse pulse is the right one. Both
# tests are required: Embraceable You's ballad grid has marks in twos
# (0.56) and no fine runs at all, and stays; Totem Pole's fine runs are
# 18% of its intervals and its marks come in fours, and it is thinned as
# before. A grid at half rate THROUGHOUT, with no fine run to compare, is
# not seen by this and still wants a tempo hint (`beats.correct_octave`).
OCTAVE_FINE_SHARE = 0.2  # of the grid's intervals near half the seed
OCTAVE_TWO_SHARE = 0.5  # of downbeat pairs in the coarse stretches two beats apart
OCTAVE_MIN_MARKS = 20  # such pairs before the layer is believed at all


def pulse_octave(beats: list[float], downbeats: list[float]) -> float | None:
    """The seed pulse when the grid's modal interval is the wrong octave,
    else None. Judged from the downbeat layer: on a 4/4 tune tracked at half
    rate the marks come every two grid beats where the grid is coarse, and
    the true pulse shows in runs of half-length intervals."""
    if len(beats) < 4 or not downbeats:
        return None
    intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    seed = modal_interval(intervals)
    if seed <= 0:
        return None
    fine = [v for v in intervals if abs(v / seed / 0.5 - 1.0) <= REFERENCE_HALF_FIT]
    if len(fine) < OCTAVE_FINE_SHARE * len(intervals):
        return None

    marks = sorted({nearest_index(beats, d) for d in downbeats})
    coarse_pairs = twos = 0
    for a, b in zip(marks, marks[1:], strict=False):
        if a >= len(intervals) or abs(intervals[a] / seed - 1.0) > REFERENCE_HALF_FIT:
            continue
        coarse_pairs += 1
        twos += b - a == 2
    if coarse_pairs < OCTAVE_MIN_MARKS or twos < OCTAVE_TWO_SHARE * coarse_pairs:
        return None
    return statistics.median(fine)


def nearest_index(times: list[float], when: float) -> int:
    """Index of the time nearest `when` in a sorted list."""
    i = bisect.bisect_left(times, when)
    candidates = [j for j in (i - 1, i) if 0 <= j < len(times)]
    return min(candidates, key=lambda j: abs(times[j] - when))


# A doubled beat: one the tracker put between two real ones. It is judged as
# a PAIR of intervals against the reference pulse, two ways:
# - the pair together IS one pulse (within DOUBLED_PAIR_FIT) and one of its
#   intervals is short: the tracker's beat on a swung offbeat (0.64 + 0.36),
#   at double rate (0.5 + 0.5), or a ghost 80 ms from a real beat (0.82 +
#   0.18). A run of these is a stretch tracked at double rate and is thinned
#   to the pulse -- measured, not assumed (2026-09-18, R26): on six WJazzD
#   solos such runs put 33 to 91 beats on the page that the annotator does
#   not have, and no run anywhere in the three benchmarks was the band's;
# - or, isolated between ordinary intervals, a ragged pair: each under
#   DOUBLED_SHORT of the pulse and together at most DOUBLED_PAIR_MAX of it.
#   Measured need: Red Garland's Billy Boy, bar 107 (0.200, 0.140, 0.140,
#   0.220 s on a 0.220 s pulse), and 306 more of the same shape across the
#   122 cached grids (docs/benchmark-deficiencies.md R21).
DOUBLED_SHORT = 0.75
DOUBLED_PAIR_MAX = 1.4
DOUBLED_PAIR_FIT = 0.15
# beat_this places beats on a 20 ms frame grid, so a pair's sum can miss
# the pulse by a frame before any timing is involved -- at 221 bpm that is
# 7% of a beat on its own, and Cheese Cake's last three slips were 0.22 +
# 0.08 s pairs read against a 0.26 s reference (1.154 of it).
TRACKER_FRAME_S = 0.02


def drop_doubled_beats(
    beats: list[float], tolerance: float, seed: float | None = None
) -> list[float]:
    """Remove the middle beat of a pair of intervals that together make one
    pulse, or of an isolated ragged short pair.

    The mirror of the insertion below, and the same harm: a beat the tracker
    doubled makes its bar a beat short and shifts every bar line after it by
    one beat for the rest of the tune. A doubled beat cannot be seen one
    interval at a time — each of its two short intervals rounds to one pulse
    on its own — so it is judged as a pair against the reference pulse. The
    left interval is taken on the KEPT sequence, so a run of doubled beats is
    thinned one by one and the merged interval then reads as ordinary.

    A grid tracked at HALF rate for most of a tune (Kenny Garrett's Brother
    Hubbard, 0.82 s on a 148 bpm tune) has the half-rate pulse for its
    seed, so the true beats surfacing in pairs are exactly what this would
    thin. `seed` is the caller's answer to that (`pulse_octave`, R32): with
    the fine pulse as the seed those pairs are two beats, and the coarse
    intervals are the gaps the insertion below fills.
    """
    if len(beats) < 4:
        return list(beats)
    intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    reference = reference_pulse(intervals, seed)
    kept = [beats[0]]
    for i in range(1, len(beats) - 1):
        pulse = reference[i]
        if pulse <= 0:
            kept.append(beats[i])
            continue
        before, after = beats[i] - kept[-1], intervals[i]
        one_pulse = (
            abs(before + after - pulse) <= DOUBLED_PAIR_FIT * pulse + TRACKER_FRAME_S
            and min(before, after) < DOUBLED_SHORT * pulse
        )
        ordinary_left = len(kept) >= 2 and abs((kept[-1] - kept[-2]) - pulse) <= tolerance * pulse
        ordinary_right = (
            i + 1 < len(intervals) and abs(intervals[i + 1] - pulse) <= tolerance * pulse
        )
        ragged_pair = (
            ordinary_left
            and ordinary_right
            and before < DOUBLED_SHORT * pulse
            and after < DOUBLED_SHORT * pulse
            and before + after <= DOUBLED_PAIR_MAX * pulse
        )
        if one_pulse or ragged_pair:
            continue  # drop beats[i]
        kept.append(beats[i])
    kept.append(beats[-1])
    return kept


# ── a ghost beat, and the metronome test (2026-10-02, R34) ──────────────────
#
# The pair test above asks whether the two intervals beside a beat make ONE
# pulse. A ghost the tracker put 80 ms from a real beat fails it whenever the
# real beats either side sit a frame or two from where a metronome would put
# them: on Joe Henderson's A Shade of Jade, 0.22 + 0.08 + 0.24 s on a 0.227 s
# pulse, dropping either crowded beat leaves 1.4 pulses, so both stayed and
# the page gained a beat -- twice in five bars, half a bar off until the end.
# beat_this's peak picker suppresses a second peak only within 60 ms (a
# 7-frame max pool), and the DBN that would hold a tempo is off (plan §2).
# Nothing downstream counted it either: the steadiness test flagged the
# 0.08 s interval, and `metrical_spans` bridged it as it bridges any single
# wobble, counting the ghost.
#
# A bar line is a COUNT, so the question is a count: how many beats does the
# time across the suspect pair hold? Locally it cannot say -- from the beat
# before the pair to the beat after was 2.4 pulses there, because the bar
# around it ran 9% slow -- so it is asked of a metronome laid across two bars
# either side (`metronome_jump`): the pulse measured from each side's SPAN
# (time over count -- a median of intervals on the tracker's 20 ms frames
# reads 0.22 s for a 0.227 s pulse, half a beat over sixteen), each side's
# phase the median of its beats against that pulse, and the jump between the
# two phases, in beats, is how many beats the pair holds too many. A ghost
# reads 1; two real beats displaced read 0. A pair is thinned only within
# GHOST_JUMP_FIT of 1, where both sides are steady and agree on the pulse --
# which is what D33's count-by-duration (a ragged stretch's own length over
# the reference) lacked, and why at 340 bpm it was a coin toss.
#
# Measured against WJazzD's annotated beats (`scripts/grid_drift.py`'s
# measure, 73 solos): five grids move and none the wrong way -- Cheese Cake
# +1.1 -> +0.1 beats over the solo (the slip the beat pins were built for,
# O5), Coltrane's Oleo +1.9 -> -0.1, In 'n Out +11.5 -> +9.5 and +2.9 ->
# +1.9, Cherokee +0.6 -> -0.4; 63 -> 65 solos within a beat. The mirror rule
# -- the same test deciding an ambiguous gap the insertion rounds -- was
# measured and is NOT here: over 147 cached grids rounding agrees with the
# metronome on 411 of the 415 gaps it can read, and the four it does not
# are ratios of 1.50 read at the edge of the band.
GHOST_SHORT = 0.6  # an interval under this share of the pulse is a candidate
GHOST_SIDE = 8  # intervals either side the metronome is laid across
GHOST_JUMP_FIT = 0.4  # |jump - 1| at most, in beats, to thin the pair
# A side is steady when every interval in it is within this share of the
# side's own pulse (a 0.18 + 0.28 jitter pair on 0.227 s passes, a ghost or
# a dropped beat does not), and the two sides' pulses must agree within the
# stability tolerance: a change of tempo is not a metronome.
GHOST_SIDE_CLEAN = 0.35


def metronome_jump(
    times: list[float], last_left: int, first_right: int, agree: float = 0.15
) -> float | None:
    """How many beats the numbering on the right of a spot runs AHEAD of the
    left's, read off one metronome laid across `GHOST_SIDE` intervals either
    side: `times[..last_left]` against `times[first_right..]`, numbered by
    index. 0.0 is a spot whose count is right, +1 a beat too many between
    the two sides (a ghost), -1 a beat too few. None when a side runs off the
    grid, is not steady, or the sides disagree on the pulse by more than
    `agree` -- where a metronome has nothing to say."""
    a, b = last_left - GHOST_SIDE, first_right + GHOST_SIDE
    if a < 0 or b >= len(times) or first_right <= last_left:
        return None
    left = times[a : last_left + 1]
    right = times[first_right : b + 1]
    pulses = []
    for run in (left, right):
        pulse = (run[-1] - run[0]) / GHOST_SIDE
        if pulse <= 0 or any(
            abs((y - x) - pulse) > GHOST_SIDE_CLEAN * pulse
            for x, y in zip(run, run[1:], strict=False)
        ):
            return None
        pulses.append(pulse)
    pulse = (pulses[0] + pulses[1]) / 2
    if abs(pulses[0] - pulses[1]) > agree * pulse:
        return None
    phase_left = statistics.median(t - pulse * (i - last_left) for i, t in enumerate(left, a))
    phase_right = statistics.median(
        t - pulse * (i - last_left) for i, t in enumerate(right, first_right)
    )
    return (phase_left - phase_right) / pulse


def drop_ghost_beats(
    beats: list[float], tolerance: float, seed: float | None = None
) -> list[float]:
    """Remove one beat of every pair far closer than a pulse that the
    metronome test says holds a beat too many (see the note above). The one
    removed is the farther from where an even beat between the pair's
    neighbours would be. Shortest pairs first, and the grid is judged again
    after each removal, so a ghost beside another never reads its side as
    ragged twice."""
    beats = list(beats)
    while len(beats) >= 4:
        intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
        reference = reference_pulse(intervals, seed)
        short = [
            k
            for k in range(1, len(intervals) - 1)
            if reference[k] > 0 and intervals[k] < GHOST_SHORT * reference[k]
        ]
        for k in sorted(short, key=lambda k: intervals[k] / reference[k]):
            jump = metronome_jump(beats, k - 1, k + 2, tolerance)
            if jump is not None and abs(jump - 1.0) <= GHOST_JUMP_FIT:
                middle = (beats[k - 1] + beats[k + 2]) / 2
                del beats[k if abs(beats[k] - middle) > abs(beats[k + 1] - middle) else k + 1]
                break
        else:
            return beats
    return beats


# ── where the count is in doubt (2026-10-02, R34) ───────────────────────────
#
# A slip the repair cannot see is invisible until a page is laid beside a
# reference, and most tracks have none -- the listener found Shade of Jade's
# by reading the page. So the grid says where its own count is unsupported:
# every run of up to DOUBT_REACH stretches between found beats whose time
# does not hold the number of intervals the grid gives it (within
# DOUBT_RESIDUAL of a whole pulse -- a ghost 0.36 of a pulse from a beat, a
# gap of 1.45 pulses the insertion rounded down, four beats tracked as three
# intervals of 1.33), unless the metronome either side confirms the count.
# Jitter does not qualify: 0.18 + 0.28 s on a 0.227 s pulse is 0.79 and
# 1.23, and 2.03 together.
DOUBT_RESIDUAL = 0.35
DOUBT_REACH = 3
# A doubt is SETTLED, and not reported, when the tracker's own downbeat marks
# within DOUBT_MARK_REACH_S either side keep one phase across it (at least
# DOUBT_MIN_MARKS each side). Measured on WJazzD's annotated solos: where the
# grid really slipped, the marks changed phase across the doubt 8 times in 8;
# where the count was right, they kept it 15 times in 16 -- Shade of Jade's
# two mended ghosts among them, whose bars ran 9% slow, so the metronome
# alone read them as half a beat out either way. The marks only ever SETTLE
# a doubt: no beat is moved by them, and bars are never counted from them.
DOUBT_MARK_REACH_S = 8.0
DOUBT_MIN_MARKS = 3


@dataclass(frozen=True)
class Doubt:
    """A stretch of the grid whose beat count the time does not support."""

    start: float  # the found beat the stretch starts on
    end: float  # the found beat it ends on
    held: float  # pulses its time holds
    kept: int  # intervals the grid gives it
    # The metronome's reading across it: + a beat too many, - too few, 0 the
    # count is right; None where the stretch's sides are too ragged to read.
    jump: float | None


def _mark_phase(times: list[float], downbeats: list[float], lo: float, hi: float, pulses: int):
    """The commonest grid phase of the tracker's downbeat marks in [lo, hi],
    or None with fewer than DOUBT_MIN_MARKS of them on the grid."""
    votes: Counter[int] = Counter()
    for mark in downbeats:
        if lo <= mark <= hi:
            k = nearest_index(times, mark)
            if abs(times[k] - mark) <= 0.05:
                votes[k % pulses] += 1
    if sum(votes.values()) < DOUBT_MIN_MARKS:
        return None
    return votes.most_common(1)[0][0]


def grid_doubts(
    beats: list[Beat],
    tolerance: float = 0.15,
    downbeats: list[float] | None = None,
    pulses: int = 4,
) -> list[Doubt]:
    """The stretches of a repaired grid whose count is in doubt (see the note
    above). A stretch runs between consecutive FOUND beats, any implied ones
    between them its count, and overlapping doubted runs are one doubt; the
    listener's pins and the window laid out around them, and beats
    extrapolated past the tracker's range, are never in doubt -- the first
    are a judgement, the second hold no count. With the tracker's
    `downbeats`, a doubt they keep one phase across (`pulses` to the bar) is
    settled."""
    if len(beats) < 4:
        return []
    times = [b.time for b in beats]
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    reference = reference_pulse(intervals)
    found = [i for i, b in enumerate(beats) if not b.implied and not b.extrapolated]

    def held(a: int, b: int) -> float:
        pulse = statistics.median(reference[a:b])
        return (times[b] - times[a]) / pulse if pulse > 0 else float(b - a)

    runs: list[list[int]] = []
    for n, a in enumerate(found):
        for b in found[n + 1 : n + 1 + DOUBT_REACH]:
            if any(_in_window(beats[i]) for i in range(a, b + 1)):
                break
            if abs(held(a, b) - (b - a)) > DOUBT_RESIDUAL:
                if runs and a <= runs[-1][1]:
                    runs[-1][1] = max(runs[-1][1], b)
                else:
                    runs.append([a, b])
    doubts = []
    for a, b in runs:
        jump = metronome_jump(times, a, b, tolerance)
        if jump is not None and abs(jump) <= GHOST_JUMP_FIT:
            continue
        if downbeats:
            before = _mark_phase(times, downbeats, times[a] - DOUBT_MARK_REACH_S, times[a], pulses)
            after = _mark_phase(times, downbeats, times[b], times[b] + DOUBT_MARK_REACH_S, pulses)
            if before is not None and before == after:
                continue
        doubts.append(Doubt(times[a], times[b], round(held(a, b), 2), b - a, jump))
    return doubts


def repair_beats(
    beats: list[float], config: MeterConfig, downbeats: list[float] | None = None
) -> list[Beat]:
    """Insert beats the tracker dropped, and drop the ones it doubled, so the
    bar count stays true.

    `downbeats` is the tracker's downbeat layer, consulted for one thing
    only: whether the grid's modal interval is the wrong octave
    (`pulse_octave`). Bars are still never counted from it.

    This is correctness, not cosmetics: a single missed beat shifts every bar
    line after it by one beat for the rest of the tune — and so does a single
    doubled one, in the other direction (drop_doubled_beats).

    How many to insert comes from the reference pulse; *where* they go is an
    even subdivision of the observed gap. That split matters — deriving the
    positions from an extrapolated grid instead would drift, because the tune's
    tempo genuinely moves (Corner Pocket's intro runs nearer 146bpm than the
    body's 136). The detected beats are real; only the holes are guesses.
    """
    if len(beats) < 2:
        return [Beat(t) for t in beats]
    if not config.repair_beats:
        return [Beat(t) for t in beats]

    seed = pulse_octave(beats, downbeats or [])
    beats = drop_doubled_beats(beats, config.stability_tolerance, seed)
    beats = drop_ghost_beats(beats, config.stability_tolerance, seed)
    intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    reference = reference_pulse(intervals, seed)

    out = [Beat(beats[0])]
    for index, gap in enumerate(intervals):
        pulse = reference[index]
        count = max(1, round(gap / pulse)) if pulse > 0 else 1
        # A very wide gap is a hole in the tracking, not a run of missed beats.
        # Leave it alone and let metrical_spans break the grid there.
        if 2 <= count <= config.max_implied_run:
            step = gap / count
            for k in range(1, count):
                out.append(Beat(beats[index] + k * step, implied=True))
        out.append(Beat(beats[index + 1]))
    return thin_by_metronome(out, config.stability_tolerance)


# A stretch the metronome reads as WHOLE beats too many (2026-10-02, R34):
# not one ghost but a ragged stretch -- Totem Pole's three, each read +2.0
# on steady bars either side, where the grid gained a beat or two against
# the annotation every time. It is re-laid exactly as a pin's window is
# (`_relay`, the tracker's own beats kept where they sit on the new
# subdivision) with the count the time holds. Only ever THINNED: rounding
# already agrees with the metronome where a beat is missing (the mirror
# measurement above), and a rule that could add a beat put one back where
# the ghost rule had just taken one out, on Limehouse Blues. Measured with
# the ghost rule in: Totem Pole +5.9 -> -0.1 beats over the solo, In 'n Out
# +9.5 -> +8.5, nothing else in a solo moved; 65 -> 66 within a beat.
#
# A WHOLE BAR too many is thinned too (2026-10-04, R35): Bud Powell's
# Oblivion, tracked at half speed, came out of 70.3-74.2 s as two streams
# 0.08 s apart, 24 beats where the time holds 20. Two doubts lay within one
# metronome side of each other, so neither could be read alone (each one's
# side ran through the other), and four beats too many in 4/4 keeps the
# tracker's downbeat marks in phase, so the doubt list called it settled and
# drew no "?". The roll left the stretch barless (bar 49 to bar 50 across
# five bars of time) and the page, which counts by index, wrote six bars
# there. Now a doubt the metronome cannot read is read again across the
# doubts crowding its right side, and the cap is four beats, a bar of 4/4.
THIN_JUMP_FIT = 0.3
THIN_MAX_EXTRA = 4


def _metronome_readings(beats: list[Beat], tolerance: float):
    """(start, end, jump) for every doubted stretch (`grid_doubts`), and,
    where a doubt reads None because the next one lies within `GHOST_SIDE`
    intervals of it, the run of them read across as one stretch."""
    doubts = grid_doubts(beats, tolerance)
    times = [b.time for b in beats]
    index = {t: i for i, t in enumerate(times)}
    for n, doubt in enumerate(doubts):
        yield doubt.start, doubt.end, doubt.jump
        if doubt.jump is not None:
            continue
        end = index[doubt.end]
        for later in doubts[n + 1 :]:
            if index[later.start] - end > GHOST_SIDE:
                break
            end = index[later.end]
            jump = metronome_jump(times, index[doubt.start], end, tolerance)
            if jump is not None:
                yield doubt.start, later.end, jump
                break


def thin_by_metronome(beats: list[Beat], tolerance: float) -> list[Beat]:
    """Re-lay every doubted stretch (`_metronome_readings`) whose metronome
    reading is within THIN_JUMP_FIT of a whole number of beats too many,
    with that many fewer. The new beats are the repair's own, never
    `relaid`: that flag is the listener's (`apply_pins`)."""
    for _ in range(len(beats)):
        for start, end, jump in _metronome_readings(beats, tolerance):
            if jump is None:
                continue
            extra = round(jump)
            if not 1 <= extra <= THIN_MAX_EXTRA or abs(jump - extra) > THIN_JUMP_FIT:
                continue
            times = [b.time for b in beats]
            a, b = times.index(start), times.index(end)
            if b - a - extra < 1:
                continue
            # Only FOUND beats may keep their place: an implied one is the
            # insertion's guess at the count this re-lay just corrected.
            found = [x for x in beats[a + 1 : b] if not x.implied]
            laid = _relay(start, end, b - a - extra, found)
            beats = [*beats[: a + 1], *(replace(x, relaid=False) for x in laid), *beats[b:]]
            break
        else:
            return beats
    return beats


# ── beats the listener pinned (roadmap O5, 2026-09-30) ──────────────────────
#
# The repair above mends what it can see, and some slips it cannot: on Dexter
# Gordon's Cheese Cake a doubled beat at 160.48/160.60 s (0.20 + 0.12 s on a
# 0.26 s pulse) misses the one-pulse test by a millisecond, and every bar
# line after it -- 32 bars of the page -- sits a beat late. The downbeat is
# one click, but it is a PHASE: moving it puts the bars after the slip right
# and the bars before it wrong. A pin is the local fix: "a beat is HERE".
#
# The grid passes through every pin, and the beats around it are re-derived
# so that the count is whole: every beat nearer a pin than half a pulse gives
# way to it, and between the pin and the nearest STEADY tracked beat either
# side (or the next pin) the beats are laid out again -- as many as the time
# between them holds at the local pulse, each the tracker's own beat where
# one sits near its place, an implied one where none does. The count across
# that window is taken from TIME, which is what mends a slip: the repaired
# grid had four beats between 160.02 and 160.84 s, the time holds three.
# Between two pins the count is theirs; a pin half a beat off the tracker
# moves beats and never adds one (the window keeps the count its ends hold,
# and is widened a steady beat each side at a time when that time holds too
# few intervals for the pins to stand in). Two pins within half a pulse of
# each other are one (`_one_pin_per_beat`).
#
# The window's intervals are the LISTENER'S (`Beat.relaid`), and everything
# that measures the tracker's steadiness treats them so (2026-09-30, the
# review of O5): `steady_intervals` takes them as steady, the reference
# pulse counts each run of them as its mean (`_window_votes`), and
# `bar_grid` hands every interval the pins left alone the unpinned grid's
# answers (`Judgement`) and extends the edges at the unpinned grid's pulses
# (`extend_beats`). Judged on the tolerance like the tracker's,
# a pin that moves a beat by a fifth of a pulse -- a tap 50 ms off at 220
# bpm, or a pin on one of a slip's crowded beats rather than between them --
# leaves the interval on each side outside it, two unsteady intervals in a
# row split the bar grid at the pin, and the split loses a bar line and
# numbers every bar after it one lower (on the roll and the chord chart,
# not on the page, whose phase is an index): 34 of 210 such taps on Cheese
# Cake did. A pin vouches for its window and decides nothing outside it.
#
# A pin is a sidecar judgement (`beat_pins`), like a downbeat but never in
# MeterConfig: the pipeline's meter stage does not see it, no cache key
# moves, and every consumer that does see it -- the roll, the page, Export,
# the chord chart, Find the solos, the Score button, the harness -- reaches
# it through `bar_grid`, the one function.

# Tracked beats nearer a pin than this share of the local pulse give way to it.
PIN_CLEAR = 0.5
# A tracked beat within this share of a re-derived step of its place keeps its
# own time: the tracker's micro-timing is evidence, the lattice only a guess.
PIN_SNAP = 0.25
# How far either side of a pin (in beats) to look for a steady beat to
# re-derive from. A stretch longer than this with none is re-derived to here.
PIN_REACH = 16
# Two pins nearer than this are one: a double click, not two beats.
PIN_MIN_GAP_S = 0.05
# A pin window's pulse is the median of at least this many intervals between
# two steady beats, sought up to this many beats beyond the window's ends.
PIN_PULSE_MIN = 4
PIN_PULSE_REACH = 4 * REFERENCE_WINDOW


def clean_pins(values: Iterable | None) -> list[float]:
    """What a sidecar or a query may hold as pins: sorted, finite,
    non-negative seconds, one per beat (`PIN_MIN_GAP_S`). Anything else --
    a string, a None, a hand-edited sidecar -- is dropped, not raised."""
    out: list[float] = []
    for value in sorted(
        float(v)
        for v in (values or [])
        if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
    ):
        if not out or value - out[-1] >= PIN_MIN_GAP_S:
            out.append(value)
    return out


def _round_half_up(value: float) -> int:
    """Deterministic rounding for a beat count: Python's round() sends 1.5
    and 2.5 different ways."""
    return math.floor(value + 0.5)


def _steady_beats(times: list[float], beats: list[Beat], tolerance: float) -> list[bool]:
    """Which beats a pin's window may end on: found by the tracker, and every
    interval beside it within `tolerance` of the reference pulse."""
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    reference = reference_pulse(intervals)

    def ok(k: int) -> bool:
        return abs(intervals[k] - reference[k]) <= tolerance * reference[k]

    steady = []
    for i, beat in enumerate(beats):
        sides = [k for k in (i - 1, i) if 0 <= k < len(intervals)]
        steady.append(not beat.implied and bool(sides) and all(ok(k) for k in sides))
    return steady


def _relay(start: float, end: float, count: int, candidates: list[Beat]) -> list[Beat]:
    """`count - 1` beats strictly between two fixed ones, evenly placed, each
    the nearest candidate beat when one is within `PIN_SNAP` of a step of
    its place. Every one is `relaid`."""
    if count <= 1:
        return []
    step = (end - start) / count
    out = []
    for k in range(1, count):
        ideal = start + k * step
        near = min(candidates, key=lambda b: abs(b.time - ideal), default=None)
        if near is not None and abs(near.time - ideal) <= PIN_SNAP * step:
            out.append(replace(near, relaid=True))
        else:
            out.append(Beat(ideal, implied=True, relaid=True))
    return out


def _one_pin_per_beat(pins: list[float], pulse_at) -> list[float]:
    """Pins nearer each other than `PIN_CLEAR` of the local pulse claim one
    beat between them: keeping both makes a beat of 50-200 ms. The earlier
    is kept. The GUI never sends two -- a new pin that near replaces the old
    one there -- so this is for a hand-edited sidecar."""
    kept: list[float] = []
    for pin in pins:
        if not kept or pin - kept[-1] > PIN_CLEAR * pulse_at(pin) + 1e-9:
            kept.append(pin)
    return kept


def apply_pins(beats: list[Beat], pins: Iterable | None, config: MeterConfig) -> list[Beat]:
    """The repaired grid made to pass through every pin, with the beats
    around each re-derived so the count is whole (see the note above)."""
    pins = clean_pins(pins)
    if not pins:
        return list(beats)
    if len(beats) < 2:
        merged = [b for b in beats if all(abs(b.time - p) >= PIN_MIN_GAP_S for p in pins)]
        return sorted([*merged, *(Beat(p, pinned=True) for p in pins)], key=lambda b: b.time)

    times = [b.time for b in beats]
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    reference = reference_pulse(intervals)
    steady = _steady_beats(times, beats, config.stability_tolerance)

    def pulse_at(when: float) -> float:
        k = min(max(bisect.bisect_right(times, when) - 1, 0), len(intervals) - 1)
        return reference[k]

    pins = _one_pin_per_beat(pins, pulse_at)
    cleared = set()
    for pin in pins:
        reach = PIN_CLEAR * pulse_at(pin) + 1e-9  # exactly half a beat gives way
        lo = bisect.bisect_left(times, pin - reach)
        hi = bisect.bisect_right(times, pin + reach)
        cleared.update(range(lo, hi))

    def bound(pin: float, side: int, stop: float | None) -> int | None:
        """Index of the beat a pin's window ends on that side: the nearest
        steady uncleared beat within reach, else the last uncleared one
        reached; None if the next pin (`stop`) or the grid's edge comes
        first."""
        i = bisect.bisect_left(times, pin) - 1 if side < 0 else bisect.bisect_right(times, pin)
        last = None
        for _ in range(PIN_REACH):
            if not 0 <= i < len(times):
                break
            if stop is not None and (times[i] <= stop if side < 0 else times[i] >= stop):
                return None
            if i not in cleared:
                last = i
                if steady[i]:
                    return i
            i += side
        return last

    # Clusters of pins whose windows meet: no steady beat between them.
    clusters: list[list[float]] = [[pins[0]]]
    for pin in pins[1:]:
        if bound(clusters[-1][-1], +1, pin) is None:
            clusters[-1].append(pin)
        else:
            clusters.append([pin])

    def further(index: int, side: int, floor: int | None, ceiling: float | None) -> int | None:
        """The next steady uncleared beat past `index` on that side, within
        reach -- never below `floor` (an index) nor at or past `ceiling` (a
        time) -- or None."""
        i = index + side
        for _ in range(PIN_REACH):
            if not 0 <= i < len(times):
                return None
            if (floor is not None and i < floor) or (ceiling is not None and times[i] >= ceiling):
                return None
            if i not in cleared and steady[i]:
                return i
            i += side
        return None

    def layout(cluster: list[float], left: int | None, right: int | None):
        """The window's two end times and how many intervals each stretch
        between them holds: the pins' own, and either side of them."""
        lo_time = times[left] if left is not None else cluster[0]
        hi_time = times[right] if right is not None else cluster[-1]
        # The pulse is MEASURED between pairs of steady beats around the
        # window, never read off the reference inside it: the reference is a
        # rolling median, and through a ragged stretch longer than its window
        # it drifts with the jitter (0.519 s on a 0.5 s pulse over 24
        # jittered beats), which over a 13.5 s window counts one interval
        # short and moves every bar after it. Jittered intervals pass the
        # steadiness test against that drifted reference by chance, so only
        # an interval whose BOTH beats are steady is a measurement, and a
        # window that ends on such a chance beat inside the stretch looks
        # further out for them (`PIN_PULSE_MIN` of them, `PIN_PULSE_REACH`).
        first = left if left is not None else bisect.bisect_left(times, cluster[0])
        last = right if right is not None else bisect.bisect_right(times, cluster[-1]) - 1
        window: list[float] = []
        for margin in range(REFERENCE_WINDOW, PIN_PULSE_REACH + 1, REFERENCE_WINDOW):
            span = range(max(first - margin, 0), min(last + margin, len(intervals)))
            window = [intervals[k] for k in span if steady[k] and steady[k + 1]]
            if len(window) >= PIN_PULSE_MIN:
                break
        if not window:
            window = [reference[k] for k in range(len(intervals)) if lo_time <= times[k] < hi_time]
        pulse = statistics.median(window) if window else pulse_at(cluster[0])

        def count(a: float, b: float) -> int:
            return max(1, _round_half_up((b - a) / pulse))

        inner = [count(a, b) for a, b in zip(cluster, cluster[1:], strict=False)]
        n_left = count(lo_time, cluster[0]) if left is not None else 0
        n_right = count(cluster[-1], hi_time) if right is not None else 0
        fits = True
        if left is not None and right is not None:
            # The window keeps the count its two ends hold, measured in TIME:
            # whatever the pins do not claim between them goes either side.
            outer = _round_half_up((hi_time - lo_time) / pulse) - sum(inner)
            fits = outer >= 2
            if fits:
                n_left = min(max(1, n_left), outer - 1)
                n_right = outer - n_left
        return lo_time, hi_time, [n_left, *inner, n_right], fits

    removed = set(cleared)
    new: list[Beat] = []
    previous_right: int | None = None
    for number, cluster in enumerate(clusters):
        left = bound(cluster[0], -1, None)
        right = bound(cluster[-1], +1, None)
        if previous_right is not None and (left is None or left < previous_right):
            left = previous_right  # two windows share an end, never overlap
        ceiling = clusters[number + 1][0] if number + 1 < len(clusters) else None
        lo_time, hi_time, counts, fits = layout(cluster, left, right)
        # A pin between two beats each just over half a pulse away (a jittered
        # 1.07-pulse interval) clears neither, and the time between them holds
        # ONE interval where the pin needs two: the count would gain a beat
        # and every bar after it would move. Widen the window, a steady beat
        # each side at a time, until the time holds the pins.
        while not fits and left is not None and right is not None:
            wider_left = further(left, -1, previous_right, None)
            wider_right = further(right, +1, None, ceiling)
            if wider_left is None and wider_right is None:
                break
            left = left if wider_left is None else wider_left
            right = right if wider_right is None else wider_right
            lo_time, hi_time, counts, fits = layout(cluster, left, right)
        previous_right = right

        # Everything strictly inside the window is laid out again; its two
        # ends (steady tracked beats, or the pins themselves at an edge of
        # the grid) stay where they are.
        inside = [i for i in range(len(beats)) if lo_time < times[i] < hi_time]
        removed.update(inside)
        candidates = [beats[i] for i in inside if i not in cleared]
        points = [lo_time, *cluster, hi_time]
        for (a, b), n in zip(zip(points, points[1:], strict=False), counts, strict=True):
            if b > a:
                new.extend(_relay(a, b, n, [x for x in candidates if a < x.time < b]))
        new.extend(Beat(pin, pinned=True) for pin in cluster)

    kept = [beat for i, beat in enumerate(beats) if i not in removed]
    return sorted([*kept, *new], key=lambda beat: beat.time)


# ── stretches the listener marked steady (2026-10-05) ───────────────────────
#
# Where the tracker follows something other than the beat for a while, the
# repair has nothing to mend it with. Bud Powell's Oblivion, bars 75-84:
# the tracker (at half speed) locked onto Powell's three-note groupings, a
# pulse every one and a half beats, half of whose marks fall on an "and";
# the insertion read each 1.5-beat gap as two and the ten bars gained five
# beats. The tempo never moved -- a constant 0.2175 s from page bar 73 puts
# bar 84 where Powell's page has it -- and the tracker kept the lock past
# the solo's end, so there were no steady bars after it for the metronome
# (`thin_by_metronome`) to bridge to. A pin cannot mend it either: with one
# on every bar, the stretch still held 46 beats where the music has 44.
#
# Over every cached grid that shape (three or more gaps at 1.3-1.75 pulses)
# falls inside a scored span twice, both on Oblivion, so it is no rule's to
# guess: the listener marks the stretch, and says by doing so that the
# tempo held. Its beats are laid on one metronome, and the tracker's beats
# inside it are NOT evidence -- the stretch is where the listener says the
# tracker went wrong. Following them was tried first: in Oblivion's lock
# they sit 0.05-0.1 s off the beat (Powell's swung accents), each one taken
# dragged the line later, and forty beats on it had lost one.
#
# The metronome is fitted to the steady beats either side (`_side_fit`:
# STEADY_LONG intervals where they are steady, else STEADY_SIDE, sought up
# to STEADY_SIDE beats outward so a stretch marked from inside the trouble
# is laid from the last steady bars before it). With both sides, the count
# between them is the time over their pulse, evenly laid -- exact, as a
# re-laid ghost stretch is. With one, the side's pulse is continued to the
# stretch's far end; four bars read Oblivion's tempo 2% fast (the band
# eased from 0.220 to 0.2175 s over the solo), so eight are preferred. A
# pin inside the stretch is a fixed point on it: the count to it is taken
# from time, and past the last one the pulse is the one the pins measured.
# Everything laid is the listener's (`relaid`), as a pin's window is:
# steady, and never in doubt.
STEADY_SIDE = 16  # intervals a side's metronome is fitted to, at least
STEADY_LONG = 32  # ... and preferred, where that many are steady
STEADY_SIDE_FIT = 0.25  # a side's beats must all sit within this of its line
STEADY_IMPLIED = 1 / 3  # ... and the tracker must have found most of them
STEADY_WHOLE = 0.35  # both sides on one metronome: the time between is whole
STEADY_MIN_S = 0.5  # a shorter stretch is a slip of the mouse


def clean_steady(values: Iterable | None) -> list[tuple[float, float]]:
    """What a sidecar or a query may hold as steady stretches: [start, end]
    pairs of finite, non-negative seconds at least STEADY_MIN_S long, sorted,
    with overlapping ones merged. Anything else is dropped, not raised."""
    pairs = []
    for value in values or []:
        if not isinstance(value, list | tuple) or len(value) != 2:
            continue
        a, b = value
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (a, b)):
            continue
        a, b = float(a), float(b)
        if not (math.isfinite(a) and math.isfinite(b)) or a < 0 or b - a < STEADY_MIN_S:
            continue
        pairs.append((round(a, 3), round(b, 3)))
    merged: list[tuple[float, float]] = []
    for a, b in sorted(pairs):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _side_pulse(times: list[float], found: list[bool], tolerance: float) -> float | None:
    """The pulse of a run of beats on one metronome, least squares of time
    on beat number, or None when they are not steady enough to lay one
    from: every beat within STEADY_SIDE_FIT of the line, and every step
    between neighbouring FOUND beats within `tolerance` of the pulses it
    holds. The repair's halves of a gap say nothing: a lock's 1.78-beat gap
    split in two is two 0.89-beat steps, inside the tolerance, while the
    gap itself is not whole (as `steady_intervals` judges an implied run).
    Numbered by time over the median interval rather than by index, so a
    stray beat in the run does not stretch the pulse it gives."""
    if len(times) < 4:
        return None
    seed = statistics.median(b - a for a, b in zip(times, times[1:], strict=False))
    if seed <= 0:
        return None
    numbered = {round((t - times[0]) / seed): (t, ok) for t, ok in zip(times, found, strict=True)}
    points = sorted((k, t) for k, (t, _ok) in numbered.items())
    n = len(points)
    if n < 4:
        return None
    mean_k = sum(k for k, _ in points) / n
    mean_t = sum(t for _, t in points) / n
    pulse = sum((k - mean_k) * (t - mean_t) for k, t in points) / sum(
        (k - mean_k) ** 2 for k, _ in points
    )
    if pulse <= 0:
        return None
    offset = mean_t - pulse * mean_k
    if any(abs(t - offset - pulse * k) > STEADY_SIDE_FIT * pulse for k, t in points):
        return None
    heard = [(k, t) for k, (t, ok) in sorted(numbered.items()) if ok]
    steps = zip(heard, heard[1:], strict=False)
    if any(abs(t2 - t1 - (k2 - k1) * pulse) > tolerance * pulse for (k1, t1), (k2, t2) in steps):
        return None
    return pulse


def _side_fit(beats: list[Beat], side: int, tolerance: float) -> tuple[float, float] | None:
    """(the edge beat, its pulse) for the steady run nearest a stretch on
    one side: `beats` are the grid's on that side in time order, `side` -1
    for the beats before the stretch and +1 for those after. A run the
    insertion made more than STEADY_IMPLIED of is not a measurement: it is
    evenly spaced because it was laid that way (Oblivion's tail after the
    solo, the tracker's 0.35 s split in two, read as a 0.176 s pulse)."""
    ordered = beats if side < 0 else list(reversed(beats))
    for shift in range(STEADY_SIDE + 1):
        stop = len(ordered) - shift
        for length in (STEADY_LONG, STEADY_SIDE):
            run = ordered[max(0, stop - length - 1) : stop]
            if len(run) < length + 1 or sum(b.implied for b in run) > STEADY_IMPLIED * len(run):
                continue
            if run[-1].implied:  # the edge the stretch is laid from was heard
                continue
            if side > 0:
                run = list(reversed(run))
            times = [b.time for b in run]
            pulse = _side_pulse(times, [not b.implied for b in run], tolerance)
            if pulse is not None:
                return (times[-1] if side < 0 else times[0]), pulse
    return None


def _counted(a: float, b: float, pulse: float) -> tuple[int, float]:
    """How many beats the time from `a` to `b` holds at `pulse`, and the
    pulse that count lays them at."""
    count = max(1, _round_half_up((b - a) / pulse))
    return count, (b - a) / count


def apply_steady(
    beats: list[Beat],
    stretches: Iterable | None,
    config: MeterConfig,
    pins: Iterable | None = None,
) -> list[Beat]:
    """The grid with every stretch the listener marked steady laid on one
    metronome (see the note above), through the `pins` inside it. A stretch
    with no steady beats on either side to take the tempo from is left as
    it is."""
    out = list(beats)
    pins = clean_pins(pins)
    for start, end in clean_steady(stretches):
        tolerance = config.stability_tolerance
        left = _side_fit([b for b in out if b.time <= start], -1, tolerance)
        right = _side_fit([b for b in out if b.time >= end], +1, tolerance)
        if left and right:
            # The listener asked for the tempo of the bars BEFORE; the bars
            # after count only as the same metronome -- the same pulse, and
            # a whole number of beats from the left edge.
            mean = (left[1] + right[1]) / 2
            held = (right[0] - left[0]) / mean
            if abs(left[1] - right[1]) > tolerance * mean or abs(held - round(held)) > STEADY_WHOLE:
                right = None
        if left is None and right is None:
            continue
        lo = left[0] if left else start
        hi = right[0] if right else end
        # The pins in the listener's own stretch; one between it and a side
        # sought further out is an ordinary pin (`bar_grid` applies it).
        fixed = [p for p in pins if lo < p < hi and start <= p <= end]
        anchors = [*([lo] if left else []), *fixed, *([hi] if right else [])]
        pulse = (left[1] + right[1]) / 2 if left and right else (left or right)[1]
        laid = [Beat(p, pinned=True) for p in fixed]
        for a, b in zip(anchors, anchors[1:], strict=False):
            count, _step = _counted(a, b, pulse)
            laid.extend(replace(x, relaid=True) for x in _relay(a, b, count, []))
        if not right:  # continue past the last fixed point to the far end
            step = _counted(*anchors[-2:], pulse)[1] if len(anchors) > 1 else pulse
            tick = anchors[-1] + step
            while tick <= end:
                laid.append(Beat(tick, implied=True, relaid=True))
                tick += step
            hi = max(b.time for b in laid) + PIN_CLEAR * step if laid else anchors[-1]
        if not left:  # and back before the first, from the right side
            step = _counted(*anchors[:2], pulse)[1] if len(anchors) > 1 else pulse
            tick = anchors[0] - step
            while tick >= start:
                laid.append(Beat(tick, implied=True, relaid=True))
                tick -= step
            lo = min(b.time for b in laid) - PIN_CLEAR * step if laid else anchors[0]
        kept = [b for b in out if not lo < b.time < hi]
        out = sorted([*kept, *laid], key=lambda b: b.time)
    return out


def _edge_pulse(window: list[Beat], config: MeterConfig) -> float | None:
    """The pulse to continue outward, or None if this edge isn't steady.

    The value comes from the repaired spacing (which is the true rate even
    where the tracker was running at half of it), but steadiness is judged
    on the *detected* beats alone. Judging the repaired ones would be
    circular: repair makes a ragged head evenly spaced, so it would always
    look steady enough to extrapolate from.
    """
    spacing = [b.time - a.time for a, b in zip(window, window[1:], strict=False)]
    if len(spacing) < 3:
        return None
    pulse = statistics.median(spacing)
    if pulse <= 0:
        return None

    detected = [b.time for b in window if not b.implied]
    gaps = [b - a for a, b in zip(detected, detected[1:], strict=False)]
    if len(gaps) < 3:
        return None
    seed = statistics.median(gaps)
    if seed <= 0:
        return None
    # Divide out each gap's multiplier first, so a passage tracked at half
    # rate still reads as steady rather than as an error.
    implied = [gap / max(1, round(gap / seed)) for gap in gaps]
    reference = statistics.median(implied)
    if reference <= 0:
        return None
    spread = max(abs(value - reference) / reference for value in implied)
    return pulse if spread <= config.stability_tolerance else None


def _extend(
    beats: list[Beat],
    config: MeterConfig,
    start_limit: float,
    end_limit: float,
    pulses: tuple[float | None, float | None] | None = None,
) -> tuple[list[Beat], tuple[float | None, float | None]]:
    """`extend_beats`, and the (head, tail) pulses it continued at."""
    if not config.extend_to_edges or len(beats) < 4:
        return beats, (None, None)
    out = list(beats)

    head = _edge_pulse(out[:12], config) if pulses is None else pulses[0]
    if head is not None:
        first = out[0].time
        added = []
        time = first - head
        while time >= start_limit and first - time <= config.max_extend_seconds:
            added.append(Beat(round(time, 6), implied=True, extrapolated=True))
            time -= head
        out = list(reversed(added)) + out

    tail = _edge_pulse(out[-12:], config) if pulses is None else pulses[1]
    if tail is not None:
        last = out[-1].time
        time = last + tail
        while time <= end_limit and time - last <= config.max_extend_seconds:
            out.append(Beat(round(time, 6), implied=True, extrapolated=True))
            time += tail
    return out, (head, tail)


def extend_beats(
    beats: list[Beat],
    config: MeterConfig,
    start_limit: float,
    end_limit: float,
    pulses: tuple[float | None, float | None] | None = None,
) -> list[Beat]:
    """Continue a steady edge pulse out to the ends of the track.

    Neural beat trackers routinely emit nothing for the first seconds of a file:
    Corner Pocket plays at full level from 0.0s but has no detected beat until
    5.86s, so without this its first five bars are simply missing. The head is
    in tempo — it is the tracking that starts late, not the band.

    Two guards keep this from papering over a genuinely free intro: the edge
    pulse must itself be steady, and the extension is capped in seconds.

    `pulses` -- (head, tail), None for an edge not to extend -- takes the
    place of the edge test. A pinned grid is extended at the UNPINNED grid's
    pulses (`bar_grid`): steadiness is a fact about the tracker's edge beats,
    and a pin among them is the listener's, not a measurement. Judged on the
    pinned beats, a pin a fifth of a pulse off one of the last twelve took
    the extension away (Cheese Cake's last nine bar lines, a ballad's last
    two), or gave one to an edge the tracker had left ragged.
    """
    return _extend(beats, config, start_limit, end_limit, pulses)[0]


def _window_votes(intervals: list[float], vouched: list[bool]) -> list[float]:
    """The intervals as they vote for the reference pulse: each run of a
    pin's window (`vouched`) votes as its MEAN, the pulse it was laid out
    at. A pin moves a beat between two others and leaves their sum alone,
    so its uneven pair (0.709 + 0.436 s where the tracker had 0.581 +
    0.564) votes as the tracker's did. It matters only where a pinned grid
    is judged afresh -- an interval the unpinned grid does not have, such
    as an extension continued from a moved edge beat (`Judgement`) -- but
    there, voting as they stand, the outliers moved the rolling median a
    few milliseconds, enough to flip a whole-gap test that sat on its
    threshold."""
    votes = list(intervals)
    k = 0
    while k < len(intervals):
        if not vouched[k]:
            k += 1
            continue
        end = k
        while end < len(intervals) and vouched[end]:
            end += 1
        mean = sum(intervals[k:end]) / (end - k)
        votes[k:end] = [mean] * (end - k)
        k = end
    return votes


def _in_window(beat: Beat) -> bool:
    """Pinned, or laid out again around a pin: the listener's word rather
    than the tracker's (`apply_pins`)."""
    return beat.pinned or beat.relaid


def _vouched(beats: list[Beat]) -> list[bool]:
    """Per interval: is it beside a beat of a pin's window?"""
    return [_in_window(a) or _in_window(b) for a, b in zip(beats, beats[1:], strict=False)]


@dataclass(frozen=True)
class Judgement:
    """The unpinned grid's answers, which every interval a pin leaves alone
    keeps (`bar_grid`), so that a pin decides nothing outside its window.

    Judged afresh, a pin's new intervals moved the rolling reference pulse
    a few milliseconds, and a whole-gap test six seconds away that had
    passed by a millisecond failed and split the grid there; and on a
    tracker's 20 ms frame grid a gap of exactly two pulses sits ON the
    bridge threshold, where a median moved by 2e-15 s split Ko Ko in four
    places 47 s from the pin.
    """

    steady: dict[tuple[float, float], bool]  # per interval, by (start, end) time
    bridge_pulse: float  # what `metrical_spans` bridges a short hole against


def judge(beats: list[Beat], config: MeterConfig) -> Judgement:
    """This grid's answers, to hand a pinned version of it (`Judgement`)."""
    flags = steady_intervals(beats, config)
    return Judgement(
        steady={(a.time, b.time): ok for a, b, ok in zip(beats, beats[1:], flags, strict=False)},
        bridge_pulse=_bridge_pulse(beats),
    )


def _bridge_pulse(beats: list[Beat]) -> float:
    """The median interval, a pin's window voting as its mean."""
    intervals = [b.time - a.time for a, b in zip(beats, beats[1:], strict=False)]
    return statistics.median(_window_votes(intervals, _vouched(beats))) if intervals else 0.0


def steady_intervals(
    beats: list[Beat],
    config: MeterConfig,
    judged: Judgement | None = None,
) -> list[bool]:
    """Per interval: is the pulse steady across it? What `metrical_spans`
    builds its spans from.

    Every interval of a pin's window is steady, whatever the tolerance
    says: a pin that moves a beat by a fifth of a pulse leaves the interval
    on each side outside it, and two unsteady intervals in a row split the
    grid at the very place the pin mends. `judged` is the unpinned grid's
    answers: an interval the pins left alone keeps its own.
    """
    if len(beats) < 2:
        return []
    intervals = [b.time - a.time for a, b in zip(beats, beats[1:], strict=False)]
    vouched = _vouched(beats)
    # Measured against the reference pulse, NOT a rolling median of these
    # intervals. Repair subdivides irregular gaps into plausible-looking beats,
    # so a local median computed after repair adapts to a rubato passage and
    # declares it steady. The reference is globally seeded and only follows
    # genuine drift, so a free passage still reads as free.
    local = reference_pulse(_window_votes(intervals, vouched))

    steady = [
        reference > 0 and abs(gap - reference) / reference <= config.stability_tolerance
        for gap, reference in zip(intervals, local, strict=False)
    ]
    # A run of implied beats is an even subdivision of one detected gap, so
    # its intervals are within a fraction of the pulse of each other BY
    # CONSTRUCTION -- a gap of 3.7 pulses cut in four reads as steady on the
    # test above, and a free intro whose gaps happen to cut that way was
    # drawn with bar lines (So What's, for 23 seconds). The gap itself has
    # to be a whole number of pulses, within the tolerance of ONE pulse: the
    # tracker found both ends of it where the pulse says they are. A gap
    # that is not has no beats in it that anyone found.
    index = 0
    while index < len(beats):
        if not beats[index].implied or beats[index].extrapolated:
            index += 1
            continue
        end = index
        while end < len(beats) and beats[end].implied and not beats[end].extrapolated:
            end += 1
        first, last = index - 1, end  # the detected beats either side
        if first >= 0 and last < len(beats):
            gap = beats[last].time - beats[first].time
            reference = statistics.median(local[first:last])
            whole = abs(gap - (last - first) * reference) <= config.stability_tolerance * reference
            if not whole:
                for k in range(first, last):
                    steady[k] = False
        index = end

    if judged is not None:
        steady = [
            judged.steady.get((a.time, b.time), ok)
            for (a, b), ok in zip(zip(beats, beats[1:], strict=False), steady, strict=True)
        ]
    return [ok or vouch for ok, vouch in zip(steady, vouched, strict=True)]


def metrical_spans(
    beats: list[Beat],
    config: MeterConfig,
    judged: Judgement | None = None,
) -> list[tuple[int, int]]:
    """Maximal runs of beats with a steady pulse, as [start, end) index pairs.

    Time outside every span gets no bar lines — that is how a rubato intro or a
    free coda is represented, with no separate concept for it. Deliberately
    conservative: wrongly hiding bars the user wants is worse than drawing them
    through a slightly ragged passage. `judged`: the unpinned grid's answers
    (`Judgement`).
    """
    if len(beats) < 2:
        return []
    steady = steady_intervals(beats, config, judged)

    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, ok in enumerate(steady):
        if ok and start is None:
            start = index
        elif not ok and start is not None:
            spans.append((start, index + 1))
            start = None
    if start is not None:
        spans.append((start, len(beats)))

    pulse = judged.bridge_pulse if judged is not None else _bridge_pulse(beats)
    max_bridge_seconds = (BRIDGE_BEATS + 1) * pulse

    merged: list[tuple[int, int]] = []
    for span in spans:
        if merged:
            index_gap = span[0] - merged[-1][1]
            time_gap = beats[span[0]].time - beats[merged[-1][1] - 1].time
            if index_gap <= BRIDGE_BEATS and time_gap <= max_bridge_seconds:
                merged[-1] = (merged[-1][0], span[1])
                continue
        merged.append(span)

    # A span must begin and end on a beat the tracker found — or on one
    # extrapolated past the end of its range, which is a deliberate extension of
    # a pulse already shown to be steady. What must never bound a span is an
    # *interpolated* beat: those are evenly spaced because they were manufactured
    # that way, so one would happily anchor the grid inside a free passage.
    trimmed: list[tuple[int, int]] = []
    for start, end in merged:
        while start < end and beats[start].implied and not beats[start].extrapolated:
            start += 1
        while end > start and beats[end - 1].implied and not beats[end - 1].extrapolated:
            end -= 1
        if end > start:
            trimmed.append((start, end))

    # And the length test counts detected beats only: fabricated ones must not
    # be able to vote for their own passage being metrical.
    return [
        (a, b)
        for a, b in trimmed
        if sum(1 for beat in beats[a:b] if not beat.implied) >= config.min_span_beats
    ]


# The downbeat vote is taken this far either side of the span being notated.
AUTO_ANCHOR_MARGIN_S = 20.0
# Marked beats needed near the span before the local vote is believed; with
# fewer, the whole track votes as it always did.
AUTO_ANCHOR_MIN_MARKS = 4


def _auto_anchor(
    beats: list[Beat],
    downbeats: list[float],
    pulses: int,
    near: tuple[float, float] | None = None,
) -> int:
    """Index of the beat to treat as beat 1 when the user hasn't chosen one.

    The detected downbeat layer is noise, but it is *biased* noise, so the phase
    it agrees with most often beats a coin flip — and one click fixes it.

    `near` is the span being notated, and the vote is taken AROUND IT
    (2026-09-17, D32). A bar's phase is an index modulo the bar, and one beat
    the tracker dropped or doubled anywhere in a track shifts the phase of
    everything after it -- so over a whole track the majority describes
    whichever side of the slip is longer, which need not be the side the solo
    is on. Measured against 96 tracks whose true phase a reference gives
    (scripts/downbeat_truth.py): the whole-track vote names the right beat on
    53 of 63 WJazzD solos, the vote within 20 s of the span on 62; the
    Omnibook (22 of 22) and the listener's own (11 of 11) are right either
    way. The span alone reads 60 -- a short solo holds too few marks.
    """
    if not beats:
        return 0
    if not downbeats:
        return 0
    times = [b.time for b in beats]
    marked = set()
    for downbeat in downbeats:
        best = min(range(len(times)), key=lambda i: abs(times[i] - downbeat))
        if abs(times[best] - downbeat) <= 0.05:
            marked.add(best)
    if not marked:
        return 0
    voters = marked
    if near is not None:
        lo, hi = near[0] - AUTO_ANCHOR_MARGIN_S, near[1] + AUTO_ANCHOR_MARGIN_S
        local = {i for i in marked if lo <= times[i] <= hi}
        if len(local) >= AUTO_ANCHOR_MIN_MARKS:
            voters = local
    scores = [sum(1 for i in voters if i % pulses == phase) for phase in range(pulses)]
    return max(range(pulses), key=lambda phase: scores[phase])


def nearest_beat_index(beats: list[Beat], when: float) -> int:
    if not beats:
        return 0
    return min(range(len(beats)), key=lambda i: abs(beats[i].time - when))


def derive_sections(
    beats: list[Beat],
    downbeats: list[float],
    config: MeterConfig,
    near: tuple[float, float] | None = None,
    judged: Judgement | None = None,
) -> list[MeterSection]:
    """Bar grid for each metrical span, sharing one phase and one meter.

    The phase is global: `index % pulses == anchor % pulses` decides a bar line
    everywhere, so a span that does not contain the anchor still counts in step
    with it. Spans only gate *where* bars are drawn. So is the NUMBER (R35,
    2026-10-05): a section's `first_bar` counts every bar from the first
    section's first line by beat index, the bars in the free time between
    them included, which is how the page numbers them (it counts beats and
    knows no free time). Counting only the bars drawn numbered the roll's
    bar after Oblivion's four-second hole 50 where the page has 54, and
    numbered a span's last line and the next span's first line alike.
    `judged`: the unpinned grid's answers (`Judgement`).
    """
    signature, pulses = resolve_meter(config)
    spans = metrical_spans(beats, config, judged)
    if not beats or not spans:
        return []

    anchor_index = (
        nearest_beat_index(beats, config.anchor)
        if config.anchor is not None
        else _auto_anchor(beats, downbeats, pulses, near)
    )
    phase = anchor_index % pulses

    sections: list[MeterSection] = []
    bar_one: int | None = None  # beat index of the first line drawn
    previous_end: int | None = None
    for start, end in spans:
        first = next((i for i in range(start, end) if i % pulses == phase), None)
        if first is None or first + pulses > end:
            previous_end = end
            continue  # not even one whole bar fits in this span
        # A span reached across a hole in the tracking still counts in step, but
        # says so: the bars in the gap are counted on the repaired grid there,
        # and a beat the repair got wrong in it would shift the bar number.
        crossed = previous_end is not None and start > previous_end
        previous_end = end
        if bar_one is None:
            bar_one = first
        sections.append(
            MeterSection(
                start=beats[first].time,
                end=beats[end - 1].time,
                pulses_per_bar=pulses,
                time_signature=signature,
                anchor=beats[anchor_index].time,
                first_bar=1 + (first - bar_one) // pulses,
                confidence=0.75 if crossed else 1.0,
                origin="user" if config.anchor is not None else "auto",
            )
        )
    return sections


def bar_grid(
    beats: list[float],
    downbeats: list[float],
    config: MeterConfig,
    duration: float,
    near: tuple[float, float] | None = None,
    pins: Iterable | None = None,
    steady: Iterable | None = None,
) -> tuple[list[Beat], list[MeterSection]]:
    """The bar grid as the GUI draws it: tracked beats repaired, the
    stretches the listener marked `steady` laid on one metronome
    (`apply_steady`), made to pass through their `pins` (`apply_pins`) and
    extended to the track's ends, and sections counted from the anchor --
    the user's if they placed one, the downbeat layer's best phase if not.

    One function, because two callers have to agree on it exactly. The roll
    (`/beats`) draws bar lines from this, and the Export button counts its
    bars with it; when export derived its own grid it anchored on the first
    beat of its margin instead, and every bar on the page sat one beat off
    the bar lines on screen.

    A pin is LOCAL: every interval it leaves alone keeps the answers the
    unpinned grid gives it (`Judgement`), and the edges are extended at the
    unpinned grid's pulses (`extend_beats`). So is a steady stretch, and a
    pin inside one has the last word.
    """
    repaired = repair_beats(beats, config, downbeats)
    pins = [p for p in clean_pins(pins) if p <= duration]
    stretches = clean_steady(steady)
    if not pins and not stretches:
        repaired = extend_beats(repaired, config, 0.0, duration)
        return repaired, derive_sections(repaired, downbeats, config, near)
    unpinned, edges = _extend(repaired, config, 0.0, duration)
    # A pin inside a steady stretch is a fixed point of its metronome; the
    # rest re-derive the beats around them as always.
    steadied = apply_steady(repaired, stretches, config, pins)
    loose = [p for p in pins if not any(a <= p <= b for a, b in stretches)]
    pinned = extend_beats(apply_pins(steadied, loose, config), config, 0.0, duration, edges)
    return pinned, derive_sections(pinned, downbeats, config, near, judge(unpinned, config))


def bar_lines(
    beats: list[Beat],
    sections: list[MeterSection],
    form_start: float | None = None,
) -> list[tuple[float, int]]:
    """(time, bar number) for every bar line — what the GUI draws.

    `form_start` says where the tune's form begins, which is not always where
    the audio does: an intro or a vamp is not part of the song structure. Bar 1
    lands there and anything before it numbers zero or negative, so the caller
    can draw those lines without labelling them. The numbers count the bars of
    free time between sections too (`derive_sections`), so they are shifted,
    never re-counted from the lines drawn.
    """
    lines: list[tuple[float, int]] = []
    for section in sections:
        anchor_index = nearest_beat_index(beats, section.anchor)
        phase = anchor_index % section.pulses_per_bar
        bar = section.first_bar
        for index, beat in enumerate(beats):
            if not (section.start <= beat.time <= section.end):
                continue
            if index % section.pulses_per_bar == phase:
                lines.append((beat.time, bar))
                bar += 1

    if form_start is not None and lines:
        # Renumber so the bar nearest form_start becomes bar 1.
        _time, at_form = min(lines, key=lambda line: abs(line[0] - form_start))
        lines = [(time, number - at_form + 1) for time, number in lines]
    return lines


def span_of(config: Config, duration: float) -> tuple[float, float] | None:
    """The span being notated -- the transcribe region, an open end meaning
    the track's -- for the automatic downbeat to vote around. None is the
    whole track."""
    region = config.transcribe.region
    if region is None:
        return None
    start, end = region
    return (float(start), float(duration if end is None else end))


def run(document: Document, config: Config) -> Document:
    grid = document.beat_grid
    if grid is None or not grid.beats:
        return document.model_copy(update={"meter": []})
    duration = document.audio.duration if document.audio else grid.beats[-1]
    _beats, sections = bar_grid(
        grid.beats, grid.downbeats, config.meter, duration, near=span_of(config, duration)
    )
    return document.model_copy(update={"meter": sections})
