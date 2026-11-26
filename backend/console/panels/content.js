/* 控制台 · 本地前端与穿透、知识库、网站分享 | 原 console.js 第 3836–5136 行 */
/* ---------------------------------------------------------------- 本地前端 / 内网穿透 */
async function loadFrontendSettings() {
  const st = await api("/api/system/settings");
  S.frontendUrl = String(st.frontend_url || "").trim();
  S.frontendAuto = !!st.frontend_url_auto;
  S.frontendConfigured = String(st.frontend_url_configured || "").trim();
  S.requestOrigin = String(st.request_origin || "").trim();
  updateFrontendUI();
}

function updateFrontendUI() {
  const btn = $("frontendBtn");
  btn.disabled = !S.frontendUrl;
  btn.title = S.frontendUrl ? `打开 ${S.frontendUrl}` : "当前访问地址不可用";
  if ($("frontendUrl")) $("frontendUrl").value = S.frontendUrl;
  if ($("frontendHint")) {
    $("frontendHint").textContent = S.frontendUrl
      ? (S.frontendAuto
        ? `已根据当前登录访问地址自动设置：${S.frontendUrl}（无需保存即可打开）`
        : `当前保存的前端地址：${S.frontendUrl}`)
      : "未取得当前访问地址；请检查反向代理的 Host / X-Forwarded-Host 配置。";
  }
}

async function openFrontendPage() {
  if (!S.frontendUrl) {
    try { await loadFrontendSettings(); } catch (e) { /* 打开失败再提示 */ }
  }
  if (!S.frontendUrl) {
    if (S.tab !== "network") switchTab("network");
    if ($("frontendHint")) $("frontendHint").textContent = "当前访问地址不可用，请检查控制台访问地址。";
    return;
  }
  window.open(S.frontendUrl, "_blank", "noopener,noreferrer");
}

async function saveFrontendUrl() {
  const raw = $("frontendUrl").value.trim();
  if (!raw) throw new Error("请填写前端地址");
  let url;
  try { url = new URL(raw); } catch { throw new Error("前端地址格式不正确"); }
  if (!/^http(s)?:/.test(url.protocol)) throw new Error("只支持 http/https 地址");
  await api("/api/system/settings", { method: "PUT", body: JSON.stringify({ frontend_url: raw }) });
  S.frontendUrl = raw;
  S.frontendAuto = false;
  S.frontendConfigured = raw;
  updateFrontendUI();
  await loadTunnelStatus();
}

function tunnelTargetLabel(v) {
  return ({ panel: "管理控制台", api: "模型 API", frontend: "本地前端页面" })[v] || "管理控制台";
}

