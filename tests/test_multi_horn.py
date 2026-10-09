"""A multi-horn head: the config's keys, the page's writing conventions, the
two-horn staff in MusicXML, the literal readings and the GUI's edits.

All synthetic and pure: no audio, no model (docs/multi-horn.md).
"""

import hashlib
from xml.etree import ElementTree

import pytest

from swingscribe.cache import canonical_json
from swingscribe.config import ENSEMBLES, Config, QuantizeConfig, TranscribeConfig
from swingscribe.gui import edits, erasures
from swingscribe.model import NotatedBar, NotatedNote, Notation, NoteEvent
from swingscribe.notation import (
    OCTAVE,
    horn_lines,
    lower_phrases,
    merge_horn_voices,
    notation_for_horns,
    notation_for_span,
    phrase_interval,
    reading_of,
    sub_phrases,
    timing_for,
)
from swingscribe.stages.export import to_musicxml
from swingscribe.stages.quantize import literal_lags, quantize_notes

BEAT = 0.5  # 120 bpm


def dump_hash(model) -> str:
    return hashlib.sha256(canonical_json(model.model_dump(mode="json")).encode()).hexdigest()[:16]


# ── the cache keys ──────────────────────────────────────────────────────────


def test_no_existing_transcribe_key_moved():
    """The multi-horn fields enter the key ONLY for a multi-horn head. These
    are the dumps as they were before the fields existed; a horn-led review,
    every pianist's and every harness note cache keep their keys."""
    assert dump_hash(TranscribeConfig()) == "97fa7c0ecb69c22b"
    assert dump_hash(TranscribeConfig(ensemble="trio")) == "7e81a1f5e562fed1"
    assert dump_hash(TranscribeConfig(ensemble="solo-piano")) == "f1fabb58fced7316"
    assert dump_hash(TranscribeConfig(ensemble="trio", piano_line="crepe")) == "1c0f4a047825179c"
    assert dump_hash(TranscribeConfig(horn_fill_gaps=False)) == "8bb6a19efad3b967"


def test_no_existing_quantize_key_moved():
    assert dump_hash(QuantizeConfig()) == "762afca5be68d378"
    assert dump_hash(QuantizeConfig(timing="literal-16")) == "80e64cc1d39a542e"
    chosen = QuantizeConfig(
        timing="literal-16", literal_eighths_beat_s=0.375, literal_lead_ins=True
    ).model_dump(mode="json")
    assert chosen["literal_eighths_beat_s"] == 0.375 and chosen["literal_lead_ins"] is True


def test_a_horn_led_dump_carries_no_multi_horn_field():
    dumped = TranscribeConfig().model_dump(mode="json")
    assert not [name for name in dumped if name.startswith("multi_horn_")]


def test_a_multi_horn_dump_carries_its_own_fields_and_none_of_crepes():
    dumped = TranscribeConfig(ensemble="multi-horn").model_dump(mode="json")
    assert dumped["multi_horn_onset_threshold"] == 0.5
    assert dumped["multi_horn_frame_threshold"] == 0.3
    assert dumped["multi_horn_min_note_ms"] == 23.0
    # The rules' own version: a change to voices.py moves the GUI's review
    # key, which hashes this dump and never transcribe.CACHE_VERSION.
    assert dumped["multi_horn_version"] == 2
    # The horn fill, the tuning, the lead-ins and the piano line are CREPE's
    # or the piano model's; a multi-horn head reads none of them.
    for gone in ("horn_fill_gaps", "tuning_correction", "glide_max_ms", "piano_line"):
        assert gone not in dumped


def test_multi_horn_is_offered_and_never_routes_to_the_piano_model():
    assert "multi-horn" in ENSEMBLES
    tc = TranscribeConfig(ensemble="multi-horn", piano_oracle=True)
    assert tc.uses_multi_horn
    assert not tc.uses_piano_oracle
    assert not tc.uses_horn_fill
    assert not tc.crepe_line


def test_a_multi_horn_page_is_literal_unless_the_sidecar_says_otherwise():
    config = Config()
    assert timing_for({"ensemble": "multi-horn"}, config) == "literal-16"
    assert timing_for({"ensemble": "multi-horn", "timing": "swing"}, config) == "swing"
    assert timing_for({}, config) == "swing"
    assert timing_for({"ensemble": "trio"}, config) == "swing"
    # A hand-edited value this build does not know is the default, not an error.
    assert timing_for({"ensemble": "multi-horn", "timing": "rubato"}, config) == "literal-16"


