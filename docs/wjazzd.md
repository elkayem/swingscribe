# Swing timing measured against the Weimar Jazz Database

456 hand-annotated jazz solos, 200,809 notes, **132,329 human-tapped beats**,
12.5 hours, spanning every era from Armstrong to the 1990s. Both note onsets
and beat positions are annotated in seconds, so our own swing estimator can be
run over them with our transcriber taken completely out of the loop.

**No audio is needed for any of this**, which is why it was worth doing long
before the audio-aligned regression set the plan schedules for M6.

```bash
uv run python scripts/wjazz_swing.py --db wjazz/wjazzd.db
```

The database is ODbL (share-alike on the database and substantial
derivatives) and its contents are transcriptions of commercial recordings.
Nothing from it is committed; this file holds aggregate numbers only, which is
all plan §12 allows anyway. Get it from
[jazzomat.hfm-weimar.de](https://jazzomat.hfm-weimar.de/download/download.html)
(see [[wjazzd-location]] for the doubled-path trap in that download link) and
put it at `wjazz/wjazzd.db` — that whole directory is gitignored (`.gitignore`
matches `wjazz/` outright, so nothing written there can be committed by
accident).

## Browsing solos, or picking new ones for the benchmark

`scripts/wjazz_shortlist.py` is the tool for "what's in here, and what should
I add next" — it doesn't just print everything (456 solos is too many to scan)
but a curated *spanning* set across instrument and tempo, which is what plan
§6 actually asks for:

```bash
uv run python scripts/wjazz_shortlist.py --db wjazz/wjazzd.db -n 30
```

Each row gives performer, title, tempo, instrument, album, and (when WJazzD
annotated it) the solo's start time in the track — enough to go find your copy
of the recording and check whether it's the same take before adding it to
`benchmark/`. Raising `-n` gives more rows without changing what's already
picked; the round-robin fills in the next-best cell each time.

For an unfiltered look at anything specific — a soloist, a tune title, an
instrument you want more of — the two tables that matter are `solo_info`
(performer, title, instrument, avgtempo, style, rhythmfeel — one row per solo)
and `melody` (onset, pitch, duration, bar/beat/tatum position — one row per
note, joined on `melid`). A one-off query from a Python shell:

```python
import sqlite3

db = sqlite3.connect("wjazz/wjazzd.db")
for row in db.execute(
    "select melid, performer, title, avgtempo, rhythmfeel from solo_info "
    "where instrument = 'p' order by avgtempo"
):
    print(row)
```

Or open the file directly in a SQLite browser (e.g. the free
[DB Browser for SQLite](https://sqlitebrowser.org/)) if you'd rather click
through tables than write queries — it's a plain, unencrypted `.db` file, no
special tooling required.

To look at one solo's actual note-level transcription (pitch, onset, duration,
metrical position) next to your own — the way you'd sanity-check a match —
filter `melody` by the `melid` you found in `solo_info`; `wjazz.py`'s
`notated_positions()` is the same query the eval harness uses internally, if
you want the exact bar/beat/tatum → quarter-note-position arithmetic rather
than raw columns.

442 of the 456 solos carry enough evidence to measure; 359 are labelled SWING.

## 1. The spread is real jazz, not our error

This is what the exercise was for. M4 measured offbeat phase spread of
0.106–0.134 on our three benchmark solos and could not say whether that was
expressive human timing or our own onset error. With human onsets on human
beats:

| | phase spread |
|---|---|
| WJazzD, 359 SWING solos | **median 0.135** (10th 0.102, 90th 0.152) |
| our three solos, from audio | 0.106 – 0.134 |
| uniform random noise | 0.144 |

**Our spread is indistinguishable from hand-annotated ground truth**, and sits
at the tighter end of it. The answer is real jazz: players place offbeats with
about this much scatter, and no improvement to our transcriber will change it.

The uncomfortable corollary is the more important half. Human-annotated swing
scatters at 0.135 against noise's 0.144 — **real jazz is only slightly tighter
than random**. So the difficulty M4 ran into is not ours to fix:

- deciding "swung or no grid at all?" from a 16-beat window is hard *for
  anyone*, with perfect onsets and perfect beats;
- the plan's specified classifier ("peak is well-separated") cannot be
  rescued by better input, which the M4 write-up suspected and this settles;
- `is_swung` as a z-test with confidence carrying the uncertainty is the right
  design, not a workaround.

That closes the largest open question in M4, and it closes it n=359 instead of
n=3.

## 2. There is a noise floor at BUR ≈ 1.56, and it matters

Re-scattering every solo's notes uniformly inside their own beats — destroying
the feel while keeping note density and the real grid — yields **BUR 1.56**.
Not 1.0. The offbeat region (0.35–0.85) is asymmetric about 0.5, so onsets
with no feel at all still average late.

Against the human `rhythmfeel` labels:

| feel | n | BUR | spread | verdict |
|---|---|---|---|---|
| SWING | 359 | **1.90** | 0.135 | clears the floor |
| TWOBEAT | 21 | 1.53 | 0.110 | at/below |
| LATIN | 27 | 1.43 | 0.125 | at/below |
| BALLAD | 10 | 1.43 | 0.142 | at/below |
| FUNK | 19 | 1.31 | 0.138 | at/below |

The estimator does separate swing from everything else, which is a real
validation against human labels. But it also means **a reported BUR near 1.5
is "no swing detected", not "slightly swung"** — an easy and consequential
misreading, and one M5 must not make when it decides what to warp.

## 3. Plan §5's hypothesis holds

The plan flags a hypothesis worth testing: that the *short* note's absolute
duration stays roughly constant regardless of tempo, which would explain the
whole tempo/BUR relationship. Across the 359 SWING solos:

| tempo | n | BUR | short note (IQR) |
|---|---|---|---|
| 100–140 | 75 | 2.44 | 139 ms (110–186) |
| 140–180 | 68 | 2.37 | 109 ms (92–131) |
| 180–220 | 52 | 1.97 | 102 ms (93–116) |
| 220–280 | 83 | 1.56 | 93 ms (80–105) |
| 280+ | 40 | 1.24 | 91 ms (43–102) |

**Between 140 and 280 bpm (n=203) the short note's median is 100 ms** while
BUR falls from 2.37 to 1.56 — a factor of 1.5 change in the ratio against a
16% change in the absolute duration. The plan predicted ~100 ms. It is ~100 ms.

Two honest qualifications. Below 140 bpm the short note grows (139 ms, and
349 ms in the sub-100 band) — the relationship is a *floor* on how short a
note a player will place, not a constant, and at slow tempos there is room
above it. And past 280 bpm both BUR (1.24) and the band's IQR (43–102 ms)
collapse toward the noise floor, so the fastest band is measuring the limit of
the method as much as the music.

The useful form of the result is therefore: **from medium tempo upward, jazz
players hold the short note near 100 ms and let the ratio go wherever that
implies.** That is a better model of swing than a fixed BUR, and it is
directly actionable — M5 can warp toward a *duration* target rather than a
ratio target, and the ratio falls out.

## 4. Our audio pipeline agrees with the humans

Our three benchmark BURs, measured end-to-end from audio through separation,
CREPE, our beat tracker and our estimator, against WJazzD's human annotations
at the same tempo (±20 bpm, unfiltered):

| | ours | WJazzD median | WJazzD IQR | |
|---|---|---|---|---|
| Confirmation (187 bpm) | 1.79 | 2.07 | 1.66–2.45 | inside |
| All The Things (194 bpm) | 2.16 | 1.95 | 1.66–2.42 | inside |
| Giant Steps (249 bpm) | 1.55 | 1.56 | 1.28–1.95 | inside |

All three land inside the human interquartile range, and Giant Steps matches
the median almost exactly. Given how much machinery sits between the waveform
and that number, this is the strongest end-to-end validation the project has.

## What this does and does not license

It does **not** replace the audio-aligned regression set of plan §6 layer 2.
Nothing here scores transcription — no pitch accuracy, no onset F1, no note
F1 — because that needs the original recordings aligned to these annotations.
WJazzD's own audio is not distributed.

What it does is settle the swing questions, validate the estimator against 359
human labels, and confirm a hypothesis the plan had only flagged.

## A score CAN be built from this database, and an earlier reading said it could not

The claim was that WJazzD carries a human's onsets and metrical positions but
not a notated score, "because `melody.duration` is performed seconds and there
is no column holding a note VALUE". The first half is true. The second half is
the wrong conclusion, and the Jazzomat project's own PDF lead sheets -- rendered
from these same columns -- are the standing counter-example.

In a single line the written value of a note is the metrical distance to the
next one, less any rest. The metrical positions are all here and they are
exact: `bar`, `beat`, and `tatum` out of that beat's own `division`. Nothing is
missing.

`wjazz.annotation_notation(db, melid)` builds the `Notation`;
`scripts/wjazz_score.py` writes it out as MusicXML, which MuseScore opens and
which the GUI's "Ground truth..." button now accepts alongside `.mscz`/`.mscx`
(`mscz.parse_any`).

### What it is evidence about, and what it is not

The POSITIONS and the PITCHES are a human's, and they are independent evidence.

The RESTS and the NOTE VALUES are OURS -- `notate.notated_durations`,
`notate.snap_values`, `notate.MIN_REST` and the tuplet grouping, applied to a
human's grid. Scoring our `value` against these would be scoring our own
conventions against themselves.

**That is the honest version of the original objection**, and it is why
`score_against_wjazz_notation` still reports rhythm only. A ground truth for
what was played and where it sits in the bar: yes. A ground truth for how it
should be written: no.

### `division` is per BEAT, and it goes up to 36

    division   1: 15812   2: 58269   3: 29650   4: 58678   5: 4579
               6: 18661   8: 6957   10: 2663  12: 1231   ... 36: 25

172 of the 456 solos used only divisions this notater could write at all
(1, 2, 3, 4, 6, 8, 12) before `notate.TUPLET_RATIOS` grew a 5:4 and a 7:4
alongside the ordinary triplet. The rest held quintuplet or septuplet onsets --
a beat divided into 5 or 7, neither a power-of-two value nor on-thirds -- and a
score built from them carried unwritable slivers (tied 32nds) however the
durations were rounded. That is where Freddie Hubbard's Maiden Voyage (melid
168) bar 6 came from: a 5-tuplet on the Jazzomat PDF, four tied 32nds on ours.

Both ratios write "in the time of 4" -- a sixteenth is the value 4 unmodified
notes would fill the beat with, so a beat split 5 ways measures out to exactly
a sixteenth's worth times 4/5, and 7 ways to a sixteenth times 4/7. `notate.py`
now recognises both, and `export.DIVISIONS` moved from 24 to 840 (the smallest
number divisible by 8, 3, 5, and 7) so a group of five or seven ticks still
sums to an exact beat instead of one tick over. Mean readability over all 456
solos rose from 0.882 to 0.9455 -- most divisions above are still quoted over
the 172-solo subset as well as over all 456, since a handful of rarer divisions
(10, 36, ...) are not fully covered by these two ratios.

### Licence

ODbL is share-alike. A score written from this database is a derivative OF the
database, so `scripts/wjazz_score.py` refuses an `--out` inside the repository
and these files must never be committed (CLAUDE.md, plan section 12).

## Why our score differs from the Jazzomat PDF: the legato rule, not the data

Reported by the listener on Dexter Gordon's Cheese Cake -- notes we write as an
eighth are quarter notes on the website's PDF. **The quarter note IS derivable
from the database.** What differed was a rule.

WJazzD bar 2, first note: pitch 55, played 0.517 of a beat, with a **whole
beat** to the next onset. `notate.notated_durations` fills a gap only when the
player held at least `legato_fill` (0.75) of it. 0.517 fails that, so we wrote
an eighth followed by an eighth rest; the lead sheet writes the quarter.

**A ratio asks "did the player hold it?", which is articulation, and a lead
sheet does not write articulation.** The 0.75 was measured against OUR
durations, which are the gated extent of a CREPE pitch and tend to overrun.
WJazzD's `duration` is a careful human's note-off, honest about a player who
tongues short -- Dexter's played fraction runs 0.28 to 0.52 against gaps of 0.5
to 1.0. Applying a hold-ratio to that manufactures a rest after nearly every
note.

`notate.notated_durations` gained `legato_cap`, which asks the question of the
GAP instead: a gap short enough to BE a note value becomes one, and anything
longer stays a note followed by a real rest. Over all 456 solos, at a cap of
two beats:

                        ratio only    + cap
    readability            0.8823    0.8884
    sub-eighth rests        2.07      1.14
    notes tied              0.158     0.181

The obvious alternative -- dropping the ratio toward zero so every gap fills --
scores slightly better on paper (0.8960) and is wrong: it ties a phrase-ending
note across four beats of silence into the next phrase. The cap cannot do that,
which is the reason to prefer it.

**`legato_cap` defaults to 0.0, which is off.** The shipped pipeline keeps the
ratio it was measured with and none of its baselines move. Only
`annotation_notation` turns it on.

### Bar numbers are WJazzD's own

Also reported, implicitly: the scores were renumbered from 1, so our bar 3 was
WJazzD's bar 1 on Cheese Cake (its annotation starts at bar -1, a pickup). A
file whose whole purpose is to be laid beside the Jazzomat lead sheet has to
share its numbering. Fixed -- bar N here is bar N there, pickup bars included.

### What still differs

A note before a LONG gap keeps its played length, snapped. Cheese Cake bar 3
ends on a pitch 62 held 0.75 of a beat with 4.08 beats to the next onset; we
write a triplet quarter and rests. A lead sheet would more likely write a plain
quarter. The cap deliberately does not reach that far, and rounding a
phrase-ending note to a plain value is a separate rule nobody has measured yet.


## A performer and a tune do not name a solo

Joe Henderson's In 'n Out read as a different piece of music from both the
audio and `solo198.html`, and the notation was not at fault. The file was the
wrong solo. WJazzD holds **456 solos under 421 performer/title pairs**:
Henderson takes two on In 'n Out (melid 198, 18 choruses, and melid 199, 8),
Sonny Rollins three on Blue Seven, and Coltrane's Body and Soul exists as a
master and an alternate take. `wjazz_score.py` named files
`{performer}_{title}` and wrote them in that order, so **35 solos were
overwritten by the next one along** and nothing said so. The file on disk was
byte-identical to melid 199.

Two things fix it and one is not a filename:

- Every name now carries its **melid** -- `Joe_Henderson_In_n_Out_solo_198`.
  That is also the number in the synopsis URL, so a file can be laid beside the
  page it was rendered from. Written `_solo_198`, not `_solo198`, so the GUI's
  name matcher splits it into a stopword and a digit and drops both
  (`gui/ground_truth.py`); the ranking against a track is unchanged.
  `titleaddon` ("Alternate Take", "1961") joins the stem where it exists,
  because it is the half of the distinction a human can read.
- The writer **refuses to write a name twice**, rather than trusting the scheme.
  The property that matters is over the whole set: a scheme that collides once
  in 456 still loses a solo in silence.

The measurement path was never affected. `score_wjazz.identify_all` finds a
solo inside a track **by content** -- `fit_affine` over onsets and pitches --
and returns every solo it finds, so it never depended on a filename. What was
affected is the ground-truth score the GUI draws against, which is the one a
human reads.
