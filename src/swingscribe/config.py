"""Configuration: one object threaded through the pipeline (plan §2).

Loaded from the packaged default-config.yaml (or a user-supplied YAML); values
can be overridden via SWINGSCRIBE_* environment variables, e.g.
SWINGSCRIBE_TRANSCRIBE__ENSEMBLE=solo-piano.

Each stage's section feeds the cache key via Config.stage_config(), so config
values must stay JSON-serializable.
"""

from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, model_serializer
from pydantic_settings import BaseSettings, SettingsConfigDict

# Shipped INSIDE the package (it used to be `config/default.yaml` at the repo
# root, which a wheel install or a frozen build does not have): a checkout,
# a wheel and a PyInstaller bundle all find it beside this module. Not under
# a `config/` directory, which would shadow this module's name.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "default-config.yaml"

# Named as types so the GUI can offer exactly what the config accepts. A menu
# built from a hand-copied list is a menu that drifts out of step with the
# validator and starts offering values that will be rejected.
# "multi-horn" is a head played by two horns in harmony (docs/multi-horn.md):
# Basic Pitch hears both, `voices.assign` says which note is which horn's,
# and the page writes them as two voices on one staff. It never consults the
# piano model.
Ensemble = Literal["horn-led", "trio", "solo-piano", "multi-horn"]
Transposition = Literal["C", "Eb", "Bb", "Bb-tenor"]
ENSEMBLES: tuple[str, ...] = get_args(Ensemble)
# Which detector supplies a pianist's line (TranscribeConfig.piano_line). The
# GUI's menu is built from this, never hand-copied.
LINES: tuple[str, ...] = ("crepe", "oracle")
TRANSPOSITIONS: tuple[str, ...] = get_args(Transposition)
# The rhythm a page is written in when the sidecar has chosen none
# (QuantizeConfig.timing), per ensemble. A multi-horn head is SWING, the
# listener's decision of 2026-10-09 after the head measured level with
# literal eighths: it writes eighths where a beat shows no more, 16ths
# where one does, triplets, and the "Swing" marking, with the lag read
# once over both horns (`notation.notation_for_span`). "Literal 8ths" and
# "Literal 16ths" stay in the menu for a straight-eighth head (bossa,
# Latin, even eighths). Read through `notation.timing_for`.
ENSEMBLE_TIMINGS: dict[str, str] = {"multi-horn": "swing"}
# How quantize writes rhythm (QuantizeConfig.timing): "swing" reads the feel
# out and writes swung eighths as eighths under a "Swing" marking; the
# literal ones snap every onset to the nearest grid point, feel and all --
# 16ths or 32nds, or "literal-8": eighths at a tempo of 160 bpm and over,
# where a human writes the running value as the eighth (D11), and 16ths
# under it; any grid refined only where it cannot keep a beat's onsets
# apart (`quantize.literal_notes`).
Timing = Literal["swing", "literal-8", "literal-16", "literal-32"]
TIMINGS: tuple[str, ...] = get_args(Timing)
# The key signatures a listener may choose instead of the detected one
# (NotateConfig.key), by fifths: sharps positive, flats negative. Each names
# its major and its relative minor, because they share one signature and
# the listener knows which the tune is in. Six either way, as the detector's
# own spellings run (F# rather than Gb at +6, Db rather than C# at -5).
KEY_SIGNATURES: dict[int, str] = {
    -6: "G♭ major / E♭ minor",
    -5: "D♭ major / B♭ minor",
    -4: "A♭ major / F minor",
    -3: "E♭ major / C minor",
    -2: "B♭ major / G minor",
    -1: "F major / D minor",
    0: "C major / A minor",
    1: "G major / E minor",
    2: "D major / B minor",
    3: "A major / F♯ minor",
    4: "E major / C♯ minor",
    5: "B major / G♯ minor",
    6: "F♯ major / D♯ minor",
}
# Which of a pianist's notes reach the roll and the page: the melody line
# (with any candidates switched on), or everything the piano model heard.
# A per-track GUI choice (sidecar `piano_notes`), never a stage setting.
PIANO_NOTES: tuple[str, ...] = ("line", "all")


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
    #
    # `bsroformer_sw` (BS-Roformer-SW through python-audio-separator, the
    # `roformer` dependency group) is the six-stem model that, measured
    # 2026-09-02, put EVERY benchmark horn in `other` and every pianist in
    # `piano`, and re-ran the whole sheet at WJazzD note F1 0.790 -> 0.858
    # paired over 61 solos (docs/separation-research.md). It is the DEFAULT
    # since then, on the listener's condition that it prove demonstrably
    # better. It costs about nine times htdemucs' CPU time and has no
    # progress callback; what makes that livable is `span` below — the GUI
    # separates the selected solo, not the record — and the estimate the
    # Separate button shows. `swingscribe run` over a whole file pays the
    # full nine times; pick htdemucs there when speed matters.
    model: str = "bsroformer_sw"
    device: str = "auto"  # auto | cuda | cpu (demucs only; the Roformer runs on cpu)
    # Separate only this [start, end] of the track (seconds), plus
    # `span_margin_s` either side for the model's context. The stems written
    # are still full-length wavs, silent outside the span, so nothing
    # downstream changes — only the separator's work does. null separates the
    # whole file, and a whole-file set on disk serves any span. This is what
    # makes a separator nine times slower than htdemucs usable on a CPU: the
    # listener selects the solo first and separates that (stages/separate.py).
    span: tuple[float, float] | None = None
    span_margin_s: float = 3.0


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
    # Track the audio played at this speed and scale the beats back. At 0.5
    # a tune beyond the tracker's range is heard at half its tempo, where
    # the tracker is at home: Bud Powell's Oblivion at quarter = 280 is
    # tracked at 79 bpm, one beat per BAR (its activation repeats every
    # 0.86 s and has no peak at the 0.214 s beat), and at half speed at 273
    # -- page rhythm 0.061 -> 0.853 against Powell's PDF page. Never a
    # default: on a tune the tracker already reads, half speed can double
    # the pulse. The listener asks for it per track (sidecar `fast_tempo`,
    # `gui.musicxml.grid_config`), and the grid it makes is cached under its
    # own key, so the default chain -- and every separation and
    # transcription keyed below it -- never moves.
    speed: float = 1.0

    @model_serializer(mode="wrap")
    def _key_stable_dump(self, handler):
        """Leave `speed` out of the dump at 1.0, so every beats key -- and
        every key chained below it -- reads exactly as it did before the
        field existed."""
        data = handler(self)
        if data.get("speed") == 1.0:
            data.pop("speed", None)
        return data


