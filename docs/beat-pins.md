# Pinned beats (roadmap O5)

2026-09-30. A listener's fix for a beat the tracker slipped part-way through
a solo, and the one measurement there is of it.

## Why the downbeat cannot do it

The bar grid is counted from an anchor: `index % pulses == anchor % pulses`
decides a bar line everywhere (`meter.derive_sections`). One beat the grid
gains or loses shifts every bar line after it by a beat. The downbeat is a
PHASE, so moving it fixes the bars on one side of the slip and breaks the
bars on the other side.

Cheese Cake (Dexter Gordon, the PDF page and WJazzD solo 121, the same
take): the tracker emits a doubled beat at 160.48 and 160.60 s. Between
160.28 and 160.84 s the intervals are 0.20, 0.12 and 0.24 s on a 0.26 s
pulse. The pair sums to 0.32 s, and `drop_doubled_beats` allows 0.15 of
the pulse plus one 20 ms tracker frame (0.059 s). It misses by a
millisecond, the repair keeps both beats, and every bar from our bar 83 on
is a beat late. Both references see it: the page's trace steps +1.0 at bar
83 and WJazzD's at its bar 84 (docs/metrics-e4-e6.md, roadmap section 1).

Widening the doubled-beat tolerance would mend this one track and move
every grid the R26 thinning was measured on. That is a different change,
and this one has to work wherever the repair has no rule.

## What a pin does (`meter.apply_pins`)

A pin is a time where a beat is, stored in the sidecar as `beat_pins`.
After the repair (`repair_beats`) and before the edge extension
(`extend_beats`), inside `meter.bar_grid`:

1. Two pins less than half the local pulse apart are one beat, and the
   earlier is kept (`_one_pin_per_beat`). The GUI never sends two: a new
   pin that near replaces the old one.
2. Every tracked beat nearer a pin than half the local pulse (`PIN_CLEAR`,
   so exactly half a beat counts too) gives way to it.
3. The pin's window runs out to the nearest STEADY uncleared beat on each
   side: found by the tracker, with every interval beside it within
   `stability_tolerance` of the reference pulse. The search goes up to
   `PIN_REACH` (16) beats and stops at the next pin. Pins with no steady
   beat between them share one window, and two windows never overlap.
4. Inside the window the beats are laid out again. Between two pins there
   are `round(gap / pulse)` intervals. The window as a whole keeps the
   count its two ends hold in TIME, and whatever the pins leave is split
   either side. When that time holds too few intervals for the pins to
   stand in, the window is widened by one steady beat on each side at a
   time. That happens to a pin between two beats that are each just over
   half a pulse away, so neither gives way. Each new beat is the
   tracker's own when one sits within a quarter of a step of its place
   (`PIN_SNAP`). Otherwise it is an implied beat at the even subdivision.
   Every beat laid out is marked `relaid`.

Counting from time is what mends the slip. The repaired grid has four
intervals between 160.02 and 160.84 s, and the time holds three. It is also
why a pin half a beat away from the tracker moves the beats around it and
never adds one: the window keeps its count.

The pulse it counts in is MEASURED, as the median interval between two
steady beats, looking out from the window's ends: at least `PIN_PULSE_MIN`
(4) such intervals, up to `PIN_PULSE_REACH` (32) beats beyond the ends.
It is never read off the reference pulse inside the window (fixed
2026-10-01, from the second review). The reference is a rolling median.
Through a jittered stretch longer than its window it drifts: 0.519 s on a
0.5 s pulse over 24 jittered beats. Across a 13.5 s window that is one
interval short, so a beat goes and every bar line after it moves. Two
things made it fail:

- Reading the window's steady intervals instead is not enough. A jittered
  interval passes the steadiness test against the drifted reference by
  chance, so only an interval whose two beats are both steady counts as a
  measurement.
- A jittered beat that is "steady" by chance also ENDS a window inside the
  stretch. With no steady pair within the reference window of it, the
  search has to look further out.

The checks run on the final code:

- **Synthetic ragged stretches.** Pins at true beats, 8 to 24 beats long,
  pinned at the ends, every 4th beat or every beat
  (`test_pins_in_a_long_ragged_stretch_keep_the_count`). The count and
  the bar numbers after the stretch now match the clean grid in all nine
  cases. Before the fix, 2 of the 9 lost a beat in the test, and 3 of 12
  in the reviewer's reproduction.
