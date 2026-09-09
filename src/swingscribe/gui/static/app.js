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
import { initStorage } from './storage.js';
import { playPitch } from './tone.js';
import { RateControl } from './rate.js';

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
  showSecond: true,         // draw the piano second-voice overlay when there is one
  snapMode: 'off',          // off | beat | bar — what A/B placement snaps to
  timeSignature: null,      // null = server default (4/4)
  anchor: null,             // seconds; null = auto-detected downbeat
  barsPerChorus: 0,
  review: null,             // cached review payload {notes, diagnostics}
  reviewMode: 'mix',        // mix | transcription | both
  reviewRate: 1,
  reviewToken: 0,
  tool: 'inspect',          // inspect | erase — what a click on the roll does
  silenced: new Set(),      // note indices marked "heard right, not the solo"
  carried: [],              // stored erasures with no note in this transcription
  added: new Set(),         // candidate indices the listener switched on (piano)
  carriedAdditions: [],     // stored additions with no candidate in this pool
  unmatchedAdditions: [],   // the subset of those inside the span
  unmatched: [],            // the subset of those inside the span — worth reporting
  moved: [],                // of those, the ones with a note still sounding there
  undoStack: [],            // whole-state snapshots; see pushHistory
  redoStack: [],
  scorePath: null,          // hand transcription chosen for the overlay
  ground: null,             // the aligned overlay: classes, counts, placed notes
  gtClasses: [...CLASSES],  // which alignment classes are drawn
  formStart: null,          // seconds; where the tune's form begins (bar 1)
  click: false,             // mix a metronome onto the audition
  ensemble: null,           // horn-led | trio | solo-piano; null = server default
  line: null,               // crepe | oracle: which detector supplies a pianist's line
  transposition: null,      // the exported part's key; null = server default
  exported: null,           // {path, bars, notes, ...} from the last export
  exportedAt: null,         // what the tree looked like when it was written
  notationScore: null,      // {rhythm, value, matched} against the hand transcription
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
  dragPans: true,   // only the A/B handles change the selection here
  onSeek: (t) => seekTo(t),
  onSelect: (a, b, done) => updateSelection(a, b, done),
  onWindow: () => onDetailWindowChanged(),
  onEdgeFocus: (edge) => setFocusEdge(edge),
  snap: (t) => snapTime(t),
  onBeatClick: (t) => setDownbeat(t),
  onFormClick: (t) => setFormStart(t),
});

const stemWave = new WaveView($('wave-stem'), {
  dragPans: true,
  onWindow: () => renderAuditionRange(),
  onSeek: (t) => {
    if (!state.selection) return;
    activate('stem');
    stemEngine.seek((t - state.selection.a) / state.stemRate);
  },
});

