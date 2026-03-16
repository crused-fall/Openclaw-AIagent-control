from __future__ import annotations

from collections import deque

from .config import AppConfig
from .models import WorkItem


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
            if step.profile not in self.config.profiles:
                raise ValueError(f"Unknown profile in pipeline {pipeline_name}: {step.profile}")

            profile = self.config.profiles[step.profile]
            work_items.append(
                WorkItem(
                    id=step.id,
                    title=step.title,
                    profile=step.profile,
                    agent=profile.agent,
                    mode=profile.mode,
                    prompt_template=step.prompt_template,
                    depends_on=list(step.depends_on),
                    metadata=dict(step.metadata),
                )
            )
        return work_items

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