def test_the_literal_readings_are_off_unless_the_sidecar_turns_them_on():
    config = Config()
    assert reading_of({"ensemble": "multi-horn"}, config) == {
        "timing": "literal-16",
        "literal_lag": False,
        "literal_thirds": False,
        "literal_eighths_beat_s": 0.0,
        # A multi-horn head folds its scoops into their notes by default.
        "literal_lead_ins": True,
    }
    on = reading_of({"literal_lag": True, "literal_thirds": True, "literal_tempo": True}, config)
    assert on["literal_lag"] and on["literal_thirds"]
    assert on["literal_eighths_beat_s"] == 0.375
    assert not on["literal_lead_ins"]  # not a multi-horn head
    off = reading_of({"ensemble": "multi-horn", "literal_lead_ins": False}, config)
    assert not off["literal_lead_ins"]


# ── the writing conventions (notation.horn_lines) ────────────────────────────


def horn(onset, duration, pitch, voice=1):
    return NoteEvent(
        onset=onset, duration=duration, pitch=pitch, confidence=0.7, source="other", voice=voice
    )


def test_a_phrase_more_than_an_octave_under_is_moved_up_an_octave():
    # Bars 15-16 of the head: the tenor an octave and a minor third below.
    upper = [horn(i * 0.5, 0.5, 72 + i % 3) for i in range(8)]
    lower = [horn(i * 0.5, 0.5, 57 + i % 3, voice=2) for i in range(8)]
    lines = horn_lines(upper + lower)
    assert [n.pitch for n in lines.lower] == [n.pitch + OCTAVE for n in lower]
    assert lines.phrases[0]["interval"] == 15.0
    assert lines.phrases[0]["moved"] == OCTAVE


def test_a_phrase_in_close_harmony_is_never_moved():
    upper = [horn(i * 0.5, 0.5, 72) for i in range(8)]
    lower = [horn(i * 0.5, 0.5, 67, voice=2) for i in range(8)]
    lines = horn_lines(upper + lower)
    assert [n.pitch for n in lines.lower] == [67] * 8
    assert lines.phrases[0]["moved"] == 0


def test_the_move_is_per_phrase_never_note_by_note():
    """One note of a phrase sits further down than the rest: the phrase is
    judged by its median and moves (or not) as a whole."""
    upper = [horn(i * 0.5, 0.5, 72) for i in range(6)]
    lower = [horn(i * 0.5, 0.5, p, voice=2) for i, p in enumerate([67, 67, 55, 67, 67, 67])]
    lines = horn_lines(upper + lower)
    assert [n.pitch for n in lines.lower] == [67, 67, 55, 67, 67, 67]


def test_phrases_are_separated_by_a_rest_and_judged_apart():
    upper = [horn(i * 0.5, 0.5, 72) for i in range(4)] + [
        horn(4.0 + i * 0.5, 0.5, 72) for i in range(4)
    ]
    lower = [horn(i * 0.5, 0.5, 57, voice=2) for i in range(4)] + [
        horn(4.0 + i * 0.5, 0.5, 67, voice=2) for i in range(4)
    ]
    assert len(lower_phrases(lower)) == 2
    lines = horn_lines(upper + lower)
    assert [p["moved"] for p in lines.phrases] == [OCTAVE, 0]
    assert [n.pitch for n in lines.lower] == [69] * 4 + [67] * 4


def test_an_octave_doubling_becomes_a_unison_written_once():
    upper = [horn(i * 0.5, 0.5, 70 + i) for i in range(4)]
    lower = [horn(i * 0.5, 0.5, 58 + i, voice=2) for i in range(4)]
    lines = horn_lines(upper + lower)
    assert lines.lower == []
    assert lines.unisons == 4
    assert [n.pitch for n in lines.upper] == [70, 71, 72, 73]


def test_an_exact_unison_is_written_once_in_voice_1():
    lines = horn_lines([horn(0.0, 1.0, 65), horn(0.02, 1.0, 65, voice=2)])
    assert [n.pitch for n in lines.upper] == [65]
    assert lines.lower == []


def test_two_parts_keep_every_note_where_it_was_heard():
    upper = [horn(i * 0.5, 0.5, 70) for i in range(4)]
    lower = [horn(i * 0.5, 0.5, 58, voice=2) for i in range(4)]
    lines = horn_lines(upper + lower, move_octaves=False, merge_unisons=False)
    assert [n.pitch for n in lines.lower] == [58] * 4


def test_an_excursion_inside_a_long_phrase_is_judged_on_its_own():
    """Bars 15-16 of the head: two bars an octave and a minor third under,
    inside one unbroken phrase whose median is a fourth. The excursion moves;
    what is around it does not."""
    upper = [horn(i * 0.25, 0.25, 72) for i in range(24)]
    pitches = [67] * 8 + [57] * 8 + [67] * 8
    lower = [horn(i * 0.25, 0.25, p, voice=2) for i, p in enumerate(pitches)]
    assert len(lower_phrases(lower)) == 1
    assert [len(part) for part in sub_phrases(lower, upper)] == [8, 8, 8]
    lines = horn_lines(upper + lower)
    assert [p["moved"] for p in lines.phrases] == [0, OCTAVE, 0]
    assert [n.pitch for n in lines.lower] == [67] * 8 + [69] * 8 + [67] * 8


