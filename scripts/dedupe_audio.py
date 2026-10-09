"""Find byte-identical recordings and propose keeping one, linking the rest.

    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark             (dry run)
    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark --apply     (not yet)

PREPARED, NOT RUN: the listener wants to review linked sidecars before any
duplicate audio goes (docs/multi-horn-handoff.md). Nothing is changed unless
`--apply` is given, and the hand-off says when that is.

The library holds copies of one recording in two folders (benchmark/
Multi-Horn/Open-Sesame.m4a and Transcriptions_Other/Open-Sesame-...m4a, say).
They are one recording -- one digest, one cache -- with a sidecar each. For
every group of identical files this keeps ONE -- the ORIGINAL, the copy
created first (a copy made later has a later creation time even where the
copy kept the modification time), else the first by path, unless
`--keep-in` names a folder -- and, for each other copy:

1. its own sidecar becomes a LINKED take naming the kept file (LINK), and
   every linked take ANYWHERE under the root that names the copy is
   pointed at the kept file instead (REPOINT; `gui/library.py`, takes).
   A sidecar's name, its folder and everything else in it stay exactly as
   they are, so its harness key (the sidecar's path) and every pin keyed
   on it do not move, and its caches are the kept file's already;
2. the copy is deleted.

A copy is decided by its SIDECARS, never by its name: a sidecar carries
the solo's identity (Curtis_Fuller_Blue_Train and Lee_Morgan_Blue_Train are
one recording and two solos, each keyed by its own sidecar), so a copy with
one becomes a linked take whatever it is called. Only a copy with NO
sidecar is judged by name, and LEFT whole and reported when its name says
another recording (neither name, letters and digits only, begins the
other: Coleman-Hawkins-Ballade.m4a beside Charlie-Parker-Ballade.m4a, one
download under two players, is to be checked by ear) or a page is paired
with it by name (a PDF or MusicXML of its base name beside it or in
`musicxml/`). A copy whose sidecars cannot be rewritten (an unreadable
sidecar) is left whole too. Hashing reads every audio file once.
"""

import argparse
import hashlib
import json
import re
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


def created(path: Path) -> float | None:
    """When the file was CREATED, where the platform says: a copy is created
    when it is made, whatever modification time it carried over. Windows'
    st_ctime is the creation time; elsewhere only st_birthtime is."""
    stat = path.stat()
    birth = getattr(stat, "st_birthtime", None)
    if birth is not None:
        return float(birth)
    return float(stat.st_ctime) if sys.platform == "win32" else None


def keeper(paths: list[Path], keep_in: str | None, root: Path) -> Path:
    """The file to keep: one under `keep_in` when asked, else the one
    created first (the original), else the first by path."""
    if keep_in:
        preferred = [p for p in paths if keep_in in p.relative_to(root).parts]
        if preferred:
            return preferred[0]
    times = {p: created(p) for p in paths}
    if all(t is not None for t in times.values()):
        return min(paths, key=lambda p: (times[p], str(p)))
    return paths[0]


def _name_key(path: Path) -> str:
    return re.sub(r"[^a-z0-9]", "", path.stem.lower())


def same_name(a: Path, b: Path) -> bool:
    """Do two file names name one recording -- one, letters and digits only,
    beginning the other ("Open_Sesame" and "Open-Sesame-copy", a download's
    suffix)? Two players' names on one file do not."""
    first, second = sorted((_name_key(a), _name_key(b)), key=len)
    return bool(first) and second.startswith(first)


PAGE_SUFFIXES = {".pdf", ".musicxml", ".mxl", ".xml", ".mscz"}


def paired_page(audio: Path) -> Path | None:
    """A transcription paired with this recording by NAME -- beside it, or
    in the `musicxml/` folder beside it, with its base name (the PDF pages'
    set pairs a recording with its page that way)."""
    for folder in (audio.parent, audio.parent / "musicxml"):
        for suffix in PAGE_SUFFIXES:
            candidate = folder / f"{audio.stem}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def unsidecared_refusal(copy: Path, kept: Path) -> str | None:
    """Why a copy with NO sidecar is left whole, or None to delete it."""
    if not same_name(copy, kept):
        return (
            "no sidecar, and its name says another recording: "
            "one file under two names? check by ear"
        )
    page = paired_page(copy)
    if page is not None:
        return f"no sidecar, and {page.name} is paired with it by name"
    return None


def sidecars(root: Path) -> list[Path]:
    """Every sidecar under `root` outside hidden folders."""
    from swingscribe.gui import library

    return sorted(
        p
        for p in root.rglob(f"*{library.SETTINGS_SUFFIX}")
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def sidecars_of(audio: Path, every: list[Path]) -> list[tuple[Path, bool]]:
    """Every sidecar about `audio`, as (sidecar, linked): its own, and every
    linked take anywhere in `every` that names it."""
    from swingscribe.gui import library

    found = []
    for sidecar in every:
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            if library._norm(library.audio_of(sidecar, data)) == library._norm(audio):
                found.append((sidecar, bool(data.get("audio"))))
        except (OSError, ValueError):
            if library._norm(library.settings_path(audio)) == library._norm(sidecar):
                found.append((sidecar, False))  # unreadable: refused below
    return found


def plan(root: Path, keep_in: str | None) -> list[dict]:
    from swingscribe.gui import library

    every = sidecars(root)
    steps = []
    for paths in groups(root):
        kept = keeper(paths, keep_in, root)
        for copy in paths:
            if copy == kept:
                continue
            about = sidecars_of(copy, every)
            if not about:
                # No sidecar carries this copy's identity, so its NAME is all
                # there is: a different name, or a page paired with it by
                # name, is the listener's to look at.
                why = unsidecared_refusal(copy, kept)
                if why:
                    steps.append({"copy": copy, "kept": kept, "refused": why})
                    continue
            relinks = []
            for sidecar, linked in about:
                try:
                    json.loads(sidecar.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    relinks = None
                    steps.append({"copy": copy, "kept": kept, "refused": f"{sidecar}: {exc}"})
                    break
                relinks.append((sidecar, library._relative_audio(sidecar, kept), linked))
            if relinks is not None:
                steps.append({"copy": copy, "kept": kept, "relink": relinks})
    return steps


def apply(steps: list[dict]) -> None:
    for step in steps:
        if "refused" in step:
            continue
        for sidecar, relative, _linked in step["relink"]:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["audio"] = relative
            data["file"] = step["kept"].name
            sidecar.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        step["copy"].unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", type=Path, help="the folder to search (e.g. benchmark)")
    parser.add_argument(
        "--keep-in",
        help="keep the copy under this folder name when there is one (default: the original)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="rewrite the sidecars and delete the copies"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    steps = plan(root, args.keep_in)
    if not steps:
        print("no byte-identical recordings")
        return 0

    def shown(path: Path) -> str:
        return path.relative_to(root).as_posix()

    for step in steps:
        copy, kept = shown(step["copy"]), shown(step["kept"])
        if "refused" in step:
            print(f"LEAVE {copy} (same bytes as {kept}): {step['refused']}")
            continue
        print(f"KEEP {kept}\n  DELETE {copy}")
        for sidecar, relative, linked in step["relink"]:
            verb = "REPOINT" if linked else "LINK"
            print(f"  {verb} {shown(sidecar)} -> audio {relative}")
    if args.apply:
        apply(steps)
        print("applied")
    else:
        print("dry run: nothing changed (--apply to do it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
