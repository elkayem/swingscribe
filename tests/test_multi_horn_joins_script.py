"""scripts/multi_horn_joins.py: the measures at a same-pitch join, on
synthetic posteriorgrams -- a re-attack against a held note split in two."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import multi_horn_joins  # noqa: E402


def note(onset, duration, pitch, voice=1):
    return {"onset": onset, "duration": duration, "pitch": pitch, "voice": voice}


def test_joins_are_touching_pairs_of_one_pitch_in_one_voice():
    notes = [
        note(0.0, 0.5, 60, 2),
        note(0.5, 0.3, 60, 2),  # touching, same pitch, same voice
        note(0.5, 0.3, 60, 1),  # other voice: not a pair with the lower C
        note(1.0, 0.2, 62, 2),  # a gap
        note(1.2, 0.2, 64, 2),  # another pitch
    ]
    pairs = multi_horn_joins.joins(notes)
    assert [(a["onset"], b["onset"]) for a, b in pairs] == [(0.0, 0.5)]


def test_a_re_attack_shows_an_onset_peak_and_a_dip():
    np = pytest.importorskip("numpy")
    frames = 200
    times = np.arange(frames) * 0.0116
    note_post = np.zeros((frames, 88))
    onset_post = np.zeros((frames, 88))
    bin_ = 60 - 21
    note_post[:, bin_] = 0.8
    join = 1.0
    at = int(np.argmin(np.abs(times - join)))
    rate = 1000
    mono = np.full(3000, 0.5)
    first, second = note(0.2, 0.8, 60), note(1.0, 0.8, 60)
    rms, rms_times = multi_horn_joins.short_time_rms(mono, rate)
    held = multi_horn_joins.join_features(
        note_post, onset_post, times, rms, rms_times, first, second
    )
    assert held["onset"] == 0.0 and held["frame_dip"] == 1.0 and held["energy_dip_db"] == 0.0
    # Re-attacked: the model's onset peaks, the frame activation and the
    # stem's level both dip at the join.
    onset_post[at, bin_] = 0.9
    note_post[at - 1 : at + 1, bin_] = 0.2
    mono[980:1010] = 0.05
    rms, rms_times = multi_horn_joins.short_time_rms(mono, rate)
    attacked = multi_horn_joins.join_features(
        note_post, onset_post, times, rms, rms_times, first, second
    )
    assert attacked["onset"] == 0.9
    assert attacked["frame_dip"] == pytest.approx(0.25)
    assert attacked["energy_dip_db"] == pytest.approx(20.0)


def test_the_other_voice_says_whether_rule_5b_takes_the_join():
    first, second = note(0.0, 1.0, 68), note(1.0, 1.0, 68)
    held_over = [first, second, note(0.0, 2.0, 65, 2)]
    assert multi_horn_joins.other_voice(held_over, first, second) == {
        "other_ms": 1000,
        "across": True,
        "attack_near": False,
    }
    together = [first, second, note(0.0, 1.0, 65, 2), note(1.012, 1.0, 65, 2)]
    found = multi_horn_joins.other_voice(together, first, second)
    assert found["attack_near"] and not found["across"] and found["other_ms"] == 12
