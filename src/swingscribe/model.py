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
    # Other pitches struck AND released with this one, so the page writes a
    # chord and not two notes fighting for one grid position. The transcriber
    # never fills this: a line is one note at a time. It is the listener,
    # enabling a note the piano model heard beside the line's
    # (notation.with_chords). MIGRATION: additive with a default, so every
    # cached Document deserializes unchanged and no cache key moves.
    chord: list[int] = []
    # This note LEADS INTO the next one, and a page writes the two as one note
    # (`transcribe.mark_lead_ins`, docs/scoops.md): a SCOOP -- short, a
    # semitone under the next and touching it, its pitch never settled, no
    # attack where the next begins -- or a RE-ATTACK -- short, the next
    # note's own pitch, touching it. Both are heard: WJazzD's annotators mark
    # them as notes, so the line keeps them; quantize's `absorb_lead_ins`
    # folds them into the note they lead into, a scoop as its grace note.
    # MIGRATION: additive with a default, like `chord`: a cached Document
    # deserializes with nothing marked, and the keys that produce marked
    # notes are the transcribe keys that carry the lead-in settings.
    lead_in: bool = False
    # Which horn of a multi-horn head played this note, as HEARD: 1 the upper,
    # 2 the lower (`voices.assign`). A note with no partner -- one horn alone,
    # or a unison heard as one note -- is 1, so a page writes it once. Every
    # other ensemble's line is all 1. The page's writing conventions (an
    # octave moved, a unison written once) are notation's, never this
    # field's. MIGRATION: additive with a default, like `chord`: every cached
    # Document deserializes as voice 1, and only the multi-horn transcribe
    # key -- new with it -- produces a 2.
    voice: int = 1


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
    chord: list[int] = []  # see NoteEvent.chord; carried, never derived here
    # Grace notes written before this one, sounding pitches: a scoop the
    # transcriber marked (NoteEvent.lead_in), folded onto the note it leads
    # into, which then starts where the scoop did. Additive with a default.
    grace: list[int] = []


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
    # Which voice on the staff this note belongs to. 1 is the line; 2 is the
    # piano review overlay (the rest of the top two notes the oracle heard),
    # written as a second voice on the SAME staff so the listener can delete
    # what they do not want without leaving the score.
    #
    # MIGRATION: additive with a default, so every cached Notation written
    # before this deserializes unchanged as voice 1, and no cache key moves —
    # keys come from stage config, not from the schema. Nothing is invalidated.
    voice: int = 1
    # The other pitches of a chord this note heads. Every tie segment of a
    # chorded note carries the same list: chord members strike and release
    # together, so they split at bar lines and tie exactly as their head does.
    # Written as <chord/> notes in MusicXML; rests never carry one.
    chord: list[int] = []
    # Which staff of a two-staff (piano) page: 1 is the treble, the right
    # hand; 2 the bass, the left. A one-staff page is all 1. MIGRATION:
    # additive with a default, like `voice`: every cached Notation
    # deserializes as staff 1 and no cache key moves.
    staff: int = 1
    # Grace notes before this note (sounding pitches; QuantizedNote.grace),
    # on the FIRST piece of a tied note only and never on a rest. Written as
    # <grace/> notes ahead of it. MIGRATION: additive with a default, like
    # `staff`: every cached Notation deserializes with none.
    grace: list[int] = []
    # The stem direction a reader must draw, "up" or "down", or "" to let it
    # choose. Two horns on one staff (notation.merge_horn_voices) stem the
    # upper voice up and the lower down in a bar that holds both, and leave
    # a bar of one voice to the reader. MIGRATION: additive with a default:
    # every cached Notation deserializes as automatic, and no key moves.
    stem: str = ""
    # Written with print-object="no": a rest that keeps its voice's bar
    # adding up but is not drawn -- the lower horn's rests on a two-horn
    # staff, where a reader sees one line resting, not two. MIGRATION:
    # additive with a default, like `stem`.
    hidden: bool = False


class ChordDegree(BaseModel):
    """One alteration of a chord symbol, as MusicXML's <degree>: value 9,
    alter -1, type "add" is the flat nine of C7b9. `type` is "alter" when the
    kind already holds the degree (the flat five of a dominant), "add" when it
    does not, "subtract" for a degree left out."""

    value: int
    alter: int = 0
    type: str = "add"


class ChordSymbol(BaseModel):
    """A chord symbol over the page (roadmap O4), from changes the listener
    typed (chords.py) -- never recognised from the audio.

    CONCERT pitch, like every note: the root and bass are transposed once, at
    export, with the part (stages/export.py). `kind` is MusicXML's <kind>
    value, the chord's meaning; `text` is the suffix as the listener spelled
    it ("-7", "m7b5", "Δ"), which is what a reader prints, because a jazz
    chart's spelling is a house style the kind value cannot carry.
    """

    beat: float = 0.0  # quarter notes from the start of its bar
    root_step: str = "C"
    root_alter: int = 0
    kind: str = "major"
    text: str = ""
    degrees: list[ChordDegree] = []
    bass_step: str | None = None  # a slash chord's bass: C7/E
    bass_alter: int = 0


class NotatedBar(BaseModel):
    number: int
    time_signature: tuple[int, int]
    notes: list[NotatedNote] = []
    # Chord symbols over this bar, in beat order (chords.place). MIGRATION:
    # additive with a default, like NotatedNote.voice: every cached Notation
    # deserializes with none and no cache key moves -- keys come from stage
    # config, and no stage writes this; only the GUI's page assembly does.
    harmony: list[ChordSymbol] = []


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
    # The page is written at TWICE the performed pulse — a ballad's 32nd runs
    # as sixteenths, "Notated in double time" at the top. A listener's choice
    # (sidecar), never inferred: the Omnibook writes these solos as literal
    # 32nds, so that stays the default. Every notated position and value is
    # in DOUBLED units when set; scoring against a true-meter reference must
    # halve them (benchmark.notation_notes), and readability must NOT — the
    # page is read as written.
    double_time: bool = False
    # 2 is a grand staff: the right hand on a treble staff over the left on
    # a bass staff (NotatedNote.staff), the listener's choice for a piano
    # texture. MIGRATION: additive with a default of 1, nothing moves.
    staves: int = 1


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