function renderTunnelStatus(st) {
  const on = !!st.running;
  const ready = on && !!st.ready;
  const failed = !on && !!st.error;
  const url = String(st.url || "");
  $("tunnelDot").classList.toggle("on", ready);
  $("tunnelDot").classList.toggle("warn", (on && !ready) || failed);
  $("tunnelState").textContent = on ? (ready ? "已开启，可以使用" : "正在连接…")
    : (failed ? "启动失败" : "未开启");
  $("tunnelSetup").hidden = on;
  $("tunnelActions").hidden = !on;
  $("tunnelStopBtn").hidden = !on;
  $("tunnelStopBtn").disabled = false;
  $("tunnelStopBtn").textContent = "停止穿透";
  $("tunnelCopyBtn").hidden = !ready || !url;
  $("tunnelCopyBtn").dataset.copy = url;
  $("tunnelOpenBtn").hidden = !ready || !url;
  $("tunnelOpenBtn").dataset.url = url;
  const hasBinary = !!st.binary;
  $("tunnelDownloadBtn").hidden = hasBinary;
  $("tunnelStartBtn").hidden = !hasBinary;
  $("tunnelTarget").disabled = on;
  const rows = [
    ["状态", on ? (ready ? "已开启，可以使用" : "正在连接，请稍等") : (failed ? "启动失败" : "未开启")],
    ["访问内容", tunnelTargetLabel(st.target_mode)],
    ["地址类型", st.mode === "token" ? "固定域名" : "免费临时地址"],
    ["公网地址", ready && url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>`
      : (on ? "正在准备地址…（通常 10 秒内）" : "—")],
    ["已运行", on && st.uptime ? `${Math.round(st.uptime)} 秒` : "—"],
  ];
  if (st.error) rows.push(["错误信息", esc(st.error)]);
  $("tunnelSummary").innerHTML = rows.map(([k, v]) =>
    `<div class="kv"><b>${esc(k)}</b><span>${v}</span></div>`).join("");

  if (!hasBinary) {
    $("tunnelHint").textContent = "第一次使用，请先点“下载穿透组件”。这是 Cloudflare 官方免费工具，下载后会自动放好。";
  } else if (failed) {
    $("tunnelHint").textContent = `上次启动失败：${st.error} 可展开下方连接日志查看详情，或稍后重试。`;
  } else if (on && !ready) {
    $("tunnelHint").textContent = "正在建立安全连接，通常需要 5–10 秒。等状态变成“已开启，可以使用”后再打开或复制地址。";
  } else if (ready) {
    $("tunnelHint").textContent = "地址已经可以使用。关闭穿透后这个地址会失效，下次开启会生成新地址。";
  } else {
    $("tunnelHint").textContent = "点击“一键开启免费穿透”即可，不需要公网 IP，也不用设置路由器。";
  }
}

async function loadTunnelStatus() {
  const st = await api("/api/tunnel/status");
  renderTunnelStatus(st);
  return st;
}

async function loadTunnelLog() {
  try {
    const d = await api("/api/tunnel/log?tail=150");
    $("tunnelLog").textContent = (d.lines || []).join("\n") || "暂无日志";
  } catch { /* 日志失败不影响状态 */ }
}

async function loadNetwork() {
  const st = await api("/api/tunnel/status");
  if (!S.networkLoaded) {
    S.frontendUrl = String(st.frontend_url || S.frontendUrl || "").trim();
    updateFrontendUI();
    $("tunnelTarget").value = ["panel", "api", "frontend"].includes(st.target_mode) ? st.target_mode : "panel";
    $("tunnelMode").value = st.mode === "token" ? "token" : "quick";
    $("tunnelDomain").value = st.tunnel_domain || "";
    S.networkLoaded = true;
  }
  renderTunnelStatus(st);
  await loadTunnelLog();
}

async function startTunnel() {
  const target = $("tunnelTarget").value;
  if (!["panel", "api", "frontend"].includes(target)) throw new Error("请选择要远程访问的内容");
  const mode = $("tunnelMode").value === "token" ? "token" : "quick";
  const btn = $("tunnelStartBtn");
  btn.disabled = true;
  btn.textContent = "正在开启…";
  try {
    await api("/api/tunnel/start", {
      method: "POST",
      body: JSON.stringify({ mode, token: $("tunnelToken").value.trim(),
        domain: $("tunnelDomain").value.trim(), target }),
    });
    await loadNetwork();
  } catch (e) {
    btn.disabled = false;
    try { await loadNetwork(); } catch { /* 让错误先展示 */ }
    throw e;
  } finally {
    btn.textContent = "一键开启免费穿透";
  }
}

async function stopTunnel() {
  const btn = $("tunnelStopBtn");
  btn.disabled = true;
  btn.textContent = "正在停止…";
  try {
    await api("/api/tunnel/stop", { method: "POST" });
    await loadNetwork();
  } finally {
    btn.disabled = false;
    btn.textContent = "停止穿透";
  }
}

function openTunnelUrl() {
  const url = $("tunnelOpenBtn").dataset.url || "";
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

async function downloadCloudflared() {
  const btn = $("tunnelDownloadBtn");
  btn.disabled = true;
  btn.textContent = "下载中…";
  try {
    await api("/api/tunnel/download", { method: "POST" });
    await loadNetwork();
  } finally {
    btn.disabled = false;
    btn.textContent = "下载穿透组件";
  }
}

function sizeText(n) {
  n = Number(n || 0);
  if (n >= 2 ** 30) return (n / 2 ** 30).toFixed(2) + " GB";
  if (n >= 2 ** 20) return (n / 2 ** 20).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

async function fetchArchive(path, fallbackName, options = {}) {
  const r = await fetch(path, {
    ...options,
    headers: {
      ...(token() ? { Authorization: "Bearer " + token() } : {}),
      ...(options.headers || {}),
    },
  });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
  if (!r.ok) {
    let msg = "操作失败";
    try { msg = (await r.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename="?([^";]+)"?/i.exec(cd);
  return { blob, name: m ? m[1] : fallbackName };
}

function saveArchive(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function setBackupNotice(text, kind = "info") {
  const box = $("backupNotice");
  const body = $("backupNoticeText");
  if (!box || !body) return;
  if (!text) {
    box.hidden = true;
    box.className = "backup-notice";
    body.textContent = "";
    return;
  }
  box.hidden = false;
  box.className = `backup-notice ${kind}`;
  body.textContent = text;
}

function setMigrationActions(show) {
  const local = S.localClient !== false;
  for (const id of ["openMigrationFolderBtn", "downloadMigrationFileBtn"]) {
    const el = $(id);
    // 远程（另一台电脑/外网）访问时后端无法操作服务器桌面，直接不显示“打开文件夹”
    if (el) el.hidden = !show || (id === "openMigrationFolderBtn" && !local);
    if (!show) el.textContent = id === "openMigrationFolderBtn" ? "打开文件夹" : "下载到浏览器";
  }
}

async function downloadBackup() {
  const btn = $("backupBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在打包…";
  setBackupNotice("正在生成完整备份，完成前请勿关闭页面。", "info");
  $("backupTitle").textContent = "正在生成备份";
  $("backupBadge").textContent = "处理中";
  $("backupBadge").className = "badge warn";
  try {
    const { blob, name } = await fetchArchive("/api/system/backup", `workbench-backup-${Date.now()}.zip`);
    saveArchive(blob, name);
    await loadBackupPage();
    $("backupTitle").textContent = "备份已下载";
    $("backupBadge").textContent = "完成";
    $("backupBadge").className = "badge good";
    $("backupMeta").textContent = `${name} · ${sizeText(blob.size)} · 已保存到浏览器下载目录`;
    setBackupNotice(`备份已下载：${name}。文件在浏览器默认下载目录。`, "good");
  } catch (e) {
    $("backupTitle").textContent = "备份失败";
    $("backupBadge").textContent = "失败";
    $("backupBadge").className = "badge bad";
    setBackupNotice(`备份失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function downloadMigration() {
  const btn = $("migrationBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成迁移包…";
  setBackupNotice("正在把程序、数据库、密钥和配置打进一个 zip；模型文件较大，不会打包。", "info");
  setMigrationActions(false);
  $("backupTitle").textContent = "正在打包程序和数据";
  $("backupBadge").textContent = "处理中";
  $("backupBadge").className = "badge warn";
  $("backupDesc").textContent = "迁移包会保存到下面的默认目录，不经过浏览器弹窗。";
  try {
    const d = await api("/api/system/migration?save=1", { method: "POST" });
    S.lastMigration = d;
    await loadBackupPage();
    $("backupTitle").textContent = "迁移包已生成";
    $("backupBadge").textContent = "已保存";
    $("backupBadge").className = "badge good";
    $("backupMeta").textContent = `${d.name} · ${sizeText(d.size)} · ${d.path}`;
    setBackupNotice(`迁移包已保存到：${d.path}\n新电脑解压后双击“一键迁移-双击我.bat”。`, "good");
    setMigrationActions(true);
  } catch (e) {
    $("backupTitle").textContent = "迁移包生成失败";
    $("backupBadge").textContent = "失败";
    $("backupBadge").className = "badge bad";
    setBackupNotice(`迁移包生成失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function openMigrationFolder() {
  try {
    const d = await api("/api/system/open-migration-folder", { method: "POST" });
    setBackupNotice(`已打开文件夹：${d.path}`, "good");
  } catch (e) {
    setBackupNotice(`打开文件夹失败：${e.message}`, "bad");
  }
}

async function downloadMigrationFile() {
  const d = S.lastMigration;
  if (!d || !d.download_url) {
    setBackupNotice("请先生成迁移包。", "warn");
    return;
  }
  try {
    const { blob, name } = await fetchArchive(d.download_url, d.name);
    saveArchive(blob, name);
    setBackupNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setBackupNotice(`下载失败：${e.message}`, "bad");
  }
}

/* ---------------------------------------------------------------- 知识库 */
function kbSourceLabel(source) {
  const s = String(source || "").trim();
  if (!s || s === "manual") return "手动文本";
  return s;
}

function renderKbRows() {
  const all = (S.kb && S.kb.docs) || [];
  const q = String(($("kbFilter") && $("kbFilter").value) || "").trim().toLowerCase();
  const scope = String(($("kbScopeFilter") && $("kbScopeFilter").value) || "all");
  const owner = String(($("kbUserFilter") && $("kbUserFilter").value) || "");
  const rows = all.filter((d) => {
    if (scope !== "all" && (d.scope || "global") !== scope) return false;
    if (owner && String(d.user_id || "") !== owner) return false;
    if (!q) return true;
    return `${d.title || ""} ${d.source || ""} ${d.username || ""}`.toLowerCase().includes(q);
  });
  if (!rows.length) {
    $("kbRows").innerHTML = `<tr><td colspan="7"><span class="hint">${all.length ? "没有匹配的文档，换个筛选条件试试。" : "还没有文档。管理员可添加公共库；用户个人库由用户在用户端上传。"}</span></td></tr>`;
    return;
  }
  $("kbRows").innerHTML = rows.map((d) => {
    const pending = String(S.kbPendingDelete) === String(d.id);
    const isPersonal = (d.scope || "global") === "personal";
    const ownerText = isPersonal ? (d.username || `用户 #${d.user_id || "?"}`) : "公共库";
    return `<tr>
      <td><div class="name">${esc(d.title || "未命名")}</div><div class="sub">#${esc(d.id)}</div></td>
      <td>${isPersonal ? esc(ownerText) : `<span class="hint">${esc(ownerText)}</span>`}</td>
      <td><span class="badge ${isPersonal ? "good" : ""}">${isPersonal ? "个人库" : "公共库"}</span></td>
      <td><span class="kb-source">${esc(kbSourceLabel(d.source))}</span></td>
      <td>${fmtInt(d.chars)}</td>
      <td>${fmtTime(d.created_at)}</td>
      <td><div class="ops"><button class="btn small ghost" data-kbview="${esc(d.id)}">查看</button><button class="btn small ${pending ? "danger" : ""}" data-kbdel="${esc(d.id)}">${pending ? "确认删除" : "删除"}</button></div></td>
    </tr>`;
  }).join("");
}

function fillKbUserFilter(docs) {
  const sel = $("kbUserFilter");
  if (!sel) return;
  const current = sel.value;
  const users = [];
  const seen = new Set();
  for (const d of docs) {
    if ((d.scope || "global") !== "personal" || !d.user_id) continue;
    const key = String(d.user_id);
    if (seen.has(key)) continue;
    seen.add(key);
    users.push({ id: key, name: d.username || `用户 #${d.user_id}` });
  }
  users.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  sel.innerHTML = `<option value="">全部账号</option>` + users.map((u) =>
    `<option value="${esc(u.id)}">${esc(u.name)} · #${esc(u.id)}</option>`).join("");
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

async function viewKbDocument(id) {
  const d = await api(`/api/kb/doc/${encodeURIComponent(id)}`);
  S.kbViewing = String(id);
  $("kbDocTitle").textContent = d.title || "未命名文档";
  const personal = (d.scope || "global") === "personal";
  $("kbDocMeta").textContent = `#${d.id} · ${personal ? (d.username || `用户 #${d.user_id}`) + " · 个人库" : "公共库"} · ${fmtInt(d.chars)} 字 · ${fmtTime(d.created_at)} · 来源 ${kbSourceLabel(d.source)}`;
  $("kbDocContent").textContent = d.content || "（正文为空）";
  $("kbDocView").hidden = false;
  $("kbDocView").scrollIntoView({ block: "nearest" });
}

function closeKbDocument() {
  S.kbViewing = null;
  $("kbDocView").hidden = true;
  $("kbDocContent").textContent = "";
}

async function loadKbPage() {
  const d = await api("/api/kb?scope=all");
  S.kb = d;
  const docs = d.docs || [];
  const enabled = !!d.enabled;
  const topK = Number(d.top_k || 3);
  const cards = [
    ["全部文档", fmtInt(d.all_count), "公共库 + 用户个人库"],
    ["公共库", fmtInt(d.global_count), "管理员维护，所有账号可检索"],
    ["个人库", fmtInt(d.personal_count), `${fmtInt(d.personal_users)} 个账号在使用`],
    ["检索状态", enabled ? "已开启" : "已关闭", enabled ? `每次返回 ${topK} 段` : "对话不会检索知识库"],
  ];
  $("kbCards").innerHTML = cards.map(([k, v, s]) => `
    <div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
  fillKbUserFilter(docs);
  $("kbDocHint").textContent = `${fmtInt(d.all_count)} 篇 · 公共 ${fmtInt(d.global_count)} / 个人 ${fmtInt(d.personal_count)} · 共 ${fmtInt(d.all_chars)} 字`;
  $("kbEnabled").checked = enabled;
  $("kbTopK").value = topK;
  $("kbSettingsHint").textContent = enabled
    ? `当前每次返回 ${topK} 段。段数太多会占用上下文，太少可能漏掉关键信息。`
    : "知识库检索已关闭；入库文档仍保留，重新开启后继续使用。";
  S.kbPendingDelete = null;
  renderKbRows();
}

function openKbEditor() {
  $("kbTitle").value = "";
  $("kbContent").value = "";
  $("kbEditor").hidden = false;
  $("kbEditorHint").textContent = "正文为空不会入库；支持 Word/PDF/Excel/PPT 和图片 OCR，扫描件默认前 15 页，单文件不超过 20MB。";
  $("kbTitle").focus();
  $("kbEditor").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function kbUploadNotice(text, danger = false) {
  const box = $("kbUploadNotice");
  if (!box) return;
  box.textContent = text || "";
  box.hidden = !text;
  box.classList.toggle("danger", !!danger);
}

async function saveKbDocument() {
  const title = $("kbTitle").value.trim();
  const content = $("kbContent").value.trim();
  if (!title) throw new Error("请填写标题");
  if (!content) throw new Error("正文不能为空");
  kbUploadNotice("");
  const fd = new FormData();
  fd.append("title", title);
  fd.append("content", content);
  const res = await api("/api/kb/text", { method: "POST", body: fd });
  $("kbEditor").hidden = true;
  await loadKbPage();
  $("kbDocHint").textContent = `已入库：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  kbUploadNotice(`已添加公共文档：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

async function uploadKbFile(file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20MB");
  kbUploadNotice(`正在上传《${file.name}》…`);
  const fd = new FormData();
  fd.append("file", file, file.name);
  const res = await api("/api/kb/upload", { method: "POST", body: fd });
  await loadKbPage();
  $("kbDocHint").textContent = `已上传：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  kbUploadNotice(`上传完成：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

function renderKbSearch(items, query) {
  if (!items.length) {
    $("kbResults").innerHTML = `<div class="kb-empty">没有命中。换一个更短、更具体的关键词，或先补一份资料。</div>`;
    return;
  }
  $("kbResults").innerHTML = items.map((it) => {
    const personal = (it.scope || "global") === "personal";
    const owner = personal ? (it.username || `用户 #${it.user_id || "?"}`) : "公共库";
    return `
    <div class="kb-result">
      <div class="kb-result-head"><b>${esc(it.title || "未命名")}</b><span>#${esc(it.doc_id)} · ${esc(owner)} · ${personal ? "个人库" : "公共库"}</span></div>
      <p>${esc(it.snippet || "（没有摘要）")}</p>
    </div>`;
  }).join("");
}

async function searchKb() {
  const q = $("kbQuery").value.trim();
  if (!q) {
    $("kbResults").innerHTML = `<div class="kb-empty">先输入一个问题或关键词，例如“退款流程要几天？”。</div>`;
    return;
  }
  const d = await api("/api/kb/search?q=" + encodeURIComponent(q));
  S.kbSearchItems = d.items || [];
  renderKbSearch(S.kbSearchItems, q);
}

async function deleteKbDocument(id) {
  if (String(S.kbPendingDelete) !== String(id)) {
    S.kbPendingDelete = String(id);
    renderKbRows();
    $("kbDocHint").textContent = "再点一次“确认删除”才会真正删除该文档和索引。";
    return;
  }
  await api("/api/kb/" + encodeURIComponent(id), { method: "DELETE" });
  S.kbPendingDelete = null;
  if (String(S.kbViewing) === String(id)) closeKbDocument();
  await loadKbPage();
  $("kbDocHint").textContent = "文档已删除，对应检索片段也已清理。";
}

async function saveKbSettings() {
  const enabled = $("kbEnabled").checked;
  const topk = Math.max(1, Math.min(10, Number($("kbTopK").value) || 3));
  await api(`/api/kb/settings?enabled=${enabled}&top_k=${topk}`, { method: "POST" });
  $("kbTopK").value = topk;
  $("kbSettingsHint").textContent = `已保存：公共知识库检索${enabled ? "已开启" : "已关闭"}，每次返回 ${topk} 段。${enabled ? "用户仍需勾选「公共知识库」才会引用。" : "所有账号都不会引用公共库。"}`;
}

function libCategoryHtml(d) {
  const folder = String(d.folder || "").trim();
  const tags = String(d.tags || "").split(",").map((x) => x.trim()).filter(Boolean);
  if (!folder && !tags.length) return `<span class="hint">未分类</span>`;
  return `<div class="lib-cat">
    ${folder ? `<span class="badge folder" title="${esc(folder)}">${esc(folder)}</span>` : ""}
    ${tags.map((t) => `<span class="badge" title="${esc(t)}">#${esc(t)}</span>`).join("")}
  </div>`;
}

function fillLibOptionSelect(sel, items, allLabel) {
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = `<option value="">${allLabel}</option>` +
    items.map((x) => `<option value="${esc(x.name)}">${esc(x.name)}（${x.count}）</option>`).join("");
  sel.value = current && items.some((x) => x.name === current) ? current : "";
}

function renderLibraryRows() {
  const all = (S.library && S.library.docs) || [];
  const q = String(($("libFilter") && $("libFilter").value) || "").trim().toLowerCase();
  const scope = String(($("libScopeFilter") && $("libScopeFilter").value) || "all");
  const owner = String(($("libUserFilter") && $("libUserFilter").value) || "");
  const folder = String(($("libFolderFilter") && $("libFolderFilter").value) || "");
  const tag = String(($("libTagFilter") && $("libTagFilter").value) || "");
  const rows = all.filter((d) => {
    if (scope !== "all" && (d.scope || "global") !== scope) return false;
    if (owner && String(d.user_id || "") !== owner) return false;
    if (folder && String(d.folder || "") !== folder) return false;
    if (tag && !String(d.tags || "").split(",").map((x) => x.trim()).includes(tag)) return false;
    if (!q) return true;
    return `${d.title || ""} ${d.source || ""} ${d.username || ""} ${d.folder || ""} ${d.tags || ""}`.toLowerCase().includes(q);
  });
  if (!rows.length) {
    $("libRows").innerHTML = `<tr><td colspan="9"><span class="hint">${all.length ? "没有匹配的资料，换个筛选条件试试。" : "还没有资料。管理员可上传总库；用户个人资料由用户在用户端上传。"}</span></td></tr>`;
    return;
  }
  $("libRows").innerHTML = rows.map((d) => {
    const pending = String(S.libPendingDelete) === String(d.id);
    const isPersonal = (d.scope || "global") === "personal";
    const ownerText = isPersonal ? (d.username || `用户 #${d.user_id || "?"}`) : "总资料库";
    return `<tr>
      <td><div class="name">${esc(d.title || "未命名")}</div><div class="sub">#${esc(d.id)}</div></td>
      <td>${libCategoryHtml(d)}</td>
      <td>${isPersonal ? esc(ownerText) : `<span class="hint">${esc(ownerText)}</span>`}</td>
      <td><span class="badge ${isPersonal ? "good" : ""}">${isPersonal ? "个人库" : "总库"}</span></td>
      <td><span class="kb-source">${esc(kbSourceLabel(d.source))}</span></td>
      <td>${fmtInt(d.chars)}</td>
      <td>${fmtInt(d.uses || 0)} 次</td>
      <td>${d.last_used_at ? fmtTime(d.last_used_at) : "尚未引用"}</td>
      <td><div class="ops"><button class="btn small ghost" data-libview="${esc(d.id)}">查看</button><button class="btn small ghost" data-liborg="${esc(d.id)}">整理</button><button class="btn small ${pending ? "danger" : ""}" data-libdel="${esc(d.id)}">${pending ? "确认删除" : "删除"}</button></div></td>
    </tr>`;
  }).join("");
}

function fillLibUserFilter(docs) {
  const sel = $("libUserFilter");
  if (!sel) return;
  const current = sel.value;
  const users = [];
  const seen = new Set();
  for (const d of docs) {
    if ((d.scope || "global") !== "personal" || !d.user_id) continue;
    const key = String(d.user_id);
    if (seen.has(key)) continue;
    seen.add(key);
    users.push({ id: key, name: d.username || `用户 #${d.user_id}` });
  }
  users.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  sel.innerHTML = `<option value="">全部账号</option>` + users.map((u) =>
    `<option value="${esc(u.id)}">${esc(u.name)} · #${esc(u.id)}</option>`).join("");
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

async function loadLibraryPage() {
  const d = await api("/api/library?scope=all");
  S.library = d;
  const docs = d.docs || [];
  const enabled = !!d.enabled;
  const cards = [
    ["全部资料", fmtInt(d.all_count), "总资料库 + 用户个人库"],
    ["总资料库", fmtInt(d.global_count), enabled ? "已开启，用户可选" : "已关闭，聊天框不显示"],
    ["个人资料", fmtInt(d.personal_count), `${fmtInt(d.personal_users)} 个账号在上传`],
    ["累计引用", `${fmtInt(d.uses || 0)} 次`, "被聊天选用会累加，可反复使用"],
  ];
  $("libCards").innerHTML = cards.map(([k, v, s]) => `
    <div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
  fillLibUserFilter(docs);
  fillLibOptionSelect($("libFolderFilter"), d.folders || [], "全部文件夹");
  fillLibOptionSelect($("libTagFilter"), d.tags || [], "全部标签");
  $("libDocHint").textContent = `${fmtInt(d.all_count)} 篇 · 总库 ${fmtInt(d.global_count)} / 个人 ${fmtInt(d.personal_count)} · 共 ${fmtInt(d.all_chars)} 字 · 引用 ${fmtInt(d.uses || 0)} 次`;
  $("libEnabled").checked = enabled;
  $("libMaxDocs").value = Number(d.max_docs || 10);
  $("libMaxChars").value = Number(d.max_chars || 12000);
  $("libSettingsHint").textContent = enabled
    ? `总资料库已开启；用户还需勾选「总资料库」，单次最多带入 ${fmtInt(d.max_docs || 10)} 篇。`
    : "总资料库已关闭；用户聊天框中不会出现总库资料，个人资料不受影响。";
  S.libPendingDelete = null;
  renderLibraryRows();
}

function openLibEditor() {
  $("libTitle").value = "";
  $("libContent").value = "";
  $("libFolder").value = "";
  $("libTags").value = "";
  $("libEditor").hidden = false;
  $("libEditorHint").textContent = "正文为空不会入库；支持 Word/PDF/Excel/PPT 和图片 OCR，扫描件默认前 15 页，单文件不超过 20MB。";
  $("libTitle").focus();
  $("libEditor").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function libNotice(text, danger = false) {
  const box = $("libUploadNotice");
  if (!box) return;
  box.textContent = text || "";
  box.hidden = !text;
  box.classList.toggle("danger", !!danger);
}

async function saveLibDocument() {
  const title = $("libTitle").value.trim();
  const content = $("libContent").value.trim();
  if (!title) throw new Error("请填写标题");
  if (!content) throw new Error("正文不能为空");
  libNotice("");
  const fd = new FormData();
  fd.append("title", title);
  fd.append("content", content);
  fd.append("folder", $("libFolder").value.trim());
  fd.append("tags", $("libTags").value.trim());
  const res = await api("/api/library/text", { method: "POST", body: fd });
  $("libEditor").hidden = true;
  await loadLibraryPage();
  $("libDocHint").textContent = `已入库：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  libNotice(`已添加总库资料：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

async function uploadLibFile(file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20MB");
  libNotice(`正在上传《${file.name}》…`);
  const fd = new FormData();
  fd.append("file", file, file.name);
  fd.append("folder", ($("libFolder") && $("libFolder").value.trim()) || "");
  fd.append("tags", ($("libTags") && $("libTags").value.trim()) || "");
  const res = await api("/api/library/upload", { method: "POST", body: fd });
  await loadLibraryPage();
  $("libDocHint").textContent = `已上传：${res.title} · ${res.chunks} 段 · ${fmtInt(res.chars)} 字`;
  libNotice(`上传完成：《${res.title}》，${fmtInt(res.chars)} 字，切成 ${res.chunks} 段。`);
}

async function viewLibDocument(id) {
  const d = await api(`/api/library/doc/${encodeURIComponent(id)}`);
  $("libDocTitle").textContent = d.title || "未命名资料";
  const personal = (d.scope || "global") === "personal";
  const cls = [d.folder ? `文件夹：${d.folder}` : "", d.tags ? `标签：${d.tags}` : ""].filter(Boolean).join(" · ");
  $("libDocMeta").textContent = `#${d.id} · ${personal ? (d.username || `用户 #${d.user_id}`) + " · 个人库" : "总资料库"} · ${fmtInt(d.chars)} 字 · 引用 ${fmtInt(d.uses || 0)} 次 · ${fmtTime(d.created_at)} · 来源 ${kbSourceLabel(d.source)}${cls ? ` · ${cls}` : ""}`;
  $("libDocContent").textContent = d.content || "（正文为空）";
  $("libDocView").hidden = false;
  $("libDocView").scrollIntoView({ block: "nearest" });
}

function closeLibDocument() {
  $("libDocView").hidden = true;
  $("libDocContent").textContent = "";
}

function openLibOrganize(id) {
  const d = ((S.library && S.library.docs) || []).find((x) => String(x.id) === String(id));
  if (!d) throw new Error("这篇资料不在当前列表里，请刷新后再整理");
  S.libOrgId = d.id;
  $("libOrgDocTitle").textContent = `#${d.id} ${d.title || "未命名"}`;
  $("libOrgTitle").value = d.title || "";
  $("libOrgFolder").value = d.folder || "";
  $("libOrgTags").value = d.tags || "";
  $("libOrgError").hidden = true;
  $("libOrgError").textContent = "";
  $("libOrganize").hidden = false;
  $("libOrganize").scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("libOrgTitle").focus();
}

function closeLibOrganize() {
  S.libOrgId = null;
  $("libOrganize").hidden = true;
  $("libOrgError").hidden = true;
}

async function saveLibOrganize() {
  if (!S.libOrgId) throw new Error("请先选择要整理的资料");
  const title = $("libOrgTitle").value.trim();
  if (!title) throw new Error("标题不能为空");
  const body = JSON.stringify({
    title,
    folder: $("libOrgFolder").value.trim(),
    tags: $("libOrgTags").value.trim(),
  });
  const d = await api(`/api/library/${encodeURIComponent(S.libOrgId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body,
  });
  closeLibOrganize();
  await loadLibraryPage();
  $("libDocHint").textContent = `已整理：《${d.title}》 · ${d.folder || "未分类"}${d.tags ? ` · #${d.tags.replaceAll(",", " #")}` : ""}`;
  libNotice(`分类已保存：《${d.title}》${d.folder ? `，文件夹「${d.folder}」` : ""}${d.tags ? `，标签 ${d.tags}` : ""}。`);
}

async function deleteLibDocument(id) {
  if (String(S.libPendingDelete) !== String(id)) {
    S.libPendingDelete = String(id);
    renderLibraryRows();
    $("libDocHint").textContent = "再点一次“确认删除”才会真正删除该资料和索引。";
    return;
  }
  await api("/api/library/" + encodeURIComponent(id), { method: "DELETE" });
  S.libPendingDelete = null;
  closeLibDocument();
  await loadLibraryPage();
  $("libDocHint").textContent = "资料已删除，对应索引片段也已清理。";
}

async function saveLibSettings() {
  const enabled = $("libEnabled").checked;
  const maxDocs = Math.max(1, Math.min(30, Number($("libMaxDocs").value) || 10));
  const maxChars = Math.max(1000, Math.min(48000, Number($("libMaxChars").value) || 12000));
  const d = await api("/api/library/settings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, max_docs: maxDocs, max_chars: maxChars }),
  });
  $("libMaxDocs").value = d.max_docs;
  $("libMaxChars").value = d.max_chars;
  await loadLibraryPage();
  $("libSettingsHint").textContent = `已保存：总资料库${enabled ? "已开启" : "已关闭"}，单次最多 ${fmtInt(d.max_docs)} 篇 / ${fmtInt(d.max_chars)} 字。`;
}

async function backupLib() {
  const btn = $("libBackupBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成备份…";
  try {
    const { blob, name } = await fetchArchive("/api/library/export", "workbench-library.json");
    saveArchive(blob, name);
    $("libDocHint").textContent = `已下载 ${name} · ${sizeText(blob.size)}。`;
  } catch (e) {
    $("libDocHint").textContent = "备份失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function restoreLib() {
  const file = S.libRestoreFile;
  if (!file) throw new Error("请先选择备份文件");
  if (file.size > 16 * 1024 * 1024) throw new Error("备份文件超过 16MB");
  const fd = new FormData();
  fd.append("file", file, file.name);
  const d = await api("/api/library/restore", { method: "POST", body: fd });
  S.libRestoreFile = null;
  $("libRestoreFile").value = "";
  $("libRestoreBtn").disabled = true;
  await loadLibraryPage();
  const extra = d.failed ? `，失败 ${d.failed} 篇` : "";
  $("libRestoreHint").textContent = `恢复完成：新增 ${d.added} 篇，跳过同名 ${d.skipped} 篇${extra}。`;
}

function memoryKindLabel(kind) {
  if (kind === "preference") return "偏好";
  if (kind === "explicit") return "明确要求";
  return "事实";
}

function renderMemoryPage() {
  const d = S.memory || {};
  const enabled = !!d.enabled;
  const st = d.stats || {};
  $("memoryState").className = "badge " + (enabled ? "good" : "off");
  $("memoryState").textContent = enabled ? "已启用" : "已关闭 · 默认短期";
  $("memoryTitle").textContent = enabled
    ? "长期记忆已启用：跨对话保留，按相关度注入"
    : "长期记忆未启用：只用本次会话的最近上下文";
  $("memoryHint").textContent = enabled
    ? "新消息里的明确自述会自动入库；每条回复最多带入 6 条相关记忆，同一账号的其他对话也能用。"
    : "关闭后不会写入新记忆，也不会把旧记忆带进对话；已有条目会保留，随时可以再打开。";
  const btn = $("memoryToggleBtn");
  btn.textContent = enabled ? "关闭长期记忆" : "启用长期记忆";
  btn.className = "btn big " + (enabled ? "danger" : "primary");
  $("memoryStats").textContent = `${fmtInt(st.total)} 条 · 自动 ${fmtInt(st.auto)} · 手动 ${fmtInt(st.manual)} · ${fmtInt(st.users)} 个账号`;

  const select = $("memoryUser");
  const keep = select.value;
  const users = d.users || [];
  select.innerHTML = users.map((u) => `<option value="${esc(u.id)}">${esc(u.username)} · #${esc(u.id)}</option>`).join("");
  const target = keep || String(d.current_user_id || (users[0] && users[0].id) || "");
  if (target) select.value = target;

  const rows = d.items || [];
  if (!rows.length) {
    $("memoryRows").innerHTML = `<tr><td colspan="6"><span class="hint">还没有记忆条目。打开开关后，说一句“我叫…”或“记住…”就会自动出现；也可以在下面手动添加。</span></td></tr>`;
    return;
  }
  $("memoryRows").innerHTML = rows.map((m) => {
    const pending = String(S.memoryPendingDelete) === String(m.id);
    const src = m.source === "manual" ? "手动" : "自动";
    return `<tr>
      <td><div class="name">${esc(m.username || "—")}</div><div class="sub mono">#${esc(m.user_id)}</div></td>
      <td><div class="memory-text">${esc(m.content)}</div><div class="sub">${esc(memoryKindLabel(m.kind))} · #${esc(m.id)}</div></td>
      <td><span class="badge ${m.source === "manual" ? "ok" : "unknown"}">${src}</span></td>
      <td>${fmtInt(m.hits)}</td>
      <td>${fmtTime(m.updated_at)}</td>
      <td><div class="ops"><button class="btn small ${pending ? "danger" : ""}" data-memorydel="${esc(m.id)}">${pending ? "确认删除" : "删除"}</button></div></td>
    </tr>`;
  }).join("");
}

async function loadMemoryPage() {
  const d = await api("/api/admin/memory");
  S.memory = d;
  S.memoryPendingDelete = null;
  renderMemoryPage();
}

async function toggleMemory() {
  const d = S.memory || {};
  const next = !d.enabled;
  await api("/api/admin/memory/toggle", { method: "POST", body: JSON.stringify({ enabled: next }) });
  await loadMemoryPage();
  $("memoryHint").textContent = next
    ? "已启用。下一条消息开始，明确自述会自动入库，并在后续对话中按相关度带入。"
    : "已关闭。之后的对话只使用本次会话的最近上下文；已保存的条目仍然保留。";
}

async function addMemory() {
  const content = $("memoryInput").value.trim();
  const uid = Number($("memoryUser").value);
  if (!content) throw new Error("先写一句要记住的内容");
  if (!uid) throw new Error("先选择账号");
  await api("/api/admin/memory/items", { method: "POST", body: JSON.stringify({ content, user_id: uid }) });
  $("memoryInput").value = "";
  await loadMemoryPage();
  $("memoryAddHint").textContent = "已添加。下一条消息开始生效；重复内容会自动合并，不会重复占位。";
}

async function deleteMemory(id) {
  if (String(S.memoryPendingDelete) !== String(id)) {
    S.memoryPendingDelete = String(id);
    renderMemoryPage();
    $("memoryAddHint").textContent = "再点一次“确认删除”才会真正删除这条记忆。";
    return;
  }
  await api("/api/admin/memory/items/" + encodeURIComponent(id), { method: "DELETE" });
  S.memoryPendingDelete = null;
  await loadMemoryPage();
  $("memoryAddHint").textContent = "已删除，下一轮对话不再使用这条记忆。";
}

async function backupKb() {  const btn = $("kbBackupBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成备份…";
  try {
    const { blob, name } = await fetchArchive("/api/kb/export", "workbench-kb.json");
    saveArchive(blob, name);
    $("kbBackupHint").textContent = `已下载 ${name} · ${sizeText(blob.size)}。建议另存到网盘或 U 盘。`;
  } catch (e) {
    $("kbBackupHint").textContent = "备份失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function restoreKb() {
  const file = S.kbRestoreFile;
  if (!file) throw new Error("请先选择备份文件");
  if (file.size > 16 * 1024 * 1024) throw new Error("备份文件超过 16MB");
  const fd = new FormData();
  fd.append("file", file, file.name);
  const d = await api("/api/kb/restore", { method: "POST", body: fd });
  S.kbRestoreFile = null;
  $("kbRestoreFile").value = "";
  $("kbRestoreBtn").disabled = true;
  await loadKbPage();
  const extra = d.failed ? `，失败 ${d.failed} 篇` : "";
  $("kbRestoreHint").textContent = `恢复完成：新增 ${d.added} 篇，跳过同名 ${d.skipped} 篇${extra}。`;
}

function backupKindLabel(item) {
  if (item.kind === "migration") return "整机迁移";
  if (String(item.name).startsWith("pre-restore")) return "恢复前安全备份";
  return "数据备份";
}

function renderBackupRows() {
  const rows = S.backups || [];
  if (!rows.length) {
    $("backupRows").innerHTML = `<tr><td colspan="6"><span class="hint">还没有备份。点上面的按钮生成第一份。</span></td></tr>`;
    return;
  }
  $("backupRows").innerHTML = rows.map((b) => {
    const kind = backupKindLabel(b);
    const badge = b.kind === "migration" ? "warn" : (String(b.name).startsWith("pre-restore") ? "bad" : "good");
    return `<tr>
      <td>${esc(b.name)}</td>
      <td><span class="badge ${badge}">${kind}</span></td>
      <td>${fmtTime(b.created_at)}</td>
      <td>${sizeText(b.size)}</td>
      <td>${b.file_count ? b.file_count + " 个文件" : (b.app_schema ? "schema v" + b.app_schema : "—")}</td>
      <td><div class="ops">
        <button class="btn small" data-bbackup="${esc(b.name)}">下载</button>
        <button class="btn small" data-bdel="${esc(b.name)}">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

async function loadBackupPage() {
  resetPendingDelete();
  const [r, ret] = await Promise.all([
    api("/api/system/backups"),
    api("/api/system/file-retention").catch(() => null),
  ]);
  S.backups = r.items || [];
  if (r.migration_dir && $("migrationDirHint")) $("migrationDirHint").textContent = r.migration_dir;
  renderBackupRows();
  if (ret) renderFileRetention(ret);
  const last = S.backups[0];
  $("backupTitle").textContent = "建议每周备份一次";
  $("backupBadge").textContent = "就绪";
  $("backupBadge").className = "badge";
  $("backupDesc").textContent = "搬机器、换服务器或升级前，先生成备份。恢复后需要重启工作台，管理员可能需重新登录。";
  $("backupMeta").textContent = last
    ? `最近：${last.name} · ${sizeText(last.size)} · ${fmtTime(last.created_at)}`
    : "还没有备份。可以先点“生成并下载备份”。";
}

function renderFileRetention(d) {
  if (!d) return;
  const days = Number(d.days) || 30;
  if ($("retentionDays")) $("retentionDays").value = days;
  if ($("retentionFiles")) $("retentionFiles").textContent = String(d.retained_files || 0);
  if ($("retentionSize")) {
    $("retentionSize").textContent =
      `${sizeText(d.retained_bytes || 0)} · 共 ${d.total_files || 0} 条记录`;
  }
  if ($("retentionSoon")) $("retentionSoon").textContent = String(d.expiring_soon || 0);
  if ($("retentionPending")) $("retentionPending").textContent = String(d.pending_cleanup || 0);
  if ($("retentionCleaned")) $("retentionCleaned").textContent = String(d.cleaned_files || 0);
  if ($("retentionBadge")) {
    $("retentionBadge").textContent = `保留 ${days} 天`;
    $("retentionBadge").className = d.pending_cleanup ? "badge warn" : "badge good";
  }
  if ($("retentionHint")) {
    const last = d.last_cleanup_text
      ? `最近清理：${d.last_cleanup_text}，删除 ${Number((d.last_result || {}).removed) || 0} 个，释放 ${sizeText(Number((d.last_result || {}).freed_bytes) || 0)}。`
      : "自动清理已启动，服务启动后立即检查一次，之后每小时检查。";
    $("retentionHint").textContent =
      `${last} 当前保留 ${d.retained_files || 0} 个文件；` +
      `保存新周期会重算所有未清理文件的到期时间并立即清理。`;
  }
}

async function saveFileRetention() {
  const input = $("retentionDays");
  const days = Number(input && input.value);
  if (!Number.isInteger(days) || days < 1 || days > 365) {
    uiToast("保留天数需填 1–365 的整数", "bad");
    if (input) input.focus();
    return;
  }
  const btn = $("saveRetentionBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在保存…";
  try {
    const d = await api("/api/system/file-retention", {
      method: "PUT",
      body: JSON.stringify({ days }),
    });
    renderFileRetention(d);
    const result = d.result || {};
    uiToast(`已改为保留 ${days} 天，清理 ${result.removed || 0} 个文件`, "ok");
  } catch (e) {
    uiToast("保存失败：" + e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function runFileRetentionCleanup() {
  const btn = $("runRetentionBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在清理…";
  try {
    const d = await api("/api/system/file-retention/cleanup", { method: "POST" });
    renderFileRetention(d);
    const result = d.result || {};
    uiToast(`已检查 ${result.checked || 0} 个到期文件，删除 ${result.removed || 0} 个`, "ok");
  } catch (e) {
    uiToast("清理失败：" + e.message, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function downloadExistingBackup(name) {
  try {
    const { blob } = await fetchArchive("/api/system/backups/" + encodeURIComponent(name), name);
    saveArchive(blob, name);
    setBackupNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setBackupNotice(`下载失败：${e.message}`, "bad");
  }
}

function resetPendingDelete() {
  if (S.pendingDeleteBtn) S.pendingDeleteBtn.textContent = "删除";
  S.pendingDelete = null;
  S.pendingDeleteBtn = null;
}

async function deleteExistingBackup(name, btn) {
  if (S.pendingDelete !== name) {
    resetPendingDelete();
    S.pendingDelete = name;
    S.pendingDeleteBtn = btn;
    btn.textContent = "确认删除";
    setBackupNotice(`再次点击“确认删除”会删除 ${name}。删除后无法恢复，但不影响当前数据。`, "warn");
    setTimeout(() => { if (S.pendingDelete === name) resetPendingDelete(); }, 5000);
    return;
  }
  S.pendingDelete = null;
  S.pendingDeleteBtn = null;
  btn.disabled = true;
  btn.textContent = "删除中…";
  try {
    await api("/api/system/backups/" + encodeURIComponent(name), { method: "DELETE" });
    await loadBackupPage();
    setBackupNotice(`已删除：${name}`, "good");
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "删除";
    setBackupNotice(`删除失败：${e.message}`, "bad");
  }
}

function prepareRestoreBackup(ev) {
  const input = ev.target;
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  S.pendingRestore = file;
  $("confirmRestoreBtn").hidden = false;
  $("cancelRestoreBtn").hidden = false;
  setBackupNotice(
    `已选择：${file.name}。恢复会覆盖当前数据库、密钥和登录方式配置；系统会先自动备份当前数据。确认后才会开始。`,
    "warn"
  );
}

function cancelRestoreBackup() {
  S.pendingRestore = null;
  $("confirmRestoreBtn").hidden = true;
  $("cancelRestoreBtn").hidden = true;
  setBackupNotice("已取消恢复，当前数据没有变化。", "info");
}

async function confirmRestoreBackup() {
  const file = S.pendingRestore;
  if (!file) {
    setBackupNotice("请先选择要恢复的备份文件。", "warn");
    return;
  }
  const btn = $("confirmRestoreBtn");
  const cancel = $("cancelRestoreBtn");
  btn.disabled = true;
  cancel.disabled = true;
  btn.textContent = "正在恢复…";
  $("backupTitle").textContent = "正在恢复数据";
  $("backupBadge").textContent = "处理中";
  $("backupBadge").className = "badge warn";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/system/restore", {
      method: "POST",
      headers: token() ? { Authorization: "Bearer " + token() } : {},
      body: fd,
    });
    if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "恢复失败");
    S.pendingRestore = null;
    btn.hidden = true;
    cancel.hidden = true;
    $("backupTitle").textContent = "恢复完成，等待重启";
    $("backupBadge").textContent = "需重启";
    $("backupBadge").className = "badge warn";
    $("backupMeta").textContent = `恢复前安全备份：${d.safety_backup || "已生成"}`;
    setBackupNotice("恢复成功。请重启工作台后再登录；当前登录状态可能已失效。", "good");
    localStorage.removeItem(TOKEN_KEY);
    showLogin();
    $("alert").textContent = "恢复完成，请重启工作台后再登录。";
  } catch (e) {
    $("backupTitle").textContent = "恢复失败";
    $("backupBadge").textContent = "失败";
    $("backupBadge").className = "badge bad";
    setBackupNotice(`恢复失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    cancel.disabled = false;
    btn.textContent = "确认恢复";
  }
}

/* ---------------------------------------------------------------- 网站分享 */
function setShareNotice(text, kind = "info") {
  const box = $("shareNotice");
  const body = $("shareNoticeText");
  if (!box || !body) return;
  if (!text) {
    box.hidden = true;
    box.className = "backup-notice";
    body.textContent = "";
    return;
  }
  box.hidden = false;
  box.className = `backup-notice ${kind}`;
  body.textContent = text;
}

function setShareActions(show) {
  const local = S.localClient !== false;
  for (const id of ["openShareFolderBtn", "downloadShareFileBtn"]) {
    const el = $(id);
    if (el) el.hidden = !show || (id === "openShareFolderBtn" && !local);
    if (!show) el.textContent = id === "openShareFolderBtn" ? "打开文件夹" : "下载到浏览器";
  }
}

async function downloadShare() {
  const btn = $("shareBtn");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "正在生成分享包…";
  setShareNotice("正在打包程序和启动脚本；不会包含数据库、账号、密钥或模型。", "info");
  setShareActions(false);
  $("shareTitle").textContent = "正在生成干净程序包";
  $("shareBadge").textContent = "处理中";
  $("shareBadge").className = "badge warn";
  $("shareDesc").textContent = "分享包会保存到下面的默认目录，不经过浏览器弹窗。";
  try {
    const d = await api("/api/system/share?save=1", { method: "POST" });
    S.lastShare = d;
    await loadSharePage();
    $("shareTitle").textContent = "分享包已生成";
    $("shareBadge").textContent = "可分发";
    $("shareBadge").className = "badge good";
    $("shareMeta").textContent = `${d.name} · ${sizeText(d.size)} · ${d.path}`;
    setShareNotice(`分享包已保存到：${d.path}\n对方解压后双击“一键开始-双击我.bat”，首次启动会重新初始化数据。`, "good");
    setShareActions(true);
  } catch (e) {
    $("shareTitle").textContent = "分享包生成失败";
    $("shareBadge").textContent = "失败";
    $("shareBadge").className = "badge bad";
    setShareNotice(`分享包生成失败：${e.message}`, "bad");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function openShareFolder() {
  try {
    const d = await api("/api/system/open-share-folder", { method: "POST" });
    setShareNotice(`已打开文件夹：${d.path}`, "good");
  } catch (e) {
    setShareNotice(`打开文件夹失败：${e.message}`, "bad");
  }
}

async function downloadShareFile() {
  const d = S.lastShare;
  if (!d || !d.download_url) {
    setShareNotice("请先生成分享包。", "warn");
    return;
  }
  try {
    const { blob, name } = await fetchArchive(d.download_url, d.name);
    saveArchive(blob, name);
    setShareNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setShareNotice(`下载失败：${e.message}`, "bad");
  }
}

function renderShareRows() {
  const rows = S.shares || [];
  if (!rows.length) {
    $("shareRows").innerHTML = `<tr><td colspan="6"><span class="hint">还没有分享包。点上面的按钮生成第一份。</span></td></tr>`;
    return;
  }
  $("shareRows").innerHTML = rows.map((b) => `<tr>
      <td>${esc(b.name)}</td>
      <td><span class="badge good">干净程序包</span></td>
      <td>${fmtTime(b.created_at)}</td>
      <td>${sizeText(b.size)}</td>
      <td>${b.file_count ? b.file_count + " 个文件" : "不含数据"}</td>
      <td><div class="ops">
        <button class="btn small" data-share-download="${esc(b.name)}">下载</button>
        <button class="btn small" data-share-delete="${esc(b.name)}">删除</button>
      </div></td>
    </tr>`).join("");
}

function resetPendingShareDelete() {
  if (S.pendingShareDeleteBtn) S.pendingShareDeleteBtn.textContent = "删除";
  S.pendingShareDelete = null;
  S.pendingShareDeleteBtn = null;
}

async function loadSharePage() {
  resetPendingDelete();
  resetPendingShareDelete();
  const r = await api("/api/system/shares");
  S.shares = r.items || [];
  if (r.share_dir && $("shareDirHint")) $("shareDirHint").textContent = r.share_dir;
  renderShareRows();
  const last = S.shares[0];
  $("shareTitle").textContent = "生成分享包，发给需要的人";
  $("shareBadge").textContent = "就绪";
  $("shareBadge").className = "badge";
  $("shareDesc").textContent = "分享包不包含你的任何数据，对方安装后是一台全新的工作台。";
  $("shareMeta").textContent = last
    ? `最近：${last.name} · ${sizeText(last.size)} · ${fmtTime(last.created_at)}`
    : "还没有分享包。可以先点“生成到默认文件夹”。";
}

async function downloadExistingShare(name) {
  try {
    const { blob } = await fetchArchive("/api/system/shares/" + encodeURIComponent(name), name);
    saveArchive(blob, name);
    setShareNotice(`已开始下载：${name}。可在浏览器下载目录中找到它。`, "good");
  } catch (e) {
    setShareNotice(`下载失败：${e.message}`, "bad");
  }
}

async function deleteExistingShare(name, btn) {
  if (S.pendingShareDelete !== name) {
    resetPendingShareDelete();
    S.pendingShareDelete = name;
    S.pendingShareDeleteBtn = btn;
    btn.textContent = "确认删除";
    setShareNotice(`再次点击“确认删除”会删除 ${name}。删除后无法恢复。`, "warn");
    setTimeout(() => { if (S.pendingShareDelete === name) resetPendingShareDelete(); }, 5000);
    return;
  }
  S.pendingShareDelete = null;
  S.pendingShareDeleteBtn = null;
  btn.disabled = true;
  btn.textContent = "删除中…";
  try {
    await api("/api/system/shares/" + encodeURIComponent(name), { method: "DELETE" });
    await loadSharePage();
    setShareNotice(`已删除：${name}`, "good");
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "删除";
    setShareNotice(`删除失败：${e.message}`, "bad");
  }
}

