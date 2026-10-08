"""Two horns in harmony: which heard note is which horn's (docs/multi-horn.md).

A hard bop head is two horns playing one tune in harmony -- trumpet over
tenor, mostly a third to a sixth apart, sometimes at the octave, sometimes in
unison. Basic Pitch hears both (on the Open Sesame head 82% of the sounding
frames hold exactly two notes, 6% three); CREPE follows the upper horn and
jumps into the lower one. This module takes Basic Pitch's notes and says
which voice each belongs to, as HEARD: every note keeps the pitch it was
heard at. The page's writing conventions -- the lower horn moved up an
octave by phrase, a unison written once -- are `notation.horn_lines`', and
nothing here knows about them.

Three rules, in order:

1. **An overtone ghost is dropped.** A note 12, 19, 24, 28 (... up to the
   eighth harmonic) semitones over a note that holds it -- the ghost lives
   inside its fundamental -- with clearly lower confidence is the louder
   note's partial, not a horn: Bb5 0.30 over Bb4 0.69 on the Open Sesame head.
2. **Where three sound at once, the two most confident stay.** Two horns
   cannot sound three notes; a third is a ghost the first rule could not
   name, or bleed.
3. **Notes that overlap meaningfully are ordered by pitch**: the higher is
   voice 1. Meaningfully: at least `OVERLAP_S` shared, or `OVERLAP_SHARE` of
   the shorter note -- a release tail running into the next note is not two
   horns. A note with no partner -- one horn alone, or a unison heard as one
   note -- is voice 1, so the page writes it once.

The third rule is applied to the overlap graph as a whole, not pair by pair,
so CONTINUITY decides where pitch alone cannot: the lower horn moving under a
held upper note is a chain of overlaps with the held note, all on the far
side of it, and a brief crossing keeps each horn in its voice. The graph is
2-coloured along its strongest overlaps (a maximum spanning forest), and each
connected stretch takes the orientation that most of its overlaps, weighted
by how long they last, agree with: higher is voice 1.

Pure arithmetic on note dicts ({onset, duration, pitch, confidence}), so all
of it runs in CI. The transcriber (`stages/transcribe.py`) applies all three
rules; the GUI re-orders a listener's EDITED set with `order` alone, because a
candidate the listener switched on must never be pruned again.
"""

from typing import Any

# Semitones from a fundamental to its 2nd..8th harmonics, rounded: the
# octave, the twelfth, two octaves, the major seventeenth, the nineteenth,
# the flat twenty-first, three octaves. The listener's list was the first
# four; the rest are the same physics, and the confidence test guards them.
OVERTONES = (12, 19, 24, 28, 31, 34, 36)

# A ghost lives INSIDE its fundamental: at least this share of the ghost's
# length is under the louder note.
GHOST_INSIDE = 0.5

# Defaults for the rules (TranscribeConfig.multi_horn_*): two notes overlap
# meaningfully at 60 ms shared or 30% of the shorter; a ghost's confidence is
# at most 0.6 of its fundamental's.
OVERLAP_S = 0.06
OVERLAP_SHARE = 0.3
GHOST_RATIO = 0.6

# Why a heard note is not in either voice, as the candidates report it.
GHOST = "ghost"
THIRD = "third"


def _end(note: dict[str, Any]) -> float:
    return float(note["onset"]) + float(note["duration"])


def overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Seconds the two notes sound together (0 when they do not)."""
    return max(0.0, min(_end(a), _end(b)) - max(float(a["onset"]), float(b["onset"])))


def meaningful_length(shared: float, shortest: float, overlap_s: float, share: float) -> bool:
    """Is `shared` seconds of sounding together two horns, not a tail?"""
    if shared <= 0.0:
        return False
    return shared >= overlap_s or shared >= share * max(0.0, shortest)


def meaningful(
    a: dict[str, Any],
    b: dict[str, Any],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
) -> bool:
    """Do two notes overlap meaningfully (rule 3)?"""
    shortest = min(float(a["duration"]), float(b["duration"]))
    return meaningful_length(overlap(a, b), shortest, overlap_s, share)


def overlapping_pairs(notes: list[dict[str, Any]]) -> list[tuple[int, int, float]]:
    """Every pair of notes that sound together at all, as (i, j, seconds)
    with i < j in list order. A sweep in onset order, so it costs the
    number of overlaps rather than every pair."""
    order = sorted(range(len(notes)), key=lambda i: float(notes[i]["onset"]))
    pairs = []
    for k, i in enumerate(order):
        end = _end(notes[i])
        for j in order[k + 1 :]:
            if float(notes[j]["onset"]) >= end:
                break
            shared = overlap(notes[i], notes[j])
            if shared > 0.0:
                pairs.append((min(i, j), max(i, j), shared))
    return pairs


def ghosts(
    notes: list[dict[str, Any]],
    ratio: float = GHOST_RATIO,
    pairs: list[tuple[int, int, float]] | None = None,
) -> set[int]:
    """Indices of the overtone ghosts (rule 1): a note an overtone interval
    over a note that holds it for at least `GHOST_INSIDE` of its length,
    with at most `ratio` of that note's confidence."""
    found: set[int] = set()
    for i, j, shared in overlapping_pairs(notes) if pairs is None else pairs:
        for ghost, root in ((i, j), (j, i)):
            interval = int(notes[ghost]["pitch"]) - int(notes[root]["pitch"])
            if interval not in OVERTONES:
                continue
            if shared < GHOST_INSIDE * float(notes[ghost]["duration"]):
                continue
            if float(notes[ghost]["confidence"]) <= ratio * float(notes[root]["confidence"]):
                found.add(ghost)
    return found


