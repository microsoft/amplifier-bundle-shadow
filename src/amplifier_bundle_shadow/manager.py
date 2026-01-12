"""Shadow environment manager."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .container import ContainerRuntime, Mount
from .environment import ShadowEnvironment
from .gitea import GiteaClient
from .models import RepoSpec, ShadowStatus
from .snapshot import SnapshotManager
from .builder import ImageBuilder, DEFAULT_IMAGE_NAME

__all__ = ["ShadowManager", "DEFAULT_IMAGE"]

# Default shadow container image (local build)
DEFAULT_IMAGE = DEFAULT_IMAGE_NAME

# Environment variables always passed to shadow containers
# UV_NO_GITHUB_FAST_PATH: Force uv to use git instead of GitHub API fast path.
# This ensures uv respects our .gitconfig URL rewriting for local sources.
DEFAULT_ENV_VARS = {
    "UV_NO_GITHUB_FAST_PATH": "1",
}


class ShadowManager:
    """
    Manages the lifecycle of shadow environments.

    Shadow environments use containers with embedded Gitea for complete
    git isolation. Each shadow has its own container with:
    - Gitea server on localhost:3000
    - Local source snapshots pushed as repos
    - Git URL rewriting to redirect GitHub URLs to local Gitea
    """

    def __init__(self, shadow_home: Path | None = None) -> None:
        """
        Initialize the shadow manager.

        Args:
            shadow_home: Base directory for shadow data. Defaults to ~/.shadow
        """
        self.shadow_home = shadow_home or Path.home() / ".shadow"
        self.environments_dir = self.shadow_home / "environments"

        # Ensure directories exist
        self.shadow_home.mkdir(parents=True, exist_ok=True)
        self.environments_dir.mkdir(parents=True, exist_ok=True)

        # Container runtime
        self.runtime = ContainerRuntime()

        # In-memory cache of active environments
        self._environments: dict[str, ShadowEnvironment] = {}

    async def create(
        self,
        local_sources: list[str] | None = None,
        name: str | None = None,
        image: str = DEFAULT_IMAGE,
        env: dict[str, str] | None = None,
    ) -> ShadowEnvironment:
        """
        Create a new shadow environment.

        Args:
            local_sources: List of local source mappings (e.g., '~/repos/amplifier-core:microsoft/amplifier-core')
            name: Optional name for the environment. Auto-generated if not provided.
            image: Container image to use (defaults to ghcr.io/microsoft/amplifier-shadow:latest)
            env: Environment variables to pass to the container (e.g., API keys)

        Returns:
            A new ShadowEnvironment ready for use
        """
        local_sources = local_sources or []

        # Generate shadow ID
        shadow_id = name or f"shadow-{uuid.uuid4().hex[:8]}"
        container_name = f"shadow-{shadow_id}"
        shadow_dir = self.environments_dir / shadow_id

        # Check if already exists
        if shadow_dir.exists():
            raise ValueError(f"Shadow environment already exists: {shadow_id}")

        # Check if container already running
        if await self.runtime.exists(container_name):
            raise ValueError(f"Container already exists: {container_name}")

        # Create directory structure
        shadow_dir.mkdir(parents=True)
        workspace_dir = shadow_dir / "workspace"
        workspace_dir.mkdir()
        snapshots_dir = shadow_dir / "snapshots"
        snapshots_dir.mkdir()

        # Parse local source specs
        repo_specs = [RepoSpec.parse_local(ls) for ls in local_sources]

        # Create snapshots of local repositories and capture commit SHAs
        snapshot_mgr = SnapshotManager(snapshots_dir)
        for spec in repo_specs:
            if spec.local_path:
                snapshot_result = await snapshot_mgr.create_snapshot(
                    local_path=spec.local_path,
                    org=spec.org,
                    name=spec.name,
                )
                # Store the commit SHA for observability
                spec.snapshot_commit = snapshot_result.commit_sha

        # Ensure image exists (auto-build if needed)
        builder = ImageBuilder(self.runtime)
        try:
            image = await builder.ensure_image(image)
        except FileNotFoundError as e:
            shutil.rmtree(shadow_dir)
            raise RuntimeError(
                f"Cannot build image: {e}. "
                "Run 'amplifier-shadow build' manually or specify --image."
            ) from e
        except Exception as e:
            shutil.rmtree(shadow_dir)
            raise RuntimeError(f"Failed to build image: {e}") from e

        # Start container
        mounts = [
            Mount(snapshots_dir, "/snapshots", readonly=True),
            Mount(workspace_dir, "/workspace", readonly=False),
        ]

        # Merge default env vars with user-provided ones (user overrides defaults)
        container_env = {**DEFAULT_ENV_VARS, **(env or {})}

        try:
            await self.runtime.run(
                image=image,
                name=container_name,
                mounts=mounts,
                env=container_env,
                detach=True,
            )
        except Exception as e:
            # Cleanup on failure
            shutil.rmtree(shadow_dir)
            raise RuntimeError(f"Failed to start container: {e}") from e

        # Wait for Gitea to be ready and set up repos
        try:
            gitea = GiteaClient(
                runtime=self.runtime,
                container=container_name,
            )

            await gitea.wait_ready(timeout=60.0)

            # Push snapshots to Gitea
            for spec in repo_specs:
                bundle_path = f"/snapshots/{spec.org}/{spec.name}.bundle"
                await gitea.setup_repo_from_bundle(
                    org=spec.org,
                    name=spec.name,
                    bundle_container_path=bundle_path,
                )

            # Configure git URL rewriting
            await self._configure_git_rewriting(container_name, repo_specs)

        except Exception as e:
            # Cleanup on failure
            await self.runtime.remove(container_name, force=True)
            shutil.rmtree(shadow_dir)
            raise RuntimeError(f"Failed to setup shadow environment: {e}") from e

        # Write metadata (include env_vars for observability)
        self._write_metadata(shadow_dir, shadow_id, repo_specs, image, container_env)

        # Create environment object
        shadow_env = ShadowEnvironment(
            shadow_id=shadow_id,
            container_name=container_name,
            repos=repo_specs,
            shadow_dir=shadow_dir,
            runtime=self.runtime,
            created_at=datetime.now(),
            status=ShadowStatus.READY,
            env_vars=container_env,
        )

        # Take baseline snapshot for diff tracking
        shadow_env.snapshot_baseline()

        # Cache it
        self._environments[shadow_id] = shadow_env

        return shadow_env

    def get(self, shadow_id: str) -> ShadowEnvironment | None:
        """Get an active shadow environment by ID."""
        # Check in-memory cache first
        if shadow_id in self._environments:
            return self._environments[shadow_id]

        # Try to load from disk
        return self._load_from_disk(shadow_id)

    async def add_source(
        self,
        shadow_id: str,
        local_sources: list[str],
    ) -> ShadowEnvironment:
        """Add local sources to an existing shadow environment.

        This allows you to add more local repos to a running shadow without
        destroying and recreating it.

        Args:
            shadow_id: ID of the existing shadow environment
            local_sources: List of "path:org/repo" strings to add

        Returns:
            Updated ShadowEnvironment

        Raises:
            ValueError: If shadow doesn't exist or isn't running
        """
        # Get existing environment
        env = self.get(shadow_id)
        if env is None:
            raise ValueError(f"Shadow environment not found: {shadow_id}")

        # Parse new source specs
        new_specs = [RepoSpec.parse(src) for src in local_sources]

        # Check for duplicates
        existing_repos = {(r.org, r.name) for r in env.repos}
        for spec in new_specs:
            if (spec.org, spec.name) in existing_repos:
                raise ValueError(
                    f"Source {spec.org}/{spec.name} already exists in shadow"
                )

        # Create snapshots for new sources
        snapshots_dir = env.shadow_dir / "snapshots"
        snapshots_dir.mkdir(exist_ok=True)

        for spec in new_specs:
            bundle_path = snapshots_dir / f"{spec.org}_{spec.name}.bundle"
            self.snapshot_manager.create_snapshot(spec.local_path, bundle_path)

        # Copy bundles into container and push to Gitea
        gitea = GiteaClient(self.runtime, env.container_name)

        for spec in new_specs:
            bundle_path = snapshots_dir / f"{spec.org}_{spec.name}.bundle"
            container_bundle_path = f"/tmp/{spec.org}_{spec.name}.bundle"

            # Copy bundle into container
            await self.runtime.copy_to(
                env.container_name,
                str(bundle_path),
                container_bundle_path,
            )

            # Push to Gitea
            await gitea.setup_repo_from_bundle(
                spec.org,
                spec.name,
                container_bundle_path,
            )

        # Add git URL rewriting for new sources
        await self._configure_git_rewriting(env.container_name, new_specs)

        # Clear uv cache so new sources are picked up on next install
        await self.runtime.exec(
            env.container_name,
            "rm -rf ~/.cache/uv/git-v0 2>/dev/null || true",
        )

        # Update environment with new repos
        env.repos.extend(new_specs)

        # Update metadata on disk
        self._write_metadata(
            env.shadow_dir,
            shadow_id,
            env.repos,
            image=None,  # Keep existing image
        )

        return env

    def list_environments(self) -> list[ShadowEnvironment]:
        """List all shadow environments."""
        environments = []

        if self.environments_dir.exists():
            for shadow_dir in self.environments_dir.iterdir():
                if shadow_dir.is_dir():
                    env = self._load_from_disk(shadow_dir.name)
                    if env:
                        environments.append(env)

        return environments

    async def destroy(self, shadow_id: str, force: bool = False) -> None:
        """
        Destroy a shadow environment.

        Args:
            shadow_id: ID of the environment to destroy
            force: If True, destroy even if there are errors
        """
        shadow_dir = self.environments_dir / shadow_id
        container_name = f"shadow-{shadow_id}"

        # Stop and remove container
        try:
            await self.runtime.remove(container_name, force=True)
        except Exception:
            if not force:
                raise

        # Remove from cache
        if shadow_id in self._environments:
            self._environments[shadow_id].status = ShadowStatus.DESTROYED
            del self._environments[shadow_id]

        # Remove directory
        if shadow_dir.exists():
            shutil.rmtree(shadow_dir)

    async def destroy_all(self, force: bool = False) -> int:
        """
        Destroy all shadow environments.

        Returns:
            Number of environments destroyed
        """
        count = 0

        if self.environments_dir.exists():
            for shadow_dir in list(self.environments_dir.iterdir()):
                if shadow_dir.is_dir():
                    try:
                        await self.destroy(shadow_dir.name, force=force)
                        count += 1
                    except Exception:
                        if not force:
                            raise

        return count

    async def _configure_git_rewriting(
        self,
        container: str,
        local_repos: list[RepoSpec],
    ) -> None:
        """Configure git to rewrite GitHub URLs to local Gitea."""
        # Base git config
        commands = [
            'git config --global user.email "shadow@localhost"',
            'git config --global user.name "Shadow"',
            "git config --global init.defaultBranch main",
            "git config --global advice.detachedHead false",
        ]

        # Add URL rewriting for each local repo
        for spec in local_repos:
            gitea_url = (
                f"http://shadow:shadow@localhost:3000/{spec.org}/{spec.name}.git"
            )

            # Rewrite various GitHub URL formats to local Gitea
            # CRITICAL: git insteadOf uses PREFIX matching!
            # The bare URL pattern (without suffix) is needed because uv strips @ref
            # before calling git. This has collision risk: if "amplifier" is local,
            # it would also match "amplifier-profiles". We accept this tradeoff
            # because shadow environments are for testing specific repos, not general use.
            # Patterns with boundary markers (.git, /, @) are safer but don't catch all cases.
            patterns = [
                # Bare URL (highest risk of prefix collision, but needed for uv)
                # uv strips @ref suffix before calling git, leaving bare URL
                f"https://github.com/{spec.org}/{spec.name}",
                # HTTPS variants with boundaries (most common for uv/pip/cargo)
                f"https://github.com/{spec.org}/{spec.name}.git",
                f"https://github.com/{spec.org}/{spec.name}.git/",
                f"https://github.com/{spec.org}/{spec.name}/",  # Trailing slash = boundary
                f"https://github.com/{spec.org}/{spec.name}@",  # @ref syntax = boundary
                # SSH variants with boundaries
                f"git@github.com:{spec.org}/{spec.name}.git",
                f"git@github.com:{spec.org}/{spec.name}/",
                f"git@github.com:{spec.org}/{spec.name}@",
                f"ssh://git@github.com/{spec.org}/{spec.name}.git",
                f"ssh://git@github.com/{spec.org}/{spec.name}/",
                f"ssh://git@github.com/{spec.org}/{spec.name}@",
                # git+ prefix variants with boundaries (pyproject.toml dependencies)
                f"git+https://github.com/{spec.org}/{spec.name}.git",
                f"git+https://github.com/{spec.org}/{spec.name}@",  # git+https://...@main
                f"git+ssh://git@github.com/{spec.org}/{spec.name}.git",
                f"git+ssh://git@github.com/{spec.org}/{spec.name}@",
            ]

            for pattern in patterns:
                # Use --add to allow multiple insteadOf values for the same URL
                commands.append(
                    f'git config --global --add url."{gitea_url}".insteadOf "{pattern}"'
                )

        # Clear uv's git cache to ensure fresh resolution with new URL rules
        # This prevents stale cached URLs from bypassing insteadOf rewriting
        commands.append("rm -rf /home/amplifier/.cache/uv/git-v0 2>/dev/null || true")

        # Execute all commands
        for cmd in commands:
            await self.runtime.exec(container, cmd)

        # Verify the configuration was applied correctly
        await self._verify_git_rewriting(container, local_repos)

    async def _verify_git_rewriting(
        self,
        container: str,
        local_repos: list[RepoSpec],
    ) -> None:
        """Verify git URL rewriting is configured correctly."""
        # Check that git config has our insteadOf rules
        code, stdout, stderr = await self.runtime.exec(
            container, 'git config --global --get-regexp "url.*insteadOf"'
        )

        if code != 0:
            raise RuntimeError(
                f"Git URL rewriting configuration failed. "
                f"No insteadOf rules found in git config. stderr: {stderr}"
            )

        # Verify each repo has URL rewriting configured
        for spec in local_repos:
            expected_pattern = f"https://github.com/{spec.org}/{spec.name}"
            if expected_pattern not in stdout:
                raise RuntimeError(
                    f"Git URL rewriting not configured for {spec.full_name}. "
                    f"Expected pattern '{expected_pattern}' not found in git config."
                )

    def _write_metadata(
        self,
        shadow_dir: Path,
        shadow_id: str,
        repos: list[RepoSpec],
        image: str | None,
        env_vars: dict[str, str] | None = None,
    ) -> None:
        """Write metadata file for the shadow environment."""
        local_sources = []
        for r in repos:
            source_info: dict[str, str | None] = {"repo": r.full_name}
            if r.local_path:
                source_info["local_path"] = str(r.local_path)
            if r.snapshot_commit:
                source_info["snapshot_commit"] = r.snapshot_commit
            local_sources.append(source_info)

        metadata: dict[str, object] = {
            "shadow_id": shadow_id,
            "container_name": f"shadow-{shadow_id}",
            "local_sources": local_sources,
            "created_at": datetime.now().isoformat(),
        }
        if image:
            metadata["image"] = image
        if env_vars:
            # Store env var names only (not values) for observability
            metadata["env_vars_passed"] = list(env_vars.keys())

        metadata_path = shadow_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

    def _load_from_disk(self, shadow_id: str) -> ShadowEnvironment | None:
        """Load a shadow environment from disk."""
        shadow_dir = self.environments_dir / shadow_id

        if not shadow_dir.exists():
            return None

        metadata_path = shadow_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        try:
            metadata = json.loads(metadata_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        # Parse repos
        repo_specs = []
        for source_info in metadata.get("local_sources", []):
            if isinstance(source_info, dict):
                spec = RepoSpec.parse(source_info["repo"])
                if "local_path" in source_info:
                    spec.local_path = Path(source_info["local_path"])
                repo_specs.append(spec)
            elif isinstance(source_info, str):
                repo_specs.append(RepoSpec.parse(source_info))

        # Parse created_at
        created_at_str = metadata.get("created_at", datetime.now().isoformat())
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            created_at = datetime.now()

        container_name = metadata.get("container_name", f"shadow-{shadow_id}")

        env = ShadowEnvironment(
            shadow_id=shadow_id,
            container_name=container_name,
            repos=repo_specs,
            shadow_dir=shadow_dir,
            runtime=self.runtime,
            created_at=created_at,
            status=ShadowStatus.READY,
        )

        # Cache it
        self._environments[shadow_id] = env

        return env
