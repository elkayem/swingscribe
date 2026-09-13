# Third-party notices

SwingScribe is MIT licensed (see `LICENSE`). It runs on the libraries and
model weights below, each under its own terms. The portable folder ships the
libraries; the model weights are downloaded by SwingScribe on first use into
`%LOCALAPPDATA%\SwingScribe\models` and are never redistributed by it.

## Model weights (downloaded on first use)

| Weights | Used for | Source | Licence |
|---|---|---|---|
| Hybrid Transformer Demucs (`htdemucs`, `htdemucs_6s`, `htdemucs_ft`) | source separation | facebookresearch/demucs, via torch hub | MIT |
| beat_this `final0` | beat tracking | CPJKU/beat_this, via torch hub | MIT (code and weights) |
| Piano transcription CRNN (Kong et al., 2020) | piano second opinion and the oracle line | Zenodo record 4034264 | CC BY 4.0 — Qiuqiang Kong, Bochen Li, Xuchen Song, Yuan Wan, Yuxuan Wang, "High-resolution piano transcription with pedals by regressing onset and offset times" |
| BS-Roformer-SW (jarredou) | source separation, the default separator | python-audio-separator's model zoo | **not stated by its author as of 2026-09-13.** Until it is, treat it as available for personal and research use only; choose `htdemucs` in the separator menu for anything commercial. |

## Libraries (shipped in the folder)

| Library | Licence |
|---|---|
| Python (python-build-standalone) | PSF |
| PyTorch, torchaudio | BSD-3-Clause |
| demucs | MIT |
| beat_this | MIT |
| torchcrepe | MIT |
| piano-transcription-inference, torchlibrosa | MIT |
| python-audio-separator | MIT — its models come from the UVR project; credit to UVR and its developers, as its licence asks |
| onnxruntime | MIT |
| FastAPI, Starlette, uvicorn | MIT, MIT, BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| mir_eval | MIT |
| pretty_midi | MIT |
| soundfile, libsndfile | BSD-3-Clause, LGPL-2.1 |
| numpy, scipy | BSD-3-Clause |
| ffmpeg (BtbN win64 **LGPL** build) | LGPL-2.1+ — this build is configured without GPL components |

Each library's own licence text is in its `dist-info` directory under
`python\Lib\site-packages`, and ffmpeg's under `ffmpeg\`.
