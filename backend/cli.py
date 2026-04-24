"""Click CLI entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

import click
from rich.console import Console

from backend.config import Settings
from backend.models import DEFAULT_MODELS

console = Console()

PORT_FILE_NAME = ".coordinator-port"


def _setup_logging(verbose: bool = False) -> None:
    from backend.console import set_verbose

    level = logging.INFO  # keep logger at INFO — verbose output goes through rich console
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiodocker").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%X"))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    set_verbose(verbose)


def _check_proxy_reachable(settings: Settings) -> None:
    """GET /models against cli-proxy-api so we fail fast with a clear message
    if it's not running, instead of waiting for the first chat.completions call
    to time out mid-run.
    """
    url = settings.openai_base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if settings.cliproxy_api_key:
        req.add_header("Authorization", f"Bearer {settings.cliproxy_api_key}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status >= 500:
                raise RuntimeError(f"proxy returned {resp.status}")
    except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as e:
        console.print(
            f"[bold red]fatal:[/bold red] cli-proxy-api at {settings.openai_base_url} "
            f"is not reachable ({e}).\n"
            "Start it with: "
            "/home/dima/cliproxyapi/cli-proxy-api --config /home/dima/cliproxyapi/config.yaml"
        )
        sys.exit(2)


@click.group()
def cli() -> None:
    """CTF Agent — multi-model solver swarm via cli-proxy-api."""


@cli.command("run")
@click.option("--ctfd-url", default=None, help="CTFd URL (overrides .env)")
@click.option("--ctfd-token", default=None, help="CTFd API token (overrides .env)")
@click.option(
    "--image",
    default=None,
    help=(
        "Sandbox image override. Default: picked per-challenge via "
        "backend/profiles.py:suggest_profile (e.g. ctf-swarm:crypto)."
    ),
)
@click.option("--models", multiple=True, help="Model specs (default: all configured)")
@click.option("--challenge", default=None, help="Solve a single challenge directory")
@click.option("--challenges-dir", default="challenges", help="Directory for challenge files")
@click.option("--no-submit", is_flag=True, help="Dry run — don't submit flags")
@click.option("--coordinator-model", default=None, help="Model for coordinator (default: gpt-5.4)")
@click.option("--max-challenges", default=10, type=int, help="Max challenges solved concurrently")
@click.option("--msg-port", default=0, type=int, help="Operator message port (0 = auto-pick)")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def main(
    ctfd_url: str | None,
    ctfd_token: str | None,
    image: str | None,
    models: tuple[str, ...],
    challenge: str | None,
    challenges_dir: str,
    no_submit: bool,
    coordinator_model: str | None,
    max_challenges: int,
    msg_port: int,
    verbose: bool,
) -> None:
    """CTF Agent — multi-model solver swarm.

    Run without --challenge to start the full coordinator (Ctrl+C to stop).
    All LLM traffic goes through the local cli-proxy-api instance (see .env.example).
    """
    _setup_logging(verbose)

    settings = Settings()
    if image is not None:
        settings.sandbox_image = image
    if ctfd_url:
        settings.ctfd_url = ctfd_url
    if ctfd_token:
        settings.ctfd_token = ctfd_token
    settings.max_concurrent_challenges = max_challenges

    _check_proxy_reachable(settings)

    model_specs = list(models) if models else list(DEFAULT_MODELS)

    console.print("[bold]CTF Agent v2[/bold]")
    console.print(f"  CTFd: {settings.ctfd_url}")
    console.print(f"  Proxy: {settings.openai_base_url}")
    console.print(f"  Models: {', '.join(model_specs)}")
    console.print(f"  Image: {settings.sandbox_image or 'per-challenge profile'}")
    console.print(f"  Max challenges: {max_challenges}")
    console.print()

    if challenge:
        asyncio.run(_run_single(settings, challenge, model_specs, no_submit, max_challenges))
    else:
        asyncio.run(_run_coordinator(settings, model_specs, challenges_dir, no_submit, coordinator_model, max_challenges, msg_port))


async def _run_single(
    settings: Settings,
    challenge_dir: str,
    model_specs: list[str],
    no_submit: bool,
    max_challenges: int,
) -> None:
    """Run a single challenge with a swarm."""
    from backend.agents.swarm import ChallengeSwarm
    from backend.cost_tracker import CostTracker
    from backend.ctfd import CTFdClient
    from backend.prompts import ChallengeMeta
    from backend.sandbox import cleanup_orphan_containers, configure_semaphore

    max_containers = max_challenges * len(model_specs)
    configure_semaphore(max_containers)
    await cleanup_orphan_containers()

    challenge_path = Path(challenge_dir)
    meta_path = challenge_path / "metadata.yml"
    if meta_path.exists():
        meta = ChallengeMeta.from_yaml(meta_path)
    else:
        meta = ChallengeMeta(name=challenge_path.name)
        console.print(f"[yellow]No metadata.yml — using directory name '{meta.name}' as challenge name.[/yellow]")
    console.print(f"[bold]Challenge:[/bold] {meta.name} ({meta.category}, {meta.value} pts)")

    ctfd = CTFdClient(
        base_url=settings.ctfd_url,
        token=settings.ctfd_token,
        username=settings.ctfd_user,
        password=settings.ctfd_pass,
    )
    cost_tracker = CostTracker()

    swarm = ChallengeSwarm(
        challenge_dir=str(challenge_path),
        meta=meta,
        ctfd=ctfd,
        cost_tracker=cost_tracker,
        settings=settings,
        model_specs=model_specs,
        no_submit=no_submit,
    )

    try:
        result = await swarm.run()
        from backend.solver_base import FLAG_FOUND
        if result and result.status == FLAG_FOUND:
            console.print(f"\n[bold green]FLAG FOUND:[/bold green] {result.flag}")
        else:
            console.print("\n[bold red]No flag found.[/bold red]")

        console.print("\n[bold]Cost Summary:[/bold]")
        for agent_name in cost_tracker.by_agent:
            console.print(f"  {agent_name}: {cost_tracker.format_usage(agent_name)}")
        console.print(f"  [bold]Total: ${cost_tracker.total_cost_usd:.2f}[/bold]")
    finally:
        await ctfd.close()


async def _run_coordinator(
    settings: Settings,
    model_specs: list[str],
    challenges_dir: str,
    no_submit: bool,
    coordinator_model: str | None,
    max_challenges: int,
    msg_port: int = 0,
) -> None:
    """Run the full coordinator (continuous until Ctrl+C)."""
    from backend.sandbox import cleanup_orphan_containers, configure_semaphore

    max_containers = max_challenges * len(model_specs)
    configure_semaphore(max_containers)
    await cleanup_orphan_containers()
    console.print("[bold]Starting coordinator (Ctrl+C to stop)...[/bold]\n")

    from backend.agents.openai_coordinator import run_openai_coordinator
    results = await run_openai_coordinator(
        settings=settings,
        model_specs=model_specs,
        challenges_root=challenges_dir,
        no_submit=no_submit,
        coordinator_model=coordinator_model,
        msg_port=msg_port,
    )

    console.print("\n[bold]Final Results:[/bold]")
    for challenge, data in results.get("results", {}).items():
        console.print(f"  {challenge}: {data.get('flag', 'no flag')}")
    console.print(f"\n[bold]Total cost: ${results.get('total_cost_usd', 0):.2f}[/bold]")


def _load_port(findings_dir: str, fallback: int) -> int:
    path = Path(findings_dir) / PORT_FILE_NAME
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return fallback


@cli.command("msg")
@click.argument("message")
@click.option(
    "--port",
    default=0,
    type=int,
    help="Coordinator message port. Default: read from findings/.coordinator-port.",
)
@click.option("--host", default="127.0.0.1", help="Coordinator host")
@click.option("--findings-dir", default="findings", help="Where to read .coordinator-port from")
def msg(message: str, port: int, host: str, findings_dir: str) -> None:
    """Send a message to the running coordinator."""
    resolved_port = port or _load_port(findings_dir, fallback=0)
    if not resolved_port:
        console.print(
            f"[red]Could not find coordinator port.[/red] Is the coordinator running?\n"
            f"Expected port file: {Path(findings_dir) / PORT_FILE_NAME}"
        )
        sys.exit(1)

    body = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        f"http://{host}:{resolved_port}/msg",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            console.print(f"[green]Sent:[/green] {data.get('queued', message[:200])}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
