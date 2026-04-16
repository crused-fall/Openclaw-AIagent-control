const state = {
  bootstrap: null,
  currentTaskId: null,
  taskStream: null,
  live: false,
  currentHistory: null,
  healthSnapshot: null,
  currentOutput: null,
  resultFilter: "all",
};

const elements = {
  repoPath: document.getElementById("repo-path"),
  configPath: document.getElementById("config-path"),
  pipeline: document.getElementById("pipeline"),
  request: document.getElementById("request"),
  stepGrid: document.getElementById("step-grid"),
  refreshBootstrap: document.getElementById("refresh-bootstrap"),
  modeToggle: document.getElementById("mode-toggle"),
  workspaceMetrics: document.getElementById("workspace-metrics"),
  heroStatus: document.getElementById("hero-status"),
  recentRuns: document.getElementById("recent-runs"),
  pruneKeepLatest: document.getElementById("prune-keep-latest"),
  pruneRuns: document.getElementById("prune-runs"),
  housekeepingStatus: document.getElementById("housekeeping-status"),
  healthAgentId: document.getElementById("health-agent-id"),
  checkHealth: document.getElementById("check-health"),
  healthPanel: document.getElementById("health-panel"),
  taskState: document.getElementById("task-state"),
  cancelTask: document.getElementById("cancel-task"),
  taskMeta: document.getElementById("task-meta"),
  taskProgress: document.getElementById("task-progress"),
  outputPane: document.getElementById("output-pane"),
  resultFilter: document.getElementById("result-filter"),
  copyRunSummary: document.getElementById("copy-run-summary"),
  copyIssueUpdate: document.getElementById("copy-issue-update"),
  copyPrNote: document.getElementById("copy-pr-note"),
  copyFeedback: document.getElementById("copy-feedback"),
  artifactContext: document.getElementById("artifact-context"),
  cleanupCurrentRun: document.getElementById("cleanup-current-run"),
  artifactList: document.getElementById("artifact-list"),
  artifactViewer: document.getElementById("artifact-viewer"),
  readinessStateSlot: document.getElementById("readiness-state-slot"),
  readinessSummary: document.getElementById("readiness-summary"),
  readinessChecks: document.getElementById("readiness-checks"),
  selectAll: document.getElementById("select-all"),
  selectNone: document.getElementById("select-none"),
  buttons: Array.from(document.querySelectorAll("[data-action]")),
  taskStateSlot: document.getElementById("task-state-slot"),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function makeStatusChip(value) {
  const normalized = String(value || "neutral").toLowerCase();
  return `<span class="status-chip ${normalized}">${escapeHtml(normalized)}</span>`;
}

function setCopyFeedback(message) {
  elements.copyFeedback.textContent = message;
}

function statusCounts(results) {
  const counts = {};
  for (const item of results || []) {
    counts[item.status] = (counts[item.status] || 0) + 1;
  }
  return counts;
}

function formatCounts(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) {
    return "no step results";
  }
  return entries.map(([key, value]) => `${key}:${value}`).join(" · ");
}

function actionableResults(results) {
  return (results || []).filter((item) => ["failed", "blocked", "skipped"].includes(item.status));
}

function filterResults(results) {
  const all = results || [];
  switch (state.resultFilter) {
    case "actionable":
      return actionableResults(all);
    case "failed-blocked":
      return all.filter((item) => ["failed", "blocked"].includes(item.status));
    case "skipped":
      return all.filter((item) => item.status === "skipped");
    case "succeeded":
      return all.filter((item) => item.status === "succeeded");
    default:
      return all;
  }
}

function extractRunPayload(payload) {
  if (!payload) {
    return null;
  }
  if (payload.runResult) {
    return {
      runResult: payload.runResult,
      history: payload.history || null,
      pipeline: payload.pipeline || "",
      request: payload.history?.context?.user_request || "",
    };
  }
  if (payload.summary) {
    return {
      runResult: payload.summary,
      history: payload,
      pipeline: "",
      request: payload.context?.user_request || "",
    };
  }
  return null;
}

function primaryBranch(runResult) {
  for (const item of runResult?.results || []) {
    const artifacts = item.artifacts || {};
    if (artifacts.source_branch) {
      return artifacts.source_branch;
    }
    if (artifacts.branch_name) {
      return artifacts.branch_name;
    }
  }
  return "";
}

function currentPipelineSteps() {
  const pipelines = state.bootstrap?.snapshot?.pipelines || {};
  return pipelines[elements.pipeline.value] || [];
}

function currentPlanMap() {
  return new Map(
    ((state.bootstrap?.snapshot?.currentPlan || []).map((step) => [step.id, step])),
  );
}

function effectiveStepIds() {
  const pipelineSteps = currentPipelineSteps();
  if (!pipelineSteps.length) {
    return [];
  }

  const stepMap = new Map(pipelineSteps.map((step) => [step.id, step]));
  const explicitSelection = selectedSteps();
  const seed = explicitSelection.length ? explicitSelection : pipelineSteps.map((step) => step.id);
  const included = new Set();

  function includeStep(stepId) {
    if (!stepId || included.has(stepId)) {
      return;
    }
    included.add(stepId);
    const step = stepMap.get(stepId);
    for (const dependency of step?.dependsOn || []) {
      includeStep(dependency);
    }
  }

  seed.forEach(includeStep);
  return pipelineSteps.map((step) => step.id).filter((stepId) => included.has(stepId));
}

