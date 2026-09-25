# A figure prior from human pages: what transcribers write per beat

2026-09-25. The research brief is `docs/figure-prior-brief.md`; this is its
result. `scripts/figure_prior.py` counts, `scripts/figure_prior.py
condition` chooses what to condition on, `scripts/figure_prior.py compare
--db wjazz/wjazzd.db` puts the humans beside each other and us beside them
(three minutes, the WJazzD alignment being the wait), and `scripts/
figure_prior.py build` writes the aggregate that ships. The count takes
four seconds; re-run it whenever the corpus folder changes -- the listener
is still correcting missed triplet marks and time signatures in it, and
every number below will move a little when they land.

A **figure** is the sorted set of onset positions inside one quarter-note
beat, as exact fractions of the beat: `0 1/2` is an eighth pair, `0 1/3
2/3` a triplet, `0 3/4` a dotted eighth and a sixteenth, `-` a beat with
no onset. A tied-into note is not an onset, a grace note is not an onset,
a chord is one onset.

## The corpus, counted

`benchmark/Transcriptions_Other/musicxml/`: the MusicXML `pdf2musicxml`
read off 275 PDF transcriptions by human transcribers (docs/pdf2musicxml.md).
Seven are dropped before anything is counted because their recording is
under `benchmark/` and the judge set must stay a hold-out (`OVERLAP` in the
script, each named with its benchmark twin): Cheese Cake (Gordon, WJazzD
121), Joy Spring (Brown, WJazzD 93), Gingerbread Boy (Shorter's solo on the
Miles Smiles track whose Hancock solo is WJazzD 186), Embraceable You
(Parker, WJazzD 56), Moose the Mooche twice (the Omnibook side) and Scrapple
from the Apple (the Omnibook side). Ornithology (12-11-1948) is kept: the
benchmark's is the 1946-07-29 take. That leaves 268.

| | n |
|---|---|
| transcriptions | 268: Wesley Chin 52 (hard bop, Sibelius), maxgrynchuk.com 49 (lead-trumpet charts, Sibelius), peterandwillanderson.com 167 (swing-era and New Orleans, Finale, 36 scans) |
| notes (chord tones collapsed, grace notes dropped) | 119,606 |
| rests | 15,133 |
| tuplet notes | 12,338 (10.3%) |
| tied-into notes (not onsets) | 4,080 (3.4%) |
| bars | 20,214 |
| bars whose notes fill their signature | 19,166 (94.8%) |
| bars the two OMR engines read differently (`check_disagreeing`) | 5,445 (26.9%) |
| bars the converter's tuplet bookkeeping doubts (a printed number it could not apply) | 769 |
| time signatures (bars) | 4/4 18,677; 2/2 1,293; 6/8 92; 12/8 55; 2/4 47; 10/8 34; 8/8 14; 6/4 2 |
| files with a tempo mark of 40 bpm or more | 111 (three marks under 40 are misread digits and are dropped) |
| tempo bands over those 111 | under 100: 5; 100-160: 21; 160-220: 28; 220-300: 49; 300 and over: 8 |

The source of a file is told by its filename's shape, as docs/pdf2musicxml.md
tells it; the doc's own count of the Grynchuk set is 47, which this rule
reproduces before the overlap drop.

### What is excluded, and what that does to the triplet rows

Under the **plain** filter a beat is counted only if its bar fills its
signature exactly (the listener's rule, without exception), the bar is not
one the converter doubts, the beat holds no duplicate onset (two at one
position, an engine slip: 75 beats), and the metre has a quarter-note beat
(compound bars, 195 of them, are out). The **strict** filter also drops
every bar the two engines read differently, and every tuplet bar of a file
in which the converter counted a tuplet the page does not print (78 such
tuplets over the corpus; the converter counts them per file and does not
say which bar).

The filters are not neutral about triplets, and this is the caveat the
brief asked for. Tuplet notes are 10.3% of the corpus, **7.9%** of the notes
in the bars the plain filter keeps, and **5.8%** under strict: a misread
triplet is exactly what makes a bar fail to fill, and a doubted bar is a
tuplet bar by definition, so the exclusions take triplet bars out
preferentially. The `0 1/3 2/3` row below therefore reads LOW -- 3.67% of
beats with an onset under plain, 2.95% under strict -- against 5.20% on the
listener's twelve pages and 6.02% on the Omnibook (the same tally, next
section). The plain filter is the one to build from, and its triplet share
should be read as a floor. Re-tallying after the listener's cleanup is
where this moves.

