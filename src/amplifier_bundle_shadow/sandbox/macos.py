"""Seatbelt-based sandbox for macOS."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from ..models import ExecResult
from .base import SandboxBackend


class SeatbeltBackend(SandboxBackend):
    """
    Seatbelt-based sandbox for macOS.
    
    Uses sandbox-exec with a custom profile to create isolated environments with:
    - Restricted filesystem access
    - Custom environment variables
    - Local repo mounts with selective git URL rewriting
    
    Note: macOS Seatbelt is less flexible than Bubblewrap - it can't easily
    remap paths, so we use environment variables and symlinks instead.
    """
    
    @property
    def name(self) -> str:
        return "Seatbelt"
    
    @property
    def is_available(self) -> bool:
        """Check if sandbox-exec is available (built into macOS)."""
        return shutil.which("sandbox-exec") is not None
    
    def _generate_sandbox_profile(self) -> str:
        """Generate a Seatbelt sandbox profile."""
        workspace = str(self.workspace_dir)
        home = str(self.home_dir)
        repos = str(self.repos_dir)
        
        profile = f'''
(version 1)
(deny default)

;; Allow basic system operations
(allow signal)
(allow process-fork)
(allow process-exec)
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix*)
(allow system-socket)

;; Allow reading system directories
(allow file-read*
    (subpath "/usr")
    (subpath "/bin")
    (subpath "/sbin")
    (subpath "/Library")
    (subpath "/System")
    (subpath "/private/var/db")
    (subpath "/dev")
    (subpath "/etc")
    (subpath "/var")
    (subpath "/tmp")
    (subpath "/private/tmp")
    (subpath "/Applications/Xcode.app")
    (literal "/")
)

;; Allow reading and executing from common tool locations
(allow file-read* file-execute
    (subpath "/usr/bin")
    (subpath "/usr/local/bin")
    (subpath "/opt/homebrew")
    (subpath "/usr/local")
)

;; Allow read/write to shadow workspace
(allow file-read* file-write*
    (subpath "{workspace}")
)

;; Allow read/write to shadow home
(allow file-read* file-write*
    (subpath "{home}")
)

;; Read-only access to local source snapshots
(allow file-read*
    (subpath "{repos}")
)

;; Allow tmp directory operations
(allow file-read* file-write*
    (subpath "/tmp")
    (subpath "/private/tmp")
    (subpath "/var/folders")
    (subpath "/private/var/folders")
)

;; Network access (limited)
(allow network-outbound)
(allow network-inbound)

;; Deny network to github.com (handled via /etc/hosts instead)
;; Seatbelt network filtering by hostname is unreliable, so we rely on hosts file
'''
        return profile
    
    async def exec(
        self,
        command: str,
        env: dict[str, str],
        cwd: str = "/workspace",
        timeout: int = 300,
    ) -> ExecResult:
        """Execute a command inside the Seatbelt sandbox."""
        # Generate sandbox profile
        profile = self._generate_sandbox_profile()
        
        # Write profile to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sb', delete=False) as f:
            f.write(profile)
            profile_path = f.name
        
        try:
            # Build the wrapper script that sets up the environment
            # Since Seatbelt can't remap paths, we use a wrapper script
            actual_workspace = str(self.workspace_dir)
            actual_home = str(self.home_dir)
            
            # Create env string
            env_exports = "\n".join(f'export {k}="{v}"' for k, v in env.items())
            
            # The wrapper script sets up the environment and runs the command
            wrapper_script = f'''
{env_exports}
export HOME="{actual_home}"
cd "{actual_workspace}"
{command}
'''
            
            args = [
                "sandbox-exec",
                "-f", profile_path,
                "/bin/bash", "-c", wrapper_script,
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **env, "HOME": actual_home},
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
        finally:
            # Clean up the profile file
            try:
                os.unlink(profile_path)
            except OSError:
                pass
    
    async def shell(self, env: dict[str, str], cwd: str = "/workspace") -> None:
        """Open an interactive shell in the Seatbelt sandbox."""
        # Generate sandbox profile
        profile = self._generate_sandbox_profile()
        
        # Write profile to temporary file (it will persist for the shell session)
        profile_path = Path(tempfile.gettempdir()) / f"shadow-{os.getpid()}.sb"
        profile_path.write_text(profile)
        
        actual_workspace = str(self.workspace_dir)
        actual_home = str(self.home_dir)
        
        # Set environment
        for k, v in env.items():
            os.environ[k] = v
        os.environ["HOME"] = actual_home
        os.chdir(actual_workspace)
        
        # Replace the current process with the sandboxed shell
        os.execvp("sandbox-exec", [
            "sandbox-exec",
            "-f", str(profile_path),
            "/bin/bash",
        ])
