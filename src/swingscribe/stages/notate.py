"""Stage 6 — Notate: quantized notes → a notatable score (plan §5 stage 6).

Quantize left every note on a grid position with a bar and a beat. That is not
yet notation. Notation needs four more decisions, and each one is a place a
transcription stops looking like something a musician wrote:

1. **What key is this**, so the staff carries a key signature.
2. **How is each note spelled** — A♯ or B♭. Same key, same sound, and a bebop
   line spelled the wrong way is genuinely harder to read.
3. **What note values**, including where a duration has to become two symbols
   tied together because no single symbol has that length or sits there.
4. **Where the rests are**, because a bar has to add up.

## No music21

The plan names music21 for this stage. It is not a dependency of this project
and adding one is not a decision a stage gets to make by itself (CLAUDE.md),
so this is arithmetic instead — which everything above turns out to be. The
payoff is the same one the rest of the pipeline gets: the whole stage, key
detection and note spelling included, runs in CI with no heavy imports.

If music21 is wanted later it can wrap this; the types in `model.py` carry
everything a `Score` would need.

## Sounding pitch, always

`NotatedNote.pitch` is concert pitch everywhere in this stage. A tenor part is
written a major ninth above what it sounds, but that belongs to the part, not
to the note — `Notation.transpose` carries it, and export applies it. Baking
it into the notes would silently invalidate every comparison against the
concert-pitch ground truth the benchmark uses.
"""

import math

from swingscribe.config import Config
from swingscribe.model import Document, MeterSection, NotatedBar, NotatedNote, Notation

# Krumhansl-Kessler key profiles: the average perceived stability of each
# scale degree. Correlating a solo's pitch-class durations against all 24
# rotations is the standard key finder and needs nothing but arithmetic.
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

