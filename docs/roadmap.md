# Roadmap: measurement first, then accuracy, then the first run

2026-09-29. Written at 0.3.0, when the listener asked where the product
goes next and offered to pair audio with the ~270 PDF transcriptions they
had given the project. The recommendation, and the order of this document,
is that **the benchmark is now the constraint, not the pipeline**: every
quantizer rule from R27 on was chosen on the same 34 human pages (the
listener's twelve and 22 Omnibook sides), and several of those decisions
rested on differences a sign test cannot separate from noise.

Where the numbers stand (pinned, `tests/regression/real-audio-baselines.json`):

| measure | value | n |
|---|---|---|
| WJazzD note F1 (audio against audio) | 0.858 | 73 solos |
| WJazzD beat F1 | 0.942 | 73 |
| hand scores, note F1 (audio against notation) | 0.537 | 12 |
| hand scores, placement on the bar | 0.903 | 12 |
| Omnibook pitch F1 / rhythm / value | 0.790 / 0.780 / 0.711 | 22 |
| pianists, pitch F1 (oracle line / CREPE line) | 0.840 / 0.787 | 7 |
| readability (a human writes 0.995) | 0.996 | 85 notations |

## 1. Data: what to pair, and how

Two wishlists, generated from the database and the pdf2musicxml manifests,
live in `benchmark/` (gitignored; they carry WJazzD metadata, which is
ODbL):

- **`benchmark/audio-wishlist-wjazzd.csv`** -- the WJazzD recordings with no
  local audio, with album, label, release and recording dates and MusicBrainz
  ids, so the take found is the take annotated. WJazzD holds 456 solos on 344
  tracks; the benchmark has 49 tracks (74 solos, ~35k notes). Missing: 295
  tracks, 379 solos, 165k notes. The gaps are not random:
  - **slow tempo**: 3 SLOW solos held, no MEDIUM SLOW; 67 missing (D16);
  - **swing and traditional era**: none of the 96 held;
  - **clarinet, cornet, vibes, baritone**: none held.
  Tier A (60 tracks, 77 solos) is the slow tracks and the ones that are also
  in the PDF corpus.
- **`benchmark/audio-wishlist-transcriptions.csv`** -- the 275 PDF
  transcriptions (222 vector, 53 scans), none paired yet. Tier A (49):
  14 that WJazzD annotated too (a name match; the take must be checked),
  ~24 ballads (many guessed from the title -- 152 pages print no tempo), and
  16 piano or vibes pages (ten Bud Powell, written for alto).

Both lists carry a `split` column (E2): 12 of the 49 tier-A pages and 17 of
the 60 tier-A WJazzD tracks are TEST, scored only at a release.

**Pairing.** A PDF page is paired by putting its recording beside its
`.musicxml` in `benchmark/Transcriptions_Other/musicxml/` under the same base
name. `scripts/locate_scores.py --folder Transcriptions_Other/musicxml`
places the score by content (no span to draw) and refuses a wrong take below
the coverage floor. Pass `--stem piano --ensemble trio` (with `--file`) for
a pianist's page. A WJazzD recording goes into `benchmark/wjazzd/` as
before; `score_wjazz.identify_all` finds its solos by content.

**The first three, from audio already on disk (2026-09-29).** Six pages were
believed to be recordings already in the benchmark (`figure_prior.OVERLAP`).
Copied beside their pages and located, three placed: Parker's Embraceable
You (91% of the page lined up), Dexter Gordon's Cheese Cake (91%) and Wayne
Shorter's Gingerbread Boy (76%), all silver, all dev. Three were refused as
other takes: Moose The Mooche (32%) and Scrapple From The Apple (26%)
against the Omnibook's sides, Joy Spring (47%) against WJazzD's. Silver
means: pitch F1 0.867, note F1 0.535, rhythm 0.821, value 0.762, placement
0.712, over 3.

They already show what a triple is for. The bar-line trace puts Cheese Cake
a beat off the page from bar 84, and WJazzD's own trace of the same solo
puts it a beat off from bar 84 too: two independent references agree, so
the slip is OUR grid's (D33's kind). Gingerbread Boy's two-beat step sits
exactly on the page's bar 102, which the OMR filled with six beats of 4/4:
the page's error, not ours. A step on an OMR page is worth checking against
the page's own unfilled bars before it is charged to the grid.

