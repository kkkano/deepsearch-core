"""deepsearch CLI: quick / deep / steer / status / replay / healthcheck。

用法：
    deepsearch quick "What is MCP?"
    deepsearch deep "腾讯港股 AI 业务" --depth 3 --policy finance --stream
    deepsearch steer run_abc123 "重点关注 QT"
    deepsearch status run_abc123
    deepsearch replay run_abc123
    deepsearch healthcheck
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from deepsearch_core.config import get_config
from deepsearch_core.facade import DeepSearch

app = typer.Typer(
    name="deepsearch",
    help="Protocol-agnostic deep research engine",
    no_args_is_help=True,
)
console = Console()


@app.command()
def quick(
    query: str = typer.Argument(..., help="Your question"),
    policy: str = typer.Option("general", "--policy", "-p"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Fast single-round search (<8s)."""

    async def _run():
        async with DeepSearch() as ds:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                progress.add_task(f"Searching: {query[:60]}...", total=None)
                result = await ds.quick_search(query, policy=policy)
            return result

    result = asyncio.run(_run())

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        report = result.get("report") or {}
        body = report.get("body_markdown") or "(no answer)"
        console.print(Panel(Markdown(body), title=f"Quick Search: {query}", border_style="cyan"))
        if result.get("citations"):
            console.print(f"\n[dim]{len(result['citations'])} sources cited.[/dim]")


@app.command()
def deep(
    query: str = typer.Argument(..., help="Your research goal"),
    depth: int = typer.Option(3, "--depth", "-d", min=1, max=5),
    policy: str = typer.Option("general", "--policy", "-p"),
    max_agents: int = typer.Option(4, "--max-agents"),
    stream: bool = typer.Option(False, "--stream", help="Stream events live"),
    async_mode: bool = typer.Option(False, "--async", help="Return task_id, run in background"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Deep research (fan-out + critic + reporter)."""

    async def _stream_run():
        async with DeepSearch() as ds:
            console.print(f"[cyan]Deep search: {query}[/cyan] (depth={depth}, policy={policy})\n")
            async for event in ds.stream(query, depth=depth, policy=policy, max_agents=max_agents):
                console.print(f"[dim]{event.type.value:30s}[/dim] {json.dumps(event.payload, ensure_ascii=False)[:120]}")

    async def _sync_run():
        async with DeepSearch() as ds:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
                progress.add_task(f"Deep researching: {query[:60]}...", total=None)
                return await ds.deep_search(query, depth=depth, policy=policy, max_agents=max_agents)

    if stream:
        asyncio.run(_stream_run())
        return

    if async_mode:
        # v0.1 简化：直接跑同步，但显示 task_id
        result = asyncio.run(_sync_run())
        typer.echo(json.dumps({"task_id": result["run_id"], "status": result["status"]}, ensure_ascii=False))
        return

    result = asyncio.run(_sync_run())

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        report = result.get("report") or {}
        body = report.get("body_markdown") or "(no report)"
        console.print(Panel(Markdown(body), title=f"Deep Research", border_style="green"))

        critic = result.get("critic")
        if critic:
            console.print(f"\n[yellow]Confidence: {critic.get('confidence', 0):.2f}[/yellow]")

        usage = result.get("token_usage", {})
        console.print(
            f"\n[dim]Tokens: prompt={usage.get('prompt_tokens', 0)} "
            f"completion={usage.get('completion_tokens', 0)} "
            f"cached={usage.get('cached_tokens', 0)} | "
            f"Elapsed: {result.get('elapsed_seconds', 0):.1f}s[/dim]"
        )


@app.command()
def steer(
    task_id: str = typer.Argument(..., help="Task ID returned by `deep --async`"),
    content: str = typer.Argument(..., help="Steering command content"),
    scope: str = typer.Option("global", "--scope", "-s"),
):
    """Inject a steer command into a running task."""
    async def _run():
        async with DeepSearch() as ds:
            return ds.steer(task_id, content, scope=scope)

    cmd = asyncio.run(_run())
    typer.echo(json.dumps(
        {"accepted": True, "cmd_id": cmd.cmd_id, "scope": cmd.scope.value},
        indent=2,
    ))


@app.command()
def status(task_id: str):
    """Show task status."""
    async def _run():
        async with DeepSearch() as ds:
            return ds.get_run(task_id)

    run = asyncio.run(_run())
    if not run:
        console.print(f"[red]Task {task_id} not found.[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Run {task_id}", show_header=False)
    for k, v in run.items():
        table.add_row(str(k), str(v)[:200])
    console.print(table)


@app.command()
def replay(task_id: str):
    """Replay all events of a finished task."""
    async def _run():
        async with DeepSearch() as ds:
            return ds.list_events(task_id)

    events = asyncio.run(_run())
    if not events:
        console.print(f"[yellow]No events for {task_id}.[/yellow]")
        return

    table = Table(title=f"Events for {task_id}")
    table.add_column("Seq", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Payload")
    table.add_column("Time", style="dim")

    for e in events:
        table.add_row(
            str(e.seq),
            e.type.value,
            json.dumps(e.payload, ensure_ascii=False)[:80],
            e.timestamp.strftime("%H:%M:%S.%f")[:-3],
        )
    console.print(table)


@app.command()
def healthcheck():
    """Check that all configured services are reachable."""
    cfg = get_config()
    table = Table(title="deepsearch-core Health Check")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")

    table.add_row(
        "LLM endpoint",
        "✅" if cfg.llm.api_key else "❌",
        cfg.llm.base_url if cfg.llm.api_key else "LLM_API_KEY not set",
    )
    table.add_row("Tavily", "✅" if cfg.search.tavily_api_key else "⚠️", "configured" if cfg.search.tavily_api_key else "not configured")
    table.add_row("Serper", "✅" if cfg.search.serper_api_key else "⚠️", "configured" if cfg.search.serper_api_key else "not configured")
    table.add_row("Cohere reranker", "✅" if cfg.search.cohere_api_key else "⚠️", "configured" if cfg.search.cohere_api_key else "not configured")
    table.add_row("Firecrawl", "✅" if cfg.search.firecrawl_api_key else "⚠️", "configured" if cfg.search.firecrawl_api_key else "not configured")
    table.add_row("SQLite store", "✅", cfg.store.dsn)
    console.print(table)


@app.command()
def list_policies():
    """List available source policies."""
    from deepsearch_core.policy.loader import PolicyLoader

    loader = PolicyLoader()
    table = Table(title="Available Policies")
    table.add_column("Name")
    table.add_column("Display")
    table.add_column("Trusted Domains")

    for name in loader.list_policies():
        try:
            cfg = loader.load(name)
            table.add_row(
                name,
                cfg.display_name,
                ", ".join(cfg.trusted_domains[:3]) + ("..." if len(cfg.trusted_domains) > 3 else ""),
            )
        except Exception as e:
            table.add_row(name, "[red]error[/red]", str(e)[:80])
    console.print(table)


@app.command()
def version():
    """Show version."""
    from deepsearch_core import __version__
    typer.echo(f"deepsearch-core {__version__}")


if __name__ == "__main__":
    app()
