"""Another tool's output, read the way our own page is read (docs/head-to-head.md).

The head-to-head scores a competitor's MusicXML with EXACTLY the functions
our own pages are scored by -- `benchmark.score_against_notation`,
`benchmark.readability`, `score_bars.bar_line_agreement` and the rest -- and
every one of them takes a `Notation`, not a parsed `mscz.Score`. So an
external file is read INTO a Notation, the model `notate` builds and
`export` writes, rather than compared Score-to-Score. Three reasons:

- `readability` needs what a Score throws away: rests, tuplet ratios, ties
  and the bar a note sits in. Read as a Score, a competitor's page could
  not be judged writable or not at all.
- It makes fairness testable. `read_musicxml` on what `export.to_musicxml`
  wrote must give back every number the scorers read off the original
  Notation -- the round trip in tests/test_external.py, and on real pages
  the control in scripts/head_to_head.py (our own exports, read back through
  this module, reproduce our pinned scores).
- The one MusicXML reader we had (`mscz.parse_musicxml`) was written for
  REFERENCES. It lays a short pickup bar out from its START, where a
  pickup's notes sound at its END, and it ignores `<transpose>`: harmless
  on a hand score, wrong on a page a transposing tool writes.

Two views come out, as `mscz.Score` has two:

- `notation` -- the page as written: every voice and staff, a chord folded
  into its head note (`NotatedNote.chord`), grace notes and unprinted rests
  left out. Readability, the key and the bar count are read off this.
- `line` -- the single line the scorers compare, by the rule the reference
  reader applies to a hand score (`mscz.parse_musicxml`'s `melody`): tied
  notes merged, then the TOP note of every simultaneity across voices and
  staves. Laid out so that `benchmark.notation_notes(line)` is exactly that
  list. On one of our own single-voice pages the two views hold the same
  notes.

Grace notes follow the REFERENCE's reader, because the two readers
disagree and a tool is compared against one of them (`graces=`): `"keep"`
(the default) keeps a grace note in the line as a pitch at its main note's
position with no length, as `mscz.parse` keeps a hand score's (.mscz);
`"compete"` lets it compete with its main note for that position, the
higher winning, as `mscz.parse_musicxml` reads a MusicXML reference (the
silver OMR pages). Read under the other rule, a tool that writes grace
notes would pay an insertion per grace that the reference cannot hold
(`graces_for`).

Pitches are CONCERT (sounding) throughout, as in every Notation: a
`<transpose>` is undone here, once. An `<octave-shift>` is NOT applied:
MusicXML's `<pitch>` under an 8va is already the sounding (or transposed)
pitch and the shift is display only -- unlike .mscz, which stores the
written pitch (`mscz.OTTAVA_SHIFT`).

Positions are counted in exact fractions of the file's own `<divisions>`
and turned into floats once, so a page read back lands on the same floats
our notate stage wrote rather than on a sum that drifted.

Timing. A page has no seconds, but a competitor's file usually carries a
tempo (`<sound tempo>`, `<metronome>`), and a MIDI file carries seconds
outright. `page_seconds` and `read_midi` turn either into `TimedNote`s so
the audio-against-audio measures (the MuseScore set's note F1, WJazzD's)
can be read where a tool delivers timing, and `write_midi` writes our own
notes the same way, so SwingScribe reaches the head-to-head by the path
every other tool takes. The two are NOT interchangeable: a page is the
performance quantized, and timed off its own tempo our page loses WJazzD
note F1 0.19 against its MIDI (0.10 even placed on our own beat grid),
while two pages of the SAME notes timed that way differ by 0.09 on the hand
scores. So the script pairs note F1 only between rows timed by performed
onsets, and `midi_timing` catches a MIDI file that is a quantized page in
disguise -- and says "unknown", never "performed", when the file's clock is
too coarse to tell (`add_tempo` built the page-timed pseudo-tool that
measured this; docs/head-to-head.md section 8).

Excerpts. A tool given the first 29 seconds of a span is scored against
the part of the reference those seconds hold. `excerpt_reference` and
`wjazz_excerpt` decide which part, from where OUR transcription placed the
reference in time: fitting code, so it lives here with its tests rather
than in the script (CLAUDE.md).

Pure Python, stdlib only (the aligner and `benchmark.place_on_anchors` are
too): CI exercises all of it.
"""

from __future__ import annotations

import bisect
import math
import re
import struct
import zipfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

from swingscribe.model import NotatedBar, NotatedNote, Notation

STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_EPS = Fraction(1, 10**9)

# Words our own export writes (stages/export.py). A page that says it is in
# double time is written in doubled units, and `benchmark.notation_notes`
# halves it only if the Notation says so.
DOUBLE_TIME_WORDS = "notated in double time"
# A tempo marking or a "Swing" instruction: AnthemScore 6.3 writes swing "as
# straight eighths with a swing marking" (docs/landscape.md section 6), and
# whether a tool wrote one is worth reporting beside its rhythm.
_SWING = re.compile(r"\bswing", re.IGNORECASE)

# How a grace note enters the line (module docstring): kept beside its main
# note, as the .mscz reader keeps it, or competing with it for the top of
# its position, as the MusicXML reference reader lets it.
GRACE_RULES = ("keep", "compete")


