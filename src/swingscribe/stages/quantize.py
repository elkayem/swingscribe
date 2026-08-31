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

Pure arithmetic, no heavy imports — the whole stage runs in CI.
"""

import bisect
import statistics

from swingscribe.config import Config
from swingscribe.model import Document, MeterSection, QuantizedNote, SwingSpan

# Bump when this stage's behavior changes without a config change (see
# pipeline._cache_name).
CACHE_VERSION = 1

STRAIGHT_PHASE = 0.5

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


def choose_grid(
    offsets: list[float],
    candidates: tuple[int, ...],
    min_onsets_for_tuplet: int = 3,
    slack: float = 0.05,
) -> int:
    """Pick the subdivision that the notes in one beat actually fit.

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
    """
    if not offsets:
        return candidates[0]
    allowed = [
        divisions
        for divisions in candidates
        if divisions % 3 != 0 or len(offsets) >= min_onsets_for_tuplet
    ]
    if not allowed:
        allowed = [candidates[0]]
    errors = {
        divisions: sum(abs(snap(offset, divisions)[1]) for offset in offsets) / len(offsets)
        for divisions in allowed
    }
    best_error = min(errors.values())
    # A grid that cannot keep two onsets apart is too coarse for this beat,
    # whatever its snap error says. Two notes on one grid position are one
    # note in a single-line score — the other is simply lost — so this is a
    # hard constraint and not a preference. Without it, buying notated rhythm
    # by coarsening the grid quietly costs notes: 4.8% of All The Things
    # disappeared before this rule existed.
    separating = [d for d in allowed if _keeps_apart(offsets, d)] or allowed
    # Coarsest first: a smaller number of divisions is a coarser grid.
    for divisions in sorted(separating):
        if errors[divisions] <= best_error + slack + 1e-12:
            return divisions
    return min(separating, key=lambda d: errors[d])


def _keeps_apart(offsets: list[float], divisions: int) -> bool:
    """Do all these onsets still land on different grid positions?"""
    snapped = {round(snap(offset, divisions)[0], 9) for offset in offsets}
    return len(snapped) == len(offsets)


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
        bar = section.first_bar + offset // pulses
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
) -> tuple[list[QuantizedNote], list[float]]:
    """Warp, snap, and place notes in bars. See the module docstring.

    Returns (notes, snapped positions in absolute beats). The positions are
    what `replay_onsets` needs and what the Document does not keep: bar plus
    beat-within-bar is the notation, and reconstructing absolute time from it
    would fail for anything outside a meter section — a pickup, a rubato
    intro — which is exactly where a round-trip check matters most.
    """
    if len(beats) < 2:
        return [], []
    by_beat, _track = pooled_phase(spans, straight_bur_ceiling)
    finest = max(1, resolution // 4)  # grid steps per beat at full resolution
    # Coarse to fine. An eighth-note grid is offered first so a beat holding
    # only an eighth pair is not forced onto a sixteenth grid it cannot
    # justify; `slack` decides how much better a finer grid has to be.
    coarse = [d for d in (2, finest) if d <= finest]
    candidates = tuple(dict.fromkeys(coarse + ([3] if allow_triplets else [])))

    # Warp first, then group by beat so the grid choice sees the whole beat.
    warped: list[tuple[int, float, float, int]] = []  # (index, position, duration, pitch)
    for onset, duration, pitch in zip(onsets, durations, pitches, strict=True):
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
        warped.append((index, warped_start, max(0.0, warped_end - warped_start), pitch))

    per_beat: dict[int, list[float]] = {}
    for index, position, _duration, _pitch in warped:
        per_beat.setdefault(index, []).append(position - index)
    # The slack is a time budget (config.py: it absorbs a player's motor
    # scatter, which is milliseconds, not beat fractions), so each beat
    # converts it at its own length. A long ballad beat gets a small slack
    # in beats and fine grids stay reachable; a burner's beat gets a large
    # one and the coarse reading wins — which is the direction the 456-solo
    # tempo staircase says humans notate (D11).
    grids = {
        index: choose_grid(
            offsets, candidates, min_onsets_for_tuplet, grid_slack_s / _beat_length(beats, index)
        )
        for index, offsets in per_beat.items()
    }

    out, positions = [], []
    for index, position, duration, pitch in warped:
        grid = grids.get(index, finest)
        snapped, residual = snap(position, grid)
        length, _ = snap(duration, grid)
        bar, beat = bar_and_beat(snapped, beats, sections)
        positions.append(snapped)
        out.append(
            QuantizedNote(
                bar=bar,
                beat=beat,
                duration_beats=max(1.0 / grid, length),
                pitch=pitch,
                # In beats, not seconds: a residual only means anything
                # relative to the pulse it deviates from.
                timing_residual=residual,
            )
        )
    return out, positions


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

    quantized, _positions = quantize_notes(
        [n.onset for n in notes],
        [n.duration for n in notes],
        [n.pitch for n in notes],
        grid.beats,
        document.swing,
        document.meter,
        resolution=qc.resolution,
        straight_bur_ceiling=qc.straight_bur_ceiling,
        allow_triplets=qc.allow_triplets,
        min_onsets_for_tuplet=qc.min_onsets_for_tuplet,
        grid_slack_s=qc.grid_slack_s,
    )

    by_beat, track = pooled_phase(document.swing, qc.straight_bur_ceiling)
    if quantized:
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
