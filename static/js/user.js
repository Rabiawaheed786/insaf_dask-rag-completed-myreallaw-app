import { api, errorText, idemKey } from "./api.js";
import { alertBox, apiNode, ask, empty, evLabel, fill, link, noticeBox, statusChips, when } from "./common.js";
import { h, withLoading } from "./dom.js";
import { bad, buildForm } from "./forms.js";
import { getLang, t } from "./i18n.js";
import { kbCard, openEmbedForFirstKb, profileCard } from "./kb.js";
import { state } from "./state.js";

const go = (hash) => { location.hash = hash; };

function scrollToBlock(el, focusSelector) {
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  if (focusSelector) setTimeout(() => el.querySelector(focusSelector)?.focus(), 320);
}

const ICONS = {
  dashboard: ["M4 4h7v7H4Z", "M13 4h7v4h-7Z", "M13 10h7v10h-7Z", "M4 13h7v7H4Z"],
  how: ["M4 6h10", "M4 12h8", "M4 18h6", "M15 15l3 3 4-5"],
  chat: ["M21 11.5a8.4 8.4 0 0 1-9 8.5 9.6 9.6 0 0 1-3-.5L4 21l1.4-4.1A8.5 8.5 0 1 1 21 11.5Z"],
  kb: ["M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5Z", "M4 18.5A2.5 2.5 0 0 1 6.5 16H20", "M9 7h7"],
  embed: ["M8 8l-4 4 4 4", "M16 8l4 4-4 4", "M13.5 5l-3 14"],
  profile: ["M20 21a8 8 0 0 0-16 0", "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"],
  audit: ["M9 4h6l1 3h4v14H4V7h4Z", "M9 12h6", "M9 16h6"],
  search: ["M11 17a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z", "M20 20l-4.3-4.3"],
  doc: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z", "M14 3v5h5", "M9 13h6", "M9 17h4"],
  upload: ["M12 15V4", "M8 8l4-4 4 4", "M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"],
  ocr: ["M8 3H5a2 2 0 0 0-2 2v3", "M16 3h3a2 2 0 0 1 2 2v3", "M8 21H5a2 2 0 0 1-2-2v-3", "M16 21h3a2 2 0 0 0 2-2v-3", "M8 9h8", "M8 12h5", "M8 15h7"],
  layers: ["M12 3 3 8l9 5 9-5-9-5Z", "M3 12.5l9 5 9-5", "M3 17l9 5 9-5"],
  shield: ["M12 3l8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6Z", "M9 12l2 2 4-4"],
  scales: ["M12 4v16", "M8 20h8", "M12 7l-5 3h10l-5-3Z", "M3 10h18", "M6 10l-3 6h6l-3-6Z", "M18 10l-3 6h6l-3-6Z"],
  logout: ["M15 12H4", "M8 8l-4 4 4 4", "M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"],
};

function icon(paths, size = 18) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function sideItem(label, iconKey, tag) {
  const parts = [icon(ICONS[iconKey], 16), h("span", { class: "dash-link-label" }, label)];
  if (tag) parts.push(h("span", { class: "dash-link-tag" + (tag === "BYOK" ? " is-byok" : "") }, tag));
  return parts;
}

function groupHead(label, tag) {
  return h("div", { class: "dash-group-head" },
    h("span", { class: "dash-group-label" }, label),
    tag ? h("span", { class: "dash-group-tag" }, tag) : null);
}

function metricCard({ label, value, tone, badge }) {
  return h("div", { class: "metric-card" + (tone ? " " + tone : "") },
    h("div", { class: "metric-row" }, h("strong", { class: "metric-value" }, value), badge || null),
    h("span", { class: "metric-label" }, label));
}

function roleBadge(role) {
  if (role === "super_admin" || role === "admin") return h("span", { class: "role-badge is-super" }, t("role_super_admin"));
  if (role === "user") return h("span", { class: "role-badge is-citizen" }, t("role_citizen_user"));
  return h("span", { class: "role-badge is-staff" }, t(`role_${role}`));
}

