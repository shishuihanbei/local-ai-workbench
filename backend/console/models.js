/* 控制台 · 硬件、平台安装、模型清单与引擎、开机自启、桌面快捷方式 | 原 console.js 第 266–1033 行 */
/* ---------------------------------------------------------------- 硬件 */
function renderHardware(hw) {
  const gpuText = hw.gpus && hw.gpus.length
    ? hw.gpus.map((g) => `${g.name} · ${(g.vram_mb / 1024).toFixed(0)}GB`).join("；")
    : "未检测到 NVIDIA 显卡（CPU 推理）";
  const disk = (hw.disks || []).map((d) => `${d.path} 剩 ${gb(d.free_gb)}`).join("；");
  const cards = [
    ["CPU", hw.cpu, `${hw.cores} 线程 · 当前占用 ${hw.cpu_percent}%`],
    ["内存", `${gb(hw.ram_total_gb)}`, `可用 ${gb(hw.ram_free_gb)}`],
    ["显卡", gpuText, hw.gpus && hw.gpus.length ? (Math.max(...hw.gpus.map(g=>g.vram_mb))/1024 < 4 ? "显存较小，建议 CPU 推理" : "可开启 GPU 加速") : "无独显，使用 CPU 推理"],
    ["磁盘", disk || "—", `模型目录 ${hw.models_dir}`],
    ["系统", hw.os, `Python ${hw.python}`],
    ["llama.cpp", hw.llama.installed ? "已安装" : "未安装",
      hw.llama.installed ? (hw.llama.version || hw.llama.path) : "请在平台卡点“一键部署”"],
  ];
  $("hwCards").innerHTML = cards.map(([k, v, s]) => `
    <div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>
  `).join("");
}

/* ---------------------------------------------------------------- 安装 */
function renderInstall(st) {
  S.install = st;
  const llama = st.llama;
  // 这块现在叫“本地部署状态”：装了 Ollama / LM Studio 的用户也能看到自己的引擎
  const panel = $("installPanel");
  if (panel) panel.hidden = false;
  const showLlama = !!llama.installed || !!st.install.running;
  if ($("installRow")) $("installRow").hidden = !showLlama;
  if ($("depsRow")) $("depsRow").hidden = !showLlama;
  $("installInfo").innerHTML = `
    <div class="status-line"><span class="dot ${llama.installed ? "on" : ""}"></span>
      <b>${llama.installed ? "llama.cpp 已就绪" : "llama.cpp 正在安装"}</b></div>
    <div class="mono">${esc(llama.installed ? (llama.path + (llama.version ? " · " + llama.version : "")) : "安装后会写入 " + llama.llama_dir)}</div>
    <div class="mono">模型目录：${esc(st.models_dir)} ${st.models_dir_exists ? "（存在）" : "（不存在，会自动创建）"}</div>`;

  $("installBtn").hidden = !!llama.installed || !st.supported;
  $("installBtn").textContent = "备用安装 llama.cpp";
  $("installBtn").disabled = !!st.install.running;
  $("installHint").textContent = st.install.running ? "llama.cpp 安装进行中…"
    : "已装的引擎逐个列在这里，未安装的去上方平台卡部署";

  $("depsRow").innerHTML = Object.entries(st.python_packages || {}).map(([k, ok]) =>
    `<span class="chip ${ok ? "ok" : "miss"}">${esc(k)} ${ok ? "已安装" : "缺失"}</span>`).join("")
    + `<span class="chip ${st.supported ? "ok" : "miss"}">${esc(st.platform)} ${st.supported ? "支持一键部署" : "仅手动"}</span>`;

  const pr = st.install;
  const showBar = pr.running || (pr.ok === false && pr.error) || pr.ok === true;
  $("installProgress").hidden = !showBar;
  $("installBar").style.width = (pr.pct || 0) + "%";
  $("installText").textContent = `${pr.step || ""} ${pr.msg || ""}`.trim();
}

let installPolling = false;

function renderLocalStatus(platforms) {
  const box = $("localStatusRows");
  if (!box) return;
  const list = (platforms || []).filter((p) => p && p.key !== "custom");
  const rows = list.filter((p) => p.installed || p.healthy);
  const idle = list.filter((p) => !p.installed && !p.healthy).map((p) => p.name || p.key);
  if (!rows.length) {
    box.innerHTML = `<div class="hint">本机还没有装任何本地引擎：在平台卡点“一键部署”，装好后这里会逐个列出状态。</div>`;
    return;
  }
  box.innerHTML = rows.map((p) => {
    const live = !!p.healthy;
    const state = live ? "运行中" : "已装未跑";
    const n = (p.models || []).length;
    const detail = (live ? [p.detail || "", n ? n + " 个模型" : ""] : ["已安装，未启动", n ? n + " 个模型" : ""])
      .filter(Boolean).join(" · ");
    return `<div class="local-status-row">
      <span class="dot ${live ? "on" : "warn"}"></span>
      <b>${esc(p.name || p.key)}</b>
      <span class="badge ${live ? "good" : "warn"}">${state}</span>
      <span class="mono">${esc(detail)}</span>
    </div>`;
  }).join("");
  if (idle.length) box.innerHTML += `<p class="hint">未安装：${esc(idle.join("、"))}（在平台卡点“一键部署”）</p>`;
}

async function pollInstall() {
  if (installPolling) return;
  installPolling = true;
  try {
    const pr = await api("/api/system/install-progress");
    renderInstall({ ...S.install, install: pr });
    if (pr.running) { setTimeout(pollInstall, 1500); }
    else if (pr.ok) { await loadAll(); }
  } finally {
    installPolling = false;
  }
}

async function pollModelDownload(key) {
  for (let i = 0; i < 720; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    let p;
    try { p = await api(`/api/models/${encodeURIComponent(key)}/progress`); }
    catch (e) { continue; }
    await loadAll();
    if (!p || p.status === "running") continue;
    if (p.status === "interrupted") { uiToast("下载已中断，可点「继续下载」续传"); return; }
    if (p.status === "error" || p.error) { uiToast(`下载失败：${p.error || "网络中断"}`); return; }
    if (p.exists) { uiToast("下载完成，可以加载了"); return; }
    return;
  }
}

