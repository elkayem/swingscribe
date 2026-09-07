/* The review screen's piano roll and diagnostic lanes.
 *
 * A note list is a picture; a piano roll wired to the frame trace is a
 * diagnostic. This draws the transcribed notes over the same bar grid the
 * selection screen uses — a wrong downbeat is invisible in a list and obvious
 * the moment notes sit against bar lines — and, beneath it, the per-frame
 * evidence: the raw CREPE f0 against the gated-and-smoothed pitch, and the two
 * gates (periodicity, energy) that decided which frames survived.
 *
 * All times are track-global seconds. The data covers one span; `view` is the
 * slice of it currently drawn, which zoom and pan move around inside the span
 * without any of the note or frame maths knowing that zoom exists.
 */

const PITCH_PAD = 2; // semitones of headroom above/below the note range
const MIN_PITCH_SPAN = 14; // never zoom the pitch axis tighter than this

// How far a click may miss a note and still count. Measured in PIXELS against
// the drawn rectangle, not in semitones: a solo spanning four octaves draws
// each note about four pixels tall, so a semitone tolerance means something
// completely different at one zoom than another. A few pixels of padding makes
// a thin note comfortable to hit while leaving the empty space above and below
// it genuinely empty — which matters once a click can erase.
const CLICK_SLACK_S = 0.05;
const HIT_PAD_PX = 4;

const MIN_VIEW_S = 0.4;   // tightest zoom: about two notes at a bebop tempo
const DRAG_SLOP_PX = 4;   // movement below this is a click, not a drag
const FOLLOW_MARGIN = 0.1; // where a scrolled-to playhead lands, as a fraction

/* The four ways a note can come out of the alignment. `matched` and `wrong`
   are pairs and get drawn twice — our note filled, the notated one outlined
   over it — so a wrong note reads as an interval, which is the whole point:
   one semitone is a scoop the transcriber chose not to write, fifteen is a
   different instrument. */
export const CLASSES = ['matched', 'wrong', 'invented', 'missed'];
const CLASS_VAR = {
  matched: '--gt-matched',
  wrong: '--gt-wrong',
  invented: '--gt-invented',
  missed: '--gt-missed',
};
const CLASS_FALLBACK = {
  matched: '#56cfc0',
  wrong: '#f0a848',
  invented: '#e2666b',
  missed: '#9f8cff',
};

export class PianoRoll {
  constructor(rollEl, f0El, gateEl, opts = {}) {
    this.rollEl = rollEl;
    this.f0El = f0El;
    this.gateEl = gateEl;
    this.opts = opts;

    this.roll = this._attach(rollEl);
    this.f0 = this._attach(f0El);
    this.gate = this._attach(gateEl);

    // `span` is the transcribed extent and never moves; `view` is the slice
    // currently drawn. Keeping them apart is what lets the roll zoom without
    // any of the note or frame maths knowing about it.
    this.span = { a: 0, b: 1 };
    this.view = { a: 0, b: 1 };
    this.notes = [];
    this.second = [];
    this.showSecond = true;
    // Everything the piano model heard that the line does not hold, drawn
    // faint under the line; `added` are the ones the listener switched on.
    // Piano only — the server sends an empty pool for a horn.
    this.candidates = [];
    this.added = new Set();
    this.diag = null;
    this.beats = null;
    this.selected = -1;
    this.playhead = null;
    this.ground = null;                        // the aligned hand transcription, if any
    this.visible = new Set(CLASSES);           // which alignment classes to draw
    this.silenced = new Set();                 // note indices marked "not the solo"
    this.tool = 'inspect';                     // inspect | erase — what a click and a drag mean
    this._band = null;                         // rubber-band rectangle while dragging

    this._drag = null;
    for (const el of [rollEl, f0El, gateEl]) {
      el.addEventListener('pointerdown', (e) => this._onPointerDown(e, el));
      el.addEventListener('pointermove', (e) => this._onPointerMove(e));
      el.addEventListener('pointerup', (e) => this._onPointerUp(e, el));
      el.addEventListener('pointercancel', () => { this._drag = null; });
      // The same gestures as the waveforms: wheel zooms about the pointer,
      // shift-wheel (or a trackpad's sideways swipe) pans. The roll takes the
      // wheel for itself, so the page does not scroll while the pointer is
      // over it — the price of one rule that holds on every view.
      el.addEventListener('wheel', (e) => this._onWheel(e, el), { passive: false });
    }
    this._observer = new ResizeObserver(() => this.draw());
    this._observer.observe(rollEl);
  }

