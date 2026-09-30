/* Find the solos (roadmap O3): the proposed spans, drawn as a strip of bands
 * under the Overview.
 *
 * The strip sits BELOW the Overview rather than inside it, because the
 * Overview's own gestures are spoken for: a drag there selects and a click
 * seeks. A band is a button; clicking it hands its edges to app.js, which
 * makes the selection through the same flow as a drag. Nothing here sets a
 * selection, a stem or an ensemble itself.
 *
 * The label is TEXT and only text: the loudest melodic stem over the span
 * in the separation the proposal was read from ("other", "guitar", ...), or
 * "rhythm" where the melodic stems fall silent, or "head" where the span
 * repeats the opening melody. It names a stem of THAT separation (a horn
 * htdemucs_6s files under guitar is the Roformer's `other`), which is why
 * it never reaches the Stem menu (gui/solos.py, docs/solo-spans.md).
 */

// What each record's action looks like on its band: the listener's own
// history with the proposal, so a span already taken reads as taken.
const ACTION_MARKS = { accepted: '✓', adjusted: '≈', ignored: '' };
// Narrower than this, a band is drawn without its word.
const MIN_LABEL_PX = 26;

export const SOLO_LEVEL_LABELS = { fewer: 'fewer', default: 'default', more: 'more' };

export function soloLabel(span) {
  return span.kind === 'head' ? 'head' : span.lead;
}

export class SoloBands {
  /**
   * @param {HTMLElement} el   the strip
   * @param {object} opts
   *   onChoose(span)   – a band was clicked
   *   describe(span)   – its tooltip
   */
  constructor(el, opts = {}) {
    this.el = el;
    this.opts = opts;
    this.spans = [];
    this.duration = 0;
    this.width = 0;
    // A band too narrow for its word shows none (a clipped "o" of "other"
    // read as a zero); its tooltip still names it. Re-laid out on resize.
    this._observer = new ResizeObserver(() => {
      if (this.el.clientWidth !== this.width && this.spans.length) this.render();
    });
    this._observer.observe(el);
  }

  setData(payload, duration) {
    this.spans = payload?.spans ?? [];
    this.duration = duration;
    this.render();
  }

  clear() {
    this.spans = [];
    this.el.replaceChildren();
  }

  /* Light the band the selection is exactly on, so a clicked span stays
     visibly "the one" until an edge moves. */
  setCurrent(selection) {
    for (const node of this.el.children) {
      const span = this.spans[Number(node.dataset.index)];
      const on = Boolean(selection && span)
        && Math.abs(selection.a - span.start) < 0.01
        && Math.abs(selection.b - span.end) < 0.01;
      node.classList.toggle('current', on);
    }
  }

  render() {
    const nodes = [];
    const total = Math.max(1e-6, this.duration);
    this.width = this.el.clientWidth;
    this.spans.forEach((span, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.index = String(index);
      const kind = span.kind === 'head' ? ' head' : span.lead === 'rhythm' ? ' rhythm' : '';
      button.className = `solo-band${index % 2 ? ' alt' : ''}${kind}`;
      button.style.left = `${(span.start / total) * 100}%`;
      button.style.width = `${((span.end - span.start) / total) * 100}%`;
      const action = span.record?.action;
      const mark = ACTION_MARKS[action] ?? '';
      if (action) button.classList.add(`taken-${action}`);
      const text = mark ? `${mark} ${soloLabel(span)}` : soloLabel(span);
      const pixels = ((span.end - span.start) / total) * this.width;
      button.textContent = pixels >= MIN_LABEL_PX || !this.width ? text : '';
      button.setAttribute('aria-label', text);
      button.title = this.opts.describe ? this.opts.describe(span) : soloLabel(span);
      button.addEventListener('click', () => this.opts.onChoose?.(span));
      nodes.push(button);
    });
    this.el.replaceChildren(...nodes);
  }
}
