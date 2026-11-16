import { errorText } from "./api.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";

export const alertBox = (text) => h("div", { class: "alert", role: "alert" }, text);
export const noticeBox = (text) => h("div", { class: "notice" }, text);
export const chip = (text, kind = "neutral") => h("span", { class: `badge badge-${kind}`.trim() }, text);
export const empty = (key) => h("p", { class: "empty" }, t(key));

// Badge rang: Saved = neutral, referral delivered = blue, lawyer accepted = emerald.
const TONE = {
  st_saved: "neutral", st_closed: "neutral",
  ref_not_sent: "neutral", ref_pending: "warn", ref_delivered: "info", ref_failed: "danger",
  law_not_assigned: "neutral", law_accepted: "ok",
  cr_pending: "warn", cr_cleared: "ok", cr_not_needed: "neutral",
};

// Server ka waqt UTC hota hai (aksar bina Z ke): user ke apne waqt mein dikhao.
export function when(iso) {
  if (!iso) return "";
  const z = /(Z|[+-]\d\d:\d\d)$/.test(iso) ? iso : iso + "Z";
  return new Date(z).toLocaleString();
}

// Jagah par "intezar" likho, phir loader ka nateeja (node ya node ki list) rakh do.
export async function fill(box, loader) {
  box.replaceChildren(h("p", { class: "empty" }, t("loading")));
  try { box.replaceChildren(...[await loader()].flat(Infinity).filter((x) => x != null && x !== false)); } catch { box.replaceChildren(alertBox(t("err_generic"))); }
}

export const apiNode = (r, render) => (r.ok ? render(r.data) : alertBox(errorText(r)));

export function statusChips(q) {
  const out = [
    chip(t(`st_${q.status}`), TONE[`st_${q.status}`] || "neutral"),
    chip(t(`ref_${q.referral_status}`), TONE[`ref_${q.referral_status}`] || "neutral"),
    chip(t(`law_${q.lawyer_status}`), TONE[`law_${q.lawyer_status}`] || "neutral"),
  ];
  if (q.child_review && q.child_review !== "not_needed") out.push(chip(t(`cr_${q.child_review}`), "warn"));
  return h("div", { class: "chips" }, out);
}

export const evLabel = (e) => { const k = `ev_${e}`; const v = t(k); return v === k ? e : v; };

export function link(href, text, cls = "") { return h("a", { href, class: cls }, text); }
export function ask(key) { return window.confirm(t(key)); }
