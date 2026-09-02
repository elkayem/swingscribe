"""Command-line interface.

Commands:
  run       full pipeline; prints the separated stems
  click     beat ear test — clicks mixed over the music
  audition  write the isolated stem (optionally one span) to listen to BEFORE
            spending minutes on transcription
  ab        transcription ear test — original left, transcription right
  gui       the local selection/audition app (plan §13, screens 1-3)
  cache     list what the stage cache holds per track, or delete some of it
"""

import argparse
import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path

from swingscribe import __version__, abmix, click, pipeline
from swingscribe.config import DEFAULT_CONFIG_PATH, Config
from swingscribe.stages import ingest, separate
from swingscribe.stages.ingest import AudioDecodeError

AUDIO_HELP = "Path to an audio file (anything ffmpeg can decode)"


def _add_common(parser: argparse.ArgumentParser, *, region: bool = False) -> None:
    parser.add_argument("audio", help=AUDIO_HELP)
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a YAML config file (default: config/default.yaml)",
    )
    if region:
        parser.add_argument(
            "--start", type=float, default=None, help="Analyse from this time (seconds)"
        )
        parser.add_argument(
            "--end", type=float, default=None, help="Analyse until this time (seconds)"
        )
        parser.add_argument(
            "--stem",
            default=None,
            help="Which separated stem carries the solo (other/guitar/piano/bass/vocals)",
        )
        parser.add_argument(
            "--time-signature",
            default=None,
            help='Time signature for the whole tune, e.g. "4/4", "3/4", "6/8"',
        )
        parser.add_argument(
            "--downbeat",
            type=float,
            default=None,
            help="Seconds; a beat that is beat 1. Re-phases the bar grid.",
        )
        parser.add_argument(
            "--bars-per-chorus",
            type=int,
            default=None,
            help="Form length in bars (12-bar blues, 32-bar AABA)",
        )


