"""Shared test fixtures for shadow environment tests."""

import subprocess
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


# Skip integration tests by default
def pytest_addoption(parser):
    """Add command line options for test categories."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that require containers",
    )
    parser.addoption(
        "--run-security",
        action="store_true",
        default=False,
        help="Run security tests that require a running shadow",
    )


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires containers)"
    )
    config.addinivalue_line(
        "markers", "security: mark test as security test (requires running shadow)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests based on markers and options."""
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(reason="need --run-integration option")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    if not config.getoption("--run-security"):
        skip_security = pytest.mark.skip(reason="need --run-security option")
        for item in items:
            if "security" in item.keywords:
                item.add_marker(skip_security)


# ============================================================================
# Git Repository Fixtures
# ============================================================================


@pytest.fixture
def temp_git_repo(tmp_path) -> Path:
    """Create a minimal git repository for testing.

    Returns a path to a git repo with:
    - Initial commit with README.md
    - Clean working tree
    """
    repo = tmp_path / "test-repo"
    repo.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    # Create initial commit
    (repo / "README.md").write_text("# Test Repository\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    return repo


@pytest.fixture
def dirty_git_repo(temp_git_repo) -> Path:
    """Git repository with uncommitted changes.

    Adds:
    - Modified README.md (tracked, modified)
    - new_file.py (untracked)
    - staged_file.txt (staged but not committed)
    """
    repo = temp_git_repo

    # Modify tracked file
    (repo / "README.md").write_text("# Test Repository\n\nModified content\n")

    # Add untracked file
    (repo / "new_file.py").write_text("# New file\nprint('hello')\n")

    # Add staged but uncommitted file
    (repo / "staged_file.txt").write_text("Staged content\n")
    subprocess.run(["git", "add", "staged_file.txt"], cwd=repo, capture_output=True)

    return repo


@pytest.fixture
def multi_repo_workspace(tmp_path) -> dict[str, Path]:
    """Create multiple git repos simulating Amplifier ecosystem.

    Returns dict with paths to:
    - amplifier-core (clean)
    - amplifier-foundation (dirty)
    - amplifier (clean)
    """
    repos = {}

    for name in ["amplifier-core", "amplifier-foundation", "amplifier"]:
        repo = tmp_path / name
        repo.mkdir()

        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        # Create initial commit with a Python file
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text('__version__ = "0.1.0"\n')
        (repo / "README.md").write_text(f"# {name}\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        repos[name] = repo

    # Make amplifier-foundation dirty
    foundation = repos["amplifier-foundation"]
    (foundation / "src" / "__init__.py").write_text('__version__ = "0.2.0-dev"\n')
    (foundation / "src" / "new_module.py").write_text("# New module\n")

    return repos


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_runtime():
    """Create a mock ContainerRuntime for unit tests."""
    runtime = MagicMock()
    runtime.runtime = "docker"
    runtime.exec = AsyncMock(return_value=(0, "", ""))
    runtime.run = AsyncMock(return_value="container-id-123")
    runtime.is_running = AsyncMock(return_value=True)
    runtime.stop = AsyncMock()
    runtime.remove = AsyncMock()
    runtime.exec_interactive = AsyncMock()
    runtime.copy_from = AsyncMock()
    runtime.copy_to = AsyncMock()
    return runtime


@pytest.fixture
def mock_gitea():
    """Create a mock GiteaClient for unit tests."""
    gitea = MagicMock()
    gitea.wait_ready = AsyncMock()
    gitea.create_org = AsyncMock()
    gitea.create_repo = AsyncMock()
    gitea.push_bundle = AsyncMock()
    return gitea


# ============================================================================
# Shadow Environment Fixtures (for integration tests)
# ============================================================================


@pytest.fixture
def shadow_home(tmp_path) -> Path:
    """Isolated shadow home directory for testing."""
    home = tmp_path / ".shadow"
    home.mkdir()
    (home / "environments").mkdir()
    return home


@pytest.fixture
def shadow_manager(shadow_home):
    """ShadowManager with isolated home directory.

    Note: For unit tests, use with mock_runtime.
    For integration tests, this creates a real manager.
    """
    from amplifier_bundle_shadow.manager import ShadowManager

    return ShadowManager(shadow_home=shadow_home)


@pytest.fixture
async def live_shadow_env(shadow_manager, temp_git_repo):
    """Create a real shadow environment for integration tests.

    Yields the environment, then destroys it on cleanup.
    Requires: --run-integration flag
    """
    # Create the shadow
    local_source = f"{temp_git_repo}:test/repo"
    env = await shadow_manager.create(
        name="test-shadow",
        local_sources=[local_source],
    )

    yield env

    # Cleanup
    try:
        await shadow_manager.destroy(env.shadow_id, force=True)
    except Exception:
        pass  # Best effort cleanup


# ============================================================================
# Helper Functions
# ============================================================================


def run_git(repo: Path, *args) -> subprocess.CompletedProcess:
    """Run a git command in a repository."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def get_git_status(repo: Path) -> str:
    """Get git status output for a repository."""
    result = run_git(repo, "status", "--porcelain")
    return result.stdout


def has_uncommitted_changes(repo: Path) -> bool:
    """Check if a repository has uncommitted changes."""
    return bool(get_git_status(repo).strip())


def get_head_sha(repo: Path) -> str:
    """Get the current HEAD commit SHA."""
    result = run_git(repo, "rev-parse", "HEAD")
    return result.stdout.strip()


# ============================================================================
# Assertions
# ============================================================================


class ShadowAssertions:
    """Custom assertions for shadow environment tests."""

    @staticmethod
    async def assert_url_rewritten(env, github_url: str, expected_gitea_pattern: str):
        """Assert that a GitHub URL is rewritten to Gitea."""
        exit_code, stdout, stderr = await env.exec(
            f'git config --global --get-regexp "url.*insteadOf" | grep "{github_url}"'
        )
        assert exit_code == 0, (
            f"URL {github_url} not rewritten. stdout={stdout}, stderr={stderr}"
        )
        assert expected_gitea_pattern in stdout, (
            f"Expected {expected_gitea_pattern} in {stdout}"
        )

    @staticmethod
    async def assert_file_exists_in_shadow(env, path: str):
        """Assert that a file exists inside the shadow container."""
        exit_code, _, _ = await env.exec(f"test -f {path}")
        assert exit_code == 0, f"File {path} does not exist in shadow"

    @staticmethod
    async def assert_file_contains(env, path: str, content: str):
        """Assert that a file in the shadow contains specific content."""
        exit_code, stdout, _ = await env.exec(f"cat {path}")
        assert exit_code == 0, f"Failed to read {path}"
        assert content in stdout, f"Expected '{content}' in {path}, got: {stdout}"


@pytest.fixture
def shadow_assert():
    """Provide shadow-specific assertions."""
    return ShadowAssertions
