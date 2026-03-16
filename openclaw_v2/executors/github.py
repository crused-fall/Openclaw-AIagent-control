from __future__ import annotations

import asyncio
import re

from ..config import ProfileConfig
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
            or f"openclaw/{work_item.id}"
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

        ref = (
            str(work_item.metadata.get("source_branch", "")).strip()
            or str(work_item.metadata.get("primary_branch_name", "")).strip()
            or self.app_config.github.base_branch
        )
        if not ref and not dry_run:
            raise ValueError("No branch reference available for workflow_dispatch action.")
        if not ref:
            ref = "main"

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
        raise ValueError(f"Unsupported GitHub action: {profile.action}")

    @staticmethod
    def _extract_resource_refs(action: str, output: str) -> dict[str, str]:
        match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/(issues|pull)/(\d+)", output)
        if not match:
            return {}

        url = match.group(0)
        resource_type = match.group(1)
        resource_number = match.group(2)
        if resource_type == "issues":
            return {"issue_url": url, "issue_number": resource_number}
        return {"pr_url": url, "pr_number": resource_number}

    @staticmethod
    def _dry_run_refs(action: str) -> dict[str, str]:
        if action == "issue":
            return {"issue_number": "ISSUE_NUMBER", "issue_url": "https://github.com/owner/repo/issues/ISSUE_NUMBER"}
        if action == "pr":
            return {"pr_number": "PR_NUMBER", "pr_url": "https://github.com/owner/repo/pull/PR_NUMBER"}
        return {}

    async def execute(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        context: ExecutionContext,
        rendered_prompt: str,
    ) -> AgentResult:
        repo = self.app_config.github.repo
        if not repo and context.dry_run:
            repo = "owner/repo"
        elif not repo:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary="github.repo is empty. Configure it before enabling live GitHub execution.",
            )

        try:
            command = self._build_command(work_item, profile, rendered_prompt, repo, context.dry_run)
        except ValueError as error:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary=str(error),
            )

        if context.dry_run:
            artifacts = {
                "repo": repo,
                "action": profile.action,
                "source_branch": str(work_item.metadata.get("source_branch", "")).strip()
                or str(work_item.metadata.get("primary_branch_name", "")).strip(),
            }
            artifacts.update(self._dry_run_refs(profile.action))
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

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            artifacts = {
                "repo": repo,
                "action": profile.action,
                "source_branch": str(work_item.metadata.get("source_branch", "")).strip()
                or str(work_item.metadata.get("primary_branch_name", "")).strip(),
            }
            artifacts.update(self._extract_resource_refs(profile.action, output))
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.SUCCEEDED,
                summary=f"GitHub workflow task {work_item.title} finished successfully.",
                output=output,
                stdout=output,
                stderr=error_output,
                exit_code=process.returncode,
                command=command,
                artifacts=artifacts,
            )

        return AgentResult(
            work_item_id=work_item.id,
            profile=work_item.profile,
            agent=work_item.agent,
            mode=work_item.mode,
            status=TaskStatus.FAILED,
            summary=f"GitHub workflow task {work_item.title} failed with exit code {process.returncode}.",
            output=error_output or output,
            stdout=output,
            stderr=error_output,
            exit_code=process.returncode,
            command=command,
            artifacts={
                "repo": repo,
                "action": profile.action,
                "source_branch": str(work_item.metadata.get("source_branch", "")).strip()
                or str(work_item.metadata.get("primary_branch_name", "")).strip(),
            },
        )
