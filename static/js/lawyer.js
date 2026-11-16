import { api, errorText } from "./api.js";
import { alertBox, apiNode, ask, chip, empty, fill, link, noticeBox, when } from "./common.js";
import { h, withLoading } from "./dom.js";
import { bad, buildForm } from "./forms.js";
import { t } from "./i18n.js";
import { state } from "./state.js";

function action(label, run, cls = "btn small") {
  const b = h("button", { class: cls, type: "button" }, label);
  b.addEventListener("click", () => withLoading(b, t("loading"), run));
  return b;
}

export function lawyerHome() {
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("nav_lawyer")),
      h("h1", {}, t("lv_title"))));
  const box = h("div", { class: "stack" });
  root.append(box);
  fill(box, async () => {
    const me = await api("GET", "/api/auth/me");  // role taza (verify ke baad badalti hai)
    if (me.ok) state.user = me.data;
    const r = await api("GET", "/api/lawyer/me");
    if (r.status === 404) return applyCard();
    if (!r.ok) return alertBox(errorText(r));
    const p = r.data;
    const head = h("div", { class: "card profile-card" }, h("p", {}, `${p.bar_council} | ${p.licence_no} | ${p.city}`), chip(t(`lv_${p.status}`), p.status === "verified" ? "ok" : "warn"));
    if (p.status !== "verified") return [head, noticeBox(t(`lv_wait_${p.status}`))];
    const cases = casesCard();
    return [head, offersCard(cases.reload), h("div", { class: "lawyer-grid" }, cases.box, availabilityCard())];
  });
  return root;
}

function applyCard() {
  const f = buildForm([
    { id: "bar_council", label: t("lv_bar"), attrs: { maxlength: 120 } },
    { id: "licence_no", label: t("lv_licence"), attrs: { maxlength: 60 } },
    { id: "city", label: t("lv_city"), attrs: { maxlength: 80 } },
  ], "lv_apply_btn", (v) => (v.bar_council && v.licence_no && v.city ? api("POST", "/api/lawyer/apply", v) : bad()),
  { onDone: () => setTimeout(() => location.reload(), 300) });
  return h("div", { class: "card apply-card" }, h("h2", {}, t("lv_apply")), h("p", { class: "hint" }, t("lv_apply_hint")), f.el);
}

function offersCard(afterChange) {
  const box = h("div", { class: "card offers-card" });
  const load = () => fill(box, async () => [h("h2", {}, t("lv_offers")), apiNode(await api("GET", "/api/lawyer/offers"), (d) => d.offers.length
    ? h("ul", { class: "plain" }, d.offers.map((o) => h("li", {}, h("strong", {}, o.tracking_no), ` ${o.category_label} | ${o.city}`,
      h("div", { class: "hint" }, `${t("lv_expires")}: ${when(o.expires_at)}`),
      h("div", { class: "row" },
        action(t("lv_accept"), async () => { const r = await api("POST", `/api/lawyer/offers/${o.offer_id}/accept`); if (!r.ok) box.prepend(alertBox(errorText(r))); load(); afterChange(); }),
        action(t("lv_decline"), async () => { await api("POST", `/api/lawyer/offers/${o.offer_id}/decline`); load(); }, "btn secondary small")))))
    : empty("lv_no_offers"))]);
  load();
  return box;
}

function casesCard() {
  const box = h("div", { class: "card cases-card" });
  const reload = () => fill(box, async () => [h("h2", {}, t("lv_cases")), apiNode(await api("GET", "/api/lawyer/cases"), (d) => d.cases.length
    ? h("ul", { class: "plain" }, d.cases.map((c) => h("li", {}, link(`#/lawyer-case/${c.tracking_no}`, c.tracking_no, "big"), h("div", {}, `${c.category_label} | ${c.city}`))))
    : empty("lv_no_cases"))]);
  reload();
  return { box, reload };  // offer qubool hone par yeh list bhi taza ho
}

function availabilityCard() {
  const box = h("div", { class: "card availability-card" }), list = h("div");
  const load = () => fill(list, async () => apiNode(await api("GET", "/api/lawyer/availability"), (d) => d.slots.length
    ? h("ul", { class: "plain" }, d.slots.map((s) => h("li", { class: "slot-row" },
      h("div", {},
        h("div", {}, `${when(s.start)} - ${when(s.end)}`),
        h("div", { class: "chips" }, chip(t(`slot_${s.status}`), s.status === "booked" ? "ok" : ""), s.booked_tracking_no ? h("span", { class: "meta" }, s.booked_tracking_no) : null)),
      action(t("slots_cancel"), async () => { if (ask("lv_slot_cancel_confirm")) { await api("DELETE", `/api/lawyer/availability/${s.id}`); load(); } }, "btn secondary small"))))
    : empty("lv_no_slots")));
  const f = buildForm([
    { id: "date", label: t("lv_date"), type: "date" }, { id: "start", label: t("lv_from"), type: "time" }, { id: "end", label: t("lv_to"), type: "time" },
    { id: "repeat", label: t("lv_repeat"), type: "select", options: [["none", t("rep_none")], ["daily", t("rep_daily")], ["weekly", t("rep_weekly")]] },
    { id: "repeat_count", label: t("lv_repeat_count"), type: "number", value: 1, attrs: { min: 1, max: 14 } },
  ], "lv_publish", (v) => (v.date && v.start && v.end
    ? api("POST", "/api/lawyer/availability", { start: `${v.date}T${v.start}:00`, end: `${v.date}T${v.end}:00`, repeat: v.repeat, repeat_count: v.repeat_count || 1 })
    : bad()), { onDone: load });
  box.append(h("h2", {}, t("lv_avail")), h("p", { class: "hint" }, t("lv_avail_hint")), f.el, list);
  load();
  return box;
}

export function lawyerCase(tn) {
  const root = h("section"), box = h("div");
  root.append(box);
  fill(box, async () => apiNode(await api("GET", `/api/lawyer/cases/${tn}`), (c) => [
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("lv_cases")),
      h("h1", {}, c.tracking_no),
      h("p", { class: "meta" }, `${c.category_label} | ${c.city}${c.province ? " | " + c.province : ""}`),
      c.safe_time ? h("p", { class: "hint" }, `${t("new_safe_time")}: ${c.safe_time}`) : null),
    h("div", { class: "card detail-card detail-body" }, h("h2", {}, t("req_statement")), h("p", {}, c.statement), h("h2", {}, t("req_summary")), h("p", {}, c.summary)),
    h("div", { class: "row" }, link(`#/case/${tn}`, t("req_room"), "btn"), link("#/lawyer", t("room_back_lawyer"), "btn secondary"))]));
  return root;
}
