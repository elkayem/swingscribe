"""Notes + a beat grid -> a Notation, with no audio and no cache.

The last four stages of the pipeline (meter, swing, quantize, notate) are pure
arithmetic over a note list and a list of beat times. Two callers need exactly
that, and neither can reach it through `pipeline.run`:

- the eval harness, which scores cached notes against hand transcriptions and
  has no reason to re-run CREPE to do it;
- the GUI's Export button, whose notes are the reviewed ones with the
  listener's ERASURES applied -- a judgement about the music that the pipeline
  knows nothing about and must not (gui/erasures.py).

Both used to assemble the Document themselves. That is the shape of duplication
that has already cost this project twice in the scoring harness (CLAUDE.md), so
it lives here, in the package, with tests.

## Bar 1 is the first bar of the span

The beat grid is trimmed to the span before anything else runs, so an excerpt's
bars are numbered from 1 the way a solo transcription is -- not from wherever
the soloist happens to enter in the tune. `anchor` is what keeps that bar 1 on
a real downbeat: it is a phase, not an origin (model.MeterSection), so a span
starting mid-bar still lands its bar lines correctly.

This deliberately does not call `stages/meter.py`. Meter derivation exists to
find where a steady pulse starts and stops across a whole track, and to repair
and extrapolate around the tracker's gaps; over a span the user has already
selected by ear, with a downbeat they have already placed by hand, there is
nothing left for it to decide.
"""

from swingscribe.config import Config
from swingscribe.model import BeatGrid, Document, MeterSection, Notation, NoteEvent
from swingscribe.stages import meter

# Seconds of beat grid either side of the span. A note at the very edge of
# the selection still needs the beat after it to be placed against.
MARGIN_SECONDS = 2.0

# Below this a span cannot support a bar grid at all -- two bars of 4/4.
MIN_BEATS = 8


def span_beats(
    beats: list[float], region: tuple[float, float | None], margin: float = MARGIN_SECONDS
) -> list[float]:
    """The beat times inside the span, with a little air either side."""
    low = region[0] or 0.0
    high = beats[-1] if (region[1] is None and beats) else region[1]
    if high is None:
        return []
    return [b for b in beats if low - margin <= b <= high + margin]


def section_for(
    beats: list[float],
    anchor: float | None,
    time_signature: tuple[int, int],
    pulses_per_bar: int,
) -> MeterSection:
    """One constant-meter section covering the whole span.

    `origin="user"` because every value in it came from a person: they drew the
    span, they set the downbeat, they chose the time signature.
    """
    return MeterSection(
        start=beats[0],
        end=beats[-1],
        pulses_per_bar=pulses_per_bar,
        time_signature=time_signature,
        anchor=beats[0] if anchor is None else anchor,
        first_bar=1,
        origin="user",
    )


def meter_from_settings(
    time_signature: str | None, pulses_per_bar: int | None, config: Config
) -> tuple[tuple[int, int], int]:
    """(signature, pulses) from what the GUI remembered, via the meter stage.

    Routed through `meter.resolve_meter` rather than parsed here so that "6/8"
    counted in two means the same thing on the page as it does on the bar grid.
    """
    overrides = {
        key: value
        for key, value in {
            "time_signature": time_signature,
            "pulses_per_bar": pulses_per_bar,
        }.items()
        if value is not None
    }
    return meter.resolve_meter(config.meter.model_copy(update=overrides))


def notation_for_span(
    audio_path: str,
    notes: list[NoteEvent],
    beats: list[float],
    region: tuple[float, float | None],
    *,
    stem: str,
    config: Config | None = None,
    anchor: float | None = None,
    time_signature: tuple[int, int] = (4, 4),
    pulses_per_bar: int = 4,
    sample_rate: int = 44100,
) -> Notation | None:
    """Run swing, quantize and notate over one span. None if it is too short.

    `config` supplies the notate settings that are genuinely choices -- the
    part's transposition, the title, legato fill -- while the stem is forced
    onto all three stages so a caller cannot half-set it.
    """
    from swingscribe.stages import notate, quantize, swing

    kept = span_beats(beats, region)
    if len(kept) < MIN_BEATS:
        return None

    base = config or Config()
    run_config = base.model_copy(
        update={
            "swing": base.swing.model_copy(update={"stem": stem}),
            "quantize": base.quantize.model_copy(update={"stem": stem}),
            "notate": base.notate.model_copy(update={"stem": stem}),
        }
    )
    document = Document(
        audio_path=audio_path,
        sample_rate=sample_rate,
        beat_grid=BeatGrid(beats=kept, downbeats=[], beats_per_bar=pulses_per_bar),
        meter=[section_for(kept, anchor, time_signature, pulses_per_bar)],
        notes={stem: list(notes)},
    )
    for stage in (swing.run, quantize.run, notate.run):
        document = stage(document, run_config)
    return document.notation
