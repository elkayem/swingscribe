# pdf2musicxml: PDF transcriptions to MusicXML ground truth

`src/pdf2musicxml/` is a standalone tool (it imports nothing from
swingscribe) that turns the jazz transcription PDFs found on the web into
one MusicXML file per transcription, for MuseScore and for the benchmark.
It was built on 2026-09-24 against the four PDFs in
`benchmark/Transcriptions_Other/`: two Sibelius exports (Minority, Whisper
Not), one Finale export (Big Chief de Sota) and a scanned ten-solo ebook in
a handwritten jazz font.

## Use

    .\pdf2musicxml setup                                  # once: fetch Audiveris
    .\pdf2musicxml convert benchmark\Transcriptions_Other  # every PDF in the folder
    .\pdf2musicxml summary benchmark\Transcriptions_Other  # one table, worst first
    .\pdf2musicxml render benchmark\Transcriptions_Other   # MuseScore opens every file
    .\pdf2musicxml doctor                                 # what is installed

`render` has MuseScore's command line convert every primary output to a
PDF under `musicxml/.render/` and lists any file it refuses: the one test
of "readable by MuseScore" that is not an opinion, and a proof sheet to
lay beside the original page.

`summary` reads every manifest in the folder's `musicxml/` and writes
`SUMMARY.md`: one row per transcription ordered by the least trustworthy
first (lowest notes-read-per-notehead-printed, then lowest engine
agreement, then most bars off), which is the order to proofread in. A
`pdf2musicxml.instruments.json` beside the PDFs maps file-name patterns
to the instrument a part is written for, for a site that files its
transcriptions by instrument and prints none on the page (the
peterandwillanderson.com set); a byte-identical copy of a PDF already in
the folder is skipped.

Outputs land in `<folder>/musicxml/`: `<pdf>.musicxml` for a single
transcription, `<pdf> - 01 <title>.musicxml` and so on for a book, and a
manifest `<pdf>.pdf2musicxml.json` with the page grouping, the title and
instrument found, the counts, and the bars to proofread. Engine output,
page images, logs and the second engine's reading
(`.work/<pdf>/tNN/<name>.audiveris.musicxml`) stay in `musicxml/.work/`,
so the folder itself holds one file per transcription; the Audiveris
`.omr` there opens in the Audiveris GUI for corrections.

**The plain `.musicxml` is the file to use.** Both readings get the same
mending and the same printed-pitch correction, so they differ only in what
the engine read; measured over the 221 vector PDFs with both readings,
homr's primary file is nearer the printed note count on 140 (Audiveris on
9, 72 level), its median read-per-printed is 98.5% against 96.9%, and it
leaves half as many bars not filling the signature (12.5% against 24.8%).
It also keeps more ties (3,632 against 3,060) and more tuplet notes. The
Audiveris reading is the cross-check that names the bars to proofread,
not a second candidate, which is why it lives under `.work/` and not
beside the file (it did until 2026-09-24, and the listener, using the
folder for another project, asked for the two not to sit together).

The report printed at the end is a proofreader's list, per transcription:

- **noteheads printed against notes read**, for a PDF with a text layer:
  a notehead is a music-font glyph about a staff space tall and a little
  wider than tall, whatever its code (`vector.is_notehead_box`; Finale
  puts its half head at U+02D9, Sibelius its quarter rest at U+0152, so
  code lists mislead), and an accent of the same shape stacked on a note
  is dropped. The count is the page's own: Big Chief de Sota prints 115
  and homr read 115. A page far from 100% lost or invented notes. A scan
  has no text layer and no count;
- **bars whose notes do not fill the bar** (the first and last may be
  short: a pickup, an ending);
- **bars the other engine reads differently**, aligned by content so a
  dropped bar does not shift the rest;
- the time signature used and why (`fix_time_signature`), ties recovered
  from slurs, extra parts dropped.

Options that matter: `--engine audiveris` swaps the primary reading;
`--no-check` skips the second engine; `--split "4-5,6-8"` or `--single`
overrides the page grouping (or edit the manifest's `pages` and re-run;
`--redetect` ignores the manifest); `--instrument "Bb Trumpet"` when the
page does not name it; `--time 4/4` forces the signature; `--concert`
shifts the pitches to concert pitch instead of writing `<transpose>`;
`--font jazz` picks Audiveris' Finale Jazz symbol family for a scan
(vector PDFs are detected from their fonts).

