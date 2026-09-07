"""Every non-hit gets exactly one class, from a fixed rule table walked in order.

`classify_pair`/`classify_miss`/`classify_fp` are pure Python and are tested
directly here without pairing or matching machinery. `match` (mir_eval) and
`pair_unmatched` (scipy) are exercised separately, each behind its own
`pytest.importorskip`, so the pure-rule tests below stay runnable without the
ml group (CLAUDE.md). One test per class in `RULES`, plus pairing behaviour,
rule ORDER (the cases where two rules could fire and the earlier one must
win), and the aggregation helpers.
"""

import pytest

from swingscribe.taxonomy import (
    ErrorRow,
    Evidence,
    FrameWindow,
    SoloErrors,
    bootstrap_noise,
    class_counts,
    classify_fp,
    classify_miss,
    classify_pair,
    compare_counts,
    f1_deficit,
    family_of,
    paired_delta_noise,
)


def note(onset: float, pitch: int, duration: float = 0.2) -> dict:
    return {"onset": onset, "pitch": pitch, "duration": duration}


class FakeEvidence(Evidence):
    """Answers exactly the questions it is told to; everything else is None,
    same as the base class, so a rule that needs unset evidence is skipped."""

    def __init__(self, frames_=None, stem_rms_=None, cross_stem_ratio_=None, oracle_has_=None):
        self._frames = frames_
        self._stem_rms = stem_rms_
        self._cross_stem_ratio = cross_stem_ratio_
        self._oracle_has = oracle_has_

    def frames(self, t0, t1):
        return self._frames

    def stem_rms(self, t0, t1):
        return self._stem_rms

    def cross_stem_ratio(self, t0, t1, pitch):
        return self._cross_stem_ratio

    def oracle_has(self, t, pitch):
        return self._oracle_has


def _needs_pairing():
    """pair_unmatched needs numpy + scipy but not mir_eval."""
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")


def _needs_full_match():
    """classify_solo (and match) additionally needs mir_eval."""
    pytest.importorskip("numpy")
    pytest.importorskip("mir_eval")
    pytest.importorskip("scipy")


# ── family_of ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", ["ts", "tp", "as", "tb", "ss"])
def test_family_of_horn_codes(code):
    assert family_of(code) == "horn"


def test_family_of_piano():
    assert family_of("p") == "piano"


def test_family_of_guitar():
    assert family_of("g") == "guitar"


def test_family_of_other_for_vib_and_none():
    assert family_of("vib") == "other"
    assert family_of(None) == "other"


# ── classify_pair: one test per pair class ───────────────────────────────


def test_pair_timing_late_same_pitch_our_onset_after():
    row = classify_pair(note(1.0, 60), note(1.08, 60))
    assert row.population == "pair"
    assert row.cls == "timing_late"


def test_pair_timing_early_same_pitch_our_onset_before():
    row = classify_pair(note(1.0, 60), note(0.92, 60))
    assert row.cls == "timing_early"


def test_pair_octave_within_tolerance_twelve_semitones_off():
    row = classify_pair(note(1.0, 60), note(1.02, 72))
    assert row.cls == "octave"


def test_pair_neighbour_within_tolerance_one_or_two_semitones_off():
    row = classify_pair(note(1.0, 60), note(1.02, 61))
    assert row.cls == "neighbour"


def test_pair_other_pitch_within_tolerance_any_other_offset():
    row = classify_pair(note(1.0, 60), note(1.02, 65))
    assert row.cls == "other_pitch"


def test_pair_loose_pitch_differs_and_onsets_far_apart():
    row = classify_pair(note(1.0, 60), note(1.1, 65))
    assert row.cls == "loose"


# ── classify_miss: one test per miss class ─────────────────────────────


def test_miss_merged_same_pitch_note_covers_the_onset():
    ref = [note(5.0, 60, 0.2)]
    est = [note(4.5, 60, 1.0)]  # covers (4.55, 5.65], same pitch
    row = classify_miss(0, ref, est, Evidence(), "horn")
    assert row.population == "miss"
    assert row.cls == "merged"
    assert row.est_index == 0


def test_miss_absorbed_other_pitch_note_covers_the_onset():
    ref = [note(5.0, 60, 0.2)]
    est = [note(4.5, 65, 1.0)]
    row = classify_miss(0, ref, est, Evidence(), "horn")
    assert row.cls == "absorbed"


