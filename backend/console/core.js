/* 控制台 · 全局状态、api/esc/toast、登录与外壳、品牌水印、导航与权限 | 原 console.js 第 1–265 行 */
/* 管理控制台（后端自带）：硬件探测、平台部署、模型清单与建议 */
const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "wb_token";
const REMEMBER_USER_KEY = "wb_console_username";
const REMEMBER_FLAG_KEY = "wb_console_remember";

function rememberedConsoleUser() {
  try {
    if (localStorage.getItem(REMEMBER_FLAG_KEY) === "0") return "";
    return localStorage.getItem(REMEMBER_USER_KEY) || "";
  } catch (e) { return ""; }
}

function saveConsoleUser(name) {
  try {
    const box = $("rememberUser");
    const on = !box || box.checked;
    localStorage.setItem(REMEMBER_FLAG_KEY, on ? "1" : "0");
    if (on) localStorage.setItem(REMEMBER_USER_KEY, name);
    else localStorage.removeItem(REMEMBER_USER_KEY);
  } catch (e) { /* 隐私模式忽略 */ }
}
const S = { hw: null, models: null, install: null, timer: null, installing: false, localBusy: false, localEnabled: true, modelCategory: "all", cluster: null, clusterEditNode: 0, clusterEditPool: 0, clusterMembers: [], cookieSession: false };
const MODEL_CATEGORY_ORDER = [
  ["text", "文字 / 对话"], ["code", "代码 / 编程"], ["vision", "多模态 / 视觉"],
  ["ocr", "OCR / 文档"], ["image", "绘画 / 图像"], ["video", "视频生成"],
  ["audio", "语音 / 音频"], ["embedding", "向量 / 检索"], ["rerank", "重排序"],
];

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }

/** 读 cookie（用户端登录后浏览器自带 wb_session / wb_csrf，控制台复用同一个会话，不再要求二次登录） */
function cookieValue(name) {
  try {
    const hit = document.cookie.split(";").map((s) => s.trim())
      .find((s) => s.startsWith(name + "="));
    return hit ? decodeURIComponent(hit.slice(name.length + 1)) : "";
  } catch (e) { return ""; }
}

/** 是否已登录：Bearer 令牌（旧版登录态）或同源 cookie 会话（用户端登录后直接进控制台） */
function signedIn() { return !!(token() || S.cookieSession); }


/** 把后端错误体转成一句可读文案：字符串、校验数组、结构化 detail 都支持。 */
function errorMessage(d, fallback = "请求失败") {
  if (!d) return fallback;
  if (typeof d === "string") return d;
  if (Array.isArray(d.detail)) return d.detail.map((x) => x.msg || String(x)).join("；");
  if (d.detail && typeof d.detail === "object") return String(d.detail.message || d.detail.code || fallback);
  if (d.detail) return String(d.detail);
  if (d.message) return String(d.message);
  return fallback;
}

async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.headers || {}) }, credentials: "same-origin" };
  if (o.body && typeof o.body === "string") o.headers["Content-Type"] = "application/json";
  const tk = token();
  if (tk) o.headers["Authorization"] = "Bearer " + tk;
  else {
    const csrf = cookieValue("wb_csrf");
    if (csrf && (o.method || "GET").toUpperCase() !== "GET") o.headers["X-CSRF-Token"] = csrf;
  }
  const r = await fetch(path, o);
  if (r.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    S.cookieSession = false;
    showLogin();
    throw new Error("未登录");
  }
  const ct = r.headers.get("content-type") || "";
  const d = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const e = new Error(errorMessage(d));
    e.status = r.status;
    e.code = (d && d.code) || "";
    e.data = d;
    throw e;
  }
  return d;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let _toastTimer = null;
function uiToast(text, kind = "info") {
  let el = $("uiToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "uiToast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.className = `ui-toast ${kind}`;
  el.hidden = false;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.hidden = true; }, kind === "bad" ? 4200 : 2600);
}

