"""Render the error-taxonomy Pareto as a static HTML page (aggregate only).

    .venv\\Scripts\\python.exe scripts/error_taxonomy_page.py --out pareto.html

Reads `tests/regression/taxonomy-baseline.json` — the committed aggregate that
`scripts/error_taxonomy.py --pin` writes — so the page can be regenerated from
the repository alone and carries nothing derived from a recording beyond
counts. One Pareto per block (all solos, then each instrument family with at
least one solo), bars coloured by population (miss / fp / pair), a cumulative
share line on the same percent axis, and the numbers as a table underneath.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

BASELINE = Path("tests/regression/taxonomy-baseline.json")
POPULATION = {"miss": "miss", "fp": "fp", "pair": "pair"}
FAMILY_ORDER = ["horn", "piano", "guitar", "other"]


def population_of(cls: str, rules) -> str:
    for population, name, _ in rules:
        if name == cls:
            return population
    return "miss"


def ranked(counts: dict) -> list[tuple[str, int]]:
    """Largest first. The pinned JSON is written with sorted keys, so the
    order on disk is alphabetical and the Pareto has to re-rank."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def rules_table():
    from swingscribe.taxonomy import RULES

    return RULES


def pareto_svg(block: dict, rules, noise: dict | None, width: int = 820) -> str:
    counts = ranked(block["counts"])
    total = block["n_errors"] or 1
    row_h, top, left, right = 26, 28, 170, 70
    height = top + row_h * len(counts) + 34
    plot_w = width - left - right
    out = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Pareto of {block["n_errors"]} errors over {block["n_solos"]} solos">'
    ]
    # percent axis, ticks every 20%
    for tick in range(0, 101, 20):
        x = left + plot_w * tick / 100
        out.append(
            f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{height - 30}" class="grid"/>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{height - 14}" class="tick" text-anchor="middle">{tick}%</text>'
        )
    cum = 0.0
    points = []
    for i, (cls, n) in enumerate(counts):
        y = top + i * row_h
        share = n / total
        population = population_of(cls, rules)
        w = max(2.0, plot_w * share)
        sd = noise.get(cls, {}).get("count_sd") if noise else None
        tip = f"{cls}: {n} errors, {share:.1%} of all; {population}"
        if sd is not None:
            tip += f"; bootstrap sd {sd:.1f}"
        out.append(
            f'<text x="{left - 10}" y="{y + 17}" class="label" text-anchor="end">{html.escape(cls)}</text>'
        )
        out.append(
            f'<rect x="{left}" y="{y + 4}" width="{w:.1f}" height="{row_h - 8}" rx="3" '
            f'class="bar {population}"><title>{html.escape(tip)}</title></rect>'
        )
        out.append(
            f'<text x="{left + w + 6:.1f}" y="{y + 17}" class="value">{n}'
            f'<tspan class="muted"> · {share:.1%}</tspan></text>'
        )
        cum += share
        points.append((left + plot_w * cum, y + row_h / 2))
    if points:
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points)
        )
        out.append(f'<path d="{path}" class="cumulative"/>')
        for x, y in points:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="cumulative-dot"/>')
    out.append("</svg>")
    return "\n".join(out)


