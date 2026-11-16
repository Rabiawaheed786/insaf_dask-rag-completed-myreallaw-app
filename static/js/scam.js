import { link } from "./common.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";

const STEP_GROUPS = [
  ["scam_group_immediate", [1, 2, 3, 4, 5]],
  ["scam_group_report", [6, 7, 8, 9]],
  ["scam_group_protect", [10, 11, 12, 13]],
  ["scam_group_after", [14, 15]],
];

// Alag safha: fraud checklist sirf yahan rehti hai, AI guftagu ke saath mix nahi hoti.
export function scamHelp() {
  return h("section", { class: "scam-page" },
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("scam_page_eyebrow")),
      h("h1", {}, t("scam_title")),
      h("p", { class: "lead" }, t("scam_lead")),
      h("div", { class: "page-meta" },
        h("span", { class: "badge badge-info" }, t("scam_steps_badge")),
        h("span", { class: "badge badge-ok" }, t("legal_verified_badge")),
        link("#/legal", t("scam_back_ai"), "back-link"))),
    scamCard());
}

function scamCard() {
  const done = new Set(), rows = [];
  const bar = h("progress", { class: "progress", max: 15, value: 0 });
  const counter = h("span", { class: "meta" });
  const reset = h("button", { class: "btn secondary small", type: "button" }, t("scam_reset"));
  const update = () => {
    const n = done.size;
    bar.value = n;
    counter.textContent = `${t("scam_progress")} ${n} / 15`;
  };
  reset.addEventListener("click", () => {
    done.clear();
    rows.forEach(({ input, row }) => { input.checked = false; row.classList.remove("done"); });
    update();
  });

  const list = h("div", { class: "checklist" });
  for (const [groupKey, nums] of STEP_GROUPS) {
    const group = h("section", { class: "checklist-group" }, h("h3", {}, t(groupKey)));
    const inner = h("div", { class: "checklist" });
    for (const n of nums) {
      const input = h("input", { type: "checkbox", id: `scam_step_${n}` });
      const row = h("label", { class: "checklist-item", for: `scam_step_${n}` },
        input, h("span", { class: "checklist-text" }, t(`scam_step_${n}`)));
      input.addEventListener("change", () => {
        if (input.checked) done.add(n); else done.delete(n);
        row.classList.toggle("done", input.checked);
        update();
      });
      rows.push({ input, row });
      inner.append(row);
    }
    group.append(inner);
    list.append(group);
  }
  update();

  return h("section", { class: "card scam-card" },
    h("div", { class: "helpline-inline" },
      h("strong", {}, t("home_help_title")),
      h("a", { href: "tel:1799" }, t("home_help_nccia")),
      h("span", { "aria-hidden": "true" }, "|"),
      h("a", { href: "tel:15" }, t("home_help_police"))),
    h("div", { class: "checklist-progress" }, bar, counter, reset),
    list,
    h("p", { class: "hint" }, t("scam_note")),
    h("div", { class: "row" },
      link("#/legal", t("scam_open_ai"), "btn"),
      link("#/new", t("scam_new_request"), "btn secondary"),
      link("#/emergency", t("scam_helplines"), "btn secondary")));
}
