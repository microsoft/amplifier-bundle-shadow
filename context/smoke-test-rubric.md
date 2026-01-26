# Shadow Smoke Test Rubric

This document provides detailed scoring criteria for validating shadow environments work correctly with local source changes.

## Scoring Philosophy

- **Objective over subjective**: Base scores on observable facts
- **Evidence required**: Every score must cite specific output
- **Fail-safe defaults**: When uncertain, do not award points
- **Partial credit**: Award proportional points for partial success

## Rubric Categories

### 1. Source Verification (25 points)

This category validates that local source snapshots are actually being used in the shadow environment, not just configured.

#### 1.1 Snapshot Commits Exist (5 points)

**What to check**: The `shadow status` output includes `snapshot_commits` with SHA hashes.

| Points | Criteria |
|--------|----------|
| 5 | All expected local sources have snapshot_commits |
| 3 | Some local sources have snapshot_commits |
| 0 | No snapshot_commits or status fails |

**Example evidence**:
```
snapshot_commits: {"myorg/my-library": "abc123def456..."}
```

#### 1.2 Git URL Rewriting Configured (5 points)

**What to check**: Inside the shadow, `git config --global --get-regexp "url.*insteadOf"` shows rewrite rules for each local source.

| Points | Criteria |
|--------|----------|
| 5 | All local sources have insteadOf rules pointing to localhost:3000 |
| 3 | Some local sources have rules |
| 0 | No rules or command fails |

**Example evidence**:
```
url.http://shadow:shadow@localhost:3000/myorg/my-library.git.insteadof https://github.com/myorg/my-library.git
```

#### 1.3 Installed Package Uses Snapshot (10 points)

**What to check**: When installing via git URL, the resolved commit matches the snapshot_commit.

| Points | Criteria |
|--------|----------|
| 10 | All packages resolve to their snapshot commits |
| 7 | Most packages resolve correctly, one mismatch |
| 5 | At least one package resolves correctly |
| 0 | No packages resolve to snapshot commits |

**How to verify (Python)**:
```bash
# Get verbose output during install
shadow exec <id> "uv pip install git+https://github.com/myorg/my-library -v 2>&1"

# Look for lines like:
#   my-library @ git+https://github.com/myorg/my-library@abc123def456

# Compare abc123def456 to snapshot_commits["myorg/my-library"]
```

**How to verify (Node.js)**:
```bash
# Clone and check commit
shadow exec <id> "cd /workspace && git clone https://github.com/myorg/my-package && cd my-package && git rev-parse HEAD"
```

**How to verify (Rust)**:
```bash
# Check Cargo.lock after build
shadow exec <id> "cd /workspace/my-crate && cargo build && grep -A2 'my-dependency' Cargo.lock"
```

#### 1.4 Unregistered Repos NOT Redirected (5 points)

**What to check**: A repo NOT in local_sources should reach real GitHub, not localhost.

| Points | Criteria |
|--------|----------|
| 5 | Unregistered repo reaches real GitHub (returns refs) |
| 0 | Unregistered repo is redirected or connection fails |

**How to verify**:
```bash
# Pick a repo NOT in local_sources
shadow exec <id> "git ls-remote https://github.com/python/cpython 2>&1 | head -1"

# Should show a real commit SHA, not "connection refused" to localhost
```

---

### 2. Installation Health (20 points)

This category validates that packages install correctly and are functional.

#### 2.1 Package Installs Without Errors (8 points)

**What to check**: Package manager exits with code 0 and shows success.

| Points | Criteria |
|--------|----------|
| 8 | All packages install with exit code 0 |
| 4 | Some packages install, others fail |
| 0 | All packages fail to install |

**Python example**:
```bash
shadow exec <id> "uv pip install git+https://github.com/myorg/my-library"
# Look for: Successfully installed my-library-X.Y.Z
```

**Node.js example**:
```bash
shadow exec <id> "cd /workspace/my-package && npm install"
# Look for: added N packages
```

**Rust example**:
```bash
shadow exec <id> "cd /workspace/my-crate && cargo build"
# Look for: Finished dev [unoptimized + debuginfo]
```