def test_a_short_excursion_stays_with_its_phrase():
    # Two notes, half a second: not a bar of its own, so nothing note by note.
    upper = [horn(i * 0.25, 0.25, 72) for i in range(18)]
    pitches = [67] * 8 + [57] * 2 + [67] * 8
    lower = [horn(i * 0.25, 0.25, p, voice=2) for i, p in enumerate(pitches)]
    assert len(sub_phrases(lower, upper)) == 1
    assert [n.pitch for n in horn_lines(upper + lower).lower] == pitches


def test_an_excursion_is_never_carried_past_its_end():
    """Local task A2: the excursion's phrase ran on into the next chord, an
    A-flat held a third under C, and the A-flat went up with it -- over the
    C. A close stretch at either end of a phrase stands, however short."""
    upper = [horn(i * 0.25, 0.25, 72) for i in range(10)] + [horn(2.5, 2.0, 72)]
    pitches = [57] * 10
    lower = [horn(i * 0.25, 0.25, p, voice=2) for i, p in enumerate(pitches)]
    lower.append(horn(2.5, 2.0, 68, voice=2))  # the held chord's A-flat
    assert [len(part) for part in sub_phrases(lower, upper)] == [10, 1]
    written = horn_lines(upper + lower).lower
    assert [n.pitch for n in written] == [69] * 10 + [68]
    # ... and at the start, the same.
    head = [horn(-2.0, 2.0, 68, voice=2)]
    over = [horn(-2.0, 2.0, 72)]
    written = horn_lines(over + upper[:10] + head + lower[:10]).lower
    assert [n.pitch for n in written] == [68] + [69] * 10


def test_a_short_wide_stretch_at_an_end_is_not_moved_alone():
    upper = [horn(i * 0.25, 0.25, 72) for i in range(12)]
    pitches = [67] * 10 + [57] * 2
    lower = [horn(i * 0.25, 0.25, p, voice=2) for i, p in enumerate(pitches)]
    assert len(sub_phrases(lower, upper)) == 1
    assert [n.pitch for n in horn_lines(upper + lower).lower] == pitches


def test_a_lone_note_goes_with_the_stretch_it_is_in():
    upper = [horn(i * 0.25, 0.25, 72) for i in range(1, 9)]
    lower = [horn(i * 0.25, 0.25, 57, voice=2) for i in range(9)]  # the first has no partner
    (only,) = sub_phrases(lower, upper)
    assert len(only) == 9
    assert {n.pitch for n in horn_lines(upper + lower).lower} == {69}


def test_the_phrase_interval_is_weighted_by_time_together():
    phrase = [horn(0.0, 2.0, 60, voice=2)]
    upper = [horn(0.0, 1.5, 64), horn(1.5, 0.5, 79)]
    assert phrase_interval(phrase, upper) == 4.0
    assert phrase_interval(phrase, []) is None


# ── the two-horn staff (notation.merge_horn_voices) ──────────────────────────


def bar(number, notes):
    return NotatedBar(number=number, time_signature=(4, 4), notes=notes)


def rest(beat, duration):
    return NotatedNote(beat=beat, duration=duration, is_rest=True)


def sound(beat, duration, pitch):
    return NotatedNote(beat=beat, duration=duration, pitch=pitch)


def test_a_bar_of_both_voices_stems_up_and_down_and_hides_the_lower_rests():
    upper = Notation(bars=[bar(1, [sound(0, 2, 74), rest(2, 1), sound(3, 1, 65)])])
    lower = Notation(bars=[bar(1, [sound(0, 2, 70), rest(2, 2)])])
    merged = merge_horn_voices(upper, lower, key=-1)
    notes = merged.bars[0].notes
    top = [n for n in notes if n.voice == 1]
    bottom = [n for n in notes if n.voice == 2]
    assert [(n.stem, n.hidden) for n in top] == [("up", False), ("", False), ("up", False)]
    assert [(n.stem, n.hidden) for n in bottom] == [("down", False), ("", True)]
    assert merged.key_fifths == -1
    assert merged.staves == 1


def test_a_bar_of_the_upper_voice_alone_has_automatic_stems_and_no_lower_rests():
    upper = Notation(bars=[bar(1, [sound(0, 4, 72)]), bar(2, [sound(0, 4, 74)])])
    lower = Notation(bars=[bar(1, [sound(0, 4, 67)]), bar(2, [rest(0, 4)])])
    merged = merge_horn_voices(upper, lower)
    second = merged.bars[1].notes
    assert [(n.voice, n.stem) for n in second] == [(1, "")]


