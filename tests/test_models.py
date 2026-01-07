"""Tests for core models."""

import pytest

from amplifier_bundle_shadow.models import RepoSpec, ExecResult, ShadowStatus


class TestRepoSpec:
    """Tests for RepoSpec parsing and properties."""
    
    def test_parse_simple(self):
        """Test parsing simple org/repo format."""
        spec = RepoSpec.parse("microsoft/amplifier")
        assert spec.org == "microsoft"
        assert spec.name == "amplifier"
        assert spec.branch is None
    
    def test_parse_with_branch(self):
        """Test parsing org/repo@branch format."""
        spec = RepoSpec.parse("microsoft/amplifier-core@feature-branch")
        assert spec.org == "microsoft"
        assert spec.name == "amplifier-core"
        assert spec.branch == "feature-branch"
    
    def test_parse_https_url(self):
        """Test parsing full HTTPS URL."""
        spec = RepoSpec.parse("https://github.com/microsoft/amplifier")
        assert spec.org == "microsoft"
        assert spec.name == "amplifier"
        assert spec.branch is None
    
    def test_parse_https_url_with_git(self):
        """Test parsing HTTPS URL with .git suffix."""
        spec = RepoSpec.parse("https://github.com/microsoft/amplifier.git")
        assert spec.org == "microsoft"
        assert spec.name == "amplifier"
    
    def test_parse_https_url_with_branch(self):
        """Test parsing HTTPS URL with branch."""
        spec = RepoSpec.parse("https://github.com/microsoft/amplifier@main")
        assert spec.org == "microsoft"
        assert spec.name == "amplifier"
        assert spec.branch == "main"
    
    def test_parse_invalid(self):
        """Test that invalid specs raise ValueError."""
        with pytest.raises(ValueError):
            RepoSpec.parse("invalid")
        
        with pytest.raises(ValueError):
            RepoSpec.parse("no-slash")
    
    def test_full_name(self):
        """Test full_name property."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        assert spec.full_name == "microsoft/amplifier"
    
    def test_url(self):
        """Test url property."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        assert spec.url == "https://github.com/microsoft/amplifier.git"
    
    def test_display_name(self):
        """Test display_name property."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        assert spec.display_name == "microsoft/amplifier"
        
        spec_with_branch = RepoSpec(org="microsoft", name="amplifier", branch="main")
        assert spec_with_branch.display_name == "microsoft/amplifier@main"


class TestExecResult:
    """Tests for ExecResult."""
    
    def test_success(self):
        """Test success property."""
        result = ExecResult(exit_code=0, stdout="output", stderr="")
        assert result.success is True
        
        result = ExecResult(exit_code=1, stdout="", stderr="error")
        assert result.success is False
    
    def test_raise_on_error_success(self):
        """Test that raise_on_error does nothing on success."""
        result = ExecResult(exit_code=0, stdout="output", stderr="")
        result.raise_on_error()  # Should not raise
    
    def test_raise_on_error_failure(self):
        """Test that raise_on_error raises on failure."""
        result = ExecResult(exit_code=1, stdout="", stderr="some error")
        with pytest.raises(RuntimeError) as exc_info:
            result.raise_on_error("Custom message")
        
        assert "Custom message" in str(exc_info.value)
        assert "some error" in str(exc_info.value)


class TestShadowStatus:
    """Tests for ShadowStatus enum."""
    
    def test_values(self):
        """Test enum values."""
        assert ShadowStatus.READY.value == "ready"
        assert ShadowStatus.ERROR.value == "error"
        assert ShadowStatus.DESTROYED.value == "destroyed"
