"""Basic Pitch over the harness's stems -- the WSL half of the A2 bake-off.

Runs INSIDE WSL, in a venv outside the repo, never on Windows: Basic Pitch
imports librosa, resampy and numba, which Smart App Control refuses on the
dev machine and CLAUDE.md forbids in the project. The Windows half is
`scripts/frontend_bakeoff.py`, which writes the manifest this reads and
scores the notes this writes. The setup (2026-09-29), recorded because the
bake-off is only reproducible with it:

    mkdir -p ~/bakeoff && cd ~/bakeoff
    ~/.local/bin/uv venv --python 3.11 .venv
    ~/.local/bin/uv pip install --python .venv/bin/python basic-pitch onnxruntime soundfile
    # basic-pitch 0.4.0 pulls full TensorFlow on Linux/3.11; the ONNX graph
    # it ships needs none of it, so it goes, and resampy 0.4.2 still imports
    # pkg_resources, which setuptools removed in 81:
    ~/.local/bin/uv pip uninstall --python .venv/bin/python tensorflow \\
        tensorflow-estimator tensorflow-io-gcs-filesystem tensorboard \\
        tensorboard-data-server keras
    ~/.local/bin/uv pip install --python .venv/bin/python "setuptools<81"

Runtime: basic-pitch 0.4.0, its `nmp.onnx` (ICASSP 2022 weights) on
onnxruntime 1.30.0, CPU. Two steps:

    .venv/bin/python bakeoff_basic_pitch_wsl.py infer --manifest M --post ~/bakeoff/post
    .venv/bin/python bakeoff_basic_pitch_wsl.py decode --manifest M --post ~/bakeoff/post \\
        --out notes.json --onset 0.5 --frame 0.3 --min-ms 35

`infer` runs the network ONCE per region and keeps its frame ("note") and
onset posteriorgrams; `decode` turns them into notes with Basic Pitch's own
`output_to_notes_polyphonic` under one parameter set. Every setting is a
decode, so a sweep costs no inference.

## The parameters are a decision, not a default

Basic Pitch's `minimum_note_length` defaults to 127.7 ms (11 frames at 86
fps). The whole question of the bake-off is the note UNDER an eighth --
WJazzD's pure misses sit at a median 49-57 ms -- so the default would
delete exactly the population being tested. `--min-ms` is therefore set
per run and recorded in the output beside every other threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

MARGIN_S = 1.0  # audio either side of the region, so an edge note has context


def wsl_path(path: str) -> str:
    """C:\\Users\\... -> /mnt/c/Users/..."""
    if len(path) > 2 and path[1] == ":":
        return "/mnt/" + path[0].lower() + path[2:].replace("\\", "/")
    return path


def post_name(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".npz"


def session(threads: int):
    import onnxruntime as ort
    from basic_pitch import ICASSP_2022_MODEL_PATH

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    path = Path(ICASSP_2022_MODEL_PATH).parent / "nmp.onnx"
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def infer_array(audio, sess, batch: int = 16) -> dict:
    """basic_pitch.inference.run_inference, on an array instead of a path.

    The same 30-frame overlap, the same half-overlap of leading zeros, the
    same `unwrap_output`; only the audio arrives loaded (a region of a
    full-length stem) and the windows go through in batches."""
    import numpy as np
    from basic_pitch.constants import AUDIO_N_SAMPLES, FFT_HOP
    from basic_pitch.inference import unwrap_output, window_audio_file

    n_overlapping_frames = 30
    overlap_len = n_overlapping_frames * FFT_HOP
    hop_size = AUDIO_N_SAMPLES - overlap_len
    original_length = audio.shape[0]
    padded = np.concatenate([np.zeros(overlap_len // 2, dtype=np.float32), audio])
    windows = [w for w, _t in window_audio_file(padded, hop_size)]
    outputs = {"note": [], "onset": []}
    for i in range(0, len(windows), batch):
        x = np.stack(windows[i : i + batch]).astype(np.float32)
        contour, note, onset = sess.run(
            ["StatefulPartitionedCall:0", "StatefulPartitionedCall:1", "StatefulPartitionedCall:2"],
            {"serving_default_input_2:0": x},
        )
        outputs["note"].append(note)
        outputs["onset"].append(onset)
    return {
        k: unwrap_output(np.concatenate(v), original_length, n_overlapping_frames)
        for k, v in outputs.items()
    }


def infer(args) -> None:
    import librosa
    import numpy as np
    from basic_pitch.constants import AUDIO_SAMPLE_RATE

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    post = Path(args.post).expanduser()
    post.mkdir(parents=True, exist_ok=True)
    sess = session(args.threads)
    todo = sorted(manifest)
    if args.only:
        todo = [k for k in todo if args.only in k]
    total_audio = total_time = 0.0
    for n, key in enumerate(todo, 1):
        out = post / post_name(key)
        if out.is_file():
            continue
        entry = manifest[key]
        lo, hi = entry["region"]
        start = max(0.0, float(lo) - MARGIN_S)
        duration = float(hi) + MARGIN_S - start
        started = time.time()
        audio, _sr = librosa.load(
            wsl_path(entry["wav"]), sr=AUDIO_SAMPLE_RATE, mono=True, offset=start, duration=duration
        )
        loaded = time.time()
        result = infer_array(audio, sess)
        np.savez_compressed(
            out,
            note=result["note"].astype(np.float16),
            onset=result["onset"].astype(np.float16),
            start=np.float64(start),
            key=np.array(key),
        )
        took = time.time() - started
        total_audio += len(audio) / AUDIO_SAMPLE_RATE
        total_time += took
        print(
            f"[{n}/{len(todo)}] {key}: {len(audio) / AUDIO_SAMPLE_RATE:.0f}s audio, "
            f"load {loaded - started:.1f}s, model {time.time() - loaded:.1f}s",
            flush=True,
        )
    if total_time:
        print(f"{total_audio:.0f}s of audio in {total_time:.0f}s ({total_audio / total_time:.1f}x)")


def decode_one(task: tuple) -> tuple[str, list]:
    key, path, region, params = task
    import numpy as np
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, FFT_HOP
    from basic_pitch.note_creation import model_frames_to_time, output_to_notes_polyphonic

    data = np.load(path)
    frames = data["note"].astype(np.float32)
    onsets = data["onset"].astype(np.float32)
    start = float(data["start"])
    min_len = int(round(params["min_ms"] / 1000 * (AUDIO_SAMPLE_RATE / FFT_HOP)))
    events = output_to_notes_polyphonic(
        frames.copy(),
        onsets.copy(),
        onset_thresh=params["onset"],
        frame_thresh=params["frame"],
        min_note_len=min_len,
        infer_onsets=params["infer_onsets"],
        max_freq=params["max_hz"],
        min_freq=params["min_hz"],
        melodia_trick=params["melodia"],
        energy_tol=params["energy_tol"],
    )
    times = model_frames_to_time(frames.shape[0])
    lo, hi = region
    out = []
    for s, e, pitch, amp in events:
        onset = float(times[s]) + start
        if not lo <= onset <= hi:
            continue
        out.append(
            [round(onset, 4), round(float(times[e]) + start, 4), int(pitch), round(float(amp), 4)]
        )
    out.sort()
    return key, out


def decode(args) -> None:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    post = Path(args.post).expanduser()
    params = {
        "onset": args.onset,
        "frame": args.frame,
        "min_ms": args.min_ms,
        "melodia": not args.no_melodia,
        "infer_onsets": not args.no_infer_onsets,
        "energy_tol": args.energy_tol,
        "min_hz": args.min_hz,
        "max_hz": args.max_hz,
    }
    tasks = [
        (key, str(post / post_name(key)), manifest[key]["region"], params)
        for key in sorted(manifest)
        if (post / post_name(key)).is_file()
    ]
    missing = len(manifest) - len(tasks)
    started = time.time()
    if args.jobs > 1:
        from multiprocessing import Pool

        with Pool(args.jobs) as pool:
            results = pool.map(decode_one, tasks, chunksize=1)
    else:
        results = [decode_one(t) for t in tasks]
    notes = dict(results)
    Path(args.out).write_text(json.dumps({"params": params, "notes": notes}), encoding="utf-8")
    count = sum(len(v) for v in notes.values())
    print(
        f"{len(notes)} regions, {count} notes, {missing} without posteriorgrams, "
        f"{time.time() - started:.0f}s -> {args.out} {params}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Basic Pitch over the bake-off manifest (WSL).")
    sub = parser.add_subparsers(dest="command", required=True)
    i = sub.add_parser("infer")
    i.add_argument("--manifest", required=True)
    i.add_argument("--post", default="~/bakeoff/post")
    i.add_argument("--threads", type=int, default=4)
    i.add_argument("--only", default=None, help="substring of the keys to run")
    d = sub.add_parser("decode")
    d.add_argument("--manifest", required=True)
    d.add_argument("--post", default="~/bakeoff/post")
    d.add_argument("--out", required=True)
    d.add_argument("--onset", type=float, default=0.5)
    d.add_argument("--frame", type=float, default=0.3)
    d.add_argument("--min-ms", type=float, default=127.7)
    d.add_argument("--no-melodia", action="store_true")
    d.add_argument("--no-infer-onsets", action="store_true")
    d.add_argument("--energy-tol", type=int, default=11)
    d.add_argument("--min-hz", type=float, default=None)
    d.add_argument("--max-hz", type=float, default=None)
    d.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    {"infer": infer, "decode": decode}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
