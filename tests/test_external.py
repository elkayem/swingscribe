"""Reading another tool's output as if it were our own page (docs/head-to-head.md).

A head-to-head is only as fair as the path the competitor's file takes to
the scorers. Ours goes Notation -> scorers; theirs goes MusicXML -> reader
-> Notation -> the same scorers. So the reader is held to one thing above
all: a page WE wrote, read back, must give every scorer exactly what the
original Notation gave it -- positions, values, pitches, the rests and ties
readability counts, the key and the bars. Anything less and the reader,
not the tool, would be in the table.

Then the things a competitor's file does that ours never does: a short
pickup bar, a second voice, a chord, a grace note, a transposed part, a
tempo marking, a compressed .mxl -- and the MIDI files that carry a tool's
timing. Pure stdlib, so all of it runs in CI; the script's own logic is at
the bottom, behind an importorskip for numpy (the paired intervals).
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

from swingscribe import external
from swingscribe.benchmark import notation_notes, readability, score_against_notation
from swingscribe.external import TimedNote, crop_score, read_midi, read_musicxml, write_midi
from swingscribe.model import NotatedBar, NotatedNote, Notation
from swingscribe.mscz import Score, ScoreNote
from swingscribe.score_bars import bar_line_agreement
from swingscribe.stages.export import to_musicxml

THIRD = 1.0 / 3.0


def note(beat, duration, pitch=60, **kw) -> NotatedNote:
    return NotatedNote(beat=beat, duration=duration, pitch=pitch, **kw)


def rest(beat, duration, **kw) -> NotatedNote:
    return NotatedNote(beat=beat, duration=duration, is_rest=True, **kw)


def round_trip(notation: Notation, tmp_path: Path, name: str = "page.musicxml"):
    path = tmp_path / name
    path.write_text(to_musicxml(notation), encoding="utf-8")
    return read_musicxml(path)


def assert_same_notes(a, b):
    assert len(a) == len(b)
    for (pa, da, na), (pb, db, nb) in zip(a, b, strict=True):
        assert pa == pytest.approx(pb, abs=1e-9)
        assert da == pytest.approx(db, abs=1e-9)
        assert na == nb


def our_kind_of_page(**kw) -> Notation:
    """Everything our notate stage writes: a pickup in a FULL bar 0, a tie
    over the bar line, a triplet, a quintuplet, dotted values, short and
    long rests, and a change of metre."""
    bars = [
        NotatedBar(
            number=0,
            time_signature=(4, 4),
            notes=[rest(0.0, 3.0), note(3.0, 0.5, 67), note(3.5, 0.5, 69)],
        ),
        NotatedBar(
            number=1,
            time_signature=(4, 4),
            notes=[
                note(0.0, THIRD, 70, tuplet=(3, 2)),
                note(THIRD, THIRD, 72, tuplet=(3, 2)),
                note(2 * THIRD, THIRD, 74, tuplet=(3, 2)),
                note(1.0, 0.75, 72),
                note(1.75, 0.25, 70),
                note(2.0, 0.2, 69, tuplet=(5, 4)),
                note(2.2, 0.2, 67, tuplet=(5, 4)),
                note(2.4, 0.2, 65, tuplet=(5, 4)),
                note(2.6, 0.2, 64, tuplet=(5, 4)),
                note(2.8, 0.2, 62, tuplet=(5, 4)),
                note(3.0, 1.0, 60, tie_start=True),
            ],
        ),
        NotatedBar(
            number=2,
            time_signature=(4, 4),
            notes=[note(0.0, 1.5, 60, tie_stop=True), rest(1.5, 0.25), note(1.75, 2.25, 58)],
        ),
        NotatedBar(
            number=3,
            time_signature=(3, 4),
            notes=[note(0.0, 1.0, 57), rest(1.0, 2.0)],
        ),
    ]
    return Notation(bars=bars, key_fifths=-2, swing=True, **kw)


# ── our own page, read back ──────────────────────────────────────────────────


def test_our_page_reads_back_to_the_same_notes_rests_and_ties(tmp_path):
    notation = our_kind_of_page()
    page = round_trip(notation, tmp_path)
    assert_same_notes(notation_notes(page.line), notation_notes(notation))
    assert readability(page.notation) == readability(notation)
    assert [b.number for b in page.notation.bars] == [0, 1, 2, 3]
    assert [b.time_signature for b in page.notation.bars] == [(4, 4), (4, 4), (4, 4), (3, 4)]
    assert page.notation.key_fifths == -2
    assert page.swing_marking and page.notation.swing
    assert page.start == 0.0  # our bar 0 is a FULL bar: nothing to right-align
    assert (page.short_bars, page.long_bars) == (0, 0)


def test_a_transposed_part_reads_back_at_concert_pitch_in_the_concert_key(tmp_path):
    """A tenor part is written a major ninth up with the key moved with it
    (export); every scorer wants concert pitch and the concert key."""
    for transpose in (14, 9, 2, -12):
        notation = our_kind_of_page(transpose=transpose)
        page = round_trip(notation, tmp_path)
        assert_same_notes(notation_notes(page.line), notation_notes(notation))
        assert page.notation.key_fifths == -2
        assert page.notation.transpose == transpose


def test_the_scorers_cannot_tell_a_page_from_its_reading(tmp_path):
    """The claim the head-to-head rests on, on the scorers themselves: the
    notation measures and the bar-line agreement off the reading equal those
    off the Notation it was written from."""
    notation = our_kind_of_page()
    page = round_trip(notation, tmp_path)
    melody = [
        ScoreNote(position=p + 4.0, duration=d, pitch=n + 12, bar=1 + int((p + 4.0) // 4))
        for p, d, n in notation_notes(notation)
    ]
    reference = Score("ref", melody, melody, 5, 4.0, 0)
    assert score_against_notation(page.line, reference) == score_against_notation(
        notation, reference
    )
    assert bar_line_agreement(page.line, reference) == bar_line_agreement(notation, reference)


def test_a_double_time_page_says_so_and_is_halved_like_ours(tmp_path):
    notation = our_kind_of_page(double_time=True)
    page = round_trip(notation, tmp_path)
    assert page.notation.double_time
    assert_same_notes(notation_notes(page.line), notation_notes(notation))


def test_a_chord_is_folded_into_its_head_and_the_line_takes_its_top(tmp_path):
    notation = Notation(
        bars=[
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[note(0.0, 2.0, 60, chord=[64, 67]), note(2.0, 2.0, 62)],
            )
        ]
    )
    page = round_trip(notation, tmp_path)
    head = page.notation.bars[0].notes[0]
    assert head.pitch == 60 and sorted(head.chord) == [64, 67]
    assert readability(page.notation) == readability(notation)
    assert [p for _, _, p in notation_notes(page.line)] == [67, 62]


def test_two_staves_read_as_one_page_and_one_line(tmp_path):
    """A grand staff: readability counts both hands as written, the line
    is the top note of every onset across them -- the reference reader's
    rule for a hand score's chords."""
    notation = Notation(
        staves=2,
        bars=[
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[
                    note(0.0, 1.0, 72),
                    note(1.0, 1.0, 74),
                    rest(2.0, 2.0),
                    note(0.0, 2.0, 48, staff=2),
                    note(2.0, 2.0, 50, staff=2),
                ],
            )
        ],
    )
    page = round_trip(notation, tmp_path)
    assert readability(page.notation) == readability(notation)
    assert {n.staff for n in page.notation.bars[0].notes} == {1, 2}
    assert {n.voice for n in page.notation.bars[0].notes} == {1}
    assert [(p, n) for p, _, n in notation_notes(page.line)] == [(0.0, 72), (1.0, 74), (2.0, 50)]


