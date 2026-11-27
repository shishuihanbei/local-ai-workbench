/* 用户端 · 消息渲染、Markdown、推理折叠、文件卡片 | 原 app.js 第 1646–1931 行 */
"use strict";
  /* ------------------------------------------------------------------ 消息渲染 */
  function addUserMessage(text, animate = true, meta = {}) {
    $("#welcome").hidden = true;
    const atts = Array.isArray(meta.attachments) ? meta.attachments : [];
    const skill = meta.skill && meta.skill.name ? meta.skill : null;
    const agent = meta.agent && meta.agent.name ? meta.agent : null;
    const row = document.createElement("div");
    row.className = "msg msg-user";
    const skillHtml = skill ? `<div class="msg-skill">技能 · ${esc(skill.name)}</div>` : "";
    const agentHtml = agent ? `<div class="msg-agent">${esc(agent.avatar || "🤖")} ${esc(agent.name)}</div>` : "";
    const webHtml = meta.web ? `<div class="msg-web"><svg><use href="#i-search"/></svg>联网检索</div>` : "";
    const fmtHtml = meta.output_format && OUT_FORMATS[meta.output_format]
      ? `<div class="msg-web"><svg><use href="#i-file"/></svg>${esc(OUT_FORMATS[meta.output_format])}</div>` : "";
    const images = atts.filter((f) => f.kind === "image" && f.url);
    const docs = atts.filter((f) => f.kind !== "image");
    const imagesHtml = images.length
      ? `<div class="msg-images">${images.map((f) => `<button type="button" class="msg-image" data-img-preview="${esc(f.url)}" data-img-name="${esc(f.name || "图片")}" title="点击放大"><img src="${esc(f.url)}" alt="${esc(f.name || "图片")}" loading="lazy"></button>`).join("")}</div>`
      : "";
    const filesHtml = docs.length
      ? `<div class="msg-files">${docs.map((f) => `<span class="msg-file"><svg><use href="#i-file"/></svg><span>${esc(f.name || "附件")}</span></span>`).join("")}</div>`
      : "";
    row.innerHTML = `<div class="bubble">${agentHtml}${skillHtml}${webHtml}${fmtHtml}${imagesHtml}${filesHtml}<div class="msg-text">${esc(text)}</div></div>`;
    if (!animate) row.style.animation = "none";
    $("#messages").appendChild(row);
    scrollBottom(true);
    return row;
  }

  function addAssistantMessage(opts = {}) {
    $("#welcome").hidden = true;
    const agent = opts.agent && opts.agent.name ? opts.agent : null;
    const row = document.createElement("div");
    row.className = "msg msg-assistant";
    row.innerHTML = `
      <div class="msg-avatar${agent ? " has-agent" : ""}">${esc(agent ? (agent.avatar || "AI") : "AI")}</div>
      <div class="body">
        <div class="msg-author"><b>${esc(agent ? agent.name : "AI 助手")}</b>${agent ? '<span class="msg-author-tag">智能体</span>' : ""}</div>
        <details class="reasoning" ${opts.reasoning ? "" : "hidden"}><summary>思考过程</summary><pre></pre></details>
        <div class="agent-trace" hidden></div>
        <div class="msg-text ${opts.streaming ? "streaming" : ""}"></div>
        <div class="kb-tags" hidden></div>
        <div class="web-tags" hidden></div>
        <div class="msg-files" hidden></div>
        <div class="msg-actions"></div>
      </div>`;
    const textEl = $(".msg-text", row);
    const reasonEl = $(".reasoning pre", row);
    if (opts.reasoning) reasonEl.textContent = opts.reasoning;
    if (opts.model_switch) renderModelSwitch(row, opts.model_switch);
    else if (isLightModel(opts.model)) renderLightWarning(row, opts.model);
    if (opts.content && !opts.streaming) {
      textEl.classList.remove("streaming");
      textEl.innerHTML = renderMarkdown(opts.content);
    } else if (opts.streaming) {
      textEl.innerHTML = `<span class="typing"><i></i><i></i><i></i></span>`;
    }
    if (opts.kb && opts.kb.length) renderKbTags(row, opts.kb);
    if (opts.web) renderWebTags(row, opts.web);
    if (opts.files && opts.files.length) renderFiles(row, opts.files);
    if (opts.actions) renderActions(row, opts.content || "");
    $("#messages").appendChild(row);
    scrollBottom(true);
    return row;
  }

  function setAssistantText(row, text, streaming) {
    const el = $(".msg-text", row);
    if (!el) return;
    if (streaming) {
      el.classList.add("streaming");
      el.innerHTML = renderMarkdown(text, { streaming: true });
    } else {
      el.classList.remove("streaming");
      el.innerHTML = renderMarkdown(text);
    }
  }

  function setAssistantReasoning(row, text) {
    if (!text) return;
    const box = $(".reasoning", row);
    const pre = $(".reasoning pre", row);
    if (box) box.hidden = false;
    if (pre) pre.textContent = text;
  }

  function isLightModel(name) {
    return /(?:^|[^\d])(?:0\.5|1\.5)\s*b(?:[^a-z]|$)/i.test(String(name || ""));
  }

  function renderLightWarning(row, model) {
    if (!row) return;
    const text = $(".msg-text", row);
    if (!text) return;
    const el = document.createElement("div");
    el.className = "msg-notice warn";
    el.innerHTML = `<svg><use href="#i-refresh"/></svg><span>这条回复由轻量测试模型 <b>${esc(model)}</b> 生成，复杂任务容易答非所问；点“重新生成”会自动改用强模型并生成可预览文件。</span>`;
    $(".body", row).insertBefore(el, text);
  }

  function renderModelSwitch(row, sw) {
    if (!row || !sw || !sw.to) return;
    let el = $(".msg-notice", row);
    if (!el) {
      el = document.createElement("div");
      el.className = "msg-notice";
      const text = $(".msg-text", row);
      if (text) $(".body", row).insertBefore(el, text);
      else $(".body", row).appendChild(el);
    }
    el.innerHTML = `<svg><use href="#i-refresh"/></svg><span>${esc(sw.reason || "已自动切换到更适合任务的模型")}：<b>${esc(sw.to)}</b></span>`;
  }

  function renderKbTags(row, names) {
    const box = $(".kb-tags", row);
    if (!box || !names || !names.length) return;
    box.hidden = false;
    box.innerHTML = names.map((x) => `<span>知识库 · ${esc(x)}</span>`).join("");
  }

  function renderWebTags(row, web) {
    const box = $(".web-tags", row);
    if (!box || !web) return;
    if (web.skipped) {
      box.hidden = false;
      box.innerHTML = `<span class="web-skip"><svg><use href="#i-search"/></svg>联网 · 已跳过：${esc(web.skipped)}</span>`;
      return;
    }
    const sources = Array.isArray(web.sources) ? web.sources : [];
    if (web.error && !sources.length) {
      box.hidden = false;
      box.innerHTML = `<span class="web-fail">联网 · ${esc(web.error)}</span>`;
      return;
    }
    if (!sources.length) return;
    box.hidden = false;
    const q = web.query ? `检索词：${web.query}` : "联网来源";
    const label = web.query ? `联网 · ${web.query}` : "联网来源";
    const links = sources.map((s, i) => {
      const href = s.url || "";
      if (!/^(https?:\/\/|\/)/i.test(href)) {
        const text = `${i + 1}. ${s.title || "来源"}`;
        return `<span class="web-link" title="${esc(s.title || "")}">${esc(text)}</span>`;
      }
      const short = `${i + 1}. ${s.title || s.url}`;
      return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="${esc(s.url)}">${esc(short)}</a>`;
    }).join("");
    box.innerHTML = `<span class="web-label" title="${esc(q)}"><svg><use href="#i-search"/></svg>${esc(label)}</span>${links}`;
  }

  const AGENT_TOOL_LABELS = {
    search_knowledge_base: "检索知识库",
    search_library: "检索资料库",
    search_web: "联网检索",
    read_attachments: "读取附件",
  };

  function renderAgentAction(row, action = {}) {
    const box = $(".agent-trace", row);
    if (!box || !action || !action.tool) return;
    box.hidden = false;
    const label = AGENT_TOOL_LABELS[action.tool] || action.tool;
    const query = action.arguments && action.arguments.query ? String(action.arguments.query) : "";
    const status = action.status || "ok";
    const count = Number(action.count || 0);
    let note = "";
    if (status === "skip") note = " · 跳过";
    else if (status === "error") note = " · 失败";
    else if (count && ["search_knowledge_base", "search_library", "search_web"].includes(action.tool)) {
      note = ` · ${count} 条`;
    }
    const item = document.createElement("div");
    item.className = `agent-action ${status === "error" ? "error" : (status === "skip" ? "skip" : "ok")}`;
    item.title = String(action.summary || "");
    item.innerHTML = `<svg><use href="#i-brain"/></svg><span>${esc(label)}${query ? `：${esc(query)}` : ""}${esc(note)}</span>`;
    box.appendChild(item);
    scrollBottom(false);
  }

  function fileExpiry(f, nowMs = Date.now()) {
    const exp = Number(f && f.expires_at) || 0;
    const deleted = Number(f && f.deleted_at) || 0;
    if ((f && f.cleaned) || deleted > 0) {
      return { state: "cleaned", download: false, badge: "已清理",
        text: `已于 ${f.deleted_text || fmtTime(deleted)} 自动清理`, title: "文件已到期并被自动清理，请重新生成" };
    }
    if ((f && f.expired) || (exp > 0 && exp * 1000 <= nowMs)) {
      return { state: "expired", download: false, badge: "已过期",
        text: `已于 ${f.expires_text || fmtTime(exp)} 到期`, title: "文件已过期，下载入口已关闭" };
    }
    if (!exp) return { state: "none", download: true, badge: "", text: "", title: "" };
    const days = Math.max(0, Math.ceil((exp * 1000 - nowMs) / 86400000));
    const warn = Number(f.warn_days) || 3;
    if (days <= warn) {
      return { state: "soon", download: true, badge: `剩 ${days} 天`,
        text: `仅剩 ${days} 天 · ${f.expires_text || fmtTime(exp)} 到期`, title: "到期后会自动删除，请尽快下载" };
    }
    return { state: "active", download: true, badge: "",
      text: `有效至 ${f.expires_text || fmtTime(exp)} · 剩 ${days} 天`, title: "" };
  }

  function renderFiles(row, files) {
    const box = $(".msg-files", row);
    if (!box || !files || !files.length) return;
    box.hidden = false;
    box.innerHTML = files.map((f) => {
      const kind = (f.kind || "docx").toLowerCase();
      const expiry = fileExpiry(f);
      const body = `<span class="file-ico">${esc(f.short || kind.toUpperCase())}</span>
        <span class="file-meta"><b>${esc(f.name)}</b><span>${esc(f.label || "文件")} · ${fmtBytes(Number(f.size) || 0)}</span>
        ${expiry.text ? `<span class="file-expiry">${esc(expiry.text)}</span>` : ""}</span>`;
      if (!expiry.download) {
        return `<div class="file-card ${expiry.state}" title="${esc(expiry.title)}">${body}
          <span class="file-dl">${esc(expiry.badge)}</span></div>`;
      }
      return `<div class="file-card ${expiry.state}" data-kind="${esc(kind)}" title="${esc(expiry.title)}">${body}
        <span class="file-actions">
          <button type="button" class="file-act" data-preview-file="${esc(f.id)}" data-file-name="${esc(f.name)}">
            <svg><use href="#i-file"/></svg>预览</button>
          <a class="file-dl" href="${esc(f.url)}" download="${esc(f.name)}" title="${esc(expiry.title || `下载 ${f.name}`)}">
            <svg><use href="#i-download"/></svg>下载</a>
        </span></div>`;
    }).join("");
  }

  function openFilePreview(fileId, name) {
    closeFilePreview();
    const wrap = document.createElement("div");
    wrap.className = "file-preview-wrap";
    wrap.innerHTML = `
      <div class="file-preview-scrim" data-close-preview></div>
      <div class="file-preview-panel" role="dialog" aria-modal="true" aria-label="文件预览">
        <div class="file-preview-head">
          <span class="file-preview-title"><svg><use href="#i-file"/></svg><b>${esc(name || "文件预览")}</b></span>
          <span class="file-preview-acts">
            <a class="btn ghost sm" href="/api/files/generated/${esc(fileId)}" download>下载</a>
            <button type="button" class="btn ghost sm" data-close-preview aria-label="关闭">关闭</button>
          </span>
        </div>
        <div class="file-preview-body"><div class="file-preview-loading">正在打开预览…</div>
          <iframe title="文件预览" src="/api/files/generated/${esc(fileId)}/preview?embed=1"></iframe>
        </div>
        <div class="file-preview-foot">看到排版不满意，直接回对话里点“重新生成”即可。</div>
      </div>`;
    document.body.appendChild(wrap);
    const frame = $("iframe", wrap);
    if (frame) frame.addEventListener("load", () => {
      const loading = $(".file-preview-loading", wrap);
      if (loading) loading.remove();
    });
    document.addEventListener("keydown", filePreviewEsc);
  }

  function closeFilePreview() {
    $$(".file-preview-wrap").forEach((el) => el.remove());
    document.removeEventListener("keydown", filePreviewEsc);
  }

  function filePreviewEsc(ev) {
    if (ev.key === "Escape") closeFilePreview();
  }

  function renderActions(row, content) {
    const box = $(".msg-actions", row);
    if (!box) return;
    box.innerHTML = `
      <button type="button" data-copy-text>${'<svg><use href="#i-copy"/></svg>'}复制</button>
      <button type="button" data-regen>${'<svg><use href="#i-refresh"/></svg>'}重新生成</button>`;
    box.dataset.content = content;
  }

  function scrollBottom(force = false) {
    const sc = $("#chatScroll");
    if (!sc) return;
    const near = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160;
    const go = () => { sc.scrollTop = sc.scrollHeight; };
    if (force || near) {
      go();
      if (force) requestAnimationFrame(() => requestAnimationFrame(go));
    }
  }

  /* 轻量 Markdown：先转义，再处理常用语法；不执行 HTML/脚本。 */
  function mdLang(lang) {
    const key = String(lang || "").toLowerCase();
    const map = {
      py: "Python", python: "Python", js: "JavaScript", javascript: "JavaScript",
      ts: "TypeScript", typescript: "TypeScript", sh: "Shell", bash: "Shell", shell: "Shell",
      ps1: "PowerShell", powershell: "PowerShell", json: "JSON", html: "HTML",
      css: "CSS", sql: "SQL", yml: "YAML", yaml: "YAML", md: "Markdown",
      java: "Java", go: "Go", rust: "Rust", c: "C", cpp: "C++", csharp: "C#",
    };
    return map[key] || (key ? key.toUpperCase() : "代码");
  }

  function mdCode(lang, code, open = false) {
    const body = String(code || "").replace(/^\n+|\n+$/g, "");
    const copy = open ? "" : `<button type="button" class="md-code-copy" data-copy-code><svg><use href="#i-copy"/></svg>复制</button>`;
    return `<div class="md-code${open ? " is-open" : ""}"><div class="md-code-head"><span>${esc(mdLang(lang))}</span>${copy}</div><pre><code>${esc(body)}</code></pre></div>`;
  }

  function mdInline(text) {
    return text
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  }

  function renderMarkdown(src, opts = {}) {
    let text = String(src || "");
    const blocks = [];
    text = text.replace(/```([a-zA-Z0-9_+.-]*)[ \t]*\r?\n?([\s\S]*?)```/g, (_, lang, code) => {
      const i = blocks.length;
      blocks.push(mdCode(lang, code));
      return `\n\u0000BLOCK${i}\u0000\n`;
    });
    if (opts.streaming) {
      const openAt = text.lastIndexOf("```");
      if (openAt >= 0) {
        const tail = text.slice(openAt + 3);
        const lang = (tail.match(/^[a-zA-Z0-9_+.-]*/) || [""])[0];
        const code = tail.slice(lang.length).replace(/^\r?\n/, "");
        const i = blocks.length;
        blocks.push(mdCode(lang, code, true));
        text = `${text.slice(0, openAt)}\n\u0000BLOCK${i}\u0000\n`;
      }
    }
    const work = esc(text);
    const lines = work.split(/\r?\n/);
    const out = [];
    let list = null;
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    const isTableSep = (s) => /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(s);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trimEnd();
      if (!line.trim()) { closeList(); continue; }
      const codeBlock = line.match(/^\u0000BLOCK(\d+)\u0000$/);
      if (codeBlock) {
        closeList();
        out.push(blocks[Number(codeBlock[1])] || "");
        continue;
      }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        closeList();
        const n = h[1].length;
        out.push(`<h${n}>${mdInline(h[2])}</h${n}>`);
        continue;
      }
      if (/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
        closeList();
        out.push("<hr>");
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        closeList();
        const cells = (s) => s.trim().replace(/^\||\|$/g, "").split("|").map((x) => x.trim());
        const head = cells(line);
        const rows = [];
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          rows.push(cells(lines[i]));
          i++;
        }
        i--;
        out.push(`<div class="md-table-wrap"><table><thead><tr>${head.map((c) => `<th>${mdInline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${head.map((_, c) => `<td>${mdInline(r[c] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ul || ol) {
        const type = ul ? "ul" : "ol";
        if (list !== type) { closeList(); out.push(`<${type}>`); list = type; }
        out.push(`<li>${mdInline((ul || ol)[1])}</li>`);
        continue;
      }
      if (/^\s*&gt;\s+/.test(line)) {
        closeList();
        out.push(`<blockquote>${mdInline(line.replace(/^\s*&gt;\s+/, ""))}</blockquote>`);
        continue;
      }
      closeList();
      out.push(`<p>${mdInline(line)}</p>`);
    }
    closeList();
    const html = out.join("").replace(/\u0000BLOCK(\d+)\u0000/g, (_, i) => blocks[Number(i)] || "");
    return `<div class="md">${html}${opts.streaming ? '<span class="md-caret" aria-hidden="true"></span>' : ""}</div>`;
  }

  function closeImagePreview() {
    document.querySelector(".img-viewer")?.remove();
  }

  function openImagePreview(src, name) {
    closeImagePreview();
    const box = document.createElement("div");
    box.className = "img-viewer";
    box.innerHTML = `<button type="button" class="img-viewer-close" aria-label="关闭">×</button>
      <img src="${esc(src)}" alt="${esc(name || "图片")}">
      <div class="img-viewer-name">${esc(name || "图片")}</div>`;
    box.addEventListener("click", (ev) => {
      if (ev.target.closest(".img-viewer-close") || ev.target === box) closeImagePreview();
    });
    document.body.appendChild(box);
  }
