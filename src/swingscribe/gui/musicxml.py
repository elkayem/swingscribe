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

## Chord symbols

The sidecar's `changes` is one chorus of chord symbols the listener typed
(chords.py). Export and the page view lay it over the page; the Score button
never sees it, because a chord symbol is not a note and the hand scores are
compared note for note. A chart that does not parse, or whose length is not
the Chorus length the listener set, is REPORTED (`changes.error`) and the
page is written without symbols rather than refused: the notes are the page,
and a typo in the changes must not cost the listener their export.
"""

from pathlib import Path
from typing import Any

from swingscribe import chords
from swingscribe.config import KEY_SIGNATURES, TRANSPOSITIONS, Config
from swingscribe.model import BeatGrid, Document, Notation, NoteEvent
from swingscribe.notation import (
    bar_grid_for_settings,
    fold_texture,
    form_bar_of_page,
    grid_config,
    meter_from_settings,
    notation_for_horns,
    notation_for_span,
    reading_of,
    timing_for,
    with_chords,
)


class NotReady(Exception):
    """A precondition the user can fix -- and the message says how."""


def export_path(
    audio_path: str | Path,
    region: tuple[float, float | None] | None,
    line: str | None = None,
    tags: list[str] | None = None,
) -> Path:
    """Where this span's score goes: beside the audio, span in the name.

    A whole-track export keeps the bare name; anything narrower carries its
    bounds, so the four choruses you exported one at a time are four files
    rather than one file overwritten four times. `line` is a take other than
    the default (the pianists' Line picker): it goes in the name for the same
    reason, so the two takes of one span can be laid side by side. `tags`
    are the page choices away from their defaults (`page_tags`), for the same
    reason again: a literal page must not overwrite the swing one.
    """
    source = Path(audio_path)
    take = "".join(f".{part}" for part in [line, *(tags or [])] if part)
    if region is None or (region[0] in (None, 0.0) and region[1] is None):
        return source.with_name(f"{source.stem}{take}.musicxml")
    low = region[0] or 0.0
    high = region[1]
    span = f"{low:.0f}-{high:.0f}s" if high is not None else f"from{low:.0f}s"
    return source.with_name(f"{source.stem}.{span}{take}.musicxml")


def take_of(config: Config, line: str | None) -> str | None:
    """The line as it appears in a filename: None for the default take."""
    return line if line and line != config.transcribe.piano_line else None


def timing_of(config: Config, settings: dict[str, Any]) -> str:
    """The sidecar's rhythm choice, or the ensemble's or the config's when
    it holds none (or one this build does not know -- a hand-edited sidecar
    must not break the button): `notation.timing_for`, the one rule the
    harness reads too. A multi-horn head is literal unless chosen swing."""
    return timing_for(settings, config)


def key_of(settings: dict[str, Any]) -> int | None:
    """The listener's key signature in fifths, or None to detect it. A value
    this build does not offer is detection, not an error."""
    stored = settings.get("key")
    return stored if isinstance(stored, int) and stored in KEY_SIGNATURES else None


def two_staves(settings: dict[str, Any], texture: bool) -> bool:
    """A grand staff: only ever for the All-notes view of a pianist."""
    return texture and settings.get("staves") == 2


def page_tags(config: Config, settings: dict[str, Any], texture: bool) -> list[str]:
    """The filename tags for this page's choices away from their defaults:
    "all" or "2staves" for a piano texture, "literal16"/"literal32", and a
    literal page's "lag" and "thirds" readings."""
    tags = []
    if texture:
        tags.append("2staves" if two_staves(settings, texture) else "all")
    reading = reading_of(settings, config)
    if reading["timing"] != "swing":
        tags.append(reading["timing"].replace("-", ""))
        tags.extend(name for name in ("lag", "thirds") if reading[f"literal_{name}"])
    return tags


def cached_grid(
    audio_path: str | Path, config: Config, settings: dict[str, Any] | None = None
) -> BeatGrid:
    """The tracked beat grid, from the cache only; NotReady if the Beats
    button has not been pressed. See `bar_grid` for why it never tracks.
    `settings` choose WHICH grid: the listener's Fast tune reads the one
    tracked at half speed (`notation.grid_config`)."""
    from swingscribe import pipeline
    from swingscribe.stages import beats, ingest

    cached = pipeline.cached_document(
        audio_path,
        grid_config(config, settings or {}),
        stages=[("ingest", ingest.run), ("beats", beats.run)],
    )
    grid = cached.beat_grid if cached else None
    if grid is None or not grid.beats:
        if (settings or {}).get("fast_tempo"):
            raise NotReady("no fast-tune beat grid yet - press Beats first")
        raise NotReady("no beat grid yet - press Beats first")
    return grid


def bar_grid(
    audio_path: str | Path,
    config: Config,
    settings: dict[str, Any],
    duration: float,
    near: tuple[float, float] | None = None,
    grid: BeatGrid | None = None,
) -> tuple[list[float], float | None]:
    """The beat grid AS THE ROLL DRAWS IT, and the beat it counts bars from.

    Never tracks beats: this endpoint must stay as cheap as the review it sits
    beside, and the Beats button already exists to do the work. Raises if the
    grid is not cached.

    The grid and the anchor come from `meter.bar_grid` with the same settings
    the `/beats` endpoint applies -- the listener's time signature and
    downbeat if they set them, the downbeat layer's best phase if they did
    not. That is the whole point: the bar lines on the page have to be the
    bar lines on the screen, and the one time export derived its own it put
    every bar of Soul Station a beat off the roll.

    Takes the path rather than reading `document.audio_path`, which is the
    same fact the caller already holds. The Document's copy is restored from
    whatever the cache stored (pipeline._for_path); the path passed in is the
    file the request is actually about, and re-deriving a cache key from
    anything else looks up a different track.

    `grid` is the tracked grid when the caller already read it (the page
    needs it again for the chord chart): reading it costs a hash of the
    whole audio file, so it is read once.
    """
    if grid is None:
        grid = cached_grid(audio_path, config, settings)
    # One derivation, shared with the eval harness (notation.py): the
    # listener's meter settings over the repaired grid, and with no downbeat
    # set, the automatic one voted around `near` -- the span on the page.
    return bar_grid_for_settings(grid.beats, grid.downbeats, settings, config, duration, near)


def notate_config(
    config: Config, settings: dict[str, Any], title: str, texture: bool = False
) -> Config:
    """Base config with the part's key and title folded into notate, and
    the listener's rhythm choice into quantize.

    The transposition is a property of the instrument, not of the audio
    (NotateConfig), so it can only ever come from the person listening. An
    unrecognised value falls back to concert rather than raising: a hand-edited
    sidecar should not be able to break the button. The timing is the same
    kind of choice -- swing eighths or a literal grid -- and so is the key
    signature; `texture` says the notes are a piano texture, whose
    collisions are chords.
    """
    stored = settings.get("transposition")
    transposition = stored if stored in TRANSPOSITIONS else config.notate.transposition
    return config.model_copy(
        update={
            "notate": config.notate.model_copy(
                update={"transposition": transposition, "title": title, "key": key_of(settings)}
            ),
            "quantize": config.quantize.model_copy(
                update={**reading_of(settings, config), "polyphonic": texture}
            ),
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
    added: list[dict[str, Any]] | None = None,
    texture: bool = False,
    left: list[dict[str, Any]] | None = None,
    grid: BeatGrid | None = None,
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

    `added` is the listener's enabled candidates (gui/erasures.py): folded
    into the line through `notation.with_chords`, so one struck with a line
    note is written as a chord on it and one struck alone is a note of its
    own. Passed by Export AND Score: unlike the overlay they are the
    listener's claim about the solo, and the page is scored as written.

    `texture` is a pianist's "All notes" view: `notes` are everything the
    piano model heard, folded into chords (`notation.fold_texture`) and
    quantized as a texture. With `left` given as well the page is a grand
    staff, `notes` the right hand and `left` the left.

    `grid` is the cached tracked grid if the caller has read it already.

    A multi-horn head (the review's ensemble) is written as two horns on
    one staff (`notation.notation_for_horns`): `notes` and `added` each
    carry the voice they are written in (gui/edits.py).
    """
    if not notes and not added and not left:
        raise NotReady("nothing to notate - every note in this span is silenced")

    duration = document.audio.duration if document.audio else 0.0
    region = run_config.transcribe.region or (0.0, None)
    near = (float(region[0]), float(duration if region[1] is None else region[1]))
    beats, anchor = bar_grid(audio_path, config, settings, duration, near, grid)
    stem = run_config.transcribe.stem
    signature, pulses = meter_from_settings(
        settings.get("time_signature"), settings.get("pulses_per_bar"), config
    )
    line = [NoteEvent(source=stem, **note) for note in notes]
    common = {
        "stem": stem,
        "config": notate_config(config, settings, Path(audio_path).stem, texture),
        "anchor": anchor,
        "time_signature": signature,
        "pulses_per_bar": pulses,
        "sample_rate": document.sample_rate,
        "double_time": bool(settings.get("double_time")),
    }
    if run_config.transcribe.uses_multi_horn:
        heard = line + [NoteEvent(source=f"{stem}:added", **note) for note in added or []]
        notation, _lines = notation_for_horns(audio_path, heard, beats, region, **common)
        if notation is None or not notation.bars:
            raise NotReady("the span is too short to bar out - select at least a couple of bars")
        return notation
    left_hand = None
    if texture:
        line = fold_texture(line)
        if left is not None:
            left_hand = fold_texture([NoteEvent(source=stem, **note) for note in left])
    elif added:
        line = with_chords(line, [NoteEvent(source=f"{stem}:added", **note) for note in added])
    notation = notation_for_span(
        audio_path,
        line,
        beats,
        region,
        stem=stem,
        config=notate_config(config, settings, Path(audio_path).stem, texture),
        anchor=anchor,
        time_signature=signature,
        pulses_per_bar=pulses,
        sample_rate=document.sample_rate,
        second_voice=(
            [NoteEvent(source=stem, **note) for note in second_voice]
            if second_voice and not texture
            else None
        ),
        # The listener's double-time checkbox: a per-track judgement like the
        # time signature, stored in the sidecar, never inferred (the Omnibook
        # writes these solos as literal 32nds, which stays the default).
        double_time=bool(settings.get("double_time")),
        left_hand=left_hand,
    )
    if notation is None or not notation.bars:
        raise NotReady("the span is too short to bar out - select at least a couple of bars")
    return notation


def page_of(
    document: Document,
    config: Config,
    run_config: Config,
    audio_path: str,
    notes: list[dict[str, Any]],
    settings: dict[str, Any],
    second_voice: list[dict[str, Any]] | None = None,
    added: list[dict[str, Any]] | None = None,
    texture: bool = False,
    left: list[dict[str, Any]] | None = None,
) -> tuple[Notation, str, dict[str, Any] | None]:
    """The page Export writes, as (Notation, MusicXML text, what became of
    the chord chart), written nowhere.

    The one assembly both the Export button and the in-app page view go
    through (gui/page.py). The page on screen has to be the file on disk
    byte for byte -- a view that drew a second reading of the same notes
    would be showing the listener a page they cannot export -- so the view
    renders exactly this string rather than a Notation of its own.

    The third value is `changes_status`'s report, None when the listener
    has typed no changes.
    """
    from swingscribe.stages.export import to_musicxml

    chart, problem = chart_of(settings, config)
    # The tracked grid is read once, here, only when the chart needs the
    # form's bar numbers -- and only once there is something to notate, so a
    # span with every note silenced still says so before asking for Beats.
    grid = None
    if chart is not None and counts_from_form(settings) and (notes or added or left):
        grid = cached_grid(audio_path, config, settings)
    notation = build_notation(
        document,
        config,
        run_config,
        audio_path,
        notes,
        settings,
        second_voice,
        added,
        texture=texture,
        left=left,
        grid=grid,
    )
    status = problem
    if chart is not None:
        notation, status = place_changes(
            notation, chart, document, config, run_config, settings, grid
        )
    return notation, to_musicxml(notation, part_name=Path(audio_path).stem), status


def counts_from_form(settings: dict[str, Any]) -> bool:
    """Whether the chart starts where the roll numbers bar 1 -- at the form
    start the listener set, or the first bar line when they set a chorus
    length and no form start, which is where the roll's gold chorus lines
    then begin -- rather than on the page's own bar 1."""
    chorus = settings.get("bars_per_chorus")
    return settings.get("form_start") is not None or (isinstance(chorus, int) and chorus > 1)


def chart_of(
    settings: dict[str, Any], config: Config
) -> tuple[chords.Chart | None, dict[str, Any] | None]:
    """The sidecar's `changes` as a chart, or (None, a report of why not).
    (None, None) when there are none. A chart whose length is not the
    listener's chorus length is refused: one of the two is wrong, and
    repeating a 12-bar chart over a 32-bar form puts every symbol after bar
    12 in the wrong place."""
    text = settings.get("changes")
    if not isinstance(text, str) or not text.strip():
        return None, None
    try:
        signature, _pulses = meter_from_settings(
            settings.get("time_signature"), settings.get("pulses_per_bar"), config
        )
        beats_per_bar: int | None = signature[0]
    except ValueError:
        beats_per_bar = None  # the page will say what is wrong with the meter
    try:
        chart = chords.parse_chart(text, beats_per_bar)
    except chords.ChartError as exc:
        return None, _report(None, error=str(exc), bar=exc.bar, token=exc.token)
    chorus = settings.get("bars_per_chorus")
    if isinstance(chorus, int) and chorus > 1 and len(chart.bars) != chorus:
        return None, _report(
            chart,
            error=(
                f"the chart has {len(chart.bars)} bars but a chorus is {chorus} (Chorus "
                "length) - type one whole chorus, or change the chorus length"
            ),
        )
    return chart, None


def _report(chart: chords.Chart | None, **fields) -> dict[str, Any]:
    """The chart's status, in the shape the Changes field and the export
    line both read."""
    return {
        "bars": len(chart.bars) if chart else 0,
        "chords": chart.chord_count if chart else 0,
        "placed": 0,
        "chart_bar": None,
        "chorus": None,
        "before": 0,
        "from": None,
        "error": None,
        "bar": None,
        "token": None,
        **fields,
    }


def check_changes(
    text: str, time_signature: str | None, bars_per_chorus: int | None, config: Config
) -> dict[str, Any]:
    """The Changes field's check as the listener types: parse and count,
    against the meter and chorus length they have set. Nothing is placed or
    stored."""
    settings = {
        "changes": text,
        "time_signature": time_signature,
        "bars_per_chorus": bars_per_chorus,
    }
    chart, problem = chart_of(settings, config)
    if problem is not None:
        return problem
    return _report(chart)


def place_changes(
    notation: Notation,
    chart: chords.Chart,
    document: Document,
    config: Config,
    run_config: Config,
    settings: dict[str, Any],
    grid: BeatGrid | None,
) -> tuple[Notation, dict[str, Any]]:
    """The chart over the page, and a report of where its bars landed.

    The chart starts at the form's bar 1 when the listener has told us where
    that is (`counts_from_form`), numbered on the same grid as the roll's bar
    lines, and at the page's own bar 1 when they have not.
    """
    origin = "span start"
    form_bar: int | None = 1
    if grid is not None:
        duration = document.audio.duration if document.audio else 0.0
        region = run_config.transcribe.region or (0.0, None)
        near = (float(region[0]), float(duration if region[1] is None else region[1]))
        form_bar = form_bar_of_page(
            grid.beats, grid.downbeats, settings, config, duration, region, near
        )
        origin = "form start" if settings.get("form_start") is not None else "chorus lines"
    if form_bar is None:
        return notation, _report(chart, error="the grid has no bar lines to count the form on")
    scale = 2 if settings.get("double_time") else 1
    placed = chords.place(chart, notation, form_bar, scale)
    count = len(chart.bars)
    inside = form_bar >= 1
    return placed, _report(
        chart,
        placed=sum(len(bar.harmony) for bar in placed.bars),
        chart_bar=(form_bar - 1) % count + 1 if inside else None,
        chorus=(form_bar - 1) // count + 1 if inside else None,
        before=0 if inside else 1 - form_bar,
        **{"from": origin},
    )


def page_path(
    config: Config,
    run_config: Config,
    audio_path: str | Path,
    settings: dict[str, Any],
    texture: bool = False,
) -> Path:
    """Where Export writes this review's page: the span, the take and the
    page's choices in the name (`export_path`). The page view names the
    same file, so it says which page it is showing."""
    return export_path(
        audio_path,
        run_config.transcribe.region or (0.0, None),
        take_of(config, run_config.transcribe.piano_line),
        page_tags(config, settings, texture),
    )


# A page with this share of its notes written as 32nds or shorter is not one
# a person would write at its tempo. Over 112 harness pages the median share
# is 0.008 and the 90th percentile 0.10; past 0.4 are three Parker ballads
# at 64-71 bpm whose double-time runs the tracker heard at the slow pulse
# (0.42-0.58; 2x time writes them as sixteenths) and Bud Powell's Oblivion
# at 280, tracked one beat per bar (0.67; Fast tune re-tracks it). Nothing
# on the page tells those two apart -- the listener's ear does -- so the hint
# names both.
SHORT_PAGE_SHARE = 0.4


def short_share(notation, double_time: bool = False) -> float:
    """The share of struck notes as short as a 32nd of the TRACKED beat:
    a 32nd on the page, or a 16th on a page notated in double time, whose
    values are twice what the tracked beat would make them. Measured
    against the tracked beat, 2x time cannot hide a grid four times too
    slow (Oblivion at 2x is all sixteenths, where Powell's page is
    eighths)."""
    struck = [n for bar in notation.bars for n in bar.notes if not n.is_rest and not n.tie_stop]
    if not struck:
        return 0.0
    limit = 0.125 * (2 if double_time else 1) + 1e-6
    return sum(1 for n in struck if n.duration <= limit) / len(struck)


def describe(
    notation,
    config: Config,
    settings: dict[str, Any],
    changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What the page holds, in the words the export bar says it: shared by
    Export and the page view so the two lines cannot disagree. `changes` is
    `page_of`'s report on the chord chart, None when there is none."""
    signature = notation.bars[0].time_signature
    share = short_share(notation, bool(settings.get("double_time")))
    return {
        "changes": changes,
        # Mostly 32nds: the beat the page was written against is probably a
        # fraction of the music's (SHORT_PAGE_SHARE). The page offers 2x time
        # and Fast tune, whichever is still off.
        "short_share": round(share, 3),
        "short_hint": share >= SHORT_PAGE_SHARE,
        "double_time": bool(settings.get("double_time")),
        "fast_tempo": bool(settings.get("fast_tempo")),
        "bars": len(notation.bars),
        "notes": sum(1 for bar in notation.bars for n in bar.notes if not n.is_rest),
        "key_fifths": notation.key_fifths,
        # The concert key, named, and whether it was detected or chosen: the
        # Key menu shows the detected one beside "Auto".
        "key": KEY_SIGNATURES.get(notation.key_fifths, ""),
        "key_auto": key_of(settings) is None,
        "swing": notation.swing,
        "timing": timing_of(config, settings),
        "staves": notation.staves,
        "transpose": notation.transpose,
        "time_signature": f"{signature[0]}/{signature[1]}",
    }


def export_span(
    document: Document,
    config: Config,
    run_config: Config,
    audio_path: str,
    notes: list[dict[str, Any]],
    settings: dict[str, Any],
    second_voice: list[dict[str, Any]] | None = None,
    added: list[dict[str, Any]] | None = None,
    texture: bool = False,
    left: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write the reviewed span to MusicXML and say what was written."""
    from swingscribe.benchmark import readability

    notation, xml, changes = page_of(
        document,
        config,
        run_config,
        audio_path,
        notes,
        settings,
        second_voice,
        added,
        texture=texture,
        left=left,
    )
    path = page_path(config, run_config, audio_path, settings, texture)
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
        **describe(notation, config, settings, changes),
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
    added: list[dict[str, Any]] | None = None,
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
    from swingscribe.score_bars import bar_line_agreement

    notation = build_notation(
        document, config, run_config, audio_path, notes, settings, added=added
    )
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
        # Are our bar lines the score's? Rhythm is gap-based and cannot see a
        # page that starts on the wrong beat (score_bars.py). This is the one
        # place the listener can FIX it -- by moving the downbeat -- so the
        # offset travels with the score and the frontend says which way.
        "beats_per_bar": reference.beats_per_bar,
        **{
            key: round(value, 3)
            for key, value in bar_line_agreement(notation, reference).items()
            if key != "beat_n"
        },
    }