function ragPipelineCard() {
  const steps = [
    [t("dash_rag_1_title"), t("dash_rag_1_sub"), "upload"],
    [t("dash_rag_2_title"), t("dash_rag_2_sub"), "ocr"],
    [t("dash_rag_3_title"), t("dash_rag_3_sub"), "layers"],
    [t("dash_rag_4_title"), t("dash_rag_4_sub"), "chat"],
  ];
  const nodes = [];
  steps.forEach(([title, sub, iconKey], i) => {
    nodes.push(h("div", { class: "rag-step s" + (i + 1) },
      h("span", { class: "rag-ico", "aria-hidden": "true" }, icon(ICONS[iconKey], 22)),
      h("h3", {}, `${i + 1}. ${title}`),
      h("p", {}, sub)));
    if (i < steps.length - 1) nodes.push(h("span", { class: "rag-arrow", "aria-hidden": "true" }, "\u2192"));
  });
  return h("div", { class: "card rag-card" },
    h("div", { class: "card-head" }, h("h2", {}, t("dash_pipeline_title"))),
    h("div", { class: "rag-pipeline" }, nodes));
}

function byokSidebarBox(profileHost) {
  const chip = h("span", { class: "dash-byok-chip", "data-state": "loading" }, t("byok_loading"));
  const masked = h("span", { class: "dash-byok-masked" }, "\u2022\u2022\u2022\u2022\u2022\u2022\u2022");
  const set = (d) => {
    const on = !!d.configured;
    chip.dataset.state = on ? "active" : "none";
    chip.textContent = on ? t("dash_byok_active") : t("byok_status_none");
    masked.textContent = on ? d.masked : "\u2022\u2022\u2022\u2022\u2022\u2022\u2022";
  };
  const onChanged = (e) => {
    if (!chip.isConnected) { document.removeEventListener("byok:changed", onChanged); return; }
    set(e.detail);
  };
  document.addEventListener("byok:changed", onChanged);
  api("GET", "/api/me/gemini-key").then((r) => {
    if (r.ok) set(r.data);
    else chip.textContent = t("err_generic");
  });
  const cta = h("button", { class: "dash-byok-cta", type: "button" }, t("byok_save"));
  cta.addEventListener("click", () => scrollToBlock(profileHost, "#byok_key"));
  return h("div", { class: "dash-byok-box" },
    h("div", { class: "dash-byok-top" },
      h("p", { class: "dash-byok-title" }, t("dash_byok_title")),
      chip),
    h("p", { class: "dash-byok-label" }, t("dash_byok_key_label")),
    masked,
    cta);
}

function howRagCard() {
  const steps = [
    [t("dash_how_1_title"), t("dash_how_1_body")],
    [t("dash_how_2_title"), t("dash_how_2_body")],
    [t("dash_how_3_title"), t("dash_how_3_body")],
    [t("dash_how_4_title"), t("dash_how_4_body")],
  ];
  let active = 0;
  const body = h("p", { class: "how-body" });
  const bar = h("div", { class: "how-progress" });
  const tabs = steps.map(([title], i) => {
    const b = h("button", { class: "how-tab", type: "button" },
      h("span", { class: "how-num" }, String(i + 1)), h("span", {}, title));
    b.addEventListener("click", () => { active = i; render(); });
    return b;
  });
  const render = () => {
    tabs.forEach((b, i) => {
      b.classList.toggle("active", i === active);
      b.setAttribute("aria-pressed", String(i === active));
    });
    body.textContent = steps[active][1];
    bar.replaceChildren(...steps.map((_, i) => h("span", { class: i <= active ? "seg on" : "seg" })));
  };
  render();
  return h("div", { class: "card how-card", id: "dash-how" },
    h("div", { class: "card-head" }, h("h2", {}, t("dash_how_title"))),
    h("p", { class: "hint" }, t("dash_how_lead")),
    h("div", { class: "how-tabs" }, tabs),
    body,
    bar);
}

