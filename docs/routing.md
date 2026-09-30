# Routing: suggesting the ensemble and the lead stem from the stems

2026-09-30. Roadmap O2. `src/swingscribe/routing.py` is the rule,
`scripts/routing_survey.py` the measurement, `tests/test_routing.py` the
pins (40 tests; 37 run in CI without numpy -- the two wav readers and the
numpy percentile check skip there). `gui/suggestion.py` is the GUI's
adapter over it.

## Why

`ensemble` decides whether the piano model is consulted
(`TranscribeConfig.uses_piano_oracle`: trio and solo-piano yes, horn-led
no), and its default is horn-led. So every piano solo loses the oracle's
gain unless the listener remembers to change the menu; three benchmark
piano solos once skipped it through `ensemble: null`, and the guide's
troubleshooting has to say "a piano solo is not getting the piano model".
The stems already on disk say who is playing, and reading them costs no
model: 0.37-0.54 s for a 75-second span of six stems, 2.8 s for a
nine-minute file (warm disk cache, two runs).

The two errors are not symmetric, and that decides every threshold:

- suggesting **horn-led for a piano solo** is the status quo -- the default
  already says it -- and costs the oracle's gain;
- suggesting **trio for a horn** costs the whole line: a piano model asked
  about a saxophone vouches for nothing and rejection deletes every note
  (CLAUDE.md, "NEVER route a horn to the piano oracle").

So the output is a SUGGESTION with its reason, never a setting, and the
piano call needs two tests to agree, each of which alone refuses every horn
span and window measured. Anything between the bands is "no suggestion",
said out loud.

## The measure

Per span, per stem, from the stem wavs over the span: one mono mean square
per second. Two numbers carry the decision.

- **piano share**: of the span's *active* seconds, the share in which
  `piano` is the loudest of the melodic stems (`other`, `vocals`,
  `guitar`, `piano`). A second is active when its loudest melodic stem is
  within 30 dB of the span's loud level (the 95th percentile of that
  per-second maximum) and above -80 dBFS, so silence and bleed between
  phrases vote for nobody.
- **piano margin**: the piano stem's RMS over the span, in dB, minus the
  loudest other melodic stem's.

Plus four guards, each of which refuses before any call:

- the stem set must be **whole**, all six stems. With the other melodic
  stems missing the piano "leads" every second by default, and with the
  bass missing the lead guard below reads nothing -- a partial whole-file
  directory (one stem copied across from another cache, CLAUDE.md) would be
  the horn-called-trio direction. A four-stem separation, which has no
  piano stem at all, is told apart and says so;
- the separator must be one the rule was **measured on**: bsroformer_sw
  (`SUGGEST_MODELS`; htdemucs_6s failed both ways, below);
- **15 s of active melody** (`MIN_ACTIVE_S`; placed by the floor sweep,
  below);
- for a piano call, the piano within **9 dB of the loudest stem** of all
  six: a lead, not a comp under a bass solo.

## The rule

| call | when | lead stem |
|---|---|---|
| **trio** | piano share >= 0.9 AND margin >= +6 dB AND the piano within 9 dB of the loudest stem | `piano` |
| **solo-piano** | as trio, and the bass stem >= 20 dB and the drums >= 30 dB under the piano | `piano` |
| **horn-led** | piano share <= 0.6 AND margin <= +3 dB | the non-piano melodic stem loudest most often |
| **none** | anything else; any guard above | -- |

Trio and solo-piano route identically (`uses_piano_oracle`), so a wrong
choice between them costs nothing. `confidence` is 0.5 at a boundary rising
to 1.0 a band past it: a normalised distance from the thresholds, NOT a
probability. Eleven piano spans cannot calibrate one. Every value in
`evidence` is finite (JSON has no infinity).

## Ground truth

