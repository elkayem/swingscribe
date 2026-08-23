"""Command-line interface: `swingscribe run <audio>`."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from swingscribe import __version__, click, pipeline
from swingscribe.config import DEFAULT_CONFIG_PATH, Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swingscribe",
        description="Jazz audio in → instrument-separated, swing-aware notation out",
    )
    parser.add_argument("--version", action="version", version=f"swingscribe {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the transcription pipeline")
    run_parser.add_argument("audio", help="Path to an audio file (mp3/wav/flac)")
    run_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a YAML config file (default: config/default.yaml)",
    )

    click_parser = subparsers.add_parser(
        "click",
        help="Ear test (plan §6): mix a click at the detected beats over the "
        "music and write a wav to listen to",
    )
    click_parser.add_argument("audio", help="Path to an audio file (mp3/wav/flac)")
    click_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a YAML config file (default: config/default.yaml)",
    )
    click_parser.add_argument(
        "-o",
        "--out",
        default=None,
        help="Output wav path (default: <input>.click.wav next to the input)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command not in ("run", "click"):
        parser.print_help()
        return 2

    config = Config.from_yaml(args.config)
    try:
        document = pipeline.run(args.audio, config)
    except NotImplementedError as exc:
        print(f"swingscribe: {exc}", file=sys.stderr)
        return 1

    if args.command == "run":
        for name, path in document.stems.items():
            print(f"{name}: {path}")
        return 0

    if document.beat_grid is None or not document.beat_grid.beats:
        print("swingscribe: no beats detected — nothing to click", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else click.default_click_path(args.audio)
    click.render_click_track(document.audio.path, document.beat_grid, out)
    grid = document.beat_grid
    print(f"{len(grid.beats)} beats / {len(grid.downbeats)} downbeats → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
