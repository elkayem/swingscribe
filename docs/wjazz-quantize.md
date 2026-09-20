# The quantizer alone, measured on WJazzD (2026-09-20)

`scripts/wjazz_quantize.py`, pinned in `tests/regression/wjazz-quantize-baseline.json`.

## Why

The listener's complaint of 2026-09-19: "even when it gets the notes right,
it chooses timing no human transcriber would ever use" -- Art Pepper's Birks
Works bar 4 as a tied sixteenth into dotted-eighth-sixteenth pairs where the
hand score has quarters and eighths; bar 16 with tied thirty-seconds. Those
are choices of `quantize` and `notate`, and until now the only measure of
them was the notated rhythm of twelve hand scores, which is gap-based,
cannot say which note moved, and rewards writing everything as eighths.

## What the instrument does

Every WJazzD note carries both when it was played (`onset`, seconds) and
where the annotator filed it (`bar`, `beat`, `tatum` out of `division`); every
solo carries the annotator's beat grid in seconds. That is the quantizer's
input and output, 200,000 notes of it, with no audio, no CREPE and no
alignment: the annotator's onsets go through `swing`, `quantize` and `notate`
on the annotator's grid -- `notation.notation_for_span`, the Export button's
path -- and each note is compared with where the annotator filed it. The one
constant not being asked (which of our bars is their bar 1) is the mode of
the differences. 452 solos in one quarter-note metre, 16 seconds to run.

### WJazzD's tatum is more literal than a page

This changed the reading of the result. The Jazzomat annotation files each
onset at the nearest tatum of a per-beat `division` chosen to fit that
beat's onsets, so it records the performance, not a transcriber's choice:
the offbeat of a two-onset beat sits at 1/2 in 22,577 beats, at 2/3 in
5,102 and at 3/4 in 2,500; a laid-back downbeat is filed at 1/4, a pushed
one at 3/4 of the beat before. A page writes an eighth, a beat and a beat.
So the instrument reports two numbers and names its classes on both sides:

- **tatum hit**: on the annotator's tatum exactly.
- **page hit**: tatum hit, or the *swing convention* (a two-onset beat's
  offbeat at 1/2, 2/3 or 3/4 on either side), with the *annotation
  literal* class -- we wrote the beat, the annotator filed the note within
  a sixteenth of it -- set aside rather than charged.

## The shipped quantizer, 2026-09-20

| tempo band | solos | notes | tatum hit | page hit | dropped |
|---|---|---|---|---|---|
| SLOW | 38 | 17,797 | 43.7% | 47.5% | 3,607 |
| MEDIUM SLOW | 31 | 12,917 | 58.1% | 64.6% | 985 |
| MEDIUM | 86 | 36,220 | 56.3% | 66.3% | 1,881 |
| MEDIUM UP | 96 | 34,049 | 61.7% | 73.5% | 1,227 |
| UP | 201 | 98,000 | 72.9% | 85.0% | 1,299 |
| **all** | **452** | **198,983** | **64.8%** | **75.6%** | **8,999** |

The classes, as a share of the 189,984 matched notes:

| class | n | share | what it is |
|---|---|---|---|
| hit | 123,191 | 64.8% | |
| swing convention | 13,503 | 7.1% | the same eighth, filed differently |
| annotation literal | 9,192 | 4.8% | we wrote the beat; the tatum is a sixteenth off it |
| early offbeat as 16th | 5,875 | 3.1% | an eighth played at 0.3-0.5 of the beat, written a sixteenth or thirty-second early |
| laid-back beat after it | 3,111 | 1.6% | a beat played 0.2-0.3 late, written on the "e" |
| pushed beat before it | 1,246 | 0.7% | a beat played early, written in the beat before |
| late offbeat as dotted | 117 | 0.1% | the dotted eighth of the complaint |
| triplet as binary | 3,104 | 1.6% | thirds written as halves or quarters |
| binary as triplet | 3,452 | 1.8% | the other way |
| below the grid | 18,847 | 9.9% | the annotator's division is 5 or finer; the page has no such value |
| other | 8,346 | 4.4% | |
| dropped | 8,999 | 4.5% of annotated | two onsets in one grid step; one is lost |

