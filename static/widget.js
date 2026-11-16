/* Insaf Dastak chat widget.
   Lagane ka tareeqa:
   <script src="https://your-host/static/widget.js" data-kb-id="12" data-token="..." data-color="#064E3B"></script>
   Koi dependency nahi; sirf ek floating chat bubble. data-color optional hai (hex color). */
(function () {
  "use strict";
  var script = document.currentScript || document.querySelector("script[data-kb-id]");
  if (!script || window.__insafKbWidget) return;
  var kbId = script.getAttribute("data-kb-id");
  var token = script.getAttribute("data-token") || "";
  if (!kbId || !token) return;
  window.__insafKbWidget = true;

  var origin = new URL(script.src, location.href).origin;
  var color = script.getAttribute("data-color") || "#0F382C";
  if (!/^#[0-9a-fA-F]{6}$/.test(color)) color = "#0F382C";
  var lang = script.getAttribute("data-lang") === "en" ? "en" : "roman_urdu";
  var TXT = lang === "en" ? {
    open: "Open chat", title: "Knowledge Base", close: "Close", placeholder: "Type your question...",
    send: "Send", error: "Could not get an answer. Try again.", thinking: "Thinking...",
  } : {
    open: "Chat kholein", title: "Knowledge Base", close: "Band karein", placeholder: "Apna sawal likhein...",
    send: "Send", error: "Jawab nahi mila. Dobara koshish karein.", thinking: "Soch raha hai...",
  };

  var style = document.createElement("style");
  style.textContent = [
    ".idw{position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}",
    ".idw-bubble{width:56px;height:56px;border-radius:50%;border:0;background:" + color + ";color:#fff;font-size:22px;cursor:pointer;box-shadow:0 8px 24px rgba(15,56,44,.35)}",
    ".idw-panel{display:none;flex-direction:column;width:340px;max-width:calc(100vw - 32px);height:440px;max-height:calc(100vh - 100px);background:#fff;border:1px solid #d8e2dc;border-radius:14px;box-shadow:0 16px 48px rgba(15,36,28,.28);overflow:hidden;margin-bottom:10px}",
    ".idw.open .idw-panel{display:flex}",
    ".idw-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;background:" + color + ";color:#fff;font-weight:650;font-size:14px}",
    ".idw-close{border:0;background:transparent;color:#fff;font-size:20px;line-height:1;cursor:pointer}",
    ".idw-log{flex:1;overflow-y:auto;padding:12px;background:#f6faf8;display:flex;flex-direction:column;gap:8px}",
    ".idw-msg{max-width:85%;padding:9px 11px;border-radius:11px;font-size:13px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word}",
    ".idw-msg.user{align-self:flex-end;background:" + color + ";color:#fff;border-bottom-right-radius:3px}",
    ".idw-msg.bot{align-self:flex-start;background:#fff;border:1px solid #d8e2dc;color:#12241d;border-bottom-left-radius:3px}",
    ".idw-msg.bot em{display:block;margin-top:6px;color:#6b7f76;font-size:11px;font-style:normal}",
    ".idw-form{display:flex;gap:6px;padding:10px;border-top:1px solid #e2eae5;background:#fff}",
    ".idw-input{flex:1;min-height:38px;max-height:90px;padding:8px 10px;border:1px solid #cfdad4;border-radius:8px;font:inherit;font-size:13px;resize:none}",
    ".idw-send{border:0;background:" + color + ";color:#fff;border-radius:8px;padding:0 13px;font-weight:650;cursor:pointer}",
    ".idw-err{color:#8a1c1c;font-size:11px;padding:0 12px 8px;background:#fff}",
  ].join("\n");
  document.head.appendChild(style);

  var root = document.createElement("div");
  root.className = "idw";
  var panel = document.createElement("div");
  panel.className = "idw-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", TXT.title);

  var head = document.createElement("div");
  head.className = "idw-head";
  var title = document.createElement("span");
  title.textContent = TXT.title;
  var close = document.createElement("button");
  close.className = "idw-close";
  close.type = "button";
  close.setAttribute("aria-label", TXT.close);
  close.textContent = "\u00d7";
  head.append(title, close);

  var log = document.createElement("div");
  log.className = "idw-log";
  log.setAttribute("role", "log");

  var err = document.createElement("div");
  err.className = "idw-err";
  err.setAttribute("role", "alert");

  var form = document.createElement("form");
  form.className = "idw-form";
  var input = document.createElement("textarea");
  input.className = "idw-input";
  input.rows = 1;
  input.placeholder = TXT.placeholder;
  input.setAttribute("aria-label", TXT.placeholder);
  var send = document.createElement("button");
  send.className = "idw-send";
  send.type = "submit";
  send.textContent = TXT.send;
  form.append(input, send);

  var bubble = document.createElement("button");
  bubble.className = "idw-bubble";
  bubble.type = "button";
  bubble.setAttribute("aria-label", TXT.open);
  bubble.textContent = "\u25cf";

  panel.append(head, log, err, form);
  root.append(panel, bubble);
  document.body.appendChild(root);

  function bubbleMsg(text, role) {
    var el = document.createElement("div");
    el.className = "idw-msg " + role;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function toggle(open) {
    root.classList.toggle("open", open);
    if (open) input.focus();
  }

  bubble.addEventListener("click", function () { toggle(true); });
  close.addEventListener("click", function () { toggle(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") toggle(false); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    err.textContent = "";
    if (q.length < 5) { err.textContent = TXT.error; return; }
    input.value = "";
    bubbleMsg(q, "user");
    var pending = bubbleMsg(TXT.thinking, "bot");
    fetch(origin + "/api/widget/" + encodeURIComponent(kbId) + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Kb-Token": token },
      body: JSON.stringify({ question: q, language: lang }),
    }).then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    }).then(function (out) {
      pending.remove();
      if (!out.ok) {
        var d = out.data && out.data.detail;
        bubbleMsg((d && d.message) || TXT.error, "bot");
        return;
      }
      bubbleMsg(out.data.answer, "bot");
      if (out.data.disclaimer) {
        var note = document.createElement("em");
        note.textContent = out.data.disclaimer;
        log.lastChild.appendChild(note);
        log.scrollTop = log.scrollHeight;
      }
    }).catch(function () {
      pending.remove();
      bubbleMsg(TXT.error, "bot");
    });
  });
})();
