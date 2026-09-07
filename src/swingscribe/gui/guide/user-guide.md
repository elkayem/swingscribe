# SwingScribe — User guide

## Overview

SwingScribe turns a jazz recording into swing-aware MusicXML. The GUI is where
you do that by hand, one solo at a time: select the span you care about,
isolate it from the rest of the band, transcribe it, review and clean up the
result, and export.

Launch it from the repo with:

```
uv run python -m swingscribe gui
```

On Windows, `.\swingscribe gui` (the `.cmd` shim beside `pyproject.toml`) does
the same thing. Prefer either to `uv run swingscribe`: that runs a
console-script `.exe` generated fresh at install time, which Windows Smart
App Control refuses as an unsigned binary it has never seen (`os error
4551`). The `README.md` has the details.

The app serves itself on `127.0.0.1:8420` and opens a browser tab there. It
listens on localhost only; the audio never leaves your machine.

## Opening a track

Click **Open track…** in the top bar to bring up the picker:

- **Recent** — tracks you've opened before.
- **Cache** — click **Show** to see what's cached per track (separated stems
  and the ingested wav) and reclaim disk space. This only deletes stems
  directories and ingest wavs — it never touches your saved span, downbeat,
  or edits.
- **Browse** — a folder browser starting from your drives.
- The text field at the bottom takes a pasted path to an audio file directly.

Whatever you set up for a track — the span, downbeat, ensemble, stem choice,
erasures, and so on — is saved beside the audio file itself, in
`<track>.swingscribe.json`. It travels with the file, not with the app's
cache.

## Zooming and panning

The same gestures work everywhere you'd want to zoom in: the Detail waveform
in panel 1, the isolated-stem waveform in panel 2, and the piano roll in
panel 3.

- **Scroll** to zoom, centered on the pointer.
- **Shift-scroll** to pan.
- **Drag** to pan.
- A trackpad's horizontal swipe pans too.
- The **+** / **−** chips zoom by a fixed step, and **Fit** resets to show
  the whole span.

The piano roll is the one exception while the **Edit** tool is selected:
there, a plain drag draws the rubber-band selection instead, so panning
becomes **shift-drag**.

The **Overview** waveform in panel 1 never zooms — it always shows the whole
track. Dragging on it draws a fresh A/B selection, and the box drawn on it
marks where the Detail view is; drag that box to slide the Detail view
without changing the selection.

## Step 1: Select the span

Opening a track for the first time — one with no remembered span — starts
you with the whole track selected, and the Detail view showing the whole
track too. Narrow it down to the solo from there.

**Overview vs. Detail:** the Overview is for finding your way around a
multi-minute file; the Detail view is where you actually place the
boundaries. Dragging on Overview draws a new selection; dragging elsewhere on
Detail pans.

**The A/B selection**, on the Detail waveform:

- Only the orange A and B handles change the selection. Drag a handle to
  move that edge.
- Or use **Set A** / **Set B** (keys <kbd>A</kbd> / <kbd>B</kbd>) to place an
  edge at the current playhead while the track plays, then the `−.1` / `+.1`
  nudge buttons to fine-tune it.
- Clicking anywhere else on Detail just moves the playhead; it does not move
  a handle.
- **Snap** (chip, or key <kbd>S</kbd>) snaps A/B to the nearest beat or bar
  while dragging or tapping — but never on a nudge, since the small nudges
  are exactly how you correct the grid's own small errors.

**Transport:** the play button, <kbd>Space</kbd> to play/pause, and
playback rate chips (1×, ¾×, ½×) for checking a fast line by ear. **Loop
A/B** (<kbd>L</kbd>) confines playback to the selection and loops it; switch
it off to listen around the span — before it, after it — without moving A or
B. **⇤ Start** (<kbd>Enter</kbd>) plays from the start: of the selection
while Loop A/B is on, of the track when it is off.

Each section has its own play button and its own **⇤ Start**, and pressing
one silences the others: play in section 1 is always the original recording,
in section 2 the isolated stem, in section 3 the transcription's rendering.
<kbd>Space</kbd> and <kbd>Enter</kbd> act on whichever section you last
played or clicked in.

**Beats:** click **Beats** to show the bar grid — bar lines, bar numbers, and
chorus markers — over the waveform, computed from the whole track (this may
run a short background job the first time). It's what transcription will
quantize against, so it's worth checking before you spend time downstream.

- <kbd>D</kbd>, or clicking a beat dot, sets the downbeat at the nearest
  beat — useful while the music is playing.
