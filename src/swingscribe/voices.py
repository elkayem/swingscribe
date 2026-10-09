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

The rules, in order:

1. **An overtone ghost is dropped.** A note 12, 19, 24, 28 (... up to the
   eighth harmonic) semitones over a note that holds it -- the ghost lives
   inside its fundamental -- with clearly lower confidence is the louder
   note's partial, not a horn: Bb5 0.30 over Bb4 0.69 on the Open Sesame head.
2. **A new chord ends what was sounding, and a note starting beats a note
   ending.** Two notes of different pitches struck together are both horns
   attacking, so a note still sounding when they start is a release tail,
   and it is cut there. And where three still sound at once and one of
   them is ENDING -- it began well before the newest and stops before both
   others -- it is cut where the newest starts. Without this a held tail
   decided the voices of the chord after it (the Open Sesame head's bar 26,
   in the listener's numbering: the upper horn's F4 still ringing put the
   next chord's Eb4 in the lower voice) and, as a third note, cost a chord
   one of its own (bar 28's G4, under a held C5 as the A-flat before it
   rang on). And a note a step or two from the ONLY note sounding, which
   ends within 0.25 s, is that horn's legato SUCCESSOR, not the other horn
   entering (`legato_successors`): the old note is cut, and after rule 4
   the successor keeps its horn's voice (`continue_voices`) -- bar 26's
   tenor E-flat into D stays in voice 2.
3. **Where three sound at once, the two most confident stay.** Two horns
   cannot sound three notes; a third is a ghost the first rule could not
   name, or bleed.
4. **Notes that overlap meaningfully are ordered by pitch**: the higher is
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

Then, in each voice:

5. **A held note Basic Pitch split is joined again** where CREPE's frame
   trace holds that pitch across the join with no attack of its own
   (`rejoin_splits`). Basic Pitch re-attacks a held note on a stray onset
   peak (bar 24's D5 written as a dotted half tied to a re-attacked
   quarter); CREPE follows one horn at a time, so it can vouch for a held
   note only where it is on that horn, and elsewhere nothing is joined.
   **5b. And where the other horn sounds across the join** with no attack
   of its own near it and the stem's energy barely dips (`join_held`): in
   a harmonized head both horns articulate together, so one horn's
   "re-attack" under the other's held note is Basic Pitch's re-trigger
   (the listener marked all five on the Open Sesame head one held note).
6. **A lead-in is marked** (`mark_lead_ins`, NoteEvent.lead_in, docs/
   scoops.md): a note of at most `LEAD_IN_MAX_S` a semitone under the next
   note in its voice, or at its pitch, and touching it -- the scoop into a
   held chord (both horns open bar 23 with one) and the head of a
   re-attack. It is heard, so it stays; the page folds it into the note.

Pure arithmetic on note dicts ({onset, duration, pitch, confidence}), so all
of it runs in CI. The transcriber (`stages/transcribe.py`) applies them all;
the GUI re-orders a listener's EDITED set with `order` and `continue_voices`
alone, because a candidate the listener switched on must never be pruned
again.
"""

import math
import statistics
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

# Two notes struck this close together are one chord: both horns attacking
# (rule 2). Basic Pitch's frame is 11.6 ms; two horns attacking a written
# chord land within a few frames of each other.
CHORD_ONSET_S = 0.06

# Two notes of one voice whose join is within this are touching: a held
# note split, or a lead-in into the next note (rules 5 and 6). Two of Basic
# Pitch's frames, because a note it ends is cut back to its last frame over
# the threshold.
TOUCH_S = 0.03

# Rule 5: CREPE's trace must hold the note's pitch for this long either
# side of the join, and have no corroborated onset within `REJOIN_ONSET_S`
# of it.
REJOIN_HOLD_S = 0.05
REJOIN_ONSET_S = 0.04

# Rule 6: a lead-in is at most this long (the CREPE line's own
# glide_max_ms and reattack_max_ms), and the note it leads into at least
# this many times as long: a scoop leads into a note that is held. Without
# the second test a run of sixteenths rising by semitones, or repeated, at
# 250 bpm (60 ms each) would be read as a chain of lead-ins. The CREPE line
# tells a scoop by its frames never settling on their semitone; Basic Pitch
# gives no frames, so the held note is the evidence here.
LEAD_IN_MAX_S = 0.1
LEAD_IN_TARGET_RATIO = 3.0

# Rule 2's legato successor: a note a step or two from the ONLY note
# sounding when it starts, which ends within this of its start, is that
# horn moving on -- the old note's release overlapping the new -- not the
# other horn coming in under it.
SUCCESSOR_TAIL_S = 0.25
SUCCESSOR_MAX_STEP = 2

# Rule 5b: in a HARMONIZED head both horns articulate together, so a voice's
# two touching notes of one pitch are one held note where the OTHER horn
# sounds straight across the join (from `HELD_ONSET_S` before it to
# `HELD_ONSET_S` after) with no attack of its own within `HELD_ONSET_S`,
# and the stem's energy dips less than `HELD_MAX_DIP_DB` there. The
# listener marked all five such joins on the Open Sesame head one held note
# (energy dip -1.3 to 3.1 dB, the other horn's nearest attack 127-443 ms
# away); the head's real repeats have both horns re-attacking within 12 ms
# and dips of 8-30 dB (Local task A6, docs/multi-horn.md). `DIP_WINDOW_S`
# and the 10 ms frames are scripts/multi_horn_joins.py's measurement.
HELD_ONSET_S = 0.06
HELD_MAX_DIP_DB = 5.0
DIP_WINDOW_S = 0.03


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


def _triples(
    notes: list[dict[str, Any]],
    alive: set[int],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
    pairs: list[tuple[int, int, float]] | None = None,
) -> list[set[int]]:
    """Every three of `alive` that sound at once: all three share a
    meaningful stretch (the pairwise rule, applied to the time all three
    hold)."""
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
    return triples


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
    triples = _triples(notes, alive, overlap_s, share, pairs)

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


def trim_tails(
    notes: list[dict[str, Any]],
    alive: set[int],
    chord_onset: float = CHORD_ONSET_S,
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
) -> int:
    """Rule 2, in place on `notes`, in two passes. Every note of `alive`
    still sounding when a NEW CHORD -- two notes of `alive` at different
    pitches struck within `chord_onset` of each other, after it began --
    starts is cut where the chord starts. Then, where three still sound at
    once, a note ENDING -- it ends before both others and began more than
    `chord_onset` before the latest -- is cut where the latest starts: a
    note starting beats a note ending (bar 28: one horn moving from A-flat
    to G under the other's held C, the A-flat's tail ringing on). Returns
    how many were cut."""
    order_ = sorted(alive, key=lambda i: float(notes[i]["onset"]))
    starts = []
    for k, i in enumerate(order_):
        for j in order_[k + 1 :]:
            if float(notes[j]["onset"]) - float(notes[i]["onset"]) > chord_onset:
                break
            if int(notes[i]["pitch"]) != int(notes[j]["pitch"]):
                starts.append(float(notes[i]["onset"]))
                break
    cut = 0
    for start in sorted(set(starts)):
        for i in alive:
            onset = float(notes[i]["onset"])
            if onset < start - chord_onset and onset + float(notes[i]["duration"]) > start:
                notes[i]["duration"] = start - onset
                cut += 1
    triples = _triples(notes, alive, overlap_s, share)
    for triple in sorted(triples, key=lambda t: max(float(notes[i]["onset"]) for i in t)):
        ending = min(triple, key=lambda i: _end(notes[i]))
        latest = max(triple, key=lambda i: float(notes[i]["onset"]))
        others = triple - {ending}
        if ending == latest or any(_end(notes[i]) <= _end(notes[ending]) for i in others):
            continue
        start = float(notes[latest]["onset"])
        onset = float(notes[ending]["onset"])
        if onset < start - chord_onset and _end(notes[ending]) > start:
            notes[ending]["duration"] = start - onset
            cut += 1
    return cut


def legato_successors(
    notes: list[dict[str, Any]],
    alive: set[int],
    tail: float = SUCCESSOR_TAIL_S,
    max_step: int = SUCCESSOR_MAX_STEP,
    chord_onset: float = CHORD_ONSET_S,
) -> dict[int, int]:
    """Rule 2's third pass, in place on `notes`: a note of `alive` that
    starts while exactly ONE other sounds -- begun more than `chord_onset`
    before it, ending at most `tail` after it, 1 to `max_step` semitones
    away -- and with no other note struck with it, is that note's legato
    SUCCESSOR: the same horn moving on, its old note's release overlapping
    the new. The old note is cut where the new begins, so the two are never
    read as two horns. Returns {successor: predecessor} (indices into
    `notes`), for `continue_voices`.

    The Open Sesame head's bar 26: the tenor's E-flat on 1 into D on 3,
    the E-flat ringing 190 ms on. Read as two horns, the D was put in the
    upper voice over it."""
    ordered = sorted(alive, key=lambda i: float(notes[i]["onset"]))
    links: dict[int, int] = {}
    for i in ordered:
        start = float(notes[i]["onset"])
        struck_with = any(
            j != i and abs(float(notes[j]["onset"]) - start) <= chord_onset for j in alive
        )
        if struck_with:
            continue
        sounding = [
            j
            for j in alive
            if j != i and float(notes[j]["onset"]) < start - chord_onset and _end(notes[j]) > start
        ]
        if len(sounding) != 1:
            continue
        (j,) = sounding
        step = abs(int(notes[i]["pitch"]) - int(notes[j]["pitch"]))
        if 1 <= step <= max_step and _end(notes[j]) - start <= tail:
            notes[j]["duration"] = start - float(notes[j]["onset"])
            links[i] = j
    return links


def continue_voices(
    kept: list[dict[str, Any]],
    indices: list[int],
    links: dict[int, int],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
    touch: float = TOUCH_S,
    max_step: int = SUCCESSOR_MAX_STEP,
) -> int:
    """After ordering, in place: a note with NO partner of its own -- which
    rule 4 puts in voice 1 -- stays in voice 2 when every note it continues
    is in voice 2: its legato predecessor (`legato_successors`, `links`
    over the original indices `indices` name), or a note of at most
    `max_step` semitones away ending within `touch` of its start. In onset
    order, so a line carries its voice on. A lone horn after a rest, or one
    continuing anything in voice 1, is voice 1 as before. Returns how many
    moved."""
    position = {index: k for k, index in enumerate(indices)}
    partnered = set()
    for a, b, _shared in overlapping_pairs(kept):
        if meaningful(kept[a], kept[b], overlap_s, share):
            partnered.update((a, b))
    moved = 0
    for k in sorted(range(len(kept)), key=lambda k: float(kept[k]["onset"])):
        if k in partnered or int(kept[k].get("voice", 1)) == 2:
            continue
        start = float(kept[k]["onset"])
        before = [
            j
            for j, other in enumerate(kept)
            if j != k
            and abs(_end(other) - start) <= touch
            and abs(int(other["pitch"]) - int(kept[k]["pitch"])) <= max_step
        ]
        predecessor = links.get(indices[k])
        if predecessor in position:
            before.append(position[predecessor])
        if before and all(int(kept[j].get("voice", 1)) == 2 for j in before):
            kept[k]["voice"] = 2
            moved += 1
    return moved


def _voice_runs(notes: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Each voice's notes in onset order."""
    runs: dict[int, list[dict[str, Any]]] = {}
    for note in sorted(notes, key=lambda n: float(n["onset"])):
        runs.setdefault(int(note.get("voice", 1)), []).append(note)
    return runs


def _touching(a: dict[str, Any], b: dict[str, Any], touch: float = TOUCH_S) -> bool:
    return abs(_end(a) - float(b["onset"])) <= touch


def rejoin_splits(
    notes: list[dict[str, Any]],
    track: tuple[float, float, list[float | None]] | None,
    attacks: list[float] = (),
    hold: float = REJOIN_HOLD_S,
    attack_window: float = REJOIN_ONSET_S,
) -> list[dict[str, Any]]:
    """Rule 5: a voice's two touching notes of one pitch are ONE note where
    CREPE's trace -- `track` as (time of frame 0, hop, pitch per frame, None
    where unvoiced) -- holds that pitch, voiced and within half a semitone,
    across `hold` either side of the join, and none of CREPE's corroborated
    onsets (`attacks`) is within `attack_window` of it. Notes in, notes out,
    the first of a joined pair lasting both; no track joins nothing."""
    if track is None:
        return notes
    start, hop, pitches = track

    def held(pitch: int, at: float) -> bool:
        first = int(round((at - hold - start) / hop))
        last = int(round((at + hold - start) / hop))
        if first < 0 or last >= len(pitches) or last < first:
            return False
        return all(p is not None and abs(p - pitch) < 0.5 for p in pitches[first : last + 1])

    out: list[dict[str, Any]] = []
    for run in _voice_runs(notes).values():
        merged: list[dict[str, Any]] = []
        for note in run:
            previous = merged[-1] if merged else None
            at = float(note["onset"])
            if (
                previous is not None
                and int(previous["pitch"]) == int(note["pitch"])
                and _touching(previous, note)
                and held(int(note["pitch"]), at)
                and not any(abs(a - at) <= attack_window for a in attacks)
            ):
                previous["duration"] = _end(note) - float(previous["onset"])
                previous["confidence"] = max(
                    float(previous["confidence"]), float(note["confidence"])
                )
                continue
            merged.append(dict(note))
        out.extend(merged)
    return out


def energy_dip(
    energy: tuple[float, float, list[float]],
    first: dict[str, Any],
    second: dict[str, Any],
    window: float = DIP_WINDOW_S,
) -> float | None:
    """How far the stem's short-time RMS falls at the join of `first` and
    `second` below its median over the two notes, in dB: the lowest frame
    within `window` of the join against the median frame from `first`'s
    onset to `second`'s end. `energy` is (time of frame 0's centre, hop,
    RMS per frame); None where the frames do not cover the join."""
    start, hop, rms = energy

    def frames(low: float, high: float) -> list[float]:
        first_frame = max(0, math.ceil((low - start) / hop))
        last_frame = min(len(rms) - 1, math.floor((high - start) / hop))
        return list(rms[first_frame : last_frame + 1]) if last_frame >= first_frame else []

    join = float(second["onset"])
    around = frames(join - window, join + window)
    level = frames(float(first["onset"]), _end(second))
    if not around or not level:
        return None
    floor = 1e-9
    return 20.0 * math.log10(max(statistics.median(level), floor) / max(min(around), floor))


def join_held(
    notes: list[dict[str, Any]],
    energy: tuple[float, float, list[float]] | None,
    max_dip_db: float = HELD_MAX_DIP_DB,
    other_onset: float = HELD_ONSET_S,
    touch: float = TOUCH_S,
) -> tuple[list[dict[str, Any]], list[float]]:
    """Rule 5b: a voice's two touching notes of one pitch are ONE held note
    where the other voice sounds across the join with no onset within
    `other_onset` of it, and the stem's energy (`energy_dip`) falls less
    than `max_dip_db` there. Notes in, notes out, the first of a joined
    pair lasting both; returns the notes and each join's time. No energy,
    or a `max_dip_db` of 0, joins nothing."""
    if energy is None or max_dip_db <= 0:
        return notes, []
    out: list[dict[str, Any]] = []
    joined: list[float] = []
    runs = _voice_runs(notes)
    for voice, run in runs.items():
        others = [n for v, other in runs.items() if v != voice for n in other]
        merged: list[dict[str, Any]] = []
        for note in run:
            previous = merged[-1] if merged else None
            at = float(note["onset"])
            if (
                previous is not None
                and int(previous["pitch"]) == int(note["pitch"])
                and _touching(previous, note, touch)
                and any(
                    float(o["onset"]) <= at - other_onset and _end(o) >= at + other_onset
                    for o in others
                )
                and not any(abs(float(o["onset"]) - at) <= other_onset for o in others)
            ):
                dip = energy_dip(energy, previous, note)
                if dip is not None and dip < max_dip_db:
                    previous["duration"] = _end(note) - float(previous["onset"])
                    previous["confidence"] = max(
                        float(previous["confidence"]), float(note["confidence"])
                    )
                    joined.append(at)
                    continue
            merged.append(dict(note))
        out.extend(merged)
    return out, sorted(joined)


def mark_lead_ins(
    notes: list[dict[str, Any]], max_s: float = LEAD_IN_MAX_S
) -> list[dict[str, Any]]:
    """Rule 6: in each voice, a note of at most `max_s` touching the next
    note of its voice, a semitone under it (a scoop) or at its pitch (a
    re-attack's head), when that note is `LEAD_IN_TARGET_RATIO` times as
    long, gets `lead_in`, and is made to touch it exactly --
    the fold (`quantize.absorb_lead_ins`) checks the two touch to 15 ms,
    and Basic Pitch's ends sit up to two frames short."""
    out: list[dict[str, Any]] = []
    for run in _voice_runs(notes).values():
        marked = [dict(n) for n in run]
        for note, after in zip(marked, marked[1:], strict=False):
            if (
                float(note["duration"]) <= max_s
                and int(after["pitch"]) - int(note["pitch"]) in (0, 1)
                and _touching(note, after)
                and float(after["duration"]) >= LEAD_IN_TARGET_RATIO * float(note["duration"])
            ):
                note["lead_in"] = True
                note["duration"] = float(after["onset"]) - float(note["onset"])
        out.extend(marked)
    return out


def assign(
    notes: list[dict[str, Any]],
    overlap_s: float = OVERLAP_S,
    share: float = OVERLAP_SHARE,
    ghost_ratio: float = GHOST_RATIO,
    track: tuple[float, float, list[float | None]] | None = None,
    attacks: list[float] = (),
    stats: dict[str, Any] | None = None,
    energy: tuple[float, float, list[float]] | None = None,
    held_dip_db: float = HELD_MAX_DIP_DB,
    held_onset_s: float = HELD_ONSET_S,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every rule: (the notes the two voices hold, each with a `voice`; the
    notes neither holds, each with `dropped` saying why).

    `track` and `attacks` are CREPE's frame trace and corroborated onsets
    for rule 5 (`rejoin_splits`), `energy` the stem's short-time RMS for
    rule 5b (`join_held`); without them nothing is joined. `stats`, when
    given, is filled with what each rule did (`held_at`: rule 5b's joins).

    Both lists are copies, in onset order (the higher pitch first at one
    onset). The dropped notes are what a listener may switch back on."""
    pairs = overlapping_pairs(notes)
    ghosted = ghosts(notes, ghost_ratio, pairs)
    alive = set(range(len(notes))) - ghosted
    work = [dict(n) for n in notes]
    tails = trim_tails(work, alive, overlap_s=overlap_s, share=share)
    links = legato_successors(work, alive)
    crowded = thirds(work, alive, overlap_s, share)
    alive -= crowded
    indices = sorted(alive)
    kept = [work[i] for i in indices]
    for note, voice in zip(kept, order(kept, overlap_s, share), strict=True):
        note["voice"] = voice
    continued = continue_voices(kept, indices, links, overlap_s, share)
    joined = rejoin_splits(kept, track, list(attacks))
    held, held_at = join_held(joined, energy, held_dip_db, held_onset_s)
    marked = mark_lead_ins(held)
    dropped = [
        {**notes[i], "dropped": GHOST if i in ghosted else THIRD} for i in sorted(ghosted | crowded)
    ]
    if stats is not None:
        stats.update(
            ghosts=len(ghosted),
            tails=tails,
            successors=len(links),
            continued=continued,
            thirds=len(crowded),
            rejoined=len(kept) - len(joined),
            held=len(held_at),
            held_at=held_at,
            lead_ins=sum(1 for n in marked if n.get("lead_in")),
        )

    def by_time(note: dict[str, Any]) -> tuple[float, int]:
        return (float(note["onset"]), -int(note["pitch"]))

    return sorted(marked, key=by_time), sorted(dropped, key=by_time)
