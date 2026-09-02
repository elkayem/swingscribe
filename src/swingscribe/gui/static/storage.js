/* The cache panel on screen 1: what the cache holds for each track, with a
 * delete on every stems directory and one for the whole track.
 *
 * Kept out of app.js because it shares nothing with the screens. It needs the
 * fetch helper, the toast, the id of the open track (so that track's model
 * chips can be refreshed when its stems go), and nothing else.
 *
 * Deletion is a second click on the same control. The first click arms it —
 * the control turns red and says what it would free — and it disarms itself
 * after a few seconds, or when anything else is clicked. No modal: a dialog
 * for each of forty directories is the friction that gets a whole cache
 * deleted from a shell instead, sidecar-less and unnamed.
 */

const $ = (id) => document.getElementById(id);
const ARM_MS = 4000;

const bytes = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`);
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function initStorage({ api, toast, currentTrackId, onChanged }) {
  const toggle = $('storage-toggle');
  const list = $('storage-list');
  const summary = $('storage-summary');
  let open = false;
  let armed = null;  // {button, label, timer} — the one control awaiting its second click

  function disarm() {
    if (!armed) return;
    clearTimeout(armed.timer);
    armed.button.classList.remove('armed');
    armed.button.textContent = armed.label;
    armed = null;
  }

  /* Click once to arm, again within ARM_MS to act. */
  function armable(button, label, prompt, action) {
    button.textContent = label;
    button.addEventListener('click', async (event) => {
      event.stopPropagation();
      if (armed?.button === button) {
        disarm();
        button.disabled = true;
        try { await action(); } finally { button.disabled = false; }
        return;
      }
      disarm();
      armed = { button, label, timer: setTimeout(disarm, ARM_MS) };
      button.classList.add('armed');
      button.textContent = prompt;
    });
  }

  async function remove(path, affectedTrackId, what) {
    try {
      const result = await api(path, { method: 'DELETE' });
      toast(`Freed ${bytes(result.freed)} — ${what}`);
      render(result);
      // The open track just lost stems: its model chips must stop saying "ready".
      if (affectedTrackId && affectedTrackId === currentTrackId()) onChanged();
    } catch (error) {
      toast(error.message, true);
      refresh();
    }
  }

  function stemsChip(item, trackId) {
    const chip = document.createElement('span');
    chip.className = `storage-item${item.busy ? ' busy' : ''}`;
    chip.title = item.busy ? `${item.name} — a separation is writing here now` : item.name;
    const label = document.createElement('span');
    const span = item.span ? ` ${clock(item.span[0])}–${clock(item.span[1])}` : '';
    label.textContent = `${item.model}${span} · ${bytes(item.bytes)}`;
    chip.appendChild(label);
    const x = document.createElement('button');
    x.className = 'x';
    x.disabled = item.busy;
    x.title = item.busy ? 'Separating now' : 'Delete these stems';
    armable(x, '✕', `free ${bytes(item.bytes)}?`, () =>
      remove(`/api/storage/stems/${encodeURIComponent(item.name)}`, trackId, `${item.model} stems`));
    chip.appendChild(x);
    return chip;
  }

  function audioChip(wav) {
    const chip = document.createElement('span');
    chip.className = 'storage-item audio';
    chip.title = `${wav.name} — the normalized wav every stage reads; re-made in seconds when the track is opened`;
    chip.textContent = `wav · ${bytes(wav.bytes)}`;
    return chip;
  }

  function trackRow(track) {
    const li = document.createElement('li');
    const row = document.createElement('div');
    row.className = 'row';
    const name = document.createElement('span');
    name.className = track.path || track.known ? 'name' : 'name unknown';
    name.textContent = track.name;
    name.title = track.path ?? track.id;
    const meta = document.createElement('span');
    meta.className = 'meta';
    // The audio is gone from where it was: these stems are for a file the
    // listener no longer has under that name — the first thing to reclaim.
    const moved = track.path && !track.source_exists ? 'audio moved · ' : '';
    meta.textContent = `${moved}${bytes(track.bytes)}`;
    const all = document.createElement('button');
    all.className = 'chip';
    all.title = 'Delete every stem set and the ingested wav for this track. Its span, downbeat and erasures live beside the audio and are kept.';
    const busy = track.stems.some((item) => item.busy);
    all.disabled = busy;
    armable(all, 'Delete all', `free ${bytes(track.bytes)}?`, () =>
      remove(`/api/storage/tracks/${track.id}`, track.id, track.name));
    row.append(name, meta, all);

    const items = document.createElement('div');
    items.className = 'items';
    for (const wav of track.audio) items.appendChild(audioChip(wav));
    for (const item of track.stems) items.appendChild(stemsChip(item, track.id));
    li.append(row, items);
    return li;
  }

  function render(inv) {
    summary.textContent = `${bytes(inv.total_bytes)} in ${inv.cache_dir}`;
    list.innerHTML = '';
    if (!inv.tracks.length && !inv.orphans.length) {
      list.innerHTML = '<li class="empty">Nothing cached</li>';
      return;
    }
    for (const track of inv.tracks) list.appendChild(trackRow(track));
    if (inv.orphans.length) {
      const head = document.createElement('li');
      head.className = 'group';
      head.textContent = `No track known · ${bytes(inv.orphan_bytes)}`;
      head.title = 'Stems whose track has not been opened in this app, so nothing names them. Still yours to delete.';
      const li = document.createElement('li');
      const items = document.createElement('div');
      items.className = 'items';
      for (const item of inv.orphans) {
        const chip = stemsChip(item, null);
        chip.firstChild.textContent = `${item.digest} ${chip.firstChild.textContent}`;
        items.appendChild(chip);
      }
      li.appendChild(items);
      list.append(head, li);
    }
  }

  async function refresh() {
    try {
      render(await api('/api/storage'));
    } catch (error) {
      toast(error.message, true);
    }
  }

  toggle.addEventListener('click', () => {
    open = !open;
    list.hidden = !open;
    toggle.textContent = open ? 'Hide' : 'Show';
    if (open) refresh();
  });
  document.addEventListener('click', (event) => {
    if (armed && !armed.button.contains(event.target)) disarm();
  });

  return {
    refreshIfOpen: () => { if (open) refresh(); },
  };
}
