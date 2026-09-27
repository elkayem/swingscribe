"""numba, or a pass-through stand-in when Application Control refuses it.

librosa imports numba, and two things this project runs import librosa: the
piano model (through torchlibrosa) and the default separator (audio-separator
loads librosa to prepare the mix). numba compiles to native code through
llvmlite's DLL, and Smart App Control's verdict on that DLL CHANGES over time
on the dev machine: blocked 2026-08-30, allowed the next morning, blocked
again by 2026-09-01 (CLAUDE.md: test, never remember). A refusal arrives as
OSError 4551, not ImportError, and without this module it failed the whole
job with the raw error.

librosa only ever uses numba to OPTIMIZE, so the stand-in's decorators hand
back the function they were given: the same functions, un-jitted, slower.
The real numba always wins when it imports.

Never use this from a process with no window: there a refused DLL HANGS
instead of raising (CLAUDE.md), and trying the real numba first is exactly
what hangs. Detached scripts install the stand-in unconditionally.
"""

from __future__ import annotations

import sys
import types

# A refused DLL raises OSError (WinError 4551), a missing package ImportError.
BLOCKED_IMPORT = (ImportError, OSError)

PASSTHROUGH_VERSION = "0.0.0-swingscribe-passthrough"


def _passthrough(*args, **kwargs):
    """`@jit` and `@jit(nopython=True)` alike: return the function unchanged."""
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]

    def wrap(function):
        return function

    return wrap


def install_passthrough() -> types.ModuleType:
    """Put the stand-in in sys.modules under the name ``numba``."""
    stub = types.ModuleType("numba")
    stub.jit = _passthrough
    stub.njit = _passthrough
    stub.vectorize = _passthrough
    stub.guvectorize = _passthrough
    stub.stencil = _passthrough
    stub.prange = range
    stub.__version__ = PASSTHROUGH_VERSION
    sys.modules["numba"] = stub
    return stub


def ensure_numba() -> bool:
    """Make ``import numba`` succeed. True when it is the real numba, False
    when Application Control (or a missing install) left the stand-in."""
    current = sys.modules.get("numba")
    if getattr(current, "__version__", None) == PASSTHROUGH_VERSION:
        return False
    try:
        import numba  # noqa: F401
    except BLOCKED_IMPORT:
        install_passthrough()
        return False
    return True
