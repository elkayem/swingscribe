"""Launching the GUI: uvicorn on localhost, and a browser pointed at it."""

import threading
import webbrowser

from swingscribe.config import Config
from swingscribe.gui.app import create_app


def serve(config: Config) -> None:
    import uvicorn

    url = f"http://{config.gui.host}:{config.gui.port}/"
    if config.gui.open_browser:
        # Fired on a timer rather than inline: uvicorn needs a moment to bind,
        # and a browser that arrives first shows a connection error.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # ASCII only: this machine's console code page is cp1252, and a stray
    # arrow here raises UnicodeEncodeError — which, being a ValueError, the CLI
    # error handler then reports as if the GUI itself had failed to start.
    print(f"SwingScribe GUI: {url}")
    print("Load a track, select the solo, audition the isolated stem. Ctrl-C to stop.")
    uvicorn.run(
        create_app(config),
        host=config.gui.host,
        port=config.gui.port,
        log_level="warning",  # the access log drowns out progress on a 10-minute job
    )