def test_the_key_is_read_once_over_both_voices():
    # A flat key the lower voice alone shows: Bb and Eb are only down there.
    upper = Notation(bars=[bar(1, [sound(0, 4, 65)])])
    lower = Notation(bars=[bar(1, [sound(0, 2, 58), sound(2, 2, 63)])])
    merged = merge_horn_voices(upper, lower)
    lowered = [n for n in merged.bars[0].notes if n.voice == 2]
    assert all(n.alter in (0, -1) for n in lowered)
    assert [n.step for n in lowered] == ["B", "E"]


def test_the_page_writes_stems_and_invisible_rests():
    upper = Notation(bars=[bar(1, [sound(0, 2, 74), rest(2, 2)])])
    lower = Notation(bars=[bar(1, [sound(0, 2, 70), rest(2, 2)])])
    xml = to_musicxml(merge_horn_voices(upper, lower))
    root = ElementTree.fromstring(xml[xml.index("<score-partwise") :])
    notes = root.find("part").find("measure").findall("note")
    stems = [n.findtext("stem") for n in notes]
    assert stems == ["up", None, "down", None]
    hidden = [n.get("print-object") for n in notes]
    assert hidden == [None, None, None, "no"]
    # The upper voice's rest is drawn; the voices are 1 then 2.
    assert [n.findtext("voice") for n in notes] == ["1", "1", "2", "2"]


def two_horn_line(beats, upper_pitches, lower_pitches):
    notes = []
    for i, t in enumerate(beats):
        notes.append(horn(t, BEAT * 0.95, upper_pitches[i % len(upper_pitches)]))
        notes.append(horn(t, BEAT * 0.95, lower_pitches[i % len(lower_pitches)], voice=2))
    return notes


def grid(count=48, start=10.0):
    return [round(start + i * BEAT, 6) for i in range(count)]


def literal_config(**quantize):
    base = Config()
    return base.model_copy(
        update={"quantize": base.quantize.model_copy(update={"timing": "literal-16", **quantize})}
    )


def test_a_two_horn_head_is_one_staff_of_two_voices_on_one_grid():
    beats = grid()
    notes = two_horn_line(beats[4:20], [74, 72, 70, 72], [70, 69, 65, 69])
    region = (beats[4], beats[20])
    page, lines = notation_for_horns(
        "t.wav", notes, beats, region, stem="other", config=literal_config(), anchor=beats[4]
    )
    assert page is not None and page.staves == 1
    assert lines.unisons == 0
    full = [b for b in page.bars if any(not n.is_rest for n in b.notes)]
    for written in full:
        uppers = [n for n in written.notes if n.voice == 1 and not n.is_rest]
        lowers = [n for n in written.notes if n.voice == 2 and not n.is_rest]
        assert uppers and lowers
        # One grid: every lower attack has an upper attack on the same beat.
        assert {n.beat for n in lowers if not n.tie_stop} <= {
            n.beat for n in uppers if not n.tie_stop
        }
        # Each voice fills its bar.
        for voice in (1, 2):
            assert sum(n.duration for n in written.notes if n.voice == voice) == 4.0


def test_the_same_page_with_no_lower_voice_is_the_upper_line_alone():
    beats = grid()
    upper = [horn(t, BEAT * 0.95, 72) for t in beats[4:20]]
    region = (beats[4], beats[20])
    page, _ = notation_for_horns(
        "t.wav", upper, beats, region, stem="other", config=literal_config(), anchor=beats[4]
    )
    assert all(n.voice == 1 and n.stem == "" for b in page.bars for n in b.notes)


def test_a_head_with_only_a_lower_voice_still_writes_it():
    beats = grid()
    lower = [horn(t, BEAT * 0.95, 60, voice=2) for t in beats[4:20]]
    region = (beats[4], beats[20])
    page = notation_for_span(
        "t.wav",
        [],
        beats,
        region,
        stem="other",
        config=literal_config(),
        anchor=beats[4],
        lower_voice=lower,
    )
    assert any(n.voice == 2 and not n.is_rest for b in page.bars for n in b.notes)


