"""The data contract (plan §3).

Everything hangs off one Document. Stages take (Document, Config) and return
an updated Document; all shared types live here and nowhere else.

Changing anything in this module invalidates cached artifacts — flag the
migration impact whenever you touch it.
"""

from pydantic import BaseModel


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
    stems: dict[str, str] = {}  # stem name → wav path
    beat_grid: BeatGrid | None = None
    notes: dict[str, list[NoteEvent]] = {}
    swing: list[SwingSpan] = []
    quantized: dict[str, list[QuantizedNote]] = {}
