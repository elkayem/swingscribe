# Third-party notices

SwingScribe is MIT licensed (see `LICENSE`). It runs on the libraries and
model weights below, each under its own terms. The portable folder ships the
libraries and one small model, Basic Pitch's; the other model weights are
downloaded by SwingScribe on first use into `%LOCALAPPDATA%\SwingScribe\models`
and are never redistributed by it.

## Model weights shipped inside SwingScribe

**Basic Pitch** (Spotify; Rachel M. Bittner, Juan José Bosch, David Rubinstein,
Gabriel Meseguer-Brocal and Sebastian Ewert, "A Lightweight
Instrument-Agnostic Model for Polyphonic Note Transcription and Multipitch
Estimation", ICASSP 2022), licensed under the Apache License, Version 2.0.
It fills the holes in a horn's line (docs/frontend-bakeoff.md). SwingScribe
ships its ICASSP 2022 model graph unmodified as
`swingscribe\basic-pitch-nmp.onnx` (basic-pitch 0.4.0's
`saved_models/icassp_2022/nmp.onnx`, 230 KB), and `swingscribe\basic_pitch.py`
is a port of parts of basic-pitch 0.4.0's `inference.py` and
`note_creation.py` to plain numpy (the package itself is not used). The
licence text is beside the graph, `swingscribe\basic-pitch-LICENSE.txt`.
Basic Pitch's NOTICE file reads:

```
Basic Pitch
Copyright 2022 Spotify AB

This product includes software developed at
Spotify AB (http://www.spotify.com/).

This product includes software from Librosa (ISC).
* Copyright (C) 2013--2017, librosa development team.

This product includes software from mir_eval (MIT)
* Copyright (C) 2014 Colin Raffel

This product includes software from numpy (BSD)
* Copyright (C) 2005-2022, NumPy Developers.

This product includes software from pretty-midi (MIT)
* Copyright (C) 2014 Colin Raffel

This product includes software from resampy (ISC)
* Copyright (C) 2016, Brian McFee

This product includes software from scipy (BSD)
* Copyright (C) 2001-2002 Enthought, Inc. 2003-2022, SciPy Developers

This product includes software from tensorflow (Apache 2.0)
* Copyright (C) 2019 Google, LLC <packages@tensorflow.org>

The tests for `basic-pitch` include audio files from the
Vocadito dataset liscened under Creative Commons
Attribution 4.0 International. The dataset can be found at:
https://zenodo.org/record/5578807#.YnRm5vPMKDU
```

## Model weights (downloaded on first use)

| Weights | Used for | Source | Licence |
|---|---|---|---|
| Hybrid Transformer Demucs (`htdemucs`, `htdemucs_6s`, `htdemucs_ft`) | source separation | facebookresearch/demucs, via torch hub | MIT |
| beat_this `final0` | beat tracking | CPJKU/beat_this, via torch hub | MIT (code and weights) |
| Piano transcription CRNN (Kong et al., 2020) | piano second opinion and the oracle line | Zenodo record 4034264 | CC BY 4.0 — Qiuqiang Kong, Bochen Li, Xuchen Song, Yuan Wan, Yuxuan Wang, "High-resolution piano transcription with pedals by regressing onset and offset times" |
| BS-Roformer-SW | source separation, the default separator | the UVR community model repository, through python-audio-separator's model zoo | **None. The weights are of unknown authorship.** They were rehosted by jarredou, who has said they did not train them and know nothing of their origin, and whose account is gone; every redistribution since declares the licence unknown (checked 2026-09-14). SwingScribe does not ship them: your machine downloads them from the community repository the first time you separate with this model. For your own transcribing that is the same position every UVR user is in. For anything you sell, choose `htdemucs` (MIT) in the separator menu. |

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
| Verovio | LGPL-3.0 — engraves the in-app page view; shipped unmodified as its own module (`verovio\`, with the Microsoft C++ runtime it bundles in `verovio.libs\`), so it can be replaced. Its music fonts (Leipzig, Bravura, Leland, Petaluma) and its Liberation text font are under the SIL Open Font License |
| pydantic, pydantic-settings | MIT |
| mir_eval | MIT |
| pretty_midi | MIT |
| soundfile, libsndfile | BSD-3-Clause, LGPL-2.1 |
| numpy, scipy | BSD-3-Clause |
| ffmpeg (BtbN win64 **LGPL** build) | LGPL-2.1+ — this build is configured without GPL components |

Each library's own licence text is in its `dist-info` directory under
`python\Lib\site-packages`, and ffmpeg's under `ffmpeg\`.