The 111 `*.swingscribe.json` under `benchmark/` (the brief said 108; three
Transcriptions_Other pages were paired on 2026-09-29): 95 horn-led, 11
trio, 5 `ensemble: null`. The nulls are scored as horn-led -- they behave
like it (CLAUDE.md), and all five are horn solos on `stem: other` (Art
Pepper twice, Dexter Gordon, Hank Mobley twice). Every sidecar's stems
were on disk for its model (bsroformer_sw, all 111) in
`benchmark/.swingscribe-cache`: 64 whole-file sets, 47 span-scoped. Nothing
was separated, ingested or transcribed; `pipeline.cached_document` reads
the ingest record without running it.

## Results, bsroformer_sw (the default separator)

**Confusion, n = 111 spans:**

| truth \ suggested | trio | horn-led | none |
|---|---|---|---|
| horn-led (100) | **0** | 100 | 0 |
| trio (11) | 11 | 0 | 0 |

**The separating margin** -- the honest number, because the thresholds were
placed after looking at these same spans:

| | worst horn span (n=100) | threshold | worst trio span (n=11) |
|---|---|---|---|
| piano share | 0.548 (Chet Baker, There Will Never Be Another You, solo 75) | 0.9 | 0.983 (Hancock, Gingerbread Boy; Garland, Oleo) |
| piano margin | +0.4 dB (the same Chet Baker) | +6 dB | +12.9 dB (Garland, Oleo) |
| piano under the loudest stem | -- | 9 dB | 5.6 dB (Flanagan, Giant Steps) |
| active seconds | -- | 15 s | 17 s (Carl Perkins, For Minors Only) |

The share threshold sits 0.35 above the worst horn and 0.08 below the
worst trio; the margin threshold 5.6 dB above the worst horn and 6.9 dB
below the worst trio. The share threshold sits nearer the worst trio than
the worst horn on purpose: a missed piano solo is the default's own
failure, a horn called trio is not.

**The leak check.** A threshold re-derived without the held-out span (the
midpoint of the gap between the worst horn and the worst trio on each test)
classifies 111 of 111. That says only that the classes do not overlap; it
cannot say how close the next piano solo will come. The margin above is
the measure to trust, and the sub-windows, the probes and the second
separator below are the tests the thresholds were not placed on.

The eleven trio spans:

| span | s | piano share | margin dB | under loudest dB | call | conf. | stem (sidecar / suggested) |
|---|---|---|---|---|---|---|---|
| Hancock, Gingerbread Boy (186) | 118 | 0.983 | +15.1 | 0.0 | trio | 0.91 | piano / piano |
| Garland, Oleo (365) | 59 | 0.983 | +12.9 | 0.0 | trio | 0.92 | piano / piano |
| Carl Perkins, For Minors Only | 17 | 1.000 | +60.0 | 2.2 | trio | 1.00 | piano / piano |
| Peterson, Lover Come Back To Me | 115 | 1.000 | +15.4 | 0.0 | trio | 1.00 | piano / piano |
| Garland, Billy Boy | 101 | 1.000 | +75.0 | 0.0 | trio | 1.00 | piano / piano |
| Sonny Clark, Melody for C | 139 | 1.000 | +36.8 | 0.0 | trio | 1.00 | piano / piano |
| Sonny Clark, There Will Never Be Another You | 76 | 1.000 | +31.0 | 0.0 | trio | 1.00 | piano / piano |
| Flanagan, Giant Steps | 62 | 1.000 | +90.6 | 5.6 | trio | 1.00 | piano / piano |
| Hancock, Dolores (185) | 101 | 1.000 | +26.4 | 0.0 | trio | 1.00 | piano / piano |
| Hancock, Orbits (188) | 80 | 1.000 | +38.0 | 0.4 | trio | 1.00 | piano / piano |
| Kelly, Soul Station | 75 | 1.000 | +55.5 | 0.0 | trio | 1.00 | piano / piano |

The ten horn spans nearest the piano side:

