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

## The prior in the quantizer

`QuantizeConfig.figure_prior_weight`, beats per nat, default 0.0 (off).
`choose_reading` adds to each (grid, reading) candidate's mean snap error
the surprisal of the figure that candidate writes -- minus the log of its
share over the 49,373 onset beats above (`quantize.figure_prior`, read
once from `swingscribe/figure-prior.json`, 131 rows; an unseen figure gets
half a count, 11.5 nats) -- times the weight, before the
coarsest-within-slack comparison. An onset a grid sends to 1.0 is the
next beat's downbeat and leaves this beat's figure. Every rule the prior
sits beside stands: `_keeps_apart` is hard, the tuplet and sixteenth gates
trim the candidates first, the lag rule runs first, and the prior decides
only among what they leave. Adding the field moved the quantize cache
key, which is arithmetic below transcribe and no CREPE. At 0.0 the term is
not computed and every pinned number reproduces (the harness: "all 2749
numbers unchanged"; the instrument: "unchanged").

**Two loopholes, found by the quantizer instrument the moment the weight
went on, and closed with the prior on only.** `scripts/wjazz_quantize.py`
at 0.015 read dropped notes 7,155 -> 22,934 of 198,983 (3.6% -> 11.5%;
the slow band 20% -> 66%). Traced on Parker's Don't Blame Me:

- a reading that pushed an onset onto the next beat's line, where that
  beat's own note sat, kept a common figure for itself and lost the note
  in notate (one note per grid position). With the prior on such a
  reading is marked as merging, exactly as one that merges inside the
  beat is (`next_occupied`: the next beat has an onset under 0.25). A
  first version also flagged the beat AFTER a push, which put every
  reading of that beat into the fallback, where the prior took the
  coarsest grid, which pushed in turn: a cascade down every ballad
  (26,973 dropped). Withdrawn; the push is refused at its source only;
- where no grid keeps every onset apart (a ballad's ornament under the
  32nd grid), the coarsest-within-slack loop ran over every candidate,
  and with the unseen figure's 11.5 nats on the 32nd grid the eighth grid
  was "within slack" while it merged four notes to the 32nd's one. With
  the prior on, that fallback set is the grids that lose the fewest
  notes.

With both, the prior drops FEWER notes on the instrument than the shipped
quantizer, at every weight: the pushes it refuses were losing notes
already.

## Setting the weight by the round trip

`scripts/figure_prior.py sweep --db wjazz/wjazzd.db`: `replay_onsets` with
the residual discarded (the notation replayed with its feel, plan section
5's acceptance question) on WJazzD's annotated onsets on the annotator's
grid, 452 solos, 198,983 notes, under the shipped settings, 33 seconds. The
first row is the least-snap-error notation (no slack, no prior), so the
table reads what coarsening costs in total. Mean absolute error in ms of
every note; per tempo band the mean of the solos' means.

| weight (beats per nat) | mean ms | rms ms | notes moved % | median solo mean ms | worst solo mean ms | solos over 20 ms | under 100 | 100-160 | 160-220 | 220-300 | 300 and over |
|---|---|---|---|---|---|---|---|---|---|---|---|
| no slack, no prior (reference) | 20.80 | 29.46 | 0.00 | 18.90 | 57.9 | 205 | 36.7 | 23.8 | 18.0 | 15.3 | 13.9 |
| 0.0 (shipped) | 21.71 | 30.68 | 0.00 | 19.75 | 58.9 | 222 | 37.9 | 24.7 | 18.7 | 16.0 | 14.8 |
| 0.0025 | 21.70 | 30.75 | 2.05 | 19.92 | 58.1 | 223 | 37.7 | 24.8 | 18.8 | 16.0 | 14.8 |
| 0.005 | 21.97 | 31.26 | 2.58 | 20.20 | 58.3 | 233 | 38.2 | 25.2 | 19.0 | 16.1 | 14.9 |
| 0.0075 | 22.23 | 31.82 | 2.99 | 20.40 | 59.2 | 236 | 38.9 | 25.6 | 19.1 | 16.2 | 15.0 |
| 0.01 | 22.46 | 32.31 | 3.32 | 20.57 | 59.8 | 247 | 39.4 | 26.0 | 19.3 | 16.3 | 15.0 |
| **0.015** | 22.80 | 33.16 | 3.75 | 20.79 | 60.3 | 251 | 40.5 | 26.5 | 19.4 | 16.3 | 15.1 |
| 0.02 | 23.02 | 33.66 | 4.01 | 20.89 | 64.7 | 257 | 41.2 | 26.8 | 19.5 | 16.4 | 15.1 |
| 0.03 | 23.23 | 34.14 | 4.25 | 20.98 | 68.0 | 258 | 42.0 | 27.1 | 19.6 | 16.5 | 15.1 |
| 0.05 | 23.29 | 34.25 | 4.33 | 21.05 | 68.0 | 259 | 42.2 | 27.2 | 19.6 | 16.5 | 15.1 |
| 0.1 | 23.32 | 34.31 | 4.38 | 21.07 | 68.0 | 259 | 42.2 | 27.2 | 19.6 | 16.5 | 15.1 |

The sweep saturates at about 0.03: past it the prior has already taken
the likeliest figure wherever the gates and the slack let it, and nothing
moves. Three readings of "the mean round-trip error stays within the
shipped criterion", stated before the pages were read:

- **the pooled mean**: already 21.7 ms at the shipped settings, over the
  criterion, because the slow bands read 25-38 ms even with no slack (a
  ballad's beat is a second long and the sixteenth is the finest grid
  offered). Under this reading no weight passes, and neither does 0.0;
- **the median solo**: 19.75 ms at the shipped settings, 0.25 ms inside
  the line, and over it at 0.005. A criterion met by a quarter of a
  millisecond at the default is not one to set anything by;
- **the bands that meet the criterion today** (160 bpm and up, where the
  judge set lives): every one stays within 20 ms at every weight to
  saturation (160-220: 18.7 -> 19.6; 220-300: 16.0 -> 16.5; 300 and over:
  14.8 -> 15.1). The criterion does not bind.

So the criterion bounds the weight only at saturation, and the weight
judged is set by the slack's own equivalence instead: `grid_slack_s` is
0.02 s of snap error a coarser grid may cost, 0.05 beats at the
benchmark's centre of 150 bpm. The prior's commonest decision -- the
eighth pair against the dotted figure `0 1/2 3/4`, 0.60 against 4.40
nats -- is 3.8 nats, and **0.015 beats per nat lets it spend 0.057 beats
there, the slack's own allowance.** At 0.015 the prior costs the round
trip 1.1 ms of pooled mean (the slack itself costs 0.9), moves 3.75% of
the notes, and the bands that meet the criterion still meet it. The
pages were then read at 0.0025 and 0.03 as well, for the trend and not
for the choice.

**A caveat on the unit.** A weight in beats per nat is worth more
milliseconds on a long beat: the sweep's under-100 band moves 37.9 ->
40.5 ms at 0.015 while 220-300 moves 16.0 -> 16.3, and the prior pushes
hardest, in time, exactly where humans write finest (the tempo table
above: 17% four-sixteenth beats at 100-160 bpm). A weight in SECONDS per
nat converted per beat like the slack is the D11-consistent alternative;
no human ballad page exists to judge it (D36), and the judge set is all
160 bpm and up, so this stays a finding.

## The judge

`scripts/run_eval.py --db wjazz/wjazzd.db --cache-dir
benchmark/.swingscribe-cache --jobs 4`, the weight set through
`SWINGSCRIBE_QUANTIZE__FIGURE_PRIOR_WEIGHT` (the environment ranks above
the yaml), four minutes a run, the baseline run first reproducing every
pinned number. Means over the default takes; "up / down" counts pages
that moved by more than the harness's own 0.002 tolerance. Hand-score
rhythm is the number R29 moved 0.794 -> 0.845; its value is 0.777, its
readability 0.9990. Coverage is on every Omnibook row (0.766 at the
default; every page trusted).

| | shipped | 0.0025 | **0.015** | 0.03 |
|---|---|---|---|---|
| hand scores, rhythm (n=12) | 0.8452 | 0.8455 (3 up, 2 down) | **0.8524 (7 up, 1 down)** | 0.8525 (8 up, 2 down) |
| hand scores, value (n=12) | 0.7769 | 0.7774 (3 / 3) | 0.7816 (6 / 2) | 0.7828 (7 / 3) |
| hand scores, readability (n=12) | 0.9990 | 0.9990 | 0.9991 (1 / 0) | 0.9994 (2 / 0) |
| hand scores, tie rate (n=12) | 0.0329 | 0.0331 | 0.0324 | 0.0321 |
| hand scores, placement (n=12) | 0.9027 | 0.9022 | 0.9021 (4 / 5) | 0.9025 |
| pianists, rhythm, oracle line (n=7) | 0.8664 | 0.8675 | 0.8730 | 0.8712 |
| pianists, rhythm, CREPE line (n=7) | 0.8623 | 0.8583 | 0.8576 | 0.8569 |
| Omnibook, rhythm (n=22, coverage 0.766 -> 0.769 / 0.768 / 0.767) | 0.7874 | 0.7861 (6 up, 12 down) | **0.7894 (12 up, 8 down)** | 0.7902 (14 up, 6 down) |
| Omnibook, value (n=22) | 0.7139 | 0.7130 (5 / 11) | 0.7158 (11 / 7) | 0.7162 (14 / 5) |
| Omnibook, readability (n=22) | 0.9975 | 0.9976 | 0.9980 (3 / 0) | 0.9982 (5 / 0) |
| Omnibook, tie rate (n=22) | 0.0421 | 0.0420 | 0.0400 (2 / 12) | 0.0395 |
| Omnibook, placement (n=22) | 0.8591 | 0.8594 | 0.8577 (6 / 9) | 0.8574 |
| readability, all notations (n=85) | 0.9957 | 0.9959 | 0.9962 | 0.9963 |
| WJazzD Flex-Q rhythm, collateral (n=73) | 0.6669 | 0.6676 (18 / 21) | 0.6635 (19 / 36) | 0.6629 (19 / 39) |
| WJazzD placement (n=73) | 0.855 | 0.8556 | 0.853 | 0.8514 |
| WJazzD Flex-Q coverage (n=73) | 0.8675 | 0.8693 (26 / 5) | 0.8663 (14 / 25) | 0.8652 (12 / 32) |
| instrument: dropped of 198,983 annotated notes | 7,155 (3.6%) | 5,186 (2.6%) | 5,989 (3.0%) | 6,276 (3.2%) |
| instrument: page hit (not evidence, D36) | 74.8% | 74.4% | 74.7% | 74.7% |
| instrument: early offbeat as 16th / late as dotted / laid-back after | 4,983 / 2,510 / 693 | 4,917 / 2,731 / 673 | 4,636 / 2,442 / 398 | 4,579 / 2,377 / 285 |
| instrument: pushed beat before / triplet as binary / binary as triplet | 644 / 4,401 / 2,637 | 863 / 4,340 / 2,812 | 800 / 4,259 / 2,998 | 781 / 4,285 / 2,960 |
| notes on our 79 judge and located pages, ties merged (of 46,802) | 46,802 | +145 (63 pages up, 10 down) | -8 (37 up, 42 down) | -64 (30 up, 52 down) |

Per page at 0.015, hand scores: All The Things 0.796 -> 0.819, Soul
Station 0.820 -> 0.838, Lover 0.846 -> 0.864, Someday My Prince 0.829 ->
0.846, Giant Steps 0.873 -> 0.880, There Will Never Be Another You 0.947
-> 0.954, Billy Boy 0.857 -> 0.863; Carl Perkins 0.825 -> 0.815 is the one
down; Birks Works, For Minors Only, Confirmation and Melody for C within
0.002. Omnibook: Ornithology 0.750 -> 0.785, Laird Baird 0.797 -> 0.816,
Shawnuff 0.816 -> 0.831, Donna Lee 0.854 -> 0.865 lead the twelve up;
Now's The Time (both takes) 0.808 -> 0.788 and 0.802 -> 0.788, KC Blues
0.658 -> 0.643 and Red Cross 0.721 -> 0.708 lead the eight down.

What the three columns say together: at 0.0025 the prior barely decides
and the collision rule does the moving -- more notes on every set, the
Omnibook a little worse (12 down); at 0.015 both hand-score and Omnibook
rhythm are up with more pages up than down, readability up on both,
ties down on both, coverage up on the Omnibook, the instrument's drops
down and its complaint classes down (the laid-back beat written after
the line 693 -> 398, the early offbeat as a sixteenth 4,983 -> 4,636,
the late offbeat as a dotted figure 2,510 -> 2,442) except two that rise
(below), and our pages hold the same notes to within eight of
46,802; at 0.03 the pages read the same or a hair better and the WJazzD
collateral (placement, coverage, Flex-Q rhythm) reads a hair worse, which
is where a page-tuned weight would have been pulled and why the weight
was not set there. Two classes rise. "Pushed beat before it" (644 -> 800 of
191,000): a beat's late note that used to be written on the "a" now
goes to the next beat line where that line is free, which a human
writes more often still. And "binary as triplet" (2,637 -> 2,998): the triplet figure is 3.7% of a
human's beats and the three-onset sixteenth figures 0.3-1.2% each, so
where the tuplet gate admits both, the prior leans ternary; the
Omnibook's triplet row on our pages rose 4.74 -> 4.95% against its 6.02%,
so on the pages this is the right direction, and the WJazzD instrument
is D36's literal layer.

**The brief's ship criteria at 0.015: hand-score rhythm up (7 of 12 up, 1
down), Omnibook rhythm up (12 of 22 up, 8 down), readability not worse
(0.9990 -> 0.9991 and 0.9975 -> 0.9980), the dropped-note count not worse
(the instrument 7,155 -> 5,989; our own pages level), and the round-trip
criterion holds on every band that meets it today. All five hold.** The
default is still 0.0 in this commit; flipping it and re-pinning both
baselines is the listener's call (the brief: stop and ask first).

### The judge, re-run once the prior kept every heard note (2026-09-25, later the same day)

The table above was measured with the push refused at its source only.
Rendering Mobley's All The Things You Are bar by bar for the listener
showed a note still lost in bar 61: beat 3's late note went to beat 4's
line through the fallback, and beat 4's eighth reading put its own first
note on that line. The narrow guard for it (`previous_pushed`, a reading
with a note ON the line the beat before pushed onto) closed the last way
the prior could lose a note, and it also stopped the SHIPPED quantizer's
own losses at those lines wherever the prior is on: the instrument's
drops 7,155 -> 4,203, and on the 79 judge and located pages no page loses
a note at any weight and 94 gain 388 (0.8% of 46,802). The round trip at
0.015 costs 0.5 ms of pooled mean (22.19 against 21.71).

Then the pages read differently, and the smallest weight says why: at
0.0025 the prior barely decides, so that column is the guard alone.

| | shipped | 0.0025 (the guard alone) | 0.015 | 0.03 |
|---|---|---|---|---|
| hand scores, rhythm (n=12) | 0.8452 | 0.8422 (3 up, 5 down) | 0.8451 (4 up, 5 down) | 0.8436 (4 up, 5 down) |
| hand scores, value (n=12) | 0.7769 | 0.7764 | 0.7785 (4 / 4) | 0.7784 |
| hand scores, readability (n=12) | 0.9990 | 0.9990 | 0.9990 | 0.9992 |
| pianists, rhythm, oracle line (n=7) | 0.8664 | 0.8683 | 0.8711 | 0.8693 |
| Omnibook, rhythm (n=22) | 0.7874 | 0.7787 (1 up, 18 down) | 0.7796 (1 up, 16 down) | 0.7800 (3 up, 14 down) |
| Omnibook, value (n=22) | 0.7139 | 0.7098 | 0.7114 | 0.7117 |
| Omnibook, readability (n=22) | 0.9975 | 0.9976 | 0.9979 | 0.9980 |
| Omnibook, coverage (n=22) | 0.7662 | 0.7729 (18 up, 0 down) | 0.7729 | 0.7729 |
| WJazzD Flex-Q coverage, collateral (n=73) | 0.8675 | 0.8725 (55 up, 0 down) | 0.8726 | 0.8726 |
| WJazzD placement (n=73) | 0.855 | 0.8567 | 0.8554 | 0.8547 |
| instrument: dropped of 198,983 | 7,155 | | 4,203 | |
| notes on our 79 pages (of 46,802) | 46,802 | +388, none lost | +388, none lost | +388, none lost |

Two effects, pulled apart:

- **Keeping the notes the shipped quantizer loses at beat lines** costs the
  page score: hand-score rhythm -0.003, Omnibook -0.009 with 18 of 22
  sides down, while coverage rises on every set and no page loses a
  note. The 388 notes are ones the transcribers mostly do not write --
  the recovered note in Mobley's bar 22 is written as a sixteenth figure
  where the page has two eighths -- and notated rhythm is gap-based, so an
  extra note between two matched ones breaks the gap either side of it.
  That the shipped quantizer drops about one heard note in 120 at beat
  lines, and that the pages read better for it, is a finding in its own
  right (D37 below): a note SwingScribe heard vanishes with nothing in
  the log, and the erase tool exists for the listener to judge such
  notes, not the quantizer.
- **The prior on top of that** reads hand-score rhythm +0.003 (0.8422 ->
  0.8451), Omnibook +0.001 (0.7787 -> 0.7796), pianists +0.003, ties down
  on both sets; measured at a level note count (the earlier table, before
  this guard) it read +0.007 and +0.002 with 7 of 12 and 12 of 22 pages up.
  Small, positive, and not what moved the earlier table most.

**The brief's ship criteria, taken as written, do not hold for the code as
it stands**: hand-score rhythm is flat with 5 pages down to 4 up, and
Omnibook rhythm is down. They held for the version measured first, at a
level note count. The two versions differ only in whether the prior is
allowed to lose notes the shipped quantizer loses too, and that is not
a choice this brief settles. Three ways forward, all the listener's:

1. leave the default at 0.0 (the state of this commit): the flag, the
   table and the guards stay for the next corpus;
2. ship the prior with the guard, at 0.015, accepting the page score for
   the notes: re-pin both baselines, and treat the 388 recovered notes as
   the transcriber's erasures to make, not the quantizer's;
3. ship the prior without the previous-beat guard (commit dabf7da's
   behaviour): the earlier table, a level note count, and the shipped
   quantizer's beat-line losses left as they are.

### Shipped (2026-09-26)

The listener read the four Mobley excerpts (the Before and After page)
and chose the note-keeping version: bars 19-20 and 54-55 "closer to the
mark" (and their own bar 19 was wrong on a second listen, and corrected);
bars 22-23 "I would still have written it the way I wrote it" (the B is a
late eighth, not a sixteenth figure) but the note was heard; bars 52-53
"SwingScribe caught a note that I missed", the score corrected. "On the
whole the After were more accurate. If this is representative of
everything, then I would enable that switch."

Enabled: `figure_prior_weight` 0.015 by default (R33), both baselines
re-pinned against the corrected Mobley score. The listener's own
corrections, measured first at the old default, moved Mobley's pitch F1
0.8975 -> 0.9025 and note F1 0.5563 -> 0.5628 and nothing else. Then the
prior at its default against that baseline:

| | old default (corrected score) | shipped |
|---|---|---|
| hand scores, rhythm (n=12) | 0.8453 | 0.8455 (4 up, 5 down) |
| hand scores, value (n=12) | 0.7768 | 0.7786 |
| pianists, rhythm, oracle line (n=7) | 0.8664 | 0.8711 |
| Omnibook, rhythm (n=22, coverage 0.766 -> 0.773) | 0.7874 | 0.7796 (1 up, 16 down) |
| Omnibook, value (n=22) | 0.7139 | 0.7114 |
| Omnibook, readability (n=22) | 0.9975 | 0.9979 |
| WJazzD placement / coverage (n=73) | 0.855 / 0.8675 | 0.8554 / 0.8726 |
| instrument: dropped of 198,983 | 7,155 | 4,203 |
| rows re-pinned in real-audio-baselines.json | | 954 of 2,749 |

The Omnibook's fall is D37's (the recovered notes), not the prior's; the
decomposition is the section above. `wjazz-quantize-baseline.json` is
re-pinned too (page hit 74.8 -> 74.9%, a collateral number). WJazzD note
F1 and beat F1 did not move: nothing above quantize did.

### The figures on our pages, re-tallied at 0.015

`compare` again with the weight on. Share of beats with an onset; the
counts of our beats with an onset are unchanged on the hand-score set
(2,578) and up on the other two (4,956 -> 4,967; 19,151 -> 19,182), which
is the collision rule keeping notes on their own beat.

| figure | hand scores % | ours before | ratio | ours at 0.015 | ratio | Omnibook % | ours before | ratio | ours at 0.015 | ratio | corpus % | ours (WJazzD) before | ratio | at 0.015 | ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 1/2 | 55.03 | 50.35 | 0.91 | 51.20 | 0.93 | 57.29 | 50.50 | 0.88 | 51.64 | 0.90 | 55.05 | 42.34 | 0.77 | 43.56 | 0.79 |
| 0 1/3 2/3 | 5.20 | 5.08 | 0.98 | 5.35 | 1.03 | 6.02 | 4.74 | 0.79 | 4.95 | 0.82 | 3.67 | 3.05 | 0.83 | 3.30 | 0.90 |
| 0 1/4 1/2 3/4 | 2.22 | 0.66 | 0.30 | 0.66 | 0.30 | 3.57 | 1.59 | 0.45 | 1.49 | 0.42 | 4.93 | 2.23 | 0.45 | 2.21 | 0.45 |
| 0 1/2 3/4 | 1.45 | 0.62 | 0.43 | 1.09 | 0.75 | 1.52 | 0.75 | 0.49 | 1.03 | 0.67 | 1.23 | 0.69 | 0.56 | 0.94 | 0.77 |
| 1/2 3/4 | 0.98 | 0.50 | 0.51 | 0.50 | 0.51 | 1.94 | 0.63 | 0.32 | 0.83 | 0.42 | 1.00 | 0.84 | 0.84 | 0.91 | 0.92 |
| 0 1/4 | 0.30 | 1.75 | **5.85** | 0.66 | **2.21** | 0.10 | 1.51 | **14.5** | 0.87 | **8.3** | 0.44 | 1.39 | **3.20** | 0.64 | **1.47** |
| 0 1/4 1/2 | 0.38 | 1.36 | **3.54** | 0.74 | **1.92** | 0.54 | 1.51 | **2.79** | 0.99 | **1.82** | 0.42 | 2.15 | **5.12** | 1.61 | **3.83** |
| 0 1/4 3/4 | 0.00 | 0.47 | - | 0.27 | - | 0.00 | 0.93 | - | 0.74 | - | 0.14 | 1.07 | 7.89 | 0.93 | 6.84 |
| 1/4 1/2 | 0.04 | 0.39 | 9.1 | 0.31 | 7.3 | 0.04 | 0.81 | 19.3 | 0.58 | 14.0 | 0.04 | 1.00 | 23.5 | 0.77 | 18.1 |
| 1/4 | 0.09 | 0.12 | 1.4 | 0.12 | 1.4 | 0.00 | 0.32 | - | 0.14 | - | 0.05 | 0.26 | 5.3 | 0.14 | 2.8 |
| 0 3/4 | 0.04 | 0.31 | 7.3 | 0.43 | 10.0 | 0.27 | 0.46 | 1.7 | 0.74 | 2.7 | 0.26 | 0.49 | 1.9 | 0.56 | 2.2 |
| 3/4 | 0.04 | 0.12 | 2.7 | 0.12 | 2.7 | 0.04 | 0.18 | 4.4 | 0.32 | 7.7 | 0.19 | 0.32 | 1.7 | 0.37 | 1.9 |

The over-written lone-"e" figures come down on every set -- `0 1/4` to a
third of its excess, `0 1/4 1/2` to a half, `1/4 1/2` and `0 1/4 3/4` by a
fifth to a quarter -- and the under-written three-onset sixteenth figures
(`0 1/2 3/4`, `1/2 3/4`) come up toward the human rate, which is the
laid-back beat being written on its beat and the late "a" staying an "a".
Nothing rare went up except the dotted figures `0 3/4` and `3/4`, by a
few beats each (5 -> 8 and 9 -> 16 on the Omnibook): the prior prefers a
lone `3/4` (0.19%) to a lone `1/4` (0.05%) where a beat's one late note
must go somewhere, and a human would more often push it to the next
line. The four-sixteenth deficit and the ternary two-onset figures do not
move, as the diagnostic said they would not: the first is missing onsets,
the second is the tuplet gate.

## Findings to report, not to implement

1. **Tuplet share.** The corpus reads 10.3% tuplet notes whole, 7.9% in
   the bars the plain filter keeps and 5.8% under strict; Wesley Chin's
   hard-bop stratum, the one nearest the judge set, 6.2% (3.7% strict);
   the listener's own pages 11.2%, the Omnibook 14.4%; ours 8.5% on the
   hand-score set and 7.6% on the Omnibook set today, 8.9% and 8.0% at
   0.015 (the survey's tally, the triplet row of the table above). The
   OMR filter's bias against tuplet bars is the largest error in the
   corpus table and the one the listener's cleanup will move; the tuplet
   row's true share is nearer the judge pages' 5-6% of beats than the
   3.7% counted. Our deficit against the listener is not in the
   three-onset triplet (5.35% against 5.20%) but in the figures below.
2. **Figures the humans write that our candidate grids cannot produce.**
   The two-onset ternary figures `1/3`, `0 2/3`, `1/3 2/3`, `2/3` are
   1.0% of the corpus's onset beats, 1.6% of the listener's, 0.4% of the
   Omnibook's, and 0.00% of ours: `min_onsets_for_tuplet` is 3 and
   `offbeat_pair_tuplet_fit` is off, both measured (D28, docs/wjazz-quantize.md).
   The sixteenth-triplet figures `0 1/6 1/3 1/2`, `1/2 2/3 5/6`, `0 1/2
   2/3 5/6`, `0 1/6 1/3 1/2 2/3 5/6` are 0.57% of the corpus's, 0.47% of
   the listener's and 3.1% of the Omnibook's, and 0.00% of ours:
   `sixteenth_triplets` is off, measured. The Omnibook's quintuplet `0
   1/5 2/5 3/5 4/5` (0.13%) has no grid at all. A prior cannot write a
   candidate the set does not hold; these are the gates' decision, and
   the table now says what each gate costs on a human page.
3. **Rests.** A human starts 95% of rests on the beat and 5% on the
   "and", and 0.4% anywhere else; writes eighth 36%, quarter 34%, half
   15%, whole 11%, sixteenth 2.5%. The sixteenth rest is 2.5% here
   against the listener's 0.1% because the lead-trumpet charts are
   sixteenth material: a rule "a sixteenth rest only inside a beat that
   holds sixteenths" would follow the corpus and keep `MIN_REST` at an
   eighth for the judge set. The dotted quarter rest is 0.1% in the
   corpus and 0% in the Omnibook, which is R30's finding from a third
   corpus.
4. **Where a beat depends on the one before.** On the raw figure the
   previous beat carries 0.33 bits held out (its class alone 0.32 with
   seven cells); given the onset count, 0.03. So the dependence is on
   how many notes the next beat holds, not on how they are written: after
   a four-sixteenth beat the next onset beat holds four sixteenths 50.5%
   of the time (the density table above, 1,779 beats), and a three-onset
   sixteenth figure 1.4-3.5%. Our pages write `0 1/4 1/2` at three to five
   times the human rate and `0 1/4 1/2 3/4` at a third to a half of it,
   on every set, and the prior does not move the second: those are
   four-sixteenth beats with a note missing, faithfully written. That is a
   transcribe finding (a sixteenth run's notes dropped or merged
   upstream), and the context that would flag it is the beat before.
5. **The weight's unit** (above): beats per nat presses hardest in time
   on the slowest beats, where humans write finest. Seconds per nat,
   converted per beat like `grid_slack_s`, is the alternative; a human
   ballad page would judge it.
6. **2/2.** A cut-time chart's per-quarter figures are a different
   distribution (pair 44% against 55%, dotted figures two to four times
   as common) and the quantizer has no notion of cut time; the 21 files
   are out of the table.
7. **The tempo staircase from the human side.** Four-sixteenth beats are
   17% of onset beats at 100-160 bpm, 6% at 160-220, 1% at 220-300, 0.3%
   at 300 and over; the eighth pair 30%, 48%, 62%, 75%. D11's rule that
   the running value is set by tempo is what a human page does, and the
   slack in seconds already carries it; given the count no band writes a
   figure differently.
8. **The shipped quantizer loses about one heard note in 120 at beat
   lines** (D37 candidate). A late note pushed onto the next beat line by
   the eighth grid meets the note already there, and notate keeps one:
   388 of 46,802 notes on the 79 judge and located pages, 7,155 of
   198,983 on the annotator's own onsets. With the prior's guards on,
   none is lost. The pages score BETTER without those notes, because the
   transcribers do not write most of them; whether they should be on the
   page is a hearing question for the listener's erase tool, not a
   quantizer's silent decision.
9. **The re-tally.** The count takes four seconds and the corpus is being
   corrected. When it changes: `python scripts/figure_prior.py` for the
   tables, `python scripts/figure_prior.py build` for the shipped JSON
   (and then the quantize tests and, if the default is on, both
   baselines), `compare --db` for the diagnostic.