export function dashboard() {
  const u = state.user;
  const kbValue = h("strong", { class: "metric-value" }, "\u2013");
  const chunkValue = h("strong", { class: "metric-value" }, "\u2013");
  const queryValue = h("strong", { class: "metric-value" }, "\u2013");
  const filterMsg = h("p", { class: "hint dash-filter-msg", hidden: true }, t("dash_filter_empty"));
  const kbHost = h("div", { class: "dash-block dash-kb-block", id: "dash-kb", tabindex: "-1" });
  const profileHost = h("div", { class: "dash-block", id: "dash-profile", tabindex: "-1" });
  const howCard = howRagCard();
  howCard.hidden = true;

  const applyFilter = () => {
    const q = search.value.trim().toLowerCase();
    const items = kbHost.querySelectorAll(".kb-item");
    let shown = 0;
    items.forEach((it) => {
      const title = it.querySelector(".kb-item-title")?.textContent.toLowerCase() || "";
      const show = !q || title.includes(q);
      it.hidden = !show;
      if (show) shown++;
    });
    filterMsg.hidden = !q || !items.length || shown > 0;
  };
  const search = h("input", {
    type: "search", class: "dash-search", placeholder: t("dash_search_ph"),
    "aria-label": t("dash_search_ph"), autocomplete: "off",
  });
  search.addEventListener("input", applyFilter);
  const searchWrap = h("div", { class: "dash-search-wrap" }, icon(ICONS.search, 15), search);

  const kbNode = kbCard((kbs) => {
    kbValue.textContent = String(kbs.length);
    chunkValue.textContent = String(kbs.reduce((n, kb) => n + (kb.chunks || 0), 0));
    applyFilter();
  });
  kbHost.append(kbNode, filterMsg);
  profileHost.append(profileCard(), geminiKeyCard());

  const howBtn = h("button", { class: "dash-link", type: "button", "aria-expanded": "false" }, sideItem(t("dash_nav_how"), "how"));
  howBtn.addEventListener("click", () => {
    const open = howCard.hidden;
    howCard.hidden = !open;
    howBtn.setAttribute("aria-expanded", String(open));
    if (open) scrollToBlock(howCard);
  });

  const navChat = h("a", { class: "dash-link", href: "#/kb-chat" }, sideItem(t("dash_nav_chat"), "chat"));
  const navKb = h("button", { class: "dash-link", type: "button" }, sideItem(t("dash_nav_kb"), "kb"));
  const navEmbed = h("button", { class: "dash-link", type: "button" }, sideItem(t("dash_nav_embed"), "embed"));
  const navAudit = h("button", { class: "dash-link", type: "button" }, sideItem(t("dash_nav_audit"), "audit"));
  const navSuper = h("button", { class: "dash-link", type: "button" }, sideItem(t("nav_super_admin"), "shield"));
  navSuper.addEventListener("click", () => { location.hash = "#/super-admin"; });
  const navProfile = h("button", { class: "dash-link", type: "button" }, sideItem(t("dash_nav_profile"), "profile", "BYOK"));
  const navLogout = h("button", { class: "dash-link dash-logout", type: "button" }, sideItem(t("btn_logout"), "logout"));
  navLogout.addEventListener("click", async () => {
    await api("POST", "/api/auth/logout");
    state.user = null;
    state.next = null;
    location.hash = "#/";
  });
  const menuBtn = h("button", {
    class: "dash-side-toggle", type: "button", "aria-expanded": "true",
    "aria-controls": "dash-side-nav", "aria-label": t("dash_menu"),
  }, h("span", {}, t("dash_menu")), h("span", { class: "dash-menu-chev", "aria-hidden": "true" }, "\u25be"));

  const sidebar = h("aside", { class: "dash-side", "aria-label": t("dash_nav_dashboard") },
    h("div", { class: "dash-side-brand" },
      h("span", { class: "dash-logo-wrap", "aria-hidden": "true" }, icon(ICONS.scales, 26)),
      h("div", { class: "dash-brand-text" },
        h("span", { class: "dash-brand-name" }, "INSAF DASTAK"),
        h("span", { class: "dash-brand-sub", lang: "ur", dir: "rtl" }, "وفاقی و صوبائی قانونی معاونت")),
      menuBtn),
    searchWrap,
    h("div", { class: "dash-side-nav", id: "dash-side-nav" },
      h("div", { class: "dash-group" },
        groupHead(t("dash_side_overview")),
        h("span", { class: "dash-link active", "aria-current": "page" }, sideItem(t("dash_nav_dashboard"), "dashboard")),
        howBtn,
        navChat),
      h("div", { class: "dash-group" },
        groupHead(t("dash_side_ai"), t("dash_side_links")),
        navKb, navEmbed),
      h("div", { class: "dash-group" },
        groupHead(t("dash_side_workspace"), t("dash_side_links")),
        navProfile, navAudit, u.role === "super_admin" ? navSuper : null, navLogout)),
    byokSidebarBox(profileHost));

  navKb.addEventListener("click", () => scrollToBlock(kbHost, ".kb-item-title, #kb_new_title"));
  navEmbed.addEventListener("click", async () => {
    const opened = await openEmbedForFirstKb();
    if (!opened) scrollToBlock(kbHost);
  });
  navAudit.addEventListener("click", () => scrollToBlock(auditCard));
  navProfile.addEventListener("click", () => scrollToBlock(profileHost, "#prof_name"));

  if (window.matchMedia("(max-width: 1100px)").matches) {
    sidebar.classList.add("collapsed");
    menuBtn.setAttribute("aria-expanded", "false");
  }
  menuBtn.addEventListener("click", () => {
    const collapsed = sidebar.classList.toggle("collapsed");
    menuBtn.setAttribute("aria-expanded", String(!collapsed));
  });

  const list = h("div");
  fill(list, async () => apiNode(await api("GET", "/api/requests"), (d) => {
    queryValue.textContent = String(d.requests.length);
    return d.requests.length
      ? h("ul", { class: "plain" }, d.requests.map((q) => h("li", { class: "request-item" },
          h("div", { class: "list-item-head" },
            h("div", {}, link(`#/request/${q.id}`, q.tracking_no, "big"), h("div", { class: "meta" }, `${q.category_label} | ${q.city}`)),
            statusChips(q)))))
      : h("div", {}, empty("dash_requests_empty"), h("p", { class: "hint" }, t("dash_empty_hint")));
  }));

  const requestsCard = h("div", { class: "card", id: "dash-requests" },
    h("div", { class: "card-head" }, h("h2", {}, t("dash_requests")), link("#/new", t("nav_new"), "btn secondary small")),
    list);

  const auditCard = h("div", { class: "card", id: "dash-audit" },
    h("div", { class: "card-head" }, h("h2", {}, t("dash_audit_title"))),
    h("p", { class: "hint" }, t("dash_audit_note")));

  return h("section", { class: "dash-layout" },
    sidebar,
    h("div", { class: "dash-main" },
      h("div", { class: "dash-head" },
        h("div", {},
          h("div", { class: "dash-title-row" },
            h("h1", { class: "dash-title" }, `${t("dash_hello")}, ${u.display_name || u.email}`),
            roleBadge(u.role)),
          h("p", { class: "dash-sub" }, t("dash_sub")))),
      h("div", { class: "metric-grid" },
        metricCard({ label: t("dash_metric_kbs"), value: kbValue, tone: "tone-1" }),
        metricCard({ label: t("dash_metric_chunks"), value: chunkValue, tone: "tone-2" }),
        metricCard({ label: t("dash_metric_queries"), value: queryValue, tone: "tone-3" }),
        metricCard({
          label: t("dash_metric_grounding"), tone: "tone-4",
          value: h("strong", { class: "metric-value" }, "100%"),
          badge: h("span", { class: "badge badge-ok metric-badge" }, t("dash_strict_ai")),
        })),
      ragPipelineCard(),
      howCard,
      kbHost,
      requestsCard,
      auditCard,
      profileHost));
}