- **The reviewer's fuzz** (1,500 trials per mode). Missing bar lines in
  ragged stretches fell from 100 to 36 (133 to 41 with a late anchor),
  and stray bar lines from 3 to 0. The slip, on-beat and half-beat modes
  did not change. The 105 trials still bad are splits into two sections
  near a pin, which the old code produced too.
- **Real cached grids** (2,940 trials of 2-4 pins, each 40 ms off a
  tracked beat).
  - **No renumbering from a steady neighbourhood.** As before, no pin
    there renumbered a far bar; every renumbering is a pin inside a messy
    stretch.
  - **Renumberings, 143 to 155.** Of the new ones, Freddie Hubbard's
    Speak No Evil at 297.8 s can be checked against WJazzD's annotated
    beats: 11 intervals across the window. The new code lays 11, the old
    code laid 9 (a 0.49 s pulse inside a steady 0.42 s solo). The
    renumbering is the probe comparing against an unpinned grid that was
    itself two beats short.
  - **Chet Baker at 143.0 s.** This pin bridges a 6.3 s hole in the
    tracking, outside the annotated solo, while the tempo moves from
    0.36 s to 0.40 s. Old and new counts differ by one, and nothing can
    say which is right.
  - **Splits, 2 to 5.** All five are at the two places the old code
    already split: Bohemia After Dark near 421 s, and April in Paris's
    rubato intro.
- **The single-pin scan below.** Still 0 broken of 17,640 pins. 15 pins
  per offset now change the count, up from 10 (11 at half a beat): five
  more pins re-derive a messy stretch the repair left. Hubbard's is one of
  them.
- **Cheese Cake.** It reads exactly as in the table below.

### A pin vouches for its window and decides nothing outside it

The first version judged a pin's window like the tracker's beats, and the
review found that a pin often broke the grid it was placed to mend. A pin
that moves a beat by a fifth of a pulse leaves the interval on each side
outside `stability_tolerance`. Two unsteady intervals in a row split the
metrical span at the pin. `derive_sections` counts whole bars per span, so
the split lost a bar line and numbered every bar after it one lower, on
the roll and in the chord chart. The page did not move, because its phase
is an index, so the page and the chart ended up a bar apart. That happened
to 34 of 210 taps 50 ms off a steady beat on Cheese Cake, and to a pin on
either crowded beat of its slip. Three rules now hold:

- **The window is steady by the listener's word.** `steady_intervals`
  takes every interval beside a pinned or relaid beat as steady. The
  reference pulse counts each run of them as its mean
  (`_window_votes`), which preserves the sum of the pair a pin moved.
- **Outside the window, the unpinned grid's answers stand.** `bar_grid`
  judges the unpinned grid first (`meter.judge` returns a `Judgement`).
  Every interval the pins left alone keeps that steadiness, and spans are
  bridged against that grid's median pulse. Judged afresh, the pin's new
  intervals moved the rolling reference a few milliseconds and flipped a
  whole-gap test six seconds away that had passed by a millisecond. And
  on a tracker's 20 ms frame grid, a hole of exactly two pulses sits on
  the bridge threshold, where a median moved by 2e-15 s split Ko Ko in
  four places 47 s from the pin.
- **The edges extend at the unpinned grid's pulses** (`extend_beats`'
  `pulses`). Steadiness at an edge is a fact about the tracker's edge
  beats. Judged on the pinned beats, a pin a fifth of a pulse off one of
  the last twelve beats took the extension away (the last nine bar lines
  of Cheese Cake, the last two of a ballad) or gave an extension to an
  edge the tracker had left ragged.

With no pins none of this runs: `bar_grid` takes exactly its old path, so
no grid, cache key or pin moved.

A pin is never in `MeterConfig`. The pipeline's meter stage does not see
pins, no cache key moved, and config.py is untouched. Every consumer that
should see the pins reaches them through `meter.bar_grid`: `/beats` and
`/solos` (a `pins` query parameter, as the page holds them), and Export,
the page view, the chord chart (`form_bar_of_page`) and the Score button
(`notation.bar_grid_for_settings`, which reads the sidecar). `run_eval`
builds its pages through that function too, so a pinned sidecar would
reach the harness. No sidecar in `benchmark/` has pins, so no pin moved.

