"""Score a two-horn head's page against a human's two-voice page.

The benchmark's notation scorers (`benchmark.score_against_notation`) read ONE
line: a reference's top note per chord, aligned time-free. A head written for
two horns is two lines on one staff -- voice 1 the upper horn, voice 2 the
lower -- and the listener's question is whether each is written the way they
wrote it. Both pages count bars from the head's first bar, so the comparison
is POSITIONAL: each voice's notes as (position in quarter notes from bar 1,
pitch), matched by mir_eval's note matcher with the position standing in for
time (a quarter note is one "second"). mir_eval stays the scorer; this module
only reads the two pages and lays them on one axis.

Two tolerances, two questions:

- WRITTEN (`EXACT`, a 48th of a quarter): the note is on the same spot of the
  page with the same pitch -- what the listener would not have to touch.
- HEARD (`NEAR`, an eighth): the right pitch within an eighth -- a note we
  heard right and wrote in a different place.

A unison the page writes once in voice 1 can sit in either voice of the
reference, so `both` scores the two voices pooled as one set as well.

Reads `.mscz`/`.mscx` (MuseScore 4: `<voice>` per measure, ties as
`Spanner type="Tie"`, gaps as `<location>`) and the MusicXML our Export
writes (`<voice>` 1/2 on staff 1, `<backup>`, `<tie>`, `<time-modification>`,
`<staccato/>`). Grace notes take no time and are counted apart, never scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

EXACT = 1 / 48
NEAR = 0.5


@dataclass(frozen=True)
class VoiceNote:
    position: float  # quarter notes from bar 1, beat 1
    duration: float  # quarter notes, ties joined
    pitch: int
    bar: int  # 1-based
    staccato: bool = False
    tuplet: bool = False


@dataclass
class TwoVoices:
    upper: list[VoiceNote] = field(default_factory=list)
    lower: list[VoiceNote] = field(default_factory=list)
    graces: int = 0
    bars: int = 0
    beats_per_bar: float = 4.0


def _join_ties(notes: list[tuple[VoiceNote, bool]]) -> list[VoiceNote]:
    """(note, ties-into-next) in order -> notes with tied pairs joined."""
    out: list[VoiceNote] = []
    pending = False
    for note, tied in notes:
        if pending and out and out[-1].pitch == note.pitch:
            held = out[-1]
            out[-1] = VoiceNote(
                held.position,
                held.duration + note.duration,
                held.pitch,
                held.bar,
                held.staccato or note.staccato,
                held.tuplet,
            )
        else:
            out.append(note)
        pending = tied
    return out


def read_mscz(path: str | Path) -> TwoVoices:
    from swingscribe import mscz

    root = ElementTree.fromstring(mscz.read_mscx_xml(path))
    score = root.find("Score")
    staff = score.find("Staff") if score is not None else None
    if staff is None:
        raise ValueError(f"{path}: no staff")
    beats_per_bar = 4.0
    lines: dict[int, list[tuple[VoiceNote, bool]]] = {0: [], 1: []}
    graces = 0
    position = 0.0
    bars = 0
    for measure in staff.findall("Measure"):
        bars += 1
        bar_start = position
        for index, voice in enumerate(measure.findall("voice")):
            cursor = bar_start
            ratio = 1.0
            for element in voice:
                tag = element.tag
                if tag == "TimeSig":
                    n = float(element.findtext("sigN", "4"))
                    d = float(element.findtext("sigD", "4"))
                    beats_per_bar = n * 4.0 / d
                elif tag == "Tuplet":
                    actual = float(element.findtext("actualNotes", "1") or 1)
                    normal = float(element.findtext("normalNotes", "1") or 1)
                    ratio = normal / actual if actual else 1.0
                elif tag == "endTuplet":
                    ratio = 1.0
                elif tag == "location":
                    whole = Fraction(element.findtext("fractions", "0") or "0")
                    cursor += float(whole) * 4.0
                elif tag == "Rest":
                    cursor += mscz._duration_of(element, beats_per_bar) * ratio
                elif tag == "Chord":
                    if mscz._is_grace(element):
                        graces += 1
                        continue
                    length = mscz._duration_of(element, beats_per_bar) * ratio
                    staccato = any(
                        "Staccato" in (a.findtext("subtype") or "")
                        for a in element.findall("Articulation")
                    )
                    for note in element.findall("Note"):
                        if not note.findtext("pitch"):
                            continue
                        tied = any(
                            s.get("type") == "Tie" and s.find("next") is not None
                            for s in note.findall("Spanner")
                        )
                        lines[min(index, 1)].append(
                            (
                                VoiceNote(
                                    cursor,
                                    length,
                                    int(note.findtext("pitch")),
                                    bars,
                                    staccato,
                                    ratio != 1.0,
                                ),
                                tied,
                            )
                        )
                    cursor += length
        position = max(position + beats_per_bar, bar_start + beats_per_bar)
    return TwoVoices(_join_ties(lines[0]), _join_ties(lines[1]), graces, bars, beats_per_bar)


_STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def read_musicxml(path: str | Path) -> TwoVoices:
    """Our Export's single-part page: voice 1 the upper horn, voice 2 the lower."""
    return _two_voices(ElementTree.parse(path).getroot(), str(path))


