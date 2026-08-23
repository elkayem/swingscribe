"""Command-line interface.

Commands:
  run       full pipeline; prints the separated stems
  click     beat ear test — clicks mixed over the music
  audition  write the isolated stem (optionally one span) to listen to BEFORE
            spending minutes on transcription
  ab        transcription ear test — original left, transcription right
"""

import argparse
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
    return config


def _region_for_output(config: Config, duration: float) -> tuple[float, float] | None:
    """The configured region resolved against the track, or None for all of it."""
    if config.transcribe.region is None:
        return None
    start, end = config.transcribe.region
    end = duration if end is None else min(end, duration)
    return (max(0.0, start), end)


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

    if args.command not in ("run", "click", "audition", "ab"):
        parser.print_help()
        return 2

    config = apply_overrides(Config.from_yaml(args.config), args)
    try:
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
