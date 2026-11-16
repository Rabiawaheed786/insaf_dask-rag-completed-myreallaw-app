import { errorText } from "./api.js";
import { h, withLoading } from "./dom.js";
import { t } from "./i18n.js";

// Aam form: fields [{id,label,type,options,value,hint,rows,maxlength,attrs,group}];
// group ek i18n key hai: ek jaisi fields ek section mein aati hain. onSubmit(values) ko api ka nateeja wapas dena hai.
export function buildForm(fields, submitKey, onSubmit, opts = {}) {
  const msg = h("div", { role: "status", "aria-live": "polite" });
  const btn = h("button", { class: "btn", type: "submit" }, t(submitKey));
  const inputs = {};
  const blocks = [];
  let group = null, groupKey = null;

  for (const f of fields) {
    let el;
    if (f.type === "select") el = h("select", { id: f.id, name: f.id }, f.options.map(([v, l]) => h("option", { value: v }, l)));
    else if (f.type === "textarea") el = h("textarea", { id: f.id, name: f.id, rows: f.rows || 4, maxlength: f.maxlength });
    else if (f.type === "checkbox") el = h("input", { id: f.id, name: f.id, type: "checkbox" });
    else el = h("input", { id: f.id, name: f.id, type: f.type || "text", ...(f.attrs || {}) });
    if (f.value != null) { if (f.type === "checkbox") el.checked = !!f.value; else el.value = f.value; }
    inputs[f.id] = el;

    const row = f.type === "checkbox"
      ? h("div", { class: "check" }, el, h("label", { for: f.id, class: "inline" }, f.label))
      : h("div", { class: f.wide ? "field field-wide" : "field" }, h("label", { for: f.id }, f.label), el, f.hint ? h("p", { class: "hint" }, f.hint) : null);

    if (f.group) {
      if (!group || groupKey !== f.group) {
        groupKey = f.group;
        group = h("section", { class: "form-group" }, h("h3", { class: "form-group-title" }, t(f.group)));
        blocks.push(group);
      }
      group.append(row);
    } else {
      blocks.push(row);
    }
  }

  const el = h("form", { novalidate: true }, blocks, msg, h("div", { class: "row" }, btn));
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.replaceChildren();
    const values = {};
    for (const f of fields) {
      const i = inputs[f.id];
      values[f.id] = f.type === "checkbox" ? i.checked : f.type === "number" ? Number(i.value) : i.value.trim();
    }
    const r = await withLoading(btn, t("loading"), () => onSubmit(values));
    if (!r) return;
    if (r.ok) {
      msg.append(h("div", { class: "success" }, r.successText || t("saved_ok")));
      if (opts.reset) el.reset();
      if (opts.onDone) opts.onDone(r);
    } else msg.append(h("div", { class: "alert", role: "alert" }, errorText(r)));
  });
  return { el, inputs, msg };
}

export const bad = () => ({ ok: false, status: 422, data: { detail: [] } });  // form adhoora: "maloomat sahi nahi"