def test_the_lag_is_read_once_and_moves_both_horns_together():
    """A held chord struck 0.2 of a beat behind: on the literal grid it is
    the "e"; with the lag taken out it is the beat -- in BOTH voices, even
    though the lower horn is a hair later than the upper."""
    beats = grid()
    late = 0.2 * BEAT
    notes = []
    for t in beats[4:20]:
        notes.append(horn(t + late, BEAT * 0.9, 72))
        notes.append(horn(t + late + 0.012, BEAT * 0.9, 67, voice=2))
    region = (beats[4], beats[20])
    as_played, _ = notation_for_horns(
        "t.wav", notes, beats, region, stem="other", config=literal_config(), anchor=beats[4]
    )
    unlagged, _ = notation_for_horns(
        "t.wav",
        notes,
        beats,
        region,
        stem="other",
        config=literal_config(literal_lag=True),
        anchor=beats[4],
    )

    def attacks(page, voice):
        return {
            round(n.beat % 1, 3)
            for b in page.bars
            for n in b.notes
            if n.voice == voice and not n.is_rest and not n.tie_stop
        }

    assert attacks(as_played, 1) == {0.25}
    assert attacks(unlagged, 1) == {0.0}
    assert attacks(unlagged, 2) == {0.0}


# ── the literal readings (quantize) ──────────────────────────────────────────


def literal(onsets, **kwargs):
    beats = [float(i) * BEAT for i in range(40)]
    return quantize_notes(onsets, [0.1] * len(onsets), [60] * len(onsets), beats, [], [], **kwargs)[
        0
    ]


def test_literal_thirds_write_an_eighth_note_triplet():
    onsets = [4 * BEAT + f * BEAT for f in (0.0, 1 / 3, 2 / 3)]
    plain = literal(onsets, timing="literal-16")
    thirds = literal(onsets, timing="literal-16", literal_thirds=True)
    assert [round(n.beat, 6) for n in plain] == [4.0, 4.25, 4.75]
    assert [round(n.beat, 6) for n in thirds] == [4.0, round(4 + 1 / 3, 6), round(4 + 2 / 3, 6)]


def test_literal_thirds_leave_sixteenths_and_pairs_alone():
    sixteenths = [4 * BEAT + f * BEAT for f in (0.0, 0.25, 0.5)]
    assert [
        round(n.beat, 6) for n in literal(sixteenths, timing="literal-16", literal_thirds=True)
    ] == [
        4.0,
        4.25,
        4.5,
    ]
    pair = [4 * BEAT, 4 * BEAT + BEAT * 2 / 3]
    assert [round(n.beat, 6) for n in literal(pair, timing="literal-16", literal_thirds=True)] == [
        4.0,
        4.75,
    ]


def test_literal_thirds_need_every_onset_inside_the_beat():
    # The third onset is the next beat's note, early: not a triplet.
    onsets = [4 * BEAT + f * BEAT for f in (0.33, 0.67, 0.95)]
    positions = [
        round(n.beat, 6) for n in literal(onsets, timing="literal-16", literal_thirds=True)
    ]
    assert positions != [round(4 + 1 / 3, 6), round(4 + 2 / 3, 6), 5.0]
    assert all(abs(p * 3 - round(p * 3)) > 1e-6 or p == int(p) for p in positions)


def test_literal_lag_takes_a_late_line_back_to_the_beat():
    onsets = [(4 + i) * BEAT + 0.15 * BEAT for i in range(12)]
    plain = literal(onsets, timing="literal-16")
    unlagged = literal(
        onsets, timing="literal-16", literal_lag=True, lag_window_beats=4, lag_floor=0.08
    )
    assert all(round(n.beat % 1, 6) == 0.25 for n in plain)
    assert all(round(n.beat % 1, 6) == 0.0 for n in unlagged)


def test_literal_lags_read_the_median_late_downbeat():
    beats = [float(i) * BEAT for i in range(40)]
    onsets = [(4 + i) * BEAT + 0.2 * BEAT for i in range(12)]
    lags = literal_lags(onsets, beats, 4, 0.2, 0.08)
    assert lags and all(abs(lag - 0.2) < 1e-6 for lag in lags.values())


FAST = 0.24  # 250 bpm, the Open Sesame head


def fast_literal(onsets, **kwargs):
    beats = [float(i) * FAST for i in range(40)]
    notes, _ = quantize_notes(
        onsets, [0.05] * len(onsets), [60] * len(onsets), beats, [], [], **kwargs
    )
    return [round(n.beat, 6) for n in notes]


def test_a_fast_literal_beat_is_written_on_eighths_when_the_listener_asks():
    """At 250 bpm a 16th is 60 ms; an attack 0.2 of a beat behind (48 ms)
    is the "e" on 16ths and the beat on eighths."""
    onsets = [(4 + i) * FAST + 0.2 * FAST for i in range(4)]
    assert fast_literal(onsets, timing="literal-16") == [4.25, 5.25, 6.25, 7.25]
    assert fast_literal(onsets, timing="literal-16", literal_eighths_beat_s=0.375) == [
        4.0,
        5.0,
        6.0,
        7.0,
    ]


def test_eighths_by_tempo_refine_where_they_cannot_keep_onsets_apart():
    sixteenths = [4 * FAST + f * FAST for f in (0.0, 0.25, 0.5)]
    assert fast_literal(sixteenths, timing="literal-16", literal_eighths_beat_s=0.375) == [
        4.0,
        4.25,
        4.5,
    ]


