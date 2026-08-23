"""CLI argument handling — pure config folding, no audio needed."""

from swingscribe.cli import apply_overrides, build_parser
from swingscribe.config import Config


def parse(argv):
    return build_parser().parse_args(argv)


def test_region_from_start_and_end():
    args = parse(["ab", "x.mp3", "--start", "90", "--end", "210"])
    config = apply_overrides(Config(), args)
    assert config.transcribe.region == (90.0, 210.0)


def test_region_open_ended_when_end_omitted():
    args = parse(["ab", "x.mp3", "--start", "90"])
    config = apply_overrides(Config(), args)
    assert config.transcribe.region == (90.0, None)


def test_region_from_start_defaults_to_zero():
    args = parse(["ab", "x.mp3", "--end", "30"])
    config = apply_overrides(Config(), args)
    assert config.transcribe.region == (0.0, 30.0)


def test_no_region_flags_leaves_none():
    args = parse(["ab", "x.mp3"])
    config = apply_overrides(Config(), args)
    assert config.transcribe.region is None


def test_stem_override():
    args = parse(["audition", "x.mp3", "--stem", "guitar"])
    config = apply_overrides(Config(), args)
    assert config.transcribe.stem == "guitar"


def test_stem_defaults_to_other():
    args = parse(["audition", "x.mp3"])
    assert apply_overrides(Config(), args).transcribe.stem == "other"


def test_tempo_hint_override():
    args = parse(["click", "x.mp3", "--tempo-hint", "140"])
    assert apply_overrides(Config(), args).beats.tempo_hint == 140.0


def test_overrides_participate_in_cache_key():
    # a different region or stem must produce a different transcribe stage key
    base = apply_overrides(Config(), parse(["ab", "x.mp3"]))
    region = apply_overrides(Config(), parse(["ab", "x.mp3", "--start", "10", "--end", "20"]))
    stem = apply_overrides(Config(), parse(["ab", "x.mp3", "--stem", "piano"]))
    assert base.stage_config("transcribe") != region.stage_config("transcribe")
    assert base.stage_config("transcribe") != stem.stage_config("transcribe")


def test_region_does_not_affect_upstream_stages():
    # separation must NOT re-run when only the region changes — that is the
    # whole point of putting region on transcribe rather than ingest
    base = apply_overrides(Config(), parse(["ab", "x.mp3"]))
    region = apply_overrides(Config(), parse(["ab", "x.mp3", "--start", "10", "--end", "20"]))
    assert base.stage_config("ingest") == region.stage_config("ingest")
    assert base.stage_config("separate") == region.stage_config("separate")
    assert base.stage_config("beats") == region.stage_config("beats")


def test_audition_subcommand_parses():
    args = parse(["audition", "x.mp3", "--stem", "piano", "--start", "5", "-o", "out.wav"])
    assert args.command == "audition"
    assert args.out == "out.wav"
