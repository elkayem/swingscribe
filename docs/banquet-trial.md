# Banquet trial: query-by-audio separation as a routing-free soloist stem

2026-09-30. A research trial, run once. Instruments: `scripts/banquet_trial.py`
(Windows: the manifest, the transcription, the scoring, the sanity probes) and
`scripts/banquet_wsl.py` (WSL: the model). Nothing in the pipeline changed, no
pin moved, nothing was written to a harness cache, and nothing downloaded is in
the repo.

## Verdict: not worth a full evaluation

Banquet's stem is worse than the Roformer's `other` on **every one of the 16
spans**:

- **Mean WJazzD note F1 falls from 0.853 to 0.562**, a change of **-0.290**
  (95% interval -0.366 to -0.216, n = 16 spans on 16 recordings). All 16 went
  down; sign test p < 0.001.
- **On the routing-trouble solos it was meant to fix, the fall is 0.844 to
  0.542**: -0.302 (-0.417 to -0.192), down on 10 of 10.
- **Precision falls as well as recall.** Precision -0.246 (-0.306 to -0.190),
  recall -0.311 (-0.400 to -0.226). So the stem is not just quieter: it loses
  the soloist's notes and adds false ones.

The failure it was meant to remove, it brings back. On 8 of the 16 spans, the
Banquet stem is digitally silent (R16's test) for at least a tenth of the
solo; on two Parker sides, for all of it. The Roformer's `other` is silent for
at most 2% of any span.

Its two premises no longer hold, either:

- **Routing was htdemucs_6s's problem**, and BS-Roformer-SW already solved it.
  Every one of these horns is in the Roformer's `other`, including Oleo's muted
  trumpet (R16) and all seven D23 tracks.
- **The weights are CC BY-NC-SA 4.0**, so Banquet could never be the shipped
  default. It could only sit behind an opt-in group, as MuScriptor would.

The checks below rule out the obvious objections:

- **The machinery works.** Asked for the bass on I Fall In Love Too Easily,
  the same model returns a stem within 1 dB of the Roformer's bass (SI-SDR
  +9.8 dB against it).
- **The queries are the soloist.** WJazzD has the soloist sounding for 63-94%
  of every query window.
- **A longer, untiled query is worse, not better.** With a 10 s query, F1 is
  -0.107 against the 6 s one.
- **A query from another recording of the same instrument is worse too.**
  -0.089 against the self query.

What would reopen this: a query separator trained on wind and brass, and on
recordings like these (old, often mono, a rhythm section in one room), or a
checkpoint that other people show working on jazz. Keep the two scripts for
that day. At about 40 minutes of GPU time for this set, they are cheap to
rerun.

## The question

