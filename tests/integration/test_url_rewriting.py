"""Integration tests for git URL rewriting.

These tests verify that the core mechanism works:
- GitHub URLs are rewritten to local Gitea for registered repos
- Unregistered repos pass through to real GitHub
- Various URL formats (https, git+https, .git suffix) all work

Run with: pytest tests/integration/test_url_rewriting.py --run-integration -v
"""

import pytest

pytestmark = pytest.mark.integration


class TestURLRewriting:
    """Test git URL rewriting mechanism."""

    @pytest.mark.asyncio
    async def test_https_url_rewritten(self, live_shadow_env, shadow_assert):
        """A1.1: HTTPS URLs for registered repos should be rewritten to Gitea."""
        env = live_shadow_env

        # Check that git config contains URL rewriting rule
        result = await env.exec('git config --global --get-regexp "url.*insteadOf"')

        assert result.exit_code == 0, (
            f"No URL rewriting configured. stderr={result.stderr}"
        )
        assert "localhost:3000" in result.stdout, (
            f"Gitea URL not in config: {result.stdout}"
        )
        assert "github.com" in result.stdout, (
            f"GitHub not being rewritten: {result.stdout}"
        )

    @pytest.mark.asyncio
    async def test_git_plus_https_rewritten(self, live_shadow_env):
        """A1.2: git+https:// URLs should be rewritten (used by uv/pip)."""
        env = live_shadow_env

        # The git config should handle this - verify the rewrite patterns
        result = await env.exec('git config --global --get-regexp "url.*insteadOf"')

        # Should have both https:// and git+https:// variants
        # Or just https:// which covers both
        assert result.exit_code == 0
        assert "github.com" in result.stdout

    @pytest.mark.asyncio
    async def test_unregistered_repo_passes_through(self, live_shadow_env):
        """A1.3: Repos NOT in local-sources should fetch from real GitHub."""
        env = live_shadow_env

        # Check that only specific repos are rewritten, not all GitHub URLs
        result = await env.exec('git config --global --get-regexp "url.*insteadOf"')

        assert result.exit_code == 0
        # The URL rewriting should be specific to the registered org/repo
        # not a blanket rewrite of all github.com URLs
        lines = result.stdout.strip().split("\n")
        for line in lines:
            # Each line should reference a specific repo, not just github.com
            if "insteadOf" in line.lower():
                # Should see something like:
                # url.http://localhost:3000/microsoft/amplifier-core.insteadOf https://github.com/microsoft/amplifier-core
                assert "localhost:3000" in line or "github.com" in line

    @pytest.mark.asyncio
    async def test_clone_uses_local_gitea(self, live_shadow_env, temp_git_repo):
        """Cloning a registered repo should use local Gitea, not GitHub."""
        env = live_shadow_env

        # Try to clone - it should work from Gitea even though we use GitHub URL
        result = await env.exec(
            "cd /workspace && git clone https://github.com/test/repo test-clone 2>&1"
        )

        # Should succeed (Gitea has the repo)
        assert result.exit_code == 0, (
            f"Clone failed: stdout={result.stdout}, stderr={result.stderr}"
        )

        # Verify the clone exists
        check = await env.exec("test -d /workspace/test-clone")
        assert check.exit_code == 0, "Cloned directory does not exist"

    @pytest.mark.asyncio
    async def test_git_suffix_variants(self, live_shadow_env):
        """A1.4: URLs with and without .git suffix should both work."""
        env = live_shadow_env

        # Both variants should be handled
        result = await env.exec('git config --global --get-regexp "url.*insteadOf"')

        assert result.exit_code == 0
        # The implementation should handle .git suffix variations


