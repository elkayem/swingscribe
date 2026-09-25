"""The figure-prior reader, on a page small enough to count by hand.

One synthetic MusicXML file with everything the brief names: a tie, a
tuplet, a chord, a grace note, a backup into a second voice that lands a
duplicate onset, a bar that does not fill its signature, a 2/2 bar and a
compound bar. Standard library only, like the script.
"""

import importlib.util
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

from swingscribe.model import NotatedBar, NotatedNote, Notation

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("figure_prior", SCRIPTS / "figure_prior.py")
fp = importlib.util.module_from_spec(spec)
sys.modules["figure_prior"] = fp  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(fp)


def note(step, octave, duration, kind, *extra):
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>1</voice><type>{kind}</type>{''.join(extra)}</note>"
    )


TUPLET = (
    "<time-modification><actual-notes>3</actual-notes>"
    "<normal-notes>2</normal-notes></time-modification>"
)

PAGE = f"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Tenor</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>12</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <direction><sound tempo="216"/></direction>
      {note("C", 5, 6, "eighth")}
      <note><chord/><pitch><step>E</step><octave>5</octave></pitch><duration>6</duration><type>eighth</type></note>
      {note("D", 5, 6, "eighth")}
      {note("E", 5, 4, "eighth", TUPLET)}
      {note("F", 5, 4, "eighth", TUPLET)}
      {note("G", 5, 4, "eighth", TUPLET)}
      {note("A", 5, 12, "quarter", '<tie type="start"/>')}
      {note("A", 5, 12, "quarter", '<tie type="stop"/>')}
    </measure>
    <measure number="2">
      <note><grace/><pitch><step>B</step><octave>4</octave></pitch><voice>1</voice><type>eighth</type></note>
      {note("C", 5, 12, "quarter")}
      {note("D", 5, 12, "quarter")}
      {note("E", 5, 24, "half")}
      <backup><duration>48</duration></backup>
      <forward><duration>12</duration></forward>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>12</duration><voice>2</voice><type>quarter</type></note>
      <forward><duration>24</duration></forward>
    </measure>
    <measure number="3">
      {note("C", 5, 12, "quarter")}
      {note("D", 5, 12, "quarter")}
      {note("E", 5, 6, "eighth")}
    </measure>
    <measure number="4">
      <attributes><time><beats>2</beats><beat-type>2</beat-type></time></attributes>
      {note("C", 5, 24, "half")}
      <note><rest/><duration>24</duration><voice>1</voice><type>half</type></note>
    </measure>
    <measure number="5">
      <attributes><time><beats>6</beats><beat-type>8</beat-type></time></attributes>
      {note("C", 5, 18, "quarter", "<dot/>")}
      {note("D", 5, 18, "quarter", "<dot/>")}
    </measure>
  </part>