A re-run reuses the engines' raw readings under `.work/` (homr takes 25-40
seconds a page on the CPU, Audiveris about 9), so correcting a title, an
instrument or a page grouping in the manifest and running again takes
seconds; `--force` reads everything afresh.

Dependencies: `uv sync --group ml --group gui --group batch --group roformer
--group omr` (pypdfium2, Pillow, numpy, homr). Audiveris is not a Python
package: `setup` downloads its 5.11.0 Windows MSI (85 MB, sha256 pinned in
`engines/audiveris.py`) and Tesseract's English data into
`%USERPROFILE%\.pdf2musicxml\`, unpacked with `msiexec /a` -- no
installation, no admin rights, nothing in AppData (a shell run from the
Claude desktop app has its AppData redirected; see CLAUDE.md).

## What the engines read, measured

Three OMR engines were considered. oemer (BreezeWhite) has no tuplets and
says it does not work on handwritten fonts, which rules it out for jazz.
The two kept were run on the same pages and the readings rendered through
MuseScore beside the PDF:

| page | Audiveris 5.11 | homr 0.7 |
|---|---|---|
| Big Chief de Sota (Finale, Maestro font, 1 page) | ties right (2), triplets right, 10 chord symbols read, grace notes dropped; 8 s | triplets right, grace notes kept, one natural read as a flat, ties as slurs; 42 s |
| Minority p1 (Sibelius, Opus font) | ties and triplets right, chord symbols partly (Inkpen chords read as "sf"), ghost-note bar wrong | most bars right, ghost-note bar and one 16th group wrong; 27 s |
| Blueberry Hill (ebook scan, Finale Jazz font) | opening rest lost, 1 of 5 triplets, 0 of 6 ties, a tuplet "3" read as a 3/4 change; Finale Jazz family read 67 bars against Bravura's 63 (the page has 68) | rests, 4 of 5 triplets, all 6 ties (as slurs); 4/4 read as 6/8; 26 s |

So: **homr is the primary reading** (it degrades gracefully on scans and
handwritten fonts, needs no Java, and its two systematic faults -- ties as
slurs, a misread time signature -- are mended in `musicxml.py`), and
**Audiveris is the cross-check** and the better reading of a clean
notation-program PDF (ties, chord symbols, the title as OCR'd text). The
engines disagree on different bars, which is what makes the disagreement
list worth reading.

Two Audiveris rules learnt the hard way, both handled in `convert.py`:

- it refuses to export a book in which any sheet failed, and a page with no
  staves fails ("No regularly spaced lines found") -- so the ebook's cover,
  contents and how-to pages never reach it;
- it renders a PDF page at 300 dpi and refuses anything over 20 megapixels
  -- the ebook embeds its 150 dpi scans on a 15-inch page -- so every page
  is rasterised by the tool (`pdfpages.render_page`, long side 3300 px)
  and handed back as a PDF written by hand (`write_gray_pdf`, Flate, 1:1).

## Pitches read off the page itself

A notation-program PDF does not need an engine for its pitches. Its staff
lines are thin vector paths (five equally spaced ones per staff), every
notehead, accidental and clef is a positioned glyph of a music font, and
a notehead's height above the bottom line IS its staff step. `vector.py`
reads them: staves from the paths, bar lines from the vertical paths
spanning a staff, a key signature as the longest valid circle-of-fifths
prefix of the accidentals before a staff's first note, and each note's
accidental as the glyph on its step just to its left (a flat's bowl sits
30% up its tall glyph; sharps and naturals are centred). An accidental
holds to the bar line, the key elsewhere, a tied-into note keeps its
pitch. The result is aligned with the engine's notes on diatonic position
(difflib), so an engine's accidental slip still aligns and is corrected,
while a dropped or invented note is counted, not guessed at.

Measured on the three first PDFs: Audiveris's Big Chief reading needed 0
corrections (the page and the engine agree exactly, which is the check on
the reader itself); homr's needed 8 of 115, all its flat-for-natural
slips. On Minority both engines had about 35 accidental errors in 972
notes, all corrected; 20 printed heads had no read note and 20 read notes
no printed head, and those are reported. Durations, rests, ties and
tuplets stay the engine's. `--no-printed-pitch` turns it off.

## Splitting a book into transcriptions

Nothing in a PDF says where one transcription ends. Two signs are read
(`layout.py`):

- **a title in the text layer** (notation-program PDFs): the largest wordy
  line in the top third of the page, at least 1.4x the median size of the
  page's other text; a running header with "PG. 2"/"page 2" marks a
  continuation page whatever else it says. Music-font lines (Opus, Maestro,
  Inkpen2, Bravura, ...) are never titles, however large;
- **the first staff's position** (scans): a title pushes the first staff
  down the page. On the ebook the title pages' first staff sits at 14% of
  the page height, continuation pages' at 8.5%; a page 4% lower than the
  highest in the file starts a transcription. With no spread at all, 12%
  decides between "each page is one" and "the file is one".

Pages without staves are dropped. The guess is written to the manifest;
correct it there and re-run.

## Instrument and pitch

Transcriptions are published in the soloist's written key. The instrument
is read off the page's own text ("Alto Saxophone (Eb)", "Clarinet in Bb",
"TRUMPET") or Audiveris' OCR'd credits, never guessed from the notes
(`instruments.py`). By default the pitches stay as printed and a
`<transpose>` says how they sound, which MuseScore honours on its Concert
Pitch toggle; `--concert` shifts every pitch, chord root and key signature
instead. Either way the benchmark's aligner settles the transposition over
the whole line (`alignment.measured_transposition`), so the file is usable
as ground truth as soon as it is proofread.

## The corpus, 2026-09-24

267 PDFs in `benchmark/Transcriptions_Other/`: the listener's 53 (Wesley
Chin's Sibelius exports), 50 from maxgrynchuk.com (Sibelius, Inkpen2), 161
from peterandwillanderson.com (Finale, Maestro; 36 of them scans), and
three others. A ten-solo scanned ebook was in the set while the tool was
built (its rows are kept in the table below as the one measurement of a
scan) and the listener removed it on 2026-09-24 as not worth proofreading.
One full pass took about five hours on the CPU (homr 25-40 s a page,
Audiveris 9 s); a re-run with readings cached takes eight minutes. Result:
275 transcriptions, 20,271 bars, 126,027 notes, none failed; MuseScore's
command line opens 274 of them (`render`). The one it refuses is a two-staff piano transcription
(Mahesh Balasooriya's There Will Never Be Another You), a five-voice
texture with tuplet-length quarters and no ratio, outside what a
single-line tool mends; it is listed as such.


The pitch and bar columns predate the second round (the stem fix above took
about 1,500 wrong pitch corrections out, and the page's tuplets took 554 bars
off the last column); the SUMMARY.md beside the outputs is current.

| source | files | notes | read per printed (median) | engine agreement (median) | pitches set from the page | bars not filling the signature |
|---|---|---|---|---|---|---|
| Wesley Chin (Sibelius) | 53 | 35,759 | 97.4% | 75% | 3.8% | 8.2% |
| maxgrynchuk.com (Sibelius) | 50 | 24,954 | 98.0% | 51% | 3.0% | 20.7% |
| peterandwillanderson.com (Finale) | 161 | 65,299 | 99.7% | 81% | 2.8% | 11.4% |
| ten-solo ebook (scan, since removed) | 10 | 3,181 | no text layer | 12-52% | none | 3-37 bars each |

Read the columns in that order. Read-per-printed near 100% says the
notes are all there (the shortfall is the 1-3% of noteheads no read note
aligned with, listed per file). The pitches are then the page's own, so
what the engines still disagree on is rhythm: high on the bebop and swing
pages, low on the maxgrynchuk lead-trumpet charts (Ferguson, Bergeron,
Sandoval: dense sixteenths, cut time, big-band ranges) and lowest on the
scanned ebook, which is where a proofreader's time goes. `SUMMARY.md`
orders every file that way.

## What else the page prints: tuplet numbers, the time signature, the tempo

The listener's second round of spot checks (2026-09-24) found three
things the engines leave out that the page states in glyphs: bar 19 of
Arriving Soon had nine plain eighths where the page brackets its first
three under a "3"; Whisper Not carried a 2/2 where the page prints 4/4;
and no file had its tempo. The same text layer that gives the pitches
gives all three, and `vector.read_page` reads them:

- **Tuplet numbers** are lone digits about a space and a half tall in
  the family's Text face (Sibelius) or Times Bold Italic (Finale), in the
  staff's band and among its notes -- a chord symbol's "7" or "13" has a
  neighbour on its baseline, a bar number sits before the first note. The
  corpus prints 4,054 of them; the engines had written 2,438 tuplet
  groups. `apply_printed_tuplets` reuses the pitch alignment: a "3"
  claims the three consecutive onsets it is centred on -- noteheads and
  RESTS alike, since a rest is a music glyph too (U+2030 an eighth rest,
  U+0152 a quarter, U+2248 a sixteenth, U+00D3 a half, U+2211 a whole,
  the same codes in Opus, Inkpen2 and Maestro), each paired with the
  reading's rest between the same two aligned notes -- with no bar line
  between them, and their read notes, consecutive in one bar, become one
  value in a 3:2 (5:4, 6:4, 7:4 for other digits), with the divisions
  refined when the ratio needs it. Which onsets the number holds is the
  BRACKET's to say when one is drawn (a thin path at the number's
  height, broken at the number or running under it): Whisper Not's bar
  20 brackets four notes under a "3", two quarters and two beamed
  eighths, a quarter-note triplet with its last quarter split. Each
  member's written value is then the page's: a rest's from its glyph, a
  note's from the BEAMS over its stem (a path a stem's length away, not
  running more than four spaces past the group, not at the number's
  height: one beam eighths, two sixteenths), else from its FLAG glyphs
  ("j"/"J" one flag, "k"/"K" two), else a quarter; and when those values
  sum to `count` of one unit the group is that tuplet, values and all,
  written with its `<normal-type>` (3:2 of quarters over quarter,
  quarter, eighth, eighth). Only the nearest bracket segment on each
  side of the number belongs to it: three brackets in a row put the
  neighbour's segment a few spaces off, and a bracket taken too wide
  once claimed five sixteenths under a 3:2, which MuseScore refused
  (seven files, caught by `render`); a bracket holding other than its
  number of onsets with no page value for them is left alone. Where the page gives no beam or flag for any
  member the reading's values stand, and the older rule applies: the
  value is the one `normal` of which make the group's read total (an
  engine that split a triplet eighth into two sixteenths kept the
  sounding total), else `count` of which make it (plain notes), else the
  majority of the read values, with the beams over the whole group
  outranking all three where they are found. Over the corpus: 1,371 groups
  made tuplets from the page, 1,021 of them valued member by member (49
  with mixed values, 39 of those quarter-note triplets), 141 with a rest
  inside; 208 numbers left explained. What is not applied is explained
  per bar in the manifest's `tuplet_notes`: a notehead or rest the engine
  dropped, a grace note in the group, a bar of several voices (shortening
  one voice's notes sends a later `<backup>` past the bar's start and
  MuseScore refuses the file: Maynard & Waynard bar 97, found by
  `render`), or no single value that fits. The engines' tuplet groups
  under no printed number are counted, not stripped. Result over the 222
  vector files: 1,394 groups made tuplets from the page, 151 of them with
  a rest inside, 323 with their value set by the beams against the
  reading's (322 of those longer: homr over-counts beams on fast
  triplets); 169 numbers left explained, 95 of them a notehead the
  engine dropped and 33 in a bar of several voices; bars not filling the
  signature down from 1,872 to 1,318 before the merge below, 912 after.
- **Bars** are the page's too. Every aligned note knows which printed bar
  it sits in (bar lines passed on its staff), so two read measures whose
  notes all sit in one printed bar are joined -- homr took Whisper Not's
  double bar line before bar 10 for two bar lines and a repeat, and split
  bar 9 around it -- and one read measure whose notes sit in two printed
  bars is divided where the second begins. A join needs the two to make
  under a bar and a half together (two real bars behind a bar line the
  finder missed would make two), a division a measure a bar and a half
  long or more; bars of several voices are left alone, and a bar line or
  repeat inside a joined bar was the engine's and goes. `bar_notes` in
  the manifest names each; the corpus needed 4 joins and 1 division on 5
  files.
- **The time signature** is two music-font digits about two spaces tall
  stacked at the staff's start (numerator on the upper half, denominator
  on the lower; several digits side by side make 10/8 and 12/8), or a
  common/cut-time glyph on the middle line. It outranks what the bars
  fill, because 2/2 and 4/4 fill the same bars; `--time` outranks both.
  185 of the 222 files print one; 25 changed, 22 of them a 2/2 the engine
  had read under a printed 4/4, and Minuano to 6/8, Mission: Impossible
  to 10/8, The First Circle to 12/8. One pdfium trap here: its text layer
  drops the second of two identical characters whose boxes touch, so a
  4/4 arrives as a lone "4" while 3/4 and 6/8 arrive whole; the page's
  text OBJECTS still hold both, and a lone numerator with a text object
  right under it is read as N/N.
- **The tempo** is a beat glyph in a notation family's Text face ("h" in
  Opus Text is a half note, "q" a quarter; Engraver Text for Finale), an
  "=", and a number on the same line, with an augmentation dot after the
  beat for a dotted unit and the words before it ("Fast Swing", "Medium")
  in the text or Script face. It is written into bar 1 as a metronome
  direction with `<sound tempo>` in quarters per minute, so MuseScore
  shows "half = 128" and plays 256. 123 of the 222 files carry one (79
  in quarters, 44 in halves); the rest print no metronome mark.

## Two readings, bar by bar

53 of the corpus's 275 transcriptions are scans (36 of the
peterandwillanderson.com files, the two Wesley Chin scans and a few
others): no text layer, so none of the page readers above apply and the
file was homr's reading alone. The listener's Don Byas Star Dust check
showed what that costs: five triplets in bars 2 and 3, and homr read
none, while the Audiveris cross-check of the same page read them as
printed (quarter and eighth under a 3, rest and eighth, the beamed
three). The single-page ebook measurement that made homr the primary on
scans was a handwritten font; on these Finale scans neither engine
wins outright (by bars filling the signature homr on 37 files, Audiveris
on 13, but where Audiveris wins it is often by every bar).

So the two readings are merged bar for bar (`musicxml.merge_readings`),
the way a proofreader with both would work: where the bar counts agree,
each bar goes to the reading that holds the page's note count for it
(vector files, from the printed noteheads per printed bar) and, failing
that, the one nearer to filling its time signature -- a reading a third
of a beat short beats one a beat long. Ties stay with homr; readings
whose bar counts differ are left alone, since nothing pairs their bars.
Both are brought to one `divisions` first. A taken bar brings its notes
and chord symbols only: Audiveris's OCR'd text directions ("m9;" in
bold over Whisper Not's bar 8), page breaks and bar lines stay behind,
the primary's clef, key, time and tempo mark stay on the bar, and every
`<beam>` element in the file is removed afterwards -- MuseScore beams a
file by hand as soon as it holds any beam element, so the homr bars
(which carry none) came out as single flagged sixteenths until they
were all gone. The page's note count per bar follows the notes' printed
bars, not the bar index, so a bar the reading joined or split does not
shift every count after it (that slip let a Whisper Not bar that
dropped two notes replace one with the page's triplets). The engine agreement in the report is
measured before the merge, or it would measure the merge. Star Dust
took 9 of 34 bars from Audiveris and its bars 2 and 3 now carry their
triplets. Over the corpus: 474 bars taken from the Audiveris reading on
92 files (56 of them on scans), and bars not filling the signature down
from 1,318 to 942 on the 222 vector files and from 635 to 590 on the 53
scans (912 before the bracket rule above; its stricter page values cost
30 bars while fixing the split-triplet class). The largest single gain of the day, and the one with a caveat: a
bar nearer its signature is not thereby right, so a taken bar still
proofreads like any other; `bars_from_check_list` in the manifest names
them.

Reading the tuplets exposed a bug in the pitch reader that had been
there all along: `find_barlines` took every thin vertical path spanning
the staff for a bar line, stems included (116 on Whisper Not's 33-bar
page), so the pitch reader reset its accidentals at every stem and
"corrected" pitches wrongly -- 10 changes on that page, 1 once fixed; 22
to 9 on Arriving Soon. Measured on Opus, Inkpen2 and Maestro pages, a bar
line overshoots BOTH outer lines by the same 0.05-0.7 of a space (0.15 in
Finale, 0.34 in Sibelius) while a stem ends on a notehead at one end, and
Sibelius draws bar lines wider than stems (Finale does not, so width is
only a floor). The corpus's pitch corrections fell from about 3,900 to
2,431 (1.9% of notes), the difference being the wrong ones, and the
engines' bar agreement rose from a median of 72% to 76%. The finder now
reads about one bar line per bar on 187 of the 222 files; an older
Finale export can still hide some (Benny Goodman's Body and Soul gives 2
of 4 a staff), so `correct_pitches` also ends an accidental's hold where
the reading's measure ends, and the manifest's `barlines_printed` beside
`measures` says which files needed that (10 files, 22 alters).

Three things the corpus taught that a single PDF did not. MuseScore
refuses a whole file, with exit code 40 and no message, for two engine
slips: a tuplet whose written values do not add up to its ratio ("3:2
over eighth, eighth, quarter", or four bare "triplet quarters" in a row)
and a `<chord/>` tone hanging on a rest or a `<backup>`; `repair_tuplets`
and `repair_chords` strip the bracket or the chord mark, keep the
durations, and leave the bar for `validate` to flag -- 48 of 285 files
were refused before them. Noteheads must be
told by glyph SHAPE: a Finale PDF puts its half head at U+02D9 and
Sibelius its quarter rest at U+0152, so the first code list undercounted
Finale pages and overcounted Sibelius ones, and an accent stacked on a
note has a notehead's shape too. And a multi-page solo is split by its
running header unless the header is recognised: "2 Strode Rode", "The
Bird 3", the title repeated without a number, a watermark across the
staves taken for a title -- 86 fragment files were superseded once those
rules were in.

## Where the off bars were, and three more things the page prints (2026-09-25)

The listener asked whether the 942 bars off the signature were spread or
concentrated, and by source. Counted by file from the manifests, the
source told by the filename's shape and confirmed by the music font on
each page: the 53 scans, a fifth of the files, held 590 of the corpus's
1,532 (22 per 100 bars); among the vector files the Anderson Finale set
read 3.0 off bars per 100 with 57 of its 88 Maestro files clean, the
listener's own Sibelius exports 5.1, and the Grynchuk Sibelius set 11.5
with 1 of 47 clean. Ten files held a third of all off bars, 84 files had
none. The worst vector files were not reading trouble at all: Artie
Shaw's Interlude in Bb had 40 of its 50 in two 2/4 sections the tool
read as 4/4 (one signature per file), and No Room For Squares' 14 were
bars a multi-bar rest had left empty. The scans' worst two (Alone
Together, 135 of 141; Hawkins's Body and Soul, 66 of 69) carried a 3/4
homr read off the handwritten "C", kept because the bars were too
irregular for the 60% rule -- 81 of 141 fill four quarters against 5
filling three, which is not a tie. Their halved values (an eighth
triplet read as sixteenths, sixteenths as 32nds) are both engines'
reading of that heavy handwritten font, not anything the tool does to
fit a signature; nothing rescales a value.

Five rules followed, four of them from the page:

- **A change of signature mid-piece** (`vector.apply_printed_times`).
  Every printed signature knows the bar it begins (bar lines passed on
  its staff, the same count a notehead carries), and the read measure
  whose first aligned note sits in that bar declares it; a signature the
  reading holds that no printed one backs goes. Artie Shaw: 4/4 to 2/4 at
  letter C and back, five changes; The First Circle: 12/8 and 8/8 turning
  about, ten. An 8/8 the page prints stays 8/8.
- **A multi-bar rest** (`vector.multi_rests`, `expand_multirests`).
  Sibelius and Finale both draw it as one filled path four spaces or
  wider and about three quarters of a space thick, centred on the middle
  line, with the count in the music font above the staff over it (Opus
  2.1 spaces tall, Maestro 2.0); a beam can lie there too, so the bar
  must hold no notehead and the count must stand over the path. The
  stretch of the page between two aligned notes is worth the rests'
  counts plus one bar for each printed bar of plain rests beside them,
  and whatever the reading wrote for it -- nothing, one empty bar, three
  -- becomes that many whole-measure rests, in the signature printed at
  the rest if one is (the 2/4 over Artie Shaw's 7-bar rest at C). A
  pitched note the reading has in a stretch the page prints no notehead
  in is the engine's (a quarter read off an H-bar) and goes with it. No
  Room For Squares' page 3 prints 95- and 64-bar rests where the trumpet
  and piano solo, and its printed bar numbers 98, 258 and 262 now match
  the file's.
- **A bar of nothing, or of one whole rest, is a whole-measure rest**
  (`musicxml.fill_rest_bars`): a whole rest stands for the whole bar in
  any metre, and MuseScore flagged The First Circle's opening 12/8 bars
  of one, written four quarters long, as the wrong length.
- **A double bar line drawn as two paths is one bar line**
  (`find_barlines`), which is what let a printed bar be counted.
- **The engine's repeat marks go** (`musicxml.strip_repeats`): homr
  wrote a forward repeat at 115 double bar lines across the corpus where
  Audiveris read 6, and a solo transcription is written out; a mark whose
  direction the cross-check also read stays (Artie Shaw, Beebe, New
  Blues Up and Down have real ones). And the scans' signature: when the
  commonest bar length has three times the bars of the declared one,
  `fix_time_signature` takes it however irregular the rest.

Over the corpus: bars off the signature 1,532 to 1,240 (vector 942 to
746, scans 590 to 494); 900 bars of rest given their bars on 22 files;
19 changes of signature on 3 files; 53 empty or whole-rest bars written
as whole-measure rests on 26; 115 repeat marks dropped on 41; 486 bars
from the cross-check on 98; 21,018 bars and 125,355 notes over 275
transcriptions. Maynard & Waynard, a two-trumpet score, moved to
`excluded/` at the listener's request. A check the round produced and
the tool should grow: the page prints a bar number at every system's
start, and comparing it with the file's measure there matches on every
system of Artie Shaw's Interlude, The First Circle, Passport, The Eel and
The Bird after these rules, while La Prima Notte di Quiete, a nine-page
feature with 176 bars of rest, drifts by up to 24 bars in two stretches
-- the manifest's `rest_notes` name each stretch for the proofreader.

### Pairing the readings when their bar counts differ

The listener saw 32nd notes in Alone Together where the page has
sixteenths, and 64ths in both Body and Souls: homr reads one beam too
many on that heavy handwritten font (213 32nds against Audiveris's 8 on
Alone Together, where Audiveris reads 850 sixteenths). Audiveris had
those bars right, and the merge could not use them, because it paired
bars only when the two readings' bar counts agreed -- 100 of the 275
transcriptions (34 of the 53 scans) differed by a bar or more, and on
those the cross-check merged nothing. `musicxml.pair_measures` now
pairs three ways, the first that applies: by the page's printed bar
when both readings' notes were aligned to the page (`vector.
printed_bar_per_measure`, exact on vector files); by index when the
counts agree; else by system, since both engines mark system breaks --
two systems of equal bar count that begin within two bars of each
other pair, and their bars by index (a SequenceMatcher on the bar
counts paired the wrong systems: with counts 4,4 against 5,4 it matched
the first 4 to the second). Bars from the cross-check 486 to 817 on
171 files; bars off the signature 1,240 to 1,015 (vector 746 to 613,
scans 494 to 402); Alone Together 59 to 36. The Body and Souls stay at
about 50 of 70: with 0% agreement between the readings, a system pairs
only where both engines counted its bars alike, and the taken bars are
nearer the signature rather than right.

## What is left to a human

An OMR reading is a draft. Per page expect a handful of wrong durations,
a missed accidental, a ghost note read as a note; the report says which
bars, and the two readings side by side in MuseScore settle most of them.
Nothing here is committed: the outputs are derivatives of commercial
recordings and `benchmark/` is gitignored (plan §12).
