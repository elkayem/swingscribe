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

### 0. No new dependency: the mix minus drums and bass — MEASURED, REJECTED

`other+vocals+guitar+piano` summed. The horn is in it wherever Demucs
filed it, so routing stops being a per-track judgement; the price is
every melodic stem's bleed, which D22 was hoped to handle. It does not,
not at this level. Same solos, same scoring, pitch F1 on the sum against
the located stem (12 dB floors both sides):

| | picked stem | sum | |
|---|---|---|---|
| Blue Train 218 | 0.881 | 0.760 | |
| Mr PC 226 | 0.848 | 0.730 | |
| There Will Never 74 | 0.937 | 0.829 | |
| Cheese Cake 121 | 0.898 | 0.815 | |
| Embraceable You 56 | 0.880 | 0.886 | the one gain |
| Ornithology 61 | 0.809 | 0.799 | |
| **subset + 61 mean (13)** | **0.880** | **0.815** | |
| Dolores 427 (split) | 0.660 | 0.686 | |
| Cherokee 446 (split) | 0.718 | 0.718 | |
| Cherokee II 447 (split) | 0.700 | 0.634 | |
| My Favorite Things 228 (split) | 0.601 | **0.156** | CREPE follows Tyner |

Worse on 12 of 13 well-routed tracks, worst where the pianist is
strongest, and no rescue on the split-routing tracks it was built for:
a loud piano in the sum out-shouts the horn and the Viterbi f0 decoder
follows it. Summing stems undoes the separation's one real service.

What it points to instead (**0b — measured, first cut**): keep the stems
apart and choose BETWEEN them per moment, not per track. Every candidate
stem (`other`, `guitar`, `vocals`, `piano`) transcribed over the located
span; per 1 s bin, a CEILING that takes the stem with the most matched
notes (reference in hand), and a reference-free CHOOSER that takes the
stem with the most confidence-weighted note duration, Viterbi over bins
with a switch penalty (`scratchpad/stem_mosaic.py`). Time+pitch F1 over
the span:

| melid | best single stem | ceiling (per-second, ref) | chooser v1 (pen 0.5) | switches |
|---|---|---|---|---|
| 427 Dolores | guitar 0.633 | 0.700 | **0.687** | 2 |
| 434 Orbits | guitar 0.749 | 0.772 | 0.747 | 1 |
| 446 Cherokee | vocals 0.672 | 0.737 | 0.691 | 6 |
| 447 Cherokee II | vocals 0.631 | 0.688 | 0.647 | 4 |
| 228 My Favorite Things | other 0.563 | 0.662 | **0.641** | 4 |
| 61 Ornithology | guitar 0.788 | 0.820 | 0.788 | 0 |
| 399 Crazy Rhythm | guitar 0.738 | 0.777 | 0.761 | 10 |

Three readings. (1) Switching per second is worth +0.03 to +0.10 even
with the reference choosing — routing is real but it is not the whole
gap on these tracks; the ceilings sit at 0.66-0.82, so on Dolores, the
Cherokees and 228 the horn is SMEARED across stems or lost to the
separation, not merely misfiled, and that is the separator-quality
question the Roformer trial asks. (2) The reference-free chooser gets a
fair share of the ceiling (Dolores +0.054 of 0.067, 228 +0.078 of
0.099) with 2-4 switches. (3) With NO switching (pen 2.0) the chooser
picks the right stem on every track by itself — a reference-free stem
recommendation the GUI could make and the batch could use instead of a
reference-guided locate order. Not integrated; the Roformer trial comes
first, because a cleaner separation raises every row of this table.

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
a query rather than a fixed label set are the direction that matches
that. Findings from the first look (2026-09-01, links at the end):

- **Banquet** (Watcharasupat & Lerch, ISMIR 2024; `query-bandit` on
  GitHub, MIT) is the strongest lead. A band-split separator with ONE
  decoder, conditioned on a PaSST embedding of a *reference clip of the
  instrument you want* ("bring your own query"), trained on MoisesDB —
  whose taxonomy goes beyond four stems and includes wind/reed/brass
  stems. The paper reports it approaching 6-stem HTDemucs on the four
  standard stems, beating it on guitar and piano, and extracting "less
  common stems such as reeds and organs". Weights are on Zenodo
  (`ev-pre-aug.ckpt` recommended); inference is a CLI
  (`train.py inference_byoq` with a query wav). GPU is recommended for
  training batch sizes; single-track CPU inference is untested here and
  is the first thing to find out. The query being AUDIO is the point: a
  few seconds of the soloist from the track itself is a query nobody has
  to label, and "alto or tenor" is answered by which clip you hand it.
- **AudioSep** (2023, open weights) separates by TEXT query ("saxophone")
  with a CLAP text encoder over a ResUNet; strong zero-shot on sound
  events and instruments in its own benchmarks, less evidence on dense
  jazz mixes. Successors (FlowSep, OmniSep, ZeroSep) exist; none is a
  drop-in.
- **MoisesDB** itself (240 tracks, 38 instruments, 11 top-level stems) is
  what any "wind stem" model gets trained on; Moises' own beyond-4-stem
  separator is commercial.

Experiment, when the Roformer trial is done: Banquet on three subset
solos with a query cut from the solo's own first phrase, stems written
into the cache's `stems/<digest>-banquet/` convention, scored the same
way. A win here removes routing outright.

