/* Waveform view: a min/max envelope on a canvas, plus DOM overlays for the
   selection, its drag handles, and the playhead.
 *
 * Drawn here rather than by a waveform library because both tiers need things
 * a library makes awkward: the detail tier renders an arbitrary time *window*
 * (so its local time frame is offset from the track's), and the audition tier
 * draws the isolated stem on top of the original mix — which is the clearest
 * possible read on what separation actually removed.
 *
 * All times in this module are track-global seconds. The window mapping is the
 * only place that changes.
 */

const DRAG_THRESHOLD_PX = 4;   // below this a pointer gesture is a click, not a drag
const HANDLE_GRAB_PX = 8;      // how close to an edge counts as grabbing it

export class WaveView {
  /**
   * @param {HTMLElement} el
   * @param {object} opts
   *   selectable  – enable the A/B selection gestures
   *   onSeek(t)          onSelect(a, b, done)
   *   onWindow(start, end)  – emitted when the view zooms or pans itself
   *   onEdgeFocus('a'|'b')  – a boundary was grabbed, so the nudge keys should
   *                           now apply to it
   */
  constructor(el, opts = {}) {
    this.el = el;
    this.opts = opts;
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d');
    el.appendChild(this.canvas);

    this.win = { start: 0, end: 1 };
    this.bounds = { start: 0, end: 1 };   // the full track; zoom never escapes it
    this.selection = null;                // {a, b} in track-global seconds
    this.playhead = null;
    this.peaks = null;
    this.overlay = null;
    this.windowBox = null;

    this._buildOverlays();
    this._bindPointer();

    this._observer = new ResizeObserver(() => this.draw());
    this._observer.observe(el);
  }

  // ── geometry ──────────────────────────────────────────────────────────────

  get span() { return Math.max(1e-6, this.win.end - this.win.start); }

  timeToX(t) { return ((t - this.win.start) / this.span) * this.el.clientWidth; }

  xToTime(x) { return this.win.start + (x / Math.max(1, this.el.clientWidth)) * this.span; }

  eventTime(event) {
    const rect = this.el.getBoundingClientRect();
    return this.xToTime(event.clientX - rect.left);
  }

  // ── state ─────────────────────────────────────────────────────────────────

  setBounds(start, end) { this.bounds = { start, end }; }

  setWindow(start, end, { silent = false } = {}) {
    const width = Math.max(0.05, end - start);
    let s = start;
    let e = start + width;
    const full = this.bounds.end - this.bounds.start;
    if (width >= full) { s = this.bounds.start; e = this.bounds.end; }
    else {
      if (s < this.bounds.start) { s = this.bounds.start; e = s + width; }
      if (e > this.bounds.end) { e = this.bounds.end; s = e - width; }
    }
    const changed = s !== this.win.start || e !== this.win.end;
    this.win = { start: s, end: e };
    this.draw();
    if (changed && !silent && this.opts.onWindow) this.opts.onWindow(s, e);
    return changed;
  }

  setPeaks(data) { this.peaks = data; this.draw(); }

  setOverlay(data) { this.overlay = data; this.draw(); }

  setSelection(a, b) {
    this.selection = a === null || b === null ? null : { a, b };
    this.draw();
  }

  setPlayhead(t) {
    this.playhead = t;
    // Playhead moves every animation frame; only the cheap overlay is touched.
    this._layoutOverlays();
  }

  setWindowBox(start, end) {
    this.windowBox = start === null ? null : { start, end };
    this._layoutOverlays();
  }

  // ── drawing ───────────────────────────────────────────────────────────────

  draw() {
    const width = this.el.clientWidth;
    const height = this.el.clientHeight;
    if (!width || !height) return;
    const dpr = window.devicePixelRatio || 1;
    if (this.canvas.width !== Math.round(width * dpr)) {
      this.canvas.width = Math.round(width * dpr);
      this.canvas.height = Math.round(height * dpr);
    }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const style = getComputedStyle(document.documentElement);
    const base = style.getPropertyValue('--wave').trim() || '#4c5468';
    const lit = style.getPropertyValue('--wave-lit').trim() || '#97a1bb';
    const lead = style.getPropertyValue('--lead').trim() || '#56cfc0';

    if (this.peaks) {
      this._drawEnvelope(this.peaks, base, width, height);
      // The selected span again, brighter — so the eye lands on the passage
      // being worked on without hiding the rest of the track.
      if (this.selection) {
        ctx.save();
        const x0 = this.timeToX(Math.min(this.selection.a, this.selection.b));
        const x1 = this.timeToX(Math.max(this.selection.a, this.selection.b));
        ctx.beginPath();
        ctx.rect(x0, 0, Math.max(0, x1 - x0), height);
        ctx.clip();
        this._drawEnvelope(this.peaks, lit, width, height);
        ctx.restore();
      }
    }
    if (this.overlay) this._drawEnvelope(this.overlay, lead, width, height, 0.92);

    // centre line
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    ctx.fillRect(0, Math.round(height / 2), width, 1);

    this._layoutOverlays();
  }

