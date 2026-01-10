# Shadow Environment: Container + Gitea Architecture

## Overview

Shadow environments provide isolated sandboxes for testing local changes to Amplifier ecosystem packages. This architecture uses containers with an embedded Gitea server to provide complete git isolation.

```
┌─────────────────────────────────────────────────────────────┐
│                    Shadow Container                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                      Gitea                            │   │
│  │              http://localhost:3000                    │   │
│  │                                                       │   │
│  │  Repos (pushed from host snapshots):                  │   │
│  │  • microsoft/amplifier-core                           │   │
│  │  • microsoft/amplifier-foundation                     │   │
│  │  • microsoft/amplifier-app-cli                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                           ↑                                  │
│                    git operations                            │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Workspace                          │   │
│  │                                                       │   │
│  │  • All git URLs rewritten to localhost:3000           │   │
│  │  • pip/uv/git all work transparently                  │   │
│  │  • Full Python/Node/etc. environment                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Mounts:                                                     │
│  • /workspace ← host workspace (read-write)                  │
│  • /snapshots ← local repo snapshots (read-only)             │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. One Gitea Per Container

Each shadow environment runs its own Gitea instance inside its container.

**Why not shared Gitea?**
- Complete isolation between shadow environments
- No organization/namespace management needed
- No port conflicts (each container has its own `localhost`)
- Simpler mental model - shadow is self-contained
- Easy cleanup - delete container, everything goes away

### 2. Git URL Rewriting

All GitHub URLs are rewritten to the local Gitea:

```bash
# Inside container's .gitconfig
[url "http://localhost:3000/"]
    insteadOf = https://github.com/
    insteadOf = git@github.com:
    insteadOf = ssh://git@github.com/
    insteadOf = git+https://github.com/
```

This means:
- `git clone https://github.com/microsoft/amplifier-core` → clones from local Gitea
- `pip install git+https://github.com/microsoft/amplifier-core` → uses local Gitea
- `uv pip install git+https://github.com/microsoft/amplifier-core` → uses local Gitea (HTTP works!)

### 3. Snapshot Strategy

Local repositories are snapshotted and pushed to Gitea:

```
Host: ~/repos/amplifier-core (with uncommitted changes)
  ↓
  git bundle create (includes working tree state)
  + fetch all remote refs (for lock file resolution)
  ↓
Container: Gitea creates repo, unbundle pushed
  + _upstream_* branches preserve remote refs
  ↓
Ready: http://localhost:3000/microsoft/amplifier-core
```

**Note**: The snapshot also fetches and preserves remote tracking refs so that commit hashes pinned in `uv.lock` or `package-lock.json` resolve correctly.

### 4. Environment Variable Passthrough

The CLI automatically passes API keys into the container:

```bash
# Auto-passed: ANTHROPIC_API_KEY, OPENAI_API_KEY, AZURE_OPENAI_*, GEMINI_API_KEY, etc.
amplifier-shadow create --name test --pass-api-keys

# Manual env vars
amplifier-shadow create --name test --env MY_VAR=value --env-file .env
```

## Container Image

### Base: `amplifier-shadow`

```dockerfile
FROM python:3.12-slim

# Gitea - single binary, minimal footprint
RUN curl -sL https://dl.gitea.io/gitea/1.21/gitea-1.21-linux-arm64 -o /usr/local/bin/gitea \
    && chmod +x /usr/local/bin/gitea

# Git and essential tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv for fast Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Gitea data directory
RUN mkdir -p /var/lib/gitea /etc/gitea
COPY gitea-app.ini /etc/gitea/app.ini

# Entrypoint that starts Gitea and waits for ready
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/entrypoint.sh"]
```

### Gitea Configuration (`gitea-app.ini`)

Minimal config for local-only use:

```ini
[server]
HTTP_PORT = 3000
ROOT_URL = http://localhost:3000/
DISABLE_SSH = true
OFFLINE_MODE = true

[database]
DB_TYPE = sqlite3
PATH = /var/lib/gitea/gitea.db

[security]
INSTALL_LOCK = true
SECRET_KEY = shadow-local-only
INTERNAL_TOKEN = shadow-local-only

[service]
DISABLE_REGISTRATION = false
REQUIRE_SIGNIN_VIEW = false
DEFAULT_ALLOW_CREATE_ORGANIZATION = true

[repository]
DEFAULT_PRIVATE = false

[api]
ENABLE_SWAGGER = false

[log]
MODE = console
LEVEL = Warn
```

