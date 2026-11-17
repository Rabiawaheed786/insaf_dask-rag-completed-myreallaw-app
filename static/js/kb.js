import { api, apiUpload, errorText } from "./api.js";
import { alertBox, ask, fill, link } from "./common.js";
import { h, withLoading } from "./dom.js";
import { getLang, t } from "./i18n.js";
import { state } from "./state.js";

// Knowledge Base screens. Guftagu sirf is session ki yaad-dasht mein rehti hai; browser storage nahi.
const go = (hash) => { location.hash = hash; };

function card(className) { return h("div", { class: className }); }

// ---------------- Screen 1: user detail + knowledge base list ----------------
export function kbDashboard() {
  return [profileCard(), kbCard()];
}

export function profileCard() {
  const u = state.user;
  const name = h("input", { id: "prof_name", name: "prof_name", type: "text", maxlength: 80, autocomplete: "name" });
  const email = h("input", { id: "prof_email", name: "prof_email", type: "email", maxlength: 160, autocomplete: "email" });
  name.value = u.display_name || "";
  email.value = u.email || "";
  const msg = h("div", { role: "status", "aria-live": "polite" });
  const btn = h("button", { class: "btn", type: "submit" }, t("prof_update"));
  const form = h("form", { novalidate: true },
    h("div", { class: "kb-profile-grid" },
      h("div", { class: "field" }, h("label", { for: "prof_name" }, t("prof_display")), name),
      h("div", { class: "field" }, h("label", { for: "prof_email" }, t("prof_email")), email)),
    msg,
    h("div", { class: "row" }, btn));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.replaceChildren();
    const r = await withLoading(btn, t("loading"), () => api("PUT", "/api/auth/me", {
      display_name: name.value.trim(), email: email.value.trim(),
    }));
    if (r.ok) {
      state.user = r.data;
      name.value = r.data.display_name || "";
      email.value = r.data.email || "";
      msg.append(h("div", { class: "success" }, t("prof_saved")));
    } else msg.append(alertBox(errorText(r)));
  });
  return h("div", { class: "card kb-profile" },
    h("div", { class: "card-head" }, h("h2", {}, t("prof_title")), h("span", { class: "badge badge-neutral" }, t("role_" + u.role))),
    form);
}

export function kbCard(onData) {
  let currentList = [];
  let requestRevision = 0;
  const listBox = h("div", { class: "kb-list" });
  const listMsg = h("div", { role: "status", "aria-live": "polite" });
  const titleIn = h("input", { id: "kb_new_title", name: "kb_new_title", type: "text", maxlength: 80, placeholder: t("kb_create_ph") });
  const createBtn = h("button", { class: "kb-create-submit", type: "submit", title: t("kb_create_btn"), "aria-label": t("kb_create_btn") }, plusIcon(18));
  const createMsg = h("div", { role: "status", "aria-live": "polite" });
  const createForm = h("form", { class: "kb-create-card", novalidate: true },
    h("div", { class: "kb-create-label" }, t("dash_create_kb")),
    h("div", { class: "kb-create-row" }, titleIn, createBtn),
    createMsg);

  createForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (createBtn.disabled) return;
    createMsg.replaceChildren();
    const title = titleIn.value.trim();
    if (!title) { createMsg.append(alertBox(t("kb_name"))); return; }
    createBtn.disabled = true;
    createBtn.setAttribute("aria-busy", "true");
    let r;
    try { r = await api("POST", "/collections", { collection_name: title, system_prompt: "" }); }
    finally { createBtn.disabled = false; createBtn.removeAttribute("aria-busy"); }
    if (!r || !r.ok) { createMsg.append(alertBox(r ? errorText(r) : t("err_network"))); return; }
    // A pending list request must not overwrite this confirmed creation.
    requestRevision++;
    currentList = [...currentList.filter((kb) => kb.id !== r.data.id), r.data];
    titleIn.value = "";
    listMsg.replaceChildren();
    render();
    createMsg.append(h("div", { class: "success" }, t("kb_created")));
    load();
  });

  const deleted = (kb, r) => {
    listMsg.replaceChildren();
    if (!r.ok) { listMsg.append(alertBox(`${t("kb_delete_failed")} ${errorText(r)}`)); return; }
    requestRevision++;
    currentList = currentList.filter((item) => item.id !== kb.id);
    render();
    listMsg.append(h("div", { class: "success" }, t("kb_deleted")));
  };

  const render = () => {
    listBox.replaceChildren(currentList.length
      ? h("div", { class: "kb-items" }, currentList.map((kb) => kbItem(kb, load, deleted)))
      : h("p", { class: "empty" }, t("kb_empty")));
    if (onData) onData(currentList);
  };

  const load = async () => {
    const revision = ++requestRevision;
    listMsg.replaceChildren();
    if (!currentList.length) listBox.replaceChildren(h("p", { class: "empty" }, t("loading")));
    const r = await api("GET", "/collections");
    if (revision !== requestRevision) return;
    if (!r.ok) {
      render();
      listMsg.append(alertBox(errorText(r)));
      return;
    }
    currentList = r.data.collections;
    render();
  };

  load();
  return h("div", { class: "card kb-hub" },
    h("div", { class: "card-head" }, h("h2", {}, t("dash_kb_manager_title"))),
    listMsg,
    h("div", { class: "kb-manager" }, listBox, createForm));
}

