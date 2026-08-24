"""Render the same ground truth through a real instrument (plan §6, §12).

`generate.render` builds notes out of stacked sines. That is a fine regression
guard and a poor quality measure: every additive case scores ≥0.98
(open-issue #4), so the suite can tell us a change broke something but not
whether the transcriber is any good. A sampled tenor sax has breath noise, a
formant-shaped and time-varying harmonic series, an attack transient that is
not a 12ms ramp, and release tails that overlap the next note — all the things
that actually make CREPE and the segmenter work.

The ground truth is unchanged: the SAME `SynthNote` list drives both paths, so
a score difference is entirely attributable to timbre. Only the audio moves.

Rendering shells out to the FluidSynth CLI, the way `stages/ingest.py` shells
out to ffmpeg. Deliberately not pyfluidsynth: bindings load a native DLL into
the Python process, which is what Windows Application Control blocks on this
machine (CLAUDE.md — it already cost us numba and therefore librosa). A
subprocess loads its own DLLs in its own process and is untouched by that.

Both the soundfont and the CLI are fetched by scripts/setup_fixtures.py and
live outside the repo; nothing here is committed (plan §12).
"""

import functools
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from synthetic.generate import SAMPLE_RATE, SynthNote

# General MIDI program numbers, 0-based as pretty_midi wants them.
ALTO_SAX = 65
TENOR_SAX = 66
TRUMPET = 56
ACOUSTIC_PIANO = 0

SOUNDFONT_ENV = "SWINGSCRIBE_SOUNDFONT"
FLUIDSYNTH_ENV = "SWINGSCRIBE_FLUIDSYNTH"

# pretty_midi's default 220 ticks/beat quantizes onsets to ~2.3ms. That is
# inside the 50ms scoring tolerance but it is free to remove, and a ground
# truth that is exact by construction should stay exact.
MIDI_RESOLUTION = 960

# Mod wheel drives the vibrato LFO in a GM bank, which is how a real sax patch
# wobbles. 0 = none.
VIBRATO_CC = 1


class FluidSynthError(RuntimeError):
    """Rendering failed; the message carries fluidsynth's own first line."""


