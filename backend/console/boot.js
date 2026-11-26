/* 控制台 · 启动引导（必须最后加载） | 原 console.js 第 1405–1424 行 */
(async function boot() {
  let st = null;
  try {
    st = await (await fetch("/api/auth/state", { credentials: "same-origin" })).json();
    S.branding = st.branding || S.branding;
    applyBranding(S.branding, "");
    if (!st.initialized) { showLogin(true); return; }
  } catch {}
  // 控制台与用户端同源：先看 /api/auth/state 里有没有 cookie 会话，
  // 有就直接认身份进后台，不会再弹一次登录；旧版只有 Bearer 令牌的浏览器仍可用令牌。
  const hasCookie = !!(st && st.user);
  if (!hasCookie && !token()) { showLogin(); return; }
  try {
    const me = await api("/api/auth/me");
    if (!me || !me.user) throw new Error("未登录");
    if (me.user.role !== "admin") {
      S.cookieSession = false;
      showLogin();
      $("alert").textContent = `当前账号「${me.user.username}」不是管理员，请用管理员账号登录`;
      return;
    }
    S.cookieSession = hasCookie;
    applyAdminPermissions(me.user);
    applyBranding(S.branding, me.user.username);
    showMain();
    try {
      const la = await api("/api/system/local-access");
      S.localClient = !!la.local;
    } catch { S.localClient = true; }
    await switchTab(initialTab());
  } catch { S.cookieSession = false; showLogin(); }
})();
