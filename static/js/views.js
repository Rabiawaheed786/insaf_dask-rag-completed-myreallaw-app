import { api, errorText } from "./api.js";
import { noticeBox } from "./common.js";
import { field, h, withLoading } from "./dom.js";
import { getLang, setLang, t } from "./i18n.js";
import { state } from "./state.js";

const go = (hash) => { location.hash = hash; };

function alertBox(text) { return h("div", { class: "alert", role: "alert" }, text); }

const NS = "http://www.w3.org/2000/svg";
function svgIcon(paths, size = 20) {
  const svg = document.createElementNS(NS, "svg");
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
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

const STEP_ICONS = {
  account: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M19 8v6", "M22 11h-6"],
  ask: ["M21 11.5a8.4 8.4 0 0 1-9 8.5 9.6 9.6 0 0 1-3-.5L4 21l1.4-4.1A8.5 8.5 0 1 1 21 11.5Z", "M8 10h8", "M8 14h5"],
  connect: ["M9 12l2 2 4-4", "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"],
  help: ["M12 9v4", "M12 17h.01", "M10.3 3.6 2.4 17a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z"],
};

const PILL_ICONS = {
  advice: ["M12 3l8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6Z", "M9 12l2 2 4-4"],
  laws: ["M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5Z", "M4 18.5A2.5 2.5 0 0 1 6.5 16H20"],
  bilingual: ["M4 5h9", "M8.5 3v2", "M6 5c0 4 2.5 6.5 6 8", "M11 5c0 4-2.5 6.5-6 8", "M14 19l4-10 4 10", "M15.5 15h5"],
};

function previewPill(label, iconKey) {
  return h("span", { class: "preview-pill" }, svgIcon(PILL_ICONS[iconKey], 14), label);
}

function previewCard() {
  return h("aside", { class: "home-preview", "aria-label": t("home_preview_aria") },
    h("div", { class: "home-preview-badges" },
      h("span", { class: "preview-badge is-emerald" }, t("home_preview_badge1")),
      h("span", { class: "preview-badge is-gold" }, t("home_preview_badge2"))),
    h("div", { class: "home-preview-stats" },
      previewPill(t("home_pill_advice"), "advice"),
      previewPill(t("home_pill_laws"), "laws"),
      previewPill(t("home_pill_bilingual"), "bilingual")),
    h("div", { class: "home-preview-qa" },
      h("span", { class: "preview-kicker" }, t("home_preview_q_label")),
      h("p", { class: "preview-q" }, t("home_preview_q")),
      h("div", { class: "preview-answer" },
        h("div", { class: "preview-answer-head" },
          h("span", { class: "preview-check", "aria-hidden": "true" }, "\u2713"),
          h("span", {}, t("home_preview_answer_label"))),
        h("p", {}, t("home_preview_answer")),
        h("span", { class: "preview-cite" }, t("home_preview_cite")))),
    h("p", { class: "preview-note" }, t("home_preview_note")));
}

function featureCard(titleKey, bodyKey, iconKey, footer, tone = "") {
  return h("article", { class: "home-feature-card" + tone },
    h("span", { class: "home-feature-icon", "aria-hidden": "true" }, svgIcon(STEP_ICONS[iconKey])),
    h("h3", {}, t(titleKey)),
    h("p", { class: "home-feature-body" }, t(bodyKey)),
    h("div", { class: "home-feature-foot" }, footer));
}

function compareCard(titleKey, itemKeys, tone) {
  return h("article", { class: `card home-compare-card ${tone}` },
    h("h2", {}, t(titleKey)),
    h("ul", { class: "plain" }, itemKeys.map((k) => h("li", {}, t(k)))));
}

export function home() {
  return h("section", { class: "home home-exec" },
    h("div", { class: "home-hero-grid" },
      h("div", { class: "hero-panel home-hero-left" },
        h("img", { class: "hero-watermark", src: "/static/img/emblem.svg", alt: "", "aria-hidden": "true" }),
        h("div", { class: "hero-badge" }, h("span", { class: "badge badge-ok" }, t("home_badge"))),
        h("h1", {}, t("home_title")),
        h("p", { class: "lead" }, t("home_lead")),
        h("div", { class: "hero-actions" },
          h("a", { class: "btn", href: "#/signup" }, t("btn_signup")),
          h("a", { class: "btn secondary", href: "#/login" }, t("btn_login"))),
        h("ul", { class: "trust-list" },
          h("li", {}, t("home_trust1")), h("li", {}, t("home_trust2")), h("li", {}, t("home_trust3")))),
      previewCard()),
    h("div", { class: "home-features" },
      h("div", { class: "home-features-head" },
        h("span", { class: "eyebrow" }, t("home_eyebrow")),
        h("h2", {}, t("home_cards_title"))),
      h("div", { class: "home-feature-grid" },
        featureCard("home_ai_title", "home_ai_body", "ask",
          h("a", { class: "btn", href: "#/legal" }, t("home_ai_cta"))),
        featureCard("home_intake_title", "home_intake_body", "account",
          h("a", { class: "btn", href: "#/new" }, t("home_intake_cta"))),
        featureCard("home_help_title", "home_help_body", "help",
          h("div", { class: "home-helpline-actions" },
            h("a", { class: "btn secondary small", href: "tel:1799" }, t("home_help_nccia")),
            h("a", { class: "btn secondary small", href: "tel:15" }, t("home_help_police")),
            h("a", { class: "btn small", href: "#/scam" }, t("scam_open_full"))),
          " is-help"))),
    h("div", { class: "home-compare" },
      compareCard("home_what", ["home_what1", "home_what2", "home_what3"], "what-card"),
      compareCard("home_not", ["home_not1", "home_not2"], "not-card")),
    h("div", { class: "home-urgent", role: "note" },
      h("span", { class: "home-urgent-mark", "aria-hidden": "true" }, "!"),
      h("div", { class: "home-urgent-body" },
        h("strong", {}, t("home_danger")),
        h("p", {}, t("home_danger_text"))),
      h("a", { class: "btn danger", href: "#/emergency" }, t("home_emergency_btn"))));
}

function authForm(kind) {
  const signup = kind === "signup";
  const notice = !signup && state.notice ? noticeBox(state.notice) : null;
  if (notice) state.notice = null;
  const box = h("div");
  const btn = h("button", { class: "btn", type: "submit" }, t(signup ? "btn_signup" : "btn_login"));
  const form = h("form", { novalidate: true },
    ...(signup ? field("display_name", t("field_display"), "text", { required: false, autocomplete: "nickname", maxlength: 80 }) : []),
    ...field("email", t("field_email"), "email", { autocomplete: "email" }),
    ...field("password", t("field_password"), "password", { autocomplete: signup ? "new-password" : "current-password", minlength: signup ? 8 : false }),
    signup ? h("p", { class: "hint" }, t("password_hint")) : null,
    box,
    h("div", { class: "row" }, btn));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    box.replaceChildren();
    const $ = (id) => form.querySelector("#" + id);
    const email = $("email").value.trim(), password = $("password").value;
    if (!email || !password) { box.append(alertBox(t("err_form"))); return; }
    const body = signup ? { email, password, display_name: $("display_name").value.trim(), language: getLang() } : { email, password };
    const r = await withLoading(btn, t("loading"), () => api("POST", signup ? "/api/auth/signup" : "/api/auth/login", body));
    if (!r.ok) { box.append(alertBox(errorText(r))); return; }
    $("password").value = "";
    if (signup) {
      // Signup ke baad seedha andar nahi: session band karke login screen par bhejo.
      await api("POST", "/api/auth/logout");
      state.user = null;
      state.notice = t("signup_login_notice");
      go("#/login");
      return;
    }
    state.user = r.data;
    if (r.data.language && r.data.language !== getLang()) setLang(r.data.language);
    const next = state.next || "#/dashboard";
    state.next = null;
    go(next);
  });
  return h("section", { class: "auth-wrap" },
    h("a", { class: "back-link auth-back", href: "#/" }, t("back_home")),
    h("div", { class: "card auth-card" },
      h("span", { class: "eyebrow" }, t(signup ? "signup_title" : "login_title")),
      h("h1", {}, t(signup ? "signup_title" : "login_title")),
      h("p", { class: "lead" }, t(signup ? "signup_lead" : "login_lead")),
      notice,
      form),
    h("p", { class: "auth-alt" }, h("a", { href: signup ? "#/login" : "#/signup" }, t(signup ? "to_login" : "to_signup"))));
}
export const login = () => authForm("login");
export const signup = () => authForm("signup");