Three readings:

1. **The dotted rhythm of bar 4 is not the quantizer's prior.** Given a
   clean grid and the whole solo, a late swung offbeat is written as an
   eighth 99 times in 100 (the *swing convention* row is where those go).
   On Birks Works it arrives from somewhere else -- the swing reading's
   confidence over a short span, or the transcriber's onsets -- and the
   instrument that will say which is `run_eval`'s per-track rows, not this.
2. **The genuine quantizer classes are the early offbeat, the laid-back
   beat and the triplet confusions**: about 9% of matched notes at medium
   and up tempos. The early offbeat is the swing warp's doing: a phase of
   0.4 or 0.5 (an eighth played straight or ahead) is mapped to 0.33-0.42
   by a warp built to bring 0.65 to 0.5, and the sixteenth or
   thirty-second grid then fits it better. The laid-back beat is the
   coarsest-within-slack rule with one onset to judge by.
3. **Ballads are a different problem.** At SLOW, 43% of notes are below
   our finest grid and 20% are dropped for want of one: the tempo-blind
   candidate set (nothing finer than a sixteenth unless a beat cannot keep
   its onsets apart) that D11 already names. A rhythm prior does not touch
   this; a tempo-aware candidate set or the double-time reading does.

## Trials, measured on the instrument, not shipped here

Each variant is a monkeypatch of `quantize` (scratchpad `quantize_trials*.py`);
the shipped numbers are the table above.

| variant | tatum | page | early offbeat | laid-back | other | dropped |
|---|---|---|---|---|---|---|
| shipped | 64.8% | 75.6% | 3.1% | 1.6% | 4.4% | 4.5% |
| one-sided warp | 67.8% | 77.5% | 1.1% | 3.1% | 4.0% | 5.4% |
| lone onset: eighth grid only | 65.6% | 77.1% | 2.5% | 0.7% | 4.5% | 4.9% |
| **two hypotheses per beat** | **70.2%** | **79.6%** | **1.2%** | 2.2% | **3.1%** | **4.4%** |
| two hypotheses + lone onset (guarded) | 71.2% | 81.3% | 0.6% | 1.0% | 3.2% | 4.7% |

- **One-sided warp** (phases at or before 0.5 untouched, [0.5, φ*]
  collapsed onto 0.5): fixes the early offbeat but the flat region merges
  onsets, so a note is lost on 1,800 more beats. Rejected on the drops.
- **Lone onset** (a beat holding one onset is offered the eighth grid
  only: one onset cannot demonstrate a sixteenth, the same reasoning as
  the three-onset gate on tuplets): halves the laid-back class, but a
  late note snapped onto the next beat collides with that beat's own
  first note and one is dropped. Needs the collision guard below.
- **Two hypotheses per beat**: every binary grid is scored under BOTH
  timing models, the raw phase (the beat is straight) and the warped one
  (the beat is swung); the coarsest grid within slack of the best (grid,
  hypothesis) wins and the note is snapped under that hypothesis. No note
  is ever moved away from the eighth it was played nearest. Every band
  up, `other` down a third, fewer drops than shipped. This is the
  principled form of the fix: the swing warp is a hypothesis about a beat,
  and a beat that was played straight should not be charged for it.
- **Both, with a guard** (the lone-onset rule declines when the eighth
  reading would land the note on the next beat's first onset): 81.3%,
  drops 4.7% -- the guard is not yet tight enough (an onset at 0.15 of
  the next beat snaps to its beat and still collides).

The next step is to ship the two-hypothesis rule in `quantize` with tests,
bump its `CACHE_VERSION`, and read the hand scores and the Omnibook through
`run_eval` before pinning: this instrument measures the quantizer on a
human's onsets and grid, and the page the listener sees is built on ours.

## What it is not

WJazzD's `duration` is a note-off, not a value, so nothing here scores
values; `notate`'s rests and ties are measured by `benchmark.readability`.
Only aggregates leave the script (ODbL); `--json` holds per-solo counts.
