"""Which written LENGTHS we get wrong on the hand scores, and what the human wrote.

The notation benchmark's `value` (0.777 over the twelve hand scores on
2026-09-21) says how often a matched note carries the human's note value;
this says what we wrote instead, as a confusion table, with the context
that decides most of it: whether a rest follows our note, and whether one
follows theirs. Reads the harness's note and grid caches, notates each
page exactly as `run_eval` does, pairs notes the way `score_notation`
does (the time-free pitch alignment), and tallies the pairs whose values
differ by more than the scorer's tolerance.

    uv run python scripts/value_confusion.py

Only aggregates leave this script (plan section 12).
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval  # noqa: E402
import score_benchmark  # noqa: E402

from swingscribe import mscz  # noqa: E402
from swingscribe.alignment import measured_transposition  # noqa: E402
from swingscribe.benchmark import NOTATION_TOLERANCE, notation_notes  # noqa: E402

NAMES = [
    (4.0, "whole"),
    (3.0, "half."),
    (2.0, "half"),
    (1.5, "quarter."),
    (1.0, "quarter"),
    (0.75, "eighth."),
    (2 / 3, "quarter-triplet"),
    (0.5, "eighth"),
    (0.375, "16th."),
    (1 / 3, "triplet-8th"),
    (0.25, "16th"),
    (1 / 6, "16th-triplet"),
    (0.125, "32nd"),
]
REST = 0.02  # a gap past the note's end that counts as a rest, in beats


def value_name(duration: float) -> str:
    for value, name in NAMES:
        if abs(duration - value) < 0.02:
            return name
    return f"{duration:.3f}"


def confusions() -> tuple[Counter, Counter, dict[str, tuple[int, int]]]:
    runs = json.loads(run_eval.notes_cache(0.2, 0.0).read_text(encoding="utf-8"))
    grids = json.loads(run_eval.GRIDS_CACHE.read_text(encoding="utf-8"))
    by_audio = {audio: m for audio, m, *_ in score_benchmark.TUNES.values()}
    pairs: Counter = Counter()
    context: Counter = Counter()
    per_track: dict[str, tuple[int, int]] = {}
    for key, run in sorted(runs.items()):
        track = run_eval.track_of(key)
        if (
            run_eval.take_of(key) is not None
            or run_eval.is_omnibook(key)
            or track not in by_audio
            or track not in grids
            or Path(by_audio[track]).suffix.lower() not in (".mscz", ".mscx")
        ):
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            notation = run_eval.notate_run(key, run, grids[track])
        ours = notation_notes(notation)
        score = mscz.parse_any(run_eval.BENCH / by_audio[track])
        theirs = [(n.position, n.duration, n.pitch) for n in score.melody]
        offset, aligned = measured_transposition([p for *_, p in theirs], [p for *_, p in ours])
        matched = [
            (ri, ei)
            for ri, ei in aligned.pairs
            if ri is not None and ei is not None and theirs[ri][2] == ours[ei][2] + offset
        ]
        wrong = 0
        for ri, ei in matched:
            o, t = ours[ei][1], theirs[ri][1]
            if abs(o - t) <= NOTATION_TOLERANCE:
                continue
            wrong += 1
            gap_o = ours[ei + 1][0] - (ours[ei][0] + o) if ei + 1 < len(ours) else 0.0
            gap_t = theirs[ri + 1][0] - (theirs[ri][0] + t) if ri + 1 < len(theirs) else 0.0
            ctx = (
                "rest after ours" if gap_o > REST else "no rest after ours",
                "rest after theirs" if gap_t > REST else "no rest after theirs",
            )
            pairs[(value_name(o), value_name(t), ctx)] += 1
            context[ctx] += 1
        per_track[track] = (wrong, len(matched))
    return pairs, context, per_track


def main() -> None:
    logging.disable(logging.CRITICAL)
    pairs, context, per_track = confusions()
    matched = sum(m for _w, m in per_track.values())
    wrong = sum(w for w, _m in per_track.values())
    print(f"matched {matched} notes, value wrong on {wrong} ({100 * wrong / matched:.1f}%)")
    print("ours -> theirs, with rest context (share of the wrong ones):")
    for (o, t, ctx), n in pairs.most_common(20):
        print(f"  {o:16s} -> {t:16s}  {ctx[0]:20s} {ctx[1]:22s} {n:4d}  {100 * n / wrong:4.1f}%")
    print("rest context overall:")
    for ctx, n in context.most_common():
        print(f"  {ctx[0]:20s} {ctx[1]:22s} {n:4d}  {100 * n / wrong:4.1f}%")
    print("per page:")
    for track, (w, m) in per_track.items():
        print(f"  {track[:44]:44s} wrong {w:3d} of {m}")


if __name__ == "__main__":
    main()
