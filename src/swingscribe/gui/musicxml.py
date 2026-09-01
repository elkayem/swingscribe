"""Screen 4's Export button: the span you just reviewed, as a MusicXML file.

Thin, like the rest of gui/. It gathers things the GUI already has -- the
cached beat grid, the meter you set by ear, the reviewed notes minus the ones
you silenced -- and hands them to `swingscribe.notation`, which is where the
stages actually run. Nothing here decides anything musical.

## Why it does not go through pipeline.run

The notes on screen are not the pipeline's notes. They come from the review
cache (gui/review.py) with the listener's ERASURES applied, and erasures are a
judgement about the music that the pipeline knows nothing about and must not
(gui/erasures.py). Exporting the pipeline's version would hand you a score
still containing every note you had just finished cutting.

## Why it is not a job

Everything below `transcribe` is pure arithmetic over a note list -- no torch,
no audio decode, no model. A hundred bars is milliseconds, so it answers in the
request like /beats does, and the button has no progress bar to get wrong.

## Where the file goes

Beside the audio, like `ab`, `audition` and `click` before it -- never in the
cache. You are going to open this in MuseScore, and a file you have to dig out
of a cache directory is a file you will not open. The span is in the name, so
exporting a second chorus does not overwrite the first.
"""

from pathlib import Path
from typing import Any

from swingscribe.config import TRANSPOSITIONS, Config
from swingscribe.model import Document, NoteEvent
from swingscribe.notation import meter_from_settings, notation_for_span


class NotReady(Exception):
    """A precondition the user can fix -- and the message says how."""


def export_path(audio_path: str | Path, region: tuple[float, float | None] | None) -> Path:
    """Where this span's score goes: beside the audio, span in the name.

    A whole-track export keeps the bare name; anything narrower carries its
    bounds, so the four choruses you exported one at a time are four files
    rather than one file overwritten four times.
    """
    source = Path(audio_path)
    if region is None or (region[0] in (None, 0.0) and region[1] is None):
        return source.with_suffix(".musicxml")
    low = region[0] or 0.0
    high = region[1]
    span = f"{low:.0f}-{high:.0f}s" if high is not None else f"from{low:.0f}s"
    return source.with_name(f"{source.stem}.{span}.musicxml")


def beat_times(audio_path: str | Path, config: Config) -> list[float]:
    """The tracked beats for this track, or raise if they are not cached.

    Never tracks them: this endpoint must stay as cheap as the review it sits
    beside, and the Beats button already exists to do the work.

    Takes the path rather than reading `document.audio_path`, which is the
    same fact the caller already holds. The Document's copy is restored from
    whatever the cache stored (pipeline._for_path); the path passed in is the
    file the request is actually about, and re-deriving a cache key from
    anything else looks up a different track.
    """
    from swingscribe import pipeline
    from swingscribe.stages import beats, ingest

    cached = pipeline.cached_document(
        audio_path,
        config,
        stages=[("ingest", ingest.run), ("beats", beats.run)],
    )
    grid = cached.beat_grid if cached else None
    if grid is None or not grid.beats:
        raise NotReady("no beat grid yet - press Beats first")
    return list(grid.beats)


def notate_config(config: Config, settings: dict[str, Any], title: str) -> Config:
    """Base config with the part's key and title folded into notate.

    The transposition is a property of the instrument, not of the audio
    (NotateConfig), so it can only ever come from the person listening. An
    unrecognised value falls back to concert rather than raising: a hand-edited
    sidecar should not be able to break the button.
    """
    stored = settings.get("transposition")
    transposition = stored if stored in TRANSPOSITIONS else config.notate.transposition
    return config.model_copy(
        update={
            "notate": config.notate.model_copy(
                update={"transposition": transposition, "title": title}
            )
        }
    )


