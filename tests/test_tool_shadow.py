"""Tests for shadow tool module enhancements."""

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_bundle_shadow.environment import ShadowEnvironment
from amplifier_bundle_shadow.models import ExecResult, RepoSpec, ShadowStatus


# Import the tool module
@pytest.fixture
def shadow_tool():
    """Create a ShadowTool instance for testing."""
    from amplifier_module_tool_shadow import ShadowTool

    return ShadowTool()


@pytest.fixture
def mock_shadow_env(tmp_path):
    """Create a mock ShadowEnvironment for testing."""
    mock_runtime = MagicMock()
    mock_runtime.exec = AsyncMock(return_value=(0, "", ""))
    mock_runtime.is_running = AsyncMock(return_value=True)

    shadow_dir = tmp_path / "shadow-test"
    shadow_dir.mkdir()
    (shadow_dir / "workspace").mkdir()
    (shadow_dir / "snapshots").mkdir()

    env = ShadowEnvironment(
        shadow_id="test-shadow-123",
        container_name="shadow-test-123",
        repos=[
            RepoSpec(
                org="microsoft",
                name="amplifier",
                local_path=tmp_path / "amplifier",
                snapshot_commit="abc123def456",
            )
        ],
        shadow_dir=shadow_dir,
        runtime=mock_runtime,
        created_at=datetime.now(),
        status=ShadowStatus.READY,
        env_vars={"ANTHROPIC_API_KEY": "test-key"},
    )

    return env


@pytest.fixture
def mock_manager(mock_shadow_env):
    """Create a mock ShadowManager."""
    manager = MagicMock()
    manager.create = AsyncMock(return_value=mock_shadow_env)
    manager.add_source = AsyncMock(return_value=mock_shadow_env)
    manager.get = MagicMock(return_value=mock_shadow_env)
    manager.destroy = AsyncMock()
    manager.list_environments = MagicMock(return_value=[mock_shadow_env])
    return manager


# ============================================================================
# Auto-verification tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_with_auto_verification_success(shadow_tool, mock_manager):
    """Test create with verify=True returns verification results when test passes."""
    # Setup mock environment
    mock_env = mock_manager.create.return_value
    mock_env.repos[0].snapshot_commit = "abc123def456"

    # Mock exec to return matching commit
    mock_env.exec = AsyncMock(
        return_value=ExecResult(exit_code=0, stdout="abc123def456\n", stderr="")
    )

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": True,
            }
        )

    # Verify result structure
    assert result.output is not None
    assert result.error is None
    assert result.output["shadow_id"] == "test-shadow-123"
    assert result.output["ready"] is True
    assert "verification" in result.output

    # Verify verification details
    verification = result.output["verification"]
    assert verification["status"] == "PASSED"
    assert verification["smoke_test_passed"] is True
    assert len(verification["issues"]) == 0
    assert "commit matches" in verification["evidence"]


@pytest.mark.asyncio
async def test_create_with_auto_verification_failure(shadow_tool, mock_manager):
    """Test create with verify=True when smoke test fails."""
    # Setup mock environment
    mock_env = mock_manager.create.return_value
    mock_env.repos[0].snapshot_commit = "abc123def456"

    # Mock exec to return different commit (mismatch)
    mock_env.exec = AsyncMock(
        return_value=ExecResult(exit_code=0, stdout="different1234\n", stderr="")
    )

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": True,
            }
        )

    # Verify result structure
    assert result.output is not None
    assert result.error is None
    assert result.output["ready"] is False
    assert "verification" in result.output

    # Verify verification details
    verification = result.output["verification"]
    assert verification["status"] == "FAILED"
    assert verification["smoke_test_passed"] is False
    assert len(verification["issues"]) > 0
    assert any("mismatch" in issue.lower() for issue in verification["issues"])


@pytest.mark.asyncio
async def test_create_with_verification_clone_failure(shadow_tool, mock_manager):
    """Test create with verify=True when git clone fails."""
    # Setup mock environment
    mock_env = mock_manager.create.return_value
    mock_env.repos[0].snapshot_commit = "abc123def456"

    # Mock exec to fail (clone error)
    mock_env.exec = AsyncMock(
        return_value=ExecResult(
            exit_code=128, stdout="", stderr="fatal: repository not found"
        )
    )

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": True,
            }
        )

    # Verify result structure
    assert result.output is not None
    assert result.output["ready"] is False
    assert "verification" in result.output

    # Verify verification details
    verification = result.output["verification"]
    assert verification["status"] == "FAILED"
    assert verification["smoke_test_passed"] is False
    assert any("Failed to clone" in issue for issue in verification["issues"])


