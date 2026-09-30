"""Banquet over the trial spans -- the WSL half of the query-separation trial.

Runs INSIDE WSL, in a venv outside the repo, never on Windows: Banquet
(Watcharasupat and Lerch, ISMIR 2024, github.com/kwatcharasupat/query-bandit,
MIT code) imports librosa (numba), which Smart App Control refuses on the dev
machine and CLAUDE.md forbids in the project, and pytorch_lightning, which
nothing here needs. The Windows half is `scripts/banquet_trial.py`: it writes
the manifest and the audio this reads (a crop of each span from the ingest
wav, and the query clip) and transcribes and scores what this writes.
docs/banquet-trial.md has the verdict.

The setup (2026-09-30), recorded because the trial is only reproducible with
it. The clone and the checkpoint live OUTSIDE the repo and outside AppData,
under C:\\Users\\lkmcg\\swingscribe-research\\banquet:

    git clone https://github.com/kwatcharasupat/query-bandit.git  # 79ed5bb
    curl -L -o ev-pre-aug.ckpt \\
        https://zenodo.org/api/records/13694558/files/ev-pre-aug.ckpt/content
    mkdir -p ~/banquet && cd ~/banquet
    ~/.local/bin/uv venv --python 3.11 .venv
    ~/.local/bin/uv pip install --python .venv/bin/python torch==2.5.1 torchaudio==2.5.1
    ~/.local/bin/uv pip install --python .venv/bin/python "pytorch_lightning>=2.3,<2.6" \\
        "torchmetrics>=1.3,<1.9" omegaconf fire pandas librosa torch_audiomentations \\
        soundfile tqdm hear21passt

The repo has no requirements file; that list is its imports. Resolved:
torch 2.5.1+cu124, torchaudio 2.5.1, pytorch-lightning 2.5.6, torchmetrics
1.8.2, hear21passt 0.0.26, timm 1.0.30, numpy 2.4.6. CUDA works in WSL through
the Windows driver with nothing installed in Linux but the pip wheels.

## The query encoder is NOT downloaded

Banquet conditions on a PaSST embedding of the query (hear21passt,
`get_basic_model(arch="openmic")`), and building that model fetches the
OpenMIC PaSST weights from GitHub. The Banquet checkpoint already holds them
(645 MB = the 24.9M-parameter separator, its Adam moments and the 86M frozen
PaSST), so `build` constructs PaSST with `pretrained=False` and the
checkpoint's STRICT load fills every parameter and persistent buffer -- a key
missing from the checkpoint would be an error, not a silent random weight.
No weights beyond the approved checkpoint are fetched.

## One run per condition

    .venv/bin/python banquet_wsl.py infer --manifest M --out DIR \\
        --repo /mnt/c/.../query-bandit --ckpt /mnt/c/.../ev-pre-aug.ckpt \\
        --condition self [--cpu] [--batch 4]

For each manifest entry it separates the entry's crop (`mix`) with the
condition's query clip and writes `DIR/<condition>/<id>.wav` (float, the
crop's length and rate); the Windows half pads it back to the track's time
base. Inference is the authors' chunked inference with their own settings
(6 s chunks, 0.5 s hop, Hann overlap-add) and their query handling (a clip
shorter than the 10 s the model was trained on is TILED to 10 s, exactly as
`train.py inference_byoq` does). `DIR/runinfo-<condition>.json` records the
versions, and per entry the device, batch, time and which of the two
changes below were on. The entry is resumable: a finished wav is skipped.

Two changes to HOW it runs, neither to what it computes, both measured
against the authors' own code on Limehouse Blues (docs/banquet-trial.md):
`QueryMemo` embeds the query once per entry instead of once per chunk batch
(SNR 75 dB against the authors' run at another batch size -- float
reordering), and `chunked_inference_offload` keeps the unfolded span on the
CPU so GPU memory stops growing with the span (SNR 141 dB at the same
batch). `--no-memo-query` and `--authors-chunking` restore the originals.

Cost here (RTX 3050 6 GB, shared with other jobs): 1,725 s of audio in
2,348 s on the GPU, 0.31-1.37x real time per span as the other jobs came and
went; on the CPU (4 threads) one batch of 4 chunks took 37 s, so the 39 s
Limehouse span (39 batches at the 0.5 s hop) is ~24 minutes and the trial set
~12 hours, which is why the GPU is used. A
`RuntimeError` from CUDA (the card is shared: an allocation elsewhere can
fail a cuDNN call) retries the entry; a context the driver has poisoned
("unknown error") does not survive in-process, so run it under a loop that
restarts it.

Nothing this writes may enter the repo: it is audio derived from commercial
recordings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

MODEL_FS = 44100
QUERY_SECONDS = 10.0  # what the model was trained on; shorter clips are tiled


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(repo: Path, ckpt: Path, batch: int, hop: float, cuda: bool):
    """The authors' `inference_byoq` model, built once for every entry."""
    import functools

    import hear21passt.base

    os.environ["CONFIG_ROOT"] = str(repo / "config")
    sys.path.insert(0, str(repo))
    # PaSST without its pretrained download: the checkpoint's strict load
    # supplies the weights (module docstring).
    hear21passt.base.get_model_passt = functools.partial(
        hear21passt.base.get_model_passt, pretrained=False
    )
    import train  # the repo's train.py: its builders, not its CLI

    config = train._load_config(str(repo / "expt" / "bandit-everything-test.yml"))
    config.data.inference_kwargs.batch_size = batch
    config.data.inference_kwargs.hop_size_seconds = hop
    model = train._build_model(config)
    system = train.EndToEndLightningSystem.load_from_checkpoint(
        str(ckpt),
        strict=True,
        map_location="cpu",
        model=model,
        loss_handler=train._build_loss(config),
        metrics=train._dummy_metrics(config),
        augmentation_handler=train._dummy_augmentation(),
        inference_handler=config.data.inference_kwargs,
        optimization_bundle=train._build_optimization_bundle(config),
        fast_run=config.fast_run,
        batch_size=config.data.batch_size,
        effective_batch_size=config.data.get("effective_batch_size", None),
        commitment_weight=config.get("commitment_weight", 1.0),
    )
    system.eval()
    return system.cuda() if cuda else system.cpu(), dict(config.data.inference_kwargs)


