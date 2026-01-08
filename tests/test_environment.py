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
    def mock_runtime(self):
        """Create a mock container runtime."""
        runtime = MagicMock()
        runtime.exec = AsyncMock(return_value=(0, "output", ""))
        runtime.is_running = AsyncMock(return_value=True)
        runtime.exec_interactive = AsyncMock()
        return runtime
    
    @pytest.fixture
    def temp_shadow_dir(self, tmp_path):
        """Create a temporary shadow directory with structure."""
        shadow_dir = tmp_path / "shadow-test"
        (shadow_dir / "workspace").mkdir(parents=True)
        (shadow_dir / "snapshots" / "microsoft").mkdir(parents=True)
        return shadow_dir
    
    @pytest.fixture
    def environment(self, temp_shadow_dir, mock_runtime):
        """Create a ShadowEnvironment for testing."""
        return ShadowEnvironment(
            shadow_id="test-123",
            container_name="shadow-test-123",
            repos=[RepoSpec(org="microsoft", name="amplifier")],
            shadow_dir=temp_shadow_dir,
            runtime=mock_runtime,
            created_at=datetime.now(),
        )
    
    def test_workspace_dir(self, environment, temp_shadow_dir):
        """Test workspace_dir property."""
        assert environment.workspace_dir == temp_shadow_dir / "workspace"
    
    def test_snapshots_dir(self, environment, temp_shadow_dir):
        """Test snapshots_dir property."""
        assert environment.snapshots_dir == temp_shadow_dir / "snapshots"
    
    def test_to_info(self, environment):
        """Test to_info returns correct data."""
        info = environment.to_info()
        
        assert info.shadow_id == "test-123"
        assert info.mode == "container"
        assert info.status == "ready"
        assert "microsoft/amplifier" in info.repos
    
    @pytest.mark.asyncio
    async def test_exec_calls_runtime(self, environment, mock_runtime):
        """Test exec delegates to runtime."""
        result = await environment.exec("echo test")
        
        mock_runtime.exec.assert_called_once()
        call_args = mock_runtime.exec.call_args
        assert call_args.kwargs["container"] == "shadow-test-123"
        assert call_args.kwargs["command"] == "echo test"
    
    @pytest.mark.asyncio
    async def test_is_running_delegates(self, environment, mock_runtime):
        """Test is_running delegates to runtime."""
        result = await environment.is_running()
        
        mock_runtime.is_running.assert_called_once_with("shadow-test-123")
        assert result is True
    
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
        """Test extract copies file from container workspace to host."""
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
        """Test extract raises for invalid container path."""
        with pytest.raises(ValueError):
            environment.extract("/invalid/path.txt", str(tmp_path / "dest.txt"))
    
    def test_inject_file(self, environment, tmp_path):
        """Test inject copies file from host to container workspace."""
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
        """Test inject raises for invalid container path."""
        source = tmp_path / "source.txt"
        source.write_text("content")
        
        with pytest.raises(ValueError):
            environment.inject(str(source), "/invalid/path.txt")
