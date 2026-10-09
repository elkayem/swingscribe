"""voices.py: which heard note is which horn's, on synthetic note lists."""

import pytest

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


# ── a new chord ends what was sounding (rule 2) ──────────────────────────────


def test_a_tail_ringing_into_the_next_chord_is_cut_there():
    """Bar 26 of the head: the upper horn's F4 rings 100 ms into the next
    chord. Uncut, three sound at once and the least confident -- the next
    chord's own lower note -- is lost as a third."""
    notes = [
        note(0.0, 1.1, 65, 0.8),
        note(0.0, 0.95, 60, 0.7),
        note(1.0, 1.0, 63, 0.7),
        note(1.0, 1.0, 58, 0.5),
    ]
    stats = {}
    kept, dropped = voices.assign(notes, stats=stats)
    assert dropped == []
    assert [(n["onset"], n["pitch"], n["voice"]) for n in kept] == [
        (0.0, 65, 1),
        (0.0, 60, 2),
        (1.0, 63, 1),
        (1.0, 58, 2),
    ]
    assert kept[0]["duration"] == pytest.approx(1.0)
    assert stats["tails"] == 1


def test_a_note_starting_beats_a_note_ending():
    """Bar 28: the upper horn holds C5 from the bar before; the lower moves
    from A-flat to G, the A-flat ringing 150 ms on. Uncut, the three sound at
    once and the G -- the less confident -- is lost as a third."""
    notes = [
        note(0.0, 2.0, 72, 0.8),
        note(0.0, 1.15, 68, 0.7),
        note(1.0, 1.0, 67, 0.63),
    ]
    kept, dropped = voices.assign(notes)
    assert dropped == []
    assert [(n["pitch"], n["voice"]) for n in kept] == [(72, 1), (68, 2), (67, 2)]
    assert kept[1]["duration"] == pytest.approx(1.0)


def test_a_stray_note_shorter_than_both_is_still_the_third():
    # Nothing is ENDING here: the newest note stops first, so the rule
    # leaves it to rule 3, which drops the least confident.
    notes = [note(0.0, 1.0, 72, 0.8), note(0.0, 1.0, 67, 0.7), note(0.3, 0.4, 64, 0.35)]
    kept, dropped = voices.assign(notes)
    assert [(n["pitch"], n["dropped"]) for n in dropped] == [(64, voices.THIRD)]


def test_one_horn_moving_alone_does_not_cut_the_held_note():
    work = [note(0.0, 2.0, 65), note(0.0, 1.0, 60), note(1.0, 0.5, 62), note(1.5, 0.5, 64)]
    assert voices.trim_tails(work, set(range(4))) == 0
    assert work[0]["duration"] == 2.0


def test_a_unison_attack_is_not_a_new_chord():
    work = [note(0.0, 2.0, 65), note(1.0, 0.5, 60), note(1.02, 0.5, 60)]
    assert voices.trim_tails(work, set(range(3))) == 0


def test_trimming_leaves_the_callers_notes_alone():
    notes = [note(0.0, 1.1, 65), note(1.0, 1.0, 63), note(1.0, 1.0, 58)]
    voices.assign(notes)
    assert notes[0]["duration"] == 1.1


# ── a held note Basic Pitch split is joined again (rule 5) ──────────────────


def in_voice(notes, voice=1):
    return [{**n, "voice": voice} for n in notes]


def held_track(pitch, frames=200, hop=0.01):
    return (0.0, hop, [float(pitch)] * frames)


def test_a_split_held_note_is_joined_where_crepe_holds_it():
    # Bar 24's D5: a dotted half re-attacked by Basic Pitch on a stray peak.
    notes = [note(0.0, 0.75, 74), note(0.75, 0.25, 74, 0.9), note(0.0, 1.0, 67)]
    stats = {}
    kept, _ = voices.assign(notes, track=held_track(74), stats=stats)
    upper = [n for n in kept if n["voice"] == 1]
    assert [(n["onset"], n["duration"], n["pitch"]) for n in upper] == [(0.0, 1.0, 74)]
    assert upper[0]["confidence"] == 0.9
    assert stats["rejoined"] == 1


def test_a_split_is_kept_where_crepe_hears_an_attack_or_another_pitch():
    notes = [note(0.0, 0.75, 74), note(0.75, 0.25, 74)]
    assert len(voices.rejoin_splits(in_voice(notes), held_track(74), [0.76])) == 2
    assert len(voices.rejoin_splits(in_voice(notes), held_track(72), [])) == 2
    assert len(voices.rejoin_splits(in_voice(notes), None, [])) == 2
    # A real gap is two notes, whatever CREPE says.
    apart = [note(0.0, 0.6, 74), note(0.75, 0.25, 74)]
    assert len(voices.rejoin_splits(in_voice(apart), held_track(74), [])) == 2


def test_an_unvoiced_frame_at_the_join_joins_nothing():
    start, hop, pitches = held_track(74)
    pitches[74] = None
    notes = in_voice([note(0.0, 0.75, 74), note(0.75, 0.25, 74)])
    assert len(voices.rejoin_splits(notes, (start, hop, pitches), [])) == 2


# ── a lead-in is marked (rule 6) ─────────────────────────────────────────────


def test_a_scoop_into_a_held_note_is_marked_and_made_to_touch_it():
    run = voices.mark_lead_ins([note(0.0, 0.05, 64), note(0.065, 0.6, 65)])
    assert run[0]["lead_in"] is True
    assert run[0]["duration"] == pytest.approx(0.065)
    assert "lead_in" not in run[1]


def test_a_re_attack_head_is_marked():
    run = voices.mark_lead_ins([note(0.0, 0.06, 65), note(0.06, 0.5, 65)])
    assert run[0].get("lead_in") is True


def test_a_run_of_sixteenths_is_not_a_chain_of_lead_ins():
    # Chromatic or repeated, 60 ms apiece at 250 bpm: each note is a note.
    for pitches in ([60, 61, 62, 63], [65, 65, 65, 65]):
        run = voices.mark_lead_ins([note(i * 0.06, 0.06, p) for i, p in enumerate(pitches)])
        assert not any(n.get("lead_in") for n in run), pitches


def test_a_lead_in_is_a_semitone_under_or_the_same_pitch_and_touching():
    assert not voices.mark_lead_ins([note(0.0, 0.06, 63), note(0.06, 0.5, 65)])[0].get("lead_in")
    assert not voices.mark_lead_ins([note(0.0, 0.06, 66), note(0.06, 0.5, 65)])[0].get("lead_in")
    assert not voices.mark_lead_ins([note(0.0, 0.06, 64), note(0.12, 0.5, 65)])[0].get("lead_in")
    assert not voices.mark_lead_ins([note(0.0, 0.15, 64), note(0.15, 0.6, 65)])[0].get("lead_in")


def test_both_horns_scoop_into_a_chord_each_in_its_own_voice():
    # Bar 23 opens with both horns scooping a semitone into a held chord.
    notes = [
        note(0.0, 0.06, 64),
        note(0.0, 0.06, 59),
        note(0.06, 0.94, 65),
        note(0.06, 0.94, 60),
    ]
    stats = {}
    kept, dropped = voices.assign(notes, stats=stats)
    assert dropped == []
    marks = {(n["pitch"], n["voice"]): bool(n.get("lead_in")) for n in kept}
    assert marks == {(64, 1): True, (59, 2): True, (65, 1): False, (60, 2): False}
    assert stats["lead_ins"] == 2
