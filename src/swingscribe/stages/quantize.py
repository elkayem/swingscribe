"""Stage 5 — Quantize: swing-warp, then grid-snap, residual preserved. Plan §5.

A swung eighth pair is played long-short but *notated* as two even eighths
with "Swing" written above the staff. So quantization has two jobs, and doing
them in one step is what makes naive transcriptions look like nonsense:

1. **Warp** the beat's internal timing so the swung offbeat moves from φ* back
   to 0.5. This removes the feel, leaving the rhythm the player was thinking.
2. **Snap** the result to a notatable grid, keeping the leftover as
   `timing_residual` — the microtiming, which is the expressive layer and the
   thing every quantizer throws away.

Three things this stage is careful about, all of them learned by measurement
rather than assumed:

- **It refuses to warp on a weak reading.** Measured against 359 hand-annotated
  WJazzD solos, onsets with no feel at all still produce BUR ≈ 1.56, because
  the offbeat region is asymmetric about 0.5 (`docs/wjazzd.md`). A reported BUR
  near 1.5 means "no swing detected", NOT "slightly swung", and warping on it
  would inject error rather than remove it.
- **It pools BUR across windows.** Per-window estimates are noisy — at 260bpm a
  16-beat window pins BUR to about ±15% — while the whole-solo aggregate is
  accurate enough to land inside the human interquartile range. So each beat's
  φ* is its own span's reading shrunk toward the track's confidence-weighted
  mean, by that span's own confidence. A confident window trusts itself; an
  unconfident one falls back on the feel of the tune.
- **It chooses a binary or ternary grid per beat.** Post-warp, a genuine
  triplet figure and a swung eighth pair are dangerously similar (plan §5), so
  the grid is not assumed: whichever subdivision the beat's own notes actually
  fit gets used, and the residual records how well.
- **It reads each beat as straight OR swung, whichever its notes fit.** The
  warp is a hypothesis about a beat, and a beat played straight inside a
  swinging solo — an offbeat at 0.5 — must not be charged for it: warped to
  0.38 it became a sixteenth or a thirty-second, 3.1% of 190,000 WJazzD
  notes (docs/wjazz-quantize.md, 2026-09-20). Every binary grid is scored
  under the raw phases and the warped ones, the coarsest grid within slack
  of the best pair wins, and the note is snapped and replayed under that
  reading.

Pure arithmetic, no heavy imports — the whole stage runs in CI.
"""

import bisect
import functools
import json
import math
import statistics
from fractions import Fraction
from pathlib import Path

from swingscribe.config import Config, QuantizeConfig
from swingscribe.model import Document, MeterSection, NoteEvent, QuantizedNote, SwingSpan

# Bump when this stage's behavior changes without a config change (see
# pipeline._cache_name).
CACHE_VERSION = 6  # 5: the line's lag is taken out before the snap (the six-per-beat grid is off)
# 6: a section's bars are counted from its own first line (R35)

STRAIGHT_PHASE = 0.5

# The quarter-note triplet: three equal notes over a half note, at 0, 2/3
# and 4/3 of a beat pair. Read one beat at a time it is invisible -- the
# first beat holds two onsets, which cannot vote a tuplet, and the second
# holds one at a third -- so it comes out as a dotted eighth and a sixteenth
# or, under the swing warp, as an eighth pair (D28: 48 of the 68 ternary
# notes the hand scores write in beats of fewer than three onsets are these,
# 19 of them in Flanagan's Giant Steps).
#
# `quarter_triplet_pairs` reads the pair as one unit, and what it looks for
# is EQUAL SPACING, not the lattice. Measured against the twelve hand scores
# (2026-09-11, the truth being our notes aligned to the human's and the
# human's two-thirds-long notes among them): the figures a human wrote as
# quarter-note triplets sit in our raw onsets at intervals of 0.58-0.78 of a
# beat, starting up to a quarter of a beat late, and none on 0, 2/3, 4/3 --
# a lattice rule adopted 108 pairs of which 3 were real. The interval rule
# below adopts 9 of which 3 are real: the perfect 0.667/0.667 figures the
# human wrote as eighths look exactly like the ones written as triplets, so
# on onset timing alone the figure is not identifiable. That is why
# `QuantizeConfig.quarter_triplets` ships OFF. The writing side (notate,
# export) is complete for when a reading exists.
QUARTER_TRIPLET_INTERVAL = (0.58, 0.80)  # beats, each of the figure's two gaps
QUARTER_TRIPLET_RATIO_MAX = 1.25  # longer gap over shorter: equal spacing
QUARTER_TRIPLET_FIRST_MAX = 0.25  # how late the figure may start, in beats
QUARTER_TRIPLET_NEXT = 1.8  # from here on an onset is the next downbeat, early

# How sharply the no-swing floor relaxes as confidence rises. Cubic, not
# linear: real solos read at confidence 0.25-0.32, which is precisely where
# the floor must stay at full strength, and a linear relaxation had already
# dropped it to 1.43 there — low enough to warp a Latin solo reading 1.45.
# Cubed, confidence 0.28 leaves the ceiling at 1.59 while a clean 0.98 reading
# drops it to 1.04.
FLOOR_RELAXATION_EXPONENT = 3


def warp_phase(phase: float, star: float) -> float:
    """Map a beat-internal phase so the swung offbeat φ* lands on 0.5.

    Piecewise linear with one knee at φ*, so it is monotonic, continuous, and
    fixes both beat boundaries — a note on the downbeat stays on the downbeat.
    Identity when φ* is already 0.5.
    """
    if not 0.0 < star < 1.0 or star == STRAIGHT_PHASE:
        return phase
    if phase <= star:
        return phase / star * STRAIGHT_PHASE
    return STRAIGHT_PHASE + (phase - star) / (1.0 - star) * STRAIGHT_PHASE


def unwarp_phase(phase: float, star: float) -> float:
    """Inverse of `warp_phase` — puts the swing back.

    Needed by the round-trip acceptance test, and by anything that wants to
    render notated rhythm as it would actually be played.
    """
    if not 0.0 < star < 1.0 or star == STRAIGHT_PHASE:
        return phase
    if phase <= STRAIGHT_PHASE:
        return phase / STRAIGHT_PHASE * star
    return star + (phase - STRAIGHT_PHASE) / STRAIGHT_PHASE * (1.0 - star)


def beat_position(onset: float, beats: list[float]) -> float | None:
    """Onset in continuous beat units: 3.25 is a quarter into beat 3.

    None outside the grid. Uses each beat's own length, so a grid that speeds
    up or slows down is handled without a tempo model.
    """
    if len(beats) < 2 or onset < beats[0] or onset >= beats[-1]:
        return None
    index = bisect.bisect_right(beats, onset) - 1
    length = beats[index + 1] - beats[index]
    if length <= 0:
        return None
    return index + (onset - beats[index]) / length


def pooled_phase(
    spans: list[SwingSpan], straight_bur_ceiling: float
) -> tuple[dict[int, float], float | None]:
    """Per-beat φ* to warp by, and the track's overall φ* for reference.

    Returns ({beat index: φ*}, track φ*). Beats with no usable reading are
    absent from the map and get no warp at all.

    Each span's own φ* is shrunk toward the track mean in proportion to its
    confidence, because per-window BUR is noisy while the aggregate is sound
    (`docs/m4-swing.md`, `docs/wjazzd.md`).

    The no-swing floor is applied ONCE, to the pooled track reading, and never
    per span. Testing each span against it separately puts a hard threshold on
    a noisy estimate: on material swinging right at the ceiling, adjacent
    windows fall on opposite sides and their beats get opposite treatment,
    which measurably broke the round trip (25.6ms at BUR 1.6 against 0.0ms at
    1.0 and 2.0). "Does this performance swing at all?" is a question about
    the whole performance, and pooling is what makes it answerable.

    The floor also SCALES WITH CONFIDENCE, because it is a statement about
    evidence rather than about music. BUR 1.56 is what feel-free onsets
    produce *when the reading is noisy* — which real solos are, at confidence
    0.25-0.32. A clean reading at confidence 1.0 measures BUR 1.3 exactly
    (M4 recovers it with 0.00% error), and refusing to warp it would notate a
    genuine shuffle as straight eighths, 49ms from the performance at 80bpm.
    So the ceiling relaxes toward 1.0 as confidence rises, and only bites when
    the evidence is as weak as the evidence the floor was measured on.
    """
    swung = [s for s in spans if s.is_swung]
    if not swung:
        return {}, None
    weight = sum(s.confidence for s in swung)
    if weight <= 0:
        return {}, None
    track = sum(_phase_of(s) * s.confidence for s in swung) / weight
    trust = sum(s.confidence for s in swung) / len(swung)
    trust = max(0.0, min(1.0, trust)) ** FLOOR_RELAXATION_EXPONENT
    ceiling = 1.0 + (straight_bur_ceiling - 1.0) * (1.0 - trust)
    if track <= ceiling / (1.0 + ceiling):
        return {}, track  # no better than noise at this confidence: notate straight

    by_beat: dict[int, float] = {}
    for span in swung:
        trust = max(0.0, min(1.0, span.confidence))
        phase = trust * _phase_of(span) + (1.0 - trust) * track
        for beat in range(span.start_beat, span.end_beat):
            by_beat[beat] = phase
    return by_beat, track