def _add_tempo_hint(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tempo-hint",
        type=float,
        default=None,
        help="Known tempo in BPM; corrects half/double-octave tracking errors",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swingscribe",
        description="Jazz audio in → instrument-separated, swing-aware notation out",
    )
    parser.add_argument("--version", action="version", version=f"swingscribe {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the transcription pipeline")
    _add_common(run_parser, region=True)
    _add_tempo_hint(run_parser)

    click_parser = subparsers.add_parser(
        "click",
        help="Beat ear test (plan §6): mix a click at the detected beats over "
        "the music and write a wav to listen to",
    )
    _add_common(click_parser)
    _add_tempo_hint(click_parser)
    click_parser.add_argument(
        "-o",
        "--out",
        default=None,
        help="Output wav path (default: <input>.click.wav next to the input)",
    )

    audition_parser = subparsers.add_parser(
        "audition",
        help="Write the isolated stem (optionally just one span) so you can "
        "hear whether the soloist is cleanly separated before transcribing",
    )
    _add_common(audition_parser, region=True)
    audition_parser.add_argument(
        "-o",
        "--out",
        default=None,
        help="Output wav path (default: <input>.<stem>.wav next to the input)",
    )

    ab_parser = subparsers.add_parser(
        "ab",
        help="Transcription ear test (plan §6): stereo wav with the original "
        "on the left and the rendered transcription on the right; also "
        "writes the transcribed MIDI",
    )
    _add_common(ab_parser, region=True)
    _add_tempo_hint(ab_parser)
    ab_parser.add_argument(
        "-o",
        "--out",
        default=None,
        help="Output stereo wav path (default: <input>.ab.wav next to the input)",
    )
    ab_parser.add_argument(
        "--midi",
        default=None,
        help="Output MIDI path (default: <input>.transcribed.mid next to the input)",
    )

    gui_parser = subparsers.add_parser(
        "gui",
        help="Open the local app for finding a solo, isolating the instrument "
        "playing it, and auditioning the isolation before transcribing",
    )
    # No audio positional: the GUI has its own track picker, and pre-loading a
    # file is a convenience, not the entry point.
    gui_parser.add_argument("audio", nargs="?", default=None, help=AUDIO_HELP)
    gui_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a YAML config file (default: config/default.yaml)",
    )
    gui_parser.add_argument(
        "--library", default=None, help="Directory the track picker lists (default: cwd)"
    )
    gui_parser.add_argument("--port", type=int, default=None, help="Port to serve on")
    gui_parser.add_argument("--no-browser", action="store_true", help="Don't open a browser window")

    cache_parser = subparsers.add_parser(
        "cache",
        help="List what the stage cache holds for each track (stems, ingested "
        "wav), or delete some of it to reclaim disk. The GUI has the same "
        "panel; this reaches a cache the GUI is not pointed at.",
    )
    cache_parser.add_argument("action", choices=["ls", "rm"])
    cache_parser.add_argument(
        "names",
        nargs="*",
        help="For rm: stems directory names exactly as `cache ls` prints them",
    )
    cache_parser.add_argument(
        "--track",
        action="append",
        default=[],
        metavar="ID",
        help="For rm: delete everything cached for this track id (repeatable). "
        "The sidecar beside the audio is never touched.",
    )
    cache_parser.add_argument(
        "--cache-dir",
        default=None,
        help="Cache to inspect instead of the config's (the eval harness keeps "
        "its own under benchmark/)",
    )
    cache_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a YAML config file (default: config/default.yaml)",
    )
    return parser


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Fold CLI flags into the config so they participate in cache keys."""
    if getattr(args, "tempo_hint", None):
        config = config.model_copy(
            update={"beats": config.beats.model_copy(update={"tempo_hint": args.tempo_hint})}
        )
    updates: dict = {}
    if getattr(args, "stem", None):
        updates["stem"] = args.stem
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if start is not None or end is not None:
        updates["region"] = (start or 0.0, end)  # a None end means "to the end"
    if updates:
        config = config.model_copy(
            update={"transcribe": config.transcribe.model_copy(update=updates)}
        )

    # Meter overrides are config, not a side channel: they belong to the cache
    # key so a different downbeat genuinely re-derives the bar grid, while
    # leaving separation and transcription cached (docs/meter-plan.md).
    meter_updates = {}
    if getattr(args, "time_signature", None):
        meter_updates["time_signature"] = args.time_signature
    if getattr(args, "downbeat", None) is not None:
        meter_updates["anchor"] = args.downbeat
    if getattr(args, "bars_per_chorus", None):
        meter_updates["bars_per_chorus"] = args.bars_per_chorus
    if meter_updates:
        config = config.model_copy(update={"meter": config.meter.model_copy(update=meter_updates)})
    return config


def _region_for_output(config: Config, duration: float) -> tuple[float, float] | None:
    """The configured region resolved against the track, or None for all of it."""
    if config.transcribe.region is None:
        return None
    start, end = config.transcribe.region
    end = duration if end is None else min(end, duration)
    return (max(0.0, start), end)


def cmd_gui(config: Config, args: argparse.Namespace) -> int:
    """Serve the selection/audition GUI. Blocks until interrupted."""
    try:
        from swingscribe.gui.server import serve
    except ModuleNotFoundError as exc:
        print(
            f"swingscribe: the GUI needs the 'gui' dependency group ({exc.name})",
            file=sys.stderr,
        )
        print("  uv sync --group ml --group gui", file=sys.stderr)
        return 1

    updates: dict = {}
    if args.library:
        updates["library_dir"] = args.library
    elif args.audio:
        # A file was named: list the folder it lives in, and it will be there.
        updates["library_dir"] = str(Path(args.audio).expanduser().resolve().parent)
    if args.port:
        updates["port"] = args.port
    if args.no_browser:
        updates["open_browser"] = False
    if updates:
        config = config.model_copy(update={"gui": config.gui.model_copy(update=updates)})

    with contextlib.suppress(KeyboardInterrupt):
        serve(config)
    return 0


def _human_bytes(count: int) -> str:
    if count >= 1e9:
        return f"{count / 1e9:.1f} GB"
    return f"{count / 1e6:.0f} MB"


def cmd_cache(config: Config, args: argparse.Namespace) -> int:
    """`cache ls` / `cache rm`, over gui/storage.py so the GUI and the shell
    agree about what a track owns."""
    from swingscribe.gui import storage

    if args.cache_dir:
        config = config.model_copy(update={"cache_dir": Path(args.cache_dir)})

    if args.action == "ls":
        listing = storage.inventory(config)
        print(f"{listing['cache_dir']}: {_human_bytes(listing['total_bytes'])}")
        for track in listing["tracks"]:
            print(f"\n{track['name']}  [{track['id']}]  {_human_bytes(track['bytes'])}")
            for wav in track["audio"]:
                print(f"    {wav['name']:<44} {_human_bytes(wav['bytes']):>8}  ingested wav")
            for item in track["stems"]:
                span = ""
                if item["span"]:
                    span = f"  span {item['span'][0]:.1f}-{item['span'][1]:.1f}s"
                print(f"    {item['name']:<44} {_human_bytes(item['bytes']):>8}{span}")
        if listing["orphans"]:
            print(f"\n(no track known)  {_human_bytes(listing['orphan_bytes'])}")
            for item in listing["orphans"]:
                print(f"    {item['name']:<44} {_human_bytes(item['bytes']):>8}")
        return 0

    if not args.names and not args.track:
        print("swingscribe: cache rm needs stems directory names or --track ids", file=sys.stderr)
        return 2
    status = 0
    for name in args.names:
        try:
            freed = storage.delete_stems(config, name)
            print(f"removed {name}: {_human_bytes(freed)}")
        except (ValueError, FileNotFoundError, storage.InUseError, OSError) as exc:
            print(f"swingscribe: {name}: {exc}", file=sys.stderr)
            status = 1
    for track_id in args.track:
        try:
            result = storage.delete_track(config, track_id)
            print(f"removed {result['name']}: {_human_bytes(result['freed'])}")
        except (ValueError, FileNotFoundError, storage.InUseError, OSError) as exc:
            print(f"swingscribe: {track_id}: {exc}", file=sys.stderr)
            status = 1
    return status


def cmd_audition(config: Config, args: argparse.Namespace) -> int:
    """Separation only — no beat tracking, no transcription."""
    stages = [("ingest", ingest.run), ("separate", separate.run)]
    document = pipeline.run(args.audio, config, stages=stages)

    stem = config.transcribe.stem
    stem_path = document.stems.get(stem)
    if stem_path is None:
        available = ", ".join(sorted(document.stems))
        print(f"swingscribe: no {stem!r} stem; available: {available}", file=sys.stderr)
        return 1

    region = _region_for_output(config, document.audio.duration)
    out = Path(args.out) if args.out else abmix.default_audition_path(args.audio, stem)
    abmix.write_stem_slice(stem_path, out, region)
    span = f"{region[0]:.1f}-{region[1]:.1f}s" if region else "whole track"
    print(f"isolated {stem} stem ({span}) → {out}")
    print("Listen before transcribing: if the soloist isn't clearly dominant here,")
    print("try a different --stem, or separate.model: htdemucs_6s for guitar/piano splits.")
    return 0


def cmd_run(document, config: Config, args: argparse.Namespace) -> int:
    for name, path in document.stems.items():
        print(f"{name}: {path}")
    return 0


def cmd_click(document, config: Config, args: argparse.Namespace) -> int:
    grid = document.beat_grid
    if grid is None or not grid.beats:
        print("swingscribe: no beats detected — nothing to click", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else click.default_click_path(args.audio)
    click.render_click_track(document.audio.path, grid, out)
    print(f"{len(grid.beats)} beats / {len(grid.downbeats)} downbeats → {out}")
    return 0


def cmd_ab(document, config: Config, args: argparse.Namespace) -> int:
    stem = config.transcribe.stem
    notes = document.notes.get(stem, [])
    if not notes:
        print("swingscribe: no notes transcribed — nothing to render", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else abmix.default_ab_path(args.audio)
    midi_out = Path(args.midi) if args.midi else abmix.default_midi_path(args.audio)
    region = _region_for_output(config, document.audio.duration)
    abmix.notes_to_midi(notes, midi_out)
    abmix.render_ab_mix(document.audio.path, notes, out, region)
    print(f"{len(notes)} notes → {midi_out}")
    print(f"A/B mix (original left, transcription right) → {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command not in ("run", "click", "audition", "ab", "gui", "cache"):
        parser.print_help()
        return 2

    config = apply_overrides(Config.from_yaml(args.config), args)
    try:
        if args.command == "gui":
            return cmd_gui(config, args)
        if args.command == "cache":
            return cmd_cache(config, args)
        if args.command == "audition":
            return cmd_audition(config, args)
        document = pipeline.run(args.audio, config)
    except (AudioDecodeError, FileNotFoundError, NotImplementedError, ValueError) as exc:
        print(f"swingscribe: {exc}", file=sys.stderr)
        return 1

    handlers = {"run": cmd_run, "click": cmd_click, "ab": cmd_ab}
    return handlers[args.command](document, config, args)


if __name__ == "__main__":
    raise SystemExit(main())
