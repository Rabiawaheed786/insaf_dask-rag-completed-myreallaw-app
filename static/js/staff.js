import { api, errorText, idemKey } from "./api.js";
import { alertBox, apiNode, ask, chip, empty, fill, link, noticeBox, when } from "./common.js";
import { h, withLoading } from "./dom.js";
import { bad, buildForm } from "./forms.js";
import { t } from "./i18n.js";
import { state } from "./state.js";

const kv = (k, v) => h("tr", {}, h("th", {}, k), h("td", {}, String(v)));

// Admin/coordinator BYOK: key sirf masked dikhti hai; key khali chhodne par purani qaim rehti hai.
function aiConfigCard() {
  const card = h("div", { class: "card", id: "ad_ai_card" });
  const load = () => fill(card, async () => {
    const r = await api("GET", "/api/admin/ai-config");
    if (!r.ok) return [h("h2", {}, t("ad_ai_title")), alertBox(errorText(r))];
    const c = r.data, defaults = c.default_models || {};
    const saved = c.configured
      ? `${t("ad_ai_saved")}: ${c.masked_key}${c.source === "environment" ? ` (${t("ad_ai_env")})` : ""}`
      : t("ad_ai_none");
    const f = buildForm([
      { id: "provider_name", label: t("ad_ai_provider"), type: "select", value: c.provider_name,
        options: [["gemini", "Gemini"], ["openai", "OpenAI"], ["deepseek", "DeepSeek"]] },
      { id: "model_name", label: t("ad_ai_model"), value: c.model_name, hint: t("ad_ai_model_hint") },
      { id: "api_key", label: t("ad_ai_key"), type: "password", hint: saved,
        attrs: { autocomplete: "off", maxlength: 500 } },
    ], "ad_ai_save", (v) => api("PUT", "/api/admin/ai-config", {
      provider_name: v.provider_name, model_name: v.model_name, api_key: v.api_key,
    }), { onDone: load });
    const sync = () => { f.inputs.model_name.placeholder = defaults[f.inputs.provider_name.value] || ""; };
    f.inputs.provider_name.addEventListener("change", sync);
    sync();
    return [h("h2", {}, t("ad_ai_title")), h("p", { class: "hint" }, t("ad_ai_hint")), f.el];
  });
  load();
  return card;
}

export function coordHome() {
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("nav_coord")),
      h("h1", {}, t("co_title"))));
  const daily = h("div", { class: "card" }), weekly = h("div", { class: "card" });
  fill(daily, async () => [h("h2", {}, t("co_daily")), apiNode(await api("GET", "/api/coord/reports/daily"), (d) => [
    h("div", { class: "stat-strip" },
      h("div", { class: "stat" }, h("strong", {}, String(d.unassigned_count)), h("span", {}, t("co_unassigned"))),
      h("div", { class: "stat" }, h("strong", {}, String(d.overdue_count)), h("span", {}, t("co_overdue")))),
    d.unassigned.length ? h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["co_tracking", "co_category", "co_city", "co_days", "co_flags"].map((k) => h("th", {}, t(k))))),
      h("tbody", {}, d.unassigned.map((x) => h("tr", {}, h("td", {}, link(`#/coord-case/${x.tracking_no}`, x.tracking_no)), h("td", {}, x.category), h("td", {}, x.city), h("td", {}, x.days_waiting),
        h("td", {}, x.overdue ? chip(t("co_overdue"), "warn") : null, x.offer_pending ? chip(t("co_offer_pending")) : null, x.child_review === "pending" ? chip(t("cr_pending"), "warn") : null)))))) : empty("co_empty")])]);
  fill(weekly, async () => [h("h2", {}, t("co_weekly")), apiNode(await api("GET", "/api/coord/reports/weekly"), (w) => [h("div", { class: "scroll" }, h("table", { class: "kv-table" }, h("tbody", {},
    kv(t("co_pending"), w.pending_requests), kv(t("co_new_week"), w.new_this_week), kv(t("co_accepted_week"), w.accepted_this_week), kv(t("co_closed_week"), w.closed_this_week),
    kv(t("co_by_cat"), Object.entries(w.pending_by_category).map(([k, v]) => `${k}: ${v}`).join(", ") || "-"),
    kv(t("co_workload"), w.lawyer_workload.map((l) => `${l.display_name}: ${l.active_cases}`).join(", ") || "-"))))])]);
  root.append(h("div", { class: "split-grid" }, daily, weekly), aiConfigCard());
  return root;
}

