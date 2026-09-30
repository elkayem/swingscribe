# A2 bake-off: a pretrained note-level model against CREPE, on our stems

2026-09-30. Roadmap A2, step 1 (docs/roadmap.md). Instruments:
`scripts/frontend_bakeoff.py` (Windows: manifest, variants, scoring) and
`scripts/bakeoff_basic_pitch_wsl.py` (WSL: the model). Nothing in the
pipeline changed; no pin moved; nothing was written to a harness cache.

## The question

The transcriber's two largest remaining error classes are ones no CREPE
threshold reaches (every gate sweep is on the record, CLAUDE.md M7b and
docs/error-taxonomy.md): the SHORT note -- under an eighth, 27% of the
Omnibook's notes and 54% of its outright misses -- and the semitone
`neighbour`. Does a pretrained NOTE-LEVEL model hear those notes better on
the SAME separated stems? If it does, the front end is a limit and a
fine-tune (step 2) has something to learn; if it does not, the limit is the
stems and a fine-tune starts from nothing.

The model is **Basic Pitch** (Spotify, ICASSP 2022, Apache-2.0; the listener
approved it): a small polyphonic note/onset network, 230 KB as ONNX, trained
on many instruments and never on jazz or on separated stems.

## Setup

- **Where it runs.** Basic Pitch imports librosa, resampy and numba, which
  Smart App Control refuses here and CLAUDE.md forbids in the project. It
  runs in WSL (Ubuntu 26.04) in a venv OUTSIDE the repo (`~/bakeoff`):
  basic-pitch 0.4.0, its `nmp.onnx` on onnxruntime 1.30.0, CPU, 4 threads.
  basic-pitch pulls full TensorFlow on Linux/3.11; it was uninstalled (the
  ONNX graph needs none of it), and `setuptools<81` restores the
  `pkg_resources` resampy 0.4.2 still imports. The recipe is in the WSL
  script's docstring.
- **What it hears.** Exactly the stem wav each harness run transcribed:
  `frontend_bakeoff.py manifest` resolves it with `run_eval`'s own
  resolution (sidecar model and stem, `library.ingested_document` +
  `library.resolve_stem`, the batch cache `benchmark/.swingscribe-cache`).
  111 runs: 86 of the listener's and WJazzD's tracks, 22 Omnibook sides, 3
  PDF pages; 11 pianists. Each region plus 1 s either side, loaded at
  22,050 Hz mono.
- **Cost.** 10,966 s of audio in 140 s of inference (78x real time, CPU);
  the posteriorgrams (frame + onset, float16) are 230 MB; decoding all 111
  regions under one parameter set takes 4-15 s. Every setting below is a
  decode of the same posteriorgrams, never a second inference.
- **Scoring.** The harness's own functions. WJazzD: `score_wjazz.score`
  under a FIXED fit -- CREPE's (`identify_all` on CREPE's notes, once), so a
  polyphonic variant cannot move or fail the fit and the comparison
  measures the front end, not the fit. Notated references: pitch F1 by
  `alignment.measured_transposition` exactly as `score_benchmark.score_tune`
  computes it; recall by the book's notated value from the same
  alignment's true matches (`benchmark.anchor_map`, the hits the error
  taxonomy's Omnibook block counts). Error classes: `taxonomy.match`,
  `pair_unmatched`, `classify_pair` (no frame evidence, so only the pair
  classes and pure miss/fp are counted). The page: `run_eval.notation_scores`.
  Every change is `evaluation.paired_change` against a CREPE card scored by
  the same code in the same run: mean delta, 95% bootstrap interval by
  recording, up/down/level by recording (tolerance 0.002).
- **The control.** The CREPE card reproduces **all 221 pinned numbers it
  overlaps** (73 WJazzD note F1, 37 notated pitch F1, 111 notation rhythm /
  value / readability) with worst |difference| 0.0000.
- **Tuning.** Declared before anything was scored: the WJazzD recordings
  whose SHA-1 of the name is 0 mod 3 (`is_tuning`) -- 22 solos, all horns.
  Every threshold below was chosen there and only there. Held out: the other
  51 WJazzD solos, the listener's twelve hand scores, the Omnibook's 22
  sides and the 3 PDF pages, none of which was looked at until the chosen
  setting was fixed.

## The minimum note length is the question