def test_miss_not_picked_piano_oracle_heard_it():
    ref = [note(3.0, 64, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(oracle_has_=True), "piano")
    assert row.cls == "not_picked"


def test_miss_left_stem_digitally_silent():
    ref = [note(3.0, 64, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(stem_rms_=1e-6), "horn")
    assert row.cls == "left_stem"


def test_miss_gated_no_frame_passes_the_energy_gate():
    fw = FrameWindow(0.01, [0.1] * 5, [False] * 5, [None] * 5, [None] * 5)
    ref = [note(5.0, 60, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(frames_=fw), "horn")
    assert row.cls == "gated"


def test_miss_unvoiced_energetic_but_never_periodic_enough():
    fw = FrameWindow(0.01, [0.3] * 5, [True] * 5, [None] * 5, [None] * 5)
    ref = [note(5.0, 60, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(frames_=fw), "horn")
    assert row.cls == "unvoiced"


def test_miss_too_short_run_at_ref_pitch_below_min_note_ms():
    # hop 0.01s, MIN_NOTE_S=0.06 -> 6 frames needed; only 3 are at the pitch.
    pitch = [60, 60, 60, None, None, None, None, None, None, None]
    fw = FrameWindow(0.01, [0.6] * 10, [True] * 10, pitch, [None] * 10)
    ref = [note(5.0, 60, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(frames_=fw), "horn")
    assert row.cls == "too_short"


def test_miss_dropped_run_survives_gates_no_line_to_compare():
    fw = FrameWindow(0.01, [0.6] * 10, [True] * 10, [60] * 10, [None] * 10)
    ref = [note(5.0, 60, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(frames_=fw), "horn")
    assert row.cls == "dropped"


def test_miss_dropped_register_run_survives_but_under_the_line():
    fw = FrameWindow(0.01, [0.6] * 10, [True] * 10, [60] * 10, [None] * 10)
    ref = [note(5.0, 60, 0.2)]
    # three notes within LINE_WINDOW_S of t=5.0, none covering it, median 80.
    est_line = [note(3.5, 80, 0.1), note(3.7, 80, 0.1), note(3.9, 80, 0.1)]
    row = classify_miss(0, ref, est_line, FakeEvidence(frames_=fw), "horn")
    assert row.cls == "dropped_register"


def test_miss_tracked_octave_live_frames_an_octave_from_reference():
    fw = FrameWindow(0.01, [0.6] * 5, [True] * 5, [None] * 5, [72] * 5)
    ref = [note(5.0, 60, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(frames_=fw), "horn")
    assert row.cls == "tracked_octave"


def test_miss_tracked_other_live_frames_at_some_other_pitch():
    fw = FrameWindow(0.01, [0.6] * 5, [True] * 5, [None] * 5, [65] * 5)
    ref = [note(5.0, 60, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(frames_=fw), "horn")
    assert row.cls == "tracked_other"


def test_miss_unclassified_when_no_evidence_is_available():
    ref = [note(3.0, 64, 0.2)]
    row = classify_miss(0, ref, [], Evidence(), "horn")
    assert row.cls == "unclassified"


# ── classify_fp: one test per false-positive class ──────────────────────


def test_fp_split_sustain_inside_a_same_pitch_reference_note():
    ref = [note(0.5, 60, 1.0)]  # covers (0.55, 1.55]
    est = [note(1.0, 60, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.population == "fp"
    assert row.cls == "split_sustain"


def test_fp_bleed_register_well_under_the_reference_lines_median():
    ref = [note(4.0, 70, 0.1), note(4.5, 70, 0.1), note(4.8, 70, 0.1)]
    est = [note(5.0, 50, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "bleed_register"


def test_fp_bleed_cross_stem_another_stem_carries_the_energy():
    ref = [note(0.0, 60, 0.1)]  # too few notes nearby for a line median
    est = [note(5.0, 50, 0.2)]
    row = classify_fp(0, ref, est, FakeEvidence(cross_stem_ratio_=1.0), "horn")
    assert row.cls == "bleed_cross_stem"


def test_fp_fragment_octave_inside_a_reference_note_octave_off():
    ref = [note(0.5, 60, 1.0)]
    est = [note(1.0, 72, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "fragment_octave"


def test_fp_fragment_neighbour_inside_a_reference_note_a_step_off():
    ref = [note(0.5, 60, 1.0)]
    est = [note(1.0, 61, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "fragment_neighbour"


def test_fp_fragment_other_inside_a_reference_note_some_other_pitch():
    ref = [note(0.5, 60, 1.0)]
    est = [note(1.0, 65, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "fragment_other"


def test_fp_between_phrases_in_a_gap_of_a_second_or_more():
    ref = [note(0.0, 50, 0.1), note(10.0, 50, 0.1)]
    est = [note(5.0, 50, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "between_phrases"


def test_fp_between_notes_in_a_shorter_gap():
    ref = [note(4.8, 50, 0.1), note(5.3, 50, 0.1)]
    est = [note(5.0, 50, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "between_notes"


def test_fp_unclassified_no_reference_notes_at_all():
    row = classify_fp(0, [], [note(5.0, 50, 0.2)], Evidence(), "horn")
    assert row.cls == "unclassified"


# ── rule order: earlier rows in RULES win when two could fire ──────────


def test_order_merged_beats_left_stem():
    """A miss covered by a same-pitch note of ours, in a digitally silent
    stem, is `merged` -- covering evidence is stronger than a gate reading
    over silence, and merged is checked first regardless."""
    ref = [note(5.0, 60, 0.2)]
    est = [note(4.5, 60, 1.0)]
    row = classify_miss(0, ref, est, FakeEvidence(stem_rms_=1e-6), "horn")
    assert row.cls == "merged"


def test_order_not_picked_beats_left_stem():
    """A piano miss the oracle heard is `not_picked` even when the chosen
    stem is also silent -- the oracle answer is checked before stem_rms."""
    ref = [note(3.0, 64, 0.2)]
    row = classify_miss(0, ref, [], FakeEvidence(oracle_has_=True, stem_rms_=1e-6), "piano")
    assert row.cls == "not_picked"


def test_order_split_sustain_beats_bleed_register():
    """A false positive inside a same-pitch reference note that is ALSO 20+
    semitones under the local line is `split_sustain`, not `bleed_register`
    -- split_sustain is checked, and returns, before the register check."""
    ref = [note(4.5, 40, 1.0), note(3.5, 80, 0.1), note(3.7, 80, 0.1)]
    est = [note(5.0, 40, 0.2)]
    row = classify_fp(0, ref, est, Evidence(), "horn")
    assert row.cls == "split_sustain"


# ── f1_deficit ────────────────────────────────────────────────────────────


def test_f1_deficit_shares_sum_to_exactly_one_minus_note_f1():
    rows = [
        ErrorRow("pair", "timing_late", "r", ref_index=1, est_index=1),
        ErrorRow("miss", "dropped", "r", ref_index=2, est_index=None),
        ErrorRow("fp", "between_notes", "r", ref_index=None, est_index=2),
    ]
    solo = SoloErrors(rows=rows, matched=[(0, 0)], pairs=[(1, 1)], n_reference=3, n_estimate=3)
    deficit = f1_deficit(solo)
    assert deficit == {
        "timing_late": pytest.approx(2 / 6),
        "dropped": pytest.approx(1 / 6),
        "between_notes": pytest.approx(1 / 6),
    }
    assert sum(deficit.values()) == pytest.approx(1 - solo.note_f1)


# ── bootstrap_noise ───────────────────────────────────────────────────────


def test_bootstrap_noise_is_deterministic_for_a_seed():
    per_solo = [{"a": 2, "b": 1}, {"a": 2, "b": 5}, {"a": 2, "b": 0}]
    first = bootstrap_noise(per_solo, resamples=200, seed=7)
    second = bootstrap_noise(per_solo, resamples=200, seed=7)
    assert first == second


def test_bootstrap_noise_returns_count_and_share_sd_per_class():
    per_solo = [{"a": 2, "b": 1}, {"a": 2, "b": 5}]
    noise = bootstrap_noise(per_solo, resamples=100, seed=1)
    assert set(noise) == {"a", "b"}
    for cls in noise:
        assert set(noise[cls]) == {"count_sd", "share_sd"}


def test_bootstrap_noise_zero_for_a_class_constant_across_identical_solos():
    """Classification is deterministic, so resampling identical solos never
    produces a different total -- every class's count_sd is exactly 0."""
    per_solo = [{"a": 3, "b": 2}] * 4
    noise = bootstrap_noise(per_solo, resamples=200, seed=0)
    assert noise["a"]["count_sd"] == 0.0
    assert noise["b"]["count_sd"] == 0.0


def test_bootstrap_noise_zero_for_a_class_constant_across_varying_solos():
    """ "a" holds count 2 in every solo even though "b" varies -- only "a"'s
    count_sd is pinned to zero by the resampling."""
    per_solo = [{"a": 2, "b": 1}, {"a": 2, "b": 9}, {"a": 2, "b": 0}]
    noise = bootstrap_noise(per_solo, resamples=500, seed=2)
    assert noise["a"]["count_sd"] == 0.0
    assert noise["b"]["count_sd"] > 0.0


# ── class_counts / compare_counts ────────────────────────────────────────


def test_class_counts_tallies_rows_by_class():
    rows = [
        ErrorRow("pair", "timing_late", "r"),
        ErrorRow("pair", "timing_late", "r"),
        ErrorRow("miss", "dropped", "r"),
    ]
    assert class_counts(rows) == {"timing_late": 2, "dropped": 1}


def test_compare_counts_lists_only_classes_whose_count_changed():
    pinned = {"a": 5, "b": 3, "d": 2}
    current = {"a": 5, "b": 4, "c": 2}
    noise = {"b": {"count_sd": 1.2}, "c": {"count_sd": 0.0}}
    movers = compare_counts(current, pinned, noise)
    # "a" is unchanged and must not appear; "c" appeared, "d" vanished.
    assert movers == [
        ("b", 3, 4, 1.2),
        ("c", 0, 2, 0.0),
        ("d", 2, 0, 0.0),
    ]


# ── pairing (needs numpy + scipy) ─────────────────────────────────────────


def test_pair_prefers_a_same_pitch_partner_over_a_closer_different_pitch():
    _needs_pairing()
    from swingscribe.taxonomy import pair_unmatched

    reference = [note(1.0, 60)]
    estimate = [note(1.08, 60), note(1.04, 61)]  # 80ms same pitch vs 40ms diff pitch
    pairs = pair_unmatched(reference, estimate, [0], [0, 1])
    assert pairs == [(0, 0)]


def test_pair_does_not_pair_a_note_two_hundred_ms_away():
    _needs_pairing()
    from swingscribe.taxonomy import pair_unmatched

    pairs = pair_unmatched([note(0.0, 60)], [note(0.2, 60)], [0], [0])
    assert pairs == []


def test_pairing_is_one_to_one():
    _needs_pairing()
    from swingscribe.taxonomy import pair_unmatched

    reference = [note(0.0, 60), note(0.05, 60)]
    estimate = [note(0.02, 60), note(0.07, 60)]
    pairs = pair_unmatched(reference, estimate, [0, 1], [0, 1])
    assert len(pairs) == 2
    assert {i for i, _ in pairs} == {0, 1}
    assert {j for _, j in pairs} == {0, 1}


# ── classify_solo end to end (needs numpy + mir_eval + scipy) ────────────


def test_pairs_alternative_differ_counts_pairs_the_no_preference_reading_would_change():
    _needs_full_match()
    from swingscribe.taxonomy import classify_solo

    reference = [note(1.0, 60)]
    estimate = [note(1.08, 60), note(1.04, 61)]
    solo = classify_solo(reference, estimate)
    # With the pitch preference: same-pitch (0,0) wins. Without it: (0,1) would.
    assert solo.pairs == [(0, 0)]
    assert solo.pairs_alternative_differ == 1


def test_every_row_has_one_population_and_every_index_used_at_most_once():
    _needs_full_match()
    from swingscribe.taxonomy import classify_solo

    reference = [note(0.0, 60), note(1.0, 62), note(2.0, 64), note(3.0, 66)]
    estimate = [note(0.0, 60), note(1.0, 70), note(2.5, 64)]
    solo = classify_solo(reference, estimate)

    ref_subjects: list[int] = []
    est_subjects: list[int] = []
    for row in solo.rows:
        assert row.population in {"pair", "miss", "fp"}
        if row.population in ("pair", "miss"):
            assert row.ref_index is not None
            ref_subjects.append(row.ref_index)
        if row.population in ("pair", "fp"):
            assert row.est_index is not None
            est_subjects.append(row.est_index)

    assert len(ref_subjects) == len(set(ref_subjects))
    assert len(est_subjects) == len(set(est_subjects))

    matched_ref = {i for i, _ in solo.matched}
    matched_est = {j for _, j in solo.matched}
    assert set(ref_subjects) == set(range(solo.n_reference)) - matched_ref
    assert set(est_subjects) == set(range(solo.n_estimate)) - matched_est


# ── the attack transient: one mechanism, two rows ─────────────────────────
# A scoop into a note is heard as a short note a step under, then the body
# at the right pitch, late. The pair row says `attack_transient`; the body's
# false-positive row is relabelled `body_late` so the two are read together
# rather than as a wrong pitch plus a split sustain.


def test_pair_attack_transient_when_the_body_follows_at_the_reference_pitch():
    ref = note(1.0, 62, 0.5)
    estimate = [note(1.01, 61, 0.08), note(1.09, 62, 0.4)]
    row = classify_pair(ref, estimate[0], estimate)
    assert row.cls == "attack_transient"
    assert row.evidence["body_index"] == 1
    assert row.evidence["body_dt"] == pytest.approx(0.09)


def test_pair_attack_transient_wins_over_neighbour():
    """Same dpitch as a neighbour pair; the body's presence decides."""
    ref = note(1.0, 62, 0.5)
    assert classify_pair(ref, note(1.01, 61, 0.08)).cls == "neighbour"
    assert classify_pair(ref, note(1.01, 61, 0.08), [note(1.01, 61, 0.08)]).cls == "neighbour"
    estimate = [note(1.01, 61, 0.08), note(1.09, 62, 0.4)]
    assert classify_pair(ref, estimate[0], estimate).cls == "attack_transient"


def test_a_body_outside_the_reference_note_is_not_a_transient():
    ref = note(1.0, 62, 0.2)
    estimate = [note(1.01, 61, 0.08), note(1.5, 62, 0.4)]
    assert classify_pair(ref, estimate[0], estimate).cls == "neighbour"


def test_the_body_row_is_relabelled_body_late():
    _needs_full_match()
    from swingscribe.taxonomy import classify_solo

    reference = [note(1.0, 62, 0.5), note(2.0, 64, 0.3)]
    estimate = [note(1.01, 61, 0.08), note(1.09, 62, 0.4), note(2.0, 64, 0.3)]
    solo = classify_solo(reference, estimate)
    classes = {(r.population, r.cls) for r in solo.rows}
    assert ("pair", "attack_transient") in classes
    assert ("fp", "body_late") in classes
    assert ("fp", "split_sustain") not in classes
    body = next(r for r in solo.rows if r.cls == "body_late")
    assert body.evidence["transient_ref_index"] == 0


# ── evidence that rides on every miss, and the gate that has two readings ──


def test_voiced_frames_that_all_fail_the_energy_gate_are_gated():
    """Energetic frames and voiced frames that never coincide: the one row
    the first full run could not place. It is a gate holding the note back,
    so it is `gated`, under its own rule text."""
    frames = FrameWindow(
        hop_s=0.01,
        periodicity=[0.9, 0.9, 0.1, 0.1],
        energy_ok=[False, False, True, True],
        pitch=[None] * 4,
        f0=[60.0] * 4,
    )
    row = classify_miss(0, [note(1.0, 60)], [], FakeEvidence(frames_=frames), "horn")
    assert row.cls == "gated"
    assert "voiced" in row.rule


def test_a_covered_miss_still_carries_its_frame_facts_and_the_oracle_opinion():
    """`absorbed` pre-empts the frame rules, but the second analyst needs to
    know what the frames said anyway — and, for a pianist, whether the
    polyphonic model heard the note."""
    frames = FrameWindow(
        hop_s=0.01, periodicity=[0.9] * 4, energy_ok=[True] * 4, pitch=[62.0] * 4, f0=[62.0] * 4
    )
    reference = [note(1.0, 60)]
    estimate = [note(0.8, 62, 0.5)]
    row = classify_miss(
        0, reference, estimate, FakeEvidence(frames_=frames, oracle_has_=True), "piano"
    )
    assert row.cls == "absorbed"
    assert row.evidence["oracle_heard"] is True
    assert row.evidence["run_at_ref_frames"] == 0
    assert row.evidence["frames"] == 4


def test_a_covered_miss_names_whether_its_coverer_was_matched():
    _needs_full_match()
    from swingscribe.taxonomy import classify_solo

    reference = [note(1.0, 60, 0.1), note(1.1, 62, 0.1)]
    estimate = [note(1.0, 60, 0.3)]
    solo = classify_solo(reference, estimate)
    absorbed = next(r for r in solo.rows if r.cls == "absorbed")
    assert absorbed.evidence["covered_by_matched"] is True
    assert absorbed.evidence["covered_by_duration"] == pytest.approx(0.3)


# ── the second reading: squeezed, no slack for misses, the alignment residual ──


def test_miss_squeezed_when_the_other_pitch_coverer_ends_within_sixty_ms():
    ref = [note(5.0, 60, 0.06)]
    est = [note(4.8, 65, 0.24)]  # ends at 5.04: 40 ms after the missed onset
    row = classify_miss(0, ref, est, Evidence(), "horn")
    assert row.cls == "squeezed"
    assert row.evidence["coverer_remaining"] == pytest.approx(0.04)
    assert row.evidence["covered_by_onset"] == pytest.approx(4.8)


def test_miss_absorbed_needs_sixty_ms_of_coverer_after_the_onset():
    ref = [note(5.0, 60, 0.06)]
    est = [note(4.8, 65, 0.27)]  # ends at 5.07: 70 ms past the missed onset
    assert classify_miss(0, ref, est, Evidence(), "horn").cls == "absorbed"


def test_a_missed_onset_after_our_note_off_is_not_covered():
    """The 50 ms cover slack applies to false positives (a release just past
    a reference note-off), never to misses: an onset past OUR note-off is in a
    gap, and the frame rules read the gap. With no frames it is unclassified,
    not absorbed."""
    ref = [note(5.0, 60, 0.06)]
    est = [note(4.8, 65, 0.19)]  # ends at 4.99, 10 ms before the missed onset
    row = classify_miss(0, ref, est, Evidence(), "horn")
    assert row.cls == "unclassified"
    assert "covered_by_index" not in row.evidence


def test_a_merged_miss_also_needs_the_onset_inside_our_note():
    ref = [note(5.0, 60, 0.06)]
    est = [note(4.8, 60, 0.19)]
    assert classify_miss(0, ref, est, Evidence(), "horn").cls != "merged"


def test_alignment_residual_is_the_local_median_offset_of_the_matched_notes():
    from swingscribe.taxonomy import alignment_residual

    matched = [(t, 0.02) for t in range(0, 11)] + [(t, -0.03) for t in range(20, 30)]
    assert alignment_residual(matched, 5.0) == pytest.approx(0.02)
    assert alignment_residual(matched, 25.0) == pytest.approx(-0.03)
    # fewer than five matches nearby: the solo's median
    assert alignment_residual(matched, 100.0) == pytest.approx(0.02)
    assert alignment_residual([], 1.0) == 0.0


def test_pairs_carry_the_alignment_residual_read_off_the_hits():
    _needs_full_match()
    from swingscribe.taxonomy import classify_solo

    # Six matched notes all 30 ms late, then a same-pitch pair 70 ms late:
    # 40 ms of it is placement once the residual is out.
    reference = [note(float(t), 60 + t, 0.2) for t in range(6)] + [note(10.0, 70, 0.2)]
    estimate = [note(float(t) + 0.03, 60 + t, 0.2) for t in range(6)] + [note(10.07, 70, 0.2)]
    solo = classify_solo(reference, estimate)
    pair = next(r for r in solo.rows if r.population == "pair")
    assert pair.cls == "timing_late"
    assert pair.evidence["align_resid"] == pytest.approx(0.03, abs=1e-3)
    assert pair.evidence["dt_residual"] == pytest.approx(0.04, abs=1e-3)


def test_paired_delta_noise_sees_a_uniform_change_the_sample_sd_cannot():
    """Ten solos with `absorbed` 100 +/- a lot; a fix trims every one by 10.
    The change is inside bootstrap_noise's 2 sd (the sample scale) and far
    beyond the paired se (every solo moved the same way)."""
    before = {f"s{i}": {"absorbed": 100 + 40 * (i % 2)} for i in range(10)}
    after = {name: {"absorbed": c["absorbed"] - 10} for name, c in before.items()}
    sample = bootstrap_noise(list(before.values()), resamples=300)["absorbed"]["count_sd"]
    paired = paired_delta_noise(before, after, resamples=300)["absorbed"]
    assert paired["delta"] == -100
    assert paired["up"] == 0 and paired["down"] == 10 and paired["n_solos"] == 10
    assert paired["se"] == 0.0  # every delta identical: no paired noise at all
    assert abs(paired["delta"]) < 2 * sample  # and yet inside the sample scale


def test_paired_delta_noise_compares_only_solos_present_in_both():
    before = {"a": {"merged": 3}, "b": {"merged": 5}, "gone": {"merged": 9}}
    after = {"a": {"merged": 1}, "b": {"merged": 6}, "new": {"merged": 4}}
    out = paired_delta_noise(before, after, resamples=50)
    assert out["merged"]["n_solos"] == 2
    assert out["merged"]["delta"] == -1
    assert out["merged"]["up"] == 1 and out["merged"]["down"] == 1
    assert paired_delta_noise({}, after) == {}
