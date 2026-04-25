"""Eval Harness 运行器：跑数据集，自动评分。

运行：
    python eval/runner.py --dataset general.jsonl
    python eval/runner.py --dataset all
    python eval/runner.py --case f001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

DATASETS_DIR = Path(__file__).parent / "datasets"
console = Console()


def load_dataset(name: str) -> list[dict]:
    path = DATASETS_DIR / name
    if not path.exists():
        path = DATASETS_DIR / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {name}")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score_factual(answer: str, expected_facts: list[str]) -> float:
    """简单字符串包含评分（v0.2 用 LLM-as-judge）。"""
    if not expected_facts:
        return 1.0
    answer_lower = answer.lower()
    matched = sum(1 for f in expected_facts if f.lower() in answer_lower)
    return matched / len(expected_facts)


def score_sources(citations: list[dict], expected_include: list[str] | None) -> float:
    if not expected_include:
        return 1.0
    cited_domains = {c.get("domain", "").lower() for c in citations}
    matched = sum(1 for src in expected_include if any(src.lower() in d for d in cited_domains))
    return matched / len(expected_include)


async def run_case(case: dict) -> dict[str, Any]:
    from deepsearch_core import DeepSearch

    async with DeepSearch() as ds:
        result = await ds.quick_search(case["query"], policy=case.get("policy", "general"))

    answer = (result.get("report") or {}).get("body_markdown", "")
    citations = result.get("citations", [])

    factual = score_factual(answer, case.get("expected_facts", []))
    sources = score_sources(citations, case.get("expected_sources_include"))

    return {
        "id": case["id"],
        "query": case["query"],
        "factual": factual,
        "sources": sources,
        "elapsed": result.get("elapsed_seconds", 0),
        "tokens": (result.get("token_usage") or {}).get("total_tokens", 0),
        "passed": factual >= 0.7 and result.get("elapsed_seconds", 0) <= case.get("max_seconds", 60),
    }


async def run_dataset(cases: list[dict]) -> list[dict]:
    results = []
    for case in cases:
        try:
            r = await run_case(case)
        except Exception as e:
            r = {"id": case["id"], "error": str(e), "passed": False}
        results.append(r)
        console.print(f"  ✓ {r['id']}: factual={r.get('factual', 0):.2f} elapsed={r.get('elapsed', 0):.1f}s")
    return results


def print_summary(results: list[dict]) -> None:
    table = Table(title="Eval Summary")
    table.add_column("ID", style="cyan")
    table.add_column("Factual", justify="right")
    table.add_column("Sources", justify="right")
    table.add_column("Elapsed", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Pass", justify="center")

    factual_sum = 0.0
    sources_sum = 0.0
    n = 0
    for r in results:
        if "error" in r:
            table.add_row(r["id"], "[red]error[/red]", "-", "-", "-", "❌")
            continue
        table.add_row(
            r["id"],
            f"{r['factual']:.2f}",
            f"{r['sources']:.2f}",
            f"{r['elapsed']:.1f}s",
            str(r['tokens']),
            "✅" if r['passed'] else "❌",
        )
        factual_sum += r["factual"]
        sources_sum += r["sources"]
        n += 1

    if n:
        table.add_section()
        table.add_row("[bold]AVG", f"[bold]{factual_sum / n:.2f}", f"[bold]{sources_sum / n:.2f}", "", "", "")
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="deepsearch-core eval runner")
    parser.add_argument("--dataset", default="general", help="dataset name or 'all'")
    parser.add_argument("--case", default=None, help="run a single case by id")
    args = parser.parse_args()

    if args.case:
        # 加载所有 dataset，找到对应 id
        all_cases = []
        for jl in DATASETS_DIR.glob("*.jsonl"):
            all_cases.extend(load_dataset(jl.name))
        case = next((c for c in all_cases if c["id"] == args.case), None)
        if not case:
            print(f"Case {args.case} not found")
            sys.exit(1)
        results = asyncio.run(run_dataset([case]))
    elif args.dataset == "all":
        all_cases = []
        for jl in DATASETS_DIR.glob("*.jsonl"):
            all_cases.extend(load_dataset(jl.name))
        results = asyncio.run(run_dataset(all_cases))
    else:
        cases = load_dataset(args.dataset)
        results = asyncio.run(run_dataset(cases))

    print_summary(results)


if __name__ == "__main__":
    main()
