/* The page view: the score Export would write, engraved on the server by
   Verovio (gui/page.py) and drawn here as one SVG per page.

   This module only shows pages and moves around them; which page to ask for,
   and when, is app.js's business — it knows what the listener changed.
   Plain DOM, no library: the SVG arrives finished, so there is nothing to
   engrave here (docs/gui-design.md — no JavaScript dependencies).

   Gestures follow the rule every view in the app keeps: scroll zooms about
   the pointer, shift-scroll or a drag pans. The view takes the wheel for
   itself while the pointer is over it, the price of one rule on every view.
   Zoom is CSS width: the page was laid out for the panel's width, so zooming
   in magnifies that layout rather than re-flowing it, and a zoom costs no
   request. */

const MIN_ZOOM = 0.4;
const MAX_ZOOM = 4;
// The waveforms' and the roll's wheel curve, so a notch means the same
// thing on every view.
const WHEEL_ZOOM = 0.0015;
const DRAG_SLOP_PX = 3;

export class PageView {
  constructor(viewEl, messageEl, { onZoom } = {}) {
    this.view = viewEl;
    this.message = messageEl;
    this.sheets = document.createElement('div');
    this.sheets.className = 'page-sheets';
    this.view.appendChild(this.sheets);
    this.zoom = 1;
    this.digest = null;
    this.onZoom = onZoom ?? (() => {});
    this._drag = null;
    this.view.addEventListener('wheel', (event) => this._onWheel(event), { passive: false });
    this.view.addEventListener('pointerdown', (event) => this._onPointerDown(event));
    this.view.addEventListener('pointermove', (event) => this._onPointerMove(event));
    const end = (event) => this._onPointerUp(event);
    this.view.addEventListener('pointerup', end);
    this.view.addEventListener('pointercancel', end);
  }

  /* The width a page should be laid out for: the view's inner width. */
  get layoutWidth() {
    const style = getComputedStyle(this.view);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    return Math.max(0, this.view.clientWidth - padding);
  }

  /* New pages. A page with the same layout keeps the zoom and the scroll
     position (an edit changes a bar, not where you were reading); a new
     layout width starts from the top at the same zoom. */
  show(pages, digest, { sameLayout = true } = {}) {
    const top = this.view.scrollTop;
    const left = this.view.scrollLeft;
    this.sheets.replaceChildren(...pages.map((svg, index) => {
      const sheet = document.createElement('div');
      sheet.className = 'page-sheet';
      sheet.setAttribute('aria-label', `Page ${index + 1} of ${pages.length}`);
      // Verovio's own SVG, engraved on this server from this server's
      // MusicXML: markup, not text, and nothing in it came from a web page.
      sheet.innerHTML = svg;
      return sheet;
    }));
    this.digest = digest;
    this.message.hidden = true;
    this.sheets.hidden = false;
    this._applyZoom();
    if (sameLayout) {
      this.view.scrollTop = top;
      this.view.scrollLeft = left;
    } else {
      this.view.scrollTop = 0;
    }
  }

  /* A message in place of the page: a step still owed, or an error. The last
     page stays hidden rather than shown under a claim it no longer meets. */
  say(text, { error = false } = {}) {
    this.message.textContent = text;
    this.message.classList.toggle('error', error);
    this.message.hidden = false;
    this.sheets.hidden = true;
    this.digest = null;
  }

  fit() {
    this.zoom = 1;
    this._applyZoom();
    this.view.scrollLeft = 0;
  }

  /* Zoom by `factor` about a point in the view (client coordinates), or
     about the middle of what is showing. */
  zoomBy(factor, clientX = null, clientY = null) {
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, this.zoom * factor));
    if (next === this.zoom) return;
    const rect = this.view.getBoundingClientRect();
    const cx = clientX ?? rect.left + rect.width / 2;
    const cy = clientY ?? rect.top + rect.height / 2;
    const before = this.sheets.getBoundingClientRect();
    this.zoom = next;
    this._applyZoom();
    // Keep the point under the pointer under the pointer. Measured off the
    // sheets themselves, before and after: they centre when narrower than
    // the view, and the gaps between pages do not scale with the zoom.
    const after = this.sheets.getBoundingClientRect();
    const rx = before.width ? after.width / before.width : 1;
    const ry = before.height ? after.height / before.height : 1;
    this.view.scrollLeft += after.left + (cx - before.left) * rx - cx;
    this.view.scrollTop += after.top + (cy - before.top) * ry - cy;
  }

  _applyZoom() {
    // Below 1 the sheets shrink and centre; above, they overflow and pan.
    this.sheets.style.width = `${(this.zoom * 100).toFixed(2)}%`;
    this.view.classList.toggle('zoomed', this.zoom > 1.001);
    this.onZoom(this.zoom);
  }

  _onWheel(event) {
    if (this.sheets.hidden) return;  // a message scrolls with the page
    event.preventDefault();
    if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      // Shift-scroll pans DOWN the page: on a score that is the reading
      // direction, as time is on the waveforms. A sideways swipe pans across.
      if (event.shiftKey) this.view.scrollTop += event.deltaY || event.deltaX;
      else this.view.scrollLeft += event.deltaX;
      return;
    }
    this.zoomBy(Math.exp(-event.deltaY * WHEEL_ZOOM), event.clientX, event.clientY);
  }

  _onPointerDown(event) {
    if (event.button !== 0 || this.sheets.hidden) return;
    this._drag = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: this.view.scrollLeft,
      top: this.view.scrollTop,
      moved: false,
    };
  }

  _onPointerMove(event) {
    const drag = this._drag;
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!drag.moved && Math.abs(dx) < DRAG_SLOP_PX && Math.abs(dy) < DRAG_SLOP_PX) return;
    if (!drag.moved) {
      drag.moved = true;
      // Capture keeps the drag when the pointer leaves the view; a pointer
      // the browser no longer tracks cannot be captured, and the pan should
      // go on regardless.
      try { this.view.setPointerCapture(event.pointerId); } catch { /* not capturable */ }
      this.view.classList.add('panning');
    }
    this.view.scrollLeft = drag.left - dx;
    this.view.scrollTop = drag.top - dy;
  }

  _onPointerUp(event) {
    const drag = this._drag;
    if (!drag || event.pointerId !== drag.id) return;
    this._drag = null;
    this.view.classList.remove('panning');
    if (drag.moved && this.view.hasPointerCapture(event.pointerId)) {
      this.view.releasePointerCapture(event.pointerId);
    }
  }
}
