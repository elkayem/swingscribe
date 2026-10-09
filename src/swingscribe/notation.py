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

from dataclasses import dataclass, field

from swingscribe.config import ENSEMBLE_TIMINGS, TIMINGS, Config
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

# ── Two horns on one staff (docs/multi-horn.md) ──────────────────────────
# The lower horn is written an octave (or two) up wherever a PHRASE of it
# sits that far under the upper voice, so the two lines sit close on the
# staff the way an arranger writes a head. Decided per phrase, never note by
# note: a horn's line moved up and down an octave through the transcription
# is the thing the listener warned against.
OCTAVE = 12
# A gap in the lower voice at least this long ends its phrase. The lower
# voice holds only the notes heard UNDER a partner (voices.assign), so a
# unison or the upper horn alone also ends one.
PHRASE_REST_S = 0.25
# The same pitch in both voices struck this close together is a unison, and
# is written once, in voice 1.
UNISON_ONSET_S = 0.05
# Inside a phrase, a stretch whose every note sits an octave or more under
# the upper voice (or every note less) is decided on its own when it lasts
# at least this long and holds this many notes (`sub_phrases`): the Open
# Sesame head's bars 15-16, the tenor an octave and a third under for two
# bars inside a 46-note phrase whose median is a fourth, were left wide
# apart (Local task A, 2026-10-09). About a bar at 250 bpm; a shorter
# excursion stays with its phrase, so nothing is decided note by note.
REGIME_MIN_S = 1.0
REGIME_MIN_NOTES = 3


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


def timing_for(settings: dict, config: Config) -> str:
    """The rhythm a page is written in: the sidecar's `timing` when it holds
    one this build knows, else the ensemble's own default (ENSEMBLE_TIMINGS:
    a multi-horn head is literal), else the config's. The Export button, the
    page view and the harness all read it here."""
    stored = settings.get("timing")
    if stored in TIMINGS:
        return stored
    ensemble = settings.get("ensemble") or config.transcribe.ensemble
    return ENSEMBLE_TIMINGS.get(ensemble, config.quantize.timing)


# A two-horn head's rest of up to an EIGHTH after a held note, before the
# voice's next note, is written into the note (NotateConfig.close_rests,
# notate.CLOSE_AFTER_BEATS): the listener heard bar 24's lower A held to the
# next note, a whole note, where the page wrote three and a half beats and
# an eighth rest (Local task A4); the riff's staccato eighths keep theirs.
HEAD_CLOSE_RESTS = 0.5


def writing_of(settings: dict, config: Config) -> dict:
    """The notate settings a page's sidecar chooses beyond the key and the
    part: for a multi-horn head, `close_rests` (an eighth, unless the
    sidecar's `close_rests` is false) and `drop_faint` (the sidecar's,
    off by default); for anything else the config's."""
    horns = (settings.get("ensemble") or config.transcribe.ensemble) == "multi-horn"
    closes = horns and settings.get("close_rests", True) is not False
    return {
        "close_rests": HEAD_CLOSE_RESTS if closes else config.notate.close_rests,
        # Off until measured: only a head's sidecar turns it on.
        "drop_faint": bool(horns and settings.get("drop_faint", config.notate.drop_faint)),
    }


def reading_of(settings: dict, config: Config) -> dict:
    """The quantize settings a page's sidecar chooses: its rhythm
    (`timing_for`), and for a literal page the readings a written head may
    take -- `literal_lag` (the line's lag behind the beat taken out) and
    `literal_thirds` -- and whether lead-ins fold into their notes
    (`literal_lead_ins`). For a multi-horn head the lag and the lead-ins
    are ON unless its sidecar says otherwise (the lag is the listener's
    decision of 2026-10-09: three bars of the head's bridge onto the
    downbeat, one 16th more); thirds, and all three for anything else,
    are off unless the sidecar turns them on."""
    qc = config.quantize
    horns = (settings.get("ensemble") or config.transcribe.ensemble) == "multi-horn"
    return {
        "timing": timing_for(settings, config),
        "literal_lag": bool(settings.get("literal_lag", horns or qc.literal_lag)),
        "literal_thirds": bool(settings.get("literal_thirds", qc.literal_thirds)),
        "literal_lead_ins": bool(settings.get("literal_lead_ins", horns or qc.literal_lead_ins)),
    }


