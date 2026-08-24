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

// How far a click may miss a note and still count. Generous on purpose: at a
// wide pitch range a note is only a few pixels tall, and a solo whose lowest
// note is fifteen semitones below its highest gives a very wide range.
const CLICK_SLACK_S = 0.05;
const CLICK_SLACK_SEMITONES = 6;

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

    this.span = { a: 0, b: 1 };
    this.notes = [];
    this.diag = null;
    this.beats = null;
    this.selected = -1;
    this.playhead = null;
    this.ground = null;                        // the aligned hand transcription, if any
    this.visible = new Set(CLASSES);           // which alignment classes to draw

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

  /* Pitch axis auto-ranges to everything drawn, with headroom, floored to a
     minimum span so a monophonic line does not render as one fat band. The
     notated notes are included deliberately: an error of fifteen semitones is
     exactly the one worth seeing, and it is the one an axis fitted to our own
     notes would push off the top or bottom of the canvas. */
  _range() {
    const pitches = this.notes.map((n) => n.pitch);
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
      // Onset ticks are red, and so are invented notes. They are never
      // confusable in shape — full-height hairlines against short horizontal
      // bars — but a field of them drowns the overlay, and with a hand
      // transcription loaded the question on screen is no longer "what split
      // this note?". So they retreat rather than disappear.
      ctx.globalAlpha = this.ground ? 0.14 : 0.4;
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
      const kind = this.classOf(i);
      if (kind && !this.visible.has(kind)) return;
      const x0 = this.timeToX(n.onset, w);
      const x1 = this.timeToX(n.onset + n.duration, w);
      const y = this.pitchToY(n.pitch, h) - noteH / 2;
      const selected = i === this.selected;
      // Confidence drives fill: a faint note is one the transcriber was unsure
      // of, which is exactly what you want to eyeball.
      const alpha = 0.35 + 0.6 * Math.min(1, Math.max(0, n.confidence));
      ctx.globalAlpha = selected ? 1 : alpha;
      ctx.fillStyle = selected
        ? this._css('--accent', '#f0a848')
        : kind
          ? this._classColor(kind)
          : this._css('--lead', '#56cfc0');
      ctx.fillRect(x0, y, Math.max(2, x1 - x0), noteH - 1);
      ctx.globalAlpha = 1;
      if (selected) {
        ctx.strokeStyle = this._css('--accent', '#f0a848');
        ctx.strokeRect(x0 - 1, y - 1, Math.max(2, x1 - x0) + 2, noteH + 1);
      }
    });

    this._drawGroundTruth(ctx, w, h, noteH);
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

  _onClick(event) {
    if (!this.notes.length) return;
    const rect = this.rollEl.getBoundingClientRect();
    const t = this.xToTime(event.clientX - rect.left);
    const h = this.roll.el.clientHeight;
    // The exact inverse of pitchToY, half-semitone offset included. Without
    // that term a click on a note's centre reads half a row high, which only
    // shifted ties before the ground-truth layer existed — and now decides
    // between our note and the notated one sitting beside it.
    const pitch =
      this.pitchLo - 0.5 + (1 - (event.clientY - rect.top) / h) * (this.pitchHi - this.pitchLo);
    // Both layers are candidates, judged the same way, and the vertically
    // nearer one wins. Searching ours first and only then falling back would
    // make a missed note unclickable whenever any note of ours overlaps it in
    // time — which in a busy passage is most of them, and a missed note is
    // exactly the case with nothing of ours to click instead.
    const ours = this._nearest(this.notes, t, pitch, (n) => n.onset, (_, i) =>
      this.visible.has(this.classOf(i) ?? 'matched'),
    );
    const notated = this.ground
      ? this._nearest(this.ground.reference_notes, t, pitch, (n) => n.x, (n) =>
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

  /* Nearest visible note in pitch whose time span contains the click. */
  _nearest(notes, t, pitch, onsetOf, isVisible) {
    let index = -1;
    let distance = Infinity;
    notes.forEach((n, i) => {
      const onset = onsetOf(n);
      if (t < onset - CLICK_SLACK_S || t > onset + n.duration + CLICK_SLACK_S) return;
      if (!isVisible(n, i)) return;
      const d = Math.abs(n.pitch - pitch);
      if (d < distance && d <= CLICK_SLACK_SEMITONES) {
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
