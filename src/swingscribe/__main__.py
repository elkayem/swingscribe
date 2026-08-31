"""Entry point for `python -m swingscribe`, which is the launcher that works here.

The console script `swingscribe.exe` is generated fresh by uv/pip at install
time, so it is a unique unsigned binary that Windows Smart App Control has
never seen and will not run: `uv run swingscribe` dies with
`os error 4551 — An Application Control policy has blocked this file`, and no
version pin can fix it because the stub is rebuilt on every sync (CLAUDE.md,
"This machine"). A module entry point is plain Python read by an interpreter
that is already trusted, so it sidesteps the stub entirely.
"""

from swingscribe.cli import main

raise SystemExit(main())
