"""Tests for ShadowManager."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from amplifier_bundle_shadow.manager import ShadowManager, GITCONFIG_TEMPLATE, HOSTS_TEMPLATE
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
        """Test _write_gitconfig creates correct file."""
        shadow_dir = temp_shadow_home / "environments" / "test"
        shadow_dir.mkdir(parents=True)
        (shadow_dir / "home").mkdir()
        (shadow_dir / "repos" / "github.com").mkdir(parents=True)
        
        manager._write_gitconfig(shadow_dir)
        
        gitconfig_path = shadow_dir / "home" / ".gitconfig"
        assert gitconfig_path.exists()
        
        content = gitconfig_path.read_text()
        assert 'insteadOf = https://github.com/' in content
        # The gitconfig should contain the actual path to the repos directory
        assert f'file://{shadow_dir}/repos/github.com/' in content
    
    def test_write_hosts(self, manager, temp_shadow_home):
        """Test _write_hosts creates correct file."""
        shadow_dir = temp_shadow_home / "environments" / "test"
        shadow_dir.mkdir(parents=True)
        
        manager._write_hosts(shadow_dir)
        
        hosts_path = shadow_dir / "hosts"
        assert hosts_path.exists()
        
        content = hosts_path.read_text()
        assert '127.0.0.1 github.com' in content
        assert '127.0.0.1 api.github.com' in content
    
    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, manager):
        """Test create raises for duplicate environment name."""
        shadow_dir = manager.environments_dir / "test-dup"
        shadow_dir.mkdir(parents=True)
        
        with pytest.raises(ValueError) as exc_info:
            await manager.create(repos=["microsoft/amplifier"], name="test-dup")
        
        assert "already exists" in str(exc_info.value)


class TestShadowManagerTemplates:
    """Tests for template content."""
    
    def test_gitconfig_template_has_url_rewrite(self):
        """Test GITCONFIG_TEMPLATE has URL rewrite rules."""
        assert 'insteadOf = https://github.com/' in GITCONFIG_TEMPLATE
        assert 'insteadOf = git@github.com:' in GITCONFIG_TEMPLATE
        assert 'file:///repos/github.com/' in GITCONFIG_TEMPLATE
    
    def test_hosts_template_blocks_github(self):
        """Test HOSTS_TEMPLATE blocks GitHub domains."""
        assert '127.0.0.1 github.com' in HOSTS_TEMPLATE
        assert '127.0.0.1 api.github.com' in HOSTS_TEMPLATE
        assert '127.0.0.1 raw.githubusercontent.com' in HOSTS_TEMPLATE
