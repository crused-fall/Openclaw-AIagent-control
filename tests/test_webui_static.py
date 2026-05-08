from pathlib import Path
import unittest


class WebUiStaticTests(unittest.TestCase):
    def test_status_chip_uses_sanitized_tone_class(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function statusChipTone(value)", source)
        self.assertIn('return `<span class=\"status-chip ${tone}\">${escapeHtml(normalized)}</span>`;', source)
        self.assertNotIn('class=\"status-chip ${normalized}\"', source)

    def test_launch_pad_exposes_workflow_run_ref_input(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="workflow-run-ref"', source)
        self.assertIn('name="workflowRunRef"', source)
        self.assertIn("Resume an existing GitHub Actions workflow run", source)

    def test_channel_health_status_uses_helper(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function channelHealthStatus(channels)", source)
        self.assertIn("!Array.isArray(channels) || !channels.length", source)
        self.assertIn('${makeStatusChip(channelHealthStatus(channels))}', source)
        self.assertNotIn(
            '${makeStatusChip(channels.every((item) => item.probeOk) ? "passed" : "warning")}',
            source,
        )

    def test_task_payload_includes_workflow_run_ref_and_ready_state_checks_it(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function currentWorkflowRunRef()", source)
        self.assertIn("function pipelineRequiresWorkflowRunRef()", source)
        self.assertIn("function workflowRunRefReady()", source)
        self.assertIn("workflowRunRef: currentWorkflowRunRef(),", source)
        self.assertIn("const workflowRunRefIsReady = workflowRunRefReady();", source)
        self.assertIn("elements.workflowRunRef.addEventListener(\"input\"", source)
        self.assertIn("workflowRunRefReady()", source)

    def test_preflight_snapshot_status_is_shared_between_panels(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function latestPreflightSource()", source)
        self.assertIn("function preflightSnapshotStatus(checks)", source)
        self.assertIn("const preflight = preflightSnapshotStatus(preflightChecks);", source)
        self.assertIn("const preflight = preflightSnapshotStatus(latestPreflightChecks());", source)
        self.assertIn("const preflightSource = latestPreflightSource();", source)
        self.assertIn("<div><dt>Source</dt><dd>${escapeHtml(preflightSource)}</dd></div>", source)
        self.assertIn('${makeStatusChip(preflight.status)}', source)
        self.assertNotIn(
            'No preflight snapshot loaded yet.',
            source.split("function preflightSnapshotStatus(checks)")[0],
        )

    def test_housekeeping_status_is_rendered_from_bootstrap_scope(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function renderHousekeepingStatus(bootstrap)", source)
        self.assertIn("bootstrap?.housekeeping?.confirmationToken", source)
        self.assertIn('["Worktrees", bootstrap.worktreesRoot]', source)
        self.assertIn("renderHousekeepingStatus(bootstrap);", source)

    def test_github_bridge_status_is_aggregated_for_reviewers(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function currentGitHubBridgeState()", source)
        self.assertIn("function currentGitHubWorkflow()", source)
        self.assertIn("function currentGitHubFailure()", source)
        self.assertIn("function formatReviewWorkflowLine(workflow)", source)
        self.assertIn("function formatReviewRecoveryHint(workflow)", source)
        self.assertIn("function formatGitHubRecoveryLine(workflow, failure)", source)
        self.assertIn("const safeRepoUrl = safeExternalUrl(repoUrl);", source)
        self.assertIn("const safeWorkflowUrl = safeExternalUrl(workflow?.url);", source)
        self.assertIn("function githubBridgeStatus(github, overview, runId)", source)
        self.assertIn("const bridgeState = currentGitHubBridgeState();", source)
        self.assertIn("<strong>Bridge state</strong>", source)
        self.assertIn("const failure = github?.latestFailure || null;", source)
        self.assertIn("Workflow ${workflowId || \"n/a\"} succeeded.", source)
        self.assertIn("GitHub bridge: ${bridgeState.label} (${bridgeState.status})", source)
        self.assertIn("formatReviewWorkflowLine(workflow),", source)
        self.assertIn("`- ${formatReviewWorkflowLine(workflow)}`", source)
        self.assertIn("const failedJobs = Array.isArray(workflow.failedJobs)", source)
        self.assertIn('typeof workflow.failedJobs === "string"', source)
        self.assertIn('workflow.failedJobs.split(",")', source)
        self.assertIn("card.githubRecoveryHint", source)
        self.assertIn("card.summary", source)
        self.assertIn("failed jobs:", source)
        self.assertIn("formatReviewRecoveryHint(workflow)", source)
        self.assertIn("formatGitHubRecoveryLine(workflow, failure)", source)
        self.assertIn("GitHub recovery:", source)
        self.assertIn("Review recovery:", source)
        self.assertIn('Open latest review workflow', source)
        self.assertIn("run.insights?.github?.latestFailure", source)
        self.assertIn("comparison.latestFailureChanged", source)
        self.assertIn("comparison.latestFailures", source)
        self.assertNotIn('href="${escapeHtml(repoUrl)}"', source)
        self.assertNotIn('href="${escapeHtml(workflow.url)}"', source)

    def test_recent_runs_surface_latest_github_failure(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function renderRecentRuns(bootstrap)", source)
        self.assertIn("const latestFailure = run.insights?.github?.latestFailure || null;", source)
        self.assertIn("const failureRecovery = formatGitHubRecoveryLine(null, latestFailure);", source)
        self.assertIn("const failureSummary = formatGitHubFailureSummary(latestFailure);", source)
        self.assertIn("formatGitHubFailureLine(run.insights?.github?.latestFailure || null)", source)
        self.assertIn("Recovery: ${failureRecovery}", source)

    def test_openclaw_usage_is_rendered_from_run_insights(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function formatOpenClawUsageSummary(usage)", source)
        self.assertIn("function formatOpenClawUsageDelta(usageDelta)", source)
        self.assertIn("const usageLine = formatOpenClawUsageSummary(run.insights?.usage || null);", source)
        self.assertIn("const usageLine = formatOpenClawUsageSummary(insights?.usage || null);", source)
        self.assertIn("const usageDeltaLine = formatOpenClawUsageDelta(comparison.usageDelta || null);", source)
        self.assertIn("OpenClaw usage", source)
        self.assertIn("OpenClaw usage delta", source)
        self.assertIn(
            "chunks.push(renderRunResults(payload.runResult, payload.history?.insights || payload.insights || null));",
            source,
        )
        self.assertIn(
            "chunks.push(renderRunResults(payload.summary, payload.insights || null));",
            source,
        )
        self.assertIn("comparison.usageDelta", source)

    def test_run_detail_surfaces_latest_github_failure(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function renderRunResults(runResult, insights = null)", source)
        self.assertIn("const workflow = currentGitHubWorkflow();", source)
        self.assertIn("const failure = currentGitHubFailure();", source)
        self.assertIn("const failureLine = formatGitHubFailureLine(failure);", source)
        self.assertIn("const failureSummary = formatGitHubFailureSummary(failure);", source)
        self.assertIn("const recoveryLine = formatGitHubRecoveryLine(workflow, failure);", source)
        self.assertIn("<div><dt>GitHub latest failure</dt><dd>${escapeHtml(failureLine)}</dd></div>", source)
        self.assertIn("Recovery: ${recoveryLine}", source)
        self.assertIn("const latestFailure = historyPayload.insights?.github?.latestFailure || null;", source)
        self.assertIn("const failureLine = formatGitHubFailureLine(latestFailure);", source)
        self.assertIn("const recoveryLine = formatGitHubRecoveryLine(null, latestFailure);", source)

    def test_hermes_panel_uses_overview_roles_and_active_run_roles(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function renderHermesPanel()", source)
        self.assertIn("const overview = state.bootstrap?.integrations?.hermes || {};", source)
        self.assertIn("const roles = hermes.roles || [];", source)
        self.assertIn("<strong>Roles</strong>", source)
        self.assertIn("No Hermes managed agent role", source)
        self.assertIn('roles.length ? `from ${activeRunId()}` : "Load a Hermes-backed run to inspect session traces."', source)


if __name__ == "__main__":
    unittest.main()
