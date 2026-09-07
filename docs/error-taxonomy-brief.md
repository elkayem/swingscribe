# Brief: an error taxonomy for single-line solo transcription

Paste everything below the rule into a fresh Fable 5.1 session started in
this repository. It is written to be read by that session, not by a person.

---

You are starting a self-contained research project on SwingScribe: build a
**Pareto breakdown of every transcription error** on the WJazzD solos, with
its cause, so that the next transcribe change can be aimed at the largest
class and checked against every other class. Nothing in the transcriber is to
be changed in this session. The deliverable is a measurement instrument and
what it says, not a fix.

Read, in this order, before doing anything else: `CLAUDE.md`,
`docs/benchmark-deficiencies.md` (the running deficiency list, D1-D24 and the
resolved R-entries), `docs/handoff-accuracy.md`, and this brief. Those files
carry what has already been measured and rejected. In particular: gate
sweeps, duration filters, and `htdemucs_ft` have all been measured and lost;
do not re-derive them.

## The two questions

1. **Where does the missing 0.145 go?** WJazzD mean note F1 is 0.855 over 73
   solos (`scripts/run_eval.py`). Horns sit at recall 0.92-0.94, so their
   loss is precision and timing; pianos sit at recall 0.54-0.70, which is the
   line-selection problem already under way (issue #8, D24). Every
   unmatched reference note and every unmatched transcribed note is to be
   given exactly one cause, and the causes ranked by count: a Pareto chart,
   overall and split by instrument family, because a piano miss and a
   trumpet miss are different problems.
2. **How do we know a fix did not move the error somewhere else?** The
   per-class counts become a pinned baseline that any later change is
   diffed against, the way `tests/regression/real-audio-baselines.json`
   already works for the F1s. A fix that empties one class by filling
   another must show up as exactly that.

## What already exists (use it, do not rebuild it)

- **The reference.** `wjazz/wjazzd.db` (Weimar Jazz Database, ODbL, outside
  git). Per-note `onset`, `duration`, `pitch` in the `melody` table; the
  solo's instrument, performer and tempo in `solo_info`. Only AGGREGATE
  numbers derived from it may enter the repository.
- **Our notes.** `.benchmark-notes-c0.2-d0.0.json` at the repo root: 121
  runs keyed by track filename, each `{model, stem, region, voiced_fraction,
  notes: [{onset, duration, pitch, confidence}]}`. These are the transcriber's
  current output and cost hours of CREPE; never delete or regenerate them.
  `.benchmark-grids.json` holds the beat grids.
- **The alignment.** `scripts/score_wjazz.py`'s `identify_all` locates each
  annotated solo inside our timeline by content and returns the `offset` and
  `rate` that map WJazzD seconds onto ours; `score` applies them. Two fitting
  bugs have been found in this harness before (CLAUDE.md), so read
  `src/swingscribe/wjazz.py`'s `fit_affine` and its tests before trusting a
  mapping, and check the "wrong take" control (scores under 10%).
- **The metric.** `src/swingscribe/metrics.py` wraps `mir_eval`: a match is
  onset within 50 ms and pitch within 50 cents, offsets ignored. mir_eval is
  the source of truth for what counts as a hit; your classifier explains the
  non-hits, it does not re-score them.
- **Audio evidence.** Separated stems live under
  `benchmark/.swingscribe-cache/stems/<digest>-<model>[@span]/` (the batch's
  Roformer sets) and `.swingscribe-cache/stems/`. A stems directory is keyed
  by the digest of the NORMALIZED wav, not the source file (CLAUDE.md). The
  GUI's review cache carries raw per-frame f0, periodicity and energy for
  spans it has transcribed; the batch cache does not, so if you need frame
  evidence for a class (unvoiced, gated) plan to compute it from the stem
  with numpy rather than re-running CREPE.
- **Two benchmarks, two questions.** Everything here is the WJazzD one:
  audio against a human's timestamps for the same recording. Do not touch
  the MuseScore notation numbers; they answer a different question.

## The taxonomy

Design the classes yourself, but they must satisfy these constraints:

- **Every unmatched note gets exactly one class**, decided by rules in a
  fixed order, written down, deterministic, and living in the package with
  tests (`src/swingscribe/taxonomy.py`, `tests/test_taxonomy.py`). Anything
  that compares our notes to a reference belongs in the package, never only
  in a script; that rule exists because of the two fitting bugs.
- **A substitution is counted once.** A reference note missed and a
  transcribed note nearby at another pitch are one error, not two. Pair them
  before classifying, and report pairs, pure misses and pure false positives
  as three populations.
- **`unclassified` is a class**, it is counted, and it must end under 10% of
  errors or the taxonomy is not finished.
- Start from these candidates and keep the ones the data supports. Misses:
  merged re-articulation (a matched note at the same pitch covers this
  onset; the re-tongued repeat was heard as one note), timing (same pitch
  within 50-150 ms), octave (±12 within tolerance), neighbour (±1 or ±2
  semitones), other pitch, soloist left the stem (near-digital silence in
  the chosen stem at that time, R16), unvoiced (periodicity below the
  threshold at a real note), gated (energy below the floor), too short for
  `min_note_ms`, and nothing nearby. False positives: split sustain (inside a
  matched note's span, same pitch, D2), bleed (register or loudness outlier
  against the line's neighbours, D22, or energy in another stem at that
  pitch), comping between phrases (in a gap between reference phrases),
  timing partner, and invented.
- **Report every count with its n**, split by instrument family (horn,
  piano, guitar, other) and by tempo band, because a mean over 73 hides
  the fact that the piano problem is a different problem.

## Deliverables

1. `src/swingscribe/taxonomy.py` and its tests: the classifier and the
   pairing, pure functions over note lists plus whatever stem evidence they
   need, importable without the ml group.
2. `scripts/error_taxonomy.py`: runs over the cached notes and the database,
   writes the **per-note classified table locally** to a gitignored path
   (add the path to `.gitignore`; note lists derived from commercial
   recordings never enter git), and prints the Pareto. Document the table's
   schema at the top of the script so a second analyst can load it cold.
3. `docs/error-taxonomy.md`: method, the rule table in decision order, the
   Pareto overall and per family, the three largest classes with what a fix
   would move and which other classes it puts at risk, open questions, and
   an "assumptions on the record" section. Every number carries its n.
4. **The Pareto chart itself**, aggregate only, as a page a person can read:
   publish it as an Artifact and also write the aggregate JSON behind it to
   `tests/regression/taxonomy-baseline.json`.
5. **The regression guard**: the script diffs its per-class counts against
   that pinned JSON and prints the movers, with a `--pin` flag, following
   `run_eval.py`'s pattern exactly. Define "noise" from the data, for example
   the spread of a class across bootstrap resamples of the 73 solos, and
   state the threshold you chose and why.
6. **A spot-check sample for the human**: 40 randomly drawn classified
   errors with track, time, class and the rule that fired, written beside
   the audio (not in git), so the listener can verify classes by ear and
   report which rules are wrong. Randomly drawn, not chosen.

## How to work

- Measure first; propose fixes only in the document, each with the class
  count it would move. Changing `transcribe.py` is out of scope here.
- Do not tune the classifier toward a hypothesis. If a rule is ambiguous,
  count both readings and say so; a second, independent analysis of your
  raw table will follow, and it will look for exactly this.
- Autonomous: no blocking questions. Record reasonable reversible
  assumptions in the document. Report negative results as results.
- **Subagents.** Use the Agent tool with `subagent_type: general-purpose` and
  `model: sonnet` for well-specified mechanical tasks: writing tests from a
  rule table you have fixed, the plotting and report scripts, pulling
  `solo_info` fields out of the database, running the batch and collecting
  its output, checking that nothing in the table reaches git. Keep for
  yourself: designing the classes and their order, judging ambiguous cases,
  reading the results, and everything that touches `fit_affine` or the
  metric. Give each subagent a self-contained brief with file paths and the
  environment traps below; they start cold.
- Git: commit only files you created or changed; run `git status` first and
  leave anything you did not touch alone (other sessions work in this tree).
  Never commit audio, MIDI, note lists or the classified table.

## Environment traps (each has cost a session real time)

- Run Python as `.venv\Scripts\python.exe`, never `uv run swingscribe`
  (Application Control blocks the console stub). No librosa, resampy or
  numba-dependent packages; do not add any dependency without asking.
- The GUI and CLI build their config with `Config.from_yaml("config/
  default.yaml")`; a bare `Config()` hashes to different cache keys and
  finds nothing in the cache.
- Two cache directories: `.swingscribe-cache` (GUI, repo root) and
  `benchmark/.swingscribe-cache` (batch, Roformer spans). `run_eval.py`
  takes `--cache-dir`; the current pin was made against the batch's.
- `pytest -q | grep` loses the summary line on this machine; run with
  `--junitxml=<file> > /dev/null 2>&1` and read the counts from the XML.
- A bash heredoc containing Python triple quotes fails to parse; write
  scripts to a file with the Write tool and run them.
- `uv run ruff check .` and `uv run ruff format --check .` must be clean
  before you commit.

## What done looks like

`docs/error-taxonomy.md` names the largest error class for horns and for
pianos with counts, says what fraction of the 0.145 each class is, ranks the
three fixes that would move the most, and for each names the classes that
would be at risk. `scripts/error_taxonomy.py --pin` has been run and the
aggregate JSON committed. The classified table and the 40-note spot-check
file exist locally with documented schemas. Finish the whole brief; if part
of it is blocked, finish everything else and say exactly what was left out.
