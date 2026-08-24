/* Playback. Two engines, because the two halves of this workflow want
 * genuinely different things.
 *
 * MixEngine (screens 1-2) plays the whole track from one <audio> element:
 * range requests make seeking anywhere in a five-minute file instant, and it
 * costs no memory. Its playbackRate preserves pitch for free.
 *
 * StemEngine (screen 3) mixes several stems at once, so it cannot use media
 * elements: separated stems are highly correlated, and even ten milliseconds
 * of drift between them comb-filters into a swish that sounds exactly like bad
 * separation. Instead each span is decoded into an AudioBuffer and every source
 * is scheduled from one instant, which is sample-accurate and stays that way
 * through any number of loops. The price is that speed changes come from the
 * server (see gui/audio.py) rather than from playbackRate, which would resample
 * and therefore transpose.
 */

export class MixEngine {
  constructor(url) {
    this.audio = new Audio();
    this.audio.preservesPitch = true;
    this.audio.src = url;
    this.loop = null;
    this.audio.addEventListener('timeupdate', () => this.enforceLoop());
  }

  get time() { return this.audio.currentTime; }
  get playing() { return !this.audio.paused && !this.audio.ended; }

  play() { return this.audio.play().catch(() => {}); }
  pause() { this.audio.pause(); }
  toggle() { return this.playing ? this.pause() : this.play(); }
  seek(t) { this.audio.currentTime = Math.max(0, t); }
  setRate(rate) { this.audio.playbackRate = rate; this.audio.preservesPitch = true; }
  setLoop(span) { this.loop = span; }
  destroy() { this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load(); }

  /* Public because the animation frame loop must call it too: timeupdate fires
     only ~4x/second, which overshoots a loop point audibly. When the tab is
     hidden there are no animation frames and timeupdate is all we have, so a
     backgrounded loop is loose by up to a quarter of a second. */
  enforceLoop() {
    if (!this.loop || !this.playing) return;
    const { a, b } = this.loop;
    if (this.audio.currentTime >= b - 0.005 || this.audio.currentTime < a - 0.25) {
      this.audio.currentTime = a;
    }
  }
}

export class StemEngine {
  constructor() {
    this.ctx = null;
    this.buffers = new Map();   // key -> AudioBuffer
    this.gains = new Map();     // key -> GainNode (persistent across restarts)
    this.sources = new Map();   // key -> AudioBufferSourceNode (single-use)
    this.levels = new Map();    // key -> 0..1 fader position
    this.muted = new Set();
    this.loopLength = 0;
    this.playing = false;
    this.pausedAt = 0;
    this._startCtx = 0;
    this._startOffset = 0;
    this.rate = 1;
    this.spanStart = 0;
  }

