"""Every transcription error given exactly one cause (docs/error-taxonomy.md).

The WJazzD benchmark says note F1 0.855; this module says where the other
0.145 goes. It takes our notes and a human's for the same recording, already
on one clock (`wjazz.fit_affine`), lets mir_eval decide what is a hit, and
then explains every non-hit with one class from a fixed, ordered rule table.

## Three populations, not two

A reference note we missed and a note we emitted nearby at another pitch are
ONE error, not two. So before anything is classified the unmatched notes on
both sides are paired (`pair_unmatched`): a one-to-one assignment inside
`PAIR_WINDOW_S`, nearest onset first, same pitch preferred. What remains is
a pure miss (a reference note with nothing of ours near it) or a pure false
positive (a note of ours with nothing of theirs near it). Every row in the
classified table belongs to exactly one of `miss`, `fp`, `pair`.

## The rules fire in a fixed order

`RULES` is the table, in decision order, and `classify_*` walk it top to
bottom taking the first rule that fires. The order is a judgement about
which explanation is stronger when two apply, and it is written down there
so a second analyst can disagree with it: a note of ours whose span covers
the missed onset (we heard it as part of something else) beats any frame
evidence about the same instant; digital silence in the stem beats a gate
reading, because a gate reading over silence is not evidence of anything.

Rules that need evidence the caller cannot supply (no stem on disk, no
frame trace, no piano model output) are skipped, never guessed — the
`Evidence` object answers None and the walk continues. `unclassified` is a
class like the others and is counted; the taxonomy is not finished while it
is more than a tenth of the errors.

## What this is not

It does not re-score anything. `mir_eval.transcription.match_notes` with the
benchmark's own tolerances (`metrics.py`: 50 ms, 50 cents, offsets ignored)
decides the hits, and this module only labels the rest; the F1 decomposition
in `f1_deficit` is exact by construction (1 - F1 = (misses + fps) / (R + E)),
which is the control that says the two agree.

Pure Python throughout the rule logic so the rule tests run in CI without
the ml group; numpy, mir_eval and scipy are imported inside the two
functions that need them (CLAUDE.md).
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any

from swingscribe.metrics import ONSET_TOLERANCE_S, PITCH_TOLERANCE_CENTS

# ── constants, each borrowed from the code whose behaviour it explains ────
# Unmatched notes on the two sides are paired if their onsets sit within
# this window. Three times the match tolerance: a note we heard 100 ms late
# is a timing error, not a miss plus an invention.
PAIR_WINDOW_S = 0.15
# Pairing prefers a same-pitch partner: an unmatched note at the same pitch
# 80 ms away is a better account of a missed note than a different pitch
# 40 ms away. The penalty is in seconds of onset distance; the alternative
# reading (no preference) is reported beside it by the script.
PAIR_PITCH_PENALTY_S = 0.05
# A note "covers" an onset when the onset falls inside its span with this
# much slack either side.
COVER_SLACK_S = 0.05
# The frame window a reference note is inspected over: a little before its
# onset (fit residual) and its own duration, floored so a speck reads its
# attack rather than two frames.
FRAME_LEAD_S = 0.03
FRAME_MIN_S = 0.05
# The transcriber's own gates, restated so a class means "this gate held it
# back" (stages/transcribe.py, TranscribeConfig).
VOICING_THRESHOLD = 0.5
MIN_NOTE_S = 0.06
# The line's own register, from D22 (TranscribeConfig.line_register_floor).
LINE_WINDOW_S = 2.0
REGISTER_FLOOR = 12
# The piano model and ours agree on a note within this (piano_onset_tolerance).
ORACLE_TOLERANCE_S = 0.10
# A stem is digitally silent below this RMS (gui/library.SILENT_RMS).
SILENT_RMS = 1e-4
# A gap between two reference onsets at least this long is between PHRASES;
# a shorter one is a rest inside a phrase.
PHRASE_GAP_S = 1.0
# Another stem holding at least this much of the harmonic energy at a false
# positive's pitch, relative to the chosen stem, says the sound is mostly
# elsewhere.
CROSS_STEM_RATIO = 1.0
# A pitch is "at" the reference pitch within this (semitones); CREPE reads
# 20-cent bins and WJazzD pitches are integers.
PITCH_AGREE_ST = 0.5

HORNS = frozenset({"ts", "tp", "as", "tb", "ss", "cl", "cor", "bs", "bcl", "ts-c", "fl", "bar"})


def family_of(instrument: str | None) -> str:
    """WJazzD's instrument code -> horn | piano | guitar | other."""
    code = (instrument or "").strip().lower()
    if code in HORNS:
        return "horn"
    if code == "p":
        return "piano"
    if code == "g":
        return "guitar"
    return "other"


