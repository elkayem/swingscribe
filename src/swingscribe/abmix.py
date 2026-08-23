"""The transcription ear test (plan §6): original left, transcription right.

Renders the transcribed notes to audio (pretty_midi's additive-sine synth —
crude but pitch- and timing-faithful, which is all judging needs) and writes
a stereo wav with the original on the LEFT channel and the rendered
transcription on the RIGHT. Thirty seconds of listening reveals more than a
page of metrics.
"""

from pathlib import Path

from swingscribe.model import NoteEvent

ORIGINAL_GAIN = 0.85
RENDER_PEAK = 0.7
SAX_PROGRAM = 66  # General MIDI tenor sax — cosmetic; the synth is sines


def default_ab_path(audio_path: str | Path) -> Path:
    p = Path(audio_path)
    return p.with_name(p.stem + ".ab.wav")


def default_midi_path(audio_path: str | Path) -> Path:
    p = Path(audio_path)
    return p.with_name(p.stem + ".transcribed.mid")


def default_audition_path(audio_path: str | Path, stem: str) -> Path:
    p = Path(audio_path)
    return p.with_name(f"{p.stem}.{stem}.wav")


def write_stem_slice(
    stem_path: str | Path, out_path: str | Path, region: tuple[float, float] | None = None
) -> Path:
    """Write a (optionally region-limited) copy of a separated stem, for the
    audition step — listen to the isolated instrument BEFORE transcribing
    (plan §13 / docs/gui-design.md screen 3)."""
    import soundfile

    data, rate = soundfile.read(str(stem_path), dtype="float32", always_2d=True)
    if region is not None:
        start, end = region
        data = data[int(start * rate) : int(end * rate)]
    out = Path(out_path)
    soundfile.write(str(out), data, rate)
    return out


def notes_to_midi(notes: list[NoteEvent], out_path: str | Path | None = None):
    import pretty_midi

    pm = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=SAX_PROGRAM)
    for note in notes:
        velocity = max(30, min(127, int(round(40 + 87 * note.confidence))))
        instrument.notes.append(
            pretty_midi.Note(
                velocity=velocity,
                pitch=note.pitch,
                start=note.onset,
                end=note.onset + note.duration,
            )
        )
    pm.instruments.append(instrument)
    if out_path is not None:
        pm.write(str(out_path))
    return pm


def render_ab_mix(
    original_path: str | Path,
    notes: list[NoteEvent],
    out_path: str | Path,
    region: tuple[float, float] | None = None,
) -> Path:
    """Stereo ear-test wav: original (mono) left, synthesized transcription right.

    With a region, both channels cover just that span — note onsets arrive in
    whole-track time and are shifted back to the slice.
    """
    import numpy as np
    import soundfile

    data, rate = soundfile.read(str(original_path), dtype="float32", always_2d=True)
    left = data.mean(axis=1) * ORIGINAL_GAIN
    if region is not None:
        start, end = region
        left = left[int(start * rate) : int(end * rate)]
        notes = [
            n.model_copy(update={"onset": n.onset - start}) for n in notes if start <= n.onset < end
        ]

    right = notes_to_midi(notes).synthesize(fs=rate).astype("float32")
    peak = float(abs(right).max()) if len(right) else 0.0
    if peak > 0:
        right *= RENDER_PEAK / peak

    length = max(len(left), len(right))
    left = np.pad(left, (0, length - len(left)))
    right = np.pad(right, (0, length - len(right)))

    stereo = np.stack([left, right], axis=1)
    np.clip(stereo, -1.0, 1.0, out=stereo)
    out = Path(out_path)
    soundfile.write(str(out), stereo, rate)
    return out
