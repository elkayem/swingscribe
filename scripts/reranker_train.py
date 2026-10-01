"""Train A6's re-ranker on the synthetic beats `reranker_data.py render` wrote.

    python scripts/reranker_train.py --beats beats.pkl --mode open --cv 5
    python scripts/reranker_train.py --beats beats.pkl --mode open --l2 1e-3 --out weights.json

docs/reranker.md. A conditional logit over each beat's candidates
(`swingscribe.reranker.featurize`): the loss is the negative log of the
softmax mass on the candidates that write the page (several may), plus L2.
`--mode gated` offers the model only what the shipped convention gates
allow; `--mode open` every reading the note-keeping guards allow. Beats no
candidate writes correctly are kept in the accuracy (as misses) and left
out of the loss. `--cv` holds out whole PAGES (every rendering of a page in
one fold). numpy and scipy (the ml group); the shipped model is the JSON.
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

MIN_COUNT = 20  # a feature seen on fewer candidates than this is dropped


def beats_for(rows: list[dict], mode: str) -> list[dict]:
    """The labelled beats where `mode` offers a choice, each with its
    candidate list (indices into the recorded candidates)."""
    out = []
    for r in rows:
        if not r["labelled"]:
            continue
        idx = [i for i, c in enumerate(r["candidates"]) if mode == "open" or c["gated"]]
        base = [i for i in idx if r["candidates"][i]["baseline"]]
        if mode == "gated" and (len(idx) < 2 or not base):
            continue
        if not idx:
            continue
        out.append({**r, "idx": idx, "base": base[0] if base else None})
    return out


def featurize_all(beats: list[dict]) -> list[list[dict]]:
    from swingscribe.reranker import featurize

    return [featurize(b["context"], [b["candidates"][i] for i in b["idx"]]) for b in beats]


def design(features: list[list[dict]], vocab: dict[str, int] | None = None):
    import numpy as np
    from scipy import sparse

    if vocab is None:
        counts = Counter(name for beat in features for cand in beat for name in cand)
        vocab = {
            name: j for j, name in enumerate(sorted(n for n, c in counts.items() if c >= MIN_COUNT))
        }
    rows, cols, vals, starts = [], [], [], [0]
    r = 0
    for beat in features:
        for cand in beat:
            for name, value in cand.items():
                j = vocab.get(name)
                if j is not None and value:
                    rows.append(r)
                    cols.append(j)
                    vals.append(value)
            r += 1
        starts.append(r)
    X = sparse.csr_matrix((vals, (rows, cols)), shape=(r, len(vocab)))
    return X, np.asarray(starts), vocab


def hits_of(beat: dict) -> list[int]:
    """Per offered candidate, how many of the beat's notes it writes where
    the page does (the page positions ride in `page_figure`, in note order)."""
    from fractions import Fraction

    rel = [float(Fraction(x)) for x in beat["page_figure"].split()]
    return [
        sum(
            1
            for s, r in zip(beat["candidates"][i]["snapped"], rel, strict=True)
            if abs(s - r) < 1e-6
        )
        for i in beat["idx"]
    ]


def distances_of(beat: dict) -> list[float]:
    """Per offered candidate, how far its written positions sit from the
    page's, summed over the beat's notes, in beats."""
    from fractions import Fraction

    rel = [float(Fraction(x)) for x in beat["page_figure"].split()]
    return [
        sum(abs(s - r) for s, r in zip(beat["candidates"][i]["snapped"], rel, strict=True))
        for i in beat["idx"]
    ]


def targets(beats: list[dict], target: str = "exact"):
    """(y the loss trains toward, y_exact, notes placed right, notes, is the
    rule's pick). `exact`: a candidate is a target when it writes every note
    of the beat where the page does; `hits`: when it writes the MOST notes
    where the page does (and at least one) -- so a beat no candidate gets
    whole still says which wrong reading is least wrong; `dist`: when its
    written positions sit nearest the page's (summed distance), so every
    labelled beat teaches, and a reading a sixteenth off beats one a third
    off; `stay`: `exact`, and where NO candidate writes the page, the rule's
    own pick -- move only to a reading that writes the page, never from one
    wrong reading to another (docs/reranker.md: on (a) those "both wrong"
    swaps were 50 of the first models' 68 moves on labelled beats, and they
    are what cost the page)."""
    import numpy as np

    y, exact, hits, notes, base = [], [], [], [], []
    for b in beats:
        h = hits_of(b)
        best = max(h)
        dist = distances_of(b)
        nearest = min(dist)
        n = len(b["page_figure"].split())
        reachable = any(b["correct"][i] for i in b["idx"])
        for i, hi, di in zip(b["idx"], h, dist, strict=True):
            exact.append(1.0 if b["correct"][i] else 0.0)
            if target == "exact":
                y.append(exact[-1])
            elif target == "stay":
                y.append(exact[-1] if reachable else 1.0 if i == b["base"] else 0.0)
            elif target == "hits":
                y.append(1.0 if best > 0 and hi == best else 0.0)
            else:
                y.append(1.0 if di <= nearest + 1e-9 else 0.0)
            hits.append(hi)
            notes.append(n)
            base.append(1.0 if i == b["base"] else 0.0)
    return np.asarray(y), np.asarray(exact), np.asarray(hits), np.asarray(notes), np.asarray(base)


def fit(X, starts, y, l2: float, w0=None):
    import numpy as np
    from scipy.optimize import minimize

    counts = np.diff(starts)
    group = np.repeat(np.arange(len(counts)), counts)
    has_pos = np.add.reduceat(y, starts[:-1]) > 0
    use = has_pos[group]
    n_groups = has_pos.sum()

    def loss(w):
        s = X @ w
        m = np.maximum.reduceat(s, starts[:-1])
        e = np.exp(s - m[group])
        z_all = np.add.reduceat(e, starts[:-1])
        z_pos = np.add.reduceat(e * y, starts[:-1])
        ok = has_pos
        value = (np.log(z_all[ok]) - np.log(z_pos[ok])).sum() / n_groups + 0.5 * l2 * w @ w
        p = e / z_all[group]
        q = np.where(y > 0, e / np.where(z_pos[group] > 0, z_pos[group], 1.0), 0.0)
        g = np.where(use, p - q, 0.0)
        grad = X.T @ g / n_groups + l2 * w
        return value, grad

    w = np.zeros(X.shape[1]) if w0 is None else w0
    result = minimize(loss, w, jac=True, method="L-BFGS-B", options={"maxiter": 400})
    return result.x, result


def accuracy(X, starts, y, base, w, hits=None, notes=None) -> dict:
    """Per beat: the model's pick (the rule's on a tie), the rule's, and
    whether any candidate is right; with `hits`, the share of NOTES each
    places where the page does."""
    import numpy as np

    s = X @ w
    model = base_right = oracle = 0
    note_model = note_base = note_total = 0
    n = len(starts) - 1
    for k in range(n):
        a, b = starts[k], starts[k + 1]
        sc = s[a:b]
        bi = np.flatnonzero(base[a:b])
        best = int(np.argmax(sc))
        if len(bi) and sc[best] <= sc[bi[0]] + 1e-12:
            best = int(bi[0])
        model += y[a + best]
        base_right += y[a + bi[0]] if len(bi) else 0
        oracle += y[a:b].max()
        if hits is not None:
            note_model += hits[a + best]
            note_base += hits[a + bi[0]] if len(bi) else 0
            note_total += notes[a]
    out = {"beats": n, "model": model / n, "baseline": base_right / n, "oracle": oracle / n}
    if hits is not None and note_total:
        out["notes_model"] = note_model / note_total
        out["notes_baseline"] = note_base / note_total
    return out


def changes(X, starts, y, base, w, beats) -> dict:
    """Where the model departs from the rule: right->wrong and wrong->right,
    by (page figure, the rule's figure, the model's figure)."""
    import numpy as np

    s = X @ w
    good, bad = Counter(), Counter()
    for k in range(len(starts) - 1):
        a, b = starts[k], starts[k + 1]
        sc = s[a:b]
        bi = np.flatnonzero(base[a:b])
        if not len(bi):
            continue
        best = int(np.argmax(sc))
        if sc[best] <= sc[bi[0]] + 1e-12 or best == bi[0]:
            continue
        cands = [beats[k]["candidates"][i] for i in beats[k]["idx"]]
        key = (beats[k]["page_figure"], cands[bi[0]]["figure"], cands[best]["figure"])
        if y[a + best] and not y[a + bi[0]]:
            good[key] += 1
        elif y[a + bi[0]] and not y[a + best]:
            bad[key] += 1
    return {"fixed": good, "broken": bad}


def folds(beats: list[dict], k: int, seed: int = 0) -> list[set[str]]:
    pages = sorted({b["page"] for b in beats})
    random.Random(seed).shuffle(pages)
    return [set(pages[i::k]) for i in range(k)]


def main() -> None:
    import numpy as np

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--beats", type=Path, required=True)
    parser.add_argument("--mode", choices=("gated", "open"), default="open")
    parser.add_argument("--l2", type=float, nargs="+", default=[1e-3])
    parser.add_argument("--cv", type=int, default=0)
    parser.add_argument("--target", choices=("exact", "stay", "hits", "dist"), default="exact")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    data = pickle.load(args.beats.open("rb"))
    beats = beats_for(data["rows"], args.mode)
    t0 = time.time()
    features = featurize_all(beats)
    print(
        f"{len(beats)} labelled beats with a {args.mode} choice over "
        f"{len({b['page'] for b in beats})} pages, featurized in {time.time() - t0:.0f}s"
    )
    card: dict = {"mode": args.mode, "beats": len(beats), "cv": {}}
    if args.cv:
        for l2 in args.l2:
            totals = Counter()
            for fold, held in enumerate(folds(beats, args.cv)):
                train = [i for i, b in enumerate(beats) if b["page"] not in held]
                test = [i for i, b in enumerate(beats) if b["page"] in held]
                Xtr, st_tr, vocab = design([features[i] for i in train])
                ytr, *_rest = targets([beats[i] for i in train], args.target)
                w, _res = fit(Xtr, st_tr, ytr, l2)
                Xte, st_te, _ = design([features[i] for i in test], vocab)
                _y, yte, hte, nte, bte = targets([beats[i] for i in test], args.target)
                acc = accuracy(Xte, st_te, yte, bte, w, hte, nte)
                for key in ("model", "baseline", "oracle"):
                    totals[key] += acc[key] * acc["beats"]
                for key in ("notes_model", "notes_baseline"):
                    totals[key] += acc[key] * acc["beats"]
                totals["beats"] += acc["beats"]
                print(
                    f"  l2={l2:g} fold {fold}: beats {acc['beats']} model {acc['model']:.4f} "
                    f"baseline {acc['baseline']:.4f} oracle {acc['oracle']:.4f}"
                )
            n = totals["beats"]
            keys = ("model", "baseline", "oracle", "notes_model", "notes_baseline")
            row = {k: totals[k] / n for k in keys}
            card["cv"][str(l2)] = {**row, "beats": n}
            print(
                f"l2={l2:g} held-out pages: model {row['model']:.4f} baseline "
                f"{row['baseline']:.4f} oracle {row['oracle']:.4f} over {n} beats; notes right "
                f"model {row['notes_model']:.4f} baseline {row['notes_baseline']:.4f}"
            )
    if args.out:
        l2 = args.l2[0]
        X, starts, vocab = design(features)
        ytrain, y, hits, notes, base = targets(beats, args.target)
        w, res = fit(X, starts, ytrain, l2)
        acc = accuracy(X, starts, y, base, w, hits, notes)
        print(f"trained on all: {acc}, {res.message}, {len(vocab)} features")
        ch = changes(X, starts, y, base, w, beats)
        for which in ("fixed", "broken"):
            print(f"  {which}: {sum(ch[which].values())}")
            for key, v in ch[which].most_common(12):
                print(f"    {v:5d} {key}")
        from swingscribe.reranker import save_model

        weights = {name: float(w[j]) for name, j in vocab.items()}
        meta = {
            "open": args.mode == "open",
            "l2": l2,
            "target": args.target,
            "beats": len(beats),
            "pages": len({b["page"] for b in beats}),
            "train_accuracy": acc,
            "source": "scripts/reranker_train.py on scripts/reranker_data.py renderings",
        }
        save_model(args.out, weights, meta)
        card["train"] = acc
        card["changes"] = {
            k: [[*key, v] for key, v in ch[k].most_common(30)] for k in ("fixed", "broken")
        }
        print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
        top = sorted(weights.items(), key=lambda kv: -abs(kv[1]))[:25]
        for name, value in top:
            print(f"    {value:+.3f} {name}")
    if args.json:
        args.json.write_text(json.dumps(card, indent=1, default=float), encoding="utf-8")
    del np


if __name__ == "__main__":
    main()