@functools.cache
def _setup_fixtures():
    """Load scripts/setup_fixtures.py so the fixture layout has one owner.

    The script decides where downloads land; duplicating that rule here is
    how the two drift apart. It imports nothing but stdlib, so this is cheap.
    """
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "setup_fixtures.py"
    spec = importlib.util.spec_from_file_location("swingscribe_setup_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fetched(env_var: str) -> str | None:
    """The fetched artifact registered under `env_var`, or None if absent."""
    try:
        setup = _setup_fixtures()
    except Exception:
        return None  # script missing or unreadable — treat as "not fetched"
    home = setup.fixture_home()
    for artifact in setup.ARTIFACTS:
        if artifact.env_var == env_var:
            found = setup.installed_path(artifact, home)
            return str(found) if found else None
    return None


def find_soundfont() -> str | None:
    override = os.environ.get(SOUNDFONT_ENV)
    if override:
        return override if Path(override).is_file() else None
    return _fetched(SOUNDFONT_ENV)


def find_fluidsynth() -> str | None:
    """Locate the FluidSynth CLI: explicit override, PATH, then the fetched copy.

    PATH comes before the fetched copy so a machine with a real install (any
    Linux, a mac with brew) needs no download at all — the fetch exists
    because FluidSynth is not in winget on this machine, not because a system
    install would be wrong.
    """
    override = os.environ.get(FLUIDSYNTH_ENV)
    if override:
        return override if Path(override).is_file() else None
    on_path = shutil.which("fluidsynth")
    if on_path:
        return on_path
    return _fetched(FLUIDSYNTH_ENV)


def available() -> bool:
    """True when a soundfont render is possible here."""
    return find_soundfont() is not None and find_fluidsynth() is not None


def missing_reason() -> str:
    """Why it isn't, phrased as something a human can act on."""
    missing = []
    if find_soundfont() is None:
        missing.append(f"soundfont (${SOUNDFONT_ENV})")
    if find_fluidsynth() is None:
        missing.append(f"fluidsynth CLI (${FLUIDSYNTH_ENV})")
    return f"missing {' and '.join(missing)} — run scripts/setup_fixtures.py"


def write_midi(
    notes: list[SynthNote],
    path,
    program: int = TENOR_SAX,
    velocity: int = 100,
    vibrato: int = 0,
) -> str:
    """Write the ground truth to a MIDI file, verbatim.

    No quantization, no humanization: the note list IS the answer key, and
    anything that moved a note here would make the scores meaningless.
    """
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(resolution=MIDI_RESOLUTION)
    instrument = pretty_midi.Instrument(program=program)
    if vibrato:
        instrument.control_changes.append(
            pretty_midi.ControlChange(number=VIBRATO_CC, value=vibrato, time=0.0)
        )
    for note in notes:
        instrument.notes.append(
            pretty_midi.Note(
                velocity=velocity,
                pitch=note.pitch,
                start=note.onset,
                end=note.onset + note.duration,
            )
        )
    pm.instruments.append(instrument)
    pm.write(str(path))
    return str(path)


def _fluidsynth_render(midi_path, wav_path, rate: int, gain: float, reverb: bool) -> None:
    binary = find_fluidsynth()
    if binary is None:
        raise FluidSynthError(missing_reason())
    soundfont = find_soundfont()
    if soundfont is None:
        raise FluidSynthError(missing_reason())

    # Reverb and chorus are off by default: they smear note offsets, and this
    # suite is measuring whether a realistic *timbre* is harder to track, not
    # whether a reverb tail is. Turn reverb on for a deliberate room case.
    result = subprocess.run(
        [
            binary,
            "-ni",  # no MIDI input, no interactive shell
            "-F",
            str(wav_path),  # fast-render straight to file
            "-T",
            "wav",
            "-r",
            str(rate),  # render at CREPE's rate; nothing resamples afterwards
            "-g",
            f"{gain:.3f}",
            "-R",
            "1" if reverb else "0",
            "-C",
            "0",  # chorus off
            str(soundfont),
            str(midi_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not Path(wav_path).is_file():
        stderr = (result.stderr or result.stdout).strip() or "unknown fluidsynth error"
        raise FluidSynthError(f"fluidsynth failed: {stderr.splitlines()[0]}")


def _render_track(notes, program, rate, gain, reverb, vibrato, total: int):
    """One instrument, rendered to a mono float64 array of exactly `total` samples."""
    import numpy as np
    import soundfile

    with tempfile.TemporaryDirectory() as tmp:
        midi = Path(tmp) / "track.mid"
        wav = Path(tmp) / "track.wav"
        write_midi(notes, midi, program=program, vibrato=vibrato)
        _fluidsynth_render(midi, wav, rate, gain, reverb)
        data, out_rate = soundfile.read(str(wav), dtype="float64", always_2d=True)

    if out_rate != rate:  # fluidsynth honoured -r, but never assume it
        raise FluidSynthError(f"expected {rate} Hz from fluidsynth, got {out_rate}")
    mono = data.mean(axis=1)
    out = np.zeros(total, dtype=np.float64)
    length = min(total, len(mono))
    out[:length] = mono[:length]
    return out


def render(
    notes: list[SynthNote],
    duration: float | None = None,
    rate: int = SAMPLE_RATE,
    program: int = TENOR_SAX,
    vibrato: int = 0,
    gain: float = 0.8,
    reverb: bool = False,
    noise_db: float | None = None,
    accompaniment: list[SynthNote] | None = None,
    accompaniment_program: int = ACOUSTIC_PIANO,
    accompaniment_db: float = -6.0,
    seed: int = 0,
):
    """Render a note list to mono float32, drop-in compatible with `generate.render`.

    Same signature shape and same mix arithmetic, so a soundfont case and its
    additive twin differ in exactly one thing: where the samples came from.
    """
    import numpy as np

    if duration is None:
        duration = max((n.onset + n.duration for n in notes), default=1.0) + 0.5
    total = int(rate * duration)

    signal = _render_track(notes, program, rate, gain, reverb, vibrato, total)
    # Peak-normalize the melody before mixing so `accompaniment_db` means the
    # same thing here as in generate.render. There the melody's peak is a
    # known ~1 from summed sines; a soundfont's is whatever the sample's
    # loudness happens to be, so it has to be pinned explicitly or a "-3dB"
    # comping case would be a different balance in the two suites.
    signal = signal / (np.abs(signal).max() or 1.0)

    if accompaniment:
        chords = _render_track(accompaniment, accompaniment_program, rate, gain, reverb, 0, total)
        chords *= (10.0 ** (accompaniment_db / 20.0)) / (np.abs(chords).max() or 1.0)
        signal = signal + chords

    signal = signal / (np.abs(signal).max() or 1.0) * 0.7

    if noise_db is not None:
        rng = np.random.default_rng(seed)
        signal += rng.standard_normal(total) * (10.0 ** (noise_db / 20.0))

    return np.clip(signal, -1.0, 1.0).astype("float32")