| span | s | piano share | margin dB | call | conf. |
|---|---|---|---|---|---|
| Chet Baker, There Will Never Be Another You (75) | 31 | 0.548 | +0.4 | horn-led | 0.54 |
| Shorter, Adam's Apple (426) | 133 | 0.481 | -0.6 | horn-led | 0.60 |
| Shorter, Footprints (431) | 128 | 0.477 | -0.4 | horn-led | 0.60 |
| Dorham, In 'n Out (251) | 119 | 0.429 | -1.0 | horn-led | 0.64 |
| Coltrane, My Favorite Things (228) | 141 | 0.411 | -1.3 | horn-led | 0.66 |
| Morgan, Totem Pole (277) | 112 | 0.348 | -2.1 | horn-led | 0.71 |
| Henderson, The Sidewinder (203) | 111 | 0.333 | -2.8 | horn-led | 0.72 |
| Morgan, The Sidewinder (276) | 113 | 0.310 | -4.4 | horn-led | 0.74 |
| Coleman, Maiden Voyage (171) | 62 | 0.290 | -4.1 | horn-led | 0.76 |
| Hubbard, Dolphin Dance (166) | 130 | 0.271 | -5.3 | horn-led | 0.77 |

Confidence: trio 0.91-1.00 (median 1.00), horn-led 0.54-1.00 (median
0.93).

