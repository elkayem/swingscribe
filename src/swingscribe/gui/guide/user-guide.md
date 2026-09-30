# SwingScribe user guide

SwingScribe turns a jazz recording into a solo transcription. You work one
solo at a time, in three steps down one page:

1. **Select the span.** Mark where the solo starts and ends, and check the
   bar grid.
2. **Isolate and audition.** Separate the soloist from the band, and listen
   to make sure the separation worked.
3. **Transcribe and review.** Get the notes, clean up anything that is not
   the solo, and export MusicXML.

This guide covers every control. To install SwingScribe, see the
[installation guide](https://github.com/elkayem/swingscribe/blob/master/INSTALL.md).
A few terms (stem, span, downbeat, F1) are defined at the end.

## Starting and stopping

**The Windows app:** double-click the SwingScribe icon. A console window
opens minimized, and the app opens in your browser.

**From source:** run this command from the repository:

```
uv run python -m swingscribe gui
```

On Windows, `.\swingscribe gui` does the same thing through the `.cmd` shim
beside `pyproject.toml`. Do not use `uv run swingscribe`: Windows Smart App
Control refuses the `swingscribe.exe` stub it runs (see Troubleshooting).

You can name a file to open it straight away:

```
uv run python -m swingscribe gui path/to/track.m4a
```

`gui` also takes these options:

- `--port <n>` serves on a different port. The default is 8420.
- `--no-browser` starts the server without opening a browser tab.
- `--library <folder>` sets the folder the track picker starts in.

The app lives at `http://127.0.0.1:8420/`. It listens only on your own
machine, so your audio never leaves it. **Help**, in the header, opens this
guide in a new tab.

### Quitting

**Quit** is at the right of the header, and at the top of the Open a track
window. It stops the server. The page replaces itself with a notice, and if
you started from the icon, the console window closes too.

If a separation or transcription is still running, the button turns red and
names it. Click again within four seconds to abandon the job and quit
anyway. Nothing you decided is lost, because your settings are saved beside
the audio as you make them.

Closing the browser tab does **not** stop the server. To get back, open
`http://127.0.0.1:8420/` again.

## Opening a track

Click **Open track…** in the header to open the track picker.

- **Recent** lists tracks you have opened before, with the stem and span
  you last used.
- **Cache** shows, once you click **Show**, how much disk each track's
  cached data uses. See "Freeing disk space" below.
- **Browse** is a folder browser. It starts in the library folder: your
  Music folder in the Windows app, or wherever you launched from. Use
  **↑ Up**, the drive menu, or type a folder into the path box and press
  <kbd>Enter</kbd>.
- The field at the bottom takes a full path to an audio file. Paste one and
  click **Open**.

SwingScribe opens `.wav`, `.flac`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`,
`.wma`, `.aiff` and `.aif` files. The files it writes itself, such as
isolated stems and A/B mixes, are hidden from the list.

### Your settings travel with the audio

Everything you decide about a track, from the span and downbeat to your
edits and the transposition, is saved in a small file beside the audio. For
`solo.m4a` it is `solo.m4a.swingscribe.json`. Keep it with the audio, and
the track opens the way you left it.

### Freeing disk space

Separated stems are big. The **Cache** panel lists each track's sets of
stems and its decoded wav. **Delete all** frees a whole track, and **✕**
frees one set of stems. Each delete asks first: the button changes to
"free N MB?", and a second click within four seconds confirms it. **No
track known** gathers cached data whose track can no longer be found.

Deleting cache data never touches your settings file. The worst it costs is
re-running a separation.

## Getting around

The page has three sections, and each has its own transport. Section 1 plays
the original recording, section 2 the isolated stem, and section 3 the
transcription. Pressing play in one section stops the others. <kbd>Space</kbd>
and <kbd>Enter</kbd> act on whichever section you last played or clicked in.

### Zooming and panning

The same gestures work on the Detail waveform in section 1, the stem
waveform in section 2, and the piano roll and the page in section 3.

- **Scroll** to zoom around the pointer.
- **Shift-scroll** or **drag** to pan. A trackpad's sideways swipe pans too.
- The **+** and **−** chips zoom in steps.
- **Fit** shows the whole span. On the Detail view it is **Fit selection**,
  which leaves a little room either side. **Edge A** and **Edge B** zoom in
  tight around one edge of the selection, so you can place it by eye.

The one exception is the piano roll with the **Edit** tool selected. There a
plain drag draws a selection box, and **shift-drag** pans.

The **Overview** waveform at the top of section 1 never zooms: it always
shows the whole track. What a drag on it does depends on where it starts:

- Inside the box that marks the Detail view, it slides the Detail view.
- On an edge of the selection, it moves that edge.
- Inside the selection, it moves the whole selection.
- Anywhere else, it draws a new selection.

### Playback speed

Every transport has the same speed control, so you can slow a fast line
down to hear it. The pitch never changes.

- The chips are **1×**, **¾×**, **½×** and **¼×**, and the slider runs
  from 20% to 200%.
- **−** and **+** step by one percent, or five with a shift-click.
  Scrolling over the slider does the same.
- Click the readout to type a speed, such as `43`, `43%` or `0.43`, and
  press <kbd>Enter</kbd>. <kbd>Esc</kbd> puts it back.
- <kbd>,</kbd> and <kbd>.</kbd> change the active section's speed by five
  percent, or one with <kbd>Shift</kbd>.

In section 1 a new speed takes effect at once. Sections 2 and 3 stretch the
audio on the server, so the change applies when you let go of the slider
and takes a moment to arrive. Press play meanwhile and playback starts as
soon as it lands.

## Step 1: Select the span

The first time you open a track, the whole track is selected. Narrow the
selection down to the solo. Use the Overview to find your way around a long
file, and the Detail view to place the edges exactly.

### Placing A and B

On the Detail waveform, only the orange **A** and **B** handles change the
selection.

- Drag a handle to move that edge.
- Or, while the track plays, press **Set A** or **Set B** (keys <kbd>A</kbd>
  and <kbd>B</kbd>) to put an edge at the playhead. Then fine-tune it with
  the **−.1** and **+.1** nudge buttons, which move it a tenth of a second.
- Clicking anywhere else on the Detail view moves the playhead. It never
  moves a handle.
- **Snap** (key <kbd>S</kbd>) cycles through **off**, **bar** and **beat**.
  With snap on, a dragged or tapped edge lands on the nearest bar line or
  beat. The nudges never snap, so you can still correct a small error in
  the beat grid.

The readout at the right shows the span's length and how many bars it
covers.

### Transport

The play button or <kbd>Space</kbd> plays and pauses. **Loop A/B**
(<kbd>L</kbd>) keeps playback inside the selection and loops it. Switch it
off to listen before and after the span without moving A or B. **⇤ Start**
(<kbd>Enter</kbd>) plays from the start of the selection, or from the start
of the track when Loop A/B is off.

### The bar grid

The bar grid is what the transcription will be written against, so check it
before you go further. Click **Beats** to compute it. The first time takes
a few seconds, and the chip shows the progress. After that the grid is
cached and appears whenever you open the track, and **Beats** just shows or
hides it.

The grid is drawn over the waveforms: a tick for each beat, a numbered dot
for each bar, and a gold dot at the start of each chorus. The readout above
the Detail view gives the tempo, the time signature, how many seconds of
the track have no steady beat (shaded on the waveform), and the bar and
chorus count.

- **Downbeat:** press <kbd>D</kbd> to put the downbeat on the beat nearest
  the playhead, or click a beat dot. Until you do, SwingScribe guesses it
  from the music **around your selection**, so the bar lines can shift when
  you select a different part of a long track. That is deliberate: a beat
  lost elsewhere in the tune should not throw off your solo. A downbeat you
  set yourself stays put.
- **Form start:** press <kbd>F</kbd>, or shift-click a beat dot, to make the
  nearest bar line bar 1. Chorus counting starts there, and everything
  before it is drawn faint and unnumbered, which is handy for skipping an
  intro. The **bar 1 @ m:ss** chip shows where it is. Its **✕** clears it.
- **Time signature:** the menu offers 2/4, 3/4, 4/4, 5/4, 6/4, 7/4, 3/8,
  6/8, 9/8 and 12/8.
- **2× time** notates the solo at twice the tracked pulse. Use it for a
  ballad played in double time, so a run of 32nd notes becomes ordinary
  sixteenths.
- **Chorus length** (8, 12, 16, 24 or 32 bars, or none) draws a heavier line
  every N bars. Choose **custom…** for a form the menu does not list, such
  as a 20-bar tune. Type the number and press <kbd>Enter</kbd>, or
  <kbd>Esc</kbd> to cancel. The custom length joins the menu and is saved
  with the track.

Snap, the time signature, 2× time and chorus length stay disabled until the
track has a beat grid.

## Step 2: Isolate and audition

This step is the gate. If the soloist is not clearly on top in the isolated
stem, nothing later on can rescue the transcription. Listen here before you
transcribe.

### Choosing a separation model

The chips choose which AI model separates the track. Hover over a chip to
see what it is. A lit dot means its stems for this span are already on
disk.

- **BS-RoFormer** is the default. It is a Band-Split RoPE Transformer, the
  architecture that won the music separation track of the 2023 Sound
  Demixing Challenge. It is much slower than Demucs, but far better at
  keeping a horn in one stem.
- **Demucs** (Hybrid Transformer Demucs) is the fast choice. It gives four
  stems (vocals, drums, bass and *other*) and takes about three minutes
  for a ten-minute track on a CPU.
- **Demucs 6-stem** adds guitar and piano stems. It is worth trying on a
  piano solo, but it sometimes files a horn under guitar or vocals.
- **Demucs fine-tuned** averages four Demucs models. It is four times
  slower than Demucs and, on SwingScribe's benchmarks, no more accurate.
  It is kept for comparison.

The configuration file calls these `bsroformer_sw`, `htdemucs`,
`htdemucs_6s` and `htdemucs_ft`.

### Separating

Separation covers only your selected span. That is what makes BS-RoFormer
practical: a solo takes minutes, not the tens of minutes a whole track
would. The button says what it will do and how long it should take, for
example **Separate selection with BS-RoFormer (~4 min)**. It disappears
once this span's stems exist. While the job runs, a progress bar shows the
time left, and **Cancel** stops it.

### Lead stem

The **Lead stem** menu picks the stem that holds the soloist. It lists
every stem the model produced (`other`, `vocals`, `guitar`, `piano`,
`bass` and so on), plus two sums:

- `other+vocals`
- `other+vocals+guitar+piano`

A sum helps when a model has switched the soloist between stems mid-phrase
(see Troubleshooting). The menu starts on `piano` for a piano ensemble and
on `other` for everything else. On a track with no ensemble yet, the
suggestion in step 3 (see "Who is playing") names a lead stem too.

### Audition

The isolated stem is drawn in teal over the original mix, and plays looped
over the span.

- The **Isolated**, **Original** and **Both** toggle switches what you hear.
  Switching is sample-locked, so you compare exactly the same instant.
- **Click** (<kbd>C</kbd>) adds a metronome on the bar grid. It is the
  quickest way to hear whether the downbeat is right, and it needs a beat
  grid.
- The **mixer** has a row for the original mix, each stem, and the click.
  Each row has a mute toggle (◉ / ○) and a level slider.
- **Download isolated span** saves the isolated stem over the span as a wav,
  at the current playback speed.
- The command box shows the equivalent `ab` command line, with a **Copy**
  button. See "The command line" below.

## Step 3: Transcribe and review

Click **Transcribe span** to transcribe the lead stem over the selected
span. Once a transcription exists, the button reads **Re-transcribe**. A
transcription that is already cached loads by itself when you open the
track.

### Who is playing

**Ensemble** tells SwingScribe who is playing: **Horn-led**, **Trio
(piano)** or **Solo piano**. A pianist is transcribed with the help of a
polyphonic piano model, which hears every note played. A horn never is,
because a piano model asked about a saxophone vouches for nothing. The note
beside the menu says whether the piano model will be consulted. Changing
the ensemble clears the review, so transcribe again afterwards.

Until a track has an ensemble of its own, SwingScribe suggests one. Once
the span is separated, a line under the menus says who the stems say is
playing, for example **Suggested: Trio (piano), lead stem `piano`**, with
the reason underneath. It compares how loud each stem is over your
selection, second by second: over a piano solo the `piano` stem carries
the line and the stem a horn is filed under goes quiet.

- **Apply** sets Ensemble and Lead stem to the suggestion.
- **Keep** stores what the menu shows now, so you are not asked again.
- Nothing changes until you click one of them. Once the track has an
  ensemble (chosen from the menu, applied or kept) the line goes away, and
  a choice you made is never changed for you.
- When the stems agree with the menus, the line is one quiet sentence.
  Hover over it for the reason.

**No suggestion** means the stems cannot decide, and the reason says why.
The two possible mistakes are not equal. A piano solo left on Horn-led only
misses the piano model's help. A horn sent to the piano model loses its
whole line, because the piano model cannot vouch for a single saxophone
note. So Trio is suggested only when the piano clearly carries the
selection. On the 111 solos SwingScribe is measured on, the suggestion was
right every time and never called a horn solo Trio.

- It needs **BS-RoFormer** stems. The Demucs models give no suggestion:
  Demucs 6-stem sometimes files a piano solo under `guitar`, and the
  four-stem models have no piano stem.
- It needs all six of BS-RoFormer's stems, and at least 15 seconds of
  melody in the selection.
- Select the solo itself. A horn solo selected together with the piano solo
  after it is suggested Horn-led, with a note to select the piano solo
  alone. A piano solo selected with up to 8 to 12 seconds of the horn solo
  before it can still be suggested Trio, and the piano model then judges
  those horn seconds too.
- Vibes, organ and Rhodes are untested. The suggestion reads the `piano`
  stem, so if one of them lands there it would be suggested Trio. Check by
  ear before you apply it.

**Line** (pianists only) chooses where the melody comes from:

- **Piano model, melody picked** is the default. The melody is chosen, as a
  line, from everything the piano model heard.
- **CREPE, checked by piano model** tracks the melody with CREPE, a neural
  network pitch tracker that follows one line at a time. The piano model
  then corrects its octaves, drops notes it cannot vouch for, and fills its
  gaps.

They are two takes of the same span, so compare them by ear. Against hand
transcriptions, the picked melody gets more of the right notes for six
pianists out of seven. The CREPE take is there for the passage where it
hears better, and its export gets `.crepe` in the file name.

**Piano notes** (pianists only) chooses which of the piano's notes are on the
roll and the page:

- **Melody line** is the default: the line chosen above, usually the top
  note but not always, plus any of the piano model's notes you switch on.
- **All notes** is everything the piano model heard, both hands, chords
  and all. It is another view of the same transcription, so switching costs
  no re-transcribing. Notes struck together are written as one chord, which
  lasts as long as its longest note. Line is hidden on this view, because no
  single line is drawn.

With **All notes**, **Staves** chooses **One staff** or **Two staves (treble +
bass)**: the right hand on a treble staff over the left hand on a bass staff.
The first guess puts middle C and above in the right hand and everything
below in the left. A dashed line on the roll marks that split, and the two
hands are drawn in different colours. The **Hands** tool moves any note to
the other hand (see below).

Each staff is one voice. A note held while other notes in the same hand move
is cut short where the next of them starts; the two hands never cut each
other short.

Silencing a note on the All-notes view is kept separate from silencing it on
the melody line. A left-hand note you silenced as "not the solo" on the line
is still there on the All-notes page, which is what that page is for.
Hand transcriptions notate the melody only, so **Ground truth** and **Score
it** work on the melody line, not on All notes.

### The piano roll

The notes are drawn over the bar grid, with the same beat strip along the
bottom as the waveforms. A note's opacity shows how confident the
transcriber was. The line above the roll counts the notes and shows how much
of the span had a clear pitch.

Two lanes under the roll show the raw evidence:

- **f0** is the pitch trace. The dim line is the raw pitch estimate, and
  the bright line is the pitch that was kept. A gap between them is a frame
  that was gated out.
- **Gate** is periodicity, meaning how clearly pitched each moment is,
  against the threshold a note must pass. Shading marks frames rejected for
  being too quiet.

The section's transport plays **Original** (the default), **Transcription**
(the notes as plain tones, with silenced notes left out) or **Both**.

### Inspect, Edit and Hands

The tools sit above the edit bar. <kbd>E</kbd> switches between Inspect and
Edit. **Hands** appears only on a two-staff page, and <kbd>H</kbd> switches
to it and back.

- **Inspect** is the default. Click a note to move the playhead there, hear
  the note's pitch, and see the evidence behind it in the inspector below:
  the frames, their periodicity, the pitch spread, and a plain-language
  verdict. **♪ Play** sounds it again. Dragging pans.
- **Edit** changes the transcription. Click a note to silence it, or click
  it again to bring it back. Drag a box to silence every note inside it.
  Alt-drag a box to restore them. Shift-drag pans.
- **Hands** chooses which staff notes go on. Drag a box to select the notes
  inside it, and <kbd>Ctrl</kbd>-drag to add another group to the
  selection. Click a note to select it alone, or <kbd>Ctrl</kbd>-click to
  add or remove it. Then click **Right hand ↑** or **Left hand ↓**, or
  press <kbd>↑</kbd> or <kbd>↓</kbd>. **Reset to guess** gives the selected
  notes back to the middle-C guess. The selection stays after a move, so a
  wrong call is one key from being put right. <kbd>Esc</kbd> clears it, and
  shift-drag pans. Selected notes are outlined; the inspector says which
  hand a note is on and whether that was your choice or the guess.

Silenced notes stay visible, struck through, so you can see what you cut.
**↶** and **↷** undo and redo (<kbd>Ctrl+Z</kbd> and
<kbd>Ctrl+Shift+Z</kbd>) across the whole edit history. **Restore all**
brings back every silenced note, and it can be undone too. The edit bar
counts what you have silenced and added.

### Notes the piano model heard

For a pianist, everything the piano model heard that the melody left out
is drawn faint on the roll. The **piano model · N** chip (<kbd>V</kbd>)
shows or hides these candidates. With **Edit** selected, click a candidate
to switch it on. It joins the transcription, and if it sounds together with
a melody note, the two are written as a chord with the melody note's
length. With **Inspect**, clicking a candidate shows how loudly the model
heard it and whether it is on the page.

### Edits survive re-transcription

Edits are remembered by the note's onset and exact pitch, not by its number
in the list, so a later transcription that renumbers every note still finds
the right one. The same goes for the hand you put a note in. If a silenced
note has vanished from the new transcription, the app says it is "already
gone": good news, since the transcriber now agrees with you. If one now
sounds at a different pitch, the app says it is "worth a look".
**Discard** forgets unmatched silenced notes for good, and even that can be
undone.

## Comparing with a hand transcription

Once a transcription exists, **Ground truth…** loads a hand transcription
and lays it over yours. It lists the scores beside the track first, and
accepts MuseScore files (`.mscz`, `.mscx`) and MusicXML (`.musicxml`,
`.xml`). The link is saved with the track, and **✕** removes it.

Every note is marked by how the two aligned. Each class has a chip that
shows or hides it, with a count:

- **matched**: you and the hand transcription agree.
- **wrong note**: a note is there in both, at different pitches.
- **invented**: a note you have that the hand transcription does not.
- **missed**: a note in the hand transcription that you do not have.

The line beside the chips names the score and gives its F1. The score is
placed against your notes by matching the notes themselves, not by clock
time, and a note that cannot be placed is pinned to the span rather than
dropped. Hand-transcription notes can be inspected and played with the
Inspect tool, just like your own.

### Two questions, two numbers

The **F1** on the ground-truth line asks: *did we hear the right notes?* It
compares pitches only and ignores rhythm.

**Score it**, in the export bar, asks a harder question: *are the notes
written the way a human wrote them?* It compares the written rhythm and note
values, so it always reads lower than F1. It charges every difference
between the played timing and the written rhythm to the transcriber. The
result looks like this:

```
vs solo.mscz: rhythm 0.82 · value 0.78 · 88% lined up (171/194) · on the bar 0.89
```

- **rhythm** is the share of matched notes whose written position agrees
  with the hand transcription.
- **value** is the share whose written note length agrees.
- **lined up** is how much of the hand transcription could be matched at
  all. Below half, the two are probably not the same solo, and SwingScribe
  withholds the rhythm score rather than show a meaningless number.
- **on the bar** is the share of matched notes written on the same beat of
  the bar as the hand transcription. A page whose every bar line is a beat
  off still scores well on rhythm, because the gaps between notes are all
  right. This is the number that catches it. A page on its bar lines reads
  about 0.8 to 0.95. If most notes sit the same distance off, the line
  turns into a **BAR LINES OFF** warning that says how far off they are and
  which way to move the downbeat. Move it, export again and score again.

### Scores built from the Weimar Jazz Database

A score built from the
[Weimar Jazz Database](https://jazzomat.hfm-weimar.de/dbformat/dboverview.html)
with the `wjazz_score` tool has a human's pitches, onsets and beats. Its
rhythm, though, is the database's automatic quantisation of the played
timing, which is more literal than any transcriber: a swung offbeat can land
on a dotted position. Trust its notes and bar lines, not its note values.

## Exporting MusicXML

**Export MusicXML** (<kbd>X</kbd>) writes the score beside the audio file,
with the span in the file name, for example `solo.42-118s.musicxml`. Export
the second chorus later and you get a second file, not an overwrite. The
export bar then shows a **Download** link and a summary: bars, notes, time
signature, swing, and where the file went. Export needs a beat grid, so
press **Beats** first.

**Written for** sets the transposition of the part:

- **C — concert**
- **E♭ — alto, baritone**
- **B♭ — trumpet, soprano**
- **B♭ tenor — written +9th**

Nothing in the audio says which horn is playing, so this has to come from
you. The key signature moves with it.

**Key** sets the key signature, at concert pitch. **Auto** reads it from the
notes over the whole span, and after an export it names what it found, for
example **Auto — D major / B minor**. A tune that moves between keys has no
single right answer, so choose the signature you want instead. Each is
listed as a major key and its relative minor, which share one signature, for
example **F major / D minor**. The notes are spelled to suit it (B♭ rather
than A♯), a two-staff page uses it on both staves, and **Written for** still
transposes it for a horn.

**Rhythm** sets how the timing is written:

- **Swing — eighths** is the default. The swing is read out of the playing:
  a swung pair is written as two even eighths, with "Swing" above the staff,
  the way a jazz chart is written.
- **Literal 16ths** writes every note on the nearest sixteenth, exactly as
  played, with no "Swing" marking. A swung pair usually comes out as a
  dotted eighth and a sixteenth. A beat whose notes are too close together
  for sixteenths is written in thirty-seconds.
- **Literal 32nds** writes every note on the nearest thirty-second.

Literal pages have no triplets, and a literal export gets `.literal16` or
`.literal32` in its file name, so it never overwrites the swing page. An
All-notes export gets `.all`, and a two-staff one `.2staves`.

Bars are numbered from 1 within your span, the way a solo transcription is
usually numbered, not from the start of the track. Notes before the first
full bar become a pickup. Silenced notes are left out, and candidates you
switched on are written in.

If you keep editing after an export, the export bar says the file on disk
is older than what you see.

### Seeing the page before you export

Below the export bar, **Page** shows the score Export would write, drawn in
the app: the same notes, bars, key, rhythm, transposition and staves. It is
redrawn a moment after anything that changes it, such as an edit on the
roll, the **Rhythm**, **Key** or **Written for** menus, the staves, the
downbeat or the time signature. Looking at it writes nothing; only Export
writes the file. It needs what Export needs, a transcription and a beat
grid, and says so while either is missing.

- **Scroll** to zoom, **shift-scroll** or **drag** to pan, as on the other
  views. **+** and **−** zoom in steps, and **Fit** goes back to the page's
  own width.
- **Paper** switches between light notes on the dark background and black
  on white, the way the page will print.
- The **Page** chip in the export bar, or <kbd>P</kbd>, hides the page and
  shows it again. This browser remembers the choice.

The page is laid out for the width of the panel, so a line holds more bars
than a printed page does. MuseScore lays out the exported file its own way,
but the notes, bars and key signature are the same.

## Keyboard shortcuts

Shortcuts need a track open. They are ignored while the focus is in a text
field, a menu or a slider.

- <kbd>Space</kbd>: play or pause the active section.
- <kbd>Enter</kbd>: play from the start of the active section.
- <kbd>A</kbd> / <kbd>B</kbd>: set edge A or B at the playhead.
- <kbd>[</kbd> / <kbd>]</kbd>: nudge the focused edge by −0.1 s or
  +0.1 s. Add <kbd>Shift</kbd> for 0.01 s.
- <kbd>←</kbd> / <kbd>→</kbd>: seek the original recording by −2 s or
  +2 s. Add <kbd>Shift</kbd> for 0.1 s.
- <kbd>,</kbd> / <kbd>.</kbd>: playback speed −5% or +5% in the active
  section. Add <kbd>Shift</kbd> for 1%.
- <kbd>L</kbd>: turn Loop A/B on or off.
- <kbd>S</kbd>: cycle snap through off, bar and beat.
- <kbd>D</kbd>: set the downbeat at the nearest beat (needs the beat grid).
- <kbd>F</kbd>: set the form start at the nearest bar line (needs the beat
  grid).
- <kbd>C</kbd>: turn the click track on or off.
- <kbd>E</kbd>: switch between the Inspect and Edit tools.
- <kbd>H</kbd>: switch to the Hands tool and back (two-staff page only).
- <kbd>↑</kbd> / <kbd>↓</kbd>: with the Hands tool, put the selected notes
  in the right or left hand.
- <kbd>Esc</kbd>: with the Hands tool, clear the selection.
- <kbd>V</kbd>: show or hide the piano model's candidates.
- <kbd>X</kbd>: export MusicXML.
- <kbd>P</kbd>: show or hide the page.
- <kbd>Ctrl+Z</kbd>: undo an edit.
- <kbd>Ctrl+Shift+Z</kbd> or <kbd>Ctrl+Y</kbd>: redo.

## The command line

Everything the app does is also a command. Run the commands from a source
checkout as `uv run python -m swingscribe <command>`, or as
`.\swingscribe <command>` on Windows. Every stage is cached, so a command
re-run with the same inputs finishes at once, and the app and the commands
share one cache.

- `run <file>` runs the whole pipeline: separate, track beats, transcribe,
  notate, and write MusicXML to the cache's `exports` folder.
- `audition <file>` writes just the isolated stem over a span. Use it to
  hear whether the soloist separates cleanly before you spend minutes on
  analysis.
- `ab <file>` is the ear test. It writes a stereo wav with the original on
  the left and the transcription, rendered as tones, on the right. It also
  writes the transcription as MIDI, and `--midi` sets where. The app's
  command box shows the exact `ab` command for your span and stem.
- `click <file>` writes the music with a click on every detected beat, so
  you can check the grid by ear.
- `cache ls` lists what the cache holds per track. `cache rm` deletes it,
  just like the Cache panel.
- `gui [file]` starts the app.

The common options are:

- `--start` and `--end` limit a command to one solo, in seconds (`run`,
  `audition` and `ab`).
- `--stem` names the stem that carries the soloist.
- `--time-signature`, `--downbeat` and `--bars-per-chorus` set up the bar
  grid.
- `--tempo-hint <bpm>` helps when the beat tracker picks half or double the
  tempo (`run`, `ab` and `click`).
- `-o` sets the output file.
- `--config <file>` uses a different configuration file.

Settings without a flag, such as the separation model, the ensemble and the
transposition, live in the configuration file. `swingscribe --version`
prints the version. Audio can be wav or flac, plus anything ffmpeg decodes
(mp3, m4a, aac, ogg, opus, wma, aiff and more).

Separation and transcription need the AI dependency groups (`uv sync
--group ml --group gui --group roformer`), and they download about half a
gigabyte of models on first use. Without a CUDA GPU they run on the CPU.
Expect minutes, not seconds, for a whole track, which is why the app
separates only the span you selected.

## The AI models and their licences

SwingScribe is MIT licensed. The models it runs belong to their authors,
and each one downloads on first use under its own terms.

- **BS-RoFormer** ([paper](https://arxiv.org/abs/2309.02612)) is the
  default separator. The weights SwingScribe uses, BS-Roformer-SW, have
  **no licence and no known author**. The person who re-hosted them says
  they did not train them and know nothing of their origin, and every copy
  since declares the licence unknown. SwingScribe does not ship them. Your
  machine downloads them the first time you separate with this model, from
  the model repository of the Ultimate Vocal Remover (UVR) community, the
  same way every UVR user gets them. For anything you sell, choose Demucs
  in the separator menu.
- **Hybrid Transformer Demucs** ([paper](https://arxiv.org/abs/2211.08553))
  and its variants, for separation, are MIT licensed.
- **Beat This!** ([paper](https://arxiv.org/abs/2407.21658)), for beat
  tracking, is MIT licensed.
- **CREPE** ([paper](https://arxiv.org/abs/1802.06182)), for pitch
  tracking, is MIT licensed.
- The **high-resolution piano transcription** model by Kong et al.
  ([paper](https://arxiv.org/abs/2010.01815)), used for pianists, is CC BY
  4.0.
- **Verovio** ([verovio.org](https://www.verovio.org)) is not a model but
  the music engraving library that draws the page view. It is LGPL-3.0,
  and SwingScribe uses it unmodified. Its music fonts are under the SIL
  Open Font License.

`NOTICES.md` lists every model and library. It sits beside the launcher in
the Windows app, and under `packaging/` in the repository.

## Troubleshooting

**A chunk of the solo is missing.** A separation model assigns each moment
to exactly one stem. So a soloist it cannot place consistently is not
turned down: it is switched to another stem, leaving digital silence in the
one you are listening to. Try a summed lead stem such as `other+vocals`,
or try another separation model.

**The bars do not line up with what you hear.** Turn on **Click** in
section 2 and listen against the metronome. A wrong downbeat is obvious
against the click. Click the right beat dot, or press <kbd>D</kbd> on it, to
fix it. If the grid itself runs at half or double the right speed, pass
`--tempo-hint` on the command line.

**A piano solo is not getting the piano model.** Check **Ensemble**. Unless
it is set to **Trio (piano)** or **Solo piano**, the piano model is never
consulted. On a track with no ensemble yet, separate the span with
BS-RoFormer and read the suggestion under the menus (see "Who is playing").
If it says there is no suggestion, its reason says why: a selection under
15 seconds of melody, a Demucs separation, or a horn in the selection.

**A separation is stuck, or you picked the wrong model.** Click **Cancel**,
pick a different model or span, and separate again.

**The browser tab is closed but the server is still running.** Closing the
tab does not stop it. Open `http://127.0.0.1:8420/` again and click
**Quit**, or close the console window.

**Copying text from the console window.** Clicking in the window does not
select text. On Windows a selection there pauses the app until it ends, so
SwingScribe switches that off. To copy an error message, right-click in the
window, choose **Mark**, select the text, and press <kbd>Enter</kbd>. The
app waits while you do.

**Windows refuses to run `swingscribe.exe`.** If `uv run swingscribe ...`
fails with `An Application Control policy has blocked this file (os error
4551)`, Smart App Control is refusing the small `.exe` stub that the
installer generates, not SwingScribe itself. Run
`uv run python -m swingscribe ...` or the `.\swingscribe` shim instead.
A first launch can also fail once while Windows checks the file's
reputation, and then pass on a retry.

**A separation fails with "the separation process crashed".** With the
default model a separation needs about 4.5 GB of free memory, and the app
itself holds about 2 GB once it has transcribed something. Close other
programs and try again, or choose **htdemucs**, a much smaller model.

**A download fails with `CERTIFICATE_VERIFY_FAILED`.** Your network
inspects encrypted traffic and signs it with its own certificate, as many
workplaces and some antivirus products do. Windows trusts that certificate,
but the downloader for the default separation model does not. Make a
certificate bundle and point SwingScribe at it:

1. Get the network's root certificate as a Base-64 `.cer` file, from your
   IT department or by exporting the top of the certificate chain your
   browser shows for https://github.com.
2. Copy `python\Lib\site-packages\certifi\cacert.pem` out of the
   SwingScribe folder to a folder of its own, open the copy in Notepad,
   paste the whole text of the `.cer` file at the end, and save. From
   source, copy the same file out of `.venv\Lib\site-packages\certifi\`.
3. In **Start > Edit environment variables for your account**, set both
   `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to the copy. From source, uv
   also needs `UV_SYSTEM_CERTS=true`.
4. Quit SwingScribe and start it again.

The installation guide has the same steps with more detail.

## Terms used in this guide

- **Span:** the stretch of the track you selected, usually one solo.
- **Stem:** one instrument group separated out of the mix, such as drums,
  bass, piano or *other*. A horn usually lands in *other*.
- **Downbeat:** the first beat of a bar. SwingScribe counts bar lines from
  it.
- **Form start:** the bar that becomes bar 1, so an intro is not counted.
- **Chorus:** one time through the tune's form, often 12 or 32 bars.
- **f0:** the fundamental frequency, which is the pitch you hear.
- **Periodicity:** how regular, and so how clearly pitched, the sound is at
  a moment. Noise and drums score low, and a held note scores high.
- **F1:** the standard accuracy score for transcription. It balances notes
  found against notes invented, and 1.0 is perfect.
- **MusicXML:** the standard file format for sheet music. MuseScore,
  Finale, Sibelius and Dorico all open it.
- **Swing:** playing pairs of eighth notes long-short. Jazz writes them as
  plain eighths under a *Swing* marking, and SwingScribe does the same.
