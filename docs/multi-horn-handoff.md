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
| A. Multi-horn core + `scripts/multi_horn_page.py` | measured four times (Local tasks A-A4); swing is the head's default, lag read once over both horns; the listener's bar 24/26/29 corrections in; waiting on Local task A5 |
| B. Linked sidecars | accepted (Local task B); every script finds a take's audio through library; dedupe reversible (Recycle Bin or --trash, manifest, --undo); the listener said go: waiting on Local task B2 |
| C. Two parts, GUI, guide | checked (Local task C); fixes pushed |

What the reports changed (2026-10-09; details in
[multi-horn.md](multi-horn.md), "The first measurement"):

- Local task A: tails cut at a new chord and a note ending loses to a note
  starting (the listener's bars 26, 28); split held notes joined where
  CREPE holds them (24, 28, 31-32); scoops marked and folded as grace notes
  (23); a two-bar excursion inside a long phrase moved up on its own (roll
  bars 15-16); the script's cp1252 crash. The review key moved
  (`multi_horn_version` 2), so the head re-transcribes once.
- Local task B: `dedupe_audio.py` prints forward slashes (the Windows test
  failure), keeps the ORIGINAL by default (the copy created first), leaves
  a group whose names say two recordings (the Hawkins/Parker Ballade), and
  re-points every linked take anywhere under the root that names a deleted
  copy (REPOINT lines). The folder browser lists a take of a recording in
  another folder as a row of its own, not under a copy of the same bytes.
- Local task C: the page summary gives both parts' intervals ("written
  +2 / +14"); the Voices tool stores only real moves; the guide says a
  tenor part can sit above the trumpet's on the page.

## Setting up (once)

Since 2026-10-09 the listener's MAIN checkout runs this branch (their
request, to try it): update it with `git pull` and run every command below
from its root, `.venv\Scripts\python.exe scripts\...`. Every push reaches
their app on the next pull, so the branch is kept runnable. The worktree
route that follows is for a checkout that stays on master.

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

## Local task A2: the head again, after the fixes

From the main checkout with the worktree updated (`git -C %MH% checkout
--detach origin/multi-horn`). The first run re-transcribes (the rules moved
the review key); the rest read the cache.

```
%PAGE% --out OUT\os2.literal16.musicxml --dump-voices OUT\os2.literal16.txt
%PAGE% --lag --out OUT\os2.lag.musicxml --dump-voices OUT\os2.lag.txt
%PAGE% --by-tempo --out OUT\os2.bytempo.musicxml --dump-voices OUT\os2.bytempo.txt
%PAGE% --lag --by-tempo --out OUT\os2.lag-bytempo.musicxml --dump-voices OUT\os2.lag-bytempo.txt
%PAGE% --no-fold --out OUT\os2.nofold.musicxml --dump-voices OUT\os2.nofold.txt
```

The transcribe log now says what each rule did ("N tail(s) cut at a new
chord, N split held note(s) joined, N lead-in(s) marked"), and the dump
marks lead-ins in the heard section and writes a grace as `(Db5)D5:4`.

Report:

1. Each rule's count from the log, and the summary lines.
2. The listener's bars 23-38 (page bars 41-56) again, against the
   screenshot, from `os2.literal16.txt` and the best of the `--by-tempo`
   pages: what the fixes mended (23, 24, 26, 28, 31-32), what they broke,
   and whether `--by-tempo` reads the chords on the beat without losing a
   16th the screenshot has.
3. Roll bars 15-16: moved up, and nothing around them moved with them?
4. Any real note now lost: a held note cut by rule 2 where only one horn
   moved and a stray note struck with it, a repeated note joined that the
   horn really re-attacked, a short note folded that was a real note.
5. MuseScore opens each file (`.\pdf2musicxml render OUT`), and the grace
   notes look right.
6. For the listener: scoops as grace notes, or nothing at all? Eighths by
   tempo on or off? Bars 24 and 32's lower third kept or dropped?

## Local task A3: the head a third time, and the dedupe dry run

What A2 changed is in [multi-horn.md](multi-horn.md), "The second
measurement": the octave move stops at the excursion's end, E natural is
no longer F-flat, the script names a take's page for the take and prints
the per-rule counts, run_eval leaves a scoreless head out, and dedupe
decides by sidecar. Nothing in the review key moved: the cached head
review is reused.

```
%PAGE% --by-tempo --out OUT\os3.bytempo.musicxml --dump-voices OUT\os3.bytempo.txt
%PAGE% --out OUT\os3.literal16.musicxml --dump-voices OUT\os3.literal16.txt
.venv\Scripts\python.exe %MH%\scripts\dedupe_audio.py benchmark
```

Report:

1. Roll bars 15-17 (page bars 23-25): 15-16 close, 17's A-flat back under
   the C, nothing else moved.
2. Any E-flat-major or A-flat-major spelling that now reads wrong.
3. The default page name (no `--out`): the take's, beside its sidecar.
4. The dedupe dry run: KEEP / DELETE / LINK / REPOINT / LEAVE counts. Every
   copy with a sidecar should now be a LINK (Blue Train, So What, the
   Parker copies), the Ballade a LEAVE, and Charlie-Parker-Embraceable-You
   a LEAVE if its page is beside it by name (else say what it is paired
   with). Do not pass `--apply`.
5. For the next round on bars 25-31: the HEARD section's lines (onset,
   duration, voice, pitch, confidence) from page bar 43 to 49 of
   `os3.bytempo.txt`. Bar 26's voice order, 27's late Ab4, 29's stray Gb4
   and 31's late Gb4 cannot be read without them.