#### 2.2 Package Imports Successfully (6 points)

**What to check**: The package can be imported/used.

| Points | Criteria |
|--------|----------|
| 6 | All packages import without errors |
| 3 | Some packages import successfully |
| 0 | All imports fail |

**Python example**:
```bash
shadow exec <id> "python -c 'import my_library; print(my_library.__version__)'"
```

**Node.js example**:
```bash
shadow exec <id> "node -e 'const pkg = require(\"my-package\"); console.log(pkg.version)'"
```

**Rust example**:
```bash
shadow exec <id> "cd /workspace/my-crate && cargo run --example basic"
```

#### 2.3 CLI Tools Respond (6 points)

**What to check**: If the package provides CLI tools, they respond correctly.

| Points | Criteria |
|--------|----------|
| 6 | CLI tool responds correctly |
| 3 | CLI tool responds with errors but runs |
| 0 | CLI tool not found or crashes |
| N/A | No CLI tools expected (award full 6 points) |

**Example**:
```bash
shadow exec <id> "my-cli --version"
# Should output version info
```

---

### 3. Code Execution (30 points)

This is the **most important category**. It validates that the actual changed code works.

#### 3.1 Touched Modules Load (10 points)

**What to check**: The specific modules that were changed can be imported.

| Points | Criteria |
|--------|----------|
| 10 | All touched modules import successfully |
| 5 | Some touched modules import |
| 0 | None of the touched modules import |

**Strategy**: Build import/require statements from touched_files.

**Python example**:
```bash
# If touched_files includes "src/my_library/core.py"
shadow exec <id> "python -c 'from my_library.core import main; print(main)'"
```

**Node.js example**:
```bash
# If touched_files includes "src/utils.js"
shadow exec <id> "node -e 'const utils = require(\"./src/utils\"); console.log(typeof utils)'"
```

#### 3.2 Basic Functionality Works (10 points)

**What to check**: A simple operation using the changed code succeeds.

| Points | Criteria |
|--------|----------|
| 10 | Basic operation completes without error |
| 5 | Operation runs but produces warnings |
| 0 | Operation fails or crashes |

**Strategy**: Design a simple test based on what was changed.

**Example patterns**:
```bash
# For a library change
shadow exec <id> "python -c 'from my_library import MyClass; obj = MyClass(); print(obj)'"

# For a CLI change
shadow exec <id> "my-cli process --input test.txt"

# For a web framework change
shadow exec <id> "curl -s http://localhost:8000/health"
```

#### 3.3 Integration Test Passes (10 points)

**What to check**: An end-to-end operation that exercises the full system.

| Points | Criteria |
|--------|----------|
| 10 | End-to-end operation completes successfully |
| 5 | Operation completes with non-critical errors |
| 0 | Operation fails |

**Example**:
```bash
# Run existing tests if available
shadow exec <id> "cd /workspace/my-project && pytest tests/ -x --tb=short -q"

# Or run a simple integration scenario
shadow exec <id> "my-cli full-workflow --test-mode"
```

---

### 4. Isolation Integrity (15 points)

This category validates that the shadow environment is properly isolated from the host.

#### 4.1 Container Hostname Differs (5 points)

**What to check**: The hostname inside the container is different from the host.

| Points | Criteria |
|--------|----------|
| 5 | Container hostname is different (e.g., container ID) |
| 0 | Container hostname matches host |

**How to verify**:
```bash
shadow exec <id> "hostname"
# Should be something like "abc123def456" (container ID), not the host hostname
```

#### 4.2 Host Home Not Accessible (5 points)

**What to check**: The container cannot read the host's home directory contents.

| Points | Criteria |
|--------|----------|
| 5 | Host home directory not accessible or empty |
| 0 | Can read host's home directory contents |

**How to verify**:
```bash
shadow exec <id> "ls -la ~/ 2>&1"
# Should show empty or minimal contents, not host's files
```

#### 4.3 Only Expected Env Vars Present (5 points)

**What to check**: Only the expected environment variables are present.

