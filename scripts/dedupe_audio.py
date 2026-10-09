"""Find byte-identical recordings and propose keeping one, linking the rest.

    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark             (dry run)
    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark --apply     (Recycle Bin)
    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py benchmark --apply --trash D:\\dedupe-trash
    .venv\\Scripts\\python.exe scripts\\dedupe_audio.py --undo benchmark\\.dedupe\\manifest-....json

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
2. the copy goes: never deleted outright. On Windows it is sent to the
   Recycle Bin (SHFileOperationW, FOF_ALLOWUNDO), where the listener can
   empty it or restore it; with `--trash DIR` it is MOVED there instead,
   under its path relative to the root (required where there is no Recycle
   Bin).

Every change is written to a MANIFEST first (`--manifest`, default
`<root>/.dedupe/manifest-<time>.json`, a hidden folder no walk reads): each
copy, where it went, and every sidecar it rewrote WITH ITS PREVIOUS
CONTENT, step by step as each lands. `--undo MANIFEST` puts it all back --
the audio from the trash or the Recycle Bin, then each sidecar's previous
content, unless the sidecar was edited since (then it is reported and left
as it is; its previous content is in the manifest).

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
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def audio_files(root: Path) -> list[Path]:
    from swingscribe.gui import library

    return library.audio_files(root, recursive=True)


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

    return [
        sidecar
        for _key, sidecar, _audio in library.discover(root)
        if not any(part.startswith(".") for part in sidecar.relative_to(root).parts)
    ]


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


MANIFEST_VERSION = 1


def default_manifest(root: Path) -> Path:
    return root / ".dedupe" / f"manifest-{datetime.now():%Y%m%d-%H%M%S}.json"


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(path)


def recycle(path: Path) -> None:
    """Send a file to the Windows Recycle Bin (SHFileOperationW with
    FOF_ALLOWUNDO), silently. Raises OSError if it is still there."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    fo_delete = 3
    flags = 0x40 | 0x10 | 0x4 | 0x400  # ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI
    # pFrom is a list of paths ending in an empty one: two NULs.
    operation = SHFILEOPSTRUCTW(
        None, fo_delete, str(path.resolve()) + "\0", None, flags, False, None, None
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted or path.exists():
        raise OSError(f"could not send {path} to the Recycle Bin (code {result})")


RESTORE_SCRIPT = r"""
$target = $args[0]
$folder = [IO.Path]::GetDirectoryName($target)
$name = [IO.Path]::GetFileName($target)
$stem = [IO.Path]::GetFileNameWithoutExtension($target)
$shell = New-Object -ComObject Shell.Application
$bin = $shell.Namespace(10)
foreach ($item in $bin.Items()) {
  if ($item.ExtendedProperty("System.Recycle.DeletedFrom") -ne $folder) { continue }
  if ($item.Name -ne $name -and $item.Name -ne $stem) { continue }
  $shell.Namespace($folder).MoveHere($item)
  exit 0
}
exit 2
"""


def restore_recycled(path: Path) -> None:
    """Bring a file this script recycled back from the Recycle Bin to where
    it was (Shell.Application, matched by its original folder and name).
    Raises OSError when it cannot, saying how to do it by hand."""
    quoted = str(path).replace("'", "''")
    command = f"& {{ {RESTORE_SCRIPT} }} '{quoted}'"
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    for _ in range(50):  # the shell moves it back asynchronously
        if path.exists():
            return
        time.sleep(0.1)
    raise OSError(
        f"{path} is not back: restore it from the Recycle Bin by hand (right-click, Restore)"
    )


def trash_path(trash: Path, root: Path, copy: Path) -> Path:
    """Where `--trash` keeps a copy: its path under the root, kept apart from
    any earlier copy of the same name."""
    target = trash / copy.relative_to(root)
    n = 1
    while target.exists():
        target = target.with_name(f"{copy.stem}.{n}{copy.suffix}")
        n += 1
    return target


def apply(
    steps: list[dict], root: Path, manifest_path: Path, trash: Path | None = None, log=print
) -> dict:
    """Do the plan, never deleting anything: each copy to `trash`, or the
    Recycle Bin when there is none. The manifest is written before the first
    change and after every step, so an interrupted run can still be undone."""
    if not any("relink" in step for step in steps):
        log("nothing to apply: every group is left as it is")
        return {}
    if trash is None and sys.platform != "win32":
        raise SystemExit("there is no Recycle Bin here: pass --trash DIR to keep the copies")
    if trash is not None and trash.is_relative_to(root):
        inside = trash.relative_to(root).parts
        if not any(part.startswith(".") for part in inside):
            # A walk would find the moved copies there and plan them again.
            raise SystemExit("--trash inside the root must be under a hidden folder (.dedupe/)")
    manifest = {
        "version": MANIFEST_VERSION,
        "root": str(root),
        "created": datetime.now().isoformat(timespec="seconds"),
        "trash": None if trash is None else str(trash),
        "steps": [],
    }
    for step in steps:
        if "refused" in step:
            continue
        sidecars = []
        for sidecar, relative, linked in step["relink"]:
            before = sidecar.read_text(encoding="utf-8")
            data = json.loads(before)
            data["audio"] = relative
            data["file"] = step["kept"].name
            sidecars.append(
                {
                    "path": str(sidecar),
                    "verb": "REPOINT" if linked else "LINK",
                    "before": before,
                    "after": json.dumps(data, indent=2, sort_keys=True),
                }
            )
        manifest["steps"].append(
            {
                "copy": str(step["copy"]),
                "kept": str(step["kept"]),
                "sidecars": sidecars,
                "went_to": None,
                "status": "planned",
            }
        )
    write_manifest(manifest_path, manifest)
    for entry in manifest["steps"]:
        copy = Path(entry["copy"])
        for sidecar in entry["sidecars"]:
            Path(sidecar["path"]).write_text(sidecar["after"], encoding="utf-8")
        try:
            if trash is not None:
                target = trash_path(trash, root, copy)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(copy), str(target))
                entry["went_to"] = str(target)
            else:
                recycle(copy)
                entry["went_to"] = "recycle-bin"
        except OSError as exc:
            # This step's sidecars go back; the steps before it stand, and the
            # manifest says which.
            for sidecar in entry["sidecars"]:
                Path(sidecar["path"]).write_text(sidecar["before"], encoding="utf-8")
            entry["status"] = f"failed: {exc}"
            write_manifest(manifest_path, manifest)
            raise SystemExit(f"stopped at {copy}: {exc} (manifest {manifest_path})") from exc
        entry["status"] = "done"
        write_manifest(manifest_path, manifest)
    log(f"manifest: {manifest_path} (undo with --undo)")
    return manifest


