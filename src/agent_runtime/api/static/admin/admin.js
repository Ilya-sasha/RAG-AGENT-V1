const TENANT_STORAGE_KEY = "agent-runtime-admin-tenant";

const state = {
  selectedWorkflowId: "",
  selectedWorkflowRunId: "",
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

function setMessage(message, tone = "info") {
  const node = el("global-message");
  node.textContent = message;
  node.dataset.tone = tone;
}

function setPanelStatus(id, message) {
  el(id).textContent = message;
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

function badgeClassForStatus(status) {
  if (status === "failed" || status === "cancelled") {
    return "pill error";
  }
  if (status === "waiting_for_approval" || status === "paused") {
    return "pill warning";
  }
  return "pill";
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

function renderEmpty(containerId, message) {
  el(containerId).innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderWorkflowList(items) {
  if (!items.length) {
    renderEmpty("workflow-list", "当前 tenant 没有 workflow");
    return;
  }
  el("workflow-list").innerHTML = items
    .map(
      (item) => `
        <article class="list-item">
          <div class="list-item-header">
            <div class="item-title">${escapeHtml(item.workflow_id)}</div>
            <span class="${badgeClassForStatus(item.status)}">${escapeHtml(item.status)}</span>
          </div>
          <div class="meta-line">${escapeHtml(item.name)}</div>
          <div class="inline-meta">
            <span>latest_version: <code>${escapeHtml(item.latest_version)}</code></span>
            <button class="btn" type="button" data-workflow-detail="${escapeHtml(item.workflow_id)}">详情</button>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderWorkflowDetail(detail) {
  const versionSummary = detail.version_summaries || [];
  el("workflow-detail").innerHTML = `
    <div class="detail-card">
      <div class="panel-header">
        <h3>${escapeHtml(detail.workflow_id)} · ${escapeHtml(detail.name)}</h3>
        <span class="${badgeClassForStatus(detail.status)}">${escapeHtml(detail.status)}</span>
      </div>
      <p class="meta-line">${escapeHtml(detail.description)}</p>
      <div class="meta-line">tenant: <code>${escapeHtml(detail.tenant_id)}</code></div>
      <div class="meta-line">latest_version: <code>${escapeHtml(detail.latest_version)}</code> · latest_published_version: <code>${escapeHtml(detail.latest_published_version ?? "-")}</code></div>
      <div class="meta-line">updated_at: <code>${escapeHtml(formatTimestamp(detail.updated_at))}</code></div>
      <h3>Version Summaries</h3>
      <pre class="json-block">${escapeHtml(prettyJson(versionSummary))}</pre>
      <h3>Latest Published</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.latest_published || null))}</pre>
      <h3>Latest Draft</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.latest_draft || null))}</pre>
    </div>
  `;
}

function renderWorkflowRunList(items) {
  if (!items.length) {
    renderEmpty("workflow-run-list", "没有匹配的 workflow run");
    return;
  }
  el("workflow-run-list").innerHTML = items
    .map(
      (item) => `
        <article class="list-item">
          <div class="list-item-header">
            <div class="item-title">${escapeHtml(item.run_id)}</div>
            <span class="${badgeClassForStatus(item.status)}">${escapeHtml(item.status)}</span>
          </div>
          <div class="meta-line">${escapeHtml(item.workflow_name)} · ${escapeHtml(item.workflow_id)}</div>
          <div class="meta-line">blocking: <code>${escapeHtml(item.current_blocking_state)}</code>${item.current_blocking_state_reason ? ` · ${escapeHtml(item.current_blocking_state_reason)}` : ""}</div>
          <div class="inline-meta">
            <span>updated: <code>${escapeHtml(formatTimestamp(item.last_updated_at))}</code></span>
            <button class="btn" type="button" data-workflow-run-detail="${escapeHtml(item.run_id)}">详情</button>
          </div>
        </article>
      `,
    )
    .join("");
}

function renderWorkflowRunDetail(detail) {
  const approval = detail.pending_approval;
  const approvalActions = approval
    ? `
      <div class="button-row">
        <button class="btn primary" type="button" data-approval-prefill="${escapeHtml(approval.approval_id)}">填入审批区</button>
        <button class="btn" type="button" data-approve-inline="${escapeHtml(approval.approval_id)}">直接批准</button>
        <button class="btn danger" type="button" data-reject-inline="${escapeHtml(approval.approval_id)}">直接拒绝</button>
      </div>
    `
    : "";
  el("workflow-run-detail").innerHTML = `
    <div class="detail-card">
      <div class="panel-header">
        <h3>${escapeHtml(detail.run.run_id)} · ${escapeHtml(detail.workflow.workflow_name)}</h3>
        <span class="${badgeClassForStatus(detail.run.status)}">${escapeHtml(detail.run.status)}</span>
      </div>
      <div class="meta-line">tenant: <code>${escapeHtml(detail.run.tenant_id)}</code> · blocking: <code>${escapeHtml(detail.current_blocking_state)}</code></div>
      <div class="meta-line">latest_failure_summary: <code>${escapeHtml(detail.latest_failure_summary || "-")}</code></div>
      <div class="meta-line">launch_input keys: <code>${escapeHtml(Object.keys(detail.workflow.launch_input || {}).join(", ") || "-")}</code></div>
      ${approvalActions}
      <h3>Run</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.run))}</pre>
      <h3>Workflow</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.workflow))}</pre>
      <h3>Latest Checkpoint</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.latest_checkpoint || null))}</pre>
      <h3>Pending Approval</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.pending_approval || null))}</pre>
      <h3>Agents</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.agents || []))}</pre>
      <h3>Tasks</h3>
      <pre class="json-block">${escapeHtml(prettyJson(detail.tasks || []))}</pre>
    </div>
  `;
}

function renderKnowledgeBaseList(items) {
  if (!items.length) {
    renderEmpty("knowledge-base-list", "当前没有 knowledge base");
    return;
  }
  el("knowledge-base-list").innerHTML = items
    .map(
      (item) => `
        <article class="list-item">
          <div class="list-item-header">
            <div class="item-title">${escapeHtml(item.kb_id)}</div>
            <span class="${badgeClassForStatus(item.status)}">${escapeHtml(item.status)}</span>
          </div>
          <div class="meta-line">${escapeHtml(item.name)}</div>
          <div class="meta-line"><code>${escapeHtml(item.root_path)}</code></div>
          <div class="meta-line">documents: <code>${escapeHtml(item.document_count)}</code> · chunks: <code>${escapeHtml(item.chunk_count)}</code></div>
          <div class="button-row">
            <button class="btn" type="button" data-kb-status="${escapeHtml(item.kb_id)}">状态</button>
            <button class="btn primary" type="button" data-kb-ingest="${escapeHtml(item.kb_id)}">Ingest</button>
            <button class="btn" type="button" data-kb-reindex="${escapeHtml(item.kb_id)}">Reindex</button>
          </div>
        </article>
      `,
    )
    .join("");
}

async function loadOverview() {
  setMessage("正在刷新服务概览…");
  const healthBadge = el("health-badge");
  try {
    const [health, metricsText] = await Promise.all([request("/health"), request("/metrics")]);
    el("health-status").textContent = health.status;
    el("metrics-status").textContent = "已加载";
    el("metrics-preview").textContent = metricsText.split("\n").slice(0, 18).join("\n");
    healthBadge.textContent = "服务正常";
    healthBadge.className = "badge ok";
    setMessage("服务概览已刷新。", "ok");
  } catch (error) {
    healthBadge.textContent = "加载失败";
    healthBadge.className = "badge error";
    el("metrics-status").textContent = "失败";
    setMessage(`服务概览刷新失败：${error.message}`, "error");
  }
}

async function loadWorkflows() {
  const tenantId = getTenantId();
  storeTenantId();
  if (!tenantId) {
    setMessage("tenant_id 不能为空。", "error");
    return;
  }
  setPanelStatus("workflows-status", "加载中…");
  try {
    const params = new URLSearchParams({ tenant_id: tenantId });
    const workflowIdPrefix = el("workflow-id-prefix").value.trim();
    const nameQuery = el("workflow-name-query").value.trim();
    const limit = el("workflow-limit").value.trim();
    if (workflowIdPrefix) params.set("workflow_id_prefix", workflowIdPrefix);
    if (nameQuery) params.set("name_query", nameQuery);
    if (limit) params.set("limit", limit);
    const payload = await request(`/v1/workflows?${params.toString()}`);
    renderWorkflowList(payload.items || []);
    setPanelStatus("workflows-status", `已加载 ${payload.items.length} 项`);
    setMessage("Workflow 列表已刷新。", "ok");
  } catch (error) {
    setPanelStatus("workflows-status", "加载失败");
    renderEmpty("workflow-list", error.message);
    setMessage(`Workflow 列表加载失败：${error.message}`, "error");
  }
}

async function loadWorkflowDetail(workflowId) {
  const tenantId = getTenantId();
  if (!tenantId) {
    setMessage("tenant_id 不能为空。", "error");
    return;
  }
  state.selectedWorkflowId = workflowId;
  el("launch-workflow-id").value = workflowId;
  try {
    const detail = await request(`/v1/workflows/${encodeURIComponent(workflowId)}?tenant_id=${encodeURIComponent(tenantId)}`);
    renderWorkflowDetail(detail);
    setMessage(`已加载 workflow 详情：${workflowId}`, "ok");
  } catch (error) {
    renderEmpty("workflow-detail", error.message);
    setMessage(`Workflow 详情加载失败：${error.message}`, "error");
  }
}

async function launchWorkflow(event) {
  event.preventDefault();
  const tenantId = getTenantId();
  const workflowId = el("launch-workflow-id").value.trim() || state.selectedWorkflowId;
  if (!tenantId || !workflowId) {
    setMessage("启动 workflow 前需要 tenant_id 和 workflow_id。", "error");
    return;
  }
  try {
    const payload = {
      tenant_id: tenantId,
      input: parseJsonField(el("launch-workflow-input").value, {}),
      metadata: parseJsonField(el("launch-workflow-metadata-inline").value, {}),
    };
    const version = el("launch-workflow-version").value.trim();
    if (version) {
      payload.version = Number(version);
    }
    const result = await request(`/v1/workflows/${encodeURIComponent(workflowId)}/launch`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    el("run-id").value = result.run_id;
    el("run-result").textContent = prettyJson(result);
    setMessage(`Workflow 已启动：${result.run_id}`, "ok");
    await loadWorkflowRuns();
  } catch (error) {
    setMessage(`Workflow 启动失败：${error.message}`, "error");
  }
}

async function loadWorkflowRuns() {
  const tenantId = getTenantId();
  if (!tenantId) {
    setMessage("tenant_id 不能为空。", "error");
    return;
  }
  setPanelStatus("workflow-runs-status", "加载中…");
  try {
    const params = new URLSearchParams({ tenant_id: tenantId });
    const workflowId = el("workflow-run-workflow-id").value.trim();
    const status = el("workflow-run-status-filter").value.trim();
    const limit = el("workflow-run-limit").value.trim();
    if (workflowId) params.set("workflow_id", workflowId);
    if (status) params.set("status", status);
    if (limit) params.set("limit", limit);
    const payload = await request(`/v1/workflow-runs?${params.toString()}`);
    renderWorkflowRunList(payload.items || []);
    setPanelStatus("workflow-runs-status", `已加载 ${payload.items.length} 项`);
    setMessage("Workflow run 列表已刷新。", "ok");
  } catch (error) {
    setPanelStatus("workflow-runs-status", "加载失败");
    renderEmpty("workflow-run-list", error.message);
    setMessage(`Workflow run 列表加载失败：${error.message}`, "error");
  }
}

async function loadWorkflowRunDetail(runId) {
  const tenantId = getTenantId();
  if (!tenantId) {
    setMessage("tenant_id 不能为空。", "error");
    return;
  }
  state.selectedWorkflowRunId = runId;
  el("run-id").value = runId;
  try {
    const detail = await request(`/v1/workflow-runs/${encodeURIComponent(runId)}?tenant_id=${encodeURIComponent(tenantId)}`);
    renderWorkflowRunDetail(detail);
    setMessage(`已加载 workflow run 详情：${runId}`, "ok");
  } catch (error) {
    renderEmpty("workflow-run-detail", error.message);
    setMessage(`Workflow run 详情加载失败：${error.message}`, "error");
  }
}

async function loadKnowledgeBases() {
  const tenantId = getTenantId();
  setPanelStatus("knowledge-bases-status", "加载中…");
  try {
    const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
    const payload = await request(`/internal/knowledge-bases${query}`);
    renderKnowledgeBaseList(payload || []);
    setPanelStatus("knowledge-bases-status", `已加载 ${payload.length} 项`);
    setMessage("Knowledge base 列表已刷新。", "ok");
  } catch (error) {
    setPanelStatus("knowledge-bases-status", "加载失败");
    renderEmpty("knowledge-base-list", error.message);
    setMessage(`Knowledge base 列表加载失败：${error.message}`, "error");
  }
}

async function createKnowledgeBase(event) {
  event.preventDefault();
  const tenantId = getTenantId();
  if (!tenantId) {
    setMessage("注册 knowledge base 前需要 tenant_id。", "error");
    return;
  }
  try {
    const payload = {
      kb_id: el("kb-id").value.trim(),
      tenant_id: tenantId,
      name: el("kb-name").value.trim(),
      root_path: el("kb-root-path").value.trim(),
      metadata: parseJsonField(el("kb-metadata").value, {}),
    };
    const result = await request("/internal/knowledge-bases", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setMessage(`Knowledge base 已注册：${result.kb_id}`, "ok");
    await loadKnowledgeBases();
  } catch (error) {
    setMessage(`Knowledge base 注册失败：${error.message}`, "error");
  }
}

async function performKnowledgeBaseAction(kbId, action) {
  const tenantId = getTenantId();
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
  try {
    if (action === "status") {
      const result = await request(`/internal/knowledge-bases/${encodeURIComponent(kbId)}/status${query}`);
      setMessage(`Knowledge base 状态：${kbId}`, "ok");
      el("knowledge-base-list").insertAdjacentHTML(
        "afterbegin",
        `<pre class="json-block">${escapeHtml(prettyJson(result))}</pre>`,
      );
      return;
    }
    await request(`/internal/knowledge-bases/${encodeURIComponent(kbId)}/${action}${query}`, { method: "POST" });
    setMessage(`Knowledge base ${action} 已提交：${kbId}`, "ok");
    await loadKnowledgeBases();
  } catch (error) {
    setMessage(`Knowledge base ${action} 失败：${error.message}`, "error");
  }
}

async function loadApproval() {
  const approvalId = el("approval-id").value.trim();
  if (!approvalId) {
    setMessage("approval_id 不能为空。", "error");
    return;
  }
  try {
    const result = await request(`/v1/approvals/${encodeURIComponent(approvalId)}`);
    el("approval-result").textContent = prettyJson(result);
    setMessage(`已加载审批：${approvalId}`, "ok");
  } catch (error) {
    el("approval-result").textContent = error.message;
    setMessage(`审批加载失败：${error.message}`, "error");
  }
}

async function resolveApproval(action, approvalIdOverride) {
  const approvalId = approvalIdOverride || el("approval-id").value.trim();
  if (!approvalId) {
    setMessage("approval_id 不能为空。", "error");
    return;
  }
  try {
    const note = el("approval-note").value;
    const result = await request(`/v1/approvals/${encodeURIComponent(approvalId)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ resolution_note: note || null }),
    });
    el("approval-result").textContent = prettyJson(result);
    setMessage(`审批已${action === "approve" ? "批准" : "拒绝"}：${approvalId}`, "ok");
    await loadWorkflowRuns();
    if (state.selectedWorkflowRunId) {
      await loadWorkflowRunDetail(state.selectedWorkflowRunId);
    }
  } catch (error) {
    setMessage(`审批处理失败：${error.message}`, "error");
  }
}