def _phase_of(span: SwingSpan) -> float:
    return span.bur / (1.0 + span.bur)


# The figure prior: how often a human transcriber writes each set of onset
# positions inside a beat, counted over 49,000 beats of 245 OMR-read
# transcription pages (docs/figure-prior.md, scripts/figure_prior.py build).
# An aggregate table, a few hundred rows, shipped inside the package.
FIGURE_PRIOR_PATH = Path(__file__).resolve().parent.parent / "figure-prior.json"


@functools.lru_cache(maxsize=1)
def figure_prior(path: Path = FIGURE_PRIOR_PATH) -> tuple[dict[str, float], float]:
    """({figure: surprisal in nats}, the surprisal of a figure the table never
    saw). Surprisal is -ln of the figure's share of beats WITH an onset; the
    unseen figure gets half a count. Read once per process."""
    data = json.loads(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = data["counts"]
    unseen = float(data.get("unseen", 0.5))
    total = sum(counts.values()) + unseen
    table = {key: -math.log(n / total) for key, n in counts.items()}
    return table, -math.log(unseen / total)


def figure_of(offsets: list[float], divisions: int) -> str:
    """The figure a reading makes: the beat's onsets snapped to `divisions`,
    as sorted exact fractions, in the table's spelling ("0 1/2"). An onset
    the grid sends to 1.0 is the next beat's downbeat and is not part of this
    beat's figure; a beat left with nothing is "-"."""
    positions = sorted({Fraction(round(offset * divisions), divisions) for offset in offsets})
    inside = [p for p in positions if p < 1]
    return " ".join(str(p) for p in inside) if inside else "-"


def figure_surprisal(key: str, prior: tuple[dict[str, float], float]) -> float:
    table, unseen = prior
    return table.get(key, unseen)


def snap(position: float, divisions: int) -> tuple[float, float]:
    """Snap a position in beats to a subdivision grid.

    Returns (snapped, residual_in_beats). The residual is signed and kept —
    it is the microtiming, and plan §5 wants it preserved rather than
    discarded, because it is what distinguishes a player from a MIDI file.
    """
    if divisions < 1:
        return position, 0.0
    snapped = round(position * divisions) / divisions
    return snapped, position - snapped


def choose_reading(
    offsets: list[float],
    candidates: tuple[int, ...],
    min_onsets_for_tuplet: int = 3,
    slack: float = 0.05,
    raw_offsets: list[float] | None = None,
    star: float | None = None,
    offbeat_pair_fit: float = 0.0,
    inside: bool = False,
    prior_weight: float = 0.0,
    prior: tuple[dict[str, float], float] | None = None,
    next_occupied: bool = False,
    previous_pushed: bool = False,
    pushed_last: bool = False,
    rerank=None,
    rerank_grids: tuple[int, ...] | None = None,
) -> tuple[int, str]:
    """Pick the subdivision the notes in one beat actually fit, and under
    which timing reading: ("warped", the beat is swung) or ("raw", the beat
    is straight or ternary).

    `rerank` (A6, QuantizeConfig.reranker, docs/reranker.md) is the one
    opt-in hook: called with every ADMITTED reading -- each (grid,
    reading) pair the gates allow that keeps the onsets apart, the
    neighbour-line guards applied whether or not the prior is on -- as
    dicts, the rule's own pick marked `baseline`, it returns the index of
    the one to write, or None to keep the rule's. It is not asked when
    nothing is admitted or the rule's pick is the only admitted reading.
    So it can choose only what the guards already allow, and never loses a
    note the rule keeps. Where the rule's own pick is NOT admitted (it
    merges two onsets, or -- with the figure prior off -- pushes one onto a
    neighbour's note) and the hook defers, the admitted reading of least
    snap error is written: the note is kept. With the shipped gates and the
    prior on that never happens, so a deferring hook writes the rule's page
    (measured: identical on all 34 pages, 8 triples and 452 WJazzD solos).
    None leaves every line below as it was. `rerank_grids` widens what it is
    offered to every reading of those grids, the convention gates lifted
    and the note-keeping guards kept (a model trained "open"), and there the
    keep-the-note fallback does fire (+19 notes on the 22 Omnibook pages).

    `pushed_last` is R28's one exception (QuantizeConfig.tuplet_pushed_last,
    docs/writing-round2.md): with `inside`, a ternary grid may still be read
    when exactly one onset leaves the beat, provided it is the LAST, sits
    from LAG_PUSH_MIN on (the next downbeat played early, the threshold the
    lag rule already uses), the figure before it starts on the downbeat,
    the others alone pass the tuplet gate, and the next beat has no note of
    its own at the line (`next_occupied`), so the pushed note lands nowhere
    taken.

    `prior_weight`, in beats per nat, adds to each (grid, reading)
    candidate's snap error the surprisal of the figure it writes -- minus
    the log of that figure's share on a human page (`figure_prior`,
    docs/figure-prior.md) -- BEFORE the coarsest-within-slack comparison.
    Everything else stands as it is: `_keeps_apart` is still a hard
    constraint, the tuplet and sixteenth gates still trim the candidates,
    and the prior only ever decides among what they leave. At 0.0 it is
    not consulted.

    With the prior on, `_keeps_apart` is applied one beat wider as well: a
    reading that sends an onset to 1.0 while the next beat has its own note
    at the beat line (`next_occupied`) writes two notes on one grid position
    across the bar line and notate keeps one. Measured without it
    (2026-09-25, docs/figure-prior.md): the prior found the loophole at
    once -- a pushed note leaves the beat's figure, the figure left behind
    is the common one, and the WJazzD instrument's dropped notes went 7,155
    to 22,934. Such a reading is marked as merging, exactly as one that
    merges inside the beat is. The other side is guarded too: where the beat
    before DID push a note onto this beat's line (every grid sent it there,
    the fallback), a reading of this beat that puts its own note on that
    line loses one of the two (`previous_pushed`; Mobley's All The Things
    bar 61), and is marked the same way. Only such a reading: a first
    version flagged every reading of the beat after a push, which put the
    whole beat in the fallback, where the prior then took the coarsest
    grid, which pushed in turn -- a cascade down every ballad (26,973
    dropped). Losses are counted before error in the fallback now, so a
    reading that keeps its note off the line always wins there.

    Post-warp, a swung eighth pair (0, 0.5) and a triplet figure (0, 1/3, 2/3)
    are close enough that assuming a binary grid silently rewrites the second
    as the first. So the candidates are tried and the snap error compared.

    **Least snap error is not enough on its own, and measurement said so
    twice.** Warping is imperfect — the phase estimate is shrunk toward the
    track mean and real playing scatters around it — so a warped offbeat
    routinely lands near 0.6 rather than 0.5. Two things follow, and both were
    happening:

    - On pure arithmetic ternary beats binary there, so an even eighth pair
      was notated as a triplet.
    - Once that was fixed it snapped to 0.75 on the sixteenth grid instead,
      and the pair was notated as a dotted eighth plus a sixteenth.

    Both are the same mistake: **reading more resolution out of the notes than
    the notes can demonstrate.** Two onsets in a beat cannot show a triplet
    and cannot show a sixteenth; they can only show an eighth pair, and the
    scatter that distinguishes 0.5 from 0.75 is smaller than the scatter a
    player produces. So:

    - a tuplet needs `min_onsets_for_tuplet` onsets before it may be chosen;
    - and among what remains, the COARSEST grid within `slack` of the best
      error wins, rather than the best. Parsimony, and the coarser reading is
      the one a musician writes.

    `raw_offsets`, when given, are the same notes UNWARPED, and they carry
    two hypotheses. The ternary candidate is scored on them alone (D12): the
    swing warp is a story about BINARY beats — it maps the swung offbeat to
    0.5 — and applying it to a genuine triplet drags the thirds off-lattice
    before this function ever votes; a performed triplet already sits at
    thirds in raw time. **Every binary candidate is scored on BOTH** (2026-09-20,
    docs/wjazz-quantize.md): the warp is a hypothesis about a beat, and a
    beat played straight inside a swinging solo must not be charged for it.
    An offbeat at 0.5 with a span reading φ* = 0.65 warps to 0.38, where the
    sixteenth or thirty-second grid fits it better than the eighth — 3.1% of
    190,000 WJazzD notes were written a sixteenth or thirty-second early
    that way. Under the raw phase it is an eighth with no error at all. The
    convention gate stays — two notes still cannot vote a tuplet, because a
    swung PAIR in raw time also lands near {0, 2/3} and the page writes that
    as eighths (CLAUDE.md).

    **The straight reading is offered only to a beat whose onsets all sit at
    or before `star`**, the span's swung offbeat. A note PAST the swing point
    is not straight: read raw, an offbeat played at 0.75 is a perfect
    sixteenth, and the first version of this rule wrote the dotted eighth
    plus sixteenth for exactly the late swung offbeats the warp exists to
    fold into an eighth — notated rhythm fell on eleven of twelve hand
    scores and 19 of 22 Omnibook sides while the WJazzD instrument, which
    then counted the annotator's own 3/4 tatum as a hit, read four points
    better. Before the swing point the two readings differ only in which
    way an early offbeat is pushed, and the raw one keeps it an eighth.
    """
    if not offsets:
        return candidates[0], "warped"
    raw = raw_offsets if raw_offsets is not None else offsets
    gate = min_onsets_for_tuplet
    # Two more things about the tuplet gate, both counted on the quantizer's
    # own instrument (docs/wjazz-quantize.md, 2026-09-20). A two-onset beat
    # whose first onset is OFF the beat and whose onsets fit thirds is the
    # second and third of a triplet after a rest -- the swung-pair
    # convention is about {0, 2/3} and says nothing about {1/3, 2/3} -- so
    # it may vote. And an onset the thirds grid sends to 1.0 is the next
    # beat's note, not the third of a triplet: laid-back sixteenths at
    # (0.3, 0.55, 0.85) are not a triplet, and four onsets never are.
    if (
        offbeat_pair_fit > 0
        and len(raw) == 2
        and min(raw) >= 0.25
        and sum(abs(snap(r, 3)[1]) for r in raw) / 2 <= offbeat_pair_fit
    ):
        gate = 2

    def ternary_ok(divisions: int) -> bool:
        # Inside is judged on the grid in question: the sixth that lands a
        # sixteenth-triplet's last note at 5/6 is inside, whatever thirds say.
        voting = sum(1 for r in raw if snap(r, divisions)[0] < 1.0 - 1e-9) if inside else len(raw)
        if voting >= gate and voting == len(raw):
            return True
        return (
            pushed_last
            and inside
            and not next_occupied
            and voting == len(raw) - 1
            and voting >= gate
            and max(raw) >= LAG_PUSH_MIN
            and snap(min(raw), divisions)[0] <= 1e-9
        )

    allowed = [d for d in candidates if d % 3 != 0 or ternary_ok(d)]
    if not allowed:
        allowed = [candidates[0]]

    straight_allowed = raw_offsets is not None and (star is None or max(raw_offsets) <= star + 1e-9)

    def readings(divisions: int) -> list[tuple[str, list[float]]]:
        if raw_offsets is None:
            return [("warped", offsets)]
        if divisions % 3 == 0:
            return [("raw", raw_offsets)]
        if not straight_allowed:
            return [("warped", offsets)]
        return [("raw", raw_offsets), ("warped", offsets)]

    # Per grid: the reading that fits it best among those that keep the
    # onsets apart on it; a grid no reading can keep apart is scored on its
    # best error and marked as merging.
    errors: dict[int, float] = {}
    chosen: dict[int, str] = {}
    lost: dict[int, int] = {}
    separating: list[int] = []
    table = prior if prior is not None else (figure_prior() if prior_weight > 0 else None)
    with_prior = table is not None and prior_weight > 0
    for divisions in allowed:
        scored = []
        for name, values in readings(divisions):
            error = sum(abs(snap(offset, divisions)[1]) for offset in values) / len(values)
            snapped = [snap(offset, divisions)[0] for offset in values]
            merged = len(values) - len({round(s, 9) for s in snapped})
            merges = merged > 0
            if with_prior:
                error += prior_weight * figure_surprisal(figure_of(values, divisions), table)
                if next_occupied and any(s >= 1.0 - 1e-9 for s in snapped):
                    merges, merged = True, merged + 1
                if previous_pushed and any(s <= 1e-9 for s in snapped):
                    merges, merged = True, merged + 1
            # With the prior on, a grid that merges is ranked by how many
            # notes it loses before its error: in the fallback below (no grid
            # keeps every onset apart -- a ballad's ornament under the 32nd
            # grid) the prior's term made the coarsest grid win, and it
            # merged three notes where the finest merged one. Off, the
            # ordering is the one every pinned number stands on.
            scored.append((merges, merged, error, name) if with_prior else (merges, error, name))
        merges, *rest = min(scored)
        error, name = rest[-2], rest[-1]
        errors[divisions], chosen[divisions] = error, name
        lost[divisions] = rest[0] if with_prior else 0
        if not merges:
            separating.append(divisions)
    best_error = min(errors.values())
    # A grid that cannot keep two onsets apart is too coarse for this beat,
    # whatever its snap error says. Two notes on one grid position are one
    # note in a single-line score — the other is simply lost — so this is a
    # hard constraint and not a preference. Without it, buying notated rhythm
    # by coarsening the grid quietly costs notes: 4.8% of All The Things
    # disappeared before this rule existed.
    # No grid keeps every onset apart (a ballad's ornament under the 32nd
    # grid): the choice is among the grids that lose the FEWEST notes. With
    # the prior off every grid counts as losing none here and the set is
    # the whole candidate list, as it always was; with it on, the coarsest
    # grid's cheap figure was winning this loop and merging four notes
    # where the finest merged one (2026-09-25, docs/figure-prior.md).
    fewest = min(lost.values())
    separating = separating or [d for d in allowed if lost[d] == fewest]
    # Coarsest first: a smaller number of divisions is a coarser grid.
    pick = None
    for divisions in sorted(separating):
        if errors[divisions] <= best_error + slack + 1e-12:
            pick = divisions, chosen[divisions]
            break
    if pick is None:
        divisions = min(separating, key=lambda d: (lost[d], errors[d]))
        pick = divisions, chosen[divisions]
    if rerank is None:
        return pick

    # A6's hook: the admitted readings, the rule's pick marked. With
    # `rerank_grids` the CONVENTION gates are lifted for it (the tuplet and
    # sixteenth gates, R28's inside rule, the straight reading's swing-point
    # gate) and every reading of those grids is offered; the note-keeping
    # guards below hold either way.
    def offered(divisions: int) -> list[tuple[str, list[float]]]:
        if rerank_grids is None or raw_offsets is None:
            return readings(divisions)
        if divisions % 3 == 0:
            return [("raw", raw_offsets)]
        return [("raw", raw_offsets), ("warped", offsets)]

    admitted = []
    for divisions in allowed if rerank_grids is None else rerank_grids:
        for name, values in offered(divisions):
            snapped = [snap(offset, divisions)[0] for offset in values]
            if len({round(s, 9) for s in snapped}) < len(values):
                continue
            if next_occupied and any(s >= 1.0 - 1e-9 for s in snapped):
                continue
            if previous_pushed and any(s <= 1e-9 for s in snapped):
                continue
            # ...and whether the convention gates allow it too
            gated = divisions in allowed and any(n == name for n, _ in readings(divisions))
            admitted.append(
                {
                    "divisions": divisions,
                    "reading": name,
                    "values": values,
                    "snapped": snapped,
                    "error": sum(abs(snap(o, divisions)[1]) for o in values) / len(values),
                    "figure": figure_of(values, divisions),
                    "baseline": (divisions, name) == pick,
                    "gated": gated,
                }
            )
    baseline_admitted = any(c["baseline"] for c in admitted)
    if not admitted or (baseline_admitted and len(admitted) < 2):
        return pick
    # With the prior on, the rule's own pick is always admitted when anything
    # is (its merge test is this one). With it off the rule does not apply
    # the neighbour-line guards, and an admitted reading beats one that loses
    # a note across the beat line.
    choice = rerank(admitted)
    if choice is None:
        if baseline_admitted:
            return pick
        choice = min(range(len(admitted)), key=lambda i: admitted[i]["error"])
    return admitted[choice]["divisions"], admitted[choice]["reading"]


def choose_grid(
    offsets: list[float],
    candidates: tuple[int, ...],
    min_onsets_for_tuplet: int = 3,
    slack: float = 0.05,
    raw_offsets: list[float] | None = None,
) -> int:
    """The grid `choose_reading` picks, without the reading."""
    return choose_reading(offsets, candidates, min_onsets_for_tuplet, slack, raw_offsets)[0]


def _keeps_apart(offsets: list[float], divisions: int) -> bool:
    """Do all these onsets still land on different grid positions?"""
    snapped = {round(snap(offset, divisions)[0], 9) for offset in offsets}
    return len(snapped) == len(offsets)


def has_half_units(pulses_per_bar: int) -> bool:
    """Does a bar of this many pulses hold two-beat units a tuplet can be
    written over? Notate halves a binary bar down to the beat (2, 4, 8) and
    cuts a bar of three binary units in three (6); 3/4 and 5/4 have no
    half-note unit, so a quarter-note triplet cannot be written in them."""
    return pulses_per_bar in (2, 4, 6, 8)


def _pulses_at(index: int, beats: list[float], sections: list[MeterSection]) -> int:
    time = beats[index]
    for section in sections:
        if section.start <= time <= section.end:
            return max(1, section.pulses_per_bar)
    return 4


def quarter_triplet_pairs(
    per_beat_raw: dict[int, list[float]],
    beats: list[float],
    sections: list[MeterSection],
) -> list[int]:
    """Beat indices that begin a pair read as a quarter-note triplet.

    A pair is the first two or last two beats of a bar that has half-note
    units (has_half_units). In RAW time -- the swing warp is a hypothesis
    about binary beats -- the pair must hold exactly three onsets before
    QUARTER_TRIPLET_NEXT (anything later is the next downbeat played early),
    the first within QUARTER_TRIPLET_FIRST_MAX of the unit's start, the two
    gaps between them each inside QUARTER_TRIPLET_INTERVAL and within
    QUARTER_TRIPLET_RATIO_MAX of each other. Equal spacing is what separates
    the figure from a swung "one, and, and" (gaps of 2/3 then 1) and from
    straight eighths (1/2 then 1/2); the numbers are where the hand scores'
    figures sit in our onsets (see the constants). Precision on those
    scores is 3 of 9, which is why the caller ships this off.
    """
    pairs = []
    low, high = QUARTER_TRIPLET_INTERVAL
    for index in sorted(per_beat_raw):
        if index + 1 >= len(beats):
            continue
        pulses = _pulses_at(index, beats, sections)
        _bar, beat_in_bar = bar_and_beat(float(index), beats, sections)
        first = int(round(beat_in_bar))
        if first % 2 or first + 2 > pulses or not has_half_units(pulses):
            continue
        positions = sorted(
            list(per_beat_raw[index]) + [1.0 + r for r in per_beat_raw.get(index + 1, [])]
        )
        figure = [p for p in positions if p < QUARTER_TRIPLET_NEXT]
        if len(figure) != 3 or figure[0] > QUARTER_TRIPLET_FIRST_MAX:
            continue
        gaps = [b - a for a, b in zip(figure, figure[1:], strict=False)]
        if (
            all(low <= gap <= high for gap in gaps)
            and max(gaps) / min(gaps) <= QUARTER_TRIPLET_RATIO_MAX
        ):
            pairs.append(index)
    return pairs


def _anchor_index(section: MeterSection, beats: list[float]) -> int:
    if not beats:
        return 0
    return min(range(len(beats)), key=lambda i: abs(beats[i] - section.anchor))


def bar_and_beat(
    position: float, beats: list[float], sections: list[MeterSection]
) -> tuple[int, float]:
    """Continuous beat position → (bar number, beat within bar, 0-based).

    Bars are counted from the section's anchor, never from the beat tracker's
    detected downbeats — that layer is noise (open-issue #5). Outside every
    section, bar 0 is reported and the position passes through, so a pickup or
    a rubato intro is not silently forced into a bar.
    """
    index = int(position)
    if not sections or index >= len(beats):
        return 0, position
    time = beats[index]
    for section in sections:
        if not (section.start <= time <= section.end):
            continue
        pulses = max(1, section.pulses_per_bar)
        phase = _anchor_index(section, beats) % pulses
        offset = index - phase
        # `first_bar` numbers the section's FIRST line, so count from it. An
        # absolute count from beat 0 added every bar before the section to
        # its number a second time (R35): after a hole in the tracking, the
        # pipeline's bars ran on from double the roll's.
        start = min(range(len(beats)), key=lambda i: abs(beats[i] - section.start))
        first = start + (phase - start) % pulses
        bar = section.first_bar + (index - first) // pulses
        return bar, (offset % pulses) + (position - index)
    return 0, position


def quantize_notes(
    onsets: list[float],
    durations: list[float],
    pitches: list[int],
    beats: list[float],
    spans: list[SwingSpan],
    sections: list[MeterSection],
    resolution: int = 16,
    straight_bur_ceiling: float = 1.6,
    allow_triplets: bool = True,
    min_onsets_for_tuplet: int = 3,
    grid_slack_s: float = 0.02,
    chords: list[list[int]] | None = None,
    graces: list[list[int]] | None = None,
    quarter_triplets: bool = False,
    min_onsets_for_sixteenth: int = 3,
    offbeat_pair_tuplet_fit: float = 0.0,
    tuplet_needs_onsets_inside: bool = False,
    lag_window_beats: int = 0,
    lag_cap: float = 0.2,
    lag_floor: float = 0.0,
    sixteenth_triplets: bool = False,
    sixteenth_triplet_fit: float = 0.03,
    slow_beat_s: float = 0.0,
    slow_beat_grids: tuple[int, ...] = (6, 8),
    figure_prior_weight: float = 0.0,
    timing: str = "swing",
    polyphonic: bool = False,
    late_downbeat_max_onsets: int = 0,
    isolated_lag_max_onsets: int = 0,
    tuplet_pushed_last: bool = False,
    reranker="",
    literal_lag: bool = False,
    literal_thirds: bool = False,
    literal_lead_ins: bool = False,
) -> tuple[list[QuantizedNote], list[float]]:
    """Warp, snap, and place notes in bars. See the module docstring.

    Returns (notes, snapped positions in absolute beats). The positions are
    what `replay_onsets` needs and what the Document does not keep: bar plus
    beat-within-bar is the notation, and reconstructing absolute time from it
    would fail for anything outside a meter section — a pickup, a rubato
    intro — which is exactly where a round-trip check matters most.

    A literal `timing` bypasses all of it for `literal_notes`, which takes
    the line's lag out first when `literal_lag` asks (`literal_lags`, with
    the lag window above), offers thirds when `literal_thirds` does, writes
    a beat shorter than `LITERAL_EIGHTHS_BEAT_S` on eighths for
    "literal-8", and carries `graces` (the run folds lead-ins on a literal
    page when `literal_lead_ins` asks; the flag itself is read there).
    `polyphonic`
    folds notes the grid puts on one position into a chord (`merge_chords`)
    rather than losing one of them.

    `graces` rides beside `chords` (QuantizedNote.grace): each note's grace
    pitches, set by `absorb_lead_ins`; swing timing only.

    `reranker` (A6, docs/reranker.md) is QuantizeConfig.reranker -- "" off,
    or the path of a weights JSON -- or any object with a
    `choose(context, candidates)` method (the training recorder); see
    `choose_reading`'s `rerank`.
    """
    if len(beats) < 2:
        return [], []
    if polyphonic:
        onsets, durations, pitches, chords = fold_near_onsets(
            onsets, durations, pitches, chords, beats
        )
    if timing != "swing":
        return literal_notes(
            onsets,
            durations,
            pitches,
            beats,
            sections,
            LITERAL_DIVISIONS[timing],
            chords=chords,
            polyphonic=polyphonic,
            lags=(
                literal_lags(onsets, beats, lag_window_beats, lag_cap, lag_floor)
                if literal_lag
                else None
            ),
            thirds=literal_thirds,
            min_onsets_for_thirds=min_onsets_for_tuplet,
            graces=graces,
            eighths_beat_s=LITERAL_EIGHTHS_BEAT_S if timing == "literal-8" else 0.0,
        )
    by_beat, _track = pooled_phase(spans, straight_bur_ceiling)
    finest = max(1, resolution // 4)  # grid steps per beat at full resolution
    # Coarse to fine. An eighth-note grid is offered first so a beat holding
    # only an eighth pair is not forced onto a sixteenth grid it cannot
    # justify; `slack` decides how much better a finer grid has to be.
    coarse = [d for d in (2, finest) if d <= finest]
    candidates = tuple(dict.fromkeys(coarse + ([3] if allow_triplets else [])))

    # Place first, so the line's lag behind the beat can be read off the
    # whole window before anything is warped (line_lag). Then warp, and
    # group by beat so the grid choice sees the whole beat. The RAW
    # fractional offset rides along: the ternary hypothesis is scored and
    # snapped in raw time (see choose_grid — the warp is a binary story).
    extras = chords if chords is not None else [[] for _ in onsets]
    ornaments = graces if graces is not None else [[] for _ in onsets]
    placed: list[tuple[int, float, float, int, list[int], list[int]]] = []
    raw_by_beat: dict[int, list[float]] = {}
    for onset, duration, pitch, chord, grace in zip(
        onsets, durations, pitches, extras, ornaments, strict=True
    ):
        position = beat_position(onset, beats)
        if position is None:
            continue
        index = int(position)
        star = by_beat.get(index, STRAIGHT_PHASE)
        end = beat_position(onset + duration, beats)
        warped_start = index + warp_phase(position - index, star)
        if end is None:
            warped_end = warped_start + duration / _beat_length(beats, index)
        else:
            end_index = int(end)
            warped_end = end_index + warp_phase(end - end_index, by_beat.get(end_index, 0.5))
        placed.append(
            (index, position - index, max(0.0, warped_end - warped_start), pitch, chord, grace)
        )
        raw_by_beat.setdefault(index, []).append(position - index)
    lags = line_lag(raw_by_beat, lag_window_beats, lag_cap, lag_floor)
    if isolated_lag_max_onsets > 0:
        lags = {**isolated_lags(raw_by_beat, lags, isolated_lag_max_onsets, lag_cap), **lags}

    # Per note: beat index, lag-corrected warped position, duration, pitch,
    # lag-corrected raw offset, chord, and what the replay needs to put the
    # lag and the swing back: the ORIGINAL warped position, the beat's φ*
    # as measured, the φ* the corrected beat was warped under, and the lag.
    warped: list[
        tuple[int, float, float, int, float, list[int], float, float, float, float, list[int]]
    ] = []
    for index, raw, duration, pitch, chord, grace in placed:
        star = by_beat.get(index, STRAIGHT_PHASE)
        lag = lags.get(index, 0.0)
        # The measured offbeat carries the lag too, so the corrected beat is
        # warped under φ* less the lag -- never below straight: a line that
        # lags past its own swing is not evidence of an early offbeat.
        star_l = max(STRAIGHT_PHASE, star - lag)
        warped.append(
            (
                index,
                index + warp_phase(unlag_phase(raw, lag), star_l),
                duration,
                pitch,
                unlag_phase(raw, lag),
                list(chord),
                index + warp_phase(raw, star),
                star,
                star_l,
                lag,
                list(grace),
            )
        )

    per_beat: dict[int, list[float]] = {}
    per_beat_raw: dict[int, list[float]] = {}
    for index, position, _duration, _pitch, raw, *_rest in warped:
        per_beat.setdefault(index, []).append(position - index)
        per_beat_raw.setdefault(index, []).append(raw)
    # The slack is a time budget (config.py: it absorbs a player's motor
    # scatter, which is milliseconds, not beat fractions), so each beat
    # converts it at its own length. A long ballad beat gets a small slack
    # in beats and fine grids stay reachable; a burner's beat gets a large
    # one and the coarse reading wins — which is the direction the 456-solo
    # tempo staircase says humans notate (D11).
    # A ballad is a TEMPO, not a long beat: judged on the median beat under
    # the notes, so a slipped or half-rate stretch inside a fast solo, or a
    # 100 bpm track with a third of its beats past the line (Soul Station,
    # 0.60 s), is not read as one (docs/wjazz-quantize.md).
    ballad = slow_beat_s > 0 and bool(per_beat)
    if ballad:
        ballad = statistics.median(_beat_length(beats, i) for i in per_beat) >= slow_beat_s
    grids: dict[int, int] = {}
    readings: dict[int, str] = {}
    prior = figure_prior() if figure_prior_weight > 0 else None
    model = None
    if reranker:
        if isinstance(reranker, str):
            from swingscribe.reranker import load_model

            model = load_model(reranker)
        else:
            model = reranker
    pushed: set[int] = set()  # beats whose chosen reading sent a note to the next beat line
    # Ascending, so the beat before is decided when the prior asks whether it
    # pushed; each beat's choice is its own, so the order changes nothing
    # with the prior off.
    for index in sorted(per_beat):
        offsets = per_beat[index]
        # A beat the finest binary grid cannot keep apart holds a genuine
        # 32nd run — Bird on a ballad — and merging is silent note LOSS on
        # the page: Don't Blame Me was writing 327 of 513 heard notes. The
        # 32nd grid is admitted on exactly that evidence and no other, so a
        # behind-the-beat sixteenth line (four onsets keep apart on the
        # sixteenth grid) can never be promoted to 32nds — the listener's
        # rule, both halves (D16/D11).
        # The sixteenth triplet -- six to the beat -- is admitted on the same
        # evidence, and tried before the 32nd grid because it is coarser:
        # three notes in half a beat sat at 0, 3/8, 5/8 before it, tied
        # 32nds on the page where the Omnibook writes 4.9% of its notes.
        cands = candidates
        if ballad:
            # A ballad beat is long enough to hold a run of sixths or 32nds
            # that the annotator files at those divisions; the tuplet gate
            # and the slack (in beats, small at this tempo) still decide.
            cands = tuple(dict.fromkeys(candidates + tuple(slow_beat_grids)))
        if not _keeps_apart(offsets, finest):
            raw = per_beat_raw[index]
            sixths = finest * 3 // 2
            finer: tuple[int, ...] = (finest * 2,)
            if (
                sixteenth_triplets
                and 3 <= len(raw) <= 4
                and sum(abs(snap(r, sixths)[1]) for r in raw) / len(raw) <= sixteenth_triplet_fit
            ):
                finer = (sixths, finest * 2)
            cands = tuple(dict.fromkeys(cands + finer))
        # A sparse beat is offered the eighth grid (and the ternary one) only:
        # one or two onsets cannot demonstrate a sixteenth, and read on one
        # they become the dotted eighth of a late swung offbeat or the "e"
        # of a laid-back downbeat (docs/wjazz-quantize.md). Never at the cost
        # of a note: the eighth grid must keep the onsets apart, and its
        # reading must not land an onset on the neighbouring beat's own note.
        offered_grids = cands  # before the sparse-beat trim: an "open" reranker's grids
        if len(offsets) < min_onsets_for_sixteenth and _keeps_apart(offsets, 2):
            neighbours = (
                per_beat.get(index - 1, []) + per_beat_raw.get(index - 1, []),
                per_beat.get(index + 1, []) + per_beat_raw.get(index + 1, []),
            )
            if not _collides_on_eighths(offsets, *neighbours):
                cands = tuple(d for d in cands if d <= 2 or d % 3 == 0) or cands
        beat_star = max(STRAIGHT_PHASE, by_beat.get(index, STRAIGHT_PHASE) - lags.get(index, 0.0))
        rerank = None
        if model is not None:
            context = {
                "index": index,
                "time": beats[index],
                "offsets": offsets,
                "raw": per_beat_raw[index],
                "star": beat_star,
                "track_phase": _track,
                "lag": lags.get(index, 0.0),
                "beat_s": _beat_length(beats, index),
                "neighbours": {k: per_beat_raw.get(index + k, []) for k in (-2, -1, 1, 2)},
            }
            rerank = functools.partial(model.choose, context)
        grids[index], readings[index] = choose_reading(
            offsets,
            cands,
            min_onsets_for_tuplet,
            grid_slack_s / _beat_length(beats, index),
            raw_offsets=per_beat_raw[index],
            star=beat_star,
            offbeat_pair_fit=offbeat_pair_tuplet_fit,
            inside=tuplet_needs_onsets_inside,
            prior_weight=figure_prior_weight,
            prior=prior,
            next_occupied=any(
                o < 0.25 for o in per_beat.get(index + 1, []) + per_beat_raw.get(index + 1, [])
            ),
            previous_pushed=(index - 1) in pushed,
            pushed_last=tuplet_pushed_last,
            rerank=rerank,
            rerank_grids=offered_grids if getattr(model, "open", False) else None,
        )
        if prior is not None or model is not None:
            grid = grids[index]
            values = per_beat_raw[index] if grid % 3 == 0 or readings[index] == "raw" else offsets
            if any(snap(o, grid)[0] >= 1.0 - 1e-9 for o in values):
                pushed.add(index)
    if allow_triplets and quarter_triplets:
        # A beat pair that reads as a quarter-note triplet is two ternary
        # beats: the figure's raw thirds snap per beat to 0 and 2/3 on the
        # first and 1/3 on the second, which notate reads back as the half
        # unit's thirds (notate.quarter_triplet_halves).
        for index in quarter_triplet_pairs(per_beat_raw, beats, sections):
            grids[index] = grids[index + 1] = 3

    def written_offsets(index: int) -> list[float]:
        """A beat's notated offsets, snapped exactly as the loop below snaps
        them: raw for a ternary or straight beat, warped otherwise."""
        grid = grids.get(index, finest)
        if grid % 3 == 0 or readings.get(index) == "raw":
            return [snap(r, grid)[0] for r in per_beat_raw.get(index, [])]
        return [snap(o, grid)[0] for o in per_beat.get(index, [])]

    moved = (
        late_downbeats({i: written_offsets(i) for i in per_beat}, late_downbeat_max_onsets)
        if late_downbeat_max_onsets > 0
        else set()
    )

    out, positions = [], []
    for index, position, duration, pitch, raw, chord, original, star, star_l, lag, grace in warped:
        grid = grids.get(index, finest)
        # The NOTATION is the lag-corrected position snapped: in raw time
        # for a ternary beat or a binary beat read STRAIGHT (a performed
        # triplet sits at thirds; a straight eighth at 0.5; no warp
        # applies), in warped time otherwise. The replay position and the
        # residual stay in the ORIGINAL warped space -- the notated phase
        # put back through the corrected beat's warp, plus the lag, through
        # the beat's measured warp -- so replay_onsets' one unwarp gives the
        # notation its feel back (swing AND lag) with no changes there, and
        # restore_residual stays exact by construction: unwarp(replay +
        # (original - replay)) is the raw position.
        straight = grid % 3 == 0 or readings.get(index) == "raw"
        notated_offset, _ = snap(raw if straight else position - index, grid)
        if index in moved and abs(notated_offset - 0.25) < 1e-9:
            notated_offset = 0.0  # the beat's late downbeat (late_downbeats)
        if straight:
            played = relag_phase(notated_offset, lag)
        else:
            played = relag_phase(unwarp_phase(notated_offset, star_l), lag)
        replay_position = index + warp_phase(played, star)
        snapped = index + notated_offset
        residual = original - replay_position
        positions.append(replay_position)
        length, _ = snap(duration, grid)
        bar, beat = bar_and_beat(snapped, beats, sections)
        out.append(
            QuantizedNote(
                bar=bar,
                beat=beat,
                duration_beats=max(1.0 / grid, length),
                pitch=pitch,
                # In beats, not seconds: a residual only means anything
                # relative to the pulse it deviates from.
                timing_residual=residual,
                chord=chord,
                grace=grace,
            )
        )
    if polyphonic:
        return merge_chords(out, positions)
    return out, positions


# Grid points per beat for each literal timing (QuantizeConfig.timing).
# "literal-8" is a 16th grid whose fast beats are written on eighths
# (`LITERAL_EIGHTHS_BEAT_S`).
LITERAL_DIVISIONS = {"literal-8": 4, "literal-16": 4, "literal-32": 8}

# A "literal-8" beat shorter than this (160 bpm) is written on EIGHTHS: the
# running value a human writes over 160 bpm is the eighth (D11). The Open
# Sesame head at 250 bpm put a 16th at 60 ms, and Basic Pitch's attacks a
# median 15 ms behind the beat with a spread to 0.19 of it, so nearest-16th
# split one chord's attacks across two grid points (Local task A); on
# eighths the page went to readability 1.000 and ties 0.30 -> 0.16 (A2).
LITERAL_EIGHTHS_BEAT_S = 0.375

# In a piano texture, onsets closer than this many BEATS are one chord: half
# a 32nd, the finest step the page can write, so no grid could honestly put
# them apart. Relative to the beat because a roll is a gesture of a few tens
# of milliseconds whatever the tempo, and a 32nd is not: on Blossom Dearie's
# 56 bpm ballad a left-hand roll 52 ms wide (just past the 50 ms texture
# fold) was kept apart on the 32nd grid and wrote a lone 32nd pickup in an
# empty bar 0. A real 32nd run is twice this far apart and is never folded.
TEXTURE_FOLD_BEATS = 1.0 / 16.0


def fold_near_onsets(
    onsets: list[float],
    durations: list[float],
    pitches: list[int],
    chords: list[list[int]] | None,
    beats: list[float],
    width: float = TEXTURE_FOLD_BEATS,
) -> tuple[list[float], list[float], list[int], list[list[int]]]:
    """A piano texture's notes with every onset cluster narrower than
    `width` beats folded into its earliest note, as a chord lasting as long as
    its longest member (`notation.with_chords`' rule for a texture). Notes
    off the grid are left alone; nothing is dropped."""
    extras = chords if chords is not None else [[] for _ in onsets]
    order = sorted(range(len(onsets)), key=lambda i: (onsets[i], pitches[i]))
    heads: list[list] = []  # [position, onset, duration, pitch, members]
    for i in order:
        position = beat_position(onsets[i], beats)
        head = heads[-1] if heads else None
        if (
            position is not None
            and head is not None
            and head[0] is not None
            and position - head[0] < width
        ):
            head[2] = max(head[2], durations[i])
            head[4].update({pitches[i], *extras[i]})
            continue
        heads.append([position, onsets[i], durations[i], pitches[i], set(extras[i])])
    return (
        [h[1] for h in heads],
        [h[2] for h in heads],
        [h[3] for h in heads],
        [sorted(h[4] - {h[3]}) for h in heads],
    )


# A literal beat is read in THIRDS (QuantizeConfig.literal_thirds) only when
# its onsets fit thirds better than the literal grid by this many beats of
# mean snap error. An eighth-note triplet played on the beat misses the 16th
# grid by 0.056 on average and thirds by nothing; three sixteenths miss
# thirds by 0.083 and the grid by nothing; a laid-back figure at (0.1, 0.4,
# 0.75) misses both, the grid by less.
LITERAL_THIRDS_MARGIN = 0.02


def literal_lags(
    onsets: list[float], beats: list[float], window: int, cap: float, floor: float
) -> dict[int, float]:
    """The line's lag behind the beat, per beat, for a literal page: the
    swing quantizer's own estimate (`line_lag`) over these onsets' raw
    offsets. A multi-horn page reads it once over BOTH voices
    (notation.notation_for_span), so the two horns' chords move together."""
    raw_by_beat: dict[int, list[float]] = {}
    for onset in onsets:
        position = beat_position(onset, beats)
        if position is None:
            continue
        index = int(position)
        raw_by_beat.setdefault(index, []).append(position - index)
    return line_lag(raw_by_beat, window, cap, floor)


def unlag_position(position: float, lags: dict[int, float]) -> float:
    """A beat position with its beat's lag taken out (`unlag_phase`)."""
    index = int(position)
    return index + unlag_phase(position - index, lags.get(index, 0.0))


def _fits_thirds(offsets: list[float], grid: int, min_onsets: int) -> bool:
    """Does this literal beat read better in thirds than on its grid?
    Enough onsets to show a triplet, every one INSIDE the beat on thirds
    (one the thirds send to 1.0 is the next beat's note, early), kept
    apart, and a mean snap error `LITERAL_THIRDS_MARGIN` under the grid's."""
    if len(offsets) < max(1, min_onsets) or not _keeps_apart(offsets, 3):
        return False
    if any(snap(o, 3)[0] >= 1.0 - 1e-9 for o in offsets):
        return False
    on_thirds = statistics.fmean(abs(snap(o, 3)[1]) for o in offsets)
    on_grid = statistics.fmean(abs(snap(o, grid)[1]) for o in offsets)
    return on_thirds + LITERAL_THIRDS_MARGIN < on_grid


def literal_notes(
    onsets: list[float],
    durations: list[float],
    pitches: list[int],
    beats: list[float],
    sections: list[MeterSection],
    divisions: int,
    chords: list[list[int]] | None = None,
    polyphonic: bool = False,
    lags: dict[int, float] | None = None,
    thirds: bool = False,
    min_onsets_for_thirds: int = 3,
    graces: list[list[int]] | None = None,
    eighths_beat_s: float = 0.0,
) -> tuple[list[QuantizedNote], list[float]]:
    """Every onset on the NEAREST point of a fixed grid: the literal page.

    No swing warp, no lag correction, no triplets, no figure prior -- a
    swung pair lands where it was played, long-short, which is the whole
    point of asking for it. What it keeps from the swing quantizer is the
    one rule that is not a reading of the music: a heard note is never
    silently lost.

    - On 16ths, a beat whose onsets the grid cannot keep apart (a 32nd run)
      is written in 32nds, that beat only, as the swing quantizer does. So
      is a beat whose last onset the grid pushes onto the next beat's own
      first note.
    - Nothing finer than a 32nd can be written, so on 32nds a note that
      lands on the previous note's grid point takes the next free one.
    - `polyphonic` (a piano texture) keeps the collision instead and makes
      it a chord (`merge_chords`): two notes on one grid point are a
      chord, not a mistake.

    Two readings are offered for a written head played in harmony
    (QuantizeConfig.literal_lag / literal_thirds, docs/multi-horn.md), both
    off by default: `lags` takes each beat's lag out of its onsets before
    the snap (`literal_lags`; a note keeps its length), and `thirds` lets a
    beat of at least `min_onsets_for_thirds` onsets that fits thirds
    (`_fits_thirds`) be written in them -- the bridge's triplet chords.
    `eighths_beat_s` writes a beat shorter than that many seconds on
    EIGHTHS ("literal-8", `LITERAL_EIGHTHS_BEAT_S`), refined to 16ths and
    then 32nds only where a coarser grid cannot keep its onsets apart or
    pushes one onto the next beat's own note. `graces` rides beside
    `chords` (QuantizedNote.grace).

    Returns (notes, snapped positions in absolute beats), like
    `quantize_notes`. The positions are raw beat time -- there is no warp
    to put back, so replay them with no swing spans.
    """
    if len(beats) < 2:
        return [], []
    extras = chords if chords is not None else [[] for _ in onsets]
    ornaments = graces if graces is not None else [[] for _ in onsets]
    placed = []
    for onset, duration, pitch, chord, grace in zip(
        onsets, durations, pitches, extras, ornaments, strict=True
    ):
        position = beat_position(onset, beats)
        if position is None:
            continue
        end = beat_position(onset + duration, beats)
        length = (
            end - position if end is not None else duration / _beat_length(beats, int(position))
        )
        if lags:
            position = unlag_position(position, lags)
        placed.append((position, max(0.0, length), pitch, list(chord), list(grace)))
    placed.sort(key=lambda note: (note[0], note[2]))

    by_beat: dict[int, list[float]] = {}
    for position, *_rest in placed:
        by_beat.setdefault(int(position), []).append(position - int(position))
    grids: dict[int, int] = {}
    finest = LITERAL_DIVISIONS["literal-32"]

    def pushes(offsets: list[float], index: int, grid: int) -> bool:
        """Would this grid push the beat's last onset onto the next beat's
        own note?"""
        return any(snap(o, grid)[0] >= 1.0 - 1e-9 for o in offsets) and any(
            snap(o, grid)[0] <= 1e-9 for o in by_beat.get(index + 1, [])
        )

    for index, offsets in by_beat.items():
        grid = divisions
        if eighths_beat_s > 0 and _beat_length(beats, index) < eighths_beat_s:
            grid = 2
        while grid < finest and (not _keeps_apart(offsets, grid) or pushes(offsets, index, grid)):
            grid *= 2
        if thirds and _fits_thirds(offsets, grid, min_onsets_for_thirds):
            grid = 3
        grids[index] = grid

    out: list[QuantizedNote] = []
    positions: list[float] = []
    previous = -math.inf
    for position, length, pitch, chord, grace in placed:
        index = int(position)
        grid = grids[index]
        slot = index + snap(position - index, grid)[0]
        if not polyphonic and slot <= previous + 1e-9:
            # The next free grid point after the previous note, on this
            # beat's grid: a 32nd late at most, and never a lost note.
            slot = index + (math.floor((previous - index) * grid + 1e-9) + 1) / grid
        previous = slot
        bar, beat = bar_and_beat(slot, beats, sections)
        out.append(
            QuantizedNote(
                bar=bar,
                beat=beat,
                duration_beats=max(1.0 / grid, snap(length, grid)[0]),
                pitch=pitch,
                timing_residual=position - slot,
                chord=chord,
                grace=grace,
            )
        )
        positions.append(slot)
    if polyphonic:
        return merge_chords(out, positions)
    return out, positions


def merge_chords(
    notes: list[QuantizedNote], positions: list[float]
) -> tuple[list[QuantizedNote], list[float]]:
    """Fold notes on one notated position into ONE chord.

    For a piano texture only. A line's two notes on one grid point are a
    grid too coarse and notate would keep one of them; a pianist's are a
    chord, rolled or struck a few tens of milliseconds apart. The chord
    lasts as long as its longest member -- chord members share a stem and a
    written value -- and keeps the first note's position, pitch and
    residual as its head. Positions stay parallel to the notes.
    """
    merged: dict[tuple[int, float], int] = {}
    out: list[QuantizedNote] = []
    kept: list[float] = []
    for note, position in zip(notes, positions, strict=True):
        key = (note.bar, round(note.beat, 6))
        at = merged.get(key)
        if at is None:
            merged[key] = len(out)
            out.append(note)
            kept.append(position)
            continue
        head = out[at]
        members = set(head.chord) | set(note.chord) | {note.pitch}
        out[at] = head.model_copy(
            update={
                "chord": sorted(members - {head.pitch}),
                "duration_beats": max(head.duration_beats, note.duration_beats),
            }
        )
    return out, kept


LAG_CANDIDATE_MAX = 0.35  # a beat's first onset past this has no downbeat to be late
# A beat's last onset from here is the NEXT downbeat, played early, and is
# neither lag evidence nor shifted. Measured (2026-09-20, R29): the
# instrument prefers 0.85 (page hit 75.1 against 74.8 here) and every page
# measure prefers 0.88 -- Omnibook rhythm 0.780 against 0.787, pianists
# 0.858 against 0.866 -- because a laid-back beat's own "a" sits at 0.86
# (Birks Works bar 4) and at 0.85 it was pushed onto the next beat line.
LAG_PUSH_MIN = 0.88


def unlag_phase(phase: float, lag: float) -> float:
    """Take the line's lag out of a beat-internal phase: a SHIFT, so the
    beat's onsets keep their spacing (a stretch onto [0, 1] turned a
    sixteenth's 0.25 into a third's 0.31 and doubled the instrument's
    "binary as triplet" class). An onset that still sits from LAG_PUSH_MIN
    on AFTER the shift is the next downbeat played early, relative to the
    line itself, and is left where it is: it belongs to the next beat's
    story, and shifted it was written a sixteenth early. Judged after the
    shift, not before: in Birks Works bar 4 the whole beat is 0.2 behind
    and its last note at 0.86 is the "a", which the listener writes, not a
    pushed downbeat. The lag is never more than the beat's own first onset
    (line_lag), so nothing goes negative.
    """
    if lag <= 0.0 or phase >= LAG_PUSH_MIN:
        return phase
    return max(0.0, phase - lag)


def relag_phase(phase: float, lag: float) -> float:
    """Inverse of `unlag_phase` where it moved anything: the replay puts
    the lag back as feel. A notated phase from LAG_PUSH_MIN on was not
    shifted."""
    if lag <= 0.0 or phase + lag >= LAG_PUSH_MIN:
        return phase
    return phase + lag


def line_lag(
    raw_by_beat: dict[int, list[float]],
    window: int,
    cap: float,
    floor: float = 0.0,
    min_candidates: int = 3,
) -> dict[int, float]:
    """How far behind the tracked beat the line sits, per beat, in beats.

    A soloist plays behind the drummer, and a human writes the line on the
    beat: Birks Works sits +0.088 behind its grid, with whole bars at
    0.22-0.33, which a sixteenth grid faithfully writes on the "e"
    (docs/notation-survey.md). The lag at a beat is the MEDIAN downbeat
    offset over `window` beats either side: a median, so one genuine "e"
    among on-time beats does not move it, and a window, so it is a
    statistic of the line and not a threshold on one beat (the shape that
    did not transfer, D34.1).

    The evidence is SYMMETRIC, or the estimate is biased late: a beat's
    first onset near the beat line counts as it stands (LAG_CANDIDATE_MAX),
    and a beat's last onset from LAG_PUSH_MIN counts as the next downbeat
    played early, negative. Without the second, a line played dead on the
    beat reads a lag of its own scatter, and every pushed note was written a
    sixteenth early on the instrument. A median under `floor` is scatter,
    not lag, and nothing is applied. Capped at `cap`, never negative, and
    never more than the beat's own first onset, so no note is moved before
    its beat line and the beat's onsets keep their spacing. Fewer than
    `min_candidates` in the window is no evidence; such beats are absent.
    """
    if window <= 0 or cap <= 0:
        return {}
    first: dict[int, float] = {}
    candidates: dict[int, list[float]] = {}
    for index, offsets in raw_by_beat.items():
        if not offsets:
            continue
        first[index] = min(offsets)
        found = []
        if first[index] <= LAG_CANDIDATE_MAX:
            found.append(first[index])
        if max(offsets) >= LAG_PUSH_MIN:
            found.append(max(offsets) - 1.0)
        if found:
            candidates[index] = found
    lags: dict[int, float] = {}
    for index in raw_by_beat:
        near = [c for j in range(index - window, index + window + 1) for c in candidates.get(j, ())]
        if len(near) < min_candidates:
            continue
        median = statistics.median(near)
        if median < max(floor, 1e-9):
            continue
        # A beat whose downbeat was already played, early, at the end of
        # the beat before has no late downbeat to pull back: shifted, its
        # first onset landed on the beat line the pushed note snaps to and
        # one of the two was dropped (+2,600 on the instrument).
        before = raw_by_beat.get(index - 1)
        if before and max(before) >= LAG_PUSH_MIN:
            continue
        lag = min(cap, median, first[index])
        if lag > 0.0:
            lags[index] = lag
    return lags


# The first onset of a beat from here up to LAG_CANDIDATE_MAX is a downbeat
# played late, for `isolated_lags`: the sounded band in which a human page
# writes the beat 69% of the time and the "e" 11% (docs/triples.md, "0.19-0.31"),
# widened to the band quantize's 16th grid sends to the "e".
ISOLATED_LAG_MIN = 0.15
# ...and the beat before must hold nothing from here on, where the eighth
# grid already sends a note to this beat's line (`_collides_on_eighths` uses
# the same line): shifted exactly onto its line, the late downbeat would
# share it with that note. Guarded at LAG_PUSH_MIN, as `line_lag` is, the
# rule dropped 18 of the WJazzD instrument's notes at two onsets; with this
# guard and the last-onset one below, none (docs/writing-round2.md).
ISOLATED_LAG_BEFORE_MAX = 0.75


def isolated_lags(
    raw_by_beat: dict[int, list[float]],
    window_lags: dict[int, float],
    max_onsets: int,
    cap: float,
) -> dict[int, float]:
    """A lag for each beat that R29's window gave none, where the beat's own
    first onset says the downbeat was played late (docs/writing-round2.md).

    `line_lag` takes a median over a window, so a line on the beat with one
    laid-back downbeat in it reads no lag, and that note is written on the
    "e" -- 3.2% of the matched notes on the triples' human onsets, every one
    sounded 0.20-0.30 late (docs/triples.md). Here a beat of at most
    `max_onsets` onsets whose first sits from ISOLATED_LAG_MIN to
    LAG_CANDIDATE_MAX is shifted by it (capped at `cap`), exactly as a
    window lag would shift it, unless the beat before holds a note from
    ISOLATED_LAG_BEFORE_MAX on: a grid may write that note on this beat's
    line, and the shifted downbeat would share it (a note lost).

    Off (QuantizeConfig.isolated_lag_max_onsets 0) and not recommended: up
    on human onsets at three onsets, level on the hand scores and the
    Omnibook at two, and at three it still drops one note of 198,983 on the
    WJazzD instrument.
    """
    out: dict[int, float] = {}
    for index, offsets in raw_by_beat.items():
        if index in window_lags or not offsets or len(offsets) > max_onsets:
            continue
        first = min(offsets)
        if not ISOLATED_LAG_MIN <= first <= LAG_CANDIDATE_MAX:
            continue
        # A last onset from LAG_PUSH_MIN on is not shifted (unlag_phase) but
        # IS unwarped by the lag, which lowers the beat's swing point: warped
        # it was the "a", straight it is the next beat's line, on its note.
        if max(offsets) >= LAG_PUSH_MIN:
            continue
        before = raw_by_beat.get(index - 1)
        if before and max(before) >= ISOLATED_LAG_BEFORE_MAX:
            continue
        out[index] = min(cap, first)
    return out


def late_downbeats(written: dict[int, list[float]], max_onsets: int) -> set[int]:
    """Beats whose first note, written on the "e", is written on the beat
    instead (QuantizeConfig.late_downbeat_max_onsets, docs/writing-round2.md).

    `written` is every beat's notated offsets as the grid choice left them.
    A beat qualifies when it holds at most `max_onsets` notes, its earliest
    is on the "e" (so nothing of its own is on the beat line), and the beat
    before wrote nothing onto that line (a note pushed to 1.0): moving the
    note there loses nothing. A post-snap reading of the one note, not a
    shift of the beat: the notes after it stay where the grid put them.

    Off and not recommended: right on human onsets, decided DOWN on the hand
    scores. On our own notes almost half the notes it moves are written
    neither on the beat nor on the "e" by the page -- mostly later, in a
    beat the page holds more notes in than we heard.
    """
    out = set()
    for index, offsets in written.items():
        if not offsets or len(offsets) > max_onsets:
            continue
        if abs(min(offsets) - 0.25) > 1e-9:
            continue
        if any(o >= 1.0 - 1e-9 for o in written.get(index - 1, [])):
            continue
        out.add(index)
    return out


def _collides_on_eighths(offsets: list[float], before: list[float], after: list[float]) -> bool:
    """Would reading this beat on the eighth grid put a note on a neighbour's?

    A late onset (0.75 and up) snaps to the NEXT beat's 1.0, where that
    beat's own first note may sit; an early one (under 0.25) snaps to this
    beat's 0, where the previous beat's late note may be pushed. Either
    collision is one note fewer on the page (notate keeps one note per grid
    position), so the beat keeps its finer grid instead. `before` and
    `after` are the neighbours' offsets, warped and raw together, so the
    test does not depend on which reading they end up under."""
    on_eighths = [snap(offset, 2)[0] for offset in offsets]
    late = any(position >= 1.0 for position in on_eighths) and any(o < 0.25 for o in after)
    early = any(position <= 0.0 for position in on_eighths) and any(o >= 0.75 for o in before)
    return late or early


def _beat_length(beats: list[float], index: int) -> float:
    if index + 1 < len(beats):
        return max(1e-9, beats[index + 1] - beats[index])
    return max(1e-9, beats[-1] - beats[-2]) if len(beats) > 1 else 1.0


def replay_onsets(
    quantized: list[QuantizedNote],
    positions: list[float],
    beats: list[float],
    spans: list[SwingSpan],
    straight_bur_ceiling: float = 1.6,
    restore_residual: bool = False,
) -> list[float]:
    """Turn quantized notes back into seconds, swing re-applied.

    The round-trip plan §5 sets as this stage's acceptance test: notated
    rhythm plus the measured feel should reproduce what was played. Takes the
    snapped positions directly rather than re-deriving them from bar numbers,
    because bar numbering is a labelling decision and this is a timing test.

    `restore_residual` decides which of two different questions is asked, and
    conflating them makes the acceptance test meaningless:

    - **False (default)** — replay the NOTATION. Grid position plus feel, no
      microtiming. Non-zero error here is real quantization error, which is
      what the 20ms criterion is about.
    - **True** — replay the performance exactly. Error is zero by
      construction, since the residual is precisely what was subtracted. Only
      useful as an invariant: it proves the stage discards no timing.
    """
    by_beat, _ = pooled_phase(spans, straight_bur_ceiling)
    out = []
    for note, position in zip(quantized, positions, strict=True):
        index = int(position)
        star = by_beat.get(index, STRAIGHT_PHASE)
        offset = position - index + (note.timing_residual if restore_residual else 0.0)
        played = index + unwarp_phase(offset, star)
        whole = int(played)
        if whole + 1 < len(beats):
            out.append(beats[whole] + (played - whole) * (beats[whole + 1] - beats[whole]))
        elif beats:
            out.append(beats[min(whole, len(beats) - 1)])
    return out


def settings(qc: QuantizeConfig) -> dict:
    """The `quantize_notes` keyword arguments a QuantizeConfig asks for --
    one mapping, so a script that quantizes by hand (the WJazzD instrument,
    the weight sweep) runs the shipped settings and not a copy of them."""
    return {
        "resolution": qc.resolution,
        "straight_bur_ceiling": qc.straight_bur_ceiling,
        "allow_triplets": qc.allow_triplets,
        "min_onsets_for_tuplet": qc.min_onsets_for_tuplet,
        "grid_slack_s": qc.grid_slack_s,
        "min_onsets_for_sixteenth": qc.min_onsets_for_sixteenth,
        "offbeat_pair_tuplet_fit": qc.offbeat_pair_tuplet_fit,
        "tuplet_needs_onsets_inside": qc.tuplet_needs_onsets_inside,
        "lag_window_beats": qc.lag_window_beats,
        "lag_cap": qc.lag_cap,
        "lag_floor": qc.lag_floor,
        "sixteenth_triplets": qc.sixteenth_triplets,
        "sixteenth_triplet_fit": qc.sixteenth_triplet_fit,
        "slow_beat_s": qc.slow_beat_s,
        "slow_beat_grids": qc.slow_beat_grids,
        "quarter_triplets": qc.quarter_triplets,
        "figure_prior_weight": qc.figure_prior_weight,
        "timing": qc.timing,
        "polyphonic": qc.polyphonic,
        "late_downbeat_max_onsets": qc.late_downbeat_max_onsets,
        "isolated_lag_max_onsets": qc.isolated_lag_max_onsets,
        "tuplet_pushed_last": qc.tuplet_pushed_last,
        "reranker": qc.reranker,
        "literal_lag": qc.literal_lag,
        "literal_thirds": qc.literal_thirds,
        "literal_lead_ins": qc.literal_lead_ins,
    }


# A lead-in and the note it leads into touch: one ends where the other
# begins (transcribe.LEAD_IN_TOUCH_S; stages never import each other).
LEAD_IN_TOUCH_S = 0.015


def absorb_lead_ins(notes: list[NoteEvent]) -> tuple[list[NoteEvent], list[list[int]]]:
    """Fold every note marked as leading into the next (NoteEvent.lead_in)
    into that note, as a transcriber writes it (docs/scoops.md).

    The pair becomes the next note, starting where the lead-in began and
    lasting both: the pages put the one note at the lead-in's place three
    times in four. A SCOOP (a semitone under) rides along as the note's grace
    note, so no heard pitch leaves the page; a RE-ATTACK (the same pitch) is
    simply the one note. The mark is checked again here -- the next note a
    semitone up or the same pitch, touching -- because the listener's edits
    can change which note comes next. Returns the notes and each one's
    grace pitches.
    """
    ordered = sorted(notes, key=lambda n: n.onset)
    out: list[NoteEvent] = []
    graces: list[list[int]] = []
    i = 0
    while i < len(ordered):
        note = ordered[i]
        after = ordered[i + 1] if i + 1 < len(ordered) else None
        if (
            note.lead_in
            and after is not None
            and after.pitch - note.pitch in (0, 1)
            and abs(note.onset + note.duration - after.onset) <= LEAD_IN_TOUCH_S
        ):
            out.append(
                after.model_copy(
                    update={"onset": note.onset, "duration": note.duration + after.duration}
                )
            )
            graces.append([note.pitch] if after.pitch != note.pitch else [])
            i += 2
            continue
        out.append(note)
        graces.append([])
        i += 1
    return out, graces


def run(document: Document, config: Config) -> Document:
    grid = document.beat_grid
    if grid is None or len(grid.beats) < 2:
        raise ValueError("quantize requires beats to have run first (document.beat_grid is None)")
    qc = config.quantize
    stem = qc.stem or config.transcribe.stem
    notes = document.notes.get(stem)
    if notes is None:
        available = ", ".join(sorted(document.notes)) or "none (run transcribe first)"
        raise ValueError(f"quantize needs notes for the {stem!r} stem; available: {available}")

    graces = None
    # A literal page writes every heard note unless it is asked to fold the
    # lead-ins too (QuantizeConfig.literal_lead_ins: a multi-horn head).
    folds = qc.timing == "swing" or qc.literal_lead_ins
    if qc.absorb_lead_ins and folds and not qc.polyphonic:
        notes, graces = absorb_lead_ins(notes)
    quantized, _positions = quantize_notes(
        [n.onset for n in notes],
        [n.duration for n in notes],
        [n.pitch for n in notes],
        grid.beats,
        document.swing,
        document.meter,
        chords=[list(n.chord) for n in notes],
        graces=graces,
        **settings(qc),
    )

    by_beat, track = pooled_phase(document.swing, qc.straight_bur_ceiling)
    if quantized and qc.timing != "swing":
        print(
            f"quantize: {len(quantized)}/{len(notes)} notes placed, literal timing "
            f"({qc.timing}), nothing warped"
        )
    elif quantized:
        residuals = [abs(n.timing_residual) for n in quantized]
        feel = (
            f"BUR {track / (1.0 - track):.2f}"
            if track is not None
            else "no swing above the noise floor - notating straight"
        )
        print(
            f"quantize: {len(quantized)}/{len(notes)} notes placed, {feel}, "
            f"{len(by_beat)} of {len(grid.beats) - 1} beats warped"
        )
        print(
            f"quantize: median |residual| {statistics.median(residuals):.3f} beats, "
            f"90th {sorted(residuals)[int(len(residuals) * 0.9)]:.3f}"
        )
    else:
        print(f"quantize: no notes placed (of {len(notes)})")

    return document.model_copy(update={"quantized": {**document.quantized, stem: quantized}})