# ── the rule table, in decision order ─────────────────────────────────────
# (population, class, what fires it). `classify_*` walk their population's
# rows in this order and take the first that fires; the doc renders it.
RULES: list[tuple[str, str, str]] = [
    # pairs: a reference note and one of ours within PAIR_WINDOW_S of each other
    ("pair", "timing_late", "same pitch, our onset 50-150 ms AFTER theirs"),
    ("pair", "timing_early", "same pitch, our onset 50-150 ms BEFORE theirs"),
    (
        "pair",
        "attack_transient",
        "pitch differs; a note of ours at the reference pitch begins later inside the note",
    ),
    ("pair", "octave", "onsets within 50 ms, pitch 12 or 24 semitones off"),
    ("pair", "neighbour", "onsets within 50 ms, pitch 1 or 2 semitones off"),
    ("pair", "other_pitch", "onsets within 50 ms, any other pitch"),
    ("pair", "loose", "pitch differs AND onsets 50-150 ms apart (both readings reported)"),
    # misses: a reference note with none of ours within PAIR_WINDOW_S
    (
        "miss",
        "merged",
        "a note of ours at the SAME pitch covers the onset: re-articulation heard as one note",
    ),
    ("miss", "absorbed", "a note of ours at ANOTHER pitch covers the onset: tracked through it"),
    (
        "miss",
        "not_picked",
        "piano: the polyphonic model heard this pitch within 100 ms and the line did not take it",
    ),
    ("miss", "left_stem", "the chosen stem is digitally silent here (R16)"),
    ("miss", "gated", "no frame under the note passes the energy gate while voiced"),
    (
        "miss",
        "unvoiced",
        "frames are energetic but periodicity never reaches the voicing threshold",
    ),
    (
        "miss",
        "too_short",
        "gated frames at the reference pitch exist but the longest run is under min_note_ms",
    ),
    (
        "miss",
        "dropped_register",
        "a run at the reference pitch survived the gates, an octave-plus under our line",
    ),
    (
        "miss",
        "dropped",
        "a run at the reference pitch survived the gates and no note was emitted",
    ),
    ("miss", "tracked_octave", "voiced, energetic frames sit an octave from the reference pitch"),
    ("miss", "tracked_other", "voiced, energetic frames sit at some other pitch"),
    ("miss", "unclassified", "none of the above fired (or no evidence)"),
    # false positives: a note of ours with none of theirs within PAIR_WINDOW_S
    (
        "fp",
        "split_sustain",
        "inside a reference note of the SAME pitch: a held note cut in two (D2)",
    ),
    (
        "fp",
        "body_late",
        "the later note at the reference pitch behind an attack_transient: one mechanism",
    ),
    (
        "fp",
        "bleed_register",
        "more than 12 semitones under the reference line's local median (D22)",
    ),
    (
        "fp",
        "bleed_cross_stem",
        "another stem carries at least as much harmonic energy at this pitch",
    ),
    ("fp", "fragment_octave", "inside a reference note, 12 or 24 semitones off it"),
    ("fp", "fragment_neighbour", "inside a reference note, 1 or 2 semitones off it"),
    ("fp", "fragment_other", "inside a reference note, some other pitch"),
    ("fp", "between_phrases", "no reference note sounding, in a gap of a second or more"),
    ("fp", "between_notes", "no reference note sounding, in a shorter rest"),
    ("fp", "unclassified", "none of the above fired"),
]

