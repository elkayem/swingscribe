# M5 — Quantize

Plan §5 stage 5. A swung eighth pair is *played* long-short and *notated* as
two even eighths with "Swing" written above the staff, so quantization has two
jobs and doing them in one step is what makes naive transcriptions unreadable:

1. **Warp** the beat's internal timing so the swung offbeat at φ* returns to
   0.5, removing the feel and leaving the rhythm the player was thinking.
2. **Snap** to a notatable grid, keeping the leftover as `timing_residual` —
   the microtiming, which is the expressive layer every quantizer discards.

Pure arithmetic, no heavy imports, so all of it including the acceptance
criterion runs in CI: `uv run pytest tests/test_quantize.py`.

## Acceptance: met

Plan §5 asks that quantize → re-render with swing applied → onsets land within
20 ms of the original. Over BUR ∈ {1.0, 1.3, 1.6, 2.0, 2.5} × tempo ∈ {80,
120, 180, 260}, the worst cell is **0.00 ms**.

One thing to be careful about, because it is easy to write a test here that
passes by construction and measures nothing. `replay_onsets` has two modes:

- `restore_residual=True` puts the microtiming back, so the round trip is
  **exact by definition** — the residual is precisely what was subtracted. It
  is worth one test as an invariant (nothing is thrown away) and is useless as
  an acceptance criterion.
- `restore_residual=False` (the default) replays the **notation**: grid
  position plus feel, no microtiming. Any error is real quantization error.
  That is what the table above measures.

The first version of this test used the wrong mode and reported 0.00 ms
everywhere. It was not a result.

## On real music

Run end-to-end over the three benchmark solos:

| | Confirmation | All The Things | Giant Steps |
|---|---|---|---|
| pooled BUR | 1.71 | 2.25 | 1.66 |
| mean span confidence | 0.34 | 0.30 | 0.31 |
| decision | warp | warp | warp |
| beats warped | 416 | 208 | 192 |
| notes placed in a bar | 858/858 | 438/439 | 350/350 |
| **notation-replay error, median** | **14.8 ms** | **17.2 ms** | **9.6 ms** |
| same, 90th percentile | 37.2 ms | 42.2 ms | 24.5 ms |
| median \|residual\| | 0.046 beats | 0.056 beats | 0.040 beats |

The median holds inside the 20 ms criterion on real audio, which the plan only
asked for on synthetic. The 90th percentile does not, and should not: a note
landing near a grid boundary snaps to the wrong sixteenth, and that is
quantization behaving as specified rather than failing. The residuals — around
0.05 beats, roughly 15 ms at these tempos — are the microtiming that makes the
difference between a player and a MIDI file, and they are kept.

## Three decisions worth knowing about

**It refuses to warp on weak evidence, and the floor scales with confidence.**
Measured against 359 hand-annotated WJazzD solos, onsets with *no feel at all*
still produce BUR ≈ 1.56, because the offbeat region is asymmetric about 0.5
(`docs/wjazzd.md`). So a reading near 1.5 means "no swing detected", not
"slightly swung", and warping on it injects error.

But the floor is a statement about *evidence*, not about music. Real solos read
at confidence 0.25–0.32, which is where the floor must hold; a clean reading at
confidence 0.98 measures BUR 1.30 exactly (M4 recovers it with 0.00% error),
and refusing to warp that would notate a genuine shuffle as straight eighths,
49 ms off the performance at 80 bpm. So the ceiling relaxes toward 1.0 as
confidence rises — cubically, because a linear relaxation had already dropped
it to 1.43 at confidence 0.28, low enough to warp a Latin solo reading 1.45.

| reading | decision |
|---|---|
| BUR 1.45 @ conf 0.28 — noisy Latin | left straight |
| BUR 1.30 @ conf 0.98 — clean shuffle | warped |
| BUR 1.90 @ conf 0.30 — WJazzD median swing | warped |

**The floor is applied once, to the pooled track reading, never per span.**
Per-window BUR is noisy (±15% at 260 bpm) while the aggregate is sound, so
each beat's φ* is its own span's reading shrunk toward the track's
confidence-weighted mean, in proportion to that span's confidence.

Testing each span against the floor separately puts a hard threshold on a
noisy estimate, and it showed: on material swinging right at the ceiling,
adjacent windows fell on opposite sides and their beats got opposite
treatment. The round trip read **25.6 ms at BUR 1.6 against 0.00 ms at both
1.0 and 2.0** — a spike at exactly the threshold value.
`test_the_floor_is_applied_once_not_per_span` guards it.

**The grid is chosen per beat, not assumed.** Post-warp a genuine triplet
figure and a swung eighth pair are dangerously similar (plan §5), so both a
binary and a ternary subdivision are tried and whichever the beat's own notes
fit better wins. Ties go to binary — the commoner reading, and the one a
notation program renders without argument.

## Known limits

- **At burning tempos we will usually notate straight.** WJazzD puts real
  swing at BUR 1.24 above 280 bpm — *below* the 1.56 noise floor — so fast
  bebop is statistically indistinguishable from no swing at all. Notating
  straight eighths with a swing marking is what lead sheets do anyway, so the
  failure is benign, but it is a limit and not a choice.
- **`bar_and_beat` reports bar 0 outside every meter section.** A pickup or a
  rubato intro is deliberately not forced into a bar; M6 has to decide how to
  notate those.
- Duration quantization is a plain snap of the warped length. Tied notes,
  rests, and note-value spelling are M6's problem, not this stage's.