export function coordCase(tn) {
  const root = h("section"), box = h("div", { class: "stack" });
  root.append(box);
  const load = () => fill(box, async () => {
    const r = await api("GET", `/api/coord/requests/${tn}`);
    if (!r.ok) return alertBox(errorText(r));
    const c = r.data, parts = [
      h("div", { class: "page-head" },
        h("span", { class: "eyebrow" }, t("co_title")),
        h("h1", {}, c.tracking_no),
        h("p", { class: "meta" }, `${c.category_label} | ${c.city}${c.province ? " | " + c.province : ""}`),
        h("div", { class: "chips" }, chip(t(`st_${c.status}`)), chip(t(`ref_${c.referral_status}`)), chip(t(`law_${c.lawyer_status}`)), c.child_review !== "not_needed" ? chip(t(`cr_${c.child_review}`), "warn") : null)),
      h("div", { class: "card detail-card" }, h("h2", {}, t("req_summary")), c.summary ? h("p", {}, c.summary) : noticeBox(t("co_no_consent")))];
    if (c.referrals.length) parts.push(h("div", { class: "card detail-card" }, h("h2", {}, t("co_referrals")), h("ul", { class: "plain" }, c.referrals.map((x) => h("li", {}, `${x.target}: ${x.status}`, x.ack_ref ? ` (${x.ack_ref})` : "", x.failed_reason ? ` - ${x.failed_reason}` : "", h("div", { class: "hint" }, when(x.at)))))));
    if (c.assignment) {
      const rv = h("button", { class: "btn secondary", type: "button" }, t("co_revoke"));
      rv.addEventListener("click", () => ask("co_revoke_confirm") && withLoading(rv, t("loading"), async () => { await api("POST", `/api/coord/assignments/${c.assignment.id}/revoke`); load(); }));
      parts.push(h("div", { class: "card detail-card" }, h("h2", {}, t("co_assignment")), h("p", {}, `${c.assignment.status} | ${t("lv_expires")}: ${when(c.assignment.expires_at)}`), rv));
    } else if (c.status !== "closed") {
      const lw = await api("GET", "/api/coord/lawyers");
      const opts = lw.ok ? lw.data.lawyers.map((l) => [String(l.lawyer_id), `${l.display_name} (${l.city}) - ${l.active_cases}`]) : [];
      const f = opts.length ? buildForm([
        { id: "lawyer_id", label: t("co_lawyer"), type: "select", options: opts },
        { id: "days", label: t("co_days_valid"), type: "number", value: 3, attrs: { min: 1, max: 14 } },
      ], "co_assign_btn", (v) => api("POST", `/api/coord/requests/${tn}/assign`, { lawyer_id: Number(v.lawyer_id), expires_in_days: v.days || 3 }), { onDone: load }) : null;
      parts.push(h("div", { class: "card detail-card" }, h("h2", {}, t("co_assign")), f ? f.el : empty("co_no_lawyers")));
    }
    if (c.status !== "closed") {
      const key = idemKey();
      const rf = buildForm([
        { id: "target", label: t("co_target"), attrs: { maxlength: 120 } },
        { id: "status", label: t("co_ref_status"), type: "select", options: [["attempted", "attempted"], ["delivered", "delivered"], ["failed", "failed"]] },
        { id: "ack_ref", label: t("co_ack"), hint: t("co_ack_hint") },
        { id: "failed_reason", label: t("co_reason") },
      ], "co_ref_btn", (v) => (v.target ? api("POST", `/api/coord/requests/${tn}/referrals`, { target: v.target, status: v.status, ack_ref: v.ack_ref || null, failed_reason: v.failed_reason || null }, { "Idempotency-Key": `${key}-${v.status}-${v.target}`.slice(0, 100) }) : bad()), { onDone: load });
      parts.push(h("div", { class: "card detail-card" }, h("h2", {}, t("co_record_ref")), c.referral_consent ? null : noticeBox(t("co_no_consent")), rf.el));
    }
    parts.push(link("#/coord", t("room_back"), "btn secondary"));
    return parts;
  });
  load();
  return root;
}

function statCard(label, value, tone) {
  return h("div", { class: "metric-card " + tone },
    h("div", { class: "metric-row" }, h("strong", { class: "metric-value" }, String(value))),
    h("span", { class: "metric-label" }, label));
}

function roleLabel(role) {
  if (role === "super_admin") return t("role_super_admin");
  if (role === "user") return t("role_user");
  return t(`role_${role}`);
}

