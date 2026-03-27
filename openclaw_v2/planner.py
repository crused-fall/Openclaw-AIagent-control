from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .config import AppConfig
from .models import AgentType, ExecutionMode, WorkItem


@dataclass
class AssignmentResolution:
    managed_agent_name: str = ""
    profile_name: str = ""
    fallback_chain: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    attempts: list[str] = field(default_factory=list)
    reason: str = ""
    fallback_used: bool = False
    blocked_reason: str = ""


class PipelinePlanner:
    """Build a work plan from a named pipeline template."""

    def __init__(self, config: AppConfig):
        self.config = config

    def build_plan(self, selected_steps: list[str] | None = None) -> list[WorkItem]:
        pipeline_name = self.config.runtime.pipeline
        if pipeline_name not in self.config.pipelines:
            raise ValueError(f"Unknown pipeline: {pipeline_name}")

        pipeline_steps = self.config.pipelines[pipeline_name]
        step_map = {step.id: step for step in pipeline_steps}
        selected_step_set = self._resolve_selected_steps(step_map, selected_steps)

        work_items: list[WorkItem] = []
        for step in pipeline_steps:
            if selected_step_set is not None and step.id not in selected_step_set:
                continue
            assignment_name = step.assignment.strip()
            assignment_source = ""
            profile_name = step.profile.strip()
            managed_agent_name = ""
            assignment_reason = ""
            fallback_used = False
            fallback_chain: list[str] = []
            required_capabilities: list[str] = []
            assignment_candidates: list[str] = []
            assignment_attempts: list[str] = []
            planning_blocked_reason = ""

            if assignment_name:
                if assignment_name not in self.config.assignments:
                    planning_blocked_reason = (
                        f"Assignment `{assignment_name}` referenced by step `{step.id}` is not defined."
                    )
                else:
                    assignment = self.config.assignments[assignment_name]
                    resolution = self._resolve_assignment(assignment_name)
                    assignment_source = assignment.manager
                    managed_agent_name = resolution.managed_agent_name
                    profile_name = resolution.profile_name
                    fallback_chain = list(resolution.fallback_chain)
                    required_capabilities = list(resolution.required_capabilities)
                    assignment_candidates = list(resolution.candidates)
                    assignment_attempts = list(resolution.attempts)
                    assignment_reason = resolution.reason
                    fallback_used = resolution.fallback_used
                    planning_blocked_reason = resolution.blocked_reason

            if not planning_blocked_reason:
                if not profile_name:
                    planning_blocked_reason = f"Pipeline step `{step.id}` has no resolved profile."
                elif profile_name not in self.config.profiles:
                    planning_blocked_reason = (
                        f"Resolved profile `{profile_name}` for step `{step.id}` is not defined."
                    )

            if planning_blocked_reason:
                agent = AgentType.SYSTEM
                mode = ExecutionMode.SYSTEM
            else:
                profile = self.config.profiles[profile_name]
                agent = profile.agent
                mode = profile.mode

            metadata = dict(step.metadata)
            if assignment_name:
                metadata["assignment"] = assignment_name
                metadata["assignment_source"] = assignment_source
                metadata["managed_agent"] = managed_agent_name
                metadata["assignment_reason"] = assignment_reason
                metadata["fallback_used"] = fallback_used
                metadata["fallback_chain"] = fallback_chain
                metadata["required_capabilities"] = required_capabilities
                metadata["assignment_candidates"] = assignment_candidates
                metadata["assignment_attempts"] = assignment_attempts
            if planning_blocked_reason:
                metadata["planning_blocked_reason"] = planning_blocked_reason
            work_items.append(
                WorkItem(
                    id=step.id,
                    title=step.title,
                    profile=profile_name,
                    agent=agent,
                    mode=mode,
                    prompt_template=step.prompt_template,
                    assignment=assignment_name,
                    assignment_source=assignment_source,
                    managed_agent=managed_agent_name,
                    assignment_reason=assignment_reason,
                    fallback_used=fallback_used,
                    fallback_chain=list(fallback_chain),
                    required_capabilities=list(required_capabilities),
                    assignment_candidates=list(assignment_candidates),
                    assignment_attempts=list(assignment_attempts),
                    planning_blocked_reason=planning_blocked_reason,
                    depends_on=list(step.depends_on),
                    metadata=metadata,
                )
            )
        return work_items

    def _resolve_assignment(self, assignment_name: str) -> AssignmentResolution:
        assignment = self.config.assignments[assignment_name]
        candidates = [assignment.agent, *assignment.fallback]
        fallback_chain = [candidate for candidate in candidates[1:] if candidate]
        required_capabilities = sorted({capability for capability in assignment.required_capabilities if capability})
        required_capability_set = set(required_capabilities)
        attempts: list[str] = []

        for index, candidate in enumerate(candidates):
            managed_agent_name = candidate.strip()
            if not managed_agent_name:
                continue
            if managed_agent_name not in self.config.managed_agents:
                attempts.append(
                    f"{managed_agent_name}: managed agent is not defined."
                )
                continue
            managed_agent = self.config.managed_agents[managed_agent_name]
            if not managed_agent.enabled:
                attempts.append(f"{managed_agent_name}: managed agent is disabled.")
                continue
            profile_name = managed_agent.profile.strip()
            if not profile_name:
                attempts.append(f"{managed_agent_name}: no profile is configured.")
                continue
            if profile_name not in self.config.profiles:
                attempts.append(
                    f"{managed_agent_name}: profile `{profile_name}` is not defined."
                )
                continue
            agent_capabilities = set(managed_agent.capabilities)
            missing_capabilities = sorted(required_capability_set.difference(agent_capabilities))
            if missing_capabilities:
                attempts.append(
                    f"{managed_agent_name}: missing capabilities {', '.join(missing_capabilities)}."
                )
                continue

            fallback_used = index > 0
            if required_capabilities:
                reason = (
                    f"Resolved by assignment {assignment_name} to managed agent {managed_agent_name} "
                    f"with capabilities {', '.join(sorted(agent_capabilities))}."
                )
            else:
                reason = (
                    f"Resolved by assignment {assignment_name} to managed agent {managed_agent_name}."
                )
            if fallback_used:
                reason = f"{reason} Fallback was used."
            attempts.append(f"{managed_agent_name}: selected.")
            return AssignmentResolution(
                managed_agent_name=managed_agent_name,
                profile_name=profile_name,
                fallback_chain=fallback_chain,
                required_capabilities=required_capabilities,
                candidates=[candidate for candidate in candidates if candidate],
                attempts=attempts,
                reason=reason,
                fallback_used=fallback_used,
            )

        attempted_text = "; ".join(attempts) if attempts else "No managed agents were configured."
        return AssignmentResolution(
            fallback_chain=fallback_chain,
            required_capabilities=required_capabilities,
            candidates=[candidate for candidate in candidates if candidate],
            attempts=attempts,
            blocked_reason=(
                f"Assignment `{assignment_name}` could not resolve a usable managed agent. "
                f"Tried: {attempted_text}"
            ),
        )

    @staticmethod
    def _resolve_selected_steps(
        step_map: dict[str, object],
        selected_steps: list[str] | None,
    ) -> set[str] | None:
        if not selected_steps:
            return None

        missing = [step_id for step_id in selected_steps if step_id not in step_map]
        if missing:
            raise ValueError(f"Unknown step ids: {', '.join(missing)}")

        resolved: set[str] = set()
        queue: deque[str] = deque(selected_steps)
        while queue:
            step_id = queue.popleft()
            if step_id in resolved:
                continue
            resolved.add(step_id)
            step = step_map[step_id]
            for dependency_id in step.depends_on:
                if dependency_id not in resolved:
                    queue.append(dependency_id)
        return resolved