const pianoRoll = new PianoRoll($('pianoroll'), $('lane-f0'), $('lane-gate'), {
  // Inspecting a note sounds it too, as the Edit tool does: the question a
  // click asks — is this the note that was played? — is answered by ear.
  onSelect: (note, index) => { renderInspector(note, index); sound(note); },
  onSelectReference: (index) => {
    renderReferenceInspector(index);
    sound(state.ground?.reference_notes[index]);
  },
  onSelectCandidate: (index) => {
    renderCandidateInspector(index);
    sound(state.review?.candidates[index]);
  },
  onSeek: (t) => seekReviewTo(t),
  onView: (view, spanWidth) => renderRollRange(view, spanWidth),
  onToggleSilence: (index) => toggleSilence(index),
  onToggleAdd: (index) => toggleAdd(index),
  onBand: (indices, restoring) => silenceRun(indices, restoring),
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

// The cache panel under Recent: per-track stems and wavs, with a delete on
// each. Lives in storage.js; it only needs the fetch helper, the toast, and
// a way to refresh the model chips when the open track loses its stems.
const storagePanel = initStorage({
  api,
  toast,
  currentTrackId: () => state.track?.id ?? null,
  onChanged: () => refreshModelStatus(),
});

function openPicker(mode) {
  pickerMode = mode;
  const score = mode === 'score';
  $('picker-title').textContent = score ? 'Choose a hand transcription' : 'Open a track';
  $('picker-recent-title').textContent = score ? 'Beside this track' : 'Recent';
  $('path-input').placeholder = $('path-input').dataset[mode];
  $('path-input').value = '';
  $('picker-storage').hidden = score;  // a .mscz picker has no cache to manage
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
      storagePanel.refreshIfOpen();
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
  // A track opened for the first time starts with the whole of it selected —
  // the listener narrows the span to the solo from there, and nothing they
  // have not chosen yet is hidden off the edge of the Detail view.
  state.selection = Array.isArray(region) && region.length === 2 && region[1] > region[0]
    ? { a: region[0], b: Math.min(region[1], track.duration) }
    : { a: 0, b: track.duration };
  state.model = remembered.model ?? track.models.find((m) => m.ready)?.model
    ?? track.models[0]?.model;
  state.leadStem = remembered.stem ?? null;
  state.mixer.clear();
  state.beats = null;
  state.showBeats = remembered.beats_shown ?? true;
  state.snapMode = remembered.snap_mode ?? 'off';
  state.timeSignature = remembered.time_signature ?? null;
  state.doubleTime = Boolean(remembered.double_time);
  state.anchor = remembered.anchor ?? null;
  state.barsPerChorus = remembered.bars_per_chorus ?? 0;
  state.formStart = remembered.form_start ?? null;
  state.click = remembered.click ?? false;
  state.scorePath = remembered.score ?? null;
  state.ensemble = remembered.ensemble ?? null;
  state.line = remembered.line ?? null;
  state.transposition = remembered.transposition ?? null;
  state.exported = null;
  state.exportedAt = null;
  state.notationScore = null;
  renderChoices();
  // Carried until a transcription exists to match them against; showReview
  // replaces these with the server's resolution.
  state.carried = Array.isArray(remembered.erasures) ? remembered.erasures : [];
  state.silenced.clear();
  state.unmatched = [];
  state.moved = [];
  state.carriedAdditions = Array.isArray(remembered.additions) ? remembered.additions : [];
  state.added.clear();
  state.unmatchedAdditions = [];
  state.undoStack.length = 0;
  state.redoStack.length = 0;
  setTool('inspect');
  renderEditBar();
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
    refreshModelStatus();  // a span-scoped separation may or may not cover the new span
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

/* Make one section's transport the live one and silence the other two.
   Three engines share the speakers, so a play button that pauses only one of
   the others lets the review's rendering keep sounding under the original
   mix — which is what "play in section 1 played the isolated stem" was. */
function activate(which) {
  state.active = which;
  if (which !== 'mix') mix.engine?.pause();
  if (which !== 'stem') stemEngine.pause();
  if (which !== 'review') reviewEngine.pause();
}

function togglePlay() {
  if (state.active === 'review' && reviewEngine.duration) {
    activate('review');
    reviewEngine.toggle();
  } else if (state.active === 'stem' && stemEngine.duration) {
    activate('stem');
    stemEngine.toggle();
  } else {
    activate('mix');
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
  renderRollLegend();

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
  const chorusMenu = $('chorus-bars');
  chorusMenu.disabled = !state.beats;
  ensureChorusOption(state.barsPerChorus);
  chorusMenu.value = String(state.barsPerChorus || 0);
  const custom = $('chorus-custom');
  custom.disabled = !state.beats;
  if (document.activeElement !== custom) custom.hidden = true;

  const snap = $('snap-toggle');
  snap.disabled = !state.beats;
  snap.textContent = `Snap: ${state.beats ? state.snapMode : 'off'}`;
  snap.classList.toggle('active', Boolean(state.beats) && state.snapMode !== 'off');
  const doubleTime = $('double-time');
  doubleTime.disabled = !state.beats;
  doubleTime.textContent = `2× time: ${state.doubleTime ? 'on' : 'off'}`;
  doubleTime.classList.toggle('active', Boolean(state.doubleTime));
  updateBars();
}

/* A form the menu does not list becomes an option in it, in order, so the
   chip reads "20-bar" rather than falling blank. A sidecar can arrive with any
   number in it — the setting has always been a plain int, and the menu was the
   only thing that ever said otherwise — so this runs on every render, not just
   when the listener types one. */
function ensureChorusOption(bars) {
  const menu = $('chorus-bars');
  const value = Number(bars) || 0;
  if (value < 2) return;
  if ([...menu.options].some((option) => Number(option.value) === value)) return;
  const option = document.createElement('option');
  option.value = String(value);
  option.textContent = `${value}-bar`;
  const after = [...menu.options].find(
    (existing) => Number(existing.value) > value || existing.value === 'custom',
  );
  menu.insertBefore(option, after ?? null);
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

/* The pool only exists for a pianist, so the button only exists then too:
   a control that is permanently inert on horn tracks teaches people to ignore
   the row it sits in. It shows everything the piano model heard that the
   line left out, faint, and the Edit tool switches any of them on. */
function renderSecondVoiceToggle(payload) {
  const chip = $('second-voice-toggle');
  const count =
    ((payload && payload.candidates && payload.candidates.length) || 0) +
    ((payload && payload.second_voice && payload.second_voice.length) || 0);
  chip.hidden = count === 0;
  chip.classList.toggle('active', state.showSecond);
  chip.textContent = state.showSecond ? `piano model · ${count}` : 'piano model';
  renderRollLegend();
}

/* What each colour on the roll means, above it. Built from what is actually
   drawn right now, so it never names a colour that is not on screen: the
   hand-transcription classes appear with a score, the piano model's pool
   with a pianist's review, and an entry dims when its layer is switched off
   rather than vanishing, so the toggle's effect can be read off the legend. */
function renderRollLegend() {
  const legend = $('roll-legend');
  legend.innerHTML = '';
  if (!state.review) {
    legend.hidden = true;
    return;
  }
  legend.hidden = false;
  const item = (label, variable, shape = '', off = false, title = '') => {
    const span = document.createElement('span');
    span.className = `item${off ? ' off' : ''}`;
    if (title) span.title = title;
    const key = document.createElement('span');
    key.className = `key ${shape}`.trim();
    key.style.setProperty('--key', `var(${variable})`);
    span.appendChild(key);
    span.appendChild(document.createTextNode(label));
    legend.appendChild(span);
  };

  if (state.ground) {
    const on = (name) => state.gtClasses.includes(name);
    item('matched', '--gt-matched', '', !on('matched'),
      "Our note, wearing the hand transcription's outline");
    item('wrong note', '--gt-wrong', 'outline', !on('wrong'),
      'The written note, outlined at the height it should have been; a stalk joins it to ours');
    item('invented', '--gt-invented', '', !on('invented'),
      'A note of ours the hand transcription does not have');
    item('missed', '--gt-missed', 'wash', !on('missed'),
      'A written note with nothing of ours under it');
  } else {
    item('transcribed line', '--lead', '', false, 'The notes we heard; fainter means less confident');
  }
  item('selected', '--accent');
  item('silenced', '--lead', 'struck', false,
    'Marked "not the solo" with the Edit tool; stays drawn, struck through');

  const candidates = (state.review.candidates || []).length;
  const second = (state.review.second_voice || []).length;
  if (candidates) {
    item('piano model heard', '--candidate', '', !state.showSecond,
      'Every note the piano model heard that the line left out; brighter is louder. Inspect tool: click to hear it. Edit tool: click to add it');
    item('added to page', '--added', '', false,
      'A piano-model note switched on: it sounds in the ear test and is written, as a chord if it strikes with a line note');
  }
  if (second) item('second voice', '--second-voice', 'outline', !state.showSecond);

  if (state.beats && state.showBeats) {
    item('bar line', '--downbeat', 'bar');
    if ((state.beats.chorus_bars || []).length) item('chorus start', '--chorus', 'bar');
  }
}

function toggleSecondVoice() {
  const chip = $('second-voice-toggle');
  if (chip.hidden) return;
  state.showSecond = !state.showSecond;
  pianoRoll.setShowSecondVoice(state.showSecond);
  renderSecondVoiceToggle(state.review);
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

/* The separation models by a name a person can read. The ids stay in the
   config, the cache and the CLI command; the chip shows the name and the
   tooltip says what the model is for. An unknown id shows as itself. */
const MODEL_LABELS = {
  bsroformer_sw: 'BS-RoFormer',
  htdemucs: 'Demucs',
  htdemucs_6s: 'Demucs 6-stem',
  htdemucs_ft: 'Demucs fine-tuned',
};
const MODEL_NOTES = {
  bsroformer_sw:
    'The default. Much slower than Demucs but far better at keeping a horn in one stem, ' +
    'so it separates only the selected span: minutes rather than tens of minutes.',
  htdemucs:
    'Hybrid Transformer Demucs, four stems: vocals, drums, bass and other. The fast choice — ' +
    'about three minutes for a ten-minute track on CPU.',
  htdemucs_6s:
    'Demucs with guitar and piano stems added. Worth trying on a piano solo; it sometimes files a ' +
    'horn under guitar or vocals.',
  htdemucs_ft:
    'Four Demucs models averaged. Four times slower than Demucs and, measured on our benchmark, ' +
    'no more accurate; kept for comparison.',
};
const modelLabel = (id) => MODEL_LABELS[id] ?? id;

function renderModels() {
  const node = $('model-chips');
  node.innerHTML = '';
  const models = state.track?.models ?? [];
  for (const entry of models) {
    const button = document.createElement('button');
    button.className = `chip${entry.model === state.model ? ' active' : ''}`;
    button.innerHTML = `<span class="dot${entry.ready ? ' ready' : ''}"></span>`;
    button.append(modelLabel(entry.model));
    const status = entry.ready
      ? `Already separated${entry.span ? ` for ${clock(entry.span[0])}–${clock(entry.span[1])}` : ''}: ${entry.stems.join(', ')}.`
      : entry.stems?.length
        ? `Partly on disk — ${entry.stems.join(', ')}; missing ${entry.missing.join(', ')}. Separate to get the rest.`
        : 'Not separated yet for this span.';
    button.title = `${MODEL_NOTES[entry.model] ?? entry.model} ${status}`;
    button.addEventListener('click', () => selectModel(entry.model));
    node.appendChild(button);
  }
  const current = models.find((m) => m.model === state.model);
  const button = $('separate-btn');
  button.hidden = Boolean(current?.ready);
  button.textContent = `Separate ${state.selection ? 'selection' : 'track'} with ${modelLabel(state.model)}`;
  if (!button.hidden) refreshEstimate();
}

/* The predicted wait, on the button, before the listener commits to it: a
   thirty-minute estimate is a reason to pick the faster model instead. */
async function refreshEstimate() {
  if (!state.track || !state.model) return;
  const button = $('separate-btn');
  try {
    const data = await api(`/api/tracks/${state.track.id}/estimate?model=${state.model}${spanParams()}`);
    const minutes = data.seconds / 60;
    const wait = minutes < 1.5 ? `~${Math.ceil(data.seconds)} s` : `~${Math.ceil(minutes)} min`;
    button.textContent = `Separate ${state.selection ? 'selection' : 'track'} with ${modelLabel(state.model)} (${wait})`;
  } catch (_error) { /* the button keeps its plain label */ }
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
  const data = await api(`/api/tracks/${state.track.id}/stems?model=${state.model}${spanParams()}`);
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
    // "other" is where a horn lands, in a 4-stem split and in the Roformer's
    // six; a pianist's line lives in `piano` when the model writes one
    // (BS-Roformer-SW, htdemucs_6s). The right guess when nothing is
    // remembered follows the ensemble the listener chose.
    const pianist = pianoOracleEnsembles.includes(state.ensemble);
    state.leadStem = pianist && state.stems.includes('piano') ? 'piano'
      : state.stems.includes('other') ? 'other' : state.stems[0] ?? null;
  }
  select.value = state.leadStem ?? '';
  $('legend-stem').textContent = state.leadStem ?? 'lead stem';
  updateHandoff();  // the command needs the stem, which we only just resolved
}

async function refreshAudition() {
  if (!state.track || !state.model) return;
  await refreshModelStatus();
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
  renderAuditionRange();
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

/* The span, and the slice of it on screen when the stem view is zoomed in. */
function renderAuditionRange() {
  if (!state.selection) return;
  const { a, b } = state.selection;
  const span = `${clock(a, false)}–${clock(b, false)} · ${(b - a).toFixed(1)}s`;
  const { start, end } = stemWave.win;
  const zoomed = end - start < (b - a) - 0.01;
  $('audition-range').textContent = zoomed
    ? `${span} · showing ${clock(start, false)}–${clock(end, false)}`
    : span;
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
    // The view zooms and pans inside the span and no further: outside it the
    // stem is not on screen, and the peaks fetched cover only the span.
    stemWave.setBounds(a, b);
    stemWave.setWindow(a, b, { silent: true });
    renderAuditionRange();
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
      <button class="s${settings.muted ? '' : ' on'}" title="Mute or unmute this stem in the audition.">${settings.muted ? '○' : '◉'}</button>
      <span class="stem-name" title="${key === 'mix' ? 'The original recording, for reference.' : key === CLICK_KEY ? 'The metronome on the bar grid.' : `The ${key} stem${key.includes('+') ? ', summed from its parts' : ''}.`}">${key === 'mix' ? 'original mix' : key === CLICK_KEY ? 'click' : key}${isLead ? '<span class="lead-tag">lead</span>' : ''}</span>
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

/* The span the stems must cover: the selection when there is one. Sent with
   every stems query and with the Separate job, so a slow model separates the
   solo rather than the record (SeparateConfig.span). */
function spanParams() {
  if (!state.selection) return '';
  return `&start=${state.selection.a}&end=${state.selection.b}`;
}

async function refreshModelStatus() {
  if (!state.track) return;
  try {
    const data = await api(`/api/tracks/${state.track.id}/stems?${spanParams().slice(1)}`);
    if (data.models) { state.track.models = data.models; renderModels(); }
  } catch (_error) { /* the picker keeps what it had */ }
}

async function startSeparation() {
  if (!state.track || !state.model) return;
  try {
    const body = { path: state.track.path, model: state.model };
    if (state.selection) { body.start = state.selection.a; body.end = state.selection.b; }
    const job = await post('/api/jobs', body);
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
      // Cancelled is terminal too. Leaving it out kept the poll running for
      // ever on a job that had already stopped, with the chip stuck on
      // "cancelling…" and the Separate button disabled until a reload.
      if (job.state === 'done' || job.state === 'error' || job.state === 'cancelled') {
        clearInterval(timer);
        resolve(job);
      }
    }, 1000);
  });
}

/* "about 4 min left" — from measured progress when the model reports it,
   from the estimate counting down when it cannot (the Roformer). */
function remainingText(update) {
  if (update.remaining == null) return '';
  const minutes = Math.ceil(update.remaining / 60);
  const left = update.remaining < 90 ? `${Math.ceil(update.remaining)} s` : `${minutes} min`;
  return update.fraction >= 0.15 ? `· ~${left} left` : `· ~${left} left (estimate)`;
}

async function pollJob(jobId) {
  state.jobId = jobId;
  $('job-cancel').disabled = false;
  const job = await watchJob(jobId, (update) => {
    $('job-fill').style.width = `${(update.fraction * 100).toFixed(1)}%`;
    $('job-message').textContent = update.cancel_requested ? 'cancelling…' : (update.message || update.state);
    $('job-elapsed').textContent = `${clock(update.elapsed, false)} elapsed ${remainingText(update)}`;
  });
  state.jobId = null;
  $('separate-btn').disabled = false;
  $('job').hidden = true;
  if (job && job.state === 'error') {
    toast(job.error, true);
    return;
  }
  if (job && job.state === 'cancelled') {
    toast(`${modelLabel(job.model)}: separation cancelled`);
    return;
  }
  if (job) toast(`${modelLabel(job.model)}: ${job.stems.length} stems ready`);
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
  const params = {
    model: state.model,
    stem: state.leadStem,
    start: a.toFixed(3),
    end: b.toFixed(3),
  };
  // The line choice is part of the review's identity for a pianist (it
  // changes every note); left out for the default so the key stays as it was.
  if (state.line) params.line = state.line;
  return new URLSearchParams(Object.assign(params, extra || {}));
}

/* The review belongs to one span+stem. When either changes the old notes are
   stale, so drop back to the Transcribe button rather than showing notes that
   describe a different passage. */
function invalidateReview() {
  state.review = null;
  // The file on disk survives — deleting the memory of it would be a lie in
  // the other direction. It is simply behind now, which renderExport says.
  state.notationScore = null;
  renderExport();
  reviewEngine.stop();
  reviewEngine.reset(0, 1);
  if (state.active === 'review') state.active = 'mix';
  $('review').hidden = true;
  $('review-summary').hidden = true;
  $('transcribe-btn').disabled = false;
  $('transcribe-btn').textContent = 'Transcribe span';
  // Note indices belong to one transcription, so they cannot survive — but the
  // erasures themselves must. Fold them back into the carried list before
  // dropping the indices, or changing stem would quietly destroy every label.
  state.carried = erasureList();
  state.silenced.clear();
  state.unmatched = state.carried.filter((e) => inSpan(e));
  state.moved = [];  // nothing to compare against until a transcription exists
  state.carriedAdditions = additionList();
  state.added.clear();
  state.unmatchedAdditions = state.carriedAdditions.filter((e) => inSpan(e));
  state.undoStack.length = 0;
  state.redoStack.length = 0;
  pianoRoll.setSilenced(state.silenced);
  pianoRoll.setAdded(state.added);
  renderEditBar();
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
      stem: state.leadStem, start: a, end: b, line: state.line || undefined,
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
  // The server matched the stored erasures onto these notes — by content, not
  // by index, because re-transcribing renumbers everything (gui/erasures.py).
  const resolved = payload.erasures ?? { silenced: [], carried: [], unmatched: [], moved: [] };
  state.silenced = new Set(resolved.silenced);
  state.carried = resolved.carried;
  state.unmatched = resolved.unmatched;
  state.moved = resolved.moved ?? [];
  // Additions the same way: matched onto the candidate pool by content.
  const additions = payload.additions ?? { added: [], carried: [], unmatched: [] };
  state.added = new Set(additions.added);
  state.carriedAdditions = additions.carried;
  state.unmatchedAdditions = additions.unmatched;
  state.notationScore = null;
  state.undoStack.length = 0;
  state.redoStack.length = 0;

  pianoRoll.setData({ a: state.selection.a, b: state.selection.b }, payload, state.showBeats ? state.beats : null);
  pianoRoll.setSilenced(state.silenced);
  pianoRoll.setAdded(state.added);
  pianoRoll.setShowSecondVoice(state.showSecond);
  renderSecondVoiceToggle(payload);
  // Park the marker at the start rather than leaving it undrawn: a playhead
  // you cannot see is not obviously one you can move.
  pianoRoll.setPlayhead(state.selection.a);
  renderEditBar();
  renderInspector(null, -1);
  if (state.unmatched.length) {
    // "No longer matches" was one message for two opposite situations. A note
    // that is simply GONE means the transcriber now agrees with the cut you
    // made by hand — which is what corroboration did to most of Orbits' erased
    // left hand (M7b) — and reporting that as a problem, next to a Discard
    // button, is how good news gets thrown away.
    const n = state.unmatched.length;
    const moved = state.moved.length;
    toast(
      moved
        ? `${n} stored erasure${n === 1 ? '' : 's'} unmatched — ${moved} now at a different pitch, worth a look`
        : `${n} erased note${n === 1 ? ' is' : 's are'} already gone from this transcription — labels kept`,
    );
  }
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
  activate('review');
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
    playButtonHtml() +
    `</div><div class="inspector-why"></div><div class="inspector-note"></div>`;
  bindPlayButton(body, note);
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
  if (state.silenced.has(index)) {
    chip('silenced', 'cut');
    remarks.push('Marked "heard right, not the solo" — it is drawn struck out and does not sound in the ear test.');
  }

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

// ── silencing notes ─────────────────────────────────────────────────────────
// A pianist comps with the left hand behind their own solo; the transcriber
// hears those notes correctly and they are not wanted. That is a difference of
// scope, not a transcription error. Every note silenced here is also a labelled
// example — "heard right, not the solo" — which is the training signal for
// picking a melodic line out of a polyphonic texture (open issue #8), so the
// records are written to keep, and nothing is ever dropped quietly.

/* History is whole-state snapshots rather than invertible operations. A
   toggle, a rubber-band sweep, "restore all" and discarding stale erasures all
   undo through the same two lines, with no per-operation inverse to get
   subtly wrong. The state is a few hundred integers; the simplicity is free. */
const HISTORY_LIMIT = 200;

function editSnapshot() {
  return {
    silenced: [...state.silenced],
    carried: state.carried.map((e) => ({ ...e })),
    added: [...state.added],
    carriedAdditions: state.carriedAdditions.map((e) => ({ ...e })),
  };
}

function pushHistory() {
  state.undoStack.push(editSnapshot());
  if (state.undoStack.length > HISTORY_LIMIT) state.undoStack.shift();
  state.redoStack.length = 0;
}

function applyEditSnapshot(snapshot) {
  state.silenced = new Set(snapshot.silenced);
  state.carried = snapshot.carried;
  state.added = new Set(snapshot.added ?? []);
  state.carriedAdditions = snapshot.carriedAdditions ?? state.carriedAdditions;
  state.unmatchedAdditions = state.carriedAdditions.filter((e) => inSpan(e));
  state.unmatched = state.carried.filter((e) => inSpan(e));
  // Undo restores labels, not the server's classification of them, so keep
  // only the ones still carried rather than re-deriving what "moved" means.
  const live = new Set(state.unmatched.map(erasureId));
  state.moved = state.moved.filter((e) => live.has(erasureId(e)));
}

function inSpan(erasure) {
  if (!state.selection) return true;
  return erasure.onset >= state.selection.a - 0.03 && erasure.onset <= state.selection.b + 0.03;
}

function undoEdit() {
  if (!state.undoStack.length) return;
  state.redoStack.push(editSnapshot());
  applyEditSnapshot(state.undoStack.pop());
  afterEdit();
}

function redoEdit() {
  if (!state.redoStack.length) return;
  state.undoStack.push(editSnapshot());
  applyEditSnapshot(state.redoStack.pop());
  afterEdit();
}

function toggleSilence(index) {
  pushHistory();
  if (state.silenced.has(index)) state.silenced.delete(index);
  else state.silenced.add(index);
  sound(state.review?.notes[index]);
  afterEdit();
}

/* The inspector's "hear it again" — the same tone the click played, for a
   note of ours or of the hand transcription alike. */
function playButtonHtml() {
  return '<button class="chip inspector-play" type="button" title="Sound this pitch again">♪ Play</button>';
}

function bindPlayButton(body, note) {
  body.querySelector('.inspector-play')?.addEventListener('click', () => sound(note));
}

/* The Edit tool sounds the note it just touched: a plain tone at its pitch,
   which is the question the click is asking -- is this the note that was
   played? The recording is a click away on the playhead; a chord of four at
   speed does not say which of them is the F sharp, and a tone does. */
function sound(note) {
  if (!note) return;
  try {
    playPitch(note.pitch, note.duration);
  } catch {
    /* no audio output on this machine; the edit still happened */
  }
}

/* The other sign of the same edit: a note the piano model heard that the
   line left out, switched on. It sounds in the ear test and reaches the page
   — as a chord on the line note it was struck with, if there is one. */
function toggleAdd(index) {
  pushHistory();
  if (state.added.has(index)) state.added.delete(index);
  else state.added.add(index);
  sound(state.review?.candidates[index]);
  afterEdit();
}

function silenceRun(indices, restoring) {
  pushHistory();
  for (const index of indices) {
    if (restoring) state.silenced.delete(index);
    else state.silenced.add(index);
  }
  afterEdit();
}

function restoreAll() {
  if (!state.silenced.size) return;
  pushHistory();
  state.silenced.clear();
  afterEdit();
}

/* Erasures that no longer match are reported, never dropped — so throwing them
   away has to be a deliberate act, and even then it is undoable. */
function discardUnmatched() {
  if (!state.unmatched.length) return;
  const gone = new Set(state.unmatched.map(erasureId));
  pushHistory();
  state.carried = state.carried.filter((e) => !gone.has(erasureId(e)));
  state.unmatched = [];
  state.moved = [];
  afterEdit();
  toast(`Discarded ${gone.size} erasure${gone.size === 1 ? '' : 's'}`);
}

const erasureId = (e) => `${e.onset}:${e.pitch}`;

function afterEdit() {
  pianoRoll.setSilenced(state.silenced);
  pianoRoll.setAdded(state.added);
  renderEditBar();
  // Silencing a note after exporting is the quietest way to end up with a
  // file on disk that no longer matches the screen, and a stale score is
  // worse than none. It also invalidates any number measured against it.
  state.notationScore = null;
  renderExport();
  persist();
  scheduleTranscriptionReload();
}

/* The list written to the sidecar: everything still carried, plus a fresh
   record for every note currently silenced. Rebuilt rather than patched, so
   the file always describes exactly what is on screen. */
function erasureList() {
  const made = [];
  if (state.review) {
    for (const index of [...state.silenced].sort((a, b) => a - b)) {
      const note = state.review.notes[index];
      if (!note) continue;
      made.push({
        onset: round3(note.onset),
        pitch: note.pitch,
        duration: round3(note.duration),
        confidence: round3(note.confidence),
        reason: 'not-solo',
        stem: state.leadStem,
        model: state.model,
        // Which detector's line the judgement was made on: an erasure is a
        // label, and a label that cannot describe its example is worth less.
        line: state.line || 'crepe',
      });
    }
  }
  return [...state.carried, ...made].sort((a, b) => a.onset - b.onset);
}

const round3 = (v) => Math.round(v * 1000) / 1000;

/* The additions written to the sidecar, built the same way as the erasures:
   everything still carried plus a record for every candidate switched on. */
function additionList() {
  const made = [];
  if (state.review && Array.isArray(state.review.candidates)) {
    for (const index of [...state.added].sort((a, b) => a - b)) {
      const note = state.review.candidates[index];
      if (!note) continue;
      made.push({
        onset: round3(note.onset),
        pitch: note.pitch,
        duration: round3(note.duration),
        confidence: round3(note.confidence),
        reason: 'added',
        stem: state.leadStem,
        model: state.model,
        line: state.line || 'crepe',
      });
    }
  }
  return [...state.carriedAdditions, ...made].sort((a, b) => a.onset - b.onset);
}

function setTool(tool) {
  state.tool = tool;
  pianoRoll.setTool(tool);
  for (const button of $('tool-group').querySelectorAll('button')) {
    button.classList.toggle('active', button.dataset.tool === tool);
  }
}

function renderEditBar() {
  const count = state.silenced.size;
  const added = state.added.size;
  const total = state.review ? state.review.notes.length : 0;
  const parts = [];
  if (count) parts.push(`${count} of ${total} silenced`);
  if (added) parts.push(`${added} added`);
  $('silenced-count').textContent = parts.length ? parts.join(' · ') : 'nothing silenced';
  $('silenced-count').classList.toggle('has-cuts', count > 0 || added > 0);
  $('undo-btn').disabled = !state.undoStack.length;
  $('redo-btn').disabled = !state.redoStack.length;
  $('restore-all').disabled = !count;

  const stale = state.unmatched.length;
  const moved = state.moved.length;
  const vanished = stale - moved;
  $('erasure-warning').hidden = !stale;
  $('discard-unmatched').hidden = !stale;
  // Only a MOVED erasure is a warning: something is still sounding there, at
  // another pitch. A vanished one means the transcriber stopped emitting that
  // note, which is agreement rather than a fault, so it is not coloured as one.
  $('erasure-warning').classList.toggle('benign', moved === 0);
  if (stale) {
    const where = state.unmatched
      .slice(0, 6)
      .map((e) => `${midiName(e.pitch)} at ${clock(e.onset, false)}`)
      .join(', ');
    const parts = [];
    if (vanished) parts.push(`${vanished} already gone`);
    if (moved) parts.push(`${moved} at another pitch`);
    $('erasure-warning').textContent =
      `${stale} erasure${stale === 1 ? '' : 's'} unmatched · ${parts.join(', ')}`;
    $('erasure-warning').title =
      (vanished
        ? `${vanished} describe notes this transcription no longer emits — it now agrees with you.\n`
        : '') +
      (moved ? `${moved} have a note at that moment but at another pitch — worth a look.\n` : '') +
      `All kept, not discarded — each one is a labelled example.\n${where}` +
      (stale > 6 ? `, and ${stale - 6} more` : '');
  }
}

/* The ear test must stop playing what you cut, but re-rendering on every click
   of a 40-note sweep is wasteful, so it settles first. */
let transcriptionReloadTimer = null;
function scheduleTranscriptionReload() {
  clearTimeout(transcriptionReloadTimer);
  transcriptionReloadTimer = setTimeout(async () => {
    if (!state.review || !reviewEngine.has('transcription')) return;
    const token = state.reviewToken;
    await persistNow();  // the server reads the erasures from the sidecar
    const url = `/api/tracks/${state.track.id}/transcription?${reviewParams({ rate: String(state.reviewRate) })}`;
    reviewEngine.drop('transcription');
    try {
      await reviewEngine.load('transcription', url);
    } catch (error) {
      if (token === state.reviewToken) toast(`Ear test: ${error.message}`, true);
      return;
    }
    if (token === state.reviewToken) applyReviewMode();
  }, 700);
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
  // A number is only meaningful beside the score it was measured against, so
  // dropping the score drops the number with it.
  state.notationScore = null;
  renderGroundTruthBar();
  renderExport();
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
  renderExport();
  return 'ok';
}

const GT_CLASS_NOTES = {
  matched: 'Notes we transcribed that agree with the hand transcription.',
  wrong: 'Notes where we produced a different pitch from the one written.',
  invented: 'Notes we produced that the hand transcription does not have.',
  missed: 'Notes in the hand transcription that we did not produce.',
};

function renderGroundTruthBar() {
  const info = $('gt-info');
  const classes = $('gt-classes');
  const caveat = $('gt-caveat');
  $('gt-clear').hidden = !state.scorePath;
  renderRollLegend();
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
    button.title = `${GT_CLASS_NOTES[name]} Click to show or hide these notes on the roll.`;
    button.addEventListener('click', () => toggleGroundClass(name));
    classes.appendChild(button);
  }

  // Horizontal position is derived from the alignment, so an aligned pair
  // sits at the same x by construction. Saying so on screen is the only thing
  // stopping the picture being read as a timing result.
  caveat.hidden = false;
  // Notes the tempo map put outside the span are pinned to its edges rather
  // than dropped, but a pile of them at bar 1 is a failed alignment, not a
  // reading of the music — so it has to be said out loud. Silently drawing
  // nothing is what made twenty missed notes look like an empty passage.
  const off = s.off_span || 0;
  caveat.textContent =
    `placed by alignment, not by time (${s.drift_s}s off constant tempo)` +
    (off ? ` · ${off} note${off === 1 ? '' : 's'} pinned to the span edge` : '');
  caveat.title =
    'Every notated note that aligned to one of ours is drawn at that note’s onset, and the ' +
    'rest are interpolated between those anchors. So horizontal agreement is by construction — ' +
    'this view answers pitch, not timing. The figure is how far that placement had to move the ' +
    'score away from a constant tempo.' +
    (off
      ? `\n\n${off} notated note${off === 1 ? '' : 's'} fell outside the span entirely and ` +
        'are drawn at its edge. That means the alignment could not anchor one end — usually ' +
        'because our line is missing notes there, not because the score is wrong about them.'
      : '');
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
    playButtonHtml() +
    `</div><div class="inspector-why"></div><div class="inspector-note"></div>`;
  bindPlayButton(body, note);
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

/* A piano-model candidate has no frames behind it either — it is what the
   polyphonic model heard, not what the pitch tracker did — so its inspector
   says what the model heard, how loud, and whether it is on the page. */
function renderCandidateInspector(index) {
  const note = state.review?.candidates?.[index];
  if (!note) return;
  $('inspector-empty').hidden = true;
  const body = $('inspector-body');
  body.hidden = false;
  const on = state.added.has(index);
  body.innerHTML =
    `<div class="inspector-head">` +
    `<span class="pitch">${midiName(note.pitch)} <span class="muted">(${note.pitch})</span></span>` +
    `<span class="timing">piano model · ${clock(note.onset)} · ${(note.duration * 1000).toFixed(0)}ms · velocity ${note.velocity}</span>` +
    playButtonHtml() +
    `</div><div class="inspector-why"></div><div class="inspector-note"></div>`;
  bindPlayButton(body, note);
  const why = body.querySelector('.inspector-why');
  const chip = (text, kind) => {
    const el = document.createElement('span');
    el.className = `why-chip ${kind || ''}`;
    el.textContent = text;
    why.appendChild(el);
  };
  chip('piano model heard');
  chip(on ? 'added to page' : 'not on the page', on ? 'ok' : '');
  if (note.velocity < 60) chip('soft', 'flag');

  const remarks = [
    'Heard by the piano model and left out of the transcribed line. Its velocity is the model’s estimate of how hard the key was struck; louder notes are more often the melody.',
  ];
  if (on) {
    remarks.push(
      'Switched on: it sounds in the ear test and is written on the page — as a chord if it strikes with a line note. Click it with the Edit tool to switch it off.',
    );
  } else {
    remarks.push('Click it with the Edit tool to add it to the transcription.');
  }
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
function settingsPayload() {
  return {
    region: [state.selection.a, state.selection.b],
    stem: state.leadStem,
    model: state.model,
    beats_shown: state.showBeats,
    snap_mode: state.snapMode,
    time_signature: state.timeSignature,
    double_time: state.doubleTime,
    anchor: state.anchor,
    bars_per_chorus: state.barsPerChorus,
    form_start: state.formStart,
    click: state.click,
    score: state.scorePath,
    ensemble: state.ensemble,
    line: state.line,
    transposition: state.transposition,
    erasures: erasureList(),
    additions: additionList(),
  };
}

function persist() {
  if (!state.track) return;
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    post(`/api/tracks/${state.track.id}/state`, { state: settingsPayload() })
      .catch(() => { /* remembering where you were is not worth an error */ });
  }, 500);
}

/* Same write, awaited. The A/B render reads erasures from the sidecar, so it
   must not be asked for one until the file actually holds them. */
async function persistNow() {
  if (!state.track) return;
  clearTimeout(persistTimer);
  try {
    await post(`/api/tracks/${state.track.id}/state`, { state: settingsPayload() });
  } catch { /* the render will simply be a beat behind */ }
}

/* ── choices that are not in the audio ──────────────────────────────────────
   Two settings nothing in the signal can tell us: who is playing, and what key
   the part is written in. Both live in the track's sidecar beside the audio,
   because both are judgements a person made about a specific recording.

   The menus are built from /api/config rather than written out here, so they
   offer exactly what the config's validator accepts — a hand-copied list is a
   list that drifts and starts offering values the server will reject. */

const LABELS = {
  'horn-led': 'Horn-led',
  trio: 'Trio (piano)',
  'solo-piano': 'Solo piano',
  C: 'C — concert',
  Bb: 'B♭ — trumpet, soprano',
  'Bb-tenor': 'B♭ tenor — written +9th',
  Eb: 'E♭ — alto, baritone',
};

let choices = null;

function fillSelect(node, values, fallback) {
  node.replaceChildren(...values.map((value) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = LABELS[value] ?? value;
    return option;
  }));
  node.dataset.fallback = fallback;
}

/* Which ensembles consult the polyphonic piano model, from /api/config.
   Declared above its first assignment: `let` is hoisted into the temporal
   dead zone, so writing to it from loadChoices before this line ran would
   throw rather than default. */
let pianoOracleEnsembles = [];

async function loadChoices() {
  try {
    choices = await api('/api/config');
  } catch {
    return;  // the pickers stay empty; every other screen still works
  }
  fillSelect($('ensemble-select'), choices.ensembles ?? [], choices.default_ensemble ?? 'horn-led');
  // Asked of the server, never listed here: the UI must not be the second
  // place the routing is written down.
  pianoOracleEnsembles = choices.piano_oracle_ensembles ?? [];
  fillLineSelect(choices.lines ?? [], choices.default_line ?? 'crepe');
  fillSelect($('transpose-select'), choices.transpositions ?? [], choices.default_transposition ?? 'C');
  renderChoices();
}

/* The two takes of a pianist's line, named for what does the hearing. Values
   come from the server (config.LINES); only the labels live here. */
const LINE_LABELS = {
  crepe: 'CREPE, checked by piano model',
  oracle: 'Piano model, melody picked',
};

function fillLineSelect(values, fallback) {
  const node = $('line-select');
  node.innerHTML = '';
  for (const value of values) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = LINE_LABELS[value] ?? value;
    node.appendChild(option);
  }
  node.dataset.fallback = fallback;
}

/* Say out loud what the ensemble choice routes to.

   The choice is not cosmetic and its consequence is invisible: a piano solo
   left on Horn-led is transcribed with no second opinion, which costs notes
   the model heard perfectly well (M7b: every piano solo improved on both
   halves of F1 once it was consulted). The listener hit exactly that. */
function renderEnsembleHint() {
  const hint = $('ensemble-hint');
  if (!hint) return;
  const ensemble = $('ensemble-select').value;
  if (!ensemble || !pianoOracleEnsembles.length) { hint.textContent = ''; return; }
  hint.textContent = pianoOracleEnsembles.includes(ensemble)
    ? '· piano model consulted'
    : '· no piano model — pick Trio or Solo piano for a pianist';
}

function renderChoices() {
  const ensemble = $('ensemble-select');
  const transpose = $('transpose-select');
  const line = $('line-select');
  if (ensemble.options.length) ensemble.value = state.ensemble ?? ensemble.dataset.fallback;
  if (transpose.options.length) transpose.value = state.transposition ?? transpose.dataset.fallback;
  if (line.options.length) line.value = state.line ?? line.dataset.fallback;
  renderEnsembleHint();
  renderLinePicker();
}

/* The line picker only means something for a pianist — a horn's review
   ignores it — so it only exists on screen then: a control that is
   permanently inert teaches people to ignore the row it sits in. */
function renderLinePicker() {
  const pianist = pianoOracleEnsembles.includes($('ensemble-select').value);
  $('line-label').hidden = !pianist;
  $('line-select').hidden = !pianist;
}

/* ── export ─────────────────────────────────────────────────────────────────
   The whole notation chain below transcribe is arithmetic, so this is a plain
   request with no job and no progress bar (gui/musicxml.py). A 409 is not a
   failure — it is the button naming the earlier step you still owe it — so it
   is shown as a normal message rather than an error. */

/* What the exported file was written FROM. Anything in here changing means the
   file on disk is behind what is on screen — including a note silenced after
   the export, which is the easy one to miss. */
function exportSignature() {
  if (!state.selection) return null;
  return JSON.stringify({
    a: state.selection.a, b: state.selection.b,
    stem: state.leadStem, model: state.model,
    transposition: state.transposition,
    token: state.reviewToken,
    silenced: [...state.silenced].sort((x, y) => x - y),
    added: [...state.added].sort((x, y) => x - y),
    timeSignature: state.timeSignature,
    anchor: state.anchor,
  });
}

async function startExport() {
  if (!state.selection || !state.leadStem || !state.review) return;
  const btn = $('export-btn');
  btn.disabled = true;
  try {
    await persistNow();  // the server reads transposition from the sidecar
    const result = await post(`/api/tracks/${state.track.id}/export?${reviewParams()}`);
    state.exported = result;
    state.exportedAt = exportSignature();
    renderExport();
    toast(`Wrote ${result.name}`);
  } catch (error) {
    state.exported = null;
    state.exportedAt = null;
    renderExport(error.message);
  } finally {
    btn.disabled = false;
  }
}

/* ── scoring the notation ───────────────────────────────────────────────────
   A DIFFERENT question from the F1 on the ground-truth bar, and keeping them
   apart is the most expensive lesson in this project. That one is time-free
   and pitch-only: did we hear the right notes? This asks whether the notes we
   did get are written the way a human wrote them. It reads lower, always. */

async function startNotationScore() {
  if (!state.review || !state.scorePath) return;
  const btn = $('score-btn');
  btn.disabled = true;
  $('score-btn').textContent = 'Scoring…';
  try {
    await persistNow();
    const params = reviewParams({ score: state.scorePath });
    state.notationScore = await api(`/api/tracks/${state.track.id}/notation-score?${params}`);
    renderExport();
  } catch (error) {
    state.notationScore = null;
    renderExport(error.message);
  } finally {
    btn.disabled = false;
    $('score-btn').textContent = 'Score it';
  }
}

function renderExport(message) {
  const info = $('export-info');
  const link = $('export-download');
  const stale = $('export-stale');
  const written = state.exported;
  const behind = Boolean(written) && state.exportedAt !== exportSignature();

  $('score-btn').hidden = !(state.review && state.scorePath);
  stale.hidden = !behind;
  stale.title =
    'Something that would change the page has changed since it was written — the span, ' +
    'the transposition, the notes, or which of them are silenced or added. Export again to catch it up.';
  info.classList.toggle('written', Boolean(written) && !behind);
  renderScoreLine();

  if (message) {
    info.textContent = message;
    link.hidden = true;
    return;
  }
  if (!written) {
    info.textContent =
      'Bars are numbered from 1 within the span; silenced notes are left out and notes you switched on are written in, as chords where they sound together.';
    link.hidden = true;
    return;
  }
  const key = written.transpose
    ? ` · written ${written.transpose > 0 ? '+' : ''}${written.transpose}`
    : '';
  info.textContent =
    `${written.bars} bars · ${written.notes} notes · ${written.time_signature}` +
    `${written.swing ? ' · swing' : ''}${key} → ${written.path}`;
  link.href = `/api/tracks/${state.track.id}/export?${reviewParams()}`;
  link.hidden = false;
}

/* The notation score, on its own line under the export.

   Two numbers, deliberately apart: rhythm is the gap to the next note, value
   is the note value written for it (benchmark.score_notation).

   COVERAGE LEADS WHEN IT IS LOW, and that is not decoration. Measured over
   every notation the benchmark can build against every hand score on disk,
   coverage is 0.69-0.74 on a right pairing and 0.16-0.36 on a wrong one -- but
   rhythm on a wrong pairing still reads up to 0.583, HIGHER than All The Things
   scores against its own correct score. Two bebop lines agree about most gaps
   by chance, so rhythm is never shown here without what it rests on. */
function renderScoreLine() {
  const line = $('score-line');
  const s = state.notationScore;
  line.hidden = !s;
  if (!s) return;
  const pct = Math.round(s.coverage * 100);
  line.classList.toggle('untrusted', !s.trusted);
  if (!s.trusted) {
    line.textContent =
      `Only ${pct}% of ${s.score} lined up with ours (${s.matched}/${s.reference}) — ` +
      'too little to read a rhythm score from';
    line.title =
      'Either this is not the score for this span, or the transcription of it went badly. ' +
      'A right pairing covers about 70% of the notated notes; a wrong one covers 16-36%. ' +
      'Rhythm cannot tell those apart — it reads as high as 0.58 against the wrong tune — ' +
      'so it is withheld rather than shown as if it meant something.';
    return;
  }
  line.textContent =
    `vs ${s.score}: rhythm ${s.rhythm.toFixed(3)} · value ${s.value.toFixed(3)} ` +
    `· ${pct}% lined up (${s.matched}/${s.reference})`;
  line.title =
    'NOT the pitch F1 above, which asks whether we heard the right notes. This asks ' +
    'whether the ones we got are WRITTEN the way a human wrote them: rhythm is the gap ' +
    'to the next note, value is the note value chosen for it. It charges the gap between ' +
    'performed timing and notated rhythm, so it reads lower and always will.\n' +
    `Our ${s.bars} bars against their ${s.reference_bars}` +
    (s.transposition
      ? `, their score written ${s.transposition > 0 ? '+' : ''}${s.transposition} semitones`
      : '');
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

$('export-btn').addEventListener('click', startExport);
$('score-btn').addEventListener('click', startNotationScore);

$('transpose-select').addEventListener('change', (event) => {
  state.transposition = event.target.value;
  // Only changes how the page is written, never which notes were heard, so the
  // review stands and this is a re-export rather than a re-transcription. The
  // file already on disk is now behind, and says so rather than disappearing.
  renderExport();
  persist();
});

$('ensemble-select').addEventListener('change', async (event) => {
  state.ensemble = event.target.value;
  renderEnsembleHint();
  renderLinePicker();
  await persistNow();  // review_config reads this back off the sidecar
  // This one DOES change the notes: a trio consults the polyphonic piano model
  // and a horn never does (M7b). So the span needs transcribing again.
  invalidateReview();
  toast('Ensemble changed — transcribe the span again');
});

$('line-select').addEventListener('change', async (event) => {
  state.line = event.target.value;
  persist();
  // A different detector supplies the notes, so the review on screen
  // describes the other take; drop back to the button. A take already
  // transcribed comes straight back from the cache.
  invalidateReview();
  await refreshReviewPanel();
  if (!state.review) toast('Line changed — transcribe the span for this take');
});

$('r-restart').addEventListener('click', () => {
  if (!reviewEngine.duration) return;
  activate('review');
  restartFromStart();
});

$('a-restart').addEventListener('click', () => {
  if (!stemEngine.duration) return;
  activate('stem');
  restartFromStart();
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

$('stem-fit').addEventListener('click', () => {
  if (state.selection) stemWave.setWindow(state.selection.a, state.selection.b);
});
for (const button of document.querySelectorAll('[data-stem-zoom]')) {
  button.addEventListener('click', () => {
    const factor = button.dataset.stemZoom === 'in' ? 0.6 : 1.7;
    const centre = (stemWave.win.start + stemWave.win.end) / 2;
    const span = stemWave.span * factor;
    stemWave.setWindow(centre - span / 2, centre + span / 2);
  });
}

for (const button of $('tool-group').querySelectorAll('button')) {
  button.addEventListener('click', () => setTool(button.dataset.tool));
}
$('undo-btn').addEventListener('click', undoEdit);
$('redo-btn').addEventListener('click', redoEdit);
$('restore-all').addEventListener('click', restoreAll);
$('discard-unmatched').addEventListener('click', discardUnmatched);

$('gt-pick').addEventListener('click', () => openPicker('score'));
$('gt-clear').addEventListener('click', () => clearGroundTruth({ forget: true }));

$('browse-up').addEventListener('click', () => {
  if (browseRoot?.parent) browseTo(browseRoot.parent);
});
$('browse-drive').addEventListener('change', (event) => browseTo(event.target.value));
$('browse-path').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') browseTo(event.target.value.trim());
});

$('play').addEventListener('click', () => { activate('mix'); togglePlay(); });
$('a-play').addEventListener('click', () => {
  activate('stem');
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

// Speed, one control per section (rate.js). The mix plays through a media
// element, so its slider is live; the other two are stretched on the server
// and reloaded, so they follow the slider on release.
const rateControls = {
  mix: new RateControl($('mix-rate'), {
    live: true,
    onChange: (rate) => {
      state.mixRate = rate;
      mix.engine?.setRate(rate);
    },
  }),
  stem: new RateControl($('stem-rate'), {
    pitchNote: 'stretched without changing pitch',
    onChange: async (rate) => {
      state.stemRate = rate;
      // Stretched server-side, so every source stays at rate 1.0 and
      // therefore still sample-locked to the others. Costs a reload.
      await loadAudition();
    },
  }),
  review: new RateControl($('review-rate'), {
    pitchNote: 'stretched without changing pitch',
    onChange: async (rate) => {
      state.reviewRate = rate;
      // Stretched server-side, so mix and transcription stay sample-locked.
      if (state.review) await loadReviewAudio();
    },
  }),
};

/* Comma and period step the speed of whichever section is playing (or was
   last played), the way < and > scrub speed in an editor. */
function stepRate(delta) {
  rateControls[state.active]?.step(delta);
}

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
$('job-cancel').addEventListener('click', async () => {
  if (!state.jobId) return;
  $('job-cancel').disabled = true;
  try { await post(`/api/jobs/${state.jobId}/cancel`, {}); } catch (error) { toast(error.message, true); }
});

$('transcribe-btn').addEventListener('click', startTranscribe);

$('r-play').addEventListener('click', () => {
  activate('review');
  reviewEngine.toggle();
  refreshPlayButtons();
});

for (const button of $('review-ab').querySelectorAll('button')) {
  button.addEventListener('click', () => {
    state.reviewMode = button.dataset.rab;
    applyReviewMode();
  });
}

$('beats-toggle').addEventListener('click', toggleBeats);
$('second-voice-toggle').addEventListener('click', toggleSecondVoice);

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

$('restart').addEventListener('click', () => { activate('mix'); restartFromStart(); });

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

$('double-time').addEventListener('click', () => {
  // A notation choice, not a grid choice: the tracked beats are untouched,
  // export subdivides them at notation time (notation_for_span), and the
  // page carries "Notated in double time". Per-track, like the signature.
  state.doubleTime = !state.doubleTime;
  const chip = $('double-time');
  chip.textContent = `2× time: ${state.doubleTime ? 'on' : 'off'}`;
  chip.classList.toggle('active', state.doubleTime);
  persist();
});

$('chorus-bars').addEventListener('change', async (event) => {
  if (event.target.value === 'custom') {
    // Don't commit anything yet: the menu is showing "custom…", and the number
    // beside it is what the setting will be. Escape puts the menu back.
    const field = $('chorus-custom');
    field.hidden = false;
    field.value = state.barsPerChorus > 1 ? String(state.barsPerChorus) : '';
    field.focus();
    field.select();
    return;
  }
  state.barsPerChorus = Number(event.target.value);
  $('chorus-custom').hidden = true;
  await maybeLoadBeats();
  persist();
});

/* `insist` is the Enter path: a bad number is worth a complaint and the caret
   back. On blur it is not — refocusing from a blur handler is a loop — so
   clicking away from something unusable simply puts the menu back. */
async function applyCustomChorus(insist) {
  const field = $('chorus-custom');
  const bars = Math.round(Number(field.value));
  if (!Number.isFinite(bars) || bars < 2 || bars > 512) {
    if (!insist) {
      field.hidden = true;
      $('chorus-bars').value = String(state.barsPerChorus || 0);
      return;
    }
    toast('Bars per chorus must be a whole number from 2 to 512', true);
    field.focus();
    field.select();
    return;
  }
  field.hidden = true;
  state.barsPerChorus = bars;
  ensureChorusOption(bars);
  $('chorus-bars').value = String(bars);
  await maybeLoadBeats();
  persist();
}

$('chorus-custom').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    applyCustomChorus(true);
  } else if (event.key === 'Escape') {
    event.preventDefault();
    $('chorus-custom').hidden = true;
    $('chorus-bars').value = String(state.barsPerChorus || 0);
    $('chorus-bars').focus();
  }
});

// Clicking away is a commit, not a cancel — the field only ever appears
// because the listener asked for it, and a number they typed and then clicked
// away from is still the number they meant.
$('chorus-custom').addEventListener('blur', () => {
  if ($('chorus-custom').hidden) return;
  applyCustomChorus(false);
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

  // Undo/redo come first: the switch below deliberately ignores modifiers, so
  // ctrl+Z would otherwise fall through to whatever "z" happens to mean.
  if (event.ctrlKey || event.metaKey) {
    const key = event.key.toLowerCase();
    if (key === 'z') {
      event.preventDefault();
      if (shift) redoEdit(); else undoEdit();
    } else if (key === 'y') {
      event.preventDefault();
      redoEdit();
    }
    return;
  }

  switch (event.key.toLowerCase()) {
    case 'e':
      // One key for the tool, because erasing a run is a sweep: pick up the
      // tool, sweep, put it down.
      setTool(state.tool === 'erase' ? 'inspect' : 'erase');
      break;
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
    case 'x':
      // eXport. Every other control on the review screen has a key; this is
      // the one you press most once a span is settled.
      if (state.review) startExport();
      break;
    case 'v':
      // Voice. Toggling the overlay off is how you check the line underneath
      // it, so it wants to be as cheap as toggling the beat grid.
      toggleSecondVoice();
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
      restartFromStart();
      break;
    case '[':
      nudge(state.focusEdge, shift ? -0.01 : -0.1);
      break;
    case ']':
      nudge(state.focusEdge, shift ? 0.01 : 0.1);
      break;
    case ',':
      stepRate(shift ? -1 : -5);
      break;
    case '.':
      stepRate(shift ? 1 : 5);
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

/* Back to the start and play. The transport plays from the playhead, which
   is what you want while hunting for a boundary — but once the span is set,
   "again from the top" is the gesture you reach for over and over. Each
   section has its own start: the review and the stem are rendered over the
   span, so theirs is A; the mix's is A while Loop A/B confines playback to
   the selection, and the top of the track when it is off — the whole point
   of switching it off is to listen around the span without moving it. */
function restartFromStart() {
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
    seekTo(state.loop ? state.selection.a : 0);
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
loadChoices();
refreshPicker();
requestAnimationFrame(tick);
// `swingscribe gui <file>` lands here with the file in the URL: open it
// straight away rather than making the listener find it in the picker.
const opened = new URLSearchParams(window.location.search).get('open');
if (opened) openTrack(opened);