async function loadRun() {
  const runId = el("run-id").value.trim();
  if (!runId) {
    setMessage("run_id 不能为空。", "error");
    return;
  }
  try {
    const result = await request(`/v1/runs/${encodeURIComponent(runId)}`);
    el("run-result").textContent = prettyJson(result);
    setMessage(`已加载 run：${runId}`, "ok");
  } catch (error) {
    el("run-result").textContent = error.message;
    setMessage(`Run 查询失败：${error.message}`, "error");
  }
}

async function runOperation(action) {
  const runId = el("run-id").value.trim();
  if (!runId) {
    setMessage("run_id 不能为空。", "error");
    return;
  }
  try {
    const endpointMap = {
      resume: `/v1/runs/${encodeURIComponent(runId)}/resume`,
      cancel: `/v1/runs/${encodeURIComponent(runId)}/cancel`,
      replay: `/v1/runs/${encodeURIComponent(runId)}/events/replay`,
    };
    const methodMap = {
      resume: "POST",
      cancel: "POST",
      replay: "GET",
    };
    const result = await request(endpointMap[action], { method: methodMap[action] });
    el("run-result").textContent = prettyJson(result);
    setMessage(`Run ${action} 操作完成：${runId}`, "ok");
    await loadWorkflowRuns();
    if (state.selectedWorkflowRunId === runId) {
      await loadWorkflowRunDetail(runId);
    }
  } catch (error) {
    setMessage(`Run ${action} 失败：${error.message}`, "error");
  }
}

