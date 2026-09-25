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

## The corpus, counted (2026-09-24, one pass over the folder)

| | n |
|---|---|
| transcriptions (`*.musicxml`) | 275 |
| notes (chord tones collapsed, grace notes dropped) | 125,352 |
| rests | 14,887 |
| tuplet notes | 8,438 (6.7%) |
| tied-into notes (not onsets) | 4,260 (3.4%) |
| bars | 20,271 |
| bars whose notes fill the signature | 17,694 (87.3%) |
| beats in those full bars (quarter-note beats) | 65,951 |
| files with a tempo mark | 0 |
| time signatures (bars) | 4/4 16,950; 2/2 2,854; 3/4 302; 2/4 97; 3/2 68 |
| sources | Wesley Chin 53 files / 35.8k notes (hard bop, Sibelius); maxgrynchuk.com 50 / 25.0k (lead-trumpet charts: Ferguson, Bergeron, Sandoval; cut time, dense sixteenths); peterandwillanderson.com 161 / 65.3k (swing era and New Orleans clarinet and tenor, Finale, 36 scanned) |

Preview of the per-beat figure tally, full bars only, onset positions as
fractions of the beat (a tied-into note is not an onset; a chord is one
onset):

| figure | share of 65,951 beats |
|---|---|
| 0 1/2 (eighth pair) | 40.7% |
| no onset | 23.4% |
| 0 (one note on the beat) | 12.9% |
| 1/2 (one note on the and) | 7.9% |
| 0 1/4 1/2 3/4 (four sixteenths) | 4.9% |
| 0 1/3 2/3 (triplet) | 2.5% |
| 0 1/2 3/4 | 1.2% |
| 1/2 3/4 | 0.8% |
| 0 1/4 (sixteenth then dotted eighth) | 0.5% |
| 1/4 1/2 3/4 | 0.5% |
| 0 1/4 1/2 | 0.4% |
| 3/4 alone (the lone "a") | 0.4% |
| 0 3/4 (dotted eighth plus sixteenth) | 0.4% |
| 1/4 alone (the lone "e") | 0.1% |
| 261 distinct figures; those seen under 20 times | 1.0% of beats |

The six commonest figures are 92% of beats. The rules already shipped
(R27, R29) encode the rarity of the lone "e", the lone "a" and the dotted
eighth; the table says how rare, and it says the same for the two
hundred figures nobody has written a rule for.

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
- It carries no tempo. Nothing in the files says how fast; a
  tempo-conditioned table is not available from this corpus. See task 3.
- It is an OMR reading, not a proofread page. 12.7% of bars do not fill
  their signature (an engine slip somewhere in the bar), and the
  figures in those bars are the long tail (591 distinct figures with
  them, 261 without). Count from full bars only. Beats with two onsets
  at one position ("0 0", 73 beats) are engine duplicates; drop them.
  The manifests (`*.pdf2musicxml.json`) carry per-file quality:
  `printed_noteheads` against `notes`, `check_agreement`, `off_bars`,
  `time_note`. Report the table with and without the low-quality files
  so its stability is on the record.
- **The OMR's commonest slip is a triplet read without its mark**, and
  it biases the table in a known direction. The listener has seen this
  on the pages (2026-09-24). A triplet read as three binary notes
  leaves its bar short, so the bar is excluded, so bars WITH triplets
  are over-represented among the excluded 12.7%: the 2.5% triplet
  figure above is a floor, not an estimate. Where the engine read the
  mark but got the values wrong, `musicxml.repair_tuplets` stripped the
  mark and kept the durations, and that bar is short too. A misread
  triplet that still fills its bar looks like a legitimate binary
  figure and cannot be told from one. So: report the tuplet figures per
  file beside the manifest's engine-agreement bars; treat the triplet
  rows as lower bounds; and if the listener has marked the missed
  triplets in any files, re-run the table on them (a re-tally takes
  seconds) and say what moved. The cleanup that matters most for the
  prior is the triplets in Wesley Chin's 53 hard-bop files, the stratum
  nearest the judge set.
- 18 files are marked "bars too irregular to decide" on the time
  signature; they are mostly ballads (Body and Soul, Star Dust, Round
  Midnight, Yesterdays) written in 32nds and sextuplets. They are 7% of
  files and their full bars are few; a wrong signature that still fills
  (4/4 read as 2/2) does not change a per-quarter count. The listener
  has also seen time-signature mistakes on the pages; those files are a
  cleanup for a later purpose (a human ballad page is what R31 waits
  for, docs/benchmark-deficiencies.md D36), not a blocker here.
- Style is skewed. 161 of 275 files are swing-era and New Orleans
  players, 50 are big-band lead-trumpet charts, 53 are the hard bop the
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
one onset). Count 4/4 and 3/4 per quarter note. Count 2/2 separately, per
quarter note as well, and say what its figures look like; it is 14% of
bars and a cut-time chart's "eighth pair" is a pair of quarters. Do not
fold it into the pooled table until you have looked. The script belongs
in `scripts/` with a test on a synthetic MusicXML file (a tie, a tuplet,
a backup, a bar that does not fill), standard library only.

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
the onsets, the beat grid in seconds, the swing reading. Test three
conditionings on the human corpus, cheapest first, and take the simplest
that carries information:

- nothing (one table);
- local onset density: onsets per beat over the surrounding eight beats,
  bucketed (this is computable on a human page and at quantize time
  alike, and it is the tempo proxy D11 found: the running note value
  steps with tempo, so a dense page is a slow or a sixteenth-note one);
- the previous beat's figure (a bigram). Report the conditional entropy
  against the unigram's; under about 0.1 bit of gain, skip it.

Meter (3/4, 2/2) is a fourth, and the beat grid already knows it. Report
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
