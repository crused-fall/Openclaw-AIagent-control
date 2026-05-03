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
        self.assertIn("const safeRepoUrl = safeExternalUrl(repoUrl);", source)
        self.assertIn("const safeWorkflowUrl = safeExternalUrl(workflow?.url);", source)
        self.assertIn("function githubBridgeStatus(github, overview, runId)", source)
        self.assertIn("const bridgeState = currentGitHubBridgeState();", source)
        self.assertIn("<strong>Bridge state</strong>", source)
        self.assertIn("Workflow ${workflowId || \"n/a\"} succeeded.", source)
        self.assertIn("GitHub bridge: ${bridgeState.label} (${bridgeState.status})", source)
        self.assertIn("Latest review workflow: ${workflow?.url || \"n/a\"}", source)
        self.assertIn('Open latest review workflow', source)
        self.assertNotIn('href="${escapeHtml(repoUrl)}"', source)
        self.assertNotIn('href="${escapeHtml(workflow.url)}"', source)

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