| Points | Criteria |
|--------|----------|
| 5 | Env vars match expected list (from env_vars_passed in create output) |
| 3 | Some extra or missing env vars |
| 0 | Completely wrong set of env vars |

**How to verify**:
```bash
shadow exec <id> "env | grep -E 'API_KEY|TOKEN|SECRET' | sort"
# Compare to env_vars_passed from shadow create/status
```

---

### 5. No Regressions (10 points)

This category validates that existing functionality still works.

#### 5.1 Basic Imports Work (5 points)

**What to check**: Standard package imports succeed.

| Points | Criteria |
|--------|----------|
| 5 | All standard imports work |
| 0 | Standard imports fail |

**How to verify**:
```bash
# Test core imports for your package
shadow exec <id> "python -c 'from my_library import core, utils, models; print(\"OK\")'"
```

#### 5.2 Smoke Test Passes (5 points)

**What to check**: A simple operation that doesn't depend on the changes works.

| Points | Criteria |
|--------|----------|
| 5 | Smoke test passes |
| 0 | Smoke test fails |

**How to verify**:
```bash
# Run existing tests if available
shadow exec <id> "cd /workspace/my-project && pytest tests/ -x --tb=short -q 2>&1 | tail -5"

# Or simple sanity check
shadow exec <id> "python -c 'print(1 + 1)'"
```

---

## Score Calculation

```
Total = Source Verification + Installation Health + Code Execution + Isolation Integrity + No Regressions
      = 25 + 20 + 30 + 15 + 10
      = 100 points

Pass Threshold: 75 points
```

### Verdict Decision Tree

```
IF Total >= 75:
    IF any critical failure (score 0 in categories 1 or 3):
        VERDICT: FAIL (critical path broken despite high score)
    ELSE:
        VERDICT: PASS
ELSE:
    VERDICT: FAIL
```

### Critical Failures (automatic FAIL regardless of score)

- Source Verification score is 0 (local sources not being used at all)
- Code Execution score is 0 (changed code completely broken)
- Installation Health score is 0 (nothing installs)

---

## Reporting Template

```
+================================================================+
|  SHADOW SMOKE TEST RESULTS                                      |
|  Shadow ID: {shadow_id}                                         |
|  Local Sources: {repos}                                         |
|  Tested: {timestamp}                                            |
+================================================================+

## Source Verification ({score}/25)
- [{Y|N}] Snapshot commits exist: {evidence}
- [{Y|N}] Git URL rewriting configured: {evidence}
- [{Y|N}] Installed package uses snapshot: {evidence}
- [{Y|N}] Unregistered repos NOT redirected: {evidence}

## Installation Health ({score}/20)
- [{Y|N}] Package installs without errors: {evidence}
- [{Y|N}] Package imports successfully: {evidence}
- [{Y|N}] CLI tools respond: {evidence}

## Code Execution ({score}/30)
- [{Y|N}] Touched modules load: {evidence}
- [{Y|N}] Basic functionality works: {evidence}
- [{Y|N}] Integration test passes: {evidence}

## Isolation Integrity ({score}/15)
- [{Y|N}] Container hostname differs: {evidence}
- [{Y|N}] Host home not accessible: {evidence}
- [{Y|N}] Only expected env vars present: {evidence}

## No Regressions ({score}/10)
- [{Y|N}] Basic imports work: {evidence}
- [{Y|N}] Smoke test passes: {evidence}

===================================================================
Total Score: {total}/100
Pass Threshold: 75

{summary}

VERDICT: {PASS|FAIL}
===================================================================
```

---

## Common Failure Patterns

| Symptom | Likely Cause | Investigation |
|---------|--------------|---------------|
| Snapshot commit mismatch | Local repo not up to date | Run `git fetch --all` in local repo |
| No insteadOf rules | Shadow create failed silently | Check shadow status for errors |
| Package install fails | Dependency resolution issue | Check error message, may need different runtime version |
| Import fails | Missing dependency | Check if all deps were installed |
| CLI not found | Package not installed as tool | May need different install method |
| Can read host home | Mount configuration wrong | Check container mounts |
| Wrong env vars | Env passthrough misconfigured | Check DEFAULT_ENV_PATTERNS |
