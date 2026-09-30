"""One command, one scorecard: everything the pipeline is measured by.

    uv run python scripts/run_eval.py --db wjazz/wjazzd.db
    uv run python scripts/run_eval.py --db wjazz/wjazzd.db --pin

Plan section 7 asks M6 for an eval harness that "prints a scorecard", with
pinned baselines so a change that moves a number has to say so. This is it.

It runs both benchmarks over everything in `benchmark/` that has a sidecar,
transcribes what it must (cached per decode setting, because CREPE on CPU is
a minute a tune), and prints one table. Then it diffs against the pinned
baselines and exits non-zero if anything moved by more than noise.

## Why there are two benchmarks and both are kept

They ask different questions and neither subsumes the other; the full
argument is in `docs/benchmark-deficiencies.md`. Briefly: WJazzD scores our
timestamps against a human's timestamps for the same recording, which is what
`transcribe` should be judged on. MuseScore scores our audio against notated
rhythm, which is what `notate` should be judged on and which necessarily
reads lower, because notation idealizes what was played.

Reporting only the second one is what made the transcriber look worse than it
is for months.

## A third set: the Omnibook

`benchmark/Omnibook/` holds LORIA's MusicXML of the Charlie Parker Omnibook
beside the recordings the listener could find, with spans located by content
(`scripts/locate_scores.py`) rather than drawn by ear. It is scored by
exactly the code the listener's own transcriptions are -- the same
`score_benchmark.score_tune`, the same `score_against_notation` -- but kept
in sections and means of its own (`omnibook`, `omnibook_notation`): folding
twenty-two Parker sides into a twelve-track mean would move every pinned
number without the pipeline having changed, and the two references differ in
kind. A listener's page covers one solo; the book covers the head and the
choruses, editorially (plan section 6, layer 3: ghost notes dropped,
enharmonics normalised), of a 78-era side. Its rhythm is never read without
its coverage, because a located span could be the wrong take.

## A fourth set: the PDF pages, in two tiers

`benchmark/Transcriptions_Other/musicxml/` holds what `pdf2musicxml` read off
the PDF transcriptions the listener collected. A page with its recording
beside it (same base name) and a sidecar from `locate_scores.py` is scored
exactly like the Omnibook -- and, like the Omnibook, in sections and means of
its own (`pages`, `pages_notation`), split again by how far its OMR reading
can be trusted: silver or bronze (`swingscribe.evaluation.page_tier`,
docs/roadmap.md E3). A page is never folded into the listener's twelve or the
book.

## The locked test set

Every track in `benchmark/` on 2026-09-29 is dev; a track added since is dev
or test by a salted hash of its tune title (`swingscribe.evaluation.Split`,
`tests/regression/split.json`). An ordinary run scores dev only and says how
many tracks it held out; `--test` scores the test tracks alone, against pins
of their own (`tests/regression/test-baselines.json`), and is for a release.
Looking at a test number and then tuning is how a test set stops being one.

## What "pinned" means here

Real-audio baselines cannot run in CI -- they need the audio, which is never
committed (plan section 12). So this is a pre-merge command, not a test. The
baselines live in `tests/regression/real-audio-baselines.json`, separately
from the synthetic ones in `baselines.json`, which stay sacred and untouched
(CLAUDE.md).

A moved number is printed with the paired change of its whole set: the same
tracks before and after, a 95% interval resampled by recording, and a sign
test (`swingscribe.evaluation.paired_change`). The pins say WHAT moved; the
interval says whether the set moved more than its own spread. `--against
card.json` prints the same comparison against a scorecard saved with
`--json`, for an A/B run under an environment override.

Nothing this reads or writes may be committed except the aggregate numbers.
"""

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

BENCH = Path("benchmark")
BASELINES = Path("tests/regression/real-audio-baselines.json")
# The test split's own pins, written only by `--test --pin` (module docstring).
TEST_BASELINES = Path("tests/regression/test-baselines.json")
SPLIT_FILE = Path("tests/regression/split.json")
# Which stage cache the stems and ingests are read from. The default is the
# repo-root cache the GUI shares when launched from here; `--cache-dir
# benchmark/.swingscribe-cache` reads the batch's, where a span-scoped
# Roformer separation lands (stages/separate.py). Copying 28 GB of stems
# between the two so this could keep one default was the alternative.
CACHE_DIR = Path(".swingscribe-cache")


def eval_config():
    from swingscribe.config import Config

    return Config(cache_dir=CACHE_DIR)


# How far a score may move before it is called a change rather than noise.
# Transcription is deterministic, so this is tight on purpose; it exists for
# floating-point drift across platforms, not for genuine variation.
TOLERANCE = 0.002


def notes_cache(step_cost: float, dip_db: float) -> Path:
    """One cache per decode setting -- they are not interchangeable results."""
    return Path(f".benchmark-notes-c{step_cost}-d{dip_db}.json")


def sidecar_name(sidecar_path: Path, sidecar: dict) -> str:
    """The track's key: its path relative to benchmark/, with forward slashes.

    `sidecar["file"]` is a bare filename, because the sidecar lives beside its
    audio and does not need to say where that is. Once benchmark/ has
    subfolders (benchmark/wjazzd/, added when the library outgrew one flat
    directory) the bare name no longer locates the file, and two tracks in
    different folders could collide on it. Forward slashes so a key pinned on
    Windows matches one pinned anywhere else.
    """
    folder = sidecar_path.parent.relative_to(BENCH)
    name = sidecar.get("file") or sidecar_path.name.removesuffix(".swingscribe.json")
    return name if folder == Path(".") else f"{folder.as_posix()}/{name}"


# A pianist is scored TWICE: on the pipeline's default line and on the other
# one (issue #8). Since 2026-09-18 the default is the oracle line, picked
# from the piano model's full output, and the second take is CREPE's line
# corrected by the piano model; it was the other way round from 2026-09-10,
# when the harness began scoring both so the default could be decided on a
# table (docs/issue8-line-selection.md). The take rides in the run's KEY,
# after the track's name, so every consumer that is keyed by track (grids,
# sidecars, scores on disk) looks up the track and every pinned number stays
# distinct. `SECOND_LINE` is whichever line the pipeline's default is NOT
# (a test holds it to that); its take is keyed "<track> [line=crepe]".
SECOND_LINE = "crepe"
SECOND_TAKE = f" [line={SECOND_LINE}]"

# The Omnibook set lives in this subfolder of benchmark/ (module docstring).
# Its rows are split out of the MuseScore sections by track key, which
# carries the folder (sidecar_name), so nothing else has to know.
OMNIBOOK_FOLDER = "Omnibook"


def is_omnibook(key: str) -> bool:
    """Whether a run key names a track of the Omnibook set."""
    return track_of(key).startswith(OMNIBOOK_FOLDER + "/")


# The PDF pages live under this subfolder (module docstring), their MusicXML
# and manifests in its `musicxml/` folder beside the recordings.
PAGES_FOLDER = "Transcriptions_Other"
TIERS = ("silver", "bronze")


def is_page(key: str) -> bool:
    """Whether a run key names a recording paired with a PDF page."""
    return track_of(key).startswith(PAGES_FOLDER + "/")


def is_located(key: str) -> bool:
    """A span placed by content rather than drawn by ear: its rhythm is
    never read without its coverage, because it could be the wrong take."""
    return is_omnibook(key) or is_page(key)


def page_score(sidecar: dict) -> Path | None:
    """The MusicXML a page's sidecar names, if it is a file."""
    score = sidecar.get("score")
    if not score:
        return None
    path = Path(score)
    return path if path.is_file() else None


def page_quality(score_path: Path) -> tuple[str, str]:
    """(tier, split group) for a PDF page: its manifest entry and the share
    of its bars that fill their signature, read by figure_prior's reader --
    the same reader that decides which bars the prior counts."""
    sys.path.insert(0, str(Path(__file__).parent))
    import figure_prior

    from swingscribe.evaluation import page_group, page_tier

    entry = figure_prior.load_manifests(score_path.parent).get(score_path.name)
    page = figure_prior.read_transcription(score_path, entry)
    bars = [bar for bar in page.bars if bar.length > 0]
    filled = sum(1 for bar in bars if bar.filled == bar.length) / len(bars) if bars else None
    return page_tier(entry, filled), page_group(entry, page.name)


