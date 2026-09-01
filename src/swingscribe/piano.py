"""Polyphonic piano transcription — the second opinion (plan §5 stage 3, M7b).

Wraps `piano_transcription_inference` (Kong et al., MIT). Chosen over the
plan's `transkun` for its dependency tree rather than its scores; the
reasoning and the measurements are in docs/m7b-piano.md.

This is NOT a stage. It is a detector that `stages/transcribe.py` consults,
for the same reason `mscz.py` is not a stage: it has one job, it has no
opinion about Documents, and keeping it here means the stage contract stays
(Document, Config) -> Document.

Two things the upstream package does not do for itself on this machine:

- **it fetches its checkpoint with `os.system('wget ...')`**, which does not
  exist on Windows, and ignores the exit code — so the failure surfaces much
  later and somewhere else, as a FileNotFoundError inside `torch.load`.
  `ensure_checkpoint` fetches it with urllib instead, and note that the
  exported CA bundle does NOT verify Zenodo while Python's own default
  context does (CLAUDE.md's TLS notes).
- **it resamples through librosa.** We hand it 16 kHz mono already resampled
  by torchaudio, which is what the rest of the project does.

Heavy imports stay inside functions: this module must import without the ml
group, which CI never installs.
"""

import ssl
import urllib.request
from pathlib import Path

import numpy as np

# Where the upstream package looks, so a checkpoint fetched here is also found
# by anything that constructs PianoTranscription() directly.
CHECKPOINT_URL = (
    "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
)
CHECKPOINT_NAME = "note_F1=0.9677_pedal_F1=0.9186.pth"
MIN_CHECKPOINT_BYTES = 160_000_000  # ~172MB; guards a truncated download
MODEL_SAMPLE_RATE = 16_000


def checkpoint_path() -> Path:
    return Path.home() / "piano_transcription_inference_data" / CHECKPOINT_NAME


def ensure_checkpoint(path: Path | None = None, log=print) -> Path:
    """Download the model weights if they are not already here.

    Verified by size rather than presence: an interrupted download leaves a
    short file, and the upstream package's own check is the same size test —
    so a truncated file would be re-fetched by it too, forever, via a `wget`
    that does not exist.
    """
    destination = path or checkpoint_path()
    if destination.is_file() and destination.stat().st_size >= MIN_CHECKPOINT_BYTES:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"piano: fetching model weights (~172 MB) -> {destination}")
    context = ssl.create_default_context()
    with (
        urllib.request.urlopen(CHECKPOINT_URL, context=context, timeout=300) as response,
        open(destination, "wb") as out,
    ):
        while chunk := response.read(1 << 20):
            out.write(chunk)
    size = destination.stat().st_size
    if size < MIN_CHECKPOINT_BYTES:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"piano checkpoint download truncated at {size} bytes")
    return destination


def to_model_rate(mono: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample to the model's 16 kHz with torchaudio, never librosa."""
    import torch
    import torchaudio

    if sample_rate == MODEL_SAMPLE_RATE:
        return mono.astype(np.float32)
    resampled = torchaudio.functional.resample(
        torch.from_numpy(mono.astype(np.float32)), sample_rate, MODEL_SAMPLE_RATE
    )
    return resampled.numpy()


def transcribe(
    mono: np.ndarray,
    sample_rate: int,
    device: str = "cpu",
    offset: float = 0.0,
) -> list[dict]:
    """Polyphonic note events for one mono signal.

    `offset` is added to every onset, so a caller analysing a span can get
    whole-track times back — matching what `stages/transcribe.py` reports.
    Runs at roughly 0.36x realtime on CPU.

    A STANDALONE caller must run `transcribe._import_torchcrepe()` first:
    the import below pulls librosa, whose resampy dependency carries numba,
    which Application Control blocks on this machine (CLAUDE.md). Inside the
    pipeline that shim has always run by the time the oracle is consulted,
    which is why this import "just works" there and dies in a bare script.
    """
    from piano_transcription_inference import PianoTranscription

    ensure_checkpoint()
    model = PianoTranscription(device=device, checkpoint_path=str(checkpoint_path()))
    output = model.transcribe(to_model_rate(mono, sample_rate), None)
    return [
        {
            "onset": float(event["onset_time"]) + offset,
            "duration": float(event["offset_time"]) - float(event["onset_time"]),
            "pitch": int(event["midi_note"]),
            "velocity": int(event["velocity"]),
        }
        for event in output["est_note_events"]
    ]
