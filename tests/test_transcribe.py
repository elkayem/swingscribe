"""Transcribe stage. Segmentation/gating/octave helpers are pure and run in
CI; the CREPE melody-recovery tests need the ml group and skip without it."""

import statistics

import pytest

from swingscribe.config import Config, TranscribeConfig
from swingscribe.model import NoteEvent
from swingscribe.stages.transcribe import (
    fill_short_gaps,
    fold_octave_outliers,
    hz_to_midi,
    median_smooth,
    segment_notes,
)

HOP = 0.01  # 10ms frames in these tests


def seg(pitches, confidences=None, onsets=(), min_note_s=0.05, persist=6, max_gap=4):
    confidences = confidences or [0.9] * len(pitches)
    return segment_notes(
        pitches,
        confidences,
        set(onsets),
        hop_s=HOP,
        min_note_s=min_note_s,
        persist_frames=persist,
        max_gap_frames=max_gap,
        source="test",
    )


def test_hz_to_midi():
    assert round(hz_to_midi(440.0)) == 69
    assert round(hz_to_midi(220.0)) == 57
    assert abs(hz_to_midi(466.16) - 70.0) < 0.01


def test_steady_pitch_is_one_note():
    notes = seg([60.0] * 50)
    assert len(notes) == 1
    assert notes[0].pitch == 60
    assert abs(notes[0].duration - 0.5) < 1e-9


def test_vibrato_does_not_split():
    # ±0.45 semitone wobble crossing the rounding boundary every few frames
    pitches = [60.0 + (0.45 if i % 6 < 3 else -0.45) for i in range(60)]
    notes = seg(pitches)
    assert len(notes) == 1
    assert notes[0].pitch == 60


def test_scoop_into_note_is_a_transition_not_a_note():
    # rise from 57 → 62 over 50ms, then hold 62: the scoop frames never
    # persist, so they fold into the target note
    scoop = [57.0, 58.0, 59.0, 60.0, 61.0]
    pitches = scoop + [62.0] * 60
    notes = seg(pitches)
    assert len(notes) == 1
    assert notes[0].pitch == 62


def test_persistent_pitch_change_splits():
    pitches = [60.0] * 30 + [64.0] * 30
    notes = seg(pitches)
    assert [n.pitch for n in notes] == [60, 64]
    assert abs(notes[1].onset - 0.30) < 1e-9


def test_silence_gap_splits_phrases():
    pitches = [60.0] * 30 + [None] * 20 + [60.0] * 30  # 200ms rest
    notes = seg(pitches)
    assert len(notes) == 2


def test_short_dropout_bridges():
    pitches = [60.0] * 30 + [None] * 3 + [60.0] * 30  # 30ms breath flutter
    notes = seg(pitches)
    assert len(notes) == 1


def test_onset_splits_repeated_notes():
    # same pitch re-articulated: only the onset can split it
    pitches = [60.0] * 60
    notes = seg(pitches, onsets={30})
    assert len(notes) == 2
    assert all(n.pitch == 60 for n in notes)


def test_specks_are_dropped():
    pitches = [None] * 10 + [60.0] * 3 + [None] * 10  # 30ms blip
    assert seg(pitches) == []


def test_unvoiced_low_confidence_never_transcribes():
    # gating happens upstream (caller passes None); all-None yields nothing
    assert seg([None] * 100) == []


def test_median_smooth_flattens_single_frame_spike():
    pitches = [60.0] * 5 + [72.0] + [60.0] * 5  # one-frame octave glitch
    smoothed = median_smooth(pitches, 5)
    assert all(p == 60.0 for p in smoothed)


def test_median_smooth_preserves_none():
    assert median_smooth([None, 60.0, None], 3) == [None, 60.0, None]


def test_fill_short_gaps_only_bridges_interior():
    assert fill_short_gaps([None, None, 60.0], 4) == [None, None, 60.0]
    assert fill_short_gaps([60.0, None, None, 61.0], 4) == [60.0, 60.0, 60.0, 61.0]
    assert fill_short_gaps([60.0, *([None] * 9), 61.0], 4)[1] is None


def note(pitch, onset=0.0):
    return NoteEvent(onset=onset, duration=0.2, pitch=pitch, confidence=0.9, source="test")


