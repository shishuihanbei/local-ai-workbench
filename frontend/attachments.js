/* 用户端 · 附件上传、OCR 状态与预览 | 原 app.js 第 1330–1425 行 */
"use strict";
  /* ------------------------------------------------------------------ 附件 */
  function fmtBytes(n) {
    const size = Number(n) || 0;
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  function hasImageAttachments() {
    return (S.attachments || []).some((f) => f.kind === "image");
  }

  function renderVisionHint() {
    const hint = $("#attachVisionHint");
    if (!hint) return;
    if (!hasImageAttachments()) {
      hint.hidden = true;
      hint.textContent = "";
      hint.classList.remove("is-warn");
      return;
    }
    hint.hidden = false;
    const model = selectedModel();
    if (model && model.vision) {
      hint.classList.remove("is-warn");
      hint.textContent = `当前模型 ${model.label || model.key} 会直接读取图片。`;
      return;
    }
    const vision = (S.models || []).find((m) => m.vision && modelRunnable(m));
    hint.classList.add("is-warn");
    hint.textContent = vision
      ? `当前模型不能看图；可用 ${modelLabel(vision)}。`
      : "当前没有可用的视觉模型：先到「模型」页拉取 Qwen2.5-VL 3B 等，或仅用 OCR 文字。";
  }

  function preferVisionModel() {
    if (!hasImageAttachments()) return false;
    const model = selectedModel();
    if (model && model.vision) {
      renderVisionHint();
      return true;
    }
    const vision = (S.models || []).find((m) => m.vision && modelRunnable(m));
    if (vision) {
      setModel(vision.key);
      toast(`已切换到视觉模型 ${modelLabel(vision)} 来读取图片`);
      renderVisionHint();
      return true;
    }
    renderVisionHint();
    return false;
  }

  function renderAttachments() {
    const box = $("#attachList");
    if (!box) return;
    box.hidden = !S.attachments.length;
    box.innerHTML = S.attachments.map((f) => `
      <div class="attach-card">
        ${f.kind === "image"
          ? `<img src="${esc(f.url)}" alt="${esc(f.name)}">`
          : `<span class="attach-file-ico"><svg><use href="#i-file"/></svg></span>`}
        <span class="attach-meta"><b>${esc(f.name)}</b><span>${FILE_KINDS[f.kind] || "文件"} · ${fmtBytes(f.size)}</span></span>
        <button class="attach-remove" type="button" data-remove-att="${f.id}" title="移除"><svg><use href="#i-close"/></svg></button>
      </div>`).join("");
    renderVisionHint();
  }

  async function removeAttachment(id) {
    S.attachments = S.attachments.filter((f) => Number(f.id) !== Number(id));
    renderAttachments();
    try {
      await fetch(`/api/chat/files/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": cookie("wb_csrf") },
      });
    } catch {}
  }

  async function clearPendingAttachments(removeRemote = true) {
    const items = S.attachments.slice();
    S.attachments = [];
    renderAttachments();
    if (!removeRemote) return;
    await Promise.all(items.map((f) => fetch(`/api/chat/files/${f.id}`, {
      method: "DELETE", credentials: "same-origin",
      headers: { "X-CSRF-Token": cookie("wb_csrf") },
    }).catch(() => {})));
  }

  async function uploadFiles(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    if (files.length + S.attachments.length > 5) return toast("一条消息最多带 5 个附件");
    const seq = S.openedConversation;
    let libAdded = 0;
    S.uploading = true;
    $("#attachBtn").disabled = true;
    for (const file of files) {
      if (file.size > 20 * 1024 * 1024) { toast(`${file.name} 超过 20MB`); continue; }
      toast(`正在上传 ${file.name}…`);
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        const res = await fetch("/api/chat/files", {
          method: "POST", credentials: "same-origin",
          headers: { "X-CSRF-Token": cookie("wb_csrf") }, body: fd,
        });
        if (res.status === 401) {
          S.uploading = false;
          $("#attachBtn").disabled = false;
          showAuth();
          return;
        }
        const raw = await res.text();
        let data = null;
        try { data = JSON.parse(raw); } catch {}
        if (!res.ok) throw new Error(errorText(data, `上传失败（${res.status}）`));
        if (seq !== S.openedConversation) {
          fetch(`/api/chat/files/${data.id}`, {
            method: "DELETE", credentials: "same-origin",
            headers: { "X-CSRF-Token": cookie("wb_csrf") },
          }).catch(() => {});
          continue;
        }
        S.attachments.push(data);
        renderAttachments();
        if (data.library && data.library.status === "added") {
          libAdded += 1;
          S.libraryLoadedAt = 0;
        }
      } catch (e) {
        toast(e.message || "上传失败");
      }
    }
    if (libAdded) toast(`已同时加入个人资料库 ${libAdded} 个文件，可在聊天框「资料库」中反复选用`);
    if (hasImageAttachments()) preferVisionModel();
    S.uploading = false;
    $("#attachBtn").disabled = false;
    $("#fileInput").value = "";
  }