docs/separation-research.md (2026-09-01) ranked **Banquet** as "the strongest
lead" and never ran it. It is by Watcharasupat and Lerch (ISMIR 2024):
[code](https://github.com/kwatcharasupat/query-bandit),
[paper](https://arxiv.org/abs/2406.18747),
[weights](https://zenodo.org/records/13694558).

- **What it is.** A band-split separator with one decoder, conditioned on a
  PaSST embedding of a QUERY clip.
- **What it was trained on.** MoisesDB, whose taxonomy has reed, brass and
  wind stems.
- **The idea.** Hand it a few seconds of the soloist and it returns that
  instrument's stem.

That could remove two failures:

- **Stem routing** (D23): htdemucs_6s filed horns under `guitar` or `vocals`.
- **The soloist leaving the stem** (R16): on htdemucs, Oleo's muted trumpet
  was in `vocals` for 30% of the solo.

It is measured against the stem that ships: BS-Roformer-SW's `other`.

## Setup

- **Where it runs.** In WSL (Ubuntu 26.04.1, kernel 6.18.33.2), in a venv
  outside the repo (`~/banquet/.venv`, Python 3.11.16, 88 packages, 5.6 GB).
  Banquet imports librosa, and through it numba, which Smart App Control
  refuses here and CLAUDE.md forbids in the project. It also imports
  pytorch_lightning.
- **Versions.** torch 2.5.1+cu124, torchaudio 2.5.1+cu124, pytorch-lightning
  2.5.6, torchmetrics 1.8.2, hear21passt 0.0.26, timm 1.0.30, numpy 2.4.6,
  librosa 0.11.0, numba 0.67.0, omegaconf 2.3.1, soundfile 0.14.0,
  torch-audiomentations 0.12.0, fire 0.7.1, pandas 3.0.6. The repo has no
  requirements file, so that list is its imports; the recipe is in the WSL
  script's docstring.
- **The GPU.** CUDA works in WSL through the Windows driver (616.92), with
  nothing installed in Linux but the pip wheels.
- **Settings.** The authors' checkpoint (`ev-pre-aug.ckpt`, which their README
  recommends), config (`expt/bandit-everything-test.yml`) and chunked
  inference: 6 s chunks, 0.5 s hop, Hann overlap-add.
- **The query.** Handled the authors' way: a clip shorter than the 10 s the
  model was trained on is tiled to 10 s, as `train.py inference_byoq` does.
- **The query encoder is not downloaded.** PaSST is built with
  `pretrained=False`, and the checkpoint's STRICT load fills every parameter.
  The 645 MB checkpoint holds the separator, its optimiser state and the
  frozen 86M-parameter PaSST, so no weights beyond the approved checkpoint
  are fetched.

Two changes to HOW it runs, neither changing what it computes. Both were
measured against the authors' own code on Limehouse Blues:

- **The query is embedded once per span.** The authors' `adapt_query` runs
  PaSST on the same 10 s query for every batch of chunks: 55-173 times per
  span at batch 3.
- **The chunks stay on the CPU.** The authors' `chunked_inference` puts 12
  overlapping copies of the whole span on the GPU. That is 842 MiB beyond the
  model for a 116 s solo, on a card this trial shared with two other jobs.
  `chunked_inference_offload` sends one batch at a time.

With both changes on, the output matches the authors' plain run at SNR 141 dB
at the same batch size, and at 75 dB at another batch size (float
reordering).

**Cost.**

- **GPU.** The 16 spans hold 1,725 s of audio. They took 2,348 s on the RTX
  3050, shared with other jobs throughout: 0.73x real time, ranging from
  0.31x to 1.37x per span as the other jobs came and went.
  - The later spans, with less contention, ran at 1.0-1.4x real time.
    BS-Roformer-SW runs at 1.7x on the same card.
- **CPU.** WSL, 4 threads: one batch of 4 chunks took 37 s. At a 0.5 s hop
  the 39 s Limehouse span is 39 such batches, about 24 minutes, or some 35x
  slower than real time. The whole set would take about 12 hours. The
  Roformer runs at 0.4x real time on this CPU.
- **Memory.** With the authors' chunking, batch 4 wanted more than 3.3 GB of
  GPU memory even on a 39 s span. Offloaded, batch 4 fits under 3 GB; the
  run used batch 3 under a 2.4 GB cap.
- **Failures.** Twice a cuDNN call failed (`CUDNN_STATUS_EXECUTION_FAILED`,
  then "unknown error") while other jobs held the card. The runner is
  resumable, and a wrapper restarted it.

## Downloads

Everything is under `C:\Users\lkmcg\swingscribe-research\banquet`, outside
OneDrive and outside AppData. The listener approved these downloads on
2026-09-30.

- **`query-bandit/`**, a git clone of
  `https://github.com/kwatcharasupat/query-bandit.git`.
  - Commit `79ed5bb75e5c3a40cd319d9d990cee913fc65c26` (2025-07-29); the
    commit is the content hash.
  - **MIT** (`LICENSE`, "Copyright (c) 2024 Karn Watcharasupat").
- **`weights/ev-pre-aug.ckpt`**, from
  `https://zenodo.org/api/records/13694558/files/ev-pre-aug.ckpt/content`.
  - 645,470,187 bytes.
  - sha256 `657295888781e62ef50593002720d2edb3858b9e5bbfabf0c54f715a0da4b9e2`.
  - md5 `4dfb91d6d27c2dfd4992a15070915541`, which equals the checksum Zenodo
    lists.
  - **CC BY-NC-SA 4.0**, as the Zenodo record states (DOI
    10.5281/zenodo.13694558, published 2024-09-05).
  - The record's other 14 checkpoints were not fetched.
- **`zenodo-record-13694558.json`**, that record's metadata
  (`https://zenodo.org/api/records/13694558`).
  - 6,860 bytes, sha256
    `7eddfc1e9fed625c336252f04315679fb64b3e594eabf39915f6727dafe8d839`.
- **The WSL venv's packages**, from PyPI. These are build tools the model
  cannot run without, and they are listed under Setup. hear21passt, the PaSST
  wrapper whose weights sit inside the checkpoint, is **Apache-2.0**
  according to its package metadata.

**Licence: the weights are non-commercial and share-alike.**

- **Research only.** Shipping them would need an opt-in dependency group
  and a module boundary, as CLAUDE.md prescribes for MuScriptor.
- **Share-alike.** Anything derived from the weights would carry the same
  licence.
- **Training data.** MoisesDB's own terms were not checked at the source.

## The trial

- **The set.** 16 spans, all dev split, named before anything was scored:
  - **10 routing-trouble solos.** D23's seven (Ornithology 61, Crazy Rhythm
    399, Cherokee 446 and Cherokee II 447, Dolores 427, Orbits 434, My
    Favorite Things 228), R16's Oleo 320, and the two that
    docs/separation-research.md adds (Blues In The Closet 397, Limehouse
    Blues 375).
  - **6 ordinary solos.** The first six of that doc's fixed separator subset:
    54, 70, 56, 58, 168 and 218.
- **Each span.** The sidecar's located span, plus the separate stage's 3 s
  margin, cut from the same ingest wav the Roformer set was made from.
- **The query ("self").** The 6 s of the span where the Roformer `other` stem
  has the highest MEDIAN 50 ms frame level. It reads our own audio, never the
  annotation, and it is what the product could do from a separation already
  on disk.
  - A check made afterwards, for diagnosis only, found WJazzD has the soloist
    sounding for 63-94% of every query window, with 14-48 annotated notes in
    each.
- **The transcriber.** The stem is padded back to the track's time base
  exactly as a span-scoped Roformer set is written. It is transcribed with
  the harness's own CREPE path (`transcribe.analyze` under
  `run_eval.transcribe_settings`, CPU, 4 threads).
  - The code is a `git archive` of commit 0049aee on PYTHONPATH, because the
    working tree's transcriber was mid-change. Its fingerprints match all 74
    WJazzD runs of a pre-hybrid snapshot of the harness notes cache.