def test_fold_octave_outliers():
    notes = [note(60), note(61), note(73), note(62), note(60)]  # 73 is 61+12
    folded = fold_octave_outliers(notes)
    assert [n.pitch for n in folded] == [60, 61, 61, 62, 60]


def test_fold_octave_outliers_leaves_genuine_leaps():
    notes = [note(60), note(67), note(60)]  # a fifth is a leap, not an error
    assert [n.pitch for n in fold_octave_outliers(notes)] == [60, 67, 60]


def test_crop_region_none_is_whole_signal():
    from swingscribe.stages.transcribe import crop_region

    mono = list(range(1000))
    cropped, offset = crop_region(mono, 100, None)
    assert cropped is mono
    assert offset == 0.0


"""crop_region only slices and measures, so a plain list exercises it exactly
as an ndarray does — and unlike an ndarray it runs in CI, which installs
neither numpy nor the rest of the ml group."""


def test_crop_region_slices_and_reports_offset():
    from swingscribe.stages.transcribe import crop_region

    mono = list(range(1000))  # 10s at 100Hz
    cropped, offset = crop_region(mono, 100, (2.0, 5.0))
    assert len(cropped) == 300
    assert offset == 2.0
    assert cropped[0] == 200


def test_crop_region_open_ended():
    from swingscribe.stages.transcribe import crop_region

    mono = list(range(1000))
    cropped, offset = crop_region(mono, 100, (7.0, None))  # to the end
    assert len(cropped) == 300
    assert offset == 7.0


def test_crop_region_clamps_past_end():
    from swingscribe.stages.transcribe import crop_region

    mono = list(range(1000))
    cropped, _ = crop_region(mono, 100, (8.0, 99.0))
    assert len(cropped) == 200


def test_crop_region_rejects_inverted():
    import pytest as _pytest

    from swingscribe.stages.transcribe import crop_region

    with _pytest.raises(ValueError):
        crop_region(list(range(1000)), 100, (5.0, 2.0))


def test_offset_notes_restores_whole_track_time():
    from swingscribe.stages.transcribe import offset_notes

    notes = [note(60, onset=1.0), note(62, onset=2.0)]
    shifted = offset_notes(notes, 90.0)
    assert [n.onset for n in shifted] == [91.0, 92.0]
    assert [n.pitch for n in shifted] == [60, 62]  # nothing else changes


def test_offset_notes_zero_is_identity():
    from swingscribe.stages.transcribe import offset_notes

    notes = [note(60, onset=1.0)]
    assert offset_notes(notes, 0.0) is notes


def test_corroborate_keeps_onset_with_harmonic_attack():
    from swingscribe.stages.transcribe import corroborate_onsets

    # flat, then a clear rise at frame 10 in the note's own harmonics
    energy = [1.0] * 10 + [4.0] * 10
    pitch = [60.0] * 20
    assert corroborate_onsets({10}, energy, pitch, rise_db=3.0, window=5) == {10}


def test_corroborate_drops_onset_without_harmonic_attack():
    # The open-issue #1 case: a transient exists (broadband flux found it) but
    # the held note's own harmonics carry straight through it unchanged.
    from swingscribe.stages.transcribe import corroborate_onsets

    energy = [1.0] * 20
    pitch = [60.0] * 20
    assert corroborate_onsets({10}, energy, pitch, rise_db=3.0, window=5) == set()


def test_corroborate_keeps_onsets_outside_voiced_runs():
    from swingscribe.stages.transcribe import corroborate_onsets

    energy = [0.0] * 20
    pitch: list[float | None] = [None] * 20
    assert corroborate_onsets({10}, energy, pitch, rise_db=3.0, window=5) == {10}


def test_corroborate_disabled_by_zero_threshold():
    from swingscribe.stages.transcribe import corroborate_onsets

    energy = [1.0] * 20
    pitch = [60.0] * 20
    assert corroborate_onsets({5, 10}, energy, pitch, rise_db=0.0, window=5) == {5, 10}


