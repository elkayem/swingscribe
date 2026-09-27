# Installing SwingScribe

There are two ways to run SwingScribe.

- **The Windows app** is a ready-to-run folder. It needs nothing else
  installed, and it is the right choice if you just want to transcribe
  solos.
- **From source** runs on Windows or Linux. Choose it if you are on Linux,
  or if you want to work on the code. macOS is not supported yet.

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

## Next steps

- The **[user guide](src/swingscribe/gui/guide/user-guide.md)** covers every
  control, the keyboard shortcuts and the command line. It is also behind
  the app's **Help** button.
- **[docs/development.md](docs/development.md)** explains how to run the tests
  and the benchmarks.
- **[NOTICES.md](packaging/NOTICES.md)** lists the licences of the AI models
  and libraries.