## The per-beat figures

Share of beats **with an onset**, which is the only kind the quantizer ever
chooses a figure for (an empty beat never competes; it is 28.2% of all
counted beats under plain, 29.1% under strict, and is kept in the shipped
file for the record). Quarter-beat metres 4/4, 3/4, 2/4 and 6/4 pooled;
2/2 is below, on its own. The strata are the three sources.

| figure | pooled n | pooled % | Wesley Chin % | maxgrynchuk % | peterandwillanderson % | strict n | strict % |
|---|---|---|---|---|---|---|---|
| 0 1/2 | 27179 | 55.05 | 57.67 | 48.40 | 55.75 | 22249 | 59.04 |
| 0 | 8881 | 17.99 | 17.91 | 22.56 | 16.43 | 6528 | 17.32 |
| 1/2 | 5677 | 11.50 | 13.00 | 12.81 | 10.10 | 4222 | 11.20 |
| 0 1/4 1/2 3/4 | 2436 | 4.93 | 3.33 | 5.33 | 5.80 | 1664 | 4.42 |
| 0 1/3 2/3 | 1812 | 3.67 | 2.65 | 3.40 | 4.40 | 1112 | 2.95 |
| 0 1/2 3/4 | 608 | 1.23 | 1.27 | 1.03 | 1.28 | 429 | 1.14 |
| 1/2 3/4 | 492 | 1.00 | 0.75 | 0.95 | 1.17 | 353 | 0.94 |
| 0 1/4 | 215 | 0.44 | 0.39 | 0.31 | 0.51 | 128 | 0.34 |
| 0 1/4 1/2 | 207 | 0.42 | 0.46 | 0.58 | 0.34 | 113 | 0.30 |
| 1/4 1/2 3/4 | 195 | 0.39 | 0.21 | 0.36 | 0.52 | 129 | 0.34 |
| 1/3 2/3 | 179 | 0.36 | 0.31 | 0.42 | 0.38 | 98 | 0.26 |
| 1/3 | 172 | 0.35 | 0.25 | 0.60 | 0.32 | 49 | 0.13 |
| 0 2/3 | 149 | 0.30 | 0.22 | 0.51 | 0.28 | 45 | 0.12 |
| 0 3/4 | 127 | 0.26 | 0.17 | 0.35 | 0.28 | 74 | 0.20 |
| 0 1/6 1/3 1/2 | 109 | 0.22 | 0.24 | 0.56 | 0.09 | 58 | 0.15 |
| 3/4 | 95 | 0.19 | 0.12 | 0.22 | 0.23 | 50 | 0.13 |
| 1/2 2/3 5/6 | 90 | 0.18 | 0.21 | 0.11 | 0.19 | 36 | 0.10 |
| 0 1/4 3/4 | 67 | 0.14 | 0.04 | 0.28 | 0.14 | 29 | 0.08 |
| 0 1/6 1/3 1/2 2/3 5/6 | 45 | 0.09 | 0.00 | 0.07 | 0.16 | 7 | 0.02 |
| 2/3 | 42 | 0.09 | 0.06 | 0.08 | 0.10 | 9 | 0.02 |
| 0 1/2 2/3 5/6 | 40 | 0.08 | 0.08 | 0.11 | 0.07 | 22 | 0.06 |
| 0 1/8 1/4 3/8 1/2 3/4 | 40 | 0.08 | 0.01 | 0.00 | 0.16 | 19 | 0.05 |
| 1/4 3/4 | 39 | 0.08 | 0.10 | 0.09 | 0.06 | 23 | 0.06 |
| 0 1/8 1/4 3/8 1/2 5/8 3/4 7/8 | 36 | 0.07 | 0.05 | 0.01 | 0.11 | 16 | 0.04 |
| 1/4 | 24 | 0.05 | 0.01 | 0.02 | 0.08 | 15 | 0.04 |
| beats with an onset | 49373 | | 15575 | 8777 | 25021 | 37685 | |
| all counted beats | 68723 | | 21787 | 12808 | 34128 | 53140 | |
| files | 245 | | 52 | 46 | 147 | 237 | |
| distinct figures | 132 | | 68 | 60 | 103 | 80 | |

