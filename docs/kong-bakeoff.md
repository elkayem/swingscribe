# Two Kong checkpoints: Edwards et al. for pianists, FiloSax for horns

2026-09-30. Roadmap A4 (pianists) and A2 (horns), the first two entries of
docs/landscape.md section 2. Instruments: `piano.load_note_model` (a second
loader, `src/swingscribe/piano.py`) and `scripts/kong_bakeoff.py`, which
reuses `scripts/frontend_bakeoff.py`'s manifest, fixed fits, scorers and
declared tuning subset. Nothing in the pipeline changed; no pin moved;
nothing was written to a harness cache.

**Edwards et al. (pianists): level.** Swapped in for the pipeline's piano
checkpoint on the 11 dev pianists, nothing moves outside its interval: WJazzD
note F1 0.8985 -> 0.8983 (n=4), hand-score pitch F1 0.8396 -> 0.8428 (n=7,
3 up / 3 down), page rhythm 0.8711 -> 0.8627 (-0.0085 [-0.0242, +0.0050]).
CC BY 4.0 would let it ship; there is nothing to ship it for on this set.

**FiloSax (horns): beats the bar in the variant fixed in advance, and may
not be a default.** The one variant that was chosen on the tuning subset
before any all-sets run and clears the bar is the Basic Pitch hybrid with the
model's notes added in the holes it still has, on the saxophones only (onset
peak 0.7, 40 ms). It reads WJazzD note F1 0.8676 against the hybrid's 0.8650
(+0.0026 [+0.0016, +0.0036], 24 up / 2 down / 47 level over 73; on the 51
held out +0.0031 [+0.0019, +0.0045], 19/0/32) and Omnibook sub-eighth recall
0.7361 against 0.7034 (+0.0325 [+0.0240, +0.0413], 21/0/1). It leaves the
listener's page level (hand-score rhythm -0.0011 [-0.0027, +0.0004]).

A larger number is **exploratory**: the model as the LINE on alto and tenor,
with Basic Pitch's notes in its holes and the hybrid on every other horn,
reads 0.8698 (+0.0048 [+0.0017, +0.0079], 24/6/43) and writes a better page
(Omnibook rhythm +0.032, hand-score rhythm +0.010). But its form and its
route were designed after the all-sets results had been read, and on the
tuning subset, where it should have earned its place, it does not clear the
hybrid (+0.0030 [-0.0045, +0.0098], 7/2/13). Its held-out 51 had been seen,
through those results, when it was designed, so they are not an independent
test of it.

As a line on every horn the model loses: it never heard a trumpet or a
trombone (-0.031 and -0.057 there). As a CREPE hole-filler it ties the
hybrid, and as a selector it does nothing. The weights are trained on
non-commercial data: opt-in only, pending the authors' terms.

## Downloads

