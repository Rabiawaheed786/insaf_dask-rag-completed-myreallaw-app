// Zaban: Roman Urdu ya English. Sirf zaban ki pasand localStorage mein ("lang"); koi hassas cheez nahi.
const KEY = "lang";
const dict = {};
let lang = "roman_urdu";

export async function initI18n() {
  const [ur, en] = await Promise.all(["ur", "en"].map((f) => fetch(`/static/i18n/${f}.json`).then((r) => r.json())));
  dict.roman_urdu = ur;
  dict.en = en;
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch { /* private mode */ }
  setLang(saved === "en" ? "en" : "roman_urdu", false);
}

export const getLang = () => lang;

export function setLang(l, persist = true) {
  lang = l === "en" ? "en" : "roman_urdu";
  document.documentElement.lang = lang === "en" ? "en" : "ur-Latn";
  if (persist) { try { localStorage.setItem(KEY, lang); } catch { /* ignore */ } }
  applyStatic();
}

export function t(key) {
  return (dict[lang] && dict[lang][key]) || key;
}

export function applyStatic() {
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
}