Three things to read off it:

- **The strata agree on the order and, to within a few points, on the
  shares.** The pair is 48-58% of onset beats in every source, the single
  downbeat 16-23%, the lone "and" 10-13%, four sixteenths 3.3-5.8%, the
  triplet 2.7-4.4%, and every figure past the seventh is under 0.6% in all
  three. The lead-trumpet charts (maxgrynchuk) write fewer pairs and more
  single notes and sixteenths, which is the material; nothing rare in one
  source is common in another. The prior is counted from the pool.
- **Plain and strict agree on the top thirty within their counts.** The
  first seven figures move by under 4 points, in the direction the filter
  bias predicts (pair up, triplet and sixteenths down). The OMR noise is
  not shaping the table.
- **The rules already shipped are the tail of this table.** The lone "e"
  (`1/4`) is 0.05% of onset beats, the lone "a" (`3/4`) 0.19%, the dotted
  eighth plus sixteenth (`0 3/4`) 0.26%, a sixteenth then a dotted eighth
  (`0 1/4`) 0.44%: R27 (a sparse beat gets no sixteenth grid) and R29 (the
  line's lag comes out first) encode the rarity of exactly these, and the
  table says how rare. What no rule yet says is the rest of the tail --
  `0 1/4 1/2` at 0.42%, `0 1/4 3/4` at 0.14%, `1/4 1/2` at 0.04% -- which is
  where our pages differ most from every human set (next section).

### 2/2, looked at before folding

| figure | n | % of onset beats | 4/4, 3/4, 2/4 % of onset beats |
|---|---|---|---|
| 0 1/2 | 1494 | 44.50 | 55.05 |
| 0 | 863 | 25.71 | 17.99 |
| 1/2 | 438 | 13.05 | 11.50 |
| 0 1/4 1/2 3/4 | 202 | 6.02 | 4.93 |
| 0 1/3 2/3 | 50 | 1.49 | 3.67 |
| 0 1/2 3/4 | 39 | 1.16 | 1.23 |
| 0 3/4 | 39 | 1.16 | 0.26 |
| 0 1/4 | 32 | 0.95 | 0.44 |
| 1/2 3/4 | 28 | 0.83 | 1.00 |
| 0 1/4 1/2 | 25 | 0.74 | 0.42 |
| 3/4 | 25 | 0.74 | 0.19 |
| beats with an onset | 3357 | over 21 files | 49373 |

A cut-time chart's eighth pair is a pair of quarters, and it shows: per
quarter the pair is 44% against 55%, the single downbeat 26% against 18%,
the triplet 1.5% against 3.7%, and the dotted figures (`0 3/4`, `0 1/4`,
`3/4`) two to four times as common. It is a different distribution of a
different unit, 6% of the corpus over 21 files, and it stays out of the
pooled table. The quantizer's beat is the tracked pulse, which for a
cut-time chart is the half note if the tracker heard it that way and the
quarter if not, so there is no clean place to apply a 2/2 table either.

### Rests

Over the counted 4/4, 3/4 and 2/4 bars (plain filter, 12,835 rests; strict
in brackets, 9,640): a rest starts on the beat 94.7% (95.6) of the time,
on the "and" 4.9% (4.0), and anywhere else 0.4% (0.3) -- 28 on the "e", 18
on the "a", 9 on a triplet's 1/3. Values: eighth 36.2% (34.2), quarter
33.7% (33.4), half 15.3% (16.2), whole 10.7% (13.3), sixteenth 2.5% (1.9),
dotted eighth 0.3%, dotted quarter 0.1%, thirty-second 0.04%.

Beside the survey (docs/notation-survey.md): the listener writes 42% eighth
rests, 30% quarter, 17.5% half, 1.8% dotted quarter; the Omnibook 44/34/17.5
and no dotted quarter; we wrote 58-56% eighth rests and 9.9-11.1% dotted
quarters before R30 took the dotted quarter out. The corpus's whole-bar
rests are high (10.7%) because a lead-trumpet chart rests through the
ensemble and No Room For Squares carries a 95-bar rest; among rests inside
bars that hold notes the picture is the listener's.

### Tuplet share and tie rate per stratum

Over the counted bars, so the filter's bias against tuplet bars applies
(see above); the whole-corpus tuplet share is 10.3%.

| set | notes | tuplet share % | tie rate |
|---|---|---|---|
| Wesley Chin (plain / strict) | 29,588 / 22,719 | 6.2 / 3.7 | 0.035 / 0.031 |
| maxgrynchuk (plain / strict) | 17,258 / 10,524 | 8.6 / 5.9 | 0.039 / 0.040 |
| peterandwillanderson (plain / strict) | 56,976 / 43,422 | 8.6 / 6.9 | 0.033 / 0.031 |
| all (plain / strict) | 103,822 / 76,665 | 7.9 / 5.8 | 0.034 / 0.033 |
| the listener's twelve pages (survey) | 4,332 | 11.2 | 0.023 |
| the Omnibook, 22 sides (survey) | 9,974 | 14.4 | 0.045 |
| ours, hand-score set (survey, today) | 4,664 | 8.5 | 0.032 |
| ours, Omnibook set (survey, today) | 9,347 | 7.6 | 0.042 |

Wesley Chin's hard-bop pages, the stratum nearest the judge set, read the
lowest tuplet share of the three and half the listener's own: the same
transcriber's Sibelius exports lost the most triplet marks to OMR (the
listener's complaint of 2026-09-24), and the strict filter halves the share
again. This is the stratum where cleanup pays most, and the number to
re-read after it.

### The survey's fourth column

`scripts/notation_survey.py --corpus benchmark/Transcriptions_Other/musicxml`
now tallies the corpus beside the listener's pages, the Omnibook and ours
(`add_corpus`, under the plain filter's bars, positions over runs of
counted bars so no gap spans an excluded one). 268 tracks, 97,532 notes,
12,835 rests, tie rate 0.034, tuplets 8.1%:

- note values: eighth 63.0, sixteenth 14.7, quarter 8.4, triplet eighth
  6.1, dotted quarter 1.9, half 1.6, 32nd 1.3, sixteenth triplet 1.3,
  quarter-note triplet 0.5, **dotted eighth 0.3**, dotted sixteenth 0.0 --
  the listener 0.1 / 0.0 and the Omnibook 0.1 / 0.0 on the two bold ones,
  against our 1.1-1.7 / 0.6-0.8;
- rests: eighth 36.2, quarter 33.7, half 15.3, whole 10.7, sixteenth 2.5;
- onset in beat: beat 45.2, and 40.0, **a 4.7, e 3.7**, 2/3 2.6, 1/3 2.5,
  odd 32nd 0.7. The "e" and "a" are higher than the listener's (1.8, 2.8)
  and the Omnibook's (2.5, 3.9) because the lead-trumpet charts are
  sixteenth-note material: four sixteenths are 4.9% of onset beats and
  contribute an "e" and an "a" each. As a lone figure they are the tail
  above;
- gap to next: eighth 59.4, sixteenth 14.6, quarter 6.9, triplet eighth
  6.1, half or longer 5.8, dotted quarter 2.7, sixteenth triplet 1.3, 32nd
  1.3, **dotted eighth 0.4** (ours 1.1-1.7).

## Humans against humans, then us against humans

The same tally on the listener's twelve `.mscz` scores (`mscz.parse`,
melody positions, grace notes at zero length collapse into their main note)
and LORIA's 22 Omnibook files (the corpus reader; every LORIA bar fills).
Share of beats with an onset:

