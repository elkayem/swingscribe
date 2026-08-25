"""Score the pipeline against the Weimar Jazz Database's hand transcriptions.

    uv run python scripts/score_wjazz.py --db wjazz/wjazzd.db --notes cache.json

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
import sqlite3
from pathlib import Path

from swingscribe.wjazz import (
    CONFIDENT_MATCH_RATE,
    MIN_MARGIN,
    MIN_MATCH_RATE,
    fit_affine,
    title_tokens,
)


def candidates(db, name, est_on, est_p, region):
    """Every WJazzD solo with a matching title, fitted, best first."""
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
        offset, rate, hits = fit_affine(ref_on, ref_p, est_on, est_p, region)
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
    scored.sort(key=lambda c: -c["match_rate"])
    return scored


def identify_all(db, name, est_on, est_p, region):
    """Which WJazzD solos this audio holds. Possibly more than one.

    A transcribed span can cover a whole tune, and a whole tune can have three
    annotated solos in it. Each one is an independent test of the transcriber
    against a different player on different material, so scoring only the best
    throws away evidence — and the margin rule, which exists to reject a solo
    we did NOT find, was rejecting the case where we found two.

    Each accepted solo is scored over its own time span (see `score`), so one
    player's notes are never counted against another's.
    """
    scored = candidates(db, name, est_on, est_p, region)
    if not scored:
        return [], "no WJazzD solo with a matching title"
    confident = [c for c in scored if c["match_rate"] >= CONFIDENT_MATCH_RATE]
    if confident:
        return confident, ""
    top = scored[0]
    if top["match_rate"] < MIN_MATCH_RATE:
        return [], f"best candidate only {top['match_rate']:.1%} - wrong take or wrong issue"
    runner_up = scored[1]["match_rate"] if len(scored) > 1 else 0.0
    if runner_up > 0 and top["match_rate"] < MIN_MARGIN * runner_up:
        return [], f"{top['match_rate']:.1%} vs {runner_up:.1%} - cannot tell the soloists apart"
    return [top], ""


def identify(db, name, est_on, est_p, region):
    """The single best solo, or None. Kept for callers wanting one answer."""
    found, why = identify_all(db, name, est_on, est_p, region)
    return (found[0] if found else None), why


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
