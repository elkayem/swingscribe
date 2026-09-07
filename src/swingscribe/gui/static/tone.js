/* A note's pitch, sounded on its own.
 *
 * The Edit tool asks the listener to judge a note by ear: is the one under
 * the pointer the note that was played, or bleed from another hand? The
 * recording answers "what happened", but a chord of four notes at 240 bpm
 * does not tell you which of them is the F sharp. A plain tone at the note's
 * pitch does, held beside the recording in the ear. It is synthesised here
 * rather than played back from the stem because the stem cannot isolate one
 * note of a chord, and because a reference pitch should carry no timbre to
 * argue with.
 *
 * Web Audio only, no library: a sine fundamental, a little triangle for the
 * attack, a touch of octave for the piano's brightness, and a decay that
 * follows the note's own length within sensible bounds.
 */

const MIN_S = 0.35;
const MAX_S = 1.2;
const LEVEL = 0.22;

let ctx = null;

function context() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

export function midiToHz(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

/* Sound `midi` for about `seconds`. Called from a click, so the browser's
   gesture rule for starting audio is already satisfied. */
export function playPitch(midi, seconds = 0.5) {
  const ac = context();
  const now = ac.currentTime;
  const hold = Math.min(MAX_S, Math.max(MIN_S, seconds || 0));
  const hz = midiToHz(midi);

  const out = ac.createGain();
  out.gain.setValueAtTime(0, now);
  out.gain.linearRampToValueAtTime(LEVEL, now + 0.008);
  out.gain.exponentialRampToValueAtTime(0.001, now + hold);
  out.connect(ac.destination);

  const voices = [
    ['sine', hz, 1.0, hold],
    ['triangle', hz, 0.3, Math.min(hold, 0.25)],
    ['sine', hz * 2, 0.12, Math.min(hold, 0.5)],
  ];
  for (const [type, frequency, level, decay] of voices) {
    const osc = ac.createOscillator();
    osc.type = type;
    osc.frequency.value = frequency;
    const gain = ac.createGain();
    gain.gain.setValueAtTime(level, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + decay);
    osc.connect(gain).connect(out);
    osc.start(now);
    osc.stop(now + hold + 0.02);
  }
}