function plusIcon(size) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const d of ["M12 5v14", "M5 12h14"]) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function miniIcon(paths, size = 14) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.9");
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

const ACT_ICONS = {
  chat: ["M21 11.5a8.4 8.4 0 0 1-9 8.5 9.6 9.6 0 0 1-3-.5L4 21l1.4-4.1A8.5 8.5 0 1 1 21 11.5Z"],
  upload: ["M12 15V4", "M8 8l4-4 4 4", "M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"],
  code: ["M8 8l-4 4 4 4", "M16 8l4 4-4 4", "M13.5 5l-3 14"],
};

function kbItem(kb, refresh, onDelete) {
  const openBtn = h("button", { class: "kb-item-title", type: "button", title: t("kb_open") }, kb.title);
  openBtn.addEventListener("click", () => openKbModal(kb, refresh));
  const chatLink = h("a", { class: "btn secondary small kb-act", href: `#/kb-chat/${kb.id}` },
    miniIcon(ACT_ICONS.chat), h("span", {}, t("kb_chat")));
  const manageBtn = h("button", { class: "btn secondary small kb-act", type: "button", title: t("kb_upload_chunks") },
    miniIcon(ACT_ICONS.upload), h("span", {}, t("kb_upload_chunks")));
  manageBtn.addEventListener("click", () => openKbModal(kb, refresh));
  const embedBtn = h("button", { class: "btn ghost small kb-act", type: "button" },
    miniIcon(ACT_ICONS.code), h("span", {}, t("kb_embed")));
  embedBtn.addEventListener("click", () => openEmbedModal(kb));
  const delBtn = h("button", { class: "btn ghost small danger-text kb-del", type: "button", title: t("kb_delete"), "aria-label": t("kb_delete") }, trashIcon());
  delBtn.addEventListener("click", async () => {
    if (delBtn.disabled || !ask("kb_delete_confirm")) return;
    // Keep the SVG intact while the request is pending and after any error.
    delBtn.disabled = true;
    delBtn.setAttribute("aria-busy", "true");
    let r;
    try { r = await api("DELETE", `/collections/${kb.id}`); }
    finally { delBtn.disabled = false; delBtn.removeAttribute("aria-busy"); }
    onDelete(kb, r);
  });
  return h("div", { class: "kb-item" },
    h("div", { class: "kb-item-main" },
      openBtn,
      h("div", { class: "kb-item-meta" }, `${t("kb_chunks")}: ${kb.chunks}`)),
    h("div", { class: "kb-item-actions" }, chatLink, manageBtn, embedBtn, delBtn));
}
function trashIcon() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const d of ["M3 6h18", "M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2",
                   "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6",
                   "M10 11v6", "M14 11v6"]) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