class TranscribeConfig(BaseModel):
    ensemble: Ensemble = "horn-led"
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
    # A new pitch must hold this long to split a note. 40 with the floor kept
    # at 60: re-segmenting the cached traces of 68 WJazzD horns on two
    # independent paths read +0.0027 to +0.0028 mean note F1 (41-42 solos up,
    # 25 down, paired t 2.5), precision unchanged. The run-through error
    # (`absorbed`, 798 -> 252) IS this rule; the cost is `split_sustain`
    # +124 (docs/error-taxonomy-review.md, 3b.1). Shipped 2026-09-07 with
    # transcribe.CACHE_VERSION 2.
    pitch_persist_ms: float = 40.0
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
    # ── The line's own register and loudness as a bleed rejector ─────────
    # A single melodic line stays near itself: measured over 23 solos (13
    # WJazzD, 10 hand-scored), a note more than an octave BELOW the median
    # pitch of its neighbours within `line_window_s`, or more than
    # `line_loudness_floor_db` quieter than their median loudness, is bleed
    # far more often than it is the soloist. htdemucs_6s put Bird's alto in
    # the `guitar` stem WITH the piano's comping on Ornithology, so the
    # rejects were inside the lead stem and no cross-stem test could see them
    # (transcribe.reject_line_outliers). Floors are relative to the line, not
    # the stem: `silence_floor_db` gates on the stem's LOUDEST frames and
    # lets a -25 dB comp through between phrases. Measured with the green
    # bar's own pitch F1: every horn track up (+0.007 to +0.062), mean
    # WJazzD +0.026, hand-scored +0.016, no track down more than 0.004; the
    # surface is flat across windows of 1.5-3 s and floors of 10-16. The
    # loudness floor is applied to HORNS ONLY: a pianist plays soft notes on
    # purpose and Carl Perkins lost 0.012 to it, while the register floor
    # removes left-hand notes and lifts every piano solo (+0.010 to +0.033).
    #
    # The loudness floor's depth is a precision/recall trade and the table
    # is on the record: over the 18 horn tracks it removes, at 12 dB, 391
    # bleed notes and 91 REAL ones (a hand transcriber wrote them — ghosted
    # notes inside a phrase, Art Pepper lost 7); at 14 dB, 333 and 61; at 16,
    # 280 and 42. Isolation does not separate the two (bleed sits as close
    # to other notes as a ghost note does). 14 keeps nearly all of the pitch
    # gain (+0.024 against +0.026) with no track's F1 down on the table, and
    # a note 14 dB under its neighbours is not one a listener calls clearly
    # audible. 0 disables either floor.
    line_window_s: float = 2.0
    line_register_floor: float = 12.0  # semitones below the local median pitch
    line_loudness_floor_db: float = 14.0  # dB below the local median note loudness
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
    # Also surface the REST of the top two notes the oracle heard, as a review
    # overlay (corroborate.second_voice). The listener asked to see the top one
    # or two and delete what they do not want, which makes recall the target:
    # top-2 holds the note a human notated 84-96% of the time against 0.54-0.74
    # for the line alone.
    #
    # OFF by default, and it must stay off for any measurement: the second
    # voice is not part of the transcription and never enters the scored note
    # list. It rides on FrameDiagnostics, which nothing downstream consumes.
    #
    # The GUI no longer turns it on either. Shown as an overlay it is most of
    # the left hand and the listener could not read it; the same recall is
    # available inside ONE line through `piano_fill_gaps`, which is what
    # replaced it as the default answer to "you are missing notes".
    piano_second_voice: bool = False
    # Merge the oracle's notes into the line wherever the line has a HOLE, at
    # the line's own register (corroborate.fill_gaps). This is the second
    # opinion used the way the listener asked for it: one monophonic line, as
    # complete as we can make it, rather than a second voice to read past.
    #
    # ON by default for piano, because the trade goes the listener's way:
    # measured over four piano solos with hand transcriptions, recall
    # 0.680 -> 0.744 against precision 0.677 -> 0.666, and all four improved on
    # recall AND F1. Deleting a note that does not belong is cheap; hearing one
    # that was never written is not. `uses_piano_oracle` still gates it, so a
    # horn never sees it.
    piano_fill_gaps: bool = True
    # ── issue #8: which detector supplies the LINE for a pianist ─────────
    # "crepe": the monophonic line, corrected and filled by the piano model
    # (everything above). "oracle": the line is PICKED from the piano model's
    # full polyphonic output by `line_selection.pick_line` — one note per
    # simultaneity, chosen as a sequence by loudness rank and register
    # continuity, with silence allowed between phrases. Measured over the ten
    # piano spans with references: mean pitch F1 0.8017 -> 0.8655, better or
    # equal on 9 of 10; then as NOTATION against the seven hand scores:
    # pitch F1 0.788 -> 0.838, note F1 0.486 -> 0.515, notated rhythm 0.780
    # -> 0.824 on all seven, WJazzD note F1 level (0.904 -> 0.898 over four)
    # (docs/issue8-line-selection.md). The pianist default since 2026-09-18,
    # the listener's call on that table; the GUI offers "crepe" as the other
    # take to compare by ear. Meaningless for a horn: it is read only where
    # `uses_piano_oracle` is true, and it never enters a horn's cache key.
    piano_line: Literal["crepe", "oracle"] = "oracle"  # one of LINES
    # The picker's two weights, in velocity-rank units. A semitone of leap
    # costs about two percentile points of loudness; a note must beat silence
    # by ten. The surface is smooth (0.83-0.87 across continuity <= 0.05).
    piano_line_continuity: float = 0.02
    piano_line_skip_margin: float = 0.10
    # The piano model's onsets LEAD a human annotator's: 16-24 ms early on
    # every WJazzD pianist (median over matched notes; CREPE's line on the
    # same stems reads 0 to -9 ms). Against a 50 ms tolerance that lead
    # turned twelve timing errors into a hundred and put the picker under
    # the CREPE line it had beaten on pitch. Added to every picked onset;
    # 20 ms is the measured median lead, not the F1-optimal value
    # (docs/error-taxonomy-review.md, 3b.2).
    piano_line_onset_shift_ms: float = 20.0
    # ── A2: Basic Pitch fills the holes in a HORN's line ─────────────────
    # CREPE's segmentation drops the short note: it hears 49% of WJazzD's
    # notes under 60 ms, Basic Pitch (Spotify, Apache-2.0, a 230 KB ONNX
    # graph vendored in the package -- swingscribe/basic_pitch.py) hears 60%.
    # As the LINE the model loses in every form (its weak onsets on a horn
    # stem are the comping); as a hole-filler -- `corroborate.fill_gaps`,
    # the pianist's, with Basic Pitch as the oracle -- it read WJazzD note F1
    # 0.8580 -> 0.8650, +0.0070 [+0.0051, +0.0093], 49 up / 1 down over 73
    # (+0.0067 on the 51 not used to choose these numbers) and the
    # Omnibook's sub-eighth recall 0.660 -> 0.703, 21 of 22 sides up
    # (docs/frontend-bakeoff.md). ON by default for horns; a pianist never
    # reads it -- the pianist's line is the piano model's, and its key must
    # not move -- so `uses_piano_oracle` gates every use and the dump below.
    horn_fill_gaps: bool = True
    # The decode: an onset peak of at least this, a note held while the
    # frame activation stays over `horn_fill_frame_threshold`, and longer
    # than this many ms (Basic Pitch's own 127.7 ms default deletes exactly
    # the notes in question: recall under 60 ms 0.098). The onset threshold
    # is the one that matters -- weaker onsets on a horn stem are the band;
    # 0.7-0.8 is a plateau on the tuning subset, 0.4 cost 16 of 22 solos.
    horn_fill_onset_threshold: float = 0.8
    horn_fill_frame_threshold: float = 0.3
    horn_fill_min_note_ms: float = 23.0
    # The hole: no line onset within this of the copied one (the piano's 60
    # ms keeps out exactly the short notes in question; 30-40 ms is the
    # plateau), and the model's amplitude at least this.
    horn_fill_gap_ms: float = 40.0
    horn_fill_min_confidence: float = 0.3
    # Basic Pitch's matched onsets sit 3-4 ms early on the tuning subset;
    # every copied onset is moved this much late.
    horn_fill_onset_shift_ms: float = 4.0
    # Take the recording's own tuning out of the pitch before notes are
    # rounded (`transcribe.tuning_offset`): the circular mean of every voiced
    # frame's distance from the equal-tempered grid. A 78 transferred a
    # little fast reads 15-30 cents sharp -- Lester Young's Tea for Two
    # +30, and 9.6% of its notes a semitone HIGH against 0.3% low; Hank
    # Mobley's Smokin' -30 and the other way (2026-10-08, the PDF pages).
    # Corrected only from `tuning_min_cents`: over the whole harness with
    # the correction from 10 cents, every one of the 19 tracks at 15 cents
    # or more heard better (+0.03 at 15-20, +0.13 past 25) and none worse,
    # while the 20 at 10-15 were a mixed bag holding every loss -- at that
    # size the estimate is as likely the player's own intonation as the
    # transfer (docs/pages-round2.md). On by default since 2026-10-08 (the
    # listener's call on that table); only CREPE's line is corrected, so
    # the fields are dumped only where they act (`uses_tuning_correction`):
    # a pianist on the piano model's line keyed exactly as before.
    tuning_correction: bool = True
    tuning_min_cents: float = 15.0
    # Mark the notes that LEAD INTO the next one (`transcribe.mark_lead_ins`,
    # NoteEvent.lead_in), which a page writes as one note (docs/scoops.md).
    # The line keeps them -- WJazzD's annotators mark both kinds as notes --
    # and quantize folds them (QuantizeConfig.absorb_lead_ins).
    #
    # A SCOOP: at most `glide_max_ms` long, a semitone under the next note
    # and touching it, no corroborated onset where the next begins, and its
    # frames on their own semitone at most `glide_max_stable` of the time (a
    # scoop slides; a chromatic approach note settles). The human pages
    # write the pair as ONE note two times in three, at the scoop's onset
    # three times in four; the settling test is the whole rule (without it
    # WJazzD would pay three times as much and the pages gain nothing more).
    #
    # A RE-ATTACK: at most `reattack_max_ms` long and touching a note of its
    # own pitch (the segmenter cut it on an onset). The pages write one note
    # 115 times in 134 (WJazzD's annotators about half the time). The other
    # way round -- a short note AFTER its pitch -- cost the PDF pages' rhythm
    # and is not marked.
    #
    # 0 ms marks none of a kind. CREPE's line only; the fields dump into the
    # key only there (`uses_lead_ins`).
    glide_max_ms: float = 100.0
    glide_max_stable: float = 0.5
    reattack_max_ms: float = 100.0
    # ── Multi-horn: two horns in harmony (docs/multi-horn.md) ─────────────
    # The notes are Basic Pitch's over the span, not CREPE's: on the Open
    # Sesame head CREPE follows the upper horn and jumps into the lower one,
    # while Basic Pitch hears both (82% of the sounding frames hold exactly
    # two notes). CREPE still runs for the roll's frame trace and its notes
    # are set aside, as a pianist's are on the piano model's line. The decode
    # is Step 0's: onset 0.5, frame 0.3, 23 ms -- never Basic Pitch's own
    # 128 ms minimum, which deletes every short note.
    multi_horn_onset_threshold: float = 0.5
    multi_horn_frame_threshold: float = 0.3
    multi_horn_min_note_ms: float = 23.0
    # Basic Pitch's onsets sit 3-4 ms early (the horn fill's measurement);
    # every note is moved this much late.
    multi_horn_onset_shift_ms: float = 4.0
    # `voices.assign`'s rules, in its own units: two notes overlap
    # MEANINGFULLY when they share at least `overlap_ms`, or `overlap_share`
    # of the shorter note; an overtone ghost (12, 19, 24, 28... semitones
    # over a note it sits inside) is dropped when its confidence is at most
    # `ghost_ratio` of that note's.
    multi_horn_overlap_ms: float = 60.0
    multi_horn_overlap_share: float = 0.3
    multi_horn_ghost_ratio: float = 0.6
    # The voices' rules themselves (voices.py, transcribe._hear_horns), as a
    # number: the GUI's review key hashes this config's dump and never
    # transcribe.CACHE_VERSION, so a change to the rules that moves no
    # field would serve every cached multi-horn review unchanged. Bump it
    # with any such change; like every field above it dumps only for a
    # multi-horn head. 2 (2026-10-09): tails cut at a new chord, split held
    # notes joined where CREPE holds them, lead-ins marked.
    multi_horn_version: int = 2

    @model_serializer(mode="wrap")
    def _key_stable_dump(self, handler):
        """Leave the line-selection fields OUT of the dump while the line is
        CREPE's or the track is a horn's, so those key exactly as they did
        before the fields existed.

        The horn hole-filler's fields are the same rule the other way round:
        they are dumped only where they act -- a horn with the fill ON -- so a
        pianist's key did not move when they arrived, and a horn with the
        fill switched OFF keys exactly as every horn did before (its cached
        CREPE passes are still whole). A horn with the fill on keys
        differently, as it must: its notes are different.

        Every transcribe cache key — the pipeline's stage key, the GUI's
        review key, run_eval's note fingerprint — is a hash of this dump. A
        new field with a default would otherwise turn every cached CREPE pass
        into a miss for a change that alters no note: hours of the batch and
        every review the listener has open. A pianist's oracle line dumps its
        fields and keys differently, as it must -- and those were already the
        second take's keys when it became the default (2026-09-18), so that
        flip moved no key either. A horn never reads the line
        (`uses_piano_oracle` gates every use of it), so its dump must not
        carry the default, whatever the default is.
        """
        data = handler(self)
        if data.get("piano_line") == "crepe" or not self.uses_piano_oracle:
            for name in (
                "piano_line",
                "piano_line_continuity",
                "piano_line_skip_margin",
                "piano_line_onset_shift_ms",
            ):
                data.pop(name, None)
        if not self.uses_horn_fill:
            for name in type(self).model_fields:
                if name.startswith("horn_fill_"):
                    data.pop(name, None)
        if not self.uses_tuning_correction:
            data.pop("tuning_correction", None)
            data.pop("tuning_min_cents", None)
        if not self.uses_lead_ins:
            data.pop("glide_max_ms", None)
            data.pop("glide_max_stable", None)
            data.pop("reattack_max_ms", None)
        # The multi-horn fields act only on a multi-horn head, and no other
        # ensemble's key may carry them: every cached review, separation-
        # keyed transcription and harness note cache reads exactly as it did
        # before they existed.
        if not self.uses_multi_horn:
            for name in type(self).model_fields:
                if name.startswith("multi_horn_"):
                    data.pop(name, None)
        return data

    @property
    def uses_multi_horn(self) -> bool:
        """Whether the span is a head played by two horns in harmony: Basic
        Pitch's notes, each assigned a voice (`voices.assign`). The one gate
        the stage and the cache key both read."""
        return self.ensemble == "multi-horn"

    @property
    def crepe_line(self) -> bool:
        """Whether the line is CREPE's: every horn, and a pianist on the CREPE
        take. A pianist on the piano model's line has its notes from the
        model, and a multi-horn head from Basic Pitch; CREPE's frames are set
        aside in both."""
        if self.uses_multi_horn:
            return False
        return not (self.uses_piano_oracle and self.piano_line == "oracle")

    @property
    def uses_lead_ins(self) -> bool:
        """Whether lead-ins are marked on this line (`transcribe.mark_lead_ins`):
        either kind on, and the line is CREPE's, whose frames and cuts the
        tests read. The one gate the stage and the key both read."""
        return (self.glide_max_ms > 0 or self.reattack_max_ms > 0) and self.crepe_line

    @property
    def uses_tuning_correction(self) -> bool:
        """Whether the recording's tuning is taken out of CREPE's line: on,
        and the line is CREPE's. A pianist on the piano model's line has
        its pitches from the model's own semitones and sets CREPE's aside,
        so the correction would change nothing there -- and the one gate
        the stage and the cache key both read keeps that key where it was."""
        return self.tuning_correction and self.crepe_line

    @property
    def uses_horn_fill(self) -> bool:
        """Whether Basic Pitch fills the holes in this line: a horn's, with
        the fill on. Never a pianist's (its line is the piano model's), and
        this is the one gate the stage and the cache key both read. Nor a
        multi-horn head's: its notes are all Basic Pitch's already."""
        return self.horn_fill_gaps and not self.uses_piano_oracle and not self.uses_multi_horn

    @property
    def uses_piano_oracle(self) -> bool:
        """Whether to consult the piano model for this ensemble.

        `piano_oracle` forces it on; otherwise the ensemble decides, which is
        the routing plan §5 stage 3 specifies. A horn-led solo must never get
        it — a piano model asked about a saxophone vouches for nothing, and
        rejection would then delete the entire line. Neither may a multi-horn
        head, whatever `piano_oracle` says: two horns are still horns.
        """
        if self.uses_multi_horn:
            return False
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
    # How many onsets a beat needs before a SIXTEENTH grid (or finer) may be
    # chosen for it; below that only the eighth grid and the ternary one are
    # offered. The same reasoning as the tuplet gate, one grid coarser: one
    # or two onsets cannot demonstrate a sixteenth, and read on one they
    # became the dotted eighth plus sixteenth (a swung offbeat played at
    # 0.8) and the note on the "e" (a downbeat played 0.2 late) that no
    # transcriber writes. Measured on the quantizer alone over 452 WJazzD
    # solos (docs/wjazz-quantize.md, 2026-09-20): page hit 70.7% -> 75.3%,
    # the dotted class 4.7% -> 2.1%, the laid-back class 1.6% -> 0.8%, no
    # note lost. Two escapes keep it from losing notes: a beat the eighth
    # grid cannot keep apart, and an eighth reading that would land on the
    # neighbouring beat's own note (the collision guard in quantize_notes).
    # 1 restores the old behaviour.
    min_onsets_for_sixteenth: int = 3
    # A two-onset beat whose FIRST onset is off the beat (raw phase 0.25 or
    # later) and whose onsets fit thirds within this mean error may vote a
    # tuplet: the second and third of a triplet after a rest or a held
    # note. The tuplet gate exists for the swung pair at {0, 2/3}, which is
    # an eighth pair by convention; this figure starts at 1/3 and the
    # convention says nothing about it. Counted on the quantizer's own
    # instrument (docs/wjazz-quantize.md, 2026-09-20): 1,129 of the 1,600
    # beats where the annotator's triplet was written binary were this pair,
    # at (0.35, 0.75). OFF, measured: +1.2 on the instrument at 0.05, and
    # through run_eval on our own notes hand-score rhythm down on 8 of 12,
    # Omnibook on 14 of 17 that moved, placement down on both sets -- the
    # pairs it admits on our onsets are not the annotator's triplets. 0.05
    # is the fit it was measured at.
    offbeat_pair_tuplet_fit: float = 0.0
    # A ternary reading needs its onsets INSIDE the beat: an onset the
    # thirds grid sends to 1.0 is the next beat's note, early, and is not
    # evidence of a triplet. Without this, laid-back sixteenths at (0.3,
    # 0.55, 0.85) read as a triplet because 0.85 "fits" 1.0 -- 1,910 beats
    # on the instrument, 597 of them holding four onsets, which no triplet
    # can.
    tuplet_needs_onsets_inside: bool = True
    # The line's LAG behind the tracked beat, taken out before the snap. A
    # soloist sits behind the drummer and a human writes the line on the
    # beat: over 108 tracks the median per-track offset of the near-beat
    # onsets is +0.033 beats and Birks Works is +0.088, with bar 4 played
    # 0.22-0.33 behind throughout -- which a sixteenth grid reads,
    # faithfully, as the "e" and a dotted eighth (docs/notation-survey.md,
    # D35: 6.2% of our onsets on the "e" against a human's 1.8-2.5%). The
    # lag is the median first-onset offset over a window of beats either
    # side (quantize.line_lag), a window statistic rather than a threshold
    # at one beat line -- the shape that failed to transfer from the
    # annotator's onsets to ours (D34.1). Capped, and never more than the
    # beat's own first onset, so no note moves before its beat line. 0
    # beats of window turns it off.
    lag_window_beats: int = 4
    lag_cap: float = 0.2
    # Below this median the window shows scatter, not lag, and none is
    # taken out.
    lag_floor: float = 0.08
    # Offer a six-per-beat grid -- sixteenth triplets -- wherever the 32nd
    # grid is offered, i.e. only where sixteenths cannot keep the beat's
    # onsets apart. The Omnibook writes 4.9% of its notes as sixteenth
    # triplets and the listener 1.0%; we wrote none, and three notes in
    # half a beat came out as a dotted sixteenth, a sixteenth and a dotted
    # sixteenth, which MuseScore draws as tied 32nds (docs/notation-survey.md,
    # D35.2; Birks Works bar 16). Same evidence rule as the 32nd grid, and
    # the tuplet gate applies: three onsets, all inside the beat. OFF,
    # measured (docs/wjazz-quantize.md): offered everywhere sixteenths
    # merge it read +2.1 on the instrument and worse on 15 of 22 Omnibook
    # sides (rhythm 0.787 -> 0.779); restricted to a beat of three or four
    # onsets that fit sixths within `sixteenth_triplet_fit` beats of mean
    # snap error, +0.4 on the instrument and still 0 up, 6 down on the
    # Omnibook. On our onsets the figure the Omnibook writes as a sixteenth
    # triplet is not three notes at sixths; what sixths fit is scatter.
    sixteenth_triplets: bool = False
    sixteenth_triplet_fit: float = 0.03
    # A solo whose MEDIAN beat is at least this long, in seconds, is a
    # BALLAD and every beat is offered `slow_beat_grids` outright (R31,
    # 2026-09-21; 0.7 is 86 bpm and under). OFF since 2026-09-23 (D36): the
    # only evidence for it was WJazzD's tatum layer, which is Flex-Q's
    # algorithmic quantisation of the onsets, not a transcriber's page --
    # at 37-79 bpm it divides beats in six, eight, ten and twelve because
    # the timing resolves that finely, which is exactly the literal reading
    # a transcriber simplifies away, and no hand score or Omnibook side is
    # under 86 bpm to say otherwise. Under it the instrument's SLOW band
    # read 35.8 -> 40.6 counting drops and the three Flex-Q ballad pages
    # 0.847 -> 0.870, which is agreement with a quantiser. The mechanism
    # stays (the median beat, not each beat: per beat it reached Soul
    # Station at 100 bpm) for a human ballad page to judge. 0 is off.
    slow_beat_s: float = 0.0
    # The grids a ballad beat is offered, in divisions of the beat. 12 is
    # the annotator's triplet 32nd (11% of the notes our page LOST at slow
    # tempos, 60-100 ms from their neighbours; notate writes it as a 32nd
    # under a 3:2 in the sixteenth). 10, the quintuplet 32nd (17% of those
    # notes), is writable too (5:4 in the eighth) and was measured: 500
    # fewer drops on the instrument, and the three ballad pages read
    # 0.864 against 0.870 with it -- left out.
    slow_beat_grids: tuple[int, ...] = (6, 8, 12)
    # How much worse, in SECONDS of mean snap error, a COARSER grid may be
    # and still win. Parsimony: reading a sixteenth out of a beat that only
    # shows an eighth pair is how a swung pair becomes a dotted eighth. 0
    # keeps the old least-error rule.
    #
    # Seconds, not beats, because the scatter this slack absorbs is a
    # player's motor timing, which is a time quantity — and because a
    # constant in beats cannot be right across tempos (D11): over 456 WJazzD
    # solos the median notated interval stays 96-166ms at EVERY tempo while
    # the value it is written as steps 16th → triplet 8th → 8th as tempo
    # rises. A per-beat slack of grid_slack_s / beat_period reproduces that
    # staircase's direction: finer grids reachable at slow tempos, coarser
    # ones preferred at speed.
    #
    # 0.02 is not tuned on the notation score, which rises monotonically to
    # "write everything as eighth notes" and would happily overfit bebop.
    # It equals the old 0.05-beat slack at 150 bpm — the benchmark's centre
    # of mass, where the shipped behaviour was already measured — and it is
    # plan §5's own 20ms round-trip criterion: the coarsening allowance is
    # exactly what the round trip is allowed to cost, at every tempo.
    grid_slack_s: float = 0.02
    # Read a beat pair whose three onsets are equally spaced at 0.58-0.80 of
    # a beat as a quarter-note triplet (quantize.quarter_triplet_pairs), so
    # notate can write it under one 3:2 over the half note. OFF, measured:
    # against the twelve hand scores the rule adopts 9 pairs of which 3 are
    # the human's, because a figure played at exactly 2/3, 2/3 is written as
    # eighths as often as as a triplet -- onset timing alone does not
    # identify it (docs/benchmark-deficiencies.md D28). The page CAN write
    # the figure; what is missing is a reading that deserves to be trusted.
    quarter_triplets: bool = False
    # How much a candidate grid's FIGURE -- the set of positions it writes
    # the beat's onsets on -- counts against it, in beats per nat of
    # surprisal on a human page. The table (`swingscribe/figure-prior.json`,
    # scripts/figure_prior.py build) is the share of each figure over 49,000
    # beats of 245 OMR-read human transcriptions (docs/figure-prior.md): an
    # eighth pair is 55% of beats with an onset, a note on the "e" alone
    # 0.05%. Added to each candidate's mean snap error before the
    # coarsest-within-slack rule, so a grid that fits the onsets a hair
    # better but writes a figure no transcriber writes loses. Every rule it
    # sits beside stands unchanged; it decides only among what the gates
    # leave. Not tuned on the page score (which rewards "everything as
    # eighth pairs"); set by the slack's own equivalence: at 150 bpm, 0.015
    # lets the commonest decision (the eighth pair against the dotted
    # figure, 3.8 nats) spend what `grid_slack_s` spends, and the tempo
    # bands that meet the 20 ms round trip at 0 still meet it. ON since
    # 2026-09-26 (R33) on the listener's reading of Mobley's All The Things
    # bar by bar. With it on, two guards keep every heard note on the page
    # (a reading may not push a note onto an occupied beat line, nor put
    # one on a line the beat before pushed onto), which the shipped
    # quantizer did not: 388 more notes on the 79 benchmark pages, and the
    # page score reads a little lower for them because the transcribers do
    # not write most of them (D37). 0 is off, and the old behaviour.
    figure_prior_weight: float = 0.015
    # "swing" is everything above: warp, lag, grid choice, the prior. A
    # literal timing snaps each onset to the NEAREST point of a fixed grid
    # instead -- 16ths or 32nds -- with no warp, no lag correction and no
    # triplets, so a swung pair is written long-short the way it was played
    # and the page carries no "Swing" marking. The listener's choice per
    # track (sidecar `timing`), made before an export. Never loses a note:
    # see quantize.literal_notes.
    timing: Timing = "swing"
    # The notes are a PIANO TEXTURE, not a line: two notes the grid puts on
    # one position are a chord, not a grid too coarse. Set by the GUI's
    # "All notes" page (notation.py), never by a user directly.
    polyphonic: bool = False
    # Writing research, round 2 (docs/writing-round2.md): three rules for the
    # classes the triples expose (docs/triples.md), each OFF, each measured
    # on the triples' human onsets, the twelve hand scores, the Omnibook and
    # the WJazzD instrument -- and none recommended: each shrinks its class
    # on human onsets and none is decided up on the pages. None dumps
    # anything at its default, so no quantize key and no pin moved when they
    # arrived.
    #
    # A beat of at most this many onsets whose FIRST onset is written on the
    # "e", with nothing on the beat line before it, has that note written on
    # the beat instead (quantize.late_downbeats): a downbeat played late
    # inside a line that does not lag, which R29's window median cannot see.
    # Decided DOWN on the hand scores' rhythm at 2 and 3. 0 is off.
    late_downbeat_max_onsets: int = 0
    # The same late downbeat read as a per-beat LAG instead (R29's shift,
    # applied to one beat): a beat of at most this many onsets whose first
    # onset sits 0.15-0.35 of a beat late and whose last sits before
    # quantize.LAG_PUSH_MIN, with no window lag and nothing from 0.75 on in
    # the beat before, is shifted by that onset (quantize.isolated_lags).
    # Level on every set at 2; at 3 it drops a note. 0 is off.
    isolated_lag_max_onsets: int = 0
    # Let a ternary reading send the beat's LAST onset to the next beat line
    # when it sits from quantize.LAG_PUSH_MIN on -- the next downbeat played
    # early -- the figure before it starts on the beat, and the next beat
    # has no note of its own there. R28 (`tuplet_needs_onsets_inside`)
    # refuses every such beat, so a triplet followed by an anticipated
    # downbeat was written in sixteenths. Half right on human onsets (the
    # page writes thirds in 5 of 18 such beats), level on the pages.
    # False is off.
    tuplet_pushed_last: bool = False
    # A6 (docs/reranker.md): a learned per-beat RE-RANKER over the readings
    # the grid choice already admits -- every (grid, reading) pair that
    # keeps the beat's onsets apart under every note-keeping guard -- in
    # place of the coarsest-within-slack pick. Trained on synthetic
    # performances of human transcription pages (the OMR corpus, dev split)
    # rendered with a performance model fitted to WJazzD's onsets against
    # its annotated beats. "" is off; anything else is the path of a weights
    # JSON (scripts/reranker_train.py), for research. It can only choose
    # among candidates the guards admit, so it never drops a heard note.
    # Trained on synthetic performances it is level on every page when
    # offered what the rule may write (an oracle there buys +0.002) and
    # decided down on the Omnibook when offered more, so no weights ship;
    # paired human data (onsets beside a human page) is what could change it.
    reranker: str = ""
    # Write each note the transcriber marked as leading into the next
    # (NoteEvent.lead_in) INTO that note: it starts where the lead-in did and
    # lasts both, a scoop riding along as its grace note (`absorb_lead_ins`).
    # Swing timing only: a literal page writes every heard note at its own
    # place. On by default (docs/scoops.md); it can only act on notes a
    # transcribe key with the lead-in settings produced, so it dumps nothing
    # while on and no quantize key moved.
    absorb_lead_ins: bool = True
    # Two readings a LITERAL page may take, for horns playing a written head
    # in harmony (docs/multi-horn.md), both OFF: Step 0 found the held
    # chords of the Open Sesame head 0.1-0.3 of a beat BEHIND the tracked
    # beat, which the nearest 16th writes on the "e", and its bridge holds
    # eighth-note triplet chords a literal grid cannot write.
    #
    # `literal_lag` takes the line's lag out before the snap, the swing
    # quantizer's own estimate (quantize.line_lag, with lag_window_beats,
    # lag_cap and lag_floor): a window median of downbeat offsets, shifted
    # out, never more than the beat's first onset.
    literal_lag: bool = False
    # `literal_thirds` offers a beat of at least `min_onsets_for_tuplet`
    # onsets, all inside it, a THIRDS grid when its onsets fit thirds
    # better than the literal grid by `LITERAL_THIRDS_MARGIN` beats of mean
    # snap error (quantize.literal_notes).
    literal_thirds: bool = False
    # Fold the notes the transcriber marked as leading into the next
    # (NoteEvent.lead_in) into it on a LITERAL page too, a scoop as its
    # grace note -- what `absorb_lead_ins` does on a swing page. A solo's
    # literal page writes every heard note; a multi-horn head's scoops
    # into a held chord are not notes on the listener's page
    # (`notation.reading_of` turns this on for that ensemble).
    literal_lead_ins: bool = False

    @model_serializer(mode="wrap")
    def _key_stable_dump(self, handler):
        """Leave `timing`, `polyphonic` and the round-2 rules out of the dump
        at their defaults, so every quantize key reads exactly as it did
        before they existed -- the same device as TranscribeConfig's line
        fields. Quantize is only arithmetic, but a key that moves for a
        change that alters no note is a cache miss for nothing, and the
        pinned harness runs read these."""
        data = handler(self)
        if data.get("timing") == "swing":
            data.pop("timing", None)
        if data.get("absorb_lead_ins"):
            data.pop("absorb_lead_ins", None)
        for field in (
            "polyphonic",
            "late_downbeat_max_onsets",
            "isolated_lag_max_onsets",
            "tuplet_pushed_last",
            "reranker",
            "literal_lag",
            "literal_thirds",
            "literal_lead_ins",
        ):
            if not data.get(field):
                data.pop(field, None)
        return data