Basic Pitch's default `minimum_note_length` is 127.7 ms. On WJazzD it
deletes the population under test: recall of notes under 60 ms is **0.098**
against CREPE's 0.489 (all 73 solos, 3,734 such notes). Every decode below
uses 23 ms (a note must last at least three 11.6 ms frames, 35 ms) unless
it says so.
`melodia_trick` (notes grown from leftover frame energy without an onset)
was off in every setting that was kept: it lowered the hybrid on every
threshold tried.

## Variants

- **raw** -- Basic Pitch's notes as they come: polyphonic.
- **sky / loud** -- one note per 50 ms onset cluster
  (`line_selection.clusters_of`): the highest, or the loudest (amplitude).
- **pick** -- `line_selection.pick_line`, the pianist's Viterbi picker,
  with amplitude as the velocity it ranks.
- **hybrid** (HORNS only) -- CREPE's line plus Basic Pitch's notes where the
  line has a HOLE, in the line's register: `corroborate.fill_gaps`, the
  pianist's gap-filler, called with Basic Pitch as the oracle. Its gates as
  shipped for the piano (top two of a cluster, a hole 60 ms clear of any
  line onset and past half the previous note, within an octave of the
  local median, confidence floor) with two measured on the tuning subset:
  the confidence floor (Basic Pitch's amplitude, 0.3) and the hole's
  clearance (40 ms: the piano's 60 ms keeps out exactly the short notes in
  question). A pianist keeps the default take, the oracle line: a horn
  change must not cost a pianist anything.
- **nvote** (horns only) -- CREPE's line with a note's pitch changed where
  Basic Pitch struck a semitone or a tone away within 50 ms and nothing at
  CREPE's pitch. It asks the `neighbour` question directly.

Basic Pitch's matched onsets sit 3-4 ms early on the tuning subset (median
of per-solo medians); every copied onset is moved 4 ms late. It is in the
noise of the 50 ms tolerance, measured and applied rather than assumed.

## Tuning subset (22 WJazzD solos; CREPE F1 0.8442, recall 0.839, under 60 ms 0.439)

| variant | decode (onset / frame / min length) | F1 | P | R | <60 ms R | change |
|---|---|---|---|---|---|---|
| raw | 0.5 / 0.3 / 128 ms, melodia (the default) | 0.6782 | 0.813 | 0.601 | 0.109 | -0.1659 [-0.2045, -0.1288] 0/22/0 |
| raw | 0.5 / 0.3 / 23 ms | 0.7890 | 0.741 | 0.850 | 0.533 | -0.0551 [-0.0751, -0.0369] 1/21/0 |
| loud | 0.5 / 0.3 / 23 ms | 0.8305 | 0.836 | 0.829 | 0.451 | -0.0136 [-0.0236, -0.0035] 1/16/5 |
| pick | 0.5 / 0.3 / 23 ms, melodia | 0.8202 | 0.841 | 0.805 | 0.365 | -0.0239 [-0.0334, -0.0137] 1/21/0 |
| nvote, amp 0.4 | 0.5 / 0.3 / 23 ms | 0.8427 | 0.850 | 0.838 | 0.436 | -0.0014 [-0.0026, -0.0003] 4/9/9 |
| hybrid 0.3 | 0.4 / 0.3 / 23 ms | 0.8338 | 0.812 | 0.860 | 0.511 | -0.0103 [-0.0157, -0.0052] 3/16/3 |
| hybrid 0.3 | 0.5 / 0.3 / 23 ms | 0.8435 | 0.831 | 0.859 | 0.508 | -0.0006 [-0.0043, +0.0032] 7/10/5 |
| hybrid 0.3 | 0.6 / 0.3 / 23 ms | 0.8475 | 0.840 | 0.858 | 0.505 | +0.0034 [+0.0000, +0.0070] 12/4/6 |
| hybrid 0.3 | 0.7 / 0.3 / 23 ms | 0.8489 | 0.846 | 0.854 | 0.496 | +0.0047 [+0.0017, +0.0078] 16/3/3 |
| hybrid 0.3 | 0.8 / 0.3 / 23 ms | 0.8487 | 0.851 | 0.849 | 0.477 | +0.0046 [+0.0027, +0.0066] 15/0/7 |
| hybrid 0.3 | 0.9 / 0.3 / 23 ms | 0.8453 | 0.851 | 0.841 | 0.448 | +0.0011 [+0.0003, +0.0021] 6/0/16 |
| hybrid 0.3, hole 40 ms | 0.7 / 0.3 / 23 ms | 0.8516 | 0.843 | 0.863 | 0.551 | +0.0074 [+0.0032, +0.0121] 17/3/2 |
| hybrid 0.3, hole 40 ms | 0.75 / 0.3 / 23 ms | 0.8516 | 0.847 | 0.859 | 0.533 | +0.0075 [+0.0038, +0.0117] 15/3/4 |
| **hybrid 0.3, hole 40 ms** | **0.8 / 0.3 / 23 ms** | **0.8518** | **0.850** | **0.856** | **0.520** | **+0.0077 [+0.0041, +0.0122] 14/0/8** |
| hybrid 0.3, hole 30 ms | 0.8 / 0.3 / 23 ms | 0.8520 | 0.850 | 0.856 | 0.523 | +0.0078 [+0.0041, +0.0125] 15/0/7 |
| hybrid 0.3, hole 40 ms | 0.8 / 0.3 / 23 ms, melodia | 0.8477 | 0.838 | 0.861 | - | +0.0036 [-0.0013, +0.0093] 10/9/3 |

