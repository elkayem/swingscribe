# Figure prior from human pages: research brief (2026-09-24)

A hand-off for one session. Deliverables, in order: a measured table of
how often each per-beat rhythmic figure occurs on human transcription
pages; the comparison of that table with what SwingScribe writes; a
prior built from it, plugged into the quantizer behind a flag; the
measurement that says whether it ships; and, if it does, the shipped
change with both baselines re-pinned. A negative result is a result and
is recorded the same way.

## Why this exists

SwingScribe's quantizer (`src/swingscribe/stages/quantize.py`,
`choose_reading`) picks a subdivision grid for each beat from the notes'
snap error alone, then applies hand-written conventions on top: two
onsets cannot vote a tuplet or a sixteenth (`min_onsets_for_tuplet`,
`min_onsets_for_sixteenth`), the coarsest grid within `grid_slack_s`
wins, a ternary reading needs every onset inside the beat, the line's
lag is taken out first (`line_lag`). Each of those rules is a fact about
what human transcribers write, discovered one at a time from a complaint
and measured on twelve hand scores and the Omnibook (docs/notation-survey.md,
docs/benchmark-deficiencies.md D35, R27-R30).

A per-beat figure frequency table is the general form of those rules: the
probability, on a human page, of each set of onset positions inside a
beat. Until now there was no human corpus big enough to count it from.
WJazzD's tatum layer must never be used for it (D36: it is Flex-Q's
algorithmic quantisation, more literal than our own). The listener's
twelve scores plus the Omnibook are 14k notes, almost all bebop.

On 2026-09-24 `src/pdf2musicxml/` (docs/pdf2musicxml.md) converted 267
PDF transcriptions by human transcribers into MusicXML under
`benchmark/Transcriptions_Other/musicxml/`. That is the corpus.

## The corpus, counted (2026-09-25, one pass over the folder after the converter's second round)

The converter was corrected on 2026-09-25 (printed tuplet numbers, time
signatures and tempo marks are now read off the page text; docs/pdf2musicxml.md)
and the listener is still spot-checking, so these numbers will move
again. Re-run the count when the folder changes; it takes seconds.

| | n (2026-09-24 in brackets) |
|---|---|
| transcriptions (`*.musicxml`) | 275 |
| notes (chord tones collapsed, grace notes dropped) | 124,615 |
| rests | 15,702 |
| tuplet notes | 12,747, 10.2% (was 8,438, 6.7%) |
| tied-into notes (not onsets) | 4,198 (3.4%) |
| bars | 21,018 |
| bars whose notes fill the signature | 19,944, 94.9% (was 87.3%) |
| beats in those full bars (quarter-note beats) | 76,896 (was 65,951) |
| bars the two OMR engines read differently | 5,613, 26.7% (median file agreement 0.76) |
| files with a tempo mark (`<sound tempo>`, quarter-note bpm, half-note marks already doubled) | 118 of 275 (was 0); Wesley Chin 49 of 53, maxgrynchuk 39 of 42, peterandwillanderson 30 of 180 |
| tempo bands over those 118 | under 100: 8; 100-160: 21; 160-220: 29; 220-300: 52; 300 and over: 8. Three marks under 40 bpm are misread digits ("quarter = 20"); drop anything under 40 |
| time signatures (bars) | 4/4 19,481; 2/2 1,293 (was 2,854, the printed signature is read now); 6/8 92; 12/8 55; 2/4 47; 10/8 34; 8/8 14 |
| printed tuplet numbers | 3,976 printed; 1,343 applied from the page over the engine's reading; 165 could not be applied (78 files); 78 read by an engine with no number printed |
| sources | Wesley Chin 53 files (hard bop, Sibelius); maxgrynchuk.com 42 (lead-trumpet charts: Ferguson, Bergeron, Sandoval; dense sixteenths); peterandwillanderson.com 180 (swing era and New Orleans clarinet and tenor, Finale, 36 scanned) |

Preview of the per-beat figure tally, full bars only, onset positions as
fractions of the beat (a tied-into note is not an onset; a chord is one
onset):

| figure | share of 76,896 beats (2026-09-24 in brackets) |
|---|---|
| 0 1/2 (eighth pair) | 38.1% (40.7) |
| no onset | 27.1% (23.4) |
| 0 (one note on the beat) | 12.5% (12.9) |
| 1/2 (one note on the and) | 7.8% (7.9) |
| 0 1/4 1/2 3/4 (four sixteenths) | 4.1% (4.9) |
| 0 1/3 2/3 (triplet) | 3.1% (2.5) |
| 0 1/2 3/4 | 1.0% |
| 1/2 3/4 | 0.8% |
| 0 1/4 1/2 | 0.4% |
| 0 1/4 (sixteenth then dotted eighth) | 0.4% |
| 1/4 1/2 3/4 | 0.4% |
| 1/3 2/3 | 0.4% (0.2) |
| 1/3 alone | 0.3% |
| 0 3/4 (dotted eighth plus sixteenth) | 0.3% |
| 0 2/3 | 0.3% |
| 3/4 alone (the lone "a") | 0.2% (0.4) |
| 1/4 alone (the lone "e") | 0.1% |
| 0 0 (an engine duplicate, not a figure) | 0.1% |

