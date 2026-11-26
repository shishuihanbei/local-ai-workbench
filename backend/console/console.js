/* 管理控制台（后端自带）：硬件探测、平台部署、模型清单与建议 */
const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "wb_token";
const S = { hw: null, models: null, install: null, timer: null, installing: false, localBusy: false, localEnabled: true, modelCategory: "all", cluster: null, clusterEditNode: 0, clusterEditPool: 0, clusterMembers: [] };
const MODEL_CATEGORY_ORDER = [
  ["text", "文字 / 对话"], ["code", "代码 / 编程"], ["vision", "多模态 / 视觉"],
  ["ocr", "OCR / 文档"], ["image", "绘画 / 图像"], ["video", "视频生成"],
  ["audio", "语音 / 音频"], ["embedding", "向量 / 检索"], ["rerank", "重排序"],
];

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }

async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.headers || {}) } };
  if (o.body && typeof o.body === "string") o.headers["Content-Type"] = "application/json";
  const tk = token();
  if (tk) o.headers["Authorization"] = "Bearer " + tk;
  const r = await fetch(path, o);
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
  const ct = r.headers.get("content-type") || "";
  const d = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((d && d.detail) || "请求失败");
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
  $("loginDesc").textContent = setup ? "首次启动，请设置管理员账号与密码" : "使用工作台管理员账号";
  $("confirmRow").hidden = !setup;
  $("loginBtn").textContent = setup ? "初始化并进入" : "进入";
  $("alert").textContent = "";
  if (setup) $("u").value = "admin";
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

/* ---------------------------------------------------------------- 硬件 */
function renderHardware(hw) {
  const gpuText = hw.gpus && hw.gpus.length
    ? hw.gpus.map((g) => `${g.name} · ${(g.vram_mb / 1024).toFixed(0)}GB`).join("；")
    : "未检测到 NVIDIA 显卡（CPU 推理）";
  const disk = (hw.disks || []).map((d) => `${d.path} 剩 ${gb(d.free_gb)}`).join("；");
  const cards = [
    ["CPU", hw.cpu, `${hw.cores} 线程 · 当前占用 ${hw.cpu_percent}%`],
    ["内存", `${gb(hw.ram_total_gb)}`, `可用 ${gb(hw.ram_free_gb)}`],
    ["显卡", gpuText, hw.gpus && hw.gpus.length ? (Math.max(...hw.gpus.map(g=>g.vram_mb))/1024 < 4 ? "显存较小，建议 CPU 推理" : "可开启 GPU 加速") : "无独显，使用 CPU 推理"],
    ["磁盘", disk || "—", `模型目录 ${hw.models_dir}`],
    ["系统", hw.os, `Python ${hw.python}`],
    ["llama.cpp", hw.llama.installed ? "已安装" : "未安装",
      hw.llama.installed ? (hw.llama.version || hw.llama.path) : "请在平台卡点“一键部署”"],
  ];
  $("hwCards").innerHTML = cards.map(([k, v, s]) => `
    <div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>
  `).join("");
}

/* ---------------------------------------------------------------- 安装 */
function renderInstall(st) {
  S.install = st;
  const llama = st.llama;
  $("installInfo").innerHTML = `
    <div class="status-line"><span class="dot ${llama.installed ? "on" : ""}"></span>
      <b>${llama.installed ? "llama.cpp 已就绪" : "本机未安装 llama.cpp"}</b></div>
    <div class="mono">${esc(llama.installed ? (llama.path + (llama.version ? " · " + llama.version : "")) : "安装后会写入 " + llama.llama_dir)}</div>
    <div class="mono">模型目录：${esc(st.models_dir)} ${st.models_dir_exists ? "（存在）" : "（不存在，会自动创建）"}</div>`;

  const canInstall = !llama.installed && st.supported;
  $("installBtn").hidden = !st.supported;
  $("installBtn").textContent = llama.installed ? "修复安装 llama.cpp" : "备用安装 llama.cpp";
  $("installBtn").disabled = !!st.install.running;
  $("installHint").textContent = st.install.running ? "安装进行中…"
    : llama.installed ? "已安装；正常请在平台卡点“一键部署”"
    : (st.supported ? "正常请用平台卡的“一键部署”；这里作为备用入口" : "当前系统需手动安装");

  $("depsRow").innerHTML = Object.entries(st.python_packages || {}).map(([k, ok]) =>
    `<span class="chip ${ok ? "ok" : "miss"}">${esc(k)} ${ok ? "已安装" : "缺失"}</span>`).join("")
    + `<span class="chip ${st.supported ? "ok" : "miss"}">${esc(st.platform)} ${st.supported ? "支持一键部署" : "仅手动"}</span>`;

  const pr = st.install;
  const showBar = pr.running || (pr.ok === false && pr.error) || pr.ok === true;
  $("installProgress").hidden = !showBar;
  $("installBar").style.width = (pr.pct || 0) + "%";
  $("installText").textContent = `${pr.step || ""} ${pr.msg || ""}`.trim();
}

let installPolling = false;

async function pollInstall() {
  if (installPolling) return;
  installPolling = true;
  try {
    const pr = await api("/api/system/install-progress");
    renderInstall({ ...S.install, install: pr });
    if (pr.running) { setTimeout(pollInstall, 1500); }
    else if (pr.ok) { await loadAll(); }
  } finally {
    installPolling = false;
  }
}

async function pollModelDownload(key) {
  for (let i = 0; i < 720; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    let p;
    try { p = await api(`/api/models/${encodeURIComponent(key)}/progress`); }
    catch (e) { continue; }
    await loadAll();
    if (!p || p.status === "running") continue;
    if (p.status === "interrupted") { uiToast("下载已中断，可点「继续下载」续传"); return; }
    if (p.status === "error" || p.error) { uiToast(`下载失败：${p.error || "网络中断"}`); return; }
    if (p.exists) { uiToast("下载完成，可以加载了"); return; }
    return;
  }
}

async function pollEngineInstall(key) {
  for (let i = 0; i < 900; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    let p;
    try { p = await api(`/api/engines/${encodeURIComponent(key)}/install-progress`); }
    catch (e) { continue; }
    const box = document.querySelector(`[data-engine-progress="${key}"]`);
    if (box) {
      box.hidden = false;
      const head = box.querySelector("span");
      const bar = box.querySelector(".engine-bar i");
      const log = box.querySelector(".engine-log");
      if (head) head.textContent = `${p.step || "安装中"} ${p.pct || 0}%`;
      if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(p.pct || 0)))}%`;
      if (log) log.textContent = p.msg || "";
    }
    if (!p || p.running) continue;
    await loadAll();
    if (p.error) uiToast(`安装失败：${p.error}`);
    else if (p.ok) uiToast(p.msg || "安装完成");
    return;
  }
}

/* ---------------------------------------------------------------- 模型 */
function statusBadge(m) {
  const d = m.download || {};
  if (d.state === "running") return `<span class="badge warn">下载中 ${m.pct || d.pct || 0}%</span>`;
  if (d.state === "error" && !m.downloaded) return `<span class="badge bad">下载失败</span>`;
  if (m.installable === false) {
    if (m.downloaded) return `<span class="badge good">已下载</span>`;
    if (d.state === "interrupted" || m.partial) return `<span class="badge warn">已中断${m.pct ? " " + m.pct + "%" : ""}</span>`;
    return m.engine_ready
      ? `<span class="badge ok">引擎就绪</span>`
      : `<span class="badge warn">需独立引擎</span>`;
  }
  if (m.available === false) return `<span class="badge off">本地已关闭</span>`;
  if (m.downloaded) return `<span class="badge good">已下载</span>`;
  if (d.state === "interrupted" || m.partial) return `<span class="badge warn">已中断 ${m.pct || 0}%</span>`;
  return `<span class="badge off">未下载</span>`;
}

function adviceBadge(a) {
  const lvl = a && a.level ? a.level : "unknown";
  const label = a ? a.label : "未知";
  return `<span class="badge ${esc(lvl)}">${esc(label)}</span>
          <div class="advice-text">${esc(a ? a.text : "下载后可评估")}</div>`;
}

function modelCategoryLabel(key) {
  const found = MODEL_CATEGORY_ORDER.find((x) => x[0] === key);
  return found ? found[1] : (key || "其他");
}

function renderModelFilters(items) {
  const box = $("modelFilters");
  if (!box) return;
  const counts = {};
  for (const m of items) counts[m.category || "text"] = (counts[m.category || "text"] || 0) + 1;
  const chips = [["all", "全部", items.length]].concat(
    MODEL_CATEGORY_ORDER.filter(([k]) => counts[k]).map(([k, label]) => [k, label, counts[k]]));
  box.innerHTML = chips.map(([key, label, n]) =>
    `<button class="model-filter ${S.modelCategory === key ? "active" : ""}" data-mcat="${esc(key)}">${esc(label)} <b>${n}</b></button>`).join("");
}

function renderModelRows() {
  const data = S.models || { items: [] };
  const items = data.items || [];
  if (!items.length) {
    $("modelRows").innerHTML = `<tr><td colspan="7" style="color:#6b7280">还没有模型清单</td></tr>`;
    return;
  }
  const filtered = S.modelCategory === "all"
    ? items
    : items.filter((m) => (m.category || "text") === S.modelCategory);
  if (!filtered.length) {
    $("modelRows").innerHTML = `<tr><td colspan="7" style="color:#6b7280">这个分类下还没有模型</td></tr>`;
    return;
  }
  const groups = S.modelCategory === "all"
    ? MODEL_CATEGORY_ORDER.map(([k, label]) => [k, label])
    : [[S.modelCategory, modelCategoryLabel(S.modelCategory)]];
  const html = [];
  for (const [cat, label] of groups) {
    const list = filtered.filter((m) => (m.category || "text") === cat);
    if (!list.length) continue;
    if (S.modelCategory === "all") {
      html.push(`<tr class="model-group"><td colspan="7"><span>${esc(label)}</span><em>${list.length} 个</em></td></tr>`);
    }
    for (const m of list) {
      const act = [];
      const dl = m.download || {};
      const running = dl.state === "running";
      const failed = dl.state === "error";
      if (m.installable === false) {
        if (m.engine_repo) {
          const tip = m.engine_ready
            ? `用 ${m.engine_recommend || "独立引擎"} 下载整仓库到模型目录`
            : `先在「部署」页安装 ${m.engine_recommend || "独立引擎"}，装好后才能下载`;
          const label = running
            ? `下载中…`
            : (m.downloaded ? "重新下载" : (failed ? "重试下载" : (m.partial ? "继续下载" : "下载")));
          act.push(`<button class="btn small" data-dl="${esc(m.key)}" ${(m.engine_ready && !running) ? "" : "disabled"} title="${esc(tip)}">${label}</button>`);
        }
        if (m.homepage) act.push(`<a class="btn small" href="${esc(m.homepage)}" target="_blank" rel="noreferrer">查看项目</a>`);
        else if (!m.engine_repo) act.push(`<span class="badge off">未接入</span>`);
      } else {
        if (running) act.push(`<button class="btn small" disabled>下载中…</button>`);
        else if (!m.downloaded) act.push(`<button class="btn small" data-dl="${esc(m.key)}">${failed ? "重试下载" : (m.partial ? "继续下载" : "下载")}</button>`);
        if (m.downloaded && !m.loaded) act.push(`<button class="btn small" data-load="${esc(m.key)}" title="${m.available === false ? "加载模型会重新开启本地部署" : ""}">${m.available === false ? "加载并开启" : "加载"}</button>`);
        if (m.loaded) act.push(`<span class="badge ok">使用中</span>`);
      }
      html.push(`<tr>
        <td><div class="name">${esc(m.label || m.key)}</div><div class="sub">${esc(m.key)}${m.filename ? " · " + esc(m.filename) : ""}</div></td>
        <td><span class="badge cat">${esc(m.category_label || modelCategoryLabel(m.category))}</span></td>
        <td><div>${esc(m.engine || "—")}</div>${m.installable === false ? `<div class="sub">推荐 ${esc(m.engine_recommend || "独立引擎")} · ${m.engine_ready ? "已安装" : "未安装"}</div>` : ""}</td>
        <td>${m.bytes ? mb(m.bytes) : (m.total_bytes ? "约 " + mb(m.total_bytes) : "—")}</td>
        <td>${statusBadge(m)}</td>
        <td>${adviceBadge(m.advice)}</td>
        <td class="right"><div class="row-actions">${act.join("")}</div></td>
      </tr>`);
    }
  }
  $("modelRows").innerHTML = html.join("");
}

function renderPlatforms(data) {
  const box = $("platformCards");
  if (!box) return;
  if (data) S.deployData = data;
  const d = S.deployData || {};
  if (!S.platformDirty) {
    S.platformSelected = (d.selected || []).slice();
    S.platformEndpoints = { ...(d.endpoints || {}) };
  }
  if (d.github_proxy && !S.platformDirty) S.platformProxy = d.github_proxy;
  const proxyEl = $("githubProxy");
  if (proxyEl && document.activeElement !== proxyEl) proxyEl.value = S.platformProxy || "auto";
  const items = d.platforms || S.platforms || [];
  S.platforms = items;
  const selected = new Set(S.platformSelected);
  box.innerHTML = items.map((p) => {
    const on = selected.has(p.key);
    const state = p.healthy
      ? `<span class="badge good">已连接</span>`
      : p.installed
        ? `<span class="badge warn">已安装</span>`
        : p.installable
          ? `<span class="badge off">可部署</span>`
          : `<span class="badge off">未安装</span>`;
    const urlValue = S.platformDirty
      ? (S.platformEndpoints[p.key] || p.base_url || "")
      : (p.base_url || "");
    const url = p.editable
      ? `<input class="platform-url" data-platform-url="${esc(p.key)}" value="${esc(urlValue)}" placeholder="http://127.0.0.1:端口">`
      : `<input class="platform-url" value="工作台管理（由本机启动）" disabled>`;
    const link = p.homepage
      ? `<a class="sub" href="${esc(p.homepage)}" target="_blank" rel="noreferrer">打开官网</a>`
      : "";
    const fit = p.suitability || { level: "unknown", label: "需确认", text: "" };
    const mm = p.multimodal ? `<span class="badge mm">${esc(p.multimodal)}</span>` : "";
    const types = (p.model_types || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("");
    const installedText = p.installed
      ? `已安装${p.version ? " · " + p.version : ""}${p.install_path ? " · " + p.install_path : ""}`
      : (p.installable ? "尚未安装，可一键部署" : "需要手动安装");
    const label = p.action_label || "一键部署";
    const disabled = p.deployable === false || (p.install && p.install.running);
    const action = p.key === "custom"
      ? `<button class="btn small" data-pdeploy="${esc(p.key)}">${esc(label)}</button>
         <button class="btn small ghost" data-custom-guide>接入说明</button>`
      : `<button class="btn small ${p.action === "install" ? "primary" : ""}" data-pdeploy="${esc(p.key)}" ${disabled ? "disabled" : ""}>${esc(label)}</button>`;
    return `<div class="platform-card ${on ? "on" : ""}">
      <div class="platform-head">
        <label><input type="checkbox" data-platform="${esc(p.key)}" ${on ? "checked" : ""}><b>${esc(p.name)}</b>${mm}</label>
        ${state}
      </div>
      <div class="platform-note">${esc(p.note || "")}</div>
      <div class="platform-detail">${esc(p.detail || "")} ${link}</div>
      <div class="platform-installed">${esc(installedText)}</div>
      <div class="platform-suit"><span class="badge ${esc(fit.level || "unknown")}">${esc(fit.label || "需确认")}</span><span>${esc(fit.text || "")}</span></div>
      <div class="platform-types">${types || `<span class="chip">未标注</span>`}</div>
      ${url}
      <div class="platform-actions">${action}</div>
      <div class="platform-progress" data-platform-progress="${esc(p.key)}" hidden>
        <div class="bar"><i data-platform-bar="${esc(p.key)}"></i></div>
        <div class="progress-text" data-platform-text="${esc(p.key)}"></div>
      </div>
    </div>`;
  }).join("");

  items.forEach((p) => {
    if (p.install && (p.install.finished_at || p.install.running)) renderPlatformProgress(p.key, p.install);
  });

  if (!S.platformSelected.length) {
    $("platformNote").textContent = "没有勾选平台；保存或开启时会自动使用默认 llama.cpp。";
  } else {
    const names = items.filter((p) => selected.has(p.key)).map((p) => p.name);
    $("platformNote").textContent = `已选择：${names.join("、")}。“保存选择”只保存勾选和地址；每张卡里的“一键部署”才会安装并启动。`;
  }
}

function platformSelection() {
  const checked = [...document.querySelectorAll("#platformCards [data-platform]:checked")].map((x) => x.dataset.platform);
  return checked.length ? checked : ["llama.cpp"];
}

function platformEndpointValues() {
  const out = { ...S.platformEndpoints };
  document.querySelectorAll("#platformCards [data-platform-url]").forEach((el) => {
    out[el.dataset.platformUrl] = el.value.trim();
  });
  return out;
}

function renderPlatformProgress(key, st) {
  const box = document.querySelector(`[data-platform-progress="${key}"]`);
  const bar = document.querySelector(`[data-platform-bar="${key}"]`);
  const text = document.querySelector(`[data-platform-text="${key}"]`);
  if (!box || !st) return;
  const hasState = st.running || st.finished_at || st.ok !== null;
  box.hidden = !hasState;
  if (!hasState) return;
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, st.pct || 0))}%`;
  if (text) {
    const skipped = st.skipped ? " · 已安装，跳过下载" : "";
    text.textContent = `${st.step || ""} ${st.msg || ""}${skipped}`.trim();
    text.className = "progress-text " + (st.ok === false ? "bad" : st.ok === true ? "good" : "");
  }
}

async function pollPlatform(key) {
  if (S.platformPolling[key]) return;
  S.platformPolling[key] = true;
  let last = null;
  try {
    for (;;) {
      const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/progress`);
      last = r.state || {};
      renderPlatformProgress(key, last);
      if (!last.running) break;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  } catch (e) {
    uiToast(e.message);
  } finally {
    S.platformPolling[key] = false;
  }
  if (last) {
    uiToast(`${last.ok ? "部署完成" : "部署失败"}：${last.msg || ""}`);
    if (last.ok && !S.platformDirty) {
      try {
        const d = await api("/api/system/local-deploy?scan=1");
        S.deployData = { ...(S.deployData || {}), ...d };
        renderPlatforms(S.deployData);
      } catch (_) {}
    }
    return last;
  }
  return null;
}

function renderLocalDeploy(data) {
  const on = data.local_enabled !== false;
  const srv = data.server || {};
  const installed = !!(data.hardware && data.hardware.llama_installed);
  S.localEnabled = on;
  const btn = $("localDeployBtn");
  if (!btn) return;
  btn.dataset.next = on ? "off" : "on";
  btn.textContent = on ? "关闭本地部署" : "开启本地部署";
  btn.className = on ? "btn danger" : "btn primary";
  btn.disabled = !!S.localBusy;

  const dot = $("localDeployDot");
  const badge = $("localDeployBadge");
  let title, desc, meta;
  if (on && srv.running && srv.healthy) {
    dot.className = "dot on"; badge.className = "badge good"; badge.textContent = "运行中";
    title = "本地部署已开启";
    desc = "用户端和 OpenAI 接口可以调用本地模型。关闭后本地模型会立即从可用列表移除，并拒绝本地模型请求。";
    meta = `模型 ${srv.model || "—"} · 端口 ${srv.port || 8080}${srv.external ? " · 外部进程" : ""}`;
  } else if (on && srv.running) {
    dot.className = "dot warn"; badge.className = "badge warn"; badge.textContent = "启动中";
    title = "本地部署已开启，服务正在启动";
    desc = "llama-server 进程已创建，正在等待模型加载完成。";
    meta = `模型 ${srv.model || "—"} · 端口 ${srv.port || 8080}`;
  } else if (on) {
    dot.className = "dot warn"; badge.className = "badge warn"; badge.textContent = "待运行";
    title = "本地部署已开启，模型未运行";
    desc = installed
      ? "开启状态已生效。请在模型清单里下载并加载一个模型，加载后用户端即可对话。"
      : "开启状态已生效，但本机还没有安装 llama.cpp，请先在上方平台卡点“一键部署”。";
    meta = installed ? `模型目录 ${data.models_dir || "—"}` : "缺少 llama.cpp";
  } else {
    dot.className = "dot"; badge.className = "badge off"; badge.textContent = "已关闭";
    title = "本地部署已关闭";
    desc = "用户端不会显示本地模型，OpenAI 接口也会拒绝本地模型请求；配置了第三方供应商时会自动改用云端。";
    meta = (srv.external || srv.healthy)
      ? "检测到 8080 端口仍有外部 llama-server 运行，工作台不会强制结束它。"
      : "已停止工作台持有的本地模型进程。";
  }
  $("localDeployTitle").textContent = title;
  $("localDeployDesc").textContent = desc;
  $("localDeployMeta").textContent = meta;
}

function renderModels(data) {
  S.models = data;
  const srv = data.server || {};
  const enabled = data.local_enabled !== false;
  const items = data.items || [];
  const ready = items.filter((m) => m.downloaded).length;
  $("modelHint").textContent = `本地${enabled ? "已开启" : "已关闭"} · 服务 ${srv.running ? "运行中" : "未运行"}${srv.model ? " · 当前 " + srv.model : ""} · ${items.length} 个模型 · 已下载 ${ready} · 单模型运行，点“加载”会切换当前模型`;
  renderModelFilters(items);
  renderModelRows();
  renderEngineSummary(items);
}

function renderEngineSummary(items) {
  const box = $("engineSummary");
  if (!box) return;
  const need = items.filter((m) => m.installable === false);
  if (!need.length) {
    box.innerHTML = `<div class="engine-empty">当前没有需要独立引擎的模型。</div>`;
    return;
  }
  const catalog = {};
  for (const e of ((S.models && S.models.engine_catalog) || [])) catalog[e.key] = e;
  const groups = new Map();
  for (const m of need) {
    const engine = m.engine || "未标注";
    if (!groups.has(engine)) groups.set(engine, []);
    groups.get(engine).push(m);
  }
  const rows = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-CN"));
  box.innerHTML = rows.map(([engine, list]) => {
    const rec = list.find((m) => m.engine_recommend) || {};
    const ready = list.some((m) => m.engine_ready);
    const info = catalog[rec.engine_recommend_key] || null;
    const hint = rec.engine_text || `需要 ${engine} 独立引擎`;
    let guide = "";
    if (info) {
      const p = info.progress || {};
      const running = !!p.running;
      let action = `<span class="badge ok">已安装</span>`;
      if (!info.installed && info.one_click) {
        action = `<button class="btn small" data-engine-install="${esc(info.key)}" ${running ? "disabled" : ""}>${running ? "安装中…" : "一键安装"}</button>`;
      }
      else if (!info.installed) {
        action = `<button class="btn small" disabled title="${esc(info.blocked || info.install)}">一键安装</button>`;
      }
      guide = `
        <div class="engine-links"><a href="${esc(info.site)}" target="_blank" rel="noreferrer">官网</a><a href="${esc(info.download)}" target="_blank" rel="noreferrer">下载地址</a></div>
        <div class="engine-cmd"><code>${esc(info.install)}</code><button class="btn tiny" data-copy-engine="${esc(info.key)}">复制</button></div>
        <div class="engine-note">${esc(info.note)}</div>
        ${info.blocked ? `<div class="engine-note warn">${esc(info.blocked)}</div>` : ""}
        <div class="engine-actions">${action}</div>
        <div class="engine-progress" data-engine-progress="${esc(info.key)}" ${running ? "" : "hidden"}>
          <span>${esc(p.step || "安装中")} ${p.pct || 0}%</span>
          <div class="engine-bar"><i style="width:${Math.max(0, Math.min(100, Number(p.pct || 0)))}%"></i></div>
          <div class="engine-log">${esc(p.msg || "")}</div>
        </div>`;
    }
    return `
    <div class="engine-item">
      <div class="engine-head"><b>${esc(engine)}</b><span>${list.length} 个模型</span></div>
      <div class="engine-rec ${ready ? "ok" : "warn"}">推荐：${esc(rec.engine_recommend || engine)} · ${ready ? "已安装" : "未安装，下载按钮不可用"}</div>
      <div class="engine-models">${list.map((m) => esc(m.label || m.key)).join(" · ")}</div>
      <div class="advice-text">${esc(hint)}</div>
      ${guide}
    </div>`;
  }).join("");
}

function renderService(hw, data) {
  const srv = data.server || {};
  const hardware = hw || {};
  $("svcRow").innerHTML = `
    <div class="svc"><h3>模型服务</h3><p>${srv.running ? "运行中" : "未运行"}${srv.external ? "（外部进程）" : ""} · 端口 ${esc(srv.port || 8080)}</p></div>
    <div class="svc"><h3>接口</h3><p><a href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a> · 健康检查 /api/health</p></div>
    <div class="svc"><h3>本机配置</h3><p>${esc(hardware.cpu || "")} · ${gb(hardware.ram_total_gb || 0)} 内存</p></div>
    <div class="svc"><h3>模型目录</h3><p class="mono">${esc(data.models_dir || (hw && hw.models_dir) || "")}</p></div>`;
}

/* ---------------------------------------------------------------- 加载 */
function renderDeployment(hw, models, deploy) {
  S.hw = hw;
  S.deployModels = models;
  S.lastDeployAt = Date.now();
  renderHardware(hw);
  renderInstall(hw.install);
  const localData = { ...hw, ...models, ...(deploy || {}),
    local_enabled: deploy ? deploy.enabled : models.local_enabled,
    hardware: models.hardware || hw,
    models_dir: models.models_dir || hw.models_dir };
  renderLocalDeploy(localData);
  renderService(hw, models);
  renderPlatforms(deploy || { platforms: [], selected: ["llama.cpp"], endpoints: {} });
  if (hw.install.install && hw.install.install.running) pollInstall();
}

function renderStorage(st) {
  if (!st) return;
  S.storage = st;
  if ($("storageModels")) $("storageModels").value = st.models_dir || "";
  if ($("storagePlatforms")) $("storagePlatforms").value = st.platforms_dir || "";
  const badge = $("storageBadge");
  if (badge) {
    badge.className = "badge good";
    badge.textContent = "已就绪";
  }
  if ($("storageHint")) {
    $("storageHint").textContent = `llama.cpp 安装位置：${st.llama_dir}${st.llama_dir_exists ? "（已存在）" : "（安装时自动创建）"}`;
  }
  if ($("storagePanel")) {
    $("storagePanel").dataset.defaults = JSON.stringify(st.defaults || {});
  }
}

async function loadStorage() {
  const st = await api("/api/system/storage");
  renderStorage(st);
}

async function saveStorage() {
  const models = ($("storageModels") && $("storageModels").value.trim()) || "";
  const platforms = ($("storagePlatforms") && $("storagePlatforms").value.trim()) || "";
  const btn = $("storageSave");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const st = await api("/api/system/storage", {
      method: "PUT",
      body: JSON.stringify({ models_dir: models, platforms_dir: platforms }),
    });
    renderStorage(st);
    if ($("storageMsg")) $("storageMsg").textContent = "已保存；正在运行的服务重启后会按新目录加载模型。";
    uiToast("存储位置已保存");
    btn.textContent = "已保存";
    setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
  } catch (e) {
    if ($("storageMsg")) $("storageMsg").textContent = e.message;
    uiToast(e.message);
    btn.textContent = "保存失败";
    setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
  }
}

async function loadDeployment() {
  const [hw, models, deploy, storage] = await Promise.all([
    api("/api/system/hardware"),
    api("/api/models"),
    api("/api/system/local-deploy"),
    api("/api/system/storage"),
  ]);
  renderDeployment(hw, models, deploy);
  renderStorage(storage);
}

/* ---------------------------------------------------------------- 开机自启 */
function renderAutostart(st) {
  const badge = $("autostartBadge");
  if (!badge || !st) return;
  const enabled = !!st.enabled;
  const supported = !!st.supported;
  badge.className = "badge " + (!supported ? "warn" : enabled ? "good" : "ok");
  badge.textContent = !supported ? (st.platform === "docker" ? "容器内无需设置" : "当前系统不支持")
    : enabled ? (st.stale ? "有旧启动项" : "已开启") : "未开启";
  const portEl = $("autostartPort");
  if (portEl) portEl.textContent = st.port ? String(st.port) : "—";
  const on = $("autostartOn");
  const off = $("autostartOff");
  if (on) on.hidden = !supported || (enabled && !st.stale);
  if (off) off.hidden = !enabled;
  if (on && !on.hidden) on.textContent = st.stale ? "重新写入当前目录" : "开启开机自启";
  const detail = $("autostartDetail");
  if (detail) {
    let text = st.message || "";
    if (st.path && supported && (enabled || st.stale)) text += ` 位置：${st.path}`;
    detail.textContent = text;
  }
}

async function loadAutostart() {
  try {
    renderAutostart(await api("/api/system/autostart"));
  } catch (e) { /* 接口异常不影响部署页其他内容 */ }
}

async function toggleAutostart(on) {
  const btn = $(on ? "autostartOn" : "autostartOff");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = on ? "正在写入…" : "正在关闭…"; }
  try {
    const st = await api("/api/system/autostart", { method: on ? "POST" : "DELETE" });
    renderAutostart(st);
    uiToast(st.message || (on ? "已开启开机自启" : "已关闭开机自启"), "good");
  } catch (e) {
    uiToast(e.message || "操作失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

/* ---------------------------------------------------------------- 桌面快捷方式 */
function renderShortcuts(st) {
  const badge = $("shortcutsBadge");
  if (!badge || !st) return;
  const supported = !!st.supported;
  const exists = (st.items || []).filter((x) => x.exists).length;
  badge.className = "badge " + (!supported ? "warn" : exists ? "good" : "ok");
  badge.textContent = !supported ? (st.platform === "docker" ? "容器内无桌面" : "当前系统不支持")
    : exists ? "已创建" : "未创建";
  const urls = st.urls || {};
  const frontUrl = $("shortcutFrontUrl");
  const consoleUrl = $("shortcutConsoleUrl");
  if (frontUrl) frontUrl.textContent = urls.front || "—";
  if (consoleUrl) consoleUrl.textContent = urls.console || "—";
  const frontLink = $("shortcutFrontLink");
  const consoleLink = $("shortcutConsoleLink");
  if (frontLink && urls.front) frontLink.href = urls.front;
  if (consoleLink && urls.console) consoleLink.href = urls.console;
  const lanEl = $("shortcutLan");
  if (lanEl) {
    if (st.lan_url) {
      lanEl.hidden = false;
      lanEl.textContent = `手机或别的电脑用这个地址：${st.lan_url}`;
    } else {
      lanEl.hidden = true;
    }
  }
  const createBtn = $("shortcutsCreate");
  const removeBtn = $("shortcutsRemove");
  if (createBtn) createBtn.hidden = !supported;
  if (removeBtn) removeBtn.hidden = !exists;
  renderShortcutMode(st, supported);
  const detail = $("shortcutsDetail");
  if (detail) {
    let text = st.message || "";
    if (supported && exists && st.desktop) text += ` 桌面目录：${st.desktop}`;
    detail.textContent = text;
  }
}

async function loadShortcuts() {
  try {
    renderShortcuts(await api("/api/system/shortcuts"));
  } catch (e) { /* 接口异常不影响部署页其他内容 */ }
}

function renderShortcutMode(st, supported) {
  const modeSel = $("shortcutMode");
  const lanSel = $("shortcutLanIp");
  const customInput = $("shortcutCustomUrl");
  const saveBtn = $("shortcutSaveMode");
  const mode = st.mode || "local";
  if (modeSel) modeSel.value = mode;
  if (saveBtn) saveBtn.hidden = !supported;
  if (lanSel) {
    const ips = st.lan_ips || [];
    const chosen = st.lan_ip || "";
    lanSel.innerHTML = "";
    const list = ips.length ? ips : (chosen ? [{ ip: chosen, iface: "" }] : []);
    for (const item of list) {
      const opt = document.createElement("option");
      opt.value = item.ip;
      opt.textContent = item.iface ? `${item.ip}（${item.iface}）` : item.ip;
      lanSel.appendChild(opt);
    }
    if (chosen) lanSel.value = chosen;
    lanSel.hidden = mode !== "lan" || !list.length;
  }
  if (customInput) {
    customInput.value = st.custom_url || "";
    customInput.hidden = mode !== "custom";
  }
}

function shortcutModePayload() {
  const modeSel = $("shortcutMode");
  const lanSel = $("shortcutLanIp");
  const customInput = $("shortcutCustomUrl");
  return {
    mode: modeSel ? modeSel.value : "local",
    lan_ip: lanSel ? lanSel.value : "",
    custom_url: customInput ? customInput.value.trim() : "",
  };
}

async function saveShortcutMode() {
  const btn = $("shortcutSaveMode");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "保存中…"; }
  try {
    const st = await api("/api/system/shortcuts/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(shortcutModePayload()),
    });
    renderShortcuts(st);
    uiToast("地址已保存，下次双击桌面图标生效", "good");
  } catch (e) {
    uiToast(e.message || "保存失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

function bindShortcutModeEvents() {
  const modeSel = $("shortcutMode");
  if (modeSel) {
    modeSel.addEventListener("change", () => {
      const mode = modeSel.value;
      const lanSel = $("shortcutLanIp");
      const customInput = $("shortcutCustomUrl");
      if (lanSel) lanSel.hidden = mode !== "lan" || !lanSel.options.length;
      if (customInput) {
        customInput.hidden = mode !== "custom";
        if (mode === "custom") customInput.focus();
      }
      const hintEl = $("shortcutModeHint");
      if (hintEl) {
        hintEl.textContent = mode === "lan"
          ? "双击后用局域网地址打开，同一内网的手机和别的电脑也能进；换网络后记得回来改。"
          : mode === "custom"
            ? "填穿透或反代后的完整地址（http:// 或 https://），例如 Cloudflare 隧道域名。"
            : "双击后只用本机 127.0.0.1 打开，不依赖网络。";
      }
    });
  }
}

async function createShortcuts() {  const btn = $("shortcutsCreate");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "正在创建…"; }
  try {
    const st = await api("/api/system/shortcuts", { method: "POST" });
    renderShortcuts(st);
    uiToast(st.message || "已创建桌面快捷方式", "good");
  } catch (e) {
    uiToast(e.message || "创建失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

async function removeShortcuts() {
  const btn = $("shortcutsRemove");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "正在删除…"; }
  try {
    const st = await api("/api/system/shortcuts", { method: "DELETE" });
    renderShortcuts(st);
    uiToast(st.message || "已删除桌面快捷方式", "good");
  } catch (e) {
    uiToast(e.message || "删除失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

async function loadModelsTab() {
  const models = await api("/api/models");
  renderModels(models);
  if (!S.timer) S.timer = setInterval(refreshLight, 3000);
}

async function loadAll() {
  await loadDeployment();
  await loadAutostart();
  await loadShortcuts();
  renderModels(S.deployModels);
  clearInterval(S.timer);
  S.timer = setInterval(refreshLight, 3000);
}

async function refreshLight() {
  try {
    if (S.tab === "models") {
      const m = await api("/api/models");
      renderModels(m);
    } else if (S.tab === "deploy" && Date.now() - (S.lastDeployAt || 0) > 8000) {
      await loadDeployment();
    }
  } catch (e) { /* 忽略轮询失败 */ }
}

/* ---------------------------------------------------------------- 事件 */
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button");
  if (!t) return;
  try {
    if (t.id === "clusterRefresh") {
      const res = await api("/api/admin/cluster/refresh", { method: "POST" });
      uiToast(`已检查 ${(res.items || []).length} 个节点`);
      await loadClusterPage();
      return;
    }
    if (t.id === "clusterNodeSave") { await clusterSaveNode(); return; }
    if (t.id === "clusterNodeProbe") { await clusterProbe(); return; }
    if (t.id === "clusterNodeCancel") { resetClusterNodeForm(); return; }
    if (t.id === "clusterPoolSave") { await clusterSavePool(); return; }
    if (t.id === "clusterPoolCancel") { resetClusterPoolForm(); return; }
    if (t.id === "clusterAddMember") {
      S.clusterMembers.push(clusterDefaultMember());
      renderClusterMembers();
      return;
    }
    if (t.id === "clusterCopyExample") {
      const text = $("clusterExample").textContent;
      try { await navigator.clipboard.writeText(text); uiToast("示例已复制"); }
      catch { uiToast("复制失败，请手动选择文本", "bad"); }
      return;
    }
    if (t.classList.contains("member-del")) {
      const idx = Number(t.dataset.memberDel);
      S.clusterMembers.splice(idx, 1);
      if (!S.clusterMembers.length) S.clusterMembers = [clusterDefaultMember()];
      renderClusterMembers();
      return;
    }
    if (t.dataset.clusterNodeEdit) {
      const node = (S.cluster.nodes || []).find((n) => n.id === Number(t.dataset.clusterNodeEdit));
      if (node) clusterFillNodeForm(node);
      return;
    }
    if (t.dataset.clusterNodeTest) {
      await api(`/api/admin/cluster/nodes/${t.dataset.clusterNodeTest}/test`, { method: "POST" });
      await loadClusterPage();
      uiToast("节点状态已更新");
      return;
    }
    if (t.dataset.clusterNodeDel) {
      if (!await confirmInline("删除这个节点？模型池里引用它的成员会一起失效。", "删除")) return;
      await api(`/api/admin/cluster/nodes/${t.dataset.clusterNodeDel}`, { method: "DELETE" });
      await loadClusterPage();
      uiToast("节点已删除");
      return;
    }
    if (t.dataset.clusterPoolEdit) {
      const pool = (S.cluster.pools || []).find((p) => p.id === Number(t.dataset.clusterPoolEdit));
      if (pool) clusterFillPoolForm(pool);
      return;
    }
    if (t.dataset.clusterPoolDel) {
      if (!await confirmInline("删除这个模型池？节点本身不会被删除。", "删除")) return;
      await api(`/api/admin/cluster/pools/${t.dataset.clusterPoolDel}`, { method: "DELETE" });
      await loadClusterPage();
      uiToast("模型池已删除");
      return;
    }
    if (t.classList.contains("usage-more")) { toggleGuideDetail(t); return; }
    if (t.hasAttribute("data-custom-guide")) {
      const panel = $("customOpenaiGuide");
      const body = $("customGuideBody");
      const toggle = $("customGuideToggle");
      if (body) body.hidden = false;
      if (panel) panel.hidden = false;
      if (toggle) { toggle.textContent = "关闭说明"; toggle.setAttribute("aria-expanded", "true"); }
      if (panel) panel.scrollIntoView({ block: "start" });
      return;
    }
    if (t.id === "customGuideToggle") {
      const panel = $("customOpenaiGuide");
      if (panel) panel.hidden = true;
      return;
    }
    if (t.dataset && t.dataset.mcat) {
      S.modelCategory = t.dataset.mcat;
      const items = (S.models && S.models.items) || [];
      renderModelFilters(items);
      renderModelRows();
      return;
    }
    if (t.id === "refreshBtn") {
      if (!token()) { showLogin(); return; }
      const btn = $("refreshBtn");
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = "刷新中…";
      const r = await refreshCurrent();
      if (r.ok) {
        const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        btn.textContent = `已刷新 ${time}`;
        setTimeout(() => { btn.textContent = "刷新数据"; btn.disabled = false; }, 1800);
      } else {
        btn.textContent = "刷新失败";
        uiToast(`刷新失败：${r.error || "请检查后端连接"}`);
        setTimeout(() => { btn.textContent = "刷新数据"; btn.disabled = false; }, 1800);
      }
    }
    else if (t.id === "logoutBtn") {
      const tk = token();
      localStorage.removeItem(TOKEN_KEY);
      showLogin();
      if (tk) {
        fetch("/api/auth/logout", { method: "POST", headers: { Authorization: "Bearer " + tk } }).catch(() => {});
      }
    }
    else if (t.id === "installBtn") {
      t.disabled = true;
      const r = await api("/api/system/install-llama" + (S.install && S.install.llama.installed ? "?force=true" : ""), { method: "POST" });
      if (!r.ok) { $("installText").textContent = r.msg || "无法开始安装"; t.disabled = false; return; }
      pollInstall();
    }
    else if (t.id === "refreshModels") {
      const btn = t;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "更新中…";
      try {
        const r = await api("/api/models/refresh", { method: "POST" });
        await loadModelsTab();
        btn.textContent = r.added
          ? (r.discovered ? `补充 ${r.added} · 目录 ${r.discovered}` : `已补充 ${r.added} 个`)
          : "已是最新";
      } catch (e) {
        btn.textContent = "更新失败";
        uiToast(e.message);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      return;
    }
    else if (t.id === "autostartOn") { await toggleAutostart(true); return; }
    else if (t.id === "autostartOff") { await toggleAutostart(false); return; }
    else if (t.id === "shortcutsCreate") { await createShortcuts(); return; }
    else if (t.id === "shortcutsRemove") { await removeShortcuts(); return; }
    else if (t.id === "shortcutSaveMode") { await saveShortcutMode(); return; }
    else if (t.id === "refreshPlatforms") {
      const btn = t;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "更新中…";
      try {
        const r = await api("/api/system/local-deploy?scan=1");
        S.deployData = { ...(S.deployData || {}), ...r };
        renderPlatforms(S.deployData);
        const found = (r.platforms || []).filter((p) => p.healthy).length;
        btn.textContent = `已更新 · ${found} 个可用`;
      } catch (e) {
        btn.textContent = "更新失败";
        uiToast(e.message);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      return;
    }
    else if (t.id === "networkCheck") {
      const btn = t;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "诊断中…";
      try {
        const r = await api("/api/system/network-check");
        const rows = (r.results || []).map((x) =>
          `<span class="network-item ${x.ok ? "ok" : "bad"}">${esc(x.name)} ${x.ok ? (x.ms + "ms") : "不可用"}</span>`).join("");
        $("networkHint").innerHTML = `网络：${esc(r.msg || "")}<div class="network-list">${rows}</div>`;
        uiToast(r.msg || "网络诊断完成");
        btn.textContent = r.ok ? "网络可用" : "网络异常";
      } catch (e) {
        btn.textContent = "诊断失败";
        uiToast(e.message);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 2200);
      return;
    }
    else if (t.id === "deploySelected") {
      const keys = platformSelection();
      const byKey = Object.fromEntries((S.platforms || []).map((p) => [p.key, p]));
      const usable = keys.filter((k) => byKey[k] && byKey[k].deployable !== false && byKey[k].action !== "running");
      if (!usable.length) { uiToast("已选平台都已运行，或本机不支持自动部署"); return; }
      t.disabled = true;
      t.textContent = "部署中…";
      const started = [];
      for (let i = 0; i < usable.length; i++) {
        const key = usable[i];
        t.textContent = `部署中 ${i + 1}/${usable.length}`;
        try {
          const endpoint = (platformEndpointValues()[key] || "").trim();
          const qs = endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : "";
          const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/deploy${qs}`, { method: "POST" });
          if (r.ok) { started.push(key); await pollPlatform(key); }
          else uiToast(`${byKey[key].name}：${r.msg || "无法开始"}`);
        } catch (e) { uiToast(`${byKey[key].name}：${e.message}`); }
      }
      t.textContent = `已开始 ${started.length} 个`;
      setTimeout(() => { t.textContent = "部署已选平台"; t.disabled = false; }, 1800);
      return;
    }
    else if (t.dataset.pdeploy) {
      const key = t.dataset.pdeploy;
      const p = (S.platforms || []).find((x) => x.key === key) || {};
      if (p.deployable === false || S.platformPolling[key]) return;
      t.disabled = true;
      const old = t.textContent;
      t.textContent = p.key === "custom" ? "测试中…" : "部署中…";
      try {
        const endpoint = (platformEndpointValues()[key] || "").trim();
        const qs = endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : "";
        const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/deploy${qs}`, { method: "POST" });
        if (!r.ok) {
          uiToast(r.msg || "无法开始部署");
          t.textContent = old;
          t.disabled = false;
          return;
        }
        await pollPlatform(key);
        const btn = document.querySelector(`[data-pdeploy="${key}"]`);
        if (btn && /部署中|测试中/.test(btn.textContent)) {
          btn.textContent = old;
          btn.disabled = false;
        }
      } catch (e) {
        uiToast(e.message);
        t.textContent = old;
        t.disabled = false;
      }
      return;
    }
    else if (t.id === "storageSave") {
      await saveStorage();
      return;
    }
    else if (t.id === "storageDefault") {
      const defaults = (S.storage && S.storage.defaults) || {};
      if ($("storageModels")) $("storageModels").value = defaults.models_dir || "";
      if ($("storagePlatforms")) $("storagePlatforms").value = defaults.platforms_dir || "";
      if ($("storageMsg")) $("storageMsg").textContent = "已填入程序根目录下的默认位置，点「保存位置」生效。";
      return;
    }
    else if (t.id === "savePlatforms") {
      const btn = t;
      btn.disabled = true;
      const old = btn.textContent;
      btn.textContent = "保存中…";
      try {
        const selected = platformSelection();
        const proxy = ($("githubProxy") && $("githubProxy").value.trim()) || "auto";
        S.platformProxy = proxy;
        const r = await api("/api/system/local-platforms", {
          method: "PUT",
          body: JSON.stringify({ platforms: selected, endpoints: platformEndpointValues(), github_proxy: proxy }),
        });
        S.platformSelected = r.selected || selected;
        S.platformEndpoints = r.endpoints || S.platformEndpoints;
        S.platformProxy = r.github_proxy || S.platformProxy;
        S.platformDirty = false;
        S.deployData = { ...(S.deployData || {}), ...r };
        renderPlatforms(S.deployData);
        btn.textContent = "已保存";
        setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      } catch (e) {
        btn.textContent = "保存失败";
        uiToast(e.message);
        setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      }
      return;
    }
    else if (t.id === "localDeployBtn") {
      const enable = t.dataset.next === "on";
      const selected = platformSelection();
      if (!enable && !(await confirmInline("确定关闭本地部署？关闭后用户端和 API 将不能使用本地模型。", "关闭部署"))) return;
      S.platformSelected = selected;
      S.platformEndpoints = platformEndpointValues();
      S.localBusy = true;
      t.disabled = true;
      t.textContent = enable ? "正在开启…" : "正在关闭…";
      try {
        const r = await api("/api/system/local-deploy", {
          method: "POST",
          body: JSON.stringify({ enabled: enable, platforms: selected, endpoints: S.platformEndpoints, github_proxy: S.platformProxy }),
        });
        if (!r.ok || (enable && !r.started) || (r.msg || "").startsWith("外部")) {
          uiToast(r.msg || (r.ok ? "操作已完成" : "操作失败"));
        }
        S.platformDirty = false;
      } finally {
        S.localBusy = false;
        await loadAll();
      }
    }
    else if (t.dataset.engineInstall) {
      t.disabled = true;
      t.textContent = "安装中…";
      const engineKey = t.dataset.engineInstall;
      const r = await api(`/api/engines/${engineKey}/install`, { method: "POST" });
      if (r && r.msg) uiToast(r.msg);
      await loadAll();
      pollEngineInstall(engineKey);
    }
    else if (t.dataset.copyEngine) {
      const info = ((S.models && S.models.engine_catalog) || []).find((e) => e.key === t.dataset.copyEngine);
      if (!info) throw new Error("没有找到安装命令");
      try {
        await navigator.clipboard.writeText(info.install);
        uiToast("安装命令已复制");
      } catch (e) {
        uiToast("复制失败，请手动选中命令复制");
      }
    }
    else if (t.dataset.dl) {
      const dlKey = t.dataset.dl;
      const item = ((S.models && S.models.items) || []).find((m) => m.key === dlKey);
      t.disabled = true;
      t.textContent = "下载中…";
      // 乐观更新：这一行立刻变成「下载中」，不用等整表刷新（否则点了像没反应）
      if (item) {
        item.download = { ...(item.download || {}), state: "running", pct: item.pct || 0 };
        renderModelRows();
      }
      try {
        const r = await api(`/api/models/${dlKey}/download`, { method: "POST" });
        if (r && r.msg) uiToast(r.msg);
      } finally {
        await loadAll();
      }
      pollModelDownload(dlKey);
    }
    else if (t.dataset.load) {
      t.disabled = true;
      await api("/api/models/load", { method: "POST", body: JSON.stringify({ key: t.dataset.load }) });
      await loadAll();
    }
  } catch (e) { uiToast(e.message); t.disabled = false; }
});

$("loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("loginBtn");
  if (btn.disabled) return;
  $("alert").textContent = "";
  try {
    const path = S.setupMode ? "/api/auth/setup" : "/api/auth/login";
    if (S.setupMode) {
      if ($("p").value.length < 6) throw new Error("密码至少 6 位");
      if ($("p").value !== $("p2").value) throw new Error("两次输入的密码不一致");
    }
    btn.disabled = true;
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("u").value.trim(), password: $("p").value }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || (S.setupMode ? "初始化失败" : "登录失败"));
    if (d.access_token) localStorage.setItem(TOKEN_KEY, d.access_token);
    S.setupMode = false;
    const me = await api("/api/auth/me");
    applyAdminPermissions(me.user);
    applyBranding(S.branding, me.user.username);
    showMain();
    try {
      const la = await api("/api/system/local-access");
      S.localClient = !!la.local;
    } catch { S.localClient = true; }
    await switchTab(initialTab());
  } catch (e) { $("alert").textContent = e.message; }
  finally { btn.disabled = false; }
});

(async function boot() {
  try {
    const st = await (await fetch("/api/auth/state")).json();
    S.branding = st.branding || S.branding;
    applyBranding(S.branding, "");
    if (!st.initialized) { showLogin(true); return; }
  } catch {}
  if (!token()) { showLogin(); return; }
  try {
    const me = await api("/api/auth/me");
    applyAdminPermissions(me.user);
    applyBranding(S.branding, me.user.username);
    showMain();
    try {
      const la = await api("/api/system/local-access");
      S.localClient = !!la.local;
    } catch { S.localClient = true; }
    await switchTab(initialTab());
  } catch { showLogin(); }
})();

/* ================================================================ 管理页签（M0–M2） */
S.tab = "overview";
S.reqPage = 1;
S.reqTotal = 0;
S.providers = [];
S.routeProviders = [];
S.routeModels = [];
S.routeLocalEnabled = true;
S.users = [];
S.modelOptions = [];
S.editingUser = null;
S.frontendUrl = "";
S.networkLoaded = false;
S.tunnelTimer = null;
S.apiCtx = null;
S.apiKeys = [];
S.apiIsAdmin = false;
S.platforms = [];
S.platformSelected = ["llama.cpp"];
S.platformEndpoints = {};
S.platformProxy = "auto";
S.platformDirty = false;
S.platformPolling = {};
S.platformBatch = false;
S.deployData = null;
S.lastDeployAt = 0;
S.backups = [];
S.shares = [];
S.kb = null;
S.kbPendingDelete = null;
S.libRestoreFile = null;
S.kbSearchItems = [];
S.library = null;
S.libPendingDelete = null;
S.kbRestoreFile = null;
S.memory = null;
S.memoryPendingDelete = null;
S.websearch = null;
S.parseItems = [];
S.parsePage = 1;
S.parseTotal = 0;
S.parseStats = {};
S.parseBusy = false;
S.parseJobId = "";
S.parseJobTimer = null;
S.parsePreviewId = 0;
S.parsePreviewName = "";
S.promptData = null;
S.promptDetail = null;
S.promptWb = null;
S.promptKey = "";
S.promptFilter = "all";
S.promptSearch = "";
S.promptDirty = false;
S.promptLoadedAt = 0;
S.frontData = null;
S.frontDraft = null;
S.frontDirty = false;
S.frontFilter = "all";
S.frontQuery = "";
S.frontIconTarget = "";
S.frontIconKey = "";
S.frontIconId = 0;
S.frontIconTone = "blue";
S.frontIcons = [];
S.frontPresets = [];

const TITLES = {
  overview: ["调用观测 · 混合路由 · 本地部署", "概览"],
  org: ["前端页面 · Logo · 备案 · 安全水印", "外观"],
  moderation: ["敏感词 · 输入输出检测 · 命中记录", "内容安全"],
  agents: ["人格 · 提示词 · 推荐模型 · 可见范围", "智能体"],
  partners: ["账号 · 用户组 · 管理员角色 · 所属小队", "伙伴"],
  squads: ["成员 · 智能体 · 共享对话", "小队"],
  announcements: ["全员公告 · 置顶 · 启停", "公告"],
  tickets: ["用户提交 · 分派 · 回复 · 关闭", "服务台"],
  "conv-shares": ["对话快照 · 公开 / 小队 · 撤销", "对话分享"],
  requests: ["请求级事实表 · Token / 延迟 / 成本", "调用记录"],
  providers: ["第三方 API 接入", "供应商"],
  routes: ["本地优先 / 云端优先 / 手动", "路由"],
  users: ["账号 · 模型权限 · 会话", "用户"],
  skills: ["自定义技能 · 提示词注入 · 用户端菜单", "技能"],
  prompts: ["核心提示词 · 技能 · 功能规则 · 热更新与版本", "提示词"],
  front: ["前台功能 · 显示开关 · 图标自定义 · 保存即生效", "前台功能"],
  auth: ["QQ / 微信 / 手机号 / 邮箱配置与教程", "登录方式"],
  api: ["API Key · 内网/外网地址 · 调用说明", "API"],
  network: ["本地前端 · 内网穿透 · 公网访问", "网络"],
  websearch: ["联网检索 · 总开关 · 来源与抓取测试", "联网"],
  parsing: ["附件 OCR · 重新解析 · 解析状态", "解析"],
  deploy: ["硬件评估 · 单平台部署 · 安装跳过", "部署"],
  cluster: ["局域网多机 · 同模型副本池 · 统一入口", "算力"],
  models: ["本地模型目录 · 分类 · 下载与加载", "模型"],
  kb: ["本地文档 · 自动切块 · 检索增强", "知识库"],
  library: ["资料库 · 总库/个人库 · 重复选用", "资料库"],
  memory: ["长期记忆 · 默认关闭 · 按账号隔离", "长期记忆"],
  backup: ["备份 · 整机迁移 · 恢复", "备份迁移"],
  audit: ["管理员操作 · 全量留痕 · 只读", "审计日志"],
  database: ["SQLite 主库 · 外部 MySQL/PG · 一键外迁", "数据库中心"],
  share: ["干净程序包 · 对方重建自己的数据", "网站分享"],
};

function tabNameFromHash() {
  const name = location.hash.replace(/^#/, "");
  return TITLES[name] ? name : "";
}

function initialTab() {
  return tabNameFromHash() || "overview";
}

function rememberTab(name) {
  const hash = "#" + name;
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

const PAGE_TUTORIALS = {
  overview: {
    lead: `概览页是控制台的“体检报告”，固定展示最近 24 小时的调用事实。它不负责改配置，只回答三个问题：量正常吗、钱花在哪、哪里变慢。`,
    cards: [
      ["看整体", "顶部卡片给出调用次数、Token、成本、错误率、首字 P50/P95、总耗时 P50/P95。"],
      ["看趋势", "逐小时柱状图展示 24 小时分布；突然的尖峰或空档，通常对应批量任务、故障或服务重启。"],
      ["看结构", "模型用量表按调用次数排序，能看出哪个模型最忙、成本最高、首字最慢。"],
    ],
    steps: [
      `进页后先等数据加载完，重点看“错误率”和“首字 P50 / P95”两行，不要只盯总调用量。`,
      `把逐小时柱子和平时对比：某一小时特别高、特别低，或整段空白，先记下时段。`,
      `在模型用量表里找“调用多但首字慢”“成本高但用得少”的模型，判断是否要换小模型或改路由。`,
      `需要定位具体失败请求时，点开「调用记录」，按刚才的时段、模型或状态筛选。`,
      `改完路由或模型后再回来看同一时段，确认错误率和延迟确实下降。`,
    ],
    example: {
      title: `案例：晚上突然变慢`,
      text: `晚上 8 点用户反馈回复很慢，概览显示错误率不高，但首字 P95 从 1.2 秒涨到 9 秒。`,
      steps: [
        `看逐小时图，发现 20:00 这一小时明显变高。`,
        `看模型用量，发现 32B 模型平均首字 8 秒，而调用量主要来自它。`,
        `把日常对话切到 7B 模型，长文任务再走云端。`,
        `第二天同一时段复查，首字 P95 回到 2 秒以内。`,
      ],
    },
    note: `概览只做汇总；单次失败原因、完整 Prompt 和路由决策要到「调用记录」看。成本按供应商单价估算，本地模型通常不产生云端费用。`,
  },

  requests: {
    lead: `调用记录是请求级事实表，每一次模型调用都会留一行。排查“为什么慢、为什么错、走了本地还是云端”时，从这一页开始。`,
    cards: [
      ["筛选", "关键词、模型、状态、来源可以组合；状态分为 ok、error、stopped。"],
      ["明细", "点一行展开 Token、首字、总耗时、成本、错误和路由决策。"],
      ["翻页", "默认按时间倒序；更早的记录用上一页 / 下一页查。"],
    ],
    steps: [
      `先输入你记得的片段：Prompt 里的词、trace_id、错误文字。搜不到就清空关键词，改用条件筛选。`,
      `排查故障时先筛“状态 = error”，再看“来源 = local / cloud”，快速判断是本地服务还是第三方接口。`,
      `点进一行看明细，重点看错误信息、TTFT、总耗时、Token 和当时选中的模型。`,
      `需要给开发者复现时，复制 trace_id；它比截图更准确。`,
      `确认是某供应商的问题后，去「供应商」测试或换 Key；确认是本地模型问题，去「模型」换模型。`,
    ],
    example: {
      title: `案例：连续 502`,
      text: `前端连续报错，调用记录里出现多条 error，用户只说“AI 挂了”。`,
      steps: [
        `筛状态 error、来源 cloud，发现失败集中在同一个供应商。`,
        `打开一条明细，错误是上游 502 / 超时，本地模型没有报错。`,
        `到「供应商」点测试，确认 Key 和地址；必要时先换备用供应商。`,
        `把路由临时切到 local_first，先恢复对话，再处理云端账号问题。`,
      ],
    },
    note: `Prompt 可能包含手机号、地址等隐私，发截图前先脱敏。调用记录用于排查，不要把它当成计费账单。`,
  },

  providers: {
    lead: `供应商页负责接入第三方 OpenAI 兼容接口。你可以用预设快速填好常见平台，也可以接完全自定义的服务；Key 加密落库，列表只显示掩码。`,
    cards: [
      ["预设", "选择常见供应商后自动填名称、Base URL 和推荐模型，字段仍可改。"],
      ["自定义", "任何 OpenAI 兼容接口都能接：填地址、Key、模型列表和价格即可。"],
      ["加密", "Key 以 AES-256-GCM 保存，页面不回显原文；删除或轮换要及时。"],
    ],
    steps: [
      `先在预设下拉框选平台；没有你的平台就选“自定义”，不要随便套用别人的地址。`,
      `填 Base URL，通常以 <code>/v1</code> 结尾；填 API Key，粘贴后不要再次截图。`,
      `填模型列表（逗号分隔）和输入/输出价格；价格用于成本统计，不确定可以先留空。`,
      `点“添加”，在列表里点测试，确认能连通；失败先查地址、Key 和账户余额。`,
      `到「路由」把供应商绑定到策略，模型才会真正走云端；不绑定只算登记。`,
    ],
    example: {
      title: `案例：接入 DeepSeek 作为云端备用`,
      text: `本地 7B 够日常，但长文和复杂任务想走云端。`,
      steps: [
        `供应商页选 DeepSeek 预设，确认 Base URL 和推荐模型。`,
        `粘贴 Key，填模型列表和价格，点添加，再点测试。`,
        `到「路由」建“云端备用”，策略选 cloud_first，供应商选 DeepSeek。`,
        `前端发一条长文，回调用记录确认来源是 cloud。`,
      ],
    },
    note: `Key 只显示掩码，轮换时建议先新增一条新 Key，测试通过后再删旧 Key。删除供应商前先检查有没有路由还在用它。`,
  },

  routes: {
    lead: `路由决定一次请求优先走本地还是云端，以及本地模型名怎么映射到云端模型名。日常只需要一两条规则，不要一上来建很多。`,
    cards: [
      ["local_first", "本地模型优先，适合日常对话、隐私数据和低延迟场景。"],
      ["cloud_first", "云端优先，适合本地显存不够、长文或需要更强模型的任务。"],
      ["manual", "手动指定供应商，适合固定走某个云端模型的特殊任务。"],
    ],
    steps: [
      `给路由起一个能看懂的名字，例如“日常本地优先”“长文走云端”。`,
      `选策略：先用 local_first 跑通，再按需要加 cloud_first 或 manual。`,
      `供应商下拉分「本地」和「云端」：本地不需要映射；选云端后点“自动匹配”，会按 deepseek / qwen / llama 等家族填映射。`,
      `自动匹配只填空缺能力，没匹配上的会提示；可以手动补 JSON 后再保存。`,
      `保存后到前端切模型发一条消息，再回「调用记录」看来源是 local 还是 cloud。`,
      `如果请求没按预期走，先检查供应商是否绑定、映射 JSON 是否合法、模型名是否存在。`,
    ],
    example: {
      title: `案例：把本地 DeepSeek 7B 映射到云端 deepseek-chat`,
      text: `前端模型下拉里本地模型的值是 7b；云端供应商 DeepSeek 的模型列表填了 deepseek-chat, deepseek-reasoner。`,
      steps: [
        `供应商页把模型列表写成 deepseek-chat, deepseek-reasoner，并保存 Key。`,
        `路由页新建“7B走云端”，策略选 cloud_first，供应商选 DeepSeek。`,
        `点“自动匹配”：本地 DeepSeek-R1 7B 的家族是 deepseek，会自动生成 {"7b":"deepseek-chat"}。`,
        `想固定用推理模型就手动改成 {"7b":"deepseek-reasoner"}，保存路由。`,
        `回前端选 7b 发消息；调用记录里 provider 是 DeepSeek，model 是 deepseek-chat（或 reasoner）。`,
      ],
    },
    note: `模型映射必须是合法 JSON：键是前端本地模型的 key（不是显示名称），值是供应商模型列表里的精确名字。自动匹配只按模型家族猜，猜错时手动改值即可。路由只是选择规则，供应商本身的地址、Key、模型名仍要正确。`,
  },

  users: {
    lead: `用户页管理账号、角色和每个账号能调用哪些模型。普通用户打开前端时，模型下拉只会出现被允许的模型；管理员自动拥有全部。`,
    cards: [
      ["按人授权", "每个用户单独勾选模型，适合家人、同事或不同项目组。"],
      ["自助注册", "开启后登录页出现“注册”；新用户默认只拿本地模型。"],
      ["停用不删除", "禁用账号会立即阻止登录，但历史会话和记录保留。"],
    ],
    steps: [
      `点“新建用户”，用户名 2–32 位；编辑用户时密码留空表示不修改。`,
      `选角色：普通用户按需分配模型；管理员自动拥有全部模型，谨慎授予。`,
      `在“可调用模型”里逐个勾选，或勾“全部模型（含以后新增）”。`,
      `保存后让用户用自己的账号登录前端，确认模型下拉只出现授权项。`,
      `人员离开时优先“禁用”，确认不再需要后再删除；删除会带走该用户的会话和记录。`,
    ],
    example: {
      title: `案例：给设计同事只开视觉模型`,
      text: `设计同事只需要看图和多模态，不需要代码和视频模型。`,
      steps: [
        `新建普通用户，设置密码。`,
        `只勾选视觉 / 多模态和必要的文字模型，不勾“全部模型”。`,
        `让对方登录前端，确认下拉里没有未授权模型。`,
        `后续新增模型不会自动出现，需要管理员再回来补勾。`,
      ],
    },
    note: `“全部模型”包含以后新增的模型；只想给固定范围就不要勾。普通用户看不到未下载的本地模型，也看不到未授权的云端模型。`,
  },

  auth: {
    lead: `登录方式页配置用户名密码之外的登录入口。默认用户名密码始终建议保留；QQ、微信、手机号、邮箱按需开启，未配置完整时不会出现在登录页。`,
    cards: [
      ["保底登录", "用户名密码是最后的入口，第三方出问题时还能进后台。"],
      ["供应商", "常见第三方供应商有预设，也可以自定义授权地址和回调地址。"],
      ["测试", "保存后先在本机测试发送或跳转，再去用户端实测登录。"],
    ],
    steps: [
      `先确认用户名密码可用，不要为了“统一登录”把它关掉。`,
      `选择要开启的方式，再选供应商；没有你的服务商就选“自定义”。`,
      `按供应商后台填 App ID、App Secret、回调地址等；回调地址必须和后台配置完全一致。`,
      `手机号 / 邮箱还要填短信或 SMTP 参数，保存后点测试，确认能发出验证码或邮件。`,
      `用无痕窗口走一遍完整登录；失败先看回调地址、端口、防火墙和供应商后台的启用状态。`,
    ],
    example: {
      title: `案例：开启企业邮箱验证码登录`,
      text: `公司希望同事用邮箱收验证码登录，不再单独发账号。`,
      steps: [
        `邮箱登录选企业 SMTP 或自定义 SMTP，填服务器、端口、账号、密码/授权码。`,
        `保存后点发送测试，确认收件箱能收到。`,
        `开启邮箱登录，用无痕窗口输入邮箱并获取验证码。`,
        `验证码登录成功后，保留用户名密码作为管理员保底入口。`,
      ],
    },
    note: `App Secret、SMTP 密码只保存在本机，页面不回显；不要发到群里。第三方登录首次使用只有在允许注册且已有管理员时才会自动建号。`,
  },

  api: {
    lead: `API 页把工作台的模型能力暴露成 OpenAI 兼容接口，给手机 App、脚本、插件或其他程序用。核心是三件事：生成 Key、选对地址、填对模型 ID。`,
    cards: [
      ["Key", "Key 等同密码，只显示一次；继承所属用户的模型权限。"],
      ["地址", "本机、内网、外网三种地址，按调用程序所在的位置选。"],
      ["示例", "curl 和 Python 示例可直接改 Key 和模型 ID 使用。"],
    ],
    steps: [
      `给 Key 起一个能分清用途的名字，例如“手机”“脚本”“测试”，点生成后立即复制保存。`,
      `看页面顶部的范围提示：本机程序用本机地址；同一 Wi-Fi 用内网地址；人在外面用外网地址。`,
      `复制 curl 或 Python 示例，替换 Key 和模型 ID，先发一条最短消息，确认返回 200。`,
      `需要外网时，先去「网络」开启穿透，目标选“模型 API”，地址出现后再复制。`,
      `怀疑 Key 泄露时立即撤销，重新生成；不要试图在客户端里“隐藏”一个已经泄露的 Key。`,
    ],
    example: {
      title: `案例：手机 App 在外网调用`,
      text: `手机不在同一 Wi-Fi，仍要调用工作台的模型。`,
      steps: [
        `API 页生成一个“手机”Key，复制保存。`,
        `到「网络」开启免费穿透，目标选“模型 API”。`,
        `复制页面给出的外网地址，拼成 <code>/v1/chat/completions</code>。`,
        `在手机端填 Base URL 和 Key，模型 ID 从“当前可用模型”里选。`,
        `先用非流式发一条短消息，成功后再开流式。`,
      ],
    },
    note: `外网地址是临时公网入口，不用时去「网络」停止穿透。Key 不要写进公开的前端代码或截图里；模型 ID 必须和页面列出的完全一致。`,
  },

  network: {
    lead: `网络页负责两件对外的事：按当前访问地址自动生成前端入口并一键跳转，以及用内网穿透把控制台、模型 API 或前端临时发布到公网。默认使用免费临时地址。`,
    cards: [
      ["前端跳转", "前端地址按当前访问地址自动生成，顶栏“前端页面”按钮可直接打开。"],
      ["免费穿透", "不需要公网 IP，不用设置路由器；临时地址关掉即失效。"],
      ["目标可选", "管理控制台、模型 API、前端页面三选一，按需要发布。"],
    ],
    steps: [
      `前端地址会按当前访问主机自动填入；使用独立前端时再手动改成对应 URL，点“打开前端页面”验证。`,
      `需要远程看后台就选“管理控制台”；给程序调用选“模型 API”；只聊天选“前端页面”。`,
      `点“一键开启免费穿透”，保持“免费临时地址”；缺组件时点“下载穿透组件”。`,
      `等状态变成已开启，复制公网地址发给需要的人；不要把地址发到公开群。`,
      `不用时点“停止穿透”；出现 1033 等错误，展开连接日志看组件和网络状态。`,
    ],
    example: {
      title: `案例：出差时用手机看控制台`,
      text: `人在外面，想用手机查看调用量和用户状态。`,
      steps: [
        `网络页目标选“管理控制台”，开启免费穿透。`,
        `复制公网地址，在手机浏览器打开并登录管理员账号。`,
        `看完后回到页面点“停止穿透”，地址立即失效。`,
        `下次需要时重新开启，免费临时地址通常会变化。`,
      ],
    },
    note: `固定域名和 Token 放在“进阶”里，不懂就保持免费临时地址。穿透只应临时开启；长期公网暴露会增加被扫描和撞库的风险。`,
  },

  deploy: {
    lead: `部署页先评估这台机器能不能跑，再在每个平台卡里单独部署。没装的自动安装，已经装好的自动跳过下载，避免重复装和环境冲突。`,
    cards: [
      ["硬件", "CPU、内存、显存、磁盘和 llama.cpp 状态决定能跑多大模型。"],
      ["平台", "每张卡有独立的一键部署按钮；可以多选共存，已安装会跳过下载。"],
      ["网络", "GitHub 打不开时自动换加速镜像；也可以先点“网络诊断”确认线路。"],
      ["自定义", "不安装任何软件，只测试外部 OpenAI 兼容地址；保存后再去供应商页和路由页接入。"],
      ["开关", "关闭本地部署后，前端不再显示本地模型，API 也会拒绝本地模型。"],
    ],
    steps: [
      `先看硬件卡：显存小于 4GB 优先 CPU 推理；磁盘剩余空间要留出模型体积的两倍。`,
      `看平台卡片的“适合 / 勉强 / 不适合 / 需确认”标签和支持的模型类型，别只看名字。`,
      `在要用的平台卡里点“一键部署”；没装会安装，已装会跳过下载并启动/连接。`,
      `GitHub 或官网打不开时点右上角“网络诊断”；自动加速不行就填自己的加速前缀再保存。`,
      `勾选要启用的平台，点“保存选择”，再开“本地部署开关”；装完回「模型」页下载模型。`,
    ],
    example: {
      title: `案例：8GB 显存的机器`,
      text: `机器有 8GB 显存，想跑 7B 模型，同时保留 Ollama 备用。`,
      steps: [
        `硬件卡确认显存 8GB、内存够用、磁盘剩余空间大于模型体积。`,
        `在 llama.cpp 卡里点“一键部署”，已安装会跳过下载；再去模型页下载 7B Q4 并加载。`,
        `在 Ollama 卡里点“一键部署”，已安装会跳过下载并直接启动服务。`,
        `勾选 llama.cpp 和 Ollama，点“保存选择”，再开本地部署开关。`,
        `速度不理想时，在 Ollama 里拉同一个模型对比首字延迟。`,
      ],
    },
    note: `“适合”只是按当前硬件估算，不代表一定跑得快；上下文长度、量化等级和并发都会影响速度。关闭本地部署前，确认云端供应商和路由已经可用。`,
  },

  models: {
    lead: `模型页把模型按用途分类，并标出体积、状态、本机建议和独立引擎。前端模型切换只显示已下载完成的模型，没下载的不会出现在下拉框里。`,
    cards: [
      ["9 类用途", "文字、代码、视觉、OCR、绘画、视频、语音、向量、重排序分开看。"],
      ["更新", "只补内置清单里缺失的模型，不覆盖已有模型和你的修改。"],
      ["独立引擎", "绘画、视频、语音等需要单独引擎；本期只登记，不安装。"],
    ],
    steps: [
      `先用顶部分类筛选缩小范围，不要在一百多个模型里从头翻。`,
      `点右上角“更新”补齐内置清单；模型目录里新放的 GGUF 也会被发现。`,
      `文字 / 代码模型看“本机建议”和体积，确认能放下再下载。`,
      `下载完成后加载；加载成功、状态变为可用后，前端模型下拉才会出现它。`,
      `绘画、视频、语音等类型先看“独立引擎”列，按引擎名称准备环境，不要直接点下载。`,
    ],
    example: {
      title: `案例：只加一个日常 7B`,
      text: `不想装一堆模型，只想让前端多一个能聊天的 7B。`,
      steps: [
        `分类选“文字 / 对话”，按体积和本机建议排序。`,
        `选一个 7B Q4 量化版本，确认磁盘空间足够。`,
        `下载并加载，等状态变为可用。`,
        `回前端切换模型，发一条消息，确认能正常回复。`,
      ],
    },
    note: `没下载、下载中、加载失败的模型都不会出现在前端切换里。模型文件不要放进工程目录；默认模型目录是 <code>D:\\AI\\models</code>，可在配置里改。`,
  },

  kb: {
    lead: `知识库页把本机文档切成小段并建立全文索引。它不会把文件上传到云端；对话时打开知识库开关，系统会先检索相关片段，再把片段拼进上下文。`,
    cards: [
      ["入库", "支持粘贴文本，也支持 Word、PDF、Excel、PPT、图片等常见文件；图片会做 OCR，扫描件默认前 15 页，单文件上限 20MB。"],
      ["切块", "正文会自动切成约 420 字的片段；段落清楚、标题明确的资料更容易命中。"],
      ["检索", "先用真实问题在“检索测试”里试，命中相关片段再回对话页使用。"],
      ["备份", "下载 JSON 备份可换机或防误删；恢复是追加模式，同名文档跳过，不覆盖现有资料。"],
    ],
    steps: [
      `先把资料整理成纯文本：PDF、网页、Word 先转成 txt 或 md，删掉页眉页脚、广告和重复目录。`,
      `点“添加文本”粘贴正文，或“上传文本文件”选择文件；标题写清楚，例如“退款政策 FAQ”。`,
      `保存后看列表里的来源和字数，确认没有传错文件；空正文不会入库。`,
      `在“检索测试”输入用户真实会问的问题，检查返回片段是否相关；不相关就改标题、补关键词或重新整理正文。`,
      `回用户端对话设置打开“使用本机知识库检索”，提问后看回复下方是否出现“知识库 · 文档名”标签。`,
      `定期点“下载知识库备份”，把 JSON 存到网盘或 U 盘；误删后点“选择备份文件”再“恢复备份”。`,
    ],
    example: {
      title: `案例：把退款政策做成可检索知识库`,
      text: `客服每天回答“退款几天到账”，政策分散在几个文档里。`,
      steps: [
        `把退款政策整理成一份 Markdown，按“申请条件 / 到账时间 / 特殊情况”分段。`,
        `标题写“退款政策 FAQ”，上传或粘贴入库。`,
        `在检索测试里问“退款几天到账”，确认命中的是到账时间那一段。`,
        `回对话页打开知识库开关，再问同样的问题，回复应引用该文档。`,
        `上线前先下载一次知识库备份；以后改版本前也备份，误删时可直接恢复。`,
      ],
    },
    note: `知识库只做检索增强，不会替代模型判断；资料本身矛盾时，模型也可能给出矛盾答案。文档存在本机 SQLite，删除后对应索引一起删除；备份 JSON 含正文，恢复时会重新切块建立索引。敏感资料不要入库到多人共用的账号。`,
  },

  backup: {
    lead: `备份迁移页负责数据安全：日常备份、整机迁移和上传恢复。备份包带数据库、密钥、登录方式和配置；迁移包还带程序和启动脚本，但不带模型。`,
    cards: [
      ["一键备份", "适合定期存档；包含 <code>secret.key</code>，要放在可信位置。"],
      ["一键迁移", "程序 + 数据 + 启动脚本；默认保存到 <code>data/migrations</code>。"],
      ["上传恢复", "恢复账号、对话、调用记录和加密配置；恢复前自动做安全备份。"],
      ["到期清理", "聊天生成的文档按保留天数自动删除，用户端会提前显示到期时间和剩余天数。"],
    ],
    steps: [
      `日常先点“生成并下载备份”，把 zip 放到移动硬盘或可信网盘；不要只留在本机。`,
      `换电脑时点“生成到默认文件夹”，页面会显示完整路径；可打开文件夹或下载到浏览器。`,
      `把迁移包复制到新电脑，解压到普通目录，双击“一键迁移-双击我.bat”。`,
      `新机启动后检查账号、供应商 Key、路由和 API Key；模型文件不在包里，需要单独复制或重新下载。`,
      `需要回滚时上传备份并确认恢复；恢复后按提示重启工作台，管理员可能需要重新登录。`,
      `在“生成文档保留策略”填写 1–365 天，保存后会重算未清理文件的到期时间并立即清理；也可点“立即清理过期”手动释放磁盘。`,
    ],
    example: {
      title: `案例：换一台新电脑`,
      text: `旧电脑要退役，希望账号、对话和配置都带过去。`,
      steps: [
        `旧机先生成一次普通备份，作为额外保险。`,
        `再生成整机迁移包，复制到 U 盘。`,
        `新机解压到 <code>D:\\AI\\workbench</code>，双击一键迁移脚本。`,
        `把旧机模型目录复制到新机对应位置，或在新机重新下载。`,
        `登录后抽查一个用户、一个供应商和一个 API Key。`,
      ],
    },
    note: `迁移包不包含模型文件和 <code>.venv</code>；备份包含密钥，泄露等于泄露供应商 Key。恢复会覆盖当前数据，操作前先确认选对了文件。生成文档到期后只删物理文件、保留一条清理记录，历史消息会显示“已清理”，不会留下可下载入口。`,
  },

  share: {
    lead: `网站分享生成的是干净程序包，和“一键迁移”相反：不带数据库、账号、密钥、配置和模型。对方安装后是一台全新工作台，需要自己初始化管理员。`,
    cards: [
      ["干净", "只含程序、启动脚本、依赖清单和说明，不含任何用户数据。"],
      ["默认目录", "保存到 <code>data/shares</code>，页面显示路径，可打开或下载。"],
      ["新机", "对方首次启动自动建空库、装依赖、初始化管理员。"],
    ],
    steps: [
      `点“生成到默认文件夹”，确认页面显示的保存路径和文件名。`,
      `需要发给别人时点“下载到浏览器”，或直接打开文件夹复制 zip。`,
      `把 zip 通过网盘、U 盘或聊天工具发过去；不要误发备份包或迁移包。`,
      `对方解压到普通目录，双击“一键开始-双击我.bat”，首次启动会装依赖。`,
      `对方自己初始化管理员，再建用户、接供应商、生成 API Key、下载模型。`,
    ],
    example: {
      title: `案例：给朋友一台干净工作台`,
      text: `朋友想自己玩本地模型，但不需要你的聊天记录和 Key。`,
      steps: [
        `分享页生成分享包，确认大小约几百 KB，而不是带数据的几百 MB。`,
        `把 zip 发给朋友，提醒他解压到普通目录，不要放 Program Files。`,
        `朋友双击一键开始脚本，首次启动自动初始化管理员。`,
        `朋友自己配模型目录和供应商；你的账号、Key、对话都不会过去。`,
      ],
    },
    note: `分享包不含模型和 <code>.venv</code>；对方需要 Python 3.10+ 和足够磁盘空间。生成前确认页面写的是“分享包”，不要把自己的迁移包发出去。`,
  },

  org: {
    lead: `外观页负责把默认工作台改造成你自己的站点，所有配置只写在本机 <code>data/config.json</code>，Logo 文件保存在 <code>data/branding/</code>，不会上传云端。左侧编辑，右侧实时预览登录页。`,
    cards: [
      ["Logo", "支持 PNG / JPEG / WebP / GIF，最大 3 MB，不接受 SVG。上传成功立即生效，不需要再点保存；点“恢复默认”回到内置图标。"],
      ["品牌信息", "品牌名称、简称、副标题和主色会同步到登录页、侧栏、页面标题和 favicon；主色还决定按钮与选中态的主题色。"],
      ["登录页文案", "大标题支持换行，另有说明、登录卡片副标题和页脚文案。修改时右侧预览同步变化，保存后用户端刷新即可看到。"],
      ["页脚与备案", "ICP 备案号、公安备案号、版权和链接都可配置。链接只接受 http/https，留空时使用官方查询入口；版权留空会自动生成年份和品牌名。"],
      ["企业档案", "域名、行业、规模、联系人和邮箱是可折叠的选填资料，只用于后台记录，公开品牌数据不会带出联系人信息。"],
      ["安全水印", "开启后登录用户在前端和控制台看到铺满页面的水印，支持 <code>{user}</code>、<code>{org}</code>、<code>{date}</code> 占位符。"],
    ],
    steps: [
      `先改品牌名称、简称、副标题和主色，观察右侧预览是否协调；主色建议选中等明度，过浅会影响按钮文字对比度。`,
      `需要自定义 Logo 时点“上传 Logo”，选中正方形透明 PNG；上传后立即生效，若效果不好点“恢复默认”。`,
      `逐个修改登录页大标题、说明、登录卡片副标题和页脚；大标题需要断行时直接回车，预览会按原样换行。`,
      `填写 ICP、公安备案和版权；备案号要与实际备案一致，链接必须是 <code>https://...</code> 或 <code>http://...</code>。`,
      `需要内部识别时展开企业档案填写域名、行业、规模、联系人；这些字段只在后台显示。`,
      `需要防截图外传时开启安全水印，先在预览里确认文字不会遮挡主要内容。`,
      `点“保存”写入品牌文案；打开用户端或刷新登录页，确认 Logo、主色、标题、备案和版权都已生效。`,
    ],
    example: {
      title: `案例：把默认工作台换成公司内部站点`,
      text: `公司要用自己的工作台给同事使用，希望登录页出现公司名称、Logo、备案和内部说明。`,
      steps: [
        `把品牌名称改成公司内部平台名，简称改成同事熟悉的短名，主色改成公司主色。`,
        `上传公司方形 Logo，确认透明底在登录卡片和侧栏都清楚。`,
        `登录页大标题改成“公司知识助手”，说明写清楚仅限内部账号使用。`,
        `填写 ICP 与公安备案，版权写成公司全称；联系人只填内部管理员。`,
        `保存后让同事刷新登录页，确认品牌、备案和页脚都正确。`,
      ],
    },
    note: `Logo 上传和文字保存是两条独立链路：Logo 上传后立即生效，文字要点“保存”。公开品牌接口不会返回联系人等后台字段；备案链接必须是 http/https。水印会覆盖整个页面，正式启用前先确认不影响阅读。`,
  },

  moderation: {
    lead: `内容安全页在模型前后加一道检查：用户输入先检测，模型输出再检测。页面同时管理敏感词库、处理动作和命中记录，默认关闭，保存策略后立即对新请求生效。`,
    cards: [
      ["检测总开关", "关闭后不检测、不产生新命中记录；开启后聊天接口和 OpenAI 兼容接口都会走同一套策略。"],
      ["输入动作", "可拦截（直接返回 400，不发给模型）、替换后继续、仅告警并记录。拦截适合绝对不能出现的词。"],
      ["输出动作", "可替换敏感词后展示、整段拦截，或仅告警并记录；流式输出会保留跨块尾巴，避免敏感词被拆开绕过。"],
      ["敏感词库", "每个词可设置分类、备注和启停；支持单个添加和批量粘贴，逗号、分号、换行都能分隔，重复词自动跳过。"],
      ["命中记录", "记录时间、用户、方向、动作、命中词、片段和模型，可按输入/输出筛选；只保留最近记录，可手动清空。"],
    ],
    steps: [
      `先在敏感词库加入真正需要管理的词，按业务分类并写备注；不要一次粘贴无关的大词表。`,
      `分别设置用户输入和模型输出的动作：高风险内容用拦截，语气或品牌词用替换，观察期先用仅告警。`,
      `打开“开启内容安全检测”，点保存；页面会提示策略已对新请求生效。`,
      `到用户端发一条包含测试词的短消息，确认输入被拦截或替换；再测试模型输出路径。`,
      `回到命中记录按方向筛选，检查命中词和片段是否符合预期；误伤时停用对应词或改动作。`,
      `观察期结束后再收紧策略；清空命中记录只清历史，不会删除词库或关闭检测。`,
    ],
    example: {
      title: `案例：先观察再拦截内部代号`,
      text: `公司有一些内部项目代号不应出现在对外回答里，但直接拦截可能误伤正常讨论。`,
      steps: [
        `把代号加入词库，分类写“内部代号”，备注写清楚适用范围。`,
        `输入和输出动作先选“仅告警并记录”，开启检测。`,
        `让同事正常使用一天，查看命中记录里的片段是否都是真正需要处理的场景。`,
        `确认误伤很少后，把输出动作改成“替换后继续”，输入保持仅告警。`,
        `一周后复查命中记录，再决定是否对输入也启用拦截。`,
      ],
    },
    note: `默认关闭，未开启时不会产生新记录。拦截输入会直接返回错误，用户消息不会到达模型；输出拦截会终止本轮回答。流式检测会保留跨块尾巴，不会因为词被拆成两个 chunk 就漏掉。命中记录含用户原文片段，排查和截图时先脱敏。`,
  },

  websearch: {
    lead: `联网页控制工作台是否允许出网检索，以及每次保留多少来源、抓取多少网页正文。用户端联网开关和定时任务都以这里为总闸门；关闭后不会偷偷出网。`,
    cards: [
      ["总开关", "允许联网检索打开后，用户端和定时任务才能联网；关闭后全局跳过检索，并在回复里明确说明后台已关闭联网。"],
      ["来源条数", "最多保留 1–10 条搜索结果，包含新闻底稿；条数越多，上下文越长，成本也越高。"],
      ["正文页数", "最多抓取 0–4 篇网页正文；0 表示只给标题和摘要，抓得越多越慢，但资料更完整。"],
      ["真实检索测试", "输入真实问题跑一次当前线路，显示耗时、检索词和来源列表；测试不会写入任何对话。"],
      ["缓存与线路", "保存设置后新请求生效；可清空检索缓存。中文问题优先 360，英文优先 Bing，结果不足时自动互补。"],
    ],
    steps: [
      `先决定是否允许联网；只在确有需要时开启，关闭是最直接的隐私和成本保护。`,
      `把来源条数设成 3–5 条、正文页数设成 1–2 篇作为日常值，再按任务复杂度临时调高。`,
      `点“保存设置”，然后清空旧缓存，确保下一轮使用新配置。`,
      `在“跑一次真实检索”输入一个你熟悉答案的问题，观察来源是否相关、耗时是否可接受。`,
      `到用户端打开联网开关发一条需要实时信息的问题，确认回复带有来源，而不是只凭模型记忆。`,
      `如果结果明显变差，先恢复较小规模并清缓存，再检查当前网络是否能访问搜索源。`,
    ],
    example: {
      title: `案例：上线前验证联网线路`,
      text: `准备把联网功能开放给同事，但不确定当前网络能否稳定访问搜索源。`,
      steps: [
        `保持总开关开启，来源 5 条、正文 2 篇。`,
        `用“今天本地天气怎么样”做真实检索，确认能返回来源和抓取正文。`,
        `再问一个英文问题，确认会自动切到 Bing 或互补来源。`,
        `如果首次很慢但能成功，属于正常冷启动；连续失败则先检查代理、DNS 和出网策略。`,
        `确认稳定后再通知同事使用；不用时关闭总开关。`,
      ],
    },
    note: `测试会真实访问外部搜索源，首次可能较慢，不代表用户对话也会同样慢。抓取正文会增加等待时间和上下文长度；来源条数不是越多越好。关闭总开关后用户端按钮和定时任务都会跳过检索，不会假装查过。`,
  },

  parsing: {
    lead: `解析页汇总所有用户上传附件的识别状态。图片、PDF、Word、Excel、PPT 都会落到本机；正文为空或识别不理想时，不需要重新上传，可以直接在这里重跑 OCR 和文档提取。`,
    cards: [
      ["统计卡", "显示附件总数、已提取正文、正文为空和解析报错，先判断问题规模再决定单条还是批量处理。"],
      ["解析引擎", "显示 RapidOCR 和文档提取组件是否就绪；引擎缺失时先按页面提示修复依赖，再重跑。"],
      ["筛选与分页", "按全部/空正文/已提取/报错，以及图片/文档/文本筛选；列表按上传时间倒序，可分页。"],
      ["批量重解析", "可勾选单页记录点“解析选中”，或一键“重新解析空正文”；任务后台串行执行，避免同时 OCR 打满 CPU。"],
      ["正文预览", "点查看可看提取后的正文、下载原件；确认是扫描件、图片或格式异常导致的问题。"],
    ],
    steps: [
      `先看四个统计卡和解析引擎状态；引擎未就绪时不要急着批量重跑。`,
      `筛选“正文为空”，按文件类型判断是扫描 PDF、纯图片还是解析失败。`,
      `点一条记录查看正文预览并下载原件，确认文件本身是否可读、是否加密或损坏。`,
      `单条问题先点该行的重新解析；多条同类型问题再勾选后批量解析。`,
      `观察进度条里的当前文件、成功/空正文/失败数量和耗时；不要连续重复点击。`,
      `处理完刷新列表，确认正文状态变为已提取；仍为空时检查 OCR 页数上限和文件大小限制。`,
    ],
    example: {
      title: `案例：一批扫描 PDF 正文为空`,
      text: `同事上传了十几份扫描合同，聊天里读不到内容。`,
      steps: [
        `解析页筛选“正文为空”和“文档”，确认记录都是 PDF。`,
        `打开一份预览，发现正文为空但原文件能下载，判断是扫描件没有文字层。`,
        `确认 RapidOCR 状态正常、扫描 PDF 页数上限足够覆盖合同页数。`,
        `勾选这一批记录点“解析选中”，等待后台串行完成。`,
        `完成后刷新，抽查两份正文是否包含合同关键条款。`,
      ],
    },
    note: `重新解析不会重新上传文件，原文件丢失或格式损坏时无法恢复正文。批量任务在后台串行执行，记录多时需要等待；扫描件只识别配置的页数上限，超出部分不会自动补。正文可能含个人信息，预览和截图前先脱敏。`,
  },

  library: {
    lead: `资料库和知识库共用文档存储，但按用途隔离。总库由管理员统一维护，个人资料由用户自己上传；资料不会只用一次，用户可以在聊天框中反复选择并带入。`,
    cards: [
      ["总资料库开关", "默认关闭；开启后用户还要在自己的资料库设置里勾选“总资料库”，聊天框才会列出总库资料。"],
      ["带入上限", "可设置单次最多选几篇、最多带入多少字；上限越大上下文越长，响应会更慢。"],
      ["总库与个人库", "管理员可上传/粘贴总库资料，也能查看和删除任意个人资料；用户只能删除自己上传的个人资料。"],
      ["分类与复用", "支持文件夹和标签，列表可按库类型、账号、文件夹、标签筛选；引用次数和最近使用时间帮助判断哪些资料常用。"],
      ["导入格式", "支持 txt/md/csv/json/pdf/docx/xlsx/xls/pptx 和常见图片，单文件 20MB；图片和扫描 PDF 会本地 OCR。"],
      ["备份恢复", "把总库和个人资料一起导出 JSON，包含正文、归属和引用次数；恢复时个人资料回到原账号，找不到账号的条目跳过。"],
    ],
    steps: [
      `先决定是否开启总资料库；如果只给个人使用，保持关闭，让用户维护自己的资料。`,
      `设置单次最多资料篇数和最多字数，建议先用较小值，确认效果后再放宽。`,
      `上传总库文件或添加文本，填写标题、文件夹和标签；正文为空不会入库。`,
      `在全部资料列表按库类型和账号检查归属，点查看确认正文和分类正确。`,
      `让用户在聊天框选择资料并发问，确认回答引用了所选内容；观察引用次数是否增长。`,
      `上线前下载资料库备份；误删或换机时选择备份文件恢复，恢复是追加模式，同名条目会跳过。`,
    ],
    example: {
      title: `案例：把产品手册放进总库反复使用`,
      text: `客服和销售经常需要查同一份产品参数，不想每次上传。`,
      steps: [
        `开启总资料库，设置单次最多 3 篇、最多 6000 字。`,
        `上传产品手册 PDF，标题写“产品参数手册”，文件夹填“产品资料”，标签填“参数, 售后”。`,
        `在检索测试或用户端聊天选择这份资料，问“某型号保修多久”。`,
        `确认回答引用了手册内容，引用次数开始增长。`,
        `手册改版时先下载备份，再删除旧资料并上传新版本。`,
      ],
    },
    note: `总资料库关闭后聊天框不会列出总库资料，但个人资料仍可由用户自己开启。资料库备份包含正文和归属，注意存放位置；恢复不会覆盖同名条目。用户只能删除自己的个人资料，管理员删除个人资料前先确认归属和影响。`,
  },

  agents: {
    lead: `智能体页把常用角色做成可复用的人格。每个智能体带自己的系统提示词和推荐模型；用户在前端选中后，服务端把提示词注入本轮对话，不改变普通聊天。`,
    cards: [
      ["新建与编辑", "名称必须唯一，描述会显示给用户；可设置图标、排序和启停。系统提示词最多 4000 字。"],
      ["系统提示词", "只作用于选中该智能体的消息，用来规定角色、语气、边界和输出结构，不额外调用模型。"],
      ["推荐模型", "可指定一个推荐模型；前端选择该智能体时优先使用，但用户没有权限或模型不可用时仍要能正常对话。"],
      ["可见范围", "公开给所有成员；仅小队只对绑定小队的成员可见；私有只保留在后台目录。"],
      ["启停与列表", "停用后前端不再出现，但历史对话里的角色标签和内容保留；列表显示名称、描述、模型、可见范围和状态。"],
    ],
    steps: [
      `先写清楚这个角色解决什么问题，再起一个用户能看懂的名称，避免用内部缩写。`,
      `编写系统提示词：说明身份、任务边界、回答结构和禁止事项；不要把具体业务数据或密钥写死。`,
      `选择推荐模型，确认该模型已下载或供应商可用，并且目标用户有权限。`,
      `设置可见范围：全员用公开，项目组用仅小队并提前绑定小队，测试期用私有。`,
      `保存并启用，到用户端选中该智能体发一条典型问题，检查语气、结构和边界。`,
      `根据实际回答调整提示词；停用后前端立即不可选，历史记录不受影响。`,
    ],
    example: {
      title: `案例：做一个售后回复助手`,
      text: `客服需要统一语气，并且回答必须包含处理步骤和升级条件。`,
      steps: [
        `新建“售后回复助手”，描述写“统一售后语气，给出处理步骤”。`,
        `提示词规定：先确认问题，再给 1–3 步处理方案，无法解决时说明升级条件。`,
        `推荐模型选日常客服用的 7B，可见范围设为公开。`,
        `让客服在前端选中该智能体，输入一个真实售后问题。`,
        `检查回答是否按结构输出；不符合就补充提示词里的格式要求。`,
      ],
    },
    note: `系统提示词会和用户消息、附件、知识库一起进入上下文，提示词冲突时模型可能摇摆；写清优先级和边界。推荐模型不是强制模型，权限或可用性不满足时会回退。不要写 API Key、密码或用户隐私；停用不会删除历史对话。`,
  },

  partners: {
    lead: `伙伴页是组织成员目录的只读视图，把账号、用户组、管理员角色、最近登录和所属小队集中在一张表里，方便快速了解“谁在这个工作台里、属于哪里”。`,
    cards: [
      ["账号目录", "显示账号、用户组、管理员角色、所属小队、最近登录和状态；支持按关键词查询。"],
      ["组织归属", "用户组来自部门/用户组树，管理员角色显示该账号绑定的后台权限角色。"],
      ["小队关系", "显示成员加入了哪些小队；小队成员和共享会话在「小队」页维护。"],
      ["只读边界", "本页不新增、不禁用、不改配额；这些操作统一到「用户」页，避免两个入口写出不同结果。"],
    ],
    steps: [
      `在查询框输入用户名、用户组或小队名，先缩小范围。`,
      `看账号的角色、用户组、最近登录和状态，判断是否长期未使用或被停用。`,
      `需要看某人加入哪些小队时，对照“所属小队”列，再到「小队」页查看共享范围。`,
      `需要调整账号、重置密码、改模型权限或停用时，点「用户」页处理，不在本页找编辑按钮。`,
      `定期导出或核对成员目录，作为组织和权限复查的依据。`,
    ],
    example: {
      title: `案例：找出长期未登录的成员`,
      text: `管理员想清理已经离职但仍占着账号的成员。`,
      steps: [
        `伙伴页按最近登录时间浏览，找出很久没有登录的账号。`,
        `查看用户组、管理员角色和所属小队，确认是否仍承担任务。`,
        `到「用户」页禁用账号，保留历史记录，先不删除。`,
        `如果账号绑定了管理员角色，先解除角色再禁用，避免残留后台权限。`,
        `一周后再复查，确认无人反馈后再决定是否删除。`,
      ],
    },
    note: `本页只读，不能在这里改账号或权限。管理员角色代表后台权限，普通用户组只影响组织归属。成员目录含账号和登录信息，截图或导出前先确认使用范围。`,
  },

  squads: {
    lead: `小队页把成员、智能体和共享对话放在一个团队空间里。成员只能看到共享到本小队的会话，不会看到别人的全部对话；它适合项目组、班组或临时协作。`,
    cards: [
      ["创建小队", "填写小队名称并指定所有者；所有者负责维护成员和绑定智能体。"],
      ["成员管理", "成员列表显示账号、用户组和角色；可把成员设为共同所有者，共同维护小队。"],
      ["绑定智能体", "把智能体绑定到小队后，仅小队可见的智能体才会对该小队成员开放。"],
      ["共享对话", "显示共享到本小队的对话标题、共享人和时间；只有被共享的会话可见。"],
      ["权限边界", "小队不是账号组，不会自动获得模型权限；模型权限仍在「用户」页按账号分配。"],
    ],
    steps: [
      `先创建小队并写清楚用途，例如“研发一组”“售后项目”。`,
      `加入成员；需要多人维护时设置共同所有者，普通成员只参与协作。`,
      `到「智能体」页把“仅小队”智能体绑定到该小队，确认成员能看到。`,
      `让成员在用户端把自己的对话共享到小队，检查其他成员只能看到共享内容。`,
      `人员离开时从成员列表移除；删除小队前先确认共享对话和智能体绑定是否需要保留。`,
    ],
    example: {
      title: `案例：给项目组建一个共享空间`,
      text: `研发小组要共用“代码评审助手”，并共享项目讨论。`,
      steps: [
        `创建“研发一组”，把自己设为所有者，加入组员。`,
        `在智能体页新建“代码评审助手”，可见范围选“仅小队”，绑定研发一组。`,
        `组员在前端选择该智能体，确认能看到并使用。`,
        `组员把项目讨论共享到小队，其他成员只能看到这条共享对话。`,
        `项目结束后移除外部成员，保留所有者和必要记录。`,
      ],
    },
    note: `成员只能看到共享到本小队的会话，不会看到别人的全部对话；共享范围在用户端选择。小队不会自动赋予模型权限，智能体可见和模型可用是两件事。共同所有者能维护小队，授予前确认对方可信。`,
  },

  announcements: {
    lead: `公告页维护用户端顶部通知。启用的公告会显示给所有登录用户，置顶公告优先展示；适合维护通知、使用规范、安全提醒和版本变更。`,
    cards: [
      ["标题与正文", "标题最多 100 字，正文最多 4000 字；正文支持纯文本换行，发布前先预览措辞。"],
      ["级别", "通知、提醒、重要三种级别，用于区分普通消息和需要优先注意的内容。"],
      ["置顶", "置顶公告在用户端优先展示；只给真正紧急或长期有效的内容置顶。"],
      ["启停", "“立即启用”控制是否展示；停用后用户端不再出现，但后台记录保留。"],
      ["列表", "显示标题、级别、置顶、状态、创建人和时间，可编辑或停用已有公告。"],
    ],
    steps: [
      `先写一句能看懂的主题作为标题，再在正文写清时间、影响范围、需要用户做什么。`,
      `选择级别；普通信息用通知，需要留意用提醒，影响登录或数据安全才用重要。`,
      `确认真的是全员都需要知道后再勾“置顶”；短时通知不要长期置顶。`,
      `保持“立即启用”勾选并发布，到用户端刷新顶部确认展示效果。`,
      `维护结束后回到列表停用旧公告，避免过期信息继续占位置。`,
    ],
    example: {
      title: `案例：夜间维护通知`,
      text: `今晚 23:00–23:30 升级数据库，登录和对话可能短暂中断。`,
      steps: [
        `标题写“今晚 23:00 数据库维护”，级别选“重要”。`,
        `正文写清影响范围、预计时长、需要用户提前保存的内容。`,
        `维护开始前 2 小时发布并置顶。`,
        `维护完成后把公告改成“已完成”或直接停用，取消置顶。`,
        `第二天在服务台查看是否有用户反馈遗留问题。`,
      ],
    },
    note: `公告对所有登录用户可见，不要写内部地址、账号、密钥或未脱敏的用户信息。停用只停止展示，不会删除历史记录；置顶内容过多会失去优先级。过期公告要及时停用，避免用户按旧信息操作。`,
  },

  tickets: {
    lead: `服务台页接住用户从用户端提交的问题，管理员在这里筛选、查看、改状态、分派和回复。每个工单保留完整对话记录，直到关闭都可以继续跟进。`,
    cards: [
      ["工单列表", "显示编号、标题、提交人、分类、优先级、状态、处理人和更新时间；默认按状态和优先级排序。"],
      ["筛选", "按全部/待处理/处理中/已解决/已关闭，以及高/普通/低优先级查询，先处理高优先级和待处理。"],
      ["详情与对话", "打开工单看用户描述和历史回复；回复会进入工单记录，用户端能看到处理进展。"],
      ["状态流转", "待处理 → 处理中 → 已解决 → 已关闭；保存状态时可同时写回复。"],
      ["处理人", "可指定处理人，明确责任；未分配的高优先级工单应先分派。"],
    ],
    steps: [
      `先筛“待处理”和“高优先级”，按更新时间从旧到新处理，避免积压。`,
      `打开工单读清问题、影响范围和用户已尝试的操作，不要只看到标题就回复。`,
      `需要跟进时把状态改为“处理中”，指定处理人，并在回复里说明下一步和时间点。`,
      `问题解决后改为“已解决”，写清解决方法和需要用户确认的事项。`,
      `用户确认或超时无反馈后再关闭；关闭前确保没有未回答的问题。`,
    ],
    example: {
      title: `案例：用户无法登录`,
      text: `用户说输入正确密码仍提示失败，影响当天使用。`,
      steps: [
        `服务台筛“待处理”，打开工单看用户账号、登录方式和错误提示。`,
        `状态改为“处理中”，指派给管理员，回复“正在检查账号状态，请稍等”。`,
        `到用户页确认账号未被禁用、登录方式未关闭，再检查是否需要重置密码。`,
        `处理后回复具体原因和操作步骤，状态改为“已解决”。`,
        `用户确认能登录后关闭工单。`,
      ],
    },
    note: `回复内容用户可见，不要贴出密码、密钥或其他用户的隐私。关闭不是删除，记录仍保留；如果问题复发，应新建工单而不是改旧结论。高优先级不等于可以跳过排查，先确认影响范围再承诺时间。`,
  },

  "conv-shares": {
    lead: `对话分享页统一查看用户生成的只读对话快照。分享链接保存的是分享时的消息，不会随后续聊天变化；管理员可以打开检查、查看浏览量和有效期，并随时撤销。`,
    cards: [
      ["快照", "分享的是分享时的消息副本，后续继续聊天不会改变已分享内容；适合对外说明问题，不适合持续协作。"],
      ["范围", "公开链接任何拿到地址的人都能打开；仅小队只有小队成员可访问。"],
      ["有效期", "可设置到期时间或永久；到期后自动失效，避免旧链接长期暴露。"],
      ["浏览统计", "列表显示消息数和浏览次数，可判断链接是否仍在传播。"],
      ["撤销", "点“撤销”立即让链接失效；打开按钮用于复查当前内容。"],
    ],
    steps: [
      `先确认这条分享是否仍需要存在；临时排查结束后及时撤销。`,
      `点“打开”检查快照内容，确认没有密码、手机号、地址或其他敏感信息。`,
      `看范围和有效期：公开且永久的最危险，能改就改成仅小队或设置到期。`,
      `需要停止访问时点“撤销”，再刷新列表确认状态变为失效。`,
      `定期清理长期无人浏览的公开分享，保留确有审计价值的记录。`,
    ],
    example: {
      title: `案例：排查完后撤销公开链接`,
      text: `同事为了排查问题把一段对话设成公开分享，问题解决后链接还在群里。`,
      steps: [
        `在对话分享列表找到这条记录，确认分享人和范围是公开。`,
        `点打开检查内容，发现包含内部项目名。`,
        `立即点撤销，刷新后确认状态为失效。`,
        `在群里说明旧链接已失效，需要继续讨论就重新生成仅小队分享。`,
        `以后默认使用仅小队和较短有效期。`,
      ],
    },
    note: `公开分享等于任何拿到链接的人都能看，链接本身要当敏感信息管理。快照不会随新消息更新；撤销立即生效但已经保存的截图无法收回。分享内容可能含用户隐私，打开和转发前先脱敏。`,
  },

  prompts: {
    lead: `提示词中心把运行时用到的所有平台提示词集中到一处：基础人格、内置与自定义技能、知识库/资料库/记忆/联网规则、文档输出格式和 9 个工作台模板。保存会生成版本并热更新，下一条消息使用新内容，历史回复不变。`,
    cards: [
      ["核心提示词", "全局系统提示词是所有普通对话的起点；技能和功能规则会依次追加。它不由用户端直接编辑。"],
      ["技能提示词", "6 个内置技能可以覆盖默认并随时恢复；自定义技能沿用原有数据，保存后立即出现在用户端技能菜单。"],
      ["功能规则", "联网、知识库、资料库、记忆的注入说明在此统一编辑；功能开关仍在联网、知识库、记忆等原页面。"],
      ["输出格式", "Word、Excel、PPT、PDF、Markdown、纯文本各自的生成约束，决定模型怎样组织可下载文件内容。"],
      ["工作台模板", "9 个内置工作台的欢迎语和 8 个推荐任务提示词，保存后用户端重新进入工作台即可看到。"],
      ["智能体", "智能体提示词在提示词中心只读展示，编辑请到智能体页，避免同一段提示词出现两个来源。"],
      ["版本与热更新", "每次保存生成版本并提升修订号；当前进程立即清缓存，多进程最多 1.2 秒内自动对齐。"],
    ],
    steps: [
      `先看顶部“实际拼装顺序”，确认要改的是基础人格、技能、功能规则还是输出格式。`,
      `在左侧搜索或按类型筛选，点选资产；右侧可以看到当前生效内容、默认值和修改人。`,
      `编辑内容，点“预览拼装”检查最终顺序和大致 Token 占用；确认没有互相矛盾的规则。`,
      `点“保存并生效”，页面显示新修订号。到用户端发一条真实消息验证，不需要重启服务。`,
      `如果改坏，展开版本历史恢复上一版；内置资产也可以点“恢复默认”。`,
    ],
    example: {
      title: `案例：把周报技能改成三段式`,
      text: `团队希望“总结提炼”技能统一输出“进展 / 风险 / 下周计划”，并且风险必须带负责人。`,
      steps: [
        `在提示词中心搜索“总结提炼”，打开技能提示词。`,
        `在原文后补上三段式结构和“缺失负责人标待确认”，不要删除保留数字与时间的要求。`,
        `点预览拼装，确认技能内容排在基础人格之后、知识库之前。`,
        `保存并生效，到用户端选中“总结提炼”粘贴一段会议记录，检查格式。`,
        `不满意就展开版本历史恢复到修改前，不需要重启。`,
      ],
    },
    note: `提示词不是越长越好，过长会挤占用户输入和资料上下文。不要把账号、密钥、内部隐私写进提示词。功能开关不在这里改；内容安全和敏感词也不属于本页，避免通过改提示词绕过审核。“刷新列表”只重新读取数据库，不会应用未保存的修改；保存本身已经即时生效。`,
  },

  front: {
    lead: `前台功能页决定用户端显示哪些入口。开关只控制“显示”，不改变用户权限，也不删除已有数据；联网、知识库、资料库、记忆四项同时控制原来的能力总开关，关闭后实际能力也会停用。`,
    cards: [
      ["功能卡片", "每个入口单独一个开关，卡片会写清关闭后影响侧栏、输入框、设置页还是工作台。"],
      ["用户端预览", "右侧实时模拟用户端侧栏、输入框工具条和设置页；预览里消失的入口，保存后用户端也会消失。"],
      ["能力开关", "联网、知识库、资料库、记忆带“能力”标记；关闭会停止检索或记忆，不只是藏入口。"],
      ["依赖关系", "定时任务和生成文件依赖工作台；工作台关闭时，它们会自动隐藏且开关不可用。"],
      ["图标自定义", "每张卡片图标右下角有铅笔按钮；顶部“图标库”可以上传透明 PNG / WebP / SVG，并统一管理。"],
      ["基础对话", "登录、对话、历史记录、模型切换、账号与主题始终显示，避免误关后无法进入。"],
      ["生效方式", "保存后递增修订号；已登录用户刷新页面或重新聚焦时同步，不重启服务。"],
    ],
    steps: [
      `先按分组浏览，确认哪些入口面向当前用户真的需要；不必把所有功能都打开。`,
      `关掉不需要的入口，观察右侧“用户端预览”：侧栏、输入框和设置页同步减少。`,
      `需要换图标时点卡片图标右下角的小铅笔，选择预设图标或上传自定义图标；底色也从低饱和色板选。`,
      `确认预览后点“保存并生效”；页面显示新修订号和“已生效”。`,
      `到用户端刷新页面，核对入口是否与预览一致；需要回退时重新打开再保存。`,
    ],
    example: {
      title: `案例：给外部访客一个干净界面`,
      text: `只保留普通对话、资料库和文档生成，不显示工作台、小队、服务台和 API 接入。`,
      steps: [
        `关闭“工作台”，定时任务和生成文件会自动一起隐藏；再关闭“小队与共享”“服务台”“API 接入”。`,
        `右侧预览只剩新建对话、资料库、文档生成和基础设置；确认没有空栏。`,
        `给资料库换一个更直观的资料图标，底色保持绿色。`,
        `保存并生效，用普通账号刷新用户端，确认看不到已关闭入口。`,
      ],
    },
    note: `这是入口显示开关，不是权限系统：知道接口地址的人仍可能直接调用未显示的 API。需要真正拦截能力时，用原有的能力开关或权限模块。关闭入口不会删除历史数据、定时任务或生成文件；已有任务仍按原计划执行。`,
  },

  skills: {
    lead: `技能页维护用户端可选的提示词技能。内置技能默认可用，提示词覆盖和启停统一到「提示词中心」；管理员新建的自定义技能会出现在用户端菜单，选中后由服务端把提示词追加到本轮系统提示，不额外调用模型。`,
    cards: [
      ["内置技能", "总结、翻译、润色、代码、文件问答、方案规划等内置项默认启用；提示词和启停请到「提示词中心」调整，不在本页删除。"],
      ["自定义技能", "可新建名称、说明、图标、提示词、排序和启停；名称和提示词必填，说明会显示在用户端菜单。"],
      ["提示词注入", "只对选中该技能的消息生效，追加到本轮系统提示；普通对话和其他技能不受影响。"],
      ["启停", "停用后新消息立即选不到，已有对话里的技能标签和回复保留。"],
      ["边界", "技能只改变本轮任务做法，不会绕过模型权限、内容安全、知识库开关或附件解析。"],
    ],
    steps: [
      `先判断内置技能是否已经够用；能用内置就不要重复造自定义技能。`,
      `新建技能，写清楚名称和一句说明，让用户能判断什么时候选它。`,
      `提示词只写这类任务的做法、输出结构和边界，不要把具体业务数据、账号或密钥写死。`,
      `保存并启用，到用户端选择该技能发一条典型问题，检查输出是否符合预期。`,
      `效果不稳定时收紧提示词，明确“先做什么、不做什么、输出格式”；停用后立即从前端菜单消失。`,
    ],
    example: {
      title: `案例：做一个会议纪要技能`,
      text: `同事经常把会议记录粘进对话，希望统一输出“结论 / 待办 / 风险”。`,
      steps: [
        `新建“会议纪要”，说明写“把流水记录整理成结论、待办和风险”。`,
        `提示词规定三段式输出，待办必须带负责人和截止时间，缺失就标注“待确认”。`,
        `保存并启用，在用户端选中该技能粘贴一段会议记录。`,
        `检查输出是否稳定按三段式；不符合就补充格式和缺失处理规则。`,
        `收集同事反馈后再调整，不要频繁改名导致大家找不到。`,
      ],
    },
    note: `技能提示词和用户输入、附件、知识库一起进入上下文，写得过长会挤占上下文；只写必要规则。停用不会删除历史回复。自定义技能不能绕过权限和内容安全，也不要在提示词里要求模型泄露系统提示或密钥。`,
  },

  cluster: {
    lead: `算力页把多台局域网机器上的同一个模型合成一个统一模型名。每台机器各自完整加载模型，工作台只负责记地址、检查在线和把请求分给当前最闲的一台；单次请求不会跨机切分层。`,
    cards: [
      ["节点", "填写机器地址，统一到 <code>/v1</code>；保存只记配置，不会在对方机器安装服务。可测试地址并查看在线状态和模型列表。"],
      ["权重与并发", "每个节点可设置权重和并发上限，参与调度；机器性能不同就给不同权重。"],
      ["模型池", "池名就是对外模型名；池内每台机器必须跑同一个模型，成员填各自机器上的真实模型名。"],
      ["调度", "加权最少连接适合性能不一致的机器，轮询适合配置一致的机器；超时和重试控制故障转移。"],
      ["重试边界", "重试 1 次表示第一台失败后再换一台；要覆盖三台机器填 2。流式请求只在还没吐出第一个字之前换机器。"],
    ],
    steps: [
      `先确认每台机器已经用 Ollama、LM Studio、vLLM 或 llama.cpp 起好服务，并在浏览器打开 <code>地址/models</code> 能看到模型列表。`,
      `在节点区填机器名和地址，保存后等自动探测；状态不在线先查 IP、端口、防火墙和服务监听地址。`,
      `设置权重和并发，性能强的机器给更高权重；保存节点。`,
      `新建模型池，填对外统一模型名，把节点逐个加为成员，并填每台机器上的真实模型名。`,
      `设置超时和重试，保存后在用户端选择池名发消息，确认请求落到其中一台在线机器。`,
      `用调用记录或节点状态检查分流；某台机器持续失败时先停用它，再排查服务。`,
    ],
    example: {
      title: `案例：三台 8G 机器合并成一个模型名`,
      text: `办公室三台机器各跑一份 qwen3-8b q4，希望同事只看到一个模型。`,
      steps: [
        `三台机器分别启动 Ollama，浏览器访问各自 <code>/v1/models</code> 确认模型名一致。`,
        `算力页添加三个节点，测试全部在线。`,
        `新建池名 <code>qwen3-8b-pool</code>，把三台机器加为成员，填真实模型名。`,
        `调度选加权最少连接，超时 30 秒，重试 2。`,
        `前端选 qwen3-8b-pool 连续发三条消息，确认分布到不同机器。`,
      ],
    },
    note: `它合并的是并发和吞吐，不是单次速度；三台 8G 机器不会合起来跑 70B。每台机器必须各自完整加载同一个模型，模型名要填对方服务里的真实名称。流式请求一旦开始输出就不能无损换机；网络不稳时先修网络，不要只加重试。`,
  },

  memory: {
    lead: `长期记忆页是管理员总开关和条目管理入口。关闭时对话只用本次会话的最近上下文；打开后账号的自述和偏好可以跨对话保留，并按相关度注入。它默认关闭，且每个用户还要自己打开。`,
    cards: [
      ["两层开关", "这里是全局总开关；关闭后所有账号都不使用。打开后，每个用户还要在用户端「设置 → 记忆」打开自己的开关。"],
      ["按账号隔离", "条目按账号保存，其他账号看不到；管理员可以查看和手动增删，用于纠正和排障。"],
      ["自动抽取", "只保存“我叫 / 我是 / 我喜欢 / 记住…”这类明确自述，闲聊和问题不会被当成事实。"],
      ["手动维护", "可手动添加一条记忆，或删除错误条目；改动下一轮对话立即生效。"],
      ["保留策略", "页面最多展示最近 300 条；单个账号超过上限时优先淘汰权重最低、最久未更新的条目。"],
    ],
    steps: [
      `先决定是否允许长期记忆；涉及隐私或多人共用账号时保持关闭。`,
      `需要时打开全局总开关，再让用户在用户端打开自己的开关；两层都开才会写入和注入。`,
      `用一条明确自述测试，例如“我叫小王，我习惯用表格看数据”，确认条目出现。`,
      `检查账号、内容和来源是否正确；自动抽取错了就删除或手动补一条正确内容。`,
      `不需要时关闭开关：停止写入和注入，但已有条目保留，以后可继续用。`,
      `定期清理过期偏好和错误事实，避免旧信息长期影响回答。`,
    ],
    example: {
      title: `案例：纠正一条错误偏好`,
      text: `用户发现模型一直按旧称呼叫他，但本人已经换了称呼。`,
      steps: [
        `记忆页按账号筛选，找到那条旧称呼。`,
        `确认来源是自动抽取还是手动添加。`,
        `删除旧条目，再手动添加一条新的正确称呼。`,
        `让用户下一轮对话确认模型使用新称呼。`,
        `提醒用户以后改偏好可以直接在用户端记忆设置里维护。`,
      ],
    },
    note: `长期记忆会跨对话保留，可能包含个人信息；不要替用户写入敏感内容。关闭只停止写入和注入，不删除旧条目。自动抽取只基于明确自述，不会调用模型猜事实。多人共用账号时建议关闭，避免偏好互相污染。`,
  },

  audit: {
    lead: `审计页是只读的管理员操作日志。登录、用户、模型、知识库、数据库、技能和算力池等管理动作都会写入本地审计表；排查“谁改了什么”时从这里查。`,
    cards: [
      ["关键词", "搜索框同时匹配账号、动作、目标、详情和 IP；可搜用户名、表名、模型名或错误片段。"],
      ["动作前缀", "动作按模块命名，例如 <code>user.</code>、<code>model.</code>、<code>database.</code>、<code>skill.</code>，输入前缀可锁定一类操作。"],
      ["状态", "成功、失败、已锁定三类；失败操作同样留痕，可区分权限不足、参数错误或系统异常。"],
      ["时间范围", "最近 1 天、7 天、30 天或全部；先缩小时间再搜关键词，结果更准。"],
      ["只读", "审计记录不能在页面修改或删除；分页查看更早记录。"],
    ],
    steps: [
      `先确定时间范围：刚发生的问题选最近 1 天，历史变更选 7 天或 30 天。`,
      `输入你记得的账号、目标名或动作前缀；不知道动作名就先搜对象名。`,
      `按状态筛选失败记录，看详情里的错误信息，不要只看“失败”两个字。`,
      `点开记录核对时间、IP、目标和详情，判断是人工操作还是程序调用。`,
      `需要继续排查时，把动作前缀带到「调用记录」或对应功能页，确认当时配置和数据。`,
      `定期抽查高风险动作：删除用户、改数据库、改路由、撤销 Key、修改权限。`,
    ],
    example: {
      title: `案例：某张表突然少了很多行`,
      text: `同事反馈数据库里一张表的数据不见了。`,
      steps: [
        `审计页时间选最近 1 天，动作前缀输入 <code>database.</code>。`,
        `找到一条清空表数据或删除表的记录，查看账号、IP 和时间。`,
        `打开详情确认目标表名和操作结果，判断是误操作还是迁移脚本。`,
        `到数据库中心查看是否有自动快照，再决定恢复方案。`,
        `在服务台或群里说明原因，并收紧该管理员的数据库权限。`,
      ],
    },
    note: `审计只记录管理动作，不记录普通聊天内容；模型调用失败要到「调用记录」看。日志含账号、IP 和操作详情，截图或外发前先脱敏。审计记录只读，发现异常先保全证据再处理账号。`,
  },

  database: {
    lead: `数据库中心把工作台 SQLite 的表、数据和常用运维操作集中在一页。可以浏览和编辑数据、查看表结构、执行只读 SQL、连接外部 MySQL/PostgreSQL，也可以把当前数据一键复制到外部库。`,
    cards: [
      ["数据浏览", "左侧表清单，右侧分页表格；支持关键词搜索、按列排序、查看完整单元格、新增/编辑/删除行和导出 CSV。"],
      ["表结构", "查看字段类型、是否可空、默认值、主键、索引、外键和建表 SQL，修改前先确认依赖。"],
      ["表管理", "图形化新建表、重命名、清空数据、删除整张表；危险操作要求输入完整表名，并自动生成 SQLite 快照。"],
      ["SQL 控制台", "单条 SQL，默认只读（SELECT / WITH / SHOW / EXPLAIN）；开启写操作后仍需二次确认，显示耗时和影响行数。"],
      ["外部连接", "支持 MySQL/MariaDB、PostgreSQL 和外部 SQLite；密码加密保存，页面不回显明文，可测试连接。"],
      ["一键迁移", "把当前工作台数据复制到目标库，自动建表、分批复制、建索引和外键、逐表校验行数；同名表需显式覆盖。"],
    ],
    steps: [
      `动手前先点“下载数据库快照”，把一致性副本放到可信位置；改数据前备份比事后补救可靠。`,
      `先在数据浏览里选表、搜索和排序，确认目标行；编辑单元格前看清字段类型和外键。`,
      `新增或删除行时一次只改一处，保存后刷新确认；批量需求优先用 SQL 控制台并先只读验证。`,
      `需要改表结构时先看“表结构”里的索引和外键；重命名、清空、删表必须输入完整表名。`,
      `需要扩容或外迁时到“外部连接”填地址和账号，测试成功后用“一键迁移”复制并核对行数。`,
      `迁移后仍以本地 SQLite 为主库；确认外部库可读后再决定后续写入策略。`,
    ],
    example: {
      title: `案例：清理一条测试用户记录`,
      text: `测试时创建了一个用户，想删掉但担心连带数据。`,
      steps: [
        `先下载数据库快照。`,
        `数据浏览选 users 表，搜索测试用户名，确认用户 ID。`,
        `查看相关会话、调用记录和外键，判断删除会不会留下孤儿数据。`,
        `优先在「用户」页删除账号，让业务层处理关联数据，而不是直接改表。`,
        `删除后回数据库浏览确认记录消失，并保留快照到确认无异常。`,
      ],
    },
    note: `工作台主库始终是本地 SQLite，外部库用于扩容、备份和管理，断网时不会拖垮服务。危险表操作会生成快照，但不等于可随意操作；核心表禁止改名或删除。SQL 默认只读，开启写操作后仍要确认语句和影响范围。外部库密码加密保存，页面不会回显。`,
  },
};

function tutorialHtml(t) {
  return `
    <div class="tutorial-lead">${t.lead}</div>
    <div class="tutorial-cards">
      ${t.cards.map(([title, text]) => `<div class="tutorial-card"><b>${title}</b><p>${text}</p></div>`).join("")}
    </div>
    <div class="tutorial-block">
      <h3>操作步骤</h3>
      <ol class="tutorial-steps">${t.steps.map((s) => `<li>${s}</li>`).join("")}</ol>
    </div>
    <div class="tutorial-case">
      <span class="tutorial-case-label">实战案例</span>
      <h3>${t.example.title}</h3>
      <p>${t.example.text}</p>
      <ol class="tutorial-steps">${(t.example.steps || []).map((s) => `<li>${s}</li>`).join("")}</ol>
    </div>
    <div class="tutorial-note"><b>注意：</b>${t.note}</div>`;
}

let guideReturnFocus = null;

function guideSummaryHtml(t) {
  return `
    <div class="panel-head">
      <h2>使用说明</h2>
      <span class="hint">本页功能和风险提示</span>
    </div>
    <p class="guide-summary-lead">${t.lead}</p>
    <ol class="guide-quick-steps">${t.steps.slice(0, 4).map((s) => `<li>${s}</li>`).join("")}</ol>
    <p class="guide-quick-foot">完整功能清单、全部步骤和实战案例，请点右上角“详细说明”或顶部“说明”。</p>`;
}

function openPageGuide() {
  if (!token()) return;
  const data = PAGE_TUTORIALS[S.tab];
  if (!data) {
    uiToast("正在整理这一页的说明，请稍后再试", "bad");
    return;
  }
  const modal = $("guideModal");
  const body = $("guideModalBody");
  if (!modal || !body) return;
  closeNav();
  const title = TITLES[S.tab] || ["", "页面说明"];
  $("guideModalTitle").textContent = `${title[1]} · 使用说明`;
  body.innerHTML = tutorialHtml(data);
  guideReturnFocus = document.activeElement;
  modal.hidden = false;
  requestAnimationFrame(() => modal.classList.add("open"));
  document.body.classList.add("guide-open");
  body.scrollTop = 0;
  $("pageGuideBtn").setAttribute("aria-expanded", "true");
  setTimeout(() => $("guideModalClose").focus(), 30);
}

function closePageGuide(restoreFocus = true) {
  const modal = $("guideModal");
  if (!modal || modal.hidden) return;
  modal.classList.remove("open");
  modal.hidden = true;
  document.body.classList.remove("guide-open");
  const btn = $("pageGuideBtn");
  if (btn) btn.setAttribute("aria-expanded", "false");
  if (restoreFocus && guideReturnFocus && document.contains(guideReturnFocus)) {
    try { guideReturnFocus.focus(); } catch {}
  }
  guideReturnFocus = null;
}

function ensureGuideDetails(name) {
  const data = PAGE_TUTORIALS[name];
  const pane = $("pane-" + name);
  if (!data || !pane) return;
  let panel = pane.querySelector(".usage-guide, .migrate-guide");
  if (!panel) {
    panel = document.createElement("section");
    panel.className = "panel usage-guide auto-guide";
    panel.dataset.pageGuide = name;
    panel.innerHTML = guideSummaryHtml(data);
    pane.appendChild(panel);
  }
  const head = panel.querySelector(".panel-head");
  if (!head) return;

  let actions = head.querySelector(".guide-actions");
  if (!actions) {
    actions = document.createElement("div");
    actions.className = "guide-actions";
    const hint = head.querySelector(".hint");
    if (hint) actions.appendChild(hint);
    head.appendChild(actions);
  }

  let btn = actions.querySelector(".usage-more");
  if (!btn) {
    btn = document.createElement("button");
    btn.className = "btn small usage-more";
    btn.type = "button";
    btn.dataset.tutorial = name;
    btn.setAttribute("aria-expanded", "false");
    btn.textContent = "详细说明";
    actions.appendChild(btn);
  }

  let detail = panel.querySelector(".usage-detail");
  if (!detail) {
    detail = document.createElement("div");
    detail.className = "usage-detail";
    detail.id = "guide-detail-" + name;
    detail.hidden = true;
    detail.innerHTML = tutorialHtml(data);
    panel.appendChild(detail);
  }
}

function toggleGuideDetail(btn) {
  const pane = btn.closest(".tab-pane");
  if (!pane) return;
  const detail = pane.querySelector(".usage-detail");
  if (!detail) return;
  const willOpen = detail.hidden;
  detail.hidden = !willOpen;
  btn.textContent = willOpen ? "收起详细说明" : "详细说明";
  btn.setAttribute("aria-expanded", String(willOpen));
  if (willOpen) detail.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function fmtInt(n) { return Number(n || 0).toLocaleString("zh-CN"); }
function fmtCost(n) { n = Number(n || 0); return n === 0 ? "—" : "$" + n.toFixed(4); }
function fmtMs(n) { n = Number(n || 0); return n ? (n >= 1000 ? (n / 1000).toFixed(1) + "s" : n + "ms") : "—"; }

async function switchTab(name) {
  if (!token()) { showLogin(); return; }
  if (!TITLES[name]) name = "overview";
  if (!tabAllowed(name)) name = firstAllowedTab();
  if (!name) {
    document.querySelectorAll(".tab-pane").forEach((p) => { p.hidden = true; });
    $("subtitle").textContent = "当前管理员角色没有可访问的模块";
    return;
  }
  S.tab = name;
  rememberTab(name);
  if (S.tunnelTimer) { clearInterval(S.tunnelTimer); S.tunnelTimer = null; }
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  const activeTab = document.querySelector(`.tab[data-tab="${name}"]`);
  const tabBar = activeTab && activeTab.closest(".tabs");
  if (tabBar) {
    const tabBox = activeTab.getBoundingClientRect();
    const barBox = tabBar.getBoundingClientRect();
    if (getComputedStyle(tabBar).flexDirection === "column") {
      const target = tabBar.scrollTop + tabBox.top - barBox.top - 46;
      tabBar.scrollTop = Math.max(0, target);
    } else {
      const target = tabBar.scrollLeft + tabBox.left - barBox.left - (barBox.width - tabBox.width) / 2;
      tabBar.scrollLeft = Math.max(0, target);
    }
  }
  closeNav();
  document.querySelectorAll(".tab-pane").forEach((p) => { p.hidden = p.id !== "pane-" + name; });
  const t = TITLES[name] || ["", ""];
  $("subtitle").textContent = t[0];
  const navToggle = $("navToggle");
  if (navToggle) navToggle.title = `当前页面：${t[1]} · 打开页面导航`;
  ensureGuideDetails(name);
  if (name === "network") {
    S.tunnelTimer = setInterval(() => {
      if (S.tab === "network") loadTunnelStatus().catch(() => {});
    }, 3000);
  }
  await refreshCurrent();
}

async function refreshCurrent() {
  if (!token()) { showLogin(); return { ok: false, error: "未登录" }; }
  try {
    if (S.tab === "overview") await loadOverview();
    else if (S.tab === "requests") await loadRequests();
    else if (S.tab === "providers") await loadProviders();
    else if (S.tab === "routes") await loadRoutes();
    else if (S.tab === "users") await loadUsers();
    else if (S.tab === "org") await loadOrgPage();
    else if (S.tab === "moderation") await loadModerationPage();
    else if (S.tab === "agents") await loadAgentsPage();
    else if (S.tab === "partners") await loadPartnersPage();
    else if (S.tab === "squads") await loadSquadsPage();
    else if (S.tab === "announcements") await loadAnnouncementsPage();
    else if (S.tab === "tickets") await loadTicketsPage();
    else if (S.tab === "conv-shares") await loadConvSharesPage();
    else if (S.tab === "skills") await loadSkillsAdmin();
    else if (S.tab === "prompts") await loadPromptsPage();
    else if (S.tab === "front") await loadFrontPage();
    else if (S.tab === "auth") await loadAuthProviders();
    else if (S.tab === "api") await loadApi();
    else if (S.tab === "network") await loadNetwork();
    else if (S.tab === "websearch") await loadWebsearch();
    else if (S.tab === "parsing") await loadParsingPage(1);
    else if (S.tab === "deploy") await loadAll();
    else if (S.tab === "cluster") await loadClusterPage();
    else if (S.tab === "models") await loadModelsTab();
    else if (S.tab === "kb") await loadKbPage();
    else if (S.tab === "library") await loadLibraryPage();
    else if (S.tab === "memory") await loadMemoryPage();
    else if (S.tab === "backup") await loadBackupPage();
    else if (S.tab === "audit") await loadAuditPage();
    else if (S.tab === "database") await loadDatabasePage();
    else if (S.tab === "share") await loadSharePage();
    else await loadAll();
    return { ok: true };
  } catch (e) {
    console.warn(e);
    return { ok: false, error: e && e.message ? e.message : String(e) };
  }
}

/* ---------------------------------------------------------------- 概览 */
async function loadOverview() {
  const d = await api("/api/admin/overview?days=1");
  const perCall = d.count ? Math.round(d.tokens / d.count) : 0;
  const cards = [
    ["调用次数", fmtInt(d.count), `本地 ${fmtInt(d.local_calls)} · 云端 ${fmtInt(d.cloud_calls)}`],
    ["Token", fmtInt(d.tokens), `单次均 ${fmtInt(perCall)}`],
    ["成本", fmtCost(d.cost), "按供应商单价折算"],
    ["错误率", (d.error_rate || 0) + "%", `${fmtInt(d.errors)} 次失败`],
    ["首字 P50 / P95", fmtMs(d.p50_ttft) + " / " + fmtMs(d.p95_ttft), "TTFT，越小越好"],
    ["总耗时 P50 / P95", fmtMs(d.p50_total) + " / " + fmtMs(d.p95_total), "含排队与推理"],
    ["缓存命中", fmtInt(d.cache_hits), "M4 预留"],
  ];
  $("statCards").innerHTML = cards.map(([k, v, s]) =>
    `<div class="card"><div class="k">${esc(k)}</div><div class="v" style="font-size:20px">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");

  const total = d.series.reduce((a, x) => a + (x.c || 0), 0);
  $("seriesHint").textContent = `最近 24 小时 · ${fmtInt(total)} 次调用`;
  if (!d.series.length) {
    $("chart").innerHTML = `<div class="chart-empty">还没有调用数据，先去对话页发一条消息</div>`;
  } else {
    const max = Math.max(...d.series.map((x) => x.c || 0), 1);
    $("chart").innerHTML = d.series.map((x) => {
      const dt = new Date((x.t || Date.now() / 1000) * 1000);
      const hh = String(dt.getHours()).padStart(2, "0") + ":00";
      const pct = Math.max(3, Math.round((x.c / max) * 100));
      return `<div class="col" title="${esc(fmtInt(x.c))} 次 · ${esc(fmtInt(x.tk))} token">
        <div class="bar2" style="height:${pct}%"></div><div class="lbl">${hh}</div></div>`;
    }).join("");
  }

  $("usageRows").innerHTML = d.models.length ? d.models.map((m) => `<tr>
      <td>${esc(m.model || "—")}</td><td>${fmtInt(m.c)}</td><td>${fmtInt(m.tk)}</td>
      <td>${fmtCost(m.cost)}</td><td>${fmtMs(m.ttft)}</td></tr>`).join("")
    : `<tr><td colspan="5" style="color:var(--muted)">暂无数据</td></tr>`;
}

/* ---------------------------------------------------------------- 调用记录 */
async function loadRequests() {
  const q = new URLSearchParams({ page: S.reqPage, size: 20 });
  if ($("fq").value.trim()) q.set("q", $("fq").value.trim());
  if ($("fmodel").value.trim()) q.set("model", $("fmodel").value.trim());
  if ($("fstatus").value) q.set("status", $("fstatus").value);
  if ($("fprovider").value) q.set("provider", $("fprovider").value);
  const d = await api("/api/admin/requests?" + q.toString());
  S.reqTotal = d.total;
  $("reqHint").textContent = `共 ${fmtInt(d.total)} 条 · 第 ${d.page} 页`;
  $("pageInfo").textContent = `${d.page} / ${Math.max(1, Math.ceil(d.total / d.size))}`;
  $("reqRows").innerHTML = d.items.length ? d.items.map((r) => `<tr data-rid="${r.id}" style="cursor:pointer">
      <td class="mono" style="font-size:12px">${esc(fmtTime(r.created_at))}</td>
      <td>${r.user_id ? `<div class="name">${esc(r.username || "已删除用户")}</div><div class="sub mono">#${esc(r.user_id)}</div>` : "—"}</td>
      <td class="req-conv">${r.conversation_id ? `<div class="req-conv-title" title="${esc(r.conversation_title || '未命名对话')}">${esc(r.conversation_title || "未命名对话")}</div><div class="sub mono">#${esc(r.conversation_id)}</div>` : "—"}</td>
      <td><div class="name">${esc(r.model || "—")}</div><div class="sub mono">${esc(r.trace_id || "")}</div></td>
      <td><span class="src ${esc(r.provider || "")}">${esc(r.provider || "—")}</span></td>
      <td>${fmtInt(r.total_tokens)}${r.tokens_estimated ? `<div class="sub">估算</div>` : ""}</td>
      <td>${fmtMs(r.ttft_ms)}</td><td>${fmtMs(r.total_ms)}</td><td>${fmtCost(r.cost)}</td>
      <td class="status-${esc(r.status)}">${esc(r.status)}${r.error ? `<div class="sub" title="${esc(r.error)}">${esc(r.error.slice(0, 24))}</div>` : ""}</td>
    </tr>`).join("")
    : `<tr><td colspan="10" style="color:var(--muted)">没有匹配的记录</td></tr>`;
}

async function loadRequestDetail(rid) {
  const d = await api("/api/admin/requests/" + rid);
  const r = d.request;
  $("reqDetail").hidden = false;
  $("detailHint").textContent = "trace " + (r.trace_id || "");
  const kv = [
    ["状态", r.status], ["模型", r.model], ["来源", r.provider + (r.provider_id ? " #" + r.provider_id : "")],
    ["Prompt Token", fmtInt(r.prompt_tokens)], ["Completion Token", fmtInt(r.completion_tokens)],
    ["总 Token", fmtInt(r.total_tokens) + (r.tokens_estimated ? "（估算）" : "")],
    ["成本", fmtCost(r.cost) + `（$${r.price_in}/$${r.price_out} 每百万）`],
    ["首字", fmtMs(r.ttft_ms)], ["总耗时", fmtMs(r.total_ms)], ["排队", fmtMs(r.queue_ms)],
    ["用户", r.user_id ? `${r.username || "已删除用户"} · #${r.user_id}` : "—"],
    ["会话", r.conversation_id ? `#${r.conversation_id} · ${r.conversation_title || "未命名对话"}` : "—"], ["Prompt 版本", r.prompt_version || "—"],
    ["Prompt Hash", r.prompt_hash || "—"], ["路由决策", r.decision_json || "—"],
    ["参数", r.params_json || "—"], ["错误", r.error || "—"],
  ];
  const spans = d.spans.map((s) => `<span class="badge off">${esc(s.kind)} · ${esc(s.name || "")} ${fmtMs(s.dur_ms)}</span>`).join(" ");
  $("detailBody").innerHTML = kv.map(([k, v]) => `<div class="kv"><b>${esc(k)}</b><span>${esc(String(v ?? "—"))}</span></div>`).join("")
    + `<div class="kv" style="grid-column:1/-1"><b>Span</b><span>${spans || "—"}</span></div>`
    + `<pre>${esc(r.prompt_rendered || "（未记录 prompt）")}</pre>`;
  $("reqDetail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------------------------------------------------------------- 供应商 */
const PROVIDER_PRESETS = [
  { key: "deepseek", label: "DeepSeek", name: "deepseek", base: "https://api.deepseek.com/v1",
    models: "deepseek-chat,deepseek-reasoner", note: "DeepSeek 官方 API，Key 在 platform.deepseek.com 创建。" },
  { key: "dashscope", label: "阿里云百炼 / 通义千问", name: "dashscope", base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: "qwen-plus,qwen-max,qwen-turbo", note: "使用百炼的 OpenAI 兼容模式，Key 在阿里云百炼控制台创建。" },
  { key: "moonshot", label: "月之暗面 Kimi", name: "moonshot", base: "https://api.moonshot.cn/v1",
    models: "moonshot-v1-8k,moonshot-v1-32k,moonshot-v1-128k", note: "Kimi 官方 OpenAI 兼容接口。" },
  { key: "zhipu", label: "智谱 GLM", name: "zhipu", base: "https://open.bigmodel.cn/api/paas/v4",
    models: "glm-4-plus,glm-4-flash,glm-4-air", note: "智谱开放平台的 OpenAI 兼容接口。" },
  { key: "ark", label: "火山方舟 / 豆包", name: "ark", base: "https://ark.cn-beijing.volces.com/api/v3",
    models: "", note: "模型列表要填火山方舟的推理接入点 ID（ep-...），不是模型展示名。" },
  { key: "qianfan", label: "百度千帆 / 文心", name: "qianfan", base: "https://qianfan.baidubce.com/v2",
    models: "ernie-4.0-8k-latest,ernie-speed-128k", note: "使用千帆 v2 的 OpenAI 兼容接口。" },
  { key: "hunyuan", label: "腾讯混元", name: "hunyuan", base: "https://api.hunyuan.cloud.tencent.com/v1",
    models: "hunyuan-turbos-latest", note: "混元 OpenAI 兼容接口，模型名以控制台为准。" },
  { key: "siliconflow", label: "硅基流动 SiliconFlow", name: "siliconflow", base: "https://api.siliconflow.cn/v1",
    models: "deepseek-ai/DeepSeek-V3,Qwen/Qwen2.5-72B-Instruct", note: "聚合平台，模型名可直接从模型广场复制。" },
  { key: "openai", label: "OpenAI", name: "openai", base: "https://api.openai.com/v1",
    models: "gpt-4o-mini,gpt-4o", note: "OpenAI 官方接口。" },
  { key: "openrouter", label: "OpenRouter", name: "openrouter", base: "https://openrouter.ai/api/v1",
    models: "deepseek/deepseek-chat,openai/gpt-4o-mini", note: "聚合很多模型，模型名带供应商前缀。" },
  { key: "groq", label: "Groq", name: "groq", base: "https://api.groq.com/openai/v1",
    models: "llama-3.3-70b-versatile", note: "Groq 的 OpenAI 兼容接口，速度快。" },
  { key: "together", label: "Together AI", name: "together", base: "https://api.together.xyz/v1",
    models: "meta-llama/Llama-3.3-70B-Instruct-Turbo", note: "Together 的 OpenAI 兼容接口。" },
  { key: "mistral", label: "Mistral AI", name: "mistral", base: "https://api.mistral.ai/v1",
    models: "mistral-large-latest,mistral-small-latest", note: "Mistral 官方接口。" },
  { key: "ollama", label: "Ollama 本地", name: "ollama", base: "http://127.0.0.1:11434/v1",
    models: "qwen2.5:7b,llama3.1:8b", note: "本机 Ollama 的 OpenAI 兼容入口，API Key 可留空。" },
  { key: "vllm", label: "vLLM 本地", name: "vllm", base: "http://127.0.0.1:8000/v1",
    models: "", note: "vLLM 启动后默认提供 OpenAI 兼容接口，模型名填启动参数里的模型。" },
  { key: "lmstudio", label: "LM Studio 本地", name: "lmstudio", base: "http://127.0.0.1:1234/v1",
    models: "", note: "LM Studio 开启本地服务后使用，API Key 可留空。" },
  { key: "custom", label: "自定义 / 其他 OpenAI 兼容接口", name: "", base: "", models: "",
    note: "自己填写名称、Base URL 和模型；只要对方提供 OpenAI 兼容的 /v1 接口即可。" },
];

function renderProviderPresets() {
  const sel = $("pvPreset");
  if (!sel || sel.dataset.ready) return;
  sel.innerHTML = `<option value="">选择常见供应商（可修改）</option>` + PROVIDER_PRESETS.map((p) =>
    `<option value="${esc(p.key)}">${esc(p.label)}</option>`).join("");
  sel.dataset.ready = "1";
}

function applyProviderPreset(key) {
  const preset = PROVIDER_PRESETS.find((p) => p.key === key);
  const note = $("pvPresetNote");
  if (!preset) {
    if (note) note.textContent = "选择常见供应商会自动填入地址和模型，所有字段仍可修改；不在列表里就选最后一项“自定义”。";
    return;
  }
  $("pvName").value = preset.name;
  $("pvBase").value = preset.base;
  $("pvModels").value = preset.models;
  $("pvIn").value = "";
  $("pvOut").value = "";
  $("pvModels").placeholder = preset.key === "ark" ? "推理接入点 ID，如 ep-2024..." : "模型列表，逗号分隔";
  if (note) note.textContent = preset.note;
}

async function loadProviders() {
  renderProviderPresets();
  const d = await api("/api/admin/providers");
  S.providers = d.items;
  $("providerRows").innerHTML = d.items.length ? d.items.map((p) => `<tr>
      <td><div class="name">${esc(p.name)}</div><div class="sub">${esc(p.note || p.kind)}</div></td>
      <td>${esc(p.kind)}</td><td class="mono" style="font-size:12px">${esc(p.base_url)}</td>
      <td class="mono">${esc(p.api_key_masked || "—")}</td>
      <td>$${Number(p.price_in || 0).toFixed(2)} / $${Number(p.price_out || 0).toFixed(2)}</td>
      <td>${p.enabled ? `<span class="badge good">启用</span>` : `<span class="badge off">停用</span>`}</td>
      <td class="right"><div class="row-actions">
        <button class="btn small" data-ptest="${p.id}">测试</button>
        <button class="btn small" data-pdel="${p.id}">删除</button>
      </div></td></tr>`).join("")
    : `<tr><td colspan="7" style="color:var(--muted)">还没有接入第三方供应商，默认走本地模型</td></tr>`;
}

async function testProvider(id) {
  const r = await api(`/api/admin/providers/${id}/test`, { method: "POST" });
  uiToast(r.ok ? `连通，${r.ms}ms，发现 ${r.models.length} 个模型` : `失败 ${r.status}：${r.detail || "无法连接"}`);
}

/* ---------------------------------------------------------------- 路由 */
const ROUTE_FAMILIES = ["deepseek", "qwen", "llama", "mistral", "mixtral", "gemma", "phi", "glm", "yi", "command", "gpt"];

function routeProviderName(providerId, strategy) {
  if (!providerId) return strategy === "cloud_first" ? "云端自动（未绑定）" : "本地 / 不绑定";
  const p = (S.routeProviders || []).find((x) => Number(x.id) === Number(providerId));
  return p ? p.name : `#${providerId}`;
}

function routeCloudModels(provider) {
  return String(provider && provider.models || "")
    .split(",").map((x) => x.trim()).filter(Boolean);
}

function renderRouteProviderOptions() {
  const select = $("rtProvider");
  if (!select) return;
  const current = select.value || "local";
  const locals = S.routeModels || [];
  const providers = S.routeProviders || [];
  const localText = locals.length ? ` · ${locals.length} 个文字/代码模型` : "";
  let html = `<optgroup label="本地">`;
  html += `<option value="local">本地部署（llama.cpp）${esc(localText)}</option></optgroup>`;
  if (providers.length) {
    html += `<optgroup label="云端供应商">`;
    for (const p of providers) {
      const models = routeCloudModels(p);
      const suffix = models.length ? ` · ${models.length} 个模型` : " · 未填模型";
      html += `<option value="${p.id}">${esc(p.name)}${esc(suffix)}</option>`;
    }
    html += `</optgroup>`;
  } else {
    html += `<optgroup label="云端供应商"><option value="" disabled>还没有接入云端供应商</option></optgroup>`;
  }
  select.innerHTML = html;
  const exists = [...select.options].some((o) => o.value === current);
  select.value = exists ? current : "local";
}

async function loadRouteOptions() {
  try {
    const [models, providers] = await Promise.all([api("/api/models"), api("/api/admin/providers")]);
    const items = models.items || [];
    S.routeModels = items.filter((m) => m.installable && ["text", "code"].includes(m.category || "text"));
    S.routeLocalEnabled = models.local_enabled !== false;
    S.routeProviders = providers.items || [];
    renderRouteProviderOptions();
    const localNote = `${S.routeModels.length} 个文字/代码模型${S.routeLocalEnabled ? "" : "（本地部署当前关闭）"}`;
    const cloudNote = S.routeProviders.length ? `${S.routeProviders.length} 个云端供应商` : "还没有云端供应商";
    $("rtMapHint").className = "hint form-note";
    $("rtMapHint").textContent = `可用：本地 ${localNote} · 云端 ${cloudNote}。选云端供应商后点“自动匹配”，也可以手动填 JSON。`;
  } catch (e) {
    $("rtMapHint").className = "hint form-note warn";
    $("rtMapHint").textContent = "读取供应商失败：" + e.message;
  }
}

function autoRouteMap() {
  const pid = Number($("rtProvider").value || 0);
  if (!pid) throw new Error("先选择一个云端供应商；本地部署不需要模型映射");
  const provider = (S.routeProviders || []).find((p) => Number(p.id) === pid);
  if (!provider) throw new Error("供应商不存在，请刷新路由页");
  const cloudModels = routeCloudModels(provider);
  if (!cloudModels.length) throw new Error("这个供应商还没有填模型列表，请先到供应商页补齐");

  const mapping = {};
  const unmatched = [];
  for (const m of S.routeModels || []) {
    const key = String(m.key || "").trim();
    if (!key) continue;
    const identity = `${m.label || ""} ${m.family || ""} ${m.key || ""} ${m.alias || ""}`.toLowerCase();
    let target = cloudModels.find((cm) => cm.toLowerCase() === key.toLowerCase());
    if (!target) {
      const family = ROUTE_FAMILIES.find((f) => identity.includes(f));
      if (family) target = cloudModels.find((cm) => cm.toLowerCase().includes(family));
    }
    // 供应商只有一个模型时，用它兜底最稳，避免映射空着无法切换。
    if (!target && cloudModels.length === 1) target = cloudModels[0];
    if (target) mapping[key] = target;
    else unmatched.push(m.label || key);
  }

  const count = Object.keys(mapping).length;
  $("rtMap").value = count ? JSON.stringify(mapping) : "";
  $("rtMapHint").className = "hint form-note " + (count ? "ok" : "warn");
  if (!count) {
    $("rtMapHint").textContent = `没有找到与 ${provider.name} 同族的模型。请手动填，例如 {"7b":"${esc(cloudModels[0])}"}。`;
    return;
  }
  const tail = unmatched.length ? `；${unmatched.length} 个没有同族云端模型，可手动补` : "";
  const names = unmatched.slice(0, 3).join("、");
  $("rtMapHint").textContent = `已匹配 ${count} 个本地模型 → ${provider.name}${tail}${names ? `（${names}）` : ""}。`;
}

async function loadRoutes() {
  await loadRouteOptions();
  const d = await api("/api/admin/routes");
  $("routeRows").innerHTML = d.items.length ? d.items.map((r) => `<tr>
      <td><div class="name">${esc(r.name)}</div><div class="sub">${esc(r.note || "")}</div></td>
      <td><span class="badge ok">${esc(r.strategy)}</span></td>
      <td><span class="badge ${r.provider_id ? "good" : "off"}">${esc(routeProviderName(r.provider_id, r.strategy))}</span></td>
      <td class="mono" style="font-size:12px">${esc(r.model_map || "{}")}</td>
      <td>${r.enabled ? `<span class="badge good">启用</span>` : `<span class="badge off">停用</span>`}</td>
      <td class="right"><button class="btn small" data-rdel="${r.id}">删除</button></td></tr>`).join("")
    : `<tr><td colspan="6" style="color:var(--muted)">还没有路由策略，当前默认 local_first</td></tr>`;
}

/* ---------------------------------------------------------------- 用户与模型权限 */
function allowedCell(u) {
  const list = Array.isArray(u.allowed_models) ? u.allowed_models : [];
  if (u.role === "admin" || u.allowed_models === "*" || list.includes("*")) {
    return `<span class="badge good">全部模型</span>`;
  }
  if (!list.length) return `<span class="badge bad">未分配</span>`;
  return list.map((m) => `<span class="model-pill">${esc(m)}</span>`).join("");
}

function buildModelOptions(models, providers) {
  const options = [];
  (models.items || []).forEach((m) => options.push({
    value: m.key, label: m.label || m.key, group: "本地模型", extra: m.downloaded ? "" : "未下载",
  }));
  (providers.items || []).forEach((p) => {
    (p.models || "").split(",").map((x) => x.trim()).filter(Boolean).forEach((m) => {
      options.push({ value: m, label: m, group: "云端 · " + p.name, extra: "" });
    });
  });
  const seen = new Set();
  return options.filter((o) => (seen.has(o.value) ? false : (seen.add(o.value), true)));
}

async function loadUsers() {
  const [u, m, p, st, g, r] = await Promise.all([
    api("/api/users"), api("/api/models"), api("/api/admin/providers").catch(() => ({ items: [] })),
    api("/api/system/settings"), api("/api/users/groups"), api("/api/users/roles"),
  ]);
  S.users = u.items || [];
  S.groups = g.items || [];
  S.roles = r.items || [];
  S.roleModules = r.modules || [];
  S.modelOptions = buildModelOptions(m, p);
  if ($("allowRegister")) $("allowRegister").checked = !!st.allow_register;
  $("userHint").textContent = `共 ${S.users.length} 个账号 · ${S.groups.length} 个用户组 · ${S.roles.length} 个管理员角色`;
  const usageCell = (x) => {
    const today = `${fmtInt(x.today_tokens)}${x.daily_token_limit ? " / " + fmtInt(x.daily_token_limit) : " / 不限"}`;
    const month = `${fmtInt(x.month_tokens)}${x.monthly_token_limit ? " / " + fmtInt(x.monthly_token_limit) : " / 不限"}`;
    return `<div class="mono" style="font-size:12px">今日 ${today}</div><div class="sub mono">本月 ${month}</div>`;
  };
  $("userRows").innerHTML = S.users.length ? S.users.map((x) => `<tr>
      <td><div class="name">${esc(x.username)}</div><div class="sub mono">#${x.id}</div></td>
      <td><div>${x.role === "admin" ? `<span class="badge ok">${esc(x.admin_role_name || "超级管理员")}</span>` : `<span class="badge off">普通用户</span>`}</div><div class="sub">${esc(x.group_name || "未分组")}</div></td>
      <td>${x.disabled ? `<span class="badge bad">已禁用</span>` : `<span class="badge good">正常</span>`}</td>
      <td>${allowedCell(x)}</td>
      <td>${usageCell(x)}</td>
      <td class="mono" style="font-size:12px">${esc(fmtTime(x.last_login_at))}</td>
      <td class="right"><div class="row-actions">
        <button class="btn small" data-uedit="${x.id}">编辑</button>
        <button class="btn small" data-udel="${x.id}">删除</button>
      </div></td></tr>`).join("")
    : `<tr><td colspan="7" style="color:var(--muted)">还没有账号</td></tr>`;
  renderGroupRows();
  renderRoleRows();
  renderImportGroupOptions();
}

function renderGroupOptions(selected) {
  const sel = $("euGroup");
  if (!sel) return;
  sel.innerHTML = `<option value="">不分组</option>` +
    (S.groups || []).map((g) => `<option value="${g.id}" ${String(selected || "") === String(g.id) ? "selected" : ""}>${esc(groupOptionLabel(g))}</option>`).join("");
}

function renderRoleOptions(selected) {
  const sel = $("euAdminRole");
  if (!sel) return;
  sel.innerHTML = `<option value="">超级管理员（全部权限）</option>` +
    (S.roles || []).map((r) => `<option value="${r.id}" ${String(selected || "") === String(r.id) ? "selected" : ""}>${esc(r.name)}（${r.permissions.length} 项）</option>`).join("");
}

function renderGroupRows() {
  if (!$("groupRows")) return;
  $("groupRows").innerHTML = (S.groups || []).length ? S.groups.map((g) => `<tr>
      <td><div class="name">${esc(g.name)}</div><div class="sub mono">#${g.id}${g.sort ? ` · 排序 ${g.sort}` : ""}</div></td>
      <td>${esc(g.parent_name || "顶层")}</td>
      <td>${esc(g.leader_name || "未指定")}</td>
      <td>${fmtInt(g.members)}</td>
      <td>${esc(g.description || "—")}</td>
      <td class="right"><div class="row-actions">
        <button class="btn small" data-gedit="${g.id}">编辑</button>
        <button class="btn small" data-gdel="${g.id}">删除</button>
      </div></td></tr>`).join("")
    : `<tr><td colspan="6" style="color:var(--muted)">还没有部门 / 用户组，可先按团队或用途分组</td></tr>`;
}

function groupDescendantIds(gid) {
  const children = {};
  (S.groups || []).forEach((g) => {
    if (g.parent_id) (children[g.parent_id] = children[g.parent_id] || []).push(g.id);
  });
  const out = new Set();
  const walk = (id) => (children[id] || []).forEach((cid) => {
    if (!out.has(cid)) { out.add(cid); walk(cid); }
  });
  walk(gid);
  return out;
}

function groupOptionLabel(g) {
  return (g.parent_name ? `${g.parent_name} / ` : "") + g.name;
}

function renderGroupEditorOptions(group) {
  const blocked = group ? groupDescendantIds(group.id) : new Set();
  $("egParent").innerHTML = `<option value="">无上级（顶层）</option>` +
    (S.groups || []).filter((g) => !group || (g.id !== group.id && !blocked.has(g.id))).map((g) =>
      `<option value="${g.id}" ${group && String(group.parent_id || "") === String(g.id) ? "selected" : ""}>${esc(groupOptionLabel(g))}</option>`).join("");
  $("egLeader").innerHTML = `<option value="">未指定负责人</option>` +
    (S.users || []).filter((u) => u.role === "admin" || u.role === "user").map((u) =>
      `<option value="${u.id}" ${group && String(group.leader_id || "") === String(u.id) ? "selected" : ""}>${esc(u.username)}</option>`).join("");
}

function openGroupEditor(group) {
  S.editingGroup = group || null;
  $("groupEditor").hidden = false;
  $("egName").value = group ? group.name : "";
  $("egDesc").value = group ? group.description || "" : "";
  $("egSort").value = group ? Number(group.sort || 0) : 0;
  renderGroupEditorOptions(group);
  $("egName").focus();
}

async function saveGroup() {
  const name = $("egName").value.trim();
  const description = $("egDesc").value.trim();
  const parentValue = $("egParent").value;
  const leaderValue = $("egLeader").value;
  const sort = Number($("egSort").value || 0);
  if (!name) throw new Error("请填写部门 / 用户组名称");
  if (!Number.isFinite(sort)) throw new Error("排序需要是数字");
  const body = {
    name, description,
    parent_id: parentValue ? Number(parentValue) : null,
    leader_id: leaderValue ? Number(leaderValue) : null,
    sort: Math.trunc(sort),
  };
  if (S.editingGroup) {
    await api("/api/users/groups/" + S.editingGroup.id, { method: "PATCH", body: JSON.stringify(body) });
  } else {
    await api("/api/users/groups", { method: "POST", body: JSON.stringify(body) });
  }
  $("groupEditor").hidden = true;
  S.editingGroup = null;
  await loadUsers();
}

function renderImportGroupOptions() {
  if (!$("importGroup")) return;
  const current = $("importGroup").value;
  $("importGroup").innerHTML = `<option value="">默认不分组</option>` +
    (S.groups || []).map((g) => `<option value="${g.id}" ${current === String(g.id) ? "selected" : ""}>${esc(groupOptionLabel(g))}</option>`).join("");
}

function renderRoleRows() {
  if (!$("roleRows")) return;
  const labels = Object.fromEntries((S.roleModules || []).map((m) => [m.key, m.label]));
  $("roleRows").innerHTML = (S.roles || []).length ? S.roles.map((r) => `<tr>
      <td><div class="name">${esc(r.name)}</div><div class="sub mono">#${r.id}</div></td>
      <td>${fmtInt(r.members)}</td>
      <td>${r.is_super ? `<span class="badge ok">全部权限</span>` : `<div class="role-perms">${r.permissions.map((p) => `<span class="badge">${esc(labels[p] || p)}</span>`).join("") || `<span class="sub">未配置</span>`}</div>`}</td>
      <td class="right"><div class="row-actions">
        <button class="btn small" data-redit="${r.id}">编辑</button>
        <button class="btn small" data-rdel="${r.id}">删除</button>
      </div></td></tr>`).join("")
    : `<tr><td colspan="4" style="color:var(--muted)">还没有自定义管理员角色；未绑定角色的管理员默认拥有全部权限</td></tr>`;
}

function renderRolePermPicker(selected) {
  const set = new Set(selected || []);
  $("erPerms").innerHTML = (S.roleModules || []).map((m) => `<label><input type="checkbox" value="${esc(m.key)}" ${set.has(m.key) ? "checked" : ""}><span>${esc(m.label)}</span></label>`).join("");
}

function openRoleEditor(role) {
  S.editingRole = role || null;
  $("roleEditor").hidden = false;
  $("erName").value = role ? role.name : "";
  renderRolePermPicker(role ? role.permissions : []);
  $("erName").focus();
}

async function saveRole() {
  const name = $("erName").value.trim();
  const permissions = Array.from(document.querySelectorAll("#erPerms input[type=checkbox]:checked")).map((x) => x.value);
  if (!name) throw new Error("请填写角色名称");
  if (!permissions.length) throw new Error("请至少勾选一项权限");
  const body = { name, permissions };
  if (S.editingRole) {
    await api("/api/users/roles/" + S.editingRole.id, { method: "PATCH", body: JSON.stringify(body) });
  } else {
    await api("/api/users/roles", { method: "POST", body: JSON.stringify(body) });
  }
  $("roleEditor").hidden = true;
  S.editingRole = null;
  await loadUsers();
}

async function loadOrgPage() {
  const d = await api("/api/admin/org");
  $("orgName").value = d.org_name || "";
  $("orgShort").value = d.org_short_name || "";
  $("orgDomain").value = d.org_domain || "";
  $("orgIndustry").value = d.org_industry || "";
  $("orgSize").value = d.org_size || "";
  $("orgContactName").value = d.org_contact_name || "";
  $("orgContactEmail").value = d.org_contact_email || "";
  $("brandTagline").value = d.brand_tagline || "";
  $("brandLoginTitle").value = d.brand_login_title || "";
  $("brandLoginLead").value = d.brand_login_lead || "";
  $("brandAuthSubtitle").value = d.brand_auth_subtitle || "";
  $("brandLoginFoot").value = d.brand_login_foot || "";
  $("brandPrimary").value = BRAND_COLOR_RE.test(d.brand_primary || "") ? d.brand_primary : "#4f6ef7";
  $("brandPrimaryText").value = $("brandPrimary").value;
  $("brandIcp").value = d.brand_icp || "";
  $("brandIcpUrl").value = d.brand_icp_url || "";
  $("brandPolice").value = d.brand_police || "";
  $("brandPoliceUrl").value = d.brand_police_url || "";
  $("brandCopyright").value = d.brand_copyright || "";
  $("wmEnabled").checked = !!d.watermark_enabled;
  $("wmText").value = d.watermark_text || "";
  $("orgSaveHint").textContent = "";
  S.branding = d;
  renderBrandLogo(d.brand_logo_url || "");
  renderBrandPreview(d);
}

const BRAND_COLOR_RE = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const BRAND_PREVIEW_IDS = new Set(["orgName", "brandTagline", "brandLoginTitle", "brandLoginLead",
  "brandAuthSubtitle", "brandLoginFoot", "brandIcp", "brandPolice", "brandCopyright",
  "brandPrimary", "brandPrimaryText"]);

function brandColorValue(value) {
  const text = String(value || "").trim();
  return BRAND_COLOR_RE.test(text) ? text : "#4f6ef7";
}

function previewLegal(box, d) {
  if (!box) return;
  box.textContent = "";
  const bits = [d.brand_icp, d.brand_police].filter(Boolean);
  const copy = d.brand_copyright || `© ${new Date().getFullYear()} ${d.org_name || "本地 AI 工作台"}`;
  [...bits, copy].forEach((text, i) => {
    if (i) {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "·";
      box.appendChild(sep);
    }
    const span = document.createElement("span");
    span.textContent = text;
    box.appendChild(span);
  });
}

function renderBrandLogo(url) {
  const box = $("brandLogoPreview");
  const img = $("brandLogoPreviewImg");
  if (!box || !img) return;
  const svg = $("svg", box);
  if (url) {
    img.src = url;
    img.hidden = false;
    if (svg) svg.hidden = true;
    box.classList.add("has-image");
  } else {
    img.removeAttribute("src");
    img.hidden = true;
    if (svg) svg.hidden = false;
    box.classList.remove("has-image");
  }
  const preview = $("brandPreviewLogo");
  const previewImg = $("brandPreviewLogoImg");
  if (preview && previewImg) {
    const previewSvg = $("svg", preview);
    if (url) {
      previewImg.src = url;
      previewImg.hidden = false;
      if (previewSvg) previewSvg.hidden = true;
      preview.classList.add("has-image");
    } else {
      previewImg.removeAttribute("src");
      previewImg.hidden = true;
      if (previewSvg) previewSvg.hidden = false;
      preview.classList.remove("has-image");
    }
  }
}

function renderBrandPreview(d) {
  const card = $("brandPreviewCard");
  if (!card) return;
  const color = brandColorValue(d.brand_primary);
  card.style.setProperty("--brand", color);
  card.style.setProperty("--brand-2", `color-mix(in srgb, ${color} 68%, #7b61ff)`);
  card.style.setProperty("--brand-ink", `color-mix(in srgb, ${color} 62%, #172033)`);
  card.style.setProperty("--brand-soft", `color-mix(in srgb, ${color} 11%, #ffffff)`);
  $("brandPreviewName").textContent = d.org_name || "本地 AI 工作台";
  $("brandPreviewTagline").textContent = d.brand_tagline || "Local AI Workbench";
  $("brandPreviewTitle").textContent = d.brand_login_title || "你的模型，\n只为你的账号工作。";
  $("brandPreviewLead").textContent = d.brand_login_lead || "";
  $("brandPreviewSub").textContent = d.brand_auth_subtitle || "使用工作台账号继续对话";
  $("brandPreviewFoot").textContent = d.brand_login_foot || "";
  previewLegal($("brandPreviewLegal"), d);
  renderBrandLogo(d.brand_logo_url || "");
}

function brandFormData() {
  return {
    org_name: $("orgName").value.trim(),
    org_short_name: $("orgShort").value.trim(),
    org_domain: $("orgDomain").value.trim(),
    org_industry: $("orgIndustry").value.trim(),
    org_size: $("orgSize").value.trim(),
    org_contact_name: $("orgContactName").value.trim(),
    org_contact_email: $("orgContactEmail").value.trim(),
    brand_tagline: $("brandTagline").value.trim(),
    brand_login_title: $("brandLoginTitle").value.trim(),
    brand_login_lead: $("brandLoginLead").value.trim(),
    brand_auth_subtitle: $("brandAuthSubtitle").value.trim(),
    brand_login_foot: $("brandLoginFoot").value.trim(),
    brand_primary: brandColorValue($("brandPrimaryText").value),
    brand_icp: $("brandIcp").value.trim(),
    brand_icp_url: $("brandIcpUrl").value.trim(),
    brand_police: $("brandPolice").value.trim(),
    brand_police_url: $("brandPoliceUrl").value.trim(),
    brand_copyright: $("brandCopyright").value.trim(),
    watermark_enabled: $("wmEnabled").checked,
    watermark_text: $("wmText").value.trim() || "{user} · {org} · 内部资料",
  };
}

function updateBrandPreviewFromForm() {
  const d = brandFormData();
  d.brand_logo_url = S.branding?.brand_logo_url || "";
  renderBrandPreview(d);
}

async function saveOrg() {
  const body = brandFormData();
  if (!body.org_name) throw new Error("品牌名称不能为空");
  if (!BRAND_COLOR_RE.test($("brandPrimaryText").value.trim())) throw new Error("品牌主色需为 #RGB 或 #RRGGBB");
  const r = await api("/api/admin/org", { method: "PUT", body: JSON.stringify(body) });
  $("orgSaveHint").textContent = "已保存";
  const branding = r.branding || body;
  S.branding = branding;
  applyBranding(branding, S.me ? S.me.username : "");
  renderBrandPreview({ ...body, ...branding });
  uiToast("前端页面设置已保存");
}

async function uploadBrandLogo(file) {
  if (!file) return;
  if (file.size > 3 * 1024 * 1024) throw new Error("Logo 不能超过 3 MB");
  if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
    throw new Error("Logo 仅支持 PNG、JPG、WebP 或 GIF");
  }
  const btn = $("brandLogoUploadBtn");
  btn.disabled = true;
  $("brandLogoHint").textContent = "正在上传…";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await api("/api/admin/org/logo", { method: "POST", body: fd });
    if (!S.branding) S.branding = {};
    S.branding.brand_logo_url = r.url;
    renderBrandLogo(r.url);
    $("brandLogoHint").textContent = `已上传 · ${(r.size / 1024).toFixed(1)} KB · 已立即生效`;
    const preview = brandFormData();
    preview.brand_logo_url = r.url;
    renderBrandPreview(preview);
    uiToast("Logo 已更新");
  } finally {
    btn.disabled = false;
    $("brandLogoFile").value = "";
  }
}

async function removeBrandLogo() {
  const btn = $("brandLogoRemoveBtn");
  btn.disabled = true;
  try {
    await api("/api/admin/org/logo", { method: "DELETE" });
    if (!S.branding) S.branding = {};
    S.branding.brand_logo_url = "";
    renderBrandLogo("");
    $("brandLogoHint").textContent = "已恢复默认图标。";
    updateBrandPreviewFromForm();
    uiToast("已恢复默认 Logo");
  } finally {
    btn.disabled = false;
  }
}

const MOD_ACTION_LABELS = { block: "拦截", replace: "替换", warn: "仅告警" };

async function loadModerationPage() {
  const q = $("modWordSearch") ? $("modWordSearch").value.trim() : "";
  const direction = $("modHitDirection") ? $("modHitDirection").value : "";
  const d = await api("/api/admin/moderation?word_q=" + encodeURIComponent(q) +
    "&direction=" + encodeURIComponent(direction));
  const s = d.settings || {};
  $("modEnabled").checked = !!s.enabled;
  $("modInputAction").value = s.input_action || "block";
  $("modOutputAction").value = s.output_action || "replace";
  $("modReplace").value = s.replace_with || "***";
  $("modMinChars").value = String(s.min_chars || 1);
  $("moderationSaveHint").textContent = s.enabled
    ? `已开启 · 词库 ${d.stats.enabled_words} 个启用词 · 24 小时命中 ${d.stats.hits_24h} 次`
    : "当前未开启；保存策略后立即对新请求生效";
  S.modWords = d.words || [];
  renderModerationWords(S.modWords);
  renderModerationHits(d.hits || []);
}

function renderModerationWords(rows) {
  const body = $("modWordRows");
  body.innerHTML = rows.map((w) => `
    <tr>
      <td><b>${esc(w.word)}</b></td>
      <td>${esc(w.category || "未分类")}</td>
      <td>${esc(w.note || "—")}</td>
      <td><span class="badge ${w.enabled ? "good" : "bad"}">${w.enabled ? "启用" : "停用"}</span></td>
      <td>${fmtTime(w.created_at)}</td>
      <td class="right">
        <button class="btn ghost small" data-mtoggle="${w.id}">${w.enabled ? "停用" : "启用"}</button>
        <button class="btn ghost small" data-mdel="${w.id}">删除</button>
      </td>
    </tr>`).join("");
  $("modWordEmpty").hidden = rows.length > 0;
}

function renderModerationHits(rows) {
  $("modHitRows").innerHTML = rows.map((h) => `
    <tr>
      <td>${fmtTime(h.created_at)}</td>
      <td>${esc(h.username || "—")}</td>
      <td>${h.direction === "input" ? "用户输入" : "模型输出"}</td>
      <td>${esc(MOD_ACTION_LABELS[h.action] || h.action)}</td>
      <td>${(h.words || []).map((w) => `<span class="badge bad">${esc(w)}</span>`).join(" ") || "—"}</td>
      <td title="${esc(h.snippet || "")}">${esc((h.snippet || "").slice(0, 60))}${(h.snippet || "").length > 60 ? "…" : ""}</td>
      <td>${esc(h.model || "—")}</td>
    </tr>`).join("");
  $("modHitEmpty").hidden = rows.length > 0;
}

async function saveModeration() {
  const body = {
    enabled: $("modEnabled").checked,
    input_action: $("modInputAction").value,
    output_action: $("modOutputAction").value,
    replace_with: $("modReplace").value.trim() || "***",
    min_chars: Number($("modMinChars").value || 1),
  };
  await api("/api/admin/moderation", { method: "PUT", body: JSON.stringify(body) });
  uiToast("内容安全策略已保存");
  await loadModerationPage();
}

async function addModerationWord() {
  const word = $("modWordInput").value.trim();
  const category = $("modWordCategory").value.trim();
  if (!word) throw new Error("请先输入要加入的敏感词");
  await api("/api/admin/moderation/words", {
    method: "POST",
    body: JSON.stringify({ word, category, enabled: true }),
  });
  $("modWordInput").value = "";
  uiToast("已加入词库");
  await loadModerationPage();
}

async function bulkModerationWords() {
  const text = $("modWordBulk").value.trim();
  if (!text) throw new Error("请先粘贴敏感词");
  const r = await api("/api/admin/moderation/words/bulk", {
    method: "POST",
    body: JSON.stringify({ text, category: $("modBulkCategory").value.trim(), enabled: true }),
  });
  $("modBulkHint").textContent = `新增 ${r.created} 个，跳过重复 ${r.skipped} 个` +
    (r.errors && r.errors.length ? `，失败 ${r.errors.length} 个` : "");
  $("modWordBulk").value = "";
  await loadModerationPage();
}

async function toggleModerationWord(id) {
  const w = (S.modWords || []).find((x) => String(x.id) === String(id));
  if (!w) return;
  await api("/api/admin/moderation/words/" + id, {
    method: "PATCH", body: JSON.stringify({ enabled: !w.enabled }),
  });
  await loadModerationPage();
}

async function deleteModerationWord(id) {
  const w = (S.modWords || []).find((x) => String(x.id) === String(id));
  if (!(await confirmInline(`从词库删除“${w ? w.word : ""}”？`, "确认删除"))) return;
  await api("/api/admin/moderation/words/" + id, { method: "DELETE" });
  await loadModerationPage();
}

async function clearModerationHits() {
  if (!(await confirmInline("清空全部内容安全命中记录？", "确认清空"))) return;
  await api("/api/admin/moderation/hits", { method: "DELETE" });
  uiToast("命中记录已清空");
  await loadModerationPage();
}

function renderModelPicker(selected, all) {
  const groups = [];
  S.modelOptions.forEach((o) => {
    let g = groups.find((x) => x.name === o.group);
    if (!g) { g = { name: o.group, items: [] }; groups.push(g); }
    g.items.push(o);
  });
  $("euModels").innerHTML = groups.length ? groups.map((g) => `
      <div class="group">${esc(g.name)}</div>
      ${g.items.map((o) => `<label><input type="checkbox" value="${esc(o.value)}"
        ${selected.has(o.value) ? "checked" : ""} ${all ? "disabled" : ""}>
        <span>${esc(o.label)}${o.extra ? `<span class="sub">${esc(o.extra)}</span>` : ""}</span></label>`).join("")}
    `).join("") : `<div class="empty">还没有可分配的模型，请先在“部署与模型”或“供应商”里添加</div>`;
  $("euAll").checked = all;
}

function openUserEditor(user) {
  S.editingUser = user || null;
  $("userEditor").hidden = false;
  $("userEditorTitle").textContent = user ? `编辑用户 · ${user.username}` : "新建用户";
  $("euName").value = user ? user.username : "";
  $("euName").disabled = !!user;
  $("euPass").value = "";
  $("euPass").placeholder = user ? "新密码（至少 8 位，留空不改）" : "密码（至少 8 位）";
  $("euRole").value = user ? user.role : "user";
  $("euDisabled").checked = !!(user && user.disabled);
  $("euDaily").value = user && user.daily_token_limit ? user.daily_token_limit : "";
  $("euMonthly").value = user && user.monthly_token_limit ? user.monthly_token_limit : "";
  renderGroupOptions(user ? user.group_id : null);
  renderRoleOptions(user ? user.admin_role_id : null);
  syncAdminRoleSelect();
  const list = user && Array.isArray(user.allowed_models) ? user.allowed_models : [];
  const all = !user || user.role === "admin" || user.allowed_models === "*" || list.includes("*");
  renderModelPicker(new Set(list), all);
  $("userEditor").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function syncAdminRoleSelect() {
  const isAdmin = $("euRole").value === "admin";
  $("euAdminRole").disabled = !isAdmin;
  if (!isAdmin) $("euAdminRole").value = "";
}

async function saveUser() {
  const id = S.editingUser ? S.editingUser.id : null;
  const username = $("euName").value.trim();
  const password = $("euPass").value;
  const role = $("euRole").value;
  const groupValue = $("euGroup").value;
  const roleValue = $("euAdminRole").value;
  const daily = Number($("euDaily").value || 0);
  const monthly = Number($("euMonthly").value || 0);
  if (!Number.isFinite(daily) || daily < 0 || !Number.isFinite(monthly) || monthly < 0) {
    throw new Error("Token 配额必须是不小于 0 的整数");
  }
  const allowed = $("euAll").checked
    ? ["*"]
    : Array.from(document.querySelectorAll("#euModels input[type=checkbox]:checked")).map((x) => x.value);
  if (!id && username.length < 2) throw new Error("用户名至少 2 位");
  if (!id && password.length < 8) throw new Error("密码至少 8 位");
  if (id && password && password.length < 8) throw new Error("密码至少 8 位");
  if (!allowed.length) throw new Error("请至少分配一个模型，或勾选“全部模型”");
  const common = {
    role,
    group_id: groupValue ? Number(groupValue) : null,
    admin_role_id: role === "admin" && roleValue ? Number(roleValue) : null,
    daily_token_limit: Math.floor(daily),
    monthly_token_limit: Math.floor(monthly),
  };
  if (id) {
    const body = { ...common, disabled: $("euDisabled").checked, allowed_models: allowed };
    if (password) body.new_password = password;
    await api("/api/users/" + id, { method: "PATCH", body: JSON.stringify(body) });
  } else {
    const body = { ...common, username, password, allowed_models: allowed };
    const r = await api("/api/users", { method: "POST", body: JSON.stringify(body) });
    if ($("euDisabled").checked && r.id) {
      await api("/api/users/" + r.id, { method: "PATCH", body: JSON.stringify({ disabled: true }) });
    }
  }
  $("userEditor").hidden = true;
  S.editingUser = null;
  await loadUsers();
}

/* ---------------------------------------------------------------- 登录方式 */
let AUTH_ITEMS = [];

function authFieldHTML(field, item, value) {
  const key = field.key;
  const hasSecret = !!item.secrets[key];
  const val = value === undefined || value === null ? "" : value;
  const req = field.required ? ' <span style="color:#d9534f">*</span>' : "";
  const help = field.help ? `<div class="fh">${esc(field.help)}</div>` : "";
  if (field.type === "checkbox") {
    const on = val === true || val === "true" || val === 1 || val === "1";
    return `<div class="auth-field"><label class="checkline"><input data-field="${esc(key)}" type="checkbox" ${on ? "checked" : ""}> ${esc(field.label)}${req}</label>${help}</div>`;
  }
  if (field.type === "select") {
    const opts = (field.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("");
    return `<div class="auth-field"><label>${esc(field.label)}${req}</label><select data-field="${esc(key)}">${opts}</select>${help}</div>`;
  }
  if (field.type === "textarea") {
    return `<div class="auth-field span2"><label>${esc(field.label)}${req}</label><textarea data-field="${esc(key)}" placeholder="${esc(field.placeholder || "")}">${esc(val)}</textarea>${help}</div>`;
  }
  const type = field.type === "number" ? "number" : (field.type === "password" ? "password" : "text");
  const ph = hasSecret ? "已保存，留空不修改" : (field.placeholder || "");
  return `<div class="auth-field"><label>${esc(field.label)}${req}</label><input data-field="${esc(key)}" type="${type}" value="${esc(val)}" placeholder="${esc(ph)}" autocomplete="off">${help}</div>`;
}

function authFieldBlock(provider, fields, item, hidden, vendorKey = "", vendor = null) {
  return `<div class="auth-vendor-block" ${hidden ? "hidden" : ""} data-block-fields data-vendor="${esc(vendorKey)}">
    <div class="auth-fields">${fields.map((f) => {
      let value = item.settings[f.key];
      if (f.key === "redirect_uri" && (value === undefined || value === "" || value === null) && item.callback_url) {
        value = item.callback_url;
      }
      if ((value === undefined || value === "" || value === null) && vendor && vendor.defaults && f.key in vendor.defaults) {
        value = vendor.defaults[f.key];
      }
      return authFieldHTML(f, item, value);
    }).join("")}</div>
  </div>`;
}

function authGuideHTML(guide) {
  if (!guide || !guide.steps) return "";
  const links = (guide.links || []).map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noreferrer">${esc(l.label)} ↗</a>`).join("");
  return `<details class="auth-guide">
    <summary>${esc(guide.title || "接入教程")}</summary>
    <ol>${guide.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
    ${links ? `<div class="links">${links}</div>` : ""}
    ${guide.note ? `<p class="gnote">${esc(guide.note)}</p>` : ""}
  </details>`;
}

function authCard(item) {
  if (!item.editable) return "";
  const vendor = item.vendor || "";
  const vendorKey = item.vendor_key || "";
  const vendors = item.vendors || [];
  const current = vendors.find((v) => v.key === vendor) || vendors[0];
  const fields = current ? current.fields : (item.fields || []);
  const blocks = vendors.length
    ? vendors.map((v) => authFieldBlock(item.key, v.fields, item, v.key !== (current ? current.key : ""), v.key, v)).join("")
    : authFieldBlock(item.key, fields, item, false, "", null);
  const badge = item.enabled
    ? (item.ready ? `<span class="badge good">已启用</span>` : `<span class="badge warn">配置不完整</span>`)
    : `<span class="badge off">未启用</span>`;
  const sub = item.mode === "oauth" ? "扫码授权登录"
    : (item.mode === "otp" ? "验证码登录" : "账号密码登录");
  const vendorBar = vendors.length ? `<div class="auth-vendor-bar">
      <label>选择供应商</label>
      <select data-auth-vendor="${esc(item.key)}">${vendors.map((v) => `<option value="${esc(v.key)}" ${v.key === (current ? current.key : "") ? "selected" : ""}>${esc(v.label)}</option>`).join("")}</select>
      <button class="btn ghost small" data-auth-fill="${esc(item.key)}">填入推荐值</button>
      <span class="hint" data-vendor-desc>${esc(current ? current.description : "")}</span>
    </div>` : "";
  const test = (item.key === "phone" || item.key === "email")
    ? `<div class="auth-test"><input data-auth-target="${esc(item.key)}" placeholder="${item.key === "phone" ? "接收测试短信的手机号" : "接收测试邮件的邮箱"}"><button class="btn ghost small" data-auth-test="${esc(item.key)}">发送测试</button></div>`
    : `<div class="auth-test"><button class="btn ghost small" data-auth-test="${esc(item.key)}">检查配置 / 打开授权页</button></div>`;
  return `<section class="panel auth-card" data-auth-card="${esc(item.key)}" data-vendor-key="${esc(vendorKey)}">
    <div class="auth-card-head">
      <div>
        <div class="auth-title"><h2>${esc(item.label)}</h2>${badge}<span class="badge ok">${esc(sub)}</span></div>
        <div class="auth-sub">${esc(item.key === "qq" || item.key === "wechat" ? "OAuth 扫码登录，需要在开放平台创建网站应用。" : "验证码登录；可直接选常见服务商，也可选“自定义”接入其他平台。")}</div>
      </div>
      <label class="checkline"><input data-auth-enabled type="checkbox" ${item.enabled ? "checked" : ""}> 启用</label>
    </div>
    ${vendorBar}
    ${blocks}
    ${authGuideHTML(item.guide)}
    <div class="auth-bottom">
      ${test}
      <button class="btn primary small" data-auth-save="${esc(item.key)}">保存</button>
    </div>
    <div class="auth-result" data-auth-result></div>
  </section>`;
}

async function loadAuthProviders() {
  const d = await api("/api/admin/auth-providers");
  AUTH_ITEMS = d.items || [];
  $("authNote").textContent = d.note || "";
  $("authStatusRow").innerHTML = AUTH_ITEMS.map((item) => {
    const cls = item.enabled ? (item.ready ? "on" : "warn") : "";
    const text = item.enabled ? (item.ready ? "已启用" : "配置不完整") : "未启用";
    return `<span class="auth-chip ${cls}"><span class="dot ${item.enabled ? (item.ready ? "on" : "warn") : ""}"></span>${esc(item.label)} · ${text}</span>`;
  }).join("");
  $("authProviderCards").innerHTML = AUTH_ITEMS.filter((x) => x.editable).map(authCard).join("")
    || `<div class="auth-empty">没有可配置的登录方式</div>`;
}

function authFillDefaults(card) {
  const provider = card.dataset.authCard;
  const item = AUTH_ITEMS.find((x) => x.key === provider);
  if (!item) return;
  const vendorKey = card.dataset.vendorKey;
  const vendor = item.vendors.find((v) => v.key === (vendorKey ? card.querySelector(`[data-auth-vendor="${provider}"]`).value : ""));
  if (!vendor) return;
  const block = card.querySelector(`[data-block-fields]:not([hidden])`);
  if (!block) return;
  const defaults = vendor.defaults || {};
  block.querySelectorAll("[data-field]").forEach((el) => {
    const key = el.dataset.field;
    if (!(key in defaults)) return;
    if (el.type === "checkbox") el.checked = !!defaults[key];
    else el.value = defaults[key];
  });
}

function authCollect(card) {
  const provider = card.dataset.authCard;
  const body = { enabled: card.querySelector("[data-auth-enabled]").checked };
  const vendorKey = card.dataset.vendorKey;
  if (vendorKey) {
    const sel = card.querySelector(`[data-auth-vendor="${provider}"]`);
    if (sel) body[vendorKey] = sel.value;
  }
  const block = card.querySelector("[data-block-fields]:not([hidden])");
  if (block) block.querySelectorAll("[data-field]").forEach((el) => {
    const key = el.dataset.field;
    if (el.type === "checkbox") body[key] = el.checked;
    else if (el.type === "number") body[key] = Number(el.value || 0);
    else body[key] = el.value;
  });
  return body;
}

/* ---------------------------------------------------------------- API 管理 */
function apiScopeBadge(net) {
  const scope = net.scope || "local";
  const cls = scope === "external" ? "external" : (scope === "lan" ? "lan" : "local");
  $("apiScopeBadge").className = "scope-badge scope-" + cls;
  $("apiScopeBadge").textContent = `${net.label || "本机"}访问`;
  $("apiScopeHint").textContent = `${net.hint || ""} 客户端 IP：${net.client_ip || "—"} · 当前地址：${net.current_base || "—"}`;
}

function apiUrlCard(item, recommended) {
  const url = String(item.url || "");
  const isPublic = item.key === "public";
  const note = isPublic && !url
    ? (S.apiCtx && S.apiCtx.tunnel && S.apiCtx.tunnel.running && S.apiCtx.tunnel.target !== "panel"
      ? "当前穿透目标是模型 API，不是管理控制台；请在“网络”页把穿透目标改为“管理控制台”。"
      : "尚未开启内网穿透。需要在外网使用时，去“网络”页一键开启。")
    : (item.note || "");
  return `<div class="api-url-card ${recommended ? "recommended" : ""}">
    <div class="cap"><b>${esc(item.label)}</b>${recommended ? `<span class="badge ok">推荐</span>` : ""}</div>
    <div class="url ${url ? "" : "empty"}">${url ? esc(url) : "暂不可用"}</div>
    <div class="note">${esc(note)}</div>
    <div class="card-actions">
      ${url ? `<button class="btn small" data-copy="${esc(url)}">复制地址</button>` : ""}
      ${isPublic && !url ? `<button class="btn small" data-goto="network">去开启穿透</button>` : ""}
    </div>
  </div>`;
}

function renderApiUrls(ctx) {
  const urls = ctx.urls || [];
  const recommended = (ctx.api || {}).recommended_base || "";
  const ordered = ["recommended", "local", "lan", "public"]
    .map((k) => urls.find((x) => x.key === k))
    .filter(Boolean);
  $("apiUrls").innerHTML = ordered.map((u) => apiUrlCard(u, u.url === recommended)).join("");
}

function renderApiKeys() {
  const admin = !!(S.apiCtx && S.apiCtx.user && S.apiCtx.user.role === "admin");
  const cols = admin
    ? ["用户", "名称", "Key", "创建时间", "最后使用", "来源", "状态", "操作"]
    : ["名称", "Key", "创建时间", "最后使用", "来源", "状态", "操作"];
  $("apiKeyHead").innerHTML = `<tr>${cols.map((c) =>
    `<th class="${c === "操作" ? "right" : ""}">${c}</th>`).join("")}</tr>`;
  const rows = S.apiKeys || [];
  if (!rows.length) {
    $("apiKeyRows").innerHTML = `<tr><td colspan="${cols.length}" style="color:var(--muted)">
      还没有 API Key。给 Key 起个名字，点“生成 API Key”即可。</td></tr>`;
    return;
  }
  $("apiKeyRows").innerHTML = rows.map((k) => {
    const cells = [];
    if (admin) cells.push(`<td><div class="name">${esc(k.username || "—")}</div><div class="sub mono">#${k.id}</div></td>`);
    cells.push(`<td><div class="name">${esc(k.name)}</div></td>`);
    cells.push(`<td class="mono" style="font-size:12px">${esc(k.masked)}</td>`);
    cells.push(`<td class="mono" style="font-size:12px">${esc(fmtTime(k.created_at))}</td>`);
    cells.push(`<td class="mono" style="font-size:12px">${k.last_used_at ? esc(fmtTime(k.last_used_at)) : "从未使用"}</td>`);
    cells.push(`<td>${k.last_scope ? esc(k.last_scope) : "—"}${k.last_ip ? `<div class="sub mono">${esc(k.last_ip)}</div>` : ""}</td>`);
    cells.push(`<td>${k.revoked ? `<span class="badge bad">已撤销</span>` : `<span class="badge good">正常</span>`}</td>`);
    cells.push(`<td class="right">${k.revoked ? "—" : `<button class="btn small" data-arevoke="${k.id}">撤销</button>`}</td>`);
    return `<tr>${cells.join("")}</tr>`;
  }).join("");
}

function renderApiDocs(ctx) {
  const base = String((ctx.api || {}).recommended_base || "").replace(/\/$/, "");
  const model = ctx.default_model || (ctx.models && ctx.models[0] && ctx.models[0].id) || "7b";
  const url = `${base}/chat/completions`;
  const curl = `curl "${url}" \\
  -H "Authorization: Bearer <你的 API Key>" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"${model}","messages":[{"role":"user","content":"你好"}],"stream":false}'`;
  const py = `from openai import OpenAI

client = OpenAI(
    base_url="${base}",
    api_key="<你的 API Key>",
)

resp = client.chat.completions.create(
    model="${model}",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)`;
  $("apiCurl").textContent = curl;
  $("apiPython").textContent = py;
  $("apiCopyCurl").dataset.copy = curl;
  $("apiCopyPython").dataset.copy = py;
  $("apiEndpointText").textContent = url;
  $("apiModelsEndpointText").textContent = `${base}/models`;
  const models = ctx.models || [];
  $("apiModels").innerHTML = models.length
    ? models.map((m) => `<span title="${esc(m.label)} · ${esc(m.owned_by)}">${esc(m.id)}</span>`).join("")
    : `<span class="empty">暂无可用模型，请让管理员在“用户”页分配模型。</span>`;
}

async function loadApi() {
  const all = !!(S.apiIsAdmin && $("apiAllKeys") && $("apiAllKeys").checked);
  const [ctx, keys] = await Promise.all([
    api("/api/api-keys/context"),
    api("/api/api-keys" + (all ? "?all=true" : "")),
  ]);
  S.apiCtx = ctx;
  S.apiIsAdmin = !!(ctx.user && ctx.user.role === "admin");
  S.apiKeys = keys.items || [];
  $("apiAllWrap").hidden = !S.apiIsAdmin;
  $("apiKeyHint").textContent = S.apiIsAdmin
    ? "Key 等同于密码，只显示一次；管理员可查看所有用户的 Key 状态"
    : "Key 等同于密码，只显示一次，请妥善保存";
  apiScopeBadge(ctx.network || {});
  renderApiUrls(ctx);
  renderApiKeys();
  renderApiDocs(ctx);
}

async function createApiKey() {
  const btn = $("createApiKeyBtn");
  btn.disabled = true;
  btn.textContent = "生成中…";
  try {
    const d = await api("/api/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: $("apiKeyName").value.trim() }),
    });
    $("apiKeyName").value = "";
    $("apiNewKey").hidden = false;
    $("apiNewKeyValue").value = d.key;
    $("apiNewKeyCopy").dataset.copy = d.key;
    await loadApi();
    $("apiNewKeyValue").focus();
    $("apiNewKeyValue").select();
  } finally {
    btn.disabled = false;
    btn.textContent = "生成 API Key";
  }
}

async function revokeApiKey(id) {
  if (!(await confirmInline("撤销这个 API Key？使用它的程序会立刻无法调用。", "确认撤销"))) return;
  await api("/api/api-keys/" + id, { method: "DELETE" });
  await loadApi();
}

/* ---------------------------------------------------------------- 本地前端 / 内网穿透 */
async function loadFrontendSettings() {
  const st = await api("/api/system/settings");
  S.frontendUrl = String(st.frontend_url || "").trim();
  S.frontendAuto = !!st.frontend_url_auto;
  S.frontendConfigured = String(st.frontend_url_configured || "").trim();
  S.requestOrigin = String(st.request_origin || "").trim();
  updateFrontendUI();
}

function updateFrontendUI() {
  const btn = $("frontendBtn");
  btn.disabled = !S.frontendUrl;
  btn.title = S.frontendUrl ? `打开 ${S.frontendUrl}` : "当前访问地址不可用";
  if ($("frontendUrl")) $("frontendUrl").value = S.frontendUrl;
  if ($("frontendHint")) {
    $("frontendHint").textContent = S.frontendUrl
      ? (S.frontendAuto
        ? `已根据当前登录访问地址自动设置：${S.frontendUrl}（无需保存即可打开）`
        : `当前保存的前端地址：${S.frontendUrl}`)
      : "未取得当前访问地址；请检查反向代理的 Host / X-Forwarded-Host 配置。";
  }
}

async function openFrontendPage() {
  if (!S.frontendUrl) {
    try { await loadFrontendSettings(); } catch (e) { /* 打开失败再提示 */ }
  }
  if (!S.frontendUrl) {
    if (S.tab !== "network") switchTab("network");
    if ($("frontendHint")) $("frontendHint").textContent = "当前访问地址不可用，请检查控制台访问地址。";
    return;
  }
  window.open(S.frontendUrl, "_blank", "noopener,noreferrer");
}

async function saveFrontendUrl() {
  const raw = $("frontendUrl").value.trim();
  if (!raw) throw new Error("请填写前端地址");
  let url;
  try { url = new URL(raw); } catch { throw new Error("前端地址格式不正确"); }
  if (!/^http(s)?:/.test(url.protocol)) throw new Error("只支持 http/https 地址");
  await api("/api/system/settings", { method: "PUT", body: JSON.stringify({ frontend_url: raw }) });
  S.frontendUrl = raw;
  S.frontendAuto = false;
  S.frontendConfigured = raw;
  updateFrontendUI();
  await loadTunnelStatus();
}

function tunnelTargetLabel(v) {
  return ({ panel: "管理控制台", api: "模型 API", frontend: "本地前端页面" })[v] || "管理控制台";
}

function renderTunnelStatus(st) {
  const on = !!st.running;
  const ready = on && !!st.ready;
  const failed = !on && !!st.error;
  const url = String(st.url || "");
  $("tunnelDot").classList.toggle("on", ready);
  $("tunnelDot").classList.toggle("warn", (on && !ready) || failed);
  $("tunnelState").textContent = on ? (ready ? "已开启，可以使用" : "正在连接…")
    : (failed ? "启动失败" : "未开启");
  $("tunnelSetup").hidden = on;
  $("tunnelActions").hidden = !on;
  $("tunnelStopBtn").hidden = !on;
  $("tunnelStopBtn").disabled = false;
  $("tunnelStopBtn").textContent = "停止穿透";
  $("tunnelCopyBtn").hidden = !ready || !url;
  $("tunnelCopyBtn").dataset.copy = url;
  $("tunnelOpenBtn").hidden = !ready || !url;
  $("tunnelOpenBtn").dataset.url = url;
  const hasBinary = !!st.binary;
  $("tunnelDownloadBtn").hidden = hasBinary;
  $("tunnelStartBtn").hidden = !hasBinary;
  $("tunnelTarget").disabled = on;
  const rows = [
    ["状态", on ? (ready ? "已开启，可以使用" : "正在连接，请稍等") : (failed ? "启动失败" : "未开启")],
    ["访问内容", tunnelTargetLabel(st.target_mode)],
    ["地址类型", st.mode === "token" ? "固定域名" : "免费临时地址"],
    ["公网地址", ready && url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>`
      : (on ? "正在准备地址…（通常 10 秒内）" : "—")],
    ["已运行", on && st.uptime ? `${Math.round(st.uptime)} 秒` : "—"],
  ];
  if (st.error) rows.push(["错误信息", esc(st.error)]);
  $("tunnelSummary").innerHTML = rows.map(([k, v]) =>
    `<div class="kv"><b>${esc(k)}</b><span>${v}</span></div>`).join("");

  if (!hasBinary) {
    $("tunnelHint").textContent = "第一次使用，请先点“下载穿透组件”。这是 Cloudflare 官方免费工具，下载后会自动放好。";
  } else if (failed) {
    $("tunnelHint").textContent = `上次启动失败：${st.error} 可展开下方连接日志查看详情，或稍后重试。`;
  } else if (on && !ready) {
    $("tunnelHint").textContent = "正在建立安全连接，通常需要 5–10 秒。等状态变成“已开启，可以使用”后再打开或复制地址。";
  } else if (ready) {
    $("tunnelHint").textContent = "地址已经可以使用。关闭穿透后这个地址会失效，下次开启会生成新地址。";
  } else {
    $("tunnelHint").textContent = "点击“一键开启免费穿透”即可，不需要公网 IP，也不用设置路由器。";
  }
}

async function loadTunnelStatus() {
  const st = await api("/api/tunnel/status");
  renderTunnelStatus(st);
  return st;
}

async function loadTunnelLog() {
  try {
    const d = await api("/api/tunnel/log?tail=150");
    $("tunnelLog").textContent = (d.lines || []).join("\n") || "暂无日志";
  } catch { /* 日志失败不影响状态 */ }
}

async function loadNetwork() {
  const st = await api("/api/tunnel/status");
  if (!S.networkLoaded) {
    S.frontendUrl = String(st.frontend_url || S.frontendUrl || "").trim();
    updateFrontendUI();
    $("tunnelTarget").value = ["panel", "api", "frontend"].includes(st.target_mode) ? st.target_mode : "panel";
    $("tunnelMode").value = st.mode === "token" ? "token" : "quick";
    $("tunnelDomain").value = st.tunnel_domain || "";
    S.networkLoaded = true;
  }
  renderTunnelStatus(st);
  await loadTunnelLog();
}

async function startTunnel() {
  const target = $("tunnelTarget").value;
  if (!["panel", "api", "frontend"].includes(target)) throw new Error("请选择要远程访问的内容");
  const mode = $("tunnelMode").value === "token" ? "token" : "quick";
  const btn = $("tunnelStartBtn");
  btn.disabled = true;
  btn.textContent = "正在开启…";
  try {
    await api("/api/tunnel/start", {
      method: "POST",
      body: JSON.stringify({ mode, token: $("tunnelToken").value.trim(),
        domain: $("tunnelDomain").value.trim(), target }),
    });
    await loadNetwork();
  } catch (e) {
    btn.disabled = false;
    try { await loadNetwork(); } catch { /* 让错误先展示 */ }
    throw e;
  } finally {
    btn.textContent = "一键开启免费穿透";
  }
}

async function stopTunnel() {
  const btn = $("tunnelStopBtn");
  btn.disabled = true;
  btn.textContent = "正在停止…";
  try {
    await api("/api/tunnel/stop", { method: "POST" });
    await loadNetwork();
  } finally {
    btn.disabled = false;
    btn.textContent = "停止穿透";
  }
}

function openTunnelUrl() {
  const url = $("tunnelOpenBtn").dataset.url || "";
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

async function downloadCloudflared() {
  const btn = $("tunnelDownloadBtn");
  btn.disabled = true;
  btn.textContent = "下载中…";
  try {
    await api("/api/tunnel/download", { method: "POST" });
    await loadNetwork();
  } finally {
    btn.disabled = false;
    btn.textContent = "下载穿透组件";
  }
}

function sizeText(n) {
  n = Number(n || 0);
  if (n >= 2 ** 30) return (n / 2 ** 30).toFixed(2) + " GB";
  if (n >= 2 ** 20) return (n / 2 ** 20).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

async function fetchArchive(path, fallbackName, options = {}) {
  const r = await fetch(path, {
    ...options,
    headers: {
      ...(token() ? { Authorization: "Bearer " + token() } : {}),
      ...(options.headers || {}),
    },
  });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
  if (!r.ok) {
    let msg = "操作失败";
    try { msg = (await r.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename="?([^";]+)"?/i.exec(cd);
  return { blob, name: m ? m[1] : fallbackName };
}

function saveArchive(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function setBackupNotice(text, kind = "info") {
  const box = $("backupNotice");
  const body = $("backupNoticeText");
  if (!box || !body) return;
  if (!text) {
    box.hidden = true;
    box.className = "backup-notice";
    body.textContent = "";
    return;
  }
  box.hidden = false;
  box.className = `backup-notice ${kind}`;
  body.textContent = text;
}

function setMigrationActions(show) {
  const local = S.localClient !== false;
  for (const id of ["openMigrationFolderBtn", "downloadMigrationFileBtn"]) {
    const el = $(id);
    // 远程（另一台电脑/外网）访问时后端无法操作服务器桌面，直接不显示“打开文件夹”
    if (el) el.hidden = !show || (id === "openMigrationFolderBtn" && !local);
    if (!show) el.textContent = id === "openMigrationFolderBtn" ? "打开文件夹" : "下载到浏览器";
  }
}

async function downloadBackup() {
  const btn = $("backupBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在打包…";
  setBackupNotice("正在生成完整备份，完成前请勿关闭页面。", "info");
  $("backupTitle").textContent = "正在生成备份";
  $("backupBadge").textContent = "处理中";
  $("backupBadge").className = "badge warn";
  try {
    const { blob, name } = await fetchArchive("/api/system/backup", `workbench-backup-${Date.now()}.zip`);
    saveArchive(blob, name);
    await loadBackupPage();
    $("backupTitle").textContent = "备份已下载";
    $("backupBadge").textContent = "完成";
    $("backupBadge").className = "badge good";
    $("backupMeta").textContent = `${name} · ${sizeText(blob.size)} · 已保存到浏览器下载目录`;
    setBackupNotice(`备份已下载：${name}。文件在浏览器默认下载目录。`, "good");
  } catch (e) {
    $("backupTitle").textContent = "备份失败";
    $("backupBadge").textContent = "失败";
    $("backupBadge").className = "badge bad";
    setBackupNotice(`备份失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function downloadMigration() {
  const btn = $("migrationBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成迁移包…";
  setBackupNotice("正在把程序、数据库、密钥和配置打进一个 zip；模型文件较大，不会打包。", "info");
  setMigrationActions(false);
  $("backupTitle").textContent = "正在打包程序和数据";
  $("backupBadge").textContent = "处理中";
  $("backupBadge").className = "badge warn";
  $("backupDesc").textContent = "迁移包会保存到下面的默认目录，不经过浏览器弹窗。";
  try {
    const d = await api("/api/system/migration?save=1", { method: "POST" });
    S.lastMigration = d;
    await loadBackupPage();
    $("backupTitle").textContent = "迁移包已生成";
    $("backupBadge").textContent = "已保存";
    $("backupBadge").className = "badge good";
    $("backupMeta").textContent = `${d.name} · ${sizeText(d.size)} · ${d.path}`;
    setBackupNotice(`迁移包已保存到：${d.path}\n新电脑解压后双击“一键迁移-双击我.bat”。`, "good");
    setMigrationActions(true);
  } catch (e) {
    $("backupTitle").textContent = "迁移包生成失败";
    $("backupBadge").textContent = "失败";
    $("backupBadge").className = "badge bad";
    setBackupNotice(`迁移包生成失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function openMigrationFolder() {
  try {
    const d = await api("/api/system/open-migration-folder", { method: "POST" });
    setBackupNotice(`已打开文件夹：${d.path}`, "good");
  } catch (e) {
    setBackupNotice(`打开文件夹失败：${e.message}`, "bad");
  }
}

async function downloadMigrationFile() {
  const d = S.lastMigration;
  if (!d || !d.download_url) {
    setBackupNotice("请先生成迁移包。", "warn");
    return;
  }
  try {
    const { blob, name } = await fetchArchive(d.download_url, d.name);
    saveArchive(blob, name);
    setBackupNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setBackupNotice(`下载失败：${e.message}`, "bad");
  }
}

/* ---------------------------------------------------------------- 知识库 */
function kbSourceLabel(source) {
  const s = String(source || "").trim();
  if (!s || s === "manual") return "手动文本";
  return s;
}

function renderKbRows() {
  const all = (S.kb && S.kb.docs) || [];
  const q = String(($("kbFilter") && $("kbFilter").value) || "").trim().toLowerCase();
  const scope = String(($("kbScopeFilter") && $("kbScopeFilter").value) || "all");
  const owner = String(($("kbUserFilter") && $("kbUserFilter").value) || "");
  const rows = all.filter((d) => {
    if (scope !== "all" && (d.scope || "global") !== scope) return false;
    if (owner && String(d.user_id || "") !== owner) return false;
    if (!q) return true;
    return `${d.title || ""} ${d.source || ""} ${d.username || ""}`.toLowerCase().includes(q);
  });
  if (!rows.length) {
    $("kbRows").innerHTML = `<tr><td colspan="7"><span class="hint">${all.length ? "没有匹配的文档，换个筛选条件试试。" : "还没有文档。管理员可添加公共库；用户个人库由用户在用户端上传。"}</span></td></tr>`;
    return;
  }
  $("kbRows").innerHTML = rows.map((d) => {
    const pending = String(S.kbPendingDelete) === String(d.id);
    const isPersonal = (d.scope || "global") === "personal";
    const ownerText = isPersonal ? (d.username || `用户 #${d.user_id || "?"}`) : "公共库";
    return `<tr>
      <td><div class="name">${esc(d.title || "未命名")}</div><div class="sub">#${esc(d.id)}</div></td>
      <td>${isPersonal ? esc(ownerText) : `<span class="hint">${esc(ownerText)}</span>`}</td>
      <td><span class="badge ${isPersonal ? "good" : ""}">${isPersonal ? "个人库" : "公共库"}</span></td>
      <td><span class="kb-source">${esc(kbSourceLabel(d.source))}</span></td>
      <td>${fmtInt(d.chars)}</td>
      <td>${fmtTime(d.created_at)}</td>
      <td><div class="ops"><button class="btn small ghost" data-kbview="${esc(d.id)}">查看</button><button class="btn small ${pending ? "danger" : ""}" data-kbdel="${esc(d.id)}">${pending ? "确认删除" : "删除"}</button></div></td>
    </tr>`;
  }).join("");
}

function fillKbUserFilter(docs) {
  const sel = $("kbUserFilter");
  if (!sel) return;
  const current = sel.value;
  const users = [];
  const seen = new Set();
  for (const d of docs) {
    if ((d.scope || "global") !== "personal" || !d.user_id) continue;
    const key = String(d.user_id);
    if (seen.has(key)) continue;
    seen.add(key);
    users.push({ id: key, name: d.username || `用户 #${d.user_id}` });
  }
  users.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  sel.innerHTML = `<option value="">全部账号</option>` + users.map((u) =>
    `<option value="${esc(u.id)}">${esc(u.name)} · #${esc(u.id)}</option>`).join("");
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

async function viewKbDocument(id) {
  const d = await api(`/api/kb/doc/${encodeURIComponent(id)}`);
  S.kbViewing = String(id);
  $("kbDocTitle").textContent = d.title || "未命名文档";
  const personal = (d.scope || "global") === "personal";
  $("kbDocMeta").textContent = `#${d.id} · ${personal ? (d.username || `用户 #${d.user_id}`) + " · 个人库" : "公共库"} · ${fmtInt(d.chars)} 字 · ${fmtTime(d.created_at)} · 来源 ${kbSourceLabel(d.source)}`;
  $("kbDocContent").textContent = d.content || "（正文为空）";
  $("kbDocView").hidden = false;
  $("kbDocView").scrollIntoView({ block: "nearest" });
}

function closeKbDocument() {
  S.kbViewing = null;
  $("kbDocView").hidden = true;
  $("kbDocContent").textContent = "";
}

async function loadKbPage() {
  const d = await api("/api/kb?scope=all");
  S.kb = d;
  const docs = d.docs || [];
  const enabled = !!d.enabled;
  const topK = Number(d.top_k || 3);
  const cards = [
    ["全部文档", fmtInt(d.all_count), "公共库 + 用户个人库"],
    ["公共库", fmtInt(d.global_count), "管理员维护，所有账号可检索"],
    ["个人库", fmtInt(d.personal_count), `${fmtInt(d.personal_users)} 个账号在使用`],
    ["检索状态", enabled ? "已开启" : "已关闭", enabled ? `每次返回 ${topK} 段` : "对话不会检索知识库"],
  ];
  $("kbCards").innerHTML = cards.map(([k, v, s]) => `
    <div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
  fillKbUserFilter(docs);
  $("kbDocHint").textContent = `${fmtInt(d.all_count)} 篇 · 公共 ${fmtInt(d.global_count)} / 个人 ${fmtInt(d.personal_count)} · 共 ${fmtInt(d.all_chars)} 字`;
  $("kbEnabled").checked = enabled;
  $("kbTopK").value = topK;
  $("kbSettingsHint").textContent = enabled
    ? `当前每次返回 ${topK} 段。段数太多会占用上下文，太少可能漏掉关键信息。`
    : "知识库检索已关闭；入库文档仍保留，重新开启后继续使用。";
  S.kbPendingDelete = null;
  renderKbRows();
}

function openKbEditor() {
  $("kbTitle").value = "";
  $("kbContent").value = "";
  $("kbEditor").hidden = false;
  $("kbEditorHint").textContent = "正文为空不会入库；支持 Word/PDF/Excel/PPT 和图片 OCR，扫描件默认前 15 页，单文件不超过 20MB。";
  $("kbTitle").focus();
  $("kbEditor").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function kbUploadNotice(text, danger = false) {
  const box = $("kbUploadNotice");
  if (!box) return;
  box.textContent = text || "";
  box.hidden = !text;
  box.classList.toggle("danger", !!danger);
}

async function saveKbDocument() {
  const title = $("kbTitle").value.trim();
  const content = $("kbContent").value.trim();
  if (!title) throw new Error("请填写标题");
  if (!content) throw new Error("正文不能为空");
  kbUploadNotice("");
  const fd = new FormData();
  fd.append("title", title);
  fd.append("content", content);
  const res = await api("/api/kb/text", { method: "POST", body: fd });
  $("kbEditor").hidden = true;
  await loadKbPage();
  $("kbDocHint").textContent = `已入库：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  kbUploadNotice(`已添加公共文档：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

async function uploadKbFile(file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20MB");
  kbUploadNotice(`正在上传《${file.name}》…`);
  const fd = new FormData();
  fd.append("file", file, file.name);
  const res = await api("/api/kb/upload", { method: "POST", body: fd });
  await loadKbPage();
  $("kbDocHint").textContent = `已上传：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  kbUploadNotice(`上传完成：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

function renderKbSearch(items, query) {
  if (!items.length) {
    $("kbResults").innerHTML = `<div class="kb-empty">没有命中。换一个更短、更具体的关键词，或先补一份资料。</div>`;
    return;
  }
  $("kbResults").innerHTML = items.map((it) => {
    const personal = (it.scope || "global") === "personal";
    const owner = personal ? (it.username || `用户 #${it.user_id || "?"}`) : "公共库";
    return `
    <div class="kb-result">
      <div class="kb-result-head"><b>${esc(it.title || "未命名")}</b><span>#${esc(it.doc_id)} · ${esc(owner)} · ${personal ? "个人库" : "公共库"}</span></div>
      <p>${esc(it.snippet || "（没有摘要）")}</p>
    </div>`;
  }).join("");
}

async function searchKb() {
  const q = $("kbQuery").value.trim();
  if (!q) {
    $("kbResults").innerHTML = `<div class="kb-empty">先输入一个问题或关键词，例如“退款流程要几天？”。</div>`;
    return;
  }
  const d = await api("/api/kb/search?q=" + encodeURIComponent(q));
  S.kbSearchItems = d.items || [];
  renderKbSearch(S.kbSearchItems, q);
}

async function deleteKbDocument(id) {
  if (String(S.kbPendingDelete) !== String(id)) {
    S.kbPendingDelete = String(id);
    renderKbRows();
    $("kbDocHint").textContent = "再点一次“确认删除”才会真正删除该文档和索引。";
    return;
  }
  await api("/api/kb/" + encodeURIComponent(id), { method: "DELETE" });
  S.kbPendingDelete = null;
  if (String(S.kbViewing) === String(id)) closeKbDocument();
  await loadKbPage();
  $("kbDocHint").textContent = "文档已删除，对应检索片段也已清理。";
}

async function saveKbSettings() {
  const enabled = $("kbEnabled").checked;
  const topk = Math.max(1, Math.min(10, Number($("kbTopK").value) || 3));
  await api(`/api/kb/settings?enabled=${enabled}&top_k=${topk}`, { method: "POST" });
  $("kbTopK").value = topk;
  $("kbSettingsHint").textContent = `已保存：公共知识库检索${enabled ? "已开启" : "已关闭"}，每次返回 ${topk} 段。${enabled ? "用户仍需勾选「公共知识库」才会引用。" : "所有账号都不会引用公共库。"}`;
}

function libCategoryHtml(d) {
  const folder = String(d.folder || "").trim();
  const tags = String(d.tags || "").split(",").map((x) => x.trim()).filter(Boolean);
  if (!folder && !tags.length) return `<span class="hint">未分类</span>`;
  return `<div class="lib-cat">
    ${folder ? `<span class="badge folder" title="${esc(folder)}">${esc(folder)}</span>` : ""}
    ${tags.map((t) => `<span class="badge" title="${esc(t)}">#${esc(t)}</span>`).join("")}
  </div>`;
}

function fillLibOptionSelect(sel, items, allLabel) {
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = `<option value="">${allLabel}</option>` +
    items.map((x) => `<option value="${esc(x.name)}">${esc(x.name)}（${x.count}）</option>`).join("");
  sel.value = current && items.some((x) => x.name === current) ? current : "";
}

function renderLibraryRows() {
  const all = (S.library && S.library.docs) || [];
  const q = String(($("libFilter") && $("libFilter").value) || "").trim().toLowerCase();
  const scope = String(($("libScopeFilter") && $("libScopeFilter").value) || "all");
  const owner = String(($("libUserFilter") && $("libUserFilter").value) || "");
  const folder = String(($("libFolderFilter") && $("libFolderFilter").value) || "");
  const tag = String(($("libTagFilter") && $("libTagFilter").value) || "");
  const rows = all.filter((d) => {
    if (scope !== "all" && (d.scope || "global") !== scope) return false;
    if (owner && String(d.user_id || "") !== owner) return false;
    if (folder && String(d.folder || "") !== folder) return false;
    if (tag && !String(d.tags || "").split(",").map((x) => x.trim()).includes(tag)) return false;
    if (!q) return true;
    return `${d.title || ""} ${d.source || ""} ${d.username || ""} ${d.folder || ""} ${d.tags || ""}`.toLowerCase().includes(q);
  });
  if (!rows.length) {
    $("libRows").innerHTML = `<tr><td colspan="9"><span class="hint">${all.length ? "没有匹配的资料，换个筛选条件试试。" : "还没有资料。管理员可上传总库；用户个人资料由用户在用户端上传。"}</span></td></tr>`;
    return;
  }
  $("libRows").innerHTML = rows.map((d) => {
    const pending = String(S.libPendingDelete) === String(d.id);
    const isPersonal = (d.scope || "global") === "personal";
    const ownerText = isPersonal ? (d.username || `用户 #${d.user_id || "?"}`) : "总资料库";
    return `<tr>
      <td><div class="name">${esc(d.title || "未命名")}</div><div class="sub">#${esc(d.id)}</div></td>
      <td>${libCategoryHtml(d)}</td>
      <td>${isPersonal ? esc(ownerText) : `<span class="hint">${esc(ownerText)}</span>`}</td>
      <td><span class="badge ${isPersonal ? "good" : ""}">${isPersonal ? "个人库" : "总库"}</span></td>
      <td><span class="kb-source">${esc(kbSourceLabel(d.source))}</span></td>
      <td>${fmtInt(d.chars)}</td>
      <td>${fmtInt(d.uses || 0)} 次</td>
      <td>${d.last_used_at ? fmtTime(d.last_used_at) : "尚未引用"}</td>
      <td><div class="ops"><button class="btn small ghost" data-libview="${esc(d.id)}">查看</button><button class="btn small ghost" data-liborg="${esc(d.id)}">整理</button><button class="btn small ${pending ? "danger" : ""}" data-libdel="${esc(d.id)}">${pending ? "确认删除" : "删除"}</button></div></td>
    </tr>`;
  }).join("");
}

function fillLibUserFilter(docs) {
  const sel = $("libUserFilter");
  if (!sel) return;
  const current = sel.value;
  const users = [];
  const seen = new Set();
  for (const d of docs) {
    if ((d.scope || "global") !== "personal" || !d.user_id) continue;
    const key = String(d.user_id);
    if (seen.has(key)) continue;
    seen.add(key);
    users.push({ id: key, name: d.username || `用户 #${d.user_id}` });
  }
  users.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  sel.innerHTML = `<option value="">全部账号</option>` + users.map((u) =>
    `<option value="${esc(u.id)}">${esc(u.name)} · #${esc(u.id)}</option>`).join("");
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

async function loadLibraryPage() {
  const d = await api("/api/library?scope=all");
  S.library = d;
  const docs = d.docs || [];
  const enabled = !!d.enabled;
  const cards = [
    ["全部资料", fmtInt(d.all_count), "总资料库 + 用户个人库"],
    ["总资料库", fmtInt(d.global_count), enabled ? "已开启，用户可选" : "已关闭，聊天框不显示"],
    ["个人资料", fmtInt(d.personal_count), `${fmtInt(d.personal_users)} 个账号在上传`],
    ["累计引用", `${fmtInt(d.uses || 0)} 次`, "被聊天选用会累加，可反复使用"],
  ];
  $("libCards").innerHTML = cards.map(([k, v, s]) => `
    <div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
  fillLibUserFilter(docs);
  fillLibOptionSelect($("libFolderFilter"), d.folders || [], "全部文件夹");
  fillLibOptionSelect($("libTagFilter"), d.tags || [], "全部标签");
  $("libDocHint").textContent = `${fmtInt(d.all_count)} 篇 · 总库 ${fmtInt(d.global_count)} / 个人 ${fmtInt(d.personal_count)} · 共 ${fmtInt(d.all_chars)} 字 · 引用 ${fmtInt(d.uses || 0)} 次`;
  $("libEnabled").checked = enabled;
  $("libMaxDocs").value = Number(d.max_docs || 10);
  $("libMaxChars").value = Number(d.max_chars || 12000);
  $("libSettingsHint").textContent = enabled
    ? `总资料库已开启；用户还需勾选「总资料库」，单次最多带入 ${fmtInt(d.max_docs || 10)} 篇。`
    : "总资料库已关闭；用户聊天框中不会出现总库资料，个人资料不受影响。";
  S.libPendingDelete = null;
  renderLibraryRows();
}

function openLibEditor() {
  $("libTitle").value = "";
  $("libContent").value = "";
  $("libFolder").value = "";
  $("libTags").value = "";
  $("libEditor").hidden = false;
  $("libEditorHint").textContent = "正文为空不会入库；支持 Word/PDF/Excel/PPT 和图片 OCR，扫描件默认前 15 页，单文件不超过 20MB。";
  $("libTitle").focus();
  $("libEditor").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function libNotice(text, danger = false) {
  const box = $("libUploadNotice");
  if (!box) return;
  box.textContent = text || "";
  box.hidden = !text;
  box.classList.toggle("danger", !!danger);
}

async function saveLibDocument() {
  const title = $("libTitle").value.trim();
  const content = $("libContent").value.trim();
  if (!title) throw new Error("请填写标题");
  if (!content) throw new Error("正文不能为空");
  libNotice("");
  const fd = new FormData();
  fd.append("title", title);
  fd.append("content", content);
  fd.append("folder", $("libFolder").value.trim());
  fd.append("tags", $("libTags").value.trim());
  const res = await api("/api/library/text", { method: "POST", body: fd });
  $("libEditor").hidden = true;
  await loadLibraryPage();
  $("libDocHint").textContent = `已入库：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  libNotice(`已添加总库资料：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

async function uploadLibFile(file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20MB");
  libNotice(`正在上传《${file.name}》…`);
  const fd = new FormData();
  fd.append("file", file, file.name);
  fd.append("folder", ($("libFolder") && $("libFolder").value.trim()) || "");
  fd.append("tags", ($("libTags") && $("libTags").value.trim()) || "");
  const res = await api("/api/library/upload", { method: "POST", body: fd });
  await loadLibraryPage();
  $("libDocHint").textContent = `已上传：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  libNotice(`上传完成：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

async function viewLibDocument(id) {
  const d = await api(`/api/library/doc/${encodeURIComponent(id)}`);
  $("libDocTitle").textContent = d.title || "未命名资料";
  const personal = (d.scope || "global") === "personal";
  const cls = [d.folder ? `文件夹：${d.folder}` : "", d.tags ? `标签：${d.tags}` : ""].filter(Boolean).join(" · ");
  $("libDocMeta").textContent = `#${d.id} · ${personal ? (d.username || `用户 #${d.user_id}`) + " · 个人库" : "总资料库"} · ${fmtInt(d.chars)} 字 · 引用 ${fmtInt(d.uses || 0)} 次 · ${fmtTime(d.created_at)} · 来源 ${kbSourceLabel(d.source)}${cls ? ` · ${cls}` : ""}`;
  $("libDocContent").textContent = d.content || "（正文为空）";
  $("libDocView").hidden = false;
  $("libDocView").scrollIntoView({ block: "nearest" });
}

function closeLibDocument() {
  $("libDocView").hidden = true;
  $("libDocContent").textContent = "";
}

function openLibOrganize(id) {
  const d = ((S.library && S.library.docs) || []).find((x) => String(x.id) === String(id));
  if (!d) throw new Error("这篇资料不在当前列表里，请刷新后再整理");
  S.libOrgId = d.id;
  $("libOrgDocTitle").textContent = `#${d.id} ${d.title || "未命名"}`;
  $("libOrgTitle").value = d.title || "";
  $("libOrgFolder").value = d.folder || "";
  $("libOrgTags").value = d.tags || "";
  $("libOrgError").hidden = true;
  $("libOrgError").textContent = "";
  $("libOrganize").hidden = false;
  $("libOrganize").scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("libOrgTitle").focus();
}

function closeLibOrganize() {
  S.libOrgId = null;
  $("libOrganize").hidden = true;
  $("libOrgError").hidden = true;
}

async function saveLibOrganize() {
  if (!S.libOrgId) throw new Error("请先选择要整理的资料");
  const title = $("libOrgTitle").value.trim();
  if (!title) throw new Error("标题不能为空");
  const body = JSON.stringify({
    title,
    folder: $("libOrgFolder").value.trim(),
    tags: $("libOrgTags").value.trim(),
  });
  const d = await api(`/api/library/${encodeURIComponent(S.libOrgId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body,
  });
  closeLibOrganize();
  await loadLibraryPage();
  $("libDocHint").textContent = `已整理：《${d.title}》 · ${d.folder || "未分类"}${d.tags ? ` · #${d.tags.replaceAll(",", " #")}` : ""}`;
  libNotice(`分类已保存：《${d.title}》${d.folder ? `，文件夹「${d.folder}」` : ""}${d.tags ? `，标签 ${d.tags}` : ""}。`);
}

async function deleteLibDocument(id) {
  if (String(S.libPendingDelete) !== String(id)) {
    S.libPendingDelete = String(id);
    renderLibraryRows();
    $("libDocHint").textContent = "再点一次“确认删除”才会真正删除该资料和索引。";
    return;
  }
  await api("/api/library/" + encodeURIComponent(id), { method: "DELETE" });
  S.libPendingDelete = null;
  closeLibDocument();
  await loadLibraryPage();
  $("libDocHint").textContent = "资料已删除，对应索引片段也已清理。";
}

async function saveLibSettings() {
  const enabled = $("libEnabled").checked;
  const maxDocs = Math.max(1, Math.min(30, Number($("libMaxDocs").value) || 10));
  const maxChars = Math.max(1000, Math.min(48000, Number($("libMaxChars").value) || 12000));
  const d = await api("/api/library/settings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, max_docs: maxDocs, max_chars: maxChars }),
  });
  $("libMaxDocs").value = d.max_docs;
  $("libMaxChars").value = d.max_chars;
  await loadLibraryPage();
  $("libSettingsHint").textContent = `已保存：总资料库${enabled ? "已开启" : "已关闭"}，单次最多 ${fmtInt(d.max_docs)} 篇 / ${fmtInt(d.max_chars)} 字。`;
}

async function backupLib() {
  const btn = $("libBackupBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成备份…";
  try {
    const { blob, name } = await fetchArchive("/api/library/export", "workbench-library.json");
    saveArchive(blob, name);
    $("libDocHint").textContent = `已下载 ${name} · ${sizeText(blob.size)}。`;
  } catch (e) {
    $("libDocHint").textContent = "备份失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function restoreLib() {
  const file = S.libRestoreFile;
  if (!file) throw new Error("请先选择备份文件");
  if (file.size > 16 * 1024 * 1024) throw new Error("备份文件超过 16MB");
  const fd = new FormData();
  fd.append("file", file, file.name);
  const d = await api("/api/library/restore", { method: "POST", body: fd });
  S.libRestoreFile = null;
  $("libRestoreFile").value = "";
  $("libRestoreBtn").disabled = true;
  await loadLibraryPage();
  const extra = d.failed ? `，失败 ${d.failed} 篇` : "";
  $("libRestoreHint").textContent = `恢复完成：新增 ${d.added} 篇，跳过同名 ${d.skipped} 篇${extra}。`;
}

function memoryKindLabel(kind) {
  if (kind === "preference") return "偏好";
  if (kind === "explicit") return "明确要求";
  return "事实";
}

function renderMemoryPage() {
  const d = S.memory || {};
  const enabled = !!d.enabled;
  const st = d.stats || {};
  $("memoryState").className = "badge " + (enabled ? "good" : "off");
  $("memoryState").textContent = enabled ? "已启用" : "已关闭 · 默认短期";
  $("memoryTitle").textContent = enabled
    ? "长期记忆已启用：跨对话保留，按相关度注入"
    : "长期记忆未启用：只用本次会话的最近上下文";
  $("memoryHint").textContent = enabled
    ? "新消息里的明确自述会自动入库；每条回复最多带入 6 条相关记忆，同一账号的其他对话也能用。"
    : "关闭后不会写入新记忆，也不会把旧记忆带进对话；已有条目会保留，随时可以再打开。";
  const btn = $("memoryToggleBtn");
  btn.textContent = enabled ? "关闭长期记忆" : "启用长期记忆";
  btn.className = "btn big " + (enabled ? "danger" : "primary");
  $("memoryStats").textContent = `${fmtInt(st.total)} 条 · 自动 ${fmtInt(st.auto)} · 手动 ${fmtInt(st.manual)} · ${fmtInt(st.users)} 个账号`;

  const select = $("memoryUser");
  const keep = select.value;
  const users = d.users || [];
  select.innerHTML = users.map((u) => `<option value="${esc(u.id)}">${esc(u.username)} · #${esc(u.id)}</option>`).join("");
  const target = keep || String(d.current_user_id || (users[0] && users[0].id) || "");
  if (target) select.value = target;

  const rows = d.items || [];
  if (!rows.length) {
    $("memoryRows").innerHTML = `<tr><td colspan="6"><span class="hint">还没有记忆条目。打开开关后，说一句“我叫…”或“记住…”就会自动出现；也可以在下面手动添加。</span></td></tr>`;
    return;
  }
  $("memoryRows").innerHTML = rows.map((m) => {
    const pending = String(S.memoryPendingDelete) === String(m.id);
    const src = m.source === "manual" ? "手动" : "自动";
    return `<tr>
      <td><div class="name">${esc(m.username || "—")}</div><div class="sub mono">#${esc(m.user_id)}</div></td>
      <td><div class="memory-text">${esc(m.content)}</div><div class="sub">${esc(memoryKindLabel(m.kind))} · #${esc(m.id)}</div></td>
      <td><span class="badge ${m.source === "manual" ? "ok" : "unknown"}">${src}</span></td>
      <td>${fmtInt(m.hits)}</td>
      <td>${fmtTime(m.updated_at)}</td>
      <td><div class="ops"><button class="btn small ${pending ? "danger" : ""}" data-memorydel="${esc(m.id)}">${pending ? "确认删除" : "删除"}</button></div></td>
    </tr>`;
  }).join("");
}

async function loadMemoryPage() {
  const d = await api("/api/admin/memory");
  S.memory = d;
  S.memoryPendingDelete = null;
  renderMemoryPage();
}

async function toggleMemory() {
  const d = S.memory || {};
  const next = !d.enabled;
  await api("/api/admin/memory/toggle", { method: "POST", body: JSON.stringify({ enabled: next }) });
  await loadMemoryPage();
  $("memoryHint").textContent = next
    ? "已启用。下一条消息开始，明确自述会自动入库，并在后续对话中按相关度带入。"
    : "已关闭。之后的对话只使用本次会话的最近上下文；已保存的条目仍然保留。";
}

async function addMemory() {
  const content = $("memoryInput").value.trim();
  const uid = Number($("memoryUser").value);
  if (!content) throw new Error("先写一句要记住的内容");
  if (!uid) throw new Error("先选择账号");
  await api("/api/admin/memory/items", { method: "POST", body: JSON.stringify({ content, user_id: uid }) });
  $("memoryInput").value = "";
  await loadMemoryPage();
  $("memoryAddHint").textContent = "已添加。下一条消息开始生效；重复内容会自动合并，不会重复占位。";
}

async function deleteMemory(id) {
  if (String(S.memoryPendingDelete) !== String(id)) {
    S.memoryPendingDelete = String(id);
    renderMemoryPage();
    $("memoryAddHint").textContent = "再点一次“确认删除”才会真正删除这条记忆。";
    return;
  }
  await api("/api/admin/memory/items/" + encodeURIComponent(id), { method: "DELETE" });
  S.memoryPendingDelete = null;
  await loadMemoryPage();
  $("memoryAddHint").textContent = "已删除，下一轮对话不再使用这条记忆。";
}

async function backupKb() {  const btn = $("kbBackupBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成备份…";
  try {
    const { blob, name } = await fetchArchive("/api/kb/export", "workbench-kb.json");
    saveArchive(blob, name);
    $("kbBackupHint").textContent = `已下载 ${name} · ${sizeText(blob.size)}。建议另存到网盘或 U 盘。`;
  } catch (e) {
    $("kbBackupHint").textContent = "备份失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function restoreKb() {
  const file = S.kbRestoreFile;
  if (!file) throw new Error("请先选择备份文件");
  if (file.size > 16 * 1024 * 1024) throw new Error("备份文件超过 16MB");
  const fd = new FormData();
  fd.append("file", file, file.name);
  const d = await api("/api/kb/restore", { method: "POST", body: fd });
  S.kbRestoreFile = null;
  $("kbRestoreFile").value = "";
  $("kbRestoreBtn").disabled = true;
  await loadKbPage();
  const extra = d.failed ? `，失败 ${d.failed} 篇` : "";
  $("kbRestoreHint").textContent = `恢复完成：新增 ${d.added} 篇，跳过同名 ${d.skipped} 篇${extra}。`;
}

function backupKindLabel(item) {
  if (item.kind === "migration") return "整机迁移";
  if (String(item.name).startsWith("pre-restore")) return "恢复前安全备份";
  return "数据备份";
}

function renderBackupRows() {
  const rows = S.backups || [];
  if (!rows.length) {
    $("backupRows").innerHTML = `<tr><td colspan="6"><span class="hint">还没有备份。点上面的按钮生成第一份。</span></td></tr>`;
    return;
  }
  $("backupRows").innerHTML = rows.map((b) => {
    const kind = backupKindLabel(b);
    const badge = b.kind === "migration" ? "warn" : (String(b.name).startsWith("pre-restore") ? "bad" : "good");
    return `<tr>
      <td>${esc(b.name)}</td>
      <td><span class="badge ${badge}">${kind}</span></td>
      <td>${fmtTime(b.created_at)}</td>
      <td>${sizeText(b.size)}</td>
      <td>${b.file_count ? b.file_count + " 个文件" : (b.app_schema ? "schema v" + b.app_schema : "—")}</td>
      <td><div class="ops">
        <button class="btn small" data-bbackup="${esc(b.name)}">下载</button>
        <button class="btn small" data-bdel="${esc(b.name)}">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

async function loadBackupPage() {
  resetPendingDelete();
  const [r, ret] = await Promise.all([
    api("/api/system/backups"),
    api("/api/system/file-retention").catch(() => null),
  ]);
  S.backups = r.items || [];
  if (r.migration_dir && $("migrationDirHint")) $("migrationDirHint").textContent = r.migration_dir;
  renderBackupRows();
  if (ret) renderFileRetention(ret);
  const last = S.backups[0];
  $("backupTitle").textContent = "建议每周备份一次";
  $("backupBadge").textContent = "就绪";
  $("backupBadge").className = "badge";
  $("backupDesc").textContent = "搬机器、换服务器或升级前，先生成备份。恢复后需要重启工作台，管理员可能需重新登录。";
  $("backupMeta").textContent = last
    ? `最近：${last.name} · ${sizeText(last.size)} · ${fmtTime(last.created_at)}`
    : "还没有备份。可以先点“生成并下载备份”。";
}

function renderFileRetention(d) {
  if (!d) return;
  const days = Number(d.days) || 30;
  if ($("retentionDays")) $("retentionDays").value = days;
  if ($("retentionFiles")) $("retentionFiles").textContent = String(d.retained_files || 0);
  if ($("retentionSize")) {
    $("retentionSize").textContent =
      `${sizeText(d.retained_bytes || 0)} · 共 ${d.total_files || 0} 条记录`;
  }
  if ($("retentionSoon")) $("retentionSoon").textContent = String(d.expiring_soon || 0);
  if ($("retentionPending")) $("retentionPending").textContent = String(d.pending_cleanup || 0);
  if ($("retentionCleaned")) $("retentionCleaned").textContent = String(d.cleaned_files || 0);
  if ($("retentionBadge")) {
    $("retentionBadge").textContent = `保留 ${days} 天`;
    $("retentionBadge").className = d.pending_cleanup ? "badge warn" : "badge good";
  }
  if ($("retentionHint")) {
    const last = d.last_cleanup_text
      ? `最近清理：${d.last_cleanup_text}，删除 ${Number((d.last_result || {}).removed) || 0} 个，释放 ${sizeText(Number((d.last_result || {}).freed_bytes) || 0)}。`
      : "自动清理已启动，服务启动后立即检查一次，之后每小时检查。";
    $("retentionHint").textContent =
      `${last} 当前保留 ${d.retained_files || 0} 个文件；` +
      `保存新周期会重算所有未清理文件的到期时间并立即清理。`;
  }
}

async function saveFileRetention() {
  const input = $("retentionDays");
  const days = Number(input && input.value);
  if (!Number.isInteger(days) || days < 1 || days > 365) {
    uiToast("保留天数需填 1–365 的整数", "bad");
    if (input) input.focus();
    return;
  }
  const btn = $("saveRetentionBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在保存…";
  try {
    const d = await api("/api/system/file-retention", {
      method: "PUT",
      body: JSON.stringify({ days }),
    });
    renderFileRetention(d);
    const result = d.result || {};
    uiToast(`已改为保留 ${days} 天，清理 ${result.removed || 0} 个文件`, "ok");
  } catch (e) {
    uiToast("保存失败：" + e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function runFileRetentionCleanup() {
  const btn = $("runRetentionBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在清理…";
  try {
    const d = await api("/api/system/file-retention/cleanup", { method: "POST" });
    renderFileRetention(d);
    const result = d.result || {};
    uiToast(`已检查 ${result.checked || 0} 个到期文件，删除 ${result.removed || 0} 个`, "ok");
  } catch (e) {
    uiToast("清理失败：" + e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function downloadExistingBackup(name) {
  try {
    const { blob } = await fetchArchive("/api/system/backups/" + encodeURIComponent(name), name);
    saveArchive(blob, name);
    setBackupNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setBackupNotice(`下载失败：${e.message}`, "bad");
  }
}

function resetPendingDelete() {
  if (S.pendingDeleteBtn) S.pendingDeleteBtn.textContent = "删除";
  S.pendingDelete = null;
  S.pendingDeleteBtn = null;
}

async function deleteExistingBackup(name, btn) {
  if (S.pendingDelete !== name) {
    resetPendingDelete();
    S.pendingDelete = name;
    S.pendingDeleteBtn = btn;
    btn.textContent = "确认删除";
    setBackupNotice(`再次点击“确认删除”会删除 ${name}。删除后无法恢复，但不影响当前数据。`, "warn");
    setTimeout(() => { if (S.pendingDelete === name) resetPendingDelete(); }, 5000);
    return;
  }
  S.pendingDelete = null;
  S.pendingDeleteBtn = null;
  btn.disabled = true;
  btn.textContent = "删除中…";
  try {
    await api("/api/system/backups/" + encodeURIComponent(name), { method: "DELETE" });
    await loadBackupPage();
    setBackupNotice(`已删除：${name}`, "good");
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "删除";
    setBackupNotice(`删除失败：${e.message}`, "bad");
  }
}

function prepareRestoreBackup(ev) {
  const input = ev.target;
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  S.pendingRestore = file;
  $("confirmRestoreBtn").hidden = false;
  $("cancelRestoreBtn").hidden = false;
  setBackupNotice(
    `已选择：${file.name}。恢复会覆盖当前数据库、密钥和登录方式配置；系统会先自动备份当前数据。确认后才会开始。`,
    "warn"
  );
}

function cancelRestoreBackup() {
  S.pendingRestore = null;
  $("confirmRestoreBtn").hidden = true;
  $("cancelRestoreBtn").hidden = true;
  setBackupNotice("已取消恢复，当前数据没有变化。", "info");
}

async function confirmRestoreBackup() {
  const file = S.pendingRestore;
  if (!file) {
    setBackupNotice("请先选择要恢复的备份文件。", "warn");
    return;
  }
  const btn = $("confirmRestoreBtn");
  const cancel = $("cancelRestoreBtn");
  btn.disabled = true;
  cancel.disabled = true;
  btn.textContent = "正在恢复…";
  $("backupTitle").textContent = "正在恢复数据";
  $("backupBadge").textContent = "处理中";
  $("backupBadge").className = "badge warn";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/system/restore", {
      method: "POST",
      headers: token() ? { Authorization: "Bearer " + token() } : {},
      body: fd,
    });
    if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "恢复失败");
    S.pendingRestore = null;
    btn.hidden = true;
    cancel.hidden = true;
    $("backupTitle").textContent = "恢复完成，等待重启";
    $("backupBadge").textContent = "需重启";
    $("backupBadge").className = "badge warn";
    $("backupMeta").textContent = `恢复前安全备份：${d.safety_backup || "已生成"}`;
    setBackupNotice("恢复成功。请重启工作台后再登录；当前登录状态可能已失效。", "good");
    localStorage.removeItem(TOKEN_KEY);
    showLogin();
    $("alert").textContent = "恢复完成，请重启工作台后再登录。";
  } catch (e) {
    $("backupTitle").textContent = "恢复失败";
    $("backupBadge").textContent = "失败";
    $("backupBadge").className = "badge bad";
    setBackupNotice(`恢复失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    cancel.disabled = false;
    btn.textContent = "确认恢复";
  }
}

/* ---------------------------------------------------------------- 网站分享 */
function setShareNotice(text, kind = "info") {
  const box = $("shareNotice");
  const body = $("shareNoticeText");
  if (!box || !body) return;
  if (!text) {
    box.hidden = true;
    box.className = "backup-notice";
    body.textContent = "";
    return;
  }
  box.hidden = false;
  box.className = `backup-notice ${kind}`;
  body.textContent = text;
}

function setShareActions(show) {
  const local = S.localClient !== false;
  for (const id of ["openShareFolderBtn", "downloadShareFileBtn"]) {
    const el = $(id);
    if (el) el.hidden = !show || (id === "openShareFolderBtn" && !local);
    if (!show) el.textContent = id === "openShareFolderBtn" ? "打开文件夹" : "下载到浏览器";
  }
}

async function downloadShare() {
  const btn = $("shareBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成分享包…";
  setShareNotice("正在打包程序和启动脚本；不会包含数据库、账号、密钥或模型。", "info");
  setShareActions(false);
  $("shareTitle").textContent = "正在生成干净程序包";
  $("shareBadge").textContent = "处理中";
  $("shareBadge").className = "badge warn";
  $("shareDesc").textContent = "分享包会保存到下面的默认目录，不经过浏览器弹窗。";
  try {
    const d = await api("/api/system/share?save=1", { method: "POST" });
    S.lastShare = d;
    await loadSharePage();
    $("shareTitle").textContent = "分享包已生成";
    $("shareBadge").textContent = "可分发";
    $("shareBadge").className = "badge good";
    $("shareMeta").textContent = `${d.name} · ${sizeText(d.size)} · ${d.path}`;
    setShareNotice(`分享包已保存到：${d.path}\n对方解压后双击“一键开始-双击我.bat”，首次启动会重新初始化数据。`, "good");
    setShareActions(true);
  } catch (e) {
    $("shareTitle").textContent = "分享包生成失败";
    $("shareBadge").textContent = "失败";
    $("shareBadge").className = "badge bad";
    setShareNotice(`分享包生成失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function openShareFolder() {
  try {
    const d = await api("/api/system/open-share-folder", { method: "POST" });
    setShareNotice(`已打开文件夹：${d.path}`, "good");
  } catch (e) {
    setShareNotice(`打开文件夹失败：${e.message}`, "bad");
  }
}

async function downloadShareFile() {
  const d = S.lastShare;
  if (!d || !d.download_url) {
    setShareNotice("请先生成分享包。", "warn");
    return;
  }
  try {
    const { blob, name } = await fetchArchive(d.download_url, d.name);
    saveArchive(blob, name);
    setShareNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setShareNotice(`下载失败：${e.message}`, "bad");
  }
}

function renderShareRows() {
  const rows = S.shares || [];
  if (!rows.length) {
    $("shareRows").innerHTML = `<tr><td colspan="6"><span class="hint">还没有分享包。点上面的按钮生成第一份。</span></td></tr>`;
    return;
  }
  $("shareRows").innerHTML = rows.map((b) => `<tr>
      <td>${esc(b.name)}</td>
      <td><span class="badge good">干净程序包</span></td>
      <td>${fmtTime(b.created_at)}</td>
      <td>${sizeText(b.size)}</td>
      <td>${b.file_count ? b.file_count + " 个文件" : "不含数据"}</td>
      <td><div class="ops">
        <button class="btn small" data-share-download="${esc(b.name)}">下载</button>
        <button class="btn small" data-share-delete="${esc(b.name)}">删除</button>
      </div></td>
    </tr>`).join("");
}

function resetPendingShareDelete() {
  if (S.pendingShareDeleteBtn) S.pendingShareDeleteBtn.textContent = "删除";
  S.pendingShareDelete = null;
  S.pendingShareDeleteBtn = null;
}

async function loadSharePage() {
  resetPendingDelete();
  resetPendingShareDelete();
  const r = await api("/api/system/shares");
  S.shares = r.items || [];
  if (r.share_dir && $("shareDirHint")) $("shareDirHint").textContent = r.share_dir;
  renderShareRows();
  const last = S.shares[0];
  $("shareTitle").textContent = "生成分享包，发给需要的人";
  $("shareBadge").textContent = "就绪";
  $("shareBadge").className = "badge";
  $("shareDesc").textContent = "分享包不包含你的任何数据，对方安装后是一台全新的工作台。";
  $("shareMeta").textContent = last
    ? `最近：${last.name} · ${sizeText(last.size)} · ${fmtTime(last.created_at)}`
    : "还没有分享包。可以先点“生成到默认文件夹”。";
}

async function downloadExistingShare(name) {
  try {
    const { blob } = await fetchArchive("/api/system/shares/" + encodeURIComponent(name), name);
    saveArchive(blob, name);
    setShareNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setShareNotice(`下载失败：${e.message}`, "bad");
  }
}

async function deleteExistingShare(name, btn) {
  if (S.pendingShareDelete !== name) {
    resetPendingShareDelete();
    S.pendingShareDelete = name;
    S.pendingShareDeleteBtn = btn;
    btn.textContent = "确认删除";
    setShareNotice(`再次点击“确认删除”会删除 ${name}。删除后无法恢复。`, "warn");
    setTimeout(() => { if (S.pendingShareDelete === name) resetPendingShareDelete(); }, 5000);
    return;
  }
  S.pendingShareDelete = null;
  S.pendingShareDeleteBtn = null;
  btn.disabled = true;
  btn.textContent = "删除中…";
  try {
    await api("/api/system/shares/" + encodeURIComponent(name), { method: "DELETE" });
    await loadSharePage();
    setShareNotice(`已删除：${name}`, "good");
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "删除";
    setShareNotice(`删除失败：${e.message}`, "bad");
  }
}

/* ---------------------------------------------------------------- 事件（管理页） */
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && document.body.classList.contains("nav-open")) {
    closeNav();
    return;
  }
  if (ev.key === "Enter" && ev.target.id === "navSearch") {
    const first = [...document.querySelectorAll("#tabs .tab")].find((btn) => !btn.hidden && !btn.classList.contains("nav-away"));
    if (first) {
      ev.preventDefault();
      first.click();
    }
  }
});

["navToggle", "navClose", "navScrim"].forEach((id) => {
  const el = $(id);
  if (!el) return;
  el.addEventListener("click", () => {
    if (id === "navToggle") {
      if (document.body.classList.contains("nav-open")) closeNav();
      else openNav();
    } else {
      closeNav();
    }
  });
});

bindShortcutModeEvents();

if ($("navSearch")) {
  $("navSearch").addEventListener("input", filterNav);
  $("navSearch").addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      $("navSearch").value = "";
      filterNav();
    }
  });
}

window.addEventListener("resize", () => {
  if (!window.matchMedia("(max-width: 980px)").matches) closeNav();
});

if ($("pageGuideBtn")) {
  $("pageGuideBtn").addEventListener("click", openPageGuide);
}
if ($("guideModalClose")) {
  $("guideModalClose").addEventListener("click", () => closePageGuide());
}
if ($("guideModalOk")) {
  $("guideModalOk").addEventListener("click", () => closePageGuide());
}
if ($("guideModal")) {
  $("guideModal").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-guide-close]")) closePageGuide();
  });
}
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && $("guideModal") && !$("guideModal").hidden) {
    ev.preventDefault();
    ev.stopImmediatePropagation();
    closePageGuide();
  }
}, true);

document.addEventListener("click", async (ev) => {
  const tabBtn = ev.target.closest(".tab");
  if (tabBtn) {
    const input = $("navSearch");
    if (input) { input.value = ""; filterNav(); }
    await switchTab(tabBtn.dataset.tab);
    return;
  }
  const row = ev.target.closest("tr[data-rid]");
  if (row) { await loadRequestDetail(row.dataset.rid); return; }
  const t = ev.target.closest("button");
  if (!t) return;
  try {
    if (t.id === "searchBtn") { S.reqPage = 1; await loadRequests(); }
    else if (t.id === "prevPage") { if (S.reqPage > 1) { S.reqPage--; await loadRequests(); } }
    else if (t.id === "nextPage") { if (S.reqPage * 20 < S.reqTotal) { S.reqPage++; await loadRequests(); } }
    else if (t.id === "frontendBtn" || t.id === "openFrontendPage") openFrontendPage();
    else if (t.id === "tunnelBtn") await switchTab("network");
    else if (t.id === "saveFrontendBtn") await saveFrontendUrl();
    else if (t.id === "tunnelStartBtn") await startTunnel();
    else if (t.id === "tunnelStopBtn") await stopTunnel();
    else if (t.id === "tunnelOpenBtn") openTunnelUrl();
    else if (t.id === "tunnelDownloadBtn") await downloadCloudflared();
    else if (t.id === "backupBtn") await downloadBackup();
    else if (t.id === "migrationBtn") await downloadMigration();
    else if (t.id === "openMigrationFolderBtn") await openMigrationFolder();
    else if (t.id === "downloadMigrationFileBtn") await downloadMigrationFile();
    else if (t.id === "confirmRestoreBtn") await confirmRestoreBackup();
    else if (t.id === "cancelRestoreBtn") cancelRestoreBackup();
    else if (t.id === "refreshBackups") await loadBackupPage();
    else if (t.id === "saveRetentionBtn") await saveFileRetention();
    else if (t.id === "runRetentionBtn") await runFileRetentionCleanup();
    else if (t.dataset.bbackup) await downloadExistingBackup(t.dataset.bbackup);
    else if (t.dataset.bdel) await deleteExistingBackup(t.dataset.bdel, t);
    else if (t.id === "restorePick") $("restoreFile").click();
    else if (t.id === "shareBtn") await downloadShare();
    else if (t.id === "openShareFolderBtn") await openShareFolder();
    else if (t.id === "downloadShareFileBtn") await downloadShareFile();
    else if (t.id === "refreshShares") await loadSharePage();
    else if (t.dataset.shareDownload) await downloadExistingShare(t.dataset.shareDownload);
    else if (t.dataset.shareDelete) await deleteExistingShare(t.dataset.shareDelete, t);
    else if (t.id === "kbRefresh") {
      try { await loadKbPage(); } catch (e) { $("kbDocHint").textContent = "刷新失败：" + e.message; }
    }
    else if (t.id === "kbNewBtn") openKbEditor();
    else if (t.id === "kbCancel") $("kbEditor").hidden = true;
    else if (t.id === "kbSave") {
      try { await saveKbDocument(); } catch (e) { $("kbEditorHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "kbUploadBtn") $("kbFile").click();
    else if (t.id === "kbSearch") {
      try { await searchKb(); } catch (e) { $("kbResults").innerHTML = `<div class="kb-empty">检索失败：${esc(e.message)}</div>`; }
    }
    else if (t.id === "kbClear") {
      $("kbQuery").value = "";
      $("kbResults").innerHTML = `<div class="kb-empty">还没有检索。输入问题后点“检索”，这里会显示命中的片段。</div>`;
    }
    else if (t.id === "kbSaveSettings") {
      try { await saveKbSettings(); } catch (e) { $("kbSettingsHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "kbBackupBtn") await backupKb();
    else if (t.id === "kbRestorePick") $("kbRestoreFile").click();
    else if (t.id === "kbRestoreBtn") {
      try { await restoreKb(); } catch (e) { $("kbRestoreHint").textContent = "恢复失败：" + e.message; }
    }
    else if (t.dataset.kbview) {
      try { await viewKbDocument(t.dataset.kbview); } catch (e) { $("kbDocHint").textContent = "查看失败：" + e.message; }
    }
    else if (t.dataset.kbdel) {
      try { await deleteKbDocument(t.dataset.kbdel); } catch (e) { $("kbDocHint").textContent = "删除失败：" + e.message; }
    }
    else if (t.id === "kbDocClose") closeKbDocument();
    else if (t.id === "libRefresh") {
      try { await loadLibraryPage(); } catch (e) { $("libDocHint").textContent = "刷新失败：" + e.message; }
    }
    else if (t.id === "libNewBtn") openLibEditor();
    else if (t.id === "libCancel") $("libEditor").hidden = true;
    else if (t.id === "libSave") {
      try { await saveLibDocument(); } catch (e) { $("libEditorHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "libUploadBtn") $("libFile").click();
    else if (t.id === "libSaveSettings") {
      try { await saveLibSettings(); } catch (e) { $("libSettingsHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "libBackupBtn") await backupLib();
    else if (t.id === "libRestorePick") $("libRestoreFile").click();
    else if (t.id === "libRestoreBtn") {
      try { await restoreLib(); } catch (e) { $("libRestoreHint").textContent = "恢复失败：" + e.message; }
    }
    else if (t.dataset.libview) {
      try { await viewLibDocument(t.dataset.libview); } catch (e) { $("libDocHint").textContent = "查看失败：" + e.message; }
    }
    else if (t.dataset.liborg) {
      try { openLibOrganize(t.dataset.liborg); } catch (e) { $("libDocHint").textContent = "整理失败：" + e.message; }
    }
    else if (t.id === "libOrgSave") {
      try { await saveLibOrganize(); } catch (e) {
        $("libOrgError").textContent = "保存失败：" + e.message;
        $("libOrgError").hidden = false;
      }
    }
    else if (t.id === "libOrgCancel") closeLibOrganize();
    else if (t.dataset.libdel) {
      try { await deleteLibDocument(t.dataset.libdel); } catch (e) { $("libDocHint").textContent = "删除失败：" + e.message; }
    }
    else if (t.id === "libDocClose") closeLibDocument();
    else if (t.id === "memoryToggleBtn") {
      try { await toggleMemory(); } catch (e) { $("memoryHint").textContent = "切换失败：" + e.message; }
    }
    else if (t.id === "refreshMemory") {
      try { await loadMemoryPage(); } catch (e) { $("memoryAddHint").textContent = "刷新失败：" + e.message; }
    }
    else if (t.id === "memoryAdd") {
      try { await addMemory(); } catch (e) { $("memoryAddHint").textContent = "添加失败：" + e.message; }
    }
    else if (t.dataset.memorydel) {
      try { await deleteMemory(t.dataset.memorydel); } catch (e) { $("memoryAddHint").textContent = "删除失败：" + e.message; }
    }
    else if (t.id === "createApiKeyBtn") await createApiKey();
    else if (t.id === "apiNewKeyHide") {
      $("apiNewKey").hidden = true;
      $("apiNewKeyValue").value = "";
      $("apiNewKeyCopy").dataset.copy = "";
    }
    else if (t.dataset.arevoke) await revokeApiKey(t.dataset.arevoke);
    else if (t.dataset.goto) await switchTab(t.dataset.goto);
    else if (t.dataset.copy) {
      try { await navigator.clipboard.writeText(t.dataset.copy); t.textContent = "已复制"; setTimeout(() => (t.textContent = "复制"), 1200); }
      catch { uiToast(t.dataset.copy); }
    }
    else if (t.id === "newUserBtn") openUserEditor(null);
    else if (t.id === "cancelUserBtn") { $("userEditor").hidden = true; S.editingUser = null; }
    else if (t.id === "saveUserBtn") await saveUser();
    else if (t.id === "saveOrgBtn") await saveOrg();
    else if (t.id === "brandLogoUploadBtn") $("brandLogoFile").click();
    else if (t.id === "brandLogoRemoveBtn") await removeBrandLogo();
    else if (t.id === "saveModerationBtn") await saveModeration();
    else if (t.id === "addModWordBtn") await addModerationWord();
    else if (t.id === "bulkModWordsBtn") await bulkModerationWords();
    else if (t.id === "refreshModHitsBtn") await loadModerationPage();
    else if (t.id === "clearModHitsBtn") await clearModerationHits();
    else if (t.dataset.mtoggle) await toggleModerationWord(t.dataset.mtoggle);
    else if (t.dataset.mdel) await deleteModerationWord(t.dataset.mdel);
    else if (t.id === "importUsersBtn") {
      $("userImportPanel").hidden = false;
      renderImportGroupOptions();
      $("importResult").textContent = "";
      $("userImportPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    else if (t.id === "cancelImportBtn") { $("userImportPanel").hidden = true; }
    else if (t.id === "submitImportBtn") {
      const body = {
        text: $("userImportText").value,
        default_group_id: $("importGroup").value ? Number($("importGroup").value) : null,
        default_role: $("importRole").value,
        default_daily_token_limit: Number($("importDaily").value || 0),
        default_monthly_token_limit: Number($("importMonthly").value || 0),
      };
      if (!body.text.trim()) throw new Error("请先粘贴要导入的账号");
      const r = await api("/api/users/import", { method: "POST", body: JSON.stringify(body) });
      $("importResult").className = "hint";
      $("importResult").textContent = `导入完成：新建 ${r.created} 个，跳过已存在 ${r.skipped} 个` +
        (r.errors && r.errors.length ? `，失败 ${r.errors.length} 个（第 ${r.errors[0].line} 行：${r.errors[0].error}）` : "");
      await loadUsers();
    }
    else if (t.id === "exportUsersBtn") {
      const r = await fetch("/api/users/export", { headers: { Authorization: "Bearer " + token() } });
      if (!r.ok) throw new Error("导出失败");
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "workbench-users.csv";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }
    else if (t.id === "newGroupBtn") openGroupEditor(null);
    else if (t.id === "cancelGroupBtn") { $("groupEditor").hidden = true; S.editingGroup = null; }
    else if (t.id === "saveGroupBtn") await saveGroup();
    else if (t.dataset.gedit) {
      const g = (S.groups || []).find((x) => String(x.id) === String(t.dataset.gedit));
      if (g) openGroupEditor(g);
    }
    else if (t.dataset.gdel) {
      const g = (S.groups || []).find((x) => String(x.id) === String(t.dataset.gdel));
      if (!(await confirmInline(`删除用户组 ${g ? g.name : ""}？成员会改为未分组。`, "确认删除"))) return;
      await api("/api/users/groups/" + t.dataset.gdel, { method: "DELETE" });
      await loadUsers();
    }
    else if (t.id === "newRoleBtn") openRoleEditor(null);
    else if (t.id === "cancelRoleBtn") { $("roleEditor").hidden = true; S.editingRole = null; }
    else if (t.id === "saveRoleBtn") await saveRole();
    else if (t.dataset.redit) {
      const r = (S.roles || []).find((x) => String(x.id) === String(t.dataset.redit));
      if (r) openRoleEditor(r);
    }
    else if (t.dataset.rdel) {
      const r = (S.roles || []).find((x) => String(x.id) === String(t.dataset.rdel));
      if (!(await confirmInline(`删除管理员角色 ${r ? r.name : ""}？`, "确认删除"))) return;
      await api("/api/users/roles/" + t.dataset.rdel, { method: "DELETE" });
      await loadUsers();
    }
    else if (t.dataset.uedit) {
      const u = S.users.find((x) => String(x.id) === String(t.dataset.uedit));
      if (u) openUserEditor(u);
    }
    else if (t.dataset.udel) {
      const u = S.users.find((x) => String(x.id) === String(t.dataset.udel));
      if (!(await confirmInline(`删除用户 ${u ? u.username : ""}？该用户的会话与记录会一并删除。`, "确认删除"))) return;
      await api("/api/users/" + t.dataset.udel, { method: "DELETE" });
      await loadUsers();
    }
    else if (t.id === "addProvider") {
      const body = {
        name: $("pvName").value.trim(), base_url: $("pvBase").value.trim(),
        api_key: $("pvKey").value.trim(), models: $("pvModels").value.trim(),
        price_in: Number($("pvIn").value || 0), price_out: Number($("pvOut").value || 0),
      };
      if (!body.name || !body.base_url) throw new Error("名称和 Base URL 必填");
      await api("/api/admin/providers", { method: "POST", body: JSON.stringify(body) });
      ["pvName", "pvBase", "pvKey", "pvModels", "pvIn", "pvOut"].forEach((k) => ($(k).value = ""));
      $("pvPreset").value = "";
      $("pvModels").placeholder = "模型列表，逗号分隔";
      $("pvPresetNote").textContent = "选择常见供应商会自动填入地址和模型，所有字段仍可修改；不在列表里就选最后一项“自定义”。";
      await loadProviders();
    }
    else if (t.dataset.authFill) {
      const card = t.closest(".auth-card");
      if (card) authFillDefaults(card);
    }
    else if (t.dataset.authTest) {
      const card = t.closest(".auth-card");
      const provider = t.dataset.authTest;
      const result = card ? card.querySelector("[data-auth-result]") : null;
      const target = card ? (card.querySelector(`[data-auth-target="${provider}"]`) || {}).value || "" : "";
      t.disabled = true;
      if (result) { result.className = "auth-result"; result.textContent = "正在测试…"; }
      try {
        const r = await api(`/api/admin/auth-providers/${provider}/test`, {
          method: "POST", body: JSON.stringify({ target }),
        });
        if (result) {
          result.className = "auth-result ok";
          result.innerHTML = esc(r.msg || "测试成功") +
            (r.authorize_url ? ` · <a href="${esc(r.authorize_url)}" target="_blank" rel="noreferrer">打开授权页</a>` : "");
        }
      } catch (e) {
        if (result) { result.className = "auth-result bad"; result.textContent = e.message; }
        else uiToast(e.message);
      } finally { t.disabled = false; }
    }
    else if (t.dataset.authSave) {
      const card = t.closest(".auth-card");
      if (!card) return;
      const provider = t.dataset.authSave;
      const result = card.querySelector("[data-auth-result]");
      t.disabled = true;
      if (result) { result.className = "auth-result"; result.textContent = "正在保存…"; }
      try {
        const r = await api(`/api/admin/auth-providers/${provider}`, {
          method: "PUT", body: JSON.stringify(authCollect(card)),
        });
        AUTH_ITEMS = AUTH_ITEMS.map((x) => x.key === provider ? r.item : x);
        await loadAuthProviders();
        const newCard = document.querySelector(`.auth-card[data-auth-card="${provider}"]`);
        const newResult = newCard ? newCard.querySelector("[data-auth-result]") : null;
        if (newResult) {
          newResult.className = "auth-result " + (r.item.ready ? "ok" : "bad");
          newResult.textContent = r.msg || "已保存";
        }
      } catch (e) {
        if (result) { result.className = "auth-result bad"; result.textContent = e.message; }
        else uiToast(e.message);
      } finally { t.disabled = false; }
    }
    else if (t.dataset.ptest) await testProvider(t.dataset.ptest);
    else if (t.dataset.pdel) {
      if (!(await confirmInline("删除该供应商？", "确认删除"))) return;
      await api("/api/admin/providers/" + t.dataset.pdel, { method: "DELETE" });
      await loadProviders();
    }
    else if (t.id === "rtAutoMap") {
      try { autoRouteMap(); } catch (e) {
        $("rtMapHint").className = "hint form-note warn";
        $("rtMapHint").textContent = "自动匹配失败：" + e.message;
      }
    }
    else if (t.id === "addRoute") {
      const providerValue = $("rtProvider").value;
      const body = {
        name: $("rtName").value.trim(), strategy: $("rtStrategy").value,
        provider_id: providerValue && providerValue !== "local" ? Number(providerValue) : null,
        model_map: $("rtMap").value.trim() || "{}",
      };
      if (!body.name) throw new Error("路由名称必填");
      await api("/api/admin/routes", { method: "POST", body: JSON.stringify(body) });
      $("rtName").value = ""; $("rtMap").value = "";
      await loadRoutes();
    }
    else if (t.dataset.rdel) {
      await api("/api/admin/routes/" + t.dataset.rdel, { method: "DELETE" });
      await loadRoutes();
    }
  } catch (e) { uiToast(e.message); }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && S.tab === "requests" && ev.target.matches("#fq, #fmodel")) {
    S.reqPage = 1; loadRequests();
    return;
  }
  if (ev.key === "Enter" && S.tab === "kb" && ev.target.id === "kbQuery") {
    searchKb().catch((e) => { $("kbResults").innerHTML = `<div class="kb-empty">检索失败：${esc(e.message)}</div>`; });
    return;
  }
  if (ev.key === "Enter" && S.tab === "moderation" && ev.target.id === "modWordSearch") {
    loadModerationPage().catch((e) => uiToast(e.message));
    return;
  }
  if (ev.key === "Enter" && S.tab === "moderation" && ev.target.id === "modWordInput") {
    addModerationWord().catch((e) => uiToast(e.message));
    return;
  }
  if (ev.key !== "Enter" || ev.shiftKey || ev.isComposing || !ev.target.matches("input")) return;
  const actions = {
    pvName: "addProvider", pvBase: "addProvider", pvKey: "addProvider",
    pvModels: "addProvider", pvIn: "addProvider", pvOut: "addProvider",
    rtName: "addRoute", rtMap: "addRoute",
    apiKeyName: "createApiKeyBtn",
    frontendUrl: "saveFrontendBtn",
    kbTitle: "kbSave",
    euName: "saveUserBtn", euPass: "saveUserBtn",
    egName: "saveGroupBtn", egDesc: "saveGroupBtn", erName: "saveRoleBtn",
  };
  const target = actions[ev.target.id];
  if (target && $(target) && !$(target).disabled) {
    ev.preventDefault();
    $(target).click();
  }
});

window.addEventListener("hashchange", () => {
  const name = tabNameFromHash();
  if (!name || $("main").hidden || name === S.tab) return;
  switchTab(name);
});

document.addEventListener("input", (ev) => {
  if (ev.target.id === "kbFilter") renderKbRows();
  if (ev.target.id === "libFilter") renderLibraryRows();
});

document.addEventListener("change", (ev) => {
  if (ev.target.id === "modHitDirection") {
    loadModerationPage().catch((e) => uiToast(e.message));
    return;
  }
  if (ev.target.id === "euRole") {
    syncAdminRoleSelect();
    return;
  }
  if (ev.target.id === "kbScopeFilter" || ev.target.id === "kbUserFilter") {
    renderKbRows();
    return;
  }
  if (ev.target.id === "libScopeFilter" || ev.target.id === "libUserFilter"
      || ev.target.id === "libFolderFilter" || ev.target.id === "libTagFilter") {
    renderLibraryRows();
    return;
  }
  if (ev.target.id === "githubProxy") {
    S.platformProxy = ev.target.value.trim() || "auto";
    S.platformDirty = true;
    return;
  }
  if (ev.target.dataset && ev.target.dataset.platform) {
    S.platformDirty = true;
    S.platformSelected = [...document.querySelectorAll("#platformCards [data-platform]:checked")]
      .map((x) => x.dataset.platform);
    renderPlatforms(S.deployData);
    return;
  }
  if (ev.target.dataset && ev.target.dataset.platformUrl) {
    S.platformDirty = true;
    S.platformEndpoints = { ...S.platformEndpoints, [ev.target.dataset.platformUrl]: ev.target.value.trim() };
    return;
  }
  if (ev.target.id === "pvPreset") {
    applyProviderPreset(ev.target.value);
    return;
  }
  if (ev.target.id === "rtProvider") {
    $("rtMap").value = "";
    const value = ev.target.value;
    if (!value || value === "local") {
      $("rtMapHint").className = "hint form-note";
      $("rtMapHint").textContent = "已选择本地部署，模型映射可以留空；需要云端时再选供应商。";
    } else {
      const p = (S.routeProviders || []).find((x) => String(x.id) === String(value));
      const models = routeCloudModels(p);
      $("rtMapHint").className = "hint form-note";
      $("rtMapHint").textContent = `已选择 ${p ? p.name : "云端供应商"}（${models.length} 个模型）。点“自动匹配”或手动填 JSON。`;
    }
    return;
  }
  if (ev.target.id === "rtStrategy" && ev.target.value === "cloud_first") {
    if (($("rtProvider").value || "local") === "local" && (S.routeProviders || []).length) {
      $("rtProvider").value = String(S.routeProviders[0].id);
      $("rtProvider").dispatchEvent(new Event("change"));
    }
  }
  if (ev.target.id === "euAll") {
    document.querySelectorAll("#euModels input[type=checkbox]").forEach((x) => { x.disabled = ev.target.checked; });
  }
  if (ev.target.id === "apiAllKeys" && S.tab === "api") loadApi().catch((e) => uiToast(e.message));
  if (ev.target.id === "allowRegister") {
    const el = ev.target;
    api("/api/system/settings", {
      method: "PUT",
      body: JSON.stringify({ allow_register: el.checked }),
    }).then(() => { el.blur(); }).catch((e) => {
      el.checked = !el.checked;
      uiToast(e.message);
    });
  }
  if (ev.target.dataset && ev.target.dataset.authVendor) {
    const provider = ev.target.dataset.authVendor;
    const card = ev.target.closest(".auth-card");
    const item = AUTH_ITEMS.find((x) => x.key === provider);
    if (!card || !item) return;
    const selected = ev.target.value;
    card.querySelectorAll("[data-block-fields]").forEach((block) => {
      block.hidden = block.dataset.vendor !== selected;
    });
    const vendor = (item.vendors || []).find((v) => v.key === selected);
    const desc = card.querySelector("[data-vendor-desc]");
    if (desc && vendor) desc.textContent = vendor.description || "";
    authFillDefaults(card);
  }
  if (ev.target.id === "restoreFile") prepareRestoreBackup(ev);
  if (ev.target.id === "kbFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    ev.target.value = "";
    uploadKbFile(file).catch((e) => {
      $("kbDocHint").textContent = "上传失败：" + e.message;
      kbUploadNotice("上传失败：" + e.message, true);
    });
  }
  if (ev.target.id === "kbRestoreFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    S.kbRestoreFile = file;
    $("kbRestoreBtn").disabled = false;
    $("kbRestoreHint").textContent = `已选择 ${file.name} · ${sizeText(file.size)}。点“恢复备份”开始追加。`;
  }
  if (ev.target.id === "libFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    ev.target.value = "";
    uploadLibFile(file).catch((e) => {
      $("libDocHint").textContent = "上传失败：" + e.message;
      libNotice("上传失败：" + e.message, true);
    });
  }
  if (ev.target.id === "libRestoreFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    S.libRestoreFile = file;
    $("libRestoreBtn").disabled = false;
    $("libRestoreHint").textContent = `已选择 ${file.name} · ${sizeText(file.size)}。点“恢复备份”开始追加。`;
  }
});

/* ---------------------------------------------------------------- 数据库中心 */
function dbState() {
  if (!S.db) {
    S.db = {
      view: "browse", conn: "local", table: "", tables: [], schema: null,
      rows: [], total: 0, page: 0, pageSize: 30, search: "", sort: "", order: "desc",
      filter: "", connections: [], editing: null, sqlConn: "local", job: null,
      jobTimer: null, lastOverview: null, lastJobId: "", migrateConn: "",
    };
  }
  return S.db;
}

function dbFmtBytes(n) {
  n = Number(n || 0);
  if (!n) return "0 B";
  if (n < 1024) return n + " B";
  if (n < 1024 ** 2) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 ** 3) return (n / 1024 ** 2).toFixed(1) + " MB";
  return (n / 1024 ** 3).toFixed(2) + " GB";
}
function dbFmtTime(ts) {
  if (!ts) return "—";
  try { return new Date(Number(ts) * 1000).toLocaleString("zh-CN", { hour12: false }); } catch { return "—"; }
}
function dbNum(n) { return Number(n || 0).toLocaleString("zh-CN"); }
function dbTargetText(c) {
  if (!c) return "";
  if (c.engine === "sqlite") return c.path || c.database || "SQLite 文件";
  return `${c.host || "127.0.0.1"}:${c.port || ""} / ${c.database || ""}`;
}
function dbSetStatus(id, text, kind = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.className = "db-form-status" + (kind ? " " + kind : "");
}

async function loadDatabasePage() {
  const d = dbState();
  dbSwitchView(d.view || "browse", false);
  let overview = null;
  let listing = null;
  try { overview = await api("/api/admin/database/overview?connection=" + encodeURIComponent(d.conn)); }
  catch (e) { overview = { error: e.message }; }
  try { listing = await api("/api/admin/database/connections"); }
  catch (e) { listing = { connections: [], error: e.message }; }
  d.connections = listing.connections || [];
  d.lastOverview = overview;
  dbRenderStats(overview);
  dbFillConnSelects();
  await dbLoadBrowse();
  if (d.view === "migrate") { dbFillMigrateTargets(); dbLoadMigrationHistory().catch(() => {}); }
  dbLoadConnections().catch(() => {});
}

function dbRenderStats(o) {
  const box = $("dbStatGrid");
  if (!box) return;
  if (!o || o.error) {
    box.innerHTML = `<div class="db-stat"><div class="k">数据库状态</div><div class="v">读取失败</div><div class="s">${esc((o && o.error) || "未知错误")}</div></div>`;
    return;
  }
  const c = o.connection || {};
  const isLocal = c.id === "local";
  const size = o.size ? dbFmtBytes(o.size) : (o.database || c.database || "—");
  const schema = o.schema_version ? `Schema v${o.schema_version}` : "外部数据库";
  const est = o.row_count_estimated ? "含估算行数" : "按表精确统计";
  const cards = [
    ["当前查看的数据库", c.name || "数据库", `${c.engine_label || c.engine || ""} · ${c.database || ""}`],
    ["表 / 视图", `${dbNum(o.table_count)} 张表${o.view_count ? ` · ${dbNum(o.view_count)} 个视图` : ""}`, schema],
    ["总行数", dbNum(o.row_count), est],
    [isLocal ? "文件大小" : "版本", isLocal ? size : (o.version || "—"), isLocal ? (o.path || c.path || "") : (c.host ? `${c.host}:${c.port || ""}` : (c.database || ""))],
  ];
  box.innerHTML = cards.map(([k, v, s]) => `<div class="db-stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s" title="${esc(s)}">${esc(s)}</div></div>`).join("");
}

function dbFillConnSelects() {
  const d = dbState();
  const options = `<option value="local">当前工作台数据库（SQLite）</option>` +
    d.connections.map((c) => `<option value="${esc(c.id)}">${esc(c.name)} · ${esc(c.engine_label || c.engine)}</option>`).join("");
  [["dbConnSelect", d.conn], ["dbSqlConn", d.sqlConn]].forEach(([id, value]) => {
    const sel = $(id);
    if (!sel) return;
    sel.innerHTML = options;
    sel.value = value;
    if (!sel.value) { sel.value = "local"; }
  });
  if ($("dbConnSelect")) d.conn = $("dbConnSelect").value || "local";
  if ($("dbSqlConn")) d.sqlConn = $("dbSqlConn").value || "local";
}

async function dbLoadBrowse() {
  const d = dbState();
  try {
    const res = await api("/api/admin/database/tables?connection=" + encodeURIComponent(d.conn));
    d.tables = res.tables || [];
  } catch (e) {
    d.tables = [];
    dbSetStatus("dbOpsHint", "读取失败：" + e.message, "bad");
    dbRenderTableList();
    dbRenderEmptyTable("读取表清单失败：" + e.message);
    return;
  }
  dbRenderTableList();
  if (!d.tables.some((t) => t.name === d.table)) d.table = d.tables[0] ? d.tables[0].name : "";
  dbRenderActiveTable();
  if (!d.table) { dbRenderEmptyTable("这个数据库里还没有表。"); return; }
  await Promise.all([dbLoadRows(), dbLoadSchema()]);
  dbLoadHealth().catch(() => {});
}

function dbRenderTableList() {
  const d = dbState();
  const f = (d.filter || "").toLowerCase();
  const rows = d.tables.filter((t) => !f || String(t.name).toLowerCase().includes(f));
  const box = $("dbTableList");
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = `<div class="db-empty">${d.tables.length ? "没有匹配的表名" : "还没有表"}</div>`;
  } else {
    box.innerHTML = rows.map((t) => `<button class="db-table-item${t.name === d.table ? " active" : ""}" data-dbtable="${esc(t.name)}" title="${esc(t.name)}">
      <span class="n">${esc(t.name)}</span>
      ${t.kind === "view" ? `<span class="kind">视图</span>` : `<span class="c">${dbNum(t.rows)}</span>`}
    </button>`).join("");
  }
  $("dbTableCount").textContent = `${d.tables.length} 张`;
}

function dbRenderActiveTable() {
  const d = dbState();
  const active = d.tables.find((t) => t.name === d.table);
  $("dbTableName").textContent = active ? active.name : "先选一张表";
  $("dbTableMeta").textContent = active
    ? `${active.kind === "view" ? "视图" : "表"} · ${dbNum(active.rows)} 行${active.rows_estimated ? "（估算）" : ""}`
    : "左侧点表名，右侧显示数据。";
  dbRenderTableList();
  $("dbNewRow").disabled = !active || active.kind === "view";
  $("dbExportCsv").disabled = !active;
  const canManage = !!active && active.kind !== "view";
  const protectedList = (d.lastOverview && d.lastOverview.protected_tables) || [];
  const isProtected = protectedList.includes(active ? active.name : "");
  ["dbTableRenameBtn", "dbTableTruncateBtn", "dbTableDropBtn"].forEach((id) => {
    $(id).hidden = !canManage;
  });
  $("dbTableRenameBtn").disabled = isProtected;
  $("dbTableDropBtn").disabled = isProtected;
  $("dbTableRenameBtn").title = isProtected ? "工作台运行依赖的表不能改名" : "";
  $("dbTableDropBtn").title = isProtected ? "工作台运行依赖的表不能删除" : "";
}

function dbRenderEmptyTable(text) {
  $("dbThead").innerHTML = "";
  $("dbTbody").innerHTML = `<tr><td class="db-empty">${esc(text)}</td></tr>`;
  $("dbPageInfo").textContent = "—";
  $("dbPageBadge").textContent = "—";
  $("dbPageBadge").className = "badge off";
  $("dbPrevPage").disabled = true;
  $("dbNextPage").disabled = true;
  if ($("dbSchemaBody")) $("dbSchemaBody").innerHTML = `<span class="hint">选中表后加载。</span>`;
}

function dbColumnsOf(res) {
  return (res.columns || []).map((c) => (typeof c === "string" ? { name: c } : c));
}

async function dbLoadRows() {
  const d = dbState();
  if (!d.table) { dbRenderEmptyTable("先从左边选一张表。"); return; }
  const q = new URLSearchParams({
    connection: d.conn, limit: String(d.pageSize), offset: String(d.page * d.pageSize),
    search: d.search || "", sort: d.sort || "", order: d.order || "desc",
  });
  $("dbTbody").innerHTML = `<tr><td class="db-empty">正在读取…</td></tr>`;
  try {
    const res = await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/rows?${q}`);
    d.rows = res.rows || [];
    d.total = Number(res.total || 0);
    dbRenderGrid(res);
  } catch (e) {
    dbRenderEmptyTable("读取失败：" + e.message);
  }
}

function dbCellPreview(v) {
  if (v === null || v === undefined) return { text: "NULL", kind: "null" };
  if (typeof v === "object") v = JSON.stringify(v);
  const s = String(v);
  return { text: s, kind: /^-?\d+(\.\d+)?$/.test(s) ? "num" : "" };
}

function dbRenderGrid(res) {
  const d = dbState();
  const cols = dbColumnsOf(res);
  if (!cols.length) { dbRenderEmptyTable("这张表没有可显示的字段。"); return; }
  const active = d.tables.find((t) => t.name === d.table);
  const editable = active && active.kind !== "view";
  const tbl = $("dbThead").closest("table");
  if (tbl) tbl.classList.toggle("has-actions", !!editable);
  $("dbThead").innerHTML = "<tr>" + cols.map((c) => {
    const sorted = d.sort === c.name;
    return `<th class="sortable" data-dbsort="${esc(c.name)}" title="按 ${esc(c.name)} 排序">${esc(c.name)}<span class="sort">${sorted ? (d.order === "asc" ? "▲" : "▼") : "↕"}</span></th>`;
  }).join("") + (editable ? "<th class=\"right\">操作</th>" : "") + "</tr>";

  if (!d.rows.length) {
    $("dbTbody").innerHTML = `<tr><td class="db-empty" colspan="${cols.length + (editable ? 1 : 0)}">${d.search ? "没有匹配的行" : "这张表还没有数据"}</td></tr>`;
  } else {
    $("dbTbody").innerHTML = d.rows.map((row) => {
      const cells = cols.map((c) => {
        const p = dbCellPreview(row[c.name]);
        return `<td><span class="db-cell ${p.kind}" title="${esc(p.text)}">${esc(p.text)}</span></td>`;
      }).join("");
      const key = row._key || "";
      const actions = editable
        ? `<td><div class="db-cell-actions">${key
            ? `<button class="btn small" data-dbedit="${esc(key)}">编辑</button><button class="btn small" data-dbdel="${esc(key)}">删除</button>`
            : `<span class="badge off" title="没有主键的表需要到 SQL 控制台修改">无主键</span>`}</div></td>`
        : "";
      return `<tr>${cells}${actions}</tr>`;
    }).join("");
  }
  const pages = Math.max(1, Math.ceil(d.total / d.pageSize));
  $("dbPageInfo").textContent = `第 ${Math.min(d.page + 1, pages)} / ${pages} 页 · 共 ${dbNum(d.total)} 行`;
  $("dbPageBadge").textContent = `${d.conn === "local" ? "主库" : "外部库"}`;
  $("dbPageBadge").className = "badge " + (d.conn === "local" ? "ok" : "warn");
  $("dbPrevPage").disabled = d.page <= 0;
  $("dbNextPage").disabled = (d.page + 1) * d.pageSize >= d.total;
}

async function dbLoadSchema() {
  const d = dbState();
  if (!d.table) { d.schema = null; return; }
  try {
    d.schema = await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/schema?connection=${encodeURIComponent(d.conn)}`);
    dbRenderSchema(d.schema);
  } catch (e) {
    d.schema = null;
    $("dbSchemaBody").innerHTML = `<span class="hint">读取表结构失败：${esc(e.message)}</span>`;
  }
}

function dbRenderSchema(s) {
  const box = $("dbSchemaBody");
  if (!box) return;
  if (!s) { box.innerHTML = `<span class="hint">没有表结构信息。</span>`; return; }
  const cols = (s.columns || []).map((c) => `<tr>
    <td><b>${esc(c.name)}</b>${c.pk ? ` <span class="badge ok">主键</span>` : ""}</td>
    <td class="mono">${esc(c.type)}</td>
    <td>${c.nullable ? "可空" : "必填"}</td>
    <td class="mono">${c.default === null || c.default === undefined ? "—" : esc(c.default)}</td>
    <td>${c.auto ? "自增" : ""}</td></tr>`).join("");
  const idx = (s.indexes || []).map((i) => `<li><b>${esc(i.name)}</b> · ${(i.columns || []).map(esc).join(", ")}${i.unique ? " · 唯一" : ""}${i.primary ? " · 主键" : ""}</li>`).join("");
  const fks = (s.foreign_keys || []).map((f) => `<li>${esc(f.from)} → ${esc(f.table)}.${esc(f.to)}</li>`).join("");
  box.innerHTML = `<div class="db-schema-body">
    <div class="table-wrap"><table class="tbl"><thead><tr><th>字段</th><th>类型</th><th>可空</th><th>默认值</th><th>自增</th></tr></thead><tbody>${cols || `<tr><td class="db-empty">无字段</td></tr>`}</tbody></table></div>
    ${idx ? `<div><h4>索引</h4><ul class="share-list">${idx}</ul></div>` : ""}
    ${fks ? `<div><h4>外键</h4><ul class="share-list">${fks}</ul></div>` : ""}
    <div><h4>建表 SQL</h4><pre>${esc(s.create_sql || "（视图或没有建表语句）")}</pre></div>
  </div>`;
}

async function dbSelectTable(name) {
  const d = dbState();
  d.table = name;
  d.page = 0;
  d.search = "";
  d.sort = "";
  d.order = "desc";
  $("dbRowSearch").value = "";
  dbRenderActiveTable();
  await Promise.all([dbLoadRows(), dbLoadSchema()]);
}

async function dbLoadHealth() {
  const d = dbState();
  const body = $("dbHealthBody");
  const btn = $("dbHealthBtn");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "检查中…"; }
  if (body) body.innerHTML = `<span class="hint">正在检查…</span>`;
  try {
    const h = await api("/api/admin/database/health?connection=" + encodeURIComponent(d.conn));
    const checks = h.checks || [];
    const fk = checks.find((c) => c.name === "外键检查");
    const bad = checks.filter((c) => !c.ok).length;
    if (body) {
      body.innerHTML = checks.map((c) => {
        const detail = c.hint ? `${c.detail} · ${c.hint}` : c.detail;
        const list = (c.details || []).length ? `<div class="db-health-list">${c.details.map((r) =>
          `<span class="db-health-chip">${esc(r.table)} #${dbNum(r.rowid)} → ${esc(r.parent)}</span>`).join("")}</div>` : "";
        return `<div class="db-health-line">
          <span>${esc(c.name)}</span><span><b class="${c.ok ? "ok" : "bad"}">${c.ok ? "通过" : "异常"}</b> · ${esc(detail)}</span>
        </div>${list}`;
      }).join("") + `<div class="db-health-foot">
        <span class="hint">最后检查 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} · 耗时 ${h.latency_ms} ms</span>
        ${fk && !fk.ok ? `<button class="btn small" data-dbfixfk="1">清理这 ${(fk.details || []).length} 条孤儿记录</button>` : ""}
      </div>`;
    }
    uiToast(`健康检查完成 · 耗时 ${h.latency_ms} ms`, bad ? "warn" : "info");
  } catch (e) {
    if (body) body.innerHTML = `<div class="db-sql-error">健康检查失败：${esc(e.message)}</div>`;
    uiToast("健康检查失败：" + e.message, "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label || "重新检查"; }
  }
}

async function dbRepairForeignKey() {
  const d = dbState();
  const ok = await confirmInline("将删除指向已删除用户的孤儿记录，父表数据不动，修复前会自动生成一份数据库快照。", "确认清理");
  if (!ok) return;
  try {
    const r = await api("/api/admin/database/repair-foreign-keys?connection=" + encodeURIComponent(d.conn), { method: "POST" });
    uiToast(`已清理 ${r.total} 条孤儿记录 · 快照 ${r.backup}`, "info");
  } catch (e) {
    uiToast("修复失败：" + e.message, "bad");
  }
  await dbLoadHealth();
}

/* ---------------------------------------------------------------- 表管理 */
function dbOpenTableAction(mode) {
  const d = dbState();
  if (!d.table) return;
  const modal = $("dbTableActionModal");
  modal.dataset.mode = mode;
  modal.dataset.table = d.table;
  const titles = { rename: "重命名表", truncate: "清空表数据", drop: "删除整张表" };
  const descs = {
    rename: "改名后，代码或报表里写死的旧表名会失效。工作台核心表已禁用此操作。",
    truncate: "只删除表里的所有数据，保留字段、索引和外键；执行前会自动生成一份 SQLite 快照。",
    drop: "删除整张表和全部数据，无法恢复；执行前会自动生成一份 SQLite 快照。",
  };
  $("dbTableActionTitle").textContent = `${titles[mode]} · ${d.table}`;
  $("dbTableActionSub").textContent = mode === "rename" ? "改成一个新名字" : "危险操作，请确认表名";
  $("dbTableActionDesc").textContent = descs[mode];
  $("dbTableActionInputWrap").hidden = false;
  $("dbTableActionStatus").textContent = "";
  const input = $("dbTableActionInput");
  input.value = mode === "rename" ? `${d.table}_copy` : "";
  $("dbTableActionInputWrap").childNodes[0].nodeValue = mode === "rename" ? "新表名" : `输入表名 ${d.table} 确认`;
  $("dbTableActionConfirm").textContent = mode === "rename" ? "重命名" : mode === "truncate" ? "清空" : "永久删除";
  $("dbTableActionConfirm").className = "btn " + (mode === "rename" ? "primary" : "danger");
  $("dbTableActionConfirm").disabled = false;
  modal.hidden = false;
  setTimeout(() => { input.focus(); if (mode === "rename") input.select(); }, 30);
}

function dbCloseTableAction() {
  $("dbTableActionModal").hidden = true;
}

async function dbSubmitTableAction() {
  const d = dbState();
  const modal = $("dbTableActionModal");
  const mode = modal.dataset.mode;
  const table = modal.dataset.table;
  const value = $("dbTableActionInput").value.trim();
  if (!value) { dbSetStatus("dbTableActionStatus", "请填写后再继续。", "bad"); return; }
  if (mode !== "rename" && value !== table) {
    dbSetStatus("dbTableActionStatus", "输入的表名不完整，请重新输入。", "bad");
    return;
  }
  $("dbTableActionConfirm").disabled = true;
  dbSetStatus("dbTableActionStatus", "正在执行…");
  try {
    if (mode === "rename") {
      await api(`/api/admin/database/table/${encodeURIComponent(table)}/rename?connection=${encodeURIComponent(d.conn)}`, {
        method: "POST", body: JSON.stringify({ new_name: value }),
      });
      d.table = value;
    } else if (mode === "truncate") {
      const res = await api(`/api/admin/database/table/${encodeURIComponent(table)}/truncate?connection=${encodeURIComponent(d.conn)}`, {
        method: "POST", body: JSON.stringify({ confirm: value }),
      });
      dbCloseTableAction();
      uiToast(`已清空 ${table}${res.affected ? `，删除 ${dbNum(res.affected)} 行` : ""}`, "ok");
      d.page = 0;
      await dbLoadBrowse();
      dbLoadOverview().catch(() => {});
      return;
    } else {
      await api(`/api/admin/database/table/${encodeURIComponent(table)}?connection=${encodeURIComponent(d.conn)}`, {
        method: "DELETE", body: JSON.stringify({ confirm: value }),
      });
      d.table = "";
    }
    dbCloseTableAction();
    uiToast(mode === "rename" ? `已将 ${table} 改名为 ${value}` : `已删除表 ${table}`, "ok");
    d.page = 0;
    await dbLoadBrowse();
    dbLoadOverview().catch(() => {});
  } catch (e) {
    dbSetStatus("dbTableActionStatus", "执行失败：" + e.message, "bad");
    $("dbTableActionConfirm").disabled = false;
  }
}

function dbNewColumnRow(col = {}) {
  const row = document.createElement("div");
  row.className = "db-col-row";
  row.innerHTML = `<input type="text" data-col-name value="${esc(col.name || "")}" placeholder="字段名">
    <select data-col-type>
      ${["INTEGER", "TEXT", "VARCHAR(255)", "REAL", "BOOLEAN", "DATETIME", "BLOB"].map((t) =>
        `<option value="${t}" ${t === (col.type || "TEXT") ? "selected" : ""}>${
          t === "INTEGER" ? "整数" : t === "TEXT" ? "长文本" : t === "VARCHAR(255)" ? "短文本" :
          t === "REAL" ? "小数" : t === "BOOLEAN" ? "是/否" : t === "DATETIME" ? "日期时间" : "二进制"}</option>`).join("")}
    </select>
    <label class="db-col-check"><input type="checkbox" data-col-pk ${col.primary_key ? "checked" : ""}>主键</label>
    <label class="db-col-check"><input type="checkbox" data-col-auto ${col.auto ? "checked" : ""}>自增</label>
    <label class="db-col-check"><input type="checkbox" data-col-null ${col.nullable !== false ? "checked" : ""}>可空</label>
    <button class="db-col-remove" type="button" title="删除这个字段">×</button>`;
  $("dbNewColumns").appendChild(row);
  dbSyncColumnRow(row);
  return row;
}

function dbSyncColumnRow(row) {
  const type = row.querySelector("[data-col-type]").value;
  const pk = row.querySelector("[data-col-pk]").checked;
  const auto = row.querySelector("[data-col-auto]");
  auto.disabled = !(pk && type === "INTEGER");
  if (auto.disabled) auto.checked = false;
  row.querySelector("[data-col-null]").disabled = pk;
  if (pk) row.querySelector("[data-col-null]").checked = false;
}

function dbOpenCreateTable() {
  $("dbNewTableName").value = "";
  $("dbNewColumns").innerHTML = "";
  $("dbCreateTableStatus").textContent = "";
  dbNewColumnRow({ name: "id", type: "INTEGER", primary_key: true, auto: true, nullable: false });
  dbNewColumnRow({ name: "created_at", type: "DATETIME", nullable: true });
  dbNewColumnRow({ name: "name", type: "TEXT", nullable: true });
  $("dbCreateTableModal").hidden = false;
  setTimeout(() => $("dbNewTableName").focus(), 30);
}

function dbCloseCreateTable() {
  $("dbCreateTableModal").hidden = true;
}

async function dbSubmitCreateTable() {
  const d = dbState();
  const table = $("dbNewTableName").value.trim();
  if (!table) { dbSetStatus("dbCreateTableStatus", "请先填写表名。", "bad"); return; }
  const columns = [...$("dbNewColumns").querySelectorAll(".db-col-row")].map((row) => ({
    name: row.querySelector("[data-col-name]").value.trim(),
    type: row.querySelector("[data-col-type]").value,
    primary_key: row.querySelector("[data-col-pk]").checked,
    auto: row.querySelector("[data-col-auto]").checked && !row.querySelector("[data-col-auto]").disabled,
    nullable: row.querySelector("[data-col-null]").checked,
  }));
  if (!columns.length) { dbSetStatus("dbCreateTableStatus", "至少要有一个字段。", "bad"); return; }
  if (columns.some((c) => !c.name)) { dbSetStatus("dbCreateTableStatus", "字段名不能留空。", "bad"); return; }
  if (columns.filter((c) => c.primary_key).length > 1) { dbSetStatus("dbCreateTableStatus", "只能选一个主键字段。", "bad"); return; }
  const auto = columns.find((c) => c.auto);
  if (auto && auto.type !== "INTEGER") { dbSetStatus("dbCreateTableStatus", "自增主键必须是整数类型。", "bad"); return; }
  $("dbCreateTableSubmit").disabled = true;
  dbSetStatus("dbCreateTableStatus", "正在创建…");
  try {
    await api("/api/admin/database/table", {
      method: "POST",
      body: JSON.stringify({ connection: d.conn, table, columns }),
    });
    dbCloseCreateTable();
    uiToast(`表 ${table} 已创建`, "ok");
    d.table = table;
    d.page = 0;
    await dbLoadBrowse();
    dbLoadOverview().catch(() => {});
  } catch (e) {
    dbSetStatus("dbCreateTableStatus", "创建失败：" + e.message, "bad");
  } finally {
    $("dbCreateTableSubmit").disabled = false;
  }
}


function dbFieldValue(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

async function dbOpenRowModal(mode, key) {
  const d = dbState();
  if (!d.schema) await dbLoadSchema();
  if (!d.schema || !d.schema.columns) throw new Error("表结构还没加载好");
  let row = null;
  if (mode === "edit") {
    const res = await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/row?connection=${encodeURIComponent(d.conn)}&key=${encodeURIComponent(key)}`);
    row = res.row;
  }
  const schema = d.schema;
  const pks = schema.primary_key || [];
  const fields = schema.columns.map((c) => {
    const disabled = mode === "edit" && c.pk;
    const isAuto = mode === "create" && c.auto && c.pk;
    const val = row ? dbFieldValue(row[c.name]) : "";
    const long = String(c.type || "").toUpperCase().includes("TEXT") || (val && val.length > 80);
    const control = long
      ? `<textarea data-dbcol="${esc(c.name)}" ${disabled || isAuto ? "disabled" : ""} placeholder="${esc(c.default ?? "")}">${esc(val)}</textarea>`
      : `<input data-dbcol="${esc(c.name)}" value="${esc(val)}" ${disabled || isAuto ? "disabled" : ""} placeholder="${esc(c.default ?? "")}">`;
    return `<div class="db-field${long ? " full" : ""}">
      <label><b>${esc(c.name)}</b> · ${esc(c.type)}${c.pk ? " · 主键" : ""}${isAuto ? " · 自增不用填" : ""}</label>
      ${control}
      ${c.nullable ? `<span class="hint">可空；留空保存为 NULL</span>` : ""}
    </div>`;
  }).join("");
  $("dbModalTitle").textContent = mode === "create" ? `新增一行 · ${d.table}` : `编辑一行 · ${d.table}`;
  $("dbModalSub").textContent = mode === "create" ? "填写字段后保存；自增主键由数据库生成。" : "主键不能改；要改主键请使用 SQL 控制台。";
  $("dbModalBody").innerHTML = fields;
  $("dbModalDelete").hidden = !(mode === "edit" && pks.length);
  $("dbModalSave").disabled = false;
  $("dbModalDelete").disabled = false;
  $("dbModalSave").textContent = "保存";
  dbSetStatus("dbModalStatus", "");
  d.modal = { mode, key, row, table: d.table, conn: d.conn, schema };
  $("dbRowModal").hidden = false;
  setTimeout(() => { const el = $("dbModalBody").querySelector("input:not(:disabled), textarea:not(:disabled)"); if (el) el.focus(); }, 30);
}

function dbCloseRowModal() {
  $("dbRowModal").hidden = true;
  const d = dbState();
  d.modal = null;
}

async function dbSaveRow() {
  const d = dbState();
  const m = d.modal;
  if (!m) return;
  const vals = {};
  let missingPk = false;
  $("dbModalBody").querySelectorAll("[data-dbcol]").forEach((el) => {
    if (el.disabled) return;
    const name = el.dataset.dbcol;
    const col = (m.schema.columns || []).find((c) => c.name === name);
    const value = el.value;
    if (m.mode === "create" && col && col.pk && !col.auto && !value.trim()) missingPk = true;
    vals[name] = value;
  });
  if (missingPk) { dbSetStatus("dbModalStatus", "这张表的主键需要手动填写，不能留空。", "bad"); return; }
  if (!Object.keys(vals).length) { dbSetStatus("dbModalStatus", "没有可保存的字段。", "bad"); return; }
  $("dbModalSave").disabled = true;
  dbSetStatus("dbModalStatus", "正在保存…");
  try {
    if (m.mode === "create") {
      await api(`/api/admin/database/table/${encodeURIComponent(m.table)}/rows?connection=${encodeURIComponent(m.conn)}`, {
        method: "POST", body: JSON.stringify({ values: vals }),
      });
    } else {
      await api(`/api/admin/database/table/${encodeURIComponent(m.table)}/row?connection=${encodeURIComponent(m.conn)}`, {
        method: "PATCH", body: JSON.stringify({ key: m.key, values: vals }),
      });
    }
    uiToast("已保存", "ok");
    dbCloseRowModal();
    await dbLoadRows();
    dbLoadHealth().catch(() => {});
    dbLoadOverview().catch(() => {});
  } catch (e) {
    dbSetStatus("dbModalStatus", "保存失败：" + e.message, "bad");
    $("dbModalSave").disabled = false;
  }
}

async function dbDeleteRow(key) {
  const d = dbState();
  if (!d.table) return;
  const ok = await confirmInline(`确定删除 ${d.table} 的这一行？删除后不能撤销，建议先备份。`, "确认删除");
  if (!ok) return;
  try {
    await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/row?connection=${encodeURIComponent(d.conn)}`, {
      method: "DELETE", body: JSON.stringify({ key }),
    });
    uiToast("已删除这一行", "ok");
    if (d.modal) dbCloseRowModal();
    await dbLoadRows();
    dbLoadHealth().catch(() => {});
  } catch (e) { uiToast("删除失败：" + e.message, "bad"); }
}

/* ---------------------------------------------------------------- 概览刷新 */
async function dbLoadOverview() {
  const d = dbState();
  try {
    const o = await api("/api/admin/database/overview?connection=" + encodeURIComponent(d.conn));
    d.lastOverview = o;
    dbRenderStats(o);
  } catch (e) {
    dbRenderStats({ error: e.message });
  }
}

/* ---------------------------------------------------------------- SQL 控制台 */
async function dbRunSql() {
  const d = dbState();
  const sql = $("dbSqlText").value.trim();
  if (!sql) { $("dbSqlError").hidden = false; $("dbSqlError").textContent = "请先输入 SQL。"; return; }
  const allow = $("dbAllowWrite").checked;
  if (allow) {
    const ok = await confirmInline("写操作会直接修改数据库，可能删改真实数据。确认执行这条 SQL？", "确认执行");
    if (!ok) return;
  }
  const btn = $("dbRunSql");
  btn.disabled = true;
  $("dbSqlError").hidden = true;
  $("dbSqlMeta").textContent = "执行中…";
  $("dbSqlWrap").hidden = true;
  try {
    const res = await api("/api/admin/database/query", {
      method: "POST",
      body: JSON.stringify({ connection: d.sqlConn, sql, allow_write: allow, limit: Number($("dbSqlLimit").value) || 100 }),
    });
    const cols = res.columns || [];
    const rows = res.rows || [];
    const meta = [`耗时 ${res.elapsed_ms} ms`, `返回 ${rows.length} 行`];
    if (res.affected >= 0) meta.push(`影响 ${res.affected} 行`);
    if (res.last_id) meta.push(`last_id ${res.last_id}`);
    if (res.truncated) meta.push(`结果已截断到 ${res.limit} 行`);
    if (res.write) meta.push("写操作");
    $("dbSqlMeta").textContent = meta.join(" · ");
    if (cols.length) {
      $("dbSqlThead").innerHTML = "<tr>" + cols.map((c) => `<th>${esc(c)}</th>`).join("") + "</tr>";
      $("dbSqlTbody").innerHTML = rows.length ? rows.map((r) => "<tr>" + cols.map((c, i) => {
        const p = dbCellPreview(Array.isArray(r) ? r[i] : r[c]);
        return `<td><span class="db-cell ${p.kind}" title="${esc(p.text)}">${esc(p.text)}</span></td>`;
      }).join("") + "</tr>").join("") : `<tr><td class="db-empty" colspan="${cols.length}">查询没有返回行</td></tr>`;
      $("dbSqlWrap").hidden = false;
    } else {
      $("dbSqlWrap").hidden = true;
      $("dbSqlMeta").textContent = meta.join(" · ") + " · 这条语句没有结果表";
    }
    uiToast("SQL 执行完成", "ok");
    dbLoadOverview().catch(() => {});
    if (d.table) dbLoadRows().catch(() => {});
  } catch (e) {
    $("dbSqlError").hidden = false;
    $("dbSqlError").textContent = "执行失败：" + e.message;
    $("dbSqlMeta").textContent = "执行失败";
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------------- 连接管理 */
async function dbLoadConnections() {
  const d = dbState();
  try {
    const res = await api("/api/admin/database/connections");
    d.connections = res.connections || [];
    dbRenderConnList();
    dbFillConnSelects();
    dbFillMigrateTargets();
  } catch (e) {
    $("dbConnList").innerHTML = `<div class="db-sql-error">读取连接失败：${esc(e.message)}</div>`;
  }
}

function dbRenderConnList() {
  const d = dbState();
  const box = $("dbConnList");
  if (!box) return;
  if (!d.connections.length) {
    box.innerHTML = `<div class="db-conn-empty">还没有外部连接。<br>在右边填一台 MySQL / PostgreSQL，或选一个外部 SQLite 文件。</div>`;
    return;
  }
  box.innerHTML = d.connections.map((c) => `<div class="db-conn-card">
    <div class="db-conn-top">
      <div style="min-width:0">
        <div class="db-conn-name">${esc(c.name)}</div>
        <div class="db-conn-meta">${esc(c.engine_label || c.engine)} · ${esc(dbTargetText(c))}</div>
      </div>
      <span class="badge ${c.password_set ? "good" : "off"}">${c.password_set ? "有密码" : (c.engine === "sqlite" ? "文件" : "无密码")}</span>
    </div>
    <div class="db-conn-meta">最近测试：${c.last_test_at ? dbFmtTime(c.last_test_at) : "还没测试"}${c.note ? " · " + esc(c.note) : ""}</div>
    <div class="db-conn-actions">
      <button class="btn small" data-dbconnbrowse="${esc(c.id)}">浏览数据</button>
      <button class="btn small" data-dbconntest="${esc(c.id)}">测试连接</button>
      <button class="btn small" data-dbconnedit="${esc(c.id)}">编辑</button>
      <button class="btn small" data-dbconndel="${esc(c.id)}">删除</button>
    </div>
  </div>`).join("");
}

function dbResetConnForm() {
  const d = dbState();
  d.editing = null;
  $("dbFormTitle").textContent = "新增外部数据库";
  ["dbConnName", "dbConnHost", "dbConnDatabase", "dbConnUser", "dbConnPassword", "dbConnPath", "dbConnNote", "dbConnUrl"].forEach((id) => { if ($(id)) $(id).value = ""; });
  $("dbConnEngine").value = "mysql";
  $("dbConnSsl").checked = false;
  $("dbConnPort").value = "";
  dbEngineChange();
  dbSetStatus("dbConnStatus", "");
  $("dbConnPassword").placeholder = "编辑时留空表示不修改";
  $("dbConnSave").textContent = "保存连接";
}

function dbEngineChange() {
  const engine = $("dbConnEngine").value;
  const net = engine !== "sqlite";
  $("dbNetworkFields").hidden = !net;
  $("dbSqliteField").hidden = net;
  $("dbSslRow").hidden = !net;
  $("dbEngineHint").textContent = engine === "mysql"
    ? "MySQL / MariaDB：需要账号有建库、建表权限；远程连接要放行 3306。"
    : engine === "postgres"
      ? "PostgreSQL：远程连接要放行 5432；迁移时会自动创建数据库（如账号有权限）。"
      : "SQLite 文件：可以选本机任意 .db 路径；不存在也能先保存。";
  if (engine === "mysql") { if (!$("dbConnPort").value) $("dbConnPort").placeholder = "3306"; }
  else if (engine === "postgres") { if (!$("dbConnPort").value) $("dbConnPort").placeholder = "5432"; }
}

function dbEditConn(id) {
  const d = dbState();
  const c = d.connections.find((x) => x.id === id);
  if (!c) return;
  d.editing = id;
  $("dbFormTitle").textContent = "编辑连接 · " + c.name;
  $("dbConnEngine").value = c.engine;
  $("dbConnName").value = c.name || "";
  $("dbConnHost").value = c.host || "";
  $("dbConnPort").value = c.port || "";
  $("dbConnDatabase").value = c.database || "";
  $("dbConnUser").value = c.username || "";
  $("dbConnPassword").value = "";
  $("dbConnPassword").placeholder = c.password_set ? "已保存密码；留空表示不修改" : "填写数据库密码";
  $("dbConnPath").value = c.path || "";
  $("dbConnSsl").checked = !!c.ssl;
  $("dbConnNote").value = c.note || "";
  $("dbConnSave").textContent = "保存修改";
  dbEngineChange();
  dbSetStatus("dbConnStatus", "正在编辑已有连接；密码留空不会覆盖原密码。");
  $("dbConnName").focus();
}

function dbCollectConnForm() {
  const engine = $("dbConnEngine").value;
  const body = {
    engine,
    name: $("dbConnName").value.trim(),
    host: $("dbConnHost").value.trim(),
    port: Number($("dbConnPort").value) || 0,
    database: $("dbConnDatabase").value.trim(),
    username: $("dbConnUser").value.trim(),
    password: $("dbConnPassword").value,
    path: $("dbConnPath").value.trim(),
    ssl: $("dbConnSsl").checked,
    note: $("dbConnNote").value.trim(),
  };
  if (!body.name) throw new Error("请给连接起一个名字，例如“云服务器 MySQL”");
  if (engine === "sqlite" && !body.path) throw new Error("请填写 SQLite 文件路径");
  if (engine !== "sqlite") {
    if (!body.database) throw new Error("请填写数据库名");
    if (!body.username) throw new Error("请填写数据库用户名");
  }
  return body;
}

async function dbSaveConn(testAfter = false) {
  const d = dbState();
  let body;
  try { body = dbCollectConnForm(); }
  catch (e) { dbSetStatus("dbConnStatus", e.message, "bad"); return null; }
  const btn = testAfter ? $("dbConnTestNew") : $("dbConnSave");
  btn.disabled = true;
  dbSetStatus("dbConnStatus", "正在保存…");
  try {
    let row;
    if (d.editing) {
      row = await api("/api/admin/database/connections/" + encodeURIComponent(d.editing), {
        method: "PUT", body: JSON.stringify(body),
      });
    } else {
      row = await api("/api/admin/database/connections", { method: "POST", body: JSON.stringify(body) });
    }
    await dbLoadConnections();
    d.editing = row.id;
    $("dbFormTitle").textContent = "编辑连接 · " + row.name;
    $("dbConnSave").textContent = "保存修改";
    $("dbConnPassword").value = "";
    $("dbConnPassword").placeholder = "已保存密码；留空表示不修改";
    dbSetStatus("dbConnStatus", `已保存：${row.name}（${row.engine_label}）`, "ok");
    uiToast("连接已保存", "ok");
    if (testAfter) return await dbTestConn(row.id, true);
    return row;
  } catch (e) {
    dbSetStatus("dbConnStatus", "保存失败：" + e.message, "bad");
    return null;
  } finally {
    btn.disabled = false;
  }
}

async function dbTestConn(id, quiet = false) {
  dbSetStatus("dbConnStatus", "正在测试连接…");
  try {
    const res = await api("/api/admin/database/connections/" + encodeURIComponent(id) + "/test", { method: "POST" });
    const text = `${res.ok ? "连接成功" : "连接失败"} · ${res.info || res.engine} · ${res.version || ""} · ${res.tables} 个表 · ${res.latency_ms} ms${res.message ? " · " + res.message : ""}`;
    dbSetStatus("dbConnStatus", text, res.ok ? "ok" : "bad");
    if (!quiet) uiToast(text, res.ok ? "ok" : "bad");
    dbLoadConnections().catch(() => {});
    return res;
  } catch (e) {
    dbSetStatus("dbConnStatus", "测试失败：" + e.message, "bad");
    if (!quiet) uiToast("测试失败：" + e.message, "bad");
    return null;
  }
}

async function dbDeleteConn(id) {
  const d = dbState();
  const c = d.connections.find((x) => x.id === id);
  const ok = await confirmInline(`确定删除连接“${c ? c.name : id}”？这不会删除目标数据库里的数据，只是从本机移除记录。`, "删除连接");
  if (!ok) return;
  try {
    await api("/api/admin/database/connections/" + encodeURIComponent(id), { method: "DELETE" });
    if (d.conn === id) d.conn = "local";
    if (d.sqlConn === id) d.sqlConn = "local";
    if (d.editing === id) dbResetConnForm();
    await dbLoadConnections();
    dbFillConnSelects();
    uiToast("连接已删除", "ok");
    if (d.view === "browse") await dbLoadBrowse();
  } catch (e) { uiToast("删除失败：" + e.message, "bad"); }
}

async function dbParseConnUrl() {
  const url = $("dbConnUrl").value.trim();
  if (!url) { dbSetStatus("dbConnStatus", "先粘贴连接串，例如 mysql://root:密码@127.0.0.1:3306/workbench", "bad"); return; }
  try {
    const p = await api("/api/admin/database/connections/parse", { method: "POST", body: JSON.stringify({ url }) });
    const label = { mysql: "MySQL / MariaDB", postgres: "PostgreSQL", sqlite: "SQLite" }[p.engine] || p.engine;
    $("dbConnEngine").value = p.engine;
    $("dbConnName").value = p.name || label;
    $("dbConnHost").value = p.host || "";
    $("dbConnPort").value = p.port || "";
    $("dbConnDatabase").value = p.database || "";
    $("dbConnUser").value = p.username || "";
    $("dbConnPassword").value = p.password || "";
    $("dbConnPath").value = p.engine === "sqlite" ? (p.path || p.database || "") : "";
    $("dbConnSsl").checked = !!p.ssl;
    dbEngineChange();
    dbSetStatus("dbConnStatus", "连接串已解析，请检查字段后点“保存连接”。", "ok");
  } catch (e) { dbSetStatus("dbConnStatus", "解析失败：" + e.message, "bad"); }
}

/* ---------------------------------------------------------------- 备份与导出 */
async function dbDownload(url, opts, fallbackName) {
  const headers = { ...(opts.headers || {}) };
  if (token()) headers.Authorization = "Bearer " + token();
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
  if (!r.ok) {
    let msg = "下载失败";
    try { const d = await r.json(); msg = d.detail || msg; } catch {}
    throw new Error(msg);
  }
  const blob = await r.blob();
  let name = fallbackName;
  const cd = r.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^";]+)"?/i);
  if (m) name = m[1];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  uiToast("已开始下载：" + name, "ok");
  return name;
}

async function dbBackup() {
  const d = dbState();
  if (d.conn !== "local") { uiToast("快照只针对当前工作台 SQLite；外部库请用导出 SQL。", "warn"); return; }
  const ok = await confirmInline("生成当前 SQLite 的一致性快照并下载？不会修改现有数据。", "生成并下载");
  if (!ok) return;
  try {
    await dbDownload(`/api/admin/database/backup?connection=${encodeURIComponent(d.conn)}`, { method: "POST" }, "database-backup.db");
  } catch (e) { dbSetStatus("dbOpsHint", "备份失败：" + e.message, "bad"); }
}

async function dbExportSql(engine) {
  const d = dbState();
  const ok = await confirmInline(`把当前工作台数据导出成 ${engine === "mysql" ? "MySQL" : "PostgreSQL"} 的 .sql 脚本？文件会下载到浏览器。`, "导出脚本");
  if (!ok) return;
  try {
    await dbDownload(`/api/admin/database/export-sql?connection=local&target_engine=${engine}`, { method: "POST" }, `workbench-${engine}.sql`);
  } catch (e) { dbSetStatus("dbOpsHint", "导出失败：" + e.message, "bad"); }
}

async function dbExportCsv() {
  const d = dbState();
  if (!d.table) return;
  try {
    await dbDownload(`/api/admin/database/table/${encodeURIComponent(d.table)}/export.csv?connection=${encodeURIComponent(d.conn)}`, {}, d.table + ".csv");
  } catch (e) { uiToast("导出失败：" + e.message, "bad"); }
}

async function dbVacuum() {
  const d = dbState();
  if (d.conn !== "local") { uiToast("空间整理只对 SQLite 开放。", "warn"); return; }
  const ok = await confirmInline("VACUUM 会重建 SQLite 文件并释放空闲页，期间不要关闭工作台。继续？", "开始整理");
  if (!ok) return;
  try {
    const res = await api("/api/admin/database/vacuum", { method: "POST" });
    dbSetStatus("dbOpsHint", `整理完成：${dbFmtBytes(res.before)} → ${dbFmtBytes(res.after)}，释放 ${dbFmtBytes(res.saved)}。`, "ok");
    uiToast("空间整理完成", "ok");
    dbLoadOverview().catch(() => {});
    dbLoadHealth().catch(() => {});
  } catch (e) { dbSetStatus("dbOpsHint", "整理失败：" + e.message, "bad"); }
}

/* ---------------------------------------------------------------- 一键迁移 */
function dbFillMigrateTargets() {
  const d = dbState();
  const sel = $("dbMigrateTarget");
  if (!sel) return;
  const conns = d.connections || [];
  const old = d.migrateConn || sel.value;
  sel.innerHTML = conns.length
    ? conns.map((c) => `<option value="${esc(c.id)}">${esc(c.name)} · ${esc(dbTargetText(c))}</option>`).join("")
    : `<option value="">先添加一个外部连接</option>`;
  if (conns.length) {
    sel.value = conns.some((c) => c.id === old) ? old : conns[0].id;
    d.migrateConn = sel.value;
  } else {
    d.migrateConn = "";
  }
}

function dbRenderPreflight(res) {
  const box = $("dbPreflightResult");
  if (!box) return;
  if (!res.ok) { box.innerHTML = `<div class="db-sql-error">检查未通过：${esc(res.error || "未知错误")}</div>`; return; }
  const conflicts = res.conflicts || [];
  const warnings = res.warnings || [];
  box.innerHTML = `<div class="db-sql-notice ${conflicts.length ? "" : ""}">
    <b>${res.ready ? "可以开始迁移。" : "目标库有同名表，不能直接迁移。"}</b>
    目标：${esc(res.engine_label || res.engine)} / ${esc(res.database || "")}；源库 ${res.tables} 张表、约 ${dbNum(res.rows)} 行。
    ${conflicts.length ? `<br>冲突表：${conflicts.map(esc).join("、")}${res.overwrite ? "（已选择覆盖）" : "（请勾选“覆盖同名表”）"}` : ""}
    ${warnings.length ? `<br>提醒：${warnings.map(esc).join("；")}` : ""}
  </div>`;
}

async function dbPreflight() {
  const d = dbState();
  const id = $("dbMigrateTarget").value;
  if (!id) { dbSetStatus("dbMigrateStatus", "先在“外部连接”里添加目标数据库。", "bad"); return; }
  d.migrateConn = id;
  $("dbPreflight").disabled = true;
  dbSetStatus("dbMigrateStatus", "正在检查目标库…");
  try {
    const res = await api("/api/admin/database/migrate/preflight", {
      method: "POST",
      body: JSON.stringify({ connection_id: id, create_database: $("dbMigrateCreate").checked, overwrite: $("dbMigrateOverwrite").checked }),
    });
    dbRenderPreflight(res);
    dbSetStatus("dbMigrateStatus", res.message || (res.ready ? "检查通过" : "检查未通过"), res.ok && res.ready ? "ok" : "bad");
  } catch (e) {
    dbSetStatus("dbMigrateStatus", "检查失败：" + e.message, "bad");
    $("dbPreflightResult").innerHTML = `<div class="db-sql-error">检查失败：${esc(e.message)}</div>`;
  } finally { $("dbPreflight").disabled = false; }
}

async function dbStartMigrate() {
  const d = dbState();
  const id = $("dbMigrateTarget").value;
  if (!id) { dbSetStatus("dbMigrateStatus", "先在“外部连接”里添加目标数据库。", "bad"); return; }
  const overwrite = $("dbMigrateOverwrite").checked;
  if (overwrite) {
    const ok = await confirmInline("覆盖会先清理目标库里的同名表，再写入当前数据。确认继续？", "确认覆盖迁移");
    if (!ok) return;
  }
  d.migrateConn = id;
  $("dbStartMigrate").disabled = true;
  $("dbMigrateVerifiedWrap").hidden = true;
  $("dbMigrateBrowse").hidden = true;
  $("dbMigrateProgress").hidden = false;
  $("dbMigrateBar").style.width = "0%";
  $("dbMigrateText").textContent = "正在启动迁移…";
  $("dbMigrateLog").innerHTML = "";
  dbSetStatus("dbMigrateStatus", "");
  dbRenderPreflight({ ok: true, ready: true, tables: 0, rows: 0, warnings: [], message: "" });
  try {
    const job = await api("/api/admin/database/migrate", {
      method: "POST",
      body: JSON.stringify({ connection_id: id, create_database: $("dbMigrateCreate").checked, overwrite }),
    });
    d.lastJobId = job.id;
    dbWatchJob(job.id);
  } catch (e) {
    $("dbStartMigrate").disabled = false;
    dbSetStatus("dbMigrateStatus", "启动失败：" + e.message, "bad");
  }
}

function dbRenderJob(job) {
  const pct = Number(job.progress || 0);
  $("dbMigrateProgress").hidden = false;
  $("dbMigrateBar").style.width = pct + "%";
  $("dbMigrateText").textContent = `${job.message || ""} · ${pct}%`;
  const logs = job.logs || [];
  $("dbMigrateLog").innerHTML = logs.map((l) => `<div>[${l.pct}%] ${esc(l.message)}</div>`).join("");
  if (job.status === "running") return;
  $("dbStartMigrate").disabled = false;
  if (job.status === "ok") {
    dbSetStatus("dbMigrateStatus", "迁移完成，所有表行数校验通过。", "ok");
    uiToast("迁移完成", "ok");
  } else if (job.status === "error") {
    dbSetStatus("dbMigrateStatus", job.error || job.message || "迁移失败", "bad");
  } else {
    dbSetStatus("dbMigrateStatus", job.message || "迁移完成，但部分表行数不一致，请检查。", "bad");
  }
  const verified = (job.result && job.result.verified) || {};
  const names = Object.keys(verified).sort();
  if (names.length) {
    $("dbMigrateVerified").innerHTML = names.map((n) => {
      const v = verified[n];
      return `<tr><td><b>${esc(n)}</b></td><td>${dbNum(v.expected)}</td><td>${dbNum(v.actual)}</td><td><span class="badge ${v.ok ? "good" : "bad"}">${v.ok ? "一致" : "不一致"}</span></td></tr>`;
    }).join("");
    $("dbMigrateVerifiedWrap").hidden = false;
  }
  if (job.status === "ok" || job.status === "error") {
    if (job.status === "ok") $("dbMigrateBrowse").hidden = false;
    else $("dbMigrateBrowse").hidden = true;
    dbLoadMigrationHistory().catch(() => {});
    dbLoadConnections().catch(() => {});
  }
}

async function dbWatchJob(id) {
  clearTimeout(dbState().jobTimer);
  const tick = async () => {
    try {
      const job = await api("/api/admin/database/migrate/" + encodeURIComponent(id));
      dbRenderJob(job);
      if (job.status === "running") dbState().jobTimer = setTimeout(tick, 1200);
    } catch (e) {
      $("dbStartMigrate").disabled = false;
      dbSetStatus("dbMigrateStatus", "读取进度失败：" + e.message, "bad");
    }
  };
  await tick();
}

async function dbLoadMigrationHistory() {
  const box = $("dbHistoryRows");
  if (!box) return;
  try {
    const res = await api("/api/admin/database/migration-history");
    const rows = res.history || [];
    box.innerHTML = rows.length ? rows.map((h) => `<tr>
      <td>${h.ts ? dbFmtTime(h.ts) : "—"}</td>
      <td class="mono" style="max-width:260px">${esc(h.target || "")}</td>
      <td>${esc(h.engine || "")}</td>
      <td>${dbNum(h.tables)}</td>
      <td>${dbNum(h.rows)}</td>
      <td><span class="badge ${h.ok ? "good" : "bad"}">${h.ok ? "成功" : "有差异"}</span></td>
      <td>${dbNum(h.warnings)} 条</td>
    </tr>`).join("") : `<tr><td class="db-empty" colspan="7">还没有迁移记录。</td></tr>`;
  } catch (e) { box.innerHTML = `<tr><td class="db-empty" colspan="7">读取迁移历史失败：${esc(e.message)}</td></tr>`; }
}

function dbSwitchView(name, refresh = true) {
  const d = dbState();
  d.view = name;
  document.querySelectorAll(".db-subtab").forEach((b) => b.classList.toggle("active", b.dataset.dbtab === name));
  document.querySelectorAll(".db-view").forEach((v) => { v.hidden = v.id !== "dbView-" + name; });
  if (!refresh) return;
  if (name === "connections") { dbLoadConnections().catch(() => {}); return; }
  if (name === "migrate") { dbLoadConnections().catch(() => {}); dbLoadMigrationHistory().catch(() => {}); return; }
  if (name === "browse") { dbLoadBrowse().catch((e) => uiToast(e.message, "bad")); return; }
}

/* ---------------------------------------------------------------- 数据库页面事件 */
document.addEventListener("click", async (ev) => {
  if (!S.db || S.tab !== "database") return;
  const d = dbState();
  const el = ev.target;
  const sub = el.closest("[data-dbtab]");
  if (sub) { dbSwitchView(sub.dataset.dbtab); return; }
  const tableBtn = el.closest("[data-dbtable]");
  if (tableBtn) { await dbSelectTable(tableBtn.dataset.dbtable); return; }
  const sortTh = el.closest("[data-dbsort]");
  if (sortTh) {
    const name = sortTh.dataset.dbsort;
    if (d.sort === name) d.order = d.order === "asc" ? "desc" : "asc";
    else { d.sort = name; d.order = "asc"; }
    d.page = 0;
    await dbLoadRows();
    return;
  }
  const edit = el.closest("[data-dbedit]");
  if (edit) { try { await dbOpenRowModal("edit", edit.dataset.dbedit); } catch (e) { uiToast(e.message, "bad"); } return; }
  const del = el.closest("[data-dbdel]");
  if (del) { await dbDeleteRow(del.dataset.dbdel); return; }
  const colRemove = el.closest(".db-col-remove");
  if (colRemove) { colRemove.closest(".db-col-row").remove(); return; }
  const browseConn = el.closest("[data-dbconnbrowse]");
  if (browseConn) {
    d.conn = browseConn.dataset.dbconnbrowse;
    d.table = "";
    dbFillConnSelects();
    dbSwitchView("browse");
    dbLoadOverview().catch(() => {});
    return;
  }
  const testConn = el.closest("[data-dbconntest]");
  if (testConn) { await dbTestConn(testConn.dataset.dbconntest); return; }
  const editConn = el.closest("[data-dbconnedit]");
  if (editConn) { dbEditConn(editConn.dataset.dbconnedit); return; }
  const delConn = el.closest("[data-dbconndel]");
  if (delConn) { await dbDeleteConn(delConn.dataset.dbconndel); return; }
  const sample = el.closest("[data-dbsample]");
  if (sample) { $("dbSqlText").value = sample.dataset.dbsample; $("dbSqlText").focus(); return; }
  if (el.id === "dbRefreshAll") { await loadDatabasePage(); return; }
  if (el.id === "dbRowSearchBtn") {
    d.search = $("dbRowSearch").value.trim(); d.page = 0; await dbLoadRows(); return;
  }
  if (el.id === "dbPrevPage") { if (d.page > 0) { d.page--; await dbLoadRows(); } return; }
  if (el.id === "dbNextPage") { if ((d.page + 1) * d.pageSize < d.total) { d.page++; await dbLoadRows(); } return; }
  if (el.id === "dbExportCsv") { await dbExportCsv(); return; }
  if (el.id === "dbNewRow") { try { await dbOpenRowModal("create"); } catch (e) { uiToast(e.message, "bad"); } return; }
  if (el.id === "dbCreateTableBtn") { dbOpenCreateTable(); return; }
  if (el.id === "dbTableRenameBtn") { dbOpenTableAction("rename"); return; }
  if (el.id === "dbTableTruncateBtn") { dbOpenTableAction("truncate"); return; }
  if (el.id === "dbTableDropBtn") { dbOpenTableAction("drop"); return; }
  if (el.id === "dbTableActionClose" || el.id === "dbTableActionCancel") { dbCloseTableAction(); return; }
  if (el.id === "dbTableActionConfirm") { await dbSubmitTableAction(); return; }
  if (el.id === "dbCreateTableClose" || el.id === "dbCreateTableCancel") { dbCloseCreateTable(); return; }
  if (el.id === "dbCreateTableSubmit") { await dbSubmitCreateTable(); return; }
  if (el.id === "dbAddColumnBtn") { dbNewColumnRow({ type: "TEXT", nullable: true }); return; }
  if (el.closest("[data-dbfixfk]")) { await dbRepairForeignKey(); return; }
  if (el.id === "dbHealthBtn") { await dbLoadHealth(); return; }
  if (el.id === "dbBackupBtn") { await dbBackup(); return; }
  if (el.id === "dbExportMysql") { await dbExportSql("mysql"); return; }
  if (el.id === "dbExportPg") { await dbExportSql("postgres"); return; }
  if (el.id === "dbVacuumBtn") { await dbVacuum(); return; }
  if (el.id === "dbRunSql") { await dbRunSql(); return; }
  if (el.id === "dbConnRefresh") { await dbLoadConnections(); return; }
  if (el.id === "dbConnReset") { dbResetConnForm(); return; }
  if (el.id === "dbConnTestNew") { await dbSaveConn(true); return; }
  if (el.id === "dbParseUrl") { await dbParseConnUrl(); return; }
  if (el.id === "dbPreflight") { await dbPreflight(); return; }
  if (el.id === "dbStartMigrate") { await dbStartMigrate(); return; }
  if (el.id === "dbMigrateBrowse") {
    d.conn = d.migrateConn || $("dbMigrateTarget").value;
    d.table = "";
    dbFillConnSelects();
    dbSwitchView("browse");
    dbLoadOverview().catch(() => {});
    return;
  }
  if (el.id === "dbModalClose" || el.id === "dbModalCancel") { dbCloseRowModal(); return; }
  if (el.id === "dbModalSave") { await dbSaveRow(); return; }
  if (el.id === "dbModalDelete") {
    if (!d.modal) return;
    const ok = await confirmInline("确定删除这一行？删除后不能撤销。", "确认删除");
    if (!ok) return;
    await dbDeleteRow(d.modal.key);
    return;
  }
});

document.addEventListener("change", (ev) => {
  if (!S.db || S.tab !== "database") return;
  const d = dbState();
  const colRow = ev.target.closest(".db-col-row");
  if (colRow) {
    if (ev.target.matches("[data-col-pk]") && ev.target.checked) {
      document.querySelectorAll("#dbNewColumns [data-col-pk]").forEach((box) => {
        if (box !== ev.target) { box.checked = false; dbSyncColumnRow(box.closest(".db-col-row")); }
      });
    }
    dbSyncColumnRow(colRow);
    return;
  }
  if (ev.target.id === "dbConnSelect") {
    d.conn = ev.target.value || "local"; d.table = ""; d.search = ""; d.page = 0;
    dbLoadOverview().catch(() => {});
    dbLoadBrowse().catch((e) => uiToast(e.message, "bad"));
    return;
  }
  if (ev.target.id === "dbSqlConn") { d.sqlConn = ev.target.value || "local"; return; }
  if (ev.target.id === "dbConnEngine") { dbEngineChange(); return; }
  if (ev.target.id === "dbMigrateTarget") { d.migrateConn = ev.target.value; $("dbPreflightResult").innerHTML = ""; return; }
});

document.addEventListener("input", (ev) => {
  if (!S.db || S.tab !== "database") return;
  if (ev.target.id === "dbTableFilter") {
    dbState().filter = ev.target.value.trim();
    dbRenderTableList();
    return;
  }
});

document.addEventListener("keydown", (ev) => {
  if (!S.db || S.tab !== "database") return;
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.target.id === "dbRowSearch") {
    ev.preventDefault();
    $("dbRowSearchBtn").click();
    return;
  }
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.target.id === "dbTableActionInput") {
    ev.preventDefault();
    $("dbTableActionConfirm").click();
    return;
  }
  if (ev.key === "Escape" && !$("dbRowModal").hidden) { dbCloseRowModal(); }
  if (ev.key === "Escape" && !$("dbTableActionModal").hidden) { dbCloseTableAction(); }
  if (ev.key === "Escape" && !$("dbCreateTableModal").hidden) { dbCloseCreateTable(); }
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && ev.target.id === "dbSqlText") {
    ev.preventDefault();
    $("dbRunSql").click();
  }
});

document.addEventListener("submit", async (ev) => {
  if (ev.target.id !== "dbConnForm") return;
  ev.preventDefault();
  await dbSaveConn(false);
});


/* ---------------------------------------------------------------- 多机算力池 */
function clusterStatusBadge(status) {
  const m = { online: ["good", "在线"], offline: ["bad", "离线"], unknown: ["unknown", "未检查"] };
  const v = m[status] || m.unknown;
  return `<span class="badge ${v[0]}">${v[1]}</span>`;
}

function clusterStrategyLabel(key) {
  return key === "round_robin" ? "轮询" : "加权最少连接";
}

function clusterDefaultMember() {
  const nodes = (S.cluster && S.cluster.nodes) || [];
  const node = nodes.find((n) => n.enabled) || nodes[0];
  if (!node) return { node_id: 0, remote_model: "", weight: 1 };
  return { node_id: node.id, remote_model: (node.models || [])[0] || "", weight: 1 };
}

function renderClusterCards(stats) {
  const box = $("clusterCards");
  if (!box) return;
  const cards = [
    ["节点", String(stats.nodes || 0) + " 台", `${stats.online || 0} 台在线`],
    ["当前并发", String(stats.active || 0), "正在处理的请求"],
    ["模型池", String(stats.pools || 0), "对外统一模型名"],
    ["入口", "/v1", "OpenAI 兼容"],
  ];
  box.innerHTML = cards.map(([k, v, s]) =>
    `<div class="card"><div class="k">${esc(k)}</div><div class="v" style="font-size:20px">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
}

function renderClusterNodes(nodes) {
  const box = $("clusterNodeRows");
  if (!box) return;
  if (!nodes.length) {
    box.innerHTML = `<tr><td colspan="6" class="cluster-empty">还没有节点。先在右边填写一台机器的 /v1 地址。</td></tr>`;
    $("clusterNodeHint").textContent = "还没有节点。先在右边填写一台局域网机器的地址，保存后会自动探测一次。";
    return;
  }
  $("clusterNodeHint").textContent = `共 ${nodes.length} 台，${nodes.filter((n) => n.status === "online").length} 台在线。状态每 30 秒自动检查一次。`;
  box.innerHTML = nodes.map((n) => {
    const models = n.models || [];
    const badges = models.slice(0, 3).map((m) => `<span class="badge cat" title="${esc(m)}">${esc(m)}</span>`).join("")
      + (models.length > 3 ? `<span class="badge unknown">+${models.length - 3}</span>` : "");
    return `<tr class="${n.status === "offline" ? "cluster-offline" : ""}">
      <td><div class="node-name">${esc(n.name)}</div>${n.note ? `<div class="hint">${esc(n.note)}</div>` : ""}</td>
      <td><span class="mono" style="font-size:12px">${esc(n.base_url)}</span><div class="hint">${n.has_key ? "已配 Key" : "无 Key"}</div></td>
      <td>${clusterStatusBadge(n.status)}<div class="hint">${n.latency_ms ? n.latency_ms + " ms" : ""}${n.last_error ? `<br>${esc(n.last_error)}` : ""}</div></td>
      <td><div class="node-models">${badges || `<span class="hint">未读取到模型</span>`}</div></td>
      <td><span class="badge ok">w ${n.weight}</span> <span class="badge unknown">${n.active}/${n.max_concurrency}</span></td>
      <td><div class="row-actions">
        <button class="btn small" data-cluster-node-test="${n.id}">测试</button>
        <button class="btn small" data-cluster-node-edit="${n.id}">编辑</button>
        <button class="btn small danger" data-cluster-node-del="${n.id}">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

function renderClusterPools(pools) {
  const box = $("clusterPoolRows");
  if (!box) return;
  if (!pools.length) {
    box.innerHTML = `<tr><td colspan="6" class="cluster-empty">还没有模型池。把几台机器加进同一个池，就能用一个名字调用。</td></tr>`;
    $("clusterPoolHint").textContent = "还没有模型池。先在下面把几台机器加进同一个池，再用池名调用。";
    return;
  }
  $("clusterPoolHint").textContent = `${pools.length} 个池。池内机器必须跑同一个模型；池名会出现在 /v1/models 里。`;
  box.innerHTML = pools.map((p) => {
    const members = p.members || [];
    const mHtml = members.slice(0, 4).map((m) =>
      `<span class="badge ${m.enabled ? "cat" : "off"}" title="${esc(m.node_name)}">${esc(m.node_name)} · ${esc(m.remote_model)}</span>`).join(" ")
      + (members.length > 4 ? ` <span class="badge unknown">+${members.length - 4}</span>` : "");
    return `<tr>
      <td><div class="node-name">${esc(p.name)}</div>${p.note ? `<div class="hint">${esc(p.note)}</div>` : ""}</td>
      <td>${esc(clusterStrategyLabel(p.strategy))}</td>
      <td><div class="node-models">${mHtml || `<span class="hint">没有成员</span>`}</div></td>
      <td>${esc(p.timeout)} 秒 / ${esc(p.retries)} 次</td>
      <td>${p.enabled ? `<span class="badge good">启用</span>` : `<span class="badge off">停用</span>`}</td>
      <td><div class="row-actions">
        <button class="btn small" data-cluster-pool-edit="${p.id}">编辑</button>
        <button class="btn small danger" data-cluster-pool-del="${p.id}">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

function renderClusterDistribution(nodes) {
  const box = $("clusterDistribution");
  if (!box) return;
  if (!nodes.length) { box.innerHTML = `<p class="hint">添加节点后，这里会显示当前并发分布。</p>`; return; }
  box.innerHTML = nodes.map((n) => {
    const pct = Math.min(100, Math.round((n.active / Math.max(1, n.max_concurrency)) * 100));
    return `<div class="cluster-dist-item">
      <span style="min-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(n.name)}</span>
      <div class="bar"><span style="width:${pct}%"></span></div>
      <span class="num">${n.active}/${n.max_concurrency}</span>
    </div>`;
  }).join("");
}

function renderClusterEntry(pools) {
  const box = $("clusterExample");
  if (!box) return;
  const base = location.origin + "/v1";
  const model = (pools.find((p) => p.enabled) || {}).name || "你的池名";
  box.textContent = `POST ${base}/chat/completions
Authorization: Bearer <你的 API Key>
Content-Type: application/json

{
  "model": "${model}",
  "messages": [{"role": "user", "content": "你好"}],
  "stream": false
}`;
}

function renderClusterMembers() {
  const box = $("clusterPoolMembers");
  if (!box) return;
  const nodes = (S.cluster && S.cluster.nodes) || [];
  if (!nodes.length) {
    box.innerHTML = `<div class="cluster-member-empty">还没有节点。先在上方加入至少一台机器，再把它加进模型池。</div>`;
    return;
  }
  if (!S.clusterMembers.length) S.clusterMembers = [clusterDefaultMember()];
  box.innerHTML = S.clusterMembers.map((m, idx) => {
    const opts = nodes.map((n) => `<option value="${n.id}" ${Number(m.node_id) === n.id ? "selected" : ""}>${esc(n.name)}</option>`).join("");
    return `<div class="cluster-member-row" data-member-idx="${idx}">
      <select data-member-node>${opts}</select>
      <input data-member-model value="${esc(m.remote_model || "")}" placeholder="节点上的模型名" autocomplete="off">
      <input data-member-weight type="number" min="1" max="100" value="${Number(m.weight) || 1}" title="成员权重">
      <button type="button" class="member-del" data-member-del="${idx}" title="移除">×</button>
    </div>`;
  }).join("");
}

function resetClusterNodeForm() {
  S.clusterEditNode = 0;
  $("clusterNodeFormTitle").textContent = "加入一台机器";
  $("clusterNodeCancel").hidden = true;
  $("clusterNodeName").value = "";
  $("clusterNodeBase").value = "";
  $("clusterNodeKey").value = "";
  $("clusterNodeKey").placeholder = "API Key（本机服务通常留空）";
  $("clusterNodeWeight").value = "1";
  $("clusterNodeMax").value = "4";
  $("clusterNodeNote").value = "";
  $("clusterNodeEnabled").checked = true;
  $("clusterProbeResult").textContent = "";
}

function resetClusterPoolForm() {
  S.clusterEditPool = 0;
  $("clusterPoolFormTitle").textContent = "新建模型池";
  $("clusterPoolCancel").hidden = true;
  $("clusterPoolName").value = "";
  $("clusterPoolStrategy").value = "weighted_least";
  $("clusterPoolTimeout").value = "30";
  $("clusterPoolRetries").value = "1";
  $("clusterPoolNote").value = "";
  S.clusterMembers = [clusterDefaultMember()];
  renderClusterMembers();
}

async function loadClusterPage() {
  const d = await api("/api/admin/cluster");
  S.cluster = d;
  renderClusterCards(d.stats || {});
  renderClusterNodes(d.nodes || []);
  renderClusterPools(d.pools || []);
  renderClusterDistribution(d.nodes || []);
  renderClusterEntry(d.pools || []);
  if (!S.clusterMembersInit) {
    S.clusterMembersInit = true;
    S.clusterMembers = [clusterDefaultMember()];
  }
  renderClusterMembers();
}

async function clusterSaveNode() {
  const payload = {
    name: $("clusterNodeName").value.trim(),
    base_url: $("clusterNodeBase").value.trim(),
    api_key: $("clusterNodeKey").value.trim(),
    weight: Number($("clusterNodeWeight").value) || 1,
    max_concurrency: Number($("clusterNodeMax").value) || 4,
    note: $("clusterNodeNote").value.trim(),
    enabled: $("clusterNodeEnabled").checked,
  };
  if (!payload.name || !payload.base_url) throw new Error("机器名和地址不能为空");
  let node;
  if (S.clusterEditNode) {
    if (!payload.api_key) delete payload.api_key;
    const res = await api(`/api/admin/cluster/nodes/${S.clusterEditNode}`, { method: "PATCH", body: JSON.stringify(payload) });
    node = res.node;
    uiToast("节点已保存");
  } else {
    const res = await api("/api/admin/cluster/nodes", { method: "POST", body: JSON.stringify(payload) });
    node = res.node;
    uiToast("节点已加入，正在探测");
  }
  resetClusterNodeForm();
  await loadClusterPage();
  if (node && node.id) {
    api(`/api/admin/cluster/nodes/${node.id}/test`, { method: "POST" }).catch(() => {});
  }
}

async function clusterProbe() {
  const base = $("clusterNodeBase").value.trim();
  if (!base) throw new Error("先填节点地址");
  const res = await api("/api/admin/cluster/probe", {
    method: "POST",
    body: JSON.stringify({ base_url: base, api_key: $("clusterNodeKey").value.trim() }),
  });
  const box = $("clusterProbeResult");
  box.textContent = res.ok ? `连接成功 · ${res.latency_ms} ms · ${(res.models || []).length} 个模型` : `连接失败 · ${res.detail || ""}`;
  box.style.color = res.ok ? "#0f7b3f" : "#b03b3b";
}

async function clusterSavePool() {
  const name = $("clusterPoolName").value.trim();
  if (!name) throw new Error("统一模型名不能为空");
  const members = S.clusterMembers.filter((m) => Number(m.node_id) > 0 && String(m.remote_model || "").trim());
  if (!members.length) throw new Error("至少加一台成员机器，并填节点上的模型名");
  const payload = {
    name,
    strategy: $("clusterPoolStrategy").value,
    timeout: Number($("clusterPoolTimeout").value) || 30,
    retries: Number($("clusterPoolRetries").value) || 0,
    note: $("clusterPoolNote").value.trim(),
    members: members.map((m) => ({
      node_id: Number(m.node_id),
      remote_model: String(m.remote_model).trim(),
      weight: Number(m.weight) || 1,
    })),
  };
  if (S.clusterEditPool) {
    await api(`/api/admin/cluster/pools/${S.clusterEditPool}`, { method: "PATCH", body: JSON.stringify(payload) });
    uiToast("模型池已保存");
  } else {
    await api("/api/admin/cluster/pools", { method: "POST", body: JSON.stringify(payload) });
    uiToast("模型池已创建，池名已加入 /v1/models");
  }
  resetClusterPoolForm();
  await loadClusterPage();
}

function clusterFillNodeForm(node) {
  S.clusterEditNode = node.id;
  $("clusterNodeFormTitle").textContent = "编辑节点 · " + node.name;
  $("clusterNodeCancel").hidden = false;
  $("clusterNodeName").value = node.name || "";
  $("clusterNodeBase").value = node.base_url || "";
  $("clusterNodeKey").value = "";
  $("clusterNodeKey").placeholder = node.has_key ? `已保存 ${node.api_key_masked}，留空不改` : "API Key（本机服务通常留空）";
  $("clusterNodeWeight").value = String(node.weight || 1);
  $("clusterNodeMax").value = String(node.max_concurrency || 4);
  $("clusterNodeNote").value = node.note || "";
  $("clusterNodeEnabled").checked = !!node.enabled;
  $("clusterNodeFormPanel").scrollIntoView({ block: "start" });
}

function clusterFillPoolForm(pool) {
  S.clusterEditPool = pool.id;
  $("clusterPoolFormTitle").textContent = "编辑模型池 · " + pool.name;
  $("clusterPoolCancel").hidden = false;
  $("clusterPoolName").value = pool.name || "";
  $("clusterPoolStrategy").value = pool.strategy || "weighted_least";
  $("clusterPoolTimeout").value = String(pool.timeout || 30);
  $("clusterPoolRetries").value = String(pool.retries || 0);
  $("clusterPoolNote").value = pool.note || "";
  S.clusterMembers = (pool.members || []).map((m) => ({
    node_id: m.node_id, remote_model: m.remote_model, weight: m.weight || 1,
  }));
  renderClusterMembers();
  $("clusterPoolName").scrollIntoView({ block: "start" });
}


document.addEventListener("change", (ev) => {
  const row = ev.target.closest(".cluster-member-row");
  if (!row) return;
  const idx = Number(row.dataset.memberIdx);
  if (!S.clusterMembers[idx]) return;
  if (ev.target.matches("[data-member-node]")) {
    const nodeId = Number(ev.target.value);
    S.clusterMembers[idx].node_id = nodeId;
    const node = ((S.cluster && S.cluster.nodes) || []).find((n) => n.id === nodeId);
    const models = (node && node.models) || [];
    if (models.length && !models.includes(S.clusterMembers[idx].remote_model)) {
      S.clusterMembers[idx].remote_model = models[0];
      row.querySelector("[data-member-model]").value = models[0];
    }
  }
  if (ev.target.matches("[data-member-model]")) S.clusterMembers[idx].remote_model = ev.target.value.trim();
  if (ev.target.matches("[data-member-weight]")) S.clusterMembers[idx].weight = Number(ev.target.value) || 1;
});

document.addEventListener("input", (ev) => {
  const row = ev.target.closest(".cluster-member-row");
  if (!row) return;
  const idx = Number(row.dataset.memberIdx);
  if (!S.clusterMembers[idx]) return;
  if (ev.target.matches("[data-member-model]")) S.clusterMembers[idx].remote_model = ev.target.value;
  if (ev.target.matches("[data-member-weight]")) S.clusterMembers[idx].weight = Number(ev.target.value) || 1;
});

/* ---------------------------------------------------------------- 自定义技能 */
S.skillAdmin = null;
S.skillEdit = 0;
S.skillIcons = ["spark", "list", "translate", "edit", "code", "file", "plan"];
const SKILL_ICON_LABELS = { spark: "通用", list: "清单 / 总结", translate: "翻译", edit: "改写", code: "代码", file: "文件", plan: "规划" };

function fillSkillIconSelect() {
  const sel = $("esIcon");
  if (!sel) return;
  const current = sel.value || "spark";
  sel.innerHTML = S.skillIcons.map((k) => `<option value="${esc(k)}">${esc(SKILL_ICON_LABELS[k] || k)}</option>`).join("");
  sel.value = S.skillIcons.includes(current) ? current : "spark";
}

/* ================================================================ 提示词中心 */
const PROMPT_GROUP_ORDER = ["core", "skill", "plugin", "format", "workbench", "agent"];
const PROMPT_GROUP_LABEL = {
  core: "核心规则", skill: "技能", plugin: "功能与插件",
  format: "输出格式", workbench: "工作台模板", agent: "智能体",
};
const PROMPT_KIND_CLASS = {
  core: "prompt-kind-core", skill: "prompt-kind-skill", plugin: "prompt-kind-plugin",
  format: "prompt-kind-format", workbench: "prompt-kind-workbench", agent: "prompt-kind-agent",
};
const PROMPT_FORMAT_LABEL = { docx: "Word", xlsx: "Excel", pptx: "PPT", pdf: "PDF", md: "Markdown", txt: "纯文本", "": "聊天正文" };

function promptTokenCount(n) {
  return Math.max(1, Math.round(Number(n || 0) / 2));
}

function promptAssetByKey(key) {
  return ((S.promptData && S.promptData.items) || []).find((x) => x.key === key) || null;
}

function promptStateText(item) {
  if (item.external_type === "agent") return item.enabled ? "可查看" : "已停用";
  if (item.external_type === "custom_skill") return item.enabled ? "已启用" : "已停用";
  if (item.kind === "plugin" && item.switch_key) return item.switch_enabled ? "功能开" : "功能关";
  if (!item.enabled) return "已停用";
  if (item.overridden) return "已覆盖";
  return "默认";
}

function renderPromptStats(data) {
  const counts = data.counts || {};
  const cards = [
    ["提示词资产", `${data.total || 0} 个`, `已启用 ${data.enabled || 0} 个 · 修订 #${data.revision || 0}`],
    ["技能", `${counts.skill || 0} 个`, `内置 6 个 + 自定义 ${Math.max(0, (counts.skill || 0) - 6)} 个`],
    ["功能与格式规则", `${(counts.plugin || 0) + (counts.format || 0)} 条`, "联网、知识库、资料库、记忆与 6 种输出"],
    ["工作台模板", `${counts.workbench || 0} 个`, "9 个内置模板的欢迎语和推荐任务"],
  ];
  $("promptStats").innerHTML = cards.map(([k, v, s]) =>
    `<div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
}

function renderPromptChain(data) {
  const switches = data.switches || {};
  const items = data.items || [];
  const steps = (data.pipeline || []).map((step) => {
    let target = step.key;
    let enabled = true;
    if (step.key === "skill") {
      const skills = items.filter((x) => x.kind === "skill" && x.enabled && !x.external);
      target = (skills[0] || {}).key || "skill.summary";
      enabled = skills.length > 0;
    } else if (step.key === "function.kb_hint") {
      enabled = !!switches.kb;
    } else if (step.key === "function.library_hint") {
      enabled = !!switches.library;
    } else if (step.key === "function.memory_rules") {
      enabled = !!switches.memory;
    } else if (step.key === "function.web_rules_general") {
      enabled = !!switches.web;
    }
    return `<button class="prompt-chain-step ${enabled ? "" : "off"}" data-prompt-jump="${esc(target)}" type="button">
      <span class="dot"></span><span>${esc(step.label)}</span><small>${enabled ? "生效" : "关闭"}</small>
    </button>`;
  });
  $("promptChain").innerHTML = steps.join('<span class="prompt-chain-arrow">→</span>');
}

function promptMatches(item) {
  if (S.promptFilter !== "all" && item.kind !== S.promptFilter) return false;
  const q = S.promptSearch.trim().toLowerCase();
  if (!q) return true;
  return [item.name, item.description, item.key, item.kind_label]
    .some((x) => String(x || "").toLowerCase().includes(q));
}

function renderPromptList() {
  const data = S.promptData || { items: [] };
  const all = data.items || [];
  const filtered = all.filter(promptMatches);
  const groups = PROMPT_GROUP_ORDER.map((kind) => [kind, filtered.filter((x) => x.kind === kind)])
    .filter(([, list]) => list.length);
  if (!groups.length) {
    $("promptList").innerHTML = `<div class="prompt-empty" style="min-height:220px;padding:24px"><h2>没有匹配的提示词</h2><p>换个关键词或切回“全部”。</p></div>`;
    return;
  }
  $("promptList").innerHTML = groups.map(([kind, list]) => {
    const rows = list.map((item) => {
      const active = item.key === S.promptKey;
      const state = promptStateText(item);
      const stateClass = state === "已覆盖" ? "over" : state.startsWith("功能关") || state === "已停用" ? "" : "on";
      return `<button class="prompt-item ${active ? "active" : ""}" data-prompt-key="${esc(item.key)}" type="button">
        <div class="prompt-item-top">
          <span class="prompt-kind-dot ${PROMPT_KIND_CLASS[item.kind] || ""}"></span>
          <b>${esc(item.name)}</b>
          <span class="prompt-item-state ${stateClass}">${esc(state)}</span>
        </div>
        <div class="prompt-item-meta">
          <span>${esc(item.kind_label || kind)}</span>
          <span>${promptTokenCount((item.content || "").length)} tokens</span>
          <span>${item.updated_at ? fmtTime(item.updated_at).slice(0, 11) : "未修改"}</span>
        </div>
      </button>`;
    }).join("");
    return `<div class="prompt-group-label"><span>${esc(PROMPT_GROUP_LABEL[kind] || kind)}</span><span>${list.length}</span></div>${rows}`;
  }).join("");
  $("promptListHint").textContent = `显示 ${filtered.length} / ${all.length} 个资产`;
}

function fillPromptPreviewSkills() {
  const skills = ((S.promptData && S.promptData.items) || [])
    .filter((x) => x.kind === "skill" && x.enabled && (x.key.startsWith("skill.") || x.key.startsWith("custom_skill.")));
  const current = S.promptKey.startsWith("skill.")
    ? S.promptKey.slice(6)
    : S.promptKey.startsWith("custom_skill.")
      ? "custom_" + S.promptKey.split(".").pop()
      : "";
  $("promptPvSkill").innerHTML = `<option value="">不选技能</option>` + skills.map((s) => {
    const sid = (s.meta && s.meta.skill_id) || (s.key.startsWith("skill.") ? s.key.slice(6) : "custom_" + s.key.split(".").pop());
    return `<option value="${esc(sid)}" ${current === sid ? "selected" : ""}>${esc(s.name)}</option>`;
  }).join("");
  if (S.promptKey.startsWith("format.")) $("promptPvFormat").value = S.promptKey.slice(7);
  else if ($("promptPvFormat").value && !["docx", "xlsx", "pptx", "pdf", "md", "txt"].includes($("promptPvFormat").value)) {
    $("promptPvFormat").value = "";
  }
}

async function loadPromptsPage() {
  const data = await api("/api/admin/prompts");
  S.promptData = data;
  S.promptLoadedAt = Date.now();
  $("promptRevision").textContent = "#" + (data.revision || 0);
  $("promptRevisionHint").textContent = "保存后下一条消息生效";
  renderPromptStats(data);
  renderPromptChain(data);
  renderPromptList();
  fillPromptPreviewSkills();
  if (!S.promptKey || !promptAssetByKey(S.promptKey)) {
    const first = (data.items || []).find((x) => x.key === "core.system")
      || (data.items || [])[0];
    if (first) await selectPrompt(first.key, true);
    else showPromptEmpty();
    return;
  }
  await selectPrompt(S.promptKey, true);
}

function showPromptEmpty() {
  $("promptEmpty").hidden = false;
  $("promptEditor").hidden = true;
  S.promptDetail = null;
  S.promptKey = "";
}

function promptBadgesFor(item) {
  const badges = [];
  if (!item.enabled) badges.push(`<span class="badge off">已停用</span>`);
  if (item.overridden && !item.external) badges.push(`<span class="badge warn">已覆盖默认</span>`);
  if (item.external_type === "agent") badges.push(`<span class="badge">智能体页维护</span>`);
  if (item.kind === "plugin" && item.switch_key) {
    badges.push(`<span class="badge ${item.switch_enabled ? "ok" : "off"}">${esc(item.switch_enabled ? "功能已开启" : "功能已关闭")}</span>`);
  }
  if (item.overridden && !item.external && item.updated_by) badges.push(`<span class="badge">修改人：${esc(item.updated_by)}</span>`);
  return badges.join("");
}

function setPromptDirty(dirty) {
  S.promptDirty = !!dirty;
  $("promptSaveState").textContent = dirty ? "有未保存的修改" : "已保存，下一条消息生效";
  $("promptSaveState").style.color = dirty ? "var(--warn)" : "var(--muted)";
}

function promptEditorNoteFor(item) {
  if (item.external_type === "agent") return "智能体提示词只读展示；请到“智能体”页编辑，避免两处同时修改。";
  if (item.kind === "plugin") {
    const page = { web: "联网", kb: "知识库", library: "资料库", memory: "记忆" }[item.plugin_id] || "对应功能页";
    return `功能开关在“${page}”页管理；这里修改的是资料注入后的说明文字。`;
  }
  if (item.kind === "format") return "只在用户要求生成对应文件时追加；修改后新生成的文件按新规则排版。";
  if (item.kind === "workbench") return "保存后，用户端重新进入工作台即可看到新的欢迎语和推荐任务。";
  if (item.external_type === "custom_skill") return "自定义技能保存后立即出现在用户端技能菜单，已有历史回复不变。";
  if (item.kind === "core") return "保存会同步写入运行时注册表和配置文件，新对话立即使用。";
  return "内置技能可覆盖默认；恢复默认不会删除历史版本。";
}

async function selectPrompt(key, force = false) {
  if (!force && S.promptDirty && key !== S.promptKey) {
    const ok = await confirmInline("当前提示词有未保存的修改，仍要切换吗？", "切换");
    if (!ok) return;
  }
  try {
    const item = await api("/api/admin/prompts/" + encodeURIComponent(key));
    S.promptKey = key;
    S.promptDetail = item;
    S.promptWb = null;
    renderPromptList();
    renderPromptEditor(item);
    setPromptDirty(false);
    renderPromptVersions(item.versions || []);
    fillPromptPreviewSkills();
    $("promptEmpty").hidden = true;
    $("promptEditor").hidden = false;
  } catch (e) {
    uiToast(e.message, "bad");
    if (String(e.message).includes("不存在")) showPromptEmpty();
  }
}

function renderPromptEditor(item) {
  $("promptKindBadge").textContent = item.kind_label || "提示词";
  $("promptKindBadge").className = "prompt-kind";
  $("promptTitle").textContent = item.name || item.key;
  $("promptDescription").textContent = item.description || "尚未填写说明";
  $("promptBadges").innerHTML = promptBadgesFor(item);
  $("promptEditorNote").textContent = promptEditorNoteFor(item);

  const readonly = item.external_type === "agent";
  const isWb = item.kind === "workbench" && !readonly;
  $("promptGenericEditor").hidden = isWb;
  $("promptWbEditor").hidden = !isWb;
  $("promptSaveBtn").disabled = readonly;
  $("promptSaveBtn").textContent = readonly ? "只读资产" : "保存并生效";
  $("promptPreviewBtn").disabled = readonly;

  const showEnabled = !readonly && (item.kind === "skill" || item.kind === "workbench");
  $("promptEnabledWrap").hidden = !showEnabled;
  $("promptEnabled").checked = !!item.enabled;

  $("promptResetBtn").hidden = readonly || item.external || !item.default_content || !item.overridden;
  $("promptRestoreLatestBtn").hidden = readonly || item.external || (item.versions || []).length < 2;

  if (isWb) {
    try {
      S.promptWb = JSON.parse(item.content || "{}");
    } catch {
      S.promptWb = { id: (item.meta || {}).template_id || item.key.split(".").pop(), name: item.name, quick: [] };
    }
    renderPromptWorkbench(S.promptWb, item);
  } else {
    $("promptContent").value = item.content || "";
    $("promptContent").readOnly = readonly;
    updatePromptCounter();
  }
  $("promptVersionsBox").hidden = readonly;
}

function updatePromptCounter() {
  const n = $("promptContent").value.length;
  $("promptCounter").textContent = `${fmtInt(n)} 字 · 约 ${fmtInt(promptTokenCount(n))} tokens`;
}

function renderPromptWorkbench(tpl, item) {
  const safe = tpl || {};
  $("pwName").value = safe.name || item.name || "";
  $("pwIcon").value = safe.icon || "🧩";
  $("pwDesc").value = safe.desc || "";
  $("pwWelcome").value = safe.welcome || "";
  $("pwWelcomeSub").value = safe.welcomeSub || "";
  renderPromptQuick(safe.quick || []);
  const skills = safe.skills || (safe.skill ? [safe.skill] : []);
  const plugins = (safe.plugins || []).map((x) => ({ web: "联网", kb: "知识库", docgen: "文档生成" }[x] || x));
  $("pwDefaultTags").innerHTML = `<span>默认技能：</span>${skills.length ? skills.map((x) => `<span class="badge">${esc(x)}</span>`).join("") : '<span class="badge off">无</span>'}
    <span style="margin-left:8px">插件：</span>${plugins.length ? plugins.map((x) => `<span class="badge">${esc(x)}</span>`).join("") : '<span class="badge off">无</span>'}`;
}

function promptQuickRow(q, idx) {
  const formats = [["", "聊天正文"], ["docx", "Word"], ["xlsx", "Excel"], ["pptx", "PPT"], ["pdf", "PDF"], ["md", "Markdown"], ["txt", "纯文本"]];
  return `<div class="wb-quick-item" data-qidx="${idx}">
    <input data-q-label placeholder="按钮名称" maxlength="12" value="${esc(q.label || "")}">
    <textarea data-q-text placeholder="点击后填入输入框的提示词" rows="2">${esc(q.text || "")}</textarea>
    <select data-q-format>${formats.map(([v, l]) => `<option value="${v}" ${(q.format || "") === v ? "selected" : ""}>${l}</option>`).join("")}</select>
    <button class="wb-quick-remove" data-q-remove title="删除这一条" type="button">×</button>
  </div>`;
}

function renderPromptQuick(list) {
  const items = (list || []).slice(0, 8);
  if (!items.length) {
    $("pwQuickList").innerHTML = `<div class="hint" style="padding:12px;text-align:center;border:1px dashed var(--line);border-radius:9px">还没有推荐任务，点右上角“加一条”添加。</div>`;
    return;
  }
  $("pwQuickList").innerHTML = items.map(promptQuickRow).join("");
}

function collectPromptWorkbench() {
  const quick = [...$("pwQuickList").querySelectorAll(".wb-quick-item")].map((row, idx) => ({
    label: row.querySelector("[data-q-label]").value.trim(),
    text: row.querySelector("[data-q-text]").value.trim(),
    format: row.querySelector("[data-q-format]").value,
    _idx: idx,
  }));
  if (!quick.length) throw new Error("至少保留一条推荐任务");
  const bad = quick.find((x) => !x.label || !x.text);
  if (bad) throw new Error("推荐任务的按钮名称和提示词都不能为空");
  const tpl = {
    ...(S.promptWb || {}),
    id: (S.promptWb && S.promptWb.id) || "",
    name: $("pwName").value.trim() || "未命名工作台",
    icon: $("pwIcon").value.trim() || "🧩",
    desc: $("pwDesc").value.trim(),
    welcome: $("pwWelcome").value.trim(),
    welcomeSub: $("pwWelcomeSub").value.trim(),
    quick: quick.map(({ _idx, ...x }) => x),
  };
  if (!tpl.id) tpl.id = (S.promptDetail && S.promptDetail.meta && S.promptDetail.meta.template_id) || "custom";
  return JSON.stringify(tpl, null, 2);
}

function renderPromptVersions(versions) {
  const list = $("promptVersionList");
  const count = $("promptVersionCount");
  count.textContent = versions.length;
  if (!versions.length) {
    list.innerHTML = `<div class="hint" style="padding:6px">还没有保存过版本；首次保存后会在这里留痕。</div>`;
    return;
  }
  list.innerHTML = versions.map((v, idx) => `<div class="prompt-version-row">
    <div><b>v${v.version}</b> <span>${esc(fmtTime(v.created_at))}${idx === 0 ? " · 当前生效" : ""}</span></div>
    ${idx === 0 ? '<span class="badge ok">当前</span>' : `<button class="btn small ghost" data-pversion="${v.version}" type="button">恢复</button>`}
  </div>`).join("");
}

async function savePromptDraft() {
  const item = S.promptDetail;
  if (!item || item.external_type === "agent") return;
  let content = "";
  try {
    content = item.kind === "workbench" ? collectPromptWorkbench() : $("promptContent").value.trim();
  } catch (e) {
    uiToast(e.message, "bad");
    return;
  }
  if (!content) {
    uiToast("提示词不能为空", "bad");
    return;
  }
  const btn = $("promptSaveBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const enabled = !$("promptEnabledWrap").hidden ? $("promptEnabled").checked : undefined;
    const res = await api("/api/admin/prompts/" + encodeURIComponent(item.key), {
      method: "PUT",
      body: JSON.stringify({ content, enabled }),
    });
    setPromptDirty(false);
    uiToast(`已生效，修订 #${res.revision}，下一条消息使用新提示词`);
    await loadPromptsPage();
    if (item.kind === "core" && S.tab === "prompts") setPromptDirty(false);
  } catch (e) {
    uiToast(e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function resetPromptDraft() {
  const item = S.promptDetail;
  if (!item || item.external) return;
  const ok = await confirmInline("恢复默认会写入默认内容并生成一个新版本，确定继续吗？", "恢复默认");
  if (!ok) return;
  try {
    const res = await api("/api/admin/prompts/" + encodeURIComponent(item.key) + "/reset", { method: "POST" });
    uiToast(`已恢复默认，修订 #${res.revision}`);
    await loadPromptsPage();
  } catch (e) { uiToast(e.message, "bad"); }
}

async function restorePromptVersion(version) {
  const item = S.promptDetail;
  if (!item) return;
  const ok = await confirmInline(`恢复 v${version} 会以该版本内容生成一个新版本，确定继续吗？`, "恢复");
  if (!ok) return;
  try {
    const res = await api(`/api/admin/prompts/${encodeURIComponent(item.key)}/restore/${version}`, { method: "POST" });
    uiToast(`已恢复到 v${version}，修订 #${res.revision}`);
    await loadPromptsPage();
  } catch (e) { uiToast(e.message, "bad"); }
}

async function previewPromptDraft() {
  try {
    const d = await api("/api/admin/prompts/preview", {
      method: "POST",
      body: JSON.stringify({
        skill_id: $("promptPvSkill").value,
        use_kb: $("promptPvKb").checked,
        use_library: $("promptPvLib").checked,
        use_memory: $("promptPvMem").checked,
        use_web: $("promptPvWeb").checked,
        output_format: $("promptPvFormat").value,
      }),
    });
    $("promptPreviewPanel").hidden = false;
    $("promptPreviewText").textContent = d.text || "没有可拼装的内容。";
    $("promptPreviewMeta").textContent = `${fmtInt(d.chars)} 字 · 约 ${fmtInt(d.tokens)} tokens · 修订 #${d.revision}`;
    $("promptPreviewPanel").scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch (e) { uiToast(e.message, "bad"); }
}

async function syncPromptPage() {
  try {
    await loadPromptsPage();
    uiToast("已刷新列表与修订号；保存本身已经即时生效");
  } catch (e) { uiToast(e.message, "bad"); }
}

function insertPromptQuickRow() {
  const rows = $("pwQuickList").querySelectorAll(".wb-quick-item").length;
  if (rows >= 8) { uiToast("推荐任务最多 8 条", "bad"); return; }
  const wrap = $("pwQuickList");
  if (!rows) wrap.innerHTML = "";
  wrap.insertAdjacentHTML("beforeend", promptQuickRow({ label: "", text: "", format: "" }, rows));
}

async function loadSkillsAdmin() {
  const d = await api("/api/admin/skills");
  S.skillAdmin = d.items || [];
  S.skillIcons = d.icons || S.skillIcons;
  const custom = S.skillAdmin.filter((x) => x.custom);
  const on = custom.filter((x) => x.enabled).length;
  $("skillAdminHint").textContent = `内置 ${S.skillAdmin.length - custom.length} 个 · 自定义 ${custom.length} 个（启用 ${on} 个）`;
  renderSkillAdminRows();
  fillSkillIconSelect();
}

function renderSkillAdminRows() {
  const box = $("skillAdminRows");
  if (!box) return;
  const items = S.skillAdmin || [];
  if (!items.length) {
    box.innerHTML = `<tr><td colspan="5" class="hint">还没有技能</td></tr>`;
    return;
  }
  box.innerHTML = items.map((s) => {
    const type = s.custom ? `<span class="badge cat">自定义</span>` : `<span class="badge off">内置 · 可覆盖</span>`;
    const state = s.enabled ? `<span class="badge good">已启用</span>` : `<span class="badge off">已停用</span>`;
    const actions = s.custom
      ? `<button class="btn small" data-skill-edit="${s.row_id}">编辑</button>
         <button class="btn small" data-skill-toggle="${s.row_id}" data-enabled="${s.enabled ? 1 : 0}">${s.enabled ? "停用" : "启用"}</button>
         <button class="btn small danger" data-skill-del="${s.row_id}">删除</button>`
      : `<span class="hint">在提示词中心调整</span>`;
    return `<tr>
      <td><b>${esc(s.name)}</b><div class="hint">${esc(s.prompt || "").slice(0, 90)}${(s.prompt || "").length > 90 ? "…" : ""}</div></td>
      <td>${type}</td>
      <td>${esc(s.hint || "—")}</td>
      <td>${state}</td>
      <td class="right">${actions}</td>
    </tr>`;
  }).join("");
}

function openSkillEditor(item) {
  S.skillEdit = (item && item.row_id) || 0;
  $("skillEditor").hidden = false;
  $("skillEditorTitle").textContent = S.skillEdit ? "编辑技能 · " + item.name : "新建技能";
  $("esName").value = item ? item.name : "";
  $("esHint").value = item ? (item.hint || "") : "";
  $("esPrompt").value = item ? (item.prompt || "") : "";
  $("esSort").value = String(item ? (item.sort || 0) : 0);
  $("esEnabled").checked = item ? !!item.enabled : true;
  fillSkillIconSelect();
  if (item && item.icon) $("esIcon").value = item.icon;
  $("skillEditor").scrollIntoView({ block: "start" });
  $("esName").focus();
}

function closeSkillEditor() {
  S.skillEdit = 0;
  $("skillEditor").hidden = true;
}

async function saveSkillAdmin() {
  const name = $("esName").value.trim();
  const prompt = $("esPrompt").value.trim();
  if (!name) { uiToast("技能名称不能为空", "bad"); return; }
  if (!prompt) { uiToast("提示词不能为空", "bad"); return; }
  const payload = {
    name,
    hint: $("esHint").value.trim(),
    icon: $("esIcon").value || "spark",
    prompt,
    enabled: $("esEnabled").checked,
    sort: Number($("esSort").value) || 0,
  };
  if (S.skillEdit) {
    await api(`/api/admin/skills/${S.skillEdit}`, { method: "PATCH", body: JSON.stringify(payload) });
    uiToast("技能已保存");
  } else {
    await api("/api/admin/skills", { method: "POST", body: JSON.stringify(payload) });
    uiToast("技能已创建，用户端技能菜单已更新");
  }
  closeSkillEditor();
  await loadSkillsAdmin();
}

async function toggleSkillAdmin(id, enabled) {
  await api(`/api/admin/skills/${id}`, { method: "PATCH", body: JSON.stringify({ enabled: !enabled }) });
  uiToast(enabled ? "技能已停用" : "技能已启用");
  await loadSkillsAdmin();
}

async function deleteSkillAdmin(id) {
  const item = (S.skillAdmin || []).find((x) => x.row_id === Number(id));
  if (!(await confirmInline(`删除技能「${(item && item.name) || id}」？删除后用户端立即不可见。`, "删除"))) return;
  await api(`/api/admin/skills/${id}`, { method: "DELETE" });
  uiToast("技能已删除");
  await loadSkillsAdmin();
}

/* ---------------------------------------------------------------- 审计日志 */
S.auditPage = 0;
S.auditLimit = 50;

async function loadAuditPage() {
  const q = $("faq").value.trim();
  const action = $("faAction").value.trim();
  const status = $("faStatus").value;
  const days = $("faDays").value;
  const params = new URLSearchParams({
    q, action, status, days: days || "0",
    limit: String(S.auditLimit), offset: String(S.auditPage * S.auditLimit),
  });
  const d = await api("/api/admin/audit?" + params.toString());
  const total = d.total || 0;
  $("auditHint").textContent = `共 ${fmtInt(total)} 条 · 当前第 ${S.auditPage + 1} 页 · 只读`;
  $("auditPageInfo").textContent = `${S.auditPage + 1} / ${Math.max(1, Math.ceil(total / S.auditLimit))}`;
  $("auditPrev").disabled = S.auditPage <= 0;
  $("auditNext").disabled = (S.auditPage + 1) * S.auditLimit >= total;
  const rows = d.items || [];
  const box = $("auditRows");
  if (!rows.length) {
    box.innerHTML = `<tr><td colspan="7" class="hint">没有匹配的操作记录</td></tr>`;
    return;
  }
  box.innerHTML = rows.map((r) => {
    const ok = r.status === "ok";
    const detail = String(r.detail || "");
    return `<tr>
      <td>${esc(fmtTime(r.ts))}</td>
      <td>${esc(r.username || "—")}<div class="hint">#${esc(r.user_id ?? "—")}</div></td>
      <td><b>${esc(r.action)}</b></td>
      <td>${esc(r.target || "—")}</td>
      <td title="${esc(detail)}">${esc(detail.length > 80 ? detail.slice(0, 80) + "…" : detail || "—")}</td>
      <td>${esc(r.ip || "—")}</td>
      <td>${ok ? `<span class="badge good">成功</span>` : `<span class="badge bad">${esc(r.status || "失败")}</span>`}</td>
    </tr>`;
  }).join("");
}

document.addEventListener("click", async (ev) => {
  const edit = ev.target.closest("[data-skill-edit]");
  if (edit) {
    const item = (S.skillAdmin || []).find((x) => x.row_id === Number(edit.dataset.skillEdit));
    if (item) openSkillEditor(item);
    return;
  }
  const toggle = ev.target.closest("[data-skill-toggle]");
  if (toggle) {
    await toggleSkillAdmin(toggle.dataset.skillToggle, toggle.dataset.enabled === "1");
    return;
  }
  const del = ev.target.closest("[data-skill-del]");
  if (del) {
    await deleteSkillAdmin(del.dataset.skillDel);
    return;
  }
});

if ($("newSkillBtn")) {
  $("newSkillBtn").addEventListener("click", () => openSkillEditor(null));
  $("saveSkillBtn").addEventListener("click", () => saveSkillAdmin().catch((e) => uiToast(e.message || "保存失败", "bad")));
  $("cancelSkillBtn").addEventListener("click", closeSkillEditor);
  $("auditSearchBtn").addEventListener("click", () => { S.auditPage = 0; loadAuditPage().catch((e) => uiToast(e.message || "查询失败", "bad")); });
  $("auditPrev").addEventListener("click", () => { if (S.auditPage > 0) { S.auditPage -= 1; loadAuditPage().catch(() => {}); } });
  $("auditNext").addEventListener("click", () => { S.auditPage += 1; loadAuditPage().catch(() => {}); });
}

/* ---------------------------------------------------------------- 协作套件 */
S.agentEditId = null;
S.squadId = null;

function agentVisibilityText(v) {
  return { public: "公开", squad: "仅小队", private: "私有" }[v] || v || "公开";
}

async function loadAgentsPage() {
  const d = await api("/api/admin/agents");
  const rows = d.items || [];
  const box = $("agentRows");
  box.innerHTML = rows.length ? rows.map((a) => `<tr>
    <td><b>${esc(a.avatar || "🤖")} ${esc(a.name)}</b><div class="hint">#${esc(a.id)} · ${esc(a.owner_name || "—")}</div></td>
    <td>${esc(a.description || "—")}</td>
    <td>${esc(a.model || "沿用当前模型")}</td>
    <td><span class="badge">${esc(agentVisibilityText(a.visibility))}</span></td>
    <td>${a.enabled ? '<span class="badge good">启用</span>' : '<span class="badge bad">停用</span>'}</td>
    <td class="right"><button class="btn small" data-agent-edit="${a.id}">编辑</button>
      <button class="btn small danger" data-agent-del="${a.id}">删除</button></td>
  </tr>`).join("") : '<tr><td colspan="6" class="hint">还没有智能体，先建一个角色</td></tr>';
}

function resetAgentEditor() {
  S.agentEditId = null;
  $("agentEditorTitle").textContent = "新建智能体";
  ["agName", "agModel", "agDesc", "agPrompt"].forEach((id) => { $(id).value = ""; });
  $("agAvatar").value = "🤖";
  $("agVisibility").value = "public";
  $("agSort").value = "0";
  $("agEnabled").checked = true;
}

function editAgent(a) {
  S.agentEditId = a.id;
  $("agentEditorTitle").textContent = `编辑智能体 · ${a.name}`;
  $("agName").value = a.name || "";
  $("agAvatar").value = a.avatar || "🤖";
  $("agModel").value = a.model || "";
  $("agVisibility").value = a.visibility || "public";
  $("agDesc").value = a.description || "";
  $("agPrompt").value = a.system_prompt || "";
  $("agEnabled").checked = !!a.enabled;
  $("agSort").value = a.sort || 0;
}

async function saveAgent() {
  const body = {
    name: $("agName").value.trim(),
    avatar: $("agAvatar").value.trim(),
    description: $("agDesc").value.trim(),
    system_prompt: $("agPrompt").value.trim(),
    model: $("agModel").value.trim(),
    visibility: $("agVisibility").value,
    enabled: $("agEnabled").checked,
    sort: Number($("agSort").value || 0),
  };
  if (!body.name) throw new Error("智能体名称不能为空");
  if (S.agentEditId) {
    await api(`/api/admin/agents/${S.agentEditId}`, { method: "PATCH", body: JSON.stringify(body) });
    uiToast("智能体已更新");
  } else {
    await api("/api/admin/agents", { method: "POST", body: JSON.stringify(body) });
    uiToast("智能体已创建");
    resetAgentEditor();
  }
  await loadAgentsPage();
}

async function deleteAgent(id) {
  if (!(await confirmInline(`删除智能体 #${id}？已绑定的小队会同时解除。`, "删除"))) return;
  await api(`/api/admin/agents/${id}`, { method: "DELETE" });
  uiToast("智能体已删除");
  await loadAgentsPage();
}

async function loadPartnersPage() {
  const q = encodeURIComponent($("partnerSearch").value.trim());
  const d = await api(`/api/admin/partners?q=${q}`);
  const rows = d.items || [];
  $("partnerRows").innerHTML = rows.length ? rows.map((p) => `<tr>
    <td><b>${esc(p.username)}</b><div class="hint">#${esc(p.id)} · ${esc(p.role === "admin" ? "管理员" : "普通用户")}</div></td>
    <td>${esc(p.group_name || "未分组")}</td>
    <td>${esc(p.admin_role_name || "—")}</td>
    <td>${esc(p.squad_count || 0)} 个</td>
    <td>${p.last_login_at ? esc(fmtTime(p.last_login_at)) : "—"}</td>
    <td>${p.disabled ? '<span class="badge bad">停用</span>' : '<span class="badge good">正常</span>'}</td>
  </tr>`).join("") : '<tr><td colspan="6" class="hint">没有匹配的成员</td></tr>';
}

async function loadSquadsPage() {
  const d = await api("/api/admin/squads");
  const rows = d.items || [];
  $("squadRows").innerHTML = rows.length ? rows.map((s) => `<tr>
    <td><b>${esc(s.name)}</b><div class="hint">${esc(s.description || "")}</div></td>
    <td>${esc(s.owner_name || "—")}</td>
    <td>${s.member_count || 0}</td>
    <td>${s.agent_count || 0}</td>
    <td>${s.conversation_count || 0}</td>
    <td class="right"><button class="btn small" data-squad-open="${s.id}">管理</button>
      <button class="btn small danger" data-squad-del="${s.id}">删除</button></td>
  </tr>`).join("") : '<tr><td colspan="6" class="hint">还没有小队</td></tr>';
}

async function openSquad(id) {
  S.squadId = Number(id);
  const s = await api(`/api/admin/squads/${id}`);
  $("squadDetail").hidden = false;
  $("sdTitle").textContent = `小队 · ${s.name}`;
  $("sdMeta").textContent = `${s.description || "没有描述"} · 所有者 ${s.owner_name || "—"}`;
  $("sdMemberRows").innerHTML = (s.members || []).map((m) => `<tr>
    <td>${esc(m.username)}</td><td>${esc(m.group_name || "未分组")}</td>
    <td>${m.role === "owner" ? '<span class="badge good">所有者</span>' : '<span class="badge">成员</span>'}</td>
    <td class="right">${m.role === "owner" ? "—" : `<button class="btn small danger" data-squad-member-del="${m.user_id}">移除</button>`}</td>
  </tr>`).join("") || '<tr><td colspan="4" class="hint">没有成员</td></tr>';
  $("sdAgentRows").innerHTML = (s.agents || []).map((a) => `<tr>
    <td>${esc(a.avatar || "")} ${esc(a.name)}</td><td>${esc(agentVisibilityText(a.visibility))}</td>
    <td class="right"><button class="btn small danger" data-squad-agent-del="${a.id}">解绑</button></td>
  </tr>`).join("") || '<tr><td colspan="3" class="hint">没有绑定智能体</td></tr>';
  $("sdConvRows").innerHTML = (s.conversations || []).map((c) => `<tr>
    <td>${esc(c.title || "未命名对话")}</td><td>${esc(c.shared_by_name || "—")}</td><td>${esc(fmtTime(c.created_at))}</td>
  </tr>`).join("") || '<tr><td colspan="3" class="hint">还没有共享对话</td></tr>';
}

async function createSquad() {
  const body = { name: $("sqName").value.trim(), description: $("sqDesc").value.trim() };
  if (!body.name) throw new Error("小队名称不能为空");
  await api("/api/admin/squads", { method: "POST", body: JSON.stringify(body) });
  $("sqName").value = ""; $("sqDesc").value = "";
  uiToast("小队已创建");
  await loadSquadsPage();
}

async function addSquadMember() {
  const body = { username: $("sdMemberName").value.trim(), role: $("sdMemberRole").value };
  if (!body.username) throw new Error("请输入用户名");
  await api(`/api/admin/squads/${S.squadId}/members`, { method: "POST", body: JSON.stringify(body) });
  $("sdMemberName").value = "";
  uiToast("成员已加入");
  await openSquad(S.squadId);
  await loadSquadsPage();
}

async function addSquadAgent() {
  const agentId = Number($("sdAgentId").value || 0);
  if (!agentId) throw new Error("请输入智能体 ID");
  await api(`/api/admin/squads/${S.squadId}/agents`, { method: "POST", body: JSON.stringify({ agent_id: agentId }) });
  $("sdAgentId").value = "";
  uiToast("智能体已绑定");
  await openSquad(S.squadId);
  await loadSquadsPage();
}

async function loadAnnouncementsPage() {
  const d = await api("/api/admin/announcements");
  const rows = d.items || [];
  const levelText = { info: "通知", warning: "提醒", important: "重要" };
  $("announcementRows").innerHTML = rows.length ? rows.map((a) => `<tr>
    <td><b>${esc(a.title)}</b><div class="hint">${esc(String(a.content || "").slice(0, 60))}</div></td>
    <td>${esc(levelText[a.level] || a.level)}</td>
    <td>${a.pinned ? "是" : "否"}</td>
    <td>${a.enabled ? '<span class="badge good">启用</span>' : '<span class="badge bad">停用</span>'}</td>
    <td>${esc(a.creator_name || "—")}</td><td>${esc(fmtTime(a.created_at))}</td>
    <td class="right"><button class="btn small" data-ann-toggle="${a.id}" data-enabled="${a.enabled ? 1 : 0}">${a.enabled ? "停用" : "启用"}</button>
      <button class="btn small danger" data-ann-del="${a.id}">删除</button></td>
  </tr>`).join("") : '<tr><td colspan="7" class="hint">还没有公告</td></tr>';
}

async function createAnnouncement() {
  const body = {
    title: $("anTitle").value.trim(), content: $("anContent").value.trim(),
    level: $("anLevel").value, pinned: $("anPinned").checked, enabled: $("anEnabled").checked,
  };
  if (!body.title || !body.content) throw new Error("标题和正文都不能为空");
  await api("/api/admin/announcements", { method: "POST", body: JSON.stringify(body) });
  $("anTitle").value = ""; $("anContent").value = ""; $("anPinned").checked = false;
  uiToast("公告已发布");
  await loadAnnouncementsPage();
}

async function toggleAnnouncement(id, enabled) {
  await api(`/api/admin/announcements/${id}`, { method: "PATCH", body: JSON.stringify({ enabled: !enabled }) });
  await loadAnnouncementsPage();
}

async function deleteAnnouncement(id) {
  if (!(await confirmInline("删除这条公告？删除后用户端立即消失。", "删除"))) return;
  await api(`/api/admin/announcements/${id}`, { method: "DELETE" });
  uiToast("公告已删除");
  await loadAnnouncementsPage();
}

async function loadTicketsPage() {
  const params = new URLSearchParams({
    status: $("tkStatus").value, priority: $("tkPriority").value, q: $("tkSearch").value.trim(),
  });
  const d = await api("/api/admin/tickets?" + params.toString());
  const stats = d.stats || {};
  $("ticketStats").innerHTML = [
    ["待处理", stats.open || 0], ["处理中", stats.processing || 0],
    ["已解决", stats.resolved || 0], ["已关闭", stats.closed || 0],
  ].map(([k, v]) => `<div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");
  const rows = d.items || [];
  $("ticketRows").innerHTML = rows.length ? rows.map((t) => `<tr data-ticket-open="${t.id}" style="cursor:pointer">
    <td>#${esc(t.id)}</td><td><b>${esc(t.title)}</b></td><td>${esc(t.username || "—")}</td>
    <td>${esc(t.category)}</td><td>${esc(t.priority === "high" ? "高" : t.priority === "low" ? "低" : "普通")}</td>
    <td>${esc({ open: "待处理", processing: "处理中", resolved: "已解决", closed: "已关闭" }[t.status] || t.status)}</td>
    <td>${esc(t.assignee_name || "—")}</td><td>${esc(fmtTime(t.updated_at))}</td>
  </tr>`).join("") : '<tr><td colspan="8" class="hint">没有匹配的工单</td></tr>';
}

async function openTicket(id) {
  const t = await api(`/api/admin/tickets/${id}`);
  S.ticketId = t.id;
  $("ticketDetail").hidden = false;
  $("tdTitle").textContent = `工单 #${t.id} · ${t.title}`;
  $("tdMeta").textContent = `${t.username || "—"} 提交 · ${t.category} · ${t.priority} · ${t.status}`;
  $("tdMessages").innerHTML = (t.messages || []).map((m) => `<div class="detail-row">
    <b>${esc(m.username || "用户")}${m.role === "staff" ? " · 管理员" : ""}</b>
    <span class="hint">${esc(fmtTime(m.created_at))}</span>
    <div>${esc(m.content)}</div>
  </div>`).join("");
  $("tdStatus").value = t.status;
  $("tdAssignee").value = t.assignee_id || "";
  $("tdReply").value = "";
  $("ticketDetail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function saveTicket() {
  const id = S.ticketId;
  if (!id) return;
  const patch = { status: $("tdStatus").value, priority: "normal" };
  const assignee = Number($("tdAssignee").value || 0);
  if (assignee) patch.assignee_id = assignee;
  await api(`/api/admin/tickets/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
  const reply = $("tdReply").value.trim();
  if (reply) {
    await api(`/api/admin/tickets/${id}/reply`, { method: "POST", body: JSON.stringify({ content: reply }) });
  }
  uiToast(reply ? "状态已保存，回复已发送" : "状态已保存");
  await loadTicketsPage();
  await openTicket(id);
}

async function loadConvSharesPage() {
  const d = await api("/api/admin/shares");
  const rows = d.items || [];
  $("convShareRows").innerHTML = rows.length ? rows.map((s) => {
    const live = s.enabled && (!s.expires_at || s.expires_at > Date.now() / 1000);
    return `<tr>
      <td><b>${esc(s.title || "未命名对话")}</b><div class="hint">#${esc(s.id)} · ${esc(s.token).slice(0, 10)}…</div></td>
      <td>${esc(s.owner_name || "—")}</td>
      <td>${esc(s.visibility === "squad" ? "仅小队" : "公开")}</td>
      <td>${esc(s.message_count || 0)}</td><td>${esc(s.view_count || 0)}</td>
      <td>${s.expires_at ? esc(fmtTime(s.expires_at)) : "永久"}</td>
      <td>${live ? '<span class="badge good">有效</span>' : '<span class="badge bad">失效</span>'}</td>
      <td class="right"><a class="btn small" href="/share/${encodeURIComponent(s.token)}" target="_blank" rel="noreferrer">打开</a>
        <button class="btn small danger" data-share-del="${s.id}">撤销</button></td>
    </tr>`;
  }).join("") : '<tr><td colspan="8" class="hint">还没有对话分享</td></tr>';
}

document.addEventListener("click", async (ev) => {
  const agentEdit = ev.target.closest("[data-agent-edit]");
  if (agentEdit) {
    const d = await api("/api/admin/agents");
    const item = (d.items || []).find((a) => a.id === Number(agentEdit.dataset.agentEdit));
    if (item) editAgent(item);
    return;
  }
  const agentDel = ev.target.closest("[data-agent-del]");
  if (agentDel) { await deleteAgent(agentDel.dataset.agentDel); return; }
  const squadOpen = ev.target.closest("[data-squad-open]");
  if (squadOpen) { await openSquad(squadOpen.dataset.squadOpen); return; }
  const squadDel = ev.target.closest("[data-squad-del]");
  if (squadDel) {
    if (await confirmInline("删除这个小队？成员关系和共享记录会一并删除。", "删除")) {
      await api(`/api/admin/squads/${squadDel.dataset.squadDel}`, { method: "DELETE" });
      uiToast("小队已删除");
      await loadSquadsPage();
      $("squadDetail").hidden = true;
    }
    return;
  }
  const memberDel = ev.target.closest("[data-squad-member-del]");
  if (memberDel) {
    await api(`/api/admin/squads/${S.squadId}/members/${memberDel.dataset.squadMemberDel}`, { method: "DELETE" });
    await openSquad(S.squadId); await loadSquadsPage(); return;
  }
  const squadAgentDel = ev.target.closest("[data-squad-agent-del]");
  if (squadAgentDel) {
    await api(`/api/admin/squads/${S.squadId}/agents/${squadAgentDel.dataset.squadAgentDel}`, { method: "DELETE" });
    await openSquad(S.squadId); await loadSquadsPage(); return;
  }
  const annToggle = ev.target.closest("[data-ann-toggle]");
  if (annToggle) { await toggleAnnouncement(annToggle.dataset.annToggle, annToggle.dataset.enabled === "1"); return; }
  const annDel = ev.target.closest("[data-ann-del]");
  if (annDel) { await deleteAnnouncement(annDel.dataset.annDel); return; }
  const ticketRow = ev.target.closest("[data-ticket-open]");
  if (ticketRow) { await openTicket(ticketRow.dataset.ticketOpen); return; }
  const shareDel = ev.target.closest("[data-share-del]");
  if (shareDel) {
    if (await confirmInline("撤销这个分享？链接会立即失效。", "撤销")) {
      await api(`/api/admin/shares/${shareDel.dataset.shareDel}`, { method: "DELETE" });
      uiToast("分享已撤销");
      await loadConvSharesPage();
    }
    return;
  }
});

if ($("refreshAgents")) {
  $("refreshAgents").addEventListener("click", () => loadAgentsPage().catch((e) => uiToast(e.message, "bad")));
  $("saveAgent").addEventListener("click", () => saveAgent().catch((e) => uiToast(e.message, "bad")));
  $("resetAgent").addEventListener("click", resetAgentEditor);
  $("refreshPartners").addEventListener("click", () => loadPartnersPage().catch((e) => uiToast(e.message, "bad")));
  $("refreshSquads").addEventListener("click", () => loadSquadsPage().catch((e) => uiToast(e.message, "bad")));
  $("createSquad").addEventListener("click", () => createSquad().catch((e) => uiToast(e.message, "bad")));
  $("closeSquad").addEventListener("click", () => { $("squadDetail").hidden = true; });
  $("addSquadMember").addEventListener("click", () => addSquadMember().catch((e) => uiToast(e.message, "bad")));
  $("addSquadAgent").addEventListener("click", () => addSquadAgent().catch((e) => uiToast(e.message, "bad")));
  $("refreshAnnouncements").addEventListener("click", () => loadAnnouncementsPage().catch((e) => uiToast(e.message, "bad")));
  $("createAnnouncement").addEventListener("click", () => createAnnouncement().catch((e) => uiToast(e.message, "bad")));
  $("refreshTickets").addEventListener("click", () => loadTicketsPage().catch((e) => uiToast(e.message, "bad")));
  $("closeTicket").addEventListener("click", () => { $("ticketDetail").hidden = true; });
  $("saveTicket").addEventListener("click", () => saveTicket().catch((e) => uiToast(e.message, "bad")));
  $("refreshConvShares").addEventListener("click", () => loadConvSharesPage().catch((e) => uiToast(e.message, "bad")));
}

/* ---------------------------------------------------------------- 联网检索 */
function renderWebsearch(cfg) {
  S.websearch = cfg || {};
  const on = !!cfg.enabled;
  $("websearchEnabled").checked = on;
  $("websearchSources").value = cfg.max_sources || 5;
  $("websearchPages").value = cfg.max_pages ?? 2;
  const dot = $("websearchDot");
  if (dot) dot.className = "dot " + (on ? "on" : "");
  $("websearchState").textContent = on ? "联网已开启" : "联网已关闭";
  $("websearchHint").textContent = `当前：最多 ${cfg.max_sources || 5} 条结果，抓取前 ${cfg.max_pages ?? 2} 篇正文；缓存 ${cfg.cache_entries || 0} 条，${Math.round((cfg.cache_ttl || 600) / 60)} 分钟过期。`;
}

async function loadWebsearch() {
  const cfg = await api("/api/system/websearch");
  renderWebsearch(cfg);
}

async function saveWebsearch() {
  const body = {
    enabled: $("websearchEnabled").checked,
    max_sources: Number($("websearchSources").value || 5),
    max_pages: Number($("websearchPages").value || 0),
  };
  const cfg = await api("/api/system/websearch", { method: "PUT", body: JSON.stringify(body) });
  renderWebsearch(cfg);
  uiToast("联网设置已保存");
}

function renderWebsearchResults(data) {
  const box = $("websearchResults");
  box.hidden = false;
  const sources = data.sources || [];
  if (!sources.length) {
    box.innerHTML = `<div class="ws-result-empty">没有搜到可用结果。${esc(data.error || "可以换个更具体的检索词再试。")}</div>`;
    return;
  }
  box.innerHTML = sources.map((s, i) => {
    const url = String(s.url || "");
    const href = /^https?:\/\//i.test(url) ? esc(url) : "";
    return `<div class="ws-result">
    <a href="${href}" target="_blank" rel="noreferrer">${i + 1}. ${esc(s.title || url || "未命名来源")}</a>
    ${href ? `<a class="url" href="${href}" target="_blank" rel="noreferrer">${esc(url)}</a>` : `<div class="url">${esc(url)}</div>`}
    ${s.snippet ? `<div class="snippet">${esc(s.snippet)}</div>` : ""}
  </div>`;
  }).join("");
}

async function testWebsearch() {
  const query = $("websearchQuery").value.trim();
  if (query.length < 2) throw new Error("请输入至少 2 个字的检索词");
  $("websearchTestBtn").disabled = true;
  $("websearchTestHint").textContent = "正在检索并抓取网页正文…";
  $("websearchResults").hidden = true;
  try {
    const data = await api("/api/system/websearch/test", {
      method: "POST", body: JSON.stringify({ query, max_sources: Number($("websearchSources").value || 5),
        max_pages: Number($("websearchPages").value || 0) }),
    });
    renderWebsearchResults(data);
    $("websearchTestHint").textContent = data.ok
      ? `完成：${data.sources.length} 条来源 · ${data.ms}ms · 检索词「${data.query}」`
      : `没有结果：${data.error || "未知原因"} · ${data.ms}ms`;
  } finally {
    $("websearchTestBtn").disabled = false;
  }
}

if ($("saveWebsearchBtn")) {
  $("saveWebsearchBtn").addEventListener("click", () => saveWebsearch().catch((e) => uiToast(e.message || "保存失败", "bad")));
  $("clearWebsearchCacheBtn").addEventListener("click", async () => {
    const r = await api("/api/system/websearch/cache/clear", { method: "POST" });
    uiToast(`缓存已清空（${r.cache_entries || 0} 条剩余）`);
    await loadWebsearch();
  });
  $("websearchTestBtn").addEventListener("click", () => testWebsearch().catch((e) => {
    $("websearchTestHint").textContent = e.message || "测试失败";
    uiToast(e.message || "测试失败", "bad");
  }));
  $("websearchQuery").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); testWebsearch().catch((e) => uiToast(e.message || "测试失败", "bad")); }
  });
}

/* ---------------------------------------------------------------- 附件解析 */
function parseStatusBadge(item) {
  if (item.chars > 0) return `<span class="badge good">已解析</span>`;
  if (item.parse_error && !String(item.parse_error).startsWith("未提取到正文")) return `<span class="badge bad">报错</span>`;
  return `<span class="badge warn">待解析</span>`;
}

function parseTypeLabel(item) {
  const suffix = String(item.suffix || "").toUpperCase();
  const map = { image: "图片", document: "文档", text: "文本" };
  return suffix || map[item.kind] || "文件";
}

function renderParseStats(stats) {
  S.parseStats = stats || {};
  $("parseStatTotal").textContent = fmtInt(stats.total || 0);
  $("parseStatParsed").textContent = fmtInt(stats.parsed || 0);
  $("parseStatEmpty").textContent = fmtInt(stats.empty || 0);
  $("parseStatErrors").textContent = fmtInt(stats.errors || 0);
  const emptyBtn = $("parseEmptyBtn");
  if (emptyBtn) emptyBtn.textContent = (stats.empty || 0) > 50 ? "重新解析空正文（前 50）" : "重新解析空正文";
  if (emptyBtn) emptyBtn.disabled = S.parseBusy || !(stats.empty || 0);
}

function renderParseEngine(engine) {
  const ok = !!(engine && engine.installed);
  const dot = $("parseEngineDot");
  if (dot) dot.className = "dot " + (ok ? "on" : "warn");
  $("parseEngineState").textContent = ok ? `${engine.engine} 已就绪` : `${engine.engine || "OCR"} 未安装`;
  $("parseEngineHint").textContent = ok
    ? `引擎 ${engine.engine}；扫描 PDF 最多识别 ${engine.pdf_pages} 页，文档内图片最多 ${engine.doc_images} 张；单文件上限 ${dbFmtBytes(engine.max_bytes)}，正文最多 ${fmtInt(engine.max_chars)} 字。图片格式：${(engine.images || []).join(" / ")}。`
    : "未检测到 RapidOCR。图片和扫描 PDF 会解析失败；可先安装 rapidocr_onnxruntime，再回到本页重试。";
}

function renderParseRows() {
  const rows = S.parseItems || [];
  const box = $("parseRows");
  if (!rows.length) {
    box.innerHTML = '<tr><td colspan="7" class="hint" style="text-align:center;padding:28px">没有匹配的附件</td></tr>';
    return;
  }
  box.innerHTML = rows.map((r) => {
    const timeText = r.parsed_at ? fmtTime(r.parsed_at) : (r.chars ? "历史解析记录" : "尚未解析");
    const cost = r.parse_ms ? fmtMs(r.parse_ms) : "";
    const brief = r.chars ? `${fmtInt(r.chars)} 字 · ` : "";
    const stateHint = r.parse_error ? r.parse_error : (r.chars ? `${fmtInt(r.chars)} 字${cost ? " · " + cost : ""}` : "原文件可重新跑 OCR");
    return `<tr>
      <td><input type="checkbox" class="parse-check" data-parse-id="${r.id}"></td>
      <td class="parse-file"><div class="name" title="${esc(r.name)}">${esc(r.name)}</div>
        <div class="sub">#${r.id} · ${esc(r.username || "未知用户")}${r.created_at ? " · " + esc(fmtTime(r.created_at)) : ""}</div></td>
      <td><span class="badge">${esc(parseTypeLabel(r))}</span></td>
      <td>${esc(dbFmtBytes(r.size))}</td>
      <td>${r.chars ? fmtInt(r.chars) + " 字" : "—"}</td>
      <td><div class="parse-state">${parseStatusBadge(r)}<small title="${esc(stateHint)}">${esc(brief)}${esc(timeText)}${cost && !r.parse_error ? " · " + cost : ""}</small></div></td>
      <td><div class="parse-actions">
        <button class="btn small" data-parse-view="${r.id}">查看</button>
        <button class="btn small" data-parse-run="${r.id}">重新解析</button>
      </div></td>
    </tr>`;
  }).join("");
}

async function loadParsingPage(page = 1) {
  const q = $("parseQuery").value.trim();
  const status = $("parseStatus").value;
  const data = await api(`/api/admin/uploads?page=${page}&size=20&q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
  S.parsePage = page;
  S.parseTotal = data.total || 0;
  S.parseItems = data.items || [];
  renderParseStats(data.stats || {});
  renderParseEngine(data.engine || {});
  renderParseRows();
  const pages = Math.max(1, Math.ceil(S.parseTotal / 20));
  $("parsePageHint").textContent = `共 ${fmtInt(S.parseTotal)} 个附件 · 第 ${page}/${pages} 页`;
  $("parsePrev").disabled = page <= 1;
  $("parseNext").disabled = page >= pages;
  $("parseSelectAll").checked = false;
  updateParseSelection();
}

function updateParseSelection() {
  const checked = [...document.querySelectorAll(".parse-check:checked")].length;
  const btn = $("parseSelectedBtn");
  btn.textContent = checked ? `解析选中（${checked}）` : "解析选中";
  btn.disabled = S.parseBusy || checked === 0;
}

function setParseBusy(busy) {
  S.parseBusy = !!busy;
  ["parseEmptyBtn", "parseSelectedBtn", "parseRefreshBtn", "parseSearchBtn"].forEach((id) => {
    if ($(id)) $(id).disabled = busy;
  });
  if (!busy) renderParseStats(S.parseStats);
}

async function pollParseJob() {
  if (!S.parseJobId) {
    if (S.parseJobTimer) { clearInterval(S.parseJobTimer); S.parseJobTimer = null; }
    return;
  }
  let data;
  try {
    data = await api(`/api/admin/uploads/jobs/${encodeURIComponent(S.parseJobId)}`);
  } catch (e) {
    setParseBusy(false);
    $("parseProgressText").textContent = e.message || "任务状态读取失败";
    return;
  }
  const pct = data.total ? Math.round(data.done / data.total * 100) : 0;
  $("parseBar").style.width = pct + "%";
  if (data.status === "running") {
    $("parseProgressText").textContent = `正在解析 ${data.done}/${data.total} · 当前：${data.current || "准备中"} · 已成功 ${data.ok}，空正文 ${data.empty}，失败 ${data.failed}`;
    return;
  }
  clearInterval(S.parseJobTimer);
  S.parseJobTimer = null;
  setParseBusy(false);
  const cost = data.elapsed_ms >= 1000 ? (data.elapsed_ms / 1000).toFixed(1) + "s" : data.elapsed_ms + "ms";
  $("parseProgressText").textContent = `完成 ${data.total} 个 · 成功 ${data.ok} · 空正文 ${data.empty} · 失败 ${data.failed} · 耗时 ${cost}${data.error ? " · " + data.error : ""}`;
  $("parseProgressText").className = "progress-text " + (data.failed ? "bad" : "good");
  S.parseJobId = "";
  await loadParsingPage(S.parsePage || 1);
}

async function startParseJob(ids, onlyEmpty) {
  const body = { ids: ids || [], only_empty: !!onlyEmpty, limit: 50 };
  setParseBusy(true);
  $("parseProgress").hidden = false;
  $("parseProgressText").className = "progress-text";
  $("parseProgressText").textContent = "正在创建后台解析任务…";
  $("parseBar").style.width = "0%";
  try {
    const job = await api("/api/admin/uploads/reparse", { method: "POST", body: JSON.stringify(body) });
    S.parseJobId = job.id;
    await pollParseJob();
    if (S.parseJobId) {
      if (S.parseJobTimer) clearInterval(S.parseJobTimer);
      S.parseJobTimer = setInterval(() => pollParseJob().catch(() => {}), 1200);
    }
  } catch (e) {
    setParseBusy(false);
    $("parseProgressText").textContent = e.message || "任务创建失败";
    $("parseProgressText").className = "progress-text bad";
    throw e;
  }
}

async function showParsePreview(id) {
  const data = await api(`/api/admin/uploads/${id}/text`);
  S.parsePreviewId = data.id;
  S.parsePreviewName = data.name;
  $("parsePreviewPanel").hidden = false;
  $("parsePreviewName").textContent = data.name || `附件 #${data.id}`;
  const parsedHint = data.parsed_at ? fmtTime(data.parsed_at) : (data.chars ? "历史解析记录" : "尚未解析");
  $("parsePreviewMeta").textContent = `${parseTypeLabel({ suffix: (data.name || "").split(".").pop(), kind: data.kind })} · ${fmtInt(data.chars)} 字 · ${data.parse_ms ? fmtMs(data.parse_ms) : "未记录耗时"} · ${parsedHint}${data.parse_error ? " · " + data.parse_error : ""}`;
  $("parsePreviewText").textContent = data.text || "（正文为空，可点「重新解析」重跑 OCR 或文档提取。）";
  $("parsePreviewPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function downloadParseFile(id, name) {
  const r = await fetch(`/api/admin/uploads/${id}/file`, { headers: token() ? { Authorization: "Bearer " + token() } : {} });
  if (!r.ok) throw new Error("下载失败，原文件可能已丢失");
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name || `attachment-${id}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

if ($("parseRefreshBtn")) {
  $("parseRefreshBtn").addEventListener("click", () => loadParsingPage(S.parsePage || 1).catch((e) => uiToast(e.message, "bad")));
  $("parseSearchBtn").addEventListener("click", () => loadParsingPage(1).catch((e) => uiToast(e.message, "bad")));
  $("parseStatus").addEventListener("change", () => loadParsingPage(1).catch((e) => uiToast(e.message, "bad")));
  $("parseQuery").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); loadParsingPage(1).catch((e) => uiToast(e.message, "bad")); }
  });
  $("parsePrev").addEventListener("click", () => { if (S.parsePage > 1) loadParsingPage(S.parsePage - 1).catch(() => {}); });
  $("parseNext").addEventListener("click", () => loadParsingPage(S.parsePage + 1).catch(() => {}));
  $("parseSelectAll").addEventListener("change", (ev) => {
    document.querySelectorAll(".parse-check").forEach((x) => { x.checked = ev.target.checked; });
    updateParseSelection();
  });
  $("parseSelectedBtn").addEventListener("click", () => {
    const ids = [...document.querySelectorAll(".parse-check:checked")].map((x) => Number(x.dataset.parseId));
    if (!ids.length) { uiToast("先勾选要解析的附件", "bad"); return; }
    startParseJob(ids, false).catch((e) => uiToast(e.message || "解析失败", "bad"));
  });
  $("parseEmptyBtn").addEventListener("click", async () => {
    const n = S.parseStats.empty || 0;
    if (!n) { uiToast("当前没有正文为空的附件"); return; }
    if (!(await confirmInline(`重新解析 ${Math.min(n, 50)} 个正文为空的附件？扫描件会重新跑 OCR，可能需要几分钟。`, "开始解析"))) return;
    startParseJob([], true).catch((e) => uiToast(e.message || "解析失败", "bad"));
  });
  $("parsePreviewClose").addEventListener("click", () => { $("parsePreviewPanel").hidden = true; });
  $("parsePreviewDownload").addEventListener("click", () => {
    downloadParseFile(S.parsePreviewId, S.parsePreviewName).catch((e) => uiToast(e.message || "下载失败", "bad"));
  });
}

document.addEventListener("change", (ev) => {
  if (ev.target.classList && ev.target.classList.contains("parse-check")) updateParseSelection();
});
document.addEventListener("click", async (ev) => {
  const view = ev.target.closest("[data-parse-view]");
  if (view) { await showParsePreview(Number(view.dataset.parseView)).catch((e) => uiToast(e.message || "读取失败", "bad")); return; }
  const run = ev.target.closest("[data-parse-run]");
  if (run) { startParseJob([Number(run.dataset.parseRun)], false).catch((e) => uiToast(e.message || "解析失败", "bad")); return; }
});
document.addEventListener("input", (ev) => {
  const id = ev.target && ev.target.id;
  if (!BRAND_PREVIEW_IDS.has(id)) return;
  if (id === "brandPrimaryText") {
    const text = ev.target.value.trim();
    if (!BRAND_COLOR_RE.test(text)) return;
    $("brandPrimary").value = brandColorValue(text);
  }
  if (id === "brandPrimary") $("brandPrimaryText").value = ev.target.value;
  $("orgSaveHint").textContent = "有未保存修改";
  updateBrandPreviewFromForm();
});

document.addEventListener("change", async (ev) => {
  if (ev.target.id !== "brandLogoFile") return;
  const file = ev.target.files && ev.target.files[0];
  if (!file) return;
  try { await uploadBrandLogo(file); }
  catch (e) {
    $("brandLogoHint").textContent = "上传失败：" + (e.message || "请重试");
    uiToast(e.message || "Logo 上传失败", "bad");
  }
});

/* ---------------- 提示词中心交互 ---------------- */
document.addEventListener("click", (ev) => {
  const jump = ev.target.closest("[data-prompt-jump]");
  if (jump) {
    const key = jump.dataset.promptJump;
    if (!promptAssetByKey(key)) { uiToast("这个环节没有独立提示词", "info"); return; }
    selectPrompt(key).catch((e) => uiToast(e.message || "打开失败", "bad"));
    return;
  }
  const filter = ev.target.closest("[data-pfilter]");
  if (filter) {
    S.promptFilter = filter.dataset.pfilter;
    [...$("promptFilters").querySelectorAll("[data-pfilter]")].forEach((b) =>
      b.classList.toggle("active", b === filter));
    renderPromptList();
    return;
  }
  const item = ev.target.closest("[data-prompt-key]");
  if (item) {
    selectPrompt(item.dataset.promptKey).catch((e) => uiToast(e.message || "读取失败", "bad"));
    return;
  }
  const versionBtn = ev.target.closest("[data-pversion]");
  if (versionBtn) {
    restorePromptVersion(Number(versionBtn.dataset.pversion));
    return;
  }
  if (ev.target.closest("[data-q-remove]")) {
    ev.target.closest(".wb-quick-item").remove();
    if (!$("pwQuickList").querySelector(".wb-quick-item")) renderPromptQuick([]);
    setPromptDirty(true);
    return;
  }
  if (ev.target.id === "promptSyncBtn") { syncPromptPage(); return; }
  if (ev.target.id === "promptSaveBtn") { savePromptDraft(); return; }
  if (ev.target.id === "promptResetBtn") { resetPromptDraft(); return; }
  if (ev.target.id === "promptRestoreLatestBtn") {
    const prev = ((S.promptDetail && S.promptDetail.versions) || [])[1];
    if (prev) restorePromptVersion(prev.version);
    return;
  }
  if (ev.target.id === "promptPreviewBtn" || ev.target.id === "promptPvRun") {
    previewPromptDraft();
    return;
  }
  if (ev.target.id === "promptPreviewClose") { $("promptPreviewPanel").hidden = true; return; }
  if (ev.target.id === "pwAddQuick") { insertPromptQuickRow(); setPromptDirty(true); return; }
});

document.addEventListener("input", (ev) => {
  if (ev.target.id === "promptSearch") {
    S.promptSearch = ev.target.value;
    renderPromptList();
    return;
  }
  if (ev.target.id === "promptContent") {
    updatePromptCounter();
    setPromptDirty(true);
    return;
  }
  if (ev.target.closest && ev.target.closest("#promptWbEditor")) {
    setPromptDirty(true);
  }
});

document.addEventListener("change", (ev) => {
  if (ev.target.id === "promptEnabled") setPromptDirty(true);
  if (ev.target.closest && ev.target.closest("#promptWbEditor")) setPromptDirty(true);
});

/* ---------------- 前台功能与图标库 ---------------- */
const FRONT_ICON_PATHS = {
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"/>',
  book: '<path d="M5 4h5.5A3.5 3.5 0 0 1 14 7.5V20a3 3 0 0 0-3-3H5z"/><path d="M19 4h-3.5A3.5 3.5 0 0 0 12 7.5V20a3 3 0 0 1 3-3H19z"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
  paperclip: '<path d="M20 11.5l-8.2 8.2a4.6 4.6 0 0 1-6.5-6.5l8.4-8.4a3.1 3.1 0 0 1 4.4 4.4l-8.3 8.3a1.7 1.7 0 0 1-2.4-2.4l7.7-7.7"/>',
  brain: '<path d="M9 5a3 3 0 0 0-3 3 3 3 0 0 0-1 5 3 3 0 0 0 3 3 3 3 0 0 0 4 2V6a3 3 0 0 0-3-1z"/><path d="M15 5a3 3 0 0 1 3 3 3 3 0 0 1 1 5 3 3 0 0 1-3 3 3 3 0 0 1-4 2V6a3 3 0 0 1 3-1z"/>',
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 19h14"/>',
  share: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 10.8l7.6-3.6M8.2 13.2l7.6 3.6"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1 1-1.1 1.8"/><circle cx="12" cy="17" r="1"/>',
  key: '<circle cx="8" cy="12" r="4"/><path d="M12 12h9M17 12v3M20 12v3"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="5" cy="6" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="5" cy="18" r="1"/>',
  code: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4"/>',
  plan: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M8 11h3M14 11h2M8 15h7"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
};

function frontIconSvg(key, sizeClass = "") {
  const body = FRONT_ICON_PATHS[key] || FRONT_ICON_PATHS.spark;
  return `<svg class="${sizeClass}" viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
}

function frontIconData(item) {
  if (!item) return "";
  if (item.icon_id) {
    const found = (S.frontIcons || []).find((x) => Number(x.id) === Number(item.icon_id));
    if (found && found.data) return found.data;
  }
  return item.icon_data || "";
}

function frontIconMarkup(item) {
  const data = frontIconData(item);
  if (data) return `<img src="${esc(data)}" alt="">`;
  return frontIconSvg(item && item.icon_key);
}

function frontDraftItem(key) {
  return (S.frontDraft || []).find((x) => x.key === key) || null;
}

function frontParentBlocked(item) {
  if (!item || !item.depends_on) return "";
  const parent = frontDraftItem(item.depends_on);
  return !parent || !parent.enabled ? item.depends_on : "";
}

function frontItemVisible(item) {
  return !!item && !!item.enabled && !frontParentBlocked(item);
}

function frontDraftChanges() {
  if (!S.frontData || !S.frontDraft) return [];
  const base = new Map(S.frontData.items.map((x) => [x.key, x]));
  return S.frontDraft.filter((d) => {
    const old = base.get(d.key);
    if (!old) return true;
    return !!old.enabled !== !!d.enabled ||
      (old.icon_key || "") !== (d.icon_key || "") ||
      (old.icon_tone || "") !== (d.icon_tone || "") ||
      Number(old.icon_id || 0) !== Number(d.icon_id || 0);
  }).map((x) => x.key);
}

function cloneFrontDraft() {
  if (!S.frontData) return [];
  return S.frontData.items.map((x) => ({ ...x }));
}

function frontGroupCount(group) {
  return (S.frontDraft || []).filter((x) => x.group === group).length;
}

function frontGroupVisibleCount(group) {
  return (S.frontDraft || []).filter((x) => x.group === group && frontItemVisible(x)).length;
}

function frontMatchesFilter(item) {
  if (S.frontFilter !== "all" && item.group !== S.frontFilter) return false;
  const q = String(S.frontQuery || "").trim().toLowerCase();
  if (!q) return true;
  return [item.name, item.description, item.key, ...(item.surfaces || [])]
    .join(" ").toLowerCase().includes(q);
}

function frontRevLabel(rev) {
  const n = Number(rev) || 0;
  if (n > 1e9 && n < 1e12) {
    const d = new Date(n * 1000);
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${mm}-${dd} ${hh}:${mi}`;
  }
  return n ? "#" + n : "—";
}

function renderFrontStats() {
  const total = (S.frontDraft || []).length;
  const visible = (S.frontDraft || []).filter(frontItemVisible).length;
  const hidden = total - visible;
  const capability = (S.frontDraft || []).filter((x) => x.source === "config").length;
  const rev = S.frontData ? S.frontData.revision : 0;
  const pct = total ? Math.round((visible / total) * 100) : 0;
  $("frontStats").innerHTML = `
    <div class="front-ov-main">
      <div class="front-ov-label">用户端当前显示</div>
      <div class="front-ov-value"><b>${visible}</b><span>/ ${total} 个入口</span></div>
      <div class="front-ov-meter" role="img" aria-label="显示 ${pct}%"><i style="width:${pct}%"></i></div>
    </div>
    <div class="front-ov-metrics">
      <div class="front-ov-metric"><span>已隐藏</span><b>${hidden}</b><small>刷新后从用户端移除</small></div>
      <div class="front-ov-metric"><span>能力开关</span><b>${capability}</b><small>关闭会同时停用能力</small></div>
      <div class="front-ov-metric"><span>最近保存</span><b class="time">${frontRevLabel(rev)}</b><small>${S.frontDirty ? "有未保存更改" : "保存即生效"}</small></div>
    </div>`;
}

function renderFrontFilters() {
  const groups = (S.frontData && S.frontData.groups) || [];
  const all = `<button type="button" class="chip ${S.frontFilter === "all" ? "active" : ""}" data-front-filter="all">全部 · ${(S.frontDraft || []).length}</button>`;
  $("frontFilters").innerHTML = all + groups.map((g) =>
    `<button type="button" class="chip ${S.frontFilter === g.key ? "active" : ""}" data-front-filter="${esc(g.key)}">${esc(g.label)} · ${frontGroupVisibleCount(g.key)}</button>`).join("");
}

function renderFrontCard(item) {
  const blocked = frontParentBlocked(item);
  const tag = blocked
    ? `<span class="front-mini-tag blocked">随工作台隐藏</span>`
    : !item.enabled
      ? `<span class="front-mini-tag hidden">已隐藏</span>`
      : item.source === "config"
        ? `<span class="front-mini-tag capability">能力开关</span>`
        : "";

  return `
    <div class="front-card ${item.enabled ? "on" : "off"} ${blocked ? "blocked" : ""}" data-front-card="${esc(item.key)}">
      <div class="front-card-top">
        <div class="front-icon-tile ${esc(item.icon_tone || "blue")}">
          ${frontIconMarkup(item)}
          <button type="button" class="front-icon-edit" data-front-icon-edit="${esc(item.key)}" title="更换图标" aria-label="更换 ${esc(item.name)} 的图标"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l4.2-1 10.3-10.3-3.2-3.2L5 15.8 4 20z"/><path d="M14 4.5l3.2 3.2"/></svg></button>
        </div>
        <div class="front-card-copy">
          <div class="front-card-title"><b>${esc(item.name)}</b>${tag}</div>
          <p title="${esc(item.description)}">${esc(item.description)}</p>
        </div>
        <label class="front-switch" title="${blocked ? "依赖的工作台已关闭" : "开启或关闭前台入口"}">
          <input type="checkbox" data-front-toggle="${esc(item.key)}" ${item.enabled ? "checked" : ""} ${blocked ? "disabled" : ""}>
          <span></span>
        </label>
      </div>
    </div>`;
}

function renderFrontGroups() {
  const groups = (S.frontData && S.frontData.groups) || [];
  let html = "";
  let matched = 0;
  groups.forEach((g) => {
    const items = (S.frontDraft || []).filter((x) => x.group === g.key && frontMatchesFilter(x));
    if (!items.length) return;
    matched += items.length;
    html += `<div class="front-group">
      <div class="front-group-head"><span class="front-group-dot ${esc(g.tone)}">${g.tone === "blue" ? "✦" : g.tone === "green" ? "●" : g.tone === "amber" ? "◆" : "✧"}</span>${esc(g.label)}<small>${frontGroupCount(g.key)} 个 · ${frontGroupCount(g.key) - frontGroupVisibleCount(g.key) ? `${frontGroupCount(g.key) - frontGroupVisibleCount(g.key)} 个已隐藏` : "全部显示"}</small></div>
      <div class="front-card-grid">${items.map(renderFrontCard).join("")}</div>
    </div>`;
  });
  $("frontGroups").innerHTML = html || `<div class="front-empty">当前筛选下没有功能。</div>`;
  $("frontEmpty").hidden = matched > 0;
}

function frontPreviewLabel(item) {
  const labels = { workbench: "工作台", skills: "插件 · 技能", collab: "小队与共享", desk: "服务台" };
  return labels[item.key] || item.name;
}

function renderFrontPreview() {
  const sideKeys = ["workbench", "skills", "collab", "desk"];
  const side = sideKeys.map((key) => {
    const item = frontDraftItem(key);
    if (!item || !frontItemVisible(item)) return "";
    return `<div class="front-preview-nav-item"><span class="front-preview-nav-icon">${frontIconMarkup(item)}</span><span>${esc(frontPreviewLabel(item))}</span></div>`;
  }).filter(Boolean).join("");
  $("frontPreviewSide").innerHTML = side || `<div class="front-preview-nav-item"><span class="front-preview-nav-icon">${frontIconSvg("spark")}</span><span>基础对话</span></div>`;
  const toolKeys = ["skills", "library", "web", "docgen", "attach"];
  const tools = toolKeys.map((key) => {
    const item = frontDraftItem(key);
    if (!item || !frontItemVisible(item)) return "";
    const labels = { skills: "技能", library: "资料库", web: "联网", docgen: "格式", attach: "附件" };
    return `<span class="front-preview-tool">${frontIconMarkup(item)}<span>${esc(labels[key] || item.name)}</span></span>`;
  }).filter(Boolean).join("");
  $("frontPreviewTools").innerHTML = `<div class="front-preview-tools">${tools || '<span class="front-preview-tool">基础对话</span>'}</div>`;
  const settingKeys = ["kb", "library", "memory", "api_access", "data_export"];
  const settings = settingKeys.map((key) => {
    const item = frontDraftItem(key);
    if (!item || !frontItemVisible(item)) return "";
    const labels = { kb: "知识库", library: "资料库", memory: "记忆", api_access: "API", data_export: "数据" };
    return `<span>${esc(labels[key] || item.name)}</span>`;
  }).filter(Boolean).join("");
  $("frontPreviewSettings").innerHTML = `<b>设置</b>${settings || `<span>账号</span>`}`;
  const agent = frontDraftItem("agent");
  const agentOn = agent && frontItemVisible(agent);
  $("frontPreviewTop").innerHTML = `<span>新对话${agentOn ? " · 通用助手 ▾" : ""}</span><span class="front-preview-model">模型 ▾</span>`;
  const wb = frontDraftItem("workbench");
  $("frontPreviewSuggest").innerHTML = wb && frontItemVisible(wb)
    ? `<span>教师工作台</span><span>金融简报</span><span>写工作总结</span>`
    : `<span>写一份工作总结</span><span>解释一个技术概念</span><span>润色一段文字</span>`;
}

function renderFrontDirty() {
  const changes = frontDraftChanges();
  const count = changes.length;
  S.frontDirty = count > 0;
  const state = $("frontSaveState");
  state.className = "front-save-state " + (S.frontDirty ? "dirty" : "ok");
  const rev = S.frontData ? S.frontData.revision : 0;
  state.textContent = S.frontDirty ? `${count} 项待生效` : `已生效 · ${frontRevLabel(rev)} 更新`;
  state.title = `修订号 #${rev}`;
  $("frontSaveBtn").disabled = !S.frontDirty;
  $("frontDirtySaveBtn").disabled = !S.frontDirty;
  $("frontDirtyBar").hidden = !S.frontDirty;
  $("frontDirtyText").textContent = S.frontDirty ? `${count} 项更改尚未保存` : "所有更改已保存";
  $("frontPreviewState").className = "front-preview-state " + (S.frontDirty ? "dirty" : "");
  $("frontPreviewState").textContent = S.frontDirty ? "待保存预览" : "已生效";
}

function renderFrontPage() {
  if (!S.frontData || !S.frontDraft) return;
  S.frontDirty = frontDraftChanges().length > 0;
  renderFrontStats();
  renderFrontFilters();
  renderFrontGroups();
  renderFrontPreview();
  renderFrontDirty();
}

async function loadFrontPage() {
  $("frontGroups").innerHTML = `<div class="front-loading">正在读取前台功能…</div>`;
  const d = await api("/api/admin/front-features");
  S.frontData = d;
  S.frontIcons = d.icons || [];
  S.frontPresets = d.presets || [];
  S.frontDraft = cloneFrontDraft();
  S.frontDirty = false;
  S.frontFilter = "all";
  S.frontQuery = "";
  const search = $("frontSearch");
  if (search) search.value = "";
  renderFrontPage();
}

function markFrontDirty() {
  renderFrontPage();
}

async function saveFrontPage() {
  const changes = frontDraftChanges();
  if (!changes.length) return;
  const btn = $("frontSaveBtn");
  const btn2 = $("frontDirtySaveBtn");
  btn.disabled = true;
  btn2.disabled = true;
  const payload = {
    items: (S.frontDraft || []).map((x) => ({
      key: x.key, enabled: !!x.enabled, icon_key: x.icon_key || "",
      icon_tone: x.icon_tone || "blue", icon_id: Number(x.icon_id || 0),
    })),
  };
  try {
    const d = await api("/api/admin/front-features", { method: "PUT", body: JSON.stringify(payload) });
    S.frontData = d;
    S.frontIcons = d.icons || [];
    S.frontPresets = d.presets || [];
    S.frontDraft = cloneFrontDraft();
    S.frontDirty = false;
    renderFrontPage();
    uiToast(`已保存并生效 · ${frontRevLabel(d.revision)} 更新`);
  } catch (e) {
    uiToast(e.message || "保存失败", "bad");
  } finally {
    btn.disabled = !frontDraftChanges().length;
    btn2.disabled = btn.disabled;
  }
}

function undoFrontDraft() {
  S.frontDraft = cloneFrontDraft();
  renderFrontPage();
  uiToast("已撤销未保存的更改");
}

function frontIconLabel(item) {
  if (!item) return "默认图标";
  if (item.icon_id) {
    const found = S.frontIcons.find((x) => Number(x.id) === Number(item.icon_id));
    if (found) return found.name;
  }
  const p = (S.frontPresets || []).find((x) => x.key === item.icon_key);
  return p ? p.label : (FRONT_ICON_PATHS[item.icon_key] ? "预设图标" : "默认图标");
}

function openFrontIconModal(key = "") {
  if (!S.frontDraft || !S.frontDraft.length) return;
  const target = key && frontDraftItem(key) ? key : S.frontDraft[0].key;
  S.frontIconTarget = target;
  const item = frontDraftItem(target);
  S.frontIconKey = item.icon_key || "spark";
  S.frontIconId = Number(item.icon_id || 0);
  S.frontIconTone = item.icon_tone || "blue";
  $("frontIconTarget").innerHTML = S.frontDraft.map((x) =>
    `<option value="${esc(x.key)}" ${x.key === target ? "selected" : ""}>${esc(x.name)}</option>`).join("");
  $("frontIconModal").hidden = false;
  renderFrontIconModal(key ? "更换图标 · " + item.name : "图标库");
}

function renderFrontIconModal(title = "") {
  const item = frontDraftItem(S.frontIconTarget);
  if (!item) return;
  $("frontIconTitle").textContent = title || "图标库";
  $("frontIconTarget").value = S.frontIconTarget;
  const fake = { key: item.key, icon_key: S.frontIconKey, icon_id: S.frontIconId, icon_tone: S.frontIconTone };
  $("frontIconBig").className = "front-icon-big " + (S.frontIconTone || "blue");
  $("frontIconBig").innerHTML = frontIconMarkup(fake);
  $("frontIconPickName").textContent = S.frontIconId
    ? (S.frontIcons.find((x) => Number(x.id) === Number(S.frontIconId)) || {}).name || "自定义图标"
    : (S.frontPresets.find((x) => x.key === S.frontIconKey) || {}).label || "默认图标";
  $("frontToneRow").innerHTML = (S.frontData.tones || ["blue", "green", "amber", "purple", "gray", "teal"]).map((tone) =>
    `<button type="button" class="front-tone ${esc(tone)} ${S.frontIconTone === tone ? "active" : ""}" data-front-tone="${esc(tone)}" title="${esc(tone)}"></button>`).join("");
  $("frontPresetGrid").innerHTML = S.frontPresets.map((p) =>
    `<button type="button" class="front-preset ${!S.frontIconId && S.frontIconKey === p.key ? "active" : ""}" data-front-preset="${esc(p.key)}" title="${esc(p.label)}">${frontIconSvg(p.key)}</button>`).join("");
  $("frontIconLibrary").innerHTML = S.frontIcons.map((ic) =>
    `<div class="front-preset ${Number(S.frontIconId) === Number(ic.id) ? "active" : ""}" role="button" tabindex="0" data-front-icon="${esc(ic.id)}" title="${esc(ic.name)}"><img src="${esc(ic.data)}" alt=""><button type="button" class="front-preset-del" data-front-icon-del="${esc(ic.id)}" title="删除图标">×</button></div>`).join("");
  $("frontIconEmpty").hidden = S.frontIcons.length > 0;
  $("frontIconHint").textContent = `将应用到：${item.name} · ${frontIconLabel({ icon_key: S.frontIconKey, icon_id: S.frontIconId })}`;
}

function applyFrontIcon() {
  const item = frontDraftItem(S.frontIconTarget);
  if (!item) return;
  item.icon_key = S.frontIconKey;
  item.icon_id = Number(S.frontIconId || 0);
  item.icon_tone = S.frontIconTone || "blue";
  item.icon_data = frontIconData({ icon_key: S.frontIconKey, icon_id: S.frontIconId });
  $("frontIconModal").hidden = true;
  markFrontDirty();
  uiToast("图标已更新，点“保存并生效”后下发");
}

async function uploadFrontIcon(file) {
  if (!file) return;
  if (file.size > 160 * 1024) { uiToast("图标超过 160KB，请压缩后再上传", "bad"); return; }
  const hint = $("frontIconHint");
  hint.textContent = "正在上传图标…";
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const data = String(reader.result || "");
      const d = await api("/api/admin/front-icons", {
        method: "POST",
        body: JSON.stringify({ name: file.name.replace(/\.[^.]+$/, "").slice(0, 40) || "自定义图标", data }),
      });
      S.frontIcons.unshift({ ...d, used_by: [] });
      S.frontIconId = Number(d.id);
      S.frontIconKey = "";
      renderFrontIconModal("图标库");
      uiToast("图标已加入图标库，点“应用到当前功能”");
    } catch (e) {
      uiToast(e.message || "上传图标失败", "bad");
      renderFrontIconModal("图标库");
    }
  };
  reader.readAsDataURL(file);
}

async function deleteFrontIcon(iconId) {
  const ic = S.frontIcons.find((x) => Number(x.id) === Number(iconId));
  const used = (ic && ic.used_by) || [];
  const ok = await confirmInline(used.length
    ? `图标「${ic.name}」正被 ${used.length} 个功能使用，删除后这些功能会回退默认图标。确定删除？`
    : `确定删除图标「${ic ? ic.name : "这个图标"}」？`, "删除");
  if (!ok) return;
  try {
    const d = await api(`/api/admin/front-icons/${iconId}`, { method: "DELETE" });
    S.frontIcons = d.icons || [];
    (S.frontDraft || []).forEach((x) => {
      if (Number(x.icon_id) === Number(iconId)) {
        x.icon_id = 0;
        x.icon_key = x.icon_key || "spark";
        x.icon_data = "";
      }
    });
    if (Number(S.frontIconId) === Number(iconId)) {
      S.frontIconId = 0;
      S.frontIconKey = frontDraftItem(S.frontIconTarget).icon_key || "spark";
    }
    renderFrontIconModal("图标库");
    renderFrontPage();
    uiToast("图标已删除");
  } catch (e) {
    uiToast(e.message || "删除失败", "bad");
  }
}

document.addEventListener("click", (ev) => {
  const filter = ev.target.closest("[data-front-filter]");
  if (filter) {
    S.frontFilter = filter.dataset.frontFilter;
    renderFrontPage();
    return;
  }
  if (ev.target.id === "frontSaveBtn" || ev.target.id === "frontDirtySaveBtn") {
    saveFrontPage();
    return;
  }
  if (ev.target.id === "frontUndoBtn") {
    undoFrontDraft();
    return;
  }
  if (ev.target.id === "frontIconLibBtn") {
    openFrontIconModal();
    return;
  }
  const edit = ev.target.closest("[data-front-icon-edit]");
  if (edit) {
    openFrontIconModal(edit.dataset.frontIconEdit);
    return;
  }
  if (ev.target.closest("[data-front-modal-close]")) {
    $("frontIconModal").hidden = true;
    return;
  }
  const preset = ev.target.closest("[data-front-preset]");
  if (preset) {
    S.frontIconKey = preset.dataset.frontPreset;
    S.frontIconId = 0;
    renderFrontIconModal($("frontIconTitle").textContent);
    return;
  }
  const icon = ev.target.closest("[data-front-icon]");
  if (icon && !ev.target.closest("[data-front-icon-del]")) {
    S.frontIconId = Number(icon.dataset.frontIcon);
    S.frontIconKey = "";
    renderFrontIconModal($("frontIconTitle").textContent);
    return;
  }
  const del = ev.target.closest("[data-front-icon-del]");
  if (del) {
    deleteFrontIcon(Number(del.dataset.frontIconDel));
    return;
  }
  const tone = ev.target.closest("[data-front-tone]");
  if (tone) {
    S.frontIconTone = tone.dataset.frontTone;
    renderFrontIconModal($("frontIconTitle").textContent);
    return;
  }
  if (ev.target.id === "frontIconApplyBtn") {
    applyFrontIcon();
    return;
  }
  if (ev.target.id === "frontIconUploadBtn") {
    $("frontIconFile").click();
    return;
  }
});

document.addEventListener("change", (ev) => {
  if (ev.target.matches("[data-front-toggle]")) {
    const key = ev.target.dataset.frontToggle;
    const item = frontDraftItem(key);
    if (!item) return;
    item.enabled = !!ev.target.checked;
    markFrontDirty();
    return;
  }
  if (ev.target.id === "frontIconTarget") {
    const key = ev.target.value;
    const item = frontDraftItem(key);
    if (!item) return;
    S.frontIconTarget = key;
    S.frontIconKey = item.icon_key || "spark";
    S.frontIconId = Number(item.icon_id || 0);
    S.frontIconTone = item.icon_tone || "blue";
    renderFrontIconModal("图标库");
    return;
  }
  if (ev.target.id === "frontIconFile" && ev.target.files && ev.target.files[0]) {
    uploadFrontIcon(ev.target.files[0]);
    ev.target.value = "";
  }
});

document.addEventListener("input", (ev) => {
  if (ev.target.id === "frontSearch") {
    S.frontQuery = ev.target.value;
    renderFrontGroups();
    return;
  }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("frontIconModal").hidden) $("frontIconModal").hidden = true;
});
