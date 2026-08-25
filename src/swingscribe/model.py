"""The data contract (plan §3).

Everything hangs off one Document. Stages take (Document, Config) and return
an updated Document; all shared types live here and nowhere else.

Changing anything in this module invalidates cached artifacts — flag the
migration impact whenever you touch it.
"""

from pydantic import BaseModel


class AudioRef(BaseModel):
    path: str  # normalized wav produced by ingest (config rate, stereo)
    sample_rate: int
    channels: int
    duration: float  # seconds


class NoteEvent(BaseModel):
    onset: float  # seconds, as performed
    duration: float  # seconds, as performed
    pitch: int  # MIDI note number
    confidence: float
    source: str  # which stem/model produced it


class BeatGrid(BaseModel):
    beats: list[float]  # seconds
    downbeats: list[float]  # subset of beats
    beats_per_bar: int
    local_bpm: list[float] = []  # tempo curve, one local BPM per beat (plan §5 stage 2)
    # Which audio produced this grid. The stage may override its initial
    # source choice or splice two together, and without this, reporting has to
    # re-derive the winner and gets it wrong (open-issue #7).
    source: str = ""
    # Spans filled from the OTHER source because the chosen one had no beats
    # there — a drumless intro, typically (open-issue #9). Empty is the normal
    # case. Beats inside these spans are worth trusting less.
    spliced: list[tuple[float, float]] = []
    # Spans subdivided because the tracker took them at a whole fraction of
    # the grid's own rate (open-issue #9). Separate from `spliced`: those
    # beats came from other audio, these were interpolated from this grid.
    repaired: list[tuple[float, float]] = []


class MeterSection(BaseModel):
    """One stretch of the tune with a constant meter (plan §13).

    Bar lines are NOT the beat tracker's detected downbeats — measured against
    real tracks, that layer is noise (open-issue #5). They are derived by
    counting beats from `anchor`, which the user can move in one click.

    Meter lives in a LIST so that two features cost no schema change later:
    a meter change is another section, and a rubato passage is simply time no
    section covers. There is deliberately no `is_rubato` flag.
    """

    start: float  # seconds, inclusive
    end: float  # seconds, exclusive
    pulses_per_bar: int  # tracked beats per bar — NOT the time-signature numerator
    time_signature: tuple[int, int]  # what gets notated, e.g. (6, 8)
    anchor: float  # seconds; a beat that is beat 1. Phase, not origin.
    first_bar: int = 1  # bar number of this section's first bar line
    confidence: float = 1.0  # lowered when the bar count crossed a gap
    origin: str = "auto"  # auto | user


class SwingSpan(BaseModel):
    start_beat: int
    end_beat: int
    bur: float  # beat-upbeat ratio; 1.0 = straight, 2.0 = triplet swing
    confidence: float
    is_swung: bool


class QuantizedNote(BaseModel):
    bar: int
    beat: float  # position within bar, in straight-eighth grid units
    duration_beats: float
    pitch: int
    timing_residual: float  # microtiming AFTER swing removal — the expressive layer


class NotatedNote(BaseModel):
    """One notated note or rest: where it sits, how long, and how it is spelled.

    `pitch` stays SOUNDING (concert) throughout. Written pitch is a property of
    the part, not of the note, and baking the transposition in here would make
    every downstream comparison against concert-pitch ground truth wrong.
    """

    beat: float  # quarter notes from the start of its bar
    duration: float  # quarter notes
    pitch: int = 0  # sounding MIDI; meaningless when is_rest
    step: str = "C"  # C..B
    alter: int = 0  # -1 flat, +1 sharp, 0 natural
    octave: int = 4
    is_rest: bool = False
    # A note too long, or too awkwardly placed, to write as one symbol becomes
    # several tied together. Both flags are set on the middle of a three-note tie.
    tie_start: bool = False
    tie_stop: bool = False
    # (actual, normal) for a tuplet — (3, 2) for the ordinary triplet. Quantize
    # chooses a ternary grid per beat where the notes fit one better (plan §5),
    # and a third of a beat is not a note value: it is an eighth note that has
    # been told three of them fill a beat. Without this the duration is simply
    # unwritable and the bar stops adding up.
    tuplet: tuple[int, int] | None = None


class NotatedBar(BaseModel):
    number: int
    time_signature: tuple[int, int]
    notes: list[NotatedNote] = []


class Notation(BaseModel):
    """A notatable score: bars of spelled notes, plus what the part needs.

    Deliberately not a music21 Score. music21 is not a dependency of this
    project and adding one is not a decision this stage gets to make on its
    own (CLAUDE.md); everything stage 6 needs — key, spelling, note values,
    ties, rests — is arithmetic, and keeping it arithmetic means the whole
    stage runs in CI like every other one.
    """

    bars: list[NotatedBar] = []
    key_fifths: int = 0  # -1 = one flat, as MuseScore's concertKey
    swing: bool = False  # write "Swing" above the staff, eighths straight
    # Written = sounding + this many semitones. Bb tenor is +14, Eb alto +9.
    transpose: int = 0
    title: str = ""


class Document(BaseModel):
    audio_path: str
    sample_rate: int
    audio: AudioRef | None = None  # set by ingest
    stems: dict[str, str] = {}  # stem name → wav path
    beat_grid: BeatGrid | None = None
    # Derived bar grid. Additive with a default, so Documents cached before
    # this field existed still deserialize — no separation or beat grid is
    # invalidated by its introduction.
    meter: list[MeterSection] = []
    notes: dict[str, list[NoteEvent]] = {}
    swing: list[SwingSpan] = []
    quantized: dict[str, list[QuantizedNote]] = {}
    # Set by notate. Additive with a default, so every Document cached before
    # M6 still deserializes and no separation or transcription is invalidated.
    notation: Notation | None = None
