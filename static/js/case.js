import { api, apiUpload, errorText, idemKey } from "./api.js";
import { alertBox, apiNode, ask, empty, fill, link, noticeBox, when } from "./common.js";
import { h, withLoading } from "./dom.js";
import { state } from "./state.js";
import { t } from "./i18n.js";

// Chat, files aur waqt (slots): sirf request ka malik ya us ka accepted wakeel.
export function caseRoom(tn) {
  const isLawyer = state.user.role === "lawyer";
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("room_title")),
      h("h1", {}, tn)));
  const panel = h("div", { class: "card room-panel" });
  const tabs = [["chat", chatPanel], ["files", filesPanel], ...(isLawyer ? [] : [["slots", slotsPanel]])];
  const bar = h("div", { class: "tabs", role: "group" });
  const show = (name) => {
    clearInterval(state.timer);
    bar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tab === name)));
    tabs.find((x) => x[0] === name)[1](panel, tn);
  };
  tabs.forEach(([name]) => {
    const b = h("button", { type: "button", "data-tab": name }, t(`room_${name}`));
    b.addEventListener("click", () => show(name));
    bar.append(b);
  });
  root.append(bar, panel, h("p", { class: "meta" }, link(isLawyer ? `#/lawyer-case/${tn}` : "#/dashboard", t("room_back"))));
  show("chat");
  return root;
}

function chatPanel(panel, tn) {
  const list = h("div", { class: "msgs", "aria-live": "polite" }), status = h("div");
  let pending = null;  // bheja jaa raha message: network error par wahi key dobara
  const box = h("textarea", { id: "chat_body", rows: 3, maxlength: 2000 });
  const send = h("button", { class: "btn", type: "submit" }, t("room_send"));
  const refresh = h("button", { class: "btn secondary small", type: "button" }, t("room_refresh"));
  const load = async () => {
    const r = await api("GET", `/api/cases/${tn}/messages`);
    if (!r.ok) { status.replaceChildren(alertBox(errorText(r))); return; }
    list.replaceChildren(...(r.data.messages.length ? r.data.messages.map((m) => h("div", { class: `bubble ${m.mine ? "mine" : ""}` },
      h("small", {}, `${m.mine ? t("room_me") : t(`role_${m.from}`)} | ${when(m.at)}`), m.body)) : [empty("room_no_msgs")]));
    list.scrollTop = list.scrollHeight;
    status.replaceChildren(r.data.chat_open ? "" : noticeBox(t("room_chat_closed")));
    send.disabled = !r.data.chat_open;
  };
  const form = h("form", { class: "chat-form" }, h("label", { for: "chat_body" }, t("room_write")), box, h("div", { class: "row" }, send, refresh));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = box.value.trim();
    if (!body) return;
    if (!pending || pending.body !== body) pending = { body, key: idemKey() };
    const r = await withLoading(send, t("loading"), () => api("POST", `/api/cases/${tn}/messages`, { body }, { "Idempotency-Key": pending.key }));
    if (r.ok) { pending = null; box.value = ""; status.replaceChildren(); load(); } else status.replaceChildren(alertBox(errorText(r)));
  });
  refresh.addEventListener("click", load);
  panel.replaceChildren(status, list, form);
  load();
  state.timer = setInterval(load, 20000);
}

function filesPanel(panel, tn) {
  const list = h("div"), msg = h("div");
  const input = h("input", { id: "file_input", type: "file", accept: ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" });
  const up = h("button", { class: "btn", type: "button" }, t("files_upload"));
  const load = () => fill(list, async () => apiNode(await api("GET", `/api/cases/${tn}/attachments`), (d) => d.attachments.length
    ? h("ul", { class: "plain file-list" }, d.attachments.map((a) => {
      const del = h("button", { class: "btn secondary small", type: "button" }, t("files_delete"));
      del.addEventListener("click", () => ask("files_delete_confirm") && withLoading(del, t("loading"), async () => {
        const r = await api("DELETE", `/api/cases/${tn}/attachments/${a.id}`);
        if (!r.ok) msg.replaceChildren(alertBox(errorText(r)));
        load();
      }));
      return h("li", {}, h("a", { href: `/api/cases/${tn}/attachments/${a.id}`, download: a.name }, a.name),
        h("div", { class: "hint" }, `${Math.ceil(a.size / 1024)} KB | ${t(`role_${a.uploaded_by}`)} | ${when(a.at)}`), del);
    }))
    : empty("files_empty")));
  up.addEventListener("click", () => withLoading(up, t("loading"), async () => {
    msg.replaceChildren();
    const f = input.files[0];
    if (!f) { msg.append(alertBox(t("files_choose"))); return; }
    const r = await apiUpload(`/api/cases/${tn}/attachments`, f);
    if (r.ok) { input.value = ""; msg.append(h("div", { class: "success" }, t("saved_ok"))); load(); } else msg.append(alertBox(errorText(r)));
  }));
  panel.replaceChildren(h("p", { class: "hint" }, t("files_hint")), h("label", { for: "file_input" }, t("files_choose")), input, h("div", { class: "row" }, up), msg, list);
  load();
}

function slotsPanel(panel, tn) {
  const box = h("div");
  const load = () => fill(box, async () => apiNode(await api("GET", `/api/cases/${tn}/slots`), (d) => {
    const out = [];
    if (d.my_booking) {
      const cancel = h("button", { class: "btn secondary small", type: "button" }, t("slots_cancel"));
      cancel.addEventListener("click", () => ask("slots_cancel_confirm") && withLoading(cancel, t("loading"), async () => { await api("DELETE", `/api/cases/${tn}/slots/${d.my_booking.id}/book`); load(); }));
      out.push(h("div", { class: "success" }, `${t("slots_mine")}: ${when(d.my_booking.start)}`), cancel);
    }
    out.push(h("h2", {}, t("slots_open")));
    out.push(d.open_slots.length ? h("ul", { class: "plain" }, d.open_slots.map((s) => {
      const b = h("button", { class: "btn small", type: "button" }, t("slots_book"));
      b.addEventListener("click", () => withLoading(b, t("loading"), async () => {
        const r = await api("POST", `/api/cases/${tn}/slots/${s.id}/book`);
        if (!r.ok) box.prepend(alertBox(errorText(r)));
        else load();
      }));
      return h("li", { class: "slot-row" }, `${when(s.start)} - ${when(s.end)} `, b);
    })) : empty("slots_empty"));
    return out;
  }));
  panel.replaceChildren(box);
  load();
}
