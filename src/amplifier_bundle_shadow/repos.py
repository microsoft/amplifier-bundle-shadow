"""Repository management for shadow environments."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from .models import RepoSpec


class RepoManager:
    """
    Manages repository cloning and caching for shadow environments.
    
    Repositories are cached in a staging directory and copied as bare repos
    into each shadow environment. This allows fast creation of new environments
    while keeping them isolated from each other.
    """
    
    def __init__(self, staging_dir: Path):
        """
        Initialize the repository manager.
        
        Args:
            staging_dir: Directory for caching cloned repositories
        """
        self.staging_dir = staging_dir
        self.staging_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_staged_path(self, spec: RepoSpec) -> Path:
        """Get the path where a repo is staged."""
        return self.staging_dir / spec.org / spec.name
    
    def is_staged(self, spec: RepoSpec) -> bool:
        """Check if a repo is already staged."""
        staged_path = self._get_staged_path(spec)
        return (staged_path / ".git").exists() or (staged_path / "HEAD").exists()
    
    async def ensure_staged(self, spec: RepoSpec, update: bool = True) -> Path:
        """
        Ensure a repository is cloned in the staging directory.
        
        Args:
            spec: Repository specification
            update: Whether to fetch updates if already staged
            
        Returns:
            Path to the staged repository
        """
        staged_path = self._get_staged_path(spec)
        
        if self.is_staged(spec):
            if update:
                # Update existing clone
                await self._git_fetch(staged_path)
        else:
            # Fresh clone
            await self._git_clone(spec.url, staged_path)
        
        return staged_path
    
    async def create_bare_repo(
        self,
        spec: RepoSpec,
        target_dir: Path,
    ) -> Path:
        """
        Create a bare repository copy for a shadow environment.
        
        Args:
            spec: Repository specification
            target_dir: Directory to create the bare repo in
            
        Returns:
            Path to the bare repository
        """
        staged_path = self._get_staged_path(spec)
        bare_path = target_dir / spec.org / f"{spec.name}.git"
        
        # Ensure parent directory exists
        bare_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Clone as bare repo
        await self._git_clone_bare(staged_path, bare_path)
        
        # If a specific branch is requested, update HEAD
        if spec.branch:
            await self._git_set_head(bare_path, spec.branch)
        
        return bare_path
    
    async def _git_clone(self, url: str, target: Path) -> None:
        """Clone a repository."""
        target.parent.mkdir(parents=True, exist_ok=True)
        
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--quiet", url, str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to clone {url}: {stderr.decode()}")
    
    async def _git_clone_bare(self, source: Path, target: Path) -> None:
        """Clone a repository as a bare repo."""
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--bare", "--quiet", str(source), str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to create bare clone: {stderr.decode()}")
    
    async def _git_fetch(self, repo_path: Path) -> None:
        """Fetch updates for a repository."""
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), "fetch", "--all", "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Ignore fetch errors - repo might be offline
    
    async def _git_set_head(self, bare_path: Path, branch: str) -> None:
        """Set HEAD of a bare repo to a specific branch."""
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(bare_path),
            "symbolic-ref", "HEAD", f"refs/heads/{branch}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            # Branch might not exist, try to check it out
            # This is a best-effort operation
            pass
    
    def cleanup_staged(self, spec: RepoSpec) -> None:
        """Remove a staged repository."""
        staged_path = self._get_staged_path(spec)
        if staged_path.exists():
            shutil.rmtree(staged_path)
    
    def cleanup_all_staged(self) -> None:
        """Remove all staged repositories."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
            self.staging_dir.mkdir(parents=True, exist_ok=True)
