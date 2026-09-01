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

# (actual, normal) tuplets this notater can write, tried in this order. 3:2 is
# the ordinary triplet. 5:4 and 7:4 exist for WJazzD: measured across all 456
# solos, a beat divided into 5 or 7 equal parts is the entire residue left
# over after triplets are handled — neither a power-of-two value nor
# on-thirds, so before this it could only be approximated as a tied chain of
# binary slivers, which is what produced tied 32nd notes where the Jazzomat
# lead sheet writes a clean 5-tuplet. Both use "in the time of 4": the written
# value a quintuplet or septuplet is drawn in is a sixteenth, the value 4
# unmodified notes would fill the beat with — the same convention engraving
# software uses, and the reason a beat divided by 5 measures out to exactly a
# sixteenth's worth times 4/5.
TUPLET_RATIOS: tuple[tuple[int, int], ...] = ((3, 2), (5, 4), (7, 4))


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


def tuplet_value(duration: float, ratio: tuple[int, int]) -> float | None:
    """The note value `duration` is written as inside this (actual, normal)
    tuplet, if any — the general form of `triplet_value` for any ratio in
    `TUPLET_RATIOS`."""
    actual, normal = ratio
    for value in NOTE_VALUES:
        if _close(duration, value * normal / actual):
            return value
    return None


def _on_nths(position: float, unit_start: float, unit_end: float, n: int) -> bool:
    parts = (position - unit_start) * n / (unit_end - unit_start)
    return abs(parts - round(parts)) < 1e-4


def _on_thirds(position: float, unit_start: float, unit_end: float) -> bool:
    return _on_nths(position, unit_start, unit_end, 3)


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


# The note values a metrical unit may be halved down through: powers of two
# only. A unit whose length is one of these is divided in two; a unit that is
# three of them is divided in THREE. Dotted values are deliberately absent -
# 1.5 is a length a note can have, but it is not a unit anything subdivides
# into.
BINARY_UNITS = (8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125)


def _is_binary_unit(length: float) -> bool:
    return any(_close(length, v) for v in BINARY_UNITS)


def split_points(unit_start: float, unit_end: float) -> list[float]:
    """Where a metrical unit is cut, in engraving order.

    Halving is right in duple metre and WRONG in triple. A 3/4 bar halved goes
    3 -> 1.5 -> 0.75 -> 0.375, and not one of those cuts lands on a beat: the
    recursion below never finds a legal boundary, bottoms out at its "nothing
    left to divide" guard, and emits slivers. That is not a cosmetic failure.
    Measured on the one 3/4 score in the benchmark it produced 12 bars that did
    not add up to their time signature and 14 notes of duration ZERO, which is
    a MusicXML file no notation program should be asked to open.

    So: a unit that IS a power-of-two value is halved; a unit that is three of
    them is divided in three; anything else (5/4 and friends) has the largest
    whole value peeled off the front, which at least leaves both pieces
    notatable.

    6/8 is not distinguished from 3/4 here - both arrive as three quarter notes
    and both get cut into three. Grouping 6/8 as two dotted quarters needs the
    time signature, which this stage is not given.
    """
    length = unit_end - unit_start
    if _is_binary_unit(length):
        return [unit_start + length / 2.0]
    if _is_binary_unit(length / 3.0):
        return [unit_start + length / 3.0, unit_start + 2.0 * length / 3.0]
    for value in BINARY_UNITS:
        if value < length - TICK:
            return [unit_start + value]
    return [unit_start + length / 2.0]


def _symmetric_syncopation(a: float, length: float, unit_start: float) -> bool:
    """May this note straddle a division it is CENTRED on?

    The engraving allowance behind every jazz syncopation: a plain binary
    value that starts an odd multiple of half its own length into the unit
    sits symmetrically about the division it crosses — a quarter on any
    "and", the middle quarter of the charleston figure — and the convention
    writes it as ONE symbol, no tie. The listener's hand transcriptions do
    exactly this (their tie rate is 0.022; ours read 0.098 with 58% of the
    excess WITHIN the bar, D14). A value that is NOT symmetric about what it
    crosses — a quarter starting on an offbeat sixteenth — still ties, which
    is the half of the conservative rule actually protecting readability.

    Dotted binary values get the same courtesy on a weaker condition: a
    dotted value has no single centre, but one that starts on a multiple of
    its own dot-unit (the eighth, for a dotted quarter) is the idiomatic
    figure — the dotted quarter on beat two — and the page writes it whole.
    One starting off its dot-grid (an offbeat sixteenth) still ties.
    """
    if any(_close(length, v) for v in BINARY_UNITS):
        half = length / 2.0
        steps = (a - unit_start) / half
        return abs(steps - round(steps)) * half <= TICK and round(steps) % 2 == 1
    if any(_close(length / 1.5, v) for v in BINARY_UNITS):
        dot_unit = length / 3.0
        steps = (a - unit_start) / dot_unit
        return abs(steps - round(steps)) * dot_unit <= TICK
    return False


