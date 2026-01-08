# Shadow Environment Instructions

You have access to the `shadow` tool for creating isolated test environments.

## Quick Reference

| Operation | Description |
|-----------|-------------|
| `create` | Create shadow environment with local source snapshots |
| `exec` | Run command inside sandbox |
| `diff` | Show changed files |
| `extract` | Copy file from sandbox to host |
| `inject` | Copy file from host to sandbox |
| `list` | List all environments |
| `status` | Get environment status |
| `destroy` | Destroy environment |

## How It Works

Shadow environments use **selective git URL rewriting**. When you create a shadow with local sources:

```bash
shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core
```

Git is configured to rewrite only that specific repo:

```
[url "file:///repos/microsoft/amplifier-core.git"]
    insteadOf = https://github.com/microsoft/amplifier-core
```

This means:
- `git clone https://github.com/microsoft/amplifier-core` → uses your **local snapshot**
- `git clone https://github.com/microsoft/amplifier` → fetches from **real GitHub**

Your local working directory (including uncommitted changes) is snapshotted with full git history preserved.

## Common Patterns

### Test Local Changes

```python
# Create shadow with your local amplifier-core changes
shadow.create(local_sources=["~/repos/amplifier-core:microsoft/amplifier-core"])

# Install amplifier - it uses YOUR local amplifier-core
shadow.exec(shadow_id, "uv tool install git+https://github.com/microsoft/amplifier")
shadow.exec(shadow_id, "amplifier --version")
```

### Test Multi-Repo Changes

```python
# Create shadow with multiple local sources
shadow.create(local_sources=[
    "~/repos/amplifier-core:microsoft/amplifier-core",
    "~/repos/amplifier-foundation:microsoft/amplifier-foundation"
])

# amplifier fetches from real GitHub, but its dependencies use your local snapshots
```

### Extract and Validate

```python
# After making changes inside the sandbox
changes = shadow.diff(shadow_id)

# Extract files for review
for file in changes["changed_files"]:
    shadow.extract(shadow_id, file["path"], f"./extracted{file['path']}")

# Test in fresh environment
shadow.create(local_sources=["~/repos/amplifier-core:microsoft/amplifier-core"], name="validation")
# ... inject and test
```

## Isolation Guarantees

- **Filesystem**: Only `/workspace` and home directory are writable
- **Network**: Full access (including GitHub for repos not in your local sources)
- **Processes**: Isolated via Bubblewrap (Linux) or Seatbelt (macOS)
- **Environment**: Fresh `AMPLIFIER_HOME`, isolated git config
- **Git history**: Preserved from your local repos (pinned commits work)

## Important Notes

- **Keep local repos current**: Run `git fetch --all` if pinned commits fail
- **Uncommitted changes included**: Your working directory state is captured
- **Only specified repos are local**: Everything else uses real GitHub