  /* Envelope data is {start, end, peaks: [maxima, minima]} covering its own
     time range, which need not match the view's window — the detail tier
     briefly shows stale peaks while fresher ones are fetched. */
  _drawEnvelope(data, color, width, height, alpha = 1) {
    const [maxima, minima] = data.peaks;
    const count = maxima.length;
    if (!count) return;
    const mid = height / 2;
    const scale = height / 2 - 1;
    const bucketSpan = (data.end - data.start) / count;
    const ctx = this.ctx;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.beginPath();

    // One column per device-independent pixel; buckets are folded into the
    // column they land in, so an over-supplied envelope stays accurate.
    const columns = Math.max(1, Math.round(width));
    let bucket = 0;
    for (let column = 0; column < columns; column++) {
      const tStart = this.xToTime(column);
      const tEnd = this.xToTime(column + 1);
      if (tEnd < data.start || tStart > data.end) continue;
      let from = Math.floor((tStart - data.start) / bucketSpan);
      let to = Math.ceil((tEnd - data.start) / bucketSpan);
      from = Math.max(0, Math.min(from, count - 1));
      to = Math.max(from + 1, Math.min(to, count));
      let hi = 0;
      let lo = 0;
      for (bucket = from; bucket < to; bucket++) {
        if (maxima[bucket] > hi) hi = maxima[bucket];
        if (minima[bucket] < lo) lo = minima[bucket];
      }
      const top = mid - hi * scale;
      const bottom = mid - lo * scale;
      ctx.rect(column, top, 1, Math.max(1, bottom - top));
    }
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  // ── DOM overlays ──────────────────────────────────────────────────────────

  _buildOverlays() {
    const make = (cls, html = '') => {
      const node = document.createElement('div');
      node.className = cls;
      node.innerHTML = html;
      node.hidden = true;
      this.el.appendChild(node);
      return node;
    };
    this.nodes = {
      dimLeft: make('sel-dim'),
      dimRight: make('sel-dim'),
      shade: make('sel-shade'),
      windowBox: make('window-box'),
      handleA: make('handle a', '<span class="tag">A</span>'),
      handleB: make('handle b', '<span class="tag">B</span>'),
      playhead: make('playhead'),
    };
    if (!this.opts.selectable) {
      this.nodes.handleA.remove();
      this.nodes.handleB.remove();
      this.nodes.handleA = this.nodes.handleB = null;
    }
  }

  _layoutOverlays() {
    const { nodes } = this;
    const width = this.el.clientWidth;
    if (this.selection) {
      const a = Math.min(this.selection.a, this.selection.b);
      const b = Math.max(this.selection.a, this.selection.b);
      const xa = this.timeToX(a);
      const xb = this.timeToX(b);
      nodes.shade.hidden = false;
      nodes.shade.style.left = `${xa}px`;
      nodes.shade.style.width = `${Math.max(0, xb - xa)}px`;
      nodes.dimLeft.hidden = xa <= 0;
      nodes.dimLeft.style.left = '0px';
      nodes.dimLeft.style.width = `${Math.max(0, xa)}px`;
      nodes.dimRight.hidden = xb >= width;
      nodes.dimRight.style.left = `${xb}px`;
      nodes.dimRight.style.width = `${Math.max(0, width - xb)}px`;
      if (nodes.handleA) {
        // Handles are hidden rather than clamped when off-window: a handle
        // pinned to the edge invites you to drag the boundary you can't see.
        nodes.handleA.hidden = xa < -2 || xa > width + 2;
        nodes.handleA.style.left = `${xa}px`;
        nodes.handleB.hidden = xb < -2 || xb > width + 2;
        nodes.handleB.style.left = `${xb}px`;
      }
    } else {
      for (const key of ['shade', 'dimLeft', 'dimRight']) nodes[key].hidden = true;
      if (nodes.handleA) { nodes.handleA.hidden = true; nodes.handleB.hidden = true; }
    }

    if (this.windowBox) {
      const x0 = this.timeToX(this.windowBox.start);
      const x1 = this.timeToX(this.windowBox.end);
      nodes.windowBox.hidden = false;
      nodes.windowBox.style.left = `${x0}px`;
      nodes.windowBox.style.width = `${Math.max(2, x1 - x0)}px`;
    } else {
      nodes.windowBox.hidden = true;
    }

    if (this.playhead === null) {
      nodes.playhead.hidden = true;
    } else {
      const x = this.timeToX(this.playhead);
      nodes.playhead.hidden = x < 0 || x > width;
      nodes.playhead.style.left = `${x}px`;
    }
  }

  // ── pointer gestures ──────────────────────────────────────────────────────

  _bindPointer() {
    this.el.addEventListener('pointerdown', (event) => this._onPointerDown(event));
    if (this.opts.onWindow) {
      this.el.addEventListener('wheel', (event) => this._onWheel(event), { passive: false });
    }
  }

  _hitHandle(x) {
    if (!this.selection || !this.opts.selectable) return null;
    const xa = this.timeToX(Math.min(this.selection.a, this.selection.b));
    const xb = this.timeToX(Math.max(this.selection.a, this.selection.b));
    if (Math.abs(x - xa) <= HANDLE_GRAB_PX) return 'a';
    if (Math.abs(x - xb) <= HANDLE_GRAB_PX) return 'b';
    if (x > xa && x < xb) return 'move';
    return null;
  }

  _onPointerDown(event) {
    if (event.button !== 0) return;
    const rect = this.el.getBoundingClientRect();
    const startX = event.clientX - rect.left;
    const startTime = this.xToTime(startX);
    const pan = event.shiftKey && this.opts.onWindow;
    const grabbed = pan ? null : this._hitHandle(startX);

    if ((grabbed === 'a' || grabbed === 'b') && this.opts.onEdgeFocus) {
      this.opts.onEdgeFocus(grabbed);
    }

    const original = this.selection ? { ...this.selection } : null;
    const winStart = this.win.start;
    let moved = false;
    let creating = false;

    this.el.setPointerCapture(event.pointerId);
    if (grabbed === 'a' && this.nodes.handleA) this.nodes.handleA.classList.add('dragging');
    if (grabbed === 'b' && this.nodes.handleB) this.nodes.handleB.classList.add('dragging');

    const clamp = (t) => Math.max(this.bounds.start, Math.min(t, this.bounds.end));

    const onMove = (moveEvent) => {
      const x = moveEvent.clientX - rect.left;
      if (!moved && Math.abs(x - startX) < DRAG_THRESHOLD_PX) return;
      moved = true;
      const now = this.xToTime(x);

      if (pan) {
        const delta = now - startTime;
        this.setWindow(winStart - delta, winStart - delta + this.span);
        return;
      }
      if (!this.opts.selectable) return;

      if (grabbed === 'a') this._emitSelect(clamp(now), original.b, false);
      else if (grabbed === 'b') this._emitSelect(original.a, clamp(now), false);
      else if (grabbed === 'move') {
        const delta = now - startTime;
        const length = original.b - original.a;
        let a = clamp(original.a + delta);
        if (a + length > this.bounds.end) a = this.bounds.end - length;
        this._emitSelect(a, a + length, false);
      } else {
        creating = true;
        this._emitSelect(clamp(startTime), clamp(now), false);
      }
    };

    const onUp = () => {
      this.el.releasePointerCapture(event.pointerId);
      this.el.removeEventListener('pointermove', onMove);
      this.el.removeEventListener('pointerup', onUp);
      this.el.removeEventListener('pointercancel', onUp);
      this.nodes.handleA?.classList.remove('dragging');
      this.nodes.handleB?.classList.remove('dragging');
      if (!moved) {
        // A click, not a drag: seek. Inside an existing selection this is how
        // you audition from a point without losing the span you just set.
        if (this.opts.onSeek) this.opts.onSeek(clamp(startTime));
      } else if (!pan && this.selection && this.opts.onSelect) {
        this.opts.onSelect(this.selection.a, this.selection.b, true);
        if (creating && this.opts.onSeek) this.opts.onSeek(Math.min(this.selection.a, this.selection.b));
      }
    };

    this.el.addEventListener('pointermove', onMove);
    this.el.addEventListener('pointerup', onUp);
    this.el.addEventListener('pointercancel', onUp);
  }

  _emitSelect(a, b, done) {
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    this.setSelection(lo, hi);
    if (this.opts.onSelect) this.opts.onSelect(lo, hi, done);
  }

  _onWheel(event) {
    event.preventDefault();
    const rect = this.el.getBoundingClientRect();
    const anchor = this.xToTime(event.clientX - rect.left);
    const factor = Math.exp(event.deltaY * 0.0015);
    const span = Math.max(0.25, Math.min(this.span * factor, this.bounds.end - this.bounds.start));
    const ratio = (anchor - this.win.start) / this.span;
    this.setWindow(anchor - ratio * span, anchor - ratio * span + span);
  }
}
