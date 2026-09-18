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

import statistics
from dataclasses import dataclass

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
CACHE_VERSION = 3


@dataclass(frozen=True)
class Beat:
    """One beat of the repaired grid."""

    time: float
    implied: bool = False  # inserted here, not found by the tracker
    # Implied *beyond* the tracker's range rather than between two of its beats.
    # Interpolation is bounded by evidence on both sides; extrapolation is not,
    # so the two are allowed to do different things (see metrical_spans).
    extrapolated: bool = False


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


def reference_pulse(intervals: list[float]) -> list[float]:
    """The pulse rate the tune is *actually* running at, per interval.

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
    # Global seed: mode at 10ms resolution, which is robust to a minority of
    # intervals sitting at a multiple of the true pulse.
    counts: dict[float, int] = {}
    for value in intervals:
        bucket = round(value, 2)
        counts[bucket] = counts.get(bucket, 0) + 1
    seed = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    if seed <= 0:
        seed = statistics.median(intervals)
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


def drop_doubled_beats(beats: list[float], tolerance: float) -> list[float]:
    """Remove the middle beat of a pair of intervals that together make one
    pulse, or of an isolated ragged short pair.

    The mirror of the insertion below, and the same harm: a beat the tracker
    doubled makes its bar a beat short and shifts every bar line after it by
    one beat for the rest of the tune. A doubled beat cannot be seen one
    interval at a time — each of its two short intervals rounds to one pulse
    on its own — so it is judged as a pair against the reference pulse. The
    left interval is taken on the KEPT sequence, so a run of doubled beats is
    thinned one by one and the merged interval then reads as ordinary.

    Not this function's problem: a grid tracked at HALF rate for most of a
    tune (Kenny Garrett's Brother Hubbard, 0.82 s on a 143 bpm tune). Its
    seed is the half-rate pulse, so the true beats surfacing in pairs are
    exactly what this thins -- the octave error is the defect there, open
    since R21, and a tempo hint (`beats.correct_octave`) is its repair.
    """
    if len(beats) < 4:
        return list(beats)
    intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    reference = reference_pulse(intervals)
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


def repair_beats(beats: list[float], config: MeterConfig) -> list[Beat]:
    """Insert beats the tracker dropped, and drop the ones it doubled, so the
    bar count stays true.

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

    beats = drop_doubled_beats(beats, config.stability_tolerance)
    intervals = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    reference = reference_pulse(intervals)

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
    return out


def extend_beats(
    beats: list[Beat], config: MeterConfig, start_limit: float, end_limit: float
) -> list[Beat]:
    """Continue a steady edge pulse out to the ends of the track.

    Neural beat trackers routinely emit nothing for the first seconds of a file:
    Corner Pocket plays at full level from 0.0s but has no detected beat until
    5.86s, so without this its first five bars are simply missing. The head is
    in tempo — it is the tracking that starts late, not the band.

    Two guards keep this from papering over a genuinely free intro: the edge
    pulse must itself be steady, and the extension is capped in seconds.
    """
    if not config.extend_to_edges or len(beats) < 4:
        return beats

    def edge_pulse(window: list[Beat]) -> float | None:
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

    out = list(beats)

    pulse = edge_pulse(out[:12])
    if pulse is not None:
        first = out[0].time
        added = []
        time = first - pulse
        while time >= start_limit and first - time <= config.max_extend_seconds:
            added.append(Beat(round(time, 6), implied=True, extrapolated=True))
            time -= pulse
        out = list(reversed(added)) + out

    pulse = edge_pulse(out[-12:])
    if pulse is not None:
        last = out[-1].time
        time = last + pulse
        while time <= end_limit and time - last <= config.max_extend_seconds:
            out.append(Beat(round(time, 6), implied=True, extrapolated=True))
            time += pulse
    return out


def metrical_spans(beats: list[Beat], config: MeterConfig) -> list[tuple[int, int]]:
    """Maximal runs of beats with a steady pulse, as [start, end) index pairs.

    Time outside every span gets no bar lines — that is how a rubato intro or a
    free coda is represented, with no separate concept for it. Deliberately
    conservative: wrongly hiding bars the user wants is worse than drawing them
    through a slightly ragged passage.
    """
    if len(beats) < 2:
        return []
    intervals = [b.time - a.time for a, b in zip(beats, beats[1:], strict=False)]
    # Measured against the reference pulse, NOT a rolling median of these
    # intervals. Repair subdivides irregular gaps into plausible-looking beats,
    # so a local median computed after repair adapts to a rubato passage and
    # declares it steady. The reference is globally seeded and only follows
    # genuine drift, so a free passage still reads as free.
    local = reference_pulse(intervals)

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

    pulse = statistics.median(intervals) if intervals else 0.0
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
) -> list[MeterSection]:
    """Bar grid for each metrical span, sharing one phase and one meter.

    The phase is global: `index % pulses == anchor % pulses` decides a bar line
    everywhere, so a span that does not contain the anchor still counts in step
    with it. Spans only gate *where* bars are drawn.
    """
    signature, pulses = resolve_meter(config)
    spans = metrical_spans(beats, config)
    if not beats or not spans:
        return []

    anchor_index = (
        nearest_beat_index(beats, config.anchor)
        if config.anchor is not None
        else _auto_anchor(beats, downbeats, pulses, near)
    )
    phase = anchor_index % pulses

    sections: list[MeterSection] = []
    bars_before = 0
    previous_end: int | None = None
    for start, end in spans:
        first = next((i for i in range(start, end) if i % pulses == phase), None)
        if first is None or first + pulses > end:
            previous_end = end
            continue  # not even one whole bar fits in this span
        # A span reached across a hole in the tracking still counts in step, but
        # says so: beats lost in the gap would shift the bar number.
        crossed = previous_end is not None and start > previous_end
        previous_end = end
        sections.append(
            MeterSection(
                start=beats[first].time,
                end=beats[end - 1].time,
                pulses_per_bar=pulses,
                time_signature=signature,
                anchor=beats[anchor_index].time,
                first_bar=bars_before + 1,
                confidence=0.75 if crossed else 1.0,
                origin="user" if config.anchor is not None else "auto",
            )
        )
        bars_before += (end - first) // pulses
    return sections


