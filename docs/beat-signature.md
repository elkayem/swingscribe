# Our pages on the Rhythm Perceiver's beat-signature measure (A6, the cheap test)

2026-09-30. `swingscribe/beat_signature.py`, `scripts/beat_signature.py`,
`tests/test_beat_signature.py`. Code at 0049aee; the note and grid caches
are the harness's, copied that morning before anything re-ran.

**The answer.** On the paper's own headline measure our shipped pipeline is
**level with the published learned system, a little ahead, not past it**:
0.573 [0.539, 0.604] of beats right over all 22 located Omnibook sides and
0.577 [0.544, 0.607] over the 21 whose bar lines held, against the Rhythm
Perceiver's 0.53 on the "easy" 60% of its Omnibook test set. On the harsher
analogue of that subset, the 13 slowest sides, we read 0.536 [0.493, 0.576]:
level. The paper places single onsets better than we do (onset F1 0.83
against our 0.785 on the same 21 sides). A learned per-beat classifier is
**not needed to catch up** with the publication. It is the only lever
measured here that is big enough to **move past** it. Given WJazzD's human
onsets on WJazzD's human beats, our quantizer writes only 0.61 of the
triples' beats the way the page does. Hearing and the grid together cost
just 0.06 more. On this measure, writing costs about six times what hearing
costs.

## 1. The measure

Shanin, Riley and Dixon, "Audio-to-Score Jazz Solo Transcription with the
Rhythm Perceiver", ICASSP 2026
([PDF](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2026/ShaninEtAl-ICASSP2026.pdf)).
The module docstring quotes the definition. It is paraphrased here:

- **Twelve bins per beat** (section 3, "Score and Rhythm Tokenization"). A
  note's first bin is an ONSET token and its later bins are TIE tokens. A bin
  between notes is a REST token. The twelve tokens of one beat, pitch
  dropped, are its **beat signature** (their Fig. 2 draws four, such as
  `O T O T O T O T T T T T`). Twelve bins can hold sixteenths (3 bins),
  triplet eighths (4), sixteenth triplets (2), triplet quarters (8) and
  everything built from those. A 32nd (1.5 bins), a dotted sixteenth (4.5) or
  a quintuplet cannot be held.
- **Classes** (section 3). The classes are the signatures counted on
  Filosax's pages. The 42 with at least 30 beats are kept. Everything else
  is filed as "rare", and a beat that cannot be built on the bins is filed as
  "unsupported". That makes 42 + 2 classes, and the rhythm branch predicts
  one per beat.
- **Rhythm accuracy** (section 4, Tables 1-2) is reported as "beat-level
  rhythm accuracy", with no formula given. The reading taken here is **the
  share of beats whose class equals the reference's**.
- **Which beats.** The model runs on madmom's beats, tracked on the separated
  accompaniment. The Omnibook reference is aligned to hand-placed downbeats
  (Riley and Dixon, SMC 2024, section 3.1). Section 4 reports every Table 2
  number except insertion and deletion on an "easy" subset: the 60% of the
  test set whose automatic beats held. The other 40% is described as fast
  tempos, poor recordings and busy accompaniment. On the easy tracks,
  predicted beat *i* is reference beat *i*.
- **The reference** is LORIA's Omnibook MusicXML (Déguernel et al., the
  corpus SMC 2024 section 3.1 aligned). That is the same file our Omnibook
  set scores against.

### How each detail is implemented, and the alternatives