function confirmInline(message, okText = "确认") {
  return new Promise((resolve) => {
    const old = $("inlineConfirm");
    if (old) old.remove();
    const bar = document.createElement("div");
    bar.id = "inlineConfirm";
    bar.className = "inline-confirm";
    const text = document.createElement("span");
    text.textContent = message;
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn";
    cancel.textContent = "取消";
    const ok = document.createElement("button");
    ok.type = "button";
    ok.className = "btn danger";
    ok.textContent = okText;
    const close = (value) => {
      document.removeEventListener("keydown", onKey, true);
      bar.remove();
      resolve(value);
    };
    const onKey = (ev) => {
      if (ev.key === "Escape") { ev.preventDefault(); close(false); }
      if (ev.key === "Enter") { ev.preventDefault(); close(true); }
    };
    cancel.addEventListener("click", () => close(false));
    ok.addEventListener("click", () => close(true));
    bar.append(text, cancel, ok);
    document.body.appendChild(bar);
    document.addEventListener("keydown", onKey, true);
    ok.focus();
  });
}

function gb(n) { return (Number(n || 0)).toFixed(1) + " GB"; }
function mb(n) { return (Number(n || 0) / 2 ** 20).toFixed(0) + " MB"; }

function showLogin(setup = false) {
  S.setupMode = !!setup;
  if (S.tunnelTimer) { clearInterval(S.tunnelTimer); S.tunnelTimer = null; }
  try {
    if (location.hash || location.search) history.replaceState(null, "", location.pathname);
  } catch {}
  const brandName = S.branding && S.branding.org_name ? S.branding.org_name : "本地 AI 工作台";
  document.title = `管理控制台 · ${brandName}`;
  const wm = $("wbWatermark");
  if (wm) wm.remove();
  $("loginWrap").hidden = false;
  $("main").hidden = true;
  $("tabs").hidden = true;
  $("navToggle").hidden = true;
  const navSearch = $("navSearch");
  if (navSearch) navSearch.value = "";
  closeNav();
  $("refreshBtn").hidden = true;
  $("refreshBtn").disabled = false;
  $("refreshBtn").textContent = "刷新数据";
  $("logoutBtn").hidden = true;
  $("frontendBtn").hidden = true;
  $("tunnelBtn").hidden = true;
  const pageGuideBtn = $("pageGuideBtn");
  if (pageGuideBtn) pageGuideBtn.hidden = true;
  closePageGuide(false);
  $("loginTitle").textContent = setup ? "初始化管理员" : "登录控制台";
  $("loginDesc").textContent = setup
    ? "这台机器还没有管理员账号：下面预填的 admin 就是即将创建的第一个管理员，可以改成别的用户名"
    : "使用工作台管理员账号";
  $("confirmRow").hidden = !setup;
  const rememberRow = $("rememberRow");
  if (rememberRow) rememberRow.hidden = setup;
  $("loginBtn").textContent = setup ? "初始化并进入" : "进入";
  $("alert").textContent = "";
  const rememberBox = $("rememberUser");
  if (rememberBox) {
    try { rememberBox.checked = localStorage.getItem(REMEMBER_FLAG_KEY) !== "0"; } catch (e) { rememberBox.checked = true; }
  }
  $("u").value = setup ? "admin" : rememberedConsoleUser();
  $("p").value = "";
  $("p2").value = "";
  $("p").focus();
}
function showMain() {
  $("loginWrap").hidden = true;
  $("main").hidden = false;
  $("tabs").hidden = false;
  $("navToggle").hidden = false;
  $("refreshBtn").hidden = false;
  $("logoutBtn").hidden = false;
  $("frontendBtn").hidden = false;
  const pageGuideBtn = $("pageGuideBtn");
  if (pageGuideBtn) pageGuideBtn.hidden = false;
  $("tunnelBtn").hidden = false;
  loadFrontendSettings().catch(() => {});
}

function applyBranding(branding, username) {
  if (!branding) return;
  S.branding = branding;
  const name = String(branding.org_name || "本地 AI 工作台").trim() || "本地 AI 工作台";
  document.title = `管理控制台 · ${name}`;
  document.querySelectorAll("[data-brand-name]").forEach((el) => { el.textContent = name; });
  renderWatermark(branding, username);
}