# Position on the line of fifths: ...F(-1) C(0) G(1) D(2) A(3) E(4) B(5)...
# A sharp adds 7, a flat subtracts 7. Spelling is then a nearest-neighbour
# question on this line, which is why it is the representation used here.
NATURAL_FIFTHS = {"F": -1, "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5}
STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# Durations a single notehead can express, in quarter notes, longest first.
# Dotted values included; double dots deliberately not — they are rare in
# jazz lead sheets and a tie reads better than a double dot.
NOTE_VALUES = (
    8.0,  # breve
    6.0,  # dotted whole
    4.0,  # whole
    3.0,  # dotted half
    2.0,  # half
    1.5,  # dotted quarter
    1.0,  # quarter
    0.75,  # dotted eighth
    0.5,  # eighth
    0.375,  # dotted sixteenth
    0.25,  # sixteenth
    0.1875,
    0.125,  # thirty-second
)
# The same values played three-to-the-space-of-two. Quantize picks a ternary
# grid for beats whose notes fit one better, so a third of a beat is a routine
# duration here — and it is not a note value at all. It is an eighth note
# carrying a 3:2 time modification, which is what TRIPLET_RATIO turns it into.
TRIPLET_RATIO = 1.5  # written value = sounded duration * 3/2
TRIPLET_VALUES = tuple(v / TRIPLET_RATIO for v in NOTE_VALUES)
QUARTER = 1.0  # a beat, in quarter notes — the unit a tuplet may live inside
TICK = 1e-6  # positions are grid-exact; this only absorbs float noise


def _close(a: float, b: float) -> bool:
    return abs(a - b) < TICK


def is_notatable(duration: float) -> bool:
    return any(_close(duration, v) for v in NOTE_VALUES)


def triplet_value(duration: float) -> float | None:
    """The note value this duration is written as inside a 3:2 tuplet, if any."""
    for value in TRIPLET_VALUES:
        if _close(duration, value):
            return value * TRIPLET_RATIO
    return None


def _on_thirds(position: float, unit_start: float, unit_end: float) -> bool:
    thirds = (position - unit_start) * 3.0 / (unit_end - unit_start)
    return abs(thirds - round(thirds)) < 1e-4


def detect_key(notes: list[tuple[int, float]]) -> int:
    """(pitch, duration) pairs → key signature in fifths, sharps positive.

    Weighted by duration rather than note count: a passing tone and a held
    tonic are not equal evidence, and in a bebop line the passing tones
    outnumber everything.

    Returns the SIGNATURE, not the tonic, so a minor key returns its relative
    major's signature — which is what actually gets drawn on the staff.
    """
    weights = [0.0] * 12
    for pitch, duration in notes:
        weights[pitch % 12] += max(0.0, duration)
    total = sum(weights)
    if total <= 0:
        return 0
    mean = total / 12.0
    centred = [w - mean for w in weights]

    def correlate(profile: tuple[float, ...], tonic: int) -> float:
        rotated = [profile[(i - tonic) % 12] for i in range(12)]
        p_mean = sum(rotated) / 12.0
        p = [v - p_mean for v in rotated]
        denominator = math.sqrt(sum(v * v for v in centred) * sum(v * v for v in p))
        if not denominator:
            return 0.0
        return sum(a * b for a, b in zip(centred, p, strict=True)) / denominator

    best = (-2.0, 0, True)
    for tonic in range(12):
        for profile, major in ((MAJOR_PROFILE, True), (MINOR_PROFILE, False)):
            score = correlate(profile, tonic)
            if score > best[0]:
                best = (score, tonic, major)
    _, tonic, major = best
    # A minor key is drawn with its relative major's signature.
    signature_tonic = tonic if major else (tonic + 3) % 12
    # Tonic pitch class → fifths, choosing the spelling engravers use
    # (F rather than E#, and 5 sharps rather than 7 flats).
    return {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: -6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}[
        signature_tonic
    ]


def spell(pitch: int, key_fifths: int) -> tuple[str, int, int]:
    """MIDI pitch → (step, alter, octave), spelled for this key signature.

    Every pitch class has two or three plausible spellings; the right one is
    the one nearest the key on the line of fifths. That single rule gives the
    diatonic notes their key spelling for free, and spells the chromatic ones
    the way a reader of that key expects — F♯ in G major, G♭ in D♭ major.

    The alternative, a fixed sharps-or-flats table, gets bebop wrong: a line
    in F wants B♭ and E♮ but also the occasional A♭, and a table cannot hold
    both.
    """
    pitch_class = pitch % 12
    # The diatonic band sits between key_fifths - 1 and key_fifths + 5, so its
    # centre is the natural place to measure "near this key" from.
    centre = key_fifths + 2
    best: tuple[float, str, int] | None = None
    for step, natural in NATURAL_FIFTHS.items():
        for alter in (-1, 0, 1):
            if (STEP_SEMITONE[step] + alter) % 12 != pitch_class:
                continue
            fifths = natural + 7 * alter
            distance = abs(fifths - centre)
            if best is None or distance < best[0]:
                best = (distance, step, alter)
    if best is None:  # unreachable for a real MIDI pitch, but never guess
        return "C", 0, pitch // 12 - 1
    _, step, alter = best
    # Octave belongs to the SPELLED letter, not the sounding pitch: B♯3 and C4
    # are one semitone apart in name and zero in sound.
    octave = (pitch - alter) // 12 - 1
    return step, alter, octave


def split_for_meter(
    start: float, duration: float, bar_length: float
) -> list[tuple[float, float, tuple[int, int] | None]]:
    """One note's span → the tied pieces it must be written as.

    A note is written as one symbol when a symbol of that length exists and
    sitting there does not hide the beat. Otherwise it is tied, and where to
    tie is decided by the metre rather than by convenience: the bar is halved,
    then halved again, and a note that straddles a division of the bar is cut
    at that division unless it starts or ends flush with the unit containing
    it. That is the standard engraving rule, and it is what stops a syncopated
    line from being written as a row of quarter notes that look like downbeats.

    Deliberately conservative. Given a choice between one symbol that could be
    misread and two tied symbols that cannot, this takes the tie.
    """
    pieces: list[tuple[float, float, tuple[int, int] | None]] = []
    _subdivide(start, start + duration, 0.0, bar_length, pieces)
    return pieces


def _subdivide(a: float, b: float, unit_start: float, unit_end: float, out: list) -> None:
    if b - a <= TICK:
        return
    length = b - a
    flush = _close(a, unit_start) or _close(b, unit_end)
    middle = (unit_start + unit_end) / 2.0
    crosses = a < middle - TICK and b > middle + TICK
    if is_notatable(length) and (flush or not crosses):
        out.append((a, length, None))
        return
    # A tuplet is allowed to live inside one beat and no larger unit. Wider
    # than that and a triplet figure would be written across a beat boundary,
    # which is unreadable and is not what quantize found either — it chooses
    # the grid per beat.
    if (
        unit_end - unit_start <= QUARTER + TICK
        and triplet_value(length) is not None
        and _on_thirds(a, unit_start, unit_end)
        and _on_thirds(b, unit_start, unit_end)
    ):
        out.append((a, length, (3, 2)))
        return
    if unit_end - unit_start <= 0.125 + TICK:
        # Below a thirty-second there is nothing left to divide; emit what we
        # have rather than recursing forever on an unnotatable sliver.
        out.append((a, length, None))
        return
    if b <= middle + TICK:
        _subdivide(a, b, unit_start, middle, out)
    elif a >= middle - TICK:
        _subdivide(a, b, middle, unit_end, out)
    else:
        _subdivide(a, middle, unit_start, middle, out)
        _subdivide(middle, b, middle, unit_end, out)


def fill_rests(notes: list[NotatedNote], bar_length: float) -> list[NotatedNote]:
    """Insert rests so the bar adds up. A bar that does not sum to its time
    signature is what makes a notation program refuse to open a file."""
    filled: list[NotatedNote] = []
    cursor = 0.0
    for note in sorted(notes, key=lambda n: n.beat):
        if note.beat > cursor + TICK:
            for start, length, tuplet in split_for_meter(cursor, note.beat - cursor, bar_length):
                filled.append(NotatedNote(beat=start, duration=length, is_rest=True, tuplet=tuplet))
        filled.append(note)
        cursor = max(cursor, note.beat + note.duration)
    if cursor < bar_length - TICK:
        for start, length, tuplet in split_for_meter(cursor, bar_length - cursor, bar_length):
            filled.append(NotatedNote(beat=start, duration=length, is_rest=True, tuplet=tuplet))
    return filled


# The shortest rest anyone writes in this music. Below a sixteenth, a gap
# between a note's written end and the next onset is not a rest — see
# close_short_gaps.
MIN_REST = 0.25


def close_short_gaps(
    events: list[tuple[int, float, float, int]],
    bars_index,
    min_rest: float = MIN_REST,
) -> list[tuple[int, float, float, int]]:
    """Extend a note to the next onset when the gap is too short to be a rest.

    Quantize snaps ONSETS to the grid it chose for each beat. Durations get no
    such treatment, so a note's written end can land off that grid — a played
    length that reached a sixteenth in a beat whose onsets are thirds, or a
    third in a beat whose onsets are halves. `fill_rests` then writes the
    difference as a rest of a twelfth or a sixth of a beat.

    Nobody notates those, and the transcriber has no evidence for them: it
    cannot hear a rest a twelfth of a beat long, only a note that was tongued
    slightly short. Worse, the rest breaks the beat's tuplet group, because
    the group no longer begins and ends on thirds — which is what MuseScore
    reports as a corrupted measure.

    So a gap shorter than a sixteenth goes back to the note that was played.
    This is deliberately much narrower than `legato_fill`, which asks the
    aesthetic question (do humans write jazz legato?) and measured neutral. This
    asks whether the rest is *writable at all*, and is bounded by a note value
    rather than by a ratio.
    """
    if len(events) < 2:
        return events
    absolute = [bars_index.start_of(bar) + beat for bar, beat, _d, _p in events]
    out = []
    for index, (bar, beat, duration, pitch) in enumerate(events):
        if index + 1 < len(events):
            gap = absolute[index + 1] - absolute[index]
            shortfall = gap - duration
            if TICK < shortfall < min_rest - TICK:
                duration = gap
        out.append((bar, beat, duration, pitch))
    return out


def _section_for_bar(bar: int, sections: list[MeterSection]) -> MeterSection | None:
    best = None
    for section in sections:
        if section.first_bar <= bar and (best is None or section.first_bar > best.first_bar):
            best = section
    return best


def without_overlap(quantized: list, bar_length_of) -> list[tuple[int, float, float, int]]:
    """(bar, beat, duration, pitch), with every note ending by the next onset.

    A transcription of one horn is a single line, but quantization does not
    know that: snapping can leave one note's rounded end past the next note's
    rounded start. On a piano roll that is invisible; in notation it is fatal,
    because two notes sounding at once in one voice make the bar add up to
    more than its time signature and a notation program will refuse the file.

    Truncating rather than dropping is deliberate — the overlap is a rounding
    artefact of a few milliseconds, not a second voice, so the note keeps its
    identity and loses only the sliver it should never have had.
    """
    ordered = sorted(quantized, key=lambda n: (n.bar, n.beat))
    absolute = []
    for note in ordered:
        start = bar_length_of.start_of(note.bar) + note.beat
        absolute.append([start, max(0.0, note.duration_beats), note.pitch, note.bar, note.beat])
    for i in range(len(absolute) - 1):
        room = absolute[i + 1][0] - absolute[i][0]
        if room < absolute[i][1]:
            absolute[i][1] = max(0.0, room)
    return [
        (bar, beat, duration, pitch)
        for _start, duration, pitch, bar, beat in absolute
        if duration > TICK
    ]


class _Bars:
    """Where each bar starts, in quarter notes, given the meter sections."""

    def __init__(self, sections: list[MeterSection], first: int, last: int):
        self.length: dict[int, float] = {}
        self._start: dict[int, float] = {}
        cursor = 0.0
        for bar in range(first, last + 2):
            section = _section_for_bar(bar, sections)
            signature = section.time_signature if section else (4, 4)
            self.length[bar] = signature[0] * 4.0 / signature[1]
            self.signature = signature
            self._start[bar] = cursor
            cursor += self.length[bar]
        self._first = first

    def start_of(self, bar: int) -> float:
        return self._start.get(bar, 0.0)

    def signature_of(self, bar: int, sections: list[MeterSection]) -> tuple[int, int]:
        section = _section_for_bar(bar, sections)
        return section.time_signature if section else (4, 4)


def notated_durations(
    events: list[tuple[int, float, float, int]],
    bars_index,
    legato_fill: float,
) -> list[tuple[int, float, float, int]]:
    """Played lengths → written lengths.

    Jazz is written legato and played detached. Measured on the three hand
    transcriptions, **90-93% of notated notes fill the gap to the next note
    exactly, and none exceed it** — so a written eighth is usually just "the
    space until the next note", regardless of how short it was tongued.
    Notating the played length instead writes a bebop eighth as a sixteenth,
    which is the single biggest disagreement with the human scores.

    The remaining 7-11% are notes genuinely followed by a rest, and they are
    told apart by how much of the gap the player actually filled.
    """
    if legato_fill <= 0 or len(events) < 2:
        return events
    absolute = [bars_index.start_of(bar) + beat for bar, beat, _d, _p in events]
    out = []
    for index, (bar, beat, duration, pitch) in enumerate(events):
        if index + 1 < len(events):
            gap = absolute[index + 1] - absolute[index]
            if gap > TICK and duration >= legato_fill * gap:
                duration = gap
        out.append((bar, beat, duration, pitch))
    return out


def build(
    quantized: list,
    sections: list[MeterSection],
    swing: bool,
    transpose: int,
    title: str = "",
    legato_fill: float = 0.0,
) -> Notation:
    """Quantized notes → bars of spelled, tied, rest-filled notation."""
    if not quantized:
        return Notation(swing=swing, transpose=transpose, title=title)

    key_fifths = detect_key([(n.pitch, n.duration_beats) for n in quantized])
    # Start where the MUSIC starts, not where the soloist does. A player who
    # comes in on bar 2 leaves bar 1 as a bar of rests, which is what a reader
    # expects; a score whose first measure is numbered 2 is a score with a bar
    # missing, and some readers say so.
    first_bar = min(n.bar for n in quantized)
    if sections:
        opening = min(section.first_bar for section in sections)
        if opening <= first_bar:
            first_bar = opening
    last_bar = max(n.bar for n in quantized)
    bars_index = _Bars(sections, first_bar, last_bar + 4)
    events = notated_durations(without_overlap(quantized, bars_index), bars_index, legato_fill)
    # Before splitting, not after: the splitter can only pick a legal tuplet
    # group if the durations it is handed already land on the beat's grid.
    events = close_short_gaps(events, bars_index)

    by_bar: dict[int, list[NotatedNote]] = {}
    for bar_number, beat, duration, pitch in events:
        step, alter, octave = spell(pitch, key_fifths)
        bar, start, remaining = bar_number, beat, duration
        first_piece = True
        while remaining > TICK:
            bar_length = bars_index.length.get(bar, 4.0)
            here = min(remaining, bar_length - start)
            if here <= TICK:
                break
            pieces = split_for_meter(start, here, bar_length)
            for index, (piece_start, piece_length, tuplet) in enumerate(pieces):
                last_piece = index == len(pieces) - 1 and _close(here, remaining)
                by_bar.setdefault(bar, []).append(
                    NotatedNote(
                        beat=piece_start,
                        duration=piece_length,
                        pitch=pitch,
                        step=step,
                        alter=alter,
                        octave=octave,
                        tuplet=tuplet,
                        tie_start=not last_piece,
                        tie_stop=not first_piece,
                    )
                )
                first_piece = False
            remaining -= here
            bar += 1
            start = 0.0

    bars = []
    for number in range(first_bar, max(by_bar) + 1 if by_bar else first_bar):
        signature = bars_index.signature_of(number, sections)
        bar_length = signature[0] * 4.0 / signature[1]
        bars.append(
            NotatedBar(
                number=number,
                time_signature=signature,
                notes=fill_rests(by_bar.get(number, []), bar_length),
            )
        )
    return Notation(bars=bars, key_fifths=key_fifths, swing=swing, transpose=transpose, title=title)


def run(document: Document, config: Config) -> Document:
    stem = config.notate.stem or next(iter(document.quantized), "")
    quantized = document.quantized.get(stem, [])
    # Swing is a property of the track, decided once by quantize: if it warped
    # the grid, the eighths on the page are straight and the feel is a word
    # above the staff. Asking the spans again here could disagree with what
    # was actually written, so this asks what quantize did.
    swung = any(span.is_swung for span in document.swing)
    notation = build(
        quantized,
        document.meter,
        swing=swung,
        transpose=config.notate.transpose,
        title=config.notate.title,
        legato_fill=config.notate.legato_fill,
    )
    print(
        f"notate: {len(notation.bars)} bars, key {notation.key_fifths:+d} fifths, "
        f"{'swing' if notation.swing else 'straight'}, transpose {notation.transpose:+d}"
    )
    return document.model_copy(update={"notation": notation})