def split_group(track: str, sidecar: dict, db=None) -> list[str]:
    """The names a track goes by for the split -- its tune title where one is
    known, else its file's stem. More than one when two spellings of the
    track exist (a WJazzD file's stem and the database's title), so the
    frozen dev list can hold both and a run with or without `--db` agrees."""
    names = [Path(track).stem]
    if is_page(track):
        score = page_score(sidecar)
        if score is not None:
            names.insert(0, page_quality(score)[1])
    melids = sidecar.get("melids") or ([sidecar["melid"]] if sidecar.get("melid") else [])
    if db is not None and melids:
        row = db.execute("select title from solo_info where melid=?", (int(melids[0]),)).fetchone()
        if row:
            names.insert(0, row[0])
    return names


def held_out(track: str, sidecar: dict, split, db=None) -> bool:
    """Whether the locked split holds this track out of an ordinary run. A
    track any of whose names is dev stays dev."""
    from swingscribe.evaluation import normalize_title

    names = split_group(track, sidecar, db)
    if any(normalize_title(name) in split.dev for name in names):
        return False
    return split.is_test(names[0])


def track_of(key: str) -> str:
    """The audio file a run key names, without any take or performer suffix."""
    return key.split(" [")[0]


def take_of(key: str) -> str | None:
    """Which line a run key transcribed: None for the default, else the line
    its "[line=...]" suffix names."""
    marker = " [line="
    if marker not in key:
        return None
    return key.split(marker, 1)[1].split("]", 1)[0]


def second_key(key: str) -> str:
    """The second take's key for a default-take key, whatever other suffix
    (a performer, for a file holding several solos) it carries."""
    track = track_of(key)
    return track + SECOND_TAKE + key[len(track) :]


def pin_name(key: str) -> str:
    """A run key as it is spelled in the baselines: the file's stem, keeping
    every bracketed suffix. `Path(key).stem` alone folded "X.m4a [line=oracle]"
    onto "X"."""
    track, *suffixes = key.split(" [")
    return Path(track).stem + "".join(" [" + s for s in suffixes)


def transcribe_settings(sidecar: dict, step_cost: float, dip_db: float, line: str | None = None):
    """The exact TranscribeConfig this sidecar asks for. One definition, used
    both to fingerprint a cached run and to compute a fresh one, so the two can
    never drift apart. `line` names a pianist's take (SECOND_TAKE); None is the
    pipeline's default and leaves the config's serialization alone, so a
    default-take fingerprint moves only when the default does."""
    from swingscribe.config import Config

    base = Config()
    low, high = sidecar["region"]
    # A null `stem` means the listener never chose one, not that there is no
    # stem: it falls back to the default exactly as `ensemble` does. Without
    # this it reached the filesystem as "None.wav" and the track was skipped -
    # which went unnoticed for as long as a cached run kept answering for it.
    update = {
        "stem": sidecar.get("stem") or base.transcribe.stem,
        "region": (low, high),
        "pitch_step_cost": step_cost,
        "onset_dip_db": dip_db,
        "ensemble": sidecar.get("ensemble") or base.transcribe.ensemble,
    }
    if line is not None:
        update["piano_line"] = line
    return base.transcribe.model_copy(update=update)


def transcribe_fingerprint(
    sidecar: dict, step_cost: float, dip_db: float, line: str | None = None
) -> str:
    """A cached run is reusable only if the transcriber would read the same
    settings AND is the same transcriber. Mirrors pipeline._cache_name: the
    stage's CACHE_VERSION is folded in, so a behaviour change with no config
    change still invalidates."""
    from swingscribe.cache import canonical_json
    from swingscribe.stages import transcribe

    settings = transcribe_settings(sidecar, step_cost, dip_db, line)
    payload = {
        "version": getattr(transcribe, "CACHE_VERSION", 1),
        "model": sidecar["model"],
        "transcribe": settings.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]


def transcribe_all(cache: Path, step_cost: float, dip_db: float, log=print) -> dict:
    """Transcribe every sidecar'd span in benchmark/, reusing what is cached."""
    from swingscribe.gui import library
    from swingscribe.stages import transcribe

    runs = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    live: set[str] = set()
    for sidecar_path in sorted(BENCH.rglob("*.swingscribe.json")):
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        name = sidecar_name(sidecar_path, sidecar)
        if not (BENCH / name).is_file():
            continue
        # A pianist is transcribed on both lines (SECOND_TAKE); a horn has no
        # second take, because the picker reads the piano model and a piano
        # model asked about a saxophone vouches for nothing.
        takes = [(name, None)]
        if transcribe_settings(sidecar, step_cost, dip_db).uses_piano_oracle:
            takes.append((second_key(name), SECOND_LINE))
        for key, line in takes:
            live.add(key)
            # Re-transcribe when ANYTHING the transcriber reads has changed.
            # The cache filename carries only the two decode settings the
            # sweep varies, so for a long time a change to the stage itself --
            # a new default, a new step like the piano gap-fill -- silently
            # kept serving notes computed by the old code. That is exactly the
            # staleness hole the pipeline's chained keys exist to close
            # (CLAUDE.md), reintroduced in the harness because this cache is
            # keyed by filename.
            #
            # So the fingerprint is the whole resolved TranscribeConfig plus
            # the stage's CACHE_VERSION, canonicalised the same way the real
            # cache keys are. An entry without one is pre-fingerprint and
            # re-runs once.
            cached_run = runs.get(key)
            wanted = transcribe_fingerprint(sidecar, step_cost, dip_db, line)
            if cached_run is not None:
                if cached_run.get("fingerprint") == wanted:
                    continue
                why = "settings" if cached_run.get("fingerprint") else "no fingerprint"
                log(f"  {key}: {why} differs from cache -- re-transcribing")
                runs.pop(key)
            base = eval_config()
            low, high = sidecar["region"]
            settings = transcribe_settings(sidecar, step_cost, dip_db, line)
            # The region rides in the config too, so a span-scoped stem set
            # that covers this solo resolves (library.span_for) — a whole-file
            # set still answers first.
            config = base.model_copy(
                update={
                    "separate": base.separate.model_copy(update={"model": sidecar["model"]}),
                    "transcribe": settings,
                }
            )
            document = library.ingested_document(BENCH / name, config)
            # Through library.resolve_stem, the same resolver the GUI uses: a
            # composite like "other+vocals" (Oleo's fix, R16) is summed on
            # demand beside its parts. Building the path by hand skipped every
            # track the listener had routed to a composite stem.
            stem = library.resolve_stem(document, config, sidecar["model"], settings.stem)
            if stem is None:
                log(f"  {key}: no {settings.stem!r} stem for {sidecar['model']} — skipped")
                continue
            # `ensemble` is a per-track human judgement about the recording,
            # so it lives in the sidecar beside the audio like the span does.
            # It routes the piano oracle (M7b): a span with a horn anywhere in
            # it must stay horn-led, because a piano model asked about a
            # saxophone vouches for nothing and rejection would delete the
            # line.
            ensemble = settings.ensemble
            started = time.time()
            notes, diagnostics = transcribe.analyze(str(stem), settings)
            log(f"  {key}: {len(notes)} notes in {time.time() - started:.0f}s")
            runs[key] = {
                "model": sidecar["model"],
                "stem": settings.stem,
                "ensemble": ensemble,
                "line": line,
                "fingerprint": wanted,
                "region": [low, high],
                "voiced_fraction": diagnostics.voiced_fraction,
                "notes": [
                    {
                        "onset": n.onset,
                        "duration": n.duration,
                        "pitch": n.pitch,
                        "confidence": n.confidence,
                    }
                    for n in notes
                ],
            }
            cache.write_text(json.dumps(runs), encoding="utf-8")
    # Only what is on disk NOW. The cache is keyed by track name and is only
    # ever added to, so a renamed or deleted track leaves its old entry behind
    # -- and everything downstream iterates these keys rather than the
    # sidecars. Renaming eight tracks scored all eight TWICE, once under each
    # name, and the WJazzD mean was quietly a mean over 32 where the truth was
    # 21. A deleted track would have gone on being scored forever.
    #
    # The stale entries stay in the FILE: they cost minutes of CREPE each and
    # come straight back if a rename is reverted. They just do not get scored.
    stale = sorted(set(runs) - live)
    if stale:
        log(f"  ignoring {len(stale)} cached run(s) with no track on disk: {', '.join(stale)}")
    return {name: run for name, run in runs.items() if name in live}


