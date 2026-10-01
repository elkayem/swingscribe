"""Notes + a beat grid -> a Notation, with no audio and no cache.

The last four stages of the pipeline (meter, swing, quantize, notate) are pure
arithmetic over a note list and a list of beat times. Two callers need exactly
that, and neither can reach it through `pipeline.run`:

- the eval harness, which scores cached notes against hand transcriptions and
  has no reason to re-run CREPE to do it;
- the GUI's Export button, whose notes are the reviewed ones with the
  listener's ERASURES applied -- a judgement about the music that the pipeline
  knows nothing about and must not (gui/erasures.py).

Both used to assemble the Document themselves. That is the shape of duplication
that has already cost this project twice in the scoring harness (CLAUDE.md), so
it lives here, in the package, with tests.

## Bar 1 is the first bar of the span

The beat grid is trimmed to the span before anything else runs, so an excerpt's
bars are numbered from 1 the way a solo transcription is -- not from wherever
the soloist happens to enter in the tune. `anchor` is what keeps that bar 1 on
a real downbeat: it is a phase, not an origin (model.MeterSection), so a span
starting mid-bar still lands its bar lines correctly.

The phase is read off the WHOLE grid, not the trimmed one (`span_anchor`). The
anchor is usually outside the span -- the downbeat the listener clicked at the
head, or the auto anchor near the track's start -- and taking the nearest
trimmed beat to it turned every one of those into "the first beat of the
margin". Bar 1 is then the bar line nearest the span start: a span dragged a
few milliseconds short of a bar line still begins on it, and a span starting
more than half a bar early gets those notes as a pickup in bar 0, the way a
score writes them. Before this, with no downbeat in the sidecar, export
anchored on the first beat of its two-second margin, and Soul Station's page
sat one beat off the bar lines drawn on the roll.

`notation_for_span` deliberately does not call `stages/meter.py`. Meter
derivation exists to find where a steady pulse starts and stops across a whole
track, and to repair and extrapolate around the tracker's gaps; over a span
the user has already selected by ear, with a downbeat they have already placed
by hand, there is nothing left for it to decide. That work is done BEFORE the
span is trimmed, over the whole tracked grid, by `bar_grid_for_settings` --
the one derivation the roll, the Export button and the eval harness share, so
the page the harness scores is the page the listener sees.
"""

from swingscribe.config import Config
from swingscribe.model import (
    BeatGrid,
    Document,
    MeterSection,
    NotatedBar,
    NotatedNote,
    Notation,
    NoteEvent,
)
from swingscribe.stages import meter

# Seconds of beat grid either side of the span. A note at the very edge of
# the selection still needs the beat after it to be placed against.
MARGIN_SECONDS = 2.0

# An enabled note struck within this of a line note is a member of that
# note's chord. Tighter than the review's own 50 ms cluster gap on purpose: a
# chord is one gesture, and the piano model's onsets for one are within a
# frame or two of each other.
CHORD_TOLERANCE_S = 0.03

# The same fold for a piano TEXTURE (the GUI's "All notes" page), where every
# note is the model's and a chord is not a line note with company. Measured
# over 34 cached pianist reviews (31,600 model notes, 2026-09-29): 43% of
# consecutive onsets are under 20 ms apart -- chords -- then a flat floor of
# about 1.8% per 10 ms to 60 ms, rolls and grace notes with no bump of their
# own, and the fast notes start at 80. 50 ms is the review's own cluster
# width (gui/erasures.POOL_TOLERANCE_S) and a sixteenth at 300 bpm, so it
# folds the roll without reaching a real run. What it misses, quantize folds
# anyway (QuantizeConfig.polyphonic): two notes on one grid point are a chord.
TEXTURE_CHORD_TOLERANCE_S = 0.05

# The first guess at which hand plays a note on a two-staff page: middle C
# and up on the treble staff, below it on the bass. Only a guess -- the
# listener reassigns any note on the roll (sidecar `hands`).
HAND_SPLIT = 60
HANDS = ("right", "left")

# Below this a span cannot support a bar grid at all -- two bars of 4/4.
MIN_BEATS = 8


def span_beats(
    beats: list[float], region: tuple[float, float | None], margin: float = MARGIN_SECONDS
) -> list[float]:
    """The beat times inside the span, with a little air either side."""
    low = region[0] or 0.0
    high = beats[-1] if (region[1] is None and beats) else region[1]
    if high is None:
        return []
    return [b for b in beats if low - margin <= b <= high + margin]


