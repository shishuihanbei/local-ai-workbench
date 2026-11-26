/* 用户端 · 伙伴、小队、公告、工单、对话分享 | 原 app.js 第 3646–3927 行 */
"use strict";
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

