"""Transcribe stage. Segmentation/gating/octave helpers are pure and run in
CI; the pYIN melody-recovery test needs librosa and skips without it."""

import pytest

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


def test_crop_region_slices_and_reports_offset():
    import numpy as np

    from swingscribe.stages.transcribe import crop_region

    mono = np.arange(1000, dtype="float32")  # 10s at 100Hz
    cropped, offset = crop_region(mono, 100, (2.0, 5.0))
    assert len(cropped) == 300
    assert offset == 2.0
    assert cropped[0] == 200


def test_crop_region_open_ended():
    import numpy as np

    from swingscribe.stages.transcribe import crop_region

    mono = np.arange(1000, dtype="float32")
    cropped, offset = crop_region(mono, 100, (7.0, None))  # to the end
    assert len(cropped) == 300
    assert offset == 7.0


def test_crop_region_clamps_past_end():
    import numpy as np

    from swingscribe.stages.transcribe import crop_region

    mono = np.arange(1000, dtype="float32")
    cropped, _ = crop_region(mono, 100, (8.0, 99.0))
    assert len(cropped) == 200


def test_crop_region_rejects_inverted():
    import numpy as np
    import pytest as _pytest

    from swingscribe.stages.transcribe import crop_region

    with _pytest.raises(ValueError):
        crop_region(np.arange(1000, dtype="float32"), 100, (5.0, 2.0))


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
