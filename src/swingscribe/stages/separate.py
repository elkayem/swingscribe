"""Stage 1 — Separate: 4 stems via the demucs Python API, not subprocess (plan §5, M1).

The model name comes from config so a BS-Roformer checkpoint can drop in
behind the same interface later. Stems are written as wavs under the cache
dir in a directory derived from the audio content and model name, so the
same input always lands in the same place — and because that directory is
content-addressed, a complete set of stems already sitting in it IS this
stage's output and is reused rather than recomputed.

That matters more than it looks. Stage outputs are cached under chained keys
(plan §3), so any config change upstream of this stage invalidates its cache
entry — correctly, since a different decode would need a different
separation. But a change that leaves the *audio* identical does not, and
without this check the honest answer to "you moved a beats setting" was
eleven minutes of demucs producing the bytes already on disk.

Heavy imports (torch, demucs) stay inside run(): this module must stay
importable without the ml dependency group, which CI never installs.
"""

import hashlib
import json
import time
from pathlib import Path

from swingscribe import progress
from swingscribe.config import Config
from swingscribe.device import resolve_device
from swingscribe.model import Document

Span = tuple[float, float]

# A stems directory covering only part of the track is named with its span in
# milliseconds after the model: `<digest>-<model>@<start_ms>-<end_ms>`. The
# stems inside are still FULL-LENGTH wavs, digitally silent outside the span,
# so every consumer keeps the track's own time base and nothing downstream
# knows the separation was partial. What changes is only the model's work:
# the listener selects the solo first and separates that, which is where a
# separator nine times slower than htdemucs (bsroformer_sw) becomes usable
# on a CPU — a solo is typically a third of its file.
SPAN_SEPARATOR = "@"

# Beside the stems, a note saying which track they came from. The directory
# is named by the digest of the NORMALIZED wav, which nothing but a re-hash
# of that wav can turn back into a title -- so a listing of the cache read as
# sixty hexadecimal names, and reclaiming disk meant guessing. The marker
# makes a stems directory self-describing. It is not consulted by the
# pipeline (content addressing decides reuse, as before) and a directory
# without one is still a valid separation; it is written on every separation
# and back-filled the first time an older set is reused.
SOURCE_MARKER = "_source.json"


