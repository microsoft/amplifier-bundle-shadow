"""Tests for repository management."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from amplifier_bundle_shadow.repos import RepoManager
from amplifier_bundle_shadow.models import RepoSpec


class TestRepoManager:
    """Tests for RepoManager."""
    
    @pytest.fixture
    def temp_staging_dir(self, tmp_path):
        """Create a temporary staging directory."""
        staging = tmp_path / "staging"
        staging.mkdir()
        return staging
    
    @pytest.fixture
    def repo_manager(self, temp_staging_dir):
        """Create a RepoManager with temporary directory."""
        return RepoManager(temp_staging_dir)
    
    def test_init_creates_directory(self, tmp_path):
        """Test that init creates the staging directory."""
        staging = tmp_path / "new_staging"
        assert not staging.exists()
        
        manager = RepoManager(staging)
        assert staging.exists()
    
    def test_get_staged_path(self, repo_manager):
        """Test _get_staged_path returns correct path."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        path = repo_manager._get_staged_path(spec)
        
        assert path == repo_manager.staging_dir / "microsoft" / "amplifier"
    
    def test_is_staged_false(self, repo_manager):
        """Test is_staged returns False for non-existent repos."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        assert repo_manager.is_staged(spec) is False
    
    def test_is_staged_true_git_dir(self, repo_manager):
        """Test is_staged returns True when .git exists."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        staged_path = repo_manager._get_staged_path(spec)
        staged_path.mkdir(parents=True)
        (staged_path / ".git").mkdir()
        
        assert repo_manager.is_staged(spec) is True
    
    def test_is_staged_true_bare(self, repo_manager):
        """Test is_staged returns True for bare repos (HEAD file)."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        staged_path = repo_manager._get_staged_path(spec)
        staged_path.mkdir(parents=True)
        (staged_path / "HEAD").touch()
        
        assert repo_manager.is_staged(spec) is True
    
    def test_cleanup_staged(self, repo_manager):
        """Test cleanup_staged removes the staged repo."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        staged_path = repo_manager._get_staged_path(spec)
        staged_path.mkdir(parents=True)
        (staged_path / "file.txt").touch()
        
        repo_manager.cleanup_staged(spec)
        assert not staged_path.exists()
    
    def test_cleanup_all_staged(self, repo_manager):
        """Test cleanup_all_staged removes all staged repos."""
        # Create some fake staged repos
        for name in ["repo1", "repo2"]:
            path = repo_manager.staging_dir / "org" / name
            path.mkdir(parents=True)
            (path / "file.txt").touch()
        
        repo_manager.cleanup_all_staged()
        
        # Directory should exist but be empty
        assert repo_manager.staging_dir.exists()
        assert list(repo_manager.staging_dir.iterdir()) == []
    
    @pytest.mark.asyncio
    async def test_ensure_staged_clones_new(self, repo_manager):
        """Test ensure_staged clones a new repo."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        
        with patch.object(repo_manager, '_git_clone', new_callable=AsyncMock) as mock_clone:
            await repo_manager.ensure_staged(spec, update=False)
            
            mock_clone.assert_called_once()
            args = mock_clone.call_args[0]
            assert args[0] == spec.url
    
    @pytest.mark.asyncio
    async def test_ensure_staged_fetches_existing(self, repo_manager):
        """Test ensure_staged fetches updates for existing repos."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        staged_path = repo_manager._get_staged_path(spec)
        staged_path.mkdir(parents=True)
        (staged_path / ".git").mkdir()
        
        with patch.object(repo_manager, '_git_fetch', new_callable=AsyncMock) as mock_fetch:
            await repo_manager.ensure_staged(spec, update=True)
            
            mock_fetch.assert_called_once_with(staged_path)
    
    @pytest.mark.asyncio
    async def test_ensure_staged_skip_fetch(self, repo_manager):
        """Test ensure_staged skips fetch when update=False."""
        spec = RepoSpec(org="microsoft", name="amplifier")
        staged_path = repo_manager._get_staged_path(spec)
        staged_path.mkdir(parents=True)
        (staged_path / ".git").mkdir()
        
        with patch.object(repo_manager, '_git_fetch', new_callable=AsyncMock) as mock_fetch:
            await repo_manager.ensure_staged(spec, update=False)
            
            mock_fetch.assert_not_called()