## Local task A4: the head on the listener's defaults

`--by-tempo` and the sidecar's `literal_tempo` are gone: eighths are the
head's DEFAULT rhythm now (`literal-8`, "Literal 8ths (16ths under 160
bpm)" in the Rhythm menu), and `--timing literal-16` (the menu's "Literal
16ths") is the choice for a melody in sixteenths. The lag is taken out by
DEFAULT too (the listener's yes); `--no-lag` keeps it. The cached review
is reused (nothing in its key moved).

```
%PAGE% --out OUT\os4.musicxml --dump-voices OUT\os4.txt
%PAGE% --no-lag --out OUT\os4.nolag.musicxml
%PAGE% --timing literal-16 --out OUT\os4.16ths.musicxml
```

Report:

1. `os4` against A3's `os3.lag-bytempo`, and `os4.nolag` against
   `os3.bytempo`: each should be the same page note for note except
   spelling (`literal-8` IS by-tempo, and the default now takes the lag
   out).
2. Spelling: page bar 10's G4/B4 chord over G7 reads B natural, page bar
   54's lower C-flat 4 now reads B3 (B natural), and no B or E natural
   reads wrong now (an A-flat-major page should hold no C-flat or F-flat).
3. In the GUI: the Rhythm menu shows "Literal 8ths (16ths under 160 bpm)"
   for the head and offers "Literal 16ths"; Export names the file
   `.literal8` / `.literal16`.
4. The listener's swing-or-literal choice. If it is swing, say so before
   it becomes the default: swing reads the lag per voice today, and must
   read it once over both horns first (multi-horn.md, "The third
   measurement").

## Local task A5: the head on swing, with the listener's corrections

What landed after A4 (multi-horn.md, "The fourth measurement"):

- SWING is the head's default rhythm (the listener's "make swing default");
  "Literal 8ths" and "Literal 16ths" stay in the menu for a straight-eighth
  head. The line's lag is read ONCE over both horns on a swing page too.
- Bar 24: a rest of up to an eighth before a voice's next note is written
  into the note before it (`--no-close-rests` keeps them).
- Bar 26: a note a step from the only note sounding, which ends within
  0.25 s, is that horn's legato successor and keeps its voice. The review
  key moved (`multi_horn_version` 3): the first run re-transcribes.
- Bar 29: faint scraps (under 80 ms AND confidence under 0.4 AND not a
  lead-in) can be left off with `--drop-faint`; OFF, and the dump lists
  them either way.
- Bar 25: `scripts/multi_horn_joins.py` measures every same-pitch join.

```
set PAGE=.venv\Scripts\python.exe scripts\multi_horn_page.py AUDIO --sidecar TAKE --start 0 --end 67.308
%PAGE% --out OUT\os5.musicxml --dump-voices OUT\os5.txt
%PAGE% --timing literal-8 --out OUT\os5.literal8.musicxml --dump-voices OUT\os5.literal8.txt
%PAGE% --no-close-rests --out OUT\os5.open.musicxml --dump-voices OUT\os5.open.txt
%PAGE% --drop-faint --out OUT\os5.faint.musicxml --dump-voices OUT\os5.faint.txt
.venv\Scripts\python.exe scripts\multi_horn_joins.py AUDIO --sidecar TAKE --json OUT\joins.json
```

Report:

1. The transcribe line's counts (tails, legato successors, rejoined,
   lead-ins) and each run's summary (rests drawn + hidden, faint scraps).
2. `os5` (swing) against A4's `os4` and A3's `os3.swing`, the listener's
   bars 23-38 (page 41-56) above all: 24 (the lower A a whole note), 26
   (the tenor's E-flat into D in voice 2; the trumpet's F4 tied over, a
   rest, F4 on 4), 25, 29; and any chord whose two horns now land apart
   (the joint lag should have closed those, not opened new ones).
