// Chhota DOM madadgar. Matn hamesha textContent se jata hai (HTML string se kabhi nahi), taake koi script ghus na sake.
export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function field(id, label, type, extra = {}) {
  return [h("label", { for: id }, label), h("input", { id, name: id, type, required: true, ...extra })];
}

// Submit par button band + "intezar" likha, phir wapas. Double-click se do darkhwast nahi jati.
export async function withLoading(btn, loadingText, fn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = loadingText;
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = original; }
}
