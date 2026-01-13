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
                        "preflight",
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
            "preflight": self._preflight,
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

    async def _preflight(self, input: dict[str, Any]) -> ToolResult:
        """Run pre-flight checks on a shadow environment.

        Validates that the environment is properly configured and ready for testing:
        - Gitea server is running and accessible
        - Local source repos are properly mirrored
        - Required tools are installed (uv, pip, git)
        - API keys are available
        """
        shadow_id = input.get("shadow_id")

        if not shadow_id:
            return ToolResult(output=None, error={"message": "shadow_id is required"})

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        checks: list[dict[str, Any]] = []
        all_passed = True

        # Check 1: Container is running
        is_running = await env.is_running()
        checks.append({
            "name": "Container running",
            "passed": is_running,
            "message": "Container is running" if is_running else "Container not running",
        })
        if not is_running:
            all_passed = False
            return ToolResult(
                output={
                    "shadow_id": shadow_id,
                    "passed": False,
                    "checks": checks,
                    "message": "Container not running - cannot proceed with other checks",
                },
                error=None,
            )

        # Check 2: Gitea server is accessible
        gitea_result = await env.exec("curl -sf http://localhost:3000/api/v1/version", timeout=10)
        gitea_ok = gitea_result.exit_code == 0
        checks.append({
            "name": "Gitea server",
            "passed": gitea_ok,
            "message": "Gitea running on localhost:3000" if gitea_ok else "Gitea not accessible",
        })
        if not gitea_ok:
            all_passed = False

        # Check 3: Local sources are mirrored
        for repo in env.repos:
            repo_check_cmd = f"curl -sf http://shadow:shadow@localhost:3000/api/v1/repos/{repo.org}/{repo.name}"
            repo_result = await env.exec(repo_check_cmd, timeout=10)
            repo_ok = repo_result.exit_code == 0
            checks.append({
                "name": f"Repo mirrored: {repo.full_name}",
                "passed": repo_ok,
                "message": f"{repo.full_name} available in Gitea" if repo_ok else f"{repo.full_name} not found in Gitea",
            })
            if not repo_ok:
                all_passed = False

        # Check 4: Required tools installed
        tools_to_check = [
            ("uv", "uv --version"),
            ("pip", "pip --version"),
            ("git", "git --version"),
        ]
        for tool_name, tool_cmd in tools_to_check:
            tool_result = await env.exec(tool_cmd, timeout=10)
            tool_ok = tool_result.exit_code == 0
            version = tool_result.stdout.strip().split("\n")[0] if tool_ok else "not found"
            checks.append({
                "name": f"Tool: {tool_name}",
                "passed": tool_ok,
                "message": version if tool_ok else f"{tool_name} not installed",
            })
            if not tool_ok:
                all_passed = False

        # Check 5: API keys available
        api_keys_found: list[str] = []
        api_keys_missing: list[str] = []
        for key in DEFAULT_ENV_PATTERNS:
            key_result = await env.exec(f"test -n \"${{{key}}}\" && echo 'set'", timeout=5)
            if key_result.exit_code == 0 and "set" in key_result.stdout:
                api_keys_found.append(key)
            else:
                api_keys_missing.append(key)

        # At least one API key should be present
        has_api_key = len(api_keys_found) > 0
        checks.append({
            "name": "API keys",
            "passed": has_api_key,
            "message": f"Found: {', '.join(api_keys_found)}" if api_keys_found else "No API keys found",
            "details": {
                "found": api_keys_found,
                "missing": api_keys_missing,
            },
        })
        if not has_api_key:
            all_passed = False

        # Check 6: Git URL rewriting configured
        git_config_result = await env.exec('git config --global --get-regexp "url.*insteadOf"', timeout=10)
        rewrite_ok = git_config_result.exit_code == 0 and "insteadOf" in git_config_result.stdout
        rewrite_count = git_config_result.stdout.count("insteadOf") if rewrite_ok else 0
        checks.append({
            "name": "Git URL rewriting",
            "passed": rewrite_ok,
            "message": f"{rewrite_count} insteadOf rules configured" if rewrite_ok else "No URL rewriting configured",
        })
        if not rewrite_ok:
            all_passed = False

        return ToolResult(
            output={
                "shadow_id": shadow_id,
                "passed": all_passed,
                "checks": checks,
                "message": "All pre-flight checks passed" if all_passed else "Some checks failed - review before testing",
            },
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