CLASSES: dict[str, list[str]] = {}
for _population, _cls, _ in RULES:
    CLASSES.setdefault(_population, []).append(_cls)


# ── evidence the rules may ask for ────────────────────────────────────────


@dataclass
class FrameWindow:
    """The transcriber's per-frame trace under one note (gui/review payload)."""

    hop_s: float
    periodicity: list[float]
    energy_ok: list[bool]
    pitch: list[float | None]  # gated, smoothed: what segment_notes saw
    f0: list[float | None]  # raw CREPE f0 in MIDI

    def __len__(self) -> int:
        return len(self.periodicity)


class Evidence:
    """What the classifier may ask about the recording. Every answer may be
    None, meaning "not available", and the rule that needed it is skipped."""

    def frames(self, t0: float, t1: float) -> FrameWindow | None:
        return None

    def stem_rms(self, t0: float, t1: float) -> float | None:
        return None

    def loudness_db(self, t0: float, t1: float) -> float | None:
        return None

    def cross_stem_ratio(self, t0: float, t1: float, pitch: int) -> float | None:
        return None

    def oracle_has(self, t: float, pitch: int) -> bool | None:
        return None


@dataclass
class ErrorRow:
    population: str
    cls: str
    rule: str
    ref_index: int | None = None
    est_index: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


# ── matching and pairing ──────────────────────────────────────────────────


def match(reference: list[dict], estimate: list[dict]) -> list[tuple[int, int]]:
    """mir_eval's own hits: (reference index, estimate index) pairs under the
    benchmark's tolerances. This is the source of truth for what counts and
    it is not reimplemented here."""
    import mir_eval
    import numpy as np

    from swingscribe.metrics import midi_to_hz

    if not reference or not estimate:
        return []
    ref_i = np.array([[n["onset"], n["onset"] + max(n["duration"], 1e-4)] for n in reference])
    est_i = np.array([[n["onset"], n["onset"] + max(n["duration"], 1e-4)] for n in estimate])
    ref_p = np.array([midi_to_hz(n["pitch"]) for n in reference])
    est_p = np.array([midi_to_hz(n["pitch"]) for n in estimate])
    pairs = mir_eval.transcription.match_notes(
        ref_i,
        ref_p,
        est_i,
        est_p,
        onset_tolerance=ONSET_TOLERANCE_S,
        pitch_tolerance=PITCH_TOLERANCE_CENTS,
        offset_ratio=None,
    )
    return [(int(i), int(j)) for i, j in pairs]


def pair_unmatched(
    reference: list[dict],
    estimate: list[dict],
    ref_free: list[int],
    est_free: list[int],
    window: float = PAIR_WINDOW_S,
    pitch_penalty: float = PAIR_PITCH_PENALTY_S,
) -> list[tuple[int, int]]:
    """One-to-one pairs among the unmatched notes: as many as fit inside
    `window`, then nearest onsets, a same-pitch partner preferred by
    `pitch_penalty` seconds. Minimum-cost assignment, so it is deterministic
    and does not depend on the order the notes are visited in."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if not ref_free or not est_free:
        return []
    big = 1e3
    cost = np.full((len(ref_free), len(est_free)), big)
    for a, i in enumerate(ref_free):
        for b, j in enumerate(est_free):
            dt = abs(estimate[j]["onset"] - reference[i]["onset"])
            if dt <= window:
                penalty = 0.0 if estimate[j]["pitch"] == reference[i]["pitch"] else pitch_penalty
                cost[a, b] = dt + penalty
    rows, cols = linear_sum_assignment(cost)
    return sorted(
        (ref_free[a], est_free[b]) for a, b in zip(rows, cols, strict=True) if cost[a, b] < big
    )


# ── rule helpers ──────────────────────────────────────────────────────────


def _covers(note: dict, t: float) -> bool:
    """Does `note`'s span hold the instant `t`, its own onset excluded?"""
    return note["onset"] + ONSET_TOLERANCE_S < t <= note["onset"] + note["duration"] + COVER_SLACK_S


