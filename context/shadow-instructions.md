# Shadow Environment Instructions

You have access to the `shadow` tool for creating isolated test environments.

## Quick Reference

| Operation | Description |
|-----------|-------------|
| `create` | Create shadow environment with mock repos |
| `exec` | Run command inside sandbox |
| `diff` | Show changed files |
| `extract` | Copy file from sandbox to host |
| `inject` | Copy file from host to sandbox |
| `list` | List all environments |
| `status` | Get environment status |
| `destroy` | Destroy environment |

## How It Works

Shadow environments intercept `git+https://github.com/...` URLs using git's URL rewriting feature. When you run:

```bash
uv tool install git+https://github.com/microsoft/amplifier
```

Inside a shadow, git rewrites this to:

```bash
git clone file:///repos/github.com/microsoft/amplifier.git
```

This means **real GitHub is never contacted** - all git operations use local mock repos.

## Common Patterns

### Test a Feature Branch

```python
# Create shadow with feature branch
shadow.create(repos=["microsoft/amplifier-core@my-feature"])

# Install and test
shadow.exec(shadow_id, "uv tool install git+https://github.com/microsoft/amplifier")
shadow.exec(shadow_id, "amplifier test-feature")
```

### Test Multi-Repo Changes

```python
# Create shadow with multiple repos
shadow.create(repos=[
    "microsoft/amplifier",
    "microsoft/amplifier-core",
    "microsoft/amplifier-foundation"
])

# Each repo is available as a mock
```

### Extract and Validate

```python
# After inner agent makes changes
changes = shadow.diff(shadow_id)

# Extract promising fixes
for file in changes["changed_files"]:
    shadow.extract(shadow_id, file["path"], f"./extracted{file['path']}")

# Test in fresh environment
shadow.create(repos=["microsoft/amplifier"], name="validation")
# ... inject and test
```

## Isolation Guarantees

- **Filesystem**: Only `/workspace` and home directory are writable
- **Network**: github.com blocked, other sites accessible
- **Processes**: Isolated via Bubblewrap (Linux) or Seatbelt (macOS)
- **Environment**: Fresh `AMPLIFIER_HOME`, isolated git config
