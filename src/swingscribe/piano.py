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

A SECOND LOADER (`load_note_model`, bottom of the file) runs the note-only
checkpoints of the same CRNN that other groups trained -- Edwards et al.'s
augmented piano weights, Riley & Dixon's FiloSax saxophone weights -- and
keeps the model's activations, which the pipeline path throws away. It is a
research path for docs/kong-bakeoff.md; `transcribe` above is untouched.

Heavy imports stay inside functions: this module must import without the ml
group, which CI never installs.
"""

import dataclasses
import os
import ssl
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
    """Where the weights live: `SWINGSCRIBE_MODELS_DIR` when set — the portable
    build points every model download at one per-user folder that way, as
    `TORCH_HOME` and `AUDIO_SEPARATOR_MODEL_DIR` do for the others — else the
    upstream package's own default under the home directory."""
    models_dir = os.environ.get("SWINGSCRIBE_MODELS_DIR")
    if models_dir:
        return Path(models_dir) / CHECKPOINT_NAME
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


def _numba_free() -> None:
    """Make librosa importable when Application Control blocks numba.

    resampy is stubbed the way transcribe._import_torchcrepe does it, and
    numba itself gets pass-through decorators when its DLLs will not load:
    numba only ever OPTIMIZES the librosa code paths the piano model
    touches, so the un-jitted functions are the same functions, slower.
    Real modules win whenever they import.
    """
    # The numba stand-in is swingscribe/numba_guard.py, shared with the
    # default separator, which loads librosa too (2026-09-27).
    from swingscribe import numba_guard
    from swingscribe.stages.transcribe import _ensure_resampy

    _ensure_resampy()
    numba_guard.ensure_numba()


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

    The import below reaches numba twice on this machine, and Application
    Control's verdict on numba CHANGES over time (allowed 2026-08-31
    morning, blocked again by 2026-09-01 — CLAUDE.md: test, never
    remember). `_numba_free()` installs the same class of shim as
    transcribe._import_torchcrepe: real modules when they load, pass-through
    stand-ins when AC refuses them. librosa uses numba only as an optimizing
    decorator on functions that run fine un-jitted, and torchlibrosa touches
    only window/pad/mel utilities. Without this, a blocked numba silently
    costs every fresh piano transcription its oracle ("keeping CREPE" in a
    log nobody reads).
    """
    _numba_free()
    from piano_transcription_inference import PianoTranscription

    from swingscribe import progress

    # Through the progress channel as well as the console: in the GUI the
    # console is minimized and the first-run download (~172 MB) is otherwise
    # a transcription that sits at 0% for minutes with no explanation.
    def announce(message: str) -> None:
        print(message)
        progress.report("transcribe", None, message)

    ensure_checkpoint(log=announce)
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


# ── A second loader: note-only Kong checkpoints ─────────────────────────────
#
# Two groups have retrained Kong's CRNN and published NOTE-ONLY checkpoints:
# Edwards et al. (piano, MAESTRO plus augmentation; Zenodo 10610212, CC BY
# 4.0) and Riley & Dixon (tenor saxophone, FiloSax; Hugging Face
# xavriley/midi-transcription-models). `transcribe` above cannot run either,
# and every way it fails is quiet or far away:
#
# - PianoTranscription's default model_type is 'Note_pedal', whose
#   load_state_dict indexes checkpoint["model"]["note_model"] -- a KeyError
#   on a note-only file -- and upstream loads with strict=False, so a layout
#   that slipped past the KeyError would load NOTHING and transcribe with
#   random weights.
# - Its constructor runs `wget` over any checkpoint under 1.6e8 bytes. Both
#   files are ~100 MB, so it would try to overwrite them with the piano
#   weights (on Windows the wget fails, and it carries on).
# - torch >= 2.6 loads weights-only by default, and both files carry the
#   training sampler's numpy RNG state, which that refuses.
#
# So this path never constructs PianoTranscription: it builds the network
# itself, loads the weights STRICTLY, and allowlists exactly the numpy
# globals the RNG state needs -- still weights-only, never arbitrary pickle.
# Enframing and deframing copy upstream's (10 s segments, half overlap, the
# middle half kept), so the pipeline's own checkpoint, run this way, gives
# the pipeline's oracle; and the four activation rolls come back with the
# notes, because roadmap A6's figure classifier wants them as its input.

NOTE_MODEL_TYPE = "Regress_onset_offset_frame_velocity_CRNN"
FRAMES_PER_SECOND = 100  # upstream's config: 16 kHz audio, a 160-sample hop
CLASSES_NUM = 88  # A0..C8
BEGIN_NOTE = 21
SEGMENT_SAMPLES = MODEL_SAMPLE_RATE * 10
ROLLS = ("reg_onset_output", "reg_offset_output", "frame_output", "velocity_output")
# Upstream's decoding thresholds: what the pipeline's oracle uses, and what
# Riley's hf_midi_transcription keeps for the saxophone model.
ONSET_THRESHOLD = 0.3
OFFSET_THRESHOLD = 0.3
FRAME_THRESHOLD = 0.1


@dataclasses.dataclass
class NoteModel:
    """A loaded note-only CRNN and the device it runs on."""

    network: Any
    device: str
    path: Path
    iteration: int | None = None


def _note_network_class():
    """Upstream's note network (a seam: the tests put a tiny one here)."""
    _numba_free()  # torchlibrosa imports librosa, which imports numba
    from piano_transcription_inference.models import Regress_onset_offset_frame_velocity_CRNN

    return Regress_onset_offset_frame_velocity_CRNN


