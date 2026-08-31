# Handoff: making the transcripts look like the hand transcriptions

Written 2026-08-27, at the end of the session that landed the readability
metric. The next session's job is accuracy and readability of the final score:
**not missing notes, not inventing notes, and writing what is there the way a
human writes it.**

Read `CLAUDE.md` first — it is the working summary and it is dense. This file
is the part that does not belong there: what has already been tried, what the
measurement said, and which threads are worth pulling.

---

## 1. Know which question you are asking

This project has lost months to conflating two measures, and the confusion
reappears in every new investigation.

| | asks | source of truth | today |
|---|---|---|---|
| **WJazzD** (`score_wjazz.py`) | did we HEAR what was played? | a human's per-note onsets in seconds, same recording | mean note F1 **0.8095** over 20 solos |
| **MuseScore** (`score_benchmark.py`) | would this NOTATE the way a human notated it? | ten hand transcriptions | mean note F1 **0.4472** over 10 |
| **WJazzD notation** | is the rhythm WRITTEN the same? | WJazzD's `bar`/`beat`/`tatum` | mean rhythm **0.582** over 19 trusted of 20 |
| **notation vs hand scores** | rhythm and note value | ten hand transcriptions | rhythm **0.712**, value **0.631** |
| **readability** (new) | is the page writable AT ALL? | nothing — a property of our own page | **0.9939** over 30, a human reads 0.995 |

"Missing notes" is the first row. "Doesn't look like my transcription" is the
third, fourth and fifth. A change that fixes one can move another the wrong
way, and reporting only the one that improved is how this went wrong before.

Everything runs in one command:

    uv run python scripts/run_eval.py --db wjazz/wjazzd.db

It exits non-zero when a baseline moves. That is the point. `--pin` rewrites
them, and CLAUDE.md's rule stands: say what moved and why.

**Newer than this handoff: `scripts/wjazz_batch.py` is now the main vehicle
for measuring end-to-end performance.** It runs the GUI's whole workflow
unattended over every audio file in `benchmark/wjazzd/` — separate, locate
the solo by content, transcribe the located span through the GUI's own
review path, export MusicXML, score against the reference in
`../wjazz-scores/` — and writes one row per solo to
`benchmark/wjazzd/wjazzd_benchmark_test.xlsx`, carrying both the pitch
measure and the notation measure, prefixed apart. **The GUI workflow is the
product, and the batch is authoritative because it faithfully runs it** —
if `run_eval.py` (or anything else) disagrees with the GUI's Score It
button for the same track, the other harness is the one that is wrong; fix
it to match the GUI, never the reverse. `run_eval.py` keeps its use as the
pinned-baseline regression gate. The batch's module docstring is the
documentation and is worth reading in full — the cache sharing, the
two-pass solo location, and the GUI-exact rounding are all things that bit
once already.

---

## 2. What has already been measured — do not redo these

Each of these cost real time. The numbers live in `docs/`; this is the index.

### On the transcriber (missing / spurious notes)

- **Loosening the gates does not buy recall.** `voicing_threshold`,
  `min_note_ms`, `pitch_persist_ms`, `median_filter_ms`, a pitch-stability
  rescue and a confidence-weighted short-note floor were all swept over six
  cached spans. Baseline P 0.715 / R 0.762 / F1 0.735. **Nothing beat it** —
  every route to recall cost about two false notes per true one.
  The GUI's cached reviews carry raw f0 + periodicity + energy, so re-running
  this sweep costs no CREPE. Do that before touching any threshold.
- **Never filter notes by duration.** Against 302 erasure labels a 0.12 s
  floor removes 41% of erased notes and 28% of KEPT ones. Confidence does
  separate them (AUC 0.830) but at a 0.65 floor it still costs 7% of kept
  notes to remove 30% of erased ones. It is a cue for SHADING the review UI,
  not for deleting.
- **Missing notes are a PIANO problem.** Over six spans, horn recall reads
  0.917 and 0.936 against 0.538–0.697 for the pianos. Do not go hunting for
  missing notes on a horn — check which instrument you are looking at first.
  (The listener's own report of missing notes on Sonny Clark's There Will
  Never Be Another You was a piano solo transcribed as `horn-led`, which
  skips the oracle entirely. The GUI now says so on screen.)
- **The piano oracle as the PRIMARY line does not work yet.** Giant Steps
  0.705 → 0.879, but the Peterson goes 0.648 → 0.627. The model hears the
  notes; we pick the wrong ones. That is melodic-line selection, open-issue #8.
- **What does work is the oracle as a SECOND OPINION** (`corroborate.py`:
  `snap_octaves`, `corroborate`, `fill_gaps`). Every piano solo improved on
  both halves of F1. `fill_gaps` moved recall 0.680 → 0.744 for precision
  0.677 → 0.666 over four spans.
- **NEVER route a horn to the piano oracle.** A piano model asked about a
  saxophone vouches for nothing, and rejection then deletes the whole line.

### On the page (how it is written)

