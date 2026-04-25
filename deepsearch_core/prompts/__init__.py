"""提示词模板。每个 agent / 节点的 system prompt 单独成文件。"""

from deepsearch_core.prompts.critic import CRITIC_SYSTEM_PROMPT
from deepsearch_core.prompts.planner import PLANNER_SYSTEM_PROMPT
from deepsearch_core.prompts.reporter import REPORTER_SYSTEM_PROMPT
from deepsearch_core.prompts.researcher import RESEARCHER_SYSTEM_PROMPT
from deepsearch_core.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT

__all__ = [
    "CRITIC_SYSTEM_PROMPT",
    "PLANNER_SYSTEM_PROMPT",
    "REPORTER_SYSTEM_PROMPT",
    "RESEARCHER_SYSTEM_PROMPT",
    "SUPERVISOR_SYSTEM_PROMPT",
]
