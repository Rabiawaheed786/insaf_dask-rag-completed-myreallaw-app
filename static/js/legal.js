import { api, errorText } from "./api.js";
import { alertBox, fill } from "./common.js";
import { h } from "./dom.js";
import { getLang, t } from "./i18n.js";
import { state } from "./state.js";

// Guftagu sirf is browser session ki yaad-dasht mein rehti hai. Server sirf ginti rakhta hai,
// sawal ka matn mehfooz nahi karta; is liye koi browser storage bhi istemal nahi hoti.
let chats = [];
let activeId = null;
let ownerId = null;
let seq = 0;
let busy = false;

let historyEl = null;
let streamEl = null;
let inputEl = null;
let consentEl = null;
let sendBtnEl = null;

const SUGGESTS = ["ai_suggest_1", "ai_suggest_2", "ai_suggest_3"];

function resetIfOwnerChanged() {
  const id = state.user ? state.user.id : null;
  if (id !== ownerId) { chats = []; activeId = null; ownerId = id; busy = false; }
}

function activeChat() {
  return chats.find((c) => c.id === activeId) || null;
}

export function legalHelp() {
  resetIfOwnerChanged();

  const historyBox = h("div", { class: "ai-history" });
  const libraryBox = h("div", { class: "ai-library" });
  const stream = h("div", { class: "ai-stream", role: "log", "aria-label": t("ai_assistant") });
  const composerErr = h("div", { class: "ai-composer-err", role: "alert" });
  const input = h("textarea", {
    id: "legal_question", name: "legal_question", rows: 2, maxlength: 1000,
    placeholder: t("ai_placeholder"), "aria-label": t("legal_question"),
  });
  const consent = h("input", { id: "legal_consent", type: "checkbox" });
  const sendBtn = h("button", { class: "btn ai-send", type: "submit", "aria-label": t("ai_send"), title: t("ai_send") },
    h("span", { class: "ai-send-arrow", "aria-hidden": "true" }, "\u2191"));

  historyEl = historyBox;
  streamEl = stream;
  inputEl = input;
  consentEl = consent;
  sendBtnEl = sendBtn;
  sendBtn.disabled = busy;

  const menuBtn = h("button", {
    class: "ai-menu", type: "button", "aria-label": t("ai_menu"),
    "aria-expanded": "false", "aria-controls": "ai-sidebar",
  }, h("span", { class: "ai-menu-bars", "aria-hidden": "true" }, h("span"), h("span"), h("span")));

  const backLink = h("a", { class: "ai-back", href: "#/dashboard", "aria-label": t("ai_back"), title: t("ai_back") },
    h("span", { class: "ai-back-arrow", "aria-hidden": "true" }, "\u2190"),
    h("span", { class: "ai-back-text" }, t("nav_home")));

  const closeBtn = h("button", { class: "ai-side-close", type: "button", "aria-label": t("ai_close") }, "\u00d7");
  const newChatBtn = h("button", { class: "ai-new", type: "button" },
    h("span", { class: "ai-new-plus", "aria-hidden": "true" }, "+"),
    h("span", {}, t("ai_new_chat")));

  const aside = h("aside", { class: "ai-sidebar", id: "ai-sidebar", "aria-label": t("ai_workspace") },
    h("div", { class: "ai-side-head" },
      h("span", { class: "ai-mark", "aria-hidden": "true" }, "AI"),
      h("span", { class: "ai-side-brand" },
        h("strong", {}, "INSAF DASTAK"),
        h("span", {}, t("ai_workspace"))),
      closeBtn),
    newChatBtn,
    h("div", { class: "ai-side-scroll" },
      h("section", { class: "ai-side-section" },
        h("div", { class: "ai-side-label" },
          h("span", {}, t("ai_history")),
          h("span", { class: "badge badge-neutral" }, t("ai_session"))),
        historyBox),
      h("section", { class: "ai-side-section" },
        h("div", { class: "ai-side-label" }, h("span", {}, t("ai_library"))),
        libraryBox),
      h("nav", { class: "ai-side-section", "aria-label": t("ai_nav") },
        h("div", { class: "ai-side-label" }, h("span", {}, t("ai_nav"))),
        h("div", { class: "ai-side-nav" },
          navLink("#/dashboard", "nav_home"),
          navLink("#/new", "nav_new"),
          navLink("#/notifications", "nav_notifications"),
          navLink("#/settings", "nav_settings"),
          navLink("#/lawyer", "nav_lawyer"),
          navLink("#/scam", "ai_scam_link"),
          ["coordinator", "admin"].includes(state.user && state.user.role) ? navLink("#/coord", "nav_coord") : null,
          state.user && state.user.role === "admin" ? navLink("#/admin", "nav_admin") : null))),
    h("div", { class: "ai-side-foot" },
      h("p", {}, t("ai_history_hint")),
      logoutBtn()));

  const scrim = h("div", { class: "ai-scrim", "aria-hidden": "true" });

  function openDrawer() {
    aside.classList.add("open");
    scrim.classList.add("show");
    menuBtn.setAttribute("aria-expanded", "true");
    newChatBtn.focus();
  }
  function closeDrawer() {
    aside.classList.remove("open");
    scrim.classList.remove("show");
    menuBtn.setAttribute("aria-expanded", "false");
    if (menuBtn.offsetParent) menuBtn.focus();
  }

  menuBtn.addEventListener("click", openDrawer);
  closeBtn.addEventListener("click", closeDrawer);
  scrim.addEventListener("click", closeDrawer);
  aside.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  newChatBtn.addEventListener("click", () => {
    activeId = null;
    renderHistory();
    renderStream();
    closeDrawer();
    input.focus();
  });

  const form = h("form", { class: "ai-composer", novalidate: true },
    composerErr,
    h("div", { class: "ai-prompt" }, input, sendBtn),
    h("div", { class: "ai-consent" },
      h("label", { class: "ai-consent-label", for: "legal_consent" },
        consent, h("span", {}, t("legal_consent"))),
      h("p", { class: "ai-consent-hint" }, t("ai_privacy"))));

  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value, composerErr); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value, composerErr); }
  });

  const shell = h("section", { class: "ai-shell", id: "legal-assistant" },
    h("h1", { class: "ai-sr" }, t("legal_title")),
    aside,
    scrim,
    h("div", { class: "ai-main" },
      h("header", { class: "ai-topbar" },
        backLink,
        menuBtn,
        h("div", { class: "ai-title" },
          h("span", { class: "ai-title-mark", "aria-hidden": "true" }, "AI"),
          h("span", { class: "ai-title-text" },
            h("strong", {}, t("legal_title")),
            h("span", {}, t("ai_workspace")))),
        h("div", { class: "ai-top-actions" },
          h("span", { class: "badge badge-ok" }, t("legal_verified_badge")),
          h("a", { class: "btn secondary small", href: "#/scam" }, t("ai_scam_link")))),
      stream,
      h("div", { class: "ai-composer-wrap" }, form)));

  fill(libraryBox, async () => {
    const r = await api("GET", "/api/legal/sources");
    if (!r.ok) return alertBox(errorText(r));
    if (!r.data.sources.length) return h("p", { class: "ai-side-empty" }, t("legal_sources_empty"));
    return r.data.sources.map((s) => h("a", {
      class: "ai-lib-item", href: s.source_url, target: "_blank", rel: "noopener noreferrer", title: s.title,
    },
      h("span", { class: "ai-lib-title" }, s.title),
      h("span", { class: "ai-lib-meta" }, `${s.jurisdiction} \u00b7 ${s.verified_on}`)));
  });

  renderHistory();
  renderStream();
  return shell;
}

