"""What the cache holds, per track, and how to let go of it.

Two numbers set the shape of this module. On the machine this was written on
the cache held 70 GB of stems and 8 GB of ingested wavs, against about a
hundred megabytes of everything else -- stage-output bins, reviews, peaks,
overlays. So this is a stems manager, not a general cache browser: the unit
of deletion is one stems directory (one track, one model, optionally one
span), or everything the cache holds for one track.

The hard part is naming. A stems directory is keyed by the digest of the
NORMALIZED wav, while the recents index and the ingest wav are keyed by the
digest of the source file, and nothing but a re-hash of the wav joins the
two. Three sources answer it, cheapest first: the `_source.json` marker
separate.py now writes beside the stems; the `stem_digest` the recents index
learns when a track is opened; and, for directories that predate both, one
hash of the ingest wav, whose result is written back into the recents index
so it is paid once.

What deletion never touches: the sidecar beside the audio (a span and a
downbeat are human judgements -- library.py says why they left the cache),
and the recents entry, which is how the track is found again. Nothing here
imports fastapi: the CLI's `cache` command uses it too, because the eval
harness keeps a second cache the GUI cannot see.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.stages.separate import SOURCE_MARKER, span_of_dir

# `<wav digest>-<model>` with an optional `@<start_ms>-<end_ms>` span tag
# (stages/separate.py). Anything under stems/ that does not parse is left
# alone: it is not ours to delete.
STEMS_DIR_RE = re.compile(
    r"^(?P<digest>[0-9a-f]{16})-(?P<model>[A-Za-z0-9_]+)(?:@(?P<start>\d+)-(?P<end>\d+))?$"
)
TRACK_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class InUseError(RuntimeError):
    """A separation is writing into the directory right now."""


def parse_stems_name(name: str) -> dict[str, Any] | None:
    match = STEMS_DIR_RE.match(name)
    if match is None:
        return None
    return {"digest": match["digest"], "model": match["model"], "span": span_of_dir(name)}


def dir_bytes(path: Path) -> int:
    """Bytes under `path`, following no links. Unreadable entries count as zero."""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _norm(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _is_empty_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


def _remove_tree(path: Path) -> None:
    """rmtree that survives OneDrive. It holds a handle on a directory whose
    files were just deleted, so the final rmdir fails with WinError 5
    (CLAUDE.md lists the same lock breaking `uv sync`) -- AFTER every byte
    is gone. Retry briefly; an emptied directory that still will not go is
    an empty directory, which the inventory ignores and sweeps later."""
    error: OSError | None = None
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            error = exc
            if not path.exists():
                return
            time.sleep(0.15 * (attempt + 1))
    if _is_empty_dir(path):
        return
    assert error is not None
    raise error


def busy_targets(jobs: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(source path, model) of every separation that is queued or running,
    from JobRunner.all() snapshots. A directory one of these is writing into
    must not be deleted out from under it."""
    return {
        (_norm(job["path"]), job["model"])
        for job in jobs
        if job.get("kind") == "separate" and job.get("state") in ("queued", "running")
    }


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[: library.DIGEST_CHARS]