def _covering(notes: list[dict], t: float, skip: int | None = None) -> list[int]:
    return [k for k, n in enumerate(notes) if k != skip and _covers(n, t)]


def _octave(dpitch: int) -> bool:
    return abs(dpitch) in (12, 24)


def _neighbour(dpitch: int) -> bool:
    return abs(dpitch) in (1, 2)


def _local_median_pitch(notes: list[dict], t: float, window: float = LINE_WINDOW_S) -> float | None:
    near = [n["pitch"] for n in notes if abs(n["onset"] - t) <= window]
    return statistics.median(near) if len(near) >= 3 else None


def _frame_facts(frames: FrameWindow | None, pitch: int) -> dict[str, Any]:
    """The numbers every frame rule reads, computed once per note."""
    if frames is None or len(frames) == 0:
        return {}
    n = len(frames)
    energetic = [bool(e) for e in frames.energy_ok]
    voiced = [p >= VOICING_THRESHOLD for p in frames.periodicity]
    live = [e and v for e, v in zip(energetic, voiced, strict=True)]
    at_ref = [p is not None and abs(p - pitch) <= PITCH_AGREE_ST for p in frames.pitch]
    f0_at_ref = [f is not None and abs(f - pitch) <= PITCH_AGREE_ST for f in frames.f0]
    run = best = 0
    for hit in at_ref:
        run = run + 1 if hit else 0
        best = max(best, run)
    live_f0 = [f for f, ok in zip(frames.f0, live, strict=True) if ok and f is not None]
    return {
        "frames": n,
        "max_periodicity": round(max(frames.periodicity), 3),
        "energetic_frac": round(sum(energetic) / n, 3),
        "live_frac": round(sum(live) / n, 3),
        "f0_at_ref_frac": round(sum(f0_at_ref) / n, 3),
        "run_at_ref_frames": best,
        "live_f0_median": round(statistics.median(live_f0), 2) if live_f0 else None,
    }


def _ref_window(note: dict) -> tuple[float, float]:
    return note["onset"] - FRAME_LEAD_S, note["onset"] + max(note["duration"], FRAME_MIN_S)


def _est_window(note: dict) -> tuple[float, float]:
    return note["onset"], note["onset"] + max(note["duration"], FRAME_MIN_S)


# ── the classifiers ───────────────────────────────────────────────────────


def _body_after(ref: dict, est: dict, estimate: list[dict] | None) -> int | None:
    """Index of the first note of ours at the reference pitch that begins
    after `est` and still inside the reference note, else None."""
    if not estimate:
        return None
    end = ref["onset"] + ref["duration"] + COVER_SLACK_S
    candidates = [
        k
        for k, n in enumerate(estimate)
        if int(n["pitch"]) == int(ref["pitch"]) and est["onset"] < n["onset"] <= end
    ]
    return min(candidates) if candidates else None


def classify_pair(ref: dict, est: dict, estimate: list[dict] | None = None) -> ErrorRow:
    """`estimate` is the whole list our note came from; with it, a pair whose
    pitch differs is checked for a BODY — a later note of ours at the
    reference pitch inside the reference note — which says we split the
    attack off at a pitch of its own (a scoop) rather than misheard it."""
    dt = est["onset"] - ref["onset"]
    dpitch = int(est["pitch"]) - int(ref["pitch"])
    facts = {"dt": round(dt, 3), "dpitch": dpitch}
    if dpitch == 0:
        cls = "timing_late" if dt > 0 else "timing_early"
        return ErrorRow("pair", cls, "same pitch, |dt| > tolerance", evidence=facts)
    body = _body_after(ref, est, estimate)
    if body is not None:
        facts["body_index"] = body
        facts["body_dt"] = round(estimate[body]["onset"] - ref["onset"], 3)
        return ErrorRow(
            "pair",
            "attack_transient",
            "a later note of ours at the reference pitch",
            evidence=facts,
        )
    if abs(dt) <= ONSET_TOLERANCE_S:
        if _octave(dpitch):
            return ErrorRow("pair", "octave", "|dpitch| in {12, 24}", evidence=facts)
        if _neighbour(dpitch):
            return ErrorRow("pair", "neighbour", "|dpitch| in {1, 2}", evidence=facts)
        return ErrorRow("pair", "other_pitch", "any other dpitch", evidence=facts)
    return ErrorRow("pair", "loose", "pitch differs and |dt| > tolerance", evidence=facts)