- **The Roformer side.** It is that snapshot's run. As a control it
  reproduces all 16 pinned note F1s with a worst difference of 0.0000.
- **The fit.** Both sides are scored under the Roformer run's own
  `identify_all` fit (`frontend_bakeoff`'s rule), so the same solo, offset
  and rate are scored on both.
- **The statistics.** `evaluation.paired_change`, resampled by recording,
  tolerance 0.002.

### Per span

Note F1 with precision and recall in brackets. The levels are the stem's RMS
over the span, in dBFS. Dropout is R16's measure: the share of 1 s bins that
are digitally silent, measured on the 16-bit stem as the separate stage
writes it.

| melid | solo | Roformer `other` | Banquet (self) | dropout R / B | level R / B (mix) |
|---|---|---|---|---|---|
| 61 | Ornithology | 0.881 (0.88/0.88) | 0.667 (0.73/0.61) | 0.00 / 0.00 | -19.7 / -65.4 (-16.9) |
| 399 | Crazy Rhythm | 0.870 (0.85/0.89) | 0.296 (0.52/0.21) | 0.00 / 0.22 | -23.1 / -43.2 (-18.3) |
| 320 | Oleo | 0.862 (0.86/0.87) | 0.687 (0.66/0.71) | 0.00 / 0.16 | -25.0 / -65.2 (-21.7) |
| 446 | Cherokee | 0.825 (0.87/0.79) | 0.464 (0.59/0.38) | 0.00 / 0.01 | -20.1 / -56.6 (-17.0) |
| 447 | Cherokee II | 0.764 (0.83/0.71) | 0.505 (0.63/0.42) | 0.00 / 0.59 | -22.2 / -77.9 (-18.2) |
| 427 | Dolores | 0.906 (0.93/0.89) | 0.719 (0.76/0.68) | 0.00 / 0.00 | -24.1 / -23.9 (-19.7) |
| 434 | Orbits | 0.878 (0.88/0.87) | 0.336 (0.42/0.28) | 0.00 / 0.05 | -22.9 / -40.6 (-19.0) |
| 228 | My Favorite Things | 0.758 (0.81/0.71) | 0.221 (0.34/0.16) | 0.00 / 0.00 | -25.6 / -40.3 (-18.1) |
| 397 | Blues In The Closet | 0.837 (0.80/0.87) | 0.678 (0.68/0.68) | 0.00 / 0.72 | -22.0 / -73.8 (-18.3) |
| 375 | Limehouse Blues | 0.863 (0.85/0.87) | 0.848 (0.82/0.88) | 0.00 / 0.00 | -17.8 / -32.7 (-16.8) |
| 54 | Don't Blame Me | 0.887 (0.91/0.87) | 0.744 (0.72/0.78) | 0.00 / 1.00 | -21.3 / -95.9 (-20.0) |
| 70 | I Fall In Love Too Easily | 0.966 (0.94/0.99) | 0.613 (0.58/0.65) | 0.00 / 0.00 | -23.9 / -36.9 (-22.0) |
| 56 | Embraceable You | 0.864 (0.85/0.88) | 0.608 (0.61/0.61) | 0.00 / 1.00 | -16.3 / -99.3 (-13.8) |
| 58 | KC Blues | 0.876 (0.87/0.88) | 0.621 (0.65/0.60) | 0.00 / 0.38 | -20.2 / -62.9 (-18.6) |
| 168 | Maiden Voyage | 0.748 (0.81/0.69) | 0.551 (0.67/0.47) | 0.02 / 0.11 | -19.6 / -40.3 (-16.1) |
| 218 | Blue Train | 0.855 (0.90/0.82) | 0.442 (0.53/0.38) | 0.00 / 0.00 | -20.8 / -44.7 (-19.0) |

| set | n | Roformer | Banquet | change (95% interval) | up / down |
|---|---|---|---|---|---|
| routing trouble | 10 | 0.844 | 0.542 | -0.302 (-0.417, -0.192) | 0 / 10 |
| ordinary | 6 | 0.866 | 0.597 | -0.270 (-0.341, -0.199) | 0 / 6 |
| **all, note F1** | 16 | 0.853 | 0.562 | **-0.290 (-0.366, -0.216)** | 0 / 16 |
| all, precision | 16 | 0.865 | 0.619 | -0.246 (-0.306, -0.190) | 0 / 16 |
| all, recall | 16 | 0.842 | 0.531 | -0.311 (-0.400, -0.226) | 1 / 15 |

**What the level column says.** Banquet estimates a mask over the mixture.
When it does not recognise the query, the mask closes and the stem comes back
nearly silent. Its stem sits a median **30 dB under the Roformer's** (from 83
dB under to 0.2 dB over), and 15 of the 16 are more than 10 dB under.