def test_a_compressed_mxl_reads_like_the_file_inside_it(tmp_path):
    notation = our_kind_of_page()
    archive = tmp_path / "page.mxl"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles>'
            '<rootfile full-path="score/page.musicxml"/></rootfiles></container>',
        )
        zipped.writestr("score/page.musicxml", to_musicxml(notation))
    page = read_musicxml(archive)
    assert_same_notes(notation_notes(page.line), notation_notes(notation))


# ── what a competitor's file does that ours does not ────────────────────────

COMPETITOR = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Theirs</work-title></work>
  <identification><encoding><software>SomeTool 6.3</software></encoding></identification>
  <part-list>
    <score-part id="P1"><part-name>Tenor Sax</part-name></score-part>
    <score-part id="P2"><part-name>Bass</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="0" implicit="yes">
      <attributes>
        <divisions>480</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <transpose><diatonic>-1</diatonic><chromatic>-2</chromatic><octave-change>-1</octave-change></transpose>
      </attributes>
      <direction placement="above">
        <direction-type><metronome><beat-unit>half</beat-unit><per-minute>60</per-minute></metronome></direction-type>
      </direction>
      <direction placement="above"><direction-type><words>Swing</words></direction-type></direction>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>480</duration><voice>1</voice><type>quarter</type></note>
    </measure>
    <measure number="1">
      <direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction>
      <note><grace/><pitch><step>E</step><octave>5</octave></pitch><voice>1</voice><type>eighth</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch><duration>960</duration><voice>1</voice><type>half</type></note>
      <note><chord/><pitch><step>A</step><octave>5</octave></pitch><duration>960</duration><voice>1</voice><type>half</type></note>
      <note><pitch><step>G</step><octave>5</octave></pitch><duration>960</duration>
        <tie type="start"/><voice>1</voice><type>half</type>
        <notations><tied type="start"/></notations></note>
      <backup><duration>1920</duration></backup>
      <forward><duration>480</duration></forward>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>480</duration><voice>2</voice><type>quarter</type></note>
      <note><rest/><duration>960</duration><voice>2</voice><type>half</type></note>
      <note print-object="no"><rest/><duration>0</duration><voice>2</voice></note>
    </measure>
    <measure number="2">
      <sound tempo="150"/>
      <note><pitch><step>G</step><octave>5</octave></pitch><duration>480</duration>
        <tie type="stop"/><voice>1</voice><type>quarter</type>
        <notations><tied type="stop"/></notations></note>
      <note><pitch><step>B</step><alter>-1</alter><octave>5</octave></pitch><duration>2400</duration><voice>1</voice><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="0"><attributes><divisions>1</divisions></attributes>
      <note><pitch><step>C</step><octave>2</octave></pitch><duration>1</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""