function wireEventDelegation() {
  el("workflow-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-workflow-detail]");
    if (button) {
      loadWorkflowDetail(button.dataset.workflowDetail);
    }
  });

  el("workflow-run-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-workflow-run-detail]");
    if (button) {
      loadWorkflowRunDetail(button.dataset.workflowRunDetail);
    }
  });

  el("workflow-run-detail").addEventListener("click", (event) => {
    const prefill = event.target.closest("[data-approval-prefill]");
    if (prefill) {
      el("approval-id").value = prefill.dataset.approvalPrefill;
      setMessage(`已填入 approval_id：${prefill.dataset.approvalPrefill}`, "ok");
      return;
    }
    const approve = event.target.closest("[data-approve-inline]");
    if (approve) {
      el("approval-id").value = approve.dataset.approveInline;
      resolveApproval("approve", approve.dataset.approveInline);
      return;
    }
    const reject = event.target.closest("[data-reject-inline]");
    if (reject) {
      el("approval-id").value = reject.dataset.rejectInline;
      resolveApproval("reject", reject.dataset.rejectInline);
    }
  });

  el("knowledge-base-list").addEventListener("click", (event) => {
    const statusButton = event.target.closest("[data-kb-status]");
    if (statusButton) {
      performKnowledgeBaseAction(statusButton.dataset.kbStatus, "status");
      return;
    }
    const ingestButton = event.target.closest("[data-kb-ingest]");
    if (ingestButton) {
      performKnowledgeBaseAction(ingestButton.dataset.kbIngest, "ingest");
      return;
    }
    const reindexButton = event.target.closest("[data-kb-reindex]");
    if (reindexButton) {
      performKnowledgeBaseAction(reindexButton.dataset.kbReindex, "reindex");
    }
  });
}

