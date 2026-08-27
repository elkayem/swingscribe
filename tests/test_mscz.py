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


# ── chords: what a monophonic path structurally cannot reach ────────────────


def polychord(pitches: list[int], duration: str = "quarter") -> str:
    """A Chord element carrying several Notes, the way MuseScore writes a dyad."""
    heads = "".join(f"<Note><pitch>{p}</pitch></Note>" for p in pitches)
    return f"<Chord><durationType>{duration}</durationType>{heads}</Chord>"


CHORDS = polychord([60]) + polychord([64, 67]) + polychord([60, 72], "half")


def test_melody_is_the_top_note_of_every_chord(tmp_path):
    """The single line, unchanged by chords now being kept — this is what the
    time-free aligner matches on, and two notes at one position have no order
    for it to match against."""
    score = parse_body(tmp_path, CHORDS)
    assert score.pitches == [60, 67, 72]
    assert [n.position for n in score.melody] == [0.0, 1.0, 2.0]


def test_notes_keeps_every_chord_tone(tmp_path):
    """M7b is precisely about these. A benchmark that dropped them would score
    a polyphonic transcriber identically to the monophonic one it replaces."""
    score = parse_body(tmp_path, CHORDS)
    assert [(n.position, n.pitch) for n in score.notes] == [
        (0.0, 60),
        (1.0, 64),
        (1.0, 67),
        (2.0, 60),
        (2.0, 72),
    ]


def test_chord_tones_are_what_the_melody_leaves_out(tmp_path):
    score = parse_body(tmp_path, CHORDS)
    assert [(n.position, n.pitch) for n in score.chord_tones] == [(1.0, 64), (2.0, 60)]
    assert len(score.melody) + len(score.chord_tones) == len(score.notes)


def test_a_chord_tone_carries_its_chord_duration(tmp_path):
    score = parse_body(tmp_path, CHORDS)
    lower = next(n for n in score.notes if n.position == 2.0 and n.pitch == 60)
    assert lower.duration == 2.0


def test_a_monophonic_score_has_no_chord_tones(tmp_path):
    """The four solos measured through M6 are single lines, so keeping chords
    must leave them bit-identical — which is what makes this change free."""
    score = parse_body(tmp_path, chord(60) + chord(62) + chord(64))
    assert score.chord_tones == []
    assert score.notes == score.melody


def test_to_note_events_stays_monophonic(tmp_path):
    """It feeds the MuseScore audio-vs-notation metric. Rendering chord tones
    there would charge a monophonic transcriber for notes it cannot reach and
    silently move a pinned number."""
    score = parse_body(tmp_path, CHORDS)
    assert [e.pitch for e in mscz.to_note_events(score, bpm=120.0)] == [60, 67, 72]


def ottava_start(subtype: str = "8va") -> str:
    return f'<Spanner type="Ottava"><Ottava><subtype>{subtype}</subtype></Ottava></Spanner>'


def ottava_end() -> str:
    return (
        '<Spanner type="Ottava"><prev><location><measures>0</measures></location></prev></Spanner>'
    )


def test_ottava_shifts_written_pitch_to_sounding_pitch(tmp_path):
    """8va means the notes under it SOUND an octave above what is written.

    MuseScore 4 stores the written pitch and carries the octave in a separate
    spanner, so a parser that ignores it reports the wrong octave for those
    notes — and charges the transcriber for a mistake the score never made.
    """
    body = chord(60) + ottava_start("8va") + chord(62) + chord(64) + ottava_end() + chord(65)
    score = parse_body(tmp_path, body)
    assert score.pitches == [60, 74, 76, 65]


def test_ottava_bassa_shifts_down(tmp_path):
    body = chord(60) + ottava_start("8vb") + chord(62) + ottava_end() + chord(64)
    assert parse_body(tmp_path, body).pitches == [60, 50, 64]


def test_two_octave_ottava(tmp_path):
    body = ottava_start("15ma") + chord(60) + ottava_end() + chord(62)
    assert parse_body(tmp_path, body).pitches == [84, 62]


def test_note_at_the_end_marker_is_outside_the_ottava(tmp_path):
    """The span is half-open. MuseScore's own declared length says so: a
    spanner of one quarter starting at an eighth covers two eighths, not
    three."""
    body = (
        ottava_start("8va")
        + chord(60, "eighth")
        + chord(62, "eighth")
        + ottava_end()
        + chord(64, "eighth")
    )
    assert parse_body(tmp_path, body).pitches == [72, 74, 64]