// ---------------- upload + chunk editor (modal) ----------------
function modalShell(label, build) {
  const box = h("div", { class: "kb-modal-card", role: "dialog", "aria-modal": "true", "aria-label": label });
  const overlay = h("div", { class: "kb-modal" }, box);
  const closeBtn = h("button", { class: "kb-modal-close", type: "button", "aria-label": t("kb_close") }, "\u00d7");
  const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", onKey);
  box.append(h("div", { class: "kb-modal-head" }, h("h2", {}, label), closeBtn));
  build(box, close);
  document.body.append(overlay);
  closeBtn.focus();
}

function openKbModal(kb, refresh) {
  modalShell(kb.title, (box) => {
    const file = h("input", { type: "file", accept: "application/pdf", "aria-label": t("kb_upload_title") });
    const consent = h("input", { id: "kb_upload_consent", type: "checkbox" });
    const uploadBtn = h("button", { class: "btn small", type: "button" }, t("kb_upload_btn"));
    const uploadMsg = h("div", { role: "status", "aria-live": "polite" });
    const chunkBox = h("div", { class: "kb-chunks" });

    const renderChunks = async (flash) => {
      chunkBox.replaceChildren(h("p", { class: "empty" }, t("loading")));
      const r = await api("GET", `/collections/${kb.id}/chunks`);
      if (!r.ok) { chunkBox.replaceChildren(alertBox(errorText(r))); return; }
      const head = flash ? h("div", { class: "success" }, flash) : null;
      if (!r.data.chunks.length) { chunkBox.replaceChildren(...[head, h("p", { class: "empty" }, t("kb_chunks_empty"))].filter(Boolean)); return; }
      chunkBox.replaceChildren(...[head, h("div", { class: "kb-chunk-list" },
        r.data.chunks.map((c) => {
          const item = h("button", { class: "kb-chunk-item", type: "button" },
            h("span", { class: "kb-chunk-meta" }, `#${c.chunk_id} \u00b7 ${t("legal_page")} ${c.page}`),
            h("span", { class: "kb-chunk-text" }, c.text.slice(0, 200)));
          item.addEventListener("click", () => openChunkEditor(c));
          return item;
        }))].filter(Boolean));
    };

    const openChunkEditor = (c) => {
      const ta = h("textarea", { id: "kb_chunk_edit", rows: 9, maxlength: 8000, "aria-label": t("kb_chunk_text") });
      ta.value = c.text;
      const msg = h("div", { role: "status", "aria-live": "polite" });
      const save = h("button", { class: "btn small", type: "button" }, t("kb_chunk_update"));
      const del = h("button", { class: "btn ghost small danger-text", type: "button" }, t("kb_chunk_delete"));
      const back = h("button", { class: "btn ghost small", type: "button" }, t("kb_back_list"));
      save.addEventListener("click", async () => {
        msg.replaceChildren();
        const text = ta.value.trim();
        if (!text) { msg.append(alertBox(t("kb_chunk_text"))); return; }
        const r = await withLoading(save, t("loading"), () => api("PUT", `/collections/${kb.id}/chunks/${c.chunk_id}`, { text }));
        if (!r.ok) { msg.append(alertBox(errorText(r))); return; }
        renderChunks(t("kb_chunk_saved"));
      });
      del.addEventListener("click", async () => {
        if (!ask("kb_chunk_delete_confirm")) return;
        const r = await withLoading(del, t("loading"), () => api("DELETE", `/collections/${kb.id}/chunks/${c.chunk_id}`));
        if (!r.ok) { msg.replaceChildren(alertBox(errorText(r))); return; }
        renderChunks();
        if (refresh) refresh();
      });
      back.addEventListener("click", () => renderChunks());
      chunkBox.replaceChildren(h("div", { class: "kb-editor" },
        h("div", { class: "kb-chunk-meta" }, `#${c.chunk_id} \u00b7 ${t("legal_page")} ${c.page}`),
        h("label", { class: "kb-editor-label", for: "kb_chunk_edit" }, t("kb_chunk_editor")),
        ta, msg, h("div", { class: "row" }, save, del, back)));
      ta.focus();
    };

    uploadBtn.addEventListener("click", async () => {
      uploadMsg.replaceChildren();
      if (!file.files.length) { uploadMsg.append(alertBox(t("file_empty"))); return; }
      const r = await withLoading(uploadBtn, t("kb_uploading"), () => apiUpload(`/collections/${kb.id}/upload`, file.files[0],
        { consent: consent.checked ? "true" : "false" }));
      if (!r.ok) { uploadMsg.append(alertBox(errorText(r))); return; }
      file.value = "";
      uploadMsg.append(h("div", { class: "success" }, `${t("kb_uploaded")} (${r.data.chunks})`));
      if (refresh) refresh();
      renderChunks();
    });

    box.append(
      h("div", { class: "kb-upload" },
        h("p", { class: "hint" }, t("kb_upload_hint")),
        h("div", { class: "kb-upload-row" }, file, uploadBtn),
        h("label", { class: "check", for: "kb_upload_consent" }, consent, h("span", { class: "inline" }, t("kb_consent"))),
        uploadMsg),
      h("div", { class: "card-head" }, h("h2", {}, t("kb_chunks"))),
      chunkBox);
    renderChunks();
  });
}

