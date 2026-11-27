/* 用户端 · 头部状态 S、$ / $$ / esc / api / toast 等基础工具、主题与偏好 | 原 app.js 第 1–319 行 */
/* 本地 AI 工作台 · 用户端
   纯前端（无构建步骤），所有数据通过 /api 访问。 */
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
    agentMode: true,
    lastAgentMode: true,
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
    if (data.detail && typeof data.detail === "object") {
      return String(data.detail.message || data.detail.code || fallback);
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
    if (!res.ok) {
      const err = new Error(errorText(data, `请求失败（${res.status}）`));
      err.status = res.status;
      err.data = data;
      throw err;
    }
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