export function newRequest() {
  const key = idemKey();  // retry par wahi key: duplicate request nahi banti
  let aiUsed = false;
  const holder = h("div");
  const root = h("section", { class: "narrow" },
    h("div", { class: "card intake-card" },
      h("span", { class: "eyebrow" }, t("new_title")),
      h("h1", {}, t("new_title")),
      h("p", { class: "lead" }, t("new_lead")),
      h("div", { class: "disclaimer", role: "note" },
        h("span", { class: "disclaimer-mark", "aria-hidden": "true" }, "!"),
        h("div", {}, h("strong", {}, t("intake_disclaimer")), h("p", {}, t("intake_disclaimer_note")))),
      holder));
  fill(holder, async () => {
    const c = await api("GET", "/api/categories");
    if (!c.ok) return alertBox(errorText(c));
    const opt = (arr) => arr.map((x) => [x.key, x.label]);
    const provinces = [["", "-"], ...c.data.provinces.map((p) => [p, p])];
    const f = buildForm([
      { id: "category", label: t("new_category"), type: "select", options: opt(c.data.categories), group: "form_group_problem", wide: true },
      { id: "statement", label: t("new_statement"), type: "textarea", rows: 6, maxlength: 5000, hint: t("new_statement_hint"), group: "form_group_problem", wide: true },
      { id: "summary", label: t("new_summary"), type: "textarea", rows: 4, maxlength: 3000, hint: t("new_summary_hint"), group: "form_group_problem", wide: true },
      { id: "city", label: t("new_city"), attrs: { maxlength: 80 }, group: "form_group_location" },
      { id: "province", label: t("new_province"), type: "select", options: provinces, group: "form_group_location" },
      { id: "safe_time", label: t("new_safe_time"), hint: t("new_safe_time_hint"), attrs: { maxlength: 40 }, group: "form_group_safe", wide: true },
    ], "new_submit", async (v) => {
      if (!v.city || v.statement.length < 20 || !v.summary) return bad();
      const r = await api("POST", "/api/requests", { category: v.category, city: v.city, province: v.province || null,
        statement: v.statement, summary: v.summary, safe_time: v.safe_time || null, ai_used: aiUsed }, { "Idempotency-Key": key });
      if (r.ok) done(r.data);
      return r.ok ? null : r;
    });
    const summaryField = f.inputs.summary.parentElement;
    const host = summaryField && summaryField.parentElement ? summaryField.parentElement : f.el;
    host.insertBefore(aiCard(f), summaryField || f.inputs.summary);
    return f.el;
  });
  function done(q) {
    root.replaceChildren(h("div", { class: "card success-card" },
      h("span", { class: "eyebrow" }, t("new_done")),
      h("h1", {}, t("new_done")),
      h("div", { class: "success" },
        h("p", {}, t("new_tracking")), h("p", { class: "big" }, q.tracking_no), h("p", {}, t("new_keep_it")), h("p", {}, q.next_action)),
      h("div", { class: "row" }, link(`#/request/${q.id}`, t("new_open"), "btn"),
        h("a", { class: "btn secondary", href: `/api/requests/${q.id}/summary.txt`, download: `${q.tracking_no}.txt` }, t("req_download")))));
  }
  function aiHead() {
    return h("div", { class: "ai-head" }, h("span", { class: "ai-mark", "aria-hidden": "true" }, "AI"), h("h3", {}, t("ai_title")));
  }
  function aiCard(f) {
    const box = h("div", { class: "ai-panel" }), out = h("div");
    const check = async () => {
      const cat = f.inputs.category.value;
      const s = await api("GET", `/api/ai/status?category=${encodeURIComponent(cat)}`);
      if (!s.ok) { box.replaceChildren(aiHead(), alertBox(errorText(s))); return; }
      if (!s.data.available) { box.replaceChildren(aiHead(), noticeBox(s.data.message || t("ai_off"))); return; }
      const consent = h("input", { id: "ai_consent", type: "checkbox" });
      const btn = h("button", { class: "btn secondary small", type: "button" }, t("ai_make"));
      btn.addEventListener("click", () => withLoading(btn, t("loading"), async () => {
        out.replaceChildren();
        const r = await api("POST", "/api/ai/summarize", { category: f.inputs.category.value, statement: f.inputs.statement.value.trim(),
          consent: consent.checked, language: getLang() });
        if (!r.ok) { out.append(alertBox(errorText(r))); return; }
        f.inputs.summary.value = r.data.summary;
        aiUsed = true;
        out.append(noticeBox(r.data.notice));
      }));
      box.replaceChildren(aiHead(), h("p", { class: "hint" }, t("ai_hint")),
        h("div", { class: "check" }, consent, h("label", { for: "ai_consent", class: "inline" }, t("ai_consent"))),
        h("div", { class: "row" }, btn), out);
    };
    f.inputs.category.addEventListener("change", check);
    check();
    return box;
  }
  return root;
}

