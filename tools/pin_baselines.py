"""Measure the synthetic suite and pin the scores into baselines.json.

Baselines are sacred (CLAUDE.md): run this only when you intend to move them,
and say in the commit message what moved and why. It prints a before/after
diff so that message can be accurate.

    uv run python tools/pin_baselines.py            # show the diff only
    uv run python tools/pin_baselines.py --write    # and write it
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_synthetic import BASELINES_PATH, CASES, run_case  # noqa: E402


def main() -> int:
    write = "--write" in sys.argv
    existing = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    previous = existing.get("synthetic", {})
    measured: dict[str, dict[str, float]] = {}

    for name in sorted(CASES):
        with tempfile.TemporaryDirectory() as tmp:
            scores = run_case(Path(tmp), name)
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
        existing["synthetic"] = measured
        BASELINES_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"\nwrote {BASELINES_PATH}")
    else:
        print("\n(dry run — pass --write to pin these)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
