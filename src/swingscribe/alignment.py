"""Time-free comparison of two note sequences.

The hand transcriptions in `benchmark/` are notated scores: bars, beats and
note values, with no timestamps. Our output is seconds. Scoring one against
the other in time needs a tempo map, and the only tempo map we have comes
from our own beat tracker — so a beat-tracking error would be charged to the
transcriber, and vice versa. That is exactly the confound the plan warns
about, so the primary benchmark measure ignores time entirely and asks the
narrower question a musician would ask first: *did it get the notes, in
order?*

This is sequence alignment, not a MIR metric. mir_eval remains the source of
truth for everything time-based (see `metrics.py`); it has no time-free
note-sequence measure, which is why this exists. Keep it that way — do not
reimplement onset or frame scoring here.

Pure Python on purpose: no numpy, so tier-1 tests can exercise it in CI,
where the ml dependency group is not installed.
"""

from dataclasses import dataclass

# Needleman-Wunsch weights. A gap costs the same as a substitution so that
# "wrong note" and "missing note plus invented note" are not silently traded
# for one another — we want the alignment to prefer calling a near-miss a
# substitution only when it genuinely lines up.
MATCH = 1
MISMATCH = -1
GAP = -1

# How far to look for a constant transposition. Two octaves each way covers
# octave errors and the written-vs-concert offsets of transposing instruments
# (a Bb tenor part written in treble clef sounds 14 semitones lower).
TRANSPOSE_SEARCH = range(-24, 25)


@dataclass(frozen=True)
class Alignment:
    """The result of aligning an estimated pitch sequence to a reference.

    `pairs` is the full alignment path: (reference index, estimate index),
    with None on either side for a gap. It is kept so callers can look at
    *where* things went wrong, not just how often.
    """

    matches: int
    substitutions: int
    insertions: int  # notes we produced that the score does not have
    deletions: int  # notes in the score we never produced
    pairs: list[tuple[int | None, int | None]]

    @property
    def n_reference(self) -> int:
        return self.matches + self.substitutions + self.deletions

    @property
    def n_estimate(self) -> int:
        return self.matches + self.substitutions + self.insertions

    @property
    def precision(self) -> float:
        return self.matches / self.n_estimate if self.n_estimate else 0.0

    @property
    def recall(self) -> float:
        return self.matches / self.n_reference if self.n_reference else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def align(reference: list[int], estimate: list[int]) -> Alignment:
    """Global (Needleman-Wunsch) alignment of two pitch sequences.

    Global rather than local because both sequences are meant to cover the
    same span of music: a transcription that only matches the middle third
    should score badly, and local alignment would hide that.
    """
    n, m = len(reference), len(estimate)
    # score[i][j] = best score aligning reference[:i] against estimate[:j].
    score = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * GAP
    for j in range(1, m + 1):
        score[0][j] = j * GAP
    for i in range(1, n + 1):
        row, previous = score[i], score[i - 1]
        ref = reference[i - 1]
        for j in range(1, m + 1):
            diagonal = previous[j - 1] + (MATCH if ref == estimate[j - 1] else MISMATCH)
            row[j] = max(diagonal, previous[j] + GAP, row[j - 1] + GAP)

    pairs: list[tuple[int | None, int | None]] = []
    matches = substitutions = insertions = deletions = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            same = reference[i - 1] == estimate[j - 1]
            if score[i][j] == score[i - 1][j - 1] + (MATCH if same else MISMATCH):
                pairs.append((i - 1, j - 1))
                if same:
                    matches += 1
                else:
                    substitutions += 1
                i, j = i - 1, j - 1
                continue
        if i > 0 and score[i][j] == score[i - 1][j] + GAP:
            pairs.append((i - 1, None))
            deletions += 1
            i -= 1
            continue
        pairs.append((None, j - 1))
        insertions += 1
        j -= 1
    pairs.reverse()
    return Alignment(matches, substitutions, insertions, deletions, pairs)


def best_transposition(
    reference: list[int], estimate: list[int], search: range = TRANSPOSE_SEARCH
) -> tuple[int, Alignment]:
    """The constant semitone offset that best explains the estimate.

    Reported rather than assumed. A hand transcription may be written an
    octave from concert pitch for readability, and our own tracker makes
    octave errors — both look identical in a raw score, and only this tells
    them apart. A full alignment per candidate offset is slow but honest;
    a cheap histogram-of-intervals shortcut breaks on sequences with many
    repeated notes, which jazz solos have.
    """
    best_offset, best = 0, align(reference, estimate)
    for offset in search:
        if offset == 0:
            continue
        candidate = align(reference, [p + offset for p in estimate])
        if candidate.matches > best.matches:
            best_offset, best = offset, candidate
    return best_offset, best


def to_chroma(pitches: list[int]) -> list[int]:
    """Pitch classes. Scoring in chroma separates "wrong note" from "right
    note, wrong octave" — the second is a much smaller musical error and the
    two are indistinguishable in a single pitch-level number."""
    return [p % 12 for p in pitches]
