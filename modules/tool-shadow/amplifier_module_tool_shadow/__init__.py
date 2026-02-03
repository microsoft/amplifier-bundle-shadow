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
                        "sync-source",
                        "exec",
                        "exec_batch",
                        "diff",
                        "extract",
                        "inject",
                        "list",
                        "status",
                        "preflight",
                        "build-image",
                        "destroy",
                    ],
                    "description": "The operation to perform",
                },
                "local_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional local source mappings for create: '/path/to/repo:org/name'. These repos will be snapshotted and served via local Gitea. If omitted, creates an isolated environment that uses real GitHub (no URL rewriting).",
                },
                "verify": {
                    "type": "boolean",
                    "description": "Automatically run smoke test after creation (create operation, default: true)",
                },
                "required_env_vars": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Environment variables that must be present (create operation)",
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
                    "description": "Shadow environment ID. Required for exec/diff/extract/inject/status/destroy. Optional for preflight (omit to run pre-create checks).",
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (exec operation)",
                },
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple commands to execute sequentially (exec_batch operation)",
                },
                "fail_fast": {
                    "type": "boolean",
                    "description": "Stop on first failure (exec_batch operation, default: true)",
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
                "health_check": {
                    "type": "boolean",
                    "description": "Run health diagnostics (status operation, default: false)",
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
            "sync-source": self._sync_source,
            "exec": self._exec,
            "exec_batch": self._exec_batch,
            "diff": self._diff,
            "extract": self._extract,
            "inject": self._inject,
            "list": self._list,
            "status": self._status,
            "preflight": self._preflight,
            "build-image": self._build_image,
            "destroy": self._destroy,
        }

        if operation not in operations:
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": f"Unknown operation: {operation}. Available: {', '.join(operations.keys())}"
                },
            )

        try:
            return await operations[operation](input)
        except Exception as e:
            return ToolResult(success=False, output=None, error={"message": str(e)})

    async def _create(self, input: dict[str, Any]) -> ToolResult:
        """Create a new shadow environment.

        Can be used in two modes:
        1. With local_sources: Creates environment with local repo overrides (Gitea serves local snapshots)
        2. Without local_sources: Creates isolated environment that uses real GitHub (no URL rewriting)
        """
        local_sources = input.get("local_sources") or []  # Empty list if not provided
        name = input.get("name")
        image = input.get("image", DEFAULT_IMAGE)
        verify = input.get("verify", True)
        required_env_vars = input.get("required_env_vars", [])

        # Validate required environment variables
        if required_env_vars:
            missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
            if missing_vars:
                return ToolResult(
                    success=False,
                    output=None,
                    error={
                        "message": "Missing required environment variables",
                        "missing_vars": missing_vars,
                        "instructions": "Set these variables in your shell before creating shadow",
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

        output = {
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
        }

        # Run smoke test verification if requested
        if verify and env.repos:
            verification = await self._run_smoke_test(env, snapshot_commits)
            output["verification"] = verification
            output["ready"] = verification["status"] == "PASSED"
        else:
            output["ready"] = True  # No verification requested, assume ready

        return ToolResult(
            output=output,
            error=None,
        )

    async def _run_smoke_test(
        self, env: Any, snapshot_commits: dict[str, str]
    ) -> dict[str, Any]:
        """Run smoke test to verify shadow environment setup.

        Args:
            env: Shadow environment instance
            snapshot_commits: Dict mapping repo names to expected commit hashes

        Returns:
            Verification result dict with status, evidence, and issues
        """
        verification = {
            "status": "PASSED",
            "smoke_test_passed": True,
            "evidence": "",
            "issues": [],
        }

        # Pick first repo from snapshot_commits to test
        if not snapshot_commits:
            verification["status"] = "FAILED"
            verification["smoke_test_passed"] = False
            verification["issues"].append("No repos to verify")
            return verification

        test_repo = list(snapshot_commits.keys())[0]
        expected_commit = snapshot_commits[test_repo]

        try:
            # Clone repo in /tmp, checkout expected commit, and verify
            clone_cmd = (
                f"cd /tmp && "
                f"rm -rf smoke-test && "
                f"git clone https://github.com/{test_repo} smoke-test && "
                f"cd smoke-test && "
                f"git checkout {expected_commit} 2>/dev/null && "
                f"git log -1 --format='%H'"
            )

            result = await env.exec(clone_cmd, timeout=60)

            if result.exit_code != 0:
                verification["status"] = "FAILED"
                verification["smoke_test_passed"] = False
                verification["issues"].append(
                    f"Failed to clone {test_repo}: {result.stderr}"
                )
                return verification

            actual_commit = result.stdout.strip()

            # Compare commits (first 7 chars is sufficient)
            if actual_commit[:7] == expected_commit[:7]:
                verification["evidence"] = (
                    f"Cloned {test_repo}, commit matches {expected_commit[:7]}"
                )
            else:
                verification["status"] = "FAILED"
                verification["smoke_test_passed"] = False
                verification["issues"].append(
                    f"Commit mismatch for {test_repo}: "
                    f"expected {expected_commit[:7]}, got {actual_commit[:7]}"
                )
                verification["evidence"] = f"Cloned {test_repo}, but commit mismatch"

        except Exception as e:
            verification["status"] = "FAILED"
            verification["smoke_test_passed"] = False
            verification["issues"].append(f"Smoke test error: {str(e)}")

        return verification

    async def _add_source(self, input: dict[str, Any]) -> ToolResult:
        """Add local sources to an existing shadow environment."""
        shadow_id = input.get("shadow_id")
        local_sources = input.get("local_sources")

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )
        if not local_sources:
            return ToolResult(
                success=False,
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

    async def _sync_source(self, input: dict[str, Any]) -> ToolResult:
        """Sync local sources to an existing shadow environment.

        Unlike add-source which only adds NEW sources, sync-source is idempotent:
        - If source doesn't exist: adds it (same as add-source)
        - If source already exists: updates it with current local HEAD

        This is the recommended operation for iterative development workflows.
        """
        shadow_id = input.get("shadow_id")
        local_sources = input.get("local_sources")

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )
        if not local_sources:
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": "local_sources parameter is required. Format: ['/path/to/repo:org/name', ...]"
                },
            )

        env = await self.manager.sync_source(shadow_id, local_sources)

        # Build snapshot_commits for observability
        snapshot_commits = {
            r.full_name: r.snapshot_commit for r in env.repos if r.snapshot_commit
        }

        return ToolResult(
            output={
                "shadow_id": env.shadow_id,
                "local_sources": [
                    {
                        "repo": r.full_name,
                        "local_path": str(r.local_path) if r.local_path else None,
                        "snapshot_commit": r.snapshot_commit,
                    }
                    for r in env.repos
                ],
                "snapshot_commits": snapshot_commits,
                "status": env.status.value,
                "message": f"Synced {len(local_sources)} source(s) to shadow environment",
            },
            error=None,
        )

    async def _exec(self, input: dict[str, Any]) -> ToolResult:
        """Execute a command inside a shadow environment."""
        shadow_id = input.get("shadow_id")
        command = input.get("command")
        timeout = input.get("timeout", 300)

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )
        if not command:
            return ToolResult(
                success=False, output=None, error={"message": "command is required"}
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        # Check if container is running
        if not await env.is_running():
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": f"Container not running for shadow environment: {shadow_id}. Try recreating it."
                },
            )

        result = await env.exec(command, timeout=timeout)

        return ToolResult(
            success=result.exit_code == 0,
            output={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            error=None
            if result.exit_code == 0
            else {"message": f"Command failed with exit code {result.exit_code}"},
        )

    async def _exec_batch(self, input: dict[str, Any]) -> ToolResult:
        """Execute multiple commands sequentially in a shadow environment."""
        shadow_id = input.get("shadow_id")
        commands = input.get("commands")
        fail_fast = input.get("fail_fast", True)
        timeout = input.get("timeout", 300)

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )
        if not commands:
            return ToolResult(
                success=False,
                output=None,
                error={"message": "commands parameter is required (array of strings)"},
            )
        if not isinstance(commands, list):
            return ToolResult(
                success=False,
                output=None,
                error={"message": "commands must be an array of strings"},
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        # Check if container is running
        if not await env.is_running():
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": f"Container not running for shadow environment: {shadow_id}. Try recreating it."
                },
            )

        steps = []
        failed_at = None
        overall_success = True

        for idx, command in enumerate(commands):
            result = await env.exec(command, timeout=timeout)

            step = {
                "command": command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            steps.append(step)

            if result.exit_code != 0:
                overall_success = False
                if fail_fast:
                    failed_at = idx
                    break

        return ToolResult(
            success=overall_success,
            output={
                "steps": steps,
                "success": overall_success,
                "failed_at": failed_at,
            },
            error=None
            if overall_success
            else {
                "message": f"Batch execution failed at step {failed_at}"
                if failed_at is not None
                else "Some commands failed"
            },
        )

    async def _diff(self, input: dict[str, Any]) -> ToolResult:
        """Show changed files in a shadow environment."""
        shadow_id = input.get("shadow_id")
        path = input.get("path")

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
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
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )
        if not container_path:
            return ToolResult(
                success=False,
                output=None,
                error={"message": "container_path is required"},
            )
        if not host_path:
            return ToolResult(
                success=False, output=None, error={"message": "host_path is required"}
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
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
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )
        if not host_path:
            return ToolResult(
                success=False, output=None, error={"message": "host_path is required"}
            )
        if not container_path:
            return ToolResult(
                success=False,
                output=None,
                error={"message": "container_path is required"},
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
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
        health_check = input.get("health_check", False)

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )

        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
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

        # Run health check diagnostics if requested
        if health_check:
            health = await self._run_health_check(env)
            output["health"] = health

        return ToolResult(
            output=output,
            error=None,
        )

    async def _run_health_check(self, env: Any) -> dict[str, Any]:
        """Run health diagnostics on a shadow environment.

        Args:
            env: Shadow environment instance

        Returns:
            Health check result dict with diagnostics
        """
        health = {
            "container_running": False,
            "gitea_accessible": False,
            "git_config_valid": False,
            "env_vars_present": [],
            "issues": [],
        }

        # Check 1: Container running
        health["container_running"] = await env.is_running()
        if not health["container_running"]:
            health["issues"].append("Container is not running")
            return health  # Can't check other things if container is down

        # Check 2: Gitea accessible
        try:
            gitea_result = await env.exec(
                "curl -sf http://localhost:3000/api/v1/version", timeout=10
            )
            health["gitea_accessible"] = gitea_result.exit_code == 0
            if not health["gitea_accessible"]:
                health["issues"].append("Gitea server not accessible")
        except Exception as e:
            health["issues"].append(f"Gitea check failed: {str(e)}")

        # Check 3: Git config valid
        try:
            git_config_result = await env.exec(
                'git config --get-regexp "url.*insteadOf"', timeout=10
            )
            health["git_config_valid"] = git_config_result.exit_code == 0
            if not health["git_config_valid"]:
                health["issues"].append("Git URL rewriting not configured")
        except Exception as e:
            health["issues"].append(f"Git config check failed: {str(e)}")

        # Check 4: Env vars present
        for key in DEFAULT_ENV_PATTERNS:
            try:
                key_result = await env.exec(
                    f"test -n \"${{{key}}}\" && echo 'set'", timeout=5
                )
                if key_result.exit_code == 0 and "set" in key_result.stdout:
                    health["env_vars_present"].append(key)
            except Exception:
                pass  # Skip this env var check

        if not health["env_vars_present"]:
            health["issues"].append("No API keys found in environment")

        return health

    async def _preflight_pre_create(self, input: dict[str, Any]) -> ToolResult:
        """Run pre-create preflight checks (BEFORE creating a shadow environment).

        Checks host prerequisites:
        - Docker/Podman binary available
        - Docker daemon running and accessible
        - Shadow container image available (or can be built)
        - API keys available in host environment
        """
        import shutil
        import subprocess

        checks: list[dict[str, Any]] = []
        all_passed = True
        setup_instructions: list[str] = []

        # Check 1: Container runtime binary available
        runtime = None
        if shutil.which("podman"):
            runtime = "podman"
        elif shutil.which("docker"):
            runtime = "docker"

        checks.append(
            {
                "name": "Container runtime binary",
                "passed": runtime is not None,
                "message": f"Found: {runtime}"
                if runtime
                else "Neither docker nor podman found in PATH",
            }
        )
        if not runtime:
            all_passed = False
            setup_instructions.append(
                "Install Docker: https://docs.docker.com/get-docker/ or Podman: https://podman.io/getting-started/installation"
            )
            # Can't continue without runtime
            return ToolResult(
                success=False,
                output={
                    "mode": "pre-create",
                    "passed": False,
                    "checks": checks,
                    "setup_instructions": setup_instructions,
                    "message": "Container runtime not installed - cannot proceed",
                    # SHADOW-006: Structured fallback guidance for downstream agents
                    "fallback": {
                        "reason": "container_runtime_not_installed",
                        "mode": "host_only",
                        "can_create_shadow": False,
                        "recommended_action": "Run tests on host without shadow isolation",
                    },
                },
                error=None,
            )

        # Check 2: Container daemon running
        try:
            # Use 'info' command which requires daemon to be running
            result = subprocess.run(
                [runtime, "info"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            daemon_running = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            daemon_running = False

        checks.append(
            {
                "name": "Container daemon running",
                "passed": daemon_running,
                "message": f"{runtime} daemon is running"
                if daemon_running
                else f"{runtime} daemon not running or not accessible",
            }
        )
        if not daemon_running:
            all_passed = False
            if runtime == "docker":
                setup_instructions.append(
                    "Start Docker: 'open -a Docker' (macOS) or 'systemctl start docker' (Linux)"
                )
            else:
                setup_instructions.append(
                    "Start Podman: 'podman machine start' (macOS) or 'systemctl start podman' (Linux)"
                )
            # Can't continue without daemon
            return ToolResult(
                success=False,
                output={
                    "mode": "pre-create",
                    "passed": False,
                    "checks": checks,
                    "setup_instructions": setup_instructions,
                    "runtime": runtime,
                    "message": f"{runtime} daemon not running - cannot proceed",
                    # SHADOW-006: Structured fallback guidance for downstream agents
                    "fallback": {
                        "reason": "container_daemon_not_running",
                        "mode": "host_only",
                        "can_create_shadow": False,
                        "recommended_action": "Start container daemon or run tests on host",
                    },
                },
                error=None,
            )

        # Check 3: Shadow image available
        try:
            result = subprocess.run(
                [runtime, "images", "-q", DEFAULT_IMAGE],
                capture_output=True,
                text=True,
                timeout=10,
            )
            image_exists = bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            image_exists = False

        checks.append(
            {
                "name": "Shadow image available",
                "passed": image_exists,
                "message": f"Image {DEFAULT_IMAGE} found"
                if image_exists
                else f"Image {DEFAULT_IMAGE} not found (will auto-build on create)",
            }
        )
        # Note: We don't fail all_passed for missing image because create will auto-build
        # But we still provide setup instructions for users who want to pre-build
        if not image_exists:
            setup_instructions.append(
                "Optional: Pre-build image with 'build-image' operation or 'amplifier-shadow build'. "
                "Note: 'create' will auto-build if image is missing."
            )

        # Check 4: API keys available in host environment
        api_keys_found: list[str] = []
        api_keys_missing: list[str] = []
        for key in DEFAULT_ENV_PATTERNS:
            if os.environ.get(key):
                api_keys_found.append(key)
            else:
                api_keys_missing.append(key)

        has_api_key = len(api_keys_found) > 0
        checks.append(
            {
                "name": "API keys in host environment",
                "passed": has_api_key,
                "message": f"Found: {', '.join(api_keys_found)}"
                if api_keys_found
                else "No API keys found",
                "details": {
                    "found": api_keys_found,
                    "missing": api_keys_missing,
                },
            }
        )
        if not has_api_key:
            all_passed = False
            setup_instructions.append(
                "Set at least one API key: export ANTHROPIC_API_KEY=... (or OPENAI_API_KEY, etc.)"
            )

        # Determine fallback guidance based on what failed
        fallback = None
        if not all_passed:
            # Identify the most severe failure for fallback recommendation
            if not image_exists and daemon_running:
                fallback = {
                    "reason": "image_not_available",
                    "mode": "auto_build",
                    "can_create_shadow": True,  # create will auto-build the image
                    "recommended_action": "Proceed with create (will auto-build) or pre-build with 'build-image' operation",
                }
            elif not has_api_key:
                fallback = {
                    "reason": "no_api_keys",
                    "mode": "host_only",
                    "can_create_shadow": True,  # Can create, but limited use
                    "recommended_action": "Set API keys or run without LLM features",
                }

        return ToolResult(
            success=all_passed,
            output={
                "mode": "pre-create",
                "passed": all_passed,
                "checks": checks,
                "runtime": runtime,
                "setup_instructions": setup_instructions
                if setup_instructions
                else None,
                "message": "All pre-create checks passed - ready to create shadow environment"
                if all_passed
                else "Some checks failed - review setup_instructions",
                # SHADOW-006: Structured fallback guidance for downstream agents
                "fallback": fallback,
            },
            error=None,
        )

    async def _preflight(self, input: dict[str, Any]) -> ToolResult:
        """Run pre-flight checks for shadow environments.

        Two modes of operation:

        1. PRE-CREATE MODE (no shadow_id): Checks prerequisites BEFORE creating an environment
           - Docker/Podman binary available
           - Docker daemon running and accessible
           - Shadow container image available
           - API keys available in host environment

        2. ENVIRONMENT MODE (with shadow_id): Checks an existing environment
           - Container running
           - Gitea server accessible
           - Local sources mirrored
           - Required tools installed
           - API keys available in container
           - Git URL rewriting configured
        """
        shadow_id = input.get("shadow_id")

        # If no shadow_id, run pre-create checks
        if not shadow_id:
            return await self._preflight_pre_create(input)

        # Otherwise, run environment checks
        env = self.manager.get(shadow_id)
        if not env:
            return ToolResult(
                success=False,
                output=None,
                error={"message": f"Shadow environment not found: {shadow_id}"},
            )

        checks: list[dict[str, Any]] = []
        all_passed = True

        # Check 1: Container is running
        is_running = await env.is_running()
        checks.append(
            {
                "name": "Container running",
                "passed": is_running,
                "message": "Container is running"
                if is_running
                else "Container not running",
            }
        )
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
        gitea_result = await env.exec(
            "curl -sf http://localhost:3000/api/v1/version", timeout=10
        )
        gitea_ok = gitea_result.exit_code == 0
        checks.append(
            {
                "name": "Gitea server",
                "passed": gitea_ok,
                "message": "Gitea running on localhost:3000"
                if gitea_ok
                else "Gitea not accessible",
            }
        )
        if not gitea_ok:
            all_passed = False

        # Check 3: Local sources are mirrored
        for repo in env.repos:
            repo_check_cmd = f"curl -sf http://shadow:shadow@localhost:3000/api/v1/repos/{repo.org}/{repo.name}"
            repo_result = await env.exec(repo_check_cmd, timeout=10)
            repo_ok = repo_result.exit_code == 0
            checks.append(
                {
                    "name": f"Repo mirrored: {repo.full_name}",
                    "passed": repo_ok,
                    "message": f"{repo.full_name} available in Gitea"
                    if repo_ok
                    else f"{repo.full_name} not found in Gitea",
                }
            )
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
            version = (
                tool_result.stdout.strip().split("\n")[0] if tool_ok else "not found"
            )
            checks.append(
                {
                    "name": f"Tool: {tool_name}",
                    "passed": tool_ok,
                    "message": version if tool_ok else f"{tool_name} not installed",
                }
            )
            if not tool_ok:
                all_passed = False

        # Check 5: API keys available
        api_keys_found: list[str] = []
        api_keys_missing: list[str] = []
        for key in DEFAULT_ENV_PATTERNS:
            key_result = await env.exec(
                f"test -n \"${{{key}}}\" && echo 'set'", timeout=5
            )
            if key_result.exit_code == 0 and "set" in key_result.stdout:
                api_keys_found.append(key)
            else:
                api_keys_missing.append(key)

        # At least one API key should be present
        has_api_key = len(api_keys_found) > 0
        checks.append(
            {
                "name": "API keys",
                "passed": has_api_key,
                "message": f"Found: {', '.join(api_keys_found)}"
                if api_keys_found
                else "No API keys found",
                "details": {
                    "found": api_keys_found,
                    "missing": api_keys_missing,
                },
            }
        )
        if not has_api_key:
            all_passed = False

        # Check 6: Git URL rewriting configured
        # Note: git config outputs "insteadof" (lowercase), not "insteadOf"
        git_config_result = await env.exec(
            'git config --global --get-regexp "url.*insteadOf"', timeout=10
        )
        stdout_lower = git_config_result.stdout.lower()
        rewrite_ok = git_config_result.exit_code == 0 and "insteadof" in stdout_lower
        rewrite_count = stdout_lower.count("insteadof") if rewrite_ok else 0
        checks.append(
            {
                "name": "Git URL rewriting",
                "passed": rewrite_ok,
                "message": f"{rewrite_count} insteadOf rules configured"
                if rewrite_ok
                else "No URL rewriting configured",
            }
        )
        if not rewrite_ok:
            all_passed = False

        return ToolResult(
            output={
                "shadow_id": shadow_id,
                "passed": all_passed,
                "checks": checks,
                "message": "All pre-flight checks passed"
                if all_passed
                else "Some checks failed - review before testing",
            },
            error=None,
        )

    async def _build_image(self, input: dict[str, Any]) -> ToolResult:
        """Build the shadow container image.

        This operation builds the amplifier-shadow container image locally.
        The image is required for shadow environments but will be auto-built
        on first `create` if missing. Use this operation to:
        - Pre-build the image before creating shadows
        - Rebuild after updating the shadow bundle
        - Verify the build process works
        """
        import shutil

        force = input.get("force", False)
        tag = input.get("image", DEFAULT_IMAGE)

        # Check for container runtime
        runtime = None
        if shutil.which("podman"):
            runtime = "podman"
        elif shutil.which("docker"):
            runtime = "docker"

        if not runtime:
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": "No container runtime found. Install Docker or Podman first.",
                    "code": "no_container_runtime",
                },
            )

        try:
            from amplifier_bundle_shadow.builder import ImageBuilder

            builder = ImageBuilder()

            # Check if image already exists
            image_exists = await builder.image_exists(tag)
            if image_exists and not force:
                return ToolResult(
                    output={
                        "image": tag,
                        "built": False,
                        "message": f"Image {tag} already exists. Use force=true to rebuild.",
                    },
                    error=None,
                )

            # Build the image
            progress_lines: list[str] = []

            def progress_callback(line: str) -> None:
                progress_lines.append(line)

            await builder.build(tag, progress_callback=progress_callback)

            return ToolResult(
                output={
                    "image": tag,
                    "built": True,
                    "message": f"Successfully built image {tag}",
                    "build_output_lines": len(progress_lines),
                },
                error=None,
            )

        except FileNotFoundError as e:
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": f"Could not find container build files: {e}",
                    "code": "build_files_not_found",
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error={
                    "message": f"Failed to build image: {e}",
                    "code": "build_failed",
                },
            )

    async def _destroy(self, input: dict[str, Any]) -> ToolResult:
        """Destroy a shadow environment."""
        shadow_id = input.get("shadow_id")
        force = input.get("force", False)

        if not shadow_id:
            return ToolResult(
                success=False, output=None, error={"message": "shadow_id is required"}
            )

        try:
            await self.manager.destroy(shadow_id, force=force)
            return ToolResult(
                output={"shadow_id": shadow_id, "destroyed": True},
                error=None,
            )
        except ValueError as e:
            return ToolResult(success=False, output=None, error={"message": str(e)})


async def mount(coordinator, config: dict[str, Any] | None = None):
    """Module entrypoint: mounts the shadow tool."""
    tool = ShadowTool()
    await coordinator.mount("tools", tool, name="shadow")

    async def cleanup():
        pass  # No cleanup needed

    return cleanup
