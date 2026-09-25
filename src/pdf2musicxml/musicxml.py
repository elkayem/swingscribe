"""What is done to an engine's MusicXML before it is called a transcription.

An OMR engine reads one page at a time and writes what it saw. A
transcription is a single line over several pages with a title, an
instrument, ties that hold across a page turn, and one time signature the
bars agree with. The gap between the two is arithmetic on the XML tree, and
it is here, in functions that each do one thing so a test can hold each
one:

- `concat` joins page readings into one part, rescaling `<divisions>`;
- `slurs_to_ties` recovers the ties an engine wrote as slurs (homr has no
  tie in its vocabulary; a slur between two adjacent notes at one pitch is
  a tie on a single-line jazz page);
- `fix_time_signature` trusts the bars over a misread signature (a
  handwritten 4/4 read as 6/8, a tuplet "3" read as a 3/4 change);
- `apply_instrument` writes the part name and `<transpose>` -- or shifts
  the pitches to concert -- from the instrument the page named;
- `validate` lists the bars whose notes do not add up, which is where a
  proofreader should look first;
- `bar_signatures` and `agreement` compare two engines' readings bar by
  bar, so the bars they disagree on can be listed too.

Everything works on the FIRST part only. These are single-line pages; a
second part is an engine's mistake, and `keep_main_part` says so.
"""

from __future__ import annotations

import copy
import difflib
import math
import zipfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from pdf2musicxml.instruments import Instrument

STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
STEPS = "CDEFGAB"

# Elements of <note> in schema order, so an inserted <tie> lands where the
# schema puts it (after <duration>) and MuseScore does not reject the file.
NOTE_ORDER = [
    "grace",
    "cue",
    "chord",
    "pitch",
    "unpitched",
    "rest",
    "duration",
    "tie",
    "instrument",
    "footnote",
    "level",
    "voice",
    "type",
    "dot",
    "accidental",
    "time-modification",
    "stem",
    "notehead",
    "notehead-text",
    "staff",
    "beam",
    "notations",
    "lyric",
    "play",
]


# ---------------------------------------------------------------- reading


def read(path: Path) -> ET.ElementTree:
    """A MusicXML tree from a .musicxml/.xml file or a compressed .mxl."""
    path = Path(path)
    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as archive:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//rootfile")
            name = rootfile.get("full-path") if rootfile is not None else None
            if not name:
                name = next(
                    n for n in archive.namelist() if n.lower().endswith((".xml", ".musicxml"))
                )
            return ET.ElementTree(ET.fromstring(archive.read(name)))
    return ET.parse(path)


def write(tree: ET.ElementTree, path: Path) -> None:
    root = tree.getroot()
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    Path(path).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN"'
        ' "http://www.musicxml.org/dtds/partwise.dtd">\n' + body + "\n",
        encoding="utf-8",
    )


def parts(root: ET.Element) -> list[ET.Element]:
    return root.findall("part")


def first_part(root: ET.Element) -> ET.Element:
    found = root.find("part")
    if found is None:
        raise ValueError("MusicXML has no <part>")
    return found


def note_count(part: ET.Element) -> int:
    return sum(1 for note in part.iter("note") if note.find("rest") is None)


def keep_main_part(root: ET.Element) -> list[str]:
    """Keep the part with the most notes as the only part; return the names dropped.

    A single-line page has one part. When an engine invents a second one
    (a staff it took for a different instrument), the melody must still be
    the FIRST part, because that is the one every reader takes.
    """
    all_parts = parts(root)
    if len(all_parts) <= 1:
        return []
    best = max(all_parts, key=note_count)
    part_list = root.find("part-list")
    dropped = []
    for part in all_parts:
        if part is best:
            continue
        root.remove(part)
        if part_list is not None:
            for score_part in part_list.findall("score-part"):
                if score_part.get("id") == part.get("id"):
                    dropped.append(score_part.findtext("part-name") or part.get("id") or "?")
                    part_list.remove(score_part)
    return dropped


# ---------------------------------------------------------------- notes


def divisions_of(measure: ET.Element, current: int) -> int:
    value = measure.findtext("attributes/divisions")
    return int(float(value)) if value else current


def pitch_midi(note: ET.Element) -> int | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    step = pitch.findtext("step", "C")
    octave = int(pitch.findtext("octave", "4"))
    alter = int(float(pitch.findtext("alter", "0") or 0))
    return (octave + 1) * 12 + STEP_SEMITONE[step] + alter


def _child_index(note: ET.Element, tag: str) -> int:
    """Where a new `tag` child goes in `note`, by schema order."""
    rank = NOTE_ORDER.index(tag)
    for index, child in enumerate(list(note)):
        if child.tag in NOTE_ORDER and NOTE_ORDER.index(child.tag) > rank:
            return index
    return len(list(note))


def _notations(note: ET.Element) -> ET.Element:
    notations = note.find("notations")
    if notations is None:
        notations = ET.Element("notations")
        note.insert(_child_index(note, "notations"), notations)
    return notations


def _add_tie(note: ET.Element, kind: str) -> None:
    if note.find(f'tie[@type="{kind}"]') is None:
        tie = ET.Element("tie", {"type": kind})
        note.insert(_child_index(note, "tie"), tie)
    notations = _notations(note)
    if notations.find(f'tied[@type="{kind}"]') is None:
        notations.append(ET.Element("tied", {"type": kind}))