GRIDS_CACHE = Path(".benchmark-grids.json")


def beat_grids(cache: Path = GRIDS_CACHE, log=print) -> dict:
    """A beat grid for every sidecar'd track in benchmark/, reusing the cache.

    This used to be an external file passed with --grids, and the file went
    stale: it held 7 of the 12 tracks, so `summary/wjazz_beat_f1` was a mean
    over 4 solos while the note score next to it was a mean over 11. A
    benchmark that silently scores a subset is the same class of mistake as a
    fit that silently manufactures agreement, so the harness computes its own
    now -- affordable only because the grid no longer chains from a
    separation (stages/beats.py) and costs seconds.
    """
    from swingscribe.gui import library
    from swingscribe.stages import beats

    grids = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    for sidecar_path in sorted(BENCH.rglob("*.swingscribe.json")):
        # rglob and the subfolder-qualified key, matching transcribe_all. With
        # the flat glob this silently skipped every track under benchmark/
        # wjazzd/, which cost them their beat score AND their notation score --
        # the exact "scores a subset without saying so" failure this docstring
        # is about, reintroduced by making two of three globs recursive.
        name = sidecar_name(sidecar_path, json.loads(sidecar_path.read_text(encoding="utf-8")))
        cached = grids.get(name)
        # A grid cached before D27 holds the beats alone. The repaired bar
        # grid the harness notates on now also wants the downbeat layer (the
        # auto anchor's phase, when the sidecar has no downbeat) and the
        # track's length (how far the edge pulse may be extended), so such an
        # entry is tracked once more and keeps its beats.
        if (cached is not None and "duration" in cached) or not (BENCH / name).is_file():
            continue
        config = eval_config()
        document = library.ingested_document(BENCH / name, config)
        started = time.time()
        # No stems on the document: the mix is the source, and handing this
        # stage a drum stem would measure a grid the pipeline does not build.
        grid = beats.run(document, config).beat_grid
        entry = {
            "beats": [round(float(b), 4) for b in grid.beats],
            "downbeats": [round(float(b), 4) for b in grid.downbeats],
            "duration": round(float(document.audio.duration), 3),
            "source": grid.source,
        }
        if cached is not None and cached["beats"] != entry["beats"]:
            # The pinned numbers stand on the cached beats; a tracker that no
            # longer reproduces them is a finding to report, not a reason to
            # move them quietly. Its downbeats belong to the other grid.
            log(
                f"  {name}: re-tracked {len(entry['beats'])} beats against "
                f"{len(cached['beats'])} cached; keeping the cached grid, no downbeat layer"
            )
            entry.update(beats=cached["beats"], downbeats=[], source=cached.get("source", ""))
        log(f"  {name}: {len(entry['beats'])} beats in {time.time() - started:.0f}s")
        grids[name] = entry
        cache.write_text(json.dumps(grids), encoding="utf-8")
    return grids


def parallel_map(fn, tasks, jobs: int) -> list:
    """`fn` over `tasks`, in order, in `jobs` processes; one is a plain map.

    Every per-track scorer below is a pure function of its task tuple (the
    run's notes, its grid, the paths it reads), so the card cannot depend
    on the pool -- it was checked byte-identical against a single-process
    card when this landed (2026-09-21). What the pool buys: the harness is
    arithmetic and alignment on one core, ten minutes a run, and a rule is
    measured on the pages several times a day.
    """
    tasks = list(tasks)
    if jobs <= 1 or len(tasks) <= 1:
        return [fn(task) for task in tasks]
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=min(jobs, len(tasks))) as pool:
        return list(pool.map(fn, tasks, chunksize=1))


