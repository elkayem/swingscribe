/* The speed control: presets, a slider, ± at one percent, and a readout you
 * can type into. One percent is the unit throughout, because "slow it a
 * little more" is the gesture — a listener hunting for a note in a fast run
 * wants 43%, not a choice between half and a quarter.
 *
 * Two commit modes, because the engines differ (engine.js). The mix plays
 * through a media element whose rate changes instantly, so the slider is
 * live. The stems and the review are stretched on the server and reloaded,
 * a few seconds of work, so those follow the slider on release only — the
 * readout tracks the drag so you can see where you will land.
 */

export const MIN_PERCENT = 20;
export const MAX_PERCENT = 200;

const PRESETS = [
  { rate: 1, label: '1×', title: 'Full speed.' },
  { rate: 0.75, label: '¾×', title: 'Three-quarter speed.' },
  { rate: 0.5, label: '½×', title: 'Half speed.' },
  { rate: 0.25, label: '¼×', title: 'Quarter speed.' },
];

const clampPercent = (p) => Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, Math.round(p)));

export class RateControl {
  /* `onChange(rate)` is called with the rate as a fraction (0.5 for 50%)
     whenever a value is settled: a preset, a step, a typed value, or the
     slider — live while dragging when `live`, on release otherwise. */
  constructor(root, { live = false, onChange, pitchNote = 'pitch unchanged' } = {}) {
    this.root = root;
    this.live = live;
    this.onChange = onChange || (() => {});
    this.percent = 100;
    root.classList.add('rate-control');
    root.innerHTML =
      `<div class="rate-group">${PRESETS.map(
        (p) => `<button class="chip" type="button" data-rate="${p.rate}" title="${p.title} Speed changes never move the pitch.">${p.label}</button>`,
      ).join('')}</div>` +
      `<button class="rate-step" type="button" data-step="-1" title="One percent slower. Shift-click for five. (comma)">−</button>` +
      `<input class="rate-slider" type="range" min="${MIN_PERCENT}" max="${MAX_PERCENT}" step="1" value="100" ` +
      `title="Drag to set the speed anywhere from ${MIN_PERCENT}% to ${MAX_PERCENT}%, ${pitchNote}.${live ? '' : ' Takes effect when you let go.'} Scroll over it for one percent at a time.">` +
      `<button class="rate-step" type="button" data-step="1" title="One percent faster. Shift-click for five. (period)">+</button>` +
      `<input class="rate-value" type="text" inputmode="numeric" value="100%" ` +
      `title="The playback speed. Click and type a percentage — 43, or 43% — then press Enter. Scroll over it for one percent at a time.">`;

    this.slider = root.querySelector('.rate-slider');
    this.value = root.querySelector('.rate-value');
    this.presets = [...root.querySelectorAll('[data-rate]')];

    for (const button of this.presets) {
      button.addEventListener('click', () => this.set(Number(button.dataset.rate) * 100));
    }
    for (const button of root.querySelectorAll('[data-step]')) {
      button.addEventListener('click', (event) => {
        this.step(Number(button.dataset.step) * (event.shiftKey ? 5 : 1));
      });
    }

    // The slider: the readout follows every notch; the engine follows on
    // release unless the change is free.
    this.slider.addEventListener('input', () => {
      const p = clampPercent(Number(this.slider.value));
      if (this.live) this.set(p);
      else this._render(p);
    });
    this.slider.addEventListener('change', () => this.set(Number(this.slider.value)));
    // A wheel notch is one percent; the page must not scroll under it.
    const wheel = (event) => {
      event.preventDefault();
      this.step(event.deltaY < 0 ? 1 : -1);
    };
    this.slider.addEventListener('wheel', wheel, { passive: false });
    this.value.addEventListener('wheel', wheel, { passive: false });

    // Typing: commit on Enter or blur, restore on Escape. Accepts "43",
    // "43%", or a fraction like "0.43".
    this.value.addEventListener('focus', () => this.value.select());
    this.value.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); this.value.blur(); }
      else if (event.key === 'Escape') { this._render(this.percent); this.value.blur(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); this.step(event.shiftKey ? 5 : 1); }
      else if (event.key === 'ArrowDown') { event.preventDefault(); this.step(event.shiftKey ? -5 : -1); }
      // Typing must not reach the page's own shortcuts; the document
      // handler already ignores inputs, but stop it here to be sure.
      event.stopPropagation();
    });
    this.value.addEventListener('blur', () => this._commitTyped());

    this._render(100);
  }

  get rate() { return this.percent / 100; }

  /* Set the speed in percent and tell the listener. A no-op at the value
     already set, so a re-click on the active preset costs no reload. */
  set(percent) {
    const p = clampPercent(percent);
    this._render(p);
    if (p === this.percent) return;
    this.percent = p;
    this.onChange(this.rate);
  }

  step(delta) { this.set(this.percent + delta); }

  /* Show a value without changing it — the engine's own rate, on open. */
  show(rate) {
    this.percent = clampPercent(rate * 100);
    this._render(this.percent);
  }

  _commitTyped() {
    const text = this.value.value.trim().replace('%', '');
    let p = Number(text);
    if (!Number.isFinite(p) || text === '') { this._render(this.percent); return; }
    // A bare fraction ("0.5") is a rate, not a percent.
    if (p > 0 && p <= 2 && text.includes('.')) p *= 100;
    this.set(p);
  }

  _render(p) {
    this.slider.value = String(p);
    this.slider.style.setProperty('--fill', `${((p - MIN_PERCENT) / (MAX_PERCENT - MIN_PERCENT)) * 100}%`);
    if (document.activeElement !== this.value) this.value.value = `${p}%`;
    for (const button of this.presets) {
      button.classList.toggle('active', Math.round(Number(button.dataset.rate) * 100) === p);
    }
  }
}