function userRow(u, reload) {
  const isSuper = u.role === "super_admin";
  const self = state.user && state.user.id === u.id;
  const note = h("p", { class: "hint sa-row-note" });
  const btn = h("button", { class: "btn small " + (isSuper ? "secondary" : ""), type: "button",
    disabled: self && isSuper }, isSuper ? t("sa_demote") : t("sa_promote"));
  btn.addEventListener("click", () => withLoading(btn, t("loading"), async () => {
    const r = await api("PATCH", `/api/admin/users/${u.id}/role`, { role: isSuper ? "user" : "super_admin" });
    if (!r.ok) { note.textContent = errorText(r); return; }
    reload();
  }));
  return h("tr", {},
    h("td", {}, u.display_name || "-", self ? h("span", { class: "sa-you" }, ` (${t("sa_you")})`) : null),
    h("td", {}, u.email),
    h("td", {}, chip(roleLabel(u.role), isSuper ? "ok" : "neutral")),
    h("td", {}, chip(u.status === "locked" ? t("sa_locked") : t("sa_active"), u.status === "locked" ? "warn" : "ok")),
    h("td", {}, h("div", { class: "sa-row-action" }, btn, note)));
}

function usersCard(users, reload) {
  return h("div", { class: "card sa-users-card" },
    h("div", { class: "card-head" }, h("h2", {}, t("sa_users"))),
    h("div", { class: "sa-table-wrap" },
      h("table", { class: "sa-table" },
        h("thead", {}, h("tr", {}, [t("sa_name"), t("sa_email"), t("sa_role"), t("sa_status"), t("sa_actions")]
          .map((x) => h("th", {}, x)))),
        h("tbody", {}, users.map((u) => userRow(u, reload))))));
}

function auditTable(logs) {
  const head = h("div", { class: "card-head" }, h("h2", {}, t("sa_audit")));
  if (!logs.length) return h("div", { class: "card" }, head, empty("sa_audit_empty"));
  const rows = logs.map((l) => h("tr", {},
    h("td", {}, l.actor),
    h("td", {}, h("code", { class: "sa-code" }, l.action)),
    h("td", {}, when(l.at))));
  return h("div", { class: "card" }, head,
    h("div", { class: "sa-table-wrap" },
      h("table", { class: "sa-table" },
        h("thead", {}, h("tr", {}, [t("sa_actor"), t("sa_action"), t("sa_when")].map((x) => h("th", {}, x)))),
        h("tbody", {}, rows))));
}

export function superAdminPanel() {
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("sa_eyebrow")),
      h("h1", {}, t("sa_title")),
      h("p", { class: "meta" }, t("sa_lead"))));
  const stats = h("div", { class: "sa-stats" });
  const usersHost = h("div");
  const logsHost = h("div");
  root.append(stats, usersHost, logsHost);
  const loadLogs = () => fill(logsHost, async () => {
    const r = await api("GET", "/api/admin/audit-logs");
    return r.ok ? [auditTable(r.data.logs)] : [alertBox(errorText(r))];
  });
  const reload = () => { loadUsers(); loadLogs(); };
  const loadUsers = () => fill(usersHost, async () => {
    const r = await api("GET", "/api/admin/users");
    if (!r.ok) { stats.replaceChildren(); return [alertBox(errorText(r))]; }
    stats.replaceChildren(
      statCard(t("sa_stat_users"), r.data.stats.users, "tone-1"),
      statCard(t("sa_stat_kbs"), r.data.stats.knowledge_bases, "tone-2"),
      statCard(t("sa_stat_queries"), r.data.stats.queries, "tone-3"));
    return usersCard(r.data.users, reload);
  });
  reload();
  return root;
}

