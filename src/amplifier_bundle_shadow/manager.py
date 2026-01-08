"""Shadow environment manager."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .environment import ShadowEnvironment
from .models import RepoSpec, ShadowStatus
from .repos import RepoManager
from .sandbox import get_sandbox_backend


# Base gitconfig template (repo-specific URL rewrites added dynamically)
GITCONFIG_BASE = """
[user]
    name = Shadow Environment
    email = shadow@localhost

[init]
    defaultBranch = main

[safe]
    directory = *

[advice]
    detachedHead = false
"""


class ShadowManager:
    """
    Manages the lifecycle of shadow environments.
    
    This class handles:
    - Creating new shadow environments with mock repos
    - Tracking active environments
    - Destroying environments and cleaning up
    """
    
    def __init__(self, shadow_home: Path | None = None):
        """
        Initialize the shadow manager.
        
        Args:
            shadow_home: Base directory for shadow data. Defaults to ~/.shadow
        """
        self.shadow_home = shadow_home or Path.home() / ".shadow"
        self.staging_dir = self.shadow_home / "staging"
        self.environments_dir = self.shadow_home / "environments"
        
        # Ensure directories exist
        self.shadow_home.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.environments_dir.mkdir(parents=True, exist_ok=True)
        
        # Repository manager for cloning/caching
        self.repo_manager = RepoManager(self.staging_dir)
        
        # In-memory cache of active environments
        self._environments: dict[str, ShadowEnvironment] = {}
    
    async def create(
        self,
        local_sources: list[str] | None = None,
        name: str | None = None,
        mode: str = "auto",
        network_enabled: bool = True,
    ) -> ShadowEnvironment:
        """
        Create a new shadow environment with local source overrides.
        
        Args:
            local_sources: List of local source mappings (e.g., '~/repos/amplifier-core:microsoft/amplifier-core')
            name: Optional name for the environment. Auto-generated if not provided.
            mode: Sandbox mode - "auto", "bubblewrap", "seatbelt", or "direct"
            network_enabled: Whether to allow network access
            
        Returns:
            A new ShadowEnvironment ready for use
            
        Example:
            # Create shadow with local amplifier-core, other deps fetch from real GitHub
            await manager.create(
                local_sources=['~/repos/amplifier-core:microsoft/amplifier-core'],
                name='test-my-changes',
            )
            
            # Then inside the shadow:
            # uv tool install git+https://github.com/microsoft/amplifier
            # -> amplifier fetches from real GitHub
            # -> amplifier-core (dependency) uses your local snapshot
        """
        local_sources = local_sources or []
        
        # Generate shadow ID
        shadow_id = name or f"shadow-{uuid.uuid4().hex[:6]}"
        shadow_dir = self.environments_dir / shadow_id
        
        # Check if already exists
        if shadow_dir.exists():
            raise ValueError(f"Shadow environment already exists: {shadow_id}")
        
        # Create directory structure
        shadow_dir.mkdir(parents=True)
        workspace_dir = shadow_dir / "workspace"
        workspace_dir.mkdir()
        home_dir = shadow_dir / "home"
        home_dir.mkdir()
        amplifier_home = home_dir / ".amplifier"
        amplifier_home.mkdir()
        repos_dir = shadow_dir / "repos" / "github.com"
        repos_dir.mkdir(parents=True)
        
        # Parse local source specs
        repo_specs = [RepoSpec.parse_local(ls) for ls in local_sources]
        
        # Create bare repos from local sources (snapshots working directory state)
        for spec in repo_specs:
            await self.repo_manager.create_bare_from_local(spec, repos_dir)
        
        # Write configuration files
        self._write_gitconfig(shadow_dir, repo_specs)
        self._write_metadata(shadow_dir, shadow_id, repo_specs, mode)
        
        # Get sandbox backend
        backend = get_sandbox_backend(
            shadow_dir=shadow_dir,
            repos_dir=repos_dir,
            mode=mode,
            network_enabled=network_enabled,
        )
        
        # Create environment object
        env = ShadowEnvironment(
            shadow_id=shadow_id,
            repos=repo_specs,
            shadow_dir=shadow_dir,
            backend=backend,
            created_at=datetime.now(),
            status=ShadowStatus.READY,
        )
        
        # Take baseline snapshot for diff tracking
        env.snapshot_baseline()
        
        # Cache it
        self._environments[shadow_id] = env
        
        return env
    
    def get(self, shadow_id: str) -> ShadowEnvironment | None:
        """Get an active shadow environment by ID."""
        # Check in-memory cache first
        if shadow_id in self._environments:
            return self._environments[shadow_id]
        
        # Try to load from disk
        return self._load_from_disk(shadow_id)
    
    def list_environments(self) -> list[ShadowEnvironment]:
        """List all shadow environments (active and on-disk)."""
        environments = []
        
        # Load all from disk
        if self.environments_dir.exists():
            for shadow_dir in self.environments_dir.iterdir():
                if shadow_dir.is_dir():
                    env = self._load_from_disk(shadow_dir.name)
                    if env:
                        environments.append(env)
        
        return environments
    
    def destroy(self, shadow_id: str, force: bool = False) -> None:
        """
        Destroy a shadow environment.
        
        Args:
            shadow_id: ID of the environment to destroy
            force: If True, destroy even if there are errors
        """
        shadow_dir = self.environments_dir / shadow_id
        
        if not shadow_dir.exists():
            if force:
                return
            raise ValueError(f"Shadow environment not found: {shadow_id}")
        
        # Remove from cache
        if shadow_id in self._environments:
            self._environments[shadow_id].status = ShadowStatus.DESTROYED
            del self._environments[shadow_id]
        
        # Remove directory
        shutil.rmtree(shadow_dir)
    
    def destroy_all(self, force: bool = False) -> int:
        """
        Destroy all shadow environments.
        
        Args:
            force: If True, continue on errors
            
        Returns:
            Number of environments destroyed
        """
        count = 0
        
        if self.environments_dir.exists():
            for shadow_dir in list(self.environments_dir.iterdir()):
                if shadow_dir.is_dir():
                    try:
                        self.destroy(shadow_dir.name, force=force)
                        count += 1
                    except Exception:
                        if not force:
                            raise
        
        return count
    
    def _write_gitconfig(self, shadow_dir: Path, local_repos: list[RepoSpec]) -> None:
        """
        Write the .gitconfig file for the shadow environment.
        
        Only rewrites URLs for repos that have local sources staged.
        Other repos fetch from real GitHub.
        
        Note: The sandbox mounts repos/github.com to /repos, so paths inside
        the sandbox are /repos/{org}/{name}.git (no github.com in path).
        """
        gitconfig_path = shadow_dir / "home" / ".gitconfig"
        
        # Start with base config
        gitconfig_lines = [GITCONFIG_BASE.strip()]
        
        # Add URL rewriting ONLY for local source repos
        # Path inside sandbox: /repos/{org}/{name}.git (sandbox mounts repos/github.com -> /repos)
        for spec in local_repos:
            sandbox_bare_path = f"/repos/{spec.org}/{spec.name}.git"
            gitconfig_lines.append(f'''
[url "file://{sandbox_bare_path}"]
    insteadOf = https://github.com/{spec.org}/{spec.name}
    insteadOf = https://github.com/{spec.org}/{spec.name}.git
    insteadOf = git@github.com:{spec.org}/{spec.name}
    insteadOf = git@github.com:{spec.org}/{spec.name}.git
    insteadOf = ssh://git@github.com/{spec.org}/{spec.name}
    insteadOf = git+https://github.com/{spec.org}/{spec.name}
''')
        
        gitconfig_path.write_text("\n".join(gitconfig_lines))
    
    def _write_metadata(
        self,
        shadow_dir: Path,
        shadow_id: str,
        repos: list[RepoSpec],
        mode: str,
    ) -> None:
        """Write metadata file for the shadow environment."""
        # Store both simple names and local source info
        local_sources = []
        for r in repos:
            source_info = {"repo": r.full_name}
            if r.local_path:
                source_info["local_path"] = str(r.local_path)
            local_sources.append(source_info)
        
        metadata = {
            "shadow_id": shadow_id,
            "local_sources": local_sources,
            "mode": mode,
            "created_at": datetime.now().isoformat(),
        }
        metadata_path = shadow_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))
    
    def _load_from_disk(self, shadow_id: str) -> ShadowEnvironment | None:
        """Load a shadow environment from disk."""
        shadow_dir = self.environments_dir / shadow_id
        
        if not shadow_dir.exists():
            return None
        
        # Read metadata
        metadata_path = shadow_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        
        try:
            metadata = json.loads(metadata_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        
        # Parse repos from local_sources format
        repo_specs = []
        for source_info in metadata.get("local_sources", []):
            if isinstance(source_info, dict):
                spec = RepoSpec.parse(source_info["repo"])
                if "local_path" in source_info:
                    spec.local_path = Path(source_info["local_path"])
                repo_specs.append(spec)
            elif isinstance(source_info, str):
                # Legacy format fallback
                repo_specs.append(RepoSpec.parse(source_info))
        
        # Get backend
        repos_dir = shadow_dir / "repos" / "github.com"
        try:
            backend = get_sandbox_backend(
                shadow_dir=shadow_dir,
                repos_dir=repos_dir,
                mode=metadata.get("mode", "auto"),
            )
        except RuntimeError:
            return None
        
        # Create environment object
        created_at_str = metadata.get("created_at", datetime.now().isoformat())
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            created_at = datetime.now()
        
        env = ShadowEnvironment(
            shadow_id=shadow_id,
            repos=repo_specs,
            shadow_dir=shadow_dir,
            backend=backend,
            created_at=created_at,
            status=ShadowStatus.READY,
        )
        
        # Cache it
        self._environments[shadow_id] = env
        
        return env