Approved by the listener on 2026-09-30. Everything is under
`C:\Users\lkmcg\swingscribe-research\` (outside OneDrive and outside AppData),
and nothing downloaded enters the repo.

| item | file | source | bytes | sha256 | licence as stated at the source |
|---|---|---|---|---|---|
| Edwards et al. piano CRNN | `edwards-piano/high_resolution_MAESTRO_augmentations.pth` | https://zenodo.org/records/10610212/files/high_resolution_MAESTRO_augmentations.pth | 103,815,845 | `b20f72053abc15b78f689b2a8b04c0a06529c8466e898b915803a1daa2011b9e` (md5 `cd449c03...` matches Zenodo's) | CC BY 4.0 (Zenodo record metadata, `zenodo-record-10610212.json` saved beside it) |
| Riley & Dixon FiloSax saxophone CRNN | `filosax-sax-crnn/filosax_25k.pth` | https://huggingface.co/xavriley/midi-transcription-models/resolve/b7bec65a2b860aca72856b0feef58b5df407b777/filosax_25k.pth (pinned to that commit) | 99,341,469 | `448cf2c8ea6d4b77f7435f5b9a496211ea60300c5c17fa9c754da764f75f3a6a` (= the Hub's LFS sha256) | "license: mit" on the model card (`hf-README.md`, `hf-model-info.json` saved beside it); the card says nothing about the training data. FiloSax's Zenodo records (6335779, Lite 5643734) are restricted access with no licence field; its terms are on the project site (dave-foster.github.io/filosax, "License"): non-commercial research only, not transferable, no distribution without written permission. Read 2026-09-30; paraphrase, page hashes and what it leaves open in `filosax-terms.md` beside the weights |

Derived, also outside the repo: the activations (onset, offset, frame and
velocity rolls, float16, 100 frames/s) of every region each model heard, under
`swingscribe-research/kong-activations/{kong,edwards,filosax}/` with an
`index.json` naming each region -- 68 MB, 68 MB and 699 MB. Roadmap A6
wants exactly these as classifier input. No build tool was downloaded.

What the files are, read without executing any pickle (`torch.load(...,
weights_only=True)` with an allowlist, below): both are `{"iteration",
"model", "sampler"}` -- Kong's training-script layout, the note network
alone, no pedal head. Edwards is iteration 240,000; FiloSax 25,000 (the paper
says 27.5k steps, so whether this is the evaluated checkpoint stays
unverifiable, as landscape.md said). 316 tensors, 24.66 M parameters each:
the same `Regress_onset_offset_frame_velocity_CRNN` as the note head of the
pipeline's checkpoint. Riley's `hf_midi_transcription` fork of the upstream
package changes the constructor, the batch size and the librosa calls, not
the network, and decodes the saxophone at upstream's thresholds (onset 0.3,
offset 0.3, frame 0.1).

## The second loader

`piano.load_note_model(path, device)` never constructs `PianoTranscription`,
so none of upstream's traps is reachable:

- upstream's default `model_type='Note_pedal'` indexes `checkpoint["model"]
  ["note_model"]` (a KeyError on these files), and it loads with
  `strict=False`, so a layout that slipped past the KeyError would run the
  random initial weights without a word. The loader builds the note network
  itself and loads STRICTLY: a checkpoint whose keys do not fit raises.
- upstream runs `wget` over any checkpoint under 1.6e8 bytes; both files are
  ~100 MB. The loader takes a file of any size as it is and never downloads.
- torch 2.6+ loads weights-only by default and both files pickle the training
  sampler's numpy RNG state, which that refuses. The loader allowlists exactly
  the numpy globals an RNG state names (`_reconstruct` under both of numpy's
  module names, `ndarray`, `dtype`, the dtype classes) -- still weights-only,
  never arbitrary pickle.

`note_activations` enframes and deframes exactly as upstream's `transcribe`
(10 s segments, half overlap, the middle half kept) and returns the four
rolls; `decode_notes` runs upstream's own `RegressionPostProcessor` on them
at any thresholds and adds `onset_strength` (the onset roll's peak at the
note's pitch within two frames), a confidence that does not lean on a
velocity head trained on another instrument. It also reads the pipeline's
own Note_pedal release (its note head IS this network).

`decode_notes` also drops a note that ends where it begins: upstream's peak
test is non-strict, and a float16 plateau of two equal onset frames decodes
to a zero-length copy of its note (the horn section has the numbers).

Tests (`tests/test_piano.py`; the four that need them importorskip torch and
the package, so CI runs one and skips four): every checkpoint layout in
circulation; a small fake checkpoint with a sampler state loads strictly,
downloads nothing (urlopen and `os.system` refuse), and raises on wrong keys
or a missing file; the deframed rolls are sample-exact against a network
whose every frame reads the sample it sits on; a synthetic onset/frame/offset
roll decodes to one note at the right time, length, velocity and strength;
a plateau decodes to one note, not two.

**The control that the loader IS the pipeline's oracle**: the pipeline's own
checkpoint through `load_note_model` + `decode_notes`, handed to the
pipeline's own take-building (`transcribe._consult_piano_oracle`), rebuilds
the cached default take of all 11 pianists note for note (share 1.0000 both
ways on every track) and every measure below to 0.0000. Every comparison
here decodes the float32 rolls at inference time or, for other thresholds,
the stored float16 rolls, which decode to the float32 notes within 3 of
46,811 (FiloSax), 2 of 8,121 (Edwards) and 0 of 8,840 (Kong).

## Pianists: Edwards et al. against the pipeline's checkpoint (A4)

**Set.** The 11 pianists on the dev side of the locked split: the seven
hand-scored (Carl Perkins, Oscar Peterson, Red Garland's Billy Boy, Sonny
Clark twice, Tommy Flanagan's Giant Steps, Wynton Kelly's Soul Station) and
the four WJazzD pianists (Hancock's Dolores, Gingerbread Boy and Orbits,
Garland's Oleo). Both checkpoints heard the same stem region, the one each
harness run transcribed (`frontend_bakeoff.py manifest`), cropped as the
pipeline crops it. Kong ran on the GPU (949 s of audio in 254 s); Edwards,
when the GPU was full, on four CPU threads (590 s). The Kong run was started
while another job held the card (5.9 of 6 GB used), against this round's
rule for a shared GPU. Its rolls are unaffected (the control below rebuilds
all 11 cached takes exactly), and `infer` and `crepe` now take the GPU only
with 3 GB free and otherwise run on the CPU and say so
(`kong_bakeoff.usable_device`).

**The swap.** Wherever a pianist's line reads the piano model, Edwards'
notes replace Kong's and the pipeline's own code does the rest:

- the **default take** (the shipped pianist line since 2026-09-18) is
  `line_selection.pick_line` over the model's full output, nothing else;
- the **second take** is CREPE's line corrected by the model --
  `corroborate.apply` (octave snap, corroboration), `fill_gaps`, then
  `reject_line_outliers` -- built by `transcribe._consult_piano_oracle` with
  the model's answer supplied.

CREPE was reserved for another task this round, so CREPE's pre-oracle line
was not re-run: it was rebuilt from the GUI's cached review payloads (the
frame trace -- gated, smoothed pitch, periodicity, corroborated onsets --
through `segment_notes` and `fold_octave_outliers`, `kong_bakeoff.py crepe`),
matched to each run by content. Seven of the eleven have a review. On the
four WJazzD pianists the rebuilt take reproduces the cached one (0.998-1.000
both ways); on Billy Boy, Giant Steps and Soul Station only 0.85-0.95,
because their reviews were made under an older config. Those three are
reported apart ("stale trace") and decide nothing.

**Onsets.** The oracle line's 20 ms onset shift was measured on Kong. Over
7,774 notes the two checkpoints both heard (same pitch within 50 ms), Edwards
sits a median +0.2 ms from Kong (-2.9 to +4.0 per track), so the shift
stands. Edwards hears 8% fewer notes (8,121 against 8,840).

### The default take (the oracle line), 11 pianists

Every change is Edwards minus Kong, `evaluation.paired_change`: mean, 95%
bootstrap interval resampled by recording, up/down/level (tolerance 0.002).
The control row under it (the cached take against Kong through the second
loader) is 0.0000 on every measure.

| measure | n | Kong (shipped) | Edwards | change |
|---|---|---|---|---|
| WJazzD note F1 | 4 | 0.8985 | 0.8983 | -0.0002 [-0.0048, +0.0045] 2/2/0 |
| WJazzD note precision | 4 | 0.9627 | 0.9643 | +0.0016 [-0.0029, +0.0085] 1/2/1 |
| WJazzD note recall | 4 | 0.8425 | 0.8408 | -0.0016 [-0.0093, +0.0084] 1/3/0 |
| hand-score pitch F1 (time-free) | 7 | 0.8396 | 0.8428 | +0.0032 [-0.0072, +0.0152] 3/3/1 |
| hand-score pitch precision | 7 | 0.8282 | 0.8301 | +0.0020 [-0.0089, +0.0141] 4/2/1 |
| hand-score pitch recall | 7 | 0.8537 | 0.8578 | +0.0041 [-0.0087, +0.0190] 3/3/1 |
| hand-score note F1 (audio against notation) | 7 | 0.5163 | 0.5151 | -0.0011 [-0.0096, +0.0063] 2/2/3 |
| page rhythm | 7 | 0.8711 | 0.8627 | -0.0085 [-0.0242, +0.0050] 2/4/1 |
| page value | 7 | 0.7999 | 0.7932 | -0.0067 [-0.0158, +0.0020] 2/4/1 |
| page readability | 7 | 0.9995 | 0.9985 | -0.0010 [-0.0029, +0.0000] 0/1/6 |
| page on the bar | 7 | 0.9265 | 0.9220 | -0.0045 [-0.0168, +0.0042] 3/2/2 |
| page tie rate | 7 | 0.0232 | 0.0225 | -0.0007 [-0.0022, +0.0011] 1/2/4 |
| edit cost per 100 reference notes | 7 | 52.01 | 52.25 | +0.24 [-2.36, +3.26] 3/4/0 |

Per track, pitch F1 (hand scores) and note F1 (WJazzD): Billy Boy 0.778 ->
0.810 and Giant Steps 0.896 -> 0.913 up; Peterson 0.845 -> 0.835 and Melody
for C 0.876 -> 0.860 down; Carl Perkins, the other Sonny Clark and Soul
Station within 0.004; Dolores 0.930 -> 0.923, Gingerbread Boy 0.916 -> 0.913,
Orbits 0.920 -> 0.926, Oleo 0.829 -> 0.831. Two up, two down, the rest level:
the spread of a different checkpoint, not a direction.

### The second take (CREPE's line corrected by the model)

| set | measure | n | Kong | Edwards | change |
|---|---|---|---|---|---|
| WJazzD pianists (control 0.998+) | note F1 | 4 | 0.8975 | 0.8984 | +0.0008 [-0.0021, +0.0037] 2/1/1 |
| | precision | 4 | 0.9502 | 0.9507 | +0.0005 [-0.0009, +0.0018] 1/0/3 |
| | recall | 4 | 0.8518 | 0.8533 | +0.0015 [-0.0048, +0.0078] 2/2/0 |
| hand-scored, stale trace | pitch F1 | 3 | 0.7093 | 0.7064 | -0.0029 [-0.0166, +0.0113] 1/2/0 |
| | note F1 (audio against notation) | 3 | 0.4747 | 0.4694 | -0.0053 [-0.0123, -0.0009] 0/2/1 |
| | page rhythm | 3 | 0.8418 | 0.8585 | +0.0167 [-0.0051, +0.0553] 1/1/1 |
| | edit cost | 3 | 69.93 | 68.54 | -1.38 [-2.83, -0.42] 0/3/0 |

Three tracks on a CREPE line the pipeline no longer produces: read these as
"no sign of a large effect", nothing more.

### Verdict: Edwards

**Level with the shipped checkpoint on every measure, none decided, on the
default take and on the second.** Its licence (CC BY 4.0) would let it ship
with attribution, but on these 11 pianists there is nothing to ship for, and
landscape.md's warning holds: the pianists' leading error is line selection
(issue #8), which no checkpoint changes -- the two checkpoints hear
different notes and the picker makes about the same line of them. Keep the
loader and the activations. The claim Edwards makes is robustness to
recording conditions, and the set that could test it is the one A4 plans --
ten 1940s-50s Bud Powell pages -- not these eleven; re-run
`kong_bakeoff.py pianists` when those are paired (it costs minutes).

## Horns: the FiloSax saxophone CRNN (A2)

**Set and scoring.** The 100 horn runs of the bake-off manifest -- 70 WJazzD
solos (73 scored solos with the 4 pianists and a two-solo file), the
listener's 5 horn hand scores, the Omnibook's 22 sides and the 3 PDF pages --
and `frontend_bakeoff.py`'s scorers, unchanged: WJazzD note F1 under CREPE's
FIXED fit (`score_wjazz.score`), recall by the reference note's performed
duration, the time-free notated pitch F1 and recall by the book's value, the
page (`run_eval.notation_scores`), every change `paired_change` by recording.
The harness caches are a snapshot taken before this round's hybrid
re-transcription (CREPE-only). **Controls**: the CREPE card reproduces all
221 pinned numbers it overlaps (worst |difference| 0.0000), and the Basic
Pitch hybrid rebuilt here from round one's notes reads 0.8650 on WJazzD and
0.8518 on the tuning subset, exactly round one's. A pianist keeps the default
take in every variant.

**The bar** is that hybrid: WJazzD note F1 **0.8650** over 73 and Omnibook
sub-eighth recall **0.7034**; CREPE reads 0.8580 and 0.6604.

**Inference.** 9,877 s of horn audio, once, rolls stored (float16). On the
GPU a region took 5-20 s; the run died twice when the machine ran out of
commit memory (cuBLAS inside the GRU), resumed from its last saved region,
and did the final 7 regions on four CPU threads (730 s of audio in 309 s). A
GPU region re-run on the CPU decodes to the same notes (158 of 158, both
ways).

**A float16 trap, found and fixed.** Upstream's onset peak test is
non-strict, so a plateau of two EQUAL onset frames is two onsets, and the
second decodes to a copy of the note that ends before it begins. float16
rolls make plateaus: 329 such copies among 47,143 notes, none from float32.
`decode_notes` now drops a note of no length (tested); after it the float16
decode matches the float32 one to 3 notes in 46,811 (and 2 in 8,121 for
Edwards). The first check of this was one-sided and read 1.0000; it is
two-sided now.

**Tuning, declared -- and the two variants that were not.** The following
were chosen on round one's tuning subset (`is_tuning`: 22 WJazzD solos -- 8
trumpet, 5 alto, 4 tenor, 3 trombone, 2 soprano) and only then run on every
set (the all-sets runs `final-a` and `final-b`):

- the model's matched onsets sit 6.5 ms early (median of per-solo medians),
  so every model onset moves 6 ms late;
- as the LINE, decode onset threshold 0.5 (0.3: -0.0026 against CREPE on
  saxophones, 0.7: -0.0123; the model's onset regression almost never
  clears 0.9 -- 340 notes in all 100 regions);
- as a FILLER, the gate is the onset roll's peak (`onset_strength`), not the
  velocity head (velocity at 0.5: -0.0079 against CREPE), at 0.7 with the
  hybrid's 40 ms hole; the decode threshold does not matter under it;
- the selector's thresholds (below) all read within 0.0015 of CREPE;
- the additive composite -- the hybrid plus the model's notes in the holes it
  still has, saxophones only -- at the filler's settings (0.7, 40 ms), with
  its neighbours checked (onset peak 0.6 / 0.8, hole 30 / 60 ms: +0.0008 to
  +0.0013). It is the one declared variant whose interval against the hybrid
  clears zero on the tuning subset, so it is the CONFIRMATORY result below.

**Not declared: the model as the line with Basic Pitch in its holes**, on
all saxophones and on alto and tenor only. Both were designed AFTER the
all-sets runs of the declared variants had been read -- the line on every
horn by instrument, and the saxophone line with its held-out 51 and its split
by instrument (soprano -0.089, tenor +0.016, alto +0.014 against CREPE).
Only then were they run on the tuning subset, where NEITHER clears the
hybrid (the last two rows). They are reported as EXPLORATORY throughout. Their
held-out 51 had been seen, through the declared variants' results, when they
were designed, so their +0.0044 and +0.0056 there are not independent
tests.

| tuning subset, 22 solos (CREPE 0.8442, hybrid 0.8518) | F1 | P | R | change vs the hybrid |
|---|---|---|---|---|
| model as the line, every horn (decode 0.3, 0.5, 0.7) | 0.8149 / 0.8209 / 0.7940 | 0.809 / 0.854 / 0.903 | 0.831 / 0.799 / 0.719 | -0.0369 / -0.0309 / -0.0579 |
| ... skyline, loudest of cluster, `pick_line` (0.3) | 0.8046 / 0.8066 / 0.7560 | | | -0.047 / -0.045 / -0.096 |
| ... saxophones only, decode 0.5 | 0.8436 | 0.868 | 0.826 | -0.0082 [-0.0327, +0.0090] 7/10/5 |
| CREPE + model in the holes, every horn, 0.5 / 0.6 / 0.7 / 0.8 | 0.8447 / 0.8466 / 0.8477 / 0.8463 | | | -0.0071 / -0.0052 / -0.0041 / -0.0055 |
| ... saxophones only, 0.6 | 0.8491 | 0.847 | 0.853 | -0.0028 [-0.0055, -0.0001] 4/10/8 |
| selector (six settings, saxophones) | 0.8436-0.8455 | | | -0.0063 to -0.0082 |
| **declared:** hybrid + model in the holes it still has, saxophones (0.7, 40 ms) | 0.8531 | 0.848 | 0.861 | **+0.0013 [+0.0001, +0.0027] 5/2/15** |
| *exploratory, run here afterwards:* model as the line + Basic Pitch in its holes, all saxophones; hybrid on other horns | 0.8545 | 0.865 | 0.848 | +0.0027 [-0.0076, +0.0122] 8/3/11 |
| *exploratory, run here afterwards:* the same on alto and tenor only | 0.8548 | 0.861 | 0.852 | +0.0030 [-0.0045, +0.0098] 7/2/13 |

The tuning subset points the same way as the all-sets split: the saxophone
line against CREPE reads alto +0.0079 (5 solos), tenor +0.0168 (4) and
soprano -0.0592 (2), and the paper's own caveat (the model struggles in the
altissimo) agrees. The route still came from the all-sets split, and on two
soprano solos the tuning subset alone could not have settled it.

### All sets

"vs hybrid" is against the bar; every interval is a 95% bootstrap by
recording, then up/down/level. Rows (i) to (iii) and the declared composite
were fixed on the tuning subset before this table existed. The two rows
marked *exploratory* were designed after the rows above them had been read,
so their held-out column is not a held-out test.

| variant | WJazzD F1 (P / R), n=73 | vs CREPE | vs hybrid | held out vs hybrid, n=51 | hand scores pitch F1, n=12 | Omnibook pitch F1, n=22 | Omnibook sub-eighth recall | vs hybrid |
|---|---|---|---|---|---|---|---|---|
| CREPE (shipped until this round) | 0.8580 (0.872 / 0.847) | -- | -0.0070 | -0.0067 | 0.8629 | 0.7905 | 0.6604 | -0.0430 |
| **Basic Pitch hybrid (the bar)** | **0.8650 (0.870 / 0.863)** | +0.0070 | -- | -- | 0.8625 | 0.7976 | **0.7034** | -- |
| (i) model as the line, every horn (upstream's decode 0.3; 0.5 read 0.006 better on the tuning subset) | 0.8403 (0.843 / 0.845) | -0.0177 [-0.0320, -0.0059] 29/40/4 | -0.0248 [-0.0393, -0.0125] 27/41/5 | -0.0195 [-0.0368, -0.0057] 21/25/5 | 0.8634 | 0.8314 | 0.7772 | +0.0740 [+0.0514, +0.0976] 20/1/1 |
| (i) ... saxophones only, CREPE elsewhere | 0.8614 (0.881 / 0.846) | +0.0034 [-0.0053, +0.0103] 28/9/36 | -0.0036 [-0.0136, +0.0041] 25/31/17 | -0.0017 [-0.0115, +0.0053] 18/21/12 | 0.8705 | 0.8293 | 0.7161 | +0.0081 [-0.0153, +0.0325] 11/10/1 |
| (ii) CREPE + model in the holes, every horn | 0.8644 (0.866 / 0.865) | +0.0064 [+0.0043, +0.0083] 49/8/16 | -0.0007 [-0.0027, +0.0013] 26/27/20 | +0.0008 [-0.0018, +0.0032] 22/15/14 | 0.8644 | 0.8044 | 0.7165 | +0.0125 [-0.0011, +0.0261] 11/6/5 |
| (ii) ... saxophones only | 0.8638 (0.867 / 0.863) | +0.0058 [+0.0039, +0.0078] 30/1/42 | -0.0012 [-0.0031, +0.0006] 20/28/25 | -0.0006 [-0.0030, +0.0018] 16/18/17 | 0.8643 | 0.8071 | 0.7380 | +0.0343 [+0.0210, +0.0477] 19/2/1 |
| (iii) selector, saxophones | 0.8591 (0.873 / 0.848) | +0.0011 [+0.0002, +0.0022] 14/4/55 | -0.0059 [-0.0087, -0.0035] 6/44/23 | -0.0057 [-0.0089, -0.0033] 4/32/15 | 0.8619 | 0.8005 | 0.6619 | -0.0421 [-0.0572, -0.0298] 1/21/0 |
| **declared, confirmatory: hybrid + model in its remaining holes, saxophones** | **0.8676 (0.867 / 0.870)** | +0.0096 [+0.0073, +0.0122] 54/0/19 | **+0.0026 [+0.0016, +0.0036] 24/2/47** | **+0.0031 [+0.0019, +0.0045] 19/0/32** | 0.8635 | 0.8060 | **0.7361** | **+0.0325 [+0.0240, +0.0413] 21/0/1** |
| *exploratory:* model as the line + Basic Pitch in its holes, all saxophones; hybrid elsewhere | 0.8689 (0.878 / 0.862) | +0.0109 [+0.0070, +0.0151] 49/8/16 | +0.0039 [-0.0004, +0.0079] 25/8/40 | (seen) +0.0044 [+0.0002, +0.0083] 17/5/29 | 0.8674 | 0.8341 | 0.7418 | +0.0357 [+0.0174, +0.0551] 17/4/1 |
| *exploratory:* the same on alto and tenor only | 0.8698 (0.877 / 0.865) | +0.0118 [+0.0085, +0.0153] 51/6/16 | +0.0048 [+0.0017, +0.0079] 24/6/43 | (seen) +0.0056 [+0.0025, +0.0089] 17/4/30 | 0.8674 | 0.8341 | 0.7418 | +0.0357 [+0.0174, +0.0551] 17/4/1 |

The selector (iii) is CREPE's line with its pitch replaced where the model
struck a confident note (onset peak 0.7) within 50 ms at another pitch and
nothing at CREPE's; dropping CREPE notes the model does not vouch for was
tried too and moved nothing. The model (every horn, 0.3 decode) has the
right pitch on 135 of CREPE's 841 `neighbour` errors (16%), about what Basic
Pitch had (3-15% by decode): **the neighbour class is not a checkpoint
question either.**

**By instrument** (WJazzD, the model as the line on every horn, against
CREPE): trumpet 0.8357 against 0.8668, -0.0311 [-0.0470, -0.0165], 4 up / 22
down; trombone 0.7692 against 0.8262, -0.0570, 0/5; soprano -0.0733, 1/2;
the one guitar solo 0.571 against 0.887. Tenor +0.0075 [+0.0004, +0.0142]
15/6 and alto +0.0137 [+0.0012, +0.0254] 9/4. **It never saw a trumpet or a
trombone, and it shows; on alto and tenor it is a better line than CREPE's**
-- a reading of all sets, and the one the exploratory route was built on.
Against the hybrid, the declared composite reads tenor +0.0050 [+0.0028,
+0.0072] 13/2/6, alto +0.0051 [+0.0025, +0.0085] 9/0/4 and soprano +0.0051
2/0/1. The exploratory alto-and-tenor composite reads tenor +0.0103
[+0.0045, +0.0160] 15/4/2 and alto +0.0102 [-0.0039, +0.0224] 9/2/2. Every
other horn is identical to the hybrid in both, by construction.

**Recall by performed duration** (WJazzD, pooled over 73 solos):

| | <60 ms | 60-100 | 100-150 | 150-250 | >250 | all |
|---|---|---|---|---|---|---|
| reference notes | 3,734 | 11,460 | 9,900 | 5,649 | 3,090 | 33,833 |
| CREPE | 0.489 | 0.830 | 0.914 | 0.917 | 0.881 | 0.836 |
| Basic Pitch hybrid (the bar) | 0.563 | 0.848 | 0.921 | 0.922 | 0.883 | 0.853 |
| model as the line, every horn (0.3) | 0.580 | 0.830 | 0.906 | 0.903 | 0.854 | 0.839 |
| model as the line, saxophones (0.5) | 0.510 | 0.826 | 0.912 | 0.916 | 0.856 | 0.834 |
| CREPE + model in the holes | 0.551 | 0.855 | 0.924 | 0.925 | 0.885 | 0.856 |
| declared: hybrid + model in its holes, saxophones | **0.589** | **0.859** | 0.924 | 0.925 | **0.885** | **0.862** |
| exploratory: model line + Basic Pitch, alto and tenor | 0.576 | 0.852 | 0.924 | 0.925 | 0.880 | 0.858 |

A perfect choice between CREPE and the model (0.3 decode) would reach 0.895
(under 60 ms 0.664) -- round one's CREPE-or-Basic-Pitch ceiling was 0.901
(0.668). The two models hear about as many of the missing notes; the
composites are how much of it is reachable without a trained selector.

**The page**, both composites against the hybrid (rhythm, value and
placement only where both pages are trusted):

| set | variant | rhythm | value | on the bar |
|---|---|---|---|---|
| hand scores (12; 5 horns can move) | declared | 0.8413 -> 0.8402, -0.0011 [-0.0027, +0.0004] 1/3/8 | +0.0006 [-0.0001, +0.0015] 1/0/11 | +0.0007 [-0.0008, +0.0024] 2/1/9 |
| | exploratory | 0.8413 -> 0.8515, +0.0103 [+0.0004, +0.0215] 4/1/7 | +0.0065 [-0.0063, +0.0223] 3/1/8 | +0.0088 [+0.0008, +0.0182] 4/1/7 |
| Omnibook (22) | declared | 0.7843 -> 0.7884, +0.0042 [-0.0001, +0.0086] 13/7/2 | 0.7197 -> 0.7289, +0.0091 [+0.0054, +0.0133] 18/2/2 | +0.0021 [-0.0016, +0.0065] 10/6/6 |
| | exploratory | 0.7843 -> 0.8161, +0.0319 [+0.0160, +0.0482] 18/4/0 | 0.7197 -> 0.7570, +0.0373 [+0.0258, +0.0495] 21/1/0 | +0.0185 [+0.0040, +0.0333] 16/5/1 |
| PDF pages (3) | declared | +0.0068, 3/0/0 | +0.0114, 3/0/0 | +0.0101, 3/0/0 |
| | exploratory | +0.0276, 3/0/0 | +0.0442, 3/0/0 | +0.0063, 2/0/1 |

Readability is level everywhere, and the Omnibook tie rate is level under
the declared composite (-0.0005) and falls 0.0419 -> 0.0373 under the
exploratory one. **The declared composite leaves the listener's page where
it was**: it keeps CREPE's line and adds notes, and only the book's note
values move (+0.009). **The page gain belongs to the exploratory variant**:
it comes from the model's LINE, its onsets, not from more notes. Errors on
WJazzD say the same. Against the hybrid, the exploratory composite has
octave errors 148 -> 94 and false positives 2,267 -> 2,042, with misses level
(2,716 both). The declared composite has misses 2,716 -> 2,403 and false
positives 2,267 -> 2,393, with octave errors level (148 -> 153).

**Two things that weaken the Omnibook column.** The paper's own evaluation
set was 50 Omnibook solos, and the file is named 25k where the paper says
27.5k steps, so a checkpoint chosen on the Omnibook cannot be ruled out: the
book is not an independent test of THIS checkpoint. WJazzD's held-out 51 is,
for the declared composite. For the exploratory composites it is not, because
it had been read before they were designed. And the book is Charlie Parker on
alto throughout.

### Verdict: FiloSax

**It beats the bar, on both halves of the criterion, as a purely additive
hole-filler on the saxophones: the hybrid, with the model's notes in the
holes it still has.** This variant was fixed on the tuning subset before
any all-sets run. It reads WJazzD 0.8650 -> 0.8676, +0.0026 [+0.0016,
+0.0036], 24 up / 2 down / 47 level over 73. On the 51 held out it reads
+0.0031 [+0.0019, +0.0045], 19/0/32, and Omnibook sub-eighth recall goes
0.7034 -> 0.7361, +0.0325 [+0.0240, +0.0413], 21/0/1. It leaves the page
level (hand-score rhythm -0.0011 [-0.0027, +0.0004]; Omnibook rhythm +0.0042
[-0.0001, +0.0086]). It is a small gain, but it is the result that was
tested the way this bake-off said it would test.

**Exploratory, and larger:** the model as the LINE on alto and tenor, with
Basic Pitch filling its holes and the hybrid on every other horn, reads
0.8698, +0.0048 [+0.0017, +0.0079], 24/6/43. Sub-eighth recall is +0.0357
[+0.0174, +0.0551], and the page moves with it (hand-score rhythm +0.0103
[+0.0004, +0.0215], Omnibook rhythm +0.032, value +0.037). It was designed
after the all-sets results had been read. On the tuning subset, where it
would have had to earn its place, it is +0.0030 [-0.0045, +0.0098], 7/2/13,
which is not a clearance. Its held-out +0.0056 was seen before it was
designed. Read it as a hypothesis worth a confirmatory test on solos
nothing here has scored, not as the result. Its all-saxophone sibling
(+0.0039 [-0.0004, +0.0079]) is the same.

As a plain line on every horn it loses (-0.0177 against CREPE, trumpet and
trombone worst), as a CREPE hole-filler it only ties the hybrid (-0.0007),
and as a selector it does nothing (+0.0011 against CREPE).

**It may never be the default.** The weights are tagged MIT on Hugging Face,
but they are trained on FiloSax, which is non-commercial research only with
no distribution without written permission, and the card is silent on
that. Those terms are on the project site, not on the Zenodo record, and
they do not say whether trained weights count as a derivative
(`filosax-terms.md` beside the weights). If the listener wants it: an opt-in dependency group and module
boundary like MuScriptor's (CLAUDE.md, M10), downloaded on request rather
than shipped, **pending the authors' written terms** -- ask Riley and Dixon
before anything else. Two product consequences first:

- it needs the INSTRUMENT, which nothing here infers -- even the declared
  composite needs "saxophone or not". The sidecar's `transposition` cannot
  say it (B-flat is tenor, soprano and trumpet), so it would be a new
  per-track listener choice beside `ensemble`, or a routing guess
  (docs/routing.md) that has not been built;
- the soprano read worse whenever the model was its LINE (3 solos, -0.023 to
  -0.089 by variant). The declared composite keeps the hybrid's line there
  and reads +0.0051 (2/0/1); the exploratory one leaves the soprano on the
  hybrid.

What it says about A2 step 2 (the fine-tune): a note model trained on one
instrument's jazz (FiloSax is tenor saxophone), used as the line on the
saxophones, beats CREPE's line on alto and tenor. All sets, against CREPE:
tenor +0.0161 [+0.0093, +0.0227], 17/4; alto +0.0136 [+0.0003, +0.0250],
10/3. The page it writes is better where measured (the exploratory
composite above). This is the split the exploratory route was read from, so
it is a hypothesis rather than a confirmed gain. It is still the strongest
sign yet that a jazz-trained note model is worth training -- on trumpet and
trombone above all, which no published model covers. The confirmatory
evidence that the model adds something is the declared filler's smaller,
cleaner +0.0026.

## Reproduce

Scratch paths are examples; `SNAP` holds copies of `.benchmark-notes-c0.2-d0.0.json`,
`.benchmark-grids.json` and `tests/regression/real-audio-baselines.json`, and
`OUT` starts with round one's `manifest.json`, `fits.json` and Basic Pitch
notes (`bp-o80-f30-m23-nomel.json`) from the `frontend_bakeoff.py` scratch.

    .venv\Scripts\python.exe scripts/kong_bakeoff.py infer --out OUT --model kong --which piano --device cuda
    .venv\Scripts\python.exe scripts/kong_bakeoff.py infer --out OUT --model edwards --which piano --device cuda
    .venv\Scripts\python.exe scripts/kong_bakeoff.py infer --out OUT --model filosax --which horn --device cuda
    .venv\Scripts\python.exe scripts/kong_bakeoff.py decode --out OUT --model filosax --onset 0.5
    .venv\Scripts\python.exe scripts/kong_bakeoff.py crepe --out OUT --snapshot SNAP
    .venv\Scripts\python.exe scripts/kong_bakeoff.py pianists --out OUT --snapshot SNAP
    .venv\Scripts\python.exe scripts/kong_bakeoff.py horns --out OUT --snapshot SNAP --notation --check \
        --fs OUT/filosax/notes-default.json --bp OUT/bp-o80-f30-m23-nomel.json --fs-shift 0.006 \
        --variants "saxbph/stack:s:0.7:0.04" --summary OUT/final.json
    .venv\Scripts\python.exe scripts/kong_bakeoff.py horns --out OUT --snapshot SNAP --notation \
        --fs OUT/filosax/notes-o0.5-f0.1.json --bp OUT/bp-o80-f30-m23-nomel.json --fs-shift 0.006 \
        --variants "atbph/fsbp:s,saxbph/fsbp:s" --summary OUT/final.json

The first `horns` run is the declared composite (the filler decodes at
upstream's thresholds; its gate is the onset peak), the second the two
exploratory ones. `infer` saves per region and resumes; a crash costs one
region, and it takes the GPU only with 3 GB free. `horns --subset tuning`
scores the declared tuning subset alone, WJazzD only. Variant grammar:
`kong_bakeoff.horn_variant` and the `ROUTES` table.

## Not done, and why

- **A confirmatory test of the exploratory line composite.** It needs horn
  solos that no run here has scored. WJazzD's held-out 51 were read before
  it was designed, and the Omnibook is the paper's own set. Candidates are
  alto and tenor solos with human note-level onsets outside WJazzD and the
  book, or new WJazzD-free hand scores from the listener. Declare the
  variant (`atbph/fsbp:s`, decode 0.5, shift 6 ms) before scoring them.

- **The second pianist take on four hand-scored pianists** (Carl Perkins,
  Peterson, both Sonny Clarks) and a validated one on three more: no cached
  review, and CREPE belonged to another task this round.
  `kong_bakeoff.py crepe --source crepe` runs it (minutes on the GPU).
- **Edwards' own decoding thresholds or onset shift**: the checkpoint's onsets
  sit where Kong's do (+0.2 ms), and the pianist line is the picker's, which
  ranks velocity within the track; nothing suggested a retune.
- **A trained selector** between CREPE, Basic Pitch and the saxophone model:
  the ceilings say how much it could buy (0.895-0.901 recall against 0.862
  for the best rule), and roadmap A6 is where the activations are for.
- **Horn edit cost**: the pianists have it; the horn page is judged on the
  same rhythm, value and placement round one used.
