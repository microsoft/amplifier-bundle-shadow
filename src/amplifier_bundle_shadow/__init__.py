"""
Amplifier Shadow - OS-level sandboxed environments for testing Amplifier changes.

This package provides tools for creating isolated shadow environments where your
local working directories (including uncommitted changes) are snapshotted and
served as git dependencies via URL rewriting. Other repos fetch from real GitHub.
"""

__version__ = "0.1.0"

from .models import RepoSpec, ExecResult, ShadowStatus
from .environment import ShadowEnvironment
from .manager import ShadowManager

__all__ = [
    "RepoSpec",
    "ExecResult", 
    "ShadowStatus",
    "ShadowEnvironment",
    "ShadowManager",
]
