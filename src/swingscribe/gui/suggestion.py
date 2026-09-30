"""The ensemble and lead stem the stems suggest, for the menus (roadmap O2).

A thin adapter over `swingscribe.routing`: find the stem set the listener's
selection is served from, hand it to `routing.measure` and `routing.suggest`,
and turn the answer into JSON. The rule, its thresholds and every measurement
behind them live in routing.py and docs/routing.md (111 of 111 benchmark
spans on the Roformer stems; no horn span, no horn window of 15 s of melody
or more -- 200,966 of them -- and no horn-containing probe called trio);
nothing here decides who is playing, and nothing here SETS anything. The page
shows the suggestion beside the Ensemble menu only while the track's sidecar
has no ensemble of its own, and Apply is the listener's click.

What the adapter adds is one refusal and one memo.

- **A partial stem set gets no suggestion, and is not even read.** A
  whole-file directory may legitimately hold one stem copied across from
  another cache (CLAUDE.md), and `library.available_stems` lists it. But the
  bass and drums are what the routing's lead guard reads, and the other
  melodic stems are what the piano is judged against: with them absent, the
  piano "leads" every second by default, which is the horn-called-trio
  direction. `routing.suggest` refuses a partial set too since the floor
  sweep (2026-09-30); either guard alone holds, and this one also saves the
  read and says which stems are missing before any wav is opened.
- **The levels are memoised** by the stem files (path, size, mtime) and the
  span, because the page asks again after every span change and every reload:
  0.37-0.54 s for a 75-second span, 2.8 s for a nine-minute file
  (docs/routing.md). A new separation writes new files and misses the memo by
  itself.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from swingscribe import routing
from swingscribe.config import Config
from swingscribe.gui import library
from swingscribe.model import Document

# Enough for every span a session touches; one entry is a few floats.
MEMO_SIZE = 64
# Span bounds are rounded like every other span the GUI keys on
# (review.SPAN_PRECISION), so 60.0637 and 60.064 are one measurement.
SPAN_DECIMALS = 3

_memo: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
_memo_lock = threading.Lock()


def _finite(value: float) -> float | None:
    """JSON has no infinity, and Starlette refuses to encode one. The routing
    keeps its evidence finite since it refuses partial sets (a margin over no
    rival stem was +inf); this is the second guard, not the only one."""
    return float(value) if math.isfinite(value) else None


def _stem_signature(stems: dict[str, str]) -> tuple:
    signature = []
    for name, path in sorted(stems.items()):
        try:
            stat = Path(path).stat()
        except OSError:
            signature.append((name, path, None, None))
            continue
        signature.append((name, path, stat.st_size, stat.st_mtime_ns))
    return tuple(signature)


def _payload(model: str, span, hint: routing.Suggestion | None, **extra) -> dict[str, Any]:
    if hint is None:
        body = {"ensemble": None, "stem": None, "confidence": 0.0, "evidence": {}}
    else:
        body = {
            "ensemble": hint.ensemble,
            "stem": hint.stem,
            "confidence": round(hint.confidence, 3),
            "reason": hint.reason,
            "evidence": {k: _finite(v) for k, v in hint.evidence.items()},
        }
    return {"model": model, "span": list(span) if span else None, **body, **extra}


def suggestion(
    document: Document,
    config: Config,
    model: str,
    span: tuple[float, float] | None,
) -> dict[str, Any]:
    """The routing suggestion for this track, model and span, as JSON.

    `measured` says whether levels were read at all: False when the span has
    no stems yet or only part of a set, and then `reason` says which. With
    `measured` True, `ensemble` and `stem` are `routing.suggest`'s answer
    unchanged -- None when it is unsure, which the page shows as "no
    suggestion" with the reason.
    """
    from swingscribe.stages.separate import KNOWN_SOURCES

    if span is not None:
        span = (round(float(span[0]), SPAN_DECIMALS), round(float(span[1]), SPAN_DECIMALS))
    stems = library.available_stems(document, config, model, span)
    if not stems:
        return _payload(
            model,
            span,
            None,
            measured=False,
            reason="Separate this span first: the suggestion is read from its stems.",
        )
    # A model the separate stage does not know cannot be judged complete by
    # its own source list (`separate.missing_stems` answers "complete" for
    # it), so it must hold every stem the routing reads.
    required = KNOWN_SOURCES.get(model, routing.SEPARATED_STEMS)
    missing = [name for name in required if name not in stems]
    if missing:
        return _payload(
            model,
            span,
            None,
            measured=False,
            reason=(
                f"No suggestion: this separation is missing {', '.join(missing)}. The "
                "bass and drums are what tell a piano solo from a comp under a bass "
                "solo, so the suggestion needs the whole set."
            ),
        )
    key = (model, span, _stem_signature(stems))
    with _memo_lock:
        cached = _memo.get(key)
        if cached is not None:
            _memo.move_to_end(key)
            return cached
    levels = routing.measure(stems, span)
    result = _payload(
        model,
        span,
        routing.suggest(levels, model),
        measured=True,
        active_s=round(levels.active_s, 1),
    )
    with _memo_lock:
        _memo[key] = result
        while len(_memo) > MEMO_SIZE:
            _memo.popitem(last=False)
    return result


def clear_memo() -> None:
    """For tests: forget every measured span."""
    with _memo_lock:
        _memo.clear()
