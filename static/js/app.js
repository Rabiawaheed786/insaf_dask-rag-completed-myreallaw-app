import { api } from "./api.js";
import { applyStatic, getLang, initI18n, setLang, t } from "./i18n.js";
import { caseRoom } from "./case.js";
import { adminHome, coordCase, coordHome, superAdminPanel } from "./staff.js";
import { lawyerCase, lawyerHome } from "./lawyer.js";
import { state } from "./state.js";
import { dashboard, newRequest, notifications, requestDetail, settings } from "./user.js";
import { legalHelp } from "./legal.js";
import { kbChat } from "./kb.js";
import { scamHelp } from "./scam.js";
import * as views from "./views.js";

const main = document.getElementById("main"), nav = document.getElementById("nav");
// [pattern, view, login zaroori?, roles (khali = sab)]
const ROUTES = [
  [/^\/?$/, views.home], [/^\/login$/, views.login], [/^\/signup$/, views.signup], [/^\/emergency$/, views.emergency],
  [/^\/dashboard$/, dashboard, true], [/^\/new$/, newRequest, true], [/^\/request\/(\d+)$/, requestDetail, true],
  [/^\/notifications$/, notifications, true], [/^\/settings$/, settings, true], [/^\/case\/([A-Za-z0-9-]+)$/, caseRoom, true],
  [/^\/legal$/, legalHelp, true], [/^\/scam$/, scamHelp, true],
  [/^\/kb-chat$/, kbChat, true], [/^\/kb-chat\/(\d+)$/, kbChat, true],
  [/^\/lawyer$/, lawyerHome, true], [/^\/lawyer-case\/([A-Za-z0-9-]+)$/, lawyerCase, true, ["lawyer"]],
  [/^\/coord$/, coordHome, true, ["coordinator", "admin"]], [/^\/coord-case\/([A-Za-z0-9-]+)$/, coordCase, true, ["coordinator", "admin"]],
  [/^\/admin$/, adminHome, true, ["admin", "super_admin"]],
  [/^\/super-admin$/, superAdminPanel, true, ["super_admin"]],
];

function backTarget(path) {
  if (["/", "/login", "/signup", "/dashboard", "/legal", "/scam", "/emergency"].includes(path)) return null;
  if (path.startsWith("/lawyer-case/")) return "#/lawyer";
  if (path.startsWith("/coord-case/")) return "#/coord";
  return "#/dashboard";
}

function backBar(href) {
  const a = document.createElement("a");
  a.href = href;
  a.className = "back-link page-back";
  a.textContent = t("nav_back");
  return a;
}

function renderNav(path) {
  const u = state.user;
  if (!u) { nav.replaceChildren(); return; }
  const items = [["#/dashboard", "nav_home"], ["#/new", "nav_new"], ["#/legal", "nav_legal"], ["#/kb-chat", "nav_kb"], ["#/scam", "nav_scam"], ["#/notifications", "nav_notifications"], ["#/settings", "nav_settings"], ["#/lawyer", "nav_lawyer"]];
  if (["coordinator", "admin"].includes(u.role)) items.push(["#/coord", "nav_coord"]);
  if (u.role === "admin" || u.role === "super_admin") items.push(["#/admin", "nav_admin"]);
  const links = items.map(([href, key]) => {
    const a = document.createElement("a");
    a.href = href; a.textContent = t(key);
    if (path && href === "#" + path) a.setAttribute("aria-current", "page");
    return a;
  });
  const out = document.createElement("a");
  out.href = "#/"; out.textContent = t("btn_logout");
  out.className = "nav-logout";
  out.addEventListener("click", async (e) => { e.preventDefault(); await api("POST", "/api/auth/logout"); state.user = null; state.next = null; location.hash = "#/"; render(); });
  nav.replaceChildren(...links, out);
}

async function render() {
  clearInterval(state.timer);
  const path = location.hash.replace(/^#/, "");
  const aiMode = path === "/legal";
  document.body.classList.toggle("ai-mode", aiMode);
  document.body.classList.toggle("dash-mode", path === "/dashboard");
  if (state.user && (path === "/login" || path === "/signup")) { location.replace("#/dashboard"); return; }
  for (const [rx, view, needLogin, roles] of ROUTES) {
    const m = path.match(rx);
    if (!m) continue;
    if (needLogin && !state.user) {
      document.body.classList.remove("ai-mode");
      state.next = path === "/legal" ? "#/legal" : null;
      location.hash = "#/login";
      return;
    }
    if (roles && !roles.includes(state.user.role)) { document.body.classList.remove("ai-mode"); location.hash = "#/dashboard"; return; }
    renderNav(path);
    const viewEl = await view(...m.slice(1));
    const back = backTarget(path);
    main.replaceChildren(...(back ? [backBar(back)] : []), viewEl);
    window.scrollTo(0, 0);
    return;
  }
  renderNav(path);
  main.replaceChildren(views.notFound());
}

// Screen chhupayein (quick exit): screen foran saaf, tab ka title badal, phir aam website par (history ki entry badal jati hai).
// Yeh browser ki purani history nahi mitata; yeh baat screen par bhi likhi hai.
export function quickExit() {
  clearInterval(state.timer);
  document.body.classList.remove("ai-mode", "dash-mode");
  main.replaceChildren();
  nav.replaceChildren();
  document.title = "Google";
  state.user = null;
  state.next = null;
  location.replace("https://www.google.com/");
}

function wire() {
  document.getElementById("btn-quickexit").addEventListener("click", quickExit);
  document.getElementById("btn-emergency").addEventListener("click", () => { location.hash = "#/emergency"; render(); });
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", async () => {
    setLang(b.dataset.lang);
    if (state.user) api("PUT", "/api/auth/me/language", { language: getLang() });  // login ho to server par bhi yaad rahe
    render();
  }));
  let escapes = [];  // Escape teen baar jaldi dabane se bhi quick exit
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const now = Date.now();
    escapes = [...escapes.filter((x) => now - x < 1200), now];
    if (escapes.length >= 3) quickExit();
  });
  window.addEventListener("hashchange", render);
}

async function boot() {
  await initI18n();
  applyStatic();
  wire();
  const me = await api("GET", "/api/auth/me");  // pehle se login ho to wahi session
  if (me.ok) { state.user = me.data; if (me.data.language !== getLang()) setLang(me.data.language); }
  await render();
}
boot();
