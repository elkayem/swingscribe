"""Score the pipeline against the hand transcriptions in `benchmark/`.

    uv run python scripts/score_benchmark.py                 # transcribe + score
    uv run python scripts/score_benchmark.py --reuse         # score cached notes

Each tune in `benchmark/` is an audio file, a `.mscz` hand transcription, and
a `.swingscribe.json` sidecar holding the span/stem/model chosen in the GUI.
The sidecar's span is the transcribed span: bar 1 of the score is its start.

Two measures, deliberately kept apart:

  1. **Pitch sequence**, time-free (`swingscribe.alignment`). "Did it get the
     notes, in order?" A notated score has no timestamps, so scoring it in
     time needs a tempo map — and the only one we have comes from our own
     beat tracker, which would charge beat-tracking error to the transcriber
     and vice versa. Ignoring time removes that confound entirely.

  2. **Onset timing**, per 4-bar window (mir_eval via `swingscribe.metrics`).
     A constant tempo is derived from bars/span, and each window gets its own
     constant time offset to absorb drift. Rhythm *within* a window is still
     being tested; rhythm across the whole solo is not, and cannot be until
     M5 gives us a real tempo map.

The transposition between the two is measured, never assumed: a hand
transcription may be written an octave from concert pitch for readability,
and our own tracker makes octave errors. They look identical in a raw score.

NOTHING this reads or writes may be committed — the notes are derivative
works of commercial recordings. Only the aggregate numbers it prints may go
in the repo (plan §12); `docs/m3-benchmark.md` holds the last run's.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from swingscribe import metrics, mscz
from swingscribe.alignment import align, best_transposition, to_chroma
from swingscribe.benchmark import anchor_map, solo_shift, window_shift
from swingscribe.config import Config
from swingscribe.model import NoteEvent

BENCH = Path("benchmark")
WINDOW_BARS = 4
# How far outside a window's notated span to look for our notes. Only sets
# which of our notes are eligible to match; the window's placement comes from
# the alignment (see `window_shift`), not from a search over this range.
WINDOW_MARGIN_S = 1.0

# tune key -> (audio file, .mscz transcription, title, soloist's instrument)
TUNES = {
    "confirmation": (
        "02 Confirmation.m4a",
        "Dexter_Gordon_solo_on_Confirmation.mscz",
        "Confirmation",
        "tenor sax",
    ),
    "all_the_things": (
        "All_The_Things_You_Are.m4a",
        "Hank Mobley on All The Things You Are.mscz",
        "All The Things You Are",
        "tenor sax",
    ),
    "giant_steps": (
        "06 Giant Steps.m4a",
        "Tommy Flanagan Solo on Giant Steps.mscz",
        "Giant Steps",
        "piano",
    ),
}


def transcribe_all(cache_path: Path, step_cost: float = 0.0) -> dict:
    """Run the transcriber over each tune's saved span, caching the notes.

    Cached because CREPE on CPU is minutes per tune and the scoring above it
    is worth iterating on by itself.
    """
    from swingscribe.gui import library
    from swingscribe.stages import transcribe
    from swingscribe.stages.separate import stems_dir

    base = Config()
    runs = {}
    for key, (audio_name, _, title, _) in TUNES.items():
        src = BENCH / audio_name
        sidecar = json.loads(Path(str(src) + ".swingscribe.json").read_text(encoding="utf-8"))
        model, stem = sidecar["model"], sidecar["stem"]
        lo, hi = sidecar["region"]
        config = base.model_copy(
            update={"separate": base.separate.model_copy(update={"model": model})}
        )
        doc = library.ingested_document(src, config)
        stem_path = stems_dir(config.cache_dir, library.file_digest(doc.audio.path), model) / (
            f"{stem}.wav"
        )
        if not stem_path.is_file():
            raise SystemExit(
                f"{title}: no {stem!r} stem for {model}. Separate it first:\n"
                f"    uv run swingscribe run {src!r}"
            )
        tc = base.transcribe.model_copy(
            update={"stem": stem, "region": (lo, hi), "pitch_step_cost": step_cost}
        )
        print(
            f"\n=== {title}: {stem} of {model}, {lo:.1f}-{hi:.1f}s, step cost {step_cost} ===",
            flush=True,
        )
        started = time.time()
        notes, diagnostics = transcribe.analyze(str(stem_path), tc, log=True)
        print(f"  {len(notes)} notes in {time.time() - started:.0f}s", flush=True)
        runs[key] = {
            "model": model,
            "stem": stem,
            "region": [lo, hi],
            "voiced_fraction": diagnostics.voiced_fraction,
            "notes": [
                {
                    "onset": n.onset,
                    "duration": n.duration,
                    "pitch": n.pitch,
                    "confidence": n.confidence,
                }
                for n in notes
            ],
        }
        cache_path.write_text(json.dumps(runs), encoding="utf-8")
    return runs


def score_tune(key: str, run: dict) -> dict:
    _, mscz_name, title, instrument = TUNES[key]
    score = mscz.parse(BENCH / mscz_name)
    lo, hi = run["region"]
    span = hi - lo
    # The score covers exactly this span, so its bars fix the average tempo.
    bpm = score.bars * score.beats_per_bar / span * 60.0
    beat_s = 60.0 / bpm

    est = [
        NoteEvent(
            onset=n["onset"],
            duration=n["duration"],
            pitch=n["pitch"],
            confidence=n["confidence"],
            source="crepe",
        )
        for n in run["notes"]
    ]
    ref_pitches = score.pitches
    est_pitches = [n.pitch for n in est]

    # --- pitch sequence ---------------------------------------------------
    # Aligning all 49 transposition candidates in full would be minutes of
    # pure Python, so narrow on a prefix and align once at the winner.
    head_ref, head_est = ref_pitches[:120], est_pitches[:160]
    coarse, _ = best_transposition(head_ref, head_est)
    offset, _ = best_transposition(head_ref, head_est, search=range(coarse - 2, coarse + 3))
    shifted = [p + offset for p in est_pitches]
    pitch = align(ref_pitches, shifted)
    chroma = align(to_chroma(ref_pitches), to_chroma(shifted))

    # --- onset timing, per window ----------------------------------------
    ref_events = mscz.to_note_events(score, bpm, start_seconds=lo)
    # Which of our notes is which notated note, established with no timing.
    # `pitch` is the alignment computed above; only true matches anchor, since
    # a substitution pairs two notes that are not the same note.
    anchor_of = anchor_map(pitch.pairs, ref_pitches, shifted)
    whole_solo = solo_shift([est[ei].onset - ref_events[ri].onset for ri, ei in anchor_of.items()])

    windows = []
    for start_bar in range(1, score.bars + 1, WINDOW_BARS):
        index = [
            i for i, n in enumerate(score.notes) if start_bar <= n.bar < start_bar + WINDOW_BARS
        ]
        if len(index) < 4:  # too few notes for a window to mean anything
            continue
        ref_win = [ref_events[i] for i in index]
        shift = window_shift(
            [est[anchor_of[i]].onset - ref_events[i].onset for i in index if i in anchor_of],
            whole_solo,
        )
        moved = [
            NoteEvent(
                onset=e.onset + shift,
                duration=e.duration,
                pitch=e.pitch - offset,  # score down to the concert pitch we produce
                confidence=1.0,
                source="mscz",
            )
            for e in ref_win
        ]
        w_lo = min(e.onset for e in moved) - 0.5 * beat_s - WINDOW_MARGIN_S
        w_hi = max(e.onset for e in moved) + 1.5 * beat_s + WINDOW_MARGIN_S
        est_win = [n for n in est if w_lo <= n.onset <= w_hi]
        if not est_win:
            windows.append({"onset_f1": 0.0, "note_f1": 0.0, "n_ref": len(ref_win), "shift": shift})
            continue
        scored = metrics.score_notes(moved, est_win)
        windows.append(
            {
                "onset_f1": scored["onset_f1"],
                "note_f1": scored["note_f1"],
                "n_ref": len(ref_win),
                "shift": shift,
            }
        )

    total = sum(w["n_ref"] for w in windows)

    def weighted(field: str) -> float:
        return sum(w[field] * w["n_ref"] for w in windows) / total if total else 0.0

    return {
        "title": title,
        "instrument": instrument,
        "stem": f"{run['stem']} of {run['model']}",
        "bars": score.bars,
        "span_s": span,
        "implied_bpm": bpm,
        "n_reference": len(ref_pitches),
        "n_estimate": len(est_pitches),
        "ref_range": [min(ref_pitches), max(ref_pitches)],
        "est_range": [min(est_pitches), max(est_pitches)] if est_pitches else [0, 0],
        "transposition": offset,
        "pitch_f1": pitch.f1,
        "pitch_precision": pitch.precision,
        "pitch_recall": pitch.recall,
        "matched": pitch.matches,
        "wrong_note": pitch.substitutions,
        "invented": pitch.insertions,
        "missed": pitch.deletions,
        "chroma_f1": chroma.f1,
        "onset_f1": weighted("onset_f1"),
        "note_f1": weighted("note_f1"),
        "onset_f1_median": statistics.median([w["onset_f1"] for w in windows]) if windows else 0.0,
        "n_windows": len(windows),
        "drift_absorbed_s": (max(w["shift"] for w in windows) - min(w["shift"] for w in windows))
        if windows
        else 0.0,
        "voiced_fraction": run["voiced_fraction"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score the pipeline against the hand transcriptions in benchmark/."
    )
    parser.add_argument(
        "--reuse", action="store_true", help="score the cached notes instead of re-running CREPE"
    )
    parser.add_argument("--notes", type=Path, default=None)
    parser.add_argument(
        "--step-cost",
        type=float,
        default=0.0,
        help="Viterbi f0 continuity cost per CREPE pitch bin (transcribe.pitch_step_cost)",
    )
    args = parser.parse_args()

    # One cache per decoding setting: they are not interchangeable results.
    default_notes = (
        ".benchmark-notes.json"
        if not args.step_cost
        else f".benchmark-notes-c{args.step_cost}.json"
    )
    notes_path = args.notes or Path(default_notes)
    if args.reuse and notes_path.is_file():
        runs = json.loads(notes_path.read_text(encoding="utf-8"))
    else:
        runs = transcribe_all(notes_path, args.step_cost)

    for key in TUNES:
        s = score_tune(key, runs[key])
        print(f"\n===== {s['title']} - {s['instrument']}, {s['stem']} =====")
        print(f"  {s['bars']} bars over {s['span_s']:.1f}s -> {s['implied_bpm']:.1f} bpm implied")
        print(
            f"  notes {s['n_estimate']} vs {s['n_reference']} notated "
            f"({s['n_estimate'] / s['n_reference']:.0%})   "
            f"range {s['est_range']} vs {s['ref_range']}"
        )
        print(f"  transposition detected: {s['transposition']:+d} semitones")
        print(
            f"  PITCH  F1 {s['pitch_f1']:.3f}  "
            f"(P {s['pitch_precision']:.3f} / R {s['pitch_recall']:.3f})   "
            f"chroma F1 {s['chroma_f1']:.3f}"
        )
        print(
            f"    {s['matched']} matched, {s['wrong_note']} wrong, "
            f"{s['invented']} invented, {s['missed']} missed"
        )
        print(
            f"  ONSET  F1 {s['onset_f1']:.3f} (median {s['onset_f1_median']:.3f}) over "
            f"{s['n_windows']} x {WINDOW_BARS}-bar windows; "
            f"drift absorbed {s['drift_absorbed_s']:.2f}s"
        )
        print(f"  NOTE (onset+pitch) F1 {s['note_f1']:.3f}")


if __name__ == "__main__":
    main()
