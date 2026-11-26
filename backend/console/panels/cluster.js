/* 控制台 · 多机算力池、自定义技能 | 原 console.js 第 6903–7225 行 */
/* ---------------------------------------------------------------- 多机算力池 */
function clusterStatusBadge(status) {
  const m = { online: ["good", "在线"], offline: ["bad", "离线"], unknown: ["unknown", "未检查"] };
  const v = m[status] || m.unknown;
  return `<span class="badge ${v[0]}">${v[1]}</span>`;
}

function clusterStrategyLabel(key) {
  return key === "round_robin" ? "轮询" : "加权最少连接";
}

function clusterDefaultMember() {
  const nodes = (S.cluster && S.cluster.nodes) || [];
  const node = nodes.find((n) => n.enabled) || nodes[0];
  if (!node) return { node_id: 0, remote_model: "", weight: 1 };
  return { node_id: node.id, remote_model: (node.models || [])[0] || "", weight: 1 };
}

function renderClusterCards(stats) {
  const box = $("clusterCards");
  if (!box) return;
  const cards = [
    ["节点", String(stats.nodes || 0) + " 台", `${stats.online || 0} 台在线`],
    ["当前并发", String(stats.active || 0), "正在处理的请求"],
    ["模型池", String(stats.pools || 0), "对外统一模型名"],
    ["入口", "/v1", "OpenAI 兼容"],
  ];
  box.innerHTML = cards.map(([k, v, s]) =>
    `<div class="card"><div class="k">${esc(k)}</div><div class="v" style="font-size:20px">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
}

function renderClusterNodes(nodes) {
  const box = $("clusterNodeRows");
  if (!box) return;
  if (!nodes.length) {
    box.innerHTML = `<tr><td colspan="6" class="cluster-empty">还没有节点。先在右边填写一台机器的 /v1 地址。</td></tr>`;
    $("clusterNodeHint").textContent = "还没有节点。先在右边填写一台局域网机器的地址，保存后会自动探测一次。";
    return;
  }
  $("clusterNodeHint").textContent = `共 ${nodes.length} 台，${nodes.filter((n) => n.status === "online").length} 台在线。状态每 30 秒自动检查一次。`;
  box.innerHTML = nodes.map((n) => {
    const models = n.models || [];
    const badges = models.slice(0, 3).map((m) => `<span class="badge cat" title="${esc(m)}">${esc(m)}</span>`).join("")
      + (models.length > 3 ? `<span class="badge unknown">+${models.length - 3}</span>` : "");
    return `<tr class="${n.status === "offline" ? "cluster-offline" : ""}">
      <td><div class="node-name">${esc(n.name)}</div>${n.note ? `<div class="hint">${esc(n.note)}</div>` : ""}</td>
      <td><span class="mono" style="font-size:12px">${esc(n.base_url)}</span><div class="hint">${n.has_key ? "已配 Key" : "无 Key"}</div></td>
      <td>${clusterStatusBadge(n.status)}<div class="hint">${n.latency_ms ? n.latency_ms + " ms" : ""}${n.last_error ? `<br>${esc(n.last_error)}` : ""}</div></td>
      <td><div class="node-models">${badges || `<span class="hint">未读取到模型</span>`}</div></td>
      <td><span class="badge ok">w ${n.weight}</span> <span class="badge unknown">${n.active}/${n.max_concurrency}</span></td>
      <td><div class="row-actions">
        <button class="btn small" data-cluster-node-test="${n.id}">测试</button>
        <button class="btn small" data-cluster-node-edit="${n.id}">编辑</button>
        <button class="btn small danger" data-cluster-node-del="${n.id}">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

function renderClusterPools(pools) {
  const box = $("clusterPoolRows");
  if (!box) return;
  if (!pools.length) {
    box.innerHTML = `<tr><td colspan="6" class="cluster-empty">还没有模型池。把几台机器加进同一个池，就能用一个名字调用。</td></tr>`;
    $("clusterPoolHint").textContent = "还没有模型池。先在下面把几台机器加进同一个池，再用池名调用。";
    return;
  }
  $("clusterPoolHint").textContent = `${pools.length} 个池。池内机器必须跑同一个模型；池名会出现在 /v1/models 里。`;
  box.innerHTML = pools.map((p) => {
    const members = p.members || [];
    const mHtml = members.slice(0, 4).map((m) =>
      `<span class="badge ${m.enabled ? "cat" : "off"}" title="${esc(m.node_name)}">${esc(m.node_name)} · ${esc(m.remote_model)}</span>`).join(" ")
      + (members.length > 4 ? ` <span class="badge unknown">+${members.length - 4}</span>` : "");
    return `<tr>
      <td><div class="node-name">${esc(p.name)}</div>${p.note ? `<div class="hint">${esc(p.note)}</div>` : ""}</td>
      <td>${esc(clusterStrategyLabel(p.strategy))}</td>
      <td><div class="node-models">${mHtml || `<span class="hint">没有成员</span>`}</div></td>
      <td>${esc(p.timeout)} 秒 / ${esc(p.retries)} 次</td>
      <td>${p.enabled ? `<span class="badge good">启用</span>` : `<span class="badge off">停用</span>`}</td>
      <td><div class="row-actions">
        <button class="btn small" data-cluster-pool-edit="${p.id}">编辑</button>
        <button class="btn small danger" data-cluster-pool-del="${p.id}">删除</button>
      </div></td>
    </tr>`;
  }).join("");
}

function renderClusterDistribution(nodes) {
  const box = $("clusterDistribution");
  if (!box) return;
  if (!nodes.length) { box.innerHTML = `<p class="hint">添加节点后，这里会显示当前并发分布。</p>`; return; }
  box.innerHTML = nodes.map((n) => {
    const pct = Math.min(100, Math.round((n.active / Math.max(1, n.max_concurrency)) * 100));
    return `<div class="cluster-dist-item">
      <span style="min-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(n.name)}</span>
      <div class="bar"><span style="width:${pct}%"></span></div>
      <span class="num">${n.active}/${n.max_concurrency}</span>
    </div>`;
  }).join("");
}

function renderClusterEntry(pools) {
  const box = $("clusterExample");
  if (!box) return;
  const base = location.origin + "/v1";
  const model = (pools.find((p) => p.enabled) || {}).name || "你的池名";
  box.textContent = `POST ${base}/chat/completions
Authorization: Bearer <你的 API Key>
Content-Type: application/json

{
  "model": "${model}",
  "messages": [{"role": "user", "content": "你好"}],
  "stream": false
}`;
}

function renderClusterMembers() {
  const box = $("clusterPoolMembers");
  if (!box) return;
  const nodes = (S.cluster && S.cluster.nodes) || [];
  if (!nodes.length) {
    box.innerHTML = `<div class="cluster-member-empty">还没有节点。先在上方加入至少一台机器，再把它加进模型池。</div>`;
    return;
  }
  if (!S.clusterMembers.length) S.clusterMembers = [clusterDefaultMember()];
  box.innerHTML = S.clusterMembers.map((m, idx) => {
    const opts = nodes.map((n) => `<option value="${n.id}" ${Number(m.node_id) === n.id ? "selected" : ""}>${esc(n.name)}</option>`).join("");
    return `<div class="cluster-member-row" data-member-idx="${idx}">
      <select data-member-node>${opts}</select>
      <input data-member-model value="${esc(m.remote_model || "")}" placeholder="节点上的模型名" autocomplete="off">
      <input data-member-weight type="number" min="1" max="100" value="${Number(m.weight) || 1}" title="成员权重">
      <button type="button" class="member-del" data-member-del="${idx}" title="移除">×</button>
    </div>`;
  }).join("");
}

function resetClusterNodeForm() {
  S.clusterEditNode = 0;
  $("clusterNodeFormTitle").textContent = "加入一台机器";
  $("clusterNodeCancel").hidden = true;
  $("clusterNodeName").value = "";
  $("clusterNodeBase").value = "";
  $("clusterNodeKey").value = "";
  $("clusterNodeKey").placeholder = "API Key（本机服务通常留空）";
  $("clusterNodeWeight").value = "1";
  $("clusterNodeMax").value = "4";
  $("clusterNodeNote").value = "";
  $("clusterNodeEnabled").checked = true;
  $("clusterProbeResult").textContent = "";
}

function resetClusterPoolForm() {
  S.clusterEditPool = 0;
  $("clusterPoolFormTitle").textContent = "新建模型池";
  $("clusterPoolCancel").hidden = true;
  $("clusterPoolName").value = "";
  $("clusterPoolStrategy").value = "weighted_least";
  $("clusterPoolTimeout").value = "30";
  $("clusterPoolRetries").value = "1";
  $("clusterPoolNote").value = "";
  S.clusterMembers = [clusterDefaultMember()];
  renderClusterMembers();
}

async function loadClusterPage() {
  const d = await api("/api/admin/cluster");
  S.cluster = d;
  renderClusterCards(d.stats || {});
  renderClusterNodes(d.nodes || []);
  renderClusterPools(d.pools || []);
  renderClusterDistribution(d.nodes || []);
  renderClusterEntry(d.pools || []);
  if (!S.clusterMembersInit) {
    S.clusterMembersInit = true;
    S.clusterMembers = [clusterDefaultMember()];
  }
  renderClusterMembers();
}

async function clusterSaveNode() {
  const payload = {
    name: $("clusterNodeName").value.trim(),
    base_url: $("clusterNodeBase").value.trim(),
    api_key: $("clusterNodeKey").value.trim(),
    weight: Number($("clusterNodeWeight").value) || 1,
    max_concurrency: Number($("clusterNodeMax").value) || 4,
    note: $("clusterNodeNote").value.trim(),
    enabled: $("clusterNodeEnabled").checked,
  };
  if (!payload.name || !payload.base_url) throw new Error("机器名和地址不能为空");
  let node;
  if (S.clusterEditNode) {
    if (!payload.api_key) delete payload.api_key;
    const res = await api(`/api/admin/cluster/nodes/${S.clusterEditNode}`, { method: "PATCH", body: JSON.stringify(payload) });
    node = res.node;
    uiToast("节点已保存");
  } else {
    const res = await api("/api/admin/cluster/nodes", { method: "POST", body: JSON.stringify(payload) });
    node = res.node;
    uiToast("节点已加入，正在探测");
  }
  resetClusterNodeForm();
  await loadClusterPage();
  if (node && node.id) {
    api(`/api/admin/cluster/nodes/${node.id}/test`, { method: "POST" }).catch(() => {});
  }
}

async function clusterProbe() {
  const base = $("clusterNodeBase").value.trim();
  if (!base) throw new Error("先填节点地址");
  const res = await api("/api/admin/cluster/probe", {
    method: "POST",
    body: JSON.stringify({ base_url: base, api_key: $("clusterNodeKey").value.trim() }),
  });
  const box = $("clusterProbeResult");
  box.textContent = res.ok ? `连接成功 · ${res.latency_ms} ms · ${(res.models || []).length} 个模型` : `连接失败 · ${res.detail || ""}`;
  box.style.color = res.ok ? "#0f7b3f" : "#b03b3b";
}

async function clusterSavePool() {
  const name = $("clusterPoolName").value.trim();
  if (!name) throw new Error("统一模型名不能为空");
  const members = S.clusterMembers.filter((m) => Number(m.node_id) > 0 && String(m.remote_model || "").trim());
  if (!members.length) throw new Error("至少加一台成员机器，并填节点上的模型名");
  const payload = {
    name,
    strategy: $("clusterPoolStrategy").value,
    timeout: Number($("clusterPoolTimeout").value) || 30,
    retries: Number($("clusterPoolRetries").value) || 0,
    note: $("clusterPoolNote").value.trim(),
    members: members.map((m) => ({
      node_id: Number(m.node_id),
      remote_model: String(m.remote_model).trim(),
      weight: Number(m.weight) || 1,
    })),
  };
  if (S.clusterEditPool) {
    await api(`/api/admin/cluster/pools/${S.clusterEditPool}`, { method: "PATCH", body: JSON.stringify(payload) });
    uiToast("模型池已保存");
  } else {
    await api("/api/admin/cluster/pools", { method: "POST", body: JSON.stringify(payload) });
    uiToast("模型池已创建，池名已加入 /v1/models");
  }
  resetClusterPoolForm();
  await loadClusterPage();
}

function clusterFillNodeForm(node) {
  S.clusterEditNode = node.id;
  $("clusterNodeFormTitle").textContent = "编辑节点 · " + node.name;
  $("clusterNodeCancel").hidden = false;
  $("clusterNodeName").value = node.name || "";
  $("clusterNodeBase").value = node.base_url || "";
  $("clusterNodeKey").value = "";
  $("clusterNodeKey").placeholder = node.has_key ? `已保存 ${node.api_key_masked}，留空不改` : "API Key（本机服务通常留空）";
  $("clusterNodeWeight").value = String(node.weight || 1);
  $("clusterNodeMax").value = String(node.max_concurrency || 4);
  $("clusterNodeNote").value = node.note || "";
  $("clusterNodeEnabled").checked = !!node.enabled;
  $("clusterNodeFormPanel").scrollIntoView({ block: "start" });
}

function clusterFillPoolForm(pool) {
  S.clusterEditPool = pool.id;
  $("clusterPoolFormTitle").textContent = "编辑模型池 · " + pool.name;
  $("clusterPoolCancel").hidden = false;
  $("clusterPoolName").value = pool.name || "";
  $("clusterPoolStrategy").value = pool.strategy || "weighted_least";
  $("clusterPoolTimeout").value = String(pool.timeout || 30);
  $("clusterPoolRetries").value = String(pool.retries || 0);
  $("clusterPoolNote").value = pool.note || "";
  S.clusterMembers = (pool.members || []).map((m) => ({
    node_id: m.node_id, remote_model: m.remote_model, weight: m.weight || 1,
  }));
  renderClusterMembers();
  $("clusterPoolName").scrollIntoView({ block: "start" });
}


document.addEventListener("change", (ev) => {
  const row = ev.target.closest(".cluster-member-row");
  if (!row) return;
  const idx = Number(row.dataset.memberIdx);
  if (!S.clusterMembers[idx]) return;
  if (ev.target.matches("[data-member-node]")) {
    const nodeId = Number(ev.target.value);
    S.clusterMembers[idx].node_id = nodeId;
    const node = ((S.cluster && S.cluster.nodes) || []).find((n) => n.id === nodeId);
    const models = (node && node.models) || [];
    if (models.length && !models.includes(S.clusterMembers[idx].remote_model)) {
      S.clusterMembers[idx].remote_model = models[0];
      row.querySelector("[data-member-model]").value = models[0];
    }
  }
  if (ev.target.matches("[data-member-model]")) S.clusterMembers[idx].remote_model = ev.target.value.trim();
  if (ev.target.matches("[data-member-weight]")) S.clusterMembers[idx].weight = Number(ev.target.value) || 1;
});

document.addEventListener("input", (ev) => {
  const row = ev.target.closest(".cluster-member-row");
  if (!row) return;
  const idx = Number(row.dataset.memberIdx);
  if (!S.clusterMembers[idx]) return;
  if (ev.target.matches("[data-member-model]")) S.clusterMembers[idx].remote_model = ev.target.value;
  if (ev.target.matches("[data-member-weight]")) S.clusterMembers[idx].weight = Number(ev.target.value) || 1;
});

/* ---------------------------------------------------------------- 自定义技能 */
S.skillAdmin = null;
S.skillEdit = 0;
S.skillIcons = ["spark", "list", "translate", "edit", "code", "file", "plan"];
const SKILL_ICON_LABELS = { spark: "通用", list: "清单 / 总结", translate: "翻译", edit: "改写", code: "代码", file: "文件", plan: "规划" };

function fillSkillIconSelect() {
  const sel = $("esIcon");
  if (!sel) return;
  const current = sel.value || "spark";
  sel.innerHTML = S.skillIcons.map((k) => `<option value="${esc(k)}">${esc(SKILL_ICON_LABELS[k] || k)}</option>`).join("");
  sel.value = S.skillIcons.includes(current) ? current : "spark";
}

