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


## What a human actually writes, counted

Two histograms, both of them decision-relevant, neither of them previously
consulted by the notater.

### The ten hand transcriptions (3,646 notes)

| value | the listener | us (1,126 notes, the 3/4 score excluded) |
|---|---|---|
| eighth | **75.9%** | 64.6% |
| quarter | 12.0% | 12.1% |
| 16th | 10.5% | 16.3% |
| tuplets | **4.1%** | **0.9%** |
| rests per 100 notes | **13.8** | 30.3 |
| **16th-or-shorter rests** | **1, in ten solos** | **9.4 per 100 notes** |

One sixteenth rest in 3,646 notes. That number is what raised `MIN_REST` from
a sixteenth to an eighth, and it removed 93% of our sub-eighth rests (260 to
18 across the four scores the notation harness can pair) while moving the
notated-rhythm score on **none** of them: rhythm compares onset positions, and
closing a gap changes the previous note's duration, not any onset.

The tuplet row is the outstanding one. We write triplets at a quarter of the
rate a human does, and where a human writes a triplet we write sixteenths and
a tie. `choose_grid`'s "three onsets before a tuplet is allowed" is the
suspect; it has not been re-measured.

### WJazzD (456 solos, 197,177 notated intervals)

WJazzD stores metrical position, so the *implied* value is the interval to the
next note. Independent confirmation of the tuplet gap, on 54 times the data:
**ternary divisions are 23.9% of intervals, and 444 of 456 solos use them on
more than 10% of their notes.**

A structural fact worth keeping, because it validates the current design: of
97,499 annotated beats, **zero mix binary and ternary notes inside one beat**.
Grid choice really is per-beat and exclusive.

### The running value is set by TEMPO, and we do not know that

| tempo | solos | median notated interval | in milliseconds |
|---|---|---|---|
| under 120 bpm | 91 | **sixteenth** | 166 ms |
| 120-160 | 116 | **triplet eighth** | 165 ms |
| 160-200 | 87 | **eighth** | 162 ms |
| 200-250 | 83 | eighth | 136 ms |
| 250-300 | 63 | eighth | 111 ms |
| 300-400 | 16 | eighth | 96 ms |

The median notated interval in *seconds* stays between 96 and 166 ms across
the entire range, while the note value it is written as steps 16th -> triplet
-> eighth. Regressing log(interval in quarters) on log(tempo) gives slope
0.705 (r = 0.690): the value absorbs most of the tempo change.

**Our grid rules know nothing about tempo.** `grid_slack` is a constant, tuned
against quantize's round-trip, and the M6 note that it "must NOT be tuned on
the notation score" stands — but a constant cannot be right from 63 bpm to 340
bpm, and this table says what it should vary with. It also predicts the
observed failure: the one score that produced thirty-second notes is at a
tempo where WJazzD says the running value is a sixteenth.

## Triple metre was unimplemented, not imperfect

`_subdivide` placed ties by halving the bar. In 4/4 that walks 4 -> 2 -> 1 ->
1/2 -> 1/4, every step a real note value. In 3/4 it walks **3 -> 1.5 -> 0.75 ->
0.375** and never lands on a beat, so the recursion bottomed out at its
"nothing left to divide" guard and emitted whatever sliver was left, named by
nearest symbol.

On the one 3/4 score in the benchmark that produced, in 66 bars:

- **12 bars that do not sum to their time signature**, short by 1 to 4 of 24
  divisions
- **14 notes of duration ZERO**
- a `<type>32nd</type>` carrying `duration=1` where a 32nd is 3

All 111 thirty-second notes in the entire export set are in that one file. The
other three exports are 4/4 and have no short bars, no zero-duration notes and
no thirty-seconds at all.

`split_points` replaces the bare midpoint: a unit that IS a power-of-two value
is halved, a unit that is three of them is divided in THREE, and anything else
(5/4) has the largest whole value peeled off the front. 6/8 is not
distinguished from 3/4 — both arrive as three quarter notes and both get cut
in three — because grouping 6/8 as two dotted quarters needs the time
signature, which this stage is not given.

Re-notating the same solo from the same 315 cached notes:

| | before | after |
|---|---|---|
| bars that do not add up | **12 of 66** | **0** |
| notes of duration zero | **14** | **0** |
| sub-eighth rests | 36 | 3 |
| thirty-second notes | 111 | **0** |
| **tuplets** | **0** | **38** |

The last row was not expected and is the more interesting half. A tuplet is
allowed inside one beat and no wider (M6), and binary bisection of a 3/4 bar
never produces a sub-unit exactly one beat long - so **triplets were
structurally unreachable in triple metre**, and every one of them was being
written as sixteenths and a tie. Some of D12's missing triplets were this.

The resulting vocabulary is one a reader recognises: 191 eighths, 116
sixteenths, 34 triplet eighths, 28 dotted eighths, 22 quarters. The hand
transcription of the same solo has 187 eighths, 40 sixteenths and 25 quarters.


## Closing a short gap: from which side?