function effectivePlanItems() {
  const planMap = currentPlanMap();
  return effectiveStepIds().map((stepId) => {
    const planItem = planMap.get(stepId);
    if (planItem) {
      return planItem;
    }
    const pipelineStep = currentPipelineSteps().find((step) => step.id === stepId) || {};
    return {
      id: pipelineStep.id || stepId,
      title: pipelineStep.title || stepId,
      mode: "",
      agent: "",
      profile: pipelineStep.profile || "",
      assignment: pipelineStep.assignment || "",
      managedAgent: "",
      dependsOn: pipelineStep.dependsOn || [],
      fallbackUsed: false,
    };
  });
}

function healthSnapshotIsCurrent() {
  const requestedAgent = (elements.healthAgentId.value || "").trim();
  if (!state.healthSnapshot) {
    return false;
  }
  if (!requestedAgent) {
    return true;
  }
  return state.healthSnapshot.agentId === requestedAgent;
}

function latestPreflightChecks() {
  const sources = [
    state.currentOutput?.preflight,
    state.currentOutput?.history?.preflight,
    state.currentHistory?.preflight,
  ];
  for (const source of sources) {
    if (Array.isArray(source?.checks) && source.checks.length) {
      return source.checks;
    }
  }
  return [];
}

function overallStatus(checks) {
  const statuses = (checks || []).map((item) => item.status);
  if (statuses.some((status) => ["blocked", "failed"].includes(status))) {
    return "blocked";
  }
  if (statuses.includes("warning")) {
    return "warning";
  }
  if (statuses.includes("passed") && statuses.every((status) => ["passed", "neutral"].includes(status))) {
    return "passed";
  }
  return "neutral";
}

function readinessFacts() {
  const bootstrap = state.bootstrap || {};
  const runtime = bootstrap.snapshot?.runtime || {};
  const git = bootstrap.git || {};
  const health = state.healthSnapshot;
  const healthCurrent = healthSnapshotIsCurrent();
  const selected = selectedSteps();
  const effective = effectiveStepIds();
  return [
    {
      label: "Repo",
      status: git.dirty ? "warning" : "passed",
      value: git.dirty ? "dirty" : "clean",
      detail: git.branch || "branch unknown",
    },
    {
      label: "Steps",
      status: effective.length ? "passed" : "warning",
      value: `${effective.length || 0} effective`,
      detail: selected.length ? `${selected.length} explicitly selected` : "full pipeline active",
    },
    {
      label: "OpenClaw",
      status: !health ? "neutral" : healthCurrent ? (health.healthOk ? "passed" : "warning") : "warning",
      value: !health ? "unchecked" : healthCurrent ? (health.healthOk ? "ready" : "warn") : "stale",
      detail: (elements.healthAgentId.value || bootstrap.defaultOpenClawAgentId || "agent unknown"),
    },
    {
      label: "Live policy",
      status: runtime.allow_fallback_in_live ? "warning" : "passed",
      value: runtime.allow_fallback_in_live ? "relaxed" : "strict",
      detail: runtime.require_step_selection_for_live ? "explicit steps required" : "step selection optional",
    },
  ];
}

