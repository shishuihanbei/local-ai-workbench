/* 用户端 · 技能、前台功能开关与图标 | 原 app.js 第 1052–1329 行 */
"use strict";
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
    btn.title = S.web ? "强制联网已开启：发送时会先搜索网页" : "强制联网检索实时网页，默认关闭";
    const state = $("#webState");
    if (state) state.textContent = S.web ? "本条已开启" : "关闭";
  }

  function setToolMenu(open) {
    const menu = $("#toolMenu");
    const btn = $("#moreBtn");
    if (!menu) return;
    menu.hidden = !open;
    if (btn) btn.setAttribute("aria-expanded", String(!!open));
  }

  function setDeep(on) {
    S.deep = !!on;
    const btn = $("#deepBtn");
    if (!btn) return;
    btn.classList.toggle("active", S.deep);
    btn.setAttribute("aria-pressed", String(S.deep));
    btn.title = S.deep ? "深度模式已开启：复杂任务优先云端补强，未接入或超预算时留在本地" : "深度模式：本条允许调用云端补强（豆包 API），仍受预算、敏感词和附件策略约束";
  }

  function modelSupportsAgentTools() {
    const m = selectedModel();
    return !!m && m.owned_by !== "cluster" && m.engine !== "cluster";
  }

  function setAgentMode(on) {
    if (!modelSupportsAgentTools()) on = false;
    S.agentMode = !!on;
    const btn = $("#agentBtn");
    if (!btn) return;
    btn.classList.toggle("active", S.agentMode);
    btn.setAttribute("aria-pressed", String(S.agentMode));
    const locked = btn.disabled || btn.classList.contains("disabled");
    btn.title = locked
      ? "当前为算力池模型，暂不支持通用助手工具闭环，已按普通对话生成"
      : S.agentMode ? "通用助手已开启：自动检索资料、附件；支持工具调用的模型可按需联网" : "通用助手关闭：本轮按普通对话生成";
  }

  function syncAgentModelLock() {
    const btn = $("#agentBtn");
    if (!btn) return;
    const supported = modelSupportsAgentTools();
    btn.disabled = !supported;
    btn.classList.toggle("disabled", !supported);
    setAgentMode(S.agentMode && supported);
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
    agent_tools: { desc: "通用助手自动检索资料、网页和附件；不支持工具调用时按固定顺序兜底", go: "开启", run: () => {
      if (!modelSupportsAgentTools()) { toast("当前为算力池模型，暂不支持通用助手工具闭环"); return; }
      setAgentMode(true); toast("通用助手已开启");
    } },
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
    }).join("") + (S.user && S.user.role === "admin"
      ? `<button class="fc-item" type="button" data-console-link>`
        + `<span class="fc-ic blue"><svg><use href="#i-grid"/></svg></span>`
        + `<span class="fc-copy"><b>管理控制台</b><small>模型、账号、功能开关与系统设置</small></span>`
        + `<span class="fc-go">打开 ›</span></button>`
      : "");
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
      if (on && map.get(key) && !el.hasAttribute("data-keep-icon")) paintFrontIcon(el, map.get(key));
      else if (!on && el.querySelector(":scope > .front-icon-slot")) {
        const slot = el.querySelector(":scope > .front-icon-slot");
        slot.innerHTML = slot.dataset.defaultSvg || "";
      }
    });
    const sideTools = document.querySelector(".side-tools");
    if (sideTools) sideTools.hidden = !sideTools.querySelector(":scope > button:not([data-front-off])");
    const sideProjects = $("#sideProjects");
    if (sideProjects) {
      sideProjects.hidden = ![...sideProjects.querySelectorAll("[data-front]")].some((el) => !el.hasAttribute("data-front-off"));
    }
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
    const moreBtn = $("#moreBtn");
    if (moreBtn) moreBtn.hidden = !frontOn("web");
    if (!frontOn("web") && $("#toolMenu") && !$("#toolMenu").hidden) setToolMenu(false);
    if (!frontOn("agent_tools") && S.agentMode) setAgentMode(false);
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

