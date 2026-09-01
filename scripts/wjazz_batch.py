"""Run the GUI's whole workflow over benchmark/wjazzd audio, unattended, and
keep a progress spreadsheet of the result.

    uv sync --group ml --group gui --group batch
    uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db --limit 3
    uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db --random 3
    uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db \
        --file Herbie_Hancock_Orbits_solo_188.m4a
    uv run python scripts/wjazz_batch.py --db wjazz/wjazzd.db --all

Run from the repository root, like every other script here — paths below
are relative to it (matches scripts/run_eval.py's BENCH convention).

## What this automates

For each audio file in benchmark/wjazzd/, by hand in the GUI you would: open
the track, pick a separation model and an ensemble, run Beats and Separate,
transcribe, find where the annotated solo actually sits, narrow the span to
it, export the MusicXML, and read the Score button. This script does all of
that, using the exact same code the GUI buttons call
(gui/musicxml.py's export_span/score_span, notation.py's notation_for_span) —
never a second copy of that logic (CLAUDE.md).

## How the solo is located — by content, never by filename

"A performer and a tune do not name a solo" (wjazz.py, docs/wjazzd.md):
WJazzD holds 456 solos under 421 performer/title pairs, and two files here
are byte-identical (Miles_Davis_Dolores_solo_314.m4a and
Wayne_Shorter_Dolores_solo_427.m4a — the same recording, each excerpt naming
the soloist WJazzD annotated in it). So the trailing number in the filename
is trusted only as *which melid to look for*, never as where it sits: the
file is transcribed whole, `wjazz.fit_affine` places that melid's own
annotated notes against what we heard, and only the fitted span is kept.
That is also what makes the two Dolores files come out as two different,
correctly-scoped exports of the same audio.

## Ensemble and separation model, chosen from WJazzD's own `instrument` field

A piano soloist gets `trio` (the piano oracle) and plain `htdemucs` — NOT
`htdemucs_6s`, which routes piano into its own stem and starves the `other`
stem we transcribe down to a twentieth of its notes
(docs/benchmark-deficiencies.md D3), and NOT `htdemucs_ft`, which costs 4x
for no measured benefit (config.py SeparateConfig). Everything else gets
`horn-led` and `htdemucs_6s`, which pulls a comping piano OUT of `other`
(CLAUDE.md). See `auto_settings`.

## The two-pass transcription

Pass 1 transcribes the WHOLE file to locate the solo (CLAUDE.md: "A WJazzD
track needs NO span selection... sidecar the full duration and let it
search"). Pass 2 re-transcribes narrowed to the located span, because
"Notate only the LOCATED solo, never the whole track" — exporting the wide
pass would put the head and every other soloist in the score too. Pass 2 is
cheap: separation and the beat grid are unchanged and served from cache, so
only CREPE re-runs, over a span rather than the whole track.

## The hand transcript and what its score means

`{performer}_{title}_solo_{melid}.musicxml` in `../wjazz-scores/` (sibling of
this repo — ODbL, never inside it) is built by `scripts/wjazz_score.py` from
WJazzD's own metrical annotation. This script writes it on demand if it does
not exist yet, via the exact same builder. The rhythm score against it is
scored via `score_against_notation` — the GUI's own Score button path — and
is reported ALONGSIDE its coverage, never alone: per CLAUDE.md, rhythm on a
wrong pairing can read as high as 0.583, so a rhythm number with no coverage
next to it is not trustworthy. The "value" (note-duration) half of that score
is deliberately NOT reported here: `../wjazz-scores` durations are already
OUR OWN notation conventions applied to WJazzD's grid (wjazz.py
annotation_notation), so scoring our values against them would be scoring our
conventions against themselves.

## The spreadsheet

benchmark/wjazzd/wjazzd_benchmark_test.xlsx, one row per melid (all 456, seeded the
first time this runs, most with no audio in this folder and so left blank
past `title`). Only rows for melids actually processed in a given run are
touched; every other row is left exactly as it was (openpyxl, keyed by the
`number` column). Never committed — `benchmark/` is entirely gitignored.

It carries BOTH of the GUI's measures, prefixed apart because both call a
number "matched" and they are not the same number (see HEADERS):

- `notes` is ours; `notation_reference` is the hand transcript's.
- `pitch_*` is the green ground-truth bar — did we hear the right notes?
- `notation_*` mirrors the Score line, "rhythm 0.630 · value 0.509 · 60%
  lined up (332/552)", in that order. COVERAGE is the "60% lined up", not
  the value: an earlier version of this sheet carried coverage where a
  reader reasonably expected value, which is how this got confusing.

`migrate_columns` adds new columns to an existing sheet by name, so widening
it never costs the rows already scored.

## Standing where the cache expects

This chdirs to the cache's own directory (`--cache-dir`'s parent, i.e. where
`swingscribe gui` is launched from) before doing anything, and that is not
cosmetic. `ingest` stores the path of its normalized wav INSIDE the cached
Document, built from `cache_dir` as given — so a GUI launched from
`benchmark/` with the default relative `.swingscribe-cache` records
`.swingscribe-cache\audio\<digest>-44100.wav`, a path that only resolves from
that directory. The ingest cache KEY covers the audio bytes and the ingest
config, not `cache_dir`, so this script gets a cache HIT on that Document and
inherits its relative path. Run from the repo root, `separate` then dies on a
file that is plainly there — which is what killed a full run 31 files in, on
the one track that had been opened in the GUI first.

Standing where the GUI stands makes every such path resolve exactly as it
does for the GUI. Everything this script owns is absolute, so nothing else
cares where it is run from.

## Matching the GUI exactly

The number in the spreadsheet must be the number the Score button shows, and
getting that right is not automatic. Two canonicalisations stand between "the
same notes" and "the same page", and skipping either produced a genuinely
different score from the GUI's:

- **The span is rounded to the millisecond** (`review.span_config`). An
  unrounded span crops the audio a couple of hundred samples away from where a
  rounded one does, which moves CREPE's 10ms frame lattice against the music
  and flips notes across quantizer grid boundaries. Measured on Maiden Voyage:
  the identical 489 notes score notated rhythm 0.686 unrounded against 0.630
  rounded.
- **Note onsets are rounded to 3 decimals** on their way into the review
  payload (`review._payload`). Worth 0.686 -> 0.673 on the same solo.

So this does not transcribe the span itself. It calls
`review.analyze_and_cache`, which is what the GUI's Transcribe button calls,
and scores the payload that comes back — the rounding, the caching and the key
are then the GUI's by construction rather than by imitation. The useful side
effect is that the review lands in the GUI's own cache: open one of these
tracks afterwards and the notes are already there, with no Transcribe click and
no second CREPE pass, and Score It reports what is in the spreadsheet.

## Sharing a cache with the real GUI

Every stage cache key is a hash chained through EVERY upstream stage's own
config (cache.py, plan §3): two configs that differ in even one field neither
stage actually reads still produce two different keys. So this uses
`Config.from_yaml()` — the exact config `swingscribe gui`/`swingscribe run`
load by default — never a bare `Config()`, whose pydantic defaults quietly
disagree with config/default.yaml in at least one field
(`beats.use_drum_stem`: code default False, yaml default True — behaviourally
identical here since beats runs before separate and so never sees a drum
stem, but the cache key cannot tell that). A bare `Config()` was this script's
first version, and it silently built separations and beat grids the live GUI
could never find under its own default cache directory — indistinguishable
from Beats never having run at all.

`cache_dir` is trickier, because it is NOT what config/default.yaml says
(`.swingscribe-cache`) resolved against any one fixed place — it is that
string resolved against whatever directory `swingscribe gui` happens to be
launched FROM, which is a habit, not a setting. Checked against a live
session on this machine: `swingscribe gui` was running with no `--library`
and no audio argument, and `/api/config` echoed back
`library_dir: .../swingscribe/benchmark` — `library.library_dir` falls back
to `Path.cwd()` exactly when neither is given, so that only makes sense if
the process's cwd IS `benchmark/`. Its cache is therefore
`benchmark/.swingscribe-cache`, not a repo-root one; an earlier version of
this script assumed the opposite (repo root) and quietly built beat grids a
GUI launched the usual way here could not find, same failure as the
`Config()` one above but from the other direction. `--cache-dir` exists in
case that launch habit ever changes — point it at wherever `swingscribe gui`
is actually being run from.
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import batch_sheet

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmark" / "wjazzd"
# Where `swingscribe gui` has actually been observed running from on this
# machine (its cwd, not the repo root) — see "Sharing a cache with the real
# GUI" above. Override with --cache-dir if that ever changes.
DEFAULT_CACHE_DIR = REPO_ROOT / "benchmark" / ".swingscribe-cache"
# ODbL is share-alike; a score built from WJazzD is a derivative of the
# database and must live outside the repo, same as scripts/wjazz_score.py's
# own default (CLAUDE.md, docs/wjazzd.md).
SCORES_DIR = REPO_ROOT.parent / "wjazz-scores"
SHEET_PATH = BENCH_DIR / "wjazzd_benchmark_test.xlsx"

sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for wjazz_score.score_name

AUDIO_GLOBS = ("*.m4a", "*.mp3", "*.wav", "*.flac")
# The trailing digits in a wjazzd filename ARE the melid — confirmed against
# every file in the folder (59 of 60; one has no number and is skipped, see
# `melid_from_filename`). Deliberately not "_solo_(\d+)$": some files carry
# the number straight after the title with no "solo" token in between
# (Cannonball_Adderley_So_What_48.m4a).
MELID_RE = re.compile(r"_(\d+)$")

# Matches scripts/run_eval.py's SOLO_MARGIN_S: enough that a bar is not
# clipped mid-phrase, small enough that a neighbouring soloist stays out.
SOLO_MARGIN_S = 1.0
# Matches score_wjazz.candidates' floor: fewer annotated notes than this and
# a content fit has nothing reliable to lock onto.
MIN_MELODY_NOTES = 50
# Matches wjazz.MIN_MATCH_RATE: below this the fit did not find the solo at
# all (chance level is 2-7%; a real match is 20%+).
MIN_MATCH_RATE = 0.15

# TWO measures, deliberately prefixed apart, because they are the two
# different questions CLAUDE.md calls this project's most expensive confusion
# — and both of them put a number called "matched" on the GUI's screen:
#
#   pitch_*     the green ground-truth bar (gui/ground_truth.py). Time-free
#               and pitch-only: DID WE HEAR THE RIGHT NOTES? Every note we
#               emitted is classified against the hand transcript as matched
#               (right pitch), wrong (a note there, wrong pitch), invented
#               (nothing there) or missed (theirs, we had nothing).
#               RAW notes, erasures deliberately NOT applied (D20, the
#               listener's ruling): silencing a note later must not change
#               the transcriber's score — the shortcoming already happened.
#   notation_*  the Score button (benchmark.score_against_notation). Are the
#               notes we got WRITTEN the way a human wrote them? It charges
#               the gap between performed timing and notated rhythm, so it
#               matches fewer notes and reads lower — always.
#
# On Maiden Voyage: 489 notes of ours against 552 of theirs, of which the
# pitch measure matches 401 and the notation measure 332. All four numbers
# are correct and none of them is "the" note count.
#
# `notes` is OURS (489). `notation_reference` is THEIRS (552) — the hand
# transcript's melody, which is also what the pitch counts are measured
# against, so pitch_matched + pitch_wrong + pitch_missed accounts for it.
#
# `notation_coverage` is the GUI's "60% lined up", NOT the value: reporting
# rhythm without it is forbidden (CLAUDE.md — rhythm on a WRONG pairing reads
# as high as 0.583). `notation_value` is here for parity with the GUI and is
# the one number to read sceptically: against a WJazzD-derived score the note
# VALUES are our own conventions applied to a human's grid
# (wjazz.annotation_notation), so it partly scores us against ourselves, and
# run_eval.py omits it. Positions and pitches are a human's, and are evidence.
HEADERS = [
    "number",
    "performer",
    "title",
    "solo_start",
    "solo_end",
    "fit_rate",
    "separation_model",
    "ensemble",
    "stem",
    "stem_dropout",
    "musicxml_written_at",
    "notes",
    "pitch_f1",
    "pitch_matched",
    "pitch_wrong",
    "pitch_invented",
    "pitch_missed",
    "notation_rhythm",
    "notation_value",
    "notation_coverage",
    "notation_matched",
    "notation_reference",
    "readability",
    "tie_rate",
    "status",
]
FIELDS = [
    "melid",
    "performer",
    "title",
    "solo_start",
    "solo_end",
    "fit_rate",
    "separation_model",
    "ensemble",
    "stem",
    "stem_dropout",
    "musicxml_written_at",
    "notes",
    "pitch_f1",
    "pitch_matched",
    "pitch_wrong",
    "pitch_invented",
    "pitch_missed",
    "notation_rhythm",
    "notation_value",
    "notation_coverage",
    "notation_matched",
    "notation_reference",
    "readability",
    "tie_rate",
    "status",
]


def melid_from_filename(path: Path) -> int | None:
    match = MELID_RE.search(path.stem)
    return int(match.group(1)) if match else None


def auto_settings(instrument: str) -> tuple[str, str]:
    """(ensemble, separation model) from the soloist's WJazzD instrument code.

    See the module docstring for the measurements behind this. There is
    never an automatic reason to pick "solo-piano": every WJazzD solo is
    from a combo recording with a rhythm section, so a piano soloist is
    always "trio", never unaccompanied.
    """
    if instrument == "p":
        return "trio", "htdemucs"
    return "horn-led", "htdemucs_6s"


def melody_rows(db: sqlite3.Connection, melid: int):
    import numpy as np

    rows = db.execute(
        "select onset, pitch from melody where melid=? order by onset", (melid,)
    ).fetchall()
    return np.array([r[0] for r in rows]), np.array([int(r[1]) for r in rows])


def time_signature_for(db: sqlite3.Connection, melid: int) -> str:
    """The annotator's majority time signature, matching wjazz.annotation_notation's
    own rule (a pickup bar can be annotated differently and must not set it)."""
    rows = db.execute("select num, denom from melody where melid=?", (melid,)).fetchall()
    counts = Counter((int(n or 4), int(d or 4)) for n, d in rows)
    num, denom = counts.most_common(1)[0][0] if counts else (4, 4)
    return f"{num}/{denom}"


def ground_truth_path(performer: str, title: str, titleaddon: str, melid: int) -> Path:
    from wjazz_score import score_name

    return SCORES_DIR / score_name(performer, title, titleaddon, melid)


def run_pipeline(audio_path: Path, config, stages):
    """pipeline.run, kept as a name for what this script means by a run.

    This used to force `document.audio_path` back to the file we asked for,
    because a cache hit restored whatever path was true when that key was
    first written — and the audio here is full of byte-identical copies under
    different names (docs/benchmark-deficiencies.md D18). `pipeline` now
    guarantees that itself for every caller, so the correction is gone rather
    than duplicated: the GUI had the same bug and did not have this wrapper.
    """
    from swingscribe import pipeline

    return pipeline.run(str(audio_path), config, stages=stages)


def ensure_ground_truth(
    db: sqlite3.Connection, melid: int, performer: str, title: str, titleaddon: str, instrument: str
) -> Path | None:
    """The hand-transcript MusicXML for this melid, writing it if it is not
    already there. Mirrors scripts/wjazz_score.py exactly — same builder, same
    writer — rather than a second copy of either (CLAUDE.md)."""
    from swingscribe.stages.export import to_musicxml
    from swingscribe.wjazz import annotation_notation

    path = ground_truth_path(performer, title, titleaddon, melid)
    if path.is_file():
        return path
    notation = annotation_notation(db, melid)
    if notation is None or not notation.bars:
        return None
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(to_musicxml(notation, part_name=instrument or "Solo"), encoding="utf-8")
    return path


def process_file(
    db: sqlite3.Connection,
    audio_path: Path,
    cache_dir: Path,
    log=print,
    fresh: bool = False,
) -> dict:
    """Run the GUI workflow end to end for one wjazzd audio file.

    Always returns a dict keyed by FIELDS. On any failure `status` explains
    why and the data columns are left blank rather than raising — one bad
    file must not stop a batch of ten.
    """
    row: dict = dict.fromkeys(FIELDS, "")

    melid = melid_from_filename(audio_path)
    if melid is None:
        row["status"] = "no melid number in filename — skipped (name it, or process by hand)"
        return row

    info = db.execute(
        "select performer, title, titleaddon, instrument from solo_info where melid=?", (melid,)
    ).fetchone()
    if info is None:
        row["melid"] = melid
        row["status"] = f"melid {melid} is not in solo_info — skipped"
        return row
    performer, title, titleaddon, instrument = info
    titleaddon = titleaddon or ""
    row.update(melid=melid, performer=performer, title=title)

    ref_on, ref_p = melody_rows(db, melid)
    if len(ref_on) < MIN_MELODY_NOTES:
        row["status"] = f"only {len(ref_on)} annotated notes for melid {melid} — too few to locate"
        return row

    ensemble, model = auto_settings(instrument)
    row["ensemble"], row["separation_model"] = ensemble, model

    from swingscribe import wjazz
    from swingscribe.config import Config
    from swingscribe.gui import ground_truth, library, review
    from swingscribe.gui.musicxml import NotReady, export_span, score_span
    from swingscribe.stages import beats, ingest, separate, transcribe

    # Config.from_yaml(), not a bare Config(): see "Sharing a cache with the
    # real GUI" in the module docstring for why the two are not the same
    # config and must not be, here, ever produce different cache keys.
    base = Config.from_yaml()
    base = base.model_copy(
        update={
            "cache_dir": cache_dir,
            "separate": base.separate.model_copy(update={"model": model}),
            "transcribe": base.transcribe.model_copy(
                update={"ensemble": ensemble, "stem": "other"}
            ),
        }
    )
    prep_stages = [("ingest", ingest.run), ("beats", beats.run), ("separate", separate.run)]
    stage_list = [*prep_stages, ("transcribe", transcribe.run)]

    # ingest+beats+separate alone first, purely to learn the file's duration:
    # transcribe.analyze's own progress log can't format a None region end, so
    # the "whole file" pass below needs an explicit number, not None.
    prepared = run_pipeline(audio_path, base, prep_stages)
    duration = prepared.audio.duration

    # Pass 1: whole file, so the solo can be located by content.
    wide = base.model_copy(
        update={"transcribe": base.transcribe.model_copy(update={"region": (0.0, duration)})}
    )
    log(
        f"  [{melid}] {performer} - {title} ({instrument}): pass 1 — whole file, {model}/{ensemble}"
    )
    started = time.time()
    document = run_pipeline(audio_path, wide, stage_list)
    notes = document.notes.get("other", [])
    log(f"  [{melid}] pass 1: {len(notes)} notes in {time.time() - started:.0f}s")
    if not notes:
        row["status"] = "transcribed zero notes in the whole file — check separation/ensemble"
        return row

    import numpy as np

    order = np.argsort([n.onset for n in notes])
    est_on = np.array([notes[i].onset for i in order])
    est_p = np.array([notes[i].pitch for i in order])

    offset, rate, hits = wjazz.fit_affine(ref_on, ref_p, est_on, est_p, (0.0, duration))
    match_rate = hits / len(ref_on)
    # Recorded before the gate, so a rejected row still shows the rate it was
    # rejected at. A rate sitting AT wjazz.RATE_LOW/RATE_HIGH is a confession:
    # the true rate is outside the clamp and every number scored against that
    # drifting clock is suspect (docs/benchmark-deficiencies.md D19).
    row["fit_rate"] = round(rate, 5)
    if match_rate < MIN_MATCH_RATE:
        row["status"] = (
            f"best fit only matched {match_rate:.0%} of melid {melid}'s notes — wrong file/take?"
        )
        return row

    solo_start = float(ref_on[0] * rate + offset)
    solo_end = float(ref_on[-1] * rate + offset)
    region = (max(0.0, solo_start - SOLO_MARGIN_S), min(duration, solo_end + SOLO_MARGIN_S))
    row["solo_start"] = round(solo_start, 3)
    row["solo_end"] = round(solo_end, 3)

    # The downbeat ANCHOR, from the annotator's own bar lines. In the GUI the
    # listener places it by hand; without one, bar 1's phase is whatever the
    # located span start happens to be modulo the bar — Don't Blame Me came
    # out one beat off, every note in the wrong place in its bar, and the
    # interval-based rhythm measure is immune to a constant shift BY DESIGN,
    # so nothing scored it. WJazzD marks every note's bar and beat, so any
    # note the annotator put ON a downbeat, mapped through the fit, IS a
    # downbeat in our timeline (notation.section_for treats the anchor as a
    # phase, so any downbeat serves). The one nearest the span start wins.
    downbeats = [
        float(onset) * rate + offset
        for (onset,) in db.execute(
            "select onset from melody where melid=? and beat=1 and tatum=1 order by onset",
            (melid,),
        )
    ]
    anchor = min(downbeats, key=lambda t: abs(t - solo_start)) if downbeats else None
    log(
        f"  [{melid}] located at offset {offset:+.2f}s rate {rate:.4f}, matched {match_rate:.0%}"
        f" -> region {region[0]:.1f}-{region[1]:.1f}s"
    )

    # Pass 2: narrowed to the located solo, through the GUI's OWN review path.
    #
    # `review.span_config` rather than a region set by hand, and
    # `review.analyze_and_cache` rather than the pipeline's transcribe stage,
    # so that what lands in the spreadsheet is the same computation the Score
    # button reports -- see "Matching the GUI exactly" in the module docstring.
    # It also populates the review cache under the GUI's own key, so opening
    # this track shows the notes with no Transcribe click and no second CREPE
    # pass.
    # WHICH stem carries the solo is decided here, over the located span, from
    # the audio alone. Demucs switches a source it cannot place between stems
    # rather than attenuating it across them, so `other` can be digitally
    # silent for a third of a solo while the horn plays on in `vocals` — Oleo
    # transcribed 106 notes against WJazzD's 224 that way, and nothing
    # reported an error. Reference-free on purpose: choosing by which stem
    # scores better against the annotation would report a best-of-two as the
    # transcriber's own number (see library.choose_stem).
    stem, dropout = library.choose_stem(prepared, base, model, region, preferred="other")
    row["stem"] = stem
    row["stem_dropout"] = round(dropout.get("other", 0.0), 3)
    if stem != "other":
        log(
            f"  [{melid}] 'other' is silent for {dropout['other']:.0%} of the span — "
            f"transcribing {stem} ({dropout[stem]:.0%})"
        )

    run_config = review.span_config(base, stem, region[0], region[1], ensemble)
    region = run_config.transcribe.region  # rounded; the sidecar must store THIS
    started = time.time()
    payload = None if fresh else review.cached_review(prepared, run_config, model)
    payload = payload or review.analyze_and_cache(prepared, run_config, model)
    note_dicts = payload["notes"]
    row["notes"] = len(note_dicts)  # recorded even if scoring later fails
    log(f"  [{melid}] pass 2: {len(note_dicts)} notes in {time.time() - started:.0f}s")
    if not note_dicts:
        row["status"] = "narrowed pass produced zero notes"
        return row

    score_path = ensure_ground_truth(db, melid, performer, title, titleaddon, instrument)
    # The sidecar is written BEFORE notating, because the GUI reads its
    # settings back through `library.load_settings` and so must this: the
    # time signature and transposition on it are inputs to the page.
    library.save_settings(
        str(audio_path),
        {
            "model": model,
            "ensemble": ensemble,
            "stem": stem,
            "region": list(region),
            # The batch computes a beat grid (prep_stages runs `beats`), so
            # the track should open showing it. Without this the work is done
            # and invisible, which reads as "the batch did not make beats".
            "beats_shown": True,
            "time_signature": time_signature_for(db, melid),
            "anchor": anchor,
            "transposition": "C",
            "score": str(score_path) if score_path else None,
            "melid": melid,
        },
        base,
    )
    settings = library.load_settings(str(audio_path), base, library.file_digest(str(audio_path)))

    try:
        exported = export_span(prepared, base, run_config, str(audio_path), note_dicts, settings)
    except NotReady as exc:
        row["status"] = f"export failed: {exc}"
        return row
    row["musicxml_written_at"] = datetime.now().isoformat(timespec="seconds")
    # Reference-free: a property of the page itself (benchmark.readability),
    # so it exists for every exported row, hand transcript or not. This is
    # the number that tracks the listener's actual complaints — a human's
    # own pages read 0.995 with tie rate 0.022.
    row["readability"] = exported["readability"]
    row["tie_rate"] = exported["tie_rate"]

    if score_path is None:
        row["status"] = (
            "wrote musicxml; no hand transcript could be built for this melid "
            "(no metrical annotation)"
        )
        return row

    try:
        result = score_span(
            prepared, base, run_config, str(audio_path), note_dicts, settings, score_path
        )
    except NotReady as exc:
        row["status"] = f"wrote musicxml; scoring failed: {exc}"
        return row

    row["notation_rhythm"] = result["rhythm"]
    row["notation_value"] = result["value"]
    row["notation_coverage"] = result["coverage"]
    row["notation_matched"] = result["matched"]
    row["notation_reference"] = result["reference"]

    # The OTHER measure: the green ground-truth bar. Same call the GUI's
    # /ground-truth endpoint makes, including the cache, so the counts are
    # the ones on screen rather than a second opinion about them. Its own
    # try/except: a failure here must not throw away the notation numbers
    # already in hand.
    try:
        low, high = run_config.transcribe.region
        overlay = ground_truth.cached_overlay(
            base,
            review.review_key(prepared, run_config, model),
            score_path,
            note_dicts,
            low or 0.0,
            prepared.audio.duration if high is None else high,
        )
        counts = overlay["counts"]
        row["pitch_f1"] = overlay["pitch_f1"]
        row["pitch_matched"] = counts["matched"]
        row["pitch_wrong"] = counts["wrong"]
        row["pitch_invented"] = counts["invented"]
        row["pitch_missed"] = counts["missed"]
    except Exception as exc:  # noqa: BLE001 — one measure failing is not the row failing
        log(f"  [{melid}] ground-truth counts unavailable: {type(exc).__name__}: {exc}")
    row["status"] = (
        "ok"
        if result["trusted"]
        else f"ok — low coverage ({result['coverage']:.2f}), rhythm untrusted"
    )
    return row


# ── the spreadsheet ──────────────────────────────────────────────────────────


# The machinery lives in batch_sheet.py, shared with benchmark_batch.py —
# one copy of the migration, Excel-Table sync and lock handling, because
# every one of those was found the hard way (see that module's docstring).


def save_sheet(wb, ws) -> None:
    batch_sheet.save_sheet(wb, ws, SHEET_PATH, HEADERS)


def load_or_create_sheet(db: sqlite3.Connection):
    seed = (
        {"number": melid, "performer": performer, "title": title}
        for melid, performer, title in db.execute(
            "select melid, performer, title from solo_info order by melid"
        )
    )
    return batch_sheet.load_or_create_sheet(SHEET_PATH, HEADERS, "wjazzd", seed_rows=seed)


def melid_row_index(ws) -> dict[int, int]:
    """melid -> 1-based worksheet row. Coerced to int: openpyxl can hand a
    numeric cell back as int or float depending on how it was written."""
    return {int(key): row for key, row in batch_sheet.row_index(ws).items()}


def write_row(ws, index: dict[int, int], row: dict) -> None:
    """Update exactly this melid's row, leaving every other row untouched."""
    melid = row.get("melid")
    batch_sheet.write_row(ws, index, int(melid) if melid else None, row, FIELDS)


