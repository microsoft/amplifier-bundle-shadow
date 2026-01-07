# Amplifier Shadow

OS-level sandboxed environments for safely testing Amplifier ecosystem changes.

## Overview

Amplifier Shadow creates isolated "shadow" environments that intercept git operations to use local mock repositories. This enables safe testing of changes to Amplifier, amplifier-core, amplifier-foundation, and other ecosystem components before deployment.

## Key Features

- **Git URL Interception**: Rewrites `https://github.com/` URLs to local bare repos
- **OS-Level Sandboxing**: Uses Bubblewrap (Linux) or Seatbelt (macOS) for process isolation
- **File Operations**: Diff, extract, and inject files between sandbox and host
- **Network Isolation**: Blocks github.com while allowing other network access
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

## Quick Start

```bash
# Create a shadow environment with Amplifier repos
amplifier-bundle-shadow create microsoft/amplifier microsoft/amplifier-core

# Execute commands inside the sandbox
amplifier-bundle-shadow exec shadow-abc123 "uv tool install git+https://github.com/microsoft/amplifier"
amplifier-bundle-shadow exec shadow-abc123 "amplifier --version"

# See what changed
amplifier-bundle-shadow diff shadow-abc123

# Extract files from the sandbox
amplifier-bundle-shadow extract shadow-abc123 /workspace/fix.py ./fix.py

# Open an interactive shell
amplifier-bundle-shadow shell shadow-abc123

# Clean up when done
amplifier-bundle-shadow destroy shadow-abc123
```

## How It Works

### Git URL Rewriting

Inside the sandbox, a custom `.gitconfig` rewrites GitHub URLs:

```
[url "file:///repos/github.com/"]
    insteadOf = https://github.com/
```

This means when you run:
```bash
uv tool install git+https://github.com/microsoft/amplifier
```

Git actually clones from:
```bash
file:///repos/github.com/microsoft/amplifier.git
```

### Network Isolation

A custom `/etc/hosts` file blocks GitHub domains:
```
127.0.0.1 github.com
127.0.0.1 api.github.com
127.0.0.1 raw.githubusercontent.com
```

Other network access (PyPI, web, etc.) remains available.

### Sandbox Backends

| Platform | Backend | Tool |
|----------|---------|------|
| Linux | Bubblewrap | `bwrap` |
| macOS | Seatbelt | `sandbox-exec` |

## CLI Commands

| Command | Description |
|---------|-------------|
| `create` | Create a new shadow environment |
| `exec` | Execute a command inside a shadow |
| `shell` | Open interactive shell in shadow |
| `list` | List all shadow environments |
| `status` | Show status of an environment |
| `diff` | Show changed files |
| `extract` | Copy file from shadow to host |
| `inject` | Copy file from host to shadow |
| `destroy` | Destroy an environment |
| `destroy-all` | Destroy all environments |
| `backends` | Show available sandbox backends |

## Use Cases

### Testing Feature Branches

```bash
# Create shadow with your feature branch
amplifier-bundle-shadow create microsoft/amplifier-core@my-feature

# Test the full install flow
amplifier-bundle-shadow exec shadow-xxx "uv tool install git+https://github.com/microsoft/amplifier"
```

### Testing Multi-Repo Changes

```bash
# Create shadow with multiple repos
amplifier-bundle-shadow create \
    microsoft/amplifier@main \
    microsoft/amplifier-core@fix-branch \
    microsoft/amplifier-foundation@main

# Inject your local changes
amplifier-bundle-shadow inject shadow-xxx ./my-fix.py /workspace/amplifier-core/src/fix.py

# Test
amplifier-bundle-shadow exec shadow-xxx "cd /workspace && pytest"
```

### Validating Fixes

```bash
# After making changes in one shadow, extract them
amplifier-bundle-shadow extract shadow-old /workspace/src/fix.py ./fix.py

# Create fresh shadow and inject for clean validation
amplifier-bundle-shadow create microsoft/amplifier --name validation
amplifier-bundle-shadow inject validation ./fix.py /workspace/src/fix.py
amplifier-bundle-shadow exec validation "pytest"
```

## Requirements

### Linux
- Bubblewrap (`apt install bubblewrap` or `dnf install bubblewrap`)

### macOS
- sandbox-exec (built into macOS)

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
