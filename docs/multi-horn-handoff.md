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
| B. Linked sidecars | pushed, waiting on Local task B |
| C. Two parts, GUI, guide | pushed, waiting on Local task C |

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

## Local task B: linked sidecars ("takes")

What landed (gui/library.py, docs/multi-horn.md has the multi-horn half):

- A sidecar may carry `"audio": "<path relative to the sidecar>"`; it is
  then a LINKED take. Its key is its own file name minus
  `.swingscribe.json`. With no `audio`, today's rule: the sibling audio
  named by the key. No existing sidecar is touched.
- Track id: the audio's digest for its own sidecar (unchanged); digest plus
  an 8-character hash of the sidecar's path for a linked take. ONE
  REFINEMENT of the approved design, for the listener to confirm: two
  byte-identical copies each opened through their OWN sidecar would still
  share the digest, which is the bug that started this. So the plain digest
  stays with the copy the recents index already holds it for (every id
  handed out before is unchanged), and another copy's own sidecar is named
  like a linked take (`library.claim_track_id`).
- Every settings read and write goes through the open entry's sidecar
  (`load_settings` / `save_settings` / `update_settings` take `sidecar`);
  jobs carry `sidecar` for a linked take.
- "New take..." (top bar) asks for a name and saves the sidecar beside the
  current one (the API takes a `folder` too; the button does not ask for one
  yet). It copies anchor, beat_pins, steady_spans, time_signature,
  pulses_per_bar, bars_per_chorus, form_start, fast_tempo, model, changes,
  key, and starts region, ensemble, erasures, additions, hands, score and
  line fresh. "Rename take..." renames the sidecar in place; the audio's own
  sidecar renamed becomes a linked take.
- Folder browser: an audio file with no sidecar is listed as the audio.
  With sidecars, the audio's row still opens its own sidecar and every
  sidecar in that folder about it is listed under it by take name (its own
  sidecar shown as "its own sidecar", linked ones as "take"). A linked
  sidecar whose audio is in another folder is listed in its own folder as
  "-> ../folder/file"; one whose audio is missing is shown greyed as "audio
  missing: ..." and opens nothing (never dropped). Recents name a linked
  take and say "take of <audio>".
- Export, the page view and the stem download are named for a linked take
  and written beside its sidecar (`Open_Sesame_Melody.0-67s.literal16.musicxml`);
  an audio's own sidecar names and places them exactly as before.
- The cache panel lists each recording once (its digest) and says "shared by
  N takes" (names in the tooltip) when more than one take has been opened on
  it.
- Harness: `library.discover(root) -> [(key, sidecar, audio)]` is the one
  walk run_eval, score_benchmark, benchmark_batch and locate_scores use;
  wjazz_batch takes the own sidecar's path from `library.settings_path`. A
  take's key is its sidecar's path; for an audio's own sidecar that is the
  audio's path, the key every pin has. run_eval logs a line when an own
  sidecar's `file` field disagrees with its name (it used to key by `file`).
- `scripts/dedupe_audio.py` is PREPARED, NOT RUN: dry run by default; with
  `--apply` it would keep one copy of each byte-identical group, make every
  other copy's sidecars linked takes of it (name, folder and contents kept,
  so no harness key moves) and delete the copy.

Commands (from the main checkout, `PYTHONPATH=%MH%\src` as above):

1. Acceptance, the harness card byte-identical:
   ```
   .venv\Scripts\python.exe %MH%\scripts\run_eval.py --db wjazz\wjazzd.db
   ```
   Expect every pin to hold, nothing re-transcribed, and NO "sidecar names
   ... as its file" lines. Report any such line and any moved pin.
2. The dedupe dry run, to see what it WOULD do (it changes nothing):
   ```
   .venv\Scripts\python.exe %MH%\scripts\dedupe_audio.py benchmark --keep-in Multi-Horn
   ```
   Report the KEEP/DELETE/LINK lines (or the group count, if long). Do not
   pass `--apply`.
3. In the GUI from the worktree (`set PYTHONPATH=%MH%\src` then
   `.venv\Scripts\python.exe -m swingscribe gui`, or the base-interpreter
   route): open `Open_Sesame.m4a`, press New take..., name it
   `Open_Sesame_Melody`; check the new sidecar beside it (an `audio` field,
   the anchor copied, no region); open both copies of the recording in two
   tabs and confirm each tab saves to its own sidecar; Rename take...; look
   at the folder browser in both folders and at the cache panel. Report what
   reads wrong or confusing -- the listener asked what the browser should
   show, and this is the proposal above.

## Local task C: two parts and the GUI

What landed: docs/multi-horn.md, "Two parts" and "The GUI"; the user guide's
"Takes" and "Two horns in harmony" sections.

Run the GUI from the worktree as in Local task B, open the Open Sesame head
(the span 0-67.308, model bsroformer_sw, stem other), set Ensemble to "Two
horns (a head)" and Transcribe (the review is the one Local task A cached,
so it opens at once if the span and stem match). Then:

1. The roll: two colours, the legend, the faint "heard, in neither voice"
   notes. Click one of each kind; the inspector names the voice.
2. The Voices tool (H): move a few notes, check the page view and Export
   follow, then "As heard" puts them back. Erase a note of a pair: its
   partner should be written once, in the upper voice.
3. The ear test (Transcription in the A/B) plays both voices.
4. Staves -> "Two parts (upper + lower)", Written for -> B♭ (trumpet), Lower
   part -> B♭ tenor: export, open in MuseScore (`.\pdf2musicxml render`
   on its folder), check two parts, each key and clef, nothing moved an
   octave, unisons in both parts.
5. Switch Ensemble back to Horn-led and back again: the edits made on the
   two-horn view are kept and return.

Report what reads wrong on the page or the roll, any console error (F12),
and any request that failed.

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
