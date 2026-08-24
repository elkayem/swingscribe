"""Reading MuseScore transcriptions as ground truth.

Fixtures are written here as XML rather than committed as .mscz: the real
benchmark scores are derivative works of commercial recordings and must never
enter git (plan §12). Hand-built scores also let each notation feature be
tested in isolation, which a real solo cannot.
"""

import zipfile

import pytest

from swingscribe import mscz


def score_xml(body: str, key: int = 0, title: str = "Test") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.70">
  <Score>
    <Division>480</Division>
    <metaTag name="workTitle">{title}</metaTag>
    <Staff>
      <Measure>
        <voice>
          <KeySig><concertKey>{key}</concertKey></KeySig>
          <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
          {body}
        </voice>
      </Measure>
    </Staff>
  </Score>
</museScore>"""


def chord(pitch: int, duration: str = "quarter", dots: int = 0, tie: bool = False) -> str:
    dot_tag = f"<dots>{dots}</dots>" if dots else ""
    tie_tag = '<Spanner type="Tie"><Tie/></Spanner>' if tie else ""
    return (
        f"<Chord><durationType>{duration}</durationType>{dot_tag}"
        f"<Note>{tie_tag}<pitch>{pitch}</pitch></Note></Chord>"
    )


def parse_body(tmp_path, body: str, **kwargs) -> mscz.Score:
    path = tmp_path / "score.mscx"
    path.write_text(score_xml(body, **kwargs), encoding="utf-8")
    return mscz.parse(path)


def test_reads_pitches_and_positions(tmp_path):
    score = parse_body(tmp_path, chord(60) + chord(62) + chord(64) + chord(65))
    assert score.pitches == [60, 62, 64, 65]
    assert [n.position for n in score.notes] == [0.0, 1.0, 2.0, 3.0]
    assert all(n.duration == 1.0 for n in score.notes)


def test_note_values_become_quarter_note_lengths(tmp_path):
    body = chord(60, "half") + chord(62, "quarter") + chord(64, "eighth") + chord(65, "16th")
    score = parse_body(tmp_path, body)
    assert [n.duration for n in score.notes] == [2.0, 1.0, 0.5, 0.25]
    assert [n.position for n in score.notes] == [0.0, 2.0, 3.0, 3.5]


def test_dots_extend_the_note(tmp_path):
    score = parse_body(tmp_path, chord(60, "quarter", dots=1) + chord(62, "eighth"))
    assert score.notes[0].duration == 1.5
    assert score.notes[1].position == 1.5


def test_double_dot(tmp_path):
    score = parse_body(tmp_path, chord(60, "quarter", dots=2))
    assert score.notes[0].duration == 1.75


def test_rests_advance_position_without_making_notes(tmp_path):
    body = chord(60) + "<Rest><durationType>quarter</durationType></Rest>" + chord(64)
    score = parse_body(tmp_path, body)
    assert score.pitches == [60, 64]
    assert [n.position for n in score.notes] == [0.0, 2.0]


def test_triplet_compresses_three_notes_into_two_beats(tmp_path):
    """An eighth-note triplet: three notes in the time of two eighths."""
    body = (
        "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes>"
        "<baseNote>eighth</baseNote></Tuplet>"
        + chord(60, "eighth")
        + chord(62, "eighth")
        + chord(64, "eighth")
        + "<endTuplet/>"
        + chord(65, "quarter")
    )
    score = parse_body(tmp_path, body)
    assert [round(n.duration, 4) for n in score.notes[:3]] == [0.3333, 0.3333, 0.3333]
    assert round(score.notes[3].position, 4) == 1.0  # the triplet filled one beat


def test_a_tie_becomes_one_longer_note(tmp_path):
    """A transcription means one sustained note, not two — and reproducing it
    means emitting one note too."""
    score = parse_body(tmp_path, chord(60, "quarter", tie=True) + chord(60, "quarter"))
    assert score.pitches == [60]
    assert score.notes[0].duration == 2.0


def test_a_tie_to_a_different_pitch_is_not_merged(tmp_path):
    # Defensive: a slur mis-encoded as a tie must not swallow a real note.
    score = parse_body(tmp_path, chord(60, "quarter", tie=True) + chord(67, "quarter"))
    assert score.pitches == [60, 67]


def test_chord_stacks_contribute_their_top_note(tmp_path):
    body = (
        "<Chord><durationType>quarter</durationType>"
        "<Note><pitch>60</pitch></Note><Note><pitch>67</pitch></Note></Chord>"
    )
    score = parse_body(tmp_path, body)
    assert score.pitches == [67]  # the melody is on top


def test_reads_title_key_and_bar_count(tmp_path):
    score = parse_body(tmp_path, chord(60), key=-4, title="Some Solo")
    assert score.title == "Some Solo"
    assert score.key_fifths == -4
    assert score.bars == 1
    assert score.beats_per_bar == 4.0


def test_reads_a_zipped_mscz(tmp_path):
    inner = score_xml(chord(60) + chord(62), title="Zipped")
    path = tmp_path / "score.mscz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("score_style.mss", "<museScore/>")
        archive.writestr("Zipped.mscx", inner)
    score = mscz.parse(path)
    assert score.title == "Zipped"
    assert score.pitches == [60, 62]


def test_mscz_without_a_score_is_rejected(tmp_path):
    path = tmp_path / "empty.mscz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("nothing.txt", "no score here")
    with pytest.raises(ValueError):
        mscz.parse(path)


def test_to_note_events_converts_beats_to_seconds(tmp_path):
    score = parse_body(tmp_path, chord(60, "quarter") + chord(62, "half"))
    events = mscz.to_note_events(score, bpm=120.0, start_seconds=10.0)
    assert [e.onset for e in events] == [10.0, 10.5]  # 120bpm → 0.5s a beat
    assert [e.duration for e in events] == [0.5, 1.0]
    assert [e.pitch for e in events] == [60, 62]
    assert all(e.source == "mscz" for e in events)


def test_to_note_events_scales_with_tempo(tmp_path):
    score = parse_body(tmp_path, chord(60, "quarter"))
    slow = mscz.to_note_events(score, bpm=60.0)
    fast = mscz.to_note_events(score, bpm=240.0)
    assert slow[0].duration == 1.0
    assert fast[0].duration == 0.25
