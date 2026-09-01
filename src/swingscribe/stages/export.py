"""Stage 7 — Export: Notation → MusicXML (plan §5 stage 7).

The end of the pipeline, and the first point at which any of this can be
opened by a musician. Plan §5's acceptance for the notation half is exactly
that: the file opens cleanly in MuseScore with no import warnings.

## Written pitch happens here and nowhere else

Everything upstream is concert pitch, deliberately — the benchmark's ground
truth is concert pitch, and a stage that silently transposed would invalidate
every comparison against it (see `notate.py`). But MusicXML's `<pitch>` for a
transposing part is the WRITTEN pitch, with a `<transpose>` element saying how
to get back to sounding. So the transposition is applied here, once, and the
key signature moves with it: a tenor part in concert F is written in G.

That last point is easy to get wrong in a way that looks right. Transposing
the notes without transposing the key signature produces a part that sounds
correct and is covered in accidentals.

## Divisions

MusicXML measures duration in integer divisions of a quarter note, so the
number has to be divisible by everything we can produce: 8 for a thirty-second,
3 for a triplet, and — since `TUPLET_RATIOS` grew a 5:4 and a 7:4 — 5 and 7 for
a quintuplet and a septuplet. 840 is the smallest divisible by all four. Below
that, a quintuplet's five 16ths round to 5 ticks each on the old 24-division
grid (24/5 is not an integer) and sum to 25 — one tick over the beat they came
from, in EVERY quintuplet, which is exactly the kind of bar-does-not-add-up
file `notate.py` exists to prevent. 840 keeps every duration we emit an exact
integer — no rounding, so a bar that added up in `notate` still adds up on the
page.
"""

from pathlib import Path
from xml.etree import ElementTree

from swingscribe.config import Config
from swingscribe.model import Document, NotatedNote, Notation
from swingscribe.stages.notate import QUARTER, spell

DIVISIONS = 840  # per quarter note: divisible by 8, 3, 5, 7 (32nds, tuplets)

# Written note value in quarter notes → (MusicXML type, number of dots).
NOTE_TYPES = {
    8.0: ("breve", 0),
    6.0: ("whole", 1),
    4.0: ("whole", 0),
    3.0: ("half", 1),
    2.0: ("half", 0),
    1.5: ("quarter", 1),
    1.0: ("quarter", 0),
    0.75: ("eighth", 1),
    0.5: ("eighth", 0),
    0.375: ("16th", 1),
    0.25: ("16th", 0),
    0.1875: ("32nd", 1),
    0.125: ("32nd", 0),
}
# Semitones of transposition → the same interval counted in fifths. Solving
# 7f ≡ semitones (mod 12): a major second up is two fifths up, a major sixth
# three. This is what keeps the written key signature correct.
_FIFTHS_OF_SEMITONE = {n: ((7 * n) % 12 + 5) % 12 - 5 for n in range(12)}


def note_type(written: float) -> tuple[str, int]:
    """Written duration in quarter notes → (type, dots). Nearest wins."""
    best = min(NOTE_TYPES, key=lambda v: abs(v - written))
    return NOTE_TYPES[best]


def fifths_for_transpose(semitones: int) -> int:
    """How far the key signature moves when the part is transposed."""
    return _FIFTHS_OF_SEMITONE[semitones % 12]


def _duration_ticks(note: NotatedNote) -> int:
    return int(round(note.duration * DIVISIONS))


def tuplet_groups(notes: list[NotatedNote]) -> dict[int, str]:
    """Index -> "start" or "stop" for the ends of each run of tuplet notes.

    `<time-modification>` says how long a tuplet note lasts; it does not say
    where the group begins and ends. MuseScore draws the bracket and the
    number from `<notations><tuplet>`, and without it reads a bare run of
    time-modified notes as a measure it has to repair.

    A run ends at a beat boundary as well as at the first non-tuplet note: two
    consecutive triplet beats are two triplets, not one six-note group. It also
    ends at a change of ratio — a triplet followed directly by a quintuplet in
    the same beat is two groups, not one bracket claiming a ratio that fits
    neither.
    """
    marks: dict[int, str] = {}
    run: list[int] = []

    def close() -> None:
        if run:
            marks[run[0]] = "start"
            marks[run[-1]] = "stop"
            run.clear()

    position = 0.0
    beat = 0
    ratio: tuple[int, int] | None = None
    for index, note in enumerate(notes):
        if note.tuplet is None:
            close()
        else:
            here = int(position / QUARTER + 1e-9)
            if run and (here != beat or note.tuplet != ratio):
                close()
            if not run:
                beat = here
                ratio = note.tuplet
            run.append(index)
        position += note.duration
    close()
    return marks