@pytest.mark.asyncio
async def test_create_without_verification(shadow_tool, mock_manager):
    """Test create with verify=False skips smoke test."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": False,
            }
        )

    # Verify result structure
    assert result.output is not None
    assert result.error is None
    assert result.output["ready"] is True  # No verification, assume ready
    assert "verification" not in result.output


@pytest.mark.asyncio
async def test_create_with_verification_exception(shadow_tool, mock_manager):
    """Test create with verify=True when smoke test raises exception."""
    # Setup mock environment
    mock_env = mock_manager.create.return_value
    mock_env.repos[0].snapshot_commit = "abc123def456"

    # Mock exec to raise exception
    mock_env.exec = AsyncMock(side_effect=Exception("Network timeout"))

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": True,
            }
        )

    # Verify result structure
    assert result.output is not None
    assert result.output["ready"] is False
    assert "verification" in result.output

    # Verify verification details
    verification = result.output["verification"]
    assert verification["status"] == "FAILED"
    assert any("Smoke test error" in issue for issue in verification["issues"])


@pytest.mark.asyncio
async def test_create_with_verification_no_repos(shadow_tool, mock_manager):
    """Test create with verify=True when no repos exist."""
    # Setup mock environment with no repos
    mock_env = mock_manager.create.return_value
    mock_env.repos = []

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": True,
            }
        )

    # Should still create but mark as not ready due to no repos to verify
    assert result.output is not None
    assert (
        result.output["ready"] is True
    )  # No repos means nothing to verify, assume ready


# ============================================================================
# Required env vars validation tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_with_required_env_vars_present(shadow_tool, mock_manager):
    """Test create succeeds when required env vars are present."""
    with patch.dict(os.environ, {"MY_API_KEY": "secret123", "MY_TOKEN": "token456"}):
        with patch.object(shadow_tool, "manager", mock_manager):
            result = await shadow_tool.execute(
                {
                    "operation": "create",
                    "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                    "required_env_vars": ["MY_API_KEY", "MY_TOKEN"],
                    "verify": False,
                }
            )

    # Verify success
    assert result.output is not None
    assert result.error is None
    assert result.output["shadow_id"] == "test-shadow-123"


@pytest.mark.asyncio
async def test_create_with_required_env_vars_missing(shadow_tool, mock_manager):
    """Test create fails when required env vars are missing."""
    # Ensure env vars are NOT set
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(shadow_tool, "manager", mock_manager):
            result = await shadow_tool.execute(
                {
                    "operation": "create",
                    "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                    "required_env_vars": ["MISSING_KEY", "ANOTHER_MISSING"],
                    "verify": False,
                }
            )

    # Verify failure
    assert result.output is None
    assert result.error is not None
    assert "Missing required environment variables" in result.error["message"]
    assert "missing_vars" in result.error
    assert "MISSING_KEY" in result.error["missing_vars"]
    assert "ANOTHER_MISSING" in result.error["missing_vars"]
    assert "instructions" in result.error


@pytest.mark.asyncio
async def test_create_with_required_env_vars_partial_missing(shadow_tool, mock_manager):
    """Test create fails when some required env vars are missing."""
    with patch.dict(os.environ, {"PRESENT_KEY": "value"}, clear=True):
        with patch.object(shadow_tool, "manager", mock_manager):
            result = await shadow_tool.execute(
                {
                    "operation": "create",
                    "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                    "required_env_vars": ["PRESENT_KEY", "MISSING_KEY"],
                    "verify": False,
                }
            )

    # Verify failure
    assert result.output is None
    assert result.error is not None
    assert "MISSING_KEY" in result.error["missing_vars"]
    assert "PRESENT_KEY" not in result.error["missing_vars"]


@pytest.mark.asyncio
async def test_create_without_required_env_vars(shadow_tool, mock_manager):
    """Test create succeeds when no required env vars specified."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "create",
                "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                "verify": False,
            }
        )

    # Verify success
    assert result.output is not None
    assert result.error is None