def graces_for(reference: str | Path | None) -> str:
    """The grace rule of the reader a reference file is parsed with, by the
    dispatch `mscz.parse_any` itself makes: a MusicXML reference competes,
    anything else (a .mscz, WJazzD's performed notes) keeps."""
    from swingscribe.mscz import MUSICXML_SUFFIXES

    if reference is not None and Path(reference).suffix.lower() in MUSICXML_SUFFIXES:
        return "compete"
    return "keep"


@dataclass(frozen=True)
class TimedNote:
    """One note in seconds from the start of the audio the tool was given."""

    onset: float
    duration: float
    pitch: int
    velocity: int = 80
    channel: int = 0


@dataclass
class ExternalPage:
    """A MusicXML file read as a page (`notation`) and as a line (`line`)."""

    notation: Notation
    line: Notation
    # The line as written: (position in written quarters from the first bar
    # line, duration, pitch, is a grace note), in order. `line` holds the
    # same notes laid out in bars.
    line_events: list[tuple[float, float, int, bool]]
    # (position in written quarters, quarter notes per minute), in order.
    tempo: list[tuple[float, float]]
    # Where the file's first bar of CONTENT begins, in written quarters: past
    # zero only for a short pickup bar, whose notes sound at the bar's end.
    # The audio's time zero is here.
    start: float
    title: str = ""
    software: str = ""
    parts: list[str] = field(default_factory=list)
    part: str = ""
    swing_marking: bool = False
    grace_notes: int = 0
    # Bars whose content ran short of their time signature (padded, as the
    # reference readers pad them) or past it (lengthened: the content decides
    # where the next bar begins, as `mscz.parse_musicxml` lets it).
    short_bars: int = 0
    long_bars: int = 0


# ── reading MusicXML ─────────────────────────────────────────────────────────


def load_root(path: str | Path) -> ElementTree.Element:
    """The score element of a .musicxml/.xml file, or of a compressed .mxl."""
    path = Path(path)
    if path.suffix.lower() != ".mxl":
        return ElementTree.parse(path).getroot()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        target = None
        if "META-INF/container.xml" in names:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            for rootfile in container.iter():
                if rootfile.tag.endswith("rootfile") and rootfile.get("full-path"):
                    target = rootfile.get("full-path")
                    break
        if target is None:
            target = next(
                (
                    n
                    for n in names
                    if not n.startswith("META-INF/") and n.lower().endswith((".xml", ".musicxml"))
                ),
                None,
            )
        if target is None:
            raise ValueError(f"{path.name}: no score inside the .mxl")
        return ElementTree.fromstring(archive.read(target))


def _fraction(text: str | None, default: int = 0) -> Fraction:
    if text is None or not text.strip():
        return Fraction(default)
    return Fraction(text.strip())


def _beats(text: str) -> int:
    """A time signature's numerator; an additive one ("3+2") is its sum."""
    return sum(int(part) for part in re.findall(r"\d+", text)) or 4


def _signature_for(length: Fraction) -> tuple[int, int]:
    """A time signature whose bar is `length` quarters long: (9, 8) for 4.5."""
    quarters = length.limit_denominator(96)
    return quarters.numerator, 4 * quarters.denominator


def _float(text: str | None) -> float | None:
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _qpm(direction: ElementTree.Element) -> float | None:
    """A direction's tempo in quarter notes per minute, if it states one:
    `<sound tempo>` (always quarters) first, else the printed metronome."""
    sound = direction.find("sound")
    if sound is not None and _float(sound.get("tempo")):
        return _float(sound.get("tempo"))
    metronome = direction.find("direction-type/metronome")
    if metronome is None:
        return None
    unit = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}.get(
        (metronome.findtext("beat-unit") or "").strip()
    )
    number = re.search(r"\d+(\.\d+)?", metronome.findtext("per-minute") or "")
    if unit is None or number is None:
        return None
    if metronome.find("beat-unit-dot") is not None:
        unit *= 1.5
    return float(number.group()) * unit


def _choose_part(root: ElementTree.Element, part: int | str | None):
    names = {}
    for score_part in root.iter("score-part"):
        pid = score_part.get("id") or ""
        names[pid] = (score_part.findtext("part-name") or pid).strip() or pid
    parts = root.findall("part")
    if not parts:
        raise ValueError("no <part> in the score")
    labels = [names.get(p.get("id") or "", p.get("id") or "") for p in parts]
    if part is None:
        index = 0
    elif isinstance(part, int) or str(part).isdigit():
        index = int(part)
    else:
        wanted = str(part).lower()
        matches = [
            i
            for i, p in enumerate(parts)
            if (p.get("id") or "").lower() == wanted or labels[i].lower() == wanted
        ]
        if not matches:
            raise ValueError(f"no part {part!r}; the score has {labels}")
        index = matches[0]
    if not 0 <= index < len(parts):
        raise ValueError(f"part {index} out of range; the score has {labels}")
    return parts[index], labels, labels[index]


