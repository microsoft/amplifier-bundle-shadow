"""Tests for CLI."""

import pytest
from click.testing import CliRunner

from amplifier_bundle_shadow.cli import main


class TestCLI:
    """Tests for CLI commands."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    def test_version(self, runner):
        """Test --version flag."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self, runner):
        """Test --help flag."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Shadow environments" in result.output

    def test_list_empty(self, runner, tmp_path):
        """Test list command with no environments."""
        result = runner.invoke(
            main, ["--shadow-home", str(tmp_path / ".shadow"), "list"]
        )
        assert result.exit_code == 0
        assert "No shadow environments" in result.output

    def test_status_not_found(self, runner, tmp_path):
        """Test status command with nonexistent environment."""
        result = runner.invoke(
            main, ["--shadow-home", str(tmp_path / ".shadow"), "status", "nonexistent"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_destroy_nonexistent(self, runner, tmp_path):
        """Test destroy command with nonexistent environment succeeds (idempotent)."""
        result = runner.invoke(
            main,
            [
                "--shadow-home",
                str(tmp_path / ".shadow"),
                "destroy",
                "nonexistent",
                "--force",
            ],
        )
        # Destroy is idempotent - succeeds even if env doesn't exist
        assert result.exit_code == 0
        assert "Destroyed" in result.output

    def test_destroy_all_empty(self, runner, tmp_path):
        """Test destroy-all command with no environments."""
        result = runner.invoke(
            main, ["--shadow-home", str(tmp_path / ".shadow"), "destroy-all", "--force"]
        )
        assert result.exit_code == 0
        assert "Destroyed 0" in result.output

    def test_exec_not_found(self, runner, tmp_path):
        """Test exec command with nonexistent environment."""
        result = runner.invoke(
            main,
            [
                "--shadow-home",
                str(tmp_path / ".shadow"),
                "exec",
                "nonexistent",
                "echo test",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_diff_not_found(self, runner, tmp_path):
        """Test diff command with nonexistent environment."""
        result = runner.invoke(
            main, ["--shadow-home", str(tmp_path / ".shadow"), "diff", "nonexistent"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_extract_not_found(self, runner, tmp_path):
        """Test extract command with nonexistent environment."""
        result = runner.invoke(
            main,
            [
                "--shadow-home",
                str(tmp_path / ".shadow"),
                "extract",
                "nonexistent",
                "/workspace/file",
                "./file",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_inject_not_found(self, runner, tmp_path):
        """Test inject command with nonexistent environment."""
        result = runner.invoke(
            main,
            [
                "--shadow-home",
                str(tmp_path / ".shadow"),
                "inject",
                "nonexistent",
                "./file",
                "/workspace/file",
            ],
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_create_help(self, runner):
        """Test create --help."""
        result = runner.invoke(main, ["create", "--help"])
        assert result.exit_code == 0
        assert "Create a new shadow environment" in result.output
        assert "--name" in result.output
        assert "--image" in result.output  # Container image option (replaces --mode)
