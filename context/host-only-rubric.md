# Host-Only Smoke Test Rubric

When shadow environments are unavailable, use this 50-point rubric for host-only validation.

## When to Use This Rubric

Use this rubric when:
- `fallback_mode: true` in handoff manifest
- Shadow preflight fails (Docker not available)
- Image build fails
- Container creation fails

**Do NOT use this rubric** when shadow is available - use the full 100-point rubric instead.

---

## Host-Only Rubric (50 points)

### 1. Local Source Verification (15 points)

Verify the local source code is valid and testable.

| Check | Points | How to Verify |
|-------|--------|---------------|
| Local path exists | 5 | `ls -la {local_path}` returns content |
| Git repository valid | 5 | `cd {local_path} && git status` succeeds |
| Current commit readable | 5 | `git rev-parse HEAD` returns SHA |

### 2. Code Quality (15 points)

Basic code quality checks that don't require isolation.

| Check | Points | How to Verify |
|-------|--------|---------------|
| Syntax valid | 5 | Language-specific syntax check passes |
| Imports resolve | 5 | Import statements don't error immediately |
| Tests exist | 5 | Test files present in expected locations |

**Language-specific syntax checks:**
- Python: `python -m py_compile {file}` or `python -c "import ast; ast.parse(open('{file}').read())"`
- Node.js: `node --check {file}`
- Rust: `cargo check` (in project dir)
- Go: `go build ./...` (dry run)

### 3. Dependency Analysis (10 points)

Analyze dependencies without full isolation.

| Check | Points | How to Verify |
|-------|--------|---------------|
| Dependency file exists | 5 | pyproject.toml, package.json, Cargo.toml, go.mod |
| Dependencies parseable | 5 | File is valid TOML/JSON/etc. |

### 4. Basic Execution (10 points)

Minimal execution tests on the host.

| Check | Points | How to Verify |
|-------|--------|---------------|
| Package imports (if safe) | 5 | `python -c 'import {pkg}'` in venv |
| Version accessible | 5 | `{pkg}.__version__` or equivalent |

**CAUTION**: Only run execution tests if:
- A virtual environment is available
- The code is known to be safe
- Tests won't modify host state

---

## Score Interpretation

| Score | Interpretation |
|-------|----------------|
| 45-50 | Code ready for shadow testing when available |
| 35-44 | Code has minor issues, likely to work |
| 25-34 | Code has issues that may cause shadow failures |
| 0-24 | Code needs fixes before any testing |

**Pass Threshold**: 35/50 (70%)

---

## Output Format (Host-Only Mode)

```
+================================================================+
|  HOST-ONLY SMOKE TEST RESULTS                                   |
|  Mode: HOST-ONLY (shadow unavailable)                           |
|  Local Source: {path} @ {commit}                                |
|  Fallback Reason: {failure_reason}                              |
|  Tested: {timestamp}                                            |
+================================================================+

## Why Host-Only Mode?
{explanation of why shadow was unavailable}

## Local Source Verification (XX/15)
- [Y|N] Local path exists: {evidence}
- [Y|N] Git repository valid: {evidence}
- [Y|N] Current commit readable: {evidence}

## Code Quality (XX/15)
- [Y|N] Syntax valid: {evidence}
- [Y|N] Imports resolve: {evidence}
- [Y|N] Tests exist: {evidence}

## Dependency Analysis (XX/10)
- [Y|N] Dependency file exists: {evidence}
- [Y|N] Dependencies parseable: {evidence}

## Basic Execution (XX/10)
- [Y|N] Package imports: {evidence}
- [Y|N] Version accessible: {evidence}

## Recommendations for Full Testing
- {steps to enable shadow testing}
- {what would be tested with full rubric}

===================================================================
Total Score: XX/50
Pass Threshold: 35
Mode: HOST-ONLY

{Brief summary}

VERDICT: PASS
===================================================================
```

---

## Comparison: Full vs Host-Only

| Category | Full Rubric | Host-Only Rubric |
|----------|-------------|------------------|
| Source Verification | 25 pts (snapshot commits, URL rewriting) | 15 pts (local path only) |
| Installation Health | 20 pts (install in isolation) | N/A |
| Code Execution | 30 pts (run in isolation) | 10 pts (minimal, careful) |
| Isolation Integrity | 15 pts (container checks) | N/A |
| No Regressions | 10 pts (full smoke test) | N/A |
| Code Quality | N/A | 15 pts (syntax, imports) |
| Dependency Analysis | N/A | 10 pts (file checks) |
| **Total** | **100 pts** | **50 pts** |

---

## Why Different Scoring?

The full rubric tests **isolation guarantees** - that your code works in a clean environment without host contamination. These tests are impossible without a shadow environment:

- Snapshot commits being used (requires Gitea)
- Git URL rewriting working (requires container git config)
- Installed package uses correct source (requires isolated install)
- Container isolation verified (requires container)

The host-only rubric tests **code validity** - that your code is syntactically correct and likely to work. It's a necessary but not sufficient condition for the full rubric to pass.

**Key insight**: A 50/50 host-only score does NOT mean the code is "production ready" - it means the code is ready to be tested in isolation. Always run full shadow tests before merging.
