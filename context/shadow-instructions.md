# Shadow Environment Instructions

You have access to the `shadow` tool for creating OS-level isolated container environments for safe testing. Optionally, snapshot local git repositories to test uncommitted changes before pushing.

## Quick Reference

| Operation | Description |
|-----------|-------------|
| `create` | Create shadow environment with local source snapshots |
| `add-source` | Add local sources to an existing shadow |
| `exec` | Run command inside sandbox |
| `exec_batch` | Run multiple commands efficiently |
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
shadow create --local ~/repos/my-library:myorg/my-library
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

## CRITICAL: Iterating During Shadow Testing

**Do NOT assume new local commits are automatically available in existing shadows.** Shadows capture a point-in-time snapshot at creation. When you fix code locally and need to re-test, you MUST explicitly sync the changes.

### When Re-testing After Local Fixes

After making local commits to fix issues found during shadow testing, **always sync before re-testing**:

```python
# 1. Sync new local commits into the running shadow
shadow.add_source(shadow_id, "/path/to/local/repo:org/repo-name")

# 2. Verify the new commits are captured
shadow.status(shadow_id)  # Check snapshot_commits matches your local HEAD

# 3. Clear caches and reinstall
shadow.exec(shadow_id, "rm -rf /tmp/uv-cache /tmp/pip-cache")
shadow.exec(shadow_id, "uv pip install git+https://github.com/org/repo-name --reinstall")

# 4. Re-test
shadow.exec(shadow_id, "pytest tests/")
```

### Alternative: Destroy and Recreate

For major changes or when debugging cache issues, destroy and recreate for a clean slate:

```python
shadow.destroy(shadow_id)
shadow.create(local_sources=["/path/to/local/repo:org/repo-name"])
```

### Fastest Path for Python: Editable Install

If iterating rapidly on Python packages, use editable installs from `/workspace/`:

```python
shadow.exec(shadow_id, "pip install -e /workspace/org/repo-name")
shadow.exec(shadow_id, "pytest tests/")  # Changes reflected immediately
```

### Quick Reference

| Situation | Action |
|-----------|--------|
| Fixed code locally, need to re-test | `add-source` → clear cache → reinstall → test |
| Multiple iteration rounds | `add-source` each time before testing |
| Cache confusion or major changes | Destroy and recreate shadow |
| Rapid Python iteration | Editable install from `/workspace/` |

**Always verify** with `shadow.status(shadow_id)` that your commits are in the shadow before testing. See "Verifying Local Sources Are Used" below for detailed verification patterns.

---

## CRITICAL: Gitea Architecture

### Where is Gitea?

**Gitea runs INSIDE the shadow container at `localhost:3000`**

```
┌──────────────────────────────────────────────────────────┐
│  Shadow Container                                        │
│  ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │  Gitea Server   │    │  Your commands run here      │ │
│  │  localhost:3000 │◄───│  (via shadow exec)           │ │
│  └─────────────────┘    └──────────────────────────────┘ │
│           │                                              │
│           ▼                                              │
│  Git config rewrites:                                    │
│  github.com/org/repo → localhost:3000/org/repo.git      │
└──────────────────────────────────────────────────────────┘
```

### Access Patterns

| From | URL |
|------|-----|
| **Inside container** (via shadow exec) | `http://localhost:3000/org/repo.git` |
| **From host** | Not directly accessible - must exec into container |

### Common Mistake: Wrong Hostname

❌ **WRONG:** `git+http://gitea:3000/org/my-lib`  
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

---

## Pre-cloned Repository Locations

Local sources are automatically cloned to `/workspace/{org}/{repo}` inside the shadow container. This is the **authoritative location** for your local code:

```bash
# Your local source microsoft/my-library is available at:
/workspace/microsoft/my-library

# Use this path for editable installs (Python)
shadow exec <id> "pip install -e /workspace/microsoft/my-library"

# Or for Node.js
shadow exec <id> "cd /workspace/microsoft/my-package && npm install"
```

**Always check this location first** - the repo is already there, no need to clone.

---

## IMPORTANT: UV Tool Caching Gotcha