async function pollEngineInstall(key) {
  for (let i = 0; i < 900; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    let p;
    try { p = await api(`/api/engines/${encodeURIComponent(key)}/install-progress`); }
    catch (e) { continue; }
    const box = document.querySelector(`[data-engine-progress="${key}"]`);
    if (box) {
      box.hidden = false;
      const head = box.querySelector("span");
      const bar = box.querySelector(".engine-bar i");
      const log = box.querySelector(".engine-log");
      if (head) head.textContent = `${p.step || "安装中"} ${p.pct || 0}%`;
      if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(p.pct || 0)))}%`;
      if (log) log.textContent = p.msg || "";
    }
    if (!p || p.running) continue;
    await loadAll();
    if (p.error) uiToast(`安装失败：${p.error}`);
    else if (p.ok) uiToast(p.msg || "安装完成");
    return;
  }
}

/* ---------------------------------------------------------------- 模型 */
function statusBadge(m) {
  const d = m.download || {};
  if (d.state === "running") return `<span class="badge warn">下载中 ${m.pct || d.pct || 0}%</span>`;
  if (d.state === "error" && !m.downloaded) return `<span class="badge bad">下载失败</span>`;
  if (m.installable === false) {
    if (m.downloaded) return `<span class="badge good">已下载</span>`;
    if (d.state === "interrupted" || m.partial) return `<span class="badge warn">已中断${m.pct ? " " + m.pct + "%" : ""}</span>`;
    return m.engine_ready
      ? `<span class="badge ok">引擎就绪</span>`
      : `<span class="badge warn">需独立引擎</span>`;
  }
  if (m.available === false) return `<span class="badge off">本地已关闭</span>`;
  if (m.downloaded) return `<span class="badge good">已下载</span>`;
  if (d.state === "interrupted" || m.partial) return `<span class="badge warn">已中断 ${m.pct || 0}%</span>`;
  return `<span class="badge off">未下载</span>`;
}

function adviceBadge(a) {
  const lvl = a && a.level ? a.level : "unknown";
  const label = a ? a.label : "未知";
  return `<span class="badge ${esc(lvl)}">${esc(label)}</span>
          <div class="advice-text">${esc(a ? a.text : "下载后可评估")}</div>`;
}

function modelCategoryLabel(key) {
  const found = MODEL_CATEGORY_ORDER.find((x) => x[0] === key);
  return found ? found[1] : (key || "其他");
}

function renderModelFilters(items) {
  const box = $("modelFilters");
  if (!box) return;
  const counts = {};
  for (const m of items) counts[m.category || "text"] = (counts[m.category || "text"] || 0) + 1;
  const chips = [["all", "全部", items.length]].concat(
    MODEL_CATEGORY_ORDER.filter(([k]) => counts[k]).map(([k, label]) => [k, label, counts[k]]));
  box.innerHTML = chips.map(([key, label, n]) =>
    `<button class="model-filter ${S.modelCategory === key ? "active" : ""}" data-mcat="${esc(key)}">${esc(label)} <b>${n}</b></button>`).join("");
}

function renderModelRows() {
  const data = S.models || { items: [] };
  const items = data.items || [];
  if (!items.length) {
    $("modelRows").innerHTML = `<tr><td colspan="7" style="color:#6b7280">还没有模型清单</td></tr>`;
    return;
  }
  const filtered = S.modelCategory === "all"
    ? items
    : items.filter((m) => (m.category || "text") === S.modelCategory);
  if (!filtered.length) {
    $("modelRows").innerHTML = `<tr><td colspan="7" style="color:#6b7280">这个分类下还没有模型</td></tr>`;
    return;
  }
  const groups = S.modelCategory === "all"
    ? MODEL_CATEGORY_ORDER.map(([k, label]) => [k, label])
    : [[S.modelCategory, modelCategoryLabel(S.modelCategory)]];
  const html = [];
  for (const [cat, label] of groups) {
    const list = filtered.filter((m) => (m.category || "text") === cat);
    if (!list.length) continue;
    if (S.modelCategory === "all") {
      html.push(`<tr class="model-group"><td colspan="7"><span>${esc(label)}</span><em>${list.length} 个</em></td></tr>`);
    }
    for (const m of list) {
      const act = [];
      const dl = m.download || {};
      const running = dl.state === "running";
      const failed = dl.state === "error";
      if (m.installable === false) {
        if (m.engine_repo) {
          const tip = m.engine_ready
            ? `用 ${m.engine_recommend || "独立引擎"} 下载整仓库到模型目录`
            : `先在「部署」页安装 ${m.engine_recommend || "独立引擎"}，装好后才能下载`;
          const label = running
            ? `下载中…`
            : (m.downloaded ? "重新下载" : (failed ? "重试下载" : (m.partial ? "继续下载" : "下载")));
          act.push(`<button class="btn small" data-dl="${esc(m.key)}" ${(m.engine_ready && !running) ? "" : "disabled"} title="${esc(tip)}">${label}</button>`);
        }
        if (m.homepage) act.push(`<a class="btn small" href="${esc(m.homepage)}" target="_blank" rel="noreferrer">查看项目</a>`);
        else if (!m.engine_repo) act.push(`<span class="badge off">未接入</span>`);
      } else {
        if (running) act.push(`<button class="btn small" disabled>下载中…</button>`);
        else if (!m.downloaded) act.push(`<button class="btn small" data-dl="${esc(m.key)}">${failed ? "重试下载" : (m.partial ? "继续下载" : "下载")}</button>`);
        if (m.downloaded && !m.loaded) act.push(`<button class="btn small" data-load="${esc(m.key)}" title="${m.available === false ? "加载模型会重新开启本地部署" : ""}">${m.available === false ? "加载并开启" : "加载"}</button>`);
        if (m.loaded) act.push(`<span class="badge ok">使用中</span>`);
      }
      // 同一个模型在 Ollama 里还有一套“tag + blobs”的取法，装了 Ollama 就多给一个入口
      if (m.ollama_tag && m.ollama_ready) {
        act.push(m.ollama_pulled
          ? `<span class="badge ok" title="Ollama 里已经有这个模型">Ollama 已拉取</span>`
          : `<button class="btn small ghost" data-opull="${esc(m.ollama_tag)}" title="执行 ollama pull ${esc(m.ollama_tag)}，落到 Ollama 的模型目录">用 Ollama 拉取</button>`);
      }
      const oTag = m.ollama_tag
        ? `<div class="sub">Ollama：${esc(m.ollama_tag)}${m.ollama_pulled ? " · 已拉取" : (m.ollama_ready ? "" : " · 服务未启动")}</div>`
        : "";
      html.push(`<tr>
        <td><div class="name">${esc(m.label || m.key)}</div><div class="sub">${esc(m.key)}${m.filename ? " · " + esc(m.filename) : ""}</div></td>
        <td><span class="badge cat">${esc(m.category_label || modelCategoryLabel(m.category))}</span></td>
        <td><div>${esc(m.engine || "—")}</div>${m.installable === false ? `<div class="sub">推荐 ${esc(m.engine_recommend || "独立引擎")} · ${m.engine_ready ? "已安装" : "未安装"}</div>` : ""}${oTag}</td>
        <td>${m.bytes ? mb(m.bytes) : (m.total_bytes ? "约 " + mb(m.total_bytes) : "—")}</td>
        <td>${statusBadge(m)}</td>
        <td>${adviceBadge(m.advice)}</td>
        <td class="right"><div class="row-actions">${act.join("")}</div></td>
      </tr>`);
    }
  }
  $("modelRows").innerHTML = html.join("");
}

function renderPlatforms(data) {
  const box = $("platformCards");
  if (!box) return;
  if (data) S.deployData = data;
  const d = S.deployData || {};
  if (!S.platformDirty) {
    S.platformSelected = (d.selected || []).slice();
    S.platformEndpoints = { ...(d.endpoints || {}) };
  }
  if (d.github_proxy && !S.platformDirty) S.platformProxy = d.github_proxy;
  const proxyEl = $("githubProxy");
  if (proxyEl && document.activeElement !== proxyEl) proxyEl.value = S.platformProxy || "auto";
  const items = d.platforms || S.platforms || [];
  S.platforms = items;
  const selected = new Set(S.platformSelected);
  box.innerHTML = items.map((p) => {
    const on = selected.has(p.key);
    const state = p.healthy
      ? `<span class="badge good">已连接</span>`
      : p.installed
        ? `<span class="badge warn">已安装</span>`
        : p.installable
          ? `<span class="badge off">可部署</span>`
          : `<span class="badge off">未安装</span>`;
    const urlValue = S.platformDirty
      ? (S.platformEndpoints[p.key] || p.base_url || "")
      : (p.base_url || "");
    const url = p.editable
      ? `<input class="platform-url" data-platform-url="${esc(p.key)}" value="${esc(urlValue)}" placeholder="http://127.0.0.1:端口">`
      : `<input class="platform-url" value="工作台管理（由本机启动）" disabled>`;
    const link = p.homepage
      ? `<a class="sub" href="${esc(p.homepage)}" target="_blank" rel="noreferrer">打开官网</a>`
      : "";
    const fit = p.suitability || { level: "unknown", label: "需确认", text: "" };
    const mm = p.multimodal ? `<span class="badge mm">${esc(p.multimodal)}</span>` : "";
    const types = (p.model_types || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("");
    const installedText = p.installed
      ? `已安装${p.version ? " · " + p.version : ""}`
      : (p.installable ? "尚未安装，可一键部署" : "需要手动安装");
    const paths = [];
    if (p.installed && p.install_path) paths.push(["程序", p.install_path]);
    if (p.installed && p.models_path) paths.push(["模型", p.models_path]);
    if (!p.installed && p.target_path) paths.push(["将装到", p.target_path]);
    if (p.legacy_models_path) paths.push(["旧模型", p.legacy_models_path]);
    const pathRows = paths.map(([k, v]) => `<div class="platform-path"><span>${esc(k)}</span><code title="${esc(v)}">${esc(v)}</code><button class="link" data-copy-path="${esc(v)}">复制</button></div>`).join("");
    const label = p.action_label || "一键部署";
    const disabled = p.deployable === false || (p.install && p.install.running);
    const manage = p.can_manage && !(p.install && p.install.running)
      ? `<button class="btn small ghost" data-pdeploy-manage="${esc(p.key)}">装到工作台目录</button>`
      : "";
    const adopt = (p.managed && p.legacy_models_path) && !(p.install && p.install.running)
      ? `<button class="btn small ghost" data-adopt-models="${esc(p.key)}">迁移旧模型</button>`
      : "";
    // 只有工作台自己装进 platforms/ 的平台才给“卸载”；系统安装的会由后端拒绝并说明
    const removable = p.installed && (p.managed || p.key === "llama.cpp");
    const uninstall = removable && !(p.install && p.install.running)
      ? `<button class="btn small danger" data-puninstall="${esc(p.key)}" title="停掉进程与端口，删掉工作台装的程序和下载缓存；保留你下载的模型和 data\\installers 里的安装包">卸载</button>`
      : "";
    const action = p.key === "custom"
      ? `<button class="btn small" data-pdeploy="${esc(p.key)}">${esc(label)}</button>
         <button class="btn small ghost" data-custom-guide>接入说明</button>`
      : `<button class="btn small ${p.action === "install" ? "primary" : ""}" data-pdeploy="${esc(p.key)}" ${disabled ? "disabled" : ""}>${esc(label)}</button>${manage}${adopt}${uninstall}`;
    const u = p.usage || {};
    const frontBadge = u.frontend_ready
      ? `<span class="badge good" title="服务健康时，这些模型会自动出现在用户端模型下拉">已接入用户端 · ${u.frontend_count} 个模型</span>`
      : (p.healthy ? `<span class="badge warn">服务在跑，还没加载模型</span>` : "");
    // 装了/在跑之后，卡片里直接给“怎么用”：接口地址、模型名、curl、步骤
    const usage = (p.installed || p.healthy) ? `
      <details class="platform-usage" ${p.healthy ? "open" : ""}>
        <summary>接入与使用<span>${esc(u.api_base || "服务健康后自动接入用户端")}</span></summary>
        <div class="platform-usage-body">
          ${u.api_base ? `<div class="platform-path"><span>API</span><code title="${esc(u.api_base)}">${esc(u.api_base)}</code><button class="link" data-copy-path="${esc(u.api_base)}">复制</button></div>` : ""}
          ${u.sample_model ? `<div class="platform-path"><span>模型</span><code>${esc(u.sample_model)}</code><button class="link" data-copy-path="${esc(u.sample_model)}">复制</button></div>` : ""}
          <ol class="usage-steps">${(u.steps || []).map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
          ${u.curl ? `<pre class="usage-code">${esc(u.curl)}</pre>` : ""}
          <div class="usage-actions">
            <a class="btn small" href="/" target="_blank" rel="noreferrer">打开用户端试用</a>
            ${u.chat_url ? `<button class="link" data-copy-path="${esc(u.chat_url)}">复制接口地址</button>` : ""}
            ${u.curl ? `<button class="link" data-copy-path="${esc(u.curl)}">复制 curl</button>` : ""}
          </div>
        </div>
      </details>` : "";
    return `<div class="platform-card ${on ? "on" : ""}">
      <div class="platform-head">
        <label><input type="checkbox" data-platform="${esc(p.key)}" ${on ? "checked" : ""}><b>${esc(p.name)}</b>${mm}</label>
        ${state}${frontBadge}
      </div>
      <div class="platform-note">${esc(p.note || "")}</div>
      <div class="platform-detail">${esc(p.detail || "")} ${link}</div>
      <div class="platform-installed">${esc(installedText)}</div>
      ${pathRows ? `<div class="platform-paths">${pathRows}</div>` : ""}
      <div class="platform-suit"><span class="badge ${esc(fit.level || "unknown")}">${esc(fit.label || "需确认")}</span><span>${esc(fit.text || "")}</span></div>
      <div class="platform-types">${types || `<span class="chip">未标注</span>`}</div>
      ${url}
      ${usage}
      <div class="platform-actions">${action}</div>
      <div class="platform-progress" data-platform-progress="${esc(p.key)}" hidden>
        <div class="bar"><i data-platform-bar="${esc(p.key)}"></i></div>
        <div class="progress-text" data-platform-text="${esc(p.key)}"></div>
        <button class="btn small ghost" data-pcancel="${esc(p.key)}" hidden>取消部署</button>
      </div>
    </div>`;
  }).join("");

  items.forEach((p) => {
    if (p.install && (p.install.finished_at || p.install.running)) renderPlatformProgress(p.key, p.install);
  });

  if (!S.platformSelected.length) {
    $("platformNote").textContent = "没有勾选平台；保存或开启时会自动使用默认 llama.cpp。";
  } else {
    const names = items.filter((p) => selected.has(p.key)).map((p) => p.name);
    $("platformNote").textContent = `已选择：${names.join("、")}。“保存选择”只保存勾选和地址；每张卡里的“一键部署”才会安装并启动。`;
  }
  renderLocalStatus(items);
}

function platformSelection() {
  const checked = [...document.querySelectorAll("#platformCards [data-platform]:checked")].map((x) => x.dataset.platform);
  return checked.length ? checked : ["llama.cpp"];
}

function platformEndpointValues() {
  const out = { ...S.platformEndpoints };
  document.querySelectorAll("#platformCards [data-platform-url]").forEach((el) => {
    out[el.dataset.platformUrl] = el.value.trim();
  });
  return out;
}

function renderPlatformProgress(key, st) {
  const box = document.querySelector(`[data-platform-progress="${key}"]`);
  const bar = document.querySelector(`[data-platform-bar="${key}"]`);
  const text = document.querySelector(`[data-platform-text="${key}"]`);
  if (!box || !st) return;
  const hasState = st.running || st.finished_at || st.ok !== null;
  box.hidden = !hasState;
  if (!hasState) return;
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, st.pct || 0))}%`;
  if (text) {
    const skipped = st.skipped ? " · 已安装，跳过下载" : "";
    text.textContent = `${st.step || ""} ${st.msg || ""}${skipped}`.trim();
    text.className = "progress-text " + (st.ok === false ? "bad" : st.ok === true ? "good" : "");
  }
  const cancel = document.querySelector(`[data-pcancel="${key}"]`);
  if (cancel) {
    cancel.hidden = !st.running;
    if (st.running) {
      cancel.disabled = !!st.cancel;
      cancel.textContent = st.cancel ? "取消中…" : "取消部署";
    }
  }
}

