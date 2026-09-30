# The head-to-head: other transcribers against SwingScribe

2026-09-30. **Prepared, not yet run against any competitor.** No competitor
software was installed or downloaded for this; the listener runs each tool,
drops its files in a folder, and one command scores them. What is here: the
protocol (which spans, what each tool is told, what to export, where to put
it), `scripts/head_to_head.py` (cut the audio, write our own outputs, score
everything), the reader that makes another tool's MusicXML scoreable
(`src/swingscribe/external.py`), and the control that says the path is fair.

Why now: AnthemScore 6.3.0 (2026-09-29) claims "swing detection, written as
straight eighths with a swing marking instead of triplets"
([version history](https://lunaverus.com/versionHistory)), and
docs/landscape.md recommendation 1 is to measure against it and Klangio
before claiming swing as ours.

## 1. The one-command version

    uv run python scripts/head_to_head.py --export-audio --excerpt 29   # the wavs
    # ... run each tool on them, save its files (section 5) ...
    uv run python scripts/head_to_head.py --write-ours --excerpt 29     # our own, the same way
    uv run python scripts/head_to_head.py --score --excerpt 29          # the table

Drop `--excerpt 29` for whole spans (a tool's paid tier). `--plan` lists the
spans without cutting anything and says whether the notes cache is the
running transcriber's; `--control` re-checks the scorer (section 7).
When another run is rewriting the harness caches, point `--notes`, `--grids`
and `--pins` at snapshots.

**Two things to know before reading that table as a result:**

- **`--write-ours` refuses stale notes.** Our column is the harness's notes
  cache, which is right only for the transcriber that wrote it. When any
  span's cached fingerprint differs from what `run_eval.transcribe_fingerprint`
  gives under the code that is running (the case where `run_eval` would
  re-transcribe it), the script stops and names the spans: run
  `scripts/run_eval.py` first. `--allow-stale` writes them anyway and lists
  them in `tool.json`, which records every span's fingerprint either way;
  `--score` refuses to cut an excerpt's references on notes other than the
  ones our page was written from. On 2026-09-30 this was live: the default
  cache held the hybrid task's re-transcribed horns, 22 of the 30 spans, not
  HEAD's transcriber's.
- **In an excerpt condition our column is not a like-for-like run.** Our
  notes come from the whole span's stem and our beat grid and downbeat from
  the whole track; only the page and the MIDI are cut to the 29 seconds.
  Every other tool hears the 29 seconds alone (section 5). The paired table
  is still the right instrument, but no excerpt result should be published
  until our pipeline is run on the cut wavs themselves; `--score` prints this
  above the table.

## 2. What it answers

The same two questions every other measure in this project keeps apart
(CLAUDE.md, "Measuring"):

- **Did it hear the notes?** Pitch F1 (time-free, the aligner), note F1 in
  time against the hand scores (`score_benchmark.score_tune`, the MuseScore
  set's measure), and WJazzD note F1 (a human's onsets in seconds,
  `score_wjazz`).
- **Would a musician write it that way?** Notated rhythm and value with their
  coverage (`benchmark.score_against_notation`), readability
  (`benchmark.readability`), placement on the reference's beat
  (`score_bars.bar_line_agreement`, `on_the_bar`), and the edit cost per 100
  reference notes (`benchmark.edit_cost`, docs/roadmap.md E4).

On WJazzD only note F1, coverage, readability and placement are read: its
tatum layer is Flex-Q's quantisation, not a page (D36), so its rhythm is never
a page measure.

## 3. The spans: thirty, all dev split

| set | n | what | reference |
|---|---|---|---|
| hand | 12 | every hand-scored track in `benchmark/` | the listener's `.mscz` |
| silver | 3 | the PDF pages rated silver (Embraceable You, Cheese Cake, Gingerbread Boy) | OMR MusicXML (`pdf2musicxml`) |
| wjazzd | 15 | a frozen subset of the 73 dev solos | WJazzD onsets, beats and bars |

The hand and silver spans are the harness's own (the run's region, i.e. the
sidecar span). A WJazzD span is the located solo plus the harness's 1 s margin
each side (`run_eval.SOLO_MARGIN_S`), so nobody transcribes the head.

**The WJazzD fifteen** (`WJAZZ_SUBSET`, chosen once by
`choose_wjazz_subset`): one solo per recording, no tune already in a page set
(Giant Steps is both), and (instrument, tempo class) cells filled first, in
the order of a salted hash of the name, so nobody picked them. Blues For
Alice, Donna Lee and Don't Blame Me (Parker); I Fall In Love Too Easily and
Let's Get Lost (Chet Baker); Crazy Rhythm and Yesterdays (J.J. Johnson); My
Favorite Things (Coltrane, soprano, 3/4); Walkin' (Miles); Nothing Personal
(Metheny, guitar); Oleo (Red Garland, piano); Limehouse Blues (Bechet,
soprano); Adam's Apple and Dolores (Shorter); Cherokee (Wynton Marsalis).
Alto, tenor, soprano, trumpet, trombone, guitar and piano; 64 to 333 bpm.
The subset is frozen: `--plan` says if the rule would pick differently today,
and the frozen list stands.

**Home advantage, on the record.** Every one of these tracks is in the dev
split: SwingScribe's rules were tuned while looking at them, and no
competitor's were. The locked test split (`tests/regression/split.json`)
holds no track yet -- everything in `benchmark/` on 2026-09-29 is dev by
construction. When test-split recordings arrive, a head-to-head over them is
the unbiased version, and it is a use of the test set that tunes nothing.

## 4. The audio every tool gets

`--export-audio` cuts each span out of the recording into
`benchmark/head_to_head/<condition>/audio/<set>/<name>.wav`: 16-bit PCM at
the recording's own rate and channels, from the same decode the pipeline
reads (the ingest cache's wav when it exists, else soundfile, else ffmpeg --
checked sample for sample on three tracks: lag 0, correlation 1.00000, gain
1.000). Beside it, `manifest.json` (every span's window, the wav's sha256,
where it was decoded from) and `settings.csv` (the sheet to click through:
instrument, time signature, what to save it as). Every later step reads the
manifest, so the windows cannot move under a tool's files.

Conditions, each its own folder:

- **`mix-excerpt29s`** -- the first 29 s of each span. AnthemScore's trial
  transcribes "the first 30 seconds of each song"
  ([download page](https://lunaverus.com/download)); a second short of that
  so no tool drops the last note. The common denominator: every tool can
  run it. (Carl Perkins' span is 17.4 s, so it is whole.)
- **`mix-full`** -- whole spans, 17 s to 2 min 45 s (median 90 s, 46
  minutes in all): a tool's paid tier.
- **`stem-*`** (`--source stem`) -- the stem SwingScribe transcribed from,
  instead of the mix. This takes separation out of the comparison: the
  mix condition is the product question (a listener hands a tool a record);
  the stem condition is the transcription question. Run the mix first.
  The stem is resolved the way `run_eval` resolves it
  (`library.resolve_stem`, the narrowest span-scoped set first) in
  `--cache-dir`, which defaults to `benchmark/.swingscribe-cache`: that is
  where the pins' span-scoped Roformer stems are (CLAUDE.md), and the repo
  root's `.swingscribe-cache` holds a different, smaller set. Pass the cache
  `run_eval` was run with if it was another. The script also refuses a span
  whose cached notes record a different model or stem from what the sidecar
  now names, and the manifest records the stem directory each wav was cut
  from.

For Klangio's free demo, which stops at 20 seconds, `--excerpt 19` makes a
`mix-excerpt19s` condition the same way.

**benchmark/ is gitignored and the wavs never leave it.** Nor do the tools'
outputs: they are transcriptions of commercial recordings (plan section 12).

## 5. What each tool is told

The rule: every tool gets what SwingScribe's sidecar gives SwingScribe, and
nothing a tool could not be given.

| | SwingScribe | every other tool |
|---|---|---|
| audio | the recording: the harness's notes and grid, cut to the window | the wav in `audio/` |
| who plays | the sidecar's ensemble (horn or piano routing) | the instrument in `settings.csv` |
| metre | the sidecar's (3/4 on Someday My Prince) | the same, from `settings.csv` |
| tempo | none (the beat tracker's) | none: let it detect |
| key | none (detected) | none |
| downbeat | none: `--write-ours` drops the sidecar's anchor | none: do not tap downbeats |
| swing | on (its default) | on, where the tool has a setting |
| pitch | concert | concert: no transposing-instrument setting |
| edits | none (no erasures, the harness's notes) | none: export the first result |

**Where SwingScribe is NOT given the same thing: context.** Our notes are
the harness's, transcribed over the whole span from its stem, on a beat
grid tracked over the whole track; only the notes and the page are cut to
the window. In the excerpt condition that is context no other tool gets --
the tempo and bar phase of the minutes around the 29 seconds. The fair
alternative is our pipeline run on the cut wav itself (the GUI opens a wav
like any recording); that is a separation and a CREPE pass per span, left
for the run that scores a real competitor.

**The downbeat costs us nothing measurable.** 21 of the 30 sidecars carry a
downbeat (3 hand, 3 silver, all 15 WJazzD, the last voted from the
reference). On all 21 the automatic downbeat has the same bar phase, and
`--write-ours --downbeat sidecar` writes byte-identical pages on all 30.

**Concert pitch, but a transposed part is fine too.** The reader undoes a
`<transpose>` element; a tool that writes transposed pitch without one is
still scored right on pitch and rhythm (every scorer settles the
transposition over the whole line, `alignment.measured_transposition`), but
its key signature is then the written one. Asking for concert pitch avoids
the question.

### AnthemScore 6.3, the desktop trial (local: nothing is uploaded)

Trial terms as the site states them: "Free trial with unlimited 30-second
transcriptions", "Limited to first 30 seconds of each song and 100 total
transcriptions", and "Use Tools > Editions to try out Lite, Professional, and
Studio features" ([lunaverus.com](https://lunaverus.com/),
[compare editions](https://lunaverus.com/compareEditions)). MusicXML and
MIDI export belong to Professional ($39) and Studio; **whether the trial's
Professional mode exports is not documented** -- the first file answers it.
Thirty spans use 30 of the 100 transcriptions.

1. Install the trial from [lunaverus.com/download](https://lunaverus.com/download)
   and check Help > About says 6.3.0 or later (6.3 is the swing release).
2. Tools > Editions > Professional.
3. For each row of `settings.csv`, in order: File > Open the wav. In the
   dialog: **Full song**, **Find notes** on, **Percussion detection** off.
4. Sheet music settings (the settings icon): one part, the instrument from
   the sheet (a grand-staff piano part for the piano rows). Instrument
   written transpose: none (concert). Smallest note: leave the default, and
   write it down. Simplify score: off. Arrangement (6.2+): the most
   detailed. Swing: whatever 6.3 offers, on; if it is automatic, leave it.
5. Measures (tab 2): if the detected time signature differs from the
   sheet's, set Time signature top/bottom at the first downbeat -- the same
   fact SwingScribe's sidecar carries. Do NOT move or tap beats or
   downbeats, and do not set a tempo.
6. Notes (tab 1): no edits.
7. File > Export > **MusicXML Sheet Music**, saved as
   `benchmark/head_to_head/mix-excerpt29s/anthemscore/<set>/<name>.musicxml`
   (the `save as` column).
8. File > Export > **MIDI** to the same name with `.mid`: Transpose 0;
   Constant note volume off; **Auto-detected tempo map**; **Use musical
   (rounded) timing OFF**. Rounded timing writes the page into the MIDI, and
   a page is not a hearing (section 8): the scorer flags a MIDI whose
   onsets sit on a 24th grid and leaves its note F1 out of the pairing.
9. Once, `benchmark/head_to_head/mix-excerpt29s/anthemscore/tool.json`:

        {"tool": "AnthemScore", "version": "6.3.0",
         "edition": "trial, Tools > Editions > Professional",
         "settings": "smallest note ..., arrangement ..., swing ..."}

   (`"part": "<name or index>"` if the file holds more than one part and the
   solo is not the first; `"drums": true` never.)

If the trial will not export MusicXML or MIDI: buying Professional is the
listener's decision. The other road is the trial's PDF through
`pdf2musicxml` into a separate tool folder (`anthemscore-pdf`) -- but that
scores AnthemScore plus our OMR, a page with no timing, and must never be
read as AnthemScore alone.

### Klangio and Songscription (cloud: the recording is uploaded)

Uploading commercial recordings is the listener's call.
**Songscription may train on it**: "By default, we may use the audio and
transcriptions you submit to help improve our AI models", with an opt-out
for paid plans only ([pricing](https://www.songscription.ai/pricing)).

- Free tiers will not do. Songscription's free plan is "Unlimited 30-second
  transcriptions" with MIDI and MusicXML export on Plus and Pro only (same
  page). Klangio's demo is 20 seconds ([Wind2Notes](https://klang.io/wind2notes/)),
  its paid plans export "PDF sheet music, MIDI, or MusicXML", and its FAQ
  offers "quantized or unquantized MIDI": take **unquantized**.
- Klangio: Wind2Notes for the horns, Piano2Notes for the piano rows. Its
  pre-transcription settings ([guide](https://klang.io/blog/additional-information-guide/)):
  key -- none; time signature -- the sheet's; tempo in BPM -- none;
  note duration quantization -- sixteenth; triplet recognition -- on (jazz
  has triplets; there is no swing setting to turn on).
- Songscription: the instrument; export MusicXML and MIDI.
- Folders `klangio/`, `songscription/`, each with a `tool.json` saying the
  plan, the date and the settings.

Any other tool: a folder of `<set>/<name>.musicxml` (or `.xml`, `.mxl`) and
`<name>.mid`. MIDI alone, or a page alone, is scored for what it can be.

## 6. How a tool's file is scored

`--score` walks every folder in the condition. Each file goes through the
same functions our own pages go through, called the way `run_eval` calls
them (`page_row` is `run_eval._notation_one`'s row).

**A page becomes a `Notation`, not a Score.** Every notation scorer takes
our `Notation`, and `external.read_musicxml` reads a MusicXML file into one.
Comparing Score-to-Score (parsing the tool's page with the reference reader)
was the other option, and it loses three ways: readability needs the rests,
tuplet ratios, ties and bar membership a Score throws away; the reference
reader (`mscz.parse_musicxml`) lays a short pickup bar out from its START
and ignores `<transpose>`, harmless on a hand score and wrong on a tool's
page; and only a Notation makes fairness testable, because our own export
read back must reproduce our own numbers exactly (section 7).

Two views come out. The **page** is everything written, every voice and
staff, a chord folded into its head note; readability, bars and key are
read off it. The **line** is what the pitch and rhythm scorers compare, by
the rule the reference reader applies to a hand score: ties merged, then the
top note of each simultaneity across voices and staves. On our single-line
pages the two hold the same notes. Pitches are concert throughout; an
`<octave-shift>` is display only in MusicXML (the pitch under an 8va is
already the sounding one), unlike `.mscz`.

**Grace notes follow the reference's reader** (`external.graces_for`),
because the two readers disagree: the `.mscz` reader keeps a grace note as a
pitch of no length beside its main note (the hand set), while
`mscz.parse_musicxml`, which reads the silver OMR references, lets it
compete with its main note for the position and the higher one wins. A tool
that writes grace notes is read by the same rule as the reference it is
compared against; read by the other, it would pay an insertion per grace on
the silver set that our graceless pages never pay. WJazzD's performed notes
keep. Checked against the reference reader on 275 OMR MusicXML files (a
review, 2026-09-30): with `<transpose>` and grace notes set aside the two
lines agree exactly on 212 and at a sequence ratio of at least 0.978 on the
rest, and on LORIA's 50 Omnibook files they are identical; the compete rule
is held to `mscz.parse_musicxml` exactly in the tests.

**Timing.** Note F1 needs seconds. A MIDI file gives them; failing that,
the page at its own tempo marking (`external.page_seconds`); a page with no
tempo marking gets pitch F1 only. Timed notes are scored as delivered, ours
included (all of a piano texture, if that is what a tool exported);
`--top-line` reduces every tool's timed notes to the top line of each 50 ms
cluster as a sensitivity reading, and `polyphony` in the row says how
chordal the delivery was.

**Pitch F1 reads the same kind of output on both sides.** Where both sides
wrote a page it is read off the page's LINE (one line by the reference
reader's rule), else off both sides' timed notes; a pair with neither in
common is not paired. Reading a tool's MIDI as delivered against our one
separated line would charge separation, not hearing: AnthemScore
transcribes the whole mix. `pitch_f1_timed` (the timed notes as delivered)
is printed and paired beside it.

**Note F1 is paired only between rows timed by performed onsets** -- a MIDI
file on both sides, and not one written from a page. Timed off a page it
measures the writing, not the hearing (section 8), so a page-only row is
shown in the tool's means and left out of the pairing, and the table says
how many. `external.midi_timing` reads every MIDI file's clock and FAILS
CLOSED: **quantized** when 90% or more of its onsets sit on a 24th of its
quarter (to the nearest tick, whatever the division) and that share is
beyond chance for its clock (binomial tail under 0.001); **performed** under
90% (our own files: at most 7%); **unknown** when the clock cannot tell --
SMPTE time, no notes, or a division so coarse (24 or 48 ticks a quarter)
that a performance lands on the grid as often as a page. Only performed is
paired. For a tool left out, the hearing measure is pitch F1, which reads no
time. `--pair-any-timing` lifts the rule for the experiment below and never
for a verdict.

**Excerpts.** For an excerpt the reference is cut to the notes the
excerpt's audio holds, keeping bar phase (`external.excerpt_reference`,
`external.crop_score`). Which notes those are is decided by aligning the
reference to OUR notes with no timing and placing it in time on the matched
ones (`benchmark.place_on_anchors`) -- a property of the recording, decided
once, the same cut for every tool. WJazzD's reference notes and positions
are cut by our pinned fit of the solo (`external.wjazz_excerpt`); each
tool's notes are then fitted by the harness's own `wjazz.fit_affine` over
the excerpt. Both cuts are fitting code, so they live in the package with
tests (CLAUDE.md), and the control runs them end to end (section 7).

**WJazzD's hearing measures** are note F1 in time (MIDI only, above) and
pitch F1, the annotation's pitch sequence against the line with the
aligner's time-free call (`alignment.measured_transposition`, what
`score_tune` does against a hand score) -- so a page-only tool is read for
hearing on WJazzD too. The page's WJazzD coverage is the share of the
annotation `wjazz_bar_line_agreement` placed, and **0 when it placed
nothing** (a page in another metre, or one that matched no note):
such a page stays in the coverage pairing as the tool's worst case instead
of dropping out of it.

**The table.** Per set, per tool: the mean of each measure with its n, the
timing source, pages carrying a swing marking, WJazzD fits the harness
would accept, and any quantized or unreadable MIDI. Then each tool against
SwingScribe on the spans both hold: n, spans missing, both means, the
change, a 95% interval resampled by span, up/down and the sign test
(`evaluation.paired_change`); a star when the interval excludes zero AND
the sign test says p < 0.05. Rhythm, value, placement and edit cost are
withheld on a page under the coverage floor (0.5) on either side, and a row
with no coverage is never trusted (CLAUDE.md: never show rhythm without its
coverage); the table counts what it withheld and what it could not pair.
`--detail` prints every span's row, `--json` saves everything.

## 7. The control: our own exports, read back, reproduce our pins

`--control` writes our pages with the settings the pins were made with (the
sidecar downbeat, whole spans), reads them back through `external` and the
MIDI path, and compares every number with
`tests/regression/real-audio-baselines.json`. Run on HEAD's code with the
pre-hybrid notes snapshot (2026-09-30):

- **714 pinned numbers over 30 spans; 710 exact, all 714 within 0.002**
  (the harness's tolerance). The four others are one span: Soul Station's
  run holds one note whose onset falls after the span's end; the audio a
  tool is given does not contain it, so our MIDI does not either (pitch F1
  0.7069 -> 0.7085, chroma 0.7875 -> 0.7892, onset 0.4602 -> 0.4613, note
  0.3329 -> 0.3337).
- **The MIDI tick is part of the control.** Our notes reach the scorer
  through a MIDI file, and a WJazzD fit is a search on a 2 ms offset grid
  (`wjazz.fit_affine`) with knife edges in it: rounding Yesterdays' onsets
  to 52.1 us ticks moved its note F1 off the pin (0.8968 -> 0.8947 in a
  direct test, 0.9032 through the file) while floats and 1, 20.8, 50 and
  100 us ticks all reproduced it. `write_midi` uses 20.8 us ticks (24000 a
  quarter at 120 bpm); with them the control is the 714 above.
- Checked: pitch, chroma, onset and note F1 on hand and silver (the pins'
  pitch and chroma F1 are our MIDI's, `pitch_f1_timed`; the headline pitch
  F1 is the page line's, section 6); rhythm, value, n_matched, bars, key,
  readability and its parts, the bar-line agreement and trace, the edit
  cost and every component; coverage and trust on the located sets; WJazzD
  note F1 and its parts, readability, placement, coverage.
- **The notes must be the pins' notes.** The control runs whatever the
  cache holds, because it tests the reader; it names the spans whose cached
  fingerprint is stale for the running code, and counts the failures on
  them separately. A span can fail because its notes are not the ones the
  pins were made from, in either direction (re-transcribed and not
  re-pinned, or re-pinned and the cache not re-run). Re-checked on
  2026-09-30 after the stale-notes fix: HEAD's code, the pre-hybrid
  snapshot (0 of 30 stale) and HEAD's pins, **714 of 714 within 0.002**,
  worst chroma F1 0.0017, the Soul Station edge note as above. The same
  HEAD code against the live cache finds 22 of 30 stale (5 hand, 3 silver,
  14 WJazzD horn solos; the hybrid task's re-transcription), and
  `--write-ours` refuses them and writes nothing; the working tree's
  transcriber finds the live cache fresh and the pre-hybrid snapshot 22
  stale. The check follows the code that is running, as `run_eval`'s does.
- **The excerpt machinery, run end to end over whole spans** (the second
  block of `--control`; `--no-crop-control` skips it). The same pages are
  scored with the reference CUT on our alignment and WJazzD refitted over
  the window, the window set to the whole span. It is a reading, not a
  gate: every tool in a condition shares one cut, so the paired table is
  fair whatever it reads, and this says how far an excerpt's absolute
  numbers sit from a pin's. 647 of 714 within 0.002. The cut is nearly the
  identity: it keeps 5,985 of the 5,987 hand and silver reference notes
  (one edge note each on Carl Perkins and Soul Station) and trims empty
  edge bars on three scores (All The Things 73 -> 72, Someday 65 -> 64,
  Lover 64 -> 62). Rhythm moves on none of 15 pages, value by at most
  0.005, placement by at most 0.006, edit cost by at most 0.44 per 100;
  WJazzD placement and coverage are exact on all 15 and its note F1 moves
  by at most +0.007 (Let's Get Lost), the refit over the window.
  **The MuseScore set's note F1 moves, on the hand set by +0.055 on
  average, from -0.022 to +0.330** (Carl Perkins' 17-bar span 0.330 ->
  0.660; For Minors Only +0.139, Someday +0.091, Lover +0.089); silver by
  -0.021 to 0. `score_tune` reads ONE tempo per score, bars divided by the
  region's seconds, and the region here is our placed bar lines instead of
  the listener's span: 1-2 s at either end of a short span is a tempo off
  by several percent, and an 8-bar window cannot absorb a scale error. The
  placed tempo is not uniformly the better one (Someday 150.5 bpm against
  the tracker's 150.0 and the span's 154.6; For Minors Only 223.2 against
  214.3 and 215.3). So in an excerpt condition that note F1 is comparable
  between tools and **not with any pin**, and the pinned MuseScore-set note
  F1 is itself that sensitive to where the listener's span ends
  (section 9).
- The pages the GUI's Export wrote beside the audio (`benchmark/*.musicxml`)
  are also scored and do NOT reproduce the pins (99 of 312 page numbers):
  they are older exports with the listener's erasures, which is the
  expected answer and the check that the control can fail.

And in CI, `tests/test_external.py` holds the reader to the round trip on
every construct our notate stage writes (a pickup in a full bar 0, ties over
a bar line, triplets, a quintuplet, a change of metre, a transposed part, a
double-time page, chords, two staves, `.mxl`), plus what only a competitor's
file does (a short pickup, a second voice after `<backup>`/`<forward>`,
a grace note under either reader's rule, an octave-shift, a tempo change, a
bar that overruns its signature, a MIDI file in format 1 with running status
and a tempo change, MIDI clocks from 24 to 24,000 ticks a quarter and SMPTE),
both excerpt cuts on a synthetic line with notes missed and added, and the
stale-notes refusals of `--write-ours` and `--score`.

## 8. What the table can and cannot see: pseudo-tools

Before any competitor's file exists, five pseudo-tools built from our own
notes show the table's resolving power and its traps (`mix-excerpt29s`,
HEAD's code, the pre-hybrid snapshot). The literal page is
`--write-ours` under `SWINGSCRIBE_QUANTIZE__TIMING=literal-16`; the second
is `--write-ours --page-variant`; the rest were built from those by
one-off scripts (a tempo marking pasted in with `external.add_tempo`, a
MIDI file written from the page's line, lower voices added to our MIDI):

- `literal16` -- our notes, the page written by our `literal-16` timing,
  our MIDI: what a tool with no swing reading writes;
- `swingscribe-page` (`--write-ours --page-variant`) -- our page with a
  tempo marking (the median of our grid over the window) and no MIDI;
- `literal16-pagetempo` -- the literal page, the same way;
- `swingscribe-roundedmidi` -- our page plus a MIDI written from it, 480
  ticks a quarter: AnthemScore's "musical (rounded) timing";
- `swingscribe-texture` -- our page, and our MIDI with every note doubled a
  twelfth and two octaves below: a tool that hears our line exactly and
  exports the whole mix as MIDI.

Re-run on 2026-09-30 after the review fixes: every `literal16`,
`swingscribe-page` and `swingscribe-roundedmidi` number below reproduced to
the last digit, including our page timed against our MIDI under
`--pair-any-timing`. `literal16-pagetempo` and the grid placement were not
rebuilt; their rows are the first run's.

**A literal page, same notes.** Hand set, n = 12:

| measure | swing | literal | change [95%] | up / down |
|---|---|---|---|---|
| rhythm | 0.842 | 0.639 | -0.204 [-0.250, -0.158] | 0 / 12 |
| value | 0.775 | 0.556 | -0.218 [-0.262, -0.171] | 0 / 12 |
| readability | 0.999 | 0.963 | -0.036 [-0.049, -0.026] | 0 / 12 |
| edit cost per 100 | 52.6 | 83.9 | +31.3 [+24.7, +37.6] | 12 worse |
| placement | 0.923 | 0.912 | -0.011 [-0.036, +0.008] | 5 / 6 |
| pitch F1 of the MIDI, note F1 | | | exactly 0 | |
| pitch F1 of the page line | 0.885 | 0.885 | -0.000 [-0.001, +0.000] | 0 / 1 |

Pitch F1 off the page line is the page's hearing AND what its writing kept:
our swing page's line holds a note or two fewer than the literal page's on
some spans, so it reads under our own MIDI by 0.000 (hand), 0.007 (silver)
and 0.002 (WJazzD), and the literal page reads +0.008 [+0.000, +0.023]
(silver, 1 up) and +0.002 [-0.002, +0.008] (WJazzD, 3 up, 2 down) against
ours. Small, and the same charge for every tool's page.

Twelve spans decide a difference of this kind; three silver spans decide
nothing (rhythm -0.188 [-0.367, +0.022], 1 up 2 down). On WJazzD
readability falls -0.029 [-0.038, -0.021] (1 up, 14 down), but placement
RISES, +0.027 [+0.013, +0.047], 14 up and none down: WJazzD's positions
are Flex-Q's literal quantisation (D36), and a literal page files a few
more matched notes in the beat Flex-Q filed them in. On WJazzD
`on_the_bar` catches a page a beat off (0.9 against under 0.1);
differences of a few hundredths there are collateral, not style.

**Timed off a page, note F1 measures the writing (NEGATIVE, and the pairing
rule).** Paired with `--pair-any-timing`:

| | hand, n = 12 | WJazzD, n = 15 |
|---|---|---|
| our page timed, against our MIDI | +0.011 [-0.053, +0.076], 6 / 6 | **-0.190 [-0.247, -0.138], 0 / 15** |
| literal page timed, against our page timed (the SAME notes) | **-0.094 [-0.146, -0.045], 2 / 10** | +0.032 [+0.000, +0.066], 10 / 5 |
| literal against ours, both from MIDI (the same notes) | exactly 0 | exactly 0 |

Two tools that heard identical notes differ by a tenth of note F1 once
both are timed off their pages, in opposite directions on the two
references: against a hand score, which is a page, the swing page's
positions win; against WJazzD's performed onsets the literal page's
sixteenths sit nearer the played swung eighths. Neither is hearing. So note
F1 pairs only rows timed by performed onsets, and a page-only tool's hearing
is read off pitch F1. The rounded-MIDI pseudo-tool is caught on all 30
spans: every onset on a 24th of its quarter (share 1.0), where our own
files reach at most 0.07 (our onsets sit on a 10 ms frame grid, and 1 in 25
of those lands on a 24th of a 120 bpm quarter; chance for a performance is
24/division, 0.001 on ours).

**A whole-mix MIDI is not charged to pitch F1 (the review fix).** Before,
pitch F1 came off a tool's MIDI when it had one and off its page when not,
so a tool exporting both was charged for every band note on its MIDI while
ours is one separated line, and even our own page-only pseudo-tool read
-0.008 on a silver span against our MIDI. Now it pairs page line with page
line: `swingscribe-page` against us is exactly 0 on all three sets, and
`swingscribe-texture` -- our line, our page, a MIDI three notes deep -- is
exactly 0 on pitch F1 while `pitch_f1_timed` falls -0.444 [-0.458, -0.428]
(hand, 0 up 12 down), -0.448 (silver) and -0.435 [-0.452, -0.417]
(WJazzD, 0 / 15). Note F1 is still read off the MIDI as delivered and falls
-0.302 [-0.344, -0.248] (hand) and -0.445 [-0.465, -0.424] (WJazzD); with
`--top-line` the texture tool reads exactly our numbers on every set, so a
tool that exported its whole mix is read both ways.

**Placing a page on a beat grid does not rescue it (NEGATIVE, not built).**
The brief allowed WJazzD note F1 "where the output can be placed on our
grid". Measured on our own page: placed on OUR OWN repaired beat grid, at
the best of 17 whole-beat origins around the window start (chosen with the
answer, so an upper bound on any grid placement), WJazzD note F1 reads
0.764, against 0.677 at one tempo marking and 0.867 from the MIDI.
Following the band's tempo wins back +0.087 [+0.066, +0.107] (15 of 15);
what remains, -0.103 [-0.156, -0.056] (0 up, 13 down), is the quantisation
itself -- the swung eighth written even -- and it is tempo-bound: 0.94 ->
0.70 and 0.97 -> 0.63 on the two 64-65 bpm ballads, nothing lost at 273 bpm
(Oleo, Limehouse Blues). Even at its best a placed page scores the
notation, so WJazzD note F1 is a MIDI measure.

## 9. Known limits

- **n.** 12, 3 and 15. The hand set decides a large difference and the
  silver set decides nothing alone; read the three together, and prefer the
  whole-span condition when a tool allows it (more notes per span, same n).
- **Pianists.** The hand scores are right-hand melody. A tool that writes
  both hands is compared on its top line (the reference reader's rule), and
  its timed notes include the comping unless `--top-line`; `polyphony` in
  the row says how much. Our own piano line is the oracle line.
- **A tool at the other pulse** (a fast tune written in half time) is
  charged on rhythm the way ours would be; `beat_slope` in `--detail` rows
  says 0.5 or 2.0.
- **The excerpt is the span's first 29 seconds,** not a chosen passage: a
  trial limit, not a musical choice.
- **Not read:** score-timewise MusicXML (refused by name), cue notes,
  unpitched percussion, a part other than the first unless `tool.json`
  names it.
- **Home advantage** (section 3), until the test split holds tracks; and
  in the excerpt condition, **context** (section 5): our notes and grid
  come from the whole span and track, a competitor's from 29 seconds.
- **The excerpt's reference is cut on our alignment.** One cut for every
  tool, but decided from where OUR matched notes placed the reference; a
  note at either edge can go the wrong way, the same way for everyone (2 of
  5,987 over whole spans, section 7).
- **MuseScore-set note F1 reads one tempo per score** (`score_tune`: bars
  over the region's seconds), so it moves with the region's ends: up to
  0.33 on a 17-bar span between the listener's span and our placed bar
  lines (section 7). Paired within a condition it is fair; across a
  condition and a pin it is not comparable, and the pins carry the same
  sensitivity. A benchmark question, not a head-to-head one.
- **Pitch F1 off a page line includes what the page dropped** (section 8):
  a tool is charged for the notes its page does not write, as ours is.
- **A MIDI whose clock cannot tell** (24 or 48 ticks a quarter, SMPTE, a
  handful of notes) is not paired on note F1, whatever it holds: failing
  closed can leave a performed file unpaired, never a page counted as a
  hearing.

## 10. Files

- `scripts/head_to_head.py` -- `--plan`, `--export-audio`, `--write-ours`,
  `--score`, `--control`.
- `src/swingscribe/external.py` -- `read_musicxml` (page and line, the
  grace rule `graces_for`), `page_seconds`, `read_midi` / `write_midi`,
  `midi_timing` / `midi_grid_share`, `add_tempo`, `top_line`, `polyphony`,
  and the excerpt cuts `excerpt_reference`, `wjazz_excerpt`, `crop_score`.
  Stdlib only.
- `tests/test_external.py` -- the round trip, a competitor's constructs,
  the grace rule against `mscz.parse_musicxml`, MIDI and every clock
  verdict, both excerpt cuts, the subset rule, the timing- and
  source-aware pairing, trust failing closed, the stale-notes refusal in
  `--write-ours` and `--score`.
- Outputs: `benchmark/head_to_head/<condition>/` (gitignored), never the
  repo.
