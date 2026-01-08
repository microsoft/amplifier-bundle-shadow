"""Repository management for shadow environments."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
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
    
    async def create_bare_from_local(
        self,
        spec: RepoSpec,
        target_dir: Path,
    ) -> Path:
        """
        Create a bare repository from a local working directory.
        
        PRESERVES ALL GIT HISTORY so pinned commit hashes work.
        If there are uncommitted changes, they're added as a new commit on main.
        
        Args:
            spec: Repository specification with local_path set
            target_dir: Directory to create the bare repo in
            
        Returns:
            Path to the bare repository
        """
        if not spec.local_path:
            raise ValueError(f"RepoSpec has no local_path: {spec}")
        
        local_path = spec.local_path
        bare_path = target_dir / spec.org / f"{spec.name}.git"
        
        # Ensure parent directory exists
        bare_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Step 1: Clone the local repo as bare (PRESERVES ALL HISTORY)
        await self._git_clone_bare(local_path, bare_path)
        
        # Step 2: Check if there are uncommitted changes in the working directory
        stdout, _ = await self._run_git(local_path, "status", "--porcelain")
        has_uncommitted_changes = bool(stdout.strip())
        
        if has_uncommitted_changes:
            # Step 3: Create a new commit with the uncommitted changes
            with tempfile.TemporaryDirectory() as tmp:
                work_path = Path(tmp) / "work"
                
                # Clone from our bare repo (gets full history)
                await self._git_clone(str(bare_path), work_path)
                
                # Configure git user for the snapshot commit
                await self._run_git(work_path, "config", "user.name", "Shadow Snapshot")
                await self._run_git(work_path, "config", "user.email", "shadow@localhost")
                
                # Copy working directory contents (excluding .git) over the clone
                for item in local_path.iterdir():
                    if item.name == '.git':
                        continue
                    dest = work_path / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    if item.is_dir():
                        shutil.copytree(item, dest, symlinks=True)
                    else:
                        shutil.copy2(item, dest)
                
                # Stage all changes
                await self._run_git(work_path, "add", "-A")
                
                # Check if there's actually anything to commit
                stdout, _ = await self._run_git(work_path, "status", "--porcelain")
                if stdout.strip():
                    # Commit the uncommitted changes
                    await self._run_git(
                        work_path,
                        "commit",
                        "-m", f"Shadow snapshot: uncommitted changes from {spec.full_name}",
                    )
                    
                    # Push back to bare repo (update main branch)
                    await self._run_git(work_path, "push", "origin", "HEAD:main", "--force")
        
        return bare_path
    
    async def _run_git(self, cwd: Path, *args: str) -> tuple[str, str]:
        """Run a git command and return stdout/stderr."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(
                f"Git command failed: git {' '.join(args)}\n"
                f"stderr: {stderr.decode()}"
            )
        
        return stdout.decode(), stderr.decode()
    
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
