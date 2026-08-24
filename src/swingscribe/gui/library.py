"""Track identity, discovery, stem availability, and remembered UI state.

The GUI never invents its own notion of a track. A track *is* its audio bytes,
identified by the same sha256 prefix ingest uses for its normalized wav, so the
GUI and the CLI always agree about which cached artifacts belong to which file.

Heavy imports stay inside functions: this module must import without the ml
dependency group (CLAUDE.md), which CI never installs.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from swingscribe.config import Config
from swingscribe.model import Document
from swingscribe.stages.separate import stems_dir

# What the track picker will list. Anything ffmpeg can decode really works, but
# an unfiltered directory listing of someone's music folder is not a UI.
AUDIO_SUFFIXES = frozenset(
    {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
)

# SwingScribe writes its ear tests and auditions next to the source file, so a
# working directory fills up with "<tune>.ab.wav", "<tune>.other.wav" and so
# on. They are wavs, so a suffix filter alone lists them all — and opening the
# A/B mix of a track as if it were a track is never what anyone meant.
DERIVED_MARKERS = frozenset(
    {"ab", "click", "mix", "drums", "bass", "other", "vocals", "guitar", "piano"}
)

DIGEST_CHARS = 16  # matches stages/ingest.py and stages/separate.py


def is_derived_output(path: Path) -> bool:
    """True for a wav this tool wrote itself, e.g. "Blues.other.wav"."""
    if path.suffix.lower() != ".wav":
        return False
    return Path(path.stem).suffix.lstrip(".").lower() in DERIVED_MARKERS


def file_digest(path: str | Path) -> str:
    """The identity of an audio file: the prefix of the sha256 of its bytes.

    Deliberately the same construction ingest uses to name its normalized wav,
    so a track id maps straight onto the existing cache layout.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:DIGEST_CHARS]


def library_dir(config: Config) -> Path:
    """The directory the track picker lists. Never escapes to the whole disk."""
    configured = config.gui.library_dir
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def list_drives() -> list[str]:
    """Windows drive letters that exist, for the folder browser's root level.

    Windows-only, matching the rest of this project (CLAUDE.md). A single-drive
    machine still benefits: it's how the browser gets back to "Computer" after
    navigating down into a folder with no further parent.
    """
    import string

    return [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]


def browse(path: str | Path | None, config: Config) -> dict[str, Any]:
    """Subdirectories and audio files at `path`, for the folder browser.

    Deliberately NOT confined to library_dir — that restriction is what this
    feature removes. It is not a new privilege boundary: the picker's "paste a
    full path" box already opened any file the OS user can read, and the
    server only ever binds to 127.0.0.1 (GuiConfig). Browsing just makes that
    existing reach navigable instead of requiring a typed path.

    `path=None` starts at library_dir. A permission error on an individual
    entry is skipped rather than failing the whole listing — one locked-down
    subfolder should not block browsing its siblings.
    """
    root = Path(path).expanduser().resolve() if path else library_dir(config)
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    try:
        entries = list(root.iterdir())
    except PermissionError:
        entries = []
    for p in entries:
        if p.name.startswith("."):
            continue
        try:
            if p.is_dir():
                dirs.append({"name": p.name, "path": str(p)})
            elif p.suffix.lower() in AUDIO_SUFFIXES and not is_derived_output(p):
                files.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
        except OSError:
            continue  # unreadable entry (permissions, broken junction) — skip it, not the listing

    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    parent = root.parent
    return {
        "path": str(root),
        "parent": None if parent == root else str(parent),  # a drive root is its own parent
        "dirs": dirs,
        "files": files,
        "drives": list_drives(),
    }


def list_tracks(config: Config) -> list[dict[str, Any]]:
    """Audio files in the library directory, newest first.

    Shallow on purpose — a recursive walk of a music library is slow and the
    result is unnavigable. Point gui.library_dir at the folder you're working in.
    """
    root = library_dir(config)
    if not root.is_dir():
        return []
    found = [
        p
        for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES and not is_derived_output(p)
    ]
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "path": str(p), "size": p.stat().st_size, "id": None} for p in found]


def ingested_document(audio_path: str | Path, config: Config) -> Document:
    """Run (or reuse) ingest alone. Seconds at worst, instant when cached.

    Screens 1 and 2 need only this: the normalized wav to draw and play. It
    deliberately does NOT touch separation, so a track opens immediately even
    when its stems represent thirteen minutes of CPU nobody has spent yet.
    """
    from swingscribe import pipeline
    from swingscribe.stages import ingest

    return pipeline.run(audio_path, config, stages=[("ingest", ingest.run)])


def stem_digest(document: Document) -> str:
    """The digest separate.py keys its stem directory by — of the *ingested*
    wav, not the original file. Two different encodes of the same master
    normalize to the same wav and legitimately share stems."""
    if document.audio is None:
        raise ValueError("stem_digest requires ingest to have run")
    return file_digest(document.audio.path)


