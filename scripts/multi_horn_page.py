"""Write a multi-horn head's page through the GUI's own path, from a shell.

    .venv\\Scripts\\python.exe scripts\\multi_horn_page.py AUDIO --start 0 --end 67.308 ^
        --sidecar AUDIO.swingscribe.json --out page.musicxml --dump-voices voices.txt

A head played by two horns in harmony (docs/multi-horn.md): Basic Pitch hears
both horns over the span on the separated `other` stem, `voices.assign` puts
each note in a voice, and the page writes them on one staff -- voice 1 stems
up, voice 2 down, the lower horn moved up an octave by phrase where it sits
an octave or more under, a unison written once. Nothing here decides
anything: it is the Export button without the browser, so the page it writes
is the page the GUI would write for the same sidecar.

- `review.span_config` -> the multi-horn transcribe config, rounded as the
  GUI rounds it, so its cached review is the GUI's and the GUI's is its;
- `review.cached_review` / `analyze_and_cache` -> the review (Basic Pitch,
  the voices, CREPE's frame trace for the roll), cached under the GUI's key;
- `gui/edits.resolve` -> the listener's erasures, additions and voice moves
  from the sidecar, exactly as the roll and Export resolve them;
- `gui/musicxml.page_of` -> the MusicXML string Export writes.

The sidecar is READ, never written. It supplies the anchor, form start,
meter, model and stem; the ensemble is forced to "multi-horn" in memory.
Flags choose the rhythm without touching it: `--timing` (literal-8 is the
multi-horn default: eighths at 160 bpm and over, finer only where eighths
cannot keep a beat's notes apart; `--timing literal-16` writes 16ths),
`--lag` (take the held chords' lag behind the beat out, read once over both
horns) and `--thirds` (write a beat that fits thirds as a triplet). Both
are off by default; the listener decides them. A head folds each scoop
into the note it leads into, written as a grace note (`--no-fold` writes
them as notes).

Needs the ml group (Basic Pitch runs on onnxruntime; CREPE on torch) and the
stems already separated -- `--separate` runs the separation first, in this
process, as the GUI's Separate button would over the span.
"""

import argparse
import contextlib
import json
import sys
from pathlib import Path


def parse_args(argv=None) -> argparse.Namespace:
    from swingscribe.config import TIMINGS

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("audio", type=Path, help="the recording")
    parser.add_argument("--start", type=float, help="span start, seconds (else the sidecar's)")
    parser.add_argument("--end", type=float, help="span end, seconds (else the sidecar's)")
    parser.add_argument(
        "--sidecar",
        type=Path,
        help="a sidecar to read (default: the audio's own <audio>.swingscribe.json if any)",
    )
    parser.add_argument("--anchor", type=float, help="the downbeat, seconds (overrides)")
    parser.add_argument("--form-start", type=float, help="where the form starts, seconds")
    parser.add_argument("--model", help="separation model (default: sidecar, then config)")
    parser.add_argument("--stem", help="the stem both horns are in (default: sidecar, else other)")
    parser.add_argument("--out", type=Path, help="MusicXML to write (default: Export's name)")
    parser.add_argument(
        "--timing",
        choices=TIMINGS,
        help="the rhythm (default: the sidecar's, else literal-8 for a multi-horn head; "
        "literal-16 for 16ths)",
    )
    parser.add_argument("--lag", action="store_true", help="take the line's lag out")
    parser.add_argument("--thirds", action="store_true", help="read triplets in literal time")
    parser.add_argument(
        "--no-fold",
        action="store_true",
        help="write scoops and re-attack heads as notes, not folded (sidecar literal_lead_ins)",
    )
    parser.add_argument(
        "--dump-voices",
        nargs="?",
        const="-",
        metavar="FILE",
        help="write the heard voices and the written bars as text (- or no FILE: stdout)",
    )
    parser.add_argument("--config", type=Path, help="a config YAML (default: the packaged one)")
    parser.add_argument("--cache-dir", type=Path, help="the GUI's cache directory")
    parser.add_argument(
        "--retranscribe", action="store_true", help="re-run the review even if it is cached"
    )
    parser.add_argument(
        "--separate", action="store_true", help="separate the span first if its stem is missing"
    )
    return parser.parse_args(argv)


def load_settings(args: argparse.Namespace) -> dict:
    """The sidecar as the page reads it, with the flags laid over it and the
    ensemble forced to multi-horn. Never written back."""
    from swingscribe.gui import library

    path = args.sidecar or library.settings_path(args.audio)
    settings = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else {}
    settings["ensemble"] = "multi-horn"
    overrides = {
        "anchor": args.anchor,
        "form_start": args.form_start,
        "model": args.model,
        "stem": args.stem,
        "timing": args.timing,
    }
    settings.update({key: value for key, value in overrides.items() if value is not None})
    if args.lag:
        settings["literal_lag"] = True
    if args.thirds:
        settings["literal_thirds"] = True
    if args.no_fold:
        settings["literal_lead_ins"] = False
    return settings


