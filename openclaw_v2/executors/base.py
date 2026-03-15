from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import AppConfig, ProfileConfig
from ..models import AgentResult, ExecutionContext, WorkItem


class Executor(ABC):
    def __init__(self, app_config: AppConfig):
        self.app_config = app_config

    @abstractmethod
    async def execute(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        context: ExecutionContext,
        rendered_prompt: str,
    ) -> AgentResult:
        raise NotImplementedError