@pytest.fixture
def competitor(tmp_path):
    path = tmp_path / "theirs.musicxml"
    path.write_text(COMPETITOR, encoding="utf-8")
    return path


def test_a_short_pickup_bar_sounds_at_its_end(competitor):
    """A pickup's notes lead INTO bar 1; laid out from the bar's start (as
    the reference reader does) every bar line after would be a beat off."""
    page = read_musicxml(competitor)
    first = page.notation.bars[0]
    assert first.number == 0 and first.notes[0].beat == 3.0
    assert page.start == 3.0
    assert notation_notes(page.line)[0][0] == 3.0


def test_the_line_is_concert_pitch_top_notes_graces_kept_ties_merged(competitor):
    page = read_musicxml(competitor)
    # Written D5 on a tenor part (down a major ninth) sounds C4.
    positions = [(p, d, n) for p, d, n in notation_notes(page.line)]
    assert positions == [
        (3.0, 1.0, 60),  # the pickup
        (4.0, 0.0, 62),  # the grace note, before its main note, no length
        (4.0, 2.0, 67),  # the chord's TOP note; the octave-shift is display only
        (5.0, 1.0, 46),  # voice 2 after the <forward>: a simultaneity with nothing
        (6.0, 3.0, 65),  # G5 tied into bar 2: one note
        (9.0, 5.0, 68),  # a bar that runs past its signature
    ]
    assert page.grace_notes == 1
    assert page.notation.key_fifths == -2  # C written for a tenor is concert B-flat
    assert page.notation.transpose == 14


def test_the_written_page_keeps_voices_and_drops_what_is_not_printed(competitor):
    page = read_musicxml(competitor)
    bar = page.notation.bars[1]
    assert [(n.voice, n.is_rest) for n in bar.notes] == [
        (1, False),
        (1, False),
        (2, False),
        (2, True),
    ]
    assert bar.notes[0].chord == [81 - 14]  # A5 written on the tenor part
    assert page.long_bars == 1  # bar 2 holds six beats under a 4/4 signature
    assert page.notation.bars[2].time_signature == (6, 4)


GRACES = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Alto</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><grace/><pitch><step>E</step><octave>5</octave></pitch><voice>1</voice><type>eighth</type></note>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
      <note><grace/><pitch><step>A</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type></note>
      <note><pitch><step>B</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
      <note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><type>half</type></note>
    </measure>
  </part>
