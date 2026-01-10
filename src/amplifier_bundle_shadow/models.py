"""Core data models for amplifier-shadow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal


class ShadowStatus(str, Enum):
    """Status of a shadow environment."""

    READY = "ready"
    ERROR = "error"
    DESTROYED = "destroyed"


@dataclass
class ExecResult:
    """Result of executing a command in a shadow environment."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def raise_on_error(self, message: str = "Command failed") -> None:
        """Raise an exception if the command failed."""
        if not self.success:
            raise RuntimeError(
                f"{message}: exit_code={self.exit_code}\nstderr: {self.stderr}"
            )


@dataclass
class RepoSpec:
    """Specification for a repository to include in a shadow environment."""

    org: str
    name: str
    branch: str | None = None
    local_path: Path | None = None  # Local source path (for --local option)

    @property
    def full_name(self) -> str:
        """Full name like 'microsoft/amplifier'."""
        return f"{self.org}/{self.name}"

    @property
    def url(self) -> str:
        """GitHub HTTPS URL."""
        return f"https://github.com/{self.org}/{self.name}.git"

    @property
    def is_local(self) -> bool:
        """Whether this is a local source."""
        return self.local_path is not None

    @property
    def display_name(self) -> str:
        """Display name with optional branch and local indicator."""
        base = self.full_name
        if self.branch:
            base = f"{base}@{self.branch}"
        if self.local_path:
            base = f"{base} (local: {self.local_path})"
        return base

    @classmethod
    def parse(cls, spec: str) -> RepoSpec:
        """
        Parse a repository specification string.

        Formats:
        - 'org/repo' -> RepoSpec(org='org', name='repo')
        - 'org/repo@branch' -> RepoSpec(org='org', name='repo', branch='branch')
        - 'https://github.com/org/repo' -> RepoSpec(org='org', name='repo')
        - 'https://github.com/org/repo@branch' -> RepoSpec(org='org', name='repo', branch='branch')
        """
        # Handle full URLs
        url_match = re.match(
            r"https?://github\.com/([^/]+)/([^/@.]+)(?:\.git)?(?:@(.+))?$", spec
        )
        if url_match:
            org, name, branch = url_match.groups()
            return cls(org=org, name=name, branch=branch)

        # Handle org/repo[@branch] format
        simple_match = re.match(r"^([^/]+)/([^/@]+)(?:@(.+))?$", spec)
        if simple_match:
            org, name, branch = simple_match.groups()
            return cls(org=org, name=name, branch=branch)

        raise ValueError(f"Invalid repository specification: {spec}")

    @classmethod
    def parse_local(cls, mapping: str) -> RepoSpec:
        """
        Parse a local source mapping string.

        Format: '/path/to/repo:org/name'

        Examples:
        - '~/repos/amplifier-core:microsoft/amplifier-core'
        - '/home/user/code/myrepo:myorg/myrepo'
        """
        if ":" not in mapping:
            raise ValueError(
                f"Invalid local mapping: {mapping}. "
                f"Expected format: /path/to/repo:org/name"
            )

        path_str, repo_spec = mapping.rsplit(":", 1)

        # Expand and resolve the path
        local_path = Path(path_str).expanduser().resolve()

        # Validate it's a git repository
        if not (local_path / ".git").exists():
            raise ValueError(f"Not a git repository: {local_path}")

        # Parse the repo spec part
        base = cls.parse(repo_spec)
        base.local_path = local_path
        return base


@dataclass
class ChangedFile:
    """A file that was changed in a shadow environment."""

    path: str
    change_type: Literal["added", "modified", "deleted"]
    size: int | None = None


@dataclass
class ShadowInfo:
    """Information about a shadow environment for serialization."""

    shadow_id: str
    repos: list[str]
    mode: str
    status: str
    created_at: str
    shadow_dir: str

    def to_dict(self) -> dict:
        return {
            "shadow_id": self.shadow_id,
            "repos": self.repos,
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "shadow_dir": self.shadow_dir,
        }
