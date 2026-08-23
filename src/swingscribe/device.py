"""Torch device resolution, shared by stages (which never import each other)."""


def resolve_device(configured: str, cuda_available: bool) -> str:
    """'auto' picks cuda when available; anything else is passed through.

    Silent CPU fallback turns a 20-second job into 15 minutes (plan §8), so
    stages log the resolved device rather than hiding it.
    """
    if configured != "auto":
        return configured
    return "cuda" if cuda_available else "cpu"
