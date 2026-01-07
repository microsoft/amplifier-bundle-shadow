"""Abstract base class for sandbox backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import ExecResult


class SandboxBackend(ABC):
    """
    Abstract base for sandbox implementations.
    
    Each backend provides process isolation and filesystem restrictions
    using platform-specific mechanisms (Bubblewrap on Linux, Seatbelt on macOS).
    """
    
    def __init__(
        self,
        shadow_dir: Path,
        repos_dir: Path,
        network_enabled: bool = True,
    ):
        """
        Initialize the sandbox backend.
        
        Args:
            shadow_dir: Directory containing this shadow environment's files
            repos_dir: Directory containing bare git repos
            network_enabled: Whether to allow network access (except github.com)
        """
        self.shadow_dir = shadow_dir
        self.repos_dir = repos_dir
        self.network_enabled = network_enabled
        
        # Standard paths within the shadow environment
        self.workspace_dir = shadow_dir / "workspace"
        self.home_dir = shadow_dir / "home"
        self.hosts_file = shadow_dir / "hosts"
        self.gitconfig_file = shadow_dir / "home" / ".gitconfig"
    
    @abstractmethod
    async def exec(
        self,
        command: str,
        env: dict[str, str],
        cwd: str = "/workspace",
        timeout: int = 300,
    ) -> "ExecResult":
        """
        Execute a command inside the sandbox.
        
        Args:
            command: Shell command to execute
            env: Environment variables to set
            cwd: Working directory inside sandbox
            timeout: Maximum execution time in seconds
            
        Returns:
            ExecResult with exit code, stdout, and stderr
        """
        pass
    
    @abstractmethod
    async def shell(self, env: dict[str, str], cwd: str = "/workspace") -> None:
        """
        Open an interactive shell inside the sandbox.
        
        This replaces the current process with the sandboxed shell.
        
        Args:
            env: Environment variables to set
            cwd: Working directory inside sandbox
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this backend."""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available on the current system."""
        pass
    
    def get_default_env(self, shadow_id: str) -> dict[str, str]:
        """Get default environment variables for sandbox execution."""
        return {
            "HOME": "/home/shadow",
            "AMPLIFIER_HOME": "/home/shadow/.amplifier",
            "SHADOW_ENV_ID": shadow_id,
            "SHADOW_ENV_ACTIVE": "true",
            "PATH": "/usr/local/bin:/usr/bin:/bin:/home/shadow/.local/bin",
            "TERM": "xterm-256color",
        }