## The measurement: one pin on Cheese Cake

The measurement is the page and its trace, built exactly as `run_eval`
builds them, from copies of the harness caches. The pins were added to an
in-memory copy of the sidecar, never to the benchmark's own. The script
wraps `notation.bar_grid_for_settings` so `run_eval`'s own `page_grid`
code runs (`scratchpad/wf9/pinbeat/recheck_cheese.py`). Re-measured on the
final code (2026-10-01, with every rule below, the edge extension's
included): the same numbers to the last digit, at all seven positions.

| measure | no pin | pin at 160.55 s |
|---|---|---|
| PDF page: on the bar | 0.707 | 0.893 |
| PDF page: trace steps | 1 (+1.0 at bar 83) | 0 |
| PDF page: rhythm / value | 0.826 / 0.766 | 0.828 / 0.768 |
| PDF page: edit cost per 100 notes | 51.96 | 51.45 |
| WJazzD: on the bar | 0.689 | 0.878 |
| WJazzD: trace steps | 1 (+1.0 at bar 84) | 0 |
| WJazzD: rhythm (531 matched notes) | 0.623 | 0.623 |

The traces read "bars 1-83 on the bar; bars 83-114 +1.0" and "bars 2-84 on
the bar; bars 84-116 +1.0" without the pin, and "bars 1-114 on the bar" and
"bars 2-116 on the bar" with it.
- Pins at 160.48 or 160.60 s, the listener dragging one crowded line onto
  the other, give the same result (page on the bar 0.891 and 0.893).
- Pins at 160.12, 160.30 and 160.70 s read 0.886, 0.893 and 0.889 on the
  page and 0.872, 0.878 and 0.874 against WJazzD, all with no step.
- Our grid against WJazzD's annotated beats for solo 121, through
  `score_wjazz.identify_all`'s affine fit: beat of the bar agrees on
  330 of 458 annotated beats without the pin (the phase changes at
  annotated bar 82), and on 458 of 458 with it.

n = 1 recording, scored against two references. A paired interval over one
recording is not an interval, so none is quoted. The change is the one
beat, fully explained.

Sensitivity: a pin anywhere from 160.00 to 160.96 s mends the count (a
window of about 3.5 beats, the unsteady stretch around the slip). From
161.00 s on it changes nothing, because the pin lands on beats the grid
already has right. Some pins inside the window, such as 160.12 s, also
move one neighbouring beat off the tracker's. The count is still right.

**The chord chart and the roll now agree with the page wherever the pin
lands.** For a page at 165-190 s the chart's form bar was 150, 149 or 148
depending on where in the slip the pin went (149 at 160.48 and 160.70, 148
at 160.12). Now it is 150 at all six positions, against 151 unpinned, and
87 at all six with the sidecar's form start, against 88. One section and
361 bar lines at every position.

## Robustness: one pin on every cached grid

`scratchpad/wf9/pinbeat/scan_grids.py` puts single pins on all 147 grids in
`.benchmark-grids.json` (a copy), at the default meter and the automatic
downbeat. Each grid gets 24 random beats inside a metrical section, and
each beat gets five pins: 0.1 and 0.2 of a pulse either side, and half a
beat after. A pin BREAKS the grid if the grid gains a section, or if any
bar line more than 3 s from the pin, between the tracker's first and last
beats, changes its number or goes missing, while the beat count stays the
same. A pin that changes the beat count has mended a slip (or mis-mended
one), and the bars after it are meant to move. Those are counted apart.
The reviewed version was rebuilt from HEAD plus the builder's diff and
run on the same pins (`meter_reviewed.py`). It reproduces the review's
Cheese Cake and jitter numbers exactly.

| pin, from a beat | reviewed: broke the grid | reviewed: changed the count | fixed: broke the grid | fixed: changed the count |
|---|---|---|---|---|
| 0.2 pulse early | 1,089 of 3,528 | 43 | 0 | 10 |
| 0.1 pulse early | 192 | 27 | 0 | 10 |
| 0.1 pulse late | 163 | 23 | 0 | 10 |
| 0.2 pulse late | 1,178 | 44 | 0 | 10 |
| half a beat late | 2,734 | 673 | 0 | 11 |

