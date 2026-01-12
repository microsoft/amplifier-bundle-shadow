"""Command-line interface for amplifier-shadow."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .manager import ShadowManager, DEFAULT_IMAGE

# Common API key environment variables to auto-passthrough
DEFAULT_ENV_PATTERNS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OLLAMA_HOST",
    "VLLM_API_BASE",
]

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
    "--local",
    "-l",
    multiple=True,
    help="Local source mapping: /path/to/repo:org/name (can be repeated)",
)
@click.option(
    "--name", "-n", help="Name for the environment (auto-generated if not provided)"
)
@click.option(
    "--image",
    "-i",
    default=DEFAULT_IMAGE,
    help=f"Container image to use (default: {DEFAULT_IMAGE})",
)
@click.option(
    "--env",
    "-e",
    multiple=True,
    help="Environment variable to pass (KEY=VALUE or just KEY to inherit from host)",
)
@click.option(
    "--env-file",
    type=click.Path(exists=True, path_type=Path),
    help="File with environment variables (one per line, KEY=VALUE format)",
)
@click.option(
    "--pass-api-keys/--no-pass-api-keys",
    default=True,
    help="Auto-pass common API key env vars from host (default: enabled)",
)
@click.pass_context
def create(
    ctx: click.Context,
    local: tuple[str, ...],
    name: str | None,
    image: str,
    env: tuple[str, ...],
    env_file: Path | None,
    pass_api_keys: bool,
) -> None:
    """
    Create a new shadow environment with local source overrides.
    
    Local sources are snapshots of your working directory (including uncommitted
    changes) that will be used instead of fetching from GitHub when those repos
    are referenced as git dependencies.
    
    Examples:
    
        # Create shadow with local amplifier-core
        amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core
        
        # Multiple local sources
        amplifier-shadow create \\
            --local ~/repos/amplifier-core:microsoft/amplifier-core \\
            --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \\
            --name test-env
        
        # Then test inside the shadow:
        amplifier-shadow exec test-env "uv pip install git+https://github.com/microsoft/amplifier"
        # -> amplifier-core/foundation use your local snapshots
    """
    manager: ShadowManager = ctx.obj["manager"]

    if not local:
        error_console.print("[red]Error:[/red] At least one --local source is required")
        error_console.print()
        error_console.print("Example:")
        error_console.print(
            "  amplifier-shadow create --local ~/repos/myrepo:org/myrepo"
        )
        sys.exit(1)

    # Collect environment variables
    env_vars: dict[str, str] = {}

    # Auto-pass common API keys from host environment
    if pass_api_keys:
        for key in DEFAULT_ENV_PATTERNS:
            value = os.environ.get(key)
            if value:
                env_vars[key] = value

    # Load from env file if specified
    if env_file:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

    # Process explicit --env options
    for env_spec in env:
        if "=" in env_spec:
            key, value = env_spec.split("=", 1)
            env_vars[key] = value
        else:
            # Just a key name - inherit from host
            value = os.environ.get(env_spec)
            if value:
                env_vars[env_spec] = value

    with console.status("[bold blue]Creating shadow environment..."):
        try:
            shadow_env = run_async(
                manager.create(
                    local_sources=list(local),
                    name=name,
                    image=image,
                    env=env_vars if env_vars else None,
                )
            )
        except Exception as e:
            error_console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    console.print()
    console.print("[green]Shadow environment ready![/green]")
    console.print(f"  ID: [bold]{shadow_env.shadow_id}[/bold]")
    console.print("  Mode: container")

    # Show what was captured with commit SHAs for verification
    console.print()
    console.print("[bold]Local sources snapshotted:[/bold]")
    for r in shadow_env.repos:
        commit = r.snapshot_commit or "unknown"
        console.print(f"  {r.full_name} @ [cyan]{commit[:8]}[/cyan]")
        console.print(f"    from: {r.local_path}")

    # Show env vars passed (names only, not values)
    if env_vars:
        console.print()
        console.print(f"[bold]Environment variables passed:[/bold] {len(env_vars)}")
        console.print(f"  {', '.join(sorted(env_vars.keys()))}")

    # Verification hint
    console.print()
    console.print(
        "[dim]Tip: After install, compare commit hashes with uv output to verify local code is used.[/dim]"
    )

    console.print()
    console.print("Next steps:")
    console.print(
        f'  [dim]amplifier-shadow exec {shadow_env.shadow_id} "uv pip install git+https://github.com/..."[/dim]'
    )
    console.print(f"  [dim]amplifier-shadow shell {shadow_env.shadow_id}[/dim]")


@main.command()
@click.argument("shadow_id")
@click.argument("command")
@click.option(
    "--timeout", "-t", type=int, default=300, help="Timeout in seconds (default: 300)"
)
@click.pass_context
def exec(ctx: click.Context, shadow_id: str, command: str, timeout: int) -> None:
    """
    Execute a command inside a shadow environment.

    SHADOW_ID: ID of the shadow environment

    COMMAND: Shell command to execute

    Examples:

        amplifier-shadow exec shadow-abc123 "uv pip install git+https://github.com/microsoft/amplifier"

        amplifier-shadow exec shadow-abc123 "amplifier --version"
    """
    manager: ShadowManager = ctx.obj["manager"]

    env = manager.get(shadow_id)
    if not env:
        error_console.print(
            f"[red]Error:[/red] Shadow environment not found: {shadow_id}"
        )
        sys.exit(1)

    # Check if container is running
    if not run_async(env.is_running()):
        error_console.print(f"[red]Error:[/red] Container not running for: {shadow_id}")
        error_console.print(
            "[dim]The container may have stopped. Try recreating the environment.[/dim]"
        )
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

        amplifier-shadow shell shadow-abc123
    """
    manager: ShadowManager = ctx.obj["manager"]

    env = manager.get(shadow_id)
    if not env:
        error_console.print(
            f"[red]Error:[/red] Shadow environment not found: {shadow_id}"
        )
        sys.exit(1)

    # Check if container is running
    if not run_async(env.is_running()):
        error_console.print(f"[red]Error:[/red] Container not running for: {shadow_id}")
        error_console.print(
            "[dim]The container may have stopped. Try recreating the environment.[/dim]"
        )
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
        error_console.print(
            f"[red]Error:[/red] Shadow environment not found: {shadow_id}"
        )
        sys.exit(1)

    info = env.to_info()
    is_running = run_async(env.is_running())

    console.print(f"[bold]Shadow Environment: {info.shadow_id}[/bold]")
    console.print()
    console.print(f"  Mode: {info.mode}")
    console.print(
        f"  Running: {'[green]yes[/green]' if is_running else '[red]no[/red]'}"
    )
    console.print(f"  Created: {info.created_at}")
    console.print(f"  Directory: {info.shadow_dir}")
    console.print()
    console.print("  Repositories:")
    for repo in info.repos:
        console.print(f"    - {repo}")

    # Show snapshot commits for verification
    if info.snapshot_commits:
        console.print()
        console.print("[bold]Local Sources (for verification):[/bold]")
        for repo, commit in info.snapshot_commits.items():
            console.print(f"  {repo}")
            console.print(f"    Snapshot HEAD: [cyan]{commit[:8]}[/cyan]")

    # Show env vars passed
    if info.env_vars_passed:
        console.print()
        console.print(
            f"[bold]Environment Variables:[/bold] {', '.join(info.env_vars_passed)}"
        )


