# Amplifier Shadow

OS-level isolated container environments for safe testing.

## Overview

Amplifier Shadow creates isolated "shadow" environments - containerized sandboxes for testing without affecting your host system. Optionally, snapshot local git repositories to test uncommitted changes before pushing.

**Use cases:**
- **Clean-state validation** - "Does it work on a fresh machine?"
- **Destructive testing** - Tests that modify system state won't affect host
- **Local git changes** - Test library changes before publishing (with `--local` flag)
- **Multi-repo testing** - Validate coordinated changes work together
- **CI/CD dry-runs** - See what CI will see
- **Dependency isolation** - Test with specific versions without polluting host
- **Security testing** - Run untrusted code safely

## Key Features

- **Exact Working Tree Snapshots**: Test your working directory state exactly as-is - new files, modifications, AND deletions
- **Embedded Gitea**: Local git server inside the container handles your snapshotted repos
- **Selective URL Rewriting**: Only your specified repos are redirected; everything else uses real GitHub
- **Security-Hardened Containers**: Uses Docker or Podman with dropped capabilities, no-new-privileges, and resource limits
- **File Operations**: Diff, extract, and inject files between container and host
- **Ephemeral Environments**: Create, use, and destroy environments as needed

## Installation

```bash
# Install from source
uv tool install git+https://github.com/microsoft/amplifier-bundle-shadow

# Or for development
git clone https://github.com/microsoft/amplifier-bundle-shadow
cd amplifier-bundle-shadow
uv pip install -e ".[dev]"
```

### Prerequisites

**Container Runtime (required):**
```bash
# Docker
sudo apt install docker.io  # Debian/Ubuntu
brew install docker         # macOS

# Or Podman (preferred - rootless by default)
sudo apt install podman     # Debian/Ubuntu
brew install podman         # macOS
```

The shadow tool will automatically detect and use podman if available, falling back to docker.

> **Shell Note**: The container uses `bash`. Use `. .venv/bin/activate` (dot syntax) which works in both `sh` and `bash`, for maximum compatibility.

## Quick Start

```bash
# Create a shadow with your local library changes
amplifier-shadow create --local ~/repos/my-library:myorg/my-library

# Inside the shadow, install via git URL
# -> my-library uses YOUR LOCAL snapshot
# -> all other dependencies fetch from REAL GitHub
amplifier-shadow exec shadow-abc123 "uv pip install git+https://github.com/myorg/my-library"

# Run tests
amplifier-shadow exec shadow-abc123 "cd /workspace && pytest"

# See what changed
amplifier-shadow diff shadow-abc123

# Open an interactive shell
amplifier-shadow shell shadow-abc123

# Clean up when done
amplifier-shadow destroy shadow-abc123
```

## How It Works

### Architecture

Shadow environments use a container with an embedded Gitea server:

```
┌─────────────────────────────────────────────────────────┐
│  Shadow Container                                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Gitea Server (localhost:3000)                  │   │
│  │  - myorg/my-library (your snapshot)             │   │
│  │  - myorg/other-lib (if specified)               │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  Git URL Rewriting:                                     │
│  github.com/myorg/my-library → Gitea (local)           │
│  github.com/myorg/other-repo → Real GitHub             │
│                                                         │
│  /workspace (your working directory)                    │
└─────────────────────────────────────────────────────────┘
```

### Exact Working Tree Snapshots

When you create a shadow with `--local /path/to/repo:org/name`:

1. Your working directory is captured **exactly as-is**:
   - New/untracked files are included
   - Modified files have your current changes
   - Deleted files are properly removed from the snapshot
   - **No staging required** - what you see in your directory is what appears in the shadow
2. The snapshot is bundled with full git history preserved
3. The container starts with an embedded Gitea server
4. Your snapshot is pushed to Gitea as `org/name`
5. Git URL rewriting redirects that specific repo to local Gitea
6. All other repos fetch from real GitHub normally

### Selective Git URL Rewriting

Inside the container, git config rewrites URLs only for your local sources:

```
[url "http://shadow:shadow@localhost:3000/myorg/my-library.git"]
    insteadOf = https://github.com/myorg/my-library
```

This means:
- `git clone https://github.com/myorg/my-library` → uses your local snapshot
- `git clone https://github.com/myorg/other-repo` → fetches from real GitHub

## CLI Commands

| Command | Description |
|---------|-------------|
| `create` | Create a new shadow environment with local sources |
| `add-source` | Add local sources to an existing shadow |
| `exec` | Execute a command inside a shadow |
| `shell` | Open interactive shell in shadow |
| `list` | List all shadow environments |
| `status` | Show status of an environment (includes snapshot commits) |
| `diff` | Show changed files |
| `extract` | Copy file from shadow to host |
| `inject` | Copy file from host to shadow |
| `destroy` | Destroy an environment |
| `destroy-all` | Destroy all environments |
| `build` | Build the shadow container image locally |

### Create Options