class NotateConfig(BaseModel):
    """Stage 6. What the page says, as opposed to what was played."""

    # The part's key. Written pitch minus sounding pitch is a property of the
    # instrument, not of the audio: nothing in the signal says which horn it
    # was, so it is config and never inferred.
    transposition: Transposition = "C"
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
    # A gap to the next note no longer than this, in beats, is written INTO
    # the note (notate.notated_durations): short enough to be a note value,
    # so it becomes one. 0 is off. Measured on WJazzD's durations first
    # (docs/m6-notate.md); on our own path the biggest single value error
    # against the hand scores is an eighth where the human wrote a quarter,
    # 119 of them a note we followed with a rest the human did not write.
    legato_cap: float = 0.0
    # The CONCERT key signature, in fifths (KEY_SIGNATURES), when the listener
    # has chosen one; None detects it from the notes (notate.detect_key). A
    # detection is one profile over the whole page, and a tune that moves
    # between keys has no single right answer to find: Blossom Dearie's More
    # Than You Know reads D minor over its first eight bars, B-flat major over
    # its last eight and D major over the whole. The part's transposition
    # still moves the written signature.
    key: int | None = None
    # A note ON a beat line whose next onset is on a later beat line, a whole
    # number of beats away and no more than this many, is written to fill
    # the gap (notate.notated_durations): the quarter a transcriber writes
    # where we wrote an eighth and an eighth rest. From the beat to the next
    # beat both human corpora hold the note 92% of the time (Omnibook 347
    # gaps, the twelve hand scores 249), while from the "and" they disagree
    # (78% held against 29%). It is decided DOWN on value anyway, like
    # `legato_cap` (docs/writing-round2.md): the gap it sees is OUR gap, and
    # in two of three of ours the page's is not a beat -- a note only the
    # page has, or the next note anticipated -- so our eighth and rest was
    # right. 0 is off.
    hold_to_beat: float = 0.0

    @model_serializer(mode="wrap")
    def _key_stable_dump(self, handler):
        """Leave `key` and `hold_to_beat` out of the dump at their defaults,
        so every notate key reads exactly as it did before they existed."""
        data = handler(self)
        if data.get("key") is None:
            data.pop("key", None)
        if not data.get("hold_to_beat"):
            data.pop("hold_to_beat", None)
        return data

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
    # A track to open as soon as the page loads (`swingscribe gui <file>`);
    # passed to the page as ?open=<path>, never to the pipeline.
    open_track: str | None = None
    # Where the track picker looks. null = the directory swingscribe was run from.
    library_dir: str | None = None
    # Separation models offered on the audition screen, in menu order — the
    # default first (the Roformer, needing the `roformer` dependency group),
    # then the demucs bags, which are ~9x faster and the choice when speed
    # matters more than the last few points. See SeparateConfig.
    models: list[str] = ["bsroformer_sw", "htdemucs", "htdemucs_6s", "htdemucs_ft"]


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
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        """Environment first, then what the caller passed.

        The module docstring has always promised that `SWINGSCRIBE_*` overrides
        a value from the YAML — but `from_yaml` hands the YAML in as init
        kwargs, and pydantic-settings ranks init kwargs above the environment,
        so the promise was empty: `SWINGSCRIBE_CACHE_DIR` lost to the yaml's
        `cache_dir` every time (found 2026-09-13 by the portable build, whose
        launcher points the cache at the user's profile that way). Nested
        sections deep-merge, so `SWINGSCRIBE_GUI__LIBRARY_DIR` changes one
        field of `gui` and leaves the yaml's port alone.
        """
        return (env_settings, init_settings)

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