The chosen setting (bold) sits on a plateau, not a spike: onset threshold
0.7-0.8 and a 30-40 ms hole read +0.0074 to +0.0081 everywhere on it. Frame
thresholds 0.2 and 0.4, minimum lengths 12 and 46 ms, a confidence floor
anywhere from 0.2 to 0.4 and a cover fraction of 0.3 all moved the hybrid
by under 0.001 around their neighbours (a floor of 0.5-0.6 gives back up
to 0.0025) (the sweep is in the scratch JSON; the rows
above are the ones that decide). The onset threshold is what matters:
Basic Pitch's weak onsets on a horn stem are the comping and the bleed.

## All sets, the chosen setting beside the model on its own

WJazzD note F1 is over all 73 solos (22 tuning + 51 held out); the hand
scores are the listener's twelve; pianist precision is the seven hand-scored
pianists' pitch precision.

| variant | WJazzD F1 (P / R), n=73 | change vs CREPE | held out, n=51 | hand scores pitch F1, n=12 | Omnibook pitch F1, n=22 | Omnibook sub-eighth recall | pianist precision, n=7 |
|---|---|---|---|---|---|---|---|
| **CREPE (shipped)** | **0.8580 (0.872 / 0.847)** | -- | 0.8640 | **0.8629** | **0.7905** | **0.6604** | **0.828** |
| raw, default decode | 0.6869 (0.834 / 0.599) | -0.1711 [-0.1922, -0.1509] 1/72/0 | -0.1750 | 0.7006 | 0.6840 | 0.3604 | 0.488 |
| raw, 0.5 / 23 ms | 0.8056 (0.760 / 0.865) | -0.0524 [-0.0650, -0.0411] 4/67/2 | -0.0517 | 0.7026 | 0.7692 | 0.7445 | 0.457 |
| sky, 0.5 / 23 ms | 0.7748 (0.780 / 0.772) | -0.0832 [-0.1041, -0.0647] 7/66/0 | -0.0823 | 0.7537 | 0.7794 | 0.6888 | 0.649 |
| loud, 0.5 / 23 ms | 0.8467 (0.852 / 0.844) | -0.0113 [-0.0176, -0.0054] 17/50/6 | -0.0105 | 0.8116 | 0.7937 | 0.6923 | 0.720 |
| pick, 0.5 / 23 ms | 0.8313 (0.874 / 0.795) | -0.0267 [-0.0332, -0.0205] 11/61/1 | -0.0270 | 0.8170 | 0.7730 | 0.6093 | 0.755 |
| nvote, amp 0.4 (horns) | 0.8568 (0.871 / 0.846) | -0.0012 [-0.0019, -0.0005] 10/26/37 | -0.0011 | 0.8627 | 0.7892 | 0.6592 | 0.828 |
| hybrid 0.3, 60 ms hole, 0.8 (fill_gaps as shipped) | 0.8623 (0.870 / 0.857) | +0.0043 [+0.0032, +0.0055] 45/2/26 | +0.0042 | 0.8629 | 0.7947 | 0.6831 | 0.828 |
| hybrid 0.3, 40 ms hole, 0.5 | 0.8610 (0.847 / 0.878) | +0.0030 [-0.0001, +0.0064] 33/22/18 | +0.0034 | 0.8600 | 0.7969 | 0.7534 | 0.828 |
| **hybrid 0.3, 40 ms hole, 0.8 (chosen)** | **0.8650 (0.870 / 0.863)** | **+0.0070 [+0.0051, +0.0093] 49/1/23** | **+0.0067 [+0.0046, +0.0094] 35/1/15** | **0.8625** | **0.7976** | **0.7034** | **0.828** |

