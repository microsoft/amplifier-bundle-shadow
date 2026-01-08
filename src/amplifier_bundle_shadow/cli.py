"""Command-line interface for amplifier-shadow."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .manager import ShadowManager, DEFAULT_IMAGE

console = Console()
error_console = Console(stderr=True)


def run_async(coro):
    """Run an async coroutine in a sync context."""
    return asyncio.run(coro)


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--shadow-home",
    type=click.Path(path_type=Path),
    default=None,
    help="Base directory for shadow data (default: ~/.shadow)",
)
@click.pass_context
def main(ctx: click.Context, shadow_home: Path | None) -> None:
    """
    Shadow environments for safely testing Amplifier ecosystem changes.
    
    Create isolated container environments where local working directories are
    snapshotted and served via an embedded Gitea server. All git operations
    inside the container use your local snapshots instead of fetching from GitHub.
    """
    ctx.ensure_object(dict)
    ctx.obj["manager"] = ShadowManager(shadow_home)


@main.command()
@click.option(
    "--local", "-l",
    multiple=True,
    help="Local source mapping: /path/to/repo:org/name (can be repeated)",
)
@click.option("--name", "-n", help="Name for the environment (auto-generated if not provided)")
@click.option(
    "--image", "-i",
    default=DEFAULT_IMAGE,
    help=f"Container image to use (default: {DEFAULT_IMAGE})",
)
@click.pass_context
def create(
    ctx: click.Context,
    local: tuple[str, ...],
    name: str | None,
    image: str,
) -> None:
    """
    Create a new shadow environment with local source overrides.
    
    Local sources are snapshots of your working directory (including uncommitted
    changes) that will be used instead of fetching from GitHub when those repos
    are referenced as git dependencies.
    
    Examples:
    
        # Create shadow with local amplifier-core
        shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core
        
        # Multiple local sources
        shadow create \\
            --local ~/repos/amplifier-core:microsoft/amplifier-core \\
            --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \\
            --name test-env
        
        # Then test inside the shadow:
        shadow exec test-env "uv pip install git+https://github.com/microsoft/amplifier"
        # -> amplifier-core/foundation use your local snapshots
    """
    manager: ShadowManager = ctx.obj["manager"]
    
    if not local:
        error_console.print("[red]Error:[/red] At least one --local source is required")
        error_console.print()
        error_console.print("Example:")
        error_console.print("  shadow create --local ~/repos/myrepo:org/myrepo")
        sys.exit(1)
    
    with console.status("[bold blue]Creating shadow environment..."):
        try:
            env = run_async(manager.create(
                local_sources=list(local),
                name=name,
                image=image,
            ))
        except Exception as e:
            error_console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
    
    console.print()
    console.print("[green]Shadow environment ready![/green]")
    console.print(f"  ID: [bold]{env.shadow_id}[/bold]")
    console.print(f"  Mode: container")
    console.print(f"  Local sources:")
    for r in env.repos:
        console.print(f"    - {r.full_name} <- {r.local_path}")
    console.print()
    console.print("Next steps:")
    console.print(f"  [dim]shadow exec {env.shadow_id} \"uv pip install git+https://github.com/...\"[/dim]")
    console.print(f"  [dim]shadow shell {env.shadow_id}[/dim]")


@main.command()
@click.argument("shadow_id")
@click.argument("command")
@click.option("--timeout", "-t", type=int, default=300, help="Timeout in seconds (default: 300)")
@click.pass_context
def exec(ctx: click.Context, shadow_id: str, command: str, timeout: int) -> None:
    """
    Execute a command inside a shadow environment.
    
    SHADOW_ID: ID of the shadow environment
    
    COMMAND: Shell command to execute
    
    Examples:
    
        shadow exec shadow-abc123 "uv pip install git+https://github.com/microsoft/amplifier"
        
        shadow exec shadow-abc123 "amplifier --version"
    """
    manager: ShadowManager = ctx.obj["manager"]
    
    env = manager.get(shadow_id)
    if not env:
        error_console.print(f"[red]Error:[/red] Shadow environment not found: {shadow_id}")
        sys.exit(1)
    
    # Check if container is running
    if not run_async(env.is_running()):
        error_console.print(f"[red]Error:[/red] Container not running for: {shadow_id}")
        error_console.print("[dim]The container may have stopped. Try recreating the environment.[/dim]")
        sys.exit(1)
    
    result = run_async(env.exec(command, timeout=timeout))
    
    if result.stdout:
        console.print(result.stdout, end="")
    if result.stderr:
        error_console.print(result.stderr, end="")
    
    sys.exit(result.exit_code)


@main.command()
@click.argument("shadow_id")
@click.pass_context
def shell(ctx: click.Context, shadow_id: str) -> None:
    """
    Open an interactive shell inside a shadow environment.
    
    SHADOW_ID: ID of the shadow environment
    
    Example:
    
        shadow shell shadow-abc123
    """
    manager: ShadowManager = ctx.obj["manager"]
    
    env = manager.get(shadow_id)
    if not env:
        error_console.print(f"[red]Error:[/red] Shadow environment not found: {shadow_id}")
        sys.exit(1)
    
    # Check if container is running
    if not run_async(env.is_running()):
        error_console.print(f"[red]Error:[/red] Container not running for: {shadow_id}")
        error_console.print("[dim]The container may have stopped. Try recreating the environment.[/dim]")
        sys.exit(1)
    
    console.print(f"[dim]Entering shadow environment {shadow_id}...[/dim]")
    console.print("[dim]Type 'exit' to leave.[/dim]")
    console.print()
    
    # This replaces the current process
    run_async(env.shell())


@main.command("list")
@click.pass_context
def list_envs(ctx: click.Context) -> None:
    """List all shadow environments."""
    manager: ShadowManager = ctx.obj["manager"]
    
    environments = manager.list_environments()
    
    if not environments:
        console.print("[dim]No shadow environments found.[/dim]")
        return
    
    table = Table(title="Shadow Environments")
    table.add_column("ID", style="bold")
    table.add_column("Mode")
    table.add_column("Repos")
    table.add_column("Created")
    table.add_column("Running")
    
    for env in environments:
        info = env.to_info()
        is_running = run_async(env.is_running())
        table.add_row(
            info.shadow_id,
            info.mode,
            ", ".join(info.repos[:2]) + ("..." if len(info.repos) > 2 else ""),
            info.created_at[:19],  # Truncate to seconds
            "[green]yes[/green]" if is_running else "[red]no[/red]",
        )
    
    console.print(table)


@main.command()
@click.argument("shadow_id")
@click.pass_context
def status(ctx: click.Context, shadow_id: str) -> None:
    """Show status of a shadow environment."""
    manager: ShadowManager = ctx.obj["manager"]
    
    env = manager.get(shadow_id)
    if not env:
        error_console.print(f"[red]Error:[/red] Shadow environment not found: {shadow_id}")
        sys.exit(1)
    
    info = env.to_info()
    is_running = run_async(env.is_running())
    
    console.print(f"[bold]Shadow Environment: {info.shadow_id}[/bold]")
    console.print()
    console.print(f"  Mode: {info.mode}")
    console.print(f"  Running: {'[green]yes[/green]' if is_running else '[red]no[/red]'}")
    console.print(f"  Created: {info.created_at}")
    console.print(f"  Directory: {info.shadow_dir}")
    console.print()
    console.print("  Repositories:")
    for repo in info.repos:
        console.print(f"    - {repo}")


@main.command()
@click.argument("shadow_id")
@click.option("--path", "-p", help="Limit diff to specific path")
@click.pass_context
def diff(ctx: click.Context, shadow_id: str, path: str | None) -> None:
    """Show changed files in a shadow environment."""
    manager: ShadowManager = ctx.obj["manager"]
    
    env = manager.get(shadow_id)
    if not env:
        error_console.print(f"[red]Error:[/red] Shadow environment not found: {shadow_id}")
        sys.exit(1)
    
    changed = env.diff(path)
    
    if not changed:
        console.print("[dim]No changes detected.[/dim]")
        return
    
    console.print(f"[bold]Changed files ({len(changed)}):[/bold]")
    for file in changed:
        if file.change_type == "added":
            console.print(f"  [green]+ {file.path}[/green]")
        elif file.change_type == "deleted":
            console.print(f"  [red]- {file.path}[/red]")
        else:
            console.print(f"  [yellow]~ {file.path}[/yellow]")


@main.command()
@click.argument("shadow_id")
@click.argument("container_path")
@click.argument("host_path")
@click.pass_context
def extract(ctx: click.Context, shadow_id: str, container_path: str, host_path: str) -> None:
    """
    Extract a file from a shadow environment to the host.
    
    SHADOW_ID: ID of the shadow environment
    
    CONTAINER_PATH: Path inside the container (e.g., /workspace/file.py)
    
    HOST_PATH: Destination path on the host
    
    Example:
    
        shadow extract shadow-abc123 /workspace/src/fix.py ./fix.py
    """
    manager: ShadowManager = ctx.obj["manager"]
    
    env = manager.get(shadow_id)
    if not env:
        error_console.print(f"[red]Error:[/red] Shadow environment not found: {shadow_id}")
        sys.exit(1)
    
    try:
        bytes_copied = env.extract(container_path, host_path)
        console.print(f"[green]Extracted to {host_path}[/green] ({bytes_copied} bytes)")
    except FileNotFoundError as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except ValueError as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.argument("shadow_id")
@click.argument("host_path")
@click.argument("container_path")
@click.pass_context
def inject(ctx: click.Context, shadow_id: str, host_path: str, container_path: str) -> None:
    """
    Copy a file from the host into a shadow environment.
    
    SHADOW_ID: ID of the shadow environment
    
    HOST_PATH: Source path on the host
    
    CONTAINER_PATH: Destination path inside the container
    
    Example:
    
        shadow inject shadow-abc123 ./fix.py /workspace/src/fix.py
    """
    manager: ShadowManager = ctx.obj["manager"]
    
    env = manager.get(shadow_id)
    if not env:
        error_console.print(f"[red]Error:[/red] Shadow environment not found: {shadow_id}")
        sys.exit(1)
    
    try:
        env.inject(host_path, container_path)
        console.print(f"[green]Injected {host_path} to {container_path}[/green]")
    except FileNotFoundError as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except ValueError as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.argument("shadow_id")
@click.option("--force", "-f", is_flag=True, help="Force destruction without confirmation")
@click.pass_context
def destroy(ctx: click.Context, shadow_id: str, force: bool) -> None:
    """
    Destroy a shadow environment.
    
    SHADOW_ID: ID of the shadow environment
    """
    manager: ShadowManager = ctx.obj["manager"]
    
    if not force:
        if not click.confirm(f"Destroy shadow environment '{shadow_id}'?"):
            console.print("[dim]Cancelled.[/dim]")
            return
    
    try:
        run_async(manager.destroy(shadow_id))
        console.print(f"[green]Destroyed {shadow_id}[/green]")
    except ValueError as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command("destroy-all")
@click.option("--force", "-f", is_flag=True, help="Force destruction without confirmation")
@click.pass_context
def destroy_all(ctx: click.Context, force: bool) -> None:
    """Destroy all shadow environments."""
    manager: ShadowManager = ctx.obj["manager"]
    
    if not force:
        if not click.confirm("Destroy ALL shadow environments?"):
            console.print("[dim]Cancelled.[/dim]")
            return
    
    count = run_async(manager.destroy_all(force=True))
    console.print(f"[green]Destroyed {count} environment(s)[/green]")


if __name__ == "__main__":
    main()
