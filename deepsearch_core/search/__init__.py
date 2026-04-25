"""搜索引擎层。"""

from deepsearch_core.search.base import BaseSearch, SearchResult
from deepsearch_core.search.crossref import CrossrefSearch
from deepsearch_core.search.duckduckgo import DuckDuckGoSearch
from deepsearch_core.search.firecrawl import FirecrawlReader
from deepsearch_core.search.jina_reader import JinaReader
from deepsearch_core.search.serper import SerperSearch
from deepsearch_core.search.tavily import TavilySearch

__all__ = [
    "BaseSearch",
    "CrossrefSearch",
    "DuckDuckGoSearch",
    "FirecrawlReader",
    "JinaReader",
    "SearchResult",
    "SerperSearch",
    "TavilySearch",
]
