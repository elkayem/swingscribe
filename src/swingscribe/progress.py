"""Per-stage progress reporting (plan §13; docs/gui-design.md requirement 4).

Separation is 6-13 minutes on CPU. A GUI cannot present that as a frozen tab,
so stages need a way to say how far along they are.

This is a *side channel*, deliberately. The stage contract is
(Document, Config) -> Document and stays that way: threading a progress
argument through every stage would change that signature for the sake of one
slow stage. Instead a stage calls report(), which forwards to whatever sink
the caller installed — and to nothing at all when nobody is listening, which
is the CLI's normal case.

The sink lives in a ContextVar, so concurrent jobs in different threads each
see their own. Note that ContextVars do not cross a thread boundary on their
own: install the sink *inside* the worker thread that runs the pipeline.

    with progress.sink(lambda ev: print(ev.fraction)):
        pipeline.run(path, config)
"""

import contextlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

__all__ = ["ProgressEvent", "ProgressSink", "report", "sink"]


@dataclass(frozen=True)
class ProgressEvent:
    """One progress datum from a stage.

    `fraction` is 0.0-1.0 within *this stage*, or None when the stage can only
    say "I have started" (cheap stages, or work with no measurable extent).
    `cached` marks a stage that was served from disk and never actually ran.
    """

    stage: str
    fraction: float | None = None
    message: str = ""
    cached: bool = False


ProgressSink = Callable[[ProgressEvent], None]

_sink: ContextVar[ProgressSink | None] = ContextVar("swingscribe_progress_sink", default=None)


def report(
    stage: str, fraction: float | None = None, message: str = "", *, cached: bool = False
) -> None:
    """Emit one progress event to the installed sink, if any.

    Never raises: a broken reporter must not take the pipeline down with it,
    and callers should be able to sprinkle these without defensive wrapping.
    """
    current = _sink.get()
    if current is None:
        return
    if fraction is not None:
        fraction = min(1.0, max(0.0, float(fraction)))
    with contextlib.suppress(Exception):
        current(ProgressEvent(stage=stage, fraction=fraction, message=message, cached=cached))


@contextmanager
def sink(callback: ProgressSink | None) -> Iterator[None]:
    """Install `callback` as the progress sink for the duration of the block."""
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)