def bar_grid(
    beats: list[float],
    downbeats: list[float],
    config: MeterConfig,
    duration: float,
    near: tuple[float, float] | None = None,
) -> tuple[list[Beat], list[MeterSection]]:
    """The bar grid as the GUI draws it: tracked beats repaired and extended
    to the track's ends, and sections counted from the anchor -- the user's
    if they placed one, the downbeat layer's best phase if not.

    One function, because two callers have to agree on it exactly. The roll
    (`/beats`) draws bar lines from this, and the Export button counts its
    bars with it; when export derived its own grid it anchored on the first
    beat of its margin instead, and every bar on the page sat one beat off
    the bar lines on screen.
    """
    repaired = repair_beats(beats, config)
    repaired = extend_beats(repaired, config, 0.0, duration)
    return repaired, derive_sections(repaired, downbeats, config, near)


def bar_lines(
    beats: list[Beat],
    sections: list[MeterSection],
    form_start: float | None = None,
) -> list[tuple[float, int]]:
    """(time, bar number) for every bar line — what the GUI draws.

    `form_start` says where the tune's form begins, which is not always where
    the audio does: an intro or a vamp is not part of the song structure. Bar 1
    lands there and anything before it numbers zero or negative, so the caller
    can draw those lines without labelling them.
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
        offset = min(range(len(lines)), key=lambda i: abs(lines[i][0] - form_start))
        lines = [(time, index - offset + 1) for index, (time, _old) in enumerate(lines)]
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