  _attach(el) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    el.appendChild(canvas);
    return { el, canvas, ctx };
  }

  setData(span, review, beats) {
    // Redrawing the same span (the bar grid arriving, say) must not throw away
    // a zoom the user set; a genuinely new span has nothing to preserve.
    const sameSpan = this.span.a === span.a && this.span.b === span.b;
    this.span = span;
    if (!sameSpan) this.view = { ...span };
    this.notes = review ? review.notes : [];
    // The piano second-voice overlay: the rest of the top two notes the oracle
    // heard. Held apart from `notes` for the same reason the server holds it
    // apart -- everything that scores, exports or erases treats `notes` as the
    // transcription, and this is a suggestion, not a claim.
    this.second = (review && review.second_voice) || [];
    this.candidates = (review && review.candidates) || [];
    this.diag = review ? review.diagnostics : null;
    this.beats = beats;
    this.selected = -1;
    this._range();
    this.draw();
    if (this.opts.onView) this.opts.onView(this.view, this.spanWidth);
  }

  /* Show or hide what the piano model offers (the candidate pool, and the
     legacy second-voice overlay). Switched-on candidates stay drawn: they
     are part of the transcription now. */
  setShowSecondVoice(on) {
    this.showSecond = !!on;
    this._range();
    this.draw();
  }

  /* Candidate indices the listener has switched on. */
  setAdded(indices) {
    this.added = new Set(indices);
    this._range();
    this.draw();
  }

  /* The aligned hand transcription (or null to drop it). */
  setGroundTruth(ground) {
    this.ground = ground;
    this._range();
    this.draw();
  }

  setVisibleClasses(classes) {
    this.visible = new Set(classes);
    this.draw();
  }

  /* Silenced notes stay on the roll, struck out. Removing them would hide the
     one thing you need to judge an erasure: what you cut. */
  setSilenced(indices) {
    this.silenced = new Set(indices);
    this.draw();
  }

  setTool(tool) {
    this.tool = tool;
    this._band = null;
    this.rollEl.classList.toggle('erasing', tool === 'erase');
    this.draw();
  }

  /* Pitch axis auto-ranges to everything drawn, with headroom, floored to a
     minimum span so a monophonic line does not render as one fat band. The
     notated notes are included deliberately: an error of fifteen semitones is
     exactly the one worth seeing, and it is the one an axis fitted to our own
     notes would push off the top or bottom of the canvas. */
  _range() {
    const pitches = this.notes.map((n) => n.pitch);
    if (this.showSecond) for (const n of this.second) pitches.push(n.pitch);
    // The pool spans the whole keyboard (the left hand is in it), so it only
    // widens the axis while it is shown; an added note is always in range.
    this.candidates.forEach((n, i) => {
      if (this.showSecond || this.added.has(i)) pitches.push(n.pitch);
    });
    if (this.ground) for (const n of this.ground.reference_notes) pitches.push(n.pitch);
    if (!pitches.length) {
      this.pitchLo = 48;
      this.pitchHi = 72;
      return;
    }
    let lo = Math.min(...pitches);
    let hi = Math.max(...pitches);
    const short = MIN_PITCH_SPAN - (hi - lo);
    if (short > 0) {
      lo -= Math.floor(short / 2);
      hi += Math.ceil(short / 2);
    }
    this.pitchLo = lo - PITCH_PAD;
    this.pitchHi = hi + PITCH_PAD;
  }

  classOf(index) {
    return this.ground ? this.ground.estimate_class[index] : null;
  }

  _classColor(name) {
    return this._css(CLASS_VAR[name], CLASS_FALLBACK[name]);
  }

  setPlayhead(t) {
    this.playhead = t;
    this.draw();
  }

  get width() {
    return this.rollEl.clientWidth;
  }

  timeToX(t, width) {
    const w = width ?? this.width;
    return ((t - this.view.a) / Math.max(1e-6, this.view.b - this.view.a)) * w;
  }

  xToTime(x, width) {
    const w = width ?? this.width;
    return this.view.a + (x / Math.max(1, w)) * (this.view.b - this.view.a);
  }

  get viewWidth() {
    return this.view.b - this.view.a;
  }

  get spanWidth() {
    return this.span.b - this.span.a;
  }

  /* Move and resize the drawn window, clamped inside the span. Everything
     else — zoom, pan, follow — goes through here so the clamp lives once. */
  setWindow(a, b) {
    const width = Math.min(this.spanWidth, Math.max(MIN_VIEW_S, b - a));
    const lo = Math.max(this.span.a, Math.min(a, this.span.b - width));
    this.view = { a: lo, b: lo + width };
    this.draw();
    if (this.opts.onView) this.opts.onView(this.view, this.spanWidth);
  }

  /* Zoom about a fixed time — the pointer under a scroll, or the playhead
     under a button — so the thing being looked at stays put. */
  zoomBy(factor, focus = null) {
    const width = this.viewWidth;
    const next = Math.min(this.spanWidth, Math.max(MIN_VIEW_S, width * factor));
    const at = focus === null ? this.view.a + width / 2 : focus;
    const ratio = Math.min(1, Math.max(0, (at - this.view.a) / Math.max(1e-6, width)));
    this.setWindow(at - ratio * next, at - ratio * next + next);
  }

  fit() {
    this.setWindow(this.span.a, this.span.b);
  }

  /* Keep a moving playhead on screen. Scrolls a whole window at a time rather
     than tracking continuously: a view that slides under a stationary line is
     far harder to read than one that jumps when the line reaches the edge. */
  follow(t) {
    if (this.viewWidth >= this.spanWidth) return;
    const width = this.viewWidth;
    if (t >= this.view.a && t <= this.view.b - width * FOLLOW_MARGIN) return;
    const lo = t - width * FOLLOW_MARGIN;
    this.setWindow(lo, lo + width);
  }

  noteHeight(height) {
    return Math.max(3, height / (this.pitchHi - this.pitchLo));
  }

  /* The rubber band, plus how many notes it currently holds — a sweep over
     left-hand comping is worth confirming before it happens. */
  _drawBand(ctx) {
    const band = this._band;
    if (!band) return;
    const x = Math.min(band.x0, band.x1);
    const y = Math.min(band.y0, band.y1);
    const w = Math.abs(band.x1 - band.x0);
    const h = Math.abs(band.y1 - band.y0);
    const color = this._css(band.restoring ? '--lead' : '--accent', '#f0a848');
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.12;
    ctx.fillRect(x, y, w, h);
    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, w, h);
    const count = this.notesInBand(band).length;
    if (count) {
      ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
      ctx.fillStyle = color;
      ctx.globalAlpha = 1;
      ctx.fillText(`${count} note${count === 1 ? '' : 's'}`, x + 4, Math.max(11, y - 3));
    }
    ctx.globalAlpha = 1;
  }

  /* Notes whose drawn rectangle intersects the band. Comparing what is on
     screen rather than time and pitch ranges means the selection is exactly
     what the box looks like it covers, at any zoom. */
  notesInBand(band) {
    const w = this.width;
    const h = this.roll.el.clientHeight;
    const noteH = this.noteHeight(h);
    const left = Math.min(band.x0, band.x1);
    const right = Math.max(band.x0, band.x1);
    const top = Math.min(band.y0, band.y1);
    const bottom = Math.max(band.y0, band.y1);
    const hits = [];
    this.notes.forEach((n, i) => {
      const kind = this.classOf(i);
      if (kind && !this.visible.has(kind)) return;
      const x0 = this.timeToX(n.onset, w);
      const x1 = x0 + Math.max(2, this.timeToX(n.onset + n.duration, w) - x0);
      if (x1 < left || x0 > right) return;
      const centre = this.pitchToY(n.pitch, h);
      if (centre + noteH / 2 < top || centre - noteH / 2 > bottom) return;
      hits.push(i);
    });
    return hits;
  }

  pitchToY(pitch, height) {
    const range = Math.max(1, this.pitchHi - this.pitchLo);
    return height - ((pitch - this.pitchLo + 0.5) / range) * height;
  }

  _fit(view, cssHeight) {
    const dpr = window.devicePixelRatio || 1;
    const w = view.el.clientWidth;
    view.el.style.height = `${cssHeight}px`;
    if (view.canvas.width !== Math.round(w * dpr) || view.canvas.height !== Math.round(cssHeight * dpr)) {
      view.canvas.width = Math.round(w * dpr);
      view.canvas.height = Math.round(cssHeight * dpr);
    }
    view.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    view.ctx.clearRect(0, 0, w, cssHeight);
    return { w, h: cssHeight };
  }

  _css(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  }

  draw() {
    if (!this.width) return;
    this._drawRoll();
    this._drawF0();
    this._drawGate();
  }

  _drawBarsBehind(ctx, w, h) {
    if (!this.beats) return;
    const downColor = this._css('--downbeat', '#9fb4ff');
    const chorusColor = this._css('--chorus', '#ffd479');
    const chorus = new Set(this.beats.chorus_bars || []);
    for (const [t, number] of this.beats.bars) {
      if (t < this.view.a || t > this.view.b) continue;
      const x = this.timeToX(t, w);
      const isChorus = chorus.has(t);
      ctx.globalAlpha = number < 1 ? 0.05 : isChorus ? 0.35 : 0.12;
      ctx.fillStyle = isChorus ? chorusColor : downColor;
      ctx.fillRect(x - 0.5, 0, isChorus ? 1.5 : 1, h);
      ctx.globalAlpha = 1;
    }
  }

  /* The beat strip along the roll's bottom edge, drawn the way the waveforms
     draw theirs (waveform.js _drawBeats) so the grid reads the same on every
     view: a tick per beat, a stub for a beat the repair pass inferred, a dot
     and a number at each bar, a larger gold dot at a chorus start. Bars
     before bar 1 are faint and unnumbered. Density-guarded the same way. */
  _drawBeatStrip(ctx, w, h) {
    const grid = this.beats;
    if (!grid) return;
    const beats = grid.beats || [];
    if (beats.length < 2) return;
    const beatColor = this._css('--beat', '#5f6c8c');
    const downColor = this._css('--downbeat', '#9fb4ff');
    const chorusColor = this._css('--chorus', '#ffd479');
    const chorus = new Set(grid.chorus_bars || []);
    const barSet = new Map(grid.bars.map(([t, n]) => [t, n]));
    const pxPerSec = w / Math.max(1e-6, this.viewWidth);
    const beatPx = pxPerSec * ((beats[beats.length - 1] - beats[0]) / (beats.length - 1));
    const barPx = beatPx * (grid.pulses_per_bar || 4);
    const visible = (t) => t >= this.view.a && t <= this.view.b;

    if (beatPx >= 5) {
      for (let i = 0; i < beats.length; i++) {
        const t = beats[i];
        if (!visible(t) || barSet.has(t)) continue;
        const x = this.timeToX(t, w) - 0.5;
        ctx.fillStyle = beatColor;
        if (grid.implied && grid.implied[i]) {
          ctx.globalAlpha = 0.55;
          ctx.fillRect(x, h - 6, 1, 2);
          ctx.globalAlpha = 1;
        } else {
          ctx.fillRect(x, h - 8, 1, 6);
        }
      }
    }

    if (barPx >= 4) {
      const labelled = barPx >= 44;
      ctx.font = '9px ui-monospace, Menlo, Consolas, monospace';
      ctx.textAlign = 'left';
      for (const [t, number] of barSet) {
        if (!visible(t)) continue;
        const x = this.timeToX(t, w);
        const isChorus = chorus.has(t);
        const preForm = number < 1;
        ctx.fillStyle = isChorus ? chorusColor : downColor;
        ctx.globalAlpha = preForm ? 0.4 : 1;
        ctx.beginPath();
        ctx.arc(x, h - 7, isChorus ? 4 : 3, 0, 2 * Math.PI);
        ctx.fill();
        if (labelled && !preForm) ctx.fillText(String(number), x + 6, h - 4);
        ctx.globalAlpha = 1;
      }
    }
  }

  _drawRoll() {
    const { w, h } = this._fit(this.roll, 220);
    const ctx = this.roll.ctx;

    // Pitch-class guide rows: shade the naturals so octaves are readable.
    for (let p = Math.ceil(this.pitchLo); p <= this.pitchHi; p++) {
      const y = this.pitchToY(p, h);
      const isC = p % 12 === 0;
      ctx.fillStyle = isC ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.02)';
      ctx.fillRect(0, y - (h / (this.pitchHi - this.pitchLo)) / 2, w, 1);
      if (isC) {
        ctx.fillStyle = 'rgba(255,255,255,0.3)';
        ctx.font = '9px ui-monospace, Menlo, Consolas, monospace';
        ctx.fillText(`C${Math.floor(p / 12) - 1}`, 2, y - 2);
      }
    }

    this._drawBarsBehind(ctx, w, h);

    // Onset ticks: candidate note-split points, so a note broken in two can be
    // seen sitting on one.
    if (this.diag) {
      ctx.strokeStyle = this._css('--onset', '#e2666b');
      // Onset ticks are red, and so are invented notes. They are never
      // confusable in shape — full-height hairlines against short horizontal
      // bars — but a field of them drowns the overlay, and with a hand
      // transcription loaded the question on screen is no longer "what split
      // this note?". So they retreat rather than disappear.
      ctx.globalAlpha = this.ground ? 0.14 : 0.4;
      ctx.beginPath();
      for (const t of this.diag.onsets) {
        if (t < this.view.a || t > this.view.b) continue;
        const x = this.timeToX(t, w);
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    const noteH = this.noteHeight(h);

    // The candidate pool, drawn first so the line sits on top of what is
    // merely offered. Velocity shades it: the model's loud notes are
    // the ones most likely to be the line's missing member. A switched-on
    // candidate is filled like a line note, in its own colour, because it IS
    // part of the transcription now and will be on the page.
    if (this.candidates.length) {
      ctx.save();
      this.candidates.forEach((n, i) => {
        const on = this.added.has(i);
        if (!on && !this.showSecond) return;
        const x0 = this.timeToX(n.onset, w);
        const x1 = this.timeToX(n.onset + n.duration, w);
        if (x1 < 0 || x0 > w) return;
        const width = Math.max(2, x1 - x0);
        const y = this.pitchToY(n.pitch, h) - noteH / 2;
        if (on) {
          ctx.globalAlpha = 0.95;
          ctx.fillStyle = this._css('--added', '#9fd66a');
          ctx.fillRect(x0, y, width, noteH - 1);
        } else {
          // Solid enough to find at any velocity -- the first version, grey
          // at a quarter alpha, could not be seen -- with the loud ones
          // still the brightest, and an outline so a soft one keeps an edge.
          const color = this._css('--candidate', '#ee86e2');
          ctx.fillStyle = color;
          ctx.globalAlpha = 0.45 + 0.45 * Math.min(1, Math.max(0, n.confidence));
          ctx.fillRect(x0, y, width, noteH - 1);
          ctx.globalAlpha = 0.9;
          ctx.strokeStyle = color;
          ctx.lineWidth = 1;
          ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(1, width - 1), Math.max(1, noteH - 2));
        }
      });
      ctx.restore();
    }

    // Drawn first, so the line always sits on top of what is merely offered,
    // and outlined rather than filled: it must never be mistaken for a note
    // we are claiming was played.
    if (this.showSecond && this.second.length) {
      ctx.save();
      ctx.strokeStyle = this._css('--second-voice', '#8a7fd0');
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.75;
      for (const n of this.second) {
        const x0 = this.timeToX(n.onset, w);
        const x1 = this.timeToX(n.onset + n.duration, w);
        const y = this.pitchToY(n.pitch, h) - noteH / 2;
        ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(2, x1 - x0) - 1, noteH - 2);
      }
      ctx.restore();
    }

    this.notes.forEach((n, i) => {
      const kind = this.classOf(i);
      if (kind && !this.visible.has(kind)) return;
      const x0 = this.timeToX(n.onset, w);
      const x1 = this.timeToX(n.onset + n.duration, w);
      const width = Math.max(2, x1 - x0);
      const centre = this.pitchToY(n.pitch, h);
      const y = centre - noteH / 2;
      const selected = i === this.selected;
      const cut = this.silenced.has(i);
      // Confidence drives fill: a faint note is one the transcriber was unsure
      // of, which is exactly what you want to eyeball.
      const alpha = 0.35 + 0.6 * Math.min(1, Math.max(0, n.confidence));
      ctx.globalAlpha = cut ? 0.22 : selected ? 1 : alpha;
      ctx.fillStyle = selected
        ? this._css('--accent', '#f0a848')
        : kind
          ? this._classColor(kind)
          : this._css('--lead', '#56cfc0');
      ctx.fillRect(x0, y, width, noteH - 1);
      ctx.globalAlpha = 1;
      if (cut) {
        // A line through the middle, in the text colour rather than a fifth
        // hue: "struck out" has to read the same whatever the note's
        // alignment class has coloured it. Widened a little so a two-pixel
        // note still shows the strike.
        const strike = Math.max(width, 5);
        ctx.strokeStyle = this._css('--text', '#e6e8ef');
        ctx.globalAlpha = 0.85;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x0 - (strike - width) / 2, Math.round(centre) + 0.5);
        ctx.lineTo(x0 - (strike - width) / 2 + strike, Math.round(centre) + 0.5);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (selected) {
        ctx.strokeStyle = this._css('--accent', '#f0a848');
        ctx.strokeRect(x0 - 1, y - 1, width + 2, noteH + 1);
      }
    });

    this._drawGroundTruth(ctx, w, h, noteH);
    this._drawBeatStrip(ctx, w, h);
    this._drawBand(ctx);
    this._drawPlayhead(ctx, w, h);
  }

  /* The notated notes, outlined over ours.
   *
   * A matched pair is our filled note wearing its notated outline exactly —
   * which is also the visual admission that the two agree horizontally BY
   * CONSTRUCTION: an aligned notated note is placed at our note's onset, so
   * nothing here is evidence about timing (see ground_truth.py). A wrong note
   * puts the outline at a different height with a stalk joining the two, so
   * the error reads as an interval; a missed note is an outline with nothing
   * underneath it.
   */
  _drawGroundTruth(ctx, w, h, noteH) {
    if (!this.ground) return;
    const outlineH = Math.max(3, noteH - 2);
    for (const note of this.ground.reference_notes) {
      if (!this.visible.has(note.cls)) continue;
      const x0 = this.timeToX(note.x, w);
      const x1 = this.timeToX(note.x + note.duration, w);
      if (x1 < 0 || x0 > w) continue;
      const y = this.pitchToY(note.pitch, h) - outlineH / 2;
      const width = Math.max(2, x1 - x0);
      const color = this._classColor(note.cls);

      if (note.cls === 'wrong' && note.partner !== null) {
        // Stalk from what we produced to what was written, at our onset.
        const ours = this.notes[note.partner];
        if (ours) {
          ctx.strokeStyle = color;
          ctx.globalAlpha = 0.5;
          ctx.beginPath();
          ctx.moveTo(x0 + 1, this.pitchToY(ours.pitch, h));
          ctx.lineTo(x0 + 1, this.pitchToY(note.pitch, h));
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      }
      if (note.cls === 'missed') {
        // Nothing of ours underneath, so a bare outline would read as faint
        // rather than absent. A wash inside makes "we never played this" the
        // loud thing it should be.
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.22;
        ctx.fillRect(x0, y, width, outlineH);
        ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.globalAlpha = note.cls === 'matched' ? 0.55 : 0.9;
      ctx.strokeRect(x0 + 0.5, y + 0.5, width - 1, outlineH - 1);
      ctx.globalAlpha = 1;
    }
  }

  _drawF0() {
    const { w, h } = this._fit(this.f0, 60);
    const ctx = this.f0.ctx;
    if (!this.diag) return;
    const { f0_midi, pitch, hop_s, start } = this.diag;

    // Same pitch axis as the roll, so the two line up vertically.
    const line = (series, color, alpha) => {
      ctx.strokeStyle = color;
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      let pen = false;
      series.forEach((v, i) => {
        if (v === null) {
          pen = false;
          return;
        }
        const x = this.timeToX(start + i * hop_s, w);
        if (x < 0 || x > w) {
          pen = false;
          return;
        }
        const y = this.pitchToY(v, h);
        if (pen) ctx.lineTo(x, y);
        else ctx.moveTo(x, y);
        pen = true;
      });
      ctx.stroke();
      ctx.globalAlpha = 1;
    };
    // Raw first (dim), kept on top (bright): the gaps in "kept" against a
    // continuous "raw" are exactly the frames gating removed.
    line(f0_midi, this._css('--wave-lit', '#97a1bb'), 0.4);
    line(pitch, this._css('--lead', '#56cfc0'), 0.95);
    this._drawPlayhead(ctx, w, h);
  }

  _drawGate() {
    const { w, h } = this._fit(this.gate, 46);
    const ctx = this.gate.ctx;
    if (!this.diag) return;
    const { periodicity, energy_ok, hop_s, start } = this.diag;

    // Energy-gate failures shaded first, behind the periodicity line.
    ctx.fillStyle = this._css('--danger', '#e2666b');
    ctx.globalAlpha = 0.12;
    energy_ok.forEach((ok, i) => {
      if (ok) return;
      const x = this.timeToX(start + i * hop_s, w);
      if (x < 0 || x > w) return;
      ctx.fillRect(x, 0, Math.max(1, w / periodicity.length), h);
    });
    ctx.globalAlpha = 1;

    // Voicing threshold line.
    const thresh = this.opts.voicingThreshold ?? 0.5;
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(0, h - thresh * h);
    ctx.lineTo(w, h - thresh * h);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = this._css('--downbeat', '#9fb4ff');
    ctx.beginPath();
    let pen = false;
    periodicity.forEach((v, i) => {
      const x = this.timeToX(start + i * hop_s, w);
      if (x < 0 || x > w) {
        pen = false;
        return;
      }
      const y = h - Math.min(1, Math.max(0, v)) * h;
      if (pen) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      pen = true;
    });
    ctx.stroke();
    this._drawPlayhead(ctx, w, h);
  }

  _drawPlayhead(ctx, w, h) {
    if (this.playhead === null) return;
    const x = this.timeToX(this.playhead, w);
    if (x < 0 || x > w) return;
    ctx.strokeStyle = '#fff';
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  /* Frame indices spanned by a note, for the inspector's "why". */
  framesFor(note) {
    if (!this.diag) return [];
    const { hop_s, start, frames } = this.diag;
    const first = Math.max(0, Math.round((note.onset - start) / hop_s));
    const last = Math.min(frames - 1, Math.round((note.onset + note.duration - start) / hop_s));
    const out = [];
    for (let i = first; i <= last; i++) out.push(i);
    return out;
  }

  /* Pointer down starts something that is not yet a click: drag past a few
     pixels and it pans, release without moving and it seeks. Deciding on
     release is what lets one gesture serve both without a modifier. */
  _onPointerDown(event, el) {
    if (event.button !== 0) return;
    // Capture keeps a pan alive when the pointer leaves the strip, which at
    // 46px tall is most of them. It throws for a pointer id the browser does
    // not know, and losing the whole gesture to that would be silly.
    try { el.setPointerCapture(event.pointerId); } catch { /* not capturable */ }
    const rect = el.getBoundingClientRect();
    // The erase tool takes the drag for the rubber band, so panning moves to
    // shift-drag while it is selected — one gesture each, and shift is already
    // the zoom modifier on the wheel.
    const banding = this.tool === 'erase' && el === this.rollEl && !event.shiftKey;
    this._drag = {
      el,
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      localX: event.clientX - rect.left,
      localY: event.clientY - rect.top,
      viewA: this.view.a,
      panning: false,
      banding,
      restoring: event.altKey,
    };
  }

  _onPointerMove(event) {
    const drag = this._drag;
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.x;
    if (drag.banding) {
      if (!drag.dragging && Math.abs(dx) < DRAG_SLOP_PX && Math.abs(event.clientY - drag.y) < DRAG_SLOP_PX) return;
      drag.dragging = true;
      const rect = drag.el.getBoundingClientRect();
      this._band = {
        x0: drag.localX,
        y0: drag.localY,
        x1: event.clientX - rect.left,
        y1: event.clientY - rect.top,
        restoring: drag.restoring,
      };
      this.draw();
      return;
    }
    if (!drag.panning && Math.abs(dx) < DRAG_SLOP_PX) return;
    drag.panning = true;
    const perPixel = this.viewWidth / Math.max(1, drag.el.clientWidth);
    const lo = drag.viewA - dx * perPixel;
    this.setWindow(lo, lo + this.viewWidth);
  }

  _onPointerUp(event, el) {
    const drag = this._drag;
    this._drag = null;
    if (!drag || event.pointerId !== drag.id) return;
    try { el.releasePointerCapture(event.pointerId); } catch { /* never captured */ }
    if (drag.panning) return;

    if (drag.dragging && this._band) {
      const hits = this.notesInBand(this._band);
      const restoring = this._band.restoring;
      this._band = null;
      this.draw();
      if (hits.length && this.opts.onBand) this.opts.onBand(hits, restoring);
      return;
    }
    this._band = null;

    const rect = el.getBoundingClientRect();
    if (this.tool === 'erase' && el === this.rollEl) {
      // Directly on a note, erase it; anywhere else, the click still places
      // the playhead, so auditioning what you just cut needs no tool change.
      const hit = this._hit(this.notes, event, rect, (n) => n.onset, (n, i) =>
        this.visible.has(this.classOf(i) ?? 'matched'),
      );
      if (hit.index >= 0) {
        if (this.opts.onToggleSilence) this.opts.onToggleSilence(hit.index);
        return;
      }
      // Not on a line note: a candidate under the pointer is switched on or
      // off. The same gesture as erasing, with the opposite sign — one tool
      // edits the transcription in both directions.
      const offered = this._hit(this.candidates, event, rect, (n) => n.onset, (n, i) =>
        this.showSecond || this.added.has(i),
      );
      if (offered.index >= 0) {
        if (this.opts.onToggleAdd) this.opts.onToggleAdd(offered.index);
        return;
      }
    }

    // A click is both "look at this" and "listen from here": the playhead
    // moves, and any note under it is inspected. Wanting one without the
    // other has not come up — you click a suspicious note to hear it.
    if (this.opts.onSeek) this.opts.onSeek(this.xToTime(event.clientX - rect.left, rect.width));
    if (el === this.rollEl) this._select(event);
  }

  _onWheel(event, el) {
    event.preventDefault();
    if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      const amount = (event.shiftKey ? event.deltaY : event.deltaX) * 0.0015 * this.viewWidth;
      this.setWindow(this.view.a + amount, this.view.a + amount + this.viewWidth);
      return;
    }
    const rect = el.getBoundingClientRect();
    const at = this.xToTime(event.clientX - rect.left, rect.width);
    // Same curve as the waveforms', so a notch of the wheel means the same
    // thing on every view.
    this.zoomBy(Math.exp(event.deltaY * 0.0015), at);
  }

  _select(event) {
    if (!this.notes.length) return;
    const rect = this.rollEl.getBoundingClientRect();
    // Both layers are candidates, judged the same way, and the vertically
    // nearer one wins. Searching ours first and only then falling back would
    // make a missed note unclickable whenever any note of ours overlaps it in
    // time — which in a busy passage is most of them, and a missed note is
    // exactly the case with nothing of ours to click instead.
    const ours = this._hit(this.notes, event, rect, (n) => n.onset, (n, i) =>
      this.visible.has(this.classOf(i) ?? 'matched'),
    );
    const notated = this.ground
      ? this._hit(this.ground.reference_notes, event, rect, (n) => n.x, (n) =>
          this.visible.has(n.cls),
        )
      : { index: -1, distance: Infinity };

    if (notated.index >= 0 && notated.distance < ours.distance) {
      this.selected = -1;
      this.draw();
      if (this.opts.onSelectReference) this.opts.onSelectReference(notated.index);
      return;
    }
    this.selected = ours.index;
    this.draw();
    if (this.opts.onSelect) {
      this.opts.onSelect(ours.index >= 0 ? this.notes[ours.index] : null, ours.index);
    }
  }

  /* The visible note under the pointer, or index -1.
   *
   * Vertical distance is measured in pixels against the drawn rectangle, so
   * the space above and below a note is genuinely empty — a semitone-based
   * tolerance meant something different at every zoom, and once a click can
   * erase a note, "close enough" has to mean what it looks like. */
  _hit(notes, event, rect, onsetOf, isVisible) {
    const t = this.xToTime(event.clientX - rect.left, rect.width);
    const h = this.roll.el.clientHeight;
    const y = event.clientY - this.rollEl.getBoundingClientRect().top;
    const reach = this.noteHeight(h) / 2 + HIT_PAD_PX;
    let index = -1;
    let distance = Infinity;
    notes.forEach((n, i) => {
      const onset = onsetOf(n);
      if (t < onset - CLICK_SLACK_S || t > onset + n.duration + CLICK_SLACK_S) return;
      if (!isVisible(n, i)) return;
      const d = Math.abs(y - this.pitchToY(n.pitch, h));
      if (d < distance && d <= reach) {
        distance = d;
        index = i;
      }
    });
    return { index, distance };
  }

  selectIndex(i) {
    this.selected = i;
    this.draw();
  }
}