| detail | taken here | alternative, and its number (Omnibook, all 22) |
|---|---|---|
| a beat is right when | the two **classes** agree | the exact twelve tokens agree: **identical to three decimals** (0.573) |
| the 42 classes | the 42 commonest signatures of the 189 human transcription pages under `Transcriptions_Other` (the figure prior's corpus and filters; the test split and benchmarked recordings dropped). They cover 99.4% of its 51,404 beats; 30 reach 30 beats | Filosax is not here. Only 0.2% of the Omnibook's beats fall outside the 42 (0.3% of the hand scores', 1.0% of the triples'), so the choice cannot move the number |
| tie against rest | distinct tokens, per the text: an eighth and an eighth rest is not a quarter | **onset pattern only**: 0.659 [0.624, 0.689] |
| our beat for their beat | from the pitch-matched notes: our position minus theirs, rounded to a whole beat, taking the commonest shift among the 7 matches either side (the difference trace's window). This emulates "aligned on the ground-truth beats" wherever our grid slipped | **one shift for the whole page**: 0.573 [0.540, 0.604]. The two differ only on Blues For Alice (0.438 local, 0.428 global), the one side whose grid slips |
| which beats | every reference beat from its first matched note to its last, rests included | no alternative computed |
| mean | pooled over beats, bootstrap resampling PAGES | mean of per-page accuracies: 0.560 [0.523, 0.594] |
| onset F1 | exact position in the aligned beat, pitch ignored (section 4 reports it at zero tolerance), counted on positions so a 32nd still counts | none |

Both sides merge ties before tokenizing (`benchmark.notation_notes`, the
score parsers), so a tied note is a run of TIE bins. A chord is one onset.
A note held under the next onset ends at that onset. A grace note carries
no duration and adds no onset of its own. A double-time page is halved to
true quarters, as every notation scorer does.

## 2. The numbers

Each of our pages is built exactly as `run_eval` builds the page it scores
(`run_eval.notate_run`, from the cached notes and grids). The per-page
placement this script recomputes matches the pinned card to four decimals.

| set | n pages / beats | beat accuracy, pooled | per-page mean | onsets only | onset F1 (P / R) | pages above 0.53 |
|---|---|---|---|---|---|---|
| **Rhythm Perceiver, Omnibook easy 60%** (paper) | ? | **0.53** | | | **0.83** | |
| Perceiver without rhythm supervision (paper) | ? | 0.48 | | | 0.81 | |
| CRNN + qparse (paper) | ? | 0.18 | | | 0.48 | |
| Rhythm Perceiver, Filosax test (paper, in-domain) | compositions 46-48 | 0.87 | | | 0.93 | |
| **Omnibook, all 22** | 22 / 6,111 | **0.573** [0.539, 0.604] | 0.560 [0.523, 0.594] | 0.659 | 0.780 (0.803 / 0.758) | 17 / 22 |
| Omnibook, bar lines held | 21 / 5,917 | **0.577** [0.544, 0.607] | 0.566 [0.528, 0.598] | 0.664 | 0.785 (0.809 / 0.762) | 17 / 21 |
| Omnibook, slowest 60% (115-214 bpm) | 13 / 3,145 | **0.536** [0.493, 0.576] | 0.529 [0.476, 0.574] | 0.617 | 0.750 (0.762 / 0.738) | 8 / 13 |
| the listener's hand scores | 12 / 3,094 | 0.598 [0.568, 0.627] | 0.594 [0.559, 0.628] | 0.692 | 0.819 (0.792 / 0.847) | 10 / 12 |

**Bar lines held** is the harness's own placement verdict. It needs two
things: the commonest beat difference is none (`on_the_bar`, 0.777-0.924
here), and the difference trace is one steady run with no step. Blues For
Alice is the one side out (4 steps). This is the direct analogue of "the
automatic beats held", so it is the headline comparison. **Slowest 60%**
covers the paper's other stated criterion, fast tempo. It is not a gentle
subset for us: four of our five lowest sides are among the slowest (KC
Blues 0.308 at 115 bpm, Blues For Alice 0.438, My Little Suede Shoes 0.448,
Laird Baird 0.487), and nothing here says why.

### The triples: whether hearing or writing loses the beats

These are the eight triples of docs/triples.md: six Omnibook sides and two
OMR pages, each page cropped to the annotated solo, all eight trusted, 1,482
beats. Rows (a), (b) and (c) add one source of error each.

| input | beat accuracy, pooled | per-page mean | onsets only | onset F1 |
|---|---|---|---|---|
| (a) WJazzD's onsets on WJazzD's beats, our quantizer | 0.612 [0.531, 0.669] | 0.584 | 0.687 | 0.761 |
| (b) the same onsets on OUR grid | 0.616 [0.514, 0.674] | 0.575 | 0.696 | 0.774 |
| (c) our transcription on our grid | 0.562 [0.448, 0.637] | 0.522 | 0.628 | 0.747 |
| (f) Flex-Q's positions for the same onsets | 0.466 [0.390, 0.519] | 0.436 | 0.543 | 0.603 |

The paired per-page changes, with `evaluation.paired_change` (n = 8):

- **grid**, (b) - (a): -0.008 [-0.030, +0.013], 2 up / 6 down, p = 0.29.
  Nothing measurable.
- **hearing**, (c) - (b): -0.054 [-0.075, -0.031], 0 up / 7 down, p = 0.016.
- **writing**: 1 - (a) = 0.39 of beats wrong even with the annotator's
  onsets on the annotator's beats. Part of that is the annotator and the
  page disagreeing about which notes exist ((a)'s onset F1 is 0.761), which
  no quantizer can mend.
- **our quantizer against Flex-Q**, on identical onsets, (a) - (f):
  +0.147 [+0.108, +0.184], 8 of 8 up. This agrees with D36 and with the
  paper's own criticism of FlexQ.

### Which figures we get wrong (Omnibook, all 22, exact view)

Of 6,111 beats, 2,612 are wrong. In **20% of the wrong beats every onset is
right**: only a note's length or a rest differs (23.5% on the hand scores).
Another 3.7% involve a beat that one side cannot tokenize. The book writes
0.2% of its beats off the twelve bins; we write 1.4% (all with a 32nd-grid
onset), and every one of ours is charged.

| the book writes | share of beats | we match it | what we write instead |
|---|---|---|---|
| 8 8 | 44.8% | 0.741 | 8 r8 (9%), q (4%), 8t 8t 8t (3%) |
| a quarter rest | 15.8% | 0.611 | a held note (18%), ~8 r8 (10%), 8 r8 (4%) |
| r8 8 | 7.5% | 0.504 | ~8 8 (24%), 8 8 (8%), rest (8%) |
| q | 7.2% | 0.572 | 8 8 (16%), 8 r8 (10%), 16 8. (5%) |
| a held beat (~q) | 5.9% | 0.387 | q (19%), ~8 8 (11%), ~8 r8 (8%) |
| 8t 8t 8t | 4.7% | 0.251 | 8 8 (36%), 8 r8 (6%), 16 16 8 (6%) |
| ~8 8 | 3.8% | 0.489 | 8 8 (26%), r8 8 (6%) |
| 16 16 16 16 | 2.8% | 0.257 | 8t 8t 8t (19%), 8 8 (16%), 16 16 8 (11%) |
| 16t 16t 16t 8 (the turn) | 1.8% | **0.000** | 8t 8t 8t (28%), 8 8 (27%), 32nds (16%) |
| 8 16 16 | 1.2% | 0.055 | 8 8 (48%), 8 r8 (15%) |

("~" means held from the beat before, "r" is a rest. `beat_signature.describe`
prints these names.)

The commonest wrong pairs, as a share of wrong beats:

- 8 8 -> 8 r8, 9.0%: a second eighth we do not have, which is hearing.
- rest -> held, 6.7%: we hold a phrase end through the book's rest.
- r8 8 -> ~8 8, 4.2%: the gap before an offbeat is closed from the left
  (`MIN_REST`).
- 8 8 -> q, 4.1%.
- 8t 8t 8t -> 8 8, 3.9%.
- rest -> ~8 r8, 3.8%.

On the hand scores the order changes:

- q -> 8 r8, 9.2%: the listener writes a quarter where the player let go.
- q -> 8 8, 8.1%.
- rest -> r8 8, 7.1%.

Two references with **opposite length conventions** is a finding in itself.
The book writes rests where Parker held on. The listener writes quarters
where the players let go.

On (a), the quantizer alone, the order is:

- 8 8 -> 8 r8, 7.1%.
- q -> 8 r8, 6.3%.
- ~q -> q, 5.0%: an anticipation the page ties over the beat and we strike
  on it.
- rest -> ~8 r8, 4.2%.
- 16 16 16 16 -> 32nds, 3.0%.
- The sixteenth-triplet turn -> 32nds, 2.3%.

## 3. What this says about A6

1. **We do not need a learned classifier to match the publication.** A rule
   quantizer with CREPE and beat_this already scores 0.577 on the sides
   whose beats held, against 0.53. The interval on the pooled figure clears
   0.53 (low end 0.544), but the per-page interval does not (low end 0.528).
   On the slow analogue the two are level. So the honest claim is "level,
   slightly ahead" and nothing stronger.
2. **The published system hears onsets better and assembles whole beats no
   better.** Its onset F1 is 0.83 against our 0.785, yet its beat accuracy
   is lower. A plausible reading, not a measurement: its beats are drawn
   from 42 Filosax classes. A Parker beat outside Filosax's idiom is lost to
   it, while a rule quantizer can write anything, including 1.4% of beats
   the bins cannot hold.
3. **What can be gained is writing, and it is large.** With perfect onsets
   and perfect beats the quantizer gets 0.61 of beats. Hearing and the grid
   together cost 0.06 (0 of 8 up). The A6 re-ranker should therefore be
   judged on the (a) row, as the roadmap already says, and this measure is
   now one of its instruments.
4. **What a per-beat model has to learn**, in order of mass:
   - Note ends: a rest against a held note. This is 20% of wrong beats, and
     the book and the listener disagree on the convention. A model trained
     on one will be wrong on the other unless it is conditioned on the
     reference style, or unless value is left to a rule.
   - The book's triplets: 8t 8t 8t is right 25% of the time, and 36% of
     them are written as 8 8.
   - Sixteenth runs, right 26% of the time.
   - The sixteenth-triplet turn, never right. `sixteenth_triplets` is off
     (R29's night), and we write 32nds or triplets there.
   - Anticipations tied across the beat.

   None of these is visible to a timing rule alone (A1, D28). They are the
   convention a learned prior over figures in context would carry.
5. **It is cheap to watch.** The whole run takes three minutes on cached
   notes and needs no GPU. A rule change (R27-R33) or the A6 re-ranker can
   print this beside `run_eval`'s rhythm and value.

## 4. Caveats

- **Their subset is unknown.** They took 60% of the test set of Riley and
  Dixon 2024 (the "same subset of Omnibook tracks"), selected on how well
  the beats were tracked. Our 22 sides are a different subset of the 50 on
  hand, and the overlap is unknown. Two analogues bracket their selection:
  held (0.577) and slowest (0.536).
- **Their beats are not ours.** On their easy tracks, madmom beat *i* is the
  annotated beat *i*. Our pages sit on our repaired beat_this grid, and each
  reference beat is paired with ours through the pitch matches. That is
  generous only where a grid slips, which happens on one side here, and
  global pairing moves nothing else.
- **Their classes are not ours.** The 42 here come from 189 OMR-read pages,
  not from Filosax. The "rare" class holds 0.2-1.0% of reference beats and
  changes no number by more than 0.001.
- **The formula is ours.** Section 4 does not define rhythm accuracy, and
  does not say whether it is pooled or a mean per track. Both are reported;
  they differ by 0.013.
- **Hearing is included on both sides.** Like theirs, this measure charges
  missed and extra notes: 8 8 -> 8 r8 is mostly a note we did not hear.
  Only the triples separate the two sources.
- **The references differ.** The Omnibook set is LORIA's MusicXML, which is
  the paper's reference. The hand scores are the listener's MuseScore
  pages, whose conventions differ (section 2). Two of the eight triples
  (Embraceable You, Cheese Cake) are OMR-read PDF pages, with that noise.
  WJazzD's onsets in (a) are a different annotator's reading of the notes.
- **Filosax's 0.87 is in-domain and cannot be run here.** Filosax is not on
  this machine, and the model was trained on the Filosax pages it is scored
  against. Nothing here says how we would read there.
- **Their onset F1 is recomputed from their description.** Zero tolerance,
  on aligned score positions, pitch ignored. If they counted it another way,
  the 0.83-against-0.785 comparison moves with it.

## 5. Running it

    python scripts/beat_signature.py --db wjazz/wjazzd.db [--json out.json]

With no arguments it reads `run_eval`'s own caches
(`.benchmark-notes-c0.2-d0.0.json`, `.benchmark-grids.json`); `--notes`
and `--grids` point it at copies. `--db` adds the triples. It needs the
`ml` group for numpy (the bootstrap and WJazzD fit). The module itself is
pure arithmetic and runs in CI. The JSON holds per-page accuracies and
pooled counts of twelve-letter rhythm strings, never a note.