def block_table(block: dict, rules, noise: dict | None) -> str:
    total = block["n_errors"] or 1
    rows = []
    cum = 0.0
    for cls, n in ranked(block["counts"]):
        cum += n / total
        cost = block["f1_deficit"].get(cls, 0.0)
        sd = noise.get(cls, {}).get("count_sd") if noise else None
        rows.append(
            "<tr>"
            f"<td>{html.escape(cls)}</td><td class='pop'>{population_of(cls, rules)}</td>"
            f"<td class='num'>{n}</td><td class='num'>{n / total:.1%}</td>"
            f"<td class='num'>{cum:.1%}</td><td class='num'>{cost:.4f}</td>"
            f"<td class='num'>{'' if sd is None else f'{sd:.1f}'}</td></tr>"
        )
    return (
        "<table><thead><tr><th>class</th><th>population</th><th class='num'>n</th>"
        "<th class='num'>share</th><th class='num'>cumulative</th>"
        "<th class='num'>F1 cost</th><th class='num'>±sd (solos)</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def section(title: str, block: dict, rules, noise: dict | None, note: str = "") -> str:
    pops = block["populations"]
    return f"""
<section>
  <h2>{html.escape(title)}</h2>
  <p class="meta"><b>{block["n_solos"]}</b> solos · <b>{block["n_reference"]:,}</b> reference notes ·
  <b>{block["n_estimate"]:,}</b> of ours · mean note F1 <b>{block["mean_note_f1"]:.3f}</b> ·
  <b>{block["n_errors"]:,}</b> errors: {pops["miss"]} misses, {pops["fp"]} false positives,
  {pops["pair"]} pairs{(" · " + note) if note else ""}</p>
  <figure>{pareto_svg(block, rules, noise)}</figure>
  <details><summary>The same numbers as a table</summary>{block_table(block, rules, noise)}</details>
</section>"""


def render(agg: dict) -> str:
    rules = rules_table()
    overall = agg["overall"]
    families = [f for f in FAMILY_ORDER if f in agg["family"]] + sorted(
        f for f in agg["family"] if f not in FAMILY_ORDER
    )
    sections = [section("All solos", overall, rules, agg.get("noise"))]
    for family in families:
        block = agg["family"][family]
        note = "too few solos for a bootstrap" if block["n_solos"] < 4 else ""
        sections.append(
            section(f"{family.capitalize()} solos", block, rules, block.get("noise"), note)
        )
    tempo_rows = "".join(
        f"<tr><td>{html.escape(t)}</td><td class='num'>{b['n_solos']}</td>"
        f"<td class='num'>{b['mean_note_f1']:.3f}</td><td class='num'>{b['n_errors']}</td>"
        f"<td>{html.escape(', '.join(f'{c} {n}' for c, n in ranked(b['counts'])[:3]))}</td></tr>"
        for t, b in agg["tempo"].items()
    )
    rules_rows = "".join(
        f"<tr><td class='pop'>{p}</td><td>{html.escape(c)}</td><td>{html.escape(d)}</td></tr>"
        for p, c, d in rules
    )
    deficit = 1.0 - overall["mean_note_f1"]
    return f"""<title>Where the 0.145 Goes</title>
<meta name="description" content="Pareto of every WJazzD transcription error, one cause each">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,600&display=swap">
<style>
:root {{
  color-scheme: light;
  --bg: #f4f5f3; --surface: #fcfcfb; --ink: #14171a; --ink-2: #4f5559; --ink-3: #7d8489;
  --rule: #d9dcd8; --grid: #e6e8e4;
  --miss: #2a78d6; --fp: #eb6834; --pair: #1baf7a; --cum: #52514e;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --bg: #15181b; --surface: #1c2024; --ink: #f2f3f1; --ink-2: #c3c6c2; --ink-3: #8f959a;
    --rule: #333a40; --grid: #262c31;
    --miss: #3987e5; --fp: #d95926; --pair: #199e70; --cum: #c3c2b7;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg: #15181b; --surface: #1c2024; --ink: #f2f3f1; --ink-2: #c3c6c2; --ink-3: #8f959a;
  --rule: #333a40; --grid: #262c31;
  --miss: #3987e5; --fp: #d95926; --pair: #199e70; --cum: #c3c2b7;
}}
body {{ background: var(--bg); color: var(--ink); margin: 0;
  font: 15px/1.5 "IBM Plex Sans", "Segoe UI", system-ui, sans-serif; }}
main {{ max-width: 880px; margin: 0 auto; padding: 40px 24px 64px; }}
h1 {{ font: 600 40px/1.1 "Fraunces", Georgia, serif; margin: 0 0 8px; text-wrap: balance; letter-spacing: -0.01em; }}
h2 {{ font: 600 20px/1.3 "IBM Plex Sans", system-ui, sans-serif; margin: 40px 0 4px; }}
.lede {{ color: var(--ink-2); max-width: 62ch; margin: 0 0 20px; }}
.meta {{ color: var(--ink-2); margin: 0 0 12px; font-size: 14px; }}
.meta b {{ color: var(--ink); font-family: "IBM Plex Mono", monospace; font-weight: 500; }}
.hero {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 20px 0 8px; }}
.hero div {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 14px 16px; }}
.hero .n {{ font: 500 28px/1.1 "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }}
.hero .l {{ color: var(--ink-3); font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; margin-top: 4px; }}
.legend {{ display: flex; gap: 18px; flex-wrap: wrap; color: var(--ink-2); font-size: 13px; margin: 8px 0 0; }}
.legend span::before {{ content: ""; display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }}
.legend .miss::before {{ background: var(--miss); }} .legend .fp::before {{ background: var(--fp); }}
.legend .pair::before {{ background: var(--pair); }}
.legend .cum::before {{ background: none; border-top: 2px solid var(--cum); height: 0; border-radius: 0; vertical-align: 3px; }}
figure {{ margin: 0; background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 8px 4px; overflow-x: auto; }}
svg {{ display: block; font-family: "IBM Plex Sans", system-ui, sans-serif; }}
svg .grid {{ stroke: var(--grid); stroke-width: 1; }}
svg .tick {{ fill: var(--ink-3); font-size: 11px; }}
svg .label {{ fill: var(--ink); font-size: 13px; font-family: "IBM Plex Mono", monospace; }}
svg .value {{ fill: var(--ink); font-size: 12px; font-family: "IBM Plex Mono", monospace; }}
svg .value .muted {{ fill: var(--ink-3); }}
svg .bar.miss {{ fill: var(--miss); }} svg .bar.fp {{ fill: var(--fp); }} svg .bar.pair {{ fill: var(--pair); }}
svg .bar:hover {{ opacity: 0.85; }}
svg .cumulative {{ fill: none; stroke: var(--cum); stroke-width: 2; stroke-linejoin: round; }}
svg .cumulative-dot {{ fill: var(--surface); stroke: var(--cum); stroke-width: 2; }}
details {{ margin-top: 8px; color: var(--ink-2); font-size: 14px; }}
summary {{ cursor: pointer; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 13px; }}
th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--rule); }}
th {{ color: var(--ink-3); font-weight: 600; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }}
td.num, th.num {{ text-align: right; font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }}
td.pop {{ color: var(--ink-3); font-family: "IBM Plex Mono", monospace; font-size: 12px; }}
.wrap {{ overflow-x: auto; }}
footer {{ color: var(--ink-3); font-size: 13px; margin-top: 40px; border-top: 1px solid var(--rule); padding-top: 12px; }}
@media (max-width: 640px) {{ .hero {{ grid-template-columns: 1fr; }} h1 {{ font-size: 30px; }} }}
</style>
<main>
  <h1>Where the 0.145 goes</h1>
  <p class="lede">Every note the WJazzD benchmark counts against the transcriber — a reference note
  we missed, a note we emitted that nobody played, or a pair of the two that is really one error —
  given exactly one cause by a fixed rule table, then ranked. Bars are the share of all errors;
  the line is the running total. Same-recording, audio-against-audio, offsets ignored.</p>
  <div class="hero">
    <div><div class="n">{overall["mean_note_f1"]:.3f}</div><div class="l">mean note F1 · n={overall["n_solos"]}</div></div>
    <div><div class="n">{deficit:.3f}</div><div class="l">deficit explained below</div></div>
    <div><div class="n">{overall["n_errors"]:,}</div><div class="l">errors classified · {overall["counts"].get("unclassified", 0)} unclassified</div></div>
  </div>
  <p class="legend"><span class="miss">miss — theirs, nothing of ours near it</span>
  <span class="fp">false positive — ours, nothing of theirs near it</span>
  <span class="pair">pair — one of each within 150 ms, one error</span>
  <span class="cum">cumulative share</span></p>
  {"".join(sections)}
  <section>
    <h2>By WJazzD tempo class</h2>
    <div class="wrap"><table><thead><tr><th>tempo class</th><th class="num">solos</th><th class="num">mean F1</th>
    <th class="num">errors</th><th>three largest classes</th></tr></thead><tbody>{tempo_rows}</tbody></table></div>
  </section>
  <section>
    <h2>The rule table, in decision order</h2>
    <p class="meta">The first rule that fires wins. `swingscribe.taxonomy.RULES`.</p>
    <div class="wrap"><table><thead><tr><th>population</th><th>class</th><th>fires when</th></tr></thead>
    <tbody>{rules_rows}</tbody></table></div>
  </section>
  <footer>Generated by scripts/error_taxonomy_page.py from tests/regression/taxonomy-baseline.json.
  Counts only; no note derived from a recording leaves the machine. ±sd is the bootstrap spread of a
  class's count over {1000} resamples of the solos — how much the count depends on which solos are in
  the set, not measurement noise (classification is deterministic).</footer>
</main>
"""


def main():
    parser = argparse.ArgumentParser(description="Render the taxonomy Pareto page.")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    agg = json.loads(args.baseline.read_text(encoding="utf-8"))
    args.out.write_text(render(agg), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
