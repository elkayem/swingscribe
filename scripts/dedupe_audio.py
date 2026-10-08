"""Find byte-identical recordings and propose keeping one, linking the rest.

    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark             (dry run)
    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark --keep-in Multi-Horn
    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark --apply     (not yet)

PREPARED, NOT RUN: the listener wants to review linked sidecars before any
duplicate audio goes (docs/multi-horn-handoff.md). Nothing is changed unless
`--apply` is given, and the hand-off says when that is.

The library holds copies of one recording in two folders (benchmark/
Multi-Horn/Open-Sesame.m4a and Transcriptions_Other/Open-Sesame-...m4a, say).
They are one recording -- one digest, one cache -- with a sidecar each. For
every group of identical files this keeps ONE (the first by path, or the one
under `--keep-in`) and, for each other copy:

1. every sidecar about the copy -- its own, and any linked take in its folder
   naming it -- becomes a LINKED take naming the kept file
   (`gui/library.py`, takes). Its name, its folder and everything in it stay
   exactly as they are, so its harness key (the sidecar's path) and every
   pin keyed on it do not move, and its caches are the kept file's already;
2. the copy is deleted.

A copy whose sidecars cannot be rewritten (an unreadable sidecar) is left
whole and reported. Hashing reads every audio file once.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def audio_files(root: Path) -> list[Path]:
    from swingscribe.gui import library

    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in AUDIO_SUFFIXES
        and not library.is_derived_output(p)
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def groups(root: Path) -> list[list[Path]]:
    """Byte-identical audio files under `root`, two or more to a group. Sizes
    first, so only files that could be identical are hashed."""
    by_size: dict[int, list[Path]] = {}
    for path in audio_files(root):
        by_size.setdefault(path.stat().st_size, []).append(path)
    found: dict[str, list[Path]] = {}
    for same in by_size.values():
        if len(same) < 2:
            continue
        for path in same:
            found.setdefault(digest(path), []).append(path)
    return [sorted(paths) for paths in found.values() if len(paths) > 1]


def keeper(paths: list[Path], keep_in: str | None, root: Path) -> Path:
    if keep_in:
        preferred = [p for p in paths if keep_in in p.relative_to(root).parts]
        if preferred:
            return preferred[0]
    return paths[0]


def sidecars_of(audio: Path) -> list[Path]:
    """Every sidecar in the copy's folder that is about it: its own, and any
    take naming it."""
    from swingscribe.gui import library

    found = []
    for sidecar in sorted(audio.parent.glob(f"*{library.SETTINGS_SUFFIX}")):
        try:
            if library._norm(library.audio_of(sidecar)) == library._norm(audio):
                found.append(sidecar)
        except OSError:
            continue
    return found


def plan(root: Path, keep_in: str | None) -> list[dict]:
    from swingscribe.gui import library

    steps = []
    for paths in groups(root):
        kept = keeper(paths, keep_in, root)
        for copy in paths:
            if copy == kept:
                continue
            relinks = []
            for sidecar in sidecars_of(copy):
                try:
                    json.loads(sidecar.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    relinks = None
                    steps.append({"copy": copy, "kept": kept, "refused": f"{sidecar}: {exc}"})
                    break
                relinks.append((sidecar, library._relative_audio(sidecar, kept)))
            if relinks is not None:
                steps.append({"copy": copy, "kept": kept, "relink": relinks})
    return steps


def apply(steps: list[dict]) -> None:
    for step in steps:
        if "refused" in step:
            continue
        for sidecar, relative in step["relink"]:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["audio"] = relative
            data["file"] = step["kept"].name
            sidecar.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        step["copy"].unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", type=Path, help="the folder to search (e.g. benchmark)")
    parser.add_argument("--keep-in", help="keep the copy under this folder name when there is one")
    parser.add_argument(
        "--apply", action="store_true", help="rewrite the sidecars and delete the copies"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    steps = plan(root, args.keep_in)
    if not steps:
        print("no byte-identical recordings")
        return 0
    for step in steps:
        copy, kept = step["copy"].relative_to(root), step["kept"].relative_to(root)
        if "refused" in step:
            print(f"LEAVE {copy}: {step['refused']}")
            continue
        print(f"KEEP {kept}\n  DELETE {copy}")
        for sidecar, relative in step["relink"]:
            print(f"  LINK {sidecar.relative_to(root)} -> audio {relative}")
    if args.apply:
        apply(steps)
        print("applied")
    else:
        print("dry run: nothing changed (--apply to do it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
