/* 控制台 · 用户与模型权限、登录方式、API Key | 原 console.js 第 2957–3835 行 */
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