export function adminHome() {
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("nav_admin")),
      h("h1", {}, t("ad_title"))));
  const lawyers = h("div", { class: "card" }), status = h("select", { id: "ad_filter", "aria-label": t("ad_filter") },
    ["pending", "verified", "rejected", "suspended"].map((s) => h("option", { value: s }, t(`lv_${s}`))));
  const loadLawyers = () => fill(lawyers, async () => [h("h2", {}, t("ad_lawyers")), status, apiNode(await api("GET", `/api/admin/lawyers?status=${status.value}`), (d) => d.lawyers.length
    ? h("div", { class: "admin-lawyers" }, d.lawyers.map((l) => lawyerCard(l)))
    : empty("ad_no_lawyers"))]);
  status.addEventListener("change", loadLawyers);
  function lawyerCard(l) {
    const vf = buildForm([
      { id: "identity_checked", label: t("ad_identity"), type: "checkbox" }, { id: "registration_checked", label: t("ad_registration"), type: "checkbox" },
      { id: "source_note", label: t("ad_source"), hint: t("ad_source_hint") }], "ad_verify", (v) => api("POST", `/api/admin/lawyers/${l.id}/verify`, v), { onDone: loadLawyers });
    const rf = buildForm([{ id: "reason", label: t("ad_reason") }], "ad_reject", (v) => (v.reason ? api("POST", `/api/admin/lawyers/${l.id}/reject`, v) : bad()), { onDone: loadLawyers });
    const sf = buildForm([{ id: "reason", label: t("ad_reason") }], "ad_suspend", (v) => (v.reason && ask("ad_suspend_confirm") ? api("POST", `/api/admin/lawyers/${l.id}/suspend`, v) : bad()), { onDone: loadLawyers });
    return h("div", { class: "subcard" }, h("p", {}, h("strong", {}, `${l.display_name || l.email}`), ` (${l.email})`), h("p", {}, `${l.bar_council} | ${l.licence_no} | ${l.city}`), chip(t(`lv_${l.status}`)),
      l.source_note ? h("p", { class: "hint" }, `${t("ad_source")}: ${l.source_note}`) : null,
      l.status !== "verified" ? h("details", {}, h("summary", {}, t("ad_verify")), vf.el) : null,
      l.status === "pending" ? h("details", {}, h("summary", {}, t("ad_reject")), rf.el) : null,
      l.status === "verified" ? h("details", {}, h("summary", {}, t("ad_suspend")), sf.el) : null);
  }
  loadLawyers();
  const contact = buildForm([
    { id: "name", label: t("ad_c_name") }, { id: "phone", label: t("ad_c_phone") },
    { id: "scope", label: t("ad_c_scope"), type: "select", options: [["national", "national"], ...["punjab", "sindh", "kpk", "balochistan", "islamabad", "gilgit_baltistan", "ajk"].map((p) => [p, p])] },
    { id: "source_url", label: t("ad_c_source"), type: "url", hint: t("ad_c_source_hint") }, { id: "verified_on", label: t("ad_c_date"), type: "date" },
    { id: "note_roman_urdu", label: t("ad_c_note_ur") }, { id: "note_en", label: t("ad_c_note_en") },
    { id: "emergency", label: t("ad_c_emergency"), type: "checkbox" },
  ], "ad_c_btn", (v) => (v.name && v.phone && v.source_url && v.verified_on ? api("POST", "/api/admin/contacts", v) : bad()), { reset: true });
  const child = buildForm([
    { id: "tracking_no", label: t("co_tracking") },
    { id: "decision", label: t("ad_decision"), type: "select", options: [["cleared", "cleared"], ["pending", "pending"]] },
    { id: "note", label: t("ad_note"), hint: t("ad_note_hint") },
  ], "ad_review_btn", (v) => (v.tracking_no ? api("POST", `/api/admin/requests/${v.tracking_no.toUpperCase()}/child-review`, { decision: v.decision, note: v.note }) : bad()), { reset: true });
  const role = buildForm([
    { id: "email", label: t("field_email"), type: "email" },
    { id: "role", label: t("ad_role"), type: "select", options: [["user", "user"], ["coordinator", "coordinator"], ["admin", "admin"]] },
  ], "ad_role_btn", (v) => (v.email ? api("PUT", "/api/admin/users/role", v) : bad()), { reset: true });
  const jobs = h("div"), run = h("button", { class: "btn secondary", type: "button" }, t("ad_jobs_btn"));
  run.addEventListener("click", () => withLoading(run, t("loading"), async () => {
    const r = await api("POST", "/api/admin/jobs/run");
    jobs.replaceChildren(r.ok ? h("div", { class: "success" }, JSON.stringify(r.data)) : alertBox(errorText(r)));
  }));
  root.append(lawyers,
    h("div", { class: "admin-grid" },
      h("div", { class: "card", id: "ad_contacts_card" }, h("h2", {}, t("ad_contacts")), h("p", { class: "hint" }, t("ad_contacts_hint")), contact.el),
      h("div", { class: "card" }, h("h2", {}, t("ad_review")), child.el),
      h("div", { class: "card" }, h("h2", {}, t("ad_roles")), role.el),
      aiConfigCard()),
    h("div", { class: "card" }, h("h2", {}, t("ad_jobs")), h("p", { class: "hint" }, t("ad_jobs_hint")), run, jobs));
  return root;
}
