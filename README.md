# Amplifier Shadow

Container-based isolated environments for safely testing Amplifier ecosystem changes.

## Overview

Amplifier Shadow creates isolated "shadow" environments that let you test local changes to Amplifier ecosystem packages before deploying them. Your local working directories (including uncommitted changes) are snapshotted and served via an embedded Gitea server, while everything else fetches from real GitHub.

## Key Features

- **Local Source Snapshots**: Test your working directory state, including uncommitted changes
- **Embedded Gitea**: Local git server inside the container handles your snapshotted repos
- **Selective URL Rewriting**: Only your specified repos are redirected; everything else uses real GitHub
- **Container Isolation**: Uses Docker or Podman for complete environment isolation
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

### Local Source Snapshots

When you create a shadow with `--local /path/to/repo:org/name`:

1. Your working directory is snapshotted as a git bundle (including uncommitted changes)
2. The container starts with an embedded Gitea server
3. Your snapshot is pushed to Gitea as `org/name`
4. Git URL rewriting redirects that specific repo to local Gitea
5. All other repos fetch from real GitHub normally

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
| `--image`, `-i` | Container image to use (default: `ghcr.io/microsoft/amplifier-shadow:latest`) |

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
