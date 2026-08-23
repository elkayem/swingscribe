/* SwingScribe — screens 1-3: load, select the span, audition the isolation.
 *
 * Everything that has to feel immediate happens here. The server is asked only
 * for things the browser cannot do: list files, read peaks, cut a span out of a
 * stem, and run Demucs. Dragging a loop point, nudging it a tenth of a second,
 * soloing a stem and switching isolated-against-original are all local.
 */

import { WaveView } from './waveform.js';
import { MixEngine, StemEngine } from './engine.js';

const $ = (id) => document.getElementById(id);

const DETAIL_PAD = 0.18;      // fraction of the span shown either side when fitting
const EDGE_ZOOM_SECONDS = 3;  // window width when focusing one boundary
const MIN_SPAN = 0.2;
const RELOAD_DEBOUNCE_MS = 320;

const state = {
  track: null,
  selection: null,          // {a, b} in track seconds
  focusEdge: 'a',
  model: null,
  leadStem: null,
  stems: [],
  loop: true,
  mixRate: 1,
  stemRate: 1,
  abMode: 'stem',
  active: 'mix',            // which transport the spacebar drives
  mixer: new Map(),         // stem -> {level, muted}
  jobTimer: null,
  reloadTimer: null,
  auditionToken: 0,
};

const mix = { engine: null };
const stemEngine = new StemEngine();

// ── tiny helpers ────────────────────────────────────────────────────────────

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail ?? detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return response.json();
}

const post = (path, body) =>
  api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

function clock(seconds, precise = true) {
  if (!Number.isFinite(seconds)) return precise ? '0:00.00' : '0:00';
  const sign = seconds < 0 ? '-' : '';
  const t = Math.abs(seconds);
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return precise
    ? `${sign}${m}:${s.toFixed(2).padStart(5, '0')}`
    : `${sign}${m}:${String(Math.floor(s)).padStart(2, '0')}`;
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $('toast');
  node.textContent = message;
  node.classList.toggle('error', isError);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, isError ? 6000 : 2600);
}

// ── waveform views ──────────────────────────────────────────────────────────

const overview = new WaveView($('wave-overview'), {
  selectable: true,
  onSeek: (t) => seekTo(t),
  onSelect: (a, b, done) => updateSelection(a, b, done),
  onEdgeFocus: (edge) => setFocusEdge(edge),
});

const detail = new WaveView($('wave-detail'), {
  selectable: true,
  onSeek: (t) => seekTo(t),
  onSelect: (a, b, done) => updateSelection(a, b, done),
  onWindow: () => onDetailWindowChanged(),
  onEdgeFocus: (edge) => setFocusEdge(edge),
});

const stemWave = new WaveView($('wave-stem'), {
  onSeek: (t) => {
    if (!state.selection) return;
    stemEngine.seek((t - state.selection.a) / state.stemRate);
    state.active = 'stem';
  },
});

// ── screen 1: the track picker ──────────────────────────────────────────────

async function refreshPicker() {
  $('picker-error').hidden = true;
  try {
    const [config, tracks] = await Promise.all([api('/api/config'), api('/api/tracks')]);
    $('library-dir').textContent = config.library_dir;
    renderTrackList($('recent-list'), tracks.recent, true);
    renderTrackList($('library-list'), tracks.library, false);
  } catch (error) {
    showPickerError(error.message);
  }
}

function renderTrackList(node, items, isRecent) {
  node.innerHTML = '';
  if (!items.length) {
    node.innerHTML = `<li class="empty">${isRecent ? 'Nothing yet' : 'No audio files here'}</li>`;
    return;
  }
  for (const item of items) {
    const li = document.createElement('li');
    // Recents describe the work (span and stem); library entries only have a
    // file, so they describe the file.
    let meta = '';
    if (isRecent) {
      meta = item.region
        ? `${item.stem ?? 'no stem'} · ${clock(item.region[0], false)}–${clock(item.region[1], false)}`
        : (item.stem ?? '');
    } else if (Number.isFinite(item.size)) {
      meta = `${(item.size / 1e6).toFixed(1)} MB`;
    }
    li.innerHTML = `<span class="name"></span><span class="meta"></span>`;
    li.querySelector('.name').textContent = item.name;
    li.querySelector('.meta').textContent = meta;
    li.addEventListener('click', () => openTrack(item.path));
    node.appendChild(li);
  }
}