- <kbd>F</kbd>, or shift-clicking a beat, sets the **form start**: that beat
  becomes bar 1, chorus counting starts there, and everything before it is
  drawn faint and unnumbered. Handy for skipping an intro.
- The time-signature menu and the **2× time** toggle (for notating a ballad
  at twice the pulse) apply to the whole tune.
- **Chorus length** (8/12/16/24/32 bars, or none) draws a heavier line every
  N bars, for a solo that's a whole number of choruses.

## Step 2: Isolate & audition

This is the gate: if the soloist isn't clearly dominant in the isolated
stem, no amount of tuning downstream will rescue the transcription. Listen
here before spending time on transcription.

**Separation model:** the chips let you pick which model separates the
track. `bsroformer_sw` is the default — slower, but it routes horns to the
right stem far more reliably than `htdemucs`. `htdemucs` is there for when
speed matters more than routing accuracy. A dot on a chip means that model's
stems are already cached for this track/span; picking an uncached model
starts a background job.

Separation is scoped to your selected span, and the **Separate** button
shows a time estimate before you click it (a span-scoped Roformer separation
of a chorus or two is a matter of minutes, not the whole-track run).

While a separation job runs, a progress bar and message show; **Cancel**
stops the job and returns the panel to a plain **Separate** button, ready to
run again.

**Lead stem:** the menu lists what got separated for this model (`other`,
`vocals`, `guitar`, `piano`, `bass`, …) plus any sum of stems that can be
formed from what's on disk — for example `other+vocals` shows up when both
of those stems exist and might together hold a soloist Demucs split between
them mid-phrase.

**Audition:** the isolated-stem waveform plays looped over the span. The
A/B toggle switches between **Isolated**, **Original**, and **Both**, and
switching mid-phrase is sample-locked — you're comparing the exact same
instant either way. **Click** (<kbd>C</kbd>) mixes a metronome on the bar
grid into the audition, which is a fast way to hear whether the downbeat is
right. The rate chips (1×, ¾×, ½×) slow playback without changing pitch.

The **mixer** below lets you solo/mute and adjust the level of every stem
from this separation. **Download isolated span** saves the isolated stem as
a wav, and the command box shows the equivalent CLI invocation.

## Step 3: Transcribe & review

Click **Transcribe span** to run transcription over the selected span.

**Ensemble** tells the transcriber who's playing: `Horn-led`, `Trio (piano)`,
or `Solo piano`. A trio or solo-piano ensemble gets a second opinion from the
polyphonic piano model; a horn never does, because a piano model asked about
a saxophone vouches for nothing useful. The hint text next to the menu says
whether the piano model will be consulted for the current choice.

**Line** (pianists only) picks which detector supplies the melody:
"CREPE, checked by piano model" (the default, monophonic pitch tracking
corroborated by the piano model) or "Piano model, melody picked" (a
sequence chosen from everything the polyphonic model heard). They're two
takes of the same span — compare them by ear.

**The piano roll** draws notes over the bar grid, with opacity tracking
confidence, and carries the same beat strip along its bottom edge as the
waveforms: a tick per beat, a dot and number per bar, a gold dot at a
chorus start. Two lanes beneath it show the raw evidence continuously: f0 (raw
CREPE pitch, dim, against the smoothed kept pitch, bright — a gap between
them is a frame that got gated out) and gate (periodicity against its
threshold, with energy-gate failures shaded).

**Tools**, in the tool group above the roll:

- **Inspect** (the default) — clicking a note moves the playhead, sounds a
  plain tone at that note's pitch, and shows the frames that produced it in
  the inspector panel below (with a **♪ Play** button to hear it again).
  This works on ground-truth notes too, once a hand transcription is loaded
  — click any matched, wrong, or missed note to inspect and hear it.
  Dragging on the roll pans.
- **Edit** (<kbd>E</kbd> toggles between the two tools) — clicking a note
  silences it; clicking a faint magenta piano-model candidate switches it
  on and sounds it. Dragging a box silences every note it covers; alt-drag
  restores a run instead. With Edit selected, shift-drag pans (a plain drag
  draws the rubber band).

Toggle the piano-model candidates with the **piano model** chip
(<kbd>V</kbd>) — everything the piano model heard that the current line
left out is drawn faint on the roll. Switching one on with the Edit tool
adds it to the transcription: if it lands at the same time as a line note,
the two are written together as a **chord**, taking the line note's
duration.

Silenced notes stay visible, struck through — you can see what you cut.
**Undo** / **Redo** (<kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Shift+Z</kbd>) and
**Restore all** work over the whole edit history, and Restore all is itself
undoable.