</score-partwise>
"""


def test_grace_notes_follow_the_reader_of_the_reference(tmp_path):
    """The two reference readers disagree about grace notes: the .mscz
    reader keeps one beside its main note, the MusicXML reader lets it
    compete for the position. A tool is read by the rule of the reference
    it is compared against, or it pays an insertion per grace that the
    reference could never hold."""
    from swingscribe import mscz

    path = tmp_path / "graces.musicxml"
    path.write_text(GRACES, encoding="utf-8")
    kept = read_musicxml(path)
    competing = read_musicxml(path, graces="compete")
    assert [(p, n) for p, _, n in notation_notes(kept.line)] == [
        (0.0, 76),
        (0.0, 72),
        (1.0, 69),
        (1.0, 71),
        (2.0, 74),
    ]
    # The higher grace wins its position with no length; the lower loses.
    reference = mscz.parse_musicxml(path)
    assert [(p, d, n) for p, d, n in notation_notes(competing.line)] == [
        (n.position, n.duration, n.pitch) for n in reference.melody
    ]
    assert [n for _, _, n in notation_notes(competing.line)] == [76, 71, 74]
    assert readability(competing.notation) == readability(kept.notation)
    assert external.graces_for("tune.musicxml") == "compete"
    assert external.graces_for("page.xml") == "compete"
    assert external.graces_for("tune.mscz") == "keep"
    assert external.graces_for(None) == "keep"
    with pytest.raises(ValueError):
        read_musicxml(path, graces="drop")


def test_the_competitor_grace_under_a_chord_loses_when_graces_compete(competitor):
    line = notation_notes(read_musicxml(competitor, graces="compete").line)
    assert [(p, n) for p, _, n in line] == [(3.0, 60), (4.0, 67), (5.0, 46), (6.0, 65), (9.0, 68)]


def test_tempo_swing_title_and_parts_are_reported(competitor):
    page = read_musicxml(competitor)
    assert page.tempo == [(3.0, 120.0), (8.0, 150.0)]  # a half note at 60 is 120 quarters
    assert page.swing_marking
    assert (page.title, page.software) == ("Theirs", "SomeTool 6.3")
    assert page.parts == ["Tenor Sax", "Bass"] and page.part == "Tenor Sax"
    assert read_musicxml(competitor, part="Bass").part == "Bass"
    assert read_musicxml(competitor, part=1).part == "Bass"
    with pytest.raises(ValueError):
        read_musicxml(competitor, part="Drums")


def test_page_seconds_run_from_the_first_note_at_the_marked_tempo(competitor):
    timed = external.page_seconds(read_musicxml(competitor))
    onsets = [round(n.onset, 6) for n in timed]
    # 120 quarters a minute until position 8, 150 after; time zero is the pickup.
    assert onsets == [0.0, 0.5, 0.5, 1.0, 1.5, round(2.5 + 60 / 150, 6)]
    assert timed[-1].duration == pytest.approx(5 * 60 / 150)


def test_a_page_with_no_tempo_has_no_seconds(tmp_path):
    page = round_trip(our_kind_of_page(), tmp_path)
    assert page.tempo == []
    assert external.page_seconds(page) is None


def test_timewise_musicxml_is_refused_by_name(tmp_path):
    path = tmp_path / "timewise.musicxml"
    path.write_text('<score-timewise version="3.1"><part-list/></score-timewise>', encoding="utf-8")
    with pytest.raises(ValueError, match="timewise"):
        read_musicxml(path)


# ── MIDI ─────────────────────────────────────────────────────────────────────


def test_our_notes_survive_a_midi_file_to_well_inside_any_tolerance(tmp_path):
    notes = [
        TimedNote(0.0, 0.2, 60),
        TimedNote(0.123456, 0.05, 62),
        TimedNote(0.1235, 0.3, 67),  # 44 microseconds after the last: stays apart
        TimedNote(1.5, 0.0, 64),
        TimedNote(61.777777, 1.25, 72),
    ]
    path = tmp_path / "ours.mid"
    write_midi(notes, path)
    back = read_midi(path)
    assert [n.pitch for n in back] == [60, 62, 67, 64, 72]
    for before, after in zip(notes, back, strict=True):
        # Half a tick of 20.8 us; the duration's two ends round apart.
        assert after.onset == pytest.approx(before.onset, abs=1.1e-5)
        assert after.duration == pytest.approx(before.duration, abs=2.1e-5)


def test_a_note_struck_again_as_it_ends_pairs_its_own_note_off(tmp_path):
    path = tmp_path / "repeat.mid"
    write_midi([TimedNote(0.0, 0.5, 60), TimedNote(0.5, 0.5, 60)], path)
    back = read_midi(path)
    assert [(round(n.onset, 4), round(n.duration, 4)) for n in back] == [(0.0, 0.5), (0.5, 0.5)]


def _track(events: bytes) -> bytes:
    return b"MTrk" + len(events).to_bytes(4, "big") + events


def test_a_format_1_file_with_a_tempo_change_and_running_status(tmp_path):
    """What a notation program writes: tempo in track 0, notes in track 1,
    running status, a note-on at velocity 0 as the note-off, and a drum
    track that is not the solo."""
    division = 480
    tempo_track = (
        b"\x00\xff\x51\x03"
        + (500_000).to_bytes(3, "big")  # 120 bpm
        + b"\x83\x60\xff\x51\x03"
        + (1_000_000).to_bytes(3, "big")  # 60 bpm after 480 ticks
        + b"\x00\xff\x2f\x00"
    )
    notes_track = (
        b"\x00\x90\x3c\x50"  # C4 on at 0
        + b"\x83\x60\x3c\x00"  # running status: off at 480 (0.5 s)
        + b"\x00\x3e\x50"  # D4 on at 480
        + b"\x83\x60\x3e\x00"  # off at 960 (0.5 + 1.0 s)
        + b"\x00\x99\x24\x64"  # a kick drum on channel 10
        + b"\x10\x89\x24\x00"
        + b"\x00\xff\x2f\x00"
    )
    header = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + (2).to_bytes(2, "big")
    path = tmp_path / "theirs.mid"
    path.write_bytes(
        header + division.to_bytes(2, "big") + _track(tempo_track) + _track(notes_track)
    )
    back = read_midi(path)
    assert [(n.pitch, round(n.onset, 6), round(n.duration, 6)) for n in back] == [
        (60, 0.0, 0.5),
        (62, 0.5, 1.0),
    ]
    assert len(read_midi(path, drums=True)) == 3


def test_a_midi_file_written_from_a_page_is_told_from_a_performance(tmp_path):
    """AnthemScore's "musical (rounded) timing" writes the page's values into
    the MIDI; timed off it, a tool's hearing would be charged for its
    quantization. Onsets on a 24th of the file's quarter give it away."""
    division = 480
    events = b""
    for i in range(16):
        # Each note starts where the last ended, lasting a sixteenth (120
        # ticks) or a sixteenth triplet (80): every onset on a 24th (20 ticks).
        length = 80 if i % 4 == 0 else 120
        events += bytes([0x00, 0x90, 60 + i % 5, 0x50])
        events += bytes([length, 0x80, 60 + i % 5, 0x00])
    events += b"\x00\xff\x2f\x00"
    header = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big")
    rounded = tmp_path / "rounded.mid"
    rounded.write_bytes(header + division.to_bytes(2, "big") + _track(events))
    share, chance = external.midi_grid_share(rounded)
    assert share == 1.0 and chance == pytest.approx(24 / 480)
    assert external.midi_timing(rounded).verdict == external.QUANTIZED

    performed = tmp_path / "performed.mid"
    write_midi(
        [TimedNote(0.1 + 0.137 * i + 0.003 * (i % 7), 0.1, 60 + i % 12) for i in range(200)],
        performed,
    )
    share, chance = external.midi_grid_share(performed)
    assert chance == pytest.approx(24 / external.WRITE_DIVISION)
    assert share < 0.05
    assert external.midi_timing(performed).verdict == external.PERFORMED