def read_musicxml_text(text: str) -> TwoVoices:
    """The same, from the MusicXML string Export would write (`to_musicxml`):
    the harness scores a page it built without writing it anywhere."""
    return _two_voices(ElementTree.fromstring(text), "page")


def _two_voices(root, name: str) -> TwoVoices:
    part = root.find("part")
    if part is None:
        raise ValueError(f"{name}: no part")
    divisions = 1.0
    beats_per_bar = 4.0
    lines: dict[int, list[tuple[VoiceNote, bool]]] = {0: [], 1: []}
    graces = 0
    position = 0.0
    bars = 0
    for measure in part.findall("measure"):
        bars += 1
        bar_start = position
        cursor = bar_start
        last_start = cursor
        length_bar = beats_per_bar
        for element in measure:
            if element.tag == "attributes":
                divisions = float(element.findtext("divisions") or divisions)
                beats = element.find("time")
                if beats is not None:
                    beats_per_bar = (
                        float(beats.findtext("beats")) * 4.0 / float(beats.findtext("beat-type"))
                    )
                    length_bar = beats_per_bar
            elif element.tag == "backup":
                cursor -= float(element.findtext("duration")) / divisions
            elif element.tag == "forward":
                cursor += float(element.findtext("duration")) / divisions
            elif element.tag == "note":
                if element.find("grace") is not None:
                    graces += 1
                    continue
                length = float(element.findtext("duration") or 0) / divisions
                chord = element.find("chord") is not None
                start = last_start if chord else cursor
                if element.find("rest") is None:
                    pitch_el = element.find("pitch")
                    midi = (
                        12 * (int(pitch_el.findtext("octave")) + 1)
                        + _STEP[pitch_el.findtext("step")]
                        + int(float(pitch_el.findtext("alter") or 0))
                    )
                    voice = int(element.findtext("voice") or 1)
                    tied = any(t.get("type") == "start" for t in element.findall("tie"))
                    staccato = element.find(".//staccato") is not None
                    tuplet = element.find("time-modification") is not None
                    lines[0 if voice == 1 else 1].append(
                        (VoiceNote(start, length, midi, bars, staccato, tuplet), tied)
                    )
                if not chord:
                    last_start = cursor
                    cursor += length
        position = bar_start + length_bar
    # Our transposing exports write sounding pitch only for a concert page;
    # the comparison is for a concert page (the head's default).
    return TwoVoices(_join_ties(lines[0]), _join_ties(lines[1]), graces, bars, beats_per_bar)


def read_page(path: str | Path) -> TwoVoices:
    suffix = Path(path).suffix.lower()
    return read_mscz(path) if suffix in (".mscz", ".mscx") else read_musicxml(path)


def _arrays(notes: list[VoiceNote], shift: float = 0.0):
    import numpy as np

    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    intervals = np.array(
        [[n.position + shift, n.position + shift + max(n.duration, 1e-3)] for n in notes]
    )
    hz = np.array([440.0 * 2 ** ((n.pitch - 69) / 12) for n in notes])
    return intervals, hz