# ============================================================================
# exec_batch tests
# ============================================================================


@pytest.mark.asyncio
async def test_exec_batch_all_success(shadow_tool, mock_manager):
    """Test exec_batch with all commands succeeding."""
    mock_env = mock_manager.get.return_value

    # Mock exec to always succeed
    exec_results = [
        ExecResult(exit_code=0, stdout="output1", stderr=""),
        ExecResult(exit_code=0, stdout="output2", stderr=""),
        ExecResult(exit_code=0, stdout="output3", stderr=""),
    ]
    mock_env.exec = AsyncMock(side_effect=exec_results)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": ["echo test1", "echo test2", "echo test3"],
                "fail_fast": True,
            }
        )

    # Verify result
    assert result.output is not None
    assert result.error is None
    assert result.output["success"] is True
    assert result.output["failed_at"] is None
    assert len(result.output["steps"]) == 3

    # Verify each step
    for i, step in enumerate(result.output["steps"]):
        assert step["exit_code"] == 0
        assert step["stdout"] == f"output{i + 1}"
        assert step["command"] == f"echo test{i + 1}"


@pytest.mark.asyncio
async def test_exec_batch_fail_fast_stops_on_error(shadow_tool, mock_manager):
    """Test exec_batch stops at first failure when fail_fast=True."""
    mock_env = mock_manager.get.return_value

    # Mock exec: first succeeds, second fails
    exec_results = [
        ExecResult(exit_code=0, stdout="output1", stderr=""),
        ExecResult(exit_code=1, stdout="", stderr="error message"),
        # Third command should not be executed
    ]
    mock_env.exec = AsyncMock(side_effect=exec_results)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": ["echo test1", "false", "echo test3"],
                "fail_fast": True,
            }
        )

    # Verify result
    assert result.output is not None
    assert result.error is not None
    assert result.output["success"] is False
    assert result.output["failed_at"] == 1  # Second command (index 1)
    assert len(result.output["steps"]) == 2  # Only 2 commands executed

    # Verify error message
    assert "step 1" in result.error["message"]


@pytest.mark.asyncio
async def test_exec_batch_continues_on_error_when_fail_fast_false(
    shadow_tool, mock_manager
):
    """Test exec_batch continues after error when fail_fast=False."""
    mock_env = mock_manager.get.return_value

    # Mock exec: second fails, but continue to third
    exec_results = [
        ExecResult(exit_code=0, stdout="output1", stderr=""),
        ExecResult(exit_code=1, stdout="", stderr="error message"),
        ExecResult(exit_code=0, stdout="output3", stderr=""),
    ]
    mock_env.exec = AsyncMock(side_effect=exec_results)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": ["echo test1", "false", "echo test3"],
                "fail_fast": False,
            }
        )

    # Verify result
    assert result.output is not None
    assert result.error is not None  # Still error because a command failed
    assert result.output["success"] is False
    assert result.output["failed_at"] is None  # fail_fast=False, so no specific index
    assert len(result.output["steps"]) == 3  # All 3 commands executed

    # Verify steps
    assert result.output["steps"][0]["exit_code"] == 0
    assert result.output["steps"][1]["exit_code"] == 1
    assert result.output["steps"][2]["exit_code"] == 0


@pytest.mark.asyncio
async def test_exec_batch_default_fail_fast_true(shadow_tool, mock_manager):
    """Test exec_batch defaults to fail_fast=True."""
    mock_env = mock_manager.get.return_value

    # Mock exec: first succeeds, second fails
    exec_results = [
        ExecResult(exit_code=0, stdout="output1", stderr=""),
        ExecResult(exit_code=1, stdout="", stderr="error"),
    ]
    mock_env.exec = AsyncMock(side_effect=exec_results)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": ["echo test1", "false", "echo test3"],
                # No fail_fast specified, should default to True
            }
        )

    # Verify stops at failure
    assert len(result.output["steps"]) == 2
    assert result.output["failed_at"] == 1


