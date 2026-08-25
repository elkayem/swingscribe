"""Configuration: one object threaded through the pipeline (plan §2).

Loaded from config/default.yaml (or a user-supplied YAML); individual values
can be overridden via SWINGSCRIBE_* environment variables, e.g.
SWINGSCRIBE_TRANSCRIBE__ENSEMBLE=solo-piano.

Each stage's section feeds the cache key via Config.stage_config(), so config
values must stay JSON-serializable.
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root default; fine for development checkouts, which is all M0 supports.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


class IngestConfig(BaseModel):
    sample_rate: int = 44100


class SeparateConfig(BaseModel):
    # `htdemucs_ft` is a BAG OF FOUR fine-tuned models and takes 4x as long
    # (~11 min for a 10-minute track on this machine's CPU, against ~2.8).
    # Measured over the 9 benchmark solos that used it, it buys nothing:
    # plain htdemucs scores mean note F1 0.759 against ft's 0.752, better on
    # 8 of the 9. So the default is the fast one.
    #
    # `htdemucs_6s` is still worth choosing by hand for a HORN solo over a
    # pianist — it routes piano into its own stem, so "other" comes back
    # cleaner (Walkin' 0.829 against htdemucs's 0.701). It is the wrong
    # choice when the soloist IS the pianist, for exactly the same reason
    # (docs/benchmark-deficiencies.md D3).
    model: str = "htdemucs"
    device: str = "auto"  # auto | cuda | cpu


class BeatsConfig(BaseModel):
    dbn: bool = False  # never True — we skip madmom entirely (plan §2)
    # Prefer a separated drum stem over the full mix, when the Document has
    # one. Default OFF, and the pipeline runs beats before separate, so
    # nothing has one: measured over 11 WJazzD-matched solos the mix tracks
    # BETTER (mean beat F1 0.929 vs 0.816) as well as ~100x faster. Kept as a
    # switch because the reasoning that chose the stem — the ride cymbal is
    # the cleanest pulse in jazz — is sound for a tune the mix mistracks, and
    # a caller that wires beats after separate can still use it.
    use_drum_stem: bool = False
    checkpoint: str = "final0"
    device: str = "auto"  # auto | cuda | cpu
    # Drum stem must carry at least this fraction of the mix's RMS energy,
    # else fall back to the full mix. Relative, not absolute: a brushes
    # ballad leaves a technically-nonsilent but useless drum stem.
    min_drum_mix_ratio: float = 0.05
    # Known tempo in BPM; corrects half/double-octave tracking errors.
    tempo_hint: float | None = None


class TranscribeConfig(BaseModel):
    ensemble: Literal["horn-led", "trio", "solo-piano"] = "horn-led"
    # Which separated stem carries the solo. htdemucs_ft gives
    # drums/bass/other/vocals; htdemucs_6s adds guitar/piano.
    stem: str = "other"
    # Analyse only [start, end] seconds of the track; a null end means "to the
    # end of the track". Lives HERE and not on ingest deliberately: separation
    # and beat tracking stay whole-file (Demucs degrades on short crops, and
    # beat tracking wants context), so switching to a different solo in the
    # same tune re-runs only this stage. Note onsets are still reported in
    # whole-track time.
    region: tuple[float, float | None] | None = None
    fmin_hz: float = 55.0  # A1 — bari sax bottom; constrains CREPE against octave errors
    fmax_hz: float = 1600.0  # ~G6 — above alto altissimo
    crepe_model: str = "full"  # full | tiny (tiny is ~10x faster on CPU, less accurate)
    device: str = "auto"  # auto | cuda | cpu
    # CREPE periodicity gate. torchcrepe's docs suggest ~0.21 for clean solo
    # audio; we sit at 0.5 because the "other" stem's piano/bass bleed is
    # itself pitched and keeps periodicity moderately high during rests —
    # biasing up trades slightly clipped note tails for fewer phantom notes.
    voicing_threshold: float = 0.5
    # Second gate: frame RMS must be within this many dB of the stem's loud
    # reference (95th-percentile frame RMS). Periodicity alone cannot reject
    # QUIET pitched bleed between phrases; energy can.
    silence_floor_db: float = -40.0
    # A detected onset only splits a held note when the note's OWN harmonics
    # show a fresh attack of at least this many dB. Broadband onset detection
    # fires on every transient in the stem, so without this a comping piano
    # shatters a sustained horn note into repeated fragments (open-issue #1).
    # Set to 0 to disable corroboration and split on every onset.
    onset_rise_db: float = 3.0
    # A rise alone is weak evidence on a held note: vibrato swells the
    # harmonics by several dB with no re-articulation. So when the pitch is
    # the SAME note either side of the onset, requiring the energy to dip
    # below the sustain first should tell a tongued repeat from a swell.
    #
    # It does — and it LOSES overall, so it ships off. Measured against
    # WJazzD it un-fragments the held notes it was built for and suppresses
    # more genuine repeated notes than it saves: mean note F1 0.791 at 0.0,
    # 0.775 at 2dB, 0.774 at 3dB, down on every tune. Kept because the
    # mechanism is sound and a better rise/dip test may yet win; do not turn
    # it on without re-running scripts/run_eval.py.
    onset_dip_db: float = 0.0
    onset_window_ms: float = 60.0  # lookback/lookahead for that rise
    min_note_ms: float = 60.0  # drop specks shorter than a fast bebop 16th
    pitch_persist_ms: float = 60.0  # a new pitch must hold this long to split a note
    silence_gap_ms: float = 40.0  # unvoiced dropouts shorter than this bridge a phrase
    median_filter_ms: float = 50.0  # f0 smoothing kernel — flattens vibrato wobble
    # Viterbi continuity for f0 decoding: the log-probability charged per
    # CREPE pitch bin (20 cents) of movement between adjacent 10ms frames.
    # 0 restores the per-frame weighted-argmax decoding M3 shipped with, which
    # has no memory at all and so follows whichever source is loudest in each
    # frame (open-issue #8). Above 0, an excursion that leaves the soloist and
    # comes back pays the cost twice while a real melodic interval pays once.
    # Scale: 5 bins = 1 semitone, 60 bins = an octave.
    pitch_step_cost: float = 0.2
    # ── M7b: the polyphonic piano model as a second opinion ──────────────
    # Consult a polyphonic piano model and use it to correct octaves and
    # reject notes it will not vouch for (src/swingscribe/corroborate.py).
    # Costs an extra ~0.36x realtime over the span.
    #
    # OFF by default because it needs the `ml` group and a 172MB checkpoint,
    # and because it is only meaningful when the soloist is a pianist — the
    # oracle would reject a saxophone wholesale. `ensemble` is what turns it
    # on: trio and solo-piano both do.
    piano_oracle: bool = False
    # Correct a note to the oracle's octave where they agree on pitch class.
    # Raises RECALL (a note at the right octave now matches).
    piano_snap_octaves: bool = True
    # Drop notes the oracle will not corroborate. Raises PRECISION. Measured
    # over both piano solos with hand transcriptions, the two together beat
    # either alone on both: Giant Steps note F1 0.705 -> 0.765, Lover Come
    # Back 0.648 -> 0.698 (docs/m7b-piano.md).
    piano_reject_uncorroborated: bool = True
    # How far apart the two detectors may place the same note. 0.05 was
    # tighter at a real cost in recall, 0.20 let unrelated neighbours vouch
    # for each other; 0.10 was best on both solos.
    piano_onset_tolerance: float = 0.10

    @property
    def uses_piano_oracle(self) -> bool:
        """Whether to consult the piano model for this ensemble.

        `piano_oracle` forces it on; otherwise the ensemble decides, which is
        the routing plan §5 stage 3 specifies. A horn-led solo must never get
        it — a piano model asked about a saxophone vouches for nothing, and
        rejection would then delete the entire line.
        """
        return self.piano_oracle or self.ensemble in ("trio", "solo-piano")


class MeterConfig(BaseModel):
    """Bar-grid derivation, and the user's overrides of it (docs/meter-plan.md).

    These are the knobs the GUI's downbeat click and time-signature menu write
    to. They belong in config precisely so they reach the cache key and
    therefore the transcription — there is no side channel.
    """

    # "4/4", "3/4", "6/8", "6/4", ... or null to use the default (4/4).
    time_signature: str | None = None
    # Tracked beats per bar. Null derives it from the time signature, which is
    # not always the numerator: 6/8 counted in 2 has two dotted-quarter pulses.
    pulses_per_bar: int | None = None
    # Seconds. A beat that is beat 1; the grid snaps to the nearest one. Stored
    # as time rather than a beat index so it survives a re-tracked grid
    # (different separation model, tempo hint) instead of silently sliding.
    anchor: float | None = None
    # Heavier line every N bars — jazz solos are whole choruses. Null/0 = off.
    bars_per_chorus: int | None = None
    # Seconds. Where the tune's form starts, which is not always where the audio
    # does: an intro is not part of the song structure. Bar 1 and the chorus
    # count both start here; bars before it are drawn but not numbered.
    form_start: float | None = None
    # Neural beat trackers routinely emit nothing for the first few seconds —
    # Corner Pocket is at full level from 0.0s but has no beat until 5.86s. Where
    # the pulse at the edge is steady, continue it out to the ends of the track
    # rather than leaving the head and tail barless.
    extend_to_edges: bool = True
    max_extend_seconds: float = 12.0
    # Insert beats the tracker dropped. Measured need: Corner Pocket's first 23
    # seconds are tracked at half rate, which would otherwise make every bar
    # there twice too long.
    repair_beats: bool = True
    # A gap wider than this many pulses is a hole in the tracking, not a run of
    # missed beats; it breaks the metrical span instead of being filled.
    max_implied_run: int = 8
    # A beat is metrical when its interval is within this fraction of the local
    # median; runs shorter than min_span_beats get no bar lines at all.
    stability_tolerance: float = 0.15
    min_span_beats: int = 8


class SwingConfig(BaseModel):
    # Beats per BUR estimate. Windows tile the grid, they do not slide — see
    # swing.swing_spans. 16 is four bars of 4/4: long enough to gather
    # offbeats, short enough to see a player change feel mid-chorus.
    window_beats: int = 16
    # Which stem's notes carry the solo. None means "whatever transcribe
    # analysed", which is the right default and the only one that stays
    # correct when the GUI points transcribe at a different stem.
    stem: str | None = None
    # Onsets in this phase band are treated as offbeats. Below the floor are
    # downbeat attacks, which carry no swing information.
    offbeat_low: float = 0.35
    offbeat_high: float = 0.85
    # A window with fewer offbeats than this gets NO span rather than a
    # guessed one — a rest or a passage of whole notes is not evidence.
    min_onsets: int = 4
    # φ above this reads as swung rather than straight (0.5 is dead straight;
    # 0.55 is BUR 1.22, about the least swing anyone would notate).
    swung_phase_threshold: float = 0.55
    # ...and only if it is that far above straight by at least this many
    # standard errors. This is the real classifier — see swing.swing_spans.
    min_z: float = 2.0
    # A weak floor on peak concentration, as a multiple of what pure noise
    # gives. Deliberately weak: measured, concentration barely separates real
    # swing from random scatter at this window size, so it can only reject the
    # most obviously scattered windows.
    min_peak_ratio: float = 1.2
    # Histogram bin for locating the peak, and the half-width of the cluster
    # whose median becomes the estimate. The bin is deliberately coarser than
    # the precision we need; the cluster median supplies the precision.
    bin_width: float = 0.02
    cluster_width: float = 0.06
    # Relative BUR uncertainty at which confidence is halved. The estimator
    # sits at its sampling limit, so at fast tempos a window can be certain
    # the feel is swung while leaving BUR loose by ~10%; this is what makes
    # that visible downstream rather than hiding it behind a tight cluster.
    target_precision: float = 0.10


class QuantizeConfig(BaseModel):
    # Grid resolution as a note value: 16 means sixteenth notes, i.e. four
    # steps per quarter-note beat.
    resolution: int = 16
    # Which stem's notes to quantize. None means "whatever transcribe
    # analysed", which stays correct when the GUI repoints transcribe.
    stem: str | None = None
    # BUR at or below this reads as NO SWING and is never warped. Measured
    # against 359 hand-annotated WJazzD solos: onsets with no feel at all
    # still produce BUR ~1.56, because the offbeat region is asymmetric about
    # 0.5 (docs/wjazzd.md). Warping on a reading near 1.5 injects error rather
    # than removing it — LATIN, BALLAD and FUNK solos all sit at 1.31-1.53.
    straight_bur_ceiling: float = 1.6
    # Let a beat snap to a ternary grid when its notes fit one better. Without
    # this a genuine triplet figure is silently rewritten as a swung eighth
    # pair, which post-warp it closely resembles (plan §5).
    allow_triplets: bool = True
    # How many onsets a beat needs before a TERNARY grid may be chosen for it.
    # You cannot see a triplet in two notes, and post-warp two notes in a beat
    # are an eighth pair by construction — letting arithmetic alone decide
    # notated a swung pair as a triplet on a third of all intervals. 1 or 2
    # restores the pre-M6 behaviour.
    min_onsets_for_tuplet: int = 3
    # How much worse, in beats of mean snap error, a COARSER grid may be and
    # still win. Parsimony: reading a sixteenth out of a beat that only shows
    # an eighth pair is how a swung pair becomes a dotted eighth. 0 keeps the
    # old least-error rule.
    #
    # 0.05 is not tuned on the notation score, which rises monotonically to
    # "write everything as eighth notes" and would happily overfit three
    # bebop solos. It is the largest value that keeps quantize inside its OWN
    # acceptance criterion — plan §5's 20ms round trip, which measures what
    # coarsening costs the performance rather than what it buys the page.
    # At 0.05 the worst tune replays at 18.7ms; at 0.08 it is 21.0ms.
    grid_slack: float = 0.05


class NotateConfig(BaseModel):
    """Stage 6. What the page says, as opposed to what was played."""

    # The part's key. Written pitch minus sounding pitch is a property of the
    # instrument, not of the audio: nothing in the signal says which horn it
    # was, so it is config and never inferred.
    transposition: Literal["C", "Eb", "Bb", "Bb-tenor"] = "C"
    # Which quantized voice to notate; empty means the only one there is.
    stem: str = ""
    title: str = ""
    # A note whose PLAYED length reaches this fraction of the gap to the next
    # note would be written as filling that gap. Humans notate that way — 90
    # to 93% of the notes in the hand transcriptions fill their gap exactly
    # and none exceed it — but so, already, do we: `notate.without_overlap`
    # truncates each note at the next onset, and 93-96% of our notated notes
    # come out filling their gap without any help. So this changes almost
    # nothing (mean note-value agreement 0.4628 off, 0.4665 at 0.75) and
    # ships OFF. Kept because the measurement is worth not repeating.
    legato_fill: float = 0.0

    @property
    def transpose(self) -> int:
        """Semitones from sounding to written.

        A Bb trumpet part is written a major second above concert; a Bb TENOR
        part is written a major ninth above, an octave further, so that the
        horn's range sits on a treble staff. They are the same key and
        different transpositions, which is why "Bb" alone cannot say it — and
        both benchmark tenor transcriptions came out +12 against our concert
        pitch precisely because of this (docs/m3-benchmark.md).
        """
        return {"C": 0, "Eb": 9, "Bb": 2, "Bb-tenor": 14}[self.transposition]


class ExportConfig(BaseModel):
    formats: list[str] = ["musicxml", "midi", "json"]


class GuiConfig(BaseModel):
    """The local selection/audition GUI (plan §13). NOT a pipeline stage —
    Config.stage_config() is only ever called with stage names, so nothing here
    reaches a cache key. Changing these values must never invalidate a
    six-to-thirteen-minute separation."""

    host: str = "127.0.0.1"  # localhost only; this serves local files by path
    port: int = 8420
    open_browser: bool = True
    # Where the track picker looks. null = the directory swingscribe was run from.
    library_dir: str | None = None
    # Separation models offered on the audition screen, in menu order — the
    # fast default first, then the two that are worth waiting for when the
    # default disappoints. See SeparateConfig for what each one buys.
    models: list[str] = ["htdemucs", "htdemucs_6s", "htdemucs_ft"]


# Sections that are pipeline stages, and therefore feed cache keys. Membership
# is explicit rather than "any BaseModel attribute" so that adding a non-stage
# section — gui, say — cannot accidentally become part of a key and invalidate
# separations that cost thirteen minutes each to rebuild.
STAGE_SECTIONS = frozenset(
    {
        "ingest",
        "separate",
        "beats",
        "transcribe",
        "meter",
        "swing",
        "quantize",
        "notate",
        "export",
    }
)


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SWINGSCRIBE_", env_nested_delimiter="__")

    cache_dir: Path = Path(".swingscribe-cache")

    ingest: IngestConfig = IngestConfig()
    separate: SeparateConfig = SeparateConfig()
    beats: BeatsConfig = BeatsConfig()
    transcribe: TranscribeConfig = TranscribeConfig()
    meter: MeterConfig = MeterConfig()
    swing: SwingConfig = SwingConfig()
    quantize: QuantizeConfig = QuantizeConfig()
    notate: NotateConfig = NotateConfig()
    export: ExportConfig = ExportConfig()
    gui: GuiConfig = GuiConfig()

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "Config":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**data)

    def stage_config(self, stage_name: str) -> dict[str, Any]:
        """The config section for one stage, as the plain dict fed to its cache key."""
        if stage_name not in STAGE_SECTIONS:
            raise KeyError(f"unknown stage: {stage_name!r}")
        section = getattr(self, stage_name, None)
        if not isinstance(section, BaseModel):
            raise KeyError(f"unknown stage: {stage_name!r}")
        return section.model_dump(mode="json")
