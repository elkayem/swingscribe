# Packaging plan: a double-click SwingScribe

Status: **pieces 1 and 2 done (2026-09-12); piece 3 re-planned as a
portable folder in a zip (2026-09-13) and not started.** The review's
findings are folded in below and the decisions are recorded at the end.

## What this delivers

Three pieces, in order. Each is useful on its own and none depends on the next,
so the first two can land now and the third can wait for a product worth
shipping.

| Piece | For whom | When |
|---|---|---|
| 1. A **Quit** button in the GUI that stops the server | everyone | now |
| 2. A **desktop icon** that launches the GUI on this machine | the developer | now |
| 3. A **portable folder** in a zip, with setup and uninstall scripts, Windows first | users | when the product ships |

The end state for a user: download one zip from the GitHub Releases page,
extract it, double-click `setup.cmd`, get an icon. Double-click the icon,
the app opens in the browser. Click Quit, it is gone. Nothing about Python,
uv, or a terminal is visible to them, and nothing else on their machine is
touched.

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
| Icon | `assets/swingscribe.ico` (drawn by the script; see below) |

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
dependency. The same file becomes the shipped folder's icon.

Size: fifteen minutes for the shortcut, an hour with the launcher fallback and
the icon.

---

## 3. The portable folder (revised 2026-09-13; was a PyInstaller installer)

### Why a folder in a zip, and not an installer

Smart App Control judges every executable file by the reputation of its
exact bytes. A PyInstaller launcher embeds our code, so every build is a
binary nobody has seen and it is refused; an Inno Setup installer is a
unique binary for the same reason. Signing would fix both, and the signing
budget is zero. A folder of files that already have reputation — a standard
`python.exe`, the DLLs exactly as the wheels ship them, ffmpeg from a known
build — runs nothing new, and a zip runs nothing at all when it is
extracted. So the shipped artifact is that folder, zipped, and it can be
verified here with the feature on, which no installer could be.

What it gives up against the installer: about twice the disk (nothing is
pruned), no Program Files location, and SmartScreen's one-time "Run"
prompt on the first launch of the `.cmd`, because the file came from the
internet. What it gains: no signing, no hidden-import wrangling (the whole
`site-packages` goes in), and a build that is a copy, not a compile.

### What the user receives

`SwingScribe-<version>-windows-x64.zip`, roughly 700 MB, from the GitHub
Releases page. They extract it wherever they like — Documents, the desktop,
a second drive — and get one folder:

```
SwingScribe\
  SwingScribe.cmd       launch (the desktop icon points here)
  setup.cmd             desktop icon + an entry in Settings > Apps
  uninstall.cmd         the reverse of setup, plus the folder itself
  swingscribe.yaml      the editable configuration file
  README.txt            the short version of the install page
  python\               CPython 3.11 with every library in its site-packages
  ffmpeg\               ffmpeg.exe, an LGPL build
```

Double-clicking `setup.cmd` once puts the icon on the desktop; the icon
launches the GUI. First launch downloads the model weights (about half a
gigabyte) into the user's profile and says so on screen. Nothing needs to
be installed first, and nothing on the machine is changed except what
setup writes, listed below.

### Isolation from anything else on the machine

The folder cannot see, and cannot be seen by, a Python already installed on
the machine, whatever library versions it has:

- **Its own interpreter and its own libraries.** `python\python.exe` is the
  interpreter and `python\Lib\site-packages` holds torch, the separators,
  the GUI's libraries and SwingScribe itself, at the versions in the lock
  file. The launcher runs it with `-I`, Python's isolated mode: it ignores
  `PYTHONPATH`, `PYTHONHOME`, the user's own site-packages and the current
  directory, so another Python's packages never load, and ours are never
  visible to it.
