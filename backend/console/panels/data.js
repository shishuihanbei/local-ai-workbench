/* 控制台 · 数据库中心、表管理、SQL 控制台、连接、备份与迁移 | 原 console.js 第 5137–6902 行 */
/* ---------------------------------------------------------------- 事件（管理页） */
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && document.body.classList.contains("nav-open")) {
    closeNav();
    return;
  }
  if (ev.key === "Enter" && ev.target.id === "navSearch") {
    const first = [...document.querySelectorAll("#tabs .tab")].find((btn) => !btn.hidden && !btn.classList.contains("nav-away"));
    if (first) {
      ev.preventDefault();
      first.click();
    }
  }
});

["navToggle", "navClose", "navScrim"].forEach((id) => {
  const el = $(id);
  if (!el) return;
  el.addEventListener("click", () => {
    if (id === "navToggle") {
      if (document.body.classList.contains("nav-open")) closeNav();
      else openNav();
    } else {
      closeNav();
    }
  });
});

bindShortcutModeEvents();

if ($("navSearch")) {
  $("navSearch").addEventListener("input", filterNav);
  $("navSearch").addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      $("navSearch").value = "";
      filterNav();
    }
  });
}

window.addEventListener("resize", () => {
  if (!window.matchMedia("(max-width: 980px)").matches) closeNav();
});

if ($("pageGuideBtn")) {
  $("pageGuideBtn").addEventListener("click", openPageGuide);
}
if ($("guideModalClose")) {
  $("guideModalClose").addEventListener("click", () => closePageGuide());
}
if ($("guideModalOk")) {
  $("guideModalOk").addEventListener("click", () => closePageGuide());
}
if ($("guideModal")) {
  $("guideModal").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-guide-close]")) closePageGuide();
  });
}
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && $("guideModal") && !$("guideModal").hidden) {
    ev.preventDefault();
    ev.stopImmediatePropagation();
    closePageGuide();
  }
}, true);