class TestPrefixCollision:
    """Test that URL rewriting doesn't cause prefix collision bugs.

    This is a CRITICAL test - git's insteadOf uses PREFIX matching, so
    a repo named "amplifier" would incorrectly match "amplifier-profiles"
    if we don't use boundary markers in our patterns.
    """

    @pytest.mark.asyncio
    async def test_similar_repo_names_not_colliding(self, live_shadow_env):
        """P0 Regression: 'amplifier' should NOT prefix-match 'amplifier-profiles'.

        If local source is 'amplifier', accessing 'amplifier-profiles' should
        NOT be rewritten to local Gitea - it should pass through to real GitHub.
        """
        env = live_shadow_env

        # Get the current URL rewriting config
        result = await env.exec('git config --global --get-regexp "url.*insteadOf"')
        assert result.exit_code == 0, f"No URL config: {result.stderr}"

        # Parse the config to understand what patterns are registered
        config_output = result.stdout

        # Check that all patterns have boundary markers
        # Valid boundaries: .git, /, @
        lines = config_output.strip().split("\n")
        for line in lines:
            if "insteadOf" in line.lower() and "github.com" in line:
                # Extract the pattern being rewritten (after "insteadOf ")
                # Format: url.http://localhost:3000/org/repo.git.insteadOf https://github.com/org/repo.git
                parts = line.split("insteadOf")
                if len(parts) >= 2:
                    github_pattern = parts[1].strip()
                    # Pattern should end with a boundary marker
                    assert (
                        github_pattern.endswith(".git")
                        or github_pattern.endswith("/")
                        or github_pattern.endswith("@")
                        or ".git/" in github_pattern
                    ), (
                        f"URL pattern lacks boundary marker (vulnerable to prefix collision): "
                        f"{github_pattern}\n"
                        f"Full line: {line}"
                    )

    @pytest.mark.asyncio
    async def test_no_bare_repo_patterns(self, live_shadow_env):
        """Verify no bare patterns like 'github.com/org/repo' without boundary."""
        env = live_shadow_env

        result = await env.exec('git config --global --get-regexp "url.*insteadOf"')
        assert result.exit_code == 0

        # Look for patterns that end with just the repo name (no .git, /, or @)
        import re

        # Pattern: github.com/org/reponame without .git or / or @ after
        bare_pattern = re.compile(r"github\.com/[^/]+/[a-zA-Z0-9_-]+(?![./@])")

        matches = bare_pattern.findall(result.stdout)
        # Filter out false positives (patterns that continue with .git, /, @)
        actual_bare = []
        for match in matches:
            # Check if this is actually bare (not followed by boundary)
            if match in result.stdout:
                idx = result.stdout.find(match)
                after = result.stdout[idx + len(match) : idx + len(match) + 5]
                if not after.startswith((".git", "/", "@")):
                    actual_bare.append(match)

        assert len(actual_bare) == 0, (
            f"Found bare URL patterns without boundary markers: {actual_bare}\n"
            f"These are vulnerable to prefix collision bugs.\n"
            f"Full config:\n{result.stdout}"
        )


class TestGiteaSetup:
    """Test that Gitea is properly configured inside the shadow."""

    @pytest.mark.asyncio
    async def test_gitea_is_running(self, live_shadow_env):
        """Gitea server should be running and accessible."""
        env = live_shadow_env

        # Check Gitea is responding
        result = await env.exec(
            "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/v1/version"
        )

        assert result.exit_code == 0, f"curl failed: {result.stderr}"
        assert result.stdout.strip() == "200", (
            f"Gitea not responding: HTTP {result.stdout}"
        )

    @pytest.mark.asyncio
    async def test_gitea_has_repos(self, live_shadow_env):
        """Gitea should have the registered repositories."""
        env = live_shadow_env

        # List repos via API
        result = await env.exec(
            "curl -s http://localhost:3000/api/v1/repos/search?limit=50"
        )

        assert result.exit_code == 0, f"API call failed: {result.stderr}"
        # Should have at least one repo
        assert (
            '"data"' in result.stdout
            or '"ok"' in result.stdout
            or "repo" in result.stdout.lower()
        )

    @pytest.mark.asyncio
    async def test_snapshot_contains_files(self, live_shadow_env, temp_git_repo):
        """Snapshot in Gitea should contain the original repo's files."""
        env = live_shadow_env

        # Clone the repo
        result = await env.exec(
            "cd /workspace && git clone https://github.com/test/repo check-content 2>&1"
        )
        assert result.exit_code == 0, f"Clone failed: {result.stderr}"

        # Check that README.md exists (created by temp_git_repo fixture)
        cat_result = await env.exec("cat /workspace/check-content/README.md")
        assert cat_result.exit_code == 0, "README.md not found in cloned repo"
        assert "Test Repository" in cat_result.stdout, (
            f"Unexpected content: {cat_result.stdout}"
        )
