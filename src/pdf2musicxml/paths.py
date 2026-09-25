"""Where the tool keeps its engines and their state.

One folder, OUTSIDE AppData, deliberately. A shell run from a packaged
(MSIX) app such as the Claude desktop app has its AppData writes redirected
into a private folder that the user's own shell never sees, so an engine
installed "in" %LOCALAPPDATA% from one shell is missing from the other.
%USERPROFILE%\\.pdf2musicxml is the same folder from both.
"""

import os
from pathlib import Path

AUDIVERIS_VERSION = "5.11.0"


def tool_home() -> Path:
    override = os.environ.get("PDF2MUSICXML_HOME")
    return Path(override) if override else Path.home() / ".pdf2musicxml"


def downloads_dir() -> Path:
    return tool_home() / "downloads"


def audiveris_dir() -> Path:
    """The extracted Audiveris application folder (app/ and runtime/ inside)."""
    return tool_home() / f"audiveris-{AUDIVERIS_VERSION}" / "Audiveris"


def audiveris_appdata() -> Path:
    """What Audiveris sees as %APPDATA%: its config (tessdata), data and logs."""
    return tool_home() / "appdata"


def tessdata_dir() -> Path:
    return audiveris_appdata() / "AudiverisLtd" / "audiveris" / "config" / "tessdata"
