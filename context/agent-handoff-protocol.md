# Agent Handoff Protocol

This document defines the communication contract between shadow-operator and smoke-test agents.

## Handoff Manifest Format

When shadow-operator delegates to smoke-test, it MUST provide a structured handoff manifest:

```yaml
# Handoff Manifest Structure
shadow_id: "shadow-abc123"           # Required if shadow exists
shadow_available: true|false          # Whether shadow environment is ready
local_sources:                        # List of local sources being tested
  - path: "~/repos/my-library"
    github_repo: "myorg/my-library"
    snapshot_commit: "abc123..."      # Commit captured in shadow
test_context:                         # What to test
  changed_files: [...]                # Files that changed
  affected_modules: [...]             # Modules impacted by changes
  project_type: "python|node|rust|go" # Detected project type
fallback_mode: false                  # True if shadow failed, host-only testing
failure_reason: null                  # If fallback_mode, why shadow failed
```

## Protocol: shadow-operator → smoke-test

### When Shadow Succeeds

```python
delegate(
    agent="shadow-smoke-test",
    instruction=f"""
Validate shadow environment with these parameters:

HANDOFF MANIFEST:
```yaml
shadow_id: {shadow_id}
shadow_available: true
local_sources:
  - path: {local_path}
    github_repo: {github_repo}
    snapshot_commit: {snapshot_commit}
test_context:
  project_type: {project_type}
  changed_files: {changed_files}
fallback_mode: false
```

Run full 100-point validation rubric.
""",
    context_depth="none"  # smoke-test runs independently
)
```

### When Shadow Fails (Fallback Mode)

```python
delegate(
    agent="shadow-smoke-test",
    instruction=f"""
Shadow environment unavailable - run HOST-ONLY validation.

HANDOFF MANIFEST:
```yaml
shadow_available: false
local_sources:
  - path: {local_path}
    github_repo: {github_repo}
test_context:
  project_type: {project_type}
  changed_files: {changed_files}
fallback_mode: true
failure_reason: "{failure_reason}"
```

Use HOST-ONLY rubric (50-point scale). Do NOT attempt shadow operations.
""",
    context_depth="none"
)
```

## Protocol: smoke-test Response

smoke-test MUST return a structured verdict:

```yaml
# Response Structure
verdict: "PASS" | "FAIL"
mode: "shadow" | "host-only"
score: 85                    # Out of 100 (shadow) or 50 (host-only)
max_score: 100               # Maximum possible for this mode
pass_threshold: 75           # Or 35 for host-only
evidence:
  source_verification: {...}
  installation_health: {...}
  code_execution: {...}
  # etc.
issues_found: [...]
recommendations: [...]
```

## Fallback Decision Tree

```
shadow.create() called
        │
        ▼
┌───────────────────┐
│ Preflight check   │
│ (auto on create)  │
└────────┬──────────┘
         │
    ┌────┴────┐
    │ Docker  │
    │ ready?  │
    └────┬────┘
         │
    NO   │   YES
    ▼    │    ▼
┌────────┴────────┐    ┌─────────────────┐
│ FALLBACK MODE   │    │ Image exists?   │
│ failure_reason: │    │ (auto-build)    │
│ "docker_unavail"│    └────────┬────────┘
└─────────────────┘             │
                           NO   │   YES
                           ▼    │    ▼
                    ┌───────────┴───────────┐
                    │ Build image           │
                    │ (build-image op)      │
                    └───────────┬───────────┘
                                │
                           FAIL │   OK
                           ▼    │    ▼
                    ┌───────────┴───────────┐
                    │ FALLBACK MODE         │
                    │ failure_reason:       │
                    │ "image_build_failed"  │
                    └───────────────────────┘
```

## Why This Protocol Matters

1. **Explicit handoff** - No assumptions about what smoke-test knows
2. **Mode awareness** - smoke-test adapts rubric based on available capabilities
3. **Evidence traceability** - Failures can be traced to specific handoff data
4. **Graceful degradation** - System provides value even when shadow unavailable

## Integration with Error Codes

The handoff manifest's `failure_reason` uses structured error codes from the shadow tool:

| Error Code | Meaning | Fallback Action |
|------------|---------|-----------------|
| `docker_not_running` | Docker daemon not started | Host-only mode |
| `docker_not_installed` | No container runtime | Host-only mode |
| `image_not_found` | Shadow image missing | Try build-image first |
| `build_failed` | Image build failed | Host-only mode |
| `create_failed` | Container creation failed | Host-only mode |

## Example Complete Handoff

```python
# shadow-operator creates shadow
result = shadow.create(
    local_sources=["~/repos/amplifier-core:microsoft/amplifier-core"],
    auto_preflight=True  # Default: checks prerequisites first
)

if result["success"]:
    # Full shadow mode
    delegate(
        agent="shadow-smoke-test",
        instruction=f"""
Validate shadow environment.

HANDOFF MANIFEST:
```yaml
shadow_id: {result["shadow_id"]}
shadow_available: true
local_sources:
  - path: ~/repos/amplifier-core
    github_repo: microsoft/amplifier-core
    snapshot_commit: {result["snapshot_commits"]["microsoft/amplifier-core"]}
test_context:
  project_type: python
fallback_mode: false
```
""",
        context_depth="none"
    )
else:
    # Fallback to host-only
    delegate(
        agent="shadow-smoke-test",
        instruction=f"""
Shadow unavailable - host-only validation.

HANDOFF MANIFEST:
```yaml
shadow_available: false
local_sources:
  - path: ~/repos/amplifier-core
    github_repo: microsoft/amplifier-core
fallback_mode: true
failure_reason: "{result['error']['code']}"
```

Use HOST-ONLY rubric.
""",
        context_depth="none"
    )
```
