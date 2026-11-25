/* 本地 AI 工作台 · 用户端
   纯前端（无构建步骤），所有数据通过 /api 访问。 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  const BRAND_RE = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

  function brandLogoUrl(branding) {
    const url = String(branding.brand_logo_url || "");
    return url.startsWith("/api/branding/logo") ? url : "";
  }

  function applyBrandColor(value) {
    const color = BRAND_RE.test(String(value || "")) ? String(value) : "#4f6ef7";
    const root = document.documentElement;
    root.style.setProperty("--brand", color);
    root.style.setProperty("--brand-2", `color-mix(in srgb, ${color} 68%, #7b61ff)`);
    root.style.setProperty("--brand-ink", `color-mix(in srgb, ${color} 62%, var(--text))`);
    root.style.setProperty("--brand-soft", `color-mix(in srgb, ${color} 11%, var(--panel))`);
  }

  function applyBrandLogo(url) {
    $$("[data-brand-logo-box]").forEach((box) => {
      const img = $("[data-brand-logo]", box);
      const fallback = $("[data-brand-logo-default]", box);
      if (!img || !fallback) return;
      if (url) {
        img.src = url;
        img.hidden = false;
        fallback.hidden = true;
        box.classList.add("has-image");
      } else {
        img.removeAttribute("src");
        img.hidden = true;
        fallback.hidden = false;
        box.classList.remove("has-image");
      }
    });
    const icon = $('link[rel="icon"]');
    if (icon) {
      icon.removeAttribute("type");
      icon.href = url || "/favicon.svg";
    }
  }

  function applyLegal(branding) {
    const box = $("#authLegal");
    if (!box) return;
    box.textContent = "";
    const links = [];
    if (branding.brand_icp) {
      links.push([branding.brand_icp, branding.brand_icp_url]);
    }
    if (branding.brand_police) {
      links.push([branding.brand_police, branding.brand_police_url]);
    }
    links.forEach(([text, href], index) => {
      if (index) {
        const sep = document.createElement("span");
        sep.className = "sep";
        sep.textContent = "·";
        box.appendChild(sep);
      }
      if (/^https?:\/\//i.test(String(href || ""))) {
        const a = document.createElement("a");
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = text;
        box.appendChild(a);
      } else {
        const span = document.createElement("span");
        span.textContent = text;
        box.appendChild(span);
      }
    });
    if (branding.brand_copyright) {
      if (links.length) {
        const sep = document.createElement("span");
        sep.className = "sep";
        sep.textContent = "·";
        box.appendChild(sep);
      }
      const copy = document.createElement("span");
      copy.textContent = branding.brand_copyright;
      box.appendChild(copy);
    }
    box.hidden = !box.childElementCount;
  }

  function applyBranding(branding) {
    if (!branding) return;
    S.branding = branding;
    const name = String(branding.org_name || "本地 AI 工作台").trim() || "本地 AI 工作台";
    document.title = name;
    $$("[data-brand-name]").forEach((el) => { el.textContent = name; });
    const shortName = String(branding.org_short_name || name).trim() || name;
    $$("[data-brand-short-name]").forEach((el) => { el.textContent = shortName; });
    $$("[data-brand-tagline]").forEach((el) => {
      el.textContent = String(branding.brand_tagline || "Local AI Workbench");
    });
    const title = $("#authHeroTitle");
    if (title && branding.brand_login_title) title.textContent = branding.brand_login_title;
    const lead = $("#authHeroLead");
    if (lead && branding.brand_login_lead) lead.textContent = branding.brand_login_lead;
    const foot = $("#authFoot");
    if (foot) {
      foot.textContent = String(branding.brand_login_foot || "");
      foot.hidden = !foot.textContent;
    }
    const sub = $("#authSubtitle");
    if (sub && branding.brand_auth_subtitle && S.authMode !== "setup" && S.authMode !== "register") {
      sub.textContent = branding.brand_auth_subtitle;
    }
    applyLegal(branding);
    applyBrandLogo(brandLogoUrl(branding));
    applyBrandColor(branding.brand_primary);
    renderWatermark(branding);
  }

  function renderWatermark(branding) {
    const old = $("#wbWatermark");
    if (old) old.remove();
    if (!branding || !branding.watermark_enabled || !S.user) return;
    const org = String(branding.org_name || "本地 AI 工作台");
    const text = String(branding.watermark_text || "{user} · {org}")
      .replaceAll("{user}", S.user.username || "?").replaceAll("{org}", org)
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

  const S = {
    initialized: false,
    allowRegister: false,
    authMode: "login",
    authMethod: "password",
    bindChannel: "",
    providers: [],
    user: null,
    models: [],
    localEnabled: true,
    conversations: [],
    cid: null,
    messages: [],
    convSystemPrompt: "",
    lastUserMessage: "",
    attachments: [],
    skills: [],
    skill: null,
    agents: [],
    agentId: null,
    collabSquads: [],
    announcements: [],
    lastAnnouncementId: null,
    lastSkill: null,
    web: false,
    lastWeb: false,
    outputFormat: "",
    lastOutputFormat: "",
    libraryItems: [],
    librarySelected: [],
    libraryState: null,
    libraryLoadedAt: 0,
    libraryQuery: "",
    uploading: false,
    stream: null,
    abort: null,
    prefs: null,
    apiCtx: null,
    apiKeys: [],
    apiDocs: { curl: "", python: "" },
    drawerTab: "account",
    openedConversation: 0,
    searchTimer: 0,
    wbTab: "overview",
    wbLoadedAt: 0,
    wbEditingTask: null,
    wbLastRunId: 0,
    wbRunStatuses: {},
    wbPoll: null,
    wbOverview: null,
    wbTasks: [],
    wbTemplate: "",
    wbCustom: [],
    frontFeatures: null,
    frontRevision: 0,
    frontPoll: null,
    frontLastSync: 0,
    frontFocusBound: false,
  };

  const PREF_DEFAULT = {
    model: "",
    temperature: 0.7,
    maxTokens: 2048,
    useKb: true,
    systemPrompt: "",
  };

  const SKILL_ICONS = {
    list: "i-list", translate: "i-translate", edit: "i-edit",
    code: "i-code", file: "i-file", plan: "i-plan",
  };
  const FILE_KINDS = { image: "图片", document: "文档", text: "文本", file: "文件" };
  const OUT_FORMATS = {
    docx: "Word 文档", xlsx: "Excel 表格", pptx: "PPT 演示",
    pdf: "PDF 文档", md: "Markdown 文档", txt: "纯文本",
  };

  /* ------------------------------------------------------------------ 基础 */
  function cookie(name) {
    const rows = document.cookie ? document.cookie.split(";") : [];
    for (const row of rows) {
      const [k, ...v] = row.trim().split("=");
      if (k === name) return decodeURIComponent(v.join("="));
    }
    return "";
  }

  function errorText(data, fallback = "请求失败") {
    if (!data) return fallback;
    if (typeof data === "string") return data;
    if (Array.isArray(data.detail)) {
      return data.detail.map((x) => x.msg || String(x)).join("；");
    }
    if (data.detail) return String(data.detail);
    if (data.error) return String(data.error.message || data.error);
    return fallback;
  }

  async function api(path, opts = {}) {
    const method = opts.method || "GET";
    const headers = { ...(opts.headers || {}) };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    const csrf = cookie("wb_csrf");
    if (csrf && method !== "GET") headers["X-CSRF-Token"] = csrf;
    const res = await fetch(path, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      signal: opts.signal,
    });
    if (res.status === 401 && !opts.noAuth) {
      showAuth();
      throw new Error("登录已失效，请重新登录");
    }
    let data = null;
    const text = await res.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = text; }
    }
    if (!res.ok) throw new Error(errorText(data, `请求失败（${res.status}）`));
    return data;
  }

  function toast(text, ms = 2600) {
    const el = $("#toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, ms);
  }

  async function formApi(path, fd, method = "POST") {
    const headers = { "X-CSRF-Token": cookie("wb_csrf") };
    const res = await fetch(path, { method, credentials: "same-origin", headers, body: fd });
    if (res.status === 401) { showAuth(); throw new Error("登录已失效，请重新登录"); }
    const text = await res.text();
    let data = null;
    if (text) { try { data = JSON.parse(text); } catch { data = text; } }
    if (!res.ok) throw new Error(errorText(data, `请求失败（${res.status}）`));
    return data;
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(Number(ts) * 1000);
    if (Number.isNaN(d.getTime())) return "—";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function relTime(ts) {
    if (!ts) return "";
    const diff = Date.now() / 1000 - Number(ts);
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
    return fmtTime(ts).slice(5, 10);
  }

  /* ------------------------------------------------------------------ 主题与偏好 */
  function loadAppearance() {
    let a = {};
    try { a = JSON.parse(localStorage.getItem("wb.appearance") || "{}"); } catch {}
    a = { theme: "light", fontScale: 100, ...a };
    applyTheme(a.theme);
    applyFontScale(a.fontScale);
    $$("#themeGrid button").forEach((b) => b.classList.toggle("active", b.dataset.themeChoice === a.theme));
    $("#fontScale").value = a.fontScale;
    $("#fontScaleValue").textContent = `${a.fontScale}%`;
    return a;
  }

  function saveAppearance(patch) {
    let a = {};
    try { a = JSON.parse(localStorage.getItem("wb.appearance") || "{}"); } catch {}
    a = { theme: "light", fontScale: 100, ...a, ...patch };
    localStorage.setItem("wb.appearance", JSON.stringify(a));
    return a;
  }

  function applyTheme(mode) {
    const systemDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const actual = mode === "system" ? (systemDark ? "dark" : "light") : mode;
    document.documentElement.dataset.theme = actual;
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.content = actual === "dark" ? "#0e1118" : "#f5f6fa";
  }

  function applyFontScale(scale) {
    const n = clamp(Number(scale) || 100, 85, 125);
    document.documentElement.style.setProperty("--chat-font", `${(15.5 * n / 100).toFixed(1)}px`);
  }

  function loadPrefs() {
    const key = `wb.prefs.${S.user ? S.user.username : "guest"}`;
    let p = {};
    try { p = JSON.parse(localStorage.getItem(key) || "{}"); } catch {}
    S.prefs = { ...PREF_DEFAULT, ...p };
    return S.prefs;
  }

  function savePrefs(patch) {
    S.prefs = { ...(S.prefs || PREF_DEFAULT), ...patch };
    const key = `wb.prefs.${S.user ? S.user.username : "guest"}`;
    localStorage.setItem(key, JSON.stringify(S.prefs));
  }

  /* ------------------------------------------------------------------ 登录 / 注册 */
  async function loadProviders() {
    try {
      const d = await api("/api/auth/providers", { noAuth: true, headers: {} });
      S.providers = d.items || [];
    } catch {
      S.providers = [];
    }
    renderAuthProviders();
  }

  function otpProviders() {
    return (S.providers || []).filter((p) => p.key === "phone" || p.key === "email");
  }

  function renderAuthProviders() {
    const wrap = $("#authProviders");
    const buttons = $("#providerButtons");
    const note = $("#providerNote");
    if (!wrap || !buttons || !note) return;
    const oauthItems = (S.providers || []).filter((p) => p.key === "qq" || p.key === "wechat");
    const items = (S.providers || []).filter((p) => p.key !== "username");
    const otpReady = otpProviders().filter((p) => p.enabled && p.ready);
    const usable = oauthItems.filter((p) => p.enabled && p.login_url);
    if (S.authMode === "setup" || !usable.length) {
      wrap.hidden = true;
      buttons.innerHTML = "";
    } else {
      wrap.hidden = false;
      buttons.innerHTML = usable.map((p) => `
        <a class="provider-btn" href="${esc(p.login_url)}">
          <span>${esc(p.label)}</span>
        </a>`).join("");
    }
    const reserved = items.filter((p) => !p.enabled).map((p) => p.label).join(" / ");
    const broken = oauthItems.filter((p) => p.enabled && !p.login_url).map((p) => p.label).join(" / ");
    if (S.authMode === "setup") {
      note.textContent = "首次初始化只支持用户名；其他登录方式可在配置后启用。";
    } else if (usable.length && otpReady.length) {
      note.textContent = "第三方登录和手机号/邮箱验证码登录均已开放，登录后可在设置中绑定更多。";
    } else if (usable.length) {
      note.textContent = "已开放的登录方式显示在上方，登录后可在设置中绑定更多。";
    } else if (otpReady.length) {
      note.textContent = `${otpReady.map((p) => p.label).join(" / ")} 验证码登录已开放，可切换到对应方式。`;
    } else if (broken) {
      note.textContent = `${broken} 登录配置不完整，请检查密钥和回调地址`;
    } else if (reserved) {
      note.textContent = `${reserved} 接口已预留，配置后自动显示`;
    } else {
      note.textContent = "更多登录方式接口已预留。";
    }
    renderAuthMethods();
  }

  function renderAuthMethods() {
    const box = $("#authMethods");
    if (!box) return;
    const available = otpProviders().filter((p) => p.enabled && p.ready);
    const allow = S.initialized && S.authMode !== "setup" && available.length > 0;
    box.hidden = !allow;
    $$("[data-authmethod]").forEach((b) => {
      const method = b.dataset.authmethod;
      b.hidden = method !== "password" && !available.some((p) => p.key === method);
      b.classList.toggle("active", method === S.authMethod);
    });
    if (!allow && S.authMethod !== "password") S.authMethod = "password";
  }

  function setAuthMethod(method, reset = true) {
    const available = otpProviders().filter((p) => p.enabled && p.ready);
    if (method !== "password" && (!S.initialized || S.authMode === "setup" || !available.some((p) => p.key === method))) {
      method = "password";
    }
    S.authMethod = method;
    const isOtp = method !== "password";
    $("#authForm").hidden = isOtp;
    $("#otpForm").hidden = !isOtp;
    $("#otpError").hidden = true;
    if (reset) {
      $("#otpTarget").value = "";
      $("#otpCode").value = "";
    }
    if (isOtp) {
      const isPhone = method === "phone";
      $("#otpTargetLabel").textContent = isPhone ? "手机号" : "邮箱";
      $("#otpTarget").type = isPhone ? "tel" : "email";
      $("#otpTarget").autocomplete = isPhone ? "tel" : "email";
      $("#otpTarget").placeholder = isPhone ? "请输入手机号" : "请输入邮箱地址";
      $("#otpSubmit").textContent = S.authMode === "register" ? "注册并进入" : "登录";
      setTimeout(() => $("#otpTarget").focus(), 60);
    } else {
      $("#authSubmit").textContent = S.authMode === "register" ? "注册并进入" : "登录";
      setTimeout(() => $("#authUser").focus(), 60);
    }
    $$("[data-authmethod]").forEach((b) => b.classList.toggle("active", b.dataset.authmethod === method));
  }

  function setAuthMode(mode) {
    S.authMode = mode;
    const isSetup = mode === "setup";
    const isRegister = mode === "register";
    const tabs = $("#authTabs");
    const submit = $("#authSubmit");
    tabs.hidden = isSetup;
    $$(".auth-tab").forEach((b) => b.classList.toggle("active", b.dataset.authmode === mode));
    $("#authConfirmWrap").hidden = !(isSetup || isRegister);
    $("#authError").hidden = true;
    $("#authPass").value = "";
    $("#authConfirm").value = "";
    $("#authPass").autocomplete = isRegister || isSetup ? "new-password" : "current-password";
    if (isSetup) {
      $("#authKicker").textContent = "FIRST RUN";
      $("#authTitle").textContent = "初始化管理员";
      $("#authSubtitle").textContent = "这是第一次启动，请创建管理员账号";
      $("#authNote").textContent = "管理员可以进入控制台，管理用户、模型和网关。";
      $("#authSwitch").hidden = true;
      $("#authSwitchLogin").hidden = true;
      $(`#toConsole`).hidden = true;
      submit.textContent = "创建并进入";
    } else if (isRegister) {
      $("#authKicker").textContent = "CREATE ACCOUNT";
      $("#authTitle").textContent = "注册账号";
      $("#authSubtitle").textContent = "注册后自动获得全部本地模型";
      $("#authNote").textContent = "第三方 API 模型需要管理员另行分配。";
      $("#authSwitch").hidden = true;
      $("#authSwitchLogin").hidden = false;
      $(`#toConsole`).hidden = false;
      submit.textContent = "注册并进入";
    } else {
      $("#authKicker").textContent = "WELCOME BACK";
      $("#authTitle").textContent = "登录账号";
      $("#authSubtitle").textContent = S.branding?.brand_auth_subtitle
        || "使用工作台账号继续对话";
      $("#authNote").textContent = S.allowRegister ? "" : "管理员已关闭自助注册，请让管理员创建账号。";
      $("#authSwitch").hidden = !S.allowRegister;
      $("#authSwitchLogin").hidden = true;
      $(`#toConsole`).hidden = false;
      submit.textContent = "登录";
    }
    renderAuthProviders();
    if (isSetup) S.authMethod = "password";
    renderAuthMethods();
    setAuthMethod(S.authMethod, false);
  }

  function showAuth(state) {
    if (state) {
      S.initialized = !!state.initialized;
      S.allowRegister = !!state.allow_register;
    }
    S.stream = null;
    S.cid = null;
    S.messages = [];
    const wm = $("#wbWatermark");
    if (wm) wm.remove();
    $("#appView").hidden = true;
    $("#authView").hidden = false;
    $("#settingsDrawer").hidden = true;
    $("#authTabs").hidden = !S.initialized;
    $("#authSwitch").hidden = !S.allowRegister;
    $("#authError").hidden = true;
    $("#otpError").hidden = true;
    $("#authForm").reset();
    $("#otpForm").reset();
    S.authMethod = "password";
    setAuthMode(S.initialized ? "login" : "setup");
  }

  async function boot() {
    loadAppearance();
    restoreOutputFormat();
    await loadProviders();
    try {
      const state = await api("/api/auth/state", { noAuth: true, headers: {} });
      S.initialized = !!state.initialized;
      S.allowRegister = !!state.allow_register;
      S.branding = state.branding || S.branding;
      if (state.user) {
        S.user = state.user;
        applyBranding(state.branding);
        await enterApp();
      } else {
        applyBranding(state.branding);
        showAuth(state);
      }
      const params = new URLSearchParams(location.search);
      const oauth = params.get("oauth");
      if (oauth === "ok") {
        toast("已通过第三方账号登录");
      } else if (oauth === "error") {
        const message = params.get("message") || "第三方登录失败";
        if (S.user) toast(message);
        else authError(message);
      }
      if (oauth) history.replaceState(null, "", location.pathname);
    } catch (e) {
      showAuth();
      $("#authError").textContent = e.message;
      $("#authError").hidden = false;
    }
  }

  async function submitAuth(ev) {
    ev.preventDefault();
    const username = $("#authUser").value.trim();
    const password = $("#authPass").value;
    const confirm = $("#authConfirm").value;
    const error = $("#authError");
    error.hidden = true;

    if (username.length < 2) return authError("用户名至少 2 位");
    if (password.length < 8) return authError("密码至少 8 位");
    if ((S.authMode === "register" || S.authMode === "setup") && password !== confirm) {
      return authError("两次输入的密码不一致");
    }
    let path = "/api/auth/login";
    if (S.authMode === "setup") path = "/api/auth/setup";
    if (S.authMode === "register") path = "/api/auth/register";

    const btn = $("#authSubmit");
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = S.authMode === "setup" ? "创建中…" : (S.authMode === "register" ? "注册中…" : "登录中…");
    try {
      const data = await api(path, {
        method: "POST",
        body: { username, password },
        noAuth: true,
      });
      S.user = data.user;
      await enterApp();
    } catch (e) {
      authError(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  async function submitOtp(ev) {
    ev.preventDefault();
    const channel = S.authMethod;
    if (channel !== "phone" && channel !== "email") return;
    const target = $("#otpTarget").value.trim();
    const code = $("#otpCode").value.replace(/\s+/g, "");
    const err = $("#otpError");
    err.hidden = true;
    if (!target) return otpError(channel === "phone" ? "请输入手机号" : "请输入邮箱地址");
    if (channel === "phone" && !/^\+?\d{6,20}$/.test(target)) return otpError("手机号格式不正确");
    if (channel === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return otpError("邮箱格式不正确");
    if (!/^\d{6}$/.test(code)) return otpError("请输入 6 位数字验证码");
    const btn = $("#otpSubmit");
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = S.authMode === "register" ? "注册中…" : "登录中…";
    try {
      const data = await api(S.authMode === "register" ? "/api/auth/otp/register" : "/api/auth/otp/login", {
        method: "POST",
        body: { channel, target, code },
        noAuth: true,
      });
      S.user = data.user;
      await enterApp();
      toast(S.authMode === "register" ? "注册成功，已绑定登录方式" : "登录成功");
    } catch (e) {
      otpError(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  async function sendOtp() {
    if (S.authMethod !== "phone" && S.authMethod !== "email") return;
    const channel = S.authMethod;
    const target = $("#otpTarget").value.trim();
    const err = $("#otpError");
    err.hidden = true;
    if (!target) return otpError(channel === "phone" ? "请先输入手机号" : "请先输入邮箱地址");
    if (channel === "phone" && !/^\+?\d{6,20}$/.test(target)) return otpError("手机号格式不正确");
    if (channel === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return otpError("邮箱格式不正确");
    const btn = $("#otpSend");
    btn.disabled = true;
    let left = 60;
    btn.textContent = `${left}s 后重发`;
    const timer = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = "重新发送";
      } else {
        btn.textContent = `${left}s 后重发`;
      }
    }, 1000);
    try {
      const data = await api("/api/auth/otp/send", {
        method: "POST",
        body: { channel, target },
        noAuth: true,
      });
      toast(data && data.msg ? data.msg : "验证码已发送，请查收");
    } catch (e) {
      clearInterval(timer);
      btn.disabled = false;
      btn.textContent = "发送验证码";
      otpError(e.message);
    }
  }

  function otpError(msg) {
    const el = $("#otpError");
    el.textContent = msg;
    el.hidden = false;
  }

  function authError(msg) {
    const el = $("#authError");
    el.textContent = msg;
    el.hidden = false;
  }

  async function enterApp() {
    $("#authView").hidden = true;
    $("#appView").hidden = false;
    applyBranding(S.branding);
    loadPrefs();
    renderUser();
    await loadFrontFeatures().catch(() => {});
    await Promise.all([loadMe(), loadModels(), loadSkills(), loadWbCatalog(), loadConversations(),
      loadCollab().catch(() => {})]);
    const prefs = S.prefs;
    const prefModel = prefs.model && S.models.find((m) => m.key === prefs.model);
    if (prefModel && modelRunnable(prefModel)) {
      setModel(prefModel.key, false);
    } else {
      const fallback = S.models.find((m) => modelRunnable(m))
        || S.models.find((m) => m.downloaded !== false)
        || S.models[0];
      if (fallback) setModel(fallback.key, true);
    }
    applyChatPrefsToUI(false);
    const initialCid = chatIdFromUrl();
    if (initialCid) await openConversation(initialCid, false);
    else newChat(false);
    if (window.innerWidth <= 900) closeSidebar();
    initWbRecommendations();
    if (!S.modelPoll) S.modelPoll = setInterval(() => { if (S.user && !S.stream) loadModels(); }, 30000);
    if (!S.wbPoll) S.wbPoll = setInterval(pollWorkbench, 45000);
    if (!S.frontPoll) S.frontPoll = setInterval(syncFrontFeatures, 60000);
    if (!S.frontFocusBound) {
      S.frontFocusBound = true;
      window.addEventListener("focus", () => syncFrontFeatures().catch(() => {}));
      document.addEventListener("visibilitychange", () => { if (!document.hidden) syncFrontFeatures().catch(() => {}); });
    }
    applyFrontFeatures();
    pollWorkbench();
    setTimeout(() => $("#messageInput").focus(), 120);
  }

  function renderUser() {
    if (!S.user) return;
    const initial = (S.user.username || "?").slice(0, 1).toUpperCase();
    $("#userAvatar").textContent = initial;
    $("#profileAvatar").textContent = initial;
    $("#userName").textContent = S.user.username;
    $("#userRole").textContent = S.user.role === "admin" ? "管理员" : "普通用户";
    $("#profileName").textContent = S.user.username;
    $("#profileRole").textContent = S.user.role === "admin" ? "管理员" : "普通用户";
    $("#sidebarUser").textContent = S.user.role === "admin" ? "管理员账号" : "个人账号";
  }

  async function loadMe() {
    try {
      const d = await api("/api/auth/me");
      S.user = { ...S.user, ...(d.user || {}) };
      renderUser();
      $("#profileMeta").textContent = `${S.user.role === "admin" ? "管理员" : "普通用户"} · 加入于 ${fmtTime(S.user.created_at)}`;
      $("#statId").textContent = `#${S.user.id}`;
      $("#statLogin").textContent = S.user.last_login_at ? fmtTime(S.user.last_login_at) : "—";
      $("#statIp").textContent = S.user.last_login_ip || "—";
    } catch (e) { /* 401 已经跳登录 */ }
  }

  /* ------------------------------------------------------------------ 模型 */
  function modelLabel(m) {
    return String(m.label || m.key || "").trim() || m.key;
  }

  function modelRunnable(m) {
    return !!m && m.downloaded !== false && m.loaded === true;
  }

  async function loadModels() {
    try {
      const d = await api("/api/models");
      S.localEnabled = d.local_enabled !== false;
      S.models = (d.items || []).filter((m) =>
        m.available !== false && m.downloaded !== false
        && ["text", "code"].includes(m.category || "text"));
      S.serverModel = S.localEnabled ? ((d.server && d.server.model) || "") : "";
    } catch {
      S.models = [];
    }
    renderModelOptions();
    updateWelcome();
    if (!S.models.length) {
      $("#welcomeNote").textContent = S.localEnabled
        ? "当前账号还没有可用模型，请联系管理员在控制台「用户」页分配。"
        : "本地部署已在管理控制台关闭，暂时没有可用模型。";
    }
  }

  function renderModelOptions() {
    const select = $("#modelSelect");
    const opts = S.models.map((m) => `<option value="${esc(m.key)}">${esc(modelLabel(m))}</option>`).join("");
    select.innerHTML = opts || `<option value="">暂无可用模型</option>`;
    let current = (S.prefs && S.prefs.model) || "";
    if (!current || !S.models.some((m) => m.key === current)) {
      const fallback = S.models.find((m) => modelRunnable(m))
        || S.models.find((m) => m.downloaded !== false)
        || S.models[0];
      current = (fallback && fallback.key) || S.serverModel || "";
    }
    if (current && S.models.some((m) => m.key === current)) {
      select.value = current;
    }
  }

  function setModel(key, persist = true) {
    if (!S.models.some((m) => m.key === key)) return;
    $("#modelSelect").value = key;
    if (persist) savePrefs({ model: key });
    updateWelcome();
  }

  async function ensureModelLoaded(key) {
    const model = S.models.find((m) => m.key === key);
    if (!model || model.loaded === true || S.modelSwitching) return;
    S.modelSwitching = true;
    const select = $("#modelSelect");
    select.disabled = true;
    toast("正在切换模型…");
    try {
      await api("/api/models/select", { method: "POST", body: { key } });
      await loadModels();
      toast("模型已就绪");
    } catch (e) {
      const loaded = S.models.find((m) => modelRunnable(m));
      if (loaded) setModel(loaded.key);
      await loadModels();
      toast(e.message || "模型加载失败");
    } finally {
      S.modelSwitching = false;
      select.disabled = false;
    }
  }

  function selectedModel() {
    const key = (S.prefs && S.prefs.model) || $("#modelSelect").value || "";
    return S.models.find((m) => m.key === key) || null;
  }

  function renderWelcomeDate() {
    const el = $("#welcomeDate");
    if (!el) return;
    const d = new Date();
    const week = "日一二三四五六"[d.getDay()];
    el.textContent = `${d.getMonth() + 1} 月 ${d.getDate()} 日 周${week}`;
  }

  function renderWelcomeContinue(activeTpl) {
    const wrap = $("#welcomeContinue");
    const grid = $("#welcomeWbGrid");
    if (!wrap || !grid) return;
    const all = wbTemplatesAll();
    const picks = [];
    const add = (tpl) => {
      if (tpl && !picks.some((x) => x.id === tpl.id)) picks.push(tpl);
    };
    add(activeTpl);
    ["teacher", "finance", "writing", "design"].forEach((id) => add(all.find((t) => t.id === id)));
    all.slice(0, 3).forEach(add);
    if (!picks.length) {
      wrap.hidden = true;
      grid.innerHTML = "";
      return;
    }
    wrap.hidden = false;
    grid.innerHTML = picks.slice(0, 3).map((tpl) => {
      const desc = tpl.welcomeSub || tpl.desc || "打开工作台继续";
      return `<button class="wc-card" type="button" data-wb-home="${esc(tpl.id)}">`
        + `<span class="wc-icon">${esc(tpl.icon || "🧩")}</span>`
        + `<span class="wc-copy"><b>${esc(tpl.name)}</b><small>${esc(desc)}</small></span>`
        + `<span class="wc-arrow"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></span>`
        + `</button>`;
    }).join("");
  }

  function renderWelcomeHome() {
    const welcome = $("#welcome");
    const box = $("#suggestions");
    if (!welcome || !box) return;
    const tpl = wbTemplateOf();
    const mark = $("#welcomeMark");
    const badge = $("#welcomeWorkbench");
    const title = $("#welcomeTitle");
    const sub = $("#welcomeSub");
    const caps = $("#welcomeCaps");

    renderWelcomeDate();
    welcome.classList.toggle("is-workbench", !!tpl);
    welcome.dataset.tone = tpl ? (tpl.tone || "custom") : "";
    if (tpl) {
      mark.classList.add("emoji");
      mark.innerHTML = `<span>${esc(tpl.icon || "🧩")}</span>`;
      badge.hidden = false;
      badge.textContent = `正在使用 · ${tpl.name}`;
      title.textContent = tpl.welcome || `今天想在「${tpl.name}」里做什么？`;
      sub.textContent = tpl.welcomeSub || tpl.desc || "选一个推荐任务开始，也可以直接描述你的需求。";
      const names = wbSkillNamesOf(tpl).slice(0, 3);
      const plugins = (tpl.plugins || []).map(wbPluginName);
      const chips = [
        names.length ? `<span>技能 · ${esc(names.join(" / "))}</span>` : "",
        plugins.length ? `<span>插件 · ${esc(plugins.join(" / "))}</span>` : "",
      ].join("");
      caps.innerHTML = chips;
      caps.hidden = !chips;
    } else {
      mark.classList.remove("emoji");
      mark.innerHTML = `<svg><use href="#i-spark"/></svg>`;
      badge.hidden = true;
      badge.textContent = "";
      title.textContent = "今天想做什么？";
      sub.textContent = "直接说任务。需要资料、联网或工作台时，再打开对应工具。";
      caps.innerHTML = "";
      caps.hidden = true;
    }

    box.classList.toggle("pills", !!tpl);
    const items = tpl ? (tpl.quick || []).slice(0, 8) : WELCOME_QUICK_DEFAULT;
    const formatName = { docx: "Word", xlsx: "Excel", pptx: "PPT" };
    box.innerHTML = items.map((x) => {
      const fmt = formatName[x.format] || "";
      if (tpl) {
        return `<button type="button" data-suggest="${esc(x.text)}" data-suggest-format="${esc(x.format || "")}">`
          + `<span class="suggest-pill-dot" aria-hidden="true"></span>${esc(x.label)}`
          + (fmt ? `<em>${fmt}</em>` : "") + `</button>`;
      }
      return `<button type="button" class="quick-card q-${esc(x.tone || "blue")}" data-suggest="${esc(x.text)}" data-suggest-format="${esc(x.format || "")}">`
        + `<span class="q-icon"><svg><use href="#i-${esc(x.icon || "spark")}"/></svg></span>`
        + `<b>${esc(x.label)}</b><small>${esc(x.desc || "")}</small>`
        + `<span class="arrow"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></span>`
        + `</button>`;
    }).join("");

    renderWelcomeContinue(tpl);
  }


  function updateWelcome() {
    renderWelcomeHome();
    const m = selectedModel();
    if (m) $("#welcomeNote").textContent = "模型在本地运行，对话记录只保存在这台机器。";
    if (!S.models.length) $("#welcomeNote").textContent = S.localEnabled
      ? "当前账号还没有可用模型，请联系管理员分配。"
      : "本地部署已在管理控制台关闭，暂时没有可用模型。";
  }

  /* ------------------------------------------------------------------ 技能 */
  async function loadWbCatalog() {
    try {
      const d = await api("/api/workbench/catalog");
      if (Array.isArray(d.items) && d.items.length) {
        WB_TEMPLATES = d.items
          .filter((t) => t && t.id)
          .map((t) => ({
            ...t,
            desc: t.desc || t.description || "",
            skill: t.skill || (Array.isArray(t.skills) && t.skills.length ? t.skills[0] : ""),
            skills: Array.isArray(t.skills) ? t.skills : [],
            plugins: Array.isArray(t.plugins) ? t.plugins : [],
            quick: Array.isArray(t.quick) ? t.quick : [],
          }));
        if (S.wbTemplate && !wbTemplateOf()) S.wbTemplate = "";
      }
    } catch {
      // 后台接口不可用时继续使用内置默认模板
    }
  }

  async function loadSkills() {
    try {
      const d = await api("/api/chat/skills");
      S.skills = d.items || [];
    } catch {
      S.skills = [];
    }
    renderSkillMenu();
  }

  function renderSkillMenu() {
    const list = $("#skillList");
    if (!list) return;
    const none = `
      <button class="skill-item ${!S.skill ? "active" : ""}" type="button" data-skill-id="none">
        <span class="skill-ico"><svg><use href="#i-close"/></svg></span>
        <span class="skill-copy"><b>不使用技能</b><span>按普通对话发送</span></span>
      </button>`;
    const items = S.skills.map((s) => `
      <button class="skill-item ${S.skill && S.skill.id === s.id ? "active" : ""}" type="button" data-skill-id="${esc(s.id)}">
        <span class="skill-ico"><svg><use href="#${SKILL_ICONS[s.icon] || "i-spark"}"/></svg></span>
        <span class="skill-copy"><b>${esc(s.name)}</b><span>${esc(s.hint || "")}</span></span>
      </button>`).join("");
    list.innerHTML = none + items;
  }

  function setSkillMenu(open) {
    $("#skillMenu").hidden = !open;
    $("#skillBtn").setAttribute("aria-expanded", String(open));
  }

  function setSkill(id) {
    if (!id || id === "none" || id === "auto") {
      S.skill = null;
    } else {
      S.skill = S.skills.find((s) => s.id === id) || null;
    }
    $("#skillBtnLabel").textContent = S.skill ? S.skill.name : "技能";
    $("#skillBtn").classList.toggle("active", !!S.skill);
    renderSkillMenu();
    setSkillMenu(false);
  }

  function setOutputFormat(value, silent = false) {
    const fmt = OUT_FORMATS[value] ? value : "";
    S.outputFormat = fmt;
    const pick = $("#fmtPick");
    const sel = $("#formatSelect");
    if (sel && sel.value !== fmt) sel.value = fmt;
    if (pick) {
      pick.classList.toggle("active", !!fmt);
      pick.title = fmt
        ? `已选择 ${OUT_FORMATS[fmt]}：回答会直接生成可下载文件`
        : "选择输出文件格式；选好后本条及后续回答会直接生成可下载文件";
    }
    try { localStorage.setItem("wb.outputFormat", fmt); } catch {}
    if (!silent) toast(fmt ? `输出格式：${OUT_FORMATS[fmt]}，回答将生成文件` : "输出格式：自动（不生成文件）");
  }

  function restoreOutputFormat() {
    let saved = "";
    try { saved = localStorage.getItem("wb.outputFormat") || ""; } catch {}
    setOutputFormat(saved, true);
  }

  function setWeb(on) {
    S.web = !!on;
    const btn = $("#webBtn");
    if (!btn) return;
    btn.classList.toggle("active", S.web);
    btn.setAttribute("aria-pressed", String(S.web));
    btn.title = S.web ? "联网已开启：发送时会先搜索网页" : "联网检索实时网页（中文 360 / 英文 Bing），默认关闭";
  }

  /* -------------------------------------------------------------- 前台功能 */
  const FRONT_TAB_FEATURE = {
    api: "api_access", kb: "kb", library: "library", memory: "memory", data: "data_export",
  };

  const FEATURE_CENTER_META = {
    skills: { desc: "输入框技能、插件入口与工作台技能页", go: "打开", run: () => openWorkbench("caps") },
    web: { desc: "发送前检索实时网页，并在回答里保留来源", go: "开启", run: () => { setWeb(true); toast("联网已开启"); } },
    docgen: { desc: "把回答整理成 Word、Excel、PPT、PDF", go: "选格式", run: () => { $("#formatSelect")?.focus(); } },
    attach: { desc: "上传文档、图片并解析或 OCR", go: "上传", run: () => { $("#attachBtn")?.click(); } },
    agent: { desc: "在输入框左侧切换智能体", go: "切换", run: () => { const s = $("#agentSelect"); if (s) { s.focus(); try { s.showPicker?.(); } catch {} } } },
    library: { desc: "长期保存资料，可挑选后随消息反复使用", go: "打开", run: () => openSettings("library") },
    kb: { desc: "个人知识库资料与检索", go: "打开", run: () => openSettings("kb") },
    memory: { desc: "跨对话保存偏好与长期记忆", go: "打开", run: () => openSettings("memory") },
    workbench: { desc: "工作台总入口、当前工作台和推荐模板", go: "打开", run: () => openWorkbench("overview") },
    schedule: { desc: "工作台里的定时任务页", go: "打开", run: () => openWorkbench("tasks") },
    files: { desc: "工作台里的生成文件列表", go: "打开", run: () => openWorkbench("files") },
    api_access: { desc: "API 密钥与调用说明", go: "打开", run: () => openSettings("api") },
    data_export: { desc: "账号数据、对话与文件导出", go: "打开", run: () => openSettings("data") },
    collab: { desc: "小队、共享会话和分享当前对话", go: "打开", run: () => openSquadsDialog() },
    desk: { desc: "提交问题工单，查看处理进度", go: "打开", run: () => openDeskDialog() },
  };

  function featureCenterIcon(item) {
    if (item.icon_data) return `<img src="${esc(item.icon_data)}" alt="">`;
    if (item.icon_key && document.getElementById(`i-${item.icon_key}`)) {
      return `<svg><use href="#i-${esc(item.icon_key)}"/></svg>`;
    }
    return `<svg><use href="#i-grid"/></svg>`;
  }

  function syncFeatureCenter() {
    const count = $("#frontEnabledCount");
    const allBtn = $("#allFeaturesBtn");
    if (!Array.isArray(S.frontFeatures)) {
      if (count) count.textContent = "·";
      return;
    }
    const items = S.frontFeatures;
    if (count) count.textContent = String(items.length);
    if (allBtn) allBtn.hidden = !items.length;
    renderFeatureCenter();
  }

  function renderFeatureCenter() {
    const grid = $("#fcGrid");
    const summary = $("#fcSummary");
    if (!grid) return;
    const items = Array.isArray(S.frontFeatures) ? S.frontFeatures : [];
    if (summary) {
      summary.textContent = items.length
        ? `${items.length} 项已启用 · 未启用功能不在此处显示`
        : "当前没有已启用的前台功能。";
    }
    if (!items.length) {
      grid.innerHTML = `<div class="fc-empty">还没有启用任何功能，请联系管理员在控制台打开。</div>`;
      return;
    }
    grid.innerHTML = items.map((item) => {
      const meta = FEATURE_CENTER_META[item.key] || { desc: "打开该功能", go: "打开" };
      const tone = esc(item.icon_tone || "gray");
      return `<button class="fc-item" type="button" data-feature-run="${esc(item.key)}">`
        + `<span class="fc-ic ${tone}">${featureCenterIcon(item)}</span>`
        + `<span class="fc-copy"><b>${esc(item.name)}</b><small>${esc(meta.desc)}</small></span>`
        + `<span class="fc-go">${esc(meta.go)} ›</span>`
        + `</button>`;
    }).join("");
  }

  function openFeatureCenter() {
    if (!Array.isArray(S.frontFeatures)) {
      toast("功能配置还在加载，请稍等");
      return;
    }
    renderFeatureCenter();
    const modal = $("#featureCenter");
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add("feature-sheet-open");
    const first = modal.querySelector("[data-feature-run]");
    if (first) first.focus({ preventScroll: true });
  }

  function closeFeatureCenter() {
    const modal = $("#featureCenter");
    if (modal) modal.hidden = true;
    document.body.classList.remove("feature-sheet-open");
  }

  function frontOn(key) {
    if (!S.frontFeatures) return true;
    return S.frontFeatures.some((x) => x.key === key);
  }

  function paintFrontIcon(el, item) {
    if (!item) return;
    let slot = el.querySelector(":scope > .front-icon-slot");
    if (!slot) {
      const svg = el.querySelector(":scope > svg");
      if (!svg) return;
      slot = document.createElement("span");
      slot.className = "front-icon-slot";
      slot.dataset.defaultSvg = svg.outerHTML;
      svg.replaceWith(slot);
    }
    if (item.icon_data) {
      slot.innerHTML = `<img src="${esc(item.icon_data)}" alt="">`;
    } else if (item.icon_key && document.getElementById("i-" + item.icon_key)) {
      slot.innerHTML = `<svg><use href="#i-${esc(item.icon_key)}"/></svg>`;
    } else {
      slot.innerHTML = slot.dataset.defaultSvg || "";
    }
  }

  function applyFrontFeatures() {
    const map = new Map((S.frontFeatures || []).map((x) => [x.key, x]));
    document.querySelectorAll("[data-front]").forEach((el) => {
      const key = el.dataset.front;
      const on = !S.frontFeatures || map.has(key);
      el.toggleAttribute("data-front-off", !on);
      if (on && map.get(key)) paintFrontIcon(el, map.get(key));
      else if (!on && el.querySelector(":scope > .front-icon-slot")) {
        const slot = el.querySelector(":scope > .front-icon-slot");
        slot.innerHTML = slot.dataset.defaultSvg || "";
      }
    });
    const sideTools = document.querySelector(".side-tools");
    if (sideTools) sideTools.hidden = !sideTools.querySelector(":scope > button:not([data-front-off])");
    if (!frontOn("workbench") && $("#workbenchDrawer") && !$("#workbenchDrawer").hidden) closeWorkbench();
    if (!frontOn("skills")) {
      S.skill = null;
      S.lastSkill = null;
      if ($("#skillBtnLabel")) $("#skillBtnLabel").textContent = "技能";
      if ($("#skillBtn")) $("#skillBtn").classList.remove("active");
      renderSkillMenu();
      if (S.wbTab === "caps" && $("#workbenchDrawer") && !$("#workbenchDrawer").hidden) setWbTab("overview");
    }
    if (!frontOn("web") && S.web) setWeb(false);
    if (!frontOn("docgen") && S.outputFormat) {
      setOutputFormat("", true);
      S.lastOutputFormat = "";
    }
    if (!frontOn("library") && S.librarySelected.length) {
      S.librarySelected = [];
      updateLibBadge();
    }
    if (!frontOn("attach") && S.attachments.length) {
      S.attachments = [];
      renderAttachments();
    }
    if (!frontOn("schedule") && S.wbTab === "tasks" && $("#workbenchDrawer") && !$("#workbenchDrawer").hidden) setWbTab("overview");
    if (!frontOn("files") && S.wbTab === "files" && $("#workbenchDrawer") && !$("#workbenchDrawer").hidden) setWbTab("overview");
    const tabFeature = FRONT_TAB_FEATURE[S.drawerTab || ""];
    if (tabFeature && !frontOn(tabFeature)) selectDrawerTab("account");
    if ((!frontOn("collab") || !frontOn("desk")) && $("#collabModal") && !$("#collabModal").hidden) {
      $("#collabModal").hidden = true;
    }
    syncFeatureCenter();
    renderAnnouncement();
  }

  async function loadFrontFeatures() {
    if (!S.user) return;
    try {
      const d = await api("/api/front/features");
      S.frontFeatures = d.items || [];
      S.frontRevision = Number(d.revision || 0);
    } catch {
      if (!S.frontFeatures) S.frontFeatures = null;
    }
    S.frontLastSync = Date.now();
    applyFrontFeatures();
  }

  async function syncFrontFeatures() {
    if (!S.user || document.hidden) return;
    if (Date.now() - (S.frontLastSync || 0) < 5000) return;
    const rev = S.frontRevision;
    await loadFrontFeatures();
    if (rev && S.frontRevision !== rev) applyFrontFeatures();
  }

  /* ------------------------------------------------------------------ 附件 */
  function fmtBytes(n) {
    const size = Number(n) || 0;
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  function renderAttachments() {
    const box = $("#attachList");
    if (!box) return;
    box.hidden = !S.attachments.length;
    box.innerHTML = S.attachments.map((f) => `
      <div class="attach-card">
        ${f.kind === "image"
          ? `<img src="${esc(f.url)}" alt="${esc(f.name)}">`
          : `<span class="attach-file-ico"><svg><use href="#i-file"/></svg></span>`}
        <span class="attach-meta"><b>${esc(f.name)}</b><span>${FILE_KINDS[f.kind] || "文件"} · ${fmtBytes(f.size)}</span></span>
        <button class="attach-remove" type="button" data-remove-att="${f.id}" title="移除"><svg><use href="#i-close"/></svg></button>
      </div>`).join("");
  }

  async function removeAttachment(id) {
    S.attachments = S.attachments.filter((f) => Number(f.id) !== Number(id));
    renderAttachments();
    try {
      await fetch(`/api/chat/files/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": cookie("wb_csrf") },
      });
    } catch {}
  }

  async function clearPendingAttachments(removeRemote = true) {
    const items = S.attachments.slice();
    S.attachments = [];
    renderAttachments();
    if (!removeRemote) return;
    await Promise.all(items.map((f) => fetch(`/api/chat/files/${f.id}`, {
      method: "DELETE", credentials: "same-origin",
      headers: { "X-CSRF-Token": cookie("wb_csrf") },
    }).catch(() => {})));
  }

  async function uploadFiles(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    if (files.length + S.attachments.length > 5) return toast("一条消息最多带 5 个附件");
    const seq = S.openedConversation;
    let libAdded = 0;
    S.uploading = true;
    $("#attachBtn").disabled = true;
    for (const file of files) {
      if (file.size > 20 * 1024 * 1024) { toast(`${file.name} 超过 20MB`); continue; }
      toast(`正在上传 ${file.name}…`);
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        const res = await fetch("/api/chat/files", {
          method: "POST", credentials: "same-origin",
          headers: { "X-CSRF-Token": cookie("wb_csrf") }, body: fd,
        });
        if (res.status === 401) {
          S.uploading = false;
          $("#attachBtn").disabled = false;
          showAuth();
          return;
        }
        const raw = await res.text();
        let data = null;
        try { data = JSON.parse(raw); } catch {}
        if (!res.ok) throw new Error(errorText(data, `上传失败（${res.status}）`));
        if (seq !== S.openedConversation) {
          fetch(`/api/chat/files/${data.id}`, {
            method: "DELETE", credentials: "same-origin",
            headers: { "X-CSRF-Token": cookie("wb_csrf") },
          }).catch(() => {});
          continue;
        }
        S.attachments.push(data);
        renderAttachments();
        if (data.library && data.library.status === "added") {
          libAdded += 1;
          S.libraryLoadedAt = 0;
        }
      } catch (e) {
        toast(e.message || "上传失败");
      }
    }
    if (libAdded) toast(`已同时加入个人资料库 ${libAdded} 个文件，可在聊天框「资料库」中反复选用`);
    S.uploading = false;
    $("#attachBtn").disabled = false;
    $("#fileInput").value = "";
  }

  /* ------------------------------------------------------------------ 会话列表 */
  async function loadConversations(q = "") {
    try {
      const d = await api("/api/chat/conversations" + (q ? `?q=${encodeURIComponent(q)}` : ""));
      S.conversations = d.items || [];
      renderConversations();
    } catch (e) {
      if (!String(e.message).includes("登录")) toast(e.message);
    }
  }

  function renderConversations() {
    const box = $("#convList");
    if (!S.conversations.length) {
      box.innerHTML = `<div class="conv-empty">还没有对话。<br>点上方「新建对话」开始。</div>`;
      return;
    }
    box.innerHTML = S.conversations.map((c) => `
      <div class="conv-item ${Number(c.id) === Number(S.cid) ? "active" : ""}" data-cid="${c.id}" tabindex="0" role="button">
        <svg class="conv-ico"><use href="#i-spark"/></svg>
        <span class="conv-text"><b>${esc(c.title || "新对话")}</b><small>${relTime(c.updated_at)}</small></span>
        <span class="conv-tools">
          <button class="conv-act" data-rnamecid="${c.id}" title="重命名"><svg><use href="#i-edit"/></svg></button>
          <button class="conv-act danger" data-delcid="${c.id}" title="删除"><svg><use href="#i-trash"/></svg></button>
        </span>
      </div>`).join("");
  }

  const CHAT_PATH_RE = /^\/chat\/(\d+)\/?$/;

  function chatIdFromUrl() {
    const m = location.pathname.match(CHAT_PATH_RE);
    return m ? Number(m[1]) : null;
  }

  function syncChatUrl(id, push = false) {
    const target = id ? `/chat/${Number(id)}` : "/";
    if (location.pathname === target) return;
    const state = { chatId: id ? Number(id) : null };
    if (push) history.pushState(state, "", target);
    else history.replaceState(state, "", target);
  }

  function newChat(syncUrl = true) {
    if (S.stream && S.abort) S.abort.abort();
    S.cid = null;
    S.messages = [];
    S.lastUserMessage = "";
    S.lastSkill = null;
    S.convSystemPrompt = "";
    S.openedConversation++;
    clearPendingAttachments();
    setSkill(null);
    $("#messages").innerHTML = "";
    $("#welcome").hidden = false;
    $("#currentTitle").textContent = "新对话";
    $("#currentMeta").textContent = "开始一段新的对话";
    $("#convSearch").value = "";
    renderConversations();
    if (S.prefs) $("#setSystemPrompt").value = S.prefs.systemPrompt || "";
    $("#sysPromptScope").textContent = "（用于新对话）";
    $("#messageInput").value = "";
    autoResizeInput();
    if (syncUrl) syncChatUrl(null);
    renderShareButton();
    if (window.innerWidth <= 900) closeSidebar();
    setTimeout(() => $("#messageInput").focus(), 80);
  }

  async function openConversation(id, syncUrl = true) {
    if (!id) return;
    if (S.stream && S.abort) S.abort.abort();
    S.openedConversation++;
    const seq = S.openedConversation;
    S.cid = Number(id);
    if (syncUrl) syncChatUrl(S.cid, true);
    S.lastUserMessage = "";
    S.lastSkill = null;
    S.convSystemPrompt = "";
    clearPendingAttachments();
    setSkill(null);
    renderConversations();
    $("#welcome").hidden = true;
    $("#messages").innerHTML = `<div class="empty-line">加载对话中…</div>`;
    try {
      const d = await api(`/api/chat/conversations/${id}/messages`);
      if (seq !== S.openedConversation) return;
      S.messages = d.items || [];
      S.convSystemPrompt = (d.conversation && d.conversation.system_prompt) || "";
      if (d.conversation && d.conversation.agent_id) {
        S.agentId = Number(d.conversation.agent_id) || null;
        renderAgentPicker();
      }
      $("#currentTitle").textContent = (d.conversation && d.conversation.title) || "对话";
      $("#currentMeta").textContent = `${S.messages.length} 条消息 · ${relTime(d.conversation && d.conversation.updated_at)}`;
      $("#messages").innerHTML = "";
      for (const m of S.messages) {
        if (m.role === "user") {
          const meta = typeof m.meta === "object" ? (m.meta || {}) : {};
          S.lastUserMessage = m.content || "";
          S.lastSkill = meta.skill && meta.skill.name ? meta.skill : null;
          S.lastWeb = !!meta.web;
          addUserMessage(m.content || "", false, meta);
        } else if (m.role === "assistant") {
          const meta = typeof m.meta === "object" ? (m.meta || {}) : {};
          addAssistantMessage({
            content: m.content || "",
            reasoning: m.reasoning || "",
            model: meta.model || "",
            agent: meta.agent || null,
            kb: meta.kb || [],
            web: meta.web || null,
            files: meta.files || [],
            actions: true,
          });
        }
      }
      const last = S.messages[S.messages.length - 1];
      if (last && last.role === "user") S.lastUserMessage = last.content || "";
      if (S.prefs) {
        $("#setSystemPrompt").value = S.convSystemPrompt;
        $("#sysPromptScope").textContent = "（当前对话）";
      }
      scrollBottom(true);
      renderShareButton();
      if (window.innerWidth <= 900) closeSidebar();
    } catch (e) {
      if (seq !== S.openedConversation) return;
      $("#messages").innerHTML = `<div class="empty-line">${esc(e.message)}</div>`;
    }
  }

  async function renameConversation(id) {
    const conv = S.conversations.find((x) => Number(x.id) === Number(id));
    if (!conv) return toast("没有找到这段对话");
    const row = $(`#convList .conv-item[data-cid="${id}"]`);
    const titleEl = row && $(".conv-text b", row);
    if (!titleEl) return;
    const current = conv.title || "新对话";
    const input = document.createElement("input");
    input.className = "conv-rename";
    input.value = current;
    input.maxLength = 60;
    titleEl.replaceWith(input);
    input.focus();
    input.select();
    let settled = false;
    const finish = async (save) => {
      if (settled) return;
      settled = true;
      const name = input.value.trim();
      if (!save || !name || name === current) {
        await loadConversations($("#convSearch").value.trim());
        return;
      }
      try {
        await api(`/api/chat/conversations/${id}`, { method: "PATCH", body: { title: name } });
        if (Number(id) === Number(S.cid)) $("#currentTitle").textContent = name;
        await loadConversations($("#convSearch").value.trim());
        toast("已重命名");
      } catch (e) {
        toast(e.message);
        await loadConversations($("#convSearch").value.trim());
      }
    };
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); ev.stopPropagation(); finish(true); }
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
    input.addEventListener("click", (ev) => ev.stopPropagation());
  }

  async function renameCurrent() {
    if (!S.cid) return toast("当前还没有对话，发消息后自动创建");
    return renameConversation(S.cid);
  }

  async function deleteConversation(id) {
    if (!id) return;
    try {
      await api(`/api/chat/conversations/${id}`, { method: "DELETE" });
      if (Number(id) === Number(S.cid)) newChat();
      await loadConversations($("#convSearch").value.trim());
      toast("对话已删除");
    } catch (e) { toast(e.message); }
  }

  function armDeleteButton(btn) {
    if (!btn) return false;
    if (btn.dataset.armed === "1") return true;
    $$("#convList .conv-act.armed").forEach((old) => {
      old.classList.remove("armed");
      old.dataset.armed = "";
      old.title = "删除";
      const oldRow = old.closest(".conv-item");
      if (oldRow && oldRow.dataset.wasText) {
        const small = $(".conv-text small", oldRow);
        if (small) small.textContent = oldRow.dataset.wasText;
      }
    });
    const row = btn.closest(".conv-item");
    const small = row && $(".conv-text small", row);
    if (small) {
      row.dataset.wasText = small.textContent;
      small.textContent = "再点一次删除";
    }
    btn.classList.add("armed");
    btn.dataset.armed = "1";
    btn.title = "再点一次删除";
    clearTimeout(armDeleteButton._t);
    armDeleteButton._t = setTimeout(() => {
      btn.classList.remove("armed");
      btn.dataset.armed = "";
      btn.title = "删除";
      if (row && row.dataset.wasText && small) small.textContent = row.dataset.wasText;
    }, 3200);
    return false;
  }

  /* ------------------------------------------------------------------ 消息渲染 */
  function addUserMessage(text, animate = true, meta = {}) {
    $("#welcome").hidden = true;
    const atts = Array.isArray(meta.attachments) ? meta.attachments : [];
    const skill = meta.skill && meta.skill.name ? meta.skill : null;
    const agent = meta.agent && meta.agent.name ? meta.agent : null;
    const row = document.createElement("div");
    row.className = "msg msg-user";
    const skillHtml = skill ? `<div class="msg-skill">技能 · ${esc(skill.name)}</div>` : "";
    const agentHtml = agent ? `<div class="msg-agent">${esc(agent.avatar || "🤖")} ${esc(agent.name)}</div>` : "";
    const webHtml = meta.web ? `<div class="msg-web"><svg><use href="#i-search"/></svg>联网检索</div>` : "";
    const fmtHtml = meta.output_format && OUT_FORMATS[meta.output_format]
      ? `<div class="msg-web"><svg><use href="#i-file"/></svg>${esc(OUT_FORMATS[meta.output_format])}</div>` : "";
    const filesHtml = atts.length
      ? `<div class="msg-files">${atts.map((f) => `<span class="msg-file"><svg><use href="#i-file"/></svg><span>${esc(f.name || "附件")}</span></span>`).join("")}</div>`
      : "";
    row.innerHTML = `<div class="bubble">${agentHtml}${skillHtml}${webHtml}${fmtHtml}${filesHtml}<div class="msg-text">${esc(text)}</div></div>`;
    if (!animate) row.style.animation = "none";
    $("#messages").appendChild(row);
    scrollBottom(true);
    return row;
  }

  function addAssistantMessage(opts = {}) {
    $("#welcome").hidden = true;
    const agent = opts.agent && opts.agent.name ? opts.agent : null;
    const row = document.createElement("div");
    row.className = "msg msg-assistant";
    row.innerHTML = `
      <div class="msg-avatar${agent ? " has-agent" : ""}">${esc(agent ? (agent.avatar || "AI") : "AI")}</div>
      <div class="body">
        <div class="msg-author"><b>${esc(agent ? agent.name : "AI 助手")}</b>${agent ? '<span class="msg-author-tag">智能体</span>' : ""}</div>
        <details class="reasoning" ${opts.reasoning ? "" : "hidden"}><summary>思考过程</summary><pre></pre></details>
        <div class="msg-text ${opts.streaming ? "streaming" : ""}"></div>
        <div class="kb-tags" hidden></div>
        <div class="web-tags" hidden></div>
        <div class="msg-files" hidden></div>
        <div class="msg-actions"></div>
      </div>`;
    const textEl = $(".msg-text", row);
    const reasonEl = $(".reasoning pre", row);
    if (opts.reasoning) reasonEl.textContent = opts.reasoning;
    if (opts.content && !opts.streaming) {
      textEl.classList.remove("streaming");
      textEl.innerHTML = renderMarkdown(opts.content);
    } else if (opts.streaming) {
      textEl.innerHTML = `<span class="typing"><i></i><i></i><i></i></span>`;
    }
    if (opts.kb && opts.kb.length) renderKbTags(row, opts.kb);
    if (opts.web) renderWebTags(row, opts.web);
    if (opts.files && opts.files.length) renderFiles(row, opts.files);
    if (opts.actions) renderActions(row, opts.content || "");
    $("#messages").appendChild(row);
    scrollBottom(true);
    return row;
  }

  function setAssistantText(row, text, streaming) {
    const el = $(".msg-text", row);
    if (!el) return;
    if (streaming) {
      el.classList.add("streaming");
      el.innerHTML = renderMarkdown(text, { streaming: true });
    } else {
      el.classList.remove("streaming");
      el.innerHTML = renderMarkdown(text);
    }
  }

  function setAssistantReasoning(row, text) {
    if (!text) return;
    const box = $(".reasoning", row);
    const pre = $(".reasoning pre", row);
    if (box) box.hidden = false;
    if (pre) pre.textContent = text;
  }

  function renderKbTags(row, names) {
    const box = $(".kb-tags", row);
    if (!box || !names || !names.length) return;
    box.hidden = false;
    box.innerHTML = names.map((x) => `<span>知识库 · ${esc(x)}</span>`).join("");
  }

  function renderWebTags(row, web) {
    const box = $(".web-tags", row);
    if (!box || !web) return;
    if (web.skipped) {
      box.hidden = false;
      box.innerHTML = `<span class="web-skip"><svg><use href="#i-search"/></svg>联网 · 已跳过：${esc(web.skipped)}</span>`;
      return;
    }
    const sources = Array.isArray(web.sources) ? web.sources : [];
    if (web.error && !sources.length) {
      box.hidden = false;
      box.innerHTML = `<span class="web-fail">联网 · ${esc(web.error)}</span>`;
      return;
    }
    if (!sources.length) return;
    box.hidden = false;
    const q = web.query ? `检索词：${web.query}` : "联网来源";
    const label = web.query ? `联网 · ${web.query}` : "联网来源";
    const links = sources.map((s, i) => {
      const href = s.url || "";
      if (!/^(https?:\/\/|\/)/i.test(href)) {
        const text = `${i + 1}. ${s.title || "来源"}`;
        return `<span class="web-link" title="${esc(s.title || "")}">${esc(text)}</span>`;
      }
      const short = `${i + 1}. ${s.title || s.url}`;
      return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="${esc(s.url)}">${esc(short)}</a>`;
    }).join("");
    box.innerHTML = `<span class="web-label" title="${esc(q)}"><svg><use href="#i-search"/></svg>${esc(label)}</span>${links}`;
  }

  function fileExpiry(f, nowMs = Date.now()) {
    const exp = Number(f && f.expires_at) || 0;
    const deleted = Number(f && f.deleted_at) || 0;
    if ((f && f.cleaned) || deleted > 0) {
      return { state: "cleaned", download: false, badge: "已清理",
        text: `已于 ${f.deleted_text || fmtTime(deleted)} 自动清理`, title: "文件已到期并被自动清理，请重新生成" };
    }
    if ((f && f.expired) || (exp > 0 && exp * 1000 <= nowMs)) {
      return { state: "expired", download: false, badge: "已过期",
        text: `已于 ${f.expires_text || fmtTime(exp)} 到期`, title: "文件已过期，下载入口已关闭" };
    }
    if (!exp) return { state: "none", download: true, badge: "", text: "", title: "" };
    const days = Math.max(0, Math.ceil((exp * 1000 - nowMs) / 86400000));
    const warn = Number(f.warn_days) || 3;
    if (days <= warn) {
      return { state: "soon", download: true, badge: `剩 ${days} 天`,
        text: `仅剩 ${days} 天 · ${f.expires_text || fmtTime(exp)} 到期`, title: "到期后会自动删除，请尽快下载" };
    }
    return { state: "active", download: true, badge: "",
      text: `有效至 ${f.expires_text || fmtTime(exp)} · 剩 ${days} 天`, title: "" };
  }

  function renderFiles(row, files) {
    const box = $(".msg-files", row);
    if (!box || !files || !files.length) return;
    box.hidden = false;
    box.innerHTML = files.map((f) => {
      const kind = (f.kind || "docx").toLowerCase();
      const expiry = fileExpiry(f);
      const body = `<span class="file-ico">${esc(f.short || kind.toUpperCase())}</span>
        <span class="file-meta"><b>${esc(f.name)}</b><span>${esc(f.label || "文件")} · ${fmtBytes(Number(f.size) || 0)}</span>
        ${expiry.text ? `<span class="file-expiry">${esc(expiry.text)}</span>` : ""}</span>`;
      if (!expiry.download) {
        return `<div class="file-card ${expiry.state}" title="${esc(expiry.title)}">${body}
          <span class="file-dl">${esc(expiry.badge)}</span></div>`;
      }
      return `<a class="file-card ${expiry.state}" data-kind="${esc(kind)}" href="${esc(f.url)}" download="${esc(f.name)}" title="${esc(expiry.title || `下载 ${f.name}`)}">${body}
        <span class="file-dl"><svg><use href="#i-download"/></svg>下载</span>
      </a>`;
    }).join("");
  }

  function renderActions(row, content) {
    const box = $(".msg-actions", row);
    if (!box) return;
    box.innerHTML = `
      <button type="button" data-copy-text>${'<svg><use href="#i-copy"/></svg>'}复制</button>
      <button type="button" data-regen>${'<svg><use href="#i-refresh"/></svg>'}重新生成</button>`;
    box.dataset.content = content;
  }

  function scrollBottom(force = false) {
    const sc = $("#chatScroll");
    if (!sc) return;
    const near = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160;
    const go = () => { sc.scrollTop = sc.scrollHeight; };
    if (force || near) {
      go();
      if (force) requestAnimationFrame(() => requestAnimationFrame(go));
    }
  }

  /* 轻量 Markdown：先转义，再处理常用语法；不执行 HTML/脚本。 */
  function mdLang(lang) {
    const key = String(lang || "").toLowerCase();
    const map = {
      py: "Python", python: "Python", js: "JavaScript", javascript: "JavaScript",
      ts: "TypeScript", typescript: "TypeScript", sh: "Shell", bash: "Shell", shell: "Shell",
      ps1: "PowerShell", powershell: "PowerShell", json: "JSON", html: "HTML",
      css: "CSS", sql: "SQL", yml: "YAML", yaml: "YAML", md: "Markdown",
      java: "Java", go: "Go", rust: "Rust", c: "C", cpp: "C++", csharp: "C#",
    };
    return map[key] || (key ? key.toUpperCase() : "代码");
  }

  function mdCode(lang, code, open = false) {
    const body = String(code || "").replace(/^\n+|\n+$/g, "");
    const copy = open ? "" : `<button type="button" class="md-code-copy" data-copy-code><svg><use href="#i-copy"/></svg>复制</button>`;
    return `<div class="md-code${open ? " is-open" : ""}"><div class="md-code-head"><span>${esc(mdLang(lang))}</span>${copy}</div><pre><code>${esc(body)}</code></pre></div>`;
  }

  function mdInline(text) {
    return text
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  }

  function renderMarkdown(src, opts = {}) {
    let text = String(src || "");
    const blocks = [];
    text = text.replace(/```([a-zA-Z0-9_+.-]*)[ \t]*\r?\n?([\s\S]*?)```/g, (_, lang, code) => {
      const i = blocks.length;
      blocks.push(mdCode(lang, code));
      return `\n\u0000BLOCK${i}\u0000\n`;
    });
    if (opts.streaming) {
      const openAt = text.lastIndexOf("```");
      if (openAt >= 0) {
        const tail = text.slice(openAt + 3);
        const lang = (tail.match(/^[a-zA-Z0-9_+.-]*/) || [""])[0];
        const code = tail.slice(lang.length).replace(/^\r?\n/, "");
        const i = blocks.length;
        blocks.push(mdCode(lang, code, true));
        text = `${text.slice(0, openAt)}\n\u0000BLOCK${i}\u0000\n`;
      }
    }
    const work = esc(text);
    const lines = work.split(/\r?\n/);
    const out = [];
    let list = null;
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    const isTableSep = (s) => /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(s);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trimEnd();
      if (!line.trim()) { closeList(); continue; }
      const codeBlock = line.match(/^\u0000BLOCK(\d+)\u0000$/);
      if (codeBlock) {
        closeList();
        out.push(blocks[Number(codeBlock[1])] || "");
        continue;
      }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        closeList();
        const n = h[1].length;
        out.push(`<h${n}>${mdInline(h[2])}</h${n}>`);
        continue;
      }
      if (/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
        closeList();
        out.push("<hr>");
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        closeList();
        const cells = (s) => s.trim().replace(/^\||\|$/g, "").split("|").map((x) => x.trim());
        const head = cells(line);
        const rows = [];
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          rows.push(cells(lines[i]));
          i++;
        }
        i--;
        out.push(`<div class="md-table-wrap"><table><thead><tr>${head.map((c) => `<th>${mdInline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${head.map((_, c) => `<td>${mdInline(r[c] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ul || ol) {
        const type = ul ? "ul" : "ol";
        if (list !== type) { closeList(); out.push(`<${type}>`); list = type; }
        out.push(`<li>${mdInline((ul || ol)[1])}</li>`);
        continue;
      }
      if (/^\s*&gt;\s+/.test(line)) {
        closeList();
        out.push(`<blockquote>${mdInline(line.replace(/^\s*&gt;\s+/, ""))}</blockquote>`);
        continue;
      }
      closeList();
      out.push(`<p>${mdInline(line)}</p>`);
    }
    closeList();
    const html = out.join("").replace(/\u0000BLOCK(\d+)\u0000/g, (_, i) => blocks[Number(i)] || "");
    return `<div class="md">${html}${opts.streaming ? '<span class="md-caret" aria-hidden="true"></span>' : ""}</div>`;
  }

  /* ------------------------------------------------------------------ 生成 */
  function streamingOn(on) {
    $("#sendBtn").hidden = on;
    $("#stopBtn").hidden = !on;
    $("#messageInput").disabled = on;
    $("#modelSelect").disabled = on && false;
    $("#composer").classList.toggle("busy", on);
  }

  function currentModel() {
    const m = selectedModel();
    return (m && m.key) || $("#modelSelect").value || "";
  }

  async function sendMessage(text, opts = {}) {
    if (S.stream) return toast("正在生成，请稍候");
    if (S.uploading) return toast("文件还在上传，请稍候");
    if (!S.user) return showAuth();
    if (!S.models.length) return toast("当前账号没有可用模型，请联系管理员分配");
    let model = selectedModel();
    if (!model) return toast("请先选择模型");
    if (!modelRunnable(model)) {
      await ensureModelLoaded(model.key);
      model = selectedModel();
      if (!modelRunnable(model)) return toast("模型尚未就绪，请重新选择");
    }
    let message = String(text || "").trim();
    const regen = !!opts.regenerate;
    const attachments = regen ? [] : S.attachments.slice();
    const skill = regen ? (S.lastSkill || S.skill) : S.skill;
    const web = regen ? S.lastWeb : S.web;
    const outFormat = regen ? (S.lastOutputFormat || S.outputFormat) : S.outputFormat;
    const agent = S.agentId ? (S.agents.find((a) => Number(a.id) === Number(S.agentId)) || null) : null;
    if (!message && attachments.length) message = "请阅读这些附件并总结要点。";
    if (!message) return;

    if (!regen) {
      S.lastUserMessage = message;
      addUserMessage(message, true, { attachments, skill, web, agent, output_format: outFormat });
    }
    $("#welcome").hidden = true;
    $("#messageInput").value = "";
    autoResizeInput();

    const assistant = addAssistantMessage({ streaming: true, model: currentModel(), agent });
    if (outFormat) {
      setAssistantText(assistant, `正在整理 ${OUT_FORMATS[outFormat]}…`, true);
    } else if (web) {
      const textEl0 = $(".msg-text", assistant);
      if (textEl0) setAssistantText(assistant, "正在联网检索网页…", true);
    }
    const textEl = $(".msg-text", assistant);
    let content = "";
    let reasoning = "";
    let done = false;
    let stopped = false;
    let fileMode = !!outFormat;
    let fileDone = false;
    let timer = 0;
    let pending = false;
    const controller = new AbortController();
    S.abort = controller;
    S.stream = { assistant, controller };

    streamingOn(true);
    const csrf = cookie("wb_csrf");
    const payload = {
      message,
      model: currentModel() || null,
      conversation_id: S.cid || null,
      temperature: Number(S.prefs.temperature) || 0.7,
      max_tokens: Number(S.prefs.maxTokens) || 2048,
      use_kb: !!S.prefs.useKb,
      library_docs: [...S.librarySelected],
      regenerate: regen,
      attachments: attachments.map((f) => f.id),
      skill: skill ? skill.id : null,
      web: !!web,
      agent_id: S.agentId || null,
      output_format: outFormat || null,
    };
    S.lastSkill = skill || null;
    S.lastWeb = !!web;
    S.lastOutputFormat = outFormat || "";
    if (!regen) {
      S.attachments = [];
      renderAttachments();
      setSkill(null);
    }
    if (S.cid) {
      if (S.convSystemPrompt) payload.system_prompt = S.convSystemPrompt;
    } else if (S.prefs.systemPrompt) {
      payload.system_prompt = S.prefs.systemPrompt;
    }

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (res.status === 401) { showAuth(); throw new Error("登录已失效，请重新登录"); }
      if (!res.ok) {
        let data = null;
        const raw = await res.text();
        try { data = JSON.parse(raw); } catch {}
        throw new Error(errorText(data, `请求失败（${res.status}）`));
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      while (true) {
        const { value, done: eof } = await reader.read();
        if (eof) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split(/\r?\n\r?\n/);
        buf = events.pop() || "";
        for (const ev of events) {
          const dataLines = ev.split(/\r?\n/).filter((x) => x.startsWith("data:"));
          if (!dataLines.length) continue;
          const raw = dataLines.map((x) => x.slice(5).trim()).join("\n");
          let evt = null;
          try { evt = JSON.parse(raw); } catch { continue; }
          if (evt.type === "meta") {
            if (evt.conversation_id) {
              const wasNew = !S.cid;
              S.cid = evt.conversation_id;
              syncChatUrl(S.cid);
              renderConversations();
              if (wasNew) {
                $("#currentTitle").textContent = message.replace(/\n/g, " ").slice(0, 30) || "新对话";
                $("#currentMeta").textContent = "正在生成…";
                updateConversationLater();
              }
            }
            if (evt.kb && evt.kb.length) renderKbTags(assistant, evt.kb);
            if (evt.file_mode) {
              fileMode = true;
              setAssistantText(assistant, `正在整理 ${OUT_FORMATS[evt.output_format] || "文档"}…`, true);
            } else if (evt.web) {
              renderWebTags(assistant, evt.web);
              if (!content) setAssistantText(assistant, "正在生成回答…", true);
            }
          } else if (evt.type === "reasoning") {
            reasoning += evt.text || "";
            setAssistantReasoning(assistant, reasoning);
            scrollBottom(false);
          } else if (evt.type === "delta") {
            content += evt.text || "";
            pending = true;
            if (!timer) {
              timer = setTimeout(() => {
                timer = 0;
                if (pending && S.stream) {
                  pending = false;
                  if (fileMode) {
                    setAssistantText(assistant, `正在排版 ${OUT_FORMATS[outFormat] || "文档"}，已接收 ${content.length} 字…`, true);
                  } else {
                    setAssistantText(assistant, content, true);
                  }
                  scrollBottom(false);
                }
              }, fileMode ? 180 : 60);
            }
          } else if (evt.type === "error") {
            throw new Error(evt.message || "生成失败");
          } else if (evt.type === "done") {
            done = true;
            stopped = !!evt.stopped;
            const files = Array.isArray(evt.files) ? evt.files : [];
            if (files.length) {
              fileDone = true;
              content = evt.summary || `已生成${files[0].label || "文件"}，点击下方卡片下载。`;
              setAssistantText(assistant, content, false);
              renderFiles(assistant, files);
              renderActions(assistant, content);
            } else if (fileMode && evt.file_error) {
              setAssistantText(assistant, content || "（没有返回内容）", false);
              const note = document.createElement("div");
              note.className = "file-note";
              note.textContent = `${evt.file_error}。以上正文可直接复制。`;
              $(".body", assistant).appendChild(note);
              renderActions(assistant, content);
            } else {
              setAssistantText(assistant, content, false);
              renderActions(assistant, content);
            }
            if (evt.ttft_ms) $("#currentMeta").textContent = `首字 ${(evt.ttft_ms / 1000).toFixed(1)}s · ${evt.tokens || 0} tokens`;
            scrollBottom(fileDone);
          }
        }
      }
    } catch (e) {
      if (e.name === "AbortError") {
        stopped = true;
      } else {
        const errBox = document.createElement("div");
        errBox.className = "msg-error";
        errBox.textContent = e.message;
        $(".body", assistant).appendChild(errBox);
        toast(e.message);
      }
    } finally {
      if (timer) clearTimeout(timer);
      if (content) {
        if (!fileDone) setAssistantText(assistant, content, false);
        renderActions(assistant, content);
      } else if (!stopped) {
        setAssistantText(assistant, done ? "（没有返回内容）" : "（生成中断）", false);
      }
      S.stream = null;
      S.abort = null;
      streamingOn(false);
      if (S.cid) {
        updateConversationLater();
        if (stopped) setTimeout(() => openConversation(S.cid), 350);
      }
    }
  }

  function updateConversationLater() {
    clearTimeout(updateConversationLater._t);
    updateConversationLater._t = setTimeout(() => {
      loadConversations($("#convSearch").value.trim());
      if (S.cid) {
        const c = S.conversations.find((x) => Number(x.id) === Number(S.cid));
        if (c && $("#currentTitle").textContent === "新对话") $("#currentTitle").textContent = c.title || "对话";
      }
    }, 220);
  }

  async function regenerate() {
    if (S.stream) return toast("正在生成，请稍候");
    let lastUser = S.lastUserMessage;
    if (!lastUser) {
      const rows = $$("#messages .msg-user .msg-text");
      lastUser = rows.length ? rows[rows.length - 1].textContent : "";
    }
    if (!lastUser) return toast("没有可重新生成的消息");
    const assistants = $$("#messages .msg-assistant");
    const last = assistants[assistants.length - 1];
    if (!last) return toast("最后一条不是模型回复");
    last.remove();
    await sendMessage(lastUser, { regenerate: true });
  }

  function stopStream() {
    if (S.abort) S.abort.abort();
    toast("已停止生成");
  }

  /* ------------------------------------------------------------------ 设置：账号 */
  async function openSettings(tab = "account") {
    $("#settingsDrawer").hidden = false;
    selectDrawerTab(tab);
    loadSessions().catch(() => {});
    if (tab === "api") loadApi().catch((e) => toast(e.message));
  }

  function closeSettings() { $("#settingsDrawer").hidden = true; closeBind(); }

  function selectDrawerTab(tab) {
    const feature = FRONT_TAB_FEATURE[tab];
    if (feature && !frontOn(feature)) tab = "account";
    S.drawerTab = tab;
    $$("#drawerTabs button").forEach((b) => b.classList.toggle("active", b.dataset.dtab === tab));
    $$(".dpanel").forEach((p) => p.classList.toggle("active", p.id === `dpanel-${tab}`));
    if (tab === "account") loadSessions().catch(() => {});
    if (tab === "account") loadIdentities().catch(() => {});
    if (tab === "api") loadApi().catch((e) => toast(e.message));
    if (tab === "chat") applyChatPrefsToUI(true);
    if (tab === "kb") loadMyKb().catch((e) => toast(e.message));
    if (tab === "library") loadMyLibrary().catch((e) => toast(e.message));
    if (tab === "memory") loadMyMemory().catch((e) => toast(e.message));
  }

  /* ------------------------------------------------------------------ 设置：我的知识库 */
  function myKbError(text) {
    const box = $("#myKbError");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function myKbNotice(text) {
    const box = $("#myKbNotice");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function applyMyKbState(d) {
    const personalOn = !!d.personal_enabled;
    const publicOn = !!d.public_enabled;
    $("#myKbToggle").checked = personalOn;
    $("#myKbToggleNote").textContent = personalOn
      ? "已开启。只有勾选下面的来源才会参与对话检索；随时可以关闭。"
      : "默认关闭。开启后才会把个人资料用于当前账号的对话检索，其他账号看不到。";
    $("#myKbUsePublic").checked = publicOn && !!d.use_public;
    $("#myKbUsePublic").disabled = !publicOn;
    $("#myKbPublicHint").textContent = publicOn ? "" : "（管理员已关闭）";
    $("#myKbUsePersonal").checked = personalOn && !!d.use_personal;
    $("#myKbUsePersonal").disabled = !personalOn;
    $("#myKbSourceState").textContent = personalOn ? "可多选" : "先开启个人知识库";
  }

  async function saveMyKbSettings(patch) {
    try {
      const d = await api("/api/my/kb/settings", { method: "POST", body: patch });
      applyMyKbState(d);
      toast("知识库设置已保存");
      return d;
    } catch (e) {
      myKbError(e.message);
      await loadMyKb().catch(() => {});
      throw e;
    }
  }

  function myKbDocsHtml(docs) {
    if (!docs.length) return `<div class="mine-empty">还没有个人文档。上传或粘贴一份资料，之后提问时会优先参考。</div>`;
    return docs.map((d) => `
      <div class="mine-item">
        <div><b title="${esc(d.title)}">${esc(d.title)}</b>
          <span>${esc(d.source || "manual")} · ${Number(d.chars || 0).toLocaleString()} 字 · ${esc(fmtTime(d.created_at))}</span></div>
        <button class="iconbtn small" data-kb-del="${d.id}" title="删除这篇文档"><svg><use href="#i-trash"/></svg></button>
      </div>`).join("");
  }

  async function loadMyKb() {
    const list = $("#myKbList");
    try {
      const d = await api("/api/my/kb");
      $("#myKbStat").textContent = `${d.count || 0} 篇 · ${Number(d.chars || 0).toLocaleString()} 字`;
      $("#myKbCount").textContent = `上限 ${d.max_docs || 200} 篇`;
      applyMyKbState(d);
      list.innerHTML = myKbDocsHtml(d.docs || []);
    } catch (e) {
      list.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function addMyKbText() {
    const title = $("#myKbTitle").value.trim();
    const content = $("#myKbContent").value.trim();
    myKbError("");
    myKbNotice("");
    if (!content) return myKbError("先粘贴正文再添加");
    const finalTitle = title || content.slice(0, 30) || "未命名资料";
    const fd = new FormData();
    fd.append("title", finalTitle);
    fd.append("content", content);
    try {
      const res = await formApi("/api/my/kb/text", fd);
      $("#myKbTitle").value = "";
      $("#myKbContent").value = "";
      myKbNotice(`已加入《${res.title || finalTitle}》：${Number(res.chars || content.length).toLocaleString()} 字，切成 ${res.chunks || 1} 段。`);
      toast("已加入我的知识库");
      await loadMyKb();
    } catch (e) { myKbNotice(""); myKbError(e.message); }
  }

  async function uploadMyKb(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    myKbError("");
    let added = 0;
    const failed = [];
    try {
      for (const [i, file] of files.entries()) {
        myKbNotice(`正在上传 ${i + 1}/${files.length}：《${file.name}》…`);
        const fd = new FormData();
        fd.append("file", file, file.name);
        try {
          await formApi("/api/my/kb/upload", fd);
          added += 1;
        } catch (e) {
          failed.push(`${file.name}：${e.message}`);
        }
      }
      if (added) {
        await loadMyKb();
        toast(added === 1 ? "文件已加入我的知识库" : `已上传 ${added} 个文件到我的知识库`);
      }
      myKbNotice(failed.length
        ? `上传完成：成功 ${added} 个，失败 ${failed.length} 个（${failed.join("；")}）`
        : `上传完成：${added} 个文件已加入我的知识库。`);
    } finally { $("#myKbFile").value = ""; }
  }

  async function searchMyKb() {
    const q = $("#myKbSearch").value.trim();
    const box = $("#myKbResults");
    if (!q) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="mine-empty">检索中…</div>`;
    try {
      const d = await api(`/api/my/kb/search?q=${encodeURIComponent(q)}`);
      const items = d.items || [];
      box.innerHTML = items.length ? items.map((x) => `
        <div class="mine-hit"><b>${esc(x.title)}</b><span>${esc(x.snippet)}</span></div>`).join("")
        : `<div class="mine-empty">个人库里没有匹配的资料。</div>`;
    } catch (e) {
      box.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function deleteMyKb(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.classList.add("warn");
      toast("再点一次确认删除这篇文档");
      setTimeout(() => { btn.dataset.armed = ""; btn.classList.remove("warn"); }, 3000);
      return;
    }
    try {
      await api(`/api/my/kb/${id}`, { method: "DELETE" });
      toast("文档已删除");
      $("#myKbResults").innerHTML = "";
      await loadMyKb();
    } catch (e) { toast(e.message); }
  }

  /* ------------------------------------------------------------------ 设置：我的资料库 */
  function myLibError(text) {
    const box = $("#myLibError");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function myLibNotice(text) {
    const box = $("#myLibNotice");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function applyMyLibState(d) {
    S.libraryState = d;
    const personalOn = !!d.personal_enabled;
    const globalOn = !!d.global_enabled;
    $("#myLibToggle").checked = personalOn;
    $("#myLibToggleNote").textContent = personalOn
      ? "已开启。聊天框「资料库」会列出你勾选来源里的资料，可多选并反复使用。"
      : "默认关闭。开启后才能挑选个人资料；总库还要管理员开启并在下面勾选。";
    $("#myLibUseGlobal").checked = globalOn && !!d.use_global;
    $("#myLibUseGlobal").disabled = !globalOn;
    $("#myLibGlobalHint").textContent = globalOn ? "" : "（管理员未开启）";
    $("#myLibUsePersonal").checked = personalOn && !!d.use_personal;
    $("#myLibUsePersonal").disabled = !personalOn;
    $("#myLibSourceState").textContent = (globalOn || personalOn) ? "可多选" : "先开启资料库";
    $("#myLibStat").textContent = `${d.count || 0} 篇 · ${Number(d.chars || 0).toLocaleString()} 字 · 引用 ${Number(d.uses || 0).toLocaleString()} 次`;
    $("#myLibCount").textContent = `上限 ${d.max_personal_docs || 100} 篇`;
  }

  async function saveMyLibSettings(patch) {
    try {
      const d = await api("/api/my/library/settings", { method: "POST", body: patch });
      applyMyLibState({ ...(S.libraryState || {}), ...d });
      toast("资料库设置已保存");
      S.libraryLoadedAt = 0;
      await loadLibraryPicker().catch(() => {});
      return d;
    } catch (e) {
      myLibError(e.message);
      await loadMyLibrary().catch(() => {});
      throw e;
    }
  }

  function libMetaHtml(d) {
    const folder = String(d.folder || "").trim();
    const tags = String(d.tags || "").split(",").map((x) => x.trim()).filter(Boolean);
    if (!folder && !tags.length) return "";
    return `<div class="lib-meta-line">
      ${folder ? `<span class="lib-meta-chip folder" title="${esc(folder)}">${esc(folder)}</span>` : ""}
      ${tags.map((t) => `<span class="lib-meta-chip">#${esc(t)}</span>`).join("")}
    </div>`;
  }

  function myLibDocsHtml(docs) {
    if (!docs.length) return `<div class="mine-empty">还没有个人资料。上传或粘贴一份资料，聊天时就能反复选用。</div>`;
    return docs.map((d) => `
      <div class="mine-item">
        <div><b title="${esc(d.title)}">${esc(d.title)}</b>
          <span>${esc(d.source || "manual")} · ${Number(d.chars || 0).toLocaleString()} 字 · 引用 ${Number(d.uses || 0)} 次${d.last_used_at ? ` · 最近 ${esc(fmtTime(d.last_used_at))}` : ""}</span>
          ${libMetaHtml(d)}</div>
        <div class="lib-item-actions">
          <button class="btn ghost sm" data-lib-open="${d.id}" title="查看资料正文">查看</button>
          <button class="btn ghost sm" data-lib-org="${d.id}" title="修改文件夹和标签">整理</button>
          <button class="iconbtn small" data-lib-del="${d.id}" title="删除这篇资料"><svg><use href="#i-trash"/></svg></button>
        </div>
      </div>`).join("");
  }

  function fillLibSelect(sel, items, allLabel, keep) {
    const current = keep !== undefined ? keep : sel.value;
    sel.innerHTML = `<option value="">${allLabel}</option>` +
      items.map((x) => `<option value="${esc(x.name)}">${esc(x.name)}（${x.count}）</option>`).join("");
    sel.value = current && items.some((x) => x.name === current) ? current : "";
  }

  function renderMyLibFacets(d) {
    const folders = d.folders || [];
    const tags = d.tags || [];
    fillLibSelect($("#myLibFolderFilter"), folders, "全部文件夹");
    fillLibSelect($("#myLibTagFilter"), tags, "全部标签");
    $("#myLibFolderOptions").innerHTML = folders
      .map((x) => `<option value="${esc(x.name)}"></option>`).join("");
  }

  function renderMyLibDocs() {
    const docs = S.myLibDocs || [];
    const folder = $("#myLibFolderFilter").value;
    const tag = $("#myLibTagFilter").value;
    const shown = docs.filter((d) => {
      if (folder && String(d.folder || "") !== folder) return false;
      if (tag && !String(d.tags || "").split(",").map((x) => x.trim()).includes(tag)) return false;
      return true;
    });
    $("#myLibList").innerHTML = shown.length
      ? myLibDocsHtml(shown)
      : `<div class="mine-empty">${docs.length ? "没有符合当前文件夹或标签的资料。" : "还没有个人资料。上传或粘贴一份资料，聊天时就能反复选用。"}</div>`;
  }

  async function loadMyLibrary() {
    const list = $("#myLibList");
    try {
      const d = await api("/api/my/library");
      applyMyLibState(d);
      S.myLibDocs = d.docs || [];
      renderMyLibFacets(d);
      renderMyLibDocs();
    } catch (e) {
      list.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  function openMyLibOrg(id) {
    const d = (S.myLibDocs || []).find((x) => String(x.id) === String(id));
    if (!d) return toast("这篇资料不在当前列表里，先刷新资料再整理");
    S.myLibOrgId = d.id;
    $("#myLibOrgTitle").value = d.title || "";
    $("#myLibOrgFolder").value = d.folder || "";
    $("#myLibOrgTags").value = d.tags || "";
    $("#myLibOrgError").hidden = true;
    $("#myLibOrg").hidden = false;
    $("#myLibOrg").scrollIntoView({ block: "nearest" });
  }

  function closeMyLibOrg() {
    S.myLibOrgId = null;
    $("#myLibOrg").hidden = true;
    $("#myLibOrgError").hidden = true;
  }

  async function saveMyLibOrg() {
    const id = S.myLibOrgId;
    if (!id) return;
    const title = $("#myLibOrgTitle").value.trim();
    if (!title) {
      $("#myLibOrgError").textContent = "标题不能为空";
      $("#myLibOrgError").hidden = false;
      return;
    }
    try {
      const d = await api(`/api/my/library/${id}`, {
        method: "PATCH",
        body: {
          title,
          folder: $("#myLibOrgFolder").value.trim(),
          tags: $("#myLibOrgTags").value.trim(),
        },
      });
      closeMyLibOrg();
      toast("分类已保存");
      S.libraryLoadedAt = 0;
      await loadMyLibrary();
      await loadLibraryPicker(true).catch(() => {});
      if (d && d.id) openMyLibDoc(d.id).catch(() => {});
    } catch (e) {
      $("#myLibOrgError").textContent = e.message;
      $("#myLibOrgError").hidden = false;
    }
  }

  async function addMyLibText() {
    const title = $("#myLibTitle").value.trim();
    const content = $("#myLibContent").value.trim();
    myLibError("");
    myLibNotice("");
    if (!content) return myLibError("先粘贴正文再添加");
    const finalTitle = title || content.slice(0, 30) || "未命名资料";
    const fd = new FormData();
    fd.append("title", finalTitle);
    fd.append("content", content);
    fd.append("folder", $("#myLibFolder").value.trim());
    fd.append("tags", $("#myLibTags").value.trim());
    try {
      const res = await formApi("/api/my/library/text", fd);
      $("#myLibTitle").value = "";
      $("#myLibContent").value = "";
      myLibNotice(`已加入《${res.title || finalTitle}》：${Number(res.chars || content.length).toLocaleString()} 字，切成 ${res.chunks || 1} 段。`);
      toast("已加入个人资料库");
      S.libraryLoadedAt = 0;
      await loadMyLibrary();
      await loadLibraryPicker().catch(() => {});
    } catch (e) { myLibNotice(""); myLibError(e.message); }
  }

  async function uploadMyLib(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    myLibError("");
    let added = 0;
    const failed = [];
    try {
      for (const [i, file] of files.entries()) {
        myLibNotice(`正在上传 ${i + 1}/${files.length}：《${file.name}》…`);
        const fd = new FormData();
        fd.append("file", file, file.name);
        fd.append("folder", $("#myLibFolder").value.trim());
        fd.append("tags", $("#myLibTags").value.trim());
        try {
          await formApi("/api/my/library/upload", fd);
          added += 1;
        } catch (e) {
          failed.push(`${file.name}：${e.message}`);
        }
      }
      if (added) {
        S.libraryLoadedAt = 0;
        $("#myLibResults").innerHTML = "";
        await loadMyLibrary();
        await loadLibraryPicker().catch(() => {});
        toast(added === 1 ? "文件已加入个人资料库" : `已上传 ${added} 个文件到个人资料库`);
      }
      myLibNotice(failed.length
        ? `上传完成：成功 ${added} 个，失败 ${failed.length} 个（${failed.join("；")}）`
        : `上传完成：${added} 个文件已加入个人资料库。`);
    } finally { $("#myLibFile").value = ""; }
  }

  async function searchMyLib() {
    const q = $("#myLibSearch").value.trim();
    const box = $("#myLibResults");
    if (!q) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="mine-empty">检索中…</div>`;
    try {
      const d = await api(`/api/my/library/search?q=${encodeURIComponent(q)}`);
      const items = d.items || [];
      box.innerHTML = items.length ? items.map((x) => `
        <div class="mine-hit" data-lib-hit="${x.doc_id}" role="button" tabindex="0"><b>${esc(x.title)}</b><span>${esc(x.snippet)}</span></div>`).join("")
        : `<div class="mine-empty">个人资料库里没有匹配的资料。</div>`;
    } catch (e) {
      box.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function openMyLibDoc(id) {
    const d = await api(`/api/my/library/doc/${id}`);
    const cls = [d.folder ? `文件夹：${d.folder}` : "", d.tags ? `标签：${d.tags}` : ""].filter(Boolean).join(" · ");
    $("#myLibViewTitle").textContent = `${d.title} · ${Number(d.chars || 0).toLocaleString()} 字${cls ? ` · ${cls}` : ""}`;
    $("#myLibViewBody").textContent = d.content || "（正文为空）";
    $("#myLibView").hidden = false;
    $("#myLibView").scrollIntoView({ block: "nearest" });
  }

  async function deleteMyLib(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.classList.add("warn");
      toast("再点一次确认删除这篇资料");
      setTimeout(() => { btn.dataset.armed = ""; btn.classList.remove("warn"); }, 3000);
      return;
    }
    try {
      await api(`/api/my/library/${id}`, { method: "DELETE" });
      toast("资料已删除");
      S.librarySelected = S.librarySelected.filter((x) => String(x) !== String(id));
      S.libraryLoadedAt = 0;
      $("#myLibResults").innerHTML = "";
      await loadMyLibrary();
      await loadLibraryPicker().catch(() => {});
    } catch (e) { toast(e.message); }
  }

  /* ------------------------------------------------------------------ 聊天：资料库选择器 */
  function libPickerNotice(text) {
    const box = $("#libPickerNotice");
    if (!box) return;
    box.textContent = text || "";
    box.hidden = !text;
  }

  function updateLibBadge() {
    const count = S.librarySelected.length;
    const badge = $("#libBtnCount");
    badge.hidden = count === 0;
    badge.textContent = String(count);
    $("#libBtn").classList.toggle("active", count > 0);
    $("#libBtn").title = count
      ? `已选 ${count} 篇资料，会随每条消息带入`
      : "从资料库挑选本次要带入的资料";
  }

  function renderLibPicker() {
    const list = $("#libPickerList");
    const items = S.libraryItems || [];
    const max = Number((S.libraryState || {}).max_docs || 10);
    const q = String(S.libraryQuery || "").trim().toLowerCase();
    const folders = (S.libraryState || {}).folders || [];
    const tags = (S.libraryState || {}).tags || [];
    fillLibSelect($("#libPickerFolder"), folders, "全部文件夹");
    fillLibSelect($("#libPickerTag"), tags, "全部标签");
    const folder = $("#libPickerFolder").value;
    const tag = $("#libPickerTag").value;
    const shown = items.filter((d) => {
      if (folder && String(d.folder || "") !== folder) return false;
      if (tag && !String(d.tags || "").split(",").map((x) => x.trim()).includes(tag)) return false;
      return q
        ? `${d.title || ""} ${d.source || ""} ${d.folder || ""} ${d.tags || ""}`.toLowerCase().includes(q)
        : true;
    });
    if (!items.length) {
      const st = S.libraryState || {};
      const effectiveGlobal = !!st.global_enabled && !!st.use_global;
      const effectivePersonal = !!st.personal_enabled && !!st.use_personal;
      let why = "资料库里还没有可用资料。";
      if (!st.global_enabled && !st.personal_enabled) {
        why = "资料库未开启。到「设置 → 资料库」开启个人库；总库需管理员开启。";
      } else if (!effectiveGlobal && !effectivePersonal) {
        why = st.global_enabled
          ? "到「设置 → 资料库」勾选「总资料库」，或开启个人资料并上传。"
          : "到「设置 → 资料库」开启个人资料并上传。";
      } else if (effectivePersonal) {
        why = "个人资料库还没有内容，先到设置里上传一份。";
      }
      list.innerHTML = `<div class="mine-empty">${esc(why)}</div>`;
    } else if (!shown.length) {
      list.innerHTML = `<div class="mine-empty">没有匹配的资料，换个关键词或清除文件夹/标签筛选。</div>`;
    } else {
      list.innerHTML = shown.map((d) => {
        const on = S.librarySelected.some((x) => String(x) === String(d.id));
        const personal = d.scope === "personal";
        const full = !on && S.librarySelected.length >= max;
        return `<label class="lib-pick-row ${on ? "on" : ""} ${full ? "full" : ""}">
          <input type="checkbox" data-lib-pick="${d.id}" ${on ? "checked" : ""} ${full ? "disabled" : ""}>
          <span class="lib-pick-copy"><b>${esc(d.title)}</b><em>${personal ? "个人资料" : "总资料库"} · ${Number(d.chars || 0).toLocaleString()} 字 · 已用 ${Number(d.uses || 0)} 次</em>${libMetaHtml(d)}</span>
        </label>`;
      }).join("");
    }
    $("#libPickerHint").textContent = S.librarySelected.length
      ? `已选 ${S.librarySelected.length} / ${max} 篇，将随每条消息重复带入`
      : `最多可选 ${max} 篇；不选则不使用资料库`;
    updateLibBadge();
  }

  async function loadLibraryPicker(force = false) {
    if (!force && Date.now() - (S.libraryLoadedAt || 0) < 5000) { renderLibPicker(); return; }
    const d = await api("/api/my/library/picker");
    S.libraryState = { ...(S.libraryState || {}), ...d };
    S.libraryItems = d.items || [];
    const available = S.libraryItems.map((x) => String(x.id));
    S.librarySelected = S.librarySelected.filter((id) => available.includes(String(id)));
    S.libraryLoadedAt = Date.now();
    renderLibPicker();
  }

  function setLibMenu(open) {
    $("#libMenu").hidden = !open;
    $("#libBtn").setAttribute("aria-expanded", String(open));
  }

  async function openLibMenu() {
    const opening = $("#libMenu").hidden;
    setLibMenu(opening);
    if (!opening) return;
    setSkillMenu(false);
    libPickerNotice("");
    S.libraryQuery = "";
    $("#libPickerSearch").value = "";
    $("#libPickerFolder").value = "";
    $("#libPickerTag").value = "";
    $("#libPickerList").innerHTML = `<div class="empty-line">读取中…</div>`;
    try {
      await loadLibraryPicker(true);
    } catch (e) {
      $("#libPickerList").innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
      libPickerNotice("读取资料库失败：" + e.message);
    }
  }

  function toggleLibDoc(id, on) {
    const max = Number((S.libraryState || {}).max_docs || 10);
    if (on && S.librarySelected.length >= max) {
      libPickerNotice(`单次最多选 ${max} 篇，先取消一篇再选。`);
      renderLibPicker();
      return;
    }
    libPickerNotice("");
    if (on) {
      if (!S.librarySelected.some((x) => String(x) === String(id))) S.librarySelected.push(Number(id));
    } else {
      S.librarySelected = S.librarySelected.filter((x) => String(x) !== String(id));
    }
    renderLibPicker();
  }

  function clearLibSelection() {
    S.librarySelected = [];
    libPickerNotice("");
    renderLibPicker();
    toast("已清空资料库选择");
  }


  function myMemError(text) {
    const box = $("#myMemError");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function myMemListHtml(items) {
    if (!items.length) return `<div class="mine-empty">还没有记忆。你明确说出的偏好会被自动保存，也可以手动添加。</div>`;
    return items.map((m) => `
      <div class="mine-item">
        <div><b title="${esc(m.content)}">${esc(m.content)}</b>
          <span>${esc(m.source === "auto" ? "自动记住" : "手动添加")} · 命中 ${Number(m.hits || 0)} 次 · ${esc(fmtTime(m.updated_at))}</span></div>
        <button class="iconbtn small" data-mem-del="${m.id}" title="删除这条记忆"><svg><use href="#i-trash"/></svg></button>
      </div>`).join("");
  }

  function myMemNoteText(d) {
    if (!d.global_enabled) {
      return "管理员还没有开启长期记忆总开关。你可以先在这里维护自己的记忆，但总开关打开前不会参与对话。";
    }
    if (!d.user_enabled) return "你还没有开启长期记忆。当前对话只参考最近 20 条消息。";
    return "已开启。对话会参考与你问题相关的记忆，最多 6 条；随时可以关闭，已有条目不会删除。";
  }

  async function loadMyMemory() {
    const list = $("#myMemList");
    try {
      const d = await api("/api/my/memory");
      $("#myMemToggle").checked = !!d.user_enabled;
      $("#myMemStat").textContent = `${Number(d.stats.total || 0)} 条`;
      $("#myMemNote").textContent = myMemNoteText(d);
      list.innerHTML = myMemListHtml(d.items || []);
    } catch (e) {
      list.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function toggleMyMemory(on) {
    myMemError("");
    try {
      const d = await api("/api/my/memory/toggle", { method: "POST", body: { enabled: on } });
      if (on && !d.global_enabled) toast("已保存你的选择，但管理员总开关还未开启");
      else toast(on ? "已开启长期记忆" : "已关闭长期记忆");
      await loadMyMemory();
    } catch (e) {
      $("#myMemToggle").checked = !on;
      myMemError(e.message);
    }
  }

  async function addMyMemory() {
    const content = $("#myMemInput").value.trim();
    myMemError("");
    if (!content) return myMemError("先写下要记住的内容");
    try {
      await api("/api/my/memory/items", { method: "POST", body: { content } });
      $("#myMemInput").value = "";
      toast("已添加记忆");
      await loadMyMemory();
    } catch (e) { myMemError(e.message); }
  }

  async function clearMyMemory(btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "再点一次确认清空";
      setTimeout(() => {
        btn.dataset.armed = "";
        btn.textContent = "清空我的记忆";
      }, 3000);
      return;
    }
    try {
      await api("/api/my/memory/clear", { method: "POST", body: {} });
      btn.dataset.armed = "";
      btn.textContent = "清空我的记忆";
      toast("我的记忆已清空");
      await loadMyMemory();
    } catch (e) { myMemError(e.message); }
  }

  async function deleteMyMemory(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.classList.add("warn");
      toast("再点一次确认删除这条记忆");
      setTimeout(() => { btn.dataset.armed = ""; btn.classList.remove("warn"); }, 3000);
      return;
    }
    try {
      await api(`/api/my/memory/items/${id}`, { method: "DELETE" });
      toast("记忆已删除");
      await loadMyMemory();
    } catch (e) { toast(e.message); }
  }

  async function loadSessions() {
    const box = $("#deviceList");
    try {
      const d = await api("/api/auth/sessions");
      const items = d.items || [];
      box.innerHTML = items.length ? items.map((x) => `
        <div class="device-row">
          <div><b>${esc(shortUA(x.ua))}</b><span>${esc(x.ip || "未知 IP")} · ${esc(fmtTime(x.created_at))}</span></div>
          <span class="badge ${x.current ? "good" : ""}">${x.current ? "当前设备" : "在线"}</span>
        </div>`).join("") : `<div class="empty-line">没有其他登录设备</div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty-line">${esc(e.message)}</div>`;
    }
  }

  async function loadIdentities() {
    const box = $("#identityList");
    if (!box) return;
    try {
      const d = await api("/api/auth/identities");
      const items = d.items || [];
      const providers = (d.providers || []).filter((p) => p.key !== "username");
      const bound = new Set(items.map((i) => i.provider));
      const rows = items.map((i) => `
        <div class="device-row">
          <div><b>${esc(i.label || i.provider)}</b><span>${esc(i.masked || i.provider_uid)} · 已绑定</span></div>
          <span class="badge good">已绑定</span>
        </div>`);
      for (const p of providers) {
        if (bound.has(p.key)) continue;
        const canOtp = (p.key === "phone" || p.key === "email") && p.enabled && p.ready;
        const state = p.enabled
          ? (p.ready ? "已配置" : "配置不完整")
          : "接口已预留";
        rows.push(`
          <div class="device-row">
            <div><b>${esc(p.label)}</b><span>未绑定 · ${esc(state)}</span></div>
            ${canOtp
              ? `<button class="btn ghost sm" type="button" data-bind="${esc(p.key)}">立即绑定</button>`
              : `<span class="badge">${p.enabled && p.ready ? "待接入" : "未启用"}</span>`}
          </div>`);
      }
      box.innerHTML = rows.join("") || `<div class="empty-line">暂无登录方式</div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty-line">${esc(e.message)}</div>`;
    }
  }

  function openBind(channel) {
    if (channel !== "phone" && channel !== "email") return;
    S.bindChannel = channel;
    const form = $("#bindForm");
    form.hidden = false;
    form.reset();
    $("#bindError").hidden = true;
    const isPhone = channel === "phone";
    $("#bindTitle").textContent = isPhone ? "绑定手机号" : "绑定邮箱";
    $("#bindTargetLabel").textContent = isPhone ? "手机号" : "邮箱";
    $("#bindTarget").type = isPhone ? "tel" : "email";
    $("#bindTarget").autocomplete = isPhone ? "tel" : "email";
    $("#bindTarget").placeholder = isPhone ? "请输入手机号" : "请输入邮箱地址";
    $("#bindSend").disabled = false;
    $("#bindSend").textContent = "发送验证码";
    setTimeout(() => $("#bindTarget").focus(), 60);
  }

  function closeBind() {
    S.bindChannel = "";
    const form = $("#bindForm");
    if (form) form.hidden = true;
  }

  function bindTargetValue() {
    return $("#bindTarget").value.trim();
  }

  function bindTargetProblem() {
    const target = bindTargetValue();
    if (!target) return S.bindChannel === "phone" ? "请输入手机号" : "请输入邮箱地址";
    if (S.bindChannel === "phone" && !/^\+?\d{6,20}$/.test(target)) return "手机号格式不正确";
    if (S.bindChannel === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return "邮箱格式不正确";
    return "";
  }

  async function sendBindCode() {
    const err = $("#bindError");
    err.hidden = true;
    const problem = bindTargetProblem();
    if (problem) return bindError(problem);
    const btn = $("#bindSend");
    btn.disabled = true;
    let left = 60;
    btn.textContent = `${left}s 后重发`;
    const timer = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = "重新发送";
      } else {
        btn.textContent = `${left}s 后重发`;
      }
    }, 1000);
    try {
      const data = await api("/api/auth/otp/send", {
        method: "POST",
        body: { channel: S.bindChannel, target: bindTargetValue() },
      });
      toast(data && data.msg ? data.msg : "验证码已发送，请查收");
    } catch (e) {
      clearInterval(timer);
      btn.disabled = false;
      btn.textContent = "发送验证码";
      bindError(e.message);
    }
  }

  async function submitBind(ev) {
    ev.preventDefault();
    const err = $("#bindError");
    err.hidden = true;
    const problem = bindTargetProblem();
    if (problem) return bindError(problem);
    const code = $("#bindCode").value.replace(/\s+/g, "");
    if (!/^\d{6}$/.test(code)) return bindError("请输入 6 位数字验证码");
    const btn = $("#bindSubmit");
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = "绑定中…";
    try {
      const data = await api("/api/auth/identities/bind", {
        method: "POST",
        body: { channel: S.bindChannel, target: bindTargetValue(), code },
      });
      toast(data.msg || "绑定成功");
      closeBind();
      await loadIdentities();
    } catch (e) {
      bindError(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  function bindError(msg) {
    const el = $("#bindError");
    el.textContent = msg;
    el.hidden = false;
  }

  function shortUA(ua) {
    const s = String(ua || "");
    if (!s) return "未知设备";
    if (/Edg\//.test(s)) return "Microsoft Edge";
    if (/Chrome\//.test(s) && !/Chromium/.test(s)) return "Chrome 浏览器";
    if (/Safari\//.test(s) && !/Chrome/.test(s)) return "Safari 浏览器";
    if (/Firefox\//.test(s)) return "Firefox 浏览器";
    if (/Android/.test(s)) return "Android 设备";
    if (/iPhone|iPad/.test(s)) return "iPhone / iPad";
    return s.slice(0, 48);
  }

  async function changePassword(ev) {
    ev.preventDefault();
    const oldp = $("#pwOld").value;
    const newp = $("#pwNew").value;
    const confirm = $("#pwConfirm").value;
    const err = $("#pwError");
    err.hidden = true;
    if (!oldp) return showPwError("请输入当前密码");
    if (newp.length < 8) return showPwError("新密码至少 8 位");
    if (newp !== confirm) return showPwError("两次输入的新密码不一致");
    const btn = $("#pwSubmit");
    btn.disabled = true;
    btn.textContent = "保存中…";
    try {
      await api("/api/auth/password", { method: "POST", body: { old_password: oldp, new_password: newp } });
      $("#pwForm").reset();
      toast("密码已修改，其他设备需要重新登录");
      await loadSessions();
    } catch (e) {
      showPwError(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "保存新密码";
    }
  }

  function showPwError(msg) {
    $("#pwError").textContent = msg;
    $("#pwError").hidden = false;
  }

  async function revokeOthers() {
    try {
      await api("/api/auth/sessions/revoke-others", { method: "POST" });
      toast("已退出其他设备");
      await loadSessions();
    } catch (e) { toast(e.message); }
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST", noAuth: true });
    } catch {}
    S.user = null;
    S.prefs = null;
    S.librarySelected = [];
    S.libraryItems = [];
    S.libraryState = null;
    S.libraryLoadedAt = 0;
    closeSettings();
    showAuth({ initialized: true, allow_register: S.allowRegister });
  }

  /* ------------------------------------------------------------------ 设置：API */
  async function loadApi() {
    const [ctx, keys] = await Promise.all([
      api("/api/api-keys/context"),
      api("/api/api-keys"),
    ]);
    S.apiCtx = ctx;
    S.apiKeys = keys.items || [];
    renderApi();
  }

  function renderApi() {
    const ctx = S.apiCtx;
    if (!ctx) return;
    const net = ctx.network || {};
    const scope = net.scope || "local";
    $("#apiScopeDot").className = "scope-dot " + scope;
    $("#apiScope").textContent = `${net.label || "本机"}访问`;
    $("#apiScopeHint").textContent = net.hint || "";
    const base = (ctx.api && ctx.api.recommended_base) || "";
    $("#apiAddress").innerHTML = `<span class="mono">${esc(base || "暂不可用")}</span>
      ${base ? `<button class="iconbtn small" id="copyBase" title="复制地址"><svg><use href="#i-copy"/></svg></button>` : ""}`;

    const urls = ctx.urls || [];
    const wanted = ["recommended", "local", "lan", "public"];
    const seenUrls = new Set();
    const visibleUrls = wanted.map((k) => urls.find((x) => x.key === k)).filter(Boolean).filter((u) => {
      const dedupeKey = u.url || ("empty:" + u.key);
      if (seenUrls.has(dedupeKey)) return false;
      seenUrls.add(dedupeKey);
      return true;
    });
    $("#apiUrls").innerHTML = visibleUrls.map((u) => `
      <div class="api-url ${u.url ? "" : "empty"}">
        <div><span>${esc(u.label)}</span><b>${esc(u.url || "暂不可用")}</b></div>
        ${u.url && u.key === "recommended" ? `<span class="badge good">推荐</span>` : ""}
        ${u.url ? `<button class="iconbtn small" data-copy-value="${esc(u.url)}" title="复制"><svg><use href="#i-copy"/></svg></button>` : ""}
      </div>`).join("");

    $("#keyList").innerHTML = S.apiKeys.length ? S.apiKeys.map((k) => `
      <div class="key-row">
        <div><b>${esc(k.name)}</b><span class="mono">${esc(k.masked)} · ${k.last_used_at ? "最近 " + relTime(k.last_used_at) : "从未使用"}${k.last_scope ? " · " + esc(k.last_scope) : ""}</span></div>
        ${k.revoked ? `<span class="badge bad">已撤销</span>` : `<span class="badge good">正常</span>`}
        ${k.revoked ? "" : `<button class="btn ghost" data-revoke-key="${k.id}">撤销</button>`}
      </div>`).join("") : `<div class="empty-line">还没有 API Key。给 Key 起个名字，点“生成 Key”。</div>`;

    const model = ctx.default_model || (ctx.models && ctx.models[0] && ctx.models[0].id) || "7b";
    const curl = `curl "${base}/chat/completions" \\\n  -H "Authorization: Bearer <你的 API Key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"${model}","messages":[{"role":"user","content":"你好"}],"stream":false}'`;
    const python = `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="${base}",\n    api_key="<你的 API Key>",\n)\n\nresp = client.chat.completions.create(\n    model="${model}",\n    messages=[{"role": "user", "content": "你好"}],\n)\nprint(resp.choices[0].message.content)`;
    S.apiDocs = { curl, python };
    $("#apiCurl").textContent = curl;
    $("#apiPython").textContent = python;
  }

  async function createApiKey() {
    const btn = $("#createKeyBtn");
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      const d = await api("/api/api-keys", {
        method: "POST",
        body: { name: $("#keyName").value.trim() },
      });
      S.apiKeys = [d.item, ...S.apiKeys];
      $("#keyName").value = "";
      $("#secretBox").hidden = false;
      $("#secretValue").value = d.key;
      $("#secretValue").dataset.copy = d.key;
      renderApi();
      $("#secretValue").focus();
      $("#secretValue").select();
    } catch (e) { toast(e.message); }
    finally {
      btn.disabled = false;
      btn.textContent = "生成 Key";
    }
  }

  async function revokeKey(id, btn) {
    if (!btn) return;
    if (btn.dataset.armed !== "1") {
      const old = btn.innerHTML;
      btn.dataset.armed = "1";
      btn.classList.add("armed");
      btn.textContent = "再点一次撤销";
      clearTimeout(revokeKey._t);
      revokeKey._t = setTimeout(() => {
        btn.dataset.armed = "";
        btn.classList.remove("armed");
        btn.innerHTML = old;
      }, 3200);
      return;
    }
    btn.dataset.armed = "";
    btn.classList.remove("armed");
    btn.disabled = true;
    try {
      await api(`/api/api-keys/${id}`, { method: "DELETE" });
      toast("Key 已撤销");
      await loadApi();
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ 设置：对话 */
  function applyChatPrefsToUI(includeSystemPrompt = true) {
    if (!S.prefs) return;
    $("#setTemp").value = S.prefs.temperature;
    $("#tempValue").textContent = Number(S.prefs.temperature).toFixed(1);
    $("#setMaxTokens").value = S.prefs.maxTokens;
    $("#setKb").checked = !!S.prefs.useKb;
    if (includeSystemPrompt) {
      $("#setSystemPrompt").value = S.cid ? S.convSystemPrompt : (S.prefs.systemPrompt || "");
      $("#sysPromptScope").textContent = S.cid ? "（当前对话）" : "（用于新对话）";
    }
  }

  async function saveChatPrefs() {
    const max = clamp(parseInt($("#setMaxTokens").value, 10) || 2048, 64, 8192);
    const temp = clamp(parseFloat($("#setTemp").value) || 0.7, 0, 1.5);
    const promptText = $("#setSystemPrompt").value.trim();
    savePrefs({ temperature: temp, maxTokens: max, useKb: $("#setKb").checked });
    if (S.cid) {
      try {
        await api(`/api/chat/conversations/${S.cid}`, { method: "PATCH", body: { system_prompt: promptText } });
        S.convSystemPrompt = promptText;
      } catch (e) {
        toast(e.message);
        return;
      }
    } else {
      savePrefs({ systemPrompt: promptText });
    }
    applyChatPrefsToUI(true);
    toast("生成参数已保存");
  }

  function resetChatPrefs() {
    const fallback = S.models.find((m) => m.loaded) || S.models[0];
    savePrefs({ ...PREF_DEFAULT, model: fallback ? fallback.key : "" });
    S.convSystemPrompt = "";
    if (S.cid) {
      api(`/api/chat/conversations/${S.cid}`, { method: "PATCH", body: { system_prompt: "" } }).catch(() => {});
    }
    applyChatPrefsToUI(true);
    if (fallback) setModel(fallback.key, false);
    toast("已恢复默认");
  }

  /* ------------------------------------------------------------------ 设置：数据 */
  async function exportData() {
    try {
      const res = await fetch("/api/auth/export", { credentials: "same-origin" });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(errorText(data, "导出失败"));
      }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "workbench-export.json";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1200);
      toast("导出完成");
    } catch (e) { toast(e.message); }
  }

  async function clearAllConversations() {
    try {
      await api("/api/chat/conversations/clear-all", { method: "POST" });
      newChat();
      await loadConversations();
      toast("所有对话已清空");
    } catch (e) { toast(e.message); }
  }

  /* ------------------------------------------------------------------ 输入与布局 */
  function autoResizeInput() {
    const el = $("#messageInput");
    el.style.height = "auto";
    el.style.height = Math.min(170, Math.max(40, el.scrollHeight)) + "px";
  }

  function openSidebar() {
    $("#appView").classList.add("side-open");
    $("#scrim").hidden = false;
  }

  function closeSidebar() {
    $("#appView").classList.remove("side-open");
    $("#scrim").hidden = true;
  }

  /* ------------------------------------------------------------------ 事件 */
  function bindEvents() {
    $("#authForm").addEventListener("submit", submitAuth);
    $("#otpForm").addEventListener("submit", submitOtp);
    $("#otpSend").addEventListener("click", sendOtp);
    $$("[data-authmode]").forEach((b) => b.addEventListener("click", () => setAuthMode(b.dataset.authmode)));
    $$("[data-authmethod]").forEach((b) => b.addEventListener("click", () => setAuthMethod(b.dataset.authmethod)));
    $("#toConsole").addEventListener("click", () => { window.location.href = "/console/"; });

    $("#newChatBtn").addEventListener("click", newChat);
    $("#allFeaturesBtn")?.addEventListener("click", openFeatureCenter);
    $("#featureCenter")?.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-close-feature-center]")) {
        closeFeatureCenter();
        return;
      }
      const item = ev.target.closest("[data-feature-run]");
      if (!item) return;
      const meta = FEATURE_CENTER_META[item.dataset.featureRun];
      closeFeatureCenter();
      if (!meta) return;
      try { meta.run(); } catch (e) { toast(e.message || "打开失败"); }
    });
    $("#welcomeAllWorkbench")?.addEventListener("click", () => openWorkbench("overview"));
    $("#welcomeContinue")?.addEventListener("click", (ev) => {
      const card = ev.target.closest("[data-wb-home]");
      if (!card) return;
      openWbHome(card.dataset.wbHome);
    });
    $("#sideLibraryBtn")?.addEventListener("click", () => openSettings("library"));
    $("#sideScheduleBtn")?.addEventListener("click", () => openWorkbench("tasks"));
    $("#sideFilesBtn")?.addEventListener("click", () => openWorkbench("files"));
    $("#attachBtn").addEventListener("click", () => $("#fileInput").click());
    $("#fileInput").addEventListener("change", (ev) => uploadFiles(ev.target.files));
    $("#composer").addEventListener("paste", (ev) => {
      const files = [...(ev.clipboardData?.items || [])]
        .filter((x) => x.kind === "file" && x.type.startsWith("image/"))
        .map((x) => x.getAsFile())
        .filter(Boolean);
      if (!files.length) return;
      ev.preventDefault();
      uploadFiles(files);
    });
    $("#composer").addEventListener("dragover", (ev) => {
      if (!ev.dataTransfer || ![...ev.dataTransfer.types].includes("Files")) return;
      ev.preventDefault();
      $("#composer").classList.add("dragover");
    });
    $("#composer").addEventListener("dragleave", (ev) => {
      if (!ev.relatedTarget || !$("#composer").contains(ev.relatedTarget)) $("#composer").classList.remove("dragover");
    });
    $("#composer").addEventListener("drop", (ev) => {
      if (!ev.dataTransfer || !ev.dataTransfer.files.length) return;
      ev.preventDefault();
      $("#composer").classList.remove("dragover");
      uploadFiles(ev.dataTransfer.files);
    });
    $("#messageInput").addEventListener("paste", (ev) => {
      const files = [...((ev.clipboardData && ev.clipboardData.files) || [])];
      if (!files.length) return;
      ev.preventDefault();
      uploadFiles(files);
    });
    $("#attachList").addEventListener("click", (ev) => {
      const rm = ev.target.closest("[data-remove-att]");
      if (rm) removeAttachment(rm.dataset.removeAtt);
    });
    $("#skillBtn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      setSkillMenu($("#skillMenu").hidden);
      if (!$("#skillMenu").hidden) setLibMenu(false);
    });
    $("#libBtn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      openLibMenu();
    });
    $("#libPickerSearch").addEventListener("input", () => {
      S.libraryQuery = $("#libPickerSearch").value;
      renderLibPicker();
    });
    $("#libPickerFolder").addEventListener("change", renderLibPicker);
    $("#libPickerTag").addEventListener("change", renderLibPicker);
    $("#libPickerList").addEventListener("change", (ev) => {
      const box = ev.target.closest("[data-lib-pick]");
      if (box) toggleLibDoc(box.dataset.libPick, box.checked);
    });
    $("#libClear").addEventListener("click", (ev) => {
      ev.stopPropagation();
      clearLibSelection();
    });
    $("#webBtn").addEventListener("click", () => {
      setWeb(!S.web);
      toast(S.web ? "联网已开启：发送时先搜索网页" : "联网已关闭");
    });
    $("#formatSelect").addEventListener("change", (ev) => {
      setOutputFormat(ev.target.value);
      ev.target.blur();
    });
    $("#skillList").addEventListener("click", (ev) => {
      const item = ev.target.closest("[data-skill-id]");
      if (item) setSkill(item.dataset.skillId);
    });
    document.addEventListener("click", (ev) => {
      if (!ev.target.closest(".skill-wrap")) setSkillMenu(false);
      if (!ev.target.closest("#libBtn") && !ev.target.closest("#libMenu")) setLibMenu(false);
    });
    $("#refreshConv").addEventListener("click", () => loadConversations($("#convSearch").value.trim()));
    $("#convSearch").addEventListener("input", () => {
      clearTimeout(S.searchTimer);
      S.searchTimer = setTimeout(() => loadConversations($("#convSearch").value.trim()), 260);
    });
    $("#convList").addEventListener("click", (ev) => {
      if (ev.target.closest(".conv-rename")) return;
      const rename = ev.target.closest("[data-rnamecid]");
      if (rename) { ev.stopPropagation(); renameConversation(rename.dataset.rnamecid); return; }
      const del = ev.target.closest("[data-delcid]");
      if (del) {
        ev.stopPropagation();
        if (armDeleteButton(del)) deleteConversation(del.dataset.delcid);
        return;
      }
      const item = ev.target.closest("[data-cid]");
      if (item) openConversation(item.dataset.cid);
    });
    $("#convList").addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" || ev.target.closest(".conv-rename")) return;
      const item = ev.target.closest("[data-cid]");
      if (item) openConversation(item.dataset.cid);
    });

    $("#userChip").addEventListener("click", () => openSettings("account"));
    $("#closeSidebar").addEventListener("click", closeSidebar);
    $("#openSidebar").addEventListener("click", openSidebar);
    $("#scrim").addEventListener("click", closeSidebar);
    $$("[data-close-settings]").forEach((el) => el.addEventListener("click", closeSettings));

    $("#messageInput").addEventListener("input", autoResizeInput);
    $("#messageInput").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
        ev.preventDefault();
        sendMessage($("#messageInput").value);
      }
    });
    $("#sendBtn").addEventListener("click", () => sendMessage($("#messageInput").value));
    $("#stopBtn").addEventListener("click", stopStream);
    $("#suggestions").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-suggest]");
      if (!b) return;
      $("#messageInput").value = b.dataset.suggest;
      if (b.hasAttribute("data-suggest-format")) setOutputFormat(b.dataset.suggestFormat || "", true);
      autoResizeInput();
      $("#messageInput").focus();
    });

    $("#messages").addEventListener("click", (ev) => {
      const codeCopy = ev.target.closest("[data-copy-code]");
      if (codeCopy) {
        const card = codeCopy.closest(".md-code");
        const code = card ? $("code", card)?.textContent || "" : "";
        copyText(code, codeCopy);
        return;
      }
      const copy = ev.target.closest("[data-copy-text]");
      if (copy) {
        const actions = copy.closest(".msg-actions");
        const text = actions ? actions.dataset.content : "";
        copyText(text, copy);
        return;
      }
      if (ev.target.closest("[data-regen]")) regenerate();
    });

    $("#modelSelect").addEventListener("change", () => {
      const key = $("#modelSelect").value;
      setModel(key);
      ensureModelLoaded(key).catch((e) => toast(e.message || "模型加载失败"));
    });

    $$("#drawerTabs button").forEach((b) => b.addEventListener("click", () => selectDrawerTab(b.dataset.dtab)));
    $("#myKbAdd").addEventListener("click", addMyKbText);
    $("#myKbFile").addEventListener("change", () => uploadMyKb($("#myKbFile").files));
    $("#myKbSearchBtn").addEventListener("click", searchMyKb);
    $("#myKbSearch").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); searchMyKb(); }
    });
    $("#myKbList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-kb-del]");
      if (btn) deleteMyKb(btn.dataset.kbDel, btn);
    });
    $("#myKbToggle").addEventListener("change", async () => {
      const on = $("#myKbToggle").checked;
      await saveMyKbSettings({ personal_enabled: on }).catch(() => {});
    });
    $("#myKbUsePublic").addEventListener("change", async () => {
      await saveMyKbSettings({ use_public: $("#myKbUsePublic").checked }).catch(() => {});
    });
    $("#myKbUsePersonal").addEventListener("change", async () => {
      await saveMyKbSettings({ use_personal: $("#myKbUsePersonal").checked }).catch(() => {});
    });
    $("#myLibAdd").addEventListener("click", addMyLibText);
    $("#myLibFile").addEventListener("change", () => uploadMyLib($("#myLibFile").files));
    $("#myLibFolderFilter").addEventListener("change", renderMyLibDocs);
    $("#myLibTagFilter").addEventListener("change", renderMyLibDocs);
    $("#myLibSearchBtn").addEventListener("click", searchMyLib);
    $("#myLibSearch").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); searchMyLib(); }
    });
    $("#myLibResults").addEventListener("click", (ev) => {
      const hit = ev.target.closest("[data-lib-hit]");
      if (hit) openMyLibDoc(hit.dataset.libHit).catch((e) => toast(e.message));
    });
    $("#myLibList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-lib-del]");
      if (btn) { deleteMyLib(btn.dataset.libDel, btn); return; }
      const org = ev.target.closest("[data-lib-org]");
      if (org) { openMyLibOrg(org.dataset.libOrg); return; }
      const open = ev.target.closest("[data-lib-open]");
      if (open) openMyLibDoc(open.dataset.libOpen).catch((e) => toast(e.message));
    });
    $("#myLibOrgSave").addEventListener("click", saveMyLibOrg);
    $("#myLibOrgCancel").addEventListener("click", closeMyLibOrg);
    $("#myLibOrgClose").addEventListener("click", closeMyLibOrg);
    $("#myLibViewClose").addEventListener("click", () => { $("#myLibView").hidden = true; });
    $("#myLibToggle").addEventListener("change", async () => {
      await saveMyLibSettings({ personal_enabled: $("#myLibToggle").checked }).catch(() => {});
    });
    $("#myLibUseGlobal").addEventListener("change", async () => {
      await saveMyLibSettings({ use_global: $("#myLibUseGlobal").checked }).catch(() => {});
    });
    $("#myLibUsePersonal").addEventListener("change", async () => {
      await saveMyLibSettings({ use_personal: $("#myLibUsePersonal").checked }).catch(() => {});
    });
    $("#myMemToggle").addEventListener("change", () => toggleMyMemory($("#myMemToggle").checked));
    $("#myMemAdd").addEventListener("click", addMyMemory);
    $("#myMemClear").addEventListener("click", () => clearMyMemory($("#myMemClear")));
    $("#myMemList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-mem-del]");
      if (btn) deleteMyMemory(btn.dataset.memDel, btn);
    });
    $("#pwForm").addEventListener("submit", changePassword);
    $("#identityList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-bind]");
      if (btn) openBind(btn.dataset.bind);
    });
    $("#bindForm").addEventListener("submit", submitBind);
    $("#bindSend").addEventListener("click", sendBindCode);
    $("#bindCancel").addEventListener("click", closeBind);
    $("#revokeOthers").addEventListener("click", revokeOthers);
    $("#logoutBtn").addEventListener("click", logout);

    $("#keyName").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); createApiKey(); }
    });
    $("#createKeyBtn").addEventListener("click", createApiKey);
    $("#hideSecret").addEventListener("click", () => {
      $("#secretBox").hidden = true;
      $("#secretValue").value = "";
    });
    $("#copySecret").addEventListener("click", () => {
      copyText($("#secretValue").dataset.copy || $("#secretValue").value, $("#copySecret"));
    });
    $("#dpanel-api").addEventListener("click", (ev) => {
      const copy = ev.target.closest("[data-copy-value]");
      if (copy) { copyText(copy.dataset.copyValue, copy); return; }
      if (ev.target.closest("#copyBase")) {
        const base = S.apiCtx && S.apiCtx.api ? S.apiCtx.api.recommended_base : "";
        copyText(base, ev.target.closest("button"));
        return;
      }
      const rev = ev.target.closest("[data-revoke-key]");
      if (rev) revokeKey(rev.dataset.revokeKey, rev);
      const cp = ev.target.closest("[data-copy-target]");
      if (cp) copyText(S.apiDocs[cp.dataset.copyTarget] || "", cp);
    });

    $("#setTemp").addEventListener("input", () => { $("#tempValue").textContent = Number($("#setTemp").value).toFixed(1); });
    $("#saveChatPrefs").addEventListener("click", saveChatPrefs);
    $("#resetChatPrefs").addEventListener("click", resetChatPrefs);

    $$("#themeGrid button").forEach((b) => b.addEventListener("click", () => {
      const mode = b.dataset.themeChoice;
      saveAppearance({ theme: mode });
      applyTheme(mode);
      $$("#themeGrid button").forEach((x) => x.classList.toggle("active", x === b));
    }));
    $("#fontScale").addEventListener("input", () => {
      const n = Number($("#fontScale").value);
      applyFontScale(n);
      $("#fontScaleValue").textContent = `${n}%`;
      saveAppearance({ fontScale: n });
    });

    $("#exportData").addEventListener("click", exportData);
    $("#clearAllData").addEventListener("click", (ev) => {
      const btn = ev.currentTarget;
      if (btn.dataset.armed === "1") {
        btn.dataset.armed = "";
        btn.classList.remove("armed");
        btn.innerHTML = `<svg><use href="#i-trash"/></svg>清空`;
        clearAllConversations();
        return;
      }
      btn.dataset.armed = "1";
      btn.classList.add("armed");
      btn.textContent = "再点一次清空全部";
      clearTimeout(clearAllConversations._t);
      clearAllConversations._t = setTimeout(() => {
        btn.dataset.armed = "";
        btn.classList.remove("armed");
        btn.innerHTML = `<svg><use href="#i-trash"/></svg>清空`;
      }, 3200);
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        if (!$("#featureCenter")?.hidden) closeFeatureCenter();
        else if (!$("#skillMenu").hidden) setSkillMenu(false);
        else if (!$("#settingsDrawer").hidden) closeSettings();
        else if (window.innerWidth <= 900 && $("#appView").classList.contains("side-open")) closeSidebar();
      }
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth > 900) closeSidebar();
    });
  }

  async function copyText(text, btn) {
    if (!text) return toast("没有可复制的内容");
    const done = () => {
      toast("已复制");
      if (btn) {
        const old = btn.dataset.label || btn.innerHTML;
        btn.dataset.label = old;
        btn.innerHTML = `<span class="toast-mini">已复制</span>`;
        setTimeout(() => { btn.innerHTML = old; }, 1100);
      }
    };
    const legacy = () => {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch {}
      area.remove();
      if (ok) done();
      else toast("复制失败，请手动选择文本");
      return ok;
    };
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await Promise.race([
        navigator.clipboard.writeText(text),
        new Promise((_, reject) => setTimeout(() => reject(new Error("clipboard timeout")), 1200)),
      ]);
      done();
    } catch {
      legacy();
    }
  }

  // 监听系统主题变化，只在“跟随系统”时即时生效
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      let a = {};
      try { a = JSON.parse(localStorage.getItem("wb.appearance") || "{}"); } catch {}
      if ((a.theme || "light") === "system") applyTheme("system");
    };
    if (mq.addEventListener) mq.addEventListener("change", handler);
    else if (mq.addListener) mq.addListener(handler);
  }

  window.addEventListener("popstate", () => {
    if (!S.user || $("#appView").hidden) return;
    const cid = chatIdFromUrl();
    if (cid) openConversation(cid, false);
    else newChat(false);
  });

  /* ---------------------------------------------------------------- 协作套件 */
  function collabEsc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function renderShareButton() {
    const btn = $("#shareChatBtn");
    if (btn) btn.hidden = !S.cid;
  }

  function renderAgentPicker() {
    const wrap = $("#agentWrap");
    const sel = $("#agentSelect");
    if (!wrap || !sel) return;
    if (!S.agents.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    sel.innerHTML = `<option value="">通用助手</option>` + S.agents.map((a) =>
      `<option value="${a.id}">${collabEsc(a.avatar || "🤖")} ${collabEsc(a.name)}</option>`).join("");
    if (S.agentId && S.agents.some((a) => a.id === S.agentId)) sel.value = String(S.agentId);
    else { S.agentId = null; sel.value = ""; }
  }

  function renderAnnouncement() {
    const strip = $("#noticeStrip");
    if (!strip) return;
    const hiddenWords = [];
    if (!frontOn("collab")) hiddenWords.push("协作", "小队", "共享", "分享");
    if (!frontOn("desk")) hiddenWords.push("服务台");
    const item = (S.announcements || []).find((a) => {
      if (localStorage.getItem(`wb.notice.${a.id}`)) return false;
      const text = `${a.title || ""} ${a.content || ""}`;
      return !hiddenWords.some((word) => text.includes(word));
    });
    if (!item) { strip.hidden = true; return; }
    S.lastAnnouncementId = item.id;
    $("#noticeTitle").textContent = item.title || "公告";
    $("#noticeBody").textContent = item.content || "";
    strip.hidden = false;
  }

  async function loadCollab() {
    try {
      const d = await api("/api/agents");
      S.agents = d.items || [];
      renderAgentPicker();
    } catch {}
    try {
      const d = await api("/api/announcements");
      S.announcements = d.items || [];
      renderAnnouncement();
    } catch {}
    try {
      const d = await api("/api/squads");
      S.collabSquads = d.items || [];
    } catch {}
    renderShareButton();
  }

  function openCollab(title, html) {
    $("#collabTitle").textContent = title;
    $("#collabBody").innerHTML = html;
    $("#collabModal").hidden = false;
  }

  function closeCollab() {
    $("#collabModal").hidden = true;
    $("#collabModal").classList.remove("over-wb");
  }

  function openShareDialog() {
    if (!S.cid) return toast("先打开一段对话再分享");
    openCollab("分享当前对话", `
      <div class="collab-field"><span>分享范围</span>
        <select id="shareVisibility"><option value="public">公开链接，拿到链接即可查看</option><option value="squad">仅指定小队成员</option></select>
      </div>
      <div class="collab-field" id="shareSquadWrap" hidden><span>选择小队</span>
        <select id="shareSquad">${(S.collabSquads || []).map((s) => `<option value="${s.id}">${collabEsc(s.name)}</option>`).join("") || `<option value="">还没有加入小队</option>`}</select>
      </div>
      <div class="collab-field"><span>有效期（天，0 表示永久）</span><input id="shareDays" type="number" min="0" max="365" value="7"></div>
      <div class="collab-row"><button class="btn primary sm" id="doShare">生成分享链接</button></div>
      <div class="collab-result" id="shareResult" hidden></div>
      <div class="small" style="color:var(--muted)">分享的是当前消息快照；之后继续聊天不会改动已分享内容。</div>
    `);
  }

  async function doShareCurrent() {
    const visibility = $("#shareVisibility").value;
    const squadId = visibility === "squad" ? Number($("#shareSquad").value || 0) : null;
    if (visibility === "squad" && !squadId) throw new Error("请选择一个自己所在的小队");
    const days = Number($("#shareDays").value || 0);
    const d = await api(`/api/conversations/${S.cid}/share`, {
      method: "POST", body: { visibility, squad_id: squadId, expires_days: days },
    });
    const url = location.origin + d.url;
    const box = $("#shareResult");
    box.hidden = false;
    box.innerHTML = `<div>${collabEsc(d.title)} · ${d.message_count} 条消息</div>
      <div style="margin-top:6px"><a href="${collabEsc(url)}" target="_blank" rel="noreferrer">${collabEsc(url)}</a></div>
      <div class="collab-row" style="margin-top:8px"><button class="btn ghost sm" id="copyShareLink" data-url="${collabEsc(url)}">复制链接</button></div>`;
  }

  async function openSquadsDialog() {
    openCollab("小队与共享", `<div class="empty-line">读取中…</div>`);
    const d = await api("/api/squads");
    S.collabSquads = d.items || [];
    if (!S.collabSquads.length) {
      $("#collabBody").innerHTML = `<div class="empty-line">你还没有加入小队。可以自己创建一个，或让管理员把你加入小队。</div>
        <div class="collab-field"><span>小队名称</span><input id="sqNewName" maxlength="60" placeholder="例如：内容组"></div>
        <div class="collab-field"><span>说明</span><input id="sqNewDesc" maxlength="300" placeholder="一句话说明这个小队做什么"></div>
        <div class="collab-row"><button class="btn primary sm" id="createSquadFromModal">创建小队</button></div>`;
      return;
    }
    $("#collabBody").innerHTML = S.collabSquads.map((s) => `
      <div class="collab-list-item">
        <b>${collabEsc(s.name)}</b>
        <span class="small">${collabEsc(s.description || "没有描述")} · 成员 ${s.member_count || 0} · 智能体 ${s.agent_count || 0}</span>
        <div class="collab-row">
          ${S.cid ? `<button class="btn ghost sm" data-share-squad="${s.id}">共享当前对话</button>` : ""}
          <button class="btn ghost sm" data-squad-convs="${s.id}">查看共享对话 (${s.conversation_count || 0})</button>
        </div>
      </div>`).join("") + `
      <div class="collab-field"><span>新建小队</span><input id="sqNewName" maxlength="60" placeholder="小队名称"></div>
      <div class="collab-row"><button class="btn sm" id="createSquadFromModal">创建小队</button></div>`;
  }

  async function shareCurrentToSquad(squadId) {
    if (!S.cid) return toast("先打开一段对话");
    await api(`/api/squads/${squadId}/conversations`, { method: "POST", body: { conversation_id: S.cid } });
    toast("已共享到小队");
    await openSquadsDialog();
  }

  async function openSquadConversations(squadId) {
    const d = await api(`/api/squads/${squadId}`);
    const convs = d.conversations || [];
    openCollab(`小队 · ${d.name}`, `
      <button class="btn ghost sm" data-back-squads="1">返回小队列表</button>
      <div class="small" style="color:var(--muted)">${collabEsc(d.description || "")} · 成员 ${d.member_count || 0}</div>
      ${convs.length ? convs.map((c) => `<div class="collab-list-item">
        <b>${collabEsc(c.title || "未命名对话")}</b>
        <span class="small">${collabEsc(c.shared_by_name || "—")} 共享 · ${collabEsc(new Date((c.created_at || 0) * 1000).toLocaleString("zh-CN"))}</span>
        <div class="collab-row"><button class="btn ghost sm" data-open-squad-conv="${d.id}:${c.conversation_id}">只读查看</button></div>
      </div>`).join("") : `<div class="empty-line">这个小队还没有共享对话</div>`}
    `);
  }

  async function openSquadConversation(squadId, cid) {
    const d = await api(`/api/squads/${squadId}/conversations/${cid}`);
    openCollab(`共享对话 · ${(d.conversation && d.conversation.title) || "未命名"}`, `
      <button class="btn ghost sm" data-squad-convs="${squadId}">返回共享列表</button>
      ${(d.messages || []).map((m) => `<div class="collab-msg"><b>${m.role === "assistant" ? "助手" : "成员"}</b>${collabEsc(m.content || "")}</div>`).join("") || `<div class="empty-line">没有可显示的消息</div>`}
    `);
  }

  async function openDeskDialog() {
    openCollab("服务台", `<div class="empty-line">读取中…</div>`);
    const d = await api("/api/tickets");
    const tickets = d.items || [];
    const statusText = { open: "待处理", processing: "处理中", resolved: "已解决", closed: "已关闭" };
    $("#collabBody").innerHTML = `
      <div class="collab-list-item">
        <b>提交问题</b>
        <div class="collab-field"><span>标题</span><input id="tkNewTitle" maxlength="120" placeholder="一句话描述问题"></div>
        <div class="collab-field"><span>详细说明</span><textarea id="tkNewContent" rows="3" placeholder="发生了什么、在哪一步、希望怎么解决"></textarea></div>
        <div class="collab-row"><select id="tkNewPriority" class="collab-select"><option value="normal">普通</option><option value="high">紧急</option><option value="low">不急</option></select>
          <button class="btn primary sm" id="createTicketBtn">提交工单</button></div>
      </div>
      <div class="section-title"><b>我的工单</b><span>${tickets.length} 条</span></div>
      ${tickets.length ? tickets.map((t) => `<div class="collab-list-item">
        <b>#${t.id} ${collabEsc(t.title)}</b>
        <span class="small">${collabEsc(statusText[t.status] || t.status)} · ${collabEsc(t.priority)} · ${collabEsc(new Date((t.updated_at || 0) * 1000).toLocaleString("zh-CN"))}</span>
        <div class="collab-row"><button class="btn ghost sm" data-open-ticket="${t.id}">查看对话</button></div>
      </div>`).join("") : `<div class="empty-line">还没有工单</div>`}`;
  }

  async function openTicketDialog(ticketId) {
    const t = await api(`/api/tickets/${ticketId}`);
    openCollab(`工单 · ${t.title}`, `
      <button class="btn ghost sm" data-back-desk="1">返回服务台</button>
      <div class="small" style="color:var(--muted)">${collabEsc(t.status)} · ${collabEsc(t.priority)} · ${collabEsc(t.category)}</div>
      ${(t.messages || []).map((m) => `<div class="collab-msg"><b>${collabEsc(m.username || "用户")}${m.role === "staff" ? " · 管理员" : ""}</b>${collabEsc(m.content || "")}</div>`).join("")}
      <div class="collab-field"><span>补充回复</span><textarea id="tkReply" rows="3" placeholder="继续说明或补充信息…"></textarea></div>
      <div class="collab-row"><button class="btn primary sm" id="replyTicketBtn" data-tid="${t.id}">发送回复</button></div>
    `);
  }

  async function createTicketFromModal() {
    const title = $("#tkNewTitle").value.trim();
    const content = $("#tkNewContent").value.trim();
    if (!title || !content) throw new Error("标题和详细说明都不能为空");
    await api("/api/tickets", { method: "POST", body: { title, content, category: "other", priority: $("#tkNewPriority").value } });
    toast("工单已提交");
    await openDeskDialog();
  }

  window.wbCollab = {
    share: openShareDialog,
    squads: openSquadsDialog,
    desk: openDeskDialog,
    close: closeCollab,
  };

  if ($("#agentSelect")) {
    $("#agentSelect").addEventListener("change", (ev) => {
      S.agentId = Number(ev.target.value || 0) || null;
      const item = S.agents.find((a) => a.id === S.agentId);
      if (item) toast(`已选择智能体：${item.name}`);
    });
  }
  if ($("#shareChatBtn")) {
    $("#shareChatBtn").addEventListener("click", openShareDialog);
  }
  if ($("#squadsBtn")) {
    $("#squadsBtn").addEventListener("click", () => openSquadsDialog().catch((e) => toast(e.message)));
  }
  if ($("#deskBtn")) {
    $("#deskBtn").addEventListener("click", () => openDeskDialog().catch((e) => toast(e.message)));
  }
  if ($("#noticeClose")) {
    $("#noticeClose").addEventListener("click", () => {
      if (S.lastAnnouncementId) localStorage.setItem(`wb.notice.${S.lastAnnouncementId}`, "1");
      $("#noticeStrip").hidden = true;
      renderAnnouncement();
    });
  }
  if ($("#collabClose")) $("#collabClose").addEventListener("click", closeCollab);
  if ($("#collabModal")) {
    $("#collabModal").addEventListener("click", (ev) => { if (ev.target === $("#collabModal")) closeCollab(); });
  }
  document.addEventListener("change", (ev) => {
    if (ev.target && ev.target.id === "shareVisibility") {
      const wrap = $("#shareSquadWrap");
      if (wrap) wrap.hidden = ev.target.value !== "squad";
    }
  });

  document.addEventListener("click", async (ev) => {
    const share = ev.target.closest("#doShare");    if (share) { await doShareCurrent().catch((e) => toast(e.message)); return; }
    const copyShare = ev.target.closest("#copyShareLink");
    if (copyShare) {
      try { await navigator.clipboard.writeText(copyShare.dataset.url); toast("链接已复制"); }
      catch { toast("复制失败，请手动选择链接"); }
      return;
    }
    const shareSquad = ev.target.closest("[data-share-squad]");
    if (shareSquad) { await shareCurrentToSquad(shareSquad.dataset.shareSquad).catch((e) => toast(e.message)); return; }
    const squadConvs = ev.target.closest("[data-squad-convs]");
    if (squadConvs) { await openSquadConversations(squadConvs.dataset.squadConvs).catch((e) => toast(e.message)); return; }
    const openConv = ev.target.closest("[data-open-squad-conv]");
    if (openConv) {
      const [sid, cid] = openConv.dataset.openSquadConv.split(":");
      await openSquadConversation(sid, cid).catch((e) => toast(e.message)); return;
    }
    const backSquads = ev.target.closest("[data-back-squads]");
    if (backSquads) { await openSquadsDialog().catch((e) => toast(e.message)); return; }
    const createSquad = ev.target.closest("#createSquadFromModal");
    if (createSquad) {
      const name = $("#sqNewName") ? $("#sqNewName").value.trim() : "";
      if (!name) { toast("小队名称不能为空"); return; }
      const desc = $("#sqNewDesc") ? $("#sqNewDesc").value.trim() : "";
      await api("/api/squads", { method: "POST", body: { name, description: desc } }).catch((e) => toast(e.message));
      toast("小队已创建");
      await openSquadsDialog().catch(() => {}); return;
    }
    const openTicket = ev.target.closest("[data-open-ticket]");
    if (openTicket) { await openTicketDialog(openTicket.dataset.openTicket).catch((e) => toast(e.message)); return; }
    const backDesk = ev.target.closest("[data-back-desk]");
    if (backDesk) { await openDeskDialog().catch((e) => toast(e.message)); return; }
    const createTicket = ev.target.closest("#createTicketBtn");
    if (createTicket) { await createTicketFromModal().catch((e) => toast(e.message)); return; }
    const replyTicket = ev.target.closest("#replyTicketBtn");
    if (replyTicket) {
      const content = $("#tkReply").value.trim();
      if (!content) { toast("回复不能为空"); return; }
      await api(`/api/tickets/${replyTicket.dataset.tid}/reply`, { method: "POST", body: { content } }).catch((e) => toast(e.message));
      toast("回复已发送");
      await openTicketDialog(replyTicket.dataset.tid).catch(() => {}); return;
    }
  });

  /* ---------------------------------------------------------------- 工作台 */
  const WB_STATUS = {
    ok: ["已完成", "ok"], error: ["失败", "error"], running: ["执行中", "running"],
  };

  const WB_QUICK_DEFAULT = [
    { label: "写总结", text: "帮我写一份本周工作总结，包含进度、问题和下周计划", format: "" },
    { label: "做 Word", text: "写一份《二次方程》教学计划，包含教学目标、重难点、教学过程和作业，排版准确", format: "docx" },
    { label: "做表格", text: "把下面的数据整理成 Excel 表格，字段清晰，适合直接汇报：", format: "xlsx" },
    { label: "做 PPT", text: "帮我整理一份 10 页以内的 PPT 大纲和每页要点：", format: "pptx" },
  ];

  const WELCOME_QUICK_DEFAULT = [
    { label: "阅读并总结", text: "把下面的文档总结成 5 条要点，标出关键结论和待办：", format: "", desc: "上传 PDF / Word，提炼结论", icon: "file", tone: "blue" },
    { label: "行业动态", text: "联网整理今天的 AI 行业重要动态，输出 5 条，每条附来源链接", format: "", desc: "联网检索，附来源链接", icon: "globe", tone: "purple" },
    { label: "文档生成", text: "把下面的内容整理成一份 Word 文档，结构清晰、可直接使用：", format: "docx", desc: "直接生成 Word / Excel / PPT", icon: "file", tone: "amber" },
    { label: "数据分析", text: "把下面的数据整理成 Excel 表格，字段清晰，适合直接汇报：", format: "xlsx", desc: "整理字段，生成 Excel", icon: "chart", tone: "green" },
  ];

  const WB_PLUGINS = [
    { id: "web", name: "联网检索", desc: "发送前搜索网页，给出来源链接", icon: "search" },
    { id: "kb", name: "知识库检索", desc: "回答前先查本机和个人知识库", icon: "book" },
    { id: "docgen", name: "文档生成", desc: "把结果直接输出成可下载文件", icon: "file" },
  ];

  let WB_TEMPLATES = [
    {
      id: "teacher", icon: "🎓", tone: "blue", name: "教师工作台",
      desc: "教案、练习题、家长通知和课堂总结，一站准备。",
      welcome: "老师，今天有什么教学任务需要帮忙？",
      welcomeSub: "写教案、出练习、做课件、分析学情，选一个开始；也可以直接告诉我年级和课题。",
      skill: "plan", skills: ["plan", "doc_qa", "polish", "summary"], plugins: ["kb", "docgen"],
      quick: [
        { label: "课件生成", text: "围绕《二次方程》生成一份 10 页课件大纲，每页包含标题、讲解要点、例题和课堂互动，输出 PPT", format: "pptx" },
        { label: "编写教案", text: "写一份《二次方程》教学计划，包含教学目标、重难点、教学过程和作业，排版准确", format: "docx" },
        { label: "出题组卷", text: "围绕《二次方程》出 20 道分层练习题，分为基础、提高、拓展三组，附带答案，整理成试卷", format: "docx" },
        { label: "学情分析", text: "根据下面的测验成绩和课堂表现，分析班级掌握情况，按知识点列出薄弱项和分层辅导建议：", format: "docx" },
        { label: "优化课件", text: "帮我优化下面这份课件的结构和表达，按导入、讲解、练习、总结四段重排，并指出可以加入的互动环节：", format: "" },
        { label: "教学视频脚本", text: "把《二次方程》的 5 分钟教学微课写成视频脚本，包含镜头、旁白、字幕和板书", format: "docx" },
        { label: "互动课件", text: "设计一套《二次方程》互动课堂活动，包含提问、分组任务、即时反馈和收尾检测，输出 PPT 大纲", format: "pptx" },
        { label: "家长通知", text: "写一则家长通知，说明本周学习重点、作业安排和需要家长配合的事项", format: "" },
      ],
    },
    {
      id: "finance", icon: "💰", tone: "gold", name: "金融投研工作台",
      desc: "行业动态、公司公告和研报摘要，按你的关注范围整理。",
      welcome: "今天想先看行业、公司，还是财报？",
      welcomeSub: "联网简报、公告摘要、研报提纲和数据表，都可以直接生成文件。",
      skill: "summary", skills: ["summary", "plan", "doc_qa"], plugins: ["web", "docgen"],
      quick: [
        { label: "行业简报", text: "联网整理今天的 AI 行业重要动态，输出 5 条，每条附来源链接，不做投资建议", format: "" },
        { label: "公告摘要", text: "把下面的公司公告整理成 5 条要点，标出对经营可能的影响，不做投资建议：", format: "docx" },
        { label: "研报提纲", text: "围绕以下行业写一份研报提纲，包含行业现状、竞争格局、风险和关键指标：", format: "docx" },
        { label: "财报解读", text: "解读下面这份财报，列出收入、利润、现金流和风险点，用普通人能理解的语言，不做投资建议：", format: "docx" },
        { label: "估值速览", text: "根据下面的公司财务数据，整理 PE、PB、PS 等估值指标和同业对比，注明数据来源，不做投资建议：", format: "xlsx" },
        { label: "数据表", text: "把下面的财务数据整理成 Excel，包含同比、环比和占比，字段清晰：", format: "xlsx" },
        { label: "事件追踪", text: "联网梳理过去 7 天与【公司或行业】相关的重要事件，按时间排序，附来源链接，不做投资建议", format: "" },
        { label: "路演提纲", text: "写一份 10 分钟路演提纲，包含投资逻辑、市场、竞争、财务和风险，不做投资建议", format: "docx" },
      ],
    },
    {
      id: "marketing", icon: "📣", tone: "pink", name: "营销工作台",
      desc: "活动方案、卖点提炼、投放复盘和竞品观察。",
      welcome: "今天要推什么产品，还是复盘哪场活动？",
      welcomeSub: "从活动方案到竞品对比、投放复盘，先把目标和素材告诉我。",
      skill: "plan", skills: ["plan", "polish", "summary"], plugins: ["web", "docgen"],
      quick: [
        { label: "活动方案", text: "为下面的产品写一份 7 天促销活动方案，包含目标、节奏、渠道和预算", format: "docx" },
        { label: "卖点提炼", text: "根据下面的产品资料，提炼 6 个用户能一眼理解的卖点，并给出对应文案", format: "" },
        { label: "竞品对比", text: "把下面几个竞品整理成对比表，从价格、功能、渠道和口碑四方面比较", format: "xlsx" },
        { label: "投放复盘", text: "根据下面的投放数据，写一份复盘，指出有效渠道、浪费点和下一步调整", format: "docx" },
        { label: "内容日历", text: "为下面品牌制定 30 天内容日历，按平台和主题排期，输出 Excel", format: "xlsx" },
        { label: "用户画像", text: "根据下面的数据和描述，整理目标用户画像：需求、场景、痛点、决策因素和触达渠道", format: "docx" },
        { label: "广告文案", text: "为下面产品写 5 组广告文案，分别适合信息流、搜索、朋友圈、短视频和电商详情页", format: "" },
        { label: "达人简报", text: "整理一份达人合作 brief，包含目标、受众、内容方向、交付要求和禁用表达", format: "docx" },
      ],
    },
    {
      id: "design", icon: "🎨", tone: "orange", name: "创意设计工作台",
      desc: "创意方向、配色说明、分镜和设计说明，先把想法说清。",
      welcome: "先聊创意方向，还是直接出分镜和设计说明？",
      welcomeSub: "把品牌、受众和想要的感觉说清楚，我来拆成可执行的方案。",
      skill: "plan", skills: ["plan", "polish"], plugins: [],
      quick: [
        { label: "创意方向", text: "为下面的品牌写 3 个视觉创意方向，分别说明关键词、色彩、构图和适用场景", format: "" },
        { label: "配色方案", text: "为下面这个页面设计 3 套配色方案，给出色值、使用比例和视觉效果说明", format: "" },
        { label: "分镜脚本", text: "把下面的 30 秒广告创意拆成 6 个分镜，包含画面、字幕和节奏", format: "docx" },
        { label: "设计说明", text: "根据下面的设计稿，写一段给客户看的说明，解释设计思路和每个元素的作用", format: "docx" },
        { label: "Logo 概念", text: "为下面品牌设计 3 个 Logo 概念，说明图形、字体、色彩和适用场景", format: "" },
        { label: "海报文案", text: "为下面活动写 3 套海报文案，包含主标题、副标题、行动号召和版式建议", format: "docx" },
        { label: "视觉规范", text: "把下面的品牌视觉整理成一份基础规范，包含色彩、字体、间距、图片风格和禁用示例", format: "docx" },
        { label: "评审清单", text: "根据下面的设计稿，列一份 10 条视觉评审清单，逐条指出问题和修改建议", format: "" },
      ],
    },
    {
      id: "writing", icon: "📚", tone: "violet", name: "写作工作台",
      desc: "长文提纲、改稿、标题和素材整理，先把结构搭稳。",
      welcome: "今天想写长文、改稿，还是先把结构搭出来？",
      welcomeSub: "提纲、润色、标题和素材整理，都可以从一句话开始。",
      skill: "polish", skills: ["polish", "plan", "summary"], plugins: ["docgen"],
      quick: [
        { label: "长文提纲", text: "围绕下面的主题写一份长文提纲，分 4 个部分，每部分列出核心观点和例子", format: "docx" },
        { label: "润色改写", text: "把下面这段文字改得更清楚、更有节奏，保留原意，不要加空洞套话：", format: "" },
        { label: "起标题", text: "根据下面的文章内容，起 10 个不同风格的标题，并说明各自适合的平台", format: "" },
        { label: "素材整理", text: "把下面这些零散素材整理成可用的写作素材库，按主题分类并标注出处", format: "docx" },
        { label: "人物小传", text: "根据下面素材写一篇 800 字人物小传，按时间线和关键事件组织，避免空洞评价：", format: "docx" },
        { label: "故事大纲", text: "把下面的设定扩写成三幕故事大纲，包含人物目标、冲突、转折和结局：", format: "docx" },
        { label: "文风模仿", text: "分析下面样文的句式、节奏和用词，再用同样风格改写我给出的段落：", format: "" },
        { label: "投稿检查", text: "按下面平台的投稿要求检查这篇文章，列出不符合项和修改建议：", format: "" },
      ],
    },
    {
      id: "formal", icon: "📄", tone: "gray", name: "正式材料工作台",
      desc: "通知、总结、汇报和请示，先明确对象、目的和口径。",
      welcome: "这份材料是通知、汇报，还是请示？",
      welcomeSub: "告诉我对象、目的和口径，我按正式格式起草。",
      skill: "polish", skills: ["polish", "plan", "summary"], plugins: ["docgen"],
      quick: [
        { label: "写通知", text: "写一则正式通知，说明事项、时间、地点、参加人员和注意事项", format: "docx" },
        { label: "写汇报", text: "写一份工作汇报，包含进展、数据、问题和下一步安排，语气正式", format: "docx" },
        { label: "写请示", text: "写一份请示，说明背景、请示事项、依据和拟办意见，格式规范", format: "docx" },
        { label: "改材料", text: "把下面的材料改得更符合正式公文口径，保留事实，删掉口语和重复", format: "" },
        { label: "会议纪要", text: "根据下面会议记录整理正式会议纪要，包含时间、参会人、议题、决定和待办", format: "docx" },
        { label: "工作总结", text: "写一份年度工作总结，包含完成情况、数据、问题和明年计划", format: "docx" },
        { label: "讲话稿", text: "为下面场合写 5 分钟讲话稿，语气正式，结构清楚", format: "docx" },
        { label: "公文校对", text: "按公文规范校对下面的材料，标出格式、称谓、数字和逻辑问题", format: "" },
      ],
    },
    {
      id: "media", icon: "🚀", tone: "cyan", name: "新媒体创作工作台",
      desc: "选题、脚本、口播和平台文案，按平台节奏来写。",
      welcome: "今天做选题、短视频，还是直播？",
      welcomeSub: "按平台节奏写脚本、口播和文案，也可以做数据复盘。",
      skill: "plan", skills: ["plan", "polish", "summary"], plugins: ["web", "docgen"],
      quick: [
        { label: "选题清单", text: "围绕下面这个账号定位，给出 20 个近期可做的选题，标注适合的平台和形式", format: "docx" },
        { label: "短视频脚本", text: "把下面的选题写成 45 秒短视频脚本，包含开场钩子、正文和结尾引导", format: "docx" },
        { label: "口播稿", text: "把下面的文章改成 90 秒口播稿，短句、好读、有节奏", format: "" },
        { label: "平台文案", text: "为下面这条内容写 3 版平台文案，分别适合小红书、公众号和视频号", format: "" },
        { label: "直播流程", text: "为下面主题设计 60 分钟直播流程，包含暖场、讲解、互动、转化和收尾", format: "xlsx" },
        { label: "封面标题", text: "为下面视频起 10 个封面标题，控制在 12 字内，并标注适合的平台", format: "" },
        { label: "评论回复", text: "为下面视频写 10 条评论区互动回复，覆盖咨询、质疑和好评", format: "" },
        { label: "数据复盘", text: "根据下面的播放和互动数据写复盘，指出开头、留存和转化的问题", format: "docx" },
      ],
    },
    {
      id: "doctor", icon: "🩺", tone: "teal", name: "医生工作台",
      desc: "健康科普、随访提醒和患者宣教材料，注意表述严谨。",
      welcome: "今天要写科普、患者宣教，还是整理门诊记录？",
      welcomeSub: "涉及诊疗的内容会保持严谨，并提示不能替代就诊。",
      skill: "summary", skills: ["summary", "doc_qa", "polish"], plugins: ["kb", "docgen"],
      quick: [
        { label: "健康科普", text: "写一篇面向普通人的健康科普，主题是高血压日常管理，语言通俗，注明不能替代就诊", format: "" },
        { label: "患者宣教", text: "把下面的注意事项整理成一页患者宣教材料，分点清楚，避免专业术语堆叠", format: "docx" },
        { label: "随访提醒", text: "写一则随访提醒，说明复诊时间、需要携带的资料和日常监测事项", format: "" },
        { label: "门诊记录", text: "把下面的门诊记录整理成规范格式，包含主诉、现病史、处理和随访计划", format: "docx" },
        { label: "用药说明", text: "把下面的用药信息整理成患者能看懂的单页说明，包含用法、注意事项和需要就医的情况，注明不能替代医嘱", format: "docx" },
        { label: "检查解读", text: "用通俗语言解释下面检查报告的关键指标和常见意义，提示需要复诊的情况，不给出诊断：", format: "" },
        { label: "科室培训", text: "围绕下面主题做一份科室培训 PPT 大纲，包含指南要点、流程和注意事项", format: "pptx" },
        { label: "科普问答", text: "围绕下面疾病整理 10 个患者最常问的问题和回答，语言通俗，避免绝对化", format: "docx" },
      ],
    },
    {
      id: "game", icon: "🎮", tone: "indigo", name: "游戏制作工作台",
      desc: "玩法拆解、关卡设计、数值表和项目排期。",
      welcome: "先拆玩法，还是排关卡和数值？",
      welcomeSub: "从核心循环到版本计划，把设计和排期一起理清。",
      skill: "plan", skills: ["plan", "summary"], plugins: ["docgen"],
      quick: [
        { label: "玩法拆解", text: "拆解下面这款游戏的核心循环，说明目标、反馈、成长和留存点", format: "" },
        { label: "关卡设计", text: "为下面这个玩法设计 5 个递进关卡，写明目标、障碍、奖励和难度变化", format: "docx" },
        { label: "数值表", text: "把下面的成长设定整理成 Excel 数值表，包含等级、消耗、产出和节奏", format: "xlsx" },
        { label: "项目排期", text: "把下面的开发内容排成 8 周计划，标出里程碑、依赖和风险", format: "xlsx" },
        { label: "剧情框架", text: "为下面这款游戏写世界观和主线剧情框架，包含冲突、章节和关键节点", format: "docx" },
        { label: "角色设定", text: "设计 5 个核心角色，包含定位、能力、成长和关系", format: "docx" },
        { label: "测试清单", text: "为下面玩法列测试清单，包含功能、边界、性能、兼容和回归项", format: "xlsx" },
        { label: "上线计划", text: "把下面版本内容排成上线计划，包含灰度、监控、回滚和公告", format: "xlsx" },
      ],
    },
  ];

  const WB_TASK_RECOS = [
    {
      id: "price-watch", title: "商品价格监控",
      desc: "持续追踪心仪商品到手价，达到目标价时提醒",
      prompt: "联网查询我关注的商品当前到手价，和我设定的目标价对比。如果达到或低于目标价，直接提醒我并给出购买链接；没达到就简述差距。商品名称和目标价：",
      frequency: "daily", time_of_day: "09:00", weekdays: [1], web_enabled: true,
    },
    {
      id: "weekend", title: "周末好去处",
      desc: "结合天气和本地活动，为你提供周末出行建议",
      prompt: "联网查一下本周末的天气和本地活动，给我 3 个适合周末出行的去处，说明距离、花费、适合人群和预约提醒。",
      frequency: "weekly", time_of_day: "18:00", weekdays: [5], web_enabled: true,
    },
    {
      id: "trivia", title: "学点小知识",
      desc: "每天一个趣味小问答，拓展知识面",
      prompt: "每天讲一个有趣的冷知识，先用一句话抛出问题，再给出答案和简短解释，控制在 200 字以内。",
      frequency: "daily", time_of_day: "08:00", weekdays: [1], web_enabled: false,
    },
    {
      id: "english", title: "每日英语单词",
      desc: "每天 5 个实用单词，带例句和记忆技巧",
      prompt: "每天给我 5 个实用英语单词，附音标、中文释义、一个例句和一个记忆技巧，难度适中。",
      frequency: "daily", time_of_day: "07:30", weekdays: [1], web_enabled: false,
    },
    {
      id: "stock-watch", title: "股价监控",
      desc: "收盘后整理关注股票走势和公开消息，不做投资建议",
      prompt: "联网整理我关注股票今天的收盘表现和公开消息，列出涨跌、成交量和 3 条可能相关的新闻，只做事实整理，不做投资建议。股票代码：",
      frequency: "daily", time_of_day: "15:30", weekdays: [1, 2, 3, 4, 5], web_enabled: true,
    },
    {
      id: "competitor", title: "竞品动态调研",
      desc: "定期跟进竞品动作，整理变化和影响",
      prompt: "联网检索我所在行业的竞品最近动态，整理产品更新、价格变化、营销动作和渠道变化，按重要性排序。行业和竞品名单：",
      frequency: "weekly", time_of_day: "09:00", weekdays: [1], web_enabled: true,
    },
    {
      id: "news", title: "每日新闻推送",
      desc: "汇总行业重要动态，按优先级排序",
      prompt: "联网汇总今天 AI 行业的重要新闻，挑 5 条，按重要性排序，每条附来源链接和一句影响判断。",
      frequency: "daily", time_of_day: "08:00", weekdays: [1], web_enabled: true,
    },
    {
      id: "weekly-summary", title: "每周工作总结",
      desc: "每周五整理本周进展、问题和下周计划",
      prompt: "根据本周聊天记录和下面补充的事项，写一份周工作总结，包含已完成、遇到的问题和下周计划。",
      frequency: "weekly", time_of_day: "17:30", weekdays: [5], web_enabled: false,
    },
  ];

  function wbShort(kind) {
    return ({ docx: "W", xlsx: "X", pptx: "P", pdf: "PDF", md: "MD", txt: "TXT" })[kind] || "F";
  }

  function wbFormatLabel(kind) {
    return OUT_FORMATS[kind] || String(kind || "文件").toUpperCase();
  }

  function wbTemplatesAll() {
    return WB_TEMPLATES.concat((S.wbCustom || []).map((t) => ({
      id: `custom-${t.id}`, dbId: t.id, custom: true, tone: "custom",
      icon: t.icon || "🧩", name: t.name || "我的工作台",
      desc: t.desc || t.description || "", quick: Array.isArray(t.quick) ? t.quick : [],
      skills: Array.isArray(t.skills) && t.skills.length ? t.skills : (t.skill_id ? [t.skill_id] : []),
      skillNames: Array.isArray(t.skill_names) ? t.skill_names : [],
      plugins: Array.isArray(t.plugins) ? t.plugins : [],
    })));
  }

  function wbSkillsOf(t) {
    if (!t) return [];
    if (Array.isArray(t.skills) && t.skills.length) return t.skills;
    return t.skill ? [t.skill] : [];
  }

  function wbSkillNamesOf(t) {
    return wbSkillsOf(t).map((id, i) => {
      const known = (S.skills || []).find((s) => s.id === id);
      return (known && known.name) || (t && (t.skillNames || t.skill_names) && (t.skillNames || t.skill_names)[i]) || id;
    });
  }

  function wbSkillName(id) {
    if (!id) return "";
    return ((S.skills || []).find((s) => s.id === id) || {}).name || id;
  }

  function wbPluginName(id) {
    return (WB_PLUGINS.find((p) => p.id === id) || {}).name || id;
  }

  function wbTemplateOf(id = S.wbTemplate) {
    return wbTemplatesAll().find((t) => t.id === id) || null;
  }

  function renderWbHero() {
    const tpl = wbTemplateOf();
    const kicker = $("#wbHeroKicker");
    const title = $("#wbHeroTitle");
    const sub = $("#wbHeroSub");
    const browse = $("#wbHeroBrowse");
    const custom = $("#wbHeroCustom");
    const share = $("#wbHeroShare");
    const exit = $("#wbHeroExit");
    const caps = $("#wbHeroCaps");
    const art = $("#wbHeroArt");
    if (!kicker || !title || !sub) return;
    $("#wbHero").classList.toggle("active", !!tpl);
    if (exit) exit.hidden = !tpl;
    if (art) {
      art.innerHTML = tpl
        ? `<span class="wb-hero-emoji">${esc(tpl.icon || "🧩")}</span><span class="wb-hero-emoji-ring"></span>`
        : `<span class="wb-art-card a">◧</span><span class="wb-art-card b">▤</span><span class="wb-art-orb">✦</span>`;
    }
    if (tpl) {
      kicker.textContent = `正在使用 · ${tpl.name}`;
      title.textContent = tpl.welcome || `${tpl.name}已就绪`;
      sub.textContent = tpl.welcomeSub || tpl.desc;
      if (browse) browse.innerHTML = "换一个模板 <span>›</span>";
    } else {
      kicker.textContent = "定制专属工作台";
      title.textContent = "轻松开工，从一组常用任务开始";
      sub.textContent = "选一个模板，快捷提示和定时任务都会跟着换。";
      if (browse) browse.innerHTML = "浏览推荐 <span>›</span>";
    }
    if (caps) {
      const skills = wbSkillsOf(tpl);
      const names = wbSkillNamesOf(tpl);
      const plugins = tpl ? (tpl.plugins || []).map(wbPluginName) : [];
      caps.hidden = !skills.length && !plugins.length;
      caps.innerHTML = [
        ...skills.map((sid, i) => {
          const on = S.skill && S.skill.id === sid;
          return `<button type="button" class="wb-cap-skill ${on ? "on" : ""}" data-wb-hero-skill="${esc(sid)}" title="使用「${esc(names[i])}」">技能 · ${esc(names[i])}</button>`;
        }),
        plugins.length ? `<span class="wb-cap-plugin">插件 · ${esc(plugins.join(" / "))}</span>` : "",
      ].join("");
    }
    if (custom) custom.innerHTML = tpl ? (tpl.custom ? "✎ 编辑当前" : "+ 自定义这套") : "+ 自定义工作台";
    if (share) share.hidden = !tpl;
  }

  function renderWbQuick() {
    const box = $("#wbQuick");
    if (!box) return;
    const tpl = wbTemplateOf();
    const items = tpl ? tpl.quick : WB_QUICK_DEFAULT;
    $("#wbQuickTitle").textContent = tpl ? `${tpl.name} · 快捷开始` : "快捷开始";
    box.innerHTML = items.map((x) => `
      <button type="button" data-wb-prompt="${esc(x.text)}" data-wb-format="${esc(x.format || "")}">${esc(x.label)}</button>`).join("");
  }

  function wbTemplateMeta(t) {
    const names = wbSkillNamesOf(t);
    const plugins = (t.plugins || []).map(wbPluginName);
    if (!names.length && !plugins.length) return "";
    return `<span class="wb-template-meta">
      ${names.length ? `<i class="skill" title="${esc(names.join(" / "))}">技能 · ${esc(names.join(" / "))}</i>` : ""}
      ${plugins.length ? `<i class="plugin">插件 · ${esc(plugins.join(" / "))}</i>` : ""}
    </span>`;
  }

  function wbTemplateCard(t) {
    const active = t.id === S.wbTemplate;
    return `<div class="wb-template ${active ? "active" : ""} ${t.custom ? "custom" : ""}" data-wb-template-card="${esc(t.id)}">
      <button type="button" class="wb-template-main" data-wb-template="${esc(t.id)}" aria-pressed="${active ? "true" : "false"}">
        <span class="wb-template-icon ${esc(t.tone)}">${esc(t.icon)}</span>
        <span class="wb-template-copy">
          <b>${esc(t.name)}${t.custom ? `<em>自建</em>` : ""}</b>
          <small>${esc(t.desc || "还没有说明，点「自定义」补充。")}</small>
          ${wbTemplateMeta(t)}
        </span>
      </button>
      <div class="wb-template-actions">
        <button type="button" class="wb-template-use ${active ? "on" : ""}" data-wb-template-use="${esc(t.id)}">${active ? "使用中" : "使用"}</button>
        <button type="button" class="wb-template-tool" data-wb-template-edit="${esc(t.id)}" title="${t.custom ? "编辑" : "自定义"}这套工作台">
          <svg><use href="#i-edit"/></svg><span>${t.custom ? "编辑" : "自定义"}</span>
        </button>
        <button type="button" class="wb-template-tool" data-wb-template-share="${esc(t.id)}" title="分享这套工作台">
          <svg><use href="#i-share"/></svg><span>分享</span>
        </button>
      </div>
    </div>`;
  }

  function renderWbTemplates() {
    const box = $("#wbTemplateGrid");
    const mine = $("#wbMyTemplateGrid");
    const mineSection = $("#wbMyTemplateSection");
    const custom = wbTemplatesAll().filter((t) => t.custom);
    if (mineSection) mineSection.hidden = custom.length === 0;
    if (mine) mine.innerHTML = custom.map(wbTemplateCard).join("");
    if (!box) return;
    box.innerHTML = WB_TEMPLATES.map(wbTemplateCard).join("");
    renderActiveWb();
  }

  function renderWbTaskRecos() {
    const box = $("#wbTaskReco");
    if (!box) return;
    box.innerHTML = WB_TASK_RECOS.map((t) => `
      <button type="button" class="wb-reco-task" data-wb-task-preset="${esc(t.id)}">
        <span class="wb-reco-main"><b>${esc(t.title)}</b><small>${esc(t.desc)}</small></span>
        <span class="wb-reco-plus" aria-hidden="true">+</span>
      </button>`).join("");
  }

  async function loadWbCustomTemplates() {
    try {
      const d = await api("/api/workbench/templates");
      S.wbCustom = (d.items || []).map((t) => ({
        id: t.id, name: t.name, icon: t.icon || "🧩",
        desc: t.description || "", quick: Array.isArray(t.quick) ? t.quick : [],
        skills: Array.isArray(t.skills) ? t.skills : (t.skill_id ? [t.skill_id] : []),
        skill_names: Array.isArray(t.skill_names) ? t.skill_names : [],
        skill_id: t.skill_id || "",
        plugins: Array.isArray(t.plugins) ? t.plugins : [],
      }));
    } catch {
      S.wbCustom = S.wbCustom || [];
    }
  }

  async function importSharedWbTemplate() {
    let raw = "";
    try { raw = localStorage.getItem("wb_shared_import") || ""; } catch {}
    if (!raw) return;
    let data = null;
    try { data = JSON.parse(raw); } catch {}
    if (!data || !data.name || !Array.isArray(data.quick) || !data.quick.length) {
      try { localStorage.removeItem("wb_shared_import"); } catch {}
      return;
    }
    try {
      const saved = await api("/api/workbench/templates", {
        method: "POST",
        body: {
          name: String(data.name).slice(0, 40),
          icon: String(data.icon || "🧩").slice(0, 8),
          description: String(data.description || "").slice(0, 200),
          quick: data.quick,
          skills: Array.isArray(data.skills) ? data.skills : [],
          skill_id: String(data.skill_id || "").slice(0, 80),
          plugins: Array.isArray(data.plugins) ? data.plugins : [],
        },
      });
      try { localStorage.removeItem("wb_shared_import"); } catch {}
      await loadWbCustomTemplates();
      applyWbTemplate(`custom-${saved.id}`);
      toast(`已导入分享的工作台「${saved.name}」`);
    } catch (e) {
      // 未登录或网络失败时保留待导入数据，登录后会再次尝试。
    }
  }

  async function loadActiveWb() {
    try {
      const d = await api("/api/workbench/active");
      S.wbTemplate = d.key || "";
    } catch {
      S.wbTemplate = "";
    }
  }

  async function persistActiveWb(key) {
    try {
      await api("/api/workbench/active", { method: "PUT", body: { key } });
    } catch {}
  }

  function renderActiveWb() {
    const box = $("#sideActiveWb");
    if (!box) return;
    const tpl = wbTemplateOf();
    box.hidden = !tpl;
    if (!tpl) return;
    $("#sideActiveWbIcon").textContent = tpl.icon || "🧩";
    $("#sideActiveWbName").textContent = tpl.name;
  }

  async function initWbRecommendations() {
    await loadActiveWb();
    await loadWbCustomTemplates();
    await importSharedWbTemplate();
    if (!wbTemplateOf()) S.wbTemplate = "";
    const current = wbTemplateOf();
    if (current) applyWbCapabilities(current);
    renderWbHero();
    renderWbTemplates();
    renderWbQuick();
    renderWbTaskRecos();
    renderActiveWb();
    updateWelcome();
  }

  function applyWbCapabilities(tpl) {
    if (!tpl) return;
    const firstSkill = wbSkillsOf(tpl)[0] || "";
    setSkill(firstSkill || null);
    const plugins = tpl.plugins || [];
    setWeb(plugins.includes("web"));
    const useKb = plugins.includes("kb");
    S.prefs = { ...(S.prefs || PREF_DEFAULT), useKb };
    savePrefs({ useKb });
    if ($("#setKb")) $("#setKb").checked = useKb;
    renderWbCaps();
  }

  function applyWbTemplate(id) {
    const tpl = wbTemplateOf(id);
    if (!tpl) return;
    S.wbTemplate = tpl.id;
    persistActiveWb(tpl.id);
    applyWbCapabilities(tpl);
    renderWbHero();
    renderWbTemplates();
    renderWbQuick();
    renderActiveWb();
    renderWelcomeHome();
    toast(`已套用「${tpl.name}」`);
  }

  function openWbHome(id) {
    const tpl = wbTemplateOf(id);
    if (!tpl) return;
    applyWbTemplate(tpl.id);
    closeWorkbench();
    newChat(false);
    applyWbCapabilities(tpl);
    updateWelcome();
    renderActiveWb();
    setTimeout(() => $("#messageInput").focus(), 80);
  }

  function closeActiveWb() {
    if (!S.wbTemplate) return;
    S.wbTemplate = "";
    persistActiveWb("");
    setSkill(null);
    setWeb(false);
    S.prefs = { ...(S.prefs || PREF_DEFAULT), useKb: false };
    savePrefs({ useKb: false });
    if ($("#setKb")) $("#setKb").checked = false;
    renderWbHero();
    renderWbTemplates();
    renderWbQuick();
    renderWbCaps();
    renderActiveWb();
    updateWelcome();
    toast("已关闭当前工作台");
  }

  function wbQuickEditorRows(items = []) {
    const rows = Array.from({ length: Math.max(4, items.length) }, (_, i) => items[i] || { label: "", text: "", format: "" });
    const formats = [["", "直接回答"], ["docx", "Word"], ["xlsx", "Excel"], ["pptx", "PPT"], ["pdf", "PDF"]];
    return rows.map((q, i) => `
      <div class="wb-edit-quick" data-wb-q="${i}">
        <div class="wb-edit-quick-head">
          <input class="wb-q-label" maxlength="20" placeholder="按钮名称，例如：写方案" value="${collabEsc(q.label || "")}">
          <select class="wb-q-format">${formats.map(([v, label]) => `<option value="${v}" ${String(q.format || "") === v ? "selected" : ""}>${label}</option>`).join("")}</select>
        </div>
        <textarea class="wb-q-text" rows="2" maxlength="600" placeholder="点这个按钮后，自动填进输入框的内容">${collabEsc(q.text || "")}</textarea>
      </div>`).join("");
  }

  function openWbTemplateEditor(template = null, builtin = false) {
    const icons = ["🎓", "💰", "📣", "🎨", "📚", "📄", "🚀", "🩺", "🎮", "🧩"];
    const initial = template || {
      name: "", icon: "🧩", desc: "", skills: [], plugins: [],
      quick: [{ label: "", text: "", format: "" }],
    };
    const isCustom = !!(template && template.custom);
    const initialSkills = wbSkillsOf(initial);
    const skillPicks = (S.skills || []).map((s) => `
      <label class="wb-skill-pick"><input type="checkbox" data-wb-tpl-skill="${collabEsc(s.id)}" ${initialSkills.includes(s.id) ? "checked" : ""}>
        <span>${collabEsc(s.name)}</span><small>${collabEsc(s.hint || "")}</small></label>`).join("");
    const pluginPicks = WB_PLUGINS.map((p) => `
      <label class="wb-plugin-pick"><input type="checkbox" data-wb-tpl-plugin="${p.id}" ${(initial.plugins || []).includes(p.id) ? "checked" : ""}>
        <span>${collabEsc(p.name)}</span></label>`).join("");
    openCollab(isCustom ? "编辑工作台" : (builtin ? "自定义这套工作台" : "新建工作台"), `
      <div class="wb-editor-note">${builtin ? "保存后会生成一份属于你的副本，原始推荐模板不会变。" : "名称、图标、说明、技能、插件和快捷按钮都可以自己定。"}</div>
      <div class="wb-editor-top">
        <label class="collab-field wb-icon-field"><span>图标</span><input id="wbtplIcon" maxlength="8" value="${collabEsc(initial.icon || "🧩")}"></label>
        <label class="collab-field"><span>工作台名称</span><input id="wbtplName" maxlength="40" placeholder="例如：内容运营工作台" value="${collabEsc(initial.name || "")}"></label>
      </div>
      <div class="wb-emoji-row">${icons.map((x) => `<button type="button" data-wb-emoji="${x}">${x}</button>`).join("")}</div>
      <label class="collab-field"><span>一句话说明</span><input id="wbtplDesc" maxlength="200" placeholder="这个工作台主要帮你做什么" value="${collabEsc(initial.desc || "")}"></label>
      <div class="wb-editor-caps">
        <div class="collab-field"><span>包含技能</span><div class="wb-skill-picks">${skillPicks}</div></div>
        <div class="collab-field"><span>默认插件</span><div class="wb-plugin-picks">${pluginPicks}</div></div>
        <div class="wb-editor-note">技能可以多选，至少选一个；套用后默认使用第一个，其余技能在工作台顶部可随时切换。插件会随工作台自动打开。</div>
      </div>
      <div class="wb-editor-sub"><b>快捷按钮</b><span>最多填 8 个，至少填 1 个；留空的会自动忽略。</span></div>
      <div class="wb-edit-quicks">${wbQuickEditorRows(initial.quick || [])}</div>
      <div class="wb-editor-actions">
        <button class="btn primary sm" type="button" id="wbtplSave">保存并套用</button>
        <button class="btn ghost sm" type="button" id="wbtplCancel">取消</button>
        ${isCustom ? `<button class="wb-editor-danger" type="button" id="wbtplDelete">删除这个工作台</button>` : ""}
      </div>`);
    $("#collabModal").classList.add("over-wb");
    $$("[data-wb-emoji]").forEach((btn) => btn.addEventListener("click", () => {
      $("#wbtplIcon").value = btn.dataset.wbEmoji;
    }));
    $("#wbtplCancel").addEventListener("click", closeCollab);
    $("#wbtplSave").addEventListener("click", () => saveWbTemplateEditor(isCustom ? template.dbId : null));
    if ($("#wbtplDelete")) {
      $("#wbtplDelete").addEventListener("click", () => deleteWbTemplate(template));
    }
    setTimeout(() => $("#wbtplName").focus(), 60);
  }

  async function saveWbTemplateEditor(editId = null) {
    const name = $("#wbtplName").value.trim();
    const icon = $("#wbtplIcon").value.trim() || "🧩";
    const description = $("#wbtplDesc").value.trim();
    const quick = $$(".wb-edit-quick").map((row) => ({
      label: $(".wb-q-label", row).value.trim(),
      text: $(".wb-q-text", row).value.trim(),
      format: $(".wb-q-format", row).value,
    })).filter((q) => q.label || q.text);
    if (!name) return toast("先给工作台起个名字");
    if (!quick.length) return toast("至少填一个快捷按钮");
    if (quick.some((q) => !q.label || !q.text)) return toast("每个快捷按钮都要有名称和提示词");
    if (quick.length > 8) return toast("快捷按钮最多 8 个");
    const pickedSkills = $$("[data-wb-tpl-skill]:checked").map((x) => x.dataset.wbTplSkill);
    if (!pickedSkills.length) return toast("至少选择一个技能");
    const body = {
      name, icon, description, quick,
      skills: pickedSkills,
      skill_id: pickedSkills[0] || "",
      plugins: $$("[data-wb-tpl-plugin]:checked").map((x) => x.dataset.wbTplPlugin),
    };
    try {
      const saved = editId
        ? await api(`/api/workbench/templates/${editId}`, { method: "PUT", body })
        : await api("/api/workbench/templates", { method: "POST", body });
      await loadWbCustomTemplates();
      applyWbTemplate(`custom-${saved.id}`);
      closeCollab();
      toast(editId ? `「${saved.name}」已保存` : `「${saved.name}」已创建并套用`);
    } catch (e) {
      toast(e.message || "保存失败");
    }
  }

  async function deleteWbTemplate(template) {
    if (!template || !template.dbId) return;
    if (!window.confirm(`确定删除「${template.name}」？这个操作不能撤销。`)) return;
    try {
      await api(`/api/workbench/templates/${template.dbId}`, { method: "DELETE" });
      if (S.wbTemplate === template.id) {
        S.wbTemplate = "";
        persistActiveWb("");
      }
      await loadWbCustomTemplates();
      renderWbHero(); renderWbTemplates(); renderWbQuick(); renderActiveWb();
      closeCollab();
      toast("工作台已删除");
    } catch (e) {
      toast(e.message || "删除失败");
    }
  }

  function openWbShareDialog(template) {
    if (!template) return;
    openCollab("分享工作台", `
      <div class="wb-share-preview">
        <span class="wb-template-icon ${collabEsc(template.tone || "custom")}">${collabEsc(template.icon || "🧩")}</span>
        <div><b>${collabEsc(template.name)}</b><small>${collabEsc(template.desc || "包含一组快捷开始按钮")}</small>${wbTemplateMeta(template)}</div>
      </div>
      <div class="collab-field"><span>链接有效期</span>
        <select id="wbShareDays"><option value="7">7 天</option><option value="30" selected>30 天</option><option value="0">永久有效</option></select>
      </div>
      <div class="collab-row"><button class="btn primary sm" type="button" id="wbDoShare">生成分享链接</button></div>
      <div class="collab-result" id="wbShareResult" hidden></div>
      <div class="wb-editor-note">收到链接的人可以直接查看这套工作台，并一键导入成自己的自定义工作台。</div>`);
    $("#collabModal").classList.add("over-wb");
    $("#wbDoShare").addEventListener("click", async () => {
      const days = Number($("#wbShareDays").value || 0);
      try {
        const d = await api("/api/workbench/shares", {
          method: "POST",
          body: {
            name: template.name, icon: template.icon || "🧩",
            description: template.desc || "", quick: template.quick,
            skill_id: template.skill || "", plugins: template.plugins || [],
            expires_days: days,
          },
        });
        const url = location.origin + (d.url || `/wb/${d.token}`);
        const box = $("#wbShareResult");
        box.hidden = false;
        box.innerHTML = `<div>链接已生成，可直接发给同事：</div>
          <div style="margin-top:6px"><a href="${collabEsc(url)}" target="_blank" rel="noreferrer">${collabEsc(url)}</a></div>
          <div class="collab-row" style="margin-top:8px"><button class="btn ghost sm" type="button" id="wbCopyShare" data-url="${collabEsc(url)}">复制链接</button></div>`;
        $("#wbCopyShare").addEventListener("click", async () => {
          try { await navigator.clipboard.writeText(url); toast("链接已复制"); }
          catch { toast("复制失败，请手动选中链接"); }
        });
      } catch (e) {
        toast(e.message || "生成分享链接失败");
      }
    });
  }


  function renderWbCaps() {
    const skillGrid = $("#wbSkillGrid");
    const pluginGrid = $("#wbPluginGrid");
    if (!skillGrid || !pluginGrid) return;
    const activeSkill = S.skill ? S.skill.id : "";
    const skills = S.skills || [];
    $("#wbCapSkillState").textContent = S.skill ? `当前 · ${S.skill.name}` : "当前不使用技能";
    skillGrid.innerHTML = `
      <button type="button" class="wb-skill-card ${!S.skill ? "active" : ""}" data-wb-skill="none">
        <span class="wb-skill-icon none"><svg><use href="#i-spark"/></svg></span>
        <span class="wb-skill-copy"><b>不使用技能</b><small>按普通对话发送</small></span>
        <span class="wb-skill-state">${!S.skill ? "使用中" : "选择"}</span>
      </button>` + skills.map((s) => {
        const icon = SKILL_ICONS[s.icon] || "i-spark";
        const on = activeSkill === s.id;
        return `<button type="button" class="wb-skill-card ${on ? "active" : ""}" data-wb-skill="${esc(s.id)}">
          <span class="wb-skill-icon"><svg><use href="#${icon}"/></svg></span>
          <span class="wb-skill-copy"><b>${esc(s.name)}</b><small>${esc(s.hint || "按这个方向回答")}</small></span>
          <span class="wb-skill-state">${on ? "使用中" : "选择"}</span>
        </button>`;
      }).join("");
    const webOn = !!S.web;
    const kbOn = !!(S.prefs && S.prefs.useKb);
    const fmt = OUT_FORMATS[S.outputFormat] || "";
    const pluginLabels = [webOn ? "联网" : "", kbOn ? "知识库" : "", fmt ? fmt : ""].filter(Boolean);
    if ($("#wbCapSummary")) {
      $("#wbCapSummary").innerHTML = `
        <span class="${S.skill ? "" : "muted"}">技能 · ${esc(S.skill ? S.skill.name : "普通对话")}</span>
        <span class="${pluginLabels.length ? "" : "muted"}">插件 · ${esc(pluginLabels.join(" / ") || "未开启")}</span>`;
    }
    pluginGrid.innerHTML = `
      <div class="wb-plugin-card ${webOn ? "on" : ""}">
        <span class="wb-plugin-icon"><svg><use href="#i-search"/></svg></span>
        <div class="wb-plugin-copy"><b>联网检索</b><small>发送前搜索网页，附来源链接</small></div>
        <label class="wb-mini-switch"><input type="checkbox" data-wb-plugin-toggle="web" ${webOn ? "checked" : ""}><span></span></label>
      </div>
      <div class="wb-plugin-card ${kbOn ? "on" : ""}">
        <span class="wb-plugin-icon"><svg><use href="#i-book"/></svg></span>
        <div class="wb-plugin-copy"><b>知识库检索</b><small>回答前先查本机和个人知识库</small></div>
        <label class="wb-mini-switch"><input type="checkbox" data-wb-plugin-toggle="kb" ${kbOn ? "checked" : ""}><span></span></label>
      </div>
      <div class="wb-plugin-card ${fmt ? "on" : ""}">
        <span class="wb-plugin-icon"><svg><use href="#i-file"/></svg></span>
        <div class="wb-plugin-copy"><b>文档生成</b><small>${fmt ? `当前输出：${esc(fmt)}` : "选格式后直接生成可下载文件"}</small></div>
        <select class="wb-plugin-format" data-wb-plugin-format>
          <option value="">只在对话里回答</option>
          ${Object.entries(OUT_FORMATS).map(([v, label]) => `<option value="${v}" ${S.outputFormat === v ? "selected" : ""}>${label}</option>`).join("")}
        </select>
      </div>`;
    $("#wbCapNote").textContent = "套用工作台会按模板自动切换，手动选择只影响接下来的对话。";
  }


  function setWorkbenchBadge(n) {
    const badge = $("#workbenchBadge");
    if (!badge) return;
    const count = Math.max(0, Number(n) || 0);
    badge.hidden = count <= 0;
    badge.textContent = count > 9 ? "9+" : String(count);
  }

  function closeWorkbench() {
    $("#workbenchDrawer").hidden = true;
  }

  function openWorkbench(tab = "overview") {
    if (!S.user) return showAuth();
    if (!frontOn("workbench")) return;
    closeSettings?.();
    $("#workbenchDrawer").hidden = false;
    setWorkbenchBadge(0);
    setWbTab(tab);
    loadWorkbench().catch((e) => toast(e.message));
    if (window.innerWidth <= 900) closeSidebar();
  }

  function setWbTab(tab) {
    let target = ["overview", "tasks", "files", "caps"].includes(tab) ? tab : "overview";
    const need = { tasks: "schedule", files: "files", caps: "skills" }[target];
    if (need && !frontOn(need)) target = "overview";
    S.wbTab = target;
    const head = {
      overview: ["WORKBENCH", "工作台", "任务、文件、最近对话，都在这里。"],
      tasks: ["SCHEDULE", "定时任务", "按你的时间自动开工，结果会留在会话里。"],
      caps: ["CAPABILITIES", "技能与插件", "选好回答方式和插件能力，下一条消息立即生效。"],
      files: ["FILES", "生成文件", "这里保存所有真实生成的文件，可直接下载。"],
    }[target];
    if ($("#wbHeadKicker")) $("#wbHeadKicker").textContent = head[0];
    if ($("#workbenchTitle")) $("#workbenchTitle").textContent = head[1];
    if ($("#wbHeadSub")) $("#wbHeadSub").textContent = head[2];
    $$("#wbTabs button").forEach((b) => b.classList.toggle("active", b.dataset.wtab === target));
    $$(".wb-pane").forEach((p) => {
      const on = p.id === `wpanel-${target}`;
      p.hidden = !on;
      p.classList.toggle("active", on);
    });
    if (target === "tasks") loadWbTasks().catch(() => {});
    if (target === "files") loadWbFiles().catch(() => {});
    if (target === "caps") renderWbCaps();
  }

  function renderWbOverview(ov) {
    S.wbOverview = ov || {};
    const counts = (ov && ov.counts) || {};
    $("#wbStatConv").textContent = String(counts.conversations || 0);
    $("#wbStatFiles").textContent = String(counts.files || 0);
    $("#wbStatTasks").textContent = String(counts.tasks || 0);
    $("#wbStatRuns").textContent = String(counts.runs_24h || 0);

    const upcoming = (ov && ov.upcoming) || [];
    $("#wbUpcoming").innerHTML = upcoming.length ? upcoming.map((t) => `
      <button type="button" class="wb-item" data-wb-task-open="${t.id}">
        <span class="wb-ico">${t.frequency === "once" ? "1" : "↻"}</span>
        <span class="wb-main"><b>${esc(t.title)}</b><small>${esc(t.schedule)} · 下次 ${esc(t.next_run_text || "待计算")}</small></span>
        <span class="wb-go">›</span>
      </button>`).join("") : `<div class="wb-empty">还没有启用的定时任务</div>`;

    renderWbFiles((ov && ov.files) || [], $("#wbRecentFiles"), true);

    const chats = (ov && ov.conversations) || [];
    $("#wbRecentChats").innerHTML = chats.length ? chats.map((c) => `
      <button type="button" class="wb-item" data-wb-conv="${c.id}">
        <span class="wb-ico">AI</span>
        <span class="wb-main"><b>${esc(c.title || "未命名对话")}</b><small>${esc(fmtTime(c.updated_at))}</small></span>
        <span class="wb-go">›</span>
      </button>`).join("") : `<div class="wb-empty">还没有对话</div>`;
  }

  function renderWbFiles(items, box, compact = false) {
    if (!box) return;
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) {
      box.innerHTML = `<div class="wb-empty">还没有生成文件。聊天时选择 Word / Excel / PPT / PDF 等格式，文件会出现在这里。</div>`;
      return;
    }
    box.innerHTML = rows.map((f) => {
      const expiry = fileExpiry(f);
      const extra = expiry.text ? ` · <span class="file-expiry">${esc(expiry.text)}</span>` : "";
      const action = expiry.download
        ? `<a class="btn ghost sm" href="/api/files/generated/${f.id}" download="${esc(f.name)}">下载</a>`
        : `<span class="badge ${expiry.state === "cleaned" ? "bad" : "warn"}">${esc(expiry.badge)}</span>`;
      return `<div class="wb-file-row ${expiry.state}" title="${esc(expiry.title)}">
        <span class="wb-ico">${wbShort(f.kind)}</span>
        <div class="wb-main"><b>${esc(f.name)}</b><small>${esc(wbFormatLabel(f.kind))} · ${esc(fmtBytes(f.size))} · ${esc(fmtTime(f.created_at))}${extra}</small></div>
        ${action}
      </div>`;
    }).join("");
  }

  async function loadWbFiles() {
    const d = await api("/api/files/generated?limit=100");
    renderWbFiles(d.items || [], $("#wbFileList"));
    const policy = $("#wbFilePolicy");
    if (policy) policy.textContent = `默认保留 ${Number(d.days) || 30} 天，到期后自动删除`;
    const notice = $("#wbFileNotice");
    if (notice) {
      const soon = Number(d.expiring_soon) || 0;
      notice.hidden = !soon;
      if (soon) {
        notice.innerHTML = `<svg><use href="#i-clock"/></svg><span>有 <b>${soon}</b> 个文件将在 ${Number(d.warn_days) || 3} 天内到期并被自动删除，请及时下载。</span>`;
      }
    }
  }

  function wbTaskStatus(task) {
    const status = String(task.last_status || "");
    if (status === "running") return WB_STATUS.running;
    if (status === "error") return WB_STATUS.error;
    if (status === "ok") return WB_STATUS.ok;
    return ["未运行", "idle"];
  }

  function renderWbTasks() {
    const box = $("#wbTaskList");
    if (!box) return;
    const items = S.wbTasks || [];
    if (!items.length) {
      box.innerHTML = `<div class="wb-empty">还没有定时任务。点上方「新建任务」，可以让模型每天、每周或某个时间自动生成一份结果。</div>`;
      return;
    }
    box.innerHTML = items.map((t) => {
      const [statusText, statusClass] = wbTaskStatus(t);
      const result = String(t.last_result || "").trim();
      const fmt = t.output_format ? wbFormatLabel(t.output_format) : "";
      const next = t.enabled ? (t.next_run_text || "待计算") : "已暂停";
      return `<div class="wb-task ${t.enabled ? "" : "off"}" data-wb-task-card="${t.id}">
        <div class="wb-task-top">
          <div><b>${esc(t.title)}</b><small>${esc(t.schedule)}</small></div>
          <span class="wb-status ${statusClass}">${statusText}</span>
        </div>
        <div class="wb-task-meta">
          <span>下次：${esc(next)}</span>
          <span>上次：${esc(t.last_run_text || "未运行")}</span>
          ${fmt ? `<span>输出：${esc(fmt)}</span>` : ""}
          ${t.web_enabled ? "<span>联网</span>" : ""}
        </div>
        ${result ? `<div class="wb-task-result">${esc(result.length > 240 ? result.slice(0, 240) + "…" : result)}</div>` : ""}
        <div class="wb-task-actions">
          <button class="btn ghost sm" data-wb-run-task="${t.id}" ${t.last_status === "running" ? "disabled" : ""}>立即执行</button>
          ${t.last_conversation_id ? `<button class="btn ghost sm" data-wb-task-conv="${t.last_conversation_id}">打开结果</button>` : ""}
          <button class="btn ghost sm" data-wb-edit-task="${t.id}">编辑</button>
          <button class="btn ghost sm danger" data-wb-del-task="${t.id}">删除</button>
          <label class="switch" title="${t.enabled ? "暂停" : "启用"}"><input type="checkbox" data-wb-toggle="${t.id}" ${t.enabled ? "checked" : ""}><span></span></label>
        </div>
      </div>`;
    }).join("");
  }

  async function loadWbTasks() {
    const d = await api("/api/workbench/tasks");
    S.wbTasks = d.items || [];
    renderWbTasks();
  }

  async function loadWorkbench() {
    const [ov, tasks] = await Promise.all([
      api("/api/workbench/overview"),
      api("/api/workbench/tasks"),
    ]);
    S.wbTasks = tasks.items || [];
    renderWbOverview(ov);
    renderWbTasks();
    S.wbLoadedAt = Date.now();
    const latest = ((ov && ov.runs) || []).reduce((m, r) => Math.max(m, Number(r.id || 0)), 0);
    if (!S.wbLastRunId || latest < S.wbLastRunId) S.wbLastRunId = latest;
  }

  function wbDatetimeLocal(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fillWbModelOptions(task = null) {
    const model = $("#wbTaskModel");
    if (model) {
      const ready = (S.models || []).filter((m) => modelRunnable(m) || m.key === (task && task.model));
      model.innerHTML = `<option value="">自动选择</option>` + ready.map((m) =>
        `<option value="${esc(m.key)}">${esc(m.label || m.key)}</option>`).join("");
      model.value = (task && task.model) || "";
    }
    const agent = $("#wbTaskAgent");
    if (agent) {
      agent.innerHTML = `<option value="">通用助手</option>` + (S.agents || []).map((a) =>
        `<option value="${a.id}">${esc(a.avatar || "🤖")} ${esc(a.name)}</option>`).join("");
      agent.value = task && task.agent_id ? String(task.agent_id) : "";
    }
  }

  function updateWbFreqFields() {
    const freq = $("#wbTaskFreq").value;
    $("#wbTaskOnceWrap").hidden = freq !== "once";
    $("#wbTaskTimeWrap").hidden = freq === "once";
    $("#wbTaskWeekdays").hidden = freq !== "weekly";
    $("#wbTaskMonthWrap").hidden = freq !== "monthly";
  }

  function openWbTaskForm(task = null, preset = null) {
    const seed = task || preset || {};
    S.wbEditingTask = task ? task.id : null;
    $("#wbTaskFormTitle").textContent = task ? "编辑定时任务" : "新建定时任务";
    $("#wbTaskTitle").value = seed.title || "";
    $("#wbTaskPrompt").value = seed.prompt || "";
    $("#wbTaskFreq").value = seed.frequency || "once";
    $("#wbTaskTime").value = seed.time_of_day || "09:00";
    $("#wbTaskMonthDay").value = String(seed.day_of_month || new Date().getDate());
    const when = new Date(Date.now() + 60 * 60 * 1000);
    when.setMinutes(Math.ceil(when.getMinutes() / 5) * 5, 0, 0);
    const savedAt = task && task.run_at ? new Date(Number(task.run_at) * 1000) : null;
    const savedFuture = savedAt && savedAt.getTime() > Date.now() + 60 * 1000;
    $("#wbTaskRunAt").value = task && task.frequency === "once" && savedFuture
      ? wbDatetimeLocal(savedAt)
      : wbDatetimeLocal(when);
    const wanted = seed.frequency === "weekly" ? (seed.weekdays || []) : [];
    $$("#wbTaskWeekdays input").forEach((x) => {
      x.checked = wanted.includes(Number(x.value));
    });
    if (seed.frequency === "weekly" && !wanted.length) {
      const first = $("#wbTaskWeekdays input");
      if (first) first.checked = true;
    }
    fillWbModelOptions(task);
    $("#wbTaskFormat").value = seed.output_format || "";
    $("#wbTaskWeb").checked = !!seed.web_enabled;
    $("#wbTaskHint").textContent = task
      ? (task.frequency === "once" && !savedFuture
        ? "这个一次性任务已经结束；要再执行一次，请选一个将来的时间，或改成每天/每周。"
        : "修改后从下一次计划时间开始生效。")
      : (preset ? "来自推荐模板，可以改时间、模型和输出格式再保存。" : "任务会在本机运行，结果进入最近对话。");
    updateWbFreqFields();
    $("#wbTaskForm").hidden = false;
    $("#wbTaskForm").scrollIntoView({ block: "start", behavior: "smooth" });
    setTimeout(() => $("#wbTaskTitle").focus(), 80);
  }

  function closeWbTaskForm() {
    S.wbEditingTask = null;
    $("#wbTaskForm").hidden = true;
  }

  async function saveWbTask() {
    const title = $("#wbTaskTitle").value.trim();
    const prompt = $("#wbTaskPrompt").value.trim();
    if (!title) return toast("任务名称不能为空");
    if (!prompt) return toast("要执行的内容不能为空");
    const frequency = $("#wbTaskFreq").value;
    const runAt = $("#wbTaskRunAt").value;
    if (frequency === "once" && !runAt) return toast("请选择执行时间");
    const weekdays = $$("#wbTaskWeekdays input:checked").map((x) => Number(x.value));
    if (frequency === "weekly" && !weekdays.length) return toast("请至少选择一天");
    const editing = S.wbEditingTask ? (S.wbTasks || []).find((t) => t.id === S.wbEditingTask) : null;
    const body = {
      title,
      prompt,
      frequency,
      time_of_day: $("#wbTaskTime").value || "09:00",
      weekdays,
      day_of_month: Number($("#wbTaskMonthDay").value || 1),
      run_at: frequency === "once" ? runAt : null,
      model: $("#wbTaskModel").value || null,
      agent_id: Number($("#wbTaskAgent").value || 0) || null,
      output_format: $("#wbTaskFormat").value || null,
      web_enabled: $("#wbTaskWeb").checked,
      enabled: editing ? !!editing.enabled : true,
    };
    const btn = $("#wbTaskSave");
    btn.disabled = true;
    try {
      if (S.wbEditingTask) {
        await api(`/api/workbench/tasks/${S.wbEditingTask}`, { method: "PUT", body });
      } else {
        await api("/api/workbench/tasks", { method: "POST", body });
      }
      toast(S.wbEditingTask ? "任务已更新" : "定时任务已创建");
      closeWbTaskForm();
      await loadWorkbench();
      setWbTab("tasks");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  }

  async function runWbTask(id, btn) {
    btn.disabled = true;
    try {
      await api(`/api/workbench/tasks/${id}/run`, { method: "POST", body: {} });
      toast("任务已开始执行，完成后会进入最近对话");
      setTimeout(() => loadWbTasks().catch(() => {}), 10000);
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
    }
  }

  async function toggleWbTask(id, enabled) {
    try {
      await api(`/api/workbench/tasks/${id}`, { method: "PATCH", body: { enabled } });
      toast(enabled ? "任务已启用" : "任务已暂停");
      await loadWorkbench();
      setWbTab("tasks");
    } catch (e) {
      toast(e.message);
      await loadWbTasks().catch(() => {});
    }
  }

  async function deleteWbTask(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "再点一次删除";
      setTimeout(() => {
        if (btn.isConnected) {
          btn.dataset.armed = "";
          btn.textContent = "删除";
        }
      }, 3200);
      return;
    }
    try {
      await api(`/api/workbench/tasks/${id}`, { method: "DELETE" });
      toast("任务已删除");
      await loadWorkbench();
      setWbTab("tasks");
    } catch (e) {
      toast(e.message);
    }
  }

  function useWbPrompt(button) {
    const prompt = button.dataset.wbPrompt || "";
    const fmt = button.dataset.wbFormat || "";
    closeWorkbench();
    newChat(false);
    if (fmt) setOutputFormat(fmt, true);
    $("#messageInput").value = prompt;
    autoResizeInput();
    $("#messageInput").focus();
    toast(fmt ? `已填入提示词，并选择 ${OUT_FORMATS[fmt]}` : "已填入提示词");
  }

  async function pollWorkbench() {
    if (!S.user || !$("#appView") || $("#appView").hidden) return;
    try {
      const ov = await api("/api/workbench/overview");
      const runs = (ov && ov.runs) || [];
      const seen = S.wbRunStatuses || {};
      const changed = runs.filter((r) => seen[r.id] && seen[r.id] !== r.status && r.status !== "running");
      S.wbRunStatuses = runs.reduce((m, r) => { m[r.id] = r.status; return m; }, {});
      const latest = runs.reduce((m, r) => Math.max(m, Number(r.id || 0)), 0);
      if (!S.wbLastRunId) S.wbLastRunId = latest;
      else if (latest > S.wbLastRunId) S.wbLastRunId = latest;
      if (changed.length) {
        const done = changed[0];
        toast(done.status === "ok"
          ? `定时任务完成：${done.summary || "已生成结果"}`
          : `定时任务失败：${done.error || "请到工作台查看"}`);
        if ($("#workbenchDrawer").hidden) {
          const current = Number(($("#workbenchBadge").textContent || "0").replace("+", "")) || 0;
          setWorkbenchBadge(current + changed.filter((r) => r.status === "ok").length);
        }
        loadConversations().catch(() => {});
      }
      if (!$("#workbenchDrawer").hidden) {
        if (S.wbTab === "overview") renderWbOverview(ov);
        else if (S.wbTab === "tasks") loadWbTasks().catch(() => {});
        else if (S.wbTab === "files") loadWbFiles().catch(() => {});
      }
    } catch {}
  }

  if ($("#workbenchBtn")) $("#workbenchBtn").addEventListener("click", () => openWorkbench());
  if ($("#sideActiveWbOpen")) $("#sideActiveWbOpen").addEventListener("click", () => openWorkbench());
  if ($("#sideActiveWbClose")) $("#sideActiveWbClose").addEventListener("click", (ev) => {
    ev.stopPropagation();
    closeActiveWb();
  });
  if ($("#capsBtn")) $("#capsBtn").addEventListener("click", () => openWorkbench("caps"));
  if ($("#wbTabs")) {
    $("#wbTabs").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-wtab]");
      if (btn) setWbTab(btn.dataset.wtab);
    });
  }
  $$("[data-close-workbench]").forEach((el) => el.addEventListener("click", closeWorkbench));
  if ($("#wbNewTask")) $("#wbNewTask").addEventListener("click", () => openWbTaskForm());
  if ($("#wbTaskCancel")) $("#wbTaskCancel").addEventListener("click", closeWbTaskForm);
  if ($("#wbTaskSave")) $("#wbTaskSave").addEventListener("click", saveWbTask);
  if ($("#wbTaskFreq")) $("#wbTaskFreq").addEventListener("change", updateWbFreqFields);
  if ($("#wbRefreshFiles")) $("#wbRefreshFiles").addEventListener("click", () => loadWbFiles().catch((e) => toast(e.message)));
  if ($("#wbNewChat")) $("#wbNewChat").addEventListener("click", () => { closeWorkbench(); newChat(); });
  if ($("#wbHeroBrowse")) $("#wbHeroBrowse").addEventListener("click", () => {
    $("#wbTemplateSection").scrollIntoView({ block: "start", behavior: "smooth" });
  });
  if ($("#wbNewTemplate")) $("#wbNewTemplate").addEventListener("click", () => openWbTemplateEditor(null, false));
  if ($("#wbHeroCustom")) $("#wbHeroCustom").addEventListener("click", () => {
    const tpl = wbTemplateOf();
    if (tpl && tpl.custom) openWbTemplateEditor(tpl, false);
    else if (tpl) openWbTemplateEditor(tpl, true);
    else openWbTemplateEditor(null, false);
  });
  if ($("#wbHeroShare")) $("#wbHeroShare").addEventListener("click", () => {
    const tpl = wbTemplateOf();
    if (tpl) openWbShareDialog(tpl);
  });
  if ($("#wbHeroExit")) $("#wbHeroExit").addEventListener("click", closeActiveWb);

  document.addEventListener("change", (ev) => {
    if (ev.target && ev.target.dataset && ev.target.dataset.wbToggle) {
      toggleWbTask(Number(ev.target.dataset.wbToggle), ev.target.checked);
      return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.wbPluginToggle) {
      const id = ev.target.dataset.wbPluginToggle;
      if (id === "web") setWeb(ev.target.checked);
      if (id === "kb") {
        savePrefs({ useKb: ev.target.checked });
        if ($("#setKb")) $("#setKb").checked = ev.target.checked;
      }
      renderWbCaps();
      return;
    }
    if (ev.target && ev.target.dataset && ev.target.dataset.wbPluginFormat !== undefined) {
      setOutputFormat(ev.target.value);
      renderWbCaps();
    }
  });

  document.addEventListener("click", async (ev) => {
    const close = ev.target.closest("[data-close-workbench]");
    if (close) { closeWorkbench(); return; }
    const goTab = ev.target.closest("[data-wtab-go]");
    if (goTab) { setWbTab(goTab.dataset.wtabGo); return; }
    const wbSkill = ev.target.closest("[data-wb-skill]");
    if (wbSkill) {
      setSkill(wbSkill.dataset.wbSkill);
      renderWbCaps();
      renderWbHero();
      toast(S.skill ? `已选择技能「${S.skill.name}」` : "已切换为普通对话");
      return;
    }
    const heroSkill = ev.target.closest("[data-wb-hero-skill]");
    if (heroSkill) {
      setSkill(heroSkill.dataset.wbHeroSkill);
      renderWbCaps();
      renderWbHero();
      toast(`已切换到「${S.skill ? S.skill.name : "普通对话"}」`);
      return;
    }
    const tplUse = ev.target.closest("[data-wb-template-use]");
    if (tplUse) { openWbHome(tplUse.dataset.wbTemplateUse); return; }
    const tplEdit = ev.target.closest("[data-wb-template-edit]");
    if (tplEdit) {
      const tpl = wbTemplateOf(tplEdit.dataset.wbTemplateEdit);
      if (tpl) openWbTemplateEditor(tpl, !tpl.custom);
      return;
    }
    const tplShare = ev.target.closest("[data-wb-template-share]");
    if (tplShare) {
      const tpl = wbTemplateOf(tplShare.dataset.wbTemplateShare);
      if (tpl) openWbShareDialog(tpl);
      return;
    }
    const useTpl = ev.target.closest("[data-wb-template]");
    if (useTpl) { openWbHome(useTpl.dataset.wbTemplate); return; }
    const preset = ev.target.closest("[data-wb-task-preset]");
    if (preset) {
      const tpl = WB_TASK_RECOS.find((x) => x.id === preset.dataset.wbTaskPreset);
      if (tpl) {
        setWbTab("tasks");
        openWbTaskForm(null, tpl);
      }
      return;
    }
    const quick = ev.target.closest("[data-wb-prompt]");
    if (quick) { useWbPrompt(quick); return; }
    const conv = ev.target.closest("[data-wb-conv]");
    if (conv) {
      closeWorkbench();
      await openConversation(Number(conv.dataset.wbConv)).catch((e) => toast(e.message));
      return;
    }
    const taskOpen = ev.target.closest("[data-wb-task-open]");
    if (taskOpen) {
      setWbTab("tasks");
      const card = document.querySelector(`[data-wb-task-card="${taskOpen.dataset.wbTaskOpen}"]`);
      if (card) card.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    const run = ev.target.closest("[data-wb-run-task]");
    if (run) { await runWbTask(Number(run.dataset.wbRunTask), run); return; }
    const edit = ev.target.closest("[data-wb-edit-task]");
    if (edit) {
      const task = (S.wbTasks || []).find((t) => t.id === Number(edit.dataset.wbEditTask));
      setWbTab("tasks");
      if (task) openWbTaskForm(task);
      return;
    }
    const taskConv = ev.target.closest("[data-wb-task-conv]");
    if (taskConv) {
      closeWorkbench();
      await openConversation(Number(taskConv.dataset.wbTaskConv)).catch((e) => toast(e.message));
      return;
    }
    const del = ev.target.closest("[data-wb-del-task]");
    if (del) { await deleteWbTask(Number(del.dataset.wbDelTask), del); return; }
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !$("#workbenchDrawer").hidden) closeWorkbench();
  });

  bindEvents();
  boot();
})();