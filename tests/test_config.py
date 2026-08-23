"""Config loading from config/default.yaml (plan §2)."""

import pytest

from swingscribe.config import Config


def test_default_yaml_loads():
    config = Config.from_yaml()
    assert config.separate.model == "htdemucs_ft"
    assert config.beats.dbn is False  # no madmom/DBN, ever (plan §2)
    assert config.transcribe.ensemble == "horn-led"
    assert config.swing.window_beats == 16


def test_stage_config_is_a_plain_dict():
    config = Config.from_yaml()
    assert config.stage_config("separate") == {"model": "htdemucs_ft", "device": "auto"}


def test_stage_config_rejects_unknown_stage():
    config = Config()
    with pytest.raises(KeyError):
        config.stage_config("nonexistent")
    with pytest.raises(KeyError):
        config.stage_config("cache_dir")  # an attribute, but not a stage


def test_yaml_overrides_defaults(tmp_path):
    path = tmp_path / "override.yaml"
    path.write_text("transcribe:\n  ensemble: solo-piano\n", encoding="utf-8")
    config = Config.from_yaml(path)
    assert config.transcribe.ensemble == "solo-piano"
    assert config.separate.model == "htdemucs_ft"  # untouched sections keep defaults