function openEmbedModal(kb) {
  modalShell(t("kb_embed_title"), (box) => {
    const origin = location.origin;
    const themes = [
      { color: "#064E3B", key: "kb_theme_emerald", cls: "is-emerald" },
      { color: "#1E3A8A", key: "kb_theme_navy", cls: "is-navy" },
      { color: "#0F766E", key: "kb_theme_teal", cls: "is-teal" },
      { color: "#1F2937", key: "kb_theme_charcoal", cls: "is-charcoal" },
    ];
    const snippetFor = (color) =>
      `<script src="${origin}/static/widget.js" data-kb-id="${kb.id}" data-token="${kb.embed_token}" data-color="${color}"></script>`;
    const code = h("textarea", { rows: 4, readonly: true, class: "kb-embed-code", "aria-label": t("kb_embed_title") });
    const copy = h("button", { class: "btn small", type: "button" }, t("kb_embed_copy"));
    const msg = h("div", { role: "status", "aria-live": "polite" });
    const preview = h("div", { class: "kb-embed-preview is-emerald", role: "img", "aria-label": t("kb_theme_preview") },
      h("div", { class: "kb-embed-preview-head" },
        h("span", {}, t("kb_embed_preview_title")),
        h("span", { class: "kb-embed-preview-close", "aria-hidden": "true" }, "\u00d7")),
      h("div", { class: "kb-embed-preview-body", "aria-hidden": "true" },
        h("span", { class: "kb-embed-preview-bubble bot" }),
        h("span", { class: "kb-embed-preview-bubble user" })),
      h("div", { class: "kb-embed-preview-form", "aria-hidden": "true" },
        h("span", { class: "kb-embed-preview-input" }),
        h("span", { class: "kb-embed-preview-send" })));

    let selected = themes[0];
    const swatches = themes.map((theme) => {
      const btn = h("button", {
        type: "button", class: `kb-theme-swatch ${theme.cls}`,
        "aria-pressed": String(theme.color === selected.color), "aria-label": t(theme.key), title: t(theme.key),
      });
      btn.addEventListener("click", () => select(theme));
      return btn;
    });
    const select = (theme) => {
      selected = theme;
      preview.className = `kb-embed-preview ${theme.cls}`;
      code.value = snippetFor(theme.color);
      swatches.forEach((btn, i) => btn.setAttribute("aria-pressed", String(themes[i].color === theme.color)));
    };
    select(selected);

    copy.addEventListener("click", async () => {
      msg.replaceChildren();
      try {
        await navigator.clipboard.writeText(code.value);
        msg.append(h("div", { class: "success" }, t("kb_embed_copied")));
      } catch {
        code.focus();
        code.select();
      }
    });
    box.append(
      h("p", { class: "hint" }, t("kb_embed_hint")),
      h("div", { class: "kb-embed-theme" },
        h("div", {},
          h("p", { class: "kb-theme-label" }, t("kb_theme_label")),
          h("div", { class: "kb-theme-swatches", role: "group", "aria-label": t("kb_theme_label") }, swatches)),
        preview),
      code,
      h("div", { class: "row" }, copy),
      msg);
  });
}

