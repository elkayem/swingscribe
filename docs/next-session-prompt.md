# Prompt for the next session

Paste this in to start.

---

I want to focus this session entirely on **transcript accuracy and
readability** — making the scores SwingScribe produces look like the hand
transcriptions in `benchmark/`, without missing notes that are clearly audible
and without adding ones that are not there.

Before doing anything, read `CLAUDE.md` and then `docs/handoff-accuracy.md`.
The handoff is the important one: it lists what has already been measured and
rejected, so you do not spend the session re-deriving it. In particular, do not
re-sweep the transcriber's gates or try filtering notes by duration — both were
measured over cached spans and both lose.

The evidence points at the notater, in this order:

1. **`choose_grid` does not know the tempo (D11).** Two independent
   measurements say so: WJazzD's 456 solos show the median notated interval
   staying 96–166 ms at every tempo while the value it is written as steps 16th
   → triplet eighth → eighth as tempo rises, and a pull-back experiment
   recovered +0.041 of notated rhythm just by coarsening the grid one note at a
   time after the fact. `grid_slack` is a constant and cannot be right across
   that range.
2. **We under-write triplets by 4x (D12)**, and `choose_grid` throws away a very
   strong free prior: zero of WJazzD's 97,499 annotated beats mix binary and
   ternary subdivisions (D15).
3. **Our tie rate is 2–8x the human's (D14)** and nobody has looked at it. The
   readability measure reports it now.

There is also a cheap one that is not a code change at all: **only one of the
twenty benchmarked solos is under 100 bpm** (D16). Our notated rhythm shows no
tempo trend, which is not evidence that we are fine at slow tempos — it is
evidence that the benchmark cannot tell. Adding two or three ballads to
`benchmark/wjazzd/` makes the existing measures able to fail.

How to measure:

- **The GUI workflow is the product, and the batch is authoritative because
  it runs it.** `scripts/wjazz_batch.py` (newer than the handoff — read its
  module docstring, it is the documentation) runs the GUI's entire workflow
  unattended for every audio file in `benchmark/wjazzd/`: separate, locate
  the annotated solo by content, transcribe the located span through the
  GUI's own review path, export MusicXML, and score against the reference
  scores in `../wjazz-scores/` (a sibling of the repo — ODbL — regenerated
  on demand):

      uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db --all

  Results land in `benchmark/wjazzd/wjazzd_benchmark_test.xlsx`, one row per
  solo, carrying both the pitch measure (`pitch_*`: did we hear the right
  notes?) and the notation measure (`notation_*`: is it written the way the
  reference writes it?). **If any other harness — `run_eval.py` included —
  reports a different transcription or a different score than the GUI's
  Score It button for the same track, the other harness is wrong.** Fix it
  to match the GUI, never the reverse.
- **What "improved" means — report every change as three deltas together:**
  mean `pitch_f1` (it charges both missing and invented notes), mean
  `notation_rhythm` over TRUSTED rows only (coverage >= 0.5) with its `n`
  beside it, and the trusted count itself — a solo crossing the coverage
  floor in either direction is a real event, not noise.
  `notation_coverage` is the gate, not the headline: it never penalises an
  invented note, so it can be gamed by over-emitting. Read `notation_value`
  sceptically against a WJazzD-derived reference — those values are our own
  conventions applied to a human's grid, so it partly scores us against
  ourselves. Never report `notation_rhythm` without its coverage.
- **A full `--all` run takes 5+ hours and grows as files are added. Never
  run it to test a small change.** Iterate on a FIXED subset chosen once at
  the start of the session (`--file`, repeatable) — a fixed set keeps
  deltas comparable across runs; `--random` resamples and does not. Cached
  separations and beat grids make subset re-runs cheap. When substantial
  changes have accumulated and the sheet needs truing up, propose the full
  overnight run to me rather than launching it unprompted. The spreadsheet
  may be stale when you start — check `musicxml_written_at` against the git
  log before trusting a row. If you change transcribe's behaviour without
  changing its config, use `--fresh` or bump `transcribe.CACHE_VERSION`, or
  cached reviews will be served back unchanged and the sheet will silently
  measure the old code.
- **There is exactly ONE set of scoring criteria, defined in one place:**
  the shared scoring code the GUI's Score It button calls
  (`benchmark.score_against_notation`, `gui/ground_truth.py`). The batch,
  the GUI, and anything else all reference that one definition — never a
  private variant that can drift out of sync. The criteria are not set in
  stone: you may revise them if you can justify it, but the revision goes
  in that one place, and the spreadsheet columns must reflect it so the
  sheet always reports the criteria actually in force.
- `uv run python scripts/run_eval.py --db wjazz/wjazzd.db` still holds the
  pinned baselines and exits non-zero when one moves — useful for catching
  accidental movement, but subordinate to the GUI path above. Know which
  measure you are moving and say so — confusing "did we hear it" with "is
  it written the way I write it" has cost this project months.

How to staff the session:

- **You (Fable 5) are the orchestrator.** Keep the judgement in this
  session — deciding what to measure, interpreting the numbers, choosing
  what to change and whether a result justifies pinning a baseline — and
  delegate mechanical or execution-heavy tasks (bulk file reading, web
  searches, drafting code or prose, babysitting long sweeps) to **Sonnet 5
  sub-agents** via the Agent tool with `model: "sonnet"`. Give each
  sub-agent a self-contained prompt: what to do, which files, and exactly
  what to report back.
- If a delegated task proves too complex for Sonnet, do **not** spawn an
  Opus agent yourself. Instead, write a complete paste-ready prompt for me
  to run in a separate Opus 5 session, tell me it is ready, and **wait for
  my input** before proceeding with anything that depends on its result.

How I want you to work:
- The readability score (new, needs no reference) is the one that tracks what I
  actually complained about. A human reads 0.995; we read 0.994.
- Do not pin baselines without telling me exactly what moved and why. If a
  change costs something, say what it cost.
- Tell me when an idea you tried did not work. A measured negative is worth as
  much to me as a positive one, and I would rather hear it than have it quietly
  dropped.
- Keep the default output a **monophonic top line**. Polyphonic piano output is
  too messy for me to read. A second voice is an occasional extra, never the
  default.

Start by telling me which of the three leads you think is most likely to pay
off and why, then go.
