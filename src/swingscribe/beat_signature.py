"""The Rhythm Perceiver's per-beat measure, on our pages (docs/beat-signature.md).

Shanin, Riley and Dixon, "Audio-to-Score Jazz Solo Transcription with the
Rhythm Perceiver" (ICASSP 2026) score a page one BEAT at a time. Section 3,
"Score and Rhythm Tokenization", divides every beat into 12 equal bins and
gives each bin one of three rhythm tokens -- "The first bin of each note is
an onset token"; the note's later bins are ties, and bins between notes are
rests. A beat's twelve tokens, pitch thrown away, are its BEAT SIGNATURE.
Twelve bins hold sixteenths (3), triplet eighths (4), sixteenth triplets (2)
and everything built from them; a 32nd (1.5 bins) or a dotted sixteenth (4.5)
does not fit, and section 3 files such a beat under a special "unsupported"
class. The classes are the signatures counted on Filosax's pages: 42 with at
least 30 beats, every other one filed as "rare" (section 3).

Section 4 reports "beat-level rhythm accuracy" beside onset F1 and names no
formula; the rhythm branch predicts one class per beat, so the reading taken
here is the share of beats whose class is the reference's. Its Omnibook
figure (0.53, Table 2) is over the "easy" 60% of the test set, the tracks
whose automatic beats held (section 4), and the reference is LORIA's
Omnibook MusicXML -- the scores our own Omnibook set is scored against, per
Riley and Dixon, SMC 2024, section 3.1.

What cannot be copied, and how it is emulated:

- **Their beats.** Their prediction lives on madmom's beats, their reference
  on the dataset's hand-placed downbeats, and on the easy tracks the two
  agree beat for beat. Our page lives on OUR beat grid, and the reference on
  its own bar 1. `beat_pairs` names each reference beat's beat on our page
  from the pitch-matched notes: the whole-beat shift (ours minus theirs)
  commonest among the matches around it (`triples.local_shifts`), which is
  what "aligned on the ground-truth beats" means on a page whose grid slipped
  a beat somewhere. `local=False` takes the one commonest shift for the whole
  page instead -- the strict reading, where a slipped beat costs everything
  after it. Only the stretch both pages cover is scored: the reference beats
  from its first matched note to its last.
- **Their classes.** Filosax's pages are not here. `inventory` takes the 42
  commonest signatures of a human corpus instead (the script counts the PDF
  transcriptions, docs/beat-signature.md); with `inventory=None` the exact
  twelve tokens must agree -- never easier than the class reading, which
  also credits "rare" for "rare".
- **Whether a rest is a rest.** The tokens tell a tie from a rest, so an
  eighth and an eighth rest is not a quarter. `onsets_only=True` scores the
  onset pattern alone, which says how much of a miss is placement and how
  much is value.

Pure arithmetic over (position, duration) pairs in quarter notes -- a
`benchmark.notation_notes` list, a `mscz.Score.melody` -- so it runs in CI.
Nothing here reads a file, and nothing it returns is a note list: signatures
are twelve-letter rhythm strings, aggregate by construction.
"""

from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Iterable

from swingscribe.score_bars import TRACE_WINDOW

BINS = 12
ONSET, TIE, REST = "O", "T", "R"
# The onset-only view writes every non-onset bin as this.
BLANK = "-"
UNSUPPORTED = "unsupported"
RARE = "rare"
# The paper's class count (section 3): signatures with at least RARE_BELOW
# beats on Filosax's pages.
PAPER_CLASSES = 42
RARE_BELOW = 30
# How far a boundary may sit from a bin edge and still be on it, in beats.
# Positions arrive as floats (a triplet is 0.3333...); a bin is 0.083.
GRID_TOLERANCE = 1e-3


