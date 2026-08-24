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
   *   snap(t) => t          – applied to pointer-placed edge times (beat snap)
   *   onBeatClick(t)        – a beat marker was clicked: make it the downbeat
   *   onFormClick(t)        – shift-click on a marker: the form starts here
   *   onWindowDrag(start,w) – the overview's window box was slid
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
    this.beatsData = null;
    this._beatsPainted = false;
    this.barSet = null;
    this.chorusSet = null;

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

  /* The derived bar grid from /api/tracks/{id}/beats, or null:
     {beats, implied, bars: [[time, number]], chorus_bars, sections}.
     All times are track-global seconds. */
  setBeats(grid) {
    this.beatsData = grid;
    this.barSet = grid ? new Map(grid.bars.map(([t, n]) => [t, n])) : null;
    this.chorusSet = grid ? new Set(grid.chorus_bars || []) : null;
    this.draw();
  }

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

    if (this.beatsData) this._drawBeats(width, height, style);

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

  /* The bar grid transcription will quantize against, drawn so the eye can
     check it against the audio's own transients.

     Full-height lines appear ONLY at bar starts — the beat tracker's detected
     downbeats are noise (open-issue #5) and drawing a line at each of them was
     unreadable. Ordinary beats get a baseline tick; beats the repair pass had
     to invent are hollow, so the software's guesses are never mistaken for
     detections. Chorus starts get a brighter line, since a jazz solo is a whole
     number of choruses. Density-guarded throughout: at zooms where marks would
     be sub-pixel confetti they simply don't draw. */
  _drawBeats(width, height, style) {
    const grid = this.beatsData;
    const beats = grid.beats || [];
    if (beats.length < 2) return;
    const ctx = this.ctx;
    const beatColor = style.getPropertyValue('--beat').trim() || '#5f6c8c';
    const downColor = style.getPropertyValue('--downbeat').trim() || '#9fb4ff';
    const chorusColor = style.getPropertyValue('--chorus').trim() || '#ffd479';
    const pxPerSec = width / this.span;
    const beatPx = pxPerSec * ((beats[beats.length - 1] - beats[0]) / (beats.length - 1));
    const barPx = beatPx * (grid.pulses_per_bar || 4);
    const visible = (t) => t >= this.win.start && t <= this.win.end;
    // Remembered so clicking can only ever hit a marker that was drawn.
    this._beatsPainted = beatPx >= 5;

    // Time no section covers has no steady pulse: shade it and draw no bars.
    for (const gap of this._rubatoGaps(grid)) {
      const x0 = this.timeToX(Math.max(gap[0], this.win.start));
      const x1 = this.timeToX(Math.min(gap[1], this.win.end));
      if (x1 <= x0) continue;
      ctx.fillStyle = 'rgba(120, 128, 150, 0.13)';
      ctx.fillRect(x0, 0, x1 - x0, height);
    }

    if (beatPx >= 5) {
      for (let i = 0; i < beats.length; i++) {
        const t = beats[i];
        if (!visible(t) || this.barSet.has(t)) continue;
        const x = this.timeToX(t) - 0.5;
        if (grid.implied && grid.implied[i]) {
          ctx.globalAlpha = 0.55;
          ctx.fillStyle = beatColor;
          ctx.fillRect(x, height - 6, 1, 2);   // stub: a beat we inferred
          ctx.globalAlpha = 1;
        } else {
          ctx.fillStyle = beatColor;
          ctx.fillRect(x, height - 8, 1, 6);
        }
      }
    }

    if (barPx >= 4) {
      const labelled = barPx >= 44;
      ctx.font = '9px ui-monospace, Menlo, Consolas, monospace';
      ctx.textAlign = 'left';
      for (const [t, number] of this.barSet) {
        if (!visible(t)) continue;
        const x = this.timeToX(t);
        const chorus = this.chorusSet.has(t);
        // Bars before bar 1 are an intro or a vamp: part of the recording, not
        // part of the form. Drawn faintly and left unnumbered, so the run of
        // numbers begins exactly where the tune does.
        const preForm = number < 1;
        ctx.globalAlpha = preForm ? 0.07 : chorus ? 0.5 : 0.16;
        ctx.fillStyle = chorus ? chorusColor : downColor;
        ctx.fillRect(x - 0.5, 0, chorus ? 1.5 : 1, height);
        ctx.globalAlpha = preForm ? 0.4 : 1;
        ctx.beginPath();
        ctx.arc(x, height - 7, chorus ? 4 : 3, 0, 2 * Math.PI);
        ctx.fill();
        ctx.globalAlpha = 1;
        if (labelled && !preForm) {
          ctx.fillStyle = chorus ? chorusColor : downColor;
          ctx.fillText(String(number), x + 6, height - 4);
        }
      }
    }
  }

  /* Stretches between metrical sections — free time, drawn without bars. */
  _rubatoGaps(grid) {
    const sections = grid.sections || [];
    if (!sections.length) return [];
    const gaps = [];
    if (sections[0].start > this.bounds.start) gaps.push([this.bounds.start, sections[0].start]);
    for (let i = 1; i < sections.length; i++) {
      gaps.push([sections[i - 1].end, sections[i].start]);
    }
    const last = sections[sections.length - 1];
    if (last.end < this.bounds.end) gaps.push([last.end, this.bounds.end]);
    return gaps;
  }

  /* Track time of the beat nearest x, when it is close enough to have been
     aimed at — used for click-to-set-the-downbeat. The radius is generous
     because the strip is only the bottom few pixels: a click that lands there
     was almost certainly aimed at a marker, and ordinary seeking clicks happen
     everywhere above it. */
  beatNear(clientX, clientY, maxPx = 12) {
    const grid = this.beatsData;
    if (!grid || !grid.beats.length) return null;
    // Only where the dots are actually on screen. Zoomed out they are hidden
    // as sub-pixel confetti, and letting a click land on an invisible marker
    // silently re-phases the whole tune onto a beat the user never saw.
    if (!this._beatsPainted) return null;
    const rect = this.el.getBoundingClientRect();
    if (clientY - rect.top < rect.height - 18) return null;   // marker strip only
    const x = clientX - rect.left;
    let best = null;
    let bestPx = maxPx;
    for (const t of grid.beats) {
      const distance = Math.abs(this.timeToX(t) - x);
      if (distance <= bestPx) { bestPx = distance; best = t; }
    }
    return best;
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
    if (this.opts.onBeatClick) {
      this.el.addEventListener('pointermove', (event) => {
        if (event.buttons) return;   // mid-drag; leave the cursor alone
        const over = this.beatNear(event.clientX, event.clientY) !== null;
        this.el.classList.toggle('over-beat', over);
      });
      this.el.addEventListener('pointerleave', () => this.el.classList.remove('over-beat'));
    }
    if (this.opts.onWindow) {
      this.el.addEventListener('wheel', (event) => this._onWheel(event), { passive: false });
    }
  }

  /* The overview's window box is a scrubber for the detail view: grabbing it
     and sliding is the natural "move the music left and right" gesture, and it
     is the one place where where-you-are and where-you-could-go are both
     visible at once. */
  _hitWindowBox(x) {
    if (!this.windowBox || !this.opts.onWindowDrag) return false;
    const x0 = this.timeToX(this.windowBox.start);
    const x1 = this.timeToX(this.windowBox.end);
    return x >= x0 - 3 && x <= x1 + 3;
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
    const slide = !pan && this._hitWindowBox(startX);
    const grabbed = pan || slide ? null : this._hitHandle(startX);
    const windowAtStart = this.windowBox ? { ...this.windowBox } : null;

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
    // Snap applies only to the endpoint(s) the pointer is actually placing —
    // never to the far edge, which may have been nudged off-grid on purpose.
    const snap = this.opts.snap ?? ((t) => t);

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
      if (slide) {
        const delta = now - startTime;
        const width = windowAtStart.end - windowAtStart.start;
        this.opts.onWindowDrag(windowAtStart.start + delta, width);
        return;
      }
      if (!this.opts.selectable) return;

      if (grabbed === 'a') this._emitSelect(snap(clamp(now)), original.b, false);
      else if (grabbed === 'b') this._emitSelect(original.a, snap(clamp(now)), false);
      else if (grabbed === 'move') {
        const delta = now - startTime;
        const length = original.b - original.a;
        // Moving snaps the leading edge and preserves the length exactly —
        // snapping both ends independently would quietly resize the span.
        let a = snap(clamp(original.a + delta));
        if (a + length > this.bounds.end) a = this.bounds.end - length;
        this._emitSelect(a, a + length, false);
      } else {
        creating = true;
        this._emitSelect(snap(clamp(startTime)), snap(clamp(now)), false);
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
        // A click on a beat marker re-phases the bar grid; anywhere else it
        // seeks. Restricting it to the marker strip keeps the ordinary click
        // — audition from here — unchanged.
        const marker = this.opts.onBeatClick
          ? this.beatNear(event.clientX, event.clientY)
          : null;
        if (marker !== null && event.shiftKey && this.opts.onFormClick) {
          this.opts.onFormClick(marker);
        } else if (marker !== null) {
          this.opts.onBeatClick(marker);
        } else if (this.opts.onSeek) {
          this.opts.onSeek(clamp(startTime));
        }
      } else if (!pan && !slide && this.selection && this.opts.onSelect) {
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
    // Sideways intent — a trackpad swipe or shift+wheel — slides the view;
    // plain vertical wheel zooms.
    if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      const amount = (event.shiftKey ? event.deltaY : event.deltaX) * 0.0015 * this.span;
      this.setWindow(this.win.start + amount, this.win.end + amount);
      return;
    }
    const rect = this.el.getBoundingClientRect();
    const anchor = this.xToTime(event.clientX - rect.left);
    const factor = Math.exp(event.deltaY * 0.0015);
    const span = Math.max(0.25, Math.min(this.span * factor, this.bounds.end - this.bounds.start));
    const ratio = (anchor - this.win.start) / this.span;
    this.setWindow(anchor - ratio * span, anchor - ratio * span + span);
  }
}
