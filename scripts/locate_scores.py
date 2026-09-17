"""Place a score that has no span, by content, and write the track's sidecar.

    uv run python scripts/locate_scores.py --folder Omnibook
    uv run python scripts/locate_scores.py --folder Omnibook --file Confirmation.m4a
    uv run python scripts/locate_scores.py --folder Omnibook --dry-run
    uv run python scripts/locate_scores.py --folder Omnibook --bars-only

The listener's own transcriptions in benchmark/ arrive with a span drawn by
ear around one solo, so bar 1 of the score is the span's start by
construction. The Omnibook set does not: benchmark/Omnibook/ holds LORIA's
MusicXML of the book beside whichever of the fifty recordings the listener
could find, and each score covers the head and Parker's choruses of a whole
side, from wherever on the record that starts.

So for every audio file with a score of the same name beside it, this
transcribes the WHOLE file -- ingest, beats, a whole-file separation,
transcribe, through `pipeline.run`, so every step is cached and a second
run costs nothing -- and asks `swingscribe.benchmark.locate_score` where the
score sits: the time-free aligner pairs the score's pitches with what we
heard, and a robust line through the pairs is the score's clock. That line
says WHERE the score is and not where its bar lines are -- a side's tempo
breathes, and the line's intercept put eleven of the twenty-two pages one to
two beats off the book's (2026-09-17) -- so the same pairs then vote on the
tracked beat grid (`swingscribe.score_bars`): bar 1, the last bar line and
the downbeat are beats of the grid the page is built on. A trusted
placement is written into the sidecar exactly as a listener's span would be
(region, the bar-1 anchor, the score's path, model, stem, ensemble), and
from then on the track is an ordinary benchmark tune: `benchmark_batch.py
--folder Omnibook` writes its row and `run_eval.py` pins its numbers.

Two things it refuses to do. It never writes a span below the coverage floor
-- the wrong take (most Parker sides exist in several), or a transcription
too poor to place -- and says so instead; and it never replaces a span the
sidecar already holds unless `--relocate`, because the listener may have
corrected one by hand. `--bars-only` is the half-step between: the stored
span stays exactly as it is (so no transcription or review keyed on it is
thrown away) and only the downbeat is voted again.

Standing where the cache expects: this chdirs to the cache's parent, as the
batch scripts do, so the relative paths inside cached Documents resolve the
way they do for the GUI (wjazz_batch.py, "Standing where the cache expects").
Nothing it writes may be committed: benchmark/ is gitignored whole.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmark"
DEFAULT_CACHE_DIR = BENCH_DIR / ".swingscribe-cache"

sys.path.insert(0, str(REPO_ROOT / "src"))

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac"}
SCORE_SUFFIXES = (".xml", ".musicxml", ".mscz", ".mscx")


def score_beside(audio: Path) -> Path | None:
    """The score named like the audio, in the folder beside it."""
    for suffix in SCORE_SUFFIXES:
        candidate = audio.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def marked_tempo(score_path: Path) -> float | None:
    """The score's own tempo marking -- for the report only, never an input:
    the clock comes from the recording."""
    if score_path.suffix.lower() not in (".xml", ".musicxml"):
        return None
    try:
        root = ElementTree.parse(score_path).getroot()
    except ElementTree.ParseError:
        return None
    sound = root.find(".//sound[@tempo]")
    return float(sound.get("tempo")) if sound is not None else None


def whole_file_notes(audio: Path, config) -> tuple[list[tuple[float, int]], float]:
    """(onset, pitch) for the whole recording, and its length in seconds."""
    from swingscribe import pipeline
    from swingscribe.stages import beats, ingest, separate, transcribe

    prep = [("ingest", ingest.run), ("beats", beats.run), ("separate", separate.run)]
    prepared = pipeline.run(str(audio), config, stages=prep)
    duration = float(prepared.audio.duration)
    # transcribe wants an explicit end; None would mean "the whole track" to
    # the stage but not to its progress log (wjazz_batch.py).
    wide = config.model_copy(
        update={"transcribe": config.transcribe.model_copy(update={"region": (0.0, duration)})}
    )
    document = pipeline.run(str(audio), wide, stages=[*prep, ("transcribe", transcribe.run)])
    notes = document.notes.get(config.transcribe.stem, [])
    return sorted((float(n.onset), int(n.pitch)) for n in notes), duration


def tracked_beats(audio: Path, config, duration: float) -> list[float]:
    """The beat grid the page is built on: tracked, repaired, extended to the
    file's ends (`meter.bar_grid`, what the roll draws and Export counts)."""
    from swingscribe import pipeline
    from swingscribe.stages import beats, ingest, meter

    document = pipeline.run(
        str(audio), config, stages=[("ingest", ingest.run), ("beats", beats.run)]
    )
    grid = document.beat_grid
    repaired, _sections = meter.bar_grid(grid.beats, grid.downbeats, config.meter, duration)
    return [beat.time for beat in repaired]


