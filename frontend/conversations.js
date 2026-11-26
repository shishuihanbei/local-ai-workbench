/* 用户端 · 会话列表、新建 / 重命名 / 删除 | 原 app.js 第 1426–1645 行 */
"use strict";
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

