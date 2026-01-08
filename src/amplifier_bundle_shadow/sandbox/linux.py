"""Bubblewrap-based sandbox for Linux."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from ..models import ExecResult
from .base import SandboxBackend


class BubblewrapBackend(SandboxBackend):
    """
    Bubblewrap-based sandbox for Linux.
    
    Uses bwrap to create isolated namespaces with:
    - Read-only system directories
    - Writable workspace and home directories
    - Local repo mounts with selective git URL rewriting
    - Optional network isolation
    """
    
    @property
    def name(self) -> str:
        return "Bubblewrap"
    
    @property
    def is_available(self) -> bool:
        """Check if bubblewrap is installed."""
        return shutil.which("bwrap") is not None
    
    def _build_bwrap_args(
        self,
        env: dict[str, str],
        cwd: str,
    ) -> list[str]:
        """Build the bwrap command arguments."""
        args = ["bwrap"]
        
        # System directories (read-only)
        system_dirs = ["/usr", "/bin", "/lib", "/lib64", "/sbin"]
        for d in system_dirs:
            if Path(d).exists():
                args.extend(["--ro-bind", d, d])
        
        # /etc is special - we bind it read-only
        args.extend(["--ro-bind", "/etc", "/etc"])
        
        # /run is needed for DNS resolution (resolv.conf is often a symlink to /run/...)
        if Path("/run").exists():
            args.extend(["--ro-bind", "/run", "/run"])
        
        # Writable workspace directory
        args.extend(["--bind", str(self.workspace_dir), "/workspace"])
        
        # Writable home directory  
        args.extend(["--bind", str(self.home_dir), "/home/shadow"])
        
        # Mock repos (read-only)
        args.extend(["--ro-bind", str(self.repos_dir), "/repos"])
        
        # /tmp and /var/tmp for temporary files
        args.extend(["--tmpfs", "/tmp"])
        args.extend(["--tmpfs", "/var/tmp"])
        
        # /dev basics
        args.extend(["--dev", "/dev"])
        
        # /proc for process information
        args.extend(["--proc", "/proc"])
        
        # Process isolation
        args.extend([
            "--die-with-parent",
            "--new-session",
            "--unshare-uts",  # Separate hostname
        ])
        
        # Optional network isolation
        if not self.network_enabled:
            args.append("--unshare-net")
        
        # Working directory
        args.extend(["--chdir", cwd])
        
        # Environment variables
        args.append("--clearenv")
        for key, value in env.items():
            args.extend(["--setenv", key, value])
        
        return args
    
    async def exec(
        self,
        command: str,
        env: dict[str, str],
        cwd: str = "/workspace",
        timeout: int = 300,
    ) -> ExecResult:
        """Execute a command inside the Bubblewrap sandbox."""
        args = self._build_bwrap_args(env, cwd)
        args.extend(["/bin/bash", "-c", command])
        
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
        """Open an interactive shell in the Bubblewrap sandbox."""
        args = self._build_bwrap_args(env, cwd)
        args.append("/bin/bash")
        
        # Replace the current process with the sandboxed shell
        os.execvp("bwrap", args)