def _append_note(
    parent,
    note: NotatedNote,
    transpose: int,
    written_key: int,
    tuplet_mark: str | None = None,
) -> None:
    element = ElementTree.SubElement(parent, "note")
    if note.is_rest:
        ElementTree.SubElement(element, "rest")
    else:
        step, alter, octave = spell(note.pitch + transpose, written_key)
        pitch = ElementTree.SubElement(element, "pitch")
        ElementTree.SubElement(pitch, "step").text = step
        if alter:
            ElementTree.SubElement(pitch, "alter").text = str(alter)
        ElementTree.SubElement(pitch, "octave").text = str(octave)
    ElementTree.SubElement(element, "duration").text = str(_duration_ticks(note))

    # A tie is two things in MusicXML: <tie> is what sounds, <tied> is what is
    # drawn. Writing only one of them opens with a warning in some readers and
    # silently drops the tie in others, so both go in.
    if note.tie_stop and not note.is_rest:
        ElementTree.SubElement(element, "tie", {"type": "stop"})
    if note.tie_start and not note.is_rest:
        ElementTree.SubElement(element, "tie", {"type": "start"})

    ElementTree.SubElement(element, "voice").text = str(note.voice)
    # Written value = sounded duration * actual/normal — 3/2 for the ordinary
    # triplet, but this must not hardcode that ratio: a quintuplet (5:4) or
    # septuplet (7:4) note needs its own.
    if note.tuplet:
        actual, normal = note.tuplet
        written = note.duration * actual / normal
    else:
        written = note.duration
    kind, dots = note_type(written)
    ElementTree.SubElement(element, "type").text = kind
    for _ in range(dots):
        ElementTree.SubElement(element, "dot")
    if note.tuplet:
        actual, normal = note.tuplet
        modification = ElementTree.SubElement(element, "time-modification")
        ElementTree.SubElement(modification, "actual-notes").text = str(actual)
        ElementTree.SubElement(modification, "normal-notes").text = str(normal)
    tied = (note.tie_start or note.tie_stop) and not note.is_rest
    if tied or tuplet_mark:
        notations = ElementTree.SubElement(element, "notations")
        if note.tie_stop and not note.is_rest:
            ElementTree.SubElement(notations, "tied", {"type": "stop"})
        if note.tie_start and not note.is_rest:
            ElementTree.SubElement(notations, "tied", {"type": "start"})
        if tuplet_mark:
            ElementTree.SubElement(notations, "tuplet", {"type": tuplet_mark})


def voices_of(bar) -> list[tuple[int, list[NotatedNote]]]:
    """The bar's notes grouped by voice, lowest voice number first.

    A bar with only voice 1 — every bar, unless the piano second-voice overlay
    is on — comes back as a single group, so the common path writes exactly
    what it always did.
    """
    grouped: dict[int, list[NotatedNote]] = {}
    for note in bar.notes:
        grouped.setdefault(note.voice, []).append(note)
    return sorted(grouped.items())


def voice_notes_before(bar, number: int) -> list[NotatedNote]:
    """Everything already written in this measure before voice `number`."""
    return [n for n in bar.notes if n.voice < number]


