"""The benchmark's bookkeeping: whether a change is real, which tracks may be
looked at, how far a reference page can be trusted, whether confidence points
at the errors, and which kinds of music a mean is made of (docs/roadmap.md,
E1-E3, E5, E6).

Nothing here aligns or scores notes -- that is `benchmark.py` and mir_eval
(`note_hits` asks mir_eval which notes it matched; it decides nothing).
These are the questions the harness asks ABOUT its scores:

- **Is a change distinguishable from noise?** `paired_change` compares the
  same tracks before and after: the mean delta, a bootstrap interval that
  resamples RECORDINGS (the three So What solos are one recording, not three
  draws), and an exact sign test over recordings. The harness shipped rules on
  differences like +0.007 with 7 of 12 pages up, which a sign test puts at
  p = 0.77.
- **May this track be looked at?** `Split`: everything in the benchmark on
  2026-09-29 is DEV, because it has been looked at. A track added since is
  dev or TEST by a salted hash of its tune title, so every version of a tune
  -- and every soloist on one recording -- falls on one side. Test tracks are
  scored only at a release (`run_eval --test`), and the figure prior is never
  counted from a test page.
- **How good is the reference?** `page_tier`: a PDF page read by OMR is not a
  hand score. Silver is a vector page whose printed noteheads were counted and
  read, whose bars fill their signatures; bronze is the rest, scans included.
  The gates were set from the pages' reading quality before any page was
  scored, and moving them to improve a score would defeat them. A bar-line
  step is judged on the UNROUNDED offsets either side, net of the page's
  overfull bars: a whole beat left over is the grid's, nothing left over
  where the page overruns is the page's slip, and anything else is left
  undecided (`page_steps`).
- **Does confidence point at the errors?** `confidence_ranking`: rank our
  notes by confidence and ask whether the wrong ones (mir_eval's false
  positives, `note_hits`) or the listener's erasures sit at the bottom. A
  review that starts from the least confident notes is only cheaper if they
  are where the errors are, and that can improve while F1 stands still.
- **What is a mean made of?** `strata`: the same mean per tempo class, style
  or instrument, each with its n. A mixed mean is how the ballad gap (D16)
  stayed invisible; strata are printed, never pinned.

Standard library at import: `scripts/figure_prior.py` imports this and runs
anywhere the corpus does. numpy is imported inside `paired_change` only, and
mir_eval inside `note_hits`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

# ── is a change real ─────────────────────────────────────────────────────────


def sign_test(up: int, down: int) -> float:
    """Exact two-sided sign test: the chance of a split at least this uneven
    between `up` and `down` if each were a coin flip. Level pairs are not
    counted -- they are neither."""
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class PairedChange:
    """One measure's change over the same tracks, before -> after."""

    n: int  # tracks paired
    recordings: int  # the independent units the interval resamples
    mean: float  # mean per-track delta
    low: float  # interval on the mean delta
    high: float
    up: int  # recordings whose mean delta rose past the tolerance
    down: int
    level: int
    p: float  # sign test over recordings

    @property
    def decided(self) -> bool:
        """The interval excludes zero."""
        return self.low > 0.0 or self.high < 0.0


def paired_change(
    before: list[float],
    after: list[float],
    recordings: list[str] | None = None,
    *,
    tolerance: float = 0.0,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> PairedChange:
    """The change from `before` to `after`, paired by position.

    `recordings` names the recording each pair belongs to; pairs that share
    one are resampled together and counted once by the sign test. None makes
    every pair its own recording. The mean inside a resample is over TRACKS
    (a recording holding three solos weighs three), so it is the same mean the
    scorecard prints. The seed is fixed: the same two cards always print the
    same interval.
    """
    import numpy as np

    if len(before) != len(after):
        raise ValueError(f"{len(before)} values before and {len(after)} after")
    if not before:
        raise ValueError("nothing to compare")
    deltas = np.asarray(after, dtype=float) - np.asarray(before, dtype=float)
    labels = list(recordings) if recordings is not None else [str(i) for i in range(len(deltas))]
    if len(labels) != len(deltas):
        raise ValueError(f"{len(labels)} recording labels for {len(deltas)} pairs")
    groups: dict[str, list[int]] = {}
    for i, label in enumerate(labels):
        groups.setdefault(label, []).append(i)
    sums = np.array([deltas[idx].sum() for idx in groups.values()])
    counts = np.array([len(idx) for idx in groups.values()], dtype=float)

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(groups), size=(resamples, len(groups)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])

    per_recording = sums / counts
    up = int((per_recording > tolerance).sum())
    down = int((per_recording < -tolerance).sum())
    return PairedChange(
        n=len(deltas),
        recordings=len(groups),
        mean=float(deltas.mean()),
        low=float(low),
        high=float(high),
        up=up,
        down=down,
        level=len(groups) - up - down,
        p=sign_test(up, down),
    )