def _midi_at(path: Path, division: int, ticks: list[int]) -> Path:
    """A format-0 file of short notes struck at `ticks`, `division` ticks a
    quarter (a top bit set makes it SMPTE)."""
    events, last = b"", 0
    for tick in sorted(ticks):
        events += external._vlq_bytes(tick - last) + bytes([0x90, 60, 0x50])
        events += external._vlq_bytes(1) + bytes([0x80, 60, 0x00])
        last = tick + 1
    events += b"\x00\xff\x2f\x00"
    header = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big")
    path.write_bytes(header + division.to_bytes(2, "big") + _track(events))
    return path


def test_a_midi_clock_that_cannot_tell_is_unknown_never_performed(tmp_path):
    """Fails CLOSED: only a PERFORMED verdict is paired on note F1. At 24
    ticks a quarter every onset is on the grid, a performance's too; SMPTE
    time has no quarter note; a handful of onsets on a coarse clock proves
    nothing. A division 24 does not divide is still read, to the nearest
    tick, with its own chance level."""
    wobble = [int(137 * i + 11 * (i % 7)) for i in range(120)]
    coarse = external.midi_timing(_midi_at(tmp_path / "coarse.mid", 24, wobble))
    assert (coarse.chance, coarse.share) == (1.0, 1.0)
    assert coarse.verdict == external.UNKNOWN and "24 ticks" in coarse.why

    smpte = external.midi_timing(_midi_at(tmp_path / "smpte.mid", 0xE728, wobble))
    assert smpte.verdict == external.UNKNOWN and smpte.share is None
    assert external.midi_grid_share(tmp_path / "smpte.mid") is None
    assert external.midi_timing(_midi_at(tmp_path / "empty.mid", 480, [])).verdict == (
        external.UNKNOWN
    )

    # 48 ticks a quarter: chance is a half, so five onsets on the grid are
    # nothing and forty are a page.
    few = external.midi_timing(_midi_at(tmp_path / "few.mid", 48, [2 * i for i in range(5)]))
    many = external.midi_timing(_midi_at(tmp_path / "many.mid", 48, [2 * i for i in range(40)]))
    assert few.chance == pytest.approx(0.5)
    assert (few.verdict, many.verdict) == (external.UNKNOWN, external.QUANTIZED)

    # 1000 ticks a quarter: a 24th is 41.67 ticks, written to the nearest.
    grid = [round(k * 1000 / 24) for k in range(200)]
    quantized = external.midi_timing(_midi_at(tmp_path / "q1000.mid", 1000, grid))
    loose = external.midi_timing(_midi_at(tmp_path / "p1000.mid", 1000, [t + 5 for t in wobble]))
    assert quantized.share == 1.0 and quantized.chance == pytest.approx(0.024)
    assert quantized.verdict == external.QUANTIZED
    assert loose.verdict == external.PERFORMED


def test_a_tempo_marking_times_the_page_and_moves_no_page_measure(tmp_path):
    """Our page-timed baseline: the same page with the tempo a tool would
    print. Readability, the line and the bars must not notice it."""
    notation = our_kind_of_page()
    xml = to_musicxml(notation)
    plain, marked = tmp_path / "plain.musicxml", tmp_path / "marked.musicxml"
    plain.write_text(xml, encoding="utf-8")
    marked.write_text(external.add_tempo(xml, 150.0), encoding="utf-8")
    a, b = read_musicxml(plain), read_musicxml(marked)
    assert b.tempo == [(0.0, 150.0)]
    assert readability(b.notation) == readability(a.notation)
    assert_same_notes(notation_notes(b.line), notation_notes(a.line))
    timed = external.page_seconds(b)
    assert timed[0].onset == pytest.approx(3.0 * 60 / 150)  # bar 0 opens with three beats' rest
    with pytest.raises(ValueError):
        external.add_tempo("<score-partwise/>", 120.0)


def test_a_file_that_is_not_midi_is_refused(tmp_path):
    path = tmp_path / "x.mid"
    path.write_bytes(b"not midi at all")
    with pytest.raises(ValueError):
        read_midi(path)


def test_top_line_keeps_the_highest_of_each_onset_cluster():
    chord_then_line = [
        TimedNote(0.00, 1.0, 48),
        TimedNote(0.01, 1.0, 72),
        TimedNote(0.02, 1.0, 64),
        TimedNote(0.50, 0.2, 74),
        TimedNote(0.70, 0.2, 76),
    ]
    assert [n.pitch for n in external.top_line(chord_then_line)] == [72, 74, 76]
    line = [TimedNote(0.1 * i, 0.1, 60 + i) for i in range(5)]
    assert external.top_line(line) == line
    assert external.polyphony(line) == 0.0
    assert external.polyphony(chord_then_line) == pytest.approx(2 / 5)