Erasures are remembered **by content** — onset and exact pitch — not by
note number, so a later re-transcription that renumbers every note still
finds the right one to keep silenced. If a stored erasure no longer matches
anything (the transcriber changed and no longer emits that note), the edit
bar reports it rather than silently dropping it; **Discard** forgets those
permanently, and even that is undoable.

## Ground truth and scoring

**Ground truth…** loads a MuseScore hand transcription (`.mscz` / `.mscx`)
and draws its notes over yours, colour-coded by how each one aligned:

- **matched** — agrees with a note you transcribed.
- **wrong** — a note is there, but at the wrong pitch.
- **invented** — a note you transcribed with nothing in the hand
  transcription to match it.
- **missed** — a note in the hand transcription with nothing of yours to
  match it.

Each class has its own toggle chip so you can show or hide it, and its own
count. Ground-truth notes can be inspected and sounded the same way your own
notes can, with the Inspect tool.

**Two different questions, easy to conflate:** the pitch F1 shown on the
ground-truth bar is time-free and pitch-only — it asks *did we hear the
right notes?* The **Score it** button asks a different, harder question:
*are the notes we got written the way a human would write them?* — matching
rhythm and value, not just pitch. It always reads lower than the F1 above
it, because it charges the gap between performed timing and notated rhythm
to the transcriber. Neither number replaces the other.

## Export

**Export MusicXML** writes the score beside the audio file, with the span
folded into the filename — export the same track's second chorus later and
you get a second file, not an overwrite.

**Written for** picks the transposition the part should be notated in
(concert C, B♭ for trumpet/soprano, B♭ tenor, or E♭ for alto/baritone).
Nothing in the audio says which horn is playing, so this can only come from
you, and the key signature moves with your choice.

Bars in the export are numbered from 1 within the span you selected — the
way a solo transcription is normally numbered — not from the start of the
track. Silenced notes are left out of the export; candidates you switched on
are written in, as chords where they land on a line note.

If the file on disk is older than what's on screen (because you kept
editing after exporting), the export bar says so.

## Keyboard shortcuts

Shortcuts are ignored while you're typing into a text field, and most need a
track loaded.

- <kbd>Space</kbd> — play / pause
- <kbd>Enter</kbd> — play from the start of the active section: A (or the
  top of the track with Loop A/B off) in section 1, the span in sections 2
  and 3
- <kbd>A</kbd> / <kbd>B</kbd> — set edge A / B at the playhead
- <kbd>L</kbd> — toggle Loop A/B
- <kbd>S</kbd> — toggle snap to beat/bar
- <kbd>C</kbd> — toggle the click track in audition
- <kbd>D</kbd> — set the downbeat at the nearest beat
- <kbd>F</kbd> — set the form start (bar 1) at the nearest bar
- <kbd>E</kbd> — toggle the Inspect / Edit tool
- <kbd>V</kbd> — toggle the piano-model candidate overlay
- <kbd>X</kbd> — export MusicXML (once a review is up)
- <kbd>[</kbd> / <kbd>]</kbd> — nudge the focused A/B edge by −0.1s / +0.1s
  (add <kbd>Shift</kbd> for 0.01s)
- <kbd>←</kbd> / <kbd>→</kbd> — seek −2s / +2s (add <kbd>Shift</kbd> for
  0.1s)
- <kbd>Ctrl+Z</kbd> — undo an edit
- <kbd>Ctrl+Shift+Z</kbd> (or <kbd>Ctrl+Y</kbd>) — redo

## Troubleshooting

**A chunk of the solo is missing entirely.** Demucs assigns every moment to
exactly one stem, so a soloist it can't place consistently isn't attenuated
— it's switched to a different stem, leaving digital silence in the one
you're listening to. If the Lead stem menu offers a summed option like
`other+vocals`, try it: the soloist may be split between the two.

**The bars don't line up with what you hear.** Turn on **Click** in the
audition step, or **Beats** in the span step, and listen against the
metronome — a wrong downbeat is obvious against the click track, and a
click or shift-click on the right beat fixes it.

**A piano solo doesn't seem to be getting a second opinion.** Check the
**Ensemble** menu — leaving it unset behaves like `Horn-led`, which never
consults the piano model. Pick `Trio (piano)` or `Solo piano` explicitly.

**A separation is stuck or you picked the wrong model.** Click **Cancel**
to stop it and return to the Separate button; pick a different model or
span and run it again.