# ── may this track be looked at ──────────────────────────────────────────────


def normalize_title(text: str) -> str:
    """A tune title as a split key: lower case, letters and digits only, so
    "Star Dust", "Stardust" and "STAR-DUST" are one tune."""
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("'", "").replace("’", ""))


@dataclass(frozen=True)
class Split:
    """Which tracks are held out. `dev` is every group already in the
    benchmark when the split was frozen; everything else is test when its
    salted hash falls under `test_share`."""

    salt: str
    test_share: float
    dev: frozenset[str]

    def is_test(self, group: str) -> bool:
        key = normalize_title(group)
        if not key or key in self.dev:
            return False
        digest = hashlib.sha256(f"{self.salt}\x00{key}".encode()).hexdigest()
        return int(digest[:8], 16) / 2**32 < self.test_share


def load_split(path: str | Path) -> Split:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Split(
        salt=data["salt"],
        test_share=float(data["test_share"]),
        dev=frozenset(normalize_title(g) for g in data["dev"]),
    )


def page_group(manifest_entry: dict | None, file_stem: str) -> str:
    """The split group of a PDF transcription: the title pdf2musicxml read
    off the page, else the file's own name. One definition, because the
    figure prior's build and the harness must agree on which pages are test."""
    title = (manifest_entry or {}).get("title") or ""
    return title if normalize_title(title) else file_stem


# ── how good is the reference ────────────────────────────────────────────────

# A silver page: at most this share of the printed noteheads went unread...
SILVER_MAX_UNREAD = 0.05
# ...at most this share of what was read is not printed on the page...
SILVER_MAX_UNPRINTED = 0.05
# ...and at least this share of its bars fill their time signature. On the
# 222 vector pages of 2026-09-29 these admit 170.
SILVER_MIN_FILLED = 0.90


def page_tier(manifest_entry: dict | None, filled_share: float | None) -> str:
    """The tier of an OMR-read page, "silver" or "bronze" (docs/roadmap.md, E3).

    A scan prints no note count, so nothing checked its reading and it is
    bronze whatever its bars do. `filled_share` is the share of the page's
    bars whose notes and rests fill the signature (figure_prior's reader).
    """
    entry = manifest_entry or {}
    printed = entry.get("printed_noteheads") or 0
    if not printed or filled_share is None:
        return "bronze"
    unread = (entry.get("unread_printed") or 0) / printed
    unprinted = (entry.get("unprinted_read") or 0) / printed
    if (
        unread <= SILVER_MAX_UNREAD
        and unprinted <= SILVER_MAX_UNPRINTED
        and filled_share >= SILVER_MIN_FILLED
    ):
        return "silver"
    return "bronze"


@dataclass(frozen=True)
class PageBar:
    """One measure of an OMR-read page, where the score reader puts it."""

    number: str  # the printed measure number
    start: float  # quarters from the page's first measure, as the reader places it
    filled: float  # quarters the reader's cursor advances through it (`reader_bars`)
    length: float  # quarters its signature calls for

    @property
    def fills(self) -> bool:
        return abs(self.filled - self.length) < 1e-9

    @property
    def overrun(self) -> float:
        """Beats the reader's cursor runs past the signature: every later
        note sits this much later on the page. A short bar is padded, 0."""
        return self.filled - self.length if self.filled > self.length and not self.fills else 0.0


def page_bars(measures: list[tuple[str, float, float]]) -> list[PageBar]:
    """(number, filled, length) per measure -> PageBars placed the way
    `mscz.parse_musicxml` places them: a short bar is padded to its
    signature, an overfull one keeps every beat it holds."""
    out, start = [], 0.0
    for number, filled, length in measures:
        out.append(PageBar(str(number), start, filled, length))
        start += max(filled, length)
    return out


