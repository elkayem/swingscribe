"""Cross-detector corroboration: telling an invented note from an unwanted one.

Pure numpy over note dicts, so all of it runs in CI without the ml group.
"""

from swingscribe.corroborate import apply, corroborate, second_voice, snap_octaves


def note(onset: float, pitch: int, duration: float = 0.2) -> dict:
    return {"onset": onset, "pitch": pitch, "duration": duration, "confidence": 0.8}


# ── corroborate ──────────────────────────────────────────────────────────


def test_a_note_both_detectors_report_is_corroborated():
    ours = [note(1.0, 60)]
    assert list(corroborate(ours, [note(1.02, 60)])) == [True]


def test_a_note_only_we_report_is_not():
    """The Orbits case: CREPE follows the bass through stem bleed and the
    piano model, correctly, does not call a double bass a piano."""
    assert list(corroborate([note(1.0, 43)], [note(1.0, 60)])) == [False]


def test_agreement_must_be_on_the_same_pitch_not_the_same_octave():
    """An octave disagreement is a real disagreement. Waving it through here
    would hide exactly the error `snap_octaves` exists to fix."""
    assert list(corroborate([note(1.0, 60)], [note(1.0, 72)])) == [False]


def test_agreement_must_be_near_in_time():
    assert list(corroborate([note(1.0, 60)], [note(2.0, 60)], onset_tolerance=0.1)) == [False]
    assert list(corroborate([note(1.0, 60)], [note(1.08, 60)], onset_tolerance=0.1)) == [True]


def test_an_empty_oracle_vouches_for_nothing():
    """Not for everything. A missing second opinion is not agreement, and the
    caller has to be able to tell those apart."""
    assert list(corroborate([note(1.0, 60), note(2.0, 62)], [])) == [False, False]


def test_no_notes_is_not_an_error():
    assert list(corroborate([], [note(1.0, 60)])) == []


# ── snap_octaves ─────────────────────────────────────────────────────────


def test_an_octave_error_is_moved_onto_the_oracle():
    ours = [note(1.0, 48)]
    assert [n["pitch"] for n in snap_octaves(ours, [note(1.0, 60)])] == [60]


def test_snapping_prefers_the_nearest_octave():
    ours = [note(1.0, 60)]
    got = snap_octaves(ours, [note(1.0, 84), note(1.0, 72)])
    assert [n["pitch"] for n in got] == [72]


def test_a_note_the_oracle_agrees_with_is_left_alone():
    ours = [note(1.0, 60)]
    got = snap_octaves(ours, [note(1.0, 60), note(1.0, 72)])
    assert [n["pitch"] for n in got] == [60]


def test_a_different_pitch_class_is_never_snapped():
    """Snapping is an octave correction, not a nearest-neighbour rewrite. A
    wrong note must stay wrong so corroboration can reject it."""
    ours = [note(1.0, 61)]
    assert [n["pitch"] for n in snap_octaves(ours, [note(1.0, 72)])] == [61]


def test_snapping_never_rejects():
    """It only corrects. Rejection is a separate decision with a separate
    measured effect — snapping raises recall, corroboration raises precision."""
    ours = [note(1.0, 60), note(5.0, 65)]
    assert len(snap_octaves(ours, [note(1.0, 72)])) == 2


def test_snapping_preserves_everything_but_the_pitch():
    ours = [{"onset": 1.0, "pitch": 48, "duration": 0.4, "confidence": 0.63}]
    got = snap_octaves(ours, [note(1.0, 60)])[0]
    assert got == {"onset": 1.0, "pitch": 60, "duration": 0.4, "confidence": 0.63}


# ── apply ────────────────────────────────────────────────────────────────


def test_apply_snaps_before_it_rejects():
    """A note at the wrong octave should get the chance to be corrected rather
    than thrown away — that ordering beat rejecting alone on both precision
    and recall over both piano solos."""
    ours = [note(1.0, 48)]
    kept, stats = apply(ours, [note(1.0, 60)])
    assert [n["pitch"] for n in kept] == [60]
    assert stats == {"input": 1, "octaves_snapped": 1, "uncorroborated": 0, "kept": 1}


def test_apply_drops_what_the_oracle_will_not_vouch_for():
    ours = [note(1.0, 60), note(2.0, 43)]
    kept, stats = apply(ours, [note(1.0, 60)])
    assert [n["pitch"] for n in kept] == [60]
    assert stats["uncorroborated"] == 1
    assert stats["kept"] == 1


def test_apply_can_report_without_rejecting():
    """The diagnostic use: count what is uncorroborated, change nothing. This
    is how the benchmark splits `invented` from `real but not the solo`."""
    ours = [note(1.0, 60), note(2.0, 43)]
    kept, stats = apply(ours, [note(1.0, 60)], reject=False)
    assert len(kept) == 2
    assert stats["uncorroborated"] == 1


def test_apply_with_no_oracle_keeps_everything_when_not_rejecting():
    ours = [note(1.0, 60), note(2.0, 62)]
    kept, stats = apply(ours, [], reject=False)
    assert len(kept) == 2
    assert stats["uncorroborated"] == 2


def test_apply_with_no_oracle_and_rejection_would_empty_the_line():
    """Documented rather than special-cased: a caller that has no oracle must
    not ask for rejection. `transcribe` checks for this before calling."""
    kept, _ = apply([note(1.0, 60)], [], reject=True)
    assert kept == []


def test_snapping_can_be_turned_off():
    ours = [note(1.0, 48)]
    kept, stats = apply(ours, [note(1.0, 60)], snap=False)
    assert kept == []
    assert stats["octaves_snapped"] == 0


def test_device_auto_is_resolved_before_it_reaches_the_model():
    """`auto` is a swingscribe convention, not a torch one. Passing it through
    reaches torch.load as a map_location and fails with a message about
    storage tags that says nothing about the real problem."""
    from swingscribe.device import resolve_device

    assert resolve_device("auto", cuda_available=False) == "cpu"
    assert resolve_device("auto", cuda_available=True) == "cuda"


def test_second_voice_takes_the_top_two_of_each_simultaneity():
    """A four-note chord contributes its top two, not all four."""
    oracle = [note(1.0, p) for p in (48, 55, 64, 72)]
    got = second_voice([], oracle)
    assert sorted(n["pitch"] for n in got) == [64, 72]


def test_second_voice_leaves_out_what_is_already_on_screen():
    oracle = [note(1.0, 72), note(1.0, 64)]
    ours = [note(1.0, 72)]
    got = second_voice(ours, oracle)
    assert [n["pitch"] for n in got] == [64]


def test_second_voice_offers_the_note_ABOVE_ours_when_ours_is_low():
    """The case that most needs this: we tracked an inner voice an octave under
    the melody (D8), so the note worth showing is above ours, not below."""
    oracle = [note(2.0, 60), note(2.0, 72)]  # ours, and the melody above it
    ours = [note(2.0, 60)]
    assert [n["pitch"] for n in second_voice(ours, oracle)] == [72]


def test_second_voice_separates_clusters_by_onset():
    oracle = [note(1.00, 72), note(1.01, 64), note(3.00, 71), note(3.01, 62)]
    got = second_voice([], oracle)
    # Both pairs survive, and each note keeps its OWN onset -- clustering
    # decides what is simultaneous, it does not quantize anything.
    assert sorted((round(n["onset"], 2), n["pitch"]) for n in got) == [
        (1.0, 72),
        (1.01, 64),
        (3.0, 71),
        (3.01, 62),
    ]


def test_second_voice_is_empty_without_an_oracle():
    assert second_voice([note(1.0, 60)], []) == []
