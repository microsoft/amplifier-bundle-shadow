"""
Amplifier tool module for shadow environment management.

This module provides the 'shadow' tool for use within Amplifier sessions,
enabling agents to create and interact with isolated shadow environments
for safe testing of changes.
"""

from __future__ import annotations

__amplifier_module_type__ = "tool"

import os
from typing import Any

from amplifier_core import ToolResult

from amplifier_bundle_shadow import ShadowManager
from amplifier_bundle_shadow.manager import DEFAULT_IMAGE

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


class ShadowTool:
    """Shadow environment tool for Amplifier."""

    def __init__(self):
        self._manager: ShadowManager | None = None

    @property
    def manager(self) -> ShadowManager:
        """Lazy-initialize the shadow manager."""
        if self._manager is None:
            self._manager = ShadowManager()
        return self._manager

    @property
    def name(self) -> str:
        return "shadow"

    @property
    def description(self) -> str:
        return (
            "Manage shadow environments for safe testing of Amplifier changes. "
            "PREFER this tool over the `amplifier-shadow` CLI when available - "
            "it provides the same operations with better integration."
        )

    @property
    def input_schema(self) -> dict:
        """JSON Schema for the tool parameters."""
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "create",
                        "add-source",
                        "exec",
                        "diff",
                        "extract",
                        "inject",
                        "list",
                        "status",
                        "destroy",
                    ],
                    "description": "The operation to perform",
                },
                "local_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Local source mappings for create: '/path/to/repo:org/name'. These repos will be snapshotted (including uncommitted changes) and served via local Gitea instead of fetching from GitHub.",
                },
                "name": {
                    "type": "string",
                    "description": "Optional name for the environment (create operation)",
                },
                "image": {
                    "type": "string",
                    "description": f"Container image to use (default: {DEFAULT_IMAGE})",
                },
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID (for exec/diff/extract/inject/status/destroy)",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (exec operation)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for exec (default: 300)",
                },
                "path": {
                    "type": "string",
                    "description": "Path filter for diff operation",
                },
                "container_path": {
                    "type": "string",
                    "description": "Path inside container (for extract/inject), e.g., /workspace/file.py",
                },
                "host_path": {
                    "type": "string",
                    "description": "Path on host (for extract/inject)",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force destruction (destroy operation)",
                },
            },
            "required": ["operation"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a shadow tool operation."""
        operation = input.get("operation")

        operations = {
            "create": self._create,
            "add-source": self._add_source,
            "exec": self._exec,
            "diff": self._diff,
            "extract": self._extract,
            "inject": self._inject,
            "list": self._list,
            "status": self._status,
            "destroy": self._destroy,
        }

        if operation not in operations:
            return ToolResult(
                output=None,
                error={
                    "message": f"Unknown operation: {operation}. Available: {', '.join(operations.keys())}"
                },
            )

        try:
            return await operations[operation](input)
        except Exception as e:
            return ToolResult(output=None, error={"message": str(e)})

    async def _create(self, input: dict[str, Any]) -> ToolResult:
        """Create a new shadow environment with local source overrides."""
        local_sources = input.get("local_sources")
        name = input.get("name")
        image = input.get("image", DEFAULT_IMAGE)

        if not local_sources:
            return ToolResult(
                output=None,
                error={
                    "message": "local_sources parameter is required. Format: ['/path/to/repo:org/name', ...]"
                },
            )

        # Auto-passthrough common API key env vars from host
        env_vars: dict[str, str] = {}
        for key in DEFAULT_ENV_PATTERNS:
            value = os.environ.get(key)
            if value:
                env_vars[key] = value

        env = await self.manager.create(
            local_sources=local_sources,
            name=name,
            image=image,
            env=env_vars if env_vars else None,
        )

        # Build snapshot_commits for observability
        snapshot_commits = {
            r.full_name: r.snapshot_commit for r in env.repos if r.snapshot_commit
        }

        return ToolResult(
            output={
                "shadow_id": env.shadow_id,
                "mode": "container",
                "local_sources": [
                    {
                        "repo": r.full_name,
                        "local_path": str(r.local_path) if r.local_path else None,
                        "snapshot_commit": r.snapshot_commit,
                    }
                    for r in env.repos
                ],
                "status": env.status.value,
                "snapshot_commits": snapshot_commits,
                "env_vars_passed": list(env_vars.keys()) if env_vars else [],
            },
            error=None,
        )

    async def _add_source(self, input: dict[str, Any]) -> ToolResult:
        """Add local sources to an existing shadow environment."""
        shadow_id = input.get("shadow_id")
        local_sources = input.get("local_sources")

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})
        if not local_sources:
            return ToolResult(
                output=None,
                error={
                    "message": "local_sources parameter is required. Format: ['/path/to/repo:org/name', ...]"
                },
            )

        env = await self.manager.add_source(shadow_id, local_sources)

        return ToolResult(
            output={
                "shadow_id": env.shadow_id,
                "local_sources": [
                    {
                        "repo": r.full_name,
                        "local_path": str(r.local_path) if r.local_path else None,
                    }
                    for r in env.repos
                ],
                "status": env.status.value,
                "message": f"Added {len(local_sources)} source(s) to shadow environment",
            },
            error=None,
        )

    async def _exec(self, input: dict[str, Any]) -> ToolResult:
        """Execute a command inside a shadow environment."""
        shadow_id = input.get("shadow_id")
        command = input.get("command")
        timeout = input.get("timeout", 300)

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})
        if not command:
            return ToolResult(output=None, error={"message": "command is required"})

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        # Check if container is running
        if not await env.is_running():
            return ToolResult(
                output=None,
                error={
                    "message": f"Container not running for shadow environment: {shadow_id}. Try recreating it."
                },
            )

        result = await env.exec(command, timeout=timeout)

        return ToolResult(
            output={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            error=None
            if result.exit_code == 0
            else {"message": f"Command failed with exit code {result.exit_code}"},
        )

    async def _diff(self, input: dict[str, Any]) -> ToolResult:
        """Show changed files in a shadow environment."""
        shadow_id = input.get("shadow_id")
        path = input.get("path")

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        changed = env.diff(path)

        return ToolResult(
            output={
                "changed_files": [
                    {
                        "path": f.path,
                        "change_type": f.change_type,
                        "size": f.size,
                    }
                    for f in changed
                ],
            },
            error=None,
        )

    async def _extract(self, input: dict[str, Any]) -> ToolResult:
        """Extract a file from a shadow environment."""
        shadow_id = input.get("shadow_id")
        container_path = input.get("container_path") or input.get(
            "sandbox_path"
        )  # backward compat
        host_path = input.get("host_path")

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})
        if not container_path:
            return ToolResult(
                output=None, error={"message": "container_path is required"}
            )
        if not host_path:
            return ToolResult(output=None, error={"message": "host_path is required"})

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        bytes_copied = env.extract(container_path, host_path)

        return ToolResult(
            output={
                "bytes_copied": bytes_copied,
                "host_path": host_path,
            },
            error=None,
        )

    async def _inject(self, input: dict[str, Any]) -> ToolResult:
        """Inject a file into a shadow environment."""
        shadow_id = input.get("shadow_id")
        host_path = input.get("host_path")
        container_path = input.get("container_path") or input.get(
            "sandbox_path"
        )  # backward compat

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})
        if not host_path:
            return ToolResult(output=None, error={"message": "host_path is required"})
        if not container_path:
            return ToolResult(
                output=None, error={"message": "container_path is required"}
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        env.inject(host_path, container_path)

        return ToolResult(
            output={"container_path": container_path},
            error=None,
        )

    async def _list(self, input: dict[str, Any]) -> ToolResult:
        """List all shadow environments."""
        environments = self.manager.list_environments()

        return ToolResult(
            output={
                "environments": [env.to_info().to_dict() for env in environments],
            },
            error=None,
        )

    async def _status(self, input: dict[str, Any]) -> ToolResult:
        """Get status of a shadow environment."""
        shadow_id = input.get("shadow_id")

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        info = env.to_info()
        is_running = await env.is_running()

        # Include snapshot_commits and env_vars_passed in output
        output = {
            **info.to_dict(),
            "running": is_running,
        }
        # Ensure these fields are always present (to_dict may omit if None)
        if "snapshot_commits" not in output:
            output["snapshot_commits"] = info.snapshot_commits or {}
        if "env_vars_passed" not in output:
            output["env_vars_passed"] = info.env_vars_passed or []

        return ToolResult(
            output=output,
            error=None,
        )

    async def _destroy(self, input: dict[str, Any]) -> ToolResult:
        """Destroy a shadow environment."""
        shadow_id = input.get("shadow_id")
        force = input.get("force", False)

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})

        try:
            await self.manager.destroy(shadow_id, force=force)
            return ToolResult(
                output={"shadow_id": shadow_id, "destroyed": True},
                error=None,
            )
        except ValueError as e:
            return ToolResult(output=None, error={"message": str(e)})


async def mount(coordinator, config: dict[str, Any] | None = None):
    """Module entrypoint: mounts the shadow tool."""
    tool = ShadowTool()
    await coordinator.mount("tools", tool, name="shadow")

    async def cleanup():
        pass  # No cleanup needed

    return cleanup
