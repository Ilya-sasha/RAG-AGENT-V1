const TENANT_STORAGE_KEY = "agent-runtime-assistant-tenant";
const KNOWLEDGE_BASE_STORAGE_PREFIX = "agent-runtime-assistant-kb-ids";

const state = {
  tenantId: "tenant-a",
  sessions: [],
  selectedSessionId: "",
  selectedMode: "chat",
  knowledgeBases: [],
  selectedKnowledgeBaseIds: [],
};

const el = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function prettyJson(value) {
  return JSON.stringify(value, null, 2);
}

function toTimestamp(value) {
  const timestamp = Date.parse(value || "");
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return String(value);
  }
}

function formatMode(mode) {
  if (mode === "chat") {
    return "聊天";
  }
  if (mode === "task") {
    return "任务";
  }
  return String(mode || "-");
}

function formatLaunchKind(kind) {
  if (kind === "chat") {
    return "聊天运行";
  }
  if (kind === "task") {
    return "任务运行";
  }
  if (kind === "workflow") {
    return "工作流运行";
  }
  return String(kind || "-");
}

function setStatus(message, tone = "muted") {
  const node = el("global-status");
  node.textContent = message;
  node.dataset.tone = tone;
}

function setActivityStatus(message) {
  el("activity-status").textContent = message;
}

function clearSelectedSessionViews() {
  el("active-session-badge").textContent = "未选择会话";
  el("message-feed").innerHTML = '<div class="empty-state">请选择一个会话查看消息。</div>';
  el("activity-list").innerHTML = '<div class="empty-state">会话活动会显示在这里。</div>';
  el("run-detail").textContent = "选择一个关联运行后可查看状态。";
  setActivityStatus("空闲");
}

function getTenantId() {
  return el("tenant-id").value.trim();
}

function storeTenantId() {
  localStorage.setItem(TENANT_STORAGE_KEY, getTenantId());
}

function hydrateTenantId() {
  const saved = localStorage.getItem(TENANT_STORAGE_KEY);
  if (saved) {
    el("tenant-id").value = saved;
  }
  state.tenantId = getTenantId();
}

function getKnowledgeBaseStorageKey(tenantId) {
  return `${KNOWLEDGE_BASE_STORAGE_PREFIX}:${tenantId}`;
}

function hydrateKnowledgeBaseSelection() {
  const tenantId = getTenantId();
  const rawSelection = localStorage.getItem(getKnowledgeBaseStorageKey(tenantId));
  if (rawSelection === null) {
    state.selectedKnowledgeBaseIds = [];
    return;
  }

  try {
    const parsed = JSON.parse(rawSelection);
    state.selectedKnowledgeBaseIds = Array.isArray(parsed)
      ? parsed.filter((item) => typeof item === "string" && item.trim())
      : [];
  } catch {
    state.selectedKnowledgeBaseIds = [];
  }
}

function storeKnowledgeBaseSelection() {
  localStorage.setItem(
    getKnowledgeBaseStorageKey(getTenantId()),
    JSON.stringify(state.selectedKnowledgeBaseIds),
  );
}

function renderKnowledgeBaseList() {
  const container = el("knowledge-base-list");
  const availableIds = state.knowledgeBases.map((item) => item.kb_id);
  const selectedIds = new Set(state.selectedKnowledgeBaseIds);
  el("knowledge-base-count").textContent = `${state.knowledgeBases.length} 个`;

  if (!state.knowledgeBases.length) {
    container.innerHTML = '<div class="empty-state">当前租户还没有知识库。请先到管理页创建并导入内容。</div>';
    return;
  }

  container.innerHTML = state.knowledgeBases
    .map(
      (knowledgeBase) => `
        <label class="knowledge-base-card">
          <input
            type="checkbox"
            data-kb-id="${escapeHtml(knowledgeBase.kb_id)}"
            ${selectedIds.has(knowledgeBase.kb_id) ? "checked" : ""}
          >
          <div class="knowledge-base-body">
            <div class="knowledge-base-title">${escapeHtml(knowledgeBase.name)}</div>
            <div class="knowledge-base-meta">${escapeHtml(knowledgeBase.kb_id)} · ${escapeHtml(knowledgeBase.status)}</div>
          </div>
        </label>
      `,
    )
    .join("");
}