def read_musicxml(
    path: str | Path, part: int | str | None = None, graces: str = "keep"
) -> ExternalPage:
    """Read one part of a MusicXML file as a page and as its line.

    `part` is an index into the score's parts or a part id/name; the first
    part by default, as the reference reader takes the first. `graces` is
    the reference reader's grace rule (`GRACE_RULES`, `graces_for`).
    """
    from swingscribe.stages.export import fifths_for_transpose

    if graces not in GRACE_RULES:
        raise ValueError(f"graces must be one of {GRACE_RULES}, not {graces!r}")
    root = load_root(path)
    if root.tag == "score-timewise":
        raise ValueError("score-timewise MusicXML is not read; export score-partwise")
    chosen, labels, label = _choose_part(root, part)

    divisions = Fraction(1)
    signature = (4, 4)
    transpose = 0  # written = sounding + transpose, the Notation's convention
    key_written: int | None = None
    swing = False
    double_time = False
    grace_count = short_bars = long_bars = 0

    bars: list[NotatedBar] = []
    # (position, duration, sounding pitch, (staff, voice), tie start, tie stop, grace)
    raw: list[tuple[Fraction, Fraction, int, tuple[int, int], bool, bool, bool]] = []
    tempo: list[tuple[Fraction, float]] = []
    bar_start = Fraction(0)
    start = Fraction(0)
    previous_number = 0

    for index, measure in enumerate(chosen.findall("measure")):
        cursor = Fraction(0)
        furthest = Fraction(0)
        last_start = Fraction(0)
        written: list[NotatedNote] = []
        starts: list[Fraction] = []  # each written note's onset in the bar
        last_head: int | None = None
        local_raw: list[tuple] = []
        local_tempo: list[tuple[Fraction, float]] = []

        for element in measure:
            tag = element.tag
            if tag == "attributes":
                if element.findtext("divisions"):
                    divisions = _fraction(element.findtext("divisions"), 1) or Fraction(1)
                beats, beat_type = (
                    element.findtext("time/beats"),
                    element.findtext("time/beat-type"),
                )
                if beats and beat_type:
                    signature = (_beats(beats), int(beat_type))
                fifths = element.findtext("key/fifths")
                if fifths is not None and key_written is None:
                    key_written = int(float(fifths))
                shift = element.find("transpose")
                if shift is not None:
                    chromatic = float(shift.findtext("chromatic") or 0)
                    octaves = float(shift.findtext("octave-change") or 0)
                    transpose = -round(chromatic + 12 * octaves)
            elif tag == "backup":
                cursor -= _fraction(element.findtext("duration")) / divisions
            elif tag == "forward":
                cursor += _fraction(element.findtext("duration")) / divisions
                furthest = max(furthest, cursor)
            elif tag in ("direction", "sound"):
                qpm = _qpm(element) if tag == "direction" else _float(element.get("tempo"))
                if qpm and qpm > 0:
                    local_tempo.append((cursor, qpm))
                for words in element.iter("words"):
                    text = (words.text or "").strip()
                    if _SWING.search(text):
                        swing = True
                    if DOUBLE_TIME_WORDS in text.lower():
                        double_time = True
                if element.find(".//swing") is not None:
                    swing = True
            elif tag == "note":
                grace = element.find("grace") is not None
                chord = element.find("chord") is not None
                length = (
                    Fraction(0) if grace else _fraction(element.findtext("duration")) / divisions
                )
                if chord:
                    at = last_start
                else:
                    at = cursor
                    last_start = cursor
                    if not grace:
                        cursor += length
                furthest = max(furthest, at + length)
                if element.find("cue") is not None:
                    continue
                voice = int(element.findtext("voice") or 1)
                staff = int(element.findtext("staff") or 1)
                if staff > 1 and voice > 4 * (staff - 1):
                    voice -= 4 * (staff - 1)  # export.xml_voice, undone
                modification = element.find("time-modification")
                tuplet = None
                if modification is not None:
                    actual = int(modification.findtext("actual-notes") or 1)
                    normal = int(modification.findtext("normal-notes") or 1)
                    tuplet = (actual, normal) if actual != normal else None
                if element.find("rest") is not None:
                    if not chord and element.get("print-object", "yes") != "no":
                        written.append(
                            NotatedNote(
                                beat=0.0,
                                duration=float(length),
                                is_rest=True,
                                tuplet=tuplet,
                                voice=voice,
                                staff=staff,
                            )
                        )
                        starts.append(at)
                    continue
                pitch_element = element.find("pitch")
                if pitch_element is None:
                    continue  # unpitched percussion
                step = (pitch_element.findtext("step") or "C").strip()
                alter = round(float(pitch_element.findtext("alter") or 0))
                octave = int(pitch_element.findtext("octave") or 4)
                pitch = (octave + 1) * 12 + STEP_SEMITONE.get(step, 0) + alter - transpose
                ties = {t.get("type") for t in element.findall("tie")}
                ties |= {t.get("type") for t in element.findall("notations/tied")}
                tie_start = bool(ties & {"start", "continue"})
                tie_stop = bool(ties & {"stop", "continue"})
                local_raw.append((at, length, pitch, (staff, voice), tie_start, tie_stop, grace))
                if grace:
                    grace_count += 1
                    continue
                if chord and last_head is not None:
                    head = written[last_head]
                    written[last_head] = head.model_copy(update={"chord": [*head.chord, pitch]})
                    continue
                written.append(
                    NotatedNote(
                        beat=0.0,
                        duration=float(length),
                        pitch=pitch,
                        step=step,
                        alter=alter,
                        octave=octave,
                        tie_start=tie_start,
                        tie_stop=tie_stop,
                        tuplet=tuplet,
                        voice=voice,
                        staff=staff,
                    )
                )
                starts.append(at)
                last_head = len(written) - 1

        length_of_bar = Fraction(signature[0] * 4, signature[1])
        shift = Fraction(0)
        time_signature = signature
        if index == 0 and 0 < furthest < length_of_bar:
            shift = length_of_bar - furthest  # a pickup: its notes sound at the bar's end
        elif furthest < length_of_bar:
            short_bars += 1
        elif furthest > length_of_bar + _EPS:
            long_bars += 1
            length_of_bar = furthest
            time_signature = _signature_for(furthest)
        if index == 0:
            start = shift

        placed = [
            note.model_copy(update={"beat": float(at + shift)})
            for note, at in zip(written, starts, strict=True)
        ]
        raw.extend((bar_start + shift + at, *rest) for at, *rest in local_raw)
        tempo.extend((bar_start + shift + at, qpm) for at, qpm in local_tempo)

        number_text = (measure.get("number") or "").strip()
        number = int(number_text) if re.fullmatch(r"-?\d+", number_text) else previous_number + 1
        previous_number = number
        bars.append(NotatedBar(number=number, time_signature=time_signature, notes=placed))
        bar_start += length_of_bar

    line_events = _line(raw, graces)
    key = 0 if key_written is None else key_written - fifths_for_transpose(transpose)
    title = (root.findtext("work/work-title") or root.findtext("movement-title") or "").strip()
    notation = Notation(
        bars=bars,
        key_fifths=key,
        swing=swing,
        transpose=transpose,
        title=title or Path(path).stem,
        double_time=double_time,
        staves=max((n.staff for b in bars for n in b.notes), default=1),
    )
    return ExternalPage(
        notation=notation,
        line=_line_notation(notation, line_events),
        line_events=[(float(p), float(d), n, g) for p, d, n, g in line_events],
        tempo=[(float(at), qpm) for at, qpm in sorted(tempo, key=lambda t: t[0])],
        start=float(start),
        title=notation.title,
        software=(root.findtext("identification/encoding/software") or "").strip(),
        parts=labels,
        part=label,
        swing_marking=swing,
        grace_notes=grace_count,
        short_bars=short_bars,
        long_bars=long_bars,
    )


