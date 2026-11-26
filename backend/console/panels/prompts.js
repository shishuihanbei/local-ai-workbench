/* 控制台 · 提示词中心 | 原 console.js 第 7226–7736 行 */
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