# The span opens a little before bar 1, so a downbeat played a hair ahead of
# the tracked beat is inside it: a quarter of a beat, and never under 80 ms
# (at 320 bpm a quarter-beat is 47 ms, inside the tracker's own jitter). Not
# more. Half a beat was tried first and let a stray sound on the and-of-four
# into three spans (Confirmation, Blues For Alice, Now's The Time 1), each
# written as a pickup bar holding one note; an onset more than a quarter-beat
# early would be written before the bar line anyway, and the book's bar 1 is
# where the book starts.
LEAD_BEATS = 0.25
LEAD_FLOOR_S = 0.08


def process(
    audio: Path, config, relocate: bool, dry_run: bool, log=print, bars_only: bool = False
) -> dict:
    from swingscribe import mscz
    from swingscribe.benchmark import locate_score
    from swingscribe.gui import library
    from swingscribe.score_bars import bars_on_grid, clock_anchors

    score_path = score_beside(audio)
    if score_path is None:
        log(f"{audio.name}: no score beside it — skipped")
        return {"status": "no score"}
    sidecar_path = library.settings_path(audio)
    stored = {}
    if sidecar_path.is_file():
        stored = json.loads(sidecar_path.read_text(encoding="utf-8"))
    keeps_span = bool(stored.get("region")) and not relocate
    if keeps_span and not bars_only:
        lo, hi = stored["region"]
        log(f"{audio.name}: keeps its span {lo:.1f}-{hi:.1f}s (--relocate to place it again)")
        return {"status": "kept"}

    started = time.time()
    notes, duration = whole_file_notes(audio, config)
    score = mscz.parse_any(score_path)
    found = locate_score(score, notes)
    marking = marked_tempo(score_path)
    log(
        f"{audio.name}: {len(notes)} notes heard in {time.time() - started:.0f}s; "
        f"{int(found['n_matched'])}/{int(found['reference'])} of the score lined up "
        f"({found['coverage']:.0%}), transposition {int(found['transposition']):+d}"
    )
    if not found["trusted"]:
        log("  -> NOT placed: below the coverage floor (the wrong take, or too little heard)")
        return {"status": "not placed", **found}
    marked = f" (marked {marking:.0f})" if marking else ""
    log(
        f"  {found['bpm']:.1f} bpm{marked}, {score.bars} bars: "
        f"{found['start']:.2f}-{found['end']:.2f}s of {duration:.1f}s, "
        f"{int(found['anchors'])} anchors within {found['residual_s']:.2f}s of the line"
    )
    if found["start"] < -0.5 or found["end"] > duration + 0.5:
        log("  !! the score runs past the recording's edge — a cut transfer, or a wrong take")
    beats = tracked_beats(audio, config, duration)
    bars = bars_on_grid(
        clock_anchors(score, notes, found),
        beats,
        quarters=score.bars * score.beats_per_bar,
        pulses_per_bar=round(score.beats_per_bar),
    )
    start, end, anchor = found["start"], found["end"], None
    if bars["trusted"]:
        lead = max(LEAD_BEATS * found["seconds_per_quarter"], LEAD_FLOOR_S)
        start = bars["bar_one"] - lead if bars["bar_one"] is not None else 0.0
        end = bars["end"] if bars["end"] is not None else duration
        anchor = bars["anchor"]
        where = "before the file begins" if bars["bar_one"] is None else f"{bars['bar_one']:.2f}s"
        log(
            f"  bar 1 on the beat grid: {where} ({bars['share']:.0%} of {bars['votes']} "
            f"notes agree; the line said {found['start']:.2f}s)"
        )
    else:
        log(
            f"  !! the beat grid does not carry the score's pulse ({bars['share']:.0%} of "
            f"{bars['votes']} notes on one beat) -- no downbeat written, the tracker's stands"
        )
    region = [round(max(0.0, start), 3), round(min(duration, end), 3)]
    if keeps_span:
        region = stored["region"]
    settings = {
        "model": config.separate.model,
        "ensemble": config.transcribe.ensemble,
        "stem": config.transcribe.stem,
        "region": region,
        # A beat of the grid that carries the book's bar line, so the page's
        # bar lines are the book's (notation.span_anchor reads the anchor's
        # phase off the whole grid). None clears a stored one: a downbeat we
        # cannot vouch for is worse than the tracker's own, which named the
        # right beat on all twenty-two sides where ours named eleven.
        "anchor": None if anchor is None else round(anchor, 3),
        "form_start": None if anchor is None else round(anchor, 3),
        "score": str(score_path.resolve()),
        "beats_shown": True,
    }
    if dry_run:
        log(f"  -> would write {sidecar_path.name}: region {region}")
    else:
        library.save_settings(str(audio), settings, config)
        log(f"  -> {sidecar_path.name} written")
    return {"status": "placed", **found}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", default="", help="a subfolder of benchmark/ (e.g. Omnibook)")
    parser.add_argument("--file", action="append", default=[], help="only these files (repeatable)")
    parser.add_argument("--relocate", action="store_true", help="replace a span already stored")
    parser.add_argument(
        "--bars-only", action="store_true", help="keep a stored span, re-vote its downbeat"
    )
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--model", default=None, help="separation model (default: the config's)")
    parser.add_argument("--stem", default="other", help="the stem that carries the soloist")
    parser.add_argument("--ensemble", default="horn-led", help="horn-led | trio | solo-piano")
    args = parser.parse_args()

    folder = BENCH_DIR / args.folder if args.folder else BENCH_DIR
    files = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES),
        key=lambda p: p.name.lower(),
    )
    if args.file:
        wanted = set(args.file)
        files = [p for p in files if p.name in wanted]
        missing = wanted - {p.name for p in files}
        if missing:
            raise SystemExit(f"no such file(s) in {folder}: {', '.join(sorted(missing))}")
    if not files:
        raise SystemExit(f"no audio in {folder}")

    cache_dir = args.cache_dir.resolve()
    os.chdir(cache_dir.parent)
    from swingscribe.config import Config

    base = Config.from_yaml()
    base = base.model_copy(
        update={
            "cache_dir": cache_dir,
            "separate": base.separate.model_copy(
                update={"model": args.model or base.separate.model}
            ),
            "transcribe": base.transcribe.model_copy(
                update={"ensemble": args.ensemble, "stem": args.stem}
            ),
        }
    )
    print(f"{len(files)} file(s) in {folder}; {base.separate.model}, {args.stem}, {args.ensemble}")
    tally: dict[str, int] = {}
    for audio in files:
        print(f"\n== {audio.name} ==")
        outcome = process(audio, base, args.relocate, args.dry_run, bars_only=args.bars_only)
        tally[outcome["status"]] = tally.get(outcome["status"], 0) + 1
    print("\n" + ", ".join(f"{count} {status}" for status, count in sorted(tally.items())))


if __name__ == "__main__":
    main()
