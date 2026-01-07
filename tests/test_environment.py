"""Tests for ShadowEnvironment."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from amplifier_bundle_shadow.environment import ShadowEnvironment
from amplifier_bundle_shadow.models import RepoSpec, ShadowStatus, ChangedFile


class TestShadowEnvironment:
    """Tests for ShadowEnvironment."""
    
    @pytest.fixture
    def mock_backend(self):
        """Create a mock sandbox backend."""
        backend = MagicMock()
        backend.name = "MockBackend"
        backend.get_default_env.return_value = {
            "HOME": "/home/shadow",
            "SHADOW_ENV_ID": "test-123",
        }
        return backend
    
    @pytest.fixture
    def temp_shadow_dir(self, tmp_path):
        """Create a temporary shadow directory with structure."""
        shadow_dir = tmp_path / "shadow-test"
        (shadow_dir / "workspace").mkdir(parents=True)
        (shadow_dir / "home").mkdir()
        (shadow_dir / "repos" / "github.com").mkdir(parents=True)
        return shadow_dir
    
    @pytest.fixture
    def environment(self, temp_shadow_dir, mock_backend):
        """Create a ShadowEnvironment for testing."""
        return ShadowEnvironment(
            shadow_id="test-123",
            repos=[RepoSpec(org="microsoft", name="amplifier")],
            shadow_dir=temp_shadow_dir,
            backend=mock_backend,
            created_at=datetime.now(),
        )
    
    def test_workspace_dir(self, environment, temp_shadow_dir):
        """Test workspace_dir property."""
        assert environment.workspace_dir == temp_shadow_dir / "workspace"
    
    def test_home_dir(self, environment, temp_shadow_dir):
        """Test home_dir property."""
        assert environment.home_dir == temp_shadow_dir / "home"
    
    def test_repos_dir(self, environment, temp_shadow_dir):
        """Test repos_dir property."""
        assert environment.repos_dir == temp_shadow_dir / "repos" / "github.com"
    
    def test_to_info(self, environment):
        """Test to_info returns correct data."""
        info = environment.to_info()
        
        assert info.shadow_id == "test-123"
        assert info.mode == "MockBackend"
        assert info.status == "ready"
        assert "microsoft/amplifier" in info.repos
    
    @pytest.mark.asyncio
    async def test_exec_calls_backend(self, environment, mock_backend):
        """Test exec delegates to backend."""
        mock_backend.exec = AsyncMock(return_value=MagicMock(
            exit_code=0, stdout="output", stderr=""
        ))
        
        result = await environment.exec("echo test")
        
        mock_backend.exec.assert_called_once()
        assert "echo test" in str(mock_backend.exec.call_args)
    
    def test_snapshot_baseline(self, environment):
        """Test snapshot_baseline records file hashes."""
        # Create some files
        (environment.workspace_dir / "file1.txt").write_text("content1")
        (environment.workspace_dir / "file2.txt").write_text("content2")
        
        environment.snapshot_baseline()
        
        assert len(environment._baseline_hashes) == 2
        assert "file1.txt" in environment._baseline_hashes
        assert "file2.txt" in environment._baseline_hashes
    
    def test_diff_no_changes(self, environment):
        """Test diff returns empty when no changes."""
        (environment.workspace_dir / "file.txt").write_text("content")
        environment.snapshot_baseline()
        
        changes = environment.diff()
        assert changes == []
    
    def test_diff_added_file(self, environment):
        """Test diff detects added files."""
        environment.snapshot_baseline()
        
        # Add a file after baseline
        (environment.workspace_dir / "new.txt").write_text("new content")
        
        changes = environment.diff()
        assert len(changes) == 1
        assert changes[0].change_type == "added"
        assert "new.txt" in changes[0].path
    
    def test_diff_modified_file(self, environment):
        """Test diff detects modified files."""
        file_path = environment.workspace_dir / "file.txt"
        file_path.write_text("original")
        environment.snapshot_baseline()
        
        # Modify the file
        file_path.write_text("modified")
        
        changes = environment.diff()
        assert len(changes) == 1
        assert changes[0].change_type == "modified"
    
    def test_diff_deleted_file(self, environment):
        """Test diff detects deleted files."""
        file_path = environment.workspace_dir / "file.txt"
        file_path.write_text("content")
        environment.snapshot_baseline()
        
        # Delete the file
        file_path.unlink()
        
        changes = environment.diff()
        assert len(changes) == 1
        assert changes[0].change_type == "deleted"
    
    def test_extract_file(self, environment, tmp_path):
        """Test extract copies file from sandbox to host."""
        # Create file in workspace
        (environment.workspace_dir / "source.txt").write_text("test content")
        
        dest = tmp_path / "dest.txt"
        bytes_copied = environment.extract("/workspace/source.txt", str(dest))
        
        assert dest.exists()
        assert dest.read_text() == "test content"
        assert bytes_copied == len("test content")
    
    def test_extract_file_not_found(self, environment, tmp_path):
        """Test extract raises for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            environment.extract("/workspace/nonexistent.txt", str(tmp_path / "dest.txt"))
    
    def test_extract_invalid_path(self, environment, tmp_path):
        """Test extract raises for invalid sandbox path."""
        with pytest.raises(ValueError):
            environment.extract("/invalid/path.txt", str(tmp_path / "dest.txt"))
    
    def test_inject_file(self, environment, tmp_path):
        """Test inject copies file from host to sandbox."""
        source = tmp_path / "source.txt"
        source.write_text("injected content")
        
        environment.inject(str(source), "/workspace/injected.txt")
        
        dest = environment.workspace_dir / "injected.txt"
        assert dest.exists()
        assert dest.read_text() == "injected content"
    
    def test_inject_file_not_found(self, environment, tmp_path):
        """Test inject raises for nonexistent source file."""
        with pytest.raises(FileNotFoundError):
            environment.inject(str(tmp_path / "nonexistent.txt"), "/workspace/dest.txt")
    
    def test_inject_invalid_path(self, environment, tmp_path):
        """Test inject raises for invalid sandbox path."""
        source = tmp_path / "source.txt"
        source.write_text("content")
        
        with pytest.raises(ValueError):
            environment.inject(str(source), "/invalid/path.txt")
