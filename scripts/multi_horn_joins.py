"""What tells a re-attack from a held note split in two, at every join.

    .venv\\Scripts\\python.exe scripts\\multi_horn_joins.py AUDIO --sidecar TAKE.swingscribe.json

A two-horn head as Basic Pitch hears it (docs/multi-horn.md) holds pairs of
notes of ONE pitch that touch: a horn re-attacking (the A section's "F5 F5
F5"), or one held note the decoder split (bar 25's lower C, a whole note
heard as 0.685 s + 0.280 s with no gap). The gap cannot tell them apart:
Basic Pitch's decoder always ends a note where a same-pitch onset begins.
CREPE's trace cannot either where it follows the other horn
(`voices.rejoin_splits`). This MEASURES, and decides nothing: for each such
pair in the cached review it prints

- `onset`: the onset posteriorgram's peak at the pitch, within two frames of
  the join -- how sure the model is a new note began;
- `frame dip`: the lowest note posteriorgram at the pitch within two frames
  of the join, as a share of its median over the two notes (1.0: no dip);
- `energy dip`: how far the stem's 10 ms RMS falls within 30 ms of the join
  below its median over the two notes, in dB.

The listener marks which joins are re-attacks and which are one note; the
feature that separates them, if one does, is the rule. Read-only: needs the
review cached (scripts/multi_horn_page.py or the GUI's Transcribe), the
stems, and the ml group (Basic Pitch on onnxruntime).
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

TOUCH_S = 0.03  # a join: the next note starts within this of the last one's end
WINDOW_FRAMES = 2  # Basic Pitch frames either side of the join (11.6 ms each)
RMS_S = 0.01
DIP_WINDOW_S = 0.03


def joins(notes: list[dict], touch: float = TOUCH_S) -> list[tuple[dict, dict]]:
    """Touching pairs of one pitch in one voice, in time order."""
    by_voice: dict[int, list[dict]] = {}
    for note in sorted(notes, key=lambda n: float(n["onset"])):
        by_voice.setdefault(int(note.get("voice", 1)), []).append(note)
    pairs = []
    for run in by_voice.values():
        for first, second in zip(run, run[1:], strict=False):
            end = float(first["onset"]) + float(first["duration"])
            if (
                int(first["pitch"]) == int(second["pitch"])
                and abs(float(second["onset"]) - end) <= touch
            ):
                pairs.append((first, second))
    return sorted(pairs, key=lambda pair: float(pair[1]["onset"]))


def join_features(
    note_post,
    onset_post,
    times,
    rms,
    rms_times,
    first: dict,
    second: dict,
    shift: float = 0.0,
    midi_offset: int = 21,
) -> dict:
    """The three measures at one join. `note_post`/`onset_post` are Basic
    Pitch's (frames, 88) posteriorgrams with each frame's whole-track time in
    `times`; `rms`/`rms_times` the stem's short-time RMS; `shift` the onset
    shift the review's notes carry (TranscribeConfig.multi_horn_onset_shift_ms)."""
    import numpy as np

    pitch_bin = int(first["pitch"]) - midi_offset
    join = float(second["onset"]) - shift
    begin = float(first["onset"]) - shift
    end = float(second["onset"]) + float(second["duration"]) - shift
    at = int(np.argmin(np.abs(times - join)))
    low, high = max(0, at - WINDOW_FRAMES), min(len(times), at + WINDOW_FRAMES + 1)
    onset_peak = float(onset_post[low:high, pitch_bin].max())
    span = (times >= begin) & (times <= end)
    typical = float(np.median(note_post[span, pitch_bin])) if span.any() else 0.0
    trough = float(note_post[low:high, pitch_bin].min())
    frame_dip = trough / typical if typical > 0 else 1.0
    around = np.abs(rms_times - join) <= DIP_WINDOW_S
    level = (rms_times >= begin) & (rms_times <= end)
    energy_dip = 0.0
    if around.any() and level.any():
        floor = 1e-9
        energy_dip = float(
            20 * np.log10(max(np.median(rms[level]), floor) / max(rms[around].min(), floor))
        )
    return {
        "time": round(join + shift, 3),
        "pitch": int(first["pitch"]),
        "voice": int(first.get("voice", 1)),
        "first": round(float(first["duration"]), 3),
        "second": round(float(second["duration"]), 3),
        "onset": round(onset_peak, 3),
        "frame_dip": round(frame_dip, 3),
        "energy_dip_db": round(energy_dip, 1),
    }