function renderReadinessGate() {
  const bootstrap = state.bootstrap || {};
  const runtime = bootstrap.snapshot?.runtime || {};
  const git = bootstrap.git || {};
  const health = state.healthSnapshot;
  const healthCurrent = healthSnapshotIsCurrent();
  const requestText = (elements.request.value || "").trim();
  const pipelineSteps = currentPipelineSteps();
  const explicitSelection = selectedSteps();
  const effectiveIds = effectiveStepIds();
  const planItems = effectivePlanItems();
  const preflightChecks = latestPreflightChecks();
  const allowedLiveSteps = Array.isArray(runtime.allowed_live_steps) ? runtime.allowed_live_steps : [];
  const usesOpenClaw = planItems.some((item) => {
    const mode = String(item.mode || "").toLowerCase();
    const agent = String(item.agent || "").toLowerCase();
    return mode === "openclaw" || agent === "openclaw";
  });
  const fallbackItems = planItems.filter((item) => item.fallbackUsed);
  const preflightProblems = preflightChecks.filter((check) =>
    ["blocked", "failed", "warning"].includes(String(check.status || "").toLowerCase()),
  );
  const liveDisallowed = state.live
    ? effectiveIds.filter((stepId) => allowedLiveSteps.length && !allowedLiveSteps.includes(stepId))
    : [];

  const checks = [
    {
      name: "Request",
      status: requestText ? "passed" : "blocked",
      summary: requestText ? "Request text is ready." : "Add request text before launching a pipeline run.",
      detail: requestText ? `${requestText.length} chars captured.` : "Diagnose and doctor can run without it, but pipeline execution cannot.",
    },
    {
      name: "Step scope",
      status: pipelineSteps.length
        ? state.live && runtime.require_step_selection_for_live && !explicitSelection.length
          ? "blocked"
          : "passed"
        : "warning",
      summary: pipelineSteps.length
        ? explicitSelection.length
          ? `Selected ${explicitSelection.length} steps; ${effectiveIds.length} effective with dependencies.`
          : `Using the full pipeline with ${effectiveIds.length} effective steps.`
        : "No steps are available for the selected pipeline.",
      detail: pipelineSteps.length
        ? state.live && runtime.require_step_selection_for_live && !explicitSelection.length
          ? "Live mode requires an explicit subset."
          : `Pipeline: ${elements.pipeline.value || bootstrap.snapshot?.defaultPipeline || "n/a"}`
        : "Refresh bootstrap or check config_v2.yaml.",
    },
    {
      name: "Live policy",
      status: !state.live
        ? "neutral"
        : liveDisallowed.length
          ? "blocked"
          : "passed",
      summary: !state.live
        ? "Dry-run ignores live launch restrictions."
        : liveDisallowed.length
          ? `Live launch is blocked by allowed_live_steps: ${liveDisallowed.join(", ")}.`
          : "Effective steps satisfy the live allow-list.",
      detail: allowedLiveSteps.length ? `Allowed: ${allowedLiveSteps.join(", ")}` : "No live allow-list configured.",
    },
    {
      name: "Repo base",
      status: git.ok === false ? "warning" : git.dirty ? "warning" : "passed",
      summary:
        git.ok === false
          ? "Git status could not be read."
          : git.dirty
            ? "Working tree is dirty; isolated live steps may start from an unexpected base."
            : "Working tree is clean.",
      detail:
        git.dirty && Array.isArray(git.changedFiles) && git.changedFiles.length
          ? `${git.changedFiles.length} changed files detected.`
          : git.branch || "Git branch unavailable.",
    },
    {
      name: "OpenClaw route",
      status: !usesOpenClaw
        ? "neutral"
        : !health
          ? "warning"
          : !healthCurrent
            ? "warning"
            : health.healthOk && health.targetAgentPresent
              ? "passed"
              : "blocked",
      summary: !usesOpenClaw
        ? "Current effective steps do not require the local OpenClaw executor."
        : !health
          ? "OpenClaw health has not been checked yet."
          : !healthCurrent
            ? `Health snapshot is stale for ${health.agentId}; refresh ${elements.healthAgentId.value || bootstrap.defaultOpenClawAgentId || "the target agent"}.`
            : health.healthOk && health.targetAgentPresent
              ? "OpenClaw target agent is reachable."
              : "OpenClaw target agent is not ready.",
      detail: usesOpenClaw
        ? `Target agent: ${elements.healthAgentId.value || bootstrap.defaultOpenClawAgentId || "n/a"}`
        : "No OpenClaw-only step selected.",
    },
    {
      name: "Memory",
      status: !usesOpenClaw
        ? "neutral"
        : !health || !healthCurrent
          ? "warning"
          : health.memory?.ok
            ? "passed"
            : "warning",
      summary: !usesOpenClaw
        ? "Embedding memory is not on the critical path for the current step set."
        : !health || !healthCurrent
          ? "Memory readiness has not been confirmed for the current agent."
          : health.memory?.ok
            ? "Embedding memory is ready."
            : "Embedding memory returned warnings.",
      detail: !usesOpenClaw
        ? "No OpenClaw memory dependency detected."
        : health?.memory?.stdout?.trim() || health?.memory?.stderr?.trim() || "No memory output captured.",
    },
    {
      name: "Fallback resolution",
      status: fallbackItems.length
        ? state.live && runtime.allow_fallback_in_live === false
          ? "blocked"
          : "warning"
        : "passed",
      summary: fallbackItems.length
        ? `${fallbackItems.length} steps currently resolve through fallback managed agents.`
        : "No fallback managed agents detected in the current plan snapshot.",
      detail: fallbackItems.length
        ? fallbackItems
            .map((item) => `${item.id} -> ${item.managedAgent || "unknown"}`)
            .join(", ")
        : "Assignment resolution is explicit.",
    },
    {
      name: "Latest preflight",
      status: !preflightChecks.length
        ? "neutral"
        : preflightProblems.some((item) => ["blocked", "failed"].includes(String(item.status || "").toLowerCase()))
          ? "blocked"
          : preflightProblems.length
            ? "warning"
            : "passed",
      summary: !preflightChecks.length
        ? "No preflight snapshot loaded yet."
        : preflightProblems.length
          ? `${preflightProblems.length} preflight checks need attention.`
          : "Latest preflight snapshot is clean.",
      detail: !preflightChecks.length
        ? "Run Preflight or load a recent run to surface the last report here."
        : `${preflightChecks.length} checks captured from the latest snapshot.`,
    },
  ];

  const status = overallStatus(checks);
  elements.readinessStateSlot.innerHTML = makeStatusChip(status);
  elements.readinessSummary.textContent =
    status === "passed"
      ? "This launch configuration is in a good state for the selected mode."
      : status === "warning"
        ? "The configuration is usable, but a few cautions should be cleared first."
        : status === "blocked"
          ? "The current configuration has blockers that should be resolved before a live launch."
          : "Readiness is waiting on more context.";
  elements.readinessChecks.innerHTML = checks
    .map(
      (check) => `
        <article class="check-row">
          <div class="result-card-header">
            <strong>${escapeHtml(check.name)}</strong>
            ${makeStatusChip(check.status)}
          </div>
          <div>${escapeHtml(check.summary)}</div>
          <small>${escapeHtml(check.detail)}</small>
        </article>
      `,
    )
    .join("");
}

function renderHeroStatus() {
  const facts = readinessFacts();
  elements.heroStatus.innerHTML = facts
    .map(
      (fact) => `
        <div class="fact">
          ${makeStatusChip(fact.status)}
          <strong>${escapeHtml(fact.label)} · ${escapeHtml(fact.value)}</strong>
          <div>${escapeHtml(fact.detail)}</div>
        </div>
      `,
    )
    .join("");
}