function showPickerError(message) {
  const node = $('picker-error');
  node.textContent = message;
  node.hidden = false;
}

async function openTrack(path) {
  try {
    const track = await api('/api/tracks/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    await loadTrack(track);
  } catch (error) {
    showPickerError(error.message);
  }
}

// ── screen 2: load, waveforms, selection ────────────────────────────────────

async function loadTrack(track) {
  state.track = track;
  $('picker').hidden = true;
  $('picker-close').hidden = false;
  $('workspace').hidden = false;
  $('track-title').textContent = `${track.name} · ${clock(track.duration, false)}`;
  $('track-title').classList.add('loaded');
  $('time-total').textContent = clock(track.duration, false);
  $('overview-duration').textContent = clock(track.duration, false);

  mix.engine?.destroy();
  mix.engine = new MixEngine(`/api/tracks/${track.id}/audio`);
  mix.engine.setRate(state.mixRate);
  stemEngine.reset(0, 1);
  $('audition').hidden = true;

  for (const view of [overview, detail, stemWave]) view.setBounds(0, track.duration);

  const remembered = track.state ?? {};
  const region = remembered.region;
  state.selection = Array.isArray(region) && region.length === 2 && region[1] > region[0]
    ? { a: region[0], b: Math.min(region[1], track.duration) }
    : { a: 0, b: Math.min(30, track.duration) };
  state.model = remembered.model ?? track.models.find((m) => m.ready)?.model
    ?? track.models[0]?.model;
  state.leadStem = remembered.stem ?? null;
  state.mixer.clear();

  overview.setPeaks(await api(`/api/tracks/${track.id}/peaks`));
  overview.setWindow(0, track.duration, { silent: true });
  applySelection(true);
  focusDetail('fit');
  renderModels();
  setFocusEdge('a');
  seekTo(state.selection.a);
  await refreshAudition();
  persist();  // so this track shows its span in Recent even if nothing is edited
}

function applySelection(fitDetail = false) {
  const { a, b } = state.selection;
  overview.setSelection(a, b);
  detail.setSelection(a, b);
  $('a-time').textContent = clock(a);
  $('b-time').textContent = clock(b);
  $('span-length').textContent = clock(b - a);
  mix.engine?.setLoop(state.loop ? { a, b } : null);
  updateHandoff();
  if (fitDetail) focusDetail('fit');
}

function updateSelection(a, b, done) {
  if (!state.track) return;
  let lo = Math.max(0, Math.min(a, b));
  let hi = Math.min(state.track.duration, Math.max(a, b));
  if (hi - lo < MIN_SPAN) hi = Math.min(state.track.duration, lo + MIN_SPAN);
  state.selection = { a: lo, b: hi };
  overview.setSelection(lo, hi);
  detail.setSelection(lo, hi);
  applySelection(false);
  if (done) {
    persist();
    scheduleAuditionReload();
  }
}

/* Which boundary the nudge keys move. Shown in the transport, because
   otherwise "[" and "]" are a guess about invisible state. */
function setFocusEdge(which) {
  state.focusEdge = which;
  $('edge-a').classList.toggle('focused', which === 'a');
  $('edge-b').classList.toggle('focused', which === 'b');
}

function setEdge(which, time) {
  if (!state.selection) return;
  const other = which === 'a' ? state.selection.b : state.selection.a;
  const a = which === 'a' ? time : other;
  const b = which === 'a' ? other : time;
  setFocusEdge(which);
  updateSelection(Math.min(a, b), Math.max(a, b), true);
  focusDetail(which);
}

function nudge(which, delta) {
  if (!state.selection) return;
  const current = which === 'a' ? state.selection.a : state.selection.b;
  setEdge(which, Math.max(0, Math.min(state.track.duration, current + delta)));
}

// ── detail window ───────────────────────────────────────────────────────────

function focusDetail(mode) {
  if (!state.selection) return;
  const { a, b } = state.selection;
  if (mode === 'fit') {
    const pad = Math.max(0.5, (b - a) * DETAIL_PAD);
    detail.setWindow(a - pad, b + pad, { silent: true });
  } else {
    const centre = mode === 'a' ? a : b;
    setFocusEdge(mode);
    detail.setWindow(centre - EDGE_ZOOM_SECONDS / 2, centre + EDGE_ZOOM_SECONDS / 2, {
      silent: true,
    });
  }
  onDetailWindowChanged();
}

let detailPeaksTimer = null;
function onDetailWindowChanged() {
  const { start, end } = detail.win;
  $('detail-range').textContent = `${clock(start, false)}–${clock(end, false)} · ${(end - start).toFixed(1)}s`;
  overview.setWindowBox(start, end);
  clearTimeout(detailPeaksTimer);
  detailPeaksTimer = setTimeout(async () => {
    if (!state.track) return;
    const query = `start=${start}&end=${end}&buckets=2000`;
    try {
      detail.setPeaks(await api(`/api/tracks/${state.track.id}/peaks?${query}`));
    } catch { /* a stale window; the next one will land */ }
  }, 90);
}

// ── transport ───────────────────────────────────────────────────────────────

function seekTo(t) {
  state.active = 'mix';
  stemEngine.pause();
  mix.engine?.seek(t);
  overview.setPlayhead(t);
  detail.setPlayhead(t);
}

function togglePlay() {
  if (state.active === 'stem' && stemEngine.duration) {
    stemEngine.toggle();
  } else {
    state.active = 'mix';
    stemEngine.pause();
    mix.engine?.toggle();
  }
  refreshPlayButtons();
}

function refreshPlayButtons() {
  $('play').textContent = mix.engine?.playing ? '❚❚' : '▶';
  $('a-play').textContent = stemEngine.playing ? '❚❚' : '▶';
}

function tick() {
  if (state.track) {
    // Keyed on which engine is *active*, not on which is playing: a paused
    // stem engine must hold its playhead where you stopped it rather than snap
    // back to wherever the mix transport happens to be.
    if (state.active === 'stem' && stemEngine.duration) {
      const t = stemEngine.trackTime;
      stemWave.setPlayhead(t);
      overview.setPlayhead(t);
      detail.setPlayhead(t);
      $('a-time-now').textContent = clock(stemEngine.position * state.stemRate);
      $('time-now').textContent = clock(t);
    } else if (mix.engine) {
      const t = mix.engine.time;
      mix.engine.enforceLoop();
      overview.setPlayhead(t);
      detail.setPlayhead(t);
      $('time-now').textContent = clock(t);
      if (state.selection && stemEngine.duration) {
        stemWave.setPlayhead(t);
      }
    }
    refreshPlayButtons();
  }
  requestAnimationFrame(tick);
}

// ── screen 3: isolate & audition ────────────────────────────────────────────

function renderModels() {
  const node = $('model-chips');
  node.innerHTML = '';
  const models = state.track?.models ?? [];
  for (const entry of models) {
    const button = document.createElement('button');
    button.className = `chip${entry.model === state.model ? ' active' : ''}`;
    button.innerHTML = `<span class="dot${entry.ready ? ' ready' : ''}"></span>`;
    button.append(entry.model);
    button.title = entry.ready
      ? `Separated — ${entry.stems.join(', ')}`
      : 'Not separated yet — 6-13 minutes on CPU';
    button.addEventListener('click', () => selectModel(entry.model));
    node.appendChild(button);
  }
  const current = models.find((m) => m.model === state.model);
  const button = $('separate-btn');
  button.hidden = Boolean(current?.ready);
  button.textContent = `Separate with ${state.model ?? ''}`;
}

async function selectModel(model) {
  state.model = model;
  renderModels();
  persist();
  await refreshAudition();
}

async function refreshStemList() {
  if (!state.track || !state.model) return;
  const data = await api(`/api/tracks/${state.track.id}/stems?model=${state.model}`);
  state.stems = data.stems ?? [];
  const select = $('lead-stem');
  select.innerHTML = '';
  for (const stem of state.stems) {
    const option = document.createElement('option');
    option.value = stem;
    option.textContent = stem;
    select.appendChild(option);
  }
  if (!state.stems.includes(state.leadStem)) {
    // "other" is where a horn lands in a 4-stem split, and it is the config
    // default, so it is the right guess when nothing is remembered.
    state.leadStem = state.stems.includes('other') ? 'other' : state.stems[0] ?? null;
  }
  select.value = state.leadStem ?? '';
  $('legend-stem').textContent = state.leadStem ?? 'lead stem';
  updateHandoff();  // the command needs the stem, which we only just resolved
}

async function refreshAudition() {
  if (!state.track || !state.model) return;
  await refreshStemList();
  const ready = state.stems.length > 0;
  $('audition').hidden = !ready;
  renderModels();
  if (!ready) { stemEngine.reset(0, 1); return; }
  await loadAudition();
}

function scheduleAuditionReload() {
  clearTimeout(state.reloadTimer);
  state.reloadTimer = setTimeout(() => loadAudition(), RELOAD_DEBOUNCE_MS);
}

function stemUrl(stem, { download = false } = {}) {
  const { a, b } = state.selection;
  const params = new URLSearchParams({
    stem,
    model: state.model,
    start: a.toFixed(3),
    end: b.toFixed(3),
    rate: String(state.stemRate),
  });
  if (download) params.set('download', 'true');
  return `/api/tracks/${state.track.id}/stem?${params}`;
}

async function loadAudition() {
  if (!state.track || !state.selection || !state.stems.length || !state.leadStem) return;
  const token = ++state.auditionToken;
  const { a, b } = state.selection;
  const wasPlaying = stemEngine.playing;

  if (!state.mixer.size) seedMixerFromAbMode();
  stemEngine.reset(a, state.stemRate);
  renderMixer();
  $('audition-range').textContent = `${clock(a, false)}–${clock(b, false)} · ${(b - a).toFixed(1)}s`;
  $('a-time-total').textContent = clock(b - a, false);

  // The original mix and the lead stem always load, so the A/B switch is
  // instant; everything else loads only if it was already part of the mix you
  // had built up. Changing span or speed must not silently tear that down.
  const wanted = new Set(['mix', state.leadStem]);
  for (const [key, settings] of state.mixer) if (!settings.muted) wanted.add(key);

  try {
    await Promise.all([...wanted].map((key) => stemEngine.load(key, stemUrl(key))));
  } catch (error) {
    if (token === state.auditionToken) toast(`Audition: ${error.message}`, true);
    return;
  }
  if (token !== state.auditionToken) return;   // a newer span superseded this one

  applyMixer();
  renderMixer();
  await drawStemOverlay(token);
  if (wasPlaying) stemEngine.play(0);
}

async function drawStemOverlay(token) {
  const { a, b } = state.selection;
  const base = `/api/tracks/${state.track.id}/peaks?start=${a}&end=${b}&buckets=2000`;
  try {
    const [mixPeaks, leadPeaks] = await Promise.all([
      api(base),
      api(`${base}&stem=${encodeURIComponent(state.leadStem)}&model=${state.model}`),
    ]);
    if (token !== state.auditionToken) return;
    stemWave.setWindow(a, b, { silent: true });
    stemWave.setPeaks(mixPeaks);
    stemWave.setOverlay(leadPeaks);
  } catch (error) {
    if (token === state.auditionToken) toast(`Waveform: ${error.message}`, true);
  }
}

function mixerKeys() {
  return ['mix', ...state.stems];
}

function renderMixer() {
  const node = $('mixer');
  node.innerHTML = '';
  for (const key of mixerKeys()) {
    const settings = state.mixer.get(key) ?? { level: 1, muted: !isAudible(key) };
    state.mixer.set(key, settings);
    const row = document.createElement('div');
    const isLead = key === state.leadStem;
    row.className = `stem-row${isLead ? ' is-lead' : ''}${settings.muted ? ' muted-row' : ''}`;
    row.innerHTML = `
      <button class="s${settings.muted ? '' : ' on'}" title="Mute / unmute">${settings.muted ? '○' : '◉'}</button>
      <span class="stem-name">${key === 'mix' ? 'original mix' : key}${isLead ? '<span class="lead-tag">lead</span>' : ''}</span>
      <input type="range" min="0" max="1" step="0.02" value="${settings.level}">
      <span class="loading"${settings.muted || stemEngine.has(key) ? ' hidden' : ''}>loading…</span>`;

    row.querySelector('button').addEventListener('click', () => toggleStem(key));
    row.querySelector('input').addEventListener('input', (event) => {
      const level = Number(event.target.value);
      state.mixer.get(key).level = level;
      stemEngine.setLevel(key, level);
    });
    node.appendChild(row);
  }
}

function isAudible(key) {
  if (state.abMode === 'both') return key === 'mix' || key === state.leadStem;
  if (state.abMode === 'mix') return key === 'mix';
  return key === state.leadStem;
}

async function toggleStem(key) {
  const settings = state.mixer.get(key);
  settings.muted = !settings.muted;
  if (!settings.muted && !stemEngine.has(key)) {
    renderMixer();
    try {
      await stemEngine.load(key, stemUrl(key));
    } catch (error) {
      toast(`${key}: ${error.message}`, true);
      settings.muted = true;
    }
  }
  stemEngine.setLevel(key, settings.level);
  stemEngine.setMuted(key, settings.muted);
  syncAbHighlight();
  renderMixer();
}

/* Light the A/B button only when the mix actually matches it — otherwise the
   toggle claims to describe an arrangement you have since changed by hand. */
function syncAbHighlight() {
  const matches = mixerKeys().every(
    (key) => (state.mixer.get(key)?.muted ?? true) === !isAudible(key)
  );
  for (const button of $('ab-toggle').querySelectorAll('button')) {
    button.classList.toggle('active', matches && button.dataset.ab === state.abMode);
  }
}

/* Push the stored mixer state at the engine. Levels are set before mutes so a
   fader you moved while a stem was muted is honoured the moment it comes back. */
function applyMixer() {
  for (const [key, settings] of state.mixer) {
    if (!stemEngine.has(key)) continue;
    stemEngine.setLevel(key, settings.level);
    stemEngine.setMuted(key, settings.muted);
  }
}

function seedMixerFromAbMode() {
  for (const key of mixerKeys()) {
    const settings = state.mixer.get(key) ?? { level: 1, muted: true };
    settings.muted = !isAudible(key);
    state.mixer.set(key, settings);
  }
}

/* The A/B buttons are a deliberate override of whatever you had soloed. */
function applyAbMode() {
  seedMixerFromAbMode();
  applyMixer();
  for (const button of $('ab-toggle').querySelectorAll('button')) {
    button.classList.toggle('active', button.dataset.ab === state.abMode);
  }
}

// ── separation jobs ─────────────────────────────────────────────────────────

async function startSeparation() {
  if (!state.track || !state.model) return;
  try {
    const job = await post('/api/jobs', { path: state.track.path, model: state.model });
    $('separate-btn').disabled = true;
    $('job').hidden = false;
    pollJob(job.id);
  } catch (error) {
    toast(error.message, true);
  }
}

function pollJob(jobId) {
  clearInterval(state.jobTimer);
  state.jobTimer = setInterval(async () => {
    let job;
    try {
      job = await api(`/api/jobs/${jobId}`);
    } catch { return; }
    $('job-fill').style.width = `${(job.fraction * 100).toFixed(1)}%`;
    $('job-message').textContent = job.message || job.state;
    $('job-elapsed').textContent = `${clock(job.elapsed, false)} elapsed`;
    if (job.state === 'done' || job.state === 'error') {
      clearInterval(state.jobTimer);
      $('separate-btn').disabled = false;
      if (job.state === 'error') {
        toast(job.error, true);
        return;
      }
      $('job').hidden = true;
      toast(`${job.model}: ${job.stems.length} stems ready`);
      state.track = await api('/api/tracks/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: state.track.path }),
      }).catch(() => state.track);
      await refreshAudition();
    }
  }, 1000);
}