Raising `MIN_REST` to an eighth removed 93% of the sub-eighth rests. It is
**not** free, and the first measurement of it missed the cost because it only
looked at notated rhythm. Over the ten hand transcriptions:

| closing the gap by | notated rhythm | notated value | sub-eighth rests |
|---|---|---|---|
| nothing (the old 16th floor) | 0.711 | **0.672** | 398 |
| **extending the note before** (ships) | 0.711 | **0.628** | 32 |
| pulling the note after back | **0.752** | 0.669 | 26 |

Extending rewrites a duration, so it costs `value` 0.044 - an eighth becomes a
dotted eighth the human never wrote. Rhythm is untouched because rhythm
compares onset positions and no onset moves.

Pulling the following note back rewrites an onset instead, and scores better
on both. **It still may not ship from here.** The moved onset lands on the
previous note's end, which is off-grid by construction - that off-grid end is
the whole reason the gap exists - and inside a ternary beat it is not a third.
Breaking the tuplet group is the corrupted measure the function exists to
prevent, and the test suite catches it immediately.

The +0.041 is worth having anyway, because of what it says. A note sitting a
sixteenth late inside a beat the human wrote as two eighths is a grid chosen
too fine; pulling it back is coarsening the grid by hand, one note at a time,
after the fact. **That is D11 arriving from a second direction** - the fix is
`choose_grid` knowing the tempo, not a repair pass downstream of it.

## Measuring readability: the one number that needs no reference

`benchmark.readability(notation)` asks whether the page is **writable at all**.
Every other measure asks whether we agree with a particular human about a
particular recording; this one is a property of our own output, so it runs over
EVERY notation the harness builds -- thirty of them, not the ten with hand
scores -- and it is the widest measurement in the project.

It exists because the listener could name two defects that NOTHING in
`score_notation` could see: a sixteenth rest before a note played behind the
beat, and "dotted 1/32 notes with strange ties". `rhythm` asks whether the gap
to the next note matches and `value` whether the note value matches. A page can
be unreadable and move neither.

Worse, `value` actively FIGHTS the repair. Absorbing an unwritable rest into the
note before it turns an eighth into a dotted eighth, which `value` scores as
wrong -- and it is right that a dotted eighth is rare, 6 in 3646. So raising
`MIN_REST` was reported as a regression with nothing on the other side of the
ledger. This is that other side.

**Anchored on what a human actually writes.** Counted over the ten hand
transcriptions, read straight out of the .mscz XML before ties are merged, so
these are symbols on a page rather than durations -- 3646 notes and 487 rests:

    rests shorter than an eighth        6 of  487   1.2%
    note values below a sixteenth      13 of 3646   0.4%
    notes tied into the next           82 of 3646   2.2%
    eighth notes                     2406 of 3646  66.0%

A human reads **0.995**. We read **0.994** over thirty notations, with ZERO
notes below a sixteenth on any of them -- the triple-metre fix (`split_points`)
had already removed the defect the listener reported in bar 18, and this measure
is what confirms it across every score rather than one.

The gap that remains is ties: ours run 0.030-0.180 against the human's 0.022.
That is D14, and it is deliberately reported beside the composite rather than
inside it -- a page is not unreadable for having a tie.

## Durations were never snapped to a grid, only onsets

`snap_values` rounds each written duration to a value a reader can read: any
number of sixteenths, or any number of triplet eighths, chosen from the grid
the note's own BEAT is on rather than from whichever is nearer. 3629 of the
listener's 3646 written values are in that set.

**It changes nothing in the shipped pipeline, and that is the finding.** Mean
readability over the thirty notations goes 0.9941 to 0.9939, and no rhythm,
value or F1 number moves. `without_overlap` truncates every note at the next
onset, so 93-96% of our notated notes already fill their gap exactly, and a gap
between two grid positions is on the grid; this rule only ever sees the other
4-7%. (Not `notated_durations` -- `legato_fill` ships at 0.0 and that function
returns early on our own path. The distinction matters: someone chasing this
would otherwise go and read a function that never runs.)

Where it is decisive is a score built from WJazzD's metrical annotation, where
no duration inherits a gap because they are all performed seconds. Over the 172
of 456 solos whose onsets sit on writable subdivisions, readability goes
**0.788 to 0.982**, notes below a sixteenth 12.8% to 0.16%, ties 0.246 to 0.119.

Two things measured and rejected along the way:

- **Offering both grids to every note and taking the nearer one** puts a
  triplet-eighth rest in a beat of sixteenths -- the twelfth-of-a-beat sliver
  `close_short_gaps` exists to prevent, arriving from the other direction. The
  grid comes from the beat.
- **Preferring a value whose leftover gap is itself writable** (nothing, or at
  least a `MIN_REST`) is much worse: it pushes the value down to open a real
  rest. Mean readability 0.9941 to 0.9678, with short rests up on 28 of 30.

And one correctness note: candidate values must NOT be rounded. A candidate of
0.333333 makes two of them 0.666666, and MuseScore calls a tuplet group that
misses a sixth of a beat by 2e-6 a corrupt file.

