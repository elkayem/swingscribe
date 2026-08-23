"""Track identity, discovery, stem availability, and remembered UI state.

The GUI never invents its own notion of a track. A track *is* its audio bytes,
identified by the same sha256 prefix ingest uses for its normalized wav, so the
GUI and the CLI always agree about which cached artifacts belong to which file.

Heavy imports stay inside functions: this module must import without the ml
dependency group (CLAUDE.md), which CI never installs.
"""

import hashlib
import json
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


# ── Remembered per-track UI state ───────────────────────────────────────────
# A sidecar under the cache dir, keyed by track id. Small and disposable: if it
# is deleted the GUI simply forgets where you were, and nothing expensive is
# lost. It holds UI state only — never anything a cache key depends on.


def _state_path(config: Config, track_id: str) -> Path:
    return Path(config.cache_dir) / "gui" / f"{track_id}.json"


def load_state(config: Config, track_id: str) -> dict[str, Any]:
    path = _state_path(config, track_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(config: Config, track_id: str, state: dict[str, Any]) -> None:
    path = _state_path(config, track_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = load_state(config, track_id) | state
    path.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")


def recent_tracks(config: Config) -> list[dict[str, Any]]:
    """Tracks the GUI has seen before, most recently opened first.

    Reconstructed from the state sidecars rather than a separate index, so
    there is only one thing to keep consistent. Entries whose audio has moved
    or been deleted are dropped silently — the file is the source of truth.
    """
    gui_dir = Path(config.cache_dir) / "gui"
    if not gui_dir.is_dir():
        return []
    entries = []
    for path in gui_dir.glob("*.json"):
        state = load_state(config, path.stem)
        source = state.get("path")
        if not source or not Path(source).is_file():
            continue
        entries.append(
            {
                "id": path.stem,
                "path": source,
                "name": Path(source).name,
                "opened_at": state.get("opened_at", 0),
                "stem": state.get("stem"),
                "model": state.get("model"),
                "region": state.get("region"),
            }
        )
    entries.sort(key=lambda e: e["opened_at"], reverse=True)
    return entries
