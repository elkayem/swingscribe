"""scripts/wjazz_batch.py finds every solo through its sidecar: a linked take
whose copy was deleted is processed in place, never missed or given a second
sidecar (scripts/dedupe_audio.py)."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

wjazz_batch = pytest.importorskip("wjazz_batch", reason="the batch group is not installed")


def test_a_linked_take_is_a_solo_of_the_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(wjazz_batch, "BENCH_DIR", tmp_path)
    kept = tmp_path / "Curtis_Fuller_Blue_Train_solo_1.m4a"
    kept.write_bytes(b"one side")
    (tmp_path / "Lee_Morgan_Blue_Train_solo_2.m4a.swingscribe.json").write_text(
        json.dumps({"audio": kept.name, "region": [3, 4]})
    )
    loose = tmp_path / "Wayne_Shorter_Dolores_solo_3.m4a"
    loose.write_bytes(b"no sidecar yet")
    takes = wjazz_batch.all_takes()
    assert [name for name, *_ in takes] == [
        "Curtis_Fuller_Blue_Train_solo_1.m4a",
        "Lee_Morgan_Blue_Train_solo_2.m4a",
        "Wayne_Shorter_Dolores_solo_3.m4a",
    ]
    by_name = {name: (audio, sidecar) for name, audio, sidecar in takes}
    audio, sidecar = by_name["Lee_Morgan_Blue_Train_solo_2.m4a"]
    assert audio == kept and sidecar.name == "Lee_Morgan_Blue_Train_solo_2.m4a.swingscribe.json"
    assert by_name["Wayne_Shorter_Dolores_solo_3.m4a"][1].name.endswith(".m4a.swingscribe.json")
    # The melid comes from the take's name, not the kept file's.
    assert wjazz_batch.melid_from_filename(Path("Lee_Morgan_Blue_Train_solo_2.m4a")) == 2
