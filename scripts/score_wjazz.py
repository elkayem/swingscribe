"""Score the pipeline against the Weimar Jazz Database's hand transcriptions.

    uv run python scripts/score_wjazz.py --db path/to/wjazzd.db --notes cache.json

This is the benchmark the `.mscz` one cannot be. WJazzD gives per-note onsets
**in seconds**, so there is no notated score to place in time: no tempo map,
no per-window offset, no swing model, none of the machinery that
`scripts/score_benchmark.py` needs and that was silently wrong inside it for
months (docs/m3-benchmark.md). Our notes and their notes are both timestamps,
and the only thing standing between them is where the recording starts.

It also brings human-tapped beats, which lets the beat tracker be scored
against something other than its own steadiness for the first time.

## Identifying the take is part of the measurement

A tune title is not a recording. "Oleo" is four different solos in WJazzD and
we must not score Red Garland's piano against Coltrane's tenor. So every
candidate solo with a matching title is fitted, and the winner has to win by a
mile: a wrong candidate scores at chance (2-7% here, which is what random note
density predicts), a right one scores 20-80%. Anything in between is reported
as unmatched rather than scored.

## Offset and rate, and why rate is legitimate

Two CD issues of one master can differ in playback speed by a few tenths of a
percent. That shows up unmistakably as a *monotone* drift in the fitted offset
across the solo -- Walkin' drifts -0.33s then -0.64s over 155 seconds, 0.4%
slow -- and correcting it is not fitting to our own data, it is undoing a
transfer artefact. So the fit is affine: their_time * rate + offset. Two
parameters for a whole solo, both about the recording rather than the playing.

WJazzD is ODbL. The database lives outside this repo and nothing derived from
it may be committed beyond aggregate numbers (plan section 12, docs/wjazzd.md).
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

ONSET_TOLERANCE_S = 0.05
# Below this share of the reference matched, we have not found the take. A
# wrong candidate lands at 2-7% from note density alone; a right one at 20%+.
MIN_MATCH_RATE = 0.15
# ...and the runner-up must be this far behind, or the identification is not
# safe enough to score against.
MIN_MARGIN = 2.5
STOPWORDS = frozenset({"the", "a", "an", "of", "on", "solo", "and"})
RATE_LOW, RATE_HIGH, RATE_STEP = 0.994, 1.006, 0.0005


def title_tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in STOPWORDS and len(w) > 2}


def _matches(ref_on, ref_p, est_on, est_p, offset, rate):
    """Boolean per reference note: does one of ours sit on it, same pitch?"""
    import numpy as np

    t = ref_on * rate + offset
    index = np.searchsorted(est_on, t)
    hit = np.zeros(len(t), dtype=bool)
    for step in (-1, 0, 1):
        j = np.clip(index + step, 0, len(est_on) - 1)
        hit |= (np.abs(est_on[j] - t) <= ONSET_TOLERANCE_S) & (est_p[j] == ref_p)
    return hit


def fit_affine(ref_on, ref_p, est_on, est_p, low, high, step=0.01):
    """(offset, rate, matches) lining their solo up with our notes.

    Coarse offset first at rate 1, then offset and rate jointly nearby. Pitch
    is part of the criterion throughout: an onset-only fit on a jazz line can
    lock onto a whole eighth-note slip, which is the bug that made the other
    benchmark wrong for months (src/swingscribe/benchmark.py).
    """
    import numpy as np

    best = (0.0, 1.0, -1)
    for offset in np.arange(low, high, step):
        n = int(_matches(ref_on, ref_p, est_on, est_p, offset, 1.0).sum())
        if n > best[2]:
            best = (float(offset), 1.0, n)
    coarse = best[0]
    pivot = float(ref_on[len(ref_on) // 2])
    for rate in np.arange(RATE_LOW, RATE_HIGH, RATE_STEP):
        # A rate change pivots about time zero, so the offset must follow it.
        centre = coarse - (rate - 1.0) * pivot
        for offset in np.arange(centre - 1.0, centre + 1.0, 0.005):
            n = int(_matches(ref_on, ref_p, est_on, est_p, offset, rate).sum())
            if n > best[2]:
                best = (float(offset), float(rate), n)
    return best


def identify(db, name, est_on, est_p, region):
    """Which WJazzD solo this audio holds, or None if it cannot be told."""
    import numpy as np

    wanted = title_tokens(Path(name).stem)
    scored = []
    for melid, performer, title, instrument, tempo in db.execute(
        "select melid, performer, title, instrument, avgtempo from solo_info"
    ):
        if not (title_tokens(title) & wanted):
            continue
        melody = list(db.execute("select onset, pitch from melody where melid=?", (melid,)))
        if len(melody) < 50:
            continue
        ref_on = np.array([m[0] for m in melody])
        ref_p = np.array([int(m[1]) for m in melody])
        seed = region[0] - float(ref_on[0])
        offset, rate, hits = fit_affine(ref_on, ref_p, est_on, est_p, seed - 25, seed + 25)
        scored.append(
            {
                "melid": melid,
                "performer": performer,
                "title": title,
                "instrument": instrument,
                "tempo": tempo,
                "offset": offset,
                "rate": rate,
                "match_rate": hits / len(ref_on),
                "ref_on": ref_on,
                "ref_p": ref_p,
            }
        )
    if not scored:
        return None, "no WJazzD solo with a matching title"
    scored.sort(key=lambda c: -c["match_rate"])
    top = scored[0]
    if top["match_rate"] < MIN_MATCH_RATE:
        return None, f"best candidate only {top['match_rate']:.1%} - wrong take or wrong issue"
    runner_up = scored[1]["match_rate"] if len(scored) > 1 else 0.0
    if runner_up > 0 and top["match_rate"] < MIN_MARGIN * runner_up:
        return None, f"{top['match_rate']:.1%} vs {runner_up:.1%} - cannot tell the soloists apart"
    return top, ""


def score(solo, est_on, est_notes):
    """mir_eval note scores over the span the two recordings actually share."""
    import numpy as np

    from swingscribe import metrics
    from swingscribe.model import NoteEvent

    placed = solo["ref_on"] * solo["rate"] + solo["offset"]
    lo, hi = float(placed[0]) - 0.25, float(placed[-1]) + 0.25
    keep = (est_on >= lo) & (est_on <= hi)
    ours = [est_notes[i] for i in np.nonzero(keep)[0]]

    reference = [
        NoteEvent(onset=float(t), duration=0.1, pitch=int(p), confidence=1.0, source="wjazzd")
        for t, p in zip(placed, solo["ref_p"], strict=True)
    ]
    estimate = [
        NoteEvent(
            onset=n["onset"],
            duration=n["duration"],
            pitch=int(n["pitch"]),
            confidence=n["confidence"],
            source="crepe",
        )
        for n in ours
    ]
    result = metrics.score_notes(reference, estimate)
    result["n_ours_in_span"] = float(len(estimate))
    result["span_s"] = hi - lo
    return result


def score_beats(db, melid, grid, offset, rate):
    """Our beat grid against human taps -- mir_eval.beat over the solo."""
    import mir_eval
    import numpy as np

    rows = db.execute("select onset from beats where melid=? order by onset", (melid,))
    taps = [r[0] for r in rows]
    if len(taps) < 10:
        return None
    reference = np.array(taps) * rate + offset
    ours = np.array([b for b in grid if reference[0] - 1 <= b <= reference[-1] + 1])
    if len(ours) < 10:
        return None
    return {
        "f_measure": float(mir_eval.beat.f_measure(reference, ours)),
        "n_reference": len(reference),
        "n_ours": len(ours),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score against the Weimar Jazz Database.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True, help="cached transcriptions")
    parser.add_argument("--grids", type=Path, default=None, help="cached beat grids, optional")
    args = parser.parse_args()

    import numpy as np

    db = sqlite3.connect(args.db)
    runs = json.loads(args.notes.read_text(encoding="utf-8"))
    grids = json.loads(args.grids.read_text(encoding="utf-8")) if args.grids else {}

    rows = []
    for name, run in sorted(runs.items()):
        est_on = np.array([n["onset"] for n in run["notes"]])
        est_p = np.array([int(n["pitch"]) for n in run["notes"]])
        order = np.argsort(est_on)
        est_on, est_p = est_on[order], est_p[order]
        notes = [run["notes"][i] for i in order]

        solo, why = identify(db, name, est_on, est_p, run["region"])
        if solo is None:
            print(f"\n### {name}: SKIPPED - {why}")
            continue
        result = score(solo, est_on, notes)
        beats = None
        if name in grids:
            beats = score_beats(
                db, solo["melid"], grids[name]["beats"], solo["offset"], solo["rate"]
            )
        print(f"\n### {name}")
        print(
            f"  {solo['performer']} - {solo['title']} ({solo['instrument']}, "
            f"{solo['tempo'] or 0:.0f} bpm), melid {solo['melid']}"
        )
        print(
            f"  lined up at offset {solo['offset']:+.2f}s rate {solo['rate']:.4f}; "
            f"{int(result['n_reference'])} of their notes, {int(result['n_ours_in_span'])} of ours"
        )
        print(
            f"  ONSET  F1 {result['onset_f1']:.3f}  (P {result['onset_precision']:.3f} / "
            f"R {result['onset_recall']:.3f})"
        )
        print(
            f"  NOTE   F1 {result['note_f1']:.3f}  (P {result['note_precision']:.3f} / "
            f"R {result['note_recall']:.3f})"
        )
        if beats:
            print(f"  BEATS  F1 {beats['f_measure']:.3f} against {beats['n_reference']} human taps")
        rows.append((name, solo, result, beats))

    if rows:
        print(f"\n===== {len(rows)} solos =====")
        print(f"  mean onset F1 {sum(r[2]['onset_f1'] for r in rows) / len(rows):.3f}")
        print(f"  mean note  F1 {sum(r[2]['note_f1'] for r in rows) / len(rows):.3f}")
        beat_rows = [r for r in rows if r[3]]
        if beat_rows:
            mean_beat = sum(r[3]["f_measure"] for r in beat_rows) / len(beat_rows)
            print(f"  mean beat  F1 {mean_beat:.3f}  over {len(beat_rows)} solos")


if __name__ == "__main__":
    main()