def test_harmonic_energy_follows_the_tracked_pitch():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import harmonic_energy

    rate, hop = 16000, 160
    t = numpy.arange(rate) / rate
    tone = numpy.sin(2 * numpy.pi * 440.0 * t).astype("float32")  # A4 = MIDI 69

    # measured at the pitch that is actually sounding → strong
    on_pitch = harmonic_energy(tone, rate, [69.0] * 50, hop)
    # measured a tritone away → weak, because those bins are empty
    off_pitch = harmonic_energy(tone, rate, [63.0] * 50, hop)
    assert statistics.median(on_pitch[10:40]) > 10 * statistics.median(off_pitch[10:40])


def test_harmonic_energy_is_zero_where_unpitched():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import harmonic_energy

    tone = numpy.sin(2 * numpy.pi * 440.0 * numpy.arange(16000) / 16000).astype("float32")
    energy = harmonic_energy(tone, 16000, [None] * 50, 160)
    assert energy == [0.0] * 50


def test_held_note_survives_a_foreign_transient(tmp_path):
    """End-to-end open-issue #1: a held tone plus an unrelated percussive hit
    must stay ONE note. Previously the hit split it."""
    pytest.importorskip("torch", reason="ml dependency group not installed")
    import numpy as np
    import soundfile

    from swingscribe.config import Config
    from swingscribe.stages import transcribe

    rate = 16000
    duration = 2.0
    t = np.arange(int(rate * duration)) / rate
    # a steady tenor-ish tone with a couple of harmonics
    tone = (
        0.5 * np.sin(2 * np.pi * 220.0 * t)
        + 0.2 * np.sin(2 * np.pi * 440.0 * t)
        + 0.1 * np.sin(2 * np.pi * 660.0 * t)
    )
    tone *= np.minimum(1.0, t * 40)  # brief fade-in, then held
    # a foreign transient at 1.0s: broadband noise burst, nothing at 220Hz
    rng = np.random.default_rng(0)
    hit = np.zeros_like(tone)
    start = int(1.0 * rate)
    burst = rng.standard_normal(int(0.05 * rate))
    burst *= np.exp(-np.arange(len(burst)) / (0.01 * rate))
    hp = np.diff(burst, prepend=0.0)  # crude high-pass: no 220Hz content
    hit[start : start + len(hp)] = hp * 0.6
    signal = (tone + hit).astype("float32")

    stem = tmp_path / "other.wav"
    soundfile.write(str(stem), signal, rate)

    config = Config(cache_dir=tmp_path / "cache")
    notes, _diag = transcribe.analyze(str(stem), config.transcribe)
    held = [n for n in notes if n.duration > 0.3]
    assert len(held) == 1, f"held note was split into {[(n.onset, n.pitch) for n in notes]}"
    assert held[0].pitch == 57  # A3


def test_pick_peaks_finds_separated_maxima():
    from swingscribe.stages.transcribe import pick_peaks

    strength = [0.0] * 50
    strength[10] = 1.0
    strength[12] = 0.9  # too close to 10 — suppressed
    strength[30] = 0.8
    assert pick_peaks(strength, min_separation=5, window=10, delta=0.1) == [10, 30]


def test_pick_peaks_ignores_flat_noise():
    from swingscribe.stages.transcribe import pick_peaks

    strength = [0.5, 0.51, 0.5, 0.52, 0.5, 0.51] * 10
    assert pick_peaks(strength, min_separation=3, window=5, delta=0.1) == []