- **`MIN_REST` is an EIGHTH.** The listener wrote one sixteenth rest in 504.
  Raising it removed 93% of sub-eighth rests. It costs notated `value`
  0.672 → 0.628, because an eighth becomes a dotted eighth — that price is on
  the record and the listener accepted it explicitly.
- **Triple metre was unimplemented**, and it was the cause of the "dotted 1/32
  notes with strange ties" in bar 18 of Someday My Prince Will Come. Bare
  halving of a 3/4 bar goes 3 → 1.5 → 0.75 and never lands on a beat.
  `split_points` fixed it: bad bars 12 → 0, zero-duration notes 14 → 0,
  32nds 111 → 0, and tuplets 0 → 38 (binary bisection of a 3/4 bar never
  yields a one-beat sub-unit, so triplets were structurally unreachable).
- **Closing a gap from the RIGHT scores better and still may not ship.**
  Pulling the note after the gap backwards reads rhythm 0.711 → 0.752 with
  `value` unchanged, but the moved onset lands on the previous note's off-grid
  end, which inside a ternary beat is not a third — it breaks the tuplet group
  `close_short_gaps` exists to protect. That +0.041 is D11 arriving from a
  second direction. **Fix `choose_grid`, not the repair pass.**
- **`snap_values` (added this session) is neutral in the shipped pipeline.**
  Durations were never snapped to a grid, only onsets — but `without_overlap`
  truncates every note at the next onset, so 93–96% of them already fill their
  gap exactly, which is grid-to-grid. (Not `notated_durations`: `legato_fill`
  ships at 0.0, so that function returns early on our own path. Worth knowing
  before you go and read it.)
  Measured: it moves NOTHING across our own 30 notations. It is decisive on
  scores built from WJazzD's annotation, where durations come from performed
  seconds with no legato inheritance — readability 0.788 → 0.982 over the 172
  solos whose onsets sit on writable subdivisions.
- **`grid_slack` must NOT be tuned on the notation score.** That score rises
  monotonically toward "write everything as eighth notes", which three bebop
  solos reward and real sixteenth-note material would not.

---

## 3. Where the evidence points, ranked

### 1. `choose_grid` does not know the tempo (D11) — start here

**Two independent measurements point at the same line of code.**

Over 456 WJazzD solos the median notated interval stays **96–166 ms at every
tempo**, while the value it is written as steps: sixteenth under 120 bpm,
triplet eighth from 120–160, eighth above 160. Log-log slope 0.705, r 0.690.
A player's fastest comfortable run is roughly constant in *seconds*; the page
absorbs that by changing what a beat is divided into.

`grid_slack` is a **constant**. It cannot be right across that range.

And from the other side: the pull-back experiment recovered +0.041 of notated
rhythm purely by hand-coarsening one note at a time after the fact — that is,
the grid chosen was too fine, and a repair pass could see it when `choose_grid`
could not.

**A third measurement landed at the end of this session and it is monotone.**
Notating all 456 WJazzD solos from the annotators' own metrical positions and
scoring the page for readability:

        bpm      n   readability   note<16th    ties
       <100     59       0.5689      43.60%    0.248
    100-140     97       0.8518      13.78%    0.175
    140-200    138       0.9275       6.07%    0.151
    200-280    121       0.9728       1.34%    0.124
      >=280     41       0.9863       0.15%    0.109

At a slow tempo a human divides the beat far more finely, and 43.6% of the
resulting values fall below the sixteenth our value set floors at.

Concrete first step: make `grid_slack` a function of the beat period and
re-run. The acceptance criterion is quantize's own 20 ms round trip (see
`docs/m5-quantize.md`), NOT the notation score.

### 2. We under-write triplets by 4x (D12)

0.9% of our notes carry a tuplet, against 4.1% in the hand scores and **23.9%
of WJazzD's 197,177 notated intervals**. 444 of 456 solos use ternary on more
than 10% of their notes.

Prime suspect: `choose_grid`'s rule that three onsets are needed before a
tuplet is allowed. Not yet re-measured.

**There is an unused prior here and it is very strong: zero of WJazzD's 97,499
annotated beats mix binary and ternary subdivisions.** A beat is one or the
other. Nothing in `choose_grid` knows that, and neighbouring beats carry
information about each other that is currently thrown away.

### 2b. The benchmark cannot see the failure mode D11 predicts (D16)

Our own notated rhythm shows **no tempo trend at all** — 0.615 below 145 bpm
(n=7) against 0.565 at or above (n=13). That is not evidence that we are fine
at slow tempos; it is evidence that we cannot tell. **Exactly one of the twenty
benchmarked solos is under 100 bpm.**

The one that is — Charlie Parker's Don't Blame Me at 64 bpm — is the sharpest
illustration available: our notation of it reads readability **1.000** and
notated rhythm **0.597**, while the WJazzD-derived score of the same solo reads
readability **0.331**. A page can be perfectly writable and still be the wrong
page. The human wrote sixteenths; we wrote eighths and quarters, and every
readability measure applauds.

Adding two or three ballads to `benchmark/wjazzd/` is the cheapest thing on
this list and it makes the existing measures able to fail.

### 3. Ties — nobody has looked at this yet