def classify_miss(
    ref_index: int,
    reference: list[dict],
    estimate: list[dict],
    evidence: Evidence,
    family: str,
) -> ErrorRow:
    ref = reference[ref_index]
    t, pitch = ref["onset"], int(ref["pitch"])
    facts: dict[str, Any] = {}
    # Evidence first, whatever rule ends up firing: every miss carries the
    # frame trace and the piano model's opinion, so a second analyst can read
    # the frame rules over the misses a covering note pre-empted.
    t0, t1 = _ref_window(ref)
    frames = evidence.frames(t0, t1)
    facts.update(_frame_facts(frames, pitch))
    heard = evidence.oracle_has(t, pitch) if family == "piano" else None
    if heard is not None:
        facts["oracle_heard"] = heard

    def row(cls, rule, est_index=None):
        return ErrorRow("miss", cls, rule, ref_index, est_index, facts)

    covering = _covering(estimate, t)
    if covering:
        # Prefer a same-pitch coverer if there is one; report the pitch of
        # whichever explains the miss.
        same = [k for k in covering if int(estimate[k]["pitch"]) == pitch]
        k = same[0] if same else covering[0]
        facts["covered_by_pitch"] = int(estimate[k]["pitch"])
        facts["covered_by_index"] = k
        facts["covering_dpitch"] = int(estimate[k]["pitch"]) - pitch
        if same:
            return row("merged", "same-pitch note of ours covers the onset", k)
        return row("absorbed", "other-pitch note of ours covers the onset", k)

    if heard:
        return row("not_picked", "piano model has this pitch within 100 ms")

    rms = evidence.stem_rms(t0, t1)
    if rms is not None:
        facts["stem_rms"] = rms
        if rms < SILENT_RMS:
            return row("left_stem", "chosen stem RMS below SILENT_RMS")

    if not facts.get("frames"):
        return row("unclassified", "no frame evidence")
    if facts["energetic_frac"] == 0.0:
        return row("gated", "no frame passes the energy gate")
    if facts["max_periodicity"] < VOICING_THRESHOLD:
        return row("unvoiced", "max periodicity below voicing threshold")
    if facts["live_frac"] == 0.0:
        return row("gated", "the voiced frames all fail the energy gate")
    min_frames = round(MIN_NOTE_S / frames.hop_s)
    run = facts["run_at_ref_frames"]
    if 0 < run < min_frames:
        return row("too_short", "run at reference pitch shorter than min_note_ms")
    if run >= min_frames:
        line = _local_median_pitch(estimate, t)
        facts["est_line_median"] = line
        if line is not None and pitch < line - REGISTER_FLOOR:
            return row("dropped_register", "reference pitch under our line's register floor")
        return row("dropped", "run at reference pitch survived gates, no note emitted")
    if facts["live_f0_median"] is not None:
        off = facts["live_f0_median"] - pitch
        facts["live_dpitch"] = round(off, 2)
        if abs(abs(off) - 12) <= PITCH_AGREE_ST or abs(abs(off) - 24) <= PITCH_AGREE_ST:
            return row("tracked_octave", "live frames an octave from the reference")
        return row("tracked_other", "live frames at another pitch")
    return row("unclassified", "frames neither dead nor at any pitch")


