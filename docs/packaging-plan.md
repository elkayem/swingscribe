# Packaging plan: a double-click SwingScribe

Status: **reviewed 2026-09-12; pieces 1 and 2 and the config move are being
built, piece 3 waits for a release.** The review's findings are folded in
below and the decisions it settled are recorded at the end.

## What this delivers

Three pieces, in order. Each is useful on its own and none depends on the next,
so the first two can land now and the third can wait for a product worth
shipping.

| Piece | For whom | When |
|---|---|---|
| 1. A **Quit** button in the GUI that stops the server | everyone | now |
| 2. A **desktop icon** that launches the GUI on this machine | the developer | now |
| 3. An **installer** built by PyInstaller, Windows then Mac | users | when the product ships |

The end state for a user: download one installer from the GitHub Releases
page, double-click it, get an icon. Double-click the icon, the app opens in the
browser. Click Quit, it is gone. Nothing about Python, uv, or a terminal is
visible to them.

---

## 1. The Quit button

### What it does

A **Quit** button in the header beside Help. Clicking it sends one request to
the server; the page replaces itself with a plain "SwingScribe has stopped.
You can close this tab." notice and stops polling; the server finishes the
request and exits. The console window it was launched from closes with it.

If a job is running (a separation, a transcription, a beats pass) the button
**arms instead**: it turns red, says what it would abandon ("Quit and abandon
the separation of Oleo?"), and needs a second click within four seconds. That is
the gesture the cache panel already uses for deletes, so it is not a new
convention. Abandoning a job loses only cache work. The span, downbeat,
erasures and every other human judgement live in the sidecar beside the audio
and are written as they change, so nothing the listener did is lost.

### How it works

`gui/server.py` runs uvicorn with `uvicorn.run(...)`, which owns the server
object and gives us no handle on it. The change is to build the server
explicitly, `uvicorn.Server(uvicorn.Config(...))`, and hand the app a callable
that sets `server.should_exit = True`. Uvicorn checks that flag every tick,
finishes in-flight requests and returns, and `cmd_gui` returns 0 as it does
after Ctrl-C today.

The app must not import uvicorn (it is a thin adapter over the pipeline and
is tested with a TestClient that has no server), so the callable is injected:
`create_app(config, on_quit=...)`, stored on `app.state`, with a no-op default
so every existing test and caller is untouched.

Before setting the flag the endpoint cancels every active job through the
existing `JobManager.cancel`, which already terminates a separation's child
process within a second. Without that, the child process would outlive the
server and keep separating into the cache with nobody listening.

The server listens on 127.0.0.1 only, so nothing off this machine can reach the
endpoint. **Any web page open in the same browser can, though**: a page on
another site can POST to localhost, and the request takes effect even though
the page cannot read the reply. That was already true of the cache panel's
deletes and every other state-changing route. The fix is one middleware: a
request that is not a GET must carry no `Origin` header (a same-site form or
a test client) or one naming this server (`http://127.0.0.1:8420` or
`http://localhost:8420`), and anything else is refused with 403 before it
reaches a route. It covers quit, the deletes, job submission and the sidecar
writes alike; the frontend's own `fetch` calls always pass because they are
same-origin.

### Changes, by file

- `gui/app.py`: `POST /api/quit`. Returns 409 with the list of active jobs
  unless `?force=1`; otherwise cancels them, calls `on_quit`, returns 200.
  `create_app` gains the `on_quit` parameter. The same-origin middleware
  above, applied to every non-GET request.
- `gui/server.py`: build `uvicorn.Server` explicitly and pass the setter.
  Change the console line "Ctrl-C to stop" to name the button too.
- `gui/static/index.html`, `app.js`, `style.css`: the button, its armed state,
  the stopped notice. Polling timers are cleared once the notice is up so the
  page does not fill the console with connection errors.
- `gui/guide/user-guide.md`: one paragraph under Overview, one line under
  Troubleshooting ("the browser tab closed but the console window is still
  there: the server is still running; reopen http://127.0.0.1:8420/ and
  click Quit, or close the console window").
- `tests/test_gui_api.py`: the endpoint calls `on_quit` with no jobs;
  refuses with 409 and does NOT call it when a job is active; cancels and
  calls it under `force`; a POST carrying a foreign `Origin` is refused and
  one carrying the server's own passes.

Size: about two hours. No new dependency.

### What it does not do

It does not notice the browser tab being closed. That would need a heartbeat
from the page and a server that exits when the heartbeat stops, and it has to
tolerate a reload, a laptop asleep and a second tab. The button never guesses,
so it is the right first step; a heartbeat can be added later without changing
anything here.

---

## 2. The desktop icon (this machine)

A Windows shortcut, nothing built. It runs the existing `swingscribe.cmd`
launcher, which is the route that never trips Smart App Control because a
`.cmd` is a script, not a binary.

| Shortcut field | Value |
|---|---|
| Target | `C:\Users\lkmcg\OneDrive\Documents\ClaudeCode\swingscribe\swingscribe.cmd gui` |
| Start in | `C:\Users\lkmcg\OneDrive\Documents\ClaudeCode\swingscribe` |
| Run | **Minimized** (not hidden; see below) |
| Icon | `assets/swingscribe.ico` (to be made; see below) |

`scripts/make_shortcut.ps1` creates it with `WScript.Shell` so it is
reproducible, and can be re-run after the repo moves.

Three things about this that are not obvious:

- **Start in decides two defaults.** `cache_dir` is `.swingscribe-cache`
  relative to the working directory and the file picker opens in the working
  directory too (`library.library_dir`). Starting in the repo root reuses the
  78 GB of stems already there. Any other folder starts an empty cache.
- **Minimized, never hidden.** CLAUDE.md, 2026-09-08: on this machine a
  process with no console window HANGS when Application Control refuses a DLL,
  instead of raising the error the transcribe shim is built to catch. A hidden
  launch would freeze the first transcription with nothing on screen to say
  why. A minimized console is out of the way and still a window. The Quit
  button closes it.
- **The `.cmd` prefers `.venv\Scripts\python.exe`, which Smart App Control
  blocked on 2026-09-12.** If the shortcut opens and closes instantly, that is
  why. The fix is in the launcher, not the shortcut: fall through to the base
  uv interpreter with `PYTHONPATH=.venv\Lib\site-packages;src` when the venv
  launcher is refused (the recipe in the session memory
  `machine-venv-python-launcher-blocked`). Worth doing as part of this piece so
  the icon survives the next reputation flap.

The icon file: the GUI has no favicon and the repo has no `.ico`. One is made
once from a 256 px PNG (a treble clef over a waveform, or the hero image
cropped) with a short PowerShell `System.Drawing` script, so no new
dependency. The same file becomes the installer's and the exe's icon later.

Size: fifteen minutes for the shortcut, an hour with the launcher fallback and
the icon.

---

## 3. The installer (PyInstaller)

### What the user receives

`SwingScribe-<version>-windows-x64.exe`, roughly 600 to 900 MB, downloaded
from the GitHub Releases page. Running it installs a folder under Program
Files, a Start Menu entry and an optional desktop icon, and registers an
uninstaller. First launch downloads the model weights (about half a gigabyte)
into the user's profile and says so on screen. Nothing needs to be installed
first: Python, torch, ffmpeg and the GUI's libraries are all in the folder.

It is a **folder build with a launcher** (PyInstaller "onedir"), wrapped in an
installer, not a single self-extracting file. A onefile build of this size
unpacks to a temp directory on every launch and puts a long pause before
anything appears.

### Why this and not a bootstrap launcher

A bootstrap (a few-megabyte program that installs Python and the libraries on
first run) has almost no build recipe to write, but every first launch then
depends on the user's network, on the package index being up, and on the
resolver picking the versions we tested. The installer contains exactly what
was tested and works offline once installed. The price is the recipe below,
paid once.

### Prerequisites in the codebase

These are small changes that make the code location-independent. Each is worth
doing before any build is attempted, and each is a normal commit with tests.

1. **`multiprocessing.freeze_support()` first thing in the entry point.**
   Separation runs in a spawned child process (`jobs._run_separation`). In a
   frozen app, spawn re-executes the launcher; without `freeze_support` the
   child starts a second GUI server instead of the worker. This one is not
   optional and it does not show up until the first Separate click.
2. **Move `config/default.yaml` into the package.** `DEFAULT_CONFIG_PATH` is
   `Path(__file__).parents[2] / "config" / "default.yaml"`, which resolves to
   the repo root in a checkout and to nothing useful anywhere else (it is
   already wrong for a wheel install). Ship it as package data beside
   `config.py` as `swingscribe/default-config.yaml` (not under a `config/`
   directory, which would shadow the module's name), found with
   `Path(__file__).parent`, which PyInstaller preserves for bundled data.
   `--config` keeps working for an editable file beside the exe, which is the
   "editable configuration file" from the original question. **Done
   2026-09-12.**
3. **A per-user data directory when frozen.** `cache_dir` and the file
   picker's start folder default to the working directory, which for an
   installed app is Program Files. When `sys.frozen` is set, default
   `cache_dir` to `%LOCALAPPDATA%\SwingScribe\cache` (Mac:
   `~/Library/Application Support/SwingScribe`) and the picker to the user's
   Music folder. Development checkouts keep `.swingscribe-cache`. `cache_dir`
   is not part of any cache key, so no key moves.
4. **ffmpeg beside the executable.** `ingest.find_ffmpeg` looks on PATH and
   then in winget's folder. Add a first look beside `sys.executable` (and
   inside the `.app` on Mac). The build bundles a static ffmpeg built under
   the LGPL configuration, not the GPL builds most download sites offer,
   because a GPL binary shipped inside the installer would bind the whole
   app's licence. About 80 MB.
5. **Model-weight downloads must be visible.** All four sets download on
   first use into the user's profile (torch hub for demucs and beat_this,
   `~/piano_transcription_inference_data`, audio-separator's model folder).
   Check each one reports through the job's progress channel; today the
   piano one prints to the console, which an installed user does not see.
   Bundling the weights instead is possible (installer grows to about
   1.5 GB) and is a reviewer decision below.
6. **Console on, for the first cut.** PyInstaller's windowed mode hides the
   console. On a Smart App Control machine a blocked DLL then hangs silently
   (the same trap as the shortcut above), and the console is the only place
   the server's startup line appears if the browser fails to open. Ship with
   the console minimized behind the browser; revisit once a native window
   exists (follow-on, below).
7. **A first-run notice that names the sidecar.** An installed app writes a
   small `<track>.swingscribe.json` beside every audio file the user opens,
   holding their span, downbeat and edits. That is the right design (the
   cache must stay deletable; the judgements must not), but a user who has
   not read the guide will wonder what the file is. The first-run notice
   that reports the weight downloads gets one sentence about it.

(The version string is a constant in the package and `--version` prints it;
nothing reads `importlib.metadata`, so no dist-info needs copying in.)

### The build recipe

Two files under `packaging/`, both text, both in git:

- `packaging/launch.py`: the frozen entry point. Calls `freeze_support()`,
  then `swingscribe.cli.main(["gui", *sys.argv[1:]])`.
- `packaging/swingscribe.spec`: the PyInstaller spec. Onedir, name
  `SwingScribe`, icon from `assets/`. Data files: the GUI's `static/` and
  `guide/`, the packaged default config, torchcrepe's weight assets,
  demucs's model manifests, beat_this and audio-separator package data,
  ffmpeg. Hidden imports: the modules torch, torchaudio, demucs,
  onnxruntime and audio-separator load by name at runtime. Excludes: pytest,
  ruff, openpyxl and the rest of the dev and batch groups.

The hidden-import and data-file lists are found by iteration: build, launch,
read the "module not found" or the blank page, add a line, rebuild. A build
with torch takes a few minutes. Expect a day or two the first time and
nothing after that unless a dependency is added or upgraded, when it is
usually one added line.

The build is then wrapped by `packaging/windows.iss` (Inno Setup, a free
installer builder): install to Program Files, Start Menu entry, optional
desktop icon, uninstaller. Per-user data under `%LOCALAPPDATA%` is never
touched by the uninstaller.

### Testing the build

The build can only be trusted on a machine that has never had the dev venv,
because a missing file would otherwise be found on the dev machine's PATH or
in its caches. The GitHub Actions Windows runner is such a machine, and it is
also the one place the build will run before signing: **Smart App Control on
the dev machine will refuse the unsigned launcher exe** exactly as it refuses
`swingscribe.exe` today, so local double-click testing waits for a signed
build or a second PC.

The smoke test, run on the runner in `--no-browser` mode: launch, open a
tier-1 rendered fixture through the API, run Beats, separate with htdemucs,
transcribe, export MusicXML, Quit. Every step except transcribe is under a
minute on the runner; the weights download on the way.

**The iteration loop is the schedule risk.** The recipe is written by
building, launching, reading the failure and adding a line, and if every
launch of the unsigned exe has to happen on a CI runner that installs torch
first, each turn of that loop is a quarter of an hour or more. The one-to-two
day estimate for 3b assumes a machine where the build can be launched
directly: a Windows VM on this machine with Smart App Control off, or any
second PC. Decide which before starting 3b; without one, budget a week.

### Weight licences

Downloading the weights on first run means the installer never redistributes
them, but the user still runs each model under its own terms, and the
project's MIT licence and the CC BY-NC rule already on record for MuScriptor
(plan §11) are the precedent for keeping non-commercial terms out of the
core. Checked 2026-09-12:

| Weights | Fetched from | Licence | Standing |
|---|---|---|---|
| htdemucs (Demucs v4) | torch hub, facebookresearch/demucs | MIT (the repo names no separate licence for the weights) | clear |
| beat_this `final0` | torch hub, CPJKU/beat_this | MIT, stated for code and weights together | clear |
| piano transcription CRNN (Kong et al.) | Zenodo record 4034264 | CC BY 4.0 | clear; the attribution belongs in the About text |
| BS-Roformer-SW (jarredou) | audio-separator's model zoo | **not stated** in the zoo's `models.json` and the model page is not publicly readable | **release gate** |

The Roformer is the default separator, so the last row blocks a release
until its terms are established. If they turn out to be non-commercial the
options are the MuScriptor shape (its own dependency group and module
boundary, chosen by the user) or falling back to htdemucs as the shipped
default; a first release could ship htdemucs-only while the question is
open. audio-separator itself is MIT and asks for UVR attribution when its
models are used.

### Mac

Separate build, same recipe, different machine. Not cross-compilable: it is
built on a Mac or on GitHub's `macos-14` runner, which is Apple Silicon.

- **Apple Silicon only.** Torch ships no universal binary, so an Intel Mac
  would be a second artifact with a second test cycle. Intel Macs stopped
  selling in 2023; leave them out unless someone asks.
- **pyproject excludes macOS today** (`tool.uv.environments`). Add
  `sys_platform == 'darwin'`, and make the torch index source conditional:
  on Mac torch comes from PyPI (the CPU index has no macOS wheels) and uses
  the Metal GPU on its own.
- **numba and librosa load normally on a Mac**, so `torchcrepe` imports
  without the shim's fallback path. Nothing should change, but it is the first
  time that path is exercised outside this machine.
- **ffmpeg**: an arm64 LGPL static build inside the `.app`.
- PyInstaller's `BUNDLE` step produces `SwingScribe.app`; `hdiutil` wraps it
  in a `.dmg` with a drag-to-Applications window.
- **Signing and notarization are mandatory**, not optional: since macOS 15 an
  unnotarized download cannot be opened by right-click at all, only by a trip
  to System Settings. Needs an Apple Developer account, `codesign` with a
  Developer ID certificate, and `notarytool` submission in the workflow.

Someone with a Mac has to double-click the result once before it is released.
The runner can run the CLI smoke test but cannot tell us the icon opened a
browser.

### Signing

| Platform | What | Cost | Without it |
|---|---|---|---|
| Windows | Azure Trusted Signing, or an OV certificate | about $10 a month | SmartScreen "unrecognized app" on every user's first run; Smart App Control machines refuse it outright |
| Mac | Apple Developer Program | $99 a year | "cannot be opened" with no right-click escape on current macOS |

Certificates and the Apple credentials live in GitHub Actions secrets, never in
the repo. Windows reputation with SmartScreen still accrues per publisher over
weeks even when signed; the first releases will warn some users regardless.

### Release mechanics

`.github/workflows/release.yml`, triggered by pushing a tag `v*`:

1. Windows runner: `uv sync` with the ml, gui and roformer groups, build the
   spec, run the smoke test, sign, build the Inno installer.
2. macOS runner: same, then codesign, notarize, staple, make the dmg.
3. Attach both to a GitHub Release for the tag.

Nothing binary enters git. Releases sit beside the repository, each version
under its own tag, with a 2 GB per-file limit that a 900 MB installer clears.
The version number comes from `pyproject.toml`; the workflow refuses a tag
that does not match it.

---

## Effort and cost

| Piece | Developer time | Money |
|---|---|---|
| 1. Quit button and the same-origin check | 2 hours | none |
| 2. Desktop icon, launcher fallback, icon file | 1 hour | none |
| 3a. Codebase prerequisites (seven items above) | half a day | none |
| 3b. Windows spec, first working build | 1 to 2 days with a local test machine; a week through CI alone | none |
| 3c. Inno Setup installer and the release workflow | half a day | none |
| 3d. Windows signing setup | half a day | ~$10 a month |
| 3e. Mac build, dmg, notarization | 1 to 2 days | $99 a year |
| Per release after that | a tag push and a wait | |

Pieces 1 and 2 are cheap and are worth doing now. Piece 3 is worth doing when
there is a version to give someone, and not before: the spec encodes the
dependency list, and the project still adds dependencies by milestone.

## Follow-on, out of scope here

- **A native window** (`pywebview`): the same page in an OS window with the
  app's own icon, no browser chrome, close-the-window-to-quit. One small pure
  Python dependency and about twenty lines. It is the right shape for a
  shipped app and would replace the visible console. Its own proposal, once
  the Quit button exists to compare against.
- **A heartbeat** so the server exits when the last tab closes.
- **A Windows build that uses an NVIDIA card.** The CUDA torch wheel is
  2.5 GB on its own; a second, larger installer for the people who have one.

## Decisions (settled at review, 2026-09-12)

1. **Quit when busy: arm and confirm.** Refusing until a separation
   finishes is a ten-minute wait to close a window.
2. **Console visible and minimized in the first cut.** The silent hang is
   real on machines like this one.
3. **Weights download on first run.** It also keeps the licence question
   above at arm's length: nothing is redistributed.
4. **Windows first.** Mac when someone with a Mac asks, since nobody here
   can double-click the result. Apple Silicon only when it comes.
5. **Move the default config into the package now.** It fixes a latent bug
   for any wheel install; the places that name the old location are a
   handful of one-line edits.
6. **Signing is a piece 3 cost.** Nothing in pieces 1 and 2 needs it;
   approve it when there is a release to sign.
7. **Open: where piece 3b iterates.** A Windows VM without Smart App Control
   on this machine, or a second PC, before 3b starts.
8. **Open: the BS-Roformer-SW licence**, before any release.