// ── handoff & persistence ───────────────────────────────────────────────────

function updateHandoff() {
  if (!state.track || !state.selection) return;
  if (!state.leadStem) {
    $('cli-command').textContent = 'Separate the track to get a transcription command';
    return;
  }
  const { a, b } = state.selection;
  const command =
    `uv run swingscribe ab "${state.track.path}" --stem ${state.leadStem} ` +
    `--start ${a.toFixed(2)} --end ${b.toFixed(2)}`;
  $('cli-command').textContent = command;
}

let persistTimer = null;
function persist() {
  if (!state.track) return;
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    post(`/api/tracks/${state.track.id}/state`, {
      state: {
        region: [state.selection.a, state.selection.b],
        stem: state.leadStem,
        model: state.model,
      },
    }).catch(() => { /* remembering where you were is not worth an error */ });
  }, 500);
}

// ── events ──────────────────────────────────────────────────────────────────

$('open-picker').addEventListener('click', () => { $('picker').hidden = false; refreshPicker(); });
$('picker-close').addEventListener('click', () => { $('picker').hidden = true; });
$('path-open').addEventListener('click', () => openTrack($('path-input').value.trim()));
$('path-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') openTrack($('path-input').value.trim());
});

$('play').addEventListener('click', () => { state.active = 'mix'; togglePlay(); });
$('a-play').addEventListener('click', () => {
  state.active = 'stem';
  mix.engine?.pause();
  stemEngine.toggle();
  refreshPlayButtons();
});

