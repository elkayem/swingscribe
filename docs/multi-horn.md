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
  2. a NEW CHORD -- two notes of different pitches struck within 60 ms --
     ends whatever was still sounding when it starts (`trim_tails`): two
     horns attacking together leave nothing else held, so what rings on is
     a release tail;
  3. where three sound at once, the two most confident stay;
  4. notes that overlap meaningfully (60 ms, or 30% of the shorter) are
     ordered by pitch, the higher in voice 1 -- over the whole overlap graph,
     so continuity keeps a horn in its voice through a brief crossing and
     the lower horn moving under a held note is caught by the overlaps with
     it. A note with no partner (one horn alone, a unison heard as one note)
     is voice 1, written once;
  5. in each voice, two touching notes of one pitch are joined where
     CREPE's frame trace holds that pitch across the join (50 ms either
     side, within half a semitone) and none of its corroborated onsets is
     within 40 ms (`rejoin_splits`) -- Basic Pitch re-attacks a held note on
     a stray onset peak. CREPE follows one horn at a time, so it vouches
     only where it is on that horn; elsewhere a split stays;
  6. in each voice, a note of at most 100 ms touching the next, a semitone
     under it (a scoop) or at its pitch (a re-attack's head), where the next
     is at least three times as long, is marked `lead_in` (`mark_lead_ins`).
     The length ratio is what keeps a chromatic or repeated 16th run at 250
     bpm (60 ms a note) from reading as a chain of lead-ins; CREPE's line
     tells a scoop by its frames never settling, which Basic Pitch cannot.
- What neither voice holds -- the ghosts and the thirds -- is the review's
  `candidates`, which the Edit tool can switch on (`dropped` says why each
  was left out).
- It never consults the piano model (`uses_piano_oracle` is false for it
  whatever `piano_oracle` says), and without onnxruntime it is an ERROR, not
  a silent fall back to CREPE's single line under the multi-horn key.
- Every `multi_horn_*` field enters a cache key only for a multi-horn head
  (`TranscribeConfig`'s serializer); no other key moved, and a test pins the
  horn-led, trio and solo-piano dumps as they were.
- `multi_horn_version` is the rules' own number. The GUI's review key hashes
  the transcribe dump, never `transcribe.CACHE_VERSION`, so a change to
  `voices.py` that moves no field would serve every cached head unchanged:
  bump it with any such change (2 since 2026-10-09: rules 2, 5 and 6).

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
  - a phrase is CUT where its distance from the upper voice changes regime
    (an octave or more under, or less) for at least a second and three
    notes (`sub_phrases`): the head's bars 15-16, two bars an octave and a
    third under inside a 46-note phrase whose median is a fourth, were
    left wide apart in the first measurement. A shorter excursion stays
    with its phrase, so nothing is decided note by note;
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
- A lead-in is FOLDED into its note on a head's page, literal or not
  (`QuantizeConfig.literal_lead_ins`, which `notation.reading_of` turns on
  for a multi-horn head; sidecar `literal_lead_ins: false` writes them as
  notes): the pair is one note from the lead-in's onset, a scoop written as
  its grace note (`quantize.absorb_lead_ins`, the solo pages' rule). A
  solo's literal page still writes every heard note.
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
- A third, also off: `literal_tempo` (sidecar; `QuantizeConfig.
  literal_eighths_beat_s`, 0.375 s when on) writes a literal beat faster
  than 160 bpm on EIGHTHS, refined to 16ths and 32nds only where a coarser
  grid cannot keep its onsets apart or pushes one onto the next beat's own
  note -- the running value set by tempo (D11). At 250 bpm a 16th is 60 ms
  and Basic Pitch's attacks spread to 0.19 of a beat behind it, so the
  nearest 16th split one chord's attacks across two grid points. The
  listener asked for the rhythm as played, so it is theirs to turn on.
  Export's file name carries `bytempo`.

New model fields, all additive with defaults (no cached artifact or key
moved): `NoteEvent.voice`, `NotatedNote.stem`, `NotatedNote.hidden`,
`Notation.clef`, `Notation.part_name`, `Notation.parts`. A one-part page's
MusicXML is byte-identical to before (checked against the previous export
on swing, literal, transposed, grand-staff and double-time pages).

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

### Two parts

Sidecar `staves: 2` on a multi-horn head (the Staves menu's "Two parts")
writes the horns as two PARTS of one page (`notation.merge_horn_parts`,
`Notation.parts`, written by export as two `<part>`s with printed names
Upper and Lower):

- no octave move and no unison merge: each part is what its horn played;
- one concert key read over both, each part at its own transposition: the
  sidecar's `transposition` for the upper part, `lower_transposition` for
  the lower (the upper's when unset);
- each part's clef by its register: bass when the length-weighted median of
  its WRITTEN pitches (concert pitch for a C part) is under middle C
  (`notation.clef_for`), else treble;
- chord symbols and the page's words ("Swing") on the upper part only;
- the Score button and readability read the upper part.

### The GUI

- The Ensemble menu offers "Two horns (a head)" (built from
  config.ENSEMBLES), with its own hint, and the Rhythm menu shows literal
  16ths for it until the listener picks another (`/api/config`
  `ensemble_timings`).
- The roll colours the upper voice like the line and the lower like the left
  hand (`review.js` `setHands` with no split line); the legend says so, and
  the faint candidates are "heard, in neither voice".
- The Voices tool is the Hands tool's gestures (box select, Ctrl-box adds,
  click, Ctrl-click; up/down or the buttons; "As heard" forgets a move; H).
  Moves are stored in the sidecar's `voices`, [{onset, pitch, voice}], and
  matched by content. `/review` returns `voices` (the moves resolved onto
  the roll's indices) and `note_voices` (every note's voice as the server
  ordered the edited set).
- Two notes put in ONE voice at one onset are written as a chord in it
  (`notation.with_chords` per voice).
- The ear test plays both voices (the render synthesises every kept note).
- The Staves menu reads "One staff, two voices" / "Two parts (upper +
  lower)", and "Lower part" appears beside "Written for" in two-parts mode.
- Export's file name carries `2parts` for two parts, `literal16` for the
  default rhythm, and `lag`/`thirds` for the readings.

A smoke test in headless Chromium against a stubbed server (cloud session,
2026-10-08): the folder browser grouped takes, a linked take opened, the
legend, the Voices tool (17 notes box-selected and moved, stored in the
take's sidecar), the Staves and Lower part menus, and Export in both modes
(the page named for the take, beside its sidecar) all worked with no
script error.

## The first measurement (Local task A, 2026-10-09)

The local session wrote the Open Sesame head four ways (branch 9f73970) and
set the dump against the listener's bars 23-38 (page bars 41-56; the page's
bar 1 is the roll's bar -7). Bar numbers below are the LISTENER'S, except
the octave move's, which are the roll's. What it changed:

- Bar 26 (the upper horn's F4 tail put the next chord's Eb4 in the lower
  voice) and bar 28 (the lower G4 lost as a third to the A-flat ringing on
  under a held C5): rule 2, both passes.
- Bars 24, 28 and 31-32 (a held note written tied to a re-attack, Bb4 cut
  in four): rule 5, wherever CREPE was on that horn.
- Bar 23 (both horns' scoops written as 16ths before the chord): rule 6 and
  the fold.
- Roll bars 15-16 not moved up (one 46-note phrase, median a fourth):
  `sub_phrases`.
- The script died printing a flat sign on a cp1252 console, after the page
  was written: it replaces what the console cannot encode now.
- The rhythm: Basic Pitch's attacks near a beat sit a median 0.06 of it
  late with a spread to 0.19, and at 250 bpm the nearest 16th splits that
  spread across two grid points. `literal_tempo` writes such a beat on
  eighths; it is OFF, the listener's call.

Left as heard, for the listener: bars 24 and 32's lower voice moving a half
step to the third and holding under the upper quarters (the listener's page
drops it), bar 25's merged C4 re-attack (no onset to split on), and the
triplets of bars 36 and 38: their onsets sit at 0.15, 0.68 and 0.97 of the
beat (upper) and 0.49, 0.68, 1.11 (lower), which no thirds rule reads
(spacing about 0.5, and with the lag out 0, 0.53, 0.82 collide on thirds)
-- a hearing question, not a writing one. `--thirds` changed nothing on
the page, byte for byte.

## The second measurement (Local task A2, 2026-10-09)

On eb618ae, Windows: 2094 tests pass, the run_eval card is byte-identical to
master's (all 4768 pins), MuseScore opens all six pages, and the graces
render as slashed graces before the chord in both voices. The head's
counts: voices 178 / 154, 12 candidates, 10 lead-ins, 1 of 10 lower phrases
moved, 3 unisons. Pages: literal 16ths 456 notes (readability 0.942, ties
0.300); `--by-tempo` 380 (1.000, 0.161), far the closest to the
screenshot.

Mended on the beat with `--by-tempo`: bar 23 (both scoops as graces on
whole notes), 24 and 28 exactly (28's lower G4 back), 31-32 exactly (the
join), 33-34. Still off, all hearing: bar 25's merged C4 re-attack, bar
26's voice order (the upper F4 held over the bar line still puts the next
chord's Eb4 under it), the lower Ab4 of bar 27 on the "and", a stray Gb4
eighth before bar 29's Eb4, bar 31's lower Gb4 an eighth late, and no
triplets in bars 36 and 38 even with `--thirds` (their onsets are not on
thirds; the figure is read from the phrase, as D28 found for the
quarter-note triplet -- left to the listener's mark, the gate not
loosened).

What it changed (2026-10-09):

- The octave move overshot: the excursion's phrase ran on into roll bar
  17's chord, and its held A-flat, a third under C, was moved over the C.
  A close stretch at either END of a phrase now stands alone however short
  (`sub_phrases`); a short wide one at an end still joins its neighbour.
- E natural was written F-flat (and B natural would have been C-flat in
  E-flat): `notate.spell`'s tie six fifths from the key went to whichever
  letter its table listed first. The natural letter wins it now, then the
  sharp side, the relative minor's leading tone; every other key's choice
  is unchanged (a test pins all fifteen). Spelling reaches no score, so no
  pin moves.
- The script named a linked take's page for the audio; it names it for
  the take and writes it beside the take's sidecar, as Export does.
- The per-rule count line is printed on every transcription, not only
  when the stage logs (the GUI's path does not).
- run_eval transcribed and tracked the head on every run although nothing
  scores it: a multi-horn sidecar with no `score` is left out of the
  harness walk now, and says so.

## Open questions for the measurement

- Is `literal_lag` right on the head's held chords, and does it move a note
  the page should keep on the "e"?
- Does `literal_thirds` write the bridge's triplets, and nothing else?
- Is the octave move's threshold (median interval of an octave or more)
  where the listener wants it -- an octave doubling written once?
- Does the ghost rule drop a real upper note at the octave (a real octave
  doubling with the upper horn under 0.6 of the lower's confidence)?
- A scoop folded as a GRACE note, or dropped outright? The solo pages write
  it as a grace; the listener's head page may want nothing there.
- Does rule 2 cut a held note when the other horn and a stray (bleed) note
  strike together? Two horns cannot sound three notes, so it reads that as
  a new chord; rule 3 used to drop the stray instead.
- `literal_tempo`: does eighths-by-tempo read the head better, and does it
  lose a 16th the listener wrote?
