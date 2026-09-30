/* The Changes field: one chorus of chord symbols the listener types, written
 * over the page (roadmap O4, swingscribe/chords.py).
 *
 * Self-contained on purpose: app.js hands it the elements, a way to ask the
 * server to read a chart, and what to do when the text is settled. The chart
 * is a per-track sidecar setting like the key or the transposition, so
 * committing it is app.js's persist(), and the page redraws from there.
 *
 * Two answers reach this field, and they are shown on one line:
 *  - the CHECK, while typing (/api/changes/check): how many bars and chords,
 *    or the bar and token that cannot be read -- red, inline, at once;
 *  - the PLACEMENT, from the page or Export (`changes` in their reply): which
 *    bar of the chart the page's bar 1 fell on, counted from the form start.
 * A chart that does not read is kept as typed (nothing the listener typed is
 * thrown away) and the page is drawn without symbols until it reads.
 */

const CHECK_DEBOUNCE_MS = 300;
const COMMIT_DEBOUNCE_MS = 900;

export class ChangesField {
  constructor({ panel, input, status, toggle, check, onCommit }) {
    this.panel = panel;
    this.input = input;
    this.status = status;
    this.toggle = toggle;
    this.check = check;
    this.onCommit = onCommit;
    this.committed = '';
    this.context = { timeSignature: null, barsPerChorus: 0 };
    this.checked = null;   // the key of the last check asked for
    this.reading = null;   // the last check's answer
    this.placement = null; // the last page's or export's `changes`
    this.token = 0;
    this.checkTimer = null;
    this.commitTimer = null;

    input.addEventListener('input', () => {
      this.placement = null;
      this.scheduleCheck();
      clearTimeout(this.commitTimer);
      this.commitTimer = setTimeout(() => this.commit(), COMMIT_DEBOUNCE_MS);
    });
    input.addEventListener('blur', () => this.commit());
    toggle.addEventListener('click', () => this.show(this.panel.hidden));
  }

  get value() {
    return this.input.value;
  }

  /* A new track: its chart, shown without being committed back. The panel
     opens by itself when the track has one, so the changes are never a
     setting nobody can see. */
  load(text) {
    clearTimeout(this.commitTimer);
    this.input.value = text || '';
    this.committed = this.input.value;
    this.placement = null;
    this.checked = null;
    this.reading = null;
    this.show(Boolean(this.committed.trim()));
    this.runCheck();
  }

  show(shown) {
    this.panel.hidden = !shown;
    this.toggle.classList.toggle('active', shown);
    if (shown && !this.input.value) this.input.focus();
  }

  /* The meter the chart is read against: a bar's chords must divide its
     beats, and the chart must be one chorus long when one is set. */
  setContext({ timeSignature, barsPerChorus }) {
    this.context = { timeSignature: timeSignature || null, barsPerChorus: barsPerChorus || 0 };
    this.runCheck();
  }

  /* Where the page put the chart, from the page view's or Export's reply. */
  report(changes) {
    this.placement = changes || null;
    this.render();
  }

  commit() {
    clearTimeout(this.commitTimer);
    if (this.input.value === this.committed) return;
    this.committed = this.input.value;
    this.onCommit(this.committed);
  }

  scheduleCheck() {
    clearTimeout(this.checkTimer);
    this.checkTimer = setTimeout(() => this.runCheck(), CHECK_DEBOUNCE_MS);
  }

  async runCheck() {
    const text = this.input.value;
    const key = JSON.stringify([text, this.context]);
    if (key === this.checked) { this.render(); return; }
    this.checked = key;
    if (!text.trim()) {
      this.reading = null;
      this.render();
      return;
    }
    const token = ++this.token;
    try {
      const reading = await this.check({
        text,
        time_signature: this.context.timeSignature,
        bars_per_chorus: this.context.barsPerChorus || null,
      });
      if (token !== this.token) return;
      this.reading = reading;
    } catch (error) {
      if (token !== this.token) return;
      this.reading = { error: `could not check the changes: ${error.message}` };
    }
    this.render();
  }

  render() {
    const node = this.status;
    const reading = this.placement ?? this.reading;
    const count = reading && !reading.error ? reading.bars : 0;
    this.toggle.textContent = count ? `Changes · ${count} bar${count === 1 ? '' : 's'}` : 'Changes';
    node.classList.toggle('error', Boolean(reading?.error));
    if (!this.input.value.trim()) {
      node.textContent = 'One chorus, bars split by |, e.g. | Dm7 G7 | Cmaj7 | % |';
      return;
    }
    if (!reading) { node.textContent = ''; return; }
    if (reading.error) { node.textContent = reading.error; return; }
    const bars = `${reading.bars} bar${reading.bars === 1 ? '' : 's'}`;
    const chords = `${reading.chords} chord${reading.chords === 1 ? '' : 's'}`;
    node.textContent = `${bars} · ${chords}${this.where(reading)}`;
  }

  /* "page bar 1 is bar 5 of the chart, chorus 2, counted from the form
     start" -- the check that the chart starts where the listener meant. */
  where(placement) {
    if (!placement || placement.from === null || placement.from === undefined) return '';
    const from = {
      'form start': 'counted from the form start (Bar 1)',
      'chorus lines': 'counted from the first chorus line',
      'span start': 'starting on the span\'s first bar - set the form start to count choruses',
    }[placement.from] ?? '';
    if (placement.chart_bar === null) {
      const before = placement.before || 0;
      return ` · the page starts ${before} bar${before === 1 ? '' : 's'} before the form, ${from}`;
    }
    return ` · page bar 1 is chart bar ${placement.chart_bar}, chorus ${placement.chorus}, ${from}`;
  }
}