@pytest.mark.asyncio
async def test_exec_batch_missing_shadow_id(shadow_tool, mock_manager):
    """Test exec_batch fails when shadow_id is missing."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "commands": ["echo test"],
            }
        )

    assert result.output is None
    assert result.error is not None
    assert "shadow_id is required" in result.error["message"]


@pytest.mark.asyncio
async def test_exec_batch_missing_commands(shadow_tool, mock_manager):
    """Test exec_batch fails when commands are missing."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
            }
        )

    assert result.output is None
    assert result.error is not None
    assert "commands parameter is required" in result.error["message"]


@pytest.mark.asyncio
async def test_exec_batch_invalid_commands_type(shadow_tool, mock_manager):
    """Test exec_batch fails when commands is not an array."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": "not an array",
            }
        )

    assert result.output is None
    assert result.error is not None
    assert "must be an array" in result.error["message"]


@pytest.mark.asyncio
async def test_exec_batch_container_not_running(shadow_tool, mock_manager):
    """Test exec_batch fails when container is not running."""
    mock_env = mock_manager.get.return_value
    mock_env.is_running = AsyncMock(return_value=False)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": ["echo test"],
            }
        )

    assert result.output is None
    assert result.error is not None
    assert "Container not running" in result.error["message"]


@pytest.mark.asyncio
async def test_exec_batch_timeout_parameter(shadow_tool, mock_manager):
    """Test exec_batch respects timeout parameter."""
    mock_env = mock_manager.get.return_value
    mock_env.exec = AsyncMock(
        return_value=ExecResult(exit_code=0, stdout="output", stderr="")
    )

    with patch.object(shadow_tool, "manager", mock_manager):
        await shadow_tool.execute(
            {
                "operation": "exec_batch",
                "shadow_id": "test-shadow-123",
                "commands": ["echo test"],
                "timeout": 60,
            }
        )

    # Verify timeout was passed to exec
    mock_env.exec.assert_called_once()
    assert mock_env.exec.call_args.kwargs["timeout"] == 60


# ============================================================================
# health_check tests
# ============================================================================


@pytest.mark.asyncio
async def test_status_with_health_check(shadow_tool, mock_manager):
    """Test status with health_check=True returns diagnostics."""
    mock_env = mock_manager.get.return_value

    # Mock health check commands
    exec_results = {
        "curl -sf http://localhost:3000/api/v1/version": ExecResult(
            exit_code=0, stdout='{"version": "1.0"}', stderr=""
        ),
        'git config --get-regexp "url.*insteadOf"': ExecResult(
            exit_code=0, stdout="url.insteadof config", stderr=""
        ),
        "test -n \"${ANTHROPIC_API_KEY}\" && echo 'set'": ExecResult(
            exit_code=0, stdout="set", stderr=""
        ),
    }

    def exec_side_effect(command, **kwargs):
        for cmd_pattern, result in exec_results.items():
            if cmd_pattern in command:
                return result
        return ExecResult(exit_code=1, stdout="", stderr="not found")

    mock_env.exec = AsyncMock(side_effect=exec_side_effect)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": True,
            }
        )

    # Verify result contains health diagnostics
    assert result.output is not None
    assert result.error is None
    assert "health" in result.output

    health = result.output["health"]
    assert health["container_running"] is True
    assert health["gitea_accessible"] is True
    assert health["git_config_valid"] is True
    assert len(health["env_vars_present"]) > 0
    assert "ANTHROPIC_API_KEY" in health["env_vars_present"]
    assert len(health["issues"]) == 0


@pytest.mark.asyncio
async def test_status_without_health_check(shadow_tool, mock_manager):
    """Test status with health_check=False omits health diagnostics."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": False,
            }
        )

    # Verify no health field in output
    assert result.output is not None
    assert result.error is None
    assert "health" not in result.output


@pytest.mark.asyncio
async def test_status_health_check_default_false(shadow_tool, mock_manager):
    """Test status defaults to health_check=False."""
    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
            }
        )

    # Verify no health field in output by default
    assert result.output is not None
    assert "health" not in result.output


@pytest.mark.asyncio
async def test_status_health_check_container_not_running(shadow_tool, mock_manager):
    """Test status health check when container is not running."""
    mock_env = mock_manager.get.return_value
    mock_env.is_running = AsyncMock(return_value=False)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": True,
            }
        )

    # Verify health diagnostics show container issue
    assert result.output is not None
    health = result.output["health"]
    assert health["container_running"] is False
    assert "Container is not running" in health["issues"]
    # Other checks should not run if container is down
    assert health["gitea_accessible"] is False
    assert health["git_config_valid"] is False


