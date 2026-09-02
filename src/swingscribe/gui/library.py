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
from swingscribe.gui import ground_truth
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
    scores: list[dict[str, Any]] = []
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
            elif ground_truth.is_score(p):
                # Listed alongside, not instead: picking a hand transcription
                # for the review screen is the same navigation problem as
                # picking a track, so it reuses this browser rather than
                # growing a second one.
                scores.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
        except OSError:
            continue  # unreadable entry (permissions, broken junction) — skip it, not the listing

    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    scores.sort(key=lambda f: f["name"].lower())
    parent = root.parent
    return {
        "path": str(root),
        "parent": None if parent == root else str(parent),  # a drive root is its own parent
        "dirs": dirs,
        "files": files,
        "scores": scores,
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


# Stems the separator does not produce, but that a listener can ask for: the
# SUM of two it does. Demucs assigns each moment of audio to exactly one
# source, so an instrument it cannot place consistently is not attenuated
# across the stems — it is switched between them, leaving DIGITAL SILENCE in
# whichever one it left. On Miles Davis' Oleo (melid 320) the muted trumpet is
# routed to `vocals` for 29.8% of the solo, and the `other` stem the sidecar
# names is bit-zero there; the energy gate correctly drops those frames and
# half the solo never reaches the piano roll. Summing the two puts the horn
# back in one place: note F1 0.497 -> 0.824, recall 0.366 -> 0.848.
#
# It is not a default. Measured over every horn track in benchmark/, Oleo is
# the only one that needs it — every other reads <=3.8% silence and a
# vocals/other energy ratio <=0.18 against Oleo's 0.81 — and the sum carries
# the OTHER stem's bleed with it, so it costs precision wherever the
# separation was already clean. Offer it; do not select it.
#
# `other+vocals+guitar+piano` is the mix minus drums and bass: everything
# Demucs could have filed a horn under, summed. It exists because the routing
# failures found on 2026-09-01 (D23) were all "the horn is in a stem nobody
# looked in", and the sum holds the horn wherever it went, at the price of
# every melodic stem's bleed. Six-stem models only.
COMBINED_STEMS = ("other+vocals", "other+vocals+guitar+piano")

COMBINED_SEPARATOR = "+"


def combinable_stems(stems: dict[str, str]) -> list[str]:
    """Which COMBINED_STEMS every part of is on disk for this track+model."""
    return [
        name
        for name in COMBINED_STEMS
        if all(part in stems for part in name.split(COMBINED_SEPARATOR))
    ]


def selectable_stems(document: Document, config: Config, model: str) -> list[str]:
    """What the stem menu offers: what was separated, plus what can be summed."""
    stems = available_stems(document, config, model)
    return sorted(set(stems) | set(combinable_stems(stems)))


def resolve_stem(document: Document, config: Config, model: str, stem: str) -> str | None:
    """Path to `stem`'s audio, summing its parts when it names a combination.

    A separated stem resolves to exactly the path `available_stems` gives, so
    every cache key computed through here is unchanged for the tracks already
    reviewed. A combination is written ONCE, beside the stems it is made of and
    keyed by the same content digest, so it is as safely deletable as they are
    and `review_key`'s stem hash sees its real bytes rather than a name.
    """
    stems = available_stems(document, config, model)
    if stem in stems:
        return stems[stem]
    parts = stem.split(COMBINED_SEPARATOR)
    if len(parts) < 2 or not all(part in stems for part in parts):
        return None
    out = Path(stems[parts[0]]).with_name(f"{stem}.wav")
    if not out.is_file():
        _write_stem_sum([stems[part] for part in parts], out)
    return str(out)


# A stem is "silent" below this RMS. Demucs writes true digital zero where it
# has moved a source elsewhere, so this only has to clear the noise floor of a
# stem that IS carrying something quiet.
SILENT_RMS = 1e-4

# Fraction of a span the chosen stem may go silent for before we stop believing
# it holds the soloist. Measured over every horn track in benchmark/: Oleo
# reads 0.298 and every other track <=0.038, so 0.10 sits in a wide gap rather
# than on a tuned edge. It is deliberately NOT sensitive — this decides whether
# to consult a second stem at all, not how to transcribe.
DROPOUT_LIMIT = 0.10


def stem_dropout(path: str | Path, region: tuple[float, float] | None = None) -> float:
    """Fraction of `region` this stem is digitally silent for, by 1-second bins.

    Reference-free and cheap — no CREPE, no model — which is the whole point:
    it answers "is the soloist even in here?" for a track nobody has annotated.
    """
    import numpy as np
    import soundfile

    info = soundfile.info(str(path))
    lo = 0.0 if region is None else max(0.0, region[0])
    hi = info.duration if region is None or region[1] is None else min(info.duration, region[1])
    if hi - lo < 1.0:
        return 0.0
    data, rate = soundfile.read(
        str(path),
        dtype="float32",
        always_2d=True,
        start=int(lo * info.samplerate),
        stop=int(hi * info.samplerate),
    )
    mono = data.mean(axis=1)
    bins = max(1, len(mono) // rate)
    rms = np.sqrt(
        np.stack([mono[i * rate : (i + 1) * rate] ** 2 for i in range(bins)]).mean(axis=1)
    )
    return float((rms < SILENT_RMS).mean())


def choose_stem(
    document: Document,
    config: Config,
    model: str,
    region: tuple[float, float] | None = None,
    preferred: str = "other",
) -> tuple[str, dict[str, float]]:
    """The stem to transcribe, and what the choice was made on.

    Demucs switches a source it cannot place between stems rather than
    attenuating it across them, so `other` going quiet is not "the horn is
    soft" — it is "the horn is in a different file". When the preferred stem
    drops out over a span and summing it with a partner recovers the audio,
    the sum is the honest choice.

    Reference-free ON PURPOSE. Picking whichever stem scores better against the
    hand annotation would report a best-of-two as if it were the transcriber's
    own result, and would not generalise to a track with no annotation at all —
    which is every track a user brings. This looks only at the audio.
    """
    stems = available_stems(document, config, model)
    report: dict[str, float] = {}
    if preferred not in stems:
        return preferred, report
    report[preferred] = stem_dropout(stems[preferred], region)
    if report[preferred] <= DROPOUT_LIMIT:
        return preferred, report
    for name in combinable_stems(stems):
        parts = name.split(COMBINED_SEPARATOR)
        if preferred not in parts:
            continue
        merged = resolve_stem(document, config, model, name)
        if merged is None:
            continue
        report[name] = stem_dropout(merged, region)
        if report[name] < report[preferred]:
            return name, report
    return preferred, report


def _write_stem_sum(sources: list[str], out: Path) -> None:
    """Sum several stems sample-for-sample into one wav.

    Demucs' stems are a decomposition of the same timeline at the same rate, so
    this is addition and nothing else — no resampling, no normalisation. The
    sum can exceed 1.0 where two sources are loud together; that is left alone
    because everything downstream reads float samples and rescaling would move
    the energy gate's reference against the music.
    """
    import soundfile

    data = None
    rate = None
    for path in sources:
        block, block_rate = soundfile.read(path, dtype="float32", always_2d=True)
        if data is None:
            data, rate = block, block_rate
            continue
        if block_rate != rate:
            raise ValueError(f"{path} is {block_rate} Hz, expected {rate}")
        length = min(len(data), len(block))
        data = data[:length] + block[:length]
    tmp = out.with_suffix(".partial.wav")
    # FLOAT, not the default 16-bit PCM: two loud sources sum past 1.0, and
    # PCM would clip exactly the peaks the horn is loudest in.
    soundfile.write(tmp, data, rate, subtype="FLOAT")
    tmp.replace(out)  # never leave a half-written stem where a reader can find it


def model_status(document: Document, config: Config) -> list[dict[str, Any]]:
    """Per-model separation status for the model picker.

    `ready` means the model's FULL set of stems is on disk. A partial set is
    not ready, and says what it is missing: CLAUDE.md's own advice is to copy
    ONE stem across between cache directories rather than re-separate, and a
    directory holding that one stem read as "Separated — other" to the
    picker, which then hid the Separate button and offered a stem menu of
    one. Crazy Rhythm's tenor was in `guitar`, and the listener could not
    get there. The stems that ARE present stay listed, because
    `resolve_stem` and run_eval legitimately use a lone copied stem.
    """
    from swingscribe.stages.separate import missing_stems

    status = []
    for model in config.gui.models:
        stems = available_stems(document, config, model)
        missing = missing_stems(model, stems) if stems else []
        status.append(
            {
                "model": model,
                "ready": bool(stems) and not missing,
                "stems": sorted(set(stems) | set(combinable_stems(stems))),
                "missing": missing,
            }
        )
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
