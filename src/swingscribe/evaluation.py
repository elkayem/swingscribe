"""The benchmark's bookkeeping: whether a change is real, which tracks may be
looked at, and how far a reference page can be trusted (docs/roadmap.md,
E1-E3).

Nothing here aligns or scores notes -- that is `benchmark.py` and mir_eval.
These are the three questions the harness asks ABOUT its scores:

- **Is a change distinguishable from noise?** `paired_change` compares the
  same tracks before and after: the mean delta, a bootstrap interval that
  resamples RECORDINGS (the three So What solos are one recording, not three
  draws), and an exact sign test over recordings. The harness shipped rules on
  differences like +0.007 with 7 of 12 pages up, which a sign test puts at
  p = 0.77.
- **May this track be looked at?** `Split`: everything in the benchmark on
  2026-09-29 is DEV, because it has been looked at. A track added since is
  dev or TEST by a salted hash of its tune title, so every version of a tune
  -- and every soloist on one recording -- falls on one side. Test tracks are
  scored only at a release (`run_eval --test`), and the figure prior is never
  counted from a test page.
- **How good is the reference?** `page_tier`: a PDF page read by OMR is not a
  hand score. Silver is a vector page whose printed noteheads were counted and
  read, whose bars fill their signatures; bronze is the rest, scans included.
  The gates were set from the pages' reading quality before any page was
  scored, and moving them to improve a score would defeat them.

Standard library at import: `scripts/figure_prior.py` imports this and runs
anywhere the corpus does. numpy is imported inside `paired_change` only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

# ── is a change real ─────────────────────────────────────────────────────────


def sign_test(up: int, down: int) -> float:
    """Exact two-sided sign test: the chance of a split at least this uneven
    between `up` and `down` if each were a coin flip. Level pairs are not
    counted -- they are neither."""
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class PairedChange:
    """One measure's change over the same tracks, before -> after."""

    n: int  # tracks paired
    recordings: int  # the independent units the interval resamples
    mean: float  # mean per-track delta
    low: float  # interval on the mean delta
    high: float
    up: int  # recordings whose mean delta rose past the tolerance
    down: int
    level: int
    p: float  # sign test over recordings

    @property
    def decided(self) -> bool:
        """The interval excludes zero."""
        return self.low > 0.0 or self.high < 0.0


def paired_change(
    before: list[float],
    after: list[float],
    recordings: list[str] | None = None,
    *,
    tolerance: float = 0.0,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> PairedChange:
    """The change from `before` to `after`, paired by position.

    `recordings` names the recording each pair belongs to; pairs that share
    one are resampled together and counted once by the sign test. None makes
    every pair its own recording. The mean inside a resample is over TRACKS
    (a recording holding three solos weighs three), so it is the same mean the
    scorecard prints. The seed is fixed: the same two cards always print the
    same interval.
    """
    import numpy as np

    if len(before) != len(after):
        raise ValueError(f"{len(before)} values before and {len(after)} after")
    if not before:
        raise ValueError("nothing to compare")
    deltas = np.asarray(after, dtype=float) - np.asarray(before, dtype=float)
    labels = list(recordings) if recordings is not None else [str(i) for i in range(len(deltas))]
    if len(labels) != len(deltas):
        raise ValueError(f"{len(labels)} recording labels for {len(deltas)} pairs")
    groups: dict[str, list[int]] = {}
    for i, label in enumerate(labels):
        groups.setdefault(label, []).append(i)
    sums = np.array([deltas[idx].sum() for idx in groups.values()])
    counts = np.array([len(idx) for idx in groups.values()], dtype=float)

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(groups), size=(resamples, len(groups)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])

    per_recording = sums / counts
    up = int((per_recording > tolerance).sum())
    down = int((per_recording < -tolerance).sum())
    return PairedChange(
        n=len(deltas),
        recordings=len(groups),
        mean=float(deltas.mean()),
        low=float(low),
        high=float(high),
        up=up,
        down=down,
        level=len(groups) - up - down,
        p=sign_test(up, down),
    )


# ── may this track be looked at ──────────────────────────────────────────────


def normalize_title(text: str) -> str:
    """A tune title as a split key: lower case, letters and digits only, so
    "Star Dust", "Stardust" and "STAR-DUST" are one tune."""
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("'", "").replace("’", ""))


@dataclass(frozen=True)
class Split:
    """Which tracks are held out. `dev` is every group already in the
    benchmark when the split was frozen; everything else is test when its
    salted hash falls under `test_share`."""

    salt: str
    test_share: float
    dev: frozenset[str]

    def is_test(self, group: str) -> bool:
        key = normalize_title(group)
        if not key or key in self.dev:
            return False
        digest = hashlib.sha256(f"{self.salt}\x00{key}".encode()).hexdigest()
        return int(digest[:8], 16) / 2**32 < self.test_share


def load_split(path: str | Path) -> Split:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Split(
        salt=data["salt"],
        test_share=float(data["test_share"]),
        dev=frozenset(normalize_title(g) for g in data["dev"]),
    )


def page_group(manifest_entry: dict | None, file_stem: str) -> str:
    """The split group of a PDF transcription: the title pdf2musicxml read
    off the page, else the file's own name. One definition, because the
    figure prior's build and the harness must agree on which pages are test."""
    title = (manifest_entry or {}).get("title") or ""
    return title if normalize_title(title) else file_stem


# ── how good is the reference ────────────────────────────────────────────────

# A silver page: at most this share of the printed noteheads went unread...
SILVER_MAX_UNREAD = 0.05
# ...at most this share of what was read is not printed on the page...
SILVER_MAX_UNPRINTED = 0.05
# ...and at least this share of its bars fill their time signature. On the
# 222 vector pages of 2026-09-29 these admit 170.
SILVER_MIN_FILLED = 0.90


def page_tier(manifest_entry: dict | None, filled_share: float | None) -> str:
    """The tier of an OMR-read page, "silver" or "bronze" (docs/roadmap.md, E3).

    A scan prints no note count, so nothing checked its reading and it is
    bronze whatever its bars do. `filled_share` is the share of the page's
    bars whose notes and rests fill the signature (figure_prior's reader).
    """
    entry = manifest_entry or {}
    printed = entry.get("printed_noteheads") or 0
    if not printed or filled_share is None:
        return "bronze"
    unread = (entry.get("unread_printed") or 0) / printed
    unprinted = (entry.get("unprinted_read") or 0) / printed
    if (
        unread <= SILVER_MAX_UNREAD
        and unprinted <= SILVER_MAX_UNPRINTED
        and filled_share >= SILVER_MIN_FILLED
    ):
        return "silver"
    return "bronze"
