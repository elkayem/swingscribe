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

from swingscribe.config import Config
from swingscribe.device import resolve_device
from swingscribe.model import Document


def stems_dir(cache_dir: str | Path, audio_digest: str, model: str) -> Path:
    return Path(cache_dir) / "stems" / f"{audio_digest}-{model}"


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

    separator = Separator(model=config.separate.model, device=device)
    _origin, separated = separator.separate_audio_file(str(audio_path))

    out_dir.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, waveform in separated.items():
        stem_path = out_dir / f"{name}.wav"
        save_audio(waveform, str(stem_path), samplerate=separator.samplerate)
        stems[name] = str(stem_path)
    return document.model_copy(update={"stems": stems})
