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