**Sub-windows inside every labelled span**, 1 s steps (a listener's
selection is rarely the sidecar's exact span). "Unsure" is judged and no
suggestion; "short" is under 15 s of active melody, refused before any
test -- a 15-s window is short when any one of its seconds is quiet.

| window | horn: trio / horn-led / unsure / short | trio: trio / unsure / short | worst horn: share; margin | worst trio: share; margin |
|---|---|---|---|---|
| 10 s | **0** / 0 / 0 / 8,924 | 0 / 0 / 844 | -- | -- |
| 12 s | **0** / 0 / 0 / 8,724 | 0 / 0 / 822 | -- | -- |
| 15 s | **0** / 8,030 / 72 / 322 | 699 / 0 / 90 | 0.800; +3.0 dB (one Adam's Apple window) | 0.933; +6.8 dB |
| 20 s | **0** / 7,867 / 57 / 0 | 736 / 0 / 0 | 0.750; +2.2 dB | 0.947; +7.4 dB |
| 30 s | **0** / 6,898 / 28 / 0 | 636 / 0 / 0 | 0.733; +1.9 dB | 0.964; +8.7 dB |
| 60 s | **0** / 4,149 / 4 / 0 | 336 / 0 / 0 | 0.617; +0.7 dB | 0.982; +12.0 dB |

## The floor: why 15 s of melody

The first version refused under 10 s and reported the 10-second windows as
safe: "the AND of the two tests still separates". Stepped at 1 s instead
of 5 and read jointly rather than one test at a time, it was not safe with
margin. At 10 s one horn second in ten is all that keeps a window under the
share test, and nine horn windows passed it; the loudest of those, 51-61 s
into Shorter's Adam's Apple solo, sat at +3.6 dB, 2.4 dB from the level
threshold -- one test was all that stood between that horn and the piano
model. (Separately, the old doc said the 15 trio windows with no suggestion
at 10 s each held a silent second; 13 did, and 2 were judged and failed the
margin, Garland's Oleo at 0 s and Hancock's Gingerbread Boy at 20 s.)

The floor sweep judges every window 10-40, 45, 50 and 60 s long at 1 s
steps inside the 111 labelled spans, under each floor:

| floor | horn windows judged | pass the share test | pass the level test | worst horn share | worst horn margin | trio windows called / judged | worst trio share; margin |
|---|---|---|---|---|---|---|---|
| 10 s | 244,707 | **9** (worst +3.6 dB) | 0 | 0.909 | +3.8 dB | 22,485 / 22,499 | 0.900; +4.4 dB |
| 11 s | 235,755 | **2** (worst +2.5 dB) | 0 | 0.909 | +3.5 dB | 21,640 / 21,649 | 0.909; +5.0 dB |
| 12 s | 226,910 | 0 | 0 | 0.857 | +3.5 dB | 20,806 / 20,810 | 0.917; +5.4 dB |
| 13 s | 218,160 | 0 | 0 | 0.857 | +3.5 dB | 19,981 / 19,982 | 0.923; +5.8 dB |
| 14 s | 209,513 | 0 | 0 | 0.857 | +3.0 dB | 19,164 / 19,164 | 0.929; +6.3 dB |
| **15 s** | 200,966 | 0 | 0 | **0.824** | **+3.0 dB** | **18,359 / 18,359** | 0.933; +6.8 dB |
| 16 s | 192,520 | 0 | 0 | 0.824 | +3.0 dB | 17,566 / 17,566 | 0.938; +7.0 dB |
| 18 s | 175,927 | 0 | 0 | 0.789 | +2.6 dB | 16,012 / 16,012 | 0.944; +7.4 dB |
| 20 s | 159,742 | 0 | 0 | 0.762 | +2.2 dB | 14,505 / 14,505 | 0.950; +7.6 dB |

15 s is the first floor at which every horn window is more than one of its
own seconds short of the share threshold (the highest, 0.824 on a 17-s
window of Coltrane's My Favorite Things, is 0.076 short where one second is
0.059; any share at most 0.824 over at least 15 active seconds is 1.1 s
short or more) AND every judged trio window keeps its call. From there
each piano test alone refuses every horn -- share at most 0.824, margin at
most +3.0 dB (16 s of Adam's Apple) -- so the AND is two guards, not one.
At 12-14 s no horn window passes the share test either, but the highest,
0.857 on 14 s, is 0.6 s from it. The cost is the minimum selection: 15 s
of melody, against a shortest benchmark span of 17.4 s (Carl Perkins, 17
active seconds).

**Probes that contain a horn**, which must never be called trio (n = 44,
all horn-led):

- the whole file of every horn track with a whole-file stem set (39):
  piano share 0.02-0.57;
- a horn solo selected together with the piano solo next to it, on the
  files that hold both (5). This is the Dolores case: CLAUDE.md's "a third
  of its span is Hancock's piano" was the whole Miles Davis Dolores file,
  whose three sidecars now split it into three soloists, and whose horn
  spans read the piano stem at digital zero (-117 dB) on Dolores, Orbits
  and Gingerbread Boy alike: Hancock lays out behind Miles and Shorter
  there, or the separator hears nothing of him. Selected together:

| probe | piano part | piano share | margin | call |
|---|---|---|---|---|
| Shorter + Hancock, Dolores | 58% | 0.568 | +1.8 dB | horn-led (0.53) |
| Shorter + Hancock, Orbits | 55% | 0.552 | +2.0 dB | horn-led |
| Shorter + Hancock, Gingerbread Boy | 51% | 0.514 | +1.7 dB | horn-led |
| Coltrane + Garland, Oleo | 34% | 0.425 | -6.2 dB | horn-led |
| Pepper + Perkins, For Minors Only | 14% | 0.203 | -7.9 dB | horn-led |
| Miles Davis Dolores, whole file | ~1/3 | 0.287 | -7.7 dB | horn-led |

(The last row is one of the 39 whole-file probes, shown for comparison.)
Above a piano share of 0.4 the reason says two leads take turns and to
select the piano solo alone, rather than claiming the horn "carries" the
span.

**A piano solo selected a little wide.** The rule does NOT keep every
selection with a horn in it horn-led, and an earlier version of this page
said it did. The share threshold is 0.9, so a tenth of a selection may be
somebody else. The edge probes take each piano solo with k seconds of the
horn solo before it:

| piano solo (the horn before it; gap) | 0 s | 2 | 5 | 8 | 10 | 12 | 15 | 20 | 30 s |
|---|---|---|---|---|---|---|---|---|---|
| Hancock, Gingerbread Boy (Shorter; 2.0 s) | trio | trio | trio | trio | trio | trio | none | none | none |
| Hancock, Dolores (Shorter; 0.2 s) | trio | trio | trio | trio | none | none | none | none | none |
| Hancock, Orbits (Shorter; 0.8 s) | trio | trio | trio | trio | none | none | none | none | none |
| Garland, Oleo (Coltrane; overlapping 2.0 s) | trio | none | none | none | none | none | none | none | none |
| Perkins, For Minors Only (Pepper's solo ended 70 s before) | trio | none | none | none | none | horn-led | horn-led | horn-led | horn-led |

Up to 8-12 s of the end of Shorter's solos, in front of a 80-118 s piano
solo, is still called trio; past that, no suggestion, and never horn-led
within 30 s on the four adjacent pairs. The selection IS the piano solo,
so trio is its right answer -- and the horn's last seconds are what pays:
the piano model judges them too. The 0 s column is the piano span on the
pair's own 1 s grid, which starts at the horn solo's start, so a fraction
of a second of the horn falls into its first window; that is why its
margins read a few dB under the span table's. What precedes Perkins' solo
is 40-70 s after Pepper's ends and unlabelled.

**Lead stem, sidecar against suggested:** 110 of 111 agree (99 horns on
`other`, all 11 pianists on `piano`). The one difference is Pat Metheny's
Nothing Personal, where the sidecar has the four-stem sum
`other+vocals+guitar+piano` and the suggestion is `guitar`, which is where
the sum's lead is (guitar loudest in 0.99 of the seconds). No sidecar under
the Roformer needs a sum for a horn split across stems; the suggestion never
proposes one.

## A second separator: htdemucs_6s, held out -- and refused

The same spans on htdemucs_6s stems (87 of the 111 have them on disk, all
whole-file sets from the batch's locate pass; 5 of them trio). The
thresholds were fixed on the Roformer before this was run, so it is the
one fully held-out test, and it failed in both directions:

- **Piano solos out of `piano`.** Hancock's Dolores and Orbits and
  Garland's Oleo read piano share 0.34-0.50 with `guitar` leading. The
  first version called them horn-led on `guitar` -- the default's failure,
  with a confident reason attached. Of the five trio spans, 1 was called
  trio even so.
- **A horn nearly in `piano`.** Inside Coltrane's soprano solo on My
  Favorite Things, at 1 s steps under the 15 s floor, 8 horn windows pass
  the share test (up to 0.941, 17 s) and the loudest horn window reads
  +5.1 dB, 0.9 dB short of a trio call; the loudest horn window that also
  passes the share test is 0.933 at +4.9 dB. At the old 10 s floor, 49
  passed the share test, one of them at share 1.000 (11 s), and the
  loudest read +5.6 dB. The Roformer's loudest window in that solo reads
  +0.4 dB. The span itself (piano share 0.397, -1.2 dB) was safe; its
  windows were not, with margin.

So nothing is suggested on any separator but bsroformer_sw
(`SUGGEST_MODELS`), and the reason says to separate with bsroformer_sw:

| htdemucs_6s, now | trio | horn-led | none |
|---|---|---|---|
| horn spans (82) | 0 | 0 | 82 |
| trio spans (5) | 0 | 0 | 5 |
| horn windows at the 15 s floor, 10-60 s (210,493) | 0 | 0 | 173,051 judged, 37,442 short |
| probes containing a horn (56) | 0 | 0 | 56 | The
evidence is still computed, which is how the survey reports the numbers
above. A four-stem separation (htdemucs, htdemucs_ft) has no piano stem and
says so. A new separator joins `SUGGEST_MODELS` when
`scripts/routing_survey.py --model <it>` shows both piano tests refusing
every horn window alone.

## Bass solos: the guard that no label measures

No sidecar labels a bass solo. Scanning every whole-file Roformer set for
stretches where the piano passes both tests while sitting under another
stem turned up three that TRACE as bass solos -- the piano sparse and
10-20 dB down, the bass steady, the drums quiet: Soul Station 390-455 s,
Flanagan's Giant Steps 170-230 s, Melody for C 370-400 s. Selected whole
they read the piano 11.5, 16.0 and 13.3 dB under the bass; at a 12 dB
guard the first was called trio, at 9 dB all three are no suggestion.

Windows inside them are not all refused. At 1 s steps, 30-s windows lying
wholly inside Soul Station's stretch (421-455 s) read trio with the piano
8.7-8.9 dB under the bass, and 20-30 s windows straddling the start of
Flanagan's and Melody for C's, where the piano solo is still ending, read
trio at up to 8.7 and 8.5 dB. (The first version said two windows, at
8.2-8.4 dB; that was at 5 s steps.) Judged trio windows inside the
labelled piano solos sit at most 7.6 dB under the loudest stem, so an 8 dB
guard would refuse those windows at no labelled cost -- but 0.4 dB from
the labelled windows, placed on three stretches nobody has labelled, is a
guess, and the error it would prevent is not the costly one: a bass solo
called trio suggests the piano stem, it sends no horn to the piano model.
The guard stays at 9 dB until a bass solo is labelled. Piano trading fours
with the drums (Flanagan, 250-300 s) sits 6-8 dB under the drums over 20 s
and is still a piano call, which is right: the piano is the only line
there.

## Untested

- **Solo piano**: no benchmark recording is one (n = 0). One
  unaccompanied stretch exists on disk (Flanagan's Giant Steps, about
  345-360 s, bass and drums at digital zero); selected alone (345-358 s)
  it reads solo-piano, and any window that takes in a few seconds of the
  bass reads trio. Both route the same way.
- **Vibes, organ, Rhodes.** The rule reads the `piano` STEM. Any lead the
  Roformer files under `piano` would be suggested trio and sent to the
  piano model, which is the costly direction. None is on disk to say where
  it lands: no vibes or organ sidecar exists (Joey DeFrancesco's Evidence
  has no sidecar). An untested risk, not a known-correct case.
- **Drum solos**: the lead guard should refuse them (the drums loudest,
  the piano far under), unmeasured.
- **Selections under 15 s of melody** are refused, not measured.

## What did not work, or was not needed

- **A 10 s floor**, above: nine horn windows passed the share test with
  only the level test left, 2.4 dB from it.
- **The piano call on htdemucs_6s**, above: 0.9 dB from calling Coltrane's
  soprano trio.
- **The horn call on htdemucs_6s**, above: three of five piano solos are
  in `guitar` there.
- **Window length and the active range** move nothing: 0.5, 1 and 2 s
  windows put the worst horn at share 0.516 / 0.548 / 0.467 and the worst
  trio at 0.972 / 0.983 / 0.966; active ranges of 20, 30 and 40 dB give
  the same 0.548 and 0.983 at 1 s.
- **The level margin alone** (piano minus `other`) would have called
  Metheny's guitar solo a piano solo (+11 dB over `other`, the guitar
  carrying it). The margin is taken against the loudest OTHER melodic
  stem, and the share is what names the lead.
- **The drums alone** cannot say "no rhythm section": Sonny Clark's brushes
  sit 31 dB under his piano with the bass 4 dB under it. Solo-piano needs
  both.
- **A 12 dB lead guard** let the Soul Station stretch through as trio
  (above).

## Wiring

`gui/suggestion.py` (the GUI task's) resolves the stems and calls:

```python
from swingscribe import routing

stems = library.available_stems(document, config, model, span=(start, end))
levels = routing.measure(stems, (start, end))  # every stem; sums are skipped
hint = routing.suggest(levels, model)  # .ensemble, .stem, .confidence, .reason
```

The adapter refuses a partial set itself before reading anything, and
turns non-finite evidence into null; since 2026-09-30 `suggest` does both
too (a partial set is "no suggestion", and its evidence is always finite),
so either guard alone holds. The page shows `hint.reason` beside the
Ensemble menu with Apply, never changes a sidecar value the listener set,
and recomputes when the selection or the separation changes (a read of
wavs, not a job).

## Reproducing

    uv run python scripts/routing_survey.py [--json out.json]
    uv run python scripts/routing_survey.py --model htdemucs_6s

152 s and 180 s on this machine (2026-09-30): the wav reads plus the
window and floor sweeps, which on the Roformer are 267,520 windows judged
under nine floors, ~2.5 million `suggest` calls of pure Python. A sidecar
whose ingest record or stems are not cached is listed as skipped, never
computed.
