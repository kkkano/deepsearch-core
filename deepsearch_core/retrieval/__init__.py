"""检索增强层：HyDE / Query expansion / Deduplication。"""

from deepsearch_core.retrieval.dedup import deduplicate_results
from deepsearch_core.retrieval.hyde import HyDEGenerator
from deepsearch_core.retrieval.query_expansion import QueryExpander

__all__ = ["HyDEGenerator", "QueryExpander", "deduplicate_results"]
