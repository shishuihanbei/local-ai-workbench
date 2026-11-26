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
  $("installInfo").innerHTML = `
    <div class="status-line"><span class="dot ${llama.installed ? "on" : ""}"></span>
      <b>${llama.installed ? "llama.cpp 已就绪" : "本机未安装 llama.cpp"}</b></div>
    <div class="mono">${esc(llama.installed ? (llama.path + (llama.version ? " · " + llama.version : "")) : "安装后会写入 " + llama.llama_dir)}</div>
    <div class="mono">模型目录：${esc(st.models_dir)} ${st.models_dir_exists ? "（存在）" : "（不存在，会自动创建）"}</div>`;

  const canInstall = !llama.installed && st.supported;
  $("installBtn").hidden = !st.supported;
  $("installBtn").textContent = llama.installed ? "修复安装 llama.cpp" : "备用安装 llama.cpp";
  $("installBtn").disabled = !!st.install.running;
  $("installHint").textContent = st.install.running ? "安装进行中…"
    : llama.installed ? "已安装；正常请在平台卡点“一键部署”"
    : (st.supported ? "正常请用平台卡的“一键部署”；这里作为备用入口" : "当前系统需手动安装");

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
      html.push(`<tr>
        <td><div class="name">${esc(m.label || m.key)}</div><div class="sub">${esc(m.key)}${m.filename ? " · " + esc(m.filename) : ""}</div></td>
        <td><span class="badge cat">${esc(m.category_label || modelCategoryLabel(m.category))}</span></td>
        <td><div>${esc(m.engine || "—")}</div>${m.installable === false ? `<div class="sub">推荐 ${esc(m.engine_recommend || "独立引擎")} · ${m.engine_ready ? "已安装" : "未安装"}</div>` : ""}</td>
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
      ? `已安装${p.version ? " · " + p.version : ""}${p.install_path ? " · " + p.install_path : ""}`
      : (p.installable ? "尚未安装，可一键部署" : "需要手动安装");
    const label = p.action_label || "一键部署";
    const disabled = p.deployable === false || (p.install && p.install.running);
    const action = p.key === "custom"
      ? `<button class="btn small" data-pdeploy="${esc(p.key)}">${esc(label)}</button>
         <button class="btn small ghost" data-custom-guide>接入说明</button>`
      : `<button class="btn small ${p.action === "install" ? "primary" : ""}" data-pdeploy="${esc(p.key)}" ${disabled ? "disabled" : ""}>${esc(label)}</button>`;
    return `<div class="platform-card ${on ? "on" : ""}">
      <div class="platform-head">
        <label><input type="checkbox" data-platform="${esc(p.key)}" ${on ? "checked" : ""}><b>${esc(p.name)}</b>${mm}</label>
        ${state}
      </div>
      <div class="platform-note">${esc(p.note || "")}</div>
      <div class="platform-detail">${esc(p.detail || "")} ${link}</div>
      <div class="platform-installed">${esc(installedText)}</div>
      <div class="platform-suit"><span class="badge ${esc(fit.level || "unknown")}">${esc(fit.label || "需确认")}</span><span>${esc(fit.text || "")}</span></div>
      <div class="platform-types">${types || `<span class="chip">未标注</span>`}</div>
      ${url}
      <div class="platform-actions">${action}</div>
      <div class="platform-progress" data-platform-progress="${esc(p.key)}" hidden>
        <div class="bar"><i data-platform-bar="${esc(p.key)}"></i></div>
        <div class="progress-text" data-platform-text="${esc(p.key)}"></div>
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
    uiToast(`${last.ok ? "部署完成" : "部署失败"}：${last.msg || ""}`);
    if (last.ok && !S.platformDirty) {
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

function renderLocalDeploy(data) {
  const on = data.local_enabled !== false;
  const srv = data.server || {};
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
  let title, desc, meta;
  if (on && srv.running && srv.healthy) {
    dot.className = "dot on"; badge.className = "badge good"; badge.textContent = "运行中";
    title = "本地部署已开启";
    desc = "用户端和 OpenAI 接口可以调用本地模型。关闭后本地模型会立即从可用列表移除，并拒绝本地模型请求。";
    meta = `模型 ${srv.model || "—"} · 端口 ${srv.port || 8080}${srv.external ? " · 外部进程" : ""}`;
  } else if (on && srv.running) {
    dot.className = "dot warn"; badge.className = "badge warn"; badge.textContent = "启动中";
    title = "本地部署已开启，服务正在启动";
    desc = "llama-server 进程已创建，正在等待模型加载完成。";
    meta = `模型 ${srv.model || "—"} · 端口 ${srv.port || 8080}`;
  } else if (on) {
    dot.className = "dot warn"; badge.className = "badge warn"; badge.textContent = "待运行";
    title = "本地部署已开启，模型未运行";
    desc = installed
      ? "开启状态已生效。请在模型清单里下载并加载一个模型，加载后用户端即可对话。"
      : "开启状态已生效，但本机还没有安装 llama.cpp，请先在上方平台卡点“一键部署”。";
    meta = installed ? `模型目录 ${data.models_dir || "—"}` : "缺少 llama.cpp";
  } else {
    dot.className = "dot"; badge.className = "badge off"; badge.textContent = "已关闭";
    title = "本地部署已关闭";
    desc = "用户端不会显示本地模型，OpenAI 接口也会拒绝本地模型请求；配置了第三方供应商时会自动改用云端。";
    meta = (srv.external || srv.healthy)
      ? "检测到 8080 端口仍有外部 llama-server 运行，工作台不会强制结束它。"
      : "已停止工作台持有的本地模型进程。";
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
  $("modelHint").textContent = `本地${enabled ? "已开启" : "已关闭"} · 服务 ${srv.running ? "运行中" : "未运行"}${srv.model ? " · 当前 " + srv.model : ""} · ${items.length} 个模型 · 已下载 ${ready} · 单模型运行，点“加载”会切换当前模型`;
  renderModelFilters(items);
  renderModelRows();
  renderEngineSummary(items);
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

function renderService(hw, data) {
  const srv = data.server || {};
  const hardware = hw || {};
  $("svcRow").innerHTML = `
    <div class="svc"><h3>模型服务</h3><p>${srv.running ? "运行中" : "未运行"}${srv.external ? "（外部进程）" : ""} · 端口 ${esc(srv.port || 8080)}</p></div>
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
  renderService(hw, models);
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
  const [hw, models, deploy, storage] = await Promise.all([
    api("/api/system/hardware"),
    api("/api/models"),
    api("/api/system/local-deploy"),
    api("/api/system/storage"),
  ]);
  renderDeployment(hw, models, deploy);
  renderStorage(storage);
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

