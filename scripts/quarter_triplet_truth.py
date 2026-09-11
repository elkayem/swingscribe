"""Precision and recall of the quarter-note-triplet pair rule against the hand
scores (D28), and a feature table of every CANDIDATE beat pair -- three to six
onsets on a half-note unit -- with its truth, so rule variants can be fitted
offline.

Analysis only: it monkeypatches `quantize.quarter_triplet_pairs` to see every
pair the rule considered, and runs the harness's own `notate_run` over the
cached notes, so `run_eval.py` must have been run first. Run from the repo
root: `uv run python scripts/quarter_triplet_truth.py`.

Truth: our notes are aligned to the score's melody the way score_tune does
(pitch sequence, no timing); a candidate pair is TRUE when a matched note
inside it is one the human wrote two thirds of a beat long. Recall is over the
human's half-units holding such notes.

Writes qt_features.json in the cwd (per-pair features and truth; positions in
beats, no pitches, no audio -- and still not for the repo) and prints the
summary. Only the aggregate counts belong in a doc.
"""

import bisect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_eval  # noqa: E402
import score_benchmark  # noqa: E402

from swingscribe import mscz  # noqa: E402
from swingscribe.alignment import align, best_transposition  # noqa: E402
from swingscribe.stages import quantize  # noqa: E402

LATTICE = (0.0, 2.0 / 3.0, 4.0 / 3.0, 2.0)
real = quantize.quarter_triplet_pairs
candidates: list[dict] = []


def spy(per_beat_raw, beats, sections):
    adopted = set(real(per_beat_raw, beats, sections))
    for index in sorted(per_beat_raw):
        if index + 1 >= len(beats):
            continue
        pulses = quantize._pulses_at(index, beats, sections)
        _bar, beat_in_bar = quantize.bar_and_beat(float(index), beats, sections)
        first = int(round(beat_in_bar))
        if first % 2 or first + 2 > pulses or not quantize.has_half_units(pulses):
            continue
        positions = sorted(
            list(per_beat_raw[index]) + [1.0 + r for r in per_beat_raw.get(index + 1, [])]
        )
        if not 3 <= len(positions) <= 6:
            continue
        nearest = [min(LATTICE, key=lambda q: abs(p - q)) for p in positions]
        errors = [abs(p - q) for p, q in zip(positions, nearest, strict=True)]
        length = (quantize._beat_length(beats, index) + quantize._beat_length(beats, index + 1)) / 2
        end = beats[index + 2] if index + 2 < len(beats) else beats[index + 1] + length
        candidates.append(
            {
                "start": beats[index],
                "end": end,
                "positions": [round(p, 4) for p in positions],
                "lattice_errors": [round(e, 4) for e in errors],
                "bpm": round(60 / length),
                "adopted": index in adopted,
            }
        )
    return sorted(adopted)


quantize.quarter_triplet_pairs = spy

# The reading ships off (config.py); it has to run for the spy to see anything.
_shipped_config = run_eval.eval_config


def _config_with_the_reading():
    config = _shipped_config()
    reading = config.quantize.model_copy(update={"quarter_triplets": True})
    return config.model_copy(update={"quantize": reading})


run_eval.eval_config = _config_with_the_reading


def main() -> None:
    os.chdir(ROOT)
    runs = json.loads(Path(".benchmark-notes-c0.2-d0.0.json").read_text(encoding="utf-8"))
    grids = json.loads(Path(".benchmark-grids.json").read_text(encoding="utf-8"))
    by_audio = {audio: (key, name) for key, (audio, name, *_r) in score_benchmark.TUNES.items()}
    table = []
    totals = {"human_units": 0, "reachable": 0, "adopted": 0, "adopted_true": 0, "recalled": 0}
    print(f"{'track':<36}{'human':>6}{'reach':>6}{'cand':>6}{'adopt':>6}{'true':>6}{'recall':>8}")
    for name in sorted(runs):
        track = run_eval.track_of(name)
        if track not in by_audio or track not in grids or run_eval.take_of(name):
            continue
        run = runs[name]
        score = mscz.parse_any(ROOT / "benchmark" / by_audio[track][1])
        est = sorted(run["notes"], key=lambda n: n["onset"])
        ref_pitches = score.pitches
        est_pitches = [n["pitch"] for n in est]
        head_ref, head_est = ref_pitches[:120], est_pitches[:160]
        coarse, _ = best_transposition(head_ref, head_est)
        offset, _ = best_transposition(head_ref, head_est, search=range(coarse - 2, coarse + 3))
        alignment = align(ref_pitches, [p + offset for p in est_pitches])
        melody = score.melody
        # Our onset -> the human's note, for true matches only.
        matched = []
        for ri, ei in alignment.pairs:
            if ri is None or ei is None or melody[ri].pitch != est[ei]["pitch"] + offset:
                continue
            matched.append((est[ei]["onset"], melody[ri]))
        matched.sort(key=lambda m: m[0])
        onsets = [m[0] for m in matched]

        candidates.clear()
        # The reading has to run for the spy to see anything; the flag ships off.
        run_eval.notate_run(name, {**run, "notes": est}, grids[track])

        def human_in(start, end, onsets=onsets, matched=matched):
            lo, hi = bisect.bisect_left(onsets, start), bisect.bisect_left(onsets, end)
            return [matched[i][1] for i in range(lo, hi)]

        human_units = {}
        for note in melody:
            if abs(note.duration - 2 / 3) < 0.02:
                human_units.setdefault((note.bar, int(note.position // 2)), []).append(note)
        adopted_true = 0
        covered_units = set()
        reachable = set()
        for c in candidates:
            inside = human_in(c["start"], c["end"])
            qt = [n for n in inside if abs(n.duration - 2 / 3) < 0.02]
            c["true"] = len(qt) >= 1
            c["track"] = Path(track).stem[:30]
            units = {(n.bar, int(n.position // 2)) for n in qt}
            if c["true"]:
                reachable |= units
                if c["adopted"]:
                    adopted_true += 1
                    covered_units |= units
        table.extend(candidates)
        n_adopted = sum(c["adopted"] for c in candidates)
        print(
            f"{Path(track).stem[:36]:<36}{len(human_units):>6}{len(reachable):>6}"
            f"{len(candidates):>6}{n_adopted:>6}{adopted_true:>6}{len(covered_units):>8}"
        )
        totals["human_units"] += len(human_units)
        totals["reachable"] += len(reachable)
        totals["adopted"] += n_adopted
        totals["adopted_true"] += adopted_true
        totals["recalled"] += len(covered_units)
    print(totals)
    Path("qt_features.json").write_text(json.dumps(table), encoding="utf-8")
    print(f"{len(table)} candidate pairs written to qt_features.json")


if __name__ == "__main__":
    main()
