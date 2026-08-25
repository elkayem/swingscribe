"""Config loading from config/default.yaml (plan §2)."""

import pytest

from swingscribe.config import Config


def test_default_yaml_loads():
    config = Config.from_yaml()
    assert config.separate.model == Config().separate.model
    assert config.beats.dbn is False  # no madmom/DBN, ever (plan §2)
    assert config.transcribe.ensemble == "horn-led"
    assert config.swing.window_beats == 16


def test_stage_config_is_a_plain_dict():
    config = Config.from_yaml()
    assert config.stage_config("separate") == {
        "model": Config().separate.model,
        "device": "auto",
    }


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
    # untouched sections keep their defaults
    assert config.separate.model == Config().separate.model


def test_the_default_separation_model_is_the_fast_one():
    """Not a preference — a measurement. `htdemucs_ft` is a bag of four models
    and takes 4x as long; over the nine benchmark solos that used it, plain
    `htdemucs` scored mean note F1 0.759 against its 0.752, better on eight of
    nine. Paying 4x for that is not a trade anyone would choose knowingly."""
    assert Config().separate.model == "htdemucs"


def test_every_offered_model_is_selectable_and_the_default_is_offered():
    """The audition menu must contain the default, or the GUI opens on a model
    the config does not name."""
    config = Config()
    assert config.separate.model in config.gui.models
    assert config.gui.models[0] == config.separate.model
