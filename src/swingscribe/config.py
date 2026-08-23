"""Configuration: one object threaded through the pipeline (plan §2).

Loaded from config/default.yaml (or a user-supplied YAML); individual values
can be overridden via SWINGSCRIBE_* environment variables, e.g.
SWINGSCRIBE_TRANSCRIBE__ENSEMBLE=solo-piano.

Each stage's section feeds the cache key via Config.stage_config(), so config
values must stay JSON-serializable.
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root default; fine for development checkouts, which is all M0 supports.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


class IngestConfig(BaseModel):
    sample_rate: int = 44100


class SeparateConfig(BaseModel):
    model: str = "htdemucs_ft"


class BeatsConfig(BaseModel):
    dbn: bool = False
    use_drum_stem: bool = True


class TranscribeConfig(BaseModel):
    ensemble: Literal["horn-led", "trio", "solo-piano"] = "horn-led"


class SwingConfig(BaseModel):
    window_beats: int = 16


class QuantizeConfig(BaseModel):
    resolution: int = 16


class NotateConfig(BaseModel):
    transposition: Literal["C", "Eb", "Bb"] = "C"


class ExportConfig(BaseModel):
    formats: list[str] = ["musicxml", "midi", "json"]


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SWINGSCRIBE_", env_nested_delimiter="__")

    cache_dir: Path = Path(".swingscribe-cache")

    ingest: IngestConfig = IngestConfig()
    separate: SeparateConfig = SeparateConfig()
    beats: BeatsConfig = BeatsConfig()
    transcribe: TranscribeConfig = TranscribeConfig()
    swing: SwingConfig = SwingConfig()
    quantize: QuantizeConfig = QuantizeConfig()
    notate: NotateConfig = NotateConfig()
    export: ExportConfig = ExportConfig()

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "Config":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**data)

    def stage_config(self, stage_name: str) -> dict[str, Any]:
        """The config section for one stage, as the plain dict fed to its cache key."""
        section = getattr(self, stage_name, None)
        if not isinstance(section, BaseModel):
            raise KeyError(f"unknown stage: {stage_name!r}")
        return section.model_dump(mode="json")
