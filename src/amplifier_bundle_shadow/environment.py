"""Shadow environment implementation."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ChangedFile, ExecResult, RepoSpec, ShadowInfo, ShadowStatus

if TYPE_CHECKING:
    from .sandbox.base import SandboxBackend


@dataclass
class ShadowEnvironment:
    """
    Represents an active shadow environment.
    
    A shadow environment provides an isolated space for testing Amplifier
    ecosystem changes. It includes:
    - Local source snapshots with selective git URL rewriting
    - An isolated workspace directory
    - An isolated home directory with fresh AMPLIFIER_HOME
    """
    
    shadow_id: str
    repos: list[RepoSpec]
    shadow_dir: Path
    backend: "SandboxBackend"
    created_at: datetime
    status: ShadowStatus = ShadowStatus.READY
    _baseline_hashes: dict[str, str] = field(default_factory=dict)
    
    @property
    def workspace_dir(self) -> Path:
        """Directory for workspace files inside the sandbox."""
        return self.shadow_dir / "workspace"
    
    @property
    def home_dir(self) -> Path:
        """Home directory inside the sandbox."""
        return self.shadow_dir / "home"
    
    @property
    def repos_dir(self) -> Path:
        """Directory containing mock git repos."""
        return self.shadow_dir / "repos" / "github.com"
    
    def _get_env(self) -> dict[str, str]:
        """Get environment variables for sandbox execution."""
        return self.backend.get_default_env(self.shadow_id)
    
    async def exec(self, command: str, timeout: int = 300) -> ExecResult:
        """
        Execute a command inside the sandbox.
        
        Args:
            command: Shell command to execute
            timeout: Maximum execution time in seconds
            
        Returns:
            ExecResult with exit code, stdout, and stderr
        """
        return await self.backend.exec(
            command=command,
            env=self._get_env(),
            cwd="/workspace",
            timeout=timeout,
        )
    
    async def shell(self) -> None:
        """
        Open an interactive shell inside the sandbox.
        
        This replaces the current process with the sandboxed shell.
        """
        await self.backend.shell(
            env=self._get_env(),
            cwd="/workspace",
        )
    
    def snapshot_baseline(self) -> None:
        """
        Take a snapshot of the current workspace state for diff tracking.
        
        This records file hashes to detect changes later.
        """
        self._baseline_hashes.clear()
        
        for file_path in self.workspace_dir.rglob("*"):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(self.workspace_dir))
                self._baseline_hashes[rel_path] = self._hash_file(file_path)
    
    def _hash_file(self, path: Path) -> str:
        """Compute a quick hash of a file."""
        hasher = hashlib.md5()
        try:
            with open(path, "rb") as f:
                # Read in chunks for large files
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, IOError):
            return ""
    
    def diff(self, path: str | None = None) -> list[ChangedFile]:
        """
        Get list of changed files in the workspace.
        
        Args:
            path: Optional path to limit the diff to
            
        Returns:
            List of ChangedFile objects describing changes
        """
        changed: list[ChangedFile] = []
        base_path = self.workspace_dir
        
        if path:
            base_path = self.workspace_dir / path.lstrip("/")
            if not base_path.exists():
                return changed
        
        # Find current files
        current_files: dict[str, str] = {}
        for file_path in base_path.rglob("*"):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(self.workspace_dir))
                current_files[rel_path] = self._hash_file(file_path)
        
        # Compare with baseline
        baseline_paths = set(self._baseline_hashes.keys())
        current_paths = set(current_files.keys())
        
        # Added files
        for rel_path in current_paths - baseline_paths:
            file_path = self.workspace_dir / rel_path
            changed.append(ChangedFile(
                path=f"/workspace/{rel_path}",
                change_type="added",
                size=file_path.stat().st_size if file_path.exists() else None,
            ))
        
        # Deleted files
        for rel_path in baseline_paths - current_paths:
            changed.append(ChangedFile(
                path=f"/workspace/{rel_path}",
                change_type="deleted",
                size=None,
            ))
        
        # Modified files
        for rel_path in baseline_paths & current_paths:
            if self._baseline_hashes[rel_path] != current_files[rel_path]:
                file_path = self.workspace_dir / rel_path
                changed.append(ChangedFile(
                    path=f"/workspace/{rel_path}",
                    change_type="modified",
                    size=file_path.stat().st_size if file_path.exists() else None,
                ))
        
        return changed
    
    def extract(self, sandbox_path: str, host_path: str) -> int:
        """
        Extract a file from the sandbox to the host.
        
        Args:
            sandbox_path: Path inside the sandbox (e.g., /workspace/file.py)
            host_path: Destination path on the host
            
        Returns:
            Number of bytes copied
        """
        # Map sandbox path to actual path
        if sandbox_path.startswith("/workspace"):
            source = self.workspace_dir / sandbox_path[len("/workspace/"):]
        elif sandbox_path.startswith("/home/shadow"):
            source = self.home_dir / sandbox_path[len("/home/shadow/"):]
        else:
            raise ValueError(f"Cannot extract from path: {sandbox_path}")
        
        if not source.exists():
            raise FileNotFoundError(f"File not found in sandbox: {sandbox_path}")
        
        dest = Path(host_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
            # Return approximate size
            total = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
            return total
        else:
            shutil.copy2(source, dest)
            return dest.stat().st_size
    
    def inject(self, host_path: str, sandbox_path: str) -> None:
        """
        Copy a file from the host into the sandbox.
        
        Args:
            host_path: Source path on the host
            sandbox_path: Destination path inside the sandbox
        """
        source = Path(host_path)
        if not source.exists():
            raise FileNotFoundError(f"File not found on host: {host_path}")
        
        # Map sandbox path to actual path
        if sandbox_path.startswith("/workspace"):
            dest = self.workspace_dir / sandbox_path[len("/workspace/"):]
        elif sandbox_path.startswith("/home/shadow"):
            dest = self.home_dir / sandbox_path[len("/home/shadow/"):]
        else:
            raise ValueError(f"Cannot inject to path: {sandbox_path}")
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(source, dest)
    
    def to_info(self) -> ShadowInfo:
        """Convert to a serializable info object."""
        return ShadowInfo(
            shadow_id=self.shadow_id,
            repos=[r.display_name for r in self.repos],
            mode=self.backend.name,
            status=self.status.value,
            created_at=self.created_at.isoformat(),
            shadow_dir=str(self.shadow_dir),
        )
