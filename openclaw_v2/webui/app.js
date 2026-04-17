const state = {
  bootstrap: null,
  currentTaskId: null,
  taskStream: null,
  live: false,
  currentHistory: null,
  healthSnapshot: null,
  currentOutput: null,
  currentTaskStatus: "idle",
  resultFilter: "all",
  comparePayload: null,
};

const elements = {
  repoPath: document.getElementById("repo-path"),
  configPath: document.getElementById("config-path"),
  pipeline: document.getElementById("pipeline"),
  request: document.getElementById("request"),
  stepGrid: document.getElementById("step-grid"),
  requestPresets: document.getElementById("request-presets"),
  refreshBootstrap: document.getElementById("refresh-bootstrap"),
  modeToggle: document.getElementById("mode-toggle"),
  workspaceMetrics: document.getElementById("workspace-metrics"),
  launchBrief: document.getElementById("launch-brief"),
  heroStatus: document.getElementById("hero-status"),
  pipelineRadar: document.getElementById("pipeline-radar"),
  pipelineDag: document.getElementById("pipeline-dag"),
  githubBridge: document.getElementById("github-bridge"),
  hermesPanel: document.getElementById("hermes-panel"),
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
  compareLeftRun: document.getElementById("compare-left-run"),
  compareRightRun: document.getElementById("compare-right-run"),
  runCompare: document.getElementById("run-compare"),
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

const STATUS_CHIP_TONES = {
  neutral: "neutral",
  idle: "neutral",
  queued: "neutral",
  running: "running",
  succeeded: "succeeded",
  success: "succeeded",
  passed: "passed",
  completed: "completed",
  ready: "passed",
  ok: "passed",
  failed: "failed",
  error: "failed",
  blocked: "blocked",
  skipped: "skipped",
  warning: "warning",
  warn: "warning",
  cancelled: "cancelled",
  canceled: "cancelled",
};

function normalizeStatusLabel(value) {
  return String(value || "neutral").trim().toLowerCase() || "neutral";
}

function statusChipTone(value) {
  return STATUS_CHIP_TONES[normalizeStatusLabel(value)] || "neutral";
}

function makeStatusChip(value) {
  const normalized = normalizeStatusLabel(value);
  const tone = statusChipTone(normalized);
  return `<span class="status-chip ${tone}">${escapeHtml(normalized)}</span>`;
}

function compactPath(value, keepSegments = 3) {
  const text = String(value || "").trim();
  if (!text) {
    return "n/a";
  }
  const normalized = text.replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= keepSegments) {
    return normalized.startsWith("/") ? `/${parts.join("/")}` : normalized;
  }
  return `…/${parts.slice(-keepSegments).join("/")}`;
}

