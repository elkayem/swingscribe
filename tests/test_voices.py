"""voices.py: which heard note is which horn's, on synthetic note lists."""

from swingscribe import voices


def note(onset, duration, pitch, confidence=0.7):
    return {"onset": onset, "duration": duration, "pitch": pitch, "confidence": confidence}


def by_pitch(notes):
    return {n["pitch"]: n.get("voice") for n in notes}


def test_two_held_notes_are_ordered_by_pitch():
    kept, dropped = voices.assign([note(0.0, 1.0, 62), note(0.0, 1.0, 70)])
    assert dropped == []
    assert by_pitch(kept) == {70: 1, 62: 2}


def test_a_note_alone_is_the_upper_voice_so_it_is_written_once():
    kept, _ = voices.assign([note(0.0, 0.5, 60), note(1.0, 0.5, 72), note(2.0, 0.5, 48)])
    assert [n["voice"] for n in kept] == [1, 1, 1]


def test_an_overtone_ghost_inside_a_louder_note_is_dropped():
    # Bb5 0.30 over Bb4 0.69, the Open Sesame head's own example.
    kept, dropped = voices.assign([note(0.0, 1.0, 70, 0.69), note(0.1, 0.6, 82, 0.30)])
    assert [n["pitch"] for n in kept] == [70]
    assert kept[0]["voice"] == 1
    assert [(n["pitch"], n["dropped"]) for n in dropped] == [(82, voices.GHOST)]


def test_every_overtone_interval_the_listener_named_is_a_ghost():
    for interval in (12, 19, 24, 28):
        kept, dropped = voices.assign(
            [note(0.0, 1.0, 60, 0.7), note(0.2, 0.5, 60 + interval, 0.25)]
        )
        assert [n["pitch"] for n in dropped] == [60 + interval], interval


def test_a_confident_note_an_octave_up_is_a_horn_not_a_ghost():
    # Clearly lower confidence is the test: an octave doubling played out
    # stays two notes, and the page decides how to write it.
    kept, dropped = voices.assign([note(0.0, 1.0, 60, 0.7), note(0.0, 1.0, 72, 0.6)])
    assert dropped == []
    assert by_pitch(kept) == {72: 1, 60: 2}


def test_a_quiet_note_a_third_up_is_not_a_ghost():
    kept, dropped = voices.assign([note(0.0, 1.0, 60, 0.8), note(0.0, 1.0, 64, 0.2)])
    assert dropped == []
    assert by_pitch(kept) == {64: 1, 60: 2}


def test_a_ghost_must_live_inside_its_fundamental():
    # Only the last 0.1 s of a 1 s note at the octave overlaps: a new note.
    kept, dropped = voices.assign([note(0.0, 0.5, 60, 0.8), note(0.4, 1.0, 72, 0.3)])
    assert dropped == []


def test_where_three_sound_at_once_the_two_most_confident_stay():
    kept, dropped = voices.assign(
        [note(0.0, 1.0, 72, 0.8), note(0.0, 1.0, 67, 0.7), note(0.1, 0.8, 64, 0.35)]
    )
    assert [(n["pitch"], n["dropped"]) for n in dropped] == [(64, voices.THIRD)]
    assert by_pitch(kept) == {72: 1, 67: 2}


def test_a_release_tail_is_not_a_third_horn():
    # The lower horn's first note rings 30 ms into its next under a held
    # upper note: three notes overlap, but never meaningfully all at once.
    notes = [note(0.0, 2.0, 72), note(0.0, 0.53, 64), note(0.5, 0.5, 65)]
    kept, dropped = voices.assign(notes)
    assert dropped == []
    assert [(n["pitch"], n["voice"]) for n in kept] == [(72, 1), (64, 2), (65, 2)]


def test_the_lower_voice_moving_under_a_held_upper_note():
    # Bar 25 of the bridge: upper F4 whole note, lower C4 half, C4, C4.
    notes = [note(0.0, 2.0, 65), note(0.0, 1.0, 60), note(1.0, 0.5, 60), note(1.5, 0.5, 60)]
    kept, _ = voices.assign(notes)
    assert [(n["onset"], n["pitch"], n["voice"]) for n in kept] == [
        (0.0, 65, 1),
        (0.0, 60, 2),
        (1.0, 60, 2),
        (1.5, 60, 2),
    ]


def test_the_upper_voice_moving_over_a_held_lower_note():
    # Bar 28: upper C5 dotted quarter, eighth, quarter, quarter; lower G4 half
    # then held on.
    notes = [
        note(0.0, 0.75, 72),
        note(0.75, 0.25, 72),
        note(1.0, 0.5, 70),
        note(1.5, 0.5, 72),
        note(0.0, 2.0, 67),
    ]
    kept, _ = voices.assign(notes)
    assert {(n["onset"], n["pitch"]): n["voice"] for n in kept} == {
        (0.0, 72): 1,
        (0.75, 72): 1,
        (1.0, 70): 1,
        (1.5, 72): 1,
        (0.0, 67): 2,
    }


def test_a_brief_crossing_keeps_each_horn_in_its_voice():
    # The lower horn steps above the held upper note for one short note:
    # continuity through the held note keeps it in voice 2 -- the overlaps
    # either side outvote it.
    notes = [
        note(0.0, 3.0, 67),  # upper horn holds G4
        note(0.0, 1.0, 60),
        note(1.0, 0.3, 69),  # lower horn crosses above, briefly
        note(1.3, 1.7, 62),
    ]
    kept, _ = voices.assign(notes)
    assert {n["pitch"]: n["voice"] for n in kept} == {67: 1, 60: 2, 69: 2, 62: 2}


def test_order_keeps_every_note_even_three_at_once():
    notes = [note(0.0, 1.0, 72), note(0.0, 1.0, 67), note(0.0, 1.0, 64)]
    assert sorted(voices.order(notes)) in ([1, 1, 2], [1, 2, 2])
    assert voices.order(notes)[0] == 1


def test_assign_copies_and_sorts():
    notes = [note(1.0, 0.5, 60), note(0.0, 0.5, 64)]
    kept, _ = voices.assign(notes)
    assert [n["onset"] for n in kept] == [0.0, 1.0]
    assert "voice" not in notes[0]


def test_meaningful_overlap_is_60_ms_or_30_percent_of_the_shorter():
    assert voices.meaningful(note(0.0, 1.0, 60), note(0.94, 1.0, 64))  # 60 ms
    assert not voices.meaningful(note(0.0, 1.0, 60), note(0.95, 1.0, 64))  # 50 ms
    assert voices.meaningful(note(0.0, 1.0, 60), note(0.96, 0.1, 64))  # 40% of 0.1
