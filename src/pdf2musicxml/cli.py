"""Command line: convert, setup, doctor."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from pdf2musicxml import __version__, paths
from pdf2musicxml.convert import Options, convert_path, report, summary_rows, summary_table
from pdf2musicxml.engines import EngineError, audiveris, homr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2musicxml",
        description="Turn PDF jazz transcriptions into MusicXML files MuseScore opens.",
    )
    parser.add_argument("--version", action="version", version=f"pdf2musicxml {__version__}")
    commands = parser.add_subparsers(dest="command")

    convert = commands.add_parser("convert", help="convert a PDF, or every PDF in a folder")
    convert.add_argument("paths", nargs="+", type=Path, help="PDF files or folders of them")
    convert.add_argument("--out", type=Path, help="output folder (default: <pdf folder>/musicxml)")
    convert.add_argument(
        "--engine",
        choices=("homr", "audiveris"),
        default="homr",
        help="primary reading (default homr; Audiveris needs `setup` once)",
    )
    convert.add_argument(
        "--no-check",
        action="store_true",
        help="do not run the other engine and list the bars the two disagree on",
    )
    convert.add_argument(
        "--font",
        choices=("auto", "standard", "jazz"),
        default="auto",
        help="Audiveris symbol family: jazz for handwritten-style pages "
        "(auto reads the PDF's fonts)",
    )
    convert.add_argument(
        "--concert",
        action="store_true",
        help="shift pitches to concert pitch instead of writing <transpose>",
    )
    convert.add_argument(
        "--instrument", help='override the instrument, e.g. "Bb Trumpet" or "Alto Sax"'
    )
    convert.add_argument("--time", dest="time_signature", help="force a time signature, e.g. 4/4")
    convert.add_argument("--title", help="title for a single-transcription PDF")
    convert.add_argument("--split", help='page ranges, one transcription each: "4-5,6-8,9"')
    convert.add_argument("--single", action="store_true", help="the whole PDF is one transcription")
    convert.add_argument(
        "--redetect", action="store_true", help="ignore the manifest's page groups"
    )
    convert.add_argument(
        "--force", action="store_true", help="redo pages and files that look up to date"
    )
    convert.add_argument(
        "--long-side", type=int, default=3300, help="page raster size in px (default 3300)"
    )
    convert.add_argument(
        "--no-printed-pitch",
        action="store_true",
        help="do not correct pitches to the noteheads a notation-program PDF prints",
    )

    setup = commands.add_parser("setup", help="download and unpack Audiveris and its OCR data")
    setup.add_argument("--force", action="store_true", help="re-download even if present")

    commands.add_parser("doctor", help="show what is installed and where")

    summary = commands.add_parser(
        "summary", help="table every transcription in a folder's manifests, worst first"
    )
    summary.add_argument("path", type=Path, help="the PDF folder, or its musicxml folder")

    render = commands.add_parser(
        "render", help="open every output in MuseScore (command line) and report any it refuses"
    )
    render.add_argument("path", type=Path, help="the PDF folder, or its musicxml folder")
    render.add_argument("--limit", type=int, help="only the first N files")
    return parser


def doctor() -> int:
    print(f"pdf2musicxml {__version__}")
    print(f"tool home: {paths.tool_home()}")
    for name, module in (("pypdfium2", "pypdfium2"), ("numpy", "numpy"), ("Pillow", "PIL")):
        try:
            __import__(module)
            print(f"  {name}: ok")
        except ImportError:
            print(f"  {name}: MISSING (uv sync --group omr)")
    print(f"  homr: {'ok' if homr.is_installed() else 'MISSING (uv sync --group omr)'}")
    if audiveris.is_installed():
        print(f"  audiveris {paths.AUDIVERIS_VERSION}: ok at {paths.audiveris_dir()}")
        print(
            f"  audiveris OCR (eng): {'ok' if audiveris.ocr_installed() else 'missing (run setup)'}"
        )
    else:
        print("  audiveris: not installed (run `pdf2musicxml setup`)")
    return 0


def tolerate_console_encoding() -> None:
    """Never let a title's ligature kill a run on a cp1252 console.

    Titles come out of PDFs and carry U+FB01-style ligatures; a Windows
    console that cannot encode one raised UnicodeEncodeError from a plain
    print after the work was done and the file written. Replacement
    characters on screen are the right trade.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):  # a closed or exotic stream
                reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    tolerate_console_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "setup":
        try:
            audiveris.install(print, force=args.force)
        except EngineError as error:
            print(f"setup failed: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "render":
        from pdf2musicxml.render import render_folder

        folder = args.path
        if folder.is_dir() and not list(folder.glob("*.musicxml")):
            folder = folder / "musicxml"
        try:
            outcome = render_folder(folder, limit=args.limit)
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(f"{len(outcome.rendered)} rendered, {len(outcome.failed)} refused by MuseScore")
        for source, why in outcome.failed:
            print(f"  {source.name}: {why}")
        return 1 if outcome.failed else 0
    if args.command == "summary":
        folder = args.path
        if folder.is_dir() and not list(folder.glob("*.pdf2musicxml.json")):
            folder = folder / "musicxml"
        rows = summary_rows(folder)
        if not rows:
            print(f"no manifests under {folder}", file=sys.stderr)
            return 1
        table = summary_table(rows)
        (folder / "SUMMARY.md").write_text(table + "\n", encoding="utf-8")
        print(table)
        print(f"\nwritten to {folder / 'SUMMARY.md'}")
        return 0
    if args.command != "convert":
        parser.print_help()
        return 2
    options = Options(
        engine=args.engine,
        check=not args.no_check,
        font=args.font,
        concert=args.concert,
        force=args.force,
        long_side=args.long_side,
        out_dir=args.out,
        split=args.split,
        single=args.single,
        instrument=args.instrument,
        time_signature=args.time_signature,
        title=args.title,
        redetect=args.redetect,
        printed_pitch=not args.no_printed_pitch,
    )
    results = []
    for target in args.paths:
        if not target.exists():
            print(f"not found: {target}", file=sys.stderr)
            return 1
        results.extend(convert_path(target, options))
    if results:
        print()
        print(report(results))
    failed = sum(1 for r in results if r.error)
    return 1 if failed else 0
