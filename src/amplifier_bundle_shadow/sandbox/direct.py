"""Direct execution backend (no sandboxing) for restricted environments."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..models import ExecResult
from .base import SandboxBackend


class DirectBackend(SandboxBackend):
    """
    Direct execution backend without OS-level sandboxing.
    
    This backend is used when Bubblewrap/Seatbelt are unavailable or
    when running in restricted environments (like unprivileged containers).
    
    It still provides:
    - Git URL rewriting via .gitconfig
    - Isolated workspace and home directories
    - Environment variable isolation
    
    But does NOT provide:
    - Process namespace isolation
    - Filesystem mount restrictions
    - Network filtering (relies on /etc/hosts)
    
    WARNING: This mode provides minimal isolation. Use only for testing
    in already-isolated environments (like CI containers).
    """
    
    @property
    def name(self) -> str:
        return "Direct"
    
    @property
    def is_available(self) -> bool:
        """Direct mode is always available."""
        return True
    
    async def exec(
        self,
        command: str,
        env: dict[str, str],
        cwd: str = "/workspace",
        timeout: int = 300,
    ) -> ExecResult:
        """Execute a command directly (no sandboxing)."""
        # Map virtual paths to actual paths
        actual_cwd = self._map_path(cwd)
        actual_env = self._prepare_env(env)
        
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(actual_cwd),
            env=actual_env,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
            )
        
        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
    
    async def shell(self, env: dict[str, str], cwd: str = "/workspace") -> None:
        """Open an interactive shell (no sandboxing)."""
        actual_cwd = self._map_path(cwd)
        actual_env = self._prepare_env(env)
        
        # Change to the workspace directory
        os.chdir(actual_cwd)
        
        # Update environment
        os.environ.clear()
        os.environ.update(actual_env)
        
        # Replace with shell
        os.execvp("bash", ["bash"])
    
    def _map_path(self, virtual_path: str) -> Path:
        """Map a virtual sandbox path to the actual filesystem path."""
        if virtual_path.startswith("/workspace"):
            return self.workspace_dir / virtual_path[len("/workspace"):].lstrip("/")
        elif virtual_path.startswith("/home/shadow"):
            return self.home_dir / virtual_path[len("/home/shadow"):].lstrip("/")
        elif virtual_path.startswith("/repos"):
            return self.repos_dir.parent / virtual_path[len("/repos"):].lstrip("/")
        else:
            # For other paths, try workspace as default
            return self.workspace_dir
    
    def _prepare_env(self, env: dict[str, str]) -> dict[str, str]:
        """Prepare environment variables, mapping paths."""
        actual_env = dict(os.environ)  # Start with current env
        
        # Override with sandbox env
        for key, value in env.items():
            if key == "HOME":
                actual_env[key] = str(self.home_dir)
            elif key == "AMPLIFIER_HOME":
                actual_env[key] = str(self.home_dir / ".amplifier")
            else:
                actual_env[key] = value
        
        # Ensure git uses our config
        actual_env["GIT_CONFIG_GLOBAL"] = str(self.gitconfig_file)
        
        # Add repos path for git URL rewriting
        actual_env["SHADOW_REPOS_DIR"] = str(self.repos_dir.parent)
        
        return actual_env
    
    def get_default_env(self, shadow_id: str) -> dict[str, str]:
        """Get default environment variables for direct execution."""
        return {
            "HOME": str(self.home_dir),
            "AMPLIFIER_HOME": str(self.home_dir / ".amplifier"),
            "SHADOW_ENV_ID": shadow_id,
            "SHADOW_ENV_ACTIVE": "true",
            "SHADOW_MODE": "direct",
            "PATH": f"{self.home_dir}/.local/bin:/usr/local/bin:/usr/bin:/bin",
            "TERM": os.environ.get("TERM", "xterm-256color"),
            "GIT_CONFIG_GLOBAL": str(self.gitconfig_file),
        }
