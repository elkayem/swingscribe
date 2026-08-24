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


def reference_pulse(intervals: list[float]) -> list[float]:
    """The pulse rate the tune is *actually* running at, per interval.

    Cannot be a plain local median. Corner Pocket's first 23 seconds are tracked
    at half rate, so the local median there is itself the wrong answer and no
    amount of local smoothing notices. Instead: seed from the global mode, use
    that to guess how many pulses each interval spans, divide it out, and smooth
    the *implied* pulse. Half-rate regions contribute their halved value, so the
    reference stays on the true rate while still following genuine tempo drift.
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

    implied = [value / max(1, round(value / seed)) if seed > 0 else value for value in intervals]
    return _rolling_median(implied, REFERENCE_WINDOW)


def repair_beats(beats: list[float], config: MeterConfig) -> list[Beat]:
    """Insert beats the tracker dropped, so the bar count stays true.

    This is correctness, not cosmetics: a single missed beat shifts every bar
    line after it by one beat for the rest of the tune.

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


def _auto_anchor(beats: list[Beat], downbeats: list[float], pulses: int) -> int:
    """Index of the beat to treat as beat 1 when the user hasn't chosen one.

    The detected downbeat layer is noise, but it is *biased* noise, so the phase
    it agrees with most often beats a coin flip — and one click fixes it.
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
    scores = [sum(1 for i in marked if i % pulses == phase) for phase in range(pulses)]
    return max(range(pulses), key=lambda phase: scores[phase])


def nearest_beat_index(beats: list[Beat], when: float) -> int:
    if not beats:
        return 0
    return min(range(len(beats)), key=lambda i: abs(beats[i].time - when))


def derive_sections(
    beats: list[Beat],
    downbeats: list[float],
    config: MeterConfig,
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
        else _auto_anchor(beats, downbeats, pulses)
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


def run(document: Document, config: Config) -> Document:
    grid = document.beat_grid
    if grid is None or not grid.beats:
        return document.model_copy(update={"meter": []})
    duration = document.audio.duration if document.audio else grid.beats[-1]
    beats = repair_beats(grid.beats, config.meter)
    beats = extend_beats(beats, config.meter, 0.0, duration)
    sections = derive_sections(beats, grid.downbeats, config.meter)
    return document.model_copy(update={"meter": sections})
