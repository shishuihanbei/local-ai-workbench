/* 用户端 · 设置：账号、知识库、资料库、选择器、API、对话、数据、输入布局 | 原 app.js 第 2188–3261 行 */
"use strict";
  /* ------------------------------------------------------------------ 设置：账号 */
  async function openSettings(tab = "account") {
    $("#settingsDrawer").hidden = false;
    selectDrawerTab(tab);
    loadSessions().catch(() => {});
    if (tab === "api") loadApi().catch((e) => toast(e.message));
  }

  function closeSettings() { $("#settingsDrawer").hidden = true; closeBind(); }

  function selectDrawerTab(tab) {
    const feature = FRONT_TAB_FEATURE[tab];
    if (feature && !frontOn(feature)) tab = "account";
    S.drawerTab = tab;
    $$("#drawerTabs button").forEach((b) => b.classList.toggle("active", b.dataset.dtab === tab));
    $$(".dpanel").forEach((p) => p.classList.toggle("active", p.id === `dpanel-${tab}`));
    if (tab === "account") loadSessions().catch(() => {});
    if (tab === "account") loadIdentities().catch(() => {});
    if (tab === "api") loadApi().catch((e) => toast(e.message));
    if (tab === "chat") applyChatPrefsToUI(true);
    if (tab === "kb") loadMyKb().catch((e) => toast(e.message));
    if (tab === "library") loadMyLibrary().catch((e) => toast(e.message));
    if (tab === "memory") loadMyMemory().catch((e) => toast(e.message));
  }

  /* ------------------------------------------------------------------ 设置：我的知识库 */
  function myKbError(text) {
    const box = $("#myKbError");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function myKbNotice(text) {
    const box = $("#myKbNotice");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function applyMyKbState(d) {
    const personalOn = !!d.personal_enabled;
    const publicOn = !!d.public_enabled;
    $("#myKbToggle").checked = personalOn;
    $("#myKbToggleNote").textContent = personalOn
      ? "已开启。只有勾选下面的来源才会参与对话检索；随时可以关闭。"
      : "默认关闭。开启后才会把个人资料用于当前账号的对话检索，其他账号看不到。";
    $("#myKbUsePublic").checked = publicOn && !!d.use_public;
    $("#myKbUsePublic").disabled = !publicOn;
    $("#myKbPublicHint").textContent = publicOn ? "" : "（管理员已关闭）";
    $("#myKbUsePersonal").checked = personalOn && !!d.use_personal;
    $("#myKbUsePersonal").disabled = !personalOn;
    $("#myKbSourceState").textContent = personalOn ? "可多选" : "先开启个人知识库";
  }

  async function saveMyKbSettings(patch) {
    try {
      const d = await api("/api/my/kb/settings", { method: "POST", body: patch });
      applyMyKbState(d);
      toast("知识库设置已保存");
      return d;
    } catch (e) {
      myKbError(e.message);
      await loadMyKb().catch(() => {});
      throw e;
    }
  }

  function myKbDocsHtml(docs) {
    if (!docs.length) return `<div class="mine-empty">还没有个人文档。上传或粘贴一份资料，之后提问时会优先参考。</div>`;
    return docs.map((d) => `
      <div class="mine-item">
        <div><b title="${esc(d.title)}">${esc(d.title)}</b>
          <span>${esc(d.source || "manual")} · ${Number(d.chars || 0).toLocaleString()} 字 · ${esc(fmtTime(d.created_at))}</span></div>
        <button class="iconbtn small" data-kb-del="${d.id}" title="删除这篇文档"><svg><use href="#i-trash"/></svg></button>
      </div>`).join("");
  }

  async function loadMyKb() {
    const list = $("#myKbList");
    try {
      const d = await api("/api/my/kb");
      $("#myKbStat").textContent = `${d.count || 0} 篇 · ${Number(d.chars || 0).toLocaleString()} 字`;
      $("#myKbCount").textContent = `上限 ${d.max_docs || 200} 篇`;
      applyMyKbState(d);
      list.innerHTML = myKbDocsHtml(d.docs || []);
    } catch (e) {
      list.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function addMyKbText() {
    const title = $("#myKbTitle").value.trim();
    const content = $("#myKbContent").value.trim();
    myKbError("");
    myKbNotice("");
    if (!content) return myKbError("先粘贴正文再添加");
    const finalTitle = title || content.slice(0, 30) || "未命名资料";
    const fd = new FormData();
    fd.append("title", finalTitle);
    fd.append("content", content);
    try {
      const res = await formApi("/api/my/kb/text", fd);
      $("#myKbTitle").value = "";
      $("#myKbContent").value = "";
      myKbNotice(`已加入《${res.title || finalTitle}》：${Number(res.chars || content.length).toLocaleString()} 字，切成 ${res.chunks || 1} 段。`);
      toast("已加入我的知识库");
      await loadMyKb();
    } catch (e) { myKbNotice(""); myKbError(e.message); }
  }

  async function uploadMyKb(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    myKbError("");
    let added = 0;
    const failed = [];
    try {
      for (const [i, file] of files.entries()) {
        myKbNotice(`正在上传 ${i + 1}/${files.length}：《${file.name}》…`);
        const fd = new FormData();
        fd.append("file", file, file.name);
        try {
          await formApi("/api/my/kb/upload", fd);
          added += 1;
        } catch (e) {
          failed.push(`${file.name}：${e.message}`);
        }
      }
      if (added) {
        await loadMyKb();
        toast(added === 1 ? "文件已加入我的知识库" : `已上传 ${added} 个文件到我的知识库`);
      }
      myKbNotice(failed.length
        ? `上传完成：成功 ${added} 个，失败 ${failed.length} 个（${failed.join("；")}）`
        : `上传完成：${added} 个文件已加入我的知识库。`);
    } finally { $("#myKbFile").value = ""; }
  }

  async function searchMyKb() {
    const q = $("#myKbSearch").value.trim();
    const box = $("#myKbResults");
    if (!q) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="mine-empty">检索中…</div>`;
    try {
      const d = await api(`/api/my/kb/search?q=${encodeURIComponent(q)}`);
      const items = d.items || [];
      box.innerHTML = items.length ? items.map((x) => `
        <div class="mine-hit"><b>${esc(x.title)}</b><span>${esc(x.snippet)}</span></div>`).join("")
        : `<div class="mine-empty">个人库里没有匹配的资料。</div>`;
    } catch (e) {
      box.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function deleteMyKb(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.classList.add("warn");
      toast("再点一次确认删除这篇文档");
      setTimeout(() => { btn.dataset.armed = ""; btn.classList.remove("warn"); }, 3000);
      return;
    }
    try {
      await api(`/api/my/kb/${id}`, { method: "DELETE" });
      toast("文档已删除");
      $("#myKbResults").innerHTML = "";
      await loadMyKb();
    } catch (e) { toast(e.message); }
  }

  /* ------------------------------------------------------------------ 设置：我的资料库 */
  function myLibError(text) {
    const box = $("#myLibError");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function myLibNotice(text) {
    const box = $("#myLibNotice");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function applyMyLibState(d) {
    S.libraryState = d;
    const personalOn = !!d.personal_enabled;
    const globalOn = !!d.global_enabled;
    $("#myLibToggle").checked = personalOn;
    $("#myLibToggleNote").textContent = personalOn
      ? "已开启。聊天框「资料库」会列出你勾选来源里的资料，可多选并反复使用。"
      : "默认关闭。开启后才能挑选个人资料；总库还要管理员开启并在下面勾选。";
    $("#myLibUseGlobal").checked = globalOn && !!d.use_global;
    $("#myLibUseGlobal").disabled = !globalOn;
    $("#myLibGlobalHint").textContent = globalOn ? "" : "（管理员未开启）";
    $("#myLibUsePersonal").checked = personalOn && !!d.use_personal;
    $("#myLibUsePersonal").disabled = !personalOn;
    $("#myLibSourceState").textContent = (globalOn || personalOn) ? "可多选" : "先开启资料库";
    $("#myLibStat").textContent = `${d.count || 0} 篇 · ${Number(d.chars || 0).toLocaleString()} 字 · 引用 ${Number(d.uses || 0).toLocaleString()} 次`;
    $("#myLibCount").textContent = `上限 ${d.max_personal_docs || 100} 篇`;
  }

  async function saveMyLibSettings(patch) {
    try {
      const d = await api("/api/my/library/settings", { method: "POST", body: patch });
      applyMyLibState({ ...(S.libraryState || {}), ...d });
      toast("资料库设置已保存");
      S.libraryLoadedAt = 0;
      await loadLibraryPicker().catch(() => {});
      return d;
    } catch (e) {
      myLibError(e.message);
      await loadMyLibrary().catch(() => {});
      throw e;
    }
  }

  function libMetaHtml(d) {
    const folder = String(d.folder || "").trim();
    const tags = String(d.tags || "").split(",").map((x) => x.trim()).filter(Boolean);
    if (!folder && !tags.length) return "";
    return `<div class="lib-meta-line">
      ${folder ? `<span class="lib-meta-chip folder" title="${esc(folder)}">${esc(folder)}</span>` : ""}
      ${tags.map((t) => `<span class="lib-meta-chip">#${esc(t)}</span>`).join("")}
    </div>`;
  }

  function myLibDocsHtml(docs) {
    if (!docs.length) return `<div class="mine-empty">还没有个人资料。上传或粘贴一份资料，聊天时就能反复选用。</div>`;
    return docs.map((d) => `
      <div class="mine-item">
        <div><b title="${esc(d.title)}">${esc(d.title)}</b>
          <span>${esc(d.source || "manual")} · ${Number(d.chars || 0).toLocaleString()} 字 · 引用 ${Number(d.uses || 0)} 次${d.last_used_at ? ` · 最近 ${esc(fmtTime(d.last_used_at))}` : ""}</span>
          ${libMetaHtml(d)}</div>
        <div class="lib-item-actions">
          <button class="btn ghost sm" data-lib-open="${d.id}" title="查看资料正文">查看</button>
          <button class="btn ghost sm" data-lib-org="${d.id}" title="修改文件夹和标签">整理</button>
          <button class="iconbtn small" data-lib-del="${d.id}" title="删除这篇资料"><svg><use href="#i-trash"/></svg></button>
        </div>
      </div>`).join("");
  }

  function fillLibSelect(sel, items, allLabel, keep) {
    const current = keep !== undefined ? keep : sel.value;
    sel.innerHTML = `<option value="">${allLabel}</option>` +
      items.map((x) => `<option value="${esc(x.name)}">${esc(x.name)}（${x.count}）</option>`).join("");
    sel.value = current && items.some((x) => x.name === current) ? current : "";
  }

  function renderMyLibFacets(d) {
    const folders = d.folders || [];
    const tags = d.tags || [];
    fillLibSelect($("#myLibFolderFilter"), folders, "全部文件夹");
    fillLibSelect($("#myLibTagFilter"), tags, "全部标签");
    $("#myLibFolderOptions").innerHTML = folders
      .map((x) => `<option value="${esc(x.name)}"></option>`).join("");
  }

  function renderMyLibDocs() {
    const docs = S.myLibDocs || [];
    const folder = $("#myLibFolderFilter").value;
    const tag = $("#myLibTagFilter").value;
    const shown = docs.filter((d) => {
      if (folder && String(d.folder || "") !== folder) return false;
      if (tag && !String(d.tags || "").split(",").map((x) => x.trim()).includes(tag)) return false;
      return true;
    });
    $("#myLibList").innerHTML = shown.length
      ? myLibDocsHtml(shown)
      : `<div class="mine-empty">${docs.length ? "没有符合当前文件夹或标签的资料。" : "还没有个人资料。上传或粘贴一份资料，聊天时就能反复选用。"}</div>`;
  }

  async function loadMyLibrary() {
    const list = $("#myLibList");
    try {
      const d = await api("/api/my/library");
      applyMyLibState(d);
      S.myLibDocs = d.docs || [];
      renderMyLibFacets(d);
      renderMyLibDocs();
    } catch (e) {
      list.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  function openMyLibOrg(id) {
    const d = (S.myLibDocs || []).find((x) => String(x.id) === String(id));
    if (!d) return toast("这篇资料不在当前列表里，先刷新资料再整理");
    S.myLibOrgId = d.id;
    $("#myLibOrgTitle").value = d.title || "";
    $("#myLibOrgFolder").value = d.folder || "";
    $("#myLibOrgTags").value = d.tags || "";
    $("#myLibOrgError").hidden = true;
    $("#myLibOrg").hidden = false;
    $("#myLibOrg").scrollIntoView({ block: "nearest" });
  }

  function closeMyLibOrg() {
    S.myLibOrgId = null;
    $("#myLibOrg").hidden = true;
    $("#myLibOrgError").hidden = true;
  }

  async function saveMyLibOrg() {
    const id = S.myLibOrgId;
    if (!id) return;
    const title = $("#myLibOrgTitle").value.trim();
    if (!title) {
      $("#myLibOrgError").textContent = "标题不能为空";
      $("#myLibOrgError").hidden = false;
      return;
    }
    try {
      const d = await api(`/api/my/library/${id}`, {
        method: "PATCH",
        body: {
          title,
          folder: $("#myLibOrgFolder").value.trim(),
          tags: $("#myLibOrgTags").value.trim(),
        },
      });
      closeMyLibOrg();
      toast("分类已保存");
      S.libraryLoadedAt = 0;
      await loadMyLibrary();
      await loadLibraryPicker(true).catch(() => {});
      if (d && d.id) openMyLibDoc(d.id).catch(() => {});
    } catch (e) {
      $("#myLibOrgError").textContent = e.message;
      $("#myLibOrgError").hidden = false;
    }
  }

  async function addMyLibText() {
    const title = $("#myLibTitle").value.trim();
    const content = $("#myLibContent").value.trim();
    myLibError("");
    myLibNotice("");
    if (!content) return myLibError("先粘贴正文再添加");
    const finalTitle = title || content.slice(0, 30) || "未命名资料";
    const fd = new FormData();
    fd.append("title", finalTitle);
    fd.append("content", content);
    fd.append("folder", $("#myLibFolder").value.trim());
    fd.append("tags", $("#myLibTags").value.trim());
    try {
      const res = await formApi("/api/my/library/text", fd);
      $("#myLibTitle").value = "";
      $("#myLibContent").value = "";
      myLibNotice(`已加入《${res.title || finalTitle}》：${Number(res.chars || content.length).toLocaleString()} 字，切成 ${res.chunks || 1} 段。`);
      toast("已加入个人资料库");
      S.libraryLoadedAt = 0;
      await loadMyLibrary();
      await loadLibraryPicker().catch(() => {});
    } catch (e) { myLibNotice(""); myLibError(e.message); }
  }

  async function uploadMyLib(fileList) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    myLibError("");
    let added = 0;
    const failed = [];
    try {
      for (const [i, file] of files.entries()) {
        myLibNotice(`正在上传 ${i + 1}/${files.length}：《${file.name}》…`);
        const fd = new FormData();
        fd.append("file", file, file.name);
        fd.append("folder", $("#myLibFolder").value.trim());
        fd.append("tags", $("#myLibTags").value.trim());
        try {
          await formApi("/api/my/library/upload", fd);
          added += 1;
        } catch (e) {
          failed.push(`${file.name}：${e.message}`);
        }
      }
      if (added) {
        S.libraryLoadedAt = 0;
        $("#myLibResults").innerHTML = "";
        await loadMyLibrary();
        await loadLibraryPicker().catch(() => {});
        toast(added === 1 ? "文件已加入个人资料库" : `已上传 ${added} 个文件到个人资料库`);
      }
      myLibNotice(failed.length
        ? `上传完成：成功 ${added} 个，失败 ${failed.length} 个（${failed.join("；")}）`
        : `上传完成：${added} 个文件已加入个人资料库。`);
    } finally { $("#myLibFile").value = ""; }
  }

  async function searchMyLib() {
    const q = $("#myLibSearch").value.trim();
    const box = $("#myLibResults");
    if (!q) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="mine-empty">检索中…</div>`;
    try {
      const d = await api(`/api/my/library/search?q=${encodeURIComponent(q)}`);
      const items = d.items || [];
      box.innerHTML = items.length ? items.map((x) => `
        <div class="mine-hit" data-lib-hit="${x.doc_id}" role="button" tabindex="0"><b>${esc(x.title)}</b><span>${esc(x.snippet)}</span></div>`).join("")
        : `<div class="mine-empty">个人资料库里没有匹配的资料。</div>`;
    } catch (e) {
      box.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function openMyLibDoc(id) {
    const d = await api(`/api/my/library/doc/${id}`);
    const cls = [d.folder ? `文件夹：${d.folder}` : "", d.tags ? `标签：${d.tags}` : ""].filter(Boolean).join(" · ");
    $("#myLibViewTitle").textContent = `${d.title} · ${Number(d.chars || 0).toLocaleString()} 字${cls ? ` · ${cls}` : ""}`;
    $("#myLibViewBody").textContent = d.content || "（正文为空）";
    $("#myLibView").hidden = false;
    $("#myLibView").scrollIntoView({ block: "nearest" });
  }

  async function deleteMyLib(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.classList.add("warn");
      toast("再点一次确认删除这篇资料");
      setTimeout(() => { btn.dataset.armed = ""; btn.classList.remove("warn"); }, 3000);
      return;
    }
    try {
      await api(`/api/my/library/${id}`, { method: "DELETE" });
      toast("资料已删除");
      S.librarySelected = S.librarySelected.filter((x) => String(x) !== String(id));
      S.libraryLoadedAt = 0;
      $("#myLibResults").innerHTML = "";
      await loadMyLibrary();
      await loadLibraryPicker().catch(() => {});
    } catch (e) { toast(e.message); }
  }

  /* ------------------------------------------------------------------ 聊天：资料库选择器 */
  function libPickerNotice(text) {
    const box = $("#libPickerNotice");
    if (!box) return;
    box.textContent = text || "";
    box.hidden = !text;
  }

  function updateLibBadge() {
    const count = S.librarySelected.length;
    const badge = $("#libBtnCount");
    badge.hidden = count === 0;
    badge.textContent = String(count);
    $("#libBtn").classList.toggle("active", count > 0);
    $("#libBtn").title = count
      ? `已选 ${count} 篇资料，会随每条消息带入`
      : "从资料库挑选本次要带入的资料";
  }

  function renderLibPicker() {
    const list = $("#libPickerList");
    const items = S.libraryItems || [];
    const max = Number((S.libraryState || {}).max_docs || 10);
    const q = String(S.libraryQuery || "").trim().toLowerCase();
    const folders = (S.libraryState || {}).folders || [];
    const tags = (S.libraryState || {}).tags || [];
    fillLibSelect($("#libPickerFolder"), folders, "全部文件夹");
    fillLibSelect($("#libPickerTag"), tags, "全部标签");
    const folder = $("#libPickerFolder").value;
    const tag = $("#libPickerTag").value;
    const shown = items.filter((d) => {
      if (folder && String(d.folder || "") !== folder) return false;
      if (tag && !String(d.tags || "").split(",").map((x) => x.trim()).includes(tag)) return false;
      return q
        ? `${d.title || ""} ${d.source || ""} ${d.folder || ""} ${d.tags || ""}`.toLowerCase().includes(q)
        : true;
    });
    if (!items.length) {
      const st = S.libraryState || {};
      const effectiveGlobal = !!st.global_enabled && !!st.use_global;
      const effectivePersonal = !!st.personal_enabled && !!st.use_personal;
      let why = "资料库里还没有可用资料。";
      if (!st.global_enabled && !st.personal_enabled) {
        why = "资料库未开启。到「设置 → 资料库」开启个人库；总库需管理员开启。";
      } else if (!effectiveGlobal && !effectivePersonal) {
        why = st.global_enabled
          ? "到「设置 → 资料库」勾选「总资料库」，或开启个人资料并上传。"
          : "到「设置 → 资料库」开启个人资料并上传。";
      } else if (effectivePersonal) {
        why = "个人资料库还没有内容，先到设置里上传一份。";
      }
      list.innerHTML = `<div class="mine-empty">${esc(why)}</div>`;
    } else if (!shown.length) {
      list.innerHTML = `<div class="mine-empty">没有匹配的资料，换个关键词或清除文件夹/标签筛选。</div>`;
    } else {
      list.innerHTML = shown.map((d) => {
        const on = S.librarySelected.some((x) => String(x) === String(d.id));
        const personal = d.scope === "personal";
        const full = !on && S.librarySelected.length >= max;
        return `<label class="lib-pick-row ${on ? "on" : ""} ${full ? "full" : ""}">
          <input type="checkbox" data-lib-pick="${d.id}" ${on ? "checked" : ""} ${full ? "disabled" : ""}>
          <span class="lib-pick-copy"><b>${esc(d.title)}</b><em>${personal ? "个人资料" : "总资料库"} · ${Number(d.chars || 0).toLocaleString()} 字 · 已用 ${Number(d.uses || 0)} 次</em>${libMetaHtml(d)}</span>
        </label>`;
      }).join("");
    }
    $("#libPickerHint").textContent = S.librarySelected.length
      ? `已选 ${S.librarySelected.length} / ${max} 篇，将随每条消息重复带入`
      : `最多可选 ${max} 篇；不选则不使用资料库`;
    updateLibBadge();
  }

  async function loadLibraryPicker(force = false) {
    if (!force && Date.now() - (S.libraryLoadedAt || 0) < 5000) { renderLibPicker(); return; }
    const d = await api("/api/my/library/picker");
    S.libraryState = { ...(S.libraryState || {}), ...d };
    S.libraryItems = d.items || [];
    const available = S.libraryItems.map((x) => String(x.id));
    S.librarySelected = S.librarySelected.filter((id) => available.includes(String(id)));
    S.libraryLoadedAt = Date.now();
    renderLibPicker();
  }

  function setLibMenu(open) {
    $("#libMenu").hidden = !open;
    $("#libBtn").setAttribute("aria-expanded", String(open));
  }

  async function openLibMenu() {
    const opening = $("#libMenu").hidden;
    setLibMenu(opening);
    if (!opening) return;
    setSkillMenu(false);
    libPickerNotice("");
    S.libraryQuery = "";
    $("#libPickerSearch").value = "";
    $("#libPickerFolder").value = "";
    $("#libPickerTag").value = "";
    $("#libPickerList").innerHTML = `<div class="empty-line">读取中…</div>`;
    try {
      await loadLibraryPicker(true);
    } catch (e) {
      $("#libPickerList").innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
      libPickerNotice("读取资料库失败：" + e.message);
    }
  }

  function toggleLibDoc(id, on) {
    const max = Number((S.libraryState || {}).max_docs || 10);
    if (on && S.librarySelected.length >= max) {
      libPickerNotice(`单次最多选 ${max} 篇，先取消一篇再选。`);
      renderLibPicker();
      return;
    }
    libPickerNotice("");
    if (on) {
      if (!S.librarySelected.some((x) => String(x) === String(id))) S.librarySelected.push(Number(id));
    } else {
      S.librarySelected = S.librarySelected.filter((x) => String(x) !== String(id));
    }
    renderLibPicker();
  }

  function clearLibSelection() {
    S.librarySelected = [];
    libPickerNotice("");
    renderLibPicker();
    toast("已清空资料库选择");
  }


  function myMemError(text) {
    const box = $("#myMemError");
    box.textContent = text || "";
    box.hidden = !text;
  }

  function myMemListHtml(items) {
    if (!items.length) return `<div class="mine-empty">还没有记忆。你明确说出的偏好会被自动保存，也可以手动添加。</div>`;
    return items.map((m) => `
      <div class="mine-item">
        <div><b title="${esc(m.content)}">${esc(m.content)}</b>
          <span>${esc(m.source === "auto" ? "自动记住" : "手动添加")} · 命中 ${Number(m.hits || 0)} 次 · ${esc(fmtTime(m.updated_at))}</span></div>
        <button class="iconbtn small" data-mem-del="${m.id}" title="删除这条记忆"><svg><use href="#i-trash"/></svg></button>
      </div>`).join("");
  }

  function myMemNoteText(d) {
    if (!d.global_enabled) {
      return "管理员还没有开启长期记忆总开关。你可以先在这里维护自己的记忆，但总开关打开前不会参与对话。";
    }
    if (!d.user_enabled) return "你还没有开启长期记忆。当前对话只参考最近 20 条消息。";
    return "已开启。对话会参考与你问题相关的记忆，最多 6 条；随时可以关闭，已有条目不会删除。";
  }

  async function loadMyMemory() {
    const list = $("#myMemList");
    try {
      const d = await api("/api/my/memory");
      $("#myMemToggle").checked = !!d.user_enabled;
      $("#myMemStat").textContent = `${Number(d.stats.total || 0)} 条`;
      $("#myMemNote").textContent = myMemNoteText(d);
      list.innerHTML = myMemListHtml(d.items || []);
    } catch (e) {
      list.innerHTML = `<div class="mine-empty">${esc(e.message)}</div>`;
    }
  }

  async function toggleMyMemory(on) {
    myMemError("");
    try {
      const d = await api("/api/my/memory/toggle", { method: "POST", body: { enabled: on } });
      if (on && !d.global_enabled) toast("已保存你的选择，但管理员总开关还未开启");
      else toast(on ? "已开启长期记忆" : "已关闭长期记忆");
      await loadMyMemory();
    } catch (e) {
      $("#myMemToggle").checked = !on;
      myMemError(e.message);
    }
  }

  async function addMyMemory() {
    const content = $("#myMemInput").value.trim();
    myMemError("");
    if (!content) return myMemError("先写下要记住的内容");
    try {
      await api("/api/my/memory/items", { method: "POST", body: { content } });
      $("#myMemInput").value = "";
      toast("已添加记忆");
      await loadMyMemory();
    } catch (e) { myMemError(e.message); }
  }

  async function clearMyMemory(btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "再点一次确认清空";
      setTimeout(() => {
        btn.dataset.armed = "";
        btn.textContent = "清空我的记忆";
      }, 3000);
      return;
    }
    try {
      await api("/api/my/memory/clear", { method: "POST", body: {} });
      btn.dataset.armed = "";
      btn.textContent = "清空我的记忆";
      toast("我的记忆已清空");
      await loadMyMemory();
    } catch (e) { myMemError(e.message); }
  }

  async function deleteMyMemory(id, btn) {
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.classList.add("warn");
      toast("再点一次确认删除这条记忆");
      setTimeout(() => { btn.dataset.armed = ""; btn.classList.remove("warn"); }, 3000);
      return;
    }
    try {
      await api(`/api/my/memory/items/${id}`, { method: "DELETE" });
      toast("记忆已删除");
      await loadMyMemory();
    } catch (e) { toast(e.message); }
  }

  async function loadSessions() {
    const box = $("#deviceList");
    try {
      const d = await api("/api/auth/sessions");
      const items = d.items || [];
      box.innerHTML = items.length ? items.map((x) => `
        <div class="device-row">
          <div><b>${esc(shortUA(x.ua))}</b><span>${esc(x.ip || "未知 IP")} · ${esc(fmtTime(x.created_at))}</span></div>
          <span class="badge ${x.current ? "good" : ""}">${x.current ? "当前设备" : "在线"}</span>
        </div>`).join("") : `<div class="empty-line">没有其他登录设备</div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty-line">${esc(e.message)}</div>`;
    }
  }

  async function loadIdentities() {
    const box = $("#identityList");
    if (!box) return;
    try {
      const d = await api("/api/auth/identities");
      const items = d.items || [];
      const providers = (d.providers || []).filter((p) => p.key !== "username");
      const bound = new Set(items.map((i) => i.provider));
      const rows = items.map((i) => `
        <div class="device-row">
          <div><b>${esc(i.label || i.provider)}</b><span>${esc(i.masked || i.provider_uid)} · 已绑定</span></div>
          <span class="badge good">已绑定</span>
        </div>`);
      for (const p of providers) {
        if (bound.has(p.key)) continue;
        const canOtp = (p.key === "phone" || p.key === "email") && p.enabled && p.ready;
        const state = p.enabled
          ? (p.ready ? "已配置" : "配置不完整")
          : "接口已预留";
        rows.push(`
          <div class="device-row">
            <div><b>${esc(p.label)}</b><span>未绑定 · ${esc(state)}</span></div>
            ${canOtp
              ? `<button class="btn ghost sm" type="button" data-bind="${esc(p.key)}">立即绑定</button>`
              : `<span class="badge">${p.enabled && p.ready ? "待接入" : "未启用"}</span>`}
          </div>`);
      }
      box.innerHTML = rows.join("") || `<div class="empty-line">暂无登录方式</div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty-line">${esc(e.message)}</div>`;
    }
  }

  function openBind(channel) {
    if (channel !== "phone" && channel !== "email") return;
    S.bindChannel = channel;
    const form = $("#bindForm");
    form.hidden = false;
    form.reset();
    $("#bindError").hidden = true;
    const isPhone = channel === "phone";
    $("#bindTitle").textContent = isPhone ? "绑定手机号" : "绑定邮箱";
    $("#bindTargetLabel").textContent = isPhone ? "手机号" : "邮箱";
    $("#bindTarget").type = isPhone ? "tel" : "email";
    $("#bindTarget").autocomplete = isPhone ? "tel" : "email";
    $("#bindTarget").placeholder = isPhone ? "请输入手机号" : "请输入邮箱地址";
    $("#bindSend").disabled = false;
    $("#bindSend").textContent = "发送验证码";
    setTimeout(() => $("#bindTarget").focus(), 60);
  }

  function closeBind() {
    S.bindChannel = "";
    const form = $("#bindForm");
    if (form) form.hidden = true;
  }

  function bindTargetValue() {
    return $("#bindTarget").value.trim();
  }

  function bindTargetProblem() {
    const target = bindTargetValue();
    if (!target) return S.bindChannel === "phone" ? "请输入手机号" : "请输入邮箱地址";
    if (S.bindChannel === "phone" && !/^\+?\d{6,20}$/.test(target)) return "手机号格式不正确";
    if (S.bindChannel === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) return "邮箱格式不正确";
    return "";
  }

  async function sendBindCode() {
    const err = $("#bindError");
    err.hidden = true;
    const problem = bindTargetProblem();
    if (problem) return bindError(problem);
    const btn = $("#bindSend");
    btn.disabled = true;
    let left = 60;
    btn.textContent = `${left}s 后重发`;
    const timer = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = "重新发送";
      } else {
        btn.textContent = `${left}s 后重发`;
      }
    }, 1000);
    try {
      const data = await api("/api/auth/otp/send", {
        method: "POST",
        body: { channel: S.bindChannel, target: bindTargetValue() },
      });
      toast(data && data.msg ? data.msg : "验证码已发送，请查收");
    } catch (e) {
      clearInterval(timer);
      btn.disabled = false;
      btn.textContent = "发送验证码";
      bindError(e.message);
    }
  }

  async function submitBind(ev) {
    ev.preventDefault();
    const err = $("#bindError");
    err.hidden = true;
    const problem = bindTargetProblem();
    if (problem) return bindError(problem);
    const code = $("#bindCode").value.replace(/\s+/g, "");
    if (!/^\d{6}$/.test(code)) return bindError("请输入 6 位数字验证码");
    const btn = $("#bindSubmit");
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = "绑定中…";
    try {
      const data = await api("/api/auth/identities/bind", {
        method: "POST",
        body: { channel: S.bindChannel, target: bindTargetValue(), code },
      });
      toast(data.msg || "绑定成功");
      closeBind();
      await loadIdentities();
    } catch (e) {
      bindError(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  function bindError(msg) {
    const el = $("#bindError");
    el.textContent = msg;
    el.hidden = false;
  }

  function shortUA(ua) {
    const s = String(ua || "");
    if (!s) return "未知设备";
    if (/Edg\//.test(s)) return "Microsoft Edge";
    if (/Chrome\//.test(s) && !/Chromium/.test(s)) return "Chrome 浏览器";
    if (/Safari\//.test(s) && !/Chrome/.test(s)) return "Safari 浏览器";
    if (/Firefox\//.test(s)) return "Firefox 浏览器";
    if (/Android/.test(s)) return "Android 设备";
    if (/iPhone|iPad/.test(s)) return "iPhone / iPad";
    return s.slice(0, 48);
  }

  async function changePassword(ev) {
    ev.preventDefault();
    const oldp = $("#pwOld").value;
    const newp = $("#pwNew").value;
    const confirm = $("#pwConfirm").value;
    const err = $("#pwError");
    err.hidden = true;
    if (!oldp) return showPwError("请输入当前密码");
    if (newp.length < 8) return showPwError("新密码至少 8 位");
    if (newp !== confirm) return showPwError("两次输入的新密码不一致");
    const btn = $("#pwSubmit");
    btn.disabled = true;
    btn.textContent = "保存中…";
    try {
      await api("/api/auth/password", { method: "POST", body: { old_password: oldp, new_password: newp } });
      $("#pwForm").reset();
      toast("密码已修改，其他设备需要重新登录");
      await loadSessions();
    } catch (e) {
      showPwError(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "保存新密码";
    }
  }

  function showPwError(msg) {
    $("#pwError").textContent = msg;
    $("#pwError").hidden = false;
  }

  async function revokeOthers() {
    try {
      await api("/api/auth/sessions/revoke-others", { method: "POST" });
      toast("已退出其他设备");
      await loadSessions();
    } catch (e) { toast(e.message); }
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST", noAuth: true });
    } catch {}
    S.user = null;
    S.prefs = null;
    S.librarySelected = [];
    S.libraryItems = [];
    S.libraryState = null;
    S.libraryLoadedAt = 0;
    closeSettings();
    showAuth({ initialized: true, allow_register: S.allowRegister });
  }

  /* ------------------------------------------------------------------ 设置：API */
  async function loadApi() {
    const [ctx, keys] = await Promise.all([
      api("/api/api-keys/context"),
      api("/api/api-keys"),
    ]);
    S.apiCtx = ctx;
    S.apiKeys = keys.items || [];
    renderApi();
  }

  function renderApi() {
    const ctx = S.apiCtx;
    if (!ctx) return;
    const net = ctx.network || {};
    const scope = net.scope || "local";
    $("#apiScopeDot").className = "scope-dot " + scope;
    $("#apiScope").textContent = `${net.label || "本机"}访问`;
    $("#apiScopeHint").textContent = net.hint || "";
    const base = (ctx.api && ctx.api.recommended_base) || "";
    $("#apiAddress").innerHTML = `<span class="mono">${esc(base || "暂不可用")}</span>
      ${base ? `<button class="iconbtn small" id="copyBase" title="复制地址"><svg><use href="#i-copy"/></svg></button>` : ""}`;

    const urls = ctx.urls || [];
    const wanted = ["recommended", "local", "lan", "public"];
    const seenUrls = new Set();
    const visibleUrls = wanted.map((k) => urls.find((x) => x.key === k)).filter(Boolean).filter((u) => {
      const dedupeKey = u.url || ("empty:" + u.key);
      if (seenUrls.has(dedupeKey)) return false;
      seenUrls.add(dedupeKey);
      return true;
    });
    $("#apiUrls").innerHTML = visibleUrls.map((u) => `
      <div class="api-url ${u.url ? "" : "empty"}">
        <div><span>${esc(u.label)}</span><b>${esc(u.url || "暂不可用")}</b></div>
        ${u.url && u.key === "recommended" ? `<span class="badge good">推荐</span>` : ""}
        ${u.url ? `<button class="iconbtn small" data-copy-value="${esc(u.url)}" title="复制"><svg><use href="#i-copy"/></svg></button>` : ""}
      </div>`).join("");

    $("#keyList").innerHTML = S.apiKeys.length ? S.apiKeys.map((k) => `
      <div class="key-row">
        <div><b>${esc(k.name)}</b><span class="mono">${esc(k.masked)} · ${k.last_used_at ? "最近 " + relTime(k.last_used_at) : "从未使用"}${k.last_scope ? " · " + esc(k.last_scope) : ""}</span></div>
        ${k.revoked ? `<span class="badge bad">已撤销</span>` : `<span class="badge good">正常</span>`}
        ${k.revoked ? "" : `<button class="btn ghost" data-revoke-key="${k.id}">撤销</button>`}
      </div>`).join("") : `<div class="empty-line">还没有 API Key。给 Key 起个名字，点“生成 Key”。</div>`;

    const model = ctx.default_model || (ctx.models && ctx.models[0] && ctx.models[0].id) || "7b";
    const curl = `curl "${base}/chat/completions" \\\n  -H "Authorization: Bearer <你的 API Key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"${model}","messages":[{"role":"user","content":"你好"}],"stream":false}'`;
    const python = `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="${base}",\n    api_key="<你的 API Key>",\n)\n\nresp = client.chat.completions.create(\n    model="${model}",\n    messages=[{"role": "user", "content": "你好"}],\n)\nprint(resp.choices[0].message.content)`;
    S.apiDocs = { curl, python };
    $("#apiCurl").textContent = curl;
    $("#apiPython").textContent = python;
  }

  async function createApiKey() {
    const btn = $("#createKeyBtn");
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      const d = await api("/api/api-keys", {
        method: "POST",
        body: { name: $("#keyName").value.trim() },
      });
      S.apiKeys = [d.item, ...S.apiKeys];
      $("#keyName").value = "";
      $("#secretBox").hidden = false;
      $("#secretValue").value = d.key;
      $("#secretValue").dataset.copy = d.key;
      renderApi();
      $("#secretValue").focus();
      $("#secretValue").select();
    } catch (e) { toast(e.message); }
    finally {
      btn.disabled = false;
      btn.textContent = "生成 Key";
    }
  }

  async function revokeKey(id, btn) {
    if (!btn) return;
    if (btn.dataset.armed !== "1") {
      const old = btn.innerHTML;
      btn.dataset.armed = "1";
      btn.classList.add("armed");
      btn.textContent = "再点一次撤销";
      clearTimeout(revokeKey._t);
      revokeKey._t = setTimeout(() => {
        btn.dataset.armed = "";
        btn.classList.remove("armed");
        btn.innerHTML = old;
      }, 3200);
      return;
    }
    btn.dataset.armed = "";
    btn.classList.remove("armed");
    btn.disabled = true;
    try {
      await api(`/api/api-keys/${id}`, { method: "DELETE" });
      toast("Key 已撤销");
      await loadApi();
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------------ 设置：对话 */
  function applyChatPrefsToUI(includeSystemPrompt = true) {
    if (!S.prefs) return;
    $("#setTemp").value = S.prefs.temperature;
    $("#tempValue").textContent = Number(S.prefs.temperature).toFixed(1);
    $("#setMaxTokens").value = S.prefs.maxTokens;
    $("#setKb").checked = !!S.prefs.useKb;
    if (includeSystemPrompt) {
      $("#setSystemPrompt").value = S.cid ? S.convSystemPrompt : (S.prefs.systemPrompt || "");
      $("#sysPromptScope").textContent = S.cid ? "（当前对话）" : "（用于新对话）";
    }
  }

  async function saveChatPrefs() {
    const max = clamp(parseInt($("#setMaxTokens").value, 10) || 2048, 64, 8192);
    const temp = clamp(parseFloat($("#setTemp").value) || 0.7, 0, 1.5);
    const promptText = $("#setSystemPrompt").value.trim();
    savePrefs({ temperature: temp, maxTokens: max, useKb: $("#setKb").checked });
    if (S.cid) {
      try {
        await api(`/api/chat/conversations/${S.cid}`, { method: "PATCH", body: { system_prompt: promptText } });
        S.convSystemPrompt = promptText;
      } catch (e) {
        toast(e.message);
        return;
      }
    } else {
      savePrefs({ systemPrompt: promptText });
    }
    applyChatPrefsToUI(true);
    toast("生成参数已保存");
  }

  function resetChatPrefs() {
    const fallback = S.models.find((m) => m.loaded) || S.models[0];
    savePrefs({ ...PREF_DEFAULT, model: fallback ? fallback.key : "" });
    S.convSystemPrompt = "";
    if (S.cid) {
      api(`/api/chat/conversations/${S.cid}`, { method: "PATCH", body: { system_prompt: "" } }).catch(() => {});
    }
    applyChatPrefsToUI(true);
    if (fallback) setModel(fallback.key, false);
    toast("已恢复默认");
  }

  /* ------------------------------------------------------------------ 设置：数据 */
  async function exportData() {
    try {
      const res = await fetch("/api/auth/export", { credentials: "same-origin" });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(errorText(data, "导出失败"));
      }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const name = (cd.match(/filename="([^"]+)"/) || [])[1] || "workbench-export.json";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1200);
      toast("导出完成");
    } catch (e) { toast(e.message); }
  }

  async function clearAllConversations() {
    try {
      await api("/api/chat/conversations/clear-all", { method: "POST" });
      newChat();
      await loadConversations();
      toast("所有对话已清空");
    } catch (e) { toast(e.message); }
  }

  /* ------------------------------------------------------------------ 输入与布局 */
  function autoResizeInput() {
    const el = $("#messageInput");
    el.style.height = "auto";
    el.style.height = Math.min(170, Math.max(40, el.scrollHeight)) + "px";
  }

  function openSidebar() {
    $("#appView").classList.add("side-open");
    $("#scrim").hidden = false;
  }

  function closeSidebar() {
    $("#appView").classList.remove("side-open");
    $("#scrim").hidden = true;
  }