def test_an_unclosed_ottava_runs_to_the_end(tmp_path):
    body = chord(60) + ottava_start("8va") + chord(62) + chord(64)
    assert parse_body(tmp_path, body).pitches == [60, 74, 76]


def test_ottava_shifts_every_note_of_a_chord(tmp_path):
    body = (
        ottava_start("8vb")
        + "<Chord><durationType>quarter</durationType>"
        + "<Note><pitch>60</pitch></Note><Note><pitch>64</pitch></Note></Chord>"
    )
    score = parse_body(tmp_path, body)
    assert sorted(n.pitch for n in score.notes) == [48, 52]
    assert score.pitches == [52]


def test_an_unknown_ottava_subtype_is_left_alone(tmp_path):
    """Better to report the written pitch than to invent a shift."""
    body = ottava_start("nonsense") + chord(60)
    assert parse_body(tmp_path, body).pitches == [60]


# ── MusicXML in, as well as MuseScore ──────────────────────────────────────
# The strongest available check is a round trip through our own exporter: what
# `to_musicxml` writes, `parse_musicxml` must read back as the notes that went
# in. That covers divisions, dots, tuplets, ties and rests in one assertion,
# and it is what makes a WJazzD-derived score usable as a ground truth.


def _round_trip(quantized, swing=False):
    from swingscribe.stages.export import to_musicxml
    from swingscribe.stages.notate import build

    notation = build(quantized, [], swing=swing, transpose=0, title="Round Trip")
    return notation, to_musicxml(notation)


def _q(bar, beat, duration, pitch):
    from swingscribe.model import QuantizedNote

    return QuantizedNote(
        bar=bar, beat=beat, duration_beats=duration, pitch=pitch, timing_residual=0.0
    )


def test_our_own_musicxml_reads_back_as_the_notes_that_went_in(tmp_path):
    from swingscribe import mscz

    notes = [
        _q(1, 0.0, 0.5, 60),
        _q(1, 0.5, 0.5, 62),
        _q(1, 1.0, 1.0, 64),
        _q(1, 2.0, 2.0, 65),
        _q(2, 0.0, 0.5, 67),
        _q(2, 1.5, 0.5, 69),
    ]
    _notation, xml = _round_trip(notes)
    path = tmp_path / "round.musicxml"
    path.write_text(xml, encoding="utf-8")
    score = mscz.parse_musicxml(path)
    assert score.pitches == [60, 62, 64, 65, 67, 69]
    assert [round(n.position, 3) for n in score.melody] == [0.0, 0.5, 1.0, 2.0, 4.0, 5.5]


def test_a_tie_across_a_barline_reads_back_as_one_note(tmp_path):
    """A tied pair is one note, the same way the MuseScore reader treats it.
    Two notes here would be a phantom repeat in every alignment."""
    from swingscribe import mscz

    _notation, xml = _round_trip([_q(1, 3.0, 2.0, 60), _q(2, 1.0, 1.0, 62)])
    path = tmp_path / "tie.musicxml"
    path.write_text(xml, encoding="utf-8")
    score = mscz.parse_musicxml(path)
    assert score.pitches == [60, 62]
    assert score.melody[0].duration == pytest.approx(2.0)


def test_a_triplet_reads_back_at_its_written_position(tmp_path):
    from swingscribe import mscz

    third = 1.0 / 3.0
    notes = [_q(1, i * third, third, 60 + i) for i in range(3)]
    _notation, xml = _round_trip(notes, swing=True)
    path = tmp_path / "triplet.musicxml"
    path.write_text(xml, encoding="utf-8")
    score = mscz.parse_musicxml(path)
    assert score.pitches == [60, 61, 62]
    assert [round(n.position, 2) for n in score.melody] == [0.0, 0.33, 0.67]


def test_parse_any_dispatches_on_the_suffix(tmp_path):
    from swingscribe import mscz

    _notation, xml = _round_trip([_q(1, 0.0, 1.0, 60)])
    path = tmp_path / "pick.musicxml"
    path.write_text(xml, encoding="utf-8")
    assert mscz.parse_any(path).pitches == [60]
