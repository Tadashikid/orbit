// Input that can't be a question (keyboard mashing, only digits or symbols, one key held down) is caught here, before
// any model call: the screen says so instead of spending a model call on it.
// ponytail: a heuristic for junk only. Real sentences in any language pass, and off-topic but real questions
// ("what's the weather?") still reach Orbit, which answers what it can help with.
const KEYBOARD = /qwert|werty|asdf|sdfg|dfgh|fghj|ghjk|hjkl|zxcv|xcvb|cvbn|vbnm|uiop/;
const CONSONANTS = /[bcdfghjklmnpqrstvwxz]{5,}/;
export function invalidInput(text: string): boolean {
  const t = text.trim();
  if ((t.match(/\p{L}/gu) ?? []).length < 2) return true; // only digits, symbols or emoji
  if (/(.)\1{4,}/u.test(t)) return true; // "aaaaaa", "??????"
  const words = t.toLowerCase().match(/\p{L}+/gu) ?? [];
  const junk = words.filter(
    (w) => w.length >= 4 && /^[a-z]+$/.test(w) && (KEYBOARD.test(w) || CONSONANTS.test(w) || !/[aeiouy]/.test(w)),
  );
  return junk.length > 0 && junk.length * 2 >= words.length; // mostly mashing
}