def _line(raw: list[tuple], graces: str = "keep") -> list[tuple[Fraction, Fraction, int, bool]]:
    """Tied notes merged within their voice, then the top note of every
    simultaneity. Grace notes are kept, each before the note it decorates
    (`graces="keep"`), or compete for the top of their position like any
    other note, with no length (`"compete"`)."""
    order = sorted(range(len(raw)), key=lambda i: (raw[i][0], not raw[i][6]))
    merged: list[list] = []
    pending: dict[tuple, int] = {}
    for i in order:
        at, length, pitch, voice, tie_start, tie_stop, grace = raw[i]
        key = (voice, pitch)
        if tie_stop and not grace and key in pending:
            held = pending.pop(key)
            merged[held][1] += length
            if tie_start:
                pending[key] = held
            continue
        merged.append([at, length, pitch, grace])
        if tie_start and not grace:
            pending[key] = len(merged) - 1
    tops: dict[Fraction, list] = {}
    decorations: list[list] = []
    for event in merged:
        if event[3] and graces == "keep":
            decorations.append(event)
        elif event[0] not in tops or event[2] > tops[event[0]][2]:
            tops[event[0]] = event
    line = sorted([*decorations, *tops.values()], key=lambda e: (e[0], not e[3]))
    return [(at, length, pitch, grace) for at, length, pitch, grace in line]


def _line_notation(page: Notation, events: list[tuple[Fraction, Fraction, int, bool]]) -> Notation:
    """The line in the page's bars, one voice, so `notation_notes` reads it back."""
    starts: list[Fraction] = []
    cursor = Fraction(0)
    for bar in page.bars:
        starts.append(cursor)
        cursor += Fraction(bar.time_signature[0] * 4, bar.time_signature[1])
    notes: list[list[NotatedNote]] = [[] for _ in page.bars]
    for at, length, pitch, _grace in events:
        index = max(0, bisect.bisect_right(starts, at) - 1)
        notes[index].append(
            NotatedNote(beat=float(at - starts[index]), duration=float(length), pitch=pitch)
        )
    return page.model_copy(
        update={
            "bars": [
                NotatedBar(number=bar.number, time_signature=bar.time_signature, notes=held)
                for bar, held in zip(page.bars, notes, strict=True)
            ],
            "staves": 1,
        }
    )