def match(reference: list[VoiceNote], ours: list[VoiceNote], tolerance: float, shift=0.0):
    """mir_eval's one-to-one note matching on the position axis, pitch within
    a quarter tone, offsets ignored: [(reference index, our index)]."""
    from mir_eval.transcription import match_notes

    if not reference or not ours:
        return []
    ri, rp = _arrays(reference)
    oi, op = _arrays(ours, shift)
    return match_notes(
        ri, rp, oi, op, onset_tolerance=tolerance, pitch_tolerance=50.0, offset_ratio=None
    )


def prf(matched: int, n_ref: int, n_ours: int) -> dict[str, float]:
    p = matched / n_ours if n_ours else 0.0
    r = matched / n_ref if n_ref else 0.0
    return {
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else 0.0,
        "matched": matched,
        "reference": n_ref,
        "ours": n_ours,
    }


def best_shift(reference: TwoVoices, ours: TwoVoices, beats_per_bar: float = 4.0) -> float:
    """The whole-beat shift of our page (within two bars either way) that puts
    the most of its upper voice exactly on the reference's: a page whose bar 1
    is a beat or a bar away from the human's still compares note for note."""
    best, best_n = 0.0, -1
    span = int(2 * beats_per_bar)
    for k in range(-span, span + 1):
        n = len(match(reference.upper, ours.upper, EXACT, float(k)))
        if n > best_n or (n == best_n and abs(k) < abs(best)):
            best, best_n = float(k), n
    return best


def compare(reference: TwoVoices, ours: TwoVoices, shift: float | None = None) -> dict:
    """Per voice and pooled: written (exact) and heard (within an eighth)
    precision/recall/F1, duration agreement on the exact matches, and the
    staccato and tuplet marks' agreement there."""
    if shift is None:
        shift = best_shift(reference, ours, reference.beats_per_bar)
    shifted = TwoVoices(
        [
            VoiceNote(n.position + shift, n.duration, n.pitch, n.bar, n.staccato, n.tuplet)
            for n in ours.upper
        ],
        [
            VoiceNote(n.position + shift, n.duration, n.pitch, n.bar, n.staccato, n.tuplet)
            for n in ours.lower
        ],
    )
    out: dict = {"shift_beats": shift}
    for name, ref, mine in (
        ("upper", reference.upper, shifted.upper),
        ("lower", reference.lower, shifted.lower),
        (
            "both",
            sorted(reference.upper + reference.lower, key=lambda n: n.position),
            sorted(shifted.upper + shifted.lower, key=lambda n: n.position),
        ),
    ):
        exact = match(ref, mine, EXACT)
        near = match(ref, mine, NEAR)
        same_length = sum(1 for i, j in exact if abs(ref[i].duration - mine[j].duration) < EXACT)
        staccato = [(ref[i].staccato, mine[j].staccato) for i, j in exact]
        tuplet = [(ref[i].tuplet, mine[j].tuplet) for i, j in exact]
        out[name] = {
            "written": prf(len(exact), len(ref), len(mine)),
            "heard": prf(len(near), len(ref), len(mine)),
            "value": same_length / len(exact) if exact else 0.0,
            "staccato": {
                "both": sum(1 for a, b in staccato if a and b),
                "reference_only": sum(1 for a, b in staccato if a and not b),
                "ours_only": sum(1 for a, b in staccato if b and not a),
            },
            "tuplet": {
                "both": sum(1 for a, b in tuplet if a and b),
                "reference_only": sum(1 for a, b in tuplet if a and not b),
                "ours_only": sum(1 for a, b in tuplet if b and not a),
            },
        }
    return out


def bar_report(reference: TwoVoices, ours: TwoVoices, shift: float) -> list[dict]:
    """Per bar of the reference: how many of its notes we wrote exactly, per voice."""
    rows = []
    for voice in ("upper", "lower"):
        ref = getattr(reference, voice)
        mine = [
            VoiceNote(n.position + shift, n.duration, n.pitch, n.bar) for n in getattr(ours, voice)
        ]
        hits = {i for i, _ in match(ref, mine, EXACT)}
        for i, n in enumerate(ref):
            rows.append({"voice": voice, "bar": n.bar, "hit": i in hits})
    return rows