def slurs_to_ties(part: ET.Element) -> int:
    """Turn a slur between two adjacent notes of one pitch into a tie; return how many.

    Adjacent means nothing sounds between them: no note, no rest. A slur
    over a rest, or across a change of pitch, stays a slur.
    """
    converted = 0
    previous: ET.Element | None = None
    for note in part.iter("note"):
        if note.find("grace") is not None or note.find("chord") is not None:
            continue
        if previous is not None and note.find("rest") is None:
            open_slur = previous.find('notations/slur[@type="start"]')
            close_slur = note.find('notations/slur[@type="stop"]')
            if (
                open_slur is not None
                and close_slur is not None
                and open_slur.get("number", "1") == close_slur.get("number", "1")
                and pitch_midi(previous) == pitch_midi(note)
            ):
                previous.find("notations").remove(open_slur)
                note.find("notations").remove(close_slur)
                _add_tie(previous, "start")
                _add_tie(note, "stop")
                converted += 1
        previous = note
    return converted


# ---------------------------------------------------------------- chords


def repair_chords(part: ET.Element) -> int:
    """Un-chord every note whose `<chord/>` has nothing to hang on; return how many.

    A chord tone follows the note it shares a stem with. One that follows a
    rest, a `<backup>`, a grace note or the bar line is an engine's slip,
    and MuseScore refuses the whole file for it (exit code 40, no message).
    The note is kept as a note of its own; the bar it lengthens is still
    flagged by `validate`.
    """
    fixed = 0
    for measure in part.findall("measure"):
        previous: ET.Element | None = None  # the last real note, or None after anything else
        for element in list(measure):
            if element.tag != "note":
                if element.tag in ("backup", "forward"):
                    previous = None
                continue
            chord = element.find("chord")
            if chord is not None and (
                previous is None
                or previous.find("rest") is not None
                or previous.find("grace") is not None
            ):
                element.remove(chord)
                fixed += 1
            if element.find("grace") is None:
                previous = element
    return fixed


def strip_spanning_tremolos(part: ET.Element) -> int:
    """Drop two-note tremolos (`<tremolo type="start|stop">`); return how many.

    An engine reads a trill squiggle as a tremolo between two notes, and
    when the two sit either side of a bar line MuseScore refuses the file.
    A single-note tremolo (no type) is left alone.
    """
    removed = 0
    for note in part.iter("note"):
        for ornaments in note.findall("notations/ornaments"):
            for tremolo in ornaments.findall("tremolo"):
                if tremolo.get("type") in ("start", "stop"):
                    ornaments.remove(tremolo)
                    removed += 1
            if len(list(ornaments)) == 0:
                note.find("notations").remove(ornaments)
    return removed


# ---------------------------------------------------------------- tuplets