def write_source_marker(out_dir: Path, document: Document, model: str, span: Span | None) -> Path:
    """Write SOURCE_MARKER into `out_dir`, naming the track the stems belong to.

    `track_id` is the digest of the SOURCE file's bytes -- the identity the GUI
    and the recents index use (gui/library.file_digest) -- so the storage view
    can group a directory under its track without hashing anything. Null when
    the source has moved since ingest; the name and path are still recorded.
    """
    source = Path(document.audio_path)
    track_id = None
    if source.is_file():
        track_id = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    record = {
        "source": str(source),
        "name": source.name,
        "track_id": track_id,
        "model": model,
        "span": list(span) if span is not None else None,
        "written_at": time.time(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / SOURCE_MARKER
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _span_tag(span: Span) -> str:
    return f"{int(round(span[0] * 1000))}-{int(round(span[1] * 1000))}"


def stems_dir(
    cache_dir: str | Path, audio_digest: str, model: str, span: Span | None = None
) -> Path:
    name = f"{audio_digest}-{model}"
    if span is not None:
        name += f"{SPAN_SEPARATOR}{_span_tag(span)}"
    return Path(cache_dir) / "stems" / name


def span_of_dir(path: str | Path) -> Span | None:
    """The span a stems directory covers, or None for a whole-file set."""
    name = Path(path).name
    if SPAN_SEPARATOR not in name:
        return None
    start_ms, _, end_ms = name.rsplit(SPAN_SEPARATOR, 1)[1].partition("-")
    try:
        return int(start_ms) / 1000.0, int(end_ms) / 1000.0
    except ValueError:
        return None


def covering_dirs(cache_dir: str | Path, audio_digest: str, model: str, span: Span | None):
    """Stems directories that cover `span`, most general first: the whole-file
    set, then any span set containing it. With no span, only the whole-file
    set qualifies — a partial separation must never stand in for the track."""
    whole = stems_dir(cache_dir, audio_digest, model)
    out = [whole]
    if span is None:
        return out
    prefix = f"{audio_digest}-{model}{SPAN_SEPARATOR}"
    parent = Path(cache_dir) / "stems"
    if parent.is_dir():
        for candidate in sorted(parent.iterdir()):
            if not candidate.name.startswith(prefix):
                continue
            covered = span_of_dir(candidate)
            if covered and covered[0] <= span[0] + 1e-3 and covered[1] >= span[1] - 1e-3:
                out.append(candidate)
    return out


def find_stems(
    cache_dir: str | Path, audio_digest: str, model: str, span: Span | None, sources: list[str]
) -> dict[str, str] | None:
    """A complete set of `sources` covering `span`, or None."""
    for candidate in covering_dirs(cache_dir, audio_digest, model, span):
        found = existing_stems(candidate, sources)
        if found is not None:
            return found
    return None


def _crop_to_span(audio_path: Path, span: Span, margin_s: float, out_path: Path) -> tuple[int, int]:
    """Write [span - margin, span + margin] of the track to `out_path`.
    Returns (offset_samples, total_samples) for padding the result back."""
    import soundfile

    info = soundfile.info(str(audio_path))
    rate = info.samplerate
    start = max(0, int((span[0] - margin_s) * rate))
    stop = min(info.frames, int((span[1] + margin_s) * rate))
    data, _ = soundfile.read(
        str(audio_path), dtype="float32", always_2d=True, start=start, stop=stop
    )
    soundfile.write(str(out_path), data, rate, subtype="PCM_16")
    return start, info.frames


def _pad_stem_to_track(stem_path: Path, offset: int, total: int) -> None:
    """Rewrite a cropped stem as a full-length wav: zeros, then the stem at
    `offset` samples. The pipeline's time base is the track's, always."""
    import numpy as np
    import soundfile

    data, rate = soundfile.read(str(stem_path), dtype="float32", always_2d=True)
    padded = np.zeros((total, data.shape[1]), dtype="float32")
    stop = min(total, offset + len(data))
    padded[offset:stop] = data[: stop - offset]
    soundfile.write(str(stem_path), padded, rate, subtype="PCM_16")


# What each model writes, for callers that must judge a stems directory
# WITHOUT loading the model (the GUI's model picker). `run` itself asks the
# loaded separator, which is the authority; this table only has to agree with
# it for the models the GUI offers. A model not listed here is judged by
# whatever is on disk.
KNOWN_SOURCES: dict[str, tuple[str, ...]] = {
    "htdemucs": ("drums", "bass", "other", "vocals"),
    "htdemucs_ft": ("drums", "bass", "other", "vocals"),
    "htdemucs_6s": ("drums", "bass", "other", "vocals", "guitar", "piano"),
    "bsroformer_sw": ("drums", "bass", "other", "vocals", "guitar", "piano"),
}

# Models served by python-audio-separator (the `roformer` dependency group)
# rather than demucs: our model name -> the zoo's checkpoint filename. The
# plan's "a BS-Roformer checkpoint can drop in behind the same interface"
# clause, cashed in: BS-Roformer-SW routed EVERY benchmark horn to `other`
# where htdemucs_6s had filed five under guitar/vocals, and read subset mean
# pitch F1 0.878 -> 0.903 (docs/separation-research.md). It costs ~9x
# htdemucs' CPU time, which is why it is offered and not the default.
ROFORMER_MODELS: dict[str, str] = {"bsroformer_sw": "BS-Roformer-SW.ckpt"}

# audio-separator names its outputs "<input>_(Stem)_<model>.wav"; these are
# the stem labels BS-Roformer-SW writes, mapped onto the names the rest of
# the pipeline expects (demucs' lower-case set).
_ROFORMER_STEM_NAMES = {
    "vocals": "vocals",
    "drums": "drums",
    "bass": "bass",
    "other": "other",
    "guitar": "guitar",
    "piano": "piano",
}


def roformer_stem_name(output_path: str | Path) -> str | None:
    """Our stem name for one audio-separator output file, or None if the
    parenthesised label is not one this pipeline knows."""
    import re

    match = re.search(r"\(([^)]+)\)", Path(output_path).name)
    if not match:
        return None
    return _ROFORMER_STEM_NAMES.get(match.group(1).strip().lower())


def _roformer_separate(audio_path: Path, checkpoint: str, out_dir: Path) -> dict[str, str]:
    """Write `checkpoint`'s stems for `audio_path` into `out_dir` as
    `<stem>.wav`, through python-audio-separator. Heavy import inside: the
    `roformer` group is optional and CI never installs it."""
    import shutil

    from audio_separator.separator import Separator

    work = out_dir / "_separating"
    work.mkdir(parents=True, exist_ok=True)
    separator = Separator(output_dir=str(work), output_format="WAV", log_level=30)
    separator.load_model(model_filename=checkpoint)
    outputs = separator.separate(str(audio_path))
    stems: dict[str, str] = {}
    for produced in outputs:
        path = Path(produced)
        if not path.is_absolute():
            path = work / path
        name = roformer_stem_name(path)
        if name is None:
            path.unlink(missing_ok=True)
            continue
        target = out_dir / f"{name}.wav"
        shutil.move(str(path), str(target))
        stems[name] = str(target)
    shutil.rmtree(work, ignore_errors=True)
    return stems


def missing_stems(model: str, present: set[str] | dict[str, str]) -> list[str]:
    """Stems this model produces that are not on disk. Empty means complete
    (or an unknown model, which cannot be judged)."""
    return [name for name in KNOWN_SOURCES.get(model, ()) if name not in present]


def existing_stems(out_dir: Path, sources: list[str]) -> dict[str, str] | None:
    """Stems already on disk for this audio+model, or None if any is missing.

    All-or-nothing against the model's own source list, deliberately: a
    directory holding three of four wavs is a separation that died partway
    through, and half a separation reused is a stage that silently returns
    less than it promises. Pure and path-only so it is testable without demucs.
    """
    if not out_dir.is_dir():
        return None
    found = {name: out_dir / f"{name}.wav" for name in sources}
    if not found or not all(path.is_file() and path.stat().st_size > 0 for path in found.values()):
        return None
    return {name: str(path) for name, path in found.items()}


def _progress_callback():
    """Adapt demucs' callback dict to a swingscribe progress fraction.

    demucs hands us {"models", "model_idx_in_bag", "segment_offset",
    "audio_length", "state", ...} as it walks the bag of models, each over the
    whole track in segments. So overall progress is the model we're on plus
    how far through the audio that model has got, over the bag size.

    Clamped monotonic: the callback fires on both segment start and segment
    end, and with jobs>0 segments can complete out of order, so the raw
    fraction is not guaranteed to increase. A progress bar that walks backwards
    reads as a bug even when the underlying work is fine.
    """
    highest = 0.0

    def callback(data: dict) -> None:
        nonlocal highest
        models = data.get("models") or 1
        audio_length = data.get("audio_length") or 0
        within = (data.get("segment_offset", 0) / audio_length) if audio_length else 0.0
        fraction = (data.get("model_idx_in_bag", 0) + within) / models
        highest = max(highest, min(1.0, fraction))
        progress.report("separate", highest, f"separating ({highest:.0%})")

    return callback


def run(document: Document, config: Config) -> Document:
    if document.audio is None:
        raise ValueError("separate requires ingest to have run first (document.audio is None)")

    audio_path = Path(document.audio.path)
    digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()[:16]
    model = config.separate.model
    span = config.separate.span
    out_dir = stems_dir(config.cache_dir, digest, model, span)

    def reuse(sources: list[str]) -> Document | None:
        existing = find_stems(config.cache_dir, digest, model, span, sources)
        if existing is None:
            return None
        progress.report("separate", 1.0, "stems already on disk", cached=True)
        where = Path(next(iter(existing.values()))).parent
        print(f"separate: reusing {len(existing)} stems in {where}")
        if not (where / SOURCE_MARKER).is_file():
            write_source_marker(where, document, model, span_of_dir(where))
        return document.model_copy(update={"stems": existing})

    def source_audio() -> tuple[Path, tuple[int, int] | None]:
        """What the model reads: the track, or its span cropped to a temp wav
        beside the stems, with the (offset, total) that pads the result back."""
        if span is None:
            return audio_path, None
        out_dir.mkdir(parents=True, exist_ok=True)
        cropped = out_dir / "_span_input.wav"
        placement = _crop_to_span(audio_path, span, config.separate.span_margin_s, cropped)
        print(
            f"separate: span {span[0]:.1f}-{span[1]:.1f}s (+{config.separate.span_margin_s:.0f}s)"
        )
        return cropped, placement

    if model in ROFORMER_MODELS:
        # A Roformer checkpoint knows its sources from KNOWN_SOURCES, so the
        # reuse check needs no model load — and no torch import either.
        sources = list(KNOWN_SOURCES[model])
        if (reused := reuse(sources)) is not None:
            return reused
        checkpoint = ROFORMER_MODELS[model]
        print(f"separate: model={model} ({checkpoint}) via audio-separator, cpu")
        progress.report("separate", 0.05, f"separating with {model} (no progress)")
        source, placement = source_audio()
        stems = _roformer_separate(source, checkpoint, out_dir)
        if placement is not None:
            for path in stems.values():
                _pad_stem_to_track(Path(path), *placement)
            source.unlink(missing_ok=True)
        missing = [name for name in sources if name not in stems]
        if missing:
            raise RuntimeError(f"{checkpoint} did not produce {', '.join(missing)}")
        write_source_marker(out_dir, document, model, span)
        progress.report("separate", 1.0, "stems written")
        return document.model_copy(update={"stems": stems})

    import torch
    from demucs.api import Separator
    from demucs.audio import save_audio

    device = resolve_device(config.separate.device, torch.cuda.is_available())
    print(f"separate: model={model} device={device}")

    # Loading the bag is seconds; separating with it is minutes. So build the
    # separator first either way — it is what knows which stems this model is
    # supposed to produce, and a partially-written directory must not be
    # mistaken for a finished one.
    separator = Separator(model=model, device=device, callback=_progress_callback())
    if (reused := reuse(list(separator.model.sources))) is not None:
        return reused

    source, placement = source_audio()
    _origin, separated = separator.separate_audio_file(str(source))
    progress.report("separate", 1.0, "writing stems")

    out_dir.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, waveform in separated.items():
        stem_path = out_dir / f"{name}.wav"
        save_audio(waveform, str(stem_path), samplerate=separator.samplerate)
        if placement is not None:
            _pad_stem_to_track(stem_path, *placement)
        stems[name] = str(stem_path)
    if placement is not None:
        source.unlink(missing_ok=True)
    write_source_marker(out_dir, document, model, span)
    return document.model_copy(update={"stems": stems})