def classify_fp(
    est_index: int,
    reference: list[dict],
    estimate: list[dict],
    evidence: Evidence,
    family: str,
) -> ErrorRow:
    est = estimate[est_index]
    t, pitch = est["onset"], int(est["pitch"])
    facts: dict[str, Any] = {}

    covering = _covering(reference, t)
    same = [k for k in covering if int(reference[k]["pitch"]) == pitch]
    if covering:
        k = same[0] if same else covering[0]
        facts["inside_ref_index"] = k
        facts["inside_ref_onset"] = round(reference[k]["onset"], 3)
        facts["inside_ref_duration"] = round(reference[k]["duration"], 3)
    if same:
        facts["inside_ref_pitch"] = pitch
        return ErrorRow(
            "fp", "split_sustain", "inside a same-pitch reference note", None, est_index, facts
        )

    line = _local_median_pitch(reference, t)
    if line is not None:
        facts["under_ref_line"] = round(line - pitch, 1)
        if pitch < line - REGISTER_FLOOR:
            return ErrorRow(
                "fp",
                "bleed_register",
                "more than 12 semitones under the reference line",
                None,
                est_index,
                facts,
            )

    t0, t1 = _est_window(est)
    ratio = evidence.cross_stem_ratio(t0, t1, pitch)
    if ratio is not None:
        facts["cross_stem_ratio"] = round(ratio, 3)
        if ratio >= CROSS_STEM_RATIO:
            return ErrorRow(
                "fp",
                "bleed_cross_stem",
                "another stem holds as much energy at this pitch",
                None,
                est_index,
                facts,
            )

    if covering:
        k = covering[0]
        dpitch = pitch - int(reference[k]["pitch"])
        facts["inside_ref_pitch"] = int(reference[k]["pitch"])
        facts["dpitch"] = dpitch
        if _octave(dpitch):
            return ErrorRow(
                "fp",
                "fragment_octave",
                "inside a reference note, an octave off",
                None,
                est_index,
                facts,
            )
        if _neighbour(dpitch):
            return ErrorRow(
                "fp",
                "fragment_neighbour",
                "inside a reference note, a step off",
                None,
                est_index,
                facts,
            )
        return ErrorRow(
            "fp", "fragment_other", "inside a reference note, another pitch", None, est_index, facts
        )

    before = [n["onset"] for n in reference if n["onset"] <= t]
    after = [n["onset"] for n in reference if n["onset"] > t]
    if before and after:
        gap = min(after) - max(before)
        facts["ref_gap_s"] = round(gap, 3)
        if gap >= PHRASE_GAP_S:
            return ErrorRow(
                "fp",
                "between_phrases",
                "in a reference gap of a second or more",
                None,
                est_index,
                facts,
            )
        return ErrorRow(
            "fp", "between_notes", "in a reference gap under a second", None, est_index, facts
        )
    if before or after:
        facts["ref_gap_s"] = None
        return ErrorRow(
            "fp",
            "between_phrases",
            "outside the reference's first or last note",
            None,
            est_index,
            facts,
        )
    return ErrorRow("fp", "unclassified", "no reference notes at all", None, est_index, facts)


# ── one solo, end to end ──────────────────────────────────────────────────


@dataclass
class SoloErrors:
    rows: list[ErrorRow]
    matched: list[tuple[int, int]]
    pairs: list[tuple[int, int]]
    n_reference: int
    n_estimate: int
    # How many pairs the alternative pairing (no same-pitch preference)
    # would have made differently — the "both readings" number.
    pairs_alternative_differ: int = 0

    @property
    def note_f1(self) -> float:
        if self.n_reference + self.n_estimate == 0:
            return 1.0
        return 2.0 * len(self.matched) / (self.n_reference + self.n_estimate)