async function copyText(text, successMessage) {
  if (!text) {
    return;
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    setCopyFeedback(successMessage);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
  setCopyFeedback(successMessage);
}

function setMode(live) {
  state.live = Boolean(live);
  elements.modeToggle.setAttribute("aria-pressed", state.live ? "true" : "false");
  const copy = elements.modeToggle.querySelector(".toggle-copy");
  copy.textContent = state.live ? "Live" : "Dry-run";
  renderHeroStatus();
  renderReadinessGate();
}

function selectedSteps() {
  return Array.from(elements.stepGrid.querySelectorAll("input[type=checkbox]:checked")).map(
    (input) => input.value,
  );
}

function renderWorkspaceMetrics(bootstrap) {
  const git = bootstrap.git || {};
  const snapshot = bootstrap.snapshot || {};
  const runtime = snapshot.runtime || {};
  const metrics = [
    ["Repo", bootstrap.repoPath],
    ["Config", bootstrap.configPath],
    ["Branch", git.branch || "unknown"],
    ["Dirty", git.dirty ? "yes" : "no"],
    ["Default pipeline", snapshot.defaultPipeline || "n/a"],
    ["Artifacts", bootstrap.artifactsRoot || "n/a"],
    ["Live policy", runtime.allow_fallback_in_live ? "fallback allowed" : "strict"],
    ["Live steps", Array.isArray(runtime.allowed_live_steps) ? runtime.allowed_live_steps.join(", ") : "n/a"],
  ];
  elements.workspaceMetrics.innerHTML = metrics
    .map(
      ([label, value]) =>
        `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`,
    )
    .join("");
}

function renderPipelines(bootstrap) {
  const snapshot = bootstrap.snapshot || {};
  const pipelines = snapshot.pipelines || {};
  const currentPipeline = elements.pipeline.value || snapshot.defaultPipeline;
  elements.pipeline.innerHTML = Object.keys(pipelines)
    .map(
      (name) =>
        `<option value="${escapeHtml(name)}" ${name === currentPipeline ? "selected" : ""}>${escapeHtml(name)}</option>`,
    )
    .join("");
}

function renderStepGrid() {
  const bootstrap = state.bootstrap;
  if (!bootstrap) {
    return;
  }
  const snapshot = bootstrap.snapshot || {};
  const pipelines = snapshot.pipelines || {};
  const steps = pipelines[elements.pipeline.value] || [];
  const previousSelection = new Set(selectedSteps());
  elements.stepGrid.innerHTML = steps.length
    ? steps
        .map((step) => {
          const checked = previousSelection.has(step.id) ? "checked" : "";
          const depends = (step.dependsOn || []).length
            ? `Depends on: ${(step.dependsOn || []).join(", ")}`
            : "Starts clean";
          const route = step.assignment || step.profile || "n/a";
          return `
            <article class="step-card">
              <label>
                <input type="checkbox" value="${escapeHtml(step.id)}" ${checked} />
                <span>
                  <strong>${escapeHtml(step.id)}</strong>
                  ${escapeHtml(step.title)}
                </span>
              </label>
              <small>${escapeHtml(depends)}</small>
              <small>Route: ${escapeHtml(route)}</small>
            </article>
          `;
        })
        .join("")
    : `<div class="empty-state">No steps are defined for the selected pipeline.</div>`;

  elements.stepGrid.querySelectorAll("input[type=checkbox]").forEach((input) => {
    input.addEventListener("change", () => {
      renderHeroStatus();
      renderReadinessGate();
    });
  });
}

function renderRecentRuns(bootstrap) {
  const runs = bootstrap.recentRuns || [];
  if (!runs.length) {
    elements.recentRuns.innerHTML = `<div class="empty-state">No recorded runs yet.</div>`;
    return;
  }
  elements.recentRuns.innerHTML = runs
    .map((run) => {
      const counts = Object.entries(run.statusCounts || {})
        .map(([key, value]) => `${key}:${value}`)
        .join(" ");
      return `
        <article class="recent-run">
          <div class="result-card-header">
            <strong>${escapeHtml(run.runId)}</strong>
            ${makeStatusChip(run.success ? "succeeded" : "warning")}
          </div>
          <p>${escapeHtml(run.request || "No request captured.")}</p>
          <small>${escapeHtml(counts || "no status data")}</small>
          <div class="task-controls">
            <button class="ghost-button" type="button" data-run-id="${escapeHtml(run.runId)}">Load summary</button>
            <button class="ghost-button" type="button" data-cleanup-run-id="${escapeHtml(run.runId)}">Cleanup</button>
          </div>
        </article>
      `;
    })
    .join("");

  elements.recentRuns.querySelectorAll("button[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      loadHistory(button.getAttribute("data-run-id"));
    });
  });
  elements.recentRuns.querySelectorAll("button[data-cleanup-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      cleanupRun(button.getAttribute("data-cleanup-run-id")).catch((error) => {
        elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      });
    });
  });
}

function clearArtifactBrowser() {
  state.currentHistory = null;
  elements.cleanupCurrentRun.disabled = true;
  elements.artifactContext.textContent = "Load a run to browse prompts, logs, and results.";
  elements.artifactList.innerHTML = `<div class="empty-state">No run artifacts loaded yet.</div>`;
  elements.artifactViewer.innerHTML = `<div class="empty-state">Pick a file from the run to preview it here.</div>`;
}

