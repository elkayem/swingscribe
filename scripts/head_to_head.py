"""The head-to-head: other transcribers against ours, on identical audio.

    uv run python scripts/head_to_head.py --plan          --excerpt 29
    uv run python scripts/head_to_head.py --export-audio  --excerpt 29
    uv run python scripts/head_to_head.py --write-ours    --excerpt 29
    uv run python scripts/head_to_head.py --score         --excerpt 29
    uv run python scripts/head_to_head.py --control

docs/head-to-head.md is the protocol: which spans, what each tool is told,
what to export and where to drop it. This script is its three moving
parts, and its one control.

**The audio.** `--export-audio` cuts every span of the three sets (the
listener's twelve hand-scored solos, the silver PDF pages, a frozen subset
of WJazzD solos) out of the recording, or out of the stem SwingScribe
transcribed with `--source stem`, into
`benchmark/head_to_head/<condition>/audio/<set>/<name>.wav`, beside a
`manifest.json` that every later step reads and a `settings.csv` the
listener clicks through. `--excerpt 29` keeps the first 29 seconds of each
span: AnthemScore's trial transcribes "the first 30 seconds of each song"
(`--excerpt 19` for Klangio's 20-second demo; docs/head-to-head.md).
Nothing here may be committed; benchmark/ is gitignored for exactly this.

**Scoring.** A tool's outputs go in `<condition>/<tool>/<set>/<name>` as
`.musicxml` (or `.xml`, `.mxl`) and, where it can, `.mid`. The page is read
into a Notation by `swingscribe.external` and scored by the functions our
own pages are scored by, called the way `run_eval` calls them: the time-free
alignment, notated rhythm and value with their coverage, readability, the
bar-line agreement, the edit cost. The timed notes -- the MIDI file, or the
page at its own tempo marking when there is none -- are scored the way the
MuseScore set scores our transcription (`score_benchmark.score_tune`) and
the way WJazzD scores it (`score_wjazz.candidates` then `score`). Timed
notes are scored AS DELIVERED, ours included: `--top-line` reduces every
tool's to its top line instead, as a sensitivity reading. Note F1 is
paired only between rows timed by PERFORMED onsets: timed off a page (its
tempo marking, or a MIDI file written from it, which `external.midi_timing`
catches -- and a MIDI whose clock cannot say is not paired either) it
measures the writing, not the hearing -- measured on pseudo-tools with
identical notes (docs/head-to-head.md section 8). Pitch F1, which reads no
time, is read off the PAGE's line wherever both sides wrote a page (one
line by the reference reader's rule, whatever else a tool's MIDI holds),
else off both sides' timed notes; `pitch_f1_timed` is the notes as
delivered, beside it.

**SwingScribe is a tool like the others.** `--write-ours` writes our page
(the harness's notes and grid through `notation_for_span` and
`export.to_musicxml`) and our notes (a MIDI file) into
`<condition>/swingscribe/`, and `--score` reads them back by the path every
competitor takes (`--page-variant` also writes `swingscribe-page/`, the
page alone with a tempo marking: the pseudo-tool that measured what timing
a page costs). The paired intervals (`evaluation.paired_change`) are
against that baseline, on the tracks both tools hold. By default our page is built with
NO sidecar downbeat (`--downbeat auto`), because no other tool is given one
(on the current thirty spans the automatic downbeat has the sidecar's
phase on all 21 that carry one, so this costs us nothing measurable).

**Stale notes are refused.** Our baseline is the harness's notes cache,
and that cache is only ever right for the transcriber that wrote it:
`run_eval` re-transcribes a run whose fingerprint
(`run_eval.transcribe_fingerprint`) no longer matches the code, and so
does this -- `--write-ours` refuses to write a span whose cached notes the
running transcriber would not produce (run `scripts/run_eval.py` first;
`--allow-stale` writes them anyway and says so in `tool.json`), and
`tool.json` records every span's fingerprint, which `--score` checks
against the cache it crops the references with.

**The control.** `--control` writes our pages with the sidecar settings the
pins were made with, full spans, scores them through the external path, and
compares every number with `tests/regression/real-audio-baselines.json`. A
path that did not reproduce our own pins could not be trusted with anyone
else's page. It then scores the same pages through the EXCERPT machinery
with the window set to the whole span -- the reference cut on our
alignment, WJazzD refitted over the window -- which is the end-to-end check
of the crop: the paired table is fair whatever it reads, but it says how
far an excerpt's absolute numbers sit from a pin's. It also scores the
pages the GUI's Export wrote beside the audio (benchmark/*.musicxml), which
are expected NOT to match: they are older exports, with the listener's
erasures.

Run it from the repo root. It reads the harness's caches and never writes
them; point `--notes`/`--grids`/`--pins` at snapshots while another run is
rewriting them.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BENCH = Path("benchmark")
ROOT = BENCH / "head_to_head"
SETS = ("hand", "silver", "wjazzd")
BASELINE = "swingscribe"
# AnthemScore's trial and Songscription's free tier stop at 30 seconds of a
# file; a second short of that, so no tool cuts the last note of a span.
TRIAL_EXCERPT_S = 29.0
AUDIO_DIR = "audio"
MANIFEST = "manifest.json"
PAGE_SUFFIXES = (".musicxml", ".xml", ".mxl")
MIDI_SUFFIXES = (".mid", ".midi")
# The notes cache's decode settings: run_eval's defaults, and what
# `run_eval.notes_cache(0.2, 0.0)` names. A cached run is ours only if
# `run_eval.transcribe_fingerprint` under these still matches it.
STEP_COST = 0.2
DIP_DB = 0.0
# Where the pins' stems live: the batch's cache, where a span-scoped
# Roformer separation lands (run_eval's CACHE_DIR comment, CLAUDE.md). The
# stem condition must hand a tool the stem our notes were transcribed from.
STEM_CACHE = BENCH / ".swingscribe-cache"

# The WJazzD solos every tool is run on: fifteen of the 73 dev solos, frozen
# so the set never moves when the benchmark grows. Chosen by
# `choose_wjazz_subset` on 2026-09-30 (docs/head-to-head.md): one solo per
# recording, tunes already in the page sets left out, (instrument, tempo
# class) cells filled first in a salted-hash order nobody picked.
WJAZZ_SUBSET: tuple[str, ...] = (
    "Charlie_Parker_Blues_For_Alice_solo_53",
    "Charlie_Parker_Donna_Lee_solo_55",
    "Charlie_Parker_Dont_Blame_Me_solo_54",
    "Chet_Baker_I_Fall_In_Love_Too_Easily_solo_70",
    "Chet_Baker_Lets_Get_Lost_solo_72",
    "JJ_Johnson_Crazy_Rhythm_solo_192",
    "JJ_Johnson_Yesterdays_solo_197",
    "John_Coltrane_My_Favorite_Things_solo_228",
    "Miles_Davis_Walkin_solo_327",
    "Pat_Metheny_Nothing_Personal_solo_345",
    "Red_Garland_Oleo_solo_365",
    "Sidney_Bechet_Limehouse_Blues_solo_375",
    "Wayne_Shorter_Adams_Apple_solo_426",
    "Wayne_Shorter_Dolores_solo_427",
    "Wynton_Marsalis_Cherokee_solo_446",
)
WJAZZ_SUBSET_SIZE = 15
SUBSET_SALT = "head-to-head"

# Who plays on the hand-scored and silver tracks, for the settings sheet
# (a tool is told the instrument, as SwingScribe's sidecar tells it the
# ensemble). By name, because no sidecar field says which horn it is.
PERFORMERS = {
    "Art_Pepper": "alto saxophone",
    "Dexter_Gordon": "tenor saxophone",
    "Dexter Gordon": "tenor saxophone",
    "Hank_Mobley": "tenor saxophone",
    "Charlie-Parker": "alto saxophone",
    "Wayne Shorter": "tenor saxophone",
}
WJAZZ_INSTRUMENTS = {
    "as": "alto saxophone",
    "ts": "tenor saxophone",
    "ss": "soprano saxophone",
    "bs": "baritone saxophone",
    "tp": "trumpet",
    "cor": "cornet",
    "tb": "trombone",
    "cl": "clarinet",
    "bcl": "bass clarinet",
    "p": "piano",
    "g": "guitar",
    "vib": "vibraphone",
    "fl": "flute",
}

# measure -> (the row it lives in, lower is better, withheld below the
# coverage floor, read in time). The third column is CLAUDE.md's rule:
# never show notated rhythm without its coverage, because a wrong pairing
# reads 0.58. The last marks a HEARING measure read in time: it is paired
# only between rows timed by performed onsets (a MIDI file not written from
# a page). Timed off a page it measures the writing: two pseudo-tools with
# IDENTICAL notes, one written literally, differ by -0.094 on the hand set
# and +0.032 on WJazzD when both are timed off their pages, and by exactly
# 0 from their MIDI (docs/head-to-head.md section 8).
MEASURES = {
    "pitch_f1": ("notes", False, False, False),
    "pitch_f1_timed": ("notes", False, False, False),
    "note_f1": ("notes", False, False, True),
    "coverage": ("page", False, False, False),
    "rhythm": ("page", False, True, False),
    "value": ("page", False, True, False),
    "readability": ("page", False, False, False),
    "on_the_bar": ("page", False, True, False),
    "edit_cost": ("page", True, True, False),
}
# Pitch F1 is read off the same KIND of output on both sides: the page's
# line where both wrote a page -- one line, by the reference reader's rule
# -- else both sides' timed notes. A tool's MIDI of the whole mix (a piano
# texture, the band) against our one separated line would charge the
# separation to the hearing; `pitch_f1_timed` shows that reading beside it.
PITCH_SOURCES = {"pitch_f1": ("pitch_f1_page", "pitch_f1_timed")}
# A row's timing: performed onsets from a MIDI file, a MIDI file written
# from a page (most onsets on a 24th grid), a MIDI file whose clock cannot
# say which (`external.midi_timing`), or the page at its own tempo.
PERFORMED = "midi"
QUANTIZED = "midi, on a grid"
UNREAD = "midi, clock unread"
PAGE_TIMING = "page tempo"
# `--write-ours --page-variant` also writes our page alone, with a tempo
# marking and no MIDI, into `<baseline>-page`: the pseudo-tool of section 8.
PAGE_VARIANT = "-page"
SET_MEASURES = {
    "hand": tuple(MEASURES),
    "silver": tuple(MEASURES),
    # Flex-Q's tatum is not a page (CLAUDE.md, D36): WJazzD judges hearing,
    # the page's readability and where its bar lines are, never its rhythm.
    # Pitch F1 is the annotation's pitch sequence against the line, the
    # aligner's time-free call: a page-only tool's hearing measure here.
    "wjazzd": ("pitch_f1", "pitch_f1_timed", "note_f1", "coverage", "readability", "on_the_bar"),
}


def run_eval_module():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import run_eval

    return run_eval


# ── what gets run ────────────────────────────────────────────────────────────


def condition_name(source: str, excerpt: float | None) -> str:
    """The folder a condition lives in: what the tools were given."""
    return f"{source}-{'full' if excerpt is None else f'excerpt{excerpt:g}s'}"


def window(region: tuple[float, float], excerpt: float | None) -> tuple[float, float]:
    """The audio a tool is given: the span, or its first `excerpt` seconds."""
    low, high = float(region[0]), float(region[1])
    return (low, high) if excerpt is None else (low, min(high, low + excerpt))


def _hash(name: str) -> str:
    return hashlib.sha256(f"{SUBSET_SALT}\x00{name}".encode()).hexdigest()


def choose_wjazz_subset(rows: list[dict], size: int = WJAZZ_SUBSET_SIZE) -> list[str]:
    """`size` WJazzD solos, one per recording, spread over the cells.

    `rows` carry `name`, `title`, `instrument` and `tempoclass`. In an order
    no one chose (a salted hash of the name): first every solo that opens a
    new (instrument, tempo class) cell with a recording not yet taken, then
    any solo of a recording not yet taken, until `size`. One solo per
    recording because the solos of one recording are not independent draws
    (`run_eval.recording_of`) and the paired intervals resample recordings.
    """
    from swingscribe.evaluation import normalize_title

    ordered = sorted(rows, key=lambda r: _hash(r["name"]))
    chosen: list[str] = []
    titles: set[str] = set()
    cells: set[tuple] = set()
    for fill_cells in (True, False):
        for row in ordered:
            if len(chosen) >= size:
                break
            title = normalize_title(row["title"])
            cell = (row["instrument"], row["tempoclass"])
            if row["name"] in chosen or title in titles or (fill_cells and cell in cells):
                continue
            chosen.append(row["name"])
            titles.add(title)
            cells.add(cell)
    return sorted(chosen)


def wjazz_candidates(pins: dict, db, page_names: set[str]) -> list[dict]:
    """Every pinned default-take WJazzD solo, with the fields the subset rule
    reads -- less any whose tune title is inside a page set's track name
    (Giant Steps is Flanagan's hand score AND two Coltrane solos in WJazzD,
    on one recording)."""
    from swingscribe.evaluation import normalize_title

    rows = []
    for key in pins:
        if not (key.startswith("wjazz/") and key.endswith("/melid")):
            continue
        name = key[len("wjazz/") : -len("/melid")]
        if " [" in name:
            continue
        found = db.execute(
            "select title, instrument, tempoclass from solo_info where melid=?", (int(pins[key]),)
        ).fetchone()
        if not found or any(normalize_title(found[0]) in page for page in page_names):
            continue
        rows.append(
            {"name": name, "title": found[0], "instrument": found[1], "tempoclass": found[2]}
        )
    return rows


def _reference_meter(path: Path) -> str:
    from swingscribe import mscz

    beats = mscz.parse_any(path).beats_per_bar
    return f"{beats:g}/4"


def _instrument(name: str, sidecar: dict) -> str:
    if (sidecar.get("ensemble") or "") in ("trio", "solo-piano"):
        return "piano"
    for performer, instrument in PERFORMERS.items():
        if performer in name:
            return instrument
    return "horn (see docs/head-to-head.md)"


def build_entries(sets, pins: dict, runs: dict, db, log=print) -> list[dict]:
    """Every span of the chosen sets, dev split only."""
    run_eval = run_eval_module()
    import score_benchmark

    from swingscribe.evaluation import load_split, normalize_title

    split = load_split(run_eval.SPLIT_FILE) if run_eval.SPLIT_FILE.is_file() else None
    entries: list[dict] = []
    # Every hand-scored and silver track's name, normalised: a WJazzD solo
    # on a tune these already hold is left out of the WJazzD set.
    page_names: set[str] = set()

    def sidecar_of(track: str) -> dict:
        return json.loads((BENCH / f"{track}.swingscribe.json").read_text(encoding="utf-8"))

    for key, (audio, reference, title, _instrument_kind) in sorted(score_benchmark.TUNES.items()):
        folder = Path(audio).parent.as_posix()
        if folder == ".":
            kind = "hand"
        elif run_eval.is_page(audio):
            kind = "silver"
        else:
            continue
        sidecar = sidecar_of(audio)
        page_names.add(normalize_title(title))
        if kind == "silver" and run_eval.page_quality(BENCH / reference)[0] != "silver":
            continue
        if kind not in sets:
            continue
        if split is not None and run_eval.held_out(audio, sidecar, split, db):
            log(f"  {audio}: test split, held out")
            continue
        region = runs[audio]["region"] if audio in runs else sidecar["region"]
        entries.append(
            {
                "set": kind,
                "name": run_eval.pin_name(audio),
                "run": audio,
                "track": audio,
                "tune_key": key,
                "reference": reference,
                "melid": None,
                "region": [float(region[0]), float(region[1])],
                "fit_region": None,
                "ensemble": sidecar.get("ensemble"),
                "instrument": _instrument(audio, sidecar),
                "time_signature": sidecar.get("time_signature")
                or _reference_meter(BENCH / reference),
            }
        )
    if "wjazzd" in sets:
        if db is None:
            raise SystemExit("the wjazzd set needs --db (wjazz/wjazzd.db)")
        names = WJAZZ_SUBSET or tuple(choose_wjazz_subset(wjazz_candidates(pins, db, page_names)))
        from swingscribe.wjazz import notated_beats

        for name in names:
            matches = sorted((BENCH / "wjazzd").glob(f"{name}.*.swingscribe.json"))
            if not matches:
                log(f"  wjazzd/{name}: no sidecar on disk, skipped")
                continue
            sidecar = json.loads(matches[0].read_text(encoding="utf-8"))
            track = f"wjazzd/{sidecar['file']}"
            start, end = pins.get(f"wjazz/{name}/solo_start"), pins.get(f"wjazz/{name}/solo_end")
            if start is None or end is None:
                log(f"  {track}: no located solo in the pins, skipped")
                continue
            melid = int(pins[f"wjazz/{name}/melid"])
            instrument = db.execute(
                "select instrument from solo_info where melid=?", (melid,)
            ).fetchone()[0]
            margin = run_eval.SOLO_MARGIN_S
            fit = runs[track]["region"] if track in runs else sidecar["region"]
            _positions, bar = notated_beats(db, melid)
            entries.append(
                {
                    "set": "wjazzd",
                    "name": name,
                    "run": track,
                    "track": track,
                    "tune_key": None,
                    "reference": None,
                    "melid": melid,
                    "region": [round(start - margin, 3), round(end + margin, 3)],
                    "fit_region": [float(fit[0]), float(fit[1])],
                    "ensemble": sidecar.get("ensemble"),
                    "instrument": WJAZZ_INSTRUMENTS.get(instrument, instrument),
                    "time_signature": f"{bar:g}/4" if bar else "4/4",
                }
            )
    return sorted(entries, key=lambda e: (SETS.index(e["set"]), e["name"]))


def with_windows(entries: list[dict], excerpt: float | None) -> list[dict]:
    return [{**e, "window": list(window(e["region"], excerpt))} for e in entries]


# ── the audio every tool is given ────────────────────────────────────────────


def _decode(path: Path, cache_dir: Path):
    """(samples, rate, how) for a whole recording, decoded the way ingest
    decodes it: the cached normalized wav when the cache still holds it,
    else soundfile, else ffmpeg. Seconds are the same in all three."""
    import soundfile

    from swingscribe.stages.ingest import find_ffmpeg

    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    cached = sorted((cache_dir / "audio").glob(f"{digest}-*.wav"))
    if cached:
        data, rate = soundfile.read(str(cached[0]), dtype="float32", always_2d=True)
        return data, rate, f"ingest cache {cached[0].name}"
    try:
        data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
        return data, rate, "soundfile"
    except Exception:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise SystemExit(f"cannot decode {path}: no ffmpeg (CLAUDE.md, this machine)") from None
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "decoded.wav"
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(path), str(out)], check=True
            )
            data, rate = soundfile.read(str(out), dtype="float32", always_2d=True)
        return data, rate, "ffmpeg"


def _stem_path(entry: dict, cache_dir: Path, run: dict | None = None) -> Path:
    """The stem SwingScribe transcribed this span from, resolved as run_eval
    resolves it (library.resolve_stem, span-scoped sets included) in the
    cache the pins were run against (`STEM_CACHE` unless `--cache-dir`),
    and checked against the model and stem the cached run records."""
    from swingscribe.gui import library

    run_eval = run_eval_module()
    sidecar = json.loads((BENCH / f"{entry['track']}.swingscribe.json").read_text(encoding="utf-8"))
    base = run_eval.eval_config().model_copy(update={"cache_dir": cache_dir})
    settings = run_eval.transcribe_settings(sidecar, STEP_COST, DIP_DB)
    if run is not None and (run.get("model"), run.get("stem")) != (sidecar["model"], settings.stem):
        raise SystemExit(
            f"{entry['track']}: the cached notes were transcribed from {run.get('stem')!r} of "
            f"{run.get('model')!r}, the sidecar now names {settings.stem!r} of "
            f"{sidecar['model']!r}: re-run scripts/run_eval.py first"
        )
    config = base.model_copy(
        update={
            "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
            "transcribe": settings,
        }
    )
    document = library.ingested_document(BENCH / entry["track"], config)
    stem = library.resolve_stem(document, config, sidecar["model"], settings.stem)
    if stem is None:
        raise SystemExit(
            f"{entry['track']}: no {settings.stem!r} stem of {sidecar['model']} under "
            f"{cache_dir} (the pins' stems are under {STEM_CACHE}; see --cache-dir)"
        )
    return Path(stem)


def export_audio(
    entries: list[dict],
    folder: Path,
    source: str,
    cache_dir: Path,
    runs: dict | None = None,
    log=print,
):
    """Cut every span to a wav, and write the manifest and settings sheet."""
    import soundfile

    out = []
    for entry in entries:
        if source == "stem":
            stem = _stem_path(entry, cache_dir, (runs or {}).get(entry["run"]))
            data, rate = soundfile.read(str(stem), dtype="float32", always_2d=True)
            how = f"stem {stem.parent.name}/{stem.name} in {cache_dir}"
        else:
            data, rate, how = _decode(BENCH / entry["track"], cache_dir)
        low, high = entry["window"]
        clip = data[int(round(low * rate)) : int(round(high * rate))]
        target = folder / AUDIO_DIR / entry["set"] / f"{entry['name']}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(target), clip, rate, subtype="PCM_16")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        out.append(
            {
                **entry,
                "wav": target.relative_to(folder).as_posix(),
                "wav_sha256": digest,
                "sample_rate": rate,
                "seconds": round(len(clip) / rate, 3),
                "decoded_from": how,
            }
        )
        log(f"  {entry['set']}/{entry['name']}: {len(clip) / rate:.1f} s ({how})")
    write_manifest(folder, out)
    with open(folder / "settings.csv", "w", newline="", encoding="utf-8") as sheet:
        writer = csv.writer(sheet)
        writer.writerow(
            ["set", "wav", "seconds", "instrument", "time signature", "swing", "tempo", "save as"]
        )
        for entry in out:
            writer.writerow(
                [
                    entry["set"],
                    entry["wav"],
                    entry["seconds"],
                    entry["instrument"],
                    entry["time_signature"],
                    "on (if offered)",
                    "detect (no hint)",
                    f"<tool>/{entry['set']}/{entry['name']}.musicxml and .mid",
                ]
            )
    return out


def write_manifest(folder: Path, entries: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MANIFEST).write_text(json.dumps(entries, indent=2), encoding="utf-8")


def load_entries(folder: Path, build, log=print) -> list[dict]:
    """The manifest the audio was cut from, or -- no audio cut yet -- the
    entries as they would be cut now."""
    path = folder / MANIFEST
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    log(f"  no {path}: using the spans as they would be cut now")
    return build()


# ── our own outputs, as a tool ───────────────────────────────────────────────


def our_page(entry: dict, run: dict, grid: dict, region, drop_anchor: bool):
    """(Notation, the repaired beat grid it is built on) for one span:
    `run_eval.notate_run`, with the sidecar's own downbeat left out when
    `drop_anchor` (no competitor is given one)."""
    from swingscribe.model import NoteEvent
    from swingscribe.notation import bar_grid_for_settings, meter_from_settings, notation_for_span

    run_eval = run_eval_module()
    track = entry["track"]
    config = run_eval.eval_config()
    path = BENCH / f"{track}.swingscribe.json"
    sidecar = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if drop_anchor:
        sidecar = {**sidecar, "anchor": None}
    raw = grid["beats"]
    beats, anchor = bar_grid_for_settings(
        raw, grid.get("downbeats", []), sidecar, config, grid.get("duration") or raw[-1]
    )
    signature, pulses = meter_from_settings(
        sidecar.get("time_signature"), sidecar.get("pulses_per_bar"), config
    )
    notation = notation_for_span(
        str(BENCH / track),
        [
            NoteEvent(
                onset=n["onset"],
                duration=n["duration"],
                pitch=n["pitch"],
                confidence=n["confidence"],
                source="crepe",
            )
            for n in run["notes"]
            if region is None or region[0] <= n["onset"] <= region[1]
        ],
        beats,
        region or tuple(run["region"]),
        stem=run["stem"],
        config=config,
        anchor=anchor,
        time_signature=signature,
        pulses_per_bar=pulses,
        double_time=bool(sidecar.get("double_time")),
    )
    return notation, beats


def _version() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _digest(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "-"
    return f"{path.name} sha256 {hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"


def fingerprints(entries: list[dict], runs: dict) -> list[dict]:
    """Every span's cached notes against the transcriber that is running:
    {span, run, cached, current}. `current` is what `run_eval` would key a
    fresh run by (`transcribe_fingerprint`: the whole resolved
    TranscribeConfig and the stage's CACHE_VERSION, under the sidecar), so
    `cached != current` is exactly the case run_eval re-transcribes -- and
    the case where these notes are not the running code's."""
    run_eval = run_eval_module()
    out = []
    for entry in entries:
        run = runs.get(entry["run"])
        path = BENCH / f"{entry['track']}.swingscribe.json"
        if run is None or not path.is_file():
            continue
        sidecar = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            {
                "span": f"{entry['set']}/{entry['name']}",
                "run": entry["run"],
                "cached": run.get("fingerprint"),
                "current": run_eval.transcribe_fingerprint(sidecar, STEP_COST, DIP_DB),
            }
        )
    return out