async function pollPlatform(key) {
  if (S.platformPolling[key]) return;
  S.platformPolling[key] = true;
  let last = null;
  try {
    for (;;) {
      const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/progress`);
      last = r.state || {};
      renderPlatformProgress(key, last);
      if (!last.running) break;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  } catch (e) {
    uiToast(e.message);
  } finally {
    S.platformPolling[key] = false;
  }
  if (last) {
    if (last.cancelled) uiToast(`已取消部署：${last.msg || ""}`);
    else uiToast(`${last.ok ? "部署完成" : "部署失败"}：${last.msg || ""}`);
    if ((last.ok || last.cancelled) && !S.platformDirty) {
      try {
        const d = await api("/api/system/local-deploy?scan=1");
        S.deployData = { ...(S.deployData || {}), ...d };
        renderPlatforms(S.deployData);
      } catch (_) {}
    }
    return last;
  }
  return null;
}

/* 本机实际部署了哪些引擎：只列已安装/已连通的，没装的不占位。 */
function engineLines(platforms, onlyRunning) {
  return (platforms || [])
    .filter((p) => p && p.key !== "custom" && (onlyRunning ? p.healthy : (p.installed || p.healthy)))
    .map((p) => {
      const addr = String(p.base_url || "").replace(/^https?:\/\//, "").replace(/\/v1$/, "");
      const n = (p.models || []).length;
      const state = onlyRunning ? "" : (p.healthy ? " · 运行中" : " · 未启动");
      return `${p.name || p.key}${addr ? " · " + addr : ""}${n ? " · " + n + " 个模型" : ""}${state}`;
    });
}

function renderLocalDeploy(data) {
  const on = data.local_enabled !== false;
  const srv = data.server || {};
  const platforms = data.platforms || [];
  const installed = !!(data.hardware && data.hardware.llama_installed);
  S.localEnabled = on;
  const btn = $("localDeployBtn");
  if (!btn) return;
  btn.dataset.next = on ? "off" : "on";
  btn.textContent = on ? "关闭本地部署" : "开启本地部署";
  btn.className = on ? "btn danger" : "btn primary";
  btn.disabled = !!S.localBusy;

  const dot = $("localDeployDot");
  const badge = $("localDeployBadge");
  const running = engineLines(platforms, true);
  const deployed = engineLines(platforms, false);
  const deployedNames = (platforms || [])
    .filter((p) => p && p.key !== "custom" && (p.installed || p.healthy))
    .map((p) => p.name || p.key);
  const installedIdle = (platforms || [])
    .filter((p) => p && p.key !== "custom" && p.installed && !p.healthy)
    .map((p) => p.name || p.key);
  let title, desc, meta;
  if (on && running.length) {
    dot.className = "dot on"; badge.className = "badge good"; badge.textContent = "运行中";
    title = `本地部署已开启 · 引擎 ${running.length} 个`;
    desc = "用户端和 OpenAI 接口可以调用这些平台上的模型。关闭后本地模型会立即从可用列表移除，并拒绝本地模型请求。";
    meta = `引擎 ${running.join("；")}${installedIdle.length ? `；已装未跑：${installedIdle.join("、")}（开关会自动拉起）` : ""}`;
  } else if (on && srv.running) {
    dot.className = "dot warn"; badge.className = "badge warn"; badge.textContent = "启动中";
    title = "本地部署已开启，服务正在启动";
    desc = "llama-server 进程已创建，正在等待模型加载完成。";
    meta = `模型 ${srv.model || "—"} · 端口 ${srv.port || 8080}`;
  } else if (on) {
    dot.className = "dot warn"; badge.className = "badge warn"; badge.textContent = "待运行";
    title = "本地部署已开启，还没有引擎在跑";
    desc = deployed.length
      ? `开关会把已装的 ${deployedNames.join("、")} 一起拉起来；起不来时去对应平台卡看进度和报错。`
      : "本机还没有部署任何本地引擎：先在上方平台卡点一个“一键部署”（llama.cpp、Ollama、LM Studio 任选其一），装好的平台会自动加进开关。";
    meta = deployed.length ? `已装 ${deployed.join("；")}` : (installed ? `模型目录 ${data.models_dir || "—"}` : "未检测到已部署引擎");
  } else {
    dot.className = "dot"; badge.className = "badge off"; badge.textContent = "已关闭";
    title = "本地部署已关闭";
    desc = "用户端不会显示本地模型，OpenAI 接口也会拒绝本地模型请求；配置了第三方供应商时会自动改用云端。";
    if (srv.external || srv.healthy) {
      meta = "检测到 8080 端口仍有外部 llama-server 运行，工作台不会强制结束它。";
    } else {
      meta = deployed.length ? `已部署但已停用：${deployed.join("；")}` : "本机没有已部署的本地引擎。";
    }
  }
  $("localDeployTitle").textContent = title;
  $("localDeployDesc").textContent = desc;
  $("localDeployMeta").textContent = meta;
}

function renderModels(data) {
  S.models = data;
  const srv = data.server || {};
  const enabled = data.local_enabled !== false;
  const items = data.items || [];
  const ready = items.filter((m) => m.downloaded).length;
  const ollama = data.ollama || {};
  const engineText = srv.running
    ? `llama.cpp${srv.model ? " " + srv.model : ""} 运行中`
    : (ollama.running ? "Ollama 运行中" : "暂无运行中的引擎");
  $("modelHint").textContent = `本地${enabled ? "已开启" : "已关闭"} · ${engineText} · ${items.length} 个模型 · 已下载 ${ready} · 单模型运行，点“加载”会切换当前模型`;
  renderModelFilters(items);
  renderModelRows();
  renderEngineSummary(items);
  renderOllamaPull();
}

/* Ollama 的模型不在内置清单里，走它自己的 registry：给个输入框按 tag 拉，
   拉完自动进模型下拉；装了 Ollama 才会显示这块（状态跟着 /api/models 一起返回）。 */
function ollamaPlatform() {
  const info = (S.models && S.models.ollama) || null;
  if (info) return info;
  // 老接口没有这个字段时退回部署页数据
  const list = ((S.deployData && S.deployData.platforms) || S.platforms || []);
  return list.find((x) => x.key === "ollama") || null;
}

function renderOllamaPull() {
  const box = $("ollamaPullBox");
  if (!box) return;
  const p = ollamaPlatform();
  const have = !!(p && (p.managed || p.installed));
  box.hidden = !have;
  const note = $("ollamaPullNote");
  if (note && p) {
    note.textContent = p.running
      ? `Ollama 服务在跑，模型目录 ${p.models_path || ""}`
      : (p.installed ? "Ollama 已安装但服务没在跑：先在「部署」页点“启动”，再来拉模型" : "");
  }
  const st = (S.models && S.models.ollama && S.models.ollama.pull) || S.ollamaPull || {};
  renderOllamaPullState(st);
  if (!box.hidden && st.running) pollOllamaWatch();
}

/* 轻量轮询：只在拉取进行中才真的转起来，避免模型页每 3 秒都多打一个请求 */
async function pollOllamaWatch() {
  if (S.pullWatching) return;
  S.pullWatching = true;
  try {
    for (let i = 0; i < 40; i += 1) {
      await new Promise((r) => setTimeout(r, 3000));
      let st;
      try { st = await api("/api/system/local-platforms/ollama/pull"); }
      catch (e) { continue; }
      if (st && st.running) { S.ollamaPull = st; renderOllamaPullState(st); }
      else if (st && S.ollamaPull && S.ollamaPull.running) { S.ollamaPull = st; renderOllamaPullState(st); await loadAll(); return; }
    }
  } finally {
    S.pullWatching = false;
  }
}

function renderOllamaPullState(st) {
  const box = $("ollamaPullProgress");
  if (!box) return;
  const show = !!st && (st.running || st.finished_at || st.ok !== null);
  box.hidden = !show;
  if (!show) return;
  const bar = $("ollamaPullBar");
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(st.pct || 0)))}%`;
  const text = $("ollamaPullText");
  if (text) {
    const head = st.running ? `${st.step || "拉取中"} ${st.pct || 0}%` : (st.ok ? "拉取完成" : (st.step || "失败"));
    text.textContent = `${head} · ${st.msg || ""}`.replace(/\s+/g, " ").trim();
  }
}

async function pollOllamaPull() {
  if (S.pullPolling) return;
  S.pullPolling = true;
  try {
    for (let i = 0; i < 1800; i += 1) {
      let st;
      try { st = await api("/api/system/local-platforms/ollama/pull"); }
      catch (e) { await new Promise((r) => setTimeout(r, 2000)); continue; }
      S.ollamaPull = st;
      renderOllamaPullState(st);
      if (!st.running) {
        await loadAll();
        uiToast(st.ok ? (st.msg || "拉取完成") : (st.msg || "拉取失败"));
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  } finally {
    S.pullPolling = false;
  }
}

function renderEngineSummary(items) {
  const box = $("engineSummary");
  if (!box) return;
  const need = items.filter((m) => m.installable === false);
  if (!need.length) {
    box.innerHTML = `<div class="engine-empty">当前没有需要独立引擎的模型。</div>`;
    return;
  }
  const catalog = {};
  for (const e of ((S.models && S.models.engine_catalog) || [])) catalog[e.key] = e;
  const groups = new Map();
  for (const m of need) {
    const engine = m.engine || "未标注";
    if (!groups.has(engine)) groups.set(engine, []);
    groups.get(engine).push(m);
  }
  const rows = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-CN"));
  box.innerHTML = rows.map(([engine, list]) => {
    const rec = list.find((m) => m.engine_recommend) || {};
    const ready = list.some((m) => m.engine_ready);
    const info = catalog[rec.engine_recommend_key] || null;
    const hint = rec.engine_text || `需要 ${engine} 独立引擎`;
    let guide = "";
    if (info) {
      const p = info.progress || {};
      const running = !!p.running;
      let action = `<span class="badge ok">已安装</span>`;
      if (!info.installed && info.one_click) {
        action = `<button class="btn small" data-engine-install="${esc(info.key)}" ${running ? "disabled" : ""}>${running ? "安装中…" : "一键安装"}</button>`;
      }
      else if (!info.installed) {
        action = `<button class="btn small" disabled title="${esc(info.blocked || info.install)}">一键安装</button>`;
      }
      guide = `
        <div class="engine-links"><a href="${esc(info.site)}" target="_blank" rel="noreferrer">官网</a><a href="${esc(info.download)}" target="_blank" rel="noreferrer">下载地址</a></div>
        <div class="engine-cmd"><code>${esc(info.install)}</code><button class="btn tiny" data-copy-engine="${esc(info.key)}">复制</button></div>
        <div class="engine-note">${esc(info.note)}</div>
        ${info.blocked ? `<div class="engine-note warn">${esc(info.blocked)}</div>` : ""}
        <div class="engine-actions">${action}</div>
        <div class="engine-progress" data-engine-progress="${esc(info.key)}" ${running ? "" : "hidden"}>
          <span>${esc(p.step || "安装中")} ${p.pct || 0}%</span>
          <div class="engine-bar"><i style="width:${Math.max(0, Math.min(100, Number(p.pct || 0)))}%"></i></div>
          <div class="engine-log">${esc(p.msg || "")}</div>
        </div>`;
    }
    return `
    <div class="engine-item">
      <div class="engine-head"><b>${esc(engine)}</b><span>${list.length} 个模型</span></div>
      <div class="engine-rec ${ready ? "ok" : "warn"}">推荐：${esc(rec.engine_recommend || engine)} · ${ready ? "已安装" : "未安装，下载按钮不可用"}</div>
      <div class="engine-models">${list.map((m) => esc(m.label || m.key)).join(" · ")}</div>
      <div class="advice-text">${esc(hint)}</div>
      ${guide}
    </div>`;
  }).join("");
}

function renderService(hw, data, platforms) {
  const srv = data.server || {};
  const hardware = hw || {};
  const list = platforms || ((S.deployData && S.deployData.platforms) || []);
  const lines = [];
  if (srv.running || (hw && hw.llama && hw.llama.installed) || (S.install && S.install.llama && S.install.llama.installed)) {
    lines.push(`llama.cpp · 端口 ${esc(srv.port || 8080)} · ${srv.running ? "运行中" : "未启动"}${srv.external ? "（外部进程）" : ""}`);
  }
  for (const p of list) {
    if (!p || p.key === "custom" || p.key === "llama.cpp") continue;
    if (!p.installed && !p.healthy) continue;
    const addr = String(p.base_url || "").replace(/^https?:\/\//, "").replace(/\/v1$/, "");
    lines.push(`${esc(p.name || p.key)} · ${esc(addr || "—")} · ${p.healthy ? "运行中" : "未启动"}`);
  }
  $("svcRow").innerHTML = `
    <div class="svc"><h3>模型服务</h3>${lines.length ? lines.map((x) => `<p>${x}</p>`).join("") : "<p>本机还没有部署任何本地引擎</p>"}</div>
    <div class="svc"><h3>接口</h3><p><a href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a> · 健康检查 /api/health</p></div>
    <div class="svc"><h3>本机配置</h3><p>${esc(hardware.cpu || "")} · ${gb(hardware.ram_total_gb || 0)} 内存</p></div>
    <div class="svc"><h3>模型目录</h3><p class="mono">${esc(data.models_dir || (hw && hw.models_dir) || "")}</p></div>`;
}

/* ---------------------------------------------------------------- 加载 */
function renderDeployment(hw, models, deploy) {
  S.hw = hw;
  S.deployModels = models;
  S.lastDeployAt = Date.now();
  renderHardware(hw);
  renderInstall(hw.install);
  const localData = { ...hw, ...models, ...(deploy || {}),
    local_enabled: deploy ? deploy.enabled : models.local_enabled,
    hardware: models.hardware || hw,
    models_dir: models.models_dir || hw.models_dir };
  renderLocalDeploy(localData);
  renderService(hw, models, (deploy || {}).platforms);
  renderPlatforms(deploy || { platforms: [], selected: ["llama.cpp"], endpoints: {} });
  if (hw.install.install && hw.install.install.running) pollInstall();
}

function renderStorage(st) {
  if (!st) return;
  S.storage = st;
  if ($("storageModels")) $("storageModels").value = st.models_dir || "";
  if ($("storagePlatforms")) $("storagePlatforms").value = st.platforms_dir || "";
  const badge = $("storageBadge");
  if (badge) {
    badge.className = "badge good";
    badge.textContent = "已就绪";
  }
  if ($("storageHint")) {
    $("storageHint").textContent = `llama.cpp 安装位置：${st.llama_dir}${st.llama_dir_exists ? "（已存在）" : "（安装时自动创建）"}`;
  }
  if ($("storagePanel")) {
    $("storagePanel").dataset.defaults = JSON.stringify(st.defaults || {});
  }
}

async function loadStorage() {
  const st = await api("/api/system/storage");
  renderStorage(st);
}

async function saveStorage() {
  const models = ($("storageModels") && $("storageModels").value.trim()) || "";
  const platforms = ($("storagePlatforms") && $("storagePlatforms").value.trim()) || "";
  const btn = $("storageSave");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const st = await api("/api/system/storage", {
      method: "PUT",
      body: JSON.stringify({ models_dir: models, platforms_dir: platforms }),
    });
    renderStorage(st);
    if ($("storageMsg")) $("storageMsg").textContent = "已保存；正在运行的服务重启后会按新目录加载模型。";
    uiToast("存储位置已保存");
    btn.textContent = "已保存";
    setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
  } catch (e) {
    if ($("storageMsg")) $("storageMsg").textContent = e.message;
    uiToast(e.message);
    btn.textContent = "保存失败";
    setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
  }
}

async function loadDeployment() {
  const [hw, models, deploy, storage, home] = await Promise.all([
    api("/api/system/hardware"),
    api("/api/models"),
    api("/api/system/local-deploy"),
    api("/api/system/storage"),
    api("/api/system/engine-home").catch(() => null),
  ]);
  renderDeployment(hw, models, deploy);
  renderStorage(storage);
  if (home) renderEngineHome(home);
}

/* 所有下载与安装产物落在哪：和“整机卸载”配套，用户能自己核对目录 */
function renderEngineHome(data) {
  S.engineHome = data;
  const box = $("engineHomeRows");
  if (box) {
    box.innerHTML = (data.dirs || []).map((d) => `
      <div class="platform-path">
        <span>${esc(d.label)}</span>
        <code title="${esc(d.path)}">${esc(d.path)}</code>
        <em>${esc(d.human || "")}</em>
        <button class="link" data-copy-path="${esc(d.path)}">复制</button>
      </div>`).join("");
  }
  const hint = $("engineHomeHint");
  if (hint) {
    hint.textContent = `根目录 ${data.root}；安装包在 platforms\\.downloads，临时解压在 platforms\\.tmp，pip / HF 缓存在 data\\cache。整个目录可以直接拷走或删掉，不牵连系统目录。`;
  }
  const up = $("uninstallPath");
  if (up && data.uninstall) {
    up.textContent = data.uninstall.bat || data.uninstall.ps1 || `${data.root}\\uninstall.bat`;
  }
}

/* ---------------------------------------------------------------- 开机自启 */
function renderAutostart(st) {
  const badge = $("autostartBadge");
  if (!badge || !st) return;
  const enabled = !!st.enabled;
  const supported = !!st.supported;
  badge.className = "badge " + (!supported ? "warn" : enabled ? "good" : "ok");
  badge.textContent = !supported ? (st.platform === "docker" ? "容器内无需设置" : "当前系统不支持")
    : enabled ? (st.stale ? "有旧启动项" : "已开启") : "未开启";
  const portEl = $("autostartPort");
  if (portEl) portEl.textContent = st.port ? String(st.port) : "—";
  const on = $("autostartOn");
  const off = $("autostartOff");
  if (on) on.hidden = !supported || (enabled && !st.stale);
  if (off) off.hidden = !enabled;
  if (on && !on.hidden) on.textContent = st.stale ? "重新写入当前目录" : "开启开机自启";
  const detail = $("autostartDetail");
  if (detail) {
    let text = st.message || "";
    if (st.path && supported && (enabled || st.stale)) text += ` 位置：${st.path}`;
    detail.textContent = text;
  }
}

async function loadAutostart() {
  try {
    renderAutostart(await api("/api/system/autostart"));
  } catch (e) { /* 接口异常不影响部署页其他内容 */ }
}

async function toggleAutostart(on) {
  const btn = $(on ? "autostartOn" : "autostartOff");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = on ? "正在写入…" : "正在关闭…"; }
  try {
    const st = await api("/api/system/autostart", { method: on ? "POST" : "DELETE" });
    renderAutostart(st);
    uiToast(st.message || (on ? "已开启开机自启" : "已关闭开机自启"), "good");
  } catch (e) {
    uiToast(e.message || "操作失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

/* ---------------------------------------------------------------- 桌面快捷方式 */
function renderShortcuts(st) {
  const badge = $("shortcutsBadge");
  if (!badge || !st) return;
  const supported = !!st.supported;
  const exists = (st.items || []).filter((x) => x.exists).length;
  badge.className = "badge " + (!supported ? "warn" : exists ? "good" : "ok");
  badge.textContent = !supported ? (st.platform === "docker" ? "容器内无桌面" : "当前系统不支持")
    : exists ? "已创建" : "未创建";
  const urls = st.urls || {};
  const frontUrl = $("shortcutFrontUrl");
  const consoleUrl = $("shortcutConsoleUrl");
  if (frontUrl) frontUrl.textContent = urls.front || "—";
  if (consoleUrl) consoleUrl.textContent = urls.console || "—";
  const frontLink = $("shortcutFrontLink");
  const consoleLink = $("shortcutConsoleLink");
  if (frontLink && urls.front) frontLink.href = urls.front;
  if (consoleLink && urls.console) consoleLink.href = urls.console;
  const lanEl = $("shortcutLan");
  if (lanEl) {
    if (st.lan_url) {
      lanEl.hidden = false;
      lanEl.textContent = `手机或别的电脑用这个地址：${st.lan_url}`;
    } else {
      lanEl.hidden = true;
    }
  }
  const createBtn = $("shortcutsCreate");
  const removeBtn = $("shortcutsRemove");
  if (createBtn) createBtn.hidden = !supported;
  if (removeBtn) removeBtn.hidden = !exists;
  renderShortcutMode(st, supported);
  const detail = $("shortcutsDetail");
  if (detail) {
    let text = st.message || "";
    if (supported && exists && st.desktop) text += ` 桌面目录：${st.desktop}`;
    detail.textContent = text;
  }
}

async function loadShortcuts() {
  try {
    renderShortcuts(await api("/api/system/shortcuts"));
  } catch (e) { /* 接口异常不影响部署页其他内容 */ }
}

function renderShortcutMode(st, supported) {
  const modeSel = $("shortcutMode");
  const lanSel = $("shortcutLanIp");
  const customInput = $("shortcutCustomUrl");
  const saveBtn = $("shortcutSaveMode");
  const mode = st.mode || "local";
  if (modeSel) modeSel.value = mode;
  if (saveBtn) saveBtn.hidden = !supported;
  if (lanSel) {
    const ips = st.lan_ips || [];
    const chosen = st.lan_ip || "";
    lanSel.innerHTML = "";
    const list = ips.length ? ips : (chosen ? [{ ip: chosen, iface: "" }] : []);
    for (const item of list) {
      const opt = document.createElement("option");
      opt.value = item.ip;
      opt.textContent = item.iface ? `${item.ip}（${item.iface}）` : item.ip;
      lanSel.appendChild(opt);
    }
    if (chosen) lanSel.value = chosen;
    lanSel.hidden = mode !== "lan" || !list.length;
  }
  if (customInput) {
    customInput.value = st.custom_url || "";
    customInput.hidden = mode !== "custom";
  }
}

function shortcutModePayload() {
  const modeSel = $("shortcutMode");
  const lanSel = $("shortcutLanIp");
  const customInput = $("shortcutCustomUrl");
  return {
    mode: modeSel ? modeSel.value : "local",
    lan_ip: lanSel ? lanSel.value : "",
    custom_url: customInput ? customInput.value.trim() : "",
  };
}

async function saveShortcutMode() {
  const btn = $("shortcutSaveMode");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "保存中…"; }
  try {
    const st = await api("/api/system/shortcuts/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(shortcutModePayload()),
    });
    renderShortcuts(st);
    uiToast("地址已保存，下次双击桌面图标生效", "good");
  } catch (e) {
    uiToast(e.message || "保存失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

function bindShortcutModeEvents() {
  const modeSel = $("shortcutMode");
  if (modeSel) {
    modeSel.addEventListener("change", () => {
      const mode = modeSel.value;
      const lanSel = $("shortcutLanIp");
      const customInput = $("shortcutCustomUrl");
      if (lanSel) lanSel.hidden = mode !== "lan" || !lanSel.options.length;
      if (customInput) {
        customInput.hidden = mode !== "custom";
        if (mode === "custom") customInput.focus();
      }
      const hintEl = $("shortcutModeHint");
      if (hintEl) {
        hintEl.textContent = mode === "lan"
          ? "双击后用局域网地址打开，同一内网的手机和别的电脑也能进；换网络后记得回来改。"
          : mode === "custom"
            ? "填穿透或反代后的完整地址（http:// 或 https://），例如 Cloudflare 隧道域名。"
            : "双击后只用本机 127.0.0.1 打开，不依赖网络。";
      }
    });
  }
}

async function createShortcuts() {  const btn = $("shortcutsCreate");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "正在创建…"; }
  try {
    const st = await api("/api/system/shortcuts", { method: "POST" });
    renderShortcuts(st);
    uiToast(st.message || "已创建桌面快捷方式", "good");
  } catch (e) {
    uiToast(e.message || "创建失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

async function removeShortcuts() {
  const btn = $("shortcutsRemove");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "正在删除…"; }
  try {
    const st = await api("/api/system/shortcuts", { method: "DELETE" });
    renderShortcuts(st);
    uiToast(st.message || "已删除桌面快捷方式", "good");
  } catch (e) {
    uiToast(e.message || "删除失败", "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

async function loadModelsTab() {
  const models = await api("/api/models");
  renderModels(models);
  if (!S.timer) S.timer = setInterval(refreshLight, 3000);
}

async function loadAll() {
  await loadDeployment();
  await loadAutostart();
  await loadShortcuts();
  renderModels(S.deployModels);
  clearInterval(S.timer);
  S.timer = setInterval(refreshLight, 3000);
}

async function refreshLight() {
  try {
    if (S.tab === "models") {
      const m = await api("/api/models");
      renderModels(m);
    } else if (S.tab === "deploy" && Date.now() - (S.lastDeployAt || 0) > 8000) {
      await loadDeployment();
    }
  } catch (e) { /* 忽略轮询失败 */ }
}

