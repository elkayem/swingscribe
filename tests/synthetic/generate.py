"""Generate audio with exact ground truth (plan §6, Layer 1).

This is the only place we get exact answers, so it carries the measurement
load: every knob here corresponds to something that has actually hurt us on
real recordings.

  - `accompaniment`  block chords under the line. This is open-issue #1 in a
                     bottle: their attacks are onsets that must NOT split the
                     melody's held notes.
  - `vibrato_cents`  the wobble that must not become separate notes.
  - `noise_db`       broadband noise, which drags CREPE's periodicity down.
  - `harmonics`      a pure sine is far easier to track than a reedy tone;
                     tracking a sine proves almost nothing.

Deterministic: same arguments in, same samples out (fixed seed).
"""

import random
from dataclasses import dataclass

SAMPLE_RATE = 16000  # CREPE's native rate; avoids a resample in the tests


@dataclass(frozen=True)
class SynthNote:
    onset: float
    duration: float
    pitch: int


def to_note_events(notes: list[SynthNote], source: str = "truth"):
    """Ground truth as the same type the pipeline emits, so it can be scored
    against an estimate without any conversion in the test."""
    from swingscribe.model import NoteEvent

    return [
        NoteEvent(onset=n.onset, duration=n.duration, pitch=n.pitch, confidence=1.0, source=source)
        for n in notes
    ]


def phrase(
    pitches: list[int], note_duration: float = 0.4, gap: float = 0.05, start: float = 0.25
) -> list[SynthNote]:
    """A simple line: equal notes separated by a small gap."""
    notes = []
    t = start
    for pitch in pitches:
        notes.append(SynthNote(onset=t, duration=note_duration - gap, pitch=pitch))
        t += note_duration
    return notes


def swung_phrase(
    pitches: list[int],
    bpm: float = 180.0,
    bur: float = 2.0,
    start: float = 0.25,
    gap_fraction: float = 0.15,
) -> tuple[list[SynthNote], list[float]]:
    """Eighth-note pairs at a KNOWN beat-upbeat ratio, plus the beat grid.

    The ground truth M4 is scored against (plan §6 layer 1). Notes alternate
    long-short within each beat: at BUR b the offbeat lands at phase
    b/(1+b), so b=1.0 puts it at 0.5 (straight) and b=2.0 at 0.667 (triplet).

    Returns (notes, beats). The grid is exact and comes back with the notes
    because the swing estimator needs both, and deriving one from the other
    in a test would be assuming the thing under test.
    """
    beat = 60.0 / bpm
    phase = bur / (1.0 + bur)
    notes = []
    for index, pitch in enumerate(pitches):
        whole, half = divmod(index, 2)
        offset = phase * beat if half else 0.0
        length = (1.0 - phase) * beat if half else phase * beat
        notes.append(
            SynthNote(
                onset=start + whole * beat + offset,
                duration=length * (1.0 - gap_fraction),
                pitch=pitch,
            )
        )
    n_beats = (len(pitches) + 1) // 2
    beats = [start + i * beat for i in range(n_beats + 1)]
    return notes, beats


def held_note_phrase(pitch: int = 57, hold: float = 1.5, start: float = 0.25) -> list[SynthNote]:
    """One long held note — the case open-issue #1 shattered."""
    return [SynthNote(onset=start, duration=hold, pitch=pitch)]


def render(
    notes: list[SynthNote],
    duration: float | None = None,
    rate: int = SAMPLE_RATE,
    harmonics: int = 5,
    vibrato_cents: float = 0.0,
    vibrato_hz: float = 5.5,
    noise_db: float | None = None,
    accompaniment: list[SynthNote] | None = None,
    accompaniment_db: float = -6.0,
    seed: int = 0,
):
    """Render a note list to a mono float32 signal."""
    import numpy as np

    if duration is None:
        duration = max((n.onset + n.duration for n in notes), default=1.0) + 0.5
    total = int(rate * duration)
    signal = np.zeros(total, dtype=np.float64)

    for note in notes:
        signal += _render_one(note, rate, total, harmonics, vibrato_cents, vibrato_hz)

    if accompaniment:
        chords = np.zeros(total, dtype=np.float64)
        for note in accompaniment:
            chords += _render_one(note, rate, total, harmonics=3, vibrato_cents=0.0, vibrato_hz=0.0)
        peak = np.abs(chords).max() or 1.0
        chords *= (10.0 ** (accompaniment_db / 20.0)) / peak
        signal += chords

    peak = np.abs(signal).max() or 1.0
    signal = signal / peak * 0.7

    if noise_db is not None:
        rng = np.random.default_rng(seed)
        amplitude = 10.0 ** (noise_db / 20.0)
        signal += rng.standard_normal(total) * amplitude

    return np.clip(signal, -1.0, 1.0).astype("float32")


def _render_one(note: SynthNote, rate: int, total: int, harmonics, vibrato_cents, vibrato_hz):
    import numpy as np

    start = int(note.onset * rate)
    length = int(note.duration * rate)
    if start >= total or length <= 0:
        return np.zeros(total)
    length = min(length, total - start)
    t = np.arange(length) / rate

    f0 = 440.0 * 2.0 ** ((note.pitch - 69) / 12.0)
    if vibrato_cents:
        cents = vibrato_cents * np.sin(2 * np.pi * vibrato_hz * t)
        freq = f0 * 2.0 ** (cents / 1200.0)
        phase = 2 * np.pi * np.cumsum(freq) / rate
    else:
        phase = 2 * np.pi * f0 * t

    wave = np.zeros(length)
    for k in range(1, harmonics + 1):
        if f0 * k >= rate / 2:
            break
        wave += np.sin(phase * k) / k

    attack = max(1, int(0.012 * rate))
    release = max(1, int(0.030 * rate))
    envelope = np.ones(length)
    envelope[:attack] = np.linspace(0.0, 1.0, attack)
    if length > release:
        envelope[-release:] = np.linspace(1.0, 0.0, release)
    envelope *= np.exp(-t * 0.35)  # gentle decay, like a blown tone

    out = np.zeros(total)
    out[start : start + length] = wave * envelope
    return out


def write_wav(path, signal, rate: int = SAMPLE_RATE) -> str:
    import soundfile

    soundfile.write(str(path), signal, rate)
    return str(path)


def comping_under(notes: list[SynthNote], every: float = 0.5, pitch_offset: int = -19):
    """Block chords on a steady pulse beneath the line — the piano-comping
    pattern that split held notes before onset corroboration existed."""
    if not notes:
        return []
    start = min(n.onset for n in notes)
    end = max(n.onset + n.duration for n in notes)
    root = notes[0].pitch + pitch_offset
    chords: list[SynthNote] = []
    t = start
    rng = random.Random(7)
    while t < end:
        for interval in (0, 4, 7):
            chords.append(SynthNote(onset=t, duration=0.22, pitch=root + interval))
        t += every * rng.choice([1.0, 1.0, 0.5])
    return chords
