"""Melodic-line selection: one line out of everything the piano model heard.

The polyphonic piano model hears virtually every note a pianist plays — its
top two per onset cluster contain the note a human notated 93-96% of the
time — and CREPE, which hears one pitch at a time, is the thing choosing
among them today. Picking is the whole piano gap (open-issue #8,
docs/issue8-line-selection.md), and the picker that closed most of it is a
small Viterbi over the model's own output:

- **emission** is the note's velocity as a WITHIN-TRACK percentile rank.
  Absolute MIDI velocities do not transfer between recordings (the model's
  loudness scale rides the mix), and normalising them was the single biggest
  finding: after it, every sequence variant beat the shipped line's mean.
- **transition** is a register-continuity cost per semitone from the last
  EMITTED note, capped at an octave, because a phrase-start leap is
  legitimate and should not be priced like a walk across the keyboard.
- **skip** is a first-class outcome: emitting must beat silence by a
  margin, so a quiet left-hand comp between phrases emits nothing. A forced
  one-note-per-cluster line gets dragged through the comping.

Measured over the ten piano spans with references: mean pitch F1 0.8655
against the shipped line's 0.8017, better or equal on 9 of 10, wrong-pitch
notes 344 -> 199. Two weights, both with physical readings: a semitone of
leap costs about two percentile points of loudness, and a note must beat
silence by ten.

Pure Python over plain note dicts, so it runs in CI. `scripts/line_selection.py`
is the measurement instrument that arrived at these numbers and imports from
here, so the experiment and the shipped picker cannot drift apart.
"""

import bisect
from typing import Any

# Two oracle notes struck within this of each other are one simultaneity.
# Tighter than corroborate.ONSET_TOLERANCE on purpose: this groups ONE
# detector's own output, where a chord really is simultaneous.
CLUSTER_GAP_S = 0.05

# A leap wider than an octave costs no more than an octave. Phrase starts
# leap; pricing them linearly made the picker cling to the last register.
LEAP_CAP = 12.0

# Continuity cost per semitone, in velocity-rank units (0-1).
CONTINUITY = 0.02

# How much a note's rank must exceed silence before it is emitted.
SKIP_MARGIN = 0.10

# States carried between clusters. Eight was enough on every track measured;
# the exact Viterbi is quadratic in cluster size for no measured gain.
BEAM = 8


def normalize_velocities(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Velocity as a within-track percentile rank in [0, 1].

    Ties rank at the lowest position of the tied value, so a run of equal
    velocities does not manufacture a spread that is not there.
    """
    ordered = sorted(float(n["velocity"]) for n in notes)
    span = max(1, len(ordered) - 1)
    out = []
    for n in notes:
        rank = bisect.bisect_left(ordered, float(n["velocity"])) / span
        out.append({**n, "velocity": min(1.0, rank)})
    return out


def clusters_of(
    notes: list[dict[str, Any]], gap_s: float = CLUSTER_GAP_S
) -> list[list[dict[str, Any]]]:
    """Notes grouped by onset: a new cluster starts wherever the gap from the
    cluster's FIRST onset exceeds `gap_s`, so a rolled chord stays one."""
    ordered = sorted(notes, key=lambda n: float(n["onset"]))
    out: list[list[dict[str, Any]]] = []
    for note in ordered:
        if out and float(note["onset"]) - float(out[-1][0]["onset"]) <= gap_s:
            out[-1].append(note)
        else:
            out.append([note])
    return out


def pick_from_clusters(
    clusters: list[list[dict[str, Any]]],
    continuity: float = CONTINUITY,
    skip_margin: float = SKIP_MARGIN,
    beam: int = BEAM,
) -> list[dict[str, Any]]:
    """At most one note per cluster, chosen as a SEQUENCE.

    Velocities must already be normalised (see `normalize_velocities`); the
    emission is `velocity - skip_margin`, so a note ranked under the margin
    can only be emitted when continuity from the previous note pays for it.
    """
    if not clusters:
        return []
    # A state is (cluster index, note index) of the last emitted note, or
    # None before anything has been emitted. Each layer maps a state to
    # (best score, previous state); a skip carries the state through and an
    # emission is a layer where the backtracked state changes.
    layers: list[dict] = [{None: (0.0, None)}]
    for k, cluster in enumerate(clusters):
        previous = layers[-1]
        layer: dict = {}
        for state, (score, _prev) in previous.items():
            keep = layer.get(state)
            if keep is None or score > keep[0]:
                layer[state] = (score, state)
        for i, note in enumerate(cluster):
            emit = float(note["velocity"]) - skip_margin
            best_score, best_prev = None, None
            for state, (score, _prev) in previous.items():
                if state is None:
                    candidate = score + emit
                else:
                    pk, pi = state
                    leap = abs(int(note["pitch"]) - int(clusters[pk][pi]["pitch"]))
                    candidate = score + emit - continuity * min(leap, LEAP_CAP)
                if best_score is None or candidate > best_score:
                    best_score, best_prev = candidate, state
            layer[(k, i)] = (best_score, best_prev)
        layers.append(dict(sorted(layer.items(), key=lambda kv: -kv[1][0])[:beam]))
    state = max(layers[-1], key=lambda s: layers[-1][s][0])
    picks = []
    for level in range(len(layers) - 1, 0, -1):
        _score, prev = layers[level][state]
        if state is not None and state != prev:
            k, i = state
            picks.append(clusters[k][i])
        state = prev
    picks.reverse()
    return picks


def pick_line(
    oracle: list[dict[str, Any]],
    continuity: float = CONTINUITY,
    skip_margin: float = SKIP_MARGIN,
    gap_s: float = CLUSTER_GAP_S,
) -> list[dict[str, Any]]:
    """The melody chosen from the piano model's full output.

    Returns note dicts with `onset`, `duration`, `pitch` and `confidence` —
    the model's own onset and duration, and the velocity RANK as the
    confidence, so the review screen shades a picked note by how loud it was
    within this performance, the same cue the picker used.
    """
    if not oracle:
        return []
    ranked = normalize_velocities(oracle)
    picks = pick_from_clusters(clusters_of(ranked, gap_s), continuity, skip_margin)
    return [
        {
            "onset": float(n["onset"]),
            "duration": float(n["duration"]),
            "pitch": int(n["pitch"]),
            "confidence": round(float(n["velocity"]), 4),
        }
        for n in picks
    ]