export function requestDetail(id) {
  const root = h("section");
  const load = () => fill(root, async () => {
    const r = await api("GET", `/api/requests/${id}`);
    if (!r.ok) return alertBox(errorText(r));
    const q = r.data, open = q.status !== "closed";
    const consent = h("input", { id: "consent", type: "checkbox", disabled: !open });
    consent.checked = q.referral_consent;
    consent.addEventListener("change", async () => {
      const x = await api("PUT", `/api/requests/${id}/consent`, { referral: consent.checked });
      if (x.ok) load(); else { consent.checked = !consent.checked; root.prepend(alertBox(errorText(x))); }
    });
    const close = h("button", { class: "btn secondary", type: "button" }, t("req_close"));
    close.addEventListener("click", () => ask("req_close_confirm") && withLoading(close, t("loading"), async () => { await api("POST", `/api/requests/${id}/close`); load(); }));
    return [
      h("div", { class: "card detail-hero" },
        h("span", { class: "eyebrow" }, t("dash_requests")),
        h("h1", {}, q.tracking_no),
        h("p", { class: "meta" }, `${q.category_label} | ${q.city}${q.province ? " | " + q.province : ""}`),
        statusChips(q)),
      h("div", { class: "card detail-card" }, h("h2", {}, t("req_next")), h("p", {}, q.next_action),
        q.assigned_lawyer ? h("p", {}, `${t("req_lawyer")}: ${q.assigned_lawyer.display_name} (${q.assigned_lawyer.city})`) : null,
        q.consultation ? h("p", {}, `${t("req_consult")}: ${when(q.consultation.start)}`) : null),
      q.fallback_contacts && q.fallback_contacts.length ? h("div", { class: "card detail-card" }, h("h2", {}, t("req_contacts")),
        h("div", {}, q.fallback_contacts.map((c) => h("div", { class: "phone-card" },
          h("div", {}, h("div", { class: "meta" }, c.name), h("a", { class: "phone", href: `tel:${c.phone}` }, c.phone),
            h("div", { class: "hint" }, `${t("emergency_verified")}: ${c.verified_on} | `, h("a", { href: c.source_url, rel: "noopener noreferrer", target: "_blank" }, t("emergency_source")))),
          h("a", { class: "btn secondary small", href: `tel:${c.phone}` }, t("emergency_btn")))))) : null,
      h("div", { class: "card detail-card" }, h("h2", {}, t("req_consent_title")),
        h("div", { class: "check" }, consent, h("label", { for: "consent", class: "inline" }, t("req_consent"))),
        h("p", { class: "hint" }, t("req_consent_hint"))),
      h("div", { class: "card detail-card detail-body" }, h("h2", {}, t("req_statement")), h("p", {}, q.statement),
        h("h2", {}, t("req_summary")), h("p", {}, q.summary)),
      h("div", { class: "card detail-card" }, h("h2", {}, t("req_timeline")),
        h("ul", { class: "plain timeline" }, q.timeline.map((e) => h("li", { class: "timeline-item" },
          h("strong", {}, evLabel(e.event)), h("div", { class: "meta" }, when(e.at)))))),
      h("div", { class: "row" }, link(`#/case/${q.tracking_no}`, t("req_room"), "btn"),
        h("a", { class: "btn secondary", href: `/api/requests/${id}/summary.txt`, download: `${q.tracking_no}.txt` }, t("req_download")), open ? close : null)];
  });
  load();
  return root;
}

