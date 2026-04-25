"""Steer 中断机制：scope + command + handler。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SteerScope(str, Enum):
    """Steer 命令的影响范围。"""

    CURRENT_STEP = "current_step"  # 仅注入当前节点 prompt，不重规划
    GLOBAL = "global"  # 触发完整重规划（默认）
    NEXT_STEP = "next_step"  # 等当前节点收尾，下个节点应用


class SteerCommand(BaseModel):
    """用户中途注入的指令。"""

    cmd_id: str = Field(default_factory=lambda: f"steer_{uuid.uuid4().hex[:8]}")
    run_id: str
    content: str
    scope: SteerScope = SteerScope.GLOBAL
    created_at: datetime = Field(default_factory=datetime.utcnow)
    applied: bool = False
    applied_at: datetime | None = None
    applied_at_step: str | None = None

    def mark_applied(self, step: str) -> None:
        self.applied = True
        self.applied_at = datetime.utcnow()
        self.applied_at_step = step

    def to_prompt_injection(self) -> str:
        return (
            f"\n\n## ⚠️ User mid-flight directive (received at {self.created_at.isoformat()})\n"
            f"{self.content}\n"
            f"Apply this directive immediately and adjust your reasoning accordingly."
        )