@pytest.mark.asyncio
async def test_status_health_check_gitea_not_accessible(shadow_tool, mock_manager):
    """Test status health check when Gitea is not accessible."""
    mock_env = mock_manager.get.return_value

    def exec_side_effect(command, **kwargs):
        if "curl" in command and "3000" in command:
            return ExecResult(exit_code=7, stdout="", stderr="Connection refused")
        return ExecResult(exit_code=0, stdout="ok", stderr="")

    mock_env.exec = AsyncMock(side_effect=exec_side_effect)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": True,
            }
        )

    # Verify health diagnostics show Gitea issue
    health = result.output["health"]
    assert health["gitea_accessible"] is False
    assert any("Gitea" in issue for issue in health["issues"])


@pytest.mark.asyncio
async def test_status_health_check_git_config_invalid(shadow_tool, mock_manager):
    """Test status health check when git config is invalid."""
    mock_env = mock_manager.get.return_value

    def exec_side_effect(command, **kwargs):
        if "git config" in command:
            return ExecResult(exit_code=1, stdout="", stderr="no config found")
        return ExecResult(exit_code=0, stdout="ok", stderr="")

    mock_env.exec = AsyncMock(side_effect=exec_side_effect)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": True,
            }
        )

    # Verify health diagnostics show git config issue
    health = result.output["health"]
    assert health["git_config_valid"] is False
    assert any("Git URL rewriting" in issue for issue in health["issues"])


@pytest.mark.asyncio
async def test_status_health_check_no_api_keys(shadow_tool, mock_manager):
    """Test status health check when no API keys are found."""
    mock_env = mock_manager.get.return_value

    def exec_side_effect(command, **kwargs):
        # All env var checks fail
        if "test -n" in command:
            return ExecResult(exit_code=1, stdout="", stderr="")
        return ExecResult(exit_code=0, stdout="ok", stderr="")

    mock_env.exec = AsyncMock(side_effect=exec_side_effect)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": True,
            }
        )

    # Verify health diagnostics show API key issue
    health = result.output["health"]
    assert len(health["env_vars_present"]) == 0
    assert any("No API keys" in issue for issue in health["issues"])


@pytest.mark.asyncio
async def test_status_health_check_exception_handling(shadow_tool, mock_manager):
    """Test status health check gracefully handles exceptions."""
    mock_env = mock_manager.get.return_value

    def exec_side_effect(command, **kwargs):
        if "curl" in command:
            raise Exception("Network error")
        return ExecResult(exit_code=0, stdout="ok", stderr="")

    mock_env.exec = AsyncMock(side_effect=exec_side_effect)

    with patch.object(shadow_tool, "manager", mock_manager):
        result = await shadow_tool.execute(
            {
                "operation": "status",
                "shadow_id": "test-shadow-123",
                "health_check": True,
            }
        )

    # Verify health diagnostics show error but don't crash
    health = result.output["health"]
    assert any("check failed" in issue.lower() for issue in health["issues"])


# ============================================================================
# Integration tests combining features
# ============================================================================


@pytest.mark.asyncio
async def test_create_with_all_features_combined(shadow_tool, mock_manager):
    """Test create with verification, required env vars, and auto-passthrough."""
    mock_env = mock_manager.create.return_value
    mock_env.repos[0].snapshot_commit = "abc123"

    # Mock successful verification
    mock_env.exec = AsyncMock(
        return_value=ExecResult(exit_code=0, stdout="abc123\n", stderr="")
    )

    with patch.dict(os.environ, {"REQUIRED_KEY": "value", "ANTHROPIC_API_KEY": "key"}):
        with patch.object(shadow_tool, "manager", mock_manager):
            result = await shadow_tool.execute(
                {
                    "operation": "create",
                    "local_sources": ["/tmp/test-repo:microsoft/amplifier"],
                    "verify": True,
                    "required_env_vars": ["REQUIRED_KEY"],
                }
            )

    # Verify all features worked
    assert result.output is not None
    assert result.error is None
    assert result.output["ready"] is True
    assert result.output["verification"]["status"] == "PASSED"
    assert "ANTHROPIC_API_KEY" in result.output["env_vars_passed"]
