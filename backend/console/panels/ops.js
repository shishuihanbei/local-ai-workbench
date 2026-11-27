/* 控制台 · 审计日志、协作套件、联网检索、附件解析 | 原 console.js 第 7737–8453 行 */
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
  await loadAgentConfig();
}

/* 自动工具 Agent 的全局配置：总开关、最大轮次、每个只读工具是否暴露 */
async function loadAgentConfig() {
  const d = await api("/api/system/settings");
  const c = d || {};
  $("agentModeOn").checked = c.agent_mode_enabled !== false;
  $("agentToolKb").checked = c.agent_tool_kb !== false;
  $("agentToolLibrary").checked = c.agent_tool_library !== false;
  $("agentToolWeb").checked = c.agent_tool_web !== false;
  $("agentToolAttach").checked = c.agent_tool_attachments !== false;
  $("agentMaxTurns").value = String(c.agent_max_turns ?? 4);
}

async function saveAgentConfig() {
  const turns = Number($("agentMaxTurns").value);
  if (!Number.isInteger(turns) || turns < 1 || turns > 6) throw new Error("最多工具轮次只支持 1–6");
  const body = {
    agent_mode_enabled: $("agentModeOn").checked,
    agent_tool_kb: $("agentToolKb").checked,
    agent_tool_library: $("agentToolLibrary").checked,
    agent_tool_web: $("agentToolWeb").checked,
    agent_tool_attachments: $("agentToolAttach").checked,
    agent_max_turns: turns,
  };
  await api("/api/system/settings", { method: "PUT", body: JSON.stringify(body) });
  uiToast("自动工具设置已保存，下一条消息生效");
  await loadAgentConfig();
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
  if ($("saveAgentConfig")) {
    $("saveAgentConfig").addEventListener("click", () => saveAgentConfig().catch((e) => uiToast(e.message, "bad")));
  }
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

