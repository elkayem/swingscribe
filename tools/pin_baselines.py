"""Measure the synthetic suite and pin the scores into baselines.json.

Baselines are sacred (CLAUDE.md): run this only when you intend to move them,
and say in the commit message what moved and why. It prints a before/after
diff so that message can be accurate.

    uv run python tools/pin_baselines.py            # show the diff only
    uv run python tools/pin_baselines.py --write    # and write it

The soundfont cases are a *separate* section, pinned separately, because they
are expected to score lower than the additive ones (open-issue #4 — that is
the point of them). Averaging the two families into one set of numbers would
hide a regression in either.

    uv run python tools/pin_baselines.py --soundfont --write
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_synthetic import (  # noqa: E402
    BASELINES_PATH,
    CASES,
    SOUNDFONT_CASES,
    run_case,
    run_soundfont_case,
)


def main() -> int:
    write = "--write" in sys.argv
    soundfont = "--soundfont" in sys.argv

    section = "synthetic_soundfont" if soundfont else "synthetic"
    cases = SOUNDFONT_CASES if soundfont else CASES
    runner = run_soundfont_case if soundfont else run_case

    existing = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    previous = existing.get(section, {})
    measured: dict[str, dict[str, float]] = {}

    print(f"section: {section}")
    for name in sorted(cases):
        with tempfile.TemporaryDirectory() as tmp:
            scores = runner(Path(tmp), name)
        measured[name] = {k: round(v, 4) for k, v in scores.items()}
        print(f"\n=== {name} ===")
        for metric in sorted(measured[name]):
            new = measured[name][metric]
            old = previous.get(name, {}).get(metric)
            if old is None:
                print(f"  {metric:24s} {new:8.3f}   (new)")
            elif abs(new - old) < 1e-6:
                print(f"  {metric:24s} {new:8.3f}")
            else:
                arrow = "up" if new > old else "DOWN"
                print(f"  {metric:24s} {new:8.3f}   was {old:.3f}  [{arrow}]")

    if write:
        existing[section] = measured
        BASELINES_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"\nwrote {section} to {BASELINES_PATH}")
    else:
        print("\n(dry run — pass --write to pin these)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