- **Nothing on PATH, nothing in the registry** apart from the per-user
  uninstall entry `setup.cmd` writes (below). The launcher prepends
  `ffmpeg\` to PATH for its own process only, which is how
  `ingest.find_ffmpeg` finds it with no code change; that PATH dies with
  the process.
- **Downloads and the cache in one per-user place**,
  `%LOCALAPPDATA%\SwingScribe`. The launcher sets `TORCH_HOME` (demucs and
  beat_this weights), `AUDIO_SEPARATOR_MODEL_DIR` (the Roformer; its
  default is `\tmp\audio-separator-models` on the drive root) and
  `SWINGSCRIBE_CACHE_DIR` (pydantic-settings already reads `SWINGSCRIBE_*`),
  and the piano checkpoint path gains the same override. A user who also
  has the dev environment sees no clash: the two keep separate copies.
- **The only file written anywhere else is the sidecar beside the audio**,
  `<track>.swingscribe.json`, which holds the listener's own judgements and
  is theirs to keep.

### Uninstall

`uninstall.cmd` removes, in order: the desktop shortcut; the Settings >
Apps entry; `%LOCALAPPDATA%\SwingScribe` after asking, since it holds the
cache and the downloaded weights (about 2 GB, and the only part worth
asking about); and finally the folder itself, which a script can do by
handing the last step to a detached `cmd /c` that runs after it exits. It
says out loud that the sidecars beside the music are left alone.

`setup.cmd` registers the app under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SwingScribe`
(display name, icon, version, install location, estimated size and the
uninstall command), which is all Settings > Apps needs to list SwingScribe
with a working Uninstall button. Per-user, no administrator prompt, and
the same key is what a later `setup.cmd` from a newer zip updates.

**Updating** is: extract the new zip over nothing (a new folder), run its
`setup.cmd`, delete the old folder. The data directory is shared, so the
weights are not downloaded again and the cache survives.

### Prerequisites in the codebase

Smaller than the installer's list, because nothing is frozen:

1. **Per-user data directory.** `piano.checkpoint_path` honours an
   environment override the way audio-separator and torch already do, and
   the file picker's first folder falls back to the user's Music folder
   when no library is configured and the working directory is the
   launcher's own. `cache_dir` needs nothing: `SWINGSCRIBE_CACHE_DIR` is
   read today.
2. **Weight downloads reported through the job's progress channel.** All
   four sets download on first use; the piano one prints to a console the
   user is not watching. The first-run notice reports them, and gets one
   sentence naming the sidecar.
3. **An About text with the third-party notices** — the licence table
   below, and UVR attribution for audio-separator.
4. **No console-script stubs in the folder.** `python\Scripts\*.exe` are
   the per-install binaries Smart App Control refuses and nothing in the
   folder needs them; the build deletes them.
5. **Console visible and minimized**, the same rule as the shortcut: a
   refused DLL must fail out loud, and the console is where a startup
   failure shows when the browser does not open.

`multiprocessing.freeze_support` is not needed: the separation worker is
spawned by an ordinary `python.exe`. The config move is done.

### The build recipe

`packaging/build_portable.ps1`, in git, deterministic given the lock file:

1. Download the python-build-standalone CPython 3.11 `windows-x86_64`
   archive — the same build uv installs and the interpreter that runs this
   project today, so its reputation is already measured here — verify its
   checksum, and unpack it to `build\SwingScribe\python`.
2. Export the lock file as pinned requirements with the ml, gui and
   roformer groups (`uv export`), and install them into that interpreter
   directly (`uv pip install --python build\SwingScribe\python\python.exe`),
   no venv, so no trampoline. Same lock file as development, so the same
   file bytes as were tested. Install the SwingScribe wheel (`uv build`)
   the same way.
3. Delete `Scripts\*.exe`, `__pycache__`, tests and anything from the dev
   or batch groups.
4. Copy ffmpeg from a pinned URL with a checksum, an LGPL-configured build
   (the GPL builds most sites offer would bind the whole folder).
5. Write `SwingScribe.cmd`, `setup.cmd`, `uninstall.cmd`, `README.txt`,
   `swingscribe.yaml` (a copy of the packaged default the launcher passes
   with `--config`) and a `VERSION` file.
6. Zip it, named with the version from `pyproject.toml`.

A few minutes to run, and nothing in it iterates: there is no import graph
to discover, because everything is included.

### Testing the build

Two machines, both available:

- **This machine, Smart App Control on.** Launching the folder here is the
  per-file test: every executable in it is judged as it loads, and a
  refused one is a visible failure in the console. This is the check that
  no installer could pass and the reason for the shape. A pass today is not
  a pass forever — reputation flaps, as the venv launcher did on
  2026-09-12 — so versions stay pinned to files that passed, and a release
  is re-launched here before it is published.
