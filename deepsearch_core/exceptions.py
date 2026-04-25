"""自定义异常。"""

from __future__ import annotations


class DeepSearchError(Exception):
    """所有 deepsearch-core 异常的基类。"""

    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, **data):
        super().__init__(message)
        self.message = message
        self.data = data

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "data": self.data}


class TaskNotFoundError(DeepSearchError):
    code = "TASK_NOT_FOUND"


class TaskAlreadyFinishedError(DeepSearchError):
    code = "TASK_ALREADY_FINISHED"


class RateLimitError(DeepSearchError):
    code = "RATE_LIMIT"


class LLMError(DeepSearchError):
    code = "LLM_ERROR"


class SearchError(DeepSearchError):
    code = "SEARCH_ERROR"


class TimeoutError_(DeepSearchError):
    code = "TIMEOUT"


class InvalidPolicyError(DeepSearchError):
    code = "INVALID_POLICY"


class ConfigError(DeepSearchError):
    code = "CONFIG_ERROR"