def edge_period(intervals: list[float]) -> float:
    """The tempo at one edge of a grid: the median of its outermost few beat
    lengths, so one tracker slip at the edge does not set it."""
    usable = [i for i in intervals if i > 0]
    if not usable:
        return 0.0
    usable.sort()
    return usable[len(usable) // 2]


def cover(beats: list[float], low: float, high: float, edge_beats: int = 4) -> list[float]:
    """The grid, continued at its own edge tempo until it reaches `low` and
    passes `high`.

    Quantize places a note by the beat it falls in, and a note before the
    first beat or after the last has none: it was dropped, silently. The
    tracker's first beat can land a tenth of a beat AFTER the music's first
    downbeat -- Blossom Dearie's More Than You Know opens with a chord at
    0.29-0.36 s against a first tracked beat at 0.40 s -- and the meter
    stage cannot continue the grid backwards past the start of the file.
    Here it can: a beat before 0 s is only arithmetic, and what matters is
    that every note in the span has a beat to be placed against, so the
    chord lands on bar 1's downbeat instead of vanishing.
    """
    if len(beats) < 2:
        return list(beats)
    head = edge_period([b - a for a, b in zip(beats, beats[1 : edge_beats + 1], strict=False)])
    tail = edge_period(
        [b - a for a, b in zip(beats[-edge_beats - 1 :], beats[-edge_beats:], strict=False)]
    )
    before: list[float] = []
    first = beats[0]
    while head > 0 and first > low:
        first -= head
        before.append(first)
    after: list[float] = []
    last = beats[-1]
    while tail > 0 and last <= high:
        last += tail
        after.append(last)
    return [*reversed(before), *beats, *after]


def with_chords(
    line: list[NoteEvent],
    extras: list[NoteEvent],
    tolerance: float = CHORD_TOLERANCE_S,
    longest: bool = False,
) -> list[NoteEvent]:
    """The line with the listener's enabled extras folded in as chords.

    A pianist's transcription is a single line by default, and the roll offers
    every other note the piano model heard as a candidate the listener can
    switch on. An extra struck together with a line note joins that note's
    `chord` and takes its DURATION: chord members strike and release together,
    and two independently-measured lengths would put one of them a 32nd short
    on the page. An extra with no line note under it becomes a note of its
    own, and later extras may then chord onto it. Quantize sees one onset per
    chord, which is what keeps it from calling the grid too coarse.

    `longest` gives each chord its LONGEST member's duration instead of the
    head's: on a piano texture there is no line note to defer to, and the
    head is merely the earliest of a roll.
    """
    hosts: list[tuple[NoteEvent, set[int], list[float]]] = [
        (note, set(note.chord), [note.duration]) for note in sorted(line, key=lambda n: n.onset)
    ]
    for extra in sorted(extras, key=lambda n: n.onset):
        nearest = None
        for host, _members, _length in hosts:
            distance = abs(host.onset - extra.onset)
            if distance <= tolerance and (nearest is None or distance < nearest[0]):
                nearest = (distance, host)
        if nearest is None:
            hosts.append((extra, set(), [extra.duration]))
            continue
        for host, members, length in hosts:
            if host is nearest[1] and extra.pitch != host.pitch:
                members.add(extra.pitch)
                length[0] = max(length[0], extra.duration)
    return sorted(
        (
            host.model_copy(
                update={
                    "chord": sorted(members - {host.pitch}),
                    **({"duration": length[0]} if longest else {}),
                }
            )
            for host, members, length in hosts
        ),
        key=lambda n: (n.onset, n.pitch),
    )


def fold_texture(notes: list[NoteEvent]) -> list[NoteEvent]:
    """A piano texture as quantize must see it: one event per chord.

    Every note the piano model heard, folded at TEXTURE_CHORD_TOLERANCE_S,
    each chord as long as its longest member (see `with_chords`).
    """
    return with_chords([], notes, TEXTURE_CHORD_TOLERANCE_S, longest=True)


def guess_hand(pitch: int) -> str:
    """The first guess at a note's hand: "right" (the treble staff) from
    middle C up, "left" (the bass staff) below it."""
    return "right" if pitch >= HAND_SPLIT else "left"


def span_anchor(
    beats: list[float],
    kept: list[float],
    anchor: float | None,
    pulses_per_bar: int,
    start: float,
) -> float:
    """The kept beat that is bar 1: in phase with `anchor` over the FULL grid,
    and nearest the span start.

    `kept` must be a contiguous slice of `beats` (span_beats). With no anchor
    at all there is no phase to keep, so bar 1 is simply the beat nearest the
    span start.
    """
    if not kept:
        raise ValueError("no beats in the span")
    if anchor is None:
        return min(kept, key=lambda b: abs(b - start))
    anchor_index = min(range(len(beats)), key=lambda i: abs(beats[i] - anchor))
    first_index = beats.index(kept[0])
    pulses = max(1, pulses_per_bar)
    in_phase = [b for i, b in enumerate(kept) if (first_index + i - anchor_index) % pulses == 0]
    return min(in_phase or kept, key=lambda b: abs(b - start))


def section_for(
    beats: list[float],
    anchor: float | None,
    time_signature: tuple[int, int],
    pulses_per_bar: int,
) -> MeterSection:
    """One constant-meter section covering the whole span.

    `origin="user"` because every value in it came from a person: they drew the
    span, they set the downbeat, they chose the time signature.
    """
    return MeterSection(
        start=beats[0],
        end=beats[-1],
        pulses_per_bar=pulses_per_bar,
        time_signature=time_signature,
        anchor=beats[0] if anchor is None else anchor,
        first_bar=1,
        origin="user",
    )


def meter_from_settings(
    time_signature: str | None, pulses_per_bar: int | None, config: Config
) -> tuple[tuple[int, int], int]:
    """(signature, pulses) from what the GUI remembered, via the meter stage.

    Routed through `meter.resolve_meter` rather than parsed here so that "6/8"
    counted in two means the same thing on the page as it does on the bar grid.
    """
    overrides = {
        key: value
        for key, value in {
            "time_signature": time_signature,
            "pulses_per_bar": pulses_per_bar,
        }.items()
        if value is not None
    }
    return meter.resolve_meter(config.meter.model_copy(update=overrides))


def bar_grid_for_settings(
    beats: list[float],
    downbeats: list[float],
    settings: dict,
    config: Config,
    duration: float,
    near: tuple[float, float] | None = None,
) -> tuple[list[float], float | None]:
    """The beat grid AS THE ROLL DRAWS IT, and the beat it counts bars from.

    The tracked beats through `meter.bar_grid` -- repaired (a dropped beat
    inserted, a doubled one removed) and extended to the track's ends --
    under the listener's per-track settings: their time signature, pulse
    count and downbeat if they set them, the downbeat layer's best phase if
    not, and the beats they pinned (`beat_pins`, meter.apply_pins). The
    Export button and the eval harness both build their page from
    this. The harness used to notate the raw tracked beats, so every bar
    after an unrepaired drop or double sat a beat off the listener's page and
    its rhythm numbers carried a defect the Score button's did not (D27).

    Whole-track, before the span is trimmed: the repair needs the pulse
    either side of a gap, and the anchor's phase is read off the full grid
    (`span_anchor`).

    `near` is the span being notated. It matters only when the listener has
    set no downbeat: the automatic one is then voted around the span rather
    than over the whole track (`meter._auto_anchor`, D32). It defaults to the
    settings' own `region`.
    """
    near = _near_of(settings, duration, near)
    meter_config = _meter_config(settings, config)
    repaired, sections = meter.bar_grid(
        beats, downbeats, meter_config, duration, near=near, pins=pins_of(settings)
    )
    anchor = sections[0].anchor if sections else settings.get("anchor")
    return [beat.time for beat in repaired], anchor


# The sidecar key for the beats the listener pinned (meter.apply_pins).
PINS_KEY = "beat_pins"


def pins_of(settings: dict) -> list[float]:
    """The listener's pinned beats from a sidecar, cleaned (`meter.clean_pins`):
    a hand-edited or missing list is no pins, never an error."""
    stored = settings.get(PINS_KEY)
    return meter.clean_pins(stored if isinstance(stored, list) else None)


def _near_of(
    settings: dict, duration: float, near: tuple[float, float] | None
) -> tuple[float, float] | None:
    """The span the automatic downbeat is voted around: `near`, or the
    settings' own region."""
    if near is None and settings.get("region"):
        lo, hi = settings["region"]
        near = (float(lo), float(duration if hi is None else hi))
    return near


def _meter_config(settings: dict, config: Config, *extra: str):
    """The meter config under the listener's per-track settings: their time
    signature, pulse count and downbeat, and any `extra` MeterConfig fields
    (form_start, bars_per_chorus) the caller also reads."""
    fields = ("time_signature", "pulses_per_bar", "anchor", *extra)
    overrides = {key: settings[key] for key in fields if settings.get(key) is not None}
    return config.meter.model_copy(update=overrides)


def bar_number_at(
    beats: list[float], lines: list[tuple[float, int]], downbeat: float, pulses_per_bar: int
) -> int | None:
    """The roll's bar number for the bar that starts on `downbeat`, a beat of
    `beats`: the nearest numbered bar line's number, plus the whole bars
    between them COUNTED IN BEATS on the same grid. Exact whenever the
    downbeat is in phase with the lines (the phase is global, meter.
    derive_sections), and right across free time, where the roll draws no
    line to read a number off."""
    if not lines or not beats:
        return None
    line_time, number = min(lines, key=lambda line: abs(line[0] - downbeat))
    steps = meter.nearest_index(beats, downbeat) - meter.nearest_index(beats, line_time)
    return number + round(steps / max(1, pulses_per_bar))


def page_downbeat(
    beats: list[float],
    region: tuple[float, float | None],
    anchor: float | None,
    pulses_per_bar: int,
) -> float | None:
    """The beat page bar 1 starts on -- the one `notation_for_span` counts
    bars from -- or None if the span is too short to bar out."""
    kept = span_beats(beats, region)
    if len(kept) < MIN_BEATS:
        return None
    return span_anchor(beats, kept, anchor, pulses_per_bar, region[0] or 0.0)


def form_bar_of_page(
    beats: list[float],
    downbeats: list[float],
    settings: dict,
    config: Config,
    duration: float,
    region: tuple[float, float | None],
    near: tuple[float, float] | None = None,
) -> int | None:
    """Which bar of the tune's form the page's bar 1 is, numbered exactly as
    the roll numbers it (`/beats`): bar 1 at the listener's form start, or
    at the first bar line when they set none, on the repaired grid under
    their meter settings.

    For the chord chart (chords.place): a solo that starts in the middle of
    the third chorus of a 32-bar tune reads 65 + 4 = 69 here, and gets bar 5
    of the chart over its bar 1. Counted on `bar_grid_for_settings`'s own
    grid from the downbeat `notation_for_span` counts from, so the chart
    and the page cannot disagree about which bar is which. None if the span
    is too short for a page or the grid has no bar lines.
    """
    near = _near_of(settings, duration, near)
    meter_config = _meter_config(settings, config, "form_start", "bars_per_chorus")
    repaired, sections = meter.bar_grid(
        beats, downbeats, meter_config, duration, near=near, pins=pins_of(settings)
    )
    times = [beat.time for beat in repaired]
    anchor = sections[0].anchor if sections else settings.get("anchor")
    _signature, pulses = meter.resolve_meter(meter_config)
    downbeat = page_downbeat(times, region, anchor, pulses)
    if downbeat is None:
        return None
    lines = meter.bar_lines(repaired, sections, meter_config.form_start)
    return bar_number_at(times, lines, downbeat, pulses)


def notation_for_span(
    audio_path: str,
    notes: list[NoteEvent],
    beats: list[float],
    region: tuple[float, float | None],
    *,
    stem: str,
    config: Config | None = None,
    anchor: float | None = None,
    time_signature: tuple[int, int] = (4, 4),
    pulses_per_bar: int = 4,
    sample_rate: int = 44100,
    second_voice: list[NoteEvent] | None = None,
    double_time: bool = False,
    left_hand: list[NoteEvent] | None = None,
) -> Notation | None:
    """Run swing, quantize and notate over one span. None if it is too short.

    `config` supplies the notate settings that are genuinely choices -- the
    part's transposition, the title, legato fill -- while the stem is forced
    onto all three stages so a caller cannot half-set it.

    `second_voice` is the piano review overlay (corroborate.second_voice). It
    is notated SEPARATELY and merged in as voice 2 rather than being mixed
    into `notes`, because quantize chooses one grid per beat and notate writes
    one note per grid position: two simultaneous notes in a single list are
    not a chord to it, they are a grid that is too coarse, and it would
    silently drop one of them (CLAUDE.md, M6).

    `left_hand`, when given (even empty), makes a two-staff page: `notes` is
    the right hand on the treble staff and this the left on the bass, each
    notated separately on the same grid and under ONE swing reading -- the
    right hand's, the melodic stream the estimator is built for, exactly as
    the overlay takes the line's. Only a page with no right hand at all
    reads its swing from the left.
    """
    from swingscribe.stages import notate, quantize, swing

    # Resolved on the tracked grid, before any doubling: the beat it names
    # survives doubling, and its phase is a fact about the tracked pulse.
    # One function with the chord chart's placement (`form_bar_of_page`),
    # so the two cannot count bar 1 from different beats.
    anchor = page_downbeat(beats, region, anchor, pulses_per_bar)
    if anchor is None:
        return None
    # Every note gets a beat to land on, however early or late it is against
    # the tracked grid (`cover`): a grid that ends before a note drops it.
    # Bar 1 is still a TRACKED beat -- chosen above, before any continuation.
    tracked = (beats[0], beats[-1])
    onsets = [n.onset for n in (*notes, *(left_hand or ()), *(second_voice or ()))]
    low = min([region[0] or 0.0, *onsets]) - MARGIN_SECONDS
    high = max([beats[-1] if region[1] is None else region[1], *onsets]) + MARGIN_SECONDS
    kept = span_beats(cover(beats, low, high), region)
    if double_time:
        # Double-time feel (the listener's checkbox): the notated pulse is
        # twice the tracked one, so each tracked beat is split at its
        # midpoint and everything downstream — grid choice, values, bars —
        # follows at the doubled pulse. A performed bar becomes two notated
        # bars; a ballad's 32nd run becomes ordinary sixteenths. The anchor
        # is still a valid downbeat instant on the doubled grid.
        kept = [t for a, b in zip(kept, kept[1:], strict=False) for t in (a, (a + b) / 2.0)] + [
            kept[-1]
        ]
    # Bars are counted from the first beat of the grid that is in phase with
    # the anchor (quantize.bar_and_beat: the anchor is a phase, not an
    # origin), so the grid starts just under a bar before the beat that is
    # bar 1. Anything left before it -- a pickup -- lands in bar 0.
    first = kept.index(anchor)
    kept = kept[max(0, first - (pulses_per_bar - 1)) :]

    base = config or Config()
    run_config = base.model_copy(
        update={
            "swing": base.swing.model_copy(update={"stem": stem}),
            "quantize": base.quantize.model_copy(update={"stem": stem}),
            "notate": base.notate.model_copy(update={"stem": stem}),
        }
    )
    staves = left_hand is not None
    right, left = list(notes), list(left_hand or [])
    lead_is_left = staves and not right and bool(left)

    def on_grid(grid: list[float]) -> Document:
        return Document(
            audio_path=audio_path,
            sample_rate=sample_rate,
            beat_grid=BeatGrid(beats=grid, downbeats=[], beats_per_bar=pulses_per_bar),
            meter=[section_for(grid, anchor, time_signature, pulses_per_bar)],
            notes={stem: left if lead_is_left else right},
        )

    # The swing reading is taken over the TRACKED beats only, exactly as it
    # was before the grid could be continued. The stage tiles its windows
    # from the grid's first beat, so a few beats added at the front move
    # every window, and a weak reading flips: Blossom Dearie's page went from
    # 32 beats warped to none for want of one early chord. The continued
    # beats are there to place notes on, not to be evidence about the feel.
    inside = [i for i, b in enumerate(kept) if tracked[0] - 1e-9 <= b <= tracked[1] + 1e-9]
    shift = inside[0] if inside else 0
    read = swing.run(on_grid(kept[shift : inside[-1] + 1] if inside else kept), run_config)
    document = on_grid(kept).model_copy(
        update={
            "swing": [
                span.model_copy(
                    update={
                        "start_beat": span.start_beat + shift,
                        "end_beat": span.end_beat + shift,
                    }
                )
                for span in read.swing
            ]
        }
    )
    for stage in (quantize.run, notate.run):
        document = stage(document, run_config)
    notation = document.notation
    if staves:
        other = right if lead_is_left else left
        follower = _notate_only(other, document, run_config) if other else None
        key = run_config.notate.key
        notation = (
            merge_staves(follower, notation, key)
            if lead_is_left
            else merge_staves(notation, follower, key)
        )
    if notation is not None and double_time:
        notation.double_time = True
    if notation is not None and second_voice and not staves:
        merge_second_voice(notation, _notate_only(second_voice, document, run_config))
    return notation


def merge_staves(right: Notation | None, left: Notation | None, key: int | None = None) -> Notation:
    """Two separately notated hands as ONE grand-staff Notation.

    Bar by bar over the union of both hands' bars, so a bar one hand sits
    out is a whole rest on its staff rather than a staff that runs out of
    bars: MusicXML measures hold every staff of the part at once. The key
    is read ONCE, over both hands' sounding notes chords and all, and both
    are respelled in it -- two staves in two keys is not a piano part. A
    `key` the listener chose (NotateConfig.key) is used instead of reading.
    """
    from swingscribe.stages import notate

    parts = {staff: n for staff, n in ((1, right), (2, left)) if n is not None}
    template = next((n for n in parts.values() if n.bars), None) or right or left or Notation()
    bars_of = {staff: {bar.number: bar for bar in n.bars} for staff, n in parts.items()}
    numbers = sorted({number for bars in bars_of.values() for number in bars})
    sounding = [
        (pitch, note.duration)
        for bars in bars_of.values()
        for bar in bars.values()
        for note in bar.notes
        if not note.is_rest
        for pitch in (note.pitch, *note.chord)
    ]
    if key is None:
        key = notate.detect_key(sounding) if sounding else template.key_fifths
    merged: list[NotatedBar] = []
    signature = (4, 4)
    for number in range(numbers[0], numbers[-1] + 1) if numbers else ():
        found = [bars[number] for bars in bars_of.values() if number in bars]
        if found:
            signature = found[0].time_signature
        length = signature[0] * 4.0 / signature[1]
        written: list[NotatedNote] = []
        for staff in (1, 2):
            bar = bars_of.get(staff, {}).get(number)
            for note in bar.notes if bar is not None else notate.fill_rests([], length):
                update: dict = {"staff": staff}
                if not note.is_rest:
                    step, alter, octave = notate.spell(note.pitch, key)
                    update |= {"step": step, "alter": alter, "octave": octave}
                written.append(note.model_copy(update=update))
        merged.append(NotatedBar(number=number, time_signature=signature, notes=written))
    return Notation(
        bars=merged,
        key_fifths=key,
        swing=template.swing,
        transpose=template.transpose,
        title=template.title,
        double_time=template.double_time,
        staves=2,
    )


def _notate_only(notes: list[NoteEvent], document: Document, run_config: Config) -> Notation | None:
    """The same stages over a different note list, on the SAME grid AND warp.

    Re-using the beat grid and meter matters: the two voices have to be
    measured against one clock, or bar 12 of one is not bar 12 of the other.

    Re-using the SWING SPANS matters just as much and is easier to miss.
    Swing is estimated from onsets, and the overlay's onsets are a different
    (smaller, chordal) sample of the same playing — run on its own it reads a
    different BUR (2.21 against the line's 1.51 on Giant Steps) and warps a
    different set of beats. Two voices of one performance warped by different
    amounts drift apart on the page. The line's reading wins because the line
    is what the swing estimator is built for: a melodic stream of onsets.
    """
    from swingscribe.stages import notate, quantize

    stem = run_config.notate.stem
    second = Document(
        audio_path=document.audio_path,
        sample_rate=document.sample_rate,
        beat_grid=document.beat_grid,
        meter=document.meter,
        swing=list(document.swing),
        notes={stem: list(notes)},
    )
    for stage in (quantize.run, notate.run):
        second = stage(second, run_config)
    return second.notation


def merge_second_voice(notation: Notation, overlay: Notation | None) -> Notation:
    """Fold `overlay`'s notes into `notation` as voice 2, bar by bar.

    Rests are kept, not dropped: a voice whose durations do not fill the bar
    does not add up, and a bar that does not add up is the one thing every
    MusicXML reader complains about. They can be hidden in the notation editor;
    an unreadable file cannot be fixed there.
    """
    if overlay is None:
        return notation
    by_number = {bar.number: bar for bar in overlay.bars}
    for bar in notation.bars:
        other = by_number.get(bar.number)
        if other is None:
            continue
        bar.notes.extend(note.model_copy(update={"voice": 2}) for note in other.notes)
    return notation
