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
a beat off the page from bar 83 (the page's pickup is bar 0), and WJazzD's
own trace of the same solo puts it a beat off at the same notes (its bar 84): two independent references agree, so
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

### E4. Edit cost per 100 notes -- DONE 2026-09-30

`benchmark.edit_cost`, off the same alignment rhythm and value read
(docs/metrics-e4-e6.md): the insertions, deletions, pitch, position, value and
bar edits that turn our page into the human's, per 100 reference notes.
Hand scores 55.3 (n=12), Omnibook 68.1 (22), silver pages 56.3 (3). Hearing
edits (insert, delete, pitch) are 40-44% of them; notation edits with no
hearing edit beside them are 19-24%; the 35-38% between are notation damage
next to a hearing edit, unassigned. Pianists: the oracle line costs 52.0
against the CREPE line's 60.1 (paired -8.1 [-12.4, -3.4], 6 of 7). MV2H, the
outside cross-check, is a Java download still to approve.

### E5. Does confidence point at the errors -- DONE 2026-09-30

WJazzD, n=73: confidence AUC 0.646 per solo, 0.637 pooled; the
least-confident fifth of notes holds 39% of the 4,320 false positives -- about
2x chance, so shading helps review but is not yet strong. The listener's
erasures only match on the stems they were made on (132 of 141 on today's
Roformer stems, 1 of 235 on the Demucs-era stems): re-anchor the old labels
before issue #8 trains on them.

### E7. Outside yardsticks -- DONE 2026-09-30

- **MV2H** (docs/mv2h.md): hand scores 0.876, Omnibook 0.734 non-aligned,
  over all 44 notation pages; an upstream bug (meter zeroed after the first
  alignment in `Main -a`) found and worked around.
- **The Rhythm Perceiver's per-beat measure** (docs/beat-signature.md): 0.577
  on the 21 Omnibook sides whose bar lines held against the paper's 0.53 on
  its easier 60% -- level with the published learned system, not clearly
  past it; its onsets are better (0.83 against 0.785).
- **The head-to-head** (docs/head-to-head.md): ready; waits on the
  listener's AnthemScore 6.3 exports.

### E6. Stratified means -- DONE 2026-09-30

Printed and in `--json`, never pinned. The ballad gap is one line on the
card: 3 of the 73 scored WJazzD solos are SLOW and none MEDIUM SLOW.

## 3. Accuracy research, ranked

### A1. Hearing against writing, on the triples -- DONE 2026-09-30

docs/triples.md. Eight triples (six Omnibook sides WJazzD annotated, KC Blues
included, and the silver pages Embraceable You and Cheese Cake), each notated
three ways against the same page cropped to the solo by content: (a) WJazzD's
onsets on WJazzD's grid, (b) the same onsets on our grid, (c) our notes. The
page's distance is mostly WRITING:

| | writing 1-(a) | grid (a)-(b) | hearing (b)-(c) |
|---|---|---|---|
| rhythm | 0.185 | 0.006 | 0.034 |
| value | 0.218 | 0.000 | 0.052 |

Only 12% of the notes we misplace on human onsets sounded nearer the page's
place: the rest is transcriber convention (the swung "and" written on the
beat, the laid-back beat, anticipations). Largest classes, as a share of
intervals: half-beat displacements 5.7% (partly OMR), triplets read binary
3.3% (the page writes 13.2% tuplets, we write 4.1%), a ballad's sixteenths as
eighths 2.3%, a lone laid-back downbeat on the "e" 2.1%. Every shipped rule
switched off does worse on (a) or level; `legato_cap` is worse on all 8. The
first human ballad page (Embraceable You, 72 bpm) favours R31 on all four
measures -- one page, so R31 stays off until A3's pages arrive.

Read beside E4: by EDIT COUNT hearing is the largest block; by RHYTHM on the
notes both sides hold, writing is. Both levers are real, and they need
different work.

### A2. A note-level front end for horns -- step 1 DONE 2026-09-30

docs/frontend-bakeoff.md. Basic Pitch (Apache-2.0, 230 KB ONNX), run in WSL
on the harness's own stems:

- **As the line it loses in every form** (best -0.011 WJazzD note F1;
  pianist precision falls 0.07-0.18).
- **As a horn hole-filler it passes the kill criterion untrained**: CREPE's
  line plus Basic Pitch notes where the line has a 40 ms hole
  (`corroborate.fill_gaps`, onset 0.8): WJazzD note F1 0.8580 -> 0.8650,
  +0.0070 [+0.0051, +0.0093], 49 up / 1 down over 73 (+0.0067 on the 51 not
  used for tuning); under-60 ms recall 0.489 -> 0.563; Omnibook sub-eighth
  recall 0.660 -> 0.703 (21 of 22 up). Hand-score rhythm -0.004, not decided;
  pianists untouched by construction.
- **It is not the neighbour fix**: it has the right pitch on 3-15% of CREPE's
  841 semitone errors, and a pitch vote costs F1.
- **The ceiling**: CREPE and Basic Pitch combined perfectly would reach
  WJazzD recall 0.908 against 0.836 -- the fine-tune's target.

**Step 1.5 SHIPPED 2026-09-30** (commit 14d7e7e): a numba-free port on
onnxruntime, the graph vendored, on by default for every non-pianist.
Product path: WJazzD note F1 0.8580 -> 0.8651 (52 up / 2 down over 73),
Omnibook pitch F1 +0.0070, pianists unchanged; the listener's horn pages
gain ornaments the transcriber left out (edit cost +0.80 per 100).

**Second opinions tried on top** (docs/kong-bakeoff.md): the FiloSax sax
CRNN adds +0.0026 over the hybrid on saxophones as a second hole-filler
(Omnibook sub-eighth recall +0.033), and loses as a line; trained on
non-commercial data, so an opt-in at most, pending the authors' terms.

**Step 2, fine-tune**, has to beat the hybrid (0.8651), not CREPE. The
ceiling for a perfect choice between CREPE and a note model is recall 0.895
to 0.908 against the hybrid's 0.863 -- a modest prize. The fine-tune's real
value is a model trained on OUR stems that could ship without licence
questions; it needs the missing WJazzD audio (section 1).

### A3. Ballads

R31's ballad grids are off because no human ballad page existed. The corpus
has ~24; paired, they judge R31 and the slow-tempo notation D16 said the
benchmark could not see. The first one (A1) already leans toward turning R31
back on.

### A4. Pianists

Ten Bud Powell pages would take the pianist set from 7 to ~17, on 1940s-50s
piano the piano model (trained on clean recordings) has not heard. Line
selection (issue #8) is still the pianist's leading error. Edwards et al.'s
augmented Kong checkpoint (CC BY 4.0) was measured 2026-09-30 through a new
loader and reads LEVEL on the 11 pianists (docs/kong-bakeoff.md): the
pianist's problem is choosing the line, not hearing the notes.

### A5. The swing era and the clarinet

Nothing from before bebop is measured, in either benchmark. The swing
estimator's floors (milestone M4) and the lag rule (R29) were set on bebop and
hard bop; a lighter swing and a two-beat feel are a different population.

### A6. Learn the transcriber's reading -- NEW

A1 says what remains on the page is convention, not timing, and every hand
rule R27-R33 is small and noisy on eight pages. The published direction
(docs/landscape.md: the Rhythm Perceiver, ICASSP 2026) predicts a per-beat
figure from evidence; ours would sit inside `choose_grid` as a re-ranker over
the candidates it already enumerates, with the counted prior as its class
prior and every note-keeping guard intact. First the cheap test: score our
quantizer with the paper's per-beat "beat signature" accuracy on the Omnibook,
where the paper reads 0.53 on its easier 60% of tracks. Training data is the
constraint: WJazzD onsets aligned to paired PDF pages (A1's triples at scale)
and our transcriptions of the tier-A pages; evaluation is the triples' (a)
row, the listener's pages and the Omnibook, never Flex-Q.

**2026-09-30:** the cheap test is done (E7): level with the published system,
so a learned re-ranker is how to get past it. Four more hand rules were tried
on the triples and none moved the pages (docs/writing-round2.md); the
half-beat displacements turned out to be ANTICIPATION -- the page writes the
note earlier than it was played, and nothing in the timing says so. Hand
rules are exhausted; the model's inputs exist (onsets, beats, and the Kong
activations kept under `C:\Users\lkmcg\swingscribe-research\kong-activations`),
and its targets are named (triplets right 25% of the time on the Omnibook,
sixteenth runs 26%). The training data is the paired pages.

## 4. The first run

### O1. Show the page in the app -- DONE 2026-09-30

A Page view renders exactly the MusicXML Export would write (one code path),
server-side with Verovio 6.3.0 (LGPL-3.0, loads under Smart App Control,
ships in the portable folder), and redraws on every change that changes the
page. Next: link the page to the playhead (Verovio's timemap), and show the
hand score's bars beside ours when one is loaded.

### O2. Route the ensemble and the lead stem automatically -- DONE 2026-09-30

`routing.suggest` (docs/routing.md): 111 of 111 benchmark spans right on the
Roformer stems, no horn span or window ever called trio; nothing suggested on
htdemucs_6s, from a partial stem set or from under 15 s of melody. The GUI
shows it beside the Ensemble menu with its reason and Apply/Keep, only on a
track with no ensemble of its own, and never writes anything by itself.
Open: a labelled bass solo, a solo-piano record and a vibes/organ lead.

### O3. Propose the solo spans -- DONE 2026-09-30 (research and GUI)

`solo_spans.propose` (docs/solo-spans.md) from the quick htdemucs_6s stems
and the bar grid: a span edge within two bars of 71% of WJazzD's solo starts
and 73% of its ends (chance 0.12), 7.5 boundaries a recording. Next: "Find
the solos" on the Overview, bands a click turns into A and B, and a log of
what the listener does with each proposal (the labels the benchmark lacks)
-- all shipped 2026-09-30.

### O4. Chord symbols on the page -- first version DONE 2026-09-30

Every human transcription service and every lead-sheet competitor delivers
the changes; we deliver none (docs/landscape.md section 6). Start from changes
the listener supplies (typed, or read from a lead sheet's MusicXML
`<harmony>`), snapped to the bar grid we already trust and written as
`<harmony>`; Verovio and MuseScore render them. Recognition comes later, and
only once measured on jazz vocabulary (WJazzD's per-beat chords are the
ground truth). Shipped: typed changes, placed on the form, transposed with the
part, drawn in the Page view, accepted by MuseScore. Next: import a lead
sheet's `<harmony>`, then recognition.

### O5. Pin a beat, re-derive the rest -- NEW

Cheese Cake's page and WJazzD's annotation both show our grid slipping a beat
at bar 83-84; the downbeat is one click but a mid-solo slip is not. Let the
listener pin a beat and have `repair_beats` re-derive the grid around it.

## 5. Ruled out

**Tuning.** Off-A440 recordings do not explain the semitone errors: over 175
cached reviews the median tuning offset is 6.6 cents, 9 exceed 20 cents and
none exceed 30 (circular mean of CREPE's pitch over confident in-note frames).

**Basic Pitch as the line**, and as a pitch voter (A2).

**Loosening the tuplet gate, sixteenth triplets, `legato_cap`** -- re-measured
on the triples' human onsets, all worse or level (A1). Four more writing rules
(late downbeat, isolated lag, tuplet with a pushed last note, hold to the
beat), default off (docs/writing-round2.md).

**Banquet** query-by-audio separation: -0.290 note F1, 16 of 16 solos down
(docs/banquet-trial.md). **Edwards' piano checkpoint**: level (A4).

## 6. Order

1. Done 2026-09-29/30: E1-E7, A1, A2 steps 1 and 1.5 (shipped), O1-O4.
2. **Pair and locate the tier-A pages** (the listener's audio). Every page
   is more ground truth for everything above, every page WJazzD also
   annotated is a triple, and the paired pages ARE A6's training data. This
   is now the constraint on accuracy.
3. **A6, the learned re-ranker** inside `choose_grid`, trained on the paired
   pages and judged on the triples, the listener's pages and the Omnibook.
   The largest remaining lever on the page.
4. **The head-to-head** once the listener has AnthemScore 6.3 exports.
5. **O5 and the page view's next steps**: pin a beat and re-derive the grid;
   link the page to the playhead; show the hand score's bars beside ours;
   import a lead sheet's changes.
6. **A2 step 2** (fine-tune on our stems) once the missing WJazzD audio is
   in -- chiefly for a shippable model, the recall prize is modest.

## 7. Decisions waiting on the listener

- **The head-to-head**: run the spans through AnthemScore 6.3's local trial
  following docs/head-to-head.md (Klangio and Songscription would mean
  uploading commercial recordings -- the listener's call).
- **The FiloSax sax CRNN** as an opt-in: worth +0.0026 over what ships;
  its weights are trained on non-commercial data, so it waits on the
  authors' terms (docs/kong-bakeoff.md says what to ask Riley and Dixon, if
  the listener wants to write to them).
- **Per-span ensembles**: the sidecar holds one ensemble per track, so a
  record with a horn solo and a piano solo can only be right for one.
