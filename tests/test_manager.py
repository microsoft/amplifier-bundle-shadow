"""Tests for ShadowManager."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from amplifier_bundle_shadow.manager import ShadowManager
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
        assert (temp_shadow_home / "environments").exists()
    
    def test_list_environments_empty(self, manager):
        """Test list_environments returns empty list when no environments."""
        envs = manager.list_environments()
        assert envs == []
    
    def test_get_nonexistent(self, manager):
        """Test get returns None for nonexistent environment."""
        env = manager.get("nonexistent")
        assert env is None
    
    @pytest.mark.asyncio
    async def test_destroy_nonexistent_no_force(self, manager):
        """Test destroy doesn't raise for nonexistent when directory doesn't exist."""
        # When directory doesn't exist, destroy just tries to remove container
        # which is a no-op if container doesn't exist
        await manager.destroy("nonexistent", force=True)  # Should not raise
    
    @pytest.mark.asyncio
    async def test_destroy_all_empty(self, manager):
        """Test destroy_all returns 0 for empty environments."""
        count = await manager.destroy_all()
        assert count == 0
    
    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, manager):
        """Test create raises for duplicate environment name."""
        shadow_dir = manager.environments_dir / "test-dup"
        shadow_dir.mkdir(parents=True)
        
        with pytest.raises(ValueError) as exc_info:
            await manager.create(local_sources=["/tmp/test:microsoft/amplifier"], name="test-dup")
        
        assert "already exists" in str(exc_info.value)
    
    def test_runtime_detected(self, manager):
        """Test that container runtime is detected."""
        # Should have detected docker or podman (or raised ContainerNotFoundError)
        assert manager.runtime.runtime in ("docker", "podman")