def _subdivide(a: float, b: float, unit_start: float, unit_end: float, out: list) -> None:
    if b - a <= TICK:
        return
    length = b - a
    flush = _close(a, unit_start) or _close(b, unit_end)
    points = split_points(unit_start, unit_end)
    crosses = any(a < p - TICK and b > p + TICK for p in points)
    # The syncopation allowance applies only where the metre HALVES — a unit
    # that divides in three (a 3/4 bar) has no symmetric middle to be centred
    # on, and hiding a ternary beat is exactly what the conservative rule is
    # for. len(points) == 1 is "this unit halves".
    halving = len(points) == 1
    if is_notatable(length) and (
        flush or not crosses or (halving and _symmetric_syncopation(a, length, unit_start))
    ):
        out.append((a, length, None))
        return
    # A tuplet is allowed to live inside one beat and no larger unit. Wider
    # than that and a triplet figure would be written across a beat boundary,
    # which is unreadable and is not what quantize found either — it chooses
    # the grid per beat.
    if unit_end - unit_start <= QUARTER + TICK:
        for ratio in TUPLET_RATIOS:
            actual, _normal = ratio
            if (
                tuplet_value(length, ratio) is not None
                and _on_nths(a, unit_start, unit_end, actual)
                and _on_nths(b, unit_start, unit_end, actual)
            ):
                out.append((a, length, ratio))
                return
    if unit_end - unit_start <= 0.125 + TICK:
        # Below a thirty-second there is nothing left to divide; emit what we
        # have rather than recursing forever on an unnotatable sliver.
        out.append((a, length, None))
        return
    bounds = [unit_start, *points, unit_end]
    for lo, hi in zip(bounds, bounds[1:], strict=False):
        if a >= lo - TICK and b <= hi + TICK:
            _subdivide(a, b, lo, hi, out)
            return
    # Straddles a division: cut at the first one crossed. The head lands inside
    # the sub-unit ending there; the tail is re-divided against everything still
    # to come, which is what lets a 3/4 bar's remaining two beats halve normally
    # once the first beat has been cut off.
    cut = next((p for p in points if a < p - TICK and b > p + TICK), None)
    if cut is None:
        # Not inside any sub-unit and crossing none of them: the span reaches
        # outside the unit it was handed. Nothing left to divide by, so emit it
        # rather than raise - a note that cannot be split is still a note.
        out.append((a, length, None))
        return
    head_start = max((lo for lo in bounds if lo <= a + TICK), default=unit_start)
    _subdivide(a, cut, head_start, cut, out)
    _subdivide(cut, b, cut, unit_end, out)


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


# The shortest rest anyone writes in this music. Below an EIGHTH, a gap
# between a note's written end and the next onset is not a rest - see
# close_short_gaps.
#
# It was a sixteenth. Counted across the ten hand transcriptions in the
# benchmark, the listener wrote exactly ONE sixteenth rest in 504 rests and no
# rest shorter than that; we were writing 9.4 per hundred notes. A player who
# lays back - Mobley, most of Someday My Prince Will Come - produces a
# sixteenth of silence before every offbeat, and writing it down records the
# lay-back as a rhythm instead of as the feel it is.
#
# Raising it removed 93% of the sub-eighth rests across the four hand scores
# the notation harness can pair (260 -> 18) and moved the notated-rhythm score
# on NONE of them: rhythm compares onset POSITIONS, and closing a gap changes
# the previous note's duration, not any onset. A readability change with no
# measured cost, which is the only kind worth making without a benchmark to
# defend it.
MIN_REST = 0.5


# Note VALUES anyone writes: any number of sixteenths, or any number of
# triplet eighths. Counted over the ten hand transcriptions, 3629 of the
# listener's 3646 written values are in this set, and the 17 that are not are
# thirty-seconds and triplet sixteenths -- 0.5% of the page.
#
# The floor is a SIXTEENTH on purpose. It is the same judgement as MIN_REST:
# the listener plays along to the record for exact timing and wants the page
# readable, so a value below a sixteenth is written as one.
# NOT rounded. A candidate of 0.333333 makes two of them 0.666666, and a
# tuplet group whose pieces must land on sixths of a beat then misses by 2e-6
# -- which is a corrupt file in MuseScore, not a rounding nicety.
BINARY_VALUES = [0.25 * k for k in range(1, 65)]
TERNARY_VALUES = [k / 3.0 for k in range(1, 97)]


