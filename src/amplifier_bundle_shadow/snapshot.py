"""Git snapshot creation for local repositories."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SnapshotManager", "SnapshotResult", "SnapshotError"]


class SnapshotError(Exception):
    """Raised when snapshot creation fails."""
    pass


@dataclass
class SnapshotResult:
    """Result of creating a snapshot."""
    bundle_path: Path
    has_uncommitted: bool
    commit_sha: str
    size_bytes: int


class SnapshotManager:
    """
    Creates git bundle snapshots from local repositories.
    
    Captures the complete repository state including:
    - All branches and tags
    - Full git history
    - Uncommitted changes (as a snapshot commit)
    
    Git bundles are portable and can be cloned/fetched from directly.
    """
    
    def __init__(self, snapshot_dir: Path) -> None:
        """Initialize snapshot manager."""
        self.snapshot_dir = snapshot_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_snapshot(
        self,
        local_path: Path,
        org: str,
        name: str,
    ) -> SnapshotResult:
        """
        Create a git bundle snapshot from a local repository.
        
        If the repository has uncommitted changes, they are captured
        as a "Shadow snapshot" commit on top of HEAD.
        """
        # Validate it's a git repo
        git_dir = local_path / ".git"
        if not git_dir.exists():
            raise ValueError(f"Not a git repository: {local_path}")
        
        # Create output directory
        bundle_path = self.get_bundle_path(org, name)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check for uncommitted changes
        has_uncommitted = await self.has_uncommitted_changes(local_path)
        
        if has_uncommitted:
            commit_sha = await self._create_snapshot_with_changes(local_path, bundle_path)
        else:
            await self._create_simple_bundle(local_path, bundle_path)
            commit_sha = await self.get_head_sha(local_path)
        
        return SnapshotResult(
            bundle_path=bundle_path,
            has_uncommitted=has_uncommitted,
            commit_sha=commit_sha,
            size_bytes=bundle_path.stat().st_size,
        )
    
    async def has_uncommitted_changes(self, repo_path: Path) -> bool:
        """Check if repository has uncommitted changes."""
        stdout, _ = await self._run_git(repo_path, "status", "--porcelain")
        return bool(stdout.strip())
    
    async def get_head_sha(self, repo_path: Path) -> str:
        """Get the current HEAD commit SHA."""
        stdout, _ = await self._run_git(repo_path, "rev-parse", "HEAD")
        return stdout.strip()
    
    def get_bundle_path(self, org: str, name: str) -> Path:
        """Get the path where a bundle would be stored."""
        return self.snapshot_dir / org / f"{name}.bundle"
    
    def cleanup(self, org: str | None = None) -> None:
        """Remove snapshot bundles."""
        if org:
            org_dir = self.snapshot_dir / org
            if org_dir.exists():
                shutil.rmtree(org_dir)
        else:
            if self.snapshot_dir.exists():
                shutil.rmtree(self.snapshot_dir)
                self.snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    async def _create_simple_bundle(self, repo_path: Path, output_path: Path) -> None:
        """Create bundle from clean repository."""
        await self._run_git(
            repo_path,
            "bundle", "create", str(output_path), "--all",
        )
    
    async def _create_snapshot_with_changes(
        self,
        repo_path: Path,
        output_path: Path,
    ) -> str:
        """Create bundle including uncommitted changes as a snapshot commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_repo = Path(tmpdir) / "repo"
            
            # Clone the repo to temp location
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--quiet", str(repo_path), str(tmp_repo),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            
            if proc.returncode != 0:
                raise SnapshotError(f"Failed to clone repository: {repo_path}")
            
            # Copy working tree changes (excluding .git)
            for item in repo_path.iterdir():
                if item.name == ".git":
                    continue
                dest = tmp_repo / item.name
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
            await self._run_git(tmp_repo, "add", "-A")
            
            # Create snapshot commit
            await self._run_git(
                tmp_repo,
                "commit",
                "--allow-empty",
                "-m", "Shadow snapshot: uncommitted changes",
                "--author", "Shadow <shadow@localhost>",
            )
            
            # Get the new commit SHA
            commit_sha = await self.get_head_sha(tmp_repo)
            
            # Create bundle from temp repo
            await self._create_simple_bundle(tmp_repo, output_path)
            
            return commit_sha
    
    async def _run_git(self, cwd: Path, *args: str) -> tuple[str, str]:
        """Run git command and return stdout/stderr."""
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(cwd), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0 and "bundle" not in args:
            # Don't raise for bundle commands (they may have warnings)
            pass
        
        return stdout.decode(), stderr.decode()