function wireControls() {
  el("tenant-id").addEventListener("change", storeTenantId);
  el("refresh-overview").addEventListener("click", loadOverview);
  el("load-workflows").addEventListener("click", loadWorkflows);
  el("reload-workflows").addEventListener("click", loadWorkflows);
  el("workflow-launch-form").addEventListener("submit", launchWorkflow);
  el("load-workflow-runs").addEventListener("click", loadWorkflowRuns);
  el("reload-workflow-runs").addEventListener("click", loadWorkflowRuns);
  el("load-knowledge-bases").addEventListener("click", loadKnowledgeBases);
  el("knowledge-base-create-form").addEventListener("submit", createKnowledgeBase);
  el("load-approval").addEventListener("click", loadApproval);
  el("approve-approval").addEventListener("click", () => resolveApproval("approve"));
  el("reject-approval").addEventListener("click", () => resolveApproval("reject"));
  el("load-run").addEventListener("click", loadRun);
  el("resume-run").addEventListener("click", () => runOperation("resume"));
  el("cancel-run").addEventListener("click", () => runOperation("cancel"));
  el("replay-run-events").addEventListener("click", () => runOperation("replay"));
}

async function boot() {
  hydrateTenantId();
  wireControls();
  wireEventDelegation();
  await loadOverview();
  await Promise.allSettled([loadWorkflows(), loadWorkflowRuns(), loadKnowledgeBases()]);
}

boot();