function syncKnowledgeBaseSelection(availableIds) {
  const selectedSet = new Set(state.selectedKnowledgeBaseIds);
  const filteredSelection = availableIds.filter((kbId) => selectedSet.has(kbId));

  if (!state.selectedKnowledgeBaseIds.length) {
    state.selectedKnowledgeBaseIds = [...availableIds];
  } else {
    state.selectedKnowledgeBaseIds = filteredSelection;
  }
}

function parseJsonField(rawValue, fallback) {
  const value = rawValue.trim();
  if (!value) {
    return fallback;
  }
  return JSON.parse(value);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    let detail = payload;
    if (isJson && payload && typeof payload === "object" && "detail" in payload) {
      detail = payload.detail;
    }
    throw new Error(typeof detail === "string" ? detail : prettyJson(detail));
  }

  return payload;
}

function renderSessionList() {
  const container = el("session-list");
  el("session-count").textContent = `${state.sessions.length} 个`;

  if (!state.sessions.length) {
    container.innerHTML = '<div class="empty-state">当前还没有加载任何会话。</div>';
    return;
  }

  container.innerHTML = state.sessions
    .map(
      (session) => `
        <article class="session-card ${session.session_id === state.selectedSessionId ? "active" : ""}">
          <div class="session-title">${escapeHtml(session.title)}</div>
          <div class="session-meta">${escapeHtml(formatMode(session.mode))} - ${escapeHtml(session.status)}</div>
          <div class="session-meta">更新时间 ${escapeHtml(formatTimestamp(session.updated_at))}</div>
          <button class="button button-ghost" type="button" data-session-id="${escapeHtml(session.session_id)}">打开会话</button>
        </article>
      `,
    )
    .join("");
}

function renderMessages(messages) {
  const container = el("message-feed");

  if (!messages.length) {
    container.innerHTML = '<div class="empty-state">当前会话还没有消息。</div>';
    return;
  }

  container.innerHTML = messages
    .map(
      (message) => `
        <article class="message-card" data-role="${escapeHtml(message.role)}">
          <div class="message-role">${escapeHtml(message.role)}</div>
          <div class="message-body">${escapeHtml(message.content)}</div>
          <div class="message-meta">${escapeHtml(formatTimestamp(message.created_at))}${message.run_id ? ` - run ${escapeHtml(message.run_id)}` : ""}</div>
        </article>
      `,
    )
    .join("");
}

