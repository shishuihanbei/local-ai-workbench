/* 控制台 · loadAll / switchTab、全局事件入口、登录提交 | 原 console.js 第 1034–1404 行 */
/* ---------------------------------------------------------------- 事件 */
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button");
  if (!t) return;
  try {
    if (t.id === "clusterRefresh") {
      const res = await api("/api/admin/cluster/refresh", { method: "POST" });
      uiToast(`已检查 ${(res.items || []).length} 个节点`);
      await loadClusterPage();
      return;
    }
    if (t.id === "clusterNodeSave") { await clusterSaveNode(); return; }
    if (t.id === "clusterNodeProbe") { await clusterProbe(); return; }
    if (t.id === "clusterNodeCancel") { resetClusterNodeForm(); return; }
    if (t.id === "clusterPoolSave") { await clusterSavePool(); return; }
    if (t.id === "clusterPoolCancel") { resetClusterPoolForm(); return; }
    if (t.id === "clusterAddMember") {
      S.clusterMembers.push(clusterDefaultMember());
      renderClusterMembers();
      return;
    }
    if (t.id === "clusterCopyExample") {
      const text = $("clusterExample").textContent;
      try { await navigator.clipboard.writeText(text); uiToast("示例已复制"); }
      catch { uiToast("复制失败，请手动选择文本", "bad"); }
      return;
    }
    if (t.classList.contains("member-del")) {
      const idx = Number(t.dataset.memberDel);
      S.clusterMembers.splice(idx, 1);
      if (!S.clusterMembers.length) S.clusterMembers = [clusterDefaultMember()];
      renderClusterMembers();
      return;
    }
    if (t.dataset.clusterNodeEdit) {
      const node = (S.cluster.nodes || []).find((n) => n.id === Number(t.dataset.clusterNodeEdit));
      if (node) clusterFillNodeForm(node);
      return;
    }
    if (t.dataset.clusterNodeTest) {
      await api(`/api/admin/cluster/nodes/${t.dataset.clusterNodeTest}/test`, { method: "POST" });
      await loadClusterPage();
      uiToast("节点状态已更新");
      return;
    }
    if (t.dataset.clusterNodeDel) {
      if (!await confirmInline("删除这个节点？模型池里引用它的成员会一起失效。", "删除")) return;
      await api(`/api/admin/cluster/nodes/${t.dataset.clusterNodeDel}`, { method: "DELETE" });
      await loadClusterPage();
      uiToast("节点已删除");
      return;
    }
    if (t.dataset.clusterPoolEdit) {
      const pool = (S.cluster.pools || []).find((p) => p.id === Number(t.dataset.clusterPoolEdit));
      if (pool) clusterFillPoolForm(pool);
      return;
    }
    if (t.dataset.clusterPoolDel) {
      if (!await confirmInline("删除这个模型池？节点本身不会被删除。", "删除")) return;
      await api(`/api/admin/cluster/pools/${t.dataset.clusterPoolDel}`, { method: "DELETE" });
      await loadClusterPage();
      uiToast("模型池已删除");
      return;
    }
    if (t.classList.contains("usage-more")) { toggleGuideDetail(t); return; }
    if (t.hasAttribute("data-custom-guide")) {
      const panel = $("customOpenaiGuide");
      const body = $("customGuideBody");
      const toggle = $("customGuideToggle");
      if (body) body.hidden = false;
      if (panel) panel.hidden = false;
      if (toggle) { toggle.textContent = "关闭说明"; toggle.setAttribute("aria-expanded", "true"); }
      if (panel) panel.scrollIntoView({ block: "start" });
      return;
    }
    if (t.id === "customGuideToggle") {
      const panel = $("customOpenaiGuide");
      if (panel) panel.hidden = true;
      return;
    }
    if (t.dataset && t.dataset.mcat) {
      S.modelCategory = t.dataset.mcat;
      const items = (S.models && S.models.items) || [];
      renderModelFilters(items);
      renderModelRows();
      return;
    }
    if (t.id === "refreshBtn") {
      if (!token()) { showLogin(); return; }
      const btn = $("refreshBtn");
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = "刷新中…";
      const r = await refreshCurrent();
      if (r.ok) {
        const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        btn.textContent = `已刷新 ${time}`;
        setTimeout(() => { btn.textContent = "刷新数据"; btn.disabled = false; }, 1800);
      } else {
        btn.textContent = "刷新失败";
        uiToast(`刷新失败：${r.error || "请检查后端连接"}`);
        setTimeout(() => { btn.textContent = "刷新数据"; btn.disabled = false; }, 1800);
      }
    }
    else if (t.id === "logoutBtn") {
      const tk = token();
      const headers = {};
      if (tk) headers.Authorization = "Bearer " + tk;
      else {
        const csrf = cookieValue("wb_csrf");
        if (csrf) headers["X-CSRF-Token"] = csrf;
      }
      localStorage.removeItem(TOKEN_KEY);
      S.cookieSession = false;
      showLogin();
      // 一并结束 cookie 会话：控制台与用户端共用同一个登录态
      fetch("/api/auth/logout", { method: "POST", headers, credentials: "same-origin" }).catch(() => {});
    }
    else if (t.id === "installBtn") {
      t.disabled = true;
      const r = await api("/api/system/install-llama" + (S.install && S.install.llama.installed ? "?force=true" : ""), { method: "POST" });
      if (!r.ok) { $("installText").textContent = r.msg || "无法开始安装"; t.disabled = false; return; }
      pollInstall();
    }
    else if (t.id === "refreshModels") {
      const btn = t;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "更新中…";
      try {
        const r = await api("/api/models/refresh", { method: "POST" });
        await loadModelsTab();
        btn.textContent = r.added
          ? (r.discovered ? `补充 ${r.added} · 目录 ${r.discovered}` : `已补充 ${r.added} 个`)
          : "已是最新";
      } catch (e) {
        btn.textContent = "更新失败";
        uiToast(e.message);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      return;
    }
    else if (t.id === "autostartOn") { await toggleAutostart(true); return; }
    else if (t.id === "autostartOff") { await toggleAutostart(false); return; }
    else if (t.id === "shortcutsCreate") { await createShortcuts(); return; }
    else if (t.id === "shortcutsRemove") { await removeShortcuts(); return; }
    else if (t.id === "shortcutSaveMode") { await saveShortcutMode(); return; }
    else if (t.id === "refreshPlatforms") {
      const btn = t;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "更新中…";
      try {
        const r = await api("/api/system/local-deploy?scan=1");
        S.deployData = { ...(S.deployData || {}), ...r };
        renderPlatforms(S.deployData);
        const found = (r.platforms || []).filter((p) => p.healthy).length;
        btn.textContent = `已更新 · ${found} 个可用`;
      } catch (e) {
        btn.textContent = "更新失败";
        uiToast(e.message);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      return;
    }
    else if (t.id === "networkCheck") {
      const btn = t;
      const old = btn.textContent;
      btn.disabled = true;
      btn.textContent = "诊断中…";
      try {
        const r = await api("/api/system/network-check");
        const rows = (r.results || []).map((x) =>
          `<span class="network-item ${x.ok ? "ok" : "bad"}">${esc(x.name)} ${x.ok ? (x.ms + "ms") : "不可用"}</span>`).join("");
        $("networkHint").innerHTML = `网络：${esc(r.msg || "")}<div class="network-list">${rows}</div>`;
        uiToast(r.msg || "网络诊断完成");
        btn.textContent = r.ok ? "网络可用" : "网络异常";
      } catch (e) {
        btn.textContent = "诊断失败";
        uiToast(e.message);
      }
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 2200);
      return;
    }
    else if (t.id === "deploySelected") {
      const keys = platformSelection();
      const byKey = Object.fromEntries((S.platforms || []).map((p) => [p.key, p]));
      const usable = keys.filter((k) => byKey[k] && byKey[k].deployable !== false && byKey[k].action !== "running");
      if (!usable.length) { uiToast("已选平台都已运行，或本机不支持自动部署"); return; }
      t.disabled = true;
      t.textContent = "部署中…";
      const started = [];
      for (let i = 0; i < usable.length; i++) {
        const key = usable[i];
        t.textContent = `部署中 ${i + 1}/${usable.length}`;
        try {
          const endpoint = (platformEndpointValues()[key] || "").trim();
          const qs = endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : "";
          const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/deploy${qs}`, { method: "POST" });
          if (r.ok) { started.push(key); await pollPlatform(key); }
          else uiToast(`${byKey[key].name}：${r.msg || "无法开始"}`);
        } catch (e) { uiToast(`${byKey[key].name}：${e.message}`); }
      }
      t.textContent = `已开始 ${started.length} 个`;
      setTimeout(() => { t.textContent = "部署已选平台"; t.disabled = false; }, 1800);
      return;
    }
    else if (t.id === "copyUninstallBtn") {
      const home = S.engineHome || {};
      const bat = (home.uninstall && home.uninstall.bat) || `${home.root || ""}\\uninstall.bat`;
      try {
        await navigator.clipboard.writeText(`"${bat}"`);
        uiToast("已复制 uninstall.bat 路径，粘贴到 PowerShell 里回车即可");
      } catch (e) { uiToast(bat); }
      return;
    }
    else if (t.dataset.copyPath) {
      const text = t.dataset.copyPath;
      try {
        await navigator.clipboard.writeText(text);
        uiToast("已复制路径");
      } catch (e) { uiToast("复制失败，请手动选择路径"); }
      return;
    }
    else if (t.dataset.pdeployManage) {
      const key = t.dataset.pdeployManage;
      if (S.platformPolling[key]) return;
      const old = t.textContent;
      t.disabled = true;
      t.textContent = "准备安装…";
      try {
        const endpoint = (platformEndpointValues()[key] || "").trim();
        const qs = `force=true${endpoint ? `&endpoint=${encodeURIComponent(endpoint)}` : ""}`;
        const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/deploy?${qs}`, { method: "POST" });
        if (!r.ok) throw new Error(r.msg || "无法开始安装");
        t.textContent = "安装中…";
        await pollPlatform(key);
      } catch (e) {
        uiToast(e.message);
      } finally {
        const btn = document.querySelector(`[data-pdeploy-manage="${key}"]`);
        if (btn) { btn.textContent = old; btn.disabled = false; }
      }
      return;
    }
    else if (t.dataset.adoptModels) {
      const key = t.dataset.adoptModels;
      const old = t.textContent;
      t.disabled = true;
      t.textContent = "迁移中…";
      try {
        const r = await api("/api/system/local-platforms/ollama/adopt-models", { method: "POST" });
        uiToast(r.msg || (r.ok ? "迁移完成" : "迁移失败"));
        if (r.ok) {
          const data = await api("/api/system/local-deploy?scan=1");
          S.deployData = { ...(S.deployData || {}), ...data };
          renderPlatforms(S.deployData);
        }
      } catch (e) {
        uiToast(e.message);
      } finally {
        const btn = document.querySelector(`[data-adopt-models="${key}"]`);
        if (btn) { btn.textContent = old; btn.disabled = false; }
      }
      return;
    }
    else if (t.id === "ollamaPullBtn") {
      const input = $("ollamaTag");
      const tag = (input && input.value.trim()) || "";
      if (!tag) { uiToast("先填一个 Ollama tag，例如 qwen2.5:7b"); return; }
      t.disabled = true;
      const old = t.textContent;
      t.textContent = "拉取中…";
      try {
        const r = await api("/api/system/local-platforms/ollama/pull", {
          method: "POST", body: JSON.stringify({ tag }),
        });
        uiToast(r.msg || "已开始拉取");
        if (!r.ok) { t.textContent = old; t.disabled = false; return; }
        if (input) input.value = "";
        await pollOllamaPull();
      } catch (e) {
        uiToast(e.message);
        t.textContent = old;
        t.disabled = false;
      }
      return;
    }
    else if (t.dataset.puninstall) {
      const key = t.dataset.puninstall;
      if (S.platformPolling[key]) return;
      const ok = await confirmInline(
        `卸载 ${key}？会先停掉工作台拉起的进程和相关端口，再删掉工作台装进 platforms 的程序与下载缓存；`
        + "你自己下载的模型和 data\\installers 里的安装包会保留。",
        "卸载");
      if (!ok) return;
      const old = t.textContent;
      t.disabled = true;
      t.textContent = "卸载中…";
      try {
        const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/uninstall`, { method: "POST" });
        uiToast(r.msg || (r.ok ? "已卸载" : "卸载失败"));
        if (!r.ok) { t.textContent = old; t.disabled = false; return; }
        const data = await api("/api/system/local-deploy?scan=1");
        S.deployData = { ...(S.deployData || {}), ...data };
        renderPlatforms(S.deployData);
        await loadAll();
      } catch (e) {
        uiToast(e.message);
        t.textContent = old;
        t.disabled = false;
      }
      return;
    }
    else if (t.dataset.opull) {
      const tag = t.dataset.opull;
      const old = t.textContent;
      t.disabled = true;
      t.textContent = "拉取中…";
      try {
        const r = await api("/api/system/local-platforms/ollama/pull", {
          method: "POST", body: JSON.stringify({ tag }),
        });
        uiToast(r.msg || "已开始拉取");
        if (!r.ok) { t.textContent = old; t.disabled = false; return; }
        await pollOllamaPull();
      } catch (e) {
        uiToast(e.message);
        t.textContent = old;
        t.disabled = false;
      }
      return;
    }
    else if (t.dataset.pdeploy) {
      const key = t.dataset.pdeploy;
      const p = (S.platforms || []).find((x) => x.key === key) || {};
      if (p.deployable === false || S.platformPolling[key]) return;
      t.disabled = true;
      const old = t.textContent;
      t.textContent = p.key === "custom" ? "测试中…" : "部署中…";
      try {
        const endpoint = (platformEndpointValues()[key] || "").trim();
        const qs = endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : "";
        const r = await api(`/api/system/local-platforms/${encodeURIComponent(key)}/deploy${qs}`, { method: "POST" });
        if (!r.ok) {
          uiToast(r.msg || "无法开始部署");
          t.textContent = old;
          t.disabled = false;
          return;
        }
        await pollPlatform(key);
        const btn = document.querySelector(`[data-pdeploy="${key}"]`);
        if (btn && /部署中|测试中/.test(btn.textContent)) {
          btn.textContent = old;
          btn.disabled = false;
        }
      } catch (e) {
        uiToast(e.message);
        t.textContent = old;
        t.disabled = false;
      }
      return;
    }
    else if (t.id === "storageSave") {
      await saveStorage();
      return;
    }
    else if (t.id === "storageDefault") {
      const defaults = (S.storage && S.storage.defaults) || {};
      if ($("storageModels")) $("storageModels").value = defaults.models_dir || "";
      if ($("storagePlatforms")) $("storagePlatforms").value = defaults.platforms_dir || "";
      if ($("storageMsg")) $("storageMsg").textContent = "已填入程序根目录下的默认位置，点「保存位置」生效。";
      return;
    }
    else if (t.id === "savePlatforms") {
      const btn = t;
      btn.disabled = true;
      const old = btn.textContent;
      btn.textContent = "保存中…";
      try {
        const selected = platformSelection();
        const proxy = ($("githubProxy") && $("githubProxy").value.trim()) || "auto";
        S.platformProxy = proxy;
        const r = await api("/api/system/local-platforms", {
          method: "PUT",
          body: JSON.stringify({ platforms: selected, endpoints: platformEndpointValues(), github_proxy: proxy }),
        });
        S.platformSelected = r.selected || selected;
        S.platformEndpoints = r.endpoints || S.platformEndpoints;
        S.platformProxy = r.github_proxy || S.platformProxy;
        S.platformDirty = false;
        S.deployData = { ...(S.deployData || {}), ...r };
        renderPlatforms(S.deployData);
        btn.textContent = "已保存";
        setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      } catch (e) {
        btn.textContent = "保存失败";
        uiToast(e.message);
        setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1800);
      }
      return;
    }
    else if (t.id === "localDeployBtn") {
      const enable = t.dataset.next === "on";
      const selected = platformSelection();
      if (!enable && !(await confirmInline("确定关闭本地部署？关闭后用户端和 API 将不能使用本地模型。", "关闭部署"))) return;
      S.platformSelected = selected;
      S.platformEndpoints = platformEndpointValues();
      S.localBusy = true;
      t.disabled = true;
      t.textContent = enable ? "正在开启…" : "正在关闭…";
      try {
        const r = await api("/api/system/local-deploy", {
          method: "POST",
          body: JSON.stringify({ enabled: enable, platforms: selected, endpoints: S.platformEndpoints, github_proxy: S.platformProxy }),
        });
        if (!r.ok || (enable && !r.started) || (r.msg || "").startsWith("外部")) {
          uiToast(r.msg || (r.ok ? "操作已完成" : "操作失败"));
        }
        S.platformDirty = false;
      } finally {
        S.localBusy = false;
        await loadAll();
      }
    }
    else if (t.dataset.engineInstall) {
      t.disabled = true;
      t.textContent = "安装中…";
      const engineKey = t.dataset.engineInstall;
      const r = await api(`/api/engines/${engineKey}/install`, { method: "POST" });
      if (r && r.msg) uiToast(r.msg);
      await loadAll();
      pollEngineInstall(engineKey);
    }
    else if (t.dataset.copyEngine) {
      const info = ((S.models && S.models.engine_catalog) || []).find((e) => e.key === t.dataset.copyEngine);
      if (!info) throw new Error("没有找到安装命令");
      try {
        await navigator.clipboard.writeText(info.install);
        uiToast("安装命令已复制");
      } catch (e) {
        uiToast("复制失败，请手动选中命令复制");
      }
    }
    else if (t.dataset.dl) {
      const dlKey = t.dataset.dl;
      const item = ((S.models && S.models.items) || []).find((m) => m.key === dlKey);
      t.disabled = true;
      t.textContent = "下载中…";
      // 乐观更新：这一行立刻变成「下载中」，不用等整表刷新（否则点了像没反应）
      if (item) {
        item.download = { ...(item.download || {}), state: "running", pct: item.pct || 0 };
        renderModelRows();
      }
      try {
        const r = await api(`/api/models/${dlKey}/download`, { method: "POST" });
        if (r && r.msg) uiToast(r.msg);
      } finally {
        await loadAll();
      }
      pollModelDownload(dlKey);
    }
    else if (t.dataset.load) {
      t.disabled = true;
      await api("/api/models/load", { method: "POST", body: JSON.stringify({ key: t.dataset.load }) });
      await loadAll();
    }
  } catch (e) { uiToast(e.message); t.disabled = false; }
});

$("loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("loginBtn");
  if (btn.disabled) return;
  $("alert").textContent = "";
  try {
    const path = S.setupMode ? "/api/auth/setup" : "/api/auth/login";
    if (S.setupMode) {
      if ($("p").value.length < 6) throw new Error("密码至少 6 位");
      if ($("p").value !== $("p2").value) throw new Error("两次输入的密码不一致");
    }
    btn.disabled = true;
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("u").value.trim(), password: $("p").value }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(errorMessage(d, S.setupMode ? "初始化失败" : "登录失败"));
    if (d.access_token) localStorage.setItem(TOKEN_KEY, d.access_token);
    S.cookieSession = true;
    saveConsoleUser($("u").value.trim());
    S.setupMode = false;
    const me = await api("/api/auth/me");
    applyAdminPermissions(me.user);
    applyBranding(S.branding, me.user.username);
    showMain();
    try {
      const la = await api("/api/system/local-access");
      S.localClient = !!la.local;
    } catch { S.localClient = true; }
    await switchTab(initialTab());
  } catch (e) { $("alert").textContent = e.message; }
  finally { btn.disabled = false; }
});