def note_weights(checkpoint: Mapping) -> Mapping:
    """The note network's state dict, from any layout in circulation.

    `{"model": weights}` (Kong's training script, Edwards et al., Riley &
    Dixon), `{"model": {"note_model": ..., "pedal_model": ...}}` (the
    Note_pedal release the pipeline downloads -- its note head IS this
    network), or bare weights.
    """
    weights = checkpoint.get("model", checkpoint)
    if isinstance(weights, Mapping) and "note_model" in weights:
        weights = weights["note_model"]
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("no note-model weights in this checkpoint")
    return weights


def _checkpoint_globals() -> list:
    """The numpy globals a training checkpoint's sampler state pickles, under
    both names numpy has given the module. Nothing that can run code."""
    try:
        from numpy._core.multiarray import _reconstruct
    except ImportError:  # numpy < 2
        from numpy.core.multiarray import _reconstruct
    # The dtype classes (numpy.dtypes.UInt32DType ...) an RNG state's arrays name.
    dtypes = {type(np.dtype(code)) for code in "?bhilqBHILQefd"}
    return [
        (_reconstruct, "numpy.core.multiarray._reconstruct"),
        (_reconstruct, "numpy._core.multiarray._reconstruct"),
        np.ndarray,
        np.dtype,
        *sorted(dtypes, key=lambda t: t.__name__),
    ]


def load_note_model(path: str | Path, device: str = "cpu") -> NoteModel:
    """A note-only Kong CRNN checkpoint, ready to run.

    Never downloads and never reaches upstream's constructor (the comment
    above): a missing file is a FileNotFoundError here, not a `wget`
    somewhere else, and a file of any size is taken as it is. Loading is
    STRICT -- a checkpoint whose keys do not fit the network raises rather
    than running random weights.
    """
    import torch

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no checkpoint at {path}")
    allow = getattr(torch.serialization, "safe_globals", None)
    if allow is None:  # torch < 2.5: nothing to extend; a sampler state then fails loudly
        checkpoint = torch.load(str(path), map_location="cpu", weights_only=True)
    else:
        with allow(_checkpoint_globals()):
            checkpoint = torch.load(str(path), map_location="cpu", weights_only=True)
    network = _note_network_class()(frames_per_second=FRAMES_PER_SECOND, classes_num=CLASSES_NUM)
    network.load_state_dict(note_weights(checkpoint), strict=True)
    network.to(device)
    network.eval()
    iteration = checkpoint.get("iteration") if isinstance(checkpoint, Mapping) else None
    return NoteModel(network, device, path, None if iteration is None else int(iteration))


def _deframe(x: np.ndarray) -> np.ndarray:
    """Upstream's `PianoTranscription.deframe`: drop each segment's extra last
    frame (the STFT is centred), then keep the first segment's first three
    quarters, the middle half of each inner one and the last one's tail."""
    if x.shape[0] == 1:
        return x[0]
    x = x[:, :-1, :]
    frames = x.shape[1]
    quarter, three_quarters = int(frames * 0.25), int(frames * 0.75)
    parts = [x[0, :three_quarters]]
    parts += [x[i, quarter:three_quarters] for i in range(1, x.shape[0] - 1)]
    parts.append(x[-1, quarter:])
    return np.concatenate(parts, axis=0)