def classify_solo(
    reference: list[dict],
    estimate: list[dict],
    evidence: Evidence | None = None,
    family: str = "horn",
) -> SoloErrors:
    """Match, pair, then give every non-hit its one class."""
    evidence = evidence or Evidence()
    matched = match(reference, estimate)
    ref_hit = {i for i, _ in matched}
    est_hit = {j for _, j in matched}
    ref_free = [i for i in range(len(reference)) if i not in ref_hit]
    est_free = [j for j in range(len(estimate)) if j not in est_hit]
    pairs = pair_unmatched(reference, estimate, ref_free, est_free)
    alternative = pair_unmatched(reference, estimate, ref_free, est_free, pitch_penalty=0.0)
    differ = len(set(pairs) - set(alternative))

    rows: list[ErrorRow] = []
    paired_ref = {i for i, _ in pairs}
    paired_est = {j for _, j in pairs}
    bodies: dict[int, int] = {}
    for i, j in pairs:
        row = classify_pair(reference[i], estimate[j], estimate)
        row.ref_index, row.est_index = i, j
        row.evidence.update(
            _frame_facts(evidence.frames(*_ref_window(reference[i])), int(reference[i]["pitch"]))
        )
        if row.cls == "attack_transient":
            bodies[row.evidence["body_index"]] = i
        rows.append(row)
    for i in ref_free:
        if i not in paired_ref:
            row = classify_miss(i, reference, estimate, evidence, family)
            k = row.evidence.get("covered_by_index")
            if k is not None:
                row.evidence["covered_by_matched"] = k in est_hit
                row.evidence["covered_by_duration"] = round(estimate[k]["duration"], 3)
            rows.append(row)
    for j in est_free:
        if j not in paired_est:
            row = classify_fp(j, reference, estimate, evidence, family)
            # The body behind an attack transient is the same mechanism as
            # the transient; it keeps its own row (it costs F1) under a
            # class that says so, rather than reading as a split sustain.
            if j in bodies and row.cls == "split_sustain":
                row.cls, row.rule = "body_late", "body of an attack_transient"
                row.evidence["transient_ref_index"] = bodies[j]
            rows.append(row)
    return SoloErrors(rows, matched, pairs, len(reference), len(estimate), differ)


# ── aggregation ───────────────────────────────────────────────────────────


def class_counts(rows: list[ErrorRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.cls] = counts.get(row.cls, 0) + 1
    return counts


def f1_deficit(solo: SoloErrors) -> dict[str, float]:
    """Each class's share of this solo's (1 - note F1), exactly.

    1 - F1 = (R - M + E - M) / (R + E): every miss and every false positive
    costs 1/(R + E) and a pair costs both. Summed over classes this is the
    solo's whole deficit, so a mean over solos of these shares sums to
    1 - mean F1 — the control that this decomposition and mir_eval agree.
    """
    total = solo.n_reference + solo.n_estimate
    out: dict[str, float] = {}
    if total == 0:
        return out
    for row in solo.rows:
        weight = 2.0 if row.population == "pair" else 1.0
        out[row.cls] = out.get(row.cls, 0.0) + weight / total
    return out


def bootstrap_noise(
    per_solo_counts: list[dict[str, int]], resamples: int = 1000, seed: int = 0
) -> dict[str, dict[str, float]]:
    """How much each class's count and share wobble when the SOLOS are
    resampled with replacement. Classification is deterministic, so this is
    not measurement noise — it is how far a class's size depends on which
    solos happen to be in the set, which is the scale a later change has to
    beat before it is about the transcriber rather than the sample."""
    rng = random.Random(seed)
    classes = sorted({cls for counts in per_solo_counts for cls in counts})
    n = len(per_solo_counts)
    if n == 0:
        return {}
    samples: dict[str, list[float]] = {cls: [] for cls in classes}
    shares: dict[str, list[float]] = {cls: [] for cls in classes}
    for _ in range(resamples):
        draw = [per_solo_counts[rng.randrange(n)] for _ in range(n)]
        totals = {cls: sum(c.get(cls, 0) for c in draw) for cls in classes}
        grand = sum(totals.values()) or 1
        for cls in classes:
            samples[cls].append(totals[cls])
            shares[cls].append(totals[cls] / grand)
    return {
        cls: {
            "count_sd": statistics.pstdev(samples[cls]),
            "share_sd": statistics.pstdev(shares[cls]),
        }
        for cls in classes
    }


def compare_counts(
    current: dict[str, int], pinned: dict[str, int], noise: dict[str, dict[str, float]]
) -> list[tuple[str, int, int, float]]:
    """Every class whose count differs from the pin, with the noise scale it
    is measured against: (class, pinned, current, count_sd)."""
    movers = []
    for cls in sorted(set(current) | set(pinned)):
        was, now = pinned.get(cls, 0), current.get(cls, 0)
        if was != now:
            movers.append((cls, was, now, noise.get(cls, {}).get("count_sd", 0.0)))
    return movers