$('loop').addEventListener('click', () => {
  state.loop = !state.loop;
  $('loop').classList.toggle('active', state.loop);
  mix.engine?.setLoop(state.loop && state.selection ? state.selection : null);
});
$('loop').classList.add('active');

for (const button of document.querySelectorAll('[data-set]')) {
  button.addEventListener('click', () => setEdge(button.dataset.set, mix.engine?.time ?? 0));
}
for (const button of document.querySelectorAll('[data-nudge]')) {
  button.addEventListener('click', () =>
    nudge(button.dataset.nudge, Number(button.dataset.delta)));
}
for (const button of document.querySelectorAll('[data-focus]')) {
  button.addEventListener('click', () => focusDetail(button.dataset.focus));
}
for (const button of document.querySelectorAll('[data-zoom]')) {
  button.addEventListener('click', () => {
    const factor = button.dataset.zoom === 'in' ? 0.6 : 1.7;
    const centre = (detail.win.start + detail.win.end) / 2;
    const span = detail.span * factor;
    detail.setWindow(centre - span / 2, centre + span / 2);
  });
}

for (const button of $('mix-rate').querySelectorAll('button')) {
  button.addEventListener('click', () => {
    state.mixRate = Number(button.dataset.rate);
    mix.engine?.setRate(state.mixRate);
    for (const other of $('mix-rate').querySelectorAll('button')) {
      other.classList.toggle('active', other === button);
    }
  });
}
$('mix-rate').querySelector('[data-rate="1"]').classList.add('active');

for (const button of $('stem-rate').querySelectorAll('button')) {
  button.addEventListener('click', async () => {
    state.stemRate = Number(button.dataset.rate);
    for (const other of $('stem-rate').querySelectorAll('button')) {
      other.classList.toggle('active', other === button);
    }
    // Stretched server-side, so every source stays at rate 1.0 and therefore
    // still sample-locked to the others. Costs a reload; keeps the pitch.
    await loadAudition();
  });
}
$('stem-rate').querySelector('[data-rate="1"]').classList.add('active');

for (const button of $('ab-toggle').querySelectorAll('button')) {
  button.addEventListener('click', () => { state.abMode = button.dataset.ab; applyAbMode(); renderMixer(); });
}

$('lead-stem').addEventListener('change', async (event) => {
  state.leadStem = event.target.value;
  $('legend-stem').textContent = state.leadStem;
  state.mixer.clear();
  persist();
  updateHandoff();
  await loadAudition();
});

$('separate-btn').addEventListener('click', startSeparation);

$('copy-cmd').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('cli-command').textContent);
    toast('Command copied');
  } catch {
    toast('Copy failed — select the text instead', true);
  }
});

$('download-stem').addEventListener('click', () => {
  if (!state.selection || !state.leadStem) return;
  window.location.href = stemUrl(state.leadStem, { download: true });
});