### Entrypoint Script

```bash
#!/bin/bash
set -e

# Start Gitea in background
gitea web --config /etc/gitea/app.ini &
GITEA_PID=$!

# Wait for Gitea to be ready
echo "Waiting for Gitea..."
for i in {1..30}; do
    if curl -s http://localhost:3000/api/v1/version > /dev/null 2>&1; then
        echo "Gitea ready"
        break
    fi
    sleep 0.5
done

# Create admin user for API access (if not exists)
gitea admin user create --admin --username shadow --password shadow --email shadow@localhost 2>/dev/null || true

# Execute the requested command (or shell)
exec "$@"
```

## CLI Interface

### Commands

```bash
# Create shadow environment with local sources
# Format: --local /path/to/repo:org/name
amplifier-shadow create \
    --local ~/repos/amplifier-core:microsoft/amplifier-core \
    --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \
    --name my-test

# List environments
amplifier-shadow list

# Execute command in shadow
amplifier-shadow exec my-test "uv pip install amplifier"
amplifier-shadow exec my-test "amplifier run --mode single 'hello'"

# Interactive shell
amplifier-shadow shell my-test

# Status
amplifier-shadow status my-test

# Show changed files since creation
amplifier-shadow diff my-test

# Copy file from container to host
amplifier-shadow extract my-test /workspace/file.py ./file.py

# Copy file from host to container
amplifier-shadow inject my-test ./file.py /workspace/file.py

# Destroy single environment
amplifier-shadow destroy my-test

# Destroy all environments
amplifier-shadow destroy-all

# Build container image locally (auto-runs if image missing)
amplifier-shadow build
```

### Create Flow

```python
async def create(
    name: str,
    local_sources: list[str],  # "/path/to/repo:org/name" format
    image: str = "amplifier-shadow:local",  # Auto-built if missing
) -> ShadowEnvironment:
    """Create a new shadow environment."""
    
    # 1. Parse local source mappings
    repo_specs = [RepoSpec.parse(s) for s in local_sources]
    
    # 2. Create snapshots of local repos (as git bundles)
    snapshot_dir = Path(f"~/.shadow/snapshots/{name}")
    for spec in repo_specs:
        await create_snapshot(spec.local_path, snapshot_dir / f"{spec.org}/{spec.repo}.bundle")
    
    # 3. Start container
    container_id = await start_container(
        image=image,
        name=f"shadow-{name}",
        mounts=[
            f"{snapshot_dir}:/snapshots:ro",
            f"{workspace_dir}:/workspace:rw",
        ],
    )
    
    # 4. Wait for Gitea ready
    await wait_for_gitea(container_id)
    
    # 5. Push snapshots to Gitea
    for spec in repo_specs:
        await push_to_gitea(container_id, spec, snapshot_dir)
    
    # 6. Configure git URL rewriting
    await configure_git_rewriting(container_id, repo_specs)
    
    return ShadowEnvironment(name=name, container_id=container_id)
```

## Implementation Plan

> **Note**: This section is historical - the implementation is complete. The actual code structure is:
> ```
> src/amplifier_bundle_shadow/
> ├── __init__.py
> ├── __main__.py
> ├── builder.py         # Image building
> ├── cli.py             # Click CLI
> ├── container.py       # Docker/Podman operations
> ├── environment.py     # Environment state tracking
> ├── gitea.py           # Gitea API client
> ├── manager.py         # Main orchestration
> ├── models.py          # RepoSpec, ShadowEnvironment
> └── snapshot.py        # Git bundle creation
> ```
> The pseudo-code below was the original design; see the actual implementation for current behavior.

### Phase 1: Core Infrastructure

**Files to create:**

```
src/amplifier_bundle_shadow/
├── __init__.py
├── cli.py                 # Click CLI (simplified)
├── models.py              # RepoSpec, ShadowEnvironment
├── manager.py             # Main orchestration
├── container.py           # Docker/Podman operations
├── gitea.py               # Gitea API client
├── snapshot.py            # Git bundle creation
└── tool.py                # Amplifier tool interface
```

**Files to delete (entire sandbox/ directory):**

```
src/amplifier_bundle_shadow/sandbox/
├── base.py      # DELETE
├── direct.py    # DELETE
├── factory.py   # DELETE
├── linux.py     # DELETE
└── macos.py     # DELETE
```