function navLink(href, key) {
  return h("a", { href }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", {}, t(key)));
}

function logoutBtn() {
  const btn = h("button", { class: "ai-logout", type: "button" }, t("btn_logout"));
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    await api("POST", "/api/auth/logout");
    state.user = null;
    chats = [];
    activeId = null;
    ownerId = null;
    busy = false;
    document.body.classList.remove("ai-mode");
    location.hash = "#/";
  });
  return btn;
}

async function send(text, composerErr) {
  if (busy) return;
  const q = String(text || "").trim();
  composerErr.replaceChildren();
  if (q.length < 5) {
    composerErr.append(alertBox(t("legal_question_short")));
    if (inputEl) inputEl.focus();
    return;
  }

  let chat = activeChat();
  if (!chat) {
    chat = { id: ++seq, title: q.slice(0, 52), messages: [] };
    chats.unshift(chat);
    activeId = chat.id;
  }
  chat.messages.push({ role: "user", text: q });
  chat.messages.push({ role: "assistant", pending: true });
  if (inputEl) inputEl.value = "";
  busy = true;
  sendBtnEl.disabled = true;
  renderHistory();
  renderStream();
  scrollBottom();

  const r = await api("POST", "/api/legal/ask", {
    question: q, consent: !!(consentEl && consentEl.checked), language: getLang(),
  });
  const pending = chat.messages[chat.messages.length - 1];
  pending.pending = false;
  if (r.ok) pending.data = r.data; else pending.error = errorText(r);
  busy = false;
  sendBtnEl.disabled = false;
  renderHistory();
  renderStream();
  if (activeId === chat.id) {
    scrollBottom();
    if (inputEl) inputEl.focus();
  }
}

