/* 用户端 · 流式生成、停止 / 重生成、排队与错误 | 原 app.js 第 1932–2187 行 */
"use strict";
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
    const agentMode = regen ? S.lastAgentMode : S.agentMode;
    const deep = regen ? S.lastDeep : S.deep;
    const outFormat = regen ? (S.lastOutputFormat || S.outputFormat) : S.outputFormat;
    const agent = S.agentId ? (S.agents.find((a) => Number(a.id) === Number(S.agentId)) || null) : null;
    if (!message && attachments.length) message = "请阅读这些附件并总结要点。";
    if (!message) return;
    const imageCount = attachments.filter((f) => f.kind === "image").length;
    if (imageCount && !model.vision) {
      toast("当前模型不能直接看图：本轮只带 OCR 文字，换视觉模型后可看原图");
    }

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
    let waitTimer = 0;
    let waitStarted = 0;
    let gotDelta = false;
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
      vision: !!model.vision,
      skill: skill ? skill.id : null,
      web: !!web,
      agent_mode: !!agentMode,
      agent_id: S.agentId || null,
      output_format: outFormat || null,
      assist_reason: deep ? "用户开启深度模式" : "",
    };
    S.lastSkill = skill || null;
    S.lastWeb = !!web;
    S.lastAgentMode = !!agentMode;
    S.lastDeep = !!deep;
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

    waitStarted = Date.now();
    const showWait = () => {
      if (!S.stream) return;
      const sec = Math.floor((Date.now() - waitStarted) / 1000);
      const meta = $("#currentMeta");
      if (meta) meta.textContent = sec >= 5 ? `正在生成… 已等待 ${sec} 秒` : "正在生成…";
    };
    showWait();
    waitTimer = setInterval(showWait, 1000);

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
            if (evt.model_switch) renderModelSwitch(assistant, evt.model_switch);
            if (evt.assist && evt.assist.state === "assist") {
              renderModelSwitch(assistant, {
                from: "本地模型",
                to: `${evt.assist.provider || "云端"} · ${evt.assist.model || ""}`,
                reason: evt.assist.reason,
              });
            } else if (evt.assist && evt.assist.state === "local" && deep) {
              toast(evt.assist.reason || "本次没有上云");
            }
            if (evt.file_mode) {
              fileMode = true;
              setAssistantText(assistant, `正在整理 ${OUT_FORMATS[evt.output_format] || "文档"}…`, true);
            } else if (evt.web) {
              renderWebTags(assistant, evt.web);
              if (!content) setAssistantText(assistant, "正在生成回答…", true);
            }
          } else if (evt.type === "agent_action") {
            renderAgentAction(assistant, evt.action);
            if (!content && !gotDelta) setAssistantText(assistant, "正在调用工具检索资料…", true);
          } else if (evt.type === "assist") {
            renderModelSwitch(assistant, {
              from: "本地模型",
              to: `${evt.provider || "云端"} · ${evt.model || ""}`,
              reason: evt.reason || "本地失败，已由云端补强",
            });
          } else if (evt.type === "reasoning") {
            reasoning += evt.text || "";
            setAssistantReasoning(assistant, reasoning);
            scrollBottom(false);
          } else if (evt.type === "delta") {
            content += evt.text || "";
            pending = true;
            if (!gotDelta) {
              gotDelta = true;
              if (waitTimer) { clearInterval(waitTimer); waitTimer = 0; }
              const meta = $("#currentMeta");
              if (meta) meta.textContent = "正在输出…";
            }
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
            if (waitTimer) { clearInterval(waitTimer); waitTimer = 0; }
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
      if (waitTimer) { clearInterval(waitTimer); waitTimer = 0; }
      const meta = $("#currentMeta");
      if (meta && (meta.textContent.startsWith("正在生成") || meta.textContent.startsWith("正在输出"))) {
        meta.textContent = done
          ? `已完成 · 用时 ${Math.max(1, Math.round((Date.now() - waitStarted) / 1000))}s`
          : (stopped ? "已停止" : "已中断");
      }
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

