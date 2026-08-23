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
    device: str = "auto"  # auto | cuda | cpu


class BeatsConfig(BaseModel):
    dbn: bool = False  # never True — we skip madmom entirely (plan §2)
    use_drum_stem: bool = True
    checkpoint: str = "final0"
    device: str = "auto"  # auto | cuda | cpu
    # Drum stem must carry at least this fraction of the mix's RMS energy,
    # else fall back to the full mix. Relative, not absolute: a brushes
    # ballad leaves a technically-nonsilent but useless drum stem.
    min_drum_mix_ratio: float = 0.05
    # Known tempo in BPM; corrects half/double-octave tracking errors.
    tempo_hint: float | None = None


class TranscribeConfig(BaseModel):
    ensemble: Literal["horn-led", "trio", "solo-piano"] = "horn-led"
    # Which separated stem carries the solo. htdemucs_ft gives
    # drums/bass/other/vocals; htdemucs_6s adds guitar/piano.
    stem: str = "other"
    # Analyse only [start, end] seconds of the track; a null end means "to the
    # end of the track". Lives HERE and not on ingest deliberately: separation
    # and beat tracking stay whole-file (Demucs degrades on short crops, and
    # beat tracking wants context), so switching to a different solo in the
    # same tune re-runs only this stage. Note onsets are still reported in
    # whole-track time.
    region: tuple[float, float | None] | None = None
    fmin_hz: float = 55.0  # A1 — bari sax bottom; constrains CREPE against octave errors
    fmax_hz: float = 1600.0  # ~G6 — above alto altissimo
    crepe_model: str = "full"  # full | tiny (tiny is ~10x faster on CPU, less accurate)
    device: str = "auto"  # auto | cuda | cpu
    # CREPE periodicity gate. torchcrepe's docs suggest ~0.21 for clean solo
    # audio; we sit at 0.5 because the "other" stem's piano/bass bleed is
    # itself pitched and keeps periodicity moderately high during rests —
    # biasing up trades slightly clipped note tails for fewer phantom notes.
    voicing_threshold: float = 0.5
    # Second gate: frame RMS must be within this many dB of the stem's loud
    # reference (95th-percentile frame RMS). Periodicity alone cannot reject
    # QUIET pitched bleed between phrases; energy can.
    silence_floor_db: float = -40.0
    min_note_ms: float = 60.0  # drop specks shorter than a fast bebop 16th
    pitch_persist_ms: float = 60.0  # a new pitch must hold this long to split a note
    silence_gap_ms: float = 40.0  # unvoiced dropouts shorter than this bridge a phrase
    median_filter_ms: float = 50.0  # f0 smoothing kernel — flattens vibrato wobble


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