</score-partwise>
"""


def page(tmp_path: Path) -> Path:
    path = tmp_path / "Tune - Player Solo.musicxml"
    path.write_text(PAGE, encoding="utf-8")
    return path


def test_reader_honours_ties_tuplets_chords_grace_backup_and_fill(tmp_path):
    t = fp.read_transcription(page(tmp_path))
    assert t.tempo == 216.0
    assert t.source == "Wesley Chin"
    b1, b2, b3, b4, b5 = t.bars
    # Bar 1: the chord is one onset, the triplet sits at thirds, the tied-into
    # quarter is not an onset. Eight symbols, one chord collapsed, one tie.
    assert b1.onsets == [
        Fraction(0),
        Fraction(1, 2),
        Fraction(1),
        Fraction(4, 3),
        Fraction(5, 3),
        Fraction(2),
    ]
    assert b1.tied_into == 1 and b1.tie_starts == 1 and b1.tuplet_notes == 3
    assert b1.fills and b1.note_kinds[3] == "eighth[3:2]"
    assert [fp.figure_key(f) for _b, f in b1.figures()] == ["0 1/2", "0 1/3 2/3", "0", "-"]
    # Bar 2: the grace note takes no time; the second voice's quarter lands on
    # the first voice's D, a duplicate onset on beat 1; the bar still fills.
    assert b2.fills and b2.voices == 2 and b2.duplicate_beats == {1}
    assert len(b2.note_kinds) == 4  # C D E and the second voice's F; no grace
    # Bar 3 is short of its signature. Bar 4 is 2/2 and fills. Bar 5 is compound.
    assert not b3.fills and b3.filled == Fraction(5, 2)
    assert b4.fills and b4.quarter_beats and b4.signature == (2, 2)
    assert b4.rests == [(Fraction(2), Fraction(2))] and b4.rest_kinds == ["half"]
    assert b5.fills and not b5.quarter_beats


def test_beat_records_apply_the_exclusions(tmp_path):
    t = fp.read_transcription(page(tmp_path))
    records = fp.beat_records(t)
    quarter = [r for r in records if not fp.is_cut_time(r)]
    cut = [r for r in records if fp.is_cut_time(r)]
    assert fp.tally(quarter) == Counter({"0 1/2": 1, "0 1/3 2/3": 1, "0": 3, "-": 2})
    assert fp.tally(cut) == Counter({"0": 1, "-": 3})  # a half note, then a half rest
    # The duplicate beat is a gap in the bigram chain, and so is an excluded bar.
    by_beat = {(r.bar_index, r.beat): r for r in records}
    assert (1, 1) not in by_beat
    assert by_beat[(1, 2)].previous is None
    assert by_beat[(0, 1)].previous == "0 1/2"
    assert (2, 0) not in by_beat and (4, 0) not in by_beat
    # Density: the surrounding beats' onsets per beat, the beat itself left out.
    assert by_beat[(0, 0)].density is not None


def test_strict_filter_drops_disagreeing_and_doubted_bars(tmp_path):
    manifest = {
        "check_disagreeing": [2],
        "tuplet_notes": [
            "bar 1: 3 printed, a head of the group was not read",
            "bar 4: 3 eighths made a 3:2 from the page",
        ],
        "tuplets_unprinted": 0,
    }
    t = fp.read_transcription(page(tmp_path), manifest)
    assert t.doubted == {"1"} and t.disagreeing == {"2"}
    # Plain drops bar 1 (doubted) already; strict drops bar 2 too.
    assert fp.tally([r for r in fp.beat_records(t) if not fp.is_cut_time(r)]) == Counter(
        {"0": 2, "-": 1}
    )
    assert [r for r in fp.beat_records(t, strict=True) if not fp.is_cut_time(r)] == []
    assert len(fp.beat_records(t, strict=True)) == 4  # the 2/2 bar survives


def test_manifest_lookup_and_overlap_drop(tmp_path):
    out = page(tmp_path)
    (tmp_path / "book.pdf2musicxml.json").write_text(
        json.dumps({"transcriptions": [{"output": str(out), "check_disagreeing": [1]}]}),
        encoding="utf-8",
    )
    dropped = next(iter(fp.OVERLAP))
    (tmp_path / f"{dropped}.musicxml").write_text(PAGE, encoding="utf-8")
    corpus = fp.load_corpus(tmp_path, log=lambda *_: None)
    assert [t.name for t in corpus] == ["Tune - Player Solo"]
    assert corpus[0].disagreeing == {"1"}


def test_figures_from_a_parsed_score_and_from_our_page():
    positions = [0.0, 0.5, 1.0, 1 + 1 / 3, 1 + 2 / 3, 2.0]
    assert fp.figures_from_positions(positions, 4.0, 1) == Counter(
        {"0 1/2": 1, "0 1/3 2/3": 1, "0": 1, "-": 1}
    )
    notation = Notation(
        bars=[
            NotatedBar(
                number=1,
                time_signature=(4, 4),
                notes=[
                    NotatedNote(beat=0.0, duration=0.5, pitch=60),
                    NotatedNote(beat=0.5, duration=0.5, pitch=62),
                    NotatedNote(beat=1.0, duration=1.0, pitch=64, tie_start=True),
                    NotatedNote(beat=2.0, duration=1.0, pitch=64, tie_stop=True),
                    NotatedNote(beat=3.0, duration=0.5, pitch=60, is_rest=True),
                    NotatedNote(beat=3.5, duration=0.5, pitch=65, voice=2),
                ],
            )
        ]
    )
    assert fp.figures_from_notation(notation) == Counter({"0 1/2": 1, "0": 1, "-": 2})


def test_small_helpers():
    assert fp.figure_key(()) == "-"
    assert fp.figure_key((Fraction(0), Fraction(3, 4))) == "0 3/4"
    assert fp.tempo_band(20.0) is None and fp.tempo_band(216.0) == "160-220"
    assert fp.tempo_band(320.0) == ">=300" and fp.tempo_band(None) is None
    assert fp.density_bucket(1.25) == "1-1.5" and fp.density_bucket(4.0) == ">=3"
    assert fp.source_of("Birdland-Maynard-Fergusons-Trumpet-Solo") == "maxgrynchuk"
    assert fp.source_of("Lester-Young-Lester-Leaps-In") == "peterandwillanderson"
    assert fp.source_of("Don-Byas-Cherokee - 01 Cherokee") == "peterandwillanderson"
    assert abs(fp.entropy(Counter({"a": 1, "b": 1})) - 1.0) < 1e-12