function renderArtifactBrowser(historyPayload) {
  state.currentHistory = historyPayload;
  elements.cleanupCurrentRun.disabled = false;
  const files = historyPayload.files || [];
  elements.artifactContext.textContent = `${historyPayload.runId} · ${historyPayload.artifactsDir || "artifact dir unknown"}`;
  if (!files.length) {
    elements.artifactList.innerHTML = `<div class="empty-state">This run has no recorded artifact files.</div>`;
    elements.artifactViewer.innerHTML = `<div class="empty-state">No artifact file available to preview.</div>`;
    return;
  }

  elements.artifactList.innerHTML = `
    <div class="artifact-grid">
      ${files
        .map(
          (file) => `
            <article class="artifact-row">
              <div class="artifact-meta">
                <strong>${escapeHtml(file.kind || "file")}</strong>
                <code>${escapeHtml(file.path)}</code>
                <small>${escapeHtml(String(file.size || 0))} bytes</small>
              </div>
              <button class="ghost-button" type="button" data-artifact-path="${escapeHtml(file.path)}">Open</button>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
  elements.artifactList.querySelectorAll("button[data-artifact-path]").forEach((button) => {
    button.addEventListener("click", () => {
      loadArtifactFile(button.getAttribute("data-artifact-path"));
    });
  });
}

function renderArtifactFile(filePayload) {
  elements.artifactViewer.innerHTML = `
    <article class="result-card">
      <div class="result-card-header">
        <strong>${escapeHtml(filePayload.path)}</strong>
        ${makeStatusChip(filePayload.truncated ? "warning" : "passed")}
      </div>
      <div class="meta-list">
        <div><dt>Size</dt><dd>${escapeHtml(String(filePayload.size || 0))} bytes</dd></div>
        <div><dt>Encoding</dt><dd>${escapeHtml(filePayload.encoding || "utf-8")}</dd></div>
      </div>
      <pre>${escapeHtml(filePayload.content || "")}</pre>
    </article>
  `;
}

function renderHealthSnapshot(payload) {
  state.healthSnapshot = payload;
  renderHeroStatus();
  renderReadinessGate();
  const channels = payload.channels || [];
  const gateway = payload.gateway || {};
  const memory = payload.memory || {};
  elements.healthPanel.innerHTML = `
    <div class="health-grid">
      <article class="health-card">
        <div class="result-card-header">
          <h3>Core</h3>
          ${makeStatusChip(payload.healthOk ? "passed" : "warning")}
        </div>
        <div class="meta-list">
          <div><dt>Checked</dt><dd>${escapeHtml(payload.checkedAt || "")}</dd></div>
          <div><dt>Agent</dt><dd>${escapeHtml(payload.agentId || "")}</dd></div>
          <div><dt>Default agent</dt><dd>${escapeHtml(payload.defaultAgentId || "n/a")}</dd></div>
          <div><dt>Target present</dt><dd>${escapeHtml(payload.targetAgentPresent ? "yes" : "no")}</dd></div>
        </div>
      </article>
      <article class="health-card">
        <div class="result-card-header">
          <h3>Channels</h3>
          ${makeStatusChip(channels.every((item) => item.probeOk) ? "passed" : "warning")}
        </div>
        <div class="meta-list">
          ${
            channels.length
              ? channels
                  .map(
                    (channel) => `
                      <div>
                        <dt>${escapeHtml(channel.label || channel.name)}</dt>
                        <dd>${escapeHtml(
                          `${channel.configured ? "configured" : "not configured"} · ${channel.running ? "running" : "stopped"} · probe ${channel.probeOk ? "ok" : "warn"}`,
                        )}</dd>
                      </div>
                    `,
                  )
                  .join("")
              : `<div><dt>Channels</dt><dd>No channel data returned.</dd></div>`
          }
        </div>
      </article>
      <article class="health-card">
        <div class="result-card-header">
          <h3>Gateway</h3>
          ${makeStatusChip(gateway.ok ? "passed" : "warning")}
        </div>
        <pre>${escapeHtml((gateway.stdout || gateway.stderr || "").trim() || "No gateway output.")}</pre>
      </article>
      <article class="health-card">
        <div class="result-card-header">
          <h3>Memory</h3>
          ${makeStatusChip(memory.ok ? "passed" : "warning")}
        </div>
        <pre>${escapeHtml((memory.stdout || memory.stderr || "").trim() || "No memory output.")}</pre>
      </article>
    </div>
  `;
}

function renderBootstrap(bootstrap) {
  state.bootstrap = bootstrap;
  elements.repoPath.value = bootstrap.repoPath || "";
  elements.configPath.value = bootstrap.configPath || "";
  elements.healthAgentId.value = bootstrap.defaultOpenClawAgentId || "";
  const runtime = (bootstrap.snapshot || {}).runtime || {};
  setMode(Boolean(runtime.dry_run) === false);
  renderPipelines(bootstrap);
  renderStepGrid();
  renderWorkspaceMetrics(bootstrap);
  renderHeroStatus();
  renderReadinessGate();
  renderRecentRuns(bootstrap);
  if (!state.currentHistory) {
    clearArtifactBrowser();
  }
  updateCopyButtons();
}