function formatAbsoluteTime(value) {
  if (!value) {
    return "unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRelativeTime(value) {
  if (!value) {
    return "time unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const diffMs = date.getTime() - Date.now();
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (Math.abs(diffMs) < hour) {
    return formatter.format(Math.round(diffMs / minute), "minute");
  }
  if (Math.abs(diffMs) < day) {
    return formatter.format(Math.round(diffMs / hour), "hour");
  }
  return formatter.format(Math.round(diffMs / day), "day");
}

function safeExternalUrl(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return /^https?:\/\//i.test(text) ? text : "";
}

function currentHistoryPayload() {
  if (state.currentHistory) {
    return state.currentHistory;
  }
  if (state.currentOutput?.history) {
    return state.currentOutput.history;
  }
  if (state.currentOutput?.summary && state.currentOutput?.files) {
    return state.currentOutput;
  }
  return null;
}

function activeRunInsights() {
  const history = currentHistoryPayload();
  if (history?.insights) {
    return history.insights;
  }
  const latestRun = state.bootstrap?.recentRuns?.[0];
  return latestRun?.insights || null;
}

function activeRunId() {
  const history = currentHistoryPayload();
  if (history?.runId) {
    return history.runId;
  }
  if (state.currentOutput?.runResult?.run_id) {
    return state.currentOutput.runResult.run_id;
  }
  return state.bootstrap?.recentRuns?.[0]?.runId || "";
}

function routeSequence(stepIds) {
  return (stepIds || []).join(" → ") || "No steps selected";
}

function setCopyFeedback(message) {
  elements.copyFeedback.textContent = message;
}

function updateActionButtons() {
  const requestReady = Boolean((elements.request.value || "").trim());
  const taskActive = ["queued", "running"].includes(state.currentTaskStatus);
  elements.buttons.forEach((button) => {
    if (taskActive) {
      button.disabled = true;
      return;
    }
    if (button.dataset.action === "run") {
      button.disabled = !requestReady;
      return;
    }
    button.disabled = false;
  });
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

function renderLaunchBrief() {
  const bootstrap = state.bootstrap || {};
  const snapshot = bootstrap.snapshot || {};
  const git = bootstrap.git || {};
  const pipelineName = elements.pipeline.value || snapshot.defaultPipeline || "n/a";
  const requestText = (elements.request.value || "").trim();
  const effectiveIds = effectiveStepIds();
  const explicitSelection = selectedSteps();
  const planItems = effectivePlanItems();
  const fallbackCount = planItems.filter((item) => item.fallbackUsed).length;
  const owners = Array.from(
    new Set(
      planItems
        .map((item) => item.managedAgent || item.assignment || item.profile || "")
        .filter(Boolean),
    ),
  );
  const usesGitHub = planItems.some((item) => String(item.mode || "").toLowerCase() === "github");
  const tone = !requestText ? "warning" : git.dirty ? "warning" : "passed";
  elements.launchBrief.innerHTML = `
    <div class="brief-banner">
      <div>
        <span class="eyebrow">Current Vector</span>
        <strong>${escapeHtml(pipelineName)} · ${escapeHtml(state.live ? "Live" : "Dry-run")}</strong>
        <p>${escapeHtml(routeSequence(effectiveIds))}</p>
      </div>
      ${makeStatusChip(tone)}
    </div>
    <div class="brief-grid">
      <article class="brief-card">
        <span class="brief-label">Request</span>
        <strong>${escapeHtml(requestText ? "Ready" : "Missing")}</strong>
        <small>${escapeHtml(requestText ? `${requestText.length} chars captured` : "Add intent before launching a run.")}</small>
      </article>
      <article class="brief-card">
        <span class="brief-label">Scope</span>
        <strong>${escapeHtml(`${effectiveIds.length} effective steps`)}</strong>
        <small>${escapeHtml(explicitSelection.length ? `${explicitSelection.length} explicitly selected` : "Full pipeline currently in play")}</small>
      </article>
      <article class="brief-card">
        <span class="brief-label">Repo Base</span>
        <strong>${escapeHtml(git.dirty ? "Dirty" : "Clean")}</strong>
        <small>${escapeHtml(git.branch || "branch unknown")}</small>
      </article>
      <article class="brief-card">
        <span class="brief-label">Tail</span>
        <strong>${escapeHtml(usesGitHub ? "GitHub armed" : "Local only")}</strong>
        <small>${escapeHtml(fallbackCount ? `${fallbackCount} fallback routes active` : "Assignments are explicit")}</small>
      </article>
    </div>
    <div class="brief-note">
      <strong>Execution owners</strong>
      <span>${escapeHtml(owners.join(" · ") || "No managed agents resolved yet")}</span>
    </div>
  `;
}

function renderPipelineRadar() {
  const steps = currentPipelineSteps();
  if (!steps.length) {
    elements.pipelineRadar.innerHTML = `<div class="empty-state">No steps are defined for the selected pipeline.</div>`;
    return;
  }

  const effectiveSet = new Set(effectiveStepIds());
  const explicitSet = new Set(selectedSteps());
  const planMap = currentPlanMap();
  const activeCount = Array.from(effectiveSet).length;
  elements.pipelineRadar.innerHTML = `
    <div class="radar-summary">
      <div>
        <strong>Effective route</strong>
        <p>${escapeHtml(routeSequence(Array.from(effectiveSet)))}</p>
      </div>
      <small>${escapeHtml(`${activeCount} active · ${steps.length - activeCount} parked`)}</small>
    </div>
    <div class="radar-strip">
      ${steps
        .map((step, index) => {
          const planItem = planMap.get(step.id) || {};
          const isEffective = effectiveSet.has(step.id);
          const isSelected = explicitSet.has(step.id);
          const badges = [];
          if (isSelected) {
            badges.push('<span class="route-badge tone-accent">selected</span>');
          } else if (isEffective) {
            badges.push('<span class="route-badge tone-teal">dependency</span>');
          } else {
            badges.push('<span class="route-badge tone-muted">parked</span>');
          }
          if (planItem.fallbackUsed) {
            badges.push('<span class="route-badge tone-gold">fallback</span>');
          }
          const mode = String(planItem.mode || "").toLowerCase();
          if (mode === "github") {
            badges.push('<span class="route-badge tone-ink">github</span>');
          } else if (mode === "openclaw" || mode === "hermes") {
            badges.push(`<span class="route-badge tone-teal">${escapeHtml(mode)}</span>`);
          }
          const routeOwner = planItem.managedAgent || step.assignment || step.profile || "n/a";
          const depends = (step.dependsOn || []).join(", ") || "none";
          return `
            <article class="route-node ${isEffective ? "effective" : "inactive"}">
              <div class="route-node-top">
                <span class="route-index">${escapeHtml(String(index + 1))}</span>
                <div class="route-badges">${badges.join("")}</div>
              </div>
              <strong>${escapeHtml(step.id)}</strong>
              <p>${escapeHtml(step.title)}</p>
              <small>Route: ${escapeHtml(routeOwner)}</small>
              <small>Depends on: ${escapeHtml(depends)}</small>
            </article>
            ${index < steps.length - 1 ? '<div class="route-link" aria-hidden="true">→</div>' : ""}
          `;
        })
        .join("")}
    </div>
  `;
}

function renderPipelineDag() {
  const steps = currentPipelineSteps();
  if (!steps.length) {
    elements.pipelineDag.innerHTML = `<div class="empty-state">No steps are defined for the selected pipeline.</div>`;
    return;
  }

  const effectiveSet = new Set(effectiveStepIds());
  const explicitSet = new Set(selectedSteps());
  const planMap = currentPlanMap();
  const stepMap = new Map(steps.map((step) => [step.id, step]));
  const depthCache = new Map();

  function depthFor(stepId, trail = new Set()) {
    if (depthCache.has(stepId)) {
      return depthCache.get(stepId);
    }
    if (trail.has(stepId)) {
      return 0;
    }
    const step = stepMap.get(stepId);
    if (!step || !(step.dependsOn || []).length) {
      depthCache.set(stepId, 0);
      return 0;
    }
    const nextTrail = new Set(trail);
    nextTrail.add(stepId);
    const depth = Math.max(...(step.dependsOn || []).map((dependency) => depthFor(dependency, nextTrail))) + 1;
    depthCache.set(stepId, depth);
    return depth;
  }

  const columns = [];
  for (const step of steps) {
    const depth = depthFor(step.id);
    if (!columns[depth]) {
      columns[depth] = [];
    }
    columns[depth].push(step);
  }

  elements.pipelineDag.innerHTML = `
    <div class="dag-lanes">
      ${columns
        .filter(Boolean)
        .map(
          (column, index) => `
            <section class="dag-stage">
              <div class="stage-label">
                <strong>${escapeHtml(`Stage ${index + 1}`)}</strong>
                <small>${escapeHtml(`${column.length} nodes`)}</small>
              </div>
              ${column
                .map((step) => {
                  const planItem = planMap.get(step.id) || {};
                  const isEffective = effectiveSet.has(step.id);
                  const isSelected = explicitSet.has(step.id);
                  const mode = String(planItem.mode || "").toLowerCase();
                  const badges = [];
                  if (isSelected) {
                    badges.push('<span class="route-badge tone-accent">selected</span>');
                  } else if (isEffective) {
                    badges.push('<span class="route-badge tone-teal">active</span>');
                  } else {
                    badges.push('<span class="route-badge tone-muted">parked</span>');
                  }
                  if (planItem.fallbackUsed) {
                    badges.push('<span class="route-badge tone-gold">fallback</span>');
                  }
                  if (mode) {
                    badges.push(`<span class="route-badge tone-ink">${escapeHtml(mode)}</span>`);
                  }
                  return `
                    <article class="dag-node ${isEffective ? "effective" : "parked"}">
                      <div class="result-card-header">
                        <strong>${escapeHtml(step.id)}</strong>
                        ${makeStatusChip(isEffective ? "passed" : "neutral")}
                      </div>
                      <p>${escapeHtml(step.title)}</p>
                      <div class="dag-stack">${badges.join("")}</div>
                      <small>${escapeHtml(`Depends on: ${(step.dependsOn || []).join(", ") || "none"}`)}</small>
                      <small>${escapeHtml(`Route: ${planItem.managedAgent || step.assignment || step.profile || "n/a"}`)}</small>
                    </article>
                  `;
                })
                .join("")}
            </section>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderGitHubBridge() {
  const overview = state.bootstrap?.integrations?.github || {};
  const github = activeRunInsights()?.github || {};
  const cards = github.cards || [];
  const repo = github.repo || overview.repo || "";
  const branch = github.branch || "";
  const repoUrl = repo ? `https://github.com/${repo}` : "";
  const runId = activeRunId();
  const checks = github.checks || [];

  if (!repo && !cards.length && !checks.length) {
    elements.githubBridge.innerHTML = `<div class="empty-state">Run a GitHub-enabled pipeline or load a run with branch / issue / PR artifacts.</div>`;
    return;
  }

  elements.githubBridge.innerHTML = `
    <div class="bridge-grid">
      <article class="bridge-card">
        <div class="result-card-header">
          <strong>Repository</strong>
          ${makeStatusChip(repo ? "passed" : "warning")}
        </div>
        <p>${escapeHtml(repo || "Repository not resolved yet")}</p>
        <small>${escapeHtml(`Base branch: ${overview.baseBranch || "main"}`)}</small>
        ${repoUrl ? `<a class="bridge-link" href="${escapeHtml(repoUrl)}" target="_blank" rel="noreferrer">Open repo</a>` : ""}
      </article>
      <article class="bridge-card">
        <div class="result-card-header">
          <strong>Active run</strong>
          ${makeStatusChip(runId ? "passed" : "neutral")}
        </div>
        <p>${escapeHtml(runId || "No run loaded")}</p>
        <small>${escapeHtml(branch ? `Branch: ${branch}` : "Branch will surface after publish_branch.")}</small>
      </article>
      <article class="bridge-card">
        <div class="result-card-header">
          <strong>Repo source</strong>
          ${makeStatusChip(repo ? "passed" : "warning")}
        </div>
        <p>${escapeHtml(overview.repoSource || "unknown")}</p>
        <small>${escapeHtml(overview.useOriginRemoteFallback ? "Origin fallback enabled" : "Config-pinned repo")}</small>
      </article>
      ${
        cards.length
          ? cards
              .map((card) => {
                const url = safeExternalUrl(card.url);
                const number = card.number || card.branch || "";
                const workflowTail = card.workflowConclusion || card.workflowStatus || "";
                return `
                  <article class="bridge-card">
                    <div class="result-card-header">
                      <strong>${escapeHtml(card.title || card.stepId || card.kind)}</strong>
                      ${makeStatusChip(card.status || "neutral")}
                    </div>
                    <p>${escapeHtml(card.kind === "branch" ? card.branch || "branch pending" : number || "link pending")}</p>
                    <small>${escapeHtml(workflowTail || card.stepId || "")}</small>
                    ${url ? `<a class="bridge-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">Open ${escapeHtml(card.kind)}</a>` : ""}
                  </article>
                `;
              })
              .join("")
          : `<div class="inline-note">No GitHub bridge artifacts are attached to the active run yet.</div>`
      }
      ${
        checks.length
          ? `<article class="bridge-card">
              <div class="result-card-header">
                <strong>GitHub preflight</strong>
                ${makeStatusChip(checks.some((item) => item.status === "failed") ? "warning" : "passed")}
              </div>
              <div class="chip-row">
                ${checks
                  .map(
                    (check) =>
                      `${makeStatusChip(check.status)} <span class="inline-note">${escapeHtml(check.name)}</span>`,
                  )
                  .join("")}
              </div>
            </article>`
          : ""
      }
    </div>
  `;
}

function renderHermesPanel() {
  const overview = state.bootstrap?.integrations?.hermes || {};
  const hermes = activeRunInsights()?.hermes || {};
  const roles = hermes.roles || [];
  const checks = hermes.checks || [];

  if (!overview.enabled && !roles.length && !checks.length) {
    elements.hermesPanel.innerHTML = `<div class="empty-state">Hermes is not configured in the current snapshot.</div>`;
    return;
  }

  elements.hermesPanel.innerHTML = `
    <div class="hermes-grid">
      <article class="hermes-card">
        <div class="result-card-header">
          <strong>Runtime</strong>
          ${makeStatusChip(overview.commandAvailable ? "passed" : "warning")}
        </div>
        <p>${escapeHtml(overview.commandAvailable ? "Hermes command available" : "Hermes command missing")}</p>
        <small>${escapeHtml(overview.configPath || "")}</small>
      </article>
      <article class="hermes-card">
        <div class="result-card-header">
          <strong>Profiles</strong>
          ${makeStatusChip((overview.profiles || []).length ? "passed" : "neutral")}
        </div>
        <p>${escapeHtml(String((overview.profiles || []).length || 0))}</p>
        <small>${escapeHtml((overview.profiles || []).map((item) => item.name).join(" · ") || "No Hermes profile registered")}</small>
      </article>
      <article class="hermes-card">
        <div class="result-card-header">
          <strong>Roles</strong>
          ${makeStatusChip((overview.roles || []).length ? "passed" : "neutral")}
        </div>
        <p>${escapeHtml(String((overview.roles || []).length || 0))}</p>
        <small>${escapeHtml((overview.roles || []).map((item) => `${item.name}:${item.role}`).join(" · ") || "No Hermes managed agent role")}</small>
      </article>
      <article class="hermes-card">
        <div class="result-card-header">
          <strong>Live sessions</strong>
          ${makeStatusChip(roles.length ? "passed" : "neutral")}
        </div>
        <p>${escapeHtml(String(hermes.sessionCount || 0))}</p>
        <small>${escapeHtml(roles.length ? `from ${activeRunId()}` : "Load a Hermes-backed run to inspect session traces.")}</small>
      </article>
      ${
        (overview.profiles || [])
          .map(
            (profile) => `
              <article class="hermes-card">
                <div class="result-card-header">
                  <strong>${escapeHtml(profile.name)}</strong>
                  ${makeStatusChip("passed")}
                </div>
                <p>${escapeHtml(profile.provider || "provider:auto")} · ${escapeHtml(profile.model || "model:auto")}</p>
                <small>${escapeHtml(`source:${profile.source || "tool"} · maxTurns:${profile.maxTurns || 0}`)}</small>
                <div class="chip-row">
                  ${(profile.toolsets || [])
                    .map((item) => `<span class="route-badge tone-teal">${escapeHtml(item)}</span>`)
                    .join("")}
                </div>
              </article>
            `,
          )
          .join("")
      }
      ${
        roles.length
          ? roles
              .map(
                (role) => `
                  <article class="hermes-card">
                    <div class="result-card-header">
                      <strong>${escapeHtml(role.title || role.stepId)}</strong>
                      ${makeStatusChip(role.status || "neutral")}
                    </div>
                    <p>${escapeHtml(`${role.role || "support"}${role.sessionId ? ` · ${role.sessionId}` : ""}`)}</p>
                    <small>${escapeHtml(`${role.provider || "provider:auto"} · ${role.model || "model:auto"}`)}</small>
                  </article>
                `,
              )
              .join("")
          : `<div class="inline-note">No Hermes step output is attached to the active run yet.</div>`
      }
      ${
        (overview.pipelines || []).length
          ? `<article class="hermes-card">
              <div class="result-card-header">
                <strong>Hermes pipelines</strong>
                ${makeStatusChip("passed")}
              </div>
              <div class="chip-row">
                ${(overview.pipelines || [])
                  .map(
                    (pipeline) =>
                      `<span class="route-badge tone-ink">${escapeHtml(`${pipeline.name} · ${pipeline.stepCount}`)}</span>`,
                  )
                  .join("")}
              </div>
            </article>`
          : ""
      }
      ${
        checks.length
          ? `<article class="hermes-card">
              <div class="result-card-header">
                <strong>Hermes checks</strong>
                ${makeStatusChip(checks.some((item) => item.status === "failed") ? "warning" : "passed")}
              </div>
              <div class="chip-row">
                ${checks
                  .map(
                    (check) =>
                      `${makeStatusChip(check.status)} <span class="inline-note">${escapeHtml(check.name)}</span>`,
                  )
                  .join("")}
              </div>
            </article>`
          : ""
      }
    </div>
  `;
}

function renderCompareSelectors(bootstrap) {
  const runs = bootstrap?.recentRuns || [];
  const options = runs
    .map(
      (run) =>
        `<option value="${escapeHtml(run.runId)}">${escapeHtml(`${run.runId} · ${formatRelativeTime(run.updatedAt)}`)}</option>`,
    )
    .join("");

  elements.compareLeftRun.innerHTML = options;
  elements.compareRightRun.innerHTML = options;
  elements.compareLeftRun.disabled = runs.length < 2;
  elements.compareRightRun.disabled = runs.length < 2;

  if (runs.length >= 2) {
    const currentLeft = runs.some((run) => run.runId === elements.compareLeftRun.value)
      ? elements.compareLeftRun.value
      : runs[0].runId;
    const preferredRight = runs.some((run) => run.runId === elements.compareRightRun.value)
      ? elements.compareRightRun.value
      : runs[1].runId;
    elements.compareLeftRun.value = currentLeft;
    elements.compareRightRun.value = currentLeft === preferredRight ? runs[1].runId : preferredRight;
    return;
  }

  if (runs.length === 1) {
    elements.compareLeftRun.value = runs[0].runId;
    elements.compareRightRun.value = runs[0].runId;
  }
}

function renderRunCompare(payload) {
  if (!payload || !(payload.runs || []).length) {
    elements.runCompare.innerHTML = `<div class="empty-state">Pick two recent runs to compare their execution signatures.</div>`;
    return;
  }

  const runs = payload.runs || [];
  const comparison = payload.comparison || {};
  elements.runCompare.innerHTML = `
    <div class="compare-grid">
      ${runs
        .map(
          (run) => `
            <article class="compare-run-card">
              <div class="result-card-header">
                <strong>${escapeHtml(run.runId)}</strong>
                ${makeStatusChip(run.success ? "succeeded" : "warning")}
              </div>
              <p>${escapeHtml(run.request || "No request captured.")}</p>
              <small>${escapeHtml(`updated ${formatAbsoluteTime(run.updatedAt)}`)}</small>
              <div class="chip-row">
                ${Object.entries(run.insights?.statusCounts || {})
                  .map(
                    ([status, value]) =>
                      `<span class="route-badge tone-ink">${escapeHtml(`${status}:${value}`)}</span>`,
                  )
                  .join("")}
              </div>
              <small>${escapeHtml(`branch: ${run.insights?.github?.branch || "n/a"}`)}</small>
              <small>${escapeHtml(`Hermes sessions: ${run.insights?.hermes?.sessionCount || 0}`)}</small>
            </article>
          `,
        )
        .join("")}
      <article class="diff-card">
        <div class="result-card-header">
          <strong>Count delta</strong>
          ${makeStatusChip((comparison.stepDiffs || []).length ? "warning" : "passed")}
        </div>
        <div class="chip-row">
          ${(comparison.countDiffs || [])
            .map(
              (item) =>
                `<span class="route-badge ${item.delta > 0 ? "tone-teal" : item.delta < 0 ? "tone-accent" : "tone-muted"}">${escapeHtml(`${item.status}: ${item.left} → ${item.right}`)}</span>`,
            )
            .join("")}
        </div>
        <small>${escapeHtml(`Branch changed: ${comparison.branchChanged ? "yes" : "no"} · Workflow changed: ${comparison.workflowChanged ? "yes" : "no"} · Hermes session delta: ${comparison.hermesSessionDelta || 0}`)}</small>
      </article>
      ${
        (comparison.stepDiffs || []).length
          ? (comparison.stepDiffs || [])
              .map(
                (item) => `
                  <article class="diff-card">
                    <div class="result-card-header">
                      <strong>${escapeHtml(item.stepId)}</strong>
                      ${makeStatusChip(item.left === "missing" || item.right === "missing" ? "warning" : "blocked")}
                    </div>
                    <p>${escapeHtml(`${item.left} → ${item.right}`)}</p>
                  </article>
                `,
              )
              .join("")
          : `<div class="inline-note">No step-status delta detected between the selected runs.</div>`
      }
    </div>
  `;
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
  renderLaunchBrief();
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
  const statCards = [
    {
      label: "Branch",
      value: git.branch || "unknown",
      detail: git.dirty ? "dirty working tree" : "clean working tree",
    },
    {
      label: "Pipeline",
      value: snapshot.defaultPipeline || "n/a",
      detail: `${Object.keys(snapshot.pipelines || {}).length} loaded`,
    },
    {
      label: "Live policy",
      value: runtime.allow_fallback_in_live ? "relaxed" : "strict",
      detail: runtime.require_step_selection_for_live ? "explicit steps" : "free selection",
    },
    {
      label: "Live allow-list",
      value: Array.isArray(runtime.allowed_live_steps) && runtime.allowed_live_steps.length
        ? `${runtime.allowed_live_steps.length} steps`
        : "n/a",
      detail: Array.isArray(runtime.allowed_live_steps) && runtime.allowed_live_steps.length
        ? compactPath(runtime.allowed_live_steps.join(" · "), 4)
        : "No allow-list configured",
    },
  ];
  const pathCards = [
    ["Repo root", bootstrap.repoPath],
    ["Config", bootstrap.configPath],
    ["Artifacts", bootstrap.artifactsRoot],
  ];
  elements.workspaceMetrics.innerHTML = statCards
    .map(
      (metric) => `
        <div class="metric-card">
          <dt>${escapeHtml(metric.label)}</dt>
          <dd>${escapeHtml(metric.value)}</dd>
          <small>${escapeHtml(metric.detail)}</small>
        </div>
      `,
    )
    .concat(
      pathCards.map(
        ([label, value]) => `
          <div class="metric-card full" title="${escapeHtml(value || "n/a")}">
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(compactPath(value || "", 4))}</dd>
            <small>${escapeHtml(value || "n/a")}</small>
          </div>
        `,
      ),
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
      renderLaunchBrief();
      renderPipelineRadar();
      renderPipelineDag();
      renderHeroStatus();
      renderReadinessGate();
    });
  });
}

function renderRequestPresets() {
  const pipelineName = elements.pipeline.value || state.bootstrap?.snapshot?.defaultPipeline || "selected pipeline";
  const presets = [
    {
      label: "Doc update",
      text: `Update the README and config notes for ${pipelineName}, then summarize any risks before implementation.`,
    },
    {
      label: "Runtime bug",
      text: `Investigate a runtime failure in ${pipelineName}, fix the root cause, and capture validation steps for review.`,
    },
    {
      label: "Preflight audit",
      text: `Audit ${pipelineName} for blockers, assignment mismatches, and live-mode risks before changing code.`,
    },
    {
      label: "GitHub follow-up",
      text: `Run the selected ${pipelineName} steps and prepare the issue / PR follow-up with a concise collaboration summary.`,
    },
  ];
  elements.requestPresets.innerHTML = presets
    .map(
      (preset) => `
        <button
          class="preset-chip"
          type="button"
          data-request-preset="${escapeHtml(preset.text)}"
        >
          ${escapeHtml(preset.label)}
        </button>
      `,
    )
    .join("");
  elements.requestPresets.querySelectorAll("button[data-request-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextValue = button.getAttribute("data-request-preset") || "";
      if (elements.request.value.trim() && elements.request.value.trim() !== nextValue) {
        const confirmed = window.confirm("Replace the current request text with this starter?");
        if (!confirmed) {
          return;
        }
      }
      elements.request.value = nextValue;
      renderLaunchBrief();
      renderReadinessGate();
      elements.request.focus();
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
          <div class="recent-run-meta">
            <span>${escapeHtml(formatRelativeTime(run.updatedAt))}</span>
            <span>${escapeHtml(`${run.stepCount || 0} planned steps`)}</span>
            <span>${escapeHtml(counts || "no status data")}</span>
          </div>
          <small>${escapeHtml(formatAbsoluteTime(run.updatedAt))}</small>
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
  renderRequestPresets();
  renderWorkspaceMetrics(bootstrap);
  renderLaunchBrief();
  renderHeroStatus();
  renderPipelineRadar();
  renderPipelineDag();
  renderReadinessGate();
  renderRecentRuns(bootstrap);
  renderCompareSelectors(bootstrap);
  renderGitHubBridge();
  renderHermesPanel();
  if (!state.currentHistory) {
    clearArtifactBrowser();
  }
  updateActionButtons();
  updateCopyButtons();
}

function renderTask(task) {
  state.currentTaskStatus = task.status || "idle";
  updateActionButtons();
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
  renderGitHubBridge();
  renderHermesPanel();
}

async function fetchJson(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const response = await fetch(url, {
    headers,
    ...options,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json();
}

function housekeepingHeaders() {
  const token = state.bootstrap?.housekeeping?.confirmationToken || "";
  return token ? { "X-OpenClaw-Housekeeping-Token": token } : {};
}

async function loadBootstrap() {
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
    pipeline: elements.pipeline.value || "",
  });
  const payload = await fetchJson(`/api/bootstrap?${query.toString()}`);
  renderBootstrap(payload);
  await loadRunCompare().catch((error) => {
    elements.runCompare.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  });
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

async function loadRunCompare() {
  if ((state.bootstrap?.recentRuns || []).length < 2) {
    state.comparePayload = null;
    renderRunCompare(null);
    return;
  }
  const leftRun = elements.compareLeftRun.value || "";
  const rightRun = elements.compareRightRun.value || "";
  if (!leftRun || !rightRun) {
    state.comparePayload = null;
    renderRunCompare(null);
    return;
  }
  if (leftRun === rightRun) {
    state.comparePayload = null;
    elements.runCompare.innerHTML = `<div class="empty-state">Choose two different runs to compare.</div>`;
    return;
  }

  elements.runCompare.innerHTML = `<div class="empty-state">Comparing ${escapeHtml(leftRun)} and ${escapeHtml(rightRun)}...</div>`;
  const query = new URLSearchParams({
    repoPath: elements.repoPath.value || "",
    configPath: elements.configPath.value || "",
  });
  const payload = await fetchJson(`/api/history/compare?${query.toString()}`, {
    method: "POST",
    body: JSON.stringify({ runIds: [leftRun, rightRun] }),
  });
  state.comparePayload = payload;
  renderRunCompare(payload);
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
    headers: housekeepingHeaders(),
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
    headers: housekeepingHeaders(),
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

  elements.compareLeftRun.addEventListener("change", () => {
    loadRunCompare().catch((error) => {
      elements.runCompare.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  });

  elements.compareRightRun.addEventListener("change", () => {
    loadRunCompare().catch((error) => {
      elements.runCompare.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
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
    renderLaunchBrief();
    renderReadinessGate();
    updateActionButtons();
  });

  elements.selectAll.addEventListener("click", () => {
    elements.stepGrid.querySelectorAll("input[type=checkbox]").forEach((input) => {
      input.checked = true;
    });
    renderLaunchBrief();
    renderPipelineRadar();
    renderPipelineDag();
    renderHeroStatus();
    renderReadinessGate();
  });

  elements.selectNone.addEventListener("click", () => {
    elements.stepGrid.querySelectorAll("input[type=checkbox]").forEach((input) => {
      input.checked = false;
    });
    renderLaunchBrief();
    renderPipelineRadar();
    renderPipelineDag();
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
  state.currentTaskStatus = "idle";
  elements.cancelTask.disabled = true;
  elements.cleanupCurrentRun.disabled = true;
  updateActionButtons();
  updateCopyButtons();
}

boot().catch((error) => {
  elements.outputPane.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});
