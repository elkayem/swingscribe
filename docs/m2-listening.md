# M2 listening pass — beat tracking ear test

Acceptance check for the M2 beat tracker (plan §5 stage 2, §6): listen to
each `*.click.wav` and judge by ear. Findings only — no audio, no note data
lives in the repo.

## What to listen for

- **Phase** — do clicks land *on* the beat, or consistently early/late?
  (`on` / `early` / `late` / `erratic`)
- **Tempo octave** — is the click at the true tempo, or half/double it?
  A click on 1-and-3 of a fast bebop head is a half-tempo octave error.
  (`ok` / `half` / `double`)
- **Downbeat placement** — is the high click on bar "1", or displaced to
  2/3/4 (or drifting between them)? (`ok` / `off by N beats` / `unstable`)
- **Drift** — does the click stay locked across the whole track, or lose
  the band during rubato, trades, or tempo pushes? Note the timestamp
  where it comes apart. (`locked` / `drifts at m:ss`)

## Findings

| Clip | Phase | Tempo octave | Downbeat placement | Drift | Notes |
|---|---|---|---|---|---|
| 02 Corner Pocket | | | | | |
| 02 Laura | | | | | |
| 05 Hampton's Pulpit | | | | | |
| 06 They Say It's Spring | | | | | |
| 06 What's New | | | | | |
| 07 Gerry's Blues | | | | | |
| 07 Our Delight | | | | | |
| 07 What Am I Here For? | | | | | |
| 1-07 Sandu | | | | | |
| 1-09 Born To Blue | | | | | |

## Verdict

- Tracks passing (click lines up by ear): __ / 10
- Systematic failures worth fixing before M3:
