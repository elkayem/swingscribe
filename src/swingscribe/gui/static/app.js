/* SwingScribe — screens 1-3: load, select the span, audition the isolation.
 *
 * Everything that has to feel immediate happens here. The server is asked only
 * for things the browser cannot do: list files, read peaks, cut a span out of a
 * stem, and run Demucs. Dragging a loop point, nudging it a tenth of a second,
 * soloing a stem and switching isolated-against-original are all local.
 */

import { WaveView } from './waveform.js';
import { MixEngine, StemEngine } from './engine.js';
import { CLASSES, PianoRoll } from './review.js';

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
  beats: null,              // whole-file derived grid from /beats
  showBeats: true,          // draw the grid when we have one
  snapMode: 'off',          // off | beat | bar — what A/B placement snaps to
  timeSignature: null,      // null = server default (4/4)
  anchor: null,             // seconds; null = auto-detected downbeat
  barsPerChorus: 0,
  review: null,             // cached review payload {notes, diagnostics}
  reviewMode: 'mix',        // mix | transcription | both
  reviewRate: 1,
  reviewToken: 0,
  scorePath: null,          // hand transcription chosen for the overlay
  ground: null,             // the aligned overlay: classes, counts, placed notes
  gtClasses: [...CLASSES],  // which alignment classes are drawn
  formStart: null,          // seconds; where the tune's form begins (bar 1)
  click: false,             // mix a metronome onto the audition
};

const mix = { engine: null };
const stemEngine = new StemEngine();
const reviewEngine = new StemEngine();  // mix + synthesized transcription, its own A/B

// ── tiny helpers ────────────────────────────────────────────────────────────

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `${response.status}`;
    try { detail = (await response.json()).detail ?? detail; } catch { /* not json */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
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
  snap: (t) => snapTime(t),
  onBeatClick: (t) => setDownbeat(t),
  onFormClick: (t) => setFormStart(t),
  onWindowDrag: (start, width) => detail.setWindow(start, start + width),
});

const detail = new WaveView($('wave-detail'), {
  selectable: true,
  onSeek: (t) => seekTo(t),
  onSelect: (a, b, done) => updateSelection(a, b, done),
  onWindow: () => onDetailWindowChanged(),
  onEdgeFocus: (edge) => setFocusEdge(edge),
  snap: (t) => snapTime(t),
  onBeatClick: (t) => setDownbeat(t),
  onFormClick: (t) => setFormStart(t),
});

const stemWave = new WaveView($('wave-stem'), {
  onSeek: (t) => {
    if (!state.selection) return;
    stemEngine.seek((t - state.selection.a) / state.stemRate);
    state.active = 'stem';
  },
});

const pianoRoll = new PianoRoll($('pianoroll'), $('lane-f0'), $('lane-gate'), {
  onSelect: (note, index) => renderInspector(note, index),
  onSelectReference: (index) => renderReferenceInspector(index),
  onSeek: (t) => seekReviewTo(t),
  onView: (view, spanWidth) => renderRollRange(view, spanWidth),
});

// ── screen 1: the track picker ──────────────────────────────────────────────

// The last successful /api/browse response. Kept around so reopening the
// picker (or a failed navigation) returns to where you were, not the start.
let browseRoot = null;

/* The picker does double duty: 'track' opens audio, 'score' picks the hand
   transcription for the review overlay. Choosing a .mscz is the same
   navigation problem as choosing a track, so it reuses this browser rather
   than growing a second one — one folder history, one drive list, one set of
   keyboard behaviours. */
let pickerMode = 'track';

function openPicker(mode) {
  pickerMode = mode;
  const score = mode === 'score';
  $('picker-title').textContent = score ? 'Choose a hand transcription' : 'Open a track';
  $('picker-recent-title').textContent = score ? 'Beside this track' : 'Recent';
  $('path-input').placeholder = $('path-input').dataset[mode];
  $('path-input').value = '';
  $('picker').hidden = false;
  refreshPicker();
}

async function refreshPicker() {
  $('picker-error').hidden = true;
  try {
    if (pickerMode === 'score') {
      const found = await api(`/api/tracks/${state.track.id}/scores`);
      renderScoreList($('recent-list'), found.scores);
    } else {
      const tracks = await api('/api/tracks');
      renderTrackList($('recent-list'), tracks.recent);
    }
  } catch (error) {
    showPickerError(error.message);
  }
  await browseTo(browseRoot?.path ?? null);
}

/* Scores found beside the track. The name match is only a ranking — the
   benchmark names its scores after the soloist and its audio after the album
   track — so every candidate in the folder is listed and the matched ones
   simply come first, with the words they share shown as the reason. */
function renderScoreList(node, items) {
  node.innerHTML = '';
  if (!items.length) {
    node.innerHTML = '<li class="empty">No .mscz or .mscx beside this track</li>';
    return;
  }
  for (const item of items) {
    const li = document.createElement('li');
    li.innerHTML = '<span class="name"></span><span class="meta"></span>';
    li.querySelector('.name').textContent = item.name;
    li.querySelector('.meta').textContent = item.matched ? `matches “${item.shared.join(' ')}”` : '';
    li.addEventListener('click', () => chooseScore(item.path));
    node.appendChild(li);
  }
}

function renderTrackList(node, items) {
  node.innerHTML = '';
  if (!items.length) {
    node.innerHTML = '<li class="empty">Nothing yet</li>';
    return;
  }
  for (const item of items) {
    const li = document.createElement('li');
    // Recents describe the work done on a track: span and stem.
    const meta = item.region
      ? `${item.stem ?? 'no stem'} · ${clock(item.region[0], false)}–${clock(item.region[1], false)}`
      : (item.stem ?? '');
    li.innerHTML = `<span class="name"></span><span class="meta"></span>`;
    li.querySelector('.name').textContent = item.name;
    li.querySelector('.meta').textContent = meta;
    li.addEventListener('click', () => openTrack(item.path));
    node.appendChild(li);
  }
}

/* The folder browser: navigate to `path` (null = the configured library
   folder) and render its subfolders and audio files. This is what lets
   "Open track…" reach anywhere on disk without typing a path — the pasted-
   path box below stays as a fallback for anywhere you'd rather jump straight
   to. Errors (a locked folder, a path that no longer exists) show inline
   without losing the listing you were already looking at. */
async function browseTo(path) {
  try {
    const query = path ? `?path=${encodeURIComponent(path)}` : '';
    const data = await api(`/api/browse${query}`);
    browseRoot = data;
    renderBrowse(data);
    $('picker-error').hidden = true;
  } catch (error) {
    showPickerError(error.message);
  }
}

function renderBrowse(data) {
  $('browse-path').value = data.path;
  $('browse-up').disabled = !data.parent;

  const driveSelect = $('browse-drive');
  driveSelect.innerHTML = '';
  for (const drive of data.drives) {
    const option = document.createElement('option');
    option.value = drive;
    option.textContent = drive;
    driveSelect.appendChild(option);
  }
  const currentDrive = data.path.slice(0, 3);
  if (data.drives.includes(currentDrive)) driveSelect.value = currentDrive;

  const node = $('library-list');
  node.innerHTML = '';
  const scoring = pickerMode === 'score';
  const files = scoring ? (data.scores ?? []) : data.files;
  if (!data.dirs.length && !files.length) {
    node.innerHTML = scoring
      ? '<li class="empty">No folders or MuseScore files here</li>'
      : '<li class="empty">No folders or audio files here</li>';
    return;
  }
  for (const dir of data.dirs) {
    const li = document.createElement('li');
    li.className = 'dir';
    li.innerHTML = '<span class="name"></span>';
    li.querySelector('.name').textContent = dir.name;
    li.addEventListener('click', () => browseTo(dir.path));
    node.appendChild(li);
  }
  for (const file of files) {
    const li = document.createElement('li');
    const meta = Number.isFinite(file.size) ? `${(file.size / 1e6).toFixed(1)} MB` : '';
    li.innerHTML = '<span class="name"></span><span class="meta"></span>';
    li.querySelector('.name').textContent = file.name;
    li.querySelector('.meta').textContent = scoring ? '' : meta;
    li.addEventListener('click', () => (scoring ? chooseScore(file.path) : openTrack(file.path)));
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
  state.beats = null;
  state.showBeats = remembered.beats_shown ?? true;
  state.snapMode = remembered.snap_mode ?? 'off';
  state.timeSignature = remembered.time_signature ?? null;
  state.anchor = remembered.anchor ?? null;
  state.barsPerChorus = remembered.bars_per_chorus ?? 0;
  state.formStart = remembered.form_start ?? null;
  state.click = remembered.click ?? false;
  state.scorePath = remembered.score ?? null;
  clearGroundTruth();  // the score is remembered; its alignment to a previous track is not

  overview.setPeaks(await api(`/api/tracks/${track.id}/peaks`));
  overview.setWindow(0, track.duration, { silent: true });
  applySelection(true);
  focusDetail('fit');
  renderModels();
  setFocusEdge('a');
  seekTo(state.selection.a);
  await refreshAudition();
  await maybeLoadBeats();  // free when the CLI already tracked this track
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
  updateBars();
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

function setEdge(which, time, { snap = true } = {}) {
  if (!state.selection) return;
  if (snap) time = snapTime(time);
  const other = which === 'a' ? state.selection.b : state.selection.a;
  const a = which === 'a' ? time : other;
  const b = which === 'a' ? other : time;
  setFocusEdge(which);
  updateSelection(Math.min(a, b), Math.max(a, b), true);
  focusDetail(which);
}

/* Nudges never snap: after snapping an edge to the grid, ±0.1s/±0.01s is
   exactly how you correct the grid's small errors — snapping the nudge would
   make it a no-op. */
function nudge(which, delta) {
  if (!state.selection) return;
  const current = which === 'a' ? state.selection.a : state.selection.b;
  setEdge(which, Math.max(0, Math.min(state.track.duration, current + delta)), { snap: false });
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
  reviewEngine.pause();
  mix.engine?.seek(t);
  overview.setPlayhead(t);
  detail.setPlayhead(t);
}

function togglePlay() {
  if (state.active === 'review' && reviewEngine.duration) {
    reviewEngine.toggle();
  } else if (state.active === 'stem' && stemEngine.duration) {
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
  $('r-play').textContent = reviewEngine.playing ? '❚❚' : '▶';
}

function tick() {
  if (state.track) {
    // Keyed on which engine is *active*, not on which is playing: a paused
    // stem engine must hold its playhead where you stopped it rather than snap
    // back to wherever the mix transport happens to be.
    if (state.active === 'review' && reviewEngine.duration) {
      const t = reviewEngine.trackTime;
      if (reviewEngine.playing) pianoRoll.follow(t);  // a zoomed roll must keep up
      pianoRoll.setPlayhead(t);
      $('r-time-now').textContent = clock(reviewEngine.position * state.reviewRate);
      $('time-now').textContent = clock(t);
    } else if (state.active === 'stem' && stemEngine.duration) {
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

// ── the beat grid ───────────────────────────────────────────────────────────
// The grid the transcription will quantize against, drawn over the waveform so
// "did it hear the bars right?" is answerable before anything downstream runs.
// Whole-file and chained from the selected model's drum stem, so it loads free
// on any track the CLI has already processed and never re-runs per span.

function nearestIn(arr, t) {
  if (!arr || !arr.length) return null;
  let lo = 0;
  let hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  const before = arr[Math.max(0, lo - 1)];
  return t - before <= arr[lo] - t ? before : arr[lo];
}

const nearestBeat = (t) => nearestIn(state.beats?.beats, t);
const nearestBar = (t) => nearestIn((state.beats?.bars ?? []).map(([time]) => time), t);

/* Identity unless snapping is on and a grid is loaded, so gesture code can
   apply it unconditionally. Bar snapping is usually what's wanted — solos
   start on downbeats — with beat snapping as the finer fallback. */
function snapTime(t) {
  if (!state.beats?.beats?.length) return t;
  if (state.snapMode === 'bar') return nearestBar(t) ?? t;
  if (state.snapMode === 'beat') return nearestBeat(t) ?? t;
  return t;
}

/* Re-phase the whole bar grid onto this beat. One parameter, so it is a redraw
   rather than a re-analysis (docs/meter-plan.md). */
/* Where the tune's form starts. An intro is not part of the song structure, so
   bar 1 and the chorus count both begin here rather than at the first bar line. */
async function setFormStart(time) {
  if (!state.beats) return;
  // Snap to a bar line first: the server does this anyway when numbering, and
  // agreeing up front keeps the chip's readout honest.
  state.formStart = nearestBar(time) ?? time;
  await maybeLoadBeats();
  persist();
  toast(`Bar 1 at ${clock(state.formStart)} — chorus counts from here`);
}

async function setDownbeat(time) {
  if (!state.beats) return;
  state.anchor = time;
  await maybeLoadBeats();
  persist();
  toast(`Downbeat at ${clock(time)}`);
}

/* The free path: fetch the grid if it's cached, silently accept that it isn't.
   Computing is only ever started by an explicit click on the Beats chip. */
async function maybeLoadBeats() {
  if (!state.track || !state.model) return;
  const params = new URLSearchParams({ model: state.model });
  if (state.timeSignature) params.set('time_signature', state.timeSignature);
  if (state.anchor !== null) params.set('anchor', state.anchor.toFixed(3));
  if (state.barsPerChorus) params.set('bars_per_chorus', String(state.barsPerChorus));
  if (state.formStart !== null) params.set('form_start', state.formStart.toFixed(3));
  try {
    const grid = await api(`/api/tracks/${state.track.id}/beats?${params}`);
    state.beats = grid.ready ? grid : null;
  } catch {
    state.beats = null;
  }
  applyBeats();
}

function applyBeats() {
  const grid = state.beats && state.showBeats ? state.beats : null;
  detail.setBeats(grid);
  stemWave.setBeats(grid);

  const info = $('beats-info');
  info.hidden = !state.beats;
  if (state.beats) {
    // Name the free time and say where it is: a bare "free time" badge reads as
    // a claim about the whole tune rather than about twenty seconds of outro.
    const free = state.beats.free || [];
    const seconds = free.reduce((total, [a, b]) => total + (b - a), 0);
    const where = free.length === 1 ? ` at ${clock(free[0][0], false)}` : '';
    const note = seconds >= 1 ? ` · ${Math.round(seconds)}s unmetered${where}` : '';
    info.textContent = `≈${Math.round(state.beats.bpm)} bpm · ${state.beats.time_signature}${note}`;
    info.title = free.length
      ? `No steady pulse: ${free.map(([a, b]) => `${clock(a, false)}–${clock(b, false)}`).join(', ')}`
      : 'A steady pulse throughout';
  }
  const reset = $('form-reset');
  reset.hidden = state.formStart === null;
  if (state.formStart !== null) {
    reset.textContent = `bar 1 @ ${clock(state.formStart, false)} ✕`;
    reset.title = 'Clear the form start; bar 1 returns to the first bar line';
  }
  // The handoff command carries the meter, so it has to be rebuilt whenever the
  // grid arrives or changes — it is first built during load, before the grid
  // has been fetched.
  updateHandoff();
  $('beats-toggle').classList.toggle('active', Boolean(grid));
  refreshClicks();
  if (state.review) pianoRoll.setData({ a: state.selection.a, b: state.selection.b }, state.review, grid);

  const menu = $('time-signature');
  if (state.beats && !menu.options.length) {
    for (const name of state.beats.known_signatures) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      menu.appendChild(option);
    }
  }
  if (state.beats) menu.value = state.beats.time_signature;
  menu.disabled = !state.beats;
  $('chorus-bars').disabled = !state.beats;
  $('chorus-bars').value = String(state.barsPerChorus || 0);

  const snap = $('snap-toggle');
  snap.disabled = !state.beats;
  snap.textContent = `Snap: ${state.beats ? state.snapMode : 'off'}`;
  snap.classList.toggle('active', Boolean(state.beats) && state.snapMode !== 'off');
  updateBars();
}

/* "16 bars" under the span readout. Counting bar lines rather than seconds is
   the check that matters: a solo that comes out as 15 bars usually means a
   boundary parked mid-bar, or a downbeat one beat out. */
function updateBars() {
  const node = $('span-bars');
  if (!state.beats || !state.selection) { node.hidden = true; return; }
  const { a, b } = state.selection;
  const bars = state.beats.bars.filter(([t]) => t >= a && t < b).length;
  node.hidden = bars < 1;
  const chorus = state.barsPerChorus;
  node.textContent =
    chorus > 1 && bars % chorus === 0
      ? `${bars} bars · ${bars / chorus} chorus${bars / chorus === 1 ? '' : 'es'}`
      : `${bars} bars`;
}

async function toggleBeats() {
  if (state.beats) {
    state.showBeats = !state.showBeats;
    applyBeats();
    persist();
    return;
  }
  // No cached grid: compute one. Separation is usually already cached from the
  // audition, so this is mostly the beat tracker's cost, once per track+model.
  state.showBeats = true;
  const chip = $('beats-toggle');
  chip.disabled = true;
  chip.textContent = 'Beats…';
  try {
    const job = await post('/api/jobs', {
      path: state.track.path, model: state.model, kind: 'beats',
    });
    await pollBeatsJob(job.id, chip);
  } catch (error) {
    toast(error.message, true);
  }
  chip.disabled = false;
  chip.textContent = 'Beats';
  persist();
}

async function pollBeatsJob(jobId, chip) {
  const job = await watchJob(jobId, (update) => {
    chip.textContent = `Beats ${(update.fraction * 100).toFixed(0)}%`;
  });
  if (job && job.state === 'error') {
    toast(job.error, true);
    return;
  }
  // Also runs when contact was lost: the grid may be on disk regardless.
  await maybeLoadBeats();
  if (!job && !state.beats) toast('The beat grid did not finish — try again', true);
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
  // The grid chains from this model's drum stem, so it's per-model too.
  state.beats = null;
  applyBeats();
  renderModels();
  persist();
  await refreshAudition();
  await maybeLoadBeats();
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
  if (!ready) { stemEngine.reset(0, 1); $('panel-review').hidden = true; return; }
  await loadAudition();
  refreshReviewPanel();
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
  for (const [key, settings] of state.mixer) {
    if (!settings.muted && key !== CLICK_KEY) wanted.add(key);
  }

  try {
    await Promise.all([...wanted].map((key) => stemEngine.load(key, stemUrl(key))));
  } catch (error) {
    if (token === state.auditionToken) toast(`Audition: ${error.message}`, true);
    return;
  }
  if (token !== state.auditionToken) return;   // a newer span superseded this one

  applyMixer();
  refreshClicks();
  renderMixer();
  await drawStemOverlay(token);
  if (wasPlaying) stemEngine.play(0);
  invalidateReview();
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

const CLICK_KEY = 'click';

/* Rebuild the metronome for the current span and grid.

   This is the ear test for everything the meter work produces: a bar line one
   beat out is unmistakable against the music and easy to miss on screen. Bar
   lines get a high accent, chorus starts a higher one, ordinary beats a quiet
   tick. Rendered locally rather than fetched, so it re-renders the instant you
   move the downbeat. */
function refreshClicks() {
  if (!state.click || !state.beats || !state.selection || !stemEngine.duration) {
    stemEngine.drop(CLICK_KEY);
    return;
  }
  const { a, b } = state.selection;
  // Span-local seconds: at half speed the buffer is twice as long, so a beat
  // one second into the music sits two seconds into the buffer.
  const toBuffer = (t) => (t - a) / state.stemRate;
  const bars = new Map(state.beats.bars.map(([time, number]) => [time, number]));
  const chorus = new Set(state.beats.chorus_bars || []);
  const events = [];
  for (const time of state.beats.beats) {
    if (time < a || time >= b) continue;
    if (chorus.has(time)) events.push({ time: toBuffer(time), frequency: 1600, gain: 0.5 });
    else if (bars.has(time)) events.push({ time: toBuffer(time), frequency: 1200, gain: 0.42 });
    else events.push({ time: toBuffer(time), frequency: 800, gain: 0.16 });
  }
  stemEngine.renderClicks(CLICK_KEY, events, stemEngine.duration);
  const settings = state.mixer.get(CLICK_KEY) ?? { level: 0.8, muted: false };
  state.mixer.set(CLICK_KEY, settings);
  stemEngine.setLevel(CLICK_KEY, settings.level);
  stemEngine.setMuted(CLICK_KEY, settings.muted);
}

function mixerKeys() {
  return state.click ? ['mix', ...state.stems, CLICK_KEY] : ['mix', ...state.stems];
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
      <span class="stem-name">${key === 'mix' ? 'original mix' : key === CLICK_KEY ? 'click' : key}${isLead ? '<span class="lead-tag">lead</span>' : ''}</span>
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
  // The click is a reference, not one of the things being compared — the A/B
  // switch must leave it running or it stops being a reference.
  if (key === CLICK_KEY) return true;
  if (state.abMode === 'both') return key === 'mix' || key === state.leadStem;
  if (state.abMode === 'mix') return key === 'mix';
  return key === state.leadStem;
}

async function toggleStem(key) {
  const settings = state.mixer.get(key);
  settings.muted = !settings.muted;
  if (!settings.muted && !stemEngine.has(key) && key !== CLICK_KEY) {
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

const LOST_JOB_TRIES = 5;

/* Watch a background job to completion. Resolves with the finished job, or
   null when contact is lost.

   Losing contact has to be handled, not ignored: the job lives in the server
   process, so restarting the server orphans it. Swallowing the error and
   retrying forever leaves a progress chip frozen at some percentage with
   nothing behind it — which is exactly what a stuck "Beats 72%" was.

   A 404 means the job is gone for good, so give up at once; anything else gets
   a few retries in case the server is merely busy. Either way the caller
   re-checks disk afterwards, because the work may well have finished. */
function watchJob(jobId, onProgress) {
  return new Promise((resolve) => {
    let failures = 0;
    const timer = setInterval(async () => {
      let job;
      try {
        job = await api(`/api/jobs/${jobId}`);
        failures = 0;
      } catch (error) {
        const gone = error.status === 404;
        failures += 1;
        if (gone || failures >= LOST_JOB_TRIES) {
          clearInterval(timer);
          toast(
            gone
              ? 'Lost that job — the server restarted. Checking what finished…'
              : 'Lost contact with the server. Checking what finished…',
            true,
          );
          resolve(null);
        }
        return;
      }
      onProgress(job);
      if (job.state === 'done' || job.state === 'error') {
        clearInterval(timer);
        resolve(job);
      }
    }, 1000);
  });
}

async function pollJob(jobId) {
  const job = await watchJob(jobId, (update) => {
    $('job-fill').style.width = `${(update.fraction * 100).toFixed(1)}%`;
    $('job-message').textContent = update.message || update.state;
    $('job-elapsed').textContent = `${clock(update.elapsed, false)} elapsed`;
  });
  $('separate-btn').disabled = false;
  $('job').hidden = true;
  if (job && job.state === 'error') {
    toast(job.error, true);
    return;
  }
  if (job) toast(`${job.model}: ${job.stems.length} stems ready`);
  // Re-read from disk either way: a job we lost contact with may have finished.
  state.track = await api('/api/tracks/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: state.track.path }),
  }).catch(() => state.track);
  await refreshAudition();
}

// ── screen 4: transcribe & review ────────────────────────────────────────────
// A note list is a picture; a note list wired to the frame trace is a
// diagnostic. Transcription runs as a background job (the CREPE pass only,
// since separation is cached), then the piano roll draws the notes over the
// same bar grid the selection screen uses, with the per-frame evidence beneath.

function reviewParams(extra) {
  const { a, b } = state.selection;
  return new URLSearchParams(Object.assign({
    model: state.model,
    stem: state.leadStem,
    start: a.toFixed(3),
    end: b.toFixed(3),
  }, extra || {}));
}

/* The review belongs to one span+stem. When either changes the old notes are
   stale, so drop back to the Transcribe button rather than showing notes that
   describe a different passage. */
function invalidateReview() {
  state.review = null;
  reviewEngine.stop();
  reviewEngine.reset(0, 1);
  if (state.active === 'review') state.active = 'mix';
  $('review').hidden = true;
  $('review-summary').hidden = true;
  $('transcribe-btn').disabled = false;
  $('transcribe-btn').textContent = 'Transcribe span';
  // The overlay is an alignment *to* these notes, so it dies with them — but
  // the chosen score does not: it is still the right score for the next
  // transcription of this solo.
  clearGroundTruth();
  refreshReviewPanel();
}

async function refreshReviewPanel() {
  const shown = Boolean(state.selection && state.leadStem && state.stems.length);
  $('panel-review').hidden = !shown;
  if (!shown) return;
  const { a, b } = state.selection;
  $('review-range').textContent = `${state.leadStem} · ${clock(a, false)}–${clock(b, false)}`;
  if (!state.review) {
    try {
      const payload = await api(`/api/tracks/${state.track.id}/review?${reviewParams()}`);
      if (payload.ready) await showReview(payload);
    } catch (e) { /* not transcribed yet — the button stands */ }
  }
}

async function startTranscribe() {
  if (!state.selection || !state.leadStem) return;
  const btn = $('transcribe-btn');
  btn.disabled = true;
  $('review-job').hidden = false;
  try {
    const { a, b } = state.selection;
    const job = await post('/api/jobs', {
      path: state.track.path, model: state.model, kind: 'transcribe',
      stem: state.leadStem, start: a, end: b,
    });
    const finished = await watchJob(job.id, (update) => {
      $('review-job-fill').style.width = `${(update.fraction * 100).toFixed(1)}%`;
      $('review-job-message').textContent = update.message || update.state;
      $('review-job-elapsed').textContent = `${clock(update.elapsed, false)} elapsed`;
    });
    $('review-job').hidden = true;
    btn.disabled = false;
    if (finished && finished.state === 'error') { toast(finished.error, true); return; }
    const payload = await api(`/api/tracks/${state.track.id}/review?${reviewParams()}`);
    if (payload.ready) await showReview(payload);
    else if (!finished) toast('Transcription did not finish — try again', true);
  } catch (error) {
    $('review-job').hidden = true;
    btn.disabled = false;
    toast(error.message, true);
  }
}

async function showReview(payload) {
  state.review = payload;
  state.reviewToken += 1;
  $('review').hidden = false;
  $('transcribe-btn').textContent = 'Re-transcribe';
  const notes = payload.notes.length;
  const voiced = Math.round(payload.diagnostics.voiced_fraction * 100);
  const fragments = countFragments(payload.notes);
  $('review-summary').hidden = false;
  $('review-summary').textContent =
    `${notes} notes · ${voiced}% voiced` +
    (fragments ? ` · ${fragments} split same-pitch pair${fragments === 1 ? '' : 's'}` : '');
  $('review-summary').title = fragments
    ? 'Consecutive notes at the same pitch, butted together — usually one held note broken up (open issue #1). Click one to see what split it.'
    : 'No same-pitch fragmentation detected in this span';
  $('review-hint').textContent = `${notes} notes`;
  $('r-time-total').textContent = clock(state.selection.b - state.selection.a, false);
  pianoRoll.opts.voicingThreshold = 0.5;
  pianoRoll.setData({ a: state.selection.a, b: state.selection.b }, payload, state.showBeats ? state.beats : null);
  // Park the marker at the start rather than leaving it undrawn: a playhead
  // you cannot see is not obviously one you can move.
  pianoRoll.setPlayhead(state.selection.a);
  renderInspector(null, -1);
  await loadGroundTruth();
  await loadReviewAudio();
}

/* Put the review playhead at a track time. The engine counts in the span's own
   stretched timeline, so a half-speed span is twice as long as the music it
   holds — hence the divide by the rate rather than a straight subtraction. */
function seekReviewTo(t) {
  if (!state.selection || !state.review) return;
  const { a, b } = state.selection;
  const clamped = Math.min(b, Math.max(a, t));
  pianoRoll.setPlayhead(clamped);
  $('r-time-now').textContent = clock(clamped - a);
  if (!reviewEngine.duration) return;  // marker still moves before the audio lands
  state.active = 'review';
  mix.engine?.pause();
  stemEngine.pause();
  reviewEngine.seek((clamped - a) / state.reviewRate);
  refreshPlayButtons();
}

/* Only shown while zoomed: at full extent the range is the span, which the
   review bar already says. */
function renderRollRange(view, spanWidth) {
  const node = $('roll-range');
  const width = view.b - view.a;
  const zoomed = width < spanWidth - 1e-6;
  node.hidden = !zoomed;
  // Below ten seconds m:ss reads "1:01–1:01" and says nothing; the tight end
  // of the zoom is exactly where the hundredths matter.
  const precise = width < 10;
  if (zoomed) node.textContent = `${clock(view.a, precise)}–${clock(view.b, precise)}`;
}

async function loadReviewAudio() {
  const token = state.reviewToken;
  const { a } = state.selection;
  reviewEngine.reset(a, state.reviewRate);
  const mixUrl = `/api/tracks/${state.track.id}/stem?${reviewParams({ stem: 'mix', rate: String(state.reviewRate) })}`;
  const transUrl = `/api/tracks/${state.track.id}/transcription?${reviewParams({ rate: String(state.reviewRate) })}`;
  try {
    await Promise.all([
      reviewEngine.load('mix', mixUrl),
      reviewEngine.load('transcription', transUrl),
    ]);
  } catch (error) {
    if (token === state.reviewToken) toast(`Ear test: ${error.message}`, true);
    return;
  }
  if (token !== state.reviewToken) return;
  applyReviewMode();
}

function applyReviewMode() {
  const audible = {
    mix: state.reviewMode !== 'transcription',
    transcription: state.reviewMode !== 'mix',
  };
  for (const key of ['mix', 'transcription']) {
    if (reviewEngine.has(key)) reviewEngine.setMuted(key, !audible[key]);
  }
  for (const button of $('review-ab').querySelectorAll('button')) {
    button.classList.toggle('active', button.dataset.rab === state.reviewMode);
  }
}

/* The inspector is the point of the screen: why is this note what it is? */
function renderInspector(note, index) {
  const empty = $('inspector-empty');
  const body = $('inspector-body');
  if (!note) { empty.hidden = false; body.hidden = true; return; }
  empty.hidden = true;
  body.hidden = false;

  const frames = pianoRoll.framesFor(note);
  const diag = state.review.diagnostics;
  const periods = frames.map((i) => diag.periodicity[i]).filter((v) => v !== undefined);
  const meanPeriod = periods.length ? periods.reduce((s2, v) => s2 + v, 0) / periods.length : 0;
  const gatedOut = frames.filter((i) => diag.energy_ok[i] === false).length;
  const raw = frames.map((i) => diag.f0_midi[i]).filter((v) => v !== null);
  const f0Spread = raw.length ? Math.max(...raw) - Math.min(...raw) : 0;
  const onsetAtStart = diag.onsets.some((t) => Math.abs(t - note.onset) < 0.03);

  body.innerHTML =
    `<div class="inspector-head">` +
    `<span class="pitch">${midiName(note.pitch)} <span class="muted">(${note.pitch})</span></span>` +
    `<span class="timing">${clock(note.onset)} · ${(note.duration * 1000).toFixed(0)}ms · conf ${note.confidence.toFixed(2)}</span>` +
    `</div><div class="inspector-why"></div><div class="inspector-note"></div>`;
  const why = body.querySelector('.inspector-why');
  const chip = (text, kind) => {
    const el = document.createElement('span');
    el.className = `why-chip ${kind || ''}`;
    el.textContent = text;
    why.appendChild(el);
  };
  chip(`${frames.length} frames`);
  chip(`periodicity ${meanPeriod.toFixed(2)}`, meanPeriod >= 0.5 ? 'ok' : 'flag');
  if (gatedOut) chip(`${gatedOut} energy-gated`, 'flag');
  chip(`f0 spread ${f0Spread.toFixed(2)} st`, f0Spread > 1 ? 'flag' : 'ok');
  if (onsetAtStart) chip('onset at start', 'flag');

  const remarks = [];
  const previous = index > 0 ? state.review.notes[index - 1] : null;
  const fragment = isFragmentOf(previous, note);
  if (fragment) chip('split from previous', 'flag');

  // What the hand transcription says about this note, if one is loaded.
  const verdict = state.ground?.estimate_class[index];
  if (verdict) {
    chip(CLASS_LABEL[verdict], verdict === 'matched' ? 'ok' : 'flag');
    const partner = state.ground.estimate_partner[index];
    if (verdict === 'wrong' && partner !== null) {
      const notated = state.ground.reference_notes[partner];
      const delta = note.pitch - notated.pitch;
      remarks.push(
        `Notated ${midiName(notated.pitch)} in bar ${notated.bar} — we are ${Math.abs(delta)} ` +
          `semitone${Math.abs(delta) === 1 ? '' : 's'} ${delta > 0 ? 'high' : 'low'}. ` +
          (Math.abs(delta) <= 2
            ? 'Close enough to be the player’s own inflection rather than a tracking error.'
            : 'Far enough to be a different note: an octave error, or another instrument.'),
      );
    } else if (verdict === 'invented') {
      remarks.push('Nothing in the hand transcription aligns to this note.');
    }
  }

  if (meanPeriod < 0.5) remarks.push('Low periodicity — the transcriber was unsure this frame was pitched.');
  if (gatedOut) remarks.push('Some frames failed the energy gate; the note may be clipped.');

  if (fragment) {
    // Same pitch, butted against the previous note: one held note got broken.
    // Which mechanism did it matters — an onset means the detector fired on
    // something else in the stem (open issue #1); no onset means a gate
    // momentarily dropped the pitch out. Reporting "fragmented" without saying
    // which would leave the actual question unanswered.
    if (onsetAtStart) {
      remarks.push(
        'Same pitch as the previous note and split at a detected onset — the onset detector fires on the whole stem, so comping or drum bleed can break a note the soloist is holding (open issue #1).',
      );
    } else {
      const gapFrames = framesBetween(previous, note);
      const unvoiced = gapFrames.filter((i) => diag.pitch[i] === null).length;
      const energyDrop = gapFrames.filter((i) => diag.energy_ok[i] === false).length;
      remarks.push(
        unvoiced
          ? `Same pitch as the previous note, split without an onset — ${unvoiced} frame${unvoiced === 1 ? '' : 's'} in between lost pitch${energyDrop ? ' (energy gate)' : ' (periodicity gate)'}, so a held note was cut in two.`
          : 'Same pitch as the previous note, split without an onset or a gate dropout — the pitch tracker likely wavered past the persistence threshold.',
      );
    }
  }

  if (f0Spread > 1) remarks.push('Wide f0 spread — a scoop, a bend, or an unstable pitch.');
  body.querySelector('.inspector-note').textContent = remarks.join(' ');
}

/* Frame indices strictly between two notes — the gap that a split happened in. */
function framesBetween(previous, note) {
  if (!previous || !state.review) return [];
  const { hop_s, start, frames } = state.review.diagnostics;
  const from = Math.max(0, Math.round((previous.onset + previous.duration - start) / hop_s));
  const to = Math.min(frames - 1, Math.round((note.onset - start) / hop_s));
  const out = [];
  for (let i = from; i <= to; i++) out.push(i);
  return out;
}

function midiName(pitch) {
  const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  return `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}

// ── the ground-truth overlay ────────────────────────────────────────────────
// Scoring prints numbers, and numbers say how much is wrong without saying
// what kind. A spurious note a semitone from a real one is the soloist's own
// scoop; one fifteen semitones down is another instrument. Same count,
// opposite fixes — and obvious on a roll.

const CLASS_LABEL = {
  matched: 'matched',
  wrong: 'wrong note',
  invented: 'invented',
  missed: 'missed',
};

/* Adopt a score only if the server accepts it. A rejected file must not
   silently replace the one that was working — and must not be persisted,
   which would resurrect it on the next open. */
async function chooseScore(path) {
  const previous = state.scorePath;
  state.scorePath = path;
  $('picker').hidden = true;
  if ((await loadGroundTruth()) === 'failed') {
    state.scorePath = previous;
    // Put the working overlay back rather than leaving the roll bare: the
    // previous alignment is cached, so this costs nothing.
    await loadGroundTruth();
    return;
  }
  persist();
}

function clearGroundTruth({ forget = false } = {}) {
  state.ground = null;
  if (forget) state.scorePath = null;
  pianoRoll.setGroundTruth(null);
  renderGroundTruthBar();
  if (forget) persist();
}

/* -> 'ok' | 'pending' (nothing transcribed yet) | 'failed' (the server said no). */
async function loadGroundTruth() {
  if (!state.review || !state.scorePath || !state.track) {
    renderGroundTruthBar();
    return 'pending';
  }
  $('gt-info').textContent = 'Aligning…';
  try {
    const params = reviewParams({ score: state.scorePath });
    state.ground = await api(`/api/tracks/${state.track.id}/ground-truth?${params}`);
  } catch (error) {
    state.ground = null;
    pianoRoll.setGroundTruth(null);
    renderGroundTruthBar();
    toast(`Ground truth: ${error.message}`, true);
    return 'failed';
  }
  pianoRoll.setVisibleClasses(state.gtClasses);
  pianoRoll.setGroundTruth(state.ground);
  renderGroundTruthBar();
  return 'ok';
}

function renderGroundTruthBar() {
  const info = $('gt-info');
  const classes = $('gt-classes');
  const caveat = $('gt-caveat');
  $('gt-clear').hidden = !state.scorePath;
  if (!state.ground) {
    info.textContent = state.scorePath
      ? `${state.scorePath.split(/[\\/]/).pop()} — transcribe the span to align it`
      : 'No hand transcription loaded';
    classes.hidden = true;
    caveat.hidden = true;
    return;
  }

  const s = state.ground.score;
  const transposed =
    s.transposition === 0
      ? 'written at concert pitch'
      : `written ${s.transposition > 0 ? '+' : ''}${s.transposition} semitones`;
  info.textContent =
    `${s.name} · ${s.bars} bars → ${s.implied_bpm} bpm · ` +
    `${transposed} · F1 ${state.ground.pitch_f1.toFixed(3)}`;
  info.title =
    'Bars over the span give the implied tempo — a wildly wrong value means the span is not ' +
    'the one this score was written against. The transposition is measured, not assumed.';

  classes.hidden = false;
  classes.innerHTML = '';
  for (const name of CLASSES) {
    const button = document.createElement('button');
    button.className = `chip gt-chip gt-${name}${state.gtClasses.includes(name) ? ' active' : ''}`;
    button.textContent = `${CLASS_LABEL[name]} ${state.ground.counts[name]}`;
    button.addEventListener('click', () => toggleGroundClass(name));
    classes.appendChild(button);
  }

  // Horizontal position is derived from the alignment, so an aligned pair
  // sits at the same x by construction. Saying so on screen is the only thing
  // stopping the picture being read as a timing result.
  caveat.hidden = false;
  caveat.textContent = `placed by alignment, not by time (${s.drift_s}s off constant tempo)`;
  caveat.title =
    'Every notated note that aligned to one of ours is drawn at that note’s onset, and the ' +
    'rest are interpolated between those anchors. So horizontal agreement is by construction — ' +
    'this view answers pitch, not timing. The figure is how far that placement had to move the ' +
    'score away from a constant tempo.';
}

function toggleGroundClass(name) {
  state.gtClasses = state.gtClasses.includes(name)
    ? state.gtClasses.filter((c) => c !== name)
    : [...state.gtClasses, name];
  pianoRoll.setVisibleClasses(state.gtClasses);
  renderGroundTruthBar();
}

/* A notated note has no frames behind it, so its inspector is a different
   thing from a transcribed note's: what was written, where, and whether we
   produced anything for it. */
function renderReferenceInspector(index) {
  const note = state.ground?.reference_notes[index];
  if (!note) return;
  $('inspector-empty').hidden = true;
  const body = $('inspector-body');
  body.hidden = false;
  const written =
    note.written === note.pitch
      ? ''
      : ` <span class="muted">written ${midiName(note.written)}</span>`;
  body.innerHTML =
    `<div class="inspector-head">` +
    `<span class="pitch">${midiName(note.pitch)} <span class="muted">(${note.pitch})</span>${written}</span>` +
    `<span class="timing">notated · bar ${note.bar} · ~${clock(note.x)}</span>` +
    `</div><div class="inspector-why"></div><div class="inspector-note"></div>`;
  const why = body.querySelector('.inspector-why');
  const chip = (text, kind) => {
    const el = document.createElement('span');
    el.className = `why-chip ${kind || ''}`;
    el.textContent = text;
    why.appendChild(el);
  };
  chip(CLASS_LABEL[note.cls], note.cls === 'matched' ? 'ok' : 'flag');

  const remarks = ['From the hand transcription, not from the audio.'];
  if (note.cls === 'missed') {
    remarks.push('We produced nothing that aligned to this note — a note the transcriber heard and we did not.');
  } else if (note.cls === 'wrong' && note.partner !== null) {
    const ours = state.review.notes[note.partner];
    const delta = ours.pitch - note.pitch;
    remarks.push(
      `We produced ${midiName(ours.pitch)} here, ${Math.abs(delta)} semitone${
        Math.abs(delta) === 1 ? '' : 's'
      } ${delta > 0 ? 'above' : 'below'}. ${
        Math.abs(delta) <= 2
          ? 'That close is usually the player’s own scoop or passing tone rather than a tracking failure.'
          : 'That far is a different note, not an inflection — an octave error or another instrument.'
      }`,
    );
  }
  remarks.push('Its horizontal position comes from the alignment, so do not read it as a timing.');
  body.querySelector('.inspector-note').textContent = remarks.join(' ');
}

const FRAGMENT_GAP_S = 0.12;

/* Two consecutive notes at the same pitch, butted together, are almost always
   one held note that got broken — the signature of open issue #1. Worth
   counting for the whole span, because the count is the first thing that tells
   you whether the transcription is fragmenting. */
function isFragmentOf(previous, note) {
  return (
    previous &&
    previous.pitch === note.pitch &&
    Math.abs(previous.onset + previous.duration - note.onset) < FRAGMENT_GAP_S
  );
}

function countFragments(notes) {
  let pairs = 0;
  for (let i = 1; i < notes.length; i++) if (isFragmentOf(notes[i - 1], notes[i])) pairs += 1;
  return pairs;
}

// ── handoff & persistence ───────────────────────────────────────────────────

function updateHandoff() {
  if (!state.track || !state.selection) return;
  if (!state.leadStem) {
    $('cli-command').textContent = 'Separate the track to get a transcription command';
    return;
  }
  const { a, b } = state.selection;
  let command =
    `uv run swingscribe ab "${state.track.path}" --stem ${state.leadStem} ` +
    `--start ${a.toFixed(2)} --end ${b.toFixed(2)}`;
  // The meter you settled on has to travel with the span, or transcription
  // quantizes against a different grid than the one you just verified.
  if (state.beats) {
    command += ` --time-signature ${state.beats.time_signature}`;
    if (state.beats.anchor !== null) command += ` --downbeat ${state.beats.anchor.toFixed(2)}`;
  }
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
        beats_shown: state.showBeats,
        snap_mode: state.snapMode,
        time_signature: state.timeSignature,
        anchor: state.anchor,
        bars_per_chorus: state.barsPerChorus,
        form_start: state.formStart,
        click: state.click,
        score: state.scorePath,
      },
    }).catch(() => { /* remembering where you were is not worth an error */ });
  }, 500);
}

// ── events ──────────────────────────────────────────────────────────────────

$('open-picker').addEventListener('click', () => openPicker('track'));
$('picker-close').addEventListener('click', () => { $('picker').hidden = true; });

const openTypedPath = () => {
  const path = $('path-input').value.trim();
  if (path) (pickerMode === 'score' ? chooseScore : openTrack)(path);
};
$('path-open').addEventListener('click', openTypedPath);
$('path-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') openTypedPath();
});

$('r-restart').addEventListener('click', () => {
  if (!reviewEngine.duration) return;
  state.active = 'review';
  mix.engine?.pause();
  stemEngine.pause();
  restartFromA();
  refreshPlayButtons();
});

/* Zoom about the playhead when it is on screen — that is what you are looking
   at — and about the middle of the view otherwise. */
for (const button of document.querySelectorAll('[data-roll-zoom]')) {
  button.addEventListener('click', () => {
    const t = pianoRoll.playhead;
    const inView = t !== null && t >= pianoRoll.view.a && t <= pianoRoll.view.b;
    pianoRoll.zoomBy(button.dataset.rollZoom === 'in' ? 1 / 1.6 : 1.6, inView ? t : null);
  });
}
$('roll-fit').addEventListener('click', () => pianoRoll.fit());

$('gt-pick').addEventListener('click', () => openPicker('score'));
$('gt-clear').addEventListener('click', () => clearGroundTruth({ forget: true }));

$('browse-up').addEventListener('click', () => {
  if (browseRoot?.parent) browseTo(browseRoot.parent);
});
$('browse-drive').addEventListener('change', (event) => browseTo(event.target.value));
$('browse-path').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') browseTo(event.target.value.trim());
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

$('transcribe-btn').addEventListener('click', startTranscribe);

$('r-play').addEventListener('click', () => {
  state.active = 'review';
  mix.engine?.pause();
  stemEngine.pause();
  reviewEngine.toggle();
  refreshPlayButtons();
});

for (const button of $('review-ab').querySelectorAll('button')) {
  button.addEventListener('click', () => {
    state.reviewMode = button.dataset.rab;
    applyReviewMode();
  });
}

for (const button of $('review-rate').querySelectorAll('button')) {
  button.addEventListener('click', async () => {
    state.reviewRate = Number(button.dataset.rrate);
    for (const other of $('review-rate').querySelectorAll('button')) {
      other.classList.toggle('active', other === button);
    }
    // Stretched server-side, so mix and transcription stay sample-locked.
    if (state.review) await loadReviewAudio();
  });
}
$('review-rate').querySelector('[data-rrate="1"]').classList.add('active');

$('beats-toggle').addEventListener('click', toggleBeats);

$('click-toggle').addEventListener('click', () => {
  state.click = !state.click;
  $('click-toggle').classList.toggle('active', state.click);
  refreshClicks();
  renderMixer();
  persist();
});
$('snap-toggle').addEventListener('click', () => {
  if (!state.beats) return;
  const order = ['off', 'bar', 'beat'];
  state.snapMode = order[(order.indexOf(state.snapMode) + 1) % order.length];
  applyBeats();
  persist();
});

$('restart').addEventListener('click', () => restartFromA());

$('form-reset').addEventListener('click', async () => {
  state.formStart = null;
  await maybeLoadBeats();
  persist();
});

$('time-signature').addEventListener('change', async (event) => {
  state.timeSignature = event.target.value;
  await maybeLoadBeats();
  persist();
});

$('chorus-bars').addEventListener('change', async (event) => {
  state.barsPerChorus = Number(event.target.value);
  await maybeLoadBeats();
  persist();
});

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
    case 's':
      $('snap-toggle').click();
      break;
    case 'c':
      $('click-toggle').click();
      break;
    case 'f':
      // Same idea as D, for the form: whichever bar you are nearest becomes
      // bar 1. Clicking an exact dot is precise but fiddly; this is neither.
      if (state.beats) {
        const bar = nearestBar(currentTime());
        if (bar !== null) setFormStart(bar);
      }
      break;
    case 'd':
      // The better gesture while the music is playing: whichever beat you are
      // nearest becomes beat 1.
      if (state.beats) {
        const beat = nearestBeat(currentTime());
        if (beat !== null) setDownbeat(beat);
      }
      break;
    case 'enter':
      event.preventDefault();
      restartFromA();
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

/* Back to A and play. The transport plays from the playhead, which is what you
   want while hunting for a boundary — but once the span is set, "again from the
   top" is the gesture you reach for over and over. */
function restartFromA() {
  if (!state.selection) return;
  if (state.active === 'review' && reviewEngine.duration) {
    reviewEngine.seek(0);
    if (!reviewEngine.playing) reviewEngine.play(0);
    pianoRoll.setPlayhead(state.selection.a);
    pianoRoll.follow(state.selection.a);
  } else if (state.active === 'stem' && stemEngine.duration) {
    stemEngine.seek(0);
    if (!stemEngine.playing) stemEngine.play(0);
  } else {
    seekTo(state.selection.a);
    mix.engine?.play();
  }
  refreshPlayButtons();
}

function currentTime() {
  return state.active === 'stem' && stemEngine.duration
    ? stemEngine.trackTime
    : (mix.engine?.time ?? 0);
}

// ── go ──────────────────────────────────────────────────────────────────────

$('picker').hidden = false;
refreshPicker();
requestAnimationFrame(tick);
