# The landscape: models, data, methods and products

*Surveyed 2026-09-30. Every claim below links to its source. A verification pass rechecked the claims against primary sources, and its corrections are applied here. Anything that could not be confirmed is marked **unverifiable**. Numbers from other papers are measured on their own test sets and tolerances. None of them is directly comparable to our WJazzD note F1 of 0.858.*

## 1. Bottom line

No published system or product does the whole of what SwingScribe does. That means finding a jazz soloist inside a full band, writing a swing-aware page that has been measured against human pages, and doing it locally and for free. The gap closed partly this week. AnthemScore 6.3.0, released 2026-09-29, now claims swing detection written as plain eighths under a swing marking ([version history](https://lunaverus.com/versionHistory)).

**Accuracy.** The literature agrees with our own bake-off. Short notes are a front-end limit that a note-level model can move. The quantizer's remaining headroom is in acoustic evidence, not in richer symbolic priors. Nothing surveyed addresses the semitone-neighbour errors.

**What limits every training idea is licensing, not method.** No dataset combines all three of:
- real jazz horn solos,
- human labels,
- a licence that clearly lets trained weights ship.

**The cheapest high-value moves:**
- Bake off two Kong-family checkpoints through the runtime we already ship. One is a jazz-sax model, the other a piano model built for robustness.
- Measure ourselves against AnthemScore 6.3 and Klangio before claiming swing as ours alone.
- Put chord symbols on the page, starting from changes the listener supplies.
- Adopt the Jazz Structure Dataset and the Aligned Omnibook as ground truth for what our benchmarks cannot see.
- Give the beat grid a confidence and a fix that takes one click.

**The longer research bet** is a per-beat rhythm-figure classifier driven by audio. It would sit inside the quantizer's existing grid choice, and it is where the best published jazz audio-to-score result comes from ([Shanin, Riley & Dixon, ICASSP 2026](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2026/ShaninEtAl-ICASSP2026.pdf)).

## 2. Models worth a bake-off on our stems

**The bar** is the Basic Pitch hybrid from `docs/frontend-bakeoff.md`:
- WJazzD note F1 0.8650 on the dev split, which is +0.0070 over CREPE, or +0.0067 held out.
- Omnibook sub-eighth recall 0.7034, which is +0.0436.

A2's kill criterion applies to every entry below. The in-house bake-off already showed two things:
- A perfect choice between CREPE and a note model would lift WJazzD recall from 0.836 to 0.908, and on notes under 60 ms from 0.489 to 0.678.
- Basic Pitch had the right pitch on only 3-15% of CREPE's semitone-neighbour errors.

**A loader change comes before the top two candidates.** Both are note-only Kong CRNN checkpoints, and `src/swingscribe/piano.py` cannot load them as it stands:
- It constructs `PianoTranscription(device, checkpoint_path)` with the default `model_type='Note_pedal'`. That class indexes `note_model` and `pedal_model` keys, which a note-only checkpoint does not have.
- `MIN_CHECKPOINT_BYTES` is 160 MB, and both files are about 100 MB.
- **The trap:** upstream `piano_transcription_inference/inference.py` (line 31) runs `wget` to download the Zenodo piano weights over any checkpoint smaller than 1.6e8 bytes.

A second loader must therefore pass `model_type='Regress_onset_offset_frame_velocity_CRNN'` and must never reach upstream's size check. The runtime is reusable; the current code path is not. Sources: [hf_midi_transcription model.py](https://raw.githubusercontent.com/xavriley/hf_midi_transcription/main/hf_midi_transcription/model.py), [Edwards checkpoint notes on Zenodo](https://zenodo.org/records/10610212).

### Ranked

| # | Candidate | Targets | Licence | Cost to test |
|---|---|---|---|---|
| 1 | Riley & Dixon FiloSax sax CRNN (`filosax_25k.pth`) | horn short notes, recall | MIT tag on weights trained on non-commercial data; **unclear** | new loader, no new dependency |
| 2 | Edwards et al. robust Kong piano checkpoint | pianist oracle on old recordings (A4) | CC BY 4.0 | same loader |
| 3 | CREPE `tiny` | CPU speed | already ours | one config flag, one CREPE re-run |
| 4 | Transkun V2 / hFT-Transformer | piano fallback | MIT | new dependency; ncls must pass Smart App Control |
| 5 | PESTO, self-trained on our stems | horn-adapted f0 (research) | LGPL-3.0 | new dependency and a training run |
| 6 | SwiftF0 | CPU speed | MIT | new dependency (onnxruntime is already in `omr`) |
| 7 | MuScriptor | settle the M10 opt-in | weights CC BY-NC 4.0 | gated download |

**1. FiloSax-trained saxophone CRNN** ([Riley & Dixon, SMC 2024](https://arxiv.org/html/2405.16687); weights at [xavriley/midi-transcription-models](https://huggingface.co/xavriley/midi-transcription-models/tree/main))

What it is:
- Kong's high-resolution CRNN retrained on FiloSax tenor sax.
- 80/10/10 split by piece, ±5-semitone pitch shifts, 27.5k steps.
- It is the only published note-level model trained on real jazz saxophone.

Evidence (onset-only, 50 ms, on the paper's own Demucs stems):
- FiloSax test split: P/R/F 96.47/95.90/96.19.
- 50 Omnibook solos: P 74.70, R 76.96, F 75.43.
- CREPE Notes on the same set: P 70.93, R 70.63, F 70.41.
- Başaran et al.: F 73.68 with R 77.98, so Başaran has *higher* recall than the CRNN. The CRNN's recall edge is over CREPE Notes only.
- The paper does not break results down by note length. That the gain lands on short notes is our hypothesis, not a published result.

Limits and caveats:
- The authors say it struggles in the alto's altissimo.
- It never saw trumpet or trombone. WJazzD has 102 trumpet and 26 trombone solos.
- The Omnibook reference is score MIDI aligned by DTW and then refined against a model's activations, so it is not hand-tapped.

Licence:
- The Hugging Face card says MIT and says nothing about FiloSax.
- FiloSax itself is non-commercial research only, with no redistribution without written permission ([Zenodo 6335779](https://zenodo.org/records/6335779)).
- The wrapper `hf_midi_transcription` declares MIT in pyproject and README, but has no LICENSE file. It also pulls librosa, so load the weights through our own loader instead.
- The file is named 25k while the paper says 27.5k steps. Whether this is the evaluated checkpoint is **unverifiable**.
- Until the authors confirm terms, keep it behind an opt-in group, as with MuScriptor.

How to test:
- Run it through `scripts/frontend_bakeoff.py` three ways: as the line, as a gap-filler, and as a selector.
- **Save its onset/offset/frame activations.** They are exactly the input the §4 figure classifier needs.

**2. Edwards et al. robust Kong piano checkpoint** ([arXiv 2402.01424](https://arxiv.org/abs/2402.01424), [Zenodo 10610212](https://zenodo.org/records/10610212))

What it is:
- The same CRNN retrained on MAESTRO plus Disklavier re-recordings with augmentation.
- No pedal head.
- `high_resolution_MAESTRO_augmentations.pth`, 103.8 MB, CC BY 4.0.

Evidence:
- Zero-shot MAPS note-onset F1 88.4, against 83.10 for Kong's original in the [Aria-MIDI table](https://arxiv.org/pdf/2504.15071).
- The [Jazz Trio Database](https://transactions.ismir.net/articles/10.5334/tismir.186) measured Kong's original at 0.77 ± 0.13 on separated jazz-trio piano. **That figure is onset detection only, with no pitch scored**, so it is not a note F1.

How to test:
- Measure on the seven hand-scored pianists and the four WJazzD pianists.
- Include `fill_gaps`, `pick_line` and corroboration downstream.
- Use the dev split only.

This is the cheapest pianist experiment on the list. Line selection is still the pianists' leading error, and no checkpoint fixes that.

**3. CREPE `tiny`.** [CREPE Notes](https://arxiv.org/pdf/2311.08884) found the tiny and full models level on FiloSax note F (82.31 both).
- Our config already has `crepe_model: tiny`, commented as about 10x faster on CPU and "less accurate". That is our own claim and has not been measured.
- The cached reviews hold full-model f0, so testing it means one CREPE pass. That is minutes on the GPU.
- It matters for users without a GPU.

**4. Transkun V2 and hFT-Transformer** are the clean piano fallbacks if checkpoint 2 is not enough.
- [Transkun](https://github.com/Yujia-Yan/Transkun): MIT code and weights; MAESTRO v3 onset+offset+velocity F1 0.9314; no librosa. Its compiled `ncls` dependency must pass the Smart App Control load test.
- [hFT-Transformer](https://github.com/sony/hFT-Transformer): MIT; MAESTRO v3 note F1 97.43, 90.32 with offset.

**5. PESTO** ([repo](https://github.com/SonyCSLParis/pesto), [TISMIR v2](https://arxiv.org/abs/2508.01488)).
- Self-supervised, so it can be trained on our own unlabelled Roformer horn stems. It would learn horn timbre and the separation's bleed.
- LGPL-3.0; about 130k parameters.
- The shipped checkpoint is trained on MIR-1K vocals and reads 0.680 on the [SwiftF0 author's benchmark](https://github.com/lars76/pitch-benchmark), below torchcrepe's 0.691.
- PyPI 2.0.1 also requires scipy, omegaconf and tqdm.
- Worth one research run to see whether horn-adapted f0 moves the neighbour class.

**6. SwiftF0** ([repo](https://github.com/lars76/swift-f0)). This is a speed lever, not an accuracy one.
- MIT; numpy plus onnxruntime only.
- The 14k-parameter network is from v0.2.0, uploaded 2026-09-19.
- Its 16 ms hop is coarser than CREPE's 10 ms.
- The benchmark that ranks it first (0.781 F1@50c at 179.6x real time) is its own author's. Whether that benchmark is dominated by speech and singing is **unverifiable**, because the README does not name its ten corpora.

**7. MuScriptor** ([repo](https://github.com/muscriptor/muscriptor), [paper](https://arxiv.org/html/2607.08168v2)).
- MIT code, CC BY-NC 4.0 weights, gated.
- There are no wind or jazz results in the paper.
- The Harmonica paper measured the 306M model at onset-pitch 0.711 on URMP stems, against YourMT3+'s 0.926 ([arXiv 2609.04640](https://arxiv.org/html/2609.04640)).
- A bake-off through the same harness would settle whether it earns its M10 slot.

### The fine-tune base (A2 step 2): Kong's CRNN rather than Basic Pitch

Published evidence that this architecture absorbs imperfectly aligned, score-derived labels ([Riley, Edwards & Dixon, ICASSP 2024](https://arxiv.org/html/2402.15258)):
- 79 professionally transcribed jazz-guitar scores, about 4 h of audio.
- Aligned by DTW against the model's own activations, then each onset snapped to its local activation peak.
- Zero-shot GuitarSet onset F1 87.3, against NoteEM's best of 82.9.
- They chose Kong over Onsets and Frames for robustness: trained with 50 ms label misalignment, Kong holds 96.49% onset F1 against 76.52%.

Why it fits us:
- The piano weights are CC BY 4.0 ([Zenodo 4034264](https://zenodo.org/record/4034264)) and the inference code is MIT.
- The recipe maps directly onto `locate_scores` plus the PDF corpus.

Basic Pitch remains the lighter option: a 230 KB ONNX graph, with TensorFlow training in WSL. Its frames are 11.6 ms, while Kong regresses onset times at 100 frames/s.

Unknown:
- Whether Riley's batch of 8 × 10 s segments fits the RTX 3050's 6 GB.
- The status of weights trained on WJazzD labels over commercial audio (see §3).

Label-making methods for turning pages into training data:
- [Snapping Matters](https://arxiv.org/abs/2606.11903) (ICMC 2026) replaces greedy snapping with bipartite matching.
- [CountEM](https://yoni-yaffe.github.io/count-the-notes) supervises with note-count histograms. Its code licence and venue are **unverifiable**.
- A [cycle-consistent approach](https://arxiv.org/abs/2605.24193) needs only a small paired anchor.
- **Avoid NoteEM's code.** It is CC BY-NC-SA 4.0 and covered by a US patent application ([repo](https://github.com/benadar293/benadar293.github.io)).

### Watch list
- **Harmonica** (BandLab, [arXiv 2609.04640](https://arxiv.org/abs/2609.04640), submitted to ICASSP 2027). A Basic Pitch-class model.
  - URMP-stem onset-pitch/frame: nano (26.3K parameters) .796/.833, medium .924/.930, against Basic Pitch .687/.894.
  - The pairs sometimes quoted, 0.831/0.880 and so on, are its MAESTRO column, not a development set.
  - No code or weights; the project page did not resolve.
- **Mel-RoFormer** ([arXiv 2409.04702](https://arxiv.org/pdf/2409.04702)). A transcription head on a separation backbone, MIR-ST500 COnP 0.798. It is the long-term shape of "learn the bleed by construction". No weights released.
- **TUTTI** ([arXiv 2609.00640](https://arxiv.org/html/2609.00640)). End-to-end audio to ABC. After fine-tuning on a small real-sax set (exercises and scales, not jazz) it reads MV2H 85.3 tenor and 84.9 alto, against 60.3 and 59.9. No weights. The ISMIR 2026 venue is **unverifiable**.

### Not worth a bake-off
- **aria-amt** ([repo](https://github.com/EleutherAI/aria-amt)): its weights sit in a CC BY-NC-SA 4.0 dataset repo, which is effectively their licence, and it is GPU-oriented. This is despite MAPS 90.58.
- **YourMT3+**: GPL-3.0 code would bind the app's licence.
- **MT3**: 42.97 on FiloSax; JAX stack.
- **Onsets and Frames and Omnizart**: TensorFlow plus librosa and madmom, both superseded.
- **RMVPE, FCPE, PENN**: vocal- or speech-trained, and f0 is not where our loss is.
- **Singing-voice note models** (ROSVOT, SOME, GAME, VOCANO). For the record, VOCANO's Molina Fno is 64.2 per [Basic Pitch Table 3](https://arxiv.org/pdf/2203.09893), not 76.5. Basic Pitch's own Molina Fno is 52.3.

## 3. Datasets: what we could train or evaluate on

**For shipping weights:** if a model will ship, only its training data's licence matters. If data is used only for evaluation, a non-commercial licence is fine, but it still stays out of git (plan §12).

### Evaluate
- **Charlie Parker Aligned Digital Omnibook** ([Zenodo 14628467](https://zenodo.org/records/14628467), 1.4 GB).
  - What it has: all 50 Omnibook solos with performance-aligned MIDI, **manually placed downbeats**, hand-corrected tuning, Demucs sax stems and MusicXML.
  - What it gives us: mir_eval note scoring for the Omnibook, extended from our 22 sides to 50, plus a downbeat ground truth at bebop tempos.
  - Four licences are in play:
    - Zenodo: CC BY 4.0.
    - [Companion site](https://aim-qmul.github.io/SaxTranscriptionPipeline/): non-commercial research only, no redistribution.
    - The arXiv paper: CC BY-NC-ND.
    - A [Hugging Face copy](https://huggingface.co/datasets/xavriley/CharlieParkerAlignedOmnibook): tagged MIT, and it includes syncpoints.
  - The stems come from commercial recordings, and the scores come from LORIA's CC BY-NC-SA 2.0 UK files. Treat it as internal.
  - The MIDI is model-refined, not tapped by hand.
- **Jazz Structure Dataset (JSD)** ([TISMIR 2022](https://transactions.ismir.net/articles/10.5334/tismir.131), [repo](https://github.com/stefan-balke/jsd)).
  - The same 340 recordings as WJazzD, with one CSV row per chorus. Soloist and band are tagged (`s_ts`, `b_p`...). File names join to WJazzD.
  - It labels 1,074 solos, where WJazzD transcribes 456. That makes it the ground truth for O2 and O3: a proposer that finds an untranscribed solo is not charged a false positive.
  - The article is CC BY 4.0; the repo has no licence file, so the annotations' own licence is **unverifiable**.
- **JazzSAMBA** ([Zenodo 22943963](https://zenodo.org/records/22943963), [arXiv 2609.34931](https://arxiv.org/abs/2609.34931), released 2026-09-27).
  - 76 standards played by 8 musicians, with per-player stems, mixes, bars, chords, sections and a soloist sequence. 21.8 GB.
  - **Drums and piano have ground-truth MIDI.** Bass, trumpet and sax MIDI are MuScriptor output.
  - That makes it the first non-circular test of our pianist path: PiJAMA and JTD MIDI are Kong's own output. It also has real isolated horns for separation tests.
  - Licence: permissive (keep the notice); the repo is MIT.
  - Unknown: how the piano MIDI was captured, and whether MuScriptor's NC terms reach the derived horn MIDI.
- **Filosax** ([ISMIR 2021](https://archives.ismir.net/ismir2021/paper/000025.pdf); data on request via [Zenodo 6335779](https://zenodo.org/records/6335779), 450.8 GB, or Lite [5643734](https://zenodo.org/records/5643734)).
  - About 24 h: 5 tenor players × 48 Aebersold standards.
  - Two note layers:
    - A performance layer, from Logic Flex Pitch with about 9% of notes hand-corrected.
    - A **human-edited score layer aligned note by note** to the performance.
  - The "transcribed solo" sections are exact score-to-performance pairs. This is the quantizer's missing instrument (roadmap A1) at scale.
  - The score layer was first quantized algorithmically to eighths, then edited for readability, so audit it the way we audited Flex-Q.
  - Restricted: non-commercial research, non-transferable. Nothing derived from it ships without written permission.
  - mirdata has four versions (`full`, `full_sax`, `lite`, `lite_sax`).
- **JAAH** ([Zenodo 1290737](https://zenodo.org/records/1290737), CC BY-NC-SA 4.0).
  - 113 tracks, 1917-1989, with hand-corrected beats including rubato, per-beat chords, and part labels naming each soloist.
  - A beat test set for older, drum-light jazz, and a chord test set. See §5 for a training-leakage issue.
- **Jazz Trio Database** ([TISMIR 2024](https://transactions.ismir.net/articles/10.5334/tismir.186)).
  - 34 hand-annotated trio tracks (72 min): beat F 0.97, downbeat F 0.63.
  - The repo declares the dataset MIT; audio is restricted.
- **ChoraleBricks** ([TISMIR 2025](https://transactions.ismir.net/articles/10.5334/tismir.252), CC BY 4.0).
  - Real isolated winds with corrected f0 and notes. The saxophones are **alto and baritone**, not tenor; trumpet and trombone are included.
  - Useful for timbre coverage; it contains no jazz articulation.
- **Weimar Jazz Database** (already ours). Two things we do not use yet:
  - Per-note f0 deviation fields (`f0_med_dev`, `f0_mod`), an intonation reference for the neighbour class.
  - Per-beat chords ([format](https://jazzomat.hfm-weimar.de/dbformat/dbcontent.html)), a chord ground truth for §7's chord-symbol work.
  - Instrument counts: ts 157, tp 102, as 80, tb 26, ss 23, cor 15, cl 15, vib 12, bs 11, p 6, g 6, bcl 2, ts-c 1, which make 456.

### Train weights that could ship
- **CC BY 4.0, clean:**
  - [CocoChorales](https://magenta.tensorflow.org/datasets/cocochorales): synthetic, with exact labels. Saxophone appears only in its random ensembles.
  - ChoraleBricks.
  - [Slakh2100](https://zenodo.org/records/4599666).
  - [GuitarSet](https://zenodo.org/records/3371780).
  - [FiloBass](https://zenodo.org/records/10069709): Zenodo says CC BY 4.0, but its [project site](https://aim-qmul.github.io/FiloBass/) states Filosax-style non-commercial terms. **Conflict.** It has 12 bassists, not 11.
- **WJazzD annotations** are ODbL 1.0 with DbCL contents. On one reading, a trained model is a "Produced Work": it needs a notice and is not share-alike ([ODbL §4.3, §4.5b](https://opendatacommons.org/licenses/odbl/1-0/)). That is a reading, not legal advice. Training on the commercial recordings themselves is a separate and unresolved question.
- **Precedent, not a ruling.** Authors have released weights trained on non-commercial data under permissive licences:
  - Kong's MAESTRO **v2.0.0** (CC BY-NC-SA) model as CC BY 4.0.
  - Riley's FiloSax model tagged MIT.
- **Non-commercial, so internal only:** MAESTRO, MedleyDB, PiJAMA (CC BY-NC), Aria-MIDI (CC BY-NC-SA), the RWC Jazz 2026 re-release ([CC BY-NC 4.0](https://zenodo.org/records/18656623)), the LORIA Omnibook (CC BY-NC-SA 2.0 UK), Filosax, and NoteEM's MusicNetEM (CC BY-NC-SA 4.0).
- **A licence check we owe ourselves:** confirm which pages the shipped `figure-prior.json` was counted from, and whether any of them are non-commercial sources.

### Low value or unverifiable
- **URMP**: 13 instrument types; no licence stated.
- **Bach10**.
- **DTL1000**: 1,060 tracks, all hand-segmented; licence unknown; rights held by Dixon ([ReShare](https://reshare.ukdataservice.ac.uk/854781/)).
- **Martínez-Sevilla sax corpus**: its size of 1,026 clips is **unverifiable**.
- **The handwritten jazz lead-sheet OMR set** ([arXiv 2509.05329](https://arxiv.org/abs/2509.05329)): relevant to pdf2musicxml's scans, but its data licence is **unverifiable**.

## 4. Quantization and audio-to-score

### The one paper that matters: the Rhythm Perceiver
[Shanin, Riley & Dixon, "Audio-to-Score Jazz Solo Transcription with the Rhythm Perceiver", ICASSP 2026](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2026/ShaninEtAl-ICASSP2026.pdf) won Best Student Paper ([Dixon's page](https://webspace.eecs.qmul.ac.uk/s.e.dixon/)).

How it works:
- Its unit is our figure prior's unit: a per-beat "beat signature" on 12 bins per beat. There are 42 classes counted from Filosax pages, plus "rare" and "unsupported".
- It **predicts the figure from acoustic evidence**: CRNN onset/offset/frame activations and phase-within-beat features, combined through Perceiver cross-attention.
- It then reads a pitch at each predicted onset, so the page is valid by construction.

Results:
- Filosax test: rhythm accuracy 0.87, onset F1 0.93.
- Omnibook: rhythm accuracy 0.53, onset F1 0.83, MV2H 0.92. The CRNN+qparse baseline reads 0.18 and 0.48.
- Those Omnibook figures cover only the "easy" 60% of tracks, where automatic beats held.
- The insertion and deletion rates (20.42% and 53.36%) are on the full reproduced set, the 31 scores qparse could parse.

Limits:
- 4/4 only; no 32nds.
- No code or weights were found (the search was not exhaustive).
- The model itself was trained on Filosax. Its CRNN front end was trained on Filosax plus 396 separated WJazzD wind solos, so it carries both licences.

### How it could beat our rule-based quantizer
This is our proposal; no paper has tested it.
- Use a small per-beat figure classifier as the **likelihood term inside `choose_grid`**. Keep:
  - the counted figure prior as the class prior;
  - the slack, lag and sparse-beat gates;
  - the guards that keep every heard note.
- Start as a **re-ranker** over the candidates `choose_grid` already enumerates.
- Later, decode across beats with Viterbi, in the metrical-HMM tradition:
  - [Nakamura et al. 2017](https://arxiv.org/abs/1701.08343) found fully learned parameters beat hand-set ones across seven methods.
  - [Nishikimi et al. 2021](https://www.cambridge.org/core/journals/apsipa-transactions-on-signal-and-information-processing/article/audiotoscore-singing-transcription-based-on-a-crnnhsmm-hybrid-model/0AE8AEECB24DC3D9B689459E11DDA03F) is a CRNN-HSMM; its language model cut error only from 21.70% to 20.08%.

Why the gain must come from the acoustic side: our own figure-prior count found under 0.03 bit in extra symbolic conditioning. A classifier that sees activations rather than CREPE's already-discretized onsets can also say *how many* notes a beat holds, and that aims at the sub-eighth misses.

Constraints:
- **Training data is the constraint.** Candidates are our 12 hand scores, the ~245 OMR pages once located (`locate_scores`), the Omnibook under the E2 split, and Filosax internally.
- Synthetic renderings of human pages with swing and lag are another route. TUTTI's sax result suggests that synthetic-to-real transfer works.
- Judge it on the listener's pages and the Omnibook, never on Flex-Q (D36).
- The first prerequisite is recommendation 2's activations.

### Read closely: Klangio's quantizer
[Wachter, Murgul & Heizmann](https://arxiv.org/html/2604.22290) (ICSM 2025, CC BY 4.0).
- The authors are at Klangio.
- A T5 model quantizes MIDI *given* beats, snapping to 12 sub-beats per beat. That is our setup.
- On ASAP piano: onset F1 97.3%, note-value accuracy 83.3%.
- **It is also trained and evaluated on Leduc's 239 jazz-guitar transcriptions**, aligned with Riley's method. That makes it the one symbolic quantizer measured on aligned jazz pages, and a competitor's.
- No explicit swing handling. No code.
- Whether the test beats were ground truth is **unverifiable**.

### Not recommended
- **Symbolic MIDI-to-score transformers**: [MIDI2ScoreTransformer](https://arxiv.org/abs/2410.00210) has no licence and ASAP (NC-SA) training data; [PM2S](https://github.com/cheriell/PM2S). Both are classical piano with fixed 4/4.
- **End-to-end audio-to-score** (TUTTI, SheetSage-A2S, piano-a2s): no jazz, NC-ND licences.
- **qparse** (CeCILL 2.1): a new unsigned native binary that Smart App Control would refuse, and it failed on 19 of 50 Omnibook scores ([Riley & Dixon 2024](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2024/RileyDixon-SMC2024.pdf)). Its implementation language is **unverifiable**.
- The [FlexQ](https://www.researchgate.net/publication/322277286_The_FlexQ_Algorithm) critique in the Rhythm Perceiver paper independently confirms D36.

### What the swing literature says about our rules
- [Corcoran & Frieler 2021](https://online.ucpress.edu/mp/article-abstract/38/4/372/116701/Playing-It-StraightAnalyzing-Jazz-Soloists-Swing): over the 456 WJazzD solos, soloists average BUR about 1.3:1, and a stable 2:1 is a myth. That is consistent with M4's 1.56 noise floor and with warping rarely.
- [Nelias et al. 2022](https://www.nature.com/articles/s42005-022-00995-z): a *majority* of soloists (not "almost all") delay downbeats by about 30 ms at about 150 bpm, while offbeats stay synchronized. Listeners judged that version swinging with odds ratio 7.48.
  - The authors say this is **not** the laid-back style, whose delays move offbeats too. So the paper does not directly support R29.
  - My reading: R29's floor of 0.08 beats sits just above their ~0.075 beats. R29 therefore mostly fires on the larger, laid-back lags, where shifting the whole beat is the right model.
- [Dittmar, Pfleiderer & Müller 2015](https://www.ismir2015.uma.es/articles/143_Paper.pdf): the ride cymbal's swing ratio from log-lag autocorrelation tracks annotation at r ≈ 0.9 (onset-based: 0.66). This is a soloist-independent swing reading for sparse beats and ballads, in pure numpy.
- Swing ratio varies with tempo and within phrases:
  - [Butterfield 2011](https://academic.oup.com/mts/article-abstract/33/1/3/1134435).
  - Friberg & Sundström 2002, confirmed only through secondary citations.
  - Benadon 2006, **unverifiable**.

  Together these cap any fixed per-track warp and argue for the per-beat classifier.
- Also **unverifiable**: [Cemgil et al. 2000](https://direct.mit.edu/comj/article-abstract/24/2/60/93434/Rhythm-Quantization-for-Transcription), and Marchand & Peeters 2015's 91% swing recall.

### The metric to adopt
- **Add MV2H** ([MIT, Java](https://github.com/apmcleod/MV2H); a slower Python port exists) to `run_eval`, as a *comparability* number beside the Rhythm Perceiver, TUTTI and PM2S. The Zulu `java.exe` bundled for Audiveris passes Smart App Control, but it has not been tried with MV2H.
- **Keep readability, gap-based rhythm and coverage as the primary measures.** The [2026 Dual Evaluation](https://arxiv.org/html/2608.04511) states that no notation metric has been validated against people *reading* a score. Its OMR-NED tracked playback preference only at ρ 0.38-0.50, against 0.84 for MUSTER's onset error.
- **Optional diagnostic:** [musicdiff](https://pypi.org/project/musicdiff/) (MIT) diffs visible symbols such as ties, tuplets and rest splits against the hand scores. Pin it below 6.0, which needs Python 3.12. It needs music21, so it goes in an eval-only group; that is a dependency to approve.
- **MUSTER** ([tool](https://amtevaluation.github.io/)) has six rates: pitch, missing, extra, onset, offset, voice. Its language and licence are unknown.
- **The method to copy** from [Cogliati et al. 2016](https://labsites.rochester.edu/air/publications/cogliati2016transcribing.pdf) is a blind expert rating of pages.

## 5. Beat tracking and solo detection

**beat_this stays.**
- Code *and* weights are MIT since 2026-05-28 ([README](https://github.com/CPJKU/beat_this)).
- Cross-validated beat/downbeat F1: JAAH 95.1/85.0, RWC Jazz 83.3/80.7 ([arXiv 2407.21658](https://arxiv.org/html/2407.21658v1)).
- No successor with released weights beats it on jazz.

**AlignBeat** ([arXiv 2510.14391 v3](https://arxiv.org/html/2510.14391)) is the one to watch.
- Level beat F1, but downbeat CMLt on JAAH rises 71.5 → 77.8. That is the continuity and metrical-level problem we fight.
- It is effectively a 2026 paper (v1-v2 of that ID were a different paper) and not yet peer-reviewed.
- Its code is "coming soon", with no licence.
- BeatFM's GTZAN margin over Beat This is about 1.3, not 4.1. It, HingeNet, BeatFCOS and BeatNet+ (weights without a licence) offer nothing to adopt.

**Activations cannot flag failures.** [The SMC Blind Spot (2026)](https://arxiv.org/html/2605.12287) found Beat This keeps a max activation of 0.931 on tracks where it fails completely. That matches our own finding. A trust signal has to come from elsewhere:
- **Committee disagreement** ([Holzapfel et al. 2012](http://mtg.upf.edu/system/files/publications/HolzapfelEtAl12-taslp.pdf)). Run beat_this's other checkpoints and shade stretches where they disagree: final0-2, small0-2 and fold0-7, which is 13 beyond the one we ship, plus the single_final and hung variants. Members of one architecture fail together more often than independent trackers do, so validate against `grid_drift`'s known slips (D33) first.
- **Listener-driven repair.**
  - [Yamamoto 2021](https://zenodo.org/records/5624651): the user corrects a few beats and the model adapts to fix the rest.
  - [Pinto et al. 2021](https://www.cisuc.uc.pt/download-file/16797/oLhvxuQlHLGmZbpp1c5i): fine-tune on one corrected 10 s region. SMC 0.551 → 0.589, Hainsworth 0.899 → 0.945; one example fell from 83 edits to 8. Their edit-count tool [ShiftIfYouCan](https://github.com/MR-T77/ShiftIfYouCan) is MIT.
  - Our arithmetic version: pin the listener's beats in `repair_beats` and re-derive the rest. Fine-tuning comes later if needed. beat_this ships training code with resume support.
- **Rubato and ballads.** Try [PLPDP](https://arxiv.org/abs/2308.10355)'s local-periodicity dynamic programming only inside flagged stretches. It was measured on classical piano. Never let a tempo floor force double time on slow music: the SMC paper found madmom's 55 bpm floor did that on 21% of tracks.
- **Octave checks.**
  - [JTD's second pass](https://transactions.ismir.net/articles/10.5334/tismir.186) re-tracks inside the track's own interquartile inter-beat-interval range.
  - [Beat Critic](https://archives.ismir.net/ismir2010/paper/000019.pdf) reads eighth-note alternation. It cut octave errors to 43% of the previous rate on well-tracked RWC tracks and 58% on the full set.
  - Both are optional third votes. R32 already fires on exactly the four bad grids.
- **Vocabulary for reporting slips:** [Annotation Coverage Ratio](https://arxiv.org/abs/2210.06817).

**Leakage in our beat pin.** beat_this's final checkpoints were trained on JAAH. The durations of four of our WJazzD tracks match JAAH's (measured locally):

| Track | Ours | JAAH |
|---|---|---|
| Giant Steps | 286.4 s | 287.4 s |
| St. Thomas | 405.7 s | 408.6 s |
| Blues in the Closet | 544.7 s | 545.3 s |
| Blues for Alice | 168.9 s | 169.1 s |

Embraceable You differs (205.9 s against 228.0 s), consistent with JAAH's note that its take is an alternate. Duration matches are circumstantial, not proof of the same recording. Quote beat F1 on those four with the fold checkpoints.

**Solo spans and routing (O2, O3).**
- No usable automatic jazz solo detector exists. Both JTD and DTL1000 marked solos by hand.
- Generic boundary detection on JSD peaks at F 0.232 at 0.5 s and 0.488 at 3 s.
- [allin1](https://github.com/mir-aidj/all-in-one) does predict a pop "solo" label, but it needs NATTEN built from source on Windows, madmom and librosa. Not viable here.
- So: our stem envelopes plus the bar grid, measured against **JSD** chorus rows and **JAAH** part labels.
- For instrument ID:
  - [Gomez, Abeßer & Cano 2018](http://ismir2018.ircam.fr/doc/pdfs/145_Paper.pdf) shows separation is the lever (macro F 0.669 → 0.803). Their models are CC BY-NC-SA, so retrain on WJazzD and JSD labels over our own stems.
  - [PANNs](https://zenodo.org/records/3987831) (CC BY 4.0 weights, CNN14 mAP 0.431) can say sax, trumpet, trombone or piano, but not alto versus tenor. It pulls librosa, so it would need the numba stub.
- The published bar for a "solo piano, no rhythm section" detector is about 88% F ([PiJAMA](https://transactions.ismir.net/articles/10.5334/tismir.162)). Our stem energies probably do it without a model.

## 6. The product landscape

### Where SwingScribe is already unusual
Against what the competitors document:
- **A soloist inside a band.** Separation plus routing plus the piano oracle. Songscription's own guide tells sax users to isolate the horn first and to transpose by hand ([guide](https://www.songscription.ai/blog/saxophone-melody-to-sheet-music)). Klangio struggles with multi-instrument recordings ([Hein, MusicRadar, 2026-07-10](https://www.musicradar.com/music-tech/klang-io-promises-to-turn-audio-into-notated-transcriptions-lead-sheets-and-guitar-tabs-but-does-it-actually-work-klang-io-transcription-studio-review)).
- **A page measured against human pages.** No competitor publishes accuracy numbers. SaxConvert's claimed 95% comes with no method ([FAQ](https://latouchemusicale.com/en/)).
- **Bar placement and meter.** Hein found Songscription completely lost on the rhythm of Monk's "Functional", an eighth late on Ray Charles and Für Elise, and cycling nonsense time signatures on Patsy Cline ([review, 2025-12-08](https://www.musicradar.com/music-tech/humans-will-be-doing-all-the-serious-music-transcription-for-the-foreseeable-future-songscription-review)). Klangio offers four time signatures, a grid and a triplet toggle, but no documented swing setting ([guide](https://klang.io/blog/additional-information-guide/)).
- **Horn transposition, two staves, key choice, swing or literal rhythm.**
- **Local, free, never uploaded.** Songscription may train on uploads by default, with opt-out for paid users only ([pricing FAQ](https://www.songscription.ai/pricing)). Moises says it never trains on user data ([moises.ai](https://moises.ai/)).

### Who else is there
- **AnthemScore 6** ([purchase](https://lunaverus.com/purchase), [web pricing](https://lunaverus.com/transcribe/pricing)).
  - One-time desktop licences at $29, $39 and $99 (only Studio gets lifetime updates), or web subscriptions from $8.33 a month.
  - 6.2.0 (2026-09-04): a new beat, downbeat and meter network; chord symbols, detected or typed; opt-in sharing of edits and audio for training.
  - 6.3.0 (2026-09-29): swing detection; whole-song fitting so sixteenths stop splitting into 16th+32nd; chord symbols "detected from the audio".
  - This is the closest competitor, and its swing accuracy is unknown.
- **Klangio** ([products](https://klang.io/products/)): Wind2Notes, Piano2Notes, Transcription Studio and Melody Scanner.
  - Over 10M transcriptions claimed since 2018.
  - $6-30 a month, 15-minute cap.
  - Melody Scanner is marketed for jazz sax improvisation; its two pages disagree on price.
  - Trustpilot 4.1 from 148 reviews, with complaints about wrong notes, octaves and support ([Trustpilot](https://uk.trustpilot.com/review/klang.io)).
  - Whether Muse Hub distributes it is **unverifiable**.
- **Songscription.** $5M seed and 150k users by November 2025 ([MBW](https://www.musicbusinessworldwide.com/songscription-raises-5m-in-funding-as-shazam-for-sheet-music-platform-reaches-150k-users/)). Its dollar prices are **unverifiable**: the page loads them by script.
- **Workflow incumbents.**
  - [Transcribe!](https://www.seventhstring.com/xscribe/overview.html) ($39) deliberately does no automatic notation. It accepts stems, and it *exports* markers; marker *import* is undocumented.
  - [Soundslice](https://www.soundslice.com/transcribe/) declines automatic transcription outright. Its [Data API](https://www.soundslice.com/help/data-api/) accepts MusicXML plus a recording plus syncpoints on the Teacher ($20 a month) or Licensing plans.
  - [Moises](https://moises.ai/features/chord-finder/) exports chord charts as iReal Pro or MusicXML.
  - Band-in-a-Box 2026 adds audio-to-MIDI with a notation view ([manual](https://www.pgmusic.com/manuals/bbw2026full/chapter11.htm)). Whether it imports MusicXML is unknown.
  - [ScoreCloud Songwriter](https://scorecloud.com/songwriter/) makes lead sheets for songwriters.
- **Human services define the paid deliverable.**
  - [Music Notation Hub](https://musicnotationhub.com/sheet-music-services/music-transcription/jazz-transcription/): from $29 a minute for solos and $35-40 for piano. MusicXML and transposed parts cost extra.
  - [MSMT](https://www.mysheetmusictranscriptions.com/jazz-transcription-service): $14-29+ a minute, chord symbols on request, and it refuses automatic transcription.
  - The deliverable is chord symbols, articulations (scoops, falls, ghost notes), a swing marking, transposed parts and both hands for piano.

### What users complain about, and what we could do
- **Rhythm, meter and bar placement.** This is the top complaint in both of Hein's reviews and in the only controlled user study.
  - Our answer is measured numbers. Publish the head-to-head (recommendation 1).
- **Fixing a draft costs more than it saves.**
  - [Holzapfel & Benetos 2019](https://archives.ismir.net/ismir2019/paper/000082.pdf): 16 transcribers showed no significant difference with an AI draft (p > 0.18).
    - Caveats: the material was 4-bar folk dance tunes; only 3 participants were designated experts, and all 3 took longer with the draft.
    - All but one called the draft a valuable starting point, and four said it helps mainly inexperienced transcribers.
  - Hein on his students: "it's the organization and presentation that's hard" ([blog, 2025-12-09](https://www.ethanhein.com/wp/2025/ai-transcription-on-musicradar/)).
  - So the product's audience is intermediate students and teachers, and the metric is time-to-correct:
    - Confidence shading. Our confidence already separates erased from kept notes at AUC 0.83.
    - Loop a bar slowly.
    - One-click downbeat and octave fixes.
    - A hide-and-reveal check-your-ear mode, which answers the educator objection that the by-ear process is the point ([Jazzadvice](https://www.jazzadvice.com/lessons/transcribing-is-not-transcibing-how-this-misnomer-has-led-you-astray/)).
- **No changes over the solo.** Chord symbols are standard in every lead-sheet competitor and in paid human work, and MuseScore 4.6 renders complex ones ([4.6 notes](https://musescore.org/en/4.6)). That Chordify flattens jazz harmony is **unverifiable** (no source found).
- **Hand-off to the tools people already use.** Worth adding:
  - A Soundslice package: MusicXML plus the recording plus syncpoints from our bar grid.
  - Stems plus bar markers for Transcribe!, if it ever documents marker import.
- **Trust.**
  - Say plainly on the site that nothing is uploaded.
  - An opt-in channel for *derived* labels only (erasures, additions, hand moves; never audio) would build the jazz correction dataset nobody has. AnthemScore just started collecting the same kind of data. It needs a licence and copyright decision first.

**Caveats.**
- Jazz forums refused automated fetches, so direct student voices are thin.
- "No mass-market tool documented swing before AnthemScore 6.3" is an absence claim, and **unverifiable**.

## 7. Five recommendations

**1. Measure against AnthemScore 6.3 and Klangio before claiming swing as ours.**
- AnthemScore claimed swing notation on 2026-09-29 ([version history](https://lunaverus.com/versionHistory)). Hein's reviews say rhythm is exactly where Klangio and Songscription fail ([Klangio](https://www.musicradar.com/music-tech/klang-io-promises-to-turn-audio-into-notated-transcriptions-lead-sheets-and-guitar-tabs-but-does-it-actually-work-klang-io-transcription-studio-review), [Songscription](https://www.musicradar.com/music-tech/humans-will-be-doing-all-the-serious-music-transcription-for-the-foreseeable-future-songscription-review)).
- Run the benchmark spans through AnthemScore's desktop trial, which is local, and through Klangio's and Songscription's free tiers.
- Score them all with `run_eval`'s notation scorer and WJazzD note F1, and publish aggregates only.
- Uploading commercial recordings to cloud services is the listener's decision, and Songscription trains on uploads by default.
- Add Riley & Dixon's MIT-declared `hf_midi_transcription` as the academic baseline.

**2. One new loader, two Kong checkpoints: bake off the FiloSax sax CRNN and the Edwards piano checkpoint** (A2, A4; [arXiv 2405.16687](https://arxiv.org/html/2405.16687), [Zenodo 10610212](https://zenodo.org/records/10610212)).
- Write a second loader in `piano.py`:
  - pass `model_type='Regress_onset_offset_frame_velocity_CRNN'`;
  - never reach upstream's `< 1.6e8` size check, which would `wget` piano weights over the file.
- No new pip dependency; the weights are downloads.
- Score both against the hybrid bar, dev split only. Test the sax model as line, gap-filler and selector.
- **Keep the activations.** They are the input to the §4 figure classifier.
- Write to the authors about the FiloSax-trained weights' terms. Until they answer, the sax model is an opt-in group, as MuScriptor is.

**3. Put the chord changes on the page, starting from changes the listener supplies** (a new O-item).
- Every human service and lead-sheet competitor delivers chord symbols ([Music Notation Hub](https://musicnotationhub.com/sheet-music-services/music-transcription/jazz-transcription/), [AnthemScore 6.2](https://lunaverus.com/versionHistory), [Moises chord export](https://moises.ai/features/chord-finder/)). We have none.
- Import iReal Pro, MusicXML `<harmony>` or typed changes, snap them to the bar grid we already trust, and export them as `<harmony>`. MuseScore 4.6 renders them.
- Automatic recognition comes only after it is measured on jazz vocabulary. WJazzD's per-beat chords (ODbL) and JAAH's (NC-SA, evaluation only) are the ground truth.

**4. Adopt the ground truth our benchmarks cannot supply.**
- **JSD** ([TISMIR](https://transactions.ismir.net/articles/10.5334/tismir.131)): chorus-level solo and instrument labels on the same 340 recordings as WJazzD. This is O2's and O3's test set, and it does not penalise a proposer for finding a solo WJazzD never transcribed.
- **The Aligned Omnibook** ([Zenodo](https://zenodo.org/records/14628467)): time-stamped notes and manual downbeats, which let us score all 50 Parker sides with mir_eval. Internal only, because of the licence conflict.
- **Leakage check:** re-quote beat F1 on the four tracks that appear to be in JAAH with beat_this's fold checkpoints.
- **Request Filosax access** ([Zenodo 6335779](https://zenodo.org/records/6335779)). Its aligned human score layer is roadmap A1's instrument at scale.
- **Add MV2H** ([repo](https://github.com/apmcleod/MV2H)) as a comparability column, never as the primary measure.

**5. Give the beat grid a confidence and a one-click repair.**
- Activations cannot flag a failed grid ([SMC Blind Spot](https://arxiv.org/html/2605.12287)), so use disagreement among beat_this's own checkpoints as the trust signal ([Holzapfel et al. 2012](http://mtg.upf.edu/system/files/publications/HolzapfelEtAl12-taslp.pdf)). Shade doubtful stretches on the roll and hold back the swing and lag rules there.
- Let the listener pin a beat or two and re-derive the rest in `repair_beats`, following [Yamamoto 2021](https://zenodo.org/records/5624651) and [Pinto et al. 2021](https://www.cisuc.uc.pt/download-file/16797/oLhvxuQlHLGmZbpp1c5i).
- Report the result as clicks-to-correct. The user study says correction time, not F1, is what decides whether a draft is worth having ([Holzapfel & Benetos 2019](https://archives.ismir.net/ismir2019/paper/000082.pdf)).

**The research bet after these five:** the per-beat figure classifier in §4. It becomes possible once recommendation 2 produces activations and roadmap A1 pairs audio with human pages.

## Addendum: what the completeness critic found missing

# Addendum: completeness critique

*A limit on this check:* the session's web-search budget ran out before this pass started. Everything added below was confirmed by fetching the URL directly, or read from this repo. A second pass with search may find more.

## Missing

**1. Separation is absent from the landscape, and its best lead has never been run.**
- The report does not cover the first stage of the pipeline. Two of our known failures belong to that stage: the soloist leaving the stem, and routing (D23).
- In-house, `docs/separation-research.md` (2026-09-01) ranked **Banquet** as "the strongest lead" ([code](https://github.com/kwatcharasupat/query-bandit), [paper](https://huggingface.co/papers/2406.18747), [weights](https://zenodo.org/records/13694558)).
  - It is a query-by-audio separator trained on MoisesDB, which has wind, reed and brass stems.
  - A few seconds of the soloist would serve as the query, which could remove routing outright.
- The experiment is still marked "when the Roformer trial is done", and nothing in the repo besides that doc mentions Banquet.
- The licence of the MoisesDB-trained weights is **unknown**.

**2. A precedent for rec 5's trust signal: Zapata, Davies & Gómez 2014, the multi-feature beat tracker** ([Essentia reference](https://essentia.upf.edu/reference/std_BeatTrackerMultiFeature.html), IEEE/ACM TASLP 22(4)).
- It runs one tracker over five different onset functions and picks the candidate by maximum agreement.
- Its confidence score is calibrated: above 1.5 means about 80% accuracy.
- The diversity comes from the **inputs**, not from sibling checkpoints. We already have the inputs: beat_this on the mix, the drum stem and the drum+bass stems.

**3. ChoCo** ([repo](https://github.com/smashub/choco); de Berardinis et al., *Scientific Data* 2023).
- 20,080 JAMS files, CC BY 4.0. The JAAH, Chordify and Mozart parts are NC-SA.
- Partitions include iReal Pro, the Real Book, Band-in-a-Box, WJazzD and a Jazz Corpus.
- For rec 3, the listener could pick a tune's changes from ChoCo instead of typing them.
- The rights in the upstream iReal Pro charts are **unknown**.

**4. Shanin & Dixon, "Annotating Jazz Recordings using Lead Sheet Alignment with Deep Chroma Features"**, WASPAA ([Dixon's page](https://webspace.eecs.qmul.ac.uk/s.e.dixon/); the PDF path says 2023).
- It is the published version of rec 3's "snap the changes to the bar grid", from the Rhythm Perceiver group.
- It also bears on O3's chorus boundaries.
- Its contents are **unverified**: the PDF would not fetch.

**5. Tony** ([site](https://www.sonicvisualiser.org/tony/)).
- A free, open-source note transcriber with a correction UI.
- Mauch et al. 2015 (TENOR) measured its "Accuracy and Efficiency". That is the outside precedent for E4's edit-cost metric and for time-to-correct.
- Its numbers and licence are **unverified**.

## Weakest claim

**The FiloSax CRNN's Omnibook lead**: F 75.43 against CREPE Notes' 70.41. This lead is what ranks it first in §2.
- The Omnibook reference was made by aligning MIDI onsets "to the frame level activations of a transcription model". The paper never says which model ([arXiv 2405.16687](https://arxiv.org/html/2405.16687)).
- If the model was the CRNN or a sibling of it, the reference favours it by construction.
- Başaran already has higher recall on the same set, and there is no breakdown by note length.

**Consequence:** rank it as a bake-off candidate, not as the likeliest win.

## Recommendations that do not follow from their evidence

**Rec 5, the committee of beat_this checkpoints.**
- The report itself concedes that one architecture's members fail together.
- The failures we measured are systematic, not random: half-rate and double-rate stretches, and the ragged stretch at 300 bpm (D33). Checkpoints trained on the same data would share them. That last point is our reasoning, not a measurement.
- The problem is also small. Placement is 73 of 77 on WJazzD, 12 of 12 and 22 of 22 on the pages (CLAUDE.md), and the downbeat is already one click.
- "Hold back swing and lag in doubtful stretches" has no evidence behind it.
- **What does follow:** pin a beat and re-derive the rest in `repair_beats`, for local slips such as Cheese Cake's bar 84 (`docs/roadmap.md`). Use Zapata-style input diversity if a trust signal is still wanted.

**The research bet in §4.**
- The Rhythm Perceiver's Omnibook numbers (0.53 against 0.18) compare it with **CRNN+qparse**, not with a swing-aware rule quantizer. They cover only the 60% of tracks where the beats held ([ICASSP 2026](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2026/ShaninEtAl-ICASSP2026.pdf)).
- So nothing yet shows that a learned figure classifier beats ours.
- **The cheap test first:** score our quantizer's per-beat figure accuracy on the 22 located Omnibook sides, using the paper's beat-signature measure.

**Rec 1, measure against the competitors.** The claim it rests on is real: AnthemScore 6.3.0 (2026-09-29) lists "Swing detection, written as straight eighths with a swing marking instead of triplets" ([version history](https://lunaverus.com/versionHistory)). But the recommendation is about positioning, and it improves nothing in the product. It also needs commercial recordings uploaded to cloud services. It belongs after recs 2 to 4, not first.
