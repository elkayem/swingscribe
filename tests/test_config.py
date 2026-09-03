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
        "span": None,
        "span_margin_s": 3.0,
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


def test_the_default_separation_model_is_the_measured_best():
    """Not a preference — a measurement, and the listener's stated condition:
    the Roformer became the default on 2026-09-02 when the whole sheet re-ran
    at WJazzD note F1 0.790 -> 0.858 paired over 61 solos, with every horn in
    `other` and every pianist in `piano` (docs/separation-research.md). It is
    ~9x htdemucs' CPU time, made livable by span-scoped separation; htdemucs
    stays in the menu for when speed matters."""
    assert Config().separate.model == "bsroformer_sw"


def test_every_offered_model_is_selectable_and_the_default_is_offered():
    """The audition menu must contain the default, or the GUI opens on a model
    the config does not name."""
    config = Config()
    assert config.separate.model in config.gui.models
    assert config.gui.models[0] == config.separate.model