def undo(manifest_path: Path, log=print) -> int:
    """Put back what `apply` did, newest first: the audio from wherever it
    went, then each sidecar's previous content -- unless the sidecar was
    edited since, which is reported and left alone. Returns how many steps
    could not be fully undone."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = 0
    for entry in reversed(manifest["steps"]):
        if entry["status"] != "done":
            continue
        copy = Path(entry["copy"])
        try:
            if copy.exists():
                raise OSError(f"{copy} is already there; nothing moved back")
            if entry["went_to"] == "recycle-bin":
                restore_recycled(copy)
            else:
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(entry["went_to"], str(copy))
        except OSError as exc:
            log(f"  AUDIO {copy}: {exc}")
            problems += 1
            continue
        for sidecar in entry["sidecars"]:
            path = Path(sidecar["path"])
            now = path.read_text(encoding="utf-8") if path.is_file() else None
            if now != sidecar["after"]:
                log(f"  SIDECAR {path}: edited since the clean-up; left as it is")
                problems += 1
                continue
            path.write_text(sidecar["before"], encoding="utf-8")
        entry["status"] = "undone"
        log(f"RESTORED {copy}")
        write_manifest(manifest_path, manifest)
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", type=Path, nargs="?", help="the folder to search (e.g. benchmark)")
    parser.add_argument(
        "--keep-in",
        help="keep the copy under this folder name when there is one (default: the original)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="rewrite the sidecars and send the copies to the Recycle Bin (or --trash)",
    )
    parser.add_argument(
        "--trash", type=Path, help="move the copies here instead of the Recycle Bin"
    )
    parser.add_argument("--manifest", type=Path, help="where --apply writes its manifest")
    parser.add_argument("--undo", type=Path, metavar="MANIFEST", help="put an --apply back")
    args = parser.parse_args(argv)
    if args.undo is not None:
        problems = undo(args.undo)
        print("undone" if not problems else f"undone, {problems} step(s) need a hand (above)")
        return 1 if problems else 0
    if args.root is None:
        parser.error("a root folder is needed (or --undo MANIFEST)")
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
        trash = args.trash.resolve() if args.trash else None
        apply(steps, root, (args.manifest or default_manifest(root)).resolve(), trash)
        print("applied")
    else:
        print("dry run: nothing changed (--apply to do it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