For the chosen hybrid the out-of-sample rows are:

- **WJazzD held out (51):** +0.0067 [+0.0046, +0.0094], 35 up, 1 down --
  the tuning subset read +0.0077. No sign the thresholds were fitted to it.
- **Omnibook (22):** pitch F1 0.7905 -> 0.7976, +0.0071 [+0.0046, +0.0099],
  15/0/7; sub-eighth recall 0.6604 -> 0.7034, **+0.0436 [+0.0324, +0.0573],
  21 of 22 sides up, none down** (2,603 notes under an eighth).
- **Hand scores (12, of which the 5 horns can move):** pitch F1 0.8629 ->
  0.8625, -0.0004 [-0.0010, +0.0000], 0/1/11.
- **PDF pages (3):** pitch F1 0.8664 -> 0.8704, 1/0/2.
- **Pianists:** untouched by construction (the four WJazzD pianists read
  0.8985 both ways; the seven hand-scored pianists' precision 0.828 both).

By instrument on WJazzD: trumpet +0.0058 (26 solos, 17 up / 0 down), tenor
+0.0053 (21, 15/1), alto +0.0087 (13, 10/0), trombone +0.0039 (5, 4/0),
soprano +0.0395 (3, 3/0). The hybrid added 770 notes to the 73 scored
spans (about ten a solo) and mir_eval's hits rose by 578: three of every
four notes it writes are notes the annotator wrote. Pure misses fell 3,304
-> 2,716; false positives rose 2,085 -> 2,267.

## Where the recall comes from

WJazzD recall by the reference note's performed duration (pooled over the 73
solos). The two "ceiling" columns are what a PERFECT selector between CREPE
and Basic Pitch could reach: a reference note counts if either detector hit
it, each under its own mir_eval matching.

| duration | notes | CREPE | BP raw, default | BP raw, 0.5 / 23 ms | hybrid (chosen) | ceiling: CREPE or BP 0.5 | ceiling: CREPE or BP 0.3 |
|---|---|---|---|---|---|---|---|
| under 60 ms | 3,734 | 0.489 | 0.098 | 0.597 | **0.563** | 0.668 | 0.678 |
| 60-100 ms | 11,460 | 0.830 | 0.352 | 0.855 | 0.848 | 0.902 | 0.906 |
| 100-150 ms | 9,900 | 0.914 | 0.712 | 0.924 | 0.921 | 0.952 | 0.957 |
| 150-250 ms | 5,649 | 0.917 | 0.900 | 0.925 | 0.922 | 0.955 | 0.964 |
| over 250 ms | 3,090 | 0.881 | 0.871 | 0.886 | 0.883 | 0.918 | 0.932 |
| all (pooled) | 33,833 | 0.836 | 0.568 | 0.861 | 0.853 | 0.901 | 0.908 |

The Omnibook by notated value (true matches of the time-free alignment):

| the book's value | notes | CREPE | BP raw, 0.5 / 23 ms | hybrid (chosen) |
|---|---|---|---|---|
| sixteenth-triplet or shorter | 542 | 0.611 | 0.744 | 0.679 |
| sixteenth | 1,199 | 0.690 | 0.767 | 0.729 |
| triplet eighth | 862 | 0.651 | 0.713 | 0.683 |
| eighth | 5,953 | 0.823 | 0.859 | 0.834 |
| up to a quarter | 601 | 0.839 | 0.932 | 0.842 |
| longer | 366 | 0.861 | 0.948 | 0.874 |
| **under an eighth** | 2,603 | **0.660** | 0.745 | **0.703** |

Ceiling on the book, CREPE or Basic Pitch: 0.796 under an eighth (0.801
with the 0.3 decode). A raw polyphonic line inflates the book's numbers
more than WJazzD's -- a sequence alignment rewards any note that happens
to carry the right pitch in order -- which is why the time-anchored WJazzD
table is the evidence and the book's is its confirmation.