def line_events(notes: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """(onset, end) of a single line, in beats: one event per distinct onset,
    lasting as long as its longest note but never past the next onset.

    The tokenization is monophonic (section 3): a chord is one onset, and a
    note held under the next one ends where that one starts -- a single line
    has no other way to write it.
    """
    longest: dict[float, float] = {}
    for position, duration in notes:
        key = round(float(position), 6)
        longest[key] = max(longest.get(key, 0.0), float(duration))
    onsets = sorted(longest)
    out = []
    for index, onset in enumerate(onsets):
        end = onset + max(0.0, longest[onset])
        if index + 1 < len(onsets):
            end = min(end, onsets[index + 1])
        out.append((onset, end))
    return out


def _on_grid(offset: float) -> bool:
    scaled = offset * BINS
    return abs(scaled - round(scaled)) <= GRID_TOLERANCE * BINS


def beat_signature(
    events: list[tuple[float, float]],
    beat: int,
    onsets_only: bool = False,
    starts: list[float] | None = None,
) -> str:
    """The twelve tokens of quarter-note beat `beat` (the span [beat, beat+1)).

    `events` are `line_events`: sorted, not overlapping. A beat with an
    onset, or a note ending, off the twelve-bin grid is UNSUPPORTED (section
    3 files a beat it cannot build under that class). `onsets_only` writes
    every non-onset bin BLANK and asks only the onsets to sit on the grid: a
    32nd's end does not spoil the onset pattern. `starts` is the events'
    onsets, precomputed by a caller asking about many beats.
    """
    lo, hi = float(beat), float(beat) + 1.0
    eps = GRID_TOLERANCE
    if starts is None:
        starts = [onset for onset, _ in events]
    tokens = [BLANK if onsets_only else REST] * BINS
    first = max(0, bisect.bisect_right(starts, lo + eps) - 1)
    for onset, end in events[first:]:
        if onset >= hi - eps:
            break
        if onset < lo - eps and end <= lo + eps:
            continue  # over before the beat began
        edges = (onset,) if onsets_only else (onset, end)
        for edge in edges:
            if lo + eps < edge < hi - eps and not _on_grid(edge - lo):
                return UNSUPPORTED
        stop = min(BINS, max(0, round((end - lo) * BINS)))
        if onset >= lo - eps:
            start = round((onset - lo) * BINS)
            tokens[start] = ONSET
            held = range(start + 1, stop)
        else:
            held = range(0, stop)  # a note begun in an earlier beat
        if not onsets_only:
            for k in held:
                tokens[k] = TIE
    return "".join(tokens)


def signatures(
    events: list[tuple[float, float]], beats: Iterable[int], onsets_only: bool = False
) -> dict[int, str]:
    """`beat_signature` for each of `beats`."""
    starts = [onset for onset, _ in events]
    return {b: beat_signature(events, b, onsets_only, starts) for b in beats}


def bar_events(
    length: float, onsets: Iterable[float], rests: Iterable[tuple[float, float]]
) -> list[tuple[float, float]]:
    """`line_events` for one bar that FILLS its signature, from its onsets
    and its rests (position, length), in quarters from the bar's start.

    What a transcription page's reader knows about a bar (the figure prior's
    reader, scripts/figure_prior.py): every instant is inside a note or
    inside a rest, so a note lasts from its onset to the next onset or rest;
    and time before the first onset that is not a rest is a note TIED INTO
    the bar, returned as an event that began before it (onset -1).
    """
    rest_spans = sorted((float(p), float(p) + float(d)) for p, d in rests if d > 0)
    points = sorted({float(o) for o in onsets})
    cuts = sorted({*points, *(start for start, _ in rest_spans), float(length)})
    events = []
    first_sound = min([*points, *(start for start, _ in rest_spans), float(length)])
    if first_sound > GRID_TOLERANCE:
        events.append((-1.0, first_sound))
    for onset in points:
        later = [c for c in cuts if c > onset + GRID_TOLERANCE]
        events.append((onset, later[0] if later else float(length)))
    return events


def signature_class(signature: str, inventory: frozenset[str] | None) -> str:
    """The class a signature is scored as: itself, or RARE when an inventory
    is given and does not hold it. UNSUPPORTED is always its own class."""
    if inventory is None or signature == UNSUPPORTED or signature in inventory:
        return signature
    return RARE


def build_inventory(counts: Counter, classes: int = PAPER_CLASSES) -> frozenset[str]:
    """The `classes` commonest supported signatures of `counts` -- the
    paper's 42 Filosax classes (section 3), counted from whatever human
    corpus the caller has. Ties at the cut go to the lexically first, so the
    inventory is a function of the counts alone."""
    ranked = sorted(
        ((s, n) for s, n in counts.items() if s not in (UNSUPPORTED, RARE)),
        key=lambda item: (-item[1], item[0]),
    )
    return frozenset(s for s, _ in ranked[:classes])


# ── which of our beats is which of theirs ───────────────────────────────────


# Matches either side whose whole-beat shift votes a match's local shift: the
# difference trace's own window (score_bars.TRACE_WINDOW, 15 wide), "wide
# enough that a syncopation we resolved differently never reads as a step".
# triples.local_shifts defaults to 15 either side, which outvoted a stretch
# of 16 matches a beat off on Blues For Alice that the trace sees.
LOCAL_WINDOW = TRACE_WINDOW // 2


def _mode(values: list[int]) -> int:
    return Counter(values).most_common(1)[0][0]


def beat_pairs(
    ours: list[tuple[float, int]], theirs: list[tuple[float, int]], local: bool = True
) -> dict:
    """Reference beat -> our beat, over the stretch both pages cover.

    `ours` and `theirs` are (position in quarters from each page's own bar
    1, pitch), in order. The pitch sequences are aligned at the
    transposition the whole line settles (`alignment.measured_transposition`,
    as every notation scorer does), and each true match votes our position
    minus theirs, rounded to a whole beat. `local` takes each reference
    beat's shift from the nearest match's LOCAL shift (the commonest of the
    LOCAL_WINDOW matches either side, `triples.local_shifts`), so a beat our
    grid dropped costs the beats beside the slip and not every beat after
    it; otherwise one shift, the commonest, holds for the page.

    Returned: `pairs` [(their beat, our beat)], `matches`, `shift` (the
    commonest), and `clock_share` -- the share of matches whose local shift
    is the commonest one, 1.0 on a page whose grid never slipped.
    """
    from swingscribe.alignment import measured_transposition
    from swingscribe.triples import local_shifts

    empty = {"pairs": [], "matches": 0, "shift": 0, "clock_share": 0.0}
    if not ours or not theirs:
        return empty
    offset, aligned = measured_transposition([p for _, p in theirs], [p for _, p in ours])
    matched = [
        (theirs[ri][0], ours[ei][0])
        for ri, ei in aligned.pairs
        if ri is not None and ei is not None and theirs[ri][1] == ours[ei][1] + offset
    ]
    if not matched:
        return empty
    deltas = [our - their for their, our in matched]
    overall = _mode([round(d) for d in deltas])
    around = local_shifts(deltas, LOCAL_WINDOW)
    shifts = around if local else [overall] * len(deltas)
    where = [their for their, _ in matched]
    pairs = []
    for beat in range(int(where[0] // 1), int(where[-1] // 1) + 1):
        k = bisect.bisect_left(where, beat + 0.5)
        if k == len(where) or (k > 0 and beat + 0.5 - where[k - 1] <= where[k] - (beat + 0.5)):
            k -= 1
        pairs.append((beat, beat + shifts[k]))
    return {
        "pairs": pairs,
        "matches": len(matched),
        "shift": overall,
        "clock_share": sum(1 for s in around if s == overall) / len(deltas),
    }


# ── the score ───────────────────────────────────────────────────────────────


def score_beats(
    ours: list[tuple[float, float]],
    theirs: list[tuple[float, float]],
    pairs: list[tuple[int, int]],
    inventory: frozenset[str] | None = None,
    onsets_only: bool = False,
) -> dict:
    """Beat-signature accuracy over `pairs` (their beat, our beat).

    `ours`/`theirs` are (position, duration) in quarters. A beat is right
    when the two classes agree (`signature_class`). `confusion` counts
    (their signature, ours) for every beat, raw signatures, so a caller can
    say which figures go wrong; `unsupported` counts the beats each side
    could not tokenize.
    """
    our_events, their_events = line_events(ours), line_events(theirs)
    our_starts = [onset for onset, _ in our_events]
    their_starts = [onset for onset, _ in their_events]
    confusion: Counter = Counter()
    correct = 0
    unsupported = {"theirs": 0, "ours": 0}
    for their_beat, our_beat in pairs:
        t = beat_signature(their_events, their_beat, onsets_only, their_starts)
        o = beat_signature(our_events, our_beat, onsets_only, our_starts)
        confusion[(t, o)] += 1
        unsupported["theirs"] += t == UNSUPPORTED
        unsupported["ours"] += o == UNSUPPORTED
        correct += signature_class(t, inventory) == signature_class(o, inventory)
    beats = len(pairs)
    return {
        "beats": beats,
        "correct": correct,
        "accuracy": correct / beats if beats else 0.0,
        "unsupported": unsupported,
        "confusion": confusion,
    }


def onset_counts(
    ours: list[tuple[float, float]],
    theirs: list[tuple[float, float]],
    pairs: list[tuple[int, int]],
) -> dict:
    """Onsets placed exactly where the reference placed them, over `pairs`.

    Section 4 reports onset precision, recall and F1 at zero tolerance
    beside rhythm accuracy: on a score grid that means the same position in
    the same (aligned) beat, pitch aside. Counted on positions, not bins,
    so a 32nd the twelve bins cannot hold still counts. `tp` / `ours` /
    `theirs` are summable over pages; `f1` is this page's.
    """
    our_starts = sorted({round(p, 6) for p, _ in ours})
    their_starts = sorted({round(p, 6) for p, _ in theirs})
    tp = n_ours = n_theirs = 0
    for their_beat, our_beat in pairs:
        mine = [
            p - our_beat
            for p in our_starts[
                bisect.bisect_left(our_starts, our_beat - GRID_TOLERANCE) : bisect.bisect_left(
                    our_starts, our_beat + 1 - GRID_TOLERANCE
                )
            ]
        ]
        yours = [
            p - their_beat
            for p in their_starts[
                bisect.bisect_left(their_starts, their_beat - GRID_TOLERANCE) : bisect.bisect_left(
                    their_starts, their_beat + 1 - GRID_TOLERANCE
                )
            ]
        ]
        n_ours += len(mine)
        n_theirs += len(yours)
        tp += sum(1 for y in yours if any(abs(y - m) <= GRID_TOLERANCE for m in mine))
    precision = tp / n_ours if n_ours else 0.0
    recall = tp / n_theirs if n_theirs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "ours": n_ours, "theirs": n_theirs, "f1": f1}


VIEWS = ("exact", "classes", "onsets")


def accuracy(
    ours: list[tuple[float, float, int]],
    theirs: list[tuple[float, float, int]],
    inventory: frozenset[str] | None = None,
    local: bool = True,
) -> dict:
    """Our page against a reference, one beat at a time, in three views.

    Both are (position, duration, pitch) in quarters from each page's own bar
    1: `benchmark.notation_notes(notation)` for a Notation, `(n.position,
    n.duration, n.pitch)` over `mscz.Score.melody` for a parsed score. The
    views: `exact` (all twelve tokens), `classes` (the paper's reading, when
    an `inventory` is given; the same as `exact` without one) and `onsets`
    (the onset pattern alone). Each is `score_beats`'s dict; the pairing's
    `matches`, `shift` and `clock_share` ride beside them, and
    `onset_counts` over the same beats as `onset_f1`.
    """
    pairing = beat_pairs([(p, n) for p, _, n in ours], [(p, n) for p, _, n in theirs], local)
    rhythm_ours = [(p, d) for p, d, _ in ours]
    rhythm_theirs = [(p, d) for p, d, _ in theirs]
    out = {k: pairing[k] for k in ("matches", "shift", "clock_share")}
    out["exact"] = score_beats(rhythm_ours, rhythm_theirs, pairing["pairs"])
    out["classes"] = (
        score_beats(rhythm_ours, rhythm_theirs, pairing["pairs"], inventory)
        if inventory is not None
        else out["exact"]
    )
    out["onsets"] = score_beats(rhythm_ours, rhythm_theirs, pairing["pairs"], onsets_only=True)
    out["onset_f1"] = onset_counts(rhythm_ours, rhythm_theirs, pairing["pairs"])
    return out


def notation_rhythm(notation) -> list[tuple[float, float, int]]:
    """A Notation as `accuracy` reads it: `benchmark.notation_notes`, which
    merges ties and halves a double-time page to true quarters."""
    from swingscribe.benchmark import notation_notes

    return notation_notes(notation)


def score_rhythm(score) -> list[tuple[float, float, int]]:
    """A parsed `mscz.Score` as `accuracy` reads it: its single line."""
    return [(n.position, n.duration, n.pitch) for n in score.melody]


def against_score(notation, score, inventory=None, local: bool = True) -> dict:
    """`accuracy` of our Notation against a parsed hand score."""
    return accuracy(notation_rhythm(notation), score_rhythm(score), inventory, local)


def against_notation(notation, reference, inventory=None, local: bool = True) -> dict:
    """`accuracy` of one Notation against another (e.g. a WJazzD-derived page)."""
    return accuracy(notation_rhythm(notation), notation_rhythm(reference), inventory, local)


# ── reading a signature ─────────────────────────────────────────────────────


def onset_pattern(signature: str) -> str:
    """A full signature's onsets alone -- `beat_signature(onsets_only=True)`
    read off the twelve tokens, so a confusion table of full signatures can
    say which misses were placement and which were only a length or a rest.
    UNSUPPORTED stays itself: its onsets were never written down."""
    if signature in (UNSUPPORTED, RARE):
        return signature
    return "".join(ONSET if token == ONSET else BLANK for token in signature)


# Twelfths of a beat -> the value a page writes, for the names below.
VALUE_OF = {
    12: "q",
    9: "8.",
    8: "q3",
    6: "8",
    4: "8t",
    3: "16",
    2: "16t",
    1: "1/12",
}


def describe(signature: str) -> str:
    """A signature as note values: "8 8" for OTTTTTOTTTTT, "8t 8t 8t" for a
    triplet, "~8 8" for an eighth tied in from the beat before and an
    eighth, "r8 8" with a rest. Values with no single name print as twelfths
    ("5/12")."""
    if signature in (UNSUPPORTED, RARE):
        return signature
    parts = []
    k = 0
    while k < len(signature):
        token = signature[k]
        j = k + 1
        if token == ONSET:
            while j < len(signature) and signature[j] in (TIE, BLANK):
                j += 1
            prefix = ""
        else:
            while j < len(signature) and signature[j] == token:
                j += 1
            prefix = {TIE: "~", REST: "r", BLANK: "~"}[token]
        width = j - k
        parts.append(prefix + VALUE_OF.get(width, f"{width}/12"))
        k = j
    return " ".join(parts)