def tolerant_console() -> None:
    """A Windows console in cp1252 cannot print a flat sign (the key, "B♭
    major"), and the summary died on it AFTER the page was written. Replace
    what the console cannot encode; files are written in UTF-8 regardless."""
    for stream in (sys.stdout, sys.stderr):
        # Not a text stream that can be reconfigured: leave it as it is.
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")


def span_of(args: argparse.Namespace, settings: dict) -> tuple[float, float | None]:
    region = settings.get("region") or [None, None]
    start = args.start if args.start is not None else region[0]
    end = args.end if args.end is not None else region[1]
    if start is None:
        sys.exit("no span: pass --start/--end or a sidecar with a region")
    return float(start), None if end is None else float(end)


def pitch_name(pitch: int, key: int) -> str:
    from swingscribe.stages.notate import spell

    step, alter, octave = spell(pitch, key)
    return f"{step}{'#' * alter if alter > 0 else 'b' * -alter}{octave}"


def written(note, key: int) -> str:
    """One notated note as text: grace notes in parentheses, pitch (or
    rest), value in quarters, ties, tuplet, stem and hidden marks."""
    head = "r" if note.is_rest else pitch_name(note.pitch, key)
    if note.grace:
        head = "(" + " ".join(pitch_name(p, key) for p in note.grace) + ")" + head
    if note.chord:
        head += "+" + "+".join(pitch_name(p, key) for p in note.chord)
    marks = ""
    if note.tie_stop:
        marks += "~"
    text = f"{marks}{head}:{note.duration:g}"
    if note.tie_start:
        text += "~"
    if note.tuplet:
        text += f"({note.tuplet[0]}:{note.tuplet[1]})"
    if note.stem:
        text += f"[{note.stem}]"
    if note.hidden:
        text += "[hidden]"
    return text