def available_stems(document: Document, config: Config, model: str) -> dict[str, str]:
    """Stems already on disk for this track+model, without running anything.

    This is what lets the audition screen say "htdemucs_ft is ready, htdemucs_6s
    is thirteen minutes away" before you commit to either.
    """
    out_dir = stems_dir(config.cache_dir, stem_digest(document), model)
    if not out_dir.is_dir():
        return {}
    return {p.stem: str(p) for p in sorted(out_dir.glob("*.wav"))}


def model_status(document: Document, config: Config) -> list[dict[str, Any]]:
    """Per-model separation status for the model picker."""
    status = []
    for model in config.gui.models:
        stems = available_stems(document, config, model)
        status.append({"model": model, "ready": bool(stems), "stems": sorted(stems)})
    return status


# ── Remembered per-track settings ───────────────────────────────────────────
# These live NEXT TO THE AUDIO as "<track>.swingscribe.json", not under the
# cache dir, and the distinction is deliberate: the cache holds derived data
# that must stay safely deletable, while a span, a stem choice and a downbeat
# are human judgements that took listening to arrive at. Clearing five
# gigabytes of stems should never cost you those. It also matches where every
# other output already goes — `ab`, `audition` and `click` all write beside
# the input.
#
# The recents *index* does stay in the cache: it is genuinely disposable, and
# losing it only means the list rebuilds as you open tracks again.

SETTINGS_SUFFIX = ".swingscribe.json"


def settings_path(audio_path: str | Path) -> Path:
    """Where this track's settings live: beside the audio, plainly named."""
    source = Path(audio_path)
    return source.with_name(source.name + SETTINGS_SUFFIX)


def _legacy_path(config: Config, track_id: str) -> Path:
    """Where settings lived before they moved out of the cache."""
    return Path(config.cache_dir) / "gui" / f"{track_id}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_settings(audio_path: str | Path, config: Config, track_id: str) -> dict[str, Any]:
    """This track's settings, migrating a pre-move sidecar if one exists."""
    settings = _read_json(settings_path(audio_path))
    if settings:
        return settings
    legacy = _read_json(_legacy_path(config, track_id))
    if legacy:
        # Bring it forward silently; the old copy is left alone so an older
        # build of the app keeps working against the same track.
        legacy.pop("path", None)
        legacy.pop("opened_at", None)
        save_settings(audio_path, legacy, config)
        return legacy
    return {}


def save_settings(audio_path: str | Path, settings: dict[str, Any], config: Config) -> Path:
    """Merge and write, falling back to the cache dir if the audio's folder is
    not writable (a read-only library, a mounted share). Returns where it went,
    so the UI can say."""
    path = settings_path(audio_path)
    merged = _read_json(path) | settings
    merged["file"] = Path(audio_path).name  # so the file is identifiable on sight
    payload = json.dumps(merged, indent=2, sort_keys=True)
    try:
        path.write_text(payload, encoding="utf-8")
        return path
    except OSError:
        fallback = _legacy_path(config, file_digest(audio_path))
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(payload, encoding="utf-8")
        return fallback


# ── Recents index (disposable) ──────────────────────────────────────────────


def _recents_path(config: Config) -> Path:
    return Path(config.cache_dir) / "gui" / "recents.json"


def remember_open(
    config: Config, track_id: str, audio_path: str | Path, when: float | None = None
) -> None:
    index = _read_json(_recents_path(config))
    index[track_id] = {
        "path": str(audio_path),
        "opened_at": time.time() if when is None else when,
    }
    path = _recents_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def remembered_path(config: Config, track_id: str) -> str | None:
    """The audio a track id refers to, for recovering after a server restart."""
    entry = _read_json(_recents_path(config)).get(track_id)
    return entry.get("path") if isinstance(entry, dict) else None


def recent_tracks(config: Config) -> list[dict[str, Any]]:
    """Tracks seen before, most recently opened first.

    Entries whose audio has moved or been deleted are dropped silently — the
    file on disk is the source of truth, never the index.
    """
    entries = []
    for track_id, record in _read_json(_recents_path(config)).items():
        source = record.get("path") if isinstance(record, dict) else None
        if not source or not Path(source).is_file():
            continue
        settings = load_settings(source, config, track_id)
        entries.append(
            {
                "id": track_id,
                "path": source,
                "name": Path(source).name,
                "opened_at": record.get("opened_at", 0),
                "stem": settings.get("stem"),
                "model": settings.get("model"),
                "region": settings.get("region"),
            }
        )
    # Name breaks ties: the clock's resolution is coarse enough on Windows that
    # two tracks opened in quick succession can share a timestamp, and an
    # arbitrary order there makes the list look like it shuffles itself.
    entries.sort(key=lambda e: (-e["opened_at"], e["name"]))
    return entries
