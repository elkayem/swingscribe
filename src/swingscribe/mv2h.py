"""Our page and a reference score in MV2H's text format (docs/mv2h.md).

MV2H (McLeod and Steedman, ISMIR 2018; github.com/apmcleod/MV2H, MIT, Java)
is the published joint measure for audio-to-score transcription: the mean of
five F-measures -- multi-pitch, voice, meter, note value and harmony. It is
the number the Rhythm Perceiver quotes for the Omnibook (0.92), so it is the
outside cross-check on our own edit cost (docs/roadmap.md E4). The Java tool
is a download outside the repo and never a dependency: this module only
WRITES its input and READS its output, and `scripts/mv2h_eval.py` runs it.

What goes in, and why each choice is MV2H's own rather than ours:

- **Both sides are scores**, rendered in score time at one fixed tempo
  (`MS_PER_QUARTER`, 120 bpm: what MuseScore and music21 assume for a file
  with no tempo marking, and so what MV2H's own MusicXML route,
  `evaluate_xml.bash`, would have rendered). A note's onset and its
  "value onset" are the same number, because a score has no performed time.
- **The meter is what MV2H's MIDI converter would read off the time
  signature** (`tools/midi/TimeSignature.getHierarchy`): beats per bar and
  two sub-beats per beat (three in compound metre), ONE tatum per sub-beat,
  so the tatums are eighth notes in x/4. It says nothing about the notes;
  the groupings MV2H compares are sub-beats, beats and bars.
- **Harmony is the key signature only**, as MV2H's MIDI converter reads it
  (major, tonic = 7 x fifths mod 12): neither side writes chord symbols
  here, and the MIDI route MV2H documents drops them anyway.
- **One voice.** Our line is monophonic and the reference is its `melody`,
  the top note of each simultaneity -- the same view every other measure of
  the page reads (`benchmark.score_against_notation`).
- **Our pitches are moved by the page's measured transposition**
  (`alignment.measured_transposition`, the offset `edit_cost` uses): a hand
  score written an octave from concert pitch is ordinary notation, not an
  error MV2H should charge a whole line for.

Nothing produced here may be committed: it is a note list derived from a
commercial recording. Only the aggregate numbers are.
"""

import re
from collections import Counter
from dataclasses import dataclass

# 120 bpm. MV2H's tolerances are in milliseconds (20 ms for a value and a
# grouping in its non-aligned mode, 50/100 ms in its aligned mode), so the
# tempo a score is rendered at decides how strict they are in beats: at 500
# ms a quarter, 20 ms is a twenty-fifth of a beat -- a written value has to
# be the same value, as a reader would read it.
MS_PER_QUARTER = 500


@dataclass(frozen=True)
class Bar:
    """One bar, in quarter notes from the side's own origin."""

    start: float
    length: float  # what the bar spans; an overfull OMR bar spans more than its signature
    numerator: int
    denominator: int


@dataclass(frozen=True)
class Side:
    """One side of the comparison: notes, bars and a key, in quarter notes."""

    notes: list[tuple[float, float, int]]  # (position, duration, pitch)
    bars: list[Bar]
    key_tonic: int | None  # 0 = C, major; None writes no key


def hierarchy(numerator: int, denominator: int) -> tuple[int, int, float]:
    """(beats per bar, sub-beats per beat, quarters per sub-beat) of a time
    signature, exactly as MV2H's MIDI converter reads one: compound when the
    numerator is a multiple of three above three (6/8 is two beats of three
    eighths), simple otherwise (3/4 is three beats of two eighths)."""
    if numerator > 3 and numerator % 3 == 0:
        return numerator // 3, 3, 4.0 / denominator
    return numerator, 2, 2.0 / denominator


def signature_of(length: float) -> tuple[int, int]:
    """A time signature for a bar known only by its length in quarters, as
    the score readers report one (`mscz.Score.beats_per_bar`): x/4 when the
    length is whole, x/8 when it is a whole number of eighths."""
    if abs(length - round(length)) < 1e-9:
        return int(round(length)), 4
    if abs(2 * length - round(2 * length)) < 1e-9:
        return int(round(2 * length)), 8
    return int(round(4 * length)), 16


