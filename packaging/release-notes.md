## What's new in 0.4.0

**See the page as you work.** Below the export bar, **Page** shows the score that Export would write, drawn in the app and redrawn as you edit. **Paper** shows it black on white, the way it will print, and <kbd>P</kbd> hides it.

**Chord symbols.** Click **Changes** and type one chorus of the tune's changes, the way a chart is written. SwingScribe writes them over every chorus of the page and transposes them with the part. It never guesses: a chord it cannot read is shown in red and left off the page.

**Find the solos.** On a record with several solos, one button proposes where each starts and ends. Click a band to select that solo.

**Who is playing, suggested.** After a BS-RoFormer separation, SwingScribe suggests the ensemble and the lead stem from how loud each stem is. Nothing changes until you click **Apply**.

**Fixing the bar lines:**

- **Pin a beat** where the beat tracker gained or lost one part-way through a solo: Alt-click the Detail waveform where the beat really is, or press <kbd>T</kbd> at the playhead. The bars on both sides of the slip come out right.
- Where two beat ticks crowd together, SwingScribe now counts the beats around them like a metronome and takes the extra one out itself. Where it cannot tell, it marks the spot with a **?** so you know where to listen.
- **Steady tempo** (<kbd>Y</kbd>): drag across a stretch where the ticks went wrong while the band kept time, and its beats are laid out on one steady tempo.
- **Fast tune** tracks the beat again at half speed, for a tune of about 250 bpm and up that the tracker heard once a bar, so the page came out as 32nd notes.

**Two horns playing a head.** A new ensemble, **Two horns (a head)**, transcribes a tune's melody played by two horns in harmony. It writes them as two voices on one staff, or as two parts, and a **Voices** tool moves notes between them.

**Takes.** A recording can now have several settings files, such as one for the head and one for each solo. **New take…** and **Rename take…** are in the header. Takes of one recording share its separated stems, so nothing is separated twice.

**Better notes:**

- Basic Pitch, a small note model that ships inside SwingScribe, now fills the holes in a horn's line, so more quick notes and ornaments are caught.
- Old recordings that run sharp or flat are transcribed against their own tuning, so their notes no longer come out a semitone off in places.
- On a Swing page, a scoop up into a note is written as a grace note, and a note re-attacked with a short "head" is written as one note.
- The exported file is beamed, so a program that does not beam a file itself shows beamed eighths and sixteenths, not a flag on every note.
- C♭, F♭, E♯ and B♯ are written only in keys that come near them, so a B natural in A♭ is no longer spelled C♭.
- Bar numbers on the piano roll now match the page after a stretch with no steady beat.
- Holding <kbd>Shift</kbd> with <kbd>[</kbd> <kbd>]</kbd> <kbd>,</kbd> <kbd>.</kbd> now gives the finer nudges and 1% speed steps the guide describes.

The user guide, behind the **Help** button, covers all of it.

## Installing

**Windows:** download the zip below, extract it somewhere with a short path such as `C:\SwingScribe`, and double-click `setup.cmd` once. It needs Windows 10 or 11 (64-bit) and 8 GB of RAM, 16 GB recommended. The [installation guide](https://github.com/elkayem/swingscribe/blob/master/INSTALL.md) has the details.

## Updating from an earlier version

Install the new version beside the old one, never over it.

1. Quit SwingScribe with its **Quit** button.
2. Rename the old folder, for example to `SwingScribe-old`. The zip always extracts a folder named `SwingScribe`.
3. Extract the new version and run its `setup.cmd`. The icons and the Settings > Apps entry now point at it.
4. Start SwingScribe from the icon and check that it opens.
5. Delete the old folder by hand. Do not run its `uninstall.cmd`, which would remove the new version's icons.

Your downloaded models, cache and per-track settings are shared between versions, so nothing downloads again.