def _common(notes: list[dict[str, Any]], indices: tuple[int, ...]) -> float:
    """Seconds all of `indices` sound together."""
    start = max(float(notes[i]["onset"]) for i in indices)
    end = min(_end(notes[i]) for i in indices)
    return max(0.0, end - start)


def thirds(
    notes: list[dict[str, Any]],
    alive: set[int],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
    pairs: list[tuple[int, int, float]] | None = None,
) -> set[int]:
    """Indices to drop so that no three of `alive` sound at once (rule 2).

    Three sound at once when all three share a meaningful stretch (the
    pairwise rule, applied to the time all three hold). Each such triple
    loses its least confident note; the least confident note in ANY triple
    goes first, which is exactly that note of its own triple, and a note it
    resolves for another triple saves that triple's own least confident."""
    pairs = overlapping_pairs(notes) if pairs is None else pairs
    neighbours: dict[int, set[int]] = {i: set() for i in alive}
    for i, j, _shared in pairs:
        if i in alive and j in alive and meaningful(notes[i], notes[j], overlap_s, share):
            neighbours[i].add(j)
            neighbours[j].add(i)
    triples = []
    for i in sorted(alive):
        for j in sorted(n for n in neighbours[i] if n > i):
            for k in sorted(n for n in neighbours[i] & neighbours[j] if n > j):
                shortest = min(float(notes[x]["duration"]) for x in (i, j, k))
                if meaningful_length(_common(notes, (i, j, k)), shortest, overlap_s, share):
                    triples.append({i, j, k})

    def weakness(i: int) -> tuple[float, float, float]:
        # Least confident first; then the shorter; then the later.
        note = notes[i]
        return (float(note["confidence"]), float(note["duration"]), -float(note["onset"]))

    dropped: set[int] = set()
    while triples:
        members = set().union(*triples)
        weakest = min(members, key=weakness)
        dropped.add(weakest)
        triples = [t for t in triples if weakest not in t]
    return dropped


def order(
    notes: list[dict[str, Any]],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
) -> list[int]:
    """Each note's voice, 1 (upper) or 2 (lower), by rule 3 alone.

    The meaningful overlaps make a graph; its strongest edges (a maximum
    spanning forest by seconds shared) are 2-coloured, and each tree takes
    the orientation most of its overlaps agree with, weighted by length:
    the higher note of a pair is voice 1. A note with no partner is voice 1.
    Nothing is dropped -- three notes at once (a listener's addition) leave
    two of them in one voice."""
    edges = [
        (shared, i, j)
        for i, j, shared in overlapping_pairs(notes)
        if meaningful(notes[i], notes[j], overlap_s, share)
    ]
    parent = list(range(len(notes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tree: dict[int, list[int]] = {i: [] for i in range(len(notes))}
    for _shared, i, j in sorted(edges, key=lambda e: (-e[0], e[1], e[2])):
        a, b = root(i), root(j)
        if a != b:
            parent[a] = b
            tree[i].append(j)
            tree[j].append(i)

    colour: dict[int, int] = {}
    component: dict[int, int] = {}
    for start in range(len(notes)):
        if start in colour:
            continue
        colour[start] = 0
        component[start] = start
        stack = [start]
        while stack:
            here = stack.pop()
            for there in tree[here]:
                if there not in colour:
                    colour[there] = 1 - colour[here]
                    component[there] = start
                    stack.append(there)

    # Per tree: does colour 0 sound ABOVE colour 1? Every meaningful overlap
    # votes, the tree's and the rest, weighted by how long it lasts.
    votes: dict[int, float] = {}
    for shared, i, j in edges:
        if colour[i] == colour[j]:
            continue
        zero, one = (i, j) if colour[i] == 0 else (j, i)
        difference = int(notes[zero]["pitch"]) - int(notes[one]["pitch"])
        sign = (difference > 0) - (difference < 0)
        votes[component[i]] = votes.get(component[i], 0.0) + sign * shared
    voices = []
    for i in range(len(notes)):
        if not tree[i]:
            voices.append(1)
            continue
        zero_on_top = votes.get(component[i], 0.0) >= 0.0
        voices.append(1 if (colour[i] == 0) == zero_on_top else 2)
    return voices


def assign(
    notes: list[dict[str, Any]],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
    ghost_ratio: float = GHOST_RATIO,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """All three rules: (the notes the two voices hold, each with a `voice`;
    the notes neither holds, each with `dropped` saying why).

    Both lists are copies, in onset order (the higher pitch first at one
    onset). The dropped notes are what a listener may switch back on."""
    pairs = overlapping_pairs(notes)
    ghosted = ghosts(notes, ghost_ratio, pairs)
    alive = set(range(len(notes))) - ghosted
    crowded = thirds(notes, alive, overlap_s, share, pairs)
    alive -= crowded
    kept_indices = sorted(alive)
    kept = [dict(notes[i]) for i in kept_indices]
    for note, voice in zip(kept, order(kept, overlap_s, share), strict=True):
        note["voice"] = voice
    dropped = [
        {**notes[i], "dropped": GHOST if i in ghosted else THIRD} for i in sorted(ghosted | crowded)
    ]

    def by_time(note: dict[str, Any]) -> tuple[float, int]:
        return (float(note["onset"]), -int(note["pitch"]))

    return sorted(kept, key=by_time), sorted(dropped, key=by_time)
