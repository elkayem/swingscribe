# Installing SwingScribe

There are two ways to run SwingScribe.

- **The Windows app** is a ready-to-run folder. It needs nothing else
  installed, and it is the right choice if you just want to transcribe
  solos.
- **From source** runs on Windows or Linux. Choose it if you are on Linux,
  or if you want to work on the code. macOS is untested, and
  [macOS (untested)](#macos-untested) says what trying it would take.

Either way, everything runs on your own computer. No account is needed, and
no audio leaves your machine. A GPU is not required.

When it is installed, the [user guide](src/swingscribe/gui/guide/user-guide.md)
shows you how to use it.

## The Windows app

**You need:** Windows 10 or 11 (64-bit) and about 2.5 GB of free disk space.
That covers the 1.3 GB app folder, about half a gigabyte of AI models that
download on first use, and some room for the cache. Separated stems need
more space as you work. The app's Cache panel frees it track by track.

### Install

1. **Download** `SwingScribe-<version>-windows-x64.zip` (about 450 MB) from
   the [latest release](https://github.com/elkayem/swingscribe/releases/latest).
2. **Extract it somewhere with a short path**, such as `C:\SwingScribe` or
   directly under Documents. A very deep path can hit the Windows limit on
   path length part-way through extraction.
3. **Double-click `setup.cmd`** in the folder, once. It adds a SwingScribe
   icon to the desktop and the Start menu, and an entry in
   **Settings > Apps**.
4. **Double-click the SwingScribe icon.** A console window opens minimized,
   and the app opens in your browser at `http://127.0.0.1:8420/`.

To stop SwingScribe, click **Quit** at the top right of the page. Closing the
browser tab does not stop it.

The folder holds its own Python, every library, ffmpeg and the app. Nothing
is installed in the usual sense. Nothing goes on your `PATH`, and a Python
already on your computer is not used or changed.

### The first run

The first time Windows runs a script that came from the internet, it may
say **"Windows protected your PC"**. Click **More info**, then **Run anyway**.
It asks once for each script.

The first run of each step (beats, separation and transcription) downloads
the AI model for that step. That is about half a gigabyte in all, and it
happens only once. The progress bar says so while it happens.

### What SwingScribe writes, and where

- `%LOCALAPPDATA%\SwingScribe\models` holds the downloaded AI models.
- `%LOCALAPPDATA%\SwingScribe\cache` holds separated stems and other
  derived data. This is safe to delete, and the app's Cache panel can clear
  it track by track.
- `<track>.swingscribe.json`, beside each audio file you open, holds your
  span, downbeat, edits and score link. This file is yours to keep. It is
  what makes a track open the way you left it.
- Exported MusicXML files go beside the audio file.

`swingscribe.yaml` in the app folder is the app's configuration, and every
setting in it is commented. `gui.library_dir` sets the folder the track
picker starts in, which is your Music folder by default.

### Updating

Extract the new version to a new folder, run its `setup.cmd`, and delete the
old folder. The models and the cache are shared between versions, so nothing
downloads again.

### Uninstalling

Run `uninstall.cmd` in the folder, or use **Settings > Apps > SwingScribe >
Uninstall**. It removes the icons, the Apps entry and the app folder. It
asks before it removes the data folder, and it never touches the
`.swingscribe.json` files beside your music.

### If Windows refuses to run it

Windows 11's **Smart App Control** judges each program file by its
reputation, and its verdicts change over time. Every file in the release was
checked against it. If a new PC still refuses one, an administrator can turn
the feature off at **Windows Security > App & browser control > Smart App
Control settings**. Since the April 2026 Windows update it can be turned
back on afterwards.

### If a download fails with a certificate error

Some networks inspect encrypted traffic and sign it with their own
certificate. Many workplaces do this, and so do some antivirus products.
Windows trusts that certificate, but the downloader for the default
separation model does not, so the first **Separate** fails with an error
that mentions `CERTIFICATE_VERIFY_FAILED`. To fix it:

1. **Get the network's root certificate** as a Base-64 `.cer` file. Your
   IT department can supply it. Or open https://github.com in your
   browser, click the padlock and view the certificate: the top of the
   chain is the root. If it names your company or your antivirus rather
   than a public authority, export it as "Base-64 encoded".
2. **Make a certificate bundle.** Copy
   `python\Lib\site-packages\certifi\cacert.pem` from the SwingScribe
   folder to a folder of its own, such as `C:\SwingScribe-certs\`, so an
   update does not delete it. Open the copy in Notepad, paste the whole
   text of the `.cer` file at the end, and save.
3. **Point SwingScribe at it.** Open **Start > Edit environment variables
   for your account** and add two variables, `SSL_CERT_FILE` and
   `REQUESTS_CA_BUNDLE`, both set to the bundle, for example
   `C:\SwingScribe-certs\cacert.pem`.
4. **Quit SwingScribe and start it again** from the icon.

### If a separation crashes

A separation needs a few GB of free memory. When it runs out, the job
fails with "the separation process crashed" and a mention of memory.
Close other programs and try again, or choose **htdemucs** in the
separator menu, a much smaller model.

## From source

**You need:**

- [uv](https://docs.astral.sh/uv/getting-started/installation/), the Python
  package manager. It installs Python 3.11 for you if needed.
- [git](https://git-scm.com/).
- [ffmpeg](https://ffmpeg.org/download.html), to open anything other than
  `.wav` and `.flac` files, such as mp3, m4a, aac or ogg.

```bash
git clone https://github.com/elkayem/swingscribe.git
cd swingscribe
uv sync --group ml --group gui --group roformer
uv run python -m swingscribe gui
```

The three dependency groups are the AI stack (`ml`), the web app (`gui`),
and the BS-RoFormer separator (`roformer`). Name all the groups you want
every time you run `uv sync`, because it removes whatever the named groups
do not need.

The app opens in your browser at `http://127.0.0.1:8420/`. To open a file
straight away, and list its folder in the track picker, name it:

```bash
uv run python -m swingscribe gui path/to/track.m4a
```

`gui` also takes `--port <n>`, `--no-browser`, and `--library <folder>` to
choose the folder the track picker starts in. Click **Quit** in the app's
header to stop the server. Closing the tab does not stop it.

### On Windows

Start the app with `uv run python -m swingscribe ...` or with the
`.\swingscribe.cmd` shim beside `pyproject.toml`. Do not use `uv run
swingscribe ...`. That runs a `swingscribe.exe` stub that is generated anew
at every install, and Smart App Control refuses it as an unknown program
(`os error 4551`). `.\swingscribe.cmd gui` never meets that check.

`scripts\make_shortcut.ps1` puts a SwingScribe icon on your desktop that
launches the app through the shim.

### Using an NVIDIA GPU (optional)

A GPU makes separation about four times faster. The lock file installs the
CPU builds of PyTorch, which keeps the install portable. To use a CUDA GPU,
install the CUDA build of the same versions over them:

```bash
uv pip install --no-deps --index-url https://download.pytorch.org/whl/cu130 torch==2.12.1+cu130 torchaudio==2.11.0+cu130
```

`cu130` is the build tested here, and it needs a recent NVIDIA driver.
[pytorch.org](https://pytorch.org/get-started/locally/) lists the other CUDA
builds. Every later `uv sync` puts the CPU builds back, so run this again
after a sync. To confirm the GPU is in use, watch `nvidia-smi` while a
separation runs.

### Downloads fail behind a corporate network

Some networks intercept TLS, and then the model downloads fail with
`CERTIFICATE_VERIFY_FAILED`. Point Python at a certificate bundle that
includes your organisation's root certificate by setting `SSL_CERT_FILE`
and `REQUESTS_CA_BUNDLE`. For uv itself, set `UV_SYSTEM_CERTS=true`.

## macOS (untested)

Nobody has run SwingScribe on a Mac yet. It is untested rather than
incompatible, and these notes are for a developer who wants to try.
They record what was checked from a Windows machine on 2026-09-27.

**What was checked:**

- **The dependencies resolve for Apple Silicon.** A copy of the project
  with macOS allowed locked cleanly, with native wheels for every compiled
  library: torch, torchaudio, onnxruntime, numba, llvmlite and soundfile.
- **The code has no Windows-only paths** in the pipeline or the web app.
  ffmpeg is found on the `PATH`, the folder browser handles a Unix root,
  and the tier-1 tests already pass on Linux in CI.

**What is needed:**

- **An Apple Silicon Mac (M1 or later) on macOS 14 Sonoma or later.**
  torch 2.12 and onnxruntime 1.29 publish Mac wheels only for Apple
  Silicon, built for macOS 14. There are no Intel Mac wheels.
- **Allow macOS in the lock.** `pyproject.toml` limits the lock to
  Windows and Linux, so `uv sync` on a Mac refuses to install anything.
  Add Apple Silicon to `environments` under `[tool.uv]`, then run
  `uv lock`:

  ```toml
  environments = [
      "sys_platform == 'win32'",
      "sys_platform == 'linux'",
      "sys_platform == 'darwin' and platform_machine == 'arm64'",
  ]
  ```

- **Decide about the torch cap.** torch and torchaudio are capped below
  2.13 because Smart App Control blocks a file in torch 2.13 on Windows.
  That reason does not apply to a Mac. With the cap in place, the lock
  falls back to audio-separator 0.45 on a Mac, because 0.47 needs torch
  2.13 or later there. That combination is untested with the default
  separator. To give the Mac current versions, make the cap apply
  everywhere except macOS, for example
  `"torch>=2.4,<2.13; sys_platform != 'darwin'"` beside
  `"torch>=2.4; sys_platform == 'darwin'"`, and the same for torchaudio.
- **ffmpeg:** `brew install ffmpeg`.

Then install and run as in [From source](#from-source). `uv run swingscribe
gui` also works on a Mac, because the Windows warning about the generated
stub does not apply.

**What to expect, and what to look at first:**

- **Everything runs on the CPU except the default separator.**
  SwingScribe's device setting chooses between CUDA and the CPU, so demucs,
  CREPE, the beat tracker and the piano model run on the CPU. audio-separator
  switches to Apple's GPU (MPS) by itself on Apple Silicon, so the
  BS-RoFormer may run faster than on a CPU, or may fail on an operation MPS
  lacks. Setting `separate.device` to `cpu` does not reach it. Teaching
  `src/swingscribe/device.py` about `mps` would let the other models try
  the GPU too, but each one needs checking.
- **Keep the separator's weights out of `/tmp`.** audio-separator stores
  its models in `/tmp/audio-separator-models/` unless told otherwise, and
  macOS empties `/tmp` on reboot. The download is about 700 MB. Set
  `AUDIO_SEPARATOR_MODEL_DIR` to a permanent folder, and create the folder
  first, because audio-separator refuses one that does not exist.
- **Run the tests first:** `uv run pytest`. Adding `macos-latest` to the
  matrix in `.github/workflows/ci.yml` would keep them passing.

**The ready-to-run app is Windows-only.** Its launcher, setup and uninstall
scripts are `.cmd` files, and its build fetches a Windows Python and a
Windows ffmpeg. A Mac version could take the same shape: a folder with a
standalone Python, the locked libraries and a launcher script. It would
also have to get past Gatekeeper, which quarantines unsigned downloads, and
notarizing an app needs a paid Apple developer account.
`docs/packaging-plan.md` has the Windows design and a note on the Mac.

## Next steps

- The **[user guide](src/swingscribe/gui/guide/user-guide.md)** covers every
  control, the keyboard shortcuts and the command line. It is also behind
  the app's **Help** button.
- **[docs/development.md](docs/development.md)** explains how to run the tests
  and the benchmarks.
- **[NOTICES.md](packaging/NOTICES.md)** lists the licences of the AI models
  and libraries.