document.addEventListener("click", async (ev) => {
  const tabBtn = ev.target.closest(".tab");
  if (tabBtn) {
    const input = $("navSearch");
    if (input) { input.value = ""; filterNav(); }
    await switchTab(tabBtn.dataset.tab);
    return;
  }
  const row = ev.target.closest("tr[data-rid]");
  if (row) { await loadRequestDetail(row.dataset.rid); return; }
  const t = ev.target.closest("button");
  if (!t) return;
  try {
    if (t.id === "searchBtn") { S.reqPage = 1; await loadRequests(); }
    else if (t.id === "prevPage") { if (S.reqPage > 1) { S.reqPage--; await loadRequests(); } }
    else if (t.id === "nextPage") { if (S.reqPage * 20 < S.reqTotal) { S.reqPage++; await loadRequests(); } }
    else if (t.id === "frontendBtn" || t.id === "openFrontendPage") openFrontendPage();
    else if (t.id === "tunnelBtn") await switchTab("network");
    else if (t.id === "saveFrontendBtn") await saveFrontendUrl();
    else if (t.id === "tunnelStartBtn") await startTunnel();
    else if (t.id === "tunnelStopBtn") await stopTunnel();
    else if (t.id === "tunnelOpenBtn") openTunnelUrl();
    else if (t.id === "tunnelDownloadBtn") await downloadCloudflared();
    else if (t.id === "backupBtn") await downloadBackup();
    else if (t.id === "migrationBtn") await downloadMigration();
    else if (t.id === "openMigrationFolderBtn") await openMigrationFolder();
    else if (t.id === "downloadMigrationFileBtn") await downloadMigrationFile();
    else if (t.id === "confirmRestoreBtn") await confirmRestoreBackup();
    else if (t.id === "cancelRestoreBtn") cancelRestoreBackup();
    else if (t.id === "refreshBackups") await loadBackupPage();
    else if (t.id === "saveRetentionBtn") await saveFileRetention();
    else if (t.id === "runRetentionBtn") await runFileRetentionCleanup();
    else if (t.dataset.bbackup) await downloadExistingBackup(t.dataset.bbackup);
    else if (t.dataset.bdel) await deleteExistingBackup(t.dataset.bdel, t);
    else if (t.id === "restorePick") $("restoreFile").click();
    else if (t.id === "shareBtn") await downloadShare();
    else if (t.id === "openShareFolderBtn") await openShareFolder();
    else if (t.id === "downloadShareFileBtn") await downloadShareFile();
    else if (t.id === "refreshShares") await loadSharePage();
    else if (t.dataset.shareDownload) await downloadExistingShare(t.dataset.shareDownload);
    else if (t.dataset.shareDelete) await deleteExistingShare(t.dataset.shareDelete, t);
    else if (t.id === "kbRefresh") {
      try { await loadKbPage(); } catch (e) { $("kbDocHint").textContent = "刷新失败：" + e.message; }
    }
    else if (t.id === "kbVectorRefresh") {
      try { await refreshKbVector(); } catch (e) { $("kbVectorHint").textContent = "扫描失败：" + e.message; }
    }
    else if (t.id === "kbNewBtn") openKbEditor();
    else if (t.id === "kbCancel") $("kbEditor").hidden = true;
    else if (t.id === "kbSave") {
      try { await saveKbDocument(); } catch (e) { $("kbEditorHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "kbUploadBtn") $("kbFile").click();
    else if (t.id === "kbSearch") {
      try { await searchKb(); } catch (e) { $("kbResults").innerHTML = `<div class="kb-empty">检索失败：${esc(e.message)}</div>`; }
    }
    else if (t.id === "kbClear") {
      $("kbQuery").value = "";
      $("kbResults").innerHTML = `<div class="kb-empty">还没有检索。输入问题后点“检索”，这里会显示命中的片段。</div>`;
    }
    else if (t.id === "kbSaveSettings") {
      try { await saveKbSettings(); } catch (e) { $("kbSettingsHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "kbBackupBtn") await backupKb();
    else if (t.id === "kbRestorePick") $("kbRestoreFile").click();
    else if (t.id === "kbRestoreBtn") {
      try { await restoreKb(); } catch (e) { $("kbRestoreHint").textContent = "恢复失败：" + e.message; }
    }
    else if (t.dataset.kbview) {
      try { await viewKbDocument(t.dataset.kbview); } catch (e) { $("kbDocHint").textContent = "查看失败：" + e.message; }
    }
    else if (t.dataset.kbdel) {
      try { await deleteKbDocument(t.dataset.kbdel); } catch (e) { $("kbDocHint").textContent = "删除失败：" + e.message; }
    }
    else if (t.id === "kbDocClose") closeKbDocument();
    else if (t.id === "libRefresh") {
      try { await loadLibraryPage(); } catch (e) { $("libDocHint").textContent = "刷新失败：" + e.message; }
    }
    else if (t.id === "libNewBtn") openLibEditor();
    else if (t.id === "libCancel") $("libEditor").hidden = true;
    else if (t.id === "libSave") {
      try { await saveLibDocument(); } catch (e) { $("libEditorHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "libUploadBtn") $("libFile").click();
    else if (t.id === "libSaveSettings") {
      try { await saveLibSettings(); } catch (e) { $("libSettingsHint").textContent = "保存失败：" + e.message; }
    }
    else if (t.id === "libBackupBtn") await backupLib();
    else if (t.id === "libRestorePick") $("libRestoreFile").click();
    else if (t.id === "libRestoreBtn") {
      try { await restoreLib(); } catch (e) { $("libRestoreHint").textContent = "恢复失败：" + e.message; }
    }
    else if (t.dataset.libview) {
      try { await viewLibDocument(t.dataset.libview); } catch (e) { $("libDocHint").textContent = "查看失败：" + e.message; }
    }
    else if (t.dataset.liborg) {
      try { openLibOrganize(t.dataset.liborg); } catch (e) { $("libDocHint").textContent = "整理失败：" + e.message; }
    }
    else if (t.id === "libOrgSave") {
      try { await saveLibOrganize(); } catch (e) {
        $("libOrgError").textContent = "保存失败：" + e.message;
        $("libOrgError").hidden = false;
      }
    }
    else if (t.id === "libOrgCancel") closeLibOrganize();
    else if (t.dataset.libdel) {
      try { await deleteLibDocument(t.dataset.libdel); } catch (e) { $("libDocHint").textContent = "删除失败：" + e.message; }
    }
    else if (t.id === "libDocClose") closeLibDocument();
    else if (t.id === "memoryToggleBtn") {
      try { await toggleMemory(); } catch (e) { $("memoryHint").textContent = "切换失败：" + e.message; }
    }
    else if (t.id === "refreshMemory") {
      try { await loadMemoryPage(); } catch (e) { $("memoryAddHint").textContent = "刷新失败：" + e.message; }
    }
    else if (t.id === "memoryAdd") {
      try { await addMemory(); } catch (e) { $("memoryAddHint").textContent = "添加失败：" + e.message; }
    }
    else if (t.dataset.memorydel) {
      try { await deleteMemory(t.dataset.memorydel); } catch (e) { $("memoryAddHint").textContent = "删除失败：" + e.message; }
    }
    else if (t.id === "createApiKeyBtn") await createApiKey();
    else if (t.id === "apiNewKeyHide") {
      $("apiNewKey").hidden = true;
      $("apiNewKeyValue").value = "";
      $("apiNewKeyCopy").dataset.copy = "";
    }
    else if (t.dataset.arevoke) await revokeApiKey(t.dataset.arevoke);
    else if (t.dataset.goto) await switchTab(t.dataset.goto);
    else if (t.dataset.copy) {
      try { await navigator.clipboard.writeText(t.dataset.copy); t.textContent = "已复制"; setTimeout(() => (t.textContent = "复制"), 1200); }
      catch { uiToast(t.dataset.copy); }
    }
    else if (t.id === "newUserBtn") openUserEditor(null);
    else if (t.id === "cancelUserBtn") { $("userEditor").hidden = true; S.editingUser = null; }
    else if (t.id === "saveUserBtn") await saveUser();
    else if (t.id === "saveOrgBtn") await saveOrg();
    else if (t.id === "brandLogoUploadBtn") $("brandLogoFile").click();
    else if (t.id === "brandLogoRemoveBtn") await removeBrandLogo();
    else if (t.id === "saveModerationBtn") await saveModeration();
    else if (t.id === "addModWordBtn") await addModerationWord();
    else if (t.id === "bulkModWordsBtn") await bulkModerationWords();
    else if (t.id === "refreshModHitsBtn") await loadModerationPage();
    else if (t.id === "clearModHitsBtn") await clearModerationHits();
    else if (t.dataset.mtoggle) await toggleModerationWord(t.dataset.mtoggle);
    else if (t.dataset.mdel) await deleteModerationWord(t.dataset.mdel);
    else if (t.id === "importUsersBtn") {
      $("userImportPanel").hidden = false;
      renderImportGroupOptions();
      $("importResult").textContent = "";
      $("userImportPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    else if (t.id === "cancelImportBtn") { $("userImportPanel").hidden = true; }
    else if (t.id === "submitImportBtn") {
      const body = {
        text: $("userImportText").value,
        default_group_id: $("importGroup").value ? Number($("importGroup").value) : null,
        default_role: $("importRole").value,
        default_daily_token_limit: Number($("importDaily").value || 0),
        default_monthly_token_limit: Number($("importMonthly").value || 0),
      };
      if (!body.text.trim()) throw new Error("请先粘贴要导入的账号");
      const r = await api("/api/users/import", { method: "POST", body: JSON.stringify(body) });
      $("importResult").className = "hint";
      $("importResult").textContent = `导入完成：新建 ${r.created} 个，跳过已存在 ${r.skipped} 个` +
        (r.errors && r.errors.length ? `，失败 ${r.errors.length} 个（第 ${r.errors[0].line} 行：${r.errors[0].error}）` : "");
      await loadUsers();
    }
    else if (t.id === "exportUsersBtn") {
      const r = await fetch("/api/users/export", { headers: { Authorization: "Bearer " + token() } });
      if (!r.ok) throw new Error("导出失败");
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "workbench-users.csv";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }
    else if (t.id === "newGroupBtn") openGroupEditor(null);
    else if (t.id === "cancelGroupBtn") { $("groupEditor").hidden = true; S.editingGroup = null; }
    else if (t.id === "saveGroupBtn") await saveGroup();
    else if (t.dataset.gedit) {
      const g = (S.groups || []).find((x) => String(x.id) === String(t.dataset.gedit));
      if (g) openGroupEditor(g);
    }
    else if (t.dataset.gdel) {
      const g = (S.groups || []).find((x) => String(x.id) === String(t.dataset.gdel));
      if (!(await confirmInline(`删除用户组 ${g ? g.name : ""}？成员会改为未分组。`, "确认删除"))) return;
      await api("/api/users/groups/" + t.dataset.gdel, { method: "DELETE" });
      await loadUsers();
    }
    else if (t.id === "newRoleBtn") openRoleEditor(null);
    else if (t.id === "cancelRoleBtn") { $("roleEditor").hidden = true; S.editingRole = null; }
    else if (t.id === "saveRoleBtn") await saveRole();
    else if (t.dataset.redit) {
      const r = (S.roles || []).find((x) => String(x.id) === String(t.dataset.redit));
      if (r) openRoleEditor(r);
    }
    else if (t.dataset.rdel) {
      const r = (S.roles || []).find((x) => String(x.id) === String(t.dataset.rdel));
      if (!(await confirmInline(`删除管理员角色 ${r ? r.name : ""}？`, "确认删除"))) return;
      await api("/api/users/roles/" + t.dataset.rdel, { method: "DELETE" });
      await loadUsers();
    }
    else if (t.dataset.uedit) {
      const u = S.users.find((x) => String(x.id) === String(t.dataset.uedit));
      if (u) openUserEditor(u);
    }
    else if (t.dataset.udel) {
      const u = S.users.find((x) => String(x.id) === String(t.dataset.udel));
      if (!(await confirmInline(`删除用户 ${u ? u.username : ""}？该用户的会话与记录会一并删除。`, "确认删除"))) return;
      await api("/api/users/" + t.dataset.udel, { method: "DELETE" });
      await loadUsers();
    }
    else if (t.id === "addProvider") {
      const body = {
        name: $("pvName").value.trim(), base_url: $("pvBase").value.trim(),
        api_key: $("pvKey").value.trim(), models: $("pvModels").value.trim(),
        price_in: Number($("pvIn").value || 0), price_out: Number($("pvOut").value || 0),
      };
      if (!body.name || !body.base_url) throw new Error("名称和 Base URL 必填");
      await api("/api/admin/providers", { method: "POST", body: JSON.stringify(body) });
      ["pvName", "pvBase", "pvKey", "pvModels", "pvIn", "pvOut"].forEach((k) => ($(k).value = ""));
      $("pvPreset").value = "";
      $("pvModels").placeholder = "模型列表，逗号分隔";
      $("pvPresetNote").textContent = "选择常见供应商会自动填入地址和模型，所有字段仍可修改；不在列表里就选最后一项“自定义”。";
      await loadProviders();
    }
    else if (t.dataset.authFill) {
      const card = t.closest(".auth-card");
      if (card) authFillDefaults(card);
    }
    else if (t.dataset.authTest) {
      const card = t.closest(".auth-card");
      const provider = t.dataset.authTest;
      const result = card ? card.querySelector("[data-auth-result]") : null;
      const target = card ? (card.querySelector(`[data-auth-target="${provider}"]`) || {}).value || "" : "";
      t.disabled = true;
      if (result) { result.className = "auth-result"; result.textContent = "正在测试…"; }
      try {
        const r = await api(`/api/admin/auth-providers/${provider}/test`, {
          method: "POST", body: JSON.stringify({ target }),
        });
        if (result) {
          result.className = "auth-result ok";
          result.innerHTML = esc(r.msg || "测试成功") +
            (r.authorize_url ? ` · <a href="${esc(r.authorize_url)}" target="_blank" rel="noreferrer">打开授权页</a>` : "");
        }
      } catch (e) {
        if (result) { result.className = "auth-result bad"; result.textContent = e.message; }
        else uiToast(e.message);
      } finally { t.disabled = false; }
    }
    else if (t.dataset.authSave) {
      const card = t.closest(".auth-card");
      if (!card) return;
      const provider = t.dataset.authSave;
      const result = card.querySelector("[data-auth-result]");
      t.disabled = true;
      if (result) { result.className = "auth-result"; result.textContent = "正在保存…"; }
      try {
        const r = await api(`/api/admin/auth-providers/${provider}`, {
          method: "PUT", body: JSON.stringify(authCollect(card)),
        });
        AUTH_ITEMS = AUTH_ITEMS.map((x) => x.key === provider ? r.item : x);
        await loadAuthProviders();
        const newCard = document.querySelector(`.auth-card[data-auth-card="${provider}"]`);
        const newResult = newCard ? newCard.querySelector("[data-auth-result]") : null;
        if (newResult) {
          newResult.className = "auth-result " + (r.item.ready ? "ok" : "bad");
          newResult.textContent = r.msg || "已保存";
        }
      } catch (e) {
        if (result) { result.className = "auth-result bad"; result.textContent = e.message; }
        else uiToast(e.message);
      } finally { t.disabled = false; }
    }
    else if (t.dataset.ptest) await testProvider(t.dataset.ptest);
    else if (t.dataset.pdel) {
      if (!(await confirmInline("删除该供应商？", "确认删除"))) return;
      await api("/api/admin/providers/" + t.dataset.pdel, { method: "DELETE" });
      await loadProviders();
    }
    else if (t.id === "rtAutoMap") {
      try { autoRouteMap(); } catch (e) {
        $("rtMapHint").className = "hint form-note warn";
        $("rtMapHint").textContent = "自动匹配失败：" + e.message;
      }
    }
    else if (t.id === "addRoute") {
      const providerValue = $("rtProvider").value;
      const body = {
        name: $("rtName").value.trim(), strategy: $("rtStrategy").value,
        provider_id: providerValue && providerValue !== "local" ? Number(providerValue) : null,
        model_map: $("rtMap").value.trim() || "{}",
      };
      if (!body.name) throw new Error("路由名称必填");
      await api("/api/admin/routes", { method: "POST", body: JSON.stringify(body) });
      $("rtName").value = ""; $("rtMap").value = "";
      await loadRoutes();
    }
    else if (t.dataset.rdel) {
      await api("/api/admin/routes/" + t.dataset.rdel, { method: "DELETE" });
      await loadRoutes();
    }
  } catch (e) { uiToast(e.message); }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && S.tab === "requests" && ev.target.matches("#fq, #fmodel")) {
    S.reqPage = 1; loadRequests();
    return;
  }
  if (ev.key === "Enter" && S.tab === "kb" && ev.target.id === "kbQuery") {
    searchKb().catch((e) => { $("kbResults").innerHTML = `<div class="kb-empty">检索失败：${esc(e.message)}</div>`; });
    return;
  }
  if (ev.key === "Enter" && S.tab === "moderation" && ev.target.id === "modWordSearch") {
    loadModerationPage().catch((e) => uiToast(e.message));
    return;
  }
  if (ev.key === "Enter" && S.tab === "moderation" && ev.target.id === "modWordInput") {
    addModerationWord().catch((e) => uiToast(e.message));
    return;
  }
  if (ev.key !== "Enter" || ev.shiftKey || ev.isComposing || !ev.target.matches("input")) return;
  const actions = {
    pvName: "addProvider", pvBase: "addProvider", pvKey: "addProvider",
    pvModels: "addProvider", pvIn: "addProvider", pvOut: "addProvider",
    rtName: "addRoute", rtMap: "addRoute",
    apiKeyName: "createApiKeyBtn",
    frontendUrl: "saveFrontendBtn",
    kbTitle: "kbSave",
    euName: "saveUserBtn", euPass: "saveUserBtn",
    egName: "saveGroupBtn", egDesc: "saveGroupBtn", erName: "saveRoleBtn",
  };
  const target = actions[ev.target.id];
  if (target && $(target) && !$(target).disabled) {
    ev.preventDefault();
    $(target).click();
  }
});

window.addEventListener("hashchange", () => {
  const name = tabNameFromHash();
  if (!name || $("main").hidden || name === S.tab) return;
  switchTab(name);
});

document.addEventListener("input", (ev) => {
  if (ev.target.id === "kbFilter") renderKbRows();
  if (ev.target.id === "libFilter") renderLibraryRows();
});

document.addEventListener("change", (ev) => {
  if (ev.target.id === "modHitDirection") {
    loadModerationPage().catch((e) => uiToast(e.message));
    return;
  }
  if (ev.target.id === "euRole") {
    syncAdminRoleSelect();
    return;
  }
  if (ev.target.id === "kbVectorOn" || ev.target.id === "kbVectorModel") {
    const on = $("kbVectorOn").checked;
    const model = $("kbVectorModel").value;
    const count = (S.kbVectorOptions || []).length;
    if (on && !model) $("kbVectorHint").textContent = "先选择一个向量模型，或取消“启用向量语义重排”。";
    else if (!on) $("kbVectorHint").textContent = count
      ? `检测到 ${count} 个可用向量模型；勾选“启用向量语义重排”并保存后用于知识库检索排序。`
      : "本机没有可用向量模型：先启动 LM Studio / Ollama，并加载一个 embedding 模型，再点“重新扫描”。";
    else $("kbVectorHint").textContent = "已选择向量模型，点“保存设置”后生效；只用于知识库检索排序，不进聊天模型下拉。";
    return;
  }
  if (ev.target.id === "kbScopeFilter" || ev.target.id === "kbUserFilter") {
    renderKbRows();
    return;
  }
  if (ev.target.id === "libScopeFilter" || ev.target.id === "libUserFilter"
      || ev.target.id === "libFolderFilter" || ev.target.id === "libTagFilter") {
    renderLibraryRows();
    return;
  }
  if (ev.target.id === "githubProxy") {
    S.platformProxy = ev.target.value.trim() || "auto";
    S.platformDirty = true;
    return;
  }
  if (ev.target.dataset && ev.target.dataset.platform) {
    S.platformDirty = true;
    S.platformSelected = [...document.querySelectorAll("#platformCards [data-platform]:checked")]
      .map((x) => x.dataset.platform);
    renderPlatforms(S.deployData);
    return;
  }
  if (ev.target.dataset && ev.target.dataset.platformUrl) {
    S.platformDirty = true;
    S.platformEndpoints = { ...S.platformEndpoints, [ev.target.dataset.platformUrl]: ev.target.value.trim() };
    return;
  }
  if (ev.target.id === "pvPreset") {
    applyProviderPreset(ev.target.value);
    return;
  }
  if (ev.target.id === "rtProvider") {
    $("rtMap").value = "";
    const value = ev.target.value;
    if (!value || value === "local") {
      $("rtMapHint").className = "hint form-note";
      $("rtMapHint").textContent = "已选择本地部署，模型映射可以留空；需要云端时再选供应商。";
    } else {
      const p = (S.routeProviders || []).find((x) => String(x.id) === String(value));
      const models = routeCloudModels(p);
      $("rtMapHint").className = "hint form-note";
      $("rtMapHint").textContent = `已选择 ${p ? p.name : "云端供应商"}（${models.length} 个模型）。点“自动匹配”或手动填 JSON。`;
    }
    return;
  }
  if (ev.target.id === "rtStrategy" && ev.target.value === "cloud_first") {
    if (($("rtProvider").value || "local") === "local" && (S.routeProviders || []).length) {
      $("rtProvider").value = String(S.routeProviders[0].id);
      $("rtProvider").dispatchEvent(new Event("change"));
    }
  }
  if (ev.target.id === "euAll") {
    document.querySelectorAll("#euModels input[type=checkbox]").forEach((x) => { x.disabled = ev.target.checked; });
  }
  if (ev.target.id === "apiAllKeys" && S.tab === "api") loadApi().catch((e) => uiToast(e.message));
  if (ev.target.id === "allowRegister") {
    const el = ev.target;
    api("/api/system/settings", {
      method: "PUT",
      body: JSON.stringify({ allow_register: el.checked }),
    }).then(() => { el.blur(); }).catch((e) => {
      el.checked = !el.checked;
      uiToast(e.message);
    });
  }
  if (ev.target.dataset && ev.target.dataset.authVendor) {
    const provider = ev.target.dataset.authVendor;
    const card = ev.target.closest(".auth-card");
    const item = AUTH_ITEMS.find((x) => x.key === provider);
    if (!card || !item) return;
    const selected = ev.target.value;
    card.querySelectorAll("[data-block-fields]").forEach((block) => {
      block.hidden = block.dataset.vendor !== selected;
    });
    const vendor = (item.vendors || []).find((v) => v.key === selected);
    const desc = card.querySelector("[data-vendor-desc]");
    if (desc && vendor) desc.textContent = vendor.description || "";
    authFillDefaults(card);
  }
  if (ev.target.id === "restoreFile") prepareRestoreBackup(ev);
  if (ev.target.id === "kbFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    ev.target.value = "";
    uploadKbFile(file).catch((e) => {
      $("kbDocHint").textContent = "上传失败：" + e.message;
      kbUploadNotice("上传失败：" + e.message, true);
    });
  }
  if (ev.target.id === "kbRestoreFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    S.kbRestoreFile = file;
    $("kbRestoreBtn").disabled = false;
    $("kbRestoreHint").textContent = `已选择 ${file.name} · ${sizeText(file.size)}。点“恢复备份”开始追加。`;
  }
  if (ev.target.id === "libFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    ev.target.value = "";
    uploadLibFile(file).catch((e) => {
      $("libDocHint").textContent = "上传失败：" + e.message;
      libNotice("上传失败：" + e.message, true);
    });
  }
  if (ev.target.id === "libRestoreFile" && ev.target.files && ev.target.files[0]) {
    const file = ev.target.files[0];
    S.libRestoreFile = file;
    $("libRestoreBtn").disabled = false;
    $("libRestoreHint").textContent = `已选择 ${file.name} · ${sizeText(file.size)}。点“恢复备份”开始追加。`;
  }
});

/* ---------------------------------------------------------------- 数据库中心 */
function dbState() {
  if (!S.db) {
    S.db = {
      view: "browse", conn: "local", table: "", tables: [], schema: null,
      rows: [], total: 0, page: 0, pageSize: 30, search: "", sort: "", order: "desc",
      filter: "", connections: [], editing: null, sqlConn: "local", job: null,
      jobTimer: null, lastOverview: null, lastJobId: "", migrateConn: "",
    };
  }
  return S.db;
}

function dbFmtBytes(n) {
  n = Number(n || 0);
  if (!n) return "0 B";
  if (n < 1024) return n + " B";
  if (n < 1024 ** 2) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 ** 3) return (n / 1024 ** 2).toFixed(1) + " MB";
  return (n / 1024 ** 3).toFixed(2) + " GB";
}
function dbFmtTime(ts) {
  if (!ts) return "—";
  try { return new Date(Number(ts) * 1000).toLocaleString("zh-CN", { hour12: false }); } catch { return "—"; }
}
function dbNum(n) { return Number(n || 0).toLocaleString("zh-CN"); }
function dbTargetText(c) {
  if (!c) return "";
  if (c.engine === "sqlite") return c.path || c.database || "SQLite 文件";
  return `${c.host || "127.0.0.1"}:${c.port || ""} / ${c.database || ""}`;
}
function dbSetStatus(id, text, kind = "") {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.className = "db-form-status" + (kind ? " " + kind : "");
}

async function loadDatabasePage() {
  const d = dbState();
  dbSwitchView(d.view || "browse", false);
  let overview = null;
  let listing = null;
  try { overview = await api("/api/admin/database/overview?connection=" + encodeURIComponent(d.conn)); }
  catch (e) { overview = { error: e.message }; }
  try { listing = await api("/api/admin/database/connections"); }
  catch (e) { listing = { connections: [], error: e.message }; }
  d.connections = listing.connections || [];
  d.lastOverview = overview;
  dbRenderStats(overview);
  dbFillConnSelects();
  await dbLoadBrowse();
  if (d.view === "migrate") { dbFillMigrateTargets(); dbLoadMigrationHistory().catch(() => {}); }
  dbLoadConnections().catch(() => {});
}

function dbRenderStats(o) {
  const box = $("dbStatGrid");
  if (!box) return;
  if (!o || o.error) {
    box.innerHTML = `<div class="db-stat"><div class="k">数据库状态</div><div class="v">读取失败</div><div class="s">${esc((o && o.error) || "未知错误")}</div></div>`;
    return;
  }
  const c = o.connection || {};
  const isLocal = c.id === "local";
  const size = o.size ? dbFmtBytes(o.size) : (o.database || c.database || "—");
  const schema = o.schema_version ? `Schema v${o.schema_version}` : "外部数据库";
  const est = o.row_count_estimated ? "含估算行数" : "按表精确统计";
  const cards = [
    ["当前查看的数据库", c.name || "数据库", `${c.engine_label || c.engine || ""} · ${c.database || ""}`],
    ["表 / 视图", `${dbNum(o.table_count)} 张表${o.view_count ? ` · ${dbNum(o.view_count)} 个视图` : ""}`, schema],
    ["总行数", dbNum(o.row_count), est],
    [isLocal ? "文件大小" : "版本", isLocal ? size : (o.version || "—"), isLocal ? (o.path || c.path || "") : (c.host ? `${c.host}:${c.port || ""}` : (c.database || ""))],
  ];
  box.innerHTML = cards.map(([k, v, s]) => `<div class="db-stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s" title="${esc(s)}">${esc(s)}</div></div>`).join("");
}

function dbFillConnSelects() {
  const d = dbState();
  const options = `<option value="local">当前工作台数据库（SQLite）</option>` +
    d.connections.map((c) => `<option value="${esc(c.id)}">${esc(c.name)} · ${esc(c.engine_label || c.engine)}</option>`).join("");
  [["dbConnSelect", d.conn], ["dbSqlConn", d.sqlConn]].forEach(([id, value]) => {
    const sel = $(id);
    if (!sel) return;
    sel.innerHTML = options;
    sel.value = value;
    if (!sel.value) { sel.value = "local"; }
  });
  if ($("dbConnSelect")) d.conn = $("dbConnSelect").value || "local";
  if ($("dbSqlConn")) d.sqlConn = $("dbSqlConn").value || "local";
}

async function dbLoadBrowse() {
  const d = dbState();
  try {
    const res = await api("/api/admin/database/tables?connection=" + encodeURIComponent(d.conn));
    d.tables = res.tables || [];
  } catch (e) {
    d.tables = [];
    dbSetStatus("dbOpsHint", "读取失败：" + e.message, "bad");
    dbRenderTableList();
    dbRenderEmptyTable("读取表清单失败：" + e.message);
    return;
  }
  dbRenderTableList();
  if (!d.tables.some((t) => t.name === d.table)) d.table = d.tables[0] ? d.tables[0].name : "";
  dbRenderActiveTable();
  if (!d.table) { dbRenderEmptyTable("这个数据库里还没有表。"); return; }
  await Promise.all([dbLoadRows(), dbLoadSchema()]);
  dbLoadHealth().catch(() => {});
}

function dbRenderTableList() {
  const d = dbState();
  const f = (d.filter || "").toLowerCase();
  const rows = d.tables.filter((t) => !f || String(t.name).toLowerCase().includes(f));
  const box = $("dbTableList");
  if (!box) return;
  if (!rows.length) {
    box.innerHTML = `<div class="db-empty">${d.tables.length ? "没有匹配的表名" : "还没有表"}</div>`;
  } else {
    box.innerHTML = rows.map((t) => `<button class="db-table-item${t.name === d.table ? " active" : ""}" data-dbtable="${esc(t.name)}" title="${esc(t.name)}">
      <span class="n">${esc(t.name)}</span>
      ${t.kind === "view" ? `<span class="kind">视图</span>` : `<span class="c">${dbNum(t.rows)}</span>`}
    </button>`).join("");
  }
  $("dbTableCount").textContent = `${d.tables.length} 张`;
}

function dbRenderActiveTable() {
  const d = dbState();
  const active = d.tables.find((t) => t.name === d.table);
  $("dbTableName").textContent = active ? active.name : "先选一张表";
  $("dbTableMeta").textContent = active
    ? `${active.kind === "view" ? "视图" : "表"} · ${dbNum(active.rows)} 行${active.rows_estimated ? "（估算）" : ""}`
    : "左侧点表名，右侧显示数据。";
  dbRenderTableList();
  $("dbNewRow").disabled = !active || active.kind === "view";
  $("dbExportCsv").disabled = !active;
  const canManage = !!active && active.kind !== "view";
  const protectedList = (d.lastOverview && d.lastOverview.protected_tables) || [];
  const isProtected = protectedList.includes(active ? active.name : "");
  ["dbTableRenameBtn", "dbTableTruncateBtn", "dbTableDropBtn"].forEach((id) => {
    $(id).hidden = !canManage;
  });
  $("dbTableRenameBtn").disabled = isProtected;
  $("dbTableDropBtn").disabled = isProtected;
  $("dbTableRenameBtn").title = isProtected ? "工作台运行依赖的表不能改名" : "";
  $("dbTableDropBtn").title = isProtected ? "工作台运行依赖的表不能删除" : "";
}

function dbRenderEmptyTable(text) {
  $("dbThead").innerHTML = "";
  $("dbTbody").innerHTML = `<tr><td class="db-empty">${esc(text)}</td></tr>`;
  $("dbPageInfo").textContent = "—";
  $("dbPageBadge").textContent = "—";
  $("dbPageBadge").className = "badge off";
  $("dbPrevPage").disabled = true;
  $("dbNextPage").disabled = true;
  if ($("dbSchemaBody")) $("dbSchemaBody").innerHTML = `<span class="hint">选中表后加载。</span>`;
}

function dbColumnsOf(res) {
  return (res.columns || []).map((c) => (typeof c === "string" ? { name: c } : c));
}

async function dbLoadRows() {
  const d = dbState();
  if (!d.table) { dbRenderEmptyTable("先从左边选一张表。"); return; }
  const q = new URLSearchParams({
    connection: d.conn, limit: String(d.pageSize), offset: String(d.page * d.pageSize),
    search: d.search || "", sort: d.sort || "", order: d.order || "desc",
  });
  $("dbTbody").innerHTML = `<tr><td class="db-empty">正在读取…</td></tr>`;
  try {
    const res = await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/rows?${q}`);
    d.rows = res.rows || [];
    d.total = Number(res.total || 0);
    dbRenderGrid(res);
  } catch (e) {
    dbRenderEmptyTable("读取失败：" + e.message);
  }
}

function dbCellPreview(v) {
  if (v === null || v === undefined) return { text: "NULL", kind: "null" };
  if (typeof v === "object") v = JSON.stringify(v);
  const s = String(v);
  return { text: s, kind: /^-?\d+(\.\d+)?$/.test(s) ? "num" : "" };
}

function dbRenderGrid(res) {
  const d = dbState();
  const cols = dbColumnsOf(res);
  if (!cols.length) { dbRenderEmptyTable("这张表没有可显示的字段。"); return; }
  const active = d.tables.find((t) => t.name === d.table);
  const editable = active && active.kind !== "view";
  const tbl = $("dbThead").closest("table");
  if (tbl) tbl.classList.toggle("has-actions", !!editable);
  $("dbThead").innerHTML = "<tr>" + cols.map((c) => {
    const sorted = d.sort === c.name;
    return `<th class="sortable" data-dbsort="${esc(c.name)}" title="按 ${esc(c.name)} 排序">${esc(c.name)}<span class="sort">${sorted ? (d.order === "asc" ? "▲" : "▼") : "↕"}</span></th>`;
  }).join("") + (editable ? "<th class=\"right\">操作</th>" : "") + "</tr>";

  if (!d.rows.length) {
    $("dbTbody").innerHTML = `<tr><td class="db-empty" colspan="${cols.length + (editable ? 1 : 0)}">${d.search ? "没有匹配的行" : "这张表还没有数据"}</td></tr>`;
  } else {
    $("dbTbody").innerHTML = d.rows.map((row) => {
      const cells = cols.map((c) => {
        const p = dbCellPreview(row[c.name]);
        return `<td><span class="db-cell ${p.kind}" title="${esc(p.text)}">${esc(p.text)}</span></td>`;
      }).join("");
      const key = row._key || "";
      const actions = editable
        ? `<td><div class="db-cell-actions">${key
            ? `<button class="btn small" data-dbedit="${esc(key)}">编辑</button><button class="btn small" data-dbdel="${esc(key)}">删除</button>`
            : `<span class="badge off" title="没有主键的表需要到 SQL 控制台修改">无主键</span>`}</div></td>`
        : "";
      return `<tr>${cells}${actions}</tr>`;
    }).join("");
  }
  const pages = Math.max(1, Math.ceil(d.total / d.pageSize));
  $("dbPageInfo").textContent = `第 ${Math.min(d.page + 1, pages)} / ${pages} 页 · 共 ${dbNum(d.total)} 行`;
  $("dbPageBadge").textContent = `${d.conn === "local" ? "主库" : "外部库"}`;
  $("dbPageBadge").className = "badge " + (d.conn === "local" ? "ok" : "warn");
  $("dbPrevPage").disabled = d.page <= 0;
  $("dbNextPage").disabled = (d.page + 1) * d.pageSize >= d.total;
}

async function dbLoadSchema() {
  const d = dbState();
  if (!d.table) { d.schema = null; return; }
  try {
    d.schema = await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/schema?connection=${encodeURIComponent(d.conn)}`);
    dbRenderSchema(d.schema);
  } catch (e) {
    d.schema = null;
    $("dbSchemaBody").innerHTML = `<span class="hint">读取表结构失败：${esc(e.message)}</span>`;
  }
}

function dbRenderSchema(s) {
  const box = $("dbSchemaBody");
  if (!box) return;
  if (!s) { box.innerHTML = `<span class="hint">没有表结构信息。</span>`; return; }
  const cols = (s.columns || []).map((c) => `<tr>
    <td><b>${esc(c.name)}</b>${c.pk ? ` <span class="badge ok">主键</span>` : ""}</td>
    <td class="mono">${esc(c.type)}</td>
    <td>${c.nullable ? "可空" : "必填"}</td>
    <td class="mono">${c.default === null || c.default === undefined ? "—" : esc(c.default)}</td>
    <td>${c.auto ? "自增" : ""}</td></tr>`).join("");
  const idx = (s.indexes || []).map((i) => `<li><b>${esc(i.name)}</b> · ${(i.columns || []).map(esc).join(", ")}${i.unique ? " · 唯一" : ""}${i.primary ? " · 主键" : ""}</li>`).join("");
  const fks = (s.foreign_keys || []).map((f) => `<li>${esc(f.from)} → ${esc(f.table)}.${esc(f.to)}</li>`).join("");
  box.innerHTML = `<div class="db-schema-body">
    <div class="table-wrap"><table class="tbl"><thead><tr><th>字段</th><th>类型</th><th>可空</th><th>默认值</th><th>自增</th></tr></thead><tbody>${cols || `<tr><td class="db-empty">无字段</td></tr>`}</tbody></table></div>
    ${idx ? `<div><h4>索引</h4><ul class="share-list">${idx}</ul></div>` : ""}
    ${fks ? `<div><h4>外键</h4><ul class="share-list">${fks}</ul></div>` : ""}
    <div><h4>建表 SQL</h4><pre>${esc(s.create_sql || "（视图或没有建表语句）")}</pre></div>
  </div>`;
}

async function dbSelectTable(name) {
  const d = dbState();
  d.table = name;
  d.page = 0;
  d.search = "";
  d.sort = "";
  d.order = "desc";
  $("dbRowSearch").value = "";
  dbRenderActiveTable();
  await Promise.all([dbLoadRows(), dbLoadSchema()]);
}

async function dbLoadHealth() {
  const d = dbState();
  const body = $("dbHealthBody");
  const btn = $("dbHealthBtn");
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "检查中…"; }
  if (body) body.innerHTML = `<span class="hint">正在检查…</span>`;
  try {
    const h = await api("/api/admin/database/health?connection=" + encodeURIComponent(d.conn));
    const checks = h.checks || [];
    const fk = checks.find((c) => c.name === "外键检查");
    const bad = checks.filter((c) => !c.ok).length;
    if (body) {
      body.innerHTML = checks.map((c) => {
        const detail = c.hint ? `${c.detail} · ${c.hint}` : c.detail;
        const list = (c.details || []).length ? `<div class="db-health-list">${c.details.map((r) =>
          `<span class="db-health-chip">${esc(r.table)} #${dbNum(r.rowid)} → ${esc(r.parent)}</span>`).join("")}</div>` : "";
        return `<div class="db-health-line">
          <span>${esc(c.name)}</span><span><b class="${c.ok ? "ok" : "bad"}">${c.ok ? "通过" : "异常"}</b> · ${esc(detail)}</span>
        </div>${list}`;
      }).join("") + `<div class="db-health-foot">
        <span class="hint">最后检查 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} · 耗时 ${h.latency_ms} ms</span>
        ${fk && !fk.ok ? `<button class="btn small" data-dbfixfk="1">清理这 ${(fk.details || []).length} 条孤儿记录</button>` : ""}
      </div>`;
    }
    uiToast(`健康检查完成 · 耗时 ${h.latency_ms} ms`, bad ? "warn" : "info");
  } catch (e) {
    if (body) body.innerHTML = `<div class="db-sql-error">健康检查失败：${esc(e.message)}</div>`;
    uiToast("健康检查失败：" + e.message, "bad");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label || "重新检查"; }
  }
}

async function dbRepairForeignKey() {
  const d = dbState();
  const ok = await confirmInline("将删除指向已删除用户的孤儿记录，父表数据不动，修复前会自动生成一份数据库快照。", "确认清理");
  if (!ok) return;
  try {
    const r = await api("/api/admin/database/repair-foreign-keys?connection=" + encodeURIComponent(d.conn), { method: "POST" });
    uiToast(`已清理 ${r.total} 条孤儿记录 · 快照 ${r.backup}`, "info");
  } catch (e) {
    uiToast("修复失败：" + e.message, "bad");
  }
  await dbLoadHealth();
}

/* ---------------------------------------------------------------- 表管理 */
function dbOpenTableAction(mode) {
  const d = dbState();
  if (!d.table) return;
  const modal = $("dbTableActionModal");
  modal.dataset.mode = mode;
  modal.dataset.table = d.table;
  const titles = { rename: "重命名表", truncate: "清空表数据", drop: "删除整张表" };
  const descs = {
    rename: "改名后，代码或报表里写死的旧表名会失效。工作台核心表已禁用此操作。",
    truncate: "只删除表里的所有数据，保留字段、索引和外键；执行前会自动生成一份 SQLite 快照。",
    drop: "删除整张表和全部数据，无法恢复；执行前会自动生成一份 SQLite 快照。",
  };
  $("dbTableActionTitle").textContent = `${titles[mode]} · ${d.table}`;
  $("dbTableActionSub").textContent = mode === "rename" ? "改成一个新名字" : "危险操作，请确认表名";
  $("dbTableActionDesc").textContent = descs[mode];
  $("dbTableActionInputWrap").hidden = false;
  $("dbTableActionStatus").textContent = "";
  const input = $("dbTableActionInput");
  input.value = mode === "rename" ? `${d.table}_copy` : "";
  $("dbTableActionInputWrap").childNodes[0].nodeValue = mode === "rename" ? "新表名" : `输入表名 ${d.table} 确认`;
  $("dbTableActionConfirm").textContent = mode === "rename" ? "重命名" : mode === "truncate" ? "清空" : "永久删除";
  $("dbTableActionConfirm").className = "btn " + (mode === "rename" ? "primary" : "danger");
  $("dbTableActionConfirm").disabled = false;
  modal.hidden = false;
  setTimeout(() => { input.focus(); if (mode === "rename") input.select(); }, 30);
}

function dbCloseTableAction() {
  $("dbTableActionModal").hidden = true;
}

async function dbSubmitTableAction() {
  const d = dbState();
  const modal = $("dbTableActionModal");
  const mode = modal.dataset.mode;
  const table = modal.dataset.table;
  const value = $("dbTableActionInput").value.trim();
  if (!value) { dbSetStatus("dbTableActionStatus", "请填写后再继续。", "bad"); return; }
  if (mode !== "rename" && value !== table) {
    dbSetStatus("dbTableActionStatus", "输入的表名不完整，请重新输入。", "bad");
    return;
  }
  $("dbTableActionConfirm").disabled = true;
  dbSetStatus("dbTableActionStatus", "正在执行…");
  try {
    if (mode === "rename") {
      await api(`/api/admin/database/table/${encodeURIComponent(table)}/rename?connection=${encodeURIComponent(d.conn)}`, {
        method: "POST", body: JSON.stringify({ new_name: value }),
      });
      d.table = value;
    } else if (mode === "truncate") {
      const res = await api(`/api/admin/database/table/${encodeURIComponent(table)}/truncate?connection=${encodeURIComponent(d.conn)}`, {
        method: "POST", body: JSON.stringify({ confirm: value }),
      });
      dbCloseTableAction();
      uiToast(`已清空 ${table}${res.affected ? `，删除 ${dbNum(res.affected)} 行` : ""}`, "ok");
      d.page = 0;
      await dbLoadBrowse();
      dbLoadOverview().catch(() => {});
      return;
    } else {
      await api(`/api/admin/database/table/${encodeURIComponent(table)}?connection=${encodeURIComponent(d.conn)}`, {
        method: "DELETE", body: JSON.stringify({ confirm: value }),
      });
      d.table = "";
    }
    dbCloseTableAction();
    uiToast(mode === "rename" ? `已将 ${table} 改名为 ${value}` : `已删除表 ${table}`, "ok");
    d.page = 0;
    await dbLoadBrowse();
    dbLoadOverview().catch(() => {});
  } catch (e) {
    dbSetStatus("dbTableActionStatus", "执行失败：" + e.message, "bad");
    $("dbTableActionConfirm").disabled = false;
  }
}

function dbNewColumnRow(col = {}) {
  const row = document.createElement("div");
  row.className = "db-col-row";
  row.innerHTML = `<input type="text" data-col-name value="${esc(col.name || "")}" placeholder="字段名">
    <select data-col-type>
      ${["INTEGER", "TEXT", "VARCHAR(255)", "REAL", "BOOLEAN", "DATETIME", "BLOB"].map((t) =>
        `<option value="${t}" ${t === (col.type || "TEXT") ? "selected" : ""}>${
          t === "INTEGER" ? "整数" : t === "TEXT" ? "长文本" : t === "VARCHAR(255)" ? "短文本" :
          t === "REAL" ? "小数" : t === "BOOLEAN" ? "是/否" : t === "DATETIME" ? "日期时间" : "二进制"}</option>`).join("")}
    </select>
    <label class="db-col-check"><input type="checkbox" data-col-pk ${col.primary_key ? "checked" : ""}>主键</label>
    <label class="db-col-check"><input type="checkbox" data-col-auto ${col.auto ? "checked" : ""}>自增</label>
    <label class="db-col-check"><input type="checkbox" data-col-null ${col.nullable !== false ? "checked" : ""}>可空</label>
    <button class="db-col-remove" type="button" title="删除这个字段">×</button>`;
  $("dbNewColumns").appendChild(row);
  dbSyncColumnRow(row);
  return row;
}

function dbSyncColumnRow(row) {
  const type = row.querySelector("[data-col-type]").value;
  const pk = row.querySelector("[data-col-pk]").checked;
  const auto = row.querySelector("[data-col-auto]");
  auto.disabled = !(pk && type === "INTEGER");
  if (auto.disabled) auto.checked = false;
  row.querySelector("[data-col-null]").disabled = pk;
  if (pk) row.querySelector("[data-col-null]").checked = false;
}

function dbOpenCreateTable() {
  $("dbNewTableName").value = "";
  $("dbNewColumns").innerHTML = "";
  $("dbCreateTableStatus").textContent = "";
  dbNewColumnRow({ name: "id", type: "INTEGER", primary_key: true, auto: true, nullable: false });
  dbNewColumnRow({ name: "created_at", type: "DATETIME", nullable: true });
  dbNewColumnRow({ name: "name", type: "TEXT", nullable: true });
  $("dbCreateTableModal").hidden = false;
  setTimeout(() => $("dbNewTableName").focus(), 30);
}

function dbCloseCreateTable() {
  $("dbCreateTableModal").hidden = true;
}

async function dbSubmitCreateTable() {
  const d = dbState();
  const table = $("dbNewTableName").value.trim();
  if (!table) { dbSetStatus("dbCreateTableStatus", "请先填写表名。", "bad"); return; }
  const columns = [...$("dbNewColumns").querySelectorAll(".db-col-row")].map((row) => ({
    name: row.querySelector("[data-col-name]").value.trim(),
    type: row.querySelector("[data-col-type]").value,
    primary_key: row.querySelector("[data-col-pk]").checked,
    auto: row.querySelector("[data-col-auto]").checked && !row.querySelector("[data-col-auto]").disabled,
    nullable: row.querySelector("[data-col-null]").checked,
  }));
  if (!columns.length) { dbSetStatus("dbCreateTableStatus", "至少要有一个字段。", "bad"); return; }
  if (columns.some((c) => !c.name)) { dbSetStatus("dbCreateTableStatus", "字段名不能留空。", "bad"); return; }
  if (columns.filter((c) => c.primary_key).length > 1) { dbSetStatus("dbCreateTableStatus", "只能选一个主键字段。", "bad"); return; }
  const auto = columns.find((c) => c.auto);
  if (auto && auto.type !== "INTEGER") { dbSetStatus("dbCreateTableStatus", "自增主键必须是整数类型。", "bad"); return; }
  $("dbCreateTableSubmit").disabled = true;
  dbSetStatus("dbCreateTableStatus", "正在创建…");
  try {
    await api("/api/admin/database/table", {
      method: "POST",
      body: JSON.stringify({ connection: d.conn, table, columns }),
    });
    dbCloseCreateTable();
    uiToast(`表 ${table} 已创建`, "ok");
    d.table = table;
    d.page = 0;
    await dbLoadBrowse();
    dbLoadOverview().catch(() => {});
  } catch (e) {
    dbSetStatus("dbCreateTableStatus", "创建失败：" + e.message, "bad");
  } finally {
    $("dbCreateTableSubmit").disabled = false;
  }
}


function dbFieldValue(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

async function dbOpenRowModal(mode, key) {
  const d = dbState();
  if (!d.schema) await dbLoadSchema();
  if (!d.schema || !d.schema.columns) throw new Error("表结构还没加载好");
  let row = null;
  if (mode === "edit") {
    const res = await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/row?connection=${encodeURIComponent(d.conn)}&key=${encodeURIComponent(key)}`);
    row = res.row;
  }
  const schema = d.schema;
  const pks = schema.primary_key || [];
  const fields = schema.columns.map((c) => {
    const disabled = mode === "edit" && c.pk;
    const isAuto = mode === "create" && c.auto && c.pk;
    const val = row ? dbFieldValue(row[c.name]) : "";
    const long = String(c.type || "").toUpperCase().includes("TEXT") || (val && val.length > 80);
    const control = long
      ? `<textarea data-dbcol="${esc(c.name)}" ${disabled || isAuto ? "disabled" : ""} placeholder="${esc(c.default ?? "")}">${esc(val)}</textarea>`
      : `<input data-dbcol="${esc(c.name)}" value="${esc(val)}" ${disabled || isAuto ? "disabled" : ""} placeholder="${esc(c.default ?? "")}">`;
    return `<div class="db-field${long ? " full" : ""}">
      <label><b>${esc(c.name)}</b> · ${esc(c.type)}${c.pk ? " · 主键" : ""}${isAuto ? " · 自增不用填" : ""}</label>
      ${control}
      ${c.nullable ? `<span class="hint">可空；留空保存为 NULL</span>` : ""}
    </div>`;
  }).join("");
  $("dbModalTitle").textContent = mode === "create" ? `新增一行 · ${d.table}` : `编辑一行 · ${d.table}`;
  $("dbModalSub").textContent = mode === "create" ? "填写字段后保存；自增主键由数据库生成。" : "主键不能改；要改主键请使用 SQL 控制台。";
  $("dbModalBody").innerHTML = fields;
  $("dbModalDelete").hidden = !(mode === "edit" && pks.length);
  $("dbModalSave").disabled = false;
  $("dbModalDelete").disabled = false;
  $("dbModalSave").textContent = "保存";
  dbSetStatus("dbModalStatus", "");
  d.modal = { mode, key, row, table: d.table, conn: d.conn, schema };
  $("dbRowModal").hidden = false;
  setTimeout(() => { const el = $("dbModalBody").querySelector("input:not(:disabled), textarea:not(:disabled)"); if (el) el.focus(); }, 30);
}

function dbCloseRowModal() {
  $("dbRowModal").hidden = true;
  const d = dbState();
  d.modal = null;
}

async function dbSaveRow() {
  const d = dbState();
  const m = d.modal;
  if (!m) return;
  const vals = {};
  let missingPk = false;
  $("dbModalBody").querySelectorAll("[data-dbcol]").forEach((el) => {
    if (el.disabled) return;
    const name = el.dataset.dbcol;
    const col = (m.schema.columns || []).find((c) => c.name === name);
    const value = el.value;
    if (m.mode === "create" && col && col.pk && !col.auto && !value.trim()) missingPk = true;
    vals[name] = value;
  });
  if (missingPk) { dbSetStatus("dbModalStatus", "这张表的主键需要手动填写，不能留空。", "bad"); return; }
  if (!Object.keys(vals).length) { dbSetStatus("dbModalStatus", "没有可保存的字段。", "bad"); return; }
  $("dbModalSave").disabled = true;
  dbSetStatus("dbModalStatus", "正在保存…");
  try {
    if (m.mode === "create") {
      await api(`/api/admin/database/table/${encodeURIComponent(m.table)}/rows?connection=${encodeURIComponent(m.conn)}`, {
        method: "POST", body: JSON.stringify({ values: vals }),
      });
    } else {
      await api(`/api/admin/database/table/${encodeURIComponent(m.table)}/row?connection=${encodeURIComponent(m.conn)}`, {
        method: "PATCH", body: JSON.stringify({ key: m.key, values: vals }),
      });
    }
    uiToast("已保存", "ok");
    dbCloseRowModal();
    await dbLoadRows();
    dbLoadHealth().catch(() => {});
    dbLoadOverview().catch(() => {});
  } catch (e) {
    dbSetStatus("dbModalStatus", "保存失败：" + e.message, "bad");
    $("dbModalSave").disabled = false;
  }
}

async function dbDeleteRow(key) {
  const d = dbState();
  if (!d.table) return;
  const ok = await confirmInline(`确定删除 ${d.table} 的这一行？删除后不能撤销，建议先备份。`, "确认删除");
  if (!ok) return;
  try {
    await api(`/api/admin/database/table/${encodeURIComponent(d.table)}/row?connection=${encodeURIComponent(d.conn)}`, {
      method: "DELETE", body: JSON.stringify({ key }),
    });
    uiToast("已删除这一行", "ok");
    if (d.modal) dbCloseRowModal();
    await dbLoadRows();
    dbLoadHealth().catch(() => {});
  } catch (e) { uiToast("删除失败：" + e.message, "bad"); }
}

/* ---------------------------------------------------------------- 概览刷新 */
async function dbLoadOverview() {
  const d = dbState();
  try {
    const o = await api("/api/admin/database/overview?connection=" + encodeURIComponent(d.conn));
    d.lastOverview = o;
    dbRenderStats(o);
  } catch (e) {
    dbRenderStats({ error: e.message });
  }
}

/* ---------------------------------------------------------------- SQL 控制台 */
async function dbRunSql() {
  const d = dbState();
  const sql = $("dbSqlText").value.trim();
  if (!sql) { $("dbSqlError").hidden = false; $("dbSqlError").textContent = "请先输入 SQL。"; return; }
  const allow = $("dbAllowWrite").checked;
  if (allow) {
    const ok = await confirmInline("写操作会直接修改数据库，可能删改真实数据。确认执行这条 SQL？", "确认执行");
    if (!ok) return;
  }
  const btn = $("dbRunSql");
  btn.disabled = true;
  $("dbSqlError").hidden = true;
  $("dbSqlMeta").textContent = "执行中…";
  $("dbSqlWrap").hidden = true;
  try {
    const res = await api("/api/admin/database/query", {
      method: "POST",
      body: JSON.stringify({ connection: d.sqlConn, sql, allow_write: allow, limit: Number($("dbSqlLimit").value) || 100 }),
    });
    const cols = res.columns || [];
    const rows = res.rows || [];
    const meta = [`耗时 ${res.elapsed_ms} ms`, `返回 ${rows.length} 行`];
    if (res.affected >= 0) meta.push(`影响 ${res.affected} 行`);
    if (res.last_id) meta.push(`last_id ${res.last_id}`);
    if (res.truncated) meta.push(`结果已截断到 ${res.limit} 行`);
    if (res.write) meta.push("写操作");
    $("dbSqlMeta").textContent = meta.join(" · ");
    if (cols.length) {
      $("dbSqlThead").innerHTML = "<tr>" + cols.map((c) => `<th>${esc(c)}</th>`).join("") + "</tr>";
      $("dbSqlTbody").innerHTML = rows.length ? rows.map((r) => "<tr>" + cols.map((c, i) => {
        const p = dbCellPreview(Array.isArray(r) ? r[i] : r[c]);
        return `<td><span class="db-cell ${p.kind}" title="${esc(p.text)}">${esc(p.text)}</span></td>`;
      }).join("") + "</tr>").join("") : `<tr><td class="db-empty" colspan="${cols.length}">查询没有返回行</td></tr>`;
      $("dbSqlWrap").hidden = false;
    } else {
      $("dbSqlWrap").hidden = true;
      $("dbSqlMeta").textContent = meta.join(" · ") + " · 这条语句没有结果表";
    }
    uiToast("SQL 执行完成", "ok");
    dbLoadOverview().catch(() => {});
    if (d.table) dbLoadRows().catch(() => {});
  } catch (e) {
    $("dbSqlError").hidden = false;
    $("dbSqlError").textContent = "执行失败：" + e.message;
    $("dbSqlMeta").textContent = "执行失败";
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------------- 连接管理 */
async function dbLoadConnections() {
  const d = dbState();
  try {
    const res = await api("/api/admin/database/connections");
    d.connections = res.connections || [];
    dbRenderConnList();
    dbFillConnSelects();
    dbFillMigrateTargets();
  } catch (e) {
    $("dbConnList").innerHTML = `<div class="db-sql-error">读取连接失败：${esc(e.message)}</div>`;
  }
}

function dbRenderConnList() {
  const d = dbState();
  const box = $("dbConnList");
  if (!box) return;
  if (!d.connections.length) {
    box.innerHTML = `<div class="db-conn-empty">还没有外部连接。<br>在右边填一台 MySQL / PostgreSQL，或选一个外部 SQLite 文件。</div>`;
    return;
  }
  box.innerHTML = d.connections.map((c) => `<div class="db-conn-card">
    <div class="db-conn-top">
      <div style="min-width:0">
        <div class="db-conn-name">${esc(c.name)}</div>
        <div class="db-conn-meta">${esc(c.engine_label || c.engine)} · ${esc(dbTargetText(c))}</div>
      </div>
      <span class="badge ${c.password_set ? "good" : "off"}">${c.password_set ? "有密码" : (c.engine === "sqlite" ? "文件" : "无密码")}</span>
    </div>
    <div class="db-conn-meta">最近测试：${c.last_test_at ? dbFmtTime(c.last_test_at) : "还没测试"}${c.note ? " · " + esc(c.note) : ""}</div>
    <div class="db-conn-actions">
      <button class="btn small" data-dbconnbrowse="${esc(c.id)}">浏览数据</button>
      <button class="btn small" data-dbconntest="${esc(c.id)}">测试连接</button>
      <button class="btn small" data-dbconnedit="${esc(c.id)}">编辑</button>
      <button class="btn small" data-dbconndel="${esc(c.id)}">删除</button>
    </div>
  </div>`).join("");
}

function dbResetConnForm() {
  const d = dbState();
  d.editing = null;
  $("dbFormTitle").textContent = "新增外部数据库";
  ["dbConnName", "dbConnHost", "dbConnDatabase", "dbConnUser", "dbConnPassword", "dbConnPath", "dbConnNote", "dbConnUrl"].forEach((id) => { if ($(id)) $(id).value = ""; });
  $("dbConnEngine").value = "mysql";
  $("dbConnSsl").checked = false;
  $("dbConnPort").value = "";
  dbEngineChange();
  dbSetStatus("dbConnStatus", "");
  $("dbConnPassword").placeholder = "编辑时留空表示不修改";
  $("dbConnSave").textContent = "保存连接";
}

function dbEngineChange() {
  const engine = $("dbConnEngine").value;
  const net = engine !== "sqlite";
  $("dbNetworkFields").hidden = !net;
  $("dbSqliteField").hidden = net;
  $("dbSslRow").hidden = !net;
  $("dbEngineHint").textContent = engine === "mysql"
    ? "MySQL / MariaDB：需要账号有建库、建表权限；远程连接要放行 3306。"
    : engine === "postgres"
      ? "PostgreSQL：远程连接要放行 5432；迁移时会自动创建数据库（如账号有权限）。"
      : "SQLite 文件：可以选本机任意 .db 路径；不存在也能先保存。";
  if (engine === "mysql") { if (!$("dbConnPort").value) $("dbConnPort").placeholder = "3306"; }
  else if (engine === "postgres") { if (!$("dbConnPort").value) $("dbConnPort").placeholder = "5432"; }
}

function dbEditConn(id) {
  const d = dbState();
  const c = d.connections.find((x) => x.id === id);
  if (!c) return;
  d.editing = id;
  $("dbFormTitle").textContent = "编辑连接 · " + c.name;
  $("dbConnEngine").value = c.engine;
  $("dbConnName").value = c.name || "";
  $("dbConnHost").value = c.host || "";
  $("dbConnPort").value = c.port || "";
  $("dbConnDatabase").value = c.database || "";
  $("dbConnUser").value = c.username || "";
  $("dbConnPassword").value = "";
  $("dbConnPassword").placeholder = c.password_set ? "已保存密码；留空表示不修改" : "填写数据库密码";
  $("dbConnPath").value = c.path || "";
  $("dbConnSsl").checked = !!c.ssl;
  $("dbConnNote").value = c.note || "";
  $("dbConnSave").textContent = "保存修改";
  dbEngineChange();
  dbSetStatus("dbConnStatus", "正在编辑已有连接；密码留空不会覆盖原密码。");
  $("dbConnName").focus();
}

function dbCollectConnForm() {
  const engine = $("dbConnEngine").value;
  const body = {
    engine,
    name: $("dbConnName").value.trim(),
    host: $("dbConnHost").value.trim(),
    port: Number($("dbConnPort").value) || 0,
    database: $("dbConnDatabase").value.trim(),
    username: $("dbConnUser").value.trim(),
    password: $("dbConnPassword").value,
    path: $("dbConnPath").value.trim(),
    ssl: $("dbConnSsl").checked,
    note: $("dbConnNote").value.trim(),
  };
  if (!body.name) throw new Error("请给连接起一个名字，例如“云服务器 MySQL”");
  if (engine === "sqlite" && !body.path) throw new Error("请填写 SQLite 文件路径");
  if (engine !== "sqlite") {
    if (!body.database) throw new Error("请填写数据库名");
    if (!body.username) throw new Error("请填写数据库用户名");
  }
  return body;
}

async function dbSaveConn(testAfter = false) {
  const d = dbState();
  let body;
  try { body = dbCollectConnForm(); }
  catch (e) { dbSetStatus("dbConnStatus", e.message, "bad"); return null; }
  const btn = testAfter ? $("dbConnTestNew") : $("dbConnSave");
  btn.disabled = true;
  dbSetStatus("dbConnStatus", "正在保存…");
  try {
    let row;
    if (d.editing) {
      row = await api("/api/admin/database/connections/" + encodeURIComponent(d.editing), {
        method: "PUT", body: JSON.stringify(body),
      });
    } else {
      row = await api("/api/admin/database/connections", { method: "POST", body: JSON.stringify(body) });
    }
    await dbLoadConnections();
    d.editing = row.id;
    $("dbFormTitle").textContent = "编辑连接 · " + row.name;
    $("dbConnSave").textContent = "保存修改";
    $("dbConnPassword").value = "";
    $("dbConnPassword").placeholder = "已保存密码；留空表示不修改";
    dbSetStatus("dbConnStatus", `已保存：${row.name}（${row.engine_label}）`, "ok");
    uiToast("连接已保存", "ok");
    if (testAfter) return await dbTestConn(row.id, true);
    return row;
  } catch (e) {
    dbSetStatus("dbConnStatus", "保存失败：" + e.message, "bad");
    return null;
  } finally {
    btn.disabled = false;
  }
}

async function dbTestConn(id, quiet = false) {
  dbSetStatus("dbConnStatus", "正在测试连接…");
  try {
    const res = await api("/api/admin/database/connections/" + encodeURIComponent(id) + "/test", { method: "POST" });
    const text = `${res.ok ? "连接成功" : "连接失败"} · ${res.info || res.engine} · ${res.version || ""} · ${res.tables} 个表 · ${res.latency_ms} ms${res.message ? " · " + res.message : ""}`;
    dbSetStatus("dbConnStatus", text, res.ok ? "ok" : "bad");
    if (!quiet) uiToast(text, res.ok ? "ok" : "bad");
    dbLoadConnections().catch(() => {});
    return res;
  } catch (e) {
    dbSetStatus("dbConnStatus", "测试失败：" + e.message, "bad");
    if (!quiet) uiToast("测试失败：" + e.message, "bad");
    return null;
  }
}

async function dbDeleteConn(id) {
  const d = dbState();
  const c = d.connections.find((x) => x.id === id);
  const ok = await confirmInline(`确定删除连接“${c ? c.name : id}”？这不会删除目标数据库里的数据，只是从本机移除记录。`, "删除连接");
  if (!ok) return;
  try {
    await api("/api/admin/database/connections/" + encodeURIComponent(id), { method: "DELETE" });
    if (d.conn === id) d.conn = "local";
    if (d.sqlConn === id) d.sqlConn = "local";
    if (d.editing === id) dbResetConnForm();
    await dbLoadConnections();
    dbFillConnSelects();
    uiToast("连接已删除", "ok");
    if (d.view === "browse") await dbLoadBrowse();
  } catch (e) { uiToast("删除失败：" + e.message, "bad"); }
}

async function dbParseConnUrl() {
  const url = $("dbConnUrl").value.trim();
  if (!url) { dbSetStatus("dbConnStatus", "先粘贴连接串，例如 mysql://root:密码@127.0.0.1:3306/workbench", "bad"); return; }
  try {
    const p = await api("/api/admin/database/connections/parse", { method: "POST", body: JSON.stringify({ url }) });
    const label = { mysql: "MySQL / MariaDB", postgres: "PostgreSQL", sqlite: "SQLite" }[p.engine] || p.engine;
    $("dbConnEngine").value = p.engine;
    $("dbConnName").value = p.name || label;
    $("dbConnHost").value = p.host || "";
    $("dbConnPort").value = p.port || "";
    $("dbConnDatabase").value = p.database || "";
    $("dbConnUser").value = p.username || "";
    $("dbConnPassword").value = p.password || "";
    $("dbConnPath").value = p.engine === "sqlite" ? (p.path || p.database || "") : "";
    $("dbConnSsl").checked = !!p.ssl;
    dbEngineChange();
    dbSetStatus("dbConnStatus", "连接串已解析，请检查字段后点“保存连接”。", "ok");
  } catch (e) { dbSetStatus("dbConnStatus", "解析失败：" + e.message, "bad"); }
}

/* ---------------------------------------------------------------- 备份与导出 */
async function dbDownload(url, opts, fallbackName) {
  const headers = { ...(opts.headers || {}) };
  if (token()) headers.Authorization = "Bearer " + token();
  const r = await fetch(url, { ...opts, headers });
  if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); showLogin(); throw new Error("未登录"); }
  if (!r.ok) {
    let msg = "下载失败";
    try { const d = await r.json(); msg = d.detail || msg; } catch {}
    throw new Error(msg);
  }
  const blob = await r.blob();
  let name = fallbackName;
  const cd = r.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^";]+)"?/i);
  if (m) name = m[1];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  uiToast("已开始下载：" + name, "ok");
  return name;
}

async function dbBackup() {
  const d = dbState();
  if (d.conn !== "local") { uiToast("快照只针对当前工作台 SQLite；外部库请用导出 SQL。", "warn"); return; }
  const ok = await confirmInline("生成当前 SQLite 的一致性快照并下载？不会修改现有数据。", "生成并下载");
  if (!ok) return;
  try {
    await dbDownload(`/api/admin/database/backup?connection=${encodeURIComponent(d.conn)}`, { method: "POST" }, "database-backup.db");
  } catch (e) { dbSetStatus("dbOpsHint", "备份失败：" + e.message, "bad"); }
}

async function dbExportSql(engine) {
  const d = dbState();
  const ok = await confirmInline(`把当前工作台数据导出成 ${engine === "mysql" ? "MySQL" : "PostgreSQL"} 的 .sql 脚本？文件会下载到浏览器。`, "导出脚本");
  if (!ok) return;
  try {
    await dbDownload(`/api/admin/database/export-sql?connection=local&target_engine=${engine}`, { method: "POST" }, `workbench-${engine}.sql`);
  } catch (e) { dbSetStatus("dbOpsHint", "导出失败：" + e.message, "bad"); }
}

async function dbExportCsv() {
  const d = dbState();
  if (!d.table) return;
  try {
    await dbDownload(`/api/admin/database/table/${encodeURIComponent(d.table)}/export.csv?connection=${encodeURIComponent(d.conn)}`, {}, d.table + ".csv");
  } catch (e) { uiToast("导出失败：" + e.message, "bad"); }
}

async function dbVacuum() {
  const d = dbState();
  if (d.conn !== "local") { uiToast("空间整理只对 SQLite 开放。", "warn"); return; }
  const ok = await confirmInline("VACUUM 会重建 SQLite 文件并释放空闲页，期间不要关闭工作台。继续？", "开始整理");
  if (!ok) return;
  try {
    const res = await api("/api/admin/database/vacuum", { method: "POST" });
    dbSetStatus("dbOpsHint", `整理完成：${dbFmtBytes(res.before)} → ${dbFmtBytes(res.after)}，释放 ${dbFmtBytes(res.saved)}。`, "ok");
    uiToast("空间整理完成", "ok");
    dbLoadOverview().catch(() => {});
    dbLoadHealth().catch(() => {});
  } catch (e) { dbSetStatus("dbOpsHint", "整理失败：" + e.message, "bad"); }
}

/* ---------------------------------------------------------------- 一键迁移 */
function dbFillMigrateTargets() {
  const d = dbState();
  const sel = $("dbMigrateTarget");
  if (!sel) return;
  const conns = d.connections || [];
  const old = d.migrateConn || sel.value;
  sel.innerHTML = conns.length
    ? conns.map((c) => `<option value="${esc(c.id)}">${esc(c.name)} · ${esc(dbTargetText(c))}</option>`).join("")
    : `<option value="">先添加一个外部连接</option>`;
  if (conns.length) {
    sel.value = conns.some((c) => c.id === old) ? old : conns[0].id;
    d.migrateConn = sel.value;
  } else {
    d.migrateConn = "";
  }
}

function dbRenderPreflight(res) {
  const box = $("dbPreflightResult");
  if (!box) return;
  if (!res.ok) { box.innerHTML = `<div class="db-sql-error">检查未通过：${esc(res.error || "未知错误")}</div>`; return; }
  const conflicts = res.conflicts || [];
  const warnings = res.warnings || [];
  box.innerHTML = `<div class="db-sql-notice ${conflicts.length ? "" : ""}">
    <b>${res.ready ? "可以开始迁移。" : "目标库有同名表，不能直接迁移。"}</b>
    目标：${esc(res.engine_label || res.engine)} / ${esc(res.database || "")}；源库 ${res.tables} 张表、约 ${dbNum(res.rows)} 行。
    ${conflicts.length ? `<br>冲突表：${conflicts.map(esc).join("、")}${res.overwrite ? "（已选择覆盖）" : "（请勾选“覆盖同名表”）"}` : ""}
    ${warnings.length ? `<br>提醒：${warnings.map(esc).join("；")}` : ""}
  </div>`;
}

async function dbPreflight() {
  const d = dbState();
  const id = $("dbMigrateTarget").value;
  if (!id) { dbSetStatus("dbMigrateStatus", "先在“外部连接”里添加目标数据库。", "bad"); return; }
  d.migrateConn = id;
  $("dbPreflight").disabled = true;
  dbSetStatus("dbMigrateStatus", "正在检查目标库…");
  try {
    const res = await api("/api/admin/database/migrate/preflight", {
      method: "POST",
      body: JSON.stringify({ connection_id: id, create_database: $("dbMigrateCreate").checked, overwrite: $("dbMigrateOverwrite").checked }),
    });
    dbRenderPreflight(res);
    dbSetStatus("dbMigrateStatus", res.message || (res.ready ? "检查通过" : "检查未通过"), res.ok && res.ready ? "ok" : "bad");
  } catch (e) {
    dbSetStatus("dbMigrateStatus", "检查失败：" + e.message, "bad");
    $("dbPreflightResult").innerHTML = `<div class="db-sql-error">检查失败：${esc(e.message)}</div>`;
  } finally { $("dbPreflight").disabled = false; }
}

async function dbStartMigrate() {
  const d = dbState();
  const id = $("dbMigrateTarget").value;
  if (!id) { dbSetStatus("dbMigrateStatus", "先在“外部连接”里添加目标数据库。", "bad"); return; }
  const overwrite = $("dbMigrateOverwrite").checked;
  if (overwrite) {
    const ok = await confirmInline("覆盖会先清理目标库里的同名表，再写入当前数据。确认继续？", "确认覆盖迁移");
    if (!ok) return;
  }
  d.migrateConn = id;
  $("dbStartMigrate").disabled = true;
  $("dbMigrateVerifiedWrap").hidden = true;
  $("dbMigrateBrowse").hidden = true;
  $("dbMigrateProgress").hidden = false;
  $("dbMigrateBar").style.width = "0%";
  $("dbMigrateText").textContent = "正在启动迁移…";
  $("dbMigrateLog").innerHTML = "";
  dbSetStatus("dbMigrateStatus", "");
  dbRenderPreflight({ ok: true, ready: true, tables: 0, rows: 0, warnings: [], message: "" });
  try {
    const job = await api("/api/admin/database/migrate", {
      method: "POST",
      body: JSON.stringify({ connection_id: id, create_database: $("dbMigrateCreate").checked, overwrite }),
    });
    d.lastJobId = job.id;
    dbWatchJob(job.id);
  } catch (e) {
    $("dbStartMigrate").disabled = false;
    dbSetStatus("dbMigrateStatus", "启动失败：" + e.message, "bad");
  }
}

function dbRenderJob(job) {
  const pct = Number(job.progress || 0);
  $("dbMigrateProgress").hidden = false;
  $("dbMigrateBar").style.width = pct + "%";
  $("dbMigrateText").textContent = `${job.message || ""} · ${pct}%`;
  const logs = job.logs || [];
  $("dbMigrateLog").innerHTML = logs.map((l) => `<div>[${l.pct}%] ${esc(l.message)}</div>`).join("");
  if (job.status === "running") return;
  $("dbStartMigrate").disabled = false;
  if (job.status === "ok") {
    dbSetStatus("dbMigrateStatus", "迁移完成，所有表行数校验通过。", "ok");
    uiToast("迁移完成", "ok");
  } else if (job.status === "error") {
    dbSetStatus("dbMigrateStatus", job.error || job.message || "迁移失败", "bad");
  } else {
    dbSetStatus("dbMigrateStatus", job.message || "迁移完成，但部分表行数不一致，请检查。", "bad");
  }
  const verified = (job.result && job.result.verified) || {};
  const names = Object.keys(verified).sort();
  if (names.length) {
    $("dbMigrateVerified").innerHTML = names.map((n) => {
      const v = verified[n];
      return `<tr><td><b>${esc(n)}</b></td><td>${dbNum(v.expected)}</td><td>${dbNum(v.actual)}</td><td><span class="badge ${v.ok ? "good" : "bad"}">${v.ok ? "一致" : "不一致"}</span></td></tr>`;
    }).join("");
    $("dbMigrateVerifiedWrap").hidden = false;
  }
  if (job.status === "ok" || job.status === "error") {
    if (job.status === "ok") $("dbMigrateBrowse").hidden = false;
    else $("dbMigrateBrowse").hidden = true;
    dbLoadMigrationHistory().catch(() => {});
    dbLoadConnections().catch(() => {});
  }
}

async function dbWatchJob(id) {
  clearTimeout(dbState().jobTimer);
  const tick = async () => {
    try {
      const job = await api("/api/admin/database/migrate/" + encodeURIComponent(id));
      dbRenderJob(job);
      if (job.status === "running") dbState().jobTimer = setTimeout(tick, 1200);
    } catch (e) {
      $("dbStartMigrate").disabled = false;
      dbSetStatus("dbMigrateStatus", "读取进度失败：" + e.message, "bad");
    }
  };
  await tick();
}

async function dbLoadMigrationHistory() {
  const box = $("dbHistoryRows");
  if (!box) return;
  try {
    const res = await api("/api/admin/database/migration-history");
    const rows = res.history || [];
    box.innerHTML = rows.length ? rows.map((h) => `<tr>
      <td>${h.ts ? dbFmtTime(h.ts) : "—"}</td>
      <td class="mono" style="max-width:260px">${esc(h.target || "")}</td>
      <td>${esc(h.engine || "")}</td>
      <td>${dbNum(h.tables)}</td>
      <td>${dbNum(h.rows)}</td>
      <td><span class="badge ${h.ok ? "good" : "bad"}">${h.ok ? "成功" : "有差异"}</span></td>
      <td>${dbNum(h.warnings)} 条</td>
    </tr>`).join("") : `<tr><td class="db-empty" colspan="7">还没有迁移记录。</td></tr>`;
  } catch (e) { box.innerHTML = `<tr><td class="db-empty" colspan="7">读取迁移历史失败：${esc(e.message)}</td></tr>`; }
}

function dbSwitchView(name, refresh = true) {
  const d = dbState();
  d.view = name;
  document.querySelectorAll(".db-subtab").forEach((b) => b.classList.toggle("active", b.dataset.dbtab === name));
  document.querySelectorAll(".db-view").forEach((v) => { v.hidden = v.id !== "dbView-" + name; });
  if (!refresh) return;
  if (name === "connections") { dbLoadConnections().catch(() => {}); return; }
  if (name === "migrate") { dbLoadConnections().catch(() => {}); dbLoadMigrationHistory().catch(() => {}); return; }
  if (name === "browse") { dbLoadBrowse().catch((e) => uiToast(e.message, "bad")); return; }
}

/* ---------------------------------------------------------------- 数据库页面事件 */
document.addEventListener("click", async (ev) => {
  if (!S.db || S.tab !== "database") return;
  const d = dbState();
  const el = ev.target;
  const sub = el.closest("[data-dbtab]");
  if (sub) { dbSwitchView(sub.dataset.dbtab); return; }
  const tableBtn = el.closest("[data-dbtable]");
  if (tableBtn) { await dbSelectTable(tableBtn.dataset.dbtable); return; }
  const sortTh = el.closest("[data-dbsort]");
  if (sortTh) {
    const name = sortTh.dataset.dbsort;
    if (d.sort === name) d.order = d.order === "asc" ? "desc" : "asc";
    else { d.sort = name; d.order = "asc"; }
    d.page = 0;
    await dbLoadRows();
    return;
  }
  const edit = el.closest("[data-dbedit]");
  if (edit) { try { await dbOpenRowModal("edit", edit.dataset.dbedit); } catch (e) { uiToast(e.message, "bad"); } return; }
  const del = el.closest("[data-dbdel]");
  if (del) { await dbDeleteRow(del.dataset.dbdel); return; }
  const colRemove = el.closest(".db-col-remove");
  if (colRemove) { colRemove.closest(".db-col-row").remove(); return; }
  const browseConn = el.closest("[data-dbconnbrowse]");
  if (browseConn) {
    d.conn = browseConn.dataset.dbconnbrowse;
    d.table = "";
    dbFillConnSelects();
    dbSwitchView("browse");
    dbLoadOverview().catch(() => {});
    return;
  }
  const testConn = el.closest("[data-dbconntest]");
  if (testConn) { await dbTestConn(testConn.dataset.dbconntest); return; }
  const editConn = el.closest("[data-dbconnedit]");
  if (editConn) { dbEditConn(editConn.dataset.dbconnedit); return; }
  const delConn = el.closest("[data-dbconndel]");
  if (delConn) { await dbDeleteConn(delConn.dataset.dbconndel); return; }
  const sample = el.closest("[data-dbsample]");
  if (sample) { $("dbSqlText").value = sample.dataset.dbsample; $("dbSqlText").focus(); return; }
  if (el.id === "dbRefreshAll") { await loadDatabasePage(); return; }
  if (el.id === "dbRowSearchBtn") {
    d.search = $("dbRowSearch").value.trim(); d.page = 0; await dbLoadRows(); return;
  }
  if (el.id === "dbPrevPage") { if (d.page > 0) { d.page--; await dbLoadRows(); } return; }
  if (el.id === "dbNextPage") { if ((d.page + 1) * d.pageSize < d.total) { d.page++; await dbLoadRows(); } return; }
  if (el.id === "dbExportCsv") { await dbExportCsv(); return; }
  if (el.id === "dbNewRow") { try { await dbOpenRowModal("create"); } catch (e) { uiToast(e.message, "bad"); } return; }
  if (el.id === "dbCreateTableBtn") { dbOpenCreateTable(); return; }
  if (el.id === "dbTableRenameBtn") { dbOpenTableAction("rename"); return; }
  if (el.id === "dbTableTruncateBtn") { dbOpenTableAction("truncate"); return; }
  if (el.id === "dbTableDropBtn") { dbOpenTableAction("drop"); return; }
  if (el.id === "dbTableActionClose" || el.id === "dbTableActionCancel") { dbCloseTableAction(); return; }
  if (el.id === "dbTableActionConfirm") { await dbSubmitTableAction(); return; }
  if (el.id === "dbCreateTableClose" || el.id === "dbCreateTableCancel") { dbCloseCreateTable(); return; }
  if (el.id === "dbCreateTableSubmit") { await dbSubmitCreateTable(); return; }
  if (el.id === "dbAddColumnBtn") { dbNewColumnRow({ type: "TEXT", nullable: true }); return; }
  if (el.closest("[data-dbfixfk]")) { await dbRepairForeignKey(); return; }
  if (el.id === "dbHealthBtn") { await dbLoadHealth(); return; }
  if (el.id === "dbBackupBtn") { await dbBackup(); return; }
  if (el.id === "dbExportMysql") { await dbExportSql("mysql"); return; }
  if (el.id === "dbExportPg") { await dbExportSql("postgres"); return; }
  if (el.id === "dbVacuumBtn") { await dbVacuum(); return; }
  if (el.id === "dbRunSql") { await dbRunSql(); return; }
  if (el.id === "dbConnRefresh") { await dbLoadConnections(); return; }
  if (el.id === "dbConnReset") { dbResetConnForm(); return; }
  if (el.id === "dbConnTestNew") { await dbSaveConn(true); return; }
  if (el.id === "dbParseUrl") { await dbParseConnUrl(); return; }
  if (el.id === "dbPreflight") { await dbPreflight(); return; }
  if (el.id === "dbStartMigrate") { await dbStartMigrate(); return; }
  if (el.id === "dbMigrateBrowse") {
    d.conn = d.migrateConn || $("dbMigrateTarget").value;
    d.table = "";
    dbFillConnSelects();
    dbSwitchView("browse");
    dbLoadOverview().catch(() => {});
    return;
  }
  if (el.id === "dbModalClose" || el.id === "dbModalCancel") { dbCloseRowModal(); return; }
  if (el.id === "dbModalSave") { await dbSaveRow(); return; }
  if (el.id === "dbModalDelete") {
    if (!d.modal) return;
    const ok = await confirmInline("确定删除这一行？删除后不能撤销。", "确认删除");
    if (!ok) return;
    await dbDeleteRow(d.modal.key);
    return;
  }
});

document.addEventListener("change", (ev) => {
  if (!S.db || S.tab !== "database") return;
  const d = dbState();
  const colRow = ev.target.closest(".db-col-row");
  if (colRow) {
    if (ev.target.matches("[data-col-pk]") && ev.target.checked) {
      document.querySelectorAll("#dbNewColumns [data-col-pk]").forEach((box) => {
        if (box !== ev.target) { box.checked = false; dbSyncColumnRow(box.closest(".db-col-row")); }
      });
    }
    dbSyncColumnRow(colRow);
    return;
  }
  if (ev.target.id === "dbConnSelect") {
    d.conn = ev.target.value || "local"; d.table = ""; d.search = ""; d.page = 0;
    dbLoadOverview().catch(() => {});
    dbLoadBrowse().catch((e) => uiToast(e.message, "bad"));
    return;
  }
  if (ev.target.id === "dbSqlConn") { d.sqlConn = ev.target.value || "local"; return; }
  if (ev.target.id === "dbConnEngine") { dbEngineChange(); return; }
  if (ev.target.id === "dbMigrateTarget") { d.migrateConn = ev.target.value; $("dbPreflightResult").innerHTML = ""; return; }
});

document.addEventListener("input", (ev) => {
  if (!S.db || S.tab !== "database") return;
  if (ev.target.id === "dbTableFilter") {
    dbState().filter = ev.target.value.trim();
    dbRenderTableList();
    return;
  }
});

document.addEventListener("keydown", (ev) => {
  if (!S.db || S.tab !== "database") return;
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.target.id === "dbRowSearch") {
    ev.preventDefault();
    $("dbRowSearchBtn").click();
    return;
  }
  if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.target.id === "dbTableActionInput") {
    ev.preventDefault();
    $("dbTableActionConfirm").click();
    return;
  }
  if (ev.key === "Escape" && !$("dbRowModal").hidden) { dbCloseRowModal(); }
  if (ev.key === "Escape" && !$("dbTableActionModal").hidden) { dbCloseTableAction(); }
  if (ev.key === "Escape" && !$("dbCreateTableModal").hidden) { dbCloseCreateTable(); }
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && ev.target.id === "dbSqlText") {
    ev.preventDefault();
    $("dbRunSql").click();
  }
});

document.addEventListener("submit", async (ev) => {
  if (ev.target.id !== "dbConnForm") return;
  ev.preventDefault();
  await dbSaveConn(false);
});


