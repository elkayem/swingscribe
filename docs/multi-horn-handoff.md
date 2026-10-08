# Multi-horn: hand-off between the cloud and the local session

The cloud session writes the code and the synthetic CI tests on the
`multi-horn` branch; it has no audio, no GPU and no stems cache. The LOCAL
session (Windows, the listener's PC) fetches the branch and runs everything
that needs real audio, then reports back with SendMessage. Nothing here is
merged: the listener reviews the branch first. Design and state:
[multi-horn.md](multi-horn.md).

## Status

| Piece | State |
| --- | --- |
| A. Multi-horn core + `scripts/multi_horn_page.py` | pushed, waiting on Local task A |
| B. Linked sidecars | not started |
| C. Two parts, GUI, guide | not started |

## Setting up (once)

Peer sessions commit to `master` in the main checkout, so do not switch it to
this branch. Use a worktree beside it, and run from the MAIN checkout's root
with the worktree's `src` first on `PYTHONPATH`: the main checkout's venv
and its `.swingscribe-cache` (the GUI's stems and reviews) are what the
scripts need, and the venv's editable install would otherwise import
`master`'s package.

```
cd <repo>
git fetch origin multi-horn
git worktree add ..\swingscribe-multi-horn origin/multi-horn
set MH=<repo>\..\swingscribe-multi-horn
set PYTHONPATH=%MH%\src
.venv\Scripts\python.exe -c "import swingscribe.voices, sys; print(swingscribe.voices.__file__)"
```

The last line must print a path under `swingscribe-multi-horn`. If
`.venv\Scripts\python.exe` is refused (exit 126, Smart App Control), use the
base interpreter named by `home =` in `.venv\pyvenv.cfg` with
`set PYTHONPATH=%MH%\src;<repo>\.venv\Lib\site-packages` (the route
`swingscribe.cmd` takes). To update later: `git fetch origin multi-horn` and
`git -C %MH% checkout --detach origin/multi-horn`.

Needs the ml group (onnxruntime for Basic Pitch, torch for CREPE) and the
cu130 torch reinstall if a sync put `+cpu` back (CLAUDE.md, Dependencies).

## Local task A: the first Open Sesame head page

The stems are already separated (Step 0 used the BS-Roformer `other` stem
over 0-67.308 s). The script reads the GUI's cache, so it must run from the
directory the GUI runs from (or pass `--cache-dir`). Replace `AUDIO` with
the recording Step 0 used, e.g. `benchmark\Multi-Horn\Open-Sesame.m4a`, and
`OUT` with a folder outside the repo or under `benchmark\` (never commit the
outputs: they are derived from a commercial recording).

```
set PAGE=.venv\Scripts\python.exe %MH%\scripts\multi_horn_page.py AUDIO --start 0 --end 67.308 --anchor 8.46 --model bsroformer_sw --stem other

%PAGE% --out OUT\os.literal16.musicxml --dump-voices OUT\os.literal16.txt
%PAGE% --lag --out OUT\os.lag.musicxml --dump-voices OUT\os.lag.txt
%PAGE% --thirds --out OUT\os.thirds.musicxml --dump-voices OUT\os.thirds.txt
%PAGE% --lag --thirds --out OUT\os.lag-thirds.musicxml --dump-voices OUT\os.lag-thirds.txt
```

If a sidecar for the head already exists (anchor, form start), add
`--sidecar <path>` and drop the flags it covers; the script reads it and
never writes it. `--form-start` sets the form start the same way.

What each run does and should produce:

- The FIRST run transcribes: Basic Pitch over the span, `voices.assign`, and
  CREPE for the frame trace (its notes set aside), cached under the GUI's own
  review key (`review.span_config` with ensemble `multi-horn`). Later runs
  print `review: cached`. Expect about 380 heard notes before the voices
  (Step 0 had 381): the summary line says how many went to each voice and
  how many were left as candidates (ghosts and third notes).
- Each run writes one MusicXML: both horns on one treble staff, concert key,
  voice 1 stems up and voice 2 down where both sound, voice-2 rests hidden,
  literal 16ths unless `--timing` says otherwise.
- `--dump-voices` writes three sections: every heard note with its voice;
  the lower voice's phrases with their median interval and whether they
  moved an octave (bars 15-16 should move +12); and the written page bar by
  bar, voice by voice, with values in quarters, `~` for ties, `(3:2)` for
  triplets, `[up]`/`[down]` stems and `[hidden]` rests. The header says which
  roll bar the page's bar 1 is, so the listener's bars 23-38 (grid bars
  33-48) can be found.

What to report back (SendMessage to this session):

1. The summary lines of each run (voice counts, candidates, phrases moved,
   unisons, bars, readability, the roll-bar offset), and any traceback.
2. The dump's bars for grid bars 33-48 from `os.literal16.txt` and
   `os.lag-thirds.txt`, set against the listener's screenshot of bars 23-38
   bar by bar: which match, which do not and how (wrong pitch, wrong voice,
   on the "e", triplets missing, a unison written twice, an octave move
   that should or should not have happened).
3. Whether `--lag` moves the held chords off the "e" and whether it moves
   anything that was right; whether `--thirds` writes bars 36 and 38's
   triplet chords and anything else as triplets.
4. Whether MuseScore 4 opens each file (`.\pdf2musicxml render OUT` opens
   every MusicXML in a folder and reports any it refuses) and whether the
   stems, hidden rests and voices look right on the page.
5. Any overtone ghost kept, or real note dropped as a ghost or a third
   (the dump's heard section and the review's candidates).

## Local check: no cache key moved

Optional, and cheap once everything is cached. Run the branch's harness from
the main checkout's root, against master's pins as they stand:

```
cd <repo>
set PYTHONPATH=%MH%\src
.venv\Scripts\python.exe %MH%\scripts\run_eval.py --db wjazz\wjazzd.db
```

It must re-transcribe NOTHING (no "settings differs from cache" lines) and
every pin must hold: no benchmark sidecar is multi-horn, and the multi-horn
fields enter no other key. Report the last lines of the card, and any pin
that moved.
