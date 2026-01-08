"""Tests for ShadowManager."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from amplifier_bundle_shadow.manager import ShadowManager, GITCONFIG_BASE
from amplifier_bundle_shadow.models import RepoSpec, ShadowStatus


class TestShadowManager:
    """Tests for ShadowManager."""
    
    @pytest.fixture
    def temp_shadow_home(self, tmp_path):
        """Create a temporary shadow home directory."""
        return tmp_path / ".shadow"
    
    @pytest.fixture
    def manager(self, temp_shadow_home):
        """Create a ShadowManager with temporary directory."""
        return ShadowManager(temp_shadow_home)
    
    def test_init_creates_directories(self, temp_shadow_home):
        """Test that init creates required directories."""
        manager = ShadowManager(temp_shadow_home)
        
        assert temp_shadow_home.exists()
        assert (temp_shadow_home / "staging").exists()
        assert (temp_shadow_home / "environments").exists()
    
    def test_list_environments_empty(self, manager):
        """Test list_environments returns empty list when no environments."""
        envs = manager.list_environments()
        assert envs == []
    
    def test_get_nonexistent(self, manager):
        """Test get returns None for nonexistent environment."""
        env = manager.get("nonexistent")
        assert env is None
    
    def test_destroy_nonexistent_raises(self, manager):
        """Test destroy raises for nonexistent environment."""
        with pytest.raises(ValueError):
            manager.destroy("nonexistent")
    
    def test_destroy_nonexistent_force(self, manager):
        """Test destroy with force=True doesn't raise for nonexistent."""
        manager.destroy("nonexistent", force=True)  # Should not raise
    
    def test_destroy_all_empty(self, manager):
        """Test destroy_all returns 0 for empty environments."""
        count = manager.destroy_all()
        assert count == 0
    
    def test_write_gitconfig(self, manager, temp_shadow_home):
        """Test _write_gitconfig creates correct file with URL rewrites."""
        shadow_dir = temp_shadow_home / "environments" / "test"
        shadow_dir.mkdir(parents=True)
        (shadow_dir / "home").mkdir()
        (shadow_dir / "repos" / "microsoft").mkdir(parents=True)
        
        # Create a local repo spec
        local_repos = [
            RepoSpec(org="microsoft", name="amplifier-core", local_path=Path("/tmp/amplifier-core"))
        ]
        
        manager._write_gitconfig(shadow_dir, local_repos)
        
        gitconfig_path = shadow_dir / "home" / ".gitconfig"
        assert gitconfig_path.exists()
        
        content = gitconfig_path.read_text()
        # Should have URL rewrite for the specific repo
        assert 'insteadOf = https://github.com/microsoft/amplifier-core' in content
        assert f'file://{shadow_dir}/repos/microsoft/amplifier-core.git' in content
    
    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, manager):
        """Test create raises for duplicate environment name."""
        shadow_dir = manager.environments_dir / "test-dup"
        shadow_dir.mkdir(parents=True)
        
        with pytest.raises(ValueError) as exc_info:
            await manager.create(local_sources=["/tmp/test:microsoft/amplifier"], name="test-dup")
        
        assert "already exists" in str(exc_info.value)


class TestGitconfigBase:
    """Tests for GITCONFIG_BASE content."""
    
    def test_gitconfig_base_has_user_config(self):
        """Test GITCONFIG_BASE has basic git user config."""
        assert '[user]' in GITCONFIG_BASE
        assert 'name = Shadow Environment' in GITCONFIG_BASE
        assert 'email = shadow@localhost' in GITCONFIG_BASE
