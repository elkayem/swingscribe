# MV2H: the outside cross-check on the edit cost (E4)

2026-09-30. MV2H (McLeod and Steedman, ISMIR 2018; [apmcleod/MV2H](https://github.com/apmcleod/MV2H),
MIT, Java) is the published joint measure for audio-to-score transcription:
the mean of five scores -- multi-pitch, voice, meter, note value and
harmony. The Rhythm Perceiver (Shanin, Riley and Dixon, ICASSP 2026) reports
**MV2H 0.92 +- 0.03 with multi-pitch 0.64 +- 0.13** on its "easy" Omnibook
subset (docs/landscape.md section 4). Roadmap E4 named it as the outside
check on our own edit cost. This page is that check: every page the harness
scores as notation (12 hand scores, the pianists' second takes, 22 Omnibook
sides, 3 silver PDF pages) scored by MV2H in three placements, beside our
measures.

**What it says, in six lines:**

- On a single line, **three of MV2H's five components are close to
  constants**. Voice is 1.000 on every page in every placement. Harmony is
  the key signature and nothing else. In the aligned placement meter
  averages 0.99 or more on the hand scores and the Omnibook, because it
  compares the two sides' bar grids and never looks at a note. What varies
  is multi-pitch, plus a lenient note value.
- **Harmony is an artefact on the Omnibook.** LORIA's files write
  `<fifths>0</fifths>` on 21 of the 22 sides (a B-flat blues and an A-flat
  Donna Lee among them). Harmony there asks whether our page, too, wrote no
  key signature: 0.340 [0.204, 0.496]. With the key agreed (arithmetic,
  `mv2h.with_keys_agreed`), Omnibook MV2H reads **0.912 [0.901, 0.922]**
  (grid) instead of 0.780.
- **Under the placement the paper's numbers imply, our Omnibook pages are
  not distinguishable from the Rhythm Perceiver's:** MV2H 0.912 +- 0.025
  with multi-pitch 0.614 +- 0.117 (n=22; grid placement, key agreed, SDs),
  against its 0.92 +- 0.03 and 0.64 +- 0.13. At the performance's own tempo
  the reading is 0.919 +- 0.026 and 0.645 +- 0.124. The sides differ, the
  systems differ, and the paper's placement is inferred, not reported
  (below). That supports "not distinguishable" and nothing stronger.
- **With the key agreed, MV2H ranks pages the way the edit cost does:**
  Spearman rho -0.81 [-0.94, -0.56] (non-aligned) and -0.76 [-0.92, -0.49]
  (grid) over 37 pages. On the pianist A/B it points the same way: the
  oracle line is up on 7 of 7 pianists, +0.017 [+0.010, +0.024] (grid),
  and the edit cost has it better on 6 of 7, -8.1 [-12.4, -3.4]. The two
  disagree on one page, Carl Perkins. **As scored, it does neither**: rho
  with the edit cost is +0.03 inside the Omnibook, and the pianist change is
  +0.002 [-0.067, +0.058]. The difference is two pianists whose two lines
  wrote different key signatures.
- **Most of that agreement is hearing, not notation.** Multi-pitch alone
  ranks pages with the edit cost at -0.84 [-0.91, -0.69] (non-aligned). In
  that placement it *is* our time-free pitch F1 (rho 0.987). MV2H's own
  note value follows ours only weakly: +0.37 [+0.04, +0.63] non-aligned,
  +0.29 [-0.05, +0.57] grid. MV2H confirms the edit cost's ranking but adds
  no notation judgement our own measures lack. Keep it as a comparability
  number, never as a measure to tune on (landscape.md section 4 already
  said so).
- **MV2H's own non-aligned mode (`Main -a`) scores wrong past its first
  alignment**, at the commit used here: it consumes the ground truth's
  meter groupings as it scores (below). Our
  driver re-reads the ground truth for every alignment. Only non-aligned
  readings move, up by +0.007 on average (at most +0.026); no conclusion
  changes.

## Setup

Nothing below enters the repository. Everything was downloaded to
`C:\Users\lkmcg\swingscribe-research\mv2h\`, which holds a `PROVENANCE.txt`
with the same record.

| file | source | size | sha256 | licence |
|---|---|---|---|---|
| `MV2H-79155847.tar.gz` | codeload.github.com/apmcleod/MV2H/tar.gz/79155847f5f50d29f14425101485a18fb2c8906d | 134,146 B | `85ba3b2b99c2e5c7faf02ef3cba6eb916d2397dca266297e5b7bc086745ff3ef` | MIT (Copyright 2018 Andrew McLeod) |
| `OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz` | github.com/adoptium/temurin21-binaries, release `jdk-21.0.12.1+1` | 207,473,347 B | `ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94` (Adoptium's published sum) | GPL v2 with the Classpath Exception |

- **The master tarball, not a release.** The GitHub releases (v1.0-v2.2,
  the last 2020-12-20) ship no jar. Master at 79155847 (2026-07-14) is the
  merge of PR #15, which fixed one `-a` bug: the Music constructor built an
  aligned copy's meter groupings a second time, so `-a` scored a file
  against ITSELF at meter 2/3 (issue #14). A second `-a` bug is still there at this commit (the
  section on the non-aligned mode below). Nothing here depends on `-a` as
  shipped: the aligned placements score once, and the non-aligned one goes
  through our driver.
- **The JDK is a build tool, and the only one.** The machine has no
  `javac`: the Zulu 25 runtime bundled with Audiveris under
  `%USERPROFILE%\.pdf2musicxml` has `java.exe` only. A Linux JDK in WSL
  is outside Smart App Control's reach, so there is no reputation lottery
  (CLAUDE.md). Both archives were unpacked under the WSL home
  (`~/mv2h-tools/jdk-21.0.12.1+1`, 346 MB, and `~/mv2h-tools/MV2H`), with
  no sudo and nothing system-wide. MV2H was compiled with its Makefile's two
  `javac` lines. WSL has no `make`. A copy of the classes is kept at
  `swingscribe-research\mv2h\bin`.
- **Two routes, the same numbers.** The script runs MV2H in WSL by default.
  The readings on this page come from the native route: the Zulu 25
  `java.exe` (which Smart App Control accepts) runs the classes in
  `swingscribe-research\mv2h\bin`, and the WSL JDK's `javac` compiles the
  driver. The aligned placements read the same to every digit on all 44
  pages by both routes, and the WSL route gives the fixed driver's
  non-aligned readings too (checked on Carl Perkins' two lines). The native
  route was used because WSL's VM was holding another task's 4 GB process.
- **Build check:** the README's three examples reproduce to the last
  digit (MV2H 0.8887720755376813, 0.8545454545454545, and the `-F` mean
  0.8716587650415679).
- The pyMV2H port was not used. MV2H's README calls the Java version
  canonical.

## Both sides in MV2H's format (`swingscribe.mv2h`)

MV2H reads a text format: `Note pitch on onVal offVal voice`, `Tatum t`,
`Hierarchy bpb,sbpb tpsb a=al t` and `Key tonic maj|min t`, with times in
milliseconds. Its own MusicXML route
(`evaluate_xml.bash`) goes MusicXML -> MuseScore 3 -> MIDI ->
`mv2h.tools.Converter` -> `Main -a`. That route needs MuseScore in the loop,
and our page is a `Notation` object, not a file. So the package writes the
format directly and makes each choice the way MV2H's own MIDI converter
would:

- **Score time at one tempo.** 120 bpm (`MS_PER_QUARTER` 500) is what
  MuseScore and music21 assume for a file with no tempo mark. A note's
  onset and "value onset" are the same number, because a score has no
  performed time.
- **The meter is the time signature, read as MV2H's MIDI converter reads
  it** (`tools/midi/TimeSignature`): beats per bar, then two sub-beats per
  beat (three in compound metre), with one tatum per sub-beat. A signature
  change, or a bar that does not span its signature (an overfull OMR bar),
  starts a new `Hierarchy`. MV2H restarts its bar count there.
- **Harmony is the key signature only** (major, tonic = 7 x fifths mod
  12). No side writes chord symbols here, and MV2H's MIDI route drops them
  anyway.
- **One voice.** Ours is the line; the reference is its `melody`, the
  same view every page measure reads.
- **Our pitches (and key) move by the page's measured transposition**
  (`alignment.measured_transposition`, the offset the edit cost uses). A hand
  score written an octave from concert pitch is notation, not an error.
- **Our notes are `benchmark.notation_notes`**: ties merged, rests
  dropped, a double-time page halved to true meter. The reference's bars are
  where the score reader puts them: `evaluation.reader_bars` for a
  MusicXML page (an overfull bar moves everything after it), otherwise every
  `beats_per_bar` quarters, as `mscz.parse` places them.

**Checked line for line against MV2H's own MIDI converter.** Two scores,
three bars of 4/4 in B-flat (eighths, a triplet, sixteenths, rests) and two
bars of 3/4 in G, were written as MIDI files by hand and converted by
`mv2h.tools.Converter`. Our writer produced the same lines (sorted), and MV2H
scores each against the other 1.0 on every component in both modes.
`tests/test_mv2h.py` pins both scores' lines. The tests run in CI; Java
never does.

## Placing both sides in time: three placements

MV2H compares times, and a score has none. So the placement is a choice, and it
changes the answer by more than any interval here.

| placement | how | what multi-pitch then measures |
|---|---|---|
| `nonaligned` | Each side from its own zero, at 120 bpm. MV2H's `-a` machinery (McLeod 2019) DTW-aligns the note sequences and maps our times onto the reference's, run through our driver (next section). | Pitch agreement after MV2H's own alignment. It is our time-free pitch F1, at rho 0.987 (n=37). |
| `grid` | Both sides on the reference's clock at 120 bpm. Ours is moved by the whole number of quarters the time-free aligner's pitch-matched notes vote for (`mv2h.grid_shift`, a mode, never one note's word). MV2H's aligned mode (onset within 50 ms, value within 100 ms). | Pitch AND position on one clock. It follows the share of matched notes within a 32nd after the one shift (rho 0.84 with that share). A slipped beat unmatches everything after it. |
| `tempo` | `grid`, rendered at the performance's own tempo (`run_eval.span_bpm`, the median beat of the page's grid, 71-333 bpm) instead of 120. | The same; MV2H's millisecond tolerances become looser or stricter in beats. |

Paired over pages (`evaluation.paired_change`):

- **Non-aligned against grid.** Non-aligned reads lower on every page:
  -0.034 [-0.041, -0.027] on the hand scores (12 of 12) and -0.046
  [-0.051, -0.040] on the Omnibook (22 of 22). Multi-pitch rises (+0.108,
  +0.171): the alignment forgives position. Meter falls (-0.252, -0.375):
  our bar grid is mapped through the DTW warp, and `-a` sets the grouping
  tolerance to 20 ms. Value falls a little (-0.024, -0.025): `-a` sets its
  tolerance to 20 ms too.
- **Tempo against grid.** Almost nothing moves: +0.004 [+0.002, +0.005] on
  the hand scores and +0.007 [+0.005, +0.009] on the Omnibook. The
  rendering tempo, which no paper reports, is NOT a confound worth worrying
  about here.

**Which placement is the paper's?** The paper does not say. It writes
MusicXML through music21 and "report[s] the MV2H metric", following
Martinez-Sevilla et al. (Interspeech 2023). The arithmetic narrows it down:

- MV2H 0.92 with multi-pitch 0.64 needs the other four components to
  average (5 x 0.92 - 0.64) / 4 = **0.99**.
- MV2H's documented MusicXML route is `-a`. Every `-a` build the paper
  could have used predates PR #15 (2026-07-14), and there meter is held to
  about 2/3 even for a perfect transcription (issue #14). Such a build
  cannot exceed (0.64 + 1 + 2/3 + 1 + 1) / 5 = 0.86. The second `-a` bug
  (next section) can only lower meter further, so this bound does not
  depend on any `-a` build being right.
- So the published number is an **aligned-mode** number, both sides on
  one clock at one tempo: our `grid`. One alternative remains: a port
  without either bug.
- Its harmony was 1, or near it. MV2H's MIDI converter defaults a file
  with no key signature to C major, so a music21 output with no key sig
  against LORIA's key-less Omnibook scores 1.
- That is why the paper comparison below uses **grid, key agreed**.

## The non-aligned mode: MV2H's `-a` does not finish, and scores wrong after its first alignment

**It does not finish.** `mv2h.Main -a` scores EVERY co-optimal DTW
alignment and keeps the best, one at a time at about 700 a second. Birks
Works, a 280-note hand score, has 1,228,800 of them: 28 minutes. Over the
44 pages the median is 3e9 and the largest 6e24.

**And it scores them wrong.** At 79155847, `Meter.getF1`
(`src/mv2h/objects/meter/Meter.java`) takes the ground truth's OWN list of
groupings and removes each grouping it matches. `-a` scores every
alignment against one ground truth, so after the first alignment the list
holds only what that alignment failed to match, and meter reads near 0
from then on. Scoring Carl Perkins' first alignment four times on one
ground truth gives meter 0.670, 0.0, 0.0, 0.0. On a freshly read ground
truth, it gives 0.670 every time; Giant Steps behaves the same (0.807, then
0.0). Nothing else is consumed (`evaluateTranscription` copies the note
list before it matches), so multi-pitch, voice, value and harmony are
right, and MV2H's aligned mode, which scores once, is untouched. What `-a`
returns is, in practice, its FIRST alignment's score. On Giant Steps, run
over all 19,968 co-optimal alignments, it returns 0.8251, which is exactly
the first alignment's score. Scored correctly, the page reads 0.8321. The
bug was found in review on 2026-09-30 and checked again independently. It
has not been reported upstream.

**So the script drives MV2H's own classes itself** (`SampledAlign`,
compiled against them at run time). It sets the flags `-a` sets, uses
`Aligner.getPossibleAlignments`, `evaluateTranscription(align(...))` and
MV2H's own "best" comparison, and **parses the ground truth again for
every alignment it scores**. It also chooses which alignments to score:

- **At most `--cap` (2,000) co-optimal alignments:** all of them, in
  `Main -a`'s order.
- **More than that:** 2,000 from the alignments that pair the most notes at
  one pitch (a longest-path pass over MV2H's own alignment DAG; all of them
  when they fit, else a seeded draw), and 2,000 more drawn from the whole
  co-optimal set. The most notes paired is the most multi-pitch, not the
  most MV2H: meter and value move with the alignment too.
- **What it reports:** the case, the counts, which subset the best came
  from, and the worst score seen.
- **With `--shared-truth`** it scores against one ground truth, as `Main -a`
  does. That is a check on the machinery, never a reading.

Scored correctly, a sample's best is a **lower bound** on the exhaustive
answer, by construction. Of the 44 pages, 2 were scored in full, 2 over the
whole most-matches subset, and 40 by sample. The best came from the
most-matches subset on 24 and from the whole-set draw on 18, so neither
draw can be dropped. The best and worst alignments scored on a page differ
by a median 0.024 MV2H (0.012-0.053). The 0.13 this page reported before
the fix was the bug: every alignment after the first lost its meter.

**The checks.** Nine pages have few enough co-optimal alignments to score
every one of them correctly. Each is scored four ways: all of them on a
fresh ground truth (the true answer), the driver at the shipped cap and at
a quarter of it, and `Main -a` as shipped.

| page | co-optimal alignments | all, fresh ground truth | driver, cap 2,000 | driver, cap 500 | `Main -a` as shipped |
|---|---|---|---|---|---|
| Carl Perkins | 48 | 0.9174 | 0.9174 (all) | 0.9174 (all) | 0.8920 |
| Carl Perkins, CREPE line | 80 | 0.9031 | 0.9031 (all) | 0.9031 (all) | 0.8792 |
| Sonny Clark, Another You | 6,912 | 0.9509 | 0.9509 | 0.9509 | 0.9457 |
| Sonny Clark, Another You, CREPE line | 15,360 | 0.9474 | 0.9474 | 0.9474 | 0.9380 * |
| Giant Steps | 19,968 | 0.8321 | 0.8321 | 0.8321 | 0.8251 |
| Art Pepper, For Minors Only | 20,736 | 0.8758 | 0.8756 | 0.8746 | 0.8722 * |
| Scrapple From The Apple | 45,360 | 0.8203 | 0.8193 | 0.8184 | 0.8164 * |
| Giant Steps, CREPE line | 86,016 | 0.7011 | 0.7011 | 0.7006 | 0.6975 * |
| Birks Works | 1,228,800 | 0.9226 | 0.9217 | 0.9188 | 0.9188 |

\* by `--shared-truth`, which reproduces `Main -a`: on the four pages where
`Main -a` itself was run to the end (Carl Perkins' two lines, Sonny Clark,
Giant Steps) the two agree to every printed digit, which is the check that
the driver's machinery is MV2H's. Birks Works' `Main -a` is the 1,707 s run.

- **The driver's reading is never above the true answer** (a lower bound,
  as it must be), and at the shipped cap it is exact on 4 of the 7
  pages that needed a sample or a subset, and at most 0.001 below on the
  other 3 (Art Pepper 0.0003, Scrapple 0.0009, Birks Works 0.0009).
- **`Main -a` is below the true answer on every page**, by 0.004-0.026:
  it keeps the first alignment's score, and on none of these pages is the
  first alignment the best one.
- **The cap matters little.** A quarter of it (500) loses at most 0.004
  on these pages (Birks Works, where 500 never beat the first alignment).
  The whole Birks Works enumeration, correctly scored, took 1,453 s; the
  cap-2,000 reading took 4.6 s.

**What the fix moved.** Non-aligned MV2H rose on 43 of 44 pages and held on
one (Segment): +0.007 on average, +0.026 at most. Meter rose +0.033 on
average (+0.122 at most). Multi-pitch fell a little on 17 pages (-0.0025 on
average): the alignment that pairs the most notes is not always the one
with the best MV2H, and now the best MV2H wins. The set means moved +0.005 to +0.010; every conclusion on this page
survives, and non-aligned still reads below grid on 12 of 12 hand scores
and 22 of 22 Omnibook sides. The aligned placements and our own measures did
not move at all.

Sampling is also what makes the non-aligned placement usable at all: the
44 pages took a median 9.9 s each (at most 31 s) for up to 4,000
alignments.
The aligned placements take 0.2 s.

## Readings

Default take, trusted pairings; set means with a 95% bootstrap interval
resampled over pages. Our measures sit beside them: the edit cost per 100
reference notes, notated rhythm and value (docs/metrics-e4-e6.md), and the
time-free pitch F1. The script recomputed ours from the same snapshot, and
they match the committed pins in `tests/regression/real-audio-baselines.json`
exactly (largest drift 0.0000 over all 44 rows).

**Our measures:**

| set | n | edit cost | rhythm | value | pitch F1 |
|---|---|---|---|---|---|
| hand scores | 12 | 55.3 | 0.846 | 0.779 | 0.863 |
| pianists, CREPE line | 7 | 60.1 | 0.850 | 0.742 | 0.787 |
| Omnibook | 22 | 68.1 | 0.780 | 0.711 | 0.791 |
| PDF pages, silver | 3 | 56.3 | 0.821 | 0.762 | 0.867 |

**MV2H by placement.** "Same key" is MV2H with harmony set to 1
(`mv2h.with_keys_agreed`). Voice is 1.000 everywhere and is left out.

| set | placement | MV2H | same key | multi-pitch | meter | value | harmony |
|---|---|---|---|---|---|---|---|
| hand scores (12) | nonaligned | 0.876 [0.836, 0.906] | 0.902 [0.889, 0.916] | 0.853 [0.814, 0.886] | 0.741 [0.696, 0.786] | 0.917 [0.903, 0.930] | 0.871 |
| | grid | 0.910 [0.871, 0.938] | 0.936 [0.927, 0.944] | 0.745 [0.705, 0.783] | 0.993 | 0.940 [0.930, 0.951] | 0.873 |
| | tempo | 0.914 [0.875, 0.941] | 0.939 [0.929, 0.949] | 0.759 [0.716, 0.801] | 0.993 | 0.943 [0.932, 0.953] | 0.873 |
| pianists, CREPE line (7) | nonaligned | 0.850 [0.791, 0.900] | 0.879 [0.845, 0.910] | 0.771 [0.690, 0.841] | 0.712 | 0.911 | 0.855 |
| | grid | 0.891 [0.833, 0.933] | 0.920 [0.900, 0.938] | 0.683 [0.592, 0.770] | 0.992 | 0.924 | 0.856 |
| | tempo | 0.895 [0.838, 0.937] | 0.924 [0.902, 0.943] | 0.701 [0.603, 0.791] | 0.992 | 0.926 | 0.856 |
| Omnibook (22) | nonaligned | 0.734 [0.707, 0.761] | 0.866 [0.852, 0.880] | 0.784 [0.738, 0.824] | 0.624 [0.578, 0.667] | 0.921 [0.911, 0.931] | 0.340 [0.204, 0.496] |
| | grid | 0.780 [0.754, 0.806] | **0.912 [0.901, 0.922]** | 0.614 [0.566, 0.661] | 0.999 | 0.945 [0.935, 0.955] | 0.340 |
| | tempo | 0.787 [0.761, 0.813] | 0.919 [0.908, 0.929] | 0.645 [0.595, 0.695] | 0.999 | 0.949 [0.939, 0.959] | 0.340 |
| silver pages (3) | nonaligned | 0.790 [0.672, 0.896] | 0.857 [0.802, 0.896] | 0.862 [0.811, 0.897] | 0.509 [0.227, 0.666] | 0.912 | 0.667 |
| | grid | 0.798 [0.679, 0.922] | 0.865 [0.794, 0.922] | 0.470 [0.279, 0.648] | 0.912 [0.760, 0.996] | 0.942 | 0.667 |
| | tempo | 0.800 [0.684, 0.926] | 0.867 [0.791, 0.926] | 0.479 [0.267, 0.668] | 0.912 | 0.944 | 0.667 |

- **The key signature decides the Omnibook's as-scored MV2H.** Harmony is
  0 on 10 sides (mostly our B-flat against LORIA's C), 0.5 on 9 (a fifth
  apart: our F against C, and on Scrapple our C against the book's F) and
  1 on 3 (one at 0.98). The spread of as-scored MV2H across sides (SD
  0.064, grid) is mostly that term: with the key agreed the SD is 0.025.
  On the hand scores,
  harmony costs only on two pages whose key signature has no flats or
  sharps: Billy Boy (ours E-flat, 0) and Giant Steps (ours G, 0.5).
- **The silver pages break the grid placement.** Embraceable You (a 71 bpm
  ballad whose OMR page has three bar-line steps, docs/metrics-e4-e6.md)
  keeps 57% of its matched notes on one clock. Its multi-pitch is 0.279
  in the grid placement and 0.878 non-aligned. n=3 supports nothing beyond
  that.

## Against our measures, page by page

Spearman rho over the default takes of every trusted page (hand + Omnibook
+ silver, n=37), with a 95% bootstrap interval over pages:

| MV2H reading | ~ edit cost | ~ rhythm | ~ value | ~ pitch F1 |
|---|---|---|---|---|
| MV2H, nonaligned | -0.45 [-0.68, -0.15] | +0.43 [+0.14, +0.65] | +0.41 [+0.10, +0.65] | +0.52 [+0.21, +0.74] |
| MV2H, grid | -0.36 [-0.62, -0.04] | +0.35 [+0.06, +0.59] | +0.36 [+0.02, +0.64] | +0.48 [+0.17, +0.72] |
| same key, nonaligned | **-0.81 [-0.94, -0.56]** | +0.72 [+0.47, +0.87] | +0.63 [+0.33, +0.83] | +0.64 [+0.35, +0.84] |
| same key, grid | **-0.76 [-0.92, -0.49]** | +0.64 [+0.37, +0.82] | +0.65 [+0.35, +0.86] | +0.66 [+0.37, +0.85] |
| multi-pitch, nonaligned | -0.84 [-0.91, -0.69] | +0.50 [+0.22, +0.70] | +0.66 [+0.43, +0.81] | +0.99 [+0.96, +1.00] |
| multi-pitch, grid | -0.72 [-0.90, -0.45] | +0.61 [+0.35, +0.79] | +0.61 [+0.31, +0.82] | +0.68 [+0.41, +0.88] |
| meter, nonaligned | -0.60 [-0.80, -0.32] | +0.76 [+0.52, +0.91] | +0.54 [+0.21, +0.78] | +0.31 [-0.01, +0.60] |
| meter, grid | +0.13 [-0.21, +0.44] | -0.26 [-0.55, +0.06] | -0.23 [-0.53, +0.12] | -0.02 [-0.36, +0.33] |
| value, nonaligned | -0.34 [-0.61, +0.01] | +0.38 [+0.09, +0.62] | +0.37 [+0.04, +0.63] | +0.04 [-0.29, +0.38] |
| value, grid | -0.25 [-0.53, +0.08] | +0.16 [-0.14, +0.42] | +0.29 [-0.05, +0.57] | +0.03 [-0.30, +0.35] |

Inside each set:

- **Omnibook (n=22).** As scored, MV2H does not rank the sides at all:
  rho with the edit cost is -0.03 [-0.49, +0.42] (non-aligned) and +0.03
  [-0.48, +0.48] (grid). With the key agreed it is -0.87 [-0.98, -0.62]
  and -0.88 [-0.97, -0.65].
- **Hand scores (n=12).** As scored: -0.57 [-0.91, +0.10] and -0.47
  [-0.87, +0.22]. With the key agreed: -0.85 [-0.99, -0.47] and -0.73
  [-0.98, -0.25].

What the table says: MV2H's agreement with the edit cost comes through
multi-pitch (the hearing edits, 40-44% of the edit cost) and, non-aligned,
through meter. Meter is then the DTW warp, which is our rhythm by another
road (+0.76). Its note value is the weakest link to our value (+0.29 to
+0.37). It is lenient by construction: a note is charged only if both it and
the next note matched, anything within 100 ms (aligned) is full credit,
and beyond that it takes partial credit, 1 - |difference| / reference
duration. At 120 bpm a triplet eighth written as an eighth is an 83 ms
difference, which is full credit.

## The pianists' two lines

The oracle line (default) against the CREPE line, paired over the seven
pianists with hand scores:

| reading | change | pages up / down | sign test p |
|---|---|---|---|
| edit cost | -8.1 [-12.4, -3.4] | 6 better of 7 (E4) | |
| MV2H, nonaligned | +0.016 [-0.047, +0.069] | 6 / 1 | 0.125 |
| MV2H, grid | +0.002 [-0.067, +0.058] | 6 / 1 | 0.125 |
| same key, nonaligned | +0.030 [+0.016, +0.047] | 7 / 0 | 0.016 |
| same key, grid | +0.017 [+0.010, +0.024] | 7 / 0 | 0.016 |

As scored, the interval spans zero. The cause is two pages where the lines
wrote different key signatures:

- **Billy Boy.** The oracle line wrote E-flat against the listener's
  key-less page (harmony 0). The CREPE line wrote none (harmony 1). As
  scored, the CREPE line wins by 0.18 (grid), though its edit cost is
  worse (67.6 against 62.9).
- **Giant Steps.** The oracle line wrote G, a fifth from the page's C
  (0.5). The CREPE line wrote E-flat (0).

With the key agreed, MV2H and the edit cost point the same way on 6 of the
7 pianists. The seventh is Carl Perkins: there the oracle line's edit cost
is 1.9 worse (53.3 against 51.4), while same-key MV2H rates it better
(+0.010 grid, +0.014 non-aligned). Both lines write the page's key there, so
the key is not why.

## Against the paper's 0.92

| | MV2H | multi-pitch | other four |
|---|---|---|---|
| Rhythm Perceiver, Omnibook "easy" subset (n not given; +- presumably SD) | 0.92 +- 0.03 | 0.64 +- 0.13 | 0.99 (implied) |
| SwingScribe, Omnibook, grid, key agreed (n=22, +- SD) | 0.912 +- 0.025 | 0.614 +- 0.117 | 0.986 |
| SwingScribe, Omnibook, tempo, key agreed (n=22) | 0.919 +- 0.026 | 0.645 +- 0.124 | 0.987 |
| SwingScribe, Omnibook, grid, as scored (n=22) | 0.780 +- 0.064 | 0.614 | 0.821 |

Read the first two rows as "not distinguishable", and no stronger:

- **Different sides.** Theirs is the "easy" 60% of the test subset of
  Riley and Dixon's Omnibook setup (SMC 2024), without the fast tempi,
  poor recordings and busy accompaniments of the "hard" 40%. Ours is the 22 sides with audio on disk, tempi 115-333 bpm, no
  subset taken.
- **Different setup.** Their MV2H setup is unreported, and the placement
  above is inferred from arithmetic.
- **One component carries the comparison.** It rests on multi-pitch
  (0.61-0.65 against 0.64); in the comparable reading the other four are
  constants or near it.
- **Sign.** The as-scored 0.780 is what MV2H says about our Omnibook pages
  against LORIA's files. The 0.912 is what it would say had we written
  LORIA's key signature. Neither is the page quality.
- **Where that leaves the comparison.** Against this paper, what
  discriminates is multi-pitch in an aligned placement: pitch and position
  on one clock. There we are level with it. The paper's rhythm accuracy
  (0.53) is a different measure from our rhythm (0.780), which is gap-based
  over the time-free alignment. They cannot be compared.

## Caveats

- **MV2H on one line is mostly constants.** Voice cannot be anything but 1.
  Harmony is a key-signature test. Aligned meter only checks that both
  sides wrote the same time signature on the same clock; every page here is
  on the bar (E4), so it reads 0.99+. A page that gets most pitches right
  therefore scores 0.9 whatever its rhythm looks like. Quote multi-pitch and
  value beside it, always.
- **The harmony term depends on the reference's encoding.** Before any
  claim about key signatures, look at what the reference file writes. A
  key-signature judgement belongs to the Key menu (the listener's choice
  since 2026-09-29), not to a measure.
- **Never quote `Main -a` as shipped.** At 79155847 it returns, in effect,
  its first alignment's score (the section above). Any published
  non-aligned MV2H made with it carries the same fault.
- **Non-aligned is a sampled lower bound** past 2,000 co-optimal
  alignments (42 of 44 pages; 40 of them sampled). It was checked against
  every alignment, correctly scored, on nine pages of up to 1.2 million
  alignments (above). A page with 1e24 alignments has not been checked
  that way, and cannot be.
- **The grid shift is ours.** One whole-quarter shift per page, voted by
  the time-free aligner's matched notes: an input MV2H did not choose. The
  non-aligned placement exists so that one reading involves no decision of
  ours at all.
- **A slipped beat costs the grid placement everything after it**, where our
  gap-based rhythm charges it once. The grid multi-pitch is part pitch and
  part "stayed on one clock" (rho 0.84 with the on-clock share).
- **n is small** everywhere but the pooled 37. The silver set (3) says
  nothing on its own.
- **Transient empty answers.** On this machine, a `wsl.exe` launched beside
  others now and then returned nothing at all: two runs of 132 in one pass,
  none in the pass before, on the same files. `run_mv2h` retries an empty
  answer. MV2H's output is deterministic, so a retry is safe.

## Reproduce

Read the harness caches only through snapshots; another process may be
rewriting the live ones. `--work` must be outside the repo, because it
receives note lists derived from commercial recordings (the script checks).

    .venv/Scripts/python.exe scripts/mv2h_eval.py \
        --notes SNAP/.benchmark-notes-c0.2-d0.0.json --grids SNAP/.benchmark-grids.json \
        --pins tests/regression/real-audio-baselines.json --work OUTSIDE_THE_REPO \
        --jobs 2 --heap 384m --cap 2000 --json card.json \
        --java %USERPROFILE%\.pdf2musicxml\audiveris-5.11.0\Audiveris\runtime\bin\java.exe \
        --classpath C:\Users\lkmcg\swingscribe-research\mv2h\bin

- **What the script expects.** With no `--java`, everything runs in WSL:
  `~/mv2h-tools/{jdk-21.0.12.1+1,MV2H/bin}` in the distro `Ubuntu`
  (`--mv2h-home`, `--jdk`, `--distro`). With `--java` it needs
  `--classpath`, and it compiles the driver with `--javac` if given, else
  with the WSL JDK's.
- **What this run took.** 279 s of MV2H with two native JVMs, after a 36 s
  page build. `--heap` bounds each JVM: the commit charge on this machine
  was within 3 GB of its limit that afternoon.
- **Which notes it scored.** This run used the pre-hybrid notes snapshot
  (sha256 `93b66506...`, CREPE-only, the notes the committed pins were
  computed on), with pages built by the HEAD tree (0049aee).
- **Not in `run_eval`.** MV2H needs a JDK the harness should not assume. It
  is a comparability column, run on demand, never a pin.
