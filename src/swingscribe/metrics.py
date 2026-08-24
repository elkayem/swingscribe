"""Transcription scoring, via mir_eval (plan §6; CLAUDE.md).

mir_eval is the source of truth — nothing here reimplements a metric, it only
marshals our types into mir_eval's shapes and names the results.

The three failure modes are scored *separately*, because in a single number
they are indistinguishable and we have been guessing between them:

  - `score_frames`  — is the pitch right where a pitch exists, and is the
                      voicing decision right? (f0 + gating)
  - `score_notes`   — are the note boundaries right? (segmentation)

A run can have excellent frame pitch accuracy and terrible note F1 (one held
note shattered into fragments — open-issue #1), or the reverse. Reporting
both is what tells them apart.

Heavy imports stay inside functions so this module is importable without the
ml dependency group.
"""

from swingscribe.model import NoteEvent

ONSET_TOLERANCE_S = 0.05  # plan §6: 50ms
PITCH_TOLERANCE_CENTS = 50.0  # plan §6: 50 cents


def midi_to_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def _intervals_and_pitches(notes: list[NoteEvent]):
    """(N,2) onset/offset intervals plus pitches in Hz, as mir_eval wants."""
    import numpy as np

    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    intervals = np.array([[n.onset, n.onset + max(n.duration, 1e-4)] for n in notes])
    pitches = np.array([midi_to_hz(n.pitch) for n in notes])
    return intervals, pitches


def score_notes(
    reference: list[NoteEvent],
    estimate: list[NoteEvent],
    onset_tolerance: float = ONSET_TOLERANCE_S,
    pitch_tolerance: float = PITCH_TOLERANCE_CENTS,
) -> dict[str, float]:
    """Note-level scores: onset-only, and onset+pitch. Offsets are ignored
    (offset_ratio=None) — sustain and release make offsets the least reliable
    thing we produce, and the plan's acceptance targets are onset-based."""
    import mir_eval

    ref_intervals, ref_pitches = _intervals_and_pitches(reference)
    est_intervals, est_pitches = _intervals_and_pitches(estimate)

    if len(ref_intervals) == 0 or len(est_intervals) == 0:
        empty = float(len(ref_intervals) == 0 and len(est_intervals) == 0)
        return {
            "onset_precision": empty,
            "onset_recall": empty,
            "onset_f1": empty,
            "note_precision": empty,
            "note_recall": empty,
            "note_f1": empty,
            "n_reference": float(len(ref_intervals)),
            "n_estimate": float(len(est_intervals)),
        }

    on_p, on_r, on_f = mir_eval.transcription.onset_precision_recall_f1(
        ref_intervals, est_intervals, onset_tolerance=onset_tolerance
    )
    note_p, note_r, note_f, _overlap = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals,
        ref_pitches,
        est_intervals,
        est_pitches,
        onset_tolerance=onset_tolerance,
        pitch_tolerance=pitch_tolerance,
        offset_ratio=None,
    )
    return {
        "onset_precision": float(on_p),
        "onset_recall": float(on_r),
        "onset_f1": float(on_f),
        "note_precision": float(note_p),
        "note_recall": float(note_r),
        "note_f1": float(note_f),
        "n_reference": float(len(ref_intervals)),
        "n_estimate": float(len(est_intervals)),
    }


def notes_to_frames(notes: list[NoteEvent], times: list[float]) -> list[float]:
    """Sample a note list onto a frame grid as Hz, 0.0 where nothing sounds.

    Monophonic by construction: where notes overlap, the later onset wins,
    which matches how a monophonic tracker would hear it.
    """
    freqs = [0.0] * len(times)
    for note in sorted(notes, key=lambda n: n.onset):
        hz = midi_to_hz(note.pitch)
        end = note.onset + note.duration
        for i, t in enumerate(times):
            if note.onset <= t < end:
                freqs[i] = hz
    return freqs


def score_frames(
    reference_hz: list[float],
    estimate_hz: list[float],
    times: list[float],
) -> dict[str, float]:
    """Frame-level pitch and voicing scores (mir_eval.melody).

    Separates "the pitch is wrong" from "we transcribed silence" — the two
    get confounded in any note-level number. 0.0 Hz means unvoiced.
    """
    import mir_eval
    import numpy as np

    ref = np.asarray(reference_hz, dtype=float)
    est = np.asarray(estimate_hz, dtype=float)
    t = np.asarray(times, dtype=float)

    ref_voicing = ref > 0
    est_voicing = est > 0
    ref_cent = mir_eval.melody.hz2cents(np.where(ref_voicing, ref, 1.0))
    est_cent = mir_eval.melody.hz2cents(np.where(est_voicing, est, 1.0))

    scores = {
        "raw_pitch_accuracy": float(
            mir_eval.melody.raw_pitch_accuracy(ref_voicing, ref_cent, est_voicing, est_cent)
        ),
        "raw_chroma_accuracy": float(
            mir_eval.melody.raw_chroma_accuracy(ref_voicing, ref_cent, est_voicing, est_cent)
        ),
        "overall_accuracy": float(
            mir_eval.melody.overall_accuracy(ref_voicing, ref_cent, est_voicing, est_cent)
        ),
        "n_frames": float(len(t)),
    }
    recall, false_alarm = mir_eval.melody.voicing_measures(ref_voicing, est_voicing)
    scores["voicing_recall"] = float(recall)
    scores["voicing_false_alarm"] = float(false_alarm)
    return scores
