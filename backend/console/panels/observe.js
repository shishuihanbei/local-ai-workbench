/* 控制台 · 概览、调用记录、供应商、路由 | 原 console.js 第 2682–2956 行 */
/* ---------------------------------------------------------------- 概览 */
async function loadOverview() {
  const d = await api("/api/admin/overview?days=1");
  const perCall = d.count ? Math.round(d.tokens / d.count) : 0;
  const cards = [
    ["调用次数", fmtInt(d.count), `本地 ${fmtInt(d.local_calls)} · 云端 ${fmtInt(d.cloud_calls)}`],
    ["Token", fmtInt(d.tokens), `单次均 ${fmtInt(perCall)}`],
    ["成本", fmtCost(d.cost), "按供应商单价折算"],
    ["错误率", (d.error_rate || 0) + "%", `${fmtInt(d.errors)} 次失败`],
    ["首字 P50 / P95", fmtMs(d.p50_ttft) + " / " + fmtMs(d.p95_ttft), "TTFT，越小越好"],
    ["总耗时 P50 / P95", fmtMs(d.p50_total) + " / " + fmtMs(d.p95_total), "含排队与推理"],
    ["缓存命中", fmtInt(d.cache_hits), "M4 预留"],
  ];
  $("statCards").innerHTML = cards.map(([k, v, s]) =>
    `<div class="card"><div class="k">${esc(k)}</div><div class="v" style="font-size:20px">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");

  const total = d.series.reduce((a, x) => a + (x.c || 0), 0);
  $("seriesHint").textContent = `最近 24 小时 · ${fmtInt(total)} 次调用`;
  if (!d.series.length) {
    $("chart").innerHTML = `<div class="chart-empty">还没有调用数据，先去对话页发一条消息</div>`;
  } else {
    const max = Math.max(...d.series.map((x) => x.c || 0), 1);
    $("chart").innerHTML = d.series.map((x) => {
      const dt = new Date((x.t || Date.now() / 1000) * 1000);
      const hh = String(dt.getHours()).padStart(2, "0") + ":00";
      const pct = Math.max(3, Math.round((x.c / max) * 100));
      return `<div class="col" title="${esc(fmtInt(x.c))} 次 · ${esc(fmtInt(x.tk))} token">
        <div class="bar2" style="height:${pct}%"></div><div class="lbl">${hh}</div></div>`;
    }).join("");
  }

  $("usageRows").innerHTML = d.models.length ? d.models.map((m) => `<tr>
      <td>${esc(m.model || "—")}</td><td>${fmtInt(m.c)}</td><td>${fmtInt(m.tk)}</td>
      <td>${fmtCost(m.cost)}</td><td>${fmtMs(m.ttft)}</td></tr>`).join("")
    : `<tr><td colspan="5" style="color:var(--muted)">暂无数据</td></tr>`;
}

/* ---------------------------------------------------------------- 调用记录 */
async function loadRequests() {
  const q = new URLSearchParams({ page: S.reqPage, size: 20 });
  if ($("fq").value.trim()) q.set("q", $("fq").value.trim());
  if ($("fmodel").value.trim()) q.set("model", $("fmodel").value.trim());
  if ($("fstatus").value) q.set("status", $("fstatus").value);
  if ($("fprovider").value) q.set("provider", $("fprovider").value);
  const d = await api("/api/admin/requests?" + q.toString());
  S.reqTotal = d.total;
  $("reqHint").textContent = `共 ${fmtInt(d.total)} 条 · 第 ${d.page} 页`;
  $("pageInfo").textContent = `${d.page} / ${Math.max(1, Math.ceil(d.total / d.size))}`;
  $("reqRows").innerHTML = d.items.length ? d.items.map((r) => `<tr data-rid="${r.id}" style="cursor:pointer">
      <td class="mono" style="font-size:12px">${esc(fmtTime(r.created_at))}</td>
      <td>${r.user_id ? `<div class="name">${esc(r.username || "已删除用户")}</div><div class="sub mono">#${esc(r.user_id)}</div>` : "—"}</td>
      <td class="req-conv">${r.conversation_id ? `<div class="req-conv-title" title="${esc(r.conversation_title || '未命名对话')}">${esc(r.conversation_title || "未命名对话")}</div><div class="sub mono">#${esc(r.conversation_id)}</div>` : "—"}</td>
      <td><div class="name">${esc(r.model || "—")}</div><div class="sub mono">${esc(r.trace_id || "")}</div></td>
      <td><span class="src ${esc(r.provider || "")}">${esc(r.provider || "—")}</span></td>
      <td>${fmtInt(r.total_tokens)}${r.tokens_estimated ? `<div class="sub">估算</div>` : ""}</td>
      <td>${fmtMs(r.ttft_ms)}</td><td>${fmtMs(r.total_ms)}</td><td>${fmtCost(r.cost)}</td>
      <td class="status-${esc(r.status)}">${esc(r.status)}${r.error ? `<div class="sub" title="${esc(r.error)}">${esc(r.error.slice(0, 24))}</div>` : ""}</td>
    </tr>`).join("")
    : `<tr><td colspan="10" style="color:var(--muted)">没有匹配的记录</td></tr>`;
}

async function loadRequestDetail(rid) {
  const d = await api("/api/admin/requests/" + rid);
  const r = d.request;
  $("reqDetail").hidden = false;
  $("detailHint").textContent = "trace " + (r.trace_id || "");
  const kv = [
    ["状态", r.status], ["模型", r.model], ["来源", r.provider + (r.provider_id ? " #" + r.provider_id : "")],
    ["Prompt Token", fmtInt(r.prompt_tokens)], ["Completion Token", fmtInt(r.completion_tokens)],
    ["总 Token", fmtInt(r.total_tokens) + (r.tokens_estimated ? "（估算）" : "")],
    ["成本", fmtCost(r.cost) + `（$${r.price_in}/$${r.price_out} 每百万）`],
    ["首字", fmtMs(r.ttft_ms)], ["总耗时", fmtMs(r.total_ms)], ["排队", fmtMs(r.queue_ms)],
    ["用户", r.user_id ? `${r.username || "已删除用户"} · #${r.user_id}` : "—"],
    ["会话", r.conversation_id ? `#${r.conversation_id} · ${r.conversation_title || "未命名对话"}` : "—"], ["Prompt 版本", r.prompt_version || "—"],
    ["Prompt Hash", r.prompt_hash || "—"], ["路由决策", r.decision_json || "—"],
    ["参数", r.params_json || "—"], ["错误", r.error || "—"],
  ];
  const spans = d.spans.map((s) => `<span class="badge off">${esc(s.kind)} · ${esc(s.name || "")} ${fmtMs(s.dur_ms)}</span>`).join(" ");
  $("detailBody").innerHTML = kv.map(([k, v]) => `<div class="kv"><b>${esc(k)}</b><span>${esc(String(v ?? "—"))}</span></div>`).join("")
    + `<div class="kv" style="grid-column:1/-1"><b>Span</b><span>${spans || "—"}</span></div>`
    + `<pre>${esc(r.prompt_rendered || "（未记录 prompt）")}</pre>`;
  $("reqDetail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------------------------------------------------------------- 供应商 */
const PROVIDER_PRESETS = [
  { key: "deepseek", label: "DeepSeek", name: "deepseek", base: "https://api.deepseek.com/v1",
    models: "deepseek-chat,deepseek-reasoner", note: "DeepSeek 官方 API，Key 在 platform.deepseek.com 创建。" },
  { key: "dashscope", label: "阿里云百炼 / 通义千问", name: "dashscope", base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: "qwen-plus,qwen-max,qwen-turbo", note: "使用百炼的 OpenAI 兼容模式，Key 在阿里云百炼控制台创建。" },
  { key: "moonshot", label: "月之暗面 Kimi", name: "moonshot", base: "https://api.moonshot.cn/v1",
    models: "moonshot-v1-8k,moonshot-v1-32k,moonshot-v1-128k", note: "Kimi 官方 OpenAI 兼容接口。" },
  { key: "zhipu", label: "智谱 GLM", name: "zhipu", base: "https://open.bigmodel.cn/api/paas/v4",
    models: "glm-4-plus,glm-4-flash,glm-4-air", note: "智谱开放平台的 OpenAI 兼容接口。" },
  { key: "ark", label: "火山方舟 / 豆包", name: "ark", base: "https://ark.cn-beijing.volces.com/api/v3",
    models: "", note: "模型列表要填火山方舟的推理接入点 ID（ep-...），不是模型展示名。" },
  { key: "qianfan", label: "百度千帆 / 文心", name: "qianfan", base: "https://qianfan.baidubce.com/v2",
    models: "ernie-4.0-8k-latest,ernie-speed-128k", note: "使用千帆 v2 的 OpenAI 兼容接口。" },
  { key: "hunyuan", label: "腾讯混元", name: "hunyuan", base: "https://api.hunyuan.cloud.tencent.com/v1",
    models: "hunyuan-turbos-latest", note: "混元 OpenAI 兼容接口，模型名以控制台为准。" },
  { key: "siliconflow", label: "硅基流动 SiliconFlow", name: "siliconflow", base: "https://api.siliconflow.cn/v1",
    models: "deepseek-ai/DeepSeek-V3,Qwen/Qwen2.5-72B-Instruct", note: "聚合平台，模型名可直接从模型广场复制。" },
  { key: "openai", label: "OpenAI", name: "openai", base: "https://api.openai.com/v1",
    models: "gpt-4o-mini,gpt-4o", note: "OpenAI 官方接口。" },
  { key: "openrouter", label: "OpenRouter", name: "openrouter", base: "https://openrouter.ai/api/v1",
    models: "deepseek/deepseek-chat,openai/gpt-4o-mini", note: "聚合很多模型，模型名带供应商前缀。" },
  { key: "groq", label: "Groq", name: "groq", base: "https://api.groq.com/openai/v1",
    models: "llama-3.3-70b-versatile", note: "Groq 的 OpenAI 兼容接口，速度快。" },
  { key: "together", label: "Together AI", name: "together", base: "https://api.together.xyz/v1",
    models: "meta-llama/Llama-3.3-70B-Instruct-Turbo", note: "Together 的 OpenAI 兼容接口。" },
  { key: "mistral", label: "Mistral AI", name: "mistral", base: "https://api.mistral.ai/v1",
    models: "mistral-large-latest,mistral-small-latest", note: "Mistral 官方接口。" },
  { key: "ollama", label: "Ollama 本地", name: "ollama", base: "http://127.0.0.1:11434/v1",
    models: "qwen2.5:7b,llama3.1:8b", note: "本机 Ollama 的 OpenAI 兼容入口，API Key 可留空。" },
  { key: "vllm", label: "vLLM 本地", name: "vllm", base: "http://127.0.0.1:8000/v1",
    models: "", note: "vLLM 启动后默认提供 OpenAI 兼容接口，模型名填启动参数里的模型。" },
  { key: "lmstudio", label: "LM Studio 本地", name: "lmstudio", base: "http://127.0.0.1:1234/v1",
    models: "", note: "LM Studio 开启本地服务后使用，API Key 可留空。" },
  { key: "custom", label: "自定义 / 其他 OpenAI 兼容接口", name: "", base: "", models: "",
    note: "自己填写名称、Base URL 和模型；只要对方提供 OpenAI 兼容的 /v1 接口即可。" },
];

function renderProviderPresets() {
  const sel = $("pvPreset");
  if (!sel || sel.dataset.ready) return;
  sel.innerHTML = `<option value="">选择常见供应商（可修改）</option>` + PROVIDER_PRESETS.map((p) =>
    `<option value="${esc(p.key)}">${esc(p.label)}</option>`).join("");
  sel.dataset.ready = "1";
}

function applyProviderPreset(key) {
  const preset = PROVIDER_PRESETS.find((p) => p.key === key);
  const note = $("pvPresetNote");
  if (!preset) {
    if (note) note.textContent = "选择常见供应商会自动填入地址和模型，所有字段仍可修改；不在列表里就选最后一项“自定义”。";
    return;
  }
  $("pvName").value = preset.name;
  $("pvBase").value = preset.base;
  $("pvModels").value = preset.models;
  $("pvIn").value = "";
  $("pvOut").value = "";
  $("pvModels").placeholder = preset.key === "ark" ? "推理接入点 ID，如 ep-2024..." : "模型列表，逗号分隔";
  if (note) note.textContent = preset.note;
}

async function loadProviders() {
  renderProviderPresets();
  const d = await api("/api/admin/providers");
  S.providers = d.items;
  $("providerRows").innerHTML = d.items.length ? d.items.map((p) => `<tr>
      <td><div class="name">${esc(p.name)}</div><div class="sub">${esc(p.note || p.kind)}</div></td>
      <td>${esc(p.kind)}</td><td class="mono" style="font-size:12px">${esc(p.base_url)}</td>
      <td class="mono">${esc(p.api_key_masked || "—")}</td>
      <td>$${Number(p.price_in || 0).toFixed(2)} / $${Number(p.price_out || 0).toFixed(2)}</td>
      <td>${p.enabled ? `<span class="badge good">启用</span>` : `<span class="badge off">停用</span>`}</td>
      <td class="right"><div class="row-actions">
        <button class="btn small" data-ptest="${p.id}">测试</button>
        <button class="btn small" data-pdel="${p.id}">删除</button>
      </div></td></tr>`).join("")
    : `<tr><td colspan="7" style="color:var(--muted)">还没有接入第三方供应商，默认走本地模型</td></tr>`;
}

async function testProvider(id) {
  const r = await api(`/api/admin/providers/${id}/test`, { method: "POST" });
  uiToast(r.ok ? `连通，${r.ms}ms，发现 ${r.models.length} 个模型` : `失败 ${r.status}：${r.detail || "无法连接"}`);
}

/* ---------------------------------------------------------------- 路由 */
const ROUTE_FAMILIES = ["deepseek", "qwen", "llama", "mistral", "mixtral", "gemma", "phi", "glm", "yi", "command", "gpt"];

function routeProviderName(providerId, strategy) {
  if (!providerId) return strategy === "cloud_first" ? "云端自动（未绑定）" : "本地 / 不绑定";
  const p = (S.routeProviders || []).find((x) => Number(x.id) === Number(providerId));
  return p ? p.name : `#${providerId}`;
}

function routeCloudModels(provider) {
  return String(provider && provider.models || "")
    .split(",").map((x) => x.trim()).filter(Boolean);
}

function renderRouteProviderOptions() {
  const select = $("rtProvider");
  if (!select) return;
  const current = select.value || "local";
  const locals = S.routeModels || [];
  const providers = S.routeProviders || [];
  const localText = locals.length ? ` · ${locals.length} 个文字/代码模型` : "";
  let html = `<optgroup label="本地">`;
  html += `<option value="local">本地部署（llama.cpp）${esc(localText)}</option></optgroup>`;
  if (providers.length) {
    html += `<optgroup label="云端供应商">`;
    for (const p of providers) {
      const models = routeCloudModels(p);
      const suffix = models.length ? ` · ${models.length} 个模型` : " · 未填模型";
      html += `<option value="${p.id}">${esc(p.name)}${esc(suffix)}</option>`;
    }
    html += `</optgroup>`;
  } else {
    html += `<optgroup label="云端供应商"><option value="" disabled>还没有接入云端供应商</option></optgroup>`;
  }
  select.innerHTML = html;
  const exists = [...select.options].some((o) => o.value === current);
  select.value = exists ? current : "local";
}

async function loadRouteOptions() {
  try {
    const [models, providers] = await Promise.all([api("/api/models"), api("/api/admin/providers")]);
    const items = models.items || [];
    S.routeModels = items.filter((m) => m.installable && ["text", "code"].includes(m.category || "text"));
    S.routeLocalEnabled = models.local_enabled !== false;
    S.routeProviders = providers.items || [];
    renderRouteProviderOptions();
    const localNote = `${S.routeModels.length} 个文字/代码模型${S.routeLocalEnabled ? "" : "（本地部署当前关闭）"}`;
    const cloudNote = S.routeProviders.length ? `${S.routeProviders.length} 个云端供应商` : "还没有云端供应商";
    $("rtMapHint").className = "hint form-note";
    $("rtMapHint").textContent = `可用：本地 ${localNote} · 云端 ${cloudNote}。选云端供应商后点“自动匹配”，也可以手动填 JSON。`;
  } catch (e) {
    $("rtMapHint").className = "hint form-note warn";
    $("rtMapHint").textContent = "读取供应商失败：" + e.message;
  }
}

function autoRouteMap() {
  const pid = Number($("rtProvider").value || 0);
  if (!pid) throw new Error("先选择一个云端供应商；本地部署不需要模型映射");
  const provider = (S.routeProviders || []).find((p) => Number(p.id) === pid);
  if (!provider) throw new Error("供应商不存在，请刷新路由页");
  const cloudModels = routeCloudModels(provider);
  if (!cloudModels.length) throw new Error("这个供应商还没有填模型列表，请先到供应商页补齐");

  const mapping = {};
  const unmatched = [];
  for (const m of S.routeModels || []) {
    const key = String(m.key || "").trim();
    if (!key) continue;
    const identity = `${m.label || ""} ${m.family || ""} ${m.key || ""} ${m.alias || ""}`.toLowerCase();
    let target = cloudModels.find((cm) => cm.toLowerCase() === key.toLowerCase());
    if (!target) {
      const family = ROUTE_FAMILIES.find((f) => identity.includes(f));
      if (family) target = cloudModels.find((cm) => cm.toLowerCase().includes(family));
    }
    // 供应商只有一个模型时，用它兜底最稳，避免映射空着无法切换。
    if (!target && cloudModels.length === 1) target = cloudModels[0];
    if (target) mapping[key] = target;
    else unmatched.push(m.label || key);
  }

  const count = Object.keys(mapping).length;
  $("rtMap").value = count ? JSON.stringify(mapping) : "";
  $("rtMapHint").className = "hint form-note " + (count ? "ok" : "warn");
  if (!count) {
    $("rtMapHint").textContent = `没有找到与 ${provider.name} 同族的模型。请手动填，例如 {"7b":"${esc(cloudModels[0])}"}。`;
    return;
  }
  const tail = unmatched.length ? `；${unmatched.length} 个没有同族云端模型，可手动补` : "";
  const names = unmatched.slice(0, 3).join("、");
  $("rtMapHint").textContent = `已匹配 ${count} 个本地模型 → ${provider.name}${tail}${names ? `（${names}）` : ""}。`;
}

async function loadRoutes() {
  await loadRouteOptions();
  const d = await api("/api/admin/routes");
  $("routeRows").innerHTML = d.items.length ? d.items.map((r) => `<tr>
      <td><div class="name">${esc(r.name)}</div><div class="sub">${esc(r.note || "")}</div></td>
      <td><span class="badge ok">${esc(r.strategy)}</span></td>
      <td><span class="badge ${r.provider_id ? "good" : "off"}">${esc(routeProviderName(r.provider_id, r.strategy))}</span></td>
      <td class="mono" style="font-size:12px">${esc(r.model_map || "{}")}</td>
      <td>${r.enabled ? `<span class="badge good">启用</span>` : `<span class="badge off">停用</span>`}</td>
      <td class="right"><button class="btn small" data-rdel="${r.id}">删除</button></td></tr>`).join("")
    : `<tr><td colspan="6" style="color:var(--muted)">还没有路由策略，当前默认 local_first</td></tr>`;
}