| figure | corpus (49,373) | hand scores (2,344) | Omnibook (4,788) |
|---|---|---|---|
| 0 1/2 | 55.05 | 55.03 | 57.29 |
| 0 | 17.99 | 19.75 | 9.77 |
| 1/2 | 11.50 | 11.69 | 14.54 |
| 0 1/4 1/2 3/4 | 4.93 | 2.22 | 3.57 |
| 0 1/3 2/3 | 3.67 | 5.20 | 6.02 |
| 0 1/2 3/4 | 1.23 | 1.45 | 1.52 |
| 1/2 3/4 | 1.00 | 0.98 | 1.94 |
| 0 1/6 1/3 1/2 | 0.22 | 0.13 | 2.36 |
| 1/3 | 0.35 | 0.68 | 0.15 |
| 0 2/3 | 0.30 | 0.64 | 0.19 |
| 0 1/4 1/2 | 0.42 | 0.38 | 0.54 |
| 0 1/4 | 0.44 | 0.30 | 0.10 |
| 1/2 2/3 5/6 | 0.18 | 0.34 | 0.42 |
| 1/3 2/3 | 0.36 | 0.21 | (under 0.1) |
| 0 3/4 | 0.26 | 0.04 | 0.27 |
| 1/4 1/2 3/4 | 0.39 | 0.13 | 0.15 |
| 3/4 | 0.19 | 0.04 | 0.04 |
| 1/4 | 0.05 | 0.09 | 0.00 |

