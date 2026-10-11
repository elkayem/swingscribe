"""swingscribe.horn_score: a two-voice head page against a human's."""

import pytest

pytest.importorskip("numpy")
pytest.importorskip("mir_eval")

from swingscribe import horn_score  # noqa: E402
from swingscribe.horn_score import TwoVoices, VoiceNote  # noqa: E402


def line(*notes):
    return [VoiceNote(p, d, pitch, int(p // 4) + 1) for p, d, pitch in notes]


REF = TwoVoices(
    upper=line((0, 4, 74), (4, 2, 74), (6, 1, 72), (7, 1, 74)),
    lower=line((0, 4, 70), (4, 4, 69)),
)


def test_an_identical_page_scores_one_everywhere():
    result = horn_score.compare(REF, REF)
    assert result["shift_beats"] == 0
    for voice in ("upper", "lower", "both"):
        assert result[voice]["written"]["f1"] == pytest.approx(1.0)
        assert result[voice]["value"] == pytest.approx(1.0)


def test_a_note_an_eighth_off_is_heard_but_not_written():
    ours = TwoVoices(
        upper=line((0, 4, 74), (4, 2, 74), (6.5, 0.5, 72), (7, 1, 74)), lower=REF.lower
    )
    result = horn_score.compare(REF, ours, shift=0.0)
    assert result["upper"]["written"]["matched"] == 3
    assert result["upper"]["heard"]["matched"] == 4


def test_a_page_a_bar_late_is_shifted_back():
    late = TwoVoices(
        upper=[VoiceNote(n.position + 4, n.duration, n.pitch, n.bar + 1) for n in REF.upper],
        lower=[VoiceNote(n.position + 4, n.duration, n.pitch, n.bar + 1) for n in REF.lower],
    )
    result = horn_score.compare(REF, late)
    assert result["shift_beats"] == -4
    assert result["both"]["written"]["f1"] == pytest.approx(1.0)


PAGE = """<?xml version="1.0"?>
<score-partwise><part id="P1">
<measure number="1">
 <attributes><divisions>24</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
 <note><pitch><step>D</step><octave>5</octave></pitch><duration>96</duration><voice>1</voice>
   <tie type="start"/></note>
 <backup><duration>96</duration></backup>
 <note><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch><duration>48</duration><voice>2</voice></note>
 <note><pitch><step>A</step><octave>4</octave></pitch><duration>24</duration><voice>2</voice>
   <notations><articulations><staccato/></articulations></notations></note>
 <note><rest/><duration>24</duration><voice>2</voice></note>
</measure>
<measure number="2">
 <note><pitch><step>D</step><octave>5</octave></pitch><duration>32</duration><voice>1</voice>
   <tie type="stop"/><time-modification><actual-notes>3</actual-notes>
   <normal-notes>2</normal-notes></time-modification></note>
 <note><grace/><pitch><step>C</step><octave>5</octave></pitch><voice>1</voice></note>
 <note><rest/><duration>64</duration><voice>1</voice></note>
</measure>
</part></score-partwise>"""


def test_our_musicxml_is_read_by_voice_with_ties_joined(tmp_path):
    path = tmp_path / "page.musicxml"
    path.write_text(PAGE, encoding="utf-8")
    page = horn_score.read_page(path)
    assert [(n.position, n.duration, n.pitch) for n in page.upper] == [
        (0.0, pytest.approx(4 + 4 / 3), 74)
    ]
    assert [(n.position, n.pitch, n.staccato) for n in page.lower] == [
        (0.0, 70, False),
        (2.0, 69, True),
    ]
    assert page.graces == 1 and page.bars == 2