| Option | Description |
|--------|-------------|
| `--local`, `-l` | Local source mapping: `/path/to/repo:org/name` (repeatable) |
| `--name`, `-n` | Name for the environment (auto-generated if not provided) |
| `--image`, `-i` | Container image to use (default: `amplifier-shadow:local`, auto-built if missing) |
| `--env`, `-e` | Environment variable to pass: `KEY=VALUE` or `KEY` to inherit from host (repeatable) |
| `--env-file` | File with environment variables (one per line) |
| `--pass-api-keys/--no-pass-api-keys` | Auto-pass common API key env vars (default: enabled) |

## Common Patterns

### Test a Single Library

```bash
# Testing your library with its dependents
amplifier-shadow create --local ~/repos/my-library:myorg/my-library --name lib-test

# Clone and test inside shadow
amplifier-shadow exec lib-test "
  cd /workspace && 
  git clone https://github.com/myorg/my-library &&
  cd my-library &&
  uv venv && . .venv/bin/activate &&
  uv pip install -e '.[dev]' &&
  pytest
"
```

### Test Multi-Repo Changes

```bash
# Testing changes across multiple repos
amplifier-shadow create \
    --local ~/repos/core-lib:myorg/core-lib \
    --local ~/repos/cli-tool:myorg/cli-tool \
    --name multi-test

# Both local sources will be used
amplifier-shadow exec multi-test "uv pip install git+https://github.com/myorg/cli-tool"
```

### Test a PR/Branch Against Main

```bash
# Your feature branch is snapshotted; all other deps use main from GitHub
amplifier-shadow create --local ~/repos/my-lib:myorg/my-lib --name pr-test

# Install - only my-lib uses your local changes
amplifier-shadow exec pr-test "uv pip install git+https://github.com/myorg/my-app"
```

### Iterate on Failures

```bash
# 1. Create shadow and run tests
amplifier-shadow create --local ~/repos/my-lib:myorg/my-lib --name test
amplifier-shadow exec test "cd /workspace && git clone ... && pytest"

# 2. Tests fail - fix locally on host

# 3. Destroy and recreate (picks up your local changes)
amplifier-shadow destroy test
amplifier-shadow create --local ~/repos/my-lib:myorg/my-lib --name test
amplifier-shadow exec test "cd /workspace && git clone ... && pytest"

# 4. Tests pass - commit with confidence!
```

### Interactive Development

```bash
# Open a shell for interactive testing
amplifier-shadow shell test-env

# Inside the shadow shell:
$ uv pip install git+https://github.com/myorg/my-lib
$ python -c "import mylib; print(mylib.__version__)"
$ exit

# Back on host - extract any files you created
amplifier-shadow extract test-env /workspace/notes.txt ./notes.txt
```

## Amplifier Ecosystem Examples

When developing Amplifier itself or its ecosystem packages:

```bash
# Test amplifier-core changes
amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core --name core-test

# Install amplifier - it will use your local amplifier-core
amplifier-shadow exec core-test "uv tool install git+https://github.com/microsoft/amplifier"

# Install providers and test
amplifier-shadow exec core-test "amplifier provider install -q"
amplifier-shadow exec core-test "amplifier run 'Hello, verify you work'"
```

Full stack integration test:

```bash
amplifier-shadow create \
    --local ~/repos/amplifier-core:microsoft/amplifier-core \
    --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \
    --local ~/repos/amplifier-app-cli:microsoft/amplifier-app-cli \
    --name full-stack

amplifier-shadow exec full-stack "uv tool install git+https://github.com/microsoft/amplifier"
amplifier-shadow exec full-stack "amplifier --help"
```

## Verifying Local Sources Are Used

After creating a shadow, verify your local code is actually being used:

```bash
# Check what was captured
amplifier-shadow status my-shadow
# Shows: snapshot_commits: {"myorg/my-lib": "abc1234..."}

# Compare with install output - commits should match!
amplifier-shadow exec my-shadow "uv pip install git+https://github.com/myorg/my-lib"
# Look for: my-lib @ git+...@abc1234
```

## Troubleshooting

### PEP 668: Externally-Managed Environment

On modern Linux (Ubuntu 24.04+, Debian 12+), you may see:
```
error: externally-managed-environment
× This environment is externally managed
```

**Solution**: Always use virtual environments inside the shadow:
```bash
amplifier-shadow exec my-shadow "
  cd /workspace &&
  uv venv &&
  . .venv/bin/activate &&
  uv pip install ...
"
```

### Container Image Not Found

If you see image pull errors, build the image locally:
```bash
amplifier-shadow build
```

This builds `amplifier-shadow:local` from the bundled Dockerfile.

### Git Lock File Errors

If you see `index.lock` errors, ensure no git operations are running on your host repo, then destroy and recreate the shadow:
```bash
amplifier-shadow destroy my-shadow
amplifier-shadow create --local ~/repos/my-repo:org/my-repo --name my-shadow
```

### /workspace Permission Denied

The `/workspace` directory may not be writable in all configurations. Use `$HOME` or `/tmp` as alternatives:
```bash
amplifier-shadow exec my-shadow "cd $HOME && git clone ..."
```

## Contributing

> [!NOTE]
> This project is not currently accepting external contributions, but we're actively working toward opening this up. We value community input and look forward to collaborating in the future. For now, feel free to fork and experiment!

Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