class QueryMemo:
    """Embed the query ONCE per entry instead of once per chunk batch.

    `chunked_inference` hands the same query tensor to every batch of chunks,
    and the model's `adapt_query` runs the 86M-parameter PaSST over that 10 s
    clip each time -- the same (1, 768) embedding, recomputed ~n_chunks /
    batch times. The memo returns it instead. Nothing else changes (the
    FiLM, the mask, the overlap-add are the authors'); docs/banquet-trial.md
    has the output measured against an un-memoised run. `clear()` runs
    before each entry, so a freed query's address reused by the next cannot
    return a stale embedding, and `calls`/`embedded` say whether it hit."""

    def __init__(self, system, enabled: bool = True):
        self.memo: dict = {}
        self.calls = self.embedded = 0
        if not enabled:
            return
        encoder = system.model.query_encoder
        original = encoder.forward

        def forward(x):
            key = (x.data_ptr(), tuple(x.shape), str(x.device))
            self.calls += 1
            if key not in self.memo:
                self.embedded += 1
                self.memo[key] = original(x)
            return self.memo[key]

        encoder.forward = forward

    def clear(self) -> None:
        self.memo.clear()
        self.calls = self.embedded = 0


def chunked_inference_offload(system, mixture, query, inference: dict):
    """The authors' `EndToEndLightningSystem.chunked_inference`, line for line
    (the same reflect padding, unfold, Hann window, scaler and fold), except
    that the unfolded chunks and the per-chunk estimates stay on the CPU and
    one batch of chunks at a time visits the GPU.

    Their version unfolds the WHOLE input on the device and concatenates
    every chunk's estimate there before the fold: at a 0.5 s hop that is 12
    copies of the span, twice, so GPU memory grows with the span (a 116 s
    solo asked for 842 MiB on top of the model at batch 2; Crazy Rhythm's
    220 s would want ~2 GB) on a card this trial shares. Here it does not.
    docs/banquet-trial.md has the output measured against theirs."""
    import math

    import torch
    from core.types import BatchedInputOutput, SimpleishNamespace
    from torch.nn import functional as F

    device = system.device
    batch = BatchedInputOutput.from_dict(
        {
            "mixture": {"audio": mixture.unsqueeze(0)},
            "query": {"audio": query.unsqueeze(0).to(device)},
            "metadata": {"stem": ["target"]},
            "estimates": {},
        }
    )
    audio = batch["mixture"]["audio"]
    _, c, n_samples = audio.shape
    fs = inference["fs"]
    chunk_size = int(inference["chunk_size_seconds"] * fs)
    hop_size = int(inference["hop_size_seconds"] * fs)
    batch_size = inference["batch_size"]
    overlap = chunk_size - hop_size
    scaler = chunk_size / (2 * hop_size)
    n_chunks = int(math.ceil((n_samples + 4 * overlap - chunk_size) / hop_size)) + 1
    pad = (n_chunks - 1) * hop_size + chunk_size - n_samples
    audio = F.pad(audio, pad=(2 * overlap, 2 * overlap + pad), mode="reflect")
    padded_length = audio.shape[-1]
    audio = audio.reshape(c, 1, -1, 1)
    chunked = F.unfold(audio, kernel_size=(chunk_size, 1), stride=(hop_size, 1))
    chunked = chunked.permute(2, 0, 1).reshape(-1, c, chunk_size)
    outputs = []
    with torch.inference_mode():
        for start in range(0, chunked.shape[0], batch_size):
            piece = SimpleishNamespace(
                mixture={"audio": chunked[start : start + batch_size].to(device)},
                query=batch["query"],
                estimates=batch["estimates"],
            )
            outputs.append(system.forward(piece).estimates["target"]["audio"].cpu())
    output = torch.cat(outputs, dim=0)
    window = torch.hann_window(chunk_size).reshape(1, 1, chunk_size)
    output = torch.permute(output * window / scaler, (1, 2, 0))
    output = F.fold(
        output, output_size=(padded_length, 1), kernel_size=(chunk_size, 1), stride=(hop_size, 1)
    )
    return output[None, :, 0, 2 * overlap : n_samples + 2 * overlap, 0]