- **The second laptop, as a stranger's machine.** It has its own Python
  with its own library versions, which is the isolation test: download
  the zip in a browser (so the files carry the mark of the web and
  SmartScreen's prompt appears the way it will for users), extract, run
  `setup.cmd`, launch from the icon, open a track, Beats, Separate with
  htdemucs, Transcribe, Export, Quit, then `uninstall.cmd` — and confirm
  that its own Python still imports its own packages unchanged, and that
  nothing but the sidecar is left behind.

The GitHub Actions Windows runner can build the zip and run the CLI smoke
test on it, but neither machine test can be delegated to it.

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
| BS-Roformer-SW (jarredou) | audio-separator's model zoo | **not stated** in the zoo's `models.json` and the model page is not publicly readable | **must be stated in the notices before release** |

This is a disclosure obligation, not a legal gate: the legal position of a
first-run download is the same as today's repo, where the user's own
audio-separator fetches the checkpoint and nothing is redistributed. What
changes is the audience. A developer cloning the repo chooses their
dependencies knowingly; a person double-clicking an installer never sees a
licence, so if the Roformer's terms turn out to be non-commercial a
transcriber selling transcriptions would break them unknowingly, under a
project whose own MIT licence implies otherwise. So: establish the terms,
state them in a third-party notices file and the About text, and if they
are non-commercial say so in the separator menu and leave htdemucs (MIT) as
the choice for commercial use. audio-separator itself is MIT and asks for
UVR attribution when its models are used.

### Mac

Later, when someone with a Mac asks (decision 4). The same shape applies —
a folder with a Python and a launcher script, no app bundle — with one
difference worth recording now: python.org's macOS build is signed and
notarized by the Python Software Foundation, so a folder built on it
carries a trusted interpreter the way this one does. Untested; pyproject
still excludes macOS.

### Signing

Not needed for this shape. The only executables are files that already
carry reputation. SmartScreen shows its "Run" prompt once for the `.cmd`
because it came from the internet; the install page shows what that looks
like. If a native window (follow-on, below) ever brings a real launcher
binary back, SignPath Foundation signs open-source Windows builds for free
and is the route to look at then.

### Release mechanics

`.github/workflows/release.yml` on a tag `v*`: build the zip on the Windows
runner, run the smoke test, attach it to a GitHub Release. Nothing binary
enters git; the release file limit is 2 GB and the zip is a third of that.
The version comes from `pyproject.toml` and the workflow refuses a tag that
does not match. The release is published only after the two machine tests
above, which are by hand.

### The installation page

A section of `README.md` written when the first zip exists, and
`README.txt` in the folder is its short form. It covers: download and
extract; `setup.cmd` and the icon; the first launch and the weight
download; the SmartScreen prompt, with a picture; updating; uninstalling,
and what it leaves behind; the package-manager route (`uv tool install`)
for people who already have Python tooling; and troubleshooting, where
Smart App Control belongs as a documented workaround for the day a fresh
library file loses reputation — toggle it off, run, toggle it on — not as
part of the install.

---

## Effort and cost

| Piece | Developer time | Money |
|---|---|---|
| 1. Quit button and the same-origin check | 2 hours (done) | none |
| 2. Desktop icon, launcher fallback, icon file | 1 hour (done) | none |
| 3a. Codebase prerequisites (five items above) | half a day | none |
| 3b. Build script and the first zip | 1 day | none |
| 3c. setup, uninstall, the Settings > Apps entry | half a day | none |
| 3d. The two machine tests | half a day | none |
| 3e. Release workflow and the installation page | half a day | none |
| Mac | later, on request | none if built on python.org's signed interpreter |
| Per release after that | a tag push, two launches by hand, a wait | |

Pieces 1 and 2 are done. Piece 3 is worth doing when there is a version to
give someone: the zip is a copy of the lock file's contents, so it does not
go stale the way a PyInstaller spec would, but each release still needs the
two launches by hand.

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
6. **No signing.** The budget is zero (2026-09-13), and the portable
   folder needs none: every executable in it already carries reputation.
7. **Test machines: this one with Smart App Control on, and the second
   laptop as a stranger's machine** (2026-09-13). No VM, no toggling
   needed for the build; the toggle is documented as a user workaround.
8. **Open: the BS-Roformer-SW licence**, stated in the notices before any
   release.
9. **A zip of a portable folder, not an installer** (2026-09-13). Smart App
   Control refuses any freshly built launcher or installer; a folder of
   files with reputation runs nothing new. See "Why a folder in a zip".
10. **Uninstall is a script plus a Settings > Apps entry** (2026-09-13):
    `setup.cmd` registers the per-user uninstall key, `uninstall.cmd`
    removes the icon, the entry, the data directory on request, and the
    folder. Sidecars beside the music are never touched.