def test_crepe_recovers_synthetic_melody(tmp_path):
    pytest.importorskip("torch", reason="ml dependency group not installed")
    import numpy as np
    import soundfile

    from swingscribe.config import Config
    from swingscribe.model import Document
    from swingscribe.stages import transcribe

    rate = 16000
    melody = [(57, 0.5), (60, 0.5), (64, 0.5), (62, 0.5)]  # A3 C4 E4 D4
    signal = np.zeros(int(rate * 2.2), dtype="float32")
    t0 = 0.0
    for midi, dur in melody:
        hz = 440.0 * 2 ** ((midi - 69) / 12)
        n = int(rate * dur * 0.9)  # 10% gap between notes
        t = np.arange(n) / rate
        env = np.minimum(1.0, t * 50) * np.exp(-t * 1.5)
        start = int(t0 * rate)
        signal[start : start + n] += (0.5 * np.sin(2 * np.pi * hz * t) * env).astype("float32")
        t0 += dur

    other = tmp_path / "other.wav"
    soundfile.write(str(other), signal, rate)
    norm = tmp_path / "norm.wav"
    soundfile.write(str(norm), signal, rate)

    config = Config(cache_dir=tmp_path / "cache")
    document = Document(
        audio_path=str(norm),
        sample_rate=rate,
        audio={"path": str(norm), "sample_rate": rate, "channels": 1, "duration": 2.2},
        stems={"other": str(other)},
    )
    out = transcribe.run(document, config)

    pitches = [n.pitch for n in out.notes["other"]]
    assert pitches == [57, 60, 64, 62]

    # analyze() must return the same notes as the stage, plus the frame trace
    # the GUI's diagnostic overlay reads (docs/gui-design.md screen 4).
    notes, diag = transcribe.analyze(str(other), config.transcribe)
    assert [n.pitch for n in notes] == pitches
    assert len(diag.periodicity) == len(diag.pitch) == len(diag.f0_midi) == len(diag.energy_ok)
    assert len(diag.times) == len(diag.periodicity)
    assert 0.0 < diag.voiced_fraction <= 1.0
    # raw f0 survives gating so a gated-out frame can still be shown
    assert sum(1 for p in diag.f0_midi if p is not None) >= sum(
        1 for p in diag.pitch if p is not None
    )


def test_frame_diagnostics_times_are_whole_track():
    from swingscribe.stages.transcribe import FrameDiagnostics

    diag = FrameDiagnostics(
        hop_s=0.01,
        start=90.0,
        f0_midi=[60.0, 60.0, None],
        periodicity=[0.9, 0.9, 0.1],
        energy_ok=[True, True, False],
        pitch=[60.0, 60.0, None],
        onsets=[90.0, 90.5],
    )
    assert diag.times == [90.0, 90.01, 90.02]  # offset by the region start
    assert abs(diag.voiced_fraction - 2 / 3) < 1e-9


"""Viterbi f0 decoding (open-issue #8). The DP itself is numpy, so these skip
in CI alongside the other ml-group tests; the arrays are tiny and none of them
touch CREPE, so they run in milliseconds locally."""


def _brute_force_viterbi(log_probs, step_cost):
    """Textbook O(bins^2) Viterbi. The shipped one uses a distance-transform
    shortcut that is easy to get subtly wrong, so it is checked against this."""
    import numpy as np

    n_frames, n_bins = log_probs.shape
    idx = np.arange(n_bins)
    transition = -step_cost * np.abs(idx[:, None] - idx[None, :])
    score = log_probs[0].copy()
    back = np.zeros((n_frames, n_bins), dtype=int)
    for t in range(1, n_frames):
        totals = score[:, None] + transition
        back[t] = totals.argmax(axis=0)
        score = totals.max(axis=0) + log_probs[t]
    bin_index = int(score.argmax())
    path = [0] * n_frames
    for t in range(n_frames - 1, -1, -1):
        path[t] = bin_index
        bin_index = int(back[t][bin_index])
    return path, float(score.max())


def _path_score(log_probs, path, step_cost):
    total = sum(log_probs[t, b] for t, b in enumerate(path))
    return total - step_cost * sum(abs(path[t] - path[t - 1]) for t in range(1, len(path)))


def test_viterbi_matches_brute_force():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import viterbi_bins

    rng = numpy.random.default_rng(7)
    for _ in range(40):
        n_frames = int(rng.integers(1, 20))
        n_bins = int(rng.integers(2, 30))
        log_probs = rng.normal(size=(n_frames, n_bins)) * rng.choice([0.3, 1.0, 4.0])
        step_cost = float(rng.choice([0.01, 0.1, 0.5, 2.0]))
        fast = viterbi_bins(log_probs, step_cost)
        _, optimal = _brute_force_viterbi(log_probs, step_cost)
        assert abs(_path_score(log_probs, fast, step_cost) - optimal) < 1e-9


def test_viterbi_zero_cost_is_per_frame_argmax():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import viterbi_bins

    log_probs = numpy.random.default_rng(3).normal(size=(50, 30))
    assert viterbi_bins(log_probs, 0.0) == list(log_probs.argmax(axis=1))