def note_activations(
    model: NoteModel, mono16k: np.ndarray, batch_size: int = 1
) -> dict[str, np.ndarray]:
    """The four rolls -- onset, offset, frame, velocity -- as (frames, 88)
    arrays at 100 frames a second, for 16 kHz mono.

    Enframed and deframed exactly as upstream's `transcribe` does, zero
    padding to whole 10 s segments included, so the rolls run on past the
    audio by up to ten seconds of silence as upstream's do: its trim slices
    FRAMES by the SAMPLE count, and so never cuts anything.
    """
    import torch

    audio = np.asarray(mono16k, dtype=np.float32)
    padded = int(np.ceil(max(len(audio), 1) / SEGMENT_SAMPLES)) * SEGMENT_SAMPLES
    audio = np.concatenate([audio, np.zeros(padded - len(audio), dtype=np.float32)])
    hop = SEGMENT_SAMPLES // 2
    segments = np.stack(
        [audio[start : start + SEGMENT_SAMPLES] for start in range(0, padded - hop, hop)]
    )
    collected: dict[str, list[np.ndarray]] = {key: [] for key in ROLLS}
    with torch.no_grad():
        for start in range(0, len(segments), batch_size):
            batch = torch.from_numpy(segments[start : start + batch_size]).to(model.device)
            output = model.network(batch)
            for key in ROLLS:
                collected[key].append(output[key].detach().float().cpu().numpy())
    return {key: _deframe(np.concatenate(parts, axis=0)) for key, parts in collected.items()}


def decode_notes(
    rolls: Mapping[str, np.ndarray],
    offset: float = 0.0,
    onset_threshold: float = ONSET_THRESHOLD,
    offset_threshold: float = OFFSET_THRESHOLD,
    frame_threshold: float = FRAME_THRESHOLD,
) -> list[dict]:
    """Notes from the rolls, through upstream's own post-processor.

    The pipeline oracle's note shape (`transcribe` above) plus
    `onset_strength`: the onset roll's peak at the note's pitch within two
    frames of its onset, a confidence that does not depend on the velocity
    head having been trained on the instrument in question.
    """
    _numba_free()  # upstream's utilities import librosa
    from piano_transcription_inference.utilities import RegressionPostProcessor

    processor = RegressionPostProcessor(
        FRAMES_PER_SECOND,
        classes_num=CLASSES_NUM,
        onset_threshold=onset_threshold,
        offset_threshold=offset_threshold,
        frame_threshold=frame_threshold,
        pedal_offset_threshold=0.2,
    )
    # The processor writes its binarised outputs into the dict it is handed.
    given = {key: np.asarray(rolls[key], dtype=np.float32) for key in ROLLS}
    events, _pedals = processor.output_dict_to_midi_events(given)
    onsets = given["reg_onset_output"]
    notes = []
    for event in events:
        # A note that ends where it begins is not a note. Upstream's peak test
        # is non-strict, so two EQUAL onset frames both count; float16 rolls
        # make such plateaus, and the second decodes to a copy of the first
        # at the same onset with a negative length (329 of 47,143 on the horn
        # regions; none from float32 rolls).
        if float(event["offset_time"]) <= float(event["onset_time"]):
            continue
        pitch = int(event["midi_note"])
        frame = int(round(float(event["onset_time"]) * FRAMES_PER_SECOND))
        low, high = max(frame - 2, 0), min(frame + 3, len(onsets))
        strength = float(onsets[low:high, pitch - BEGIN_NOTE].max()) if high > low else 0.0
        notes.append(
            {
                "onset": float(event["onset_time"]) + offset,
                "duration": float(event["offset_time"]) - float(event["onset_time"]),
                "pitch": pitch,
                "velocity": int(event["velocity"]),
                "onset_strength": round(strength, 4),
            }
        )
    return notes


def transcribe_notes(
    model: NoteModel,
    mono: np.ndarray,
    sample_rate: int,
    offset: float = 0.0,
    batch_size: int = 1,
    **thresholds: float,
) -> tuple[list[dict], dict[str, np.ndarray]]:
    """`transcribe` for a note-only checkpoint: the notes AND the rolls."""
    rolls = note_activations(model, to_model_rate(mono, sample_rate), batch_size)
    return decode_notes(rolls, offset, **thresholds), rolls