def stale(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["cached"] != c["current"]]


def stale_report(bad: list[dict], notes_path: Path, limit: int = 12) -> str:
    lines = [
        f"{len(bad)} span(s) in {notes_path} hold notes the running transcriber would not "
        "produce (fingerprint differs; run_eval.transcribe_fingerprint):"
    ]
    for check in bad[:limit]:
        lines.append(f"    {check['span']}: cached {check['cached']}, current {check['current']}")
    if len(bad) > limit:
        lines.append(f"    ... and {len(bad) - limit} more")
    return "\n".join(lines)


def write_ours(
    entries: list[dict],
    folder: Path,
    runs: dict,
    grids: dict,
    excerpt: float | None,
    drop_anchor: bool,
    notes_path: Path,
    page_variant: bool = False,
    grids_path: Path | None = None,
    allow_stale: bool = False,
    log=print,
) -> None:
    """Our page (MusicXML, exactly what `export.to_musicxml` writes) and our
    notes (MIDI, seconds from the cut) for every span, where a competitor's
    go. With `page_variant`, also the page alone with a tempo marking -- the
    median tempo of our grid over the window, what a tool that detects one
    tempo prints -- in `<folder>-page`: the pseudo-tool that measured what
    timing a page costs (docs/head-to-head.md section 8; the marking moves
    no page measure).

    Refuses when any span's cached notes are stale for the running
    transcriber (`fingerprints`): the baseline would be some other code's
    notes under this code's version string. `allow_stale` writes them and
    names them in `tool.json`, which records every span's fingerprint."""
    from swingscribe import external
    from swingscribe.stages.export import to_musicxml

    run_eval = run_eval_module()
    checks = fingerprints(entries, runs)
    bad = stale(checks)
    if bad and not allow_stale:
        raise SystemExit(
            stale_report(bad, notes_path)
            + "\n  Re-run scripts/run_eval.py (it re-transcribes exactly these), or pass "
            "--allow-stale to write them anyway (tool.json will name them)."
        )
    if bad:
        log("  WARNING, --allow-stale: " + stale_report(bad, notes_path))
    paged = folder.with_name(folder.name + PAGE_VARIANT)
    written = 0
    for entry in entries:
        run, grid = runs.get(entry["run"]), grids.get(entry["track"])
        if run is None or grid is None:
            log(f"  {entry['set']}/{entry['name']}: no cached notes or grid, skipped")
            continue
        low, high = entry["window"]
        # Hand-scored and silver spans notate the run's own region, as the
        # harness does; a WJazzD solo is notated over its located window
        # (run_eval._wjazz_notation_one); an excerpt over the excerpt.
        region = None if (excerpt is None and entry["set"] != "wjazzd") else (low, high)
        notation, beats = our_page(entry, run, grid, region, drop_anchor)
        target = folder / entry["set"] / entry["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if notation is not None and notation.bars:
            xml = to_musicxml(notation, part_name=entry["name"])
            target.with_suffix(".musicxml").write_text(xml, encoding="utf-8")
            bpm = run_eval.span_bpm(beats, (low, high))
            if page_variant and bpm:
                # A double-time page is written in doubled units: twice the
                # quarters per minute of the beat.
                qpm = bpm * (2.0 if notation.double_time else 1.0)
                page_target = paged / entry["set"] / f"{entry['name']}.musicxml"
                page_target.parent.mkdir(parents=True, exist_ok=True)
                page_target.write_text(external.add_tempo(xml, qpm), encoding="utf-8")
        inside = [n for n in run["notes"] if low <= n["onset"] <= high]
        external.write_midi(
            [
                external.TimedNote(onset=n["onset"] - low, duration=n["duration"], pitch=n["pitch"])
                for n in inside
            ],
            target.with_suffix(".mid"),
        )
        written += 1
    about = {
        "tool": "SwingScribe",
        "version": _version(),
        "code": str(Path(sys.modules["swingscribe"].__file__).parent),
        "quantize_timing": run_eval.eval_config().quantize.timing,
        "downbeat": "auto (sidecar anchor dropped)" if drop_anchor else "sidecar",
        "notes": _digest(notes_path),
        "grids": _digest(grids_path),
        # Per span, the fingerprint of the notes this page was written from;
        # `--score` crops the references with the cache's notes and checks
        # they are still these.
        "fingerprints": {c["span"]: c["cached"] for c in checks},
        "stale": [c["span"] for c in bad],
        "timing": "midi",
        "note": "written by scripts/head_to_head.py --write-ours from the harness caches",
    }
    if excerpt is not None:
        about["context"] = (
            "whole-span notes and a whole-track beat grid, cut to the window: context no "
            "other tool is given (docs/head-to-head.md section 5)"
        )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.json").write_text(json.dumps(about, indent=2), encoding="utf-8")
    if page_variant and paged.is_dir():
        about = {
            **about,
            "timing": "page",
            "note": about["note"] + "; the page alone, a tempo marking added (median grid tempo)",
        }
        (paged / "tool.json").write_text(json.dumps(about, indent=2), encoding="utf-8")
    log(f"  wrote {written} span(s) to {folder}" + (f" and {paged}" if page_variant else ""))


# ── scoring one tool's outputs ───────────────────────────────────────────────


class References:
    """Each span's reference, parsed once, cut to the excerpt when the tools
    were given one (`crop`, on by default exactly when there is an excerpt;
    the control turns it on over whole spans). The cut is decided from OUR
    transcription's alignment (`external.excerpt_reference`,
    `external.wjazz_excerpt`) -- it decides which reference notes the
    excerpt's audio holds, never what any tool is scored as having heard,
    and every tool is scored against the same cut."""

    def __init__(self, runs: dict, db, excerpt: float | None, crop: bool | None = None):
        self.runs, self.db, self.excerpt = runs, db, excerpt
        self.crop = excerpt is not None if crop is None else crop
        self._scores: dict[str, tuple] = {}
        self._solos: dict[str, dict] = {}

    def score(self, entry: dict):
        """(Score, region its bars cover in seconds, OMR page bars or None)."""
        if entry["name"] in self._scores:
            return self._scores[entry["name"]]
        from swingscribe import external, mscz

        run_eval = run_eval_module()
        path = BENCH / entry["reference"]
        reference = mscz.parse_any(path)
        region = tuple(entry["region"])
        page_bars = run_eval.read_page_bars(path) if run_eval.is_page(entry["track"]) else None
        if self.crop:
            ours = sorted(self.runs[entry["run"]]["notes"], key=lambda n: n["onset"])
            cut = external.excerpt_reference(
                reference,
                [n["onset"] for n in ours],
                [int(n["pitch"]) for n in ours],
                tuple(entry["window"]),
            )
            reference, region = cut.score, cut.region
            page_bars = None  # the OMR step check reads the whole page's bars
        self._scores[entry["name"]] = (reference, region, page_bars)
        return self._scores[entry["name"]]

    def solo(self, entry: dict) -> dict:
        """Our fit of the WJazzD solo over its whole run (the pinned one),
        and the annotation's notes and positions in scope: the whole solo,
        or for a cut the part of it the window holds."""
        if entry["name"] in self._solos:
            return self._solos[entry["name"]]
        import numpy as np
        from score_wjazz import candidates

        from swingscribe.external import wjazz_excerpt
        from swingscribe.wjazz import bar_anchors, notated_beats

        run = self.runs[entry["run"]]
        ordered = sorted(run["notes"], key=lambda n: n["onset"])
        est_on = np.array([n["onset"] for n in ordered])
        est_p = np.array([int(n["pitch"]) for n in ordered])
        fit = next(
            c
            for c in candidates(self.db, entry["track"], est_on, est_p, entry["fit_region"])
            if c["melid"] == entry["melid"]
        )
        positions, bar = notated_beats(self.db, entry["melid"])
        solo = {"fit": fit, "positions": positions, "bar": bar, "ref_p": fit["ref_p"]}
        if self.crop:
            anchors, _ = bar_anchors(self.db, entry["melid"])
            onsets, pitches, kept = wjazz_excerpt(
                fit["ref_on"].tolist(),
                fit["ref_p"].tolist(),
                positions,
                [onset for _q, onset in anchors],
                fit["offset"],
                fit["rate"],
                tuple(entry["window"]),
            )
            solo["ref_on"], solo["ref_p"] = np.array(onsets), np.array(pitches, dtype=int)
            solo["positions"] = kept
        self._solos[entry["name"]] = solo
        return solo


@contextlib.contextmanager
def _reference_for(score_benchmark, reference):
    """score_tune parses its reference from disk; hand it this one instead
    (the cropped excerpt), everything else in it unchanged."""
    real = score_benchmark.mscz

    class Shim:
        parse_any = staticmethod(lambda _path: reference)
        to_note_events = staticmethod(real.to_note_events)

    score_benchmark.mscz = Shim
    try:
        yield
    finally:
        score_benchmark.mscz = real


def _timed_run(notes, region) -> dict:
    return {
        "notes": [
            {"onset": n.onset, "duration": n.duration, "pitch": n.pitch, "confidence": 1.0}
            for n in notes
        ],
        "region": list(region),
        "stem": "-",
        "model": "-",
        "voiced_fraction": 0.0,
    }


def _pitch_headline(row: dict) -> dict:
    """`pitch_f1` (and chroma) for the set means: the page's line where the
    tool wrote a page, else its timed notes -- the preference the pairing
    applies too (`PITCH_SOURCES`)."""
    for source, label in (("page", "page line"), ("timed", "timed notes")):
        if f"pitch_f1_{source}" in row:
            row["pitch_f1"] = row[f"pitch_f1_{source}"]
            if f"chroma_f1_{source}" in row:
                row["chroma_f1"] = row[f"chroma_f1_{source}"]
            row["pitch_source"] = label
            break
    return row


def notes_row(entry: dict, timed, page, refs: References) -> dict:
    """The MuseScore set's measures (`score_tune`): pitch F1 and chroma F1
    time-free, off the page's line (`*_page`) and off the timed notes as
    delivered (`*_timed`); onset and note F1 in time, off the timed notes."""
    import score_benchmark

    from swingscribe.external import TimedNote

    reference, region, _bars = refs.score(entry)

    def scored(notes):
        with _reference_for(score_benchmark, reference):
            return score_benchmark.score_tune(entry["tune_key"], _timed_run(notes, region))

    row: dict = {}
    if page is not None:
        # Positions stand in for seconds: the pitch alignment reads no time.
        line = [
            TimedNote(onset=region[0] + 0.5 * p, duration=0.1, pitch=n)
            for p, _d, n, _g in page.line_events
        ]
        result = scored(line)
        row.update(
            pitch_f1_page=round(result["pitch_f1"], 4),
            chroma_f1_page=round(result["chroma_f1"], 4),
            transposition=float(result["transposition"]),
            n_line=float(len(line)),
        )
    if timed is not None:
        result = scored(timed)
        row.update(
            pitch_f1_timed=round(result["pitch_f1"], 4),
            chroma_f1_timed=round(result["chroma_f1"], 4),
            onset_f1=round(result["onset_f1"], 4),
            note_f1=round(result["note_f1"], 4),
            n_notes=float(len(timed)),
        )
        row.setdefault("transposition", float(result["transposition"]))
    return _pitch_headline(row)


def page_row(entry: dict, page, refs: References) -> dict:
    """`run_eval._notation_one`'s row, for a page read from a file."""
    from swingscribe.benchmark import readability
    from swingscribe.score_bars import bar_line_trace

    run_eval = run_eval_module()
    reference, _region, page_bars = refs.score(entry)
    agreement, result = run_eval.score_notation_page(page.line, reference)
    row = {
        "bars": float(len(page.notation.bars)),
        "key_fifths": float(page.notation.key_fifths),
        **readability(page.notation),
        "coverage": round(result.get("coverage", 0.0), 4),
        "trusted": float(bool(result.get("trusted", False))),
        "n_matched": result["n_matched"],
    }
    if not result["n_matched"]:
        return row
    row.update(
        {
            "rhythm": round(result["rhythm"], 4),
            "value": round(result["value"], 4),
            **{k: round(v, 4) for k, v in agreement.items()},
            **{k: round(result[k], 3) for k in run_eval.EDIT_KEYS},
            **{
                k: round(result[k], 3 if k != "edit_beside_share" else 4)
                for k in run_eval.EDIT_SPLIT_KEYS
            },
            **run_eval.traced(
                bar_line_trace(page.line, reference),
                reference.beats_per_bar,
                page_bars,
                run_eval.page_differences(page.line, reference) if page_bars is not None else None,
            ),
        }
    )
    return row


def _wjazz_pitch_f1(solo: dict, pitches: list[int]) -> float:
    """Time-free pitch F1 of a line against the annotation's pitch sequence
    in scope: `alignment.measured_transposition`, the call `score_tune`
    makes against a hand score (the aligner is mir_eval's one sanctioned
    exception, CLAUDE.md)."""
    from swingscribe.alignment import measured_transposition

    _offset, aligned = measured_transposition([int(p) for p in solo["ref_p"]], list(pitches))
    return round(aligned.f1, 4)


def wjazz_notes_row(entry: dict, timed, refs: References) -> dict:
    """WJazzD's note F1 for a tool's timed notes: the solo fitted to THIS
    tool's notes by the harness's own procedure (`candidates`, the pinned
    melid), or for a cut the cut's reference notes fitted by `fit_affine`
    over the window, then `score_wjazz.score`. Pitch F1 beside it, time-free."""
    import numpy as np
    from score_wjazz import candidates, score

    from swingscribe.wjazz import MIN_MATCH_RATE, fit_affine

    ordered = sorted(timed, key=lambda n: n.onset)
    est_on = np.array([n.onset for n in ordered])
    est_p = np.array([n.pitch for n in ordered])
    notes = [
        {"onset": n.onset, "duration": n.duration, "pitch": n.pitch, "confidence": 1.0}
        for n in ordered
    ]
    if not notes:
        return {"note_f1": 0.0, "located": 0.0, "pitch_f1_timed": 0.0}
    solo_info = refs.solo(entry)
    if not refs.crop:
        found = [
            c
            for c in candidates(refs.db, entry["track"], est_on, est_p, entry["fit_region"])
            if c["melid"] == entry["melid"]
        ]
        solo = found[0]
    else:
        ref_on, ref_p = solo_info["ref_on"], solo_info["ref_p"]
        offset, rate, hits = fit_affine(ref_on, ref_p, est_on, est_p, tuple(entry["window"]))
        solo = {
            "ref_on": ref_on,
            "ref_p": ref_p,
            "offset": offset,
            "rate": rate,
            "match_rate": hits / len(ref_on) if len(ref_on) else 0.0,
        }
    result = score(solo, est_on, notes)
    return {
        "note_f1": round(result["note_f1"], 4),
        "note_precision": round(result["note_precision"], 4),
        "note_recall": round(result["note_recall"], 4),
        "onset_f1": round(result["onset_f1"], 4),
        "match_rate": round(solo["match_rate"], 4),
        # The harness's own gate on a fit (score_wjazz.identify_all).
        "located": float(solo["match_rate"] >= MIN_MATCH_RATE),
        "n_notes": float(len(notes)),
        "pitch_f1_timed": _wjazz_pitch_f1(solo_info, [n.pitch for n in ordered]),
    }


def wjazz_page_row(entry: dict, page, refs: References) -> dict:
    """Readability and the bar lines against WJazzD's own (CLAUDE.md: the
    tatum is Flex-Q's, so no rhythm); coverage is the share of the
    annotation the alignment matched, the gate placement is read behind --
    0 when the page matched nothing, so a tool's worst page stays in the
    coverage pairing rather than dropping out of it. Pitch F1 off the line."""
    from swingscribe.benchmark import COVERAGE_FLOOR, readability
    from swingscribe.score_bars import wjazz_bar_line_agreement, wjazz_bar_line_trace

    run_eval = run_eval_module()
    solo = refs.solo(entry)
    row = dict(readability(page.notation))
    row["pitch_f1_page"] = _wjazz_pitch_f1(solo, [n for _p, _d, n, _g in page.line_events])
    positions, bar = solo["positions"], solo["bar"]
    agreement = wjazz_bar_line_agreement(page.line, positions, bar)
    if agreement["beat_n"]:
        coverage = agreement["beat_n"] / len(positions)
        row.update({k: round(v, 4) for k, v in agreement.items()})
        row.update(coverage=round(coverage, 4), trusted=float(coverage >= COVERAGE_FLOOR))
        row.update(run_eval.traced(wjazz_bar_line_trace(page.line, positions, bar), bar))
    else:
        row.update(coverage=0.0, trusted=0.0, beat_n=0.0)
        row["coverage_why"] = (
            "no annotated note in scope"
            if not positions
            else "nothing placed: the page's metre is not the annotation's, or no note matched"
        )
    return row


def find_output(folder: Path, entry: dict, suffixes) -> Path | None:
    for suffix in suffixes:
        path = folder / entry["set"] / f"{entry['name']}{suffix}"
        if path.is_file():
            return path
    return None


def score_tool(folder: Path, entries: list[dict], refs: References, top: bool, log=print) -> dict:
    """{set: {name: row}} for one tool's folder; a row is the notes row and
    the page row merged, plus where its timing came from."""
    from swingscribe import external

    config = {}
    if (folder / "tool.json").is_file():
        config = json.loads((folder / "tool.json").read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for entry in entries:
        page_path = find_output(folder, entry, PAGE_SUFFIXES)
        midi_path = find_output(folder, entry, MIDI_SUFFIXES)
        if page_path is None and midi_path is None:
            continue
        row: dict = {}
        page = None
        try:
            if page_path is not None:
                # A grace note enters the line by the rule of the reader the
                # span's reference is parsed with (external.graces_for).
                page = external.read_musicxml(
                    page_path, config.get("part"), graces=external.graces_for(entry["reference"])
                )
            timed = None
            if midi_path is not None:
                drums = bool(config.get("drums"))
                timed = external.read_midi(midi_path, drums=drums)
                # A MIDI file written from a page is a page in disguise, and
                # one whose clock cannot say is not taken for a performance.
                clock = external.midi_timing(midi_path, drums=drums)
                row["timing"] = {
                    external.PERFORMED: PERFORMED,
                    external.QUANTIZED: QUANTIZED,
                    external.UNKNOWN: UNREAD,
                }[clock.verdict]
                if clock.share is not None:
                    row["midi_on_grid"] = round(clock.share, 4)
                    row["midi_grid_chance"] = round(clock.chance, 4)
                if clock.why:
                    row["midi_clock"] = clock.why
            elif page is not None:
                timed = external.page_seconds(page)
                row["timing"] = PAGE_TIMING if timed is not None else "none"
            if timed is not None:
                row["polyphony"] = round(external.polyphony(timed), 4)
                if top:
                    timed = external.top_line(timed)
                low = entry["window"][0]
                timed = [
                    external.TimedNote(n.onset + low, n.duration, n.pitch, n.velocity, n.channel)
                    for n in timed
                ]
            if entry["set"] == "wjazzd":
                if timed is not None:
                    row.update(wjazz_notes_row(entry, timed, refs))
                if page is not None:
                    row.update(wjazz_page_row(entry, page, refs))
                _pitch_headline(row)
            else:
                if timed is not None or page is not None:
                    row.update(notes_row(entry, timed, page, refs))
                if page is not None:
                    row.update(page_row(entry, page, refs))
            if page is not None:
                row.update(
                    swing_marking=float(page.swing_marking),
                    short_bars=float(page.short_bars),
                    long_bars=float(page.long_bars),
                    software=page.software,
                )
        except Exception as error:  # a file the reader cannot take is a finding, not a crash
            row = {"error": f"{type(error).__name__}: {error}"}
            log(f"  {folder.name}/{entry['set']}/{entry['name']}: {row['error']}")
        out.setdefault(entry["set"], {})[entry["name"]] = row
    return out


# ── the table ────────────────────────────────────────────────────────────────


def _trusted(row: dict) -> bool:
    """Coverage at or over the floor. A row with no coverage at all is NOT
    trusted: every page row carries one (0 when nothing matched), so its
    absence means no page was read, and nothing that needs trust is shown."""
    from swingscribe.benchmark import COVERAGE_FLOOR

    return "coverage" in row and row["coverage"] >= COVERAGE_FLOOR


def _pair(measure: str, mine: dict, other: dict) -> tuple | None:
    """The two values a measure compares, read off the same kind of output
    on both sides (`PITCH_SOURCES`), or None when the sides hold no common
    one."""
    for source in PITCH_SOURCES.get(measure, (measure,)):
        if source in mine and source in other:
            return mine[source], other[source]
    return None


def paired_rows(ours: dict, theirs: dict, measures=None, any_timing: bool = False) -> list[dict]:
    """One row per measure: the tool against the baseline on the tracks
    both hold (trusted on BOTH sides where the measure needs trust), with
    `evaluation.paired_change`'s interval and sign test. `missing` counts the
    baseline's tracks the tool has no output for at all; `withheld` the
    pairs under the coverage floor on either side.

    A hearing measure read in time pairs only rows timed by PERFORMED
    onsets on both sides; a row timed off a page, off a MIDI file written
    from one, or off a MIDI whose clock cannot say, is counted in `unpaired`
    instead -- it would charge the writing to the hearing (MEASURES).
    `any_timing` lifts the rule, for the experiment that measured it and
    never for a verdict. Pitch F1 pairs the page line with the page line
    and timed notes with timed notes; a pair with no common source is
    `unpaired` too."""
    from swingscribe.evaluation import paired_change

    rows = []
    for measure in measures or MEASURES:
        _kind, _lower, needs_trust, timed = MEASURES[measure]
        pairs = []
        missing = unpaired = withheld = 0
        for track, mine in sorted(ours.items()):
            if measure not in mine:
                continue
            other = theirs.get(track)
            if other is None or "error" in other and measure not in other:
                missing += 1
                continue
            if measure not in other:
                continue
            performed = mine.get("timing") == PERFORMED and other.get("timing") == PERFORMED
            if timed and not (performed or any_timing):
                unpaired += 1
                continue
            if needs_trust and not (_trusted(mine) and _trusted(other)):
                withheld += 1
                continue
            values = _pair(measure, mine, other)
            if values is None:
                unpaired += 1
                continue
            pairs.append(values)
        counts = {"missing": missing, "unpaired": unpaired, "withheld": withheld}
        if not pairs:
            rows.append({"measure": measure, "n": 0, **counts})
            continue
        change = paired_change([a for a, _ in pairs], [b for _, b in pairs])
        rows.append(
            {
                "measure": measure,
                "n": change.n,
                "ours": statistics.fmean(a for a, _ in pairs),
                "theirs": statistics.fmean(b for _, b in pairs),
                "delta": change.mean,
                "low": change.low,
                "high": change.high,
                "up": change.up,
                "down": change.down,
                "level": change.level,
                "p": change.p,
                **counts,
            }
        )
    return rows


def _extras(rows: dict) -> str:
    """What a tool's summary line adds: how many pages carry a swing marking
    (AnthemScore 6.3 claims one), WJazzD fits the harness would accept, and
    MIDI files that look written from a page."""
    out = []
    pages = [r for r in rows.values() if "swing_marking" in r]
    if pages:
        out.append(f"swing marking on {sum(r['swing_marking'] > 0 for r in pages)}/{len(pages)}")
    located = [r for r in rows.values() if "located" in r]
    if located:
        out.append(f"WJazzD fit accepted {sum(r['located'] > 0 for r in located)}/{len(located)}")
    midi = [r for r in rows.values() if str(r.get("timing", "")).startswith("midi")]
    quantized = [r for r in midi if r["timing"] == QUANTIZED]
    if quantized:
        out.append(
            f"{len(quantized)}/{len(midi)} MIDI file(s) on a 24th grid: written from a "
            "page, so not a hearing (re-export with rounded timing off)"
        )
    unread = [r for r in midi if r["timing"] == UNREAD]
    if unread:
        why = sorted({r.get("midi_clock", "") for r in unread})
        out.append(
            f"{len(unread)}/{len(midi)} MIDI file(s) whose clock cannot tell a performance "
            f"from a page ({'; '.join(why)}): not paired on note F1"
        )
    return "; ".join(out)


def set_means(rows: dict, measures) -> dict:
    out = {}
    for measure in measures:
        needs_trust = MEASURES[measure][2]
        values = [
            r[measure] for r in rows.values() if measure in r and (not needs_trust or _trusted(r))
        ]
        if values:
            out[measure] = (statistics.fmean(values), len(values))
    return out


UNPAIRED_WHY = {
    "note_f1": "timed off a page, or a MIDI file written from one or whose clock cannot say "
    "(its hearing is pitch_f1)",
    "pitch_f1": "no output of the same kind on both sides (page line, or timed notes)",
}


def render(
    scores: dict,
    baseline: str,
    condition: str,
    entries: list[dict],
    any_timing: bool = False,
    excerpt: bool = False,
) -> dict:
    """Print tool x set x measure; return the paired rows for --json."""
    counts = {s: sum(1 for e in entries if e["set"] == s) for s in SETS}
    tools = sorted(scores, key=lambda t: (t != baseline, t))
    paired: dict = {}
    print(f"\n== Head-to-head, {condition}: {', '.join(tools)} (baseline {baseline}) ==")
    if excerpt:
        print(
            f"  CAVEAT: {baseline}'s notes and beat grid here come from the whole span and "
            "track, cut to the window;\n  every other tool heard only the excerpt "
            "(docs/head-to-head.md section 5). Not a publishable result until our\n  "
            "pipeline is run on the cut wavs themselves."
        )
    for set_name in SETS:
        if not counts.get(set_name):
            continue
        measures = SET_MEASURES[set_name]
        print(f"\n-- {set_name}: {counts[set_name]} span(s) --")
        for tool in tools:
            rows = scores[tool].get(set_name, {})
            means = set_means(rows, measures)
            timing = sorted({r.get("timing", "-") for r in rows.values()})
            errors = sum(1 for r in rows.values() if "error" in r)
            cells = "  ".join(f"{m} {v:.3f} (n={n})" for m, (v, n) in means.items())
            extras = _extras(rows)
            print(
                f"  {tool:<22s} {len(rows):3d} output(s), timing {'/'.join(timing)}"
                + (f", {errors} unreadable" if errors else "")
            )
            if cells:
                print(f"      {cells}")
            if extras:
                print(f"      {extras}")
        if baseline not in scores:
            continue
        for tool in tools:
            if tool == baseline:
                continue
            table = paired_rows(
                scores[baseline].get(set_name, {}),
                scores[tool].get(set_name, {}),
                measures,
                any_timing,
            )
            paired.setdefault(tool, {})[set_name] = table
            print(
                f"\n  {tool} against {baseline}, paired on the same spans "
                "(95% interval resampled by span; sign test):"
            )
            header = (
                f"    {'measure':<12s} {'n':>3s} {'miss':>4s} {baseline:>11s} {tool[:11]:>11s} "
                f"{'change':>8s} {'95% interval':>19s} {'up':>3s} {'down':>4s} {'p':>6s}"
            )
            print(header)
            for row in table:
                if not row["n"]:
                    print(
                        f"    {row['measure']:<12s} {0:3d} {row['missing']:4d}  (nothing to pair)"
                    )
                    continue
                lower = " (v)" if MEASURES[row["measure"]][1] else ""
                separated = row["low"] > 0 or row["high"] < 0
                decided = " *" if separated and row["p"] < 0.05 else ""
                print(
                    f"    {row['measure'] + lower:<12s} {row['n']:3d} {row['missing']:4d} "
                    f"{row['ours']:11.3f} {row['theirs']:11.3f} {row['delta']:+8.3f} "
                    f"[{row['low']:+.3f}, {row['high']:+.3f}] {row['up']:3d} {row['down']:4d} "
                    f"{row['p']:6.3f}{decided}"
                )
            for row in table:
                if row.get("unpaired"):
                    why = UNPAIRED_WHY.get(row["measure"], "no common output")
                    print(f"    {row['measure']}: {row['unpaired']} span(s) not paired: {why}")
                if row.get("withheld"):
                    print(
                        f"    {row['measure']}: {row['withheld']} span(s) withheld, under the "
                        "coverage floor on one side or both"
                    )
    print("\n  (v) lower is better; * the interval excludes zero and the sign test says p < 0.05.")
    print("  Rhythm, value, on-the-bar and edit cost are withheld on a page under the coverage")
    print("  floor (0.5), on either side. Note F1 pairs only rows timed by performed onsets (MIDI")
    print("  not written from a page); timed off a page it measures the writing. Pitch F1 reads")
    print("  the page's line on both sides where both wrote a page, else both sides' timed")
    print("  notes; pitch_f1_timed is the timed notes as delivered (a whole-mix MIDI included).")
    if any_timing:
        print("  --pair-any-timing: that rule is OFF in this table. Not a verdict.")
    return paired


# ── the control ──────────────────────────────────────────────────────────────


def pin_keys(entry: dict) -> tuple[str, str]:
    """(timed section, page section) of the pins a span's rows live under."""
    return {
        "hand": ("mscz", "notation"),
        "silver": ("pages", "pages-notation"),
        "wjazzd": ("wjazz", "wjazz-notation"),
    }[entry["set"]]


CONTROL_FIELDS = {
    "hand": (
        ("notes", ("pitch_f1", "chroma_f1", "onset_f1", "note_f1")),
        (
            "page",
            (
                "rhythm",
                "value",
                "n_matched",
                "bars",
                "key_fifths",
                "readability",
                "short_rests",
                "short_values",
                "tie_rate",
                "events",
                "on_the_bar",
                "beat_offset",
                "beat_share",
                "beat_n",
                "beat_steps",
                "beat_slope",
                "edit_cost",
                "edit_insertions",
                "edit_deletions",
                "edit_pitch",
                "edit_position",
                "edit_value",
                "edit_bar",
                "edit_position_beside",
                "edit_value_beside",
                "edit_beside_share",
                "page_steps",
            ),
        ),
    ),
}
CONTROL_FIELDS["silver"] = (
    CONTROL_FIELDS["hand"][0],
    ("page", (*CONTROL_FIELDS["hand"][1][1], "coverage", "trusted")),
)
CONTROL_FIELDS["wjazzd"] = (
    ("notes", ("note_f1", "note_precision", "note_recall", "onset_f1")),
    (
        "page",
        (
            "readability",
            "short_rests",
            "short_values",
            "tie_rate",
            "events",
            "on_the_bar",
            "beat_offset",
            "beat_share",
            "beat_n",
            "beat_steps",
            "beat_slope",
            "coverage",
            "trusted",
        ),
    ),
)
CONTROL_TOLERANCE = 0.002  # run_eval.TOLERANCE
# The pins' pitch and chroma F1 are score_tune over the run's notes: our
# MIDI's reading, `*_timed` in a row (the headline `pitch_f1` is the page's).
CONTROL_ROW_FIELD = {"pitch_f1": "pitch_f1_timed", "chroma_f1": "chroma_f1_timed"}


def control_diffs(rows: dict, entries: list[dict], pins: dict) -> list[tuple]:
    """(set, name, section, field, pinned, read) for every compared number."""
    out = []
    for entry in entries:
        row = rows.get(entry["set"], {}).get(entry["name"])
        if row is None:
            continue
        sections = pin_keys(entry)
        for (kind, fields), section in zip(CONTROL_FIELDS[entry["set"]], sections, strict=True):
            for field in fields:
                key = f"{section}/{entry['name']}/{field}"
                read = CONTROL_ROW_FIELD.get(field, field) if kind == "notes" else field
                if key in pins and read in row:
                    out.append((entry["set"], entry["name"], kind, field, pins[key], row[read]))
                elif key in pins:
                    out.append((entry["set"], entry["name"], kind, field, pins[key], None))
    return out


def print_control(
    label: str, diffs: list[tuple], stale_spans: set[str] | None = None, gate: bool = True
) -> int:
    moved = [d for d in diffs if d[5] is None or abs(d[5] - d[4]) > CONTROL_TOLERANCE]
    spans = {(d[0], d[1]) for d in diffs}
    print(f"\n== Control: {label} ==")
    print(
        f"  {len(diffs)} pinned numbers over {len(spans)} span(s); "
        f"{len(diffs) - len(moved)} reproduced within {CONTROL_TOLERANCE}, {len(moved)} not"
    )
    if stale_spans:
        on_stale = sum(1 for d in moved if f"{d[0]}/{d[1]}" in stale_spans)
        print(
            f"  {on_stale} of those {len(moved)} are on the {len(stale_spans)} span(s) whose "
            "cached notes are stale for this code: a failure there is the notes, not the reader"
        )
    moved_spans = {(d[0], d[1]) for d in moved}
    if moved_spans and stale_spans is not None and gate:
        print(
            f"  moved on {len(moved_spans)} span(s). A span can fail because its notes are not "
            "the ones the pins were made from\n  (re-transcribed and not re-pinned, or re-pinned "
            "and the cache not re-run): check the fingerprints\n  before suspecting the reader."
        )
    by_field: dict[str, list[float]] = {}
    for d in diffs:
        if d[5] is not None:
            by_field.setdefault(d[3], []).append(abs(d[5] - d[4]))
    worst = sorted(by_field.items(), key=lambda kv: -max(kv[1]))[:8]
    print("  largest |read - pinned| by field: " + ", ".join(f"{f} {max(v):.4f}" for f, v in worst))
    for set_name, name, kind, field, pinned, read in moved[:40]:
        shown = "missing" if read is None else f"{read:.4f}"
        print(f"    {set_name}/{name} {kind}.{field}: pinned {pinned:.4f}, read {shown}")
    if len(moved) > 40:
        print(f"    ... and {len(moved) - 40} more")
    return len(moved)


SHIFT_FIELDS = ("pitch_f1", "note_f1", "rhythm", "value", "on_the_bar", "coverage", "edit_cost")


def print_shifts(diffs: list[tuple]) -> None:
    """Per set and measure, the mean signed read - pinned, with n and the
    largest: how far the excerpt machinery moves a whole span's numbers."""
    by: dict[tuple[str, str], list[float]] = {}
    for set_name, _name, _kind, field, pinned, read in diffs:
        if field in SHIFT_FIELDS and read is not None:
            by.setdefault((set_name, field), []).append(read - pinned)
    print("  mean signed shift (read - pinned), n, largest |shift|:")
    for set_name in SETS:
        cells = [
            f"{field} {statistics.fmean(v):+.4f} (n={len(v)}, max {max(map(abs, v)):.4f})"
            for field in SHIFT_FIELDS
            if (v := by.get((set_name, field)))
        ]
        if cells:
            print(f"    {set_name}: " + ", ".join(cells))


def check_baseline(
    folder: Path,
    entries: list[dict],
    runs: dict,
    notes_path: Path,
    crop: bool,
    allow_stale: bool,
    log=print,
) -> None:
    """The baseline's pages were written from notes whose fingerprints its
    `tool.json` records; a cut reference is decided from the notes cache
    NOW. If the two differ, the reference was cut on notes the baseline was
    not written from -- refused when there is a cut (unless `allow_stale`),
    noted when there is none (a whole-span reference reads no notes)."""
    path = folder / "tool.json"
    about = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    recorded = about.get("fingerprints")
    if recorded is None:
        if folder.is_dir():
            log(
                f"  NOTE: {path} records no fingerprints: cannot check that {notes_path} "
                "still holds the notes the baseline was written from (re-run --write-ours)"
            )
        return
    if about.get("stale"):
        log(
            f"  NOTE: the baseline was written with --allow-stale from notes the transcriber "
            f"that wrote it would not produce, on {len(about['stale'])} span(s)"
        )
    now = {f"{e['set']}/{e['name']}": runs.get(e["run"], {}).get("fingerprint") for e in entries}
    differ = sorted(span for span, fp in recorded.items() if span in now and now[span] != fp)
    if not differ:
        return
    message = (
        f"{len(differ)} span(s) of {notes_path} no longer hold the notes {folder.name} was "
        f"written from ({', '.join(differ[:6])}{' ...' if len(differ) > 6 else ''})"
    )
    if crop and not allow_stale:
        raise SystemExit(
            message + ": the excerpt's references are cut on those notes. Re-run --write-ours, "
            "or point --notes at the cache it was written from."
        )
    log(f"  {'WARNING' if crop else 'NOTE'}: {message}")


def gui_exports(entries: list[dict]) -> dict[str, Path]:
    """The page the GUI's Export wrote beside each hand-scored track, if any:
    `<stem>.<lo>-<hi>s[.oracle].musicxml` at the span the sidecar holds."""
    found = {}
    for entry in entries:
        if entry["set"] != "hand":
            continue
        stem = Path(entry["track"]).stem
        low, high = entry["region"]
        base = f"{stem}.{low:.0f}-{high:.0f}s"
        # The oracle line has been the pianists' default since 2026-09-18.
        for name in (f"{base}.oracle.musicxml", f"{base}.musicxml"):
            if (BENCH / name).is_file():
                found[entry["name"]] = BENCH / name
                break
    return found


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true", help="list the spans of a condition")
    action.add_argument("--export-audio", action="store_true", help="cut the span wavs")
    action.add_argument("--write-ours", action="store_true", help="write SwingScribe's outputs")
    action.add_argument("--score", action="store_true", help="score every tool's outputs")
    action.add_argument("--control", action="store_true", help="our own exports against the pins")
    parser.add_argument(
        "--excerpt",
        type=float,
        default=None,
        help=f"give the tools only the first N seconds of each span ({TRIAL_EXCERPT_S:g} for "
        "the free trials); default: the whole span",
    )
    parser.add_argument("--source", choices=("mix", "stem"), default="mix")
    parser.add_argument("--sets", default=",".join(SETS))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--notes", type=Path, default=None, help="the harness's notes cache")
    parser.add_argument("--grids", type=Path, default=None, help="the harness's grid cache")
    parser.add_argument(
        "--pins", type=Path, default=Path("tests/regression/real-audio-baselines.json")
    )
    parser.add_argument("--db", type=Path, default=Path("wjazz/wjazzd.db"))
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=STEM_CACHE,
        help=f"stage cache the stems (and ingest wavs) are read from (default {STEM_CACHE}, "
        "where the pins' span-scoped stems are; pass the one run_eval ran with)",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="--write-ours/--score: go on when the cached notes are not the running "
        "transcriber's (named in tool.json); never for a result",
    )
    parser.add_argument(
        "--no-crop-control",
        action="store_true",
        help="--control: skip the excerpt-machinery pass over whole spans",
    )
    parser.add_argument("--tools", default=None, help="comma-separated tool folders to score")
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument(
        "--downbeat",
        choices=("auto", "sidecar"),
        default="auto",
        help="--write-ours: drop the sidecar downbeat (auto, the fair default) or keep it",
    )
    parser.add_argument("--top-line", action="store_true", help="reduce timed notes to a line")
    parser.add_argument(
        "--page-variant",
        action="store_true",
        help="--write-ours: also write our page alone with a tempo marking (<baseline>-page)",
    )
    parser.add_argument(
        "--pair-any-timing",
        action="store_true",
        help="pair note F1 whatever the timing: the section 8 experiment, never a verdict",
    )
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--detail", action="store_true", help="print every span's row")
    args = parser.parse_args()

    run_eval = run_eval_module()
    from swingscribe.evaluation import normalize_title as normalize

    sets = [s for s in args.sets.split(",") if s]
    notes_path = args.notes or run_eval.notes_cache(STEP_COST, DIP_DB)
    grids_path = args.grids or run_eval.GRIDS_CACHE
    runs = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}
    pins = json.loads(args.pins.read_text(encoding="utf-8")) if args.pins.is_file() else {}
    db = None
    if args.db.is_file():
        import sqlite3

        db = sqlite3.connect(args.db)
    excerpt = None if args.control else args.excerpt
    folder = args.root / condition_name(args.source, excerpt)

    def build() -> list[dict]:
        return with_windows(build_entries(sets, pins, runs, db), excerpt)

    if args.plan:
        entries = load_entries(folder, build)
        if db is not None and pins and "wjazzd" in sets:
            names = {normalize(e["name"]) for e in entries if e["set"] != "wjazzd"}
            today = choose_wjazz_subset(wjazz_candidates(pins, db, names))
            if tuple(today) == WJAZZ_SUBSET:
                print(f"  the subset rule still picks the frozen {len(today)} WJazzD solos")
            else:
                print(
                    f"  NOTE: the subset rule today picks {sorted(set(today) ^ set(WJAZZ_SUBSET))}"
                )
                print("  differently from the frozen WJAZZ_SUBSET, which stands (it is frozen)")
        bad = stale(fingerprints(entries, runs))
        if bad:
            print("  NOTE: " + stale_report(bad, notes_path))
        else:
            print(f"  every span's cached notes in {notes_path} are the running transcriber's")
        print(f"== {folder}: {len(entries)} span(s) ==")
        for entry in entries:
            low, high = entry["window"]
            print(
                f"  {entry['set']:<7s} {entry['name'][:52]:<52s} {low:8.2f}-{high:8.2f} s "
                f"({high - low:5.1f} s)  {entry['instrument']}, {entry['time_signature']}"
            )
        return

    if args.export_audio:
        entries = build()
        print(f"== Cutting {len(entries)} span(s) into {folder / AUDIO_DIR} ==")
        export_audio(entries, folder, args.source, args.cache_dir, runs)
        print(f"\nDrop each tool's outputs in {folder}/<tool>/<set>/<name>.musicxml (+ .mid).")
        return

    grids = json.loads(grids_path.read_text(encoding="utf-8")) if grids_path.is_file() else {}

    if args.write_ours:
        entries = [e for e in load_entries(folder, build) if e["set"] in sets]
        target = folder / (BASELINE if args.downbeat == "auto" else f"{BASELINE}-sidecar")
        print(f"== Writing SwingScribe's outputs to {target} ==")
        write_ours(
            entries,
            target,
            runs,
            grids,
            excerpt,
            args.downbeat == "auto",
            notes_path,
            page_variant=args.page_variant,
            grids_path=grids_path,
            allow_stale=args.allow_stale,
        )
        return

    if args.control:
        entries = build()
        # The control runs whatever the cache holds -- it tests the reader
        # against the pins -- but names the spans whose notes are stale, so
        # a failure there is read as the notes and not the path.
        stale_spans = {c["span"] for c in stale(fingerprints(entries, runs))}
        refs = References(runs, db, None)
        crop_rows = None
        with tempfile.TemporaryDirectory() as tmp:
            ours = Path(tmp) / "swingscribe-pinned"
            write_ours(
                entries,
                ours,
                runs,
                grids,
                None,
                False,
                notes_path,
                grids_path=grids_path,
                allow_stale=True,
            )
            rows = score_tool(ours, entries, refs, top=False)
            if not args.no_crop_control:
                crop_rows = score_tool(
                    ours, entries, References(runs, db, None, crop=True), top=False
                )
        failures = print_control(
            "our pages and notes, pinned settings, read back through the external path",
            control_diffs(rows, entries, pins),
            stale_spans,
        )
        if crop_rows is not None:
            diffs = control_diffs(crop_rows, entries, pins)
            print_control(
                "the same pages through the EXCERPT machinery with the window = the whole span "
                "(reference cut on our alignment, WJazzD refitted over the window; a reading, "
                "not a gate)",
                diffs,
                stale_spans,
                gate=False,
            )
            print_shifts(diffs)
        exported = gui_exports(entries)
        if exported:
            with tempfile.TemporaryDirectory() as tmp:
                gui = Path(tmp) / "gui"
                for name, path in exported.items():
                    (gui / "hand").mkdir(parents=True, exist_ok=True)
                    (gui / "hand" / f"{name}.musicxml").write_bytes(path.read_bytes())
                gui_rows = score_tool(gui, entries, refs, top=False)
            diffs = [d for d in control_diffs(gui_rows, entries, pins) if d[2] == "page"]
            print_control(
                "the pages the GUI's Export wrote beside the audio (older exports, the "
                "listener's erasures applied: NOT expected to match)",
                diffs,
            )
        if args.json:
            args.json.write_text(
                json.dumps(
                    {"rows": rows, "crop_rows": crop_rows, "stale": sorted(stale_spans)},
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        raise SystemExit(1 if failures else 0)

    # --score
    entries = [e for e in load_entries(folder, build) if e["set"] in sets]
    wanted = set(args.tools.split(",")) if args.tools else None
    tool_dirs = (
        sorted(
            p
            for p in folder.iterdir()
            if p.is_dir() and p.name != AUDIO_DIR and (wanted is None or p.name in wanted)
        )
        if folder.is_dir()
        else []
    )
    if not tool_dirs:
        raise SystemExit(f"no tool folders under {folder}; see docs/head-to-head.md")
    refs = References(runs, db, excerpt)
    check_baseline(folder / args.baseline, entries, runs, notes_path, refs.crop, args.allow_stale)
    scores = {}
    for tool in tool_dirs:
        print(f"== Scoring {tool.name} ==")
        scores[tool.name] = score_tool(tool, entries, refs, args.top_line)
    if args.detail:
        shown_keys = {*MEASURES, "timing", "pitch_source"}
        for tool, sets_rows in scores.items():
            for set_name, rows in sets_rows.items():
                for name, row in sorted(rows.items()):
                    shown = {k: v for k, v in row.items() if k in shown_keys}
                    print(f"  {tool}/{set_name}/{name}: {shown}")
    paired = render(
        scores, args.baseline, folder.name, entries, args.pair_any_timing, excerpt is not None
    )
    if args.json:
        args.json.write_text(
            json.dumps({"condition": folder.name, "scores": scores, "paired": paired}, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