### Phase 2: Container Management

`container.py`:

```python
"""Container runtime abstraction (Docker/Podman)."""

import asyncio
import shutil
from pathlib import Path


class ContainerRuntime:
    """Abstraction over Docker/Podman."""
    
    def __init__(self):
        # Prefer podman, fall back to docker
        self.runtime = self._detect_runtime()
    
    def _detect_runtime(self) -> str:
        if shutil.which("podman"):
            return "podman"
        if shutil.which("docker"):
            return "docker"
        raise RuntimeError("No container runtime found (need docker or podman)")
    
    async def run(
        self,
        image: str,
        name: str,
        mounts: list[tuple[Path, str, str]],  # (host, container, mode)
        command: str | None = None,
        detach: bool = True,
    ) -> str:
        """Start a container, return container ID."""
        args = [self.runtime, "run"]
        
        if detach:
            args.append("-d")
        
        args.extend(["--name", name])
        
        for host_path, container_path, mode in mounts:
            args.extend(["-v", f"{host_path}:{container_path}:{mode}"])
        
        args.append(image)
        
        if command:
            args.extend(["sh", "-c", command])
        
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"Container start failed: {stderr.decode()}")
        
        return stdout.decode().strip()
    
    async def exec(self, container: str, command: str) -> tuple[int, str, str]:
        """Execute command in container."""
        proc = await asyncio.create_subprocess_exec(
            self.runtime, "exec", container, "sh", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()
    
    async def stop(self, container: str) -> None:
        """Stop and remove container."""
        await asyncio.create_subprocess_exec(
            self.runtime, "rm", "-f", container,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
```

### Phase 3: Gitea Integration

`gitea.py`:

```python
"""Gitea API client for shadow environments."""

import httpx
from dataclasses import dataclass


@dataclass
class GiteaClient:
    """Simple Gitea API client."""
    
    base_url: str = "http://localhost:3000"
    username: str = "shadow"
    password: str = "shadow"
    
    @property
    def _auth(self) -> tuple[str, str]:
        return (self.username, self.password)
    
    async def wait_ready(self, timeout: float = 30.0) -> None:
        """Wait for Gitea to be ready."""
        import asyncio
        
        async with httpx.AsyncClient() as client:
            for _ in range(int(timeout * 2)):
                try:
                    resp = await client.get(f"{self.base_url}/api/v1/version")
                    if resp.status_code == 200:
                        return
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.5)
        
        raise TimeoutError("Gitea did not become ready")
    
    async def create_repo(self, org: str, name: str) -> dict:
        """Create a repository."""
        async with httpx.AsyncClient(auth=self._auth) as client:
            # Ensure org exists
            await client.post(
                f"{self.base_url}/api/v1/orgs",
                json={"username": org},
            )
            
            # Create repo under org
            resp = await client.post(
                f"{self.base_url}/api/v1/orgs/{org}/repos",
                json={
                    "name": name,
                    "private": False,
                    "auto_init": False,
                },
            )
            return resp.json()
    
    async def push_bundle(self, org: str, name: str, bundle_path: str) -> None:
        """Push a git bundle to a repo."""
        # This is done via git commands, not API
        # The bundle is unbundled and pushed to the Gitea repo
        pass
```

### Phase 4: Snapshot Creation

`snapshot.py`:

```python
"""Git snapshot creation for local repositories."""

import asyncio
from pathlib import Path
from dataclasses import dataclass


@dataclass
class RepoSpec:
    """Repository specification."""
    org: str
    name: str
    local_path: Path
    
    @classmethod
    def parse(cls, mapping: str) -> "RepoSpec":
        """Parse 'org/name:path' format."""
        repo_part, path_part = mapping.split(":", 1)
        org, name = repo_part.split("/", 1)
        return cls(org=org, name=name, local_path=Path(path_part).expanduser())


async def create_snapshot(local_path: Path, output_bundle: Path) -> None:
    """Create a git bundle from local repo, including uncommitted changes.
    
    Strategy:
    1. Create bundle of all refs
    2. If there are uncommitted changes, create a temporary commit and include it
    """
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    
    # Check for uncommitted changes
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(local_path), "status", "--porcelain",
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    has_changes = bool(stdout.strip())
    
    if has_changes:
        # Create temporary commit with uncommitted changes
        await _create_snapshot_with_changes(local_path, output_bundle)
    else:
        # Simple bundle of current state
        await _create_simple_bundle(local_path, output_bundle)


async def _create_simple_bundle(local_path: Path, output_bundle: Path) -> None:
    """Create bundle without uncommitted changes."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(local_path), "bundle", "create",
        str(output_bundle), "--all",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def _create_snapshot_with_changes(local_path: Path, output_bundle: Path) -> None:
    """Create bundle including uncommitted changes as a snapshot commit."""
    import tempfile
    import shutil
    
    # Clone to temp location
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_repo = Path(tmpdir) / "repo"
        
        # Clone the repo
        await asyncio.create_subprocess_exec(
            "git", "clone", str(local_path), str(tmp_repo),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        
        # Copy uncommitted files
        # (simplified - full implementation would use git status to find changed files)
        for item in local_path.iterdir():
            if item.name == ".git":
                continue
            dest = tmp_repo / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        
        # Commit the changes
        await asyncio.create_subprocess_exec(
            "git", "-C", str(tmp_repo), "add", "-A",
            stdout=asyncio.subprocess.DEVNULL,
        )
        await asyncio.create_subprocess_exec(
            "git", "-C", str(tmp_repo), "commit", "-m", "Shadow snapshot",
            "--author", "Shadow <shadow@localhost>",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        
        # Create bundle
        await _create_simple_bundle(tmp_repo, output_bundle)
```

### Phase 5: Manager Integration

`manager.py`:

```python
"""Shadow environment manager."""

import asyncio
from pathlib import Path
from dataclasses import dataclass, field

from .container import ContainerRuntime
from .gitea import GiteaClient
from .snapshot import RepoSpec, create_snapshot


@dataclass
class ShadowEnvironment:
    """A shadow environment instance."""
    name: str
    container_id: str
    repo_specs: list[RepoSpec] = field(default_factory=list)


class ShadowManager:
    """Manages shadow environments."""
    
    def __init__(self):
        self.runtime = ContainerRuntime()
        self.base_dir = Path.home() / ".shadow"
        self.base_dir.mkdir(exist_ok=True)
    
    async def create(
        self,
        name: str,
        local_sources: list[str],
        image: str = "amplifier-shadow:local",  # Auto-built if missing
    ) -> ShadowEnvironment:
        """Create a new shadow environment."""
        
        # Parse repo specs
        repo_specs = [RepoSpec.parse(s) for s in local_sources]
        
        # Create snapshot directory
        snapshot_dir = self.base_dir / "snapshots" / name
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Create snapshots
        for spec in repo_specs:
            bundle_path = snapshot_dir / f"{spec.org}/{spec.name}.bundle"
            await create_snapshot(spec.local_path, bundle_path)
        
        # Start container
        container_id = await self.runtime.run(
            image=image,
            name=f"shadow-{name}",
            mounts=[
                (snapshot_dir, "/snapshots", "ro"),
            ],
            detach=True,
        )
        
        # Wait for Gitea
        gitea = GiteaClient()
        # Note: exec into container to check Gitea
        for _ in range(60):
            code, _, _ = await self.runtime.exec(
                container_id,
                "curl -s http://localhost:3000/api/v1/version",
            )
            if code == 0:
                break
            await asyncio.sleep(0.5)
        
        # Create repos and push bundles
        for spec in repo_specs:
            await self._setup_repo(container_id, spec)
        
        # Configure git URL rewriting
        await self._configure_git(container_id)
        
        return ShadowEnvironment(
            name=name,
            container_id=container_id,
            repo_specs=repo_specs,
        )
    
    async def _setup_repo(self, container_id: str, spec: RepoSpec) -> None:
        """Create repo in Gitea and push bundle."""
        # Create org
        await self.runtime.exec(
            container_id,
            f'curl -s -X POST -u shadow:shadow '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"username": "{spec.org}"}}\' '
            f'http://localhost:3000/api/v1/orgs',
        )
        
        # Create repo
        await self.runtime.exec(
            container_id,
            f'curl -s -X POST -u shadow:shadow '
            f'-H "Content-Type: application/json" '
            f'-d \'{{"name": "{spec.name}", "private": false}}\' '
            f'http://localhost:3000/api/v1/orgs/{spec.org}/repos',
        )
        
        # Unbundle and push
        await self.runtime.exec(
            container_id,
            f'cd /tmp && '
            f'git clone /snapshots/{spec.org}/{spec.name}.bundle {spec.name} && '
            f'cd {spec.name} && '
            f'git remote set-url origin http://shadow:shadow@localhost:3000/{spec.org}/{spec.name}.git && '
            f'git push -u origin --all',
        )
    
    async def _configure_git(self, container_id: str) -> None:
        """Configure git to rewrite GitHub URLs to local Gitea."""
        commands = [
            'git config --global url."http://localhost:3000/".insteadOf "https://github.com/"',
            'git config --global url."http://localhost:3000/".insteadOf "git@github.com:"',
            'git config --global url."http://localhost:3000/".insteadOf "ssh://git@github.com/"',
            'git config --global url."http://localhost:3000/".insteadOf "git+https://github.com/"',
            'git config --global user.email "shadow@localhost"',
            'git config --global user.name "Shadow"',
        ]
        for cmd in commands:
            await self.runtime.exec(container_id, cmd)
    
    async def exec(self, name: str, command: str) -> tuple[int, str, str]:
        """Execute command in shadow environment."""
        return await self.runtime.exec(f"shadow-{name}", command)
    
    async def shell(self, name: str) -> None:
        """Open interactive shell in shadow environment."""
        import subprocess
        subprocess.run([self.runtime.runtime, "exec", "-it", f"shadow-{name}", "bash"])
    
    async def destroy(self, name: str) -> None:
        """Destroy shadow environment."""
        await self.runtime.stop(f"shadow-{name}")
        
        snapshot_dir = self.base_dir / "snapshots" / name
        if snapshot_dir.exists():
            import shutil
            shutil.rmtree(snapshot_dir)
```