The six commonest figures are 93% of beats. The rules already shipped
(R27, R29) encode the rarity of the lone "e", the lone "a" and the dotted
eighth; the table says how rare, and it says the same for the two
hundred figures nobody has written a rule for. Between the two rounds the
triplet rows rose and the sixteenth and lone-"a" rows fell: that is the
page's printed tuplet numbers replacing engine readings, and the
direction to expect from further cleanup.

## What the corpus is and is not evidence about

- It IS a human's page: which figures a transcriber writes, how often,
  with what rests, ties, tuplets and values. Nine times the notes of the
  existing human pages, and a different mix of styles.
- It is NOT audio. Not one of these 275 recordings is on hand under
  `benchmark/`; the closest are different takes (the Omnibook's 1946
  Ornithology against the corpus's 1948 one). So the table is COUNTED
  here and JUDGED elsewhere: on the twelve hand scores and the 22
  Omnibook sides through `scripts/run_eval.py`, which is a clean
  hold-out by construction. Verify that no corpus title is a recording in
  `benchmark/` (list both; a match is dropped from the count).
- It carries a tempo on 118 of 275 files, read from the page's own
  metronome text and written as `<sound tempo>` in quarter-note bpm
  (the converter doubles a half-note mark: Advance Notice's "Swing half
  = 108" is 216). The bands are thin at the ends (8 files under 100
  bpm, 8 at 300 and over) and full in the middle. Three marks under 40
  bpm are misread digits; drop them. The other 157 files have no
  tempo. See task 3.
- It is an OMR reading, not a proofread page, and **a bar whose notes
  do not fill its signature is excluded, without exception** (the
  listener's rule, 2026-09-25: a short or long bar is a certain sign of
  a mistake somewhere in it, and there is no way to say where). That is
  5.1% of bars now (12.7% before the converter's second round). Two
  more exclusions beside it: a beat with two onsets at one position
  ("0 0", 75 beats) is an engine duplicate; and a bar the manifest
  names under its tuplet bookkeeping as one where a printed tuplet
  number could not be applied (`tuplets_unapplied`, 165 over 78 files)
  or where an engine read a tuplet the page does not print
  (`tuplets_unprinted`, 78) is a bar the tool itself doubts. The
  manifests (`*.pdf2musicxml.json`) carry the rest of the per-file
  quality: `printed_noteheads` against `notes`, `check_agreement`,
  `check_disagreeing` (the bars the two engines read differently, 26.7%
  of all bars), `off_bars`, `time_note`, `tempo`. Report the table
  under the plain filter and under a strict one that also drops every
  bar the two engines disagree on (about 70% of bars survive it); if
  the top thirty figures agree within their counts, the plain filter is
  the one to build from, and the comparison is the evidence that the
  OMR noise does not shape the table.
- **The OMR's commonest slip was a triplet read without its mark.** The
  listener saw it on the pages (2026-09-24) and the converter now reads
  the printed tuplet numbers off the page text and applies them over
  the engine's reading (1,343 of 3,976 printed numbers changed a
  reading; tuplet notes went from 6.7% to 10.2% of the corpus, beside
  the listener's own 11.2% and the Omnibook's 14.4%). What remains: a
  misread triplet that still fills its bar looks like a legitimate
  binary figure and cannot be told from one, and the 165 numbers the
  tool could not apply are in bars excluded above. So the triplet rows
  are close now but still read slightly low; say so beside them, report
  them per stratum, and re-tally when the listener's spot checks land
  (a re-tally takes seconds). Cleanup pays most in Wesley Chin's 53
  hard-bop files, the stratum nearest the judge set.
- Time signatures are read from the page now ("printed 4/4" on 182
  files); 7 files remain "too irregular to decide" (18 before), mostly
  ballads (Body and Soul, Star Dust, Round Midnight) written in 32nds
  and sextuplets. A wrong signature that still fills (4/4 read as 2/2)
  does not change a per-quarter count. Compound meters (6/8, 12/8, 10/8,
  8/8: 195 bars, under 1%) have no quarter-note beat and are left out of
  the count entirely. The listener has seen time-signature mistakes on
  the pages; those files are a cleanup for a later purpose (a human
  ballad page is what R31 waits for, docs/benchmark-deficiencies.md
  D36), not a blocker here.
- Style is skewed. 180 of 275 files are swing-era and New Orleans
  players, 42 are big-band lead-trumpet charts, 53 are the hard bop the
  judge set is made of. Count per source stratum and report whether the
  strata agree on the top thirty figures before pooling. If Bechet and
  Parker disagree on what is rare, the prior conditions on something, or
  it is counted from the stratum nearest the judge set.
- Copyright: the pages are transcriptions of commercial recordings and
  `benchmark/` is gitignored. Aggregate counts (a figure table, per-source
  shares) may be committed; note lists, bar-by-bar content and the
  MusicXML may not (CLAUDE.md, plan section 12).

## Tasks

### 1. The reader and the table (`scripts/figure_prior.py`, `docs/figure-prior.md`)

Read every `*.musicxml` in the folder and tally, per beat of each bar that
fills its signature: the sorted tuple of onset positions in the beat
(fractions, exact, from `duration`/`divisions` with `backup`/`forward`
honoured; a tied-into note and a grace note are not onsets; a chord is
one onset), applying the exclusions above (a bar that does not fill, a
duplicate onset, a bar the manifest's tuplet bookkeeping doubts, a
compound meter). Count 4/4, 3/4 and 2/4 per quarter note. Count 2/2
separately, per quarter note as well, and say what its figures look
like; it is 6% of bars and a cut-time chart's "eighth pair" is a pair of
quarters. Do not fold it into the pooled table until you have looked.
The script belongs in `scripts/` with a test on a synthetic MusicXML
file (a tie, a tuplet, a backup, a duplicate onset, a bar that does not
fill), standard library only.

Write `docs/figure-prior.md`: the table per source stratum and pooled,
with n on every row; the same with the low-quality files excluded; the
2/2 table; rests per beat position and rest values; tuplet share and tie
rate per stratum beside the survey's numbers for the listener's pages
(11.2% tuplets, tie rate 0.023) and the Omnibook (14.4%, 0.045).

Extend `scripts/notation_survey.py` with the corpus as a fourth human
column (note values, rest values, onset positions, gaps, tuplet share,
tie rate) so the existing "what we write instead" tables have it. Its
`add_musicxml` already reads LORIA's MusicXML; the corpus files carry
`<transpose>` and `<time-modification>` the same way.

### 2. Humans against humans, then us against humans

Before building anything: tally the same per-beat figures on the
listener's twelve `.mscz` scores (`mscz.parse` gives positions in
quarter notes; grace notes are zero-length) and on the 22 Omnibook files,
and put the three human tables side by side. Where the humans disagree
with each other by more than the counts can bear, the prior cannot be
sharper than that, and the table should say so.