function renderWatermark(branding, username) {
  const old = $("wbWatermark");
  if (old) old.remove();
  if (!branding || !branding.watermark_enabled || !username) return;
  const org = String(branding.org_name || "本地 AI 工作台");
  const text = String(branding.watermark_text || "{user} · {org}")
    .replaceAll("{user}", username).replaceAll("{org}", org)
    .replaceAll("{date}", new Date().toLocaleDateString("zh-CN"));
  const layer = document.createElement("div");
  layer.id = "wbWatermark";
  layer.className = "watermark-layer";
  layer.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 60; i++) {
    const span = document.createElement("span");
    span.textContent = text;
    span.style.left = ((i % 6) * 18 - 8) + "%";
    span.style.top = (Math.floor(i / 6) * 13 - 6) + "%";
    layer.appendChild(span);
  }
  document.body.appendChild(layer);
}

const TAB_MODULES = {
  overview: "overview", org: "org", moderation: "moderation", requests: "requests", users: "users", skills: "skills",
  prompts: "prompts",
  front: "front",
  agents: "agents", partners: "partners", squads: "squads", announcements: "announcements",
  tickets: "tickets", "conv-shares": "conv_shares",
  auth: "auth", providers: "providers", routes: "routes", api: "api",
  network: "network", websearch: "websearch", parsing: "parsing",
  deploy: "deploy", cluster: "cluster", models: "models",
  kb: "kb", library: "library", memory: "memory", backup: "backup",
  audit: "audit", database: "database", share: "share",
};

function applyAdminPermissions(user) {
  S.me = user || null;
  if (!user || user.role !== "admin") {
    S.adminPermissions = null;
    document.querySelectorAll("#tabs .tab").forEach((btn) => { btn.hidden = false; });
    updateNavGroups();
    return;
  }
  S.adminPermissions = Array.isArray(user.admin_permissions) ? user.admin_permissions : [];
  document.querySelectorAll("#tabs .tab").forEach((btn) => {
    const module = TAB_MODULES[btn.dataset.tab];
    btn.hidden = !!module && !S.adminPermissions.includes(module);
  });
  updateNavGroups();
}

function updateNavGroups() {
  const groups = [...document.querySelectorAll("#tabs .nav-group")];
  groups.forEach((group) => {
    const visible = [...group.querySelectorAll(".tab")].filter((btn) => !btn.hidden && !btn.classList.contains("nav-away"));
    group.hidden = visible.length === 0;
  });
  const empty = $("navEmpty");
  if (empty) empty.hidden = groups.some((group) => !group.hidden);
}

function filterNav() {
  const input = $("navSearch");
  if (!input) return;
  const query = String(input.value || "").trim().toLowerCase();
  document.querySelectorAll("#tabs .tab").forEach((btn) => {
    const haystack = `${btn.textContent} ${btn.title || ""}`.toLowerCase();
    btn.classList.toggle("nav-away", !!query && !haystack.includes(query));
  });
  updateNavGroups();
}

function closeNav() {
  document.body.classList.remove("nav-open");
  const scrim = $("navScrim");
  if (scrim) scrim.hidden = true;
  const toggle = $("navToggle");
  if (toggle) toggle.setAttribute("aria-expanded", "false");
  const input = $("navSearch");
  if (input && input.value) {
    input.value = "";
    filterNav();
  }
}

function openNav() {
  if (!window.matchMedia("(max-width: 980px)").matches) return;
  document.body.classList.add("nav-open");
  const scrim = $("navScrim");
  if (scrim) scrim.hidden = false;
  const toggle = $("navToggle");
  if (toggle) toggle.setAttribute("aria-expanded", "true");
  filterNav();
}

function tabAllowed(name) {
  if (!S.adminPermissions) return true;
  const module = TAB_MODULES[name];
  return !module || S.adminPermissions.includes(module);
}

function firstAllowedTab() {
  const btn = [...document.querySelectorAll("#tabs .tab")].find((b) => !b.hidden);
  return btn ? btn.dataset.tab : "";
}

