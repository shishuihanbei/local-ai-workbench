/* 用户端 · 全局事件分发 bindEvents | 原 app.js 第 3262–3645 行 */
"use strict";
  /* ------------------------------------------------------------------ 事件 */
  function bindEvents() {
    document.addEventListener("click", (ev) => {
      const img = ev.target.closest("[data-img-preview]");
      if (img) openImagePreview(img.dataset.imgPreview, img.dataset.imgName);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeImagePreview();
    });
    $("#authForm").addEventListener("submit", submitAuth);
    $("#otpForm").addEventListener("submit", submitOtp);
    $("#otpSend").addEventListener("click", sendOtp);
    $$("[data-authmode]").forEach((b) => b.addEventListener("click", () => setAuthMode(b.dataset.authmode)));
    $$("[data-authmethod]").forEach((b) => b.addEventListener("click", () => setAuthMethod(b.dataset.authmethod)));
    $("#toConsole").addEventListener("click", () => { window.location.href = "/console/"; });
    document.querySelector("#consoleEntry")?.addEventListener("click", () => { window.location.href = "/console/"; });

    $("#newChatBtn").addEventListener("click", newChat);
    $("#allFeaturesBtn")?.addEventListener("click", openFeatureCenter);
    $("#featureCenter")?.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-close-feature-center]")) {
        closeFeatureCenter();
        return;
      }
      const item = ev.target.closest("[data-feature-run]");
      if (!item) return;
      const meta = FEATURE_CENTER_META[item.dataset.featureRun];
      closeFeatureCenter();
      if (!meta) return;
      try { meta.run(); } catch (e) { toast(e.message || "打开失败"); }
    });
    $("#welcomeAllWorkbench")?.addEventListener("click", () => openWorkbench("overview"));
    $("#welcomeContinue")?.addEventListener("click", (ev) => {
      const card = ev.target.closest("[data-wb-home]");
      if (!card) return;
      openWbHome(card.dataset.wbHome);
    });
    $("#sideLibraryBtn")?.addEventListener("click", () => openSettings("library"));
    $("#sideScheduleBtn")?.addEventListener("click", () => openWorkbench("tasks"));
    $("#sideFilesBtn")?.addEventListener("click", () => openWorkbench("files"));
    $("#attachBtn").addEventListener("click", () => $("#fileInput").click());
    $("#fileInput").addEventListener("change", (ev) => uploadFiles(ev.target.files));
    $("#composer").addEventListener("paste", (ev) => {
      const files = [...(ev.clipboardData?.items || [])]
        .filter((x) => x.kind === "file" && x.type.startsWith("image/"))
        .map((x) => x.getAsFile())
        .filter(Boolean);
      if (!files.length) return;
      ev.preventDefault();
      uploadFiles(files);
    });
    $("#composer").addEventListener("dragover", (ev) => {
      if (!ev.dataTransfer || ![...ev.dataTransfer.types].includes("Files")) return;
      ev.preventDefault();
      $("#composer").classList.add("dragover");
    });
    $("#composer").addEventListener("dragleave", (ev) => {
      if (!ev.relatedTarget || !$("#composer").contains(ev.relatedTarget)) $("#composer").classList.remove("dragover");
    });
    $("#composer").addEventListener("drop", (ev) => {
      if (!ev.dataTransfer || !ev.dataTransfer.files.length) return;
      ev.preventDefault();
      $("#composer").classList.remove("dragover");
      uploadFiles(ev.dataTransfer.files);
    });
    $("#messageInput").addEventListener("paste", (ev) => {
      const files = [...((ev.clipboardData && ev.clipboardData.files) || [])];
      if (!files.length) return;
      ev.preventDefault();
      uploadFiles(files);
    });
    $("#attachList").addEventListener("click", (ev) => {
      const rm = ev.target.closest("[data-remove-att]");
      if (rm) removeAttachment(rm.dataset.removeAtt);
    });
    $("#skillBtn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      setSkillMenu($("#skillMenu").hidden);
      if (!$("#skillMenu").hidden) setLibMenu(false);
    });
    $("#libBtn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      openLibMenu();
    });
    $("#libPickerSearch").addEventListener("input", () => {
      S.libraryQuery = $("#libPickerSearch").value;
      renderLibPicker();
    });
    $("#libPickerFolder").addEventListener("change", renderLibPicker);
    $("#libPickerTag").addEventListener("change", renderLibPicker);
    $("#libPickerList").addEventListener("change", (ev) => {
      const box = ev.target.closest("[data-lib-pick]");
      if (box) toggleLibDoc(box.dataset.libPick, box.checked);
    });
    $("#libClear").addEventListener("click", (ev) => {
      ev.stopPropagation();
      clearLibSelection();
    });
    $("#webBtn").addEventListener("click", () => {
      setWeb(!S.web);
      toast(S.web ? "联网已开启：发送时先搜索网页" : "联网已关闭");
    });
    $("#agentBtn").addEventListener("click", () => {
      setAgentMode(!S.agentMode);
      toast(S.agentMode ? "通用助手已开启：自动检索资料后再回答" : "通用助手已关闭：本轮按普通对话生成");
    });
    $("#deepBtn").addEventListener("click", () => {
      setDeep(!S.deep);
      toast(S.deep ? "深度模式已开启：复杂任务优先交给云端，未接入或超预算时留在本地" : "深度模式已关闭：恢复本地优先");
    });
    $("#formatSelect").addEventListener("change", (ev) => {
      setOutputFormat(ev.target.value);
      ev.target.blur();
    });
    $("#skillList").addEventListener("click", (ev) => {
      const item = ev.target.closest("[data-skill-id]");
      if (item) setSkill(item.dataset.skillId);
    });
    document.addEventListener("click", (ev) => {
      const preview = ev.target.closest("[data-preview-file]");
      if (preview) {
        openFilePreview(preview.dataset.previewFile, preview.dataset.fileName || "");
        return;
      }
      if (ev.target.closest("[data-close-preview]")) {
        closeFilePreview();
        return;
      }
      if (!ev.target.closest(".skill-wrap")) setSkillMenu(false);
      if (!ev.target.closest("#libBtn") && !ev.target.closest("#libMenu")) setLibMenu(false);
    });
    $("#refreshConv").addEventListener("click", () => loadConversations($("#convSearch").value.trim()));
    $("#convSearch").addEventListener("input", () => {
      clearTimeout(S.searchTimer);
      S.searchTimer = setTimeout(() => loadConversations($("#convSearch").value.trim()), 260);
    });
    $("#convList").addEventListener("click", (ev) => {
      if (ev.target.closest(".conv-rename")) return;
      const rename = ev.target.closest("[data-rnamecid]");
      if (rename) { ev.stopPropagation(); renameConversation(rename.dataset.rnamecid); return; }
      const del = ev.target.closest("[data-delcid]");
      if (del) {
        ev.stopPropagation();
        if (armDeleteButton(del)) deleteConversation(del.dataset.delcid);
        return;
      }
      const item = ev.target.closest("[data-cid]");
      if (item) openConversation(item.dataset.cid);
    });
    $("#convList").addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" || ev.target.closest(".conv-rename")) return;
      const item = ev.target.closest("[data-cid]");
      if (item) openConversation(item.dataset.cid);
    });

    $("#userChip").addEventListener("click", () => openSettings("account"));
    $("#closeSidebar").addEventListener("click", closeSidebar);
    $("#openSidebar").addEventListener("click", openSidebar);
    $("#scrim").addEventListener("click", closeSidebar);
    $$("[data-close-settings]").forEach((el) => el.addEventListener("click", closeSettings));

    $("#messageInput").addEventListener("input", autoResizeInput);
    $("#messageInput").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
        ev.preventDefault();
        sendMessage($("#messageInput").value);
      }
    });
    $("#sendBtn").addEventListener("click", () => sendMessage($("#messageInput").value));
    $("#stopBtn").addEventListener("click", stopStream);
    $("#suggestions").addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-suggest]");
      if (!b) return;
      $("#messageInput").value = b.dataset.suggest;
      if (b.hasAttribute("data-suggest-format")) setOutputFormat(b.dataset.suggestFormat || "", true);
      autoResizeInput();
      $("#messageInput").focus();
    });

    $("#messages").addEventListener("click", (ev) => {
      const codeCopy = ev.target.closest("[data-copy-code]");
      if (codeCopy) {
        const card = codeCopy.closest(".md-code");
        const code = card ? $("code", card)?.textContent || "" : "";
        copyText(code, codeCopy);
        return;
      }
      const copy = ev.target.closest("[data-copy-text]");
      if (copy) {
        const actions = copy.closest(".msg-actions");
        const text = actions ? actions.dataset.content : "";
        copyText(text, copy);
        return;
      }
      if (ev.target.closest("[data-regen]")) regenerate();
    });

    $("#modelSelect").addEventListener("change", () => {
      const key = $("#modelSelect").value;
      setModel(key);
      ensureModelLoaded(key).catch((e) => toast(e.message || "模型加载失败"));
    });

    $$("#drawerTabs button").forEach((b) => b.addEventListener("click", () => selectDrawerTab(b.dataset.dtab)));
    $("#myKbAdd").addEventListener("click", addMyKbText);
    $("#myKbFile").addEventListener("change", () => uploadMyKb($("#myKbFile").files));
    $("#myKbSearchBtn").addEventListener("click", searchMyKb);
    $("#myKbSearch").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); searchMyKb(); }
    });
    $("#myKbList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-kb-del]");
      if (btn) deleteMyKb(btn.dataset.kbDel, btn);
    });
    $("#myKbToggle").addEventListener("change", async () => {
      const on = $("#myKbToggle").checked;
      await saveMyKbSettings({ personal_enabled: on }).catch(() => {});
    });
    $("#myKbUsePublic").addEventListener("change", async () => {
      await saveMyKbSettings({ use_public: $("#myKbUsePublic").checked }).catch(() => {});
    });
    $("#myKbUsePersonal").addEventListener("change", async () => {
      await saveMyKbSettings({ use_personal: $("#myKbUsePersonal").checked }).catch(() => {});
    });
    $("#myLibAdd").addEventListener("click", addMyLibText);
    $("#myLibFile").addEventListener("change", () => uploadMyLib($("#myLibFile").files));
    $("#myLibFolderFilter").addEventListener("change", renderMyLibDocs);
    $("#myLibTagFilter").addEventListener("change", renderMyLibDocs);
    $("#myLibSearchBtn").addEventListener("click", searchMyLib);
    $("#myLibSearch").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); searchMyLib(); }
    });
    $("#myLibResults").addEventListener("click", (ev) => {
      const hit = ev.target.closest("[data-lib-hit]");
      if (hit) openMyLibDoc(hit.dataset.libHit).catch((e) => toast(e.message));
    });
    $("#myLibList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-lib-del]");
      if (btn) { deleteMyLib(btn.dataset.libDel, btn); return; }
      const org = ev.target.closest("[data-lib-org]");
      if (org) { openMyLibOrg(org.dataset.libOrg); return; }
      const open = ev.target.closest("[data-lib-open]");
      if (open) openMyLibDoc(open.dataset.libOpen).catch((e) => toast(e.message));
    });
    $("#myLibOrgSave").addEventListener("click", saveMyLibOrg);
    $("#myLibOrgCancel").addEventListener("click", closeMyLibOrg);
    $("#myLibOrgClose").addEventListener("click", closeMyLibOrg);
    $("#myLibViewClose").addEventListener("click", () => { $("#myLibView").hidden = true; });
    $("#myLibToggle").addEventListener("change", async () => {
      await saveMyLibSettings({ personal_enabled: $("#myLibToggle").checked }).catch(() => {});
    });
    $("#myLibUseGlobal").addEventListener("change", async () => {
      await saveMyLibSettings({ use_global: $("#myLibUseGlobal").checked }).catch(() => {});
    });
    $("#myLibUsePersonal").addEventListener("change", async () => {
      await saveMyLibSettings({ use_personal: $("#myLibUsePersonal").checked }).catch(() => {});
    });
    $("#myMemToggle").addEventListener("change", () => toggleMyMemory($("#myMemToggle").checked));
    $("#myMemAdd").addEventListener("click", addMyMemory);
    $("#myMemClear").addEventListener("click", () => clearMyMemory($("#myMemClear")));
    $("#myMemList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-mem-del]");
      if (btn) deleteMyMemory(btn.dataset.memDel, btn);
    });
    $("#pwForm").addEventListener("submit", changePassword);
    $("#identityList").addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-bind]");
      if (btn) openBind(btn.dataset.bind);
    });
    $("#bindForm").addEventListener("submit", submitBind);
    $("#bindSend").addEventListener("click", sendBindCode);
    $("#bindCancel").addEventListener("click", closeBind);
    $("#revokeOthers").addEventListener("click", revokeOthers);
    $("#logoutBtn").addEventListener("click", logout);

    $("#keyName").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); createApiKey(); }
    });
    $("#createKeyBtn").addEventListener("click", createApiKey);
    $("#hideSecret").addEventListener("click", () => {
      $("#secretBox").hidden = true;
      $("#secretValue").value = "";
    });
    $("#copySecret").addEventListener("click", () => {
      copyText($("#secretValue").dataset.copy || $("#secretValue").value, $("#copySecret"));
    });
    $("#dpanel-api").addEventListener("click", (ev) => {
      const copy = ev.target.closest("[data-copy-value]");
      if (copy) { copyText(copy.dataset.copyValue, copy); return; }
      if (ev.target.closest("#copyBase")) {
        const base = S.apiCtx && S.apiCtx.api ? S.apiCtx.api.recommended_base : "";
        copyText(base, ev.target.closest("button"));
        return;
      }
      const rev = ev.target.closest("[data-revoke-key]");
      if (rev) revokeKey(rev.dataset.revokeKey, rev);
      const cp = ev.target.closest("[data-copy-target]");
      if (cp) copyText(S.apiDocs[cp.dataset.copyTarget] || "", cp);
    });

    $("#setTemp").addEventListener("input", () => { $("#tempValue").textContent = Number($("#setTemp").value).toFixed(1); });
    $("#saveChatPrefs").addEventListener("click", saveChatPrefs);
    $("#resetChatPrefs").addEventListener("click", resetChatPrefs);

    $$("#themeGrid button").forEach((b) => b.addEventListener("click", () => {
      const mode = b.dataset.themeChoice;
      saveAppearance({ theme: mode });
      applyTheme(mode);
      $$("#themeGrid button").forEach((x) => x.classList.toggle("active", x === b));
    }));
    $("#fontScale").addEventListener("input", () => {
      const n = Number($("#fontScale").value);
      applyFontScale(n);
      $("#fontScaleValue").textContent = `${n}%`;
      saveAppearance({ fontScale: n });
    });

    $("#exportData").addEventListener("click", exportData);
    $("#clearAllData").addEventListener("click", (ev) => {
      const btn = ev.currentTarget;
      if (btn.dataset.armed === "1") {
        btn.dataset.armed = "";
        btn.classList.remove("armed");
        btn.innerHTML = `<svg><use href="#i-trash"/></svg>清空`;
        clearAllConversations();
        return;
      }
      btn.dataset.armed = "1";
      btn.classList.add("armed");
      btn.textContent = "再点一次清空全部";
      clearTimeout(clearAllConversations._t);
      clearAllConversations._t = setTimeout(() => {
        btn.dataset.armed = "";
        btn.classList.remove("armed");
        btn.innerHTML = `<svg><use href="#i-trash"/></svg>清空`;
      }, 3200);
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        if (!$("#featureCenter")?.hidden) closeFeatureCenter();
        else if (!$("#skillMenu").hidden) setSkillMenu(false);
        else if (!$("#settingsDrawer").hidden) closeSettings();
        else if (window.innerWidth <= 900 && $("#appView").classList.contains("side-open")) closeSidebar();
      }
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth > 900) closeSidebar();
    });
  }

  async function copyText(text, btn) {
    if (!text) return toast("没有可复制的内容");
    const done = () => {
      toast("已复制");
      if (btn) {
        const old = btn.dataset.label || btn.innerHTML;
        btn.dataset.label = old;
        btn.innerHTML = `<span class="toast-mini">已复制</span>`;
        setTimeout(() => { btn.innerHTML = old; }, 1100);
      }
    };
    const legacy = () => {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch {}
      area.remove();
      if (ok) done();
      else toast("复制失败，请手动选择文本");
      return ok;
    };
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await Promise.race([
        navigator.clipboard.writeText(text),
        new Promise((_, reject) => setTimeout(() => reject(new Error("clipboard timeout")), 1200)),
      ]);
      done();
    } catch {
      legacy();
    }
  }

  // 监听系统主题变化，只在“跟随系统”时即时生效
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      let a = {};
      try { a = JSON.parse(localStorage.getItem("wb.appearance") || "{}"); } catch {}
      if ((a.theme || "light") === "system") applyTheme("system");
    };
    if (mq.addEventListener) mq.addEventListener("change", handler);
    else if (mq.addListener) mq.addListener(handler);
  }

  window.addEventListener("popstate", () => {
    if (!S.user || $("#appView").hidden) return;
    const cid = chatIdFromUrl();
    if (cid) openConversation(cid, false);
    else newChat(false);
  });