**Problem:** `uv tool install` has its own caching layer that may **bypass git insteadOf redirects**.

When you run:
```bash
shadow exec <id> "uv tool install git+https://github.com/myorg/my-cli"
```

UV may fetch from its GitHub cache instead of your local Gitea, even though git redirects are configured correctly.

### How to Detect This

```bash
# UV shows the resolved commit during install
# If this commit differs from your snapshot_commits, UV used its cache!
Updating https://github.com/myorg/my-lib (main)
Updated https://github.com/myorg/my-lib (976fb87...)  # ← Check this!
```

### How to Verify Correctly

**Don't trust UV's install output alone.** Verify through the actual source:

```bash
# 1. Check what Python is actually loading
shadow exec <id> "python3 -c 'import my_lib; print(my_lib.__file__)'"
# Should show: /workspace/myorg/my-lib/...  (your local snapshot)

# 2. Verify the workspace has the correct commit
shadow exec <id> "cd /workspace/myorg/my-lib && git rev-parse HEAD"
# Should match your snapshot_commits value

# 3. Git clone DOES respect redirects (for verification)
shadow exec <id> "git clone https://github.com/myorg/my-lib /tmp/test-clone && cd /tmp/test-clone && git log -1 --oneline"
# Should show your local snapshot commit
```

### Workarounds

If UV caching is a problem:

```bash
# Option 1: Install from the pre-cloned workspace (recommended)
shadow exec <id> "pip install -e /workspace/myorg/my-lib"

# Option 2: Clear UV cache first
shadow exec <id> "rm -rf /tmp/uv-cache && uv tool install git+https://github.com/myorg/my-cli"

# Option 3: Use pip instead of uv for git dependencies
shadow exec <id> "pip install git+https://github.com/myorg/my-lib"
```

---

## Common Patterns

### Test Local Library Changes (Python)

```python
# Create shadow with your local library changes
shadow.create(local_sources=["~/repos/my-library:myorg/my-library"])

# Install the library - it uses YOUR local code
shadow.exec(shadow_id, "uv pip install git+https://github.com/myorg/my-library")

# Run tests
shadow.exec(shadow_id, "pytest tests/")
```

### Test Local Package Changes (Node.js)

```python
# Create shadow with your local package
shadow.create(local_sources=["~/repos/my-package:myorg/my-package"])

# Clone and install
shadow.exec(shadow_id, "cd /workspace && git clone https://github.com/myorg/my-package")
shadow.exec(shadow_id, "cd /workspace/my-package && npm install")

# Run tests
shadow.exec(shadow_id, "cd /workspace/my-package && npm test")
```

### Test Local Crate Changes (Rust)

```python
# Create shadow with your local crate
shadow.create(local_sources=["~/repos/my-crate:myorg/my-crate"])

# Clone and build
shadow.exec(shadow_id, "cd /workspace && git clone https://github.com/myorg/my-crate")
shadow.exec(shadow_id, "cd /workspace/my-crate && cargo build")

# Run tests
shadow.exec(shadow_id, "cd /workspace/my-crate && cargo test")
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

## Isolation Guarantees

- **Filesystem**: Only `/workspace` and home directory are writable inside container
- **Network**: Full access (including GitHub for repos not in your local sources)
- **Processes**: Isolated via Docker/Podman containers
- **Environment**: Fresh home directory, isolated git config, API keys auto-passed
- **Git history**: Preserved from your local repos (pinned commits work)
- **Gitea server**: Embedded git server hosts your local repo snapshots

## Cache Isolation

Shadow environments isolate package manager caches to ensure URL rewriting works:

| Ecosystem | Cache Location in Shadow |
|-----------|--------------------------|
| Python (uv) | `/tmp/uv-cache` |
| Python (pip) | `/tmp/pip-cache` |
| Node (npm) | `/tmp/npm-cache` |
| Node (yarn) | `/tmp/yarn-cache` |
| Rust (cargo) | `/tmp/cargo-home` |
| Go | `/tmp/go-mod-cache` |

This prevents package managers from using cached GitHub packages instead of your local Gitea snapshots.

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