def _read_marker(stems: Path) -> dict[str, Any]:
    try:
        data = json.loads((stems / SOURCE_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ingest_wavs(cache: Path) -> dict[str, list[Path]]:
    """Track id -> its normalized wav(s) under audio/ (`<track id>-<rate>.wav`)."""
    out: dict[str, list[Path]] = {}
    audio = cache / "audio"
    if not audio.is_dir():
        return out
    for wav in sorted(audio.glob("*.wav")):
        track_id = wav.name.split("-", 1)[0]
        if TRACK_ID_RE.match(track_id):
            out.setdefault(track_id, []).append(wav)
    return out


def _wav_digest_memo_path(cache: Path) -> Path:
    return cache / "gui" / "wav-digests.json"


def _digest_index(
    config: Config, recents: dict[str, dict[str, Any]], wavs: dict[str, list[Path]]
) -> dict[str, str]:
    """Wav digest -> track id, for every ingest wav in the cache.

    Hashing a wav is the one slow step in this module, so each answer is
    paid for once: a track the recents index knows gets `stem_digest`
    written into its entry, and every other wav (the eval harness ingests
    tracks the GUI never opened) goes into `gui/wav-digests.json`, keyed by
    name, size and mtime. Both are disposable -- lose them and the next
    inventory simply hashes again.
    """
    cache = Path(config.cache_dir)
    memo_path = _wav_digest_memo_path(cache)
    memo = library._read_json(memo_path)
    memo_changed = False
    by_digest: dict[str, str] = {}
    for track_id, paths in wavs.items():
        record = recents.get(track_id)
        digest = record.get("stem_digest") if record else None
        if not digest:
            wav = paths[0]
            try:
                stat = wav.stat()
                cached = memo.get(wav.name)
                if (
                    isinstance(cached, dict)
                    and cached.get("size") == stat.st_size
                    and cached.get("mtime") == stat.st_mtime
                ):
                    digest = cached["digest"]
                else:
                    digest = _hash_file(wav)
                    memo[wav.name] = {
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "digest": digest,
                    }
                    memo_changed = True
            except OSError:
                continue
            if record is not None:
                library.remember_open(
                    config, track_id, record.get("path", ""), record.get("opened_at"), digest
                )
        by_digest[digest] = track_id
    # A remembered track whose wav is gone still names its stems directories.
    for track_id, record in recents.items():
        digest = record.get("stem_digest")
        if digest and digest not in by_digest:
            by_digest[digest] = track_id
    if memo_changed:
        memo_path.parent.mkdir(parents=True, exist_ok=True)
        memo_path.write_text(json.dumps(memo, indent=2, sort_keys=True), encoding="utf-8")
    return by_digest


def inventory(config: Config, busy: set[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Every stems directory and ingest wav in the cache, grouped by track.

    Tracks are sorted largest first, which is the order anyone reclaiming
    disk wants. `orphans` are stems directories no track can be named for:
    still listed with their digest and size, still deletable.
    """
    busy = busy or set()
    cache = Path(config.cache_dir)
    recents = library.recent_index(config)
    wavs = _ingest_wavs(cache)
    by_digest = _digest_index(config, recents, wavs)

    tracks: dict[str, dict[str, Any]] = {}

    def track_entry(track_id: str, name: str | None, path: str | None) -> dict[str, Any]:
        entry = tracks.get(track_id)
        if entry is None:
            record = recents.get(track_id, {})
            source = record.get("path") or path
            entry = {
                "id": track_id,
                "name": Path(source).name if source else (name or track_id),
                "path": source,
                "known": track_id in recents,
                # False when the audio has moved since: the stems are for a
                # file the listener no longer has under that name.
                "source_exists": bool(source) and Path(source).is_file(),
                "audio": [],
                "stems": [],
                "bytes": 0,
            }
            tracks[track_id] = entry
        return entry

    orphans: list[dict[str, Any]] = []
    stems_root = cache / "stems"
    if stems_root.is_dir():
        for child in sorted(stems_root.iterdir()):
            parsed = parse_stems_name(child.name)
            if parsed is None or not child.is_dir():
                continue
            if _is_empty_dir(child):
                # A delete OneDrive would not finish (see _remove_tree): the
                # bytes are gone, so it is not worth a control. Sweep it if
                # the lock has let go, and hide it either way.
                with contextlib.suppress(OSError):
                    child.rmdir()
                continue
            marker = _read_marker(child)
            track_id = marker.get("track_id") or by_digest.get(parsed["digest"])
            item = {
                "name": child.name,
                "digest": parsed["digest"],
                "model": parsed["model"],
                "span": list(parsed["span"]) if parsed["span"] else None,
                "bytes": dir_bytes(child),
                "modified": child.stat().st_mtime,
                "busy": False,
            }
            if track_id is None:
                orphans.append(item)
                continue
            entry = track_entry(track_id, marker.get("name"), marker.get("source"))
            if entry["path"] and (_norm(entry["path"]), item["model"]) in busy:
                item["busy"] = True
            entry["stems"].append(item)
            entry["bytes"] += item["bytes"]

    for track_id, paths in wavs.items():
        entry = track_entry(track_id, None, None)
        for wav in paths:
            size = wav.stat().st_size
            entry["audio"].append({"name": wav.name, "bytes": size})
            entry["bytes"] += size

    listed = sorted(tracks.values(), key=lambda t: (-t["bytes"], t["name"]))
    return {
        "cache_dir": str(cache.resolve()),
        "total_bytes": dir_bytes(cache) if cache.is_dir() else 0,
        "tracks": listed,
        "orphans": orphans,
        "orphan_bytes": sum(o["bytes"] for o in orphans),
    }


def _stems_path(config: Config, name: str) -> Path:
    """The directory `name` names, refusing anything that is not a stems
    directory directly under stems/ -- a name is request input."""
    if parse_stems_name(name) is None:
        raise ValueError(f"not a stems directory name: {name!r}")
    root = (Path(config.cache_dir) / "stems").resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError(f"not a stems directory name: {name!r}")
    if not target.is_dir():
        raise FileNotFoundError(str(target))
    return target


def delete_stems(config: Config, name: str, busy: set[tuple[str, str]] | None = None) -> int:
    """Remove one stems directory. Returns the bytes it held."""
    target = _stems_path(config, name)
    listing = inventory(config, busy)
    items = {item["name"]: item for track in listing["tracks"] for item in track["stems"]}
    item = items.get(name)
    if item is not None and item["busy"]:
        raise InUseError(f"a separation is writing to {name}")
    size = dir_bytes(target)
    _remove_tree(target)
    return size


def delete_track(
    config: Config, track_id: str, busy: set[tuple[str, str]] | None = None
) -> dict[str, Any]:
    """Remove everything the cache holds for one track: its stems directories,
    ingest wav and waveform peaks. The recents entry and the sidecar beside
    the audio are left alone. Refuses before touching anything if any of the
    track's separations is running."""
    if not TRACK_ID_RE.match(track_id):
        raise ValueError(f"not a track id: {track_id!r}")
    listing = inventory(config, busy)
    track = next((t for t in listing["tracks"] if t["id"] == track_id), None)
    if track is None:
        raise FileNotFoundError(f"nothing cached for {track_id}")
    if any(item["busy"] for item in track["stems"]):
        raise InUseError(f"a separation is running for {track['name']}")

    cache = Path(config.cache_dir)
    freed = 0
    removed: list[str] = []
    for item in track["stems"]:
        target = _stems_path(config, item["name"])
        freed += dir_bytes(target)
        _remove_tree(target)
        removed.append(item["name"])
    for wav in _ingest_wavs(cache).get(track_id, []):
        freed += wav.stat().st_size
        wav.unlink()
        removed.append(wav.name)
    for extra in [
        *(cache / "gui" / "peaks").glob(f"{track_id}-*.json"),
        cache / "gui" / f"{track_id}.json",  # pre-sidecar settings, long migrated
    ]:
        if extra.is_file():
            freed += extra.stat().st_size
            extra.unlink()
            removed.append(extra.name)
    return {"id": track_id, "name": track["name"], "freed": freed, "removed": removed}