def page_seconds(page: ExternalPage) -> list[TimedNote] | None:
    """The line in seconds from the audio's start, at the page's own tempo
    marking; None when the file states no tempo (MusicXML's implied 120 is
    a default, not a claim about the recording).

    Time zero is the page's first bar line (`start`, past it for a short
    pickup); where that falls in the audio is unknown, and both timed
    scorers absorb a constant offset (score_tune's window shifts,
    `wjazz.fit_affine`'s offset search). A written note is timed as
    written: a swung eighth sits on the even eighth."""
    if not page.tempo:
        return None
    changes = sorted(page.tempo)

    def seconds(position: float) -> float:
        total, at, qpm = 0.0, 0.0, changes[0][1]
        for change_at, change_qpm in changes:
            if change_at >= position:
                break
            if change_at > at:
                total += (change_at - at) * 60.0 / qpm
                at = change_at
            qpm = change_qpm
        return total + (position - at) * 60.0 / qpm

    origin = seconds(page.start)
    return [
        TimedNote(
            onset=seconds(at) - origin,
            duration=seconds(at + length) - seconds(at),
            pitch=pitch,
        )
        for at, length, pitch, _grace in page.line_events
    ]


# ── MIDI ─────────────────────────────────────────────────────────────────────

DRUM_CHANNEL = 9  # General MIDI channel 10, counted from zero