- **The worst cases.** On Don't Blame Me and Embraceable You the stem is 75-83
  dB down: at the 16-bit floor, and "digitally silent" by R16's test.
- **Why those still score 0.6-0.74.** CREPE is level-invariant, and the
  transcribe gates are relative to the stem's own loudest frames, so what
  survives the quantisation still reads as notes. A product would not get
  that far: R16's check, the one `choose_stem` makes, calls those stems
  empty.
- **Only Dolores comes back at the Roformer's level** (0.2 dB apart), and it
  still reads 0.719 against 0.906.
- **The shape disagrees too.** Measured against the Roformer `other` over the
  same span, Banquet's stem has a median SI-SDR of -5.9 dB (range -12.5 to
  +3.4, n = 16). The Roformer is a pseudo-reference, so this says "a
  different signal", not "a worse separation". The F1 column says worse.

### The objections, measured

- **"The plumbing is broken."** The same model, the same runner and the same
  kind of query, asked for sources MoisesDB certainly has. Each query was cut
  the self query's way, from the Roformer's own drums or bass stem of the same
  span:

  | span | asked for | Banquet dB | Roformer dB | SI-SDR vs Roformer |
  |---|---|---|---|---|
  | 70 I Fall In Love Too Easily | bass | -28.7 | -27.7 | **+9.8** |
  | 54 Don't Blame Me | bass | -34.1 | -31.7 | -0.4 |
  | 61 Ornithology | bass | -53.4 | -31.7 | -17.2 |
  | 61 Ornithology | drums | -95.1 | -27.6 | -8.5 |
  | 375 Limehouse Blues | drums | -94.9 | -36.5 | -21.6 |

  Where it recognises the query, it returns that source at the right level
  and in the right shape (Chet Baker's bass). So the chunking, the fold, the
  conditioning and the output scale all work. On these recordings it often
  does not recognise the query, whatever the instrument: the drums of
  Ornithology and Limehouse Blues come back about 60 dB under.
- **"You tiled a 6 s query; it was trained on 10 s."** The loudest 10 s
  window was used, untiled, on the five worst spans (54, 56, 58, 61, 168).
  Note F1 went **0.638 to 0.531**: -0.107 (-0.151, -0.035), 4 of 5 down.
  Recall fell -0.154.
- **"An instrument library would do: the app supplies a tenor clip when the
  listener says tenor."** The `cross` query is the self clip of ANOTHER trial
  recording of the same WJazzD instrument: a different player where one
  exists, else the same player on another tune. On 4 spans (54, 61, 70, 375)
  it scored 0.629 against self's 0.718: -0.089 (-0.152, -0.026), 0 of 4 up.
  The Roformer reads 0.899 on the same four.

### Negative results, on the record

- Banquet `ev-pre-aug` with a self query, over 16 WJazzD horn spans: note F1
  **-0.290 (-0.366, -0.216)** against BS-Roformer-SW `other`; 0 of 16 up.
- The same on the 10 routing-trouble solos: **-0.302 (-0.417, -0.192)**,
  0 of 10 up.
- A 10 s untiled query against the 6 s tiled one: **-0.107 (-0.151, -0.035)**,
  n = 5.
- A same-instrument query from another recording against the self query:
  **-0.089 (-0.152, -0.026)**, n = 4.
- R16's dropout of at least 0.10 on 8 of 16 Banquet stems, against 0 of 16
  on the Roformer (whose maximum is 0.02).
- Drums queries returned near-silence (-95 dBFS) on both spans tried.

## Reproduce

The commands, with this machine's traps (CLAUDE.md) worked in. DIR is a
scratch directory outside the repo; the run used the session scratchpad.

    # Windows: the trial set, the crops and the queries (uses a SNAPSHOT of the
    # harness notes cache, never the live one)
    .venv\Scripts\python.exe scripts/banquet_trial.py manifest --db wjazz/wjazzd.db ^
        --out DIR --notes SNAPSHOT\.benchmark-notes-c0.2-d0.0.json
    # optional: the sanity probes and the 10 s query
    .venv\Scripts\python.exe scripts/banquet_trial.py probes --out DIR --ids m61,m375,m54,m70
    .venv\Scripts\python.exe scripts/banquet_trial.py probes --out DIR ^
        --ids m54,m56,m58,m61,m168 --stems other --seconds 10 --name self10

    # WSL: one run per condition (resumable; restart it if CUDA dies)
    cd ~/banquet && PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      .venv/bin/python /mnt/c/.../scripts/banquet_wsl.py infer \
        --manifest DIR/manifest-wsl.json --out DIR/banquet \
        --repo /mnt/c/Users/lkmcg/swingscribe-research/banquet/query-bandit \
        --ckpt /mnt/c/Users/lkmcg/swingscribe-research/banquet/weights/ev-pre-aug.ckpt \
        --condition self --batch 3 --gpu-fraction 0.4

    # Windows: transcribe and score. While the working tree's transcriber is
    # mid-change, put a `git archive` of a commit's src/ on PYTHONPATH.
    .venv\Scripts\python.exe scripts/banquet_trial.py score --db wjazz/wjazzd.db --out DIR ^
        --notes SNAPSHOT\.benchmark-notes-c0.2-d0.0.json ^
        --pins tests/regression/real-audio-baselines.json ^
        --device cpu --jobs 2 --conditions self,cross,self10
    .venv\Scripts\python.exe scripts/banquet_trial.py probes --out DIR --ids ... --report

`score` writes `card.json`: every per-span number above, the paired changes,
the levels and dropouts, and which `swingscribe` it imported. `probes
--report` writes `probes.json`. Both stay in the scratch folder, together with
every wav and note list: they are derived from commercial recordings.