NOMINAL_QUARTERS = {
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


def _nominal(note: ET.Element) -> Fraction | None:
    """The note's written value in quarter notes, dots included; None without a type."""
    kind = note.findtext("type")
    if kind not in NOMINAL_QUARTERS:
        return None
    value = Fraction(NOMINAL_QUARTERS[kind])
    dots = len(note.findall("dot"))
    return value * (2 - Fraction(1, 2**dots))


def _strip_tuplet(note: ET.Element) -> None:
    modification = note.find("time-modification")
    if modification is not None:
        note.remove(modification)
    notations = note.find("notations")
    if notations is not None:
        for tuplet in notations.findall("tuplet"):
            notations.remove(tuplet)


def repair_tuplets(part: ET.Element) -> int:
    """Strip every tuplet bracket whose written values do not add up to its ratio; return how many.

    MuseScore aborts the whole import, silently (exit code 40), on a bracket
    such as "3:2 over eighth, eighth, quarter": three-in-the-time-of-two
    of what? A bracket is kept when its notes share one ratio and their
    values sum to `actual` of some note value in the group (the
    `normal-type`, written in when it is not the first note's). The
    durations are left as the engine read them; only the notation goes,
    and the bar stays flagged by `validate` if it does not add up.
    """
    stripped = 0
    for measure in part.findall("measure"):
        group: list[ET.Element] = []
        open_group = False
        covered: set[int] = set()
        for note in measure.findall("note"):
            if note.find("grace") is not None:
                continue
            notations = note.find("notations")
            starts = notations is not None and notations.find('tuplet[@type="start"]') is not None
            stops = notations is not None and notations.find('tuplet[@type="stop"]') is not None
            if starts and not open_group:
                open_group = True
                group = []
            if open_group:
                group.append(note)
            elif stops or note.find("notations/tuplet") is not None:
                # a bracket mark with no bracket open: nothing to bracket
                _strip_tuplet(note)
                stripped += 1
            if stops and open_group:
                open_group = False
                covered.update(id(member) for member in group)
                if not _tuplet_adds_up(group):
                    for member in group:
                        _strip_tuplet(member)
                    stripped += 1
                group = []
        if open_group:  # never closed inside the bar: not a tuplet
            for member in group:
                _strip_tuplet(member)
            stripped += 1
        # Ratios with no bracket at all (homr writes "triplet quarters" this
        # way): a run of them must add up to whole tuplets, or it goes too.
        run: list[ET.Element] = []
        for note in measure.findall("note") + [None]:
            in_run = (
                note is not None
                and note.find("grace") is None
                and id(note) not in covered
                and note.find("time-modification") is not None
                and (not run or _ratio(note) == _ratio(run[-1]))
            )
            if in_run:
                run.append(note)
                continue
            if run and not _tuplet_adds_up(run, whole_multiples=True):
                for member in run:
                    _strip_tuplet(member)
                stripped += 1
            run = (
                [note]
                if note is not None
                and note.find("time-modification") is not None
                and id(note) not in covered
                and note.find("grace") is None
                else []
            )
    return stripped


def _ratio(note: ET.Element) -> tuple[str | None, str | None]:
    modification = note.find("time-modification")
    if modification is None:
        return (None, None)
    return (modification.findtext("actual-notes"), modification.findtext("normal-notes"))


def _tuplet_adds_up(group: list[ET.Element], whole_multiples: bool = False) -> bool:
    """Whether the written values make `actual` of one note value (a bare run: several)."""
    ratios = set()
    total = Fraction(0)
    for note in group:
        if note.find("chord") is not None:
            continue
        modification = note.find("time-modification")
        if modification is None:
            return False
        ratios.add((modification.findtext("actual-notes"), modification.findtext("normal-notes")))
        nominal = _nominal(note)
        if nominal is None:
            return False
        total += nominal
    if len(ratios) != 1:
        return False
    actual_text, _normal_text = next(iter(ratios))
    try:
        actual = int(actual_text)
    except (TypeError, ValueError):
        return False
    # Only a plain value can be the unit: a dotted one has no <normal-type>.
    plain = {Fraction(v) for v in NOMINAL_QUARTERS.values()}
    bases = {_nominal(n) for n in group if n.find("chord") is None} & plain
    # Several tuplets in a bare run are only claimed when every note has the
    # same value: "six triplet eighths" is two triplets, but four eighths
    # and a sixteenth that happen to sum to nine sixteenths are not three.
    several = whole_multiples and len(bases) == 1
    for base in sorted(bases, reverse=True):
        if not base:
            continue
        unit = actual * base
        fits = total == unit or (several and total > 0 and (total / unit).denominator == 1)
        if fits:
            # Always named: MuseScore accepts "quarter, quarter, eighth,
            # eighth under 3:2" with <normal-type>quarter</normal-type>
            # and refuses the same notes without it.
            kind = next(k for k, v in NOMINAL_QUARTERS.items() if Fraction(v) == base)
            for note in group:
                modification = note.find("time-modification")
                if modification is not None and modification.find("normal-type") is None:
                    ET.SubElement(modification, "normal-type").text = kind
            return True
    return False


# ---------------------------------------------------------------- bars


@dataclass
class Bar:
    number: str
    length: Fraction  # quarter notes actually filled
    expected: Fraction | None  # from the time signature in force
    notes: int


def _measure_length(measure: ET.Element, divisions: int) -> Fraction:
    """How many quarter notes the measure's first voice fills, following backup/forward."""
    cursor = Fraction(0)
    furthest = Fraction(0)
    for element in measure:
        if element.tag == "backup":
            cursor -= Fraction(int(float(element.findtext("duration") or 0)), divisions)
        elif element.tag == "forward":
            cursor += Fraction(int(float(element.findtext("duration") or 0)), divisions)
        elif element.tag == "note":
            if element.find("grace") is not None or element.find("chord") is not None:
                continue
            cursor += Fraction(int(float(element.findtext("duration") or 0)), divisions)
        furthest = max(furthest, cursor)
    return furthest


def _time_length(attributes: ET.Element | None) -> Fraction | None:
    if attributes is None:
        return None
    beats = attributes.findtext("time/beats")
    beat_type = attributes.findtext("time/beat-type")
    if not beats or not beat_type:
        return None
    return Fraction(int(beats) * 4, int(beat_type))


def bars(part: ET.Element) -> list[Bar]:
    divisions = 1
    expected: Fraction | None = None
    out = []
    for measure in part.findall("measure"):
        divisions = divisions_of(measure, divisions)
        declared = _time_length(measure.find("attributes"))
        if declared is not None:
            expected = declared
        out.append(
            Bar(
                measure.get("number", "?"),
                _measure_length(measure, divisions),
                expected,
                sum(1 for n in measure.findall("note") if n.find("rest") is None),
            )
        )
    return out


def _time_for(length: Fraction) -> tuple[int, int] | None:
    """A time signature whose bar is `length` quarter notes long."""
    if length.denominator == 1:
        return (int(length), 4)
    if length.denominator == 2:
        return (int(length * 2), 8)
    return None


# Signatures an engine writes that fill the bar and that no jazz page uses:
# 8/8 is a 4/4 read at the eighth, 4/8 a 2/4. Compound metres (6/8, 12/8)
# are left alone; they are real.
CANONICAL_TIME = {(8, 8): (4, 4), (4, 8): (2, 4), (16, 16): (4, 4), (2, 8): (1, 4)}
# Signatures a jazz transcription can carry. A declared one outside this set
# (a "1/2" read off a smudge) is replaced by whatever the bars fill most
# often, however irregular the bars are.
PLAUSIBLE_TIME = {
    (4, 4),
    (3, 4),
    (2, 4),
    (2, 2),
    (5, 4),
    (6, 4),
    (7, 4),
    (6, 8),
    (9, 8),
    (12, 8),
    (3, 8),
    (5, 8),
    (7, 8),
    (3, 2),
}


@dataclass
class TimeFix:
    declared: str | None
    used: str | None
    changed: bool
    dropped_changes: int
    note: str = ""


def fix_time_signature(part: ET.Element, force: str | None = None) -> TimeFix:
    """Make the first time signature agree with the bars; drop mid-piece changes that do not.

    The bars are the evidence: the length most of them fill. A declared
    signature that disagrees with it -- or none at all -- is replaced when
    at least 60% of the inner bars fill that common length. A later change
    of signature is kept only when the bars after it fill it. `force`
    ("4/4") overrides all of this.
    """
    measures = part.findall("measure")
    if not measures:
        return TimeFix(None, None, False, 0)
    first_attributes = measures[0].find("attributes")
    declared_time = first_attributes.find("time") if first_attributes is not None else None
    declared = (
        f"{declared_time.findtext('beats')}/{declared_time.findtext('beat-type')}"
        if declared_time is not None
        else None
    )
    lengths = [bar.length for bar in bars(part)]
    inner = lengths[1:-1] if len(lengths) > 3 else lengths
    counts: dict[Fraction, int] = {}
    for length in inner:
        if length > 0:
            counts[length] = counts.get(length, 0) + 1
    common = max(counts, key=counts.get) if counts else None
    share = counts[common] / max(1, len([x for x in inner if x > 0])) if common else 0.0

    declared_pair = tuple(int(x) for x in declared.split("/")) if declared else None
    declared_length = (
        Fraction(declared_pair[0] * 4, declared_pair[1]) if declared_pair is not None else None
    )
    declared_count = counts.get(declared_length, 0) if declared_length is not None else 0
    if force:
        beats, beat_type = (int(x) for x in force.split("/"))
        chosen: tuple[int, int] | None = (beats, beat_type)
        note = f"forced to {force}"
    elif common is not None and share >= 0.6 and _time_for(common) is not None:
        if declared_pair is None or Fraction(declared_pair[0] * 4, declared_pair[1]) != common:
            chosen = _time_for(common)
            note = f"{int(share * 100)}% of bars fill {common} quarters"
        elif declared_pair in CANONICAL_TIME:
            chosen = CANONICAL_TIME[declared_pair]
            note = f"{declared} fills the bars; written as {chosen[0]}/{chosen[1]}"
        else:
            chosen = None
            note = "declared signature agrees with the bars"
    elif (
        common is not None
        and _time_for(common) is not None
        and (declared_pair is None or declared_pair not in PLAUSIBLE_TIME)
    ):
        chosen = _time_for(common)
        note = (
            f"bars irregular; {declared or 'no signature'} is not one a page carries, "
            f"so the commonest length ({common} quarters, {int(share * 100)}%) decides"
        )
    elif (
        common is not None
        and _time_for(common) is not None
        and declared_length is not None
        and common != declared_length
        and share >= 0.25
        and counts[common] >= 3 * max(declared_count, 1)
    ):
        # A scan's bars are irregular, but 81 of 141 filling four quarters
        # against 5 filling the declared three is not a tie (Alone Together).
        chosen = _time_for(common)
        note = (
            f"bars irregular; {counts[common]} fill {common} quarters against "
            f"{declared_count} filling the declared {declared}"
        )
    else:
        chosen = None
        note = "bars too irregular to decide" if declared else "no signature and bars too irregular"

    changed = False
    if chosen is not None:
        if first_attributes is None:
            first_attributes = ET.Element("attributes")
            measures[0].insert(0, first_attributes)
        if declared_time is None:
            declared_time = ET.Element("time")
            # after <key>, before <clef>
            index = 0
            for i, child in enumerate(list(first_attributes)):
                if child.tag in ("divisions", "key"):
                    index = i + 1
            first_attributes.insert(index, declared_time)
        for child in list(declared_time):
            declared_time.remove(child)
        ET.SubElement(declared_time, "beats").text = str(chosen[0])
        ET.SubElement(declared_time, "beat-type").text = str(chosen[1])
        changed = f"{chosen[0]}/{chosen[1]}" != declared

    # Mid-piece changes: keep one only when the bars after it fill it.
    in_force = _time_length(first_attributes)
    dropped = 0
    for index, measure in enumerate(measures[1:], start=1):
        attributes = measure.find("attributes")
        length = _time_length(attributes)
        if length is None:
            continue
        following = [x for x in lengths[index : index + 4] if x > 0]
        fits = sum(1 for x in following if x == length)
        if force or (following and fits < len(following) / 2 and in_force is not None):
            attributes.remove(attributes.find("time"))
            if len(list(attributes)) == 0:
                measure.remove(attributes)
            dropped += 1
        else:
            in_force = length
    used_time = first_attributes.find("time") if first_attributes is not None else None
    used = (
        f"{used_time.findtext('beats')}/{used_time.findtext('beat-type')}"
        if used_time is not None
        else None
    )
    return TimeFix(declared, used, changed, dropped, note)


def set_measure_time(measure: ET.Element, beats: int, beat_type: int) -> None:
    """Declare a time signature on the measure, in its attributes (after key, before clef)."""
    attributes = measure.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        measure.insert(0, attributes)
    time = attributes.find("time")
    if time is None:
        time = ET.Element("time")
        index = 0
        for i, child in enumerate(list(attributes)):
            if child.tag in ("divisions", "key"):
                index = i + 1
        attributes.insert(index, time)
    for child in list(time):
        time.remove(child)
    ET.SubElement(time, "beats").text = str(beats)
    ET.SubElement(time, "beat-type").text = str(beat_type)


def measure_rest(duration: int) -> ET.Element:
    """A whole-measure rest: it fills its bar whatever the signature."""
    note = ET.Element("note")
    ET.SubElement(note, "rest", {"measure": "yes"})
    ET.SubElement(note, "duration").text = str(duration)
    ET.SubElement(note, "voice").text = "1"
    return note


def fill_rest_bars(part: ET.Element) -> int:
    """Write a bar of nothing, or of one whole rest, as a whole-measure rest of its bar's length.

    A whole rest stands for the whole bar in any metre; an engine writes
    it four quarters long and MuseScore flags a 12/8 or 2/4 bar of one as
    the wrong length (The First Circle's first two bars). A bar the
    engine left empty (a multi-bar rest it could not count) is filled the
    same way. Returns how many bars were written.
    """
    all_bars = bars(part)
    factor = 1
    divisions = 1
    for measure, bar in zip(part.findall("measure"), all_bars, strict=True):
        divisions = divisions_of(measure, divisions)
        if bar.expected is not None:
            factor = math.lcm(factor, (bar.expected * divisions).denominator)
    if factor > 1:
        scale_divisions(part, factor)
    filled = 0
    divisions = 1
    for measure, bar in zip(part.findall("measure"), all_bars, strict=True):
        divisions = divisions_of(measure, divisions)
        if bar.expected is None:
            continue
        notes = measure.findall("note")
        lone = None
        if len(notes) == 1 and notes[0].find("rest") is not None:
            kind = notes[0].findtext("type")
            if kind in (None, "whole") and notes[0].find("grace") is None:
                lone = notes[0]
        if notes and lone is None:
            continue
        duration = int(bar.expected * divisions)
        if lone is not None:
            if int(float(lone.findtext("duration") or 0)) == duration:
                lone.find("rest").set("measure", "yes")
                continue
            lone.find("rest").set("measure", "yes")
            lone.find("duration").text = str(duration)
            for tag in ("type", "dot"):
                for child in lone.findall(tag):
                    lone.remove(child)
        else:
            new = measure_rest(duration)
            right = next(
                (
                    c
                    for c in measure
                    if c.tag == "barline" and c.get("location", "right") == "right"
                ),
                None,
            )
            if right is not None:
                measure.insert(list(measure).index(right), new)
            else:
                measure.append(new)
        filled += 1
    return filled


def drop_redundant_times(part: ET.Element) -> int:
    """Remove a declared signature that repeats the one already in force."""
    dropped = 0
    in_force = None
    for measure in part.findall("measure"):
        attributes = measure.find("attributes")
        length = attributes.find("time") if attributes is not None else None
        if length is None:
            continue
        pair = (length.findtext("beats"), length.findtext("beat-type"))
        if pair == in_force:
            attributes.remove(length)
            if len(list(attributes)) == 0:
                measure.remove(attributes)
            dropped += 1
        in_force = pair
    return dropped


def time_changes(part: ET.Element) -> list[str]:
    """The changes of signature after the first bar, as "bar N: 2/4"."""
    out = []
    for measure in part.findall("measure")[1:]:
        time = measure.find("attributes/time")
        if time is not None:
            beats, beat_type = time.findtext("beats"), time.findtext("beat-type")
            out.append(f"bar {measure.get('number')}: {beats}/{beat_type}")
    return out


def repeat_directions(part: ET.Element) -> set[str]:
    """The repeat directions ("forward", "backward") the reading holds anywhere."""
    return {r.get("direction", "") for r in part.iter("repeat")}


def strip_repeats(part: ET.Element, keep: set[str] = frozenset()) -> int:
    """Drop the reading's repeat marks, leaving a plain double bar line behind each.

    homr writes a forward repeat at 115 double bar lines across the
    corpus where Audiveris reads 6, and a solo transcription is written
    out, not repeated; a repeat the cross-check also read (its direction
    in `keep`) stays. Returns how many marks went.
    """
    dropped = 0
    for measure in part.findall("measure"):
        for barline in measure.findall("barline"):
            for repeat in barline.findall("repeat"):
                if repeat.get("direction") in keep:
                    continue
                barline.remove(repeat)
                dropped += 1
                if barline.find("bar-style") is None:
                    style = ET.Element("bar-style")
                    style.text = "light-light"
                    barline.insert(0, style)
    return dropped


# ---------------------------------------------------------------- joining pages


def _rescale(measure: ET.Element, factor: int) -> None:
    for element in measure.iter():
        if element.tag == "duration" and element.text:
            element.text = str(int(float(element.text)) * factor)


def _canonical(element: ET.Element) -> bytes:
    """The element's content with the pretty-printing whitespace taken out."""
    clone = copy.deepcopy(element)
    for node in clone.iter():
        node.text = (node.text or "").strip() or None
        node.tail = None
    return ET.tostring(clone)


def _same(a: ET.Element | None, b: ET.Element | None) -> bool:
    if a is None or b is None:
        return a is b
    return _canonical(a) == _canonical(b)


def concat(trees: list[ET.ElementTree]) -> ET.ElementTree:
    """One tree whose first part holds every tree's first part, in order.

    Each engine run picks its own `<divisions>`; the joined part uses their
    least common multiple and rescales every duration. A page's opening
    clef, key and time are dropped when they only repeat what is in force,
    so a page turn does not become a courtesy signature.
    """
    if not trees:
        raise ValueError("nothing to join")
    result = copy.deepcopy(trees[0])
    target = first_part(result.getroot())
    all_divisions = []
    for tree in trees:
        current = 1
        for measure in first_part(tree.getroot()).findall("measure"):
            current = divisions_of(measure, current)
            all_divisions.append(current)
    lcm = 1
    for value in all_divisions:
        lcm = lcm * value // math.gcd(lcm, value)

    for measure in target.findall("measure"):
        target.remove(measure)
    in_force: dict[str, ET.Element | None] = {"clef": None, "key": None, "time": None}
    first = True
    for tree in trees:
        current = 1
        page_first = True
        for measure in first_part(tree.getroot()).findall("measure"):
            current = divisions_of(measure, current)
            measure = copy.deepcopy(measure)
            _rescale(measure, lcm // current)
            # homr writes a page's first measure with TWO <attributes>, the
            # divisions in one and key/time/clef in the other; every one is
            # examined, or the second repeats the signatures at each page turn.
            for attributes in measure.findall("attributes"):
                divisions = attributes.find("divisions")
                if divisions is not None:
                    attributes.remove(divisions)
                for tag in ("clef", "key", "time"):
                    element = attributes.find(tag)
                    if element is None:
                        continue
                    if page_first and not first and _same(element, in_force[tag]):
                        attributes.remove(element)
                    else:
                        in_force[tag] = element
                if len(list(attributes)) == 0:
                    measure.remove(attributes)
            if first:
                attributes = measure.find("attributes")
                if attributes is None:
                    attributes = ET.Element("attributes")
                    measure.insert(0, attributes)
                divisions = ET.Element("divisions")
                divisions.text = str(lcm)
                attributes.insert(0, divisions)
            target.append(measure)
            first = page_first = False
    for number, measure in enumerate(target.findall("measure"), start=1):
        measure.set("number", str(number))
    return result


# ---------------------------------------------------------------- instrument


def _transpose_pitch(pitch: ET.Element, instrument: Instrument) -> None:
    step = pitch.findtext("step", "C")
    octave = int(pitch.findtext("octave", "4"))
    alter = int(float(pitch.findtext("alter", "0") or 0))
    index = STEPS.index(step) + instrument.diatonic
    new_step = STEPS[index % 7]
    new_octave = octave + index // 7 + instrument.octave_change
    natural_shift = (
        (new_octave - instrument.octave_change) * 12
        + STEP_SEMITONE[new_step]
        - (octave * 12 + STEP_SEMITONE[step])
    )
    new_alter = alter + instrument.chromatic - natural_shift
    pitch.find("step").text = new_step
    pitch.find("octave").text = str(new_octave)
    alter_element = pitch.find("alter")
    if new_alter == 0:
        if alter_element is not None:
            pitch.remove(alter_element)
    else:
        if alter_element is None:
            alter_element = ET.Element("alter")
            pitch.insert(1, alter_element)
        alter_element.text = str(new_alter)


def _transpose_root(root_element: ET.Element, instrument: Instrument) -> None:
    step = root_element.findtext("root-step", "C")
    alter = int(float(root_element.findtext("root-alter", "0") or 0))
    index = STEPS.index(step) + instrument.diatonic
    new_step = STEPS[index % 7]
    natural_shift = (STEP_SEMITONE[new_step] - STEP_SEMITONE[step]) % 12
    new_alter = alter + (instrument.chromatic - natural_shift) % 12
    if new_alter > 6:
        new_alter -= 12
    root_element.find("root-step").text = new_step
    alter_element = root_element.find("root-alter")
    if new_alter == 0:
        if alter_element is not None:
            root_element.remove(alter_element)
    else:
        if alter_element is None:
            alter_element = ET.SubElement(root_element, "root-alter")
        alter_element.text = str(new_alter)


def apply_instrument(root: ET.Element, instrument: Instrument, *, concert: bool = False) -> None:
    """Name the part after the instrument and record -- or apply -- its transposition.

    Not `concert`: the pitches stay as printed and a `<transpose>` says how
    they sound, which MuseScore shows on its Concert Pitch toggle.
    `concert`: every pitch, chord root and key signature is shifted to
    sounding pitch and no `<transpose>` is written.
    """
    part_list = root.find("part-list")
    score_part = part_list.find("score-part") if part_list is not None else None
    if score_part is not None:
        name = score_part.find("part-name")
        if name is None:
            name = ET.SubElement(score_part, "part-name")
        name.text = instrument.name
        for tag in ("instrument-name",):
            for element in score_part.iter(tag):
                element.text = instrument.name
    part = first_part(root)
    measures = part.findall("measure")
    if not measures:
        return
    for measure in measures:
        attributes = measure.find("attributes")
        if attributes is not None:
            existing = attributes.find("transpose")
            if existing is not None:
                attributes.remove(existing)
    if instrument.concert:
        return
    if concert:
        for pitch in part.iter("pitch"):
            _transpose_pitch(pitch, instrument)
        for harmony in part.iter("harmony"):
            chord_root = harmony.find("root")
            if chord_root is not None:
                _transpose_root(chord_root, instrument)
        for fifths in part.iter("fifths"):
            fifths.text = str(int(fifths.text or 0) + instrument.fifths_shift)
        return
    attributes = measures[0].find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        measures[0].insert(0, attributes)
    transpose = ET.Element("transpose")
    ET.SubElement(transpose, "diatonic").text = str(instrument.diatonic)
    ET.SubElement(transpose, "chromatic").text = str(instrument.chromatic)
    if instrument.octave_change:
        ET.SubElement(transpose, "octave-change").text = str(instrument.octave_change)
    # <transpose> follows <clef> and <staff-details> in the schema.
    index = len(list(attributes))
    for i, child in enumerate(list(attributes)):
        if child.tag in ("directive", "measure-style"):
            index = i
            break
    attributes.insert(index, transpose)


# ---------------------------------------------------------------- titles


def set_title(root: ET.Element, title: str, subtitle: str | None = None) -> None:
    work = root.find("work")
    if work is None:
        work = ET.Element("work")
        root.insert(0, work)
    work_title = work.find("work-title")
    if work_title is None:
        work_title = ET.SubElement(work, "work-title")
    work_title.text = title
    if subtitle:
        movement = root.find("movement-title")
        if movement is None:
            movement = ET.Element("movement-title")
            root.insert(list(root).index(work) + 1, movement)
        movement.text = subtitle


def set_tempo(
    root: ET.Element, unit: str, per_minute: int, *, dots: int = 0, words: str = ""
) -> None:
    """Write a metronome mark (and the words before it) at the start of bar 1.

    `<sound tempo>` is in quarter notes per minute, whatever the beat unit,
    so a "half = 128" plays at 256; MuseScore shows the mark as printed.
    Any metronome direction an engine already put in bar 1 is replaced.
    """
    part = first_part(root)
    measures = part.findall("measure")
    if not measures:
        return
    first = measures[0]
    for direction in first.findall("direction"):
        if direction.find("direction-type/metronome") is not None:
            first.remove(direction)
    direction = ET.Element("direction", {"placement": "above"})
    if words:
        kind = ET.SubElement(direction, "direction-type")
        ET.SubElement(kind, "words", {"font-weight": "bold"}).text = words
    kind = ET.SubElement(direction, "direction-type")
    metronome = ET.SubElement(kind, "metronome", {"parentheses": "no"})
    ET.SubElement(metronome, "beat-unit").text = unit
    for _ in range(dots):
        ET.SubElement(metronome, "beat-unit-dot")
    ET.SubElement(metronome, "per-minute").text = str(per_minute)
    quarters = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}[unit]
    tempo = per_minute * quarters * (2 - 0.5**dots)
    ET.SubElement(direction, "sound", {"tempo": f"{tempo:g}"})
    # After <print> and <attributes>, before the first note or other direction.
    index = 0
    for i, child in enumerate(list(first)):
        if child.tag in ("print", "attributes", "barline"):
            index = i + 1
        else:
            break
    first.insert(index, direction)


def credit_lines(root: ET.Element) -> list[tuple[int, float, str]]:
    """(page, font size, text) of every credit an engine OCR'd, largest first."""
    out = []
    for credit in root.findall("credit"):
        page = int(credit.get("page", "1") or 1)
        for words in credit.findall("credit-words"):
            text = (words.text or "").strip()
            if text:
                out.append((page, float(words.get("font-size", "0") or 0), text))
    return sorted(out, key=lambda item: -item[1])


def strip_credits(root: ET.Element) -> None:
    for credit in root.findall("credit"):
        root.remove(credit)


# ---------------------------------------------------------------- validation


@dataclass
class Validation:
    measures: int = 0
    notes: int = 0
    rests: int = 0
    ties: int = 0
    tuplets: int = 0
    chords: int = 0
    harmonies: int = 0
    grace: int = 0
    off_bars: list[str] = field(default_factory=list)  # bar numbers whose length is wrong
    time_signature: str | None = None
    key_fifths: int | None = None

    @property
    def off_share(self) -> float:
        return len(self.off_bars) / self.measures if self.measures else 0.0


def validate(part: ET.Element) -> Validation:
    """Counts, and the bars whose notes do not fill the time signature.

    The first bar may be a pickup and the last may be short, so both are
    allowed to be UNDER; any bar over its length is wrong.
    """
    result = Validation()
    all_bars = bars(part)
    result.measures = len(all_bars)
    for index, bar in enumerate(all_bars):
        if bar.expected is None:
            continue
        edge = index == 0 or index == len(all_bars) - 1
        if bar.length > bar.expected or (bar.length < bar.expected and not edge):
            result.off_bars.append(bar.number)
    for note in part.iter("note"):
        if note.find("rest") is not None:
            result.rests += 1
            continue
        if note.find("grace") is not None:
            result.grace += 1
        if note.find("chord") is not None:
            result.chords += 1
        else:
            result.notes += 1
        if note.find('tie[@type="start"]') is not None:
            result.ties += 1
        if note.find('notations/tuplet[@type="start"]') is not None:
            result.tuplets += 1
    result.harmonies = sum(1 for _ in part.iter("harmony"))
    measures = part.findall("measure")
    if measures:
        attributes = measures[0].find("attributes")
        length = _time_length(attributes)
        if attributes is not None and length is not None:
            result.time_signature = (
                f"{attributes.findtext('time/beats')}/{attributes.findtext('time/beat-type')}"
            )
        fifths = attributes.findtext("key/fifths") if attributes is not None else None
        result.key_fifths = int(fifths) if fifths not in (None, "") else None
    return result


# ---------------------------------------------------------------- agreement


def bar_signatures(part: ET.Element) -> list[tuple]:
    """Per bar, the (pitch, length) sequence of its first voice; rests are pitch 0."""
    out = []
    divisions = 1
    for measure in part.findall("measure"):
        divisions = divisions_of(measure, divisions)
        events = []
        for note in measure.findall("note"):
            if note.find("grace") is not None or note.find("chord") is not None:
                continue
            if (note.findtext("voice") or "1") != "1":
                continue
            length = Fraction(int(float(note.findtext("duration") or 0)), divisions)
            events.append((pitch_midi(note) or 0, length))
        out.append(tuple(events))
    return out


@dataclass
class Agreement:
    matched: int
    total: int
    disagreeing: list[int]  # 1-based bar numbers of the FIRST reading not matched in the second

    @property
    def share(self) -> float:
        return self.matched / self.total if self.total else 0.0


def agreement(first: list[tuple], second: list[tuple]) -> Agreement:
    """Which bars of `first` the `second` reading reproduces, aligned by content.

    A bar dropped or split by one engine shifts every bar after it, so the
    two lists are aligned by longest matching runs (difflib), not by index.
    """
    matcher = difflib.SequenceMatcher(a=first, b=second, autojunk=False)
    matched = set()
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            matched.add(block.a + offset)
    disagreeing = [i + 1 for i in range(len(first)) if i not in matched]
    return Agreement(len(matched), len(first), disagreeing)


# ---------------------------------------------------------------- two readings, bar by bar


def scale_divisions(part: ET.Element, factor: int) -> None:
    """Multiply the part's divisions and every duration by `factor`."""
    if factor == 1:
        return
    for measure in part.findall("measure"):
        for element in measure.iter():
            if element.tag in ("divisions", "duration") and element.text:
                element.text = str(int(float(element.text)) * factor)


def _first_divisions(part: ET.Element) -> int:
    current = 1
    for measure in part.findall("measure"):
        current = divisions_of(measure, current)
        return current
    return current


@dataclass
class Merge:
    compared: int = 0  # bars the two readings had in common by count
    taken: int = 0  # bars taken from the other reading
    bars: list[str] = field(default_factory=list)  # their numbers


def merge_readings(
    part: ET.Element, other: ET.Element, printed_counts: list[int | None] | None = None
) -> Merge:
    """Take from the other reading each bar it reads better, bar for bar.

    Two engines read one page; where their bar counts agree, each bar is
    judged the way a proofreader judges it: when the page prints its
    noteheads, does it hold as many notes as the page's bar; and how far
    is it from filling its time signature. The other reading's bar
    replaces this one's where it does better (the note count outranks
    the fill, nearer the signature wins); ties stay with this reading. Both readings are brought to
    one `divisions` first, and this reading's attributes (clef, key,
    time, the divisions) stay on a replaced bar. Readings whose bar
    counts differ are left alone: nothing pairs their bars.
    """
    result = Merge()
    measures = part.findall("measure")
    others = other.findall("measure")
    if not measures or len(measures) != len(others):
        return result
    this_divisions, other_divisions = _first_divisions(part), _first_divisions(other)
    common = math.lcm(this_divisions, other_divisions)
    scale_divisions(part, common // this_divisions)
    scale_divisions(other, common // other_divisions)
    counts = printed_counts if printed_counts and len(printed_counts) == len(measures) else None
    this_bars, other_bars = bars(part), bars(other)
    result.compared = len(measures)
    for k, (mine, theirs) in enumerate(zip(measures, others, strict=True)):
        expected = this_bars[k].expected
        # The page's note count first, then how far the bar is from its
        # signature (nearer wins: a reading a third of a beat short beats
        # one a beat long); ties stay with this reading.
        score_mine: tuple = (0, 0)
        score_theirs: tuple = (0, 0)
        if counts is not None and counts[k] is not None:
            score_mine = (this_bars[k].notes == counts[k], 0)
            score_theirs = (other_bars[k].notes == counts[k], 0)
        if expected is not None:
            score_mine = (score_mine[0], -abs(this_bars[k].length - expected))
            score_theirs = (score_theirs[0], -abs(other_bars[k].length - expected))
        if score_theirs <= score_mine:
            continue
        replacement = copy.deepcopy(theirs)
        # Only the other reading's notes and chord symbols come across: its
        # OCR'd text directions ("m9;"), page breaks and bar lines do not,
        # and this reading's attributes and tempo mark stay.
        for child in list(replacement):
            if child.tag in ("attributes", "direction", "print", "barline"):
                replacement.remove(child)
        keep = [
            child
            for child in mine
            if child.tag == "attributes"
            or (child.tag == "direction" and child.find("direction-type/metronome") is not None)
        ]
        for offset, child in enumerate(keep):
            replacement.insert(offset, copy.deepcopy(child))
        replacement.set("number", mine.get("number", str(k + 1)))
        index = list(part).index(mine)
        part.remove(mine)
        part.insert(index, replacement)
        result.taken += 1
        result.bars.append(replacement.get("number"))
    if result.taken:
        # A file with any <beam> at all is beamed by hand to MuseScore, so
        # the bars without them come out as single flagged notes: none.
        for note in part.iter("note"):
            for beam in note.findall("beam"):
                note.remove(beam)
    return result
