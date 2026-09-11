"""Cache layer: hit, miss, invalidation, and chained-key behavior (plan §3)."""

import pytest

from swingscribe import cache as cache_module
from swingscribe.cache import StageCache, canonical_json, root_key, stage_key


def test_miss_returns_none(tmp_path):
    cache = StageCache(tmp_path)
    key = root_key(b"some audio bytes")
    assert cache.get(key) is None
    assert not cache.has(key)


def test_hit_roundtrip(tmp_path):
    cache = StageCache(tmp_path)
    key = stage_key(root_key(b"some audio bytes"), "separate", {"model": "htdemucs_ft"})
    cache.put(key, b"stem payload")
    assert cache.has(key)
    assert cache.get(key) == b"stem payload"


def test_config_change_invalidates(tmp_path):
    cache = StageCache(tmp_path)
    rk = root_key(b"some audio bytes")
    old_key = stage_key(rk, "separate", {"model": "htdemucs_ft"})
    new_key = stage_key(rk, "separate", {"model": "bs_roformer"})
    cache.put(old_key, b"old stems")

    assert old_key != new_key
    assert cache.get(new_key) is None  # changed config is a miss, not a stale hit
    assert cache.get(old_key) == b"old stems"  # the old entry is untouched


def test_upstream_config_change_invalidates_downstream_key():
    # The staleness hole chaining exists to close (plan §3): with flat keys,
    # transcribe's key would not see a separation config change.
    rk = root_key(b"some audio bytes")
    sep_a = stage_key(rk, "separate", {"model": "htdemucs_ft"})
    sep_b = stage_key(rk, "separate", {"model": "bs_roformer"})
    transcribe_config = {"ensemble": "horn-led"}
    assert stage_key(sep_a, "transcribe", transcribe_config) != stage_key(
        sep_b, "transcribe", transcribe_config
    )


def test_different_audio_different_keys():
    assert root_key(b"take one") != root_key(b"take two")


def test_stage_name_distinguishes_keys():
    rk = root_key(b"some audio bytes")
    assert stage_key(rk, "separate", {}) != stage_key(rk, "beats", {})


def test_key_ignores_dict_order():
    upstream = "ab" * 32
    a = stage_key(upstream, "swing", {"window_beats": 16, "min_confidence": 0.5})
    b = stage_key(upstream, "swing", {"min_confidence": 0.5, "window_beats": 16})
    assert a == b


def test_canonical_json_is_order_insensitive():
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_json_roundtrip(tmp_path):
    cache = StageCache(tmp_path)
    key = root_key(b"x")
    cache.put_json(key, {"beats": [0.5, 1.0], "beats_per_bar": 4})
    assert cache.get_json(key) == {"beats": [0.5, 1.0], "beats_per_bar": 4}


def test_overwrite_is_idempotent(tmp_path):
    cache = StageCache(tmp_path)
    key = root_key(b"x")
    cache.put(key, b"first")
    cache.put(key, b"second")
    assert cache.get(key) == b"second"


def test_rejects_malformed_key(tmp_path):
    cache = StageCache(tmp_path)
    with pytest.raises(ValueError):
        cache.get("not-a-sha256-key")
    with pytest.raises(ValueError):
        cache.put("../escape", b"payload")


# -- a locked entry (OneDrive holds a file it is syncing) --------------------

KEY = "a" * 64


def _locked_replace(monkeypatch, failures: int):
    """os.replace that answers WinError 5 `failures` times, then works."""
    import os

    real = os.replace
    seen = []

    def replace(src, dst):
        seen.append(dst)
        if len(seen) <= failures:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(cache_module.os, "replace", replace)
    monkeypatch.setattr(cache_module, "RETRY_DELAY_S", 0.0)
    return seen


def test_a_briefly_locked_entry_is_written_on_retry(tmp_path, monkeypatch):
    cache = StageCache(tmp_path)
    cache.put(KEY, b"old")
    seen = _locked_replace(monkeypatch, failures=2)
    cache.put(KEY, b"new")
    assert cache.get(KEY) == b"new"
    assert len(seen) == 3
    assert not list(tmp_path.rglob("*.tmp"))


def test_an_entry_locked_for_good_is_left_as_it_was_and_reported(tmp_path, monkeypatch):
    """The caller's Document is right either way; the pipeline re-checks what
    an entry points at rather than trusting the write, so a stale entry costs
    a re-run, never a wrong answer. Raising killed an eval run over it."""
    cache = StageCache(tmp_path)
    cache.put(KEY, b"old")
    _locked_replace(monkeypatch, failures=cache_module.REPLACE_ATTEMPTS)
    with pytest.warns(RuntimeWarning, match="locked"):
        cache.put(KEY, b"new")
    assert cache.get(KEY) == b"old"
    assert not list(tmp_path.rglob("*.tmp"))