## Container Image Build

### Build Script

```bash
#!/bin/bash
# build-image.sh

set -e

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64) GITEA_ARCH="amd64" ;;
    aarch64|arm64) GITEA_ARCH="arm64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

GITEA_VERSION="1.21.4"

docker build \
    --build-arg GITEA_VERSION=$GITEA_VERSION \
    --build-arg GITEA_ARCH=$GITEA_ARCH \
    -t amplifier-shadow:latest \
    -t ghcr.io/microsoft/amplifier-shadow:latest \
    .
```

### Multi-arch Support

The image should support both amd64 and arm64 (for Mac M-series).

## Testing Plan

### Unit Tests

```python
# tests/test_snapshot.py
async def test_create_snapshot_clean_repo():
    """Snapshot of clean repo creates valid bundle."""
    
async def test_create_snapshot_with_uncommitted():
    """Snapshot includes uncommitted changes."""

# tests/test_container.py
async def test_container_start_stop():
    """Container lifecycle works."""

# tests/test_gitea.py
async def test_gitea_create_repo():
    """Can create repo via API."""
```

### Integration Tests

```python
# tests/test_integration.py
async def test_full_workflow():
    """Complete shadow create → exec → destroy flow."""
    
    # Create shadow with local source
    env = await manager.create(
        name="test",
        local_sources=["microsoft/test-repo:./fixtures/test-repo"],
    )
    
    # Verify git clone uses local
    code, stdout, _ = await manager.exec("test", "git clone https://github.com/microsoft/test-repo /tmp/cloned")
    assert code == 0
    
    # Verify content matches local
    code, stdout, _ = await manager.exec("test", "cat /tmp/cloned/marker.txt")
    assert "local-snapshot-marker" in stdout
    
    # Cleanup
    await manager.destroy("test")
```

## Migration Notes

### What's Removed

1. **All sandbox backends** - bwrap, seatbelt, direct mode
2. **Path rewriting complexity** - no more per-backend path handling
3. **Bare repo management** - Gitea handles this
4. **Complex gitconfig generation** - simple URL rewriting

### What's Added

1. **Container runtime abstraction** - Docker/Podman
2. **Gitea integration** - API client, repo setup
3. **Git bundle snapshots** - portable, includes uncommitted changes
4. **Container image** - pre-built with Gitea + tools

### Breaking Changes

- CLI syntax unchanged (`shadow create --local ...`)
- Requires Docker or Podman (no more native sandbox)
- Container must be available (no offline-only mode)

## Success Criteria

1. `amplifier-shadow create` with local sources works on Linux and macOS
2. `git clone https://github.com/...` inside shadow uses local snapshot
3. `uv pip install git+https://github.com/...` uses local snapshot
4. Multiple shadows can run simultaneously with different repo versions
5. `amplifier-shadow destroy` cleanly removes all resources
