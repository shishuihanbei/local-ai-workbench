/* 用户端 · 登录 / 注册 / 初始化、启动引导 boot | 原 app.js 第 320–753 行 */
"use strict";
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
    const rememberWrap = $("#authRememberWrap");
    if (rememberWrap) rememberWrap.hidden = isSetup;
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
    restoreRememberedUsername();
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

  const REMEMBER_USER_KEY = "wb_last_username";
  const REMEMBER_FLAG_KEY = "wb_remember_username";

  function rememberedUsername() {
    try {
      if (localStorage.getItem(REMEMBER_FLAG_KEY) === "0") return "";
      return localStorage.getItem(REMEMBER_USER_KEY) || "";
    } catch (e) { return ""; }
  }

  function saveRememberedUsername(name) {
    try {
      const box = $("#authRemember");
      const on = !box || box.checked;
      localStorage.setItem(REMEMBER_FLAG_KEY, on ? "1" : "0");
      if (on) localStorage.setItem(REMEMBER_USER_KEY, name);
      else localStorage.removeItem(REMEMBER_USER_KEY);
    } catch (e) { /* 隐私模式忽略 */ }
  }

  function restoreRememberedUsername() {
    const box = $("#authRemember");
    if (box) {
      try { box.checked = localStorage.getItem(REMEMBER_FLAG_KEY) !== "0"; } catch (e) { box.checked = true; }
    }
    const name = rememberedUsername();
    const input = $("#authUser");
    if (name && input && !input.value) input.value = name;
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
      saveRememberedUsername(username);
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
    const consoleEntry = document.querySelector("#consoleEntry");
    if (consoleEntry) consoleEntry.hidden = S.user.role !== "admin";
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