Then tally OUR pages. `scripts/run_eval.py --json <card>` builds every
notation the harness scores; `notation_survey.py` shows how to rebuild
them from the grids cache (`run_eval.GRIDS_CACHE`) without re-running
the harness. Tally our figures on the 12 + 22 judge pages and on the 77
WJazzD pages (ours, not Flex-Q's). The table of "figure, human share,
our share, ratio" is the diagnostic even if nothing else ships: it
names what we over-write and under-write with a number on each.

### 3. What to condition on

The prior must condition only on what the quantizer knows when it runs:
the onsets, the beat grid in seconds, the swing reading. Test four
conditionings on the human corpus, cheapest first, and take the simplest
that carries information:

- nothing (one table);
- tempo band, on the 118 files with a mark (drop marks under 40 bpm):
  the quantizer knows each beat's length in seconds, and D11 found the
  running note value steps with tempo (sixteenth under 120 bpm, triplet
  eighth to 160, eighth above). The bands under 100 and at 300 and over
  hold 8 files each, so a table per band is thin at the ends; report the
  counts behind every cell, and whether the middle bands differ from
  each other at all;
- local onset density: onsets per beat over the surrounding eight beats,
  bucketed. It is computable on every page, marked or not, and at
  quantize time alike, and it is the same tempo proxy from the other
  side. If it carries what the tempo band carries, it is the one to use,
  because it covers all 275 files;
- the previous beat's figure (a bigram). Report the conditional entropy
  against the unigram's; under about 0.1 bit of gain, skip it.

Meter (3/4, 2/2) is a fifth, and the beat grid already knows it. Report
each conditioning's entropy and the counts behind the sparsest cell.

### 4. The prior in the quantizer

Add to `choose_reading` a term for each (grid, reading) candidate: the
surprisal, minus log of the table's probability, of the figure that
candidate's snapped positions make, weighted by a new
`QuantizeConfig.figure_prior_weight` in beats per nat, default 0.0.
Unseen figures get a floor (half a count). The table ships inside the
package as an aggregate JSON (`src/swingscribe/figure-prior.json`, a few
hundred rows, committed). Keep every existing rule as it is in this
version: `_keeps_apart` stays a hard constraint, the tuplet and
sixteenth gates stay, the lag rule runs first, the coarsest-within-slack
rule stays and the prior is added to the error before that comparison.
The prior is additive, not a replacement, until the measurement says
otherwise.

Adding a field to `QuantizeConfig` moves the quantize cache key. Quantize
sits below transcribe, so that costs arithmetic and no CREPE; say so in
the commit. A stage change needs a test in `tests/test_quantize.py`: a
beat whose snap error prefers the sixteenth grid by a hair and whose
figure the table calls rare is written on the eighth grid with the weight
on, and unchanged with it at zero.

### 5. Setting the weight, and the judge

Do not choose the weight on the page score. That score rises
monotonically toward "write everything as eighth pairs", the judge set is
bebop and rewards it, and `grid_slack_s` was set by the quantizer's own
20 ms round-trip criterion for exactly this reason (CLAUDE.md). Set the
weight the same way: the largest value at which `replay_onsets`' mean
round-trip error stays within the shipped criterion, and report the
whole sweep.

Then judge, at that weight, with everything reported beside its n:

- `scripts/run_eval.py --db wjazz/wjazzd.db --cache-dir benchmark/.swingscribe-cache --jobs 4 --json <card>` (about four minutes): the twelve hand scores' rhythm, value, readability and tie rate; the Omnibook's rhythm (0.7874 over 22 today) and value; never rhythm without its coverage. The hand-score rhythm mean is the number R29 moved 0.794 to 0.845; read the current value off the pinned card. Per track, not just means: how many pages up, how many down.
- `scripts/wjazz_quantize.py --db wjazz/wjazzd.db` (16 s): COLLATERAL only, dropped and merged notes and lost beats. A rise in its page hit is not evidence; a rise in dropped notes is a defect.
- The figure tables of task 2 re-tallied on our new pages: did the over-written figures come down, and did anything rare go up.

Ship if hand-score rhythm and Omnibook rhythm are up or flat with more
pages up than down, readability and the dropped-note count are not
worse, and the round-trip criterion holds. Otherwise leave the default at
0.0 and write down what happened; the flag stays for the next corpus.

### 6. If it ships

Flip the default, re-pin `tests/regression/real-audio-baselines.json`
(`--pin`) and `tests/regression/wjazz-quantize-baseline.json` (`--pin`),
list every row that moved and why, add the R-record to
docs/benchmark-deficiencies.md (next numbers: D37, R33), a bullet in
CLAUDE.md under the quantize section beside R27-R29, the finding in
docs/figure-prior.md, `ruff check` and `ruff format` clean, tests green,
commit, push.

### 7. Findings to report, not to implement

Note in docs/figure-prior.md anything the corpus says that the rules do
not, for the listener to decide on: the tuplet share per stratum against
ours (5.7% on the hand-scored pages against the listener's 11.2%); rest
placement and values; where a beat's figure depends on the one before it;
figures the humans write that our candidate grids cannot produce at all.

## Standing rules for this session (from CLAUDE.md, the ones that bite here)

- Run Python as `C:/Users/lkmcg/AppData/Roaming/uv/python/cpython-3.11.16-windows-x86_64-none/python.exe` with `PYTHONPATH=<repo>/.venv/Lib/site-packages;<repo>/src` (the venv's own launcher is blocked); ruff is `.venv/Scripts/ruff.exe`; tests are `python -m pytest`. Never pipe a script into `python -`; write the file and run it. Long jobs in the background.
- Never add a dependency without asking. The corpus reader needs only the standard library.
- No audio, MIDI, MusicXML or note lists from commercial recordings in git; `benchmark/` is gitignored. Aggregates only.
- Baselines are sacred: when a number moves, say which, by how much, over how many, and why. Every mean carries its n. Never show rhythm without coverage.
- A rule is judged on the listener's twelve scores and the Omnibook. WJazzD's Flex-Q rows and the quantizer instrument's page hit judge collateral only (D36).
- Commit only the files you wrote. The working tree may hold another session's uncommitted pdf2musicxml work (CLAUDE.md, README.md, pyproject.toml, uv.lock, src/pdf2musicxml/); do not stage, revert or reformat it. Do not switch branches. Push after each completed step. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do not tune `grid_slack_s` or the new weight on the page score (see task 5).
