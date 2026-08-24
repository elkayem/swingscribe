/* The review screen's piano roll and diagnostic lanes.
 *
 * A note list is a picture; a piano roll wired to the frame trace is a
 * diagnostic. This draws the transcribed notes over the same bar grid the
 * selection screen uses — a wrong downbeat is invisible in a list and obvious
 * the moment notes sit against bar lines — and, beneath it, the per-frame
 * evidence: the raw CREPE f0 against the gated-and-smoothed pitch, and the two
 * gates (periodicity, energy) that decided which frames survived.
 *
 * All times are track-global seconds; the view is fixed to one span [a, b].
 */

const PITCH_PAD = 2; // semitones of headroom above/below the note range
const MIN_PITCH_SPAN = 14; // never zoom the pitch axis tighter than this

export class PianoRoll {
  constructor(rollEl, f0El, gateEl, opts = {}) {
    this.rollEl = rollEl;
    this.f0El = f0El;
    this.gateEl = gateEl;
    this.opts = opts;

    this.roll = this._attach(rollEl);
    this.f0 = this._attach(f0El);
    this.gate = this._attach(gateEl);

    this.span = { a: 0, b: 1 };
    this.notes = [];
    this.diag = null;
    this.beats = null;
    this.selected = -1;
    this.playhead = null;

    this.rollEl.addEventListener('pointerdown', (e) => this._onClick(e));
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
    this.span = span;
    this.notes = review ? review.notes : [];
    this.diag = review ? review.diagnostics : null;
    this.beats = beats;
    this.selected = -1;
    // Pitch axis auto-ranges to the notes, with headroom, floored to a minimum
    // span so a monophonic line does not render as one fat band.
    if (this.notes.length) {
      let lo = Math.min(...this.notes.map((n) => n.pitch));
      let hi = Math.max(...this.notes.map((n) => n.pitch));
      const short = MIN_PITCH_SPAN - (hi - lo);
      if (short > 0) {
        lo -= Math.floor(short / 2);
        hi += Math.ceil(short / 2);
      }
      this.pitchLo = lo - PITCH_PAD;
      this.pitchHi = hi + PITCH_PAD;
    } else {
      this.pitchLo = 48;
      this.pitchHi = 72;
    }
    this.draw();
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
    return ((t - this.span.a) / Math.max(1e-6, this.span.b - this.span.a)) * w;
  }

  xToTime(x, width) {
    const w = width ?? this.width;
    return this.span.a + (x / Math.max(1, w)) * (this.span.b - this.span.a);
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
      if (t < this.span.a || t > this.span.b) continue;
      const x = this.timeToX(t, w);
      const isChorus = chorus.has(t);
      ctx.globalAlpha = number < 1 ? 0.05 : isChorus ? 0.35 : 0.12;
      ctx.fillStyle = isChorus ? chorusColor : downColor;
      ctx.fillRect(x - 0.5, 0, isChorus ? 1.5 : 1, h);
      ctx.globalAlpha = 1;
      if (number >= 1) {
        ctx.fillStyle = isChorus ? chorusColor : downColor;
        ctx.font = '9px ui-monospace, Menlo, Consolas, monospace';
        ctx.fillText(String(number), x + 3, 10);
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
      ctx.globalAlpha = 0.4;
      ctx.beginPath();
      for (const t of this.diag.onsets) {
        if (t < this.span.a || t > this.span.b) continue;
        const x = this.timeToX(t, w);
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    const noteH = Math.max(3, h / (this.pitchHi - this.pitchLo));
    this.notes.forEach((n, i) => {
      const x0 = this.timeToX(n.onset, w);
      const x1 = this.timeToX(n.onset + n.duration, w);
      const y = this.pitchToY(n.pitch, h) - noteH / 2;
      const selected = i === this.selected;
      // Confidence drives fill: a faint note is one the transcriber was unsure
      // of, which is exactly what you want to eyeball.
      const alpha = 0.35 + 0.6 * Math.min(1, Math.max(0, n.confidence));
      ctx.fillStyle = selected ? this._css('--accent', '#f0a848') : `rgba(86, 207, 192, ${alpha})`;
      ctx.fillRect(x0, y, Math.max(2, x1 - x0), noteH - 1);
      if (selected) {
        ctx.strokeStyle = this._css('--accent', '#f0a848');
        ctx.strokeRect(x0 - 1, y - 1, Math.max(2, x1 - x0) + 2, noteH + 1);
      }
    });

    this._drawPlayhead(ctx, w, h);
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

  _onClick(event) {
    if (!this.notes.length) return;
    const rect = this.rollEl.getBoundingClientRect();
    const t = this.xToTime(event.clientX - rect.left);
    const h = this.roll.el.clientHeight;
    const pitch = this.pitchLo + (1 - (event.clientY - rect.top) / h) * (this.pitchHi - this.pitchLo);
    // Nearest note whose time span contains the click, breaking ties by pitch.
    let best = -1;
    let bestDist = Infinity;
    this.notes.forEach((n, i) => {
      if (t < n.onset - 0.05 || t > n.onset + n.duration + 0.05) return;
      const d = Math.abs(n.pitch - pitch);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    this.selected = best;
    this.draw();
    if (this.opts.onSelect) this.opts.onSelect(best >= 0 ? this.notes[best] : null, best);
  }

  selectIndex(i) {
    this.selected = i;
    this.draw();
  }
}
