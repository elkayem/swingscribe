"""Stage 0 — Ingest: decode, resample, and normalize the input audio (plan §5, M1).

Produces an AudioRef pointing at a normalized wav (config sample rate, stereo)
under the cache dir, so every downstream stage reads one known format and mp3
decoding happens exactly once.

I/O goes through soundfile (wav/flac) with an ffmpeg-CLI fallback for
everything else (mp3/m4a): torchaudio 2.11+ removed its built-in decoders,
so torchaudio.load/save are NOT usable — only its pure-DSP functional API is.

Heavy imports (torch, soundfile) stay inside functions: this module must stay
importable without the ml dependency group, which CI never installs.
"""

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from swingscribe.config import Config
from swingscribe.model import AudioRef, Document


def run(document: Document, config: Config) -> Document:
    import torchaudio

    src = Path(document.audio_path)
    if not src.is_file():
        raise FileNotFoundError(f"audio file not found: {src}")

    target_rate = config.ingest.sample_rate
    waveform, rate = _load(src)
    if rate != target_rate:
        waveform = torchaudio.functional.resample(waveform, rate, target_rate)
    if waveform.shape[0] == 1:
        waveform = waveform.repeat(2, 1)  # mono → stereo; separation models expect 2 channels

    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    out = Path(config.cache_dir) / "audio" / f"{digest}-{target_rate}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    _save_wav(out, waveform, target_rate)

    audio = AudioRef(
        path=str(out),
        sample_rate=target_rate,
        channels=waveform.shape[0],
        duration=waveform.shape[1] / target_rate,
    )
    return document.model_copy(update={"audio": audio, "sample_rate": target_rate})


def _load(path: Path):
    """Decode audio to a float32 [channels, time] tensor plus its sample rate."""
    if path.suffix.lower() in (".wav", ".flac"):
        return _load_via_soundfile(path)
    return _load_via_ffmpeg(path)


def _load_via_soundfile(path: Path):
    import soundfile
    import torch

    data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T.copy()), rate  # [time, ch] → [ch, time]


def _load_via_ffmpeg(path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            f"cannot decode {path}: this format needs ffmpeg, which is not on "
            "PATH (plan §8: winget install ffmpeg)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        decoded = Path(tmp) / "decoded.wav"
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(path), str(decoded)],
            check=True,
        )
        return _load_via_soundfile(decoded)


def _save_wav(path: Path, waveform, rate: int) -> None:
    import soundfile

    soundfile.write(str(path), waveform.numpy().T, rate)  # [ch, time] → [time, ch]