def short_time_rms(mono, rate: int, hop_s: float = RMS_S):
    """(rms, times) of `mono` in hop_s windows."""
    import numpy as np

    hop = max(1, int(rate * hop_s))
    frames = len(mono) // hop
    shaped = np.asarray(mono[: frames * hop], dtype=np.float64).reshape(frames, hop)
    return np.sqrt((shaped**2).mean(axis=1)), (np.arange(frames) + 0.5) * hop / rate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("audio", type=Path)
    parser.add_argument("--sidecar", type=Path, help="the take's sidecar (else the audio's own)")
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument("--model", help="separation model (default: sidecar, then config)")
    parser.add_argument("--stem", help="default: sidecar, else other")
    parser.add_argument("--cache-dir", type=Path, help="the GUI's cache directory")
    parser.add_argument("--json", type=Path, help="also write the rows here")
    args = parser.parse_args(argv)

    import soundfile

    from swingscribe import basic_pitch
    from swingscribe.config import DEFAULT_CONFIG_PATH, Config
    from swingscribe.gui import library, review

    config = Config.from_yaml(DEFAULT_CONFIG_PATH)
    if args.cache_dir is not None:
        config = config.model_copy(update={"cache_dir": args.cache_dir})
    audio = args.audio.expanduser().resolve()
    sidecar = args.sidecar or library.settings_path(audio)
    settings = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    region = settings.get("region") or [None, None]
    start = args.start if args.start is not None else region[0]
    end = args.end if args.end is not None else region[1]
    if start is None or end is None:
        sys.exit("no span: pass --start/--end or a sidecar with a region")
    model = args.model or settings.get("model") or config.separate.model
    stem = args.stem or settings.get("stem") or "other"

    document = library.ingested_document(audio, config)
    run_config = review.span_config(config, stem, float(start), float(end), "multi-horn")
    run_config = run_config.model_copy(
        update={"separate": run_config.separate.model_copy(update={"model": model})}
    )
    payload = review.cached_review(document, run_config, model)
    if payload is None:
        sys.exit("no cached review for this span: transcribe it first (multi_horn_page.py)")
    stem_path = library.resolve_stem(document, run_config, model, stem)
    if stem_path is None:
        sys.exit(f"no {stem!r} stem for {model} over {start}-{end}")
    data, rate = soundfile.read(str(stem_path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    segment, offset = basic_pitch.region_audio(mono, rate, (float(start), float(end)))
    note_post, onset_post = basic_pitch.posteriorgrams(basic_pitch.resample(segment, rate))
    times = basic_pitch.frame_times(note_post.shape[0]) + offset
    rms, rms_times = short_time_rms(segment, rate)
    rms_times = rms_times + offset
    shift = run_config.transcribe.multi_horn_onset_shift_ms / 1000.0

    rows = [
        join_features(note_post, onset_post, times, rms, rms_times, first, second, shift)
        for first, second in joins(payload["notes"])
    ]
    print(f"{len(rows)} same-pitch join(s) in {audio.name} {start}-{end} s")
    print(
        f"{'time':>9} {'pitch':>5} {'v':>2} {'first':>6} {'second':>6} "
        f"{'onset':>6} {'f.dip':>6} {'e.dip':>6}"
    )
    for row in rows:
        print(
            f"{row['time']:9.3f} {row['pitch']:5d} {row['voice']:2d} {row['first']:6.3f} "
            f"{row['second']:6.3f} {row['onset']:6.3f} {row['frame_dip']:6.3f} "
            f"{row['energy_dip_db']:6.1f}"
        )
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