document.addEventListener('keydown', (event) => {
  // Shortcuts must never fire while typing a path into the picker. The target
  // is not always an Element (it can be the document itself), so test before
  // calling matches() on it.
  const target = event.target;
  if (target instanceof Element && target.matches('input, select, textarea')) return;
  if (!state.track) return;
  const shift = event.shiftKey;
  switch (event.key.toLowerCase()) {
    case ' ':
      event.preventDefault();
      togglePlay();
      break;
    case 'a':
      setEdge('a', currentTime());
      break;
    case 'b':
      setEdge('b', currentTime());
      break;
    case 'l':
      $('loop').click();
      break;
    case '[':
      nudge(state.focusEdge, shift ? -0.01 : -0.1);
      break;
    case ']':
      nudge(state.focusEdge, shift ? 0.01 : 0.1);
      break;
    case 'arrowleft':
      event.preventDefault();
      seekTo(currentTime() - (shift ? 0.1 : 2));
      break;
    case 'arrowright':
      event.preventDefault();
      seekTo(currentTime() + (shift ? 0.1 : 2));
      break;
    default:
      break;
  }
});

function currentTime() {
  return state.active === 'stem' && stemEngine.duration
    ? stemEngine.trackTime
    : (mix.engine?.time ?? 0);
}

// ── go ──────────────────────────────────────────────────────────────────────

$('picker').hidden = false;
refreshPicker();
requestAnimationFrame(tick);
