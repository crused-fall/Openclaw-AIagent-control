from __future__ import annotations

import asyncio
import re

from ..config import ProfileConfig
from ..github_support import resolve_github_repo_from_origin
from ..models import AgentResult, ExecutionContext, TaskStatus, WorkItem
from .base import Executor


class GitHubWorkflowExecutor(Executor):
    """Run GitHub-backed workflow steps through `gh`.

    This executor is intentionally conservative. In dry-run mode it only returns
    the planned command. When enabled, it relies on a configured GitHub repo and
    an installed `gh` CLI.
    """

    @staticmethod
    def _build_title(work_item: WorkItem, profile: ProfileConfig) -> str:
        return (profile.title_template or work_item.title).format(
            title=work_item.title,
            work_item_id=work_item.id,
        )

    @staticmethod
    def _body(work_item: WorkItem, profile: ProfileConfig, rendered_prompt: str) -> str:
        if profile.body_template:
            return profile.body_template.format(prompt=rendered_prompt, title=work_item.title)
        return rendered_prompt

    def _build_issue_command(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        rendered_prompt: str,
        repo: str,
    ) -> list[str]:
        title = self._build_title(work_item, profile)
        labels = profile.labels or self.app_config.github.default_labels
        command = [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            self._body(work_item, profile, rendered_prompt),
        ]
        for label in labels:
            command.extend(["--label", label])
        return command

    def _build_issue_comment_command(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        rendered_prompt: str,
        repo: str,
        dry_run: bool,
    ) -> list[str]:
        issue_ref = str(work_item.metadata.get("primary_issue_ref", "")).strip()
        if not issue_ref:
            if not dry_run:
                raise ValueError("No issue reference available for issue_comment action.")
            issue_ref = "ISSUE_NUMBER"

        return [
            "gh",
            "issue",
            "comment",
            issue_ref,
            "--repo",
            repo,
            "--body",
            self._body(work_item, profile, rendered_prompt),
        ]

    def _build_pr_command(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        rendered_prompt: str,
        repo: str,
    ) -> list[str]:
        title = self._build_title(work_item, profile)
        branch_name = (
            str(work_item.metadata.get("source_branch", "")).strip()
            or str(work_item.metadata.get("primary_branch_name", "")).strip()
            or f"openclaw-{work_item.id}"
        )
        return [
            "gh",
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            self.app_config.github.base_branch,
            "--head",
            branch_name,
            "--title",
            title,
            "--body",
            self._body(work_item, profile, rendered_prompt),
        ]

    def _build_pr_comment_command(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        rendered_prompt: str,
        repo: str,
        dry_run: bool,
    ) -> list[str]:
        pr_ref = str(work_item.metadata.get("primary_pr_ref", "")).strip()
        if not pr_ref:
            if not dry_run:
                raise ValueError("No PR reference available for pr_comment action.")
            pr_ref = "PR_NUMBER"

        return [
            "gh",
            "pr",
            "comment",
            pr_ref,
            "--repo",
            repo,
            "--body",
            self._body(work_item, profile, rendered_prompt),
        ]

    def _workflow_dispatch_ref(self, work_item: WorkItem, dry_run: bool) -> str:
        ref = (
            str(work_item.metadata.get("source_branch", "")).strip()
            or str(work_item.metadata.get("primary_branch_name", "")).strip()
            or self.app_config.github.base_branch
        )
        if not ref and dry_run:
            return "main"
        return ref

    def _build_workflow_dispatch_command(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        repo: str,
        dry_run: bool,
    ) -> list[str]:
        workflow_name = profile.workflow_name.strip()
        if not workflow_name:
            raise ValueError("workflow_name is required for workflow_dispatch action.")

        ref = self._workflow_dispatch_ref(work_item, dry_run)
        if not ref and not dry_run:
            raise ValueError("No branch reference available for workflow_dispatch action.")

        return [
            "gh",
            "workflow",
            "run",
            workflow_name,
            "--repo",
            repo,
            "--ref",
            ref,
        ]

    def _build_workflow_view_command(
        self,
        work_item: WorkItem,
        repo: str,
        dry_run: bool,
    ) -> list[str]:
        workflow_run_ref = str(work_item.metadata.get("primary_workflow_run_ref", "")).strip()
        normalized = self._normalize_workflow_run_ref(workflow_run_ref)
        run_id = normalized.get("workflow_run_id", "")
        if not run_id:
            if not dry_run:
                raise ValueError("No workflow run reference available for workflow_view action.")
            run_id = "WORKFLOW_RUN_ID"

        return [
            "gh",
            "run",
            "view",
            run_id,
            "--repo",
            repo,
            "--json",
            "attempt,conclusion,databaseId,displayTitle,headBranch,jobs,number,status,url,workflowName",
        ]

    def _build_command(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        rendered_prompt: str,
        repo: str,
        dry_run: bool,
    ) -> list[str]:
        if profile.action == "issue":
            return self._build_issue_command(work_item, profile, rendered_prompt, repo)
        if profile.action == "issue_comment":
            return self._build_issue_comment_command(work_item, profile, rendered_prompt, repo, dry_run)
        if profile.action == "pr":
            return self._build_pr_command(work_item, profile, rendered_prompt, repo)
        if profile.action == "pr_comment":
            return self._build_pr_comment_command(work_item, profile, rendered_prompt, repo, dry_run)
        if profile.action == "workflow_dispatch":
            return self._build_workflow_dispatch_command(work_item, profile, repo, dry_run)
        if profile.action == "workflow_view":
            return self._build_workflow_view_command(work_item, repo, dry_run)
        raise ValueError(f"Unsupported GitHub action: {profile.action}")

    @staticmethod
    def _is_blocking_configuration_error(message: str) -> bool:
        normalized = message.lower()
        return any(
            phrase in normalized
            for phrase in [
                "no issue reference available",
                "no pr reference available",
                "no branch reference available",
                "workflow_name is required",
                "no workflow run reference available",
                "github.repo is empty",
            ]
        )

    @staticmethod
    def _recovery_hint(kind: str) -> str:
        hints = {
            "auth_required": "Run `gh auth status` or `gh auth login`, then retry the GitHub step.",
            "insufficient_token_permissions": (
                "Refresh GitHub CLI auth with workflow-capable permissions, for example "
                "`gh auth refresh -h github.com -s repo,workflow`, or re-login with a token that can dispatch Actions workflows."
            ),
            "repository_unavailable": "Confirm `github.repo` and the repository remote, then retry the GitHub step.",
            "workflow_missing": "Add the workflow file under `.github/workflows/` or update `workflow_name`, then retry.",
            "reference_missing": "Ensure upstream steps produced the required issue, PR, or branch reference before retrying.",
            "network_or_transport": "Retry after GitHub or network connectivity recovers. Inspect `github_error` for the original CLI failure.",
            "configuration_missing_repo": "Set `github.repo` in config before enabling live GitHub execution.",
            "configuration_missing_workflow_name": "Set `workflow_name` for the workflow_dispatch profile before retrying.",
            "unknown": "Inspect `github_error` and rerun the printed `gh` command manually if needed.",
        }
        return hints.get(kind, hints["unknown"])

    @classmethod
    def _artifacts_for_failure(
        cls,
        work_item: WorkItem,
        profile: ProfileConfig,
        repo: str,
        kind: str,
        retryable: bool,
        error_output: str = "",
        blocked_reason: str = "",
    ) -> dict[str, object]:
        artifacts = cls._base_artifacts(work_item, profile, repo)
        artifacts["github_failure_kind"] = kind
        artifacts["github_retryable"] = retryable
        artifacts["github_recovery_hint"] = cls._recovery_hint(kind)
        if error_output:
            artifacts["github_error"] = error_output
        if blocked_reason:
            artifacts["blocked_reason"] = blocked_reason
        return artifacts

    @staticmethod
    def _classify_execution_failure(output: str, error_output: str) -> dict[str, object]:
        combined = "\n".join(part for part in [output, error_output] if part).lower()

        categories: list[tuple[list[str], TaskStatus, str, bool, str]] = [
            (
                [
                    "not logged into any github hosts",
                    "authentication required",
                    "gh auth login",
                    "must authenticate",
                    "login required",
                ],
                TaskStatus.BLOCKED,
                "auth_required",
                True,
                "GitHub authentication is required.",
            ),
            (
                [
                    "resource not accessible by personal access token",
                    "insufficient permissions to create workflow dispatch event",
                    "must have admin or write permission to repository",
                ],
                TaskStatus.BLOCKED,
                "insufficient_token_permissions",
                False,
                "GitHub token does not have enough permission to trigger this workflow.",
            ),
            (
                [
                    "could not resolve to a repository",
                    "repository not found",
                    "not a git repository",
                    "remote repository is empty",
                ],
                TaskStatus.BLOCKED,
                "repository_unavailable",
                False,
                "GitHub repository is unavailable.",
            ),
            (
                [
                    "workflow not found",
                    "could not find any workflows",
                    "no workflow found",
                    "workflow file not found",
                ],
                TaskStatus.BLOCKED,
                "workflow_missing",
                False,
                "GitHub workflow is missing.",
            ),
            (
                [
                    "could not resolve to a pull request",
                    "could not resolve to an issue",
                    "pull request not found",
                    "issue not found",
                    "reference does not exist",
                ],
                TaskStatus.BLOCKED,
                "reference_missing",
                False,
                "GitHub reference is missing or invalid.",
            ),
            (
                [
                    "rate limit",
                    "timed out",
                    "timeout",
                    "connection refused",
                    "network is unreachable",
                    "temporary failure",
                    "tls handshake",
                    "service unavailable",
                ],
                TaskStatus.FAILED,
                "network_or_transport",
                True,
                "GitHub CLI encountered a network or transport error.",
            ),
        ]

        for phrases, status, kind, retryable, reason in categories:
            if any(phrase in combined for phrase in phrases):
                return {
                    "status": status,
                    "kind": kind,
                    "retryable": retryable,
                    "reason": reason,
                }

        return {
            "status": TaskStatus.FAILED,
            "kind": "unknown",
            "retryable": False,
            "reason": "GitHub workflow task failed.",
        }

    @staticmethod
    def _normalize_issue_ref(ref: str) -> dict[str, str]:
        ref = ref.strip()
        if not ref:
            return {}
        match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)", ref)
        if match:
            return {"issue_url": match.group(0), "issue_number": match.group(1)}
        if ref.isdigit():
            return {"issue_number": ref}
        return {}

    @staticmethod
    def _normalize_pr_ref(ref: str) -> dict[str, str]:
        ref = ref.strip()
        if not ref:
            return {}
        match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)", ref)
        if match:
            return {"pr_url": match.group(0), "pr_number": match.group(1)}
        if ref.isdigit():
            return {"pr_number": ref}
        return {}

    @staticmethod
    def _normalize_workflow_run_ref(ref: str) -> dict[str, str]:
        ref = ref.strip()
        if not ref:
            return {}
        match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/actions/runs/(\d+)", ref)
        if match:
            return {"workflow_run_url": match.group(0), "workflow_run_id": match.group(1)}
        if ref.isdigit():
            return {"workflow_run_id": ref}
        return {}

    @classmethod
    def _base_artifacts(
        cls,
        work_item: WorkItem,
        profile: ProfileConfig,
        repo: str,
        repo_source: str = "",
    ) -> dict[str, str]:
        artifacts = {
            "repo": repo,
            "action": profile.action,
            "repo_source": repo_source,
            "source_branch": str(work_item.metadata.get("source_branch", "")).strip()
            or str(work_item.metadata.get("primary_branch_name", "")).strip(),
        }
        artifacts.update(cls._normalize_issue_ref(str(work_item.metadata.get("primary_issue_ref", ""))))
        artifacts.update(cls._normalize_pr_ref(str(work_item.metadata.get("primary_pr_ref", ""))))
        artifacts.update(
            cls._normalize_workflow_run_ref(str(work_item.metadata.get("primary_workflow_run_ref", "")))
        )
        if profile.action == "workflow_dispatch":
            artifacts["workflow_name"] = profile.workflow_name.strip()
            artifacts["workflow_ref"] = artifacts["source_branch"] or ""
        return {key: value for key, value in artifacts.items() if value}

    async def _resolve_repo(self, context: ExecutionContext) -> tuple[str, str]:
        configured_repo = self.app_config.github.repo.strip()
        if configured_repo:
            return configured_repo, "config"

        if self.app_config.github.use_origin_remote_fallback:
            resolved_repo, _, _ = await resolve_github_repo_from_origin(context.repo_path)
            if resolved_repo:
                return resolved_repo, "git_origin"

        if context.dry_run:
            return "owner/repo", "placeholder"
        return "", ""

    @staticmethod
    def _extract_resource_refs(action: str, output: str) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        issue_match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)", output)
        pr_match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)", output)
        workflow_match = re.search(
            r"https://github\.com/[^/\s]+/[^/\s]+/actions/runs/(\d+)",
            output,
        )

        if issue_match:
            artifacts["issue_url"] = issue_match.group(0)
            artifacts["issue_number"] = issue_match.group(1)
        if pr_match:
            artifacts["pr_url"] = pr_match.group(0)
            artifacts["pr_number"] = pr_match.group(1)
        if workflow_match:
            artifacts["workflow_run_url"] = workflow_match.group(0)
            artifacts["workflow_run_id"] = workflow_match.group(1)
        return artifacts

    def _dry_run_refs(self, action: str, work_item: WorkItem, profile: ProfileConfig, repo: str) -> dict[str, str]:
        existing = self._base_artifacts(work_item, profile, repo)
        if action == "issue":
            return {
                **existing,
                "issue_number": "ISSUE_NUMBER",
                "issue_url": f"https://github.com/{repo}/issues/ISSUE_NUMBER",
            }
        if action == "pr":
            return {
                **existing,
                "pr_number": "PR_NUMBER",
                "pr_url": f"https://github.com/{repo}/pull/PR_NUMBER",
            }
        if action == "workflow_dispatch":
            return {
                **existing,
                "workflow_ref": existing.get("workflow_ref") or self._workflow_dispatch_ref(work_item, True),
                "workflow_run_id": "WORKFLOW_RUN_ID",
                "workflow_run_url": f"https://github.com/{repo}/actions/runs/WORKFLOW_RUN_ID",
            }
        if action == "workflow_view":
            return {
                **existing,
                "workflow_run_id": existing.get("workflow_run_id", "WORKFLOW_RUN_ID"),
                "workflow_run_url": existing.get(
                    "workflow_run_url",
                    f"https://github.com/{repo}/actions/runs/WORKFLOW_RUN_ID",
                ),
                "workflow_status": "queued",
                "workflow_conclusion": "",
            }
        return existing

    @staticmethod
    def _parse_workflow_view_output(output: str) -> tuple[TaskStatus, str, dict[str, object]]:
        import json

        data = json.loads(output or "{}")
        if not isinstance(data, dict):
            raise ValueError("Workflow view response is not a JSON object.")

        workflow_status = str(data.get("status", "")).strip()
        workflow_conclusion = str(data.get("conclusion") or "").strip()
        workflow_name = str(data.get("workflowName") or data.get("name") or "").strip()
        run_id = str(data.get("databaseId") or "").strip()
        run_url = str(data.get("url") or "").strip()
        head_branch = str(data.get("headBranch") or "").strip()
        run_attempt = data.get("attempt")
        run_number = data.get("number")
        jobs = data.get("jobs")
        failed_jobs: list[str] = []
        job_count = 0
        if isinstance(jobs, list):
            job_count = len(jobs)
            for index, job in enumerate(jobs, start=1):
                if not isinstance(job, dict):
                    continue
                job_name = str(
                    job.get("name") or job.get("displayTitle") or job.get("jobName") or f"job-{index}"
                ).strip()
                job_status = str(job.get("status") or "").strip()
                job_conclusion = str(job.get("conclusion") or "").strip()
                if job_status == "completed" and job_conclusion not in {"", "success", "neutral", "skipped"}:
                    failed_jobs.append(job_name)

        artifacts: dict[str, object] = {
            "workflow_run_id": run_id,
            "workflow_run_url": run_url,
            "workflow_name": workflow_name,
            "workflow_status": workflow_status,
            "workflow_conclusion": workflow_conclusion,
            "workflow_head_branch": head_branch,
            "workflow_job_count": job_count,
            "workflow_failed_job_count": len(failed_jobs),
        }
        if failed_jobs:
            artifacts["workflow_failed_jobs"] = ", ".join(failed_jobs)
        if run_attempt is not None:
            artifacts["workflow_run_attempt"] = run_attempt
        if run_number is not None:
            artifacts["workflow_run_number"] = run_number

        if workflow_status and workflow_status != "completed":
            blocked_reason = (
                f"GitHub workflow run {run_id or workflow_name or 'unknown'} is still {workflow_status}."
            )
            artifacts["blocked_reason"] = blocked_reason
            return TaskStatus.BLOCKED, blocked_reason, artifacts

        if workflow_conclusion in {"success", "neutral", "skipped"}:
            summary = (
                f"GitHub workflow run {run_id or workflow_name or 'unknown'} completed with conclusion {workflow_conclusion}."
            )
            return TaskStatus.SUCCEEDED, summary, artifacts

        if workflow_conclusion == "action_required":
            blocked_reason = (
                f"GitHub workflow run {run_id or workflow_name or 'unknown'} requires manual action."
            )
            artifacts["blocked_reason"] = blocked_reason
            return TaskStatus.BLOCKED, blocked_reason, artifacts

        summary = (
            f"GitHub workflow run {run_id or workflow_name or 'unknown'} completed with conclusion {workflow_conclusion or 'unknown'}."
        )
        if failed_jobs:
            summary = f"{summary} Failed jobs: {', '.join(failed_jobs)}."
        return TaskStatus.FAILED, summary, artifacts

    @staticmethod
    async def _run_command(command: list[str], repo_path: str) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()
        return process.returncode, output, error_output

    async def execute(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        context: ExecutionContext,
        rendered_prompt: str,
    ) -> AgentResult:
        repo, repo_source = await self._resolve_repo(context)
        if not repo:
            blocked_reason = "github.repo is empty. Configure it before enabling live GitHub execution."
            if self.app_config.github.use_origin_remote_fallback:
                blocked_reason = (
                    "GitHub repo is empty and could not be resolved from `git remote origin`. "
                    "Configure github.repo or fix the origin remote before enabling live GitHub execution."
                )
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.BLOCKED,
                summary=blocked_reason,
                artifacts=self._artifacts_for_failure(
                    work_item,
                    profile,
                    repo,
                    kind="configuration_missing_repo",
                    retryable=False,
                    blocked_reason=blocked_reason,
                ),
            )

        try:
            command = self._build_command(work_item, profile, rendered_prompt, repo, context.dry_run)
        except ValueError as error:
            message = str(error)
            status = TaskStatus.BLOCKED if self._is_blocking_configuration_error(message) else TaskStatus.FAILED
            if "workflow_name is required" in message.lower():
                kind = "configuration_missing_workflow_name"
            elif "reference" in message.lower():
                kind = "reference_missing"
            else:
                kind = "unknown"
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=status,
                summary=(
                    f"GitHub workflow task {work_item.title} blocked: {message}"
                    if status == TaskStatus.BLOCKED
                    else f"GitHub workflow task {work_item.title} failed: {message}"
                ),
                artifacts={
                    **self._artifacts_for_failure(
                        work_item,
                        profile,
                        repo,
                        kind=kind,
                        retryable=False,
                        blocked_reason=message if status == TaskStatus.BLOCKED else "",
                        error_output=message if status == TaskStatus.FAILED else "",
                    ),
                    **({"repo_source": repo_source} if repo_source else {}),
                },
            )

        if context.dry_run:
            artifacts = self._dry_run_refs(profile.action, work_item, profile, repo)
            if repo_source:
                artifacts["repo_source"] = repo_source
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.SUCCEEDED,
                summary=f"Dry-run only. Planned GitHub workflow command for {work_item.title}.",
                output=rendered_prompt,
                stdout=rendered_prompt,
                exit_code=0,
                command=command,
                artifacts=artifacts,
            )

        is_workflow_view = profile.action == "workflow_view"
        if is_workflow_view:
            max_attempts = max(1, int(self.app_config.runtime.github_workflow_view_poll_attempts))
            retry_backoff_seconds = max(
                0.0,
                float(self.app_config.runtime.github_workflow_view_poll_interval_seconds),
            )
        else:
            max_attempts = max(1, int(self.app_config.runtime.github_retry_attempts))
            retry_backoff_seconds = max(0.0, float(self.app_config.runtime.github_retry_backoff_seconds))
        last_failure: dict[str, object] | None = None
        last_output = ""
        last_error_output = ""
        last_returncode = 0

        for attempt in range(1, max_attempts + 1):
            returncode, output, error_output = await self._run_command(command, context.repo_path)
            combined_output = "\n".join(part for part in [output, error_output] if part)
            last_output = output
            last_error_output = error_output
            last_returncode = returncode

            if returncode == 0:
                artifacts = self._base_artifacts(work_item, profile, repo, repo_source=repo_source)
                if profile.action == "workflow_dispatch" and not artifacts.get("workflow_ref"):
                    artifacts["workflow_ref"] = self._workflow_dispatch_ref(work_item, False)
                if is_workflow_view:
                    try:
                        view_status, view_summary, workflow_artifacts = self._parse_workflow_view_output(output)
                    except (ValueError, Exception) as error:
                        return AgentResult(
                            work_item_id=work_item.id,
                            profile=work_item.profile,
                            agent=work_item.agent,
                            mode=work_item.mode,
                            status=TaskStatus.FAILED,
                            summary=f"GitHub workflow task {work_item.title} returned invalid workflow JSON: {error}",
                            output=output,
                            stdout=output,
                            stderr=error_output,
                            exit_code=returncode,
                            command=command,
                            artifacts={
                                **artifacts,
                                "github_failure_kind": "invalid_workflow_view_output",
                                "github_retryable": False,
                                "github_recovery_hint": "Inspect the raw workflow view JSON and `gh run view` output before retrying.",
                            },
                        )
                    artifacts.update(workflow_artifacts)
                    pending_workflow = (
                        view_status == TaskStatus.BLOCKED
                        and str(workflow_artifacts.get("workflow_status", "")).strip() not in {"", "completed"}
                    )
                    if pending_workflow and attempt < max_attempts:
                        await asyncio.sleep(retry_backoff_seconds)
                        continue
                    artifacts["github_attempt_count"] = attempt
                    artifacts["workflow_poll_attempt_count"] = attempt
                    if attempt > 1:
                        artifacts["github_retried"] = True
                        if view_status == TaskStatus.SUCCEEDED:
                            view_summary = f"{view_summary} Resolved after {attempt} status polls."
                        elif pending_workflow:
                            view_summary = f"{view_summary} Poll limit reached after {attempt} attempts."
                    return AgentResult(
                        work_item_id=work_item.id,
                        profile=work_item.profile,
                        agent=work_item.agent,
                        mode=work_item.mode,
                        status=view_status,
                        summary=view_summary,
                        output=output,
                        stdout=output,
                        stderr=error_output,
                        exit_code=returncode,
                        command=command,
                        artifacts=artifacts,
                    )

                artifacts.update(self._extract_resource_refs(profile.action, combined_output))
                artifacts["github_attempt_count"] = attempt
                if attempt > 1:
                    artifacts["github_retried"] = True
                return AgentResult(
                    work_item_id=work_item.id,
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary=(
                        f"GitHub workflow task {work_item.title} finished successfully after {attempt} attempts."
                        if attempt > 1
                        else f"GitHub workflow task {work_item.title} finished successfully."
                    ),
                    output=output,
                    stdout=output,
                    stderr=error_output,
                    exit_code=returncode,
                    command=command,
                    artifacts=artifacts,
                )

            failure = self._classify_execution_failure(output, error_output)
            last_failure = failure
            should_retry = (
                failure["status"] == TaskStatus.FAILED
                and bool(failure["retryable"])
                and attempt < max_attempts
            )
            if should_retry:
                await asyncio.sleep(retry_backoff_seconds)
                continue

            break

        assert last_failure is not None
        combined_output = "\n".join(part for part in [last_output, last_error_output] if part)
        attempts_taken = attempt
        artifacts = self._artifacts_for_failure(
            work_item,
            profile,
            repo,
            kind=str(last_failure["kind"]),
            retryable=bool(last_failure["retryable"]),
            error_output=last_error_output,
            blocked_reason=str(last_failure["reason"]) if last_failure["status"] == TaskStatus.BLOCKED else "",
        )
        artifacts.update(self._extract_resource_refs(profile.action, combined_output))
        artifacts["github_attempt_count"] = attempts_taken
        if repo_source:
            artifacts["repo_source"] = repo_source
        if attempts_taken > 1:
            artifacts["github_retried"] = True
        if is_workflow_view:
            artifacts["workflow_poll_attempt_count"] = attempts_taken

        return AgentResult(
            work_item_id=work_item.id,
            profile=work_item.profile,
            agent=work_item.agent,
            mode=work_item.mode,
            status=last_failure["status"],
            summary=(
                f"GitHub workflow task {work_item.title} blocked after {attempts_taken} attempts: {last_failure['reason']}"
                if last_failure["status"] == TaskStatus.BLOCKED and attempts_taken > 1
                else f"GitHub workflow task {work_item.title} blocked: {last_failure['reason']}"
                if last_failure["status"] == TaskStatus.BLOCKED
                else f"GitHub workflow task {work_item.title} failed after {attempts_taken} attempts with exit code {last_returncode}: {last_failure['reason']}"
                if attempts_taken > 1
                else f"GitHub workflow task {work_item.title} failed with exit code {last_returncode}: {last_failure['reason']}"
            ),
            output=last_error_output or last_output,
            stdout=last_output,
            stderr=last_error_output,
            exit_code=last_returncode,
            command=command,
            artifacts=artifacts,
        )