def test_viterbi_ignores_a_brief_louder_competitor():
    """Open-issue #8 in miniature: another instrument out-shouts the soloist
    for 40ms. Without continuity the decoder follows it; with continuity the
    round trip costs more than the four frames are worth."""
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import viterbi_bins

    log_probs = numpy.full((40, 60), -6.0)
    log_probs[:, 10] = -0.5  # the soloist: steady, never the loudest
    log_probs[18:22, 45] = 0.0  # the competitor: louder, briefly

    assert set(viterbi_bins(log_probs, 0.0)) == {10, 45}
    assert set(viterbi_bins(log_probs, 0.05)) == {10}


def test_viterbi_still_follows_a_real_interval():
    """The other half of the trade: continuity must not flatten the melody.
    A leap that STAYS is paid for once and is worth it."""
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import viterbi_bins

    log_probs = numpy.full((40, 60), -6.0)
    log_probs[:20, 10] = -0.5
    log_probs[20:, 45] = -0.5  # an octave-ish leap, sustained

    path = viterbi_bins(log_probs, 0.05)
    assert path[0] == 10
    assert path[-1] == 45


def test_viterbi_never_chooses_a_masked_bin():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import BIN_FLOOR, viterbi_bins

    log_probs = numpy.zeros((6, 20))
    log_probs[:, 3] = 5.0
    log_probs[:, 15] = BIN_FLOOR  # outside [fmin, fmax]
    assert 15 not in viterbi_bins(log_probs, 0.1)


def test_viterbi_handles_an_empty_matrix():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import viterbi_bins

    assert viterbi_bins(numpy.zeros((0, 360)), 0.1) == []


def test_refine_bins_interpolates_between_bin_centres():
    numpy = pytest.importorskip("numpy")
    from swingscribe.stages.transcribe import CENTS_PER_BIN, refine_bins

    probs = numpy.zeros((1, 20))
    probs[0, 10] = 1.0
    probs[0, 11] = 1.0  # mass split evenly across two adjacent bins
    cents = refine_bins(probs, [10])
    centre_10 = refine_bins(numpy.eye(20)[None, 10], [10])[0]
    assert abs(cents[0] - (centre_10 + CENTS_PER_BIN / 2)) < 1e-6


def test_hz_to_bin_agrees_with_midi_conversion():
    from swingscribe.stages.transcribe import _hz_to_bin

    # 20 cents per bin means a semitone is exactly 5 bins, an octave 60.
    assert abs((_hz_to_bin(440.0) - _hz_to_bin(220.0)) - 60.0) < 1e-9
    assert abs((_hz_to_bin(440.0) - _hz_to_bin(415.3047)) - 5.0) < 1e-3


def test_a_vibrato_swell_on_a_held_note_is_not_a_re_articulation():
    """The bug behind the fragmented held note in All The Things.

    Vibrato swells a note's own harmonics by several dB without the player
    doing anything, so a rise alone let the onset detector cut an 11-beat
    held note into five. Tonguing a note interrupts it first; a swell never
    goes below the sustain it came from.
    """
    from swingscribe.stages.transcribe import corroborate_onsets

    pitch = [68.0] * 24
    swell = [1.0] * 10 + [1.0, 1.2, 1.5, 1.9, 2.1] + [2.0] * 9  # rises, never dips
    assert corroborate_onsets({10}, swell, pitch, rise_db=3.0, window=5) == {10}
    assert corroborate_onsets({10}, swell, pitch, rise_db=3.0, window=5, dip_db=2.0) == set()


def test_a_tongued_repeat_still_splits():
    """The other half: a real repeated note must survive the dip test."""
    from swingscribe.stages.transcribe import corroborate_onsets

    pitch = [68.0] * 24
    tongued = [1.0] * 9 + [0.3, 0.25, 1.6, 2.0, 2.1] + [2.0] * 10  # dips, then attacks
    assert corroborate_onsets({11}, tongued, pitch, rise_db=3.0, window=5, dip_db=2.0) == {11}


