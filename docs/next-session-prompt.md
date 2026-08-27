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

How I want you to work:

- Measure everything with `uv run python scripts/run_eval.py --db wjazz/wjazzd.db`.
  Know which of the five measures you are moving and say so — confusing "did we
  hear it" with "is it written the way I write it" has cost this project months.
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