**Reading.** A model that has never heard jazz or a Roformer stem hears 60%
of WJazzD's notes under 60 ms where CREPE's front end hears 49%, and
together they hear 67-68%. The stems carry those notes; CREPE's
segmentation drops them. That is the front end being a limit, on the short
note, in the one place the plan asked.

## The neighbour class: no

| measure | value |
|---|---|
| CREPE's `neighbour` pairs on WJazzD (73 solos) | 841 |
| ... whose reference note Basic Pitch hit at the RIGHT pitch, onset 0.3 (precision 0.57) | 126 (15%) |
| ... onset 0.5 | 100 (12%) |
| ... onset 0.8 | 26 (3%) |
| neighbour pairs, BP raw 0.5 / 23 ms (recall 0.865, above CREPE's) | 908 |
| neighbour pairs, the pitch vote (nvote, amp 0.4) | 884; F1 -0.0012 [-0.0019, -0.0005] |
| neighbour pairs, the chosen hybrid | 870 (+29 from 770 added notes) |

Where CREPE reads a semitone or a tone off, Basic Pitch almost never has
the right pitch either, and trusting it where the two disagree makes F1
worse. This agrees with the error taxonomy's frame evidence -- the misread
notes' pitch trace sits a median half a semitone off, the pitch genuinely
lay between two notes -- and says a note-level model's architecture does
not by itself decide it. **The neighbour class is not a front-end-choice
problem this bake-off can see a lever for.**

## The page (chosen hybrid, `--notation`)

Through `run_eval.notation_scores`; rhythm, value and placement only where
both pages are trusted.

| set | measure | CREPE | hybrid | change |
|---|---|---|---|---|
| hand scores (12) | rhythm | 0.8455 | 0.8413 | -0.0043 [-0.0108, +0.0001] 0/3/9 |
| | value | 0.7788 | 0.7762 | -0.0027 [-0.0074, +0.0002] 0/2/10 |
| | readability | 0.9990 | 0.9991 | +0.0002, 1/0/11 |
| | on the bar | 0.9026 | 0.9004 | -0.0022 [-0.0051, -0.0003] 0/4/8 |
| | tie rate | 0.0325 | 0.0323 | level |
| Omnibook (22) | rhythm | 0.7796 | 0.7843 | +0.0046 [-0.0023, +0.0110] 14/7/1 |
| | value | 0.7113 | 0.7197 | +0.0084 [+0.0028, +0.0141] 15/4/3 |
| | readability | 0.9979 | 0.9975 | -0.0004, 1/3/18 |
| | on the bar | 0.8571 | 0.8600 | +0.0030 [-0.0008, +0.0063] 12/4/6 |
| | tie rate | 0.0403 | 0.0419 | +0.0015 [+0.0001, +0.0032] |
| PDF pages (3) | rhythm | 0.8211 | 0.8187 | -0.0024, 0/2/1 |

Mixed and small: the book's page gains value (its sixteenths are notes we
now have), three of the listener's five horn pages lose a little rhythm and
four sit slightly less on the bar (mean -0.0022) -- a transcriber who
leaves an ornament out is not wrong, and a note we now write is then an
extra. Readability does not move. The raw model on the page (onset 0.8) is
what the hybrid avoids: value -0.0895 on the hand scores, tie rate
doubled.

## What did not work

- **Basic Pitch as the line, any way it is reduced.** Loudest-per-cluster
  is the best at -0.0113 on WJazzD (17 up, 50 down), skyline -0.083,
  `pick_line` -0.027; every reduction loses 0.046-0.11 of hand-score pitch
  F1 and 0.07-0.18 of pianist precision against the oracle line (0.37
  raw). Its
  precision on a horn stem is the comping: raw at onset 0.5 reads recall
  0.865 above CREPE's 0.847 at precision 0.760.
- **The model's defaults.** 128 ms minimum length: under-60 ms recall 0.098.
  `melodia_trick`: worse in every hybrid (it grows notes without an onset,
  and on a stem those are the bleed).
- **Permissive onsets in the hybrid.** Onset threshold 0.4: -0.0103, 16 of
  22 tuning solos down. The hole gets filled with the band.
- **The pitch vote.** Covered above: -0.0012, neighbour pairs up.
- **The piano's 60 ms hole.** Keeps out the notes in question; 40 ms adds
  about 0.003 on both the tuning subset (+0.0046 -> +0.0077) and the full
  set (+0.0043 -> +0.0070).

## Verdict on A2 step 2 (fine-tune)

