"""Cache layer: hit, miss, invalidation, and chained-key behavior (plan §3)."""

import pytest

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