# ── cutting a reference to an excerpt ────────────────────────────────────────


def test_crop_score_keeps_bar_phase_and_counts_its_bars():
    melody = [
        ScoreNote(position=q, duration=0.5, pitch=60 + i, bar=1 + int(q // 4))
        for i, q in enumerate([0.0, 1.5, 4.0, 5.5, 9.0, 10.5, 13.0])
    ]
    chord_tone = ScoreNote(position=5.5, duration=0.5, pitch=55, bar=2)
    score = Score("ref", sorted([*melody, chord_tone], key=lambda n: n.position), melody, 4, 4.0, 0)
    cropped, origin = crop_score(score, [3, 4, 5])
    assert origin == 4.0
    assert [(n.position, n.pitch, n.bar) for n in cropped.melody] == [
        (1.5, 63, 1),
        (5.0, 64, 2),
        (6.5, 65, 2),
    ]
    assert cropped.bars == 2
    assert (1.5, 55) in [(n.position, n.pitch) for n in cropped.notes]
    empty, _ = crop_score(score, [])
    assert empty.melody == [] and empty.bars == 0


def _eight_bars():
    """Eight bars of straight eighths, a line that never repeats a pitch
    pattern for long, and OUR transcription of it: heard an octave low, at
    120 bpm from 10 s, with every fifth note missed and a stray low note."""
    melody = [
        ScoreNote(position=0.5 * i, duration=0.5, pitch=60 + (7 * i) % 13, bar=1 + i // 8)
        for i in range(64)
    ]
    reference = Score("ref", melody, melody, 8, 4.0, 0)
    heard = [(10.0 + 0.5 * n.position, n.pitch - 12) for i, n in enumerate(melody) if i % 5]
    heard.append((17.25, 30))
    heard.sort()
    return reference, [t for t, _ in heard], [p for _, p in heard]


def test_an_excerpt_keeps_the_reference_notes_its_audio_holds():
    """The cut is decided from where OUR notes placed the reference: bars 3
    and 4 are 14-18 s here, whatever we missed or added, and the cut keeps
    its bar phase and says where its bar lines fall."""
    reference, onsets, pitches = _eight_bars()
    cut = external.excerpt_reference(reference, onsets, pitches, (14.0, 18.0))
    assert cut.keep == list(range(16, 32))
    assert cut.anchors > 40
    assert cut.score.bars == 2
    assert [n.position for n in cut.score.melody][:3] == [0.0, 0.5, 1.0]
    assert [n.bar for n in cut.score.melody][::8] == [1, 2]
    assert cut.region == pytest.approx((14.0, 18.0), abs=1e-6)
    # A window covering everything is the whole reference, bar for bar.
    whole = external.excerpt_reference(reference, onsets, pitches, (0.0, 100.0))
    assert whole.keep == list(range(64))
    assert [(n.position, n.pitch) for n in whole.score.melody] == [
        (n.position, n.pitch) for n in reference.melody
    ]
    with pytest.raises(ValueError):
        external.excerpt_reference(reference, onsets, pitches[:-1], (14.0, 18.0))


def test_a_wjazz_excerpt_is_cut_where_our_fit_places_the_annotation():
    ref_on = [0.0, 1.0, 2.0, 3.0, 4.0]
    ref_p = [60, 62, 64, 65, 67]
    positions = [(0.0, 1), (1.0, 2), (2.0, 3), (3.0, 4), (4.0, 1)]
    # Placed at on * 1.02 + 30.0: 30.0, 31.02, 32.04, 33.06, 34.08.
    onsets, pitches, kept = external.wjazz_excerpt(
        ref_on, ref_p, positions, ref_on, 30.0, 1.02, (31.0, 33.06)
    )
    assert (onsets, pitches) == ([1.0, 2.0], [62, 64])
    assert kept == [(1.0, 2), (2.0, 3)]
    with pytest.raises(ValueError):
        external.wjazz_excerpt(ref_on, ref_p, positions[:2], ref_on, 30.0, 1.0, (0, 1))


# ── the script's own logic ───────────────────────────────────────────────────

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def head_to_head():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import head_to_head as module
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def test_the_excerpt_window_starts_at_the_span_and_never_passes_it(head_to_head):
    assert head_to_head.window((10.0, 100.0), None) == (10.0, 100.0)
    assert head_to_head.window((10.0, 100.0), 29.0) == (10.0, 39.0)
    assert head_to_head.window((10.0, 20.0), 29.0) == (10.0, 20.0)


def test_condition_names_say_what_the_tools_were_given(head_to_head):
    assert head_to_head.condition_name("mix", None) == "mix-full"
    assert head_to_head.condition_name("stem", 29.0) == "stem-excerpt29s"


def test_the_wjazz_subset_takes_one_solo_per_recording_and_spreads_the_cells(head_to_head):
    rows = [
        {"name": f"A_{i}", "title": "Blue Train", "instrument": "ts", "tempoclass": "MEDIUM"}
        for i in range(3)
    ] + [
        {"name": "B", "title": "Oleo", "instrument": "tp", "tempoclass": "UP"},
        {"name": "C", "title": "Oleo", "instrument": "p", "tempoclass": "UP"},
        {"name": "D", "title": "Embraceable You", "instrument": "as", "tempoclass": "SLOW"},
        {"name": "E", "title": "Cherokee", "instrument": "tp", "tempoclass": "UP"},
    ]
    chosen = head_to_head.choose_wjazz_subset(rows, size=4)
    titles = [next(r["title"] for r in rows if r["name"] == name) for name in chosen]
    assert len(chosen) == 4 and len(set(titles)) == 4
    assert chosen == head_to_head.choose_wjazz_subset(list(reversed(rows)), size=4)


def test_paired_rows_compare_the_same_tracks_and_respect_trust(head_to_head):
    pytest.importorskip("numpy")
    midi = {"timing": "midi"}
    ours = {
        "a": {"rhythm": 0.8, "coverage": 0.9, "note_f1": 0.5, **midi},
        "b": {"rhythm": 0.7, "coverage": 0.8, "note_f1": 0.6, **midi},
        "c": {"rhythm": 0.9, "coverage": 0.7, "note_f1": 0.7, **midi},
    }
    theirs = {
        "a": {"rhythm": 0.6, "coverage": 0.9, "note_f1": 0.4, **midi},
        # Untrusted: its rhythm is withheld.
        "b": {"rhythm": 0.9, "coverage": 0.3, "note_f1": 0.5, **midi},
    }
    rows = {r["measure"]: r for r in head_to_head.paired_rows(ours, theirs)}
    assert rows["rhythm"]["n"] == 1 and rows["rhythm"]["delta"] == pytest.approx(-0.2)
    assert rows["note_f1"]["n"] == 2 and rows["note_f1"]["delta"] == pytest.approx(-0.1)
    assert rows["note_f1"]["missing"] == 1  # a track the tool has no output for


def test_note_f1_pairs_only_performed_timing(head_to_head):
    """Timed off a page -- its tempo marking, or a MIDI file written from it
    -- note F1 measures the writing: two pseudo-tools with the same notes
    differed by -0.094 that way (docs/head-to-head.md section 8). So it is
    paired only between rows timed by performed onsets; pitch F1, which
    reads no time, pairs whatever the timing."""
    pytest.importorskip("numpy")

    def row(note, pitch, timing):
        return {
            "note_f1": note,
            "pitch_f1": pitch,
            "pitch_f1_page": pitch,
            "pitch_f1_timed": pitch,
            "timing": timing,
        }

    ours = {"a": row(0.9, 0.8, "midi"), "b": row(0.8, 0.7, "midi"), "c": row(0.7, 0.6, "midi")}
    theirs = {
        "a": row(0.5, 0.6, "page tempo"),
        "b": row(0.4, 0.5, "midi, on a grid"),
        "c": row(0.6, 0.5, "midi"),
        "d": row(0.6, 0.5, "midi, clock unread"),
    }
    ours["d"] = row(0.7, 0.6, "midi")
    rows = {r["measure"]: r for r in head_to_head.paired_rows(ours, theirs)}
    # A MIDI whose clock cannot say is not paired either: the rule fails closed.
    assert rows["note_f1"]["n"] == 1 and rows["note_f1"]["unpaired"] == 3
    assert rows["note_f1"]["delta"] == pytest.approx(0.6 - 0.7)
    assert rows["pitch_f1"]["n"] == 4
    lifted = {r["measure"]: r for r in head_to_head.paired_rows(ours, theirs, any_timing=True)}
    assert lifted["note_f1"]["n"] == 4 and lifted["note_f1"]["unpaired"] == 0


def test_pitch_f1_pairs_the_same_kind_of_output_on_both_sides(head_to_head):
    """A tool's MIDI of the whole mix against our one separated line would
    charge the separation to the hearing: pitch F1 pairs page line with
    page line where both wrote a page, else timed notes with timed notes."""
    pytest.importorskip("numpy")
    ours = {
        t: {"pitch_f1": 0.8, "pitch_f1_page": 0.8, "pitch_f1_timed": 0.7, "timing": "midi"}
        for t in "abcd"
    }
    theirs = {
        "a": {"pitch_f1": 0.6, "pitch_f1_page": 0.6, "pitch_f1_timed": 0.3},  # page and MIDI
        "b": {"pitch_f1": 0.5, "pitch_f1_timed": 0.5},  # MIDI only
        "c": {"pitch_f1": 0.4, "pitch_f1_page": 0.4},  # page only
    }
    rows = {r["measure"]: r for r in head_to_head.paired_rows(ours, theirs)}
    assert rows["pitch_f1"]["n"] == 3 and rows["pitch_f1"]["missing"] == 1
    # a: page 0.8 vs 0.6; b: timed 0.7 vs 0.5; c: page 0.8 vs 0.4.
    assert rows["pitch_f1"]["delta"] == pytest.approx((-0.2 - 0.2 - 0.4) / 3)
    assert rows["pitch_f1_timed"]["n"] == 2
    lone = {"x": {"pitch_f1": 0.8, "pitch_f1_page": 0.8}}
    only_midi = {"x": {"pitch_f1": 0.5, "pitch_f1_timed": 0.5}}
    unpaired = {r["measure"]: r for r in head_to_head.paired_rows(lone, only_midi)}
    assert unpaired["pitch_f1"]["n"] == 0 and unpaired["pitch_f1"]["unpaired"] == 1


def test_a_page_without_coverage_is_never_trusted_and_withholding_is_counted(head_to_head):
    pytest.importorskip("numpy")
    assert not head_to_head._trusted({"rhythm": 0.9})
    assert head_to_head._trusted({"coverage": 0.7})
    ours = {t: {"rhythm": 0.8, "coverage": 0.9, "timing": "midi"} for t in "abc"}
    theirs = {
        "a": {"rhythm": 0.7, "coverage": 0.9},
        "b": {"rhythm": 0.9, "coverage": 0.2},
        "c": {"rhythm": 0.9},  # no coverage: nothing matched was read
    }
    rows = {r["measure"]: r for r in head_to_head.paired_rows(ours, theirs, ["rhythm", "coverage"])}
    assert rows["rhythm"]["n"] == 1 and rows["rhythm"]["withheld"] == 2
    assert rows["coverage"]["n"] == 2


def _stale_setup(head_to_head, tmp_path, monkeypatch):
    """Two spans on disk, one whose cached notes carry the running
    transcriber's fingerprint and one whose notes some other code wrote."""
    run_eval = head_to_head.run_eval_module()
    monkeypatch.setattr(head_to_head, "BENCH", tmp_path)
    sidecar = {"file": "x.m4a", "region": [0.0, 10.0], "model": "htdemucs", "ensemble": None}
    entries = []
    runs = {}
    for name, fresh in (("fresh", True), ("old", False)):
        (tmp_path / f"{name}.m4a.swingscribe.json").write_text(
            json.dumps(sidecar), encoding="utf-8"
        )
        current = run_eval.transcribe_fingerprint(sidecar, 0.2, 0.0)
        runs[f"{name}.m4a"] = {"fingerprint": current if fresh else "0123abcd", "notes": []}
        entries.append({"set": "hand", "name": name, "run": f"{name}.m4a", "track": f"{name}.m4a"})
    return entries, runs


def test_our_baseline_refuses_notes_the_running_transcriber_would_not_write(
    head_to_head, tmp_path, monkeypatch
):
    """run_eval re-transcribes a run whose fingerprint no longer matches the
    code; a baseline written from such a run would be some other code's
    notes under this code's version string. --write-ours refuses, and with
    --allow-stale records which spans it wrote them for."""

    entries, runs = _stale_setup(head_to_head, tmp_path, monkeypatch)
    checks = head_to_head.fingerprints(entries, runs)
    assert [c["span"] for c in head_to_head.stale(checks)] == ["hand/old"]
    out = tmp_path / "out" / "swingscribe"
    with pytest.raises(SystemExit, match="hand/old"):
        head_to_head.write_ours(
            entries, out, runs, {}, None, True, tmp_path / "notes.json", log=lambda *_: None
        )
    assert not out.exists()
    head_to_head.write_ours(
        entries,
        out,
        runs,
        {},
        None,
        True,
        tmp_path / "notes.json",
        allow_stale=True,
        log=lambda *_: None,
    )
    about = json.loads((out / "tool.json").read_text(encoding="utf-8"))
    assert about["stale"] == ["hand/old"]
    assert about["fingerprints"] == {"hand/fresh": checks[0]["cached"], "hand/old": "0123abcd"}


def test_score_refuses_a_cut_made_on_notes_the_baseline_was_not_written_from(
    head_to_head, tmp_path, monkeypatch
):

    entries, runs = _stale_setup(head_to_head, tmp_path, monkeypatch)
    baseline = tmp_path / "swingscribe"
    baseline.mkdir()
    recorded = {"hand/fresh": runs["fresh.m4a"]["fingerprint"], "hand/old": "0123abcd"}
    (baseline / "tool.json").write_text(json.dumps({"fingerprints": recorded}), encoding="utf-8")
    quiet = {"log": lambda *_: None}
    head_to_head.check_baseline(baseline, entries, runs, Path("n"), True, False, **quiet)
    runs["old.m4a"]["fingerprint"] = "fedcba98"  # the cache moved on under the baseline
    with pytest.raises(SystemExit, match="hand/old"):
        head_to_head.check_baseline(baseline, entries, runs, Path("n"), True, False, **quiet)
    # No cut: a whole-span reference reads no notes, so it is only noted.
    head_to_head.check_baseline(baseline, entries, runs, Path("n"), False, False, **quiet)
    head_to_head.check_baseline(baseline, entries, runs, Path("n"), True, True, **quiet)
