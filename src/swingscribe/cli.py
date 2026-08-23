"""Command-line interface: `swingscribe run <audio>`."""

import argparse
import sys
from collections.abc import Sequence

from swingscribe import __version__, pipeline
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "run":
        parser.print_help()
        return 2

    config = Config.from_yaml(args.config)
    try:
        document = pipeline.run(args.audio, config)
    except NotImplementedError as exc:
        print(f"swingscribe: {exc}", file=sys.stderr)
        return 1
    for name, path in document.stems.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
