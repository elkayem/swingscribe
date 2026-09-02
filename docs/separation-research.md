# Separation research queue — is htdemucs the weak link?

2026-09-01. The listener's observation, after ear-checking the batch's
"wrong take" rows: too many transcriptions carry stray notes from piano
comping, and a human has no trouble telling an alto from a tenor from a
trumpet from a voice, let alone a horn from a piano. So the problem is
solvable, and the question is whether software other than htdemucs solves
more of it. This file is the plan and the ledger; results go in as they
land.

## What the measurements say the failure IS

Two different failures have been hiding under "the separation is bad", and
they want different fixes:

1. **Routing.** Demucs assigns each moment to exactly one source, and a
   horn is not a source it was trained to name. So the horn goes to
   `other` usually, to `guitar` on Ornithology and Crazy Rhythm
   (htdemucs_6s), to `vocals` on Miles' Oleo and Marsalis' Cherokees, and
   between stems mid-solo on Dolores and Orbits (a third of `other`
   digitally silent). Every batch "wrong take" of 2026-08-31 was this
   (docs/benchmark-deficiencies.md D23). It is not attenuation: the horn
   is intact, just filed elsewhere.
2. **Bleed.** Whatever stem holds the horn also holds some of the piano's
   comping and the bass, and CREPE reads those as notes in the gaps
   between phrases. On Ornithology the comping was INSIDE the `guitar`
   stem with Bird — the other stems had nothing at those pitches — so no
   cross-stem test can see it. The line-register/loudness pass (D22)
   rejects most of it after the fact; a cleaner stem would remove it at
   the source.

A better separator can only help with (2) unless it also names the horn.

## The queue, in order

### 0. No new dependency: the mix minus drums and bass (queued, running)

`other+vocals+guitar+piano` summed. The horn is in it wherever Demucs
filed it, so routing stops being a per-track judgement; the price is
every melodic stem's bleed, which is what D22 now handles. Measured over
the fixed 12-solo subset plus Ornithology with the batch's own scoring
(`scratchpad/composite_run.py`), against the same solos on their
hand-picked stems. If it reads within noise of the picked stem, it can be
the batch's default and the GUI's suggestion.

### 1. Roformer family (authorised by the listener; after the queue drains)

`audio-separator` (MIT; the engine under Ultimate Vocal Remover) runs
BS-Roformer and Mel-Band Roformer checkpoints locally on CPU. Add it
behind its own extras group (`roformer`), never in `ml`: it pulls
onnxruntime and its own model zoo, and Application Control may block its
DLLs (test, never assume — CLAUDE.md).

Plan: write the stems into the cache's own `stems/<digest>-<model>/`
convention so `library.available_stems`, `resolve_stem`, the review path
and the batch consume them unchanged; the driver skips `separate.run`
(it would try to load the name as a demucs bag) and goes ingest → beats
→ review. Score the same subset the same way. Candidates, to verify at
run time because the model zoo moves:

- a 4-stem BS-Roformer checkpoint (the community "SW" 4-stem, or the
  best 4-stem the zoo lists) — the like-for-like replacement;
- a vocals/instrumental Mel-Band Roformer, run as "vocals" against
  "everything else" — tests whether a stronger vocal model also swallows
  horns more consistently, which would make `vocals` the horn carrier
  rather than a hazard;
- MDX23C 4-stem and SCNet-XL if the zoo has them, as second opinions.

What to read off, per solo: note F1 and the three sheet numbers, AND the
routing measure — the fraction of the located span that the horn's stem
is digitally silent for (`library.stem_dropout`) and the energy ratio
between the horn's stem and its neighbours. A model that scores 0.01
better on F1 but routes the horn out of `other` on a fifth of the tracks
is a worse default.

Expected, on the record so it can be wrong: a modest precision gain from
cleaner stems, no consistent routing gain, 2-4x htdemucs' CPU time.

### 2. Query-conditioned separation — the thing a human actually does

The listener can name the instrument. Models that take the instrument as
a query rather than a fixed label set are the research direction that
matches that: text-queried separation (AudioSep, 2023, and successors)
and audio-queried "separate what sounds like this" models. These are
larger, slower, and mostly evaluated on sound events rather than music,
so this is research rather than an experiment: find what has weights and
a CPU path, try "saxophone" / "trumpet" queries on three subset solos,
and measure the same way. A win here would remove the routing problem
outright and would also answer "alto or tenor?", which no stem model can.

### 3. Instrument-specific stems from commercial services

LALAL.AI and Moises advertise wind/brass stems. That means uploading the
recordings, which this project has never done; listed so the option is on
the record, not recommended.

## How every candidate gets judged

Same fixed subset (melids 54, 70, 56, 58, 168, 218, 60, 74, 385, 121,
226, 231, plus 61), same scoring code (`review.analyze_and_cache` →
`score_span` → `ground_truth.cached_overlay`), three numbers reported
together (mean pitch F1; mean notation rhythm over trusted rows with its
n; trusted count), plus the routing measure above. Nothing is promoted to
a default on fewer than those.