def reader_bars(path) -> list[PageBar]:
    """A MusicXML page's measures, `filled` as the SCORE READER fills them.

    What moves every later note on the page is how far `mscz.parse_musicxml`
    advances its cursor through a bar: to where the LAST voice ends, padded
    to the signature. A bar whose first voice overruns and whose last voice
    fits moves nothing, however many beats its fullest voice holds -- so the
    step check must not read `filled` off the fullest voice, as the figure
    prior's reader does for its own purpose (its `filled` asks whether ANY
    voice overruns). This walks the elements with parse_musicxml's cursor
    arithmetic, element for element, and a test holds the two together on a
    page of two voices; one walker in mscz.py would be better, and that file
    is the next change to make it so.
    """
    from xml.etree import ElementTree

    root = ElementTree.parse(path).getroot()
    part = root.find("part")
    if part is None:
        return []
    beats_per_bar, divisions = 4.0, 1.0
    measures = []
    for index, measure in enumerate(part.findall("measure")):
        if (value := measure.findtext("attributes/divisions")) is not None:
            divisions = float(value) or 1.0
        beats = measure.findtext("attributes/time/beats")
        beat_type = measure.findtext("attributes/time/beat-type")
        if beats and beat_type:
            beats_per_bar = float(beats) * 4.0 / float(beat_type)
        cursor = 0.0
        for element in measure:
            duration = float(element.findtext("duration") or 0) / divisions
            if element.tag == "backup":
                cursor -= duration
            elif element.tag == "forward":
                cursor += duration
            elif element.tag == "note":
                chord = element.find("chord") is not None
                if element.find("rest") is not None or not chord:
                    cursor += duration  # a rest always advances, a chord tone never
        measures.append((measure.get("number", str(index + 1)), cursor, beats_per_bar))
    return page_bars(measures)


# How far a step's residual (`page_steps`) may sit from a whole number of
# beats and still be read as that whole number: a quarter of a beat,
# inclusive. It is the trace's own label arithmetic turned on the residual,
# not a number fitted to a page. The trace labels an offset
# `round(2 * offset) / 2`, so it names everything within a quarter beat of a
# half-beat value by that value and cannot tell two offsets in one bin apart:
# a quarter is half its resolution. Python sends a tie to the EVEN count of
# half beats, which is always a whole beat, so the trace labels an offset
# exactly a quarter from a whole number with that whole number; the check
# reads a residual the same way, so the bound is inclusive. A residual the
# trace would label a half beat is neither a grid's whole beat nor nothing.
STEP_MATCH = 0.25
# Float dust: the reader's fills carry it (4.250000000000001), and a triplet
# offset is a third.
_DUST = 1e-6


def page_overrun(bars: list[PageBar], low: float, high: float) -> list[PageBar]:
    """The overfull bars the reader's cursor leaves between two page
    positions: each moved every note after its END later by its overrun, and
    a note inside it by some part of that no one can place, so a bar is
    counted where it ends."""
    return [b for b in bars if b.overrun and low < b.start + b.filled <= high]


def _label(offset: float) -> float:
    """An offset as the trace labels it: to the half beat, a quarter-beat tie
    to the even count of half beats (Python's round), dust first."""
    return round(2.0 * round(offset, 6)) / 2.0