def snap_values(
    events: list[tuple[int, float, float, int]],
    bars_index,
) -> list[tuple[int, float, float, int]]:
    """Round each written duration to a value a reader can read.

    ## The defect this fixes

    Quantize snaps ONSETS to a grid and nothing ever snapped DURATIONS. For
    the 90-93% of notes that run legato into the next one that never showed,
    because `notated_durations` had already replaced the duration with the gap
    -- which is grid-to-grid and therefore on the grid. It is the other 7-10%,
    the note genuinely followed by a rest, that was written to the
    millisecond: a played length of 0.476 quarter notes went to
    `split_for_meter` as 0.476, came back as a sixteenth tied to a
    thirty-second tied to a sliver, and left an unwritable rest behind it.

    That is exactly what the listener reported -- "the dotted 1/32 notes with
    strange ties" -- and it was never a timing problem. It was a page that
    wrote a duration nobody asked for to a precision nobody wanted.

    ## Measured, including the part that says this changes nothing here

    **On our own pipeline it moves nothing.** Over the thirty notations the
    eval harness builds, mean readability goes 0.9941 to 0.9939 and no rhythm,
    value or F1 number moves at all. The reason is `without_overlap`, which
    truncates every note at the next onset: 93-96% of our notated notes come
    out filling their gap exactly, and a gap between two grid positions is on
    the grid. (NOT `notated_durations` -- `legato_fill` ships at 0.0, off, so
    that function returns early on our own path.) This rule only ever sees the
    other 4-7%, the note genuinely followed by a rest.

    **On a score built from WJazzD's metrical annotation it is decisive**,
    because there no duration inherits a gap -- they are all performed seconds.
    Over the 172 of 456 solos whose onsets sit on subdivisions writable at all:

                             before    after
        readability           0.788    0.982
        notes below a 16th   12.8%     0.16%
        notes tied            0.246    0.119

    Over all 456 it was 0.729 to 0.882, and the residue was quintuplet and
    septuplet ONSETS -- unwritable in this notater whatever their duration,
    because `_subdivide` had no tuplet ratio but 3:2. `TUPLET_RATIOS` closes
    that: with 5:4 and 7:4 added (and `export.DIVISIONS` raised from 24 to 840
    so a group of five or seven still sums to an exact beat), mean readability
    over all 456 rises again, to 0.9455, mean notes-below-a-16th falls to
    4.6%, and Freddie Hubbard's Maiden Voyage (melid 168, bar 6) writes a
    quintuplet where it used to write four tied thirty-seconds.

    So it ships as insurance and for `wjazz.annotation_notation`, not as a fix
    to a defect the shipped pipeline currently has. Said plainly because the
    opposite claim would have been easy to make and wrong.

    ## The clamp

    A snapped value may never exceed the gap to the next onset. `without_overlap`
    has already run by this point, so rounding up past the next note would put
    two notes sounding at once in a single-line score -- and `fill_rests` would
    then be handed a negative gap.
    """
    if not events:
        return events
    absolute = [bars_index.start_of(bar) + beat for bar, beat, _d, _p in events]
    ternary = ternary_beats(absolute)
    out = []
    for index, (bar, beat, duration, pitch) in enumerate(events):
        gap = absolute[index + 1] - absolute[index] if index + 1 < len(events) else None
        values = TERNARY_VALUES if int(absolute[index] // 1.0) in ternary else BINARY_VALUES
        out.append((bar, beat, snap_value(duration, gap, values), pitch))
    return out


def ternary_beats(absolute: list[float]) -> set[int]:
    """Which beats hold onsets on thirds rather than on quarters.

    The grid is a property of the BEAT, chosen by quantize one beat at a time,
    and a duration has to end on the same one its neighbours start on. Snapping
    to whichever of the two happens to be nearer is what left a triplet-eighth
    rest sitting in a beat of sixteenths -- the twelfth-of-a-beat sliver that
    `close_short_gaps` exists to prevent, arriving from the other direction.
    """
    beats: set[int] = set()
    for position in absolute:
        fraction = position % 1.0
        to_third = min(abs(fraction - third) for third in (0.0, 1 / 3, 2 / 3, 1.0))
        to_quarter = min(abs(fraction - q / 4.0) for q in range(5))
        if to_third < to_quarter - TICK:
            beats.add(int(position // 1.0))
    return beats


def snap_value(duration: float, gap: float | None, values: list[float] | None = None) -> float:
    """One duration to the nearest writable value, never past `gap`.

    NEAREST, and nothing cleverer. Preferring a value whose leftover gap is
    itself writable -- nothing, or at least a `MIN_REST` -- was tried and is
    much worse: it pushes the value down to open a real rest, and mean
    readability over our thirty notations falls 0.9941 to 0.9678 while short
    rests rise on twenty-eight of them. Measured, and not worth revisiting.
    """
    values = BINARY_VALUES if values is None else values
    if gap is not None:
        values = [value for value in values if value <= gap + TICK] or [gap]
    return min(values, key=lambda value: (abs(value - duration), value))


def close_short_gaps(
    events: list[tuple[int, float, float, int]],
    bars_index,
    min_rest: float = MIN_REST,
) -> list[tuple[int, float, float, int]]:
    """Extend a note to the next onset when the gap is too short to be a rest.

    Quantize snaps ONSETS to the grid it chose for each beat. Durations get no
    such treatment, so a note's written end can land off that grid - a played
    length that reached a sixteenth in a beat whose onsets are thirds, or a
    third in a beat whose onsets are halves. `fill_rests` then writes the
    difference as a rest of a twelfth or a sixth of a beat.

    Nobody notates those, and the transcriber has no evidence for them: it
    cannot hear a rest a twelfth of a beat long, only a note that was tongued
    slightly short. Worse, the rest breaks the beat's tuplet group, because
    the group no longer begins and ends on thirds - which is what MuseScore
    reports as a corrupted measure.

    So a gap shorter than `min_rest` goes back to the note that was played.
    This is deliberately much narrower than `legato_fill`, which asks the
    aesthetic question (do humans write jazz legato?) and measured neutral.
    This asks whether the rest is *writable at all*, and is bounded by a note
    value rather than by a ratio.

    THE GAP IS CLOSED FROM THE LEFT, and the alternative was measured. Pulling
    the note AFTER the gap back onto the beat scores better against the ten
    hand transcriptions - notated rhythm 0.711 -> 0.752 with notated value
    unchanged, against 0.711 / 0.672 -> 0.628 for extending. It is still wrong
    to do here: it lands the moved onset on the previous note's off-grid end,
    which inside a ternary beat is not a third, and the tuplet group it breaks
    is the corrupted measure this function exists to prevent.

    That +0.041 is not nothing, though, and it says where it belongs. A note
    sitting a sixteenth late inside a beat the human wrote as two eighths is a
    grid chosen too fine, and the place to fix that is `choose_grid` with the
    tempo it is writing at (D11), not a repair pass afterwards.
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
    legato_cap: float = 0.0,
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

    ## `legato_cap` — the same question asked of the GAP instead of the player

    A ratio asks "did the player hold it?", which is articulation, and a lead
    sheet does not write articulation. On our own path that question is moot:
    `legato_fill` ships at 0.0 and `without_overlap` has already truncated
    every note at the next onset, so the durations arrive grid-to-grid. It
    becomes the wrong question only where the duration is a careful human's
    note-off, honest about a player who tongues short.

    Measured on WJazzD's annotation of Dexter Gordon's Cheese Cake: he plays
    0.52 of a one-beat gap, the ratio test fails at 0.75, and we write an
    eighth plus an eighth rest where the Jazzomat lead sheet writes a quarter.
    Over all 456 solos the ratio manufactures 2.07 sub-eighth rests per 100
    events; a cap of two beats brings that to 1.14 and raises readability
    0.882 to 0.888, WITHOUT the failure the ratio route has -- dropping the
    ratio toward zero instead ties a phrase-ending note across four beats of
    silence into the next phrase.

    So `legato_cap` fills a gap because the gap is short enough to BE a note
    value, and leaves anything longer as a note followed by a real rest.
    Default 0.0, which is off. The shipped pipeline passes neither this nor a
    non-zero `legato_fill`, and all 436 baselines were verified unchanged.
    """
    if len(events) < 2 or (legato_fill <= 0 and legato_cap <= 0):
        return events
    absolute = [bars_index.start_of(bar) + beat for bar, beat, _d, _p in events]
    out = []
    for index, (bar, beat, duration, pitch) in enumerate(events):
        if index + 1 < len(events):
            gap = absolute[index + 1] - absolute[index]
            within_cap = legato_cap > 0 and gap <= legato_cap + TICK
            holds = legato_fill > 0 and duration >= legato_fill * gap
            if gap > TICK and (within_cap or holds):
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
    legato_cap: float = 0.0,
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
    events = notated_durations(
        without_overlap(quantized, bars_index), bars_index, legato_fill, legato_cap
    )
    # Values before gaps. `close_short_gaps` extends a note to the NEXT ONSET,
    # which is already on the grid, so what it produces is grid-aligned by
    # construction and needs no second rounding; doing it the other way round
    # would round the extension back off the onset and re-open the gap.
    events = snap_values(events, bars_index)
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