def test_the_dip_is_only_required_between_two_of_the_same_note():
    """A slur into a different pitch has no dip and must not need one."""
    from swingscribe.stages.transcribe import corroborate_onsets

    pitch = [64.0] * 10 + [68.0] * 14  # a real interval, slurred
    swell = [1.0] * 10 + [1.0, 1.2, 1.5, 1.9, 2.1] + [2.0] * 9
    assert corroborate_onsets({10}, swell, pitch, rise_db=3.0, window=5, dip_db=2.0) == {10}


def test_dip_defaults_to_off_so_it_changes_nothing_unasked():
    from swingscribe.stages.transcribe import corroborate_onsets

    pitch = [68.0] * 24
    swell = [1.0] * 10 + [1.0, 1.2, 1.5, 1.9, 2.1] + [2.0] * 9
    assert corroborate_onsets({10}, swell, pitch, rise_db=3.0, window=5) == {10}


# ── M7b: routing to the piano oracle ─────────────────────────────────────


def test_a_horn_never_consults_the_piano_oracle():
    """A piano model asked about a saxophone vouches for nothing, so rejection
    would delete the whole line. This is the guard that makes the default safe."""
    assert TranscribeConfig(ensemble="horn-led").uses_piano_oracle is False


def test_the_piano_ensembles_consult_it():
    """Plan §5 stage 3 routes on `ensemble`; this is that routing."""
    assert TranscribeConfig(ensemble="trio").uses_piano_oracle is True
    assert TranscribeConfig(ensemble="solo-piano").uses_piano_oracle is True


def test_the_oracle_can_be_forced_on_for_a_horn_led_config():
    """An escape hatch for measurement — the benchmark spans are horn-led by
    default even when the soloist is a pianist."""
    assert TranscribeConfig(ensemble="horn-led", piano_oracle=True).uses_piano_oracle is True


def test_oracle_settings_reach_the_cache_key():
    """They change the notes, so they must change the key — otherwise a run
    with the oracle on would serve notes computed without it (plan §3)."""
    base = Config()
    key = base.stage_config("transcribe")
    for field in (
        "piano_oracle",
        "piano_snap_octaves",
        "piano_reject_uncorroborated",
        "piano_onset_tolerance",
    ):
        assert field in key, field


def test_an_unavailable_oracle_leaves_the_line_alone(monkeypatch):
    """A missing checkpoint or an absent ml group must not turn a working
    transcription into no transcription — the oracle improves a line that
    already exists."""
    from swingscribe import piano
    from swingscribe.stages import transcribe as stage

    def explode(*_args, **_kwargs):
        raise RuntimeError("no checkpoint here")

    monkeypatch.setattr(piano, "transcribe", explode)
    notes = [NoteEvent(onset=1.0, duration=0.2, pitch=60, confidence=0.9, source="other:crepe")]
    tc = TranscribeConfig(ensemble="trio")
    assert stage._consult_piano_oracle(None, 44100, tc, 0.0, notes) == notes


def test_an_oracle_that_hears_nothing_leaves_the_line_alone(monkeypatch):
    from swingscribe import piano
    from swingscribe.stages import transcribe as stage

    monkeypatch.setattr(piano, "transcribe", lambda *a, **k: [])
    notes = [NoteEvent(onset=1.0, duration=0.2, pitch=60, confidence=0.9, source="other:crepe")]
    assert (
        stage._consult_piano_oracle(None, 44100, TranscribeConfig(ensemble="trio"), 0.0, notes)
        == notes
    )


def test_the_oracle_corrects_an_octave_and_drops_a_phantom(monkeypatch):
    """The two measured effects, end to end through the stage: a note at the
    wrong octave is moved (recall), a note nobody else heard goes (precision)."""
    from swingscribe import piano
    from swingscribe.stages import transcribe as stage

    monkeypatch.setattr(
        piano,
        "transcribe",
        lambda *a, **k: [{"onset": 1.0, "duration": 0.2, "pitch": 72, "velocity": 80}],
    )
    notes = [
        NoteEvent(onset=1.0, duration=0.2, pitch=60, confidence=0.9, source="other:crepe"),
        NoteEvent(onset=5.0, duration=0.2, pitch=43, confidence=0.5, source="other:crepe"),
    ]
    got = stage._consult_piano_oracle(None, 44100, TranscribeConfig(ensemble="trio"), 0.0, notes)
    assert [n.pitch for n in got] == [72]
    assert got[0].source == "other:crepe+piano"
