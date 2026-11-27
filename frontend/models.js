/* 用户端 · 模型下拉、模型切换与加载保护 | 原 app.js 第 754–1051 行 */
"use strict";
  /* ------------------------------------------------------------------ 模型 */
  function modelLabel(m) {
    const base = String(m.label || m.key || "").trim() || m.key;
    const tags = [m.vision ? "视觉" : "", m.light ? "轻量测试" : ""].filter(Boolean);
    const tag = tags.length ? `（${tags.join(" · ")}）` : "";
    return (m.source_platform ? `${base} · ${m.source_platform}` : base) + tag;
  }

  function modelRunnable(m) {
    return !!m && m.downloaded !== false && m.loaded === true;
  }

  /* 用户端只列“现在真能选”的模型：
     - 已经启动并可达的平台（含 Ollama / vLLM 等）由 /api/models 带 platform_key；
     - 算力池另外调度；
     - 本地 GGUF 必须装了 llama.cpp，否则选了也会在 /select 报“需要独立引擎”。 */
  function modelSelectable(m, d) {
    if (!m) return false;
    if (m.platform_key || m.owned_by === "platform" || m.owned_by === "cluster") return true;
    const engine = String(m.engine || "llama.cpp").toLowerCase();
    if (engine !== "llama.cpp") return false;
    const hw = (d && d.hardware) || {};
    return hw.llama_installed === true || m.loaded === true;
  }

  async function loadModels() {
    try {
      const d = await api("/api/models");
      S.localEnabled = d.local_enabled !== false;
      S.models = (d.items || []).filter((m) =>
        m.available !== false && m.downloaded !== false
        && ["text", "code", "vision"].includes(m.category || "text")
        && modelSelectable(m, d));
      S.serverModel = S.localEnabled ? ((d.server && d.server.model) || "") : "";
    } catch {
      S.models = [];
    }
    renderModelOptions();
    updateWelcome();
    if (!S.models.length) {
      $("#welcomeNote").textContent = S.localEnabled
        ? "当前账号还没有可用模型，请联系管理员在控制台「用户」页分配。"
        : "本地部署已在管理控制台关闭，暂时没有可用模型。";
    }
  }

  function renderModelOptions() {
    const select = $("#modelSelect");
    const opts = S.models.map((m) => `<option value="${esc(m.key)}">${esc(modelLabel(m))}</option>`).join("");
    select.innerHTML = opts || `<option value="">暂无可用模型</option>`;
    let current = (S.prefs && S.prefs.model) || "";
    const currentObj = S.models.find((m) => m.key === current);
    if (currentObj && currentObj.light) {
      const better = S.models.find((m) => modelRunnable(m) && !m.light)
        || S.models.find((m) => m.downloaded !== false && !m.light);
      if (better) {
        current = better.key;
        savePrefs({ model: current });
      }
    }
    if (!current || !S.models.some((m) => m.key === current)) {
      const fallback = S.models.find((m) => modelRunnable(m) && !m.light)
        || S.models.find((m) => modelRunnable(m))
        || S.models.find((m) => m.downloaded !== false && !m.light)
        || S.models.find((m) => m.downloaded !== false)
        || S.models[0];
      current = (fallback && fallback.key) || S.serverModel || "";
    }
    if (current && S.models.some((m) => m.key === current)) {
      select.value = current;
    }
    if (typeof syncAgentModelLock === "function") syncAgentModelLock();
  }

  function setModel(key, persist = true) {
    if (!S.models.some((m) => m.key === key)) return;
    $("#modelSelect").value = key;
    if (persist) savePrefs({ model: key });
    const picked = S.models.find((m) => m.key === key);
    if (picked && picked.light) toast("轻量测试模型只适合短问答，复杂任务会自动切换到默认强模型");
    if (typeof syncAgentModelLock === "function") syncAgentModelLock();
    updateWelcome();
  }

  /* 本地 llama.cpp 一次只加载一个模型，切换会重启进程；
     别人正在回答时先提示，让切换方自己选等待、强制还是取消。 */
  function busyRowsHtml(items) {
    return (items || []).map((it) => {
      const users = (it.users || []).join("、") || "其他账号";
      const secs = it.seconds ? ` · 已 ${it.seconds} 秒` : "";
      return `<li><b>${esc(it.model)}</b> · ${it.count || 1} 个回答 · ${esc(users)}${secs}</li>`;
    }).join("");
  }

  function askBusySwitch(items) {
    return new Promise((resolve) => {
      const mask = document.createElement("div");
      mask.className = "wb-mask";
      mask.innerHTML = `<div class="wb-dialog" role="dialog" aria-modal="true">
        <h3>本地模型正在被使用</h3>
        <p class="wb-busy-tip">本机同一时间只能加载一个模型。现在有别人的回答正在生成，直接切换会把它中断。</p>
        <ul class="wb-busy-list">${busyRowsHtml(items)}</ul>
        <div class="wb-dialog-actions">
          <button type="button" class="btn ghost" data-act="cancel">取消</button>
          <button type="button" class="btn danger" data-act="force">强制切换</button>
          <button type="button" class="btn primary" data-act="wait">等它说完</button>
        </div>
      </div>`;
      const onKey = (e) => { if (e.key === "Escape") done("cancel"); };
      const done = (v) => {
        document.removeEventListener("keydown", onKey);
        mask.remove();
        resolve(v);
      };
      document.addEventListener("keydown", onKey);
      mask.addEventListener("click", (e) => {
        if (e.target === mask) return done("cancel");
        const act = e.target.closest("[data-act]");
        if (act) done(act.dataset.act);
      });
      document.body.appendChild(mask);
    });
  }

  function openWaitMask(items) {
    const mask = document.createElement("div");
    mask.className = "wb-mask";
    mask.innerHTML = `<div class="wb-dialog" role="dialog" aria-modal="true">
      <h3>正在等对方说完</h3>
      <p class="wb-busy-tip">回答结束后会自动切到新模型。等待期间对方的回答不会被打断。</p>
      <ul class="wb-busy-list">${busyRowsHtml(items)}</ul>
      <div class="wb-dialog-actions">
        <button type="button" class="btn ghost" data-act="cancel">取消等待</button>
      </div>
    </div>`;
    document.body.appendChild(mask);
    const list = mask.querySelector(".wb-busy-list");
    const ctl = {
      cancelled: false,
      update(next) { list.innerHTML = busyRowsHtml(next); },
      close() { mask.remove(); },
    };
    mask.addEventListener("click", (e) => {
      if (e.target === mask || e.target.closest('[data-act="cancel"]')) {
        ctl.cancelled = true;
        ctl.close();
      }
    });
    return ctl;
  }

  async function waitForFree(ctl) {
    let last = [];
    for (let i = 0; i < 240 && !ctl.cancelled; i += 1) {
      try {
        const d = await api("/api/models/in-use");
        last = d.busy || [];
      } catch {
        last = last || [];
      }
      if (!ctl.cancelled && !last.length) return true;
      if (!ctl.cancelled) ctl.update(last);
      await new Promise((r) => setTimeout(r, 2000));
    }
    return false;
  }

  async function ensureModelLoaded(key) {
    const model = S.models.find((m) => m.key === key);
    if (!model || model.loaded === true || S.modelSwitching) return;
    if (model.owned_by === "platform" || model.platform_key) {
      setModel(key);
      return;
    }
    const previous = (S.prefs && S.prefs.model) || "";
    S.modelSwitching = true;
    const select = $("#modelSelect");
    select.disabled = true;
    toast("正在切换模型…");
    let force = false;
    let givenUp = false;
    try {
      while (true) {
        try {
          await api("/api/models/select", { method: "POST", body: { key, force } });
          await loadModels();
          toast("模型已就绪");
          return;
        } catch (e) {
          const detail = (e && e.data && e.data.detail) || {};
          if (e.status !== 409 || detail.code !== "model_busy") throw e;
          const items = detail.items || [];
          const act = await askBusySwitch(items);
          if (act === "cancel") { givenUp = true; break; }
          if (act === "force") { force = true; continue; }
          force = false;
          const ctl = openWaitMask(items);
          const free = await waitForFree(ctl);
          ctl.close();
          if (!free) { givenUp = true; break; }
        }
      }
      if (givenUp) {
        if (previous) setModel(previous);
        await loadModels();
        toast("已取消切换，保持原来的模型");
      }
    } catch (e) {
      const loaded = S.models.find((m) => modelRunnable(m));
      if (loaded) setModel(loaded.key);
      await loadModels();
      toast(e.message || "模型加载失败");
    } finally {
      S.modelSwitching = false;
      select.disabled = false;
    }
  }

  function selectedModel() {
    const key = (S.prefs && S.prefs.model) || $("#modelSelect").value || "";
    return S.models.find((m) => m.key === key) || null;
  }

  function renderWelcomeDate() {
    const el = $("#welcomeDate");
    if (!el) return;
    const d = new Date();
    const week = "日一二三四五六"[d.getDay()];
    el.textContent = `${d.getMonth() + 1} 月 ${d.getDate()} 日 周${week}`;
  }

  function renderWelcomeContinue(activeTpl) {
    const wrap = $("#welcomeContinue");
    const grid = $("#welcomeWbGrid");
    if (!wrap || !grid) return;
    const all = wbTemplatesAll();
    const picks = [];
    const add = (tpl) => {
      if (tpl && !picks.some((x) => x.id === tpl.id)) picks.push(tpl);
    };
    add(activeTpl);
    ["teacher", "finance", "writing", "design"].forEach((id) => add(all.find((t) => t.id === id)));
    all.slice(0, 3).forEach(add);
    if (!picks.length) {
      wrap.hidden = true;
      grid.innerHTML = "";
      return;
    }
    wrap.hidden = false;
    grid.innerHTML = picks.slice(0, 3).map((tpl) => {
      const desc = tpl.welcomeSub || tpl.desc || "打开工作台继续";
      return `<button class="wc-card" type="button" data-wb-home="${esc(tpl.id)}">`
        + `<span class="wc-icon">${esc(tpl.icon || "🧩")}</span>`
        + `<span class="wc-copy"><b>${esc(tpl.name)}</b><small>${esc(desc)}</small></span>`
        + `<span class="wc-arrow"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></span>`
        + `</button>`;
    }).join("");
  }

  function renderWelcomeHome() {
    const welcome = $("#welcome");
    const box = $("#suggestions");
    if (!welcome || !box) return;
    const tpl = wbTemplateOf();
    const mark = $("#welcomeMark");
    const badge = $("#welcomeWorkbench");
    const title = $("#welcomeTitle");
    const sub = $("#welcomeSub");
    const caps = $("#welcomeCaps");

    renderWelcomeDate();
    welcome.classList.toggle("is-workbench", !!tpl);
    welcome.dataset.tone = tpl ? (tpl.tone || "custom") : "";
    if (tpl) {
      mark.classList.add("emoji");
      mark.innerHTML = `<span>${esc(tpl.icon || "🧩")}</span>`;
      badge.hidden = false;
      badge.textContent = `正在使用 · ${tpl.name}`;
      title.textContent = tpl.welcome || `今天想在「${tpl.name}」里做什么？`;
      sub.textContent = tpl.welcomeSub || tpl.desc || "选一个推荐任务开始，也可以直接描述你的需求。";
      const names = wbSkillNamesOf(tpl).slice(0, 3);
      const plugins = (tpl.plugins || []).map(wbPluginName);
      const chips = [
        names.length ? `<span>技能 · ${esc(names.join(" / "))}</span>` : "",
        plugins.length ? `<span>插件 · ${esc(plugins.join(" / "))}</span>` : "",
      ].join("");
      caps.innerHTML = chips;
      caps.hidden = !chips;
    } else {
      mark.classList.remove("emoji");
      mark.innerHTML = `<svg><use href="#i-spark"/></svg>`;
      badge.hidden = true;
      badge.textContent = "";
      title.textContent = "今天想做什么？";
      sub.textContent = "直接说任务。需要资料、联网或工作台时，再打开对应工具。";
      caps.innerHTML = "";
      caps.hidden = true;
    }

    box.classList.toggle("pills", !!tpl);
    const items = tpl ? (tpl.quick || []).slice(0, 8) : WELCOME_QUICK_DEFAULT;
    const formatName = { docx: "Word", xlsx: "Excel", pptx: "PPT" };
    box.innerHTML = items.map((x) => {
      const fmt = formatName[x.format] || "";
      if (tpl) {
        return `<button type="button" data-suggest="${esc(x.text)}" data-suggest-format="${esc(x.format || "")}">`
          + `<span class="suggest-pill-dot" aria-hidden="true"></span>${esc(x.label)}`
          + (fmt ? `<em>${fmt}</em>` : "") + `</button>`;
      }
      return `<button type="button" class="quick-card q-${esc(x.tone || "blue")}" data-suggest="${esc(x.text)}" data-suggest-format="${esc(x.format || "")}">`
        + `<span class="q-icon"><svg><use href="#i-${esc(x.icon || "spark")}"/></svg></span>`
        + `<b>${esc(x.label)}</b><small>${esc(x.desc || "")}</small>`
        + `<span class="arrow"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg></span>`
        + `</button>`;
    }).join("");

    renderWelcomeContinue(tpl);
  }


  function updateWelcome() {
    renderWelcomeHome();
    const m = selectedModel();
    if (m) $("#welcomeNote").textContent = "模型在本地运行，对话记录只保存在这台机器。";
    if (!S.models.length) $("#welcomeNote").textContent = S.localEnabled
      ? "当前账号还没有可用模型，请联系管理员分配。"
      : "本地部署已在管理控制台关闭，暂时没有可用模型。";
  }

