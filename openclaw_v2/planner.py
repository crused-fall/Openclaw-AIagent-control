from __future__ import annotations

from .config import AppConfig
from .models import WorkItem


class PipelinePlanner:
    """Build a work plan from a named pipeline template."""

    def __init__(self, config: AppConfig):
        self.config = config

    def build_plan(self) -> list[WorkItem]:
        pipeline_name = self.config.runtime.pipeline
        if pipeline_name not in self.config.pipelines:
            raise ValueError(f"Unknown pipeline: {pipeline_name}")

        work_items: list[WorkItem] = []
        for step in self.config.pipelines[pipeline_name]:
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
