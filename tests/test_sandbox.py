"""Tests for sandbox backends."""

import platform
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from amplifier_bundle_shadow.sandbox import get_sandbox_backend, get_available_backends
from amplifier_bundle_shadow.sandbox.base import SandboxBackend


class TestSandboxFactory:
    """Tests for sandbox factory functions."""
    
    @pytest.fixture
    def temp_dirs(self, tmp_path):
        """Create temporary directories for sandbox."""
        shadow_dir = tmp_path / "shadow"
        shadow_dir.mkdir()
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()
        return shadow_dir, repos_dir
    
    def test_get_available_backends(self):
        """Test get_available_backends returns a list."""
        backends = get_available_backends()
        assert isinstance(backends, list)
        # Should have at least one on Linux or macOS
        if platform.system() in ("Linux", "Darwin"):
            # Might be empty if bwrap not installed
            pass
    
    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux only")
    def test_get_sandbox_backend_linux(self, temp_dirs):
        """Test getting sandbox backend on Linux."""
        shadow_dir, repos_dir = temp_dirs
        
        # Mock bubblewrap being available AND working
        with patch('amplifier_bundle_shadow.sandbox.factory._check_bubblewrap_works', return_value=True):
            backend = get_sandbox_backend(
                shadow_dir=shadow_dir,
                repos_dir=repos_dir,
                mode="auto",
            )
            assert backend.name == "Bubblewrap"
    
    def test_get_sandbox_backend_direct(self, temp_dirs):
        """Test getting direct sandbox backend."""
        shadow_dir, repos_dir = temp_dirs
        
        backend = get_sandbox_backend(
            shadow_dir=shadow_dir,
            repos_dir=repos_dir,
            mode="direct",
        )
        assert backend.name == "Direct"
    
    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_get_sandbox_backend_macos(self, temp_dirs):
        """Test getting sandbox backend on macOS."""
        shadow_dir, repos_dir = temp_dirs
        
        backend = get_sandbox_backend(
            shadow_dir=shadow_dir,
            repos_dir=repos_dir,
            mode="auto",
        )
        assert backend.name == "Seatbelt"
    
    def test_get_sandbox_backend_container_not_implemented(self, temp_dirs):
        """Test that container mode raises NotImplementedError."""
        shadow_dir, repos_dir = temp_dirs
        
        with pytest.raises(NotImplementedError):
            get_sandbox_backend(
                shadow_dir=shadow_dir,
                repos_dir=repos_dir,
                mode="container",
            )
    
    def test_get_sandbox_backend_invalid_mode(self, temp_dirs):
        """Test that invalid mode raises ValueError."""
        shadow_dir, repos_dir = temp_dirs
        
        with pytest.raises(ValueError):
            get_sandbox_backend(
                shadow_dir=shadow_dir,
                repos_dir=repos_dir,
                mode="invalid",
            )


class TestSandboxBackendBase:
    """Tests for SandboxBackend base class."""
    
    def test_get_default_env(self, tmp_path):
        """Test get_default_env returns expected variables."""
        # Create a concrete implementation for testing
        class TestBackend(SandboxBackend):
            @property
            def name(self):
                return "Test"
            
            @property
            def is_available(self):
                return True
            
            async def exec(self, command, env, cwd="/workspace", timeout=300):
                pass
            
            async def shell(self, env, cwd="/workspace"):
                pass
        
        shadow_dir = tmp_path / "shadow"
        repos_dir = tmp_path / "repos"
        
        backend = TestBackend(shadow_dir, repos_dir)
        env = backend.get_default_env("test-123")
        
        assert env["HOME"] == "/home/shadow"
        assert env["AMPLIFIER_HOME"] == "/home/shadow/.amplifier"
        assert env["SHADOW_ENV_ID"] == "test-123"
        assert env["SHADOW_ENV_ACTIVE"] == "true"
        assert "/usr/local/bin" in env["PATH"]