export async function openEmbedForFirstKb() {
  const r = await api("GET", "/collections");
  if (!r.ok) return false;
  const kb = r.data.collections[0];
  if (!kb) return false;
  openEmbedModal(kb);
  return true;
}

// ---------------- Screen 2: RAG chat with sidebar + system prompt ----------------
export function kbChat(id) {
  const kbId = id ? Number(id) : null;
  const sideList = h("div", { class: "kb-side-list" });
  const main = h("div", { class: "kb-chat-main" });
  const root = h("section", { class: "kb-chat" },
    h("aside", { class: "kb-chat-side", "aria-label": t("kb_list_title") },
      h("div", { class: "card-head" },
        h("h2", {}, t("kb_list_title")),
        link("#/dashboard", "+", "btn ghost small")),
      sideList),
    main);

  fill(sideList, async () => {
    const r = await api("GET", "/collections");
    if (!r.ok) return alertBox(errorText(r));
    const kbs = r.data.collections;
    if (!kbs.length) {
      main.replaceChildren(h("div", { class: "card" }, h("p", { class: "empty" }, t("kb_chat_no_kb")),
        h("div", { class: "row" }, link("#/dashboard", t("kb_create"), "btn"))));
      return h("p", { class: "ai-side-empty" }, t("kb_empty"));
    }
    if (!kbId) { location.replace(`#/kb-chat/${kbs[0].id}`); return null; }    const kb = kbs.find((x) => x.id === kbId);
    if (!kb) { main.replaceChildren(h("div", { class: "card" }, h("p", { class: "empty" }, t("kb_not_found")),
      h("div", { class: "row" }, link("#/kb-chat", t("kb_chat_select"), "btn secondary")))); return null; }
    renderMain(kb);
    return h("div", {}, kbs.map((x) => {
      const a = h("a", { href: `#/kb-chat/${x.id}`, class: x.id === kb.id ? "kb-side-item active" : "kb-side-item" },
        h("span", { class: "kb-side-title" }, x.title),
        h("span", { class: "meta" }, `${t("kb_chunks")}: ${x.chunks}`));
      return a;
    }));
  });
  return root;

  function renderMain(kb) {
    const system = h("textarea", { rows: 4, maxlength: 4000, "aria-label": t("kb_system_title") });
    system.value = kb.system_prompt || "";
    const saveBtn = h("button", { class: "btn secondary small", type: "button" }, t("kb_system_save"));
    const saveMsg = h("div", { role: "status", "aria-live": "polite" });
    saveBtn.addEventListener("click", async () => {
      saveMsg.replaceChildren();
      const r = await withLoading(saveBtn, t("loading"), () => api("PUT", `/collections/${kb.id}`, { system_prompt: system.value }));
      if (!r.ok) { saveMsg.append(alertBox(errorText(r))); return; }
      kb.system_prompt = r.data.system_prompt;
      saveMsg.append(h("div", { class: "success" }, t("kb_system_saved")));
    });
    const embedBtn = h("button", { class: "btn secondary small", type: "button" }, t("kb_embed"));
    embedBtn.addEventListener("click", () => openEmbedModal(kb));

    const log = h("div", { class: "kb-log", role: "log", "aria-label": t("kb_chat_title") });
    const qIn = h("textarea", { rows: 2, maxlength: 1000, placeholder: t("kb_chat_placeholder"), "aria-label": t("kb_chat_title") });
    const consent = h("input", { id: "kb_chat_consent", type: "checkbox" });
    const send = h("button", { class: "btn", type: "submit" }, t("kb_chat_send"));
    const err = h("div", { role: "alert" });
    const form = h("form", { class: "kb-composer", novalidate: true },
      err,
      qIn,
      h("label", { class: "check", for: "kb_chat_consent" }, consent, h("span", { class: "inline" }, t("kb_consent"))),
      h("div", { class: "row" }, send));

    log.append(h("p", { class: "empty" }, t("kb_chat_empty")));
    let started = false;
    const sendQuestion = async () => {
      const q = qIn.value.trim();
      err.replaceChildren();
      if (q.length < 5) { err.append(alertBox(t("legal_question_short"))); return; }
      qIn.value = "";
      if (!started) { log.replaceChildren(); started = true; }
      appendUser(log, q);
      const pending = h("div", { class: "kb-msg bot" }, h("span", { class: "kb-status" }, t("kb_typing")));
      log.append(pending);
      log.scrollTop = log.scrollHeight;
      const r = await api("POST", `/collections/${kb.id}/chat`, { question: q, consent: consent.checked, language: getLang() });
      pending.replaceChildren();
      if (!r.ok) pending.append(alertBox(errorText(r)));
      else pending.append(answerBlock(r.data));
      log.scrollTop = log.scrollHeight;
    };
    form.addEventListener("submit", (e) => { e.preventDefault(); sendQuestion(); });
    qIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendQuestion(); }
    });

    main.replaceChildren(
      h("div", { class: "page-head" },
        h("span", { class: "eyebrow" }, t("kb_chat_title")),
        h("h1", {}, kb.title),
        h("p", { class: "lead" }, t("kb_chat_lead"))),
      trackingPill(kb),
      h("div", { class: "row" }, link("#/dashboard", t("nav_home"), "btn secondary"), embedBtn),
      h("div", { class: "card kb-system" },
        h("h2", {}, t("kb_system_title")),
        h("p", { class: "hint" }, t("kb_system_hint")),
        system, saveMsg, h("div", { class: "row" }, saveBtn)),
      log,
      form);
  }
}

