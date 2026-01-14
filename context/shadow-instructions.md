# Shadow Environment Instructions

You have access to the `shadow` tool for creating OS-level isolated container environments for safe testing. Optionally, snapshot local git repositories to test uncommitted changes before pushing.

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
| `status` | Get environment status (includes snapshot commits) |
| `destroy` | Destroy environment |

## How It Works

Shadow environments use **selective git URL rewriting**. When you create a shadow with local sources:

```bash
# Generic example
amplifier-shadow create --local ~/repos/my-library:myorg/my-library
```

Git is configured to rewrite only that specific repo:

```
[url "http://shadow:shadow@localhost:3000/myorg/my-library.git"]
    insteadOf = https://github.com/myorg/my-library.git
```

Note: Patterns always include boundary markers (`.git`, `/`, `@`) to prevent prefix collisions between similar repo names.

This means:
- `git clone https://github.com/myorg/my-library` → uses your **local snapshot**
- `git clone https://github.com/myorg/other-repo` → fetches from **real GitHub**

Your local working directory is snapshotted **exactly as-is** with full git history preserved:
- New files are included
- Modified files have your current changes  
- Deleted files are properly removed from the snapshot
- **No staging required** - what you see in your directory is what appears in the shadow

---

## CRITICAL: Gitea Architecture

### Where is Gitea?

**Gitea runs INSIDE the shadow container at `localhost:3000`**

```
┌──────────────────────────────────────────────────────┐
│  Shadow Container                                     │
│  ┌─────────────────┐    ┌──────────────────────────┐ │
│  │  Gitea Server   │    │  Your commands run here  │ │
│  │  localhost:3000 │◄───│  (via shadow exec)       │ │
│  └─────────────────┘    └──────────────────────────┘ │
│           │                                           │
│           ▼                                           │
│  Git config rewrites:                                 │
│  github.com/org/repo → localhost:3000/org/repo.git   │
└──────────────────────────────────────────────────────┘
```

### Access Patterns

| From | URL |
|------|-----|
| **Inside container** (via shadow exec) | `http://localhost:3000/org/repo.git` |
| **From host** | Not directly accessible - must exec into container |

### Common Mistake: Wrong Hostname

❌ **WRONG:** `git+http://gitea:3000/microsoft/amplifier`  
✅ **RIGHT:** Use standard GitHub URLs - git rewrites automatically

The hostname "gitea" does NOT exist. Gitea is at `localhost:3000` inside the container.

### The Rewriting Is Automatic

When you run commands inside the shadow:
```bash
shadow exec <id> "git clone https://github.com/org/my-lib"
```

Git sees the URL rewriting config and automatically redirects to your local snapshot:
```bash
# Git internally rewrites to:
git clone http://shadow:shadow@localhost:3000/org/my-lib.git
```

**You should never manually specify localhost:3000 URLs** - just use standard GitHub URLs and let the rewriting work.

---

## Verifying Local Sources Are Used

After creating a shadow with local sources, **verify** your local code is actually being used:

### Step 1: Check snapshot commits (from create/status output)

```python
# Create returns snapshot_commits showing what was captured
result = shadow.create(local_sources=["~/repos/my-lib:myorg/my-lib"])
# Output includes:
#   snapshot_commits: {"myorg/my-lib": "abc1234..."}
#   env_vars_passed: ["MY_API_KEY", ...]

# Or check existing shadow
result = shadow.status(shadow_id)
# Shows snapshot_commits for verification
```

### Step 2: Compare with install output

```python
# When you install, uv/pip shows the commit hash it resolved
shadow.exec(shadow_id, "uv pip install git+https://github.com/myorg/my-lib")
# Look for: my-lib @ git+...@abc1234

# If the commit matches snapshot_commits, your local code is being used!
```

### Step 3: Verify environment variables

```python
# Don't assume - verify!
shadow.exec(shadow_id, "env | grep API_KEY")
# Should show your API keys are present
```

**Key insight**: The `create` and `status` operations return `snapshot_commits` so you can verify the exact commit captured from your local repo.

## Common Patterns

### Test Local Library Changes

```python
# Create shadow with your local library changes
shadow.create(local_sources=["~/repos/my-library:myorg/my-library"])

# Install the library - it uses YOUR local code
shadow.exec(shadow_id, "uv pip install git+https://github.com/myorg/my-library")

# Run tests
shadow.exec(shadow_id, "pytest tests/")
```

### Test Multi-Repo Changes

```python
# Create shadow with multiple local sources
shadow.create(local_sources=[
    "~/repos/core-lib:myorg/core-lib",
    "~/repos/cli-tool:myorg/cli-tool"
])

# Install the CLI - it uses both your local repos
shadow.exec(shadow_id, "uv pip install git+https://github.com/myorg/cli-tool")
```

### Extract and Validate

```python
# After making changes inside the sandbox
changes = shadow.diff(shadow_id)

# Extract files for review
for file in changes["changed_files"]:
    shadow.extract(shadow_id, file["path"], f"./extracted{file['path']}")
```

## Amplifier Ecosystem Examples

When developing Amplifier itself or its ecosystem packages:

```python
# Test amplifier-core changes
shadow.create(local_sources=["~/repos/amplifier-core:microsoft/amplifier-core"])

# Install amplifier - it uses YOUR local amplifier-core
shadow.exec(shadow_id, "uv tool install git+https://github.com/microsoft/amplifier")

# Install providers (quiet mode for automation)
shadow.exec(shadow_id, "amplifier provider install -q")

# Test it works
shadow.exec(shadow_id, 'amplifier run "Hello, confirm you are working"')
```

Multi-repo Amplifier testing:

```python
shadow.create(local_sources=[
    "~/repos/amplifier-core:microsoft/amplifier-core",
    "~/repos/amplifier-foundation:microsoft/amplifier-foundation"
])
# amplifier fetches from real GitHub, but its dependencies use your local snapshots
```

## Isolation Guarantees

- **Filesystem**: Only `/workspace` and home directory are writable inside container
- **Network**: Full access (including GitHub for repos not in your local sources)
- **Processes**: Isolated via Docker/Podman containers
- **Environment**: Fresh home directory, isolated git config, API keys auto-passed
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
