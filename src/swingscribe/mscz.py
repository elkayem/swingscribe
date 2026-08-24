"""Read a MuseScore file (.mscz / .mscx) as ground-truth notes.

The benchmark folder holds hand-made transcriptions of real solos. They are
the target output of the whole pipeline, so being able to read them turns
"does this sound right?" into a measurement.

What comes out is deliberately NOT seconds. A notated score has no
timestamps — it has bars, beats and note values. Converting to seconds needs
a tempo map, and deriving one from our own beat tracker would let beat-tracking
errors contaminate the score. So this module reports musical position, and
`to_note_events` does the conversion explicitly when a caller supplies the
tempo, keeping that assumption visible instead of buried.

NOTHING parsed here may be committed: these are derivative works of
commercial recordings (plan §12). Only aggregate metrics.
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from swingscribe.model import NoteEvent

# Note value → length in quarter notes.
DURATION_BEATS = {
    "long": 16.0,
    "breve": 8.0,
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
    "128th": 0.03125,
}


@dataclass(frozen=True)
class ScoreNote:
    """One notated note. Positions are in quarter notes from the start."""

    position: float  # quarter notes since bar 1 beat 1
    duration: float  # quarter notes
    pitch: int  # MIDI note number
    bar: int  # 1-based, for reporting


@dataclass(frozen=True)
class Score:
    title: str
    notes: list[ScoreNote]
    bars: int
    beats_per_bar: float
    key_fifths: int  # -1 = one flat, as MuseScore's concertKey

    @property
    def pitches(self) -> list[int]:
        return [n.pitch for n in self.notes]


def read_mscx_xml(path: str | Path) -> str:
    """The score XML, from either a zipped .mscz or a bare .mscx."""
    p = Path(path)
    if p.suffix.lower() == ".mscx":
        return p.read_text(encoding="utf-8")
    with zipfile.ZipFile(p) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".mscx")]
        if not names:
            raise ValueError(f"no .mscx inside {p.name}")
        # A multi-score .mscz is possible in theory; take the first, which is
        # the primary score MuseScore itself opens.
        return archive.read(names[0]).decode("utf-8")


def _duration_of(element: ElementTree.Element, beats_per_bar: float) -> float:
    """Quarter-note length of a Chord or Rest, honouring dots."""
    name = element.findtext("durationType", "")
    if name == "measure":
        return beats_per_bar
    beats = DURATION_BEATS.get(name)
    if beats is None:
        return 0.0
    dots = int(element.findtext("dots", "0") or 0)
    # Each dot adds half of what came before: 1.5x, 1.75x, ...
    return beats * (2.0 - 0.5**dots)


def parse(path: str | Path) -> Score:
    """Parse a MuseScore file into monophonic-ordered ScoreNotes.

    Handles dotted values, tuplets, and ties (a tied pair becomes one longer
    note, which is what a transcription means and what we would want to
    reproduce). Chords with several notes contribute their top note only —
    every benchmark solo is a single line, and the top note is the melody.
    """
    root = ElementTree.fromstring(read_mscx_xml(path))
    score = root.find("Score")
    if score is None:
        raise ValueError("not a MuseScore score")

    title = ""
    for tag in score.findall("metaTag"):
        if tag.get("name") == "workTitle" and (tag.text or "").strip():
            title = tag.text.strip()

    staff = score.find("Staff")
    if staff is None:
        raise ValueError("score has no Staff")

    beats_per_bar = 4.0
    key_fifths = 0
    notes: list[ScoreNote] = []
    position = 0.0
    bar_number = 0
    # A tie makes the NEXT note at the same pitch a continuation, not a new
    # note; hold the index of the note waiting to be extended.
    pending_tie: int | None = None

    for measure in staff.findall("Measure"):
        bar_number += 1
        bar_start = position
        for voice in measure.findall("voice") or [measure]:
            cursor = bar_start
            tuplet_ratio = 1.0
            for element in voice:
                if element.tag == "TimeSig":
                    numerator = float(element.findtext("sigN", "4"))
                    denominator = float(element.findtext("sigD", "4"))
                    beats_per_bar = numerator * (4.0 / denominator)
                elif element.tag == "KeySig":
                    key_fifths = int(element.findtext("concertKey", "0") or 0)
                elif element.tag == "Tuplet":
                    actual = float(element.findtext("actualNotes", "1") or 1)
                    normal = float(element.findtext("normalNotes", "1") or 1)
                    tuplet_ratio = normal / actual if actual else 1.0
                elif element.tag == "endTuplet":
                    tuplet_ratio = 1.0
                elif element.tag == "Rest":
                    cursor += _duration_of(element, beats_per_bar) * tuplet_ratio
                    pending_tie = None  # a rest breaks any tie
                elif element.tag == "Chord":
                    duration = _duration_of(element, beats_per_bar) * tuplet_ratio
                    pitches = [
                        int(n.findtext("pitch", "0"))
                        for n in element.findall("Note")
                        if n.findtext("pitch")
                    ]
                    if pitches:
                        pitch = max(pitches)  # the melody is the top voice
                        if pending_tie is not None and notes[pending_tie].pitch == pitch:
                            held = notes[pending_tie]
                            notes[pending_tie] = ScoreNote(
                                position=held.position,
                                duration=held.duration + duration,
                                pitch=held.pitch,
                                bar=held.bar,
                            )
                        else:
                            notes.append(
                                ScoreNote(
                                    position=cursor,
                                    duration=duration,
                                    pitch=pitch,
                                    bar=bar_number,
                                )
                            )
                        ties = [n for n in element.findall("Note") if n.find(".//Tie") is not None]
                        pending_tie = (
                            (len(notes) - 1)
                            if ties
                            else (pending_tie if pending_tie is not None and not pitches else None)
                        )
                        if not ties:
                            pending_tie = None
                    cursor += duration
            position = max(position, cursor)
        # Bars whose contents came up short (pickup bars, or voices we skipped)
        # still advance by a full bar, so bar numbering stays aligned.
        position = max(position, bar_start + beats_per_bar)

    return Score(
        title=title,
        notes=notes,
        bars=bar_number,
        beats_per_bar=beats_per_bar,
        key_fifths=key_fifths,
    )


def to_note_events(
    score: Score, bpm: float, start_seconds: float = 0.0, source: str = "mscz"
) -> list[NoteEvent]:
    """Musical position → seconds at a constant tempo.

    Constant tempo is an explicit simplification: real solos drift, so this is
    only fair for scoring when the caller knows the drift is small, or supplies
    a span short enough that it does not matter. Anything better needs a real
    tempo map from the beat grid.
    """
    seconds_per_beat = 60.0 / bpm
    return [
        NoteEvent(
            onset=start_seconds + n.position * seconds_per_beat,
            duration=n.duration * seconds_per_beat,
            pitch=n.pitch,
            confidence=1.0,
            source=source,
        )
        for n in score.notes
    ]