def notation_side(notation, transpose: int = 0) -> Side:
    """Our page. Its notes exactly as every page measure reads them
    (`benchmark.notation_notes`: ties merged, rests dropped, a double-time
    page halved to true meter), moved by `transpose` semitones; its bars
    from its own time signatures; its key signature, moved with the notes."""
    from swingscribe.benchmark import bar_starts, notation_notes

    scale = 0.5 if getattr(notation, "double_time", False) else 1.0
    notes = [
        (position, duration, pitch + transpose)
        for position, duration, pitch in notation_notes(notation)
    ]
    bars = []
    for start, bar in zip(bar_starts(notation.bars), notation.bars, strict=True):
        numerator, denominator = bar.time_signature
        # A doubled bar at true meter is the same count of half-length beats.
        written = denominator if scale == 1.0 else denominator * 2
        bars.append(Bar(scale * start, scale * numerator * 4.0 / denominator, numerator, written))
    return Side(notes, bars, (7 * notation.key_fifths + transpose) % 12)


def score_side(score, page_bars: list | None = None) -> Side:
    """A reference score. Its `melody`; its bars where the score reader puts
    them -- `page_bars` (`evaluation.reader_bars`, for a MusicXML page, where
    an overfull bar moves everything after it) or else every
    `beats_per_bar` quarters from its first bar, which is where
    `mscz.parse` places them; its key signature."""
    notes = [(n.position, n.duration, n.pitch) for n in score.melody]
    if page_bars:
        bars = [Bar(b.start, max(b.filled, b.length), *signature_of(b.length)) for b in page_bars]
    else:
        length = float(score.beats_per_bar) or 4.0
        end = max([score.bars * length] + [p + d for p, d, _ in notes])
        count = max(1, int(-(-end // length)))
        numerator, denominator = signature_of(length)
        bars = [Bar(i * length, length, numerator, denominator) for i in range(count)]
    return Side(notes, bars, (7 * score.key_fifths) % 12)


def lines(side: Side, shift: float = 0.0, ms_per_quarter: float = MS_PER_QUARTER) -> list[str]:
    """`side` as MV2H's text format, every position moved by `shift` quarters.

    A Hierarchy where the signature changes and around a bar that does not
    span its signature (MV2H restarts its bar count at each Hierarchy, which
    is how an irregular bar is written in its format); a Tatum on every
    sub-beat of every bar and one closing the last bar; the key at the
    first bar. Times must come out non-negative: MV2H's grouping code uses
    -1 as "not started".
    """

    earliest_ms: list[int] = []

    def ms(position: float) -> int:
        time = int(round((position + shift) * ms_per_quarter))
        earliest_ms.append(time)
        return time

    out = []
    for position, duration, pitch in side.notes:
        on = ms(position)
        out.append(f"Note {pitch} {on} {on} {ms(position + duration)} 0")
    previous: tuple[int, int] | None = None
    irregular = False
    for bar in side.bars:
        beats, sub_beats, sub_length = hierarchy(bar.numerator, bar.denominator)
        regular = abs(beats * sub_beats * sub_length - bar.length) < 1e-9
        if (beats, sub_beats) != previous or not regular or irregular:
            out.append(f"Hierarchy {beats},{sub_beats} 1 a=0 {ms(bar.start)}")
        previous, irregular = (beats, sub_beats), not regular
        step = 0
        while step * sub_length < bar.length - 1e-9:
            out.append(f"Tatum {ms(bar.start + step * sub_length)}")
            step += 1
    if side.bars:
        last = side.bars[-1]
        out.append(f"Tatum {ms(last.start + last.length)}")
        if side.key_tonic is not None:
            # "Maj", as MV2H's own converter prints it (its reader takes either case).
            out.append(f"Key {side.key_tonic} Maj {ms(side.bars[0].start)}")
    if earliest_ms and min(earliest_ms) < 0:
        raise ValueError(
            f"MV2H needs non-negative times; shift {shift} leaves {min(earliest_ms)} ms"
        )
    return out


def earliest(side: Side) -> float:
    """The earliest position anything on `side` sits at, in quarters."""
    starts = [bar.start for bar in side.bars] + [position for position, _, _ in side.notes]
    return min(starts) if starts else 0.0


def grid_shift(
    ours: list[tuple[float, float, int]],
    theirs: list[tuple[float, float, int]],
    pairs: list[tuple[int | None, int | None]],
) -> tuple[float, float]:
    """(shift, share): the whole number of quarters that puts our page on the
    reference's clock, and the share of the pitch-matched notes it puts
    within a thirty-second of their place.

    The shift is the MODE of (their position - ours), rounded to a quarter,
    over the pairs the time-free aligner matched at one pitch -- a vote, not
    one note's word (CLAUDE.md: never take a downbeat from one point). Ties
    go to the smaller shift. Whole quarters, not whole bars: a page a beat
    off its bar lines is then shifted onto the right notes, and MV2H's
    meter sees its bar lines a beat off, which is where the fault is.
    """
    differences = [
        theirs[r][0] - ours[e][0]
        for r, e in pairs
        if r is not None and e is not None and theirs[r][2] == ours[e][2]
    ]
    if not differences:
        return 0.0, 0.0
    votes = Counter(round(d) for d in differences)
    top = max(votes.values())
    shift = float(min((v for v, n in votes.items() if n == top), key=lambda v: (abs(v), v)))
    near = sum(1 for d in differences if abs(d - shift) <= 0.125)
    return shift, near / len(differences)


FIELDS = {
    "Multi-pitch": "multi_pitch",
    "Voice": "voice",
    "Meter": "meter",
    "Value": "value",
    "Harmony": "harmony",
    "MV2H": "mv2h",
}

_PROGRESS = re.compile(r"Evaluating alignment (\d+) / (\d+)")
# What the alignment driver in scripts/mv2h_eval.py adds to MV2H's own lines.
DRIVER_FIELDS = {
    "Alignments": "alignments",
    "Evaluated": "evaluated",
    "Worst": "worst",
    "Most matches": "most_matches",
    "With most matches": "with_most_matches",
}


def with_keys_agreed(result: dict) -> float:
    """MV2H as it would read had our page written the reference's key
    signature: harmony 1, the other four components as measured.

    Harmony, with no chord symbols on either side, is the key signature alone
    (1 the same, 0.5 a fifth apart, 0 otherwise), and none of the other four
    reads the key. So this is arithmetic, not a second run. It exists because
    LORIA's Omnibook files write `<fifths>0</fifths>` on 21 of the 22 sides
    the benchmark holds (a B-flat blues and an A-flat Donna Lee among them),
    which makes the component a test of whether our page also wrote no key
    signature -- an encoding choice of the reference, not a transcription --
    and because the published 0.92 needs harmony near 1 (docs/mv2h.md)."""
    parts = ("multi_pitch", "voice", "meter", "value")
    return (sum(float(result[part]) for part in parts) + 1.0) / 5.0


def parse_output(text: str) -> dict[str, float | str]:
    """MV2H's printed result as numbers: the LAST value of each field (its
    non-aligned mode prints a progress line per candidate alignment, joined
    by carriage returns, then the best), plus `alignments`, how many
    co-optimal alignments there were, when it printed that -- and, from the
    alignment driver, `evaluated` and `how` ("all": every co-optimal
    alignment, each scored against a freshly read ground truth;
    "restricted" or "sampled": a lower bound on that; a "-shared" suffix:
    scored against one ground truth, as MV2H's own `-a` does, which is a
    check and never a reading), `worst`, and `best_from`, the subset the
    best alignment came from."""
    out: dict[str, float | str] = {}
    for line in re.split(r"[\r\n]+", text):
        name, _, value = line.partition(": ")
        name, value = name.strip(), value.strip()
        if name in FIELDS:
            out[FIELDS[name]] = float(value)
        elif name in DRIVER_FIELDS:
            number, _, how = value.partition(" ")
            out[DRIVER_FIELDS[name]] = float(number)
            if name == "Evaluated":
                out["how"] = how
        elif name == "Best from":
            out["best_from"] = value
    progress = _PROGRESS.findall(text)
    if progress and "alignments" not in out:
        out["alignments"] = float(progress[-1][1])
    missing = [key for key in FIELDS.values() if key not in out]
    if missing:
        raise ValueError(f"MV2H printed no {', '.join(missing)}")
    return out
