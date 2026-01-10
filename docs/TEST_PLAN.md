# Shadow Environment Test Plan

**Version**: 1.0  
**Date**: 2026-01-10  
**Status**: Implementation in Progress

## Purpose

Comprehensive testing to ensure shadow environments are:
- **A) USEFUL** - Actually helps developers test local changes
- **B) SAFE** - Prevents catastrophic failures
- **C) STABLE** - Works reliably across scenarios

## Primary Use Case

A developer has local modifications to Amplifier repos. They want to:
1. Run `amplifier-shadow create --local ~/repos/amplifier-core:microsoft/amplifier-core`
2. Inside the shadow: `uv tool install git+https://github.com/microsoft/amplifier`
3. Git dependencies resolve from GitHub EXCEPT registered local sources
4. Local sources transparently redirect via git URL rewriting
5. No special config needed inside - it "just works"

---

## Current Test Coverage

| Module | Test File | Coverage |
|--------|-----------|----------|
| `models.py` | `test_models.py` | Good |
| `environment.py` | `test_environment.py` | Good |
| `cli.py` | `test_cli.py` | Partial (error paths) |
| `manager.py` | `test_manager.py` | Minimal |
| `container.py` | - | **None** |
| `snapshot.py` | - | **None** |
| `gitea.py` | - | **None** |
| `builder.py` | - | **None** |

---

## Test Dimensions

### A. USEFULNESS Tests

Does the core mechanism work?

| ID | Test | Priority | Status |
|----|------|----------|--------|
| A1.1 | HTTPS URL rewriting works | P0 | Pending |
| A1.2 | git+ prefix rewriting works | P0 | Pending |
| A1.3 | Unregistered repos pass through to GitHub | P0 | Pending |
| A1.4 | .git suffix variants work | P1 | Pending |
| A2.1 | New uncommitted file captured | P0 | Pending |
| A2.2 | Modified uncommitted file captured | P0 | Pending |
| A2.3 | Staged but uncommitted captured | P1 | Pending |
| A3.1 | Pinned SHA in lock file resolves | P1 | Pending |
| A3.2 | Origin-only commit resolves | P1 | Pending |
| A4.1 | Shadow creation < 60 seconds | P1 | Pending |
| A4.2 | Full cycle < 2 minutes | P1 | Pending |

### B. SAFETY Tests

Does isolation work?

| ID | Test | Priority | Status |
|----|------|----------|--------|
| B1.1 | Cannot write to host filesystem | P0 | Pending |
| B1.2 | Cannot see host processes | P0 | Pending |
| B1.3 | pkill inside cannot kill host processes | P0 | Pending |
| B1.4 | Snapshots mount is readonly | P0 | Pending |
| B2.1 | Only specified env vars passed | P1 | Pending |
| B2.2 | Cannot access host ~/.amplifier | P1 | Pending |
| B3.1 | Host git config unchanged after ops | P0 | Pending |
| B3.2 | Source repo unchanged after shadow use | P0 | Pending |
| B3.3 | Destroy removes all traces | P1 | Pending |
| B4.1 | Running as non-root | P1 | Pending |
| B4.2 | Capabilities dropped | P1 | Pending |

### C. STABILITY Tests

Does it work across scenarios?

| ID | Test | Priority | Status |
|----|------|----------|--------|
| C1.1 | Two local sources work | P0 | Pending |
| C1.2 | Five local sources work | P1 | Pending |
| C1.3 | Dependency chain resolves | P1 | Pending |
| C2.1 | Docker runtime works | P1 | Pending |
| C2.2 | Podman runtime works | P1 | Pending |
| C3.1 | Clean repo works | P0 | Pending |
| C3.2 | Dirty repo works | P0 | Pending |
| C3.3 | Detached HEAD works | P2 | Pending |
| C5.1 | Invalid local path → clear error | P1 | Pending |
| C5.2 | Non-git directory → clear error | P1 | Pending |
| C5.3 | Network offline → graceful fail | P2 | Pending |

---

## Success Criteria

### A. USEFULNESS - Pass if:
- [x] `uv tool install git+https://github.com/microsoft/amplifier` uses local source
- [ ] Uncommitted Python changes visible in installed package
- [ ] Shadow create/destroy cycle < 2 minutes

### B. SAFETY - Pass if:
- [ ] Zero container escape vectors
- [ ] Host git config unchanged after 10 operations
- [ ] Source repos unchanged after shadow use
- [ ] pkill inside container cannot affect host

### C. STABILITY - Pass if:
- [ ] Works with Docker AND Podman
- [ ] Works with 1, 3, and 5 local sources
- [ ] Works with clean AND dirty repos
- [ ] 95%+ success rate over 20 runs

---

## Test Infrastructure

### Required Fixtures (`tests/conftest.py`)

```python
@pytest.fixture
def temp_git_repo(tmp_path):
    """Create minimal git repo for testing."""
    
@pytest.fixture
def dirty_git_repo(temp_git_repo):
    """Git repo with uncommitted changes."""
    
@pytest.fixture
async def shadow_manager(tmp_path):
    """ShadowManager with isolated shadow_home."""
    
@pytest.fixture
async def shadow_env(shadow_manager, temp_git_repo):
    """Live shadow environment, destroyed after test."""
```

### Test Categories

```
tests/
├── conftest.py              # Shared fixtures
├── unit/                    # Fast, mocked tests
│   ├── test_models.py       # ✓ Exists
│   ├── test_snapshot.py     # NEW
│   └── test_container.py    # NEW
├── integration/             # Real container tests
│   ├── test_url_rewriting.py
│   ├── test_uncommitted.py
│   └── test_multi_source.py
└── safety/                  # Security tests
    └── test_security_isolation.py  # ✓ Exists
```

---

## Running Tests

```bash
# Unit tests only (fast, no containers)
pytest tests/unit/ -v

# Integration tests (requires docker/podman)
pytest tests/integration/ -v --run-integration

# Safety tests (requires running shadow)
SHADOW_CONTAINER=shadow-test pytest tests/safety/ -v --run-security

# All tests
pytest -v --run-integration --run-security

# With coverage
pytest --cov=amplifier_bundle_shadow --cov-report=html
```

---

## P0 Test Implementation Order

1. **Test Infrastructure** - `conftest.py` with fixtures
2. **A1.1-A1.3** - URL rewriting (core mechanism)
3. **A2.1-A2.2** - Uncommitted changes (core value)
4. **B1.1-B1.3** - Container isolation (safety critical)
5. **B3.1-B3.2** - Host protection (safety critical)
6. **C3.1-C3.2** - Clean/dirty repo (basic functionality)

---

## Known Security Gaps to Address

From security-guardian analysis:

| Gap | Severity | Fix |
|-----|----------|-----|
| No `--cap-drop=ALL` | High | Add to container.py |
| No resource limits | Medium | Add `--memory`, `--pids-limit` |
| No explicit PID namespace | Medium | Verify default isolation |

---

## CI/CD (Future)

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      - run: uv run pytest tests/unit/ -v

  integration:
    runs-on: ubuntu-latest
    services:
      docker:
        image: docker:dind
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      - run: uv run pytest tests/integration/ -v --run-integration
```
