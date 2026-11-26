/* 控制台 · 提示词交互、前台功能与图标库、页面输入事件 | 原 console.js 第 8454–9031 行 */
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
