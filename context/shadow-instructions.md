# Shadow Environment Instructions

You have access to the `amplifier-shadow` tool for creating isolated test environments.

## Quick Reference

| Operation | Description |
|-----------|-------------|
| `create` | Create shadow environment with local source snapshots |
| `add-source` | Add local sources to an existing shadow |
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
amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core
```

Git is configured to rewrite only that specific repo:

```
[url "file:///repos/microsoft/amplifier-core.git"]
    insteadOf = https://github.com/microsoft/amplifier-core
```

This means:
- `git clone https://github.com/microsoft/amplifier-core` → uses your **local snapshot**
- `git clone https://github.com/microsoft/amplifier` → fetches from **real GitHub**

Your local working directory is snapshotted **exactly as-is** with full git history preserved:
- New files are included
- Modified files have your current changes  
- Deleted files are properly removed from the snapshot
- **No staging required** - what you see in your directory is what appears in the shadow

## Verifying Local Sources Are Used

After creating a shadow with local sources, you need to **verify** your local code is actually being used:

### Step 1: Check snapshot commits (from create/status output)

```python
# Create returns snapshot_commits showing what was captured
result = shadow.create(local_sources=["~/repos/amplifier-core:microsoft/amplifier-core"])
# Output includes:
#   snapshot_commits: {"microsoft/amplifier-core": "abc1234..."}
#   env_vars_passed: ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]

# Or check existing shadow
result = shadow.status(shadow_id)
# Shows snapshot_commits for verification
```

### Step 2: Compare with uv output during install

```python
# When you install, uv shows the commit hash it resolved
shadow.exec(shadow_id, "uv tool install git+https://github.com/microsoft/amplifier")
# Look for: amplifier-core @ git+...@abc1234

# If the commit matches snapshot_commits, your local code is being used!
```

### Step 3: Verify API keys are available

```python
# Don't assume - verify!
shadow.exec(shadow_id, "env | grep -E 'ANTHROPIC|OPENAI|API_KEY'")
# Should show your API keys are present
```

**Key insight**: The `create` and `status` operations now return `snapshot_commits` so you can verify the exact commit that was captured from your local repo.

## Common Patterns

### Test Local Changes

```python
# Create shadow with your local amplifier-core changes
shadow.create(local_sources=["~/repos/amplifier-core:microsoft/amplifier-core"])

# Install amplifier - it uses YOUR local amplifier-core
shadow.exec(shadow_id, "uv tool install git+https://github.com/microsoft/amplifier")

# Install providers (quiet mode for automation)
shadow.exec(shadow_id, "amplifier provider install -q")

# Test it works
shadow.exec(shadow_id, 'amplifier run "Hello, confirm you are working"')
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

- **Filesystem**: Only `/workspace` and home directory are writable inside container
- **Network**: Full access (including GitHub for repos not in your local sources)
- **Processes**: Isolated via Docker/Podman containers
- **Environment**: Fresh `AMPLIFIER_HOME`, isolated git config, API keys auto-passed
- **Git history**: Preserved from your local repos (pinned commits work)
- **Gitea server**: Embedded git server hosts your local repo snapshots

## Important Notes

- **Keep local repos current**: Run `git fetch --all` if pinned commits fail
- **Exact working tree captured**: Your working directory state is captured exactly - files, modifications, AND deletions
- **No staging required**: Unlike git workflows, you don't need to `git add` - the snapshot mirrors your filesystem
- **Only specified repos are local**: Everything else uses real GitHub
- **Security hardened**: Containers run with dropped capabilities and resource limits

## CRITICAL: Process Safety

**NEVER run these commands - they will kill the parent session:**

```bash
# DANGEROUS - kills parent Amplifier session
pkill -f amplifier   # NEVER
pkill amplifier      # NEVER
killall amplifier    # NEVER
```

**If a command times out:**
1. Report the timeout to the user
2. Use `shadow(operation="destroy", ...)` to clean up
3. Let the user handle any host-side cleanup

Running `pkill -f amplifier` from within Amplifier is a **self-destruct command** that kills the parent session, loses all user work, and terminates the conversation.