That is 5,356 of 17,640 pins broken before and none after. The reviewed
version's 673 count changes at half a beat were mostly the defect the
window widening fixes: a pin between two beats that are each just over
half a pulse away added a beat.

On the fixed code, the pins that changed the count are the same ten beats
at every offset, and every one REMOVES a beat next to an interval of
0.18-0.73 of the median: a doubled or ragged pair the repair missed, like
Cheese Cake's. They are Orbits (two copies of the audio), Just Friends,
In 'n Out, Limehouse Blues, Cherokee II, Totem Pole, Oleo (two copies)
and Nothing Personal. Two of them were checked by hand. Orbits has
172.54/172.62 s (0.18 + 0.08 s on a 0.23 s pulse) and Just Friends has
49.92/50.00 s (0.24 + 0.08 s on 0.32 s). The pin mended both.
Before the edge extension took the unpinned grid's pulses, five more pins
changed the count at the end of a track, by +21, -7, +2, +1 and +1 beats.
Those were extrapolated beats only.

Synthetic checks, all on the fixed code: 0 of 130 pins 0-0.5 of a pulse
past a beat break a jittered grid (reviewed: 38); every 20 ms position
across the synthetic slip from 0.3 s before it to 0.68 s into it gives
one section and the true grid's bar numbers (reviewed: 26 of 50 split);
on 3,000 random fuzz grids with 1-6 random pins, nothing raises, no grid
goes non-monotone, no pin makes a beat under 0.2 of a pulse (reviewed:
43) and no two pins stand within half a pulse (reviewed: 143). A section
was added in 53 trials (reviewed: 958), and every one was a new island in
a stretch that had no bars before, never a split.

## Limits

- A pin must be AT the slip. A pin on a beat the grid already holds only
  moves that beat. A pin cannot say "this beat is a downbeat". A bar-line
  pin (a pin that is also a phase) is the next step if the listener asks
  for it.
- The GUI shows the slip only as ticks crowded together or a gap on the
  Detail view. Nothing points at it yet. A highlight on intervals far from
  the reference pulse would.
- Pins are applied on the whole-track grid, so a pin outside the span
  still re-derives its own neighbourhood. That is harmless, because a
  window is local.
- A pin in a stretch the tracker left free (no steady beat within reach)
  re-derives it at the local pulse, and the window is steady by the
  listener's word. If that window holds `min_span_beats` found beats, bars
  appear there that were not drawn before. In the synthetic fuzz (3,000
  random grids with 1-6 random pins) every section a pin added was one of
  these new islands (53 of 3,000 trials), never a split.
- Bar lines on extrapolated beats, past the tracker's first or last beat,
  continue from the pinned grid's edge beat. A pin on one of the last
  beats moves them by up to its own offset, never their count or numbers.
- The half-beat contradiction is resolved asymmetrically: 19.5, 19.875
  (implied), 20.25 (pin), 21.0 on a 0.5 s pulse. Keeping the count while
  passing through a pin half a beat off forces one long and one short
  stretch somewhere.

## Interface

The Detail waveform is the place, because the downbeat and form clicks
already live there. A plain drag pans and a click seeks, under the one
gesture rule. Pinning takes Alt:

- **Alt-click**: pin a beat here. On a pin's marker, take that pin away.
  A new pin less than half a beat from another one replaces it (one pin
  per beat; the local beat length comes from the grid on screen).
- **Alt-drag**: carry a line to where the beat is. Started on a pin, the
  drag moves that pin.
- <kbd>T</kbd> or **Pin beat**: pin at the playhead.
- **N pins ✕**: clear them all, after a second click.

A cancelled pointer gesture (`pointercancel`: the browser took the
pointer) pins and unpins nothing. It used to take the click branch.

Pins are drawn as a pale line with a flag at the top on the Detail view and
on the piano roll (`--pin`). The export and page signatures include the
pins, so the page redraws when they change. Verified in the browser
preview on scratch copies of Cheese Cake and Birks Works, 2026-09-30, and
again on the fixed code: Alt-click at 160.55 s moves bar 84 from 161.12 to
161.40 s; an Alt-click 60 ms from that pin moved it ("one pin per beat")
rather than adding a second; a cancelled click on a pin and a cancelled
drag of a pin changed nothing, while the same gestures completed unpinned
and moved it; a plain drag panned; <kbd>T</kbd> pinned at the playhead;
the clear chip asked first.