def _worker_setup(cache_dir: str) -> None:
    """A spawned worker re-imports this script fresh: give it the CLI's
    cache directory and the scripts folder on its path."""
    global CACHE_DIR
    CACHE_DIR = Path(cache_dir)
    scripts = str(Path(__file__).parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _wjazz_one(task: tuple) -> dict:
    name, run, grid, db_path, cache_dir = task
    import sqlite3

    import numpy as np

    _worker_setup(cache_dir)
    from score_wjazz import identify_all, score, score_beats

    db = sqlite3.connect(db_path)
    track = track_of(name)
    onsets = np.array([n["onset"] for n in run["notes"]])
    pitches = np.array([int(n["pitch"]) for n in run["notes"]])
    order = np.argsort(onsets)
    onsets, pitches = onsets[order], pitches[order]
    ordered = [run["notes"][i] for i in order]

    found, why = identify_all(db, track, onsets, pitches, run["region"])
    if not found:
        return {name: {"skipped": why}}
    out = {}
    for solo in found:
        result = score(solo, onsets, ordered)
        entry = {
            # The run these numbers came from: the notation scorer needs
            # its notes and grid, and cannot get the key back from a row
            # keyed "file [take] [performer]" by splitting.
            "run": name,
            "performer": solo["performer"],
            "instrument": solo["instrument"],
            "tempo": solo["tempo"],
            "melid": solo["melid"],
            # Where the annotated solo actually sits in OUR timeline. The
            # notation scorer needs it: a whole-track region notates the
            # head and every other soloist too, and a global aligner given
            # 450 reference notes against 1500 of ours is not measuring
            # notation any more.
            "solo_start": round(float(solo["ref_on"][0]) * solo["rate"] + solo["offset"], 3),
            "solo_end": round(float(solo["ref_on"][-1]) * solo["rate"] + solo["offset"], 3),
            "note_f1": round(result["note_f1"], 4),
            "note_precision": round(result["note_precision"], 4),
            "note_recall": round(result["note_recall"], 4),
            "onset_f1": round(result["onset_f1"], 4),
        }
        if grid is not None:
            beats = score_beats(db, solo["melid"], grid["beats"], solo["offset"], solo["rate"])
            if beats:
                entry["beat_f1"] = round(beats["f_measure"], 4)
        # One audio file can hold several annotated solos, so the row is
        # keyed by the solo, not by the file.
        key = name if len(found) == 1 else f"{name} [{solo['performer']}]"
        out[key] = entry
    return out


def wjazz_scores(db_path: Path, runs: dict, grids: dict, jobs: int = 1) -> dict:
    """Note and beat scores against WJazzD, for every take we can identify."""
    tasks = []
    for name, run in sorted(runs.items()):
        if is_located(name):
            # The sets stay disjoint. WJazzD annotated six of these very
            # sides, and benchmark/wjazzd/ already holds them under their own
            # names: identifying them here again would score the same
            # recording twice and move the WJazzD mean's population without
            # the pipeline having changed. A PDF page's recording is often a
            # copy of a WJazzD track (the "triples", docs/roadmap.md A1), so
            # the same holds for the pages.
            continue
        tasks.append((name, run, grids.get(track_of(name)), str(db_path), str(CACHE_DIR)))
    results = {
        task[0]: result
        for task, result in zip(
            [t for t in tasks if t[1]["notes"]],
            parallel_map(_wjazz_one, [t for t in tasks if t[1]["notes"]], jobs),
            strict=True,
        )
    }
    out = {}
    for name, run, *_rest in tasks:
        if not run["notes"]:
            # A span that transcribed to nothing is a finding, not a crash:
            # the fit has no onsets to place and indexes an empty array.
            out[name] = {"skipped": "transcribed no notes"}
            continue
        out.update(results[name])
    return out


def _mscz_one(task: tuple) -> dict:
    key, run, cache_dir = task
    _worker_setup(cache_dir)
    import score_benchmark

    scored = score_benchmark.score_tune(key, run)
    return {
        "pitch_f1": round(scored["pitch_f1"], 4),
        "chroma_f1": round(scored["chroma_f1"], 4),
        "onset_f1": round(scored["onset_f1"], 4),
        "note_f1": round(scored["note_f1"], 4),
    }


def mscz_scores(runs: dict, jobs: int = 1) -> dict:
    """Pitch, onset and note scores against the hand transcriptions."""
    sys.path.insert(0, str(Path(__file__).parent))
    import score_benchmark

    by_audio = {audio: key for key, (audio, *_rest) in score_benchmark.TUNES.items()}
    names, tasks = [], []
    for name, run in sorted(runs.items()):
        key = by_audio.get(track_of(name))
        if key is None:
            continue
        names.append(name)
        tasks.append((key, run, str(CACHE_DIR)))
    return dict(zip(names, parallel_map(_mscz_one, tasks, jobs), strict=True))


# How far either side of the located solo to notate. Enough that a bar is not
# clipped mid-phrase, small enough that the neighbouring soloist stays out.
SOLO_MARGIN_S = 1.0


def notate_run(name: str, run: dict, grid: dict, region: tuple[float, float] | None = None):
    """Everything from cached notes to a Notation: swing, quantize, notate.

    The stages below transcribe are all pure arithmetic, so this is a second
    or two per tune and needs no audio -- only the notes and the beat grid.
    The assembly itself lives in the package (swingscribe.notation), because
    the GUI's Export button needs exactly the same thing and a second copy of
    it here is how the scoring harness has gone wrong before (CLAUDE.md).
    """
    import json as _json

    from swingscribe.model import NoteEvent
    from swingscribe.notation import bar_grid_for_settings, meter_from_settings, notation_for_span

    track = track_of(name)  # the key may carry a take; the sidecar is the track's
    sidecar_path = BENCH / f"{track}.swingscribe.json"  # name carries any subfolder
    sidecar = {}
    if sidecar_path.is_file():
        sidecar = _json.loads(sidecar_path.read_text(encoding="utf-8"))

    config = eval_config()
    # The page the Score button scores is built on the REPAIRED grid, under
    # the sidecar's meter settings (gui/musicxml.bar_grid). Until D27 this
    # notated the raw tracked beats in 4/4, so every bar after a dropped or
    # doubled beat sat a beat off the listener's page. A grid cached before
    # then carries no length; its last beat stands in, which only forgoes the
    # extension past it.
    raw = grid["beats"]
    beats, anchor = bar_grid_for_settings(
        raw, grid.get("downbeats", []), sidecar, config, grid.get("duration") or raw[-1]
    )
    signature, pulses = meter_from_settings(
        sidecar.get("time_signature"), sidecar.get("pulses_per_bar"), config
    )
    return notation_for_span(
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
            # A region override means the run covers more music than we are
            # notating (a whole track against one annotated solo), so the
            # notes have to be cut to it as well as the beat grid.
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


def notation_scores(runs: dict, grids: dict, jobs: int = 1) -> dict:
    """Our notation against the hand transcription's, as notation.

    The comparison itself lives in `swingscribe.benchmark` -- anything that
    aligns our notes to a reference belongs in the package with tests, never
    in a script (CLAUDE.md), and the GUI's Score button needs the same numbers.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import score_benchmark

    by_audio = {audio: mscz_name for audio, mscz_name, *_ in score_benchmark.TUNES.values()}
    names, tasks = [], []
    for name, run in sorted(runs.items()):
        track = track_of(name)
        if track not in by_audio or track not in grids:
            continue
        names.append(name)
        tasks.append((name, run, grids[track], str(BENCH / by_audio[track]), str(CACHE_DIR)))
    results = parallel_map(_notation_one, tasks, jobs)
    return {name: entry for name, entry in zip(names, results, strict=True) if entry}


def _notation_one(task: tuple) -> dict | None:
    name, run, grid, score_path, cache_dir = task
    _worker_setup(cache_dir)
    from swingscribe import mscz
    from swingscribe.benchmark import readability, score_against_notation
    from swingscribe.score_bars import bar_line_agreement, bar_line_trace

    notation = notate_run(name, run, grid)
    if notation is None or not notation.bars:
        return None
    reference = mscz.parse_any(score_path)
    result = score_against_notation(notation, reference)
    if not result["n_matched"]:
        return None
    entry = {
        "rhythm": round(result["rhythm"], 4),
        "value": round(result["value"], 4),
        "n_matched": result["n_matched"],
        "bars": float(len(notation.bars)),
        "key_fifths": float(notation.key_fifths),
        # Whether the page is writable at all -- a question no comparison
        # against a reference can see. Folded in here rather than measured
        # in a pass of its own because the notation is already built.
        **readability(notation),
        # Rhythm compares gaps and cannot see a page whose every bar line
        # sits a beat off the reference's; this can (score_bars.py).
        **{k: round(v, 4) for k, v in bar_line_agreement(notation, reference).items()},
        **traced(bar_line_trace(notation, reference), reference.beats_per_bar),
    }
    if is_located(name):
        # A located span can be the wrong take, so its rhythm is never
        # read without its coverage (CLAUDE.md). The listener's rows
        # carry none: their spans were drawn by ear around one solo.
        entry["coverage"] = round(result["coverage"], 4)
        entry["trusted"] = float(bool(result["trusted"]))
    return entry


def wjazz_notation_scores(
    db_path: Path, card_wjazz: dict, runs: dict, grids: dict, jobs: int = 1
) -> dict:
    """Our notation against WJazzD's metrical annotation, per identified solo.

    This is the notation benchmark the MuseScore set cannot be on its own: ten
    hand transcriptions, all bebop eighth-note lines, can reward a grid rule
    for writing everything as eighths. WJazzD is hundreds of solos annotated by
    different people, with `division` running 1 through 10 — and it writes a
    swung pair as two eighths, which is the convention we target.

    Only `rhythm`: WJazzD stores metrical position, not notated value.
    """
    keys, tasks = [], []
    for key, entry in sorted(card_wjazz.items()):
        if "melid" not in entry:
            continue
        # The row may be keyed "file [performer]" when one file holds several
        # annotated solos, and "file [line=crepe]" for a pianist's second
        # take; the notes are the run's and the grid is the file's.
        name = entry.get("run") or key.split(" [")[0]
        track = track_of(name)
        if name not in runs or track not in grids:
            continue
        keys.append(key)
        tasks.append((name, entry, runs[name], grids[track], str(db_path), str(CACHE_DIR)))
    results = parallel_map(_wjazz_notation_one, tasks, jobs)
    return {key: entry for key, entry in zip(keys, results, strict=True) if entry}


def _wjazz_notation_one(task: tuple) -> dict | None:
    name, entry, run, grid, db_path, cache_dir = task
    import sqlite3

    _worker_setup(cache_dir)
    from swingscribe.benchmark import readability, score_against_wjazz_notation
    from swingscribe.score_bars import wjazz_bar_line_agreement, wjazz_bar_line_trace
    from swingscribe.wjazz import notated_beats, notated_positions

    db = sqlite3.connect(db_path)
    # Notate ONLY the located solo, not the whole track. The alignment
    # underneath is global on purpose (both sides are meant to cover the
    # same music), so handing it a five-minute notation against a
    # one-chorus annotation measures nothing about notation.
    window = (entry["solo_start"] - SOLO_MARGIN_S, entry["solo_end"] + SOLO_MARGIN_S)
    notation = notate_run(name, run, grid, region=window)
    if notation is None or not notation.bars:
        return None
    # Readability is a property of OUR page and needs no reference, so it
    # is recorded even for a solo the alignment could not line up. That is
    # the point of having it: it is the one number every notation the
    # harness can build contributes to.
    out = dict(readability(notation))
    result = score_against_wjazz_notation(notation, notated_positions(db, entry["melid"]))
    if not result["n_matched"]:
        return out
    out.update(
        {
            "rhythm": round(result["rhythm"], 4),
            "n_matched": result["n_matched"],
            "coverage": round(result["coverage"], 4),
            "trusted": float(bool(result["trusted"])),
        }
    )
    # Whether our bar lines are the annotator's. Rhythm above is
    # gap-based and cannot see a page that starts on the wrong beat;
    # WJazzD's bar/beat/tatum can (score_bars.py). Absent for a solo
    # whose beat is not a quarter or whose metre is not the page's.
    positions, bar = notated_beats(db, entry["melid"])
    agreement = wjazz_bar_line_agreement(notation, positions, bar)
    if agreement["beat_n"]:
        out.update({k: round(v, 4) for k, v in agreement.items()})
        out.update(traced(wjazz_bar_line_trace(notation, positions, bar), bar))
    return out


def readable_pages(card: dict) -> dict:
    """Every notation this run built, keyed uniquely, for the readability mean.

    Both notation sections contribute. WJazzD keys carry a performer suffix
    when one file holds several annotated solos and the hand-scored keys are
    bare filenames, so nothing collides -- but the two sections DO notate some
    of the same audio over different regions, which is why this reads them as
    separate pages rather than deduplicating by track.
    """
    pages = {}
    for section, prefix in (("notation", ""), ("wjazz_notation", "wjazz:")):
        for name, entry in card.get(section, {}).items():
            # The second take's pages are pinned per track but kept out of the
            # mean, which is a mean over what SHIPS by default; folding a
            # second page per pianist in would move it without the pipeline
            # having changed.
            if "readability" in entry and take_of(name) is None:
                pages[prefix + name] = entry
    return pages


def traced(trace: dict, bar: float) -> dict:
    """What a page's bar-line trace adds to its row. `on_the_bar` says a page
    is off; the trace says WHERE and which kind: `beat_steps` counts the
    places the page leaves or rejoins its bar lines (a beat the grid dropped
    or doubled, a chorus the reference omits), `beat_slope` is our quarters
    per reference quarter (0.5 or 2.0 is a grid at the wrong pulse), and
    `trace` is the sentence a person reads -- a string, so never pinned."""
    from swingscribe.score_bars import describe_trace

    if not trace["matches"]:
        return {}
    return {
        "beat_steps": float(len(trace["steps"])),
        "beat_slope": round(trace["slope"], 3),
        "trace": describe_trace(trace, bar),
    }


# A page is traced on the scorecard when its bar lines are in doubt: off the
# reference's, or fewer than this share of its matched notes at one offset.
TRACE_BELOW_SHARE = 0.75


def trace_line(entry: dict) -> str:
    in_doubt = entry.get("beat_n") and (
        entry["beat_offset"] != 0.0
        or entry["beat_share"] < TRACE_BELOW_SHARE
        or entry.get("beat_steps")
    )
    return f"\n      -> {entry['trace']}" if in_doubt and entry.get("trace") else ""


def bar_cell(entry: dict) -> str:
    """`on_the_bar` for a notation row, and a loud flag when the page's bar
    lines are not the reference's: the number alone reads like a bad rhythm
    score, and this is a different and much cheaper defect -- one downbeat."""
    if not entry.get("beat_n"):
        return f"{'-':>7s}"
    cell = f"{entry['on_the_bar']:7.3f}"
    if entry["beat_offset"] != 0.0:
        cell += (
            f"   OFF THE BAR: {entry['beat_share']:.0%} of matched notes sit "
            f"{entry['beat_offset']:+.1f} beats from the reference's"
        )
    return cell


def placement_summary(rows: dict, prefix: str) -> dict:
    """The set's mean `on_the_bar` and how many of its pages sit on the
    reference's bar lines -- default takes, trusted pairings only. A page a
    beat off reads under 0.1 where a right one reads 0.8-0.95, so one wrong
    downbeat in twenty moves the mean by 0.04: this is the number that
    PENALIZES starting on the wrong beat, which rhythm cannot."""
    judged = [
        e
        for name, e in rows.items()
        if e.get("beat_n") and e.get("trusted", 1.0) and take_of(name) is None
    ]
    if not judged:
        return {}
    return {
        f"{prefix}_placement": round(statistics.fmean(e["on_the_bar"] for e in judged), 4),
        f"{prefix}_on_the_bar": float(sum(1 for e in judged if e["beat_offset"] == 0.0)),
        f"{prefix}_on_the_bar_n": float(len(judged)),
    }


def print_placement(summary: dict, prefix: str) -> None:
    if f"{prefix}_placement" in summary:
        print(
            f"\n  mean on-the-bar {summary[f'{prefix}_placement']:.3f}; "
            f"{int(summary[f'{prefix}_on_the_bar'])} of "
            f"{int(summary[f'{prefix}_on_the_bar_n'])} pages on the reference's bar lines"
        )


def tier_of(entry: dict) -> str:
    """A page row's reference tier, carried as a pinned 1/0 so a page that
    changes tier shows in the diff."""
    return "silver" if entry.get("silver") else "bronze"


def render_located(rows: dict, notation: dict) -> None:
    """The Omnibook's table, used for any set whose spans were placed by
    content: pitch and note beside the page's rhythm, value, readability
    and bar line, never a rhythm without its coverage."""
    header = (
        f"  {'tune':<26s} {'pitch':>6s} {'note':>6s} {'bars':>5s} {'cover':>6s} "
        f"{'rhythm':>7s} {'value':>6s} {'read':>7s} {'bar line':>9s}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, e in sorted(rows.items()):
        n = notation.get(name, {})

        def cell(field: str, width: int, digits: int, n=n) -> str:
            return f"{n[field]:{width}.{digits}f}" if field in n else f"{'-':>{width}s}"

        flag = "" if n.get("trusted", 1.0) else "   (untrusted — too little lined up)"
        # Beats our bar lines sit from the book's, and the share of
        # matched notes that say so: "+0.0 91%" is a page on its bars.
        bar_line = f"{n['beat_offset']:+5.1f} {n['beat_share']:3.0%}" if n.get("beat_n") else "-"
        print(
            f"  {Path(name).stem[:26]:<26s} {e['pitch_f1']:6.3f} {e['note_f1']:6.3f} "
            f"{cell('bars', 5, 0)} {cell('coverage', 6, 3)} {cell('rhythm', 7, 3)} "
            f"{cell('value', 6, 3)} {cell('readability', 7, 4)} {bar_line:>9s}{flag}"
            f"{trace_line(n)}"
        )


def print_located_summary(s: dict, prefix: str, unit: str) -> None:
    if f"{prefix}_pitch_f1" in s:
        print(
            f"\n  mean pitch F1 {s[f'{prefix}_pitch_f1']:.3f}   note F1 "
            f"{s[f'{prefix}_note_f1']:.3f}   over {int(s[f'{prefix}_n'])} {unit}"
        )
    if f"{prefix}_rhythm" in s:
        print(
            f"  mean rhythm {s[f'{prefix}_rhythm']:.3f}   value {s[f'{prefix}_value']:.3f}"
            f"   over {int(s[f'{prefix}_rhythm_n'])} trusted"
        )
    print_placement(s, prefix)
    if f"{prefix}_readability" in s:
        print(
            f"  mean readability {s[f'{prefix}_readability']:.4f} over "
            f"{int(s[f'{prefix}_readability_n'])} notation(s)"
        )


def located_summary(rows: dict, notation: dict, prefix: str) -> dict:
    """The means of a set whose spans were located by content, over the
    DEFAULT take: pitch and note over every row, rhythm and value over the
    trusted pairings only, placement, readability."""
    out: dict[str, float] = {}
    scored = [e for k, e in rows.items() if take_of(k) is None]
    if scored:
        out[f"{prefix}_pitch_f1"] = round(statistics.fmean(e["pitch_f1"] for e in scored), 4)
        out[f"{prefix}_note_f1"] = round(statistics.fmean(e["note_f1"] for e in scored), 4)
        out[f"{prefix}_n"] = float(len(scored))
    pages = {k: e for k, e in notation.items() if take_of(k) is None}
    trusted = [e for e in pages.values() if e.get("trusted")]
    if trusted:
        out[f"{prefix}_rhythm"] = round(statistics.fmean(e["rhythm"] for e in trusted), 4)
        out[f"{prefix}_value"] = round(statistics.fmean(e["value"] for e in trusted), 4)
        out[f"{prefix}_rhythm_n"] = float(len(trusted))
    out.update(placement_summary(notation, prefix))
    readable = [e for e in pages.values() if "readability" in e]
    if readable:
        out[f"{prefix}_readability"] = round(
            statistics.fmean(e["readability"] for e in readable), 4
        )
        out[f"{prefix}_readability_n"] = float(len(readable))
    return out


def render(card: dict) -> None:
    wjazz = {k: v for k, v in card["wjazz"].items() if "skipped" not in v}
    skipped = {k: v for k, v in card["wjazz"].items() if "skipped" in v}

    print("\n== WJazzD: our timestamps against a human's, same recording ==")
    if wjazz:
        header = (
            f"  {'tune':<26s} {'soloist':<20s} {'inst':>4s} {'bpm':>5s}  "
            f"{'note':>6s} {'P':>6s} {'R':>6s} {'beat':>6s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name, e in sorted(wjazz.items(), key=lambda kv: -kv[1]["note_f1"]):
            beat = f"{e['beat_f1']:.3f}" if "beat_f1" in e else "  -  "
            print(
                f"  {Path(name).stem[:26]:<26s} {e['performer'][:20]:<20s} {e['instrument']:>4s} "
                f"{e['tempo'] or 0:5.0f}  {e['note_f1']:6.3f} {e['note_precision']:6.3f} "
                f"{e['note_recall']:6.3f} {beat:>6s}"
            )
        # Each mean states its own n. They are not always the same n -- a solo
        # can be note-scored with no beat grid -- and printing one count for
        # both is how the two came to be read as the same population.
        note_n = int(card["summary"]["wjazz_note_n"])
        beat_n = int(card["summary"].get("wjazz_beat_n", 0))
        note_f1 = card["summary"]["wjazz_note_f1"]
        beat_f1 = card["summary"]["wjazz_beat_f1"]
        print(f"\n  mean note F1 {note_f1:.3f} over {note_n} solos", end="")
        print(f"   mean beat F1 {beat_f1:.3f} over {beat_n} solos")
    for name, e in sorted(skipped.items()):
        print(f"  (not scored) {Path(name).stem[:30]:<30s} {e['skipped']}")

    if card.get("notation"):
        print("\n== Notation: our score against the hand transcription, as notation ==")
        header = (
            f"  {'tune':<30s} {'bars':>5s} {'matched':>8s} {'rhythm':>8s} {'value':>7s} "
            f"{'on bar':>7s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name, entry in sorted(card["notation"].items()):
            print(
                f"  {Path(name).stem[:30]:<30s} {int(entry['bars']):5d} "
                f"{int(entry['n_matched']):8d} {entry['rhythm']:8.3f} {entry['value']:7.3f} "
                f"{bar_cell(entry)}{trace_line(entry)}"
            )
        print_placement(card["summary"], "mscz")

    if card.get("wjazz_notation"):
        print("\n== Flex-Q: our page against WJazzD's ALGORITHMIC quantisation of the onsets ==")
        print(
            "  (collateral only -- dropped notes, bar count, placement. Not a page measure:"
            " the tatum layer is Flex-Q's, more literal than any transcriber, D36)"
        )
        header = f"  {'solo':<34s} {'matched':>8s} {'cover':>7s} {'rhythm':>8s} {'on bar':>7s}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        rows = sorted(card["wjazz_notation"].items())
        for name, entry in rows:
            if "rhythm" not in entry:
                print(f"  {Path(name).stem[:34]:<34s} {'-':>8s}   (nothing lined up)")
                continue
            flag = "" if entry["trusted"] else "   (untrusted — too little lined up)"
            print(
                f"  {Path(name).stem[:34]:<34s} {int(entry['n_matched']):8d} "
                f"{entry['coverage']:7.3f} {entry['rhythm']:8.3f} {bar_cell(entry)}{flag}"
                f"{trace_line(entry)}"
            )
        print_placement(card["summary"], "wjazz")
        trusted = [e for _n, e in rows if e.get("trusted")]
        if trusted:
            print(
                f"\n  mean rhythm {statistics.fmean(e['rhythm'] for e in trusted):.3f} "
                f"over {len(trusted)} solo(s)"
            )

    pages = readable_pages(card)
    if pages:
        print("\n== Readability: is the page writable at all? (no reference needed) ==")
        header = (
            f"  {'notation':<34s} {'events':>7s} {'rest<8th':>9s} "
            f"{'note<16th':>10s} {'ties':>6s} {'score':>7s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name, e in sorted(pages.items(), key=lambda kv: kv[1]["readability"]):
            print(
                f"  {Path(name).stem[:34]:<34s} {int(e['events']):7d} "
                f"{e['short_rests']:9.2f} {e['short_values']:10.2f} "
                f"{e['tie_rate']:6.3f} {e['readability']:7.4f}"
            )
        print(
            f"\n  mean readability {card['summary']['readability']:.4f} "
            f"over {int(card['summary']['readability_n'])} notation(s)"
        )
        # The target, counted off the ten hand transcriptions in benchmark/:
        # 6 sub-eighth rests in 487 rests, 13 sub-sixteenth notes in 3646.
        print("  a human writes 0.995 (benchmark/*.mscz: 6 short rests, 13 short values)")

    print("\n== MuseScore: our audio against notated rhythm ==")
    header = f"  {'tune':<30s} {'pitch':>7s} {'chroma':>7s} {'onset':>7s} {'note':>7s}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, e in sorted(card["mscz"].items()):
        print(
            f"  {Path(name).stem[:30]:<30s} {e['pitch_f1']:7.3f} {e['chroma_f1']:7.3f} "
            f"{e['onset_f1']:7.3f} {e['note_f1']:7.3f}"
        )
    if card["mscz"]:
        print(f"\n  mean note F1 {card['summary']['mscz_note_f1']:.3f}")

    if card.get("omnibook"):
        print("\n== Omnibook: Parker's recordings against LORIA's MusicXML of the book ==")
        print("  (pitch and note as the MuseScore set; rhythm and value never without coverage)")
        render_located(card["omnibook"], card.get("omnibook_notation", {}))
        print_located_summary(card["summary"], "omnibook", "sides")

    if card.get("pages"):
        print("\n== PDF pages: recordings against the OMR reading of a human's transcription ==")
        print(
            "  (silver: a vector page whose printed notes were counted and read, bars filled;"
            " bronze: the rest, scans included. Never folded into the sets above)"
        )
        for tier in TIERS:
            rows = {k: e for k, e in card["pages"].items() if tier_of(e) == tier}
            if not rows:
                continue
            print(f"\n  -- {tier} --")
            render_located(rows, card.get("pages_notation", {}))
            print_located_summary(card["summary"], f"pages_{tier}", "pages")

    takes = sorted(k for k in card["mscz"] if take_of(k) is None and second_key(k) in card["mscz"])
    if takes:
        print(f"\n== Pianists: the default line against the {SECOND_LINE} take (issue #8) ==")
        print(f"  (default / {SECOND_LINE}; rhythm with its matched count, hand score as notation)")
        header = f"  {'tune':<30s} {'pitch':>15s} {'note':>15s} {'rhythm':>17s}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for name in takes:
            a, b = card["mscz"][name], card["mscz"][second_key(name)]
            na = card.get("notation", {}).get(name)
            nb = card.get("notation", {}).get(second_key(name))
            rhythm = "-"
            if na and nb:
                matched = f"({int(na['n_matched'])}/{int(nb['n_matched'])})"
                rhythm = f"{na['rhythm']:.3f}/{nb['rhythm']:.3f} {matched}"
            print(
                f"  {Path(name).stem[:30]:<30s} {a['pitch_f1']:7.3f}/{b['pitch_f1']:<7.3f} "
                f"{a['note_f1']:7.3f}/{b['note_f1']:<7.3f} {rhythm:>17s}"
            )
        s = card["summary"]
        if "pianist_pitch_f1" in s:
            pitch = f"{s['pianist_pitch_f1']:.3f} / {s['pianist_pitch_f1_crepe']:.3f}"
            note = f"{s['pianist_note_f1']:.3f} / {s['pianist_note_f1_crepe']:.3f}"
            print(
                f"\n  mean pitch F1 {pitch}   note F1 {note}"
                f"   over {int(s['pianist_pitch_f1_n'])} pianists"
            )
        if "pianist_rhythm" in s:
            print(
                f"  mean rhythm {s['pianist_rhythm']:.3f} / {s['pianist_rhythm_crepe']:.3f}"
                f" over {int(s['pianist_rhythm_n'])}"
            )
        if "wjazz_pianist_note_f1" in s:
            print(
                f"  WJazzD note F1 {s['wjazz_pianist_note_f1']:.3f} / "
                f"{s['wjazz_pianist_note_f1_crepe']:.3f} over {int(s['wjazz_pianist_note_f1_n'])}"
            )


def paired_takes(section: dict, field: str) -> tuple[list[float], list[float]]:
    """`field` for every default-take row whose second take is also in
    `section` and carries the field: (default values, second values), aligned."""
    default, second = [], []
    for key, entry in sorted(section.items()):
        if take_of(key) is not None or field not in entry:
            continue
        other = section.get(second_key(key))
        if other is None or field not in other:
            continue
        default.append(float(entry[field]))
        second.append(float(other[field]))
    return default, second


def flatten(card: dict) -> dict[str, float]:
    """Every number the baselines pin, as one flat name -> value mapping."""
    flat = {}
    for name, entry in card["wjazz"].items():
        for field, value in entry.items():
            if isinstance(value, (int, float)):
                flat[f"wjazz/{pin_name(name)}/{field}"] = float(value)
    for name, entry in card["mscz"].items():
        for field, value in entry.items():
            flat[f"mscz/{pin_name(name)}/{field}"] = float(value)
    for name, entry in card.get("notation", {}).items():
        for field, value in entry.items():
            if isinstance(value, (int, float)):
                flat[f"notation/{pin_name(name)}/{field}"] = float(value)
    for name, entry in card.get("wjazz_notation", {}).items():
        for field, value in entry.items():
            if isinstance(value, (int, float)):
                flat[f"wjazz-notation/{pin_name(name)}/{field}"] = float(value)
    for section, prefix in (
        ("omnibook", "omnibook"),
        ("omnibook_notation", "omnibook-notation"),
        ("pages", "pages"),
        ("pages_notation", "pages-notation"),
    ):
        for name, entry in card.get(section, {}).items():
            for field, value in entry.items():
                if isinstance(value, (int, float)):
                    flat[f"{prefix}/{pin_name(name)}/{field}"] = float(value)
    for field, value in card["summary"].items():
        flat[f"summary/{field}"] = float(value)
    return flat


# The per-track measures a set's headline means are made of, and so the ones
# whose change is summarised paired (`paired_changes`).
HEADLINE_FIELDS = ("note_f1", "pitch_f1", "beat_f1", "rhythm", "value", "readability", "on_the_bar")
# Measures a pairing must be trusted for on BOTH sides: a located page below
# the coverage floor has no rhythm worth comparing (CLAUDE.md).
TRUSTED_FIELDS = ("rhythm", "value", "on_the_bar")


def recording_of(pinned_track: str) -> str:
    """The recording a pinned row belongs to: a WJazzD file holding several
    annotated solos pins one row per soloist ("file [performer]"), and those
    rows are not independent draws."""
    return pinned_track.split(" [")[0]


def paired_changes(before: dict[str, float], after: dict[str, float]) -> list[tuple]:
    """(set, measure, PairedChange) for every headline measure of every set in
    which at least one track moved past TOLERANCE, over the tracks both sides
    hold. Default takes only -- the means describe what ships -- and trusted
    pairings only where trust is defined."""
    from swingscribe.evaluation import paired_change

    grouped: dict[tuple[str, str], list[tuple[str, float, float]]] = {}
    for key, now in after.items():
        section, _, rest = key.partition("/")
        if section == "summary" or key not in before:
            continue
        track, _, field = rest.rpartition("/")
        if field not in HEADLINE_FIELDS or take_of(track) is not None:
            continue
        if field in TRUSTED_FIELDS:
            trust = f"{section}/{track}/trusted"
            if before.get(trust, 1.0) < 1.0 or after.get(trust, 1.0) < 1.0:
                continue
        grouped.setdefault((section, field), []).append((track, before[key], now))
    out = []
    for (section, field), rows in sorted(grouped.items()):
        if not any(abs(now - was) > TOLERANCE for _t, was, now in rows):
            continue
        change = paired_change(
            [was for _t, was, _n in rows],
            [now for _t, _w, now in rows],
            [recording_of(track) for track, _w, _n in rows],
            tolerance=TOLERANCE,
        )
        out.append((section, field, change))
    return out


def print_paired(changes: list[tuple]) -> None:
    if not changes:
        return
    print(
        "\n== Paired changes: the same tracks before and after "
        "(95% interval resampled by recording; up/down/level and the sign test by recording) =="
    )
    header = (
        f"  {'set / measure':<30s} {'n':>4s} {'rec':>4s} {'mean change':>12s} "
        f"{'95% interval':>21s} {'up':>4s} {'down':>5s} {'level':>6s} {'sign p':>7s}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for section, field, c in changes:
        mark = "  *" if c.decided else ""
        print(
            f"  {section + ' / ' + field:<30s} {c.n:4d} {c.recordings:4d} {c.mean:+12.4f} "
            f"   [{c.low:+.4f}, {c.high:+.4f}] {c.up:4d} {c.down:5d} {c.level:6d} {c.p:7.3f}{mark}"
        )
    print("  * the interval excludes zero")


def compare(card: dict, baselines: Path = BASELINES, pinned: dict | None = None) -> int:
    """Diff against the pinned baselines, or against `pinned` (a flattened
    scorecard, `--against`). Returns a process exit code: a moved pin is a
    failure, a difference from another run is information."""
    against = pinned is not None
    if pinned is None:
        if not baselines.is_file():
            print(f"\nNo baselines pinned yet. Run with --pin to create {baselines}.")
            return 0
        pinned = json.loads(baselines.read_text(encoding="utf-8"))
    current = flatten(card)
    moved, appeared, vanished = [], [], []
    for key, value in sorted(current.items()):
        if key not in pinned:
            appeared.append(key)
        elif abs(value - pinned[key]) > TOLERANCE:
            moved.append((key, pinned[key], value))
    vanished = sorted(set(pinned) - set(current))

    label = "Against the other card" if against else "Baselines"
    if not (moved or appeared or vanished):
        print(f"\n== {label}: all {len(current)} numbers unchanged ==")
        return 0
    print(f"\n== {label}: CHANGED ==")
    for key, was, now in moved:
        print(f"  {key:<48s} {was:7.4f} -> {now:7.4f}  ({now - was:+.4f})")
    for key in appeared:
        print(f"  {key:<48s}      new -> {current[key]:7.4f}")
    for key in vanished:
        print(f"  {key:<48s} {pinned[key]:7.4f} -> gone")
    print_paired(paired_changes(pinned, current))
    if against:
        return 0
    print("\nIf this is intended, say so explicitly and re-pin with --pin (CLAUDE.md).")
    return 1


def default_jobs() -> int:
    import os

    # Half the cores, capped: each worker imports numpy, scipy and mir_eval,
    # and on the 16 GB dev machine ten of them pushed the commit charge past
    # the page file ("DLL load failed ... paging file is too small" from
    # scipy's HiGHS wrapper) with 23 GB of 32 already in use by the
    # browser, MuseScore and the app. Four is well inside it and takes the
    # run from ten minutes to about three.
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def main() -> None:
    global CACHE_DIR

    parser = argparse.ArgumentParser(description="Score everything and print one scorecard.")
    parser.add_argument("--db", type=Path, default=None, help="wjazzd.db; skips WJazzD if absent")
    parser.add_argument(
        "--grids", type=Path, default=GRIDS_CACHE, help=f"beat-grid cache (default {GRIDS_CACHE})"
    )
    parser.add_argument("--step-cost", type=float, default=0.2)
    parser.add_argument("--dip-db", type=float, default=0.0)
    parser.add_argument("--pin", action="store_true", help="rewrite the baselines from this run")
    parser.add_argument("--json", type=Path, default=None, help="also write the scorecard here")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"stage cache to read stems from (default {CACHE_DIR}; the batch's is "
        "benchmark/.swingscribe-cache)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=default_jobs(),
        help="processes for the per-track scoring (default: half the cores); 1 is in-process",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="score the locked TEST split alone, against its own pins (a release, not tuning)",
    )
    parser.add_argument(
        "--against",
        type=Path,
        default=None,
        help="compare with a scorecard saved by --json instead of the pins (an A/B run)",
    )
    args = parser.parse_args()
    if args.cache_dir is not None:
        CACHE_DIR = args.cache_dir.resolve()
    if args.pin and args.against:
        raise SystemExit("--pin rewrites the pins; --against compares with a card. Pick one.")

    cache = notes_cache(args.step_cost, args.dip_db)
    print(f"== Transcribing (step cost {args.step_cost}, dip {args.dip_db} dB), cache {cache} ==")
    runs = transcribe_all(cache, args.step_cost, args.dip_db)
    runs = split_runs(runs, args.db, test=args.test)
    if args.test and not runs:
        print("\nNo test-split track is in benchmark/ yet; nothing to score.")
        return
    print(f"== Beat grids, cache {args.grids} ==")
    grids = beat_grids(args.grids)

    print(f"== Scoring in {args.jobs} process(es) ==")
    wjazz = wjazz_scores(args.db, runs, grids, args.jobs) if args.db else {}
    # The Omnibook set and the PDF pages are scored by the same two functions
    # and then kept apart (OMNIBOOK_FOLDER, PAGES_FOLDER), so the MuseScore
    # sections stay the listener's.
    scored = mscz_scores(runs, args.jobs)
    notated = notation_scores(runs, grids, args.jobs) if grids else {}
    tiers = page_tiers(runs)
    for section in (scored, notated):
        for key, entry in section.items():
            if is_page(key):
                entry["silver"] = float(tiers.get(track_of(key)) == "silver")

    def own(section: dict) -> dict:
        return {k: v for k, v in section.items() if not is_located(k)}

    card = {
        "settings": {"step_cost": args.step_cost, "dip_db": args.dip_db},
        "wjazz": wjazz,
        "mscz": own(scored),
        "notation": own(notated),
        "omnibook": {k: v for k, v in scored.items() if is_omnibook(k)},
        "omnibook_notation": {k: v for k, v in notated.items() if is_omnibook(k)},
        "pages": {k: v for k, v in scored.items() if is_page(k)},
        "pages_notation": {k: v for k, v in notated.items() if is_page(k)},
        # WJazzD carries a human's NOTATION as well as their onsets, so the
        # same solos answer both questions.
        "wjazz_notation": (
            wjazz_notation_scores(args.db, wjazz, runs, grids, args.jobs)
            if args.db and grids
            else {}
        ),
        "summary": {},
    }
    # Every mean below is over the DEFAULT take: it describes what ships. The
    # second take is pinned per track and summarised paired, further down.
    scored = [e for k, e in card["wjazz"].items() if "skipped" not in e and take_of(k) is None]
    if scored:
        card["summary"]["wjazz_note_f1"] = round(statistics.fmean(e["note_f1"] for e in scored), 4)
        card["summary"]["wjazz_note_n"] = float(len(scored))
        beats = [e["beat_f1"] for e in scored if "beat_f1" in e]
        if beats:
            card["summary"]["wjazz_beat_f1"] = round(statistics.fmean(beats), 4)
            # Pinned so the denominator can never change silently. It already
            # did once: beat F1 was a mean over the 4 solos that happened to
            # have a cached grid, printed beside a note F1 over 11, and the
            # gap read as agreement between two numbers that were measuring
            # different populations.
            card["summary"]["wjazz_beat_n"] = float(len(beats))
    pages = readable_pages(card)
    if pages:
        card["summary"]["readability"] = round(
            statistics.fmean(e["readability"] for e in pages.values()), 4
        )
        card["summary"]["readability_n"] = float(len(pages))
    default_mscz = [e for k, e in card["mscz"].items() if take_of(k) is None]
    if default_mscz:
        card["summary"]["mscz_note_f1"] = round(
            statistics.fmean(e["note_f1"] for e in default_mscz), 4
        )
        card["summary"]["mscz_note_n"] = float(len(default_mscz))
    # The Omnibook set, in means of its own, so every mean above stays over
    # the music it was pinned on. All horns, so no oracle take to keep out.
    card["summary"].update(located_summary(card["omnibook"], card["omnibook_notation"], "omnibook"))
    # The PDF pages, per tier: a silver page and a scan are different kinds
    # of reference, and neither is a hand score (docs/roadmap.md, E3).
    for tier in TIERS:
        card["summary"].update(
            located_summary(
                {k: e for k, e in card["pages"].items() if tier_of(e) == tier},
                {k: e for k, e in card["pages_notation"].items() if tier_of(e) == tier},
                f"pages_{tier}",
            )
        )
    card["summary"].update(placement_summary(card["notation"], "mscz"))
    card["summary"].update(placement_summary(card["wjazz_notation"], "wjazz"))
    # The pianists on both lines, PAIRED: the same tracks under each mean, so
    # the difference is the take's and not the population's.
    for section, field, label in (
        ("mscz", "pitch_f1", "pianist_pitch_f1"),
        ("mscz", "note_f1", "pianist_note_f1"),
        ("notation", "rhythm", "pianist_rhythm"),
        ("wjazz", "note_f1", "wjazz_pianist_note_f1"),
    ):
        default, second = paired_takes(card.get(section, {}), field)
        if default:
            card["summary"][label] = round(statistics.fmean(default), 4)
            card["summary"][f"{label}_{SECOND_LINE}"] = round(statistics.fmean(second), 4)
            card["summary"][f"{label}_n"] = float(len(default))

    render(card)
    if args.json:
        args.json.write_text(json.dumps(card, indent=2), encoding="utf-8")

    baselines = TEST_BASELINES if args.test else BASELINES
    if args.pin:
        baselines.parent.mkdir(parents=True, exist_ok=True)
        baselines.write_text(json.dumps(flatten(card), indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nPinned {len(flatten(card))} numbers to {baselines}.")
        return
    if args.against:
        other = flatten(json.loads(args.against.read_text(encoding="utf-8")))
        raise SystemExit(compare(card, pinned=other))
    raise SystemExit(compare(card, baselines))


def split_runs(runs: dict, db_path: Path | None, test: bool, log=print) -> dict:
    """The runs this invocation may score: the dev split, or with `test` the
    test split alone. Says how many it held back, never silently."""
    from swingscribe.evaluation import load_split

    if not SPLIT_FILE.is_file():
        log(f"  no {SPLIT_FILE}: every track is scored, none is held out")
        return runs if not test else {}
    split = load_split(SPLIT_FILE)
    db = None
    if db_path is not None:
        import sqlite3

        db = sqlite3.connect(db_path)
    held: set[str] = set()
    sidecars: dict[str, dict] = {}
    for key in runs:
        track = track_of(key)
        if track not in sidecars:
            path = BENCH / f"{track}.swingscribe.json"
            sidecars[track] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if held_out(track, sidecars[track], split, db):
            held.add(key)
    if test:
        log(f"  scoring the TEST split: {len(held)} run(s)")
        return {k: v for k, v in runs.items() if k in held}
    if held:
        log(f"  held out: {len(held)} test-split run(s), scored only by --test at a release")
    return {k: v for k, v in runs.items() if k not in held}


def page_tiers(runs: dict) -> dict[str, str]:
    """The reference tier of every PDF page among the runs, by track."""
    tiers = {}
    for key in runs:
        track = track_of(key)
        if not is_page(track) or track in tiers:
            continue
        path = BENCH / f"{track}.swingscribe.json"
        score = page_score(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else None
        tiers[track] = page_quality(score)[0] if score is not None else "bronze"
    return tiers


if __name__ == "__main__":
    main()