def test_eighths_by_tempo_leave_a_slower_beat_on_sixteenths():
    onsets = [(4 + i) * BEAT + 0.2 * BEAT for i in range(4)]
    assert [
        round(n.beat, 6) for n in literal(onsets, timing="literal-16", literal_eighths_beat_s=0.375)
    ] == [4.25, 5.25, 6.25, 7.25]


def test_a_literal_grid_is_unchanged_without_the_tempo_reading():
    # literal-32 never refines; literal-16 refines once, to 32nds.
    crowded = [4 * BEAT + f * BEAT for f in (0.0, 0.1, 0.2)]
    assert [round(n.beat, 6) for n in literal(crowded, timing="literal-16")] == [
        4.0,
        4.125,
        4.25,
    ]
    assert [round(n.beat, 6) for n in literal(crowded, timing="literal-32")] == [
        4.0,
        4.125,
        4.25,
    ]


def scoop(onset, duration, pitch, voice):
    return NoteEvent(
        onset=onset,
        duration=duration,
        pitch=pitch,
        confidence=0.7,
        source="other",
        voice=voice,
        lead_in=True,
    )


def test_a_multi_horn_page_folds_both_horns_scoops_into_the_chord():
    """Bar 23: both horns scoop a semitone into a held chord. On the head's
    page the chord is written on the beat, each scoop as its grace note; a
    page that does not fold writes the scoops as notes."""
    beats = grid()
    t = beats[8]
    notes = [
        scoop(t, 0.06, 71, 1),
        scoop(t, 0.06, 66, 2),
        horn(t + 0.06, 3 * BEAT, 72),
        horn(t + 0.06, 3 * BEAT, 67, voice=2),
    ]
    region = (beats[4], beats[20])

    def sounding(config):
        page, _ = notation_for_horns(
            "t.wav", notes, beats, region, stem="other", config=config, anchor=beats[4]
        )
        return [
            (n.voice, round(n.beat, 6), n.pitch, list(n.grace))
            for b in page.bars
            for n in b.notes
            if not n.is_rest and not n.tie_stop
        ]

    folded = sounding(literal_config(literal_lead_ins=True))
    assert sorted(folded) == [(1, 0.0, 72, [71]), (2, 0.0, 67, [66])]
    as_heard = sounding(literal_config())
    assert sorted(p for _, _, p, _ in as_heard) == [66, 67, 71, 72]


def test_a_literal_page_in_thirds_is_written_as_a_triplet():
    beats = grid()
    notes = []
    for t in beats[4:20]:
        for f in (0.0, 1 / 3, 2 / 3):
            notes.append(horn(t + f * BEAT, BEAT / 3 * 0.9, 72))
            notes.append(horn(t + f * BEAT, BEAT / 3 * 0.9, 67, voice=2))
    region = (beats[4], beats[20])
    page, _ = notation_for_horns(
        "t.wav",
        notes,
        beats,
        region,
        stem="other",
        config=literal_config(literal_thirds=True),
        anchor=beats[4],
    )
    sounding = [n for b in page.bars for n in b.notes if not n.is_rest]
    assert sounding and all(n.tuplet == (3, 2) for n in sounding)
    assert {n.voice for n in sounding} == {1, 2}


# ── the GUI's edits on a multi-horn head (gui/edits.py) ──────────────────────


def payload(notes, candidates=()):
    return {"notes": list(notes), "candidates": list(candidates)}


def heard(onset, duration, pitch, voice=1, confidence=0.7):
    return {
        "onset": onset,
        "duration": duration,
        "pitch": pitch,
        "confidence": confidence,
        "voice": voice,
    }


def test_edits_keep_the_heard_voices_when_nothing_was_edited():
    notes = [heard(0.0, 1.0, 72, 1), heard(0.0, 1.0, 67, 2), heard(1.0, 1.0, 74, 1)]
    resolved = edits.resolve({}, payload(notes), (0.0, 2.0), horns=True)
    assert [n["voice"] for n in resolved["audible"]] == [1, 2, 1]


def test_a_note_whose_partner_was_erased_is_written_once_in_voice_1():
    notes = [heard(0.0, 1.0, 72, 1), heard(0.0, 1.0, 67, 2)]
    erasure = {**erasures.record(notes[0], "other", "m"), "view": erasures.HORNS}
    resolved = edits.resolve({"erasures": [erasure]}, payload(notes), (0.0, 2.0), horns=True)
    assert [(n["pitch"], n["voice"]) for n in resolved["audible"]] == [(67, 1)]


