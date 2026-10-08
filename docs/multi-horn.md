# Multi-horn heads: two horns in harmony on one staff

A hard bop head is two horns playing one tune in harmony -- trumpet over
tenor, a third to a sixth apart most of the time, at the octave sometimes,
in unison sometimes. Every other ensemble SwingScribe knows is one line.
This is the design and the state of the `multi-horn` ensemble (the
listener's design, 2026-10-08; the hand-off between the cloud session that
wrote it and the local session that measures it is
[multi-horn-handoff.md](multi-horn-handoff.md)).

## Step 0: what the head sounds like to the models

The Open Sesame head (0-67.308 s, the BS-Roformer `other` stem), measured
locally before any code:

- Basic Pitch heard 381 notes. Of the sounding frames, 82% hold exactly two
  notes and 6% three.
- Simultaneous intervals are mostly 3-8 semitones; 12 at 15 semitones (grid
  bars 15-16, the tenor an octave and a minor third under the trumpet) and 6
  octaves.
- Overtone ghosts at low confidence: Bb5 0.30 over Bb4 0.69, F6 0.31 over
  F5, C5's partials around 0.25-0.31.
- Basic Pitch merges re-attacks (grid bar 35: a C4 half and a C4 quarter
  came out as one note).
- CREPE follows the upper horn and jumps into the lower one: no use for the
  voices.
- The vocals stem is silent: both horns are in `other`.

## Hearing and writing are kept apart

The same split as the lead-ins ([scoops.md](scoops.md)): the transcriber
outputs both horns at their HEARD pitches, each note tagged with its voice;
the page applies the writing conventions.

### Hearing (`stages/transcribe.py`, `voices.py`)

`ensemble: "multi-horn"` (config.ENSEMBLES, so the GUI's menu offers it):

- The notes are Basic Pitch's over the span (`basic_pitch.transcribe`,
  onset 0.5, frame 0.3, 23 ms -- never its own 128 ms minimum), 4 ms late
  like the horn fill's. CREPE still runs, for the roll's frame trace, and
  its notes are set aside, as a pianist's are on the piano model's line.
  None of CREPE's line rules apply (the floors, the horn fill, the tuning,
  the lead-ins): `TranscribeConfig.crepe_line` is false.
- `voices.assign` puts each note in a voice, `NoteEvent.voice`:
  1. an overtone ghost (12, 19, 24, 28 ... semitones over a note that holds
     it for half its length or more, with at most 0.6 of its confidence) is
     dropped;
  2. where three sound at once, the two most confident stay;
  3. notes that overlap meaningfully (60 ms, or 30% of the shorter) are
     ordered by pitch, the higher in voice 1 -- over the whole overlap graph,
     so continuity keeps a horn in its voice through a brief crossing and
     the lower horn moving under a held note is caught by the overlaps with
     it. A note with no partner (one horn alone, a unison heard as one note)
     is voice 1, written once.
- What neither voice holds -- the ghosts and the thirds -- is the review's
  `candidates`, which the Edit tool can switch on (`dropped` says why each
  was left out).
- It never consults the piano model (`uses_piano_oracle` is false for it
  whatever `piano_oracle` says), and without onnxruntime it is an ERROR, not
  a silent fall back to CREPE's single line under the multi-horn key.
- Every `multi_horn_*` field enters a cache key only for a multi-horn head
  (`TranscribeConfig`'s serializer); no other key moved, and a test pins the
  horn-led, trio and solo-piano dumps as they were.

### Writing (`notation.py`)

One function, `notation.notation_for_horns`, is the page for the Export
button, the page view, the Score button, `run_eval` and
`scripts/multi_horn_page.py`:

- BOTH horns on ONE staff, treble clef, concert key.
- `horn_lines` writes the heard notes:
  - the lower voice moves up by whole octaves PER PHRASE (a phrase runs
    between gaps of 0.25 s), where the phrase's median interval under the
    upper voice, weighted by time together, is an octave or more. Never note
    by note. An octave and a third becomes a third; a phrase doubled at the
    octave becomes a unison;
  - a unison (same pitch, onsets within 50 ms) is written ONCE, in voice 1.
- Each voice is quantized on its own, on ONE grid, under the upper voice's
  swing reading (the piano overlay's precedent, `_notate_only`), and the two
  are merged as voices 1 and 2 of the staff (`merge_horn_voices`):
  - in a bar that holds both, voice 1 stems up and voice 2 down;
  - a bar of voice 1 alone has automatic stems and NO voice-2 rests;
  - voice-2 rests are written `print-object="no"`; voice-1 rests are drawn;
  - the key is read once over both voices.
- The rhythm is LITERAL by default (`config.ENSEMBLE_TIMINGS`,
  `notation.timing_for`): horns playing in harmony play the rhythm that is
  written. The sidecar's `timing` still wins when the listener picks one.
- Two readings a literal page may take, both OFF until measured on the real
  head (`QuantizeConfig.literal_lag`, `literal_thirds`; sidecar keys of the
  same names):
  - `literal_lag` takes the line's lag behind the beat out before the snap
    (`quantize.literal_lags`, the swing quantizer's window median). Step 0
    found the held chords 0.1-0.3 of a beat behind, which the nearest 16th
    writes on the "e". On a two-horn page the lag is read ONCE over both
    voices and moves them together, so a chord stays a chord;
  - `literal_thirds` writes a beat of three or more onsets, all inside it,
    in thirds when they fit thirds better than the literal grid by 0.02
    beats of mean snap error -- the bridge's eighth-note triplet chords.
    Notate reads a literal page's beat as ternary only when an onset sits
    EXACTLY on a third (`notate.exact_thirds`), which nothing else writes.

New model fields, all additive with defaults (no cached artifact or key
moved): `NoteEvent.voice`, `NotatedNote.stem`, `NotatedNote.hidden`.

### The GUI's edits (`gui/edits.py`)

`resolve` -- the closure in `create_app` that the ear test, Export and Score
shared, moved to a module so the script can use it -- treats a multi-horn
review as its own VIEW:

- erasures and additions made on it carry `view: "horns"` and are resolved
  only there; on any other view they are carried, never resolved, and the
  other views' records are carried on it (`erasures.split_by_view`, the
  `split_by_texture` precedent);
- the kept notes are re-ordered over the EDITED set with rule 3 alone
  (`voices.order`), so a note whose partner was erased is written once and a
  switched-on candidate is never pruned again;
- the listener's voice moves (sidecar `voices`, [{onset, pitch, voice}],
  matched by content through `erasures.match`) are applied on top.

## Open questions for the measurement

- Is `literal_lag` right on the head's held chords, and does it move a note
  the page should keep on the "e"?
- Does `literal_thirds` write the bridge's triplets, and nothing else?
- Is the octave move's threshold (median interval of an octave or more)
  where the listener wants it -- an octave doubling written once?
- Does the ghost rule drop a real upper note at the octave (a real octave
  doubling with the upper horn under 0.6 of the lower's confidence)?
