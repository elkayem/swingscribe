"""Keep a click in the console window from freezing a running job.

The classic Windows console has QuickEdit on by default: a mouse click in the
window starts a text selection, and while a selection is open every process
writing to that console BLOCKS on its next write. The GUI server, the
separator's progress bar and every stage's log line write there, so on
2026-09-29 a BS-Roformer separation sat at chunk 10 of 45 for twelve minutes
with the CPU and the GPU idle, and went on the moment a resize of the window
ended the selection. Nothing in the app, its log or the job's state could
say why; the only sign was the selection anchor, a white cell in the
middle of old output.

So the launcher switches QuickEdit off for the life of the process and puts
the console's mode back on the way out. Text can still be copied from the
window on purpose: right-click, Mark. A process whose stdin is not a console
(a pipe, a detached run) and every other platform are left alone.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from collections.abc import Iterator

STD_INPUT_HANDLE = -10
ENABLE_QUICK_EDIT_MODE = 0x0040
# SetConsoleMode ignores the QuickEdit bit unless this flag comes with it.
ENABLE_EXTENDED_FLAGS = 0x0080


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    return kernel32


@contextlib.contextmanager
def quick_edit_disabled(kernel32=None) -> Iterator[None]:
    """Switch QuickEdit off on this process's console until the block exits.

    The mode belongs to the console, not the process, so the separator's
    worker and anything else sharing the window are covered too. A server
    that leaves through `os._exit` (a CREPE pass still running at Quit) skips
    the restore; the icon's console closes with it anyway.
    """
    if kernel32 is None:
        if sys.platform != "win32":
            yield
            return
        kernel32 = _kernel32()
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    mode = ctypes.c_ulong()
    if not kernel32.GetConsoleMode(handle, ctypes.pointer(mode)) or not (
        mode.value & ENABLE_QUICK_EDIT_MODE
    ):
        yield
        return
    original = mode.value
    kernel32.SetConsoleMode(handle, (original | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE)
    try:
        yield
    finally:
        kernel32.SetConsoleMode(handle, original | ENABLE_EXTENDED_FLAGS)