function renderTask(task) {
  elements.taskStateSlot.innerHTML = makeStatusChip(task.status || "neutral");
  elements.cancelTask.disabled = !["queued", "running"].includes(task.status);
  elements.taskMeta.innerHTML = `
    <div><strong>Action:</strong> ${escapeHtml(task.action)}</div>
    <div><strong>Task id:</strong> <code>${escapeHtml(task.id)}</code></div>
    <div><strong>Created:</strong> <code>${escapeHtml(task.createdAt)}</code></div>
  `;

  const progress = task.progress || [];
  if (!progress.length) {
    elements.taskProgress.innerHTML = `<div class="empty-state">No task events yet.</div>`;
  } else {
    elements.taskProgress.innerHTML = progress
      .map(
        (event) => `
          <article class="progress-event">
            <time>${escapeHtml(event.at)}</time>
            <div>${escapeHtml(event.message)}</div>
          </article>
        `,
      )
      .join("");
  }

  if (task.result) {
    renderOutput(task.result);
  } else if (task.error) {
    elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(task.error)}</div>`;
  }
}

function renderChecks(checks) {
  return `
    <section>
      <h3>Checks</h3>
      <div class="check-grid">
        ${(checks || [])
          .map(
            (check) => `
              <article class="check-row">
                <div class="result-card-header">
                  <strong>${escapeHtml(check.name)}</strong>
                  ${makeStatusChip(check.status)}
                </div>
                <div>${escapeHtml(check.message)}</div>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderPlan(plan) {
  return `
    <section>
      <h3>Plan</h3>
      <div class="plan-grid">
        ${(plan || [])
          .map(
            (step) => `
              <article class="result-card">
                <div class="result-card-header">
                  <strong>${escapeHtml(step.id)}</strong>
                  ${makeStatusChip(step.mode)}
                </div>
                <p>${escapeHtml(step.title)}</p>
                <dl class="meta-list">
                  <div><dt>Agent</dt><dd>${escapeHtml(step.agent || "n/a")}</dd></div>
                  <div><dt>Profile</dt><dd>${escapeHtml(step.profile || "n/a")}</dd></div>
                  <div><dt>Assignment</dt><dd>${escapeHtml(step.assignment || "n/a")}</dd></div>
                  <div><dt>Managed</dt><dd>${escapeHtml(step.managedAgent || "n/a")}</dd></div>
                  <div><dt>Depends</dt><dd>${escapeHtml((step.dependsOn || []).join(", ") || "none")}</dd></div>
                </dl>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderRunResults(runResult) {
  const results = runResult.results || [];
  const visibleResults = filterResults(results);
  const counts = statusCounts(results);
  const resultMarkup = visibleResults.length
    ? visibleResults
        .map((item) => {
          const command = Array.isArray(item.command) ? item.command.join(" ") : "";
          const stdout = item.stdout || "";
          const stderr = item.stderr || "";
          const artifacts = item.artifacts || {};
          const metaRows = [
            ["Profile", item.profile],
            ["Agent", item.agent],
            ["Mode", item.mode],
            ["Workspace", artifacts.workspace_path || ""],
            ["Branch", artifacts.source_branch || artifacts.branch_name || ""],
            ["Managed agent", artifacts.managed_agent || ""],
            ["Blocked reason", artifacts.blocked_reason || ""],
          ].filter(([, value]) => value);
          return `
            <article class="result-card">
              <div class="result-card-header">
                <strong>${escapeHtml(item.work_item_id)}</strong>
                ${makeStatusChip(item.status)}
              </div>
              <p>${escapeHtml(item.summary || "")}</p>
              <dl class="meta-list">
                ${metaRows
                  .map(
                    ([label, value]) =>
                      `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`,
                  )
                  .join("")}
              </dl>
              ${
                command
                  ? `<details><summary>Command</summary><pre>${escapeHtml(command)}</pre></details>`
                  : ""
              }
              ${
                stdout
                  ? `<details><summary>Stdout</summary><pre>${escapeHtml(stdout)}</pre></details>`
                  : ""
              }
              ${
                stderr
                  ? `<details><summary>Stderr</summary><pre>${escapeHtml(stderr)}</pre></details>`
                  : ""
              }
            </article>
          `;
        })
        .join("")
    : `<div class="empty-state">No results match the current filter.</div>`;
  return `
    <section>
      <h3>Run Summary</h3>
      <div class="result-card">
        <div class="result-card-header">
          <strong>${escapeHtml(runResult.run_id || "run")}</strong>
          ${makeStatusChip(runResult.success ? "succeeded" : "warning")}
        </div>
        <dl class="meta-list">
          <div><dt>Artifacts</dt><dd>${escapeHtml(runResult.artifacts_dir || "n/a")}</dd></div>
          <div><dt>Plan steps</dt><dd>${escapeHtml(String((runResult.plan || []).length))}</dd></div>
          <div><dt>Results</dt><dd>${escapeHtml(String(results.length))}</dd></div>
          <div><dt>Status counts</dt><dd>${escapeHtml(formatCounts(counts))}</dd></div>
          <div><dt>Visible filter</dt><dd>${escapeHtml(state.resultFilter)}</dd></div>
        </dl>
      </div>
      <div class="result-grid">${resultMarkup}</div>
    </section>
  `;
}

function updateCopyButtons() {
  const runPayload = extractRunPayload(state.currentOutput);
  const enabled = Boolean(runPayload?.runResult);
  elements.copyRunSummary.disabled = !enabled;
  elements.copyIssueUpdate.disabled = !enabled;
  elements.copyPrNote.disabled = !enabled;
}

function generateRunSummaryText() {
  const runPayload = extractRunPayload(state.currentOutput);
  if (!runPayload) {
    return "";
  }
  const runResult = runPayload.runResult;
  const results = runResult.results || [];
  const counts = formatCounts(statusCounts(results));
  const actionable = actionableResults(results);
  const lines = [
    `Run ID: ${runResult.run_id || "n/a"}`,
    `Pipeline: ${runPayload.pipeline || "n/a"}`,
    `Request: ${runPayload.request || "n/a"}`,
    `Success: ${runResult.success ? "yes" : "no"}`,
    `Artifacts: ${runResult.artifacts_dir || "n/a"}`,
    `Status counts: ${counts}`,
  ];
  if (actionable.length) {
    lines.push("", "Actionable results:");
    for (const item of actionable) {
      lines.push(`- ${item.work_item_id}: [${item.status}] ${item.summary}`);
    }
  }
  return lines.join("\n");
}

function generateIssueUpdateText() {
  const runPayload = extractRunPayload(state.currentOutput);
  if (!runPayload) {
    return "";
  }
  const runResult = runPayload.runResult;
  const results = runResult.results || [];
  const actionable = actionableResults(results);
  const lines = [
    "OpenClaw progress update",
    "",
    `- Run: ${runResult.run_id || "n/a"}`,
    `- Pipeline: ${runPayload.pipeline || "n/a"}`,
    `- Request: ${runPayload.request || "n/a"}`,
    `- Success: ${runResult.success ? "yes" : "no"}`,
    `- Status counts: ${formatCounts(statusCounts(results))}`,
  ];
  if (actionable.length) {
    lines.push("- Actionable items:");
    for (const item of actionable) {
      lines.push(`  - ${item.work_item_id}: [${item.status}] ${item.summary}`);
    }
  } else {
    lines.push("- Actionable items: none");
  }
  return lines.join("\n");
}

function generatePrNoteText() {
  const runPayload = extractRunPayload(state.currentOutput);
  if (!runPayload) {
    return "";
  }
  const runResult = runPayload.runResult;
  const branch = primaryBranch(runResult);
  const readiness = readinessFacts()
    .map((fact) => `${fact.label}:${fact.value}`)
    .join(" · ");
  const lines = [
    "PR-ready note",
    "",
    `Run: ${runResult.run_id || "n/a"}`,
    `Pipeline: ${runPayload.pipeline || "n/a"}`,
    `Request: ${runPayload.request || "n/a"}`,
    `Branch: ${branch || "n/a"}`,
    `Readiness: ${readiness}`,
    `Status counts: ${formatCounts(statusCounts(runResult.results || []))}`,
  ];
  return lines.join("\n");
}

function renderOutput(payload) {
  state.currentOutput = payload;
  updateCopyButtons();
  const chunks = [];
  if (payload.mode === "doctor") {
    chunks.push(renderChecks(payload.checks || []));
  }
  if (payload.plan) {
    chunks.push(renderPlan(payload.plan));
  }
  if (payload.preflight && payload.preflight.checks) {
    chunks.push(renderChecks(payload.preflight.checks));
  }
  if (payload.runResult) {
    chunks.push(renderRunResults(payload.runResult));
  }
  if (payload.summary) {
    chunks.push(renderRunResults(payload.summary));
  }
  elements.outputPane.innerHTML = chunks.join("") || `<div class="empty-state">No output captured.</div>`;
  if (payload.history) {
    renderArtifactBrowser(payload.history);
  } else if (payload.summary && payload.files) {
    renderArtifactBrowser(payload);
  } else {
    clearArtifactBrowser();
  }
  renderReadinessGate();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json();
}

async function loadBootstrap() {
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
    pipeline: elements.pipeline.value || "",
  });
  const payload = await fetchJson(`/api/bootstrap?${query.toString()}`);
  renderBootstrap(payload);
  setCopyFeedback("Plan, preflight, run summary, and step results.");
}

async function loadHistory(runId) {
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
  });
  const payload = await fetchJson(`/api/history/${encodeURIComponent(runId)}?${query.toString()}`);
  renderOutput(payload);
}

async function loadArtifactFile(relativePath) {
  if (!state.currentHistory) {
    return;
  }
  elements.artifactViewer.innerHTML = `<div class="empty-state">Loading ${escapeHtml(relativePath)}...</div>`;
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
    path: relativePath,
  });
  const payload = await fetchJson(
    `/api/history/${encodeURIComponent(state.currentHistory.runId)}/file?${query.toString()}`,
  );
  renderArtifactFile(payload);
}

async function loadHealth() {
  elements.healthPanel.innerHTML = `<div class="empty-state">Checking OpenClaw health...</div>`;
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
    agentId: elements.healthAgentId.value || "",
  });
  const payload = await fetchJson(`/api/system/health?${query.toString()}`);
  renderHealthSnapshot(payload);
}

async function cleanupRun(runId) {
  const confirmed = window.confirm(`Cleanup run ${runId}? This removes its artifact folder and any retained orchestration worktrees.`);
  if (!confirmed) {
    return;
  }
  elements.housekeepingStatus.textContent = `Cleaning up ${runId}...`;
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
  });
  const payload = await fetchJson(`/api/history/${encodeURIComponent(runId)}/cleanup?${query.toString()}`, {
    method: "POST",
    body: JSON.stringify({
      removeWorktrees: true,
      removeArtifacts: true,
    }),
  });
  elements.housekeepingStatus.textContent = `Cleaned ${runId}. Operations: ${(payload.operations || []).length}.`;
  if (state.currentHistory && state.currentHistory.runId === runId) {
    clearArtifactBrowser();
    elements.outputPane.innerHTML = `<div class="empty-state">Run ${escapeHtml(runId)} was cleaned up.</div>`;
  }
  await loadBootstrap();
}

async function pruneRuns() {
  const keepLatest = Number(elements.pruneKeepLatest.value || "10");
  const confirmed = window.confirm(`Prune old runs and keep the latest ${keepLatest}?`);
  if (!confirmed) {
    return;
  }
  elements.housekeepingStatus.textContent = `Pruning runs, keeping latest ${keepLatest}...`;
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
  });
  const payload = await fetchJson(`/api/history/prune?${query.toString()}`, {
    method: "POST",
    body: JSON.stringify({
      keepLatest,
      removeWorktrees: true,
      removeArtifacts: true,
    }),
  });
  elements.housekeepingStatus.textContent = `Pruned ${payload.removed.length} runs.`;
  if (state.currentHistory && (payload.removed || []).some((item) => item.runId === state.currentHistory.runId)) {
    clearArtifactBrowser();
  }
  await loadBootstrap();
}

function taskPayload(action) {
  return {
    action,
    repoPath: elements.repoPath.value,
    configPath: elements.configPath.value,
    pipeline: elements.pipeline.value,
    request: elements.request.value,
    steps: selectedSteps(),
    live: state.live,
  };
}

async function submitTask(action) {
  const payload = taskPayload(action);
  const response = await fetchJson("/api/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const task = response.task;
  state.currentTaskId = task.id;
  renderTask(task);
  openTaskStream(task.id);
}

function closeTaskStream() {
  if (state.taskStream) {
    state.taskStream.close();
    state.taskStream = null;
  }
}

function openTaskStream(taskId) {
  closeTaskStream();
  const stream = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/events`);
  state.taskStream = stream;
  stream.addEventListener("task", (event) => {
    const payload = JSON.parse(event.data);
    const task = payload.task;
    renderTask(task);
    if (["completed", "failed", "cancelled"].includes(task.status)) {
      closeTaskStream();
      loadBootstrap().catch((error) => {
        elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      });
    }
  });
  stream.onerror = () => {
    closeTaskStream();
    fetchJson(`/api/tasks/${encodeURIComponent(taskId)}`)
      .then((payload) => {
        renderTask(payload.task);
        if (["completed", "failed", "cancelled"].includes(payload.task.status)) {
          return loadBootstrap();
        }
        elements.outputPane.innerHTML = `<div class="empty-state">Live stream disconnected. Refresh or relaunch the task feed.</div>`;
      })
      .catch((error) => {
        elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      });
  };
}

async function cancelCurrentTask() {
  if (!state.currentTaskId) {
    return;
  }
  const payload = await fetchJson(`/api/tasks/${encodeURIComponent(state.currentTaskId)}/cancel`, {
    method: "POST",
  });
  renderTask(payload.task);
}

function bindEvents() {
  elements.refreshBootstrap.addEventListener("click", () => {
    loadBootstrap()
      .then(() => loadHealth())
      .catch((error) => {
        elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      });
  });

  elements.pipeline.addEventListener("change", () => {
    loadBootstrap()
      .then(() => loadHealth())
      .catch((error) => {
        elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      });
  });

  elements.resultFilter.addEventListener("change", () => {
    state.resultFilter = elements.resultFilter.value;
    if (state.currentOutput) {
      renderOutput(state.currentOutput);
    }
    renderReadinessGate();
  });

  elements.checkHealth.addEventListener("click", () => {
    loadHealth().catch((error) => {
      elements.healthPanel.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  });

  elements.healthAgentId.addEventListener("input", () => {
    renderHeroStatus();
    renderReadinessGate();
  });

  elements.pruneRuns.addEventListener("click", () => {
    pruneRuns().catch((error) => {
      elements.housekeepingStatus.textContent = error.message;
    });
  });

  elements.cancelTask.addEventListener("click", () => {
    cancelCurrentTask().catch((error) => {
      elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  });

  elements.cleanupCurrentRun.addEventListener("click", () => {
    if (!state.currentHistory) {
      return;
    }
    cleanupRun(state.currentHistory.runId).catch((error) => {
      elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  });

  elements.copyRunSummary.addEventListener("click", () => {
    copyText(generateRunSummaryText(), "Copied run summary.").catch((error) => {
      setCopyFeedback(error.message);
    });
  });

  elements.copyIssueUpdate.addEventListener("click", () => {
    copyText(generateIssueUpdateText(), "Copied issue update.").catch((error) => {
      setCopyFeedback(error.message);
    });
  });

  elements.copyPrNote.addEventListener("click", () => {
    copyText(generatePrNoteText(), "Copied PR note.").catch((error) => {
      setCopyFeedback(error.message);
    });
  });

  elements.modeToggle.addEventListener("click", () => {
    setMode(!state.live);
  });

  elements.request.addEventListener("input", () => {
    renderReadinessGate();
  });

  elements.selectAll.addEventListener("click", () => {
    elements.stepGrid.querySelectorAll("input[type=checkbox]").forEach((input) => {
      input.checked = true;
    });
    renderHeroStatus();
    renderReadinessGate();
  });

  elements.selectNone.addEventListener("click", () => {
    elements.stepGrid.querySelectorAll("input[type=checkbox]").forEach((input) => {
      input.checked = false;
    });
    renderHeroStatus();
    renderReadinessGate();
  });

  elements.buttons.forEach((button) => {
    button.addEventListener("click", () => {
      submitTask(button.dataset.action).catch((error) => {
        elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      });
    });
  });
}

async function boot() {
  bindEvents();
  await loadBootstrap();
  await loadHealth().catch((error) => {
    setCopyFeedback(`Health check skipped: ${error.message}`);
  });
  elements.cancelTask.disabled = true;
  elements.cleanupCurrentRun.disabled = true;
  updateCopyButtons();
}

boot().catch((error) => {
  elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});