def page_steps(
    trace: dict, bars: list[PageBar], bar: float, differences: list[tuple[float, float]]
) -> list[dict]:
    """For each step of a bar-line trace (`score_bars.difference_trace`),
    whose it is -- the page's, the grid's, or undecided -- and which page
    bars account for it.

    A step is where our position minus the page's changes, and three things
    move that difference. The GRID adds or drops whole beats (a beat the
    tracker missed or doubled, a chorus the reference omits). The PAGE's
    reader moves every note after an overfull bar later by that bar's
    overrun -- any fraction: an OMR engine that read six beats into a bar of
    4/4 makes a step of -2 (Gingerbread Boy's bar 102, 2026-09-29), one that
    read 4.25 and 4.125 into bars 26 and 28 leaves every later note 0.375 of
    a beat late (Embraceable You). And OUR LINE sits a fraction of a beat
    off the page wherever it was written differently -- a phrase a
    sixteenth later -- which moves from passage to passage and is neither.

    The trace's labels cannot tell them apart. Each is a run's offset
    rounded to the half beat, so an offset near a quarter flips between two
    labels (Embraceable You's runs sit at -0.375, -0.125, -0.375 and read
    -0.5, 0, -0.5), and a grid's whole beat under a fractional offset can
    read as a label change of half a beat. The rule before this one judged
    the labels and gave every half-beat step to the page, which handed the
    page a grid's dropped beat wherever the offset beside it was fractional
    (review, 2026-09-30); and half-beat steps are not the page's by
    construction -- WJazzD's annotation, which no OMR reader touched,
    traces them too (Hancock's Gingerbread Boy, +0.5 at bar 6).

    So a step is judged UNROUNDED. `differences` are the matched notes the
    trace was built from, (our position, ours minus theirs) each
    (`score_bars._matched_differences` on the same notes); a run's offset is
    the median of its notes', and the step's `change` is the after run's
    median less the before run's. The page's `overrun` across the step is
    summed over the overfull bars the reader leaves between the BULK of each
    run (the middle of its page positions): the median, like the label,
    follows the majority of a run's notes, and an overfull bar inside a run
    moves only the notes after it -- Embraceable You's bars 26 and 28 sit
    inside the run labelled 0, whose last notes are bar 30, and are summed
    at the step after that run. The `residual` is the change with the
    page's overrun taken out (change plus overrun: the reader moves notes
    later, ours minus theirs down). Then, with STEP_MATCH the tolerance:

    - a residual near a whole number other than zero is the GRID's: it
      added or dropped that many beats, whatever the page did beside it;
    - a residual near zero is the PAGE's only if the page MADE the step:
      add back to each run's median the page's overrun standing at that
      run's bulk, label both the way the trace does, and the labels agree
      -- without the page's overruns the trace would not have stepped here.
      This is a counterfactual, not a rule about the overrun's size: a
      page running an eighth late while our line moves a sixteenth still
      steps without the page (our line's), and a page running a half beat
      late can push an exact-quarter tie across a label (the page's) --
      both cases a review built through the real trace (2026-09-30), and
      the rule before this one got both wrong;
    - anything else is UNDECIDED: a residual the trace would label a half
      beat, or a step that stands without the page -- the trace rounding
      an offset that is ours.

    `bars` must be placed as the reader places them (`reader_bars`), or a
    bar whose fullest voice overruns would account for a step the reader
    never made. The reader pads a short bar to its signature, so a short
    bar cannot move a note after it: one within a bar of the step is named
    and never counted. A whole-bar step with no overfull bar behind it (a
    bar the engine dropped or added) reads as the grid's, unchecked.

    Returns one dict per step: `step` (the trace's), `before` and `after`
    (the two runs' median offsets), `change`, `bars` (the overfull bars the
    page crossed between the runs, and short bars at the step), `overrun`
    (beats the page moved across the step), `standing` (every overfull bar
    the reader leaves before the after run's bulk) and `standing_overrun`
    (their sum), `residual`, and `verdict`: "page", "grid" or "undecided".
    """
    segments = trace.get("segments", [])
    if not segments:
        return []

    def bulk(segment: dict) -> float:
        return (segment["from"] + segment["to"]) / 2.0 - segment["offset"]

    def median_offset(segment: dict) -> float:
        run = [d for position, d in differences if segment["from"] <= position <= segment["to"]]
        if not run:
            raise ValueError(
                f"no matched note in the run at {segment['from']:g}-{segment['to']:g}: "
                "the differences are not this trace's"
            )
        return statistics.median(run)

    medians = [median_offset(segment) for segment in segments]
    out = []
    steps = zip(trace.get("steps", []), segments, segments[1:], medians, medians[1:], strict=False)
    for step, before, after, was, now in steps:
        moved = page_overrun(bars, bulk(before), bulk(after))
        low = before["to"] - before["offset"] - bar
        high = after["from"] - after["offset"] + bar
        short = [
            b
            for b in bars
            if b.filled < b.length and not b.fills and b.start < high and b.start + b.length > low
        ]
        overrun = sum(b.overrun for b in moved)
        standing = page_overrun(bars, -math.inf, bulk(after))
        standing_overrun = sum(b.overrun for b in standing)
        standing_before = sum(b.overrun for b in page_overrun(bars, -math.inf, bulk(before)))
        change = now - was
        residual = change + overrun
        whole = round(residual)
        if abs(residual - whole) > STEP_MATCH + _DUST:
            verdict = "undecided"
        elif whole:
            verdict = "grid"
        elif _label(was + standing_before) == _label(now + standing_overrun):
            verdict = "page"  # with the page's overruns out, no step
        else:
            verdict = "undecided"
        out.append(
            {
                "step": step,
                "before": was,
                "after": now,
                "change": change,
                "bars": sorted(moved + short, key=lambda b: b.start),
                "overrun": overrun,
                "standing": standing,
                "standing_overrun": standing_overrun,
                "residual": residual,
                "verdict": verdict,
            }
        )
    return out


