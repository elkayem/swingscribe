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


# Ottava (8va / 8vb) shift in semitones, by MuseScore subtype.
#
# MuseScore 4 stores the WRITTEN pitch under an ottava, not the sounding one,
# and carries the octave in a separate <Spanner type="Ottava">. MEASURED, not
# assumed: aligning the Peterson solo against our transcription of the same
# recording matches 10 of the 11 notes under its 8vb once the shift is applied
# and 1 of 11 without it. Ignoring the spanner is a GROUND TRUTH error — it
# charges the transcriber for an octave the score never claimed.
#
# 58 notes across 5 of the 10 hand transcriptions sit under one; on the Wynton
# Kelly and Carl Perkins solos that is ~10% of the line. Writing a high passage
# 8va to keep it on the staff is ordinary notation, not a mistake.
OTTAVA_SHIFT = {"8va": 12, "8vb": -12, "15ma": 24, "15mb": -24, "22ma": 36, "22mb": -36}


@dataclass(frozen=True)
class ScoreNote:
    """One notated note. Positions are in quarter notes from the start."""

    position: float  # quarter notes since bar 1 beat 1
    duration: float  # quarter notes
    pitch: int  # MIDI note number
    bar: int  # 1-based, for reporting


@dataclass(frozen=True)
class Score:
    """A parsed hand transcription, in two views of the same music.

    `melody` is the single line — the top note of every chord. It is what the
    time-free pitch aligner needs (two notes at one position have no order,
    and a monophonic transcriber can only ever produce one of them), and it is
    what every measure through M6 is scored against.

    `notes` is everything, chord tones included. Nothing scores against it yet:
    it exists because M7b is about the notes a monophonic path structurally
    cannot reach, and a benchmark that silently dropped them would report a
    polyphonic transcriber as no better than the one it replaced.
    """

    title: str
    notes: list[ScoreNote]  # every notated note, chord tones included
    melody: list[ScoreNote]  # top note of each chord — the single line
    bars: int
    beats_per_bar: float
    key_fifths: int  # -1 = one flat, as MuseScore's concertKey

    @property
    def pitches(self) -> list[int]:
        """The melody's pitches — the sequence the aligner matches on."""
        return [n.pitch for n in self.melody]

    @property
    def chord_tones(self) -> list[ScoreNote]:
        """Everything `melody` leaves out."""
        top = {(round(n.position, 6), n.pitch) for n in self.melody}
        return [n for n in self.notes if (round(n.position, 6), n.pitch) not in top]


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
    reproduce).

    A chord contributes its top note to `melody` and ALL of its notes to
    `notes`. The top note is the melody by convention and by measurement —
    every solo here is a single line except the Peterson, where 11% of events
    are dyads he plays as octaves and locked-hands doubling under the tune.
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
    # Chord tones below the top note, collected in parallel and merged in at
    # the end. Kept separate through the walk so the melody logic below — ties
    # included — stays exactly the single-line logic it has always been, and
    # adding polyphony cannot move a monophonic number.
    lower: list[ScoreNote] = []
    position = 0.0
    bar_number = 0
    # A tie makes the NEXT note at the same pitch a continuation, not a new
    # note; hold the index of the note waiting to be extended.
    pending_tie: int | None = None
    # Semitones to add to every note until the ottava closes. The start and end
    # markers arrive inline in voice order, so a running offset gives exactly
    # the right half-open span: a note at the end marker's own tick is already
    # outside, which is what the spanner's declared length says too.
    ottava = 0

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
                elif element.tag == "Spanner" and element.get("type") == "Ottava":
                    # The start marker carries the <Ottava>; the end marker is
                    # the same tag with only a <prev> back-reference.
                    spanner = element.find("Ottava")
                    if spanner is not None:
                        ottava = OTTAVA_SHIFT.get(spanner.findtext("subtype", ""), 0)
                    else:
                        ottava = 0
                elif element.tag == "Rest":
                    cursor += _duration_of(element, beats_per_bar) * tuplet_ratio
                    pending_tie = None  # a rest breaks any tie
                elif element.tag == "Chord":
                    duration = _duration_of(element, beats_per_bar) * tuplet_ratio
                    pitches = [
                        int(n.findtext("pitch", "0")) + ottava
                        for n in element.findall("Note")
                        if n.findtext("pitch")
                    ]
                    if pitches:
                        pitch = max(pitches)  # the melody is the top voice
                        for other in sorted(pitches):
                            if other != pitch:
                                lower.append(
                                    ScoreNote(
                                        position=cursor,
                                        duration=duration,
                                        pitch=other,
                                        bar=bar_number,
                                    )
                                )
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
        notes=sorted(notes + lower, key=lambda n: (n.position, n.pitch)),
        melody=notes,
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
        for n in score.melody
    ]
