"""Score the hand-transcribed benchmark tracks through the GUI itself, and
keep a progress spreadsheet of the result.

    uv sync --group ml --group gui --group batch
    uv run python scripts/benchmark_batch.py
    uv run python scripts/benchmark_batch.py --file Tommy_Flanagan_Giant_Steps.m4a

The wjazzd sheet's sibling (wjazz_batch.py), for the tracks in benchmark/
itself — the listener's OWN transcriptions (.mscz beside each audio file).
One row per audio file, in benchmark/benchmark_test.xlsx, same columns and
the same two measures: `pitch_*` (the green ground-truth bar — did we hear
the right notes?) and `notation_*` (the Score button — is it written the way
the human wrote it?).

## Driven through the GUI's OWN endpoints, not its internals

Unlike wjazz_batch, which needs internal access for its two-pass solo
location, nothing here needs anything a browser cannot do: the span is the
listener's, stored in the sidecar, and the score sits beside the audio. So
this script runs the actual FastAPI app (gui.app.create_app) under a test
client and calls the endpoints the buttons call — /api/tracks/open,
/api/jobs (transcribe, when the review is not already cached), /export,
/notation-score, /ground-truth. There is no way for these numbers to drift
from the Score button's, because they ARE the Score button's, erasures and
all. If a needed input is missing (no beat grid, no stems), the endpoint's
409 tells us which button we owe it, and the corresponding job is submitted
exactly as the frontend would.

## Differences from the wjazzd sheet worth knowing

- **`notation_value` is REAL evidence here.** The wjazzd references carry
  our own duration conventions applied to a human's grid, so value there
  partly scores us against ourselves. These .mscz files carry the values a
  human chose; disagreement is a genuine finding.
- **Erasures apply.** The listener has silenced notes on these tracks (the
  sidecars carry 239 of them as of 2026-08-31), and the endpoints resolve
  them before exporting or scoring, exactly as the GUI does. The row says
  how many were silenced.
- **No solo location.** The span in the sidecar is a human judgement,
  hand-drawn by ear. If a sidecar has no span, that is the row's status —
  this script never invents one.
- These recordings are DIFFERENT TAKES from the ones WJazzD annotated (the
  wjazz identify control rejects all ten at 1.8-10%), which is exactly why
  they carry their own hand transcriptions.

## Standing where the cache expects

Same rule as wjazz_batch: chdir to the cache's parent so every relative
path inside cached Documents resolves the way it does for the live GUI.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import batch_sheet

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmark"
DEFAULT_CACHE_DIR = BENCH_DIR / ".swingscribe-cache"
SHEET_PATH = BENCH_DIR / "benchmark_test.xlsx"

sys.path.insert(0, str(REPO_ROOT / "src"))

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac"}
JOB_POLL_S = 2.0
JOB_TIMEOUT_S = 30 * 60  # a fresh htdemucs_ft separation on CPU is ~11 min

HEADERS = [
    "file",
    "span_start",
    "span_end",
    "separation_model",
    "ensemble",
    "stem",
    "erasures_silenced",
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
FIELDS = HEADERS  # row keys match headers one-to-one here (no melid/number split)


def audio_files() -> list[Path]:
    return sorted(
        (p for p in BENCH_DIR.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES),
        key=lambda p: p.name.lower(),
    )


def wait_for_job(client, job: dict, log) -> dict:
    """Poll /api/jobs/{id} until the job leaves queued/running."""
    started = time.time()
    while job["state"] in ("queued", "running"):
        if time.time() - started > JOB_TIMEOUT_S:
            raise TimeoutError(f"{job['kind']} job still {job['state']} after {JOB_TIMEOUT_S}s")
        time.sleep(JOB_POLL_S)
        job = client.get(f"/api/jobs/{job['id']}").json()
    log(f"    {job['kind']}: {job['state']} in {job['elapsed']}s")
    return job


def run_job(client, path: str, kind: str, model: str, stem=None, span=None, log=print) -> dict:
    body = {"path": path, "kind": kind, "model": model}
    if kind == "transcribe":
        body |= {"stem": stem, "start": span[0], "end": span[1]}
    job = client.post("/api/jobs", json=body).json()
    if "state" not in job:
        raise RuntimeError(f"{kind} job refused: {job}")
    return wait_for_job(client, job, log)


def process_track(client, audio_path: Path, log=print) -> dict:
    """One track through open → review (transcribing if needed) → export →
    score → ground truth. Always returns a FIELDS-keyed dict; on any failure
    `status` says why and the other columns stay blank."""
    row: dict = dict.fromkeys(FIELDS, "")
    row["file"] = audio_path.name

    opened = client.post("/api/tracks/open", json={"path": str(audio_path)})
    if opened.status_code != 200:
        row["status"] = f"could not open: {opened.json().get('detail', opened.text)}"
        return row
    track = opened.json()
    track_id, state = track["id"], track["state"]

    defaults = client.get("/api/config").json()
    model = state.get("model") or defaults["default_model"]
    stem = state.get("stem") or defaults["default_stem"]
    region = state.get("region")
    if not region:
        row["status"] = "no span in the sidecar — open the track and select the solo by ear"
        return row
    span = (region[0], region[1])
    row.update(
        span_start=round(span[0], 3),
        span_end=round(span[1], 3) if span[1] is not None else "",
        separation_model=model,
        ensemble=state.get("ensemble") or "",
        stem=stem,
    )

    params = {"model": model, "stem": stem, "start": span[0], "end": span[1]}

    review = client.get(f"/api/tracks/{track_id}/review", params=params).json()
    if not review.get("ready"):
        log(f"    review not cached — transcribing {span[0]:.1f}-{span[1]:.1f}s")
        # The transcribe job runs on an already-separated stem; if separation
        # (or the beat grid) is missing too, run those buttons first, exactly
        # as the frontend would.
        stems = client.get(f"/api/tracks/{track_id}/stems", params={"model": model}).json()
        if stem not in stems.get("stems", []):
            run_job(client, str(audio_path), "separate", model, log=log)
        job = run_job(client, str(audio_path), "transcribe", model, stem=stem, span=span, log=log)
        if job["state"] != "done":
            row["status"] = f"transcribe failed: {job.get('error') or job['state']}"
            return row
        review = client.get(f"/api/tracks/{track_id}/review", params=params).json()
    if not review.get("ready"):
        row["status"] = "review still not ready after transcribing — investigate"
        return row

    silenced = review.get("erasures", {}).get("silenced", [])
    row["erasures_silenced"] = len(silenced)
    row["notes"] = len(review["notes"]) - len(silenced)

    exported = client.post(f"/api/tracks/{track_id}/export", params=params)
    if exported.status_code == 409 and "Beats" in exported.json().get("detail", ""):
        run_job(client, str(audio_path), "beats", model, log=log)
        exported = client.post(f"/api/tracks/{track_id}/export", params=params)
    if exported.status_code != 200:
        row["status"] = f"export failed: {exported.json().get('detail', exported.text)}"
        return row
    page = exported.json()
    row["musicxml_written_at"] = datetime.now().isoformat(timespec="seconds")
    row["readability"] = page["readability"]
    row["tie_rate"] = page["tie_rate"]

    score = state.get("score")
    if not score or not Path(score).is_file():
        row["status"] = "wrote musicxml; no hand transcription on the sidecar"
        return row

    scored = client.get(f"/api/tracks/{track_id}/notation-score", params={**params, "score": score})
    if scored.status_code != 200:
        row["status"] = f"wrote musicxml; scoring failed: {scored.json().get('detail', '')}"
        return row
    result = scored.json()
    row["notation_rhythm"] = result["rhythm"]
    row["notation_value"] = result["value"]
    row["notation_coverage"] = result["coverage"]
    row["notation_matched"] = result["matched"]
    row["notation_reference"] = result["reference"]

    # Its own try: one measure failing must not throw away the other.
    overlay = client.get(f"/api/tracks/{track_id}/ground-truth", params={**params, "score": score})
    if overlay.status_code == 200:
        got = overlay.json()
        row["pitch_f1"] = got["pitch_f1"]
        counts = got["counts"]
        row["pitch_matched"] = counts["matched"]
        row["pitch_wrong"] = counts["wrong"]
        row["pitch_invented"] = counts["invented"]
        row["pitch_missed"] = counts["missed"]
    else:
        log(f"    ground-truth counts unavailable: {overlay.json().get('detail', '')}")

    row["status"] = (
        "ok"
        if result["trusted"]
        else f"ok — low coverage ({result['coverage']:.2f}), rhythm untrusted"
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", action="append", default=[], help="only these files (repeatable)")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()

    import os

    os.chdir(args.cache_dir.resolve().parent)

    from fastapi.testclient import TestClient

    from swingscribe.config import Config
    from swingscribe.gui.app import create_app

    files = audio_files()
    if args.file:
        wanted = set(args.file)
        files = [p for p in files if p.name in wanted]
        missing = wanted - {p.name for p in files}
        if missing:
            raise SystemExit(f"no such file(s) in {BENCH_DIR}: {', '.join(sorted(missing))}")
    files = [p for p in files if (BENCH_DIR / f"{p.name}.swingscribe.json").is_file()]
    if not files:
        print("Nothing to do — no sidecar'd audio in benchmark/.")
        return

    print(f"Processing {len(files)} file(s): {', '.join(p.name for p in files)}")
    client = TestClient(create_app(Config.from_yaml()))
    wb, ws = batch_sheet.load_or_create_sheet(SHEET_PATH, HEADERS, "benchmark")
    index = batch_sheet.row_index(ws)

    for audio_path in files:
        print(f"\n== {audio_path.name} ==")
        row = process_track(client, audio_path)
        batch_sheet.write_row(ws, index, row["file"], row, FIELDS)
        batch_sheet.save_sheet(wb, ws, SHEET_PATH, HEADERS)
        print(f"  -> {row['status'] or 'ok'}")

    print(f"\nSpreadsheet: {SHEET_PATH}")


if __name__ == "__main__":
    main()
