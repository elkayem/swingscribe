"""scripts/locate_scores.py: where it looks for the score a recording pairs with."""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import locate_scores  # noqa: E402


def test_a_score_beside_the_audio_is_found(tmp_path):
    audio = tmp_path / "Confirmation.m4a"
    audio.write_bytes(b"")
    score = tmp_path / "Confirmation.musicxml"
    score.write_text("<score-partwise/>")
    assert locate_scores.score_beside(audio) == score


def test_a_pdf_pages_score_is_found_in_its_musicxml_folder(tmp_path):
    """pdf2musicxml writes the pages' readings to musicxml/; the listener keeps
    the recordings one level up, beside the PDFs."""
    audio = tmp_path / "Cotton Tail - Ben Webster Solo.mp3"
    audio.write_bytes(b"")
    (tmp_path / "musicxml").mkdir()
    score = tmp_path / "musicxml" / "Cotton Tail - Ben Webster Solo.musicxml"
    score.write_text("<score-partwise/>")
    assert locate_scores.score_beside(audio) == score


def test_the_score_beside_wins_over_the_musicxml_folder(tmp_path):
    audio = tmp_path / "Tune.m4a"
    audio.write_bytes(b"")
    beside = tmp_path / "Tune.musicxml"
    beside.write_text("<score-partwise/>")
    (tmp_path / "musicxml").mkdir()
    (tmp_path / "musicxml" / "Tune.musicxml").write_text("<score-partwise/>")
    assert locate_scores.score_beside(audio) == beside


def test_no_score_anywhere_is_none(tmp_path):
    audio = tmp_path / "Lonely.m4a"
    audio.write_bytes(b"")
    assert locate_scores.score_beside(audio) is None