# ── file selection & CLI ─────────────────────────────────────────────────────


def all_audio_files() -> list[Path]:
    found: set[Path] = set()
    for pattern in AUDIO_GLOBS:
        found.update(BENCH_DIR.glob(pattern))
    return sorted(found)


def select_files(args) -> list[Path]:
    available = all_audio_files()
    if args.file:
        by_name = {p.name: p for p in available}
        chosen = []
        for name in args.file:
            if name in by_name:
                chosen.append(by_name[name])
            else:
                print(f"  (not found in benchmark/wjazzd) {name}")
        return chosen
    if args.random:
        import random

        return random.sample(available, min(args.random, len(available)))
    if args.all:
        return available
    return available[: args.limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, required=True, help="wjazzd.db")
    parser.add_argument("--limit", type=int, default=None, help="first N files, alphabetically")
    parser.add_argument(
        "--file", action="append", default=[], help="one exact filename; repeatable"
    )
    parser.add_argument("--random", type=int, default=None, help="N files chosen at random")
    parser.add_argument("--all", action="store_true", help="every audio file in benchmark/wjazzd")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "re-run CREPE instead of reusing a cached review. Separation and the "
            "beat grid are still reused — they are minutes each and a cached stem "
            "is bit-identical to the one that made it. Use this after changing "
            "transcribe's behaviour without changing its config."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=(
            "Must match wherever `swingscribe gui` is actually launched from + "
            f".swingscribe-cache, or its cache and this script's are two different "
            f"places (default: {DEFAULT_CACHE_DIR} — see the module docstring)"
        ),
    )
    args = parser.parse_args()
    if not (args.limit or args.file or args.random or args.all):
        parser.error("pick one: --limit N, --file NAME (repeatable), --random N, or --all")

    # Run from the directory the CACHE belongs to, which is where the GUI runs
    # from — see "Standing where the cache expects" in the module docstring.
    # Everything this script touches is absolute already; `--db` is the one
    # path a caller gives relative to their own shell, so resolve it first.
    db_path = args.db.resolve()
    cache_dir = args.cache_dir.resolve()
    os.chdir(cache_dir.parent)

    db = sqlite3.connect(db_path)
    files = select_files(args)
    if not files:
        print("Nothing to do — no matching audio in benchmark/wjazzd.")
        return

    print(f"Processing {len(files)} file(s): {', '.join(p.name for p in files)}")
    print(f"Cache: {cache_dir}   (running from {Path.cwd()})")
    wb, ws = load_or_create_sheet(db)
    index = melid_row_index(ws)

    for audio_path in files:
        print(f"\n== {audio_path.name} ==")
        row = process_file(db, audio_path, cache_dir, fresh=args.fresh)
        write_row(ws, index, row)
        save_sheet(wb, ws)  # after every file: a crash mid-batch loses nothing already done
        print(f"  -> {row['status'] or 'ok'}")

    print(f"\nSpreadsheet: {SHEET_PATH}")


if __name__ == "__main__":
    main()