Where the humans disagree with each other: the Omnibook writes half as many
lone downbeats (Parker's lines run) and ten times the sixteenth-triplet
figure (`0 1/6 1/3 1/2`, LORIA's house style, D35); the corpus writes fewer
triplets than either (the OMR floor above) and more four-sixteenth beats
(the trumpet charts). On everything under 1% the three agree that it is
under 1%. The prior cannot be sharper than the triplet disagreement
(3.7 against 5.2 and 6.0), and it is not asked to be: the tuplet gate
decides triplets, and the prior is added to a candidate set the gate has
already trimmed.

**Us against each human set, over the same pages** (`compare`): the twelve
hand-score pages, the 22 Omnibook sides and the 77 located WJazzD solos,
notated exactly as `run_eval` notates them today (R29, R30 in). Figure,
human share, our share, ratio, beats with an onset; the WJazzD column has
no human page of its own (D36) and is set against the corpus.

| figure | hand scores % | ours % | ratio | Omnibook % | ours % | ratio | corpus % | ours (WJazzD, 19,151) % | ratio |
|---|---|---|---|---|---|---|---|---|---|
| 0 1/2 | 55.03 | 50.35 | 0.91 | 57.29 | 50.50 | 0.88 | 55.05 | 42.34 | 0.77 |
| 0 | 19.75 | 19.86 | 1.01 | 9.77 | 18.16 | 1.86 | 17.99 | 24.67 | 1.37 |
| 1/2 | 11.69 | 16.45 | 1.41 | 14.54 | 15.17 | 1.04 | 11.50 | 15.04 | 1.31 |
| 0 1/3 2/3 | 5.20 | 5.08 | 0.98 | 6.02 | 4.74 | 0.79 | 3.67 | 3.05 | 0.83 |
| 0 1/4 1/2 3/4 | 2.22 | 0.66 | **0.30** | 3.57 | 1.59 | **0.45** | 4.93 | 2.23 | **0.45** |
| 0 1/2 3/4 | 1.45 | 0.62 | 0.43 | 1.52 | 0.75 | 0.49 | 1.23 | 0.69 | 0.56 |
| 1/2 3/4 | 0.98 | 0.50 | 0.51 | 1.94 | 0.63 | 0.32 | 1.00 | 0.84 | 0.84 |
| 0 1/4 | 0.30 | 1.75 | **5.85** | 0.10 | 1.51 | **14.5** | 0.44 | 1.39 | **3.20** |
| 0 1/4 1/2 | 0.38 | 1.36 | **3.54** | 0.54 | 1.51 | **2.79** | 0.42 | 2.15 | **5.12** |
| 0 1/4 3/4 | 0.00 | 0.47 | - | 0.00 | 0.93 | - | 0.14 | 1.07 | **7.89** |
| 1/4 1/2 | 0.04 | 0.39 | 9.1 | 0.04 | 0.81 | 19.3 | 0.04 | 1.00 | **23.5** |
| 1/4 3/4 | 0.00 | 0.16 | - | 0.00 | 0.59 | - | 0.08 | 0.64 | 8.1 |
| 0 3/4 | 0.04 | 0.31 | 7.3 | 0.27 | 0.46 | 1.7 | 0.26 | 0.49 | 1.9 |
| 3/4 | 0.04 | 0.12 | 2.7 | 0.04 | 0.18 | 4.4 | 0.19 | 0.32 | 1.7 |
| 1/4 | 0.09 | 0.12 | 1.4 | 0.00 | 0.32 | - | 0.05 | 0.26 | 5.3 |
| 1/3 | 0.68 | 0.00 | **0** | 0.15 | 0.00 | 0 | 0.35 | 0.00 | 0 |
| 0 2/3 | 0.64 | 0.00 | **0** | 0.19 | 0.00 | 0 | 0.30 | 0.00 | 0 |
| 1/3 2/3 | 0.21 | 0.00 | 0 | (under 0.1) | 0.00 | | 0.36 | 0.01 | 0.03 |
| 1/2 2/3 5/6 | 0.34 | 0.00 | 0 | 0.42 | 0.00 | 0 | 0.18 | 0.00 | 0 |
| 0 1/6 1/3 1/2 | 0.13 | 0.00 | 0 | 2.36 | 0.00 | **0** | 0.22 | 0.00 | 0 |
| 32nd figures (`0 1/4 3/8 5/8`, `1/8 3/8 5/8`, ...) | 0.00 | 0.8 | - | 0.00 | 0.5 | - | 0.01 | 1.0 | - |
| beats with an onset | 2344 | 2578 | | 4788 | 4956 | | 49373 | 19151 | |

The diagnostic, whatever ships:

- **We under-write the four-sixteenth beat by two to three times** on every
  set, and the three-onset sixteenth figures with it (`0 1/2 3/4`, `1/2
  3/4` at 0.3-0.6). A prior cannot mend this: a beat of four onsets is
  offered the sixteenth grid and takes it. What is missing is the onsets
  -- a sixteenth run's notes dropped or merged upstream -- and the
  over-written `0 1/4 1/2` (3-5x) and `0 1/4` (3-14x) are its remainder:
  a four-sixteenth beat with a note missing, written faithfully.
- **We over-write every lone-"e" figure**: `0 1/4`, `0 1/4 1/2`, `0 1/4
  3/4`, `1/4 1/2`, `1/4 3/4`, on every set, by three to twenty times,
  0.2-1% of beats each and about 4-6% together. These are R29's target
  (the laid-back line written on the "e") after R29: the lag rule takes
  out the window median, and what is left is the beats whose lag is not
  the window's. This is the class a prior can reach, because on those beats
  the eighth reading is a candidate and loses on snap error by a little.
- **We write no two-onset ternary figure at all** (`1/3`, `0 2/3`, `1/3
  2/3`: 0.7-1.3% of a human's beats together) and no sixteenth-triplet
  figure (`1/2 2/3 5/6`, `0 1/6 1/3 1/2`: 0.5% of the listener's, 2.8% of
  the Omnibook's). Both are by rule -- the tuplet gate (two onsets cannot
  vote a tuplet, measured and kept, `offbeat_pair_tuplet_fit` off) and
  `sixteenth_triplets` off -- and a prior added to the candidate set cannot
  produce a candidate the set does not hold. Task 7 has them.
- **We write 32nd figures the humans never write** (0.5-1% of our beats),
  which is D16's rule at work: the 32nd grid is admitted where sixteenths
  cannot keep the onsets apart, so these are beats of two onsets under 60
  ms apart. Whether they are notes is a transcribe question.
- The WJazzD pages read further from the corpus than the judge pages do
  (pair 0.77, single 1.37): the batch's spans are whole solos on the
  Roformer's stems with no listener's erasures, and these pages carry more
  of the transcriber's extra notes. The ratio table is the same shape.

## What to condition on

Over the 49,373 onset beats of the plain pooled table, each conditioning's
entropy in bits per beat: the in-sample conditional entropy, and the honest
number, the held-out cross-entropy (each file scored on a table counted from
the other files, two folds, add-half smoothing over the 132 figures). The
last two columns are the ones that matter: **the quantizer never chooses
between a two-onset figure and a three-onset one** -- the count is the
beat's own -- so the bits a conditioning carries about the CHOICE are the
bits it carries beyond the count, H(F | count) against H(F | count, c),
held out.

| conditioning | beats | files | cells | H(F) | H(F given c) | gain | held-out | held-out unigram | held-out given count | held-out given count and c | sparsest cell |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nothing | 49373 | 245 | 1 | 2.244 | 2.244 | 0.000 | 2.253 | 2.253 | 0.755 | 0.755 | all (49373) |
| tempo band | 23705 | 106 | 5 | 2.131 | 1.992 | 0.140 | 2.046 | 2.142 | 0.713 | 0.764 | under 100 (540) |
| onset density | 49373 | 245 | 6 | 2.244 | 2.017 | 0.227 | 2.047 | 2.253 | 0.755 | 0.794 | under 0.5 (956) |
| previous figure | 49373 | 245 | 125 | 2.244 | 1.807 | 0.437 | 1.923 | 2.253 | 0.755 | 0.819 | one beat |
| previous figure's class | 49373 | 245 | 7 | 2.244 | 1.901 | 0.342 | 1.935 | 2.253 | 0.755 | 0.724 | other (16) |
| density and previous class | 49373 | 245 | 40 | 2.244 | 1.765 | 0.479 | 1.891 | 2.253 | 0.755 | 0.894 | two beats |
| meter | 49373 | 245 | 3 | 2.244 | 2.238 | 0.005 | 2.255 | 2.253 | 0.755 | 0.765 | 6/4 (3) |
| source | 49373 | 245 | 3 | 2.244 | 2.226 | 0.017 | 2.248 | 2.253 | 0.755 | 0.785 | maxgrynchuk (8777) |

Read on the raw figure, every conditioning looks informative: the tempo
band carries 0.10 bit held out (on the 106 marked files; its per-band
tables are below, the under-100 band holding 540 beats over 5 files), the
local onset density 0.21 bit and on every file, the previous figure 0.33,
density with the previous figure's class 0.36. **Read given the onset
count, none of them carries anything**: the count itself takes the unigram
from 2.253 to 0.755 bits, and every conditioning on top of it reads WORSE
held out (0.76-0.89) except the previous figure's class, at 0.724, a gain
of 0.03 bit -- under the brief's 0.1 and not worth a sequential dependency
in the quantizer. What the tempo band and the density were carrying was
how many notes a beat holds, which the quantizer already has in the beat's
own onsets; given that, a swung-era page at 300 bpm and a lead-trumpet
chart at 120 write a three-onset beat the same way.

So the prior is **one table, conditioned on nothing**, which is also the
simplest thing the brief allowed. Its meter column agrees (0.005 bit), and
its 2/2 rows are out for the reason given above.

Per tempo band, share of onset beats, for the record (the under-100 band is
five files and should not be read):

| figure | under 100 (540, 5 files) | 100-160 (2261, 19) | 160-220 (5109, 27) | 220-300 (13416, 49) | 300 and over (2379, 6) |
|---|---|---|---|---|---|
| 0 1/2 | 18.0 | 29.6 | 48.4 | 61.6 | 74.8 |
| 0 | 18.1 | 16.9 | 21.2 | 19.0 | 12.9 |
| 1/2 | 5.9 | 8.8 | 16.1 | 13.2 | 6.1 |
| 0 1/4 1/2 3/4 | 13.1 | 17.1 | 6.1 | 1.0 | 0.3 |
| 0 1/3 2/3 | 5.4 | 6.6 | 2.6 | 2.5 | 4.0 |
| 0 1/2 3/4 | 2.2 | 2.9 | 1.2 | 0.9 | 0.5 |
| 1/2 3/4 | 3.3 | 1.7 | 0.9 | 0.4 | 0.1 |
| 0 1/4 | 4.3 | 1.9 | 0.1 | 0.0 | 0.0 |
| 0 3/4 | 2.2 | 1.5 | 0.1 | 0.0 | 0.0 |

The middle bands differ from each other in exactly the way D11 found: the
running value steps from the sixteenth (17% four-sixteenth beats at
100-160) to the eighth pair (62% at 220-300, 75% at 300 and over). That is
the onset count again, and `grid_slack_s` in seconds already carries it.

## The prior in the quantizer, and the judge

(Tasks 4-6. Filled in below as they land.)

## Findings to report, not to implement

(Task 7. Filled in below.)