function appendUser(log, text) {
  log.append(h("div", { class: "kb-msg user" }, h("div", { class: "kb-bubble" }, text)));
}

function sessionTracking(kb) {
  const year = new Date(kb.created_at || Date.now()).getFullYear() || new Date().getFullYear();
  return `IS-${year}-${String(1000 + (kb.id || 0)).padStart(4, "0")}`;
}

function trackingPill(kb) {
  const ref = sessionTracking(kb);
  const status = h("span", { class: "kb-track-status", role: "status", "aria-live": "polite" });
  const copy = h("button", { class: "kb-track-copy", type: "button", "aria-label": t("kb_track_copy") }, t("kb_track_copy"));
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(ref);
    } catch { /* clipboard band ho to number screen se select karke copy kiya ja sakta hai */ }
    status.textContent = t("kb_track_copied");
    setTimeout(() => { status.textContent = ""; }, 2000);
  });
  return h("div", { class: "kb-track-pill" },
    h("span", { class: "kb-track-label" }, t("kb_track_label")),
    h("code", { class: "kb-track-id" }, ref),
    copy, status);
}

function answerBlock(d) {
  if (!d) return h("p", { class: "hint" }, t("err_generic"));
  const parts = [];
  if (!d.found) parts.push(h("div", { class: "notice" }, h("strong", {}, t("kb_no_match")), h("p", {}, d.answer)));
  else {
    parts.push(h("p", { class: "kb-answer" }, d.answer));
    if (d.sources && d.sources.length) {
      parts.push(h("div", { class: "kb-sources" }, d.sources.map((s) => h("div", { class: "kb-source" },
        h("span", { class: "kb-source-head" }, `[${s.n}] #${s.chunk_id} \u00b7 ${t("legal_page")} ${s.page}`),
        h("p", {}, s.snippet)))));
    }
  }
  if (d.disclaimer) parts.push(h("p", { class: "ai-disclaimer" }, d.disclaimer));
  return h("div", {}, parts);
}