3. Closing rests: `os5` against `os5.open` -- how many rests went, and any
   the listener hears as a REAL rest.
4. The faint list from `os5.txt`: which are scraps, which are notes; and
   whether `os5.faint` loses anything it should keep.
5. The joins table, with the listener's marks: bar 25's lower C at 41.651
   (one note, they say), the A section's F5 F5 F5 (roll bars 6 and 22,
   re-attacks), and any other repeat they can call. Which column, if any,
   separates the two?
6. MuseScore opens each file (`.\pdf2musicxml render OUT`).

## Local task B2: the clean-up, reversibly, with every check

The listener said "go ahead with the clean-up". `dedupe_audio.py --apply`
never deletes: on Windows each copy goes to the Recycle Bin, and a
manifest of every DELETE, LINK and REPOINT, with each rewritten sidecar's
previous content, is written to `benchmark\.dedupe\manifest-<time>.json`
before the first change; `--undo MANIFEST` restores the audio and the
sidecars. Every script now finds a take's audio through
`library.audio_for_key` / `library.discover` (a test holds scripts/ to
it), so no track drops out once its copy is gone.

1. Rehearse the Recycle Bin and the undo on a scratch folder first (the
   Recycle Bin path is Windows-only and untested in the cloud):
   ```
   mkdir C:\dedupe-rehearsal\a C:\dedupe-rehearsal\b
   copy SOMEAUDIO.m4a C:\dedupe-rehearsal\a\x.m4a
   copy SOMEAUDIO.m4a C:\dedupe-rehearsal\b\x-copy.m4a
   echo {"region": [0, 1]} > C:\dedupe-rehearsal\b\x-copy.m4a.swingscribe.json
   .venv\Scripts\python.exe scripts\dedupe_audio.py C:\dedupe-rehearsal --apply
   .venv\Scripts\python.exe scripts\dedupe_audio.py --undo C:\dedupe-rehearsal\.dedupe\manifest-<time>.json
   ```
   After --apply: one copy in the Recycle Bin, its sidecar naming the kept
   file. After --undo: the copy back where it was, the sidecar as it was.
   If the undo cannot bring the audio back from the Recycle Bin, say so --
   `--trash D:\somewhere` is the fallback, a plain move.
2. Back up every sidecar:
   `robocopy benchmark C:\dedupe-backup *.swingscribe.json /S`
3. Before:
   ```
   .venv\Scripts\python.exe scripts\run_eval.py --db wjazz\wjazzd.db --json OUT\card-before.json > OUT\card-before.txt
   .venv\Scripts\python.exe scripts\error_taxonomy.py --db wjazz\wjazzd.db --count > OUT\taxonomy-before.txt
   .venv\Scripts\python.exe scripts\wjazz_reviews.py --count > OUT\reviews-before.txt
   .venv\Scripts\python.exe scripts\wjazz_reviews.py --folder Omnibook --count > OUT\reviews-omnibook-before.txt
   .venv\Scripts\python.exe scripts\dedupe_audio.py benchmark > OUT\dedupe-dry.txt
   ```
4. Apply: `.venv\Scripts\python.exe scripts\dedupe_audio.py benchmark --apply > OUT\dedupe-apply.txt`
5. After: the four commands of step 3 again, to `*-after` files. Then:
   - `fc /b OUT\card-before.json OUT\card-after.json` must say no
     differences, and the card must end "Baselines: all 4768 numbers
     unchanged" (or `run_eval.py ... --against OUT\card-before.json`);
   - the taxonomy counts and the solo NAMES in the reviews lists must
     match; the reviews' `<- audio` paths change for the linked takes
     (they name the kept file now), and that is expected;
   - nothing re-transcribed in either run_eval.
6. If anything moved: `dedupe_audio.py --undo benchmark\.dedupe\manifest-<time>.json`,
   then report with the before/after files.

Report: the dry run's counts, the apply's output and manifest path, each
comparison, and anything the undo rehearsal did not restore.

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
   .venv\Scripts\python.exe %MH%\scripts\dedupe_audio.py benchmark
   ```
   It keeps the original of each group (the copy created first) unless
   `--keep-in` names a folder. Report the KEEP/DELETE/LINK/REPOINT/LEAVE
   lines (or the counts, if long). Do not pass `--apply`. (Done once on
   9f73970 with `--keep-in Multi-Horn`: 41 DELETE, 40 LINK, 338 MB; re-run
   it on the fixed script: the Ballade pair should now be a LEAVE, and
   Open_Sesame_Melody a REPOINT or nothing, depending on which copy is
   kept.)
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
