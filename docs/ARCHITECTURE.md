# Shadow Environment: Container + Gitea Architecture

## Overview

Shadow environments provide isolated sandboxes for testing local changes to git-based packages before pushing them. This architecture uses containers with an embedded Gitea server to provide complete git isolation.

**Use cases:**
- Testing library changes before publishing
- Validating multi-repo changes work together  
- CI/CD dry-runs with local modifications
- Amplifier ecosystem development

```
┌─────────────────────────────────────────────────────────────────┐
│                    Shadow Container                              │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐     │
│  │                      Gitea                              │     │
│  │              http://localhost:3000                      │     │
│  │                                                         │     │
│  │  Repos (pushed from host snapshots):                    │     │
│  │  • myorg/my-library (your snapshot)                     │     │
│  │  • myorg/my-cli (your snapshot)                         │     │
│  └────────────────────────────────────────────────────────┘     │
│                           ↑                                      │
│                    git operations                                │
│                           ↓                                      │
│  ┌────────────────────────────────────────────────────────┐     │
│  │                    Workspace                            │     │
│  │                                                         │     │
│  │  • Specified git URLs rewritten to localhost:3000       │     │
│  │  • pip/uv/git all work transparently                    │     │
│  │  • Full Python/Node/etc. environment                    │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  Mounts:                                                         │
│  • /workspace ← host workspace (read-write)                      │
│  • /snapshots ← local repo snapshots (read-only)                 │
└──────────────────────────────────────────────────────────────────┘
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

### 2. Selective Git URL Rewriting

Only your specified local sources are rewritten to the local Gitea:

```bash
# Inside container's .gitconfig (for each local source)
[url "http://shadow:shadow@localhost:3000/myorg/my-library.git"]
    insteadOf = https://github.com/myorg/my-library
```

This means:
- `git clone https://github.com/myorg/my-library` → uses your local snapshot
- `git clone https://github.com/myorg/other-repo` → fetches from real GitHub
- `pip install git+https://github.com/myorg/my-library` → uses local Gitea
- `uv pip install git+https://github.com/myorg/my-library` → uses local Gitea

### 3. Snapshot Strategy

Local repositories are snapshotted and pushed to Gitea:

```
Host: ~/repos/my-library (with uncommitted changes)
  ↓
  git bundle create (includes working tree state)
  + fetch all remote refs (for lock file resolution)
  ↓
Container: Gitea creates repo, unbundle pushed
  + _upstream_* branches preserve remote refs
  ↓
Ready: http://localhost:3000/myorg/my-library
```

**Note**: The snapshot also fetches and preserves remote tracking refs so that commit hashes pinned in `uv.lock` or `package-lock.json` resolve correctly.

### 4. Environment Variable Passthrough

The CLI automatically passes API keys into the container:

```bash
# Auto-passed: *_API_KEY env vars
amplifier-shadow create --name test

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
    jq \
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
    --local ~/repos/my-library:myorg/my-library \
    --local ~/repos/my-cli:myorg/my-cli \
    --name my-test

# List environments
amplifier-shadow list

# Execute command in shadow
amplifier-shadow exec my-test "uv pip install git+https://github.com/myorg/my-library"
amplifier-shadow exec my-test "pytest"

# Interactive shell
amplifier-shadow shell my-test

# Status (shows snapshot commits for verification)
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
    
    # 6. Configure git URL rewriting (selective - only for local sources)
    await configure_git_rewriting(container_id, repo_specs)
    
    return ShadowEnvironment(name=name, container_id=container_id)
```

## Implementation Structure

The actual code structure:
```
src/amplifier_bundle_shadow/
├── __init__.py
├── __main__.py
├── builder.py         # Image building
├── cli.py             # Click CLI
├── container.py       # Docker/Podman operations
├── environment.py     # Environment state tracking
├── gitea.py           # Gitea API client
├── manager.py         # Main orchestration
├── models.py          # RepoSpec, ShadowEnvironment
└── snapshot.py        # Git bundle creation
```

## Amplifier Ecosystem Example

When developing Amplifier packages:

```bash
# Test changes across the entire Amplifier stack
amplifier-shadow create \
    --local ~/repos/amplifier-core:microsoft/amplifier-core \
    --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \
    --local ~/repos/amplifier-app-cli:microsoft/amplifier-app-cli \
    --name full-stack

amplifier-shadow exec full-stack "uv tool install git+https://github.com/microsoft/amplifier"
amplifier-shadow exec full-stack "amplifier --help"
```

## Multi-arch Support

The image supports both amd64 and arm64 (for Mac M-series).

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
        local_sources=["myorg/test-repo:./fixtures/test-repo"],
    )
    
    # Verify git clone uses local
    code, stdout, _ = await manager.exec("test", "git clone https://github.com/myorg/test-repo /tmp/cloned")
    assert code == 0
    
    # Verify content matches local
    code, stdout, _ = await manager.exec("test", "cat /tmp/cloned/marker.txt")
    assert "local-snapshot-marker" in stdout
    
    # Cleanup
    await manager.destroy("test")
```

## Success Criteria

1. `amplifier-shadow create` with local sources works on Linux and macOS
2. `git clone https://github.com/...` inside shadow uses local snapshot (for specified repos)
3. `uv pip install git+https://github.com/...` uses local snapshot (for specified repos)
4. Other repos fetch from real GitHub normally
5. Multiple shadows can run simultaneously with different repo versions
6. `amplifier-shadow destroy` cleanly removes all resources
