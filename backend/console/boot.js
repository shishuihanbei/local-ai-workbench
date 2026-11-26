/* 控制台 · 启动引导（必须最后加载） | 原 console.js 第 1405–1424 行 */
(async function boot() {
  try {
    const st = await (await fetch("/api/auth/state")).json();
    S.branding = st.branding || S.branding;
    applyBranding(S.branding, "");
    if (!st.initialized) { showLogin(true); return; }
  } catch {}
  if (!token()) { showLogin(); return; }
  try {
    const me = await api("/api/auth/me");
    applyAdminPermissions(me.user);
    applyBranding(S.branding, me.user.username);
    showMain();
    try {
      const la = await api("/api/system/local-access");
      S.localClient = !!la.local;
    } catch { S.localClient = true; }
    await switchTab(initialTab());
  } catch { showLogin(); }
})();