export function notifications() {
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("nav_notifications")),
      h("h1", {}, t("nav_notifications"))));
  const box = h("div", { class: "card" });
  const load = () => fill(box, async () => apiNode(await api("GET", "/api/notifications"), (d) => {
    if (!d.notifications.length) return empty("notif_empty");
    const all = h("button", { class: "btn secondary small", type: "button" }, t("notif_read_all"));
    all.addEventListener("click", async () => { await api("POST", "/api/notifications/read-all"); load(); });
    return [h("div", { class: "row" }, all), h("ul", { class: "plain" }, d.notifications.map((n) => {
      const b = h("button", { class: "btn secondary small", type: "button" }, t("notif_read"));
      b.addEventListener("click", async () => { await api("POST", `/api/notifications/${n.id}/read`); load(); });
      return h("li", { class: n.read ? "notif-item" : "notif-item unread" },
        h("div", { class: "list-item-head" },
          h("div", {}, h("div", {}, n.body), h("div", { class: "meta" }, when(n.at))),
          n.read ? null : b));
    }))];
  }));
  load();
  root.append(box);
  return root;
}

function geminiKeyCard() {
  const status = h("span", { class: "badge badge-neutral" }, t("byok_loading"));
  const masked = h("p", { class: "byok-masked", hidden: true });
  const input = h("input", {
    id: "byok_key", name: "byok_key", type: "password", placeholder: "AIzaSy...",
    autocomplete: "off", spellcheck: "false", maxlength: 200,
  });
  const msg = h("div", { role: "status", "aria-live": "polite" });
  const save = h("button", { class: "btn", type: "submit" }, t("byok_save"));
  const clear = h("button", { class: "btn ghost", type: "button", hidden: true }, t("byok_clear"));
  const form = h("form", { novalidate: true },
    h("div", { class: "field" },
      h("label", { for: "byok_key" }, t("byok_label")), input,
      h("p", { class: "hint" }, t("byok_hint"))),
    msg,
    h("div", { class: "row" }, save, clear));

  const apply = (d) => {
    status.textContent = d.configured ? t("byok_status_active") : t("byok_status_none");
    status.className = "badge " + (d.configured ? "badge-ok" : "badge-neutral");
    masked.hidden = !d.configured;
    masked.textContent = d.configured ? `${t("byok_saved_as")}: ${d.masked}` : "";
    clear.hidden = !d.configured;
    input.value = "";
    document.dispatchEvent(new CustomEvent("byok:changed", { detail: d }));
  };
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.replaceChildren();
    const key = input.value.trim();
    if (!key) {
      msg.append(alertBox(t("byok_enter")));
      input.focus();
      return;
    }
    const r = await withLoading(save, t("loading"), () => api("PUT", "/api/me/gemini-key", { api_key: key }));
    if (r.ok) {
      apply(r.data);
      msg.append(h("div", { class: "success" }, t("byok_saved")));
    } else msg.append(alertBox(errorText(r)));
  });
  clear.addEventListener("click", async () => {
    if (!ask("byok_clear_confirm")) return;
    msg.replaceChildren();
    const r = await withLoading(clear, t("loading"), () => api("PUT", "/api/me/gemini-key", { api_key: "" }));
    if (r.ok) {
      apply(r.data);
      msg.append(h("div", { class: "success" }, t("byok_removed")));
    } else msg.append(alertBox(errorText(r)));
  });

  api("GET", "/api/me/gemini-key").then((r) => {
    if (r.ok) apply(r.data);
    else status.textContent = t("err_generic");
  });

  return h("div", { class: "card byok-card" },
    h("div", { class: "card-head" }, h("h2", {}, t("byok_title")), status),
    h("p", { class: "hint" }, t("byok_lead")),
    form,
    masked,
    h("p", { class: "hint byok-note" }, t("byok_note")));
}