def test_a_listener_move_puts_a_note_in_the_other_voice():
    notes = [heard(0.0, 1.0, 72, 1), heard(0.0, 1.0, 67, 2)]
    moves = [{"onset": 0.0, "pitch": 72, "voice": 2}, {"onset": 0.0, "pitch": 67, "voice": 1}]
    resolved = edits.resolve({"voices": moves}, payload(notes), (0.0, 2.0), horns=True)
    assert [(n["pitch"], n["voice"]) for n in resolved["audible"]] == [(72, 2), (67, 1)]
    assert resolved["voices"]["stored"] == 2


def test_a_switched_on_ghost_is_kept_and_given_a_voice():
    notes = [heard(0.0, 1.0, 70, 1)]
    ghost = {"onset": 0.1, "duration": 0.6, "pitch": 82, "confidence": 0.3, "dropped": "ghost"}
    addition = {**erasures.record_addition(ghost, "other", "m"), "view": erasures.HORNS}
    resolved = edits.resolve(
        {"additions": [addition]}, payload(notes, [ghost]), (0.0, 2.0), horns=True
    )
    assert [(n["pitch"], n["voice"]) for n in resolved["added"]] == [(82, 1)]
    assert [(n["pitch"], n["voice"]) for n in resolved["audible"]] == [(70, 2)]


def test_erasures_made_on_the_multi_horn_view_are_carried_on_the_others():
    line = [heard(0.0, 1.0, 72)]
    record = {**erasures.record(line[0], "other", "m"), "view": erasures.HORNS}
    on_line = edits.resolve({"erasures": [record]}, payload(line), (0.0, 2.0))
    assert on_line["erasures"]["silenced"] == []
    assert on_line["erasures"]["carried"] == [record]
    assert on_line["erasures"]["unmatched"] == []
    on_horns = edits.resolve({"erasures": [record]}, payload(line), (0.0, 2.0), horns=True)
    assert on_horns["erasures"]["silenced"] == [0]
    # And the line's own erasures are carried, unresolved, on the horns' view.
    plain = erasures.record(line[0], "other", "m")
    carried = edits.resolve({"erasures": [plain]}, payload(line), (0.0, 2.0), horns=True)
    assert carried["erasures"]["silenced"] == [] and carried["erasures"]["carried"] == [plain]


def test_views_of_stored_records():
    assert erasures.view_of({}) == erasures.LINE
    assert erasures.view_of({"piano_notes": "all"}) == erasures.ALL
    assert erasures.view_of({"view": "horns"}) == erasures.HORNS
    assert erasures.view_of({"view": "nonsense"}) == erasures.LINE


def test_the_review_payload_carries_each_notes_voice_only_for_a_multi_horn_head():
    from swingscribe.gui.review import _payload

    class Frames:
        hop_s = 0.01
        start = 0.0
        f0_midi = [None]
        periodicity = [0.0]
        energy_ok = [False]
        pitch = [None]
        onsets = []
        voiced_fraction = 0.0
        second_voice = []
        candidates = [
            {"onset": 0.1, "duration": 0.3, "pitch": 84, "confidence": 0.31, "dropped": "ghost"}
        ]

    notes = [horn(0.0, 1.0, 72), horn(0.0, 1.0, 67, voice=2)]
    horns = _payload(notes, Frames(), voices=True)
    assert [n["voice"] for n in horns["notes"]] == [1, 2]
    assert horns["candidates"] == [
        {"onset": 0.1, "duration": 0.3, "pitch": 84, "confidence": 0.31, "dropped": "ghost"}
    ]
    plain = _payload(notes, Frames())
    assert all("voice" not in n for n in plain["notes"])


# ── the stage's multi-horn hearing (transcribe._hear_horns) ─────────────────


def test_the_stage_hears_both_horns_and_offers_what_neither_voice_holds(monkeypatch):
    from swingscribe import basic_pitch
    from swingscribe.stages import transcribe

    def fake(whole, rate, region, **decode):
        assert decode == {"onset_threshold": 0.5, "frame_threshold": 0.3, "min_note_ms": 23.0}
        return [
            {"onset": 1.0, "duration": 1.0, "pitch": 70, "confidence": 0.69},
            {"onset": 1.0, "duration": 1.0, "pitch": 74, "confidence": 0.6},
            {"onset": 1.1, "duration": 0.6, "pitch": 82, "confidence": 0.30},
        ]

    monkeypatch.setattr(basic_pitch, "transcribe", fake)
    tc = TranscribeConfig(ensemble="multi-horn", region=(0.0, 3.0))
    notes, candidates = transcribe._hear_horns(None, 44100, tc)
    assert [(n.pitch, n.voice) for n in notes] == [(74, 1), (70, 2)]
    assert all(abs(n.onset - 1.004) < 1e-9 for n in notes)  # Basic Pitch's 4 ms
    assert [(c["pitch"], c["dropped"]) for c in candidates] == [(82, "ghost")]


