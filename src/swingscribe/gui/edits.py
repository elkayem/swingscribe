"""The listener's edits against one review, and the notes they leave.

ONE function (`resolve`) turns a cached review payload and the sidecar into
what every reader of the span needs -- the roll, the ear test, Export, the
page view, Score, and scripts/multi_horn_page.py -- so none of them can
disagree about which notes the listener kept. It used to be a closure inside
`create_app`; a script that wants the GUI's page needs it too, and a second
copy is the shape of duplication this project has paid for twice.

Three views of a review, each with its own stored edits (`erasures.view_of`):

- the LINE (every horn, and a pianist's melody line): erasures against the
  line, additions from the piano model's pool;
- a pianist's ALL NOTES (`texture`): everything the piano model heard, with
  the listener's hand assignments for a two-staff page;
- a MULTI-HORN head (`horns`): both voices, additions from the notes Basic
  Pitch heard that neither voice holds, and the listener's voice moves
  (sidecar `voices`, docs/multi-horn.md).

Pure: it reads only what it is handed.
"""

from typing import Any

from swingscribe.gui import erasures as gui_erasures


def resolve(
    settings: dict[str, Any],
    payload: dict[str, Any],
    span: tuple[float, float] | None,
    texture: bool = False,
    horns: bool = False,
    overlap_s: float | None = None,
    overlap_share: float | None = None,
) -> dict[str, Any]:
    """Both of the listener's edits against this review, and what they leave.

    `erasures` and `additions` are the two resolutions the client reads;
    `candidates` is the pool the roll draws (heard notes the transcription
    does not already hold); `audible` and `added` are the notes that reach a
    render or a page.

    `texture` swaps the line for EVERYTHING the piano model heard (the
    All-notes view): those become `notes`, there is no pool left to offer,
    and `hands` resolves the listener's staff assignments, with `right` and
    `left` the audible notes each hand's staff will hold.

    `horns` is a multi-horn head: `audible` and `added` each carry the
    `voice` they are written in -- the voices re-ordered over the edited
    set (`voices.order`), so a note whose partner was erased is written
    once, and then the listener's own moves (`voices`) on top. `overlap_s`
    and `overlap_share` are the review's own TranscribeConfig values.
    """
    view = gui_erasures.HORNS if horns else gui_erasures.ALL if texture else gui_erasures.LINE
    stored_erasures = settings.get("erasures") or []
    stored_additions = settings.get("additions") or []
    if texture:
        notes = sorted(
            (
                {
                    "onset": c["onset"],
                    "duration": c["duration"],
                    "pitch": c["pitch"],
                    "confidence": c.get("confidence", 0.0),
                }
                for c in payload.get("candidates") or []
            ),
            key=lambda n: (n["onset"], n["pitch"]),
        )
        erased = resolve_erasures(stored_erasures, notes, span, view)
        hands = gui_erasures.resolve_hands(settings.get("hands") or [], notes, span)
        silenced = set(erased["silenced"])
        sides = gui_erasures.hands_of(notes, hands)
        kept = [
            (note, side)
            for index, (note, side) in enumerate(zip(notes, sides, strict=True))
            if index not in silenced
        ]
        return {
            "notes": notes,
            "erasures": erased,
            # Additions belong to the line's view; carried, never touched.
            "additions": _carried(stored_additions),
            "candidates": [],
            "audible": gui_erasures.audible(notes, silenced),
            "added": [],
            "hands": hands,
            "voices": None,
            "right": [n for n, side in kept if side == "right"],
            "left": [n for n, side in kept if side == "left"],
        }
    notes = payload["notes"]
    erased = resolve_erasures(stored_erasures, notes, span, view)
    candidates = gui_erasures.pool(payload.get("candidates") or [], notes)
    mine, rest = gui_erasures.split_by_view(stored_additions, view)
    additions = gui_erasures.resolve_additions(mine, candidates, span)
    additions = {**additions, "carried": additions["carried"] + rest}
    audible = gui_erasures.audible(notes, erased["silenced"])
    added = gui_erasures.enabled(candidates, additions["added"])
    voices = None
    if horns:
        audible, added, voices = _voiced(
            audible, added, settings.get("voices") or [], span, overlap_s, overlap_share
        )
    return {
        "notes": notes,
        "erasures": erased,
        "additions": additions,
        "candidates": candidates,
        "audible": audible,
        "added": added,
        "hands": None,
        "voices": voices,
    }


def resolve_erasures(
    stored: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    span: tuple[float, float] | None,
    view: str,
) -> dict[str, Any]:
    """Which of these notes the listener silenced ON THIS VIEW; every other
    view's erasures are carried through untouched (`erasures.split_by_view`).
    """
    mine, rest = gui_erasures.split_by_view(stored, view)
    resolved = gui_erasures.resolve(mine, notes, span)
    return {**resolved, "carried": resolved["carried"] + rest}


def _carried(stored: list[dict[str, Any]]) -> dict[str, Any]:
    """Additions a view does not resolve, handed back whole."""
    return {"added": [], "carried": stored, "unmatched": [], "moved": [], "stored": len(stored)}


def _voiced(
    audible: list[dict[str, Any]],
    added: list[dict[str, Any]],
    moves: list[dict[str, Any]],
    span: tuple[float, float] | None,
    overlap_s: float | None,
    overlap_share: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """The kept notes of a multi-horn head, each with the voice it is
    written in: ordered over the EDITED set (`voices.order` -- rule 3 alone,
    so nothing the listener kept or switched on is pruned again), then the
    listener's voice moves applied, matched by content."""
    from swingscribe import voices as horn_voices

    combined = [*audible, *added]
    rules = {}
    if overlap_s is not None:
        rules["overlap_s"] = overlap_s
    if overlap_share is not None:
        rules["share"] = overlap_share
    order = horn_voices.order(combined, **rules)
    resolved = gui_erasures.resolve_voices(moves, combined, span)
    chosen = dict.fromkeys(resolved["upper"], 1) | dict.fromkeys(resolved["lower"], 2)
    voiced = [
        {**note, "voice": chosen.get(index, voice)}
        for index, (note, voice) in enumerate(zip(combined, order, strict=True))
    ]
    return voiced[: len(audible)], voiced[len(audible) :], resolved