def dump(notation, lines, edits, key: int, roll_bar: int | None) -> str:
    """The heard voices and the written page, as text a person can read
    beside the score."""
    out = ["# heard (as transcribed, after the listener's edits)"]
    heard = sorted(
        [*edits["audible"], *edits["added"]], key=lambda n: (n["onset"], -int(n["pitch"]))
    )
    for n in heard:
        out.append(
            f"{n['onset']:8.3f}  {n['duration']:6.3f}  v{n.get('voice', 1)}  "
            f"{pitch_name(int(n['pitch']), key):>4}  conf {n.get('confidence', 0.0):.2f}"
            + ("  lead-in" if n.get("lead_in") else "")
        )
    out.append("")
    out.append("# lower-voice phrases (start, end, notes, median interval, moved)")
    for p in lines.phrases:
        interval = "-" if p["interval"] is None else f"{p['interval']:g}"
        out.append(
            f"{p['start']:8.3f} {p['end']:8.3f}  {p['notes']:3d} notes  "
            f"interval {interval:>4}  moved {p['moved']:+d}"
        )
    out.append(f"unisons written once: {lines.unisons}")
    out.append("")
    offset = "" if roll_bar is None else f" (page bar 1 is the roll's bar {roll_bar})"
    out.append(f"# written, bar by bar{offset}")
    for bar in notation.bars:
        for voice in (1, 2):
            notes = [n for n in bar.notes if n.voice == voice]
            if notes:
                body = " ".join(written(n, key) for n in notes)
                out.append(f"bar {bar.number:3d} v{voice}: {body}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    args = parse_args(argv)
    tolerant_console()
    from swingscribe import pipeline
    from swingscribe.benchmark import readability
    from swingscribe.config import DEFAULT_CONFIG_PATH, Config
    from swingscribe.gui import edits as gui_edits
    from swingscribe.gui import library, review
    from swingscribe.gui import musicxml as gui_musicxml
    from swingscribe.model import NoteEvent
    from swingscribe.notation import form_bar_of_page, grid_config, horn_lines, reading_of
    from swingscribe.stages import beats, ingest, separate

    config = Config.from_yaml(args.config or DEFAULT_CONFIG_PATH)
    if args.cache_dir is not None:
        config = config.model_copy(update={"cache_dir": args.cache_dir})
    audio = args.audio.expanduser().resolve()
    if not audio.is_file():
        sys.exit(f"no such file: {audio}")
    settings = load_settings(args)
    # A linked take names its page, and places it, as the GUI's Export does
    # (gui/musicxml.take_name); the audio's own sidecar names it for the audio.
    take = (
        str(args.sidecar)
        if args.sidecar is not None and library.is_linked(args.sidecar, audio)
        else None
    )
    start, end = span_of(args, settings)
    settings["region"] = [start, end]
    model = settings.get("model") or config.separate.model
    stem = settings.get("stem") or "other"

    document = library.ingested_document(audio, config)
    duration = float(document.audio.duration)
    run_config = review.span_config(config, stem, start, end, "multi-horn")
    run_config = run_config.model_copy(
        update={"separate": run_config.separate.model_copy(update={"model": model})}
    )
    if library.resolve_stem(document, run_config, model, stem) is None:
        if not args.separate:
            available = ", ".join(library.selectable_stems(document, run_config, model)) or "none"
            sys.exit(
                f"no {stem!r} stem for {model} over {start}-{end} (available: {available}); "
                "separate the span in the GUI first, or pass --separate"
            )
        span = (
            round(start, review.SPAN_PRECISION),
            round(duration if end is None else end, review.SPAN_PRECISION),
        )
        print(f"separating {span[0]}-{span[1]} s with {model} ...", flush=True)
        separating = config.model_copy(
            update={"separate": config.separate.model_copy(update={"model": model, "span": span})}
        )
        pipeline.run(audio, separating, stages=[("ingest", ingest.run), ("separate", separate.run)])

    payload = None if args.retranscribe else review.cached_review(document, run_config, model)
    if payload is None:
        print(
            "transcribing both horns (Basic Pitch, and CREPE for the frame trace) ...", flush=True
        )
        payload = review.analyze_and_cache(document, run_config, model)
    else:
        print("review: cached")

    tc = run_config.transcribe
    region_end = duration if end is None else end
    edits = gui_edits.resolve(
        settings,
        payload,
        (start, region_end),
        horns=True,
        overlap_s=tc.multi_horn_overlap_ms / 1000.0,
        overlap_share=tc.multi_horn_overlap_share,
    )

    try:
        grid = gui_musicxml.cached_grid(audio, config, settings)
    except gui_musicxml.NotReady:
        print("tracking beats ...", flush=True)
        pipeline.run(
            audio,
            grid_config(config, settings),
            stages=[("ingest", ingest.run), ("beats", beats.run)],
        )
        grid = gui_musicxml.cached_grid(audio, config, settings)

    notation, xml, changes = gui_musicxml.page_of(
        document,
        config,
        run_config,
        str(audio),
        edits["audible"],
        settings,
        added=edits["added"],
        take=take,
    )
    out = args.out or gui_musicxml.page_path(config, run_config, audio, settings, take=take)
    out.write_text(xml, encoding="utf-8")

    heard = [NoteEvent(source=stem, **note) for note in (*edits["audible"], *edits["added"])]
    lines = horn_lines(heard)
    upper = sum(1 for n in heard if n.voice != 2)
    lower = sum(1 for n in heard if n.voice == 2)
    described = gui_musicxml.describe(notation, config, settings, changes)
    readable = readability(notation)
    roll_bar = form_bar_of_page(
        grid.beats, grid.downbeats, settings, config, duration, (start, end)
    )
    print(f"wrote {out}")
    lead_ins = sum(1 for n in heard if n.lead_in)
    print(
        f"heard: {upper} notes in voice 1, {lower} in voice 2, "
        f"{len(edits['candidates'])} candidates (ghosts and thirds) offered, "
        f"{lead_ins} lead-ins"
    )
    moved = [p for p in lines.phrases if p["moved"]]
    reading = reading_of(settings, config)
    print(
        f"written: {described['bars']} bars, {described['notes']} notes, key "
        f"{described['key']} ({described['timing']}"
        f"{', lag out' if settings.get('literal_lag') else ''}"
        f"{', thirds' if settings.get('literal_thirds') else ''}"
        f"{', lead-ins folded' if reading['literal_lead_ins'] else ''}); "
        f"{len(moved)} of {len(lines.phrases)} lower phrases moved up, "
        f"{lines.unisons} unisons written once"
    )
    print(
        f"readability {readable['readability']:.3f}, tie rate {readable['tie_rate']:.3f}"
        + ("" if roll_bar is None else f"; page bar 1 is the roll's bar {roll_bar}")
    )
    if args.dump_voices:
        text = dump(notation, lines, edits, notation.key_fifths, roll_bar)
        if args.dump_voices == "-":
            print(text)
        else:
            Path(args.dump_voices).write_text(text, encoding="utf-8")
            print(f"voices written to {args.dump_voices}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
