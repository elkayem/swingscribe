# Notate and export — from a grid to a page

Plan §5 stages 6 and 7. Quantize left every note on a grid position with a bar
and a beat; this turns that into something a musician can open.

Reproduce with `uv run pytest tests/test_notate.py tests/test_export.py` — the
whole of both stages is pure arithmetic and runs in CI, key detection and note
spelling included.

## Acceptance

Plan §5 asks that the output open cleanly in MuseScore with no import
warnings. That is a human check and it is **still outstanding** — it needs
someone to open the file. What can be asserted has been:

- Every measure sums exactly to its time signature. Confirmation exports
  **129 of 129** correct, at 24 divisions per quarter with no rounding.
- Ties are written both as `<tie>` (what sounds) and `<tied>` (what is drawn).
  Readers disagree about which they honour, and a file with one of them either
  warns or silently loses the tie.
- A transposed part carries a `<transpose>` element that matches its key
  signature.

## No music21, and why

The plan names music21 for stage 6. It is not a dependency of this project,
and "never add a dependency without asking" is explicit (CLAUDE.md), so this
is arithmetic instead — which, once written down, all of it turned out to be.

The payoff is the one the rest of the pipeline already gets: no heavy import,
so the entire stage is exercised in CI rather than behind an `importorskip`.
`model.py`'s `Notation` carries everything a music21 `Score` would need, so if
music21 is wanted later it can wrap this rather than replace it.

**This is a plan deviation and wants confirming or overturning.**

## The four decisions

**Key** is Krumhansl-Kessler, correlating the pitch-class profile against all
24 rotations — but weighted by **duration, not note count**. In a bebop line
the passing tones outnumber the chord tones, and counting notes finds the
wrong key more often than the right one.

Measured against the hand transcriptions' own key signatures:

| tune | the score says | from their notes | from our audio |
|---|---|---|---|
| Confirmation | F | F | **F** |
| All The Things You Are | A♭ | A♭ | **A♭** |
| Giant Steps | C | E♭ | B♭ |

Exact on both tunes that have a key. Giant Steps has three, and the human
chose to write no key signature at all — their own notes analyse as E♭, ours
as B♭, and the honest reading is that the question has no answer for that
tune rather than that we got it wrong.

**Spelling** is nearest-neighbour on the line of fifths, measured from the
key's centre. One rule: it gives the diatonic notes their key spelling for
free, and spells chromatic ones the way a reader of that key expects — F♯ in
G major, G♭ in D♭ major. A fixed sharps-or-flats table cannot do this, because
a line in F wants B♭ and E♮ *and* the occasional A♭.

The invariant that matters is tested exhaustively over every key and every
pitch: **spelling never changes the sound.**

**Note values** come from halving the bar and halving again. A note that
straddles a division is tied at it unless it sits flush with the unit
containing it. Deliberately conservative — offered a choice between one symbol
that could be misread as a downbeat and two tied symbols that cannot, it takes
the tie.

**Rests** fill each bar to its time signature, because a bar that does not add
up is the most common reason a notation program refuses a file outright.

## Two things only running it on a real solo revealed

**Quantize's ternary grid means thirds of a beat arrive here routinely, and a
third of a beat is not a note value.** It is an eighth note carrying a 3:2
time modification. Without tuplets those durations were unnotatable slivers,
and **57 of Confirmation's 129 bars did not add up**. `NotatedNote.tuplet`
fixes it, and a tuplet is allowed inside one beat and no wider — a triplet
written across a beat boundary is unreadable, and it is not what quantize
found either, since it chooses the grid one beat at a time.

**Quantization can round one note's end past the next note's start.** Two
notes sounding at once in one voice is invisible on a piano roll and fatal in
notation. `without_overlap` truncates rather than drops, because the overlap
is a few milliseconds of rounding and not a second voice.

Together, on Confirmation:

| | before | after |
|---|---|---|
| bars that add up | 72 / 129 | **129 / 129** |
| noteheads for 858 notes | 1280 | **936** |
| of which tied | 422 | **93** |

## Written pitch happens once, at export

Everything upstream is concert pitch, deliberately: the benchmark's ground
truth is concert pitch, and a stage that silently transposed would invalidate
every comparison against it. MusicXML wants written pitch plus a `<transpose>`
saying how to get back, so the transposition is applied at the very end.

**The key signature moves with it.** A tenor part whose concert key is F is
written in G. Transposing the notes and not the signature produces a part that
sounds perfect and is covered in accidentals — a mistake that survives a
listening test, which is why it has its own test.

| instrument | `transpose` | `<transpose>` | key shift |
|---|---|---|---|
| concert | 0 | — | 0 |
| B♭ trumpet | +2 | −1 / −2 / 0 | +2 fifths |
| E♭ alto | +9 | −5 / −9 / 0 | +3 fifths |
| B♭ tenor | +14 | −1 / −2 / **−1** | +2 fifths |

The tenor is the one worth staring at: a major ninth is 14 semitones but only
8 staff steps, so MusicXML's reduced-interval-plus-octave form is not the
semitone count and cannot be derived from it by division.

## Known limits

- **Nothing measures the notation.** Both benchmarks score pitch sequences and
  onset times; neither scores note values, ties, spelling or bar assembly, so
  a score full of unreadable rhythms would move no number on
  `docs/benchmark-deficiencies.md`. The measure to build is our MusicXML
  against the `.mscz` for the same solo, compared as notation.
- **Pickups and rubato intros are not handled.** Quantize reports bar 0 for
  anything outside a meter section and this stage does not yet do anything
  special with it.
- **No beaming, articulation, dynamics or chord symbols.** A jazz lead sheet
  wants chord symbols above the staff; nothing here produces them.
- **The transposition is config, never inferred.** Nothing in the signal says
  which horn it was, so `notate.transposition` has to be told.
