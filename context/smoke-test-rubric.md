# Shadow Smoke Test Rubric

This document provides detailed scoring criteria for the shadow smoke test validation rubric.

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
snapshot_commits: {"microsoft/amplifier-core": "abc123def456..."}
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
url.http://shadow:shadow@localhost:3000/microsoft/amplifier-core.git.insteadof https://github.com/microsoft/amplifier-core.git
```

#### 1.3 Installed Package Uses Snapshot (10 points)

**What to check**: When installing via `uv pip install git+https://github.com/<repo>`, the resolved commit matches the snapshot_commit.

| Points | Criteria |
|--------|----------|
| 10 | All packages resolve to their snapshot commits |
| 7 | Most packages resolve correctly, one mismatch |
| 5 | At least one package resolves correctly |
| 0 | No packages resolve to snapshot commits |

**How to verify**:
```bash
# Get verbose output during install
shadow exec <id> "uv pip install git+https://github.com/microsoft/amplifier-core -v 2>&1"

# Look for lines like:
#   amplifier-core @ git+https://github.com/microsoft/amplifier-core@abc123def456

# Compare abc123def456 to snapshot_commits["microsoft/amplifier-core"]
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
shadow exec <id> "git ls-remote https://github.com/microsoft/amplifier 2>&1 | head -1"

# Should show a real commit SHA, not "connection refused" to localhost
```

---

### 2. Installation Health (20 points)

This category validates that packages install correctly and are functional.

#### 2.1 Package Installs Without Errors (8 points)

**What to check**: `uv pip install` exits with code 0 and shows success.

| Points | Criteria |
|--------|----------|
| 8 | All packages install with exit code 0 |
| 4 | Some packages install, others fail |
| 0 | All packages fail to install |

**Example evidence**:
```
Successfully installed amplifier-core-0.1.0
```

#### 2.2 Package Imports Successfully (6 points)

**What to check**: `python -c 'import <package>'` succeeds.

| Points | Criteria |
|--------|----------|
| 6 | All packages import without errors |
| 3 | Some packages import successfully |
| 0 | All imports fail |

**How to verify**:
```bash
shadow exec <id> "python -c 'import amplifier_core; print(amplifier_core.__version__)'"
# Should output version like "0.1.0"
```

#### 2.3 CLI Tools Respond (6 points)

**What to check**: If the package provides CLI tools, they respond to `--version` or `--help`.

| Points | Criteria |
|--------|----------|
| 6 | CLI tool responds correctly |
| 3 | CLI tool responds with errors but runs |
| 0 | CLI tool not found or crashes |
| N/A | No CLI tools expected (award full 6 points) |

**How to verify**:
```bash
shadow exec <id> "amplifier --version"
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

**Strategy**: Build import statements from touched_files.

```python
# If touched_files includes "src/amplifier_core/session.py"
# Then test: from amplifier_core.session import Session
```

**How to verify**:
```bash
shadow exec <id> "python -c 'from amplifier_core.session import Session; print(Session)'"
```

#### 3.2 Basic Functionality Works (10 points)

**What to check**: A simple operation using the changed code succeeds.

| Points | Criteria |
|--------|----------|
| 10 | Basic operation completes without error |
| 5 | Operation runs but produces warnings |
| 0 | Operation fails or crashes |

**Strategy based on touched_files**:

| Touched File | Test Operation |
|--------------|----------------|
| `session.py` | Create a Session instance |
| `coordinator.py` | Create a Coordinator instance |
| `hooks.py` | Create and trigger a hook |
| `loader.py` | Load a simple config |

**How to verify**:
```bash
# For session.py changes
shadow exec <id> "python -c 'from amplifier_core import Session; s = Session(); print(s.id)'"

# For coordinator.py changes  
shadow exec <id> "python -c 'from amplifier_core import Coordinator; c = Coordinator({}); print(type(c))'"
```

#### 3.3 Integration Test Passes (10 points)

**What to check**: An end-to-end operation that exercises the full system.

| Points | Criteria |
|--------|----------|
| 10 | End-to-end operation completes successfully |
| 5 | Operation completes with non-critical errors |
| 0 | Operation fails |

**How to verify**:
```bash
# Full Amplifier smoke test (if API keys available)
shadow exec <id> "amplifier run 'Say hello' --max-turns 1"

# Or if no API keys, test the loading/config path
shadow exec <id> "python -c '
from amplifier_core import Session, Coordinator
from amplifier_core.interfaces import Provider

class MockProvider(Provider):
    @property
    def name(self): return \"mock\"
    async def complete(self, request): 
        return type(\"R\", (), {\"text\": \"OK\", \"tool_calls\": []})()

import asyncio
async def test():
    s = Session()
    c = Coordinator({\"providers\": {}})
    print(\"Integration OK\")
asyncio.run(test())
'"
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

**What to check**: The container cannot read the host's `~/.amplifier` directory.

| Points | Criteria |
|--------|----------|
| 5 | Host config directory not accessible or empty |
| 0 | Can read host's ~/.amplifier contents |

**How to verify**:
```bash
shadow exec <id> "ls -la ~/.amplifier/ 2>&1"
# Should show empty, not exist, or permission denied
# Should NOT show host's settings.yaml, projects/, etc.
```

#### 4.3 Only Expected Env Vars Present (5 points)

**What to check**: Only the expected API key environment variables are present.

| Points | Criteria |
|--------|----------|
| 5 | Env vars match expected list (from env_vars_passed in create output) |
| 3 | Some extra or missing env vars |
| 0 | Completely wrong set of env vars |

**How to verify**:
```bash
shadow exec <id> "env | grep -E 'API_KEY|ENDPOINT|HOST' | sort"
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
shadow exec <id> "python -c '
from amplifier_core import Session, Coordinator
from amplifier_core.hooks import HookManager
from amplifier_core.models import ToolDefinition
print(\"All imports OK\")
'"
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
shadow exec <id> "cd /workspace && python -m pytest tests/ -x --tb=short -q 2>&1 | tail -5"

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
| Package install fails | Dependency resolution issue | Check error message, may need different Python version |
| Import fails | Missing dependency | Check if all deps were installed |
| CLI not found | Package not installed as tool | May need `uv tool install` instead of `uv pip install` |
| Can read host ~/.amplifier | Mount configuration wrong | Check container mounts |
| Wrong env vars | Env passthrough misconfigured | Check DEFAULT_ENV_PATTERNS |