def load(path: str, rate: int):
    import torchaudio as ta

    audio, fs = ta.load(path)
    if fs != rate:
        audio = ta.functional.resample(audio, orig_freq=fs, new_freq=rate)
    return audio, fs


def tiled_query(query):
    """`inference_byoq`'s own handling: truncate past 10 s, tile under it."""
    import torch

    n = int(QUERY_SECONDS * MODEL_FS)
    if query.shape[1] >= n:
        return query[:, :n]
    return torch.cat([query] * (n // query.shape[1] + 1), dim=1)[:, :n]


def wait_for_gpu(torch, need_gb: float, patience_s: float) -> bool:
    """The GPU is SHARED with the harness (a CREPE re-transcription can hold
    it for hours), so a track starts only when `need_gb` is free on the
    device with this process's own cache released. Polls; False after
    `patience_s` without it."""
    torch.cuda.empty_cache()
    waited = 0.0
    while True:
        free, _total = torch.cuda.mem_get_info()
        if free / 2**30 >= need_gb:
            return True
        if waited >= patience_s:
            return False
        if waited == 0.0:
            print(f"  waiting for {need_gb:.1f} GB free on the GPU ({free / 2**30:.1f} now)")
        time.sleep(30)
        waited += 30


def infer(args) -> None:
    import torch
    import torchaudio as ta

    torch.set_num_threads(args.threads)
    cuda = not args.cpu and torch.cuda.is_available()
    if cuda:
        # Never more than this share of the card, whatever the batch asks:
        # the allocator frees its cache and retries before it fails.
        torch.cuda.set_per_process_memory_fraction(args.gpu_fraction)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out = Path(args.out) / args.condition
    out.mkdir(parents=True, exist_ok=True)
    todo = sorted(manifest)
    if args.only:
        todo = [k for k in todo if any(o in k for o in args.only.split(","))]
    todo = [k for k in todo if not (out / f"{manifest[k]['id']}.wav").is_file()]
    info_path = Path(args.out) / f"runinfo-{args.condition}.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
    if not todo:
        print("nothing to do")
        return
    started = time.time()
    system, inference = build(Path(args.repo), Path(args.ckpt), args.batch, args.hop, cuda)
    memo = QueryMemo(system, args.memo_query)
    print(f"model built in {time.time() - started:.0f}s on {'cuda' if cuda else 'cpu'}")
    import hear21passt
    import pytorch_lightning
    import timm

    info.setdefault("entries", {})
    info["runtime"] = {
        "torch": torch.__version__,
        "torchaudio": ta.__version__,
        "pytorch_lightning": pytorch_lightning.__version__,
        "hear21passt": getattr(hear21passt, "__version__", "0.0.26"),
        "timm": timm.__version__,
        "device": torch.cuda.get_device_name(0) if cuda else f"cpu x{args.threads}",
        "inference": inference,
        "checkpoint": str(args.ckpt),
    }
    if args.hash:
        info["runtime"]["checkpoint_sha256"] = sha256(Path(args.ckpt))
    for key in todo:
        entry = manifest[key]
        query_path = entry["queries"].get(args.condition)
        if query_path is None:
            print(f"  {key}: no {args.condition} query -- skipped")
            continue
        if cuda and not wait_for_gpu(torch, args.gpu_free_gb, args.patience):
            print(f"  {key}: under {args.gpu_free_gb} GB free for {args.patience:.0f}s -- stopping")
            break
        mix, fs = load(entry["mix"], MODEL_FS)
        query, _ = load(query_path, MODEL_FS)
        t0 = time.time()
        estimate = None
        for attempt in range(1, args.retries + 2):
            memo.clear()
            try:
                if args.offload:
                    estimate = chunked_inference_offload(system, mix, tiled_query(query), inference)
                else:
                    with torch.no_grad():
                        batch = {
                            "mixture": {"audio": mix.unsqueeze(0).to(system.device)},
                            "query": {"audio": tiled_query(query).unsqueeze(0).to(system.device)},
                            "metadata": {"stem": ["target"]},
                            "estimates": {},
                        }
                        estimate = system.chunked_inference(batch)["estimates"]["target"]["audio"]
                break
            except RuntimeError as error:  # torch.OutOfMemoryError is one too
                # A SHARED card: another process's allocation can fail a
                # cuDNN call (CUDNN_STATUS_EXECUTION_FAILED) or an allocation
                # mid-entry. Release, wait, redo the entry -- the result does
                # not depend on which attempt made it.
                if not cuda or attempt > args.retries:
                    raise
                print(f"  {key}: attempt {attempt} failed ({str(error)[:80]}) -- retrying")
                batch = None
                torch.cuda.empty_cache()
                time.sleep(30)
                if not wait_for_gpu(torch, args.gpu_free_gb, args.patience):
                    raise
                t0 = time.time()
        estimate = estimate.squeeze(0).cpu()
        if fs != MODEL_FS:
            estimate = ta.functional.resample(estimate, orig_freq=MODEL_FS, new_freq=fs)
        seconds = time.time() - t0
        length = mix.shape[1] / MODEL_FS
        tmp = out / f"{entry['id']}.partial.wav"
        ta.save(str(tmp), estimate, fs, encoding="PCM_F", bits_per_sample=32)
        tmp.replace(out / f"{entry['id']}.wav")
        info["entries"][key] = {
            "audio_s": round(length, 2),
            "infer_s": round(seconds, 2),
            # Per entry, because a resumed run may use another device.
            "device": info["runtime"]["device"],
            "batch": args.batch,
            "hop_s": args.hop,
            "memo_query": args.memo_query,
            "offload": args.offload,
            "query_calls": memo.calls,
            "query_embedded": memo.embedded,
        }
        info_path.write_text(json.dumps(info, indent=1), encoding="utf-8")
        print(
            f"  {key}: {length:.0f}s of audio in {seconds:.0f}s ({length / seconds:.2f}x), "
            f"query embedded {memo.embedded} time(s) for {memo.calls} batch(es)"
        )
        if cuda:
            torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("infer")
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--ckpt", required=True)
    p.add_argument("--condition", required=True, help="which query in the manifest: self | cross")
    p.add_argument("--only", default="", help="comma-separated substrings of run keys")
    p.add_argument("--cpu", action="store_true")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--hop", type=float, default=0.5, help="the authors' default is 0.5 s")
    p.add_argument("--hash", action="store_true", help="record the checkpoint's sha256")
    p.add_argument("--gpu-fraction", type=float, default=0.3, help="cap on this process's share")
    p.add_argument("--gpu-free-gb", type=float, default=3.0, help="free memory a track waits for")
    p.add_argument("--patience", type=float, default=3600.0, help="seconds to wait for it")
    p.add_argument("--retries", type=int, default=3, help="per entry, after a CUDA failure")
    p.add_argument(
        "--no-memo-query",
        dest="memo_query",
        action="store_false",
        help="embed the query per chunk batch, as the authors' code does",
    )
    p.add_argument(
        "--authors-chunking",
        dest="offload",
        action="store_false",
        help="the authors' chunked_inference, whole span on the device",
    )
    args = parser.parse_args()
    # Progress lines reach a redirected log as they happen, not at exit.
    sys.stdout.reconfigure(line_buffering=True)
    if args.command == "infer":
        infer(args)


if __name__ == "__main__":
    main()
