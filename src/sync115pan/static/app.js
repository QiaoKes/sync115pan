const settingsModal = document.getElementById("settings-modal");
const cloudPickerModal = document.getElementById("cloud-picker-modal");
const formMessage = document.getElementById("form-message");
const settingsMessage = document.getElementById("settings-message");
const cloudMessage = document.getElementById("cloud-message");
const cloudCurrentPath = document.getElementById("cloud-current-path");
const cloudList = document.getElementById("cloud-list");
const cloudRootIdInput = document.getElementById("cloud_root_id");
const cloudPathDisplay = document.getElementById("cloud_path_display");
const localPathInput = document.getElementById("local_path");
const recentLogsList = document.getElementById("recent-logs-list");
const runFullSyncButton = document.getElementById("run-full-sync-btn");

let cloudStack = [{ id: "0", name: "根目录" }];

function setMessage(node, text, isError = true) {
  if (!node) return;
  node.textContent = text || "";
  node.style.color = isError ? "var(--alert)" : "var(--accent)";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `请求失败: ${response.status}`);
  }
  return data;
}

function currentCloudNode() {
  return cloudStack[cloudStack.length - 1];
}

function currentCloudPathText() {
  if (cloudStack.length <= 1) {
    return "/";
  }
  return cloudStack.slice(1).map((item) => item.name).join(" / ");
}

function collectConfigPayload() {
  return {
    auth_value: document.getElementById("settings-auth-value").value.trim(),
    local_path: localPathInput.value.trim(),
    cloud_root_id: cloudRootIdInput.value.trim(),
    cloud_path: cloudPathDisplay.value.trim(),
    watch_enabled: document.getElementById("watch_enabled").checked,
    schedule_cron: document.getElementById("schedule_cron").value.trim(),
    watch_mode: document.getElementById("watch_mode").value,
    debounce_seconds: Number(document.getElementById("debounce_seconds").value),
    stability_check_seconds: Number(document.getElementById("stability_check_seconds").value),
    max_instant_failures: Number(document.getElementById("max_instant_failures").value),
    retry_interval_seconds: Number(document.getElementById("retry_interval_seconds").value),
  };
}

function updateRunButtonState() {
  if (!runFullSyncButton) {
    return;
  }
  const ready = Boolean(localPathInput.value.trim() && cloudRootIdInput.value.trim());
  runFullSyncButton.disabled = !ready;
}

async function saveConfig(successText) {
  const payload = collectConfigPayload();
  if (!payload.local_path || !payload.cloud_root_id) {
    throw new Error("请先完整选择本地目录和云盘目录。");
  }
  await requestJson("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  window.sync115pan.authConfigured = Boolean(payload.auth_value);
  updateRunButtonState();
  if (successText) {
    setMessage(formMessage, successText, false);
  }
}

function renderLogs(logs) {
  if (!recentLogsList) {
    return;
  }
  if (!logs.length) {
    recentLogsList.innerHTML = "<li>暂无日志</li>";
    return;
  }
  recentLogsList.innerHTML = logs
    .map(
      (log) => `
        <li>
          <span><strong>${String(log.level || "").toUpperCase()}</strong> ${log.created_at} ${log.message}</span>
        </li>
      `
    )
    .join("");
}

function renderRuntime(runtime) {
  const sync = runtime.sync || {};
  document.getElementById("runtime-status").textContent = sync.status_label || sync.status || "空闲";
  document.getElementById("runtime-job").textContent = sync.current_job_label || "待命";
  document.getElementById("runtime-watch-mode").textContent = runtime.watch_mode_label || runtime.watch_mode || "自动";
  document.getElementById("runtime-watcher").textContent = runtime.watcher_running ? "运行中" : "未启动";
  document.getElementById("runtime-last-full-sync").textContent = sync.last_full_sync_at || "暂无";
  document.getElementById("runtime-pending").textContent = String(sync.pending_scope_count || 0);
  document.getElementById("runtime-error").textContent = sync.last_error || "暂无";
}

async function refreshRuntime() {
  const runtime = await requestJson("/api/runtime");
  renderRuntime(runtime);
}

async function loadCloudDirectories(parentId) {
  setMessage(cloudMessage, "");
  cloudCurrentPath.textContent = `${currentCloudPathText()} · 正在加载...`;
  cloudList.innerHTML = "";
  try {
    const data = await requestJson(`/api/cloud/directories?parent_id=${parentId}`);
    cloudCurrentPath.textContent = currentCloudPathText();
    if (!data.directories.length) {
      cloudList.innerHTML = `<div class="empty-state">当前目录下没有子文件夹，可以直接选择当前目录。</div>`;
      return;
    }
    cloudList.innerHTML = data.directories
      .map(
        (item) => `
          <div class="cloud-item">
            <div>
              <strong>${item.name}</strong>
              <div>ID: ${item.id}</div>
            </div>
            <button type="button" data-cloud-id="${item.id}" data-cloud-name="${item.name}">进入</button>
          </div>
        `
      )
      .join("");
    cloudList.querySelectorAll("button[data-cloud-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        cloudStack.push({ id: button.dataset.cloudId, name: button.dataset.cloudName });
        await loadCloudDirectories(button.dataset.cloudId);
      });
    });
  } catch (error) {
    cloudCurrentPath.textContent = currentCloudPathText();
    setMessage(cloudMessage, error.message);
  }
}

