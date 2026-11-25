const token = location.pathname.split("/").filter(Boolean).pop();
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
async function load() {
  try {
    const res = await fetch(`/api/shares/${encodeURIComponent(token)}`, { credentials: "same-origin" });
    if (!res.ok) throw new Error(res.status === 404 ? "分享不存在、已失效，或你没有查看这个小队分享的权限。" : "读取分享失败");
    const d = await res.json();
    document.title = `${d.title || "对话分享"} · 本地 AI 工作台`;
    document.getElementById("title").textContent = d.title || "对话分享";
    const time = d.created_at ? new Date(d.created_at * 1000).toLocaleString("zh-CN") : "";
    document.getElementById("meta").textContent = `${d.owner_name || "成员"} 分享 · ${time} · ${d.messages.length} 条消息${d.expires_at ? " · 有效期至 " + new Date(d.expires_at * 1000).toLocaleString("zh-CN") : ""}`;
    const box = document.getElementById("messages");
    box.innerHTML = d.messages.length ? d.messages.map((m) => `<div class="msg"><b>${m.role === "assistant" ? "助手" : "成员"}</b>${esc(m.content)}</div>`).join("") : `<div class="empty">这段分享没有可显示的消息</div>`;
  } catch (e) {
    document.getElementById("messages").innerHTML = `<div class="error"><b>无法查看这段分享</b>${esc(e.message)}</div>`;
    document.getElementById("meta").textContent = "链接可能已经过期或被撤销";
  }
}
load();