@main.command()
@click.argument("shadow_id")
@click.option("--path", "-p", help="Limit diff to specific path")
@click.pass_context
def diff(ctx: click.Context, shadow_id: str, path: str | None) -> None:
    """Show changed files in a shadow environment."""
    manager: ShadowManager = ctx.obj["manager"]

    env = manager.get(shadow_id)
    if not env:
        error_console.print(
            f"[red]Error:[/red] Shadow environment not found: {shadow_id}"
        )
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
def extract(
    ctx: click.Context, shadow_id: str, container_path: str, host_path: str
) -> None:
    """
    Extract a file from a shadow environment to the host.

    SHADOW_ID: ID of the shadow environment

    CONTAINER_PATH: Path inside the container (e.g., /workspace/file.py)

    HOST_PATH: Destination path on the host

    Example:

        amplifier-shadow extract shadow-abc123 /workspace/src/fix.py ./fix.py
    """
    manager: ShadowManager = ctx.obj["manager"]

    env = manager.get(shadow_id)
    if not env:
        error_console.print(
            f"[red]Error:[/red] Shadow environment not found: {shadow_id}"
        )
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
def inject(
    ctx: click.Context, shadow_id: str, host_path: str, container_path: str
) -> None:
    """
    Copy a file from the host into a shadow environment.

    SHADOW_ID: ID of the shadow environment

    HOST_PATH: Source path on the host

    CONTAINER_PATH: Destination path inside the container

    Example:

        amplifier-shadow inject shadow-abc123 ./fix.py /workspace/src/fix.py
    """
    manager: ShadowManager = ctx.obj["manager"]

    env = manager.get(shadow_id)
    if not env:
        error_console.print(
            f"[red]Error:[/red] Shadow environment not found: {shadow_id}"
        )
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
@click.option(
    "--force", "-f", is_flag=True, help="Force destruction without confirmation"
)
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
@click.option(
    "--force", "-f", is_flag=True, help="Force destruction without confirmation"
)
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


@main.command()
@click.option(
    "--tag",
    "-t",
    default=None,
    help="Image tag (default: amplifier-shadow:local)",
)
@click.option("--force", "-f", is_flag=True, help="Rebuild even if image exists")
@click.pass_context
def build(ctx: click.Context, tag: str | None, force: bool) -> None:
    """
    Build the shadow container image locally.

    Builds the container image from bundled Dockerfile without needing
    to pull from a registry. The image is built locally and tagged
    as 'amplifier-shadow:local' by default.

    Examples:

        # Build with default tag
        amplifier-shadow build

        # Build with custom tag
        amplifier-shadow build --tag my-shadow:v1

        # Force rebuild
        amplifier-shadow build --force
    """
    from .builder import ImageBuilder, DEFAULT_IMAGE_NAME

    image_tag = tag or DEFAULT_IMAGE_NAME
    builder = ImageBuilder()

    # Check if image exists
    if not force and run_async(builder.image_exists(image_tag)):
        console.print(f"[yellow]Image already exists:[/yellow] {image_tag}")
        console.print("[dim]Use --force to rebuild[/dim]")
        return

    console.print(f"[bold blue]Building image:[/bold blue] {image_tag}")
    console.print()

    def progress(line: str) -> None:
        # Filter noisy docker build output
        if line.startswith("#") or "--->" in line or "Removing" in line:
            console.print(f"[dim]{line}[/dim]")
        elif "Successfully" in line or "DONE" in line:
            console.print(f"[green]{line}[/green]")
        elif "ERROR" in line or "error" in line.lower():
            console.print(f"[red]{line}[/red]")

    try:
        run_async(builder.build(image_tag, progress_callback=progress))
        console.print()
        console.print(f"[green]Successfully built:[/green] {image_tag}")
    except Exception as e:
        error_console.print(f"[red]Build failed:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