document.getElementById("open-settings-btn")?.addEventListener("click", () => {
  settingsModal.showModal();
});

document.getElementById("save-settings-btn")?.addEventListener("click", async () => {
  try {
    const payload = collectConfigPayload();
    await requestJson("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    window.sync115pan.authConfigured = Boolean(payload.auth_value);
    setMessage(settingsMessage, "Cookie 已保存。", false);
    setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    setMessage(settingsMessage, error.message);
  }
});

document.getElementById("pick-local-btn")?.addEventListener("click", async () => {
  setMessage(formMessage, "");
  const initialPath = localPathInput.value ? `?initial_path=${encodeURIComponent(localPathInput.value)}` : "";
  try {
    const data = await requestJson(`/api/system/pick-local-directory${initialPath}`, { method: "POST" });
    localPathInput.value = data.path;
  } catch (error) {
    setMessage(formMessage, error.message);
  }
});

document.getElementById("pick-cloud-btn")?.addEventListener("click", async () => {
  setMessage(formMessage, "");
  if (!window.sync115pan.authConfigured) {
    settingsModal.showModal();
    setMessage(settingsMessage, "请先保存 Cookie，然后再选择云盘目录。");
    return;
  }
  cloudStack = [{ id: "0", name: "根目录" }];
  cloudPickerModal.showModal();
  await loadCloudDirectories("0");
});

document.getElementById("cloud-up-btn")?.addEventListener("click", async () => {
  if (cloudStack.length <= 1) {
    return;
  }
  cloudStack.pop();
  await loadCloudDirectories(currentCloudNode().id);
});

document.getElementById("cloud-select-btn")?.addEventListener("click", () => {
  const node = currentCloudNode();
  cloudRootIdInput.value = String(node.id);
  cloudPathDisplay.value = currentCloudPathText();
  cloudPickerModal.close();
  updateRunButtonState();
  setMessage(formMessage, `已选择云盘目录：${cloudPathDisplay.value}`, false);
});

document.getElementById("sync-config-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveConfig("同步配置已保存。");
    await refreshRuntime();
  } catch (error) {
    setMessage(formMessage, error.message);
  }
});

document.getElementById("run-full-sync-btn")?.addEventListener("click", async () => {
  try {
    await requestJson("/api/run-full-sync", { method: "POST" });
    setMessage(formMessage, "已提交全量同步请求。", false);
    await refreshRuntime();
  } catch (error) {
    setMessage(formMessage, error.message);
  }
});

updateRunButtonState();

async function refreshDashboard() {
  try {
    const [runtime, logs] = await Promise.all([
      requestJson("/api/runtime"),
      requestJson("/api/logs"),
    ]);
    renderRuntime(runtime);
    renderLogs(logs);
  } catch (_) {
    // 后台刷新失败时不打断用户当前操作，等待下一轮刷新。
  }
}

setInterval(refreshDashboard, 5000);