def to_musicxml(notation: Notation, part_name: str = "Solo") -> str:
    """A complete score-partwise MusicXML document."""
    written_key = notation.key_fifths + fifths_for_transpose(notation.transpose)

    root = ElementTree.Element("score-partwise", {"version": "4.0"})
    work = ElementTree.SubElement(root, "work")
    ElementTree.SubElement(work, "work-title").text = notation.title or "Transcription"
    identification = ElementTree.SubElement(root, "identification")
    creator = ElementTree.SubElement(identification, "creator", {"type": "software"})
    creator.text = "SwingScribe"
    encoding = ElementTree.SubElement(identification, "encoding")
    ElementTree.SubElement(encoding, "software").text = "SwingScribe"

    part_list = ElementTree.SubElement(root, "part-list")
    score_part = ElementTree.SubElement(part_list, "score-part", {"id": "P1"})
    ElementTree.SubElement(score_part, "part-name").text = part_name

    part = ElementTree.SubElement(root, "part", {"id": "P1"})
    previous_signature = None
    for index, bar in enumerate(notation.bars):
        measure = ElementTree.SubElement(part, "measure", {"number": str(bar.number)})
        if index == 0 or bar.time_signature != previous_signature:
            attributes = ElementTree.SubElement(measure, "attributes")
            ElementTree.SubElement(attributes, "divisions").text = str(DIVISIONS)
            if index == 0:
                key = ElementTree.SubElement(attributes, "key")
                ElementTree.SubElement(key, "fifths").text = str(written_key)
            time = ElementTree.SubElement(attributes, "time")
            ElementTree.SubElement(time, "beats").text = str(bar.time_signature[0])
            ElementTree.SubElement(time, "beat-type").text = str(bar.time_signature[1])
            if index == 0:
                clef = ElementTree.SubElement(attributes, "clef")
                ElementTree.SubElement(clef, "sign").text = "G"
                ElementTree.SubElement(clef, "line").text = "2"
                if notation.transpose:
                    _append_transpose(attributes, notation.transpose)
            previous_signature = bar.time_signature
        if index == 0 and notation.swing:
            # The one word that makes the difference between a readable jazz
            # chart and a wrong one: the eighths on the page are even.
            direction = ElementTree.SubElement(measure, "direction", {"placement": "above"})
            direction_type = ElementTree.SubElement(direction, "direction-type")
            words = ElementTree.SubElement(direction_type, "words", {"font-style": "italic"})
            words.text = "Swing"
        if index == 0 and notation.double_time:
            # The listener's condition for double-time pages: the page must
            # say so, or its values read as twice what was played.
            direction = ElementTree.SubElement(measure, "direction", {"placement": "above"})
            direction_type = ElementTree.SubElement(direction, "direction-type")
            words = ElementTree.SubElement(direction_type, "words", {"font-style": "italic"})
            words.text = "Notated in double time"
        # Voices are written one after another, each rewound to the barline by
        # a <backup>. MusicXML has no interleaved form: a reader consumes a
        # voice until the duration runs out, so voice 2 must start by undoing
        # voice 1's advance or it lands in the next bar.
        for offset, (number, voice_notes) in enumerate(voices_of(bar)):
            if offset:
                backup = ElementTree.SubElement(measure, "backup")
                ElementTree.SubElement(backup, "duration").text = str(
                    sum(_duration_ticks(n) for n in voice_notes_before(bar, number))
                )
            marks = tuplet_groups(voice_notes)
            for position, note in enumerate(voice_notes):
                _append_note(measure, note, notation.transpose, written_key, marks.get(position))

    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">\n' + body + "\n"
    )


def transpose_element(semitones: int) -> tuple[int, int, int]:
    """Written-to-sounding, as MusicXML wants it: (diatonic, chromatic, octaves).

    `semitones` is our direction — written = sounding + semitones — and
    MusicXML's <transpose> is the other one, so every number here is negated.

    The two halves do not scale together and that is the whole difficulty: a
    major ninth is 14 semitones but only 8 staff steps. MusicXML wants the
    interval reduced into an octave plus a separate octave count, so the
    chromatic and diatonic parts describe the reduced interval and
    `octave-change` carries the rest. Bb tenor is (-1, -2, -1): down a major
    second, then down one more octave.

    Staff steps come from the fifths, which is the only representation that
    keeps interval spelling honest -- a major second is two fifths and one
    step, an augmented unison is seven fifths and none.
    """
    reduced = semitones % 12
    steps = (fifths_for_transpose(reduced) * 4) % 7
    octaves = (semitones - reduced) // 12
    return -steps, -reduced, -octaves


def _append_transpose(attributes, semitones: int) -> None:
    diatonic, chromatic, octaves = transpose_element(semitones)
    element = ElementTree.SubElement(attributes, "transpose")
    ElementTree.SubElement(element, "diatonic").text = str(diatonic)
    ElementTree.SubElement(element, "chromatic").text = str(chromatic)
    if octaves:
        ElementTree.SubElement(element, "octave-change").text = str(octaves)


def run(document: Document, config: Config) -> Document:
    if document.notation is None:
        raise ValueError("export requires notate to have run first (document.notation is None)")
    out_dir = Path(config.cache_dir) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(document.audio_path).stem
    written = []
    if "musicxml" in config.export.formats:
        path = out_dir / f"{stem}.musicxml"
        path.write_text(to_musicxml(document.notation, part_name=stem), encoding="utf-8")
        written.append(str(path))
    print(f"export: wrote {', '.join(written) if written else 'nothing'}")
    return document