def build_notation(
    document: Document,
    config: Config,
    run_config: Config,
    audio_path: str,
    notes: list[dict[str, Any]],
    settings: dict[str, Any],
    second_voice: list[dict[str, Any]] | None = None,
):
    """The reviewed span as a Notation, or raise something the user can fix.

    `run_config` is the review's config -- it carries the span and the lead
    stem, and is what the notes were produced under. `notes` is already the
    AUDIBLE list: erasures were resolved by the caller, through the one module
    allowed to resolve them.

    Shared by the Export button and the Score button so they cannot disagree
    about what was notated: scoring a different Notation from the one on disk
    would be a number about nothing.

    `second_voice` is the piano review overlay and is passed by EXPORT ONLY.
    The Score button must never see it: it compares our line against a hand
    transcription's single melody, and a second voice on the page would be
    scored as a page full of notes the human did not write.
    """
    if not notes:
        raise NotReady("nothing to notate - every note in this span is silenced")

    beats = beat_times(audio_path, config)
    region = run_config.transcribe.region or (0.0, None)
    stem = run_config.transcribe.stem
    signature, pulses = meter_from_settings(
        settings.get("time_signature"), settings.get("pulses_per_bar"), config
    )
    notation = notation_for_span(
        audio_path,
        [NoteEvent(source=stem, **note) for note in notes],
        beats,
        region,
        stem=stem,
        config=notate_config(config, settings, Path(audio_path).stem),
        anchor=settings.get("anchor"),
        time_signature=signature,
        pulses_per_bar=pulses,
        sample_rate=document.sample_rate,
        second_voice=(
            [NoteEvent(source=stem, **note) for note in second_voice] if second_voice else None
        ),
        # The listener's double-time checkbox: a per-track judgement like the
        # time signature, stored in the sidecar, never inferred (the Omnibook
        # writes these solos as literal 32nds, which stays the default).
        double_time=bool(settings.get("double_time")),
    )
    if notation is None or not notation.bars:
        raise NotReady("the span is too short to bar out - select at least a couple of bars")
    return notation


def export_span(
    document: Document,
    config: Config,
    run_config: Config,
    audio_path: str,
    notes: list[dict[str, Any]],
    settings: dict[str, Any],
    second_voice: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write the reviewed span to MusicXML and say what was written."""
    from swingscribe.benchmark import readability
    from swingscribe.stages.export import to_musicxml

    notation = build_notation(
        document, config, run_config, audio_path, notes, settings, second_voice
    )
    region = run_config.transcribe.region or (0.0, None)
    title = Path(audio_path).stem
    signature = notation.bars[0].time_signature
    path = export_path(audio_path, region)
    xml = to_musicxml(notation, part_name=title)
    try:
        path.write_text(xml, encoding="utf-8")
    except OSError as exc:
        raise NotReady(f"could not write beside the audio: {exc}") from exc

    # Reference-free, a property of the page just written (benchmark.py):
    # reported with the export because this is the moment the page exists.
    readable = readability(notation)
    return {
        "path": str(path),
        "name": path.name,
        "bars": len(notation.bars),
        "notes": sum(1 for bar in notation.bars for n in bar.notes if not n.is_rest),
        "key_fifths": notation.key_fifths,
        "swing": notation.swing,
        "transpose": notation.transpose,
        "time_signature": f"{signature[0]}/{signature[1]}",
        "readability": readable["readability"],
        "tie_rate": readable["tie_rate"],
        "short_rests": readable["short_rests"],
        "short_values": readable["short_values"],
    }


def score_span(
    document: Document,
    config: Config,
    run_config: Config,
    audio_path: str,
    notes: list[dict[str, Any]],
    settings: dict[str, Any],
    score_path: Path,
) -> dict[str, Any]:
    """Score the span's notation against a hand transcription, as notation.

    A DIFFERENT QUESTION from the F1 already on the ground-truth bar, and the
    difference is the most expensive confusion in this project (CLAUDE.md).
    That one is time-free and pitch-only: did we hear the right notes? This
    one asks whether the notes we did get are written the way a human wrote
    them -- the gap to the next note, and the note value. It is the measure of
    what the Export button just produced, and until now it existed only in
    `scripts/run_eval.py`.

    It reads lower than the pitch F1 and always will, because it charges the
    gap between performed timing and notated rhythm. Read as transcription
    accuracy it is simply the wrong number.
    """
    from swingscribe import mscz
    from swingscribe.benchmark import score_against_notation

    notation = build_notation(document, config, run_config, audio_path, notes, settings)
    try:
        reference = mscz.parse_any(score_path)
    except Exception as exc:
        raise NotReady(f"could not read {score_path.name}: {exc}") from exc

    result = score_against_notation(notation, reference)
    if not result["n_matched"]:
        raise NotReady(
            f"no note in {score_path.name} lined up with ours - is this the score for this span?"
        )
    # `trusted` travels WITH the numbers rather than replacing them. Low
    # coverage means either the wrong score or a bad transcription, and the
    # second is a real result worth seeing — but rhythm alone cannot tell the
    # two apart, so it must never be shown without this (benchmark.py).
    return {
        "score": score_path.name,
        "rhythm": round(result["rhythm"], 3),
        "value": round(result["value"], 3),
        "matched": int(result["n_matched"]),
        "reference": int(result["reference"]),
        "coverage": round(result["coverage"], 3),
        "trusted": bool(result["trusted"]),
        "transposition": int(result["transposition"]),
        "bars": len(notation.bars),
        "reference_bars": reference.bars,
    }