export function settings() {
  const root = h("section", {},
    h("div", { class: "page-head" },
      h("span", { class: "eyebrow" }, t("set_title")),
      h("h1", {}, t("set_title"))));  const fu = h("div", { class: "card" });
  fill(fu, async () => apiNode(await api("GET", "/api/me/followup"), (d) => {
    const f = buildForm([
      { id: "pref", label: t("set_pref"), type: "select", value: d.pref, options: [["daily", t("pref_daily")], ["weekly", t("pref_weekly")], ["important_only", t("pref_important")], ["off", t("pref_off")]] },
      { id: "safe_time", label: t("set_time"), type: "time", value: d.safe_time },
      { id: "timezone", label: t("set_tz"), value: d.timezone },
    ], "set_save", (v) => api("PUT", "/api/me/followup", { pref: v.pref, safe_time: v.safe_time, timezone: v.timezone }));
    return [h("h2", {}, t("set_followup")), h("p", { class: "hint" }, d.note), f.el];
  }));
  const pw = buildForm([
    { id: "old_password", label: t("set_old_pw"), type: "password", attrs: { autocomplete: "current-password" } },
    { id: "new_password", label: t("set_new_pw"), type: "password", hint: t("password_hint"), attrs: { autocomplete: "new-password" } },
  ], "set_pw_btn", (v) => api("POST", "/api/auth/change-password", v), { reset: true });
  const del = buildForm([{ id: "password", label: t("field_password"), type: "password" }], "set_delete_btn", async (v) => {
    if (!v.password || !ask("set_delete_confirm")) return null;
    const r = await api("DELETE", "/api/me", { password: v.password });
    if (r.ok) { state.user = null; go("#/"); }
    return r.ok ? null : r;
  });
  del.el.querySelector("button[type=submit]").classList.add("danger");
  root.append(fu, geminiKeyCard(),
    h("div", { class: "card" }, h("h2", {}, t("set_password")), pw.el),
    h("div", { class: "card" }, h("h2", {}, t("set_data")), h("p", { class: "hint" }, t("set_export_hint")),
      h("div", { class: "row" }, h("a", { class: "btn secondary", href: "/api/me/export", download: "insaf-dastak-data.json" }, t("set_export")))),
    h("div", { class: "card danger-zone" }, h("h2", {}, t("set_danger")), h("p", { class: "hint" }, t("set_delete_hint")), del.el));
  return root;
}