  _context() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    return this.ctx;
  }

  /** Seconds into the span's *own* timeline (which is longer when slowed). */
  get position() {
    if (!this.playing) return this.pausedAt;
    const elapsed = Math.max(0, this._context().currentTime - this._startCtx);
    const raw = this._startOffset + elapsed;
    return this.loopLength > 0 ? raw % this.loopLength : raw;
  }

  /** The same instant in the original recording's timeline. */
  get trackTime() { return this.spanStart + this.position * this.rate; }

  get duration() { return this.loopLength; }

  /** Drop everything: a new span, or a new speed, invalidates every buffer. */
  reset(spanStart, rate) {
    this.stop();
    this.buffers.clear();
    this.spanStart = spanStart;
    this.rate = rate;
    this.loopLength = 0;
    this.pausedAt = 0;
  }

  has(key) { return this.buffers.has(key); }

  async load(key, url) {
    if (this.buffers.has(key)) return;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${key}: ${response.status} ${await response.text()}`);
    const bytes = await response.arrayBuffer();
    const buffer = await this._context().decodeAudioData(bytes);
    this.buffers.set(key, buffer);
    // Every stem of one span is the same length by construction; taking the
    // shortest anyway means a stray sample can never desynchronise the loop.
    this.loopLength = this.loopLength
      ? Math.min(this.loopLength, buffer.duration)
      : buffer.duration;
    if (this.playing) this._startSource(key, this.position, this._context().currentTime + 0.02);
  }

  /* Install a locally generated buffer (the click track) as though it were a
     stem: it then loops, mixes and mutes through exactly the same path, and —
     because every source is scheduled from one instant — stays sample-locked to
     the music instead of drifting against it. */
  setBuffer(key, buffer) {
    this.buffers.set(key, buffer);
    this.loopLength = this.loopLength
      ? Math.min(this.loopLength, buffer.duration)
      : buffer.duration;
    if (this.playing) this._startSource(key, this.position, this._context().currentTime + 0.02);
  }

  /* A click track for `events` — {time, frequency, gain} in buffer seconds —
     rendered to a buffer exactly one loop long so it repeats seamlessly.
     Each click is a short sine burst with an exponential decay: enough attack
     to place the beat precisely, short enough not to smear the thing it is
     supposed to be measuring. */
  renderClicks(key, events, seconds) {
    const ctx = this._context();
    const rate = ctx.sampleRate;
    const length = Math.max(1, Math.round(seconds * rate));
    const buffer = ctx.createBuffer(1, length, rate);
    const data = buffer.getChannelData(0);
    const decay = 0.055;

    for (const { time, frequency, gain } of events) {
      const start = Math.round(time * rate);
      if (start < 0 || start >= length) continue;
      const span = Math.min(Math.round(decay * 3 * rate), length - start);
      for (let i = 0; i < span; i++) {
        const t = i / rate;
        data[start + i] += gain * Math.sin(2 * Math.PI * frequency * t) * Math.exp(-t / decay);
      }
    }
    for (let i = 0; i < length; i++) data[i] = Math.max(-1, Math.min(1, data[i]));
    this.setBuffer(key, buffer);
  }

  drop(key) {
    const source = this.sources.get(key);
    if (source) {
      try { source.stop(); } catch { /* already stopped */ }
      source.disconnect();
      this.sources.delete(key);
    }
    this.buffers.delete(key);
  }

  _gainFor(key) {
    if (!this.gains.has(key)) {
      const node = this._context().createGain();
      node.gain.value = this._effective(key);
      node.connect(this._context().destination);
      this.gains.set(key, node);
    }
    return this.gains.get(key);
  }

  _effective(key) {
    if (this.muted.has(key)) return 0;
    return this.levels.has(key) ? this.levels.get(key) : 1;
  }

  _applyGain(key) {
    const node = this._gainFor(key);
    // Ramped, not stepped: an instant gain change on a running buffer clicks,
    // and a click on every A/B switch would make the comparison useless.
    node.gain.setTargetAtTime(this._effective(key), this._context().currentTime, 0.012);
  }

  setLevel(key, value) { this.levels.set(key, value); this._applyGain(key); }

  setMuted(key, muted) {
    if (muted) this.muted.add(key); else this.muted.delete(key);
    this._applyGain(key);
  }

  _startSource(key, offset, when) {
    const buffer = this.buffers.get(key);
    if (!buffer || !this.loopLength) return;
    const source = this._context().createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    source.loopStart = 0;
    source.loopEnd = this.loopLength;
    source.connect(this._gainFor(key));
    source.start(when, Math.max(0, offset % this.loopLength));
    this.sources.set(key, source);
  }

  async play(offset = null) {
    const ctx = this._context();
    if (ctx.state === 'suspended') await ctx.resume();
    if (!this.loopLength) return;
    this.stopSources();
    const at = offset === null ? this.pausedAt : offset;
    // One `when` for every source is the whole point: they are locked together
    // from the first sample and stay locked through every loop.
    const when = ctx.currentTime + 0.03;
    for (const key of this.buffers.keys()) this._startSource(key, at, when);
    this._startCtx = when;
    this._startOffset = at;
    this.playing = true;
  }

  pause() {
    if (!this.playing) return;
    this.pausedAt = this.position;
    this.stopSources();
    this.playing = false;
  }

  toggle() { return this.playing ? this.pause() : this.play(); }

  seek(offset) {
    const target = this.loopLength ? Math.max(0, offset % this.loopLength) : 0;
    if (this.playing) this.play(target);
    else this.pausedAt = target;
  }

  stop() { this.stopSources(); this.playing = false; this.pausedAt = 0; }

  stopSources() {
    for (const source of this.sources.values()) {
      try { source.stop(); } catch { /* already stopped */ }
      source.disconnect();
    }
    this.sources.clear();
  }
}