def test_the_stage_refuses_a_multi_horn_head_without_basic_pitch(monkeypatch):
    from swingscribe import basic_pitch
    from swingscribe.stages import transcribe

    def missing(*args, **kwargs):
        raise ImportError("No module named 'onnxruntime'")

    monkeypatch.setattr(basic_pitch, "transcribe", missing)
    with pytest.raises(RuntimeError, match="onnxruntime"):
        transcribe._hear_horns(None, 44100, TranscribeConfig(ensemble="multi-horn"))


def test_the_roll_gets_every_note_s_voice_and_the_moves_by_its_own_indices():
    notes = [heard(0.0, 1.0, 72, 1), heard(0.0, 1.0, 67, 2), heard(1.0, 1.0, 74, 1)]
    erasure = {**erasures.record(notes[0], "other", "m"), "view": erasures.HORNS}
    move = {"onset": 1.0, "pitch": 74, "voice": 2}
    resolved = edits.resolve(
        {"erasures": [erasure], "voices": [move]}, payload(notes), (0.0, 2.0), horns=True
    )
    # Its partner erased, the lower note is written in voice 1; the erased
    # note keeps the voice it was heard in; a move is the roll's own index.
    assert resolved["note_voices"] == [1, 1, 1]
    assert resolved["voices"]["lower"] == [2]
    assert [(n["pitch"], n["voice"]) for n in resolved["audible"]] == [(67, 1), (74, 2)]


# ── two parts ─────────────────────────────────────────────────────────────────


def test_two_parts_keep_each_horn_s_notes_its_transposition_and_clef():
    beats = grid()
    notes = two_horn_line(beats[4:20], [74, 72], [50, 48])  # trumpet over a low trombone
    region = (beats[4], beats[20])
    page, lines = notation_for_horns(
        "t.wav",
        notes,
        beats,
        region,
        stem="other",
        config=literal_config(),
        anchor=beats[4],
        parts=True,
        lower_transpose=0,
    )
    assert len(page.parts) == 1
    lower = page.parts[0]
    assert [p["moved"] for p in lines.phrases] == [0]  # no octave moved in parts
    assert page.clef == "treble" and lower.clef == "bass"
    assert page.part_name == "Upper" and lower.part_name == "Lower"
    assert [b.number for b in page.bars] == [b.number for b in lower.bars]
    assert {n.pitch for b in lower.bars for n in b.notes if not n.is_rest} == {50, 48}
    assert all(n.voice == 1 for b in lower.bars for n in b.notes)


def test_two_parts_keep_a_unison_in_both():
    beats = grid()
    notes = two_horn_line(beats[4:12], [65], [65])
    region = (beats[4], beats[12])
    page, lines = notation_for_horns(
        "t.wav",
        notes,
        beats,
        region,
        stem="other",
        config=literal_config(),
        anchor=beats[4],
        parts=True,
    )
    assert lines.unisons == 0
    assert any(not n.is_rest for b in page.parts[0].bars for n in b.notes)


def test_two_parts_are_two_musicxml_parts_each_in_its_own_key_and_clef():
    from swingscribe.notation import merge_horn_parts

    upper = Notation(bars=[bar(1, [sound(0, 4, 74)])], transpose=2)
    lower = Notation(bars=[bar(1, [sound(0, 4, 50)])], transpose=2)
    page = merge_horn_parts(upper, lower, key=-2, lower_transpose=0)
    xml = to_musicxml(page, part_name="Head")
    root = ElementTree.fromstring(xml[xml.index("<score-partwise") :])
    names = [p.findtext("part-name") for p in root.find("part-list").findall("score-part")]
    assert names == ["Upper", "Lower"]
    first, second = root.findall("part")
    assert first.find(".//key/fifths").text == "0"  # concert Bb major, a Bb part: C
    assert second.find(".//key/fifths").text == "-2"
    assert first.find(".//clef/sign").text == "G"
    assert second.find(".//clef/sign").text == "F"
    assert first.find(".//transpose") is not None and second.find(".//transpose") is None


def test_two_notes_put_in_one_voice_are_a_chord_in_it():
    beats = grid()
    notes = [horn(t, BEAT * 0.9, 72) for t in beats[4:12]] + [
        horn(t, BEAT * 0.9, 67) for t in beats[4:12]
    ]
    region = (beats[4], beats[12])
    page, _ = notation_for_horns(
        "t.wav", notes, beats, region, stem="other", config=literal_config(), anchor=beats[4]
    )
    struck = [n for b in page.bars for n in b.notes if not n.is_rest and not n.tie_stop]
    assert len(struck) == 8
    assert all(n.pitch == 72 and n.chord == [67] for n in struck)
