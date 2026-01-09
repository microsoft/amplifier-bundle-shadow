"""
Amplifier Shadow - Container-based isolated environments for testing Amplifier changes.

This package provides tools for creating isolated shadow environments where your
local working directories (including uncommitted changes) are snapshotted and
served via an embedded Gitea server. Git URL rewriting redirects your specified
repos to the local Gitea while everything else fetches from real GitHub.
"""

from pathlib import Path

__version__ = "0.1.0"


def get_bundle_path() -> Path:
    """Return the path to the bundle.yaml file for this package."""
    # When installed, bundle.yaml is in the package directory
    return Path(__file__).parent / "bundle.yaml"

from .models import RepoSpec, ExecResult, ShadowStatus, ShadowInfo, ChangedFile
from .environment import ShadowEnvironment
from .manager import ShadowManager
from .container import ContainerRuntime, Mount, ContainerNotFoundError, ContainerRuntimeError
from .snapshot import SnapshotManager, SnapshotResult, SnapshotError
from .gitea import GiteaClient, GiteaError, GiteaTimeoutError

__all__ = [
    # Models
    "RepoSpec",
    "ExecResult",
    "ShadowStatus",
    "ShadowInfo",
    "ChangedFile",
    # Core
    "ShadowEnvironment",
    "ShadowManager",
    # Container
    "ContainerRuntime",
    "Mount",
    "ContainerNotFoundError",
    "ContainerRuntimeError",
    # Snapshot
    "SnapshotManager",
    "SnapshotResult",
    "SnapshotError",
    # Gitea
    "GiteaClient",
    "GiteaError",
    "GiteaTimeoutError",
]
