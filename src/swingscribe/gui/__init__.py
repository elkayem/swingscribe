"""The local selection/audition GUI (plan §13, screens 1-3 of docs/gui-design.md).

Import lazily. This package needs the `gui` dependency group (fastapi,
uvicorn), which plain `uv sync` — and therefore CI — does not install, so
nothing outside it may import it at module scope.
"""