function renderHistory() {
  if (!historyEl) return;
  if (!chats.length) {
    historyEl.replaceChildren(h("p", { class: "ai-side-empty" }, t("ai_history_empty")));
    return;
  }
  historyEl.replaceChildren(...chats.map((c) => {
    const btn = h("button", {
      class: "ai-history-item", type: "button",
      "aria-current": c.id === activeId ? "true" : null,
      title: c.title,
    }, h("span", { class: "ai-history-title" }, c.title));
    btn.addEventListener("click", () => {
      activeId = c.id;
      renderHistory();
      renderStream();
      const side = document.getElementById("ai-sidebar");
      if (side) side.classList.remove("open");
      const scrim = document.querySelector(".ai-scrim");
      if (scrim) scrim.classList.remove("show");
      const menu = document.querySelector(".ai-menu");
      if (menu) menu.setAttribute("aria-expanded", "false");
      if (inputEl) inputEl.focus();
    });
    return btn;
  }));
}

function renderStream() {
  if (!streamEl) return;
  const chat = activeChat();
  const inner = h("div", { class: "ai-stream-inner" });
  if (!chat || !chat.messages.length) inner.append(emptyState());
  else chat.messages.forEach((m) => inner.append(messageNode(m)));
  streamEl.replaceChildren(inner);
}

function emptyState() {
  return h("div", { class: "ai-empty" },
    h("span", { class: "ai-mark", "aria-hidden": "true" }, "AI"),
    h("h2", {}, t("ai_empty_title")),
    h("p", {}, t("ai_empty_body")),
    h("div", { class: "ai-suggests" }, SUGGESTS.map((key) => {
      const btn = h("button", { class: "ai-suggest", type: "button" }, t(key));
      btn.addEventListener("click", () => {
        if (!inputEl) return;
        inputEl.value = t(key);
        inputEl.focus();
      });
      return btn;
    })));
}

function messageNode(m) {
  if (m.role === "user") {
    return h("div", { class: "ai-msg user", role: "group", "aria-label": t("ai_you") },
      h("div", { class: "ai-bubble" }, m.text));
  }
  const body = m.pending ? typingStatus() : m.error ? alertBox(m.error) : answerBlock(m.data);
  return h("div", { class: "ai-msg bot", role: "group", "aria-label": t("ai_assistant") },
    h("span", { class: "ai-avatar", "aria-hidden": "true" }, "AI"),
    h("div", { class: "ai-content" }, body));
}

function typingStatus() {
  return h("div", { class: "ai-status", role: "status" },
    h("span", { class: "typing-dots", "aria-hidden": "true" }, h("span"), h("span"), h("span")),
    t("legal_typing"));
}

function answerBlock(d) {
  if (!d) return h("p", { class: "hint" }, t("err_generic"));
  if (!d.found) {
    return h("div", {},
      h("div", { class: "notice" },
        h("strong", {}, t("legal_no_match")),
        h("p", {}, d.answer)),
      h("p", { class: "ai-disclaimer" }, d.disclaimer));
  }
  const parts = [
    h("div", { class: "ai-answer-head" },
      h("strong", {}, t("legal_answer")),
      h("span", { class: "badge badge-ok" }, t(d.llm_used ? "legal_ai_note" : "legal_passages_note"))),
    h("p", { class: "ai-answer-text" }, d.answer),
  ];
  if (d.sources && d.sources.length) parts.push(citations(d.sources));
  parts.push(h("p", { class: "ai-disclaimer" }, d.disclaimer));
  return h("div", { class: "ai-answer" }, parts);
}

function citations(sources) {
  return h("div", { class: "ai-citations" },
    h("div", { class: "ai-cite-label" },
      h("span", {}, t("legal_citations")),
      h("span", { class: "badge badge-ok" }, t("legal_verified_badge"))),
    h("div", { class: "ai-cite-list" }, sources.map(citeCard)));
}

function citeCard(s) {
  return h("article", { class: "ai-cite" },
    h("span", { class: "citation" }, `[${s.n}]`),
    h("div", { class: "ai-cite-body" },
      h("div", { class: "ai-cite-head" },
        h("span", { class: "ai-cite-title" }, s.title),
        h("span", { class: "badge badge-neutral" }, `${t("legal_page")} ${s.page}`)),
      h("p", { class: "ai-cite-snippet" }, s.snippet),
      h("div", { class: "ai-cite-meta" },
        h("span", {}, `${t("legal_jurisdiction")}: ${s.jurisdiction}`),
        h("span", {}, `${t("emergency_verified")}: ${s.verified_on}`),
        h("a", { href: s.source_url, target: "_blank", rel: "noopener noreferrer" }, t("emergency_source")))));
}

function scrollBottom() {
  requestAnimationFrame(() => { if (streamEl) streamEl.scrollTop = streamEl.scrollHeight; });
}