The kill criterion in docs/roadmap.md: *beat CREPE on WJazzD note F1 over
the dev split AND on the Omnibook's sub-eighth recall, without costing
pianist precision.*

- **Basic Pitch alone fails it** on the first clause in every form
  (best -0.0113) and on the third (pianist precision down in every form).
- **Basic Pitch as a hole-filler passes all three already, untrained**:
  WJazzD +0.0070 [+0.0051, +0.0093] (49 up, 1 down; held out +0.0067),
  Omnibook sub-eighth recall +0.0436 [+0.0324, +0.0573] (21/0/1), pianist
  precision unchanged.

So the bake-off answers the roadmap's condition ("the fine-tune only if
the bake-off shows the front end, not the stems, is the limit") in two
halves:

1. **Short notes: the front end IS a limit.** The ceiling says a perfect
   selector over CREPE and an untrained note model would reach WJazzD recall
   0.908 (pooled; CREPE 0.836) and 0.678 under 60 ms (CREPE 0.489). The
   hybrid takes a quarter of the first gap and two fifths of the second
   (0.853; 0.563) with hand-set gates.
   What stands between the two is SELECTION on a stem that carries the band
   -- exactly what a model fine-tuned on Roformer stems with WJazzD's labels
   would learn, and what a hand gate approximates.
2. **Neighbour pitches: no evidence for a fine-tune.** The untrained model
   hits the right pitch on 3-15% of CREPE's neighbour errors and a vote
   costs F1. A fine-tune should not be sold as the fix for the neighbour
   class; if it moves it, that is a bonus to measure, not the goal.

**Recommendation: go, in two moves, with the bar raised.**

- **First, ship the hybrid** (horns only, pianists untouched) -- it is the
  cheapest measured gain on the table. It needs the listener's approval for
  a dependency: onnxruntime in a pipeline group (it is in `omr` today, and
  homr runs on it under Smart App Control on this machine), the 230 KB
  `nmp.onnx` vendored with Basic Pitch's Apache-2.0 NOTICE, and a
  numba-free port of `output_to_notes_polyphonic` (about 100 lines of numpy
  and `scipy.signal.argrelmax`) -- the `basic_pitch` package itself imports
  librosa and resampy at module import and can never be imported on
  Windows. Resampling to 22,050 Hz would move from librosa's soxr to
  torchaudio, so the hybrid must be re-measured once ported, and CREPE's
  cache keys must not move (a new `TranscribeConfig` field that dumps
  nothing at its default, the `timing` / `line` pattern).
- **Then fine-tune, against the HYBRID, not against CREPE.** The untrained
  model already clears the CREPE bar as a hole-filler, so a fine-tune that
  merely clears it again has bought nothing. Kill criterion for step 2:
  beat the hybrid on WJazzD note F1 over the dev split (0.8650) AND on the
  Omnibook's sub-eighth recall (0.7034), without costing pianist
  precision; split by performer; never a test-split track. Its head-room
  is the gap to the ceiling above (recall 0.853 -> 0.908 on WJazzD), and
  its scope is onsets of short notes on horn stems. Basic Pitch's own
  architecture is the natural starting point (small, open weights and
  training code, Apache-2.0) and would keep the product's runtime the same
  as the hybrid's.

## Reproducing

    # Windows: the manifest (seconds)
    .venv\Scripts\python.exe scripts/frontend_bakeoff.py manifest --out <scratch>
    # WSL: inference once, then one decode per parameter set
    ~/bakeoff/.venv/bin/python scripts/bakeoff_basic_pitch_wsl.py infer --manifest <scratch>/manifest.json
    ~/bakeoff/.venv/bin/python scripts/bakeoff_basic_pitch_wsl.py decode --manifest <scratch>/manifest.json \
        --out <scratch>/bp-o80-f30-m23-nomel.json --onset 0.8 --min-ms 23 --no-melodia
    # Windows: CREPE's card against the pins, then the chosen hybrid with its page
    .venv\Scripts\python.exe scripts/frontend_bakeoff.py score --out <scratch> --check --notation \
        --bp <scratch>/bp-o80-f30-m23-nomel.json --shift 0.004 --variants hybrid:0.3:0.04

`--subset tuning --wjazz-only` restricts a run to the declared tuning
subset. Everything written is under `<scratch>` or `~/bakeoff`: the notes
are derived from commercial recordings and never enter the repo.