function renderActivity(activity) {
  const container = el("activity-list");

  if (!activity.linked_runs.length) {
    container.innerHTML = '<div class="empty-state">当前会话还没有关联运行。</div>';
    return;
  }

  container.innerHTML = activity.linked_runs
    .map((linkedRun) => {
      const approvalId = linkedRun.pending_approval?.approval_id || "";
      return `
        <article class="activity-card">
          <div class="activity-title">${escapeHtml(formatLaunchKind(linkedRun.launch_kind))} - ${escapeHtml(linkedRun.run_status)}</div>
          <div class="activity-meta">${escapeHtml(linkedRun.run_id)} - ${escapeHtml(formatTimestamp(linkedRun.created_at))}</div>
          <div class="activity-body">${escapeHtml(linkedRun.objective || linkedRun.result || linkedRun.error || "暂无摘要。")}</div>
          <div class="action-row">
            <button class="button button-ghost" type="button" data-run-id="${escapeHtml(linkedRun.run_id)}">查看运行</button>
            ${approvalId ? `<button class="button button-primary" type="button" data-approval-prefill="${escapeHtml(approvalId)}">加载审批</button>` : ""}
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadRunDetail(runId) {
  const run = await request(`/v1/runs/${encodeURIComponent(runId)}`);
  el("run-detail").textContent = prettyJson(run);
  return run;
}

async function loadSessions() {
  const tenantId = getTenantId();
  if (!tenantId) {
    state.sessions = [];
    state.selectedSessionId = "";
    renderSessionList();
    clearSelectedSessionViews();
    setStatus("tenant_id 不能为空。", "error");
    return;
  }

  state.tenantId = tenantId;
  storeTenantId();
  setStatus("正在加载会话…");

  try {
    const sessions = await request(`/v1/assistant/sessions?tenant_id=${encodeURIComponent(tenantId)}`);
    state.sessions = [...sessions].sort((left, right) => {
      const updatedAtDelta = toTimestamp(right.updated_at) - toTimestamp(left.updated_at);
      if (updatedAtDelta !== 0) {
        return updatedAtDelta;
      }
      return right.session_id.localeCompare(left.session_id);
    });

    if (!state.selectedSessionId && state.sessions.length) {
      state.selectedSessionId = state.sessions[0].session_id;
    } else if (
      state.selectedSessionId &&
      !state.sessions.some((item) => item.session_id === state.selectedSessionId)
    ) {
      state.selectedSessionId = state.sessions[0]?.session_id || "";
    }

    renderSessionList();
    setStatus(`已加载 ${sessions.length} 个会话。`, "ok");

    if (state.selectedSessionId) {
      await Promise.all([loadMessages(state.selectedSessionId), loadActivity(state.selectedSessionId)]);
    } else {
      clearSelectedSessionViews();
    }
  } catch (error) {
    state.sessions = [];
    state.selectedSessionId = "";
    renderSessionList();
    clearSelectedSessionViews();
    setStatus(`加载会话失败：${error.message}`, "error");
  }
}

async function loadKnowledgeBases() {
  const tenantId = getTenantId();
  if (!tenantId) {
    state.knowledgeBases = [];
    state.selectedKnowledgeBaseIds = [];
    renderKnowledgeBaseList();
    return;
  }

  try {
    const payload = await request(`/internal/knowledge-bases?tenant_id=${encodeURIComponent(tenantId)}`);
    state.knowledgeBases = payload;
    const availableIds = payload.map((item) => item.kb_id);
    syncKnowledgeBaseSelection(availableIds);
    renderKnowledgeBaseList();
    storeKnowledgeBaseSelection();
  } catch (error) {
    state.knowledgeBases = [];
    state.selectedKnowledgeBaseIds = [];
    renderKnowledgeBaseList();
    setStatus(`加载知识库失败：${error.message}`, "error");
  }
}

async function createSession(event) {
  event.preventDefault();
  const tenantId = getTenantId();
  const title = el("session-title").value.trim();
  const mode = el("session-mode").value;

  if (!tenantId || !title) {
    setStatus("tenant_id 和会话标题不能为空。", "error");
    return;
  }

  try {
    const session = await request("/v1/assistant/sessions", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, mode, title }),
    });
    state.selectedSessionId = session.session_id;
    state.selectedMode = session.mode;
    el("session-form").reset();
    el("session-mode").value = mode;
    await loadSessions();
    setStatus(`已创建会话：${session.title}`, "ok");
  } catch (error) {
    setStatus(`创建会话失败：${error.message}`, "error");
  }
}

async function loadMessages(sessionId) {
  if (!sessionId) {
    clearSelectedSessionViews();
    return;
  }

  const tenantId = getTenantId();
  const selectedSession = state.sessions.find((item) => item.session_id === sessionId);
  state.selectedMode = selectedSession?.mode || state.selectedMode;
  el("active-session-badge").textContent = selectedSession
    ? `${selectedSession.title} - ${formatMode(selectedSession.mode)}`
    : sessionId;

  try {
    const messages = await request(
      `/v1/assistant/sessions/${encodeURIComponent(sessionId)}/messages?tenant_id=${encodeURIComponent(tenantId)}`,
    );
    renderMessages(messages);
  } catch (error) {
    el("message-feed").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    setStatus(`加载消息失败：${error.message}`, "error");
  }
}

async function sendChat(event) {
  event.preventDefault();
  const tenantId = getTenantId();
  const content = el("chat-input").value.trim();
  const sessionId = state.selectedSessionId;
  const selectedKnowledgeBaseIds = state.selectedKnowledgeBaseIds.filter((item) => Boolean(item));

  if (!sessionId || !content) {
    setStatus("请先选择会话并输入消息。", "error");
    return;
  }

  if (state.knowledgeBases.length > 0 && selectedKnowledgeBaseIds.length === 0) {
    setStatus("请先选择至少一个知识库。", "error");
    return;
  }

  try {
    await request(`/v1/assistant/sessions/${encodeURIComponent(sessionId)}/chat`, {
      method: "POST",
      body: JSON.stringify({
        tenant_id: tenantId,
        content,
        knowledge_base_ids: selectedKnowledgeBaseIds,
      }),
    });
    el("chat-input").value = "";
    await Promise.all([loadSessions(), loadMessages(sessionId), loadActivity(sessionId)]);
    setStatus("消息已发送。", "ok");
  } catch (error) {
    setStatus(`发送消息失败：${error.message}`, "error");
  }
}

async function createTask(event) {
  event.preventDefault();
  const tenantId = getTenantId();
  const sessionId = state.selectedSessionId;
  const objective = el("task-objective").value.trim();

  if (!sessionId || !objective) {
    setStatus("请先选择会话并填写任务目标。", "error");
    return;
  }

  try {
    const payload = {
      tenant_id: tenantId,
      objective,
      launch_input: parseJsonField(el("task-launch-input").value, {}),
    };
    const workflowId = el("task-workflow-id").value.trim();
    const version = el("task-version").value.trim();
    if (workflowId) {
      payload.workflow_id = workflowId;
    }
    if (version) {
      payload.version = Number(version);
    }

    const result = await request(`/v1/assistant/sessions/${encodeURIComponent(sessionId)}/tasks`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    el("task-objective").value = "";
    el("task-workflow-id").value = "";
    el("task-version").value = "";
    el("task-launch-input").value = "";
    await Promise.all([loadSessions(), loadMessages(sessionId), loadActivity(sessionId)]);
    await loadRunDetail(result.run_id);
    setStatus(`任务已发起，运行 ID：${result.run_id}`, "ok");
  } catch (error) {
    setStatus(`创建任务失败：${error.message}`, "error");
  }
}

async function loadActivity(sessionId = state.selectedSessionId) {
  const tenantId = getTenantId();
  if (!sessionId) {
    clearSelectedSessionViews();
    return;
  }

  setActivityStatus("加载中");

  try {
    const activity = await request(
      `/v1/assistant/sessions/${encodeURIComponent(sessionId)}/activity?tenant_id=${encodeURIComponent(tenantId)}`,
    );

    renderActivity(activity);
    if (activity.linked_runs[0]) {
      await loadRunDetail(activity.linked_runs[0].run_id);
    } else {
      el("run-detail").textContent = "选择一个关联运行后可查看状态。";
    }
    setActivityStatus(`${activity.linked_runs.length} 条运行`);
  } catch (error) {
    el("run-detail").textContent = "选择一个关联运行后可查看状态。";
    el("activity-list").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    setActivityStatus("加载失败");
    setStatus(`加载活动记录失败：${error.message}`, "error");
  }
}

async function loadApproval() {
  const approvalId = el("approval-id").value.trim();
  if (!approvalId) {
    setStatus("approval_id 不能为空。", "error");
    return;
  }

  try {
    const approval = await request(`/v1/approvals/${encodeURIComponent(approvalId)}`);
    el("approval-result").textContent = prettyJson(approval);
    setStatus(`已加载审批：${approvalId}`, "ok");
  } catch (error) {
    el("approval-result").textContent = error.message;
    setStatus(`加载审批失败：${error.message}`, "error");
  }
}

async function resolveApproval(action, approvalIdOverride) {
  const approvalId = approvalIdOverride || el("approval-id").value.trim();
  if (!approvalId) {
    setStatus("approval_id 不能为空。", "error");
    return;
  }

  try {
    const result = await request(`/v1/approvals/${encodeURIComponent(approvalId)}/${action}`, {
      method: "POST",
      body: JSON.stringify({
        resolution_note: el("approval-note").value.trim() || null,
      }),
    });
    el("approval-result").textContent = prettyJson(result);
    setStatus(`审批已${action === "approve" ? "批准" : "拒绝"}：${approvalId}`, "ok");
    if (state.selectedSessionId) {
      await loadActivity(state.selectedSessionId);
    }
  } catch (error) {
    setStatus(`处理审批失败：${error.message}`, "error");
  }
}

function bindSessionSelection() {
  el("session-list").addEventListener("click", async (event) => {
    const trigger = event.target.closest("[data-session-id]");
    if (!trigger) {
      return;
    }
    state.selectedSessionId = trigger.dataset.sessionId;
    renderSessionList();
    await Promise.all([loadMessages(state.selectedSessionId), loadActivity(state.selectedSessionId)]);
  });
}

function bindActivityActions() {
  el("activity-list").addEventListener("click", async (event) => {
    const runTrigger = event.target.closest("[data-run-id]");
    if (runTrigger) {
      await loadRunDetail(runTrigger.dataset.runId);
      return;
    }

    const approvalTrigger = event.target.closest("[data-approval-prefill]");
    if (approvalTrigger) {
      el("approval-id").value = approvalTrigger.dataset.approvalPrefill;
      await loadApproval();
    }
  });
}

function bindKnowledgeBaseSelection() {
  el("knowledge-base-list").addEventListener("change", (event) => {
    const trigger = event.target.closest("[data-kb-id]");
    if (!trigger) {
      return;
    }

    const nextSelectedIds = new Set(state.selectedKnowledgeBaseIds);
    if (trigger.checked) {
      nextSelectedIds.add(trigger.dataset.kbId);
    } else {
      nextSelectedIds.delete(trigger.dataset.kbId);
    }

    state.selectedKnowledgeBaseIds = state.knowledgeBases
      .map((item) => item.kb_id)
      .filter((kbId) => nextSelectedIds.has(kbId));
    renderKnowledgeBaseList();
    storeKnowledgeBaseSelection();
  });
}

function bindControls() {
  el("tenant-id").addEventListener("change", () => {
    storeTenantId();
    state.sessions = [];
    state.selectedSessionId = "";
    state.knowledgeBases = [];
    state.selectedKnowledgeBaseIds = [];
    renderSessionList();
    clearSelectedSessionViews();
    renderKnowledgeBaseList();
    hydrateKnowledgeBaseSelection();
    loadSessions();
    loadKnowledgeBases();
  });
  el("refresh-sessions").addEventListener("click", loadSessions);
  el("refresh-knowledge-bases").addEventListener("click", loadKnowledgeBases);
  el("session-form").addEventListener("submit", createSession);
  el("chat-form").addEventListener("submit", sendChat);
  el("task-form").addEventListener("submit", createTask);
  el("load-approval").addEventListener("click", loadApproval);
  el("approve-approval").addEventListener("click", () => resolveApproval("approve"));
  el("reject-approval").addEventListener("click", () => resolveApproval("reject"));
}

async function boot() {
  hydrateTenantId();
  hydrateKnowledgeBaseSelection();
  bindControls();
  bindSessionSelection();
  bindActivityActions();
  bindKnowledgeBaseSelection();
  await Promise.all([loadSessions(), loadKnowledgeBases()]);
}

boot();
