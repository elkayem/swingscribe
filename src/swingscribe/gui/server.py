"""Launching the GUI: uvicorn on localhost, and a browser pointed at it."""

import os
import sys
import threading
import webbrowser
from urllib.parse import urlencode

from swingscribe.config import Config
from swingscribe.gui.app import create_app


def serve(config: Config) -> None:
    import uvicorn

    url = f"http://{config.gui.host}:{config.gui.port}/"
    if config.gui.open_track:
        url += "?" + urlencode({"open": config.gui.open_track})
    if config.gui.open_browser:
        # Fired on a timer rather than inline: uvicorn needs a moment to bind,
        # and a browser that arrives first shows a connection error.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # The server is built by hand rather than through uvicorn.run so the app
    # can be handed a way to stop it: the Quit button sets should_exit, and
    # uvicorn finishes the request in flight and returns.
    server: list = []

    def stop() -> None:
        if server:
            server[0].should_exit = True

    app = create_app(config, on_quit=stop)
    server.append(
        uvicorn.Server(
            uvicorn.Config(
                app,
                host=config.gui.host,
                port=config.gui.port,
                log_level="warning",  # the access log drowns out progress on a 10-minute job
            )
        )
    )

    # ASCII only: this machine's console code page is cp1252, and a stray
    # arrow here raises UnicodeEncodeError — which, being a ValueError, the CLI
    # error handler then reports as if the GUI itself had failed to start.
    print(f"SwingScribe GUI: {url}")
    print("Load a track, select the solo, audition the isolated stem.")
    print("Quit from the button in the page, or Ctrl-C here.")
    server[0].run()

    # A cancelled transcription is a CREPE pass that cannot be interrupted
    # from another thread, and its worker thread is not a daemon: the
    # interpreter would wait for it at exit, leaving the console open for
    # minutes after Quit with nothing on it. The stage's cache writes are
    # atomic (a temp file and a rename), so ending the process now costs at
    # most a temp file; the listener's judgements are in the sidecar already.
    still_running = [job for job in app.state.runner.all() if job["state"] in ("queued", "running")]
    if still_running:
        print(f"SwingScribe GUI: stopped with {len(still_running)} job(s) abandoned")
        sys.stdout.flush()
        os._exit(0)
    print("SwingScribe GUI: stopped")