**What each pair buys.**

| pair | answers | the only source of |
|---|---|---|
| WJazzD audio | did we hear it (onsets in seconds) | training-grade note labels |
| PDF page + audio | would a human write it this way | a notation benchmark at scale |
| WJazzD + a page of the SAME take (a "triple") | how a human writes a performance, with no hearing error in the way | a quantizer measured alone against a human page (D36 took the old one away) |

## 2. Metrics

Built before the new pages are scored, so the pages judge the next change
instead of being spent on tuning it.

### E1. Uncertainty on every change -- DONE 2026-09-29

`run_eval` compared against the pins track by track and printed only the
movement. It now also prints, per set and measure, the paired change over
tracks (`swingscribe.evaluation.paired_change`): mean delta, a 95% bootstrap interval resampled by recording (the
three So What solos are one recording, not three draws), tracks up / down /
level, and an exact sign test. Example of why: R33's prior read +0.007 on the
hand scores with 7 of 12 pages up -- a two-sided sign test puts 7 of 12 at
p = 0.77. `--against card.json` does the same between two runs, for A/B
experiments under an environment override.

### E2. A locked test set -- DONE 2026-09-29

Every track already in the benchmark is dev: it has been looked at. Every
track added from now on is assigned dev or test by a salted hash of its tune
title, so all versions of one tune (and every soloist on one recording) land
on the same side. Test tracks are held out of the ordinary run and scored
only by `run_eval --test`, against their own pins, at a release. **The
figure prior is counted only from pages that no benchmark run scores**:
test-split pages are left out of `figure_prior.py build`, as the pages whose
recording is already in the benchmark (`OVERLAP`) always were.

Frozen in `tests/regression/split.json`: 153 dev names; 79 of the 275 pages
and 81 of the 295 missing WJazzD tracks fall on the test side. Rebuilding
the prior without the test pages (245 -> 177 pages counted) moved 9 of
2,749 pins by 0.002-0.004 and no summary mean past 0.0001
(docs/figure-prior.md).

### E3. Reference tiers -- DONE 2026-09-29

PDF pages are OMR readings, not hand scores, and are scored as their own sets
with their own means, never folded into the listener's twelve or the
Omnibook:

- **silver** -- a vector PDF whose printed noteheads were counted, with at
  most 5% of them unread, at most 5% of read notes unprinted, and at least
  90% of bars filling their signature (170 of the 222 vector pages);