def _held(bars: list[PageBar]) -> str:
    return ", ".join(f"page bar {b.number} holds {b.filled:g} of {b.length:g} beats" for b in bars)


def _signed(beats: float) -> str:
    return f"{round(beats, 2) + 0.0:+.2f}"  # + 0.0: never print "-0.00"


def _running_late(item: dict) -> str:
    late, standing = item["standing_overrun"], item["standing"]
    amount = f"{late:g} of a beat" if late < 1 else f"{late:g} beats"
    plural = "s" if len(standing) > 1 else ""
    numbers = ", ".join(b.number for b in standing)
    return f"the page runs {amount} late since page bar{plural} {numbers}"


def describe_page_steps(found: list[dict]) -> str:
    """The annotation a trace line carries: the steps that are the page's and
    the page bars behind them, a grid's step only where a page bar near it
    was ruled out, and then, separately, every undecided step with its
    residual. A grid's step with no page bar near it says nothing."""
    decided, undecided = [], []
    for item in found:
        step = item["step"]
        head = f"{step['change']:+.1f} at bar {step['bar']}: "
        held = _held(item["bars"])
        lead = f"{held}; " if held else ""
        residual = f"residual {_signed(item['residual'])}"
        if item["verdict"] == "grid":
            if held:
                decided.append(
                    f"{head}{held} -- not this step ({residual}, a whole beat: the grid's)"
                )
        elif item["verdict"] == "page" and item["overrun"]:
            decided.append(f"{head}{held} -- the page's step ({residual})")
        elif item["verdict"] == "page":
            decided.append(
                f"{head}{lead}nothing the trace resolves moved across it ({residual}); "
                f"{_running_late(item)}, which the trace rounds to half beats -- the page's step"
            )
        elif abs(item["residual"]) <= STEP_MATCH + _DUST:
            undecided.append(
                f"{head}{lead}nothing the trace resolves moved across it ({residual}), and the "
                "trace would step here without the page's overruns: rounding an offset that "
                "is not the page's"
            )
        else:
            undecided.append(
                f"{head}{lead}{residual} with the page's overrun out: not a whole beat, "
                "so not the grid's, and not what the page moved"
            )
    text = "; ".join(decided)
    if undecided:
        text += (". " if text else "") + "Undecided: " + "; ".join(undecided)
    return text


# ── does confidence point at the errors ──────────────────────────────────────

# The review fractions reported: the least-confident tenth and fifth of notes.
LOW_SHARES = (0.1, 0.2)


@dataclass(frozen=True)
class ConfidenceRanking:
    """Our notes ranked by confidence against a flag (wrong, or erased)."""

    n: int  # notes ranked
    flagged: int  # of them wrong (or erased)
    # The chance a flagged note is LESS confident than an unflagged one, ties
    # counted half: 0.5 is a confidence that knows nothing, 1.0 one that puts
    # every error below every good note. None when either class is empty.
    auc: float | None
    # The share of all flagged notes among the least-confident 10% / 20% of
    # notes. A confidence that knows nothing reads 0.10 / 0.20.
    low_10: float | None
    low_20: float | None


def _mid_ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties sharing their mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def share_in_lowest(confidences: list[float], flagged: list[bool], fraction: float) -> float:
    """The share of the flagged notes among the least-confident `fraction` of
    all notes. A tie that straddles the cut is counted in proportion -- the
    expected share under a random tie-break -- because the piano model's
    confidence takes about fifty distinct values and a sort order would
    otherwise decide the answer."""
    total = sum(flagged)
    if not total or not confidences:
        return 0.0
    budget = fraction * len(confidences)
    groups: dict[float, list[int]] = {}
    for value, flag in zip(confidences, flagged, strict=True):
        groups.setdefault(value, [0, 0])
        groups[value][0] += 1
        groups[value][1] += int(flag)
    caught, used = 0.0, 0.0
    for value in sorted(groups):
        size, wrong = groups[value]
        if used >= budget:
            break
        take = min(size, budget - used)
        caught += wrong * take / size
        used += take
    return caught / total


