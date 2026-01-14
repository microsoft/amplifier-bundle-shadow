# Shadow Smoke Test Protocol

This protocol ensures shadows work correctly before expensive testing begins.

## Purpose

Prevent wasting tokens on broken shadows. Verify the shadow actually works before claiming it's ready.

---

## When to Run

**ALWAYS run after:**
- Creating a new shadow environment
- Adding sources to existing shadow
- Before handing off to validators
- Before claiming "shadow is ready"

---

## The Protocol

### Step 1: Create Shadow and Capture Metadata

```python
result = shadow.create(
    local_sources=[
        "~/repos/my-lib:org/my-lib",
        "~/repos/another-lib:org/another-lib"
    ],
    name="test-env"
)

# Capture these for verification:
shadow_id = result["shadow_id"]
snapshot_commits = result["snapshot_commits"]
```

**Verify:**
- `snapshot_commits` is non-empty dict
- Each local source has a commit hash

**If snapshot_commits is empty:** Shadow creation failed - investigate and recreate.

---

### Step 2: Run Smoke Test

**Purpose:** Verify local sources are actually being used (not just configured)

```python
# Pick any local source to test
test_repo = list(snapshot_commits.keys())[0]
expected_commit = snapshot_commits[test_repo]

smoke_result = shadow.exec(shadow_id, f"""
    cd /tmp &&
    git clone https://github.com/{test_repo} smoke-test &&
    cd smoke-test &&
    git log -1 --format='%H'
""")
```

**Verify:**
- Exit code is 0 (clone succeeded)
- No DNS errors in stderr
- No "gitea" hostname errors
- stdout contains commit hash

**Compare commits:**
```python
actual_commit = smoke_result["stdout"].strip()

if not actual_commit.startswith(expected_commit[:7]):
    FAIL(f"Local sources NOT being used!")
    FAIL(f"Expected: {expected_commit}")
    FAIL(f"Got: {actual_commit}")
```

**Common failure modes:**
- DNS error for "gitea" → Git URL rewriting misconfigured
- Wrong commit → Local snapshot not being served
- Clone fails → Shadow is broken

---

### Step 3: Verify Environment Variables (if needed)

```python
env_result = shadow.exec(shadow_id, 
    "env | grep -E '(ANTHROPIC|OPENAI|GITHUB)_API_KEY'")
```

**Verify:**
- Required API keys are present
- Count matches expected number

---

### Step 4: Prepare Handoff Package

**Only if ALL verifications pass:**

```python
handoff_package = {
    "shadow_id": shadow_id,
    "snapshot_commits": snapshot_commits,
    "local_sources": [
        "~/repos/my-lib:org/my-lib",
        "~/repos/another-lib:org/another-lib"
    ],
    "pre_validation_passed": True,  # CRITICAL
    "smoke_test_output": smoke_result["stdout"],
    "env_vars_passed": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
    "verification_complete": True
}
```

**Hand this to validator with:**
```
"Shadow verified and ready for testing. Pre-validation passed ✓

Shadow ID: {shadow_id}
Snapshot commits verified:
  - org/my-lib @ {commit[:8]}
  
Smoke test: PASSED
All local sources confirmed working.

Here's the handoff package for comprehensive validation..."
```

---

## Failure Handling

### If Smoke Test Fails

**DO:**
1. Report to user: "Shadow creation failed smoke test"
2. Show error output clearly
3. Destroy shadow: `shadow.destroy(shadow_id, force=True)`
4. Ask user if you should retry or need help

**DON'T:**
- Proceed to "fix" it with docker exec
- Create manual override files
- Debug for >5k tokens without progress
- Hand off broken shadow to validator

### If Stuck (>5k tokens debugging)

**Stop and report:**
```
I've spent significant tokens trying to get the shadow working but haven't succeeded.

What I tried: [summary]
Current error: [error]

I recommend:
1. Reviewing the shadow architecture documentation
2. Destroying this shadow and starting fresh
3. Or you can help me understand what's going wrong
```

---

## Red Flags Checklist

If you encounter ANY of these while verifying shadow, **STOP** and re-read architecture:

- [ ] DNS error for hostname "gitea"
- [ ] Creating files in `~/.gitconfig` manually
- [ ] Using `docker exec` instead of `shadow exec`
- [ ] Looking for external gitea containers
- [ ] Checking docker networks
- [ ] Modifying `/etc/hosts`
- [ ] Creating manual git URL override files

**These indicate fundamental architecture misunderstanding.**

The correct architecture:
- Gitea runs INSIDE the shadow container
- Access via `localhost:3000` from inside container
- Git URL rewriting is automatic via git config
- Just use standard `https://github.com/...` URLs

---

## Success Criteria

Before handoff or claiming "shadow ready", confirm:

✅ Shadow created successfully  
✅ Snapshot commits captured (non-empty dict)  
✅ Smoke test passed (git clone works with correct commit)  
✅ Environment variables present (if needed)  
✅ No "gitea" hostname in any URLs or errors  
✅ Used `shadow exec` for all commands (not docker exec)  
✅ No manual override files created  

**If ALL checkboxes pass → safe to proceed**  
**If ANY checkbox fails → fix before handoff**

---

## Token Budget

**Expected token cost for smoke test protocol:** ~1-2k tokens

**If you exceed 5k tokens**, you're debugging instead of following the protocol. Stop and reassess.

---

## Reference

For detailed shadow environment architecture and usage patterns:

@shadow:context/shadow-instructions.md
