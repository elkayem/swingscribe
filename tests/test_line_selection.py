"""Melodic-line selection over the piano model's output (issue #8).

Pure Python over note dicts, so all of it runs in CI without the ml group.
"""

from swingscribe.line_selection import (
    clusters_of,
    normalize_velocities,
    pick_from_clusters,
    pick_line,
)


def note(onset: float, pitch: int, velocity: int, duration: float = 0.2) -> dict:
    return {"onset": onset, "pitch": pitch, "velocity": velocity, "duration": duration}


# ── normalisation ─────────────────────────────────────────────────────────


def test_velocities_become_within_track_percentile_ranks():
    """Absolute MIDI velocities do not transfer between recordings; the rank
    within THIS performance is what the picker reads."""
    ranked = normalize_velocities([note(0, 60, 40), note(1, 62, 80), note(2, 64, 120)])
    assert [n["velocity"] for n in ranked] == [0.0, 0.5, 1.0]


def test_a_single_note_ranks_at_the_bottom_not_a_division_by_zero():
    assert normalize_velocities([note(0, 60, 90)])[0]["velocity"] == 0.0


def test_tied_velocities_share_a_rank():
    ranked = normalize_velocities([note(0, 60, 80), note(1, 62, 80), note(2, 64, 100)])
    assert ranked[0]["velocity"] == ranked[1]["velocity"]


# ── clustering ────────────────────────────────────────────────────────────


def test_notes_struck_together_form_one_cluster():
    chord = [note(1.00, 60, 80), note(1.02, 64, 70), note(1.04, 67, 60)]
    later = note(1.30, 72, 90)
    clusters = clusters_of([later, *chord])
    assert [len(c) for c in clusters] == [3, 1]
    assert clusters[1][0] is later


def test_the_gap_is_measured_from_the_cluster_start_so_a_roll_cannot_chain():
    """Three notes each 40 ms apart span 80 ms: a rolled chord is one
    cluster, but a chain of near-neighbours must not swallow the next beat."""
    clusters = clusters_of([note(1.00, 60, 80), note(1.04, 64, 80), note(1.08, 67, 80)])
    assert [len(c) for c in clusters] == [2, 1]


# ── the sequence picker ───────────────────────────────────────────────────


def test_the_loudest_note_wins_a_lone_cluster():
    clusters = [[{"pitch": 60, "velocity": 0.3}, {"pitch": 72, "velocity": 0.9}]]
    assert [n["pitch"] for n in pick_from_clusters(clusters)] == [72]


def test_continuity_prefers_the_register_the_line_is_already_in():
    """A melody note slightly quieter than a left-hand note two octaves down
    is still the melody: the leap costs more than the loudness buys."""
    clusters = [
        [{"pitch": 72, "velocity": 0.9}],
        [{"pitch": 74, "velocity": 0.70}, {"pitch": 45, "velocity": 0.80}],
    ]
    assert [n["pitch"] for n in pick_from_clusters(clusters)] == [72, 74]


def test_a_quiet_comp_between_phrases_emits_nothing():
    """The skip state: a cluster whose best note ranks under the margin is
    silence, not a forced pick. A one-note-per-cluster line gets dragged
    through the comping."""
    clusters = [
        [{"pitch": 72, "velocity": 0.9}],
        [{"pitch": 48, "velocity": 0.05}, {"pitch": 52, "velocity": 0.02}],
        [{"pitch": 74, "velocity": 0.8}],
    ]
    assert [n["pitch"] for n in pick_from_clusters(clusters)] == [72, 74]


def test_a_leap_costs_no_more_than_an_octave():
    """A phrase can start anywhere: after the cap a two-octave leap prices
    like a one-octave leap, so a loud new phrase is not refused for distance."""
    near = [[{"pitch": 60, "velocity": 0.9}], [{"pitch": 72, "velocity": 0.5}]]
    far = [[{"pitch": 60, "velocity": 0.9}], [{"pitch": 96, "velocity": 0.5}]]
    assert [n["pitch"] for n in pick_from_clusters(near)] == [60, 72]
    assert [n["pitch"] for n in pick_from_clusters(far)] == [60, 96]


def test_empty_input_picks_nothing():
    assert pick_from_clusters([]) == []
    assert pick_line([]) == []


# ── end to end ────────────────────────────────────────────────────────────


def test_pick_line_returns_line_notes_with_the_rank_as_confidence():
    """The review screen shades a note by confidence; for a picked note that
    is how loud it was within this performance — the cue the picker used."""
    oracle = [
        note(1.0, 72, 100),
        note(1.0, 48, 60),
        note(1.5, 74, 90),
        note(1.5, 50, 40),
    ]
    line = pick_line(oracle)
    assert [n["pitch"] for n in line] == [72, 74]
    assert line[0]["confidence"] == 1.0
    assert set(line[0]) == {"onset", "duration", "pitch", "confidence"}


def test_pick_line_is_one_note_per_simultaneity():
    """Two notes on one grid position are one note in a single-line score."""
    chord = [note(1.0, 60, 90), note(1.01, 64, 100), note(1.02, 67, 110)]
    assert [n["pitch"] for n in pick_line(chord)] == [67]


def test_a_note_ranked_at_the_floor_is_silence():
    """Ranks are within-track, so the quietest note of a performance ranks
    0.0 and cannot beat the skip margin on its own. A one-note or
    all-equal input therefore picks nothing — a degenerate case no solo
    reaches, recorded here so the behaviour is deliberate, not a surprise."""
    assert pick_line([note(1.0, 72, 90)]) == []
    assert pick_line([note(1.0, 60, 90), note(1.01, 64, 90)]) == []