@dataclass
class HornLines:
    """Two horns' heard notes as one staff writes them (`horn_lines`)."""

    upper: list[NoteEvent]
    lower: list[NoteEvent]
    # One record per phrase of the lower voice: its span, its median
    # interval under the upper voice (None with no partner) and how far it
    # was moved up, in semitones.
    phrases: list[dict] = field(default_factory=list)
    # Lower notes written once, in voice 1, as a unison.
    unisons: int = 0
    # The faint scraps (`faint_scraps`), whether or not they were left off.
    faint: list[NoteEvent] = field(default_factory=list)


def _weighted_median(pairs: list[tuple[float, float]]) -> float | None:
    """The median of (value, weight) pairs: the value at half the weight."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    if not pairs:
        return None
    half = sum(w for _v, w in pairs) / 2.0
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def lower_phrases(lower: list[NoteEvent], rest: float = PHRASE_REST_S) -> list[list[NoteEvent]]:
    """The lower voice in phrases: runs of notes with no gap of `rest`."""
    phrases: list[list[NoteEvent]] = []
    end = None
    for note in sorted(lower, key=lambda n: n.onset):
        if end is None or note.onset - end >= rest:
            phrases.append([])
        phrases[-1].append(note)
        end = note.onset + note.duration if end is None else max(end, note.onset + note.duration)
    return phrases


def sub_phrases(
    phrase: list[NoteEvent],
    upper: list[NoteEvent],
    min_s: float = REGIME_MIN_S,
    min_notes: int = REGIME_MIN_NOTES,
) -> list[list[NoteEvent]]:
    """A phrase of the lower voice cut where its distance from the upper
    voice changes REGIME -- an octave or more under, or less -- for at
    least `min_s` and `min_notes`. A note with no partner goes with the
    stretch it is in; a stretch too short to stand alone joins the one
    before it (the first, the one after). One phrase in, usually one out.

    Except a CLOSE stretch at either END of the phrase: it stands, however
    short, so a wide excursion is never carried past its end. The head's
    excursion ran on into the next chord's held A-flat, a third under C,
    and the A-flat went up with it, over the C (Local task A2,
    2026-10-09). A short WIDE stretch at an end still joins its neighbour:
    alone it would be moved note by note."""

    def wide(note: NoteEvent) -> bool | None:
        interval = phrase_interval([note], upper)
        return None if interval is None else interval >= OCTAVE

    runs: list[list] = []  # [wide or None, notes]
    for note in phrase:
        kind = wide(note)
        if runs and (kind is None or runs[-1][0] is None or runs[-1][0] == kind):
            if runs[-1][0] is None:
                runs[-1][0] = kind
            runs[-1][1].append(note)
        else:
            runs.append([kind, [note]])

    def stands(run: list, edge: bool = False) -> bool:
        notes = run[1]
        if edge and run[0] is False and len(runs) > 1:
            return True
        span = max(n.onset + n.duration for n in notes) - notes[0].onset
        return len(notes) >= min_notes and span >= min_s

    merged: list[list] = []
    for k, run in enumerate(runs):
        edge = k == len(runs) - 1
        if merged and (not stands(run, edge) or merged[-1][0] == run[0]):
            merged[-1][1].extend(run[1])
        else:
            merged.append(run)
    if len(merged) > 1 and not stands(merged[0], edge=merged[0][1][0] is phrase[0]):
        merged[1][1][:0] = merged[0][1]
        merged.pop(0)
    return [run[1] for run in merged]


def phrase_interval(phrase: list[NoteEvent], upper: list[NoteEvent]) -> float | None:
    """How far a phrase of the lower voice sits under the upper voice: the
    median interval to the upper notes sounding over it, weighted by how
    long each pair sounds together. None when nothing sounds over it."""
    pairs = []
    for low in phrase:
        for high in upper:
            shared = min(low.onset + low.duration, high.onset + high.duration) - max(
                low.onset, high.onset
            )
            if shared > 0:
                pairs.append((float(high.pitch - low.pitch), shared))
    return _weighted_median(pairs)


# A heard note this short AND this unsure, and not a lead-in, is a faint
# scrap a person would not write down: the head's 58 ms G-flat at
# confidence 0.33 on bar 29's bar line ("too short to write down. I would
# ignore it", the listener). Never one condition alone -- CLAUDE.md's
# "never filter notes by duration" was measured on solos -- and OFF until
# measured on the head (NotateConfig.drop_faint, sidecar `drop_faint`):
# `horn_lines` lists the scraps either way, and the script's dump says
# what the rule would take.
#
# And ISOLATED: a short, unsure note with another within FAINT_NEIGHBOUR_S
# is part of a figure, not a scrap. The head's bar 36 is three notes of
# 58-70 ms at confidence 0.31-0.35, 92 ms apart, and real (Local task A5:
# without this, `drop_faint` took them and a bar-38 pair with them).
FAINT_MAX_S = 0.08
FAINT_CONFIDENCE = 0.4
FAINT_NEIGHBOUR_S = 0.15


def is_faint(note: NoteEvent) -> bool:
    """Short AND unsure AND not a lead-in: what a scrap is made of."""
    return note.duration < FAINT_MAX_S and note.confidence < FAINT_CONFIDENCE and not note.lead_in


def faint_scraps(notes: list[NoteEvent], near: float = FAINT_NEIGHBOUR_S) -> list[NoteEvent]:
    """The faint notes (`is_faint`) with no other faint note, in either
    voice, starting within `near` seconds of them: a lone scrap, never a
    run of quick soft notes."""
    faint = sorted((n for n in notes if is_faint(n)), key=lambda n: n.onset)
    return [
        n
        for k, n in enumerate(faint)
        if not any(abs(m.onset - n.onset) <= near for j, m in enumerate(faint) if j != k)
    ]


def horn_lines(
    notes: list[NoteEvent],
    *,
    move_octaves: bool = True,
    merge_unisons: bool = True,
    rest: float = PHRASE_REST_S,
    unison_onset: float = UNISON_ONSET_S,
    drop_faint: bool = False,
) -> HornLines:
    """Two horns' heard notes (NoteEvent.voice) as one staff writes them.

    Hearing and writing are kept apart, as with the lead-ins (docs/
    scoops.md): the transcriber gives each horn its HEARD pitches, and this
    is where the page's conventions are applied.

    - The lower voice is moved up by whole octaves PER PHRASE, wherever the
      phrase's median interval under the upper voice is an octave or more:
      an octave and a third becomes a third (the Open Sesame head's bars
      15-16), and a phrase doubled at the octave becomes a unison. A
      phrase is cut where its distance changes regime for a bar or so
      (`sub_phrases`), so a two-bar excursion inside a long phrase is
      decided on its own.
    - A unison -- the same pitch struck within `unison_onset` in both voices
      -- is written ONCE, in voice 1.

    `move_octaves` and `merge_unisons` are off for two PARTS, where each
    horn plays its own notes at its own octave. `drop_faint` leaves the
    faint scraps (`faint_scraps`) off the page; they are listed either way.
    """
    faint = faint_scraps(notes)
    if drop_faint:
        scraps = {id(n) for n in faint}
        notes = [n for n in notes if id(n) not in scraps]
    upper = sorted((n for n in notes if n.voice != 2), key=lambda n: (n.onset, -n.pitch))
    lower = sorted((n for n in notes if n.voice == 2), key=lambda n: (n.onset, -n.pitch))
    moved: list[NoteEvent] = []
    phrases = []
    for phrase in (
        sub for whole in lower_phrases(lower, rest) for sub in sub_phrases(whole, upper)
    ):
        interval = phrase_interval(phrase, upper)
        shift = 0
        if move_octaves and interval is not None and interval >= OCTAVE:
            shift = OCTAVE * int(interval // OCTAVE)
        phrases.append(
            {
                "start": phrase[0].onset,
                "end": max(n.onset + n.duration for n in phrase),
                "notes": len(phrase),
                "interval": interval,
                "moved": shift,
            }
        )
        moved.extend(n.model_copy(update={"pitch": n.pitch + shift}) for n in phrase)
    unisons = 0
    if merge_unisons:
        kept = []
        for note in moved:
            if any(
                high.pitch == note.pitch and abs(high.onset - note.onset) <= unison_onset
                for high in upper
            ):
                unisons += 1
                continue
            kept.append(note)
        moved = kept
    return HornLines(upper=upper, lower=moved, phrases=phrases, unisons=unisons, faint=faint)


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


# The listener's Fast tune: the speed the beat tracker hears the audio at.
FAST_TEMPO_SPEED = 0.5


def grid_config(config: Config, settings: dict) -> Config:
    """The config a track's beat grid is TRACKED and READ under.

    With the sidecar's `fast_tempo` on, the tracker hears the audio at half
    speed (`BeatsConfig.speed`): a tune past its range -- Bud Powell's
    Oblivion at quarter = 280, tracked one beat per BAR -- is heard where
    the tracker is at home, and its grid is cached under its own beats key.
    Only the grid's readers take this config: the review, the separation
    and the transcription keep the default chain, so switching it on costs
    a few seconds of tracking and moves no transcription.

    Every reader -- the roll, Export and the page view, Score, the chord
    chart, Find the solos, the Beats job, the harness -- comes through here,
    so no two can read different grids.
    """
    if not settings.get("fast_tempo"):
        return config
    return config.model_copy(
        update={"beats": config.beats.model_copy(update={"speed": FAST_TEMPO_SPEED})}
    )


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
    not, the stretches they marked steady (`steady_spans`,
    meter.apply_steady) and the beats they pinned (`beat_pins`,
    meter.apply_pins). The
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
        beats,
        downbeats,
        meter_config,
        duration,
        near=near,
        pins=pins_of(settings),
        steady=steady_of(settings),
    )
    anchor = sections[0].anchor if sections else settings.get("anchor")
    return [beat.time for beat in repaired], anchor


def grid_doubts_for_settings(
    beats: list[float],
    downbeats: list[float],
    settings: dict,
    config: Config,
    duration: float,
    span: tuple[float, float | None] | None = None,
    near: tuple[float, float] | None = None,
) -> list[meter.Doubt]:
    """Where the count of the grid `bar_grid_for_settings` builds is in doubt
    (`meter.grid_doubts`, R34) -- inside `span` when one is given. The same
    grid the roll draws and the page counts, pins and all, so a doubt the
    listener mends with a pin goes away and the harness's count of them is
    the Export button's."""
    near = _near_of(settings, duration, near)
    meter_config = _meter_config(settings, config)
    repaired, _sections = meter.bar_grid(
        beats,
        downbeats,
        meter_config,
        duration,
        near=near,
        pins=pins_of(settings),
        steady=steady_of(settings),
    )
    _signature, pulses = meter.resolve_meter(meter_config)
    doubts = meter.grid_doubts(repaired, meter_config.stability_tolerance, downbeats, pulses)
    if span is None:
        return doubts
    lo = span[0] or 0.0
    hi = duration if span[1] is None else span[1]
    return [d for d in doubts if d.end >= lo and d.start <= hi]