The new readability output reports it. Our tie rate runs **0.030–0.180** across
30 notations; the ten hand transcriptions sit at **0.022**. That is 2–8x, and
"strange ties" is in the listener's own words.

Some are legitimate (a long note crossing a barline). Some are the
`split_for_meter` recursion fragmenting a value that should have been one
symbol. Nobody has separated the two. This is cheap, and the instrument now
exists.

### 4. Melodic-line selection (open-issue #8)

The listener has been explicit about what they want, and it is not what we
have been optimising: **show the top one or two notes and let them delete the
rest.** That flips the target from precision to recall.

Measured: top-2 of each onset cluster contains the note the human notated
93–96% of the time, against 0.74 recall for what ships. Precision is ~0.5,
which is the trade they asked for. Loudest-of-cluster beats highest-of-cluster
on the hard case (Peterson 0.583 → 0.715 F1); a register floor does NOT
generalise.

Standing caveat, from the session this handoff closes: the listener has since
said the polyphonic piano output is **too messy to read**, and asked to keep
the default a monophonic top line, with a second note occasionally and never
by default. So what is wanted here is a review affordance, not a change to
what `notes` contains.

### 5. Should we train a model? (asked, not yet acted on)

My reading of the material available:

- **Not for the acoustic step.** WJazzD contains no audio. Training an
  audio → notes transcriber needs hundreds of hours of aligned audio, which we
  do not have and cannot assemble from commercial recordings.
- **Yes, plausibly, for the notation step.** 456 solos and ~200k notes, each
  carrying a performed onset in seconds AND a human's metrical position, is a
  clean supervised dataset for exactly the problem items 1–3 describe:
  *performed timing → written rhythm*. It is small, input and output are both
  short symbol sequences, and what it would replace is a hand-tuned constant.
  This is the highest-value ML idea available, and it is not the one the plan
  anticipated.
- Do the rule-based work first regardless. D11 and D12 are specific and cheap,
  and they will produce exactly the features such a model would need.

---

## 4. Instruments that now exist — use them, do not rebuild them

- **`scripts/wjazz_batch.py`** (added after this handoff was written) — the
  whole GUI workflow, unattended, over `benchmark/wjazzd/`. The spreadsheet
  it maintains (`benchmark/wjazzd/wjazzd_benchmark_test.xlsx`, one row per
  melid, never committed) **may be stale when you arrive** — the
  `musicxml_written_at` column says when each row was computed. A full
  `--all` run takes 5+ hours and is an overnight, propose-it-first affair;
  iterate on a fixed subset (`--file`, repeatable — fixed so deltas stay
  comparable) and true up the whole sheet only when substantial changes
  have accumulated. Cached separations and beat grids make subset re-runs
  cheap; `--fresh` (or bumping `transcribe.CACHE_VERSION`) is required
  after changing transcribe's behaviour without changing its config, or
  cached reviews are served back unchanged. The scoring criteria live in
  exactly ONE place — the shared code the GUI's Score It button calls
  (`benchmark.score_against_notation`, `gui/ground_truth.py`) — and the
  batch references it, never a private variant. Revisions are allowed, in
  that one place, with the spreadsheet columns updated to match, so the
  sheet always reports the criteria actually in force.
- **`benchmark.readability(notation)`** — needs no reference, so it runs over
  every notation the harness can build, not only the ten with hand scores.
  Reports `short_rests`, `short_values`, `tie_rate` and a composite. Anchored:
  a human reads 0.995 (6 sub-eighth rests in 487, and 13 sub-sixteenth values
  in 3646, counted straight off the .mscz XML).
- **`wjazz.annotation_notation(db, melid)`** — a WJazzD solo as a `Notation`.
  Positions and pitches are a human's; rests and note values are OURS, so it
  is a ground truth for what was played and where it sits in the bar, and NOT
  evidence about note values. `scripts/wjazz_score.py` writes them as MusicXML.
- **`mscz.parse_any`** reads MusicXML as well as MuseScore, and the GUI's
  ground-truth view accepts both. Any transcription can now be a ground truth.
- **`run_eval.py`'s note cache is fingerprinted.** If you change transcribe's
  behaviour without changing its config, bump `transcribe.CACHE_VERSION` or
  the harness will score stale notes and say nothing about it (R15).
- **The GUI's cached reviews carry raw f0 + periodicity + energy**, so any
  threshold sweep costs no CREPE.

## 5. Traps on this machine

Beyond CLAUDE.md's list, four that bit during this session:

- **`Path.read_text()` / `write_text()` without `encoding=` use cp1252** on
  Windows and will silently corrupt a UTF-8 source file. Always pass
  `encoding="utf-8"`.
- **Source files are CRLF in the working copy.** A patch script that
  round-trips through `\n` rewrites every line and buries the real diff.
- **A default argument is bound at `def` time.** Monkeypatching
  `notate.MIN_REST` in a sweep does nothing — rebind `__defaults__`.
- **WJazzD is ODbL share-alike.** Scores generated from it are derivatives of
  the database and must stay out of this repository; `scripts/wjazz_score.py`
  refuses an `--out` inside the repo.
