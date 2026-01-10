# Amplifier Shadow

Container-based isolated environments for safely testing Amplifier ecosystem changes.

## Overview

Amplifier Shadow creates isolated "shadow" environments that let you test local changes to Amplifier ecosystem packages before deploying them. Your local working directories (including uncommitted changes) are snapshotted and served via an embedded Gitea server, while everything else fetches from real GitHub.

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
# Create a shadow with your local amplifier-core changes
amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core

# Inside the shadow, install amplifier normally
# -> amplifier fetches from REAL GitHub
# -> amplifier-core uses YOUR LOCAL snapshot
amplifier-shadow exec shadow-abc123 "uv pip install git+https://github.com/microsoft/amplifier"

# Test it
amplifier-shadow exec shadow-abc123 "amplifier --version"

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
┌─────────────────────────────────────────────────────┐
│  Shadow Container                                   │
│  ┌─────────────────────────────────────────────┐   │
│  │  Gitea Server (localhost:3000)              │   │
│  │  - microsoft/amplifier-core (your snapshot) │   │
│  │  - microsoft/amplifier-foundation           │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  Git URL Rewriting:                                │
│  github.com/microsoft/amplifier-core → Gitea      │
│  github.com/microsoft/amplifier → Real GitHub     │
│                                                     │
│  /workspace (your working directory)               │
└─────────────────────────────────────────────────────┘
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
[url "http://shadow:shadow@localhost:3000/microsoft/amplifier-core.git"]
    insteadOf = https://github.com/microsoft/amplifier-core
```

This means:
- `git clone https://github.com/microsoft/amplifier-core` → uses your local snapshot
- `git clone https://github.com/microsoft/amplifier` → fetches from real GitHub

## CLI Commands

| Command | Description |
|---------|-------------|
| `create` | Create a new shadow environment with local sources |
| `exec` | Execute a command inside a shadow |
| `shell` | Open interactive shell in shadow |
| `list` | List all shadow environments |
| `status` | Show status of an environment |
| `diff` | Show changed files |
| `extract` | Copy file from shadow to host |
| `inject` | Copy file from host to shadow |
| `destroy` | Destroy an environment |
| `destroy-all` | Destroy all environments |

### Create Options

| Option | Description |
|--------|-------------|
| `--local`, `-l` | Local source mapping: `/path/to/repo:org/name` (repeatable) |
| `--name`, `-n` | Name for the environment (auto-generated if not provided) |
| `--image`, `-i` | Container image to use (default: `amplifier-shadow:local`, auto-built if missing) |

## Common Patterns

### Test a Single Module

```bash
# Testing your module with the real amplifier stack
amplifier-shadow create --local ~/repos/my-module:myorg/my-module --name module-test

# Clone and test inside shadow
amplifier-shadow exec module-test "
  cd /workspace && 
  git clone https://github.com/myorg/my-module &&
  cd my-module &&
  uv venv && . .venv/bin/activate &&
  uv pip install -e '.[dev]' &&
  pytest
"
```

### Test a PR/Branch Against Main

```bash
# Your feature branch is snapshotted; all other deps use main from GitHub
amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core --name pr-test

# Install full stack - only amplifier-core uses your local changes
amplifier-shadow exec pr-test "uv pip install git+https://github.com/microsoft/amplifier"
```

### Full Stack Integration Test

```bash
# Test changes across the entire Amplifier stack
amplifier-shadow create \
    --local ~/repos/amplifier-core:microsoft/amplifier-core \
    --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \
    --local ~/repos/amplifier-app-cli:microsoft/amplifier-app-cli \
    --name full-stack

amplifier-shadow exec full-stack "uv pip install git+https://github.com/microsoft/amplifier"
amplifier-shadow exec full-stack "amplifier --help"
```

### Iterate on Failures

```bash
# 1. Create shadow and run tests
amplifier-shadow create --local ~/repos/my-module:org/my-module --name test
amplifier-shadow exec test "cd /workspace && git clone ... && pytest"

# 2. Tests fail - fix locally on host

# 3. Destroy and recreate (picks up your local changes)
amplifier-shadow destroy test
amplifier-shadow create --local ~/repos/my-module:org/my-module --name test
amplifier-shadow exec test "cd /workspace && git clone ... && pytest"

# 4. Tests pass - commit with confidence!
```

## Use Cases

### Testing Local Changes

```bash
# You're working on amplifier-core and want to test the full install flow
amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core --name test-core

# Install amplifier - it will use your local amplifier-core changes
amplifier-shadow exec test-core "uv pip install git+https://github.com/microsoft/amplifier"

# Run tests or use amplifier
amplifier-shadow exec test-core "amplifier run"
```

### Testing Multi-Repo Changes

```bash
# Testing changes across multiple repos
amplifier-shadow create \
    --local ~/repos/amplifier-core:microsoft/amplifier-core \
    --local ~/repos/amplifier-foundation:microsoft/amplifier-foundation \
    --name multi-test

# Both local sources will be used, amplifier itself fetches from GitHub
amplifier-shadow exec multi-test "uv pip install git+https://github.com/microsoft/amplifier"
```

### Interactive Development

```bash
# Open a shell for interactive testing
amplifier-shadow shell test-env

# Inside the shadow shell:
$ uv pip install git+https://github.com/microsoft/amplifier
$ amplifier --version
$ exit

# Back on host - extract any files you created
amplifier-shadow extract test-env /workspace/notes.txt ./notes.txt
```

## When to Use Shadow vs Source Overrides

Amplifier offers two approaches for testing local changes:

| Approach | Command | Use When |
|----------|---------|----------|
| **Shadow Environment** | `amplifier-shadow create --local ...` | Testing installation flow, clean environment needed, multi-repo testing |
| **Source Override** | `amplifier source add org/repo /path` | Quick iteration, testing module loading, no container overhead |

**Shadow environments** are best when you need:
- Complete isolation from your host environment
- To test the full `git clone` → `pip install` flow
- To verify your changes work in a clean container
- To test multiple interdependent repos together

**Source overrides** are best when you need:
- Fast iteration without container startup
- To test module loading and registration
- Quick validation before full shadow testing

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