def confidence_ranking(confidences: list[float], flagged: list[bool]) -> ConfidenceRanking:
    """Does low confidence point at the flagged notes? (docs/roadmap.md E5)

    The AUC is the Mann-Whitney statistic from mid-ranks, so it needs no
    library and ties are exact. The two shares are what a review that starts
    at the bottom of the confidence order would find.
    """
    if len(confidences) != len(flagged):
        raise ValueError(f"{len(confidences)} confidences for {len(flagged)} flags")
    n, bad = len(confidences), sum(bool(f) for f in flagged)
    good = n - bad
    if not bad or not good:
        return ConfidenceRanking(n, bad, None, None, None)
    ranks = _mid_ranks([float(c) for c in confidences])
    good_rank_sum = sum(r for r, f in zip(ranks, flagged, strict=True) if not f)
    # Pairs (good, bad) with the good note ranked above: U of the good class.
    above = good_rank_sum - good * (good + 1) / 2.0
    flags = [bool(f) for f in flagged]
    low_10, low_20 = (share_in_lowest(list(confidences), flags, s) for s in LOW_SHARES)
    return ConfidenceRanking(n, bad, above / (good * bad), low_10, low_20)


def note_hits(reference, estimate) -> list[bool]:
    """For each of our notes, whether mir_eval matched it to a reference note.

    The SAME match `metrics.score_notes` scores (mir_eval's `match_notes`
    under its onset and pitch tolerances, offsets ignored), asked for the
    pairs instead of the counts -- so a note flagged wrong here is exactly one
    of the false positives in the note precision beside it, which the harness
    checks. `reference` and `estimate` are NoteEvents.
    """
    import mir_eval

    from swingscribe.metrics import (
        ONSET_TOLERANCE_S,
        PITCH_TOLERANCE_CENTS,
        _intervals_and_pitches,
    )

    if not reference or not estimate:
        return [False] * len(estimate)
    ref_intervals, ref_pitches = _intervals_and_pitches(reference)
    est_intervals, est_pitches = _intervals_and_pitches(estimate)
    matching = mir_eval.transcription.match_notes(
        ref_intervals,
        ref_pitches,
        est_intervals,
        est_pitches,
        onset_tolerance=ONSET_TOLERANCE_S,
        pitch_tolerance=PITCH_TOLERANCE_CENTS,
        offset_ratio=None,
    )
    hit = {int(est) for _ref, est in matching}
    return [i in hit for i in range(len(estimate))]


# ── what a mean is made of ───────────────────────────────────────────────────

# WJazzD's own `tempoclass` bands (min and max avgtempo per class over its 456
# solos: SLOW 37-79, MEDIUM SLOW 82-109, MEDIUM 112-140, MEDIUM UP 141-179,
# UP 180-361), so a notation set's strata read on the database's scale --
# the same bands scripts/error_taxonomy.py tables by.
TEMPO_CLASSES = ((80.0, "SLOW"), (112.0, "MEDIUM SLOW"), (140.0, "MEDIUM"), (180.0, "MEDIUM UP"))
TEMPO_CLASS_ORDER = ("SLOW", "MEDIUM SLOW", "MEDIUM", "MEDIUM UP", "UP")


def tempo_class(bpm: float | None) -> str | None:
    """A tempo in WJazzD's classes; None for no tempo at all."""
    if not bpm or bpm <= 0:
        return None
    for ceiling, name in TEMPO_CLASSES:
        if bpm < ceiling:
            return name
    return "UP"


def strata(rows, by: str, fields) -> dict[str, dict[str, float]]:
    """{stratum: {field: mean, field_n: count}} over `rows` (dicts) grouped by
    their `by` value. Each field keeps its own n -- a solo can carry a note F1
    and no beat F1 -- and a row without a `by` value is in no stratum."""
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        key = row.get(by)
        if key is None or key == "":
            continue
        cell = grouped.setdefault(str(key), {})
        for field in fields:
            value = row.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell.setdefault(field, []).append(float(value))
    out: dict[str, dict[str, float]] = {}
    for key, cell in grouped.items():
        entry: dict[str, float] = {}
        for field, values in cell.items():
            entry[field] = round(sum(values) / len(values), 4)
            entry[f"{field}_n"] = float(len(values))
        if entry:
            out[key] = entry
    return out
