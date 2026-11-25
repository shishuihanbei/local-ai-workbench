(() => {
  const view = document.getElementById("view");
  const toastEl = document.getElementById("toast");
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const fmt = (v) => ({ docx: "Word", xlsx: "Excel", pptx: "PPT", pdf: "PDF", md: "Markdown", txt: "纯文本" }[v] || "");
  const plugins = (v) => ({ web: "联网检索", kb: "知识库检索", docgen: "文档生成" }[v] || "");
  let toastTimer = 0;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2200);
  }
  function fail(title, detail) {
    view.innerHTML = `<div class="error"><b>${esc(title)}</b><span>${esc(detail || "")}</span></div>`;
  }
  function tokenFromPath() {
    const parts = location.pathname.split("/").filter(Boolean);
    return parts[0] === "wb" ? (parts[1] || "") : "";
  }
  async function load() {
    const token = tokenFromPath();
    if (!token) return fail("链接不完整", "请让分享者重新生成工作台链接。");
    try {
      const res = await fetch(`/api/workbench/shares/${encodeURIComponent(token)}`, {
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "这个分享不存在或已经失效");
      render(data);
    } catch (e) {
      fail("无法打开这个工作台", e.message || "请稍后再试");
    }
  }
  function render(d) {
    document.title = `${d.name || "工作台"} · 本地 AI 工作台`;
    const quick = Array.isArray(d.quick) ? d.quick : [];
    const skillNames = Array.isArray(d.skill_names) && d.skill_names.length
      ? d.skill_names
      : (d.skill_name ? [d.skill_name] : []);
    const caps = [
      ...skillNames.map((s) => `技能 · ${s}`),
      ...(Array.isArray(d.plugins) ? d.plugins : []).map((p) => plugins(p)).filter(Boolean).map((p) => `插件 · ${p}`),
    ].filter(Boolean);
    const expire = d.expires_at
      ? `有效期至 ${new Date(d.expires_at * 1000).toLocaleDateString("zh-CN")}`
      : "永久有效";
    view.innerHTML = `
      <div class="hero">
        <div class="icon">${esc(d.icon || "🧩")}</div>
        <h1>${esc(d.name || "分享的工作台")}</h1>
        <p class="desc">${esc(d.description || "这个工作台准备了一组常用快捷按钮，导入后可以直接开工。")}</p>
        <div class="caps">${caps.map((c) => `<span>${esc(c)}</span>`).join("")}</div>
        <div class="owner">由 ${esc(d.owner_name || "成员")} 分享 · ${esc(expire)} · 已查看 ${Number(d.view_count) || 1} 次</div>
      </div>
      <div class="section-title"><b>包含的快捷按钮</b><span>导入后自动填进输入框</span></div>
      <div class="quick-list">${quick.map((q) => `
        <div class="quick">
          <b>${esc(q.label || "快捷按钮")}</b>
          <small>${esc(q.text || "")}</small>
          ${fmt(q.format) ? `<em>${esc(fmt(q.format))}</em>` : ""}
        </div>`).join("") || `<div class="quick"><b>暂无快捷按钮</b><small>这个工作台只有名称和说明。</small></div>`}
      </div>
      <div class="actions">
        <button class="primary" type="button" id="importBtn">导入到我的工作台</button>
        <a class="ghost" href="/">先看看我的工作台</a>
      </div>
      <div class="notice">导入后会作为你自己的自定义工作台保存，不影响分享者的版本；快捷按钮只会填入输入框，不会自动创建定时任务。</div>`;
    document.getElementById("importBtn").addEventListener("click", (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = "正在打开…";
      try {
        localStorage.setItem("wb_shared_import", JSON.stringify({
          name: d.name, icon: d.icon || "🧩", description: d.description || "",
          quick: quick, source: d.owner_name || "",
          skills: Array.isArray(d.skills) ? d.skills : [],
          skill_id: d.skill_id || "", plugins: Array.isArray(d.plugins) ? d.plugins : [],
        }));
        toast("已准备好，正在打开工作台…");
        setTimeout(() => { location.href = "/"; }, 900);
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "导入到我的工作台";
        toast("浏览器没有允许保存，请检查隐私设置");
      }
    });
  }
  load();
})();