- **bronze** -- everything else: scans (no printed count; the pitches are
  the engines' alone) and vector pages that miss a gate.

The gates were set from the pages' own reading quality, before any page was
scored, and must not be moved to make a score look better.

### E4. Edit cost per 100 notes -- PLANNED

The number a user feels: the insertions, deletions, pitch fixes, rhythm fixes
and bar shift that turn our page into the human's, from the existing
time-free alignment. It folds pitch F1, rhythm, value and placement -- four
numbers with coverage caveats today -- into one. MV2H (McLeod and Steedman,
2018) is the published joint measure for audio-to-score transcription and is
the outside cross-check. New scoring beside mir_eval: needs the listener's
sign-off (CLAUDE.md).

### E5. Does confidence point at the errors -- PLANNED

The share of wrong notes among the least-confident 10% and 20% of notes. The
roll already shades by confidence (AUC 0.830 against 302 erasure labels); a
better curve makes review cheaper even when F1 does not move.

### E6. Stratified means -- PLANNED

Every mean also by tempo class, era, instrument and notated value. A mixed
mean is how the ballad gap (D16) stayed invisible.

## 3. Accuracy research, ranked

### A1. Hearing against writing, on the triples

Feed WJazzD's human onsets (not ours) through swing, quantize and notate, and
score the page against the human page of the same take. Every difference is
the notater's. This is the instrument the quantizer has lacked since D36
showed WJazzD's tatum layer is an algorithm's. Candidates today: the 14 name
matches in the PDF corpus (Cheese Cake, Hawkins' Body and Soul, Joy Spring,
Punjab, Embraceable You, ...) plus the six Omnibook sides already under
`benchmark/wjazzd/`. *Needs*: a take check per pair; no new code in the
pipeline. *Kill*: none -- it is a measurement.

### A2. A note-level front end for horns

The leading error classes are ones no threshold reaches (the gate sweeps are
on the record): notes under an eighth are 27% of the Omnibook's notes and 54%
of its outright misses, and semitone `neighbour` errors are 38% of its
deficit. On the worst WJazzD solos the misread notes' pitch trace sits a
median half a semitone off -- the pitch genuinely lay between two notes
(scoops, falls, short notes), which is a decision about the whole note.

1. **Bake-off, no training.** Run a pretrained note-level model (Basic Pitch
   is small and ships an ONNX graph; onnxruntime is already in the `omr`
   group) over the cached stems and score it through `run_eval` and the error
   taxonomy, by notated value.
2. **Fine-tune** a small onset-and-pitch head on the Roformer stems with
   WJazzD's labels, so it learns our separation's bleed. 35k labelled notes
   today, ~200k with the full WJazzD audio; split by performer, and never on
   a test-split track.

*Kill*: it must beat CREPE on WJazzD note F1 over the dev split AND on the
Omnibook's sub-eighth recall, without costing pianist precision. *Needs*: new
dependencies (the listener's call), and a decision on weights trained on
commercial recordings (the MuScriptor precedent: its own group, never core).

### A3. Ballads

R31's ballad grids are off because no human ballad page existed. The corpus
has ~24; paired, they judge R31 and the slow-tempo notation D16 said the
benchmark could not see.

### A4. Pianists

Ten Bud Powell pages would take the pianist set from 7 to ~17, on 1940s-50s
piano the piano model (trained on clean recordings) has not heard. Line
selection (issue #8) is still the pianist's leading error.

### A5. The swing era and the clarinet

Nothing from before bebop is measured, in either benchmark. The swing
estimator's floors (milestone M4) and the lag rule (R29) were set on bebop and hard
bop; a lighter swing and a two-beat feel are a different population.

## 4. The first run

### O1. Show the page in the app

The product is a page, and today it is seen only after Export, in MuseScore.
Verovio (a Python wheel, LGPL) renders MusicXML to SVG on the server, which
keeps the frontend free of JavaScript dependencies. A dependency to approve.

### O2. Route the ensemble and the lead stem automatically

From which stem carries the span's energy, as a suggestion with its reason
and a one-click override. The guide's troubleshooting has to say "a piano
solo is not getting the piano model": the default is wrong for every piano
solo. The 108 sidecars the listener set (11 trio) are the test. A suggested
transposition from an instrument classifier trained on WJazzD's labels comes
after (published on exactly this data: Gomez, Abesser and Cano, ISMIR 2018).

### O3. Propose the solo spans

A new user's first job is finding A and B on a waveform. Propose spans where
the lead stem's activity changes, snapped to chorus boundaries on the bar
grid, from the quick htdemucs separation the batch already locates with.
WJazzD's located solos are the ground truth.

## 5. Ruled out

**Tuning.** Off-A440 recordings do not explain the semitone errors: over 175
cached reviews the median tuning offset is 6.6 cents, 9 exceed 20 cents and
none exceed 30 (circular mean of CREPE's pitch over confident in-note frames).

## 6. Order

1. E1-E3 (done 2026-09-29), while the listener gathers tier-A audio.
2. Pair and locate the tier-A pages; A1 on the triples; A3 and A4 fall out
   of the new pages with no pipeline change.
3. O1 and O2, which need no new measurement.
4. A2's bake-off; the fine-tune only if the bake-off shows the front end, not
   the stems, is the limit.