# The sidecar key for the beats the listener pinned (meter.apply_pins).
PINS_KEY = "beat_pins"


def pins_of(settings: dict) -> list[float]:
    """The listener's pinned beats from a sidecar, cleaned (`meter.clean_pins`):
    a hand-edited or missing list is no pins, never an error."""
    stored = settings.get(PINS_KEY)
    return meter.clean_pins(stored if isinstance(stored, list) else None)


# The sidecar key for the stretches the listener marked steady
# (meter.apply_steady): [[start, end], ...] in seconds.
STEADY_KEY = "steady_spans"


def steady_of(settings: dict) -> list[tuple[float, float]]:
    """The listener's steady stretches from a sidecar, cleaned
    (`meter.clean_steady`): a hand-edited or missing list is none, never an
    error."""
    stored = settings.get(STEADY_KEY)
    return meter.clean_steady(stored if isinstance(stored, list) else None)


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
        beats,
        downbeats,
        meter_config,
        duration,
        near=near,
        pins=pins_of(settings),
        steady=steady_of(settings),
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
    lower_voice: list[NoteEvent] | None = None,
    horn_parts: bool = False,
    lower_transpose: int | None = None,
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

    `lower_voice`, when given (even empty), makes a two-horn staff: `notes`
    is the upper horn and this the lower (`horn_lines` has already written
    them), each quantized on its own on the same grid under the upper's
    swing reading, and merged as voices 1 and 2 of one staff
    (`merge_horn_voices`). The line's lag -- a swing page's always (R29),
    a literal page's when QuantizeConfig.literal_lag asks -- is read ONCE
    over both horns and moves them together, so a chord struck behind the
    beat stays one chord. With
    `horn_parts` the two horns are two PARTS instead (`horn_parts`), the
    lower one written at `lower_transpose` semitones (the upper part's own
    when None).
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
    onsets = [
        n.onset for n in (*notes, *(left_hand or ()), *(second_voice or ()), *(lower_voice or ()))
    ]
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
    horns = lower_voice is not None
    right, left = list(notes), list(left_hand or [])
    lower = list(lower_voice or [])
    lead_is_left = staves and not right and bool(left)
    lead_is_lower = horns and not right and bool(lower)
    if horns and run_config.quantize.timing != "swing" and run_config.quantize.literal_lag:
        right, lower = _unlag_together(right, lower, kept, run_config)
        run_config = run_config.model_copy(
            update={"quantize": run_config.quantize.model_copy(update={"literal_lag": False})}
        )
    elif horns and run_config.quantize.timing == "swing" and run_config.quantize.lag_window_beats:
        # Swing takes the line's lag out too (R29), but per CALL, so each
        # horn would read its own: a lower horn entering for two chords has
        # too few downbeats in its window to read any, and was written late
        # under an upper horn moved onto the beat. Read once over both,
        # before the swing reading (which then measures the corrected
        # offbeats, as quantize's own warp does under phi* less the lag),
        # and the quantizer's own per-voice lag is switched off.
        right, lower = _unlag_together(right, lower, kept, run_config)
        run_config = run_config.model_copy(
            update={"quantize": run_config.quantize.model_copy(update={"lag_window_beats": 0})}
        )
    lead = left if lead_is_left else lower if lead_is_lower else right

    def on_grid(grid: list[float]) -> Document:
        return Document(
            audio_path=audio_path,
            sample_rate=sample_rate,
            beat_grid=BeatGrid(beats=grid, downbeats=[], beats_per_bar=pulses_per_bar),
            meter=[section_for(grid, anchor, time_signature, pulses_per_bar)],
            notes={stem: lead},
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
    if horns:
        other = right if lead_is_lower else lower
        follower = _notate_only(other, document, run_config) if other else None
        upper_page, lower_page = (follower, notation) if lead_is_lower else (notation, follower)
        if horn_parts:
            notation = merge_horn_parts(
                upper_page, lower_page, run_config.notate.key, lower_transpose
            )
        else:
            notation = merge_horn_voices(upper_page, lower_page, run_config.notate.key)
    elif staves:
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
    if notation is not None and second_voice and not staves and not horns:
        merge_second_voice(notation, _notate_only(second_voice, document, run_config))
    return notation


def notation_for_horns(
    audio_path: str,
    notes: list[NoteEvent],
    beats: list[float],
    region: tuple[float, float | None],
    *,
    parts: bool = False,
    lower_transpose: int | None = None,
    **kwargs,
) -> tuple[Notation | None, HornLines]:
    """A multi-horn head's page: the voices as one staff writes them
    (`horn_lines`), notated as a two-horn staff (`notation_for_span`'s
    `lower_voice`). THE assembly the Export button, the page view, the
    harness and scripts/multi_horn_page.py share; `kwargs` are
    `notation_for_span`'s. Returns the page and what the writing did.

    `parts` writes TWO PARTS instead, upper and lower, the lower at its own
    `lower_transpose`: each part plays its own notes, so nothing is moved an
    octave and no unison is merged."""
    config = kwargs.get("config")
    lines = horn_lines(
        notes,
        move_octaves=not parts,
        merge_unisons=not parts,
        drop_faint=bool(config and config.notate.drop_faint),
    )
    # Two notes struck together in ONE voice -- the listener moved one there
    # with the Voices tool -- are a chord in it, not a grid too coarse (one
    # would be pushed a 32nd late, or dropped).
    notation = notation_for_span(
        audio_path,
        with_chords([], lines.upper),
        beats,
        region,
        lower_voice=with_chords([], lines.lower),
        horn_parts=parts,
        lower_transpose=lower_transpose,
        **kwargs,
    )
    return notation, lines


def _time_at(position: float, beats: list[float]) -> float:
    """The time of a beat position (`quantize.beat_position`'s inverse)."""
    index = min(max(0, int(position)), len(beats) - 2)
    return beats[index] + (position - index) * (beats[index + 1] - beats[index])


def _unlag_together(
    upper: list[NoteEvent], lower: list[NoteEvent], beats: list[float], config: Config
) -> tuple[list[NoteEvent], list[NoteEvent]]:
    """Both horns with the line's lag taken out, read ONCE over all their
    onsets (`quantize.literal_lags`) and applied to each: two horns attack a
    chord together, and a lag read per voice could write one of them on the
    beat and the other on the "e". A note keeps its length."""
    from swingscribe.stages import quantize

    qc = config.quantize
    lags = quantize.literal_lags(
        [n.onset for n in (*upper, *lower)], beats, qc.lag_window_beats, qc.lag_cap, qc.lag_floor
    )
    if not lags:
        return upper, lower

    def moved(note: NoteEvent) -> NoteEvent:
        position = quantize.beat_position(note.onset, beats)
        if position is None:
            return note
        onset = _time_at(quantize.unlag_position(position, lags), beats)
        return note if onset == note.onset else note.model_copy(update={"onset": onset})

    return [moved(n) for n in upper], [moved(n) for n in lower]


def merge_horn_voices(
    upper: Notation | None, lower: Notation | None, key: int | None = None
) -> Notation:
    """Two separately notated horns as voices 1 and 2 of ONE staff.

    Bar by bar over the union of both voices' bars. In a bar where the lower
    horn sounds, the upper voice's stems go up and the lower's down, and
    the lower voice's rests are written but not drawn (print-object="no"):
    a reader sees one line resting, not two. A bar where only the upper horn
    sounds is the upper voice alone, stems left to the reader, with no
    lower-voice rests at all. The upper voice's rests are always drawn. The
    key is read ONCE over both voices (`merge_staves`' rule); `key` is the
    listener's when they chose one.
    """
    from swingscribe.stages import notate

    voices = {voice: n for voice, n in ((1, upper), (2, lower)) if n is not None}
    template = next((n for n in voices.values() if n.bars), None) or upper or lower or Notation()
    bars_of = {voice: {bar.number: bar for bar in n.bars} for voice, n in voices.items()}
    numbers = sorted({number for bars in bars_of.values() for number in bars})
    if key is None:
        sounding = _sounding(bars_of)
        key = notate.detect_key(sounding) if sounding else template.key_fifths
    merged: list[NotatedBar] = []
    signature = (4, 4)
    for number in range(numbers[0], numbers[-1] + 1) if numbers else ():
        found = [bars[number] for bars in bars_of.values() if number in bars]
        if found:
            signature = found[0].time_signature
        length = signature[0] * 4.0 / signature[1]
        top = bars_of.get(1, {}).get(number)
        bottom = bars_of.get(2, {}).get(number)
        both = bottom is not None and any(not n.is_rest for n in bottom.notes)
        written: list[NotatedNote] = []
        for note in top.notes if top is not None else notate.fill_rests([], length):
            stem = "up" if both and not note.is_rest else ""
            written.append(_respelled(note, key, voice=1, staff=1, stem=stem, hidden=False))
        if both:
            for note in bottom.notes:
                stem = "" if note.is_rest else "down"
                written.append(
                    _respelled(note, key, voice=2, staff=1, stem=stem, hidden=note.is_rest)
                )
        merged.append(NotatedBar(number=number, time_signature=signature, notes=written))
    return Notation(
        bars=merged,
        key_fifths=key,
        swing=template.swing,
        transpose=template.transpose,
        title=template.title,
        double_time=template.double_time,
    )


# A part whose written notes sit mostly under middle C reads on a bass staff:
# the median written pitch, weighted by length, decides (`clef_for`).
CLEF_SPLIT = 60


def clef_for(bars: list[NotatedBar], transpose: int = 0) -> str:
    """A part's clef by its register: "bass" when the length-weighted median
    of its WRITTEN pitches (concert pitch plus the part's transposition --
    concert pitch itself for a C part) is under middle C, else "treble"."""
    pitches = [
        (note.pitch + transpose, note.duration)
        for bar in bars
        for note in bar.notes
        if not note.is_rest
    ]
    if not pitches:
        return "treble"
    pitches.sort()
    half = sum(d for _p, d in pitches) / 2.0
    running = 0.0
    for pitch, duration in pitches:
        running += duration
        if running >= half:
            return "bass" if pitch < CLEF_SPLIT else "treble"
    return "treble"


def merge_horn_parts(
    upper: Notation | None,
    lower: Notation | None,
    key: int | None = None,
    lower_transpose: int | None = None,
) -> Notation:
    """Two separately notated horns as two PARTS of one page: the upper
    part, carrying the lower as `parts[0]`. Both over the same bars (a bar a
    horn sits out is a whole rest in its part), in ONE concert key read over
    both (`merge_staves`' rule), each with its own transposition -- the
    lower's `lower_transpose`, else the upper's -- and its own clef by its
    register (`clef_for`). No octave is moved and no unison merged: each
    part is what its horn played."""
    from swingscribe.stages import notate

    voices = {voice: n for voice, n in ((1, upper), (2, lower)) if n is not None}
    template = next((n for n in voices.values() if n.bars), None) or upper or lower or Notation()
    bars_of = {voice: {bar.number: bar for bar in n.bars} for voice, n in voices.items()}
    numbers = sorted({number for bars in bars_of.values() for number in bars})
    if key is None:
        sounding = _sounding(bars_of)
        key = notate.detect_key(sounding) if sounding else template.key_fifths
    transposes = {
        1: template.transpose,
        2: template.transpose if lower_transpose is None else lower_transpose,
    }
    parts: dict[int, Notation] = {}
    for voice, name in ((1, "Upper"), (2, "Lower")):
        written: list[NotatedBar] = []
        signature = (4, 4)
        for number in range(numbers[0], numbers[-1] + 1) if numbers else ():
            found = [bars[number] for bars in bars_of.values() if number in bars]
            if found:
                signature = found[0].time_signature
            length = signature[0] * 4.0 / signature[1]
            bar = bars_of.get(voice, {}).get(number)
            notes = bar.notes if bar is not None else notate.fill_rests([], length)
            written.append(
                NotatedBar(
                    number=number,
                    time_signature=signature,
                    notes=[
                        _respelled(n, key, voice=1, staff=1, stem="", hidden=False) for n in notes
                    ],
                )
            )
        parts[voice] = Notation(
            bars=written,
            key_fifths=key,
            swing=template.swing,
            transpose=transposes[voice],
            title=template.title,
            double_time=template.double_time,
            clef=clef_for(written, transposes[voice]),
            part_name=name,
        )
    head = parts[1]
    head.parts = [parts[2]]
    return head


def _sounding(bars_of: dict[int, dict[int, NotatedBar]]) -> list[tuple[int, float]]:
    """(pitch, duration) of every sounding note, chord members included: what
    one key signature is read from, over every staff or voice of a page."""
    return [
        (pitch, note.duration)
        for bars in bars_of.values()
        for bar in bars.values()
        for note in bar.notes
        if not note.is_rest
        for pitch in (note.pitch, *note.chord)
    ]


def _respelled(note: NotatedNote, key: int, **update) -> NotatedNote:
    """A note moved into a merged page: `update`, and spelled in its key."""
    from swingscribe.stages import notate

    if not note.is_rest:
        step, alter, octave = notate.spell(note.pitch, key)
        update |= {"step": step, "alter": alter, "octave": octave}
    return note.model_copy(update=update)


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
    sounding = _sounding(bars_of)
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
