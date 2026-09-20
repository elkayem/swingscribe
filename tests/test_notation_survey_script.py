"""The notation survey's tallies, on pages small enough to count by hand."""

import importlib.util
import sys
from pathlib import Path

from swingscribe.model import NotatedBar, NotatedNote, Notation

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("notation_survey", SCRIPTS / "notation_survey.py")
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)


def test_written_kind_names_the_symbol_not_the_sounding_length():
    assert survey.written_kind(0.5, None) == "eighth"
    assert survey.written_kind(0.75, None) == "eighth."
    assert survey.written_kind(0.375, None) == "16th."
    # A triplet eighth lasts a third of a beat and is written as an eighth.
    assert survey.written_kind(1 / 3, (3, 2)) == "eighth[3:2]"
    assert survey.written_kind(1 / 6, (3, 2)) == "16th[3:2]"


def test_nearest_classes_positions_and_gaps():
    assert survey.nearest(0.0, survey.POSITIONS) == "beat"
    assert survey.nearest(0.5, survey.POSITIONS) == "and"
    assert survey.nearest(2 / 3, survey.POSITIONS) == "2/3"
    assert survey.nearest(0.375, survey.POSITIONS) == "odd 32nd"
    assert survey.nearest(0.41, survey.POSITIONS) == "other"
    assert survey.nearest(1 / 6, survey.GAPS) == "16th triplet"
    assert survey.nearest(3.0, survey.GAPS, floor="half+") == "half+"


def _note(beat, duration, **kw):
    return NotatedNote(beat=beat, duration=duration, pitch=60, **kw)


def test_add_notation_merges_ties_and_counts_the_line_only():
    bars = [
        NotatedBar(
            number=1,
            time_signature=(4, 4),
            notes=[
                _note(0.0, 0.5),
                _note(0.5, 0.5),
                _note(1.0, 1 / 3, tuplet=(3, 2)),
                _note(1 + 1 / 3, 1 / 3, tuplet=(3, 2)),
                _note(1 + 2 / 3, 1 / 3, tuplet=(3, 2)),
                NotatedNote(beat=2.0, duration=1.0, is_rest=True),
                _note(3.0, 1.0, tie_start=True),
            ],
        ),
        NotatedBar(
            number=2,
            time_signature=(4, 4),
            notes=[
                _note(0.0, 0.5, tie_stop=True),
                _note(0.5, 0.5, voice=2),  # the overlay is not the page's line
                NotatedNote(beat=1.0, duration=3.0, is_rest=True),
            ],
        ),
    ]
    tally = survey.Tally("t")
    survey.add_notation(tally, Notation(bars=bars))
    assert tally.n_notes == 7  # both halves of the tied note are written notes
    assert tally.n_rests == 2
    assert tally.tied == 1
    assert tally.tuplet == 3
    assert tally.notes["eighth[3:2]"] == 3
    # Onsets: 0, 0.5, 1, 4/3, 5/3, 3 -- the tie's second half is not one.
    assert tally.n_onsets == 6
    assert tally.positions["beat"] == 3
    assert tally.positions["and"] == 1
    assert tally.positions["1/3"] == 1
    # Gaps: 0.5, 0.5, 1/3, 1/3, and 5/3 -> 3 is 4/3, which no symbol names.
    assert tally.gaps["eighth"] == 2
    assert tally.gaps["triplet eighth"] == 2
    assert tally.gaps["other"] == 1


MUSICXML = """<score-partwise><part id="P1"><measure number="1">
<note><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration><type>eighth</type>
<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification></note>
<note><pitch><step>D</step><octave>5</octave></pitch><duration>3</duration><type>eighth</type><dot/>
<tie type="start"/></note>
<note><chord/><pitch><step>F</step><octave>5</octave></pitch><duration>3</duration><type>eighth</type><dot/></note>
<note><rest/><duration>2</duration><type>quarter</type></note>
</measure></part></score-partwise>"""


def test_add_musicxml_reads_type_dots_tuplets_ties_and_skips_chord_members(tmp_path):
    path = tmp_path / "book.xml"
    path.write_text(MUSICXML, encoding="utf-8")
    tally = survey.Tally("book")
    survey.add_musicxml(tally, path)
    assert tally.n_notes == 2
    assert tally.n_rests == 1
    assert tally.notes == {"eighth[3:2]": 1, "eighth.": 1}
    assert tally.rests == {"quarter": 1}
    assert tally.tied == 1
    assert tally.tuplet == 1


def test_tally_as_dict_reports_shares_in_percent():
    tally = survey.Tally("t")
    tally.add_written("eighth", False, True, False)
    tally.add_written("quarter", False, False, False)
    tally.add_written("eighth", True, False, False)
    tally.add_onsets([0.0, 0.5, 1.0])
    out = tally.as_dict()
    assert out["tie_rate"] == 0.5
    assert out["note_values_pct"] == {"eighth": 50.0, "quarter": 50.0}
    assert out["rest_values_pct"] == {"eighth": 100.0}
    assert out["onset_positions_pct"] == {"beat": 66.67, "and": 33.33}
    assert out["gap_to_next_pct"] == {"eighth": 100.0}
