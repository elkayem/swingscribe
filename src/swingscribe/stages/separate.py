"""Stage 1 — Separate: 4 stems via the demucs Python API, not subprocess (plan §5, M1).

The model name comes from config so a BS-Roformer checkpoint can drop in
behind the same interface later. Stems are written as wavs under the cache
dir in a directory derived from the audio content and model name, so the
same input always lands in the same place.

Heavy imports (torch, demucs) stay inside run(): this module must stay
importable without the ml dependency group, which CI never installs.
"""

import hashlib
from pathlib import Path

from swingscribe import progress
from swingscribe.config import Config
from swingscribe.device import resolve_device
from swingscribe.model import Document


def stems_dir(cache_dir: str | Path, audio_digest: str, model: str) -> Path:
    return Path(cache_dir) / "stems" / f"{audio_digest}-{model}"


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
    import torch
    from demucs.api import Separator
    from demucs.audio import save_audio

    if document.audio is None:
        raise ValueError("separate requires ingest to have run first (document.audio is None)")

    audio_path = Path(document.audio.path)
    digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()[:16]
    out_dir = stems_dir(config.cache_dir, digest, config.separate.model)

    device = resolve_device(config.separate.device, torch.cuda.is_available())
    print(f"separate: model={config.separate.model} device={device}")

    separator = Separator(model=config.separate.model, device=device, callback=_progress_callback())
    _origin, separated = separator.separate_audio_file(str(audio_path))
    progress.report("separate", 1.0, "writing stems")

    out_dir.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, waveform in separated.items():
        stem_path = out_dir / f"{name}.wav"
        save_audio(waveform, str(stem_path), samplerate=separator.samplerate)
        stems[name] = str(stem_path)
    return document.model_copy(update={"stems": stems})