const EMERGENCY_CONTACTS = [
  { key: "police", phone: "15", tone: "red", icon: PILL_ICONS.advice, source: "https://lahorepolice.punjab.gov.pk/emergency-help-directory" },
  { key: "rescue", phone: "1122", tone: "red", icon: ["M9 3h6v6h6v6h-6v6H9v-6H3V9h6Z"], source: "https://sialkot.punjab.gov.pk/Punjab_Emergency_Service" },
  { key: "rights", phone: "1099", tone: "green", icon: STEP_ICONS.connect, source: "https://www.mohr.gov.pk/Detail/YWRiYjU0NzktMGE2Zi00NDYyLTljNzktMTA2N2M2MjBlZWZl" },
  { key: "cyber", phone: "1799", tone: "green", icon: ["M4 3h16v14H4Z", "M8 21h8", "M12 17v4", "M9 10l2 2 4-4"], source: "https://www.nccia.gov.pk/" },
  { key: "child", phone: "1121", tone: "gold", icon: STEP_ICONS.account, source: "https://cpwb.punjab.gov.pk/contact_us" },
  { key: "legal", phone: "0800-70806", tone: "gold", icon: PILL_ICONS.laws, source: "https://www.las.org.pk/" },
];

function emergencyCard(contact) {
  const title = t(`emergency_${contact.key}_title`);
  return h("article", { class: `emergency-contact is-${contact.tone}` },
    h("div", { class: "emergency-contact-head" },
      h("span", { class: "emergency-contact-icon" }, svgIcon(contact.icon, 23)),
      h("span", { class: "emergency-coverage" }, t(`emergency_${contact.key}_coverage`))),
    h("h3", {}, title),
    h("p", { class: "emergency-contact-description" }, t(`emergency_${contact.key}_body`)),
    h("div", { class: "emergency-contact-foot" },
      contact.source ? h("a", { class: "emergency-source", href: contact.source, target: "_blank", rel: "noopener noreferrer" }, t("emergency_source")) : null,
      h("a", { class: "emergency-call", href: `tel:${contact.phone.replace(/-/g, "")}`, "aria-label": `${t("emergency_call")} ${title} — ${contact.phone}` },
        h("span", { class: "emergency-number" }, contact.phone),
        h("span", { class: "emergency-call-label" }, t("emergency_call"), h("span", { "aria-hidden": "true" }, " →")))));
}