### 3. Instrument-specific stems from commercial services

LALAL.AI and Moises advertise wind/brass stems. That means uploading the
recordings, which this project has never done; listed so the option is on
the record, not recommended.

### Roformer trial — first result (2026-09-02, one track)

The zoo's only non-Demucs multi-stem checkpoint is **BS-Roformer-SW**
(jarredou), and it is SIX-stem: drums, bass, other, vocals, guitar,
piano. On Ornithology (181 s) it took 7.5 minutes on this CPU against
htdemucs' ~0.85 — about nine times slower — and it routed Bird to
`other` (in-span RMS 0.104; `guitar` 87% digital silence) where
htdemucs_6s had filed him under `guitar` and left `other` a quarter
silent. Scored through the batch's own path on the same located span,
14 dB floors both sides:

| Ornithology 61 | htdemucs_6s (guitar) | BS-Roformer-SW (other) |
|---|---|---|
| pitch F1 | 0.803 | **0.875** |
| notation rhythm | 0.615 | 0.615 |
| coverage | 0.778 | **0.851** |

Then the subset and the split-routing tracks, same scoring, same floors,
each track on the Roformer's `other` stem (which is where it put EVERY
horn — no track needed `guitar` or `vocals`):

| | htdemucs_6s (located stem) | BS-Roformer-SW (`other`) |
|---|---|---|
| **subset, mean pitch F1 (n=12)** | 0.878 | **0.903** |
| subset, trusted rhythm (n=12) | 0.696 | **0.709** |
| subset, trusted count | 12 | 12 |
| **routing-trouble five, mean pitch F1** | 0.696 | **0.838** |
| routing five, trusted count | 4 | 5 |

Per track on the subset: up on 10 of 12 (Chet Baker 0.862 → 0.969, Suede
Shoes 0.872 → 0.931, Embraceable You 0.881 → 0.926, St Thomas 0.892 →
0.926), down on Blue Train (0.880 → 0.866) and Cheese Cake (0.896 →
0.887). The routing five: Dolores 0.660 → 0.913, Cherokee 0.718 → 0.834,
Cherokee II 0.700 → 0.791, My Favorite Things 0.601 → 0.776 (coverage
0.47 → 0.70, trusted now), Ornithology 0.803 → 0.875. The 0.66-0.82
"ceilings" measured under htdemucs_6s in 0b were htdemucs_6s's ceilings:
the horn was not smeared by the recording, it was smeared by the
separator.

The price is CPU: 7-8 minutes per 3 minutes of audio on this machine,
26 minutes for Blue Train — roughly nine times htdemucs. One-time per
track, cached like every other stem. **The listener's answer (2026-09-02):
separate only the selected span.** `SeparateConfig.span` crops the track
to the selection plus a 3 s margin, separates that, and pads the stems
back to full length (silent outside), so nothing downstream changes and
a solo costs a third of the file. The GUI sends the selection with every
Separate click; the batch keeps its whole-file locate on htdemucs_6s and
separates the located span alone with `--separation-model`. Verified on
Limehouse Blues through the batch: located in `guitar` on htdemucs_6s,
the 33 s span separated by the Roformer in 183 s (model load included),
pitch F1 0.842 → 0.858, coverage 0.831 → 0.861, the horn in `other`.

**Reading.** Both halves of the diagnosis moved: routing (every horn in
`other`) AND bleed (fewer notes on Chet Baker, 161 → 133, at higher F1).
This is the largest single gain of the project's measurement history and
it came from a model the plan's "drop a checkpoint in behind the same
interface" clause anticipated. Not yet a default: the two dips need a
look, the pianos are unmeasured on it, and the full sheet is a day of
CPU at this speed.

### Roformer notes from the first look

`audio-separator` installs CPU-only as `pip install "audio-separator[cpu]"`
(MIT; bundles onnxruntime for its MDX models, torch for Roformers, and
asks for UVR attribution when its default models are used). Its model
zoo is listed at run time (`audio-separator --list_models`); the README
names `BS-Roformer-SW` and the `model_bs_roformer_ep_317_sdr_12.9755`
vocals checkpoint, and ships the same htdemucs bags we already run, so
one driver can compare everything on identical audio. Which 4-stem
Roformer checkpoints the zoo carries is read off that list at install
time, not assumed here.

## How every candidate gets judged

Same fixed subset (melids 54, 70, 56, 58, 168, 218, 60, 74, 385, 121,
226, 231, plus 61), same scoring code (`review.analyze_and_cache` →
`score_span` → `ground_truth.cached_overlay`), three numbers reported
together (mean pitch F1; mean notation rhythm over trusted rows with its
n; trusted count), plus the routing measure above. Nothing is promoted to
a default on fewer than those.

## Sources (first look, 2026-09-01)

- python-audio-separator: https://github.com/nomadkaraoke/python-audio-separator
  (README, and discussion #133 "which model should I use")
- Banquet / query-bandit: https://github.com/kwatcharasupat/query-bandit ;
  paper https://huggingface.co/papers/2406.18747 ; weights
  https://zenodo.org/records/13694558
- MoisesDB: https://arxiv.org/pdf/2307.15913
- AudioSep: https://arxiv.org/html/2308.05037
