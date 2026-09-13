"""Eighth-note triplets, BEAT by beat, against the hand scores (D29).

The listener's complaint: they would have written an eighth-note triplet
where the page did not. This asks, for every beat the human wrote ternary,
what our page did with the SAME beat and why -- and, the other way, how
many of our ternary beats sit where the human wrote binary.

A human beat is ternary when any of its notes sits on a third of the beat
or is a third (or two thirds) of a beat long. Our beat is ternary when any
onset in it was quantized to a third. The two sides are joined through the
aligner (score_tune's: pitch sequence, no timing): a human beat is looked
up by the beat our matched note for it landed in.

Analysis only: it spies on `quantize.quantize_notes` to see the onsets each
beat held and the grid it got, and runs the harness's own `notate_run` over
the cached notes, so `run_eval.py` must have been run first. Run from the
repo root: `uv run python scripts/triplet_beats.py`. Aggregate counts only.

The causes it splits a miss into:

- fewer than three onsets in ours: the three-onset gate cannot write a
  tuplet (the swung-pair convention, D12). Sub-split: our notes for the
  human's beat landed in two beats; the human has a note we never matched;
  other (a two-note triplet figure, D28).
- three or more onsets, and the grid chose binary: eighths where an onset
  was pushed onto the NEXT downbeat (position 1.0), 32nds admitted because
  sixteenths would merge two onsets, or sixteenths outright.

And for the displaced-eighth case, what the human wrote for the beat in
which we pushed a note onto the next downbeat: measured 2026-09-12, the
human ALSO puts a note on the next downbeat two times in three, so that
displacement is not a defect (D29).
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_eval  # noqa: E402
import score_benchmark  # noqa: E402

from swingscribe import mscz  # noqa: E402
from swingscribe.alignment import align, best_transposition  # noqa: E402
from swingscribe.stages import quantize  # noqa: E402

TICK = 1e-3
real = quantize.quantize_notes
onset_beat: dict[float, int] = {}
beat_info: dict[int, dict] = {}


def spy(onsets, durations, pitches, beats, spans, sections, **kw):
    quantized, positions = real(onsets, durations, pitches, beats, spans, sections, **kw)
    by_beat, _ = quantize.pooled_phase(spans, kw.get("straight_bur_ceiling", 1.6))
    placed = [o for o in onsets if quantize.beat_position(o, beats) is not None]
    onset_beat.clear()
    beat_info.clear()
    for onset, q in zip(placed, quantized, strict=True):
        p = quantize.beat_position(onset, beats)
        index = int(p)
        onset_beat[onset] = index
        info = beat_info.setdefault(
            index,
            {
                "raw": [],
                "fracs": [],
                "star": by_beat.get(index, 0.5),
                "slack": 0.02 / quantize._beat_length(beats, index),
            },
        )
        info["raw"].append(p - index)
        info["fracs"].append(q.beat - int(q.beat + 1e-9))
    return quantized, positions


quantize.quantize_notes = spy


def on_thirds(x: float) -> bool:
    f = x - int(x + TICK)
    return abs(f - 1 / 3) < 0.02 or abs(f - 2 / 3) < 0.02


def human_beat_ternary(notes) -> bool:
    return any(
        on_thirds(n.position) or abs(n.duration - 1 / 3) < 0.02 or abs(n.duration - 2 / 3) < 0.02
        for n in notes
    )


def replay_grid(info: dict) -> int:
    """The grid quantize chose for this beat, re-derived from what it saw."""
    raw = sorted(info["raw"])
    warped = [quantize.warp_phase(r, info["star"]) for r in raw]
    cands = (2, 4, 3) + ((8,) if not quantize._keeps_apart(warped, 4) else ())
    return quantize.choose_grid(warped, cands, 3, info["slack"], raw_offsets=raw)


def displaced(info: dict, grid: int) -> bool:
    """Did the chosen grid push an onset onto the next downbeat?"""
    raw = sorted(info["raw"])
    offsets = raw if grid % 3 == 0 else [quantize.warp_phase(r, info["star"]) for r in raw]
    return any(quantize.snap(o, grid)[0] >= 1.0 for o in offsets)


def main() -> None:
    os.chdir(ROOT)
    runs = json.loads(Path(".benchmark-notes-c0.2-d0.0.json").read_text(encoding="utf-8"))
    grids = json.loads(Path(".benchmark-grids.json").read_text(encoding="utf-8"))
    by_audio = {audio: (key, name) for key, (audio, name, *_r) in score_benchmark.TUNES.items()}
    cols = ["human_t", "reached", "hit", "miss_lt3", "miss_grid", "ours_t", "false_t"]
    print(f"{'track':<34}" + "".join(f"{c:>10}" for c in cols))
    total: Counter = Counter()
    displaced_human: Counter = Counter()
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
        human_beats: dict[int, list] = {}
        for n in melody:
            if n.duration > 0:
                human_beats.setdefault(int(n.position + TICK), []).append(n)
        run_eval.notate_run(name, {**run, "notes": est}, grids[track])

        landed: dict[int, Counter] = {}  # human beat -> our beats its matched notes landed in
        our_beat_to_human: dict[int, Counter] = {}
        for ri, ei in alignment.pairs:
            if ri is None or ei is None or melody[ri].pitch != est[ei]["pitch"] + offset:
                continue
            hb = int(melody[ri].position + TICK)
            ob = onset_beat.get(est[ei]["onset"])
            if ob is None:
                continue
            landed.setdefault(hb, Counter())[ob] += 1
            our_beat_to_human.setdefault(ob, Counter())[hb] += 1

        c: Counter = Counter()
        for hb, notes in human_beats.items():
            if not human_beat_ternary(notes):
                continue
            c["human_t"] += 1
            if hb not in landed:
                continue
            ob = landed[hb].most_common(1)[0][0]
            info = beat_info[ob]
            c["reached"] += 1
            if any(on_thirds(f) for f in info["fracs"]):
                c["hit"] += 1
            elif len(info["raw"]) < 3:
                c["miss_lt3"] += 1
                if len(landed[hb]) > 1:
                    c["lt3_spilled"] += 1
                elif sum(landed[hb].values()) < len(notes):
                    c["lt3_note_missed"] += 1
                else:
                    c["lt3_other"] += 1
            else:
                c["miss_grid"] += 1
                chosen = replay_grid(info)
                if chosen == 2:
                    c["grid_eighths_displaced"] += 1
                elif chosen == 8:
                    c["grid_32nds"] += 1
                else:
                    c["grid_16ths"] += 1
        for ob, info in beat_info.items():
            ternary = any(on_thirds(f) for f in info["fracs"])
            if ternary:
                c["ours_t"] += 1
            humans = our_beat_to_human.get(ob)
            hb = humans.most_common(1)[0][0] if humans else None
            if ternary and hb is not None and not human_beat_ternary(human_beats.get(hb, [])):
                c["false_t"] += 1
            if len(info["raw"]) >= 3 and displaced(info, replay_grid(info)):
                if hb is None:
                    displaced_human["unmatched"] += 1
                elif human_beat_ternary(human_beats.get(hb, [])):
                    displaced_human["human ternary"] += 1
                elif any(
                    abs(m.position - (hb + 1)) < 0.02 for m in human_beats.get(hb + 1, [])
                ) and len(human_beats.get(hb, [])) < len(info["raw"]):
                    displaced_human["human also on the next downbeat"] += 1
                else:
                    displaced_human["human binary"] += 1
        print(f"{Path(track).stem[:34]:<34}" + "".join(f"{c.get(col, 0):>10}" for col in cols))
        total.update(c)
    print(f"{'ALL':<34}" + "".join(f"{total.get(col, 0):>10}" for col in cols))
    r = max(1, total["reached"])
    print()
    print(
        f"human ternary beats {total['human_t']}, reached through a matched note {total['reached']}"
    )
    print(f"  written ternary by us (recall):       {total['hit']} ({total['hit'] / r:.2f})")
    print(
        f"  missed, fewer than 3 onsets in ours:  {total['miss_lt3']} ({total['miss_lt3'] / r:.2f})"
    )
    print(
        f"    spilled into two beats {total['lt3_spilled']}, a human note we never matched "
        f"{total['lt3_note_missed']}, other {total['lt3_other']}"
    )
    grid_miss = total["miss_grid"]
    print(f"  missed, 3+ onsets, grid chose binary: {grid_miss} ({grid_miss / r:.2f})")
    print(
        f"    eighths with an onset pushed onto the next downbeat "
        f"{total['grid_eighths_displaced']}, 32nds via the merge rule {total['grid_32nds']}, "
        f"16ths {total['grid_16ths']}"
    )
    print(
        f"our ternary beats {total['ours_t']}; matched to a human beat written binary: "
        f"{total['false_t']}"
    )
    n = sum(displaced_human.values())
    print(f"beats of 3+ onsets where the grid pushed one onto the next downbeat: {n}")
    for k, v in displaced_human.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