export function emergency() {
  const additional = h("div", { class: "emergency-additional" });
  const exit = h("button", { class: "btn danger emergency-quick-exit", type: "button" }, t("emergency_exit"));
  exit.addEventListener("click", () => document.getElementById("btn-quickexit").click());
  const view = h("section", { class: "emergency-page", "aria-labelledby": "emergency-title" },
    h("a", { class: "back-link emergency-back", href: "#/" }, t("emergency_back")),
    h("div", { class: "emergency-heading" },
      h("span", { class: "eyebrow" }, t("emergency_eyebrow")),
      h("h1", { id: "emergency-title" }, t("emergency_title")),
      h("p", { class: "lead" }, t("emergency_intro"))),
    h("aside", { class: "emergency-safety", "aria-labelledby": "emergency-safety-title" },
      h("span", { class: "emergency-safety-icon" }, svgIcon(STEP_ICONS.help, 26)),
      h("div", { class: "emergency-safety-body" },
        h("h2", { id: "emergency-safety-title" }, t("emergency_safety_title")),
        h("p", {}, t("emergency_lead"))),
      exit),
    h("section", { class: "emergency-directory", "aria-labelledby": "emergency-directory-title" },
      h("div", { class: "emergency-directory-head" },
        h("h2", { id: "emergency-directory-title" }, t("emergency_directory_title")),
        h("p", {}, t("emergency_note"))),
      h("div", { class: "emergency-grid" }, EMERGENCY_CONTACTS.map(emergencyCard))),
    additional,
    h("div", { class: "emergency-footer" },
      h("aside", { class: "notice emergency-privacy", "aria-labelledby": "emergency-privacy-title" },
        h("h2", { id: "emergency-privacy-title" }, t("emergency_privacy_title")),
        h("p", {}, t("quickexit_hint"))),
      h("a", { class: "btn secondary emergency-return", href: "#/" }, h("span", { "aria-hidden": "true" }, "←"), t("emergency_back"))));
  api("GET", "/api/emergency").then((r) => {
    if (!r.ok) { additional.append(h("p", { class: "hint", role: "status" }, t("emergency_additional_unavailable"))); return; }
    const contacts = r.data.contacts.filter((c) => !EMERGENCY_CONTACTS.some((item) => item.phone.replace(/\D/g, "") === c.phone.replace(/\D/g, "")));
    if (!contacts.length) return;
    const list = contacts.map((c) => h("div", { class: "phone-card" },
      h("div", {},
        h("div", { class: "meta" }, c.name),
        h("a", { class: "phone", href: `tel:${c.phone}` }, c.phone),
        c.note ? h("div", { class: "hint" }, c.note) : null,
        h("div", { class: "hint" }, `${t("emergency_verified")}: ${c.verified_on} | `, h("a", { href: c.source_url, rel: "noopener noreferrer", target: "_blank" }, t("emergency_source")))),
      h("a", { class: "btn secondary small", href: `tel:${c.phone}` }, t("emergency_call"))));
    additional.append(h("h2", {}, t("emergency_additional_title")), ...list);
  });
  return view;
}

export function notFound() {
  return h("section", { class: "card notfound" }, h("h1", {}, t("notfound")), h("a", { class: "btn", href: "#/" }, t("back_home")));
}