def _vlq(data: bytes, at: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[at]
        at += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, at


def _vlq_bytes(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _smf(path: str | Path):
    """(division, [(tick, microseconds per quarter)], [(tick, order, on,
    channel + 16 * track, pitch, velocity)]) of a Standard MIDI File; `on`
    is -1 for a track's end."""
    data = Path(path).read_bytes()
    if data[:4] == b"RIFF":  # an RMID wrapper around a plain SMF
        found = data.find(b"MThd")
        if found < 0:
            raise ValueError(f"{Path(path).name}: no MThd inside the RIFF file")
        data = data[found:]
    if data[:4] != b"MThd":
        raise ValueError(f"{Path(path).name}: not a Standard MIDI File")
    header_length = struct.unpack(">I", data[4:8])[0]
    _format, tracks_declared, division = struct.unpack(">HHH", data[8:14])
    at = 8 + header_length
    tracks: list[bytes] = []
    while at + 8 <= len(data) and len(tracks) < tracks_declared:
        tag, size = data[at : at + 4], struct.unpack(">I", data[at + 4 : at + 8])[0]
        if tag == b"MTrk":
            tracks.append(data[at + 8 : at + 8 + size])
        at += 8 + size

    tempos: list[tuple[int, int]] = []  # (tick, microseconds per quarter)
    events: list[tuple[int, int, int, int, int, int]] = []  # tick, order, on, channel, pitch, vel
    order = 0
    for track_index, track in enumerate(tracks):
        tick, at, status = 0, 0, None
        while at < len(track):
            delta, at = _vlq(track, at)
            tick += delta
            byte = track[at]
            if byte == 0xFF:
                kind = track[at + 1]
                size, at = _vlq(track, at + 2)
                payload = track[at : at + size]
                at += size
                if kind == 0x51 and size == 3:
                    tempos.append((tick, int.from_bytes(payload, "big")))
                elif kind == 0x2F:
                    break
                continue
            if byte in (0xF0, 0xF7):
                size, at = _vlq(track, at + 1)
                at += size
                continue
            if byte & 0x80:
                status = byte
                at += 1
            elif status is None:
                raise ValueError(f"{Path(path).name}: running status with no status byte")
            kind, channel = status & 0xF0, status & 0x0F
            size = 1 if kind in (0xC0, 0xD0) else 2
            payload = track[at : at + size]
            at += size
            if kind in (0x80, 0x90):
                on = kind == 0x90 and payload[1] > 0
                events.append(
                    (tick, order, int(on), channel + 16 * track_index, payload[0], payload[1])
                )
                order += 1
        events.append((tick, order, -1, 16 * track_index, -1, 0))  # end of track
        order += 1
    return division, tempos, events


def read_midi(path: str | Path, drums: bool = False) -> list[TimedNote]:
    """Every note of a Standard MIDI File, in seconds, in onset order.

    Formats 0 and 1, running status, a tempo map gathered from every track,
    note-on at velocity 0 as a note-off, and SMPTE time division. A note
    still sounding at the end of its track ends there. Channel 10 (General
    MIDI drums) is left out unless `drums`.
    """
    division, tempos, events = _smf(path)
    if division & 0x8000:
        frames = 256 - (division >> 8)
        per_tick = 1.0 / (frames * (division & 0xFF))

        def seconds(tick: int) -> float:
            return tick * per_tick
    else:
        changes = sorted(tempos)
        marks: list[tuple[int, float, int]] = [(0, 0.0, 500_000)]  # tick, seconds, tempo
        for change_tick, micros in changes:
            last_tick, last_seconds, last_tempo = marks[-1]
            elapsed = last_seconds + (change_tick - last_tick) * last_tempo / 1e6 / division
            if change_tick == last_tick:
                marks[-1] = (change_tick, last_seconds, micros)
            else:
                marks.append((change_tick, elapsed, micros))
        ticks = [m[0] for m in marks]

        def seconds(tick: int) -> float:
            mark_tick, mark_seconds, micros = marks[bisect.bisect_right(ticks, tick) - 1]
            return mark_seconds + (tick - mark_tick) * micros / 1e6 / division

    sounding: dict[tuple[int, int], list[tuple[int, int]]] = {}
    notes: list[TimedNote] = []
    # Offs before ons at one tick, so a note struck again at the instant it
    # ends pairs its own note-off and not the new one.
    for tick, _order, on, channel, pitch, velocity in sorted(
        events, key=lambda e: (e[0], e[2] != 0, e[1])
    ):
        if on == -1:
            track = channel // 16
            for key in [k for k in sounding if k[0] // 16 == track]:
                for start_tick, start_velocity in sounding.pop(key):
                    notes.append(_timed(seconds, start_tick, tick, key, start_velocity))
            continue
        key = (channel, pitch)
        if on:
            sounding.setdefault(key, []).append((tick, velocity))
        elif sounding.get(key):
            start_tick, start_velocity = sounding[key].pop(0)
            notes.append(_timed(seconds, start_tick, tick, key, start_velocity))
    kept = [n for n in notes if drums or n.channel != DRUM_CHANNEL]
    return sorted(kept, key=lambda n: (n.onset, n.pitch))


# A 24th of a quarter holds every written value a page uses down to a
# thirty-second, and the eighth and sixteenth triplets.
GRID_PER_QUARTER = 24


# A MIDI file with at least this share of its onsets on that grid was
# written from a page -- when the share is also far past what its clock
# gives a performance by chance (`midi_timing`).
QUANTIZED_SHARE = 0.9
# ... "far past": a binomial tail below this at the chance level.
QUANTIZED_TAIL = 1e-3

PERFORMED = "performed"
QUANTIZED = "quantized"
UNKNOWN = "unknown"


def _on_grid(tick: int, division: int) -> bool:
    """Within half a tick of a 24th of the quarter: exactly on it when 24
    divides the division, else on the tick a writer would round it to."""
    residue = (GRID_PER_QUARTER * tick) % division
    return 2 * min(residue, division - residue) <= GRID_PER_QUARTER


def _grid_chance(division: int) -> float:
    """The share of a quarter's ticks `_on_grid` accepts: what uniformly
    placed (performed) onsets reach by chance."""
    return sum(_on_grid(t, division) for t in range(division)) / division


def _tail(n: int, k: int, p: float) -> float:
    """P(at least k of n) for a binomial(n, p), in log space for large n."""
    if k <= 0 or p >= 1.0:
        return 1.0
    if p <= 0.0:
        return 0.0
    total = 0.0
    for i in range(k, n + 1):
        log_term = (
            math.lgamma(n + 1)
            - math.lgamma(i + 1)
            - math.lgamma(n - i + 1)
            + i * math.log(p)
            + (n - i) * math.log1p(-p)
        )
        total += math.exp(log_term)
    return min(1.0, total)


@dataclass(frozen=True)
class MidiTiming:
    """Whether a MIDI file's onsets are a performance (`midi_timing`)."""

    share: float | None  # onsets on a 24th of the file's quarter
    chance: float | None  # the share performed onsets reach by chance
    n: int
    verdict: str  # PERFORMED, QUANTIZED or UNKNOWN
    why: str = ""


def midi_grid_share(path: str | Path, drums: bool = False) -> tuple[float, float] | None:
    """(share, chance): the share of a MIDI file's note onsets on a 24th of
    its own quarter note (to the nearest tick), and the share performed
    onsets would reach by chance. None for SMPTE time or no notes."""
    division, _tempos, events = _smf(path)
    onsets = [e[0] for e in events if e[2] == 1 and (drums or e[3] % 16 != DRUM_CHANNEL)]
    if division & 0x8000 or not division or not onsets:
        return None
    share = sum(_on_grid(tick, division) for tick in onsets) / len(onsets)
    return share, _grid_chance(division)


def midi_timing(path: str | Path, drums: bool = False) -> MidiTiming:
    """Is this MIDI file a performance, a page in disguise, or can't it say?

    QUANTIZED: at least 90% of the onsets on a 24th of the quarter AND that
    many is beyond chance for the file's clock (binomial tail under 1e-3) --
    a notation program's MIDI, or AnthemScore's with "musical (rounded)
    timing" on. PERFORMED: under 90%. UNKNOWN: the clock cannot tell --
    SMPTE time, no notes, or a division so coarse (24 or 48 ticks a
    quarter) that a performance lands on the grid as often as a page does.

    Fails CLOSED: only PERFORMED is paired on note F1 (scripts/
    head_to_head.py). A quantized MIDI is a page in disguise, and timed off
    a page note F1 measures the writing -- 0.10-0.19 of WJazzD note F1 on
    our own pages (docs/head-to-head.md section 8).
    """
    division, _tempos, events = _smf(path)
    onsets = [e[0] for e in events if e[2] == 1 and (drums or e[3] % 16 != DRUM_CHANNEL)]
    if not onsets:
        return MidiTiming(None, None, 0, UNKNOWN, "no notes")
    if division & 0x8000 or not division:
        return MidiTiming(None, None, len(onsets), UNKNOWN, "SMPTE time: no quarter note to read")
    hits = sum(_on_grid(tick, division) for tick in onsets)
    share, chance = hits / len(onsets), _grid_chance(division)
    if share < QUANTIZED_SHARE:
        return MidiTiming(share, chance, len(onsets), PERFORMED)
    if _tail(len(onsets), hits, chance) < QUANTIZED_TAIL:
        return MidiTiming(share, chance, len(onsets), QUANTIZED)
    return MidiTiming(
        share,
        chance,
        len(onsets),
        UNKNOWN,
        f"{division} ticks a quarter puts a performance on the grid {chance:.0%} of the time",
    )


def add_tempo(xml: str, qpm: float) -> str:
    """A MusicXML page with a tempo marking (`<metronome>` and `<sound
    tempo>`, quarters per minute) at the start of its first bar: what a tool
    that detects one tempo prints. The notes, and so every page measure,
    are untouched."""
    marking = (
        '<direction placement="above"><direction-type><metronome>'
        f"<beat-unit>quarter</beat-unit><per-minute>{qpm:.0f}</per-minute>"
        f'</metronome></direction-type><sound tempo="{qpm:.3f}"/></direction>'
    )
    head, found, tail = xml.partition("</attributes>")
    if not found:
        raise ValueError("no <attributes> in the first bar to put a tempo after")
    return head + found + marking + tail


def _timed(
    seconds, start_tick: int, end_tick: int, key: tuple[int, int], velocity: int
) -> TimedNote:
    onset = seconds(start_tick)
    return TimedNote(
        onset=onset,
        duration=seconds(end_tick) - onset,
        pitch=key[1],
        velocity=velocity,
        channel=key[0] % 16,
    )


# Ticks per quarter at 120 bpm: 20.8 microseconds a tick, so an onset
# written and read back moves by at most 10.4. Far inside mir_eval's 50 ms,
# but NOT nothing: a WJazzD fit (`wjazz.fit_affine`) is a search on a 2 ms
# offset grid, and rounding Yesterdays' onsets to 52 us ticks moved its
# note F1 by 0.002-0.006 while 1, 20.8, 50 and 100 us all reproduced the
# pin (docs/head-to-head.md section 7). A multiple of 24, so a
# 24th of a quarter is a whole tick (`midi_timing`): our onsets sit on a 10 ms frame
# grid, and 1 in 25 of those lands on its 24th of a quarter (20.8 ms).
WRITE_DIVISION = 24_000
WRITE_TEMPO_US = 500_000


def write_midi(notes: list[TimedNote], path: str | Path) -> None:
    """A format-0 Standard MIDI File of `notes` (seconds from zero)."""
    per_tick = WRITE_TEMPO_US / 1e6 / WRITE_DIVISION
    events: list[tuple[int, int, bytes]] = []
    for note in notes:
        if note.onset < 0:
            raise ValueError(f"a note at {note.onset:.3f} s is before the file starts")
        on = round(note.onset / per_tick)
        # A note of no length still needs its note-off AFTER its note-on.
        off = max(on + 1, round((note.onset + max(note.duration, 0.0)) / per_tick))
        channel = note.channel & 0x0F
        velocity = min(127, max(1, int(note.velocity)))
        events.append((on, 1, bytes([0x90 | channel, note.pitch & 0x7F, velocity])))
        events.append((off, 0, bytes([0x80 | channel, note.pitch & 0x7F, 0])))
    body = bytearray(b"\x00\xff\x51\x03" + WRITE_TEMPO_US.to_bytes(3, "big"))
    tick = 0
    for at, _kind, message in sorted(events, key=lambda e: (e[0], e[1])):
        body += _vlq_bytes(at - tick) + message
        tick = at
    body += b"\x00\xff\x2f\x00"
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, WRITE_DIVISION)
    Path(path).write_bytes(header + b"MTrk" + struct.pack(">I", len(body)) + bytes(body))


# Notes whose onsets fall within this of a cluster's first are one
# simultaneity -- the 50 ms `notation.fold_texture` folds a piano texture at.
LINE_ONSET_S = 0.05


def top_line(notes: list[TimedNote], window: float = LINE_ONSET_S) -> list[TimedNote]:
    """The highest note of every cluster of onsets `window` apart: a timed
    list reduced to a line by the page's rule. A SENSITIVITY reading only
    (scripts/head_to_head.py --top-line): the timed measures score a tool's
    notes as delivered, ours included, and on our own line this folds the
    few notes a fast figure puts inside 50 ms of each other."""
    out: list[TimedNote] = []
    first = -math.inf
    for note in sorted(notes, key=lambda n: (n.onset, -n.pitch)):
        if out and note.onset - first <= window:
            if note.pitch > out[-1].pitch:
                out[-1] = note
            continue
        out.append(note)
        first = note.onset
    return out


def polyphony(notes: list[TimedNote], window: float = LINE_ONSET_S) -> float:
    """The share of notes that start within `window` of a note still
    sounding: 0 for a line, most of a chordal texture. Printed beside a
    tool's timed scores so a low precision reads as comping, not noise."""
    ordered = sorted(notes, key=lambda n: n.onset)
    stacked = sum(
        1
        for previous, note in zip(ordered, ordered[1:], strict=False)
        if note.onset - previous.onset <= window and previous.onset + previous.duration > note.onset
    )
    return stacked / len(ordered) if ordered else 0.0


# ── cutting a reference to an excerpt ────────────────────────────────────────


def crop_score(score, keep: list[int]):
    """(the part of `score` an excerpt covers, where its first bar began).

    `keep` indexes `score.melody`: the reference notes the excerpt's audio
    holds, decided by the caller from where they were placed in time. The
    cropped score starts at the bar line before the first of them, so its
    positions keep their place in the bar (`score_bars` reads position
    modulo the bar) and its bar 1 is that bar; `bars` counts the bars the
    kept notes reach into. Chord tones between the first and last kept
    note stay in `notes`. One metre throughout, as the MuseScore reader's
    `beats_per_bar` already assumes.
    """
    from swingscribe.mscz import Score, ScoreNote

    kept = [score.melody[i] for i in sorted(set(keep))]
    if not kept:
        return Score(score.title, [], [], 0, score.beats_per_bar, score.key_fifths), 0.0
    bar = float(score.beats_per_bar)
    first_bar = math.floor(kept[0].position / bar + 1e-9)
    origin = first_bar * bar
    end = max(n.position + n.duration for n in kept)
    bars = max(1, math.ceil((end - origin) / bar - 1e-9))

    def moved(note):
        return ScoreNote(
            position=note.position - origin,
            duration=note.duration,
            pitch=note.pitch,
            bar=note.bar - first_bar,
        )

    low, high = kept[0].position - 1e-9, kept[-1].position + 1e-9
    notes = [moved(n) for n in score.notes if low <= n.position <= high]
    return Score(score.title, notes, [moved(n) for n in kept], bars, bar, score.key_fifths), origin


@dataclass
class Excerpt:
    """A reference cut to what an excerpt's audio holds (`excerpt_reference`)."""

    score: object  # mscz.Score, the cut
    region: tuple[float, float]  # seconds its bars cover, placed on our notes
    keep: list[int]  # indices into the uncut `melody`
    anchors: int  # matched notes the placement stood on


def excerpt_reference(
    reference, onsets: list[float], pitches: list[int], window: tuple[float, float]
) -> Excerpt:
    """The part of a notated reference an excerpt's audio holds.

    `onsets` and `pitches` are OUR transcription of the whole span, in
    onset order; `window` is the excerpt in the same seconds. The reference
    is aligned to our notes with no timing (`alignment.measured_transposition`,
    the scorers' own call), every truly matched note anchors its notated
    position to our onset, and every reference note is placed in time on
    those anchors (`benchmark.place_on_anchors`, 19 ms median leave-one-out
    on the Omnibook). The notes placed inside the window are kept
    (`crop_score`: bar phase kept, bar 1 the bar the first of them is in);
    `region` is where the cut's first and last bar lines fall, which the
    MuseScore set's note F1 reads its tempo from.

    Decided from our notes, once, and the same cut for every tool: it
    decides which reference notes the audio holds, never what any tool is
    scored as having heard. A note at either edge can go the wrong way --
    the same way for everyone.
    """
    from swingscribe.alignment import measured_transposition
    from swingscribe.benchmark import place_on_anchors

    if len(onsets) != len(pitches):
        raise ValueError("one onset per pitch")
    offset, aligned = measured_transposition(reference.pitches, list(pitches))
    anchors = [
        (reference.melody[ri].position, onsets[ei])
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and reference.melody[ri].pitch == pitches[ei] + offset
    ]
    positions = [n.position for n in reference.melody]
    placed = place_on_anchors(positions, [n.duration for n in reference.melody], anchors)
    low, high = window
    keep = [i for i, t in enumerate(placed["onsets"]) if low <= t < high]
    cropped, origin = crop_score(reference, keep)
    ends = place_on_anchors(
        [origin, origin + cropped.bars * cropped.beats_per_bar], [0.0, 0.0], anchors
    )["onsets"]
    return Excerpt(cropped, (ends[0], ends[1]), keep, len(anchors))


def wjazz_excerpt(
    ref_on, ref_p, positions, anchor_onsets, offset: float, rate: float, window
) -> tuple[list[float], list[int], list]:
    """(onsets, pitches, positions) of a WJazzD solo inside an excerpt.

    `ref_on`/`ref_p` are the annotation's onsets (its own seconds) and
    pitches; `positions` its notated beats (`wjazz.notated_beats`), one per
    `anchor_onsets` (`wjazz.bar_anchors`: the annotated onset each position
    belongs to). `offset` and `rate` are OUR pinned fit of the solo
    (`score_wjazz.candidates`), which places the annotation in the track's
    time: `onset * rate + offset`. A note is in the excerpt when it is
    placed inside the window; the same cut for every tool."""
    low, high = window
    inside = [low <= on * rate + offset < high for on in ref_on]
    onsets = [float(on) for on, k in zip(ref_on, inside, strict=True) if k]
    pitches = [int(p) for p, k in zip(ref_p, inside, strict=True) if k]
    if len(positions) != len(anchor_onsets):
        raise ValueError("one anchor onset per notated position")
    kept = [
        p
        for p, onset in zip(positions, anchor_onsets, strict=True)
        if low <= onset * rate + offset < high
    ]
    return onsets, pitches, kept
